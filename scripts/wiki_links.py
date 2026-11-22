"""Find the English Wikipedia article for every entity, capital and flag.

Usage:
    python scripts/wiki_links.py

Writes enrich/wiki_links.json: {slug: {"entity": url, "capital": [url, ...], "flag": url}}
(keys only where an article was found). The converter turns these into a line
of links at the end of each card's Extra.

Countries are resolved through Natural Earth's Wikidata id, never by name:
names mislead ("Ireland" is the island, "Georgia" a disambiguation page).
Capitals are the country's Wikidata capitals (P36) whose label matches the
deck's capital; flags are the country's flag item (P163). Everything else
(oceans, seas, continents, regions) is looked up by name, and disambiguation
pages are rejected. Unresolved names are printed for a person to check, and
MANUAL fills them.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from locator_maps import FILES, entities, load, norm  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "enrich" / "wiki_links.json"
UA = {"User-Agent": "ultimate-geography-enrichment/0.1 (github.com/Complement-AI/ultimate-geography)"}
WIKI = "https://en.wikipedia.org/wiki/"

# Deck name -> article title, where lookup by name fails or picks the wrong page.
MANUAL: dict[str, str] = {
    "Palestine": "State of Palestine",  # Natural Earth's id is the region
    "Bougainville": "Autonomous Region of Bougainville",
    "Jeju": "Jeju Province",
    "St. John's": "St. John's, Antigua and Barbuda",
}


def request(url: str, data: dict | None = None, attempts: int = 6) -> dict:
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=UA)
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as err:
            if err.code not in (429, 503) or attempt == attempts - 1:
                raise
            time.sleep(min(int(err.headers.get("Retry-After") or 0) or 5 * 2 ** attempt, 120))
    raise RuntimeError("unreachable")


def url(title: str) -> str:
    return WIKI + urllib.parse.quote(title.replace(" ", "_"), safe="_(),'-")


def wikidata_links(qids: list[str]) -> dict[str, dict]:
    """QID -> {"entity": title, "capitals": [(label, title)], "flag": title}."""
    query = f"""
    SELECT ?c ?article ?cap ?capLabel ?capArticle ?flagArticle WHERE {{
      VALUES ?c {{ {' '.join('wd:' + q for q in qids)} }}
      OPTIONAL {{ ?article schema:about ?c ; schema:isPartOf <https://en.wikipedia.org/> . }}
      OPTIONAL {{ ?c wdt:P36 ?cap .
                 OPTIONAL {{ ?capArticle schema:about ?cap ; schema:isPartOf <https://en.wikipedia.org/> . }} }}
      OPTIONAL {{ ?c wdt:P163 ?flag .
                 ?flagArticle schema:about ?flag ; schema:isPartOf <https://en.wikipedia.org/> . }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}"""
    rows = request("https://query.wikidata.org/sparql", {"query": query, "format": "json"})["results"]["bindings"]
    out: dict[str, dict] = {}

    def title(row: dict, key: str) -> str | None:
        value = row.get(key, {}).get("value")
        return urllib.parse.unquote(value.rsplit("/wiki/", 1)[1]).replace("_", " ") if value else None

    for r in rows:
        qid = r["c"]["value"].rsplit("/", 1)[1]
        o = out.setdefault(qid, {"capitals": []})
        o["entity"] = o.get("entity") or title(r, "article")
        if r.get("capArticle"):
            cap = (r.get("capLabel", {}).get("value", ""), title(r, "capArticle"))
            if cap not in o["capitals"]:
                o["capitals"].append(cap)
        if r.get("flagArticle") and not o.get("flag"):
            o["flag"] = title(r, "flagArticle")
    return out


def by_name(names: list[str]) -> dict[str, str]:
    """Look titles up on Wikipedia, following redirects, rejecting disambiguation pages."""
    found: dict[str, str] = {}
    for i in range(0, len(names), 50):
        chunk = names[i:i + 50]
        data = request("https://en.wikipedia.org/w/api.php", {
            "action": "query", "format": "json", "redirects": 1, "prop": "pageprops",
            "titles": "|".join(chunk),
        })["query"]
        alias = {n["from"]: n["to"] for n in data.get("normalized", [])}
        alias.update({r["from"]: r["to"] for r in data.get("redirects", [])})
        pages = {p["title"]: p for p in data["pages"].values()}
        for name in chunk:
            t = name
            while t in alias:
                t = alias[t]
            page = pages.get(t)
            if page and "missing" not in page and "disambiguation" not in page.get("pageprops", {}):
                found[name] = t
        time.sleep(1)
    return found


def main() -> None:
    countries = load(FILES[0])
    index: dict[str, str] = {}
    for f in countries:
        p = f["properties"]
        for k in ("NAME", "NAME_LONG", "ADMIN", "NAME_EN", "FORMAL_EN", "NAME_SORT", "BRK_NAME", "GEOUNIT", "SUBUNIT"):
            if p.get(k) and p.get("WIKIDATAID"):
                index.setdefault(norm(p[k]), p["WIKIDATAID"])

    ents = entities()
    qid_of = {slug: index.get(norm(e.get("name", ""))) for slug, e in ents.items()}
    qids = sorted({q for q in qid_of.values() if q})
    wd: dict[str, dict] = {}
    for i in range(0, len(qids), 100):
        wd.update(wikidata_links(qids[i:i + 100]))
        time.sleep(1)

    links: dict[str, dict] = {}
    need_names: dict[str, list[tuple[str, str]]] = {}
    for slug, e in ents.items():
        name, cap = e.get("name", ""), e.get("capital")
        info = wd.get(qid_of[slug] or "", {})
        entry: dict[str, str] = {}
        if name in MANUAL:
            entry["entity"] = url(MANUAL[name])
        elif info.get("entity"):
            entry["entity"] = url(info["entity"])
        else:
            need_names.setdefault(name, []).append((slug, "entity"))
        if info.get("flag") and "flag" in e["directions"]:
            entry["flag"] = url(info["flag"])
        if "flag" in e["directions"] and "flag" not in entry:
            for guess in (f"Flag of {name}", f"Flag of the {name}"):
                need_names.setdefault(guess, []).append((slug, "flag"))
        labels = {norm(label) for label, _ in info.get("capitals", [])}
        whole = cap and (norm(cap) in labels or cap in MANUAL)  # "Washington, D.C." is one name
        for part in ([cap] if whole else re.split(r",\s*|\s+and\s+", cap) if cap else []):
            match = next((t for label, t in info.get("capitals", []) if norm(label) == norm(part)), None)
            if part in MANUAL:
                entry.setdefault("capital", []).append(url(MANUAL[part]))
            elif match:
                entry.setdefault("capital", []).append(url(match))
            else:
                need_names.setdefault(part, []).append((slug, "capital"))
        links[slug] = entry

    found = by_name(sorted(need_names))
    unresolved = []
    for name, uses in need_names.items():
        for slug, key in uses:
            if name in found and key == "capital":
                links[slug].setdefault("capital", []).append(url(found[name]))
            elif name in found:
                links[slug].setdefault(key, url(found[name]))
            elif not name.startswith("Flag of"):
                unresolved.append(f"{name} ({slug} {key})")
    for slug, e in ents.items():
        if "flag" in e["directions"] and "flag" not in links[slug]:
            unresolved.append(f"flag of {e.get('name')} ({slug})")

    OUT.write_text(json.dumps(dict(sorted(links.items())), ensure_ascii=False, indent=1) + "\n")
    print(f"{sum(len(v) for v in links.values())} links for {len(links)} entities -> {OUT.relative_to(REPO)}")
    print(f"by name: {len(found)} of {len(need_names)}: " + ", ".join(f"{k} -> {v}" for k, v in sorted(found.items())))
    if unresolved:
        print("unresolved (add to MANUAL): " + "; ".join(sorted(unresolved)))


if __name__ == "__main__":
    main()
