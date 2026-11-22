"""Draw a locator map for each country: the country highlighted, its capital
marked and named, and the countries around it labelled.

Usage:
    python scripts/locator_maps.py                 # every entity with a capital, country or flag card
    python scripts/locator_maps.py mexico benin    # just these slugs

Writes enrich/maps/cx-locator-<slug>.svg, and enrich/maps/index.json with each
map's country code, capital point and label, which the converter uses to wrap
the static map in a live `cmp-map` block (the static map stays as its fallback). Data is Natural Earth 1:10m
(public domain), downloaded once into enrich/_cache/. Pure Python, no
dependencies. The projection is orthographic, centred on the country, so small
countries get a regional view and very large ones a globe.

Entities Natural Earth doesn't have (e.g. England, Abkhazia) are listed and
skipped; add them to NAME_OVERRIDES if a match exists under another name.
"""

from __future__ import annotations

import json
import math
import re
import sys
import urllib.request
from html import escape
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CACHE = REPO / "enrich" / "_cache"
OUT = REPO / "enrich" / "maps"
NE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
FILES = ["ne_10m_admin_0_countries", "ne_10m_populated_places_simple", "ne_110m_land"]

W, H = 640, 400
OCEAN, LAND, BORDER = "#cfe0ea", "#f3f0e7", "#aaa498"
HIGHLIGHT, HIGHLIGHT_EDGE = "#c8473d", "#8e2b23"
INK, MUTED = "#1d2733", "#5d6570"
FONT = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
EARTH_KM = 6371.0

# UG name -> Natural Earth ADM0_A3, where the names differ.
NAME_OVERRIDES: dict[str, str] = {}


# ---------- data ----------

def load(name: str) -> list[dict]:
    path = CACHE / f"{name}.geojson"
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(NE + f"{name}.geojson", path)
    return json.loads(path.read_text(encoding="utf-8"))["features"]


def norm(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.lower().replace("&", "and"))


def polygons(geometry: dict) -> list[list[list[tuple[float, float]]]]:
    if geometry["type"] == "Polygon":
        return [[[tuple(p) for p in ring] for ring in geometry["coordinates"]]]
    return [[[tuple(p) for p in ring] for ring in poly] for poly in geometry["coordinates"]]


def entities() -> dict[str, dict]:
    """slug -> {name, capital, directions} from the generated notes."""
    out: dict[str, dict] = {}
    for path in (REPO / "notes").glob("*/*--*.md"):
        slug, direction = path.stem.split("--")
        text = path.read_text(encoding="utf-8")
        back = re.search(r"## Back\n\n<b>(.*?)</b>", text).group(1)
        e = out.setdefault(slug, {"directions": set()})
        e["directions"].add(direction)
        if direction == "capital":
            e["capital"] = back
        else:
            e["name"] = back
    return out


# ---------- geometry ----------

