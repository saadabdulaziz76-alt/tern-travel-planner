"""Everything TNAT knows about a country beyond how many people visit it.

All of it is read from `data/reference/`, built once by
`build_reference_data.py`. Nothing here touches the network.

The one rule carried over from the arrivals layer: no number is invented. Where
a figure rests on an assumption — carbon factors above all — the assumption is
returned alongside the number so the page can print it.
"""
from __future__ import annotations

import json
import ssl
from functools import lru_cache
from itertools import permutations
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

REF = Path(__file__).resolve().parent.parent / "data" / "reference"


def _load(name: str) -> dict:
    p = REF / name
    return json.loads(p.read_text()) if p.exists() else {}


facts = lru_cache(maxsize=1)(lambda: _load("country_facts.json"))
visa_table = lru_cache(maxsize=1)(lambda: _load("visa.json"))
population = lru_cache(maxsize=1)(lambda: _load("population.json"))
price_level = lru_cache(maxsize=1)(lambda: _load("price_level.json"))
economy = lru_cache(maxsize=1)(lambda: _load("tourism_economy.json"))
climate = lru_cache(maxsize=1)(lambda: _load("climate.json"))
cities = lru_cache(maxsize=1)(lambda: _load("cities.json"))


# ----------------------------------------------------------------- cities
def search_cities(iso3: str, q: str = "", limit: int = 12) -> list[dict]:
    """Cities in one country matching a prefix, biggest and capitals first.

    Scoped to a country on purpose: "Springfield" is ambiguous worldwide and
    obvious once you know which country is meant.
    """
    rows = cities().get((iso3 or "").upper(), [])
    needle = (q or "").strip().lower()
    hits = []
    for name, state, lat, lon, pop, cap in rows:
        n = name.lower()
        if not needle:
            rank = 0
        elif n.startswith(needle):
            rank = 1
        elif needle in n or needle in (state or "").lower():
            rank = 2
        else:
            continue
        hits.append((rank, -cap, -pop, {"city": name, "state": state,
                                        "lat": lat, "lon": lon,
                                        "population": pop, "capital": bool(cap)}))
    hits.sort(key=lambda h: h[:3])
    return [h[3] for h in hits[:limit]]


def find_city(q: str, limit: int = 10) -> list[dict]:
    """Search every country at once, for someone who has not set a home."""
    needle = (q or "").strip().lower()
    if len(needle) < 2:
        return []
    hits = []
    for iso3, rows in cities().items():
        for name, state, lat, lon, pop, cap in rows:
            n = name.lower()
            if n.startswith(needle):
                rank = 1
            elif needle in n:
                rank = 2
            else:
                continue
            hits.append((rank, -cap, -pop, {
                "city": name, "state": state, "iso3": iso3,
                "lat": lat, "lon": lon, "population": pop, "capital": bool(cap)}))
    hits.sort(key=lambda h: h[:3])
    return [h[3] for h in hits[:limit]]


# ------------------------------------------------------------------ parks
parks_file = lru_cache(maxsize=1)(lambda: _load("parks.json"))
unesco_file = lru_cache(maxsize=1)(lambda: _load("unesco.json"))
airports_file = lru_cache(maxsize=1)(lambda: _load("airports.json"))

IMAGE_BASE = "https://commons.wikimedia.org/wiki/Special:FilePath/"


def commons_thumb(filename: str, width: int = 640) -> str:
    """A direct Commons thumbnail URL, skipping the redirect.

    `Special:FilePath` works but 302s to upload.wikimedia.org for every image;
    a page of 118 of them crawled, with one picture in eight arriving after
    eight seconds. The thumbnail path is derivable — md5 of the underscored
    filename gives the two directory segments — so the browser can fetch the
    final URL directly and in parallel.
    """
    import hashlib
    import urllib.parse
    name = urllib.parse.unquote(filename).replace(" ", "_")
    digest = hashlib.md5(name.encode("utf-8")).hexdigest()
    enc = urllib.parse.quote(name)
    return (f"https://upload.wikimedia.org/wikipedia/commons/thumb/"
            f"{digest[0]}/{digest[:2]}/{enc}/{width}px-{enc}")


def _public_host(url: str | None) -> str | None:
    """Wikipedia's API hands back thumb.wikimedia.org, which browsers do not
    resolve. upload.wikimedia.org serves the identical path and is the host
    every Wikipedia page itself uses."""
    if not url:
        return None
    return url.replace("//thumb.wikimedia.org/", "//upload.wikimedia.org/")


def park_photo(park: dict, large: bool = False) -> str | None:
    """A freely licensed photograph, referenced rather than copied.

    `photo_url` was resolved to a final upload.wikimedia.org address at build
    time, so there is no redirect to follow here. Special:FilePath remains the
    fallback for the handful with no Wikipedia article.
    """
    if large and park.get("photo_full"):
        return _public_host(park["photo_full"])
    if park.get("photo_url"):
        return _public_host(park["photo_url"])
    return park_photo_fallback(park, 1280 if large else 640)


def park_photo_fallback(park: dict, width: int = 640) -> str | None:
    """The slow-but-certain URL, used only if the direct thumbnail misses.

    Wikidata's P18 is already percent-encoded, so it must be decoded before
    being encoded again — quoting twice turned every space into %2520.
    """
    if park.get("image"):
        import urllib.parse
        name = urllib.parse.unquote(park["image"])
        return f"{IMAGE_BASE}{urllib.parse.quote(name)}?width={width}"
    return None


@lru_cache(maxsize=1)
def parks() -> list[dict]:
    out = []
    for p in parks_file().get("parks", []):
        out.append({**p, "photo": park_photo(p),
                    "photo_large": park_photo(p, large=True),
                    "photo_fallback": park_photo_fallback(p)})
    return out


# ---------------------------------------------------------- world heritage
# Photos are Commons filenames rather than resolved URLs: a park page shows a
# hundred images and resolving each one at build time is worth it, but there
# are 1,500 sites here and only one country is ever on screen. The browser
# follows the Special:FilePath redirect itself, lazily.
COMMONS = "https://commons.wikimedia.org/wiki/Special:FilePath/"


def heritage_photo(site: dict, width: int = 640) -> str | None:
    """Commons URL for a site's photograph.

    The filename comes off the end of a Wikidata image URL and is already
    percent-encoded, so encoding it again turned "Aeolian%20Islands.jpg" into
    "Aeolian%2520Islands.jpg" and every photo 404'd. Decode first, then encode
    once. The parks pipeline hit this same bug.
    """
    img = site.get("image")
    if not img:
        return None
    from urllib.parse import quote, unquote
    return f"{COMMONS}{quote(unquote(img))}?width={width}"


