"""RULING R -- PORT DEMAND PER RETIRED CLOCKED ACTION, adjudicated.

⛔⛔ WHY THIS GATE EXISTS, AND IT IS THE WORST SHAPE A GREEN SUITE CAN HAVE.
`M_CK_HOLD_INVAL` -- one line, invalidating a clocked lane's head slot on every
HELD dispatch -- SURVIVED EVERY GATE IN THIS REPO for an entire arc:

  * Layer A1 cannot see it. The PC does NOT advance during a hold, so the
    prefetch re-reads the SAME address and restores an IDENTICAL word. Every
    delay the zero-flop rebase reads out of the head slot is still correct.
  * Layer B cannot see it. A refill changes no dispatch count.
  * The coverage sweep cannot see it. The lines it touches are covered either
    way.

What it breaks is **Amendment A1's PORT PREMISE**: a refill per DISPATCH
instead of per ACTION. `D* = N_LANES * L_REFILL` and every port-feasible cell
in Theorem 3 are computed from the premise that a held clocked dispatch owes no
refill -- so under the mutant the schedule the entire A2 argument quotes is for
a different machine. Re-dispatch counts moved 1229 -> 1061 on `corpus_i2c`.

⇒ THE TREE WAS GREEN ON A PREMISE NOTHING CHECKED. That is the finding, and
  this gate is the answer to it.

⭐ THE BOUND IS DERIVED, NOT FITTED: at most one fill per SLOT per action, i.e.
`SPL`. Inside one action's window a lane can take the head refill the PREVIOUS
action's retire triggered, plus one speculative spare fill -- and no more,
because the spare stays valid until the swap consumes it. `clocked_conform.vh`
reads `dut.u_eng.SPL` so the bound follows the design.

⚠ THE FIRST BOUND WAS 1 AND WAS WRONG, recorded rather than quietly bumped.
`ckod` and `corpus_i2c` each have ONE live clocked lane and both measure 1;
`corpus_all5` has FIVE and measures 2. A bound measured on the single-lane case
and applied to the stress image is the same category error as three others in
this session's ledger.

⛔ WHAT THIS GATE REFUSES TO DO: pass on a clean run alone. A clean arm is
evidence only if the mutant arm is RED, and RED **of layer R** rather than of
something else -- a kill for the wrong reason is not evidence about this
mutation.
"""

from __future__ import annotations

import io
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

#: the arms `test/refill_run.sh` produces, and what each one must show.
#: ⛔ DECLARED HERE so a missing arm is a FAILURE rather than an absence: a
#: gate that adjudicates whatever it happens to find cannot tell "the mutant
#: was not red" from "the mutant was never built".
CLEAN_ARMS = ("clean_ckod_image", "clean_corpus_i2c", "clean_corpus_all5")
MUTANT_ARMS = ("inval_ckod_image", "inval_corpus_i2c", "inval_corpus_all5")

#: the mutant must exceed the bound by more than rounding. It costs a refill
#: per DISPATCH, and a clocked byte is 16 dispatches, so anything below this is
#: a sign the mutant did not really take effect.
MUTANT_MIN_WORST = 8


def load():
    p = os.environ.get("PE_REFILL_JSON", "")
    if not p:
        for cand in ("probe_refill/refill.json",):
            if os.path.isfile(os.path.join(ROOT, cand)):
                p = os.path.join(ROOT, cand)
                break
    if not p or not os.path.isfile(p):
        return None, p
    with io.open(p, encoding="utf-8") as fh:
        return json.load(fh), p


