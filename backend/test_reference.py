"""Tests for the reference layer: distance, visas, carbon, prices, routing."""
from __future__ import annotations

import sys

import reference as R

PASS = FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [ok  ] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}   {extra}")


print("\ndatasets loaded")
for name, d, lo in (("country facts", R.facts(), 240), ("visa table", R.visa_table(), 190),
                    ("population", R.population(), 240), ("price level", R.price_level(), 190),
                    ("tourism economy", R.economy(), 170)):
    check(f"{name} has {lo}+ entries", len(d) >= lo, f"{len(d)}")

print("\ndistance — against published capital-to-capital figures")
# Every expected value here is a published great-circle distance. The first
# build of this file silently used country centroids and put London-Paris at
# 934 km; without these the error would have shipped.
for a, b, expect in [("GBR", "FRA", 344), ("USA", "CAN", 735), ("JPN", "KOR", 1157),
                     ("AUS", "NZL", 2325), ("DEU", "POL", 517), ("IND", "CHN", 3780),
                     ("EGY", "SAU", 1640)]:
    got = R.distance_km(a, b)
    check(f"{a} to {b} is about {expect:,} km",
          got is not None and abs(got - expect) / expect < 0.06, f"got {got}")
check("capitals are real cities, not centroids",
      R.facts()["JPN"]["capital"] == "Tokyo" and R.facts()["GBR"]["capital"] == "London")
check("most capitals are exact, and the rest are flagged",
      sum(1 for f in R.facts().values() if f["capital_precise"]) >= 190)
check("distance is symmetric",
      R.distance_km("JPN", "BRA") == R.distance_km("BRA", "JPN"))
check("a country to itself is zero", R.distance_km("FRA", "FRA") == 0)
check("an unknown code gives None, not a crash", R.distance_km("ZZZ", "FRA") is None)

print("\ncities — home is a place, not just a country")
check("the city dataset loaded", len(R.cities()) >= 200, str(len(R.cities())))
check("tens of thousands of cities",
      sum(len(v) for v in R.cities().values()) > 30000)
hits = R.search_cities("SAU", "jed")
check("a prefix search finds the city", hits and hits[0]["city"] == "Jeddah", str(hits[:1]))
check("the state comes with it", hits[0]["state"] == "Mecca Region", str(hits[0]))
check("search is scoped to the country", not R.search_cities("JPN", "jeddah"))
check("an empty query lists the biggest first",
      R.search_cities("USA", "")[0]["capital"] is True)
check("results are capped", len(R.search_cities("USA", "", limit=5)) == 5)
check("an unknown country gives nothing, not a crash", R.search_cities("ZZZ", "a") == [])
check("a stored choice resolves back to a point",
      R.city_point("SAU", "Jeddah")["lat"] > 21)
check("matching is case-insensitive", R.city_point("SAU", "jEdDaH") is not None)
check("a city not in that country is refused", R.city_point("JPN", "Jeddah") is None)

# The whole point: distances must start where the person actually lives.
cap = R.footprint("SAU", ["FRA", "JPN"])
jed = R.footprint("SAU", ["FRA", "JPN"],
                  origin=(R.city_point("SAU", "Jeddah")["lat"],
                          R.city_point("SAU", "Jeddah")["lon"]))
check("choosing a city changes the distance", cap["total_km"] != jed["total_km"],
      f"{cap['total_km']} vs {jed['total_km']}")
check("and the change is material (Jeddah is ~850 km from Riyadh)",
      abs(cap["total_km"] - jed["total_km"]) > 500,
      str(abs(cap["total_km"] - jed["total_km"])))
check("no origin falls back to the capital",
      R.footprint("SAU", ["FRA"])["total_km"]
      == R.footprint("SAU", ["FRA"], origin=R.point("SAU"))["total_km"])
check("nearest-unvisited respects the origin too",
      R.nearest_unvisited("SAU", [], ["EGY", "ARE"], origin=(21.49, 39.19))[0]["iso3"]
      == "EGY", "from Jeddah, Egypt is closer than the UAE")
