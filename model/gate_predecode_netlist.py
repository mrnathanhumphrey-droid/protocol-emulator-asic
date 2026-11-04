"""GATE predecode-netlist -- the pre-decode is what synthesis builds (Wilson 11-03).

The latch store's row clock gates were enabled by `wv_q && bank_hit &&
wrow_q == gr`, a 7-bit compare through a fanout-7 decode -- the chip's binder
at two of three densities, on a HALF-cycle check. The pre-decode registers the
write address as one-hot at the staging edge, so every GATE is one flop pair
and one AND. A simulation passing proves the function, not the structure; the
canary's timing claim is about the STRUCTURE, so this reads it off yosys:

  1. the 48 one-hot flops are present: wpa_q (16, {row[1:0], bank}, valid
     folded in) and wpb_q (32, row[6:2]);
  2. the binary staging (wrow_q / wsel_q / wv_q) is GONE from the netlist --
     it is simulation-only, for the contract checks;
  3. every pe_icg GATE is driven by ONE 2-input AND whose two inputs are one
     wpa_q flop and one wpb_q flop -- no compare, no decode, between.

pe_store is synthesised alone at MEM_TYPE "latch" with pe_icg / pe_latch8 /
pe_hold_buf / pe_rowmux kept as boxes, so the GATE net is visible.
Must-fire: a decode planted back into the enable (`wen & (wpb_q != 0)`) is red.
yosys is found as gate_formal_miters finds its suite (PE_SBY, PATH, WSL); none
is COULD NOT RUN, red.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import gate_formal_miters as FM                     # noqa: E402
from gate_rowmux_equiv import yosys_argv            # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

STORE = os.path.join(ROOT, "src", "pe_store.v")
BOXES = ("pe_icg", "pe_latch8", "pe_hold_buf", "pe_rowmux")
WANT_A, WANT_B = 16, 32
SCRIPT = """read_verilog -sv {src}
hierarchy -top pe_store
setattr -mod -set keep_hierarchy 1 {boxes}
synth -top pe_store
opt_clean -purge
write_json {out}
"""


def netlist(how, sby, work, text, tag):
    src = os.path.join(work, "pe_store_%s.v" % tag)
    # the chip's arm: project.v builds pe_store at MEM_TYPE "latch"
    text = text.replace('parameter         MEM_TYPE = "flops"',
                        'parameter         MEM_TYPE = "latch"', 1)
    with open(src, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    out = os.path.join(work, "pe_store_%s.json" % tag)
    path = (lambda p: FM.wslpath(p)) if how == "wsl" else (lambda p: p)
    ys = os.path.join(work, "pd_%s.ys" % tag)
    with open(ys, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(SCRIPT.format(src=path(src), out=path(out), boxes=" ".join(
            "*%s*" % b for b in BOXES)))
    r = subprocess.run(yosys_argv(how, sby, work, os.path.basename(ys)), cwd=work,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not os.path.isfile(out):
        raise RuntimeError("yosys failed: %s" % (r.stdout + r.stderr)[-600:])
    with open(out, encoding="utf-8") as fh:
        return json.load(fh)


def judge(nl):
    """-> ([problem], summary) for pe_store's flattened top."""
    top = next(m for n, m in nl["modules"].items() if n == "pe_store"
               or n.startswith("$paramod") and "pe_store" in n)
    names = {}                                      # bit -> net name
    for n, d in top["netnames"].items():
        for i, b in enumerate(d["bits"]):
            names.setdefault(b, (n, i))
    drv = {}                                        # bit -> (cell, type, port)
    for cn, c in top["cells"].items():
        for port, dirn in c.get("port_directions", {}).items():
            if dirn == "output":
                for b in c["connections"][port]:
                    drv[b] = (cn, c["type"], port)
    flops = [c for c in top["cells"].values() if "DFF" in c["type"].upper()]
    qnet = lambda c: names.get(c["connections"]["Q"][0], ("?", 0))[0]
    count = lambda pat: sum(1 for c in flops if re.search(pat, qnet(c)))
    na, nb = count(r"\bwpa_q\b|wpa_q$"), count(r"\bwpb_q\b|wpb_q$")
    stale = sorted({qnet(c) for c in flops if re.search(r"wrow_q|wsel_q|wv_q", qnet(c))})
    probs = []
    if (na, nb) != (WANT_A, WANT_B):
        probs.append("one-hot flops wpa_q %d / wpb_q %d, want %d / %d" % (na, nb, WANT_A, WANT_B))
    if stale:
        probs.append("binary staging flops survive synthesis: %s" % ", ".join(stale))
    icgs = [c for c in top["cells"].values() if "pe_icg" in c["type"]]
    bad = 0
    for c in icgs:
        g = c["connections"]["GATE"][0]
        d = drv.get(g)
        ok = d is not None and d[1] in ("$_AND_",)
        if ok:
            cell = top["cells"][d[0]]
            ins = [drv.get(cell["connections"][p][0]) for p in ("A", "B")]
            src = sorted(qnet(top["cells"][x[0]]) for x in ins if x and "DFF" in x[1].upper())
            ok = len(src) == 2 and re.search("wpa_q", src[0]) and re.search("wpb_q", src[1])
        bad += 0 if ok else 1
    if not icgs:
        probs.append("no pe_icg instance found -- the latch arm did not synthesise")
    elif bad:
        probs.append("%d of %d clock-gate GATEs are not one AND of a wpa_q and a wpb_q flop"
                     % (bad, len(icgs)))
    return probs, "%d gates, wpa_q %d + wpb_q %d flops, %d binary staging flops" % (
        len(icgs), na, nb, len(stale))


def main():
    print("GATE predecode-netlist: every row clock gate is flop -> AND -> GATE")
    try:
        how, sby = FM.resolve()
    except FM.CouldNotRun as e:
        print("  *** COULD NOT RUN: %s" % e)
        print("  GATE predecode-netlist: COULD NOT RUN")
        return 1
    work = tempfile.mkdtemp(prefix="pe_predecode_", dir=os.environ.get("PE_SCRATCH_ROOT"))
    with open(STORE, encoding="utf-8") as fh:
        text = fh.read()
    rc = 0
    try:
        probs, summ = judge(netlist(how, sby, work, text, "tree"))
    except (RuntimeError, StopIteration, KeyError) as e:
        print("  *** COULD NOT RUN: %s" % e)
        print("  GATE predecode-netlist: COULD NOT RUN")
        return 1
    print("  tree   : %s" % summ)
    for p in probs:
        print("  *** " + p)
    rc |= 1 if probs else 0
    anchor = ".GATE(wen), .GCLK(gclk)"
    if text.count(anchor) != 1:
        print("  *** must-fire PLANT FAILED: anchor %r not found once" % anchor)
        rc = 1
    else:
        planted = text.replace(anchor, ".GATE(wen & (wpb_q != {NPB{1'b0}})), .GCLK(gclk)")
        mp, msumm = judge(netlist(how, sby, work, planted, "plant"))
        print("  must-fire: a decode planted into the enable   %s"
              % ("red  ok -- " + mp[0][:60] if mp else "*** STAYED GREEN"))
        rc |= 0 if mp else 1
    print()
    print("  GATE predecode-netlist: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
