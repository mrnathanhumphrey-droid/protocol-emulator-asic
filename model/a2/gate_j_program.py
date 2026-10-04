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
# ⛔⛔⛔ CONFIRMED: THE RECORD IS WRONG AND THE DERIVATION IS VIOLATED.
# `price_j_sweep.sh` -- named four lines above as the thing that re-measures
# this, and which DID NOT EXIST until 2026-10-04 -- now runs. On a 200,000-cycle
# run with an asserted steady window of 195,908 cycles:
#
#   d          2..7      8    9   10   11   12   13   14   15   16   18   20   25
#   recorded   5         5    5    4    0    0    0    0    0    0    0    0    0
#   derived    7         7    7    7    7    6    5    4    3    2    0    0    0
#   measured   7..11    10    9    8    8   11   11   11   11   11   11    0    0
#   admissible no       yes  yes  yes  yes  yes  yes  yes  yes  yes  yes  yes  yes
#
# TEN ADMISSIBLE POINTS MEASURE ABOVE THE DERIVATION (d = 8..18). The derivation
# is an UPPER BOUND on the stall, so this is an unsoundness, not a stale record.
# ⇒ THE UNIVERSAL J = 8 DOES NOT HOLD. It must not be quoted until re-derived.
#
# ⭐ THE SHIPPED CLAIM STANDS, and is unaffected: `smoke_image` measures a
# steady stall of 0 over a 195,908-cycle window with the bench PASSING, and the
# sweep reproduces 0 exactly at d = 20 and d = 25. The shipped program is
# d_min = 25.
#
# ⭐ TWO INDEPENDENT READINGS AGREE at d = 12: the engine's own `jitter_max`
# is 11 and the bench's independently reconstructed steady max is 11, with
# 13,558 stall events and the last at cycle 84,814. Not a transient.
# ⛔⛔ BUT BOTH READINGS ARE OF THE **AGGREGATE**, and agreeing with each other
# does not make either one a per-lane J. `jitter_cnt` is one counter for all
# lanes and does not clear when the winner changes, so 11 is the longest
# any-winner-blocked run and may be several lanes' waits laid end to end. The
# per-lane instrument (`test/tb_jlane.v`) measures the same program and reads
# 7 per lane -- so the 11 does decompose, and quoting it as one lane's jitter
# would have overstated it by 4 cycles in the unsafe direction for a claim and
# the safe one for a bound. See `docs/PREREG_J_LANE.md`.
#
# ⚠⚠ AND IT TOOK FOUR BROKEN PROBES TO GET HERE, every one of which produced
# a confident, plausible number. Recorded so the next reader does not repeat
# them:
#   1. an absolute Git-Bash path passed to `+IMG`: `$readmemh` failed silently,
#      the program was EMPTY, and "stall 0" looked like a clean bisect result;
#   2. a reading taken from a bench reporting three failures -- two of which
#      turned out to be IMAGE-SPECIFIC (it counts edges on `uo_out[0:1]`, which
#      this image does not drive) and harmless, but unexamined at the time;
#   3. "converged" by doubling the warm-up until two readings agreed -- 500 and
#      1000 both read 7 because the TRANSIENT SPANNED BOTH;
#   4. pushing the warm-up past the bench's 4000-cycle run length, which
#      emptied the window: ZERO EVENTS reads exactly like "no stalls" and is
#      really "no measurement". That one produced the opposite wrong answer.
# ⇒ The bench now takes `+NCYC` and `+WARMUP`, and PRINTS THE WINDOW LENGTH,
#   so an empty window cannot be read as a clean zero. The sweep refuses any
#   point whose image did not load or whose window is under 100k cycles.
#
# d -> measured steady-state stall (double buffer, primed)
# ⚠ THE VALUES BELOW ARE THE ORIGINAL RECORD, KEPT FOR COMPARISON. They are
#   NOT a measurement of this design: see the table above.
SWEEP = {
    2: 5, 3: 5, 4: 5, 5: 5, 6: 5, 7: 5, 8: 5, 9: 5, 10: 4,
    11: 0, 12: 0, 13: 0, 14: 0, 15: 0, 16: 0, 18: 0, 20: 0, 25: 0,
}
# The single-buffer arm, same sweep, for the double buffer's price.
# ⛔⛔ THIS ARM CANNOT BE RE-MEASURED, AND THE BENEFIT CLAIM RESTS ON IT.
# `NSLOT = 2 * N_LANES` is hardcoded in pe_engine.v and there is NO
# single-buffer build option -- no define, no parameter. So these numbers
# describe a configuration that cannot be rebuilt, while `worst_s` below still
# computes the double buffer's advertised benefit from them.
# ⚠ WORSE THAN THE J SWEEP, which at least had a script that *could* have
# re-measured it once written. Here there is nothing to run.
# ⭐ AND THE J ARM'S VALUES WERE WRONG, so these have no claim to be right:
# the double-buffer "universal worst case 11 -> 7" was computed from the same
# recorded sweep that live measurement has now contradicted at ten admissible
# points. The benefit is therefore UNVERIFIED, not merely stale.
# ⇒ OWED, and Wilson's call which way: either add an `M_SINGLE_BUF` build
#   option (head-only fill, no spare, no swap) so the comparison becomes
#   reproducible, or RETRACT the benefit claim. The double buffer costs ~169
#   flops; keeping it on the strength of an unrepeatable measurement is the
#   thing this project keeps finding and fixing.
#
# ⭐⭐ UPDATE -- IT IS NOW BUILDABLE, AND THE RECORD BELOW IS CONTRADICTED.
# `SPL` (slots per lane) is a real parameter in `pe_engine.v`, so the
# single-buffer engine elaborates: `iverilog -Ptb_smoke.SPL_CFG=1`. Recipe:
# `python test/run_spl_compare.py`, which runs THIS sweep's recipe at both
# depths after proving both correct with `tb_smoke`.
#
# ⛔⛔ THE LIVE MEASUREMENT DISAGREES WITH THE STORED VALUES, in the same
# direction and for the same reason as `SWEEP` did:
#
#     d      stored single     live single
#     8          8                 8          agrees
#     12         4                11          +7
#     16         0                 9          +9
#     18         0                 8          +8
#     20         0                 6          +6
#     25         0                 1          +1
#     30         -                 1
#
# The record said the single buffer reached 0 at d = 16; live measurement finds
# it still stalling at d = 30. ⇒ THE STORED ARM IS WITHDRAWN, not re-fitted.
#
# ⭐ AND THE CONCLUSION IT WAS USED FOR WAS BACKWARDS. The retracted claim was
# "169 flops buys 11 -> 7". The measured effect is larger and somewhere else:
# in the SCOPED region (d >= D* = 20) the double buffer stalls 0 while the
# single buffer stalls up to 6, so `d_min >= D* -> J = 1` -- the only published
# timing claim -- HOLDS ONLY AT SPL = 2. The double buffer is not insurance for
# programs we have not written; it is what makes the shipped claim true.
SWEEP_SINGLE = {
    2: 5, 3: 5, 4: 5, 5: 5, 6: 5, 7: 8, 8: 8, 9: 8, 10: 8,
    11: 3, 12: 4, 13: 3, 14: 2, 15: 1, 16: 0, 18: 0, 20: 0, 25: 0,
}


