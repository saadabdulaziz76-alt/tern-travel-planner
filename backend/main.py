"""TNAT API.

Split deliberately in two:

  * the statistics come from pure Python and answer in about 0.05 ms
  * the agents only write prose, and gpt-6-luna takes seconds to minutes

So the map fills in its numbers instantly and the commentary arrives after.
Making a user wait a minute to be told they are a tourist would be a worse
product and would not have been any more accurate.
"""

from __future__ import annotations

import json
import os
import uuid
from collections import defaultdict, deque

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import agents
import auth
import config
import guard
import quiz
import reference as R
import tnat_data as D
import usage_log

WEB = __import__("pathlib").Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="Traveler Not a Tourist", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173",
                   "http://localhost:4173", "http://127.0.0.1:4173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# test1 / test2 with password 12345678, so the app can be tried without
# signing up. Only these two demo accounts are ever touched, and never their maps.
auth.seed_test_accounts()

# Ceilings the per-run usage limits cannot give: UsageLimits stops one runaway
# call, not ten thousand well-behaved ones, which is the same bill.
BUDGET = guard.Budget(
    daily_tokens=int(os.getenv("TNAT_DAILY_TOKENS", "400000")),
    daily_calls=int(os.getenv("TNAT_DAILY_CALLS", "300")),
    session_calls=int(os.getenv("TNAT_SESSION_CALLS", "40")),
)


# The budget protects the total bill. This stops one caller eating all of it
# and leaving nothing for anyone else.
THROTTLE = guard.Throttle(limit=int(os.getenv("TNAT_PER_MINUTE", "12")), window=60.0)


def _caller(request: Request | None) -> str:
    return (request.client.host if request and request.client else "unknown")


def _throttle_ok(request: Request | None, what: str) -> None:
    who = _caller(request)
    v = THROTTLE.check(who)
    if not v["ok"]:
        guard.record("throttled", caller=who, route=what, retry_after=v["retry_after"])
        raise HTTPException(429, f"Too many requests. Try again in {v['retry_after']}s.")
    THROTTLE.record(who)


def _spend_ok(session: str = "anon") -> None:
    v = BUDGET.check(session)
    if not v["ok"]:
        guard.record("budget_block", session=session, reason=v["reason"],
                     **BUDGET.snapshot())
        raise HTTPException(429, f"{v['reason'].capitalize()} — {v['retry']}.")


def _scrub(payload: dict) -> dict:
    """Run every string in a model response through the leak check.

    Chat was screened from the start; the structured routes were not, and a
    headline is just as capable of carrying a leaked key as a chat reply.
    """
    leaked: list[str] = []

    def walk(v):
        if isinstance(v, str):
            out = guard.screen_output(v)
            leaked.extend(out["leaked"])
            return out["text"]
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        return v

    cleaned = walk(payload)
    if leaked:
        guard.record("output_redacted", leaked=sorted(set(leaked)))
    return cleaned


def _verified(run, extra_context=None) -> dict:
    """Check the model's figures against what the tools actually returned.

    The product claim is that every number is counted. A figure the tools never
    produced is the failure that matters most here, so it is surfaced rather
    than quietly passed through.
    """
    allowed = guard.collect_allowed(run.tool_returns)
    if extra_context is not None:
        allowed |= guard.collect_allowed(extra_context)
    text = run.output if isinstance(run.output, str) else json.dumps(
        run.output.model_dump() if hasattr(run.output, "model_dump") else run.output,
        default=str)
    v = guard.check_numbers(text, allowed)
    if not v["ok"]:
        guard.record("unverified_figures", figures=v["unsupported"][:10],
                     checked=v["checked"])
    return v

# Per-session conversation, stored as the ModelMessage objects pydantic-ai
# returns. An earlier version kept ("user", text) tuples here and handed them
# back as message_history, which crashed the second message of every chat.
CHATS: dict[str, list] = defaultdict(list)

MAX_COUNTRIES = 206
MAX_CHARS = config.MAX_MESSAGE_CHARS


MAX_LABEL_CHARS = 80


class Labels(BaseModel):
    # Per-item length matters as much as list length: 206 labels of 2,000
    # characters each is a 400 KB prompt, which is a bill, not a map.
    visited: list[str] = Field(default_factory=list, max_length=MAX_COUNTRIES)
    lived: list[str] = Field(default_factory=list, max_length=MAX_COUNTRIES)
    want: list[str] = Field(default_factory=list, max_length=MAX_COUNTRIES)

    @field_validator("visited", "lived", "want")
    @classmethod
    def _cap(cls, v: list[str]) -> list[str]:
        return [s[:MAX_LABEL_CHARS] for s in v if isinstance(s, str) and s.strip()]
    # ISO3 codes. Optional throughout: every page works without them, they just
    # unlock the distance, carbon, visa and routing figures.
    home: str | None = Field(default=None, max_length=3)
    passport: str | None = Field(default=None, max_length=3)
    # Optional city within the home country. Distances start here rather than
    # at the country's capital — Jeddah to Riyadh alone is 850 km.
    home_city: str | None = Field(default=None, max_length=80)
    # place name -> year visited, all optional
    years: dict[str, int] | None = None


class ProfileIn(BaseModel):
    home: str | None = Field(default=None, max_length=3)
    passport: str | None = Field(default=None, max_length=3)
    home_city: str | None = Field(default=None, max_length=80)


class Credentials(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=auth.MAX_PASSWORD)


class Signup(Credentials):
    confirm: str = Field(max_length=auth.MAX_PASSWORD)
    # a guest who painted a map before signing up keeps it
    carry: Labels | None = None


class ItineraryRequest(BaseModel):
    country: str = Field(max_length=80)
    days: int = Field(ge=1, le=30)
    hours_per_day: int = Field(ge=1, le=14)
    style: str = Field(description="cultural | relaxing | mixed")
    accommodation: str = Field(default="3-star",
                               description="5-star | 4-star | 3-star | hostel")
    local_guide: bool = False
    # The exact head count, not just the tier — planning for 6 and planning for
    # 19 are both "medium" and are not the same trip.
    group_size: int = Field(default=2, ge=1, le=D.GROUP_MAX)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_CHARS)
    session_id: str | None = None


# ----------------------------------------------------------------- instant tier
@app.get("/api/health")
def health():
    return {"ok": True, "model": config.MODEL_NAME, "key": config.which_key(),
            "key_present": config.api_key_present(),
            "destinations": len(D.all_countries()),
            "countries": len(D.un_members()),
            "places_pinnable": len(D.labellable()),
            "reference_year": D.REF_YEAR,
            "world_total_arrivals": int(D.world_total())}


