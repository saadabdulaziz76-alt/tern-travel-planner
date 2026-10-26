# "You're in the top X% of travellers" — can we say it?

## Short answer

Not from arrivals data. Arrivals counts trips into countries and contains no
per-person information at all. A **survey** is needed, and one exists.

## The source: Pew Research Center, Spring 2023, 24 countries

Share of people by number of foreign countries ever visited (median across the
24 countries surveyed):

| Countries visited | Share |
|---|---|
| None — never left home country | **21%** |
| 1–4 | 34% |
| 5–9 | 17% |
| **10 or more** | **13%** |

(These are medians computed per bucket across 24 countries, so they do not sum
to 100. Worth stating if the figure is quoted.)

Spread is enormous: **Sweden 57%** have visited 10+ countries and ~1% have never
left. **India: 95% have never left the country**, 3% have travelled at all.

Sources:
- https://www.pewresearch.org/global/2023/12/06/international-travel/
- Agoda well-travelled survey, 2019: 68% have visited up to 10 countries
  https://www.agoda.com/press/well-traveled-survey-2019/

## The ceiling problem — this is the important bit

**The top bucket is "10 or more". The data does not resolve above 10.**

So 10 countries, 34 countries and 100 countries all sit in the same 13% bucket.
Any site claiming "34 countries puts you in the top 2.1%" is inventing precision
that no public dataset supports.

## The population problem

Pew surveyed 24 countries, skewed toward wealthier ones. Weighted by actual
world population — India alone is 1.4bn with 95% never having left — the true
global share who have seen 10+ countries is far below 13%. Probably low single
digits. Nobody has measured it properly.

So "top 13% of the world" is **wrong**. "Top 13% of people in 24 surveyed
countries" is right, and is what the source supports.

## What can be said honestly

| Claim | Supportable? |
|---|---|
| "Fewer than 13% of people in surveyed countries have visited 10+ countries" | **Yes** — Pew, directly |
| "21% of people have never left their home country" | **Yes** — Pew |
| "You've beaten 97.9% of travellers" | **No** — invented precision |
| "You're in the top 13% of the world" | **No** — wrong population |
| "Your countries take 38% of world arrivals" | **Yes** — exact, from OWID |
| "You've been to 3 countries in the bottom 10% by arrivals" | **Yes** — exact |

## Recommended framing

Give the sourced band, admit the ceiling, then pivot to the number that *is*
exact:

> You've been to 34 countries. Only **13%** of people in surveyed countries have
> been to ten or more — and the survey doesn't count any higher than that, so
> nobody can honestly tell you your exact percentile.
>
> Here is something we can measure exactly: your 34 countries account for
> **38.4%** of all international travel on Earth. And four of them are in the
> bottom tenth of countries by visitors.

Stronger than a fake percentile, and every number has a citation.

---

## What the site actually ships (decided 14 Oct 2026)

An earlier build ignored the advice above and did show a "top X% of travellers"
tile. It interpolated between Pew's 13%-at-ten and the Travelers' Century Club's
membership count (~1,500 people in seventy years) to produce a smooth curve —
"top 4.8%" at 17 countries, "top 0.002%" at 94.

Two things were wrong with it:

1. It was an estimate stacked on an estimate. Neither endpoint measures what the
   curve claimed to measure, and the shape between them was assumed.
2. It was ~3× too generous, because it quietly treated Pew's 24 wealthier
   countries as if they were the world.

**It has been deleted.** `rarity_among_people()` is gone from `tnat_data.py` and
a regression test asserts it never comes back. The four tiles are now all
counted figures:

| Tile | At 17 countries | Where it comes from |
|---|---|---|
| countries pinned | 17 | count |
| of the world's 195 | 8.7% | 17 / 195 UN member states |
| world travel covered | 36.1% | those countries' share of 2019 arrivals, OWID |
| rarest stop | 1 in 17,797 | Chad's share of world arrivals, OWID |

The survey still appears, but as a sentence under the tiles rather than a hero
number, carrying its own ceiling and its own caveat:

> 13% of people in surveyed countries have visited ten or more. That is the
> smallest group the survey measures, so it cannot place 17 any more precisely
> than that. Pew surveyed 24 mostly wealthier countries, so this is not a world
> figure. Weighted by population it would be rarer.

The "rare traveller" idea it was meant to capture survives as `off_path()`,
which is exact: how many of your countries sit in the world's 50 least-visited,
named so the claim can be checked.

This is the same move the *Visited* app makes — it reports countries ÷ 195 and
ranks users against its own userbase, never against humanity — arrived at
independently and for the same reason.
