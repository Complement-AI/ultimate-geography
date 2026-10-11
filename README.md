# Ultimate Geography for Complement

The [Ultimate Geography](https://github.com/anki-geo/ultimate-geography) Anki
deck, converted for [Complement](https://complementai.app)'s Deck Cloud.

**982 cards**: map, capital and flag cards for 205 sovereign states, plus
territories, oceans, seas and continents.

| Subdeck | Notes |
| --- | --- |
| Europe | 242 |
| Africa | 228 |
| Asia | 197 |
| North America | 122 |
| Oceania | 84 |
| Oceans and Seas | 52 |
| South America | 50 |
| Continents | 7 |

## How this repo is built

Everything under `notes/`, `media/` and `SOURCES.csv` is generated. Don't edit
it by hand; fix content upstream, then re-run the converter:

```sh
git clone https://github.com/anki-geo/ultimate-geography /tmp/ug
python scripts/convert.py /tmp/ug
git -C /tmp/ug rev-parse HEAD > UPSTREAM_COMMIT
```

Upstream builds four cards per Anki note from one note type. Complement's
GitHub pipeline makes one card per non-cloze note, so each card direction
becomes its own Basic note (`<entity>--map.md`, `--capital.md`, `--country.md`,
`--flag.md`). Note ids are UUIDv5 values derived from upstream's stable guid
plus the direction, so re-running the converter updates cards in place.

`UPSTREAM_COMMIT` records the upstream commit this conversion came from.
English only for now; upstream also ships 15 other languages.

## License

Card text is public domain under the [Unlicense](LICENSE.md), as upstream
releases it. Images are **not** public domain: every flag and map keeps the
license of its source, mostly Wikimedia Commons (CC BY-SA, CC BY, CC0 or public
domain). [`SOURCES.csv`](SOURCES.csv) lists each file's source URL, license and
modifications.

Credit for the content belongs to the
[Ultimate Geography contributors](https://github.com/anki-geo/ultimate-geography/graphs/contributors).
Report content errors upstream.

## Sync to Complement

Pushes to `main` trigger Complement's webhook, which diffs the repo and
publishes a new version of the shared deck. The format is described in
[Complement-AI/deck-starter](https://github.com/Complement-AI/deck-starter).