@app.get("/api/countries")
def countries():
    """Every country a pin can go in — including those with no arrivals data."""
    rows = D.labellable()
    return {"reference_year": D.REF_YEAR,
            "with_data": sum(1 for r in rows if r["has_data"]),
            "total": len(rows),
            "un_members": len(D.un_members()),
            "countries": rows}


@app.post("/api/profile")
def profile(labels: Labels):
    """The numbers. No model involved — this returns in well under a millisecond."""
    visited = labels.visited + labels.lived
    score = D.profile_score(visited)
    n = score.get("n_countries", 0)
    places = sorted(set(labels.visited) | set(labels.lived))
    # Counted against the UN's 195, so the four UK nations are one member state.
    # Countries with no arrivals figure still count — a traveller who went to
    # Iraq has been to a country, whatever UN Tourism published.
    cov = D.coverage_counts(places)
    pinned = cov["countries"]
    return {"profile": score,
            "n_places": len(places),
            "coverage": cov,
            "whats_left": D.whats_left(visited),
            "peer_band": D.peer_band(n),
            "world_coverage": D.world_coverage(pinned),
            "peer_context": D.peer_context(pinned),
            "off_path": D.off_path(visited),
            "benchmarks": D.benchmarks(),
            **_extras(places, labels.home, labels.passport, labels.home_city,
                      labels.years),
            "lived_count": len(D.resolve_many(labels.lived)[0]),
            "want_count": len(D.resolve_many(labels.want)[0])}


@app.get("/api/country/{name}")
def country(name: str, visited_year: int | None = None):
    stats = D.country_stats(name)
    if not stats.get("found"):
        raise HTTPException(404, f"No country matching {name!r}.")
    return {"stats": stats, "trajectory": D.trajectory(name, visited_year)}


@app.get("/api/extremes")
def extremes(n: int = 10):
    return D.extremes(min(max(n, 1), 25))


@app.get("/api/safety")
def safety():
    """What the defences are set to, and what they have caught.

    Exposed so the report can cite real counts instead of describing intentions.
    """
    events = []
    try:
        with guard.LOG.open() as fh:
            events = [json.loads(l) for l in fh if l.strip()][-50:]
    except OSError:
        pass
    counts: dict[str, int] = {}
    for e in events:
        counts[e["event"]] = counts.get(e["event"], 0) + 1
    return {"budget": BUDGET.snapshot(),
            "per_run_limits": {"requests": config.MAX_REQUESTS_PER_RUN,
                               "tool_calls": config.MAX_TOOL_CALLS_PER_RUN,
                               "message_chars": config.MAX_MESSAGE_CHARS,
                               "label_chars": MAX_LABEL_CHARS,
                               "requests_per_minute": THROTTLE.limit},
            "injection_patterns": len(guard.COMPILED),
            "recent_events": events[-20:], "counts": counts}


@app.get("/api/usage")
def usage():
    """Token totals, read straight off the append-only log."""
    return usage_log.summary()


# ------------------------------------------------------------------ agent tier
@app.post("/api/verdict")
async def verdict(labels: Labels, request: Request = None):
    visited = labels.visited + labels.lived
    if not visited:
        raise HTTPException(400, "Label some countries first.")
    ctx = agents.prefetch(visited, labels.want)
    _throttle_ok(request, "verdict")
    _spend_ok("verdict")
    run = await agents.run(
        "profile_analyst",
        # Only names the dataset recognises reach the model. A label is user
        # text, and user text in a prompt is an injection vector — the UI only
        # offers real countries, but the API will accept any string.
        f"{ctx}\n\nThe user has visited: {', '.join(_known(visited))}."
        + (f" They have lived in: {', '.join(_known(labels.lived))}." if labels.lived else "")
        + " Give them their verdict.")
    BUDGET.record("verdict", (run.usage or {}).get("input_tokens", 0)
                  + (run.usage or {}).get("output_tokens", 0))
    v = _verified(run, ctx)
    return {"verdict": _scrub(run.output.model_dump()), "usage": run.usage,
            "verified": v["ok"], "unverified_figures": v["unsupported"][:5]}


def _known(names: list[str]) -> list[str]:
    """Drop anything the dataset does not recognise, before it reaches a prompt."""
    out = []
    for n in names[:MAX_COUNTRIES]:
        c = D.resolve(n)
        if c:
            out.append(c.name)
        elif n in D._by_label_name():
            out.append(n)
    return out


def _trip_origin(body):
    """Where this trip starts: the stated origin if there is one, else home."""
    if getattr(body, "origin_iso3", None):
        return _origin(body.origin_iso3, getattr(body, "origin_city", None))
    return _origin(body.home, body.home_city)


def _origin_label(body, cityinfo) -> str:
    if cityinfo:
        return f"{cityinfo['city']}, {cityinfo['state']}" if cityinfo.get("state") else cityinfo["city"]
    iso = getattr(body, "origin_iso3", None) or body.home
    return R.facts().get(iso, {}).get("capital") or (iso or "home")


def _origin(home: str | None, city: str | None):
    """The point distances are measured from: the chosen city, else the capital."""
    if home and city:
        p = R.city_point(home, city)
        if p:
            return (p["lat"], p["lon"]), p
    return (R.point(home) if home else None), None


def _extras(places: list[str], home: str | None, passport: str | None,
            city: str | None = None, years: dict | None = None) -> dict:
    """Everything that depends on the reference data.

    All of it degrades rather than fails: with no home country you still get
    languages, currencies and blind spots, you just do not get distance,
    carbon or routing. The front end hides what is absent instead of showing
    an empty figure.
    """
    iso = D.iso3_many(places)
    pool = D.pinnable_iso3()
    out: dict = {
        "reach": R.reach(iso),
        "blind_spots": R.blind_spots(iso, pool)[:6],
        "home": None, "passport": None,
    }
    home = (home or "").strip().upper() or None
    passport = (passport or "").strip().upper() or None
    if home and R.point(home):
        origin, cityinfo = _origin(home, city)
        out["home"] = home
        out["home_city"] = cityinfo
        # Years make the trip grouping much better: two countries tagged 2019
        # were probably one journey however far apart they are.
        by_iso = {}
        for name, yr in (years or {}).items():
            code = D.iso3_of(name)
            if code:
                by_iso[code] = yr
        out["footprint"] = R.footprint(home, iso, origin=origin, years=by_iso or None)
        out["footprint"]["from"] = (f"{cityinfo['city']}, {cityinfo['state']}"
                                    if cityinfo else
                                    (R.facts().get(home, {}).get("capital") or home))
        out["nearest_unvisited"] = [
            {**n, "name": D.name_of_iso3(n["iso3"]) or n["iso3"]}
            for n in R.nearest_unvisited(home, iso, pool, limit=6, origin=origin)]
    if passport:
        v = R.visa_summary(passport, iso)
        if v.get("known"):
            out["passport"] = passport
            v["easy_unvisited_names"] = [
                D.name_of_iso3(i) for i in v["easy_unvisited"][:400]]
            v["easy_unvisited_names"] = [n for n in v["easy_unvisited_names"] if n]
            v.pop("easy_unvisited", None)
            out["visa"] = v
    return out


