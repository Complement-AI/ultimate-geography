# Enriching cards

Upstream's cards test a name and nothing else. Complement adds a short answer-side
block to each card: a photo where one helps, one or two facts, and one "worth
knowing" paragraph. No new cards: everything goes in Extra, under the answer.

The ten files under `enrich/` are the reference examples. Match their length and tone.

Every card also gets a **locator map** first in Extra: the country highlighted,
its capital marked, neighbours labelled. These need no writing:
`python scripts/locator_maps.py` draws all of them from Natural Earth (public
domain) into `enrich/maps/`, and the converter adds them. Natural Earth has no
shape for England, Scotland, Wales, Northern Ireland, Abkhazia, South Ossetia,
Transnistria or the EU; those cards go without a map for now.

## Files

One JSON file per card, mirroring `notes/`:

```
notes/North America/mexico--capital.md   <- generated, never edit
enrich/North America/mexico--capital.json <- written here
enrich/media/cx-photo-mexico.jpg          <- downloaded by scripts/enrich_photos.py
```

```json
{
  "photo": {"commons": "File:Exact Commons name.jpg", "alt": "What the photo shows"},
  "facts": ["About 9.2 million people in the city itself (2020 census)",
            "2,240 m up, in the Valley of Mexico"],
  "worth_knowing": "One or two sentences.",
  "sources": ["https://en.wikipedia.org/wiki/Mexico_City", "https://www.wikidata.org/wiki/Q1489"],
  "written_by": "<model id>",
  "checked_by": null
}
```

`photo` may be `null`. `enrich_photos.py` adds `file`, `source`, `license` and
`credit`; don't write those yourself. Set `credit` by hand only when Commons'
author field is a mess (see Mongolia).

## What each card gets

| Card | Article to read | Photo | Facts | Worth knowing |
| --- | --- | --- | --- | --- |
| `--capital` (country → capital) | the city | the city (its Wikidata image) | population with year; setting (elevation, coast, river) | the city: how it got its name, why it is the capital, what it is known for |
| `--country` (capital → country) | the country | a landscape or the country from orbit, not a map or flag | population with year and area, or neighbours, or highest point | the country: one defining trait |
| `--flag` | "Flag of X" | none (the flag is on the card) | adoption date | what the colours and emblems mean, or what makes the flag unusual |
| `--map` | the country, its Geography section | a landscape that shows the terrain | neighbours; population and area | the shape or terrain you can see on the map |

Each direction of the same country should teach something different. Don't
repeat the capital card's fact on the country card.

## Steps for one card

1. `python scripts/enrich_sources.py "<Wikipedia title>" --out enrich/_sources`
   saves the article text, Wikidata facts and the article's photo with its license.
2. Write the JSON **only from that file**. Every number must appear in its
   `wikidata` block or `extract`, and every claim in `worth_knowing` must match a
   sentence in `extract`. If you know something that isn't in the file, leave it
   out. (Wikidata dates Mexico City from 1521, the Spanish founding; the article
   says Tenochtitlan was built around 1325. Use what the article says.)
3. `python scripts/enrich_photos.py` downloads photos and records their licenses.
   It refuses NC, ND and fair-use files; pick another or use `null`.
4. `python scripts/convert.py /path/to/upstream-checkout` at `UPSTREAM_COMMIT`. It
   fails on an enrich file that matches no note.
5. A second model checks each card against the same sources file and sets
   `checked_by`. A card it can't verify is removed, not softened.

## Photos

- At most two photos per place: the capital's city photo on its `--capital` card,
  and one landscape for the country, used by both its `--country` and `--map` cards
  (write the same `commons` name in both files; it is stored once).
- Take the photo from the sources file's `image` (the article's Wikidata picture)
  when `usable` is true and it shows the place, not a flag, coat of arms, map,
  locator, seal or portrait. Otherwise pick a well-known Commons photo that the
  article itself uses, or set `photo` to `null`. Never guess a file name: it must
  appear in the sources file or the article.
- Flags, oceans, seas and continents: `photo` is `null` unless a striking,
  clearly-licensed photo is in the sources file.

## Working in batches

Several writers may run at once, one batch of places each.

- Write only the `enrich/<Subdeck>/<slug>--<direction>.json` files of your batch.
  Don't touch other files, don't run `enrich_photos.py` or `convert.py` (they are
  run once at the end), and don't commit.
- Fetch sources with `enrich_sources.py` into `enrich/_sources/` and wait a second
  between fetches; it backs off on Wikipedia's 429s.
- Read sources with targeted searches (grep the `extract` for the sentences you
  need, read the `wikidata` block), not whole 30 KB extracts.
- `written_by` is your model id; leave `checked_by` null. A second pass checks
  every file against the same sources and sets it.
- Skip a card rather than pad it: no file is fine.

## Style

- Facts: short noun phrases, no full stop, at most two. Round numbers ("about
  474,000", "about 3.4 million") and give the year of any population.
- Worth knowing: at most two sentences, about 35 words. Plain and specific; no
  "Did you know", no exclamation marks, no "fascinating" or "unique" unless the
  source says "only".
- Metric units; add nothing in brackets that the source doesn't give.
- No "·" separators. Join facts with `<br>` (the converter does this).
- Disputed places (Taiwan, Kosovo, Western Sahara, Palestine, Crimea): state
  only what is undisputed, in the article's own neutral wording, or skip
  `worth_knowing`.
- Small territories with thin articles: facts only is fine. Never pad.
- `alt` describes the picture in plain words, without giving away a different card's answer.
