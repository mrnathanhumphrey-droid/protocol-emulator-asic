"""THE BENCH SET -- one declaration of how every Verilog bench is built and run.

⛔⛔ WHY THIS EXISTS. The coverage sweep has to build and run every bench, and
the invocations were scattered across eight scripts (`run_csat.py`,
`run_dstar_check.py`, `run_rxbw.py`, `run_i2c.py`, `clean_room.py`,
`gate_corpus_trace.py`, `price_j_sweep.sh`, the cocotb Makefile). A sweep that
re-typed them would be a NINTH copy, and the lesson already paid for here is
that two lists drift -- "all 8 CI gates green" was reported from a loop pasted
in two places while CI went red.

⇒ So the sweep reads THIS, and this file is guarded against drift in the only
way that holds: it ENUMERATES `test/tb*.v` from disk and refuses to run if a
bench exists that nobody has classified. A bench may be IN the sweep or
EXCLUDED WITH A REASON; it may not be silently absent. ⛔ That is Wilson's
ruling 3 applied to the bench set itself -- "must-fires over small parameter
spaces enumerate; they don't use hand-picked lists."

⚠ WHAT A CONFIG HERE IS AND IS NOT. It is the arm set the COVERAGE sweep runs,
chosen to execute as much RTL as the tracked artefacts allow. It is NOT the
gate's own arm set: `run_csat.py` sweeps four release vectors and
`gate_corpus_trace.py` three phases because their CLAIMS need that, and those
claims stay with those gates. Coverage asks only "did this line ever execute",
so one representative arm per distinct path is the right shape -- and anything
still uncovered becomes a waiver with a written reason, not a silent zero.
"""

from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

ENGINE = ["src/pe_engine.v", "src/pe_store.v", "src/project.v"]

# ---------------------------------------------------------------------------
# EXCLUSIONS, each with the reason it is not a self-checking Verilog bench.
# ⛔ An exclusion is a DECLARATION, checked below against what is on disk.
# ---------------------------------------------------------------------------
EXCLUDED = {
    "tb.v": (
        "THE COCOTB TOPLEVEL. It has no self-checking `initial` block at all -- "
        "`test/test.py` drives it from Python, so there is no PASS line for a "
        "Verilator `--binary` run to read. ⭐ Its coverage is not lost: the "
        "cocotb suite exercises `project.v` and `pe_engine.v` through the same "
        "ports, and the RTL coverage of those paths is attributed to the "
        "benches that do self-check. ⚠ What IS unmeasured here is `tb.v`'s own "
        "two lines and the cocotb-only host pacing."),
}

# ---------------------------------------------------------------------------
# THE ARMS. (label, extra plusargs) per bench. `$IMG` entries get their
# `+NBYTES` computed from the file, because an image that never loaded emits
# nothing and "no bytes" reads as a queue fault rather than a missing file.
# ---------------------------------------------------------------------------
#: benches whose `+NBYTES` must be supplied (they refuse to start without it)
#: ⛔⛔ ARMS THAT MUST COME OUT **RED**, declared by name. The sweep's per-arm
#: verdict is a checker, and it was SILENTLY BROKEN for as long as the
#: watchdogs existed: the grep wanted `*** FAIL` while they printed a bare
#: `FAIL`, and the log was cut at the first `$finish` while they report from
#: `final` blocks. "The sweep catches it" was false twice over, and fixing it
#: immediately turned four arms red.
#: ⇒ `tb_verdict` prints a watchdog-shaped failure from a `final` block and
#:   nothing else. Requiring it to be RED prices the log cut and the grep
#:   pattern TOGETHER and permanently: if either regresses, this arm starts
#:   passing and the sweep fails on it. A checker that has stopped checking
#:   announces itself no other way.
XFAIL = {("tb_verdict", "pipeline")}

NEEDS_NBYTES = {"tb_tx", "tb_half", "tb_i2c", "tb_csat", "tb_jlane", "tb_status",
                "tb_fifo", "tb_lock", "tb_w", "tb_ckack", "tb_cktx",
                "tb_rxbw", "tb_trace", "tb_witness", "tb_pinrange"}

#: ⛔⛔ PLUSARGS READ BY A **SHARED INCLUDE**, with their default declared ONCE.
#: `test/clocked_conform.vh` is included by thirteen benches, so a plusarg read
#: there is read by all thirteen -- and the rule above says a bench running on
#: an undeclared default is a different run from the one the gates certify. The
#: alternative is repeating `+A2BOUND=0` on 36 arms, which states the condition
#: 36 times and lets 35 of them drift.
#: ⇒ The DEFAULT is the declaration, and it lives here with its reason. Any
#:   bench whose own arm supplies the plusarg overrides it, which is exactly
#:   what `ckod` does with `+A2BOUND=1`.
#: ⚠ WHY THIS TABLE EXISTS AT ALL -- IT IS A FINDING, NOT HOUSEKEEPING. The
#: scanner's pattern was `[A-Z_]+`, which cannot match a name containing a
#: DIGIT, so `A2BOUND` was invisible to it for a whole arc while `CKRUNS` was
#: caught in one run. Widening the pattern turned up twelve benches that had
#: been running on an undeclared default the whole time. A guard that cannot
#: see part of its subject passes about the part it can.
SHARED_INCLUDE_DEFAULTS = {
    # ⛔⛔ R's BOUND IS ENFORCED BY DEFAULT, unlike A2's. The whole finding of
    # ruling R is that the tree was green on the port premise because NOTHING
    # CHECKED IT, so a layer defaulting to report-only would rebuild the hole.
    # The default is the design's own `SPL` (the buffer depth) and is
    # DERIVED then CHECKED: at most one fill per slot. Worst 1 on the single-lane
    # images (ckod 184 actions, corpus_i2c 72), 2 on corpus_all5 (five live lanes,
    # so the spare fill lands inside a clocked window), 16-17 under
    # `M_CK_HOLD_INVAL`.
    # ⇒ `+RBOUND` exists to RAISE it for a lane set that legitimately needs
    #   more, and no shipped arm passes it.
    "RBOUND": ("test/clocked_conform.vh", "dut.u_eng.SPL (2 at the shipped depth), ENFORCED",
               "refills per retired clocked action. Amendment A1 says a HELD "
               "clocked dispatch owes no refill, and D* plus every "
               "port-feasibility cell in Theorem 3 assume it. This is the only "
               "layer that sees `M_CK_HOLD_INVAL`, which survives A1 (the PC "
               "does not advance, so the refill restores an identical word) "
               "and B (a refill changes no dispatch count)."),
    # ⛔⛔ `+A2BOUND` IS RETIRED (ruling S). It switched one shared constant on
    # for one arm; the bound is now a per-lane vector GENERATED per arm, so
    # the default below is what an arm gets only when its image has NO
    # clocked open-drain lane -- in which case the A2 layer has nothing to
    # bound and reports NOT EXERCISED.
    "A2SLACK": ("test/clocked_conform.vh", "absent (no clocked OD lane)",
                "A2's per-lane post-HIGH budget, `L_SYNC + 1 + (r_i - C)` with "
                "r_i from pyRTA over the PROGRAM's OWN lane set "
                "(`model/a2/program_a2.py` -> `test/clocked_a2_bounds.json`). "
                "Supplied by the planning loop for EVERY arm whose image has a "
                "clocked open-drain lane, so it is never hand-typed and never "
                "omitted; -1 in a field means that lane's set is overloaded "
                "and has no finite bound."),
}