@app.get("/api/cities")
def city_search(country: str, q: str = "", limit: int = 12):
    """Cities in one country. Scoped to a country because "Springfield" is
    ambiguous worldwide and obvious once you know which country is meant.

    The cap used to be 25, which is right for an autocomplete and wrong for a
    picker: it silently cut the United States off at 25 of its 3,408 cities,
    so most places simply could not be chosen as a stop or a starting point.
    The ceiling now admits the largest country in the set.
    """
    return {"country": country.upper(),
            "cities": R.search_cities(country, q, min(max(limit, 1), 4000))}


# ------------------------------------------------------------- collections
@app.get("/api/collections/parks")
def collection_parks(country: str | None = None, q: str | None = None):
    """The national parks of the United States and Canada, with photographs.

    Photographs are Wikimedia Commons files referenced by URL — freely
    licensed, and we link rather than copy.
    """
    rows = R.parks()
    if country:
        rows = [p for p in rows if p["iso3"] == country.upper()]
    if q:
        needle = q.strip().lower()
        rows = [p for p in rows
                if needle in p["name"].lower() or needle in (p["state"] or "").lower()]
    # Five apiece that a traveller would choose first. This is a hand-picked
    # list, not a ranking: attendance only answers which parks are busiest, and
    # could not answer even that for Canada, where two parks publish a figure.
    return {"parks": rows, "total": len(rows),
            "first_picks": {"USA": R.first_picks("USA"),
                            "CAN": R.first_picks("CAN")},
            "countries": {"USA": sum(1 for p in R.parks() if p["iso3"] == "USA"),
                          "CAN": sum(1 for p in R.parks() if p["iso3"] == "CAN")},
            "source": R.parks_file().get("source", "")}


class ParkIn(BaseModel):
    id: str = Field(max_length=32)
    home: str | None = Field(default=None, max_length=3)
    home_city: str | None = Field(default=None, max_length=80)


@app.post("/api/collections/park")
def park_detail(body: ParkIn):
    """One park, with the journey from where the user lives. No model."""
    park = R.park_by_id(body.id)
    if not park:
        raise HTTPException(404, "No such park.")
    origin, cityinfo = _origin(body.home, body.home_city)
    journey = None
    if origin:
        journey = R.journey_to_park(origin, (body.home or "").upper(), park)
        journey["from"] = (f"{cityinfo['city']}, {cityinfo['state']}" if cityinfo
                           else R.facts().get(body.home, {}).get("capital") or body.home)
    return {"park": park, "journey": journey}


@app.post("/api/collections/park/guide")
async def park_guide(body: ParkIn, request: Request = None):
    """What the park is for and when to go. The one part that needs a model."""
    _throttle_ok(request, "park_guide")
    park = R.park_by_id(body.id)
    if not park:
        raise HTTPException(404, "No such park.")
    country = R.facts().get(park["iso3"], {}).get("name", park["iso3"])
    _spend_ok("park_guide")
    run = await agents.run(
        "park_guide",
        f"{park['name']}, {park['state']}, {country}.\n"
        + (f"Established {park['established']}. " if park.get("established") else "")
        + (f"Area about {park['area_km2']:,} square kilometres.\n"
           if park.get("area_km2") else "\n")
        + "\nWrite the page.")
    BUDGET.record("park_guide", (run.usage or {}).get("input_tokens", 0)
                  + (run.usage or {}).get("output_tokens", 0))
    v = _verified(run, {"area": park.get("area_km2"), "year": park.get("established")})
    return {"guide": _scrub(run.output.model_dump()), "usage": run.usage,
            "verified": v["ok"], "unverified_figures": v["unsupported"][:5]}


@app.get("/api/collections/heritage")
def heritage_list(country: str | None = None, q: str | None = None):
    """UNESCO World Heritage sites, for one country at a time."""
    rows = R.heritage(country)
    if q:
        needle = q.strip().lower()
        rows = [r for r in rows if needle in r["name"].lower()]
    rows.sort(key=lambda r: r["name"])
    return {"sites": rows, "total": len(rows),
            "countries": R.heritage_countries(),
            "source": R.unesco_file().get("source", ""),
            "caveat": "Counted from Wikidata rather than UNESCO's own feed, "
                      "which blocks automated access. A handful of entries are "
                      "a component of a listing whose parent record is missing, "
                      "so a country's count can run slightly above the official "
                      "figure."}


@app.get("/api/quiz")
def quiz_round(kind: str = "mixed", n: int = 10, seed: int | None = None):
    """A round of geography questions, generated from our own reference data.

    The correct index travels with the question. This is a single-player quiz
    played against yourself on your own machine, so grading on the client is
    the simpler design and the only person a devtools window would cheat is
    the person who opened it.
    """
    return {"questions": quiz.round_of(kind, min(max(n, 1), 25), seed),
            "kinds": list(quiz.BUILDERS)}


@app.get("/api/visa")
def visa_map(passport: str):
    """Every destination this passport can reach, and how.

    One small payload so the trip picker can filter and warn without a round
    trip per country.
    """
    p = (passport or "").strip().upper()
    row = R.visa_table().get(p)
    if not row:
        raise HTTPException(404, f"No visa data for passport {p!r}.")
    out = {}
    # The UK is pinnable only as its four nations, which carry no ISO3, so GBR
    # never appeared here and the trip picker could not say whether London
    # needed a visa. It is one destination for travel purposes.
    for iso3 in sorted(set(D.pinnable_iso3()) | {"GBR"}):
        st = R.visa_status(p, iso3)
        if st:
            out[iso3] = {"code": st["code"], "easy": st["easy"],
                         "advance": st["advance"], "action": st["action"],
                         "detail": st["detail"]}
    return {"passport": p, "destinations": out}


@app.get("/api/city-search")
def city_search_global(q: str, limit: int = 10):
    """Find a city anywhere, for someone who has not set a home."""
    return {"cities": R.find_city(q, min(max(limit, 1), 20))}


# What the scout can rank for. No dataset labels a city "romantic", so the
# themes shape the model's judgement over a shortlist the data already chose.
THEMES = {
    "romantic": "romantic",
    "hiking": "hiking and outdoors",
    "food": "food and drink",
    "history": "history and culture",
    "beach": "beach and water",
    "nightlife": "nightlife",
    "family": "family, with children",
}


