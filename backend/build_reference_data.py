"""Fetch and cache the reference datasets TNAT needs beyond arrivals.

Run once; the output is committed. Nothing here is fetched at request time, so
the app stays fast and a fresh clone works offline after the first load.

    python build_reference_data.py            # everything except climate
    python build_reference_data.py --climate  # the slow one, resumable

Sources, all open and citable:
  facts      github.com/mledoze/countries      capital, lat/lon, currency, language
  visa       github.com/ilyankou/passport-index-dataset
  population Our World in Data
  prices     World Bank PPP conversion factor / official exchange rate
  economy    World Bank international tourism receipts, % of exports
  climate    Open-Meteo ERA5 archive, 2021-2023 daily means per capital
"""
from __future__ import annotations

import csv
import io
import json
import ssl
import sys
import time
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "reference"
UA = {"User-Agent": "TNAT-course-project/1.0 (academic use; saad.alarifi@yale.edu)"}
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def fetch(url: str, timeout: int = 120) -> bytes:
    return urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=timeout, context=CTX).read()


def save(name: str, obj) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    p.write_text(json.dumps(obj, separators=(",", ":"), sort_keys=True))
    print(f"  wrote {name:22s} {p.stat().st_size/1024:7.0f} KB  {len(obj):>5} entries")


# ------------------------------------------------------------------- facts
def build_facts() -> dict:
    """Country facts, with capital coordinates from Natural Earth.

    mledoze/countries carries `capitalInfo: null` and integer country
    centroids, which put London at 54N -2 and made London-Paris 934 km instead
    of 344. Natural Earth publishes the actual capital cities keyed on ISO3, so
    distances are measured city to city — which is what a traveller flies.
    Countries with no Natural Earth capital fall back to the centroid and are
    flagged, so a coarse distance is never passed off as a precise one.
    """
    d = json.loads(fetch("https://raw.githubusercontent.com/mledoze/countries/"
                         "master/countries.json"))
    ne = json.loads(fetch("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
                          "master/geojson/ne_110m_populated_places_simple.geojson"))
    # "Admin-0 capital alt" marks historical or secondary capitals — Kyoto is
    # one, and taking the first prefix match put Japan's capital 830 km from
    # Tokyo. The real capital always wins.
    caps = {}
    for f in ne["features"]:
        pr = f["properties"]
        iso, cls = pr.get("adm0_a3"), str(pr.get("featurecla", ""))
        if not iso or not cls.startswith("Admin-0 capital"):
            continue
        exact = cls.strip() == "Admin-0 capital"
        if iso in caps and not exact:
            continue
        if iso in caps and caps[iso][3] and not exact:
            continue
        lon, lat = f["geometry"]["coordinates"][:2]
        if iso not in caps or exact:
            caps[iso] = (round(lat, 4), round(lon, 4), pr.get("name"), exact)

    out, fallback = {}, 0
    for c in d:
        iso = c["cca3"]
        ll = c.get("latlng") or []
        cap_name = (c.get("capital") or [None])[0]
        if iso in caps:
            lat, lon, ne_name, _ = caps[iso]
            precise = True
            cap_name = cap_name or ne_name
        elif len(ll) == 2:
            lat, lon, precise = float(ll[0]), float(ll[1]), False
            fallback += 1
        else:
            continue
        out[iso] = {
            "name": c["name"]["common"], "capital": cap_name,
            # land neighbours: the difference between "you could drive" and
            # "you are getting on a plane"
            "borders": c.get("borders") or [],
            "landlocked": bool(c.get("landlocked")),
            "lat": round(lat, 4), "lon": round(lon, 4),
            "capital_precise": precise,
            "currencies": sorted(c.get("currencies", {})),
            "languages": sorted(set((c.get("languages") or {}).values())),
            "region": c.get("region"), "subregion": c.get("subregion"),
        }
    print(f"    capitals: {len(out) - fallback} exact, {fallback} fell back to centroid")
    return out


