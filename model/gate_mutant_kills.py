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
    # -- v2 R1: the word-organised store's addressing (bench tb_smoke) ------
    "M_STORE_BANK_SWAP": RUN_MUTANTS, "M_STORE_ROW_OFF1": RUN_MUTANTS,
    "M_STORE_WRONG_BANK": RUN_MUTANTS,
    # -- v2 step 2: the load's magic check (the equivalence gate's load section)
    "M_NO_MAGIC": "model/gate_v2_equiv.py",
    # CE1: the rebase at the observed rise (an `elsif` arm, undiscovered
    # until 10-27) -- killed on t_HIGH >= d by the UM10204 gate
    "M_CK_RISE_ELIGIBLE": "model/a2/gate_um10204.py",
    # -- v2 primitive 1: BRANCH_BIT (bench tb_equiv +BRCHECK) ---------------
    "M_BR_TGT_OFF1": "test/run_branch_check.py", "M_BR_ALWAYS": "test/run_branch_check.py",
    "M_BR_NEVER": "test/run_branch_check.py", "M_BR_LVL_INV": "test/run_branch_check.py",
    "M_BR_FETCH_PAST": "test/run_branch_check.py", "M_BR_W_ZERO": "test/run_branch_check.py",
    # silicon fix #2: killed on VALUE by Layer V1 (tb_trace, corpus_i2c)
    "M_TX_LOAD_ANYPHASE": RUN_MUTANTS,
    # silicon fix #3: killed on VALUE by Layer V-RX (tb_trace, corpus_spim)
    "M_CKRX_HEADER_PIN": RUN_MUTANTS,
    "M_CKRX_PP_OBSERVED": RUN_MUTANTS,
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
    # ruling CDC5: structural, on the M_CDC_RAW netlist; ui_in[7] -> run named
    "M_CDC_RAW": "model/gate_cdc.py",
    # ruling RX2: rx_e2e on corpus_all5 seed 1, 200k cycles (corpus gate, CI)
    "M_RX_NO_CAPGATE": "test/gate_corpus_trace.py",
    # ruling EX1: the d = 4 SPI read -- EARLY fails EX1 + rx_e2e; LATE has no
    # functional failure and is killed by never using the exact edge
    # (boundary consumes 0 against 1,016 clean)
    "M_RX_CAPGATE_EARLY": "test/gate_corpus_trace.py",
    "M_RX_CAPGATE_LATE": "test/gate_corpus_trace.py",
    # ruling CS1: inv_cdc.vh on corpus_sptgt (run_mutants' clocked family)
    "M_CS_RAW_D": "test/run_mutants.py",
    # -- WF2: a reload is a clean slate (run_reload: each red for its OWN
    # reason, matched on the FAIL text, not merely "some FAIL") --------------
    "M_NO_RELOAD_RESET": "test/run_reload.py",
    "M_NO_HALT_IDLE": "test/run_reload.py",
    "M_NO_RELOAD_FLUSH": "test/run_reload.py",
    "M_HALT_KEEP_CKBIT": "test/run_reload.py",
    "M_HALT_KEEP_HOLD": "test/run_reload.py",
    # reset-network halt: the twins on the halting reset -- the `keep` arm
    "M_KEEP_ON_HALT": "test/run_reload.py",
    "M_ONE_PHASE_HALT": "test/run_reload.py",
    # silicon fix #8 undone: moves the 9 TX images' digests (and reproduces
    # the pre-fix ones exactly -- the re-record's proof)
    "M_TX_PRELOAD": "test/run_lockstep.py",
    # -- rulings K and U --------------------------------------------------------
    "M_SHIFTIN_UNHELD": "model/gate_sda_hold.py",
    "M_HOLD_CLOCKED_ONLY": "model/gate_sda_hold.py",
    # -- ruling W -----------------------------------------------------------------
    "M_NO_HOLD_GATE": "model/gate_sda_hold.py",
    "M_SHIFTIN_UC_UNHELD": "model/gate_sda_hold.py",
    # ⚠ LOCAL ONLY: judged by sigrok's foreign I2C decoder, which CI does not
    # install -- so it runs under `run_a2.py` with the other sigrok gates.
    "M_IGNORE_ORDER": "test/run_i2c.py",
    # -- rulings CE1 / CE2 -------------------------------------------------------
    # HALF_HIGH ignored: CI's phase measurement (`half_mutant` arm) runs a
    # full-d HIGH where the lane is HALF_HIGH; `run_ckack` (local) also kills
    # it on Layer B gaps and the SCL period. The gl_test arms kill both.
    "M_HALF_IGNORED": "model/a2/gate_um10204.py",
    # CLK_INV ignored: the READs stop being mode 1 at the pins and the chip
    # receives 5B C4 one bit early (`run_spifram`, local, sigrok).
    "M_CLKINV_IGNORED": "test/run_spifram.py",
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
    # ⭐ RULING TM1 / TM2: EQUIVALENT BY REQUIREMENT. These are the timing
    # fixes' old forms; the ruling demands the new form be cycle-identical,
    # so a bench that COULD kill one would be reporting a failed fix. Their
    # evidence is the lockstep (pin + dispatch streams byte-identical vs the
    # pre-fix RTL), and for the argmin rewrite the SymbiYosys miter.
    "M_TM1_UNREG": "the old direct hold-counter load; TM1 records the load "
                   "and lands it a cycle later as SDA_HS - 1, so `l_hcnt` is "
                   "equal in every cycle -- equivalent by requirement.",
    # ⭐ RULING PR2: same standing. Its evidence is the lockstep vs 94cebb7
    # and `test/inv_curck.vh` in every bench (priced by S_PR_CKSTALE).
    "M_PR_CURSEL": "the old `l_clkpin[cur]` select; PR2 registers the same "
                   "value as `cur_ck` at dispatch and on a header write to "
                   "the current lane, so every clock-pin access reads the "
                   "same pin in the same cycle -- equivalent by requirement.",
}


