"""Check enrich/ card files against ENRICHMENT.md's format rules.

Usage:
    python scripts/enrich_check.py [Subdeck/slug--direction ...]   # default: every file

Checks shape and style only (facts are checked against sources by a second
reader): known keys, a matching note, at most two short facts, a worth-knowing
paragraph of at most ~45 words, no "·", no "!", no "Did you know", photo fields
well-formed, sources listed. Exits non-zero when anything fails.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENRICH = REPO / "enrich"
SKIP_DIRS = {"maps", "media", "_cache", "_sources"}
KEYS = {"photo", "facts", "worth_knowing", "sources", "written_by", "checked_by"}
PHOTO_KEYS = {"commons", "alt", "credit", "file", "source", "license"}


def problems(path: Path) -> list[str]:
    out = []
    try:
        card = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        return [f"invalid JSON: {err}"]
    rel = path.relative_to(ENRICH).with_suffix("")
    if not (REPO / "notes" / f"{rel}.md").exists():
        out.append("no matching note in notes/")
    if extra := set(card) - KEYS:
        out.append(f"unknown keys {sorted(extra)}")
    facts = card.get("facts") or []
    if not isinstance(facts, list) or len(facts) > 2:
        out.append("facts must be a list of at most 2")
    for f in facts if isinstance(facts, list) else []:
        if len(f) > 110 or (f.endswith(".") and not re.search(r"\b[A-Z]\.[A-Z]\.$|\b(?:St|Mt|Jr|Inc|Co)\.$", f)):
            out.append(f"fact too long or ends with a full stop: {f!r}")
    wk = card.get("worth_knowing") or ""
    if len(wk.split()) > 45:
        out.append(f"worth_knowing has {len(wk.split())} words (max ~45)")
    text = " ".join(facts if isinstance(facts, list) else []) + " " + wk
    for bad, why in (("·", "middot"), ("!", "exclamation mark"), ("did you know", "'Did you know'")):
        if bad in text.lower():
            out.append(f"contains {why}")
    if not facts and not wk:
        out.append("empty: no facts and no worth_knowing (delete the file instead)")
    photo = card.get("photo")
    if photo is not None:
        if not isinstance(photo, dict) or not str(photo.get("commons", "")).startswith("File:") or not photo.get("alt"):
            out.append("photo needs commons ('File:…') and alt, or null")
        elif extra := set(photo) - PHOTO_KEYS:
            out.append(f"unknown photo keys {sorted(extra)}")
    if not card.get("sources"):
        out.append("sources missing")
    if not card.get("written_by"):
        out.append("written_by missing")
    return out


def main(args: list[str]) -> None:
    if args:
        paths = [ENRICH / f"{a}.json" for a in args]
    else:
        paths = sorted(p for p in ENRICH.glob("*/*.json") if p.parent.name not in SKIP_DIRS)
    bad = 0
    for path in paths:
        if not path.exists():
            continue
        for p in problems(path):
            bad += 1
            print(f"{path.relative_to(ENRICH)}: {p}")
    print(f"{len(paths)} files checked, {bad} problems")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
