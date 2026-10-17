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
    "model/a2/gate_cj_bounds.py": ("retired", "model/a2/gate_c3_requote.py",
                                   "ruling CJ: every claim moved to gates "
                                   "that run"),
    "model/a2/price_j_sweep.sh": ("manual", "model/a2/gate_j_program.py",
                                  "the live J sweep the gate's record names"),
    "model/nonadmissible.py": ("helper", "model/a2/program_a2.py",
                               "the non-admissible image registry (data); "
                               "names benches, runs none"),
    "test/a2_run.sh": ("helper", "ci/run_gates.sh",
                       "the WSL A2 measurement run_gates drives"),
    "test/coverage_sweep.sh": ("helper", "ci/run_gates.sh",
                               "the WSL coverage sweep run_gates drives"),
    "test/ln1_vl.sh": ("helper", "ci/ln1_replay.py",
                       "the Verilator trace export LN1 drives"),
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


def bench_invokers(root=ROOT):
    """{path: text} for every .py / .sh under test/, model/, ci/ that names a
    simulator and a bench. ⚠ Over-approximates (a mention in a comment
    counts), which is the safe direction: an extra entry is declared, a
    missing one is a runner nobody sweeps."""
    out = {}
    for top in ("test", "model", "ci"):
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
