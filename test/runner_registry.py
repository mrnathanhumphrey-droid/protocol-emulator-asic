"""THE RUNNER REGISTRY -- every script that can run a bench, enumerated ONCE.

⛔⛔ WHY (Wilson, WF2 #8 follow-up). The unknown-image check (layer V3-ID:
a program the V3 table does not know is red) was swept by running "the whole
gate list" -- and the gate list was `ci/run_gates.sh` only. Twice in one day a
runner outside it loaded unregistered images that nobody saw: gate_sda_hold's
generated frames (it reads only Layer H), then run_ckack's (it runs in the
local A2 suite). Fixing instances leaves the third one waiting in whichever
runner nobody listed. ⇒ The cause is fixed instead:
  * every runner is enumerated HERE -- the CI gate list and the A2 suite are
    READ from their own files (never copied), and everything else is declared
    below with its kind and reason;
  * `model/gate_runner_registry.py` turns red on any script that invokes a
    bench and is not in this registry;
  * V3-ID is FATAL in the bench (`clocked_conform.vh`), so a runner that loads
    an unknown image goes red WHICHEVER layer it reads.

KINDS: "ci" (ci/run_gates.sh), "a2" (model/a2/run_a2.py), and the declared:
  "workflow"  run by a CI workflow job of its own
  "helper"    called by a named runner (checked: the caller names it)
  "manual"    a measurement/recipe run by hand; its numbers are recorded and
              owned by a named gate. Loading an unknown image is still fatal.
  "retired"   kept for its record; superseded by a named gate
"""
from __future__ import annotations

import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

#: what counts as "invokes a bench": a simulator or elaborator AND a bench name
BENCH_TOOL = re.compile(r"(\bvvp\b|verilator|iverilog)")
BENCH_NAME = re.compile(r"\btb_[a-z0-9_]+")