@app.get("/api/getaway/themes")
def getaway_themes():
    return {"themes": [{"key": k, "label": v} for k, v in THEMES.items()]}


class GetawayIn(BaseModel):
    # either a saved home (country + optional city) or a city picked by hand
    home: str | None = Field(default=None, max_length=3)
    home_city: str | None = Field(default=None, max_length=80)
    lat: float | None = None
    lon: float | None = None
    from_iso3: str | None = Field(default=None, max_length=3)
    from_label: str | None = Field(default=None, max_length=120)
    passport: str | None = Field(default=None, max_length=3)
    max_km: int = Field(default=600, ge=100, le=1500)
    theme: str | None = Field(default=None, max_length=24)


def _getaway_origin(b: GetawayIn):
    """Where the weekend starts, however the user told us."""
    if b.lat is not None and b.lon is not None and b.from_iso3:
        return (b.lat, b.lon), b.from_iso3, (b.from_label or ""), None
    if b.home:
        origin, city = _origin(b.home, b.home_city)
        label = (f"{city['city']}, {city['state']}" if city
                 else R.facts().get(b.home, {}).get("capital") or b.home)
        return origin, b.home, label, (city or {}).get("city")
    return None, None, "", None


@app.post("/api/getaway")
def getaway(body: GetawayIn):
    """Places near enough for a weekend. Instant: no model involved."""
    origin, iso, label, city = _getaway_origin(body)
    if not origin or not iso:
        raise HTTPException(400, "Tell me which city you are starting from.")
    picks = R.getaways(origin[0], origin[1], iso, max_km=body.max_km,
                       exclude_city=city, min_pop=75_000, limit=9, per_state=2)
    passport = (body.passport or "").strip().upper() or None
    for p in picks:
        if passport:
            p["visa"] = R.visa_status(passport, p["iso3"])
    return {"from": label, "from_iso3": iso, "max_km": body.max_km,
            "theme": (body.theme or "").strip().lower() or None,
            "places": picks,
            "modes_note": ("Transport is inferred from distance and land borders, "
                           "not from timetables — it answers whether driving or "
                           "rail is possible, not whether there is a service "
                           "on the day.")}


@app.post("/api/getaway/suggest")
async def getaway_suggest(body: GetawayIn, request: Request = None):
    """Destinations named by the scout, then checked against the map.

    The reverse of the first design, which had the data pick the nine nearest
    large towns and the model rank them. That could only ever return the same
    nine — and from New York they were Stamford and Levittown, commuter towns
    nobody takes a weekend in, while Newport and Beacon sat unused because they
    are small. The model knows where people go; the data checks the places are
    real, in range, and tells you how to get there.
    """
    _throttle_ok(request, "getaway_suggest")
    origin, iso, label, _ = _getaway_origin(body)
    if not origin or not iso:
        raise HTTPException(400, "Tell me which city you are starting from.")
    theme_key = (body.theme or "").strip().lower()
    theme = THEMES.get(theme_key, "")

    _spend_ok("getaway_suggest")
    run = await agents.run(
        "getaway_finder",
        f"They live in {label} ({R.facts().get(iso, {}).get('name', iso)}) and will "
        f"travel up to {body.max_km} km.\n"
        + (f"They want a {theme} weekend.\n" if theme else
           "No particular theme — name the places people go from there for a weekend.\n")
        + "\nName eight to ten, each with its region.")

    BUDGET.record("getaway_suggest", (run.usage or {}).get("input_tokens", 0)
                  + (run.usage or {}).get("output_tokens", 0))
    out = _scrub(run.output.model_dump())

    passport = (body.passport or "").strip().upper() or None
    places, dropped = [], []
    for prop in out.get("places", []):
        hit = R.resolve_place(prop["city"], prop.get("region"), origin, body.max_km)
        if not hit:
            dropped.append(f"{prop['city']}, {prop.get('region', '')}".strip(", "))
            continue
        row = {"city": hit["name"], "state": hit["state"] or prop.get("region", ""),
               "iso3": hit["iso3"],
               "country": R.facts().get(hit["iso3"], {}).get("name", hit["iso3"]),
               "km": hit["km"], "population": hit.get("population", 0),
               "lat": hit.get("lat"), "lon": hit.get("lon"),
               "abroad": hit["iso3"] != iso,
               "modes": R.transport_modes(iso, hit["iso3"], hit["_km"]),
               "why": prop["why"], "fit": prop.get("fit", "good")}
        if passport:
            row["visa"] = R.visa_status(passport, hit["iso3"])
        places.append(row)
    places.sort(key=lambda p: p["km"])

    v = _verified(run, {"max_km": body.max_km})
    return {"from": label, "theme": theme_key or None, "max_km": body.max_km,
            "intro": out.get("intro", ""), "places": places,
            # named but unreachable or unfindable, so the page can be honest
            "dropped": dropped,
            "modes_note": ("Transport is inferred from distance and land borders, "
                           "not from timetables."),
            "usage": run.usage, "verified": v["ok"]}


@app.post("/api/getaway/notes")
async def getaway_notes(body: GetawayIn, request: Request = None):
    """One line per place on what it is actually worth going for."""
    _throttle_ok(request, "getaway")
    data = getaway(body)
    if not data["places"]:
        raise HTTPException(400, "Nothing within range to write about.")
    _spend_ok("getaway")
    pool = data.get("candidates") or data["places"]
    slim = [{k: p[k] for k in ("city", "state", "country", "km", "abroad")
             if k in p} | {"visa": (p.get("visa") or {}).get("detail")}
            for p in pool]
    theme = (body.theme or "").strip().lower()
    theme = theme if theme in THEMES else ""
    run = await agents.run(
        "getaway_scout",
        f"Starting from {data['from']}. Shortlist, already measured:\n{slim}\n\n"
        + (f"They want a {THEMES[theme]} weekend. That list is a wide net of "
           f"everything reachable — **choose the six to nine that genuinely "
           f"suit a {THEMES[theme]} weekend and write up only those**. Leave out "
           f"the ones that do not fit rather than padding the list. Set `fit` on "
           f"each one you keep. Say plainly if barely anything near them suits "
           f"it.\n\n" if theme
           else "Write one line for each on what you would go there for.\n\n")
        + "Do not restate distance or transport.")
    BUDGET.record("getaway", (run.usage or {}).get("input_tokens", 0)
                  + (run.usage or {}).get("output_tokens", 0))
    v = _verified(run, pool)
    out = _scrub(run.output.model_dump())
    # return the chosen places with their data, so the page can show cities the
    # first nine never included
    by_city = {p["city"]: p for p in pool}
    chosen = [by_city[n["city"]] for n in out.get("notes", []) if n["city"] in by_city]
    return {"notes": out, "places": chosen or data["places"],
            "from": data["from"], "max_km": data["max_km"], "pool": len(pool),
            "modes_note": data["modes_note"], "usage": run.usage,
            "verified": v["ok"], "unverified_figures": v["unsupported"][:5]}