#: ⛔⛔ RULING AC2 -- SCRATCH MUTANTS, REGISTERED. A mutant built into scratch
#: from `src/`'s own text (so lock hygiene charges no harden for a test-only
#: change) has no `ifdef` for `discover()` to find, and a mutant nothing
#: tracks decays quietly -- this project has seen it. So each killer DECLARES
#: its scratch mutants in a module-level `SCRATCH_MUTANTS = {name: what}`, and
#: this table names the killer. Red if a declared one is unlisted, a listed one
#: is declared nowhere (stale), the declaring file is not the listed killer,
#: or the killer is run by nothing. The KILL is the killer's own verdict, as
#: for `KILLERS`: each one reds when its scratch mutant survives.
SCRATCH = {
    # ruling W4: the slow-refill copy; the live subset kills it in CI
    "S_W4_SLOW_REFILL": "test/run_w_sweep.py",
    # ruling PR2: the registered clock pin left stale; inv_curck.vh must fire
    # (W live subset, CI)
    "S_PR_CKSTALE": "test/run_w_sweep.py",
    # ruling ACK (b): the wrong-instant SHIFTIN sampler; local (sigrok)
    "S_CK_COMMANDED_RISE": "test/run_ckack.py",
    # ruling CI5: the clocked SHIFT drives the header pin; V2 on the action
    # pin must catch it (a header-pin checker would not); CI
    "S_TX_HEADER_PIN": "test/run_cktx.py",
    # Wilson (WF2 #8 follow-up): the queue head read from the NEWER slot --
    # tb_tx's per-byte order check kills it (CI, run_mutants)
    "S_HEAD_NEWER": "test/run_mutants.py",
    # Wilson: two queues' heads swapped -- tb_tx's cross-queue diagnosis
    # (distinct per-queue data); also V2 pins-only red in run_cktx
    "S_QUEUE_SWAP": "test/run_mutants.py",
}


def discover_scratch():
    """{name: file} for every `SCRATCH_MUTANTS` dict declared at module level
    in model/ and test/ (probe_* excluded)."""
    import ast
    found = {}
    for base in ("model", "test"):
        for p in sorted(glob.glob(os.path.join(ROOT, base, "**", "*.py"),
                                  recursive=True)):
            if os.path.basename(p).startswith("probe_"):
                continue
            with open(p, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=p)
            rel = os.path.relpath(p, ROOT).replace(os.sep, "/")
            for node in tree.body:
                if (isinstance(node, ast.Assign) and isinstance(node.value,
                                                                ast.Dict)
                        and any(isinstance(t, ast.Name)
                                and t.id == "SCRATCH_MUTANTS"
                                for t in node.targets)):
                    for k in node.value.keys:
                        if isinstance(k, ast.Constant):
                            found[k.value] = rel
    return found