#: ⛔⛔ RULING CI3's MUST-FIRE: an `+IMG` path LONGER THAN 128 BYTES, on a real
#: arm. `tb_trace`'s 64-byte name buffer truncated CI's 99-byte checkout path
#: and the simulation exited 0 having written nothing -- five commits red in
#: CI, green here, where the path was 59 bytes. Every bench now has a 256-byte
#: buffer and `test/imgload.vh` fails loudly on an image that did not load.
#: This arm is what makes that more than a claim: it runs `tb_tx`'s `clean`
#: arm unchanged except for the path, so it must produce the SAME passing
#: assertions -- proof the image LOADED through a long name, not merely that
#: nothing complained.
#: ⚠ RELATIVE, because the sweep runs from the repo root and so does CI; the
#: directory is a `probe_*` name (gitignored) generated by `plan()`, so a clean
#: checkout has it too.
LONGPATH_DIR = "probe_longpath/" + ("a_directory_name_long_enough_to_push_the_"
                                    "image_path_well_past_one_hundred_and_"
                                    "twenty_eight_bytes_for_ruling_ci3")
LONGPATH_IMG = LONGPATH_DIR + "/tx_image.hex"
assert len(LONGPATH_IMG) > 128, len(LONGPATH_IMG)


def ensure_longpath_image():
    """Copy `test/tx_image.hex` to the long path, byte for byte."""
    src = os.path.join(ROOT, "test", "tx_image.hex")
    dst = os.path.join(ROOT, LONGPATH_IMG)
    with open(src, "rb") as fh:
        data = fh.read()
    if os.path.isfile(dst):
        with open(dst, "rb") as fh:
            if fh.read() == data:
                return
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "wb") as fh:
        fh.write(data)