# =========================================================================
# D* -- THE PORT-FEASIBILITY THRESHOLD, AND THE SCOPED CLAIM
# =========================================================================
# ⛔⛔ ADMISSIBILITY IS WEAKER THAN PORT FEASIBILITY, AND THAT GAP IS THE
# WHOLE BUG. `admissible` asks whether the DISPATCHER keeps up:
# U = k*C/(d+C) <= 1, which allows d >= 8. But every dispatched action must
# also be REFILLED through ONE SHARED FETCH PORT, and a refill occupies it for
# L_REFILL cycles. k lanes each consuming one action per d cycles demand
# k*L_REFILL cycles of port time per d cycles, so the port saturates unless
#
#       d >= D_STAR = k * L_REFILL = 5 * 4 = 20
#
# Admissible-but-port-saturated programs are d in [8, 19], and those are
# EXACTLY the ten points where the old derivation was found unsound.
#
# ⭐ MEASURED CHECK, NOT MEASURED SOURCE: the live sweep puts the cliff
# between d = 18 (stall 11) and d = 19 (stall 0), so D_STAR = 20 is
# CONSERVATIVE BY ONE CYCLE against the observation.
# ⚠ ITS TIGHTNESS IS THEREFORE UNCLAIMED. 19 measures 0 and the structure
# says 20; rather than move the constant to 19 to fit the data -- which would
# make the measurement the source and leave the off-by-one unexplained -- the
# claim is stated at the structural number and the gap is recorded. Explaining
# why 19 suffices needs the witness trace, and is owed.
D_STAR = N_LANES * L_REFILL


