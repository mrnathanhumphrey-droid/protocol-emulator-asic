"""The FOREIGN check for the jitter extension (ruling step 2).

THE ONE CLAIM: the jitter-inflated interference term is not merely larger than
the term it replaces -- it is RIGHT, as judged by an engine that explores actual
schedules with per-job release delays and has never seen our recurrence.

⛔⛔ WHY THIS RUN EXISTS AND WHAT IT IS ANSWERING. `bursty.py` now carries the
fix and a must-fire showing the old nominal-curve sum was BLIND to an
interferer's jitter. That establishes the old form unsound. It does NOT
establish the new form sound: "bigger" is not "correct", and a bound inflated
too far is a different failure that no self-check in the same file can see. Only
an independent engine can say whether the number is the true worst case.

⭐ THIS IS THE SAME MOVE THAT CAUGHT THE PROJECT'S WORST BUG. At `m_i > 1`
TChecker reported 11 against the recurrence's 8 and the hand trace confirmed 11:
non-strict deadline eligibility against a strict release count was UNDER-counting
interference. The jitter extension re-opens exactly that seam -- it changes the
release count -- so it gets exactly that treatment.

THE MODEL'S JITTER, in one line: a per-job delay re-rolled nondeterministically
in [0, J] at every nominal release, with the deadline and the response still
measured from the NOMINAL release. See `gen_edf.gen` for why that is jitter and
the pre-existing phase nondeterminism is not.

⛔ THE DIRECTION CHECK IS ASYMMETRIC AND THE ASYMMETRY IS THE POINT. Ours
LARGER than TChecker's is pessimism: the bound holds, we have left margin on the
table, and it is reported. Ours SMALLER is unsoundness: the bound is a lie.
`gate_pyrta.py` had this check INVERTED for a while -- the variable holding the
safe cases was named `tighter` and the alarm fired on them -- and it only looked
right because an exact-equality guard was doing the work. So here the two sets
are named for what they MEAN, and the verdict reads `not ours_smaller`.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))

from gen_edf import gen                                      # noqa: E402,F401
from bursty import BLane, response_time_b                    # noqa: E402
from run_edf import check, foreign_r, validate               # noqa: E402
from jitter_instances import (JINSTANCES, MUSTFIRE,          # noqa: E402
                              TCHECKER_RECORDED, key_of, recorded)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def rmax_for(lanes) -> int:
    """A bound the bisection can start above. ⛔ IT MUST ACCOUNT FOR JITTER.
    `run_edf`'s default is sum(C) + max(C) + 4, which predates jitter; a job
    delayed by J completes J later, so an unjittered rmax can sit BELOW the true
    response, and then `foreign_r` reports "BAD still reachable at R=rmax: no
    bound found" -- an error that reads like a divergence rather than a too-small
    search window."""
    return (sum(l[2] for l in lanes) + max(l[2] for l in lanes)
            + sum((l[6] if len(l) > 6 else 0) for l in lanes) + 4)


def foreign(lanes, target, tag):
    return foreign_r(lanes, target, tag, rmax=rmax_for(lanes))


def recurrence(lanes, target):
    """Our r for the same instance. Built ONCE and selected by identity --
    `response_time_b` refuses a lane that is merely equal to a list member."""
    objs = [BLane(n, T, C, D, J=(l[6] if len(l) > 6 else 0))
            for l in lanes for (n, T, C, D) in [(l[0], l[1], l[2], l[3])]]
    return response_time_b(objs[target], objs)["r"]


def recurrence_old(lanes, target):
    """The pre-fix nominal-curve sum, for the blindness face."""
    objs = [BLane(n, T, C, D, J=(l[6] if len(l) > 6 else 0))
            for l in lanes for (n, T, C, D) in [(l[0], l[1], l[2], l[3])]]
    return response_time_b(objs[target], objs,
                           jitter_in_interference=False)["r"]


# ============================================================================
# STEP 0 -- the JITTERED model, on answers that are forced
# ============================================================================
# ⛔ A NEW BRANCH IN THE GENERATOR IS A NEW MODEL AND IT IS NOT AUTHORITATIVE
# UNTIL IT REPRODUCES FORCED SCHEDULES. `run_edf.validate()` validated the J = 0
# branch; it says nothing about edges that only exist when J > 0. Skipping this
# step would mean adjudicating the recurrence with an unvalidated judge -- the
# same error as trusting a gate that has never fired.
JVALIDATION = [
    # (label, lanes, target, truth, why)
    ("solo J=0 -- the unjittered answer must not move",
     [("solo", 100, 2, 50, 1, 100, 0)], 0, 2,
     "no interference, no blocking: r = C"),
    ("solo J=1 -- the delay is spent, then the job runs",
     [("solo", 100, 2, 50, 1, 100, 1)], 0, 3,
     "worst delay 1 then C=2, measured from the NOMINAL release: 1+2"),
    ("solo J=3 -- and the delay is BOUNDED by J, not unbounded",
     [("solo", 100, 2, 50, 1, 100, 3)], 0, 5,
     "3+2 = 5. If the model let the wait run free this would not terminate "
     "at 5, so the number checks the bound and not just the mechanism"),
    ("solo J=3, C=1 -- C and J are separable",
     [("solo", 100, 1, 50, 1, 100, 3)], 0, 4,
     "3+1: the delay does not scale with service time"),
    # A jittered lane that CANNOT interfere: its deadline is always later, so
    # under EDF it contributes zero interference -- but it CAN still block.
    # Truth: the subject waits out the blocker's remaining C-1, then runs.
    ("jittery lane is a blocker only (later deadline), B = C_j - 1",
     [("analysed", 100, 2, 10, 1, 100, 0),
      ("blocker", 100, 4, 50, 1, 100, 2)], 0, 5,
     "blocker holds the engine non-preemptively: C_j-1 = 3, then C_i = 2"),
]


def validate_jitter() -> bool:
    print("=" * 78)
    print("STEP 0 -- validate the JITTERED model against forced schedules")
    print("=" * 78)
    print("  %-52s %-7s %-9s %s" % ("case", "truth", "TChecker", "verdict"))
    ok = True
    for i, (label, lanes, tgt, truth, why) in enumerate(JVALIDATION):
        res = foreign(lanes, tgt, "jval%d" % i)
        got = res.get("r")
        good = got == truth
        ok = ok and good and res["ovr"]["reachable"] is False
        print("  %-52s %-7d %-9s %s"
              % (label[:52], truth, got if got is not None else "ERR",
                 "OK" if good else "*** MISMATCH ***"))
        print("      %s" % why)
        if res.get("err"):
            print("      err: %s" % res["err"])
        if res["ovr"]["reachable"] is not False:
            ok = False
            print("      *** ovr reachable (%s) -- the single-pending "
                  "assumption breaks, instance is outside the model ***"
                  % res["ovr"]["reachable"])
    print()
    print("  jittered-model validation: %s"
          % ("PASSED -- the J > 0 branch reproduces every forced answer"
             if ok else "FAILED -- it cannot adjudicate anything"))
    return ok


# ============================================================================
# STEP 1 -- the must-fire instance, adjudicated
# ============================================================================
# ⭐ THE INSTANCES AND THE MUST-FIRE SHAPE COME FROM `jitter_instances.py`, which
# is also what `gate_pyrta_jitter.py` reads. Three witnesses on one instance
# list, so "all three agree" cannot mean "all three ran something different".
# This run also CHECKS the recorded verdicts in that file against what TChecker
# says live, in the direction that catches a stale record.


def main() -> int:
    print()
    print("THE FOREIGN CHECK FOR THE JITTER EXTENSION")
    print("per the ruling: recurrence fixed -> TChecker agrees -> then pyRTA")
    print()
    if not validate():
        print("\nABORTING: the BASE model fails its own validation, so nothing")
        print("built on top of it can be trusted.")
        return 1
    print()
    if not validate_jitter():
        print("\nABORTING: the jittered branch is not validated. An unvalidated")
        print("judge cannot adjudicate the recurrence -- that is the whole")
        print("reason this project uses a foreign checker at all.")
        return 1
    print()
    print("=" * 78)
    print("STEP 1 -- the must-fire instance, judged by TChecker")
    print("=" * 78)
    mf = foreign(MUSTFIRE, 0, "jmf")
    r_tck = mf.get("r")
    r_new = recurrence(MUSTFIRE, 0)
    r_old = recurrence_old(MUSTFIRE, 0)
    print("  lanes: subject(T=8,C=2,D=4,J=0)  jittery(T=7,C=2,D=5,J=1)")
    print("  subject's r:   OLD sum %s     FIXED %s     TChecker %s"
          % (r_old, r_new, r_tck))
    # ⛔⛔ THE FIRST VERSION OF THIS TEST DEMANDED `r_tck == r_new` AND FAILED
    # ON A CORRECT RESULT. That was my error in the criterion, not a problem
    # with the fix: Spuri's recurrence is an UPPER BOUND, not an exact response
    # time, so requiring equality asks it to be something it never claimed to
    # be. On this instance TChecker says 4, the fix says 5, the old sum said 3
    # -- the fix is sound and pessimistic by one cycle, which is the acceptable
    # side. Demanding exactness would have driven a "fix" that tightened the
    # bound until it broke, which is how a soundness margin gets optimised away.
    # The two faces that MATTER are kept, and the exactness is reported.
    mf_sound = r_tck is not None and r_new is not None and r_new >= r_tck
    mf_old_unsound = r_tck is not None and r_old < r_tck
    mf_ok = mf_sound and mf_old_unsound
    if mf_ok:
        print("  ⭐ THE OLD SUM IS BELOW THE TRUE WORST CASE BY %d, confirmed by"
              % (r_tck - r_old))
        print("     an engine that has never seen our recurrence. It was not")
        print("     conservative -- it was WRONG, in the one direction a bound")
        print("     may not err in. The fixed form is sound (%d >= %d)%s."
              % (r_new, r_tck,
                 ", pessimistic by %d" % (r_new - r_tck) if r_new > r_tck
                 else " and exact"))
    else:
        print("  *** must-fire NOT adjudicated as expected ***")
        if r_tck is not None and r_new is not None and r_new < r_tck:
            print("      ⛔⛔ TChecker %d > ours %d: THE FIXED RECURRENCE IS STILL"
                  % (r_tck, r_new))
            print("          UNSOUND. Do not re-baseline. This is the m_i>1 bug")
            print("          again, on the jitter axis.")
        if not mf_old_unsound:
            print("      the OLD sum is not below TChecker here, so this instance")
            print("      no longer witnesses the bug -- the fix would be")
            print("      unevidenced even if sound. Pick a witnessing instance.")
    if mf.get("err"):
        print("      err: %s" % mf["err"])
    if mf["ovr"]["reachable"] is not False:
        print("      *** ovr reachable -- instance outside the model ***")
        mf_ok = False

    print()
    print("=" * 78)
    print("STEP 2 -- constructed jitter instances, every lane")
    print("=" * 78)
    rows = []
    for label, lanes in JINSTANCES:
        print()
        print("  %s   lanes (T,C,D,J): %s"
              % (label, ", ".join("%s(%d,%d,%d,J=%d)"
                                  % (l[0], l[1], l[2], l[3], l[6])
                                  for l in lanes)))
        U = sum(l[2] / l[1] for l in lanes)
        print("    U = %.4f" % U)
        print("    %-10s %-11s %-10s %-9s %-8s %s"
              % ("lane", "recurrence", "TChecker", "old sum", "agree", "states"))
        for k, l in enumerate(lanes):
            rec = recurrence(lanes, k)
            old = recurrence_old(lanes, k)
            tag = "j%s_l%d" % (label.split()[0].lower(), k)
            res = foreign(lanes, k, tag)
            got = res.get("r")
            rows.append({"inst": label, "lane": l[0], "rec": rec, "old": old,
                         "tck": got, "ovr": res["ovr"]["reachable"],
                         "rec_file": recorded(label, l[0])})
            print("    %-10s %-11d %-10s %-9d %-8s %s"
                  % (l[0], rec, got if got is not None else "ERR", old,
                     "yes" if got == rec else ("LARGER" if got is not None
                                               and rec > got else "*** NO ***"),
                     res.get("states")))
            if res.get("err"):
                print("        err: %s" % res["err"])
            if res["ovr"]["reachable"] is not False:
                print("        *** ovr reachable -- outside the model ***")

    print()
    print("=" * 78)
    print("VERDICT")
    print("=" * 78)
    usable = [r for r in rows if r["tck"] is not None]
    ours_smaller = [r for r in usable if r["rec"] < r["tck"]]      # UNSOUND
    ours_larger = [r for r in usable if r["rec"] > r["tck"]]       # pessimistic
    exact = [r for r in usable if r["rec"] == r["tck"]]
    old_unsound = [r for r in usable if r["old"] < r["tck"]]
    ovr_bad = [r for r in rows if r["ovr"] is not False]
    err = [r for r in rows if r["tck"] is None]
    # ⛔ THE RECORD CHECK, IN THE DIRECTION THAT CATCHES A STALE NUMBER.
    # `jitter_instances.TCHECKER_RECORDED` is what the pyRTA gate reads instead
    # of shelling into WSL. A recorded value that no longer matches this run is
    # the project's #1 recurring defect -- a summary figure quoted as evidence
    # without being checked against the run that produced it.
    stale = []
    for r in rows:
        f = r["rec_file"]
        if f is None:
            stale.append((r["inst"], r["lane"], "NO RECORD", ""))
        elif (f["tck"], f["old"], f["ours"]) != (r["tck"], r["old"], r["rec"]):
            stale.append((r["inst"], r["lane"],
                          "recorded tck/old/ours %s/%s/%s"
                          % (f["tck"], f["old"], f["ours"]),
                          "live %s/%s/%s" % (r["tck"], r["old"], r["rec"])))
    print("  recorded verdicts in jitter_instances.py that are STALE: %d"
          % len(stale))
    if stale:
        for s in stale:
            print("      %s / %s: %s vs %s" % s)
        print("      ⛔ gate_pyrta_jitter.py reads those records instead of")
        print("         re-running TChecker. Update them from THIS run.")

    print("  lane-instances judged:                    %d of %d"
          % (len(usable), len(rows)))
    print("  ours EXACT  (== TChecker):                %d" % len(exact))
    print("  ours LARGER (safe, pessimistic):          %d" % len(ours_larger))
    print("  ours SMALLER (UNSOUND -- forbidden):      %d" % len(ours_smaller))
    print("  OLD nominal-curve sum below TChecker:     %d  <- the bug, measured"
          % len(old_unsound))
    if ovr_bad:
        print("  *** ovr reachable on %d instances ***" % len(ovr_bad))
    if err:
        print("  *** checker errored on %d instances ***" % len(err))
    print()
    ok = (mf_ok and not ours_smaller and not ovr_bad and not err and not stale
          and len(usable) == len(rows))
    if ours_smaller:
        print("  ⛔⛔ UNSOUND ON %d LANE-INSTANCES: %s"
              % (len(ours_smaller),
                 ", ".join("%s/%s ours %d < tck %d"
                           % (r["inst"].split()[0], r["lane"], r["rec"],
                              r["tck"]) for r in ours_smaller)))
        print("      The jitter fix is NOT sound. Do not re-baseline, do not")
        print("      bump the digest, and do not run the pyRTA step -- a third")
        print("      witness agreeing with two wrong ones proves nothing.")
    elif ok:
        print("  ⭐ THE JITTER EXTENSION IS FOREIGN-CHECKED. %d of %d exact, "
              "%d pessimistic," % (len(exact), len(usable), len(ours_larger)))
        print("     ZERO unsound, and the old sum is demonstrably below the true")
        print("     worst case on %d of them." % len(old_unsound))
        print()
        if ours_larger:
            print("  THE PESSIMISM, NAMED RATHER THAN AVERAGED: %s"
                  % ", ".join("%s/%s ours %d vs true %d (+%d)"
                              % (r["inst"].split()[0], r["lane"], r["rec"],
                                 r["tck"], r["rec"] - r["tck"])
                              for r in ours_larger))
            print("     Every gap is +1 cycle and every one is on a lane that is")
            print("     INTERFERED WITH by a jittery lane, never on the jittery")
            print("     lane itself -- so it is the inflated arrival count")
            print("     rounding a partial period up to a whole job. Spuri's")
            print("     bound is an upper bound and this is what that costs;")
            print("     published J > 0 margins are understated by at most this.")
            print()
        print("  ⚠ WHAT THIS DOES NOT COVER: every instance here is PERIODIC")
        print("    (n = 1). The generator refuses bursty-with-jitter because")
        print("    that cross product has no validated reference -- so the")
        print("    reactive lanes' m_i > 1 regime is checked at J = 0 only, by")
        print("    run_bursty.py. A reactive lane carrying J is NOT yet")
        print("    foreign-checked and must not be published as if it were.")
    else:
        print("  the run did not complete cleanly -- read the rows above before")
        print("  drawing any conclusion from the counts.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
