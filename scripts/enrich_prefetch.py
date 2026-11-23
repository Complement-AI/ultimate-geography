"""Fetch many enrich sources serially and politely (one Wikipedia request at a time).

Usage:
    python scripts/enrich_prefetch.py titles.txt [--delay 1.5]

Writes enrich/_sources/<slug>.json in the same shape as enrich_sources.py, but
skips the Commons license lookup (enrich_photos.py checks licenses when it
downloads), so the photo's `usable` is null. Waits out HTTP 429s using the
server's Retry-After. Never run several copies at once: parallel fetching is
what gets this machine rate-limited.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import enrich_sources as es  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "enrich" / "_sources"


def polite(url: str, params: dict) -> dict:
    """GET with patience: honour Retry-After, back off up to 5 minutes, never give up early."""
    wait = 5
    while True:
        req = es.urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers=es.UA)
        try:
            with es.urllib.request.urlopen(req, timeout=90) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as err:
            if err.code not in (429, 500, 502, 503, 504):
                raise
            pause = int(err.headers.get("Retry-After") or 0) or wait
            print(f"  {err.code}, waiting {pause}s", flush=True)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
            pause = wait
            print(f"  network error ({err}), waiting {pause}s", flush=True)
        time.sleep(min(pause, 300))
        wait = min(wait * 2, 300)


def main(path: str, delay: float) -> None:
    es.get_json = polite
    titles = [t.strip() for t in Path(path).read_text().splitlines() if t.strip()]
    OUT.mkdir(parents=True, exist_ok=True)
    for i, title in enumerate(titles, 1):
        target = OUT / f"{es.slugify(title)}.json"
        if target.exists():
            continue
        try:
            resolved, qid, extract = es.wiki_page(title)
        except SystemExit as err:
            print(f"[{i}/{len(titles)}] {title}: {err}", flush=True)
            continue
        facts = es.wikidata(qid) if qid else {}
        image = None
        if facts.get("image"):
            name = urllib.parse.unquote(facts["image"][0].rsplit("/", 1)[-1])
            image = {"file": f"File:{name}", "usable": None,
                     "note": "license not looked up; enrich_photos.py checks it on download"}
        out = OUT / f"{es.slugify(resolved)}.json"
        payload = json.dumps({
            "title": resolved,
            "article_url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(resolved.replace(" ", "_")),
            "wikidata": facts, "image": image, "extract": extract,
        }, ensure_ascii=False, indent=2)
        out.write_text(payload)
        if out != target:  # redirected title: keep the requested name too, so writers find it
            target.write_text(payload)
        print(f"[{i}/{len(titles)}] {title} -> {out.name}", flush=True)
        time.sleep(delay)


if __name__ == "__main__":
    args = sys.argv[1:]
    delay = float(args[args.index("--delay") + 1]) if "--delay" in args else 1.5
    main(args[0], delay)
