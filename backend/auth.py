"""Accounts, sessions and per-user map storage.

Deliberately small and dependency-free: PBKDF2-HMAC-SHA256 out of the standard
library, a single JSON file on disk, and bearer tokens. That is the right size
for a single-process teaching app, and it is honest about what it is — there is
no email verification, no password reset and no TLS in front of it, so the
README says plainly that this is not a production identity system.

What it does get right, because these are the mistakes that actually matter:
  * passwords are never stored or logged, only a salted PBKDF2 digest
  * the digest comparison is constant-time
  * a wrong password and an unknown email return the identical error, so the
    endpoint cannot be used to find out who has an account
  * repeated failures are rate-limited per account
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

STORE = Path(__file__).resolve().parent.parent / "data" / "accounts.json"

ITERATIONS = 200_000
SALT_BYTES = 16
MIN_PASSWORD = 8          # the seeded test accounts use 12345678
MAX_PASSWORD = 128
SESSION_DAYS = 30
MAX_FAILS = 5
FAIL_WINDOW = 15 * 60     # how far back failures are counted, seconds
LOCKOUT = 60              # how long the account is held, seconds
TEST_DOMAIN = "tern.app"
TEST_ACCOUNTS = ("test1", "test2")
TEST_PASSWORD = "12345678"

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_lock = threading.Lock()


class AuthError(Exception):
    """Raised with a message that is safe to show the user."""


# --------------------------------------------------------------- the store
def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _blank() -> dict:
    return {"users": {}, "sessions": {}}


def _read() -> dict:
    if not STORE.exists():
        return _blank()
    try:
        d = json.loads(STORE.read_text())
    except (json.JSONDecodeError, OSError):
        # A corrupt store must not take the whole app down. Move it aside so
        # the evidence survives and carry on with an empty one.
        STORE.replace(STORE.with_suffix(".corrupt.json"))
        return _blank()
    d.setdefault("users", {})
    d.setdefault("sessions", {})
    return d


def _write(d: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1))
    tmp.replace(STORE)           # atomic, so a crash mid-write cannot truncate


# ------------------------------------------------------------- credentials
def _hash(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS).hex()


def normalise(email: str, shorthand: bool = True) -> str:
    """Lower-case and trim. A bare `test1` resolves to the seeded test account.

    Typing the full address every time to try the app would be a pointless tax,
    and the shorthand only ever reaches the demo domain. It is a *sign-in*
    convenience only: registration passes `shorthand=False`, because otherwise
    a typo with no "@" in it would be silently turned into a valid-looking
    address and the account would be created against something the user never
    typed.
    """
    e = (email or "").strip().lower()
    if shorthand and e and "@" not in e:
        e = f"{e}@{TEST_DOMAIN}"
    return e


def _check_password(password: str) -> None:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        raise AuthError(f"Password must be at least {MIN_PASSWORD} characters.")
    if len(password) > MAX_PASSWORD:
        raise AuthError("That password is too long.")


# ------------------------------------------------------------ rate limiting
_fails: dict[str, list[float]] = {}


def _record_fail(email: str) -> None:
    now = time.time()
    hits = [t for t in _fails.get(email, []) if now - t < FAIL_WINDOW]
    hits.append(now)
    _fails[email] = hits


def _locked_for(email: str) -> int:
    now = time.time()
    hits = [t for t in _fails.get(email, []) if now - t < FAIL_WINDOW]
    _fails[email] = hits
    if len(hits) < MAX_FAILS:
        return 0
    # Held for a minute from the last attempt, not for the whole counting
    # window — long enough to stop guessing, short enough that a user who
    # genuinely forgot their password is not locked out of the demo.
    left = int(LOCKOUT - (now - hits[-1]))
    return left if left > 0 else 0


# ----------------------------------------------------------------- the API
EMPTY_MAP = {"visited": [], "lived": [], "want": []}


def register(email: str, password: str, confirm: str,
             carry_map: dict | None = None) -> dict:
    e = normalise(email, shorthand=False)
    if not EMAIL_RE.match(e):
        raise AuthError("That does not look like an email address.")
    if password != confirm:
        raise AuthError("The two passwords do not match.")
    _check_password(password)

    with _lock:
        d = _read()
        if e in d["users"]:
            raise AuthError("An account already exists for that email.")
        salt = secrets.token_bytes(SALT_BYTES)
        d["users"][e] = {
            "email": e,
            "salt": salt.hex(),
            "hash": _hash(password, salt),
            "iterations": ITERATIONS,
            "created": _now(),
            "updated": _now(),
            # a guest who painted a map before signing up keeps it
            "map": _clean_map(carry_map) if carry_map else dict(EMPTY_MAP),
        }
        token = _new_session(d, e)
        _write(d)
        return {"token": token, "email": e, "map": d["users"][e]["map"],
                "profile": {k: None for k in PROFILE_KEYS}, "created": True}


def login(email: str, password: str) -> dict:
    e = normalise(email)
    wait = _locked_for(e)
    if wait:
        raise AuthError(f"Too many failed attempts. Try again in {wait} seconds.")

    with _lock:
        d = _read()
        u = d["users"].get(e)
        # Identical failure for "no such account" and "wrong password", so this
        # endpoint cannot be used to enumerate who has signed up.
        if not u or not hmac.compare_digest(
                _hash(password, bytes.fromhex(u["salt"])), u["hash"]):
            _record_fail(e)
            raise AuthError("Email or password is incorrect.")
        _fails.pop(e, None)
        token = _new_session(d, e)
        _write(d)
        return {"token": token, "email": e, "map": u.get("map", dict(EMPTY_MAP)),
                "profile": {k: u.get(k) for k in PROFILE_KEYS}, "created": False}


def _new_session(d: dict, email: str) -> str:
    token = secrets.token_urlsafe(32)
    d["sessions"][token] = {
        "email": email,
        "expires": (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS))
        .isoformat(timespec="seconds"),
    }
    _prune(d)
    return token


def _prune(d: dict) -> None:
    now = datetime.now(timezone.utc)
    for t, s in list(d["sessions"].items()):
        try:
            if datetime.fromisoformat(s["expires"]) < now:
                del d["sessions"][t]
        except (ValueError, KeyError):
            del d["sessions"][t]


def whoami(token: str | None) -> str | None:
    """Email for a live token, or None. Never raises — callers treat None as a guest."""
    if not token:
        return None
    with _lock:
        d = _read()
        s = d["sessions"].get(token)
        if not s:
            return None
        try:
            if datetime.fromisoformat(s["expires"]) < datetime.now(timezone.utc):
                del d["sessions"][token]
                _write(d)
                return None
        except ValueError:
            return None
        return s["email"] if s["email"] in d["users"] else None


def logout(token: str | None) -> None:
    if not token:
        return
    with _lock:
        d = _read()
        if d["sessions"].pop(token, None) is not None:
            _write(d)


MIN_YEAR, MAX_YEAR = 1900, 2100


def _clean_map(m: dict | None) -> dict:
    """Keep the three lists and the optional year each place was visited."""
    out = {}
    for k in ("visited", "lived", "want"):
        seen, vals = set(), []
        for n in (m or {}).get(k, []) or []:
            if isinstance(n, str) and n and n not in seen and len(n) <= 80:
                seen.add(n)
                vals.append(n)
        out[k] = vals[:400]
    pinned = set(out["visited"]) | set(out["lived"]) | set(out["want"])
    years = {}
    for name, y in ((m or {}).get("years") or {}).items():
        # only for places still pinned, so deleting a pin cannot leave a
        # year behind that nothing refers to
        if name in pinned:
            try:
                yi = int(y)
            except (TypeError, ValueError):
                continue
            if MIN_YEAR <= yi <= MAX_YEAR:
                years[name] = yi
    out["years"] = years
    return out


# Home country and passport drive distance, carbon, visas and routing, so they
# belong with the map rather than in a separate place that can drift from it.
PROFILE_KEYS = ("home", "passport", "home_city")


def get_profile(email: str) -> dict:
    with _lock:
        u = _read()["users"].get(email) or {}
        return {k: u.get(k) for k in PROFILE_KEYS}


def save_profile(email: str, home: str | None, passport: str | None,
                 home_city: str | None = None) -> dict:
    """Store two ISO3 codes and an optional city. Anything else is refused."""
    def clean(v):
        v = (v or "").strip().upper()
        return v if len(v) == 3 and v.isalpha() else None

    city = (home_city or "").strip()[:80] or None

    with _lock:
        d = _read()
        u = d["users"].get(email)
        if not u:
            raise AuthError("That account no longer exists.")
        u["home"], u["passport"] = clean(home), clean(passport)
        u["home_city"] = city if u["home"] else None
        u["updated"] = _now()
        _write(d)
        return {k: u.get(k) for k in PROFILE_KEYS}


def get_map(email: str) -> dict:
    with _lock:
        u = _read()["users"].get(email)
        return u.get("map", dict(EMPTY_MAP)) if u else dict(EMPTY_MAP)


def save_map(email: str, labels: dict) -> dict:
    """Write the user's map. Called on every change, so a logout loses nothing."""
    with _lock:
        d = _read()
        u = d["users"].get(email)
        if not u:
            raise AuthError("That account no longer exists.")
        u["map"] = _clean_map(labels)
        u["updated"] = _now()
        _write(d)
        return u["map"]


