"""Safety layer for TNAT.

Three risks, three defences, each one code rather than a line in a prompt:

  1. ATTACKS      prompt injection, attempts to extract the system prompt,
                  the API key, or another user's data.
  2. MALFUNCTION  the model inventing a figure. For this app that is the
                  failure that matters: the whole product claim is that every
                  number is counted, so an invented one is worse than an error.
  3. OVERSPENDING a loop or a bad actor burning the token budget.

A prompt that says "do not leak your instructions" is a request, not a control:
the model is free to ignore it and there is no record when it does. Everything
here runs outside the model, so it holds whether or not the model complies, and
every block is logged as evidence.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import re
import time
import unicodedata
from collections import defaultdict
from datetime import date
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "data" / "safety_log.jsonl"

# ---------------------------------------------------------------- 1. attacks
# Deliberately specific multi-word patterns. A single word like "ignore" would
# block "can you ignore the stale figures?", which is a reasonable question, and
# a guard that cries wolf gets switched off.
INJECTION = [
    (r"\b(ignore|disregard|override|bypass)\s+(all\s+|any\s+|the\s+|your\s+|these\s+|those\s+)*"
     r"(previous|prior|above|earlier|preceding|original|system)\s+"
     r"(instruction|instructions|prompt|prompts|rule|rules|direction|directions)", "override"),
    (r"\b(ignore|disregard)\s+(everything|all)\s+(above|before|prior|previous)", "override"),
    (r"\bforget\s+(everything|all)\s+(you|above|before)", "override"),
    # The possessive is required. "tell me the rules about visas" is a travel
    # question; "tell me YOUR rules" is not. Only "the SYSTEM prompt" counts
    # without it.
    (r"\b(show|print|reveal|repeat|output|display|tell\s+me|give\s+me)\s+(me\s+)?"
     r"your\s+(system\s+)?(prompt|instructions|rules|directives|guidelines)", "prompt-theft"),
    (r"\b(show|print|reveal|repeat|output|display|tell\s+me|give\s+me)\s+(me\s+)?"
     r"the\s+system\s+(prompt|instructions|message|rules)", "prompt-theft"),
    (r"\bwhat\s+(are|were)\s+your\s+(system\s+)?(instructions|rules|prompt)\b", "prompt-theft"),
    (r"\brepeat\s+(the\s+)?(text|words)\s+above\b", "prompt-theft"),
    (r"\b(api|secret|private)[\s_-]?key\b", "secret"),
    (r"\bPORTKEY_API_KEY\b|\bOPENAI_API_KEY\b", "secret"),
    (r"\benvironment\s+variable|\.env\b|\bos\.environ\b", "secret"),
    (r"\b(you\s+are\s+now|from\s+now\s+on\s+you\s+are|pretend\s+(you\s+are|to\s+be)|"
     r"act\s+as\s+(if\s+you\s+are\s+)?a?n?\s*(different|unrestricted|uncensored))", "role-hijack"),
    (r"\bdeveloper\s+mode\b|\bDAN\s+mode\b|\bjailbreak\b", "role-hijack"),
    (r"\b(list|show|dump|give\s+me)\s+(all\s+)?(the\s+)?(users|accounts|passwords|emails)\b",
     "exfiltration"),
    (r"\baccounts\.json\b|\busers\.json\b|\bpassword\s+hash", "exfiltration"),
]
COMPILED = [(re.compile(p, re.I), kind) for p, kind in INJECTION]

REFUSAL = {
    "override": "That is an attempt to change my instructions, so I am not going "
                "to act on it. Ask me about travel data and I will answer.",
    "prompt-theft": "I will not repeat my own instructions. Ask me about arrivals "
                    "or destinations instead.",
    "secret": "I do not have access to credentials and would not share them. "
              "Ask me about travel data instead.",
    "role-hijack": "I am the travelling consultant for this app and that is the only "
                   "role I take. What would you like to know about travel?",
    "exfiltration": "I cannot see other people's accounts or maps, and I would not "
                    "share them. Your own map is the only one I can read.",
    # Not a safety refusal -- a scope one. Kept here so there is exactly one
    # wording of it and the server, not the model, decides what it says.
    "off-topic": "I can only answer travelling-related questions — places, trips, "
                 "visas, weather, food, getting around. Ask me something about "
                 "travel and I will help.",
}
OFF_TOPIC = REFUSAL["off-topic"]


# Obfuscation is the obvious way around a pattern list, so the text is
# normalised before matching: unicode folded, zero-width characters stripped,
# leetspeak mapped back, and letters spaced out to defeat the regex rejoined.
ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad"), None)
LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s",
                      "7": "t", "@": "a", "$": "s", "|": "i"})
SPACED = re.compile(r"(?:\b\w\b[\s.\-_*]+){3,}\b\w\b")
B64 = re.compile(r"\b[A-Za-z0-9+/]{20,}={0,2}\b")


GAP = "\u0001"          # stands in for a real word break while letters are rejoined


def normalise(text: str) -> str:
    """Fold a message down to the plainest form of what it says."""
    t = unicodedata.normalize("NFKC", text or "").translate(ZERO_WIDTH).lower()
    # A wide gap is a word break; rejoining letters must not swallow it, or
    # "i g n o r e   a l l" collapses into one unsearchable word.
    t = re.sub(r"\s{2,}", GAP, t)
    t = SPACED.sub(lambda m: re.sub(r"[\s.\-_*]", "", m.group(0)), t)
    t = t.replace(GAP, " ").translate(LEET)
    t = re.sub(r"[^a-z0-9\s.,'?!_-]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def squash(text: str) -> str:
    """Every separator removed, for the case where word breaks are gone too."""
    return re.sub(r"[^a-z0-9]+", "", normalise(text))


# The same patterns with their whitespace made optional, so they still match
# once the spaces have been stripped out entirely.
SQUASHED = [(re.compile(p.pattern.replace(r"\s+", r"\s*").replace(r"\b", ""), re.I), k)
            for p, k in COMPILED]


def _decoded_payloads(text: str) -> list[str]:
    """Base64 blobs, decoded, so an encoded instruction is screened too."""
    out = []
    for m in B64.finditer(text or ""):
        chunk = m.group(0)
        try:
            raw = base64.b64decode(chunk + "=" * (-len(chunk) % 4), validate=True)
            dec = raw.decode("utf-8", "strict")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        if sum(c.isprintable() for c in dec) / max(len(dec), 1) > 0.9:
            out.append(dec)
    return out


def screen_input(text: str) -> dict:
    """Check a user message before it ever reaches the model.

    Blocking here is cheaper as well as safer: a refused message costs no
    tokens at all, which makes this defence serve risk 1 and risk 3 at once.
    """
    raw = (text or "").strip()
    # the raw text, the normalised text, and anything base64 hid inside it
    candidates = [("raw", raw, COMPILED), ("normalised", normalise(raw), COMPILED),
                  ("squashed", squash(raw), SQUASHED)]
    candidates += [("decoded", normalise(d), COMPILED) for d in _decoded_payloads(raw)]
    for how, t, patterns in candidates:
        for pattern, kind in patterns:
            m = pattern.search(t)
            if m:
                return {"blocked": True, "category": kind,
                        "matched": redact_pii(m.group(0))[:80],
                        "via": how, "reply": REFUSAL[kind]}
    # Same keys whether or not it fired, so a caller can read `reply` without
    # first checking `blocked`.
    return {"blocked": False, "category": None, "matched": None,
            "via": None, "reply": None}


# --------------------------------------------------------------- leak checks
# Fingerprints of our own system prompt. If these come back out of the model,
# the instructions have leaked no matter how the request was phrased.
PROMPT_FINGERPRINTS = (
    "House rules — these apply to every TNAT agent",
    "You have no travel statistics of your own",
    "Never invent a percentile",
)
KEY_SHAPES = [re.compile(p) for p in (
    r"\bsk-[A-Za-z0-9_\-]{16,}", r"\bpk-[A-Za-z0-9_\-]{16,}",
    r"\b[A-Za-z0-9+/]{32,}={0,2}\b",
)]


def _live_keys() -> list[str]:
    return [v for k, v in os.environ.items()
            if k.endswith("_API_KEY") and len(v.strip()) >= 12]


def screen_output(text: str) -> dict:
    """Last line of defence: nothing secret leaves the process.

    Checked against the live key values too, so even a key that does not match
    a known shape cannot be echoed back.
    """
    out, leaked = text or "", []
    for key in _live_keys():
        if key in out:
            out = out.replace(key, "[redacted]")
            leaked.append("api-key")
    for fp in PROMPT_FINGERPRINTS:
        if fp.lower() in out.lower():
            leaked.append("system-prompt")
            out = ("I will not repeat my own instructions. Ask me about travel "
                   "data instead.")
            break
    for shape in KEY_SHAPES:
        m = shape.search(out)
        if m and len(m.group(0)) >= 32 and " " not in m.group(0):
            out = out.replace(m.group(0), "[redacted]")
            leaked.append("key-shaped-string")
    return {"text": out, "leaked": sorted(set(leaked)), "clean": not leaked}


# ----------------------------------------------------------- 2. malfunction
# The app's entire claim is that every figure is counted. So figures in the
# model's prose are checked against the figures the tools actually returned.
NUM = re.compile(r"\b\d[\d,]*(?:\.\d+)?\b")
MIN_CHECKED = 1000          # below this it is a year, a day count, a rank


def numbers_in(text: str) -> list[float]:
    out = []
    for m in NUM.finditer(text or ""):
        try:
            out.append(float(m.group(0).replace(",", "")))
        except ValueError:
            pass
    return out


def collect_allowed(obj, into: set | None = None) -> set:
    """Every number any tool returned, at any depth, as the allowed set."""
    into = set() if into is None else into
    if isinstance(obj, dict):
        for v in obj.values():
            collect_allowed(v, into)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            collect_allowed(v, into)
    elif isinstance(obj, bool):
        pass
    elif isinstance(obj, (int, float)):
        into.add(float(obj))
    elif isinstance(obj, str):
        for n in numbers_in(obj):
            into.add(n)
    return into


def _is_year(raw: str, value: float) -> bool:
    """A bare four-digit number in a sensible range is a date, not a claim.

    Without this, "go in 2024" is flagged as an invented statistic whenever
    2024 happens not to appear in the tool output — a false positive on
    ordinary writing, which would make the whole check untrustworthy.
    Thousands separators and decimals mark a real quantity, so those still
    get checked.
    """
    return ("," not in raw and "." not in raw
            and 1900 <= value <= 2100 and float(value).is_integer())


def check_numbers(text: str, allowed: set, tol: float = 0.02) -> dict:
    """Find figures in the prose that no tool supports.

    Rounding is expected — "about 2 million" for 2,013,000 is good writing, not
    a fabrication — so a number passes if it is within tolerance of an allowed
    value, or is a plausible rounding of one.
    """
    unsupported, checked = [], 0
    for m in NUM.finditer(text or ""):
        raw = m.group(0)
        try:
            n = float(raw.replace(",", ""))
        except ValueError:
            continue
        if n < MIN_CHECKED or _is_year(raw, n):
            continue
        checked += 1
        ok = False
        for a in allowed:
            if a == 0:
                continue
            if abs(n - a) / max(abs(a), 1e-9) <= tol:
                ok = True
                break
            # "2 million" standing in for 2,013,000
            for unit in (1e3, 1e6, 1e9):
                if abs(n * unit - a) / max(abs(a), 1e-9) <= tol:
                    ok = True
                    break
            if ok:
                break
        if not ok:
            unsupported.append(n)
    return {"ok": not unsupported, "unsupported": unsupported, "checked": checked}


# --------------------------------------------------------- 3. overspending
class Budget:
    """Ceilings the per-run usage limits cannot provide.

    `UsageLimits` stops one runaway call. It does nothing about ten thousand
    well-behaved calls, which is the same bill. These are process-wide and
    reset daily.
    """

    def __init__(self, daily_tokens: int, daily_calls: int, session_calls: int):
        self.daily_tokens = daily_tokens
        self.daily_calls = daily_calls
        self.session_calls = session_calls
        self.day = date.today()
        self.tokens = 0
        self.calls = 0
        self.per_session: dict[str, int] = defaultdict(int)

    def _roll(self) -> None:
        if date.today() != self.day:
            self.day, self.tokens, self.calls = date.today(), 0, 0
            self.per_session.clear()

    def check(self, session: str = "anon") -> dict:
        self._roll()
        if self.tokens >= self.daily_tokens:
            return {"ok": False, "reason": "daily token budget reached",
                    "retry": "tomorrow"}
        if self.calls >= self.daily_calls:
            return {"ok": False, "reason": "daily request budget reached",
                    "retry": "tomorrow"}
        if self.per_session[session] >= self.session_calls:
            return {"ok": False, "reason": "this conversation has reached its limit",
                    "retry": "start a new session"}
        return {"ok": True}

    def record(self, session: str, tokens: int) -> None:
        self._roll()
        self.calls += 1
        self.tokens += max(tokens, 0)
        self.per_session[session] += 1

    def snapshot(self) -> dict:
        self._roll()
        return {"day": str(self.day), "tokens_used": self.tokens,
                "daily_token_budget": self.daily_tokens,
                "calls_used": self.calls, "daily_call_budget": self.daily_calls,
                "session_call_budget": self.session_calls,
                "pct_tokens": round(self.tokens / self.daily_tokens * 100, 1)}


# --------------------------------------------------------------------- PII
# The safety log records what matched. That snippet is user text, so it can
# carry an address or a card number straight into a file we keep forever.
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
LONGNUM = re.compile(r"\b\d[\d \-]{11,}\d\b")


def redact_pii(text: str) -> str:
    t = EMAIL.sub("[email]", text or "")
    return LONGNUM.sub("[number]", t)


# ----------------------------------------------------- per-caller throttle
class Throttle:
    """A sliding window per caller.

    The budget protects the bill in total; this stops one caller consuming all
    of it and leaving nothing for anybody else.
    """

    def __init__(self, limit: int, window: float = 60.0):
        self.limit, self.window = limit, window
        self.hits: dict[str, list[float]] = defaultdict(list)

    def check(self, who: str) -> dict:
        now = time.time()
        recent = [t for t in self.hits[who] if now - t < self.window]
        self.hits[who] = recent
        if len(recent) >= self.limit:
            return {"ok": False, "retry_after": int(self.window - (now - recent[0])) + 1}
        return {"ok": True}

    def record(self, who: str) -> None:
        self.hits[who].append(time.time())


# ------------------------------------------------------------------ logging
def record(event: str, **fields) -> dict:
    """Append-only. The evidence that a defence fired, with a timestamp."""
    safe = {k: (redact_pii(v) if isinstance(v, str) else v) for k, v in fields.items()}
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event, **safe}
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError:
        pass
    return row