#: (path) -> (kind, caller-or-owner, why). Paths are repo-relative.
DECLARED = {
    "ci/ln1_replay.py": ("workflow", ".github/workflows/test.yaml",
                         "the LN1 Lean replay job (JLane.step vs the RTL)"),
    "test/monitor_mustfire.py": ("helper", "test/sim_run.py",
                                 "the monitor judge's must-fire declarations "
                                 "(Wilson's must-fire ruling): it NAMES arms (compiled benches, "
                                 "images, plusargs) and invokes none"),
    "model/stale_records.py": ("helper", "model/gate_phase_coverage.py",
                               "the STALE / DEBT declarations: it NAMES benches "
                               "(a record's moved inputs) and invokes none"),
    "test/sweep_i2c_delay.py": ("manual", "model/gate_phase_coverage.py",
                                "the I2C peer-delay sweep (sigrok, local): its "
                                "record model/phase_sweep_i2c.json is held "
                                "fresh by the phase-coverage gate"),
    "model/a2/price_j_sweep.sh": ("manual", "model/a2/gate_j_program.py",
                                  "the live J sweep the gate's record names"),
    "model/nonadmissible.py": ("helper", "model/a2/program_a2.py",
                               "the non-admissible image registry (data); "
                               "names benches, runs none"),
    "test/a2_run.sh": ("helper", "ci/run_gates.sh",
                       "the WSL A2 measurement run_gates drives"),
    "test/coverage_sweep.sh": ("helper", "ci/run_gates.sh",
                               "the WSL coverage sweep run_gates drives"),
    # ⛔ R3 (10-23): it now READS bench output -- `trace_completed` judges a
    # trace-bench log (FATAL line, the cycles-run line) for the shell runners
    # that source it. It invokes no bench itself.
    "ci/tools.sh": ("helper", "test/phases_run.sh",
                    "the sourced shell library; its trace_completed judges "
                    "whether a trace-bench run FINISHED for the runners that "
                    "source it (refill_run, a2_run, store_run, phases_run)"),
    "test/ln1_vl.sh": ("helper", "ci/ln1_replay.py",
                       "the Verilator trace export LN1 drives"),
    # Wilson 11-12 ruled "usbdev (the USB device) is GATE": the USB device IS
    # gated -- by test/run_usbaddr.py and test/run_usbrst.py, both in CI. This
    # file is their shared golden + program + bench driver (it has no verdict
    # of its own), so it is registered as their helper; reported to Wilson.
    "test/usbdev.py": ("helper", "test/run_usbaddr.py",
                       "the USB device's golden, program and bench driver, "
                       "shared by run_usbaddr and run_usbrst (both CI gates)"),
    "test/phases_run.sh": ("helper", "ci/run_gates.sh",
                           "the WSL phase measurement run_gates drives"),
    "test/refill_run.sh": ("helper", "ci/run_gates.sh",
                           "the WSL refill measurement run_gates drives"),
    "test/store_run.sh": ("helper", "ci/run_gates.sh",
                          "the WSL store sentinel run_gates drives"),
    "test/verilator_trace.sh": ("helper", "test/gate_corpus_trace.py",
                                "the corpus gate's second simulator"),
    "test/xsim_run.sh": ("helper", "test/gate_xsim.py",
                         "the cross-simulator gate's Verilator half"),
    "test/toolchain.py": ("helper", "test/run_reload.py",
                          "the tool probe every runner imports; runs none"),
    "test/sim_run.py": ("helper", "test/run_lockstep.py",
                        "THE run path (Wilson's launch-helper ruling): every simulation run "
                        "takes its command from it, after the bound lookup; "
                        "it launches nothing itself"),
    "test/clean_room.py": ("manual", "model/gate_ruling_audit.py",
                           "the clean-room recipe check (every artefact has "
                           "a recipe)"),
    "test/check_reset_shift.py": ("manual", "model/a2/gate_j_program.py",
                                  "the reset-network +1 proof run before the "
                                  "sweep_w / cj_measured re-records"),
    "test/measure_a2_widest.py": ("manual", "model/a2/program_a2.py",
                                  "the recipe for an EMPIRICAL A2 budget"),
    "test/race_remeasure.py": ("manual", "model/gate_stored_numbers.py",
                               "ruling RA1's one-simulator re-measure"),
    "test/run_csat.py": ("manual", "model/gate_stored_numbers.py",
                         "the pre-registered C-saturation sweep"),
    "test/run_dstar_check.py": ("manual", "model/gate_stored_numbers.py",
                                "the D* refill-queueing measurement"),
    "test/run_jlane.py": ("manual", "model/gate_stored_numbers.py",
                          "the pre-registered T1 per-lane jitter sweep"),
    "test/run_param_points.py": ("manual", "model/gate_stored_numbers.py",
                                 "every bench at every parameter point"),
    "test/run_rxbw.py": ("manual", "model/gate_stored_numbers.py",
                         "the serial link's measured capacity"),
    "test/run_spl_compare.py": ("manual", "model/gate_stored_numbers.py",
                                "T3, single vs double action buffer"),
}

