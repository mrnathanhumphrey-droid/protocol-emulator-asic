"""gen_op_reads -- WHICH ACTION-WORD FIELDS EACH OPCODE READS, GENERATED FROM THE
ENGINE'S DECODE (Wilson 11-14: "read, not assumed").

    python model/gen_op_reads.py --write    write test/op_reads.json
    python model/gen_op_reads.py [--check]  the gate (CI runs it with no arguments): the tracked table equals a fresh
                                            extraction, every engine read site is covered
                                            (token: GATE op-reads: PASSED)

⛔⛔ WHY. pe_asm filled every action's `count` with 8 and corpus stamped a lane's TX
queue on every word of that lane, so fields an op never reads carried assembler
defaults -- and a later bit assignment (ARM's HALF / QUAL / FALLTHROUGH, 11-14) would
have collided with them. The rule (Wilson 11-14): pe_asm writes 0 in every field an
op does not read, and pe_isa refuses a nonzero value there -- on every opcode, from
THIS table, never from a list typed in pe_isa.

HOW THE TABLE IS READ OFF src/pe_engine.v:
  * the FIELDS are the decode slices `a_pin a_lvl a_dly a_cnt a_q a_pinb a_mod` (and
    the head-word slices of `l_act`/`u_head`/`hact`, the pre-decode `w[...]`), plus
    the DERIVED wires built from them (DERIVED below: each names the fields its own
    definition reads -- the definition line is a covered site);
  * every line inside a `case (a_op)` arm is attributed to THAT ARM'S opcodes,
    found from the arm labels in the RTL itself;
  * every other line that names a field or a derived wire must match a SITE below
    (an exact substring of the line), which states the opcodes that reach it and
    why -- or the IGNORE list (transport, declarations, resets). A line that names a
    field and matches nothing is RED: a new engine read cannot slip past the table.
Bit-level reads are kept where the RTL takes them: ARM reads count[0] (HALF) and
count[1] (QUAL) and mod[0] (LEVEL2) / mod[1] (FALLTHROUGH).

THE ONE EXEMPTION (Wilson 11-14, option 1): the store filler, `pe_isa.STORE_FILLER`
(REARM with pin = PIN_NONE, ruling M1's defined non-driving word, generated into the
RTL as PE_STORE_FILLER). REARM does not read `pin`, so the filler is exempt BY EXACT
VALUE ONLY -- that one word, byte-identical; any other REARM with a nonzero pin is
refused. pe_isa reads the filler from the same generator that writes it.
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENGINE = os.path.join(ROOT, "src", "pe_engine.v")
OUT = os.path.join(ROOT, "test", "op_reads.json")

FIELDS = ("pin", "level", "delay", "count", "q", "pinb", "mod")
FULL = {"pin": 0xF, "level": 0x1, "delay": 0x3FF, "count": 0xF, "q": 0x3, "pinb": 0xF, "mod": 0x3}
OPS = ("LEVEL", "SHIFT", "SHIFTIN", "READBIT", "START", "STOP", "ARM", "REARM",
       "BRANCH_BIT", "CMP_BRANCH", "LOOP", "SHIFTI")
ALL = OPS

#: base decode tokens -> (field, mask). A bit-select `a_cnt[0]` reads only that bit.
BASE = {"a_pin": "pin", "a_lvl": "level", "a_dly": "delay", "a_cnt": "count",
        "a_q": "q", "a_pinb": "pinb", "a_mod": "mod"}

#: derived wires -> {field: the ops whose decode reaches that field through the wire}
#: (None = every op that uses the wire). Read off each wire's own definition: a field
#: the definition takes only under a class gate is restricted to that class's ops, so
#: a shared arm or an every-op site does not spread it (e.g. `a_dly_wb` is the delay
#: for every op but the branch wait -- count + pinb -- only for a branch).
_BR = ("BRANCH_BIT", "CMP_BRANCH", "LOOP")
DERIVED = {
    "pin_real": {"pin": None}, "pinb_real": {"pinb": None}, "rx_vpin": {"pin": None},
    "rx_bit": {"pin": None},
    "ck_shift": {"level": ("SHIFT", "SHIFTI")}, "ck_shiftin": {"level": ("SHIFTIN",)},
    "ck_nbits": {"count": ("SHIFT", "SHIFTI", "SHIFTIN"), "level": ("SHIFT", "SHIFTI", "SHIFTIN")},
    "st_lastix": {"count": ("SHIFT", "SHIFTI", "SHIFTIN")},
    "a_dly_wb": {"delay": None, "count": _BR, "pinb": _BR},
    "shi_imm": {"count": ("SHIFTI",), "q": ("SHIFTI",), "delay": ("SHIFTI",)},
    "br_wait": {"count": _BR, "pinb": _BR},
    "br_tgt_w": {"delay": _BR}, "br_tdly": {"delay": _BR},
    "br_bit_take": {"pin": ("BRANCH_BIT",), "level": ("BRANCH_BIT",)},
    "cmp_src": {"q": ("CMP_BRANCH",)},
    "cmp_imm": {"pin": ("CMP_BRANCH",), "delay": ("CMP_BRANCH",), "level": ("CMP_BRANCH",)},
    "cmp_mask": {"mod": ("CMP_BRANCH",)},
    "br_cmp_take": {f: ("CMP_BRANCH",) for f in ("pin", "delay", "level", "q", "mod")},
    "lp_n": {"pin": ("LOOP",), "delay": ("LOOP",), "level": ("LOOP",)},
    "usb_send": {"q": ("SHIFT",)}, "uc_hold": {"level": ("SHIFT", "SHIFTI")},
    "tx_bit": {"count": ("SHIFTI",), "q": ("SHIFT", "SHIFTI"), "delay": ("SHIFTI",)},
}

C_SHIFT = ("SHIFT", "SHIFTI")            # pre_cls C_SHIFT is SHIFT or SHIFTI
#: (exact substring of the line, ops, why) -- every field-naming line outside an arm
SITES = [
    ("wire [OP_W-1:0]  a_op    = cur_act[", "DEF", "the opcode itself"),
    ("wire [PINW-1:0]  a_pin   = cur_act[", "DEF", "decode slice"),
    ("wire             a_lvl   = cur_act[", "DEF", "decode slice"),
    ("wire [DLY_W-1:0] a_dly   = cur_cls[C_SHI] ? {{(DLY_W-8){1'b0}}, cur_act[", "DEF", "decode slice (SHIFTI: 8 bits)"),
    (": cur_act[LOWX+BQW+BPW +: DLY_W];", "DEF", "decode slice"),
    ("wire [BPW-1:0]   a_cnt   = cur_cls[C_SHI] ? 4'd7 : cur_act[", "DEF", "decode slice"),
    ("wire [7:0]       shi_imm = {cur_act[", "DEF", "SHIFTI immediate"),
    ("cur_act[LOWX+BQW+BPW+8 +: 2]};", "DEF", "SHIFTI immediate"),
    ("assign           a_q     = cur_act[", "DEF", "decode slice"),
    ("wire [BPW+PINB_W-1:0] br_wait = {a_cnt, cur_act[", "DEF", "branch wait"),
    ("wire [MOD_W-1:0] a_mod  = cur_act[", "DEF", "decode slice"),
    ("wire [PINB_W-1:0] a_pinb = cur_act[", "DEF", "decode slice"),
    ("wire [BQW-1:0]   a_q;", "DEF", "declaration"),
    ("assign host_q    = a_q;", C_SHIFT + ("CMP_BRANCH",),
     "host_q -> project.v q_sel -> tx_valid/tx_head/do_popq, consumed only on SHIFT/SHIFTI "
     "(host_valid l.4006/4260, host_pop); CMP_BRANCH reads a_q itself"),
    ("wire pin_real = (a_pin < N_PINS", "DEF", "pin index guard"),
    ("wire pin_real = 1'b1;", "DEF", "mutant"),
    ("wire pinb_real = (a_pinb < N_PINS", "DEF", "pinb index guard"),
    ("wire ck_shift   = clk_real & a_lvl & cur_cls[C_SHIFT];", "DEF", "clocked SHIFT"),
    ("wire ck_shiftin = clk_real & a_lvl & cur_cls[C_SHIFTIN];", "DEF", "clocked SHIFTIN"),
    ("wire [DLY_W-1:0] a_dly_wb = a_is_br ? {DLY_W{1'b0}} : a_dly;", "DEF", "mutant arm"),
    ("wire [DLY_W-1:0] a_dly_wb = a_is_br ? {{(DLY_W-BPW-PINB_W){1'b0}}, br_wait} : a_dly;", "DEF", "writeback delay"),
    ("? (a_dly >> 1) : a_dly_wb;", ALL, "the writeback timestamp advance: every op's delay (branch: its wait)"),
    ("wire [BPW-1:0] ck_nbits = ck_shift ? (a_cnt", "DEF", "clocked bit count"),
    (": a_cnt;", ("SHIFT", "SHIFTI", "SHIFTIN"), "ck_nbits, read by the clocked shift path"),
    ("wire [BPW-1:0] st_lastix = cur_cls[C_SHIFT] ? a_cnt", "DEF", "self-timed last bit"),
    ("wire usb_send = st_act & cur_cls[C_SHIFT]", "DEF", "USB buffer send"),
    ("(st_act & cur_cls[C_SHIFTIN] & (a_cnt == {BPW{1'b0}})) | usb_wrong;", ("SHIFTIN",), "zero-count self-timed SHIFTIN refusal"),
    ("wire uc_hold = cur_cls[C_SHIFT] & clk_real & ~a_lvl;", "DEF", "unclocked hold"),
    ("& (a_dly <= SDA_HOLD[DLY_W-1:0]);", ("LEVEL", "START", "STOP") + C_SHIFT + ("SHIFTIN", "READBIT"),
     "the SDA hold rule on driving / sampling ops"),
    ("wire act_retire = ~ck_hold_eff & (~cur_cls[C_REARM] | a_lvl);", ("REARM",), "REARM's level: loop vs chain"),
    (": cur_cls[C_SHI] ? shi_imm[0] : (host_valid & host_ord[0]);", "DEF", "tx_bit"),
    ("wire       rx_vpin    = (a_pin == VPIN_READY)", "DEF", "virtual pins"),
    ("(a_pin == VPIN_CRC_OK)", "DEF", "virtual pins"),
    ("(a_pin == VPIN_STUFF_ERR)", "DEF", "virtual pins"),
    ("(a_pin == VPIN_ADDR_OK)", "DEF", "virtual pins"),
    ("wire       usb_clr_lvl = (st == ST_WB) & (a_op == OP_LEVEL) & (a_pin == VPIN_READY) &", ("LEVEL",), "READY clear"),
    ("~a_lvl & (cur == USB_LANE[LW-1:0]);", ("LEVEL",), "READY clear"),
    ("wire       rx_bit     = pin_in[a_pin];", "DEF", "mutant"),
    ("wire       rx_bit     = pin_real ? pin_in[a_pin] : rx_vpin;", "DEF", "sampled bit"),
    ("wire [AW-1:0] br_tgt_w = {{(AW-BR_W){1'b0}}, a_dly[BR_W-1:0]};", "DEF", "branch target"),
    ("wire [DLY_W-1:0] br_tdly = (a_op[1:0] != 2'b00)", "DEF", "branch target"),
    ("| (br_wait < BR_W_MIN[BPW+PINB_W-1:0]);", ("BRANCH_BIT", "CMP_BRANCH", "LOOP"), "br_bad: wait below the floor"),
    ("wire          br_bit_take = (rx_bit != a_lvl);", "DEF", "mutant"),
    ("wire          br_bit_take = (rx_bit == a_lvl);", "DEF", "BRANCH_BIT decision"),
    ("wire [7:0]    cmp_src  = a_q[1] ? usb_pidc : cmp_rx;", "DEF", "CMP source"),
    ("wire [7:0]    cmp_imm  = {a_pin, a_dly[DLY_W-1 -: 3], a_lvl} + 8'd1;", "DEF", "mutant"),
    ("wire [7:0]    cmp_imm  = {a_pin, a_dly[DLY_W-1 -: 3], a_lvl};", "DEF", "CMP immediate"),
    ("wire [7:0]    cmp_mask = (a_mod == 2'd1)", "DEF", "CMP mask"),
    (": (a_mod == 2'd3) ? 8'h0F : 8'hFF;", "DEF", "CMP mask"),
    ("wire          br_cmp_take = (((cmp_src ^ cmp_imm) & cmp_mask) == 8'h00) ^ a_q[0];", "DEF", "CMP decision"),
    ("wire [7:0]    lp_n    = {a_pin, a_dly[DLY_W-1 -: 3], a_lvl} + 8'd1;", "DEF", "mutant"),
    ("wire [7:0]    lp_n    = {a_pin, a_dly[DLY_W-1 -: 3], a_lvl};", "DEF", "LOOP count"),
    ("l_armpin[cur]  <= a_pin;", ("ARM",), "ARM latch (inside `if (a_op == OP_ARM)`)"),
    ("l_armedge[cur] <= a_lvl;", ("ARM",), "ARM latch"),
    ("l_arm2[cur]    <= a_mod[0];", ("ARM",), "ARM latch"),
    ("l_armpinb[cur] <= a_pinb;", ("ARM",), "ARM latch"),
    ("l_armhalf[cur] <= a_cnt[0];", ("ARM",), "ARM latch: HALF = count[0]"),
    ("l_armqual[cur] <= a_cnt[1];", ("ARM",), "ARM latch: QUAL = count[1]"),
    ("l_armft[cur]   <= a_mod[1];", ("ARM",), "ARM latch: FALLTHROUGH = mod[1]"),
    ("notmo_n[cur]   = (a_dly == {DLY_W{1'b0}});", ("ARM",), "ARM latch: no timeout"),
    ("if (cur == USB_LANE[LW-1:0] && !a_lvl &&", ("ARM", "LEVEL"), "USB pair latch"),
    ("((a_op == OP_ARM && a_mod[0]) || (a_op == OP_LEVEL && a_mod == 2'b11)) &&", ("ARM", "LEVEL"), "USB pair latch"),
    ("a_pin < N_UIO[PINW-1:0] && a_pinb < N_UIO[PINB_W-1:0]) begin", ("ARM", "LEVEL"), "USB pair latch"),
    ("usb_sp <= a_pin;", ("ARM", "LEVEL"), "USB pair latch"),
    ("usb_sn <= a_pinb;", ("ARM", "LEVEL"), "USB pair latch"),
    ("if (usb_act & ~usb_stuff & (a_mod[0] | usb_new))", ("SHIFTIN",), "USB receive CRC (C_USB)"),
    ("usb_crc <= a_mod[0] ?", ("SHIFTIN",), "USB receive CRC"),
    ("end else if (a_lvl) begin", ("REARM",), "writeback: REARM level (loop back)"),
    ("if (cur_cls[C_SHIFT] && (!ck_shift || ck_is_low) && l_bitp_shared == a_cnt) begin", C_SHIFT, "TX byte boundary"),
    ("if (cur_cls[C_SHIFT] && tx_bitp[cur] == a_cnt) begin", C_SHIFT, "TX byte boundary (mutant)"),
    ("if (cur_cls[C_SHIFT] && (!ck_shift || ck_is_low) && tx_bitp[cur] == a_cnt) begin", C_SHIFT, "TX byte boundary"),
    # head-word reads (the prefetched head, before dispatch)
    ("op = w[ACT_W-1 -: OP_W];", "DEF", "pre-decode: the opcode"),
    ("pre_cls[C_ST]      = (((op == OP_SHIFT) || (op == OP_SHIFTIN)) && w[1]) || (op == OP_SHIFTI);",
     ("SHIFT", "SHIFTIN"), "pre-decode: mod[1] = self-timed"),
    ("pre_cls[C_USB]     = (op == OP_SHIFTIN) && w[1] && w[ACT_W-1-OP_W-PINW];", ("SHIFTIN",), "pre-decode: USB receive"),
    ("wire [PINW-1:0] ck_rpin = l_act[hix[gi]][ACT_W-1-OP_W -: PINW];", ("SHIFTIN", "READBIT"),
     "the clocked receive's capture pin, from the head"),
    ("assign ck_dly[gi] = l_act[hix[gi]][LOWX+BQW+BPW +: DLY_W];", ALL, "the head's delay (clocked park rebase)"),
    ("wire [PINW-1:0]  u_pin   = u_head[ACT_W-1-OP_W -: PINW];", ("SHIFTIN",), "USB re-anchor: the head receive's pin"),
    ("wire [TS_W-1:0]  u_half   = {{(TS_W-DLY_W+1){1'b0}}, u_head[LOWX+BQW+BPW+1 +: DLY_W-1]};", ("SHIFTIN",),
     "USB re-anchor: half the head receive's delay"),
    ("else if (l_cls[hix[ln]][C_REARM] && hact[ACT_W-1-OP_W-PINW])", ("REARM",), "want_fetch: REARM level"),
    ("else if (l_cls[hix[ln]][C_REARM] && !hact[ACT_W-1-OP_W-PINW])", ("REARM",), "want_fetch: REARM level"),
    # derived-wire uses, attributed by the class that gates each (pre_cls: C_SHIFT =
    # SHIFT|SHIFTI, C_SHIFTIN, C_ST = self-timed SHIFT|SHIFTIN|SHIFTI, C_BR = branches)
    ("wire ck_act     = ck_shift | ck_shiftin;", "DEF", "clocked action"),
    ("wire ppc_set    = (st == ST_WB) & ck_shiftin & ck_is_high & l_mode[cur];", ("SHIFTIN",), "clocked capture"),
    ("wire [BPW-1:0] st_lastix_e = cur_cls[C_SHIFTIN] ? st_lastix + 4'd8 : st_lastix;", "DEF", "mutant"),
    ("wire [BPW-1:0] st_lastix_e = st_lastix;", ("SHIFT", "SHIFTI", "SHIFTIN"), "self-timed last bit"),
    ("wire st_last  = usb_send ? (usb_bcnt == usb_blen - 7'd1) : (st_last_b & ~cur_cls[C_SHIFT]);", "DEF", "mutant"),
    ("wire st_last  = usb_send ? (usb_bcnt == usb_blen - 7'd1) : st_last_b;", ("SHIFT", "SHIFTI", "SHIFTIN"), "self-timed hold"),
    ("wire ck_degen = (ck_act & (ck_nbits == {BPW{1'b0}})) |", ("SHIFT", "SHIFTI", "SHIFTIN"), "zero-bit clocked refusal"),
    ("wire ck_holdviol = (ck_act | uc_hold) & ~l_mode[cur] & (SDA_HOLD != 0)", ("SHIFT", "SHIFTI", "SHIFTIN"), "hold violation"),
    ("wire ck_bits_done = (l_ckbit[cur] == ck_nbits);", ("SHIFT", "SHIFTI", "SHIFTIN"), "clocked bits done"),
    ("wire ck_retire  = (ck_shift   & ck_is_high & ck_bits_done) |", ("SHIFT", "SHIFTI"), "clocked retire"),
    ("(ck_shiftin & ck_is_coll);", ("SHIFTIN",), "clocked retire"),
    ("wire ck_consume = ck_shiftin & (ck_is_coll |", ("SHIFTIN",), "clocked consume"),
    ("wire [1:0] ck_norm = ck_shift", ("SHIFT", "SHIFTI", "SHIFTIN"), "clocked phase"),
    ("wire tx_bit   = l_tx[cur][0];", "DEF", "mutant"),
    ("wire tx_bit   = l_txv[cur] ? l_tx[cur][0]", "DEF", "the TX bit"),
    ("assign     usb_sent    = (st == ST_WB) & usb_send & act_retire;", ("SHIFT",), "USB send done"),
    ("wire [AW-1:0] br_tgt   = ACT_BASE[AW-1:0] + (br_tgt_w + {{(AW-1){1'b0}}, 1'b1}) * ACT_BYTES[AW-1:0];", "DEF", "mutant"),
    ("wire [AW-1:0] br_tgt   = ACT_BASE[AW-1:0] + br_tgt_w * ACT_BYTES[AW-1:0];", ("BRANCH_BIT", "CMP_BRANCH", "LOOP"), "branch target"),
    ("wire          br_bad   = (br_tdly >= BR_NWORDS[DLY_W-1:0])", ("BRANCH_BIT", "CMP_BRANCH", "LOOP"), "branch refusal"),
    ("wire [7:0]    cmp_mask = 8'hFF;", "DEF", "mutant"),
    ("wire          br_cmp_take = (((cmp_src ^ cmp_imm) & cmp_mask) == 8'h00);", "DEF", "mutant"),
    ("wire [7:0]    lp_eff  = (lp_cur == 8'd0) ? lp_n : lp_cur;", ("LOOP",), "LOOP count"),
    ("wire       usb_dec    = (rx_bit == usb_prev);", ("SHIFTIN",), "USB NRZI decode"),
    ("wire       rx_bit_sel = ck_shiftin ? ck_rxbit : usb_act ? usb_dec : rx_bit;", ("SHIFTIN",), "receive bit"),
    ("br_take_q <= a_op[1] ? br_loop_take : a_op[0] ? br_cmp_take : br_bit_take;", ("BRANCH_BIT", "CMP_BRANCH", "LOOP"), "branch decision"),
    ("if (usb_send) usb_bcnt <= act_retire ? 7'd0 : usb_bcnt + 7'd1;", ("SHIFT",), "USB send count"),
    ("usb_prev <= rx_bit;", ("SHIFTIN",), "USB NRZI tracker"),
    ("if (ck_shiftin & ck_is_high) begin", ("SHIFTIN",), "clocked capture"),
    ("if (usb_send && act_retire) begin", ("SHIFT",), "USB send retire"),
]
#: lines that move or declare a word without reading a field
IGNORE = ("l_act[i]  <= {ACT_W{1'b0}};", "reg [ACT_W-1:0] l_act ", "reg [CLS_W-1:0] l_cls ",
          "assign hw[gi] = l_act[hix[gi]];", "reg [ACT_W-1:0] w_act;",
          "wire [ACT_W-1:0] u_head  = l_act[hix[USB_LANE]];", "hact   = l_act [hix[ln]];",
          "l_act [fix] <= s_wrdata[")

TOKEN = re.compile(r"\b(%s)\b(\[(\d+)\])?" % "|".join(list(BASE) + list(DERIVED)))
HEAD = re.compile(r"\b(cur_act|l_act|u_head|hact)\s*\[|\bw\[")


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read().replace("\r\n", "\n").split("\n")


def regions(lines):
    """[(first, last, (ops...))] for every `case (a_op)` arm, from the labels."""
    out = []
    i = 0
    lab = re.compile(r"^\s+((?:OP_[A-Z_]+\s*,\s*)*OP_[A-Z_]+|default)\s*:")
    while i < len(lines):
        if re.search(r"\bcase \(a_op\)", lines[i]):
            depth, j, cur = 0, i + 1, None
            while j < len(lines):
                s = lines[j]
                if re.search(r"\bcase\b", s) and not s.strip().startswith("//"):
                    depth += 1
                if re.search(r"\bendcase\b", s):
                    if depth == 0:
                        break
                    depth -= 1
                m = lab.match(s) if depth == 0 else None
                if m:
                    if cur:
                        out.append((cur[0], j - 1, cur[1]))
                    ops = tuple(x.strip()[3:] for x in m.group(1).split(",")) if m.group(1) != "default" else ()
                    cur = (j, ops)
                j += 1
            if cur:
                out.append((cur[0], j - 1, cur[1]))
            i = j
        i += 1
    return out


def extract(lines=None):
    """(table {op: {field: mask}}, [problem])."""
    lines = _read(ENGINE) if lines is None else lines
    regs = regions(lines)
    table = {op: {f: 0 for f in FIELDS} for op in OPS}
    probs, used_sites = [], set()

    def fields_of(line, op=None):
        """{field: mask} the line reads -- for `op` when given (derived wires
        carry only the fields their definition reaches for that op)."""
        out = {}
        for m in TOKEN.finditer(line):
            tok, bit = m.group(1), m.group(3)
            if tok in BASE:
                f = BASE[tok]
                out[f] = out.get(f, 0) | ((1 << int(bit)) if bit is not None else FULL[f])
            else:
                for f, ops in DERIVED[tok].items():
                    if op is None or ops is None or op in ops:
                        out[f] = out.get(f, 0) | FULL[f]
        return out

    for n, raw in enumerate(lines):
        line = raw.split("//", 1)[0]
        if not line.strip():
            continue
        fl = fields_of(line)
        if not fl and not HEAD.search(line):
            continue
        reg = [r for r in regs if r[0] <= n <= r[1]]
        if reg:
            for op in reg[0][2]:
                for f, mk in fields_of(line, op).items():
                    table[op][f] |= mk
            continue
        if any(ig in raw for ig in IGNORE):
            continue
        hit = [s for s in SITES if s[0] in raw]
        if not hit:
            probs.append("pe_engine.v:%d names a field and is covered by no SITE: %s" % (n + 1, raw.strip()[:100]))
            continue
        used_sites.add(hit[0][0])
        anchor, ops, _why = hit[0]
        if ops == "DEF":
            continue
        # head-word / pre-decode sites name the field by slice, not by token
        for op in ops:
            for f, mk in (fields_of(line, op) if fl else _head_fields(raw)).items():
                table[op][f] |= mk
    for a, _o, _w in SITES:
        c = sum(1 for l in lines if a in l)
        if c != 1 and a not in ("& (a_dly <= SDA_HOLD[DLY_W-1:0]);",):
            probs.append("SITE anchor matches %d engine lines (want 1): %s" % (c, a[:80]))
    # the opcode field itself is read by every op
    return table, probs


def _head_fields(raw):
    """Fields a head-word / pre-decode slice line reads (by its slice text)."""
    out = {}
    if "ACT_W-1-OP_W -: PINW" in raw:
        out["pin"] = FULL["pin"]
    if "ACT_W-1-OP_W-PINW]" in raw:
        out["level"] = FULL["level"]
    if "LOWX+BQW+BPW" in raw:
        out["delay"] = FULL["delay"]
    if "w[1]" in raw:
        out["mod"] = out.get("mod", 0) | 0x2
    return out


def write(table):
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"_doc": "GENERATED by model/gen_op_reads.py from src/pe_engine.v -- "
                           "the bits of each field each opcode reads; never edit by hand",
                   "reads": table}, fh, indent=1, sort_keys=True)
        fh.write("\n")


def load():
    with open(OUT, encoding="utf-8") as fh:
        return json.load(fh)["reads"]


def check():
    table, probs = extract()
    try:
        tracked = load()
    except (OSError, ValueError) as exc:
        tracked, _ = None, probs.append("test/op_reads.json unreadable: %s" % exc)
    if tracked is not None and tracked != table:
        probs.append("test/op_reads.json is STALE against the engine -- run model/gen_op_reads.py")
    return table, probs


def must_fires(table):
    rows = []
    lines = _read(ENGINE)
    # a new engine read site no SITE covers
    planted = lines + ["  wire planted_read = a_cnt[2] & cur_cls[C_REARM];"]
    rows.append(("an uncovered engine read site (planted)",
                 any("covered by no SITE" in p for p in extract(planted)[1])))
    # a perturbed table
    bad = json.loads(json.dumps(table))
    bad["REARM"]["pin"] = FULL["pin"]
    rows.append(("a perturbed table (REARM made to read pin)", bad != extract()[0]))
    # ---- the refusal itself (pe_isa.unread_problems), Wilson 11-14 ----------
    sys.path.insert(0, os.path.join(ROOT, "test"))
    import pe_isa as I
    def refused(word):
        img = I.full_store(I.join_image([I.hdr(0, I.PIN_NONE, 1, 40, 0, 40, 60, I.ACT_BASE)]
                                        + [I.hdr(1, I.PIN_NONE, 1, 500, 0, 200, 240, I.ACT_BASE)] * (I.N_LANES - 1),
                                        [word]))
        return bool(I.unread_problems(img))
    rows.append(("an ARM with count = 8 is refused",
                 refused(I.act(I.OP_ARM, 0, 0, 0, count=8))))
    rows.append(("a LEVEL with q = 1 (the old lane tag) is refused",
                 refused(I.act(I.OP_LEVEL, 0, 1, 20, q=1))))
    # the store filler: exempt by EXACT value only
    fill = bytes(I.STORE_FILLER)
    rows.append(("control: the exact filler is ACCEPTED", not refused(fill)))
    # EVERY one-bit flip of the filler must be refused (Wilson 11-14) -- by the
    # whole refusal aggregate (pe_isa.branch_problems), not only the unread rule.
    # ⚠ OPEN, PENDING WILSON (reported, never silent): three opcode-bit flips turn
    # the filler into a REAL op whose (read) pin field holds PIN_NONE -- ARM,
    # STOP, READBIT with pin 15, delay 1023. Whether PIN_NONE is refused on those
    # ops is a pin-semantics ruling (LEVEL's no-op idiom uses PIN_NONE
    # legitimately; an ARM on PIN_NONE is a deliberate runtime-refusal image), not
    # an unread-field one. Any OTHER accepted flip is red.
    accepted = []
    for byte in range(len(fill)):
        for bit in range(8):
            w = bytearray(fill)
            w[byte] ^= 1 << bit
            img = I.full_store(I.join_image(
                [I.hdr(0, I.PIN_NONE, 1, 40, 0, 40, 60, I.ACT_BASE)]
                + [I.hdr(1, I.PIN_NONE, 1, 500, 0, 200, 240, I.ACT_BASE)] * (I.N_LANES - 1),
                [bytes(w)]))
            if not I.branch_problems(img):
                accepted.append(I._unpack(I.ACT_FIELDS, bytes(w), I.ACT_BYTES)["op"])
    open_pending = sorted(op for op in accepted if op in (I.OP_ARM, I.OP_STOP, I.OP_READBIT))
    for op in open_pending:
        print("  OPEN (pending Wilson): a filler flip -> opcode %d with pin PIN_NONE is accepted" % op)
    rows.append(("every filler bit flip refused (but the 3 OPEN)",
                 len(accepted) == len(open_pending) and len(fill) * 8 > 0))
    rows.append(("a REARM with pin 15 not byte-identical to the filler is refused",
                 refused(I.act(I.OP_REARM, I.PIN_NONE, 0, 500))))
    return rows


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--write" in argv:      # a gate runs with no arguments: the default is the check
        table, probs = extract()
        for p in probs:
            print("  *** " + p)
        if probs:
            return 1
        write(table)
        print("  -> %s" % os.path.relpath(OUT, ROOT))
        return 0
    print("GATE op-reads -- the fields each opcode reads, generated from the engine's decode")
    table, probs = check()
    for op in OPS:
        print("  %-11s %s" % (op, " ".join("%s=%#x" % (f, table[op][f]) for f in FIELDS if table[op][f])))
    for label, red in must_fires(table):
        print("  must-fire: %-46s %s" % (label[:46], "ok" if red else "*** FAILED"))
        if not red:
            probs.append("must-fire failed: " + label)
    for p in probs:
        print("  *** " + p)
    print("  GATE op-reads: %s" % ("PASSED" if not probs else "FAILED"))
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