def audit_scratch(found, table, ran):
    probs = []
    for m, f in sorted(found.items()):
        if m not in table:
            probs.append("scratch mutant %s (declared in %s) is UNLISTED"
                         % (m, f))
        elif table[m] != f:
            probs.append("scratch mutant %s is declared in %s but listed "
                         "against %s" % (m, f, table[m]))
    for m, k in sorted(table.items()):
        if m not in found:
            probs.append("scratch mutant %s is listed but declared nowhere "
                         "-- stale" % m)
        if k not in ran:
            probs.append("scratch mutant %s's killer %s is run by NOTHING "
                         "(not CI, not run_a2)" % (m, k))
    return probs


def discover():
    """Every `ifdef`/`ifndef`/`elsif M_*` in the RTL and the bench includes.
    ⛔ `elsif` added 10-27 (v2 primitive 1): an `elsif` mutant arm was never
    discovered, so M_CK_RISE_ELIGIBLE (killed by gate_um10204) sat outside
    this audit since CE1 -- found when BRANCH_BIT's taken-test chain was."""
    found = set()
    pats = [os.path.join(ROOT, "src", "*.v"), os.path.join(ROOT, "test", "*.v"),
            os.path.join(ROOT, "test", "*.vh")]
    for pat in pats:
        for p in glob.glob(pat):
            if os.path.basename(p).startswith("probe_"):
                continue
            with open(p, encoding="utf-8", errors="replace") as fh:
                found |= set(re.findall(r"`(?:ifn?def|elsif)\s+(M_[A-Z0-9_]+)", fh.read()))
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
        _a, _d, _c, flags = gma.arm_flags("M_MU_SAME", d)
        return (any(f.startswith("EMPTY") for f in flags),
                "%d diff line(s), EMPTY rule %s"
                % (len(d), "fired" if any(f.startswith("EMPTY")
                                          for f in flags) else "silent"))
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

    # ---- AC2: scratch mutants ------------------------------------------
    sfound = discover_scratch()
    sprobs = audit_scratch(sfound, SCRATCH, ran)
    print("  %d scratch mutant(s) declared by their killers" % len(sfound))
    for m in sorted(SCRATCH):
        k = SCRATCH[m]
        print("    %-24s %-24s [%s]" % (m, k, "CI" if k in ggc.ci_gates()
                                       else "run_a2" if k in ggc.a2_gates()
                                       else "-"))
    for p in sprobs:
        print("  *** %s" % p)
        rc = 1

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
    checks.append(("an unlisted scratch mutant",
                   any("UNLISTED" in x for x in audit_scratch(
                       dict(sfound, S_MU_GHOST="test/x.py"), SCRATCH, ran))))
    checks.append(("a stale scratch entry",
                   any("stale" in x for x in audit_scratch(
                       sfound, dict(SCRATCH, S_MU_GONE="test/x.py"), ran))))
    checks.append(("a scratch killer nothing runs",
                   any("run by NOTHING" in x for x in audit_scratch(
                       dict(sfound, S_MU_IDLE="test/run_spl_compare.py"),
                       dict(SCRATCH, S_MU_IDLE="test/run_spl_compare.py"),
                       ran))))
    # ⛔ A SCRATCH LANDMARK IN DEAD CODE: `S_CK_COMMANDED_RISE`'s landmark once
    # matched exactly once inside `ifdef M_CKRX_PP_OBSERVED`, so its mutant was
    # the clean RTL. Every scratch builder goes through `scratch_sub`, which
    # must refuse that -- and must still accept the same line when it is live.
    sys.path.insert(0, os.path.join(ROOT, "test"))
    from toolchain import scratch_sub
    dead = ("`ifdef M_MU_X\n  assign h = a & b;\n`else\n  assign h = c;\n"
            "`endif\n")
    try:
        scratch_sub(dead, "  assign h = a & b;", "  assign h = a;", "plant")
        refused = False
    except SystemExit:
        refused = True
    checks.append(("a scratch landmark inside a mutant `ifdef", refused))
    try:
        live_ok = "a;" in scratch_sub(dead, "  assign h = c;",
                                      "  assign h = a;", "plant")
    except SystemExit:
        live_ok = False
    checks.append(("... and the live branch is accepted", live_ok))
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
