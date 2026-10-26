# OWID / UN Tourism arrivals — known limitations

Dataset: `owid_tourist_arrivals.csv` · *International tourist trips* ·
Our World in Data, compiled from UN Tourism (UNWTO).
206 countries, 1995–2024. **5,193 of a possible 6,180 country-years = 84% complete.**

## 1 · What the number is, and is not

- **Arrivals, not people.** One person entering Spain four times is four arrivals.
  The global "1.5 billion" is trips, never individuals.
- **Overnight visitors only.** Same-day visitors and most cruise passengers are
  excluded. This is why the World Bank's Spain figure is ~50% higher — it counts
  same-day visitors too. The two are not interchangeable.
- **Non-residents only.** Residents returning home are never counted.
- **Residence, not citizenship.** A Saudi living in New York who visits France is
  an arrival *from the United States*.
- **No domestic tourism at all.**
- **Each country measures its own way** — border counts vs hotel registrations.
  Fine for orders of magnitude, unreliable for ranking neighbours 1–2% apart.

## 2 · Coverage by year

| Year | Countries reporting |
|---|---|
| 1995 | 173 |
| 2000 | 187 |
| 2005 | 188 |
| 2010 | 186 |
| 2015 | 185 |
| 2019 | 174 |
| 2020 | 177 |
| 2021 | 167 |
| 2022 | 138 |
| 2023 | 69 |
| 2024 | 67 |

Coverage is strong to 2021 (167–189 countries), then collapses: **138 in 2022,
69 in 2023, 67 in 2024.** Countries report late. A 2024 map is mostly empty.

## 3 · The absences that will bite

**Missing from 2024 despite being major destinations** (last year reported, and that figure):

| Country | Last year | Arrivals then |
|---|---|---|
| Turkey | 2022 | 50.5M |
| France | 2021 | 48.4M |
| Greece | 2022 | 27.8M |
| Austria | 2022 | 26.2M |
| Netherlands | 2022 | 16.1M |
| Croatia | 2022 | 15.3M |
| Denmark | 2022 | 14.2M |
| Egypt | 2022 | 11.6M |
| United Arab Emirates | 2021 | 11.5M |
| Ireland | 2019 | 11.0M |
| Morocco | 2022 | 10.9M |
| Malaysia | 2022 | 10.1M |

**France is the headline problem** — the world's most-visited country, last
reported 2021. On any map after 2021 the single biggest destination is blank.

**67 countries stop before 2022 entirely.** The worst: Mauritania (2000),
Tajikistan (2001), Zimbabwe (2001), Gabon (2005), **Russia (2005)**,
**Australia (2006)**, Turkmenistan (2007), Libya (2008), Syria (2011).

**17 countries start after 2000**, several only at the pandemic:
**Japan, South Korea, Taiwan and Uzbekistan all begin in 2020**; Iran has a
single year (2021); Indonesia starts 2015; Georgia 2010; Albania 2007.

**29 countries have holes inside their own range** — Romania is missing 19 years
between 1995 and 2024, French Guiana 12, Qatar 11, Vietnam 11, UAE 8, Bahrain 7.
A country can appear, vanish, and come back.

## 4 · What this means for the build

| Risk | Consequence | Handling |
|---|---|---|
| Year slider past 2021 | Map empties out, France disappears | Cap the slider at 2021, or show a live "N of 206 reporting" counter |
| Treating missing as zero | Countries look like nobody visits them | Grey for *no data*, distinct from low values |
| Totals by year | 2024 "world total" is 67 countries, not the world | Never present a yearly sum as global without the caveat |
| % of world flow | Denominator shifts with coverage | Fix the denominator to one well-covered year (2019: 174 countries) |
| Country-to-country compare | One side may have no overlapping years | Check for a shared year before plotting |
| Ranking close neighbours | Measurement methods differ | Present bands, not exact ranks |

## 5 · Where it came from

- Download: https://ourworldindata.org/grapher/international-tourist-trips.csv
- Upstream: UN Tourism, *Yearbook of Tourism Statistics* / *Compendium of Tourism Statistics*
- Checked against World Bank `ST.INT.ARVL` on 14 Oct 2026: systematic ~50%
  difference for Spain in every year, traced to the same-day-visitor definition.
  Sources were **not** merged for that reason.