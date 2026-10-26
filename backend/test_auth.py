"""Tests for the account layer.

Runs against a throwaway store so it can never touch the real accounts file.
"""
from __future__ import annotations

import pathlib
import sys
import tempfile

import auth

PASS = FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [ok  ] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}   {extra}")


def expect_error(label, fn, fragment):
    try:
        fn()
    except auth.AuthError as e:
        check(label, fragment in str(e), f"got {e!r}")
    else:
        check(label, False, "no error raised")


# redirect the store before anything touches it
tmp = pathlib.Path(tempfile.mkdtemp()) / "accounts.json"
auth.STORE = tmp
auth._fails.clear()

print("\nregistration")
r = auth.register("Ada@Example.com ", "hunter22", "hunter22")
check("returns a session token", len(r["token"]) > 20)
check("email is normalised to lower case", r["email"] == "ada@example.com")
check("a new account starts with an empty map", r["map"] == auth.EMPTY_MAP)
check("flagged as newly created", r["created"] is True)

expect_error("mismatched confirmation is refused",
             lambda: auth.register("b@x.com", "abcdefgh", "abcdeg"), "do not match")
expect_error("a password under 8 characters is refused",
             lambda: auth.register("b@x.com", "abc1234", "abc1234"), "at least 8")
expect_error("a malformed email is refused",
             lambda: auth.register("not-an-email", "abcdefgh", "abcdefgh"), "email address")
expect_error("a duplicate email is refused",
             lambda: auth.register("ada@example.com", "abcdefgh", "abcdefgh"), "already exists")

print("\npassword storage")
raw = tmp.read_text()
check("the plaintext password is nowhere in the store", "hunter22" not in raw)
u = auth._read()["users"]["ada@example.com"]
check("a digest is stored, not the password", len(u["hash"]) == 64)
check("the salt is per-user and random", len(u["salt"]) == auth.SALT_BYTES * 2)
other = auth.register("bob@example.com", "hunter22", "hunter22")
b = auth._read()["users"]["bob@example.com"]
check("the same password gives a different digest for a different user",
      b["hash"] != u["hash"])

print("\nsign in")
s = auth.login("ada@example.com", "hunter22")
check("correct credentials return a token", len(s["token"]) > 20)
check("whoami resolves a live token", auth.whoami(s["token"]) == "ada@example.com")
check("whoami rejects a made-up token", auth.whoami("not-a-real-token") is None)
check("whoami on no token is simply a guest", auth.whoami(None) is None)

# The two failures must be indistinguishable or the endpoint tells an attacker
# which emails are registered.
msgs = []
for email, pw in (("ada@example.com", "wrong"), ("nobody@example.com", "wrong")):
    auth._fails.clear()
    try:
        auth.login(email, pw)
    except auth.AuthError as e:
        msgs.append(str(e))
check("a wrong password and an unknown email are indistinguishable",
      len(msgs) == 2 and msgs[0] == msgs[1], str(msgs))

print("\nrate limiting")
auth._fails.clear()
for _ in range(auth.MAX_FAILS):
    try:
        auth.login("ada@example.com", "wrong")
    except auth.AuthError:
        pass
expect_error("the account locks after repeated failures",
             lambda: auth.login("ada@example.com", "hunter22"), "Too many")
check("the lock is a minute, not the whole counting window",
      0 < auth._locked_for("ada@example.com") <= auth.LOCKOUT)
auth._fails.clear()
check("a correct password works again once the lock clears",
      auth.login("ada@example.com", "hunter22")["email"] == "ada@example.com")

print("\nthe map survives a sign-out")
tok = auth.login("ada@example.com", "hunter22")["token"]
auth.save_map("ada@example.com", {"visited": ["France", "Japan"], "lived": [], "want": ["Bhutan"]})
auth.logout(tok)
check("the token stops working after sign-out", auth.whoami(tok) is None)
check("the map is still there", auth.get_map("ada@example.com")["visited"] == ["France", "Japan"])
back = auth.login("ada@example.com", "hunter22")
check("signing back in returns it", back["map"]["want"] == ["Bhutan"])
check("the other account is unaffected", auth.get_map("bob@example.com") == auth.EMPTY_MAP)

print("\nthe map is cleaned before it is stored")
auth.save_map("bob@example.com", {
    "visited": ["France", "France", "", 42, "x" * 200],
    "lived": None, "want": ["Peru"], "junk": ["should not survive"]})
m = auth.get_map("bob@example.com")
check("duplicates are dropped", m["visited"] == ["France"], str(m["visited"]))
check("unknown keys are dropped",
      set(m) == {"visited", "lived", "want", "years"}, str(sorted(m)))
check("a null list becomes an empty list", m["lived"] == [])

print("\nvisit years")
auth.save_map("bob@example.com", {
    "visited": ["France", "Japan"], "lived": [], "want": [],
    "years": {"France": 2015, "Japan": "2019", "Narnia": 2020, "France2": "abc"}})
y = auth.get_map("bob@example.com")["years"]
check("years are kept for pinned places", y == {"France": 2015, "Japan": 2019}, str(y))
check("a year for somewhere not pinned is dropped", "Narnia" not in y)
auth.save_map("bob@example.com", {"visited": ["Japan"], "lived": [], "want": [],
                                  "years": {"France": 2015, "Japan": 2019}})