# Special:FilePath redirects on every single request, so a page of seventy of
# them crawls — the parks pipeline hit this and solved it by resolving each
# URL at build time, one HTTP call per park. There are 1,500 sites here, so
# instead the Commons API resolves them in bulk: fifty filenames per request,
# two requests for a country, cached for the life of the process.
_THUMBS: dict[tuple, str] = {}


def resolve_thumbs(files: list[str], width: int = 640) -> dict:
    """Commons filename -> direct thumbnail URL, fifty at a time."""
    import json as _json
    import urllib.request
    from urllib.parse import quote, unquote

    want = [f for f in files if f and (f, width) not in _THUMBS]
    for i in range(0, len(want), 50):
        batch = want[i:i + 50]
        titles = "|".join("File:" + unquote(f) for f in batch)
        url = ("https://commons.wikimedia.org/w/api.php?action=query&format=json"
               "&prop=imageinfo&iiprop=url&iiurlwidth=" + str(width)
               + "&titles=" + quote(titles, safe="|:"))
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "TNAT-course-project/1.0"})
            data = _json.loads(urllib.request.urlopen(req, timeout=25).read())
        except Exception:
            continue
        for page in (data.get("query", {}).get("pages", {}) or {}).values():
            info = (page.get("imageinfo") or [{}])[0]
            thumb = info.get("thumburl") or info.get("url")
            name = (page.get("title") or "").removeprefix("File:")
            if thumb and name:
                # Same host swap the parks needed: browsers do not resolve
                # thumb.wikimedia.org, upload.wikimedia.org serves the same path.
                _THUMBS[(name, width)] = _public_host(thumb)
    # key on both the raw and decoded filename, since callers have either
    out = {}
    for f in files:
        if not f:
            continue
        hit = _THUMBS.get((f, width)) or _THUMBS.get((unquote(f), width))
        if hit:
            out[f] = hit
    return out


def heritage(iso3: str | None = None) -> list[dict]:
    """World Heritage sites, optionally for one country."""
    iso = (iso3 or "").upper()
    out = []
    for s in unesco_file().get("sites", []):
        if iso and s["iso3"] != iso:
            continue
        out.append({**s, "photo": heritage_photo(s),
                    "photo_large": heritage_photo(s, 1280),
                    "unesco_url": f"https://whc.unesco.org/en/list/{s['whs_stem']}"})
    # One country at a time, so this is two API calls, not fifteen hundred.
    if iso:
        thumbs = resolve_thumbs([r.get("image") for r in out], 640)
        big = resolve_thumbs([r.get("image") for r in out], 1280)
        for r in out:
            img = r.get("image")
            if img and img in thumbs:
                r["photo"] = thumbs[img]
            if img and img in big:
                r["photo_large"] = big[img]
    return out


def heritage_countries() -> list[dict]:
    """Which countries have sites, and how many, for the picker."""
    counts: dict[str, int] = {}
    for s in unesco_file().get("sites", []):
        counts[s["iso3"]] = counts.get(s["iso3"], 0) + 1
    rows = [{"iso3": k, "name": facts().get(k, {}).get("name", k), "n": v}
            for k, v in counts.items()]
    rows.sort(key=lambda r: r["name"])
    return rows


def heritage_by_id(sid: str) -> dict | None:
    return next((s for s in heritage() if s["id"] == sid), None)


def park_by_id(pid: str) -> dict | None:
    return next((p for p in parks() if p["id"] == pid), None)


# --------------------------------------------------------- travellers' picks
# Attendance answers "which parks are busiest", which is not the same question
# as "which would a traveller choose first" -- and it could not answer even
# that for Canada, where only two parks publish a figure. These five apiece are
# a hand-picked editorial list, the parks that top traveller guides and that
# most people would name first. There is no data behind the order, and the
# panel that shows them says so rather than implying a measurement.
#
# Keyed on (country, exact name): Glacier National Park exists in both the
# United States and Canada and they are different places.
FIRST_PICKS: dict[str, list[tuple[str, str]]] = {
    "USA": [
        ("Yosemite National Park",
         "Granite walls and waterfalls — the valley most people picture first."),
        ("Grand Canyon National Park",
         "A mile deep and so wide the far rim fades; nothing prepares you."),
        ("Yellowstone National Park",
         "Geysers, hot springs and the easiest wildlife watching in the country."),
        ("Zion National Park",
         "Red canyon walls you walk between, and the river route through them."),
        ("Glacier National Park",
         "Going-to-the-Sun Road, turquoise lakes and peaks on every side."),
    ],
    "CAN": [
        ("Banff National Park",
         "Lake Louise and Moraine Lake — the postcard the Rockies are sold on."),
        ("Jasper National Park",
         "The Icefields Parkway in, glaciers you can stand on, dark skies at night."),
        ("Gros Morne National Park",
         "Fjords cut into Newfoundland and the Tablelands, bare rock from the mantle."),
        ("Pacific Rim National Park Reserve",
         "Rainforest meeting open Pacific, with Long Beach and winter storm watching."),
        ("Cape Breton Highlands National Park",
         "The Cabot Trail runs along the headlands; whales offshore in summer."),
    ],
}


def first_picks(iso3: str) -> list[dict]:
    """The curated five for one country, joined to the real park records.

    A pick that no longer matches a park in the dataset is dropped rather than
    invented, so the panel can never show a park the rest of the app does not
    have. The test suite asserts that nothing is ever dropped.
    """
    by_name = {(p["iso3"], p["name"]): p for p in parks()}
    out = []
    for name, why in FIRST_PICKS.get(iso3, []):
        hit = by_name.get((iso3, name))
        if not hit:
            continue
        out.append({"id": hit["id"], "name": hit["name"], "state": hit["state"],
                    "photo": hit["photo"], "why": why,
                    "visitors": hit.get("visitors"),
                    "year": hit.get("visitors_year")})
    return out


def nearest_airport(lat: float, lon: float, big_only: bool = False) -> dict | None:
    """The airport you would actually fly into for somewhere remote."""
    best = None
    for iata, name, alat, alon, cc, large in airports_file().get("airports", []):
        if big_only and not large:
            continue
        km = haversine((lat, lon), (alat, alon))
        if best is None or km < best["km"]:
            best = {"iata": iata, "name": name, "lat": alat, "lon": alon,
                    "country": cc, "large": bool(large), "km": round(km)}
    return best