class Stop(BaseModel):
    iso3: str = Field(max_length=3)
    city: str | None = Field(default=None, max_length=80)


class MultiTripIn(BaseModel):
    stops: list[Stop] = Field(default_factory=list, max_length=10)
    days: int = Field(default=7, ge=1, le=60)
    hours_per_day: int = Field(default=5, ge=1, le=14)
    style: str = Field(default="mixed", max_length=20)
    accommodation: str = Field(default="3-star", max_length=20)
    local_guide: bool = False
    group_size: int = Field(default=2, ge=1, le=40)
    home: str | None = Field(default=None, max_length=3)
    home_city: str | None = Field(default=None, max_length=80)
    # Where this particular trip starts. Someone can live in Riyadh and be
    # setting out from London; distances, flights and the loop home all have
    # to follow the trip, not the profile. Falls back to home when unset.
    origin_iso3: str | None = Field(default=None, max_length=3)
    origin_city: str | None = Field(default=None, max_length=80)
    passport: str | None = Field(default=None, max_length=3)
    optimise: bool = True


def _stop_points(stops: list[Stop]) -> list[dict]:
    """Turn each stop into a point: the chosen city, or the country's capital."""
    out = []
    for st in stops:
        iso = (st.iso3 or "").upper()
        name = R.facts().get(iso, {}).get("name", iso)
        pt = R.city_point(iso, st.city) if st.city else None
        if pt:
            out.append({"iso3": iso, "country": name, "city": pt["city"],
                        "state": pt["state"], "lat": pt["lat"], "lon": pt["lon"],
                        "label": f"{pt['city']}, {name}"})
        else:
            p = R.point(iso)
            if not p:
                continue
            cap = R.facts().get(iso, {}).get("capital") or name
            out.append({"iso3": iso, "country": name, "city": None, "state": "",
                        "lat": p[0], "lon": p[1], "label": name,
                        "note": f"no city chosen — measured from {cap}"})
    return out


@app.post("/api/trip/route")
def trip_route(body: MultiTripIn):
    """Order the stops to keep the travelling down. No model involved."""
    pts = _stop_points(body.stops)
    if not pts:
        raise HTTPException(400, "Add at least one stop.")
    origin, cityinfo = _trip_origin(body)
    if not origin:
        # no home set: start from the first stop and do not loop back
        start = (pts[0]["lat"], pts[0]["lon"])
        r = R.route_points(start, pts[1:], return_home=False)
        order = [pts[0]] + (r["order"] if r else [])
        return {"order": order, "legs": (r or {}).get("legs", []),
                "total_km": (r or {}).get("total_km", 0),
                "saved_km": (r or {}).get("saved_km", 0),
                "from": pts[0]["label"], "home_known": False}
    r = R.route_points(origin, pts, return_home=True)
    # The router labels the start and the return leg "home". That was true
    # when the only possible origin was where you live; now that a trip can
    # start anywhere, the legs are named after the place it actually starts.
    label = _origin_label(body, cityinfo)
    for leg in r.get("legs", []):
        if leg.get("from") == "home":
            leg["from"] = label
        if leg.get("to") == "home":
            leg["to"] = label
    return {**r, "from": label, "home_known": True}


def _legs_for(ordered: list[dict], origin, origin_label: str = "home") -> dict:
    """Leg distances for a fixed order, without rearranging anything."""
    legs, total = [], 0.0
    prev, prev_label = origin, origin_label
    for stop in ordered:
        if prev is not None:
            km = R.haversine(prev, (stop["lat"], stop["lon"]))
            legs.append({"from": prev_label, "to": stop["label"], "km": round(km)})
            total += km
        prev, prev_label = (stop["lat"], stop["lon"]), stop["label"]
    if origin is not None and ordered:
        km = R.haversine(prev, origin)
        legs.append({"from": prev_label, "to": origin_label, "km": round(km)})
        total += km
    return {"order": ordered, "legs": legs, "total_km": round(total),
            "as_listed_km": round(total), "saved_km": 0, "exact": True}


def _alternatives(point, chosen: str, to_iata: str) -> list[dict]:
    """Other airports you could depart from, each with its own direct search.

    The closest airport and the one with a non-stop are often not the same —
    from New Haven the nearest is Bradley, but the transatlantic departures
    are at JFK and Newark, and Boston is two hours up the road. OurAirports
    calls all of them large, so no field in our data picks the hub out, and we
    hold no schedules to settle it. Rather than guess, we name the airports
    within driving range and let each direct-only search answer for itself.
    """
    if point is None:
        return []
    out = []
    for a in R.airports_near(point[0], point[1]):
        if a["iata"] in (chosen, to_iata):
            continue
        out.append({"iata": a["iata"], "name": a["name"], "km": a["km"],
                    "search": R.flight_search(a["iata"], to_iata)})
    # Six, because from New Haven the fifth is Albany and the sixth is Boston,
    # and Boston is the one someone would actually drive to for a non-stop.
    return out[:6]


def _arrivals(point, chosen: str, from_iata: str) -> list[dict]:
    """The same question at the far end: another airport may fly non-stop."""
    if point is None:
        return []
    out = []
    for a in R.airports_near(point[0], point[1], radius_km=200, limit=5):
        if a["iata"] in (chosen, from_iata):
            continue
        out.append({"iata": a["iata"], "name": a["name"], "km": a["km"],
                    "search": R.flight_search(from_iata, a["iata"])})
    return out[:3]


