"""THE FPGA BUILD MUST BUILD -- checked in CI, without Vivado (bundle F1, Wilson 11-09).

⛔⛔ WHY. On 11-07 `pe_store.v` gained `always_latch` (SystemVerilog) and
`fpga/pa100t/build.tcl` read the sources as Verilog-2001: the board build was
broken for two days and no gate noticed, because only Vivado on Nathan's
machine ever built it.

⭐ THE STORE IS THE CHIP'S OWN (Wilson 11-09). The FPGA builds MEM_TYPE "sram",
the chip's default, with NO store define: the sram arm's arbitration, write
buffer, forwarding and buffer-read slot are the code that tapes out, and only
the RAM core differs -- the TT flow's `PE_SRAM_MACRO` binds the IHP macro
through `src/pe_sram_macro_ihp.v`; without it the inline core is that macro's
behaviour (matched to the PDK's RM_IHPSG13_1P_core_behavioral_bm_bist.v).
(Withdrawn 11-09: a must-fail "no PE_MEM_FLOPS -> RM_IHPSG13 unresolved". The
macro is never referenced without PE_SRAM_MACRO, so it could not fire.)

THE CHECK. Each FPGA variant -- UART (default), 1-Wire (`PE_OW`), I2C
(`PE_I2C`) -- through yosys `synth_xilinx -family xc7`, with the build's OWN
inputs, read from the files `build.tcl` reads:
  * the same five sources, read `-sv`, with the exact `-verilog_define` set of
    the variant's `synth_design` line, parsed out of `build.tcl` itself, so this
    gate cannot drift from the real build; a store define there is RED;
  * the same generics: `CLK_HZ` from `fpga/board.yaml`, the variant's image /
    feed files (copied into the run directory, as `build.tcl` does, so
    `$readmemh` resolves) and its `.params` counts;
  * `hierarchy -check`: a module nobody defines is an ERROR, not a blackbox;
  * THE STORE CHECK: the elaborated pe_store holds the sram arm -- its RAM
    array `g_mem.mem` and its write buffer `g_mem.pw`, exactly once each.
Green only if all three parse, elaborate with no unresolved module, build the
sram arm, and map.

MUST-FAILS (each must fail, for ITS reason, or the gate is red):
  * flops_caught -- `PE_MEM_FLOPS` added: builds fine, but the store check
    must fail (the flop store is not the chip's);
  * sram_macro_leak -- `PE_SRAM_MACRO` added: must fail on an unresolved
    `pe_sram_macro` (the TT flow's macro binding has no FPGA file);
  * no_sv -- the `-sv` reads dropped: must fail at `pe_store.v`'s
    `always_latch` line.
All run on the UART variant and stop after elaboration (every break is in
front of mapping; a full synth would add minutes and prove nothing more).

NOT CHECKED HERE: timing. The full Vivado build (WNS / WHS) runs on Nathan's
machine before every board session -- docs/FPGA_BRINGUP.md.
                                                    token: GATE fpga-synth: PASSED
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from toolchain import banner, tool                     # noqa: E402

BUILD = os.path.join(ROOT, "fpga", "pa100t", "build.tcl")
SRCS = ["src/pe_engine.v", "src/pe_store.v", "src/project.v",
        "fpga/rtl/pe_fpga_core.v", "fpga/pa100t/pa100t_top.v"]


def clk_hz():
    m = re.search(r"^\s*clock_hz:\s*(\d+)", open(os.path.join(ROOT, "fpga", "board.yaml"),
                                                  encoding="utf-8").read(), re.M)
    if not m:
        raise SystemExit("*** fpga/board.yaml: no clock_hz")
    return int(m.group(1))


def params(rel):
    out = {}
    for line in open(os.path.join(ROOT, rel), encoding="utf-8"):
        f = line.split()
        if len(f) == 2:
            out[f[0]] = int(f[1])
    return out


def build_defines():
    """The -verilog_define set of each synth_design line in build.tcl, keyed by
    variant (the define that selects it; '' = the UART build)."""
    txt = open(BUILD, encoding="utf-8").read()
    out = {}
    for line in txt.splitlines():
        if line.strip().startswith("synth_design"):
            d = re.findall(r"-verilog_define\s+(\w+)", line)
            key = "PE_OW" if "PE_OW" in d else "PE_I2C" if "PE_I2C" in d else ""
            out[key] = d
    if set(out) != {"", "PE_OW", "PE_I2C"}:
        raise SystemExit("*** build.tcl: expected three synth_design lines, found %r" % sorted(out))
    reads = re.findall(r"read_verilog(\s+-sv)?\s", txt)
    return out, all(r for r in reads) and len(reads) == 3


def variants():
    hz = clk_hz()
    ow, i2c = params("fpga/feeds/onewire_fpga_feed.params"), params("fpga/feeds/i2c_fram.params")
    return [
        ("uart", "", ["fpga/images/uart_rx_board.hex"],
         [("IMG", '"uart_rx_board.hex"'), ("CLK_HZ", hz)]),
        ("onewire", "PE_OW", ["test/onewire_fpga_image.hex", "fpga/feeds/onewire_fpga_feed.hex"],
         [("IMG", '"onewire_fpga_image.hex"'), ("FEED", '"onewire_fpga_feed.hex"'),
          ("NFEED", ow["NFEED"]), ("POLLIDX", ow["POLLIDX"]), ("PER2", ow["PER2"]),
          ("MARGIN", ow["MARGIN"]), ("CLK_HZ", hz)]),
        ("i2c", "PE_I2C", ["fpga/images/i2c_fram_fpga.hex", "fpga/feeds/i2c_fram_feed.hex",
                           "fpga/feeds/i2c_fram_falls.hex"],
         [("IMG", '"i2c_fram_fpga.hex"'), ("FEED", '"i2c_fram_feed.hex"'),
          ("FALLS", '"i2c_fram_falls.hex"'), ("NFEED", i2c["NFEED"]), ("NRX", i2c["NRX"]),
          ("CLK_HZ", hz)]),
    ]


def script(defines, sv, gens, full):
    dflags = " ".join("-D%s" % d for d in defines)
    # -defer: nothing elaborates at read time, so no module is built with its
    # DEFAULT image (whose $readmemh file this variant does not have)
    s = ["read_verilog -defer -I%s %s %s %s" % (ROOT.replace(os.sep, "/"), "-sv" if sv else "", dflags, os.path.join(ROOT, f).replace(os.sep, "/"))
         for f in SRCS]
    # chparam -set keeps a quoted string a string; hierarchy -chparam cannot
    # take one ("Can't decode value")
    # the Xilinx primitives (IBUFDS, MMCME2_BASE, BUFG, IOBUF) as library
    # blackboxes -- what synth_xilinx itself loads first. Only THEY are known:
    # any other module nobody defines (the SRAM macro) is still unresolved.
    s += ["read_verilog -lib -specify +/xilinx/cells_sim.v",
          "read_verilog -lib +/xilinx/cells_xtra.v"]
    s += ["chparam -set %s %s pa100t_top" % (k, v) for k, v in gens]
    s.append("hierarchy -check -top pa100t_top")
    # THE STORE CHECK: the sram arm's RAM array and write buffer, once each
    s += ["select -assert-count 1 */m:*g_mem.mem",
          "select -assert-count 1 */w:*g_mem.pw"]
    if full:
        s.append("synth_xilinx -family xc7 -top pa100t_top")
        s.append("stat")
    return "\n".join(s) + "\n"


def run_yosys(ys, files, tag):
    d = tempfile.mkdtemp(prefix="pe_fpga_synth_%s_" % tag)
    try:
        for f in files:
            shutil.copy(os.path.join(ROOT, f), os.path.join(d, os.path.basename(f)))
        p = os.path.join(d, "run.ys")
        open(p, "w", encoding="utf-8").write(ys)
        t0 = time.time()
        r = subprocess.run([tool("yosys"), "-q", "-l", os.path.join(d, "log.txt"), "-s", p],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=d)
        log = open(os.path.join(d, "log.txt"), encoding="utf-8", errors="replace").read() \
            if os.path.exists(os.path.join(d, "log.txt")) else ""
        return r.returncode, log + r.stdout + r.stderr, time.time() - t0
    finally:
        shutil.rmtree(d, ignore_errors=True)


def errors(txt):
    return [l.strip() for l in txt.splitlines() if re.search(r"\bERROR\b", l)][:3]


def main():
    banner("yosys")
    t_all = time.time()
    defs, sv_ok = build_defines()
    bad = []
    if not sv_ok:
        bad.append("build.tcl does not read every source -sv")
    for key in ("", "PE_OW", "PE_I2C"):
        for d in ("PE_MEM_FLOPS", "PE_MEM_LATCH", "PE_SRAM_MACRO"):
            if d in defs[key]:
                bad.append("build.tcl's %s synth_design defines %s (the FPGA builds the chip's sram arm, "
                           "no store define)" % (key or "UART", d))
    print("  build.tcl defines: " + "; ".join("%s=%s" % (k or "uart", ",".join(v)) for k, v in sorted(defs.items())))

    vs = variants()
    for name, key, files, gens in vs:
        rc, log, dt = run_yosys(script(defs[key], True, gens, True), files, name)
        # yosys `stat` prints each module, then the whole design under
        # "=== design hierarchy ===": count only that last section
        tot = log.rsplit("=== design hierarchy ===", 1)[-1] if "=== design hierarchy ===" in log else ""
        luts = sum(int(n) for n in re.findall(r"^\s+LUT\d\s+(\d+)\s*$", tot, re.M))
        ffs = sum(int(n) for n in re.findall(r"^\s+FD[CPRS]E\s+(\d+)\s*$", tot, re.M))
        ok = rc == 0 and "End of script" in log
        print("  %-8s %-5s %5.1f s  LUT %d  FF %d  %s" % (name, "ok" if ok else "FAIL", dt, luts, ffs,
                                                     "" if ok else " | ".join(errors(log)) or "rc %d" % rc))
        if not ok:
            bad.append("%s did not synthesize" % name)

    # must-fails, on the UART variant, read + hierarchy only
    name, key, files, gens = vs[0]
    mf = [("flops_caught", defs[key] + ["PE_MEM_FLOPS"], True,
           # elaborated cleanly (no unresolved module), then the STORE CHECK failed
           lambda log: "is not part of the design" not in log and
           re.search(r"ERROR: Assertion failed: selection contains 0 elements .*g_mem\.(mem|pw)", log)),
          ("sram_macro_leak", defs[key] + ["PE_SRAM_MACRO"], True,
           lambda log: re.search(r"ERROR: Module `\\pe_sram_macro' referenced", log)),
          ("no_sv", defs[key], False,
           lambda log: _latch_line(log))]
    for tag, d, sv, why in mf:
        rc, log, dt = run_yosys(script(d, sv, gens, False), files, tag)
        failed = rc != 0
        right = failed and why(log)
        print("  must-fail %-13s %s  %5.1f s  %s" % (tag, "fired" if right else "DID NOT FIRE", dt,
                                                    " | ".join(errors(log))[:200]))
        if not right:
            bad.append("must-fail %s: %s" % (tag, "passed" if not failed else "failed for another reason"))

    print("  total %.1f s" % (time.time() - t_all))
    if bad:
        for b in bad:
            print("  *** " + b)
        print("GATE fpga-synth: FAILED")
        return 1
    print("GATE fpga-synth: PASSED")
    return 0


def _latch_line(log):
    """The no-sv failure must point at pe_store.v's always_latch line."""
    src = open(os.path.join(ROOT, "src", "pe_store.v"), encoding="utf-8").read().splitlines()
    lines = {k + 1 for k, l in enumerate(src) if "always_latch" in l and not l.strip().startswith("//")}
    for m in re.finditer(r"pe_store\.v:(\d+)", log):
        if int(m.group(1)) in lines:
            return True
    return False


if __name__ == "__main__":
    sys.exit(main())
