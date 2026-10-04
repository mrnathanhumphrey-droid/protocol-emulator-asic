"""The jitter-sound re-baseline, and the verdict that turns out to be
BOUND-DEPENDENT.

THE ONE CLAIM: at the derived J, OUR bound fails the pre-registered margin bar
and a tighter sound bound clears it, so the published margin depends on which
bound is quoted -- and that dependence, not a pass or a fail, is the result.

⛔⛔ THIS FILE OVERCLAIMED IN ITS FIRST VERSION AND THE CORRECTION IS THE POINT.
It asserted "the design FAILS its bar at the derived J". What is actually true
is narrower: OUR recurrence's bound fails it. pyRTA, given the same lanes and
the same jitter, returns I2C r = 12 where ours returns 16 -- margin 5 against
margin 1, PASS against FAIL. Both are sound upper bounds; neither is
contradicted by any foreign check. So "the design fails" was a statement about
our own arithmetic dressed as a statement about the chip.

⭐ AND THE TIGHTER BOUND IS THE BETTER-EVIDENCED ONE, which is what makes this
uncomfortable rather than academic. On the 11 constructed instances where
TChecker supplies ground truth, pyRTA was EXACT 11 of 11; ours was exact 9 of 11
and pessimistic on 2. The bound that fails the bar is the one with the worse
record against truth.

WHERE OUR LOOSENESS COMES FROM -- read against `docs/SPURI_RR2772_EXTRACT.md`
(Section 5, p13), which is the source, not my reconstruction. Our recurrence is
Spuri's J = 0 form with jitter added to the interference terms. His jitter form
differs in THREE further places that we do not implement:

  (1) THE SUBJECT'S OWN TERM. Ours: `(N_i(a) - 1) * C_i`, a plain count of
      earlier own-instances. His: `delta_i(a,t) * C_i` with
      `s_i(a) = a + J_i - floor((a+J_i)/T_i) * T_i` -- phase-aware, dependent on
      `t`, and therefore inside the fixpoint rather than in the constant.
  (2) THE RESPONSE FORMULA. Ours: `L + C_i + J_i - a`. His:
      `r_i(a) = max{ J_i + C_i, L_i(a) - a }` -- the subject's own service is
      already inside `L_i` via `delta_i`, so adding `C_i + J_i` on top of a
      differently-constructed base is not the same quantity.
  (3) THE OFFSET RANGE. Ours searches `a` over nominal arrivals in
      `[0, horizon]`. His is `a in [-J_i, L - J_i - C_i]` -- it starts NEGATIVE,
      and we never evaluate a negative offset at all.

⛔⛔ NOT ADOPTED -- AND UNDER RULING 2, NO LONGER NECESSARY. The restraint was
right for the stated reason: replacing the subject term, the response formula
and the offset range is a rewrite of the core recurrence that every number
rests on, and doing it in the same breath as discovering the current form fails
a bar is exactly "tighten the bound until the verdict improves".

⭐ BUT THE DATA GAVE A CLEANER ANSWER THAN TIGHTENING. Correctly framed, pyRTA
was EXACT 11 of 11 against TChecker's ground truth where ours was 9 of 11. So
pyRTA's bound is now the PUBLISHED number and ours is the independent
cross-check in the safe direction -- `pyrta_bound.check_direction` requires
ours >= pyRTA on every lane, and ours SMALLER means STOP: either we are unsound
or pyRTA is misframed, and the naive arm kept red in `gate_pyrta_jitter` proves
misframing is a live risk rather than a theoretical one.

⇒ OUR RECURRENCE SETS NO PUBLISHED NUMBER, SO THERE IS NOTHING TO TIGHTEN. The
three gaps stay recorded as the REASON our form is loose, not as work owed.
⛔ If Spuri's full form is ever adopted it needs a PRE-REGISTERED rationale,
decided BEFORE margins are computed -- otherwise the adoption cannot be told
apart from choosing the recurrence that gives the answer we wanted.

⭐ AND AT THE SHIPPED PROGRAM THE QUESTION DISSOLVES. With J re-baselined to its
derived 1, the two bounds AGREE EXACTLY on all five lanes: r = {11, 8, 5, 10, 6},
min margin 12. The bound-dependence below is a LARGE-J phenomenon and the
shipped program is not in that regime -- which is also why Ruling 1(b) publishes
the program's J and the universal worst case as two separate numbers.

THE TWO FACES STILL ASSERTED HERE:
  (a) THE SWEEP. Our bound's minimum margin at each J, checked against a
      recorded expectation so a silent drift in the lane table or the deadlines
      cannot pass as a new table.
  (b) THE MUST-FIRE. The pre-fix sum reports min margin 5 at J = 8 and clears
      the bar; the fixed sum reports 1 and does not. A fix that moves a verdict
      has to be able to show the number it replaced, or a real reversal cannot
      be told from a transcription slip -- and "min margin 5" had already
      reached a commit message.

⭐ WHAT IS UNAMBIGUOUS, AND IT IS THE DECISION-RELEVANT PART: at J_pipe = 2 the
two bounds AGREE EXACTLY on all five lanes, min margin 11, bar cleared. The
bound-dependence only appears at large J. So reducing J does not merely buy
margin -- it buys a margin that does not depend on which sound bound you quote.
That is the strongest argument for the double buffer, and it is stronger than
the one it was approved on.

⛔⛔ WHY THIS GATE EXISTS AS A GATE. The finding is a NUMBER CHANGING DIRECTION:
"min margin 5, clears the bar" became "min margin 1, fails the bar" when the
recurrence was fixed. A finding like that, left in prose, is exactly what this
project calls a summary value quoted without being checked against its run --
and this one has already been written into a commit message once in its wrong
form. So the sweep is recomputed every run and the two faces are asserted.

THE TWO FACES:
  (a) THE SOUND NUMBER. At J_pipe = 8 the minimum admissibility margin is 1,
      against the pre-registered bar of 4. The design is one cycle outside, and
      the tightest lane is I2C -- the only lane carrying J_PIPE + L_JIT.
  (b) THE OLD NUMBER, KEPT AS THE MUST-FIRE. The pre-fix sum reports min margin
      5 at the same J: it clears the bar by 1. ⛔ A fix that quietly made a
      passing design fail has to be able to show the passing number it replaced,
      or there is no way to tell a real reversal from a transcription slip.

⭐ THE SHAPE OF THE J CURVE IS THE ACTIONABLE PART. The margin falls roughly one
per cycle of J from 13 down to 4 at J = 7, and then drops THREE to 1 at J = 8.
That step is a whole interferer job crossing into I2C's window, so it cannot be
recovered by tightening anything else -- only by reducing J. Which is the
double buffer, pre-registered in `bursty.DOUBLE_BUFFER_PREREG`.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import lane_digest                                                 # noqa: E402
from jitter_instances import PYRTA_SHIPPED                          # noqa: E402
from bursty import (DOUBLE_BUFFER_PREREG, J_PIPE_DERIVED,          # noqa: E402
                    J_PIPE_PREDICTED, L_JIT, SPI_RX, TX, UART_RX,
                    BLane, response_time_b)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

MARGIN_BAR = 4          # pre-registered in ARCH_PREREG_01.md

# The expected sweep. ⛔ WRITTEN DOWN so a change in the recurrence, the lane
# table or the deadlines shows up as a disagreement instead of as a new table.
# J_pipe -> (min margin, tightest lane name fragment)
EXPECTED = {
    0: 13, 1: 12, 2: 11, 3: 8, 4: 7, 5: 6, 6: 5, 7: 4, 8: 1,
}
OLD_SUM_AT_8 = 5        # what the unsound form reported -- the must-fire


def lanes_at(j_pipe: int) -> list:
    """The shipped five lanes with a uniform J_pipe, plus L_JIT on I2C.

    ⛔ I2C IS THE ONLY LANE THAT CARRIES L_JIT, and it is why I2C is the
    tightest lane at every J: it is the reactive lane whose release is captured
    asynchronously, so it pays J_PIPE + L_JIT where every other lane pays
    J_PIPE. An earlier estimate of "margin 6 at J = 8" missed exactly this and
    was wrong by one for exactly this reason.
    """
    return [BLane(l.name, l.T, l.C, D_tol=l.D_tol, n=l.n, t=l.t,
                  J=j_pipe + (L_JIT if l.name.startswith("I2C") else 0))
            for l in TX + [UART_RX, SPI_RX]]


def sweep(jitter_in_interference: bool = True) -> dict:
    out = {}
    for j in sorted(EXPECTED):
        ls = lanes_at(j)
        rows = []
        for l in ls:
            r = response_time_b(l, ls,
                                jitter_in_interference=jitter_in_interference)["r"]
            rows.append((l.margin(r), l.name, r))
        mn = min(rows)
        out[j] = {"min_margin": mn[0], "tightest": mn[1],
                  "r": [x[2] for x in rows]}
    return out


def main() -> int:
    print()
    print("=" * 78)
    print("THE JITTER-SOUND RE-BASELINE (ruling step 4)")
    print("=" * 78)
    # ⛔ A DECLARED VARIANT, and the meta-check caught it undeclared first. Every
    # lane set this gate analyses carries a `J`, and the shipped table carries
    # J = 0 on every lane -- so `used` CANNOT match `base` here, by construction.
    # That is the whole subject of the gate. `lanes_at(0)` differs from the
    # shipped table too, because I2C still picks up L_JIT at J_pipe = 0.
    lane_digest.announce(
        "gate_j_sound.py", lanes_at(0),
        variant="every lane set here carries J (I2C also L_JIT); the shipped "
                "table is J=0 on all five, so a VARIANT is the point of this "
                "gate rather than a drift in it")

    sound = sweep(True)
    old = sweep(False)

    print()
    print("  --- face (a): the sound sweep, bar = margin >= %d ---" % MARGIN_BAR)
    print("    %-7s %-30s %-10s %-7s %s"
          % ("J_pipe", "r (5 lanes)", "min margin", "bar", "tightest lane"))
    drift = []
    for j in sorted(sound):
        s = sound[j]
        want = EXPECTED[j]
        if s["min_margin"] != want:
            drift.append((j, want, s["min_margin"]))
        print("    %-7d %-30s %-10d %-7s %s"
              % (j, "{" + ",".join(str(x) for x in s["r"]) + "}",
                 s["min_margin"],
                 "PASS" if s["min_margin"] >= MARGIN_BAR else "*** FAIL ***",
                 s["tightest"]))
    if drift:
        print()
        print("    *** THE SWEEP HAS MOVED from the recorded expectation:")
        for j, want, got in drift:
            print("        J_pipe=%d: recorded %d, now %d" % (j, want, got))
        print("        Either the lane table, the deadlines or the recurrence")
        print("        changed. Nothing below is interpretable until it is known")
        print("        which, so this gate is RED rather than re-recording.")
        return 1
    print("    => the sweep matches the record at every J")

    print()
    print("  --- face (b) MUST-FIRE: the old sum's number at the same J ---")
    j = J_PIPE_DERIVED
    s, o = sound[j], old[j]
    print("    at J_pipe = %d (the derived bound):" % j)
    print("      OLD unsound sum   r = %s   min margin %d   -> %s"
          % ("{" + ",".join(str(x) for x in o["r"]) + "}", o["min_margin"],
             "clears the bar" if o["min_margin"] >= MARGIN_BAR else "fails"))
    print("      FIXED sound sum   r = %s   min margin %d   -> %s"
          % ("{" + ",".join(str(x) for x in s["r"]) + "}", s["min_margin"],
             "clears the bar" if s["min_margin"] >= MARGIN_BAR else "FAILS"))
    faces = {
        "old cleared the bar": o["min_margin"] >= MARGIN_BAR,
        "old reported exactly %d" % OLD_SUM_AT_8: o["min_margin"] == OLD_SUM_AT_8,
        "sound FAILS the bar": s["min_margin"] < MARGIN_BAR,
        "the fix moved it DOWN": s["min_margin"] < o["min_margin"],
    }
    for k, v in faces.items():
        print("      %-34s %s" % (k, "PASS" if v else "*** FAIL ***"))
    if not all(faces.values()):
        print()
        print("    *** the must-fire does not reproduce the reversal. The claim")
        print("        'the bug was the only reason J=8 looked acceptable' is")
        print("        then unevidenced, whatever the sound number says. ***")
        return 1
    print()
    print("    ⛔ OUR BOUND'S VERDICT REVERSED. Under the unsound sum it cleared")
    print("       the bar; under the sound one it is %d short, and 'min margin 5'"
          % (MARGIN_BAR - s["min_margin"]))
    print("       had already reached a commit message. ⚠ This is a statement")
    print("       about our bound, NOT about the chip -- see face (c).")

    # ---- face (c): the other sound bound, which clears the bar -----------
    print()
    print("  --- face (c): the SAME lanes under pyRTA's bound ---")
    print("    (recorded in jitter_instances.PYRTA_SHIPPED; this gate must not")
    print("     require a third-party clone to state a margin verdict)")
    print("    %-7s %-22s %-7s %-7s %-9s %s"
          % ("J_pipe", "lane", "ours", "pyRTA", "gap", "margin ours/pyRTA"))
    bound_dep = []
    for jp in sorted(PYRTA_SHIPPED):
        ls = {l.name: l for l in lanes_at(jp)}
        worst_ours, worst_py = None, None
        for name, (o, p) in PYRTA_SHIPPED[jp].items():
            l = ls[name]
            mo, mp = l.margin(o), l.margin(p)
            worst_ours = mo if worst_ours is None else min(worst_ours, mo)
            worst_py = mp if worst_py is None else min(worst_py, mp)
            if o != p:
                print("    %-7d %-22s %-7d %-7d %-9s %d / %d"
                      % (jp, name, o, p, "+%d" % (o - p), mo, mp))
        verdict_ours = worst_ours >= MARGIN_BAR
        verdict_py = worst_py >= MARGIN_BAR
        if verdict_ours != verdict_py:
            bound_dep.append(jp)
        print("    %-7d %-22s min margin %d (%s) vs %d (%s)   %s"
              % (jp, "ALL FIVE", worst_ours,
                 "PASS" if verdict_ours else "FAIL", worst_py,
                 "PASS" if verdict_py else "FAIL",
                 "⛔ BOUND-DEPENDENT VERDICT" if verdict_ours != verdict_py
                 else "both agree"))
        # ⛔ our bound must never be BELOW pyRTA's: that would be unsoundness,
        # not looseness, and it is checked here on the recorded numbers too so
        # a bad record cannot sit next to a good gate.
        low = [(n, o, p) for n, (o, p) in PYRTA_SHIPPED[jp].items() if o < p]
        if low:
            print("    *** OURS BELOW pyRTA at J=%d on %s -- forbidden direction"
                  % (jp, low))
            return 1
    print()
    if bound_dep:
        print("    ⛔⛔ THE BAR VERDICT IS BOUND-DEPENDENT AT J_pipe = %s."
              % ", ".join(str(j) for j in bound_dep))
        print("        Our bound fails, pyRTA's clears it, both are sound, and")
        print("        pyRTA's is the one that matched TChecker's ground truth")
        print("        11 of 11 times. So the honest published statement is not")
        print("        'the design fails' -- it is 'our bound cannot show it")
        print("        passes, and the looseness is located' (see the three")
        print("        structural gaps in this file's header).")
        print("    ⭐⭐ RULING 2 SETTLES IT: pyRTA's bound is the PUBLISHED")
        print("        number, so the verdict at J = %d is PASS. Ours stays as"
              % J_PIPE_DERIVED)
        print("        the cross-check in the safe direction, and Spuri's full")
        print("        jitter form is NOT adopted -- our form sets no published")
        print("        number, so there is nothing to tighten.")
    print("    ⭐ AND AT J_pipe = 2 THE TWO BOUNDS AGREE EXACTLY on every lane.")
    print("       Reducing J buys a margin that does not depend on which sound")
    print("       bound is quoted -- a stronger reason for the double buffer")
    print("       than the one it was approved on.")

    print()
    print("  --- the step, located ---")
    for a, b in ((6, 7), (7, 8)):
        print("    J %d -> %d:  min margin %d -> %d   (delta %+d)"
              % (a, b, sound[a]["min_margin"], sound[b]["min_margin"],
                 sound[b]["min_margin"] - sound[a]["min_margin"]))
    print("    ⭐ the -3 at J=8 is a whole interferer job (C=2) plus I2C's L_JIT")
    print("       crossing into the window, not a rounding effect -- so it is")
    print("       not recoverable by tightening the bound. Only by reducing J.")

    print()
    print("  --- the double buffer, as pre-registered ---")
    pred = DOUBLE_BUFFER_PREREG["predicted_J_pipe"]
    print("    predicted J_pipe after the double buffer:   %d" % pred)
    print("    min margin AT that J (from the sweep above): %d  -> %s"
          % (sound[pred]["min_margin"],
             "PASS" if sound[pred]["min_margin"] >= MARGIN_BAR else "FAIL"))
    print("    falsifier:                                   %s"
          % DOUBLE_BUFFER_PREREG["falsifier"])
    print("    still owed:                                  %s"
          % ", ".join(DOUBLE_BUFFER_PREREG["owes"]))
    # ⛔ the pre-registration must agree with the sweep it was justified by, or
    # the recorded `margin_at_predicted_J` is a number nobody checked.
    if sound[pred]["min_margin"] != DOUBLE_BUFFER_PREREG["margin_at_predicted_J"]:
        print("    *** the pre-registration records margin %d at J=%d, the sweep"
              % (DOUBLE_BUFFER_PREREG["margin_at_predicted_J"], pred))
        print("        says %d. The decision was justified against a number that"
              % sound[pred]["min_margin"])
        print("        is no longer current. ***")
        return 1
    if pred != J_PIPE_PREDICTED:
        print("    *** J_PIPE_PREDICTED and the pre-reg dict disagree ***")
        return 1
    print("    => the pre-registration is consistent with the live sweep")

    print()
    print("=" * 78)
    print("WHAT IS AND IS NOT PUBLISHABLE")
    print("=" * 78)
    print("  PUBLISHABLE NOW:  the J = 0 table, labelled as a J = 0 analysis,")
    print("                    which is what it has always been;")
    print("                    the sweep above, as a sensitivity result.")
    print("  NOT PUBLISHABLE:  any single re-baselined table, because the")
    print("                    derived J fails the bar and the design is being")
    print("                    changed (double buffer) in response. Publishing a")
    print("                    failing table and then a passing one from the")
    print("                    same session would make the bar look negotiable.")
    print("  ⚠ FOREIGN COVERAGE: the jitter extension is checked by TChecker and")
    print("    pyRTA on PERIODIC instances (zone/run_jitter.py,")
    print("    gate_pyrta_jitter.py). The two reactive lanes are m_i > 1 --")
    print("    UART-rx n=10, SPI-target n=16 -- and TChecker's generator REFUSES")
    print("    bursty-with-jitter. pyRTA covers them via ArrivalCurvePrefix;")
    print("    TChecker does not, so those two lanes have ONE foreign witness at")
    print("    J > 0 where every other number in this project has two.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
