"""META-TEST: every gate's check, stubbed to always pass, must turn its gate red.

    python model/gate_meta.py [--tier fast|slow|all] [--jobs N]

⛔⛔ THE MUST-FIRE AUDIT AS A GATE (Wilson 10-21 / 10-22). A must-fire proves a
check CAN fail only if it runs the check the gate really uses. The 10-22 static
audit found 8 hollow and 20 suspect must-fires -- copies that drifted, inputs
that went empty -- and fixed them by hand. This gate keeps them fixed: for each
registered SEAM (a gate's real check function) it re-runs ONLY that gate with
the seam replaced by an always-pass stub (model/meta_stub.py: record the clean
answer, replay it to every planted defect) and requires the gate to EXIT
NON-ZERO. A gate that stays green has a check no must-fire prices.

⇒ KNOWN_GAPS holds the stubs that stay green TODAY, each with its finding id
  (probe_reports/meta_inventory.txt). A gap that goes red has been FIXED and
  its entry is STALE -- also red -- so the list can only shrink honestly.
⇒ A seam whose stub was never CALLED is a registry error (the gate does not
  use that function), red: a seam nobody calls proves nothing either way.

TIERS: `fast` gates are pure Python over tracked files or the run's own
pre-step JSONs (they need run_gates' PE_* env when they read a measurement);
`slow` gates rebuild and simulate, minutes per seam -- the CI matrix owns them
(one job per seam). The local suite runs `fast`.
"""
from __future__ import annotations

import concurrent.futures as cf
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STUB = os.path.join(HERE, "meta_stub.py")

