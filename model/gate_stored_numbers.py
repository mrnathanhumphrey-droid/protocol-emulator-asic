"""THE STORED-NUMBER AUDIT -- every gate that compares a number it was TOLD
rather than a number it MEASURED.

⛔⛔ WHY, FROM THE WORST DEFECT THIS PROJECT HAS HAD. `gate_j_program.py`
compared its derivation against `SWEEP`, a dict of stall measurements recorded
once. `sim <= derived` held against those values and FAILS against live
measurement at ten admissible points -- so the universal `J = 8` survived in a
PASSING gate for as long as nobody re-measured. The script that would have
re-measured it did not exist.

And the same shape, worse, next to it: `SWEEP_SINGLE` describes a
single-buffer configuration with **no build option at all**, so its arm cannot
be re-run even in principle -- while the gate computed the double buffer's
advertised benefit from it.

⇒ A stored number is not forbidden. Foreign-tool results (TChecker, pyRTA) and
  pre-registrations SHOULD be stored, and a typed expected value that a gate
  recomputes live is a regression pin, not a liability. What is forbidden is a
  stored number with **no way back to its source**.

So every site is classified, and each one must be exactly one of:

  LIVE    the gate recomputes the quantity in the same run and compares. The
          stored value is a regression pin; drift goes red by itself.
  RECORD  stored from a run that is not repeated in-gate. Must carry a RECIPE
          THAT CAN RUN -- a file that exists -- so the number can be remade.
  LEDGER  a historical entry whose whole purpose is to be immutable (a
          pre-registration, a digest ledger). Not re-measurable BY DESIGN, and
          it must say so.

⭐ THE TEETH: a RECORD whose recipe file does not exist is a FINDING, which is
exactly the `SWEEP_SINGLE` class. And coverage is measured, not asserted --
every module-level constant collection carrying three or more numbers is
scraped out of `model/` and `test/` and compared against the table, so a new
stored sweep cannot be added without appearing here as UNREVIEWED.
"""

from __future__ import annotations

import ast
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

LIVE, RECORD, LEDGER = "LIVE", "RECORD", "LEDGER"


class Site:
    def __init__(self, path, symbol, kind, what, recipe, dated, note=""):
        self.path = path            # repo-relative
        self.symbol = symbol        # module-level name that must exist
        self.kind = kind
        self.what = what
        self.recipe = recipe        # a FILE that can be run, or "" for LEDGER
        self.dated = dated          # commit / date / tool the number came from
        self.note = note


