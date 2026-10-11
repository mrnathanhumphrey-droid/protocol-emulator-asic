"""A2 BOUNDS DIFF -- a bound that disappears is RED, never a quiet change.

⛔⛔ WHY (Wilson, HC1-B). Under HS + 2 pyRTA's W1 fixed point gave no bound on
`ckdense`, `derive` fell back to pyRTA with OUR jitter, and the regenerated
`test/clocked_a2_bounds.json` carried a budget that looked like a bound. The A2
suite stayed 44/44 green: nothing compared the new budgets with the old ones.
An absent result counted as a pass -- the third time in one arc.

CHECKS (pyRTA-primary: RED without the pinned pyRTA, like every A2 bound gate)
  1. `program_a2.budgets()` regenerates every image's budget WITHOUT REFUSING
     (an image with no pyRTA bound that is not marked `NO_RTA_BUDGET` raises).
  2. Against the COMMITTED json: any field that was set and is now None or
     gone -> RED; any slack < 0 -> RED; any other change is REPORTED (a moved
     margin is information, not a failure).
  3. Every lane of every non-overloaded image has a budget, labelled `pyRTA`
     or `EMPIRICAL`; an EMPIRICAL one is only on a NO_RTA_BUDGET image.

MUST-FIRES (each must go red): a planted None in one regenerated field; a
planted negative slack; `ckdense` un-marked (the refuse-to-emit rule).
"""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path[:0] = [HERE, os.path.join(ROOT, "model"), os.path.join(ROOT, "test")]
import program_a2 as P                      # noqa: E402
from pyrta_src import pinned_pyrta          # noqa: E402

FIELDS = ("T", "r_ours", "r_pyrta", "r_floor", "slack", "budget")


def diff(committed, regen):
    """(problems, changes)."""
    probs, changes = [], []
    for name, c in sorted(committed.items()):
        r = regen.get(name)
        if r is None:
            probs.append("%s: image vanished from the regenerated bounds" % name)
            continue
        for key in ("w1", "w1_pyrta"):
            if c.get(key) is not None and r.get(key) is None:
                if not (key == "w1_pyrta" and name in P.NO_RTA_BUDGET):
                    probs.append("%s: %s was %s, now None" % (name, key, c[key]))
        for ln, ce in sorted(c.get("lanes", {}).items()):
            re_ = r.get("lanes", {}).get(ln)
            if re_ is None:
                probs.append("%s lane %s vanished" % (name, ln))
                continue
            for f in FIELDS:
                a, b = ce.get(f), re_.get(f)
                if a is not None and b is None:
                    if f == "r_pyrta" and name in P.NO_RTA_BUDGET:
                        continue
                    probs.append("%s lane %s: %s was %s, now None" % (name, ln, f, a))
                elif a != b:
                    changes.append("%s lane %s: %s %s -> %s" % (name, ln, f, a, b))
    for name, r in regen.items():
        for ln, e in r.get("lanes", {}).items():
            if e.get("slack") is not None and e["slack"] < 0:
                probs.append("%s lane %s: NEGATIVE slack %s" % (name, ln, e["slack"]))
            if r["U"] <= 1.0:
                kind = e.get("budget")
                if kind not in ("pyRTA", "EMPIRICAL") or e.get("slack") is None:
                    probs.append("%s lane %s: no labelled budget (%s)" % (name, ln, kind))
                if kind == "EMPIRICAL" and name not in P.NO_RTA_BUDGET:
                    probs.append("%s lane %s: EMPIRICAL budget on an unmarked image"
                                 % (name, ln))
    return probs, changes


def main():
    print("=" * 78)
    print("A2 BOUNDS DIFF -- a bound that disappears is red")
    print("=" * 78)
    src = pinned_pyrta(quiet=True)
    if not src:
        print("  *** pinned pyRTA not found -- RED (the budgets are pyRTA-primary)")
        return 1
    with open(P.OUT_JSON, encoding="utf-8") as fh:
        committed = json.load(fh)
    images = P.clocked_images()
    try:
        regen = json.loads(json.dumps(P.budgets(src, images)))
    except RuntimeError as exc:
        print("  *** program_a2 REFUSED to emit: %s" % exc)
        return 1
    probs, changes = diff(committed, regen)
    print("  images: %d committed, %d regenerated" % (len(committed), len(regen)))
    for s in changes[:40]:
        print("  changed  " + s)
    print("  %d field change(s) reported (not failures)" % len(changes))
    for s in probs:
        print("  *** " + s)
    ok = not probs

    print("  --- must-fires: each must go RED ---")
    a = copy.deepcopy(regen)
    a["ckheavy_image.hex"]["lanes"]["0"]["slack"] = None
    p1, _ = diff(committed, a)
    b = copy.deepcopy(regen)
    b["ckheavy_image.hex"]["lanes"]["0"]["slack"] = -1
    p2, _ = diff(committed, b)
    saved = P.NO_RTA_BUDGET.pop("ckdense_image.hex")
    try:
        P.budgets(src, [x for x in images if x[0] == "ckdense_image.hex"])
        p3 = []
    except RuntimeError as exc:
        p3 = [str(exc)]
    finally:
        P.NO_RTA_BUDGET["ckdense_image.hex"] = saved
    for name, p in (("a planted None (ckheavy lane 0 slack)", p1),
                    ("a planted negative slack", p2),
                    ("ckdense un-marked (refuse to emit)", p3)):
        print("  must-fire %-40s %s" % (name, ("red  ok -- " + p[0][:60]) if p
                                        else "*** STAYED GREEN"))
        ok = ok and bool(p)
    print()
    print("  GATE a2-bounds-diff: %s" % ("PASSED" if ok else "*** FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