#: (gate, seam = module.function, tier, policy). `policy` is the seam's
#: ALWAYS-PASS answer, by its return contract (model/meta_stub.py _pass):
#: E empty problems, E0/E1 empty element 0/1, T True, Z 0, NONE None, NORAISE
#: never raise, and named shapes. An OWED policy (none since 3a, 10-24) is
#: reported by name by a run, never guessed.
SEAMS = (
    ("model/gate_bench_lint.py", "gate_bench_lint.scan", "fast", "E"),
    ("model/gate_bench_lint.py", "gate_bench_lint.narrow_names", "fast", "E"),
    ("model/gate_bench_race.py", "gate_bench_race.scan", "fast", "E"),
    ("model/gate_degenerate_fields.py", "gate_degenerate_fields.violations", "fast", "E"),
    ("test/gate_tb_elaborates.py", "gate_tb_elaborates.preprocess", "fast", "PRE"),
    ("model/gate_ruling_audit.py", "gate_ruling_audit.anchor_resolves", "fast", "T"),
    ("model/gate_mutant_arms.py", "gate_mutant_arms.audit", "fast", "Z0"),
    ("model/gate_reset_audit.py", "gate_reset_audit.stale_entries", "fast", "E"),
    ("model/gate_reset_audit.py", "gate_reset_audit.check_fix_alias", "fast", "Z"),
    ("model/gate_reset_audit.py", "gate_reset_audit.unreset_groups", "fast", "E"),
    ("model/gate_reset_audit.py", "gate_reset_audit.allowlist_problems", "fast", "E"),
    ("model/gate_stored_numbers.py", "gate_stored_numbers.check_sites", "fast", "E"),
    ("model/gate_stored_numbers.py", "gate_stored_numbers.readme_audit", "fast", "E"),
    ("model/gate_stored_numbers.py", "gate_stored_numbers.coverage_problems", "fast", "E"),
    ("model/gate_stored_numbers.py", "gate_stored_numbers.scrape_text", "fast", "E"),
    ("model/gate_bench_indices.py", "gate_bench_indices.check_file", "fast", "E"),
    ("model/gate_j_proof_anchors.py", "gate_j_proof_anchors.check", "fast", "E"),
    ("model/gate_j_proof_anchors.py", "gate_j_proof_anchors.s7_gone", "fast", "E"),
    ("model/a2/gate_j_program.py", "gate_j_program.check_sweep_w", "fast", "E"),
    ("model/a2/gate_j_program.py", "gate_j_program.sweep_violations", "fast", "E"),
    ("model/a2/gate_j_program.py", "gate_j_program.live_violations", "fast", "E"),
    ("model/a2/gate_dmin_clocked.py", "gate_j_program.admissible", "fast", "T"),
    ("model/a2/gate_um10204.py", "gate_um10204.lane_problems", "fast", "E"),
    ("model/gate_port_demand.py", "gate_port_demand.check_premise_text", "fast", "P1NONE"),
    ("model/a2/gate_a2_program.py", "gate_a2_program.stale_rows", "fast", "E"),
    ("model/gate_gates_complete.py", "gate_gates_complete.audit", "fast", "E"),
    ("model/gate_admissible_images.py", "gate_admissible_images.audit", "fast", "E0"),
    ("model/gate_admissible_images.py", "pe_isa.flag_problems", "fast", "E"),
    ("model/gate_admissible_images.py", "nonadmissible.registry_problems", "fast", "E"),
    ("model/gate_admissible_images.py", "nonadmissible.no_rta_problems", "fast", "E"),
    ("model/gate_wire_feed.py", "gate_wire_feed.audit", "fast", "E0"),
    ("model/gate_wire_feed.py", "gate_wire_feed.v3_table_currency", "fast", "NONE"),
    ("model/gate_wire_feed.py", "gate_wire_feed.scratch_v3_problems", "fast", "E"),
    ("model/gate_wire_feed.py", "gate_wire_feed.published_problems", "fast", "E"),
    ("model/gate_image_bounds.py", "gate_image_bounds.audit", "fast", "E"),
    ("model/gate_image_bounds.py", "gate_image_bounds.class_problems", "fast", "E"),
    ("model/gate_sim_runs.py", "gate_sim_runs.scan", "fast", "E"),
    ("model/gate_sim_runs.py", "gate_sim_runs.cocotb_ok", "fast", "T"),
    ("model/gate_sim_runs.py", "gate_sim_runs.hidden_problems", "fast", "E0"),
    # ⭐ production functions main() never calls on real data -- unstubbable
    # under the first (replay) design, fine under constant-pass policies
    ("model/gate_sim_runs.py", "sim_run.trace_incomplete", "fast", "NONE"),
    ("model/gate_sim_runs.py", "sim_run.check", "fast", "NORAISE"),
    ("model/gate_sim_runs.py", "sim_run.is_scratch", "fast", "T"),
    ("model/gate_admissible_images.py", "nonadmissible.require", "fast", "NORAISE"),
    ("model/gate_i2c_hw_witness.py", "gate_i2c_hw_witness.audit", "fast", "E"),
    ("model/gate_onewire_hw_witness.py", "gate_onewire_hw_witness.audit", "fast", "E"),
    ("model/gate_onewire_hw_witness.py", "gate_onewire_hw_witness.feed_matches", "fast", "T"),
    ("model/gate_flow_config.py", "gate_flow_config.audit", "fast", "E0"),
    ("model/gate_flow_config.py", "gate_flow_config.env_audit", "fast", "E"),
    ("model/gate_shell_rc.py", "gate_shell_rc.audit_text", "fast", "E"),
    ("model/gate_except.py", "gate_except.audit", "fast", "E"),
    ("model/gate_tool_pinning.py", "gate_tool_pinning.audit", "fast", "E"),
    ("model/gate_tool_pinning.py", "gate_tool_pinning.audit_sh", "fast", "E"),
    ("model/gate_tool_pinning.py", "gate_tool_pinning.audit_py", "fast", "E"),
    ("model/gate_f2_local.py", "f2_flop_driven_outputs.json_verdict", "fast", "JV"),
    ("model/gate_cdc.py", "gate_cdc.check", "fast", "E"),
    ("model/gate_slang_lint.py", "gate_slang_lint.judge", "fast", "E0"),
    ("model/gate_halt_reset.py", "gate_halt_reset.check_text", "fast", "E"),
    ("model/gate_halt_reset.py", "gate_halt_reset.check_netlist", "fast", "E0"),
    ("model/gate_runner_registry.py", "gate_runner_registry.check", "fast", "E"),
    ("model/gate_sp2_frontend.py", "gate_sp2_frontend.first_diff", "fast", "NONE"),
    ("model/gate_count_ranges.py", "pe_asm.split_counts", "fast", "NORAISE"),
    ("model/gate_count_ranges.py", "count_ranges.ranges", "fast", "NORAISE"),
    ("model/gate_ce5_freeze.py", "gate_ce5_freeze.changed", "fast", "CE5"),
    ("model/gate_mutant_kills.py", "gate_mutant_kills.audit", "fast", "E"),
    ("model/gate_mutant_kills.py", "gate_mutant_kills.audit_scratch", "fast", "E"),
    ("model/gate_bench_races.py", "gate_bench_races.races", "fast", "E"),
    ("test/gate_manifest.py", "gate_manifest.check", "fast", "E0"),
    ("model/gate_i2c_order.py", "gate_i2c_order.audit", "fast", "E"),
    ("model/gate_store_full.py", "gate_store_full.audit", "fast", "E0"),
    ("model/gate_program_index.py", "gate_program_index.guard_used", "fast", "NOTNONE"),
    ("model/part1_param_contract.py", "part1_param_contract.rx_lane_verdict", "fast", "RXOK"),
    ("test/gl_harness_check.py", "gl_harness_check.reachins", "fast", "E1"),
    ("test/check_vectors.py", "check_vectors.pattern_ok", "fast", "T"),
    ("test/benchset.py", "benchset.cocotb_blind_spot", "fast", "E"),
    ("test/benchset.py", "benchset.plusargs_read", "fast", "E"),
    ("test/benchset.py", "benchset.includes_file", "fast", "T"),
    ("test/gate_coverage.py", "gate_coverage.point_problems", "fast", "E"),
    ("test/gate_coverage.py", "gate_coverage.stale_problems", "fast", "E"),
    ("test/gate_coverage.py", "gate_coverage.anchor_problems", "fast", "E"),
    ("test/gate_coverage.py", "gate_coverage.reason_problems", "fast", "REASON"),
    ("test/gate_coverage.py", "gate_coverage.check_pinned_tool_quiet", "fast", "Z"),
    ("test/gate_coverage.py", "gate_coverage.false_gaps", "fast", "E"),
    ("model/pe_asm.py", "pe_asm.check_queue_ownership", "fast", "NORAISE"),
    ("model/pe_asm.py", "pe_asm.check_receive_pin", "fast", "NORAISE"),
    ("model/pe_asm.py", "pe_asm.check_clocked_hold_delay", "fast", "NORAISE"),
    ("model/pe_asm.py", "pe_asm.check_mode_floor", "fast", "NORAISE"),
    ("model/pe_asm.py", "pe_asm.check_queue_slot", "fast", "NORAISE"),
    ("model/pe_asm.py", "pe_asm.check_shift_clock_alias", "fast", "NORAISE"),
    ("model/pe_asm.py", "pe_asm.check_i2c_order", "fast", "NORAISE"),
    ("model/pe_asm.py", "pe_asm.check_open_drain_bank", "fast", "NORAISE"),
    ("model/pe_asm.py", "pe_asm.check_park_overlap", "fast", "NORAISE"),
    # ⚠ the SHARED zero-spacing rule, not pe_asm's wrapper: program_a2.lane_set
    # enforces it independently, so stubbing the wrapper alone left that second
    # path to raise (measured, meta run 2)
    ("model/pe_asm.py", "zero_spacing.check", "fast", "NORAISE"),
    # ---- slow: rebuild + simulate; the CI matrix owns these --------------
    ("test/gate_xsim.py", "gate_xsim.first_diff", "slow", "S"),
    ("model/gate_one_encoder.py", "gate_one_encoder.dump_iverilog", "slow", "CLEANVALS"),
    ("model/gate_one_encoder.py", "gate_one_encoder.find_second_definitions", "slow", "E"),
    ("model/gate_one_encoder.py", "gate_one_encoder.width_problems", "slow", "E"),
    ("test/gate_corpus_trace.py", "gate_corpus_trace.precondition", "slow", "PREC"),
    ("test/gate_corpus_trace.py", "gate_corpus_trace.od_violations", "slow", "E"),
    ("test/gate_corpus_trace.py", "gate_corpus_trace.pin_problem", "slow", "NONE"),
    ("model/gate_formal_miters.py", "gate_formal_miters.verdict", "slow", "OK"),
    ("model/gate_rtl_lint.py", "gate_rtl_lint.judge", "slow", "E0"),
    ("model/gate_hold_offset.py", "gate_hold_offset.judge", "slow", "E0"),
    ("test/run_uartrx.py", "uart_rx.build", "slow", "NORAISE"),
    ("test/run_wirefeed_mf.py", "zero_spacing.find", "slow", "E"),
    ("test/run_onewire.py", "run_onewire.judge", "slow", "ALLOK"),
    ("test/run_mutants.py", "run_mutants.verdict", "slow", "NOFIRE"),
    ("test/run_lockstep.py", "run_lockstep.compare", "slow", "LOCK"),
    ("test/run_w_sweep.py", "run_w_sweep.viol", "slow", "Z"),
    ("test/run_spidelay.py", "run_spidelay.transition_problems", "slow", "E"),
    ("test/run_spim_witness.py", "run_spim_witness.judge", "slow", "DOK"),
    ("model/gate_sda_hold.py", "gate_sda_hold.run", "slow", "NOFAIL"),
    ("model/gate_sda_hold.py", "gate_sda_hold.image_problems", "slow", "E"),
)

