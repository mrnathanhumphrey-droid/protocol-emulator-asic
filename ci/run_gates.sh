#!/usr/bin/env bash
# THE MODEL GATES -- ONE ENTRY POINT, run by CI and by hand (Wilson's ruling 2).
#
# ⛔⛔ WHY THIS FILE EXISTS, FROM A REAL FAILURE. The ruling-0 commit was pushed
# after a local run reported "all 8 CI gates green", and CI went RED on
# `gate_stored_numbers` -- an unclassified collection (`test/test.py ::
# HOST_PAT`). Reproduced afterwards in a clean worktree at that commit: the gate
# fails there too. So it was never an environment difference. I ran the gate
# loop, then KEPT EDITING, and reported the earlier run's result for a tree that
# no longer existed.
# ⇒ Two things follow, and this script is both:
#     1. ONE list of gates, in one place, that CI executes and nothing else.
#        A loop pasted into a workflow and a loop typed at a prompt are two
#        lists, and two lists drift.
#     2. A DIRTY-TREE WARNING. A green on a tree you are not committing is not
#        a green on what you push. The script says so, by name, every run.
#
# ⚠ THE TOOLCHAIN IS SPLIT ON THE DEV BOX AND THAT IS HANDLED HERE, not by a
# second procedure. `yosys` lives only inside WSL on this machine while
# `iverilog` lives only natively, so the netlist step DELEGATES to WSL when
# yosys is not on PATH. In CI all three tools are native and no delegation
# happens. Either way the GATE LIST below is the same list, which is the part
# that drifted.
#
# Usage:
#   bash ci/run_gates.sh              # generate the netlist, run every gate
#   PE_NETLIST_JSON=/path bash ci/run_gates.sh   # reuse a netlist
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1

PY="${PE_PYTHON:-python}"
command -v "$PY" >/dev/null 2>&1 || PY=python3

# ⛔ RULING V: every tool through the one resolver, and the log says which.
# "$VL" / "$IV" / "$VVP" / "$YS" read PE_VERILATOR / PE_IVERILOG / PE_VVP /
# PE_YOSYS before PATH. A tool this side cannot see prints NOT FOUND here and
# is delegated to WSL below (or the gate that needs it is RED).
. "$ROOT/ci/tools.sh"
echo "  --- tools, as resolved (ruling V) ---"
tool_banner verilator iverilog vvp yosys

