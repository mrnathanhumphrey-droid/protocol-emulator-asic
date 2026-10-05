"""SPEC 0.9b -- the differential reading does NOT cover every lane-action.

THE ONE CLAIM: gate 0.9's `(r_i - C_i) <= D_i` is correct only where WE are the
timing source. Where the PEER sources timing, the budget is ABSOLUTE, the
synchroniser latency enters it, and C9 (does the pin move at service START or at
COMPLETION?) comes back from the dead.

⛔⛔ THIS IS A SCOPE LIMIT ON A RESULT THIS FILE'S AUTHOR ARGUED FOR. Gate 0.9
rests on two legs: start delay in [0, r-C], and a UNIFORM SHIFT BEING INVISIBLE
because the peer re-synchronises. The second leg is what fails for a reactive
action. When the master generates SCLK and samples MISO at a fixed phase of ITS
OWN clock, a uniform delay in our output is not invisible -- it eats the master's
setup window directly. So:

    SOURCE action    -> differential test, C9 cancels (constant offset)
    REACTIVE action  -> ABSOLUTE test, C9 is load-bearing

⭐ AND C9 IS WORTH REAL MEGAHERTZ. Driving the pin at service COMPLETION rather
than at START adds C_i to every reactive budget, which moves the SPI-target
ceiling by about 0.6 MHz. C9 was declared dissolved when only SOURCE lanes were
in view; it is a design decision again, and 1.3 has to make it.

SYNCHRONISER NUMBERS TAKEN FROM THE SHIPPED RTL, not assumed: `src/project.v`
uses `reg [2:0] wr_sync` -- "Two flops to resolve metastability, a third to see
the edge" -- with `wr_rise = (wr_sync[2:1] == 2'b01)`. Detection lands at t+2,
and the asynchronous capture can miss by a cycle, so

    L_sync (latency)      <= 3 cycles
    L_jitter (uncertainty) = 1 cycle
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import lane_digest                                                  # noqa: E402
from bursty import (BLane, F_CLK, L_JIT, L_SYNC, OUT_REG, SPI_RX,   # noqa: E402
                    TSU_MASTER, TX, UART_RX, abs_tolerance, response_time_b)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ⛔ L_SYNC / L_JIT / OUT_REG were DEFINED HERE and are now imported from
# `bursty`, where the lane table can see them. Spec R1 derives SPI-target's
# DEADLINE from exactly these three numbers, so a copy here and a copy there
# would be two numbers that must agree for the lane table to mean anything --
# and nothing would have been checking.

# ---- the classification, which is the deliverable -----------------------
# (lane, action, who sources the timing, test to apply)
ACTIONS = [
    ("UART-tx", "drive TX edge", "US", "SOURCE"),
    ("SPI-master", "drive SCLK + MOSI (atomic)", "US", "SOURCE"),
    ("SPI-master", "sample MISO", "US (we clock it)", "SOURCE"),
    ("I2C", "drive SCL low / SDA", "US", "SOURCE"),
    ("I2C", "release SCL, high phase", "PEER (observed rise)", "REACTIVE-J"),
    # ⭐ SPEC R3 -- this action was MISSING from the classification, which is how
    # a counted-offset placement rule got proposed for it without the table ever
    # disagreeing. It is FOLDED into the high-phase release above: same release,
    # same 3-FF sync, no new event. See gate_i2c_sda_read.py.
    ("I2C", "sample SDA (folded into the rise)", "PEER (observed rise)",
     "REACTIVE-J"),
    ("UART-rx", "detect start edge", "PEER", "REACTIVE-anchor"),
    ("UART-rx", "sample bit k", "US (from detection)", "SOURCE+anchor"),
    ("SPI-target", "sample MOSI", "PEER (master SCLK)", "REACTIVE-abs"),
    ("SPI-target", "drive MISO", "PEER (master SCLK)", "REACTIVE-abs"),
]


def five_lanes(i2c_j: int | None = None):
    """A rebuild of the shipped five, with I2C's J optionally overridden.

    ⛔⛔ THIS BUILDER DROPPED `J` AND THE DIGEST META-CHECK CAUGHT IT. It copied
    name/T/C/D/n/t out of the shipped lanes and simply did not carry `J`. While
    the shipped table was J = 0 everywhere that was invisible -- the copy and
    the original agreed by coincidence. The moment the table was re-baselined to
    its derived J = 1 this gate reported `used = 8ea5756203e1`, the OLD digest,
    as an UNDECLARED VARIANT: it was analysing the previous table under the
    current table's name.
    ⭐ That is precisely the failure the A1 digest cross-check exists for, and
    it is the second time a SECOND BUILDER has caused one here (the first was
    `response_time_b` filtering interference by identity, where a copy
    under-excluded and inflated the bound). A field added to the lane table must
    be carried by every rebuild of it, so `J=l.J` is now explicit.
    """
    ls = [BLane(l.name, l.T, l.C, l.D, n=l.n, t=l.t, J=l.J) for l in TX]
    if i2c_j is not None:
        # the SWEEP arm: override I2C's J only, keeping everything else
        ls[2] = BLane(TX[2].name, TX[2].T, TX[2].C, TX[2].D, J=i2c_j)
    ls += [BLane(UART_RX.name, UART_RX.T, UART_RX.C, UART_RX.D,
                 n=UART_RX.n, t=UART_RX.t, J=UART_RX.J),
           BLane(SPI_RX.name, SPI_RX.T, SPI_RX.C, SPI_RX.D,
                 n=SPI_RX.n, t=SPI_RX.t, J=SPI_RX.J)]
    return ls


def abs_budget(r_minus_c: int, c9_at_completion: bool, C: int) -> int:
    """The ABSOLUTE latency a reactive output accumulates before the pin moves.

    ⛔ This is the SAME relation as `bursty.abs_tolerance`, rearranged: that one
    solves for the start-delay tolerance given a half period, this one adds up
    the latency given a start delay. `assert_budget_consistent()` below pins
    them to each other, because R1 turns one of them into a shipped DEADLINE and
    two rearrangements of one equation drifting apart is how a lane table ends
    up disagreeing with the gate that justified it.
    """
    return L_SYNC + r_minus_c + OUT_REG + (C if c9_at_completion else 0)


def assert_budget_consistent(verbose: bool = True) -> bool:
    """`abs_budget` and `abs_tolerance` must be inverses, at every input."""
    bad = []
    for half in range(8, 40):
        for c9 in (False, True):
            for C in (1, 2, 3, 5):
                for tsu in (0, 1, 3):
                    tol = abs_tolerance(half, c9, C, tsu)
                    # a start delay of exactly `tol` must just fit
                    if abs_budget(tol, c9, C) != half - tsu:
                        bad.append((half, c9, C, tsu, tol))
    if verbose:
        print("  budget/tolerance inverse gate: %s"
              % ("PASS -- abs_tolerance(half) is exactly the start delay at "
                 "which abs_budget() equals half - tSU, over %d combinations"
                 % (32 * 2 * 4 * 3) if not bad
                 else "*** FAIL: %d mismatches, first %s ***" % (len(bad), bad[0])))
    return not bad


def main() -> int:
    print()
    print("=" * 78)
    print("SPEC 0.9b -- SOURCE vs REACTIVE: which test applies where")
    print("=" * 78)
    print("  %-12s %-28s %-22s %s"
          % ("lane", "action", "timing source", "test"))
    for lane, act, src, cls in ACTIONS:
        print("  %-12s %-28s %-22s %s" % (lane, act, src, cls))
    print()
    print("  SOURCE          -> differential, (r-C) <= D, C9 cancels")
    print("  REACTIVE-abs    -> ABSOLUTE budget, C9 LOAD-BEARING")
    print("  REACTIVE-J      -> release jitter J = sync uncertainty, into A2")
    print("  REACTIVE-anchor -> sample grid carries the sync latency")
    print()
    print("  from src/project.v: L_sync <= %d cycles, uncertainty %d, out reg %d"
          % (L_SYNC, L_JIT, OUT_REG))
    print()
    lane_digest.announce("gate_lane_class.py (0.9b)", five_lanes())
    print()
    rc_gate = 0 if assert_budget_consistent() else 1

    # ---- REACTIVE-anchor: UART-rx ---------------------------------------
    print()
    print("=" * 78)
    print("  REACTIVE-anchor -- UART-rx: the grid is anchored to DETECTION")
    print("=" * 78)
    T, half = 434, 217
    d_nom = T - half - 1
    d_anchored = d_nom - L_SYNC
    # ⛔ ONE lane set, selected from -- not two builder calls. See the identity
    # assertion in response_time_b: equal-but-distinct objects are not excluded.
    _ls = five_lanes()
    rx = [l for l in _ls if l.name.startswith("UART-rx")][0]
    r_rx = response_time_b(rx, _ls)["r"]
    print("  samples land at detection + half + kT, and detection LAGS the true")
    print("  edge by L_sync, so the whole grid slides: the early-side constraint")
    print("  becomes  delta_0 - delta_m+1 < T - half - L_sync.")
    print("    D_UART-rx = %d - %d = %d   (was %d)" % (d_nom, L_SYNC, d_anchored, d_nom))
    print("    delta_max = r - C = %d - %d = %d  ->  margin %d"
          % (r_rx, rx.C, r_rx - rx.C, d_anchored - (r_rx - rx.C)))
    # ⭐ SPEC H3 -- the derivation and the LANE TABLE must agree, asserted.
    # This gate printed 213 while the table carried 216 for as long as both
    # existed, and nothing compared them: the derived value was a line of
    # output, not an input to anything. A number that is only ever printed is
    # not in the model.
    if rx.D_tol != d_anchored:
        print("    *** FAIL (H3): the lane table says D_tol = %d, this"
              % rx.D_tol)
        print("        derivation says %d. One of them is not the shipped"
              % d_anchored)
        print("        number, and every UART-rx result is ambiguous. ***")
        rc_gate = 1
    else:
        print("    H3: the lane table's D_tol for this lane IS %d -- derivation"
              % rx.D_tol)
        print("        and table agree, and now they are compared.")
    print("  ⭐ costs 3 of 216; nowhere near binding. Recorded because the lane")
    print("     class is different even where the number does not care.")

    # ---- REACTIVE-J: I2C high phase -------------------------------------
    print()
    print("=" * 78)
    print("  REACTIVE-J -- I2C high phase released on the OBSERVED rise")
    print("=" * 78)
    _i2c0 = [l for l in five_lanes() if l.name.startswith("I2C")][0]
    print("  %-26s %-7s %-7s %s"
          % ("config", "r_I2C", "r-C", "margin vs D_tol = %d" % _i2c0.D_tol))
    for j in (0, L_JIT, L_SYNC):
        ls = five_lanes(i2c_j=j)
        i2c = [l for l in ls if l.name.startswith("I2C")][0]
        r = response_time_b(i2c, ls)["r"]
        # ⛔ D_tol, not D. `D` is now the EDF key (= D_sched + C), so this column
        # read "margin vs D=15" while printing 17 - (r - C). Same bug class as
        # the lane table's old `D - r` column: a label naming one quantity over
        # an arithmetic using another.
        print("  %-26s %-7d %-7d %d"
              % ("J = %d (%s)" % (j, "ideal" if j == 0 else
                                  "sync uncertainty" if j == L_JIT else
                                  "full sync latency"),
                 r, r - i2c.C, i2c.margin(r)))
    print("  ⭐ J = %d is the honest figure: the LATENCY is %d but it is constant,"
          % (L_JIT, L_SYNC))
    print("     and only the 1-cycle async-capture AMBIGUITY is jitter. A constant")
    print("     lag on a release is absorbed by the period, which N1a already")
    print("     established is free.")

    # ---- REACTIVE-abs: SPI-target, and N2' ------------------------------
    print()
    print("=" * 78)
    print("  REACTIVE-abs -- SPI-target MISO, and the N2' ceiling recomputed")
    print("=" * 78)
    ls = five_lanes()
    sp = [l for l in ls if l.name.startswith("SPI-target")][0]
    r_sp = response_time_b(sp, ls)["r"]
    rc = r_sp - sp.C
    print("  budget = L_sync + (r-C) + out_reg + [C9]   must fit")
    print("           half_period - tSU(master)")
    for c9 in (False, True):
        b = abs_budget(rc, c9, sp.C)
        print("    C9 = pin at %-10s : %d + %d + %d + %d = %d cycles"
              % ("COMPLETION" if c9 else "START", L_SYNC, rc, OUT_REG,
                 sp.C if c9 else 0, b))
    print()
    print()
    print("  ⭐ SPEC R1 -- THIS BUDGET IS NOW THE LANE'S DEADLINE, NOT JUST A")
    print("     CHECK ON IT. At 1 MHz the same relation rearranged gives")
    print("     D_tol = half - tSU - L_sync - out_reg - [C9] = %d (START) / %d"
          % (abs_tolerance(25, False, sp.C), abs_tolerance(25, True, sp.C)))
    print("     (COMPLETION), and the table ships the smaller so it is correct")
    print("     under either C9 outcome. The lane table's D_tol is %d."
          % sp.D_tol)
    if sp.D_tol != abs_tolerance(25, True, sp.C):
        print("     *** FAIL (R1): table says %d, derivation says %d ***"
              % (sp.D_tol, abs_tolerance(25, True, sp.C)))
        rc_gate = 1
    print("  ⚠ tSU(master) is parametric -- no device picked. Shown at %d cycle"
          % TSU_MASTER)
    print("    (%d ns), which is generous for a real master." % (TSU_MASTER * 20))
    print()
    print("  %-9s %-7s %-9s %-11s %-11s %s"
          % ("f_SCLK", "T", "half", "differential", "absolute", "binding test"))
    tsu = TSU_MASTER
    ceil_start = ceil_compl = None
    for mhz in (1, 2, 2.5, 3, 4, 5, 6):
        T = int(round(25.0 / mhz))
        half = 25.0 / mhz
        D = min(T // 2, T - T // 2 - 1)
        diff_ok = rc <= D
        a_start = abs_budget(rc, False, sp.C) <= half - tsu
        a_compl = abs_budget(rc, True, sp.C) <= half - tsu
        if diff_ok and a_start:
            ceil_start = mhz
        if diff_ok and a_compl:
            ceil_compl = mhz
        bind = ("absolute" if diff_ok and not a_compl
                else "differential" if not diff_ok else "neither binds")
        print("  %-9s %-7d %-9.1f %-11s %-11s %s"
              % ("%g MHz" % mhz, T, half,
                 "ok (%d<=%d)" % (rc, D) if diff_ok else "FAIL",
                 "ok" if a_compl else ("start-only" if a_start else "FAIL"),
                 bind))
    print()
    print("  ⭐ N2' CEILING: %g MHz with the pin at COMPLETION, %g MHz at START."
          % (ceil_compl, ceil_start))
    print("     The differential test alone said 5 MHz. The absolute budget is")
    print("     TIGHTER, so that figure is SUPERSEDED -- it was computed with the")
    print("     centre-sample D and no sync latency.")

    # ---- the must-fire arm 0.9b demands --------------------------------
    print()
    print("  --- must-fire: a REACTIVE action that passes differential but")
    print("      fails absolute MUST be rejected ---")
    # ⛔⛔ THIS ARM WAS TUNED TO THE J = 0 NUMBERS AND WENT VACUOUS ON THE
    # RE-BASELINE. It checked exactly two hard-coded rates, 3 and 4 MHz, which
    # were separating cases while `r - C` was one cycle smaller. With the shipped
    # table carrying its derived J = 1, `r - C` grows by 1, the DIFFERENTIAL test
    # starts failing at those rates too, and `diff_ok and not a_ok` became
    # unreachable -- the arm reported "no case separates the two tests" about a
    # separation that had simply moved to a lower frequency (2.5 MHz, visible in
    # the table printed above).
    # ⭐ A must-fire whose witness is a hard-coded constant is a must-fire with a
    # shelf life. It now SEARCHES for the separating case and NAMES the one it
    # finds, so the arm survives any change that moves the boundary instead of
    # silently going vacuous -- which is the standing rule that a spec fix must
    # audit its own suite for arms that encoded the old numbers.
    # ⛔⛔⛔ AND IT WENT VACUOUS A SECOND TIME, ON THE C = 2 -> 3 CORRECTION.
    # The fix above replaced two hard-coded rates with a SEARCH -- over a
    # hard-coded LIST of round megahertz values, which has the same shelf life
    # one step removed. At C = 3 the separating case is the integer period
    # T = 13 (about 1.92 MHz), which sits between the list's 2.0 and 1.5 and
    # was therefore missed: the arm reported "no case separates the two tests"
    # about a separation that exists.
    # ⇒ THE SCAN IS OVER THE INTEGER PERIOD, exhaustively. `T` is the quantity
    #   both tests actually depend on -- `D = min(T//2, T-T//2-1)` and
    #   `half = T/2` -- and it is an integer, so sweeping it cannot step over a
    #   boundary. A search that can miss its own witness is not a search.
    # ⚠ THE SAME DEFECT CLASS, THIRD TIME: a must-fire whose witness is a
    #   constant, then a list of constants. Recorded rather than quietly fixed
    #   again.
    fired = False
    scanned = []
    for T in range(2, 121):
        half = T / 2.0
        D = min(T // 2, T - T // 2 - 1)
        diff_ok = rc <= D
        a_ok = abs_budget(rc, True, sp.C) <= half - tsu
        scanned.append((T, diff_ok, a_ok))
        if diff_ok and not a_ok and not fired:
            fired = True
            print("    T = %d cycles (%.2f MHz): differential PASSES "
                  "(%d <= %d) but absolute FAILS" % (T, 25.0 / T, rc, D))
            print("            (%d > %.1f - %d) -> REJECTED by the absolute test"
                  % (abs_budget(rc, True, sp.C), half, tsu))
    print("    scanned %d integer periods; separating cases: %d"
          % (len(scanned), sum(1 for _t, d, a in scanned if d and not a)))
    print("    must-fire: %s"
          % ("PASS -- the absolute test catches what the differential one misses"
             if fired else
             "*** FAIL -- no case separates the two tests; arm is vacuous ***"))

    # ---- what R1 COST this lane, which the minimum margin does not show ---
    print()
    print("  --- R1's cost on THIS lane, reported because it is a loss ---")
    print("    R1's reorder moved SPI-target from the most urgent lane to the")
    print("    second, so its start delay (r - C) went 1 -> %d. That is a GAIN"
          % rc)
    print("    of 3 cycles on the minimum margin across the set (11 -> 14) and a")
    print("    LOSS of %d cycles of absolute budget on this lane. Both at once:"
          % (rc - 1))
    print("    %-9s %-14s %-14s %s"
          % ("f_SCLK", "margin (r-C=1)", "margin (r-C=%d)" % rc, "effect"))
    for mhz in (1, 2, 2.5, 3):
        half = 25.0 / mhz
        was = int(half - tsu - abs_budget(1, True, sp.C))
        now = int(half - tsu - abs_budget(rc, True, sp.C))
        eff = ("both clear the >= 4 bar" if was >= 4 and now >= 4
               else "*** dropped below the bar ***" if was >= 4 > now
               else "below the bar either way")
        print("    %-9s %-14d %-14d %s" % ("%g MHz" % mhz, was, now, eff))
    print("    ⛔ AT 2 MHz THE MARGIN FELL FROM 4 TO 2 -- from exactly at the bar")
    print("    to below it. 1 MHz is unaffected (margin %d) and 1 MHz is what is"
          % int(25.0 - tsu - abs_budget(rc, True, sp.C)))
    print("    declared, so nothing shipped moves. But the 2 MHz option is now")
    print("    out of reach without a C9 decision or a C measurement, and that")
    print("    is a consequence of R1, not of anything measured since.")

    print()
    print("=" * 78)
    print("  GATE 0.9b: %s" % ("PASSED" if fired and not rc_gate else "FAILED"))
    print("    * every lane-action classified SOURCE / REACTIVE")
    print("    * C9 is LOAD-BEARING again for REACTIVE outputs, worth ~%g MHz"
          % (ceil_start - ceil_compl))
    print("    * I2C high phase carries J = %d into A2" % L_JIT)
    print("    * UART-rx D drops by L_sync to %d, not binding" % d_anchored)
    print("    * N2' ceiling %g MHz (completion) supersedes the 5 MHz figure"
          % ceil_compl)
    print()
    print("  ⛔ THE >= 4 MARGIN BAR, AND WHY IT IS NOT TASTE (spec P2). Every margin")
    print("     here is computed at C = 2, which is STILL UNMEASURED -- it traces to")
    print("     one ARCH_PREREG sentence. The reserve has to cover that measurement")
    print("     risk: one C increment (2 -> 3) costs about 2 cycles of margin on the")
    print("     tight lanes, and a registered EDF winner costs J = 1. That is 3-4,")
    print("     so the bar is the measurement reserve, not a preference.")
    print("     ⭐ IT RETIRES once Phase 2 measures C: after that, margins are quoted")
    print("     on the measured value and only A2-F6 (zero margin) is a hard stop.")
    print("  ⛔ Wilson's recommendation to declare 1 MHz STANDS: at 2 MHz the")
    print("     absolute margin is %d cycles, below the >= 4 bar."
          % int(25.0 / 2 - tsu - abs_budget(rc, True, sp.C)))
    return 0 if (fired and not rc_gate) else 1


if __name__ == "__main__":
    raise SystemExit(main())