#: Gates with NO stubbable check, each with why -- every gate in
#: ci/run_gates.sh is in SEAMS or here (checked), so none is silently unaudited.
NOT_STUBBABLE = {
    "test/run_v2window.py": "F4: no must-fire at all; its inside-window arm "
                            "prints and never feeds the verdict",
    "model/gate_spuri_candidates.py": "INLINE: both must-fires compare counts "
                                      "inline in main(); no check function",
    "test/run_rxfast.py": "verdict made inside tb_rxbw.v; priced by its d = 60 "
                          "must-fire arm",
    "test/run_uarttx.py": "verdict made inside tb_uarttx.v; priced by its two "
                          "mutant arms",
    "test/run_reload.py": "verdict made inside tb_reload.v; priced by its nine "
                          "mutant arms",
    "test/run_cktx.py": "verdict made inside clocked_conform.vh; priced by its "
                        "six mutant arms",
    "test/run_spitgt.py": "verdict made inside tb_spitgt.v; priced by its "
                          "eight plusarg arms",
    "test/run_rxbw.py": "verdict made inside tb_rxbw.v; priced by its "
                        "over-rate sweep arms",
    "model/gate_pin_matrix.py": "matrix() computes a coverage map, not a "
                                "verdict: there is no 'always pass' answer",
    "model/gate_meta.py": "this gate",
}