# ---------------------------------------------------------------------------
# THE GATE LIST. One place. Add a gate here and CI runs it.
# ---------------------------------------------------------------------------
# ⛔ NOT INCLUDED, and each exclusion is declared rather than implied:
#   * the clean room, the parameter-point sweep and run_spl_compare -- minutes
#     of simulation each, and the clean room moves files about. By-hand at each
#     `cmos5l` checkpoint.
#   * every pyRTA-PRIMARY gate (gate_pyrta, gate_j_sound, gate_c3_requote,
#     gate_j9_margins, ...). pyRTA is NOT VENDORED -- it is reached through
#     PYRTA_SRC -- and those gates are RED by design without it rather than
#     falling back to our own recurrence. `model/a2/run_a2.py` is their
#     harness, by hand at each checkpoint.
#   * `model/gate_flow_netlist.py` -- the R2 FLOW CROSS-CHECK. It reads the
#     HARDENING FLOW's post-synthesis netlist, which costs a ~3.5-hour run, so
#     it cannot be a per-push gate. It runs after each harden, on the
#     downloaded artefact, and its result is recorded with that harden's
#     per-job report:
#       $env:PE_FLOW_NETLIST = '<run>\logs\runs\wokwi\06-yosys-synthesis\tt_um_protocol_emulator.nl.v.json'
#       $env:PE_NETLIST_JSON = 'D:\ProtocolEmulator\probe_nl\ci_netlist.json'
#       python model/gate_flow_netlist.py
#     ⛔ IT IS A SECOND AUTHORITY, NOT A REPLACEMENT: `gate_reset_audit` above
#     still gates every push on the netlist built in seconds. ⛔ AND IT IS NOT
#     CONDITIONALLY WIRED INTO THIS LIST -- a gate that skips itself when an
#     env var is unset is the exact shape this project keeps finding bugs in,
#     so the exclusion is declared here and the invocation is explicit.
GATES=(
  # ⛔ THE BENCH LINT, and it earned its place twice over in one file. The
  # watchdog `test/progress.vh` was VACUOUS on all twelve benches on its first
  # run -- a hierarchical reference to a `localparam` compiled and never
  # matched -- and then its failure messages printed NOTHING because their
  # format strings were brace-concatenated, while the counter beside them
  # reached 144. Both shapes are "a check that cannot speak", which reads
  # exactly like a check that passed.
  model/gate_bench_lint.py
  # ⛔ EVERY OPCODE x FIELD x DEGENERATE VALUE, enumerated. `count = 0` was
  # found by accident (a corrupted store reached the engine) and a SECOND
  # route to the same state -- a clocked SHIFT with `count = 15`, where
  # `a_cnt + 1` wraps to 0 -- was found by writing the fix. That is a class,
  # and a class gets enumerated rather than fixed instance by instance.
  model/gate_degenerate_fields.py
  # ⛔ `tb.v` PREPROCESSES AS THE COCOTB MAKEFILE DOES. 81 of 81 arms and 16
  # of 16 gates were green while the cocotb half would not even preprocess:
  # the single bus model's include is written `test/od_bus.vh`, Verilator runs
  # from the repo root and resolves it, the Makefile runs from `test/` and did
  # not. Nothing local looked at `tb.v` at all, so only CI could see it.
  test/gate_tb_elaborates.py
  model/gate_ruling_audit.py
  model/gate_one_encoder.py
  model/gate_mutant_arms.py
  model/gate_reset_audit.py
  model/gate_stored_numbers.py
  model/gate_bench_indices.py
  model/gate_j_proof_anchors.py
  model/a2/gate_j_program.py
  # ⛔ `d_min` OVER REFILL-BEARING DISPATCHES -- the definition the clocked
  # SHIFT forced, fixed in `docs/PREREG_C_CLOCKED.md` §3a BEFORE it was
  # measured. It is here rather than in `run_a2.py`'s pyRTA set because it
  # needs no pyRTA: it composes the golden model onto one absolute timeline and
  # reads the spacings off it. ⛔ Its must-fire is the point -- counting EVERY
  # dispatch gives d_min = 3 (the L_SYNC park, which makes no port demand) and
  # U = 5.0, refusing every clocked program ever written.
  model/a2/gate_dmin_clocked.py
  # ⛔⛔ THE CLOCKED BUS TIMINGS, MEASURED OFF TRACES. It adjudicates a
  # measurement that `test/phases_run.sh` produces (clean + mutant + two
  # stretch arms + a push-pull control), and it is RED without it. ⭐ WHY IT IS
  # IN CI AT ALL: the defect it closes -- an SCL high phase that was the
  # synchroniser latency rather than the programmed delay -- was INVISIBLE to
  # every existing check, because Layer B compares dispatch COUNTS and a park
  # changes timing without changing a count.
  model/a2/gate_um10204.py
  # ⛔⛔⛔ RULING R -- THE PORT PREMISE, AND IT IS HERE BECAUSE A ONE-LINE
  # MUTANT SURVIVED EVERY OTHER GATE IN THIS FILE FOR AN ENTIRE ARC.
  # `M_CK_HOLD_INVAL` invalidates a clocked lane's head slot on every HELD
  # dispatch. A1 cannot see it (the PC does not advance, so the refill restores
  # an IDENTICAL word), B cannot see it (a refill changes no dispatch count),
  # and the coverage sweep cannot see it (the lines are covered either way).
  # What it breaks is the premise `D* = N_LANES * L_REFILL` and every
  # port-feasible cell in Theorem 3 are COMPUTED FROM: that a held clocked
  # dispatch owes no refill. Measured 16-17 refills per action against a
  # derived bound of SPL = 2.
  # ⇒ The suite read 20 of 20 while that premise was unchecked. This is the
  #   gate that ends it, and it is RED without `test/refill_run.sh`'s data.
  model/gate_port_demand.py
  # ⛔⛔ RULING S -- A2's post-HIGH bound belongs to (PROGRAM, LANE). The bench
  # used to hold ONE constant, derived for the A2 model's shipped lane set and
  # enforced on `ckod` -- a different lane set whose own bounds are
  # 8 / 11 / 17 / 18 -- while every other clocked arm ran unbounded. This gate
  # holds the generated per-lane budgets current, refuses a typed one, and
  # requires the must-fire: a LIGHTER set's bound on a HEAVIER feasible
  # program goes red while the program's own bound holds.
  model/a2/gate_a2_program.py
  # ⛔⛔⛔ RULING Q2 -- THE TWO-SIMULATOR CORPUS WITNESS, AND IT WAS NEVER HERE.
  # `test/gate_corpus_trace.py` compares iverilog against Verilator, cycle for
  # cycle, on every corpus program. It could not BUILD from `7a672b0` to now
  # (`final procedures cannot enable/call tasks`, in two shared includes), and
  # because it was in no list, 20 of 20 meant nothing about it. It was not
  # FAIL-OPEN -- it returns 1 on a build failure -- it was UNRUN: a correct
  # gate nobody invoked. Fifth check-that-could-not-fire, new shape.
  # => Brought back, it found TWO more things the dark period had hidden: D2's
  #   must-fire mutant had become EQUIVALENT (the self-clocked rework made it
  #   unable to express the defect), and its 1500-cycle window had shrunk to
  #   under one transaction at D5's d = 70. Both fixed in the same change.
  test/gate_corpus_trace.py
  # ⭐ AND THE CHECK THAT WOULD HAVE CAUGHT IT: every `gate_*.py` is in this
  # list, in `model/a2/run_a2.py`'s, or excluded BY NAME with a reason. Its
  # first run found NINE gate files nothing ran -- four passing analysis gates
  # and the whole TA-02 harness now under `run_a2.py`, `gate_flow_netlist`
  # excluded (a 3.5 h hardening input), and `gate_cj_bounds` -- RED then, now
  # RETIRED under ruling CJ with a per-claim pointer to the gates that run.
  model/gate_gates_complete.py
  # ⭐ N1 -- every NON-ADMISSIBLE image is declared by name with the condition
  # it breaks (OVERLOAD, PORT, PINMAP), derived from the image itself. Its
  # first run found the stress image `five_image` overloaded (U = 1.083) and
  # nine more below D* that nothing declared.
  model/gate_admissible_images.py
  # ⛔⛔ E+ -- A SHELL EXIT CODE IS READ ONLY WHERE IT CAN BELONG. Four times in
  # one arc a checking loop printed an exit code belonging to something else
  # (`| tail`, `| head`, and `"$(basename $g)" "$?"` -- the substitution reset
  # it, with no pipe for pipefail to catch), and once that hid a gate really
  # exiting 1. Every committed read is clean; this keeps it so, and
  # `ci/rc.sh`'s `run_rc` is how loops capture a code.
  model/gate_shell_rc.py
  # ⛔⛔ E -- THE PYTHON HALF: no bare `except:`, and no `except Exception`
  # that neither re-raises nor is named with where its verdict is recorded.
  # Its audit fixed four live swallows (measure_phases deleting phases on a
  # corrupt file, gate_stored_numbers skipping unparsable files, an over-
  # broad resolver, gate_a2_program skipping a crashed lane). Must-fire: the
  # pre-fix measure_phases `NameError -> None` shape.
  model/gate_except.py
  # ⛔⛔ V -- EVERY TOOL THROUGH ONE RESOLVER, AND THE LOG SAYS WHICH. A bare
  # `verilator` ran apt's 5.020 in CI and the witness disagreed with the pin
  # on 666 lines. Refuses a bare invocation or a private PATH-default resolver
  # anywhere in ci/ test/ model/, and a tool-driven script with no banner.
  # Must-fire: verilator_trace.sh as it stood at f8f952c.
  model/gate_tool_pinning.py
  # ⭐ MU -- F2 face 3 on the real design, priced by building M_COMB_OUT. That
  # mutant was killed only by hand until now.
  model/gate_f2_local.py
  # ⭐⭐ CDC5 -- no top-level input reaches core logic except through its
  # synchronizer (silicon fixes #4 / #5). Priced by building M_CDC_RAW, the
  # 94cebb7 wiring, whose ui_in[7] -> run path must be named.
  model/gate_cdc.py
  # ⛔⛔ PORTABILITY -- a STRICT front end (slang) over src/: zero errors
  # (declare-before-use: iverilog, Verilator and yosys all accepted 8 uses
  # before declaration and Vivado refused one, so the FPGA could not build the
  # chip), warnings pinned per class, LW's inlined port widths text-anchored.
  model/gate_slang_lint.py
  # ⭐⭐ UART -- the first program that RECEIVES a real UART stream (Wilson's
  # UART ruling): 8N1 vs a peer at -3..+3 % baud, back-to-back frames, bytes
  # vs what the PEER sent, count exact; framing reported; must-fires "edge"
  # (sampled at the bit edge, red at +-2 %) and "nostop" (no framing check).
  test/run_uartrx.py
  # ⭐⭐ SP2 -- the pe_asm protocol front-end (model/pe_proto.py): every
  # shipped FRAM program re-expressed as a TRANSACTION (START / rSTART / STOP
  # and CS framing generated from context), byte-identical to the verified
  # image; must-fire: rSTART emitted as STOP + START goes red.
  model/gate_sp2_frontend.py
  # ⭐⭐ CE5 FREEZE -- src/ unchanged since FREEZE_SHA (one constant, re-pin on
  # rebase); CE5 is VOID if this is red. Must-fire: a planted 1-char change
  # in a temp COPY of src/, via a temp index.
  model/gate_ce5_freeze.py
  # ⭐⭐ CE5 -- 1-Wire DS18B20 on the frozen RTL, a pe_asm program only:
  # presence, READ ROM + CRC, CONVERT T polled, READ SCRATCHPAD + CRC, every
  # slot in its datasheet window (19-7487 Rev 6) against a same-hand peer;
  # must-fires: write-0 low 50 us, read sample at 20 us, a flipped ROM bit.
  test/run_onewire.py
  # ⭐ MU -- the simulation mutant runner, ~10 s: every arm must die of the
  # assertion it names. It was run by nothing, so its kills were as old as the
  # day each was last typed.
  test/run_mutants.py
  # ⛔⛔ MU -- every `ifdef M_*` is KILLED by a named, actually-run killer or is
  # a DECLARED survivor; an unregistered mutant is red.
  model/gate_mutant_kills.py
  # ⛔⛔ RA3 -- no bench layer reads, on the same edge, another `always` block's
  # BLOCKING write. Layer R did, and the clean design failed it under iverilog.
  # Must-fire: Layer R as it stood at 231b37c.
  model/gate_bench_races.py
  # ⛔⛔ MF1 -- every pinned artefact hash matches its file, against the
  # COMMITTED manifest in CI (the working copy is regenerated here). The
  # manifest carried five stale corpus hashes through two green commits.
  test/gate_manifest.py
  # ⭐ RL1 -- the RTL's race classes: Verilator -Wall on src/ with BLKSEQ and
  # COMBDLY as errors, except a CHECKED block-local temporary. Must-fires: a
  # planted blocking assignment in a clocked block; a planted `<=` in a
  # combinational one.
  model/gate_rtl_lint.py
  # ⛔⛔ K + U -- every chip-driven SDA move holds >= SDA_HOLD after the SCL
  # fall, per CLASS (Layer H attributes each move to its opcode); the class x
  # image table has required cells; the refusal covers the unclocked frame.
  # The clocked SHIFTIN's release had hold 0 on every one until ruling K.
  model/gate_sda_hold.py
  # ⛔⛔ Z -- OUR RECURRENCE SEARCHES SPURI'S FULL CANDIDATE SET. It searched
  # only the subject's own releases and fell below TChecker's exact worst case
  # on 7 of 8 instances (184 of 6,601 with no jitter). It is CI's only timing
  # floor (no pyRTA here), so this runs here: >= the recorded exact verdicts,
  # the old search shown failing, the step set shown complete.
  model/gate_spuri_candidates.py
  # ⛔⛔ TF4 -- THE SCHEDULE FREEZE. The 50 MHz timing fix (registered
  # readiness, tree select, registered prefetch winner) may change nothing
  # where a claim is made: on the 12 shipped admissible images the dispatch
  # and pin streams must be byte-identical to the pre-fix RTL's recorded
  # digests. Must-fire: M_TF1_LATE (the naive retiming), which the smoke
  # bench passes and this gate must not.
  test/run_lockstep.py
  # ⭐ W -- THEOREM 3 ON THE BENCH, LIVE. The conclusion (every freed slot
  # valid before the decision that consumes it) on u20 and m20, ~55 s. Must-
  # fires: d = 18, and u20 on a slow-refill mutant built from src's own text
  # into scratch (src/ untouched). The full D* sweep is the recipe behind the
  # record `gate_j_program` checks.
  test/run_w_sweep.py
  # ⛔⛔ TX -- SILICON FIX #2: CLOCKED TRANSMIT VALUES. The clocked SHIFT's
  # host load fired on the HIGH phase, so every clocked byte drifted a bit
  # while every timing layer stayed exact. Layer V of clocked_conform.vh now
  # checks the BITS (V1 vs the golden model, V2 vs the pushed bytes); this
  # covers widths 1..8, MSB/LSB lanes, ACK or not, empty/refill. Must-fire:
  # M_TX_LOAD_ANYPHASE red on V1 and V2.
  test/run_cktx.py
  # ⛔ CI3 -- SILICON FIX #3 (b): WHERE THE PUSH-PULL CLOCKED RECEIVE SAMPLES,
  # FOUND BY SWEEPING THE SPI PEER's MISO DELAY on the real FRAM read: all
  # right at N <= d-2, all wrong at N >= d+1, the edge within 1 cycle of the
  # prediction (HOST_INTERFACE's SPI receive timing).
  test/run_spidelay.py
  # ⛔⛔ PN4 -- EVERY PIN-TAKING OPCODE IS RUN WITH ITS ACTION PIN != THE
  # LANE's HEADER PIN. Silicon fix #3 hid where the two were always equal
  # (I2C); so did pe_asm's alias check and Layer V2. Red on a class with only
  # same-pin coverage. Must-fires: no pindiv -> holes; a clock-pin action is
  # not diversity.
  model/gate_pin_matrix.py
  # ⛔⛔ RC4 -- EVERY START/STOP (I2C) LANE IS MSB-FIRST. Three corpus images
  # framed I2C on LSB-first lanes (hdr()'s default) and sent every byte
  # reversed until sigrok read them. Same rule as pe_asm's refusal; census
  # lane 0 exempt by name. Must-fires: a planted LSB I2C image, a stale
  # exemption.
  model/gate_i2c_order.py
  # ⛔⛔ M -- EVERY IMAGE WRITES THE WHOLE STORE. The store has no reset, and a
  # 51-byte image left 205 bytes holding power-up contents, one missing REARM
  # from running on real pins. Every image is now the program plus the defined
  # filler word; this refuses a short image, a lane with no terminating REARM,
  # and a header base outside its program. `test/store_run.sh` is the
  # simulated half (the bench sentinel, `clocked_conform.vh` Layer M).
  model/gate_store_full.py
  # ⭐ JOINED THE LIST when it took the RX lane-field width check. That check
  # guards against a received byte being attributed to the WRONG LANE if
  # `N_LANES` ever outgrows the explicit [2:0] on `e_rx_lane` -- and it lives
  # here rather than in the RTL because a generate-guarded zero-width net was
  # tried as a compile-time assertion and iverilog accepted it SILENTLY.
  # ⛔⛔ THE SAME DEFECT THREE TIMES is why this gate exists: an array
  # indexed by a PROGRAM-CONTROLLED pin field can be driven out of range,
  # and it shipped as the `pin_out[12]` WRITE, then as the `pin_in[a_pin]`
  # RX SAMPLE, then as the `pin_rise[l_armpin]` EDGE SELECT -- each found
  # and fixed separately. It enumerates the family and holds every member
  # to a declared guard, keyed on (file, array, index) so nothing has to be
  # re-anchored when lines move.
  model/gate_program_index.py
  model/part1_param_contract.py
  # ⛔⛔ THE HARNESS MUST BUILD AT GATE LEVEL, and this is in the list because
  # a checkpoint harden died proving otherwise: `gl_test` failed in 55 seconds
  # on a parameter override in `tb.v` after `gds` had spent 3h50m and
  # `precheck` 2h11m succeeding. Gate-level elaboration happens ONLY inside
  # the harden, so the RTL `test` job and the parameter sweep could both be
  # green while the gate-level harness was unbuildable. This answers the same
  # question in under a second.
  test/gl_harness_check.py
  # ⛔ RULING 1b. Every end-to-end payload pattern must contain a byte whose
  # bit reversal differs from itself. Three benches fed {5A, C3, 3C, A5} --
  # FOUR PALINDROMES OUT OF FOUR -- so every "the byte reached the wire"
  # result was true and said nothing about bit ORDER, which is how the
  # engine's LSB-first wire order survived an entire host-channel audit while
  # `pe_isa.py` documented the opposite.
  test/check_vectors.py
  # ⛔⛔ WILSON'S COVERAGE RULING, GATED. "Every uncovered branch, FSM state,
  # opcode arm and peer branch gets either a test that reaches it, or a
  # written reason why it's unreachable, checked like the reset allowlist. It
  # becomes a gate: new uncovered RTL fails CI unless justified."
  # ⭐ WHAT IT FOUND ON ITS FIRST RUN: `fram_spi.v`'s ENTIRE command decoder
  # had never executed (18 points), no byte had ever been written into the I2C
  # peer's memory, and `lane_underrun` and `tx_full_sticky` -- two status bits
  # the host reads -- had never been SET by any test, only asserted clear.
  # ⚠ The bench set it measures is `test/benchset.py`, which enumerates
  # `test/tb*.v` from disk and fails on a bench nobody classified.
  test/benchset.py
  test/gate_coverage.py
  model/pe_asm.py
)