def _logistics(origin, origin_label, ordered, accommodation, return_home=True,
               local_guide=False):
    """Flights and stays for the trip, from our own data plus live searches.

    Everything in here is either measured (airport codes and distances come
    from the airports dataset and the haversine) or a link to somebody who
    holds the live numbers. There are no prices, because we do not have any
    and a plausible invented fare is worse than no fare at all.

    A leg is only called a flight when the two nearest big airports differ and
    the distance makes flying the realistic choice; two stops sharing an
    airport, or an hour apart, are ground travel and are reported as such.

    "Nearest airport" means the nearest *large* one. OurAirports classifies
    these as large_airport with scheduled service, and they are where non-stop
    routes concentrate — a regional field 20 km closer will route you through
    a hub anyway. We hold no schedules, so we never claim a direct flight
    exists; the searches are filtered to non-stop so the site answers that.
    """
    FLY_KM = 400                      # below this, flying is rarely the answer
    legs, prev, prev_label = [], origin, origin_label
    for stop in ordered:
        here = (stop["lat"], stop["lon"])
        if prev is not None:
            km = round(R.haversine(prev, here))
            a = R.nearest_airport(*prev, big_only=True)
            b = R.nearest_airport(*here, big_only=True)
            leg = {"from": prev_label, "to": stop["label"], "km": km}
            if a and b and a["iata"] != b["iata"] and km >= FLY_KM:
                leg |= {"mode": "fly", "from_iata": a["iata"], "from_airport": a["name"],
                        "to_iata": b["iata"], "to_airport": b["name"],
                        "search": R.flight_search(a["iata"], b["iata"]),
                        "from_options": _alternatives(prev, a["iata"], b["iata"]),
                        "to_options": _arrivals(here, b["iata"], a["iata"])}
            else:
                leg |= {"mode": "ground",
                        "note": "same airport" if a and b and a["iata"] == b["iata"]
                                else "short enough to go overland"}
            legs.append(leg)
        prev, prev_label = here, stop["label"]
    if return_home and origin is not None and ordered:
        km = round(R.haversine(prev, origin))
        a = R.nearest_airport(*prev, big_only=True)
        b = R.nearest_airport(*origin, big_only=True)
        leg = {"from": prev_label, "to": origin_label, "km": km, "home": True}
        if a and b and a["iata"] != b["iata"] and km >= FLY_KM:
            leg |= {"mode": "fly", "from_iata": a["iata"], "from_airport": a["name"],
                    "to_iata": b["iata"], "to_airport": b["name"],
                    "search": R.flight_search(a["iata"], b["iata"]),
                    "from_options": _alternatives(prev, a["iata"], b["iata"]),
                    "to_options": _arrivals(origin, b["iata"], a["iata"])}
        else:
            leg |= {"mode": "ground", "note": "short enough to go overland"}
        legs.append(leg)

    stays = []
    for stop in ordered:
        air = R.nearest_airport(stop["lat"], stop["lon"], big_only=True)
        stays.append({
            "city": stop["label"], "country": stop.get("country", ""),
            "airport": (f"{air['iata']} — {air['name']}, {air['km']} km away"
                        if air else None),
            "search": R.stay_search(stop.get("city") or stop["label"],
                                    stop.get("country", "")),
            "guides": R.guide_links(stop.get("city") or stop["label"],
                                    stop.get("country", ""), stop.get("iso3", "")),
            "tours": (R.tour_search(stop.get("city") or stop["label"],
                                    stop.get("country", "")) if local_guide else None),
        })
    flights = [l for l in legs if l["mode"] == "fly"]
    return {"legs": legs, "stays": stays, "accommodation": accommodation,
            "n_flights": len(flights),
            "airport_note": "Closest airports first, then the others within "
                            "driving range. Every search is set to direct flights "
                            "only.",
            "disclaimer": "Airports and distances are measured from our own data. "
                          "We hold no fares and no room rates — every link opens "
                          "a live search on a site that does."}


@app.post("/api/trip/plan")
async def trip_plan(body: MultiTripIn, request: Request = None):
    """A multi-stop itinerary, with the travel between stops costed in days."""
    _throttle_ok(request, "trip_plan")
    pts = _stop_points(body.stops)
    if not pts:
        raise HTTPException(400, "Add at least one stop.")
    # The distances are wanted either way; `optimise` only decides whether the
    # order is rearranged. Skipping the route when it is off meant a trip
    # planned in the user's own order showed no leg distances at all.
    solved = trip_route(body)
    ordered = solved["order"] if body.optimise else pts
    origin, cityinfo = _trip_origin(body)
    route = (solved if body.optimise
             else _legs_for(ordered, origin, _origin_label(body, cityinfo)))

    passport = (body.passport or "").strip().upper() or None
    visas = {}
    if passport:
        for p in ordered:
            v = R.visa_status(passport, p["iso3"])
            if v and v["advance"]:
                visas[p["label"]] = v["detail"]

    grp = D.group_band(body.group_size)
    legs = (route or {}).get("legs", [])
    hops = "; ".join(f"{l['from']} to {l['to']} {l['km']} km" for l in legs) or "single stop"
    stats = []
    for p in ordered:
        c = D.resolve(p["country"])
        if c:
            stats.append(D.country_stats(c.name))

    _spend_ok("trip_plan")
    run = await agents.run(
        "trip_architect",
        f"Stops in order: {', '.join(p['label'] for p in ordered)}.\n"
        f"Legs: {hops}.\n"
        f"Context on the countries: {stats}\n\n"
        f"Party of {grp['size']} — a {grp['band']} group. {grp['logistics']}.\n"
        f"{body.days} days total, {body.hours_per_day} hours of sightseeing a day, "
        f"style: {body.style}, staying in {body.accommodation}, "
        f"local guide wanted: {body.local_guide}.\n"
        + (f"Visas needed on their passport: {visas}. Mention it once.\n" if visas else "")
        + "\nBuild the itinerary across every stop.")
    BUDGET.record("trip_plan", (run.usage or {}).get("input_tokens", 0)
                  + (run.usage or {}).get("output_tokens", 0))
    v = _verified(run, {"stats": stats, "legs": legs})
    return {"itinerary": _scrub(run.output.model_dump()), "route": route,
            "logistics": _logistics(origin, _origin_label(body, cityinfo),
                                    ordered, body.accommodation,
                                    return_home=origin is not None,
                                    local_guide=body.local_guide),
            "stops": ordered, "group": grp, "visas": visas, "usage": run.usage,
            "verified": v["ok"], "unverified_figures": v["unsupported"][:5]}


class WeekendPlanIn(BaseModel):
    city: str = Field(max_length=80)
    iso3: str = Field(max_length=3)
    state: str | None = Field(default=None, max_length=80)
    km: int = Field(default=0, ge=0, le=5000)
    mode: str | None = Field(default=None, max_length=16)
    theme: str | None = Field(default=None, max_length=24)
    from_label: str | None = Field(default=None, max_length=120)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)


