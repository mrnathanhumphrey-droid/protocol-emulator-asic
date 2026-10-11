"""count_ranges -- pe_asm's per-opcode COUNT range, DERIVED from the RTL decode.

⛔⛔ WILSON'S CONDITION ON SP2/P1. The per-opcode range (SHIFT 0..14, SHIFTIN
1..15, every other opcode 0..15) was ACCEPTED only if the asymmetry comes from
the RTL decode, not from fitting the shipped references. A table typed into
pe_asm that happens to admit every reference is a fit; a table computed from
the expressions silicon evaluates is an anchor. This module is the second.

⭐ HOW IT IS DERIVED (each step needs its anchor TEXT present in
`src/pe_engine.v`, the way `hold_bound` reads SDA_HOLD; a missing anchor RAISES,
it never falls back to a typed table):

  A1  `localparam integer BPW   = <W>;`
        the count field is W bits, so every count lies in 0 .. 2^W - 1
  A2  `wire [BPW-1:0]   a_cnt   = cur_act[BQW +: BPW];`
        `a_cnt` IS that field (W bits: arithmetic on it wraps mod 2^W)
  A3  `wire ck_shift   = clk_real & a_lvl & (a_op == OP_SHIFT);`
      `wire ck_shiftin = clk_real & a_lvl & (a_op == OP_SHIFTIN);`
        the two counted opcodes are SHIFT and SHIFTIN; no other opcode feeds
        `ck_nbits`, so every other opcode has no count rule (full field)
  A4  `wire [BPW-1:0] ck_nbits = ck_shift ? (a_cnt + {{(BPW-1){1'b0}}, 1'b1})`
      `                                     : a_cnt;`
        bits moved: SHIFT = (count + 1) mod 2^W, SHIFTIN = count
  A5  `wire ck_degen = ck_act & (ck_nbits == {BPW{1'b0}});`
        a zero bit count is CONFIG_ERR (`ck_refuse = ck_degen | ...`)
  =>  SHIFT is legal iff (c + 1) mod 2^W != 0  ->  0 .. 2^W - 2   (15 wraps)
      SHIFTIN is legal iff c != 0                ->  1 .. 2^W - 1

⚠ SCOPE, STATED. `ck_degen` is a CLOCKED-action refusal (`ck_act`). The
UNCLOCKED forms count with the same arithmetic (A6/A7 below: the TX load at
`tx_bitp == a_cnt`, the RX push at `rx_bitp == a_cnt - 1`), so an unclocked
SHIFT at 15 or SHIFTIN at 0 is a 16-bit cycle over the 8-bit `l_tx`/`l_rx`
register: defined in silicon, NOT refused, and meaningless as a byte. pe_asm
applies the clocked range to both forms -- STRICTER than silicon on the
unclocked form, the safe direction (it can only refuse a program the chip
would run, never accept one the chip refuses). A6/A7 are anchored so that if
the unclocked arithmetic ever diverges from the clocked one, this reader stops.

  A6  `if (a_op == OP_SHIFT && (!ck_shift || ck_is_low) && tx_bitp[cur] == a_cnt) begin`
  A7  `if (rx_bitp[cur] == a_cnt - {{(BPW-1){1'b0}}, 1'b1}) begin`
"""

from __future__ import annotations

import io
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENGINE = os.path.join(ROOT, "src", "pe_engine.v")

#: (id, what it establishes, the exact substring that must be present)
ANCHORS = (
    ("A2", "a_cnt is the W-bit count field",
     "wire [BPW-1:0]   a_cnt   = cur_act[BQW +: BPW];"),
    ("A3a", "clocked SHIFT decode",
     "wire ck_shift   = clk_real & a_lvl & (a_op == OP_SHIFT);"),
    ("A3b", "clocked SHIFTIN decode",
     "wire ck_shiftin = clk_real & a_lvl & (a_op == OP_SHIFTIN);"),
    ("A4a", "SHIFT moves count + 1 bits (W-bit add, wraps)",
     "wire [BPW-1:0] ck_nbits = ck_shift ? (a_cnt + {{(BPW-1){1'b0}}, 1'b1})"),
    ("A4b", "SHIFTIN moves count bits",
     "                                     : a_cnt;"),
    ("A5", "zero bits is CONFIG_ERR",
     "wire ck_degen = ck_act & (ck_nbits == {BPW{1'b0}});"),
    ("A5b", "ck_degen is a refusal",
     "wire ck_refuse = ck_degen | ck_holdviol;"),
    ("A6", "unclocked SHIFT loads after count + 1 bits",
     "if (a_op == OP_SHIFT && (!ck_shift || ck_is_low) && tx_bitp[cur] == a_cnt) begin"),
    ("A7", "unclocked SHIFTIN pushes after count bits",
     "if (rx_bitp[cur] == a_cnt - {{(BPW-1){1'b0}}, 1'b1}) begin"),
)

