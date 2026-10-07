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
#: ⛔ R4's must-fire is a DIFFERENT mutant, and the orthogonality is measured
#: rather than argued -- see §3's table.
BOTH_ARMS = ("both_ckod_image", "both_corpus_i2c", "both_corpus_all5")

#: Theorem 3's premises, quoted from `docs/J_LANE_PROOF.md` so the gate output
#: carries the same wording the proof does. ⛔ IF THESE DIVERGE FROM THE DOC THE
#: WHOLE POINT IS LOST, so `check_premise_text()` reads the doc and compares.
P10_TEXT = ("a dispatch consumes a valid head and leaves **at most one** slot\n"
            "per lane to be refilled")
P1_TEXT = ("One prefetch FSM, one refill in flight engine-wide.** A single "
           "`pst`/`pl` pair; there is no per-lane fetch engine.")

#: `D* = k * L_REFILL` with k = N_LANES = 5 and L_REFILL = 4.
#: ⚠ REPORTED AGAINST, NEVER ASSERTED AGAINST. A program may legally run below
#: `D*`; what `D*` buys is `J = 1`. `corpus_all5` runs four lanes at d = 9..13
#: ON PURPOSE and is port-INFEASIBLE by construction.
D_STAR = 20

#: the mutant must exceed the bound by more than rounding. It costs a refill
#: per DISPATCH, and a clocked byte is 16 dispatches, so anything below this is
#: a sign the mutant did not really take effect.
MUTANT_MIN_WORST = 8


