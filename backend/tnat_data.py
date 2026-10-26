"""TNAT data layer — every number the agents are allowed to say.

One source: UN Tourism arrivals via Our World in Data, 206 countries, 1995-2024.
The agents have no numeric knowledge of their own; they may only report what
these functions return. That keeps "agents use real tools and data" true rather
than claimed.

Reference year is 2019 — the most recent year with broad coverage (174 of 206
countries) and before the pandemic distorted everything. Countries with no 2019
figure fall back to their nearest available year, and say so.
"""

from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data" / "owid_tourist_arrivals.csv"
ISO2_MAP = Path(__file__).resolve().parent.parent / "data" / "iso3_to_iso2.json"
ISO_REG = Path(__file__).resolve().parent.parent / "data" / "iso_registry.json"
COL = "Arrivals of tourists from abroad"
REF_YEAR = 2019
STALE_AFTER = 3          # a reference figure more than 3 years off is flagged
TOURIST_THRESHOLD = 40.0  # flow coverage % above which a profile reads "tourist"


@dataclass(frozen=True)
class Country:
    name: str
    iso3: str
    region: str
    series: dict[int, float]        # year -> arrivals
    ref_year: int                   # year used for the reference figure
    ref_arrivals: float

    @property
    def stale(self) -> bool:
        return abs(self.ref_year - REF_YEAR) > STALE_AFTER

    @property
    def years(self) -> list[int]:
        return sorted(self.series)


PANDEMIC = {2020, 2021}


def _pick_ref(series: dict[int, float]) -> tuple[int, float]:
    """Choose the year that best represents a country's normal travel volume.

    2020 and 2021 are skipped wherever possible: a country whose only nearby
    year is a pandemic year would otherwise look like almost nobody goes there.
    Japan, for instance, has no data before 2020 — its 2020 figure is 4M against
    a normal 30M+, so we take its most recent recovered year instead.
    """
    if REF_YEAR in series:
        return REF_YEAR, series[REF_YEAR]
    pre = [y for y in series if y < 2020]
    if pre:                                    # nearest pre-pandemic year
        y = max(pre)
        return y, series[y]
    post = [y for y in series if y >= 2022]
    if post:                                   # recovered years only
        y = max(post)
        return y, series[y]
    y = max(series)                            # nothing else available
    return y, series[y]


@lru_cache(maxsize=1)
def _iso2() -> dict[str, str]:
    """ISO3 -> ISO2, saved locally so the app needs no network to show a flag."""
    try:
        return json.loads(ISO2_MAP.read_text())
    except Exception:
        return {}


def iso2_of(c: "Country") -> str | None:
    return registry().get(c.iso3, {}).get("iso2") or _iso2().get(c.iso3)


@lru_cache(maxsize=1)
def registry() -> dict[str, dict]:
    """ISO 3166 reference: alpha-3 -> alpha-2, numeric, name."""
    try:
        return json.loads(ISO_REG.read_text())
    except Exception:
        return {}


def _rarity_quartiles() -> dict:
    vals = sorted(one_in(c) for c in all_countries())
    n = len(vals)
    return {f"p{q}": vals[int(n * q / 100)] for q in (25, 50, 75, 95)}


