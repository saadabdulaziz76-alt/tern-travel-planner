"""Build `web/map-extras.json` — the shapes the base world atlas does not carry.

Run once; the output is committed, so the app never fetches a 3 MB file at
runtime and a fresh clone works offline after the first load.

Three problems it solves, all of them things a user noticed on the real map:

  1. The UK is one polygon in every world atlas. People do not think of
     themselves as having been to "the United Kingdom" — they went to Scotland.
     Natural Earth publishes England / Scotland / Wales / Northern Ireland as
     separate map units, so we lift those four out.
  2. A handful of countries have no polygon even at 1:50m — mostly French
     overseas departments and disputed territories folded into a parent.
  3. Whatever is still missing gets a label point so the map can draw a
     clickable dot. A country with no shape at any resolution must still be
     pinnable, or the count is a lie.

Source: Natural Earth 1:50m admin-0 map units (public domain).
"""
from __future__ import annotations

import json
import ssl
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tnat_data as D

NE = ("https://cdn.jsdelivr.net/gh/nvkelso/natural-earth-vector@master/"
      "geojson/ne_50m_admin_0_map_units.geojson")
ATLAS = "https://cdn.jsdelivr.net/npm/world-atlas@2/countries-50m.json"
OUT = Path(__file__).resolve().parent.parent / "web" / "map-extras.json"

UK_PARTS = ["England", "Scotland", "Wales", "Northern Ireland"]


def fetch(url):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(url, timeout=120, context=ctx) as r:
        return json.loads(r.read())


def prop(f, *keys):
    for k in keys:
        v = f["properties"].get(k)
        if v not in (None, "", "-99", -99):
            return v
    return None


def round_geom(g, nd=3):
    """Three decimals is ~110 m at the equator — far finer than a world map
    needs, and it cuts the file by more than half."""
    def walk(x):
        if isinstance(x, (int, float)):
            return round(x, nd)
        return [walk(i) for i in x]
    return {"type": g["type"], "coordinates": walk(g["coordinates"])}


def main():
    print("fetching Natural Earth map units…")
    ne = fetch(NE)["features"]
    print("fetching the base atlas to see what is already covered…")
    atlas = fetch(ATLAS)
    have = {str(g.get("id", "")).zfill(3)
            for g in atlas["objects"]["countries"]["geometries"]}

    ours = D.labellable()
    by_num = {c["num"]: c for c in ours if c.get("num")}
    missing = [c for c in ours if not c.get("num") or c["num"] not in have]
    print(f"  base atlas covers {len(ours) - len(missing)}/{len(ours)} of our countries")

    ne_by_n3, ne_by_name = {}, {}
    for f in ne:
        n3 = prop(f, "ISO_N3", "iso_n3")
        if n3:
            ne_by_n3.setdefault(str(n3).zfill(3), f)
        for key in ("NAME", "NAME_LONG", "GEOUNIT", "ADMIN"):
            v = prop(f, key)
            if v:
                ne_by_name.setdefault(str(v).lower(), f)

    out = {"source": "Natural Earth 1:50m admin-0 map units (public domain)",
           "parts": [], "extra": [], "dots": []}

    # 1. the four UK nations
    for name in UK_PARTS:
        f = ne_by_name.get(name.lower()) or ne_by_name.get(
            name.replace("Northern", "N.").lower())
        if not f:
            print(f"  !! no shape for {name}")
            continue
        out["parts"].append({"name": name, "parent": "United Kingdom",
                             "geometry": round_geom(f["geometry"])})
        print(f"  part  {name}")

    # 2. countries the base atlas lacks but Natural Earth has
    still = []
    for c in missing:
        f = (ne_by_n3.get(c["num"]) if c.get("num") else None) \
            or ne_by_name.get(c["name"].lower())
        if f:
            out["extra"].append({"name": c["name"], "num": c.get("num"),
                                 "geometry": round_geom(f["geometry"])})
            print(f"  shape {c['name']}")
        else:
            still.append(c)

    # 3. a label point for anything with no shape anywhere
    for c in still:
        f = ne_by_name.get(c["name"].lower())
        lon = lat = None
        if f:
            lon, lat = prop(f, "LABEL_X"), prop(f, "LABEL_Y")
        if lon is None or lat is None:
            lon, lat = FALLBACK_POINTS.get(c["name"], (None, None))
        if lon is None:
            print(f"  !! no shape and no point for {c['name']}")
            continue
        out["dots"].append({"name": c["name"], "num": c.get("num"),
                            "lonlat": [round(float(lon), 3), round(float(lat), 3)]})
        print(f"  dot   {c['name']}")

    OUT.write_text(json.dumps(out, separators=(",", ":")))
    kb = OUT.stat().st_size / 1024
    print(f"\nwrote {OUT.name}: {len(out['parts'])} parts, {len(out['extra'])} shapes, "
          f"{len(out['dots'])} dots, {kb:.0f} KB")


# Hand-entered for the few places Natural Earth has no map unit for at all.
# Each is the accepted centre of the territory; they only position a dot.
FALLBACK_POINTS = {
    "Bonaire, Sint Eustatius and Saba": (-68.26, 12.18),
    "Bouvet Island": (3.36, -54.42),
    "Gibraltar": (-5.35, 36.14),
    "Reunion": (55.54, -21.12),
    "Svalbard and Jan Mayen": (18.0, 78.5),
    "United States Minor Outlying Islands": (-160.02, 5.88),
    "Christmas Island": (105.69, -10.45),
    "Saint Helena, Ascension and Tristan da Cunha": (-5.72, -15.96),
    "Heard Island and McDonald Islands": (73.5, -53.08),
    "Pitcairn": (-128.32, -24.37),
    "Norfolk Island": (167.95, -29.04),
    "British Indian Ocean Territory": (72.42, -7.33),
}

if __name__ == "__main__":
    main()
