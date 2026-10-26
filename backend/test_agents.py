"""Tests for conversation handling.

No API key and no network: these exercise the pure history logic, which is
where the chat actually broke.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from pydantic_ai.messages import (
    ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart,
)

import agents

PASS = FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [ok  ] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}   {extra}")


def turn(text, with_tool=False):
    """One user turn and the assistant's reply, optionally using a tool."""
    out = [ModelRequest(parts=[UserPromptPart(content=text)])]
    if with_tool:
        out.append(ModelResponse(parts=[ToolCallPart(tool_name="country_stats",
                                                     args={"name": "Iceland"},
                                                     tool_call_id="call_1")]))
        out.append(ModelRequest(parts=[ToolReturnPart(tool_name="country_stats",
                                                      content={"arrivals": 1},
                                                      tool_call_id="call_1")]))
    out.append(ModelResponse(parts=[TextPart(content=f"reply to {text}")]))
    return out


def starts_cleanly(msgs):
    """A history must begin with a user turn, never mid tool-call."""
    if not msgs:
        return True
    return any(type(p).__name__ == "UserPromptPart"
               for p in getattr(msgs[0], "parts", []))


def no_orphan_returns(msgs):
    """Every tool return must have its matching call still present."""
    calls = {p.tool_call_id for m in msgs for p in getattr(m, "parts", [])
             if type(p).__name__ == "ToolCallPart"}
    returns = {p.tool_call_id for m in msgs for p in getattr(m, "parts", [])
               if type(p).__name__ == "ToolReturnPart"}
    return returns <= calls


print("\nthe shape the library actually wants")
# This is the bug that broke the chat: ("user", text) tuples were handed back
# as message_history and failed deep inside pydantic-ai.
check("history entries are message objects, not tuples",
      all(not isinstance(m, tuple) for m in turn("hi")))
check("a turn starts with a user prompt", starts_cleanly(turn("hi")))

print("\ntrimming a long conversation")
short = turn("one") + turn("two")
check("a short history is returned untouched",
      agents.trim_history(short, max_messages=24) == short)

long_plain = sum((turn(f"q{i}") for i in range(20)), [])
t = agents.trim_history(long_plain, max_messages=10)
check("a long history is cut down", len(t) <= 10, f"{len(t)} messages")
check("and still starts at a user turn", starts_cleanly(t))
check("the most recent exchange survives",
      any(getattr(p, "content", None) == "q19"
          for m in t for p in getattr(m, "parts", [])))

print("\ntool calls are never orphaned")
# Cutting mid-turn would leave a tool return whose call is gone, which the
# provider rejects outright — a far more confusing failure than the original.
long_tools = sum((turn(f"q{i}", with_tool=True) for i in range(12)), [])
for cap in range(2, 26):
    t = agents.trim_history(long_tools, max_messages=cap)
    if not starts_cleanly(t):
        check(f"cap={cap} starts cleanly", False, "starts mid-turn")
        break
    if not no_orphan_returns(t):
        check(f"cap={cap} leaves no orphan tool return", False, "orphaned")
        break
else:
    check("every cap from 2 to 25 starts at a turn boundary", True)
    check("every cap from 2 to 25 leaves no orphaned tool return", True)

check("an impossible cap yields an empty history rather than a broken one",
      agents.trim_history(long_tools, max_messages=1) == [])

print("\nthe Run object carries the history forward")
check("Run has a messages field", "messages" in agents.Run.__dataclass_fields__)
check("it defaults to empty rather than None",
      agents.Run(output="x", usage={}, seconds=0, tool_calls=0).messages == [])

print("\n" + "=" * 62)
print(f"  {PASS} passed, {FAIL} failed")
print("=" * 62)
sys.exit(1 if FAIL else 0)
