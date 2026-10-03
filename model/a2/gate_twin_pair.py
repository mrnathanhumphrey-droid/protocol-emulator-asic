"""SPEC P3 -- the twin-pair regression: pin BOTH directions of the self-exclusion bug.

THE ONE CLAIM: a parameter-identical pair of lanes is analysed against exactly
N-1 interferers, in every analysis path this project uses.

⛔⛔ WHY ONE TEST AND NOT TWO HABITS. "Exclude self from the set" is silently
wrong in opposite directions depending on how it compares, and this project has
now hit both within an hour:

  BY VALUE    (pyRTA: `t != excluded` on a frozen dataclass)
              two parameter-identical lanes are BOTH removed -> an interferer
              vanishes -> the bound is OPTIMISTIC (10 -> 8, 5 -> 3)
  BY IDENTITY (ours: `o is not lane`)
              a lane object merely EQUAL to one in the list is NOT removed ->
              the subject interferes with itself -> the bound is PESSIMISTIC
              (SPI-target 5 -> 7)

Neither raises. Both produce a plausible number of the right magnitude. And
knowing about one gives no protection against the other -- they look nothing
alike at the call site. The identity assertion inside `response_time_b` catches
only the by-identity shape, and only when a caller builds the set twice; the
by-value shape originates in the ANALYSIS LIBRARY, where we cannot put an
assertion at all.

⭐ SO THE INVARIANT IS PINNED BY A TEST INSTEAD OF BY MEMORY: build the twins
ONCE, and require every path to see N-1 interferers and to return the SAME
number for both members of the pair. The real lane set contains two such pairs
by construction (UART-tx/UART-rx and SPI-tx/SPI-target are parameter-identical
in C and D), which is exactly why this bug was reachable here.

⛔ The pessimistic direction never threatened a bound -- but it DID fabricate a
negative finding (it made gate 0.9b report "no case separates the two tests").
A wrong number is damaging in both directions; only one of them is unsafe.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from a2_close import Lane                                      # noqa: E402
from bursty import BLane, response_time_b                      # noqa: E402
from rta_spuri import response_time_spuri                      # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Two parameter-identical PAIRS, built ONCE. Same shape as the real lane set.
TWINS = [("A1", 100, 2, 40), ("A2", 100, 2, 40),      # identical pair
         ("B1", 37, 2, 15), ("B2", 37, 2, 15),        # identical pair
         ("C1", 61, 2, 25)]                           # a singleton, as control


def main() -> int:
    print()
    print("=" * 78)
    print("SPEC P3 -- twin-pair regression (both directions of self-exclusion)")
    print("=" * 78)
    print("  lane set, built ONCE: %s"
          % ", ".join("%s(T=%d,C=%d,D=%d)" % t for t in TWINS))
    print("  two parameter-identical pairs + one singleton; N = %d" % len(TWINS))
    N = len(TWINS)
    rc = 0

    # ---- path 1: our bursty recurrence ---------------------------------
    print()
    print("  --- path 1: response_time_b (ours, filters BY IDENTITY) ---")
    bl = [BLane(n, T, C, D) for n, T, C, D in TWINS]
    seen = {}
    for l in bl:
        r = response_time_b(l, bl)["r"]
        seen[l.name] = r
        print("    %-5s r = %s" % (l.name, r))
    ok1 = seen["A1"] == seen["A2"] and seen["B1"] == seen["B2"]
    print("    twins agree (A1==A2, B1==B2): %s"
          % ("yes" if ok1 else "*** NO -- a twin saw a different interferer set ***"))
    rc |= 0 if ok1 else 1

    # ---- path 2: the periodic recurrence --------------------------------
    print()
    print("  --- path 2: response_time_spuri (ours, filters BY IDENTITY) ---")
    pl = [Lane(n, T, C=C, D=D) for n, T, C, D in TWINS]
    seen2 = {}
    for l in pl:
        r = response_time_spuri(l, pl, plus_one=0)["r"]
        seen2[l.name] = r
        print("    %-5s r = %s" % (l.name, r))
    ok2 = seen2["A1"] == seen2["A2"] and seen2["B1"] == seen2["B2"]
    agree12 = all(seen[k] == seen2[k] for k in seen)
    print("    twins agree: %s ; matches path 1: %s"
          % ("yes" if ok2 else "*** NO ***", "yes" if agree12 else "*** NO ***"))
    rc |= 0 if (ok2 and agree12) else 1

    # ---- the by-identity trap, demonstrated then caught -----------------
    print()
    print("  --- the BY-IDENTITY trap: a copy is not excluded ---")
    copy = BLane("A1", 100, 2, 40)          # equal to bl[0] but not identical
    try:
        response_time_b(copy, bl)
        print("    *** FAIL: an equal-but-distinct lane was ACCEPTED; the subject")
        print("        would interfere with itself and the bound inflate ***")
        rc |= 1
    except AssertionError as e:
        print("    REJECTED by the identity assertion in response_time_b")
        print("      %s" % str(e).split(".")[0])

    # ---- path 3: the foreign tool, which filters BY VALUE ---------------
    print()
    print("  --- path 3: pyRTA (foreign, filters BY VALUE) ---")
    src = os.environ.get("PYRTA_SRC")
    if not src or not os.path.isdir(src):
        print("    *** pyRTA not found (set PYRTA_SRC). This path is UNPINNED,")
        print("        and it is the one where the by-VALUE direction lives.")
        print("    Gate is RED: the regression does not cover both directions.")
        return 1
    sys.path.insert(0, src)
    from response_time_analysis import edf                                  # noqa
    from response_time_analysis.model import (WCET, Deadline,               # noqa
                                              FullyNonPreemptive, IdealProcessor,
                                              Periodic, Priority, Task, taskset)
    tasks = [Task(Periodic(period=T), FullyNonPreemptive(WCET(C)),
                  Deadline(D), Priority(i))
             for i, (n, T, C, D) in enumerate(TWINS)]
    ts = taskset(*tasks)
    bad = 0
    for (n, T, C, D), t in zip(TWINS, tasks):
        k = len(list(ts.excluding_iter(t)))
        if k != N - 1:
            bad += 1
        print("    %-5s sees %d of %d interferers  %s"
              % (n, k, N - 1, "ok" if k == N - 1 else "*** %d DROPPED ***"
                 % (N - 1 - k)))
    if bad:
        print("    *** FAIL: the by-VALUE filter merged a twin pair. Without the")
        print("        distinct Priority identity tags this is what happens, and")
        print("        the bounds come out OPTIMISTIC. ***")
        rc |= 1
    else:
        print("    => no pair merged; the identity tags are doing their job")
    seen3 = {}
    for (n, T, C, D), t in zip(TWINS, tasks):
        sol = edf.rta(ts, t, IdealProcessor())
        seen3[n] = getattr(sol.response_time_bound, "value", sol.response_time_bound)
    print("    pyRTA: %s" % ", ".join("%s=%s" % (k, v) for k, v in seen3.items()))
    ok3 = seen3["A1"] == seen3["A2"] and seen3["B1"] == seen3["B2"]
    cross = all(seen[k] == seen3[k] for k in seen)
    print("    twins agree: %s ; matches ours: %s"
          % ("yes" if ok3 else "*** NO ***", "yes" if cross else "*** NO ***"))
    rc |= 0 if (ok3 and cross) else 1

    # ---- the by-value trap, demonstrated ---------------------------------
    print()
    print("  --- the BY-VALUE trap: identical tags merge the pair ---")
    untagged = [Task(Periodic(period=T), FullyNonPreemptive(WCET(C)),
                     Deadline(D), Priority(0))              # SAME tag for all
                for n, T, C, D in TWINS]
    ts2 = taskset(*untagged)
    merged = [k for k in (0, 2) if len(list(ts2.excluding_iter(untagged[k]))) != N - 1]
    print("    with every Priority(0): twin members seeing < %d interferers: %s"
          % (N - 1, [TWINS[k][0] for k in merged] or "none"))
    if merged:
        print("    DEMONSTRATED -- this is the optimistic direction, and it is why")
        print("    gate_pyrta asserts the interferer count rather than trusting tags.")
    else:
        print("    *** the trap did not reproduce; the guard may be unnecessary")
        print("        or the library changed. Investigate before relying on it. ***")
        rc |= 1

    print()
    print("=" * 78)
    print("  GATE P3: %s" % ("PASSED -- both directions pinned by one test"
                             if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
