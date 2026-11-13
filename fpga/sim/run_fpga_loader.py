"""FPGA PC-UART LOADER, SIMULATION -- the runner tb_fpga_loader never had.

`fpga/sim/tb_fpga_loader.v` is the simulation twin of the board's PC-UART
loader (fpga/host/load.py): the whole FPGA core against a model of the PC on
one 115200 8N1 port -- boot from BRAM, a corrupt-checksum load refused ('E',
chip silent), a good load of uart_rx_board_nostop.hex ('K', one byte per frame),
a reload of uart_rx_board.hex ('K', two bytes per frame). It passed by hand
(10-11) and was then in NO suite: the registry walk did not reach fpga/sim
(Wilson 10-17: a runner for it, LOCAL -- in the A2 suite, not CI).

ARMS
  ok      the shipped bench: its own verdict line `FPGA-LOADER: ok` and no
          `*** FAIL` line
MUST-FIRE (must be red for its own reason)
  boot    the core BOOTS from uart_rx_board_nostop.hex (an `-P` override of the
          core's IMG): the boot check expects 12 bytes for 6 frames and gets 6,
          so the bench must print its boot-image FAIL -- proof the verdict
          reads what the core actually booted
  magic   (F1.5) the boot image with its v2 MAGIC corrupted: the CHIP refuses
          it (bad_magic, CONFIG_ERR) and the boot frames come back empty
  short   (F1.5) the glue streams v1's half-store (LOAD_N): the chip refuses
          it (short load, CONFIG_ERR) -- the 10-25..11-09 break, priced
The ok arm also asserts the boot load EXACTLY: PE_STORE_BYTES written, and the
chip's verdict store_full=1, bad_magic=0, short=0, CONFIG_ERR=0.
POSITIVE TOKEN: `FPGA-LOADER: PASSED` only on the success path.
Usage: python fpga/sim/run_fpga_loader.py
"""
import concurrent.futures as cf
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "test"))
from toolchain import banner, tool          # noqa: E402
import sim_run                               # noqa: E402
import pe_isa                                # noqa: E402  STORE_BYTES, HDR_REGION (F1.5)
sys.path.insert(0, HERE)
import fpga_engine                           # noqa: E402  PE_SIM=verilator (Wilson 11-10)

#: this runner's scratch-image generator id (test/sim_run.py SCRATCH_GENERATORS)
GEN = "run_fpga_loader"

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
LOADER_IMGS = ["fpga/images/uart_rx_board.hex",
               "fpga/images/uart_rx_board_nostop.hex"]
SRCS = ["fpga/sim/tb_fpga_loader.v", "fpga/rtl/pe_fpga_core.v",
        "src/project.v", "src/pe_engine.v", "src/pe_store.v"]


def rel(p):
    return os.path.relpath(p, ROOT).replace(os.sep, "/")


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def sim(name, extra_images=(), **params):
    """Build + run. `params` override the CORE's parameters (`dut.X`): iverilog's
    `-P` reaches root-module parameters only, so they go in a second root
    module of `defparam`s written to TMP -- the tracked bench is untouched."""
    images = LOADER_IMGS + [rel(p) for p in extra_images]
    if fpga_engine.SIM == "verilator":
        # the same overrides, as `defparam tb_fpga_loader.dut.X` in a wrapper
        # top -- except IMG, which the bench connects on the instance line:
        # that one is substituted in a scratch copy (fpga_engine.vl_build)
        prm = dict(params)
        subs = []
        if "IMG" in prm:
            subs.append(("fpga/sim/tb_fpga_loader.v", '.IMG("%s")' % LOADER_IMGS[0],
                         ".IMG(%s)" % prm.pop("IMG")))
        b = fpga_engine.vl_build("tb_fpga_loader", SRCS,
                                 {"dut." + k: v for k, v in prm.items()}, subs)
        log = os.path.join(TMP, "vl_%s.log" % name)
        fpga_engine.vl_run(b, images, log)
        return open(log, encoding="utf-8", errors="replace").read()
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
    r = run(sim_run.vvp([rel(vvp)], images=images))
    return r.stdout + r.stderr


def boot_load(txt):
    """(bytes written, store_full, bad_magic, short_load, config_err) of the boot load."""
    m = re.search(r"^LD-BOOT bytes=(\d+) full=(\d) bad_magic=(\d) short=(\d) config_err=(\d)", txt, re.M)
    return tuple(int(x) for x in m.groups()) if m else None


