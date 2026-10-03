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
    print("  ⛔ REINSTATEMENT CONDITION, derived rather than guessed. The mid-bit")
    print("     instant is on the grid iff 50 ns * f_clk is an integer, i.e. iff")
    print("     f_clk is a multiple of 20 MHz:")
    for f in (20, 40, 50, 60, 80, 100):
        c = Fraction(50e-9).limit_denominator(10 ** 12) * f * 1_000_000
        print("       %3d MHz -> half-bit = %-6s %s"
              % (f, str(c), "ON GRID" if c.denominator == 1 else "off grid"))
    print("     So 60, 80 or 100 MHz place it exactly; 50 MHz cannot. The")
    print("     alternative is fractional edge placement (a delay line or DDR")
    print("     output), which a single-clock-domain 130 nm tile does not give.")
    print()
    print("  ⚠ THE DECISION NEEDS THE TEXT. If IEEE 802.3 Clause 14's transmit")
    print("     jitter allowance at the MDI is below %.0f ns, Ethernet is OUT AT" % err)
    print("     50 MHz for a GRID reason -- independent of gate 0.9, and not")
    print("     repairable by any buffer width. That number is not in refs/ and")
    print("     is deliberately not guessed here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
