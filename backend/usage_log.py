"""Append-only token log — the evidence behind the tokenomics section.

JSON Lines, never rewritten. The report needs token counts measured from real
runs, so every agent call records what it actually cost at the moment it
happened rather than being reconstructed later.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "data" / "usage_log.jsonl"
_lock = threading.Lock()


def record(agent: str, usage, seconds: float, *, tools: int = 0,
           cached: bool = False, note: str | None = None) -> dict:
    row = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "agent": agent,
        "requests": getattr(usage, "requests", None),
        "input_tokens": getattr(usage, "input_tokens", None),
        "cache_read_tokens": getattr(usage, "cache_read_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "tool_calls": tools,
        "cached_response": cached,
        "seconds": round(seconds, 3),
    }
    if note:
        row["note"] = note
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with _lock, LOG.open("a") as f:
        f.write(json.dumps(row) + "\n")
    return row


def summary() -> dict:
    """Per-agent totals and averages, straight off the log."""
    if not LOG.exists():
        return {"runs": 0, "agents": {}}
    rows = [json.loads(l) for l in LOG.read_text().splitlines() if l.strip()]
    out: dict[str, dict] = {}
    for r in rows:
        a = out.setdefault(r["agent"], {"runs": 0, "input": 0, "cached": 0,
                                        "output": 0, "seconds": 0.0, "tool_calls": 0})
        a["runs"] += 1
        a["input"] += r.get("input_tokens") or 0
        a["cached"] += r.get("cache_read_tokens") or 0
        a["output"] += r.get("output_tokens") or 0
        a["seconds"] += r.get("seconds") or 0
        a["tool_calls"] += r.get("tool_calls") or 0
    for a in out.values():
        n = max(a["runs"], 1)
        a["avg_input"] = round(a["input"] / n)
        a["avg_output"] = round(a["output"] / n)
        a["avg_seconds"] = round(a["seconds"] / n, 2)
    return {"runs": len(rows), "agents": out}