@app.post("/api/getaway/plan")
async def weekend_plan(body: WeekendPlanIn, request: Request = None):
    """Two days in one city, shaped by the journey and the theme."""
    _throttle_ok(request, "weekend_plan")
    place = R.city_point(body.iso3, body.city)
    if not place and body.lat is not None and body.lon is not None:
        place = {"city": body.city, "state": body.state or "",
                 "lat": body.lat, "lon": body.lon}
    if not place:
        raise HTTPException(404, f"No city {body.city!r} in {body.iso3}.")
    country = R.facts().get(body.iso3, {}).get("name", body.iso3)
    theme = (body.theme or "").strip().lower()
    theme = THEMES.get(theme, "")
    mode = (body.mode or "").strip().lower()
    leg = R.journey_time(mode, body.km) if mode and body.km else None

    by_leg = (f", travelling by {mode} — about {leg['range']} each way"
              if leg else "")

    _spend_ok("weekend_plan")
    run = await agents.run(
        "weekend_planner",
        f"City: {place['city']}, {place['state']}, {country}.\n"
        + (f"From {body.from_label}, {body.km} km away{by_leg}.\n"
           if body.km else "")
        + (f"They want a {theme} weekend.\n" if theme else "")
        + "\nBuild exactly two days.")
    BUDGET.record("weekend_plan", (run.usage or {}).get("input_tokens", 0)
                  + (run.usage or {}).get("output_tokens", 0))
    v = _verified(run, {"km": body.km})
    return {"itinerary": _scrub(run.output.model_dump()),
            "city": place["city"], "state": place["state"], "country": country,
            "leg": leg, "theme": theme or None, "usage": run.usage,
            "verified": v["ok"], "unverified_figures": v["unsupported"][:5]}


@app.post("/api/route")
def plan_route(labels: Labels):
    """Shortest order to visit the want-list and come home. Pure arithmetic."""
    home = (labels.home or "").strip().upper()
    if not R.point(home):
        raise HTTPException(400, "Set your home country first.")
    stops = D.iso3_many(labels.want)
    origin, cityinfo = _origin(home, labels.home_city)
    r = R.route(home, stops, origin=origin)
    if not r:
        raise HTTPException(400, "Pick at least one country to route.")
    named = lambda i: D.name_of_iso3(i) or i
    r["order_names"] = [named(i) for i in r["order"]]
    r["home_name"] = (cityinfo["city"] if cityinfo else named(home))
    for leg in r["legs"]:
        leg["from_name"], leg["to_name"] = named(leg["from"]), named(leg["to"])
    return r


@app.post("/api/shortlist")
def shortlist(labels: Labels):
    """The want-list, ranked, with no model involved.

    Same two-tier rule the rest of the app follows: the figures are arithmetic
    and arrive instantly, so the page shows them the moment you open it. The
    model is only needed for the prose about *why*, and that stays on a button.
    """
    visited = labels.visited + labels.lived
    out = D.recommend(visited, labels.want, limit=12, want_only=True)
    # the copy on the page describes how rare these are, so it needs the
    # distribution it is describing them against
    out["rarity_quartiles"] = D.benchmarks()["rarity_quartiles"]

    home = (labels.home or "").strip().upper() or None
    passport = (labels.passport or "").strip().upper() or None
    for p in out["recommendations"]:
        iso = D.iso3_of(p["country"])
        if not iso:
            continue
        p["iso3"] = iso
        if passport:
            p["visa"] = R.visa_status(passport, iso)
        if home:
            o, _ = _origin(home, labels.home_city)
            p["km"] = (round(R.haversine(o, R.point(iso)), 1)
                       if o and R.point(iso) else None)
            p["price"] = R.price_vs(home, iso)
        # weather, never crowds — the label says so on the card
        bm = R.best_months(iso, n=3)
        if bm:
            p["best_months"] = {"months": [m["name"] for m in bm["best"]],
                                "caveat": bm["caveat"], "source": bm["source"]}
    return out


@app.post("/api/recommend")
async def recommend(labels: Labels, region: str | None = None, request: Request = None):
    """Ranks the user's own want-list, rather than the whole world.

    Someone who has already said where they want to go does not need a machine
    telling them to go somewhere else. The job here is to order their list by
    what it would do to their map, and to be honest about the ones that are
    rare for bad reasons.
    """
    visited = labels.visited + labels.lived
    picks = D.recommend(visited, labels.want, region, limit=8, want_only=True)

    # Nothing to rank and nothing to ask a model about — answer in Python and
    # spend no tokens saying "your list is empty".
    if not picks["recommendations"]:
        visited_from_want = picks["already_visited_from_want"]
        return {"recommendations": {
                    "intro": ("You have already been to everything on your want-list — "
                              f"{', '.join(visited_from_want)}. Mark somewhere new as "
                              "'want to go' and this page will rank it."
                              if visited_from_want else
                              "Nothing is on your want-list yet. Open the map, mark a few "
                              "countries as 'want to go', and this page will rank them by "
                              "what each would do to your profile."),
                    "picks": []},
                "candidates": picks, "usage": None, "empty": True}

    _throttle_ok(request, "recommend")
    _spend_ok("recommend")
    run = await agents.run(
        "recommender",
        f"The user's own want-list, already ranked by rarity:\n{picks}\n\n"
        f"Counts you may quote, and no others: they have visited exactly "
        f"{len(set(visited))} countries, and exactly {len(picks['recommendations'])} "
        f"are on the want-list below. These are the places THEY chose — rank and "
        f"explain these, and do not propose anywhere else. Cover every entry if "
        f"there are five or fewer.")
    BUDGET.record("recommend", (run.usage or {}).get("input_tokens", 0)
                  + (run.usage or {}).get("output_tokens", 0))
    v = _verified(run, picks)
    return {"recommendations": _scrub(run.output.model_dump()),
            "candidates": picks, "usage": run.usage,
            "verified": v["ok"], "unverified_figures": v["unsupported"][:5]}


@app.post("/api/itinerary")
async def itinerary(req: ItineraryRequest, request: Request = None):
    c = D.resolve(req.country)
    if not c:
        raise HTTPException(404, f"No country matching {req.country!r}.")
    grp = D.group_band(req.group_size)
    _throttle_ok(request, "itinerary")
    _spend_ok("itinerary")
    run = await agents.run(
        "trip_architect",
        f"Country: {c.name}. Context: {D.country_stats(c.name)}\n\n"
        f"Party of {grp['size']} — a {grp['band']} group. {grp['logistics']}.\n"
        f"{req.days} days, {req.hours_per_day} hours of sightseeing a day, "
        f"style: {req.style}, staying in {req.accommodation}, "
        f"local guide wanted: {req.local_guide}.\n\n"
        f"Plan for exactly {grp['size']} people. Every day must be something "
        f"{grp['size']} people can actually do together.")
    BUDGET.record("itinerary", (run.usage or {}).get("input_tokens", 0)
                  + (run.usage or {}).get("output_tokens", 0))
    v = _verified(run, D.country_stats(c.name))
    return {"itinerary": _scrub(run.output.model_dump()), "group": grp, "usage": run.usage,
            "verified": v["ok"], "unverified_figures": v["unsupported"][:5]}