def great_circle(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_KM * math.asin(min(1.0, math.sqrt(h)))


class Ortho:
    def __init__(self, lon0: float, lat0: float):
        self.lon0, self.lat0 = math.radians(lon0), math.radians(lat0)
        self.scale, self.cx, self.cy = 1.0, 0.0, 0.0

    def raw(self, lon: float, lat: float) -> tuple[float, float, bool]:
        lon, lat = math.radians(lon), math.radians(lat)
        dl = lon - self.lon0
        cos_c = math.sin(self.lat0) * math.sin(lat) + math.cos(self.lat0) * math.cos(lat) * math.cos(dl)
        x = math.cos(lat) * math.sin(dl)
        y = math.cos(self.lat0) * math.sin(lat) - math.sin(self.lat0) * math.cos(lat) * math.cos(dl)
        if cos_c < 0:  # behind the globe: pin to the horizon
            r = math.hypot(x, y) or 1.0
            return x / r, y / r, False
        return x, y, True

    def px(self, lon: float, lat: float) -> tuple[float, float, bool]:
        x, y, visible = self.raw(lon, lat)
        return W / 2 + (x - self.cx) * self.scale, H / 2 - (y - self.cy) * self.scale, visible


def clip(ring: list[tuple[float, float]], x0: float, y0: float, x1: float, y1: float) -> list[tuple[float, float]]:
    """Sutherland-Hodgman against an axis-aligned rectangle."""
    def cut(pts, inside, intersect):
        out = []
        for i, cur in enumerate(pts):
            prev = pts[i - 1]
            if inside(cur):
                if not inside(prev):
                    out.append(intersect(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(intersect(prev, cur))
        return out

    def ix(x):
        return lambda p, q: (x, p[1] + (q[1] - p[1]) * (x - p[0]) / (q[0] - p[0]))

    def iy(y):
        return lambda p, q: (p[0] + (q[0] - p[0]) * (y - p[1]) / (q[1] - p[1]), y)

    pts = ring
    for inside, inter in (
        (lambda p: p[0] >= x0, ix(x0)), (lambda p: p[0] <= x1, ix(x1)),
        (lambda p: p[1] >= y0, iy(y0)), (lambda p: p[1] <= y1, iy(y1)),
    ):
        if not pts:
            break
        pts = cut(pts, inside, inter)
    return pts


def simplify(ring: list[tuple[float, float]], tol: float = 0.7) -> list[tuple[float, float]]:
    out = []
    for p in ring:
        if not out or abs(p[0] - out[-1][0]) + abs(p[1] - out[-1][1]) >= tol:
            out.append(p)
    return out


def area_centroid(ring: list[tuple[float, float]]) -> tuple[float, float, float]:
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        cross = x1 * y2 - x2 * y1
        a += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(a) < 1e-9:
        return 0.0, ring[0][0], ring[0][1]
    return abs(a) / 2, cx / (3 * a), cy / (3 * a)


def path_d(rings: list[list[tuple[float, float]]]) -> str:
    return "".join("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in r) + "Z" for r in rings)


# ---------- drawing ----------

def project_feature(proj: Ortho, feature: dict, margin: float = 30) -> list[list[tuple[float, float]]]:
    rings = []
    for poly in polygons(feature["geometry"]):
        for ring in poly:
            pts = [proj.px(lon, lat) for lon, lat in ring]
            if not any(v for _, _, v in pts):
                continue
            xy = simplify(clip([(x, y) for x, y, _ in pts], -margin, -margin, W + margin, H + margin))
            if len(xy) >= 3:
                rings.append(xy)
    return rings


def frame(feature: dict, capital: tuple[float, float] | None) -> tuple[Ortho, bool]:
    """Centre on the country's main landmass and zoom so it fills about half the frame."""
    polys = polygons(feature["geometry"])
    main = max(polys, key=lambda p: len(p[0]))[0]
    lon0 = sum(p[0] for p in main) / len(main)
    lat0 = sum(p[1] for p in main) / len(main)
    radius = max(great_circle((lon0, lat0), p) for p in main)
    reach = max(1500.0, 2.5 * radius)
    def deg_area(ring):
        return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]))) / 2

    main_area = deg_area(main)
    near = [p for poly in polys if deg_area(poly[0]) >= 0.02 * main_area
            for p in poly[0] if great_circle((lon0, lat0), p) <= reach]
    if capital:  # island nations: the capital may sit far from the biggest island
        near.append(capital)

    proj = Ortho(lon0, lat0)
    xs, ys = zip(*[proj.raw(lon, lat)[:2] for lon, lat in near])
    proj.cx, proj.cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    span_w = max((max(xs) - min(xs)) / 0.5, (max(ys) - min(ys)) / 0.62 * W / H, 0.16)
    globe = span_w >= 2.1
    if globe:
        proj.cx = proj.cy = 0.0
        proj.scale = (H - 24) / 2
    else:
        proj.scale = W / span_w
    return proj, globe


def capital_point(places: list[dict], adm0: str, capital: str | None) -> tuple[float, float] | None:
    if not capital:
        return None
    key = norm(capital)
    in_country = [p["properties"] for p in places if p["properties"].get("adm0_a3") == adm0]
    for props in in_country:
        if key in (norm(props.get("name") or ""), norm(props.get("nameascii") or "")):
            return props["longitude"], props["latitude"]
    for props in in_country:
        if props.get("adm0cap") == 1:
            return props["longitude"], props["latitude"]
    return None


