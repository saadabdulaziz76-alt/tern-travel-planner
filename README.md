# Tern — *traveler, not a tourist*

A travel planning desk that keeps the map of where you have been, works out what
it adds up to against real arrivals data, and builds the next trip around it —
distances, visas, airports and stays in one place.

Built for **AI Foundations** (Yale SOM, 2026). Eight agents, 493 passing tests,
and a standing rule that **no number appears unless it traces to a published
source**.

---

## Run it in under ten minutes

```bash
git clone <this-repo> && cd "Final Project"
python3 -m venv backend/.venv
./backend/.venv/bin/pip install -r backend/requirements.txt
cp .env.example .env          # then paste in one API key
cd backend && ./.venv/bin/uvicorn main:app --port 8200
```

Open **<http://localhost:8200>**.

One process serves the page and the API — there is no second terminal, no build
step and no database. Reference data is committed, so the app starts with
everything it needs.

**Test accounts:** `test1` / `test2`, password `12345678`. Seeded on startup, so
a fresh clone has working logins with nothing secret in git.

---

## What is in it

| Page | What it does |
|---|---|
| **Map** | Paint 249 countries and territories as visited, lived in, or want to go |
| **Insights** | What your map adds up to — coverage, concentration, carbon and offsets |
| **Where Next** | Your own want-list ranked by how much each would move your profile |
| **Getaways** | Real weekend destinations by theme, within range of home |
| **National Parks** | Every national park in the US and Canada, with how to get there |
| **Heritage** | 1,511 UNESCO World Heritage sites, by country |
| **Plan** | Multi-stop trips with distances, visas, airports, stays and a checklist |
| **Test Yourself** | A geography quiz — capitals, flags, land borders |
| **Consultant** | A travel adviser that answers travel questions and nothing else |

## The eight agents

`profile_analyst` · `recommender` · `trip_architect` · `consultant` ·
`getaway_finder` · `getaway_scout` · `weekend_planner` · `park_guide`

All use `gpt-6-luna` through Portkey, return Pydantic models rather than free
text, and are forbidden from stating any figure a tool did not return — a rule
enforced by re-checking every number in the generated prose against the tool
results for that run.

## Architecture in one line

**Statistics are pure Python and instant; agents only write prose.** Computing a
travel profile takes 0.05 ms in Python and 30 seconds via an agent, for the same
answer. The map fills in its numbers before the commentary arrives.

---

## What it deliberately does not do

- **No prices, fares or room rates.** Those need a paid API. The app names the
  airports and hands off to sites that hold live data, with the search
  pre-filled.
- **No flight schedules.** It cannot tell you a non-stop exists — it names the
  airports where one is plausible and filters the search to direct flights.
- **No invented statistics.** There is no "top 5% of travellers" badge, because
  that figure could not be justified.

## Testing

```bash
cd backend
for t in test_*.py; do ./.venv/bin/python "$t"; done
```

493 tests across six suites: data, reference, auth, safety, agents and quiz.

## Safety

Three risks, each with a defence, tests and live transcripts.

- **Prompt injection** — 14 patterns checked against raw, normalised,
  whitespace-squashed and base64-decoded text, blocked *before* the model runs.
  10/10 attacks blocked including 4 obfuscated, 0 false positives.
- **Model output in the DOM** — every generated string is escaped; a real XSS
  was found and closed during review.
- **Runaway cost** — daily, per-session and per-minute ceilings.

Evidence: `docs/safety_evidence.md` (regenerate with `python safety_demo.py`),
`backend/test_guard.py`, and the live state at `GET /api/safety`.

## Project files

| File | What |
|---|---|
| `report.html` | The final report |
| `slides.html` | Ten slides (reveal.js from CDN) |
| `demo/tern-walkthrough.mp4` | Narrated walkthrough, 5 min 58 s |
| `DECISIONS.md` | Every design decision and every bug, 1,589 lines |
| `TODO.md` | Outstanding items, honestly listed |
| `SPEC.md` | The original specification |

## Data sources

OWID / UN Tourism (arrivals) · ISO 3166 and REST Countries · GeoNames-derived
city gazetteer · OurAirports · Wikidata and Wikimedia Commons (parks, heritage,
photographs) · Open-Meteo (climate) · EPA Greenhouse Gas Equivalencies ·
UK DEFRA/DESNZ 2023 conversion factors.

Rebuilding reference data is rarely needed — it is committed — but:

```bash
cd backend && ./.venv/bin/python build_reference_data.py          # core
./.venv/bin/python build_reference_data.py --cities --climate     # then these
./.venv/bin/python build_reference_data.py --parks --airports --unesco
```