# What each gate actually needs, so a missing prerequisite is NAMED rather than
# showing up as that gate's own failure.
# ⛔ `gate_reset_audit` NEEDS THE NETLIST, NOT `yosys` ON PATH, and the first
# version of this said yosys. On this box yosys lives only inside WSL, so the
# netlist is built by delegation and the gate -- which is pure Python once it
# has the JSON -- was declared unrunnable while its input sat ready on disk.
# A precondition stated as the wrong thing fails in the safe direction here
# (it refused to claim green) but it would have made the audit permanently
# unrunnable locally, which is how a gate quietly stops being run at all.
can_run() {
  case "$1" in
    # ⛔ THE CORPUS WITNESS NEEDS BOTH SIMULATORS, and a missing one is a
    # failure named as itself -- a two-simulator comparison with one simulator
    # compares nothing.
    test/gate_corpus_trace.py)
      command -v "$IV" >/dev/null 2>&1 || { echo "iverilog not found (PE_IVERILOG unset and not on PATH)"; return 1; }
      { command -v "$VL" >/dev/null 2>&1 || [ -n "${PE_VERILATOR:-}" ] \
        || command -v wsl.exe >/dev/null 2>&1; } \
        || { echo "no verilator and no wsl.exe to reach one"; return 1; } ;;
    model/gate_rtl_lint.py)
      { command -v "$VL" >/dev/null 2>&1 || command -v wsl.exe >/dev/null 2>&1; } \
        || { echo "no verilator and no wsl.exe to reach one"; return 1; } ;;
    model/gate_one_encoder.py|test/gl_harness_check.py|test/gate_tb_elaborates.py|test/run_mutants.py|model/gate_sda_hold.py|test/run_w_sweep.py|test/run_cktx.py|test/run_spidelay.py)
      command -v "$IV" >/dev/null 2>&1 || { echo "iverilog not found (PE_IVERILOG unset and not on PATH)"; return 1; } ;;
    model/gate_reset_audit.py)
      [ -n "${PE_NETLIST_JSON:-}" ] && [ -f "${PE_NETLIST_JSON:-}" ] \
        || { echo "no netlist at PE_NETLIST_JSON"; return 1; } ;;
    model/gate_f2_local.py)
      [ -n "${PE_NETLIST_COMB_JSON:-}" ] && [ -f "${PE_NETLIST_COMB_JSON:-}" ] \
        || { echo "no M_COMB_OUT netlist at PE_NETLIST_COMB_JSON"; return 1; } ;;
    model/gate_cdc.py)
      [ -n "${PE_NETLIST_CDCRAW_JSON:-}" ] && [ -f "${PE_NETLIST_CDCRAW_JSON:-}" ] \
        || { echo "no M_CDC_RAW netlist at PE_NETLIST_CDCRAW_JSON"; return 1; } ;;
    # ⛔ THE COVERAGE GATE NEEDS THE MEASUREMENT, and a missing measurement is
    # a FAILURE here rather than a skip -- the same rule the reset audit's
    # netlist precondition follows, and for the same reason: a gate that
    # quietly stops running is a gate that stops covering anything.
    test/gate_coverage.py)
      [ -n "${PE_COVERAGE_DAT:-}" ] && [ -f "${PE_COVERAGE_DAT:-}" ] \
        || { echo "no coverage data at PE_COVERAGE_DAT"; return 1; } ;;
    # ⛔ SAME RULE AS THE COVERAGE GATE: a missing measurement is a FAILURE,
    # not a skip. This gate exists because a timing defect survived every
    # count-based check, so a version of it that quietly stops running would
    # reopen exactly that hole.
    model/a2/gate_um10204.py)
      [ -n "${PE_PHASES_JSON:-}" ] && [ -f "${PE_PHASES_JSON:-}" ] \
        || { echo "no phase measurement at PE_PHASES_JSON"; return 1; } ;;
    # ⛔⛔ RULING R, AND THE STRICTEST VERSION OF THIS RULE. `M_CK_HOLD_INVAL`
    # survived every gate in this repo for a whole arc, so the premise `D*`
    # rests on was unchecked while the suite read 20 of 20. A version of this
    # gate that skipped on a missing measurement would restore exactly that.
    model/gate_port_demand.py)
      [ -n "${PE_REFILL_JSON:-}" ] && [ -f "${PE_REFILL_JSON:-}" ] \
        || { echo "no refill measurement at PE_REFILL_JSON"; return 1; } ;;
    # ⛔ RULING S: without the must-fire measurement the per-program bound has
    # never been seen to do anything a shared number would not.
    model/a2/gate_a2_program.py)
      [ -n "${PE_A2_JSON:-}" ] && [ -f "${PE_A2_JSON:-}" ] \
        || { echo "no A2 must-fire measurement at PE_A2_JSON"; return 1; } ;;
    # ⛔ RULING M: the sentinel's must-fire is a simulation; without it Layer M
    # has never been seen to name a lane.
    model/gate_store_full.py)
      [ -n "${PE_STORE_JSON:-}" ] && [ -f "${PE_STORE_JSON:-}" ] \
        || { echo "no sentinel measurement at PE_STORE_JSON"; return 1; } ;;
  esac
  return 0
}