# ------------------------------------------------------------- booking links
# We hold no fares and no hotel inventory, and buying either would cost money
# this project does not have. Inventing them is the one thing that would be
# worse. So the app does the part it can do honestly -- naming the airports you
# would really fly between, from our own airports dataset, and the city you
# would really stay in -- and then hands the search to the sites that do hold
# live prices. Nothing here is a quote; every link opens a live search.

def flight_search(from_iata: str, to_iata: str, direct: bool = True) -> dict:
    """Live flight searches between two real airports. No fares of our own.

    We hold no schedules, so we cannot tell you a direct flight exists. What
    we can do is ask the question for you: these searches are filtered to
    non-stop, so the site answers it on the first screen rather than burying
    it behind three connections.
    """
    f, t = from_iata.upper(), to_iata.upper()
    sky = f"https://www.skyscanner.net/transport/flights/{f.lower()}/{t.lower()}/"
    return {
        "Skyscanner": sky + ("?preferdirects=true" if direct else ""),
        "Google Flights": "https://www.google.com/travel/flights?q="
                          + _q(f"{'nonstop ' if direct else ''}flights from {f} to {t}"),
        "Wego": f"https://www.wego.com/flights/{f}/{t}",
    }


def stay_search(city: str, country: str = "") -> dict:
    """Live accommodation searches for one city. No rates of our own."""
    where = f"{city}, {country}".strip().strip(",")
    return {
        "Booking.com": "https://www.booking.com/searchresults.html?ss=" + _q(where),
        "Airbnb": "https://www.airbnb.com/s/" + _q(where) + "/homes",
        "Google Hotels": "https://www.google.com/travel/search?q=" + _q(f"hotels in {where}"),
    }


# Michelin publishes for a limited set of countries. Sending someone to a
# Michelin search for Windhoek returns nothing and makes the app look broken,
# so the link only appears where the guide actually has a selection. This list
# is conservative and will lag their expansions -- a missing link is a smaller
# failure than a dead one. Lonely Planet covers essentially everywhere and is
# always offered.
MICHELIN = {
    # Europe
    "FRA", "ITA", "ESP", "PRT", "DEU", "GBR", "IRL", "NLD", "BEL", "LUX",
    "CHE", "AUT", "DNK", "SWE", "NOR", "FIN", "ISL", "POL", "CZE", "HUN",
    "HRV", "SVN", "GRC", "MLT", "EST", "SRB", "TUR",
    # Americas
    "USA", "CAN", "MEX", "BRA", "ARG",
    # Asia
    "JPN", "KOR", "CHN", "HKG", "MAC", "TWN", "SGP", "MYS", "THA", "VNM",
    # Middle East and Africa
    "ARE", "QAT", "MAR",
}


def tour_search(city: str, country: str = "") -> dict:
    """Guided days in one city. Marketplaces, so there is something to book.

    The itinerary says what kind of guide to look for; this is where you go to
    find one. We take no commission, hold no listings and show no prices.
    """
    where = f"{city} {country}".strip()
    return {
        # marketplaces: operators and professional guides
        "GetYourGuide": "https://www.getyourguide.com/s/?q=" + _q(where),
        "Viator": "https://www.viator.com/search/" + _q(where),
        # marketplaces: individual hosts rather than firms
        "Withlocals": "https://www.withlocals.com/search/?q=" + _q(where),
        "Airbnb Experiences": "https://www.airbnb.com/s/" + _q(where) + "/experiences",
        # The official board is the only one of these that can tell you who is
        # actually licensed, which in some cities is a legal requirement rather
        # than a nicety. It belongs in the list for that reason alone.
        "Official tourist board": "https://www.google.com/search?q="
            + _q(f"{where} official tourist board licensed tour guides"),
    }


def guide_links(city: str, country: str = "", iso3: str = "") -> dict:
    """Published guides for one city. Links to their search, never their text.

    Neither publisher has an open API, and copying their write-ups or their
    star ratings would be both unverifiable and somebody else's work. So this
    does what the booking handoff does: it takes you to their own search.
    """
    where = f"{city} {country}".strip()
    out = {"Lonely Planet": "https://www.lonelyplanet.com/search?q=" + _q(where)}
    if (iso3 or "").upper() in MICHELIN:
        out["Michelin Guide"] = "https://guide.michelin.com/en/search?q=" + _q(where)
    return out


def _q(text: str) -> str:
    from urllib.parse import quote
    return quote(text, safe="")


def airports_near(lat: float, lon: float, radius_km: int = 250,
                  limit: int = 7, big_only: bool = True) -> list[dict]:
    """Every airport you could reasonably set out from, nearest first.

    The nearest large airport is not the same as the one with a non-stop.
    From New Haven the closest is Bradley; the transatlantic departures are at
    JFK and Newark, an hour further on. OurAirports calls all three
    `large_airport`, so nothing in our data can pick the hub out — and we hold
    no schedules to settle it. So we stop pretending to choose: list the
    airports within driving range and let the direct-only search say which one
    actually flies there.
    """
    out = []
    for iata, name, alat, alon, cc, large in airports_file().get("airports", []):
        if big_only and not large:
            continue
        km = haversine((lat, lon), (alat, alon))
        if km <= radius_km:
            out.append({"iata": iata, "name": name, "km": round(km),
                        "country": cc, "large": bool(large)})
    out.sort(key=lambda a: a["km"])
    return out[:limit]


def nearest_town(lat: float, lon: float, iso3: str, min_pop: int = 5_000) -> dict | None:
    """Somewhere to sleep: the closest real town, not the closest city."""
    best = None
    for name, state, clat, clon, pop, cap in cities().get(iso3, []):
        if pop < min_pop:
            continue
        km = haversine((lat, lon), (clat, clon))
        if best is None or km < best["km"]:
            best = {"city": name, "state": state, "km": round(km),
                    "population": pop, "lat": clat, "lon": clon}
    return best


# Below this, flying somewhere you could simply drive is a waste of a day.
DRIVE_RATHER_THAN_FLY = 900


