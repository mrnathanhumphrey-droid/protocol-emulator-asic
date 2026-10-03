"""SPEC N1 + 1.1 (I2C half) -- the SCL phase split, derived from UM10204.

THE ONE CLAIM: `D_I2C` is derived from the I2C bus-timing table, not from the
centre-sampling stand-in -- and the symmetric phase split the project shipped is
NOT LEGAL.

⛔⛔ THE SHIPPED I2C LANE WAS WRONG, AND IN THE DIRECTION THE PRE-REG THOUGHT WAS
SAFE. `ARCH_PREREG_01` set the I2C event period to 125/2 = 62.5 -> 62 cycles and
labelled rounding DOWN as conservative ("makes the lane slightly FASTER than
reality"). It is not conservative, because it presumes a SYMMETRIC split, and a
symmetric 400 kHz phase is

    125 / 2 = 62.5 cycles = 1.25 us  <  tLOW(min) = 1.3 us = 65 cycles

so the low phase violates the spec at NOMINAL, before any jitter. The legal
split is asymmetric, and its minimum inter-event spacing is SHORTER than 62 --
so the lane is denser than modelled, not slower.

Source: NXP UM10204 Rev. 7.0 (1 Oct 2021), **Table 11** -- "Characteristics of
the SDA and SCL bus lines". ⛔ Not Table 10: the numbering moved in Rev 7.0 and
Table 10 is now the I/O stages. Fast mode, at 50 MHz (20 ns/cycle):

    tLOW  min 1.3 us = 65 cyc      tHIGH min 0.6 us = 30 cyc
    tr    max 0.3 us = 15 cyc      tf    max 0.3 us = 15 cyc
    tSU;DAT min 100 ns = 5 cyc     tHD;DAT min 0

⭐ `D_I2C` IS NOW A DERIVED QUANTITY. For a lane whose clock WE generate, the
peer judges the intervals between our edges, so the tolerance is how much
differential jitter each phase can absorb:

    D_I2C = min( N_low - tLOW(min),  N_high - tHIGH(min) )

That replaces the modelled centre-sample value of 30 and is TIGHTER. One of the
three O4 "modelled, not derived" labels comes off here; SPI and Ethernet remain.
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

CY_PER_US = 50.0                 # 50 MHz
T_LOW, T_HIGH = 65, 30           # cycles, fast-mode minima
TR, TF = 15, 15                  # cycles, fast-mode MAXIMA
PERIOD = 125                     # 400 kHz in cycles

# every lane except I2C, so the I2C lane can be varied
OTHERS = [BLane(l.name, l.T, l.C, l.D, n=l.n, t=l.t)
          for l in (TX[0], TX[1], UART_RX, SPI_RX)]


def solve(n_low: int):
    """(N_high, T, r, delta_max, tLOW slack, tHIGH slack) for this split."""
    n_high = PERIOD - n_low
    T = min(n_low, n_high)
    d = min(T // 2, T - T // 2 - 1)
    lane = BLane("I2C", T, 2, d)
    r = response_time_b(lane, OTHERS + [lane])["r"]
    dm = r - 2                                   # gate 0.9: delta_max = r - C
    return n_high, T, r, dm, n_low - dm - T_LOW, n_high - dm - T_HIGH


def main() -> int:
    print()
    print("=" * 78)
    print("SPEC N1 -- the I2C SCL phase split (UM10204 Rev 7.0, Table 11)")
    print("=" * 78)

    # ---- MUST-FIRE: the shipped symmetric split has to FAIL --------------
    print("  --- must-fire arm: a SYMMETRIC split must be rejected ---")
    fired = True
    for nl in (62, 63):
        nh, T, r, dm, sl, sh = solve(nl)
        bad = sl < 0
        fired = fired and bad
        print("    N_low=%-3d N_high=%-3d  tLOW slack %-4d  %s"
              % (nl, nh, sl,
                 "REJECTED (tLOW violated by %d cycles)" % -sl if bad
                 else "*** ACCEPTED -- the check cannot see the violation ***"))
    print("    must-fire: %s"
          % ("PASS -- the shipped symmetric assumption is caught"
             if fired else "*** FAIL -- this gate proves nothing ***"))
    if not fired:
        return 1
    print()

    # ---- the legal family ------------------------------------------------
    print("  --- the legal split family ---")
    print("    %-7s %-8s %-6s %-5s %-7s %-11s %-11s %s"
          % ("N_low", "N_high", "T=min", "r", "delta", "tLOW slack",
             "tHIGH slack", "note"))
    best = None
    for nl in range(65, 96, 5):
        nh, T, r, dm, sl, sh = solve(nl)
        if sl < 0 or sh < 0:
            note = "ILLEGAL"
        elif min(sl, sh) == 0:
            note = "zero margin -> A2-F6"
        else:
            note = ""
            if best is None or min(sl, sh) > best[0]:
                best = (min(sl, sh), nl, nh, T, r, dm, sl, sh)
        print("    %-7d %-8d %-6d %-5d %-7d %-11d %-11d %s"
              % (nl, nh, T, r, dm, sl, sh, note))
    if best is None:
        print("    *** no split has positive margin on both phases")
        return 1
    _, NL, NH, T, r, dm, sl, sh = best
    print()
    print("  ⭐ BALANCED-SLACK CHOICE: N_low=%d, N_high=%d -> T=%d, slacks %d/%d"
          % (NL, NH, T, sl, sh))
    print("     (maximising the minimum inter-event spacing instead gives")
    print("      N_low=70/N_high=55, T=55 -- but tLOW slack 0, which A2-F6 calls")
    print("      a named obstacle rather than a pass. Margin beats density here.)")
    D_I2C = min(NL - T_LOW, NH - T_HIGH)
    print()
    print("  D_I2C = min(N_low - tLOW, N_high - tHIGH) = min(%d, %d) = %d cycles"
          % (NL - T_LOW, NH - T_HIGH, D_I2C))
    print("    DERIVED from Table 11. Replaces the modelled centre-sample 30.")
    print("    Feasibility (gate 0.9 reading): delta_max %d <= D_I2C %d, margin %d"
          % (dm, D_I2C, D_I2C - dm))
    ok_feas = dm <= D_I2C

    # ---- the whole-period budget, which is the real squeeze --------------
    print()
    print("=" * 78)
    print("  THE WHOLE-PERIOD BUDGET -- and it is already spent")
    print("=" * 78)
    print("  An I2C clock period is tLOW + tHIGH + tr + tf. With the Table 11")
    print("  minima for the phases and MAXIMA for the edges:")
    total = T_LOW + T_HIGH + TR + TF
    print("    %d + %d + %d + %d = %d cycles,  against a period of %d"
          % (T_LOW, T_HIGH, TR, TF, total, PERIOD))
    print("    slack = %d cycles" % (PERIOD - total))
    print()
    print("  ⛔⛔ AT 400 kHz WITH WORST-CASE RISE AND FALL THE BUDGET IS EXACTLY")
    print("     CONSUMED, before any scheduler jitter. Our delta_max of %d cycles"
          % dm)
    print("     has nowhere to come from. This is NOT an RTL problem.")
    print()
    budget = PERIOD - T_LOW - T_HIGH - dm
    print("  What the board must deliver:")
    print("    tr + tf <= period - tLOW - tHIGH - delta_max = %d cycles = %d ns"
          % (budget, budget * 20))
    print("    The spec permits up to 600 ns (300+300), so rise+fall must beat")
    print("    the spec maximum by %d ns. That is a pull-up resistor and bus"
          % (600 - budget * 20))
    print("    capacitance requirement, owned by the BOARD rung.")
    print()
    print("  Or run the lane slower -- where worst-case tr/tf fits unaided:")
    print("    %-9s %-11s %-9s %s" % ("f_SCL", "period", "slack", "verdict"))
    for khz in (400, 350, 300, 250, 200, 100):
        per = 1000.0 / khz
        slack = (per - 1.3 - 0.6 - 0.3 - 0.3) * CY_PER_US
        v = ("ok, delta_max=%d fits" % dm if slack >= dm
             else "no room for jitter" if slack >= 0 else "ILLEGAL")
        print("    %-9s %-11s %-9s %s"
              % ("%d kHz" % khz, "%.2f us" % per, "%.0f cyc" % slack, v))
    print()
    print("  ⭐ 350 kHz is the first rate that carries worst-case edges AND our")
    print("     jitter with no board requirement at all (18 cycles of slack).")

    print()
    print("=" * 78)
    print("  GATE N1: %s" % ("PASSED" if ok_feas else "FAILED"))
    print("    * symmetric split rejected (must-fire fired)")
    print("    * legal split chosen on balanced margin: %d/%d" % (NL, NH))
    print("    * D_I2C = %d, DERIVED -- one O4 label removed" % D_I2C)
    print("    * T_I2C = %d, down from the shipped 62: the lane is DENSER" % T)
    print("  ⛔ LEDGER (board rung, not ours): tr+tf <= %d ns required at"
          % (budget * 20))
    print("     400 kHz, or drop to 350 kHz. Open-drain edge rates are wire")
    print("     physics and are labelled MODELLED until the board rung measures")
    print("     them.")
    return 0 if ok_feas else 1


if __name__ == "__main__":
    raise SystemExit(main())