#: the opcode values the ranges are keyed on (pe_isa's, checked equal to the
#: RTL's by gate_one_encoder)
OP_SHIFT, OP_SHIFTIN = 1, 2


class CountRangeError(RuntimeError):
    """The RTL could not be read, or no longer carries an anchor."""


def _text(engine_path=None, text=None):
    if text is not None:
        return text
    path = engine_path or ENGINE
    try:
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError as exc:
        raise CountRangeError("cannot read %s: %s" % (path, exc))


def anchors(engine_path=None, text=None):
    """-> [(id, what, line number)]; raises on the first missing anchor."""
    t = _text(engine_path, text)
    lines = t.splitlines()
    out = []
    m = re.search(r"localparam\s+integer\s+BPW\s*=\s*(\d+)\s*;", t)
    if m is None:
        raise CountRangeError("A1: src/pe_engine.v has no "
                              "`localparam integer BPW = <n>;` -- the count "
                              "field width cannot be read")
    out.append(("A1", "the count field is BPW = %s bits" % m.group(1),
                t[:m.start()].count("\n") + 1))
    for aid, what, sub in ANCHORS:
        ln = next((i + 1 for i, l in enumerate(lines) if sub in l), None)
        if ln is None:
            raise CountRangeError(
                "%s: anchor not found in src/pe_engine.v (%s): %r. The count "
                "range is DERIVED from this text; with it gone the derivation "
                "has no premise and pe_asm refuses rather than guess."
                % (aid, what, sub.strip()))
        out.append((aid, what, ln))
    # A4b must be the continuation of A4a (the ternary's else arm)
    a4a = next(l for a, _w, l in out if a == "A4a")
    a4b = next(l for a, _w, l in out if a == "A4b")
    if a4b != a4a + 1:
        raise CountRangeError("A4: the `: a_cnt;` arm is not the line after "
                              "`ck_nbits = ck_shift ? ...` (lines %d, %d)"
                              % (a4a, a4b))
    return out


def ranges(engine_path=None, text=None):
    """{OP_SHIFT: (lo, hi), OP_SHIFTIN: (lo, hi), None: (lo, hi)} -- None is
    every other opcode. Derived, never typed: see the module docstring."""
    t = _text(engine_path, text)
    anchors(text=t)
    w = int(re.search(r"localparam\s+integer\s+BPW\s*=\s*(\d+)\s*;", t).group(1))
    full = 1 << w
    nbits = {OP_SHIFT: lambda c: (c + 1) % full,      # A4a, W-bit wrap (A2)
             OP_SHIFTIN: lambda c: c}                  # A4b
    out = {None: (0, full - 1)}                        # A1, A3: no rule
    for op, f in nbits.items():
        legal = [c for c in range(full) if f(c) != 0]  # A5: zero = CONFIG_ERR
        lo, hi = min(legal), max(legal)
        if legal != list(range(lo, hi + 1)):
            raise CountRangeError("opcode %d: the legal counts are not one "
                                  "contiguous range: %s" % (op, legal))
        out[op] = (lo, hi)
    return out


if __name__ == "__main__":
    for aid, what, ln in anchors():
        print("  %-4s src/pe_engine.v:%-5d %s" % (aid, ln, what))
    r = ranges()
    print("  SHIFT %d..%d, SHIFTIN %d..%d, others %d..%d"
          % (r[OP_SHIFT] + r[OP_SHIFTIN] + r[None]))