# ===========================================================================
# THE TABLE. Known members from Wilson's T4 plus whatever the scraper finds.
# ===========================================================================
SITES = [
    # ---- the headline pair ------------------------------------------------
    Site("model/a2/gate_j_program.py", "SWEEP", RECORD,
         "steady-state stall per action delay d, double buffer",
         "model/a2/price_j_sweep.sh",
         "live counterpart added after the J retraction",
         "the gate's `sim <= derived` check runs against THESE values; the "
         "live sweep is the authority and must be run to make the claim"),
    Site("model/a2/gate_j_program.py", "SWEEP_SINGLE", RECORD,
         "the same sweep on a SINGLE-BUFFER engine",
         "test/run_spl_compare.py",
         "WITHDRAWN -- contradicted by live measurement at 5 of 6 shared "
         "points once the configuration became buildable",
         "⛔ IT HAD NO RECIPE AT ALL: `NSLOT = 2*N_LANES` was fixed in "
         "pe_engine.v, so this arm described a configuration no command could "
         "produce -- while the double buffer's advertised benefit was computed "
         "from it. `SPL` is now a parameter, the arm is buildable, and the "
         "live numbers disagree with these (d=16: stored 0, measured 9). The "
         "stored values are retained as a labelled record and the benefit "
         "claim is withdrawn, not re-fitted"),

    # ---- foreign-tool records: stored ON PURPOSE -------------------------
    Site("model/a2/jitter_instances.py", "TCHECKER_RECORDED", RECORD,
         "TChecker reachability answers on the 11 jitter lane-instances",
         "model/a2/jitter_instances.py",
         "TChecker, tck-reach -a reach, /opt/ta/tchecker/bin (WSL Ubuntu)",
         "⚠ the recipe is the tool invocation described in the module header, "
         "not a committed script -- a foreign authority is re-run by hand. "
         "That is acceptable for a FOREIGN witness and would not be for ours"),
    Site("model/a2/jitter_instances.py", "PYRTA_SHIPPED", RECORD,
         "pyRTA response times on the shipped five lanes, per J_pipe",
         "model/a2/gate_pyrta_jitter.py",
         "PYRTA_SRC=<clone>/src, arm 3",
         "stored so `gate_j_sound.py` carries the margin verdict WITHOUT "
         "needing a third-party clone -- price_gates.sh removes pyRTA to "
         "prove the pyRTA gates are real, and the verdict must survive that"),

    # ---- synthesis measurements -----------------------------------------
    Site("model/a2/gate_cj_bounds.py", "DOUBLE_BUFFER_COST", RECORD,
         "flop and cell counts before/after double buffering",
         "test/yosys_check.sh",
         "Yosys 0.52, synth -flatten, both trees",
         "⚠ `flops_before` was measured on the PRE-DOUBLE-BUFFER TREE, which "
         "HEAD no longer is, and no commit ref is recorded -- so the recipe "
         "reproduces `flops_after` only. The delta is not re-derivable from "
         "HEAD alone"),

    # ---- immutable by design --------------------------------------------
    Site("model/a2/bursty.py", "DOUBLE_BUFFER_PREREG", LEDGER,
         "the pre-registered double-buffer prediction",
         "", "written before the measurement",
         "a pre-registration is worthless if it can be re-run; being frozen "
         "is the point"),
    Site("model/a2/lane_digest.py", "DIGEST_LEDGER", LEDGER,
         "historical lane-table digests",
         "", "appended at each table change",
         "the ledger is the record OF changes, so entries are immutable"),

    # ---- regression pins: recomputed live in the same run ----------------
    Site("model/a2/gate_pyrta.py", "EXPECTED_R", LIVE,
         "per-lane response times, typed",
         "model/a2/gate_pyrta.py", "n/a -- recomputed every run",
         "the answers are TYPED while the parameters are IMPORTED, so a "
         "recurrence change disagrees instead of re-blessing itself"),
    Site("model/a2/gate_j_sound.py", "EXPECTED", LIVE,
         "min margin per J_pipe over the shipped lane set",
         "model/a2/gate_j_sound.py", "n/a -- recomputed every run",
         "written down so a change in the recurrence, the lane table or the "
         "deadlines shows up as a disagreement instead of as a new table"),
    Site("model/gate_reset_audit.py", "ALLOWED", LIVE,
         "per-group expected widths of the unreset flop groups",
         "model/gate_reset_audit.py", "n/a -- read off the netlist every run",
         "⭐ this pin has fired for real: `s_wrdata` went 22 -> 24 when ACT_W "
         "absorbed the TX queue field, and the gate refused the new total"),
    Site("model/gate_mutant_arms.py", "EXPECT", LIVE,
         "declared line budget for each mutant `ifdef` arm",
         "model/gate_mutant_arms.py",
         "n/a -- the arms are preprocessed every run",
         "a budget with a declared reason per arm; drift in an arm goes red"),

    # ---- the C = 3 re-quote ---------------------------------------------
    # ⭐ THREE TABLES AND NOT ONE, which is itself the finding. The first
    # version of that gate kept a single C = 3 table filled from OUR
    # recurrence and then printed conclusions about the PUBLISHED bound. Each
    # table is now named for the bound that produced it.
    Site("model/a2/gate_c3_requote.py", "EXPECTED_C3_PYRTA", LIVE,
         "min margin per J_pipe at the measured C, pyRTA -- the PUBLISHED one",
         "model/a2/gate_c3_requote.py",
         "n/a -- recomputed every run, PYRTA_SRC required",
         "the corrected companion to gate_j_sound.EXPECTED; the gate is RED "
         "on drift rather than re-recording"),
    Site("model/a2/gate_c3_requote.py", "EXPECTED_C2_PYRTA", LIVE,
         "the same under the OLD C, so the correction's size is checkable",
         "model/a2/gate_c3_requote.py",
         "n/a -- recomputed every run, PYRTA_SRC required",
         "⛔ without it the must-fire could not show every row was strictly "
         "optimistic -- a correction with no before-value is an assertion"),
    Site("model/a2/gate_c3_requote.py", "EXPECTED_C2_OURS", LEDGER,
         "the J sweep under our bound at the PRE-CORRECTION configuration",
         "", "gate_j_sound.EXPECTED before ledger entry 65bc3c8114e5",
         "⛔ LEDGER, NOT LIVE, AND THAT IS THE POINT: it is what the sweep "
         "said at (C = 2, SPI-target D_tol = 18), the configuration the "
         "project shipped before the saturation measurement. It CANNOT be "
         "recomputed from the current table, and re-fitting it would destroy "
         "the only before-value the correction can be measured against. "
         "⭐ It was REPRODUCED from that configuration by gate_j_sound before "
         "being frozen here, so it is not merely remembered"),
    Site("model/a2/gate_c3_requote.py", "EXPECTED_C3_OURS", LIVE,
         "min margin per J_pipe at the measured C, OUR recurrence",
         "model/a2/gate_c3_requote.py", "n/a -- recomputed every run",
         "the safe-direction cross-check. ⛔ NEVER THE QUOTED NUMBER: it "
         "reads -2 at J = 8 where pyRTA reads +4, and an earlier draft "
         "published the -2 as an infeasibility"),
    Site("model/a2/gate_j_program.py", "SWEEP_LIVE", RECORD,
         "the live J sweep -- the ten points that retracted the universal J",
         "model/a2/price_j_sweep.sh",
         "200k cycles per point, >=100k-cycle asserted steady window",
         "⛔⛔ THESE NUMBERS EXISTED ONLY IN A SOURCE COMMENT. The gate's "
         "`sim <= derived` check ran against the STALE `SWEEP` and found zero "
         "violations while the prose above it said ten. Found by writing a "
         "check that needed them and getting `0 violations total`"),

    Site("test/gate_coverage.py", "TOGGLE_CEILING", RECORD,
         "uncovered TOGGLE points per file -- the ratchet the coverage gate "
         "holds, which may only fall",
         "test/coverage_sweep.sh",
         "the sweep as pinned: 25 arms over 12 benches at "
         "+verilator+rand+reset+0, PINNED Verilator 5.053 from OSS CAD "
         "Suite 2026-09-30 -- the ceilings are EXACT POINT COUNTS and 5.053 "
         "emits ~2x the toggle points of 5.032, so the release is part of "
         "the number",
         "⛔ MEASURED, NOT CHOSEN, and that distinction is the whole value of "
         "the number: a ratchet seeded from a guess permits a regression up "
         "to the guess. ⚠ Toggle is ratcheted rather than adjudicated point "
         "by point because there are ~390 uncovered toggle points against 37 "
         "line/branch ones, most of them top bits of wide buses that the "
         "parameter set cannot reach -- and 390 written reasons would bury "
         "the 37 that name real behaviour. The ruling's named subjects "
         "(branches, FSM states, opcode arms, peer branches) are all "
         "line/branch points, and those ARE adjudicated individually"),

    Site("model/gate_flow_netlist.py", "EXPECT_TIED", RECORD,
         "tied-reset (unreset) flop bits per declared register group in the "
         "HARDENING FLOW's PDK-mapped netlist -- 2048 + 64 + 24 + 8 + 8 + 1 "
         "= 2153, which must equal the local audit's unreset count",
         "model/gate_flow_netlist.py",
         "set PE_FLOW_NETLIST to a harden's "
         "logs/runs/wokwi/06-yosys-synthesis/"
         "tt_um_protocol_emulator.nl.v.json and PE_NETLIST_JSON to the local "
         "netlist, then run the gate: it PRINTS the per-group tied counts it "
         "measured beside the expected ones, so the number is remade on "
         "every run rather than merely compared",
         "⛔ MEASURED FROM THE ARTEFACT, and it is a PARTITION rather than a "
         "list of interesting groups: the gate requires these counts AND "
         "requires them to account for every tied bit with no residue. "
         "Checking only the four groups the ruling named would let one extra "
         "tied flop land anywhere else and still pass, which is exactly the "
         "must-fire. ⚠ THE TOTAL IS NOT STORED HERE -- it is read from the "
         "local netlist at run time, because an expectation recorded on both "
         "sides passes while both sides drift together. ⭐ The `u_eng.fix: 1` "
         "entry is the `pslot` alias by the concatenation identity "
         "fix = {pl, pslot}; `pslot` does NOT survive into the mapped "
         "netlist as a name, so a check spelling it would pass vacuously"),
]