#: (gate, seam) -> finding id: stubs that stay GREEN today. Each must go red
#: when its finding is fixed, and is then STALE (red) until removed.
KNOWN_GAPS: dict = {
    # F2 (gate_tool_pinning.audit) CLOSED 10-24: its must-fires now go
    # through audit(), the dispatcher main() uses.
}

LINE = re.compile(r"^META-STUB \S+ \S+ calls=(\d+) rc=(\S+)", re.M)


def one(gate, seam, policy, timeout):
    if policy == "OWED":
        return gate, seam, None, None, "its always-pass policy is OWED"
    try:
        r = subprocess.run([sys.executable, STUB, gate, seam, policy], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return gate, seam, None, None, "timed out after %ds" % timeout
    out = (r.stdout or "") + (r.stderr or "")
    m = LINE.search(out)
    calls = int(m.group(1)) if m else None
    first = next((l.strip() for l in out.splitlines() if "***" in l), "")
    if calls is None:
        # ⛔ 3c (10-24): a stub run that CRASHED printed no `***` line, so CI
        # said only "did not run to its end:" with nothing after it -- the
        # traceback is in the tail, so the tail is what is reported
        tail = [l.strip() for l in out.splitlines() if l.strip()][-4:]
        return gate, seam, r.returncode, calls, (first[:110] + " || tail: "
                                                 + " | ".join(tail))[:600]
    return gate, seam, r.returncode, calls, first[:110]


def gate_list():
    """The gates ci/run_gates.sh runs (its GATES=( ... ) array)."""
    with open(os.path.join(ROOT, "ci", "run_gates.sh"), encoding="utf-8") as fh:
        txt = fh.read()
    body = txt[txt.index("GATES=("):]
    body = body[:body.index("\n)")]
    return sorted(set(re.findall(r"^\s+([a-z][\w/.-]*\.(?:py|sh))", body, re.M)))


def coverage_problems(gates, seams=None, nots=None):
    """Every suite gate is in SEAMS or NOT_STUBBABLE, never both, and neither
    table names a gate the suite does not run."""
    seams = SEAMS if seams is None else seams
    nots = NOT_STUBBABLE if nots is None else nots
    have = {g for g, _s, _t, _p in seams}
    probs = []
    for g in gates:
        if g not in have and g not in nots:
            probs.append("%s is in the suite but in neither SEAMS nor "
                         "NOT_STUBBABLE -- unaudited" % g)
        if g in have and g in nots:
            probs.append("%s is in BOTH SEAMS and NOT_STUBBABLE" % g)
    for g in sorted((have | set(nots)) - set(gates)):
        if g != "model/gate_meta.py":
            probs.append("%s is in the meta registry but not in the suite" % g)
    return probs


def judge(results, gaps):
    """[problem] -- the gate and its must-fire both call this."""
    probs = []
    for gate, seam, rc, calls, first in results:
        key = (gate, seam)
        if rc is None:
            probs.append("%s %s: %s" % (gate, seam, first))
        elif calls == 0:
            probs.append("%s %s: the stub was NEVER CALLED -- the registry "
                         "names a function this gate does not use" % key)
        elif calls is None:
            probs.append("%s %s: the gate did not run to its end under the "
                         "stub (rc %s): %s" % (gate, seam, rc, first))
        elif rc == 0 and key not in gaps:
            probs.append("%s %s: STAYED GREEN with its check stubbed to pass "
                         "-- no must-fire prices it" % key)
        elif rc != 0 and key in gaps:
            probs.append("%s %s: went RED, so KNOWN_GAPS[%s] is stale -- "
                         "remove it" % (gate, seam, gaps[key][:3]))
    for key in gaps:
        if key not in {(g, s) for g, s, *_r in results} and \
                key not in {(g, s) for g, s, _t, _p in SEAMS}:
            probs.append("%s %s: a KNOWN_GAPS entry for no registered seam" % key)
    return probs


def select(tier, seam=None):
    """[(gate, seam, policy)] for a tier, or the ONE row naming `seam`."""
    if seam is not None:
        return [(g, s, p) for g, s, _t, p in SEAMS if s == seam]
    return [(g, s, p) for g, s, t, p in SEAMS if tier == "all" or t == tier]


def main() -> int:
    tier = "fast"
    if "--tier" in sys.argv:
        tier = sys.argv[sys.argv.index("--tier") + 1]
    if "--list" in sys.argv:
        # ⭐ THE CI MATRIX IS READ FROM SEAMS, never typed into the workflow:
        # a seam added here is in CI, and none can drop out silently (3b)
        import json
        print(json.dumps([s for _g, s, _p in
                          select(sys.argv[sys.argv.index("--list") + 1])]))
        return 0
    seam = sys.argv[sys.argv.index("--seam") + 1] if "--seam" in sys.argv else None
    jobs = int(sys.argv[sys.argv.index("--jobs") + 1]) if "--jobs" in sys.argv else 4
    todo = select(tier, seam)
    if seam is not None and len(todo) != 1:
        print("  *** --seam %s names %d SEAMS rows (want exactly 1)" % (seam, len(todo)))
        print("  GATE meta: FAILED")
        return 1
    print()
    print("=" * 78)
    print("  META-TEST -- each gate's check stubbed to always pass must turn it red")
    print("=" * 78)
    print("  %s: %d seam(s) over %d gate(s), %d job(s)"
          % ("seam " + seam if seam else "tier " + tier, len(todo), len({g for g, _s, _p in todo}), jobs))
    timeout = 1800 if tier != "fast" or seam is not None else 600
    with cf.ThreadPoolExecutor(max_workers=jobs) as ex:
        results = list(ex.map(lambda gs: one(gs[0], gs[1], gs[2], timeout),
                              todo))
    for gate, seam, rc, calls, first in sorted(results):
        gap = (gate, seam) in KNOWN_GAPS
        verdict = ("red  ok" if rc not in (0, None) and calls
                   else "green  (KNOWN GAP %s)" % KNOWN_GAPS[(gate, seam)][:3]
                   if gap and rc == 0 else "*** rc=%s calls=%s" % (rc, calls))
        print("    %-34s %-44s %s" % (os.path.basename(gate), seam, verdict))
    rc = 0
    probs = judge(results, {k: v for k, v in KNOWN_GAPS.items()
                            if any((g, s) == k for g, s, _p in todo)})
    probs += coverage_problems(gate_list())
    for p in probs:
        print("  *** %s" % p)
        rc = 1
    # ---- must-fire: the judge rejects what it claims to ------------------
    print()
    print("  --- must-fire: the judge rejects what it claims to ---")
    g = ("model/x.py", "x.f")
    for what, res, gaps in (
            ("a stub that stayed green, undeclared", [g + (0, 3, "")], {}),
            ("a stub never called", [g + (1, 0, "")], {}),
            ("a declared gap that went red (stale)", [g + (1, 3, "")],
             {g: "F0: x"}),
            ("a run that did not reach its end", [g + (1, None, "boom")], {})):
        red = bool(judge(res, gaps))
        print("    %-46s %s" % (what, "red  ok" if red else "*** MISSED"))
        if not red:
            rc = 1
    for what, gl in (("a suite gate in neither table",
                      gate_list() + ["model/gate_new.py"]),):
        red = bool(coverage_problems(gl))
        print("    %-46s %s" % (what, "red  ok" if red else "*** MISSED"))
        if not red:
            rc = 1
    # a --seam that names no row would run nothing and pass (the CI matrix job)
    red = len(select("slow", "no_such.seam")) != 1
    print("    %-46s %s" % ("a --seam naming no SEAMS row",
                            "red  ok" if red else "*** MISSED"))
    if not red:
        rc = 1
    print()
    print("  GATE meta: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