def overlaps(box, boxes) -> bool:
    return any(not (box[2] < b[0] or b[2] < box[0] or box[3] < b[1] or b[3] < box[1]) for b in boxes)


def text_box(x: float, y: float, text: str, size: float, anchor: str = "middle") -> tuple[float, float, float, float]:
    w = len(text) * size * 0.58
    left = x - w / 2 if anchor == "middle" else (x if anchor == "start" else x - w)
    return left - 2, y - size, left + w + 2, y + 3


def draw(feature: dict, countries: list[dict], places: list[dict], land: list[dict], name: str, capital: str | None) -> str:
    adm0 = feature["properties"]["ADM0_A3"]
    cap = capital_point(places, adm0, capital)
    proj, globe = frame(feature, cap)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
             f'font-family="{FONT}">',
             f"<title>Map of {escape(name)}</title>"]
    gcx, gcy = W / 2 - proj.cx * proj.scale, H / 2 + proj.cy * proj.scale
    limb = globe or any(math.hypot(x - gcx, y - gcy) > proj.scale for x in (0, W) for y in (0, H))
    if limb:
        parts.append(f'<rect width="{W}" height="{H}" fill="#f6f6f4"/>')
        parts.append(f'<circle cx="{gcx:.1f}" cy="{gcy:.1f}" r="{proj.scale:.1f}" fill="{OCEAN}" '
                     f'stroke="{BORDER}" stroke-width="0.7"/>')
    else:
        parts.append(f'<rect width="{W}" height="{H}" fill="{OCEAN}"/>')

    others, labels = [], []
    for f in countries:
        if f["properties"]["ADM0_A3"] in (adm0, "ATA"):
            continue
        rings = project_feature(proj, f)
        if not rings:
            continue
        others.append(rings)
        visible = [clip(r, 0, 0, W, H) for r in rings]
        pieces = [area_centroid(r) for r in visible if len(r) >= 3]
        if pieces:
            a, lx, ly = max(pieces)
            total = sum(p[0] for p in pieces)
            labels.append((total, a, lx, ly, f["properties"]["NAME"]))
    parts.append(f'<path d="{path_d([r for rs in others for r in rs])}" fill="{LAND}" '
                 f'stroke="{BORDER}" stroke-width="0.7" stroke-linejoin="round"/>')

    mine = project_feature(proj, feature)
    parts.append(f'<path d="{path_d(mine)}" fill="{HIGHLIGHT}" stroke="{HIGHLIGHT_EDGE}" '
                 f'stroke-width="0.8" stroke-linejoin="round"/>')
    taken = []
    if sum(area_centroid(r)[0] for r in mine) < 0.002 * W * H:
        # Too small to see (microstates, atolls): circle each island group.
        if mine:
            centres = [area_centroid(r)[1:] for r in mine]
        else:
            main = max(polygons(feature["geometry"]), key=lambda p: len(p[0]))[0]
            x, y, _ = proj.px(sum(p[0] for p in main) / len(main), sum(p[1] for p in main) / len(main))
            centres = [(x, y)]
        rings_at: list[tuple[float, float]] = []
        for cx, cy in centres:
            if 0 <= cx <= W and 0 <= cy <= H and all(math.hypot(cx - a, cy - b) > 26 for a, b in rings_at):
                rings_at.append((cx, cy))
        for cx, cy in rings_at:
            parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="13" fill="none" stroke="{HIGHLIGHT}" stroke-width="2.5"/>')
            taken.append((cx - 15, cy - 15, cx + 15, cy + 15))

    halo = 'stroke="#ffffff" stroke-width="3" stroke-linejoin="round" paint-order="stroke"'
    if cap:
        x, y, visible = proj.px(*cap)
        if visible and 0 <= x <= W and 0 <= y <= H:
            anchor = "start" if x < W - 140 else "end"
            tx = x + 8 if anchor == "start" else x - 8
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="{INK}" stroke="#ffffff" stroke-width="1.6"/>')
            parts.append(f'<text x="{tx:.1f}" y="{y + 4.5:.1f}" font-size="14" font-weight="600" fill="{INK}" '
                         f'text-anchor="{anchor}" {halo}>{escape(capital)}</text>')
            taken.append(text_box(tx, y + 4.5, capital, 14, anchor))
            taken.append((x - 6, y - 6, x + 6, y + 6))

    inset = None
    if not globe:
        inset = (16, H - 96, 96, H - 16)
        taken.append(inset)
    for total, _, lx, ly, label in sorted(labels, reverse=True):
        if total < 0.005 * W * H:
            break
        box = text_box(lx, ly, label, 11.5)
        if box[0] < 4 or box[2] > W - 4 or box[1] < 4 or box[3] > H - 4 or overlaps(box, taken):
            continue
        taken.append(box)
        parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="11.5" fill="{MUTED}" text-anchor="middle" '
                     f'{halo}>{escape(label)}</text>')

    if inset:  # small globe, bottom left, with a dot on the country
        g = Ortho(math.degrees(proj.lon0), math.degrees(proj.lat0))
        r = 38
        g.scale, gx, gy = r, 56, H - 56
        rings = []
        for f in land:
            if min(lat for poly in polygons(f["geometry"]) for _, lat in poly[0]) < -60:
                continue  # Antarctica
            for poly in polygons(f["geometry"]):
                pts = [g.raw(lon, lat) for lon, lat in poly[0]]
                # A ring mostly behind the globe pins to the horizon the long way
                # round and floods the disc; at this size, leaving it out is fine.
                if sum(v for _, _, v in pts) >= 0.5 * len(pts):
                    rings.append(simplify([(gx + x * r, gy - y * r) for x, y, _ in pts], 0.8))
        parts.append(f'<circle cx="{gx}" cy="{gy}" r="{r + 2}" fill="#ffffff"/>')
        parts.append(f'<circle cx="{gx}" cy="{gy}" r="{r}" fill="{OCEAN}"/>')
        parts.append(f'<path d="{path_d([q for q in rings if len(q) >= 3])}" fill="#d9d5ca"/>')
        parts.append(f'<circle cx="{gx}" cy="{gy}" r="3.5" fill="{HIGHLIGHT}" stroke="#ffffff" stroke-width="1"/>')
    parts.append("</svg>")
    return "\n".join(parts)


