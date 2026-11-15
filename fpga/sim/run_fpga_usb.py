"""FPGA USB build (USB = 1), SIMULATION -- the glue, before any Vivado run (Wilson 11-14).

tb_fpga_usb boots the certified device program (fpga/images/usbdev_fpga.hex, written by
fpga/sim/gen_usbdev_fpga.py) and checks the glue's promises (comms/USB_PIN_DELTA.md): D+, D-
and the soft-attach pin released unless the program runs, the pull-up = run_ok, and the D+/D-
mapping both ways (raw pads into uio_in; uio_out/oe bits 3/2 out).
MUST-FIRE: the same bench with USB = 0 (the default build: nothing on J11) must be red.
Usage: python fpga/sim/run_fpga_usb.py
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "test"))
from toolchain import banner, tool          # noqa: E402
import sim_run                               # noqa: E402

TMP = os.environ.get("PE_FUSB_TMP") or os.path.join(ROOT, "probe_fpga_usb")
USB_IMGS = ["fpga/images/usbdev_fpga.hex"]
SRCS = ["fpga/sim/tb_fpga_usb.v", "fpga/rtl/pe_fpga_core.v",
        "src/project.v", "src/pe_engine.v", "src/pe_store.v"]


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def sim(name, **params):
    os.makedirs(TMP, exist_ok=True)
    vvp = os.path.join(TMP, "tb_%s.vvp" % name)
    extra, roots = [], ["-s", "tb_fpga_usb"]
    if params:
        dp = os.path.join(TMP, "mf_%s.v" % name)
        with open(dp, "w", encoding="ascii", newline="\n") as fh:
            fh.write("module mf_%s;\n" % name)
            for k, v in params.items():
                fh.write("  defparam tb_fpga_usb.dut.%s = %s;\n" % (k, v))
            fh.write("endmodule\n")
        extra, roots = [os.path.relpath(dp, ROOT).replace(os.sep, "/")], roots + ["-s", "mf_%s" % name]
    b = run([tool("iverilog"), "-g2012", "-o", vvp] + roots + SRCS + extra)
    if b.returncode:
        raise SystemExit("*** build failed (%s)\n%s%s" % (name, b.stdout, b.stderr))
    r = run(sim_run.vvp([os.path.relpath(vvp, ROOT).replace(os.sep, "/")], images=USB_IMGS))
    return r.stdout + r.stderr


def main():
    banner("iverilog", "vvp")
    txt = sim("ok")
    ok = any(ln.startswith("FPGA-USB: ok") for ln in txt.splitlines())
    print("  ok        %s" % ("GREEN" if ok else "RED"))
    for ln in txt.splitlines():
        if ln.startswith("FPGA-USB") or "*** FAIL" in ln:
            print("    " + ln.strip())
    mf = sim("nousb", USB=0)
    killed = not any(ln.startswith("FPGA-USB: ok") for ln in mf.splitlines())
    print("  must-fire USB=0  %s" % ("RED (killed)" if killed else "SURVIVED"))
    verdict = "PASSED" if ok and killed else "FAILED"
    print("GATE fpga-usb: %s" % verdict)
    return 0 if verdict == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main())
