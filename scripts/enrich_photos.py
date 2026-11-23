"""Download the Commons photos that enrich/ files name, and fill in their licenses.

Usage:
    python scripts/enrich_photos.py

For every enrich/**/*.json whose "photo" names a Commons file, this saves a
Commons thumbnail under enrich/media/ (once; existing files are kept), scaled to at
most 800 px on its long side as an ~80%-quality JPEG with macOS `sips` when it is
available, and writes the
file name, source page, license and credit line back into the JSON. A credit
already present is kept, so a messy Commons author field can be fixed by hand.
Photos under NC, ND or fair-use terms are refused.
"""

from __future__ import annotations

import html
import json
import shutil
import subprocess
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENRICH = REPO / "enrich"
PHOTOS = ENRICH / "media"
COMMONS = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "ultimate-geography-enrichment/0.1 (github.com/Complement-AI/ultimate-geography)"}
WIDTH = 1280      # Commons thumbnail step to fetch
MAX_SIDE = 800    # stored size: keeps ~440 photos near 40 MB


def fetch(url: str, attempts: int = 6) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as err:
            if err.code not in (429, 503) or attempt == attempts - 1:
                raise
            time.sleep(min(int(err.headers.get("Retry-After") or 0) or 5 * 2 ** attempt, 120))
    raise RuntimeError("unreachable")


def plain(meta: dict, key: str) -> str:
    raw = meta.get(key, {}).get("value", "")
    text = html.unescape(re.sub(r"<[^>]+>", "", raw))
    return re.sub(r"\s+", " ", text).strip()


def commons_info(title: str) -> dict:
    params = {
        "action": "query", "format": "json", "titles": title,
        "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": WIDTH,
    }
    data = json.loads(fetch(COMMONS + "?" + urllib.parse.urlencode(params)))
    page = next(iter(data["query"]["pages"].values()))
    if not page.get("imageinfo"):
        return None
    return page["imageinfo"][0]


def shrink(path: Path) -> None:
    """Scale to MAX_SIDE and re-encode as JPEG (macOS sips; left as is elsewhere)."""
    if not shutil.which("sips"):
        return
    subprocess.run(["sips", "-Z", str(MAX_SIDE), "-s", "format", "jpeg", "-s", "formatOptions", "80",
                    str(path), "--out", str(path)], check=True, capture_output=True)


def main() -> None:
    PHOTOS.mkdir(parents=True, exist_ok=True)
    for path in sorted(ENRICH.glob("*/*.json")):
        card = json.loads(path.read_text())
        photo = card.get("photo")
        if not photo or not photo.get("commons"):
            continue
        # Named after the Commons file, so a photo used by several cards is stored once
        # and a capital's city photo never collides with its country's landscape.
        stem = re.sub(r"[^a-z0-9]+", "-", photo["commons"].removeprefix("File:").rsplit(".", 1)[0].lower()).strip("-")[:60]
        photo.setdefault("file", f"cx-photo-{stem}.jpg")
        target = PHOTOS / photo["file"]
        if not target.exists() or not photo.get("license"):
            info = commons_info(photo["commons"])
            meta = (info or {}).get("extmetadata", {})
            license_name = plain(meta, "LicenseShortName")
            if not info or not license_name or re.search(r"\bNC\b|\bND\b|non-?commercial|fair use", license_name, re.I):
                # No usable file or license: drop the photo rather than stop the run.
                print(f"{path.relative_to(REPO)}: dropped {photo['commons']} ({license_name or 'no file/license'})")
                card["photo"] = None
                path.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n")
                continue
            author = plain(meta, "Artist")[:80] or "Unknown author"
            # Some licenses (e.g. ESA's "Attribution") name the exact credit to show.
            required = plain(meta, "Attribution")
            photo["license"] = license_name
            photo["source"] = info["descriptionurl"]
            photo.setdefault("credit", f"{required}, {author}, via Wikimedia Commons" if required
                             else f"{author}, {license_name}, via Wikimedia Commons")
            if not target.exists():
                target.write_bytes(fetch(info.get("thumburl") or info["url"]))
                shrink(target)
                time.sleep(1)
        path.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n")
        print(f"{path.relative_to(REPO)} -> {target.relative_to(REPO)} ({photo['license']})")


if __name__ == "__main__":
    main()
