"""STALE -- a THIRD verdict for a bound record, beside PASS and FAIL (Wilson
ruling 10-25, v2 step 2).

A bound record (the harden, CE5, LN1, A2, the phase sweeps, ...) holds the
blob hash of what it ran on. On the v2 branch step 2 moves those inputs ON
PURPOSE, and the record is re-run ONCE at v2's milestone. Until then a red that
everyone has agreed to ignore is how S1g hid for nine days -- so the gate says
STALE, which is NOT a tolerated FAIL:

  STALE  only when BOTH hold: the gate is on DECLARED below (with its reason),
         AND every input that moved since BASELINE is inside CHANGE_SET --
         the files step 2 is DECLARED to touch.
  FAIL   any other moved input (a bench or model file outside the set), any
         other failure, or a gate not on the list.

STALE prints its own pass token ("GATE <name>: STALE (declared: ...)"):
non-blocking on a work branch and LISTED BY NAME (ci/run_gates.sh); with
`--tag` / PE_TAG=1, i.e. at the v2 lock, STALE BLOCKS, as PENDING did for v1.
⛔ AT THE v2 MILESTONE `DECLARED` MUST BE EMPTY: re-run each record, re-bind
it, delete its entry. CHANGE_SET is FROZEN -- a file added to it is a reviewed
edit here, never a glob.

WHAT MOVED is read from git, not from the record (a record holds one SET
hash): every record was green at BASELINE (the v1-lock tag, b019e28), so the
moved inputs are `git diff --name-only BASELINE HEAD -- <inputs>` plus any
uncommitted edit.

⛔⛔ A STALE GATE IS A DEBT (Wilson 11-04): every DECLARED gate has a DEBT
entry -- the item that owns turning it green and the point it must be green
by -- and the STALE reason carries both, so run_gates' STALE line names the
owner. A declared gate with no owner is red (`debt_problems`, priced in
ci/pass_token.py's self-test, which every shard runs first).

MUST-FIRES (planted, through stale_verdict): a moved input OUTSIDE the set ->
FAIL; a gate not declared -> FAIL; inputs that did not move -> PASS; a moved
input inside the set on a declared gate -> STALE; and --tag turns STALE into
a block.
"""
from __future__ import annotations

import fnmatch
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

BASELINE = "v1-lock"

#: gate -> why its record is stale on purpose, and what re-binds it
DECLARED = {
    "model/gate_harden_record.py":
        "the harden of record ran on v1's RTL; v2's RTL is re-hardened at the "
        "v2 milestone (gds) and the record re-bound",
    "model/gate_ce5_freeze.py":
        "CE5 was certified on v1's frozen set; step 2 widens its RTL and "
        "bench, so CE5 is re-certified and FREEZE_BLOBS re-pinned at v2",
    "model/gate_ln1_record.py":
        "the 200k LN1 run read v1's RTL and benches; re-dispatched with "
        "--record on v2 (Wilson: it referees step 2 before merge)",
    "model/gate_a2_record.py":
        "the A2 suite ran on v1's tree; re-run with --record at v2",
    "model/gate_flow_config.py":
        "the timing of record was hardened with v1's flow config; v2 moves it "
        "on purpose (60 MHz, the latch store, T1/T2 -- Wilson 11-03) and the "
        "v2 harden of record re-binds it",
    "model/gate_phase_coverage.py":
        "the I2C and 1-Wire sweep records read v1's RTL and benches; both "
        "sweeps re-run with --record at v2",
    "model/a2/gate_j_program.py":
        "the W sweep record (model/a2/sweep_w.json) ran on v1's RTL and "
        "images; `run_w_sweep.py --full` re-run at v2",
    "model/gate_wire_feed.py":
        "board images are v1-encoded; v2 FPGA build owed (fpga/images stay v1 "
        "until it exists -- no v2 image beside a v1 bitstream; checked through "
        "test/v1_translate.py meanwhile)",
    "model/gate_admissible_images.py":
        "board images are v1-encoded; v2 FPGA build owed (read through "
        "test/v1_translate.py meanwhile -- image_universe.board_as_v2)",
    "model/gate_image_bounds.py":
        "board images are v1-encoded; v2 FPGA build owed (read through "
        "test/v1_translate.py meanwhile -- image_universe.board_as_v2)",
    "model/gate_store_full.py":
        "board images are v1-encoded; v2 FPGA build owed (read through "
        "test/v1_translate.py meanwhile -- image_universe.board_as_v2)",
    "model/a2/gate_a2_program.py":
        "the A2 RE-CERTIFICATION item owns it: the bound tables "
        "(clocked_a2_bounds, lane_response_bounds) are stale for the images the "
        "60 MHz move re-derived, and program_a2 regenerates them with pyRTA "
        "working first (Wilson 11-04); and board images are v1-encoded, v2 FPGA "
        "build owed (program_a2 reads them translated -- image_universe.images_v2)",
    "test/run_uartrx.py":
        "board images are v1-encoded; v2 FPGA build owed (the nostop board "
        "image compared through test/v1_translate.py)",
    "test/run_cktx.py":
        "the pre-#8 silicon arm is v1-era RTL that reads only v1 images; set "
        "aside by name (fix #8 priced on v2 by M_TX_PRELOAD); the v2 lock "
        "rebuilds it on a v1 builder + bench or retires it to the v1 record",
    "ci/ln1_replay.py":
        "LN1's image replays mismatch at row 0 on v2; the replay is reworked "
        "when Lean is updated for the first primitives (Wilson 10-26) -- "
        "diagnosed then, not now",
    "model/gate_onewire_hw_witness.py":
        "needs bench re-witness on v2 bitstream -- the 1-Wire FPGA witness is a "
        "HARDWARE record of the v1 image on a v1 bitstream; v2's image is "
        "translate(v1). At the v2 lock: re-run at the bench, or SCOPE.md says "
        "the board evidence is v1's (Wilson 10-25)",
    "model/gate_i2c_hw_witness.py":
        "needs bench re-witness on v2 bitstream -- the I2C FRAM witness ran a "
        "bitstream built from v1's RTL. At the v2 lock: re-run at the bench, or "
        "SCOPE.md says the board evidence is v1's (Wilson 10-25)",
}