CONFIG = {
    # ⭐⭐ THE SPL = 1 ARM IS HERE BECAUSE COVERAGE ASKED FOR IT. The sweep's
    # first run left `pe_engine.v:867 else if (SPL == 1)` and the two
    # `if (SPL > 1)` slot-flip arms (1580, 1588) at ZERO -- not because nothing
    # tests the single-buffer engine, but because the sweep only ever BUILT
    # SPL = 2. `run_param_points.py` has been running both depths all along;
    # the measurement simply could not see it.
    # ⛔ ONLY `tb_smoke` TAKES THIS ARM, and the reason is in
    # `run_param_points.py`'s own expectation map: `tb_edge` at SPL = 1 FAILS
    # must-fire 5b by design (a programmed delay shorter than the refill
    # latency does not reach the pin at single-buffer depth). That is a
    # recorded design consequence, so an SPL = 1 arm there would be an
    # expected-fail arm, and the per-bench SPL matrix stays with the sweep that
    # already declares those expectations.
    # ⛔⛔ THE PLUSARGS ARE THE BENCH'S OWN DEFAULTS, SPELLED OUT, AND THE
    # FIRST DRAFT INVENTED `+NCYC=200000` INSTEAD -- which CLOBBERED the
    # tracked `test/cj_measured.txt`. `tb_smoke` writes that artefact to a
    # hardcoded path whenever the image and depth are canonical, and the
    # pinned numbers were measured at the DEFAULT budget: jobs came back
    # 344 -> 17642, cycles 4000 -> 200000. ⇒ Reuse the certified invocation,
    # do not improvise one. The values are written out rather than left to
    # defaults so the drift guard can see them and so a change to a default
    # cannot silently change what the sweep measured.
    "tb_smoke": {
        "srcs": [],
        "arms": [("default", ["+IMG=test/smoke_image.hex", "+NCYC=4000",
                              "+WARMUP=200"]),
                 ("spl1", ["+IMG=test/smoke_image.hex", "+NCYC=4000",
                           "+WARMUP=200"], {"SPL_CFG": 1})],
    },
    # ⛔ ONE ARM, AND THE OTHER TWO IMAGES ARE NOT MISSING FROM IT. `tb_edge`
    # `$readmemh`s `edge_image_noto.hex` and `edge_image_rise.hex` ITSELF, at
    # lines 236 and 291, reloading the store mid-run for must-fires 2 and 4.
    # ⚠ The sweep's first draft gave each image its own arm, and the rise arm
    # FAILED must-fire 1 -- correctly: that program produces no output edge
    # after the peer edge, so the claim "`t_out - t_edge` is phase-invariant"
    # has nothing to measure. Feeding a bench an image it loads for itself
    # measures a run nobody certifies, and reports the mismatch as a defect.
    "tb_edge": {
        "srcs": [],
        "arms": [("default", ["+IMG=test/edge_image.hex"])],
    },
    # ⛔ THE BADCLK ARM IS NOT OPTIONAL. `tx_badclk_image.hex` is the program
    # that aliases a SHIFT lane's clock pin onto its data pin, and the refusal
    # path (`config_err` sticky + lane halt) exists ONLY for it. Without this
    # arm the entire 1.6s silicon backstop reads as uncovered.
    "tb_tx": {
        "srcs": [],
        "arms": [("clean", ["+IMG=test/tx_image.hex", "+NCYC=6000"]),
                 # ⭐ CI3's must-fire: the SAME arm through a >128-byte path.
                 ("longpath", ["+IMG=" + LONGPATH_IMG, "+NCYC=6000"]),
                 ("badclk", ["+IMG=test/tx_badclk_image.hex", "+NCYC=6000",
                             "+BADCLK=1"])],
    },
    # ⭐⭐ THE SAME-CYCLE PUSH AND POP ON ONE TX QUEUE, directed. The coverage
    # sweep reported `src/project.v`'s `do_push && do_pop && q_sel == tx_tag`
    # arm UNCOVERED and it was tabled as OWED -- then the cocotb cross-check
    # reported it EXECUTED 48 times. The swept benches could not reach it, so
    # "owed" described a gap in ONE BENCH as a gap in the DESIGN.
    # ⛔ THE PHASE IS WALKED, NOT COMPUTED: `do_push` is the LOW-nibble push
    # after a three-stage synchroniser and `do_pop` is a byte-load pulse from a
    # lane's own cadence, so computing the alignment means composing three
    # latencies and being off by one looks exactly like the corner being
    # unreachable. The bench slips the push phase a cycle per byte and asserts
    # when the coincidence happens -- it reports the phase it found (191), and
    # NEVER seeing it is a FAILURE rather than a pass.
    # ⛔ THE VERDICT PIPELINE ITSELF, declared XFAIL. It instantiates no DUT:
    # the subject is the harness, not the design.
    "tb_verdict": {
        "srcs": [],
        "arms": [("pipeline", ["+NCYC=100"])],
    },
    "tb_fifo": {
        "srcs": [],
        "arms": [("pushpop", ["+IMG=test/tx_image.hex", "+NCYC=60000"])],
    },
    "tb_half": {
        "srcs": [],
        "arms": [("default", ["+IMG=test/half_image.hex", "+NCYC=40000"])],
    },
    # ⭐ RULING TF4's schedule freeze. Its verdict lives in
    # `test/run_lockstep.py`, which compares the printed stream with the
    # pre-fix RTL's digests on 12 images; this arm runs it once on the A2
    # subject so the bench is swept, linted and counted like every other.
    "tb_lock": {
        "srcs": [],
        "arms": [("ckheavy", ["+IMG=test/ckheavy_image.hex", "+NCYC=20000"])],
    },
    # ⭐ RULING W -- Theorem 3 on the bench. Its verdicts live in
    # `test/run_w_sweep.py` (live subset in CI, full sweep -> the record
    # `gate_j_program` checks); this arm runs it once on the A2 subject so the
    # bench is swept, linted and counted like every other.
    "tb_w": {
        "srcs": [],
        "arms": [("ckheavy", ["+IMG=test/ckheavy_image.hex", "+NCYC=20000",
                              "+WARMUP=2000"])],
    },
    # ⭐ RULING TX4 -- clocked transmit values over widths 1..8, MSB/LSB, ACK
    # or not, empty/refill. Verdicts in `test/run_cktx.py` (CI); this arm
    # runs it once fed, on an image that exists on disk, so it is swept.
    "tb_cktx": {
        "srcs": [],
        "arms": [("ckfive", ["+IMG=test/ckfive_image.hex", "+NCYC=20000",
                             "+STARVE=0", "+STARVE_LEN=0"])],
    },
    # ⭐ RULING ACK (b)-(c) -- the clocked I2C read against a stretching peer.
    # Its verdicts (chip bytes == sigrok bytes) live in `test/run_ckack.py`,
    # which is local (sigrok); this arm runs the bench in the sweep so it is
    # linted and counted and Layer V sees it.
    # ⭐ `+DEVW=A1` MAKES `ckread_image`'s FIRST BYTE A READ ADDRESS. ⚠ It was
    # 85 while `ckread`'s lane was LSB-first (85 went out as A1); ruling RC
    # made the lane MSB-first, as I2C requires, so A1 now goes out as A1 --
    # and the 85 workaround silently lost the read path from the sweep
    # (measured: nine fram_i2c points went dark until this changed). So the peer's read
    # path (R/W = 1, the data presentation, the second-byte reload, the
    # master's NACK) runs in the swept set, and `LATE` runs the
    # late-data stretch -- the peer code ruling ACK added, covered here
    # rather than only by the local sigrok gate.
    "tb_ckack": {
        "srcs": ["test/fram_i2c.v"],
        "arms": [("ckread_late", ["+IMG=test/ckread_image.hex",
                                  "+NCYC=40000",
                                  "+DUMP=probe_ckack_sweep.bin", "+DEVW=A1",
                                  "+DEVR=A1"],
                  # LATE_SKIP: the first 4 read bits at the fall, the rest
                  # late -- both arms of the peer's presentation choice
                  {"LATE": 300, "LATE_SKIP": 4})],
    },
    # ⭐⭐ THE TWO HOST STATUS BITS, ACTUALLY SET (Wilson's ruling (a) item 1).
    # The coverage sweep found that `lane_underrun` (pe_engine.v:1627) and
    # `tx_full_sticky` (project.v:412) had never been SET by any test -- both
    # were asserted CLEAR as preconditions everywhere, so every run proved only
    # that they do not fire spuriously. The two claims need opposite setups, so
    # the bench carries two modes.
    "tb_status": {
        "srcs": [],
        "arms": [("starve", ["+IMG=test/tx_image.hex", "+NCYC=20000",
                             "+MODE=0"]),
                 ("overrun", ["+IMG=test/tx_image.hex", "+NCYC=20000",
                              "+MODE=1"])],
    },
    # ⭐⭐ PINS OUTSIDE THE REAL RANGE (ruling (a) item 1). `PINW = 4` addresses
    # 0..15 while `N_PINS = 12`, and the two out-of-range cases are different:
    # an OPEN-DRAIN lane on a `uo_out` pin must be REFUSED (1143/1145), while
    # the RESERVED index PIN_NONE = 15 is LEGAL and must simply drive nothing
    # (1158, 1352, 1446).
    # ⛔ THE `refuse` ARM IS ALSO A SWEEP-BLIND-SPOT FIX, and a correction:
    # `cfgerr_image.hex` has been run by the cocotb suite all along, but `tb.v`
    # is the one bench this file excludes, so 1143/1145 read as "never tested".
    # A sweep with a blind spot keeps manufacturing false gaps.
    "tb_pinrange": {
        "srcs": [],
        "arms": [("refuse", ["+IMG=test/cfgerr_image.hex", "+NCYC=8000",
                             "+MODE=0"]),
                 ("reserved", ["+IMG=test/pinnone_image.hex", "+NCYC=8000",
                               "+MODE=1"]),
                 # ⭐ THE THIRD SITE IN THE FAMILY: an `OP_ARM` on the reserved
                 # index put X into `arm_hit` for every armed cycle. The arm
                 # counts the armed WINDOW and asserts it non-empty, because
                 # `arm_hit` is masked to 0 whenever no lane is armed -- so
                 # "no X" would otherwise be vacuous.
                 ("armnone", ["+IMG=test/armnone_image.hex", "+NCYC=8000",
                              "+MODE=2"]),
                 # ⭐ THE DEGENERATE CLOCKED COUNT, both routes in one image:
                 # lane 0 a clocked SHIFTIN at count 0, lane 1 a clocked SHIFT
                 # at count 15 where count + 1 wraps to 0. Asserts both lanes
                 # HALT with CONFIG_ERR set and NO pin edge emitted.
                 ("ckdegen", ["+IMG=test/ckdegen_image.hex", "+NCYC=8000",
                              "+MODE=3"]),
                 # the SECOND route: a clocked SHIFT at count 15, whose
                 # count + 1 wraps to 0. Its own image, because `config_err`
                 # gates dispatch engine-wide and the first refusal would
                 # stop the second from ever running.
                 ("ckdegen2", ["+IMG=test/ckdegen2_image.hex", "+NCYC=8000",
                               "+MODE=3"]),
                 # ⭐⭐ D4: THE SDA-HOLD BOUNDARY, THE TWO REFUSING POINTS.
                 # One image each, for the same reason `ckdegen` is two
                 # images: `config_err` gates dispatch ENGINE-WIDE, so two
                 # refusals in one program means only the first ever runs.
                 # ⛔ THE THIRD POINT (`SDA_HOLD + 1`, which must RUN) IS NOT
                 # HERE AND THAT IS NOT AN OMISSION: an open-drain clocked
                 # lane parks on an OBSERVED rise, and this bench holds
                 # `uio_in` at a constant 8'hFF -- a released SCL reads high
                 # but never TRANSITIONS, so the lane would park until the
                 # stretch-fault bound halted it and the arm would measure a
                 # hang. It runs in `tb_trace` (`+CKRUNS=1`) instead, which
                 # has `od_bus`. The same reasoning put `ckod` there.
                 ("ckhold_at", ["+IMG=test/ckhold_at_image.hex",
                                "+NCYC=8000", "+MODE=4"]),
                 ("ckhold_under", ["+IMG=test/ckhold_under_image.hex",
                                   "+NCYC=8000", "+MODE=4"])],
    },
    "tb_i2c": {
        "srcs": ["test/fram_i2c.v"],
        # ⛔ THE DUMP GOES TO A SCRATCH NAME. `probe_*` is gitignored by rule,
        # and a sweep that wrote a tracked artefact would be the clobber this
        # project has already shipped once (`rxfast_image.hex` left at the
        # swept `d` under a manifest entry for a different one).
        # ⭐ `+DIAG=0` IS DECLARED RATHER THAN DEFAULTED, and the drift guard
        # below is what asked for it: `run_i2c.py` supplies no `+DIAG` either,
        # so the certified run takes the bench's own default. Writing the value
        # down means a change to that default cannot silently change what the
        # sweep measured.
        # ⭐⭐ `+TXB` IS THE TRANSACTION LENGTH, and both arms are here because
        # ruling (a)2 needs the peer's SECOND address byte. At TXB = 2 this is
        # the sigrok-certified frame, unchanged. At TXB = 3 the program sends
        # `dev | addrhi | addrlo`, which is what reaches the peer's `P_ALO`
        # phase -- and the bench then asserts the assembled address is 0x0123,
        # a value only both phases can produce.
        # ⛔ A FOURTH BYTE WOULD BE A COMPLETE WRITE AND IT DOES NOT FIT: the
        # framing costs `51 + 60n` bytes, so n = 4 is 291 against a 256-byte
        # store. `P_WDATA` is therefore out of reach with this idiom -- see
        # `make_smoke_image.py --i2caddr`.
        "arms": [("default", ["+IMG=test/i2cframe_image.hex", "+NCYC=40000",
                              "+DIAG=0", "+TXB=2",
                              "+DUMP=probe_cov_i2c.bin"]),
                 ("addr3", ["+IMG=test/i2caddr_image.hex", "+NCYC=60000",
                            "+DIAG=0", "+TXB=3",
                            "+DUMP=probe_cov_i2caddr.bin"])],
    },
    "tb_witness": {
        "srcs": [],
        "arms": [("five", ["+IMG=test/five_image.hex", "+NCYC=200000",
                           "+WARMUP=4000"]),
                 ("stress", ["+IMG=test/stress_image.hex", "+NCYC=200000",
                             "+WARMUP=4000"])],
    },
    # ⛔⛔ THESE TWO NEED A PURPOSE-BUILT PROGRAM, and the sweep's first draft
    # fed them `five_image.hex` instead. `tb_jlane` then reported "complete
    # intervals: 6 (need >= 100)" and `tb_csat` could not measure a floor:
    # both benches need SIMULTANEOUS RELEASE at a port-feasible period, which
    # is the shape `run_csat.py`'s arm S builds. ⇒ The sweep builds the image
    # with THE SAME BUILDER those gates call (`make_smoke_image.py --five`)
    # rather than carrying a second recipe, and writes it to a `probe_*` name.
    "tb_csat": {
        "srcs": [],
        "gen": ["--five", "40", "40", "40", "40", "40", "probe_cov_sim40"],
        "arms": [("sim40", ["+IMG=test/probe_cov_sim40.hex", "+NCYC=200000",
                            "+WARMUP=4000"]),
                 # ⭐⭐ THE CLOCKED `C` RE-MEASUREMENT, swept permanently.
                 # `sim40` runs only OP_LEVEL and OP_REARM, so it cannot say
                 # anything about the clocked opcodes -- which is the whole
                 # reason `C` had to be re-measured. This arm dispatches
                 # clocked SHIFT and clocked SHIFTIN and reports their
                 # per-opcode OCCUPANCY, the only service-only measure.
                 # ⛔ MEASURED: occupancy 2 for both, i.e. C = 3, the
                 # charged value -- so the pre-registered verdict is
                 # "unchanged, proceed". It is an ARM and not a one-off run
                 # so a later RTL change cannot move C silently.
                 ("ckfive", ["+IMG=test/ckfive_image.hex", "+NCYC=200000",
                             "+WARMUP=4000"])],
    },
    # ⚠ AND `tb_jlane` WANTS THE OPPOSITE SHAPE TO `tb_csat`, which is why it
    # has its own image rather than sharing one. `run_dstar_check.py` builds
    # its arms as `[d, d+1, d+2, d+3, d+4]` -- DISTINCT per-lane periods at or
    # above `D* = 20`. Handed the simultaneous-release image it reported
    # "complete intervals: 0", so a shared image is not a saving here.
    "tb_jlane": {
        "srcs": [],
        "gen": ["--five", "20", "21", "22", "23", "24", "probe_cov_ds20"],
        "arms": [("lane0", ["+IMG=test/probe_cov_ds20.hex", "+LANE=0",
                            "+NCYC=200000", "+WARMUP=20000"])],
    },
    "tb_rxbw": {
        "srcs": [],
        "arms": [("default", ["+IMG=test/rxfast_image.hex", "+NCYC=200000"])],
    },
    # ⭐⭐ THE PEER MODELS ARE COVERED HERE, AND THAT IS THE POINT WILSON MADE:
    # the I2C peer's address-match branch had never fired, and coverage would
    # have shown it as a zero. The arms are ENUMERATED FROM `corpus.CORPUS`
    # rather than listed, so a sixth corpus program joins the sweep by being
    # added to the corpus.
    "tb_trace": {
        "srcs": ["test/fram_i2c.v", "test/fram_spi.v"],
        "arms": "FROM_CORPUS",
    },
}


