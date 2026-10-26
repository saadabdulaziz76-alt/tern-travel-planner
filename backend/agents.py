"""The four TNAT agents.

Every agent shares the same toolset, and the tools are the only source of
numbers. The prompts forbid stating a figure that did not come from a tool, so
the data layer is the single place a statistic can enter the system.
"""

from __future__ import annotations

import json
import os
import time

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

import tnat_data as D
import usage_log
from config import MAX_REQUESTS_PER_RUN, MAX_TOOL_CALLS_PER_RUN, build_model

PROMPTS = Path(__file__).resolve().parent / "prompts"
LIMITS = UsageLimits(request_limit=MAX_REQUESTS_PER_RUN,
                     tool_calls_limit=MAX_TOOL_CALLS_PER_RUN)


def _instructions(name: str) -> str:
    shared = (PROMPTS / "_shared.md").read_text()
    return f"{(PROMPTS / name).read_text()}\n\n---\n\n{shared}"


# ------------------------------------------------------------ structured output
class Verdict(BaseModel):
    """What the Profile Analyst returns."""
    verdict: str = Field(description="'traveler' or 'tourist'")
    headline: str = Field(description="One sentence, leading with the best number.")
    flow_coverage_pct: float
    n_countries: int
    observations: list[str] = Field(description="Two or three specific findings.")
    peer_note: str = Field(description="Survey context, with its ceiling stated.")


class ConsultantReply(BaseModel):
    """What the Consultant returns.

    The scope decision is the model's, because judging it needs the meaning of
    the question and the thread it sits in -- "why?" is a travel question or
    not depending entirely on what came before, and no word list reads that.
    The refusal *wording* is not the model's: main.py substitutes its own, so
    a user cannot talk it into answering anyway.
    """
    on_topic: bool = Field(
        description="True if the message is about travel or leisure travel in "
                    "any form -- destinations, trips, visas, weather, food, "
                    "safety, transport, culture, cost -- or is a follow-up to "
                    "the travel conversation so far. False for anything else.")
    reply: str = Field(
        description="The answer, in full. This must never be empty when "
                    "on_topic is true — if you have judged the question to be "
                    "about travel then you have to answer it. Leave it empty "
                    "only when on_topic is false, where the site supplies the "
                    "wording instead.")


class Pick(BaseModel):
    country: str
    why: str = Field(description="One line on what it does to their profile.")
    one_in_n_trips: int
    caution: str | None = Field(default=None,
                                description="Safety, access or stale-data warning.")


class Recommendations(BaseModel):
    intro: str
    picks: list[Pick]


class GetawayNote(BaseModel):
    city: str
    why: str = Field(description="one or two sentences on what you would go for")
    # How well this place suits the chosen theme. No dataset says a city is
    # romantic, so this is the model's judgement over a shortlist the data
    # picked — and the UI labels it as a suggestion, not a measurement.
    fit: str = Field(default="ok", description="good | ok | poor for the chosen theme")
    visa_warning: str | None = Field(
        default=None, description="set when this one needs a visa the traveller lacks")


class ParkGuide(BaseModel):
    what_its_for: str = Field(description="why you come here, two or three sentences")
    best_months: str = Field(description="when to go and why, with months named")
    avoid: str | None = Field(default=None, description="months or conditions to avoid")
    how_long: str = Field(description="how much time it deserves")
    know_before: list[str] = Field(default_factory=list,
                                   description="permits, car, altitude, bears, season")


class Proposal(BaseModel):
    city: str = Field(description="the town itself, not the region")
    region: str = Field(description="state, province or region, for disambiguation")
    why: str = Field(description="one line on what you go there for")
    fit: str = Field(default="good", description="good | ok for the chosen theme")


class Proposals(BaseModel):
    intro: str = Field(description="one line setting up the list")
    places: list[Proposal]


class GetawayNotes(BaseModel):
    intro: str = Field(description="one line setting up the shortlist")
    notes: list[GetawayNote]


class Day(BaseModel):
    day: int
    theme: str
    items: list[str]


class Itinerary(BaseModel):
    country: str
    summary: str
    days: list[Day]
    money_note: str = Field(description="Relative cost guidance. Never a figure.")
    guide_note: str | None = Field(
        default=None,
        description="Required whenever a local guide was asked for: what kind "
                    "of guide to look for in these places, where such a day "
                    "is usually booked, and the questions worth asking before "
                    "booking one. Leave null only when no guide was wanted.")