# -------------------------------------------------------------------- visa
# Numbers in the source mean "visa free for N days"; -1 marks the passport's
# own country. Collapsed to a short code plus the day count where given.
def build_visa() -> dict:
    raw = fetch("https://raw.githubusercontent.com/ilyankou/passport-index-dataset/"
                "master/passport-index-tidy-iso3.csv").decode()
    out: dict[str, dict] = {}
    for r in csv.DictReader(io.StringIO(raw)):
        req = r["Requirement"].strip().lower()
        if req == "-1":
            code = "self"
        elif req.isdigit():
            code = f"free:{req}"
        elif req == "visa free":
            code = "free"
        elif req in ("visa on arrival", "voa"):
            code = "arrival"
        elif req == "e-visa":
            code = "evisa"
        elif req == "eta":
            code = "eta"
        elif req == "no admission":
            code = "banned"
        else:
            code = "required"
        out.setdefault(r["Passport"], {})[r["Destination"]] = code
    return out


# -------------------------------------------------------------- population
def build_population() -> dict:
    raw = fetch("https://ourworldindata.org/grapher/population.csv?v=1&csvType=full").decode()
    return {r["Code"]: int(r["Population"])
            for r in csv.DictReader(io.StringIO(raw))
            if r.get("Year") == "2019" and r.get("Code") and r["Population"].isdigit()}


# ------------------------------------------------------------- world bank
def wb(indicator: str, year: int = 2019) -> dict:
    d = json.loads(fetch(f"https://api.worldbank.org/v2/country/all/indicator/"
                         f"{indicator}?date={year}&format=json&per_page=400"))
    return {r["countryiso3code"]: r["value"] for r in (d[1] or [])
            if r.get("value") is not None and r.get("countryiso3code")}


def build_prices() -> dict:
    """Price level, 1.0 = United States.

    The World Bank's own price-level indicator returns nothing for 2019, so it
    is computed the way the ratio is defined: PPP conversion factor divided by
    the market exchange rate.
    """
    ppp, fx = wb("PA.NUS.PPP"), wb("PA.NUS.FCRF")
    return {k: round(ppp[k] / fx[k], 4)
            for k in set(ppp) & set(fx) if fx[k]}


def build_economy() -> dict:
    rcpt, share = wb("ST.INT.RCPT.CD"), wb("ST.INT.RCPT.XP.ZS")
    out = {}
    for k in set(rcpt) | set(share):
        row = {}
        if k in rcpt:
            row["receipts_usd"] = int(rcpt[k])
        if k in share:
            row["pct_of_exports"] = round(share[k], 2)
        if row:
            out[k] = row
    return out


# ----------------------------------------------------------------- climate
def build_climate(facts: dict) -> dict:
    """Monthly mean temperature and rainfall at each capital, 2021-2023.

    This answers "when is the weather good", which is NOT the same question as
    "when is it quiet" — no monthly arrivals data exists publicly. The UI has
    to say which one it is showing.
    """
    path = OUT / "climate.json"
    out = json.loads(path.read_text()) if path.exists() else {}
    todo = [k for k in facts if k not in out]
    print(f"  climate: {len(out)} cached, {len(todo)} to fetch")
    for i, iso in enumerate(todo, 1):
        f = facts[iso]
        try:
            d = json.loads(fetch(
                "https://archive-api.open-meteo.com/v1/archive"
                f"?latitude={f['lat']}&longitude={f['lon']}"
                "&start_date=2021-01-01&end_date=2023-12-31"
                "&daily=temperature_2m_mean,precipitation_sum&timezone=UTC", timeout=60))
            days = d["daily"]["time"]
            temp = d["daily"]["temperature_2m_mean"]
            rain = d["daily"]["precipitation_sum"]
            buckets = {m: [[], []] for m in range(1, 13)}
            for day, t, r in zip(days, temp, rain):
                m = int(day[5:7])
                if t is not None:
                    buckets[m][0].append(t)
                if r is not None:
                    buckets[m][1].append(r)
            out[iso] = {str(m): {
                "t": round(sum(b[0]) / len(b[0]), 1) if b[0] else None,
                # total rainfall in an average month, not a daily mean
                "rain": round(sum(b[1]) / 3, 0) if b[1] else None,
            } for m, b in buckets.items()}
        except Exception as e:
            print(f"    {iso} failed: {type(e).__name__}")
        if i % 25 == 0:
            path.write_text(json.dumps(out, separators=(",", ":"), sort_keys=True))
            print(f"    {i}/{len(todo)} …")
        time.sleep(0.12)          # be polite to a free API
    return out