def image_bytes(rel: str):
    """Token count of a hex image, or None if it is not on disk."""
    path = os.path.join(ROOT, rel)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="ascii", errors="replace") as fh:
        return len([w for w in fh.read().split() if w])


def corpus_arms():
    """tb_trace's arms, enumerated from the corpus rather than listed."""
    sys.path.insert(0, HERE)
    try:
        import corpus
    except Exception as exc:                      # pragma: no cover
        return None, "corpus.py did not import: %s" % exc
    out = []
    for name, (_builder, peer) in sorted(corpus.CORPUS.items()):
        out.append((name, ["+IMG=test/%s.hex" % name, "+PEER=%s" % peer,
                           "+OUT=probe_cov_trace_%s.txt" % name,
                           "+NCYC=200000", "+SEED=1", "+ASYNC=0",
                           "+STAYLOAD=0", "+SCLHOLD=0"]))
    # ⭐ THE TWO CLOCK-STRETCH ARMS, both of which `gate_corpus_trace.py`
    # already certifies: `+SCLHOLD` is a BENCH-DRIVEN hold on SCL (its line
    # 365), and the PEER-driven stretch is a second instance,
    # `fram_i2c #(.STRETCH(12)) u_i2cs`, selected by `+PEER=i2cs`. They are
    # different mechanisms and the first draft here conflated them.
    #
    # ⛔⛔ AND NEITHER ARM COVERS `fram_i2c.v:235`, WHICH IS THE FINDING. I
    # added them expecting the uncovered `if (STRETCH != 0)` to go green and it
    # did not move -- 37 points before, 37 after. The reason is worth more than
    # the arms: line 235 sits at the end of the `byte_done` block, so it needs
    # a COHERENT BYTE clocked into the stretching instance, and no program ever
    # delivers one. `i2cframe_image.hex` is the only program that produces
    # coherent I2C bytes and it runs in `tb_i2c` against the NON-stretching
    # peer; the corpus I2C program drives the bus but never assembles a byte
    # the peer accepts. ⇒ The stretching peer has never had a byte clocked into
    # it at all, and that is an owed test, not a measurement gap.
    # ⚠ The arms stay because they are certified arms that do execute the
    # bench-side stretch path -- but they are NOT the fix for 235, and saying
    # so here is the point: an arm added in the expectation of covering
    # something must be checked against whether it did.
    # ⭐⭐ THE OPEN-DRAIN CLOCKED ARM WITH A DELAY THAT FITS THE SDA HOLD,
    # and it is here because the coverage gate asked for it rather than because
    # it looked tidy. The hold-taking branch is reached only when a lane is
    # OPEN-DRAIN, CLOCKED, and has `d > SDA_HOLD`; every clocked open-drain
    # image in the corpus runs at d = 9, so the clamp sends them all down the
    # direct-drive path and the hold path was NEVER EXECUTED by the sweep.
    # ⛔ IT NEEDS A BUS MODEL, which is why it runs here and not in
    # `tb_csat`: an open-drain clocked lane PARKS on the observed rise, and
    # without a pull-up there is no rise to observe -- it would measure a hang.
    # That is also why the `ckfive` saturation image is deliberately push-pull.
    out.append(("ckod",
                ["+IMG=test/ckod_image.hex", "+PEER=none",
                 "+OUT=probe_cov_trace_ckod.txt",
                 "+NCYC=200000", "+SEED=1", "+ASYNC=0",
                 "+STAYLOAD=0", "+SCLHOLD=0"]))
    # ⛔⛔ THE `+A2BOUND=1` THAT USED TO SIT ON THE ARM ABOVE IS GONE, AND THE
    # COMMENT IT CARRIED WAS WRONG. It said `ckod`'s "lane set is the one A2
    # models, so 8 is its number". It is not: A2's model is the SHIPPED set
    # (UART-tx, SPI-tx, UART-rx, SPI-rx, one clocked I2C lane), while `ckod` is
    # four clocked open-drain lanes. Derived over `ckod`'s own lanes the bounds
    # are 8 / 11 / 17 / 18. Every clocked arm now gets `+A2SLACK` GENERATED
    # from `test/clocked_a2_bounds.json` in the planning loop (ruling S).
    # ⭐ RULING S's MUST-FIRE SUBJECT, swept under its OWN bound so the derived
    # numbers are held on every run, not only in the must-fire runner.
    out.append(("ckdense",
                ["+IMG=test/ckdense_image.hex", "+PEER=none",
                 "+OUT=probe_cov_trace_ckdense.txt",
                 "+NCYC=200000", "+SEED=1", "+ASYNC=0",
                 "+STAYLOAD=0", "+SCLHOLD=0"]))
    # ⭐⭐ D4's POSITIVE POINT: `d = SDA_HOLD + 1` MUST RUN. It is here rather
    # than in `tb_pinrange` because an open-drain clocked lane parks on an
    # OBSERVED rise and needs `od_bus`'s pull-up to have a rise to observe --
    # the same reason `ckod` is here. ⛔ WITHOUT THIS ARM the boundary is
    # tested only from the refusing side, and a refusal that was too WIDE --
    # one that rejected every clocked open-drain program -- would pass every
    # other arm in ruling D. `+CKRUNS=1` asserts config_err clear AND at least
    # one clocked action RETIRED, because the flag alone is also true of an
    # engine that never started.
    out.append(("ckhold_over",
                ["+IMG=test/ckhold_over_image.hex", "+PEER=none",
                 "+OUT=probe_cov_trace_ckhold_over.txt",
                 "+NCYC=40000", "+SEED=1", "+ASYNC=0",
                 "+STAYLOAD=0", "+SCLHOLD=0", "+CKRUNS=1"]))
    # ⭐ RULING M5: A PARTIAL LOAD, IN THE SWEEP. Every other arm loads the
    # whole store, so the release-time refusal (`short_load` in `project.v`)
    # was the one new uncovered point -- MEASURED, 1 against the table. This
    # arm loads corpus_i2c's 51 program bytes and releases. ⚠ It is a COVERAGE
    # arm, and it judges itself: `+EXPECT_REFUSED=1` makes tb_trace assert
    # CONFIG_ERR, `store_full` clear and zero writebacks (and tells
    # `progress.vh` the arm is quiescent on purpose). The mutant half -- the
    # same load RUNS on `M_NO_STORE_FULL` -- is `test/store_run.sh`'s.
    # ⛔ `+NBYTES` IS GIVEN HERE, and `plan()` does not append the file's count
    # when an arm names its own -- a plusarg's FIRST occurrence wins.
    out.append(("shortload",
                ["+IMG=test/corpus_i2c.hex", "+NBYTES=51", "+PEER=none",
                 "+OUT=probe_cov_trace_shortload.txt",
                 "+NCYC=4000", "+SEED=1", "+ASYNC=0",
                 "+STAYLOAD=0", "+SCLHOLD=0", "+EXPECT_REFUSED=1"]))
    # ⭐⭐ THE ZERO-HOLD BUILD, IN THE COVERAGE SWEEP (ruling D3). Removing the
    # `ck_hold_fits` clamp from the clocked site left ONE branch reachable only
    # at `SDA_HOLD == 0`: the open-drain side of the clocked direct-drive arm.
    # With a hold in force, every clocked open-drain action now routes to the
    # HOLD path -- D1 refuses the delays that used to be clamped past it -- so
    # at the default parameter point that `else` cannot be taken.
    # ⛔ MEASURED, NOT PREDICTED: the sweep reported it as the ONE new
    # uncovered point after D1/D3 (27 against 26), which is exactly the kind of
    # parameter-conditional branch `tb_smoke`'s `spl1` arm already exists for.
    # ⇒ BUILDING THE PARAMETER POINT IS THE FIX, not a waiver. A written reason
    #   would have said "unreachable at the default", which is true and is not
    #   the same as unreachable -- and the zero-hold build is a build we
    #   already ship a measurement arm for (`test/phases_run.sh`'s `hold0`), so
    #   it was being simulated and simply never swept.
    out.append(("ckod_hold0",
                ["+IMG=test/ckod_image.hex", "+PEER=none",
                 "+OUT=probe_cov_trace_ckod_hold0.txt",
                 "+NCYC=200000", "+SEED=1", "+ASYNC=0",
                 "+STAYLOAD=0", "+SCLHOLD=0"],
                {"SDA_HOLD_NS": 0}))
    out.append(("corpus_i2c_sclhold",
                ["+IMG=test/corpus_i2c.hex", "+PEER=i2c",
                 "+OUT=probe_cov_trace_i2c_sclhold.txt",
                 "+NCYC=200000", "+SEED=1", "+ASYNC=0",
                 "+STAYLOAD=0", "+SCLHOLD=200"]))
    # ⭐⭐ THE CLOCK-STRETCH FAULT BOUND, EXERCISED. `CK_STRETCH_TO` halts a
    # lane whose clock never rises, and a 200-cycle hold is well inside the
    # bound (it must be TOLERATED, losing nothing) while this one is far past
    # it and must HALT the lane with `clk_stretch_err` set.
    # ⛔ IT IS AN ARM RATHER THAN AN OWED POINT because the bound is new
    # safety-critical behaviour: a fault detector nothing ever triggers has
    # unknown strength, and "the lane halts" is exactly the kind of claim that
    # would otherwise sit in a comment. ⚠ FOUND BY CI, not by design -- the
    # cocotb bench holds `uio_in` constant so a released SCL never TRANSITIONS,
    # two open-drain tests hung on a park with no bound, and a dead board would
    # do the same thing.
    out.append(("corpus_i2c_sclfault",
                ["+IMG=test/corpus_i2c.hex", "+PEER=i2c",
                 "+OUT=probe_cov_trace_i2c_sclfault.txt",
                 "+NCYC=200000", "+SEED=1", "+ASYNC=0",
                 "+STAYLOAD=0", "+SCLHOLD=5000"], {"CK_PRE": 4}))
    # ⭐ THE OTHER SIDE OF THE MUST-FIRE: a 25,000-cycle hold is 500 us at
    # 50 MHz -- a LEGITIMATE long stretch, far inside the 35 ms SMBus bound --
    # and must NOT fault. ⛔ IT RUNS AT THE SHIPPED PRESCALER, because the claim
    # is about the real bound: at CK_PRE = 16384 those 25,000 cycles are 1.5
    # ticks of 107. Testing only the fault side would leave "does it tolerate a
    # long stretch" unmeasured, which is the half that matters to a user.
    out.append(("corpus_i2c_sclslow",
                ["+IMG=test/corpus_i2c.hex", "+PEER=i2c",
                 "+OUT=probe_cov_trace_i2c_sclslow.txt",
                 "+NCYC=200000", "+SEED=1", "+ASYNC=0",
                 "+STAYLOAD=0", "+SCLHOLD=25000"]))
    out.append(("corpus_i2cs_stretch",
                ["+IMG=test/corpus_i2c.hex", "+PEER=i2cs",
                 "+OUT=probe_cov_trace_i2cs_stretch.txt",
                 "+NCYC=200000", "+SEED=1", "+ASYNC=0",
                 "+STAYLOAD=0", "+SCLHOLD=0"]))
    return out, None