def journey_to_park(origin: tuple, origin_iso3: str, park: dict) -> dict:
    """How you would actually get there, leg by leg.

    Three stages, each measured: the long haul to a sensible airport, the drive
    from that airport to a town worth sleeping in, and the last hop to the park
    gate. When the whole thing is drivable it says so instead of inventing a
    flight.
    """
    plat, plon = park["lat"], park["lon"]
    direct_km = haversine(origin, (plat, plon))
    town = nearest_town(plat, plon, park["iso3"])
    air = nearest_airport(plat, plon)
    home_air = nearest_airport(origin[0], origin[1], big_only=True)

    legs = []
    if direct_km <= DRIVE_RATHER_THAN_FLY:
        # Drive to the town you will sleep in, not to the park itself — the
        # last leg below then covers the gate, so the two do not overlap.
        to = (f"{town['city']}, {town['state']}" if town else park["name"])
        km = (haversine(origin, (town["lat"], town["lon"])) if town else direct_km)
        legs.append({"stage": "drive", "from": "home", "to": to,
                     "km": round(km), "mode": "drive",
                     "note": "close enough to drive the whole way",
                     **journey_time("drive", km)})
    else:
        if home_air and air:
            fly_km = haversine((home_air["lat"], home_air["lon"]),
                               (air["lat"], air["lon"]))
            legs.append({"stage": "fly", "from": f"{home_air['iata']} ({home_air['name']})",
                         "to": f"{air['iata']} ({air['name']})",
                         "km": round(fly_km), "mode": "fly",
                         "note": "nearest airport with scheduled service to the park",
                         **journey_time("fly", fly_km)})
        if air and town:
            km = haversine((air["lat"], air["lon"]), (town["lat"], town["lon"]))
            legs.append({"stage": "transfer",
                         "from": air["iata"] if air else "airport",
                         "to": f"{town['city']}, {town['state']}",
                         "km": round(km), "mode": "drive",
                         "note": "hire a car or take a shuttle; most parks have no "
                                 "public transport",
                         **journey_time("drive", km)})
    if town:
        km = haversine((town["lat"], town["lon"]), (plat, plon))
        legs.append({"stage": "last", "from": f"{town['city']}, {town['state']}",
                     "to": f"{park['name']} gate", "km": round(km), "mode": "drive",
                     "note": "taxi, ride-hail or your own car from where you sleep",
                     **journey_time("drive", km)})
    return {"direct_km": round(direct_km), "drivable": direct_km <= DRIVE_RATHER_THAN_FLY,
            "legs": legs, "base_town": town, "airport": air, "home_airport": home_air,
            "caveat": "Distances are great-circle and the times are estimates from "
                      "them, not timetables. Remote parks often have one road in "
                      "and seasonal closures — check before you book."}


# --------------------------------------------------------------- geocoding
# A gazetteer of towns over 15,000 people cannot answer "where do people go for
# a weekend". Montauk has 3,326 residents, Lenox 1,675, Cooperstown 1,792 — all
# real destinations, none of them in a cities15000 file. So the scout names
# places and this resolves them; the data then decides whether they are
# actually in range.
GEOCACHE = REF / "geocache.json"
_geo_cache: dict | None = None


def _cache() -> dict:
    global _geo_cache
    if _geo_cache is None:
        try:
            _geo_cache = json.loads(GEOCACHE.read_text())
        except (OSError, json.JSONDecodeError):
            _geo_cache = {}
    return _geo_cache


def _cache_save() -> None:
    try:
        GEOCACHE.parent.mkdir(parents=True, exist_ok=True)
        GEOCACHE.write_text(json.dumps(_cache(), separators=(",", ":"), sort_keys=True))
    except OSError:
        pass


def geocode(name: str, limit: int = 8) -> list[dict]:
    """Every place with this name, from the local gazetteer then the network.

    Cached to disk, because the same handful of towns come back constantly and
    a weekend page should not wait on an API it does not need.
    """
    key = (name or "").strip().lower()
    if not key:
        return []
    if key in _cache():
        return _cache()[key]

    hits = []
    for iso3, rows in cities().items():
        for cname, state, lat, lon, pop, cap in rows:
            if cname.lower() == key:
                hits.append({"name": cname, "state": state, "iso3": iso3,
                             "lat": lat, "lon": lon, "population": pop,
                             "source": "gazetteer"})
    try:
        import urllib.parse
        import urllib.request
        url = ("https://geocoding-api.open-meteo.com/v1/search?count=10&language=en"
               "&name=" + urllib.parse.quote(name))
        req = urllib.request.Request(url, headers={"User-Agent": "TNAT-course-project/1.0"})
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        data = json.loads(urllib.request.urlopen(req, timeout=12, context=ctx).read())
        seen = {(h["lat"], h["lon"]) for h in hits}
        for r in data.get("results", []):
            pt = (round(r["latitude"], 4), round(r["longitude"], 4))
            if pt in seen:
                continue
            hits.append({"name": r["name"], "state": r.get("admin1") or "",
                         "iso3": _iso2_to_iso3().get(r.get("country_code", ""), ""),
                         "lat": pt[0], "lon": pt[1],
                         "population": r.get("population") or 0, "source": "geocoder"})
    except Exception:
        pass                       # the gazetteer answer alone is still useful

    hits = hits[:limit]
    _cache()[key] = hits
    _cache_save()
    return hits


@lru_cache(maxsize=1)
def _iso2_to_iso3() -> dict:
    return {v["iso2"]: k for k, v in
            json.loads((REF.parent / "iso_registry.json").read_text()).items()
            if v.get("iso2")}


def resolve_place(name: str, region: str | None, origin: tuple,
                  max_km: float, min_pop: int = 1_000) -> dict | None:
    """Pick which place of this name was meant: the one you could actually go to.

    "Newport" is in Kentucky, Rhode Island and Wales. From New York only one is
    a weekend away, so range does most of the disambiguating and the stated
    region settles the rest.
    """
    want = (name or "").strip().lower()
    best = None
    for h in geocode(name):
        if not h.get("iso3"):
            continue
        km = haversine(origin, (h["lat"], h["lon"]))
        if km > max_km:
            continue
        # There is a Lisbon, Maryland with 282 residents. Letting a hamlet
        # stand in for the place the scout actually named is worse than
        # dropping the suggestion: Montauk has 3,326 and Lenox 1,675, so a
        # floor of a thousand keeps the real destinations out of harm's way.
        pop = h.get("population") or 0
        if pop and pop < min_pop:
            continue
        score = km
        if region and region.lower()[:6] in (h["state"] or "").lower():
            score -= max_km            # a stated region wins outright
        # "Cold Spring" is not "Cold Spring Harbor" — a different town 30 km
        # away. Without this the nearest fuzzy match won and quietly replaced
        # the place that was actually meant.
        if h["name"].strip().lower() != want:
            score += max_km * 1.5
        if best is None or score < best[0]:
            best = (score, {**h, "km": round(km), "_km": km,
                            "exact": h["name"].strip().lower() == want})
    return best[1] if best else None


