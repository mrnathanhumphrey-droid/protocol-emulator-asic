"""FPGA PC-UART LOADER, SIMULATION -- the runner tb_fpga_loader never had.

`fpga/sim/tb_fpga_loader.v` is the simulation twin of the board's PC-UART
loader (fpga/host/load.py): the whole FPGA core against a model of the PC on
one 115200 8N1 port -- boot from BRAM, a corrupt-checksum load refused ('E',
chip silent), a good load of uart_rx_434_nostop.hex ('K', one byte per frame),
a reload of uart_rx_434.hex ('K', two bytes per frame). It passed by hand
(10-11) and was then in NO suite: the registry walk did not reach fpga/sim
(Wilson 10-17: a runner for it, LOCAL -- in the A2 suite, not CI).

ARMS
  ok      the shipped bench: its own verdict line `FPGA-LOADER: ok` and no
          `*** FAIL` line
MUST-FIRE (must be red for its own reason)
  boot    the core BOOTS from uart_rx_434_nostop.hex (an `-P` override of the
          core's IMG): the boot check expects 12 bytes for 6 frames and gets 6,
          so the bench must print its boot-image FAIL -- proof the verdict
          reads what the core actually booted
POSITIVE TOKEN: `FPGA-LOADER: PASSED` only on the success path.
Usage: python fpga/sim/run_fpga_loader.py
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "test"))
from toolchain import banner, tool          # noqa: E402
import sim_run                               # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TMP = os.environ.get("PE_FLOAD_TMP") or os.path.join(ROOT, "probe_fpga_loader")
#: the images a tb_fpga_loader run loads: the bench $readmemh's BOTH by
#: hardcoded path and the core boots its compile-time IMG -- none is a plusarg,
#: so they are named to the helper here. A MODULE CONSTANT so
#: model/gate_sim_runs.py can cross-check it against the bench source
#: (Wilson 10-19, ruling 1).
LOADER_IMGS = ["fpga/images/uart_rx_434.hex",
               "fpga/images/uart_rx_434_nostop.hex"]
SRCS = ["fpga/sim/tb_fpga_loader.v", "fpga/rtl/pe_fpga_core.v",
        "src/project.v", "src/pe_engine.v", "src/pe_store.v"]


def rel(p):
    return os.path.relpath(p, ROOT).replace(os.sep, "/")


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def sim(name, **params):
    """Build + run. `params` override the CORE's parameters (`dut.X`): iverilog's
    `-P` reaches root-module parameters only, so they go in a second root
    module of `defparam`s written to TMP -- the tracked bench is untouched."""
    vvp = os.path.join(TMP, "tb_%s.vvp" % name)
    extra, roots = [], ["-s", "tb_fpga_loader"]
    if params:
        dp = os.path.join(TMP, "mf_%s.v" % name)
        with open(dp, "w", encoding="ascii", newline="\n") as fh:
            fh.write("module mf_%s;\n" % name)
            for k, v in params.items():
                fh.write("  defparam tb_fpga_loader.dut.%s = %s;\n" % (k, v))
            fh.write("endmodule\n")
        extra, roots = [rel(dp)], roots + ["-s", "mf_%s" % name]
    b = run([tool("iverilog"), "-g2012", "-o", vvp] + roots + SRCS + extra)
    if b.returncode:
        raise SystemExit("*** build failed (%s)\n%s%s"
                         % (name, b.stdout, b.stderr))
    r = run(sim_run.vvp([rel(vvp)], images=LOADER_IMGS))
    return r.stdout + r.stderr


def verdict(txt):
    ok = any(ln.startswith("FPGA-LOADER: ok") for ln in txt.splitlines())
    fails = [ln.strip() for ln in txt.splitlines()
             if ln.lstrip().startswith("*** FAIL")]
    return ok, fails


def main():
    print("FPGA PC-UART loader -- simulation (tb_fpga_loader)")
    banner("iverilog", "vvp")
    os.makedirs(TMP, exist_ok=True)
    rc = 0

    txt = sim("ok")
    ok, fails = verdict(txt)
    print("  --- ok (the shipped bench) ---")
    for ln in txt.splitlines():
        if ln.startswith(("FPGA-LOADER", "*** FAIL")):
            print("    " + ln.strip())
    good = ok and not fails
    print("    verdict line present, no FAIL line: %s" % ("ok" if good else "***"))
    rc |= 0 if good else 1

    print()
    print("  --- must-fire ---")
    txt = sim("boot_mf", IMG='"fpga/images/uart_rx_434_nostop.hex"')
    ok, fails = verdict(txt)
    fired = (not ok) and any("boot image" in f for f in fails)
    print("  must-fire boot      (core boots the nostop image): %s"
          % (("red ok -- " + fails[0][:110]) if fired
             else "*** MUST-FIRE FAILED (ok=%s fails=%s)" % (ok, fails[:2])))
    rc |= 0 if fired else 1

    print()
    print("  FPGA-LOADER: %s" % ("PASSED" if rc == 0 else "*** FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
