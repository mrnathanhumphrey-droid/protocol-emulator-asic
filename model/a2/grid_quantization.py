"""SPEC C3 -- edge-placement quantization against the clock grid.

THE ONE CLAIM: a synchronous engine can only place an edge on a clock boundary,
so any protocol edge whose nominal time is not an integer number of cycles
carries a SYSTEMATIC placement error of up to half a cycle -- present with ZERO
scheduling jitter, and invisible to every scheduling argument in A2.

⛔⛔ WHY THIS IS INDEPENDENT OF GATE 0.9, AND WHY IT MATTERS MORE FOR ETHERNET.
Gate 0.9 established that feasibility is `(r_i - C_i) <= D_i`, which made
unbuffered Ethernet schedulably feasible by one cycle. That is a statement about
the SCHEDULER. It says nothing about whether the engine can put the edge where
the protocol wants it in the first place. For 10 Mbit Manchester the mid-bit
edge falls at 50 ns, which is 2.5 cycles at 50 MHz -- not placeable. No
scheduling policy, buffer width or deadline reading fixes a grid that does not
contain the required instant.

⭐ THE GENERAL FORM, so this is a lane property rather than an Ethernet anecdote:
quantization error is +/- half a cycle for any off-grid edge, and what decides
whether it matters is the ratio of that error to the protocol's own smallest
nominal interval. 10 ns against Ethernet's 50 ns half-bit is 20%; the same 10 ns
against I2C's 1300 ns minimum low time is 0.8%.

⚠ WHAT THIS FILE DOES NOT DO. It does not decide Ethernet. It computes the
engine-side distortion so the IEEE 802.3 Clause 14 transmit-jitter budget has a
number to be compared against. That document is not in `refs/` and is not quoted
here. If the spec's allowance is below the distortion, Ethernet is out at 50 MHz
for a GRID reason and the reinstatement condition is a clock change, not a
design change.
"""

from __future__ import annotations

import sys
from fractions import Fraction

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

F_CLK = 50_000_000
NS = 1e9


def cycles(seconds: float) -> Fraction:
    return Fraction(seconds).limit_denominator(10 ** 12) * F_CLK


# name, the edge the protocol requires, its nominal time, the protocol's own
# smallest nominal interval that the error eats into
EDGES = [
    ("UART 115200", "bit boundary", 1 / 115200, 1 / 115200),
    ("SPI 1 MHz", "SCLK edge (half-bit)", 0.5e-6, 0.5e-6),
    ("I2C 400 kHz", "SCL edge (half-period)", 1.25e-6, 1.3e-6),
    ("10 Mbit Ethernet", "Manchester MID-BIT", 50e-9, 50e-9),
]


