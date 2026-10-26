# Traveler Not a Tourist (TNAT) — spec

A travel site that answers its own question: are you a traveler, or a tourist?

Built on 30 years of UN Tourism arrivals data (206 countries, 1995–2024). The
site measures how much of the world's *travel flow* you have covered, how
off-path your countries are, and whether you got there before everyone else —
then recommends where to go to stop being a tourist, and plans that trip.

## Why this is not a trip planner

The rubric caps "trip planner" at Tier 1. TNAT is not one. The planning only
exists downstream of a judgement the planner cannot make: *you are a tourist,
here is what would change that.* Planning is the last step, not the product.

## The three things a user does

1. **Label the map.** Click countries: visited · lived · want. That is the input.
2. **Get the verdict.** Flow coverage, rarity, traveler-or-tourist, were-you-early.
3. **Get told where to go next**, and then plan that specific trip.

## The metrics (all computed, none invented)

| Metric | Definition | Example |
|---|---|---|
| **Flow coverage** | Sum of your countries' share of 2019 world arrivals | 12 classic countries = **46.5%** |
| **Rarity score** | Mean of −log₁₀(share) across your countries | classic trip −0.53 · off-path **+1.11** |
| **Verdict** | Tourist if flow > 40%, else Traveler | threshold to be tuned on real profiles |
| **Were you early** | Arrivals in your visit year vs now | Georgia 2.8M (2012) → 7M+ |
| **Peer band** | Pew 2023: 21% never left · 13% have 10+ | cite the band, never a fake decimal |
| **What's left** | Share of world flow in countries you have not seen | 94 countries → remaining 80 = **2.3%** |

Denominator fixed at **2019** (174 countries, 1,279M arrivals). See
`data/LIMITATIONS.md` for why, and `DECISIONS.md` for the rules this imposes.

## Agents

Four, each with real tools over the real dataset.

```
                       ┌──────────────────┐
   map input  ────────▶│  Profile Analyst │  reads the dataset, no LLM guessing
                       └────────┬─────────┘
                                │ profile: flow %, rarity, verdict, early finds
              ┌─────────────────┼──────────────────┐
              ▼                 ▼                  ▼
   ┌────────────────────┐  ┌──────────┐  ┌──────────────────────┐
   │ Anti-Tourist       │  │ Travel-  │  │  Trip Architect      │
   │ Recommender        │  │ ling     │  │  (runs on a chosen   │
   │ where to go next   │  │ Consul-  │  │   country only)      │
   └─────────┬──────────┘  │ tant     │  └──────────┬───────────┘
             │             │ chatbot  │             │
             └────────────▶└──────────┘◀────────────┘
                     all four share the same tools
```

**1 · Profile Analyst.** Turns map labels into the verdict. Deterministic maths
in tools; the agent writes the prose. Never states a number a tool did not return.

**2 · Anti-Tourist Recommender.** Ranks unvisited countries by how much they
would move the user's rarity score, filtered by region, budget band and the
user's own "want" list. Explains *why* each one.

**3 · Trip Architect.** Only runs once a country is chosen. Produces an
itinerary from the user's inputs: hours per day for sightseeing, and
cultural / relaxing / mixed. Accommodation tier (5★ · 4★ · 3★ · hostel) and
whether they want a local guide shape the plan. Honest labelling: suggestions
from model knowledge, **not** live inventory or live prices.

**4 · Travelling Consultant.** The chatbot. Open travel questions, and it can
call the same data tools — so "is Georgia getting more touristy?" returns a real
number, not a vibe.

## Tools (all backed by the CSV, no invented data)

| Tool | Returns |
|---|---|
| `country_stats(country, year)` | arrivals, share of world flow, rank |
| `profile_score(visited[])` | flow coverage, rarity score, verdict |
| `trajectory(country, from, to)` | arrivals over time, growth, were-you-early |
| `recommend(profile, filters)` | unvisited countries ranked by score impact |
| `peer_band(n_countries)` | the Pew band, with its ceiling caveat |
| `whats_left(visited[])` | share of world flow not yet covered |
| `least_visited(n)` / `most_visited(n)` | ends of the distribution |

## Open questions

- **Prices.** No free flight/hotel price API is secured. Until one is, the
  Architect gives **no prices** — budget is a constraint on recommendations, not
  a quoted total. Revisit only if a real API lands.
- **Local guides.** Needs real named sites, or it is cut.
- **Verdict threshold.** 40% flow is a first guess, to be tuned.
- **A real user for impact testing.** Still unidentified. This gates 5 points
  directly and caps the Impact section at 50% without it.

## Build order (12 days, solo)

1. Data layer + the tools, tested against the CSV
2. Map + labelling, verdict panel  ← the core product, must land first
3. Profile Analyst + Anti-Tourist Recommender
4. Travelling Consultant
5. Trip Architect
6. Safety defences + token logging (instrument from day one, not retrofitted)
7. report.html + slides.html