r1 = R.route("SAU", ["FRA", "ESP"])
r2 = R.route("SAU", ["FRA", "ESP"], origin=(21.49, 39.19))
check("routing respects the origin", r1["total_km"] != r2["total_km"])

print("\nweekend getaways")
jed = R.city_point("SAU", "Jeddah")
g = R.getaways(jed["lat"], jed["lon"], "SAU", exclude_city="Jeddah")
check("places are found near a real city", len(g) >= 5, str(len(g)))
check("every one is within range", all(p["km"] <= 600 for p in g))
# The first build offered Parisians Cergy-Pontoise, 29 km away. A suburb is
# not a weekend away.
check("suburbs are excluded", all(p["km"] >= 50 for p in g), str(min(p["km"] for p in g)))
check("the starting city is not in its own list", all(p["city"] != "Jeddah" for p in g))
check("each place says how to get there", all(p["modes"] for p in g))
check("foreign ones are flagged", any(p["abroad"] for p in g))
par = R.getaways(48.8581, 2.353, "FRA", exclude_city="Paris")
check("no more than two per state", max(
    sum(1 for p in par if (p["iso3"], p["state"]) == k) for k in
    {(p["iso3"], p["state"]) for p in par}) <= 2)

print("\ntransport — inferred from geography, and honest about it")
same = [m["mode"] for m in R.transport_modes("FRA", "FRA", 300)]
check("a short domestic hop offers road and rail",
      {"drive", "bus", "train"} <= set(same), str(same))
sea = [m["mode"] for m in R.transport_modes("JPN", "USA", 10000)]
check("an ocean crossing is a flight", sea == ["fly"], str(sea))
check("and says why", R.transport_modes("JPN", "USA", 10000)[0]["why"] == "no land route")
nb = [m["mode"] for m in R.transport_modes("FRA", "DEU", 400)]
check("a land neighbour can be driven", "drive" in nb, str(nb))
# Paris to London came back "fly or ferry" before the fixed-crossing table.
ch = [m["mode"] for m in R.transport_modes("FRA", "GBR", 344)]
check("the Channel Tunnel counts as a land link", "train" in ch and "drive" in ch, str(ch))
far = [m["mode"] for m in R.transport_modes("RUS", "RUS", 6000)]
check("a 6,000 km domestic hop drops the car", "drive" not in far, str(far))
check("something is always offered",
      all(R.transport_modes(a, b, k) for a, b, k in
          [("ZZZ", "YYY", 100), ("FRA", "FRA", 9000), ("GBR", "IRL", 10)]))

print("\njourney time — an estimate from distance, never a timetable")
t = R.journey_time("train", 344)
check("a range is given, not a single number", t["low"] < t["hours"] < t["high"])
check("it reads in hours and minutes", "h" in t["range"] or "min" in t["range"], t["range"])
check("the basis says it is not a timetable", "not a timetable" in t["basis"])
check("flying carries its airport overhead",
      R.journey_time("fly", 100)["hours"] > 2,
      str(R.journey_time("fly", 100)["hours"]))
check("over a short hop the train beats the plane",
      R.journey_time("train", 200)["hours"] < R.journey_time("fly", 200)["hours"])
# Paris-London is 344 km and Eurostar genuinely wins door to door, so the
# crossover has to sit beyond it.
check("the train still wins at Paris-London range",
      R.journey_time("train", 344)["hours"] < R.journey_time("fly", 344)["hours"],
      f"train {R.journey_time('train', 344)['hours']} vs fly {R.journey_time('fly', 344)['hours']}")
check("there is a crossover, and it is past 300 km",
      next(k for k in range(100, 1500, 10)
           if R.journey_time("fly", k)["hours"] < R.journey_time("train", k)["hours"]) > 300)
check("over a long one the plane wins",
      R.journey_time("fly", 3000)["hours"] < R.journey_time("drive", 3000)["hours"])
check("a bus is slower than the same drive",
      R.journey_time("bus", 200)["hours"] > R.journey_time("drive", 200)["hours"])
check("every offered mode carries a time and an explanation",
      all(m.get("range") and m.get("detail")
          for m in R.transport_modes("FRA", "GBR", 344)))