#: ⛔⛔ THE RESOURCES EACH RUNNER USES, DECLARED (Wilson 11-14). The inventory's
#: scheduler skipped gates by grepping their own text for `wsl.exe`, and missed
#: every runner that reaches WSL through a module it imports (run_pit_gcd, and --
#: measured from the inventory ledgers -- run_pit_clk / _rt / _s12 / _s3 too, all
#: through run_pit_capture). A scheduler reads THIS, never the file text.
#:   "wsl"     runs anything in WSL (Verilator, yosys, sby, the netlist, docker)
#:   "vivado"  runs Vivado
#:   "mem4g"   needs more than 4 GB (declared only: it cannot be detected)
#: `model/gate_runner_registry.py` is red on a runner whose own code, or a local
#: module it imports (one level), uses WSL / Vivado and that declares neither
#: the resource here nor, in RESOURCE_NOT_USED, why the hit is not a use.
_W = frozenset({"wsl"})
RESOURCES = {
    "ci/ln1_replay.py": _W,
    "fpga/sim/run_fpga_i2c.py": _W,
    "fpga/sim/run_fpga_loader.py": _W,
    "fpga/sim/run_fpga_onewire.py": _W,
    "model/gate_cdc_qual.py": _W,
    "model/gate_formal_miters.py": _W,
    "model/gate_halt_reset.py": _W,
    "model/gate_macro_inputs.py": _W,
    "model/gate_one_encoder.py": _W,
    "model/gate_predecode_netlist.py": _W,
    "model/gate_reset_audit.py": _W,
    "model/gate_rowmux_equiv.py": _W,
    "model/gate_rtl_lint.py": _W,
    "model/gate_select_copies.py": _W,
    "model/ta02/run_ta02.py": _W,
    "test/gate_corpus_trace.py": _W,
    "test/gate_fpga_synth.py": _W,
    "test/gate_xsim.py": _W,
    "test/race_remeasure.py": _W,
    "test/run_ckack.py": _W,
    "test/run_i2c.py": _W,
    "test/run_pit_capture.py": _W,
    "test/run_pit_clk.py": _W,
    "test/run_pit_gcd.py": _W,
    "test/run_pit_rt.py": _W,
    "test/run_pit_s12.py": _W,
    "test/run_pit_s3.py": _W,
    "test/run_recert.py": _W,
    "test/toolchain.py": _W,
}
#: a detected hit that is NOT a use, each with why (measured: the 11-14
#: inventory ledger shows every one of these runs on the Windows side)
RESOURCE_NOT_USED = {
    "test/gate_batch_equiv.py": "imports gate_corpus_trace only for feed_args(), "
                                "each image's host-feed plusargs; both builds run "
                                "on Windows iverilog",
    "model/gate_bench_indices.py": "imports gate_one_encoder only for "
                                   "dump_iverilog(), an iverilog dump",
    "model/gate_image_bounds.py": "imports run_recert only for its class tables",
    "model/gate_sp2_frontend.py": "imports run_ckack only for its image builder",
    "test/run_mutants.py": "imports gate_corpus_trace only for od_violations(), "
                           "pure Python (the record-mode inventory ledger: none through WSL)",
    "test/run_pit_s0.py": "its arms build and run on iverilog (the 11-14 inventory "
                          "ledger: none through WSL)",
    "test/run_spidelay.py": "imports run_recert's helpers; runs on iverilog "
                            "(the record-mode inventory ledger: none through WSL)",
    "test/run_spifram.py": "imports run_recert's helpers; runs on iverilog",
    "test/run_spim_witness.py": "imports run_recert's helpers; runs on iverilog "
                                "(the record-mode inventory ledger: none through WSL)",
}

#: what counts as a use, on comment-stripped code: a WSL call or a `wsl` /
#: `docker` argv word, or a toolchain lookup that resolves into WSL
#: (`tool("verilator")` / `tool("yosys")`); Vivado by its argv word or batch flag
_RES_PATS = {
    "wsl": re.compile(r"""wsl\.exe|["']wsl["']|["']docker["']|tool\(\s*["'](?:verilator|yosys)["']"""),
    "vivado": re.compile(r"""["']vivado["']|\bvivado\s+-mode\b"""),
}
#: shared infrastructure every runner imports: their hits are judged at the
#: CALL SITE (`tool("verilator")`), not on import
_RES_INFRA = ("test/toolchain.py", "test/sim_run.py", "test/runner_registry.py")
_RES_DIRS = ("test", "model", os.path.join("model", "a2"), "ci", os.path.join("fpga", "sim"))


def _code(path):
    return "\n".join(l.split("#", 1)[0] for l in _read(path).splitlines())


