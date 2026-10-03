"""RULING F2 -- EVERY ENGINE-DRIVEN OUTPUT PIN COMES FROM A FLOP. Statically.

THE ONE CLAIM: for every bit of `uo_out`, `uio_out` and `uio_oe`, the path back
from the pin reaches a flip-flop without passing through a multi-input
combinational cell -- checked on the NETLIST, not on the RTL.

⛔⛔ THE REASON IS CORRECTNESS, NOT TIMING, AND THAT IS WHY IT IS A STATIC CHECK
RATHER THAN AN SDC CONSTRAINT. A combinational output GLITCHES while its inputs
settle. A glitch on SCLK is an EXTRA CLOCK EDGE, and an extra edge does not
degrade a transfer, it corrupts it -- the peer shifts in one bit too many and
every byte after it is wrong. No amount of setup/hold margin addresses that,
because the glitch is inside the cycle.

⛔ AND I2C's SPIKE FILTER IS NOT A DEFENCE. `T_SP` = 50 ns swallows spikes
shorter than itself, which means a device MAY ignore our glitch. That is the
device's mercy, not a property of our design, and it is 50 ns on a 20 ns clock
grid -- a two-cycle glitch is inside the filter, a three-cycle one is not. Relying
on it would make correctness a function of the peer's input stage.

⭐ WHY A BUFFER CHAIN IS STILL COMPLIANT. A single-input cell (buffer, inverter,
delay cell) cannot create a glitch: its output transitions once per input
transition. So the walk back from the pin passes THROUGH single-input cells and
stops at the first cell with two or more inputs. That is the real property --
"no combinational RECONVERGENCE on an output path" -- and "driven by a flop" is
its shorthand.

⛔⛔ UNKNOWN CELLS FAIL CLOSED, AND THIS IS THE DESIGN DECISION THAT MATTERS. A
checker that skips cells it does not recognise reports PASS on a netlist full of
cells it has never seen, which is a guard passing because of its own blind spot.
Every cell this tool classifies is listed in its output, and anything
unclassified is reported as a FINDING with its name, so the list grows by being
forced to.

⚠ NOT IN CI, SAID PLAINLY. The gate-level netlist is produced by a third-party
GitHub Action (`TinyTapeout/tt-gds-action`) and exists only inside its uploaded
artifact; `test/gate_level_netlist.v` is gitignored. So this runs by hand against
a downloaded artifact, exactly like `model/a4_precondition.py`. Its `--selftest`
needs no artifact and is what makes the checker itself priced.

Usage:
    python model/f2_flop_driven_outputs.py <netlist.v>
    python model/f2_flop_driven_outputs.py --selftest
"""

from __future__ import annotations

import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Pins that are engine-driven outputs. `uio_oe` is included because an enable
# glitch RELEASES or ASSERTS a pin for a moment, which on an open-drain bus is
# indistinguishable from driving it.
OUT_PORTS = ("uo_out", "uio_out", "uio_oe")

# ---- cell classification. Pattern -> kind. FIRST MATCH WINS. --------------
# ⛔⛔ ORDER MATTERS AND GETTING IT WRONG WAS UNSAFE. The first version put the
# flop pattern first as `(^|_)(df|dl|sdf|sdl)`, and `dl` MATCHED `_dlygate4sd3_1`
# -- so the 555 hold-fix delay cells in this design classified as FLOPS. The
# trace then STOPPED at the delay cell and never walked back to see what drove
# it, which is wrong in the direction that matters: a combinational path hidden
# behind a hold-fix buffer would have read as compliant. Buffers and delays are
# matched FIRST, by their specific names, and the flop pattern is narrowed.
#
# ⛔⛔ AND THE COMBINATIONAL FAMILY HAS TO BE NAMED EXPLICITLY. Without it every
# and2/mux2/nand fell through to "unknown", so all three mutants below died with
# the SAME finding -- "UNKNOWN-CELL" -- rather than for their stated reasons.
# Three mutants dying for one reason is one mutant, and it made the
# unknown-cell arm vacuous because nothing distinguished it.
CELL_KINDS = [
    (r"(^|_)(dly|dlygate|dlymetal|dlclkp|buf|bufbuf|clkbuf|clkdly)", "buffer"),
    (r"(^|_)(inv|clkinv|einvp|einvn)", "inverter"),
    (r"(^|_)(conb|tiehi|tielo|tie)", "constant"),
    # flops and latches: narrowed so it cannot swallow `dly*`
    (r"(^|_)(dfr|dfs|dfb|dfx|dfbb|dff|sdfr|sdfs|sdff|dlxt|dlrt|dlyt|sdl)",
     "flop"),
    # the ordinary combinational families, so a mutant dies for its own reason
    (r"(^|_)(and\d|or\d|nand\d|nor\d|xor\d|xnor\d|mux\d|mux4|a\d+o|a\d+oi|"
     r"o\d+a|o\d+ai|maj\d|fa|ha|einv|dlygate4s)", "comb"),
]
SINGLE_INPUT = {"buffer", "inverter"}