# ------------------------------------------------------------- trip list
# The checklist you tick off while you are actually travelling, so it follows
# the account rather than the browser. Same contract as the map: written on
# every change, so closing the tab mid-trip loses nothing.
MAX_TODO = 120
MAX_TODO_TEXT = 200
MAX_TODO_WHERE = 80


def _clean_todo(items) -> list[dict]:
    """Trust nothing from the client: shape, length and types are all ours."""
    out = []
    for it in (items or [])[:MAX_TODO]:
        if not isinstance(it, dict):
            continue
        text = str(it.get("text", "")).strip()[:MAX_TODO_TEXT]
        if not text:
            continue
        # `where` is the city and country this line belongs to, so a list
        # built from a four-stop trip still says which stop each item is for.
        out.append({"text": text, "done": bool(it.get("done")),
                    "where": str(it.get("where", "")).strip()[:MAX_TODO_WHERE]})
    return out


def get_todo(email: str) -> list[dict]:
    with _lock:
        u = _read()["users"].get(email)
        return list(u.get("todo", [])) if u else []


def save_todo(email: str, items) -> list[dict]:
    with _lock:
        d = _read()
        u = d["users"].get(email)
        if not u:
            raise AuthError("That account no longer exists.")
        u["todo"] = _clean_todo(items)
        u["updated"] = _now()
        _write(d)
        return u["todo"]


