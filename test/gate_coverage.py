"""THE COVERAGE GATE -- no uncovered RTL point outside a written justification.

⛔⛔ WILSON'S RULING, VERBATIM IN EFFECT: "Every uncovered branch, FSM state,
opcode arm and peer branch gets either a test that reaches it, or a written
reason why it's unreachable, checked like the reset allowlist. It becomes a
gate: new uncovered RTL fails CI unless justified."

⇒ This is that gate. `test/coverage_sweep.sh` produces the measurement over
every bench in `test/benchset.py`; this file adjudicates it against the table
below, and goes RED on an uncovered point nobody has classified.

⚠⚠ WHAT THIS GATE CLAIMS, AND WHAT IT DOES NOT. It claims: no uncovered
line-or-branch point in the design or the peer models outside `CLASSIFIED`. It
does NOT claim the 30 points marked `OWED` are acceptable -- they are DEBT,
each named with the test that would reach it, and listing them is how the debt
stays visible instead of dissolving into a percentage. ⛔ The honest reading of
a green here is "nothing NEW went uncovered", which is exactly the gating
property the ruling asks for, and not "the design is covered".

⛔ "UNCOVERED" IS PER ARM, NOT PER LINE, and reading it as "never ran" would be
flatly wrong for several entries. A branch point is one ARM of a condition:
`fram_i2c.v:235` executes 28 times and `fram_i2c.v:251` 2,845,919 times, and
both appear below because their TRUE arm is never taken. The count is in each
reason where it matters.

⚠ TOGGLE COVERAGE IS RATCHETED, NOT ADJUDICATED PER POINT, and that is a
declared choice rather than an omission. There are ~390 uncovered toggle points
against 37 line/branch points, most of them single bits of wide buses whose top
bits are unreachable by the parameter set (a 4-bit pin index against 12 pins).
Demanding 390 written reasons would bury the 37 that name real behaviour -- the
`gate_reset_audit` lesson in reverse. So toggle is held at a per-file CEILING
that may only fall, and the ruling's named subjects (branches, FSM states,
opcode arms, peer branches) are all line/branch points, which ARE adjudicated.
"""

from __future__ import annotations

import collections
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

DAT = os.environ.get("PE_COVERAGE_DAT", os.path.join(ROOT, "probe_cov",
                                                     "merged.dat"))

# ⛔⛔ THE KEYS ARE LINE NUMBERS AND THEY DRIFT. Adding the `rx_bit` guard
# to `pe_engine.v` moved four anchors by +24 and this gate reported all four
# as NOT IN THE DATA while their new line numbers came back UNCLASSIFIED --
# loudly, from both directions at once, which is the behaviour to keep. A
# coverage point IS identified by file and line, so the fragility cannot be
# designed away; what matters is that a drifted anchor can never read as a
# pass. ⚠ On an RTL edit above a classified line, expect to re-anchor.
#: the subject of the gate: the design, and the peer models Wilson named
SUBJECT = ("src/", "test/fram_")

UNREACHABLE = "UNREACHABLE"
OWED = "OWED"
DEAD_CONFIG = "DEAD_CONFIG"
#: ⛔⛔ A POINT WHOSE COVERAGE STATUS DEPENDS ON THE VERILATOR RELEASE.
#: Established, not assumed: the same 19 arms on 5.020 and 5.032 produce
#: IDENTICAL point totals for every file and IDENTICAL uncovered toggle counts
#: for every file. The whole difference is two branch arms in `pe_engine.v`,
#: which 5.032 credits and 5.020 does not. ⇒ These are exempt from the stale
#: check -- being covered is EXPECTED on some versions -- and they are counted
#: as uncovered, which is the safe direction.
TOOL_DIVERGENT = "TOOL_DIVERGENT"
#: ⚠⚠ TESTED, BUT BY THE UNSWEPT BENCH. A point the cocotb suite EXECUTES and
#: the Verilator sweep never reaches. ⛔ IT IS NOT "OWED": owed means no test
#: reaches it, and this one is reached 48 times. Calling it owed described a
#: gap in ONE BENCH as a gap in the DESIGN.
#: ⛔⛔ AND IT IS NOT SILENTLY DROPPED EITHER, which is the point of giving it
#: a name: the cross-check still reports it, the entry still has to carry a
#: reason, and what it costs is stated -- cocotb is NOT swept across the three
#: rand-reset modes and is NOT ratcheted, so a point resting on it has WEAKER
#: evidence than a swept one. The ruled resolution is still to bring the
#: stimulus into a swept bench; this records the debt honestly until that
#: happens, instead of a red gate or a deleted finding.
COCOTB_ONLY = "COCOTB_ONLY"
#: ⛔⛔ AND EVERY `COCOTB_ONLY` ENTRY MUST NAME THE SWEPT STIMULUS THAT WILL
#: RETIRE IT -- a ruled condition, so the status cannot become a permanent
#: home for a point nobody intends to cover. The reason text has to contain
#: a `test/tb` bench name; `check_reasons` enforces it.
#: ⭐ ITS FIRST AND ONLY MEMBER HAS ALREADY LEFT: `src/project.v` 411 named
#: `test/tb_fifo.v`, that bench was built, and the point is COVERED in the
#: sweep. The class is empty by resolution rather than by never being used.
COCOTB_ONLY_NEEDS = "test/tb"