def verdict(txt):
    ok = any(ln.startswith("FPGA-LOADER: ok") for ln in txt.splitlines())
    fails = [ln.strip() for ln in txt.splitlines()
             if ln.lstrip().startswith("*** FAIL")]
    return ok, fails


def main():
    print("FPGA PC-UART loader -- simulation (tb_fpga_loader)")
    banner("iverilog", "vvp")
    fpga_engine.banner_line()
    os.makedirs(TMP, exist_ok=True)
    rc = 0

    # ⛔ F1.5 (Wilson 11-09): THE CHIP'S OWN LOAD CHECKS, ON THE BOARD PATH --
    # the magic must-fire's image (byte HDR_REGION flipped), written first
    bad = os.path.join(TMP, "ldmf_badmagic.hex")
    img = bytearray(int(t, 16) for t in open(os.path.join(ROOT, LOADER_IMGS[0]), encoding="ascii").read().split())
    img[pe_isa.HDR_REGION] ^= 0xFF
    with open(bad, "w", encoding="ascii", newline="\n") as fh:
        fh.write("".join("%02x\n" % b for b in img))
    sim_run.scratch_image(GEN, bad)
    # ⭐ THE FOUR SCENARIOS RUN IN PARALLEL (Wilson 11-10): independent, each
    # its own build and image set, so the wall time is the slowest one's. The
    # verdicts are judged below in the old order, one at a time.
    runs = {"ok": ((), {}),
            "boot_mf": ((), dict(IMG='"fpga/images/uart_rx_board_nostop.hex"')),
            "ld_magic": ((bad,), dict(IMG='"%s"' % rel(bad))),
            "ld_short": ((), dict(LOAD_N=pe_isa.STORE_BYTES // 2))}
    with cf.ThreadPoolExecutor(max_workers=len(runs)) as ex:
        fut = {n: ex.submit(sim, n, extra_images=e, **p) for n, (e, p) in runs.items()}
        out = {n: f.result() for n, f in fut.items()}

    txt = out["ok"]
    ok, fails = verdict(txt)
    print("  --- ok (the shipped bench) ---")
    for ln in txt.splitlines():
        if ln.startswith(("FPGA-LOADER", "*** FAIL")):
            print("    " + ln.strip())
    good = ok and not fails
    print("    verdict line present, no FAIL line: %s" % ("ok" if good else "***"))
    rc |= 0 if good else 1
    # ⛔ F1.5: the boot load EXACT -- the whole store written, and accepted
    bl = boot_load(txt)
    exact = bl == (pe_isa.STORE_BYTES, 1, 0, 0, 0)
    print("    boot load: %s bytes written, full/bad_magic/short/config_err = %s -- %s"
          % (bl[0] if bl else None, bl[1:] if bl else None,
             "ok (== %d, accepted)" % pe_isa.STORE_BYTES if exact else "***"))
    rc |= 0 if exact else 1

    print()
    print("  --- must-fire ---")
    txt = out["boot_mf"]
    ok, fails = verdict(txt)
    fired = (not ok) and any("boot image" in f for f in fails)
    print("  must-fire boot      (core boots the nostop image): %s"
          % (("red ok -- " + fails[0][:110]) if fired
             else "*** MUST-FIRE FAILED (ok=%s fails=%s)" % (ok, fails[:2])))
    rc |= 0 if fired else 1

    # ⛔ F1.5 (Wilson 11-09): THE CHIP'S OWN LOAD CHECKS, ON THE BOARD PATH.
    # Each must be REFUSED by the chip (CONFIG_ERR, chip silent) for ITS reason.
    #   magic   a whole-store image with byte HDR_REGION flipped
    #   short   the glue streaming v1's 256 bytes (LOAD_N): today's break
    for tag, want, why in (
            ("magic", (pe_isa.STORE_BYTES, 1, 1, 0, 1),
             "whole store, MAGIC corrupted -> bad_magic, CONFIG_ERR"),
            ("short", (pe_isa.STORE_BYTES // 2, 0, 0, 1, 1),
             "v1's half-store stream -> short load, CONFIG_ERR")):
        txt = out["ld_" + tag]
        ok, fails = verdict(txt)
        bl = boot_load(txt)
        fired = (not ok) and any("boot image: 0 bytes" in f for f in fails) and bl == want
        print("  must-fire %-9s (%s): %s" % (tag, why, "red ok -- refused, boot silent, %s" % (bl,)
              if fired else "*** MUST-FIRE FAILED (boot load %s, want %s; fails %s)" % (bl, want, fails[:1])))
        rc |= 0 if fired else 1

    print()
    print("  FPGA-LOADER: %s" % ("PASSED" if rc == 0 else "*** FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