# ⛔ Collections that carry numbers but are SPECIFICATIONS, not measurements:
# a pin map, a lane table, a condition list. They are excluded BY NAME rather
# than by a pattern, because a silent filter is how a coverage measure starts
# over-reporting itself as complete. Each name here is a claim that the thing
# is an input to the design, not an observation of it.
# ⚠ BUILT FROM THE SCRAPER'S OUTPUT, NOT FROM A GREP. The first version of
# this list was assembled from a text search and 10 of its 32 names were never
# scraped at all -- the exclusion list had drifted out of contact with the tree
# before it was ever committed, which is why the stale-exclusion check below
# exists and why it fired immediately.
SPEC_SYMBOLS = {
    # ⭐ The clocked phase model's PROGRAMS: the ACTION SHAPES it runs its
    # invariants over -- the corpus lanes, a full 4-byte FRAM write, a random
    # read with repeated START. The numbers are BIT COUNTS the protocols
    # require (8 for a byte, 1 for an I2C ACK slot), so they are inputs to the
    # model, not observations of it. ⛔ WHAT THE MODEL *MEASURES* -- the
    # dispatch count per action -- is NOT stored anywhere: it is computed by
    # running the machine and emitted to `test/clocked_bounds.vh`, which is why
    # there is no RECORD entry to pair with this exclusion.
    ("model/clocked_phase.py", "PROGRAMS"),
    # ⭐⭐ UM10204's TIMING MINIMA, TRANSCRIBED. These are REQUIREMENTS the
    # design is measured against, so they are inputs in the strongest sense --
    # the whole point of the gate that holds them is that nothing in this repo
    # may derive or adjust them. ⛔ AND THEY CANNOT BE PAIRED WITH A RECORD
    # ENTRY, which is a real weakness rather than an oversight: UM10204 is
    # third-party copyright and `refs/` is gitignored with the guard committed,
    # because the submission is open source. So there is no artefact here from
    # which the numbers could be remade on every run, the way `EXPECT_TIED` is
    # remade from a netlist. They are hand-carried, and `gate_um10204.py` says
    # so in its header and in its output. ⭐ ONE INDEPENDENT CROSS-CHECK
    # EXISTS: the t_LOW minima give d >= 25 / 65 / 235 at 50 MHz, which were
    # derived separately in the ruling that ordered the gate -- two routes to
    # the same three numbers, which a transcription slip would have had to
    # survive twice.
    ("model/a2/gate_um10204.py", "UM10204"),
    # ⭐ THE SAME TABLE'S MAXIMA -- `t_VD;DAT` and `t_r` per mode. They bound
    # the data hold from ABOVE, and they are requirements for exactly the same
    # reason the minima are: transcribed from UM10204, not derivable here, and
    # nothing in this repo may adjust them. ⛔ THEY EXIST BECAUSE A FLOOR
    # WITHOUT A CEILING IS HALF A REQUIREMENT: with only the minima the gate
    # would accept any hold above 15 cycles, including one long enough to push
    # the data change past the next clock rise -- a worse defect than the one
    # the hold fixes.
    ("model/a2/gate_um10204.py", "UM10204_MAX"),
    # ⭐ THE DELAY SPAN THE HIGH-PHASE INSTRUMENT SWEEPS. An experiment design,
    # not an observation: four periods spanning 13x, chosen because the defect
    # being caught was a high phase that did not move with `d` AT ALL, and a
    # single delay cannot distinguish "t_HIGH = d" from "t_HIGH happens to
    # equal d here". ⛔ What the instrument MEASURES -- t_HIGH and t_LOW per
    # lane -- is not stored anywhere: it is written to the phase JSON by
    # `test/measure_phases.py` on every run and adjudicated from there, which
    # is why there is no RECORD entry to pair with this exclusion either.
    ("test/make_smoke_image.py", "CKOD_DELAYS"),
    # ⭐ THE I2C MODE RATE CEILINGS -- 100 kHz, 400 kHz, 1 MHz. These are what
    # the mode NAMES mean, not observations of anything, and they are the
    # loosest kind of input: an I2C mode is a MAXIMUM rate, so a slower clock
    # is a legal clock of that mode and only the upper edge constrains. ⛔ They
    # sit beside `UM10204`'s minima for the same reason that table does -- a
    # requirement the design is measured against, which nothing here may
    # derive or adjust.
    ("model/a2/gate_clocked_lane_a2.py", "MODE_MAX_HZ"),
    # ⭐ The degenerate-field audit's two tables. `TABLE` is the enumerated
    # verdict per (opcode, field, degenerate value) and `DELIBERATE` names the
    # must-fire images that trip a refusal ON PURPOSE. Both are
    # SPECIFICATIONS -- a statement of what is legal and which programs are
    # intentionally illegal -- not measurements of the design. ⚠ The numbers a
    # reader sees in them are field VALUES (0, 15, PIN_NONE) quoted from the
    # ISA, which is an input to the design; nothing in either table is
    # observed, so there is no run to check them against.
    ("model/gate_degenerate_fields.py", "TABLE"),
    ("model/gate_degenerate_fields.py", "DELIBERATE"),
    # instance / lane / pin definitions -- inputs to the design
    ("model/a2/a2_close.py", "REQUIRED"),
    ("model/a2/frontier.py", "LANE_SPEC"),
    ("model/a2/task_model.py", "LANES"),
    ("model/a2/gate_differential.py", "LANES"),
    ("model/a2/gate_twin_pair.py", "TWINS"),
    ("model/a2/jitter_instances.py", "JINSTANCES"),
    ("model/a2/gate_pin_subsets.py", "PINS"),
    ("model/a2/gate_pin_subsets.py", "PINS_DIR"),
    ("model/a2/gate_load_pin_safety.py", "PINMAP"),
    ("model/a2/gate_load_pin_safety.py", "SERIAL_BITS"),
    ("model/a2/gate_encoding_f1.py", "PIN_MAP"),
    ("model/a2/gate_encoding_f1.py", "TRANSACTIONS"),
    ("model/a2/gate_cj_bounds.py", "OPNAMES"),
    ("model/a2/gate_cj_bounds.py", "J_SOURCES"),
    ("model/a2/gate_admissibility_1_6.py", "CONDITIONS"),
    ("model/a2/gate_spec_freeze_s2.py", "CUT_FIELDS"),
    ("model/a2/grid_quantization.py", "EDGES"),
    ("model/a2/gate_microarch_1_3.py", "UNPIPELINED"),
    ("model/a2/gate_microarch_1_3.py", "PIPELINED"),
    ("model/a2/gate_microarch_1_3.py", "CANDIDATES"),
    ("model/part1_param_contract.py", "FORBIDDEN_LITERALS"),
    ("model/part1_param_contract.py", "REQUIRED_PARAMS"),
    ("model/sram_spike.py", "MACROS"),
    ("model/ta01b/uart_stream.py", "STREAM_DEFAULT"),
    ("model/gate_reverse_trace.py", "LANE_CFG"),
    ("test/make_smoke_image.py", "FIVE_STRESS"),
    # ⭐ `CKHOLD_POINTS` IS AN EXPERIMENT'S DESIGN AND THE NUMBERS ARE OFFSETS,
    # not values: -1, 0, +1 AROUND a boundary this file does not store. The
    # boundary itself is `SDA_HOLD`, which lives in `src/pe_engine.v` and is
    # read through `model/hold_bound.py` -- so there is nothing here to drift
    # from the design. ⛔ THE OFFSETS ARE THE POINT: a refusal tested only
    # below its boundary passes against a guard written `<` when the design
    # says `<=`, which is why `at` (offset 0) must refuse and `over` (+1) must
    # run.
    ("test/make_smoke_image.py", "CKHOLD_POINTS"),
    # ⭐ `CKDENSE_DELAYS` IS AN EXPERIMENT'S DESIGN, NOT A RESULT: the delays
    # of ruling S's must-fire subject, chosen to make a FEASIBLE program
    # heavier than `corpus_i2c`. The RESULTS -- its per-lane budgets and its
    # measured lateness -- are derived (`test/clocked_a2_bounds.json`, held
    # current by `gate_a2_program`) and measured (`test/a2_run.sh`), never
    # stored here.
    ("test/make_smoke_image.py", "CKDENSE_DELAYS"),
    ("test/gate_corpus_trace.py", "COLS"),
    # ⭐ `PAD_COLLISION` IS A NAMED-EXEMPTION LIST (ruling P5), like
    # `gate_degenerate_fields.DELIBERATE`: an image, the LANES of it that
    # collide with the pad override, and why that is intended. Its numbers are
    # lane indices and the pin numbers quoted in the prose -- not a
    # measurement. ⛔ STALENESS IS CAUGHT WHERE IT MEANS SOMETHING, not here:
    # `audit_pad_collisions` reds on an undeclared collision, on a declared
    # lane set that no longer matches, AND on a declaration whose image no
    # longer collides at all. The pin numbers themselves come from
    # `src/project.v` through `_assert_rtl_agrees`, so they cannot drift from
    # the RTL either.
    ("test/corpus.py", "PAD_COLLISION"),
    # ⭐ THE COVERAGE SWEEP'S TWO DECLARATIONS, and neither holds a
    # measurement. `benchset.CONFIG` is STIMULUS -- plusargs, cycle budgets
    # and the per-lane delay vectors handed to `make_smoke_image.py` -- i.e.
    # inputs to the design in exactly the sense this list is for. And
    # `gate_coverage.CLASSIFIED`'s numbers are SOURCE LINE ANCHORS: every one
    # is a line in `pe_engine.v`, `project.v` or a peer model that a waiver
    # points at. ⛔ Staleness in both is caught where it means something
    # rather than here: `benchset.plan()` fails if an image or source is
    # absent, and `gate_coverage.check_stale` fails on an anchor the merged
    # coverage does not contain -- which is what a moved line looks like.
    ("test/benchset.py", "CONFIG"),
    # ⭐ `SHARED_INCLUDE_DEFAULTS` IS A RUN CONDITION, NOT A MEASUREMENT: the
    # default value a shared include's plusarg takes on the benches that do not
    # override it. ⛔ IT EXISTS BECAUSE THE SCANNER COULD NOT SEE `A2BOUND` --
    # a digit in the name defeated its pattern -- so the number here (0) is the
    # declaration of a stimulus, in exactly the sense `CONFIG` above is, and
    # staleness is caught where it means something: a bench that stops
    # including the file loses the excuse, which `includes_file` enforces, and
    # the gate's own must-fire checks that the scanner still sees both names.
    ("test/benchset.py", "SHARED_INCLUDE_DEFAULTS"),
    ("test/gate_coverage.py", "CLASSIFIED"),
    # ⭐ ANCHOR_TEXT is the same thing one step further: a line number and the
    # SOURCE TEXT that line must still read as. Its numbers are anchors, not
    # measurements, and drift in them is caught by `check_anchors` -- which
    # names expected vs found -- rather than by an audit here.
    ("test/gate_coverage.py", "ANCHOR_TEXT"),
    # ⭐ a MUTANT INVENTORY, like the others above: a define, the bench it is
    # judged by, the failure text that certifies the kill, and why. Its
    # numbers are line counts in prose, not measurements.
    ("test/run_mutants.py", "PINRANGE_MUTANTS"),
    # ⚠ PINRANGE_ARMS is NOT listed: it holds two string values, so the
    # scraper (>= 3 numbers) never sees it, and a named exclusion the
    # scraper cannot find is itself a finding -- this gate says so, and said
    # so about this very line.
    # ⭐ the program-index family: (file, array, index) -> (guard, reason).
    # Its only numbers are the pin-count bound in the prose.
    ("model/gate_program_index.py", "CLASSIFIED"),
    ("model/gate_program_index.py", "PROGRAM_INDEX"),
    # ⭐ MUTANT INVENTORIES ARE DECLARATIONS, not measurements: a define, what
    # it breaks, the failure text that certifies the kill, and why. The numbers
    # the scraper counts are inside the PROSE (queue indices, byte values named
    # in the reason). `MUTANTS` and `EDGE_MUTANTS` are already excluded on the
    # same grounds.
    ("test/run_mutants.py", "TX_MUTANTS"),
    ("test/run_mutants.py", "HALF_MUTANTS"),
    # ⭐ A SWEEP'S POINTS ARE AN EXPERIMENT'S DESIGN, not its result. The
    # points straddle the derived payload slot and are CONSECUTIVE INTEGERS
    # around it, for the reason ruling 3 gives: this project has three cases
    # of a must-fire's witness sliding between hand-picked points. The RESULT
    # is the measured boundary and the measured frame gap, both checked
    # against the derivation inside the gate.
    ("test/run_rxbw.py", "D_POINTS"),
    # ⭐ THE C-SATURATION ARMS ARE AN EXPERIMENT'S DESIGN, not its result. The
    # delays are chosen (40 = 2 x D*, so refill cannot bind; 60 as a slack
    # control; 2 as the oversubscribed contrast) and the pre-registration
    # explains each choice. The RESULT is `btbmin`, which lives in
    # `gate_c3_requote.C_SPACING` and is tabled above.
    ("test/run_csat.py", "ARMS"),
    # ⭐ A TEST PAYLOAD IS STIMULUS, NOT A MEASUREMENT. The four bytes the
    # cocotb host feeder pushes are chosen to be distinguishable on a wire;
    # nothing is concluded from their values. `host_feed.vh` carries the same
    # kind of pattern on the Verilog side and is not a Python collection.
    ("test/test.py", "HOST_PAT"),
    # ⭐ FORCED ANSWERS, NOT OBSERVATIONS. The `zone/` validation tables are
    # schedules whose answers are DERIVED BY HAND, used to validate the model
    # generator before TChecker is trusted on anything else. They are a
    # specification of what the tool must reproduce, and the tool computes
    # live against them -- so a drift shows up as a disagreement.
    ("model/a2/zone/run_edf.py", "VALIDATION"),
    ("model/a2/zone/run_edf.py", "INSTANCES"),
    ("model/a2/zone/run_bursty.py", "INSTANCES"),
    ("model/a2/zone/run_jitter.py", "JVALIDATION"),
    # gate / mutant inventories and fixtures
    ("model/a2/run_a2.py", "GATES"),
    ("model/ta02/run_ta02.py", "GATES"),
    ("model/ta02/audit_branches.py", "MUTANTS"),
    ("model/gate_ruling_audit.py", "RULINGS"),
    ("test/run_mutants.py", "EDGE_MUTANTS"),
    ("test/run_jlane.py", "ARMS"),
    # ⭐ CAUGHT BY THIS GATE'S OWN COVERAGE CHECK, on the commit that added it:
    # the T3 sweep's d points. They are which programs to BUILD, not readings.
    ("test/run_spl_compare.py", "D_LIST"),
    # ⭐ CAUGHT THE SAME WAY ON THE NEXT COMMIT: the parameter-point sweep's
    # bench inventory. Its numbers are run lengths and plusargs -- how to
    # invoke a bench, not an observation of one.
    # ⚠ Twice in two commits, both times on my own new file. That is the
    # coverage check doing the job it exists for, and it is worth recording
    # that it catches the AUTHOR rather than only a future editor.
    ("test/run_param_points.py", "BENCHES"),
    # ⭐ AND A THIRD TIME, ON A THIRD NEW FILE: the J=9 proof's premise list.
    # Its numbers are Verilog literals inside the RTL anchors (`3'd0`, `1'b0`),
    # so it is a specification of what the proof rests on, not an observation.
    # ⚠ Three commits, three catches, all of them on my own new work. Worth
    # recording: the coverage check's value is that it does not care whose file
    # it is, and it has now never once been triggered by someone else.
    ("model/gate_j_proof_anchors.py", "PREMISES"),
    # the D* theorem's check: which programs to BUILD, not readings from them
    ("test/run_dstar_check.py", "D_POINTS"),
    ("test/run_dstar_check.py", "CONTROL"),
    # ⚠ A DELIBERATELY WRONG FIXTURE: a stale lane table kept to price a gate.
    ("model/a2/_price_stale_lane_table.py", "STALE"),
    # this audit's own table
    ("model/gate_stored_numbers.py", "SITES"),
}


