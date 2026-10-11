"""THE RECIPE for an EMPIRICAL A2 budget (`program_a2.NO_RTA_BUDGET`).

Runs tb_trace on an image with NO budget (+A2SLACK absent) and prints, per
lane, the widest post-HIGH gap past d that `clocked_conform[A2]` measured --
the quantity an A2 budget bounds. For a stress image the primary analysis
(pyRTA) cannot bound, this measurement plus a STATED margin is the budget, and
it is labelled EMPIRICAL wherever it is used. The live enforcement is the
coverage sweep's arm for the image, which runs with that budget.

Usage:  python test/measure_a2_widest.py [image] [ncyc] [seeds...]
        (default: test/ckdense_image.hex 200000 1 2 3, PEER=none as benchset)
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from toolchain import banner, tool     # noqa: E402


def main():
    img = sys.argv[1] if len(sys.argv) > 1 else "test/ckdense_image.hex"
    ncyc = int(sys.argv[2]) if len(sys.argv) > 2 else 200000
    seeds = [int(s) for s in sys.argv[3:]] or [1, 2, 3]
    banner("iverilog", "vvp")
    tmp = os.path.join(ROOT, "test", "sim_build_hold")
    os.makedirs(tmp, exist_ok=True)
    vvp = os.path.join(tmp, "a2w.vvp")
    r = subprocess.run([tool("iverilog"), "-g2012", "-I", "test", "-o", vvp,
                        "-s", "tb_trace", "test/tb_trace.v", "test/fram_i2c.v",
                        "test/fram_spi.v", "src/pe_engine.v", "src/pe_store.v",
                        "src/project.v"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(r.stdout + r.stderr)
    worst = None
    for s in seeds:
        o = subprocess.run([tool("vvp"), vvp, "+IMG=" + img, "+NBYTES=256",
                            "+PEER=none", "+NCYC=%d" % ncyc, "+SEED=%d" % s,
                            "+OUT=" + os.path.join(tmp, "a2w.txt"), "+ASYNC=0",
                            "+STAYLOAD=0", "+SCLHOLD=0"],
                           cwd=ROOT, capture_output=True, text=True).stdout
        m = re.search(r"clocked_conform\[A2\] lanes: budget .* widest (\S+)", o)
        if not m:
            raise SystemExit("*** seed %d: no A2 lanes line -- the bench did not "
                             "report a measurement" % s)
        w = [int(x) for x in m.group(1).split(",")]
        print("  seed %d: widest per lane %s" % (s, w))
        worst = w if worst is None else [max(a, b) for a, b in zip(worst, w)]
    print("A2-WIDEST: %s %s" % (img, worst))


if __name__ == "__main__":
    main()
