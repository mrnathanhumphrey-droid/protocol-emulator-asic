"""The pyRTA witness for the jitter extension (ruling step 3).

THE ONE CLAIM: a THIRD engine, independent of both our recurrence and TChecker,
reproduces the jitter-sound numbers -- and the naive way of asking it reproduces
our BUG instead, which is why the construction is spelled out rather than
assumed.

⛔⛔⛔ RETRACTION FIRST, BECAUSE A BLOCKER I RAISED WAS FALSE. `bursty.py` has
carried this since S3:

    "pyRTA's task model HAS NO JITTER PARAMETER. Its tasks are
     Periodic(t)/FullyNonPreemptive(C)/Deadline(D)/Priority -- nowhere to put J."

That is wrong. pyRTA ships `response_time_analysis.model.PeriodicWithJitter`,
a first-class arrival model whose upper arrival curve is literally

    max_arrivals(delta) = ceil((delta + jitter) / period)

i.e. exactly the inflated release count Spuri's interference term uses, exactly
the one `BLane.N_J` implements. There was nothing to work around.

⭐ HOW THE FALSE ABSENCE WAS REACHED, BECAUSE IT IS THE SAME MISTAKE TWICE. I
read the TASK constructor, saw four fields, and concluded jitter was absent from
the MODULE. But `Periodic` is itself an arrival model occupying the first field
-- the jitter lives in a SIBLING of the thing I was looking at, one import line
away. This is the same error as the two "primary full-tree reads" that were
truncation artefacts: an ABSENCE claimed from a partial read of the place it
would have been. The standing rule from those is "a zero-hit search proves the
string absent, not the thing", and the fix is the same -- grep the module for
the CONCEPT (`jitter`), not the API shape I expected it to have.

⛔⛔ AND NOW THE REAL OBSTACLE, WHICH IS SHARPER THAN THE ONE I RETRACTED.
pyRTA's `Deadline(D)` is relative to the job's ARRIVAL. Ours is relative to its
NOMINAL release. Without jitter those are the same instant and nothing turns on
it. With jitter they are not, and the difference is not a convention detail --
it CHANGES THE EDF PRIORITY ORDER:

  * ours:   absolute deadline = nominal + D. A job whose nominal release was
            early but whose actual release was delayed still carries that early
            deadline, so it can be MORE urgent than a job released after it.
  * pyRTA:  absolute deadline = arrival + D. The delay carries the deadline
            along with it, so a delayed job is never made more urgent by having
            been delayed.

So a jittery interferer that CAN preempt-by-urgency in our semantics simply
cannot in pyRTA's, its interference is not counted, and the bound comes out
OPTIMISTIC.

⭐⭐ THE MEASUREMENT THAT MAKES THIS WORTH WRITING DOWN. On the must-fire
instance the naive arm returns 3. The true worst case, from TChecker, is 4. And
3 is EXACTLY WHAT OUR OLD, UNSOUND SUM RETURNED. Same on J3/B: naive pyRTA 4,
truth 5, old sum 4. ⛔ A naive `PeriodicWithJitter` arm would therefore have
AGREED WITH THE BUG on both lanes where the bug was visible, and been quoted as
a foreign confirmation of it. Two engines agreeing is not two witnesses when
they share an assumption.

THE SOUND CONSTRUCTION, per subject lane k:
    subject k    keeps D_k        -- the LEAST urgent its nominal-release
                                     deadline can appear from its own arrival
                                     (delay 0), so k is not handed priority it
                                     may not have
    every j != k gets D_j - J_j   -- the MOST urgent theirs can appear (delay
                                     J_j), so their interference is counted at
                                     its maximum
    and the reported response is pyRTA's + J_k, converting from the arrival back
    to the nominal release.

⛔ BOTH SHIFTS ARE CONSERVATIVE *FOR SUBJECT k ONLY*, AND THAT IS WHY THE TASK
SET IS REBUILT PER SUBJECT. One task set with every deadline shifted would make
each lane more urgent while analysing it, which reduces the interference it
suffers -- optimistic, in the forbidden direction. A single shared task set is
the obvious implementation and it is the wrong one.

⚠ THIS CONSTRUCTION IS MINE, NOT pyRTA'S DOCUMENTED USE, and that costs some of
the independence this arm exists to provide: I am choosing the question. What is
NOT mine is the answer -- pyRTA's solver, its busy-window search and its
interference algebra are untouched. The arm is reported as a third witness to
the NUMBERS, with the framing attributed, and it is checked against TChecker's
recorded verdicts rather than against our own recurrence alone.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import lane_digest                                                 # noqa: E402
import pyrta_bound                                                 # noqa: E402
from bursty import BLane, response_time_b                          # noqa: E402
from jitter_instances import (JINSTANCES, MUSTFIRE, key_of,        # noqa: E402
                              recorded)
from pyrta_src import require_pyrta                                # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def ours(lanes, k, jitter_in_interference=True):
    """Our bound. Built ONCE and selected by identity -- `response_time_b`
    rejects a lane that is merely EQUAL to a list member, because filtering
    interference with `is not` would then exclude nothing."""
    objs = [BLane(l[0], l[1], l[2], l[3], J=l[6]) for l in lanes]
    return response_time_b(objs[k], objs,
                           jitter_in_interference=jitter_in_interference)["r"]


def as_lanes(tup):
    """The 7-tuples (name,T,C,D,n,t,J) as BLane objects.

    ⭐ Built ONCE per instance and selected by index, never rebuilt per subject:
    `response_time_b` filters interference BY IDENTITY, so an equal-but-distinct
    copy is not excluded and the subject interferes with itself.
    """
    return [BLane(l[0], l[1], l[2], l[3], n=l[4], t=l[5], J=l[6]) for l in tup]


# ⛔⛔ THE FRAMING LIVES IN `pyrta_bound`, NOT HERE, AND THAT IS THE POINT OF
# RULING 2. This gate used to carry its own copy of the correct construction
# while three OTHER gates carried the naive one -- and the J = 1 re-baseline
# made all three fail at once. A bound that is quoted as the published number
# cannot have four private implementations. So `bound` and `bound_naive` are
# imported, and what remains here is the EVIDENCE: that the naive framing is
# optimistic, and that the correct one matches TChecker.
def pyrta_r(src, lanes, k, shift: bool):
    if shift:
        return pyrta_bound.bound(src, lanes, k)
    return pyrta_bound.bound_naive(src, lanes, k)


def main() -> int:
    print()
    print("=" * 78)
    print("pyRTA WITNESS FOR THE JITTER EXTENSION (ruling step 3)")
    print("=" * 78)
    print()
    # ⛔ THE META-CHECK CAUGHT THIS GATE OPTING OUT. Arm 3 analyses the shipped
    # five lanes, so this gate DOES consume the table and must report a digest.
    # Not printing one leaves the cross-check silently, and the suite then goes
    # green with fewer participants than it declared -- which is exactly the
    # failure the explicit gate list exists to make impossible.
    import gate_pyrta_jitter as _self                                     # noqa
    from bursty import TX as _TX, UART_RX as _RX, SPI_RX as _SRX, L_JIT as _LJ
    lane_digest.announce(
        "gate_pyrta_jitter.py",
        [BLane(l.name, l.T, l.C, D_tol=l.D_tol, n=l.n, t=l.t,
                 J=l.J)
           for l in _TX + [_RX, _SRX]],
          variant="arm 3 analyses the SHIPPED lanes at their own derived J. "
                  "⛔ IT USED TO ANALYSE A UNIVERSAL WORST-CASE J_pipe=8 "
                  "SET, AND THAT SUBJECT NO LONGER EXISTS: the universal J was "
                  "found UNSOUND by live measurement at ten admissible points, "
                  "because `j_of` capped the stall at L_CAP=7 while the witness "
                  "chain gives (queued ahead + 1) x L_REFILL, up to 20. It is "
                  "RETRACTED, and the published claim is SCOPED: d_min >= D* = "
                  "k*L_REFILL = 20 -> J = 1. No replacement universal number is "
                  "analysed here: k*L_REFILL+1 = 21 still rests on an underived "
                  "premise about the scan's arbitration order.")
    print()
    print("  ⛔ RETRACTED: 'pyRTA's task model has no jitter parameter'.")
    print("     It ships PeriodicWithJitter(period, jitter) with")
    print("     max_arrivals(d) = ceil((d + jitter)/period) -- Spuri's inflated")
    print("     release count exactly. I read the Task constructor and claimed")
    print("     an absence about the module; the jitter is in a SIBLING arrival")
    print("     model, one import away. Option (a) of the ruling, not (b).")

    src = require_pyrta("gate_pyrta_jitter.py")
    if not src:
        return 1
    sys.path.insert(0, src)
    from response_time_analysis import edf                                # noqa
    from response_time_analysis.model import (WCET, Deadline,             # noqa
                                              FullyNonPreemptive,
                                              IdealProcessor, Periodic,
                                              PeriodicWithJitter, Priority,
                                              Task, taskset)
    mod = (WCET, Deadline, FullyNonPreemptive, Periodic, PeriodicWithJitter,
           Priority, Task, taskset)

    # ---- arm 0: the arrival curve IS our inflated count ------------------
    # ⛔ CHECK THE CURVE BEFORE THE SOLVER. If pyRTA's notion of "jitter" were
    # not ours, every number below would be a comparison of two different
    # questions -- and that is precisely the failure this gate goes on to
    # document for the DEADLINE convention. So the one place the two models are
    # supposed to coincide is verified point by point first.
    print()
    print("  --- arm 0: pyRTA's jittered arrival curve vs ours, pointwise ---")
    mism = 0
    n_pts = 0
    for T in (3, 5, 7, 8, 25, 62):
        for J in (0, 1, 2, 3, 7):
            bl = BLane("x", T, 1, max(1, T // 2), J=J)
            pw = PeriodicWithJitter(period=T, jitter=J) if J else Periodic(period=T)
            for d in range(1, 3 * T + 4):
                n_pts += 1
                if bl.N_J(d - 1) != pw.max_arrivals(d):
                    mism += 1
                    if mism == 1:
                        print("      FIRST MISMATCH T=%d J=%d delta=%d: "
                              "ours %d, pyRTA %d"
                              % (T, J, d, bl.N_J(d - 1), pw.max_arrivals(d)))
    print("      %d points compared, %d mismatches" % (n_pts, mism))
    if mism:
        print("      *** ABORT: the two arrival models are not the same model.")
        print("          ⚠ offsets: ours counts the CLOSED interval [0,delta]")
        print("          and pyRTA the half-open window of length delta, so the")
        print("          comparison is N_J(delta-1) vs max_arrivals(delta). A")
        print("          mismatch here is a real disagreement, not that shift.")
        return 1
    print("      => ceil((delta+J)/T) on both sides. ⭐ Our inflated count is")
    print("         pyRTA's PeriodicWithJitter curve, point for point.")

    # ---- arm 1: the naive arm, shown AGREEING WITH THE BUG --------------
    print()
    print("  --- arm 1: the NAIVE arm (Deadline(D) unshifted) -- the trap ---")
    print("    %-6s %-10s %-8s %-8s %-8s %s"
          % ("inst", "lane", "naive", "TCK", "old sum", "what the naive arm did"))
    trap = []
    for label, lanes in JINSTANCES:
        for k, l in enumerate(lanes):
            R, err = pyrta_r(src, as_lanes(lanes), k, shift=False)
            rec = recorded(label, l[0])
            if R is None or rec is None:
                print("    %-6s %-10s %s" % (key_of(label), l[0], err or "no record"))
                continue
            if R < rec["tck"]:
                verdict = ("BELOW the truth" +
                           (" -- and EQUALS our old bug" if R == rec["old"]
                            else ""))
                trap.append((key_of(label), l[0], R, rec["tck"], rec["old"]))
            else:
                verdict = "sound here"
            print("    %-6s %-10s %-8d %-8d %-8d %s"
                  % (key_of(label), l[0], R, rec["tck"], rec["old"], verdict))
    print()
    if trap:
        print("    ⛔⛔ THE NAIVE ARM IS OPTIMISTIC ON %d LANE-INSTANCES, and on"
              % len(trap))
        print("        %d of them it returns EXACTLY our old unsound number:"
              % len([t for t in trap if t[2] == t[4]]))
        for inst, lane, R, tck, old in trap:
            print("          %s/%s: naive %d, truth %d, old sum %d%s"
                  % (inst, lane, R, tck, old,
                     "   <- SAME" if R == old else ""))
        print("        Asked the obvious way, pyRTA would have CONFIRMED the")
        print("        bug. Two engines sharing a deadline convention are one")
        print("        witness. This is the arm that must not be shipped.")
    else:
        print("    *** the naive arm is NOT optimistic on any instance.")
        print("        Then the deadline-convention argument in this file's")
        print("        header predicts an effect that does not occur, and the")
        print("        shifted construction below is unmotivated. Resolve that")
        print("        before reading arm 2 as evidence of anything. ***")
        return 1

    # ---- arm 2: the sound per-subject construction ----------------------
    print()
    print("  --- arm 2: per-subject deadline shift (the sound construction) ---")
    print("    %-6s %-10s %-9s %-8s %-8s %-9s %s"
          % ("inst", "lane", "pyRTA", "TCK", "ours", "agree", "direction"))
    rows = []
    for label, lanes in JINSTANCES:
        for k, l in enumerate(lanes):
            R, err = pyrta_r(src, as_lanes(lanes), k, shift=True)
            rec = recorded(label, l[0])
            o = ours(lanes, k)
            if R is None or rec is None:
                print("    %-6s %-10s %s" % (key_of(label), l[0], err or "no record"))
                return 1
            rows.append({"inst": key_of(label), "lane": l[0], "pyrta": R,
                         "tck": rec["tck"], "ours": o})
            print("    %-6s %-10s %-9d %-8d %-8d %-9s %s"
                  % (key_of(label), l[0], R, rec["tck"], o,
                     "exact" if R == rec["tck"] else "+%d" % (R - rec["tck"]),
                     "ours >= pyRTA" if o >= R else "*** OURS SMALLER ***"))

    # ---- arm 3: the REAL lanes, including the two that are m_i > 1 ------
    # ⛔⛔ THE ARM THAT COVERS WHAT TCHECKER CANNOT. Arms 1 and 2 are periodic,
    # because `gen_edf.gen` REFUSES bursty-with-jitter -- that cross product has
    # no validated reference. But two shipped lanes ARE bursty (UART-rx n=10,
    # SPI-target n=16), and `m_i > 1` is the exact regime in which this
    # recurrence was once PROVED unsound. Re-baselining at J > 0 without a
    # witness for those two would put the whole re-baseline back on our own
    # algebra, in the one place it has already failed.
    #
    # ⭐ pyRTA CAN express them, exactly, via `ArrivalCurvePrefix`: our bursty
    # jittered curve is a step function, and a prefix up to a horizon longer
    # than the busy window IS that function. The steps are generated from
    # `BLane.N_J` and then CHECKED POINTWISE against it, so a transcription
    # error becomes a mismatch rather than a quietly different task set.
    print()
    print("  --- arm 3: the SHIPPED five lanes at J > 0, bursty lanes included ---")
    from bursty import TX, UART_RX, SPI_RX, L_JIT                        # noqa
    from response_time_analysis.model import ArrivalCurvePrefix          # noqa

    def shipped_at(j_pipe):
        return [BLane(l.name, l.T, l.C, D_tol=l.D_tol, n=l.n, t=l.t,
                      J=j_pipe + (L_JIT if l.name.startswith("I2C") else 0))
                for l in TX + [UART_RX, SPI_RX]]

    def acp_for(bl, H):
        """Our jittered curve as a pyRTA arrival-curve prefix, then verified
        against the curve it came from."""
        steps, prev = [], 0
        for d in range(1, H):
            v = bl.N_J(d - 1)          # closed-interval ours -> half-open pyRTA
            if v != prev:
                steps.append((d, v))
                prev = v
        acp = ArrivalCurvePrefix(horizon=H, ac_steps=steps)
        bad = [d for d in range(1, H) if acp.max_arrivals(d) != bl.N_J(d - 1)]
        if bad:
            raise AssertionError(
                "%s: the prefix disagrees with N_J at %d points (first delta=%d)"
                % (bl.name, len(bad), bad[0]))
        return acp

    arm3_bad = []
    for j_pipe in (2, 7, 8):
        ls = shipped_at(j_pipe)
        H = 2 * max(l.T for l in ls)
        print("    J_pipe = %d   (horizon %d)" % (j_pipe, H))
        print("      %-22s %-4s %-5s %-8s %-8s %-8s %s"
              % ("lane", "n", "J", "ours", "pyRTA", "margin", "direction"))
        for k, l in enumerate(ls):
            # ⭐ the bursty lanes go through the SAME `pyrta_bound.bound`: it
            # builds an ArrivalCurvePrefix from `N_J` and VERIFIES it pointwise
            # against that curve, so pyRTA cannot be handed a different task
            # set from the one we analysed.
            R, err3 = pyrta_bound.bound(src, ls, k, horizon=H)
            if R is None:
                print("      *** %s: %s ***" % (l.name, err3))
                return 1
            o = response_time_b(l, ls)["r"]
            good = R is not None and o >= R
            if not good:
                arm3_bad.append((j_pipe, l.name, o, R))
            print("      %-22s %-4d %-5d %-8d %-8s %-8d %s"
                  % (l.name, l.n, l.J, o, R, l.margin(o),
                     ("ours >= pyRTA" if o == R else "ours +%d" % (o - R))
                     if good else "*** OURS SMALLER ***"))
    print()
    if arm3_bad:
        print("    ⛔⛔ OUR BOUND IS BELOW pyRTA's ON THE SHIPPED LANES: %s"
              % ", ".join("J=%d %s (%d < %s)" % b for b in arm3_bad))
    else:
        print("    ⭐ the two m_i > 1 lanes ARE foreign-checked at J > 0, by")
        print("       pyRTA. ⚠ By pyRTA ALONE -- TChecker's generator refuses")
        print("       bursty-with-jitter, so these two lanes carry ONE foreign")
        print("       witness where every other number here carries two.")

    print()
    print("=" * 78)
    print("VERDICT")
    print("=" * 78)
    # ⛔⛔ THE DIRECTION CHECK, NAMED FOR WHAT IT MEANS. `gate_pyrta.py` had this
    # INVERTED -- the variable holding the SAFE cases was called `tighter` and
    # the unsoundness alarm fired on them -- and it looked correct only because
    # an exact-equality guard was failing either way. So: ours SMALLER than a
    # sufficient bound is the forbidden direction, and that is the name.
    ours_smaller = [r for r in rows if r["ours"] < r["pyrta"]]      # FORBIDDEN
    pyrta_below_tck = [r for r in rows if r["pyrta"] < r["tck"]]    # FORBIDDEN
    exact = [r for r in rows if r["pyrta"] == r["tck"]]
    print("  lane-instances:                            %d" % len(rows))
    print("  pyRTA EXACT against TChecker:              %d" % len(exact))
    print("  pyRTA BELOW TChecker (would be unsound):   %d" % len(pyrta_below_tck))
    print("  ours SMALLER than pyRTA (forbidden):       %d" % len(ours_smaller))
    ok = not ours_smaller and not pyrta_below_tck and not arm3_bad
    print()
    if ours_smaller:
        print("  ⛔⛔ OUR BOUND IS BELOW pyRTA's SUFFICIENT BOUND on %s."
              % ", ".join("%s/%s" % (r["inst"], r["lane"]) for r in ours_smaller))
        print("      Possible unsoundness, not tightness. Do not re-baseline.")
    if pyrta_below_tck:
        print("  ⛔⛔ pyRTA IS BELOW THE TRUE WORST CASE on %s -- the shifted"
              % ", ".join("%s/%s" % (r["inst"], r["lane"])
                          for r in pyrta_below_tck))
        print("      construction is NOT conservative after all, so it cannot")
        print("      serve as a witness and the derivation is wrong somewhere.")
    if ok:
        print("  ⭐ THIRD WITNESS OBTAINED. With the per-subject deadline shift,")
        print("     pyRTA matches TChecker exactly on %d of %d lane-instances and"
              % (len(exact), len(rows)))
        print("     is never below it, and our recurrence is never below pyRTA.")
        print("     Three engines, one instance list, no forbidden direction.")
        print()
        print("  ⚠ WHAT THIS IS NOT: pyRTA was asked a question I constructed")
        print("    (the per-subject shift). The SOLVER is independent; the")
        print("    FRAMING is not. The naive framing is in arm 1 above and it")
        print("    agrees with our old bug -- which is the honest measure of how")
        print("    much the framing is doing.")
        print("  ⚠ AND: every instance is PERIODIC. A reactive lane (m_i > 1)")
        print("    carrying J has no foreign witness at all yet.")

    # ---- arm 4: RULING Y-R2 -- the retracted "charge once" framing --------
    # ⛔⛔ Ruling Y ordered `bound` changed to give interferers Deadline(D)
    # (jitter "charged once") on the claim that D - J double-counts. The claim
    # was unwitnessed and is FALSE: at large J the D - J framing is EXACT and
    # the charge-once framing is BELOW the truth. Both halves are required.
    from jitter_instances import LJ_CHARGE_ONCE, LJ_INSTANCES, LJ_RECORDED
    print()
    print("  --- arm 4: Y-R2 -- D - J exact, 'charge once' below the truth ---")
    n_exact = n_below = n_lanes = 0
    drift = []
    for name, spec in LJ_INSTANCES:
        objs = [BLane(nm, T, C, D, J=J) for (nm, T, C, D, _n, _t, J) in spec]
        for k in range(len(spec)):
            if (name, k) not in LJ_RECORDED:
                continue
            tck = LJ_RECORDED[(name, k)]
            dj = pyrta_bound.bound(src, objs, k)[0]
            once = pyrta_bound.bound_charge_once(src, objs, k)
            n_lanes += 1
            n_exact += dj == tck
            n_below += once < tck
            if once != LJ_CHARGE_ONCE[(name, k)]:
                drift.append((name, k, once, LJ_CHARGE_ONCE[(name, k)]))
            print("    %s/%d  tck %2d   D-J %2s   charge-once %2s%s"
                  % (name, k, tck, dj, once,
                     "   <-- BELOW truth" if once < tck else ""))
    for d in drift:
        print("    *** %s/%d: charge-once gives %s, recorded %s" % d)
    ok4 = n_exact == n_lanes and n_below == 5 and not drift
    print("    D - J exact on %d of %d; charge-once below on %d (recorded 5)"
          "   %s" % (n_exact, n_lanes, n_below, "ok" if ok4 else "*** WRONG"))
    return 0 if (ok and ok4) else 1


if __name__ == "__main__":
    raise SystemExit(main())