#: gate -> (the item that owns turning it green, the point it must be green
#: by). Wilson 11-04: a STALE gate is a debt, and a debt has an owner. Keys
#: must equal DECLARED's (`debt_problems`).
_V2_LOCK = "the v2 lock (PE_TAG=1, where STALE blocks)"
DEBT = {
    "model/gate_harden_record.py": ("the v2 harden of record (gds)", _V2_LOCK),
    "model/gate_ce5_freeze.py": ("CE5 re-certification at v2", _V2_LOCK),
    "model/gate_ln1_record.py": ("the LN1 --record re-run on v2", "before step 2 merges"),
    "model/gate_a2_record.py": ("the A2 re-certification", "before the entry is final"),
    "model/gate_flow_config.py": ("the v2 harden of record", _V2_LOCK),
    "model/gate_phase_coverage.py": ("the I2C + 1-Wire sweep --record re-runs", _V2_LOCK),
    "model/a2/gate_j_program.py": ("run_w_sweep.py --full at v2", _V2_LOCK),
    "model/gate_wire_feed.py": ("the v2 FPGA build", _V2_LOCK),
    "model/gate_admissible_images.py": ("the v2 FPGA build", _V2_LOCK),
    "model/gate_image_bounds.py": ("the v2 FPGA build", _V2_LOCK),
    "model/gate_store_full.py": ("the v2 FPGA build", _V2_LOCK),
    "model/a2/gate_a2_program.py": ("the A2 re-certification (pyRTA working first)",
                                    "before the entry is final"),
    "test/run_uartrx.py": ("the v2 FPGA build", _V2_LOCK),
    "test/run_cktx.py": ("the v2 lock's cktx rebuild or retirement", _V2_LOCK),
    "ci/ln1_replay.py": ("the Lean update for the first primitives", _V2_LOCK),
    "model/gate_onewire_hw_witness.py": ("the bench re-witness on the v2 bitstream",
                                         _V2_LOCK),
    "model/gate_i2c_hw_witness.py": ("the bench re-witness on the v2 bitstream",
                                     _V2_LOCK),
}


def debt_problems(declared=None, debt=None):
    """[problem]: a DECLARED gate with no owner, or an owner for no gate."""
    declared = DECLARED if declared is None else declared
    debt = DEBT if debt is None else debt
    out = ["%s is DECLARED stale with no owning item (DEBT)" % g
           for g in sorted(set(declared) - set(debt))]
    out += ["DEBT names %s, which is not DECLARED stale" % g
            for g in sorted(set(debt) - set(declared))]
    out += ["DEBT for %s has an empty owner or green-by point" % g
            for g, v in sorted(debt.items()) if not (v and v[0] and v[1])]
    return out


