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

import lane_digest                                                 # noqa: E402
from bursty import TX, UART_RX, SPI_RX, response_time_b            # noqa: E402
import pyrta_bound                                                 # noqa: E402
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
#   S3   RE-BASELINED AT THE DERIVED JITTER. ⛔⛔ The previous literals
#        {10, 7, 3, 9, 5} were the J = 0 analysis -- and the table carried
#        J = 0 on every lane while the stated design point was always
#        "(C = 2, J_pipe = 1)". So those numbers were computed off an analysis
#        matching NEITHER 1.3 candidate. S3 derived J_pipe = 8 from
#        src/pe_engine.v's structure (see gate_cj_bounds.py), with I2C alone
#        carrying J_PIPE + L_JIT as the REACTIVE-J lane. Logged as an ERROR,
#        not a footnote.
#        ⭐ AND THIS GATE IS WHAT CAUGHT THE BUMP: it refused to interpret
#        anything once the typed answers stopped matching the table, which is
#        exactly the job of a hand-typed literal next to an imported parameter.
# ⭐⭐ RETYPED FOR THE J = 1 RE-BASELINE, and the gate caught the staleness
# itself: arm 0 reported all five lanes as drifted (table 11 / file 10, 8/7,
# 5/3, 10/9, 6/5) and aborted before touching pyRTA. That is the whole reason
# the answers are TYPED while the parameters are IMPORTED -- a gate that
# recomputed both sides would have silently re-blessed whatever the recurrence
# now produces.
# ⛔ The previous values {10, 7, 3, 9, 5} were the J = 0 analysis. The shipped
# table now carries its DERIVED J (1, and 2 on I2C for async capture), so these
# are the J = 1 answers: r = {11, 8, 5, 10, 6}, min margin 12.
# ⛔ RE-DERIVED AT C = 3, NOT RE-BLESSED. Every value below is the response
# time the recurrence now gives on the shipped table, and the table moved for a
# MEASURED reason: `docs/PREREG_C_SAT.md` pre-registered the minimum
# inter-dispatch spacing at 2, `test/run_csat.py` measured 3, and the old
# figure (`svc_cycles/svc_jobs` = 2.00) was the engine's OCCUPANCY per job
# rather than the SPACING between the jobs it can deliver. Ledger entry
# `65bc3c8114e5`.
# ⚠ THE SHIFT IS NOT UNIFORM: +5, +4, +2, +5, +3. It is not "add one per lane",
# because a larger C changes how many interfering instances fit inside each
# lane's window as well as its own service time. A table corrected by adding a
# constant would have been wrong on all five rows.
# ⛔⛔ RULING A2: THIS IS THE PUBLISHED VALUE, AND IT IS pyRTA's. Until ruling
# Z our recurrence and pyRTA agreed on all five lanes, so one literal served
# both. Z gave our recurrence Spuri's full candidate set (it had been searching
# too few offsets and could fall BELOW the exact worst case); it is now sound
# and on two lanes PESSIMISTIC, so the two separate and each gets its own pin.
EXPECTED_R = {"UART-tx 115200": 16,
              "SPI-tx 1 MHz": 12,
              "I2C 400 kHz": 7,
              "UART-rx 115200": 15,
              "SPI-target 1 MHz": 9}
# ⭐ OUR RECURRENCE ON THE SAME TABLE -- the cross-check, asserted >= pyRTA.
# The two gaps are NAMED and cited, not tolerated: TChecker on the scaled
# shapes (`jitter_instances.TIE_INSTANCES`, ruling Z4) gives truth = pyRTA under
# every tie rule, so these are our recurrence's pessimism at a deadline tie
# combined with blocking, not a missing case in pyRTA.
EXPECTED_OURS = {"UART-tx 115200": 16,
                 "SPI-tx 1 MHz": 12,
                 "I2C 400 kHz": 9,
                 "UART-rx 115200": 16,
                 "SPI-target 1 MHz": 9}