# ---------------------------------------------------------------------------
# THE CLASSIFICATION. (file, line, kind, arm) -> (status, reason)
# ⛔ An uncovered point that is not here FAILS the gate.
# ⛔ A point here that is now COVERED also fails -- see `check_stale`.
# ---------------------------------------------------------------------------
CLASSIFIED = {
    # ⭐⭐ RETIRED BY ruling (a) item 1, and TWO OF THEM WERE NEVER DEBT.
    #   1143, 1145  the open-drain `pin >= N_UIO` refusal. ⛔ I REPORTED THESE
    #               AS "never fired" AND THAT WAS WRONG: `cfgerr_image.hex` is
    #               `hdr(UO0, UO0, 0, ...)` and `test/test.py` has run it as
    #               `test_config_error_refuses_to_run` all along. They read as
    #               uncovered because the cocotb toplevel `tb.v` is the ONE
    #               bench `benchset.py` excludes. `tb_pinrange +MODE=0` now
    #               runs that image where the sweep can see it, and asserts
    #               both the flag AND that nothing was emitted.
    #   1158, 1352, 1446  the reserved index PIN_NONE on a HEADER, an OP_SHIFT
    #               and an OP_SHIFTIN. These WERE genuine: `build_noop` only
    #               ever put PIN_NONE on an `OP_LEVEL` action, which is why
    #               1339's arm was already covered and these three were not.
    #               `pinnone_image.hex` + `tb_pinrange +MODE=1` reach all three.
    # ⚠ AND THAT ARM FOUND A NEW DEFECT, recorded in the bench header and the
    # spec doc: `pin_in[a_pin]` is read UNGUARDED, so SHIFTIN on PIN_NONE
    # samples out of range and puts X on `ser_d`. Not a coverage point, so it
    # is not in this table -- it is an owed RULING.

    # ---- the tool-divergent point(s) -------------------------------------
    # ⛔ RETIRED BY RULING TF2: the EDF arbiter's serial-loop condition
    # `ready[k] && (!winner_v || edf_key_off[k] < best)` (old line 1021),
    # which 5.020 reported uncovered and 5.032 recorded taken 5,231,510 times.
    # For N_LANES = 5 the select is now a tree (proved equal to that loop,
    # formal/argmin_equiv.sby); the loop survives only in the generate branch
    # for other lane counts, which is not elaborated, so the point no longer
    # exists to classify.
    ("src/pe_engine.v", 2235, "v_branch", "if"): (
        TOOL_DIVERGENT,
        "`if (hdr_done && !prime_unp) primed_q <= 1'b1;` -- the prime scan's "
        "COMPLETION test, which sits AFTER the `for` over lanes, not inside "
        "it. 5.020 reports this arm uncovered; 5.032 records it taken 34 "
        "times on byte-identical stimulus, and the per-file point totals are "
        "the same on both, so the count is being attributed to an adjacent "
        "line of the same statement group. ⚠ I CANNOT RUN 5.020 HERE to say "
        "WHICH line absorbs it, so that part is inference and is labelled as "
        "such; what is measured is the two counts and the equal totals. "
        "⛔⛔ THIS ENTRY WAS MIS-ANCHORED ONCE, AND THE WAY IT HAPPENED IS THE "
        "LESSON. Its original line was 942; the `rx_bit` guard shifted the "
        "file by +24, so the new line is 966 -- but I re-anchored it to 965 by "
        "GREPPING FOR A STATEMENT I REMEMBERED as the anchor instead of "
        "applying the measured shift, and 965 is a different statement "
        "(`l_live[pi] && want_fetch`, inside the loop, covered on both). CI "
        "caught it: `*** UNCLASSIFIED src/pe_engine.v line 966`. Copy the "
        "number out of the artefact; do not reconstruct it from memory."),

    # ---- src/pe_engine.v --------------------------------------------------
    ("src/pe_engine.v", 2320, "v_branch", "else"): (
        UNREACHABLE,
        "H_IDLE (line 1134) with `hdr_done` ALREADY SET. Every assignment that puts the "
        "header FSM into H_IDLE clears `hdr_done` in the same non-blocking "
        "block -- the reset arm (`hst <= H_IDLE` at 1001 beside "
        "`hdr_done <= 1'b0` at 1005) and the `!run` arm (1070 beside 1071). "
        "So the state is never OCCUPIED with the flag set, and the `else` is "
        "the arm of a condition that is true on every entry. ⭐ Checked "
        "structurally by `check_h_idle_clears` below rather than asserted, "
        "because the claim is about two specific lines and would rot."),
    ("src/pe_engine.v", 2486, "v_line", "case"): (
        UNREACHABLE,
        "The prefetch FSM's defensive `default`. `pst` is declared `[2:0]` and "
        "its four encodings P_SCAN/P_REQ/P_WAIT/P_CAP are 3'd0..3'd3, all "
        "handled by name; 3'd4..3'd7 are assigned NOWHERE in the file. "
        "⭐ Verified mechanically by `check_full_case` below, which reads the "
        "encodings out of the source -- a hand-counted enumeration is the sort "
        "of claim that survives the addition of a fifth state."),
    ("src/pe_engine.v", 2930, "v_line", "case"): (
        UNREACHABLE,
        "The opcode `case`'s `default`. ⭐ v2 (Wilson 10-26): the opcode is 5 "
        "bits and the EIGHT BUILT opcodes are named in arms (OP_LEVEL .. "
        "OP_REARM); opcodes N_BUILT_OPS..31 are REFUSED AT LOAD -- "
        "src/project.v `bad_op` tests each action word's opcode as it "
        "streams in and an image holding one sets CONFIG_ERR and never starts "
        "the engine -- so no value that can reach dispatch reaches the "
        "default. Must-fires: gate_v2_equiv's opcode 8 in the first and in the "
        "last action word, both refused. ⭐ Checked by `check_full_case`'s "
        "third mechanism: the arms must be exactly 0..N_BUILT_OPS-1 and the "
        "loader check present, so a primitive built without its arm, or a "
        "limit raised without the loader, makes this waiver false."),
    # ⭐ RETIRED (ruling (a) item 1): the host underrun path at 1627 is now
    # covered by `tb_status +MODE=0`, which starves the TX lanes with `hf_en`
    # never enabled and asserts `lane_underrun` SETS on lanes 0 and 1 and on no
    # other lane, with the lane still LIVE -- the flag must report, never
    # stall. The entry is removed rather than kept, because a stale OWED claim
    # says something is untested when it is tested.
    ("src/pe_engine.v", 3345, "v_line", "case"): (
        UNREACHABLE,
        "The dispatch FSM's defensive `default`. `st` is declared `[1:0]` with "
        "three encodings ST_IDLE/ST_DRIVE/ST_WB = 2'd0..2'd2 at line 666; "
        "2'd3 is assigned nowhere, so it is reachable only by corruption of a "
        "reset-bearing flop. ⚠ The arm stays in the RTL on purpose -- it "
        "returns to ST_IDLE rather than latching -- and `gate_reset_audit` is "
        "what underwrites `st` being reset at all."),

    # ---- src/project.v ----------------------------------------------------
    # ⭐⭐ COVERED NOW, AND IT PASSED THROUGH `COCOTB_ONLY` TO GET HERE.
    # `src/project.v` 411 -- a host PUSH and an engine POP on the SAME queue
    # in one cycle -- was tabled OWED, then the cocotb cross-check reported
    # it EXECUTED 48 times (so nothing was missing, the SWEPT benches could
    # not reach it), then it was tabled COCOTB_ONLY while a directed bench
    # was built, and `test/tb_fifo.v` now reaches it IN THE SWEEP.
    # ⛔ THE INTERIM STATUS DID ITS JOB AND EMPTIED: it kept the point
    # visible and honest instead of being reported as debt that did not
    # exist, and it did not become a permanent home.
    # ⚠ tb_fifo WALKS the push phase rather than computing it, asserts that
    # both pointers flip, the count holds and order is preserved, and
    # FAILS if no phase ever hits the corner.
    # ⭐⭐ DEBT PAID BY THE **OTHER BENCH**, and the cross-check is what
    # found it: `src/project.v` 411 -- a host PUSH and an engine POP landing
    # on the SAME queue in one cycle -- was OWED here, and cocotb executes
    # it 48 TIMES. The gate reported "FALSE GAP" and refused to keep the
    # entry. ⛔ IT ONLY BECAME TRUE WITH THE SHARED BUS MODEL: once cocotb
    # drove the resolved bus instead of a constant, its runs reached a
    # push/pop alignment the Verilator sweep never produces. ⚠ So "OWED"
    # had been describing a gap in ONE bench as a gap in the DESIGN -- which
    # is exactly what the cocotb cross-check exists to catch, and the second
    # false gap it has caught.
    # ⭐ RETIRED (ruling (a) item 1): `tx_full_sticky` at 412 is now set by
    # `tb_status +MODE=1`, which pushes three bytes into QUEUE 2 -- drawn by no
    # lane of `tx_image`, so it fills and is never drained -- shows `tx_cnt[2]`
    # at the depth, and asserts both stored bytes survive the refused third.
    # ⚠ The first draft held the chip in LOAD mode to stop the engine popping
    # and pushed nothing at all: the host strobe IS `ui_in[6]` = `PIN_WR`, so
    # in LOAD mode those pushes went to the image loader.
    # ⭐⭐ RETIRED BY DELETION, and it is the only point in this table that
    # retired that way rather than by a test reaching it. The `DEAD_CONFIG`
    # entry here was `src/project.v` 557, the implicit `else` of
    # `if (RX_SERIAL != 0)`: a parameter overridden NOWHERE in the tree, so the
    # arm was shipped source no configuration executed. It named two honest
    # resolutions -- sweep it as a build arm the way `SPL_CFG = 1` is, or
    # delete the parameter and the arm -- and DELETE was ruled. The parameter,
    # the branch and the rows that froze it in the Part 1 contract and the S2
    # freeze all went together.
    # ⛔ SO `DEAD_CONFIG` NOW HAS NO MEMBERS, and the status is deliberately
    # KEPT in the vocabulary rather than removed with its last user: it is the
    # classification that says "this arm cannot be reached because no build
    # selects it", and the next unexercised parameter needs somewhere to land
    # that is not `UNREACHABLE`. ⚠ An empty class is not a dead one -- it is a
    # class whose only member was resolved, which is the outcome it exists for.

    # ---- the self-clocked arms: redundant-by-construction guards ---------
    # ⛔ ALL FIVE ARE UNREACHABLE **STRUCTURALLY**, not by argument, and each
    # names the enclosing condition that makes it so. They exist because the
    # index gate requires a program-indexed write's guard to be LOCAL (within
    # 60 lines and inside its own case arm), so the clocked arms repeat guards
    # their enclosing conditions already imply. Synthesis folds them; the
    # locality is for the reader and the gate.
    # ⭐ THE SDA HOLD EXPIRY'S RANGE GUARD (ruling H). The expiry writes
    # `pin_out[l_pin[i]]` / `pin_oe[l_pin[i]]` at block level, outside
    # `case (st)`, so none of the dispatch arm's own guards dominate it --
    # which is why it carries its own, and why `gate_program_index` classifies
    # both writes as members of the program-indexed family.
    ("src/pe_engine.v", 3391, "v_branch", "else"): (
        OWED,
        "The `l_pin[i] < N_PINS` guard on the hold expiry. Its `else` is "
        "REACHABLE, not unreachable: a lane may legally name the RESERVED data "
        "index (PIN_NONE = 15), and `pinnone_image.hex` exists precisely to do "
        "that. What no image yet does is name it on a lane that is ALSO "
        "open-drain, clocked, and running a delay greater than SDA_HOLD -- the "
        "three conditions that put a hold in flight at all. ⇒ THE TEST THAT "
        "WOULD REACH IT: a `build_pinnone` variant declaring mode 0, a real "
        "clkpin distinct from the data pin, and `d = 33`, run in a bench with "
        "a bus model (`tb_trace`, not `tb_csat`, because an open-drain clocked "
        "lane parks on an observed rise). ⚠ IT IS OWED RATHER THAN WAIVED "
        "BECAUSE THE GUARD IS NEW AND UNPRICED: every other member of this "
        "family was added after a measured out-of-range read, and a guard that "
        "has never been seen to fire has unknown strength."),
    # ⛔⛔ PAID ONLY BY A DEFECT, LIKE TX5's SEVEN. Until silicon fix #3b every
    # push-pull clocked SHIFTIN consumed a bit it never captured (`uo_out` has
    # no input path, so the observed rise never came), and THAT is what covered
    # this branch on every sweep. With the fix it went dark -- which is the fix
    # working, and also a branch nothing legitimate is known to reach.
    ("src/pe_engine.v", 3104, "v_branch", "if"): (
        OWED,
        "`ck_consume & ~l_ckgot`: a clocked SHIFTIN consumes a bit that was "
        "never captured, and reports it (`clk_stretch_err`). Covered before "
        "silicon fix #3b ONLY by that defect: every push-pull clocked consume "
        "was uncaptured. Why the clean build does not reach it: an open-drain "
        "lane PARKS on the rise after its HIGH phase, so its next dispatch "
        "waits for the capture (reached under `M_CK_NO_PARK`); a stretch "
        "watchdog HALTS the lane rather than letting it consume; a push-pull "
        "capture fires 2-3 cycles after the HIGH writeback (the `ppc` slot), "
        "while the lane's next dispatch is `d` later. ⚠ NOT CLAIMED "
        "UNREACHABLE: a push-pull clocked SHIFTIN with `d` of a few cycles "
        "has not been ruled out and is the candidate stimulus (`tb_cktx`, a "
        "pindiv variant at small d). `M_CKRX_PP_OBSERVED` reaches it."),
    # ⭐ THE UNCLOCKED SITE'S OPEN-DRAIN DIRECT DRIVE (ruling H). Its
    # clocked twin IS covered -- every clocked open-drain image runs at d = 9,
    # so the clamp sends them all down the direct path -- and the asymmetry is
    # the whole reason this one is debt rather than a waiver.
    ("src/pe_engine.v", 2780, "v_branch", "else"): (
        OWED,
        "The `if (l_mode[cur])` inside the UNCLOCKED SHIFT's direct-drive arm, "
        "open-drain side. Reaching it needs an unclocked open-drain SHIFT whose "
        "delay CANNOT fit the SDA hold, because a fitting delay routes to the "
        "hold path instead -- and `i2cframe_image.hex`, the only unclocked "
        "open-drain shifting program, runs at d = 62. ⇒ THE TEST THAT WOULD "
        "REACH IT: `build_i2cframe(d=12)`, which is an ILLEGAL I2C delay and "
        "that is precisely what makes it the right witness -- the clamp exists "
        "for programs like it, and the arm would show the clamp choosing the "
        "old zero-hold behaviour instead of pushing data past the rise. "
        "⚠ NOT waived as unreachable: it is reachable, by exactly the class "
        "of program the clamp was written for, and leaving the clamp's own "
        "fallback untested is how a safety path rots."),
    ("src/pe_engine.v", 2651, "v_branch", "else"): (
        UNREACHABLE,
        "The local `if (pin_real)` inside the SELF-CLOCKED SHIFT's LOW phase. "
        "Its `else` cannot be taken: the enclosing case label is "
        "`OP_SHIFT: if (pin_real)`, so `pin_real` is already true on every "
        "path that reaches here. Written locally anyway because "
        "`model/gate_program_index.py` bounds its guard search at 60 lines and "
        "at the enclosing arm -- and widening that window is refused, since the "
        "gate's own docstring records a `clk_real` 30 lines away falsely "
        "guarding a deliberately unguarded mutant arm."),
    ("src/pe_engine.v", 2684, "v_branch", "else"): (
        UNREACHABLE,
        "The `if (clk_real)` around the LOW phase's CLOCK write. Unreachable "
        "`else`: this block runs only under `ck_shift`, which is DEFINED as "
        "`clk_real & a_lvl & (a_op == OP_SHIFT)` -- so `clk_real` is a "
        "conjunct of the condition that got us here. ⚠ It is still written, "
        "because the guard must be visible at the indexed write rather than "
        "inferred through a wire's definition."),
    ("src/pe_engine.v", 2704, "v_branch", "else"): (
        UNREACHABLE,
        "The same `if (clk_real)` around the HIGH phase's clock write, "
        "unreachable for the identical reason -- `ck_shift` carries "
        "`clk_real`. Both phases guard separately because a guard shared "
        "across two write groups is how the 1.6x refusal first failed: it "
        "suppressed the data write and let the clock write run anyway."),
    ("src/pe_engine.v", 2774, "v_branch", "else"): (
        UNREACHABLE,
        "The local `if (pin_real)` inside the UNCLOCKED SHIFT body. Same "
        "structure as the clocked one at 1621 and unreachable for the same "
        "reason. ⭐ IT WAS ADDED BECAUSE THE INDEX GATE CAUGHT THE EXISTING "
        "CODE: inserting the clocked arm pushed the case label's own guard "
        "more than 60 lines away from five writes that were fine the day "
        "before, which is exactly the drift that window exists to detect."),
    ("src/pe_engine.v", 2904, "v_branch", "if"): (
        UNREACHABLE,
        "`if (ck_shiftin & ack_drv[1]) pin_out[a_pin] <= ack_drv[0];` -- the "
        "TRUE arm cannot be taken in a clean build, because `ack_drv` is "
        "`2'b00` and only `M_ACK_DRIVES_SDA` makes it `2'b11`. ⭐ THE LINE IS "
        "IN THE COMMON PATH ON PURPOSE: keeping it outside the `ifdef` is what "
        "makes that mutant ONE LINE against one, which `gate_mutant_arms` "
        "requires -- an arm that wrapped this write too would wrap more than "
        "its delta. ⚠ So this point is uncovered BY DESIGN and its coverage "
        "would mean the mutant had leaked into the shipped build."),

    # ---- test/fram_i2c.v (the peer model Wilson named) --------------------
    # ⭐⭐ NINE OWED POINTS WERE PAID BY THE SELF-CLOCKED CORPUS, and the gate
    # REFUSED to let their entries linger: "DEBT PAID, ENTRY STALE". They were
    # the I2C peer's clock-stretch counter arms (fram_i2c 235, 251) and most of
    # the SPI peer's COMMAND DECODER (fram_spi 134-160) -- which was the single
    # largest OWED item on the list. The old corpus idiom clocked two payload
    # bits per clock and never completed a byte, so the peers' decoders were
    # never driven past their first state; whole-byte clocked shifts drive them
    # properly. ⚠ THE DEBT WAS NOT PAID BY WRITING A TEST FOR IT. It was paid
    # by fixing a program that had been under-exercising the peer all along,
    # which is worth more than the nine points: it means the earlier "the peer
    # model is exercised" claims were measuring less than they sounded like.
    # ⭐⭐ THE READ TRANSACTION IS PAID (ruling ACK / TX9): the R/W = 1 arm,
    # the shout load, and the read-data presentation (old 207, 208, 239) are
    # covered by `tb_ckack`'s swept arm, which addresses the peer with A1 and
    # reads -- the first program ever to. The gate retired the entries
    # ("DEBT PAID, ENTRY STALE"), as it should.
    # ⭐ RETIRED by ruling (a)2: `P_ALO` is reached by `i2caddr_image.hex`
    # (`dev | addrhi | addrlo`, 3 bytes) under `tb_i2c +TXB=3`, and the claim
    # is stronger than the count -- the bench asserts the peer's assembled
    # address reads 0x0123, from `addrhi 0x01` at P_AHI and `addrlo 0x23` at
    # P_ALO, a value only BOTH phases can produce.
    # ⛔ `P_WDATA` (228, below) STAYS OWED AND IS NOT REACHABLE WITH THIS
    # IDIOM: the framing costs `51 + 60n` bytes, so a fourth byte is 291
    # against a 256-byte store. That is a ruling, not a missing test.
    # (266 -> 281 on 10-21: the PEER_DLY_NS block above it added 15 lines,
    # MEASURED -- the anchor text below moved with it)
    ("test/fram_i2c.v", 281, "v_line", "case"): (
        OWED,
        "⛔ P_WDATA -- SO NO BYTE HAS EVER BEEN WRITTEN INTO THE PEER'S "
        "MEMORY. `mem[addr] <= shin` lives here and its count is 0. The "
        "sigrok-certified transaction reads `Address write 50 | ACK | Data "
        "write 5B | ACK`, and that second byte is consumed by the model as "
        "`addr[AW-1:8]` at P_AHI, not as data. ⚠ THE CERTIFICATION STANDS for "
        "what it claimed -- framing and byte values on the wire, adjudicated "
        "by a foreign decoder -- but the FRAM write itself has never "
        "completed, and the two are easy to conflate. ⇒ One more address byte "
        "and one more data byte in the program reaches this and 223."),
    # ---- test/fram_spi.v --------------------------------------------------
    # ⛔⛔ ONE FINDING, EIGHTEEN POINTS: the SPI peer's ENTIRE command decoder
    # has never executed. `byte_done` never becomes 1 at an `negedge sck` with
    # the part selected, so the `case (phase)` at 124 and everything under it
    # is dark -- WREN, WRDI, RDSR, RDID, READ, WRITE, and the P_AHI/P_ALO/
    # P_DATA phases alike. Bits ARE shifted in (the assembly block at 104 is
    # covered), so the peer is wired up and clocked; it simply never completes
    # a byte. ⚠ THIS IS THE SAME SHAPE AS THE I2C PEER DEFECT sigrok found --
    # a corpus program that drives the bus without assembling a byte the peer
    # accepts -- and it is the largest single item the sweep produced.
    # ⇒ The test: an SPI-master program that clocks eight coherent bits per
    # byte with CS asserted, then a certified decode of it, exactly as the
    # I2C frame was certified. Per-point entries follow so that a partial fix
    # cannot close the family.
    # ⭐⭐ AND THE FAMILY WAS PARTIALLY PAID EXACTLY THAT WAY: the
    # self-clocked corpus now drives WHOLE BYTES through this peer, and SEVEN
    # of the eighteen points went covered -- the READ/WRITE opcode arm, the
    # P_AHI, P_ALO and P_DATA phases, the WRITE arm, and two not-taken forks.
    # The gate refused to let their entries linger ("DEBT PAID, ENTRY
    # STALE"), so they are gone and ELEVEN remain owed. ⛔ THE DEBT WAS NOT
    # PAID BY WRITING A TEST FOR IT: it was paid by fixing a corpus program
    # that had been clocking two payload bits per clock and never completing
    # a byte. That is worth more than the seven points, because it means the
    # earlier "the peer model is exercised" claims were measuring less than
    # they sounded like -- the same shape as the I2C peer defect sigrok found.
    # ⚠ STILL OWED: the taken READ fork and the honoured write-enable latch,
    # which need a program that actually READS and one that WRITES with WREN
    # set -- i.e. the FRAM write and random read that come next.
}

