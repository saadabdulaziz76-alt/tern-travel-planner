# Travel statistics — sources gathered 14 Oct 2026

Everything here is a **real, citable source**. The final report needs named
sources with numbers, so nothing below is estimated or filled in.

## 1 · UN Tourism (UNWTO) World Tourism Barometer — the headline authority

The UN specialised agency for tourism. Publishes global and regional arrivals
three times a year. This is the number everyone else cites.

| Measure | Figure | Period |
|---|---|---|
| Global international arrivals | **1.52 billion** | 2025, +4% on 2024 |
| Global international arrivals | **~1.5 billion** | 2024, back to pre-pandemic |
| Global international arrivals | ~1.4 billion | 2023 |
| Arrivals, first half | ~690 million (+5%, +33m on 2024) | Jan–Jun 2025 |
| Export revenue from tourism | **USD 2 trillion** | 2024, record |

Regional, Jan–Jun 2025 vs 2024: Africa **+12%** (North Africa +14%, Sub-Saharan
+11%) · Europe **+4%** (~340m arrivals, +7% on 2019) · Americas **+3%** (South
America +14%, Central America +2%, North America +0%, Caribbean +0%) ·
Asia-Pacific **+9%** but still 11% below 2019.

Fastest-growing destinations 2025: Brazil +37%, Egypt +20%, Morocco +14%,
Seychelles +13%. Jan–Sep 2025: Brazil +45%, Vietnam +21%, Egypt +21%,
Ethiopia +18%, Japan +18%, South Africa +17%, Sri Lanka +16%, Mongolia +16%.

Fastest-growing 2024 vs 2019: Qatar +137%, El Salvador +81%, Albania +80%,
Saudi Arabia +69%, Ethiopia +40%, Colombia +37%, Morocco +35%, Andorra +35%,
Guatemala +33%, Malta +29%, Serbia +29%.

- Barometer, Sep 2025 excerpt (PDF saved here): `UNWTO_Barometer_Sep2025_excerpt.pdf`
  extracted text in `unwto_sep2025_text.txt`
- https://www.untourism.int/news/international-tourist-arrivals-up-4-in-2025-reflecting-strong-travel-demand-around-the-world
- https://www.untourism.int/news/international-tourism-recovers-pre-pandemic-levels-in-2024
- Note: the free Barometer is an **excerpt**. The full country-by-country
  statistical annex is behind UN Tourism's paid e-library.

## 2 · Country-level arrivals, 2022–2024

Consolidated from UN Tourism "International Tourism Highlights, 2025 Edition".

| Country | 2024 | 2023 | 2022 |
|---|---|---|---|
| France | 102.0M | 100.0M | 93.2M |
| Spain | 93.8M | 85.2M | 71.7M |
| United States | 72.4M | 66.4M | 50.8M |
| Turkey | 60.6M | 55.2M | 50.5M |
| Italy | 57.7M | 57.3M | 49.8M |
| Mexico | 45.0M | 42.0M | 38.3M |
| United Kingdom | 41.8M | 37.2M | 30.7M |
| Germany | 37.5M | 34.8M | 28.5M |
| Japan | 36.9M | 25.1M | 3.8M |
| Greece | 36.0M | 32.7M | 27.8M |

- https://en.wikipedia.org/wiki/World_Tourism_rankings (secondary, cites UNWTO)
- Machine-readable: `country_arrivals_2022_2024.csv`

## 3 · Checked and rejected

- **World Bank** indicator `ST.INT.ARVL` (International tourism, number of
  arrivals). Queried the API directly for 2019–2025: **data stops at 2020**
  (224 countries for 2019, 132 for 2020, nothing after). Not usable for recent
  years. API, if ever needed:
  `https://api.worldbank.org/v2/country/all/indicator/ST.INT.ARVL?date=2019:2025&format=json`

## 4 · Worth pulling if the project needs more

- **Our World in Data** — tourism page, downloadable CSV, cites UNWTO/World Bank
- **Eurostat** — monthly tourism nights/arrivals for Europe, free API, very current
- **OECD Tourism Statistics** — arrivals and receipts for member countries
- **WTTC Economic Impact Research** — jobs and GDP contribution by country
- **IATA** — air passenger demand, monthly, good leading indicator
- **National tourism boards** — most current single-country numbers (e.g. Japan
  JNTO publishes monthly, Saudi MT publishes quarterly)

## 5 · Country coverage — the honest picture

No free source has every country for 2023–2025. Countries report late, so the
more recent the year, the fewer countries exist in the data.

Our World in Data, `international-tourist-trips` (cites UN Tourism / World Bank),
saved here as `owid_tourist_arrivals.csv`, 1995–2024:

| Year | Countries with a figure |
|---|---|
| 2015 | **185** |
| 2019 | **174** |
| 2020 | **177** |
| 2021 | **167** |
| 2022 | **138** |
| 2023 | **69** |
| 2024 | **67** |

So: ~174 countries for 2019, 138 for 2022, and only **69 for 2023 and 67 for
2024**. For **2025** there is no country-level file at all — only UN Tourism's
global and regional totals plus about twenty named growth percentages.

**A quirk worth knowing:** France is absent from the OWID 2023/2024 rows even
though it is the world's most-visited country. It has not reported to that
dataset, so Spain appears top. The UN Tourism Highlights table (section 2) does
have France. Two reputable sources, two different "number one" — the kind of
thing the report should mention rather than paper over.

Download: https://ourworldindata.org/grapher/international-tourist-trips.csv

### What this means for scoping

| If the app needs | Then |
|---|---|
| Every country, recent | Does not exist free. Rethink or narrow. |
| Every country, 2019 baseline | Fine — 174 countries. |
| ~67 major countries, 2023–24 | Fine — OWID covers it. |
| Anything 2025 | Global/regional only, or go per-country to national boards. |
| Europe, very current | Eurostat free API, monthly. |
| A live feed | National boards (Japan JNTO monthly), or IATA air traffic as a proxy. |
