"""Fetch the source material a writer needs to enrich one card.

Usage:
    python scripts/enrich_sources.py "Mexico City" [--out DIR]

Takes an English Wikipedia article title and writes <out>/<slug>.json with:
  - wikidata: QID, population (latest), area, elevation, inception,
    neighbours (P47), official languages, currency, highest point
  - image: the Wikidata P18 picture with its Commons license, author and
    credit line (None when the article has none)
  - extract: the article's plain text (lead plus body, truncated)

Writers (people or models) must take every fact on a card from this file,
not from memory. See ENRICHMENT.md.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UA = {"User-Agent": "ultimate-geography-enrichment/0.1 (github.com/Complement-AI/ultimate-geography)"}
WIKI = "https://en.wikipedia.org/w/api.php"
WD_SPARQL = "https://query.wikidata.org/sparql"
COMMONS = "https://commons.wikimedia.org/w/api.php"
EXTRACT_CHARS = 30_000


def get_json(url: str, params: dict, attempts: int = 6) -> dict:
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers=UA)
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as err:
            if err.code not in (429, 503) or attempt == attempts - 1:
                raise
            wait = int(err.headers.get("Retry-After") or 0) or 5 * 2 ** attempt
            time.sleep(min(wait, 120))
    raise RuntimeError("unreachable")


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def wiki_page(title: str) -> tuple[str, str, str]:
    data = get_json(WIKI, {
        "action": "query", "format": "json", "redirects": 1, "titles": title,
        "prop": "extracts|pageprops|info", "explaintext": 1, "inprop": "url",
    })
    page = next(iter(data["query"]["pages"].values()))
    if "missing" in page:
        sys.exit(f"No Wikipedia article titled {title!r}")
    qid = page.get("pageprops", {}).get("wikibase_item")
    return page["title"], qid, page.get("extract", "")[:EXTRACT_CHARS]


def wikidata(qid: str) -> dict:
    query = f"""
    SELECT ?prop ?valLabel ?val ?time WHERE {{
      {{ wd:{qid} p:P1082 ?st . ?st ps:P1082 ?val . OPTIONAL {{ ?st pq:P585 ?time }} BIND("population" AS ?prop) }}
      UNION {{ wd:{qid} wdt:P2046 ?val . BIND("area_km2" AS ?prop) }}
      UNION {{ wd:{qid} wdt:P2044 ?val . BIND("elevation_m" AS ?prop) }}
      UNION {{ wd:{qid} wdt:P571 ?val . BIND("inception" AS ?prop) }}
      UNION {{ wd:{qid} wdt:P47 ?val . ?val wdt:P31/wdt:P279* wd:Q6256 . BIND("neighbours" AS ?prop) }}
      UNION {{ wd:{qid} wdt:P37 ?val . BIND("official_languages" AS ?prop) }}
      UNION {{ wd:{qid} wdt:P38 ?val . BIND("currency" AS ?prop) }}
      UNION {{ wd:{qid} wdt:P610 ?val . BIND("highest_point" AS ?prop) }}
      UNION {{ wd:{qid} wdt:P18 ?val . BIND("image" AS ?prop) }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}"""
    rows = get_json(WD_SPARQL, {"query": query, "format": "json"})["results"]["bindings"]
    out: dict = {"qid": qid}
    pops = []
    for r in rows:
        prop = r["prop"]["value"]
        label = r.get("valLabel", {}).get("value") or r["val"]["value"]
        if prop == "population":
            pops.append((r.get("time", {}).get("value", ""), label))
        elif prop in ("neighbours", "official_languages", "currency", "image"):
            out.setdefault(prop, [])
            value = r["val"]["value"] if prop == "image" else label
            if value not in out[prop]:
                out[prop].append(value)
        else:
            out.setdefault(prop, label)
    if pops:
        year, value = max(pops)
        out["population"] = {"value": value, "as_of": year[:10] or None}
    return out


def commons_image(file_url: str) -> dict | None:
    name = urllib.parse.unquote(file_url.rsplit("/", 1)[-1])
    data = get_json(COMMONS, {
        "action": "query", "format": "json", "titles": f"File:{name}",
        "prop": "imageinfo", "iiprop": "url|extmetadata|size", "iiurlwidth": 1280,
    })
    page = next(iter(data["query"]["pages"].values()))
    info = (page.get("imageinfo") or [None])[0]
    if not info:
        return None
    meta = info.get("extmetadata", {})

    def plain(key: str) -> str:
        raw = meta.get(key, {}).get("value", "")
        return html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()

    author = plain("Artist") or "Unknown author"
    license_name = plain("LicenseShortName")
    return {
        "file": f"File:{name}",
        "page_url": info.get("descriptionurl"),
        "thumb_url": info.get("thumburl"),
        "width": info.get("width"),
        "height": info.get("height"),
        "author": author,
        "license": license_name,
        "license_url": plain("LicenseUrl") or None,
        "description": plain("ImageDescription")[:400],
        "credit": f"{author}, {license_name}, via Wikimedia Commons",
        "usable": not re.search(r"\bNC\b|\bND\b|non-?commercial|fair use", license_name, re.I),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("title")
    parser.add_argument("--out", default="enrich/_sources")
    args = parser.parse_args()

    title, qid, extract = wiki_page(args.title)
    facts = wikidata(qid) if qid else {}
    image = None
    if facts.get("image"):
        image = commons_image(facts["image"][0])

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{slugify(title)}.json"
    path.write_text(json.dumps({
        "title": title,
        "article_url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")),
        "wikidata": facts,
        "image": image,
        "extract": extract,
    }, ensure_ascii=False, indent=2))
    print(path)


if __name__ == "__main__":
    main()