# ⭐⭐ RULING SP1 -- THE DECODER IS PAID BY A REAL TRANSACTION. `corpus_spim` is
# now the MB85RS64V's WREN / WRITE / READ, fed its own opcodes in order, and
# the peer was brought to the datasheet's mode 3 (it was mode-0-only: deselect
# needed an SCK edge, and a transaction's last byte never acted). MEASURED,
# Verilator 5.053: fram_spi went from 11/17 lines and 7/12 branches UNCOVERED
# to 4/18 and 2/18. The eighteen-point "never executed" family and the seven
# points ruling TX5 retracted (paid only by silicon fix #2's misaligned bytes)
# are now paid by the bytes the program MEANT, and their entries are retired.
# What remains is what this program does not send:
_SPI_LEFT = (
    "Not in the swept SPI FRAM transaction (`corpus_spim`: WREN, WRITE, "
    "READ). Owed to a program that sends it -- the pe_asm front-end's SPI "
    "FRAM sequences (RDSR to poll status, WRDI to drop WEL, RDID to "
    "identify). This point is ")
for _k, _what in (
        ((177, "v_line", "case"), "the WRDI opcode arm"),
        ((178, "v_line", "case"), "the RDSR (read status) opcode arm"),
        ((183, "v_line", "case"), "the RDID (read id) opcode arm"),
        ((210, "v_branch", "else"), "a WRITE with WEL clear -- the refused "
                                    "write (the program always WRENs first)"),
        ((212, "v_branch", "else"), "the data phase of an opcode that is "
                                    "neither WRITE nor READ (RDSR/RDID)")):
    CLASSIFIED[("test/fram_spi.v", _k[0], _k[1], _k[2])] = (
        OWED, _SPI_LEFT + _what + ".")
CLASSIFIED[("test/fram_spi.v", 217, "v_line", "case")] = (
    UNREACHABLE,
    "the phase case's `default`: `phase` is 2 bits and P_OP, P_AHI, P_ALO, "
    "P_DATA enumerate all four values, so no phase reaches it. Defensive.")