# ---------------------------------------------------------------- getaways
# Modes are inferred from distance and land borders, not from timetables. The
# UI says so: this answers "is driving even possible", not "is there a 7:40
# service on Fridays".
DRIVE_LIMIT = 900          # beyond this most people stop considering a drive
TRAIN_LIMIT = 1200
# Fixed crossings that carry road or rail over water, so the two countries are
# connected even though they share no land border. Without these, Paris to
# London came back "fly or ferry" and no Eurostar.
FIXED_LINKS = {frozenset(("GBR", "FRA")), frozenset(("DNK", "SWE")),
               frozenset(("MYS", "SGP")), frozenset(("BHR", "SAU"))}


# Effective speeds, not top speeds: they include the stopping, the queueing and
# the getting to the station. Overheads are the fixed cost of using that mode at
# all — two and a half hours for a flight is check-in, security and the ride in
# from the airport at both ends.
SPEEDS = {
    "drive": (75, 0.25), "bus": (60, 0.6), "train": (120, 0.4),
    "fly": (750, 3.0), "ferry": (35, 1.0),
}
# With the first numbers the train/plane crossover sat at 270 km, which made
# Paris-London a flight. Eurostar does it city centre to city centre in 2 h 16;
# flying is nearer four hours once both airports are counted. At 120 km/h for
# rail and a three-hour flying overhead the crossover lands near 370 km, which
# is about right for ordinary intercity track. Genuine high-speed lines beat
# this estimate and the note says so.
MODE_DETAIL = {
    "drive": "Door to door, and you keep the car at the other end. Add time for "
             "city traffic at both ends and for parking once you arrive.",
    "bus": "Usually the cheapest option and the slowest. Coaches use the same "
           "roads as cars but stop on the way, so budget more than the drive.",
    "train": "City centre to city centre, which is why it often beats flying at "
             "this range even when the flight is quicker in the air.",
    "fly": "The flight itself is the short part. The estimate includes getting "
           "to the airport, security, and the ride into town at the far end.",
    "ferry": "Slow, weather-dependent and usually seasonal. Check sailings exist "
             "on your dates before planning around it.",
}


def journey_time(mode: str, km: float) -> dict:
    """A time estimate from distance, never a timetable.

    Deliberately a range: the point is "is this a morning or a whole day", not
    "you arrive at 14:32".
    """
    speed, overhead = SPEEDS.get(mode, (70, 0.5))
    hours = km / speed + overhead
    lo, hi = hours * 0.85, hours * 1.3
    fmt = lambda h: (f"{round(h * 60)} min" if h < 1
                     else f"{h:.0f} h" if abs(h - round(h)) < 0.15
                     else f"{int(h)} h {round((h - int(h)) * 60)} min")
    return {"hours": round(hours, 1), "low": round(lo, 1), "high": round(hi, 1),
            "range": f"{fmt(lo)} – {fmt(hi)}",
            "basis": "estimated from distance and typical speeds, including the "
                     "time it takes to get to and from the station or airport — "
                     "not a timetable. High-speed rail beats this; rural lines "
                     "and ferries in winter do not."}


def transport_modes(origin_iso: str, dest_iso: str, km: float) -> list[dict]:
    """Plausible ways to cover this hop, with the reason and a time estimate."""
    f = facts()
    same = origin_iso == dest_iso
    neighbour = dest_iso in (f.get(origin_iso, {}).get("borders") or [])
    linked = frozenset((origin_iso, dest_iso)) in FIXED_LINKS
    land = same or neighbour or linked
    out = []
    if land and km <= DRIVE_LIMIT:
        out.append({"mode": "drive", "why": "same country" if same
                    else "fixed crossing" if linked else "shares a land border"})
        out.append({"mode": "bus", "why": "coach routes follow the same roads"})
    if land and 40 <= km <= TRAIN_LIMIT:
        out.append({"mode": "train", "why": "rail is usually the easy option at this range"})
    if km >= 250 or not land:
        out.append({"mode": "fly", "why": "no land route" if not land
                    else "far enough that flying saves a day"})
    if not land and not f.get(dest_iso, {}).get("landlocked")             and not f.get(origin_iso, {}).get("landlocked") and km <= 600:
        out.append({"mode": "ferry", "why": "both coasts, short crossing"})
    out = out or [{"mode": "fly", "why": "no land route"}]
    for m in out:
        m.update(journey_time(m["mode"], km))
        m["detail"] = MODE_DETAIL.get(m["mode"], "")
    return out