@lru_cache(maxsize=1)
def benchmarks() -> dict:
    """Reference points for reading a flow-coverage figure.

    "Your countries receive 55% of world travel" means nothing on its own —
    55% of what, and is that a lot? These are the anchors that make it legible,
    and the headline among them is genuinely surprising: international travel is
    so concentrated that a handful of countries absorb half of it.
    """
    ranked = sorted(all_countries(), key=lambda c: -c.ref_arrivals)
    cum, marks, half_n = 0.0, {}, None
    for i, c in enumerate(ranked, 1):
        cum += share_pct(c)
        if half_n is None and cum >= 50:
            half_n = i
        if i in (1, 5, 10, 20):
            marks[i] = round(cum, 1)
    return {
        "reference_year": REF_YEAR,
        "world_trips": int(world_total()),
        # These four have to reconcile on screen or 206 and 195 look like a
        # contradiction: destinations = countries_with_data + territories_with_data,
        # and countries_without_data is the remainder of the 195.
        "destinations_with_data": len(ranked),
        "un_countries": UN_COUNTRIES,
        "territories_with_data": sum(
            1 for c in ranked if classify(c.name)[0] == "territory"),
        "countries_with_data": sum(
            1 for c in ranked if classify(c.name)[0] == "country"),
        "countries_without_data": UN_COUNTRIES - sum(
            1 for c in ranked if classify(c.name)[0] == "country"),
        "most_visited": ranked[0].name,
        "most_visited_pct": round(share_pct(ranked[0]), 1),
        "top_1_pct": marks[1],
        "top_5_pct": marks[5],
        "top_10_pct": marks[10],
        "top_20_pct": marks[20],
        # the line worth putting on screen
        "countries_for_half": half_n,
        "tourist_threshold": TOURIST_THRESHOLD,
        # Quartiles of the 1-in-N distribution, so the copy can say "rarer than
        # three quarters of the world's destinations" and have it be true.
        # Hard-coded thresholds got this wrong: Namibia at 1 in 881 was being
        # called well-trodden when it is almost exactly the median.
        "rarity_quartiles": _rarity_quartiles(),
    }


# -------------------------------------------------------------- group travel
# Party size changes an itinerary more than style does. Four people walk into a
# restaurant; thirty need it booked weeks ahead and a coach to get there.
#
# The brief said "small under 5, medium 5-20, large 20-40", which makes 20 both
# medium and large. The boundary is resolved upward — a party of 20 is planned
# as medium, because that is the tier that still fits one minibus and one table.
GROUP_BANDS = (
    ("small", 1, 4, "moves on foot, in taxis or on public transport; "
                    "walk-ins are realistic"),
    ("medium", 5, 20, "one minibus, one restaurant table; most sites need "
                      "calling ahead but not months of notice"),
    ("large", 21, 40, "a coach, timed entry, block bookings, and some sites "
                      "simply cannot take the whole party at once"),
)
GROUP_MAX = GROUP_BANDS[-1][2]


def group_band(size: int) -> dict:
    """Which planning tier a party of this size falls into."""
    n = max(1, min(int(size), GROUP_MAX))
    for name, lo, hi, note in GROUP_BANDS:
        if lo <= n <= hi:
            return {"size": n, "band": name, "min": lo, "max": hi,
                    "logistics": note,
                    "label": f"{name} group ({lo}\u2013{hi})" if name != "small"
                             else f"small group (under {GROUP_BANDS[1][1]})"}
    raise ValueError(f"no band for {size}")


# ------------------------------------------------------- countries vs places
# Three different totals were on screen at once and they looked contradictory:
# "of the world's 195", "206 destinations with figures", "255 you can pin".
# All three are correct and they count different things, so the vocabulary is
# now fixed and used consistently everywhere:
#
#   country     a UN member state or observer  -> 195, the only denominator
#   destination anything UN Tourism publishes arrivals for -> 206
#   place       anything you can put a pin in -> 255
#
# ISO 3166-1 lists 249 entries. These 54 are dependencies, territories and
# special areas: real places you can travel to, but not countries. 249 - 54 =
# 195, and a test asserts exactly that, so an error in this table cannot pass
# unnoticed.
TERRITORIES = {
    "AIA": "GBR", "ABW": "NLD", "ASM": "USA", "ATA": None,  "ATF": "FRA",
    "BES": "NLD", "BLM": "FRA", "BMU": "GBR", "BVT": "NOR", "CCK": "AUS",
    "COK": "NZL", "CUW": "NLD", "CXR": "AUS", "CYM": "GBR", "ESH": None,
    "FLK": "GBR", "FRO": "DNK", "GGY": "GBR", "GIB": "GBR", "GLP": "FRA",
    "GRL": "DNK", "GUF": "FRA", "GUM": "USA", "HKG": "CHN", "HMD": "AUS",
    "IMN": "GBR", "IOT": "GBR", "JEY": "GBR", "MAC": "CHN", "MAF": "FRA",
    "MNP": "USA", "MSR": "GBR", "MTQ": "FRA", "MYT": "FRA", "NCL": "FRA",
    "NFK": "AUS", "NIU": "NZL", "PCN": "GBR", "PRI": "USA", "PYF": "FRA",
    "REU": "FRA", "SGS": "GBR", "SHN": "GBR", "SJM": "NOR", "SPM": "FRA",
    "SXM": "NLD", "TCA": "GBR", "TKL": "NZL", "UMI": "USA", "VGB": "GBR",
    "VIR": "USA", "WLF": "FRA", "ALA": "FIN", "TWN": None,
}