#: FROZEN: the files step 2 is declared to touch (git diff v1-lock..HEAD at
#: the time this list was written, reviewed). Never a glob.
CHANGE_SET = frozenset([
    "docs/PORT_SPEC.md",
    "model/a2/gate_j_program.py",
    "model/a2/program_a2.py",
    "model/count_ranges.py",
    "model/gate_a2_record.py",
    "model/gate_ce5_freeze.py",
    "model/gate_degenerate_fields.py",
    "model/gate_harden_record.py",
    "model/gate_hold_offset.py",
    "model/gate_ln1_record.py",
    "model/gate_mutant_arms.py",
    "model/gate_mutant_kills.py",
    "model/gate_one_encoder.py",
    "model/gate_onewire_hw_witness.py",
    "model/gate_phase_coverage.py",
    "model/gate_sda_hold.py",
    "model/gate_store_full.py",
    "model/pe_asm.py",
    "model/stale_records.py",
    "model/v3_table.py",
    "src/pe_engine.v",
    "src/pe_store.v",
    "src/project.v",
    "test/armnone_image.hex",
    "test/artefacts.sha256",
    "test/b3b_a3_image.hex",
    "test/b3b_a_image.hex",
    "test/b3b_b_image.hex",
    "test/b3b_bnoi2c_image.hex",
    "test/cfgerr_image.hex",
    "test/ckdegen2_image.hex",
    "test/ckdegen_image.hex",
    "test/ckdense_image.hex",
    "test/ckfive_image.hex",
    "test/ckheavy_image.hex",
    "test/ckhold_at_image.hex",
    "test/ckhold_over_image.hex",
    "test/ckhold_under_image.hex",
    "test/ckod_image.hex",
    "test/ckread_image.hex",
    "test/clocked_conform.vh",
    "test/corpus.py",
    "test/corpus_all5.hex",
    "test/corpus_i2c.hex",
    "test/corpus_spim.hex",
    "test/corpus_spim25.hex",
    "test/corpus_sptgt.hex",
    "test/corpus_uartrx.hex",
    "test/gate_corpus_trace.py",
    "test/half_image.hex",
    "test/i2caddr_image.hex",
    "test/i2cframe_image.hex",
    "test/make_smoke_image.py",
    "test/measure_a2_widest.py",
    "test/onewire_fpga_image.hex",
    "test/onewire_image.hex",
    "test/pe_isa.py",
    "test/pinnone_image.hex",
    "test/race_remeasure.py",
    "test/run_ckack.py",
    "test/run_cktx.py",
    "test/run_mutants.py",
    "test/run_onewire.py",
    "test/run_recert.py",
    "test/run_reload.py",
    "test/run_spim_witness.py",
    "test/run_spitgt.py",
    "test/run_uartrx.py",
    "test/run_uarttx.py",
    "test/run_v2window.py",
    "test/run_wirefeed_mf.py",
    "test/rxfast_image.hex",
    "test/smoke_image.hex",
    "test/sptgt_m0_image.hex",
    "test/sptgt_m1_image.hex",
    "test/sptgt_m2_image.hex",
    "test/sptgt_m3_image.hex",
    "test/sptgt_mosi_image.hex",
    "test/store_filler.vh",
    "test/store_probe.py",
    "test/tb_ckack.v",
    "test/tb_cktx.v",
    "test/tb_csat.v",
    "test/tb_edge.v",
    "test/tb_fifo.v",
    "test/tb_half.v",
    "test/tb_i2c.v",
    "test/tb_jlane.v",
    "test/tb_lock.v",
    "test/tb_onewire.v",
    "test/tb_pinrange.v",
    "test/tb_reload.v",
    "test/tb_rxbw.v",
    "test/tb_smoke.v",
    "test/tb_spitgt.v",
    "test/tb_status.v",
    "test/tb_trace.v",
    "test/tb_tx.v",
    "test/tb_uartrx.v",
    "test/tb_uarttx.v",
    "test/tb_v2win.v",
    "test/tb_w.v",
    "test/tb_witness.v",
    "test/test.py",
    "test/tx_badclk_image.hex",
    "test/tx_image.hex",
    "test/uart_rx_image.hex",
    "test/uart_tx_busy_image.hex",
    "test/uart_tx_image.hex",
    "test/v1_translate.py",
    "test/v3_table.vh",
    "test/ws2812_sub3_rearm21.hex",
    # ---- AMENDMENT 1 (10-25, Nate go): files step 2's own later commits
    # touched, caught by this guard (phase_coverage / a2_record went FAIL).
    # Reviewed, one by one, never a glob:
    "test/runstart.vh",              # fe0eeb5: engine-started guard (Wilson R3), NEW
    "test/progress.vh",              # fe0eeb5: includes runstart.vh
    "test/inv_cdc.vh",               # fe0eeb5: CS falls while the engine ran
    "model/gate_wire_feed.py",       # 8a666fd: board images read through v1_translate
    "ci/pass_token.py",              # d189e97: the STALE verdict accepted, named
    "ci/run_gates.sh",               # d189e97: STALE listed in the verdict line
    "model/gate_i2c_hw_witness.py",  # d189e97: board witness as v1 evidence
    # ---- AMENDMENT 2 (10-25, Nate go, item 4): the 9 fast-shard reds fixed.
    "model/gate_admissible_images.py", # board images read translated (STALE)
    "model/gate_image_bounds.py",      # board images read translated (STALE)
    "model/image_universe.py",         # board_as_v2 / board_stale_verdict, the ONE helper
    "model/gate_i2c_order.py",         # its plant through pe_isa.join_image
    "model/gate_pin_matrix.py",        # its plant through pe_isa.join_image
    "model/gate_reset_audit.py",       # allowlist: u_store.g_bank 4096, s_wrdata 26
    "model/gate_stored_numbers.py",    # 3 new tables classified as specifications
    "test/param_dump.v",               # prints ACT_BASE, MAGIC_AT, ACT_BYTES_T, WIDE_B
    # ---- AMENDMENT 3 (10-25, Nate go, item 5): the equivalence gate.
    "model/gate_v2_equiv.py",          # NEW: v1 == v2 at the derived offset
    "test/tb_equiv.v",                 # NEW: its bench, built against both RTLs
    "test/sim_run.py",                 # its scratch generator registered
    "test/benchset.py",                # tb_equiv.v excluded from the sweep, with why
    "ci/shards.txt",                   # the gate in shard sim2
    "ci/gate_tokens.txt",              # its pass token
    "model/gate_meta.py",              # its seam (same -> always True)
    # ---- AMENDMENT 4 (10-26, Nate go): the first-CI reds on v2-main.
    "ci/ln1_replay.py",                # image-replay rows -> declared STALE
    "model/a2/gate_a2_program.py",     # board images translated (STALE)
    "model/phase_coverage.py",         # the tb_equiv row
    "test/lockstep_golden.json",       # re-pinned on v2 (proof: gate_v2_equiv)
    "test/phases_run.sh",              # store size from pe_isa, not 256
    "test/store_run.sh",               # store size from pe_isa, not 256
    # ---- AMENDMENT 5 (10-26, Nate go): the second CI run's reds.
    ".github/workflows/test.yaml",     # ln1 job: full history for the STALE check
    "test/gate_coverage.py",           # 13 anchors re-anchored by their text
    # ---- AMENDMENT 6 (10-26, Wilson: reserved opcodes refused at load).
    "test/coverage_sweep.sh",          # --coverage-max-width 512 (l_act measured whole)
    # ---- AMENDMENT 7 (10-27, Nate go: primitive 1, BRANCH_BIT, Wilson R2c).
    "test/branch_check.vh",            # NEW: tb_equiv +BRCHECK, the PC / head / stall checks
    "test/branch_corpus.py",           # NEW: the branch images, chain + runtime refusals
    "test/run_branch_check.py",        # NEW: the gate, the six M_BR_* must-fires' killer
    "model/a2/pyrta_src.py",           # no fallback clone search: PYRTA_SRC or nothing (Nate 10-27)
    # ---- AMENDMENT 8 (11-03, Wilson: the clock bundle, retargetable). One
    # clock source (model/clock.py, info.yaml / fpga/board.yaml); every typed
    # 50 MHz in a record's inputs reads it. Commit (a) is byte-identical at
    # 50 MHz (band off); the records re-run once after the 60 MHz move.
    "model/clock.py",                  # NEW: the clock source
    "model/gate_clock_consistency.py", # NEW: the copies agree, counts meet spec
    "model/gate_clock_literals.py",    # NEW: no typed clock returns
    "test/pe_clock.vh",                # NEW: generated bench clock (chip)
    "fpga/board.yaml",                 # NEW: the FPGA board's clock
    "fpga/sim/fpga_clock.vh",          # NEW: generated bench clock (fpga)
    "model/hold_bound.py",             # reads CLK_PERIOD_PS + the band
    "model/a2/gate_um10204.py",        # mode floors via clock; maxima rounded down
    "model/pe_proto.py",               # t_ext / OneWire read the target clock
    "model/macro_harden_gate.py",      # docstring: CLOCK_PERIOD is held, not typed
    "model/a2/a2_close.py",            # F_CLK = clock.hz()
    "model/a2/bursty.py",              # F_CLK = clock.hz()
    "model/a2/gate_admissibility_1_6.py",  # rx cap / us prints via clock
    "model/a2/gate_clocked_lane_a2.py",    # F_CLK = clock.hz()
    "model/a2/gate_descriptor_1_5.py",     # SLOW_PERIOD_NS marked a v1 RECORD
    "model/a2/gate_differential.py",       # F_CLK = clock.hz()
    "model/a2/gate_i2c_phase.py",          # Table 11 in ns, cycles via clock
    "model/a2/gate_microarch_1_3.py",      # SLOW_PERIOD_NS marked a v1 RECORD
    "model/a2/gate_miso_tristate.py",      # HZ = clock.hz()
    "model/a2/gate_pin_subsets.py",        # agg / clock.hz()
    "model/a2/gate_reactive_2mhz.py",      # F_CLK = clock.hz()
    "model/a2/gate_rearm.py",              # F_CLK, us prints via clock
    "model/a2/grid_quantization.py",       # F_CLK = clock.hz()
    "model/a2/task_model.py",              # F_CLK = clock.hz()
    "model/ta01/uart_ta.py",               # F_CLK = clock.hz()
    "model/ta01b/uart_stream.py",          # F_CLK = clock.hz()
    "model/ta02/gate0_spi.py",             # F_CLK = clock.hz()
    "model/ta02/gate_pwm.py",              # F_CLK = clock.hz()
    "model/ta02/probe_band_edge.py",       # baud via clock.hz()
    "test/run_i2c.py",                     # F_CLK = clock.hz()
    "test/run_rxbw.py",                    # rx cap via clock.hz()
    "test/tb_pit.v",                       # bench clock from pe_clock.vh
    "test/tb_store_latch.v",               # clock-ok: cycle-only unit bench
    "test/tb_verdict.v",                   # bench clock from pe_clock.vh
    "fpga/pa100t/build.tcl",               # passes board.yaml clock_hz as CLK_HZ
    "fpga/pa100t/pa100t_top.v",            # CLK_HZ through to the core
    "fpga/rtl/pe_fpga_core.v",             # UART/break/deglitch + chip period from CLK_HZ
    "fpga/sim/run_fpga_onewire.py",        # us prints at the board clock
    "fpga/sim/tb_fpga_i2c.v",              # board clock from fpga_clock.vh
    "fpga/sim/tb_fpga_loader.v",           # board clock from fpga_clock.vh
    "fpga/sim/tb_fpga_onewire.v",          # board clock from fpga_clock.vh
    "fpga/sim/tb_fpga_uart.v",             # board clock from fpga_clock.vh
    # ---- AMENDMENT 9 (11-03, Wilson: clock (b), the 60 MHz move). The band
    # on, info.yaml / config.json / RTL to 60 MHz together, the programs in
    # real time, the A2 layer a RECORD at 50 MHz, the cross-clock gate.
    "info.yaml",                           # clock_hz 60000000
    "src/config.json",                     # CLOCK_PERIOD 16.667
    "README.md",                           # the UART-rx paragraph at 60 MHz
    "fpga/sim/i2c_fram.py",                # the board program rebuilt as witnessed (band 1)
    "model/a2/gate_dmin_clocked.py",       # mode floors at the A2 RECORD clock
    "model/gate_clock_cross.py",           # NEW: the same programs at both clocks
    "test/tb_xclock.v",                    # NEW: its bench
    "test/sweep_onewire_phase.py",         # per-arm phase plan (17 / 20)
    "test/uart_rx.py",                     # T_NOMINAL = 115200 at the target
    "test/uart_tx.py",                     # T_NOMINAL = 115200 at the target
    # ---- AMENDMENT 10 (11-03, Wilson: clock (c), proofs + docs).
    "lean/JLane/JLane/Hold.lean",          # holdCycles_meets: every period; SDA_HS 23
    "lean/JLane/JLane/HoldGate.lean",      # SDA_HS computed; d >= SDA_HS + 16 = 39
    "docs/HOST_INTERFACE.md",              # the clock note: cycles hold, ns are 50 MHz
    "docs/SCOPE.md",                       # v1 scope at 50 MHz, pointer to v2's clock
    # ---- AMENDMENT 11 (11-03, Wilson: the config + bindings commit, A1/B1).
    "src/pe_cells_ihp.v",                  # the IHP stock-cell bindings, now the tapeout's
    "test/gate_store_latch.py",            # the bound store on the PDK's models + polarity
    "test/run_pit_capture.py",             # one PIT case, bound == generic
    "test/rtl_lint.sh",                    # the bound lint (3rd argument: the models)
    "model/gate_rtl_lint.py",              # Verilator on the bound store
    "model/gate_slang_lint.py",            # slang on the bound store
    "model/gate_canary_check.py",          # NEW: B1, the canary builder + refusal
    "ci/make_canary.py",                   # NEW: a canary = work commit + density
    "ci/pdk.sha",                          # NEW: the pinned PDK commit, one place
    "model/nonadmissible.py",              # ckhold_over admissible at 60 MHz (r 16 <= 20)
    ".github/workflows/v2_canary.yaml",    # B1 check step; PDK_SHA from ci/pdk.sha
])


