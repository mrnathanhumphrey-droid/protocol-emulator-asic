"""SLANG LINT GATE -- a STRICT front end over src/ (Wilson's portability ruling).

⛔⛔ WHY. iverilog, Verilator and yosys all accepted eight identifiers used
before their declaration in pe_engine.v (`LW` in the port list, `ck_parked`,
`now_inc`, `gi`, `a_q`, `primed`, `winner_q`, `winner_v_q`) -- and Vivado
REFUSED one of them (`genvar gi`), so the FPGA bring-up could not build the
chip at all. Every tool in CI let the class through; this gate is the one that
does not. slang enforces declare-before-use and needs no vendor tool.

CHECKS
  1. ZERO slang errors on src/ (pe_store.v, pe_engine.v, project.v together).
  2. WARNINGS PINNED (Wilson): at most PINNED[class] of each known class, and
     no other class at all. The four that exist are classified, line by line,
     in docs/RESUME_CLOCKED_ARC.md ("slang warnings") -- explained, not just
     recorded.
  3. THE LW ANCHOR: `LW` is a body localparam, so the two ports that need its
     value (`host_lane`, `rx_lane`) INLINE its expression. Each inlined
     expression must equal LW's definition TEXTUALLY (whitespace ignored), so
     the duplicated constant cannot drift.

MUST-FIRES (each on a modified in-memory copy; each must go red)
  a. a planted use-before-declare            -> check 1 red
  b. LW's definition changed, ports untouched -> check 3 red
  c. one more sign-conversion warning        -> check 2 red
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = ["src/pe_store.v", "src/pe_engine.v", "src/project.v"]
PINNED = {"ArithOpMismatch": 2, "SignConversion": 2}
LW_PORTS = ("host_lane", "rx_lane")

try:
    import pyslang
except ImportError:
    print("SLANG LINT GATE: *** pyslang is not installed -- RED, not skipped "
          "(pip install pyslang)")
    sys.exit(1)


def sources():
    out = {}
    for f in FILES:
        with open(os.path.join(ROOT, f), encoding="utf-8") as fh:
            out[f] = fh.read()
    return out


def diagnose(srcs):
    """[(is_error, code_name, file, line, message-ish)] for the sources."""
    comp = pyslang.ast.Compilation()
    for name, text in srcs.items():
        comp.addSyntaxTree(pyslang.syntax.SyntaxTree.fromText(text, name))
    sm = comp.sourceManager
    out = []
    for d in comp.getAllDiagnostics():
        code = str(d.code)
        m = re.match(r"DiagCode\((\w+)\)", code)
        out.append((d.isError(), m.group(1) if m else code,
                    sm.getFileName(d.location), sm.getLineNumber(d.location)))
    return out


def _norm(s):
    return re.sub(r"\s+", "", s)


def lw_anchor(engine_text):
    """Problems with the LW inlining, [] when every port matches LW's text."""
    m = re.search(r"localparam\s+integer\s+LW\s*=\s*(.*?);", engine_text, re.S)
    if not m:
        return ["LW's localparam definition not found in pe_engine.v"]
    want = _norm(m.group(1))
    probs = []
    for port in LW_PORTS:
        p = re.search(r"\[\((.*?)\)-1:0\]\s*" + port + r"\b", engine_text)
        if not p:
            probs.append("port %s: no inlined [(...)-1:0] width found" % port)
        elif _norm(p.group(1)) != want:
            probs.append("port %s width (%s) != LW (%s)"
                         % (port, _norm(p.group(1)), want))
    return probs


def judge(srcs):
    """(problems, summary) for one set of sources."""
    d = diagnose(srcs)
    probs = []
    errs = [x for x in d if x[0]]
    for e in errs:
        probs.append("ERROR %s at %s:%d" % (e[1], e[2], e[3]))
    counts = {}
    for x in d:
        if not x[0]:
            counts[x[1]] = counts.get(x[1], 0) + 1
    for cls, n in sorted(counts.items()):
        if cls not in PINNED:
            probs.append("NEW warning class %s (x%d) -- classify it or fix it"
                         % (cls, n))
        elif n > PINNED[cls]:
            probs.append("warning %s x%d, pinned at %d" % (cls, n, PINNED[cls]))
    probs += ["LW ANCHOR: " + s for s in lw_anchor(srcs["src/pe_engine.v"])]
    return probs, (len(errs), counts)


def main():
    print("=" * 78)
    print("SLANG LINT GATE -- declare-before-use and a strict front end over src/")
    print("=" * 78)
    print("  pyslang %s" % getattr(pyslang, "__version__", "?"))
    srcs = sources()
    probs, (ne, counts) = judge(srcs)
    print("  errors   : %d" % ne)
    for cls, n in sorted(counts.items()):
        print("  warnings : %-18s x%d (pinned %s)" % (cls, n, PINNED.get(cls, "-")))
    for s in probs:
        print("  *** " + s)
    ok = not probs

    # ---- must-fires ------------------------------------------------------
    print("  --- must-fires: each must go RED ---")
    eng = srcs["src/pe_engine.v"]
    anchor = "  reg [TS_W-1:0] now;\n"
    lw_def = re.search(r"localparam\s+integer\s+LW\s*=.*?;", eng, re.S).group(0)
    plants = {
        "use before declare": eng.replace(
            anchor, anchor + "  wire mf_ubd = winner_v_q;   // PLANTED\n", 1),
        "LW changed, ports untouched": eng.replace(
            lw_def, lw_def.replace("? 3 : 4", "? 3 : 5"), 1),
        # the existing warning's OWN pattern (a genvar x SPL into 4 bits),
        # planted once more inside the same generate: a constant would not warn
        "one more sign conversion": eng.replace(
            "      assign hix[gs] = gs * SPL",
            "      wire [3:0] mf_sc = gs * SPL + (l_sel[gs] ? 1 : 0);   // PLANTED\n"
            "      assign hix[gs] = gs * SPL", 1),
    }
    for name, text in plants.items():
        if text == eng:
            print("  *** must-fire %-28s PLANT FAILED (anchor not found)" % name)
            ok = False
            continue
        p, _ = judge(dict(srcs, **{"src/pe_engine.v": text}))
        print("  must-fire %-28s %s" % (name, ("red  ok -- " + p[0][:70]) if p
                                         else "*** STAYED GREEN"))
        ok = ok and bool(p)

    print()
    print("  SLANG LINT GATE: %s" % ("PASSED" if ok else "*** FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