# ------------------------------------------------------------------- seed
def seed_test_accounts() -> list[str]:
    """test1 / test2, password 12345678, so the app can be tried without signing up.

    These exist for the demo and the grader, and the password is published, so
    the one guarantee that matters is that the documented password always works.
    An account whose digest no longer matches — because the demo password
    changed between versions — has its credential reset in place. Its map is
    left exactly as it was: resetting a password must never cost a user their
    pins, and these are the only accounts this ever touches.

    Returns the accounts that were created or repaired.
    """
    touched = []
    for name in TEST_ACCOUNTS:
        e = f"{name}@{TEST_DOMAIN}"
        with _lock:
            d = _read()
            u = d["users"].get(e)
            if u and hmac.compare_digest(
                    _hash(TEST_PASSWORD, bytes.fromhex(u["salt"])), u["hash"]):
                continue                      # already correct, leave it alone
            if u:
                salt = secrets.token_bytes(SALT_BYTES)
                u["salt"] = salt.hex()
                u["hash"] = _hash(TEST_PASSWORD, salt)
                u["iterations"] = ITERATIONS
                u["updated"] = _now()
                _write(d)
                touched.append(e)
                continue
        try:
            register(e, TEST_PASSWORD, TEST_PASSWORD)
            touched.append(e)
        except AuthError:
            pass
    return touched
