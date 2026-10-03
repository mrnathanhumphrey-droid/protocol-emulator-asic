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

from bursty import BLane, TX, UART_RX, SPI_RX, response_time_b   # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

L_SYNC = 3          # cycles, worst-case edge-detection latency (3-FF chain)
L_JIT = 1           # cycles, async-capture uncertainty
OUT_REG = 1         # cycles, output register to pad
F_CLK = 50_000_000

# ---- the classification, which is the deliverable -----------------------
# (lane, action, who sources the timing, test to apply)
ACTIONS = [
    ("UART-tx", "drive TX edge", "US", "SOURCE"),
    ("SPI-master", "drive SCLK + MOSI (atomic)", "US", "SOURCE"),
    ("SPI-master", "sample MISO", "US (we clock it)", "SOURCE"),
    ("I2C", "drive SCL low / SDA", "US", "SOURCE"),
    ("I2C", "release SCL, high phase", "PEER (observed rise)", "REACTIVE-J"),
    ("UART-rx", "detect start edge", "PEER", "REACTIVE-anchor"),
    ("UART-rx", "sample bit k", "US (from detection)", "SOURCE+anchor"),
    ("SPI-target", "sample MOSI", "PEER (master SCLK)", "REACTIVE-abs"),
    ("SPI-target", "drive MISO", "PEER (master SCLK)", "REACTIVE-abs"),
]


def five_lanes(i2c_j: int = 0):
    ls = [BLane(l.name, l.T, l.C, l.D, n=l.n, t=l.t) for l in TX]
    ls[2] = BLane(TX[2].name, TX[2].T, TX[2].C, TX[2].D, J=i2c_j)
    ls += [BLane(UART_RX.name, UART_RX.T, UART_RX.C, UART_RX.D,
                 n=UART_RX.n, t=UART_RX.t),
           BLane(SPI_RX.name, SPI_RX.T, SPI_RX.C, SPI_RX.D,
                 n=SPI_RX.n, t=SPI_RX.t)]
    return ls


def abs_budget(r_minus_c: int, c9_at_completion: bool, C: int) -> int:
    """The ABSOLUTE latency a reactive output accumulates before the pin moves."""
    return L_SYNC + r_minus_c + OUT_REG + (C if c9_at_completion else 0)


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
    print("  ⭐ costs 3 of 216; nowhere near binding. Recorded because the lane")
    print("     class is different even where the number does not care.")

    # ---- REACTIVE-J: I2C high phase -------------------------------------
    print()
    print("=" * 78)
    print("  REACTIVE-J -- I2C high phase released on the OBSERVED rise")
    print("=" * 78)
    print("  %-26s %-7s %-7s %s" % ("config", "r_I2C", "r-C", "margin vs D=15"))
    for j in (0, L_JIT, L_SYNC):
        ls = five_lanes(i2c_j=j)
        i2c = [l for l in ls if l.name.startswith("I2C")][0]
        r = response_time_b(i2c, ls)["r"]
        print("  %-26s %-7d %-7d %d"
              % ("J = %d (%s)" % (j, "ideal" if j == 0 else
                                  "sync uncertainty" if j == L_JIT else
                                  "full sync latency"),
                 r, r - i2c.C, i2c.D - (r - i2c.C)))
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
    print("  ⚠ tSU(master) is parametric -- no device picked. Shown at 1 cycle")
    print("    (20 ns), which is generous for a real master.")
    print()
    print("  %-9s %-7s %-9s %-11s %-11s %s"
          % ("f_SCLK", "T", "half", "differential", "absolute", "binding test"))
    tsu = 1
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
    fired = False
    for mhz in (3, 4):
        T = int(round(25.0 / mhz))
        half = 25.0 / mhz
        D = min(T // 2, T - T // 2 - 1)
        diff_ok = rc <= D
        a_ok = abs_budget(rc, True, sp.C) <= half - tsu
        if diff_ok and not a_ok:
            fired = True
            print("    %g MHz: differential PASSES (%d <= %d) but absolute FAILS"
                  % (mhz, rc, D))
            print("            (%d > %.1f - %d) -> REJECTED by the absolute test"
                  % (abs_budget(rc, True, sp.C), half, tsu))
    print("    must-fire: %s"
          % ("PASS -- the absolute test catches what the differential one misses"
             if fired else
             "*** FAIL -- no case separates the two tests; arm is vacuous ***"))

    print()
    print("=" * 78)
    print("  GATE 0.9b: %s" % ("PASSED" if fired else "FAILED"))
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
    return 0 if fired else 1


if __name__ == "__main__":
    raise SystemExit(main())