print("\nsuburbs are not getaways")
# Ranking by "nearest and biggest" returned Stamford, Levittown and Bensalem
# from New York — commuter towns, not weekends away.
ny = R.city_point("USA", "New York City")
us = R.getaways(ny["lat"], ny["lon"], "USA", exclude_city="New York City",
                min_pop=75_000, limit=9)
names = {g["city"] for g in us}
check("dormitory towns are filtered out",
      not (names & {"Levittown", "Bensalem", "Lindenhurst", "Copiague", "West Islip"}),
      str(sorted(names)))
check("the plain list is still nine", len(us) == 9)
check("nothing in it is a suburb of the origin", all(g["km"] >= 50 for g in us))

print("\nresolving a place the scout named")
origin = (ny["lat"], ny["lon"])
r = R.resolve_place("Beacon", "New York", origin, 400)
check("a small town is found at all", r is not None and r["name"] == "Beacon", str(r))
check("and it is a real distance away", 60 <= r["km"] <= 120, str(r["km"]))
check("towns below the gazetteer floor still resolve",
      R.resolve_place("Montauk", "New York", origin, 400) is not None)
# "Cold Spring" is a different town from "Cold Spring Harbor", 30 km apart.
cs = R.resolve_place("Cold Spring", "New York", origin, 400)
check("an exact name beats a longer fuzzy match", cs["name"] == "Cold Spring", str(cs))
check("the exact flag is reported", cs.get("exact") is True)
# "Newport" is in Kentucky, Rhode Island and Wales; range settles it.
np = R.resolve_place("Newport", "Rhode Island", origin, 400)
check("the reachable Newport is chosen", np["state"] == "Rhode Island", str(np))
check("somewhere out of range returns nothing",
      R.resolve_place("Reykjavik", "Capital Region", origin, 400) is None)
# There is a Lisbon, Maryland with 282 residents; it must not stand in for the
# place the scout meant.
check("a hamlet does not stand in for a named destination",
      R.resolve_place("Lisbon", "Lisboa", origin, 400) is None)
check("but real small destinations still resolve",
      all(R.resolve_place(n, "", origin, 400) for n in ("Montauk", "Lenox", "Cooperstown")))
check("an invented place returns nothing",
      R.resolve_place("Qzzxlandia", None, origin, 400) is None)

print("\nmulti-stop routing over real cities")
ny = R.city_point("USA", "New York City")
start = (ny["lat"], ny["lon"])
def stop(iso, city):
    c = R.city_point(iso, city)
    return {"label": city, "lat": c["lat"], "lon": c["lon"], "iso3": iso}
trip = [stop("FRA", "Paris"), stop("ITA", "Rome"),
        stop("ESP", "Barcelona"), stop("GBR", "London")]
rp = R.route_points(start, trip)
check("every stop is routed", len(rp["order"]) == 4)
check("the legs form a closed loop",
      rp["legs"][0]["from"] == "home" and rp["legs"][-1]["to"] == "home")
check("leg count is stops + 1", len(rp["legs"]) == 5)
check("the solved order is no longer than the listed one",
      rp["total_km"] <= rp["as_listed_km"])
check("small trips are solved exactly", rp["exact"] is True)
check("the saving is reported", rp["saved_km"] == rp["as_listed_km"] - rp["total_km"])
# cities, not capitals: Kyoto must not be routed as Tokyo
kyo, tok = R.city_point("JPN", "Kyoto"), R.city_point("JPN", "Tokyo")
check("a city stop uses the city, not its capital",
      R.haversine((kyo["lat"], kyo["lon"]), (tok["lat"], tok["lon"])) > 300)
one = R.route_points(start, [stop("FRA", "Paris")])
check("a single stop still routes", one and len(one["legs"]) == 2)
check("no stops gives nothing", R.route_points(start, []) is None)
big = R.route_points(start, [stop("FRA", "Paris"), stop("ITA", "Rome"),
                             stop("ESP", "Barcelona"), stop("GBR", "London"),
                             stop("DEU", "Berlin"), stop("NLD", "Amsterdam"),
                             stop("PRT", "Lisbon"), stop("AUT", "Vienna")])
check("large trips fall back to the heuristic", big["exact"] is False)
check("and still visit everything", len(big["order"]) == 8)