INST_RE = re.compile(
    r"^\s*([A-Za-z_][\w$]*)\s+([A-Za-z_\\][\w$\\\[\]\.]*)\s*\((.*?)\)\s*;",
    re.S | re.M)
CONN_RE = re.compile(r"\.\s*([\w$]+)\s*\(\s*([^()]*?)\s*\)")
OUT_PORT_NAMES = {"X", "Y", "Q", "Q_N", "QN", "Z", "COUT", "SUM", "HI", "LO"}


def classify(cell: str) -> str:
    c = cell.lower()
    for pat, kind in CELL_KINDS:
        if re.search(pat, c):
            return kind
    return "unknown"


def parse(text: str) -> tuple:
    """(drivers, instances) -- drivers maps a net to (cell, kind, inputs)."""
    # strip comments so a commented-out instance is not parsed
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    drivers, insts = {}, []
    for cell, inst, body in INST_RE.findall(text):
        if cell in ("module", "input", "output", "wire", "assign", "endmodule"):
            continue
        conns = CONN_RE.findall(body)
        if not conns:
            continue
        kind = classify(cell)
        outs = [(p, n) for p, n in conns if p.upper() in OUT_PORT_NAMES]
        ins = [n for p, n in conns if p.upper() not in OUT_PORT_NAMES]
        insts.append((cell, inst, kind, len(ins)))
        for _p, net in outs:
            drivers[net.strip()] = (cell, kind, [i.strip() for i in ins])
    # continuous assignments: `assign a = b;` is a rename, not a cell
    for lhs, rhs in re.findall(r"assign\s+([\w$\[\]\.]+)\s*=\s*([^;]+);", text):
        r = rhs.strip()
        if re.match(r"^[\w$\[\]\.]+$", r):
            drivers.setdefault(lhs.strip(), ("assign", "buffer", [r]))
    return drivers, insts


def trace(net: str, drivers: dict, depth: int = 0) -> tuple:
    """Walk back to a flop. Returns (verdict, path). Fail-closed on unknown."""
    if depth > 64:
        return "LOOP", [net]
    d = drivers.get(net)
    if d is None:
        return "UNDRIVEN", [net]
    cell, kind, ins = d
    here = "%s(%s)" % (cell, kind)
    if kind == "flop":
        return "FLOP", [net, here]
    if kind == "constant":
        return "CONST", [net, here]
    if kind in SINGLE_INPUT and len(ins) == 1:
        v, p = trace(ins[0], drivers, depth + 1)
        return v, [net, here] + p
    if kind == "unknown":
        return "UNKNOWN-CELL", [net, here]
    # multi-input, or a single-input-classified cell wired with several inputs
    return "COMBINATIONAL", [net, here + "x%d-in" % len(ins)]