check("removing a pin removes its year",
      auth.get_map("bob@example.com")["years"] == {"Japan": 2019})
check("an impossible year is refused",
      auth.save_map("bob@example.com", {"visited": ["Japan"], "lived": [], "want": [],
                                        "years": {"Japan": 1200}})["years"] == {})

print("\nguest pins carry into a new account")
c = auth.register("carry@example.com", "abcdefgh", "abcdefgh",
                  carry_map={"visited": ["Peru", "Peru"], "lived": [], "want": []})
check("the pins moved across", c["map"]["visited"] == ["Peru"])

print("\nshorthand and seeding")
check("a bare username resolves to the demo domain",
      auth.normalise("test1") == f"test1@{auth.TEST_DOMAIN}")
check("a real address is left alone",
      auth.normalise(" Ada@Example.COM ") == "ada@example.com")
made = auth.seed_test_accounts()
check("test1 and test2 are seeded", sorted(made) ==
      [f"test1@{auth.TEST_DOMAIN}", f"test2@{auth.TEST_DOMAIN}"], str(made))
check("both sign in with the published demo password",
      auth.login("test1", auth.TEST_PASSWORD)["email"] == f"test1@{auth.TEST_DOMAIN}"
      and auth.login("test2", auth.TEST_PASSWORD)["email"] == f"test2@{auth.TEST_DOMAIN}")
check("the demo password is at least as long as the minimum",
      len(auth.TEST_PASSWORD) >= auth.MIN_PASSWORD)
auth.save_map(f"test1@{auth.TEST_DOMAIN}", {"visited": ["Chad"], "lived": [], "want": []})
check("re-seeding a correct account is a no-op",
      auth.seed_test_accounts() == []
      and auth.get_map(f"test1@{auth.TEST_DOMAIN}")["visited"] == ["Chad"])

# a demo account left on an older password must be repaired, pins intact
_d = auth._read()
_salt = bytes.fromhex(_d["users"][f"test1@{auth.TEST_DOMAIN}"]["salt"])
_d["users"][f"test1@{auth.TEST_DOMAIN}"]["hash"] = auth._hash("123456", _salt)
auth._write(_d)
_fixed = auth.seed_test_accounts()
check("a demo account on a stale password is reset", _fixed == [f"test1@{auth.TEST_DOMAIN}"],
      str(_fixed))
check("the repaired account signs in with the new password",
      auth.login("test1", auth.TEST_PASSWORD)["email"] == f"test1@{auth.TEST_DOMAIN}")
check("repairing the password kept the map",
      auth.get_map(f"test1@{auth.TEST_DOMAIN}")["visited"] == ["Chad"])

print("\ntrip list")
me = f"test1@{auth.TEST_DOMAIN}"
auth.save_todo(me, [])
check("a new list is empty", auth.get_todo(me) == [])
auth.save_todo(me, [{"text": "Renew I-20 signature", "done": False},
                    {"text": "Book the flight", "done": True}])
got = auth.get_todo(me)
check("items come back in order", [i["text"] for i in got]
      == ["Renew I-20 signature", "Book the flight"])
check("ticks are kept", got[1]["done"] is True)
# The client is not trusted with the shape of what it stores.
auth.save_todo(me, [{"text": "   "}, {"text": "  padded  ", "done": "yes"},
                    "not a dict", {"no_text": 1}])
got = auth.get_todo(me)
check("blank and malformed entries are dropped", len(got) == 1, str(got))
auth.save_todo(me, [{"text": "See the Jerónimos Monastery",
                     "where": "Lisbon, Portugal"}])
check("an item remembers which stop it belongs to",
      auth.get_todo(me)[0]["where"] == "Lisbon, Portugal")
auth.save_todo(me, [{"text": "x", "where": "y" * 300}])
check("the stop label is capped too",
      len(auth.get_todo(me)[0]["where"]) == auth.MAX_TODO_WHERE)
auth.save_todo(me, [{"text": "no stop given"}])
check("an item without a stop is still valid",
      auth.get_todo(me)[0]["where"] == "")
auth.save_todo(me, [{"text": "  padded  ", "done": "yes"}])
got = auth.get_todo(me)
check("text is trimmed", got[0]["text"] == "padded")
check("done is coerced to a real boolean", got[0]["done"] is True)
auth.save_todo(me, [{"text": "x" * 500}])
check("overlong text is cut at the stored limit",
      len(auth.get_todo(me)[0]["text"]) == auth.MAX_TODO_TEXT)
auth.save_todo(me, [{"text": f"item {n}"} for n in range(200)])
check("the list cannot grow without bound",
      len(auth.get_todo(me)) == auth.MAX_TODO)
auth.save_todo(me, [])
check("it can be emptied again", auth.get_todo(me) == [])
check("one account cannot see another's list",
      auth.get_todo(f"test2@{auth.TEST_DOMAIN}") == [])

print("\n" + "=" * 62)
print(f"  {PASS} passed, {FAIL} failed")
print("=" * 62)
sys.exit(1 if FAIL else 0)
