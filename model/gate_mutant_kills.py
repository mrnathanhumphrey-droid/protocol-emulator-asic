"""Ruling MU -- every mutant is KILLED by a named killer that actually runs, or
is a DECLARED survivor. Nothing in between.

⛔⛔ WHY. `gate_mutant_arms` holds the STRUCTURE of each `ifdef M_*` (minimal
delta, no comments, non-empty, no drift). Nothing held the KILL. Answering MU
measured it, over the 29 mutant defines in `src/` and the bench includes:

  * `test/run_mutants.py` -- 12 kills -- was run by NOTHING: not CI, not
    `run_a2`. Its kills were as old as the day each was last typed.
  * SIX clocked mutants (`M_CK_NEVER_RETIRE`, `M_CK_NO_ALTERNATE`,
    `M_CK_NO_PARK`, `M_CK_HOLD_RETIRES`, `M_CK_REBASE_2D`, ...) were named by
    no script at all -- each killed once by a hand-run probe and recorded in a
    spec. So were `M_ACK_DRIVES_SDA`, `M_BUS_NO_PULLDOWN` and the in-CI
    meaning of `M_PFETCH_NOWAIT`; `M_COMB_OUT` was priced only by hand.
  * And the clean design FAILED Layer R under iverilog (a cross-block race in
    the bench), which no runner had ever shown because none ran it.

⇒ `KILLERS` names, per mutant, the file that kills it. The gate checks that
  the killer EXISTS, that it is ACTUALLY RUN (in `ci/run_gates.sh`'s GATES or
  `model/a2/run_a2.py`'s), and that it names the mutant -- for `run_mutants.py`
  in one of its RUN lists, not merely in prose. `SURVIVORS` names, per mutant,
  why it cannot be killed. A define in neither is RED; an entry for a define
  that no longer exists is RED (stale).
⇒ The kill VERDICTS themselves are the killers' own: this gate holds the
  inventory and the wiring, and each killer reds on a survivor.

⚠ A MUTANT IDENTICAL TO CLEAN is `gate_mutant_arms` rule 3 (empty preprocessed
diff). It is priced here too, on a synthetic arm, because MU names it.
"""

from __future__ import annotations

import glob
import os
import re
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "test")):
    sys.path.insert(0, _p)

import gate_gates_complete as ggc                                 # noqa: E402

RUN_MUTANTS = "test/run_mutants.py"

#: mutant -> killer. ⛔ The killer must be RUN somewhere (checked) and must
#: name the mutant (checked); `run_mutants.py` must hold it in a RUN list.
KILLERS = {
    # -- run_mutants.py, double buffer / prime / rebase (bench tb_smoke) ----
    "M_BUF_NOINVAL": RUN_MUTANTS, "M_BUF_SWAP": RUN_MUTANTS,
    "M_BUF_CHAINFLIP": RUN_MUTANTS, "M_NO_PRIME": RUN_MUTANTS,
    "M_NO_REBASE": RUN_MUTANTS,
    # -- run_mutants.py, other benches ---------------------------------------
    "M_SHIFT_CLK_ALIAS": RUN_MUTANTS, "M_TX_IGNORE_TAG": RUN_MUTANTS,
    "M_TIMEOUT_PROCEED": RUN_MUTANTS, "M_UNGUARDED_ARMPIN": RUN_MUTANTS,
    "M_UNGUARDED_SAMPLE": RUN_MUTANTS, "M_SHARED_BITP": RUN_MUTANTS,
    "M_RX_NO_LANE": RUN_MUTANTS,
    # -- run_mutants.py, the clocked family (MU) -----------------------------
    "M_CK_NEVER_RETIRE": RUN_MUTANTS, "M_CK_NO_ALTERNATE": RUN_MUTANTS,
    "M_CK_NO_PARK": RUN_MUTANTS, "M_CK_HOLD_RETIRES": RUN_MUTANTS,
    "M_CK_REBASE_2D": RUN_MUTANTS, "M_CK_HOLD_INVAL": RUN_MUTANTS,
    "M_PFETCH_BOTH_INVAL": RUN_MUTANTS, "M_PFETCH_NOWAIT": RUN_MUTANTS,
    "M_ACK_DRIVES_SDA": RUN_MUTANTS, "M_BUS_NO_PULLDOWN": RUN_MUTANTS,
    # -- dedicated gates ------------------------------------------------------
    "M_NO_STORE_FULL": "model/gate_store_full.py",
    # RULING TF4: the naive retiming of TF1. The smoke bench PASSES on it;
    # only an exact schedule comparison sees a one-cycle shift.
    "M_TF1_LATE": "test/run_lockstep.py",
    # TF2-R3: a lane halted this cycle stays eligible one more
    "M_TF2_LIVE_LATE": "test/run_lockstep.py",
    "M_CK_OD_CLK_DRIVE": "test/gate_corpus_trace.py",
    "M_COMB_OUT": "model/gate_f2_local.py",
    # -- rulings K and U --------------------------------------------------------
    "M_SHIFTIN_UNHELD": "model/gate_sda_hold.py",
    "M_HOLD_CLOCKED_ONLY": "model/gate_sda_hold.py",
    # -- ruling W -----------------------------------------------------------------
    "M_NO_HOLD_GATE": "model/gate_sda_hold.py",
    "M_SHIFTIN_UC_UNHELD": "model/gate_sda_hold.py",
    # ⚠ LOCAL ONLY: judged by sigrok's foreign I2C decoder, which CI does not
    # install -- so it runs under `run_a2.py` with the other sigrok gates.
    "M_IGNORE_ORDER": "test/run_i2c.py",
}