def main() -> int:
    rc = 0
    print()
    print("=" * 78)
    print("  RULING R -- REFILLS PER RETIRED CLOCKED ACTION")
    print("=" * 78)
    blob, path = load()
    if blob is None:
        print("  *** FAIL no measurement at PE_REFILL_JSON='%s'" % path)
        print("      `bash test/refill_run.sh <outdir>` produces it. This gate")
        print("      is RED without it rather than skipping: a port-demand")
        print("      gate that passes when the measurement is missing is a")
        print("      guard that passes because of what it guards -- and the")
        print("      premise it protects (D*) is quoted in the write-up.")
        return 1

    print("  measurement : %s" % path)
    print()
    print("  --- 1. the clean design: every clocked action within the bound ---")
    print("    %-26s %-14s %-8s %-7s %s"
          % ("arm", "verdict", "actions", "worst", "bound"))
    total_actions = 0
    for arm in CLEAN_ARMS:
        r = blob.get(arm)
        if r is None:
            print("    *** %-26s MISSING -- the arm was not built or produced"
                  % arm)
            print("        no layer-R verdict, so nothing is known about it")
            rc = 1
            continue
        ok = r["verdict"] == "ok"
        # ⛔ NON-VACUITY IS PART OF THE PASS. `not_exercised` means the program
        # retired no clocked action at all, which on a clocked image means the
        # run did not do what the arm exists to do.
        if r["verdict"] == "not_exercised":
            print("    *** %-26s NOT EXERCISED -- a clocked image that retired"
                  % arm)
            print("        no clocked action measures nothing")
            rc = 1
            continue
        total_actions += r["actions"] or 0
        print("    %-26s %-14s %-8s %-7s %s"
              % (arm, r["verdict"], r["actions"], r["worst"], r["bound"]))
        if not ok:
            print("        *** FAIL %d action(s) over the bound" % r["over"])
            rc = 1
    if total_actions:
        print("    ⇒ %d retired clocked action(s) across the clean arms"
              % total_actions)

    print()
    print("  --- 2. must-fire: M_CK_HOLD_INVAL must be RED, and red OF R ---")
    print("    ⛔ THE MUTANT IS THE EVIDENCE. It survived A1, B and the")
    print("    coverage sweep for a whole arc; a clean arm above proves")
    print("    nothing unless this layer can actually see the defect.")
    print("    %-26s %-14s %-8s %-7s %s"
          % ("arm", "verdict", "actions", "worst", "bound"))
    killed = 0
    for arm in MUTANT_ARMS:
        r = blob.get(arm)
        if r is None:
            print("    *** %-26s MISSING -- the must-fire did not run" % arm)
            rc = 1
            continue
        print("    %-26s %-14s %-8s %-7s %s"
              % (arm, r["verdict"], r["actions"], r["worst"], r["bound"]))
        if r["verdict"] != "red":
            print("        *** DID NOT FIRE -- a refill per DISPATCH went")
            print("        unnoticed, which is the state ruling R exists to end")
            rc = 1
            continue
        # ⚠ AND IT MUST FIRE BY THE RIGHT MARGIN. The mutation costs one refill
        # per dispatch; a worst of 2 or 3 would mean it barely took effect, and
        # a must-fire that only just fires is not a priced one.
        if (r["worst"] or 0) < MUTANT_MIN_WORST:
            print("        *** fired, but worst is only %s -- the mutation"
                  % r["worst"])
            print("        costs a refill PER DISPATCH, so a clocked byte")
            print("        should show ~16. Check it really took effect.")
            rc = 1
            continue
        killed += 1
    if killed == len(MUTANT_ARMS):
        print("    ⇒ fires on all %d arms, at %s refills against a bound of %s"
              % (killed,
                 sorted({blob[a]["worst"] for a in MUTANT_ARMS}),
                 blob[MUTANT_ARMS[0]]["bound"]))

    print()
    print("  --- 3. what this gate does NOT check ---")
    print("    ⚠ IT BOUNDS REFILLS PER ACTION, NOT `D*` ITSELF. `D*` is a")
    print("      port-feasibility statement over a whole lane SET; this layer")
    print("      checks the per-action premise `D*` is computed FROM. A design")
    print("      that respected this bound and still oversubscribed the port")
    print("      would pass here and fail `gate_admissibility_1_6`.")
    print("    ⚠ THE SPARE FILL IS COUNTED AGAINST WHICHEVER ACTION IS")
    print("      RUNNING, so the bound is per-slot rather than per-cause. A")
    print("      tighter per-cause split would need the prefetch's own reason")
    print("      exported, which is flops for a bound that already holds.")

    print()
    print("=" * 78)
    print("  GATE port-demand: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
