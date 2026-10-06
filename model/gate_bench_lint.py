"""A CHECK THAT CANNOT FIRE READS EXACTLY LIKE A CHECK THAT PASSED.

⛔⛔ TWO INSTANCES IN ONE FILE, DAYS APART, BOTH SILENT. `test/progress.vh` is
the bench watchdog, and on its first run it checked NOTHING on all twelve
benches:

  1. THE HIERARCHICAL LOCALPARAM. The hook read
         dut.u_eng.st === dut.u_eng.ST_WB
     A hierarchical reference to a `localparam` compiled without a warning and
     the comparison was NEVER TRUE. The watchdog ran everywhere and saw nothing.
     ⇒ Fixed by the literal `2'd2` with the encoding cited in a comment.

  2. THE BRACE-CONCATENATED FORMAT STRING. Every
         $display({"a %0d ", "b %0d"}, x, y)
     printed NOTHING, while the counter beside it incremented 144 times. A
     failure that counts itself silently is indistinguishable from a pass.
     ⇒ Fixed by making every format string one plain literal.

Both have the same shape: the checker is present, runs, and is incapable of
speaking. Neither was caught by a test -- the first by adding a writeback
counter, the second by noticing a counter disagree with the log. This gate is
the cheap guard that stops the class recurring.

⚠ WHAT IT IS NOT: a Verilog parser. It is a textual scan over the bench sources
for two specific, recognisable shapes. It will not catch every way to write a
vacuous check, and claiming otherwise would be the same kind of false comfort.
"""
import io
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TESTD = os.path.join(ROOT, "test")

#: A comparison against an UPPERCASE name reached THROUGH a hierarchy -- i.e.
#: `dut.something.NAME`. Lowercase hierarchical names are regs and wires and
#: are fine; the uppercase convention is what marks a parameter here.
HIER_PARAM = re.compile(
    r"[=!]==?\s*(dut(?:\.[A-Za-z_][A-Za-z_0-9]*)*\.[A-Z][A-Z_0-9]{2,})\b")
#: ... and the same thing on the LEFT of the comparison.
HIER_PARAM_L = re.compile(
    r"(dut(?:\.[A-Za-z_][A-Za-z_0-9]*)*\.[A-Z][A-Z_0-9]{2,})\s*[=!]==?")
#: `$display({` -- a format string assembled by concatenation.
BRACE_FMT = re.compile(r"\$(?:display|write|fatal|error)\s*\(\s*\{")


def strip_comments(lines):
    """Code only, with `//` AND `/* ... */` removed.

    ⛔⛔ THE FIRST VERSION HANDLED ONLY `//`, and it immediately flagged this
    gate's own subject matter: `test/progress.vh` documents both defects inside
    a `/* ... */` header, so the scan reported the PROSE DESCRIBING the bug as
    the bug. A linter that fires on its own documentation trains people to
    ignore it, which is worse than not having one.
    ⚠ Block comments are STATEFUL across lines, so this cannot be a per-line
    function -- which is exactly why the first version got it wrong.
    """
    out, in_block = [], False
    for raw in lines:
        buf, i, n = [], 0, len(raw)
        while i < n:
            if in_block:
                j = raw.find("*/", i)
                if j < 0:
                    i = n
                else:
                    in_block = False
                    i = j + 2
            elif raw.startswith("//", i):
                break
            elif raw.startswith("/*", i):
                in_block = True
                i += 2
            else:
                buf.append(raw[i])
                i += 1
        out.append("".join(buf))
    return out


def sources():
    out = []
    for fn in sorted(os.listdir(TESTD)):
        if fn.endswith((".v", ".vh")) and not fn.startswith("probe_"):
            out.append(os.path.join("test", fn))
    return out


def scan(rel, lines):
    """(hier_param_hits, brace_fmt_hits) for one file."""
    hp, bf = [], []
    for n, code in enumerate(strip_comments(lines), 1):
        for m in HIER_PARAM.finditer(code):
            hp.append((n, m.group(1), code.strip()[:58]))
        for m in HIER_PARAM_L.finditer(code):
            hp.append((n, m.group(1), code.strip()[:58]))
        if BRACE_FMT.search(code):
            bf.append((n, code.strip()[:58]))
    return hp, bf