def scrape():
    """Every module-level ALL-CAPS collection literal with >= 3 numbers.

    ⭐ DELIBERATELY LOOSE. Over-reporting is the safe direction for a coverage
    measure: a specification caught here is removed by NAME, in `SPEC_SYMBOLS`,
    where the exclusion is reviewable. A tightened pattern that quietly dropped
    a real stored sweep is the failure this is guarding.
    """
    found = []
    for base in ("model", "test"):
        for d, _subs, files in os.walk(os.path.join(ROOT, base)):
            if any(x in d for x in (".git", "__pycache__", "node_modules")):
                continue
            for f in sorted(files):
                if not f.endswith(".py"):
                    continue
                p = os.path.join(d, f)
                rel = os.path.relpath(p, ROOT).replace(os.sep, "/")
                try:
                    with open(p, encoding="utf-8") as fh:
                        tree = ast.parse(fh.read())
                except Exception:
                    continue
                for node in tree.body:
                    if not isinstance(node, ast.Assign):
                        continue
                    if not isinstance(node.value, (ast.Dict, ast.List,
                                                   ast.Tuple, ast.Set)):
                        continue
                    for t in node.targets:
                        if not isinstance(t, ast.Name):
                            continue
                        if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", t.id):
                            continue
                        try:
                            src = ast.unparse(node.value)
                        except Exception:
                            src = ""
                        nums = re.findall(r"(?<![\w.])\d+(?![\w.])", src)
                        if len(nums) >= 3:
                            found.append((rel, t.id, len(nums)))
    return sorted(set(found))