def check(text: str, label: str, expect_verdict: str | None = None) -> int:
    """⛔ `expect_verdict` certifies a mutant kill BY ITS STATED REASON. A colour
    cannot certify a reason: three mutants that all die as "UNKNOWN-CELL" are one
    mutant wearing three hats, and that is what the first version of this file
    did."""
    drivers, insts = parse(text)
    print("  %s" % label)
    print("    instances parsed: %d" % len(insts))
    kinds = {}
    for _c, _i, k, _n in insts:
        kinds[k] = kinds.get(k, 0) + 1
    print("    by kind: %s"
          % ", ".join("%s=%d" % kv for kv in sorted(kinds.items())))
    unknown = sorted({c for c, _i, k, _n in insts if k == "unknown"})
    if unknown:
        print("    ⛔ UNCLASSIFIED CELLS (fail-closed, named so the list can")
        print("       grow): %s" % ", ".join(unknown[:12]))

    targets = [n for n in drivers if any(n.startswith(p) for p in OUT_PORTS)]
    targets += [n for p in OUT_PORTS for n in drivers
                if n == p and n not in targets]
    targets = sorted(set(targets))
    if not targets:
        print("    *** no %s nets found -- this is not the netlist we think it"
              % "/".join(OUT_PORTS))
        print("        is, and a check that found nothing to check has not run")
        return 1
    bad = []
    for net in targets:
        v, path = trace(net, drivers)
        ok = v in ("FLOP", "CONST")
        if not ok:
            bad.append((net, v, path))
        print("    %-16s %-14s %s" % (net, v, " <- ".join(path[1:]) or "-"))
    print()
    if expect_verdict is not None:
        got = sorted({v for _n, v, _p in bad})
        if got != [expect_verdict]:
            print("    *** WRONG REASON: expected every failure to be %r, got %s"
                  % (expect_verdict, got or "no failures"))
            print("        The mutant may have died, but not for the reason it")
            print("        was written to test -- so the arm certifies nothing.")
            return 2
        print("    reason certified: every failure is %r, as stated"
              % expect_verdict)
    if bad:
        print("    *** FAIL: %d output bit(s) are not flop-driven:" % len(bad))
        for net, v, path in bad:
            print("      %-16s %-14s %s" % (net, v, " <- ".join(path[1:])))
        print("      A combinational output can GLITCH, and a glitch on a clock")
        print("      pin is an extra edge. Not a margin problem -- a corruption.")
        return 1
    print("    => every output bit traces to a flop (or a tie) through")
    print("       single-input cells only. No combinational reconvergence.")
    return 0


# ============================================================================
# SYNTHETIC NETLISTS -- so the checker is priced without the artifact
# ============================================================================
GOOD = """
module tt_um_x (uo_out, uio_out, uio_oe, clk);
  sg13cmos5l_dfrbpq_1 ff0 (.CLK(clk), .D(d0), .RESET_B(rb), .Q(q0));
  sg13cmos5l_buf_2    b0  (.A(q0), .X(n1));
  sg13cmos5l_dlygate4sd3_1 dly0 (.A(n1), .X(uo_out[0]));
  sg13cmos5l_dfrbpq_1 ff1 (.CLK(clk), .D(d1), .RESET_B(rb), .Q(uio_out[0]));
  sg13cmos5l_dfrbpq_1 ff2 (.CLK(clk), .D(d2), .RESET_B(rb), .Q(uio_oe[0]));
endmodule
"""

# the mutant F2 exists to catch: a 2-input gate driving a protocol pin
MUTANT_COMB = """
module tt_um_x (uo_out, uio_out, uio_oe, clk);
  sg13cmos5l_dfrbpq_1 ff0 (.CLK(clk), .D(d0), .RESET_B(rb), .Q(q0));
  sg13cmos5l_dfrbpq_1 ff1 (.CLK(clk), .D(d1), .RESET_B(rb), .Q(q1));
  sg13cmos5l_and2_1   a0  (.A(q0), .B(q1), .X(uio_out[0]));
  sg13cmos5l_dfrbpq_1 ff2 (.CLK(clk), .D(d2), .RESET_B(rb), .Q(uo_out[0]));
  sg13cmos5l_dfrbpq_1 ff3 (.CLK(clk), .D(d3), .RESET_B(rb), .Q(uio_oe[0]));
endmodule
"""

# the SHIPPED design's shape: uio_out tied to 0, readback COMBINATIONAL from mem
MUTANT_SHIPPED = """
module tt_um_x (uo_out, uio_out, uio_oe, clk);
  sg13cmos5l_tiehi t0 (.HI(uio_out[0]));
  sg13cmos5l_mux2_1 m0 (.A0(a), .A1(b), .S(s), .X(uo_out[0]));
  sg13cmos5l_dfrbpq_1 ff0 (.CLK(clk), .D(d0), .RESET_B(rb), .Q(uio_oe[0]));
endmodule
"""

