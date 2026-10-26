"""Checks on the data layer. Run: python backend/test_tnat_data.py"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import tnat_data as t

ok, fail = 0, []


def check(label, cond, detail=""):
    global ok
    if cond:
        ok += 1
    else:
        fail.append(f"{label}  {detail}")
    print(f"  [{'ok  ' if cond else 'FAIL'}] {label}" + (f"   {detail}" if detail and not cond else ""))


print("\nloading")
cs = t.all_countries()
check("206 countries", len(cs) == 206, f"got {len(cs)}")
check("denominator is sane", 1.2e9 < t.world_total() < 1.6e9, f"{t.world_total():,.0f}")
check("shares sum to 100%", abs(sum(t.share_pct(c) for c in cs) - 100) < 0.01)
check("every country has a reference year", all(c.ref_year in c.series for c in cs))
check("no pandemic reference year unless unavoidable",
      all(c.ref_year not in (2020, 2021) or not [y for y in c.series if y < 2020 or y >= 2022]
          for c in cs))

print("\nname resolution")
for q, want in [("USA", "United States"), ("uk", "United Kingdom"), ("FRA", "France"),
                ("uae", "United Arab Emirates"), ("korea", "South Korea"),
                ("czech republic", "Czechia"), ("Japan", "Japan")]:
    c = t.resolve(q)
    check(f"resolve {q!r}", c is not None and c.name == want, f"got {c.name if c else None}")
check("nonsense returns None", t.resolve("Narnia") is None)
# Loose substring matching used to return the wrong country's statistics:
# "mali" sits inside "somalia", "guinea" inside "equatorial guinea".
for q in ["Somalia", "Equatorial Guinea", "South Sudan", "Western Sahara"]:
    got = t.resolve(q)
    check(f"{q!r} does not silently match another country",
          got is None or got.name == q, f"got {got.name if got else None}")
for q, want in [("Mali", "Mali"), ("Guinea", "Guinea"), ("Sudan", "Sudan"),
                ("Niger", "Niger"), ("Dominica", "Dominica")]:
    got = t.resolve(q)
    check(f"{q!r} still resolves to itself", got is not None and got.name == want,
          f"got {got.name if got else None}")
check("empty returns None", t.resolve("") is None)

print("\nsanity of known values")
jp = t.resolve("Japan")
check("Japan not scored off a pandemic year", jp.ref_year not in (2020, 2021), f"ref {jp.ref_year}")
check("Japan share is realistic", 1.5 < t.share_pct(jp) < 4, f"{t.share_pct(jp):.2f}%")
fr = t.resolve("France")
check("France is the biggest", max(cs, key=lambda c: c.ref_arrivals).name == "France")
check("France ~6-8% of world flow", 6 < t.share_pct(fr) < 8, f"{t.share_pct(fr):.2f}%")

print("\nprofile scoring")
BIG = ["France", "Spain", "Italy", "USA", "UK", "Germany", "Greece", "Mexico",
       "Turkey", "Austria", "Netherlands", "Portugal"]
RARE = ["Bhutan", "Mongolia", "Namibia", "Bolivia", "Laos", "Ethiopia",
        "Kyrgyzstan", "Madagascar", "Suriname", "Nepal"]
pb, pr = t.profile_score(BIG), t.profile_score(RARE)
check("big-hitters read as tourist", pb["verdict"] == "tourist", pb["verdict"])
check("off-path reads as traveler", pr["verdict"] == "traveler", pr["verdict"])
check("tourist flow > traveler flow", pb["flow_coverage_pct"] > pr["flow_coverage_pct"] * 10)
check("traveler rarity > tourist rarity", pr["rarity_score"] > pb["rarity_score"])
check("unmatched names are reported", t.profile_score(["France", "Narnia"])["unmatched"] == ["Narnia"])
check("empty profile does not crash", t.profile_score([])["n_countries"] == 0)
check("duplicates counted once", t.profile_score(["France", "FRA", "france"])["n_countries"] == 1)

print("\nwhat is left")
w = t.whats_left(BIG)
check("visited + remaining = 206", w["visited"] + w["remaining"] == 206)
check("coverage + remaining ~ 100%",
      abs(pb["flow_coverage_pct"] + w["remaining_share_pct"] - 100) < 0.1,
      f"{pb['flow_coverage_pct']} + {w['remaining_share_pct']}")

print("\ntrajectory")
g = t.trajectory("Georgia", visited_year=2012)
check("Georgia grew a lot", g["change_pct"] > 100, f"{g['change_pct']}%")
check("early flag set for Georgia 2012", g["you_went"]["were_you_early"] is True)
check("missing country handled", t.trajectory("Narnia")["found"] is False)
check("gaps are reported", isinstance(t.trajectory("Romania")["gaps"], list)
      and len(t.trajectory("Romania")["gaps"]) > 0)

print("\nrecommender")
r = t.recommend(BIG, want=["Mongolia"], limit=8)
names = [d["country"] for d in r["recommendations"]]
check("returns the requested number", len(names) == 8, str(len(names)))
check("never recommends a visited country", not ({"France", "Spain"} & set(names)))
check("want-list item surfaces first", names[0] == "Mongolia", names[0])
check("micro-states filtered out", not ({"Tuvalu", "Kiribati", "Marshall Islands"} & set(names)))
check("more than one region represented",
      len({d["region"] for d in r["recommendations"]}) >= 3)
check("region filter works",
      all(d["region"] == "Africa" for d in t.recommend(BIG, region="Africa")["recommendations"]))

print("\npeer bands")
check("0 countries -> never-left band", t.peer_band(0)["band_share_pct"] == 21)
check("3 countries -> 1-4 band", t.peer_band(3)["band_share_pct"] == 34)
check("34 hits the ceiling", t.peer_band(34)["ceiling_reached"] is True)
check("34 carries the caveat", t.peer_band(34)["caveat"] is not None)
check("94 adds the reference note, flagged as not a statistic",
      "not a computed statistic" in t.peer_band(94).get("rarity_note", ""))
# The caveat text mentions "percentile" in order to deny one, so the check is
# that no KEY returns a percentile number — the prose is allowed to say there
# isn't one.
check("no percentile value is ever returned",
      all(not any("percentile" in k.lower() for k in t.peer_band(n))
          for n in (0, 3, 34, 94)))
check("the caveat denies a percentile outright",
      "No exact percentile exists" in t.peer_band(94)["caveat"])

print("\nworld coverage — exact, no estimate anywhere")
check("0 countries is 0%", t.world_coverage(0)["world_pct"] == 0.0)
check("195 countries is 100%", t.world_coverage(195)["world_pct"] == 100.0)
check("17 countries is 8.7% of the world",
      t.world_coverage(17)["display"] == "8.7%", t.world_coverage(17)["display"])
wc = [t.world_coverage(n)["world_pct"] for n in range(0, 196)]
check("rises with every country added",
      all(b > a for a, b in zip(wc, wc[1:])))
check("remaining counts down to zero", t.world_coverage(195)["remaining"] == 0)
check("no key anywhere claims a percentile of travellers",
      not any("percentile" in k or "rarity" in k
              for n in (0, 10, 94) for k in t.world_coverage(n)))
check("rarity_among_people is gone for good",
      not hasattr(t, "rarity_among_people"))

print("\npeer context — the survey states its own ceiling")
check("0 countries quotes the never-left share",
      "21%" in t.peer_context(0)["sentence"])
check("10 or more hits the survey's top bucket",
      "ten or more" in t.peer_context(10)["sentence"])
check("94 gets the same bucket, and says so",
      "cannot place 94 any more precisely" in t.peer_context(94)["sentence"])
check("the caveat names the 24-country sample",
      "24 mostly wealthier countries" in t.peer_context(34)["caveat"])
check("the source is always attached",
      all("Pew" in t.peer_context(n)["source"] for n in (0, 5, 94)))

print("\noff the path — an exact rarity measure, from arrivals")
op = t.off_path(["France", "Spain", "United States"])
check("a tourist route hits none of the tail-50", op["in_tail"] == 0)
# Chad sits 18th from the bottom on 2019 arrivals; Bhutan, at 316k, does not
# make the cut — the list is short on purpose.
op = t.off_path(["Chad", "France"])
check("Chad counts as off the path", op["in_tail"] == 1, str(op["countries"]))
check("Bhutan at 316k is not in the tail", t.off_path(["Bhutan"])["in_tail"] == 0)
check("it counts only what resolved", t.off_path(["France", "Narnia"])["of_visited"] == 1)
check("the cutoff is reported so the claim is checkable",
      t.off_path(["France"])["cutoff"] == 50)

print("\nUK nations — four pins, one member state")
check("the UK itself is no longer pinnable",
      "United Kingdom" not in {r["name"] for r in t.labellable()})
check("all four nations are pinnable",
      {"England", "Scotland", "Wales", "Northern Ireland"} <=
      {r["name"] for r in t.labellable()})
check("each nation carries a flag code",
      all(r["iso2"] for r in t.labellable() if r["name"] in t.PARTS))
check("each is marked as part of the UK",
      all(r.get("part_of") == "United Kingdom"
          for r in t.labellable() if r["name"] in t.PARTS))
check("a nation resolves to the UK's arrivals record",
      t.resolve("Scotland").name == "United Kingdom")
# the figure is the UK's, and must be labelled as such or Scotland looks like
# it receives 39 million visitors of its own
check("the shared figure is flagged",
      all(r.get("figures_are") == "United Kingdom"
          for r in t.labellable() if r["name"] in t.PARTS))
check("four nations collapse to one country for flow",
      t.profile_score(["England", "Scotland", "Wales", "Northern Ireland"])["n_countries"] == 1)
check("and to exactly the UK's flow share",
      t.profile_score(["England", "Scotland"])["flow_coverage_pct"]
      == t.profile_score(["United Kingdom"])["flow_coverage_pct"])
check("two nations are one sovereign state",
      t.count_sovereign(["England", "Scotland"]) == 1)
check("a country with no arrivals data still counts as one",
      t.count_sovereign(["Iraq"]) == 1)
check("mixed pins count correctly",
      t.count_sovereign(["England", "Wales", "Iraq", "Japan"]) == 3)

print("\ncountries, territories and places — the totals must reconcile")
check("ISO 3166 minus the territory table is exactly 195",
      len(t.registry()) - len(t.TERRITORIES) == 195,
      f"{len(t.registry())} - {len(t.TERRITORIES)} = {len(t.registry()) - len(t.TERRITORIES)}")
check("un_members() agrees", len(t.un_members()) == t.UN_COUNTRIES)
check("every territory code is a real ISO entry",
      all(k in t.registry() for k in t.TERRITORIES))
check("no code is both a country and a territory",
      not (set(t.TERRITORIES) & t.un_members()))
_b = t.benchmarks()
check("destinations split exactly into countries and territories",
      _b["countries_with_data"] + _b["territories_with_data"] == _b["destinations_with_data"],
      f"{_b['countries_with_data']} + {_b['territories_with_data']} "
      f"!= {_b['destinations_with_data']}")
check("countries with and without data account for all 195",
      _b["countries_with_data"] + _b["countries_without_data"] == _b["un_countries"])
check("every destination classifies as one or the other",
      not [c.name for c in t.all_countries() if t.classify(c.name)[0] == "unknown"],
      str([c.name for c in t.all_countries() if t.classify(c.name)[0] == "unknown"][:5]))

# This was a live bug: four territories claimed "2.1% of the world's 195".
check("territories do not count toward the 195",
      t.coverage_counts(["Hong Kong", "Macao", "Puerto Rico", "Guam"])["countries"] == 0)
check("but they are still counted, not discarded",
      t.coverage_counts(["Hong Kong", "Macao", "Puerto Rico", "Guam"])["territories"] == 4)
check("a territory still contributes to travel flow",
      t.profile_score(["Hong Kong"])["flow_coverage_pct"] > 0)
check("the UK is a country even though it is not pinnable by that name",
      t.classify("United Kingdom") == ("country", "United Kingdom"))
check("UK nations count as one country, no territories",
      t.coverage_counts(["England", "Scotland", "Wales"]) ["countries"] == 1
      and t.coverage_counts(["England", "Scotland"])["territories"] == 0)
check("disputed places count as territories, not countries",
      t.coverage_counts(["Kosovo", "Somaliland"])["countries"] == 0)
check("a UN member with no arrivals data is still a country",
      t.coverage_counts(["Iraq"])["countries"] == 1)
check("an unrecognised name is reported, not silently counted",
      t.coverage_counts(["Narnia"])["unknown"] == ["Narnia"])
check("no pinnable place can ever push the count past 195",
      t.coverage_counts([r["name"] for r in t.labellable()])["countries"] <= 195,
      str(t.coverage_counts([r["name"] for r in t.labellable()])["countries"]))

print("\nbenchmarks — what makes a flow figure readable")
b = t.benchmarks()
check("the world total matches the data layer", b["world_trips"] == int(t.world_total()))
check("destination count is reported under its own name",
      b["destinations_with_data"] == len(t.all_countries()))
check("the most-visited country is France", b["most_visited"] == "France")
check("cumulative shares only ever rise",
      b["top_1_pct"] < b["top_5_pct"] < b["top_10_pct"] < b["top_20_pct"])
check("the top 10 land near 43%", 40 <= b["top_10_pct"] <= 45, str(b["top_10_pct"]))
# the headline fact on the page — if this drifts, the sentence is wrong
check("a small group of countries takes half the world's travel",
      5 <= b["countries_for_half"] <= 25, str(b["countries_for_half"]))
check("that threshold really does cross 50%",
      sum(t.share_pct(c) for c in
          sorted(t.all_countries(), key=lambda c: -c.ref_arrivals)[:b["countries_for_half"]]) >= 50)
check("and one country fewer does not",
      sum(t.share_pct(c) for c in
          sorted(t.all_countries(), key=lambda c: -c.ref_arrivals)[:b["countries_for_half"] - 1]) < 50)
check("the tourist threshold is carried with it",
      b["tourist_threshold"] == t.TOURIST_THRESHOLD)
check("both bar markers fit on the track",
      0 < b["tourist_threshold"] < 100 and 0 < b["top_10_pct"] < 100)

print("\nrarity quartiles — the copy describes these, so they must be real")
q = t.benchmarks()["rarity_quartiles"]
check("quartiles rise in order", q["p25"] < q["p50"] < q["p75"] < q["p95"],
      str(q))
check("the median really is the median",
      abs(sum(1 for c in t.all_countries() if t.one_in(c) < q["p50"])
          - len(t.all_countries()) / 2) <= 2)
check("p95 really does cut the top ~5%",
      4 <= sum(1 for c in t.all_countries() if t.one_in(c) >= q["p95"])
           / len(t.all_countries()) * 100 <= 6)
# the bug these replaced: Namibia was being called "well-trodden" by a
# hard-coded threshold when it sits almost exactly on the median
check("Namibia is not in the bottom quartile",
      t.one_in(t.resolve("Namibia")) > q["p25"])
check("France is", t.one_in(t.resolve("France")) < q["p25"])
check("Tuvalu is above the 95th", t.one_in(t.resolve("Tuvalu")) >= q["p95"])

print("\ngroup bands")
check("under 5 is small", all(t.group_band(n)["band"] == "small" for n in (1, 2, 4)))
check("5 to 20 is medium", all(t.group_band(n)["band"] == "medium" for n in (5, 12, 20)))
check("21 to 40 is large", all(t.group_band(n)["band"] == "large" for n in (21, 30, 40)))
check("the 20/21 boundary is unambiguous",
      t.group_band(20)["band"] != t.group_band(21)["band"])
check("every band is contiguous with the next",
      all(t.GROUP_BANDS[i][2] + 1 == t.GROUP_BANDS[i + 1][1]
          for i in range(len(t.GROUP_BANDS) - 1)))
check("oversized parties clamp rather than crash", t.group_band(500)["size"] == t.GROUP_MAX)
check("zero and negatives clamp to one", t.group_band(0)["size"] == 1)
check("every size from 1 to the max has a band",
      all(t.group_band(n)["band"] for n in range(1, t.GROUP_MAX + 1)))
check("each band explains what it changes",
      all(len(t.group_band(n)["logistics"]) > 20 for n in (2, 10, 30)))

print("\nwhere next — the want-list, and only the want-list")
r = t.recommend(["France", "Japan"], want=["Bhutan", "Namibia"], want_only=True)
got = {p["country"] for p in r["recommendations"]}
check("nothing outside the want-list is suggested", got == {"Bhutan", "Namibia"}, str(got))
check("it is ranked rarest first",
      [p["country"] for p in r["recommendations"]] == ["Bhutan", "Namibia"])
# Tuvalu is below the 250k floor the open-ended recommender uses. Someone who
# typed it in has overruled that guard on purpose.
check("the size floor does not override an explicit want",
      "Tuvalu" in {p["country"] for p in
                   t.recommend([], want=["Tuvalu"], want_only=True)["recommendations"]})
check("the floor still applies when not in want-only mode",
      "Tuvalu" not in {p["country"] for p in
                       t.recommend([], want=[], want_only=False)["recommendations"]})
iraq = t.recommend([], want=["Iraq"], want_only=True)["recommendations"]
check("a want with no arrivals data is kept, not dropped",
      len(iraq) == 1 and iraq[0]["country"] == "Iraq")
check("and is marked as having no data", iraq[0]["has_data"] is False)
check("an empty want-list returns nothing to rank",
      t.recommend(["France"], want=[], want_only=True)["recommendations"] == [])
check("somewhere already visited is not suggested again",
      t.recommend(["Japan"], want=["Japan"], want_only=True)["recommendations"] == [])
check("the already-visited want is reported so the UI can explain itself",
      t.recommend(["Japan"], want=["Japan"], want_only=True)
      ["already_visited_from_want"] == ["Japan"])

print("\nextremes")
e = t.extremes(5)
check("most visited starts with France", e["most_visited"][0]["country"] == "France")
check("least visited is tiny", e["least_visited"][0]["arrivals"] < 100_000)

print("\n" + "=" * 62)
print(f"  {ok} passed, {len(fail)} failed")
for f in fail:
    print("   -", f)
print("=" * 62)
sys.exit(1 if fail else 0)