print("\nvisa framing — what you must do before you board")
# An e-visa is paperwork you need in advance; filing it under "no visa
# needed" is how somebody gets turned away at check-in.
us_cn = R.visa_status("USA", "CHN")
check("an e-visa counts as advance paperwork", us_cn["advance"] is True, str(us_cn))
check("and says when it is needed", us_cn["action"] == "before you travel")
check("visa free needs nothing", R.visa_status("USA", "FRA")["advance"] is False)
check("visa on arrival needs nothing in advance",
      R.visa_status("USA", "TZA")["advance"] is False,
      str(R.visa_status("USA", "TZA")))
# Kenya switched to an eTA, which is advance paperwork even though it is not a
# visa — exactly the distinction this field exists to make.
check("a travel authorisation counts as advance",
      R.visa_status("USA", "KEN")["advance"] is True)
check("a full visa is advance too", R.visa_status("USA", "RUS")["advance"] is True)
check("your own country needs nothing", R.visa_status("USA", "USA")["advance"] is False)

print("\ncollections — national parks")
parks = R.parks()
us = [p for p in parks if p["iso3"] == "USA"]
ca = [p for p in parks if p["iso3"] == "CAN"]
# 63 on the official NPS list plus Chiricahua, redesignated in 2025.
check("all 64 US national parks are there", len(us) == 64, str(len(us)))
# 37 national parks, 11 national park reserves, and Rouge, the urban park.
check("all 49 Canadian parks are there", len(ca) == 49, str(len(ca)))
check("Virgin Islands survived its bogus Wikidata end date",
      any(p["name"] == "Virgin Islands National Park" for p in us))
check("delisted and proposed parks are excluded",
      not any(p["name"].startswith(("Menissawok", "Nemiskam", "Bowen Island",
                                    "South Okanagan", "Mackinac"))
              for p in parks))
check("the territories are not filed under a mainland state",
      next(p["state"] for p in parks
           if p["name"] == "National Park of American Samoa") == "American Samoa")
check("every park has coordinates", all("lat" in p and "lon" in p for p in parks))
check("every park has a state or province", all(p["state"] for p in parks))
check("nearly all have a photograph",
      sum(1 for p in parks if p["photo"]) >= len(parks) - 10)
check("photos point at the public image host",
      all("thumb.wikimedia.org" not in (p["photo"] or "") for p in parks))

# Nearest-city put Arches in Colorado and Auyuittuq in Quebec.
for name, want in [("Arches National Park", "Utah"),
                   ("Auyuittuq National Park", "Nunavut"),
                   ("Denali National Park", "Alaska"),
                   ("Banff National Park", "Alberta")]:
    # Denali is stored under its full name, "...National Park and Preserve".
    hit = next((p for p in parks if p["name"].startswith(name)), None)
    check(f"{name.split(' National')[0]} is in {want}",
          hit and hit["state"] == want, str(hit and hit["state"]))

# Wikidata stores most of these in hectares; the bare number made Yellowstone
# a hundred times too big.
for name, km2 in [("Yellowstone National Park", 8983), ("Zion National Park", 595),
                  ("Banff National Park", 6641), ("Grand Canyon National Park", 4926)]:
    hit = next((p for p in parks if p["name"] == name), None)
    check(f"{name.split(' National')[0]} is about {km2:,} km²",
          hit and hit.get("area_km2") and abs(hit["area_km2"] - km2) / km2 < 0.1,
          str(hit and hit.get("area_km2")))
check("no park is implausibly large",
      all(p.get("area_km2", 0) < 120_000 for p in parks),
      str(max((p.get("area_km2", 0) for p in parks))))

print("\nbooking handoff — links, never prices")
fs = R.flight_search("LHR", "LIS")
check("a flight search is offered on more than one site", len(fs) >= 3)
check("flight links carry both airport codes",
      all("lhr" in u.lower() and "lis" in u.lower() for u in fs.values()))