echo "=============================================================================="
echo "  MODEL GATES -- ci/run_gates.sh  (the one entry point)"
echo "=============================================================================="
echo "  root   : $ROOT"
echo "  python : $("$PY" -c 'import sys;print(sys.version.split()[0])' 2>/dev/null)"
for t in iverilog verilator yosys; do
  printf "  %-7s: %s\n" "$t" "$(command -v "$t" 2>/dev/null || echo 'not on PATH')"
done

# ---------------------------------------------------------------------------
# ⛔⛔ THE DIRTY-TREE WARNING -- the specific lesson of the red commit.
# ---------------------------------------------------------------------------
echo
if command -v git >/dev/null 2>&1 && git rev-parse --git-dir >/dev/null 2>&1; then
  DIRTY="$(git status --porcelain --untracked-files=no 2>/dev/null)"
  if [ -n "$DIRTY" ]; then
    echo "  ⚠⚠ THE WORKING TREE HAS UNCOMMITTED CHANGES TO TRACKED FILES:"
    echo "$DIRTY" | sed 's/^/       /'
    echo "     A green below is a green on THIS tree. If you edit anything"
    echo "     after this run, the result no longer describes what you push --"
    echo "     which is exactly how a 'all gates green' report preceded a red"
    echo "     CI run once already. Re-run this script as the LAST thing before"
    echo "     reporting."
  else
    echo "  tree: clean -- a green below describes HEAD as it will be pushed"
  fi