#: ⚠ TOGGLE CEILINGS -- uncovered toggle points per file, which may only FALL.
#: ⛔ Measured, not chosen: these are the values of the sweep that shipped with
#: this gate. A ratchet seeded from a guess is a ratchet that permits a
#: regression up to the guess.
TOGGLE_CEILING = {
    # ⚠⚠ RAISED 651 -> 728 BY THE SELF-CLOCKED REGISTERS, and a RISE in a
    # ratchet needs a reason rather than a new number. The clocked phase
    # machine adds five per-lane registers -- `l_ckph` (2 bits), `l_ckbit`
    # (4), `l_ckwait`, `l_cksamp`, `l_ckgot` -- across 5 lanes, plus the
    # decode wires. Total toggle points went 2844 -> 3026 (+182) and
    # uncovered 651 -> 728 (+77): the new state is mostly top bits of the
    # bit counter and the per-lane copies for lanes no clocked program uses.
    # ⛔ THIS IS DESIGN GROWTH, NOT A REGRESSION, and the distinction is
    # checkable: no point that was COVERED became uncovered -- the
    # line/branch adjudication above is exhaustive and reports 0 unclassified
    # and 0 newly-dark points. A rise that could not point at new registers
    # would be a regression and would have to be refused.
    # ⚠ 728 -> 737 (+9) FOR THE CLOCK-STRETCH PARK: `l_ckpark` is one more
    # per-lane bit (5 flops) plus the park's decode wires. Same test as the
    # rise before it -- design growth, and checkable because the line/branch
    # adjudication is exhaustive and reports nothing newly dark. ⭐ AND THE
    # SAME RUN CAUGHT A REAL REGRESSION the other way: parking every clocked
    # lane, not just open-drain ones, hung the push-pull SPI master on a clock
    # it drives itself, and four `fram_spi` points the clocked corpus had just
    # PAID went dark again. Recording paid debt is what made that visible.
    # ⚠ 737 -> 819 (+82) FOR THE STRETCH FAULT BOUND: `l_ckwdog` is a 10-bit
    # counter per lane (50 flops) plus its compare and decode. ⛔ THAT IS THE
    # PRICE OF NOT HANGING ON A DEAD BUS, and it is a real cost stated
    # plainly rather than absorbed: the park makes the engine depend on an
    # OBSERVABLE rise, so a bus whose clock never transitions -- a dead board,
    # or a bench that does not model the bus -- would otherwise stall a lane
    # for ever.
    # ⚠ 819 -> 1153 (+334) FOR v2 STEP 2 (the 32-bit word, the 512-byte store),
    # and the sweep now runs --coverage-max-width 512 (the default 256 dropped
    # half of the 320-bit `l_act` from toggle coverage). ⛔ DESIGN GROWTH, NOT
    # A REGRESSION, and checked FIELD BY FIELD against v1-lock's own sweep
    # (10-26): every toggle point v1 covered is covered at its MAPPED v2 bit
    # (v1 bit b -> v2 bit b + 6) on cur_act, w_act, l_act (362 = 362), hw,
    # s_wrdata, wrdata -- 0 lost. The new dark points are: the reserved word
    # bits (0-5 pinb/mod, 30-31 the opcode's top) no v1 image sets; byte
    # addresses' bits 0-1 (the PC steps by 4); bit 8 of the 512-byte store
    # (v1 images fit the bottom half); a_op bits 3-4 (opcodes 8-21 not built);
    # l_base's low bits (bases moved from 30 + 3k to 32 + 4k).
    "src/pe_engine.v": 1153,
    # ⚠ 6 -> 28 (+22) for v2: the wide read's reserved bits (16), the row
    # index's top bits (4: v1 images fit rows 0..31) and wraddr bits 0-1 (4:
    # the engine writes whole words) -- same field-by-field check, 0 lost.
    "src/pe_store.v": 28,
    "src/project.v": 186,
    # ⭐ RATCHETED DOWN BY THE SELF-CLOCKED CORPUS, and the cause is worth
    # recording: the rewritten corpus drives WHOLE BYTES through the peer
    # models instead of two bits per clock, so `fram_spi` went 54 -> 30
    # uncovered toggle points and `fram_i2c` 94 -> 93. The old idiom was
    # not merely verbose -- it was reaching less of the peer.
    # ⛔⛔ RAISED BY RULING TX (measured, Verilator 5.053), each for a stated
    # reason and not to make the gate pass:
    #   fram_i2c 93 -> 98: ruling ACK's LATE-mode registers. `late_n` is 32
    #     bits and the swept arm stretches 300 cycles, so its high bits never
    #     toggle; the request/seen counters likewise only reach a few values.
    #   fram_spi 30 -> 54: the SAME retraction as `_SPI_DRIFT` above. The
    #     toggles the self-clocked corpus "paid" (54 -> 30) were paid by the
    #     pre-fix silicon's MISALIGNED bytes forming READ/WRITE opcodes; with
    #     silicon fix #2 the corpus sends 5B 01 7A C7 and the decoder's
    #     address and data registers go quiet again. Owed to the FRAM programs.
    "test/fram_i2c.v": 98,
    #   fram_spi 54 -> 18 (RATCHETED DOWN, ruling SP1): the real WREN / WRITE /
    #     READ transaction drives the decoder's address, data and output
    #     registers with the bytes the program means.
    "test/fram_spi.v": 18,
}

#: ⛔⛔ EVERY ANCHOR CARRIES ITS SOURCE TEXT (Wilson's ruling). A coverage
#: point is identified by FILE AND LINE, so an edit above it silently
#: re-points the anchor at a different construct -- and that is not
#: hypothetical: the `rx_bit` guard shifted `pe_engine.v` by +24, and when I
#: re-anchored one entry I GREPPED FOR A STATEMENT I REMEMBERED instead of
#: applying the measured shift. It landed on 965 (`l_live[pi] && want_fetch`,
#: inside the lane loop) when the construct was at 966 (`hdr_done &&
#: !prime_unp`, after it). Both lines exist, both are branch points, and the
#: reason text then described the wrong statement. CI caught it; nothing
#: local did.
#: ⇒ The gate reads the anchored line back and requires it to MATCH, so
#: "copy, do not recall" is mechanised instead of remembered.
ANCHOR_TEXT = {
    # ⭐ v2 STEP 2 (10-26): 13 pe_engine.v anchors RE-ANCHORED by their recorded
    # TEXT (not by arithmetic): 12 moved +29 and land exactly on CI run
    # 40326671675's 12 UNCLASSIFIED points; the TOOL_DIVERGENT prime-scan entry
    # moved +30 (2200 -> 2230, a line step 2 removed sits between).
    # ⛔ RULING TF: every pe_engine.v anchor below was RE-ANCHORED by matching
    # its recorded text in the pre-TF file (c8a4126) to the TF file -- each
    # text found once in the shift band (+145 .. +172), the two
    # `if (clk_real) begin` in their original order. The serial-select entry
    # (old 1021) is RETIRED: TF2 replaced that loop with a tree for
    # N_LANES = 5, so the branch is no longer elaborated (see CLASSIFIED).
    ("src/pe_engine.v", 2235):
        "if (hdr_done && !prime_unp) primed_q <= 1'b1;",
    # the self-clocked arms' redundant-by-construction guards. ⭐ TWO PAIRS
    # SHARE THEIR TEXT (`if (pin_real) begin` at 1621/1694, `if (clk_real)
    # begin` at 1630/1641), which is exactly why the anchor is keyed on the
    # LINE and the text is the drift check rather than the identifier.
    ("src/pe_engine.v", 2651):
        "if (pin_real) begin",
    # ⛔ THE TWO RULING-H ENTRIES NEED ANCHORS LIKE EVERY OTHER, and the
    # first version of them did not have any -- so `reanchor.py` could not move
    # them when the hold's own edits shifted the file, and the gate failed on a
    # classification that had slid off its line. The gate already demands this
    # ("Add it to ANCHOR_TEXT"); I had simply not met it.
    ("src/pe_engine.v", 2780):
        "if (l_mode[cur]) begin",
    ("src/pe_engine.v", 3391):
        "if (l_pin[i] < N_PINS[PINW-1:0]) begin",
    ("src/pe_engine.v", 2684):
        "if (clk_real) begin",
    ("src/pe_engine.v", 2704):
        "if (clk_real) begin",
    ("src/pe_engine.v", 2774):
        "if (pin_real) begin",
    ("src/pe_engine.v", 2904):
        "if (ck_shiftin & ack_drv[1]) pin_out[a_pin] <= ack_drv[0];",
    ("src/pe_engine.v", 2320):
        "H_IDLE: if (!hdr_done) begin",
    ("src/pe_engine.v", 3104):
        "if (ck_consume & ~l_ckgot[cur]) begin",
    ("src/pe_engine.v", 2486):
        "default: pst <= P_SCAN;",
    ("src/pe_engine.v", 2930):
        "default: ;",
    ("src/pe_engine.v", 3345):
        "default: st <= ST_IDLE;",
    # `src/project.v` 557 -- `if (RX_SERIAL != 0) begin` -- is gone with the
    # parameter. ⭐ THE ANCHOR IS WHAT MADE THAT SAFE TO DO: the source text
    # was recorded beside the line number, so the deletion had to account for
    # the anchor instead of leaving a live number pointing at whatever moved
    # into line 557.
    ("test/fram_i2c.v", 281):
        "P_WDATA: begin",
    # ruling SP1: what the real WREN/WRITE/READ transaction does not send
    ("test/fram_spi.v", 177):
        "OP_WRDI: begin wel <= 1'b0; drive <= 1'b0; end",
    ("test/fram_spi.v", 178):
        "OP_RDSR: begin",
    ("test/fram_spi.v", 183):
        "OP_RDID: begin shout <= 8'h04; drive <= 1'b1; phase <= P_DATA; end",
    ("test/fram_spi.v", 210):
        "if (wel) mem[addr] <= shin;",
    ("test/fram_spi.v", 212):
        "end else if (opcode == OP_READ) begin",
    ("test/fram_spi.v", 217):
        "default: ;",
}

#: ⛔⛔ EVERY COVERAGE FIGURE IS LABELLED WITH THE TOOL THAT MEASURED IT
#: (Wilson's provenance ruling). A release bump is not neutral here: 5.053
#: emits ~2x the toggle points of 5.032 AND a conditional-expression point
#: class 5.032 lacked, which added an OWED point with the design unchanged. So
#: "29 uncovered" is not a fact about the design on its own -- it is a fact
#: about the design AND the release.
TOOL_LABEL = "Verilator (unrecorded)"

#: ⛔⛔ THE PINNED RELEASE, ASSERTED AND NOT MERELY LABELLED. Labelling was not
#: enough, and the way that showed up is the reason this exists: a sweep run
#: against the distro's 5.032 instead of the pinned binary reported
#:
#:     src/pe_engine.v  1337 total  234 uncov  651 ceiling
#:                                  improved by 417 -- lower the ceiling
#:
#: on EVERY file at once. The ceilings are EXACT POINT COUNTS, so a release
#: that emits half as many points reads as a sweeping improvement -- and the
#: gate's own advice was to ratchet down to it. Accepting that invitation would
#: have frozen wrong-tool numbers into the ratchet permanently, where they
#: would then mis-measure every later run. ⭐ A RATCHET IS ONLY AS GOOD AS THE
#: CONSTANCY OF WHAT IT COUNTS, so the counter is now part of the contract.
#: ⚠ The check is on the MAJOR.MINOR prefix, because the pinned build is a
#: devel revision ("5.053 devel rev v5.052-258-ga419e9157 (mod)") whose full
#: string carries a git hash that moves without the point counts moving.
#: ⛔ RULING V: STATED ONCE, in the resolver (`test/toolchain.py`), and read
#: here -- the pin and the check that enforces it can no longer disagree.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from toolchain import PINNED_VERILATOR as PINNED_TOOL            # noqa: E402

_LINE = re.compile(r"^C '(.*)' (\d+)\s*$")


def parse(path):
    """(aggregated points, record count). Aggregated ACROSS HIERARCHY.

    ⛔⛔ THE AGGREGATION IS THE WHOLE CORRECTNESS OF THIS PARSER.
    `verilator_coverage --write` does NOT sum a point across benches: the
    merged file carries one record per (point, hierarchy), and the hierarchy
    is `tb_csat.dut.u_eng`, `tb_edge.dut.u_eng`, ... one per bench. So a point
    reached only by `tb_edge` appears with count 0 under nine other benches.
    Reading those as uncovered would report nearly every point as dark and
    make the gate's output pure noise -- a check that is wrong in the ALARMING
    direction still has to be fixed before it can be trusted.
    """
    if not os.path.isfile(path):
        return None, 0
    agg = collections.Counter()
    n = 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            m = _LINE.match(ln)
            if not m:
                continue
            n += 1
            f = {}
            for part in m.group(1).split("\x01"):
                kv = part.split("\x02", 1)
                if len(kv) == 2:
                    f[kv[0]] = kv[1]
            agg[(f.get("f", "?"), int(f.get("l", 0)),
                 f.get("page", "?").split("/")[0], f.get("o", ""))] \
                += int(m.group(2))
    return agg, n