check("every flight link is https", all(u.startswith("https://") for u in fs.values()))
ss = R.stay_search("Lisbon", "Portugal")
check("a stay search is offered on more than one site", len(ss) >= 3)
check("stay links name the city", all("Lisbon" in u for u in ss.values()))
check("every stay link is https", all(u.startswith("https://") for u in ss.values()))
check("the city is encoded, not pasted raw",
      " " not in "".join(R.stay_search("New York City", "United States").values()))
# The whole point of the handoff is that we never state a fare or a rate.
blob = " ".join(list(fs.values()) + list(ss.values())).lower()
check("no link smuggles a price into the URL",
      not any(w in blob for w in ("price=", "usd", "eur", "currency=", "rate=")))

print("\ncity pickers cover the whole country")
us = R.search_cities("USA", "", 4000)
check("every US city is reachable, not the first 25", len(us) > 3000, str(len(us)))
check("a mid-sized town is in there",
      any(c["city"] == "New Haven" for c in us))
check("so is a small one", any(c["city"] == "Bozeman" for c in us))
pt = R.search_cities("PRT", "", 4000)
check("smaller countries are complete too", len(pt) > 150, str(len(pt)))
check("and resolve to a point",
      R.city_point("PRT", "Évora") is not None)
check("a prefix search still narrows",
      len(R.search_cities("USA", "New Hav", 4000)) < len(us))

print("\nairports you could actually depart from")
nh = R.city_point("USA", "New Haven")
near = R.airports_near(nh["lat"], nh["lon"])
codes = [a["iata"] for a in near]
check("the closest airport is offered", "BDL" in codes, str(codes))
# The point of the list: the nearest airport is not the one with the non-stop.
check("so are the New York hubs", "JFK" in codes and "EWR" in codes, str(codes))
check("and Boston, which is worth the drive", "BOS" in codes, str(codes))
check("they come back nearest first",
      [a["km"] for a in near] == sorted(a["km"] for a in near))
check("nothing absurdly far is included", max(a["km"] for a in near) <= 250)
check("every one of them is a large airport", all(a["large"] for a in near))

print("\nworld heritage")
wh = R.heritage()
check("the whole list is there", len(wh) > 1200, str(len(wh)))
check("every site has a UNESCO reference", all(s.get("whs_stem") for s in wh))
check("and a link to its own listing",
      all(s["unesco_url"].startswith("https://whc.unesco.org/en/list/") for s in wh))
it = R.heritage("ITA")
check("Italy is roughly its official count", 55 <= len(it) <= 85, str(len(it)))
check("one country is a subset of all", len(it) < len(wh))
check("most sites carry a photograph",
      sum(1 for s in wh if s.get("image")) > len(wh) * 0.8)
# Components of a serial listing share the parent's reference stem; keeping
# them would have shown single rock-art panels as if they were sites.
pt = R.heritage("PRT")
check("components are folded into their listing",
      not any("-" in s["whs_stem"] for s in pt))
check("Portugal is near its official 17", 15 <= len(pt) <= 24, str(len(pt)))
check("countries are listed with counts",
      all(c["n"] > 0 and c["name"] for c in R.heritage_countries()))
# The parks pipeline double-encoded these and every photo 404'd.
photos = [s["photo"] for s in pt if s.get("photo")]
check("photo URLs are not double-encoded",
      not any("%25" in u for u in photos), str(photos[:1]))

print("\nguided days")
t = R.tour_search("Lisbon", "Portugal")
check("more than one marketplace is offered", len(t) >= 3)
check("they all name the city", all("Lisbon" in u for u in t.values()))
check("all https", all(u.startswith("https://") for u in t.values()))
check("no price or commission parameter rides along",
      not any(w in " ".join(t.values()).lower()
              for w in ("price", "aff", "partner_id", "currency")))

print("\npublished guides")
g = R.guide_links("Lisbon", "Portugal", "PRT")
check("Lonely Planet is offered", "Lonely Planet" in g)
check("Michelin is offered where it publishes", "Michelin Guide" in g)
g2 = R.guide_links("Windhoek", "Namibia", "NAM")
check("Lonely Planet covers everywhere", "Lonely Planet" in g2)
check("Michelin is withheld where it has no selection",
      "Michelin Guide" not in g2)