def check_sites():
    """Each tabled site's symbol must exist, and each RECORD needs a recipe
    file that is really there."""
    bad = []
    for s in SITES:
        p = os.path.join(ROOT, s.path.replace("/", os.sep))
        if not os.path.isfile(p):
            bad.append((s, "the file does not exist"))
            continue
        with open(p, encoding="utf-8") as fh:
            txt = fh.read()
        # ⛔ ANCHORED AT COLUMN 0: a module-level assignment, not a mention in
        # a comment. `gate_ruling_audit`'s lesson -- an anchor that resolves
        # against prose proves the prose, not the code.
        if not re.search(r"(?m)^%s\s*=" % re.escape(s.symbol), txt):
            bad.append((s, "no module-level `%s =` in %s"
                        % (s.symbol, s.path)))
            continue
        if s.kind == RECORD:
            if not s.recipe:
                bad.append((s, "RECORD with NO RECIPE -- the number cannot "
                               "be remade"))
            elif not os.path.isfile(os.path.join(
                    ROOT, s.recipe.replace("/", os.sep))):
                bad.append((s, "RECORD whose recipe file is missing: %s"
                            % s.recipe))
        if s.kind == LEDGER and s.recipe:
            bad.append((s, "LEDGER with a recipe -- if it can be re-run it is "
                           "not a ledger"))
    return bad


