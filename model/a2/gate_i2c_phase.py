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
T_SU_DAT = 5                     # cycles, fast-mode tSU;DAT min (100 ns)
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

    # ---- N1a: tr leaves the budget, because of clock synchronization ----
    print()
    print("=" * 78)
    print("  N1a -- WHY THERE IS NO BOARD REQUIREMENT (clock synchronization)")
    print("=" * 78)
    print("  The naive budget looks fatal: a period is tLOW + tHIGH + tr + tf,")
    total = T_LOW + T_HIGH + TR + TF
    print("  and with the phase MINIMA and the edge MAXIMA that is")
    print("    %d + %d + %d + %d = %d cycles against a %d-cycle period -> slack %d."
          % (T_LOW, T_HIGH, TR, TF, total, PERIOD, PERIOD - total))
    print("  Read that way, 400 kHz leaves no room for any jitter and the board")
    print("  would have to beat the spec's own edge maxima. ⛔ THAT READING IS")
    print("  WRONG, and UM10204 says so itself.")
    print()
    print("  Rev 7.0, clock synchronization, VERBATIM from refs/UM10204.txt:")
    print('    "When all controllers concerned have counted off their LOW')
    print('     period, the clock line is released and goes HIGH. There is then')
    print('     no difference between the controller clocks and the state of the')
    print('     SCL line, and all the controllers start counting their HIGH')
    print('     periods."')
    print()
    print("  The HIGH count starts when SCL *goes* HIGH, not when the controller")
    print("  released it. So a slow rise LENGTHENS THE PERIOD instead of eating")
    print("  tHIGH, and `tr` is outside the controller's budget entirely. Since")
    print("  Table 11 gives f_SCL as 0..400 kHz -- a MAXIMUM -- a longer period is")
    print("  compliant. ⭐ The same sampled-SCL-high condition is already required")
    print("  by A2 Part 4 for clock stretching, so no new mechanism is needed.")
    print()
    print("  ⭐ f_SCL therefore becomes an OUTCOME, not a target: the controller")
    print("  picks N_low and N_high, and the wire decides the rate. Margin m above")
    print("  the spec minima is the real knob:")
    print("    %-4s %-7s %-8s %-6s %-7s %-10s %s"
          % ("m", "N_low", "N_high", "T", "D_I2C", "f worst", "margin"))
    for m in (0, 5, 10, 15):
        nl, nh = T_LOW + dm + m, T_HIGH + dm + m
        Tm = min(nl, nh)                      # conservative: assumes tr -> 0
        Dm = min(nl - T_LOW, nh - T_HIGH, (nl - T_SU_DAT) // 2)
        f = 50e6 / (TF + nl + TR + nh) / 1000
        print("    %-4d %-7d %-8d %-6d %-7d %-10.0f %-3d %s"
              % (m, nl, nh, Tm, Dm, f, Dm - dm,
                 "<- A2-F6 zero margin" if Dm == dm else ""))
    print()
    print("  ⛔ THE BOARD REQUIREMENT IS WITHDRAWN. The earlier conclusion -- that")
    print("     tr+tf must beat the spec maximum by 100 ns, or the lane drop to")
    print("     350 kHz -- was an artefact of charging tr to the controller.")
    print("     What replaces it is a DECLARED SCOPE POINT: at m=%d the lane runs"
          % 10)
    print("     at ~%d kHz worst-case rise, faster with better pull-ups."
          % (50e6 / (TF + 80 + TR + 45) / 1000))
    print("     Only tf stays in the controller's budget.")

    # ---- N1b: D over EVERY Table 11 constraint, not the phases only ------
    print()
    print("=" * 78)
    print("  N1b -- D_I2C over EVERY Table 11 differential constraint")
    print("=" * 78)
    sda_tol = (NL - T_SU_DAT) // 2
    fixed = [("SCL low phase", NL - T_LOW, "bounded above by the f_SCL target"),
             ("SCL high phase", NH - T_HIGH, "bounded above by the f_SCL target"),
             ("SDA placement", sda_tol, "boxed inside the low phase")]
    free = [("tSU;STA separation", 30), ("tHD;STA separation", 30),
            ("tSU;STO separation", 30), ("tBUF separation", 65)]
    print("  %-22s %-13s %s" % ("constraint", "tolerance", "note"))
    for n, v, note in fixed:
        print("  %-22s %-13s %s" % (n, "%d cyc" % v, note))
    for n, tmin in free:
        print("  %-22s %-13s FREE timestamp offset (Q2): set it generously"
              % (n, "unbounded"))
    D_all = min(v for _, v, _ in fixed)
    binds = [n for n, v, _ in fixed if v == D_all]
    print()
    print("  D_I2C = min over the BINDING constraints = %d cycles, set by: %s"
          % (D_all, ", ".join(binds)))
    print()
    print("  ⛔ P1.1b IS FALSIFIED, NOT MERELY UNTESTED. The prediction was that a")
    print("     START/STOP separation would bind. It cannot: per Q2 those")
    print("     separations are FREE TIMESTAMP OFFSETS, so they are CHOSEN rather")
    print("     than given, and a chosen parameter is never the binding one -- we")
    print("     just set it generously at zero cell cost. Only a constraint with")
    print("     competing UPWARD pressure can bind, which here means the SCL")
    print("     phases (pushed up by the f_SCL target) and the SDA placement")
    print("     (boxed inside the low phase).")

    # ---- N1b must-fire: SDA inside tSU;DAT of the rise must FAIL --------
    print()
    print("  --- must-fire arm: SDA placed inside tSU;DAT of the rise ---")
    bad_offsets = [NL - T_SU_DAT + 1, NL - 1, NL]
    mf = True
    for s in bad_offsets:
        setup_left = NL - s - dm
        rejected = setup_left < T_SU_DAT
        mf = mf and rejected
        print("    SDA at offset %-3d -> setup left %-4d vs tSU;DAT %d : %s"
              % (s, setup_left, T_SU_DAT,
                 "REJECTED" if rejected else "*** ACCEPTED -- check is blind ***"))
    s_ok = (NL - T_SU_DAT) // 2
    print("    SDA at offset %-3d -> setup left %-4d vs tSU;DAT %d : %s"
          % (s_ok, NL - s_ok - dm, T_SU_DAT,
             "accepted (the legal centre)" if NL - s_ok - dm >= T_SU_DAT
             else "*** rejected -- the legal case fails ***"))
    mf = mf and (NL - s_ok - dm >= T_SU_DAT)
    print("    must-fire: %s"
          % ("PASS -- illegal SDA placements are caught and the legal one is not"
             if mf else "*** FAIL ***"))

    print()
    print("=" * 78)
    ok = ok_feas and mf
    print("  GATE N1: %s" % ("PASSED" if ok else "FAILED"))
    print("    * symmetric split rejected (must-fire fired)")
    print("    * split chosen on balanced margin: %d/%d" % (NL, NH))
    print("    * D_I2C = %d over ALL Table 11 constraints, DERIVED" % D_all)
    print("    * T_I2C = %d, down from the shipped 62: the lane is DENSER" % T)
    print("    * P1.1b falsified: free offsets cannot bind")
    print("    * board requirement WITHDRAWN (clock synchronization)")
    print("  ⛔ LEDGER: f_SCL ~%d kHz worst-case is a DECLARED SCOPE POINT, not"
          % (50e6 / (TF + NL + TR + NH) / 1000))
    print("     400 kHz. Open-drain edge rates remain MODELLED until the board")
    print("     rung measures them; only tf is in the controller's budget.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
