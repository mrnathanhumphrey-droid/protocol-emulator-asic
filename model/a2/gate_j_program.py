"""Ruling 1(b) -- J is a DERIVED FUNCTION of the program, not one number.

THE ONE CLAIM: `J` follows from the refill/queueing structure given the
program's minimum inter-action delay, and both numbers that matter are
published -- the shipped program's `J` and the universal worst case over every
ADMISSIBLE program.

⛔⛔ WHY "ONE J" WAS ALWAYS WRONG. This project quoted `J = 5`, then derived
`J = 8`, and both were presented as properties of the design. They are
properties of a PROGRAM running on the design. The sweep makes that
unmistakable: the stall is 5 cycles at `d = 8` and ZERO from `d = 11` upward,
and the shipped lanes sit at `d >= 25`. A single `J` either understates the
programs we have not written or overstates the one we ship.

THE DERIVATION, from the prefetch FSM rather than from the measurement:

  L_REFILL = 4    one refill occupies the prefetch FSM for 4 cycles:
                  P_SCAN notices (1) + P_REQ -> P_WAIT -> P_CAP (3). The 3 is
                  forced by the hardware, not chosen: the arbiter REGISTERS the
                  request and the store read is itself registered, so data
                  asked for in P_REQ is valid two cycles later.

  WINDOW = d + C  with double buffering, a lane's spare must be refilled
                  between two of its consecutive dispatches -- the action delay
                  plus its own service.

  demand = k * L_REFILL     k lanes each need one refill inside that window,
                            and the FSM is a SINGLE SERVER, so refills
                            serialise.

  shortfall = max(0, k*L_REFILL - (d_min + C))

  L_CAP = 7       ⭐ AND THE SHORTFALL IS CAPPED, which is what keeps the bound
                  usable. P_SCAN serves the EDF WINNER FIRST when its head is
                  empty, so AT MOST ONE other refill can be ahead of a stalling
                  lane's: the in-flight one finishes (<= 3), P_SCAN takes the
                  winner (1), its own refill completes (3) = 7. Without
                  winner-first the queue would be k deep and this cap would not
                  exist -- the policy is load-bearing for the BOUND, not just
                  for the average.

  J_stall(d_min, k) = min(shortfall, L_CAP)
  J(d_min, k)       = J_stall + J_WINNER_REG

⭐ THE SHIPPED PROGRAM FALLS OUT AT J = 1. Its tightest inner spacing is 25
cycles (SPI and SPI-target at 1 MHz on a 50 MHz clock), so the shortfall is
`max(0, 20 - 27) = 0` and only the winner-registration cycle survives. That is
derived, and the measurement agrees (stall 0 over 3,700 cycles).

⛔ ADMISSIBILITY BOUNDS THE SWEEP, and ignoring that would manufacture a worse
`J` than any admissible program can produce. At `d < 8` the five-lane set has
`U = N*C/(d+C) > 1` -- an OVERLOADED system, infeasible by condition (1), where
stalls come from the engine being saturated rather than from refill latency.
Those points are reported and EXCLUDED from the universal maximum, because `J`
is a bound over admissible programs.
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

N_LANES = 5
C_SVC = 2
L_REFILL = 4          # P_SCAN(1) + P_REQ/P_WAIT/P_CAP(3)
L_CAP = 7             # in-flight(3) + scan(1) + own(3), via winner-first
J_WINNER_REG = 1      # registering the EDF winner; structural, never stalls

# The shipped program's tightest inner action spacing, in cycles at 50 MHz.
# SPI-master and SPI-target both run 1 MHz => 25 cycles per bit.
D_MIN_SHIPPED = 25

# =========================================================================
# THE RECORDED SWEEP
# =========================================================================
# Produced by: for each d, `python test/make_smoke_image.py --five d d+1 .. d+4`
# then the smoke bench with +IMG=test/five_image.hex, reading
# "max prefetch stall, STEADY". Five ACTIVE lanes, double-buffered,
# prime-before-release in place.
#
# ⛔ RECORDED, NOT RE-RUN, for the same reason as the TChecker verdicts: this
# gate must have an opinion on a machine with no iverilog. `price_j_sweep.sh`
# is what re-measures it, and a sim value ABOVE the derivation stops everything.
#
# d -> measured steady-state stall (double buffer, primed)
SWEEP = {
    2: 5, 3: 5, 4: 5, 5: 5, 6: 5, 7: 5, 8: 5, 9: 5, 10: 4,
    11: 0, 12: 0, 13: 0, 14: 0, 15: 0, 16: 0, 18: 0, 20: 0, 25: 0,
}
# The single-buffer arm, same sweep, for the double buffer's price.
SWEEP_SINGLE = {
    2: 5, 3: 5, 4: 5, 5: 5, 6: 5, 7: 8, 8: 8, 9: 8, 10: 8,
    11: 3, 12: 4, 13: 3, 14: 2, 15: 1, 16: 0, 18: 0, 20: 0, 25: 0,
}


def utilisation(d: int, k: int = N_LANES) -> float:
    return k * C_SVC / float(d + C_SVC)


def admissible(d: int, k: int = N_LANES) -> bool:
    """Condition (1). ⛔ `<= 1.0` with a tolerance, because d = 8 lands on
    EXACTLY 1.0 and a float compare must not silently drop the boundary case --
    which is the tightest admissible point and therefore the one that sets the
    universal maximum."""
    return utilisation(d, k) <= 1.0 + 1e-12


def j_stall(d_min: int, k: int = N_LANES) -> int:
    shortfall = max(0, k * L_REFILL - (d_min + C_SVC))
    return min(shortfall, L_CAP)


def j_of(d_min: int, k: int = N_LANES) -> int:
    return j_stall(d_min, k) + J_WINNER_REG


def main() -> int:
    print()
    print("=" * 78)
    print("J AS A FUNCTION OF THE PROGRAM (Ruling 1(b))")
    print("=" * 78)
    print("  L_REFILL=%d  L_CAP=%d  J_WINNER_REG=%d  N_LANES=%d  C=%d"
          % (L_REFILL, L_CAP, J_WINNER_REG, N_LANES, C_SVC))

    print()
    print("  --- the derivation against the recorded sweep ---")
    print("    %-5s %-8s %-7s %-10s %-10s %s"
          % ("d", "U", "adm?", "derived", "measured", "verdict"))
    violations, inadmissible = [], []
    for d in sorted(SWEEP):
        der = j_stall(d)
        sim = SWEEP[d]
        adm = admissible(d)
        if not adm:
            inadmissible.append(d)
        bad = sim > der
        if bad and adm:
            violations.append((d, der, sim))
        print("    %-5d %-8.3f %-7s %-10d %-10d %s"
              % (d, utilisation(d), "yes" if adm else "NO", der, sim,
                 "*** SIM > DERIVED ***" if bad else
                 ("ok" if adm else "ok (excluded: U>1)")))

    # ⛔⛔ THE MUST-STOP. A measurement cannot RAISE a bound -- if simulation
    # exceeds the derivation on an admissible program, the derivation is wrong
    # and every published r_i rests on it. This is the same rule that made the
    # C/J work a re-derivation rather than a re-measurement.
    if violations:
        print()
        print("    ⛔⛔ SIMULATION EXCEEDS THE DERIVED BOUND on %d admissible"
              % len(violations))
        print("        point(s): %s" % (violations,))
        print("        A measurement cannot raise a bound. The derivation is")
        print("        WRONG and nothing downstream is usable. STOP.")
        return 1
    print()
    print("    ⇒ sim <= derived at every ADMISSIBLE point (%d of %d swept)"
          % (len(SWEEP) - len(inadmissible), len(SWEEP)))
    if inadmissible:
        print("    ⚠ EXCLUDED, U > 1 (overloaded, infeasible by condition (1)):")
        print("      d = %s. Their stalls are the engine being saturated, not"
              % ", ".join(str(d) for d in inadmissible))
        print("      refill latency, and J is a bound over ADMISSIBLE programs.")
        print("      ⛔ Including them would manufacture a worse J than any")
        print("      admissible program can produce.")

    # ---- the two published numbers -------------------------------------
    adm_ds = [d for d in SWEEP if admissible(d)]
    d_worst = min(adm_ds)
    universal_derived = max(j_of(d) for d in adm_ds)
    universal_measured = max(SWEEP[d] for d in adm_ds) + J_WINNER_REG
    shipped = j_of(D_MIN_SHIPPED)

    print()
    print("  --- THE TWO PUBLISHED NUMBERS ---")
    print("    SHIPPED PROGRAM   d_min = %d  ->  J = %d"
          % (D_MIN_SHIPPED, shipped))
    print("      stall %d (shortfall max(0, %d - %d) = 0) + winner reg %d."
          % (j_stall(D_MIN_SHIPPED), N_LANES * L_REFILL,
             D_MIN_SHIPPED + C_SVC, J_WINNER_REG))
    print("      ⭐ derived, and the measurement agrees: steady stall 0.")
    print("    UNIVERSAL WORST CASE over admissible programs  ->  J = %d"
          % universal_derived)
    print("      attained at the tightest admissible d = %d (U = %.3f)"
          % (d_worst, utilisation(d_worst)))
    print("      measured maximum over the same range: J = %d"
          % universal_measured)
    print("      ⚠ THE PUBLISHED NUMBER IS THE DERIVED ONE (%d), NOT THE"
          % universal_derived)
    print("      MEASURED ONE (%d). A measurement is a FLOOR on the true"
          % universal_measured)
    print("      maximum -- one program, one lane mix, one phase -- and this")
    print("      project already shipped `C = 2.00` as a mean and `J = 5` as a")
    print("      bound once. The derivation is what the proof uses.")

    # ---- what the double buffer buys, in the same units ----------------
    print()
    print("  --- the double buffer, priced on the same sweep ---")
    worst_d = max(SWEEP[d] for d in adm_ds)
    worst_s = max(SWEEP_SINGLE[d] for d in adm_ds)
    print("    worst measured stall, admissible d:  double %d   single %d"
          % (worst_d, worst_s))
    print("    ⇒ J (measured floor):                double %d   single %d"
          % (worst_d + J_WINNER_REG, worst_s + J_WINNER_REG))
    print("    ⭐ 169 flops for %d cycles of universal worst-case J. At the"
          % (worst_s - worst_d))
    print("    SHIPPED program both are 0, so this is insurance for programs")
    print("    we have not written -- which is exactly what a bound over")
    print("    admissible programs is for.")

    # ---- the admissibility hook ---------------------------------------
    print()
    print("  --- d_min AS AN ADMISSIBILITY INPUT (1.6t) ---")
    print("    The loader computes the program's J from its own d_min, the way")
    print("    every other admissibility condition is a property the loader")
    print("    CHECKS rather than a promise the programmer makes.")
    print("    %-10s %-8s %-8s %s" % ("d_min", "J", "adm?", "note"))
    for d in (4, 8, 10, 12, 18, 25, 434):
        print("    %-10d %-8d %-8s %s"
              % (d, j_of(d), "yes" if admissible(d) else "NO -- U>1",
                 "the shipped program" if d == D_MIN_SHIPPED else
                 ("tightest admissible" if d == 8 else "")))
    print("    ⛔ A program with d_min below the admissible floor is REJECTED by")
    print("    condition (1) before J is even asked about -- the two checks")
    print("    compose, and J is only meaningful inside the feasible region.")

    print()
    print("=" * 78)
    print("  GATE j-program: PASSED")
    print("    * J(d_min, k) derived from the refill FSM, not fitted to the sweep")
    print("    * sim <= derived at every admissible swept point")
    print("    * published: shipped J = %d, universal derived J = %d"
          % (shipped, universal_derived))
    print("    * ⛔ a measurement can falsify this bound, never raise it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