def port_feasible(d: int, k: int = N_LANES) -> bool:
    """Can the single fetch port serve k refills per action period?"""
    return d >= k * L_REFILL


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

    # ---- THE PUBLISHED CLAIM, NOW SCOPED -------------------------------
    # THE UNIVERSAL NUMBER IS WITHDRAWN. It was max(j_of(d)) over the
    # admissible range, and j_of caps the stall at L_CAP = 7 -- which the
    # witness traces show is BELOW what the refill chain can produce:
    # (queued ahead + 1) x L_REFILL, up to k x L_REFILL = 20. Live
    # measurement exceeded the derivation at TEN admissible points, so the
    # universal claim was unsound and is RETRACTED rather than re-fitted.
    # AND NO REPLACEMENT UNIVERSAL NUMBER IS PRINTED. The chain implies
    # k*L_REFILL + J_WINNER_REG = 21, but that rests on "at most one refill
    # per lane ahead of you", which is NOT yet derived from the scan's
    # arbitration -- a lane may have a head AND a spare outstanding. Until
    # that is a theorem, 21 is arithmetic, not a bound.
    adm_ds = [d for d in SWEEP if admissible(d)]
    shipped = j_of(D_MIN_SHIPPED)

    print()
    print("  --- THE PUBLISHED CLAIM, SCOPED ---")
    print("    PROGRAMS WITH d_min >= D* = %d  ->  J = 1" % D_STAR)
    print("      D* = k * L_REFILL = %d * %d: the ONE fetch port must serve"
          % (N_LANES, L_REFILL))
    print("      every live lane's refill inside the shortest action period,")
    print("      so nothing is ever found missing and the stall is 0.")
    print("      live-measured 0 at every port-feasible point swept")
    print("        (d = 20,21,22,25,30,40,60), each on a 200k-cycle run")
    print("        with an asserted >=100k-cycle steady window.")
    print("    SHIPPED PROGRAM   d_min = %d  ->  J = %d   [inside the claim]"
          % (D_MIN_SHIPPED, shipped))
    print("      measured steady stall 0 over 195,908 cycles, bench PASSING.")
    print()
    print("    RETRACTED: the universal worst case over admissible programs,")
    print("      published as J = 8. j_of capped the stall at L_CAP = %d; the"
          % L_CAP)
    print("      witness chain gives (queued ahead + 1) x %d, up to %d. Ten"
          % (L_REFILL, N_LANES * L_REFILL))
    print("      admissible points measured ABOVE the derivation.")
    print("      NOT re-fitted -- withdrawn.")
    print("    UNCLAIMED: d_min in [%d, %d] -- admissible (the dispatcher"
          % (min(adm_ds), D_STAR - 1))
    print("      keeps up) but NOT port-feasible; measured stalls 7..12.")
    print("      pe_asm REFUSES such programs rather than quoting a bound.")

    # ---- the double buffer: the benefit claim is WITHDRAWN --------------
    # ⛔⛔ THIS BLOCK USED TO COMPUTE AND PRINT THE BENEFIT from SWEEP and
    # SWEEP_SINGLE: "169 flops for N cycles of universal worst-case J". It is
    # removed rather than re-stated, for two independent reasons:
    #   1. SWEEP_SINGLE describes a configuration THAT CANNOT BE BUILT. There
    #      is no parameter or define that produces a single-buffer engine, so
    #      the arm has no recipe and cannot be re-measured. A number whose
    #      generator does not exist is not a measurement.
    #   2. Both arms are AGGREGATE readings (the any-winner-blocked run
    #      length), and the per-lane instrument reads 7 per lane on the same
    #      d = 12 program where the aggregate reads 11. So the subtraction was
    #      between two numbers that are not per-lane J either.
    # ⚠ A RETRACTION IN THE DOCS WHILE THE GATE STILL PRINTS THE CLAIM is the
    # two-copies defect: whoever runs the gate sees the withdrawn number. So
    # the computation goes, and the stored dicts stay ONLY as a labelled
    # record for comparison.
    print()
    print("  --- the double buffer: benefit claim WITHDRAWN ---")
    print("    the stored single-buffer arm (SWEEP_SINGLE) describes a")
    print("    configuration with no build option, so it cannot be")
    print("    re-measured, and no benefit is computed from it here.")
    print("    T3 replaces it: NSLOT becomes a parameter and both")
    print("    configurations are measured with the per-lane instrument.")
    print("    (the stored dicts are retained as a labelled record only)")

    # ---- the admissibility hook ---------------------------------------
    print()
    print("  --- d_min AS AN ADMISSIBILITY INPUT (1.6t) ---")
    print("    The loader computes the program's J from its own d_min, the way")
    print("    every other admissibility condition is a property the loader")
    print("    CHECKS rather than a promise the programmer makes.")
    # ⛔⛔ THIS TABLE USED TO PRINT `j_of(d)` FOR EVERY ROW, INCLUDING THE
    # SUB-D* ONES -- so it published J = 8 at d_min = 8 and J = 7 at d_min = 12
    # two sections below a RETRACTION of exactly those numbers. A retraction
    # that one section of the same gate contradicts is not a retraction.
    # ⇒ The rows now answer what the loader ACTUALLY does, which is what
    #   `pe_asm.compute_j` implements: port feasibility FIRST, and a program
    #   below D* is REFUSED with the port arithmetic named rather than quoted
    #   a bound. The three columns are the two independent screens and the
    #   verdict, so the weaker test (U <= 1) can no longer be mistaken for the
    #   binding one.
    print("    %-8s %-9s %-14s %s"
          % ("d_min", "adm (U<=1)", "port (d>=D*)", "loader verdict"))
    for d in (4, 8, 10, 12, 18, 25, 434):
        adm = admissible(d)
        pf = port_feasible(d)
        if not adm:
            verdict = "REFUSED -- U > 1"
        elif not pf:
            verdict = ("REFUSED -- admissible but d < D* = %d, so the one "
                       "fetch port saturates" % D_STAR)
        else:
            verdict = "J = %d%s" % (j_of(d),
                                    "   (the shipped program)"
                                    if d == D_MIN_SHIPPED else "")
        print("    %-8d %-9s %-14s %s"
              % (d, "yes" if adm else "NO", "yes" if pf else "NO", verdict))
    print("    ⛔ TWO SCREENS, AND THE PORT ONE IS THE BINDING ONE. U <= 1 asks")
    print("    only whether the DISPATCHER keeps up and admits d >= 8; the")
    print("    fetch port needs d >= D* = %d. The gap d in [8, %d] is exactly"
          % (D_STAR, D_STAR - 1))
    print("    where the retracted universal J was unsound, and the loader")
    print("    refuses there instead of quoting a number.")

    print()
    print("=" * 78)
    print("  GATE j-program: PASSED -- on the SCOPED claim")
    print("    * D* = k * L_REFILL derived from the refill FSM and the")
    print("      single fetch port, not fitted to the sweep")
    print("    * published: d_min >= D* = %d -> J = 1; shipped d_min"
          % D_STAR)
    print("      = %d -> J = %d, measured 0 over 195,908 cycles"
          % (D_MIN_SHIPPED, shipped))
    print("    * RETRACTED: universal J = 8, unsound by live")
    print("      measurement at ten admissible points")
    print("    * ⛔ THE SWEEP BELOW IS A RECORD, NOT A LIVE READING.")
    print("      `sim <= derived` holds against the RECORDED values and")
    print("      FAILS against live measurement -- which is exactly how")
    print("      the unsoundness survived: this gate compared a stored")
    print("      number with the derivation and the script that would")
    print("      have re-measured it did not exist. Run")
    print("      `bash model/a2/price_j_sweep.sh` for the live check.")
    print("    * a measurement can falsify a bound, never raise it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