GAP_CITED = {"I2C 400 kHz": (2, "T-I2C / T-I2C-mirror"),
             "UART-rx 115200": (1, "T-URX / T-URX-mirror")}

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
        out.append((l.name, l.t, l.C, l.D, r_ours, EXPECTED_OURS.get(l.name)))
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
    # ⛔ SPEC A1 -- digest the set ACTUALLY ANALYSED. This gate is the one that
    # carried a hand-typed second table, so `used` here is `LANES`, the object
    # handed to the analyser, and not a re-digest of what was imported. A copy
    # would move `used` and leave `base` alone, which is the whole signature.
    lane_digest.announce("gate_pyrta.py", LANES)

    # ---- arm 0: OUR numbers vs the typed literal, before the tool ---------
    # ⛔ Run this FIRST and unconditionally. It needs no foreign tool, so if the
    # typed answers have drifted from the table we learn it even on a machine
    # with no pyRTA clone -- rather than hiding a stale literal behind a red
    # that looks like a missing dependency.
    print()
    print("  --- arm 0: OUR recurrence on the lane table vs its typed pin "
          "(no tool needed) ---")
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
    # ⭐⭐ RULING 2: pyRTA'S BOUND IS NOW THE PUBLISHED NUMBER, so its framing
    # comes from `pyrta_bound` -- the single implementation -- instead of being
    # rebuilt here. This gate's own private version used plain `Periodic`, and
    # when the shipped table was re-baselined to its derived J = 1 it reported
    # the J = 0 answers against ours on all five lanes. The interferer-count
    # footgun is asserted inside `pyrta_bound.bound`, on every delta it tries.
    print()
    print("  --- pyRTA non-preemptive EDF, ideal uniprocessor ---")
    print("    ⭐ PRIMARY BOUND (Ruling 2). Ours is the cross-check, and the")
    print("    requirement is DIRECTION (ours >= pyRTA), not exact agreement.")
    print("    %-20s %-6s %-8s %-8s %s"
          % ("lane", "D_i", "pyRTA", "ours", "direction"))
    rows = []
    for i, (n, _t, _C, D, r_ours, _typed) in enumerate(spec_rows()):
        R, err = pyrta_bound.bound(src, LANES, i)
        if R is None:
            print("    *** ABORT: %s: %s" % (n, err))
            return 1
        rows.append((n, R, r_ours))
        print("    %-20s %-6s %-8s %-8d %s"
              % (n, D, R, r_ours,
                 "exact" if R == r_ours else
                 ("ours +%d (safe)" % (r_ours - R) if r_ours > R
                  else "*** OURS SMALLER ***")))
    # ⛔⛔ RULING A2: THE VERDICT IS ON pyRTA, the published value. It must
    # reproduce EXPECTED_R exactly; ours must be >= it everywhere, and every
    # lane where ours is larger must be a NAMED gap of exactly the cited size.
    published_ok = all(R == EXPECTED_R[n] for n, R, _o in rows)
    gaps = {n: o - R for n, R, o in rows if o > R}
    gaps_ok = gaps == {n: g for n, (g, _c) in GAP_CITED.items()}
    print("    published (pyRTA) == EXPECTED_R on every lane: %s"
          % ("yes" if published_ok else "*** NO"))
    for n, (g, cite) in sorted(GAP_CITED.items()):
        print("    ours - pyRTA on %-16s = %s (cited %d: TChecker %s, truth = "
              "pyRTA)" % (n, gaps.get(n, 0), g, cite))
    if not gaps_ok:
        print("    *** the gap set %s is not the cited one" % gaps)
    agree = published_ok and gaps_ok

    print()
    # direction matters more than agreement
    # ⛔⛔ THESE TWO WERE SWAPPED, AND THE MESSAGES WENT WITH THEM.
    # rows are (name, pyRTA_r, our_r). The FORBIDDEN direction is OUR number
    # being SMALLER than pyRTA's sufficient bound, i.e. our_r < pyRTA_r, i.e.
    # x[2] < x[1]. The old code put `x[1] < x[2]` -- pyRTA smaller, so OURS
    # LARGER, the CONSERVATIVE case -- in a list called `tighter` and fired the
    # unsoundness alarm on it, while the genuinely unsound case landed in
    # `looser` and got "Safe direction (we are pessimistic)".
    # ⭐ THE VERDICT WAS SAVED ONLY BY `agree`, which demands exact equality and
    # so fails either way. So the gate worked FOR A REASON OTHER THAN THE ONE IT
    # STATED, and its diagnosis would have described a possible unsoundness as
    # safe. That is the defect this project keeps finding: a guard that passes,
    # or fires, for the wrong reason.
    ours_smaller = [x for x in rows if x[2] < x[1]]   # FORBIDDEN
    ours_larger  = [x for x in rows if x[2] > x[1]]   # safe, pessimistic
    if ours_smaller:
        print("  ⛔⛔ OUR NUMBER IS SMALLER THAN pyRTA's ON: %s"
              % ", ".join(x[0] for x in ours_smaller))
        print("      pyRTA computes a SUFFICIENT bound, so a smaller number from")
        print("      us is the FORBIDDEN direction -- possible unsoundness, not")
        print("      merely tightness. Resolve before quoting any r_i.")
    elif ours_larger:
        print("  ⚠ our bound is LARGER than pyRTA's on: %s"
              % ", ".join(x[0] for x in ours_larger))
        print("    Safe direction (we are pessimistic). Each gap is cited above")
        print("    to the TChecker shape that shows pyRTA is the exact one.")
    print()
    eq = periodic_equivalence()
    print()
    print("=" * 78)
    ok = agree and eq and not ours_smaller
    print("  GATE 1.4b: %s" % (
        "PASSED -- the PUBLISHED r_i are pyRTA's (a third-party implementation\n"
        "  of machine-verified theory) at the real periods, with no replica and\n"
        "  no scaling; our recurrence is >= them on every lane, its two gaps\n"
        "  cited to TChecker (ruling A2)."
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