def discovered():
    """Every `test/tb*.v` on disk. The enumeration, not a list."""
    return sorted(n for n in os.listdir(HERE)
                  if re.fullmatch(r"tb.*\.v", n))


A2_BOUNDS_JSON = os.path.join(HERE, "clocked_a2_bounds.json")


def a2_slack_arg(img):
    """`+A2SLACK=s0,..,s4` for `img`, from the generated per-program bounds.

    Returns None when the image has no clocked open-drain lane. ⚠ A lane the
    derivation could not bound (an OVERLOADED lane set) is -1, which the bench
    reports without a verdict -- unbounded is a result there, not an omission.
    ⛔ A MISSING JSON IS AN ERROR, NOT "NO BOUND". Returning None would let
    every clocked arm run unbounded in silence, which is exactly the state
    ruling S ended.
    """
    if not os.path.isfile(A2_BOUNDS_JSON):
        raise RuntimeError(
            "test/clocked_a2_bounds.json is absent -- run "
            "`python model/a2/program_a2.py`. Without it every clocked arm "
            "would run with A2's upper bound switched off.")
    with open(A2_BOUNDS_JSON, encoding="utf-8") as fh:
        blob = json.load(fh)
    rec = blob.get(os.path.basename(img))
    if rec is None:
        return None
    sl = [-1] * N_LANES_A2
    for ln, e in rec["lanes"].items():
        if e.get("slack") is not None:
            sl[int(ln)] = int(e["slack"])
    return "+A2SLACK=" + ",".join(str(x) for x in sl)