@lru_cache(maxsize=1)
def un_members() -> set[str]:
    """ISO3 codes of the 193 UN member states plus the 2 observer states."""
    return {k for k in registry() if k not in TERRITORIES}


@lru_cache(maxsize=1)
def _by_label_name() -> dict[str, dict]:
    return {r["name"]: r for r in labellable()}


def classify(name: str) -> tuple[str, str | None]:
    """Sort a pin into ('country' | 'territory' | 'unknown', canonical name).

    Hong Kong is somewhere you can genuinely travel to and it publishes its own
    arrivals, so it is a destination and it counts toward travel flow. It is
    not a UN member state, so it must not count toward 195 — pinning four
    territories used to claim "2.1% of the world".
    """
    if name in PARTS:
        return "country", PARTS[name]
    row = _by_label_name().get(name)
    canon = row["name"] if row else None
    iso3 = row.get("iso3") if row else None
    if iso3 is None:
        # No pinnable row, or a row with no ISO code. The United Kingdom lands
        # here: it is still a destination in the arrivals data, but its
        # pinnable row was replaced by its four nations.
        c = resolve(name)
        if c:
            canon = canon or c.name
            iso3 = iso3 or c.iso3
    if canon is None:
        return "unknown", None
    return ("country" if iso3 and iso3 in un_members() else "territory"), canon


@lru_cache(maxsize=1)
def _iso3_index() -> dict[str, str]:
    """Pinnable name -> ISO3, including the UK nations, which all map to GBR.

    The reference datasets are keyed on ISO3 and know nothing about Scotland,
    so distance, visas and climate for a UK nation are the United Kingdom's.
    """
    out = {}
    for r in labellable():
        if r.get("iso3"):
            out[r["name"]] = r["iso3"]
    for part, parent in PARTS.items():
        pr = next((r for r in labellable() if r["name"] == parent), None)
        out[part] = (pr or {}).get("iso3") or registry_iso3(parent) or "GBR"
    return out


def registry_iso3(name: str) -> str | None:
    for iso3, meta in registry().items():
        if meta.get("name") == name:
            return iso3
    return None


def iso3_of(name: str) -> str | None:
    """ISO3 for whatever the user pinned, resolving aliases where needed."""
    idx = _iso3_index()
    if name in idx:
        return idx[name]
    c = resolve(name)
    if c and c.iso3:
        return c.iso3
    return idx.get((c.name if c else ""), None)


def iso3_many(names: list[str]) -> list[str]:
    """Deduplicated ISO3 codes, preserving order."""
    out = []
    for n in names:
        i = iso3_of(n)
        if i and i not in out:
            out.append(i)
    return out


@lru_cache(maxsize=1)
def pinnable_iso3() -> list[str]:
    return sorted({r["iso3"] for r in labellable() if r.get("iso3")})


def name_of_iso3(iso3: str) -> str | None:
    for name, i in _iso3_index().items():
        if i == iso3 and name not in PARTS:
            return name
    return None


def coverage_counts(names: list[str]) -> dict:
    """Split a list of pins into countries, territories and anything unmatched."""
    countries, territories, unknown = set(), set(), []
    for n in names:
        kind, canon = classify(n)
        if kind == "country":
            countries.add(canon)
        elif kind == "territory":
            territories.add(canon)
        else:
            unknown.append(n)
    return {"countries": len(countries), "territories": len(territories),
            "unknown": unknown,
            "country_names": sorted(countries),
            "territory_names": sorted(territories)}