check("guide links are https", all(u.startswith("https://") for u in g.values()))
check("the city reaches the query", all("Lisbon" in u for u in g.values()))
check("spaces are encoded",
      " " not in "".join(R.guide_links("New York City", "United States", "USA").values()))

print("\ntravellers' first picks")
for iso, n in (("USA", 5), ("CAN", 5)):
    picks = R.first_picks(iso)
    # A pick that does not match a park is silently dropped, so a short list
    # means a name in FIRST_PICKS has gone stale.
    check(f"{iso} has all {n} picks", len(picks) == n, str(len(picks)))
    check(f"{iso} picks all carry a reason", all(p["why"].strip() for p in picks))
    check(f"{iso} picks all have a photo", all(p["photo"] for p in picks))
    check(f"{iso} picks are all real parks in the dataset",
          all(any(q["id"] == p["id"] for q in parks) for p in picks))
    check(f"{iso} picks are not duplicated",
          len({p["id"] for p in picks}) == len(picks))
# Glacier National Park exists in both countries and they are different places.
us_glacier = next(p for p in R.first_picks("USA") if "Glacier" in p["name"])
check("the US pick is Montana's Glacier, not Canada's",
      us_glacier["state"] == "Montana", us_glacier["state"])
check("Banff leads the Canadian picks",
      R.first_picks("CAN")[0]["name"].startswith("Banff"))

print("\nmost-visited parks")
withv = [p for p in parks if p.get("visitors")]
check("most US parks publish a figure",
      sum(1 for p in withv if p["iso3"] == "USA") >= 50,
      str(sum(1 for p in withv if p["iso3"] == "USA")))
top = sorted([p for p in parks if p["iso3"] == "USA" and p.get("visitors")],
             key=lambda p: -p["visitors"])
check("Great Smoky Mountains is the busiest US park",
      top[0]["name"].startswith("Great Smoky"), top[0]["name"])
check("and by a wide margin", top[0]["visitors"] > top[1]["visitors"] * 2)
check("the Grand Canyon is second", top[1]["name"].startswith("Grand Canyon"))
check("every figure carries the year it is from",
      all(p.get("visitors_year") for p in withv))
# A pandemic year is not what a park normally receives, and a figure from the
# future is not a figure at all.
import time as _t
check("no pandemic-year figures", all(p["visitors_year"] not in (2020, 2021) for p in withv))
check("no figures from the future",
      all(p["visitors_year"] <= _t.localtime().tm_year for p in withv))
check("the busiest figures are plausible",
      all(p["visitors"] < 30_000_000 for p in withv))

print("\ngetting to a park from where you live")
ny = R.city_point("USA", "New York City")
origin = (ny["lat"], ny["lon"])
yell = next(p for p in parks if p["name"] == "Yellowstone National Park")
j = R.journey_to_park(origin, "USA", yell)
check("a far park is flown to", not j["drivable"] and j["legs"][0]["mode"] == "fly")
check("it routes through a real airport", j["airport"]["iata"] == "WYS", str(j["airport"]))
check("it suggests somewhere to sleep", j["base_town"]["city"] == "Bozeman")
check("the last leg ends at the gate", "gate" in j["legs"][-1]["to"])
check("every leg carries a time estimate", all(l.get("range") for l in j["legs"]))
acadia = next(p for p in parks if p["name"] == "Acadia National Park")
ja = R.journey_to_park(origin, "USA", acadia)
check("a close park is driven to", ja["drivable"] and ja["legs"][0]["mode"] == "drive")
check("the drive ends at the town, not the gate",
      "gate" not in ja["legs"][0]["to"], str(ja["legs"][0]["to"]))
check("there is no phantom flight", not any(l["mode"] == "fly" for l in ja["legs"]))
check("the caveat is carried", "not timetables" in j["caveat"] or "timetables" in j["caveat"])

print("\nglobal city search")
check("a city is findable without knowing its country",
      R.find_city("kyoto")[0]["iso3"] == "JPN")
check("the country code comes back", "iso3" in R.find_city("lisbon")[0])
check("one letter is too vague to search", R.find_city("k") == [])
check("results are capped", len(R.find_city("san", limit=5)) == 5)