# -------------------------------------------------------------------- the tools
def _attach(agent: Agent) -> Agent:
    """Give an agent the whole toolset. Counts of calls are tracked per run."""

    @agent.tool_plain
    def country_stats(country: str) -> dict:
        """Arrivals, share of world travel, rank and data quality for one country."""
        return D.country_stats(country)

    @agent.tool_plain
    def profile_score(visited: list[str]) -> dict:
        """Flow coverage, rarity score and traveler/tourist verdict for a list of countries."""
        return D.profile_score(visited)

    @agent.tool_plain
    def whats_left(visited: list[str]) -> dict:
        """Share of world travel still uncovered, and the biggest unvisited countries."""
        return D.whats_left(visited)

    @agent.tool_plain
    def trajectory(country: str, visited_year: int | None = None) -> dict:
        """A country's arrivals over time; pass visited_year to test 'were you early'."""
        return D.trajectory(country, visited_year)

    @agent.tool_plain
    def recommend(visited: list[str], want: list[str] | None = None,
                  region: str | None = None, limit: int = 8) -> dict:
        """Unvisited countries ranked by how much they would improve a traveler score."""
        return D.recommend(visited, want, region, limit)

    @agent.tool_plain
    def peer_band(n_countries: int) -> dict:
        """Survey band for someone with this many countries, including its ceiling."""
        return D.peer_band(n_countries)

    @agent.tool_plain
    def extremes(n: int = 10) -> dict:
        """The most- and least-visited countries in the world."""
        return D.extremes(n)

    return agent


AGENTS = {
    "profile_analyst": ("profile_analyst.md", Verdict),
    "recommender": ("recommender.md", Recommendations),
    "trip_architect": ("trip_architect.md", Itinerary),
    "consultant": ("consultant.md", ConsultantReply),
    "getaway_scout": ("getaway_scout.md", GetawayNotes),
    "weekend_planner": ("weekend_plan.md", Itinerary),
    "getaway_finder": ("getaway_finder.md", Proposals),
    "park_guide": ("park_guide.md", ParkGuide),
}


@lru_cache(maxsize=8)
def build(key: str) -> Agent:
    prompt_file, output = AGENTS[key]
    agent = Agent(build_model(), instructions=_instructions(prompt_file),
                  output_type=output, retries=1)
    return _attach(agent)


def prefetch(visited: list[str], want: list[str] | None = None) -> str:
    """Compute the profile in Python and hand it to the agent as context.

    The data layer is pure arithmetic and answers in microseconds. Letting the
    model discover the same numbers through six sequential tool calls costs a
    minute of wall clock and thousands of tokens for no extra information. The
    tools stay available for anything the agent wants to dig into — this just
    removes the round trips it would always have made anyway.
    """
    block = {
        "profile": D.profile_score(visited),
        "whats_left": D.whats_left(visited),
        "peer_band": D.peer_band(len(D.resolve_many(visited)[0])),
        "off_path": D.off_path(visited),
    }
    if want:
        block["want_list"] = want
    return ("Here are the computed figures for this user. They are already "
            "correct — use them directly and do not call tools to re-fetch "
            "them. Call a tool only if you need something not shown here.\n\n"
            + json.dumps(block, indent=1))


@dataclass
class Run:
    output: object
    usage: dict
    seconds: float
    tool_calls: int
    # The full conversation as pydantic-ai models it. A caller continuing a
    # chat must hand this straight back as `history` — the library expects
    # ModelMessage objects, and anything else fails deep inside the run with
    # an AttributeError rather than a readable error.
    messages: list = field(default_factory=list)
    # Exactly what the tools returned this run. The safety layer checks the
    # model's prose against these, so an invented figure can be caught.
    tool_returns: list = field(default_factory=list)


async def run(key: str, prompt: str, history=None) -> Run:
    """Run an agent and record what it cost."""
    agent = build(key)
    t0 = time.perf_counter()
    result = await agent.run(prompt, message_history=history or [], usage_limits=LIMITS)
    secs = time.perf_counter() - t0
    calls = sum(
        1
        for m in result.new_messages()
        for p in getattr(m, "parts", [])
        if type(p).__name__ == "ToolCallPart"
    )
    returns = [getattr(p, "content", None)
               for m in result.new_messages()
               for p in getattr(m, "parts", [])
               if type(p).__name__ == "ToolReturnPart"]
    row = usage_log.record(key, result.usage, secs, tools=calls)
    return Run(result.output, row, secs, calls, list(result.all_messages()),
               [r for r in returns if r is not None])


def trim_history(messages: list, max_messages: int = 24) -> list:
    """Keep a conversation bounded without orphaning a tool call.

    Dropping messages from the front is only safe at a turn boundary. Cutting
    mid-turn can leave a tool return whose matching call is gone, which the
    model provider rejects outright.
    """
    if len(messages) <= max_messages:
        return messages
    cut = messages[-max_messages:]
    for i, m in enumerate(cut):
        parts = getattr(m, "parts", [])
        if any(type(p).__name__ == "UserPromptPart" for p in parts):
            return cut[i:]
    return []          # no clean boundary found — start the context over