# ------------------------------------------------------------- constituent parts
# UN Tourism reports arrivals for the United Kingdom as a single country, but
# nobody says "I have been to the United Kingdom" — they went to Scotland. So
# the four nations are what you pin, and all four resolve to the UK's one
# arrivals figure. The dedup in resolve_many() then counts that figure exactly
# once no matter how many of the four are pinned: pinning England and Scotland
# must not claim 79 million arrivals.
PARTS = {
    "England": "United Kingdom",
    "Scotland": "United Kingdom",
    "Wales": "United Kingdom",
    "Northern Ireland": "United Kingdom",
}
PART_ISO2 = {"England": "gb-eng", "Scotland": "gb-sct",
             "Wales": "gb-wls", "Northern Ireland": "gb-nir"}


def sovereign_key(name: str) -> str | None:
    """The sovereign state a pin belongs to, for counting against the UN's 195.

    England and Scotland are two pins but one member state. Countries with no
    arrivals figure still get a key — a traveller who went to Iraq has been to
    a country, whatever UN Tourism published.
    """
    if name in PARTS:
        return PARTS[name]
    c = resolve(name)
    if c:
        return c.name
    n = _norm(name)
    return n or None


def count_sovereign(names: list[str]) -> int:
    """Distinct UN member states among these pins — the denominator is 195.

    Territories are deliberately excluded. They are still real places, still
    pinnable and still counted toward travel flow; they just are not countries.
    """
    return coverage_counts(names)["countries"]


@lru_cache(maxsize=1)
def labellable() -> list[dict]:
    """Every country a user can put a pin in.

    The arrivals dataset covers 206 countries, but a person can have been to
    Iraq or Afghanistan, which UN Tourism never published figures for. Leaving
    those off the map makes a user's own history look wrong. So the map carries
    the full ISO 3166 list; the ones without arrivals data are marked
    `has_data: false` and are excluded from the flow calculation rather than
    counted as zero.
    """
    by_iso3 = {c.iso3: c for c in all_countries()}
    out: list[dict] = []
    for iso3, meta in registry().items():
        c = by_iso3.get(iso3)
        row = {"iso3": iso3, "iso2": meta["iso2"], "num": meta["num"],
               "name": c.name if c else meta["name"],
               "region": c.region if c else (meta["region"] or "Other"),
               "has_data": c is not None}
        if c:
            row.update(arrivals=int(c.ref_arrivals),
                       share_pct=round(share_pct(c), 4),
                       one_in_n_trips=one_in(c),
                       reference_year=c.ref_year, stale=c.stale)
        out.append(row)
    # Territories world-atlas draws but ISO 3166 does not code. They show on the
    # map with id -99, so they are matched by name instead. A traveller can have
    # been to them, so they get a pin; only Kosovo has a flag code in common use.
    for name, iso2 in (("Kosovo", "xk"), ("N. Cyprus", None), ("Somaliland", None)):
        out.append({"iso3": None, "iso2": iso2, "num": None, "name": name,
                    "region": "Other", "has_data": False, "disputed": True})

    # The United Kingdom is replaced by its four nations. The UK row itself is
    # dropped so there is no way to pin both "Scotland" and "United Kingdom"
    # and wonder which one counted.
    uk = next((r for r in out if r["name"] == "United Kingdom"), None)
    if uk:
        out.remove(uk)
        for part, iso2 in PART_ISO2.items():
            row = dict(uk)
            row.update(name=part, iso2=iso2, iso3=None, num=None,
                       part_of="United Kingdom",
                       figures_are="United Kingdom")
            out.append(row)

    # arrivals-only entities that ISO does not list (e.g. OWID aggregates)
    for iso3, c in by_iso3.items():
        if iso3 not in registry():
            out.append({"iso3": iso3, "iso2": _iso2().get(iso3), "num": None,
                        "name": c.name, "region": c.region, "has_data": True,
                        "arrivals": int(c.ref_arrivals),
                        "share_pct": round(share_pct(c), 4),
                        "one_in_n_trips": one_in(c),
                        "reference_year": c.ref_year, "stale": c.stale})
    return sorted(out, key=lambda r: r["name"])