def selftest():
    """⛔ PRICE IT (standing rule 3): the gate must reject a bogus anchor, a
    missing file and a recipe-less RECORD."""
    global SITES
    keep = SITES
    rc = 0
    cases = (
        ("a bogus symbol",
         Site("model/a2/gate_j_program.py", "NO_SUCH_SYMBOL_XYZ", LIVE,
              "", "model/a2/gate_j_program.py", "")),
        ("a missing file",
         Site("model/no_such_file_xyz.py", "SWEEP", LIVE, "",
              "model/a2/gate_j_program.py", "")),
        ("a RECORD with no recipe",
         Site("model/a2/gate_j_program.py", "SWEEP", RECORD, "", "", "")),
        ("a RECORD with a missing recipe file",
         Site("model/a2/gate_j_program.py", "SWEEP", RECORD, "",
              "model/no_such_recipe_xyz.sh", "")),
        ("a LEDGER that can be re-run",
         Site("model/a2/bursty.py", "DOUBLE_BUFFER_PREREG", LEDGER, "",
              "test/yosys_check.sh", "")),
    )
    print("  --- must-fire: the checks reject what they claim to ---")
    try:
        for name, site in cases:
            SITES = [site]
            fired = bool(check_sites())
            print("    %-34s %s" % (name, "rejected" if fired
                                    else "*** NOT REJECTED"))
            if not fired:
                rc = 1
        # and a good one must be ACCEPTED, or the checks reject everything
        SITES = [Site("model/a2/gate_j_program.py", "SWEEP", RECORD, "",
                      "model/a2/price_j_sweep.sh", "")]
        ok = not check_sites()
        print("    %-34s %s" % ("a sound RECORD", "accepted" if ok
                                else "*** REJECTED, so the gate rejects all"))
        if not ok:
            rc = 1
    finally:
        SITES = keep
    return rc