def main() -> int:
    print()
    print("=" * 78)
    print("SPEC C3 -- edge placement against a %d MHz grid (%.0f ns/cycle)"
          % (F_CLK // 1_000_000, NS / F_CLK))
    print("=" * 78)
    print("  %-18s %-22s %-10s %-9s %-9s %s"
          % ("lane", "edge", "nominal", "cycles", "err ns", "err / interval"))
    worst = None
    for name, edge, t, interval in EDGES:
        c = cycles(t)
        frac = c - int(c)
        # distance to the nearest grid point, in cycles
        off = min(frac, 1 - frac) if frac else Fraction(0)
        err_ns = float(off) * NS / F_CLK
        ratio = err_ns / (interval * NS)
        flag = ""
        if ratio > 0.05:
            flag = "  <== MATERIAL"
            if worst is None or ratio > worst[1]:
                worst = (name, ratio, err_ns)
        print("  %-18s %-22s %-10s %-9s %-9.1f %6.2f%%%s"
              % (name, edge, "%.1f ns" % (t * NS), str(c), err_ns,
                 ratio * 100, flag))
    print()
    print("  'cycles' is exact. A non-integer value means the engine CANNOT")
    print("  place that edge; it rounds to a grid point and the error is")
    print("  systematic, not jitter -- it does not average out and no deadline")
    print("  reading removes it.")
    print()

    if worst is None:
        print("  No lane carries a material quantization error at this clock.")
        return 0

    name, ratio, err = worst
    print("=" * 78)
    print("  %s -- the binding case" % name)
    print("=" * 78)
    print("  Manchester requires a transition at the CENTRE of every bit.")
    print("  100 ns bit period / 2 = 50 ns = %s cycles at %d MHz."
          % (cycles(50e-9), F_CLK // 1_000_000))
    print("  Placeable only at 2 cycles (40 ns) or 3 cycles (60 ns):")
    print("    systematic error  +/- %.0f ns  =  %.0f%% of the 50 ns half-bit"
          % (err, ratio * 100))
    print("  And that is BEFORE scheduling jitter. At the gate-0.9 bound")
    print("  delta_max = r - C = 1 cycle, the budget becomes:")
    half_bit_ns = 50.0
    total = err + NS / F_CLK
    print("    grid %.0f ns + schedule %.0f ns = %.0f ns of a %.0f ns half-bit (%.0f%%)"
          % (err, NS / F_CLK, total, half_bit_ns, total / half_bit_ns * 100))
    print()
    # ---- the spec window, now sourced -----------------------------------
    print("=" * 78)
    print("  THE 802.3 WINDOW -- sourced, and it decides the question")
    print("=" * 78)
    print("  IEEE Std 802.3-2015, Section One (refs/8023_2015_section1.pdf).")
    print("  Annex B.4.3.3, the ABSOLUTE placement form of 14.3.1.2.3:")
    print('    mid-bit zero crossings constrained to "46.5 ns to 53.5 ns"')
    print("      -> +/- 3.5 ns, EXTERNAL MAU")
    print('    "when measuring an integrated MAU ... 44.5 ns to 55.5 ns"')
    print("      -> +/- 5.5 ns, INTEGRATED MAU (the generous reading, and ours)")
    print("  14.3.1.2.3 itself: jitter added through the twisted-pair model")
    print('    shall be "no more than +/-3.5 ns".')
    print()
    EXT, INT = 3.5, 5.5
    print("  %-28s %-10s %-10s %s" % ("budget", "ours", "allowed", "verdict"))
    print("  %-28s %-10s %-10s %s"
          % ("grid error alone", "%.0f ns" % err, "%.1f ns" % INT,
             "*** NON-CONFORMANT (%.1fx over)" % (err / INT)))
    print("  %-28s %-10s %-10s %s"
          % ("grid + schedule (d_max=1)", "%.0f ns" % total, "%.1f ns" % INT,
             "*** NON-CONFORMANT (%.1fx over)" % (total / INT)))
    print()
    print("  ⛔⛔ THE GRID ERROR ALONE IS %.1fx THE MOST GENEROUS WINDOW." % (err / INT))
    print("     So this is NOT repairable by a shadow register. Buffering removes")
    print("     the SCHEDULER's 20 ns and leaves the grid's 10 ns, which is still")
    print("     outside +/-5.5 ns. 10BASE-T transmit is OUT OF SCOPE AT 50 MHz.")
    print()
    print("  ⛔ AND IT CANNOT BE DITHERED. B.4.3.3 requires that *all* zero")
    print("     crossings fall within the interval, so alternating 40/60 ns to")
    print("     average 50 ns does not conform -- the mean is not the constraint.")
    print()
    print("  REINSTATEMENT, now computable against a real window. With bit period")
    print("  B = f/10 cycles, an EVEN B places the mid-bit exactly; an ODD B")
    print("  misses by P/2 = 50/B ns:")
    print("    %-9s %-5s %-11s %-9s %s"
          % ("f_clk", "B", "mid-bit", "err ns", "conforms?"))
    for f in (50, 60, 70, 80, 90, 100, 110, 150):
        B = Fraction(f, 10)
        if B.denominator != 1:
            continue
        B = int(B)
        e = 0.0 if B % 2 == 0 else 50.0 / B
        v = ("exact" if e == 0 else
             "ok (integrated)" if e <= INT else "NO")
        print("    %-9s %-5d %-11s %-9.2f %s"
              % ("%d MHz" % f, B, "%s cyc" % Fraction(B, 2), e, v))
    print("    => any multiple of 20 MHz is exact; 60 MHz is the cheapest fix.")
    print("       Odd multiples of 10 MHz only conform from 110 MHz up.")
    print()
    print("  ⚠ EDITION BOUNDARY: this is 802.3-2015 (title page verified, approved")
    print("    3 Sep 2015). 802.3-2022 Section One could not be obtained -- IEEE's")
    print("    GET program now serves through Xplore, which refuses non-browser")
    print("    clients. Clause 14 has been editorially stable for decades, but the")
    print("    2022 wording was NOT read. Cite the 2015 edition.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