#: the field count `clocked_conform.vh`'s `$sscanf` expects. ⚠ It is the
#: engine's N_LANES; a mismatch makes the bench print a FAIL rather than parse
#: a short vector, so drift here is loud.
N_LANES_A2 = 5


def includes_file(bench: str, inc: str) -> bool:
    """Does `bench`'s own source `include` this file?

    ⛔ CHECKED RATHER THAN ASSUMED: `SHARED_INCLUDE_DEFAULTS` excuses a plusarg
    only for the benches that actually pull the include in, so a bench that
    reads the same name in its own body still has to supply it. The first draft
    excused it everywhere, which would have let exactly the `CKRUNS` case this
    table was written for slip through unnoticed.
    """
    p = os.path.join(HERE, bench + ".v")
    if not os.path.isfile(p):
        return False
    with open(p, encoding="utf-8", errors="replace") as fh:
        body = fh.read()
    base = os.path.basename(inc)
    return any(os.path.basename(m) == base
               for m in re.findall(r'`include\s+"([^"]+)"', body))


def plusargs_read(bench: str):
    """Every plusarg the bench's own source reads, including its includes."""
    names = set()
    srcs = [os.path.join(HERE, bench + ".v")]
    with open(srcs[0], encoding="utf-8", errors="replace") as fh:
        body = fh.read()
    for inc in re.findall(r'`include\s+"([^"]+)"', body):
        p = os.path.join(ROOT, inc)
        if not os.path.isfile(p):
            p = os.path.join(HERE, os.path.basename(inc))
        if os.path.isfile(p):
            srcs.append(p)
    for p in srcs:
        with open(p, encoding="utf-8", errors="replace") as fh:
            # ⛔⛔ THE PATTERN WAS `[A-Z_]+` AND THAT WAS A BLIND SPOT, found
            # by ruling D4 rather than by review. `+A2BOUND` CONTAINS A DIGIT,
            # so the old pattern matched "A" and then needed "=", failed, and
            # the scanner never saw it -- which is why `A2BOUND` was read by
            # thirteen benches and supplied by one arm for a whole arc without
            # this check saying a word. A plusarg named `CKRUNS` was caught
            # instantly; the identical mistake under a digit was invisible.
            # ⇒ A guard that cannot see part of its subject reports a pass
            #   about the part it CAN see. Fourth instance of that class in
            #   this project's ledger.
            for m in re.finditer(r'\$value\$plusargs\("([A-Z_][A-Z0-9_]*)=',
                                 fh.read()):
                names.add(m.group(1))
    return names


