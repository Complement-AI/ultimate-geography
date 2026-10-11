"""Convert Ultimate Geography (anki-geo/ultimate-geography) into a Complement deck repo.

Usage:
    python scripts/convert.py /path/to/ultimate-geography-checkout

Reads the upstream source CSVs (src/data/*.csv) and media, then rewrites
notes/, media/, and SOURCES.csv in this repo. Safe to re-run on a newer
upstream checkout: note ids are derived from upstream's stable per-note guid
plus the card direction, so edits arrive as updates rather than new cards.

Upstream builds several cards per note from one Anki note type. Complement's
GitHub pipeline makes one card per non-cloze note, so each upstream card
template becomes its own Basic note here:

    map      -> "What is highlighted?"   (every entity)
    capital  -> country to capital       (entities with a capital)
    country  -> capital to country       (entities with a capital)
    flag     -> flag to country          (entities with a flag)
"""

from __future__ import annotations

import csv
import re
import shutil
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/anki-geo/ultimate-geography")

# First matching tag decides the subdeck folder.
SUBDECKS = [
    ("UG::Continents", "Continents"),
    ("UG::Oceans+Seas", "Oceans and Seas"),
    ("UG::Europe", "Europe"),
    ("UG::Asia", "Asia"),
    ("UG::Africa", "Africa"),
    ("UG::North_America", "North America"),
    ("UG::South_America", "South America"),
    ("UG::Oceania", "Oceania"),
]

IMG_SRC = re.compile(r'src="([^"]+)"')


def read_column(data_dir: Path, name: str, column: str) -> dict[str, str]:
    with open(data_dir / f"{name}.csv", newline="", encoding="utf-8") as f:
        return {row["country"]: (row.get(column) or "").strip() for row in csv.DictReader(f)}


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def image_file(cell: str) -> str | None:
    match = IMG_SRC.search(cell or "")
    return match.group(1) if match else None


def subdeck_for(tags: list[str]) -> str:
    for tag, folder in SUBDECKS:
        if tag in tags:
            return folder
    return "Other"


def toml_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_note(path: Path, note_id: str, tags: list[str], sections: list[tuple[str, str]]) -> None:
    lines = [
        "---",
        f"id    = {toml_str(note_id)}",
        'model = "Basic"',
        "tags  = [" + ", ".join(toml_str(t) for t in tags) + "]",
        "---",
        "",
    ]
    for heading, body in sections:
        if body:
            lines += [f"## {heading}", "", body, ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def extra_block(*parts: str) -> str:
    return "<br><br>".join(p for p in parts if p)


def main(upstream: Path) -> None:
    data = upstream / "src" / "data"
    media_src = upstream / "src" / "media"

    guid = read_column(data, "guid", "guid")
    capital = read_column(data, "capital", "capital")
    capital_hint = read_column(data, "capital_hint", "capital hint")
    capital_info = read_column(data, "capital_info", "capital info")
    country_info = read_column(data, "country_info", "country info")
    flag_similarity = read_column(data, "flag_similarity", "flag similarity")

    notes_dir = REPO / "notes"
    media_dir = REPO / "media"
    for d in (notes_dir, media_dir):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)

    used_media: set[str] = set()
    counts: dict[str, int] = {}

    with open(data / "main.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    for row in rows:
        name = row["country"].strip()
        tags_upstream = [t.strip() for t in row["tags"].split(",") if t.strip()]
        tags = [t.removeprefix("UG::").lower().replace("+", "-and-") for t in tags_upstream]
        folder = notes_dir / subdeck_for(tags_upstream)
        folder.mkdir(exist_ok=True)
        slug = slugify(name)
        base_guid = guid[name]

        def media_md(filename: str, alt: str) -> str:
            used_media.add(filename)
            return f"![{alt}](../../media/{filename})"

        def emit(direction: str, sections: list[tuple[str, str]]) -> None:
            note_id = str(uuid.uuid5(ID_NAMESPACE, f"{base_guid}:{direction}"))
            write_note(folder / f"{slug}--{direction}.md", note_id, tags + [direction], sections)
            counts[direction] = counts.get(direction, 0) + 1

        info = country_info.get(name, "")
        map_file = image_file(row["map"])
        flag_file = image_file(row["flag"])
        cap = capital.get(name, "")

        if map_file:
            emit("map", [
                ("Front", "What is highlighted on this map?\n\n" + media_md(map_file, "Map")),
                ("Back", f"<b>{name}</b>"),
                ("Extra", info),
            ])
        if cap:
            hint = capital_hint.get(name, "")
            emit("capital", [
                ("Front", f"What is the capital of <b>{name}</b>?" + (f"\n\n<i>{hint}</i>" if hint else "")),
                ("Back", f"<b>{cap}</b>"),
                ("Extra", extra_block(capital_info.get(name, ""), info)),
            ])
            emit("country", [
                ("Front", f"<b>{cap}</b> is the capital of which country or territory?"),
                ("Back", f"<b>{name}</b>"),
                ("Extra", extra_block(info, capital_info.get(name, ""))),
            ])
        if flag_file:
            similar = flag_similarity.get(name, "")
            emit("flag", [
                ("Front", "Whose flag is this?\n\n" + media_md(flag_file, "Flag")),
                ("Back", f"<b>{name}</b>"),
                ("Extra", extra_block(f"Similar flags: {similar}" if similar else "", info)),
            ])

    for filename in sorted(used_media):
        kind = "flags" if filename.startswith("ug-flag-") else "maps"
        shutil.copy2(media_src / kind / filename, media_dir / filename)

    with open(upstream / "sources.csv", newline="", encoding="utf-8") as src, open(
        REPO / "SOURCES.csv", "w", newline="", encoding="utf-8"
    ) as dst:
        reader = csv.reader(src)
        writer = csv.writer(dst, lineterminator="\n")
        header = next(reader)
        writer.writerow([h.strip() for h in header])
        # Upstream occasionally lists a file without its extension.
        by_stem = {Path(f).stem: f for f in used_media}
        credited: set[str] = set()
        for record in reader:
            if not record:
                continue
            listed = record[0].strip()
            filename = listed if listed in used_media else by_stem.get(listed)
            if filename:
                credited.add(filename)
                writer.writerow([filename] + [c.strip() for c in record[1:]])

    uncredited = used_media - credited
    if uncredited:
        sys.exit(f"media without a license entry in sources.csv: {sorted(uncredited)}")

    total = sum(counts.values())
    print(f"{len(rows)} entities -> {total} notes {counts}; {len(used_media)} media files")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]).resolve())
