"""SPEC 1.4b -- a THIRD-PARTY implementation checks the SHIPPED five-lane numbers.

THE ONE CLAIM: `r_i = {10, 5, 7, 10, 5}` on the real five-lane table, at the real
periods, computed by an implementation nobody on this project wrote.

⛔⛔ WHY THIS IS THE STRONGEST INDEPENDENCE RESULT HERE, AND WHY THE EARLIER ONES
WERE NOT ENOUGH. TChecker is a foreign ENGINE running OUR model, and
`gen_edf.py` is a second implementation of the recurrence's semantics by the same
hand -- exactly what standing law 1 says is not an independent witness. It has
already bitten once: the `a == T-1` release guard made every period one tick
short and looked precisely like "the recurrence is unsound". And every foreign
agreement so far (9/9 periodic, 9/9 bursty) was on SMALL CONSTRUCTED instances;
the shipped numbers were accepted on a transfer argument, not checked.

pyRTA is a different thing: a third-party library implementing MACHINE-VERIFIED
theory (Bozhko & Brandenburg, "Abstract Response-Time Analysis: A Formal
Foundation for the Busy-Window Principle", ECRTS 2020; the PROSA/Rocq
development). It takes the real periods with no scaling and no replica.

⭐ AND ITS BLOCKING TERM INDEPENDENTLY CONFIRMS A CORRECTION WE DERIVED. pyRTA's
`blocking_bound()` is

    max(t.execution.max_non_preemptive_segment - EPSILON_TIME
        for t in all_tasks.with_deadline_greater_than_iter(reference))
    where reference = offset + deadline_of(task_under_analysis)

which is `max{C_j - 1 : D_j > a + D_i}` -- the `-1`, the later-deadline filter,
AND the dependence on the offset `a`. The offset-dependence of `B_i` was derived
here as something the A2 spec had missed; PROSA had it all along. Independent
arrival at the same formula is worth more than our derivation alone.

⚠ WHAT THIS DOES AND DOES NOT ESTABLISH:
  * pyRTA computes a SUFFICIENT bound, not an exact one. So our number being
    LARGER than pyRTA's would mean we are pessimistic (acceptable); our number
    being SMALLER would mean we may be UNSOUND (the forbidden direction). They
    are EQUAL, which is the strongest of the three outcomes.
  * pyRTA's own README disclaims: "While PROSA verifies the underlying RTA
    theory, the implementations in pyRTA are not verified themselves." So this is
    a foreign implementation of verified theory, not a verified implementation.
  * For an EXACTNESS check the tool is `nptest` (Nasri & Brandenburg, RTSS 2017),
    whose uniprocessor schedule-abstraction-graph analysis is exact. Not run here
    -- it needs a C++14/TBB build under WSL. Recorded as the next escalation.

⛔ SETUP. pyRTA is not vendored (it is third-party source and this repo is
published). Point `PYRTA_SRC` at a clone's `src/`:
    git clone https://github.com/PROSA-Project/pyRTA
    PYRTA_SRC=/path/to/pyRTA/src python model/a2/gate_pyrta.py
Zero dependencies, Python >= 3.10. If the tool is absent this gate goes RED
rather than silently passing -- the F1 pattern.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# the shipped five-lane table and OUR numbers, as committed in A2_GREEN_RESULTS
SPEC = [("UART-tx 115200", 434, 2, 216, 10),
        ("SPI-tx 1 MHz", 25, 2, 12, 5),
        ("I2C 400 kHz", 62, 2, 30, 7),
        ("UART-rx 115200", 434, 2, 216, 10),
        ("SPI-target 1 MHz", 25, 2, 12, 5)]


def find_pyrta() -> str | None:
    env = os.environ.get("PYRTA_SRC")
    if env and os.path.isdir(env):
        return env
    # a clone beside the scratchpad is the documented convenience path
    for base in (os.environ.get("TEMP", ""), os.path.expanduser("~")):
        for root, dirs, _ in os.walk(base):
            if os.path.basename(root) == "pyrta" and "src" in dirs:
                cand = os.path.join(root, "src")
                if os.path.isdir(os.path.join(cand, "response_time_analysis")):
                    return cand
            if root.count(os.sep) - base.count(os.sep) > 6:
                dirs[:] = []
    return None


def periodic_equivalence() -> bool:
    """⭐ OUR TWO 'BURSTY' LANES ARE EXACTLY PERIODIC, and that is why the real
    lanes never exercised the bursty path.

    With `n * t == T` the burst is gapless, so Spuri's sporadically-periodic
    arrival curve collapses to a strict period of the INNER spacing. Checked on
    our own arrival curve rather than argued, because it explains two things at
    once: why `m_i = 1` on every real lane, and why `run_bursty.py` had to use
    CONSTRUCTED instances to reach `m_i > 1`.

    ⛔ It also marks the modelling assumption: if the hardware ever has idle gaps
    between frames, the burst parameters as written do not express that -- they
    express the densest case, which is the conservative one.
    """
    from bursty import BLane
    print("  --- our bursty lanes vs a plain period, on our own curve ---")
    ok = True
    for name, n, t, T in (("UART-rx", 10, 434, 4340), ("SPI-target", 16, 25, 400)):
        b = BLane(name, T, 2, 1, n=n, t=t)
        p = BLane(name, t, 2, 1)
        diff = [d for d in range(0, 3 * T) if b.N(d) != p.N(d)]
        print("    %-12s n*t = %d*%d = %d == T = %d ; curve mismatches over "
              "[0,%d): %d"
              % (name, n, t, n * t, T, 3 * T, len(diff)))
        ok = ok and not diff
    print("    => the burst model is IDENTICAL to Periodic(inner) here: %s"
          % ("confirmed" if ok else "*** NOT identical -- investigate ***"))
    return ok


def main() -> int:
    print()
    print("=" * 78)
    print("SPEC 1.4b -- third-party check of the SHIPPED five-lane numbers")
    print("=" * 78)
    src = find_pyrta()
    if not src:
        print("  *** pyRTA NOT FOUND. Set PYRTA_SRC to a clone's src/ directory:")
        print("        git clone https://github.com/PROSA-Project/pyRTA")
        print("        PYRTA_SRC=<clone>/src python model/a2/gate_pyrta.py")
        print("  Gate is RED: a foreign check that cannot run has not run.")
        return 1
    print("  pyRTA source: %s" % src)
    sys.path.insert(0, src)
    from response_time_analysis import edf                              # noqa
    from response_time_analysis.model import (WCET, Deadline,           # noqa
                                              FullyNonPreemptive, IdealProcessor,
                                              Periodic, Priority, Task, taskset)

    tasks, names, ours = [], [], []
    for i, (n, T, C, D, r) in enumerate(SPEC):
        # ⛔ Priority is an IDENTITY TAG, not a scheduling input: `edf.rta` reads
        # deadlines only. It is required because pyRTA filters interferers by
        # VALUE on a frozen dataclass, so two parameter-identical lanes would
        # both be excluded -- and UART-tx/UART-rx and SPI-tx/SPI-target ARE
        # parameter-identical pairs here.
        tasks.append(Task(Periodic(period=T), FullyNonPreemptive(WCET(C)),
                          Deadline(D), Priority(i)))
        names.append(n)
        ours.append(r)
    ts = taskset(*tasks)

    # ---- the footgun, checked mechanically rather than trusted ----------
    print()
    print("  --- interferer-count check (the identity footgun) ---")
    want = len(tasks) - 1
    dropped = 0
    for n, t in zip(names, tasks):
        k = len(list(ts.excluding_iter(t)))
        if k != want:
            dropped += 1
        print("    %-20s sees %d of %d interferers  %s"
              % (n, k, want, "ok" if k == want else "*** %d DROPPED ***" % (want - k)))
    if dropped:
        print("    *** ABORT: parameter-identical lanes were silently merged.")
        print("        Every bound below would be optimistic. This is why the")
        print("        count is asserted instead of the tags being trusted.")
        return 1
    print("    => no lane was merged; the task set pyRTA analysed is ours")

    # ---- the comparison ------------------------------------------------
    print()
    print("  --- pyRTA non-preemptive EDF, ideal uniprocessor ---")
    print("    %-20s %-6s %-8s %-8s %-8s %s"
          % ("lane", "D_i", "pyRTA", "ours", "agree", "busy window"))
    agree, rows = True, []
    for n, t, r_ours in zip(names, tasks, ours):
        sol = edf.rta(ts, t, IdealProcessor())
        R = getattr(sol.response_time_bound, "value", sol.response_time_bound)
        L = getattr(sol.busy_window_bound, "value", sol.busy_window_bound)
        D = getattr(t.deadline, "value", None)
        ok = (R == r_ours)
        agree = agree and ok
        rows.append((n, R, r_ours))
        print("    %-20s %-6s %-8s %-8d %-8s %s"
              % (n, D, R, r_ours, "yes" if ok else "*** NO ***", L))

    print()
    # direction matters more than agreement
    looser = [x for x in rows if x[1] > x[2]]
    tighter = [x for x in rows if x[1] < x[2]]
    if tighter:
        print("  ⛔⛔ OUR NUMBER IS SMALLER THAN pyRTA's ON: %s"
              % ", ".join(x[0] for x in tighter))
        print("      pyRTA computes a SUFFICIENT bound, so a smaller number from")
        print("      us is the FORBIDDEN direction -- possible unsoundness, not")
        print("      merely tightness. Resolve before quoting any r_i.")
    elif looser:
        print("  ⚠ our bound is LARGER than pyRTA's on: %s"
              % ", ".join(x[0] for x in looser))
        print("    Safe direction (we are pessimistic), but worth tightening.")
    print()
    eq = periodic_equivalence()
    print()
    print("=" * 78)
    ok = agree and eq and not tighter
    print("  GATE 1.4b: %s" % (
        "PASSED -- a third-party implementation of machine-verified theory\n"
        "  reproduces the shipped r_i exactly, at the real periods, with no\n"
        "  replica and no scaling. The shipped numbers are foreign-checked."
        if ok else "FAILED -- see above."))
    if ok:
        print()
        print("  ⚠ Still owed: EXACTNESS. pyRTA's bound is sufficient, not exact.")
        print("    `nptest` (Nasri & Brandenburg RTSS 2017) is exact on a")
        print("    uniprocessor and is the next escalation; it needs a C++14/TBB")
        print("    build under WSL and has not been run.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