def subject(key):
    return key[0].startswith(SUBJECT)


#: the cocotb suite's own coverage, produced by `test/coverage_cocotb.sh`
COCOTB_DAT = os.environ.get(
    # ⛔ R4 #5 (10-23): NO DEFAULT PATH. run_gates exports this only when the
    # cocotb arm produced data THIS run; a default read an earlier run's file
    # whenever the arm failed.
    "PE_COCOTB_DAT", "")


def norm_path(fn):
    """Reduce a coverage record's filename to a repo-relative path.

    ⛔⛔ THE COCOTB RUN RECORDS ABSOLUTE PATHS, because its `make` runs from
    `test/`: `.../test/../src/pe_engine.v`. Two bugs came out of that, and the
    second is the instructive one:
      1. a filter on a `src/` prefix matched NOTHING and reported "cocotb
         covers 0 points" -- implausible for a run that simulated 279,580 ns;
      2. the fix keyed on the literal substring `ProtocolEmulator/`, WHICH IS
         THIS MACHINE'S CHECKOUT DIRECTORY NAME. In CI the repo is
         `protocol-emulator-asic`, so it matched nothing there and the gate
         failed with "the data has NO subject points at all" -- a hardcoded
         local path masquerading as a normaliser.
    ⇒ So it depends on NO directory name: collapse `..`, then keep the tail
    from the LAST segment that is `src` or `test`. That holds for any checkout
    path on any machine.
    """
    fn = fn.replace(chr(92), "/")
    parts = []
    for seg in fn.split("/"):
        if seg == "..":
            if parts:
                parts.pop()
        elif seg not in ("", "."):
            parts.append(seg)
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] in ("src", "test"):
            return "/".join(parts[i:])
    return "/".join(parts)