def main() -> int:
    rc = 0
    print()
    print("=" * 78)
    print("STORED-NUMBER AUDIT -- which gates compare a number they were told?")
    print("=" * 78)

    by_kind = {LIVE: [], RECORD: [], LEDGER: []}
    for s in SITES:
        by_kind[s.kind].append(s)
    print("  tabled: %d sites -- %d LIVE, %d RECORD, %d LEDGER"
          % (len(SITES), len(by_kind[LIVE]), len(by_kind[RECORD]),
             len(by_kind[LEDGER])))
    print()
    for kind in (RECORD, LIVE, LEDGER):
        print("  === %s ===" % kind)
        for s in by_kind[kind]:
            print("    %s :: %s" % (s.path, s.symbol))
            print("      what   : %s" % s.what)
            print("      recipe : %s" % (s.recipe or "(none -- by design)"))
            print("      source : %s" % s.dated)
            if s.note:
                print("      note   : %s" % s.note)
        print()

    # ---- the anchors and the recipes ------------------------------------
    print("  --- anchors resolve, and every RECORD can be remade ---")
    bad = check_sites()
    if not bad:
        print("    all %d sites: symbol present, recipe runnable" % len(SITES))
    for s, why in bad:
        print("    *** %s :: %s -- %s" % (s.path, s.symbol, why))
        rc = 1

    # ---- coverage, measured ---------------------------------------------
    print()
    print("  --- coverage: scraped vs tabled ---")
    scraped = scrape()
    tabled = {(s.path, s.symbol) for s in SITES}
    unreviewed = [(p, sym, n) for p, sym, n in scraped
                  if (p, sym) not in tabled and (p, sym) not in SPEC_SYMBOLS]
    print("    constant collections carrying >= 3 numbers : %d" % len(scraped))
    print("    tabled as stored numbers                   : %d" % len(tabled))
    print("    excluded by name as specifications         : %d"
          % len(SPEC_SYMBOLS))
    print("    UNREVIEWED                                 : %d"
          % len(unreviewed))
    for p, sym, n in unreviewed:
        print("      *** %s :: %s (%d numbers) -- classify it" % (p, sym, n))
        rc = 1
    # ⛔ A STALE EXCLUSION IS ALSO A FINDING. A name in SPEC_SYMBOLS that the
    # scraper no longer sees means the list is drifting out of contact with
    # the tree, and the next real sweep could be excluded by a name that
    # happens to match.
    seen = {(p, sym) for p, sym, _n in scraped}
    stale = sorted(x for x in SPEC_SYMBOLS if x not in seen)
    if stale:
        print("    *** STALE EXCLUSIONS (named but not found): %d" % len(stale))
        for p, sym in stale:
            print("      *** %s :: %s" % (p, sym))
        rc = 1

    print()
    print("  --- the mechanism, priced ---")
    if selftest():
        rc = 1

    print()
    print("=" * 78)
    print("  STORED-NUMBER AUDIT: %s" % ("PASSED" if rc == 0 else "FAILED"))
    if rc:
        print("    ⛔ A RECORD with no runnable recipe is the SWEEP_SINGLE")
        print("       class: a number that cannot be remade, sitting inside a")
        print("       gate that passes because of it.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
