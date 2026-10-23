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
    # ⭐⭐ YOSYS GENERIC CELLS FIRST, so this checker can run on a LOCAL
    # synthesis instead of only on a CI artefact. ⛔ THE REASON IS A MEASURED
    # ONE: face 3 is a check on a gate-level netlist, the netlist only existed
    # after a ~2-HOUR harden, and when it finally arrived it found a real defect
    # (all 16 uio bits combinationally gated by a raw async input). A checker
    # whose feedback loop is two hours is a checker that gets run once.
    # `yosys -p 'synth -top ...; write_verilog'` produces these names, so the
    # same classifier now answers in seconds locally and against the PDK
    # netlist in CI.
    # ⚠ A LOCAL RUN IS NOT A SUBSTITUTE: generic cells are pre-technology
    # mapping, so a local PASS does not prove the PDK netlist passes. It catches
    # the structural error -- a pin driven by a function instead of a register --
    # which is exactly what F2 is about.
    (r"^\$_(dffe?|sdffe?|dffsre|aldff|dlatch|ff)_", "flop"),
    (r"^\$_(not|buf)_", "inverter"),
    (r"^\$_(and|or|nand|nor|xor|xnor|andnot|ornot|mux|nmux|aoi3|oai3|"
     r"aoi4|oai4|mux4|mux8|mux16)_", "comb"),
    (r"(^|_)(dly|dlygate|dlymetal|dlclkp|buf|bufbuf|clkbuf|clkdly)", "buffer"),
    (r"(^|_)(inv|clkinv|einvp|einvn)", "inverter"),
    (r"(^|_)(conb|tiehi|tielo|tie)", "constant"),
    # ⛔ PHYSICAL-ONLY CELLS, named so the UNKNOWN list stays empty of EXPECTED
    # entries. The first real netlist contained 124 `sg13cmos5l_antennanp`
    # (antenna-effect protection diodes) and F2 reported them as unclassified.
    # It failed CLOSED and the verdict was unaffected -- none of them sits in an
    # output path -- but an unknown list that always has one expected member
    # trains you to skip reading it, and the next genuinely new cell would be
    # skipped with it. ⭐ `physical` is NOT a driver: it is still fail-closed if
    # anything ever traces THROUGH one, which would mean a protection diode had
    # landed in a signal path.
    (r"(^|_)(antenna|diode|fill|decap|tapvpwrvgnd|tap)", "physical"),
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
# ⛔⛔ `L_HI`/`L_LO` ADDED AFTER THE FIRST REAL NETLIST, and the omission
# produced a FALSE POSITIVE rather than a false negative -- which is the whole
# design of this checker working. IHP's tie cells are
# `sg13cmos5l_tiehi(.L_HI(...))` / `tielo(.L_LO(...))`, and `L_LO` is not `LO`.
# With the port unrecognised the instance contributed NO driver, so the net
# looked UNDRIVEN and `uo_out[7]` -- the deliberately tied spare pin -- was
# reported as a violation.
# ⭐ IT FAILED CLOSED, which is why this is a classifier fix and not a scare.
# The header's rule is "a registered value OR a constant tie"; a tie cell cannot
# glitch, so recognising it is correct and does NOT weaken the check. An
# genuinely floating output still reports UNDRIVEN, because nothing drives it at
# all -- the two cases stay distinguishable.
# ⚠ The full port-name set was taken from the netlist itself (every `.NAME(`
# occurrence, counted) rather than from memory of a library.
OUT_PORT_NAMES = {"X", "Y", "Q", "Q_N", "QN", "Z", "COUT", "SUM", "HI", "LO",
                  "L_HI", "L_LO"}


def classify(cell: str) -> str:
    c = cell.lower()
    for pat, kind in CELL_KINDS:
        if re.search(pat, c):
            return kind
    return "unknown"


# ===========================================================================
# THE JSON PATH -- the same question, answerable LOCALLY in seconds
# ===========================================================================
# ⛔⛔ WHY THIS EXISTS, AND IT IS THE WHOLE LESSON OF FACE 3. This check needs a
# gate-level netlist; the only netlist was a CI artefact behind a ~2-hour
# harden; so face 3 sat as a PREDICTION from S3 until the harden finally ran --
# and when it ran it found 16 output bits combinationally gated by `prog_mode`,
# a RAW ASYNCHRONOUS INPUT PIN, with SCL and SCLK in that bank. A check whose
# feedback loop is two hours is a check that runs once, late.
#
# ⛔ AND `write_verilog` CANNOT SERVE: yosys renders its own internal cells
# ($_DFFE_PP_, $_MUX_, ...) as behavioural `always`/`assign` blocks, so the
# emitted file contains ZERO instances and the anti-vacuity guard below
# correctly refuses it. `write_json` keeps the cell graph, which is what a
# structural question actually needs.
#
# ⚠ A LOCAL PASS IS NOT A PDK PASS. These are pre-technology-mapping cells, and
# only the real flow produces `sg13cmos5l_*`. What it catches is the STRUCTURAL
# error F2 is about -- a pin driven by a function rather than by a register --
# which is exactly the error that took two hours to find the first time.
_JSON_FLOP = ("$_dff", "$_sdff", "$_dffe", "$dff", "$_aldff", "$_dlatch",
              "$_ff", "$_dffsr")