def check_premise_text():
    """Do the sentences this gate prints still appear in `J_LANE_PROOF.md`?

    ⛔⛔ WITHOUT THIS THE WHOLE RULING IS DECORATIVE. R4 exists so the bench and
    the proof check the SAME statement; if the proof's wording is edited and the
    bench's copy is not, the two drift apart and the gate goes on claiming they
    agree. ⚠ It compares TEXT, so a reworded premise is a deliberate action
    that fails here and gets updated in both places -- which is the point.
    """
    path = os.path.join(ROOT, "docs", "J_LANE_PROOF.md")
    if not os.path.isfile(path):
        return None, "docs/J_LANE_PROOF.md is absent, so the premise this " \
                     "gate checks cannot be compared with the one the proof " \
                     "states"
    with io.open(path, encoding="utf-8", errors="replace") as fh:
        doc = fh.read()
    missing = [n for n, t in (("P10", P10_TEXT), ("P1", P1_TEXT))
               if t not in doc]
    if missing:
        return None, ("%s no longer appears VERBATIM in docs/J_LANE_PROOF.md, "
                      "so the bench and the proof have drifted apart. Update "
                      "both deliberately -- R4's only purpose is that they "
                      "read the same." % " and ".join(missing))
    return doc, None


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

    # -----------------------------------------------------------------
    # 3. R4 -- Theorem 3's premises, in the words the proof uses
    # -----------------------------------------------------------------
    print()
    print("  --- 3. R4: Theorem 3's premises, checked as written ---")
    ptxt, perr = check_premise_text()
    if perr:
        print("    *** %s" % perr)
        rc = 1
    else:
        print("    the bench prints these, and `docs/J_LANE_PROOF.md` states")
        print("    them -- compared textually, not trusted:")
    print("      P10  \"a dispatch consumes a valid head and leaves AT MOST")
    print("            ONE slot per lane to be refilled\"")
    print("      P1   \"One prefetch FSM, one refill in flight engine-wide.")
    print("            A single `pst`/`pl` pair; there is no per-lane fetch")
    print("            engine.\"")
    print("    ⚠ The Lean formalisation has not started. When it does, its")
    print("      premise is copied from this same sentence.")
    print()
    print("    %-26s %-8s %-9s %-11s %s"
          % ("arm", "R4", "worst", "in flight", "verdict"))
    # ⛔ THE THREE-WAY TABLE IS THE EVIDENCE THAT R4 IS NOT REDUNDANT WITH R.
    # Each mutant must be caught by exactly the layer whose sentence it breaks.
    want = ([(a, "ok") for a in CLEAN_ARMS]
            + [(a, "ok") for a in MUTANT_ARMS]       # R's mutant PASSES R4
            + [(a, "red") for a in BOTH_ARMS])      # R4's mutant FAILS R4
    for arm, expect in want:
        r = (blob.get(arm) or {}).get("r4")
        if r is None:
            print("    *** %-26s MISSING -- R4 never spoke on this arm" % arm)
            rc = 1
            continue
        ok = r["verdict"] == expect
        print("    %-26s %-8s %-9s %-11s %s"
              % (arm, r["verdict"], r["worst_slots"], r["max_inflight"],
                 "as expected" if ok else "*** WANTED %s" % expect))
        if not ok:
            rc = 1
    print("    ⇒ `M_CK_HOLD_INVAL` PASSES R4 and fails Layer R; "
          "`M_PFETCH_BOTH_INVAL`")
    print("      FAILS R4 and passes Layer R. Two sentences, two mutants,")
    print("      neither layer redundant -- which is why R4 was ordered")
    print("      separately once R turned out to check a RATE.")

    # -----------------------------------------------------------------
    # 4. R5 -- where the refill-bearing dispatches actually are
    # -----------------------------------------------------------------
    print()
    print("  --- 4. R5: are refill-bearing dispatches the ones §1 assumes? ---")
    print("    ⛔ THE QUESTION: `gate_dmin_clocked` (§1) computes `d_min` over")
    print("    REFILL-BEARING dispatches as if those are the action-BEGIN")
    print("    ones. If a refill is owed by some OTHER dispatch, `d_min` for")
    print("    contended programs was derived over the wrong set.")
    print()
    print("    %-26s %-11s %-10s %-9s %s"
          % ("arm", "non-retir", "bearing", "lane-min", "spec fills"))
    for arm in CLEAN_ARMS + MUTANT_ARMS + BOTH_ARMS:
        r = (blob.get(arm) or {}).get("r5")
        if r is None:
            print("    *** %-26s MISSING -- R5 never spoke" % arm)
            rc = 1
            continue
        print("    %-26s %-11s %-10s %-9s %s"
              % (arm, r["non_retiring"], r["bearing"], r["lane_min"],
                 r["speculative"]))
    # ⛔ ASSERTED ON THE CLEAN ARMS ONLY: by Amendment A1 a re-dispatch retires
    # nothing and owes no refill, so a non-retiring refill-bearing dispatch on
    # the real design means §1's set is wrong.
    bad = [a for a in CLEAN_ARMS
           if ((blob.get(a) or {}).get("r5") or {}).get("non_retiring", 1) != 0]
    if bad:
        print("    *** FAIL non-retiring refill-bearing dispatches on %s"
              % ", ".join(bad))
        print("        ⇒ CASE (b): `d_min` must be re-derived with refills at")
        print("        their MEASURED positions, and `J = 1` re-checked for")
        print("        those programs.")
        rc = 1
    else:
        print("    ⇒ CASE (a): ZERO non-retiring refill-bearing dispatches on")
        print("      every clean arm. Every refill is owed by a RETIRING")
        print("      dispatch, which is exactly the set §1's closed form")
        print("      covers. §1 stands, unchanged.")
    # and the must-fire for R5 itself: the mutant makes held dispatches bear
    # refills, so a zero here would mean R5 cannot see the thing it is for.
    fired = [a for a in MUTANT_ARMS
             if ((blob.get(a) or {}).get("r5") or {}).get("non_retiring", 0) > 0]
    print("    must-fire: `M_CK_HOLD_INVAL` makes HELD dispatches refill-"
          "bearing")
    print("      -> non-retiring > 0 on %d of %d arms %s"
          % (len(fired), len(MUTANT_ARMS),
             "" if len(fired) == len(MUTANT_ARMS) else "*** DID NOT FIRE"))
    if len(fired) != len(MUTANT_ARMS):
        rc = 1
    print()
    print("    per-lane MIN spacing vs D* = %d, with each program's own" % D_STAR)
    print("    admissibility -- REPORTED, NEVER ASSERTED:")
    print("      ⛔ `D*` IS A RATE BOUND -- \"in any window of d cycles the")
    print("      port is asked for at most k refills\" -- NOT a minimum")
    print("      separation. A program below `D*` is one that does not claim")
    print("      `J = 1`; it is not a design failure. `corpus_all5` runs four")
    print("      lanes at d = 9..13 ON PURPOSE.")
    for arm in CLEAN_ARMS:
        r = (blob.get(arm) or {}).get("r5")
        if r is None:
            continue
        lm = r["lane_min"]
        print("      %-26s lane-min %-6s %s"
              % (arm, lm,
                 "clears D*" if lm >= D_STAR
                 else "BELOW D* -- port-infeasible by construction"))

    print()
    print("  --- 5. what this gate does NOT check ---")
    print("    ⚠ IT BOUNDS REFILLS PER ACTION, NOT `D*` ITSELF. `D*` is a")
    print("      port-feasibility statement over a whole lane SET; this layer")
    print("      checks the per-action premise `D*` is computed FROM. A design")
    print("      that respected this bound and still oversubscribed the port")
    print("      would pass here and fail `gate_admissibility_1_6`.")
    print("    ⚠ THE SPARE FILL IS COUNTED AGAINST WHICHEVER ACTION IS")
    print("      RUNNING, so the bound is per-slot rather than per-cause. A")
    print("      tighter per-cause split would need the prefetch's own reason")
    print("      exported, which is flops for a bound that already holds.")

    # -----------------------------------------------------------------
    # 6. must-fire: the premise-text comparison must be able to fail
    # -----------------------------------------------------------------
    # ⛔⛔ OTHERWISE R4 IS DECORATIVE. The whole ruling is that the bench and
    # the proof read the same sentence; a comparison that cannot fail would let
    # them drift while this gate reported agreement. Priced by asking the real
    # function about a sentence the proof does not contain.
    print()
    print("  --- 6. must-fire: the premise comparison can fail ---")
    global P10_TEXT                                            # noqa: PLW0603
    keep = P10_TEXT
    try:
        P10_TEXT = "a dispatch leaves EXACTLY SEVEN slots to be refilled"
        _doc, err = check_premise_text()
    finally:
        P10_TEXT = keep
    fired = err is not None
    print("    a premise absent from the doc is reported   %s"
          % ("ok" if fired else "*** MISSED -- the comparison is vacuous"))
    if not fired:
        rc = 1
    _doc, err2 = check_premise_text()
    print("    and the real wording still matches          %s"
          % ("ok" if err2 is None else "*** %s" % err2))
    if err2 is not None:
        rc = 1

    print()
    print("=" * 78)
    print("  GATE port-demand: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