def check_cocotb(agg) -> int:
    """⛔⛔ NO POINT MAY BE CALLED UNCOVERED IF COCOTB REACHES IT.

    RULING 2. `tb.v` is the one bench the sweep excludes, and that exclusion
    produced TWO FALSE "never fired" gaps that I relayed as silicon findings.
    With the cocotb suite's own coverage in hand the claim is CHECKED instead
    of inferred: any point this gate reports uncovered, which the cocotb suite
    actually executes, is a measurement artefact and fails here.

    ⚠ ABSENT DATA IS REPORTED, NOT PASSED OVER. The arm needs a pinned
    toolchain (cocotb 2.0.1 wants Verilator >= 5.036; the distro has 5.032 and
    CI 5.020), so it cannot run everywhere yet. When the data is missing this
    says so and says what it therefore did NOT check -- it does not quietly
    read as "no false gaps".
    """
    print()
    print("  --- ruling 2: does cocotb reach anything we call uncovered? ---")
    if not os.path.isfile(COCOTB_DAT):
        print("    ⚠ NO COCOTB COVERAGE DATA at %s" % COCOTB_DAT)
        print("      So this run did NOT check for the false-gap class. Produce")
        print("      it with `bash test/coverage_cocotb.sh` (needs the pinned")
        print("      OSS CAD Suite verilator and the Python 3.12 venv).")
        return 0
    coco = collections.Counter()
    with open(COCOTB_DAT, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            m = _LINE.match(ln)
            if not m:
                continue
            f = {}
            for part in m.group(1).split(chr(1)):
                kv = part.split(chr(2), 1)
                if len(kv) == 2:
                    f[kv[0]] = kv[1]
            fn = norm_path(f.get("f", ""))
            if not fn.startswith(SUBJECT):
                continue
            kind = f.get("page", "?").split("/")[0]
            if kind not in ("v_line", "v_branch"):
                continue
            coco[(fn, int(f.get("l", 0)), kind, f.get("o", ""))] += int(m.group(2))
    if not coco:
        print("    *** the data has NO subject points at all, which is a")
        print("        finding rather than a pass: the cocotb suite drives the")
        print("        same RTL. Either the paths no longer normalise or the")
        print("        run emitted nothing.")
        return 1
    uncovered = [k for k, c in agg.items()
                 if c == 0 and subject(k) and k[2] in ("v_line", "v_branch")]
    # ⚠ A point TABLED as COCOTB_ONLY is acknowledged, not rescued -- it is
    # still printed below so it cannot hide, but it does not fail the gate.
    # ⛔ ONLY A TABLED ONE: an untabled rescued point still fails, so this
    # cannot become a way to make the cross-check quiet.
    rescued, tabled = false_gaps(agg, coco, CLASSIFIED)
    for k in tabled:
        print("    ⚠ COCOTB-ONLY  %s line %d %s/%s -- cocotb executes it "
              "%d time(s), the sweep does not"
              % (k[0], k[1], k[2].replace("v_", ""), k[3], coco[k]))
        print("        tabled, so it is not owed debt -- but it rests on the")
        print("        UNSWEPT bench: no rand-reset sweep, no ratchet.")
    print("    cocotb subject points: %d   our uncovered: %d"
          % (len(coco), len(uncovered)))
    for k in rescued:
        print("    *** FALSE GAP  %s line %d %s/%s -- cocotb executes it %d time(s)"
              % (k[0], k[1], k[2].replace("v_", ""), k[3], coco[k]))
        print("        ⛔ This point is TESTED and the sweep cannot see it.")
        print("           Bring the stimulus into a swept bench rather than")
        print("           reporting the point as owed.")
    if not rescued:
        print("    none -- every point we call uncovered is uncovered by")
        print("    cocotb too, so the uncovered set stands on its own.")
    return 1 if rescued else 0


def false_gaps(agg, coco, classified):
    """(rescued, tabled): points WE call uncovered that cocotb executes --
    untabled ones are FALSE GAPS (a failure), ones tabled COCOTB_ONLY are
    acknowledged. check_cocotb and its must-fire both call this (F8,
    meta-test 10-24: the branch had no must-fire, and no data reaches it on
    the dev box at all)."""
    uncovered = [k for k, c in agg.items()
                 if c == 0 and subject(k) and k[2] in ("v_line", "v_branch")]
    hit = sorted(k for k in uncovered if coco.get(k, 0) > 0)
    tabled = [k for k in hit if classified.get(k, (None,))[0] == COCOTB_ONLY]
    return [k for k in hit if k not in tabled], tabled


def point_problems(agg, classified):
    """Uncovered line/branch subject points with no classification. The gate
    and its must-fire both call this (10-22 must-fire audit: the must-fire
    ran a quiet copy)."""
    return sorted(key for key, c in agg.items()
                  if subject(key) and key[2] in ("v_line", "v_branch")
                  and c == 0 and classified.get(key) is None)


def stale_problems(agg, classified):
    """[(kind, key, count)] for every classified entry that must leave or move:
    GONE (a tool-divergent anchor absent from the data), ABSENT (any other
    entry absent), FALSE (UNREACHABLE but covered), PAID (any other covered
    entry). TOOL_DIVERGENT is exempt from "covered" and only from it."""
    out = []
    for key, (st, _why) in sorted(classified.items()):
        c = agg.get(key)
        if st == TOOL_DIVERGENT:
            if c is None:
                out.append(("GONE", key, c))
        elif c is None:
            out.append(("ABSENT", key, c))
        elif c > 0:
            out.append(("FALSE" if st == UNREACHABLE else "PAID", key, c))
    return out


def anchor_problems(classified, anchor_text, root=None):
    """[(kind, f, l, expect, found)]: NOTEXT (a classified anchor with no
    recorded text), ORPHAN (text for a point nobody classifies), MISSING (the
    file is gone), MOVED (the line no longer reads as recorded)."""
    root = ROOT if root is None else root
    out = []
    want = {(f, l) for (f, l, _k, _a) in classified}
    for f, l in sorted(want - set(anchor_text)):
        out.append(("NOTEXT", f, l, None, None))
    for f, l in sorted(set(anchor_text) - want):
        out.append(("ORPHAN", f, l, None, None))
    src = {}
    for (f, l), expect in sorted(anchor_text.items()):
        if f not in src:
            path = os.path.join(root, f)
            if not os.path.isfile(path):
                out.append(("MISSING", f, l, expect, None))
                src[f] = None
            else:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    src[f] = fh.read().splitlines()
        lines = src[f]
        if lines is None:
            continue
        found = (lines[l - 1].strip() if 0 < l <= len(lines)
                 else "<past end of file>")
        if found != expect:
            out.append(("MOVED", f, l, expect, found))
    return out


def check_points(agg) -> int:
    """Every uncovered line/branch point in the subject must be classified."""
    rc = 0
    print()
    print("  --- line and branch points, per file ---")
    tot = collections.Counter()
    unc = collections.Counter()
    uncovered = []
    for key, c in agg.items():
        if not subject(key) or key[2] not in ("v_line", "v_branch"):
            continue
        tot[(key[0], key[2])] += 1
        if c == 0:
            unc[(key[0], key[2])] += 1
            uncovered.append(key)
    print("    %-20s %-9s %7s %7s %8s" % ("file", "kind", "total", "uncov",
                                          "covered"))
    for fk in sorted(tot):
        t, u = tot[fk], unc[fk]
        print("    %-20s %-9s %7d %7d %7.1f%%"
              % (fk[0], fk[1].replace("v_", ""), t, u, 100.0 * (t - u) / t))

    print()
    print("  --- adjudication: %d uncovered point(s), measured with %s ---"
          % (len(uncovered), TOOL_LABEL))
    by_status = collections.Counter()
    for key in sorted(uncovered):
        hit = CLASSIFIED.get(key)
        if hit is not None:
            by_status[hit[0]] += 1
    unclassified = point_problems(agg, CLASSIFIED)
    for st, n in sorted(by_status.items()):
        print("    %-14s %d" % (st, n))
    for key in unclassified:
        print("    *** UNCLASSIFIED  %s line %d %s/%s"
              % (key[0], key[1], key[2].replace("v_", ""), key[3]))
        print("        ⛔ An uncovered point with no entry in `CLASSIFIED`.")
        print("           Wilson's ruling: a test that reaches it, or a")
        print("           WRITTEN reason it is unreachable. Add one.")
        rc = 1
    return rc


def check_stale(agg) -> int:
    """A classified point that is now COVERED must leave the table.

    ⛔ BOTH DIRECTIONS ARE FAILURES, for different reasons. An UNREACHABLE
    point that got covered means the written reason was FALSE -- the most
    important thing this gate can tell anyone, because the reason is the whole
    justification. An OWED point that got covered means the debt was PAID and
    the entry is now a stale claim that something is untested. ⚠ Without this
    the table would only ever grow, and a list that cannot shrink is a list
    nobody prunes.
    """
    rc = 0
    print()
    print("  --- stale entries: classified but now covered ---")
    # ⛔ TOOL_DIVERGENT IS EXEMPT FROM "COVERED", AND ONLY IT -- those points
    # are covered on one Verilator release and not another. ⛔⛔ BUT NOT FROM
    # "ABSENT": the first version skipped both, and a DRIFTED ANCHOR survived
    # in silence (the `rx_bit` guard moved an entry by +24, the point came
    # back absent, and CI -- where that arm reads uncovered -- went red on the
    # new line). The rules live in `stale_problems`, which the must-fire calls.
    for key, (st, _why) in sorted(CLASSIFIED.items()):
        c = agg.get(key)
        if st == TOOL_DIVERGENT and c is not None:
            print("    %-20s line %-5d %s/%-5s tool-divergent (count %s)"
                  % (key[0], key[1], key[2].replace("v_", ""), key[3], c))
    probs = stale_problems(agg, CLASSIFIED)
    stale = sum(1 for kind, _k, _c in probs if kind != "GONE")
    for kind, key, c in probs:
        rc = 1
        where = "%s line %d %s/%s" % (key[0], key[1],
                                       key[2].replace("v_", ""), key[3])
        if kind == "GONE":
            print("    *** ANCHOR IS GONE  %s" % where)
            print("        A tool-divergent entry may be COVERED, but it")
            print("        must still EXIST. Re-anchor it to the line the")
            print("        construct moved to.")
        elif kind == "ABSENT":
            print("    *** NOT IN THE DATA  %s" % where)
            print("        The point does not exist in the merged coverage.")
            print("        Either the line moved, or the sweep no longer")
            print("        builds the file -- a waiver for a point nothing")
            print("        measures is a waiver that can never be retired.")
        elif kind == "FALSE":
            print("    *** THE REASON WAS FALSE  %s (count %d)" % (where, c))
            print("        It was classified UNREACHABLE and a test")
            print("        reached it. The written reason is wrong and")
            print("        the mechanism behind it needs re-reading.")
        else:
            print("    *** DEBT PAID, ENTRY STALE  %s (count %d)" % (where, c))
            print("        Remove it: a stale OWED entry claims")
            print("        something is untested when it is tested.")
    if not stale:
        print("    none -- every classified point is still uncovered")
    return rc


def check_anchors() -> int:
    """Every classified anchor's line must still READ as the recorded text.

    ⛔⛔ THIS IS THE MECHANISED FORM OF "COPY, DO NOT RECALL". A coverage point
    is file-and-line, so an RTL edit above an anchor re-points it at a
    different construct and the gate's own reason text then describes the wrong
    statement -- which happened: the `rx_bit` guard shifted `pe_engine.v` by
    +24 and one entry was re-anchored to 965 (`l_live[pi] && want_fetch`,
    inside the lane loop) when the construct had moved to 966 (`hdr_done &&
    !prime_unp`, after it). Both lines existed and both were branch points, so
    nothing local objected; CI caught it as an UNCLASSIFIED point.

⭐ PRICED WITH A REAL SHIFT, not only a synthetic text swap: inserting ONE
    blank line into `pe_engine.v` makes this name every anchor, and the entry
    for 966 then reports `found: if (l_live[pi] && want_fetch(...))` -- which
    is EXACTLY the statement the mis-anchor had pointed at. The check
    reproduces the slip it was built for.

        ⚠ IT CANNOT CATCH EVERYTHING. If an edit moves an anchor onto a line whose
    text happens to be identical -- two `default: ;` arms, say -- the text
    matches and the anchor is still wrong. The `v_line`/`v_branch` kind and the
    arm name narrow it, and the coverage data itself is the backstop (a drifted
    anchor usually stops resolving at all). What this closes is the case where
    a human re-anchors from memory.
    """
    rc = 0
    print()
    print("  --- anchors still read as recorded ---")
    probs = anchor_problems(CLASSIFIED, ANCHOR_TEXT)
    for kind, f, l, expect, found in probs:
        rc = 1
        if kind == "NOTEXT":
            print("    *** NO RECORDED TEXT  %s line %d" % (f, l))
            print("        A classified anchor with no source text cannot be")
            print("        checked for drift. Add it to ANCHOR_TEXT.")
        elif kind == "ORPHAN":
            print("    *** TEXT FOR A POINT NOBODY CLASSIFIES  %s line %d"
                  % (f, l))
        elif kind == "MISSING":
            print("    *** %s is missing entirely (anchor line %d)" % (f, l))
        else:
            print("    *** ANCHOR MOVED  %s line %d" % (f, l))
            print("        expected: %s" % expect)
            print("        found   : %s" % found)
            print("        ⛔ Re-anchor by applying the MEASURED line shift, not by")
            print("           grepping for a statement you remember. Then update")
            print("           ANCHOR_TEXT and the entry's reason together.")
    ok = len(ANCHOR_TEXT) - sum(1 for p in probs if p[0] in ("MOVED", "MISSING"))
    if rc == 0:
        print("    %d anchors, every one reads as recorded" % ok)
    return rc


def reason_problems(classified):
    """-> dict of problem lists for a CLASSIFIED-shaped dict: cocotb (a
    COCOTB_ONLY entry naming no swept bench), short (< 60 chars), vague
    (boilerplate), unknown (status). THE ONE rule set: check_reasons() and
    its must-fire both call it (10-22 must-fire audit: the must-fire had
    re-typed the length test inline)."""
    BOILER = ("n/a", "todo", "tbd", "unreachable", "not reachable", "see above",
              "obvious", "by design", "")
    out = {"cocotb": [], "short": [], "vague": [], "unknown": []}
    for key, (st, why) in sorted(classified.items()):
        # ⛔ A COCOTB_ONLY entry must NAME the swept bench that will retire
        # it. Without that the status is a parking space, and the whole
        # reason it was ratified is that it is INTERIM.
        if st == COCOTB_ONLY and COCOTB_ONLY_NEEDS not in (why or ""):
            out["cocotb"].append(key)
        w = (why or "").strip()
        if len(w) < 60:
            out["short"].append((key, len(w)))
        if w.lower().rstrip(". ") in BOILER:
            out["vague"].append(key)
        if st not in (UNREACHABLE, OWED, DEAD_CONFIG, TOOL_DIVERGENT,
                      COCOTB_ONLY):
            out["unknown"].append((key, st))
    return out


def check_reasons() -> int:
    """The reasons themselves are checked, as the reset allowlist's are."""
    rc = 0
    print()
    print("  --- the reasons ---")
    p = reason_problems(CLASSIFIED)
    short, vague = p["short"], p["vague"]
    for key in p["cocotb"]:
        print("    *** %s line %d is COCOTB_ONLY but names no swept"
              % (key[0], key[1]))
        print("        stimulus (a `%s...` bench) that will retire it"
              % COCOTB_ONLY_NEEDS)
        rc = 1
    for key, st in p["unknown"]:
        print("    *** %s line %d has unknown status %r" % (key[0], key[1], st))
        rc = 1
    for key, n in short:
        print("    *** REASON TOO SHORT (%d chars)  %s line %d %s/%s"
              % (n, key[0], key[1], key[2].replace("v_", ""), key[3]))
        print("        A one-line reason is an assertion. What is wanted is")
        print("        the MECHANISM: why no stimulus can reach it, or which")
        print("        test would.")
        rc = 1
    for key in vague:
        print("    *** REASON IS BOILERPLATE  %s line %d" % (key[0], key[1]))
        rc = 1
    if not short and not vague:
        print("    %d entries, every reason substantive" % len(CLASSIFIED))
    return rc


def check_pinned_tool_quiet(label) -> int:
    """1 if `label` is not the pinned release. Shared by the gate and its
    must-fire so the two cannot drift apart.

    ⛔ TOKEN EQUALITY, NOT A PREFIX, and the must-fire is what forced it: the
    first version of this said `label.startswith(PINNED_TOOL)`, which accepts
    "Verilator 5.0531" -- a release that would emit its own point counts while
    reading as the pin.
    """
    want = PINNED_TOOL.split()
    got = label.split()
    if len(got) < 2 or len(want) < 2:
        return 1
    return 0 if (got[0] == want[0] and got[1] == want[1]) else 1


def check_pinned_tool(label) -> int:
    """The sweep must have been taken with the PINNED release.

    ⛔ RED, NOT A WARNING, and the difference matters: the toggle ceilings are
    exact point counts, so data from another release does not merely carry a
    caveat -- it makes every ceiling verdict in this run meaningless, in the
    direction that reads as good news. See PINNED_TOOL.
    """
    print()
    print("  --- the sweep's tool, against the pin ---")
    if label.startswith("Verilator (unrecorded"):
        print("    *** the tool is UNRECORDED, so it cannot be checked against")
        print("        the pin. Re-run test/coverage_sweep.sh, which writes")
        print("        sweep_env.txt beside the data.")
        return 1
    if check_pinned_tool_quiet(label):
        print("    *** %s produced this data; the pin is %s"
              % (label, PINNED_TOOL))
        print("        ⛔ The toggle ceilings are EXACT POINT COUNTS measured")
        print("           at the pin. On 5.032 every file reads 'improved --")
        print("           lower the ceiling', because that release emits about")
        print("           half the toggle points. Ratcheting to those numbers")
        print("           would freeze a wrong-tool count into the ratchet.")
        print("        ⇒ export PE_VERILATOR=<pinned verilator> and re-sweep.")
        return 1
    print("    %-44s ok (pin %s)" % (label, PINNED_TOOL))
    return 0


def check_toggle(agg) -> int:
    """Toggle coverage is ratcheted per file: the ceiling may only fall."""
    rc = 0
    print()
    print("  --- toggle, against the declared ceiling ---")
    unc = collections.Counter()
    tot = collections.Counter()
    for key, c in agg.items():
        if not subject(key) or key[2] != "v_toggle":
            continue
        tot[key[0]] += 1
        if c == 0:
            unc[key[0]] += 1
    print("    %-20s %7s %7s %8s %s" % ("file", "total", "uncov", "ceiling",
                                        "verdict"))
    for fn in sorted(tot):
        ceil = TOGGLE_CEILING.get(fn)
        u = unc[fn]
        if ceil is None:
            print("    %-20s %7d %7d %8s *** NO CEILING DECLARED"
                  % (fn, tot[fn], u, "-"))
            rc = 1
            continue
        if u > ceil:
            v = "*** ROSE by %d" % (u - ceil)
            rc = 1
        elif u < ceil:
            v = "improved by %d -- lower the ceiling" % (ceil - u)
        else:
            v = "ok"
        print("    %-20s %7d %7d %8d %s" % (fn, tot[fn], u, ceil, v))
    for fn in sorted(set(TOGGLE_CEILING) - set(tot)):
        print("    %-20s %7s %7s %8d *** NOT MEASURED"
              % (fn, "-", "-", TOGGLE_CEILING[fn]))
        print("        A ceiling for a file the sweep does not cover is a")
        print("        number that can never be checked.")
        rc = 1
    return rc


# ---------------------------------------------------------------------------
# THE STRUCTURAL CHECKS BEHIND TWO `UNREACHABLE` REASONS.
# ⛔ A reason that says "all eight opcodes are handled" is a COUNT, and this
# project has a rule about counts: name the thing and check it, because the
# count still looks about right after a ninth is added.
# ---------------------------------------------------------------------------
def _encodings(src):
    """name -> (value, width) for every sized localparam constant.

    ⛔ v2 (Wilson 10-26): the opcodes are now `localparam [OP_W-1:0] OP_X =
    n;` -- a SYMBOLIC width and a plain value -- and this parser, which read
    only `[2:0] ... 3'dN`, found NONE of them and said "encodings=0": a check
    reading nothing, the hollow pattern. The width may be `N` or `NAME-1`
    (NAME a `localparam integer`), the value `W'dN` or `N`."""
    ints = {m.group(1): int(m.group(2)) for m in re.finditer(
        r"localparam\s+integer\s+([A-Za-z_]\w*)\s*=\s*(\d+)\s*[;,]", src)}
    out = {}
    for m in re.finditer(r"localparam\s*\[([^\]:]+):0\]\s*(.+?);", src, re.S):
        w = m.group(1).strip()
        if re.fullmatch(r"\d+", w):
            width = int(w) + 1
        else:
            mm = re.fullmatch(r"([A-Za-z_]\w*)\s*-\s*1", w)
            if not mm or mm.group(1) not in ints:
                continue
            width = ints[mm.group(1)]
        for a in re.finditer(r"([A-Za-z_][A-Za-z_0-9]*)\s*=\s*(?:\d+'d)?(\d+)\b",
                             m.group(2)):
            out[a.group(1)] = (int(a.group(2)), width)
    return out


def _load_guard():
    """(N_BUILT_OPS from project.v, the loader's refusal present?) -- the
    third mechanism's evidence, read from the RTL (Wilson 10-26)."""
    with open(os.path.join(ROOT, "src", "project.v"), encoding="utf-8",
              errors="replace") as fh:
        pv = fh.read()
    m = re.search(r"localparam\s+integer\s+N_BUILT_OPS\s*=\s*(\d+)\s*;", pv)
    present = ("uio_q1[7 -: OP_W_T] >= N_BUILT_OPS[OP_W_T-1:0]" in pv
               and re.search(r"\bcfg_err_any\s*=.*\bbad_op\b", pv) is not None
               and re.search(r"\beng_run\s*=.*~bad_op\b", pv) is not None)
    return (int(m.group(1)) if m else None), present


def _case_arms(lines, default_line):
    """(selector, [arm labels]) for the `case` enclosing a `default:` line.

    ⛔ WHY THE LABELS ARE PARSED PER LINE AND SPLIT ON COMMAS. The first
    version of this check used one regex over the whole file and captured only
    the FIRST name of a multi-label arm, so `OP_LEVEL, OP_START, OP_STOP:` and
    `OP_ARM, OP_REARM:` read as two opcodes instead of five. It then declared
    this file's own `UNREACHABLE` reason false. ⚠ A structural check that is
    wrong in the alarming direction is still wrong, and it nearly bought a
    rewrite of a waiver that was correct.
    """
    di = default_line - 1
    indent = len(lines[di]) - len(lines[di].lstrip())
    sel, start = None, None
    for i in range(di - 1, -1, -1):
        m = re.match(r"^(\s*)case\s*\(\s*([A-Za-z_][\w]*)\s*\)", lines[i])
        if m and len(m.group(1)) < indent:
            sel, start = m.group(2), i
            break
    if sel is None:
        return None, []
    arms = []
    depth = 0
    for i in range(start + 1, len(lines)):
        ln = lines[i]
        if re.match(r"^\s*case\s*\(", ln):
            depth += 1
            continue
        if re.match(r"^\s*endcase", ln):
            if depth == 0:
                break
            depth -= 1
            continue
        if depth:
            continue
        m = re.match(r"^\s*([A-Za-z_][\w]*(?:\s*,\s*[A-Za-z_][\w]*)*)\s*:", ln)
        if m:
            for name in m.group(1).split(","):
                arms.append(name.strip())
    return sel, arms


def check_full_case() -> int:
    """The `default is unreachable` reasons, checked against the encodings.

    ⛔ THE CLAIM IS NOT "ALL THE NAMED STATES ARE HANDLED" -- that is a count,
    and a count still looks about right after a ninth encoding is added. The
    claim is that the arms cover the SELECTOR'S WHOLE SPACE: a 3-bit opcode
    with eight named arms leaves no value for the default. So the check
    resolves each arm label to its numeric encoding and compares the set
    against `{0 .. 2**width-1}`.
    """
    rc = 0
    print()
    print("  --- the `default is unreachable` reasons, checked structurally ---")
    path = os.path.join(ROOT, "src", "pe_engine.v")
    with open(path, encoding="utf-8", errors="replace") as fh:
        src = fh.read()
    lines = src.splitlines()
    enc = _encodings(src)
    bare = re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", src, flags=re.S))
    # ⛔ THE SAME MEASURED SHIFT AS THE ANCHORS ABOVE. These are the three
    # `default` arms whose UNREACHABILITY rests on the case being FULL, and
    # they moved with the self-clocked arms: 1296 -> 1476, 1502 -> 1787,
    # 1701 -> 2079. ⚠ A stale number here degrades silently to "no enclosing
    # case found", which is why the gate says that out loud rather than
    # skipping the check. Ruling TF moved them again: 1810 -> 1971,
    # 2249 -> 2410, 2632 -> 2793 (the same text match as ANCHOR_TEXT), and
    # TF2-R again: 1971 -> 2033, 2410 -> 2475, 2793 -> 2858.
    # v2 step 2 (10-26): 2452 -> 2481, 2896 -> 2925, 3311 -> 3340 -- the same
    # +29 text match as ANCHOR_TEXT (each line read back: the `default:` arm)
    for line in (2486, 2930, 3345):
        sel, arms = _case_arms(lines, line)
        if sel is None:
            print("    line %-5d *** no enclosing `case` found -- the waiver's"
                  % line)
            print("              mechanism no longer describes the code")
            rc = 1
            continue
        vals, widths, unknown = set(), set(), []
        for a in arms:
            if a == "default":
                continue
            if a in enc:
                vals.add(enc[a][0])
                widths.add(enc[a][1])
            else:
                unknown.append(a)
        width = max(widths) if widths else None
        space = (1 << width) if width else None
        full = space is not None and vals == set(range(space))
        # ⛔⛔ TWO DIFFERENT MECHANISMS MAKE A `default` UNREACHABLE, and
        # testing only the first declared this file's own correct reasons
        # false. `a_op` is a 3-bit field with all EIGHT values named, so no
        # input reaches the default. `st` is 2 bits with THREE states and
        # `pst` 3 bits with FOUR: their unnamed encodings exist, and what
        # makes the default unreachable is that NOTHING EVER ASSIGNS ONE.
        # ⇒ So the second mechanism is checked on its own terms: every
        # assignment to the selector must write a named encoding. ⚠ This is
        # reachability FROM RESET and nothing more -- a corrupted flop still
        # lands in the default, which is why the arm stays in the RTL and why
        # `gate_reset_audit` underwriting the selector's reset matters.
        # ⚠ COMMENTS STRIPPED FIRST. `[^;]+` ran past `st <= ST_IDLE;`'s
        # trailing `//` comment and on to the next semicolon, so the RHS came
        # back as the comment prose and read as an unnamed encoding.
        assigns = re.findall(r"\b%s\s*<=\s*([^;]+);" % re.escape(sel), bare)
        bad_assign = []
        for rhs in assigns:
            r = rhs.strip()
            if r in enc and enc[r][0] in vals:
                continue
            bad_assign.append(r)
        closed = not bad_assign and bool(assigns)
        # ⭐ THE THIRD MECHANISM (Wilson 10-26): the opcode is 5 bits on v2 and
        # only the BUILT opcodes have arms -- the rest cannot reach the
        # default because the LOADER refuses any image holding one (project.v
        # `bad_op`: CONFIG_ERR, the engine never starts). It holds only if the
        # named arms are EXACTLY 0..N_BUILT_OPS-1, project.v's N_BUILT_OPS is
        # pe_isa's, and the refusal is really in the RTL; its must-fires
        # (opcode 8 in the first and the last word) live in gate_v2_equiv.
        guarded = False
        if not (full or closed) and sel == "a_op":
            import pe_isa
            nb, present = _load_guard()
            guarded = (present and nb == pe_isa.N_BUILT_OPS
                       and vals == set(range(nb)))
        ok = full or closed or guarded
        how = ("every encoding named" if full
               else "every assignment writes a named arm" if closed
               else "every BUILT opcode named; the rest refused at load"
               if guarded else "NEITHER")
        print("    line %-5d sel=%-6s arms=%-2d encodings=%-2d space=%-4s "
              "assigns=%-2d %s"
              % (line, sel, len(arms), len(vals), space if space else "?",
                 len(assigns), ("%s  ok" % how) if ok else "*** %s" % how))
        if unknown:
            print("              arms with no sized localparam: %s"
                  % ", ".join(sorted(set(unknown))))
        if not ok:
            for r in sorted(set(bad_assign))[:6]:
                print("              assigns `%s`, which is not a named arm"
                      % r[:60])
            print("        ⛔ The `default` waiver for this case claims it")
            print("           cannot be reached. Neither mechanism holds: the")
            print("           arms do not cover the selector's space AND an")
            print("           assignment can write a value no arm names. The")
            print("           written reason is false.")
            rc = 1
    return rc


def check_h_idle_clears() -> int:
    """The 1110 waiver's mechanism: every entry to H_IDLE clears `hdr_done`."""
    print()
    print("  --- the H_IDLE waiver's mechanism ---")
    path = os.path.join(ROOT, "src", "pe_engine.v")
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()
    sites = [i + 1 for i, l in enumerate(lines)
             if re.search(r"hst\s*<=\s*H_IDLE", l)]
    rc = 0
    for ln in sites:
        near = "\n".join(lines[max(0, ln - 6):ln + 6])
        ok = re.search(r"hdr_done\s*<=\s*1'b0", near) is not None
        print("    hst <= H_IDLE at line %-5d %s"
              % (ln, "clears hdr_done nearby  ok" if ok
                 else "*** NO hdr_done clear within 6 lines"))
        if not ok:
            rc = 1
    if not sites:
        print("    *** no `hst <= H_IDLE` found at all -- the waiver's")
        print("        mechanism has been restructured and its reason no")
        print("        longer describes the code.")
        rc = 1
    return rc


def selftest(agg) -> int:
    """⛔ PRICE THE GATE. Each arm is the failure it is meant to catch."""
    rc = 0
    print()
    print("  --- must-fire: the gate rejects what it claims to ---")
    # (1) an uncovered point with no classification
    fake = dict(agg)
    fake[("src/pe_engine.v", 999999, "v_branch", "if")] = 0
    saved = dict(CLASSIFIED)
    try:
        bad = bool(point_problems(fake, CLASSIFIED))
    finally:
        CLASSIFIED.clear()
        CLASSIFIED.update(saved)
    print("    %-52s %s" % ("an unclassified uncovered point is rejected",
                            "ok" if bad else "*** ACCEPTED"))
    if not bad:
        rc = 1
    # (2) a classified point that is covered
    # ⛔ A NON-DIVERGENT key: the gate exempts TOOL_DIVERGENT from "covered",
    # so a divergent key here would test a rule the gate does not have
    fake2 = dict(agg)
    key = next(k for k, (st, _w) in CLASSIFIED.items() if st != TOOL_DIVERGENT)
    fake2[key] = 7
    bad2 = any(kind in ("FALSE", "PAID") and k == key
               for kind, k, _c in stale_problems(fake2, CLASSIFIED))
    print("    %-52s %s" % ("a covered point still in the table is rejected",
                            "ok" if bad2 else "*** ACCEPTED"))
    if not bad2:
        rc = 1
    # (2b) ⛔ A TOOL_DIVERGENT ENTRY WHOSE ANCHOR NO LONGER EXISTS. This is
    # the arm the `rx_bit` line shift earned: the exemption for "covered" had
    # also exempted "absent", so a drifted anchor passed in silence here while
    # CI, on a toolchain where that arm reads uncovered, would have gone red on
    # its new line number.
    probe_key = ("src/pe_engine.v", 999998, "v_branch", "if")
    saved2 = dict(CLASSIFIED)
    CLASSIFIED[probe_key] = (TOOL_DIVERGENT, "x" * 80)
    try:
        gone = ("GONE", probe_key, None) in stale_problems(agg, CLASSIFIED)
    finally:
        CLASSIFIED.clear()
        CLASSIFIED.update(saved2)
    print("    %-52s %s" % ("a tool-divergent entry with a dead anchor is rejected",
                            "ok" if gone else "*** ACCEPTED"))
    if not gone:
        rc = 1
    # (2c) ⛔ AN ANCHOR WHOSE LINE NO LONGER READS AS RECORDED. Simulated by
    # pointing a recorded text at a line that certainly does not match, which
    # is what a shift above the anchor produces.
    saved3 = dict(ANCHOR_TEXT)
    ANCHOR_TEXT[("src/pe_engine.v", 1)] = "this is not what line 1 says"
    try:
        moved = any(p[0] == "MOVED" and p[1:3] == ("src/pe_engine.v", 1)
                    for p in anchor_problems(CLASSIFIED, ANCHOR_TEXT))
    finally:
        ANCHOR_TEXT.clear()
        ANCHOR_TEXT.update(saved3)
    print("    %-52s %s" % ("an anchor whose line text changed is rejected",
                            "ok" if moved else "*** ACCEPTED"))
    if not moved:
        rc = 1
    # (2e) ⛔ F8 (meta-test, 10-24): THE FALSE-GAP BRANCH. No cocotb data
    # reaches it on the dev box (WSL has no cocotb), so it had never run --
    # priced here on planted data so the branch is known to work when it does.
    pt = ("src/pe_engine.v", 999997, "v_line", "")
    fake_agg = dict(agg)
    fake_agg[pt] = 0
    resc, _t = false_gaps(fake_agg, {pt: 4}, CLASSIFIED)
    saved4 = dict(CLASSIFIED)
    CLASSIFIED[pt] = (COCOTB_ONLY, "x" * 80)
    try:
        resc2, tab2 = false_gaps(fake_agg, {pt: 4}, CLASSIFIED)
    finally:
        CLASSIFIED.clear()
        CLASSIFIED.update(saved4)
    for what, ok in (("an uncovered point cocotb executes is a FALSE GAP",
                      resc == [pt]),
                     ("... tabled COCOTB_ONLY it is acknowledged, not failed",
                      resc2 == [] and tab2 == [pt])):
        print("    %-52s %s" % (what, "ok" if ok else "*** MISSED"))
        if not ok:
            rc = 1
    # (2d) ⛔ THE PATH NORMALISER, ON EVERY SPELLING IT MUST HANDLE. It was
    # keyed on this machine's checkout directory name once, matched nothing in
    # CI, and the gate failed with "no subject points at all". A normaliser
    # that depends on where the repo happens to live is not one.
    cases = (
        ("/mnt/d/ProtocolEmulator/test/../src/pe_engine.v", "src/pe_engine.v"),
        ("/home/runner/work/protocol-emulator-asic/"
         "protocol-emulator-asic/test/../src/project.v", "src/project.v"),
        ("/home/runner/work/protocol-emulator-asic/"
         "protocol-emulator-asic/test/tb.v", "test/tb.v"),
        ("src/pe_store.v", "src/pe_store.v"),
        ("/some/src/checkout/test/fram_i2c.v", "test/fram_i2c.v"),
    )
    bad = [(i, norm_path(i), w) for i, w in cases if norm_path(i) != w]
    print("    %-52s %s (%d spellings)"
          % ("the path normaliser handles every checkout spelling",
             "ok" if not bad else "*** WRONG", len(cases)))
    for i, got, want in bad:
        print("        %s -> %s, wanted %s" % (i, got, want))
        rc = 1
    # (3) a short reason
    # ⛔ HOLLOW UNTIL 10-22 (must-fire audit): this checked len("because.") < 60
    # inline. It now runs the gate's own rule set on the probe.
    probe = {("x.v", 1, "v_line", "case"): (UNREACHABLE, "because.")}
    short = bool(reason_problems(probe)["short"])
    print("    %-52s %s" % ("a one-line reason is rejected",
                            "ok" if short else "*** ACCEPTED"))
    if not short:
        rc = 1
    # (3b) ⛔⛔ THE PIN ITSELF, priced on the release that actually fooled it.
    # A guard added after a near miss and never mutated is the shape this
    # project keeps finding, so each arm must fail FOR ITS OWN REASON.
    for label, want_fail in (
            ("Verilator 5.053", False),
            ("Verilator 5.032", True),       # what the distro gives, the near miss
            ("Verilator 5.036", True),       # cocotb's floor, still not the pin
            ("Verilator 5.0531", True),      # ⛔ a prefix that must NOT pass
            ("Verilator (unrecorded)", True),
            ("Icarus 12.0", True)):
        got = bool(check_pinned_tool_quiet(label))
        ok = (got == want_fail)
        print("    %-52s %s"
              % ("tool pin: %-24s -> %s" % (label,
                                            "REJECT" if want_fail else "accept"),
                 "ok" if ok else "*** wanted the other verdict"))
        if not ok:
            rc = 1
    # (4) ⛔ THE PARSER ITSELF, priced on the aggregation it exists for. A
    # point that IS covered must read as covered -- if the hier aggregation
    # broke, everything would read uncovered and the gate would be loud and
    # useless.
    covered = sum(1 for k, c in agg.items()
                  if subject(k) and k[2] in ("v_line", "v_branch") and c > 0)
    total = sum(1 for k in agg if subject(k)
                and k[2] in ("v_line", "v_branch"))
    ok = total > 0 and covered > total // 2
    print("    %-52s %s (%d of %d covered)"
          % ("the parser reads most subject points as COVERED",
             "ok" if ok else "*** SUSPECT", covered, total))
    if not ok:
        print("        ⛔ Fewer than half the points read as covered, which")
        print("           is what a broken hierarchy aggregation looks like.")
        rc = 1
    return rc


def main() -> int:
    print()
    print("=" * 78)
    print("COVERAGE GATE -- no uncovered RTL point outside a written reason")
    print("=" * 78)
    print("  data : %s" % DAT)
    agg, n = parse(DAT)
    if agg is None:
        print()
        print("  *** NO COVERAGE DATA at %s" % DAT)
        print("      Run `bash test/coverage_sweep.sh` first (it needs")
        print("      verilator; on this box that means WSL). ⛔ This is a")
        print("      FAILURE and not a skip: a coverage gate that passes")
        print("      when the measurement is absent is the exact shape of")
        print("      a guard that passes because of what it guards.")
        return 1
    print("  records: %d   distinct points: %d" % (n, len(agg)))
    # ⛔ THE TOOL THAT PRODUCED THE DATA, PRINTED WHERE THE VERDICT IS READ.
    # The toggle ceilings are exact point counts and a Verilator release can
    # emit a different number of them, so a ceiling breach caused by a version
    # change must not be indistinguishable from a regression.
    global TOOL_LABEL
    env = os.path.join(os.path.dirname(DAT), "sweep_env.txt")
    if os.path.isfile(env):
        with open(env, encoding="utf-8", errors="replace") as fh:
            for ln in fh.read().strip().splitlines():
                t = ln.strip()
                print("  %s" % t)
                if t.startswith("Verilator "):
                    TOOL_LABEL = " ".join(t.split()[:2])
    else:
        print("  ⚠ no sweep_env.txt beside the data -- the tool version that")
        print("    produced it is unrecorded, so a toggle-ceiling breach")
        print("    cannot be told from a version difference.")
    rc = 0
    rc |= check_pinned_tool(TOOL_LABEL)
    rc |= check_points(agg)
    rc |= check_cocotb(agg)
    rc |= check_stale(agg)
    rc |= check_anchors()
    rc |= check_reasons()
    rc |= check_full_case()
    rc |= check_h_idle_clears()
    rc |= check_toggle(agg)
    rc |= selftest(agg)
    print()
    print("=" * 78)
    print("  GATE coverage: %s" % ("PASSED" if rc == 0 else "FAILED"))
    owed = sum(1 for s, _ in CLASSIFIED.values() if s == OWED)
    dead = sum(1 for s, _ in CLASSIFIED.values() if s == DEAD_CONFIG)
    print("    ⚠ PASSED means NOTHING NEW went uncovered. It does not mean")
    print("      the design is covered: %d points are OWED (debt, each named "
          "with" % owed)
    print("    ⚠ ALL FIGURES ABOVE -- uncovered, OWED, and every toggle")
    print("      ceiling -- are relative to %s. A release bump can add or" % TOOL_LABEL)
    print("      reshape points without the design changing, and has.")
    print("      the test that would reach it) and %d is dead configuration"
          % dead)
    print("      awaiting a ruling. The debt is the point of the list -- it")
    print("      is visible instead of inside a percentage.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