print("\ncarbon — assumptions are returned, not hidden")
kg, band = R.carbon_kg(10000)
check("a 10,000 km flight is 1.4-1.6 t", 1400 <= kg <= 1600, f"{kg} kg")
check("it is labelled long haul", band == "long haul")
check("a short hop uses the higher factor", R.carbon_kg(500)[0] / 500 > R.carbon_kg(10000)[0] / 10000)
fp = R.footprint("GBR", ["FRA", "USA", "JPN"])
check("home is excluded from your own footprint",
      R.footprint("GBR", ["GBR", "FRA"])["countries"] == 1)
check("the carbon source is stated", "DEFRA" in fp["carbon_source"])
check("so is the trip assumption", "journey" in fp["assumption"], fp["assumption"][:60])

print("\ncarbon offsets — published equivalences, not a plan")
o = R.offsets(5.92)
# EPA: 0.060 t per urban tree per YEAR, averaged over a ten-year growth
# period. Reading that as a ten-year total would be out by a factor of ten.
check("trees are counted over ten years", o["tree_years"] == 10)
check("5.92 t is about ten trees", o["trees"] == 10, str(o["trees"]))
check("the arithmetic matches EPA's own factor",
      abs(o["trees"] - 5.92 / (R.EPA["tree_year"] * 10)) < 1)
check("forest acres use the published annual rate",
      abs(o["forest_acres"] - 5.92) < 0.2, str(o["forest_acres"]))
check("cars use the published per-vehicle year",
      abs(o["cars_off_road"] - 5.92 / 4.29) < 0.02)
check("the source is named", "EPA" in o["source"])
check("it says plainly that this is not neutralisation",
      "not a neutralisation plan" in o["caveat"])
check("it no longer calls the carbon figure a floor",
      "floor" not in o["caveat"], o["caveat"][-70:])
check("and that a flight not taken beats one offset",
      "not taken beats" in o["caveat"])
check("the ten-year multiplication is attributed to us, not EPA",
      "multiplied by ten" in o["tree_note"])
check("zero carbon offers nothing to offset", R.offsets(0) == {"tonnes": 0})
check("a tiny footprint still rounds to at least one tree",
      R.offsets(0.01)["trees"] == 1)
check("offsets scale linearly",
      R.offsets(12)["trees"] == 2 * R.offsets(6)["trees"])
fp = R.footprint("GBR", ["USA", "JPN"])
check("the footprint carries its offsets", fp["offsets"]["trees"] > 0)

print("\nfootprint — journeys, not one flight per country")
ny = R.city_point("USA", "New York City")
o = (ny["lat"], ny["lon"])
euro = ["FRA", "DEU", "BEL", "NLD", "LUX", "CHE", "AUT", "ITA", "ESP", "PRT"]
e = R.footprint("USA", euro, origin=o)
# Counting a return flight per country put these ten at 18.1 t. One trip is
# 2.8 t — the trip model, not the per-km factor, was the real error.
check("neighbouring countries become one journey", e["trips"] == 1, str(e["trips"]))
check("and the total falls accordingly", e["tonnes_co2e"] < 5, str(e["tonnes_co2e"]))
check("every country is still counted", e["countries"] == 10)

wide = R.footprint("USA", euro + ["JPN", "AUS", "BRA"], origin=o)
check("distant continents stay separate journeys", wide["trips"] == 4, str(wide["trips"]))
check("the furthest is still reported", wide["furthest"]["iso3"] in ("AUS", "JPN"))

# Years are the stronger signal: two visits years apart are two trips even
# when the countries are neighbours.
apart = R.footprint("USA", ["FRA", "DEU"], origin=o, years={"FRA": 2015, "DEU": 2019})
together = R.footprint("USA", ["FRA", "DEU"], origin=o, years={"FRA": 2019, "DEU": 2019})
check("different years are not merged into one trip", apart["trips"] == 2)
check("the same year stays one trip", together["trips"] == 1)
check("so separate visits cost more", apart["tonnes_co2e"] > together["tonnes_co2e"])

check("the assumption is stated, not buried", "journey" in e["assumption"])
check("an empty map has no footprint", R.footprint("USA", [], origin=o)["tonnes_co2e"] == 0)