def detect_resources(rel, root=ROOT):
    """({resource}, [why]) for a runner: its own code plus every LOCAL module
    it imports, one level (never the shared infrastructure)."""
    p = os.path.join(root, rel)
    if not os.path.isfile(p):
        return set(), []
    own = _code(p)
    found, why = set(), []
    for k, rx in _RES_PATS.items():
        if rx.search(own):
            found.add(k)
            why.append("%s (own code)" % k)
    if rel.endswith(".py"):
        names = set(re.findall(r"^\s*import\s+([A-Za-z_]\w*)", own, re.M))
        names |= set(re.findall(r"^\s*from\s+([A-Za-z_]\w*)\s+import", own, re.M))
        for n in sorted(names):
            for d in _RES_DIRS:
                m = os.path.join(d, n + ".py").replace(os.sep, "/")
                if os.path.isfile(os.path.join(root, m)):
                    if m not in _RES_INFRA:
                        t = _code(os.path.join(root, m))
                        for k, rx in _RES_PATS.items():
                            if rx.search(t):
                                found.add(k)
                                why.append("%s (via %s)" % (k, m))
                    break
    return found, why


def resource_problems(reg=None, resources=None, not_used=None, root=ROOT):
    """[problem]: a detected resource neither declared nor explained; a
    declaration for a runner not in the registry."""
    reg = registry() if reg is None else reg
    resources = RESOURCES if resources is None else resources
    not_used = RESOURCE_NOT_USED if not_used is None else not_used
    out = []
    for rel in sorted(reg):
        found, why = detect_resources(rel, root)
        missing = found - set(resources.get(rel, ()))
        if missing and rel not in not_used:
            out.append("%s uses %s (%s) and declares neither the resource in "
                       "RESOURCES nor why it is not a use in RESOURCE_NOT_USED"
                       % (rel, ",".join(sorted(missing)), "; ".join(why[:3])))
    for rel in sorted((set(resources) | set(not_used)) - set(reg)):
        out.append("%s has a resource declaration but is not a registered runner" % rel)
    return out


GATES_SH = os.path.join(ROOT, "ci", "run_gates.sh")
RUN_A2 = os.path.join(ROOT, "model", "a2", "run_a2.py")


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read().replace("\r\n", "\n")


def ci_list(text=None):
    """The scripts in run_gates.sh's GATES=( ... ) block, as written there."""
    t = _read(GATES_SH) if text is None else text
    m = re.search(r"^GATES=\((.*?)^\)", t, re.S | re.M)
    if not m:
        return set()
    body = re.sub(r"#[^\n]*", "", m.group(1))
    return set(re.findall(r"(?:test|model|ci)/[A-Za-z0-9_/]+\.py", body))


def a2_list(text=None):
    """The scripts in the A2 suite's table, repo-relative."""
    t = _read(RUN_A2) if text is None else text
    out = set()
    for p in re.findall(r'\(\s*"([^"]+\.py)"', t):
        out.add(os.path.normpath(os.path.join("model", "a2", p))
                .replace("\\", "/"))
    return out


def registry():
    """{path: kind} -- the ONE enumeration of every runner."""
    reg = {p: "ci" for p in ci_list()}
    reg.update({p: "a2" for p in a2_list()})
    for p, (kind, _owner, _why) in DECLARED.items():
        reg.setdefault(p, kind)
    return reg


#: the trees walked for bench invokers. ⛔ fpga/sim ADDED (Wilson 10-17): the
#: FPGA benches' runners (run_fpga_onewire, run_fpga_i2c) lived there, outside
#: the walk, so they were in no registry and no suite ran them.
SCAN_TOPS = ("test", "model", "ci", "fpga/sim")


def bench_invokers(root=ROOT):
    """{path: text} for every .py / .sh under SCAN_TOPS that names a
    simulator and a bench. ⚠ Over-approximates (a mention in a comment
    counts), which is the safe direction: an extra entry is declared, a
    missing one is a runner nobody sweeps."""
    out = {}
    for top in SCAN_TOPS:
        for dp, dn, fn in os.walk(os.path.join(root, top)):
            dn[:] = [d for d in dn if not d.startswith(
                ("sim_build", "probe", "__pycache__", "build", "fixtures"))]
            for f in fn:
                if not f.endswith((".py", ".sh")) or f.startswith("probe"):
                    continue
                p = os.path.relpath(os.path.join(dp, f), root).replace("\\", "/")
                t = _read(os.path.join(root, p))
                if BENCH_TOOL.search(t) and BENCH_NAME.search(t):
                    out[p] = t
    return out
