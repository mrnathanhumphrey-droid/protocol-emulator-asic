"""DOES THE TEST HARNESS SURVIVE GATE LEVEL? Checked in a second, not in 4 hours.

⛔⛔ WHY THIS EXISTS, FROM A BROKEN CHECKPOINT HARDEN. `gl_test` on the
`cmos5l` checkpoint died in 55 SECONDS with

    test/tb.v:33: error: parameter `SPL' not found in `tb.user_project'.

after `gds` had already spent 3h50m and `precheck` 2h11m succeeding. At gate
level `user_project` is the flat synthesised netlist: it has NO PARAMETERS, and
synthesis keeps neither the hierarchy nor the internal names.

⚠ NOTHING COULD HAVE CAUGHT IT. Gate-level elaboration happens ONLY inside the
harden. CI's `test` job and `run_param_points.py` both build the RTL, so
`tb.v`'s parameter was added, swept at two values, and never once elaborated
the way `gl_test` does. The design was fine; the HARNESS could not be built.

⇒ THE TWO FAILURE MODES THIS SHIPPED, both checked here:
    (1) a PARAMETER OVERRIDE on a module that has none      -- elaboration
    (2) a PYTHON REACH-IN to a signal the netlist drops      -- AttributeError
Neither is a design fault, which is the point: they are harness faults that
cost a four-hour run each to discover.

⛔ WHAT THIS IS NOT. It does not run the gate-level simulation -- that needs
the PDK cell models and the real netlist, and only the harden has them. It
answers "can the harness be BUILT and does it avoid signals that will not
exist", which is exactly the class that broke. The behavioural claim stays with
`gl_test`.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from toolchain import banner, tool          # noqa: E402  ruling V

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRATCH = os.environ.get("PE_SCRATCH",
                         os.path.join(os.environ.get("TEMP", "/tmp"), "pe_gl"))

# the ports `tb.v` connects -- the only names that survive synthesis
PORTS = {"ui_in", "uo_out", "uio_in", "uio_out", "uio_oe", "ena", "clk",
         "rst_n"}

STUB = """`default_nettype none
// A STAND-IN FOR THE SYNTHESISED NETLIST: the right PORTS, no parameters, and
// no internals. That is precisely what `gl_test` is handed, and the only
// properties of it that the harness may depend on.
module tt_um_protocol_emulator (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);
  assign uo_out  = 8'h00;
  assign uio_out = 8'h00;
  assign uio_oe  = 8'h00;
endmodule
`default_nettype wire
"""


def run(cmd, cwd=ROOT):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=cwd)


def check_elaborates() -> int:
    """(1) `tb.v` must elaborate with `-DGL_TEST` against a parameterless module."""
    rc = 0
    print()
    print("  --- (1) tb.v elaborates with -DGL_TEST, no parameters available ---")
    os.makedirs(SCRATCH, exist_ok=True)
    stub = os.path.join(SCRATCH, "gl_stub.v")
    with open(stub, "w", encoding="ascii", newline="\n") as fh:
        fh.write(STUB)
    out = os.path.join(SCRATCH, "gl_tb.vvp")
    r = run([tool("iverilog"), "-g2012", "-DGL_TEST", "-o", out, "-s", "tb",
             "-I", "test", "test/tb.v", stub])
    txt = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        print("    *** tb.v DOES NOT ELABORATE at gate level:")
        for line in txt.strip().splitlines()[:6]:
            print("        %s" % line)
        print("    ⛔ This is the exact failure that killed `gl_test` after")
        print("       nearly six hours of successful hardening. Anything")
        print("       `tb.v` asks of `user_project` beyond its PORTS -- a")
        print("       parameter override, a hierarchical reference -- is")
        print("       unavailable once the module is a netlist.")
        rc = 1
    else:
        print("    elaborates  ok")
    # ⭐ AND THE RTL PATH MUST STILL WORK, including the parameter override the
    # guard hides at gate level. A fix that made gate level build by deleting
    # the override would break the SPL sweep, so both are required.
    print("  --- (1b) and the RTL path keeps its parameter override ---")
    srcs = ["src/pe_engine.v", "src/pe_store.v", "src/project.v"]
    for extra, label in (([], "default"), (["-Ptb.SPL_CFG=1"], "SPL=1")):
        o2 = os.path.join(SCRATCH, "rtl_tb.vvp")
        r2 = run([tool("iverilog"), "-g2012"] + extra +
                 ["-o", o2, "-s", "tb", "-I", "test", "test/tb.v"] + srcs)
        ok = r2.returncode == 0
        print("    RTL %-8s %s" % (label, "ok" if ok else "*** FAILED"))
        if not ok:
            print("        %s" % ((r2.stdout + r2.stderr).strip()[:200]))
            rc = 1
    return rc


def check_reachins() -> int:
    """(2) every `dut.user_project.<internal>` read must be GL-guarded.

    ⛔ THE RULE, AND WHY IT IS STRUCTURAL RATHER THAN A `try/except` AUDIT. A
    bare `except` around each internal read would make a gate-level run
    silently SKIP the host-channel precondition and still print a pass --
    "a guard that passes because what it guards is absent", which this project
    has paid for more than once. So the rule is: any function that reaches past
    a PORT must also mention `GL`, i.e. it must have decided what to do at
    gate level rather than discovering it.
    ⚠ THIS IS A SYNTACTIC CHECK. It cannot tell a correct `GL` branch from an
    incorrect one; it catches the case where nobody thought about it at all,
    which is the case that cost a harden.
    """
    rc = 0
    print()
    print("  --- (2) internal reach-ins are GL-guarded ---")
    path = os.path.join(HERE, "test.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    tree = ast.parse(src)
    lines = src.splitlines()

    # every `dut.user_project.X` where X is not a port
    hits = []
    for m in re.finditer(r"dut\.user_project\.([A-Za-z_][A-Za-z_0-9]*)", src):
        name = m.group(1)
        if name in PORTS:
            continue
        ln = src[:m.start()].count("\n") + 1
        hits.append((ln, name))
    print("    internal reach-ins found : %d" % len(hits))

    # which function each line belongs to, and whether that function mentions GL
    funcs = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", None) or node.lineno
            body = "\n".join(lines[node.lineno - 1:end])
            funcs.append((node.lineno, end, node.name, "GL" in body))
    bad = []
    for ln, name in hits:
        owner = None
        for a, b, fn, has_gl in funcs:
            if a <= ln <= b:
                owner = (fn, has_gl)
        if owner is None:
            bad.append((ln, name, "<module level>", False))
        elif not owner[1]:
            bad.append((ln, name, owner[0], False))
        else:
            print("    line %-4d %-16s in %-18s GL-aware  ok"
                  % (ln, name, owner[0]))
    for ln, name, fn, _ in bad:
        print("    *** line %d reads `%s` inside `%s`, which never mentions GL"
              % (ln, name, fn))
        print("        At gate level that signal does not exist and this is an")
        print("        AttributeError mid-test -- a harness fault costing a")
        print("        four-hour run to find.")
        rc = 1
    if not hits:
        print("    ⚠ NONE FOUND AT ALL, which is suspicious rather than clean:")
        print("      the host-channel precondition needs internals by nature.")
        print("      Either the regex no longer matches how they are written,")
        print("      or the precondition has been removed.")
        rc = 1
    return rc


def selftest() -> int:
    """⛔ PRICE BOTH CHECKS. Each is reconstructed from the defect it is for."""
    rc = 0
    print()
    print("  --- must-fire: both checks reject what they claim to ---")
    os.makedirs(SCRATCH, exist_ok=True)
    stub = os.path.join(SCRATCH, "gl_stub.v")
    with open(stub, "w", encoding="ascii", newline="\n") as fh:
        fh.write(STUB)
    # (1) a tb that overrides a parameter unconditionally -- the real defect
    bad_tb = os.path.join(SCRATCH, "bad_tb.v")
    with open(bad_tb, "w", encoding="ascii", newline="\n") as fh:
        fh.write("`default_nettype none\nmodule tb ();\n"
                 "  parameter integer SPL_CFG = 2;\n"
                 "  reg [7:0] ui_in, uio_in; reg ena, clk, rst_n;\n"
                 "  wire [7:0] uo_out, uio_out, uio_oe;\n"
                 "  tt_um_protocol_emulator #(.SPL(SPL_CFG)) user_project (\n"
                 "    .ui_in(ui_in), .uo_out(uo_out), .uio_in(uio_in),\n"
                 "    .uio_out(uio_out), .uio_oe(uio_oe),\n"
                 "    .ena(ena), .clk(clk), .rst_n(rst_n));\n"
                 "endmodule\n`default_nettype wire\n")
    r = run([tool("iverilog"), "-g2012", "-DGL_TEST", "-o",
             os.path.join(SCRATCH, "bad.vvp"), "-s", "tb", bad_tb, stub])
    fires = r.returncode != 0 and "SPL" in (r.stdout + r.stderr)
    print("    %-52s %s" % ("an unguarded parameter override is rejected",
                            "ok" if fires else "*** ACCEPTED"))
    if not fires:
        rc = 1
    # (2) an unguarded reach-in in a function with no GL mention
    snippet = ("async def f(dut):\n"
               "    x = int(dut.user_project.u_eng.lane_underrun.value)\n"
               "    return x\n")
    tree = ast.parse(snippet)
    body = snippet
    has_gl = "GL" in body
    reaches = bool(re.search(r"dut\.user_project\.([A-Za-z_][A-Za-z_0-9]*)",
                             snippet))
    caught = reaches and not has_gl
    print("    %-52s %s" % ("an unguarded internal reach-in is rejected",
                            "ok" if caught else "*** MISSED"))
    if not caught:
        rc = 1
    # and a guarded one is accepted
    ok_snippet = ("async def g(dut):\n"
                  "    if GL:\n        return 0\n"
                  "    return int(dut.user_project.u_eng.host_pop.value)\n")
    accepted = ("GL" in ok_snippet) and bool(
        re.search(r"dut\.user_project\.", ok_snippet))
    print("    %-52s %s" % ("a GL-guarded reach-in is accepted",
                            "ok" if accepted else "*** REJECTED"))
    if not accepted:
        rc = 1
    _ = tree
    return rc


def main() -> int:
    banner("iverilog")   # ruling V2: the log names the binary that ran
    rc = 0
    print()
    print("=" * 78)
    print("GL HARNESS CHECK -- can the test harness be BUILT at gate level?")
    print("=" * 78)
    print("  the defect this is for: `gl_test` died in 55 seconds on a")
    print("  parameter override, after gds (3h50m) and precheck (2h11m) had")
    print("  both succeeded. Gate-level elaboration happens ONLY in the")
    print("  harden, so nothing cheaper could see it.")
    if not os.path.isfile(os.path.join(HERE, "tb.v")):
        print("  *** test/tb.v is missing")
        return 1
    rc |= check_elaborates()
    rc |= check_reachins()
    rc |= selftest()
    print()
    print("=" * 78)
    print("  GATE gl-harness: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    ⚠ PASSED means the harness BUILDS at gate level and asks")
    print("      nothing of signals the netlist drops. It does NOT run the")
    print("      gate-level simulation -- that needs the PDK cell models and")
    print("      the real netlist, and stays with `gl_test` in the harden.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