@app.post("/api/chat")
async def chat(req: ChatRequest, request: Request = None):
    session = req.session_id or uuid.uuid4().hex[:12]

    # 1. Screened before the model sees it. A refused message costs nothing,
    #    so this defends the token budget as well as the instructions.
    _throttle_ok(request, "chat")
    scan = guard.screen_input(req.message)
    if scan["blocked"]:
        guard.record("injection_blocked", session=session,
                     category=scan["category"], matched=scan["matched"])
        return {"reply": scan["reply"], "session_id": session, "usage": None,
                "blocked": True, "category": scan["category"]}

    _spend_ok(session)
    run = await agents.run("consultant", req.message, history=CHATS[session])
    CHATS[session] = agents.trim_history(run.messages)
    BUDGET.record(session, (run.usage or {}).get("input_tokens", 0)
                  + (run.usage or {}).get("output_tokens", 0))

    # 2. Scope. The model judges whether the question was about travel, because
    # that needs the meaning of the sentence and the thread it sits in. What it
    # does not get to choose is the answer when it says no: the refusal text is
    # ours, so a user who argues with it still gets the same sentence.
    if not run.output.on_topic:
        guard.record("off_topic", session=session,
                     asked=guard.redact_pii(req.message)[:80])
        return {"reply": guard.OFF_TOPIC, "session_id": session,
                "usage": run.usage, "blocked": True, "category": "off-topic"}

    # The model occasionally returns on_topic=true with an empty reply — it did
    # it every time for "what should I pack for Iceland in winter". An empty
    # bubble looks like a crash, so it is treated as one failed attempt and
    # asked again; if it comes back empty twice we say so rather than showing
    # nothing at all.
    if not (run.output.reply or "").strip():
        guard.record("empty_reply", session=session,
                     asked=guard.redact_pii(req.message)[:80])
        _spend_ok(session)
        run = await agents.run("consultant", req.message, history=CHATS[session])
        CHATS[session] = agents.trim_history(run.messages)
        BUDGET.record(session, (run.usage or {}).get("input_tokens", 0)
                      + (run.usage or {}).get("output_tokens", 0))
        if not (run.output.reply or "").strip():
            return {"reply": "I lost that one on the way — ask me again and I "
                             "will answer it.", "session_id": session,
                    "usage": run.usage, "blocked": False, "empty": True}

    # 3. Nothing secret leaves the process, whatever the model decided to write.
    out = guard.screen_output(run.output.reply)
    if not out["clean"]:
        guard.record("output_redacted", session=session, leaked=out["leaked"])

    # 4. Every figure checked against what the tools returned.
    v = _verified(run)
    return {"reply": out["text"], "session_id": session, "usage": run.usage,
            "blocked": False,
            "leaked": out["leaked"], "verified": v["ok"],
            "unverified_figures": v["unsupported"][:5],
            "turns": sum(1 for msg in CHATS[session]
                         for part in getattr(msg, "parts", [])
                         if type(part).__name__ == "UserPromptPart")}


# --------------------------------------------------------------- accounts
# Signing up is optional. Everything above works for a guest; an account only
# decides where the map is kept — this browser, or the server.

def _token(authorization: str | None) -> str | None:
    """Pull the bearer token out of the Authorization header, if there is one."""
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip() else None


def _require(authorization: str | None) -> str:
    email = auth.whoami(_token(authorization))
    if not email:
        raise HTTPException(401, "Sign in first.")
    return email


@app.post("/api/auth/register")
def register(body: Signup):
    try:
        return auth.register(body.email, body.password, body.confirm,
                             body.carry.model_dump() if body.carry else None)
    except auth.AuthError as e:
        raise HTTPException(400, str(e))


@app.post("/api/auth/login")
def login(body: Credentials):
    try:
        return auth.login(body.email, body.password)
    except auth.AuthError as e:
        # 429 when the account is temporarily locked, 401 for a bad credential
        raise HTTPException(429 if "Too many" in str(e) else 401, str(e))


@app.post("/api/auth/logout")
def logout(authorization: str | None = Header(default=None)):
    auth.logout(_token(authorization))
    return {"ok": True}


@app.get("/api/auth/me")
def me(authorization: str | None = Header(default=None)):
    email = auth.whoami(_token(authorization))
    if not email:
        return {"email": None, "map": None, "profile": None}
    return {"email": email, "map": auth.get_map(email),
            "profile": auth.get_profile(email)}


@app.post("/api/me/profile")
def set_profile(body: ProfileIn, authorization: str | None = Header(default=None)):
    """Home country and passport, for signed-in users. Guests keep theirs locally."""
    email = _require(authorization)
    try:
        return {"profile": auth.save_profile(email, body.home, body.passport,
                                             body.home_city)}
    except auth.AuthError as e:
        raise HTTPException(400, str(e))


class TodoItem(BaseModel):
    text: str = Field(max_length=200)
    done: bool = False
    where: str = Field(default="", max_length=80)


class TodoIn(BaseModel):
    items: list[TodoItem] = Field(default_factory=list, max_length=120)


@app.get("/api/me/todo")
def get_todo(authorization: str | None = Header(default=None)):
    """The trip checklist. Signed-in only; guests keep theirs in the browser."""
    return {"items": auth.get_todo(_require(authorization))}


@app.post("/api/me/todo")
def put_todo(body: TodoIn, authorization: str | None = Header(default=None)):
    email = _require(authorization)
    try:
        return {"items": auth.save_todo(email,
                                        [i.model_dump() for i in body.items])}
    except auth.AuthError as e:
        raise HTTPException(400, str(e))


@app.post("/api/map")
def put_map(labels: Labels, authorization: str | None = Header(default=None)):
    """Written on every label change, so signing out can never lose a pin."""
    email = _require(authorization)
    try:
        return {"map": auth.save_map(email, labels.model_dump())}
    except auth.AuthError as e:
        raise HTTPException(400, str(e))


# The front end is plain static files — no build step, so a fresh clone runs
# with one command.
class NoCacheStatic(StaticFiles):
    """Serve the front end with `no-store`.

    A browser holding yesterday's app.js against today's index.html produces
    the worst possible bug report: half the page works. It cost a real "the
    chatbot is broken" that was only ever a cached script. The files are a few
    hundred KB served from localhost, so there is nothing to gain by caching
    them and a whole class of phantom bugs to lose.
    """

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
        return resp


app.mount("/", NoCacheStatic(directory=WEB, html=True), name="web")