# ------------------------------------------------------------------ cities
def build_cities() -> dict:
    """Cities of 15,000+ people, with their state and coordinates.

    Home was a country, so every distance started from that country's capital.
    For anyone not living in their capital that is wrong by hundreds of
    kilometres — Jeddah to Riyadh alone is 850 km. This lets someone say where
    they actually live.

    Keyed by ISO3 so a search can be scoped to one country, which keeps the
    result list short and the match quality high.
    """
    import io
    import zipfile

    raw = fetch("https://download.geonames.org/export/dump/cities15000.zip")
    txt = zipfile.ZipFile(io.BytesIO(raw)).read("cities15000.txt").decode("utf-8")
    admin = {}
    for line in fetch("https://download.geonames.org/export/dump/"
                      "admin1CodesASCII.txt").decode("utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            admin[parts[0]] = parts[1]

    iso2_to_iso3 = {m["iso2"]: iso3 for iso3, m in
                    json.loads((OUT.parent / "iso_registry.json").read_text()).items()
                    if m.get("iso2")}

    out: dict[str, list] = {}
    for line in txt.splitlines():
        f = line.split("\t")
        if len(f) < 15:
            continue
        cc, a1 = f[8], f[10]
        iso3 = iso2_to_iso3.get(cc)
        if not iso3:
            continue
        try:
            lat, lon, pop = round(float(f[4]), 4), round(float(f[5]), 4), int(f[14] or 0)
        except ValueError:
            continue
        state = admin.get(f"{cc}.{a1}", "")
        # PPLC is a national capital; it should lead its country's list
        out.setdefault(iso3, []).append(
            [f[1], state, lat, lon, pop, 1 if f[7] == "PPLC" else 0])
    # biggest first, so an unqualified search lands on the obvious answer
    for iso3 in out:
        out[iso3].sort(key=lambda r: (-r[5], -r[4]))
    return out


# ------------------------------------------------------------------- parks
SPARQL = "https://query.wikidata.org/sparql"


def _sparql(query: str, timeout: int = 240) -> list[dict]:
    import urllib.parse
    url = SPARQL + "?format=json&query=" + urllib.parse.quote(query)
    req = urllib.request.Request(url, headers={
        **UA, "Accept": "application/sparql-results+json"})
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return json.loads(r.read())["results"]["bindings"]


# Wikidata area units, converted to square kilometres.
AREA_TO_KM2 = {
    "Q712226": 1.0,          # square kilometre
    "Q35852": 0.01,          # hectare
    "Q25343": 1e-6,          # square metre
    "Q232291": 2.589988,     # square mile
    "Q81292": 0.00404686,    # acre
}

PARK_QUERIES = {
    # US national parks are their own Wikidata class; Canada's are the generic
    # national-park class filtered by country.
    "USA": """SELECT ?p ?pLabel ?coord ?img ?area ?unit ?visitors ?vyear ?inception ?article WHERE {
      { ?p wdt:P31 wd:Q34918903 }
      UNION { ?p wdt:P31/wdt:P279* wd:Q46169 ; wdt:P17 wd:Q30 }
      UNION { ?p wdt:P31/wdt:P279* wd:Q46169 ; wdt:P17 wd:Q11703 }
      FILTER EXISTS { ?p rdfs:label ?lbl FILTER(lang(?lbl)='en' && CONTAINS(?lbl,"National Park")) }
      # A dissolution date means the park no longer exists -- Mackinac was
      # delisted in 1895, General Grant became Kings Canyon. Q491005 (Virgin
      # Islands) carries one in error and is open, so it is excepted.
      FILTER( NOT EXISTS { ?p wdt:P576 ?dissolved } || ?p = wd:Q491005 )
      OPTIONAL { ?p wdt:P625 ?coord } OPTIONAL { ?p wdt:P18 ?img }
      OPTIONAL { ?p p:P2046/psv:P2046 [ wikibase:quantityAmount ?area ;
                                        wikibase:quantityUnit ?unit ] }
      OPTIONAL { ?p p:P1174 [ ps:P1174 ?visitors ; pq:P585 ?vyear ] }
      OPTIONAL { ?p wdt:P571 ?inception }
      OPTIONAL { ?article schema:about ?p ; schema:isPartOf <https://en.wikipedia.org/> }
      SERVICE wikibase:label { bd:serviceParam wikibase:language "en". } }""",
    "CAN": """SELECT ?p ?pLabel ?coord ?img ?area ?unit ?visitors ?vyear ?inception ?article WHERE {
      ?p wdt:P31/wdt:P279* wd:Q46169 ; wdt:P17 wd:Q16 .
      FILTER NOT EXISTS { ?p wdt:P576 ?dissolved }
      OPTIONAL { ?p wdt:P625 ?coord } OPTIONAL { ?p wdt:P18 ?img }
      OPTIONAL { ?p p:P2046/psv:P2046 [ wikibase:quantityAmount ?area ;
                                        wikibase:quantityUnit ?unit ] }
      OPTIONAL { ?p p:P1174 [ ps:P1174 ?visitors ; pq:P585 ?vyear ] }
      OPTIONAL { ?p wdt:P571 ?inception }
      OPTIONAL { ?article schema:about ?p ; schema:isPartOf <https://en.wikipedia.org/> }
      SERVICE wikibase:label { bd:serviceParam wikibase:language "en". } }""",
}


def build_parks() -> dict:
    """National parks of the US and Canada, with a photo apiece.

    Images are Wikimedia Commons files referenced through Special:FilePath, so
    they are freely licensed and we store a reference rather than a copy.

    Wikidata returns a row per optional value, so the same park arrives several
    times; rows are merged on the entity id. The state or province comes from
    the nearest city in our own gazetteer rather than Wikidata's P131, which
    gives a county as often as a state.
    """
    # Nearest-city gave Arches National Park as Colorado (it is in Utah, close
    # to the border) and Auyuittuq as Quebec (it is on Baffin Island). Remote
    # parks are exactly the ones with no nearby city, so the state comes from
    # actual boundaries instead.
    print("  fetching state and province boundaries…")
    admin1 = json.loads(fetch("https://cdn.jsdelivr.net/gh/nvkelso/natural-earth-vector"
                              "@master/geojson/ne_50m_admin_1_states_provinces.geojson"))
    regions = []
    for f in admin1["features"]:
        pr = f["properties"]
        if pr.get("adm0_a3") not in ("USA", "CAN"):
            continue
        rings = []
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for poly in polys:
            rings.append(poly[0])
        regions.append((pr.get("name") or "", pr.get("adm0_a3"), rings))
    print(f"  {len(regions)} US/Canada subdivisions loaded")

    def inside(lon: float, lat: float, ring: list) -> bool:
        hit = False
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i][0], ring[i][1]
            x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
            if (y1 > lat) != (y2 > lat):
                xi = x1 + (lat - y1) / (y2 - y1) * (x2 - x1)
                if lon < xi:
                    hit = not hit
        return hit

    # Natural Earth files the US insular areas as their own countries, so the
    # US subdivision set does not contain them and the nearest-polygon fallback
    # put American Samoa in Hawaii and the Virgin Islands in Florida. They are
    # few and far from everything else, so a bounding box settles them.
    TERRITORIES = [
        ("American Samoa",      -15.5, -13.9, -171.5, -168.0),
        ("U.S. Virgin Islands",  17.6,  18.5,  -65.2,  -64.5),
        ("Puerto Rico",          17.8,  18.6,  -67.3,  -65.2),
        ("Guam",                 13.2,  13.7,  144.6,  145.0),
    ]

    def nearest_state(lat: float, lon: float, iso3: str) -> str:
        if iso3 == "USA":
            for name, lo, hi, wlon, elon in TERRITORIES:
                if lo <= lat <= hi and wlon <= lon <= elon:
                    return name
        mine = [r for r in regions if r[1] == iso3]
        for name, _, rings in mine:
            if any(inside(lon, lat, r) for r in rings):
                return name
        # Island and coastal parks sit just outside the land polygon — Gulf
        # Islands, Mingan Archipelago, Fundy. Fall back to the closest
        # subdivision rather than leaving them stateless.
        best, bd = "", 1e18
        for name, _, rings in mine:
            for ring in rings:
                for x, y in ring[::7]:          # every seventh vertex is plenty
                    d = (y - lat) ** 2 + ((x - lon) * 0.75) ** 2
                    if d < bd:
                        bd, best = d, name
        return best

    out: dict[str, dict] = {}
    for iso3, query in PARK_QUERIES.items():
        rows = _sparql(query)
        print(f"  {iso3}: {len(rows)} rows")
        for r in rows:
            qid = r["p"]["value"].rsplit("/", 1)[-1]
            rec = out.setdefault(qid, {"id": qid, "iso3": iso3,
                                       "name": r["pLabel"]["value"]})
            if "coord" in r and "lat" not in rec:
                try:
                    lon, lat = r["coord"]["value"].removeprefix("Point(").rstrip(")").split()
                    rec["lat"], rec["lon"] = round(float(lat), 4), round(float(lon), 4)
                except ValueError:
                    pass
            if "img" in r and "image" not in rec:
                rec["image"] = r["img"]["value"].rsplit("/", 1)[-1]
            if "area" in r and "area_km2" not in rec:
                # Wikidata stores the unit separately, and these are mostly
                # hectares: taking the bare number made Yellowstone 898,349 km²
                # when it is 8,983.
                try:
                    amount = float(r["area"]["value"])
                except ValueError:
                    amount = None
                unit = r.get("unit", {}).get("value", "").rsplit("/", 1)[-1]
                factor = AREA_TO_KM2.get(unit)
                if amount is not None and factor:
                    rec["area_km2"] = round(amount * factor)
            # Visitor counts arrive one row per year. Keep the most recent,
            # but skip 2020 and 2021 — the same rule the arrivals data uses,
            # because a pandemic year is not what a park normally receives.
            if "visitors" in r:
                try:
                    v = int(float(r["visitors"]["value"]))
                    yr = int(r.get("vyear", {}).get("value", "0")[:4] or 0)
                except ValueError:
                    v = yr = 0
                # Parks Canada counts by fiscal year, so Wikidata carries
                # dates like 2026 that have not happened yet. A visitor figure
                # from the future is not a visitor figure.
                this_year = time.localtime().tm_year
                if v and yr and yr not in (2020, 2021) and yr <= this_year:
                    if yr > rec.get("visitors_year", 0):
                        rec["visitors"], rec["visitors_year"] = v, yr
            if "inception" in r and "established" not in rec:
                rec["established"] = r["inception"]["value"][:4]
            if "article" in r and "wiki" not in rec:
                rec["wiki"] = r["article"]["value"].rsplit("/", 1)[-1]

    parks = list(out.values())
    # Resolve every photo to its final upload.wikimedia.org URL here, once.
    #
    # Commons' Special:FilePath redirects on every request, and a page of 118
    # of them crawled — one image in eight had arrived after eight seconds.
    # Constructing thumbnail URLs by hand does not work either: Commons now
    # rejects any width that is not already cached, and which widths those are
    # varies per file. Wikipedia's REST summary hands back a direct thumbnail
    # URL, so the slow lookup happens at build time and the browser gets a
    # final URL it can fetch in parallel.
    import urllib.parse
    withwiki = [p for p in parks if p.get("wiki")]
    print(f"  resolving photo URLs for {len(withwiki)} parks via Wikipedia…")
    found = 0
    for i, park in enumerate(withwiki, 1):
        try:
            url = ("https://en.wikipedia.org/api/rest_v1/page/summary/"
                   + urllib.parse.quote(park["wiki"]))
            data = json.loads(fetch(url, timeout=30))
            thumb = (data.get("thumbnail") or {}).get("source")
            full = (data.get("originalimage") or {}).get("source")
            if thumb:
                park["photo_url"] = thumb
                park["photo_full"] = full or thumb
                found += 1
            # New River Gorge and Lake Clark carry no P625 on Wikidata, so
            # they were being dropped for having no coordinates. Wikipedia
            # has them.
            if "lat" not in park:
                co = data.get("coordinates") or {}
                if co.get("lat") is not None and co.get("lon") is not None:
                    park["lat"] = round(float(co["lat"]), 4)
                    park["lon"] = round(float(co["lon"]), 4)
        except Exception:
            pass
        if i % 30 == 0:
            print(f"    {i}/{len(withwiki)}…")
        time.sleep(0.05)
    print(f"  {found} resolved to a direct URL; "
          f"{sum(1 for p in parks if p.get('photo_url') or p.get('image'))} have some photo")

    # now that every source has been consulted, drop anything still unplaceable
    no_coord = [p["name"] for p in parks if "lat" not in p]
    parks = [p for p in parks if "lat" in p]
    if no_coord:
        print(f"  {len(no_coord)} still have no coordinates and are dropped: "
              f"{', '.join(no_coord[:4])}")
    for p in parks:
        p["state"] = nearest_state(p["lat"], p["lon"], p["iso3"])
    # Wikidata holds "Denali National Park" and "Denali National Park and
    # Preserve" as separate entities. They are one place to visit, so they are
    # merged on the shorter name, keeping whichever record carries more.
    before = len(parks)
    parks = [p for p in parks
             if not p["name"].startswith(("Establishment of", "History of",
                                          "List of", "Geology of"))]
    if len(parks) < before:
        print(f"  dropped {before - len(parks)} entries that are events, not places")


    def base(name: str) -> str:
        # "North Cascades National Park Complex" is the administrative unit
        # around North Cascades National Park, not a second park.
        return (name.replace(" and Preserve", "").replace(" and Reserve", "")
                .replace(" National Park Complex", " National Park")
                .replace(" National Park Reserve", " National Park").strip())

    merged: dict[tuple, dict] = {}
    for park in parks:
        key = (park["iso3"], base(park["name"]).lower())
        have = merged.get(key)
        if not have:
            merged[key] = park
            continue
        richer = max(have, park, key=lambda r: sum(
            1 for f in ("photo_url", "image", "area_km2", "visitors",
                        "established", "wiki") if r.get(f)))
        poorer = park if richer is have else have
        for f, v in poorer.items():               # fill any gaps from the other
            richer.setdefault(f, v)
        merged[key] = richer
    dropped = len(parks) - len(merged)
    if dropped:
        print(f"  merged {dropped} duplicate entries (park / park-and-preserve)")
    parks = list(merged.values())

    # Four entries are not parks you can visit today, and no property in
    # Wikidata separates them: the first two were delisted in the 1920s but
    # carry no abolition date, and the last two are only proposed. A missing
    # founding date does not mark them -- New River Gorge and Lake Clark are
    # open and have none either -- so they are named here with the reason.
    NOT_OPEN = {
        "Menissawok National Park":                       "delisted 1930",
        "Nemiskam National Park":                         "delisted 1947",
        "South Okanagan-Similkameen National Park Reserve": "proposed only",
        "Bowen Island National Park Reserve":              "proposed only",
    }
    gone = [p["name"] for p in parks if p["name"] in NOT_OPEN]
    parks = [p for p in parks if p["name"] not in NOT_OPEN]
    if gone:
        print(f"  dropped {len(gone)} that are delisted or only proposed")

    parks.sort(key=lambda p: (p["iso3"], p["name"]))
    print(f"  kept {len(parks)} with coordinates, "
          f"{sum(1 for p in parks if p.get('image'))} with a photo")
    return {"parks": parks,
            "image_base": "https://commons.wikimedia.org/wiki/Special:FilePath/",
            "source": "Wikidata; photographs from Wikimedia Commons"}