@lru_cache(maxsize=1)
def _load() -> tuple[dict[str, Country], float]:
    raw: dict[str, dict] = {}
    for r in csv.DictReader(DATA.open()):
        if not r["Code"] or not r[COL]:
            continue
        e = raw.setdefault(r["Entity"], {"iso3": r["Code"],
                                         "region": r["World region according to OWID"],
                                         "series": {}})
        e["series"][int(r["Year"])] = float(r[COL])

    countries: dict[str, Country] = {}
    for name, e in raw.items():
        s = e["series"]
        countries[name] = Country(name, e["iso3"], e["region"], s, *_pick_ref(s))
    denom = sum(c.ref_arrivals for c in countries.values())
    return countries, denom


def all_countries() -> list[Country]:
    return list(_load()[0].values())


def world_total() -> float:
    """Denominator: every country's reference-year arrivals, summed."""
    return _load()[1]


# --------------------------------------------------------------- name resolving
ALIASES = {
    "usa": "United States", "us": "United States", "america": "United States",
    "uk": "United Kingdom", "britain": "United Kingdom", "great britain": "United Kingdom",
    "england": "United Kingdom", "scotland": "United Kingdom", "wales": "United Kingdom",
    "uae": "United Arab Emirates", "emirates": "United Arab Emirates",
    "korea": "South Korea", "republic of korea": "South Korea",
    "north korea": "North Korea", "dprk": "North Korea",
    "russia": "Russia", "russian federation": "Russia",
    "czech republic": "Czechia", "holland": "Netherlands", "burma": "Myanmar",
    "ivory coast": "Cote d'Ivoire", "swaziland": "Eswatini",
    "drc": "Democratic Republic of Congo", "congo kinshasa": "Democratic Republic of Congo",
    "vatican": "Vatican", "turkiye": "Turkey", "cape verde": "Cape Verde",
    "macedonia": "North Macedonia", "east timor": "East Timor",
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z ]", "", s.lower().replace("&", "and")).strip()


def resolve(name: str) -> Country | None:
    """Turn whatever a user typed into a country, or None.

    A UK nation resolves to the United Kingdom, because that is the only level
    the arrivals data exists at.
    """
    countries, _ = _load()
    if name in PARTS:
        return countries.get(PARTS[name])
    if name in countries:
        return countries[name]
    n = _norm(name)
    if not n:
        return None
    if n in ALIASES and ALIASES[n] in countries:
        return countries[ALIASES[n]]
    by_norm = {_norm(k): k for k in countries}
    by_iso = {c.iso3.lower(): k for k, c in countries.items()}
    if n in by_norm:
        return countries[by_norm[n]]
    if n in by_iso:
        return countries[by_iso[n]]
    # Deliberately NOT a loose substring match. "mali" is inside "somalia" and
    # "guinea" is inside "equatorial guinea", so `n in norm` silently returned
    # the wrong country's statistics. Only a prefix match is allowed, and only
    # when it is unambiguous.
    hits = [k for norm, k in by_norm.items() if norm.startswith(n) or n.startswith(norm)]
    return countries[hits[0]] if len(hits) == 1 else None


def resolve_many(names: list[str]) -> tuple[list[Country], list[str]]:
    """Resolve a list, returning what matched and what did not."""
    found, missed = [], []
    seen = set()
    for n in names:
        c = resolve(n)
        if c and c.name not in seen:
            seen.add(c.name)
            found.append(c)
        elif not c:
            missed.append(n)
    return found, missed


# --------------------------------------------------------------------- metrics
def share_pct(c: Country) -> float:
    """This country's share of world travel flow, in percent."""
    return c.ref_arrivals / world_total() * 100


def rarity(c: Country) -> float:
    """-log10(share%). France ~ -0.85, Bhutan ~ +1.6, Tuvalu ~ +3.5."""
    return -math.log10(max(share_pct(c), 1e-6))


def one_in(c: Country) -> int:
    """'1 in N of the world's trips goes here' — the human-readable form."""
    s = share_pct(c)
    return int(round(100 / s)) if s > 0 else 0


