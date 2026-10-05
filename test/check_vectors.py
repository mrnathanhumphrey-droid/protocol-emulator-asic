"""EVERY END-TO-END PAYLOAD PATTERN MUST CONTAIN AN ASYMMETRIC BYTE (ruling 1b).

⛔⛔ WHY, FROM A FINDING THAT COST A FOREIGN DECODER TO SEE. `OP_SHIFT` emits
`l_tx[0]` first -- the engine was LSB-FIRST on the wire -- while `pe_isa.py`'s
own docstring claimed the lanes shift MSB-first. The contradiction sat there
undetected through the entire host-channel audit, and the reason is this:

    the only byte ever checked end to end was 0x5A, and
    0x5A reversed is 0x5A.

A BIT-REVERSAL PALINDROME passes under either bit order. `tb_smoke` and
`tb_trace` fed {5A, C3, 3C, A5} and `test.py` pushed the same four -- FOUR
PALINDROMES OUT OF FOUR, in three benches. Every one of those "the byte reached
the wire" results was true and said nothing whatever about order.

⇒ THE RULE: a pattern that a bench checks end to end must contain at least one
byte whose bit reversal differs from itself. A palindrome-only pattern is not a
weak test of order, it is NO test of order, and it reads exactly like a strong
one.

⚠ SCOPE, STATED. This checks the declared PAYLOAD PATTERNS -- `hf_set(...)` in
the Verilog benches and `HOST_PAT` in the cocotb suite -- and not every byte
literal in the tree. A mask, an idle level or a pin constant has no bit order
to get wrong, and flagging those would bury the real finding in noise.
"""

from __future__ import annotations

import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))


def rev8(b: int) -> int:
    return int("{:08b}".format(b & 0xFF)[::-1], 2)


def palindrome(b: int) -> bool:
    return rev8(b) == b


def patterns():
    """(file, line, label, [bytes]) for every declared payload pattern."""
    out = []
    for name in sorted(os.listdir(HERE)):
        path = os.path.join(HERE, name)
        if not os.path.isfile(path):
            continue
        if not (name.endswith(".v") or name.endswith(".vh")
                or name == "test.py"):
            continue
        with open(path, encoding="utf-8", errors="replace") as fh:
            src = fh.read()
        # the Verilog feeder: hf_set(q, b0, b1, b2, b3)
        for m in re.finditer(
                r"hf_set\s*\(\s*(\d+)\s*,\s*"
                + r"\s*,\s*".join([r"8'h([0-9A-Fa-f]{2})"] * 4) + r"\s*\)",
                src):
            ln = src[:m.start()].count("\n") + 1
            out.append((name, ln, "hf_set queue %s" % m.group(1),
                        [int(m.group(i), 16) for i in range(2, 6)]))
        # the cocotb feeder: HOST_PAT = [...]
        for m in re.finditer(r"HOST_PAT\s*=\s*\[([^\]]*)\]", src):
            ln = src[:m.start()].count("\n") + 1
            vals = [int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{2})",
                                                   m.group(1))]
            if vals:
                out.append((name, ln, "HOST_PAT", vals))
    return out


def selftest() -> int:
    """⛔ PRICE IT on the exact pattern that hid the defect."""
    rc = 0
    print()
    print("  --- must-fire: the rule rejects what it claims to ---")
    cases = (
        ("the pattern that hid it, {5A,C3,3C,A5}", [0x5A, 0xC3, 0x3C, 0xA5],
         False),
        ("one palindrome among asymmetric bytes", [0x5A, 0x01, 0x7A, 0xC7],
         True),
        ("the replacement, {5B,01,7A,C7}", [0x5B, 0x01, 0x7A, 0xC7], True),
        ("a single palindrome", [0x66], False),
        ("0x01, the asymmetric extreme", [0x01], True),
    )
    for label, vals, want_ok in cases:
        ok = any(not palindrome(b) for b in vals)
        agree = ok == want_ok
        print("    %-42s %-9s %s"
              % (label, "accepted" if ok else "REJECTED",
                 "ok" if agree else "*** wanted %s"
                 % ("accept" if want_ok else "reject")))
        if not agree:
            rc = 1
    # ⭐ AND THE REVERSAL ITSELF IS CHECKED, because the whole rule rests on it
    # and a wrong `rev8` would classify everything as asymmetric and pass
    # everything. Two known pairs and one fixed point.
    known = ((0x05, 0xA0), (0x01, 0x80), (0x5A, 0x5A))
    good = all(rev8(a) == b for a, b in known)
    print("    %-42s %s" % ("rev8 on known pairs 05/A0, 01/80, 5A/5A",
                            "ok" if good else "*** WRONG"))
    if not good:
        rc = 1
    return rc


def main() -> int:
    rc = 0
    print()
    print("=" * 78)
    print("TEST VECTORS -- no end-to-end pattern may be palindrome-only")
    print("=" * 78)
    pats = patterns()
    print("  declared payload patterns found : %d" % len(pats))
    if not pats:
        print("  *** NONE FOUND, which is a finding rather than a pass: the")
        print("      benches declare payload patterns by construction, so")
        print("      either they are gone or this scan no longer matches how")
        print("      they are written.")
        return 1
    print()
    print("  %-18s %-6s %-20s %s" % ("file", "line", "pattern", "bytes"))
    for name, ln, label, vals in pats:
        asym = [b for b in vals if not palindrome(b)]
        marks = " ".join("%02X%s" % (b, "" if not palindrome(b) else "(pal)")
                         for b in vals)
        ok = bool(asym)
        print("  %-18s %-6d %-20s %s  %s"
              % (name, ln, label, marks,
                 "ok" if ok else "*** PALINDROME-ONLY"))
        if not ok:
            print("      ⛔ every byte here equals its own bit reversal, so")
            print("         this pattern passes under EITHER bit order and")
            print("         tests nothing about order. Include an asymmetric")
            print("         byte -- 0x01 reverses to 0x80.")
            rc = 1
    rc |= selftest()
    print()
    print("=" * 78)
    print("  GATE test-vectors: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    ⚠ PASSED means each pattern COULD detect a bit-order error, not")
    print("      that any bench checks order. The order claims themselves are")
    print("      `test/run_i2c.py` (sigrok, MSB-first) and `tb_tx` (LSB-first).")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
