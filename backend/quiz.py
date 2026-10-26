"""The geography quiz.

Every question is generated from reference data we already hold — capitals,
land borders, currencies and regions — so a round costs nothing and no model
is involved. The point of this file is the *distractors*: a multiple-choice
question is only worth asking if the wrong answers are plausible, and the
cheapest way to get that wrong is to draw them at random from the world.
"""
from __future__ import annotations

import random

import reference as R
import tnat_data as D

# Territories make poor quiz questions — few people can place Saint Barthélemy
# and nobody learns anything from failing to. Sovereign states only.
def _pool() -> list[dict]:
    iso2 = D._iso2()
    out = []
    for iso3 in D.un_members():
        f = R.facts().get(iso3)
        if not f or not f.get("capital") or not iso2.get(iso3):
            continue
        out.append({"iso3": iso3, "iso2": iso2[iso3].lower(), "name": f["name"],
                    "capital": f["capital"], "region": f.get("region", ""),
                    "subregion": f.get("subregion", ""),
                    "borders": f.get("borders") or [],
                    "currencies": f.get("currencies") or []})
    return out


def _distractors(pool, answer, key, n=3, rng=None, prefer="subregion"):
    """Three wrong answers that could believably be right.

    Drawn from the same sub-region first, then the same region, then anywhere.
    Asking which city is the capital of Peru is a real question when the other
    options are Quito, La Paz and Bogotá, and a giveaway when they are Oslo,
    Hanoi and Accra.
    """
    rng = rng or random
    want = answer[key]
    def take(rows):
        seen = {want}
        out = []
        for r in rows:
            v = r[key]
            if v and v not in seen:
                seen.add(v)
                out.append(v)
        return out
    near = [r for r in pool if r[prefer] == answer[prefer] and r["iso3"] != answer["iso3"]]
    mid = [r for r in pool if r["region"] == answer["region"] and r["iso3"] != answer["iso3"]]
    far = [r for r in pool if r["iso3"] != answer["iso3"]]
    rng.shuffle(near); rng.shuffle(mid); rng.shuffle(far)
    picks = take(near)[:n]
    if len(picks) < n:
        picks += [v for v in take(mid) if v not in picks][:n - len(picks)]
    if len(picks) < n:
        picks += [v for v in take(far) if v not in picks][:n - len(picks)]
    return picks[:n]


def _shuffled(correct, wrong, rng):
    options = [*wrong, correct]
    rng.shuffle(options)
    return options, options.index(correct)


def _capital_of(pool, c, rng):
    wrong = _distractors(pool, c, "capital", 3, rng)
    options, idx = _shuffled(c["capital"], wrong, rng)
    return {"kind": "capital", "prompt": f"What is the capital of {c['name']}?",
            "options": options, "answer": idx,
            "note": f"{c['capital']} is the capital of {c['name']}."}


def _country_of(pool, c, rng):
    wrong = _distractors(pool, c, "name", 3, rng)
    options, idx = _shuffled(c["name"], wrong, rng)
    return {"kind": "country", "prompt": f"{c['capital']} is the capital of which country?",
            "options": options, "answer": idx,
            "note": f"{c['capital']} is the capital of {c['name']}."}


def _flag_of(pool, c, rng):
    wrong = _distractors(pool, c, "name", 3, rng)
    options, idx = _shuffled(c["name"], wrong, rng)
    return {"kind": "flag", "prompt": "Which country flies this flag?",
            "flag": c["iso2"], "options": options, "answer": idx,
            "note": f"That is the flag of {c['name']}."}


def _border_of(pool, c, rng):
    """Which country does X share a land border with?

    The three wrong answers are deliberately taken from the same region, so
    the question tests whether you know the map rather than whether you know
    roughly which continent somebody is on.
    """
    names = {r["iso3"]: r["name"] for r in pool}
    real = [names[b] for b in c["borders"] if b in names]
    if not real:
        return None
    correct = rng.choice(real)
    banned = set(c["borders"]) | {c["iso3"]}
    near = [r for r in pool if r["region"] == c["region"] and r["iso3"] not in banned]
    rng.shuffle(near)
    wrong = [r["name"] for r in near[:3]]
    if len(wrong) < 3:
        return None
    options, idx = _shuffled(correct, wrong, rng)
    return {"kind": "border", "prompt": f"Which of these shares a land border with {c['name']}?",
            "options": options, "answer": idx,
            "note": f"{c['name']} borders {', '.join(sorted(real)[:6])}."}


BUILDERS = {"capital": _capital_of, "country": _country_of,
            "flag": _flag_of, "border": _border_of}


def round_of(kind: str = "mixed", n: int = 10, seed: int | None = None) -> list[dict]:
    """A round of questions. `kind` is one of the builders, or 'mixed'."""
    rng = random.Random(seed)
    pool = _pool()
    kinds = list(BUILDERS) if kind == "mixed" else [kind]
    kinds = [k for k in kinds if k in BUILDERS] or ["capital"]
    out, tries = [], 0
    used: set[str] = set()
    while len(out) < n and tries < n * 40:
        tries += 1
        c = rng.choice(pool)
        k = rng.choice(kinds)
        if (c["iso3"], k) in used:
            continue
        q = BUILDERS[k](pool, c, rng)
        if not q:
            continue
        used.add((c["iso3"], k))
        q["id"] = len(out) + 1
        out.append(q)
    return out
