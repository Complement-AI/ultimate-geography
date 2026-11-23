"""Fetch enrich sources in bulk when Wikipedia is rate-limiting: lead sections only.

Usage:
    python scripts/enrich_prefetch_leads.py titles.txt

Asks Wikipedia for the plain-text lead section of 20 articles per request
(the API returns several extracts at once only for leads), then reads Wikidata
per article. Writes enrich/_sources/<slug>.json like enrich_sources.py, with
"extract_scope": "lead" and the photo's license left for enrich_photos.py.
Existing files are kept.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import enrich_prefetch as ep  # noqa: E402  (polite GET with Retry-After)
import enrich_sources as es  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "enrich" / "_sources"


def main(path: str) -> None:
    es.get_json = ep.polite
    titles = [t.strip() for t in Path(path).read_text().splitlines() if t.strip()]
    todo = [t for t in titles if not (OUT / f"{es.slugify(t)}.json").exists()]
    print(f"{len(todo)} of {len(titles)} titles to fetch", flush=True)
    for i in range(0, len(todo), 20):
        chunk = todo[i:i + 20]
        data = ep.polite(es.WIKI, {
            "action": "query", "format": "json", "redirects": 1, "titles": "|".join(chunk),
            "prop": "extracts|pageprops", "explaintext": 1, "exintro": 1, "exlimit": 20,
        })["query"]
        alias = {n["from"]: n["to"] for n in data.get("normalized", [])}
        alias.update({r["from"]: r["to"] for r in data.get("redirects", [])})
        pages = {p["title"]: p for p in data["pages"].values()}
        for title in chunk:
            t = title
            while t in alias:
                t = alias[t]
            page = pages.get(t)
            if not page or "missing" in page:
                print(f"  missing: {title}", flush=True)
                continue
            qid = page.get("pageprops", {}).get("wikibase_item")
            facts = es.wikidata(qid) if qid else {}
            image = None
            if facts.get("image"):
                name = urllib.parse.unquote(facts["image"][0].rsplit("/", 1)[-1])
                image = {"file": f"File:{name}", "usable": None,
                         "note": "license not looked up; enrich_photos.py checks it on download"}
            payload = json.dumps({
                "title": page["title"], "extract_scope": "lead",
                "article_url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(page["title"].replace(" ", "_")),
                "wikidata": facts, "image": image, "extract": page.get("extract", ""),
            }, ensure_ascii=False, indent=2)
            for name in {es.slugify(title), es.slugify(page["title"])}:
                (OUT / f"{name}.json").write_text(payload)
            time.sleep(0.3)  # Wikidata is not the bottleneck; stay gentle anyway
        print(f"[{min(i + 20, len(todo))}/{len(todo)}]", flush=True)
        time.sleep(3)


if __name__ == "__main__":
    main(sys.argv[1])