def json_verdict(path: str):
    """(status, info, bad) for a yosys JSON netlist. status: "ok", "comb" (bits
    driven by a function -- THE F2 failure), or a structural refusal
    "no_top" / "no_port" / "shape". gate_f2_local's mutant must be "comb":
    rc == 1 alone also accepted a netlist that failed for being the wrong
    netlist (10-22 must-fire audit)."""
    import json
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    mods = d.get("modules", {})
    top = "tt_um_protocol_emulator"
    if top not in mods:
        return "no_top", {"modules": list(mods)[:4]}, []
    m = mods[top]
    drv = {}
    for _cn, c in m["cells"].items():
        pd = c.get("port_directions", {})
        for port, bits in c["connections"].items():
            if pd.get(port) == "output":
                for b in bits:
                    if isinstance(b, int):
                        drv[b] = c["type"]
    info = {"cells": len(m["cells"]), "driven": len(drv), "checked": 0}
    bad = []
    for pname in ("uo_out", "uio_out", "uio_oe"):
        if pname not in m["ports"]:
            info["port"] = pname
            return "no_port", info, []
        for i, b in enumerate(m["ports"][pname]["bits"]):
            info["checked"] += 1
            if not isinstance(b, int):
                kind = "CONST"              # tied 0/1: cannot glitch
            else:
                t = drv.get(b)
                kind = ("FLOP" if (t and t.lower().startswith(_JSON_FLOP))
                        else (t or "UNDRIVEN"))
            if kind not in ("FLOP", "CONST"):
                bad.append(("%s[%d]" % (pname, i), kind))
    # ⛔ ANTI-VACUITY, same rule as the Verilog path: a check that examined
    # nothing has not run, and 0 violations out of 0 bits is not a pass.
    if info["checked"] != 24:
        return "shape", info, bad
    return ("comb" if bad else "ok"), info, bad


def check_json(path: str) -> int:
    status, info, bad = json_verdict(path)
    if status == "no_top":
        print("    *** tt_um_protocol_emulator not in the JSON (modules: %s)"
              % info["modules"])
        return 1
    print("    cells: %d   driven nets: %d" % (info["cells"], info["driven"]))
    if status == "no_port":
        print("    *** port %s absent -- not the netlist we think it is"
              % info["port"])
        return 1
    if status == "shape":
        print("    *** examined %d output bits, expected 24 (8+8+8). The port "
              "shape changed or the parse is wrong." % info["checked"])
        return 1
    print("    output bits examined: %d   flop-or-const: %d"
          % (info["checked"], info["checked"] - len(bad)))
    if bad:
        print("    *** FAIL: %d bit(s) driven by a function, not a register:"
              % len(bad))
        for n, k in bad:
            print("        %-14s %s" % (n, k))
        print("    A combinational output can GLITCH, and a glitch on a clock")
        print("    pin is an extra edge -- a corruption, not a margin problem.")
        return 1
    print("    ⭐ every output bit is a register Q or a constant tie.")
    return 0


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

# ✅ THE ASYNC-CLEAR FACE -- this must PASS.
# The 1.6r ruling fixes shared-MISO release with the reset-synchroniser pattern
# applied to the enable: CS rising ASYNCHRONOUSLY CLEARS the uio_oe flop, while
# the assert path stays synchronised. ⭐ The pin is still a flop's Q, so F2
# holds -- an async-clear flop IS a flop, and recognising it is CLASSIFICATION,
# not a waiver.
# ⛔⛔ AND THIS FACE EXISTS BECAUSE THE ACCEPTANCE WAS ONLY INCIDENTAL. The flop
# pattern already contains `dfr`, so `dfrbpq`-style async-reset cells happened
# to classify correctly -- but nothing TESTED that, which is the same defect as
# `uio_oe` being in OUT_PORTS with no face exercising it. A property that holds
# by accident is a property that can be lost by a pattern edit nobody connects
# to MISO. ⚠ If a future narrowing of the flop pattern breaks this, THIS face
# is what says so, rather than a shared bus in silicon.
MUTANT_ASYNC_OK = """
module tt_um_x (uo_out, uio_out, uio_oe, clk);
  sg13cmos5l_dfrbpq_1 ff0 (.CLK(clk), .D(d0), .RESET_B(rb), .Q(uo_out[0]));
  sg13cmos5l_dfrbpq_1 ff1 (.CLK(clk), .D(d1), .RESET_B(rb), .Q(uio_out[0]));
  sg13cmos5l_dfrbpq_1 ff2 (.CLK(clk), .D(cs_pad), .RESET_B(rb), .Q(cs_s1));
  sg13cmos5l_dfrbpq_1 ff3 (.CLK(clk), .D(cs_s1), .RESET_B(rb), .Q(cs_s2));
  sg13cmos5l_dfrbpq_1 ff4 (.CLK(clk), .D(cs_s2), .RESET_B(cs_n), .Q(uio_oe[0]));
endmodule
"""