def base_images():
    """Build the tracked-and-generated image set the arms load.

    ⛔⛔ WHY THIS IS HERE AT ALL, FROM A RED CI RUN. The sweep was green on
    this box and failed in CI with "image test/edge_image.hex is not on disk"
    for three arms. `edge_image.hex`, `five_image.hex` and `stress_image.hex`
    are GENERATED, not tracked, so they exist here only because the generators
    have been run -- and a fresh clone has none of them. ⚠ The local tree was
    carrying state the repository does not, which is the same shape as
    reporting a green from a tree that no longer exists.

    ⭐ THE GENERATOR LIST IS IMPORTED FROM `clean_room`, not re-typed. It
    already owns that declaration (`make_smoke_image.py --all`, then
    `corpus.py`), and a second copy here is the drift this file exists to
    prevent -- the clean room would then be verifying a recipe set the sweep
    does not use.
    """
    import subprocess
    # ⛔⛔ ONLY WHEN SOMETHING IS ACTUALLY MISSING, and this is not an
    # optimisation. `make_smoke_image.py --all` REWRITES the tracked
    # `test/artefacts.sha256` -- it pins every artefact's hash, which is its
    # job -- so running it unconditionally meant the coverage sweep modified a
    # tracked manifest on every single run. One of those runs left the five
    # `corpus_*.hex` hashes pointing at content that was not on disk.
    # ⇒ A fresh clone has no generated images and regenerates (and re-pins,
    # which is correct there -- a hash that then DIFFERS is exactly the finding
    # the clean room exists for). A working tree that already has them is left
    # alone, and the sweep touches nothing tracked.
    want = set()
    for top, cfg in CONFIG.items():
        arms = cfg["arms"]
        if arms == "FROM_CORPUS":
            continue
        for a in arms:
            for p in a[1]:
                if p.startswith("+IMG="):
                    want.add(p.split("=", 1)[1])
    missing = [w for w in sorted(want)
               if not os.path.isfile(os.path.join(ROOT, w))
               and "probe_cov_" not in w
               and not w.startswith("probe_longpath/")]
    if not missing:
        return []
    sys.path.insert(0, HERE)
    try:
        import clean_room
        gens = clean_room.GENERATORS
    except Exception as exc:
        return ["clean_room.GENERATORS did not import (%s) -- the sweep has "
                "no image recipes and must not improvise a copy" % exc]
    probs = []
    for cmd in gens:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0:
            probs.append("generator %s failed: %s"
                         % (os.path.basename(str(cmd[-1])),
                            (r.stdout + r.stderr).strip()[-200:]))
    return probs