# The per-kilometre factor itself stands up: a New York to London return is
# 1.65 t here, inside the published range for economy.
lon = R.city_point("GBR", "London")
km = R.haversine(o, (lon["lat"], lon["lon"]))
check("a New York to London return is in the published range",
      0.6 <= R.carbon_kg(km)[0] * 2 / 1000 <= 2.0,
      f"{R.carbon_kg(km)[0] * 2 / 1000:.2f} t")

print("\nvisas")
check("a passport in its own country is 'self'",
      R.visa_status("FRA", "FRA")["code"] == "self")
check("Schengen neighbours are visa free for a French passport",
      R.visa_status("FRA", "DEU")["easy"] is True)
check("day counts are parsed out", isinstance(R.visa_status("SAU", "ALB")["days"], int))
check("an unknown passport gives None", R.visa_status("ZZZ", "FRA") is None)
s = R.visa_summary("JPN", ["FRA"])
check("a strong passport opens 100+ countries easily", s["easy_total"] > 100, str(s["easy_total"]))
check("visited countries are subtracted from the unvisited list",
      "FRA" not in s["easy_unvisited"])
check("an unknown passport is reported, not guessed",
      R.visa_summary("ZZZ", [])["known"] is False)

print("\nprices")
p = R.price_vs("USA", "EGY")
check("Egypt is cheaper than the United States", p["ratio"] < 1, str(p["ratio"]))
check("and the label says so", "cheaper" in p["label"])
check("a country against itself is about the same",
      "same" in R.price_vs("FRA", "FRA")["label"])
check("the source is named", "World Bank" in p["source"])

print("\nreach")
r = R.reach(["FRA", "JPN", "EGY", "BRA"])
check("languages are counted", r["n_languages"] >= 4, str(r["n_languages"]))
check("currencies are counted", r["n_currencies"] >= 4, str(r["n_currencies"]))
check("an empty list gives zeroes", R.reach([])["n_languages"] == 0)

print("\nblind spots")
pool = [k for k in R.facts()]
b = R.blind_spots(["FRA", "DEU", "ITA", "ESP"], pool)
check("the emptiest sub-region comes first", b[0]["pct"] == 0)
west = next(x for x in b if x["subregion"] == "Western Europe")
check("a region you have been to is not 0%", west["pct"] > 0, str(west))

print("\nrouting")
r = R.route("GBR", ["FRA", "ESP", "ITA", "GRC"])
check("every stop is in the route", set(r["order"]) == {"FRA", "ESP", "ITA", "GRC"})
check("small routes are solved exactly", r["exact"] is True)
check("the optimised route is never longer than the listed one",
      r["total_km"] <= r["as_listed_km"])
check("the legs form a closed loop",
      r["legs"][0]["from"] == "GBR" and r["legs"][-1]["to"] == "GBR")
check("leg count is stops + 1", len(r["legs"]) == len(r["order"]) + 1)
big = R.route("GBR", ["FRA", "ESP", "ITA", "GRC", "TUR", "EGY", "MAR", "PRT", "DEU", "POL"])
check("large routes fall back to heuristics", big["exact"] is False)
check("and still visit every stop", len(big["order"]) == 10)
check("duplicates are collapsed",
      len(R.route("GBR", ["FRA", "FRA", "ESP"])["order"]) == 2)
check("home inside the stop list is dropped",
      "GBR" not in R.route("GBR", ["GBR", "FRA"])["order"])
check("no stops gives None", R.route("GBR", []) is None)

print("\nclimate (weather, never crowds)")
c = R.best_months("ISL")
if c:
    check("Iceland's best months are in summer",
          any(m["month"] in (6, 7, 8, 9) for m in c["best"]),
          str([m["name"] for m in c["best"]]))
    check("twelve months are returned", len(c["all"]) == 12)
    check("the caveat says it is not about crowds", "quietest" in c["caveat"])
else:
    check("climate data still downloading — skipped", True)

print("\n" + "=" * 62)
print(f"  {PASS} passed, {FAIL} failed")
print("=" * 62)
sys.exit(1 if FAIL else 0)
