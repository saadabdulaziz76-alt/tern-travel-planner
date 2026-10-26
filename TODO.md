# Open items — TNAT

Deadline: **Mon 26 Oct 2026, 6:00 PM**

## Submission state — 26 Oct, 16:35

| Deliverable | State |
|---|---|
| Application | **done** — 9 pages, 8 agents, 493 tests passing |
| `report.html` | **done** — 8 required sections, ~10 pages |
| `slides.html` | **done** — 10 slides, reveal.js from CDN |
| `README.md` | **done** — ten-minute rule verified, app imports in 0.9 s |
| `.env.example` | **done** — placeholders only, real `.env` gitignored |
| Demo video | **done** — `demo/tern-walkthrough.mp4`, 5 min 58 s, narrated |
| External user test | **NOT DONE** — see below |

### The one gap, stated plainly

No external user test was conducted. It was identified as a risk on 14 October,
flagged repeatedly as the only item costing calendar rather than working time,
and never closed. It gates 5 points outright and caps the Impact section. The
report says so in its own words rather than implying otherwise.

### Settled since the last entry

- **PRICES** — decided: ship with no prices at all. The app names what it
  measures (airports, distances, visa rules) and hands live pricing to the sites
  that hold it, with the search pre-filled. No fare or rate appears anywhere, and
  a test asserts no generated link carries a currency parameter.
- **Local guides** — kept, reframed. The label no longer says "find me a local
  guide", which was a promise the app does not keep; it says "plan around a local
  guide" and links to five places to book one.
- **Safety screenshot loose end** — closed; the refusal card is visible in the
  walkthrough video.

## Parked, must come back to

- [ ] **A REAL USER for impact testing.** Nobody identified yet. Gates 5 points
      outright and caps the Impact section at 50% without it. This is the only
      item that costs *calendar* time rather than work time — a build can happen
      in a weekend, a user test cannot. **Line someone up this week.**

- [ ] **Verdict threshold** — 40% flow coverage = "tourist" is a first guess.
      Tune once there are real profiles to look at.

## Still to build

- [x] **Safety defences — DONE 15 Oct**, then hardened the same day. All three
      risks the brief names, each with a test and a live transcript. Evidence:
      `docs/safety_evidence.md` (regenerate with `python safety_demo.py`),
      `backend/test_guard.py` (41 tests), `GET /api/safety`.
      **10/10 attacks blocked including 4 obfuscated, 0 false positives.**
      Two real vulnerabilities found and closed in the second pass: XSS from
      model output into `innerHTML` (could have stolen the session token), and
      indirect injection through unvalidated country labels.
      *Loose end:* no UI screenshot of the refusal card — the Browser pane was
      hidden both times. One minute's work when the pane is open.
- [ ] **`report.html` (10–15 pages)** — the main remaining task. Required
      sections, in order: Title+links · Motivation · What is new here · The
      agents · Tokenomics · Safety · Impact · Limits+next steps.
      Nearly all the raw material is already written up in `DECISIONS.md`,
      which has every design call, every bug found, and the reasoning.
- [ ] `slides.html` (≤10 slides, reveal.js from CDN)
- [ ] GitHub repo: `.env.example`, README, the 10-minute rule
- [ ] Demo video (optional)

## Where things stood at the end of 15 Oct

Six agents, six pages, **330 tests passing** (133 data · 104 reference ·
41 auth · 41 safety · 11 agents).

Built today, in order: the exact-figures rewrite (no invented percentile) ·
accounts with the map saved per user · all 255 countries on the map with the UK
split into its four nations · Hong Kong and Macao separated from China · the
chat history crash fixed · Where Next ranking only the want-list · group sizes
on trips · the countries/territories/places vocabulary · ten new features on a
reference-data layer (visas, distance, carbon, languages, routing, blind spots,
year timeline, prices, climate) · home as a city rather than a country ·
the safety layer and its hardening · the Getaways tab with themes, transport
detail and two-day plans.

Running the app: `cd backend && ./.venv/bin/uvicorn main:app --port 8200`,
then open <http://localhost:8200>. One process serves the page and the API.
Test accounts `test1` / `test2`, password `12345678`.

Rebuilding reference data (rarely needed, it is committed):
`python build_reference_data.py`, then `--cities`, then `--climate`.

## Built so far (14 Oct)

- `backend/tnat_data.py` — the data layer, 7 tools, **46 tests passing**
  (`backend/test_tnat_data.py` — **133 passing**, plus 41 in
  `backend/test_auth.py`, 11 in `backend/test_agents.py`, 70 in
  `backend/test_reference.py` and 41 in `backend/test_guard.py`
  — **402 total**). Two real bugs caught: Japan was being scored
  off its 2020 pandemic figure (0.3% instead of 2.6%), and the recommender was
  suggesting Tuvalu and Kiribati until a 250k-arrivals floor was added.
- `backend/agents.py` + `backend/prompts/` — four agents, shared toolset,
  structured outputs, house rules forbidding any number not returned by a tool.
- `backend/usage_log.py` — append-only JSONL token log. Already capturing
  cached-input tokens, which is what the tokenomics section needs.
- `backend/main.py` — 10 routes, deliberately two-tier (see below).
- `backend/config.py` — gpt-6-luna, finds `.env` here or in any parent.

### Measured, not guessed

| | |
|---|---|
| Pure-Python profile | **0.05 ms** (0.002 s through HTTP) |
| Profile Analyst | 50–114 s |
| Recommender | 48 s |
| Consultant, cold / cached | 7.2 s / **0.3 s** |
| Prefetch saving | 5,492 → 3,700 input tokens, 6 → 2 tool calls |
| Cached input per analyst run | 2,399–3,150 tokens |

**Architecture follows from this:** statistics are pure Python and return
instantly; agents only write prose. The map fills in its numbers before the
commentary arrives. Making someone wait a minute to be told they are a tourist
would be a worse product and no more accurate.

- Accounts: optional sign-up, guest map in localStorage, account map on the
  server, guest pins carried into a new account. test1 / test2, password
  12345678 (minimum 8 characters). `data/accounts.json` is gitignored and
  re-seeds on startup.

## Settled

- Arrivals source: OWID / UN Tourism. World Bank rejected (see DECISIONS.md).
- Denominator fixed at 2019 (174 countries, 1,279M arrivals).
- Percentile: **no percentile is shown at all.** All four tiles are counted
  figures (countries · of 195 · share of world travel flow · rarest stop). The
  Pew band appears as a sentence with its ceiling and sample stated. The
  interpolated "top X%" was deleted on 14 Oct and a test keeps it deleted.
  See `data/PERCENTILE.md`.
- Eight agents: Profile Analyst · Anti-Tourist Recommender · Trip Architect ·
  Travelling Consultant · Getaway Finder · Getaway Scout · Weekend Planner ·
  Park Guide. See SPEC.md.
- Planning stays, but downstream of the recommendation — never standalone.
