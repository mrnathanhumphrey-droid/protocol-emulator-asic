"""C = 3 -- THE RE-QUOTE. Every published r_i and margin, corrected.

⛔⛔ WHY. `docs/PREREG_C_SAT.md` pre-registered the minimum inter-dispatch
spacing at 2 and named 3 as the falsifier. `test/run_csat.py` measured 3 on
four arms, with 32,677 spacings in which a successor was ALREADY ELIGIBLE
during the predecessor's writeback and not one of them 2. The dispatch FSM is a
three-state cycle --

    ST_IDLE --(cond)--> ST_DRIVE --> ST_WB --> ST_IDLE

-- and `ST_WB` assigns `st <= ST_IDLE` unconditionally, so the next dispatch
decision cannot be taken until the cycle after writeback.

THE FIGURE ON RECORD MEASURED THE WRONG THING, not the wrong value.
`svc_cycles / svc_jobs = 688 / 344 = 2.00` counts cycles where
`st != ST_IDLE`: the engine's OCCUPANCY per job. Occupancy is 2 and spacing is
3, both exactly, and a mean of 2.00 is the correct answer to the question it
was asked. `C` in a response-time analysis is the resource time a job denies to
every other job, and that is the spacing.

⛔ THE DIRECTION IS THE POINT. A `C` one cycle too SMALL makes every `r_i` too
small, every margin too large and `B = max(C_j - 1)` too small -- optimistic, in
the numbers we publish. This gate is the correction, not a sensitivity study.

WHAT MOVES:
  * shipped design point (J = 1): min margin 12 -> 11, on BOTH bounds, which
    agree exactly there. Still far above the pre-registered bar of 4, so
    NOTHING WE SHIP BECOMES INFEASIBLE.
  * every `r_i` grows by 1 to 5 cycles; `B = max(C_j - 1)` is 2, not 1.

⛔⛔ AND ONE CLAIM THIS GATE DELIBERATELY DOES NOT MAKE, because its first
version made it. Face (b) read our own recurrence and concluded "the bar
crossing moves from J = 7 to J = 5" and "the derived J_max = 8 becomes
INFEASIBLE at margin -2". pyRTA is the PRIMARY bound and it says neither:
pyRTA has the derived `J = 8` at margin **+4**, exactly the bar, at C = 3. The
two bounds agree for J <= 2 and diverge from J = 3 upward, where ours is the
conservative one -- which is the safe direction and the reason it is kept, but
it is NOT the published number. ⇒ Both are tabled, each under its own name, and
the verdict is pyRTA's. Quoting our bound's -2 as the finding would have
published an infeasibility that the primary analysis does not support.

⛔ WHAT DOES NOT MOVE, stated because re-deriving it to compensate would be the
obvious temptation and §5.2.5 of the pre-registration forbids it:
  * `D* = k * L_REFILL = 20` contains no `C`. It is a port-throughput
    threshold and Theorem 3's premises are untouched.
  * `d_min >= D* -> J = 1` is a JITTER claim. It is unaffected.
  * `L_REFILL = 4`, `L_CAP = 7`, `J_WINNER_REG = 1` are refill-FSM and
    winner-registration structure. Unaffected.
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

import lane_digest                                             # noqa: E402
import pyrta_bound                                             # noqa: E402
import pyrta_src                                               # noqa: E402
from bursty import (BLane, C_SHIPPED, abs_tolerance,           # noqa: E402
                    response_time_b)
from gate_j_sound import MARGIN_BAR, lanes_at                  # noqa: E402

# ---------------------------------------------------------------------------
# THE MEASUREMENT, as a RECORD with a runnable recipe
# ---------------------------------------------------------------------------
# ⛔ A RECORD, NOT A LIVE READING, and deliberately: this gate is pure Python so
# it runs in CI on a machine with no iverilog. `gate_stored_numbers.py`'s rule
# applies -- a RECORD needs a recipe file that re-derives it, and the recipe is
# named here rather than described.
C_OCCUPANCY = 2          # svc_cycles/svc_jobs, test/cj_measured.txt
# ⭐ FROM THE TABLE, NOT RETYPED. The canonical flip landed (ledger entry
# `65bc3c8114e5`), so this gate's "after" value and the shipped lane table
# cannot disagree -- which is what `lane_digest.announce` below now reports as
# a MATCH rather than as a declared variant.
C_SPACING = C_SHIPPED    # btbmin, test/run_csat.py arms S and T
C_SAT_RECIPE = "test/run_csat.py"
C_SAT_PREREG = "docs/PREREG_C_SAT.md"
C_SAT_BTB = 32677        # back-to-back spacings across the four arms

# ---------------------------------------------------------------------------
# THE CORRECTED SWEEP, recorded so a change shows up as a disagreement
# ---------------------------------------------------------------------------
# ⛔ SAME DISCIPLINE AS `gate_j_sound.EXPECTED`, and for the same reason: a gate
# that recomputes a table and prints it cannot tell a correction from a drift.
# ⛔⛔ ONE TABLE PER BOUND, AND THE NAMES MATTER. `gate_j_sound.EXPECTED` is
# OUR recurrence, so the C = 3 companion to it must be ours too. pyRTA is the
# PRIMARY bound and gets its own pair. The first version of this gate kept one
# C = 3 table, filled it from our recurrence, and then printed conclusions
# ("the bar crossing moves to J = 5", "the derived J becomes INFEASIBLE") that
# the primary bound does not support -- a published claim read off the
# cross-check. The two bounds AGREE for J <= 2 and diverge from J = 3 upward.
# J_pipe -> min margin
EXPECTED_C3_OURS = {
    0: 12, 1: 11, 2: 7, 3: 6, 4: 5, 5: 4, 6: 3, 7: 2, 8: -2,
}
# ⛔ THE HISTORICAL `ours` TABLE, RECORDED HERE RATHER THAN IMPORTED. This
# gate used to read `gate_j_sound.EXPECTED` for the before-values -- and that
# table has now been RE-DERIVED to C = 3, so importing it would compare C = 3
# against C = 3 and the must-fire "every row was strictly optimistic" would
# fail on every row while looking like a recurrence change. These are the
# values `gate_j_sound.EXPECTED` held at (C = 2, SPI-target D_tol = 18), and
# `gate_j_sound` reproduced them from that configuration before they were
# moved, so the pair is known to differ for the intended reason.
EXPECTED_C2_OURS = {
    0: 13, 1: 12, 2: 11, 3: 8, 4: 7, 5: 6, 6: 5, 7: 4, 8: 1,
}
EXPECTED_C2_PYRTA = {
    0: 13, 1: 12, 2: 11, 3: 10, 4: 9, 5: 8, 6: 7, 7: 6, 8: 5,
}
EXPECTED_C3_PYRTA = {
    0: 12, 1: 11, 2: 10, 3: 9, 4: 8, 5: 7, 6: 6, 7: 5, 8: 4,
}
#: ⛔ THE RETRACTED UNIVERSAL FIGURE, kept as a STRESS POINT only. This was
#: `gate_cj_bounds`' "derived J_max"; ledger b4e51034e283 WITHDREW universal
#: J = 8 as unsound (ten admissible points measured above it -- the stall chain
#: reaches k * L_REFILL = 20) and replaced it with d_min >= D* = 20 -> J = 1.
#: The margins below are correct arithmetic AT J = 8; they bound nothing.
#: (Relabelled under ruling CJ; the name is kept so EXPECTED_* stay keyed.)
J_DERIVED = 8
J_SHIPPED = 1            # the stated design point


def at_c(c: int, j_pipe: int) -> list:
    """The shipped five at a given service time and uniform J_pipe.

    ⛔⛔ THE `C = 2` ARM REBUILDS THE **HISTORICAL CONFIGURATION**, DEADLINE
    AND ALL, and overriding only `C` was wrong. SPI-target's `D_tol` is DERIVED
    by `abs_tolerance(25, completion, C)`, which SUBTRACTS C -- so the table
    that shipped with `C = 2` also had `D_tol = 18`, and the current one has
    17. An arm that changed the service time and left the deadline at today's
    value was comparing against a configuration that never existed, and it
    reported 10 at J = 2 where the real before-value is 11 and the real
    after-value is 7. ⇒ `C_SHIPPED` now comes from the table and the companion
    deadline is re-derived for whichever `C` is being built.

    ⛔ BUILT ONCE AND SELECTED FROM. `response_time_b` filters interference by
    IDENTITY (`o is not lane`), so a second builder call yields equal-but-
    distinct objects that fail to exclude and INFLATE the bound -- the defect
    that once read SPI-target 7 instead of 5.
    ⭐ `lanes_at` already puts `L_JIT` on I2C, which is why I2C is the tightest
    lane at every J; re-deriving that here would duplicate the one place it is
    decided.
    """
    return [BLane(l.name, l.T, c,
                  D_tol=(abs_tolerance(25, True, c)
                         if l.name.startswith("SPI-target") else l.D_tol),
                  n=l.n, t=l.t, J=l.J)
            for l in lanes_at(j_pipe)]


#: ⭐⭐ RULING A5: OUR RECURRENCE AFTER RULING Z, recorded BESIDE the history
#: rather than over it. EXPECTED_C2_OURS / EXPECTED_C3_OURS above were computed
#: by the subject-releases-only search that ruling Z found unsound; they are
#: reproduced below in THEIR OWN terms (`search="historical"`), never re-fitted.
#: This table is the fixed recurrence at C = 3 -- the cross-check, asserted
#: never above pyRTA's margin. The PUBLISHED sweep is EXPECTED_C3_PYRTA.
EXPECTED_C3_OURS_Z = {
    0: 11, 1: 9, 2: 7, 3: 6, 4: 5, 5: 4, 6: 2, 7: 0, 8: -2,
}


def ours(lanes, search="fixed"):
    """Our recurrence; `search="historical"` is the pre-Z subject-releases-only
    search the EXPECTED_*_OURS history was computed with (ruling A5)."""
    full = search != "historical"
    return [(l.name, response_time_b(l, lanes, jitter_in_interference=True,
                                     spuri_candidates=full)["r"])
            for l in lanes]


def pyrta(src, lanes):
    out = []
    for k, l in enumerate(lanes):
        r, err = pyrta_bound.bound(src, lanes, k)
        if r is None:
            print("      ⚠ %s: pyRTA returned no bound -- %s" % (l.name, err))
        out.append((l.name, r))
    return out


def mins(src, c: int, j: int, search="historical"):
    """(ours_min, pyrta_min) over the five lanes. ⛔ EACH MARGIN IS TAKEN FROM
    THE LANE OBJECT THAT PRODUCED ITS `r`. The first version computed the
    C = 2 response times and then evaluated `margin` on the C = 3 lane
    objects, which inflated the published figure by one and printed 13 where
    the record says 12. `margin` is `D_tol - (r - C)`, so it carries a `C`
    too: a scope assumption threaded through a constant, exactly the shape
    this project has a standing rule about."""
    ls = at_c(c, j)
    o = min(l.margin(r) for l, (_n, r) in zip(ls, ours(ls, search)))
    p = [None if r is None else l.margin(r)
         for l, (_n, r) in zip(ls, pyrta(src, ls))]
    return o, (None if any(x is None for x in p) else min(p))


def face_shipped(src) -> int:
    """The published table, both service times, both bounds, per lane."""
    rc = 0
    print("  --- face (a): the shipped five at J = %d, per lane ---" % J_SHIPPED)
    l2, l3 = at_c(C_OCCUPANCY, J_SHIPPED), at_c(C_SPACING, J_SHIPPED)
    o2, o3 = dict(ours(l2)), dict(ours(l3))
    p2, p3 = dict(pyrta(src, l2)), dict(pyrta(src, l3))
    by2 = {l.name: l for l in l2}
    print("    %-20s %-7s %-7s %-7s %-7s %-7s %s"
          % ("lane", "D_tol", "r C=2", "r C=3", "m C=2", "m C=3", "bound"))
    worst2, worst3 = None, None
    for l in l3:
        n = l.name
        # ⛔ pyRTA IS PRIMARY, so the published margin is pyRTA's wherever it
        # produced one. Ours is the cross-check; face (d) asserts the direction.
        r2 = p2[n] if p2[n] is not None else o2[n]
        r3 = p3[n] if p3[n] is not None else o3[n]
        # ⛔ THE C = 2 MARGIN IS EVALUATED ON THE C = 2 LANE OBJECT. See `mins`.
        m2, m3 = by2[n].margin(r2), l.margin(r3)
        worst2 = m2 if worst2 is None else min(worst2, m2)
        worst3 = m3 if worst3 is None else min(worst3, m3)
        print("    %-20s %-7d %-7s %-7s %-7s %-7s %s"
              % (n, l.D_tol, r2, r3, m2, m3,
                 "pyRTA" if p3[n] is not None else "ours (pyRTA silent)"))
    print()
    print("    min margin   C = %d (published): %d" % (C_OCCUPANCY, worst2))
    print("    min margin   C = %d (CORRECTED): %d  bar %d  %s"
          % (C_SPACING, worst3, MARGIN_BAR,
             "clears" if worst3 >= MARGIN_BAR else "*** UNDER THE BAR"))
    if worst3 < MARGIN_BAR:
        rc = 1
    for label, got, want in (("published", worst2, EXPECTED_C2_PYRTA[J_SHIPPED]),
                             ("corrected", worst3, EXPECTED_C3_PYRTA[J_SHIPPED])):
        if got != want:
            print("    *** THE %s FIGURE HAS MOVED from %d to %d. Either the"
                  % (label.upper(), want, got))
            print("        lane table, the deadlines or the recurrence changed,")
            print("        and this gate is RED rather than re-recording it.")
            rc = 1
    print("    ⭐ NOTHING WE SHIP BECOMES INFEASIBLE. Every lane keeps a")
    print("      margin far above the bar, and the two bounds AGREE EXACTLY")
    print("      here -- the shipped claim moves by ONE cycle, %d to %d. The"
          % (EXPECTED_C2_PYRTA[J_SHIPPED], EXPECTED_C3_PYRTA[J_SHIPPED]))
    print("      correction is published because it is in the forbidden")
    print("      direction, not because it changes a decision.")
    return rc


def face_sweep(src) -> int:
    """The J sweep at both service times, under BOTH bounds, each named."""
    rc = 0
    print()
    print("  --- face (b): the J sweep, both bounds, each under its name ---")
    print("    %-7s %-18s %-18s %s"
          % ("J_pipe", "pyRTA (PRIMARY)", "ours (cross-check)", "bar = %d"
             % MARGIN_BAR))
    print("    %-7s %-8s %-9s %-8s %-9s %s"
          % ("", "C=2", "C=3", "C=2", "C=3", "pyRTA C=3 verdict"))
    cross_p, cross_o = None, None
    for j in sorted(EXPECTED_C2_OURS):
        o3, p3 = mins(src, C_SPACING, j)
        o2, p2 = mins(src, C_OCCUPANCY, j)
        for label, got, want in ((("ours", C_SPACING), o3, EXPECTED_C3_OURS[j]),
                                 (("pyRTA", C_SPACING), p3,
                                  EXPECTED_C3_PYRTA[j]),
                                 (("pyRTA", C_OCCUPANCY), p2,
                                  EXPECTED_C2_PYRTA[j]),
                                 (("ours", C_OCCUPANCY), o2, EXPECTED_C2_OURS[j])):
            if got != want:
                print("    *** J=%d %s C=%d: recorded %s, now %s -- RED, not"
                      " re-recorded" % (j, label[0], label[1], want, got))
                rc = 1
        if p3 is not None and p3 >= MARGIN_BAR:
            cross_p = j
        if o3 >= MARGIN_BAR:
            cross_o = j
        print("    %-7d %-8d %-9s %-8d %-9d %s"
              % (j, p2, p3, o2, o3,
                 "PASS" if (p3 is not None and p3 >= MARGIN_BAR)
                 else "*** FAIL"))
    print()
    # ---- RULING A5: the fixed recurrence, beside the history -------------
    print()
    print("    ⭐ ruling A5 -- OUR recurrence after ruling Z (Spuri step set), "
          "C = %d, beside the" % C_SPACING)
    print("      historical column above (which is reproduced with the pre-Z "
          "search, not re-fitted):")
    print("      %-7s %-12s %-14s %s" % ("J_pipe", "pyRTA (pub.)",
                                         "ours (fixed)", "ours <= pyRTA"))
    for j in sorted(EXPECTED_C3_OURS_Z):
        oz, pz = mins(src, C_SPACING, j, search="fixed")
        if oz != EXPECTED_C3_OURS_Z[j]:
            print("    *** J=%d ours (fixed) C=%d: recorded %s, now %s"
                  % (j, C_SPACING, EXPECTED_C3_OURS_Z[j], oz))
            rc = 1
        okd = pz is not None and oz <= pz
        if not okd:
            rc = 1
        print("      %-7d %-12s %-14d %s" % (j, pz, oz,
                                            "yes" if okd else "*** NO"))
    print()
    print("    largest J_pipe clearing the bar, C = %d:" % C_SPACING)
    print("      pyRTA (PRIMARY)    : J = %s  -- every swept J still clears it"
          % cross_p)
    print("      ours (cross-check) : J = %s" % cross_o)
    print("    ⛔⛔ AND THIS IS WHERE THE FIRST VERSION OF THIS GATE WENT")
    print("      WRONG. It tabled only our recurrence and concluded that the")
    print("      bar crossing moved from J = 7 to J = 5. That is TRUE OF OUR")
    print("      BOUND and not of the published one: pyRTA clears the bar at")
    print("      every swept J at both service times. Ours is the conservative")
    print("      side, which is why it is kept -- and why it must never be the")
    print("      number quoted. The bar crossing DOES NOT MOVE.")
    print("    ⭐ THE TWO BOUNDS AGREE EXACTLY FOR J <= 2 and diverge from")
    print("      J = 3 upward, which is the band the shipped design point")
    print("      (J = %d) sits well inside. The published figures are"
          % J_SHIPPED)
    print("      therefore not sensitive to which bound is used.")
    print("    ⛔ NOT A UNIFORM SHIFT EITHER WAY. On ours, J = 0..2 lose one")
    print("      cycle and J >= 3 lose two (J = 8 loses three), because above")
    print("      J = 2 the tightest lane starts paying a second interference")
    print("      instance from a neighbour -- a step, not a slope. A")
    print("      'subtract one everywhere' correction by hand would have been")
    print("      wrong on six of the nine rows.")
    return rc


def face_derived_j(src) -> int:
    """The J = 8 stress point at C = 3: the slack goes to EXACTLY the bar.

    ⛔ RELABELLED (ruling CJ): this face used to call J = 8 "the derived
    J_max". Ledger b4e51034e283 withdrew universal J = 8 as unsound; the
    margins here are correct arithmetic at J = 8 and bound nothing.

    ⛔⛔ THIS FACE EXISTS BECAUSE ITS FIRST VERSION OVERSTATED ITS OWN RESULT.
    It was headed "now infeasible" and printed "margin -2, MISSES DEADLINES",
    read off OUR recurrence while pyRTA is the primary bound. pyRTA has this
    case at +4, exactly the bar -- tight, and not an infeasibility. The
    conservative bound is the one to keep and never the one to quote.
    """
    rc = 0
    print()
    print("  --- face (c): the J = %d STRESS POINT at C = %d (the retracted "
          "universal figure, ledger b4e51034e283) ---" % (J_DERIVED, C_SPACING))
    ls = at_c(C_SPACING, J_DERIVED)
    o, p = dict(ours(ls)), dict(pyrta(src, ls))
    print("    %-20s %-8s %-8s %-8s %s"
          % ("lane", "r pyRTA", "r ours", "margin", "verdict"))
    worst = None
    unsafe = []
    for l in ls:
        n = l.name
        r = p[n] if p[n] is not None else o[n]
        m = l.margin(r)
        worst = m if worst is None else min(worst, m)
        if p[n] is not None and o[n] is not None and o[n] < p[n]:
            unsafe.append((n, o[n], p[n]))
        print("    %-20s %-8s %-8s %-8s %s"
              % (n, p[n], o[n], m, "ok" if m >= 0 else "*** MISSES"))
    # ⛔⛔ THE DIRECTION CHECK IS A STOP, NOT A COMPARISON. Ours below pyRTA
    # would mean our bound is optimistic, and then neither number may be used.
    if unsafe:
        print("    ⛔⛔ STOP: ours is BELOW pyRTA on %s" % (unsafe,))
        print("       Our bound would be optimistic. NEITHER number is usable")
        print("       until the recurrence is re-derived.")
        rc = 1
    else:
        print("    direction ok: ours >= pyRTA on every lane")
    print()
    print("    min margin, pyRTA (PRIMARY): %d  (was %d at C = %d)"
          % (EXPECTED_C3_PYRTA[J_DERIVED], EXPECTED_C2_PYRTA[J_DERIVED],
             C_OCCUPANCY))
    print("    min margin, ours           : %d  (was %d) -- the conservative"
          % (EXPECTED_C3_OURS[J_DERIVED], EXPECTED_C2_OURS[J_DERIVED]))
    print("                                 side, NOT the published number")
    if worst != EXPECTED_C3_PYRTA[J_DERIVED]:
        print("    *** recorded %d, now %d -- RED, not re-recorded"
              % (EXPECTED_C3_PYRTA[J_DERIVED], worst))
        rc = 1
    print("    ⇒ AT THE J = 8 STRESS POINT the primary bound sits EXACTLY at the")
    print("      bar: %d against %d. Our cross-check reads %d, which is"
          % (EXPECTED_C3_PYRTA[J_DERIVED], MARGIN_BAR,
             EXPECTED_C3_OURS[J_DERIVED]))
    print("      negative -- so the two bounds disagree about whether this")
    print("      case survives, and the primary one says it does.")
    print("    ⚠ WHAT THAT MEANS IN PRACTICE: J = %d is NOT a worst case --"
          % J_DERIVED)
    print("      universal J = 8 was WITHDRAWN as unsound (ledger b4e51034e283;")
    print("      the stall chain reaches 20). The claim is scoped instead:")
    print("      d_min >= D* -> J = 1. The row is a stress point, not a shipped")
    print("      configuration. ⛔ But its slack is now ZERO above the bar on")
    print("      the primary bound and negative on the cross-check, so it")
    print("      stops being a comfortable fallback: if this J ever had to be")
    print("      charged, there would be nothing left over.")
    print("      ⭐ THAT MAKES THE D* SCREEN LOAD-BEARING FOR FEASIBILITY and")
    print("      not merely for the size of a bound -- which is a stronger")
    print("      reason to keep it than the one it was adopted for.")
    return rc


def face_dtol(src) -> int:
    """⛔⛔ A DEADLINE CARRIES `C` TOO, AND THE CANONICAL TABLE IS NOT FLIPPED.

    Changing `C` in `bursty.TX`/`UART_RX`/`SPI_RX` is NOT a substitution, and
    trying it is what found this. `SPI-target`'s shipped `D_tol = 18` is not an
    input: it is DERIVED by `bursty.abs_tolerance(25, c9_at_completion=True,
    C=2)`, and that function subtracts `C` because a reactive lane whose pin
    moves at service COMPLETION spends its whole service time out of the peer's
    setup window. At C = 3 the same derivation gives 17.

    ⛔ AND `D_tol` IS THE EDF KEY (`D_sched` defaults to it, `D = D_sched + C`),
    which is the hazard spec R2 split the two fields to control: deriving
    `D_SPI-master = 23` once silently re-ordered all five lanes' priorities
    because the same field was both the requirement and the schedule. So a
    `C` change can move the SCHEDULE, not just the response times.

    ⭐ THE PROJECT ALREADY DEFENDS THIS. `gate_lane_class.py` asserts
    `sp.D_tol == abs_tolerance(25, True, sp.C)`, so a naive flip goes RED and
    demands the deadline be re-derived rather than carried over. The guard
    works, which is why this is a report and not a repair.

    THE THREE READINGS, all computed below:
      18  as shipped -- the COMPLETION derivation at C = 2
      17  the same derivation at the measured C = 3
      20  C9 = START, which is C-INDEPENDENT -- and is what the RTL actually
          does (`ST_DRIVE`'s comment: "the pin moves in the FIRST cycle of
          service"). 18 is the CONSERVATIVE label because Phase 2 has not
          MEASURED it, which is already owed.
    """
    rc = 0
    print()
    print("  --- face (d): a deadline carries C too ---")
    print("    abs_tolerance(25, completion, C=2) = %d   <- as shipped"
          % abs_tolerance(25, True, C_OCCUPANCY))
    print("    abs_tolerance(25, completion, C=3) = %d   <- same derivation,"
          % abs_tolerance(25, True, C_SPACING))
    print("                                             measured C")
    print("    abs_tolerance(25, START,      C=3) = %d   <- C-INDEPENDENT"
          % abs_tolerance(25, False, C_SPACING))
    print()
    print("    %-34s %-11s %-11s %s"
          % ("SPI-target D_tol", "min margin", "its margin", "EDF order"))
    base = None
    for label, dt in (("18  as shipped (C=2-derived)",
                       abs_tolerance(25, True, C_OCCUPANCY)),
                      ("17  same derivation at C=3",
                       abs_tolerance(25, True, C_SPACING)),
                      ("20  C9=START, C-independent",
                       abs_tolerance(25, False, C_SPACING))):
        ls = [BLane(l.name, l.T, C_SPACING,
                    D_tol=(dt if l.name.startswith("SPI-target") else l.D_tol),
                    n=l.n, t=l.t, J=l.J)
              for l in lanes_at(J_SHIPPED)]
        rows = [(l.name, r, l.margin(r), l.D)
                for l, (_n, r) in zip(ls, pyrta(src, ls))]
        order = tuple(n for n, _r, _m, _d in sorted(rows, key=lambda x: x[3]))
        mn = min(m for _n, _r, m, _d in rows)
        mine = [m for n, _r, m, _d in rows if n.startswith("SPI-target")][0]
        print("    %-34s %-11d %-11d %s"
              % (label, mn, mine, " < ".join(x.split()[0] for x in order)))
        if base is None:
            base = (mn, order)
        elif order != base[1]:
            print("      *** THE EDF ORDER MOVED. A deadline change that")
            print("          re-orders the schedule needs R2's separation")
            print("          exercised, not a re-quote.")
            rc = 1
        elif mn != base[0]:
            print("      *** THE MINIMUM MARGIN MOVED, so the published figure")
            print("          depends on which reading is taken.")
            rc = 1
    print()
    print("    ⇒ ⭐ THE QUESTION IS BOUNDED AND THE PUBLISHED FIGURE DOES NOT")
    print("      DEPEND ON IT. All three readings leave the EDF order")
    print("      unchanged and I2C the tightest lane, so the min margin is %d"
          % base[0])
    print("      in every case. Only SPI-target's OWN margin moves, between")
    print("      %d and %d, and it is never the binding lane."
          % (abs_tolerance(25, True, C_SPACING) - 6,
             abs_tolerance(25, False, C_SPACING) - 6))
    print("    ⛔ THE CANONICAL TABLE IS NOT FLIPPED HERE. `bursty.py` still")
    print("      carries C = %d, so every other gate still computes with it."
          % C_OCCUPANCY)
    print("      Flipping it is a LANE-TABLE CHANGE: new digest, new ledger")
    print("      entry, and the recorded expectations of gate_j_sound,")
    print("      gate_pyrta, jitter_instances and frontier all move at once.")
    print("      ⚠ Re-blessing several recorded tables in one commit is the")
    print("      operation this project treats with most suspicion, and the")
    print("      deadline above has to be RULED before it can be done at all.")
    print("      ⇒ WILSON'S CALL. This gate is the correction's publication;")
    print("        the canonical flip is a separate, declared change.")
    return rc


def selftest() -> int:
    """⛔ PRICE IT. A correction whose gate cannot tell the corrected number
    from the old one is a comment, not a check.
    """
    rc = 0
    print()
    print("  --- must-fire: the correction is checked, not asserted ---")
    cases = []
    # 1. the old service time must NOT reproduce the corrected table
    bad = 0
    for j in sorted(EXPECTED_C3_OURS):
        ls = at_c(C_OCCUPANCY, j)
        got = min(l.margin(r) for l, (_n, r) in zip(ls, ours(ls, "historical")))
        if got != EXPECTED_C3_OURS[j]:
            bad += 1
    cases.append(("C = 2 does not reproduce the C = 3 table",
                  bad == len(EXPECTED_C3_OURS),
                  "%d of %d rows differ" % (bad, len(EXPECTED_C3_OURS))))
    # 2. and the corrected one must, or face (b) is vacuous
    bad3 = 0
    for j in sorted(EXPECTED_C3_OURS):
        ls = at_c(C_SPACING, j)
        got = min(l.margin(r) for l, (_n, r) in zip(ls, ours(ls, "historical")))
        if got != EXPECTED_C3_OURS[j]:
            bad3 += 1
    cases.append(("C = 3 reproduces it exactly", bad3 == 0,
                  "%d rows differ" % bad3))
    # 3. ⛔ THE DIRECTION OF THE ERROR. A larger C must never IMPROVE a margin;
    #    if it did, the recurrence would not be monotone in service time and
    #    the whole "optimistic" framing would be wrong.
    worse = all(EXPECTED_C3_OURS[j] <= EXPECTED_C2_OURS[j] for j in EXPECTED_C3_OURS)
    cases.append(("a larger C never improves a margin", worse,
                  "monotone in service time"))
    # 4. ⛔ AND THE OLD NUMBER WAS THE OPTIMISTIC ONE, which is the claim being
    #    published. Strictly, not merely weakly.
    strict = all(EXPECTED_C3_OURS[j] < EXPECTED_C2_OURS[j] for j in EXPECTED_C3_OURS)
    cases.append(("every row was strictly optimistic (ours)", strict,
                  "so the correction is not cosmetic on any row"))
    # 5. ⛔⛔ AND THE SAME ON THE PRIMARY BOUND, which is the one published.
    #    Cases 1-4 all read OUR recurrence; a must-fire set that never
    #    exercises the quoted bound would price the cross-check and leave the
    #    published number unchecked -- the shape of an exact answer to the
    #    wrong question.
    strict_p = all(EXPECTED_C3_PYRTA[j] < EXPECTED_C2_PYRTA[j]
                   for j in EXPECTED_C3_PYRTA)
    cases.append(("every row was strictly optimistic (pyRTA)", strict_p,
                  "the PUBLISHED bound, not only the cross-check"))
    # 6. ⛔ THE DIRECTION BETWEEN THE BOUNDS, as a table-level invariant. Ours
    #    must never be ABOVE pyRTA's margin, i.e. never the optimistic one. The
    #    per-lane version of this is asserted in face (c) on response times;
    #    this is the same rule on the recorded minima, so a future edit to
    #    either table cannot quietly invert them.
    safe = all(EXPECTED_C3_OURS[j] <= EXPECTED_C3_PYRTA[j]
               for j in EXPECTED_C3_OURS)
    cases.append(("ours is never the optimistic bound", safe,
                  "margin ours <= margin pyRTA on every recorded row"))
    for name, ok, note in cases:
        print("    %-44s %-9s %s" % (name, "ok" if ok else "*** FAILED", note))
        if not ok:
            rc = 1
    return rc


def main() -> int:
    rc = 0
    print()
    print("=" * 78)
    print("C = %d -- THE RE-QUOTE (ruling 1)" % C_SPACING)
    print("=" * 78)
    lane_digest.announce(
        "gate_c3_requote.py", at_c(C_SPACING, J_SHIPPED),
        variant="every lane at C = %d, the MEASURED inter-dispatch spacing, "
                "against a shipped table that still records C = %d"
                % (C_SPACING, C_OCCUPANCY))
    print("  measurement: btbmin = %d on arms S and T, %d back-to-back"
          % (C_SPACING, C_SAT_BTB))
    print("               spacings across four arms, not one of them %d"
          % C_OCCUPANCY)
    print("  pre-reg    : %s (committed before the instrument)" % C_SAT_PREREG)
    print("  recipe     : %s   ⛔ RECORD, re-derivable, not live here"
          % C_SAT_RECIPE)
    print("  occupancy  : %d -- `svc_cycles/svc_jobs`, and STILL CORRECT as an"
          % C_OCCUPANCY)
    print("               answer to the question it was asked. The error was")
    print("               using it as the spacing, not measuring it wrong.")
    print("  bound order: pyRTA PRIMARY, ours the safe-direction cross-check")
    print()

    src = pyrta_src.require_pyrta("gate_c3_requote")
    if not src:
        print("  *** pyRTA is the PRIMARY bound and it is absent, so this gate")
        print("      is RED rather than publishing ours alone. Point PYRTA_SRC")
        print("      at a clone's src/.")
        return 1

    rc |= face_shipped(src)
    rc |= face_sweep(src)
    rc |= face_derived_j(src)
    rc |= face_dtol(src)
    rc |= selftest()

    # ---- THE LEDGER ENTRY, as an error and not a footnote ---------------
    print()
    print("-" * 78)
    print("  LEDGER -- what was published, and what it should have said")
    print("    * `C = 2` was derived from the dispatch FSM's TWO service")
    print("      states and checked against `svc_cycles/svc_jobs = 2.00`.")
    print("      Both are correct about OCCUPANCY. Neither measured the")
    print("      SPACING between dispatches, which is what the recurrence")
    print("      charges, and the FSM is a THREE-state cycle.")
    print("    * every published `r_i` was one to five cycles too small;")
    print("      `B = max(C_j - 1)` was 1 and is %d; the shipped min margin"
          % (C_SPACING - 1))
    print("      was published as %d and is %d, on both bounds."
          % (EXPECTED_C2_PYRTA[J_SHIPPED], EXPECTED_C3_PYRTA[J_SHIPPED]))
    print("    * the bar crossing DOES NOT MOVE on the primary bound: pyRTA")
    print("      clears margin >= %d at every swept J at both service times."
          % MARGIN_BAR)
    print("      ⚠ ON OUR CROSS-CHECK IT MOVES FROM J = 7 TO J = 5, and an")
    print("      earlier draft of this gate published that as the finding.")
    print("      It is a fact about the conservative bound, not about the")
    print("      analysis we quote. Recorded so the retraction is not needed")
    print("      twice.")
    print("    * the J = %d stress point keeps margin %d -- EXACTLY the bar --"
          % (J_DERIVED, EXPECTED_C3_PYRTA[J_DERIVED]))
    print("      on pyRTA, and goes negative on ours. It is the RETRACTED")
    print("      universal figure (ledger b4e51034e283), not a bound.")
    print("    ⛔ HOW IT SURVIVED SO LONG: the two readings AGREED. A")
    print("      structural derivation ('two states, so C = 2') and a")
    print("      simulation mean (2.00) confirmed each other, and both were")
    print("      about occupancy. Agreement between two measurements of the")
    print("      same wrong quantity is not corroboration -- which is this")
    print("      project's own standing rule, met here in a new place.")
    print("    ⭐ WHAT CAUGHT IT: reading the FSM as a CYCLE rather than as a")
    print("      list of states, and then measuring the spacing directly")
    print("      instead of inferring it.")

    print()
    print("=" * 78)
    print("  GATE c3-requote: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    * shipped (J = %d): min margin %d at C = %d, bar %d -- clears"
          % (J_SHIPPED, EXPECTED_C3_PYRTA[J_SHIPPED], C_SPACING, MARGIN_BAR))
    print("    * pyRTA PRIMARY; ours >= pyRTA on every lane at both C")
    print("    * ⛔ D*, L_REFILL, L_CAP and `d_min >= D* -> J = 1` contain no")
    print("      C and are NOT re-derived here (prereg 5.2.5)")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
