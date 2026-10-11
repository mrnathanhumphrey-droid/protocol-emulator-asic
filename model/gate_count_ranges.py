"""SP2/P1 -- pe_asm's per-opcode COUNT range is the RTL's, read from its decode.

THE CLAIM (Wilson's condition on accepting the per-opcode range): the ranges
pe_asm enforces -- SHIFT 0..14, SHIFTIN 1..15, every other opcode 0..15 -- are
DERIVED from text anchors in `src/pe_engine.v` (`model/count_ranges.py`:
BPW, `a_cnt`, `ck_shift`/`ck_shiftin`, `ck_nbits`, `ck_degen`, `ck_refuse`,
and the unclocked TX-load / RX-push compares), not fitted to the references.

CHECKS (each positive):
  1  every anchor is present; its file:line is printed
  2  the derived table equals the RULED table (Wilson): SHIFT 0..14,
     SHIFTIN 1..15, others 0..15 -- a derivation that moved is red here, not
     silently adopted by pe_asm
  3  pe_isa's count-field width (CNT_W) equals the RTL's BPW
  4  pe_asm's split_counts accepts both ends of every derived range
MUST-FIRES (positive evidence of red):
  M1  SHIFT count 15 is refused by pe_asm, naming the count
  M2  SHIFTIN count 0 is refused by pe_asm, naming the count
  M3  the derivation on a MUTATED copy of the RTL text (`ck_nbits` without the
      `+ 1`) raises -- the anchor is load-bearing, not decorative
  M4  the derivation on a copy with `ck_degen` removed raises

POSITIVE TOKEN: `GATE count-ranges: PASSED` only on the success path.
"""

from __future__ import annotations

import io
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "test"))

import count_ranges as CR                     # noqa: E402
import pe_asm                                 # noqa: E402
import pe_isa                                 # noqa: E402

#: the table Wilson RULED (accepted conditionally); checked equal to the
#: derivation, never used as the source
RULED = {pe_isa.OP_SHIFT: (0, 14), pe_isa.OP_SHIFTIN: (1, 15), None: (0, 15)}


def main() -> int:
    print("=" * 78)
    print("  SP2/P1 -- pe_asm count ranges, derived from src/pe_engine.v")
    print("=" * 78)
    rc = 0
    try:
        anc = CR.anchors()
    except CR.CountRangeError as exc:
        print("  *** %s" % exc)
        print("  *** GATE count-ranges: FAILED")
        return 1
    for aid, what, ln in anc:
        print("    %-4s src/pe_engine.v:%-5d %s" % (aid, ln, what))
    der = CR.ranges()
    ok = (CR.OP_SHIFT == pe_isa.OP_SHIFT and CR.OP_SHIFTIN == pe_isa.OP_SHIFTIN
          and der == RULED)
    print("  derived : SHIFT %d..%d, SHIFTIN %d..%d, others %d..%d"
          % (der[CR.OP_SHIFT] + der[CR.OP_SHIFTIN] + der[None]))
    print("  ruled   : SHIFT %d..%d, SHIFTIN %d..%d, others %d..%d   %s"
          % (RULED[pe_isa.OP_SHIFT] + RULED[pe_isa.OP_SHIFTIN] + RULED[None]
             + ("equal" if ok else "*** DIFFER",)))
    rc |= 0 if ok else 1
    w = (der[None][1] + 1).bit_length() - 1
    okw = w == pe_isa.CNT_W
    print("  pe_isa.CNT_W = %d, RTL BPW = %d   %s"
          % (pe_isa.CNT_W, w, "equal" if okw else "*** DIFFER"))
    rc |= 0 if okw else 1

    def split(op, cnt):
        lvl = 1 if op in (pe_isa.OP_SHIFT, pe_isa.OP_SHIFTIN) else 0
        return pe_asm.split_counts({0: [(op, 2, lvl, 25, 0, cnt)]})

    # both ends of every range accepted (a refusal too wide is red too)
    for op, nm in ((pe_isa.OP_SHIFT, "SHIFT"), (pe_isa.OP_SHIFTIN, "SHIFTIN"),
                   (pe_isa.OP_LEVEL, "LEVEL"), (pe_isa.OP_REARM, "REARM")):
        lo, hi = der.get(op, der[None])
        try:
            split(op, lo)
            split(op, hi)
            print("    %-8s count %2d and %2d accepted" % (nm, lo, hi))
        except pe_asm.Reject as e:
            print("    *** %s end of range refused: %s" % (nm, str(e)[:70]))
            rc = 1

    print("  --- must-fires ---")
    for tag, op, cnt, nm in (("M1", pe_isa.OP_SHIFT, 15, "SHIFT count 15"),
                             ("M2", pe_isa.OP_SHIFTIN, 0, "SHIFTIN count 0")):
        try:
            split(op, cnt)
            print("  *** %s %s ACCEPTED -- the refusal does not fire"
                  % (tag, nm))
            rc = 1
        except pe_asm.Reject as e:
            good = ("count %d" % cnt) in str(e) and "ck_degen" in str(e)
            print("    %s %-16s REFUSED%s" % (tag, nm, "" if good else
                  " *** but did not name the count / the RTL source"))
            print("       %s" % str(e)[:96])
            rc |= 0 if good else 1
    with io.open(CR.ENGINE, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    for tag, old, new, why in (
            ("M3", "(a_cnt + {{(BPW-1){1'b0}}, 1'b1})", "(a_cnt)",
             "ck_nbits without the + 1"),
            ("M4", "wire ck_degen = ck_act & (ck_nbits == {BPW{1'b0}});",
             "wire ck_degen = 1'b0;", "ck_degen removed")):
        if old not in text:
            print("  *** %s: the mutation site is not in the RTL" % tag)
            rc = 1
            continue
        try:
            CR.ranges(text=text.replace(old, new, 1))
            print("  *** %s (%s): the derivation still produced a table"
                  % (tag, why))
            rc = 1
        except CR.CountRangeError as e:
            print("    %s %-26s derivation RAISES (%s)" % (tag, why,
                                                         str(e)[:46]))
    print()
    if rc == 0:
        print("  GATE count-ranges: PASSED")
        return 0
    print("  *** GATE count-ranges: FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