def selftest():
    """⛔ PRICE BOTH DETECTORS on the exact text that fooled the watchdog."""
    print()
    print("  --- must-fire: the two real defects are detected ---")
    rc = 0
    cases = [
        ("the hierarchical localparam, as written",
         ["  end else if (pg_armed && dut.u_eng.st === dut.u_eng.ST_WB) begin"],
         "hier", True),
        ("the same with the parameter on the LEFT",
         ["    if (dut.u_eng.ST_WB === dut.u_eng.st) begin"],
         "hier", True),
        ("a literal comparison is accepted",
         ["  end else if (dut.u_eng.st === 2'd2) begin"],
         "hier", False),
        ("a lowercase hierarchical wire is accepted",
         ["    if (dut.u_eng.clk_real === 1'b1) begin"],
         "hier", False),
        ("a hierarchical parameter inside a // COMMENT is accepted",
         ["    // was dut.u_eng.ST_WB === dut.u_eng.st, see the header"],
         "hier", False),
        ("... and inside a /* */ BLOCK comment, over several lines",
         ["/* the hook first read", "   dut.u_eng.st === dut.u_eng.ST_WB",
          "   which never matched. */"],
         "hier", False),
        ("... and a braced $display inside a block comment",
         ["/* it was $display({\"a %0d \", \"b\"}, x); */"],
         "brace", False),
        ("code AFTER a block comment closes is still scanned",
         ["/* note */ if (dut.u_eng.st === dut.u_eng.ST_WB) begin"],
         "hier", True),
        ("the brace-concatenated format string, as written",
         ['        $display({"FAIL a %0d ", "b %0d"}, x, y);'],
         "brace", True),
        ("a plain format string is accepted",
         ['        $display("FAIL a %0d b %0d", x, y);'],
         "brace", False),
    ]
    for label, lines, kind, want in cases:
        hp, bf = scan("probe", lines)
        got = bool(hp) if kind == "hier" else bool(bf)
        ok = (got == want)
        print("    %-52s %s" % (label, "ok" if ok else
                                "*** wanted %s" % ("a hit" if want else "none")))
        if not ok:
            rc = 1
    return rc


def main():
    print()
    print("=" * 78)
    print("BENCH LINT -- a check that cannot fire reads like a check that passed")
    print("=" * 78)
    rc = 0
    files = sources()
    if not files:
        print("  *** no bench sources found, which is a finding rather than a")
        print("      pass: this gate would report clean on an empty scan.")
        return 1
    print("  scanned %d bench source(s)" % len(files))
    print()
    print("  --- comparisons against a hierarchical parameter ---")
    nhp = 0
    for rel in files:
        with io.open(os.path.join(ROOT, rel), encoding="utf-8",
                     errors="replace") as fh:
            lines = fh.read().splitlines()
        hp, _bf = scan(rel, lines)
        for n, name, code in hp:
            nhp += 1
            print("    *** %s:%d  compares against `%s`" % (rel, n, name))
            print("        %s" % code)
            print("        ⛔ A hierarchical reference to a parameter compiles")
            print("           and silently never matches. Use the literal")
            print("           encoding and CITE the source in a comment.")
            rc = 1
    if not nhp:
        print("    none -- every comparison uses a literal or a signal")
    print()
    print("  --- $display format strings assembled by concatenation ---")
    nbf = 0
    for rel in files:
        with io.open(os.path.join(ROOT, rel), encoding="utf-8",
                     errors="replace") as fh:
            lines = fh.read().splitlines()
        _hp, bf = scan(rel, lines)
        for n, code in bf:
            nbf += 1
            print("    *** %s:%d  %s" % (rel, n, code))
            print("        ⛔ A brace-concatenated format string prints NOTHING")
            print("           while the code around it runs. Use one literal.")
            rc = 1
    if not nbf:
        print("    none -- every format string is a single literal")

    rc |= selftest()
    print()
    print("=" * 78)
    print("  GATE bench-lint: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    ⚠ A TEXTUAL SCAN FOR TWO KNOWN SHAPES, not a parser. It stops")
    print("      these two from recurring; it does not prove a checker can")
    print("      fire. Only a must-fire does that.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