#: mutant -> why no killer exists. Each is recorded at its site too.
SURVIVORS = {
    "M_NOOP_DRIVES": "out-of-range writes are silently ignored by the "
                     "simulators, so removing the guard changes nothing a "
                     "bench can see; the guard is real logic (3 cells in the "
                     "netlist) kept for synthesis portability.",
    "M_CK_NO_PHASE_RESET": "every clocked action already leaves the phase at "
                           "LOW and power-on resets it; the reset is defensive "
                           "(a lane halted mid-action).",
    "M_OD_CLK_PUSHPULL": "equivalent in the clocked path: every open-drain "
                         "clocked HIGH routes through the release arm; D2's "
                         "live must-fire is M_CK_OD_CLK_DRIVE.",
}


def discover():
    """Every `ifdef`/`ifndef M_*` in the RTL and the bench includes."""
    found = set()
    pats = [os.path.join(ROOT, "src", "*.v"), os.path.join(ROOT, "test", "*.v"),
            os.path.join(ROOT, "test", "*.vh")]
    for pat in pats:
        for p in glob.glob(pat):
            if os.path.basename(p).startswith("probe_"):
                continue
            with open(p, encoding="utf-8", errors="replace") as fh:
                found |= set(re.findall(r"`ifn?def\s+(M_[A-Z0-9_]+)", fh.read()))
    return found


def run_mutants_runs():
    """The defines `run_mutants.py` actually BUILDS (its RUN lists)."""
    import run_mutants as rm
    runs = set()
    for fam in ("MUTANTS", "TX_MUTANTS", "EDGE_MUTANTS", "HALF_MUTANTS",
                "PINRANGE_MUTANTS", "CLOCKED_MUTANTS"):
        for e in getattr(rm, fam, []):
            runs.add(e[0])
    return runs - {"M_COMB_OUT", "M_NOOP_DRIVES"}       # structural, not built


def run_somewhere():
    """Files run by CI's GATES or run_a2's GATES (repo-relative)."""
    return set(ggc.ci_gates()) | set(ggc.a2_gates())


def audit(found, killers, survivors, ran, rm_runs, read):
    probs = []
    for m in sorted(found):
        if m in killers and m in survivors:
            probs.append("%s is BOTH a kill and a declared survivor" % m)
        elif m not in killers and m not in survivors:
            probs.append("%s is UNREGISTERED: no killer, no declared survivor"
                         % m)
    for m in sorted((set(killers) | set(survivors)) - found):
        probs.append("%s is registered but no such `ifdef` exists -- stale" % m)
    for m, k in sorted(killers.items()):
        if m not in found:
            continue
        if k not in ran:
            probs.append("%s's killer %s is run by NOTHING (not CI, not run_a2)"
                         % (m, k))
        txt = read(k)
        if txt is None:
            probs.append("%s's killer %s does not exist" % (m, k))
        elif not re.search(r"\b%s\b" % re.escape(m), txt):
            probs.append("%s's killer %s never names it" % (m, k))
        elif k == RUN_MUTANTS and m not in rm_runs:
            probs.append("%s is named by run_mutants.py but in no RUN list -- "
                         "named is not built" % m)
    return probs