# a netlist using a cell the classifier has never seen
MUTANT_UNKNOWN = """
module tt_um_x (uo_out, uio_out, uio_oe, clk);
  sg13cmos5l_frobnicator_7 fz (.A(a), .X(uo_out[0]));
  sg13cmos5l_dfrbpq_1 ff1 (.CLK(clk), .D(d1), .RESET_B(rb), .Q(uio_out[0]));
  sg13cmos5l_dfrbpq_1 ff2 (.CLK(clk), .D(d2), .RESET_B(rb), .Q(uio_oe[0]));
endmodule
"""


def selftest() -> int:
    print()
    print("=" * 78)
    print("RULING F2 -- the flop-driven-output check, both faces")
    print("=" * 78)
    rc = 0
    print()
    print("  --- face 1: a compliant netlist must PASS ---")
    if check(GOOD, "synthetic: flop -> buf -> dly -> pin") != 0:
        print("    *** FAIL: the compliant case was rejected. A check that")
        print("        reds a correct netlist will be switched off.")
        rc = 1
    else:
        print("    ⭐ note it passed THROUGH a buffer and a hold-fix delay cell.")
        print("    This design has 555 dlygate4sd3_1; a checker that called")
        print("    those combinational would red the real netlist wrongly.")

    print()
    print("  --- face 2: MUST-FIRE, a 2-input gate on a protocol pin ---")
    if check(MUTANT_COMB, "mutant: and2_1 drives uio_out[0]",
             expect_verdict="COMBINATIONAL") != 1:
        print("    *** FAIL: the mutant survived, or died for another reason.")
        rc = 1
    else:
        print("    MUST-FIRE PASSED -- this is the mutant the ruling names.")

    print()
    print("  --- face 3: the SHIPPED design's own shape must fail ---")
    if check(MUTANT_SHIPPED, "mutant: mux2_1 readback -> uo_out (today's RTL)",
             expect_verdict="COMBINATIONAL") != 1:
        print("    *** FAIL: the readback mux survived, or died wrongly. ***")
        rc = 1
    else:
        print("    ⭐⭐ THIS IS THE REAL DESIGN TODAY, AND IT FAILS -- which is")
        print("    the point. `uo_out = mem[rd_ptr]` is the 18.4388-of-20 ns")
        print("    feedthrough, and F2 is the ruling that retires it. The check")
        print("    is expected RED against the current netlist and must go")
        print("    green once the readback is registered. That makes it a")
        print("    FALSIFIABLE acceptance test for F2 rather than a lint.")
        print("    ⚠ uio_out tied high reads as CONST and is allowed: a tie")
        print("    cannot glitch. The shipped design ties it LOW, same reason.")

    print()
    print("  --- face 4: an unknown cell must FAIL CLOSED ---")
    if check(MUTANT_UNKNOWN, "mutant: an unclassified cell drives uo_out[0]",
             expect_verdict="UNKNOWN-CELL") != 1:
        print("    *** FAIL: an unrecognised cell was treated as compliant.")
        print("        That is a guard passing because of its own blind spot.")
        rc = 1
    else:
        print("    FAILS CLOSED, and names the cell so the pattern list grows")
        print("    by being forced to rather than by being remembered.")

    print()
    print("=" * 78)
    print("  GATE F2-selftest: %s" % ("PASSED -- compliant passes, three "
                                      "mutants die, unknown fails closed"
                                      if rc == 0 else "FAILED"))
    return rc


def main(argv) -> int:
    if not argv or argv[0] == "--selftest":
        return selftest()
    path = argv[0]
    if not os.path.isfile(path):
        print("  *** netlist not found: %s" % path)
        print("  The gate-level netlist comes from the tt-gds-action artifact;")
        print("  test/gate_level_netlist.v is gitignored. Download it first.")
        return 1
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    print()
    print("=" * 78)
    print("RULING F2 -- flop-driven outputs, on %s" % os.path.basename(path))
    print("=" * 78)
    return check(text, path)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