# ⛔⛔ THE MISO FACE. Every DATA output is correctly flopped and only the
# ENABLE is combinational -- so a checker that looked at `uo_out`/`uio_out` and
# stopped would call this compliant. It is the worst of the four:
#   * a glitch on a DATA pin is a wrong level for a few hundred ps;
#   * a glitch on an ENABLE turns a second DRIVER on, so a shared MISO gets two
#     output stages fighting -- contention, not a wrong value.
# ⭐ This face exists because the MISO ruling put a REAL enable in the design
# for the first time (uio_oe[MISO] = target CS). Before that ruling `uio_oe` was
# in OUT_PORTS but no face exercised it, so the coverage was untested -- a guard
# whose scope was right and whose evidence was absent.
MUTANT_COMB_OE = """
module tt_um_x (uo_out, uio_out, uio_oe, clk);
  sg13cmos5l_dfrbpq_1 ff0 (.CLK(clk), .D(d0), .RESET_B(rb), .Q(uo_out[0]));
  sg13cmos5l_dfrbpq_1 ff1 (.CLK(clk), .D(d1), .RESET_B(rb), .Q(uio_out[0]));
  sg13cmos5l_dfrbpq_1 ff2 (.CLK(clk), .D(d2), .RESET_B(rb), .Q(cs_sync));
  sg13cmos5l_nand2_1  n0  (.A(cs_sync), .B(sel), .Y(cs_n));
  sg13cmos5l_inv_1    i0  (.A(cs_n), .Y(uio_oe[0]));
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
    print("  --- face 4: the 1.6r ASYNC-CLEAR ENABLE must PASS ---")
    if check(MUTANT_ASYNC_OK, "1.6r: uio_oe from a flop with an async clear"
                              " (RESET_B = cs_n), assert path synchronised") != 0:
        print("    *** FAIL: the async-clear enable was rejected. The 1.6r fix")
        print("        would be blocked by F2, and the two rulings would be in")
        print("        conflict.")
        rc = 1
    else:
        print("    ⭐ AN ASYNC-CLEAR FLOP IS A FLOP -- recognising it is")
        print("    CLASSIFICATION, not a waiver, so 1.6r's hardware fix and")
        print("    F2 hold at the same time.")
        print("    ⛔ THIS FACE EXISTS BECAUSE THE ACCEPTANCE WAS INCIDENTAL:")
        print("    the flop pattern already contains `dfr`, so these cells")
        print("    happened to classify right and NOTHING TESTED IT -- the same")
        print("    defect as uio_oe being in scope with no face. A property")
        print("    that holds by accident can be lost by a pattern edit nobody")
        print("    connects to MISO.")

    print()
    print("  --- face 5: MUST-FIRE, a combinational ENABLE with every data")
    print("      output correctly flopped (the MISO face) ---")
    if check(MUTANT_COMB_OE, "mutant: nand2+inv drive uio_oe[0], data flopped",
             expect_verdict="COMBINATIONAL") != 1:
        print("    *** FAIL: a combinational uio_oe survived. `uio_oe` is in")
        print("        OUT_PORTS but was never EXERCISED -- scope without")
        print("        evidence, and a shared MISO is what pays for it.")
        rc = 1
    else:
        print("    ⭐⭐ THE WORST OF THE MUTANTS, AND THE ONLY ONE WHOSE DATA")
        print("    PINS ARE ALL CORRECT. A glitch on a data output is a wrong")
        print("    level; a glitch on an ENABLE switches a second DRIVER on, so")
        print("    a shared MISO gets two output stages at opposing levels.")
        print("    ⛔ This face exists because the MISO ruling put the first")
        print("    real enable in the design. `uio_oe` was already in scope and")
        print("    no face had ever tested it.")

    print()
    print("  --- face 6: an unknown cell must FAIL CLOSED ---")
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
    print("  GATE F2-selftest: %s" % ("PASSED -- compliant + async-clear pass, four "
                                      "mutants die incl. a combinational "
                                      "ENABLE, unknown fails closed"
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
    print()
    print("=" * 78)
    print("RULING F2 -- flop-driven outputs, on %s" % os.path.basename(path))
    print("=" * 78)
    # ⭐ A `.json` argument is a LOCAL yosys netlist graph; anything else is a
    # gate-level Verilog netlist from the CI artefact. Same ruling, two input
    # formats, because the slow one is the only authoritative one and the fast
    # one is the only one that gets run.
    if path.endswith(".json"):
        print("  (yosys JSON -- pre-technology-mapping cells; structural only,")
        print("   NOT a substitute for the PDK netlist from CI)")
        return check_json(path)
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    return check(text, path)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