def _read(rel):
    p = os.path.join(ROOT, rel)
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def identical_arm_is_red():
    """MU's second must-fire: a mutant whose arms are identical to clean."""
    import gate_mutant_arms as gma
    src = ("module mu_same(output wire y);\n"
           "`ifdef M_MU_SAME\n  assign y = 1'b1;\n`else\n  assign y = 1'b1;\n"
           "`endif\nendmodule\n")
    fd, path = tempfile.mkstemp(suffix=".v")
    with os.fdopen(fd, "w") as fh:
        fh.write(src)
    try:
        a, b = gma.preprocess(path), gma.preprocess(path, "M_MU_SAME")
        if a is None or b is None:
            return False, "preprocess failed"
        d = gma.diff_lines(a, b)
        return (len(d) == 0), "%d diff line(s)" % len(d)
    finally:
        os.remove(path)


def main() -> int:
    print()
    print("=" * 78)
    print("  MU -- EVERY MUTANT KILLED BY A RUN KILLER, OR A DECLARED SURVIVOR")
    print("=" * 78)
    found = discover()
    ran = run_somewhere()
    rm_runs = run_mutants_runs()
    probs = audit(found, KILLERS, SURVIVORS, ran, rm_runs, _read)
    by = {}
    for m in sorted(found):
        by.setdefault(KILLERS.get(m, "DECLARED SURVIVOR" if m in SURVIVORS
                                  else "*** NONE"), []).append(m)
    print("  %d mutant define(s) in src/ and the bench includes" % len(found))
    for k in sorted(by):
        where = ("CI" if k in ggc.ci_gates() else "run_a2"
                 if k in ggc.a2_gates() else "-")
        print("    %-28s [%-6s] %2d  %s" % (k, where, len(by[k]),
                                         " ".join(by[k])))
    rc = 0
    for p in probs:
        print("  *** %s" % p)
        rc = 1
    if not probs:
        print("  every mutant is killed by a killer that runs, or declared")

    print()
    print("  --- must-fire ---")
    checks = []
    p1 = audit(found | {"M_MU_UNREGISTERED"}, KILLERS, SURVIVORS, ran,
               rm_runs, _read)
    checks.append(("an unregistered dummy mutant",
                   any("M_MU_UNREGISTERED is UNREGISTERED" in x for x in p1)))
    k2 = dict(KILLERS, M_MU_GHOST=RUN_MUTANTS)
    p2 = audit(found | {"M_MU_GHOST"}, k2, SURVIVORS, ran, rm_runs,
               lambda r: (_read(r) or "") + " M_MU_GHOST")
    checks.append(("named by run_mutants but in no RUN list",
                   any("M_MU_GHOST is named" in x for x in p2)))
    k3 = dict(KILLERS, M_ACK_DRIVES_SDA="test/run_spl_compare.py")
    p3 = audit(found, k3, SURVIVORS, ran, rm_runs, _read)
    checks.append(("a killer that nothing runs",
                   any("run by NOTHING" in x for x in p3)))
    p4 = audit(found, dict(KILLERS, M_MU_STALE=RUN_MUTANTS), SURVIVORS, ran,
               rm_runs, _read)
    checks.append(("a stale registry entry", any("stale" in x for x in p4)))
    same, why = identical_arm_is_red()
    checks.append(("a mutant identical to clean (empty diff, %s)" % why, same))
    for label, hit in checks:
        print("    %-50s %s" % (label, "ok" if hit else "*** MISSED"))
        if not hit:
            rc = 1

    print()
    print("=" * 78)
    print("  GATE mutant-kills: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
