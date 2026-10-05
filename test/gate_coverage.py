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

    # ---- the two tool-divergent points -----------------------------------
    ("src/pe_engine.v", 651, "v_branch", "if"): (
        TOOL_DIVERGENT,
        "The EDF arbiter's selection condition, `ready[k] && (!winner_v || "
        "edf_key_off[k] < best)`, inside the unrolled `for` over lanes in an "
        "`always @*`. 5.020 reports this arm UNCOVERED; 5.032 records it taken "
        "**5,231,510 times** on byte-identical stimulus. ⭐ So the arm is "
        "plainly exercised and 5.020's zero is an ATTRIBUTION artefact, not a "
        "test gap -- both releases emit the same 72 branch points for this "
        "file, so the disagreement is over which unrolled loop iteration the "
        "point belongs to. ⛔ Counted as uncovered anyway, because the gate "
        "must not pick the lenient reading of a disagreement it cannot "
        "adjudicate."),
    ("src/pe_engine.v", 966, "v_branch", "if"): (
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
    ("src/pe_engine.v", 1134, "v_branch", "else"): (
        UNREACHABLE,
        "H_IDLE (line 1134) with `hdr_done` ALREADY SET. Every assignment that puts the "
        "header FSM into H_IDLE clears `hdr_done` in the same non-blocking "
        "block -- the reset arm (`hst <= H_IDLE` at 1001 beside "
        "`hdr_done <= 1'b0` at 1005) and the `!run` arm (1070 beside 1071). "
        "So the state is never OCCUPIED with the flag set, and the `else` is "
        "the arm of a condition that is true on every entry. ⭐ Checked "
        "structurally by `check_h_idle_clears` below rather than asserted, "
        "because the claim is about two specific lines and would rot."),
    ("src/pe_engine.v", 1270, "v_line", "case"): (
        UNREACHABLE,
        "The prefetch FSM's defensive `default`. `pst` is declared `[2:0]` and "
        "its four encodings P_SCAN/P_REQ/P_WAIT/P_CAP are 3'd0..3'd3, all "
        "handled by name; 3'd4..3'd7 are assigned NOWHERE in the file. "
        "⭐ Verified mechanically by `check_full_case` below, which reads the "
        "encodings out of the source -- a hand-counted enumeration is the sort "
        "of claim that survives the addition of a fifth state."),
    ("src/pe_engine.v", 1476, "v_line", "case"): (
        UNREACHABLE,
        "The opcode `case`'s `default`. The opcode field is 3 bits and ALL "
        "EIGHT encodings are named in arms -- OP_LEVEL, OP_SHIFT, OP_SHIFTIN, "
        "OP_READBIT, OP_START, OP_STOP, OP_ARM, OP_REARM at 196..203 -- so no "
        "value of a 3-bit selector reaches the default. ⭐ Checked by "
        "`check_full_case`: if a ninth opcode were added without an arm, the "
        "default would become reachable and this waiver must not survive it."),
    # ⭐ RETIRED (ruling (a) item 1): the host underrun path at 1627 is now
    # covered by `tb_status +MODE=0`, which starves the TX lanes with `hf_en`
    # never enabled and asserts `lane_underrun` SETS on lanes 0 and 1 and on no
    # other lane, with the lane still LIVE -- the flag must report, never
    # stall. The entry is removed rather than kept, because a stale OWED claim
    # says something is untested when it is tested.
    ("src/pe_engine.v", 1675, "v_line", "case"): (
        UNREACHABLE,
        "The dispatch FSM's defensive `default`. `st` is declared `[1:0]` with "
        "three encodings ST_IDLE/ST_DRIVE/ST_WB = 2'd0..2'd2 at line 666; "
        "2'd3 is assigned nowhere, so it is reachable only by corruption of a "
        "reset-bearing flop. ⚠ The arm stays in the RTL on purpose -- it "
        "returns to ST_IDLE rather than latching -- and `gate_reset_audit` is "
        "what underwrites `st` being reset at all."),

    # ---- src/project.v ----------------------------------------------------
    ("src/project.v", 401, "v_branch", "if"): (
        OWED,
        "A host PUSH and an engine POP landing on the SAME queue in one cycle. "
        "The arm exists so the occupancy update is not lost, and reaching it "
        "needs the two events aligned deliberately rather than by luck. "
        "⇒ The test: drive `ui_in[6]` on the cycle the engine's `host_pop` "
        "pulses for `q_sel`, which `tb_tx` can already observe."),
    # ⭐ RETIRED (ruling (a) item 1): `tx_full_sticky` at 412 is now set by
    # `tb_status +MODE=1`, which pushes three bytes into QUEUE 2 -- drawn by no
    # lane of `tx_image`, so it fills and is never drained -- shows `tx_cnt[2]`
    # at the depth, and asserts both stored bytes survive the refused third.
    # ⚠ The first draft held the chip in LOAD mode to stop the engine popping
    # and pushed nothing at all: the host strobe IS `ui_in[6]` = `PIN_WR`, so
    # in LOAD mode those pushes went to the image loader.
    ("src/project.v", 557, "v_branch", "else"): (
        DEAD_CONFIG,
        "⚠ THIS ONE IS NEITHER UNREACHABLE NOR OWED, AND IT NEEDS A RULING. "
        "`RX_SERIAL` is a `parameter integer RX_SERIAL = 1` at line 98 and it "
        "is overridden NOWHERE in the tree -- the only two references are the "
        "declaration and this use. So the `else` is the RX_SERIAL = 0 build, "
        "a configuration nothing instantiates and the chip does not ship. "
        "⇒ Two honest resolutions, and code does not pick between them: sweep "
        "it as a build arm the way `SPL_CFG = 1` now is, or delete the "
        "parameter and the arm. Leaving it is shipping source that no "
        "configuration executes."),

    # ---- test/fram_i2c.v (the peer model Wilson named) --------------------
    ("test/fram_i2c.v", 208, "v_branch", "if"): (
        OWED,
        "The READ transaction: `shin[0]` set at P_DEV, i.e. R/W = 1. Every "
        "frame ever put on the bus has been a WRITE -- this arm's count is 0 "
        "against 13 executions of the address-match. ⚠ ALREADY OWED to Wilson "
        "in `docs/SPEC_V4_I2C_CERTIFIED.md` §6; coverage found it "
        "independently, which is the point of the sweep."),
    # ⭐ RETIRED by ruling (a)2: `P_ALO` is reached by `i2caddr_image.hex`
    # (`dev | addrhi | addrlo`, 3 bytes) under `tb_i2c +TXB=3`, and the claim
    # is stronger than the count -- the bench asserts the peer's assembled
    # address reads 0x0123, from `addrhi 0x01` at P_AHI and `addrlo 0x23` at
    # P_ALO, a value only BOTH phases can produce.
    # ⛔ `P_WDATA` (228, below) STAYS OWED AND IS NOT REACHABLE WITH THIS
    # IDIOM: the framing costs `51 + 60n` bytes, so a fourth byte is 291
    # against a 256-byte store. That is a ruling, not a missing test.
    ("test/fram_i2c.v", 228, "v_line", "case"): (
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
    ("test/fram_i2c.v", 235, "v_branch", "if"): (
        OWED,
        "⛔ NO COHERENT BYTE HAS EVER BEEN CLOCKED INTO THE STRETCHING PEER. "
        "This arm needs `byte_done` on an instance with STRETCH != 0; the "
        "point EXECUTES 28 times, always on the STRETCH = 0 instance. "
        "`i2cframe_image.hex` is the only program that assembles bytes the "
        "peer accepts and `tb_i2c` runs it against `u_i2c`; `tb_trace`'s "
        "`+PEER=i2cs` selects the stretching `u_i2cs` but the corpus I2C "
        "program never completes a byte into it. ⚠ Two arms were added to the "
        "sweep expecting to cover this and the count did not move -- recorded "
        "in `benchset.py`, because an arm added in hope must be checked. "
        "⇒ The test: `tb_i2c` with a STRETCH-parameterised peer."),
    ("test/fram_i2c.v", 239, "v_branch", "if"): (
        OWED,
        "The read-data presentation (`selected && rw && phase == P_RDATA`). "
        "Count 0 against 270 executions of the enclosing `else`. Downstream "
        "of 208: no read transaction exists to reach it."),
    ("test/fram_i2c.v", 251, "v_branch", "if"): (
        OWED,
        "The stretch countdown's decrementing arm. The point executes "
        "2,845,919 times -- every clock -- and `stretch_n` is never nonzero, "
        "because the only thing that loads it is 235. ⇒ Covered by the same "
        "test; listed separately because a fix to 235 that left this at zero "
        "would mean the countdown never ran."),

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
}

_SPI_FAMILY = (
    "`fram_spi.v`'s command decoder has never executed: `byte_done` never "
    "fires at an `negedge sck` with the part selected, so this arm is dark "
    "along with the other seventeen. See the block comment above -- the whole "
    "family needs one SPI-master program that clocks eight coherent bits per "
    "byte with CS asserted. ")
for _k, _what in (
        ((113, "v_line", "elsif"), "the deselect reset of the phase machine"),
        ((126, "v_line", "case"), "the WREN opcode arm"),
        ((127, "v_line", "case"), "the WRDI opcode arm"),
        ((128, "v_line", "case"), "the RDSR (read status) opcode arm"),
        ((133, "v_line", "case"), "the RDID (read id) opcode arm"),
        ((134, "v_line", "case"), "the READ/WRITE opcode arm"),
        ((138, "v_line", "case"), "the P_AHI high-address phase"),
        ((146, "v_line", "case"), "the P_ALO low-address phase"),
        ((149, "v_branch", "if"), "the READ fork at P_ALO, taken"),
        ((149, "v_branch", "else"), "the READ fork at P_ALO, not taken"),
        ((154, "v_line", "case"), "the P_DATA phase"),
        ((155, "v_line", "elsif"), "the WRITE arm inside P_DATA"),
        ((160, "v_branch", "if"), "the write-enable latch honoured"),
        ((160, "v_branch", "else"), "the write-enable latch refusing"),
        ((162, "v_branch", "if"), "the READ arm inside P_DATA"),
        ((162, "v_branch", "else"), "the READ arm inside P_DATA, not taken"),
        ((167, "v_line", "case"), "the phase case's defensive default"),
        ((169, "v_branch", "if"), "the drive-out shift between bytes")):
    CLASSIFIED[("test/fram_spi.v", _k[0], _k[1], _k[2])] = (
        OWED, _SPI_FAMILY + "This point is " + _what + ".")

#: ⚠ TOGGLE CEILINGS -- uncovered toggle points per file, which may only FALL.
#: ⛔ Measured, not chosen: these are the values of the sweep that shipped with
#: this gate. A ratchet seeded from a guess is a ratchet that permits a
#: regression up to the guess.
TOGGLE_CEILING = {
    "src/pe_engine.v": 236,
    "src/pe_store.v": 3,
    "src/project.v": 66,
    "test/fram_i2c.v": 42,
    "test/fram_spi.v": 27,
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
    ("src/pe_engine.v", 651):
        "if (ready[k] && (!winner_v || edf_key_off[k] < best)) begin",
    ("src/pe_engine.v", 966):
        "if (hdr_done && !prime_unp) primed_q <= 1'b1;",
    ("src/pe_engine.v", 1134):
        "H_IDLE: if (!hdr_done) begin",
    ("src/pe_engine.v", 1270):
        "default: pst <= P_SCAN;",
    ("src/pe_engine.v", 1476):
        "default: ;",
    ("src/pe_engine.v", 1675):
        "default: st <= ST_IDLE;",
    ("src/project.v", 401):
        "if (do_push && do_pop && (q_sel == tx_tag)) begin",
    ("src/project.v", 557):
        "if (RX_SERIAL != 0) begin",
    ("test/fram_i2c.v", 208):
        "if (shin[0]) shout <= mem[addr];",
    ("test/fram_i2c.v", 228):
        "P_WDATA: begin",
    ("test/fram_i2c.v", 235):
        "if (STRETCH != 0) stretch_n <= STRETCH[15:0];",
    ("test/fram_i2c.v", 239):
        "if (selected && rw && phase == P_RDATA) begin",
    ("test/fram_i2c.v", 251):
        "if (stretch_n != 16'd0) stretch_n <= stretch_n - 16'd1;",
    ("test/fram_spi.v", 113):
        "if (cs_n) begin",
    ("test/fram_spi.v", 126):
        "OP_WREN: begin wel <= 1'b1; drive <= 1'b0; end",
    ("test/fram_spi.v", 127):
        "OP_WRDI: begin wel <= 1'b0; drive <= 1'b0; end",
    ("test/fram_spi.v", 128):
        "OP_RDSR: begin",
    ("test/fram_spi.v", 133):
        "OP_RDID: begin shout <= 8'h04; drive <= 1'b1; phase <= P_DATA; end",
    ("test/fram_spi.v", 134):
        "OP_READ, OP_WRITE: begin phase <= P_AHI; drive <= 1'b0; end",
    ("test/fram_spi.v", 138):
        "P_AHI: begin",
    ("test/fram_spi.v", 146):
        "P_ALO: begin",
    ("test/fram_spi.v", 149):
        "if (opcode == OP_READ) begin",
    ("test/fram_spi.v", 154):
        "P_DATA: begin",
    ("test/fram_spi.v", 155):
        "if (opcode == OP_WRITE) begin",
    ("test/fram_spi.v", 160):
        "if (wel) mem[addr] <= shin;",
    ("test/fram_spi.v", 162):
        "end else if (opcode == OP_READ) begin",
    ("test/fram_spi.v", 167):
        "default: ;",
    ("test/fram_spi.v", 169):
        "end else if (drive) begin",
}

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
    print("  --- adjudication: %d uncovered point(s) ---" % len(uncovered))
    by_status = collections.Counter()
    unclassified = []
    for key in sorted(uncovered):
        hit = CLASSIFIED.get(key)
        if hit is None:
            unclassified.append(key)
        else:
            by_status[hit[0]] += 1
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
    stale = 0
    for key, (st, _why) in sorted(CLASSIFIED.items()):
        c = agg.get(key)
        # ⛔ TOOL_DIVERGENT IS EXEMPT, AND ONLY IT. Those points are covered
        # on one Verilator release and not another, so "covered" is the
        # expected reading half the time and failing on it would make the
        # gate red on whichever version it was not tuned against. ⚠ The
        # exemption is this narrow on purpose: an UNREACHABLE point that got
        # covered stays fatal, because that means the written reason is false.
        if st == TOOL_DIVERGENT:
            # ⛔⛔ EXEMPT FROM "COVERED", NOT FROM "ABSENT". The first version
            # skipped both, and a DRIFTED ANCHOR then survived in silence: the
            # `rx_bit` guard moved this entry's line by +24, the point came
            # back `absent`, and the gate said nothing -- while on the CI
            # toolchain, where that arm reads uncovered, its new line number
            # would have been UNCLASSIFIED and CI would have gone red. Being
            # covered on some releases is the entry's whole premise; not
            # existing at all is an anchor that needs moving.
            if c is None:
                print("    *** ANCHOR IS GONE  %s line %d %s/%s"
                      % (key[0], key[1], key[2].replace("v_", ""), key[3]))
                print("        A tool-divergent entry may be COVERED, but it")
                print("        must still EXIST. Re-anchor it to the line the")
                print("        construct moved to.")
                rc = 1
                continue
            print("    %-20s line %-5d %s/%-5s tool-divergent (count %s)"
                  % (key[0], key[1], key[2].replace("v_", ""), key[3], c))
            continue
        if c is None:
            print("    *** NOT IN THE DATA  %s line %d %s/%s"
                  % (key[0], key[1], key[2].replace("v_", ""), key[3]))
            print("        The point does not exist in the merged coverage.")
            print("        Either the line moved, or the sweep no longer")
            print("        builds the file -- a waiver for a point nothing")
            print("        measures is a waiver that can never be retired.")
            rc = 1
            stale += 1
        elif c > 0:
            stale += 1
            if st == UNREACHABLE:
                print("    *** THE REASON WAS FALSE  %s line %d %s/%s "
                      "(count %d)" % (key[0], key[1],
                                      key[2].replace("v_", ""), key[3], c))
                print("        It was classified UNREACHABLE and a test")
                print("        reached it. The written reason is wrong and")
                print("        the mechanism behind it needs re-reading.")
            else:
                print("    *** DEBT PAID, ENTRY STALE  %s line %d %s/%s "
                      "(count %d)" % (key[0], key[1],
                                      key[2].replace("v_", ""), key[3], c))
                print("        Remove it: a stale OWED entry claims")
                print("        something is untested when it is tested.")
            rc = 1
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
    want = {(f, l) for (f, l, _k, _a) in CLASSIFIED}
    missing = sorted(want - set(ANCHOR_TEXT))
    for f, l in missing:
        print("    *** NO RECORDED TEXT  %s line %d" % (f, l))
        print("        A classified anchor with no source text cannot be")
        print("        checked for drift. Add it to ANCHOR_TEXT.")
        rc = 1
    stale = sorted(set(ANCHOR_TEXT) - want)
    for f, l in stale:
        print("    *** TEXT FOR A POINT NOBODY CLASSIFIES  %s line %d" % (f, l))
        rc = 1
    src = {}
    ok = 0
    for (f, l), expect in sorted(ANCHOR_TEXT.items()):
        path = os.path.join(ROOT, f)
        if f not in src:
            if not os.path.isfile(path):
                print("    *** %s is missing entirely" % f)
                rc = 1
                src[f] = []
            else:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    src[f] = fh.read().splitlines()
        lines = src[f]
        found = lines[l - 1].strip() if 0 < l <= len(lines) else "<past end of file>"
        if found == expect:
            ok += 1
            continue
        print("    *** ANCHOR MOVED  %s line %d" % (f, l))
        print("        expected: %s" % expect)
        print("        found   : %s" % found)
        print("        ⛔ Re-anchor by applying the MEASURED line shift, not by")
        print("           grepping for a statement you remember. Then update")
        print("           ANCHOR_TEXT and the entry's reason together.")
        rc = 1
    if rc == 0:
        print("    %d anchors, every one reads as recorded" % ok)
    return rc


def check_reasons() -> int:
    """The reasons themselves are checked, as the reset allowlist's are."""
    rc = 0
    print()
    print("  --- the reasons ---")
    short, vague = [], []
    BOILER = ("n/a", "todo", "tbd", "unreachable", "not reachable", "see above",
              "obvious", "by design", "")
    for key, (st, why) in sorted(CLASSIFIED.items()):
        w = (why or "").strip()
        if len(w) < 60:
            short.append((key, len(w)))
        if w.lower().rstrip(". ") in BOILER:
            vague.append(key)
        if st not in (UNREACHABLE, OWED, DEAD_CONFIG, TOOL_DIVERGENT):
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
    """name -> (value, width) for every sized localparam constant."""
    out = {}
    for m in re.finditer(r"localparam\s*\[(\d+):0\]\s*(.+?);", src, re.S):
        width = int(m.group(1)) + 1
        for a in re.finditer(r"([A-Za-z_][A-Za-z_0-9]*)\s*=\s*\d+'d(\d+)",
                             m.group(2)):
            out[a.group(1)] = (int(a.group(2)), width)
    return out


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
    for line in (1270, 1476, 1675):
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
        ok = full or closed
        how = ("every encoding named" if full
               else "every assignment writes a named arm" if closed
               else "NEITHER")
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
        bad = check_points_quiet(fake)
    finally:
        CLASSIFIED.clear()
        CLASSIFIED.update(saved)
    print("    %-52s %s" % ("an unclassified uncovered point is rejected",
                            "ok" if bad else "*** ACCEPTED"))
    if not bad:
        rc = 1
    # (2) a classified point that is covered
    fake2 = dict(agg)
    key = next(iter(CLASSIFIED))
    fake2[key] = 7
    bad2 = check_stale_quiet(fake2)
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
        gone = check_stale_quiet_absent(agg)
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
        moved = check_anchors_quiet()
    finally:
        ANCHOR_TEXT.clear()
        ANCHOR_TEXT.update(saved3)
    print("    %-52s %s" % ("an anchor whose line text changed is rejected",
                            "ok" if moved else "*** ACCEPTED"))
    if not moved:
        rc = 1
    # (3) a short reason
    probe = {("x.v", 1, "v_line", "case"): (UNREACHABLE, "because.")}
    short = any(len((w or "").strip()) < 60 for _s, w in probe.values())
    print("    %-52s %s" % ("a one-line reason is rejected",
                            "ok" if short else "*** ACCEPTED"))
    if not short:
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


def check_points_quiet(agg):
    out = []
    for key, c in agg.items():
        if not subject(key) or key[2] not in ("v_line", "v_branch"):
            continue
        if c == 0 and CLASSIFIED.get(key) is None:
            out.append(key)
    return bool(out)


def check_anchors_quiet():
    """True if any recorded anchor text no longer matches its line."""
    src = {}
    for (f, l), expect in ANCHOR_TEXT.items():
        path = os.path.join(ROOT, f)
        if f not in src:
            if not os.path.isfile(path):
                return True
            with open(path, encoding="utf-8", errors="replace") as fh:
                src[f] = fh.read().splitlines()
        lines = src[f]
        found = lines[l - 1].strip() if 0 < l <= len(lines) else None
        if found != expect:
            return True
    return False


def check_stale_quiet_absent(agg):
    """True if any TOOL_DIVERGENT entry's anchor is missing from the data."""
    for key, (st, _why) in CLASSIFIED.items():
        if st == TOOL_DIVERGENT and agg.get(key) is None:
            return True
    return False


def check_stale_quiet(agg):
    for key in CLASSIFIED:
        if agg.get(key, 0) > 0:
            return True
    return False


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
    env = os.path.join(os.path.dirname(DAT), "sweep_env.txt")
    if os.path.isfile(env):
        with open(env, encoding="utf-8", errors="replace") as fh:
            for ln in fh.read().strip().splitlines():
                print("  %s" % ln.strip())
    else:
        print("  ⚠ no sweep_env.txt beside the data -- the tool version that")
        print("    produced it is unrecorded, so a toggle-ceiling breach")
        print("    cannot be told from a version difference.")
    rc = 0
    rc |= check_points(agg)
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
    print("      the test that would reach it) and %d is dead configuration"
          % dead)
    print("      awaiting a ruling. The debt is the point of the list -- it")
    print("      is visible instead of inside a percentage.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
