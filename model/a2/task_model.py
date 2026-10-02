"""A2 — the REAL task set, computed. Not a derivation; the numbers it must aim at.

⛔⛔ THIS DOES NOT PROVE A2. Wilson owns the derivation. This computes the concrete
instance so the derivation has something to hit, and so claims about "a handful of
scheduling points" or "the closed form breaks at Ethernet" are MEASURED rather than
asserted. Every number here comes out of the lane table in ARCH_PREREG_01.

Notation per Wilson's §1 (the Q collision is dead):
    N    lanes          C_i  per-lane worst-case service      T_i  period
    L    busy period    m_i  = ceil(L / T_i), instances of i in L
"""

from __future__ import annotations

import sys
from math import gcd, ceil

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

F_CLK = 50_000_000

# ARCH_PREREG_01's lane table, verbatim: "At 50 MHz, one event per bit",
# "engine busy at 2 clk/event".
C_EVENT = 2

# ⛔⛔ THE EVENT PERIOD IS NOT THE BIT PERIOD, AND GETTING THAT WRONG HALVED U.
# A first version of this file used clks/bit as T_i for every lane and produced
# U = 0.0606 against the pre-reg's stated 11.7% -- a 2x disagreement, and the
# PRE-REG WAS RIGHT. The cause: a clocked protocol emits TWO engine events per bit
# (drive the clock high, drive it low); only UART, which has no clock line, emits
# one. Reproducing the pre-reg's table exactly is the check that the task model is
# the same task model the architecture was sized against.
#
#   lane          clks/bit   events/bit   T_event   C_i   duty = C/T   pre-reg
#   UART 115200       434         1          434     2      0.46%       0.5%
#   SPI 1 MHz          50         2           25     2      8.00%       8.0%
#   I2C 400 kHz       125         2           62*    2      3.23%       3.2%
#   Ethernet            5         1            5     2     40.00%      40.0%
#   * 125/2 = 62.5; rounded DOWN to 62, which makes the lane slightly FASTER than
#     reality. Rounding a period down is the conservative direction for a bound.
LANES = [
    # name,            T_event (clk),  C_i
    ("UART 115200",    434,            C_EVENT),
    ("SPI 1 MHz",       25,            C_EVENT),
    ("I2C 400 kHz",     62,            C_EVENT),
]
ETHERNET = ("10 Mbit Ethernet", 5, C_EVENT)


def lcm(a, b):
    return a * b // gcd(a, b)


def busy_period(lanes):
    """L = fixpoint of W(t) = Σ ceil(t/T_i)·C_i, starting at Σ C_i (Spuri Eq 1).
    Converges iff U ≤ 1."""
    L = sum(c for _, _, c in lanes)
    for _ in range(10_000):
        nxt = sum(ceil(L / t) * c for _, t, c in lanes)
        if nxt == L:
            return L
        L = nxt
    return None


def report(lanes, label):
    U = sum(c / t for _, t, c in lanes)
    N = len(lanes)
    print("=" * 72)
    print("%s   N = %d lanes" % (label, N))
    print("  %-20s %-10s %-6s %-10s" % ("lane", "T_i (clk)", "C_i", "C_i/T_i"))
    for n, t, c in lanes:
        print("  %-20s %-10d %-6d %.4f" % (n, t, c, c / t))
    print("  %-20s %-10s %-6s %.4f   %s"
          % ("TOTAL U", "", "", U,
             "FEASIBLE (U<=1)" if U <= 1 else "*** U > 1: OVERSUBSCRIBED ***"))

    L = busy_period(lanes)
    print()
    print("  busy period L = %s cycles   (Spuri Eq 1 fixpoint)" % L)
    if L is None:
        print("  *** did not converge")
        return
    print("  %-20s %-8s %s" % ("lane", "m_i", "= ceil(L/T_i), instances in L"))
    ms = []
    for n, t, c in lanes:
        m = ceil(L / t)
        ms.append(m)
        print("  %-20s %-8d %s" % (n, m, "<-- MULTIPLE" if m > 1 else ""))

    # ⭐ Wilson's validity condition for the closed form
    all_single = all(m == 1 for m in ms)
    print()
    print("  closed form valid (every m_i == 1)?  %s" % all_single)

    # the closed form, per lane
    print()
    print("  %-20s %-14s %-14s %s"
          % ("analysed lane", "closed form", "margin vs D?", "note"))
    for i, (n, t, c) in enumerate(lanes):
        others = sum(cj for j, (_, _, cj) in enumerate(lanes) if j != i)
        blk = max([cj for j, (_, _, cj) in enumerate(lanes) if j != i] or [1]) - 1
        cf = others + blk
        print("  %-20s %-14d %-14s %s"
              % (n, cf, "-", "Σ_other C_j + max(C_k−1) = %d + %d" % (others, blk)))

    # hyperperiod and the scheduling-point count
    H = 1
    for _, t, _ in lanes:
        H = lcm(H, t)
    pts = sum(H // t for _, t, _ in lanes)
    print()
    print("  hyperperiod H = lcm(periods) = %d cycles  (%.3f ms at %d Hz)"
          % (H, H / F_CLK * 1000, F_CLK))
    print("  distinct release points in [0,H]: %d" % pts)
    print("  distinct release points in [0,L]: %d"
          % sum(ceil(L / t) for _, t, _ in lanes))
    return L, H, pts


def main() -> int:
    print("A2 TASK MODEL — the real instance, computed")
    print("source: ARCH_PREREG_01 lane table; C_i = %d clk/event as pre-registered"
          % C_EVENT)
    print()
    report(LANES, "THE THREE REQUIRED PROTOCOLS")
    print()
    report(LANES + [ETHERNET], "WITH THE ETHERNET STRETCH GOAL")

    print()
    print("=" * 72)
    print("WHAT THESE NUMBERS SAY")
    print("=" * 72)
    L3 = busy_period(LANES)
    L4 = busy_period(LANES + [ETHERNET])
    print("  * the three required protocols: busy period %d cycles, every m_i = 1," % L3)
    print("    so the closed form IS valid there and the bound is single digits.")
    print("  * with Ethernet: busy period %d cycles and Ethernet contributes" % L4)
    print("    m = %d instances -- the closed form counts it ONCE and therefore"
          % ceil(L4 / 5))
    print("    UNDER-states the true response. Wilson's validity condition and his")
    print("    prediction that it breaks at Ethernet are both confirmed.")
    print("  * ⛔ THE DEADLINE D_i IS THE MISSING INPUT. Feasibility is r_i <= D_i,")
    print("    and NOTHING in the pre-reg or any rung has ever defined D_i. Until a")
    print("    per-lane deadline is derived from each protocol's tolerance, neither")
    print("    the feasibility test NOR the bound can be checked against anything.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