else
  echo "  tree: not a git checkout, so no dirty-tree check"
fi

# ---------------------------------------------------------------------------
# ⛔⛔ THE GIT-BASH -> WSL PATH CONVERSION, IN ONE PLACE. Two steps delegate to
# WSL now (the netlist and the coverage sweep), and this conversion has already
# cost two failures: a rule that only matched `X:` converted nothing, because
# Git Bash reports this repo as `/d/ProtocolEmulator`; and a `sed 's|\\|/|g'`
# fix had its backslashes eaten before sed saw them. Parameter expansion has no
# such layer, and ONE copy cannot drift from the other.
# ---------------------------------------------------------------------------
wsl_root() {
  local p="${1//\\//}" d rest
  case "$p" in
    [A-Za-z]:*) d="${p%%:*}"; rest="${p#*:}" ;;
    /?/*)       d="${p:1:1}"; rest="${p:2}"  ;;
    *)          d="";         rest="$p"      ;;
  esac
  if [ -n "$d" ]; then
    d="$(printf '%s' "$d" | tr 'A-Z' 'a-z')"
    printf '/mnt/%s%s' "$d" "$rest"
  else
    printf '%s' "$rest"
  fi
}

# ---------------------------------------------------------------------------
# the netlist the reset audit classifies flops from
# ---------------------------------------------------------------------------
# ⭐ VIA THE SAME SCRIPT THE LOCAL FLOW USES (`test/local_netlist.sh`), whose
# output directory is an argument for exactly this reason.
NL_DIR="${PE_NETLIST_DIR:-/tmp}"
if [ -z "${PE_NETLIST_JSON:-}" ]; then
  echo
  echo "  --- netlist for the reset audit ---"
  if command -v "$YS" >/dev/null 2>&1; then
    bash test/local_netlist.sh "$ROOT" "" ci_netlist "$NL_DIR" || {
      echo "  *** yosys could not build the netlist"; exit 1; }
    # ⭐ RULING MU: THE SAME RECIPE AT `M_COMB_OUT`, ~5 s, so F2 face 3 is
    # priced on every push (`model/gate_f2_local.py`) rather than by hand.
    bash test/local_netlist.sh "$ROOT" M_COMB_OUT ci_netlist_comb "$NL_DIR" || {
      echo "  *** yosys could not build the M_COMB_OUT netlist"; exit 1; }
    # ⭐ CDC5: the same recipe at M_CDC_RAW, the must-fire of model/gate_cdc.py
    bash test/local_netlist.sh "$ROOT" M_CDC_RAW ci_netlist_cdcraw "$NL_DIR" || {
      echo "  *** yosys could not build the M_CDC_RAW netlist"; exit 1; }
    export PE_NETLIST_JSON="$NL_DIR/ci_netlist.json"
    export PE_NETLIST_COMB_JSON="$NL_DIR/ci_netlist_comb.json"
    export PE_NETLIST_CDCRAW_JSON="$NL_DIR/ci_netlist_cdcraw.json"
  elif command -v wsl.exe >/dev/null 2>&1; then
    # ⛔ DELEGATED, AND THE RULES FOR IT ARE THE PROJECT'S: always a SCRIPT
    # FILE (never inline `bash -c`) and always MSYS_NO_PATHCONV=1, because
    # Git Bash rewrites anything that looks like a path in the argv.
    # ⚠ WSL CANNOT SEE GIT BASH'S /tmp, so the wrapper and the output both
    # live where both sides can reach them.
    echo "  yosys is not on PATH; delegating the netlist step to WSL"
    WRAP="$ROOT/probe_ci_netlist.sh"
    {
      echo '#!/bin/bash'
      echo 'cd "$(dirname "$0")" || exit 1'
      echo 'bash test/local_netlist.sh "$PWD" "" ci_netlist "$PWD/probe_nl" || exit 1'
      echo 'bash test/local_netlist.sh "$PWD" M_COMB_OUT ci_netlist_comb "$PWD/probe_nl" || exit 1'
      echo 'bash test/local_netlist.sh "$PWD" M_CDC_RAW ci_netlist_cdcraw "$PWD/probe_nl"'
    } > "$WRAP"
    mkdir -p "$ROOT/probe_nl"
    # ⛔ TWO SPELLINGS TO HANDLE, AND BASH EXPANSION RATHER THAN `sed`.
    # Git Bash reports this repo as `/d/ProtocolEmulator`, not `D:\...`, so a
    # rule that only matched `X:` converted nothing and WSL was handed a path
    # that does not exist there. The second attempt used `sed 's|\\|/|g'`,
    # whose backslashes are eaten before sed sees them -- the same quoting
    # hazard this project has a standing rule about. Parameter expansion has
    # no such layer.
    WSLROOT="$(wsl_root "$ROOT")"
    # ⭐ AND IT IS CHECKED FROM WSL'S OWN VIEW before being used. The first
    # failure was "No such file or directory" from inside WSL, which is a
    # clearer message than anything downstream would have produced -- but only
    # because the wrapper happened to be the first thing touched.
    if ! MSYS_NO_PATHCONV=1 wsl.exe -e test -f "$WSLROOT/probe_ci_netlist.sh"
    then
      echo "  *** WSL cannot see $WSLROOT/probe_ci_netlist.sh"
      echo "      (converted from $ROOT). Fix the path mapping rather than"
      echo "      skipping the reset audit."
      exit 1
    fi
    MSYS_NO_PATHCONV=1 wsl.exe -e bash "$WSLROOT/probe_ci_netlist.sh" || {
      echo "  *** the WSL netlist step failed"; exit 1; }
    export PE_NETLIST_JSON="$ROOT/probe_nl/ci_netlist.json"
    export PE_NETLIST_COMB_JSON="$ROOT/probe_nl/ci_netlist_comb.json"
    export PE_NETLIST_CDCRAW_JSON="$ROOT/probe_nl/ci_netlist_cdcraw.json"
  else
    echo "  *** neither yosys nor wsl.exe is available, so the reset audit"
    echo "      cannot see the design. It is RED rather than skipped."
  fi
fi
[ -n "${PE_NETLIST_JSON:-}" ] && echo "  PE_NETLIST_JSON=$PE_NETLIST_JSON"
[ -n "${PE_NETLIST_COMB_JSON:-}" ] && echo "  PE_NETLIST_COMB_JSON=$PE_NETLIST_COMB_JSON"
[ -n "${PE_NETLIST_CDCRAW_JSON:-}" ] && echo "  PE_NETLIST_CDCRAW_JSON=$PE_NETLIST_CDCRAW_JSON"

# ---------------------------------------------------------------------------
# THE COVERAGE SWEEP, whose data `test/gate_coverage.py` adjudicates.
# ---------------------------------------------------------------------------
# ⛔⛔ WILSON'S RULING PUT THIS IN CI: "It becomes a gate: new uncovered RTL
# fails CI unless justified." So the measurement is produced here rather than
# by hand, and the gate is RED without it -- a coverage gate that passes when
# the measurement is missing is a guard that passes because of what it guards.
#
# ⚠ IT COSTS MINUTES, AND THAT IS DECLARED. Eleven Verilator builds at ~19s
# plus nineteen simulated arms is roughly five minutes, against seconds for
# every other gate here. `PE_COVERAGE_DAT=<path>` reuses an existing
# measurement, and `PE_SKIP_COVERAGE=1` leaves the gate RED rather than
# pretending. ⛔ The reuse path is for iterating on the WAIVER TABLE, not for
# reporting a green: data from an older tree describes that tree, which is the
# dirty-tree lesson above in another form.
if [ -z "${PE_COVERAGE_DAT:-}" ] && [ "${PE_SKIP_COVERAGE:-0}" != "1" ]; then
  echo
  echo "  --- coverage sweep for the coverage gate ---"
  # ⛔⛔ THE EXPORT IS GUARDED ON THE SWEEP'S EXIT CODE, NOT ON THE FILE
  # EXISTING, and this cost a false green. The first delegated run failed all
  # nineteen arms; `merged.dat` from an EARLIER successful run was still on
  # disk; this block exported it and `gate_coverage` passed on data describing
  # a tree that no longer existed. Nothing in the output said the data was
  # stale. ⇒ The sweep now destroys the old measurement before starting, AND
  # the path is only exported when the sweep actually succeeded. Either guard
  # alone leaves the hole open.
  SWEEP_OK=0
  if command -v "$VL" >/dev/null 2>&1; then
    if bash test/coverage_sweep.sh "$ROOT/probe_cov"; then
      SWEEP_OK=1
    else
      echo "  *** the coverage sweep failed -- the gate will be RED"
    fi
    [ "$SWEEP_OK" = "1" ] && [ -f "$ROOT/probe_cov/merged.dat" ] \
      && export PE_COVERAGE_DAT="$ROOT/probe_cov/merged.dat"
  elif command -v wsl.exe >/dev/null 2>&1; then
    echo "  verilator is not on PATH; delegating the sweep to WSL"
    CWRAP="$ROOT/probe_ci_coverage.sh"
    {
      echo '#!/bin/bash'
      echo 'cd "$(dirname "$0")" || exit 1'
      # ⛔⛔ THE SWEEP GETS THE SAME PINNED VERILATOR AS THE COCOTB ARM. Without
      # this they split inside ONE gate run -- the sweep on the distro's 5.032
      # and the arm on the pinned 5.053 -- and the coverage gate then failed on
      # a classified point that only the newer release emits. One toolchain, or
      # the two halves of the same gate disagree about what exists.
      echo "export PE_VERILATOR=\"${PE_VERILATOR_WSL:-/opt/oss-cad-suite-2026-09-30/bin/verilator}\""
      echo 'bash test/coverage_sweep.sh "$PWD/probe_cov"'
    } > "$CWRAP"
    CWSLROOT="$(wsl_root "$ROOT")"
    if ! MSYS_NO_PATHCONV=1 wsl.exe -e test -f "$CWSLROOT/probe_ci_coverage.sh"
    then
      echo "  *** WSL cannot see $CWSLROOT/probe_ci_coverage.sh"
      echo "      (converted from $ROOT). Fix the path mapping rather than"
      echo "      skipping the coverage gate."
    else
      if MSYS_NO_PATHCONV=1 wsl.exe -e bash "$CWSLROOT/probe_ci_coverage.sh"
      then
        SWEEP_OK=1
      else
        echo "  *** the WSL coverage sweep failed -- the gate will be RED"
      fi
      [ "$SWEEP_OK" = "1" ] && [ -f "$ROOT/probe_cov/merged.dat" ] \
        && export PE_COVERAGE_DAT="$ROOT/probe_cov/merged.dat"
    fi
  else
    echo "  *** neither verilator nor wsl.exe is available, so no coverage"
    echo "      can be measured. The gate is RED rather than skipped."
  fi
fi
[ -n "${PE_COVERAGE_DAT:-}" ] && echo "  PE_COVERAGE_DAT=$PE_COVERAGE_DAT"

# ---------------------------------------------------------------------------
# THE COCOTB COVERAGE ARM (ruling 2) -- the one bench the sweep excludes.
# ---------------------------------------------------------------------------
# ⛔⛔ IT RUNS AFTER THE SWEEP, NOT BEFORE. The sweep clears `cov_*.dat` at
# startup, which deleted this arm's output once and made the gate report "no
# cocotb coverage" after a run that had produced it.
# ⚠ A MISSING ARM IS REPORTED, NOT FAILED. It needs Verilator >= 5.036 (cocotb
# 2.0.1's floor) and Python <= 3.13; `gate_coverage` then names what it did NOT
# check rather than reading as "no false gaps".
if [ -z "${PE_COCOTB_DAT:-}" ] && [ "${PE_SKIP_COVERAGE:-0}" != "1" ]; then
  echo
  echo "  --- cocotb coverage arm (ruling 2) ---"
  CC_OK=0
  if command -v "$VL" >/dev/null 2>&1 || [ -n "${PE_VERILATOR:-}" ]; then
    if bash test/coverage_cocotb.sh "$ROOT/probe_cov"; then CC_OK=1; fi
  elif command -v wsl.exe >/dev/null 2>&1; then
    CCWRAP="$ROOT/probe_ci_cocotb.sh"
    {
      echo '#!/bin/bash'
      echo 'cd "$(dirname "$0")" || exit 1'
      echo "export PE_VERILATOR=\"${PE_VERILATOR_WSL:-/opt/oss-cad-suite-2026-09-30/bin/verilator}\""
      echo 'bash test/coverage_cocotb.sh "$PWD/probe_cov"'
    } > "$CCWRAP"
    CCROOT="$(wsl_root "$ROOT")"
    if MSYS_NO_PATHCONV=1 wsl.exe -e bash "$CCROOT/probe_ci_cocotb.sh"; then
      CC_OK=1
    fi
  fi
  if [ "$CC_OK" = "1" ] && [ -f "$ROOT/probe_cov/cocotb_coverage.dat" ]; then
    export PE_COCOTB_DAT="$ROOT/probe_cov/cocotb_coverage.dat"
  else
    echo "  ⚠ the cocotb arm did not produce data; the false-gap check will"
    echo "    report itself as NOT PERFORMED."
  fi
fi
[ -n "${PE_COCOTB_DAT:-}" ] && echo "  PE_COCOTB_DAT=$PE_COCOTB_DAT"

# ---------------------------------------------------------------------------
# THE CLOCKED PHASE MEASUREMENT, which `gate_um10204.py` adjudicates.
# ---------------------------------------------------------------------------
# ⛔⛔ IT BUILDS TWO ARMS ON PURPOSE -- clean and `M_CK_RISE_ELIGIBLE` -- because
# the gate requires the pre-fix design to MISS the bound it requires the fixed
# one to meet. A single-arm measurement would leave a timing check nobody has
# seen fail, which is how the watchdog verdict pipeline sat broken for an entire
# arc.
# ⚠ ~40s for two Verilator builds, declared. `PE_PHASES_JSON=<path>` reuses an
# existing measurement; as with coverage, reuse is for iterating on the TABLE,
# not for reporting a green on a tree the data does not describe.
if [ -z "${PE_PHASES_JSON:-}" ] && [ "${PE_SKIP_PHASES:-0}" != "1" ]; then
  echo
  echo "  --- clocked phase measurement (F4) ---"
  PH_OK=0
  if command -v "$VL" >/dev/null 2>&1 || [ -n "${PE_VERILATOR:-}" ]; then
    if bash test/phases_run.sh "$ROOT/probe_phases"; then PH_OK=1; fi
  elif command -v wsl.exe >/dev/null 2>&1; then
    echo "  verilator is not on PATH; delegating the measurement to WSL"
    PWRAP="$ROOT/probe_ci_phases.sh"
    {
      echo '#!/bin/bash'
      echo 'cd "$(dirname "$0")" || exit 1'
      echo "export PE_VERILATOR=\"${PE_VERILATOR_WSL:-/opt/oss-cad-suite-2026-09-30/bin/verilator}\""
      echo 'bash test/phases_run.sh "$PWD/probe_phases"'
    } > "$PWRAP"
    PWSLROOT="$(wsl_root "$ROOT")"
    if ! MSYS_NO_PATHCONV=1 wsl.exe -e test -f "$PWSLROOT/probe_ci_phases.sh"
    then
      echo "  *** WSL cannot see $PWSLROOT/probe_ci_phases.sh"
      echo "      (converted from $ROOT). Fix the path mapping rather than"
      echo "      skipping the timing gate."
    elif MSYS_NO_PATHCONV=1 wsl.exe -e bash "$PWSLROOT/probe_ci_phases.sh"; then
      PH_OK=1
    else
      echo "  *** the WSL phase measurement failed -- the gate will be RED"
    fi
  else
    echo "  *** neither verilator nor wsl.exe is available, so no phase"
    echo "      timing can be measured. The gate is RED rather than skipped."
  fi
  [ "$PH_OK" = "1" ] && [ -f "$ROOT/probe_phases/phases.json" ] \
    && export PE_PHASES_JSON="$ROOT/probe_phases/phases.json"
fi
[ -n "${PE_PHASES_JSON:-}" ] && echo "  PE_PHASES_JSON=$PE_PHASES_JSON"

# ---------------------------------------------------------------------------
# THE PORT-DEMAND MEASUREMENT (ruling R), which `gate_port_demand.py` judges.
# ---------------------------------------------------------------------------
# ⛔⛔ IT BUILDS TWO ARMS ON PURPOSE -- clean and `M_CK_HOLD_INVAL` -- and the
# mutant one is the reason the gate is worth running. That mutation survived
# EVERY gate in this file for an entire arc: the PC does not advance during a
# hold, so the refill restores an identical word and A1 sees nothing, while a
# refill changes no dispatch count so B sees nothing either. A clean arm alone
# would be a check nobody has seen fail, on the premise `D*` is computed from.
# ⚠ ~80s for two Verilator builds, declared, same as the phase measurement.
if [ -z "${PE_REFILL_JSON:-}" ] && [ "${PE_SKIP_REFILL:-0}" != "1" ]; then
  echo
  echo "  --- port-demand measurement (R) ---"
  RF_OK=0
  if command -v "$VL" >/dev/null 2>&1 || [ -n "${PE_VERILATOR:-}" ]; then
    if bash test/refill_run.sh "$ROOT/probe_refill"; then RF_OK=1; fi
  elif command -v wsl.exe >/dev/null 2>&1; then
    echo "  verilator is not on PATH; delegating the measurement to WSL"
    RWRAP="$ROOT/probe_ci_refill.sh"
    {
      echo '#!/bin/bash'
      echo 'cd "$(dirname "$0")" || exit 1'
      echo "export PE_VERILATOR=\"${PE_VERILATOR_WSL:-/opt/oss-cad-suite-2026-09-30/bin/verilator}\""
      echo 'bash test/refill_run.sh "$PWD/probe_refill"'
    } > "$RWRAP"
    RWSLROOT="$(wsl_root "$ROOT")"
    if ! MSYS_NO_PATHCONV=1 wsl.exe -e test -f "$RWSLROOT/probe_ci_refill.sh"
    then
      echo "  *** WSL cannot see $RWSLROOT/probe_ci_refill.sh"
      echo "      (converted from $ROOT). Fix the path mapping rather than"
      echo "      skipping the port-demand gate."
    elif MSYS_NO_PATHCONV=1 wsl.exe -e bash "$RWSLROOT/probe_ci_refill.sh"; then
      RF_OK=1
    else
      echo "  *** the WSL port-demand measurement failed -- the gate is RED"
    fi
  else
    echo "  *** neither verilator nor wsl.exe is available, so port demand"
    echo "      cannot be measured. The gate is RED rather than skipped."
  fi
  [ "$RF_OK" = "1" ] && [ -f "$ROOT/probe_refill/refill.json" ] \
    && export PE_REFILL_JSON="$ROOT/probe_refill/refill.json"
fi
[ -n "${PE_REFILL_JSON:-}" ] && echo "  PE_REFILL_JSON=$PE_REFILL_JSON"

# ---------------------------------------------------------------------------
# THE A2 MUST-FIRE (ruling S), which `gate_a2_program.py` judges.
# ---------------------------------------------------------------------------
# ⛔⛔ ONE PROGRAM, TWO BUDGETS: `ckdense` under its OWN derived per-lane
# budgets must pass, and under `corpus_i2c`'s lighter budget must fail. The
# swept arms already hold every clocked program to its own bound; this is the
# arm that shows the bound is PER PROGRAM rather than one number.
# ⚠ ~40s for one Verilator build, declared.
if [ -z "${PE_A2_JSON:-}" ] && [ "${PE_SKIP_A2:-0}" != "1" ]; then
  echo
  echo "  --- A2 per-program must-fire (S) ---"
  A2_OK=0
  if command -v "$VL" >/dev/null 2>&1 || [ -n "${PE_VERILATOR:-}" ]; then
    if bash test/a2_run.sh "$ROOT/probe_a2"; then A2_OK=1; fi
  elif command -v wsl.exe >/dev/null 2>&1; then
    echo "  verilator is not on PATH; delegating the measurement to WSL"
    AWRAP="$ROOT/probe_ci_a2.sh"
    {
      echo '#!/bin/bash'
      echo 'cd "$(dirname "$0")" || exit 1'
      echo "export PE_VERILATOR=\"${PE_VERILATOR_WSL:-/opt/oss-cad-suite-2026-09-30/bin/verilator}\""
      echo 'bash test/a2_run.sh "$PWD/probe_a2"'
    } > "$AWRAP"
    AWSLROOT="$(wsl_root "$ROOT")"
    if ! MSYS_NO_PATHCONV=1 wsl.exe -e test -f "$AWSLROOT/probe_ci_a2.sh"
    then
      echo "  *** WSL cannot see $AWSLROOT/probe_ci_a2.sh"
      echo "      (converted from $ROOT). Fix the path mapping rather than"
      echo "      skipping the A2 gate."
    elif MSYS_NO_PATHCONV=1 wsl.exe -e bash "$AWSLROOT/probe_ci_a2.sh"; then
      A2_OK=1
    else
      echo "  *** the WSL A2 measurement failed -- the gate is RED"
    fi
  else
    echo "  *** neither verilator nor wsl.exe is available, so the A2"
    echo "      must-fire cannot run. The gate is RED rather than skipped."
  fi
  [ "$A2_OK" = "1" ] && [ -f "$ROOT/probe_a2/a2.json" ] \
    && export PE_A2_JSON="$ROOT/probe_a2/a2.json"
fi
[ -n "${PE_A2_JSON:-}" ] && echo "  PE_A2_JSON=$PE_A2_JSON"

# ---------------------------------------------------------------------------
# THE STORE SENTINEL (ruling M3), which `gate_store_full.py` judges.
# ---------------------------------------------------------------------------
# ⛔ Shipped images written whole must never fetch the filler; a lane with no
# terminating REARM must be NAMED at the first filler address. The second arm
# is the one that shows Layer M can fire at all.
# ⚠ ~40s for one Verilator build, declared.
if [ -z "${PE_STORE_JSON:-}" ] && [ "${PE_SKIP_STORE:-0}" != "1" ]; then
  echo
  echo "  --- store sentinel (M3) ---"
  ST_OK=0
  if command -v "$VL" >/dev/null 2>&1 || [ -n "${PE_VERILATOR:-}" ]; then
    if bash test/store_run.sh "$ROOT/probe_store"; then ST_OK=1; fi
  elif command -v wsl.exe >/dev/null 2>&1; then
    echo "  verilator is not on PATH; delegating the measurement to WSL"
    SWRAP="$ROOT/probe_ci_store.sh"
    {
      echo '#!/bin/bash'
      echo 'cd "$(dirname "$0")" || exit 1'
      echo "export PE_VERILATOR=\"${PE_VERILATOR_WSL:-/opt/oss-cad-suite-2026-09-30/bin/verilator}\""
      echo 'bash test/store_run.sh "$PWD/probe_store"'
    } > "$SWRAP"
    SWSLROOT="$(wsl_root "$ROOT")"
    if ! MSYS_NO_PATHCONV=1 wsl.exe -e test -f "$SWSLROOT/probe_ci_store.sh"
    then
      echo "  *** WSL cannot see $SWSLROOT/probe_ci_store.sh"
      echo "      (converted from $ROOT). Fix the path mapping rather than"
      echo "      skipping the store gate."
    elif MSYS_NO_PATHCONV=1 wsl.exe -e bash "$SWSLROOT/probe_ci_store.sh"; then
      ST_OK=1
    else
      echo "  *** the WSL store sentinel failed -- the gate is RED"
    fi
  else
    echo "  *** neither verilator nor wsl.exe is available, so the store"
    echo "      sentinel cannot run. The gate is RED rather than skipped."
  fi
  [ "$ST_OK" = "1" ] && [ -f "$ROOT/probe_store/store.json" ] \
    && export PE_STORE_JSON="$ROOT/probe_store/store.json"
fi
[ -n "${PE_STORE_JSON:-}" ] && echo "  PE_STORE_JSON=$PE_STORE_JSON"

# ---------------------------------------------------------------------------
# run them
# ---------------------------------------------------------------------------
echo
FAILED=()
MISSING=()
# ⛔⛔ POSITIVE TOKENS (Wilson): a gate passes only on exit 0 AND its declared
# pass line (ci/gate_tokens.txt) in its OWN output. The judge proves itself
# first -- an empty output, a FAILED verdict and an undeclared gate must all
# be red -- or nothing below is readable.
"$PY" ci/pass_token.py --self-test
if [ $? -ne 0 ]; then
  echo "  *** the pass-token judge failed its own self-test -- no verdict possible"
  exit 1
fi
TOKLOG="$(mktemp)"
for g in "${GATES[@]}"; do
  # ⛔ A MISSING PREREQUISITE IS A FAILURE, NOT A SKIP, and it is named as
  # itself. "An audit that cannot see the design has not audited it" -- and a
  # run that quietly covered 8 of 9 gates is how a partial result gets
  # reported as a whole one.
  if ! why="$(can_run "$g")"; then
    echo "=== $g : *** CANNOT RUN -- $why ==="
    MISSING+=("$g ($why)")
    continue
  fi
  echo "=== $g ==="
  # output to a file (no pipe: the exit code read is the GATE's own), then
  # shown, then judged for the gate's positive token
  "$PY" "$g" > "$TOKLOG" 2>&1
  rc=$?
  cat "$TOKLOG"
  if [ $rc -ne 0 ]; then
    FAILED+=("$g (exit $rc)")
  else
    "$PY" ci/pass_token.py "$g" "$TOKLOG"
    if [ $? -ne 0 ]; then
      FAILED+=("$g (exit 0 but NO PASS TOKEN)")
    fi
  fi
done
rm -f "$TOKLOG"

echo
echo "=============================================================================="
echo "  GATES: $(( ${#GATES[@]} - ${#FAILED[@]} - ${#MISSING[@]} )) of ${#GATES[@]} passed"
if [ ${#FAILED[@]} -gt 0 ]; then
  echo "  FAILED:"
  for f in "${FAILED[@]}"; do echo "    $f"; done
fi
if [ ${#MISSING[@]} -gt 0 ]; then
  echo "  COULD NOT RUN (a missing tool is NOT a pass):"
  for m in "${MISSING[@]}"; do echo "    $m"; done
fi
if [ ${#FAILED[@]} -eq 0 ] && [ ${#MISSING[@]} -eq 0 ]; then
  echo "  ⇒ every gate in the list ran and passed. This is the SAME list CI"
  echo "    runs, so a green here is a green there -- provided the tree was"
  echo "    clean above."
  exit 0
fi
exit 1
