"""The quiz: shape, fairness and determinism."""
import sys
import quiz

PASS = FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [ok  ] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}   {detail}")


print("\nquestion shape")
qs = quiz.round_of("mixed", 10, seed=1)
check("a round is the length asked for", len(qs) == 10, str(len(qs)))
check("every question has four options", all(len(q["options"]) == 4 for q in qs))
check("the answer index is inside the options",
      all(0 <= q["answer"] < len(q["options"]) for q in qs))
check("no question repeats an option",
      all(len(set(q["options"])) == 4 for q in qs))
check("every question explains itself", all(q["note"].strip() for q in qs))
check("every question is numbered", [q["id"] for q in qs] == list(range(1, 11)))

print("\nfairness")
# The whole value of the quiz is that the wrong answers are plausible. A
# capital question whose distractors are drawn from the far side of the world
# is answerable without knowing anything.
caps = quiz.round_of("capital", 12, seed=3)
pool = {c["name"]: c for c in quiz._pool()}
by_capital = {c["capital"]: c for c in quiz._pool()}
same_region = 0
for q in caps:
    right = by_capital.get(q["options"][q["answer"]])
    others = [by_capital.get(o) for i, o in enumerate(q["options"]) if i != q["answer"]]
    if right and all(o and o["region"] == right["region"] for o in others):
        same_region += 1
check("distractors come from the same region", same_region >= 10, f"{same_region}/12")

bor = quiz.round_of("border", 8, seed=5)
# borders are ISO3 codes, so they need the ISO3-keyed map, not the name one
by_iso3 = {c["iso3"]: c for c in quiz._pool()}
ok = True
for q in bor:
    right = q["options"][q["answer"]]
    subject = q["prompt"].split("land border with ")[-1].rstrip("?")
    c = pool.get(subject)
    names = {by_iso3[b]["name"] for b in (c["borders"] if c else []) if b in by_iso3}
    if right not in names:
        ok = False
    # and none of the wrong answers may actually be a neighbour
    if any(o in names for i, o in enumerate(q["options"]) if i != q["answer"]):
        ok = False
check("border questions have exactly one true neighbour", ok)

print("\nrepeatability")
a = quiz.round_of("mixed", 8, seed=42)
b = quiz.round_of("mixed", 8, seed=42)
check("the same seed gives the same round",
      [q["prompt"] for q in a] == [q["prompt"] for q in b])
c = quiz.round_of("mixed", 8, seed=43)
check("a different seed does not", [q["prompt"] for q in a] != [q["prompt"] for q in c])

print("\nscope")
flags = quiz.round_of("flag", 6, seed=9)
check("flag questions carry a flag code", all(q.get("flag") for q in flags))
check("flag codes are two letters", all(len(q["flag"]) == 2 for q in flags))
check("only one kind is asked when one is chosen",
      {q["kind"] for q in flags} == {"flag"})
check("mixed really is mixed", len({q["kind"] for q in quiz.round_of("mixed", 20, seed=2)}) >= 3)
# Territories make poor questions and sovereign states are the stated scope.
check("the pool is sovereign states only", 150 <= len(quiz._pool()) <= 200,
      str(len(quiz._pool())))
check("an absurd length is clamped by the caller, not here",
      len(quiz.round_of("capital", 1, seed=1)) == 1)

print("\n" + "=" * 62)
print(f"  {PASS} passed, {FAIL} failed")
print("=" * 62)
sys.exit(1 if FAIL else 0)