# ------------------------------------------------------------------ the tools
def country_stats(name: str) -> dict:
    """Everything known about one country."""
    c = resolve(name)
    if not c:
        return {"found": False, "query": name}
    ranked = sorted(all_countries(), key=lambda x: -x.ref_arrivals)
    return {
        "found": True, "country": c.name, "iso3": c.iso3, "iso2": iso2_of(c),
        "region": c.region,
        "arrivals": int(c.ref_arrivals), "reference_year": c.ref_year,
        "share_of_world_travel_pct": round(share_pct(c), 4),
        "one_in_n_trips": one_in(c),
        "rank": ranked.index(c) + 1, "of_countries": len(ranked),
        "rarity": round(rarity(c), 3),
        "years_available": [c.years[0], c.years[-1]], "n_years": len(c.years),
        "stale": c.stale,
        "note": (f"No {REF_YEAR} figure; using {c.ref_year}." if c.ref_year != REF_YEAR else None),
    }


def profile_score(visited: list[str]) -> dict:
    """The verdict: how much of world travel flow these countries represent."""
    found, missed = resolve_many(visited)
    if not found:
        return {"n_countries": 0, "unmatched": missed,
                "error": "No countries recognised."}
    flow = sum(share_pct(c) for c in found)
    rare = sum(rarity(c) for c in found) / len(found)
    ranked = sorted(found, key=lambda c: share_pct(c))
    return {
        "n_countries": len(found),
        "countries": [c.name for c in found],
        "unmatched": missed,
        "flow_coverage_pct": round(flow, 2),
        "rarity_score": round(rare, 3),
        "verdict": "tourist" if flow > TOURIST_THRESHOLD else "traveler",
        "threshold_pct": TOURIST_THRESHOLD,
        "rarest": {"country": ranked[0].name, "share_pct": round(share_pct(ranked[0]), 4),
                   "one_in_n": one_in(ranked[0])},
        "most_popular": {"country": ranked[-1].name,
                         "share_pct": round(share_pct(ranked[-1]), 4)},
        "stale_figures": [c.name for c in found if c.stale],
        "regions": sorted({c.region for c in found}),
    }


def off_path(visited: list[str], cutoff: int = 50) -> dict:
    """How many of a traveller's countries sit in the world's least-visited tail.

    Exact, from the arrivals data, and it does what the estimated percentile was
    meant to do: reward going somewhere few people go.
    """
    found, _ = resolve_many(visited)
    ranked = sorted(all_countries(), key=lambda c: c.ref_arrivals)
    tail = {c.name for c in ranked[:cutoff]}
    hits = [c.name for c in found if c.name in tail]
    return {"cutoff": cutoff, "in_tail": len(hits), "countries": sorted(hits),
            "of_visited": len(found)}


def whats_left(visited: list[str]) -> dict:
    """The flip side — what share of world travel is still unseen."""
    found, _ = resolve_many(visited)
    seen = {c.name for c in found}
    rest = [c for c in all_countries() if c.name not in seen]
    return {
        "visited": len(seen),
        "remaining": len(rest),
        "remaining_share_pct": round(sum(share_pct(c) for c in rest), 2),
        "biggest_unvisited": [
            {"country": c.name, "share_pct": round(share_pct(c), 3)}
            for c in sorted(rest, key=lambda x: -x.ref_arrivals)[:5]
        ],
    }


def trajectory(name: str, visited_year: int | None = None) -> dict:
    """How a country's popularity has moved, and whether you got there early."""
    c = resolve(name)
    if not c:
        return {"found": False, "query": name}
    ys = c.years
    first, last = ys[0], ys[-1]
    out = {
        "found": True, "country": c.name,
        "first_year": first, "last_year": last, "n_years": len(ys),
        "series": {str(y): int(c.series[y]) for y in ys},
        "first_value": int(c.series[first]), "last_value": int(c.series[last]),
        "change_pct": round((c.series[last] / c.series[first] - 1) * 100, 1)
        if c.series[first] else None,
        "gaps": [y for y in range(first, last + 1) if y not in c.series],
    }
    if visited_year is not None:
        near = min(ys, key=lambda y: abs(y - visited_year))
        then, now = c.series[near], c.series[last]
        out["you_went"] = {
            "year_asked": visited_year, "year_used": near,
            "arrivals_then": int(then), "arrivals_now": int(now),
            "growth_since_pct": round((now / then - 1) * 100, 1) if then else None,
            "were_you_early": bool(then and now / then >= 1.5),
        }
    return out


MIN_REAL_DESTINATION = 250_000   # arrivals below this and it is not a trip, it is an expedition