def generate(cfg, top):
    """Build a bench's purpose-made probe image, via the gates' own builder.

    ⛔ IT RUNS BEFORE `+NBYTES` IS RESOLVED, because NBYTES is counted from the
    file on disk. A generator that ran after would leave the arm carrying the
    byte count of whatever image happened to be there -- which is the clobber
    class already shipped once here, when a sweep left a tracked image at the
    wrong `d` under a manifest entry for a different one.
    """
    args = cfg.get("gen")
    if not args:
        return None
    import subprocess
    r = subprocess.run([sys.executable,
                        os.path.join(HERE, "make_smoke_image.py")] + args,
                       capture_output=True, text=True, cwd=ROOT,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return "%s: make_smoke_image %s failed: %s" % (
            top, " ".join(args), (r.stdout + r.stderr).strip()[-200:])
    return None


def cocotb_images():
    """Images the cocotb suite loads, scraped from `test/test.py`."""
    path = os.path.join(HERE, "test.py")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as fh:
        body = fh.read()
    return sorted(set(re.findall(r'read_hex\(\s*"([a-z0-9_]+\.hex)"', body)))


def cocotb_blind_spot(recs):
    """⛔⛔ THE COCOTB SUITE'S STIMULUS MUST BE REACHABLE BY THE SWEEP.

    RULING 2, and it is here because the exclusion of `tb.v` produced TWO
    FALSE "never fired" GAPS. `cfgerr_image.hex` had been run by
    `test_config_error_refuses_to_run` all along, but the cocotb toplevel is
    the one bench this file excludes (no self-checking PASS line for a
    `--binary` run), so the open-drain refusal arms read as untested and I
    relayed them to Wilson as a silicon gap. Twice.

    ⚠ WHAT THIS IS AND IS NOT. Running the cocotb suite itself under Verilator
    with coverage is BLOCKED ON TOOL VERSIONS: cocotb 2.0.1 requires Verilator
    >= 5.036, and this box has 5.032 while the CI runner installs 5.020 -- so
    that arm cannot run in either environment today. What IS checkable now is
    that every PROGRAM the cocotb suite loads is also driven by a bench the
    sweep measures, which is what made `cfgerr_image` a false gap rather than
    a real one.
    ⇒ So this does NOT measure cocotb's own driving -- its host pacing and its
    serial-readback decode through `tb.v` are still unmeasured, and that
    remains owed. It does close the case where a cocotb-only PROGRAM exercises
    RTL nothing else reaches.
    """
    want = cocotb_images()
    if want is None:
        return ["test/test.py is missing, so the cocotb suite's images cannot "
                "be compared against the sweep"]
    if not want:
        return ["no `read_hex(...)` found in test/test.py -- either the cocotb "
                "suite stopped loading images or this scan no longer matches "
                "how it does, and a zero-hit scan proves the string absent, "
                "not the thing"]
    swept = set()
    for r in recs:
        for a in r["args"]:
            if a.startswith("+IMG="):
                swept.add(os.path.basename(a.split("=", 1)[1]))
    out = []
    for img in want:
        if img not in swept:
            out.append("the cocotb suite loads %s and NO swept bench does. "
                       "A point only that program reaches would read as "
                       "\"never fired\" -- which has already happened twice. "
                       "Give some bench in CONFIG an arm that loads it."
                       % img)
    return out


def plan():
    """(records, problems). A record is one runnable arm, fully resolved.

    ⛔ A MISSING CONFIG IS A PROBLEM, NOT A SKIP. The whole value of this file
    is that a new bench cannot join the tree without joining the sweep or being
    excluded in writing, and `can_run`-style silence is how a gate quietly
    stops covering something.
    """
    recs, probs = [], []
    probs.extend(base_images())
    ensure_longpath_image()
    found = discovered()
    for name in found:
        top = name[:-2]
        if name in EXCLUDED:
            continue
        if top not in CONFIG:
            probs.append("%s is on disk but has no CONFIG entry and no "
                         "declared exclusion" % name)
            continue
    for top, cfg in sorted(CONFIG.items()):
        if top + ".v" not in found:
            probs.append("CONFIG names %s but test/%s.v is not on disk"
                         % (top, top))
            continue
        gerr = generate(cfg, top)
        if gerr:
            probs.append(gerr)
            continue
        arms = cfg["arms"]
        if arms == "FROM_CORPUS":
            arms, err = corpus_arms()
            if err:
                probs.append("%s: %s" % (top, err))
                continue
        srcs = [os.path.join("test", top + ".v")] + cfg["srcs"] + ENGINE
        missing_src = [s for s in srcs
                       if not os.path.isfile(os.path.join(ROOT, s))]
        if missing_src:
            probs.append("%s: sources absent: %s" % (top, missing_src))
            continue
        # an arm is (label, plusargs) or (label, plusargs, build-parameters)
        arms = [(a[0], a[1], a[2] if len(a) > 2 else {}) for a in arms]
        declared = set()
        for _label, pargs, _g in arms:
            for a in pargs:
                declared.add(a.lstrip("+").split("=")[0])
        if top in NEEDS_NBYTES:
            declared.add("NBYTES")
        # ⭐ A SHARED INCLUDE'S PLUSARG IS DECLARED BY ITS DEFAULT, once, in
        # `SHARED_INCLUDE_DEFAULTS` -- but ONLY for a bench that really does
        # include the file. A blanket set would excuse a bench that reads the
        # plusarg in its OWN source and supplies it nowhere, which is the case
        # this check exists for.
        for pa, (inc, _dflt, _why) in SHARED_INCLUDE_DEFAULTS.items():
            if includes_file(top, inc):
                declared.add(pa)
        unsupplied = plusargs_read(top) - declared
        for u in sorted(unsupplied):
            probs.append("%s reads +%s and no arm supplies it -- a bench "
                         "running on an undeclared default is a different "
                         "run from the one the gates certify" % (top, u))
        for label, pargs, gparams in arms:
            img = None
            for a in pargs:
                if a.startswith("+IMG="):
                    img = a.split("=", 1)[1]
            full = list(pargs)
            if top in NEEDS_NBYTES and any(a.startswith("+NBYTES=")
                                           for a in pargs):
                pass                     # the arm sizes its own load (M5)
            elif top in NEEDS_NBYTES:
                if img is None:
                    probs.append("%s/%s needs +NBYTES but names no image"
                                 % (top, label))
                    continue
                nb = image_bytes(img)
                if nb is None:
                    probs.append("%s/%s: image %s is not on disk"
                                 % (top, label, img))
                    continue
                full.append("+NBYTES=%d" % nb)
            elif img is not None and image_bytes(img) is None:
                probs.append("%s/%s: image %s is not on disk"
                             % (top, label, img))
                continue
            # ⛔⛔ RULING S: THE A2 BOUND IS GENERATED, PER LANE, FROM THE
            # PROGRAM'S OWN LANE SET -- never typed on an arm. Every arm whose
            # image has a clocked open-drain lane gets `+A2SLACK` from
            # `test/clocked_a2_bounds.json`, which `model/a2/program_a2.py`
            # derives with pyRTA. So no arm can carry a bound for the wrong
            # lane set, and no clocked arm can be left out -- the two failures
            # the single `CK_GAP_SLACK` constant had at once.
            if img is not None:
                a2 = a2_slack_arg(img)
                if a2 is not None:
                    full.append(a2)
            # ⛔ THE BUILD KEY CARRIES THE PARAMETERS. Two arms that differ in
            # a build-time parameter are two BINARIES, and keying the build on
            # the top module alone would have silently run the SPL = 1 arm
            # against the SPL = 2 binary -- an arm that reports a pass for a
            # configuration it never built.
            key = top + ("" if not gparams else
                         "_" + "_".join("%s%s" % (k.lower(), v)
                                        for k, v in sorted(gparams.items())))
            recs.append({"top": top, "label": label, "srcs": srcs,
                         "args": full, "gparams": gparams, "build": key,
                         "xfail": 1 if (top, label) in XFAIL else 0})
    # ⛔ RULING 2: the cocotb suite's stimulus must be reachable
    probs.extend(cocotb_blind_spot(recs))
    return recs, probs


def main() -> int:
    recs, probs = plan()
    if "--json" in sys.argv:
        # ⛔ THE PLAN GOES OUT AS DATA so the shell sweep and the Python gate
        # consume ONE declaration. A second hand-typed arm list in the shell
        # script would be the drift this file exists to prevent.
        import json
        if probs:
            sys.stderr.write("benchset: %d problem(s)\n" % len(probs))
            for p in probs:
                sys.stderr.write("  %s\n" % p)
            return 1
        json.dump(recs, sys.stdout, indent=1)
        return 0
    print()
    print("=" * 78)
    print("THE BENCH SET -- %d arms over %d benches"
          % (len(recs), len({r["top"] for r in recs})))
    print("=" * 78)
    for name, why in sorted(EXCLUDED.items()):
        print("  excluded  %-14s %s" % (name, why.split(".")[0] + "."))
    print()
    for r in recs:
        print("  %-11s %-14s %s" % (r["top"], r["label"],
                                    " ".join(a for a in r["args"]
                                             if not a.startswith("+OUT"))))
    if probs:
        print()
        print("  *** %d PROBLEM(S):" % len(probs))
        for p in probs:
            print("      %s" % p)
    print()
    ci = cocotb_images() or []
    print("  cocotb images, all swept : %s" % (", ".join(ci) or "none"))
    print("    ⚠ cocotb's OWN driving is still unmeasured: running the")
    print("      suite under Verilator needs cocotb >= its 5.036 Verilator")
    print("      floor, and this box has 5.032 / CI has 5.020.")
    # ⛔ PRICE THE BLIND-SPOT CHECK. It passes today because all three cocotb
    # images are swept, and a check only ever seen to pass has unknown
    # strength -- which is the whole reason this one exists.
    print()
    print("  --- must-fire: a cocotb-only image is reported ---")
    fake_recs = [{"args": ["+IMG=test/corpus_i2c.hex"]}]
    _real = globals()["cocotb_images"]
    try:
        globals()["cocotb_images"] = lambda: ["corpus_i2c.hex",
                                              "only_in_cocotb.hex"]
        got = cocotb_blind_spot(fake_recs)
    finally:
        globals()["cocotb_images"] = _real
    hit = any("only_in_cocotb.hex" in g for g in got)
    print("    %-46s %s" % ("an image only cocotb loads is reported",
                            "ok" if hit else "*** MISSED"))
    if not hit:
        probs = list(probs) + ["the cocotb blind-spot check does not fire"]
    try:
        globals()["cocotb_images"] = lambda: []
        empty = cocotb_blind_spot([])
    finally:
        globals()["cocotb_images"] = _real
    print("    %-46s %s" % ("a zero-hit scan is a finding, not a pass",
                            "ok" if empty else "*** ACCEPTED"))
    if not empty:
        probs = list(probs) + ["an empty cocotb image scan reads as a pass"]
    # ⛔⛔ PRICE THE PLUSARG SCANNER, because it was BROKEN for a whole arc and
    # read as green. `A2BOUND` escaped it on a digit, so the two arms below are
    # the digit case and the shared-include case -- the exact two holes the
    # fix closed.
    print()
    print("  --- must-fire: the plusarg scanner sees what it claims to ---")
    seen = plusargs_read("tb_trace")
    for want, label in (("A2SLACK", "a plusarg with a DIGIT in its name"),
                        ("CKRUNS", "a plusarg read in the bench's own body")):
        ok = want in seen
        print("    %-46s %s" % (label, "ok" if ok else "*** MISSED " + want))
        if not ok:
            probs = list(probs) + ["plusargs_read cannot see +%s" % want]
    # ⛔ AND THE EXEMPTION MUST NOT BE BLANKET: a bench that does NOT include
    # the shared file gets no free pass from its default.
    inc = SHARED_INCLUDE_DEFAULTS["A2SLACK"][0]
    scoped = includes_file("tb_trace", inc) and not includes_file("tb_verdict",
                                                                  inc)
    print("    %-46s %s" % ("the shared-include excuse is scoped to includers",
                            "ok" if scoped else "*** NOT SCOPED"))
    if not scoped:
        probs = list(probs) + ["SHARED_INCLUDE_DEFAULTS is applied blanket"]
    print("  BENCH SET: %s" % ("ok" if not probs else "FAILED"))
    return 1 if probs else 0


if __name__ == "__main__":
    raise SystemExit(main())
