"""GATE store-latch (Wilson 10-31, Track 2): the LATCH STORE's two contracts the
chip-level benches cannot see from outside.

  1. THE ARRAY POWERS UP RANDOM. Latches have no reset, so the model has none
     either: every byte starts random (never X, never one value). Must-fire:
     M_STORE_NO_FILL (the fill off) fails the check; and M_STORE_DROP_ROW0 (row
     0's writes lost) is caught BECAUSE the fill is random -- a zero-filled model
     would hide a lost write of a zero.
  2. NO READ AFTER WRITE. A byte written in cycle C is read from C+2: a read in
     C+1 samples on the edge that closes the latch (a half-cycle path). The
     modes keep that apart, and pe_store's contract check stops any bench that
     breaks it -- so EVERY chip bench proves the chip never does; this gate proves
     the check fires (narrow and wide arms).
  3. NEVER BOTH READS IN ONE CYCLE (Wilson 11-01). Each bank's one row-mux tree
     serves both reads, selected by `wre`; pe_store's check stops any bench where
     `re` and `wre` are high together, and the ARM_SHARED arm proves it fires.
  4. THE TREE READS EVERY ROW (Wilson 11-01). tb_rowmux checks pe_rowmux
     against the plain array read for every row at three tree sizes; the
     must-fire M_ROWMUX_NODE (one node's children reversed) fails it.
  5. THE BOUND STORE (Wilson 11-03). The tapeout config builds pe_store with
     PE_IHP_CELLS: src/pe_cells_ihp.v binds the clock gate, latches and hold
     delays to IHP stock cells. The legal arm runs on THOSE bindings against
     the PDK's own cell models (libs.ref/sg13cmos5l_stdcell/verilog, at the
     pinned PDK_SHA; PE_PDK_STDCELL_VERILOG names the directory). Must-fire
     S_ICG_POLARITY (the clock gate's enable inverted, built in scratch from
     src/'s own text) fails it. ⛔ No models = COULD NOT RUN, red; and a
     simulator that cannot drive the models' $setuphold-delayed nets (a probe
     latch stays X) is COULD NOT RUN too, never a skip.
     ⭐ ITS OWN NAMED SIMULATOR: PE_IVERILOG_CELLS / PE_VVP_CELLS (default the
     suite's iverilog). The 2015 iverilog of the dev box leaves the delayed
     nets X; the pinned OSS CAD Suite iverilog 14 drives them (measured
     11-03) -- the one that cannot elaborate pe_engine, which these arms
     never build. CI names it for the sim1 shard.

Legal arm: all 512 bytes written, read back on both ports.
token: GATE store-latch: PASSED
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from toolchain import banner, tool          # noqa: E402
import sim_run                              # noqa: E402

BENCH = "test/tb_store_latch.v"
RTL = ["src/pe_store.v"]

# arm -> (defines, the line that must appear, the line that must NOT)
ARMS = [
    ("legal",          [],                     "STORE-LATCH PASS",                        "***"),
    ("no fill",        ["M_STORE_NO_FILL"],    "STORE-LATCH *** FILL NOT RANDOM",         "STORE-LATCH PASS"),
    ("row 0 dropped",  ["M_STORE_DROP_ROW0"],  "STORE-LATCH *** narrow read of 0",        "STORE-LATCH PASS"),
    ("raw narrow",     ["ARM_RAW"],            "pe_store: *** READ-AFTER-WRITE",          "was NOT stopped"),
    ("raw wide",       ["ARM_RAW_WIDE"],       "pe_store: *** READ-AFTER-WRITE",          "was NOT stopped"),
    ("shared read",    ["ARM_SHARED"],         "pe_store: *** SHARED READ",               "was NOT stopped"),
]
# the row-read tree alone (Wilson 11-01): every row at three tree sizes
TREE_BENCH = "test/tb_rowmux.v"
TREE_ARMS = [
    ("tree",           [],                     "ROWMUX PASS",                             "***"),
    ("tree node",      ["M_ROWMUX_NODE"],      "ROWMUX *** FAIL",                         "ROWMUX PASS"),
]
BENCHES = [(BENCH, "tb_store_latch", ARMS), (TREE_BENCH, "tb_rowmux", TREE_ARMS)]

#: the bound store's arms: (name, defines, scratch mutant or None, want, refuse)
BOUND_ARMS = [
    ("bound",          ["PE_IHP_CELLS"], None,             "STORE-LATCH PASS", "***"),
    ("bound polarity", ["PE_IHP_CELLS"], "S_ICG_POLARITY", "STORE-LATCH *** narrow read", "STORE-LATCH PASS"),
]
CELLS = "src/pe_cells_ihp.v"
#: scratch-built mutants this file kills (gate_mutant_kills' SCRATCH table)
SCRATCH_MUTANTS = {
    "S_ICG_POLARITY": "the bound row clock gate's enable inverted (sg13cmos5l_lgcp_1 "
                      ".GATE(~GATE)): every row opens except the one written",
}
_ICG = ".GATE(GATE), .GCLK(GCLK)"


def cells_sim():
    """(iverilog, vvp) for the bound arms -- named by env, or the suite's."""
    return (os.environ.get("PE_IVERILOG_CELLS") or tool("iverilog"),
            os.environ.get("PE_VVP_CELLS") or tool("vvp"))


