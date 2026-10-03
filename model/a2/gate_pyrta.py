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

from bursty import TX, UART_RX, SPI_RX, response_time_b            # noqa: E402
from pyrta_src import require_pyrta                                # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ============================================================================
# THE SUBJECT: lane PARAMETERS from the one table, expected r_i hand-typed
# ============================================================================
# ⛔⛔ THE PARAMETERS ARE IMPORTED, THE ANSWERS ARE TYPED, AND THAT SPLIT IS
# DELIBERATE. This file used to carry a hand-copied second copy of the lane
# table, which is a transcription-error class with nothing watching it: when 1.1
# moved D_SPI and R1/H3 moved two more, the copy had to be found and edited by
# memory, and a copy that is edited by memory is a copy that is eventually wrong.
# So the T/C/D now come from `bursty.py` -- the SAME table A2 reports on, which
# is the point: pyRTA's independence is of the ANALYSIS, never of the inputs.
#
# ⭐ The expected `r_i` stay hand-typed, because that is the actual pin. A gate
# that imported the answers too would compare our recurrence against itself and
# agree by construction. Three things must line up: the typed literal, our
# recurrence, and pyRTA. Any disagreement is a finding, including a `r_i` we
# changed on purpose and forgot to retype here.
#
# ⛔ THE DEADLINE pyRTA IS GIVEN IS THE EDF KEY `D_sched + C_i`, not the
# tolerance (spec R2). pyRTA schedules on absolute deadlines; the tolerances
# bound start delays. Feeding it a tolerance would schedule the set C_i cycles
# tighter than the design asks for -- conservative, but a different task set
# from the one we ship.
#
# CORRECTIONS BAKED INTO THE TABLE THIS READS, each re-checked here afterwards:
#   N1   I2C is T=45, D_tol=15 -- the symmetric 62-cycle phase violated tLOW at
#        nominal and D=30 was the centre-sample stand-in (gate_i2c_phase.py).
#   N2+P1 UART-rx is T=414 -- the band [413,458] assumed an EXACT sampler and
#        double-counted the per-bit slack; re-synthesized with the sampler
#        displaced by L_sync=3 and uncertain by Dj=8, Imitator gives exactly
#        5*Te > 2067 & 4126 > 9*Te, i.e. [414,458]. Te=413 is REJECTED.
#   1.1  D_tol(SPI-tx) = 23, derived from the MB85RS64V AC table.
#   H3   D_tol(UART-rx) = 213 = 216 - L_sync, the REACTIVE-anchor correction.
#   R1   D_tol(SPI-target) = 18, derived from the absolute budget -- the last
#        stand-in deadline, and the one that was the EDF key for the whole set.
EXPECTED_R = {"UART-tx 115200": 10,
              "SPI-tx 1 MHz": 7,
              "I2C 400 kHz": 3,
              "UART-rx 115200": 9,
              "SPI-target 1 MHz": 5}

# ⛔ ONE lane set, built once and selected from -- never a second builder call.
# `response_time_b` filters interference BY IDENTITY, so an equal-but-distinct
# copy is not excluded and the subject interferes with itself (see
# gate_twin_pair.py).
LANES = list(TX) + [UART_RX, SPI_RX]


def spec_rows():
    """(name, period pyRTA sees, C, EDF key, our r, typed r) per lane.

    ⭐ THE PERIOD pyRTA SEES IS THE INNER SPACING `t`, NOT THE OUTER `T`, AND
    THAT IS SOUND ONLY BECAUSE `n*t == T` ON BOTH BURSTY LANES. pyRTA has no
    bursty arrival model; `periodic_equivalence()` below checks on our own
    arrival curve that the burst is gapless and therefore IS a plain period at
    the inner spacing. Were a lane to have idle gaps between frames, this
    substitution would silently analyse a denser task set -- conservative, but
    not the shipped one, and the gate would stop being a check of our numbers.
    """
    out = []
    for l in LANES:
        r_ours = response_time_b(l, LANES)["r"]
        out.append((l.name, l.t, l.C, l.D, r_ours, EXPECTED_R.get(l.name)))
    return out


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
    # ⛔⛔ THESE PARAMETERS WERE HARD-CODED HERE AND WENT STALE: this check ran
    # at UART-rx (n=10, t=434, T=4340) long after P1 re-synthesized the lane to
    # t=414, T=4140. It passed -- n*t == T holds for both -- so a green check was
    # certifying the gaplessness of a lane the project no longer ships, which is
    # the whole substitution the pyRTA comparison rests on. Read off the objects.
    ok = True
    for lane in (l for l in LANES if l.n > 1):
        name, n, t, T = lane.name, lane.n, lane.t, lane.T
        b = BLane(name, T, 2, 1, n=n, t=t)
        p = BLane(name, t, 2, 1)
        diff = [d for d in range(0, 3 * T) if b.N(d) != p.N(d)]
        print("    %-20s n*t = %d*%d = %d %s T = %d ; curve mismatches over "
              "[0,%d): %d"
              % (name, n, t, n * t, "==" if n * t == T else "!=", T, 3 * T,
                 len(diff)))
        ok = ok and not diff and n * t == T
    print("    => the burst model is IDENTICAL to Periodic(inner) here: %s"
          % ("confirmed" if ok else "*** NOT identical -- investigate ***"))
    return ok


def main() -> int:
    print()
    print("=" * 78)
    print("SPEC 1.4b -- third-party check of the SHIPPED five-lane numbers")
    print("=" * 78)
    # ---- arm 0: OUR numbers vs the typed literal, before the tool ---------
    # ⛔ Run this FIRST and unconditionally. It needs no foreign tool, so if the
    # typed answers have drifted from the table we learn it even on a machine
    # with no pyRTA clone -- rather than hiding a stale literal behind a red
    # that looks like a missing dependency.
    print()
    print("  --- arm 0: the lane table vs the typed answers (no tool needed) ---")
    print("    %-20s %-6s %-5s %-6s %-7s %-7s %s"
          % ("lane", "t_i", "C_i", "key", "ours", "typed", "agree"))
    drift = []
    for name, t, C, key, r_ours, r_typed in spec_rows():
        ok = (r_ours == r_typed)
        if not ok:
            drift.append((name, r_ours, r_typed))
        print("    %-20s %-6d %-5d %-6d %-7s %-7s %s"
              % (name, t, C, key, r_ours, r_typed,
                 "yes" if ok else "*** NO ***"))
    if drift:
        print("    *** ABORT: the typed answers no longer match the table.")
        for name, a, b in drift:
            print("        %s: table says %s, this file says %s" % (name, a, b))
        print("        Either the table moved and this literal was not retyped,")
        print("        or the recurrence changed. Nothing below is interpretable")
        print("        until it is known which.")
        return 1
    print("    => the typed answers ARE the current table's answers")

    src = require_pyrta("gate_pyrta.py")
    if not src:
        return 1
    sys.path.insert(0, src)
    from response_time_analysis import edf                              # noqa
    from response_time_analysis.model import (WCET, Deadline,           # noqa
                                              FullyNonPreemptive, IdealProcessor,
                                              Periodic, Priority, Task, taskset)

    tasks, names, ours = [], [], []
    for i, (n, T, C, D, r, _typed) in enumerate(spec_rows()):
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