def main(slugs: list[str]) -> None:
    countries = load(FILES[0])
    places = load(FILES[1])
    land = load(FILES[2])
    index: dict[str, dict] = {}
    for f in countries:
        p = f["properties"]
        for k in ("NAME", "NAME_LONG", "ADMIN", "NAME_EN", "FORMAL_EN", "NAME_SORT", "BRK_NAME", "GEOUNIT", "SUBUNIT"):
            if p.get(k):
                index.setdefault(norm(p[k]), f)
    by_a3 = {f["properties"]["ADM0_A3"]: f for f in countries}

    ents = entities()
    wanted = slugs or [s for s, e in sorted(ents.items()) if e["directions"] & {"capital", "country", "flag"}]
    OUT.mkdir(parents=True, exist_ok=True)
    missing = []
    index_path = OUT / "index.json"
    index_out = json.loads(index_path.read_text()) if index_path.exists() and slugs else {}
    for slug in wanted:
        e = ents[slug]
        name = e.get("name", slug)
        feature = by_a3.get(NAME_OVERRIDES.get(name, "")) or index.get(norm(name))
        if not feature:
            missing.append(name)
            continue
        svg = draw(feature, countries, places, land, name, e.get("capital"))
        (OUT / f"cx-locator-{slug}.svg").write_text(svg, encoding="utf-8")
        a3 = feature["properties"]["ADM0_A3"]
        cap = capital_point(places, a3, e.get("capital"))
        index_out[slug] = {"focus": a3, "pin": [round(cap[1], 4), round(cap[0], 4)] if cap else None,
                           "label": e.get("capital") if cap else None}
        print(f"{slug}: {len(svg) // 1024} KB")
    index_path.write_text(json.dumps(dict(sorted(index_out.items())), ensure_ascii=False, indent=1) + "\n")
    if missing:
        print(f"no Natural Earth match, skipped: {', '.join(missing)}")


if __name__ == "__main__":
    main(sys.argv[1:])