def pdk_models():
    """The PDK's stdcell Verilog directory, or None."""
    d = os.environ.get("PE_PDK_STDCELL_VERILOG")
    if not d and os.environ.get("PDK_ROOT"):
        d = os.path.join(os.environ["PDK_ROOT"], "ihp-sg13cmos5l", "libs.ref",
                         "sg13cmos5l_stdcell", "verilog")
    if not d:
        return None
    fs = [os.path.join(d, f) for f in ("sg13cmos5l_stdcell.v", "sg13cmos5l_udp.v")]
    return fs if all(os.path.isfile(f) for f in fs) else None


PROBE = """`timescale 1ns/1ps
module tb_probe; reg d = 1'b0, g = 1'b0; wire q;
  sg13cmos5l_dlhq_1 u (.Q(q), .D(d), .GATE(g));
  initial begin #5 g = 1'b1; d = 1'b1; #5;
    $display("PROBE q=%b", q); $finish; end
endmodule
"""


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")


def main() -> int:
    banner("iverilog", "vvp")
    probs = []
    with tempfile.TemporaryDirectory() as tmp:
        for bench, top, arms in BENCHES:
            for name, defs, want, refuse in arms:
                vvp = os.path.join(tmp, "store_latch_%s.vvp" % name.replace(" ", "_"))
                b = run([tool("iverilog"), "-g2012", "-o", vvp, "-s", top]
                        + ["-D%s" % d for d in defs] + [bench] + RTL)
                if b.returncode != 0:
                    probs.append("%s: build failed: %s" % (name, (b.stdout + b.stderr)[-300:]))
                    continue
                r = run(sim_run.vvp([vvp], images=[]))
                out = r.stdout + r.stderr
                got = want in out and refuse not in out
                kind = "legal    " if not defs else "must-fire"
                line = next((l for l in out.splitlines() if want in l), out.strip().splitlines()[-1:] or [""])
                line = line if isinstance(line, str) else line[0]
                print("  %-9s %-14s %s  %s" % (kind, name, "ok " if got else "***", line.strip()[:90]))
                if not got:
                    probs.append("%s: expected %r (and no %r)" % (name, want, refuse))
        # ---- 5. the bound store, on the PDK's own cell models --------------
        models = pdk_models()
        if models is None:
            probs.append("COULD NOT RUN the bound store: no PDK stdcell models "
                         "(set PE_PDK_STDCELL_VERILOG or PDK_ROOT)")
        else:
            pv = os.path.join(tmp, "probe.v")
            with open(pv, "w", encoding="utf-8") as fh:
                fh.write(PROBE)
            vvp = os.path.join(tmp, "probe.vvp")
            civ, cvvp = cells_sim()
            print("  bound arms simulate on: %s" % civ)
            b = run([civ, "-g2012", "-o", vvp, "-s", "tb_probe", pv] + models)
            r = run(sim_run.argv([cvvp, "-n", vvp], images=[])) if b.returncode == 0 else None
            if r is None or "PROBE q=1" not in r.stdout:
                probs.append("COULD NOT RUN the bound store: this iverilog does not "
                             "drive the PDK models' $setuphold-delayed nets (a "
                             "transparent sg13cmos5l_dlhq_1 read %s)"
                             % ((r.stdout.strip() if r else "a build failure")[-40:]))
            else:
                with open(os.path.join(ROOT, CELLS), encoding="utf-8") as fh:
                    cells = fh.read()
                for name, defs, mut, want, refuse in BOUND_ARMS:
                    src = os.path.join(ROOT, CELLS)
                    if mut == "S_ICG_POLARITY":
                        if cells.count(_ICG) != 1:
                            probs.append("%s: the landmark %r is not in %s exactly once"
                                         % (name, _ICG, CELLS))
                            continue
                        src = os.path.join(tmp, "pe_cells_ihp_%s.v" % mut)
                        with open(src, "w", encoding="utf-8") as fh:
                            fh.write(cells.replace(_ICG, ".GATE(~GATE), .GCLK(GCLK)"))
                    vvp = os.path.join(tmp, "store_latch_%s.vvp" % name.replace(" ", "_"))
                    b = run([civ, "-g2012", "-o", vvp, "-s", "tb_store_latch"]
                            + ["-D%s" % d for d in defs] + [BENCH] + RTL + [src] + models)
                    if b.returncode != 0:
                        probs.append("%s: build failed: %s" % (name, (b.stdout + b.stderr)[-300:]))
                        continue
                    out = run(sim_run.argv([cvvp, "-n", vvp], images=[]))
                    out = out.stdout + out.stderr
                    got = want in out and refuse not in out
                    line = next((l for l in out.splitlines() if want in l), "")
                    print("  %-9s %-14s %s  %s" % ("must-fire" if mut else "bound    ", name,
                          "ok " if got else "***", line.strip()[:90]))
                    if not got:
                        probs.append("%s: expected %r (and no %r)" % (name, want, refuse))
    for p in probs:
        print("  *** " + p)
    print("  GATE store-latch: %s" % ("FAILED" if probs else "PASSED"))
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())