def _git(args):
    r = subprocess.run(["git"] + args, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, r.stdout


def moved(inputs, base=BASELINE):
    """[path] among `inputs` that differ from `base` (committed or not)."""
    rc, out = _git(["diff", "--name-only", base, "--"] + sorted(inputs))
    rc2, out2 = _git(["ls-files", "--others", "--exclude-standard", "--"] + sorted(inputs))
    if rc != 0:
        return ["<git diff against %s failed>" % base]
    return sorted(set(l for l in (out + out2).splitlines() if l.strip()))


def stale_verdict(gate, moved_inputs, tag=None, declared=None, change_set=None):
    """-> ("PASS" | "STALE" | "FAIL", why). The gates and the must-fires both
    call this. `tag` defaults to PE_TAG=1 or `--tag` on the command line."""
    declared = DECLARED if declared is None else declared
    change_set = CHANGE_SET if change_set is None else change_set
    if tag is None:
        tag = os.environ.get("PE_TAG") == "1" or "--tag" in sys.argv
    if not moved_inputs:
        return "PASS", "no input moved since %s" % BASELINE
    if gate not in declared:
        return "FAIL", "inputs moved (%s) and %s is not a DECLARED stale record" % (
            ", ".join(moved_inputs[:4]), gate)
    outside = [p for p in moved_inputs if p not in change_set]
    if outside:
        return "FAIL", ("input(s) OUTSIDE step 2's declared change set moved: %s "
                        "-- a real change, not the declared staleness"
                        % ", ".join(outside[:4]))
    if tag:
        return "FAIL", "STALE blocks at the tag (%s)" % declared[gate]
    owner, by = DEBT.get(gate, ("NO OWNER", "-"))
    return "STALE", "%s [owner: %s; green by: %s]" % (declared[gate], owner, by)


def token(name, why):
    return "  GATE %s: STALE (declared: %s)" % (name, why)


def self_test():
    ok = True
    d = {"g.py": "a reason"}
    cs = frozenset(["src/pe_engine.v"])
    for what, args, want in (
            ("a moved input OUTSIDE the set", ("g.py", ["test/tb_x.v"]), "FAIL"),
            ("a gate not declared", ("other.py", ["src/pe_engine.v"]), "FAIL"),
            ("nothing moved", ("g.py", []), "PASS"),
            ("inside the set, declared", ("g.py", ["src/pe_engine.v"]), "STALE")):
        got = stale_verdict(*args, tag=False, declared=d, change_set=cs)[0]
        print("    %-40s %s" % (what, "ok (%s)" % got if got == want else "*** got %s" % got))
        ok = ok and got == want
    got = stale_verdict("g.py", ["src/pe_engine.v"], tag=True, declared=d, change_set=cs)[0]
    print("    %-40s %s" % ("--tag turns STALE into a block", "ok (FAIL)" if got == "FAIL" else "*** " + got))
    return ok and got == "FAIL"


if __name__ == "__main__":
    print("STALE RECORDS -- %d declared, change set %d files, baseline %s"
          % (len(DECLARED), len(CHANGE_SET), BASELINE))
    sys.exit(0 if self_test() else 1)