# ---------------------------------------------------------------- airports
def build_airports() -> dict:
    """Airports you could actually fly into, keyed for nearest-airport lookups.

    86,000 rows in the source, almost all of them airstrips. Only large and
    medium airports with an IATA code are of any use for "fly into X".
    """
    raw = fetch("https://davidmegginson.github.io/ourairports-data/airports.csv").decode()
    out = []
    for row in csv.DictReader(io.StringIO(raw)):
        if row["type"] not in ("large_airport", "medium_airport"):
            continue
        if not row["iata_code"] or row["scheduled_service"] != "yes":
            continue
        try:
            lat, lon = round(float(row["latitude_deg"]), 4), round(float(row["longitude_deg"]), 4)
        except ValueError:
            continue
        out.append([row["iata_code"], row["name"], lat, lon,
                    row["iso_country"], 1 if row["type"] == "large_airport" else 0])
    print(f"  {len(out)} airports with scheduled service and an IATA code")
    return {"airports": out}


def build_unesco() -> dict:
    """Every UNESCO World Heritage site, country by country.

    The one global query for this times out at the endpoint every time — it is
    too broad. Asked one country at a time it answers in about two seconds, so
    the loop is the fix rather than a workaround: ~190 small queries instead of
    one that never returns.

    UNESCO's own XML feed would be the better source, but it sits behind bot
    protection and cannot be fetched from a script.
    """
    print("  fetching country codes…")
    rows = _sparql("SELECT ?c ?iso WHERE { ?c wdt:P298 ?iso }")
    countries = {}
    for r in rows:
        countries.setdefault(r["iso"]["value"].upper(),
                             r["c"]["value"].rsplit("/", 1)[-1])
    print(f"  {len(countries)} countries to ask about")

    out, blank = [], 0
    for n, (iso3, qid) in enumerate(sorted(countries.items()), 1):
        # P1435 alone catches every component of a serial listing — Portugal
        # came back with 49 entries for its 17 sites, including single rock-art
        # panels in the Côa Valley. P757 is UNESCO's own reference number and
        # exists once per inscribed site, so it is what "a site" means here.
        q = """SELECT ?s ?sLabel ?whs ?coord ?img ?inception ?article WHERE {
          ?s wdt:P757 ?whs ; wdt:P17 wd:%s .
          OPTIONAL { ?s wdt:P625 ?coord } OPTIONAL { ?s wdt:P18 ?img }
          OPTIONAL { ?s wdt:P571 ?inception }
          OPTIONAL { ?article schema:about ?s ; schema:isPartOf <https://en.wikipedia.org/> }
          SERVICE wikibase:label { bd:serviceParam wikibase:language "en". } }""" % qid
        try:
            hits = _sparql(q)
        except Exception:
            blank += 1
            continue
        seen = {}
        for r in hits:
            sid = r["s"]["value"].rsplit("/", 1)[-1]
            rec = seen.setdefault(sid, {"id": sid, "iso3": iso3,
                                        "name": r["sLabel"]["value"],
                                        "whs": r["whs"]["value"]})
            if "coord" in r and "lat" not in rec:
                try:
                    lon, lat = r["coord"]["value"].removeprefix("Point(").rstrip(")").split()
                    rec["lat"], rec["lon"] = round(float(lat), 4), round(float(lon), 4)
                except ValueError:
                    pass
            if "img" in r and "image" not in rec:
                rec["image"] = r["img"]["value"].rsplit("/", 1)[-1]
            if "inception" in r and "listed" not in rec:
                rec["listed"] = r["inception"]["value"][:4]
            if "article" in r and "wiki" not in rec:
                rec["wiki"] = r["article"]["value"].rsplit("/", 1)[-1]
        out.extend(seen.values())
        if n % 25 == 0:
            print(f"    {n}/{len(countries)} countries, {len(out)} sites so far")

    # Wikidata gives a serial listing's components the parent's reference
    # number, so P757 narrowed nothing on its own: 6,054 entities carry 1,200
    # numbers between them. One number is one inscribed site, so they are
    # folded together here, keeping whichever entity looks most like the
    # listing itself — the one with a Wikipedia article, then a photograph,
    # then the shortest name, since components are named at greater length
    # than the site that contains them.
    # The reference number says which is which: a listed site carries a bare
    # number ("866", "263bis"), each of its components the same number with a
    # part suffix ("866-001", "263bis-002"). Grouping on the stem puts the
    # Côa Valley's rock-art panels back inside the Côa Valley, and the parent
    # — the one with no suffix — is the entry to keep.
    best: dict[tuple, dict] = {}
    for rec in out:
        stem = rec["whs"].split("-")[0]
        rec["whs_stem"] = stem
        key = (rec["iso3"], stem)
        rank = (rec["whs"] == stem, bool(rec.get("wiki")),
                bool(rec.get("image")), -len(rec["name"]))
        have = best.get(key)
        if not have or rank > have[0]:
            best[key] = (rank, rec)
    folded = len(out) - len(best)
    out = [r for _, r in best.values()]
    if folded:
        print(f"  folded {folded} component parts into their listed site")

    out.sort(key=lambda r: (r["iso3"], r["name"]))
    print(f"  {len(out)} sites across {len({r['iso3'] for r in out})} countries"
          + (f" ({blank} countries failed)" if blank else ""))

    # Parks resolve every photo to a final URL at build time, which costs one
    # HTTP call per park. At 1,200+ sites that would take an hour. These keep
    # the Commons filename instead and the page builds the URL, lazily, for
    # the one country on screen — a few dozen images, not twelve hundred.
    done = sum(1 for r in out if r.get("image"))
    print(f"  {done} with a photograph")
    return {"sites": out,
            "source": "Wikidata (P757, UNESCO World Heritage Site reference); "
                      "photographs from Wikimedia Commons"}


def main() -> None:
    if "--unesco" in sys.argv:
        save("unesco.json", build_unesco())
        return
    if "--parks" in sys.argv:
        save("parks.json", build_parks())
        return
    if "--airports" in sys.argv:
        save("airports.json", build_airports())
        return
    if "--cities" in sys.argv:
        save("cities.json", build_cities())
        return
    if "--climate" in sys.argv:
        facts = json.loads((OUT / "country_facts.json").read_text())
        save("climate.json", build_climate(facts))
        return
    print("building reference data")
    facts = build_facts()
    save("country_facts.json", facts)
    save("visa.json", build_visa())
    save("population.json", build_population())
    save("price_level.json", build_prices())
    save("tourism_economy.json", build_economy())
    print("\nnow run:  python build_reference_data.py --cities")
    print("     and:  python build_reference_data.py --climate")


if __name__ == "__main__":
    main()