def recommend(visited: list[str], want: list[str] | None = None,
              region: str | None = None, limit: int = 8,
              min_arrivals: int = MIN_REAL_DESTINATION,
              diversify: bool = True, want_only: bool = False) -> dict:
    """Countries that would most improve a traveler score.

    Ranked by rarity, but only among places a person can actually go. Pure
    rarity ranking returns Tuvalu, Kiribati and the Marshall Islands — true,
    and useless as advice. The floor keeps destinations with real tourism
    infrastructure; `diversify` then caps how many come from one region so the
    answer is not six Central Asian republics.

    `want_only` restricts the pool to the user's own want-list and turns both
    guards off. They are there to stop the machine proposing an expedition to
    somewhere nobody goes — but if a person has said outright that they want to
    go to Tuvalu, filtering Tuvalu out for being too small is not protecting
    them from anything. It is ignoring them.
    """
    found, _ = resolve_many(visited)
    seen = {c.name for c in found}
    want_set = {c.name for c in resolve_many(want or [])[0]}
    no_data_wants: list[dict] = []

    if want_only:
        pool = [c for c in all_countries() if c.name in want_set and c.name not in seen]
        too_small, diversify, region = [], False, None
        # A want-list entry with no arrivals figure still belongs in the answer;
        # it simply cannot be ranked. Dropping it silently would look like a bug
        # to the one person who put it there.
        for n in (want or []):
            c = resolve(n)
            if c is None:
                no_data_wants.append({"country": n, "has_data": False,
                                      "on_want_list": True})
            elif c.name in seen:
                continue
    else:
        pool = [c for c in all_countries() if c.name not in seen]
        too_small = [c.name for c in pool if c.ref_arrivals < min_arrivals]
        pool = [c for c in pool if c.ref_arrivals >= min_arrivals]
    if region:
        pool = [c for c in pool if c.region.lower() == region.lower()]
    base = profile_score(visited) if found else None

    scored = []
    for c in pool:
        new_flow = (base["flow_coverage_pct"] + share_pct(c)) if base else share_pct(c)
        n = (base["n_countries"] + 1) if base else 1
        new_rare = ((base["rarity_score"] * base["n_countries"] + rarity(c)) / n) if base else rarity(c)
        scored.append({
            "country": c.name, "iso3": c.iso3, "region": c.region,
            "arrivals": int(c.ref_arrivals), "reference_year": c.ref_year,
            "share_pct": round(share_pct(c), 4), "one_in_n_trips": one_in(c),
            "rarity": round(rarity(c), 3),
            "rarity_after": round(new_rare, 3),
            "rarity_gain": round(new_rare - base["rarity_score"], 4) if base else None,
            "on_want_list": c.name in want_set,
            "stale": c.stale,
        })
    scored.sort(key=lambda d: (not d["on_want_list"], -d["rarity"]))

    if diversify and not region:
        cap = max(2, limit // 3)
        picked, per_region = [], {}
        for d in scored:
            if d["on_want_list"] or per_region.get(d["region"], 0) < cap:
                picked.append(d)
                per_region[d["region"]] = per_region.get(d["region"], 0) + 1
            if len(picked) == limit:
                break
        scored = picked

    picks = scored[:limit] + no_data_wants
    return {"based_on": len(seen), "pool": len(pool), "region": region,
            "min_arrivals": None if want_only else min_arrivals,
            "want_only": want_only,
            "want_listed": sorted(want_set),
            "already_visited_from_want": sorted(want_set & seen),
            "excluded_too_small": len(too_small),
            "recommendations": picks}


# Pew Research Center, Spring 2023, 24 countries. Medians per bucket, so they
# do not sum to 100. The top bucket is "10 or more" — the data cannot resolve
# above ten, which is why no exact percentile is ever returned.
PEW = [(0, 0, 21), (1, 4, 34), (5, 9, 17), (10, 10**6, 13)]


# Cumulative share of people who have visited AT LEAST this many countries,
# derived from the Pew buckets. Unlike the buckets themselves this falls
# monotonically, which is what "how rare am I" actually means: the more
# countries you have seen, the smaller the group you belong to.
#   >=1  : 100 - 21            = 79%
#   >=5  : 17 + 13             = 30%
#   >=10 : 13                  = 13%
# Above 10 the survey cannot resolve, so the only honest figures beyond it are
# the Travelers' Century Club estimates, flagged as estimates.
# The UN has 193 members plus 2 permanent observers (Vatican, Palestine). 195 is
# the count every travel tracker uses, so a user's number here matches what they
# see elsewhere.
UN_COUNTRIES = 195

# Pew Research Center, Spring 2023, 24 countries. Cumulative: the share of
# people who have visited AT LEAST this many. Pew's top bucket is "10 or more",
# so the series genuinely stops there and this does too.
AT_LEAST = [(0, 100.0), (1, 79.0), (5, 30.0), (10, 13.0)]


def world_coverage(n_countries: int) -> dict:
    """Share of the world's countries visited — countries / 195.

    This is the figure every travel tracker reports, it needs no survey and no
    estimate, and it is the number a user expects to see. An earlier version of
    this file tried to interpolate a "top X% of travellers" percentile between
    Pew's 13%-at-ten and a club membership count. That was an estimate stacked
    on an estimate, and it is gone: nothing here is now unsourceable.
    """
    pct = n_countries / UN_COUNTRIES * 100
    return {"n_countries": n_countries, "of_countries": UN_COUNTRIES,
            "world_pct": round(pct, 1),
            "display": f"{pct:.1f}%",
            "remaining": max(UN_COUNTRIES - n_countries, 0)}


def peer_context(n_countries: int) -> dict:
    """What a survey can honestly say about someone with this many countries."""
    share = next(p for floor, p in reversed(AT_LEAST) if n_countries >= floor)
    out = {"n_countries": n_countries, "at_least_share_pct": share,
           "source": "Pew Research Center, Spring 2023, 24 countries"}
    if n_countries == 0:
        out["sentence"] = "21% of people in surveyed countries have never left their own."
    elif n_countries >= 10:
        out["sentence"] = (
            f"13% of people in surveyed countries have visited ten or more. "
            f"That is the smallest group the survey measures, so it cannot place "
            f"{n_countries} any more precisely than that.")
    else:
        out["sentence"] = (
            f"{share:g}% of people in surveyed countries have visited "
            f"{next(f for f, _ in reversed(AT_LEAST) if n_countries >= f)} or more.")
    out["caveat"] = ("Pew surveyed 24 mostly wealthier countries, so this is not a "
                     "world figure. Weighted by population it would be rarer.")
    return out


def peer_band(n_countries: int) -> dict:
    """Where a traveller sits against survey data, with the ceiling stated."""
    band = next(b for b in PEW if b[0] <= n_countries <= b[1])
    out = {
        "n_countries": n_countries,
        "band_share_pct": band[2],
        "band_label": ("never left home country" if band[1] == 0
                       else f"{band[0]}-{band[1]} countries" if band[1] < 1000
                       else "10 or more countries"),
        "source": "Pew Research Center, Spring 2023, 24 countries",
        "ceiling_reached": n_countries >= 10,
        "caveat": None,
    }
    if n_countries >= 10:
        out["caveat"] = ("The survey's top bucket is '10 or more', so it cannot "
                         "distinguish 10 from 34 from 94. No exact percentile exists.")
    out["world_coverage"] = world_coverage(n_countries)
    out["context"] = peer_context(n_countries)
    if n_countries >= 70:
        out["rarity_note"] = ("For reference only, not a computed statistic: the "
                              "Travelers' Century Club has roughly 1,500 members after "
                              "seventy years. No survey resolves this far out, so the "
                              "site does not claim a percentile.")
    return out


def extremes(n: int = 10) -> dict:
    """The two ends of the distribution."""
    ranked = sorted(all_countries(), key=lambda c: -c.ref_arrivals)
    fmt = lambda c: {"country": c.name, "arrivals": int(c.ref_arrivals),
                     "share_pct": round(share_pct(c), 4), "one_in_n_trips": one_in(c),
                     "reference_year": c.ref_year}
    return {"most_visited": [fmt(c) for c in ranked[:n]],
            "least_visited": [fmt(c) for c in ranked[-n:][::-1]]}