def getaways(lat: float, lon: float, home_iso: str, max_km: float = 600,
             min_pop: int = 15_000, limit: int = 9, min_km: float = 50,
             exclude_city: str | None = None, per_state: int = 2,
             spread: bool = False) -> list[dict]:
    """Places worth a short trip from a given point.

    Ranking by "nearest and biggest" was wrong, and wrong in a way that is
    obvious once you see it: from New York it returned Stamford, Levittown and
    Bensalem — commuter towns nobody takes a weekend in — while Newport,
    Kingston and Poughkeepsie sat in the data unused because they are small.

    Two changes. Dormitory towns are dropped: anywhere with a city three times
    its size within 35 km is a satellite of that city, not a destination. And
    with `spread`, candidates are drawn evenly across compass sectors and
    distance bands rather than by population, so a wide net reaches the small
    towns a getaway actually means. The scout then picks from that.
    """
    here = (lat, lon)
    rows = []
    for iso3, entries in cities().items():
        for name, state, clat, clon, pop, cap in entries:
            if pop < min_pop or (exclude_city and name == exclude_city):
                continue
            km = haversine(here, (clat, clon))
            if km < min_km or km > max_km:
                continue
            rows.append({"city": name, "state": state, "iso3": iso3,
                         "country": facts().get(iso3, {}).get("name", iso3),
                         "km": round(km), "_km": km, "lat": clat, "lon": clon,
                         "population": pop, "capital": bool(cap),
                         "abroad": iso3 != home_iso})

    # A town in the shadow of a much larger one is that city's suburb.
    big = sorted(rows, key=lambda r: -r["population"])[:400]
    def satellite(r):
        for b in big:
            if b["population"] >= r["population"] * 3 \
                    and haversine((r["lat"], r["lon"]), (b["lat"], b["lon"])) < 35:
                return True
        return False
    rows = [r for r in rows if not satellite(r)]

    if spread:
        # even coverage of the map rather than a cluster round the nearest city
        import math
        buckets: dict[tuple, list] = {}
        for r in rows:
            bearing = math.degrees(math.atan2(r["lon"] - lon, r["lat"] - lat)) % 360
            sector = int(bearing // 45)                 # eight directions
            band = min(int(r["_km"] / max(max_km / 4, 1)), 3)
            buckets.setdefault((sector, band), []).append(r)
        for b in buckets.values():
            b.sort(key=lambda r: -r["population"])
        out, i = [], 0
        while len(out) < limit and any(len(b) > i for b in buckets.values()):
            for b in buckets.values():
                if len(b) > i and len(out) < limit:
                    out.append(b[i])
            i += 1
        picked = sorted(out, key=lambda r: r["_km"])
    else:
        for r in rows:
            r["_score"] = r["_km"] / max_km - min(r["population"], 5e6) / 5e6 * 0.45
        rows.sort(key=lambda r: r["_score"])
        picked, seen_state = [], {}
        for r in rows:
            key = (r["iso3"], r["state"])
            if seen_state.get(key, 0) >= per_state:
                continue
            seen_state[key] = seen_state.get(key, 0) + 1
            picked.append(r)
            if len(picked) == limit:
                break

    for r in picked:
        r["modes"] = transport_modes(home_iso, r["iso3"], r["_km"])
        for k in ("_km", "_score", "lat", "lon"):
            r.pop(k, None)
    return picked


def city_point(iso3: str, city: str) -> dict | None:
    """Exact match for a stored choice, so a reload does not drift."""
    for row in cities().get((iso3 or "").upper(), []):
        if row[0].lower() == (city or "").lower():
            return {"city": row[0], "state": row[1], "lat": row[2], "lon": row[3]}
    return None


# --------------------------------------------------------------- distance
def haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle kilometres between two (lat, lon) points."""
    lat1, lon1, lat2, lon2 = map(radians, (*a, *b))
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(h))


def point(iso3: str) -> tuple[float, float] | None:
    f = facts().get(iso3)
    return (f["lat"], f["lon"]) if f else None


def distance_km(a: str, b: str) -> float | None:
    """Capital to capital. A traveller flies to the city, not the centroid."""
    pa, pb = point(a), point(b)
    return round(haversine(pa, pb), 1) if pa and pb else None


# ----------------------------------------------------------------- carbon
# UK DEFRA / DESNZ 2023 greenhouse gas conversion factors, economy class,
# kg CO2e per passenger-kilometre. Great-circle distance understates the route
# actually flown and these exclude the radiative-forcing uplift, so the figure
# is a floor, not a worst case. Both caveats are returned with the number.
CARBON = ((1000, 0.246, "short haul"), (3700, 0.151, "medium haul"),
          (float("inf"), 0.148, "long haul"))
CARBON_SOURCE = ("UK DEFRA/DESNZ 2023 conversion factors, economy class, "
                 "great-circle distance, no radiative-forcing uplift")


def carbon_kg(km: float) -> tuple[float, str]:
    for limit, factor, label in CARBON:
        if km <= limit:
            return round(km * factor, 1), label
    raise AssertionError("unreachable")


# US EPA Greenhouse Gas Equivalencies Calculator, "Calculations and
# References". Every figure here is published; none is estimated by us.
#
#   trees   0.060 t CO2 per urban tree per YEAR. EPA is explicit that this is
#           an annual average over a ten-year growth period, and it does not
#           publish a ten-year total — so the multiplication by ten is ours and
#           the page says so rather than implying EPA stated it.
#   forest  1.00 t CO2 absorbed per acre of average US forest per year.
#   car     4.29 t CO2e from one petrol passenger vehicle per year.
#   home    4.798 t CO2 from one home's electricity for a year.
EPA = {"tree_year": 0.060, "forest_acre_year": 1.00,
       "car_year": 4.29, "home_elec_year": 4.798}
EPA_SOURCE = ("US EPA Greenhouse Gas Equivalencies Calculator, "
              "Calculations and References")
TREE_YEARS = 10


def offsets(tonnes: float) -> dict:
    """What it would take to absorb this much carbon, in published units.

    Deliberately framed as equivalences rather than a plan. Trees need the full
    decade to do it, offset quality varies enormously, and not taking the
    flight beats offsetting it — all of which the page says out loud. A number
    like "plant 100 trees" with none of that attached is the kind of comforting
    arithmetic this app exists not to do.
    """
    t = max(float(tonnes or 0), 0)
    if not t:
        return {"tonnes": 0}
    trees = t / (EPA["tree_year"] * TREE_YEARS)
    return {
        "tonnes": round(t, 2),
        "trees": max(1, round(trees)),
        "tree_years": TREE_YEARS,
        "forest_acres": round(t / EPA["forest_acre_year"], 1),
        "cars_off_road": round(t / EPA["car_year"], 2),
        "homes_powered": round(t / EPA["home_elec_year"], 2),
        "source": EPA_SOURCE,
        "tree_note": (f"EPA publishes {EPA['tree_year']} tonnes per urban tree per "
                      f"year, averaged over a ten-year growth period; the "
                      f"ten-year total is that figure multiplied by ten."),
        # Not "a floor" any more: the trip grouping above can push the carbon
        # figure either way, and it moves the number far more than the
        # per-kilometre factor does.
        "caveat": ("These are equivalences, not a neutralisation plan. The trees "
                   "need the full ten years to absorb it, offset quality varies "
                   "enormously, and a flight not taken beats a flight offset. "
                   "The carbon figure above is an estimate that rests on how many "
                   "separate journeys these countries really were."),
    }


# Countries this close together were almost certainly one journey. Nobody
# flies home to New York between Belgium and the Netherlands.
SAME_TRIP_KM = 2_000


def group_into_trips(points: list[dict], years: dict | None = None) -> list[list[dict]]:
    """Guess which destinations were one journey rather than many.

    Counting a return flight per country was the single biggest error in this
    figure: ten European countries came out at 18.1 t modelled separately,
    against 2.8 t as the one trip it almost certainly was — **6.6 times too
    high**. Years are the strongest signal when the user has tagged them;
    otherwise countries within SAME_TRIP_KM of each other are joined up.
    """
    buckets: dict = {}
    for p in points:
        key = (years or {}).get(p["iso3"]) if years else None
        buckets.setdefault(key, []).append(p)

    trips: list[list[dict]] = []
    for group in buckets.values():
        clusters: list[list[dict]] = []
        for p in group:
            joined = None
            for c in clusters:
                if any(haversine((p["lat"], p["lon"]), (q["lat"], q["lon"]))
                       <= SAME_TRIP_KM for q in c):
                    if joined is None:
                        c.append(p)
                        joined = c
                    else:
                        # p bridges two clusters, so they are one trip
                        joined.extend(c)
                        c.clear()
            if joined is None:
                clusters.append([p])
        trips.extend([c for c in clusters if c])
    return trips


def footprint(home: str, destinations: list[str], origin: tuple | None = None,
              years: dict | None = None) -> dict:
    """Distance and carbon for everywhere someone has been.

    Modelled as a handful of journeys rather than one return flight per
    country. The per-kilometre factors are DEFRA's and stand up — New York to
    London comes out at 1.65 t return, inside the published range — but the
    trip count is what actually drives the total, and counting each country
    separately inflated it severalfold.
    """
    start = origin or point(home)
    pts = []
    for iso in dict.fromkeys(destinations):
        if iso == home:
            continue
        pt = point(iso)
        if pt:
            pts.append({"iso3": iso, "lat": pt[0], "lon": pt[1], "label": iso})
    if not start or not pts:
        return {"home": home, "legs": [], "countries": 0, "trips": 0,
                "total_km": 0, "total_kg_co2e": 0, "tonnes_co2e": 0,
                "furthest": None, "times_around_earth": 0,
                "assumption": "nothing pinned yet", "carbon_source": CARBON_SOURCE,
                "offsets": offsets(0)}

    trips, legs, total_km, total_kg = [], [], 0.0, 0.0
    for group in group_into_trips(pts, years):
        r = route_points(start, group, return_home=True)
        if not r:
            continue
        trip_km = sum(l["km"] for l in r["legs"])
        trip_kg = sum(carbon_kg(l["km"])[0] for l in r["legs"])
        trips.append({"countries": [g["iso3"] for g in r["order"]],
                      "km": round(trip_km), "kg_co2e": round(trip_kg)})
        total_km += trip_km
        total_kg += trip_kg
        legs.extend(r["legs"])

    far = max(pts, key=lambda p: haversine(start, (p["lat"], p["lon"])))
    far_km = haversine(start, (far["lat"], far["lon"]))
    return {
        "home": home, "countries": len(pts), "trips": len(trips),
        "trip_detail": trips, "legs": legs,
        "total_km": round(total_km), "total_kg_co2e": round(total_kg),
        "tonnes_co2e": round(total_kg / 1000, 2),
        "furthest": {"iso3": far["iso3"], "km_each_way": round(far_km)},
        "times_around_earth": round(total_km / 40075, 2),
        "assumption": (f"grouped into {len(trips)} "
                       f"{'journey' if len(trips) == 1 else 'journeys'} rather than "
                       f"one return flight per country — countries within "
                       f"{SAME_TRIP_KM:,} km of each other are treated as one trip"
                       + (", and anything you tagged with the same year is kept "
                          "together" if years else "")),
        "carbon_source": CARBON_SOURCE,
        "offsets": offsets(total_kg / 1000),
    }


# ------------------------------------------------------------------- visa
VISA_LABEL = {
    "self": "your own country", "free": "visa free",
    "arrival": "visa on arrival", "evisa": "e-visa",
    "eta": "travel authorisation", "required": "visa required",
    "banned": "no admission",
}
EASY = {"self", "free", "arrival", "evisa", "eta"}

# `easy` only means "no embassy appointment", and that is not the question a
# traveller is asking. An e-visa or an ETA is paperwork you must hold before
# you board — lumping those under "no visa needed" is how somebody ends up
# turned away at check-in. ACTION says what you actually have to do.
ACTION = {
    "self": "none", "free": "none", "arrival": "on arrival",
    "evisa": "before you travel", "eta": "before you travel",
    "required": "before you travel", "banned": "not permitted",
}
BEFORE_YOU_GO = {"evisa", "eta", "required"}


def visa_status(passport: str, destination: str) -> dict | None:
    row = visa_table().get(passport)
    if not row:
        return None
    code = row.get(destination)
    if code is None:
        return None
    days = None
    if code.startswith("free:"):
        code, days = "free", int(code.split(":")[1])
    return {"code": code, "label": VISA_LABEL.get(code, code),
            "days": days, "easy": code in EASY,
            "action": ACTION.get(code, "before you travel"),
            "advance": code in BEFORE_YOU_GO,
            "detail": f"visa free for {days} days" if days else VISA_LABEL.get(code, code)}


def visa_summary(passport: str, visited: list[str]) -> dict:
    """How much of the world this passport opens, and how much of that is used."""
    row = visa_table().get(passport)
    if not row:
        return {"known": False}
    seen = set(visited)
    easy = [d for d, c in row.items()
            if d != passport and (c.startswith("free:") or c in EASY)]
    return {"known": True, "passport": passport,
            "easy_total": len(easy), "easy_visited": len(seen & set(easy)),
            "easy_unvisited": sorted(set(easy) - seen),
            "needs_visa_total": sum(1 for d, c in row.items()
                                    if c == "required" and d != passport)}


# -------------------------------------------------------------- neighbours
def nearest_unvisited(home: str, visited: list[str], pool: list[str],
                      limit: int = 8, origin: tuple | None = None) -> list[dict]:
    seen = set(visited)
    start = origin or point(home)
    out = []
    for iso in pool:
        if iso in seen or iso == home:
            continue
        there = point(iso)
        km = round(haversine(start, there), 1) if start and there else None
        if km is not None:
            out.append({"iso3": iso, "km": round(km)})
    out.sort(key=lambda d: d["km"])
    return out[:limit]


# ----------------------------------------------------- languages, currencies
def reach(visited: list[str]) -> dict:
    langs, curr, subs = {}, {}, {}
    for iso in visited:
        f = facts().get(iso)
        if not f:
            continue
        for l in f["languages"]:
            langs.setdefault(l, []).append(iso)
        for c in f["currencies"]:
            curr.setdefault(c, []).append(iso)
        if f.get("subregion"):
            subs.setdefault(f["subregion"], []).append(iso)
    return {
        "languages": sorted(langs, key=lambda k: (-len(langs[k]), k)),
        "currencies": sorted(curr, key=lambda k: (-len(curr[k]), k)),
        "n_languages": len(langs), "n_currencies": len(curr),
        "subregions": sorted(subs, key=lambda k: (-len(subs[k]), k)),
        "n_subregions": len(subs),
    }


def blind_spots(visited: list[str], pool: list[str]) -> list[dict]:
    """Sub-regions of the world with nothing pinned in them."""
    seen = set(visited)
    by_sub: dict[str, list[str]] = {}
    for iso in pool:
        f = facts().get(iso)
        if f and f.get("subregion"):
            by_sub.setdefault(f["subregion"], []).append(iso)
    out = []
    for sub, members in by_sub.items():
        hit = [m for m in members if m in seen]
        out.append({"subregion": sub, "countries": len(members),
                    "visited": len(hit), "pct": round(len(hit) / len(members) * 100)})
    out.sort(key=lambda d: (d["pct"], -d["countries"]))
    return out


# ------------------------------------------------------------------ prices
def price_vs(home: str, destination: str) -> dict | None:
    """Relative price level only. The app has no live prices and invents none."""
    pl = price_level()
    a, b = pl.get(home), pl.get(destination)
    if not a or not b:
        return None
    ratio = b / a
    return {"ratio": round(ratio, 2), "destination_level": round(b, 2),
            "home_level": round(a, 2),
            "label": ("about the same as home" if 0.9 <= ratio <= 1.1
                      else f"about {round(1/ratio,1)}x cheaper than home" if ratio < 1
                      else f"about {round(ratio,1)}x pricier than home"),
            "source": "World Bank PPP conversion factor / market exchange rate, 2019"}


# ----------------------------------------------------------------- climate
MONTHS = ["", "January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def best_months(iso3: str, n: int = 3) -> dict | None:
    """Pleasantest months by temperature and rainfall at the capital.

    This is weather, not crowds. No monthly arrivals data exists publicly, so
    the app must not pretend this says anything about how busy a place is.
    """
    c = climate().get(iso3)
    if not c:
        return None
    rows = []
    for m in range(1, 13):
        d = c.get(str(m)) or {}
        t, rain = d.get("t"), d.get("rain")
        if t is None or rain is None:
            continue
        # comfort: distance from 21C, penalised by rainfall
        rows.append({"month": m, "name": MONTHS[m], "t": t, "rain": rain,
                     "score": round(abs(t - 21) + rain / 25, 2)})
    if not rows:
        return None
    rows.sort(key=lambda r: r["score"])
    return {"best": rows[:n], "worst": rows[-1],
            "all": sorted(rows, key=lambda r: r["month"]),
            "basis": "mean temperature and rainfall at the capital, 2021-2023",
            "caveat": "weather only — no public data exists on which months are quietest",
            "source": "Open-Meteo ERA5 archive"}


# ------------------------------------------------------------------- route
def route_points(start: tuple, stops: list[dict], return_home: bool = True) -> dict | None:
    """Order arbitrary labelled points into the shortest run.

    The country-level version could only route capitals. A multi-city trip
    needs real stops — Kyoto is not Tokyo — so this works on whatever points it
    is given and keeps each one's label attached.
    """
    pts = [s for s in stops if s.get("lat") is not None and s.get("lon") is not None]
    if not pts or start is None:
        return None
    idx = list(range(len(pts)))
    at = lambda i: (pts[i]["lat"], pts[i]["lon"])
    d = {}
    for i in idx:
        d[("S", i)] = haversine(start, at(i))
        for j in idx:
            if i != j:
                d[(i, j)] = haversine(at(i), at(j))

    def length(order):
        total = d[("S", order[0])]
        for a, b in zip(order, order[1:]):
            total += d[(a, b)]
        return total + (d[("S", order[-1])] if return_home else 0)

    if len(idx) <= 7:
        best, exact = min(permutations(idx), key=length), True
    else:
        unused, cur, best = set(idx), None, []
        while unused:
            cur = min(unused, key=lambda i: d[("S", i)] if cur is None else d[(cur, i)])
            best.append(cur)
            unused.remove(cur)
        improved = True
        while improved:
            improved = False
            for i in range(len(best) - 1):
                for j in range(i + 2, len(best)):
                    cand = best[:i + 1] + best[i + 1:j + 1][::-1] + best[j + 1:]
                    if length(cand) < length(best) - 1e-9:
                        best, improved = cand, True
        exact = False

    order = [pts[i] for i in best]
    legs = []
    prev = {"label": "home", "lat": start[0], "lon": start[1]}
    for stop in order:
        legs.append({"from": prev.get("label", "home"), "to": stop["label"],
                     "km": round(haversine((prev["lat"], prev["lon"]),
                                           (stop["lat"], stop["lon"])))})
        prev = stop
    if return_home:
        legs.append({"from": prev["label"], "to": "home",
                     "km": round(haversine((prev["lat"], prev["lon"]), start))})
    as_listed = length(list(idx))
    return {"order": order, "legs": legs, "exact": exact,
            "total_km": round(length(best)), "as_listed_km": round(as_listed),
            "saved_km": round(as_listed - length(best))}


def route(home: str, stops: list[str], origin: tuple | None = None) -> dict | None:
    """Shortest order to visit every stop and come home.

    Exact for small parties by brute force; a nearest-neighbour pass with 2-opt
    beyond that, where exhaustive search stops being possible.
    """
    stops = [s for s in dict.fromkeys(stops) if point(s) and s != home]
    start = origin or point(home)
    if not start or not stops:
        return None
    nodes = [home] + stops
    at = lambda i: start if i == home else point(i)
    d = {(a, b): haversine(at(a), at(b)) for a in nodes for b in nodes if a != b}
    leg = lambda o: sum(d[(o[i], o[i + 1])] for i in range(len(o) - 1))

    if len(stops) <= 8:
        best = min(permutations(stops), key=lambda p: leg([home, *p, home]))
        order, exact = list(best), True
    else:
        unvisited, cur, order = set(stops), home, []
        while unvisited:
            cur = min(unvisited, key=lambda s: d[(cur, s)])
            order.append(cur)
            unvisited.remove(cur)
        improved = True
        while improved:                      # 2-opt
            improved = False
            for i in range(len(order) - 1):
                for j in range(i + 2, len(order)):
                    cand = order[:i + 1] + order[i + 1:j + 1][::-1] + order[j + 1:]
                    if leg([home, *cand, home]) < leg([home, *order, home]) - 1e-9:
                        order, improved = cand, True
        exact = False

    best_km = leg([home, *order, home])
    naive_km = leg([home, *stops, home])
    return {"home": home, "order": order, "exact": exact,
            "total_km": round(best_km), "as_listed_km": round(naive_km),
            "saved_km": round(naive_km - best_km),
            "legs": [{"from": a, "to": b, "km": round(d[(a, b)])}
                     for a, b in zip([home, *order], [*order, home])]}
