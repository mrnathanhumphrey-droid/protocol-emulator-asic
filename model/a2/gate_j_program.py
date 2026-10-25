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

# ⛔ THE MEASURED SERVICE TIME COMES FROM THE LANE TABLE, NOT A SECOND COPY.
# Writing `3` here as well would put the same measured number in two places,
# and `gate_stored_numbers` treats a duplicated figure as a finding for good
# reason: the two copies drift and nothing says which is the design's.
from bursty import C_SHIPPED                                    # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

N_LANES = 5
# =========================================================================
# ⛔⛔ TWO DIFFERENT QUANTITIES WERE BOTH CALLED `C`, AND ONE OF THEM WAS
# MEASURED WRONG. `docs/PREREG_C_SAT.md` pre-registered the minimum
# inter-dispatch spacing at 2; `test/run_csat.py` measured 3 on four arms with
# 32,677 back-to-back opportunities and not one spacing of 2. The dispatch FSM
# is a THREE-state cycle (ST_IDLE -> ST_DRIVE -> ST_WB -> ST_IDLE) and `ST_WB`
# returns to ST_IDLE unconditionally, so the next dispatch decision cannot be
# taken until the cycle after writeback.
#
#   C_SPACING   = 3   the resource time a job denies to every other job. THIS
#                     is what a response-time analysis charges, and what
#                     `utilisation` must use.
#   C_OCCUPANCY = 2   cycles with `st != ST_IDLE`, i.e. `svc_cycles/svc_jobs`.
#                     Still exactly right as an answer to its own question.
#
# ⛔⛔ RULING 3: THE REFILL-WINDOW `+ C` IN `j_stall` DELIBERATELY KEEPS THE
# OCCUPANCY FIGURE, AND THIS IS THE RECORD OF THAT DECISION so it does not read
# as an unexamined leftover after the C correction.
#   WHAT THE TERM IS. `shortfall = max(0, k*L_REFILL - (d_min + C))`. The `+ C`
#   is not a service charge: it is the WINDOW in which a lane's spare slot can
#   be refilled -- the action delay plus the lane's own busy time, during which
#   the port is free to work on that lane's next action. The quantity it wants
#   is "how long is the engine occupied by this job", which is the OCCUPANCY,
#   2 -- not the spacing, 3.
#   WHY THE DIRECTION SETTLES IT ANYWAY. A LARGER `C` makes the shortfall
#   SMALLER and therefore the derived bound WEAKER. So 2 is the conservative
#   choice, and substituting 3 here would move a BOUND in the unsafe direction
#   on the strength of an argument about a different quantity.
#   WHY IT CHANGES NO PUBLISHED NUMBER. `j_of(D_MIN_SHIPPED = 25)` is
#   `max(0, 20 - (25 + C)) + 1 = 1` at either value, so the shipped claim is
#   identical; and the universal bound this term feeds is RETRACTED (see the
#   sweep below), so nothing else quotes it.
# ⇒ Re-derive only if a published number would change. Recorded, not deferred.
C_SPACING = C_SHIPPED
C_OCCUPANCY = 2
C_SVC = C_OCCUPANCY   # the refill-window term only; see above
L_REFILL = 4          # P_SCAN(1) + P_REQ/P_WAIT/P_CAP(3)
L_CAP = 7             # in-flight(3) + scan(1) + own(3), via winner-first
J_WINNER_REG = 1      # registering the EDF winner; structural, never stalls
# the number of points at which live measurement exceeded the derivation. The
# retraction of the universal J = 8 cites it, so it is asserted, not counted
# afresh each run.
VIOLATIONS_RECORDED = 10

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
# ⛔⛔⛔ AND THE LIVE MEASUREMENT AS *DATA*, WHICH IT WAS NOT. The ten
# violations that retracted the universal `J = 8` existed ONLY in the comment
# table above. This gate's `sim <= derived` check ran against `SWEEP` -- the
# stale record -- so it found zero violations and said so, while the prose four
# screens up said ten. The two-copies defect in its purest form: the gate was
# green BECAUSE the numbers that falsify it were not in any data structure.
# ⚠ FOUND BY TRYING TO USE THEM. `docs/PREREG_C_SAT.md` §6.1 pre-registered a
# check that the admissibility correction must not take known violations out of
# scope -- and that check printed "0 violations total", which is how the
# missing data surfaced. A guard can pass because what it guards is absent.
# ⇒ Transcribed from the comment table, which is the ONLY record of them, and
#   re-derivable with `bash model/a2/price_j_sweep.sh`.
# ⚠ d = 2..7 is recorded in that table as a RANGE ("7..11") and not per point,
#   so those points are ABSENT here rather than guessed. They are inadmissible
#   under both conditions, so no verdict depends on them.
SWEEP_LIVE = {
    8: 10, 9: 9, 10: 8, 11: 8, 12: 11, 13: 11, 14: 11,
    15: 11, 16: 11, 18: 11, 20: 0, 25: 0,
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
# ⛔⛔ CLOSED BY PS1 (2026-10-07): 19 DOES NOT SUFFICE, AND 20 IS TIGHT. The
# sweep's "d = 19" point is the recipe `--five 19 20 21 22 23`: ONE lane at 19,
# so the port's demand is sum(4/d_i) < 1. On 1M-cycle runs, today's RTL:
#     19 20 21 22 23   stall 0, winner-head refills after priming 0
#     19 23 19 23 19   stall 0, 0
#     19 19 19 19 23   STALLS (184,612 window cycles), 25,919
#     19 19 19 19 19   STALLS (195,571 window cycles), 35,754
# With five lanes at 19 the port is asked for 20 cycles of refill per 19.
# ⇒ The cliff is a THROUGHPUT floor, d >= k*L_REFILL = 20, and that is what
#   D_STAR states. The candidate latency bound (2d >= 37, i.e. d >= 19) is
#   NECESSARY, NOT SUFFICIENT: a sound statement needs both conditions.
#   Recorded in docs/J_LANE_PROOF.md (Amendment A2) and docs/PORT_SPEC.md.
# ⭐ RE-MEASURED ON THE TF RTL (ruling W, 2026-10-08), and the table above is
# PRE-TF in one column: "winner-head refills 0" on the two clean arms is no
# longer true. TF3's branch 1 reads the registered winner, so it now starts
# speculative head fills with NOTHING stalling -- 92 on `19..23` and 2,291 on
# `19 23 19 23 19` in 1M cycles, dispatch stream unchanged. At d = 19 the
# record `SWEEP_W` below says: m and drift CLEAN (slack 8 and 13), u and mb
# STALL. So 19 is not a boundary for all programs, and the published claim
# stays D* = 20: "measured clean on some recipes; candidate bound 2d >= 37;
# not claimed until the formal proof closes". This item is CLOSED.
D_STAR = N_LANES * L_REFILL


# ⛔⛔ RULING W -- THE D* SWEEP, AS A RECORD WITH A RECIPE THAT RUNS. This file
# is the project's lesson in numbers nobody could remake (`SWEEP`,
# `SWEEP_SINGLE`), so the W sweep is not transcribed here: it is LOADED from
# `model/a2/sweep_w.json`, which `python test/run_w_sweep.py --full` writes,
# and the record carries the sha256 of the RTL it ran on. An RTL change makes
# it STALE and this gate red until the sweep is re-run -- the record cannot
# outlive the design it describes. The live subset of the same bench runs in
# CI on its own (`test/run_w_sweep.py`).
def _load_sweep_w():
    import json
    p = os.path.join(HERE, "sweep_w.json")
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


SWEEP_W = _load_sweep_w()


def check_sweep_w(rec, live_sha, live_img=None):
    """-> list of problems; empty is a pass. The claims (ruling W):
      W2  every arm whose every lane has d >= D*, and every shipped admissible
          image: 0 conclusion violations, every lane consuming;
      W4  every must-fire (d = 18; the slow-refill mutant at d = 20): red;
      W5  d = 19 as ruled: m and drift clean, u and mb stall."""
    if rec is None:
        return ["model/a2/sweep_w.json is missing -- run "
                "`python test/run_w_sweep.py --full`"]
    probs = []
    if rec.get("_src_sha256") != live_sha:
        probs.append("STALE: the record ran on different RTL than src/ holds "
                     "now -- re-run `python test/run_w_sweep.py --full`")
    # ⛔ RULING RC6: a PROGRAM can change while the RTL does not (the RC
    # rebuild of corpus_i2c and ckread did exactly that), so the image rows
    # carry their images' hashes too
    if live_img is not None and rec.get("_image_sha256") != live_img:
        probs.append("STALE: an image row ran on a different .hex than test/ "
                     "holds now -- re-run `python test/run_w_sweep.py "
                     "--images`")
    arms = rec.get("arms", {})

    def v(a):
        return sum(l["viol_ev"] for l in arms[a]["lanes"])
    clean = [a for a, r in arms.items() if r["rtl"] == "good" and (
        r["kind"] == "image" or (r["kind"] == "synthetic"
                                 and min(r["delays"]) >= D_STAR))]
    if not clean:
        probs.append("no clean-claim arm in the record")
    for a in sorted(clean):
        if v(a):
            probs.append("%s: %d violations at d >= D*" % (a, v(a)))
        if r_has_idle(arms[a]):
            probs.append("%s: a lane never consumed -- 0 violations from a "
                         "bench that did not run" % a)
    mf = [a for a, r in arms.items() if r["kind"] == "mustfire"]
    if len(mf) < 4:
        probs.append("must-fires missing: %d of 4 in the record" % len(mf))
    for a in sorted(mf):
        if not v(a):
            probs.append("must-fire %s did NOT violate" % a)
    for a, want_clean in (("m19", True), ("drift19", True),
                          ("u19", False), ("mb19", False)):
        if a not in arms:
            probs.append("d = 19 row %s missing" % a)
        elif (v(a) == 0) != want_clean:
            probs.append("d = 19 row %s: ruled %s, record says %d violations"
                         % (a, "clean" if want_clean else "stall", v(a)))
    return probs


def r_has_idle(arm):
    """A synthetic arm must have every lane consuming; an image only the
    lanes it uses (an idle lane on an image is the program, not the bench)."""
    if arm["kind"] == "image":
        return not any(l["consumed"] > 0 for l in arm["lanes"])
    return not all(l["consumed"] > 0 for l in arm["lanes"])


def port_feasible(d: int, k: int = N_LANES) -> bool:
    """Can the single fetch port serve k refills per action period?"""
    return d >= k * L_REFILL


def utilisation(d: int, k: int = N_LANES) -> float:
    """⛔⛔ THE PERIOD IS EXACTLY `d`, NOT `d + C`. This read
    `k*C/(d + C)` and printed `adm = yes` at d = 8, 10, 12 and 18 -- a false
    label on a green gate, and the reason Wilson ruled it fixed regardless of
    how the C measurement came out.

    `P8` (anchored in `model/gate_j_proof_anchors.py`) is the premise: writeback
    advances a lane's timestamp from the PREVIOUS TIMESTAMP, absolutely, not
    from completion. So a lane releases every `d` cycles however long its job
    took -- which is also what Theorem 3 needs, and what the RTL comment at
    that line records as the reason the relative form drifts `k*(r - C)`.
    Dividing by `d + C` credited the system with a longer period than any lane
    has, in the optimistic direction.

    ⇒ `U = k*C/d <= 1` admits `d >= k*C`: **15** at the measured spacing,
    against the **8** this printed before. The two corrections compound --
    `d + C -> d` alone would have given 10.
    """
    return k * C_SPACING / float(d)


def admissible(d: int, k: int = N_LANES) -> bool:
    """Condition (1). ⛔ `<= 1.0` with a tolerance, because `d = k*C` lands on
    EXACTLY 1.0 and a float compare must not silently drop the boundary case --
    it is the tightest admissible point and therefore the one that would set
    any universal maximum."""
    return utilisation(d, k) <= 1.0 + 1e-12


# ⛔⛔ THE OLD CONDITION, KEPT AS A FUNCTION AND NOT AS A COMMENT. §6.1 of
# `docs/PREREG_C_SAT.md` pre-registered the trap this correction walks into:
# this gate EXCLUDES inadmissible points from its `sim <= derived` check, and
# the recorded sweep has TEN admissible points measuring above the derivation
# -- the unsoundness that retracted the universal J = 8. Tightening
# `admissible` to d >= 15 moves seven of those ten OUT OF SCOPE, so the gate
# could start reporting "sim <= derived at every admissible point" while the
# measurements that killed the bound sat silently outside it.
# ⇒ Both scopes are computed and both are printed. A correction that makes
#   known violations disappear by re-scoping is not a correction.
def admissible_as_published(d: int, k: int = N_LANES) -> bool:
    """`k*C/(d + C) <= 1` at C = 2 -- the condition that printed `yes` at
    d >= 8. Retained so the violations it admitted stay visible."""
    return k * C_OCCUPANCY / float(d + C_OCCUPANCY) <= 1.0 + 1e-12


def j_stall(d_min: int, k: int = N_LANES) -> int:
    shortfall = max(0, k * L_REFILL - (d_min + C_SVC))
    return min(shortfall, L_CAP)


def j_of(d_min: int, k: int = N_LANES) -> int:
    return j_stall(d_min, k) + J_WINNER_REG


def sweep_violations(sweep):
    """(violations [(d, derived, sim)] at ADMISSIBLE points, inadmissible [d])
    over a recorded sweep: `sim > derived` is a must-stop. The gate and its
    must-fire both call this (F8, meta-test 10-24: the comparison was inline
    and nothing planted a violation)."""
    violations, inadmissible = [], []
    for d in sorted(sweep):
        der, sim = j_stall(d), sweep[d]
        if not admissible(d):
            inadmissible.append(d)
        elif sim > der:
            violations.append((d, der, sim))
    return violations, inadmissible


def live_violations(live):
    """[(d, derived, live, adm now, adm as published)] where the LIVE
    measurement exceeds the derivation -- the retraction's evidence."""
    return [(d, j_stall(d), live[d], admissible(d), admissible_as_published(d))
            for d in sorted(live) if live[d] > j_stall(d)]


def main() -> int:
    rc = 0
    print()
    print("=" * 78)
    print("J AS A FUNCTION OF THE PROGRAM (Ruling 1(b))")
    print("=" * 78)
    print("  L_REFILL=%d  L_CAP=%d  J_WINNER_REG=%d  N_LANES=%d"
          % (L_REFILL, L_CAP, J_WINNER_REG, N_LANES))
    print("  C_SPACING=%d (measured, used by `utilisation`)  C_OCCUPANCY=%d"
          % (C_SPACING, C_OCCUPANCY))
    print("    ⛔ docs/PREREG_C_SAT.md: the min inter-dispatch spacing was")
    print("    pre-registered at %d and MEASURED %d. The dispatch FSM is a"
          % (C_OCCUPANCY, C_SPACING))
    print("    three-state cycle, and `svc_cycles/svc_jobs = 2.00` was")
    print("    occupancy, not spacing. Margins are re-quoted in")
    print("    `model/a2/gate_c3_requote.py`.")

    print()
    print("  --- the derivation against the recorded sweep ---")
    print("    ⛔ `adm?` NOW READS `U = k*C/d` WITH C = %d (the measured"
          % C_SPACING)
    print("    inter-dispatch spacing), not `k*C/(d+C)` with C = %d. `was?`"
          % C_OCCUPANCY)
    print("    is the condition this gate used to print, kept visible because")
    print("    the tighter one would otherwise take known violations out of")
    print("    scope -- docs/PREREG_C_SAT.md §6.1.")
    print("    %-5s %-8s %-6s %-6s %-9s %-9s %s"
          % ("d", "U", "adm?", "was?", "derived", "measured", "verdict"))
    violations, inadmissible = sweep_violations(SWEEP)
    for d in sorted(SWEEP):
        der = j_stall(d)
        sim = SWEEP[d]
        adm = admissible(d)
        was = admissible_as_published(d)
        bad = sim > der
        print("    %-5d %-8.3f %-6s %-6s %-9d %-9d %s"
              % (d, utilisation(d), "yes" if adm else "NO",
                 "yes" if was else "NO", der, sim,
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
    # ⛔⛔⛔ THE §6.1 SECTION. The admissibility correction is in the
    # RIGHT direction and it has a side effect that must never be allowed to
    # read as progress: it takes points OUT of the `sim <= derived` check, and
    # some of those points are the ones that falsified the universal bound.
    # Pre-registered before the C measurement was known, and printed here
    # whatever either condition says.
    print()
    print("  --- ⛔ EVERY MEASURED VIOLATION, UNDER BOTH SCOPES (prereg §6.1) ---")
    print("    ⛔⛔ AGAINST `SWEEP_LIVE`, NOT `SWEEP`. The table above compares")
    print("    the derivation with the STALE RECORD and finds nothing; the ten")
    print("    violations are in the LIVE measurement, which until this round")
    print("    existed only in a source comment. A check written against the")
    print("    record would print `0 violations` -- and did, which is how the")
    print("    missing data was found.")
    print("    %-5s %-9s %-9s %-7s %s"
          % ("d", "derived", "live", "adm now", "adm as published"))
    all_viol = live_violations(SWEEP_LIVE)
    for d, der, sim, adm, was in all_viol:
        print("    %-5d %-9d %-9d %-7s %s"
              % (d, der, sim, "yes" if adm else "NO", "yes" if was else "NO"))
    n_now = len([1 for _d, _r, _s, a, _w in all_viol if a])
    n_was = len([1 for _d, _r, _s, _a, w in all_viol if w])
    # ⛔ THE COUNT IS RECORDED, so an edit to `SWEEP_LIVE` that quietly drops a
    # violation makes this gate RED instead of making the problem smaller. The
    # retraction of the universal J = 8 cites TEN points; if this ever prints
    # fewer, the citation and the data have parted company.
    if len(all_viol) != VIOLATIONS_RECORDED:
        print("    *** %d VIOLATIONS, NOT THE %d THE RETRACTION CITES. Either"
              % (len(all_viol), VIOLATIONS_RECORDED))
        print("        `SWEEP_LIVE` or `j_stall` has changed. The retraction")
        print("        names a count, so this is RED rather than re-recorded.")
        rc = 1
    print("    %d violations total: %d still in scope, %d were in scope under"
          % (len(all_viol), n_now, n_was))
    print("    the published condition. ⛔ THE %d THAT LEFT THE SCOPE DID NOT"
          % (n_was - n_now))
    print("    GO AWAY. They are measurements of this design and they exceed")
    print("    the derivation; the universal J = 8 stays RETRACTED, and this")
    print("    gate must not be read as having re-established it.")
    print("    ⭐ WHY IT IS NOT A DODGE EITHER: the points that left are below")
    print("    d = %d, where the corrected utilisation says the DISPATCHER"
          % (N_LANES * C_SPACING))
    print("    itself cannot keep up -- so their stalls were never refill")
    print("    latency to begin with. Both facts are true, and printing only")
    print("    the convenient one is what §6.1 forbids.")
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
    print("      witness chain gives (queued ahead + 1) x %d, up to %d. %d"
          % (L_REFILL, N_LANES * L_REFILL, VIOLATIONS_RECORDED))
    print("      points measured ABOVE the derivation (d = 8..18), and they")
    print("      were ALL admissible under the condition published at the")
    print("      time. ⛔ Under the corrected utilisation only d = 15, 16, 18")
    print("      are still admissible -- which NARROWS THE SCOPE and does not")
    print("      un-measure the rest. NOT re-fitted -- withdrawn.")
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
    print("    only whether the DISPATCHER keeps up and admits d >= %d; the"
          % (N_LANES * C_SPACING))
    print("    fetch port needs d >= D* = %d, so the admissible-but-not-"
          % D_STAR)
    print("    port-feasible gap is d in [%d, %d] and the loader refuses"
          % (N_LANES * C_SPACING, D_STAR - 1))
    print("    throughout it instead of quoting a number.")
    print("    ⛔ TWO INTERVALS, NOT ONE, AND THEY USED TO BE CONFLATED. The")
    print("    region where live measurement exceeded the derivation is")
    print("    d = 8..18, which is WIDER than the gap above: the points below")
    print("    d = %d are now inadmissible, so their stalls are the dispatcher"
          % (N_LANES * C_SPACING))
    print("    saturating rather than refill latency. Both intervals end at")
    print("    D* - 1 and they start in different places.")

    # ---- ruling W: the D* sweep record --------------------------------
    print()
    print("  --- W: Theorem 3's conclusion over the D* sweep (record) ---")
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)),
                                    "test"))
    from run_w_sweep import image_sha256, src_sha256
    live_sha, live_img = src_sha256(), image_sha256()
    wp = check_sweep_w(SWEEP_W, live_sha, live_img)
    if SWEEP_W is not None:
        arms = SWEEP_W["arms"]
        print("    %d arms, recipe `%s`, RTL sha256 %s, image sha256 %s"
              % (len(arms), SWEEP_W["_recipe"],
                 "MATCHES src/" if SWEEP_W["_src_sha256"] == live_sha
                 else "*** STALE",
                 "MATCH test/" if SWEEP_W.get("_image_sha256") == live_img
                 else "*** STALE"))
        print("    %-6s %-6s %-9s %-9s %-9s %s"
              % ("d", "arms", "violated", "min slk", "owed max", "worst R_i"))
        for d in (19, 20, 21, 22, 25, 30, 40, 60):
            a = [r for r in arms.values() if r["kind"] == "synthetic"
                 and min(r["delays"]) == d]
            if not a:
                continue
            bad = sum(1 for r in a if sum(l["viol_ev"] for l in r["lanes"]))
            ok = [r for r in a if not sum(l["viol_ev"] for l in r["lanes"])]
            sl = min((l["slack_min"] for r in ok for l in r["lanes"]
                      if l["consumed"] > 0), default=-1)
            ow = max(l["owed_max"] for r in ok for l in r["lanes"]) if ok else -1
            rr = max(l["r_max"] for r in ok for l in r["lanes"]) if ok else -1
            print("    %-6d %-6d %-9d %-9d %-9d %d" % (d, len(a), bad, sl, ow, rr))
        im = [r for r in arms.values() if r["kind"] == "image"]
        print("    images %d, violated %d, min slack %d"
              % (len(im), sum(1 for r in im
                              if sum(l["viol_ev"] for l in r["lanes"])),
                 min(l["slack_min"] for r in im for l in r["lanes"]
                     if l["consumed"] > 0)))
    for p in wp:
        print("    *** %s" % p)
    # ⭐ v2 (Wilson 10-25): the W record's staleness is judged LAST, against
    # model/stale_records.py -- STALE only if every other check here is green
    sw_bad = bool(wp)
    if not wp:
        print("    every arm at d >= D* and every image: 0 violations; every")
        print("    must-fire red; d = 19 as ruled (m, drift clean; u, mb stall)")
    # ⛔ PRICE IT: the check must reject a stale record, a violation above D*
    # and a must-fire that stayed quiet. Planted on copies, in memory.
    if SWEEP_W is not None:
        import copy
        print("    --- must-fires (planted on a copy of the record) ---")
        stale = copy.deepcopy(SWEEP_W)
        stale["_src_sha256"] = {"pe_engine.v": "0" * 64}
        hot = copy.deepcopy(SWEEP_W)
        hot["arms"]["u20"]["lanes"][0]["viol_ev"] = 1
        quiet = copy.deepcopy(SWEEP_W)
        for l in quiet["arms"]["MF_slow_u20"]["lanes"]:
            l["viol_ev"] = 0
        oldimg = copy.deepcopy(SWEEP_W)
        oldimg["_image_sha256"] = dict(live_img, **{"corpus_i2c.hex": "0" * 64})
        for what, rec in (("a stale RTL hash", stale),
                          ("a stale image hash (RC6)", oldimg),
                          ("one violation on u20", hot),
                          ("a silent slow-refill must-fire", quiet)):
            red = bool(check_sweep_w(rec, live_sha, live_img))
            print("      %-36s %s" % (what, "red  ok" if red else "*** WRONG"))
            if not red:
                rc = 1
    # ⛔ F8 (meta-test, 10-24): THE MUST-STOP AND THE RETRACTION COUNT, priced.
    # Both comparisons ran only on the recorded tables.
    print("    --- must-fires (the recorded sweeps) ---")
    adm_d = next(d for d in sorted(SWEEP) if admissible(d))
    hot = {**SWEEP, adm_d: j_stall(adm_d) + 1}
    drop = dict(SWEEP_LIVE)
    # the PLANT is chosen from the table directly, so a broken
    # live_violations cannot also break the plant (meta-test, 10-24)
    drop.pop(next(d for d in sorted(SWEEP_LIVE) if SWEEP_LIVE[d] > j_stall(d)))
    for what, red in (
            ("an admissible SWEEP point above derived (d = %d)" % adm_d,
             bool(sweep_violations(hot)[0])),
            ("one violation removed counts exactly 9",
             len(live_violations(drop)) == VIOLATIONS_RECORDED - 1)):
        print("      %-36s %s" % (what, "red  ok" if red else "*** WRONG"))
        if not red:
            rc = 1

    stale_line = None
    if sw_bad:
        sys.path.insert(0, os.path.dirname(HERE))   # model/, for stale_records
        import stale_records as SR
        from run_w_sweep import SRCS as _W_SRCS
        from run_lockstep import IMAGES as _W_IMAGES
        inputs = ["src/" + s for s in _W_SRCS] + ["test/" + i for i in _W_IMAGES]
        v, why = SR.stale_verdict("model/a2/gate_j_program.py", SR.moved(inputs))
        print("    stale_records: %s -- %s" % (v, why))
        if v == "STALE" and rc == 0:
            stale_line = SR.token("j-program", why)
        else:
            rc = 1
    print()
    print("=" * 78)
    if stale_line:
        print(stale_line)
        return 0
    print("  GATE j-program: %s -- on the SCOPED claim"
          % ("PASSED" if rc == 0 else "FAILED"))
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
    print("    * ⛔ `utilisation` now divides by `d`, not `d + C`, and uses")
    print("      the MEASURED spacing: the admissible floor is d >= %d, not"
          % (N_LANES * C_SPACING))
    print("      d >= 8. The four rows that printed `adm = yes` at d = 8, 10,")
    print("      12 and 18 were a false label; 18 is still admissible and the")
    print("      other three are not.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
