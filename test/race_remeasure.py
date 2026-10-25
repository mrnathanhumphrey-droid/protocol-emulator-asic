"""Ruling RA1 -- Layer R / R4 / R5 per image, per arm, on ONE simulator.

Re-measures what the RACY Layer R (pre-0e29fe7) had measured, with the fixed
bench, so the two simulators can be compared field for field. Result recorded
in docs/SPEC_V4_CLOCKED_HIGH_PHASE.md section 23: identical on iverilog and
Verilator 5.053 across 5 images x 3 arms.

    python test/race_remeasure.py iverilog          (Windows side)
    python3 test/race_remeasure.py verilator        (WSL, PE_VERILATOR = the pin)

Writes probe_ra1/<sim>.json (gitignored). Parsing is refill_collect's own
regexes, so both columns are read by the same code the CI gate uses.
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "test"))
os.chdir(ROOT)
from pe_isa import STORE_BYTES as _STORE_BYTES  # noqa: E402  v2: never a typed 256
from toolchain import tool, banner          # noqa: E402
import sim_run                              # noqa: E402
import refill_collect as rc                 # noqa: E402

SIM = sys.argv[1]
IMAGES = ["ckod_image", "corpus_i2c", "corpus_all5", "ckfive_image",
          "ckhold_over_image"]
ARMS = [("clean", []), ("inval", ["M_CK_HOLD_INVAL"]),
        ("both", ["M_PFETCH_BOTH_INVAL"])]
SRCS = ["test/tb_trace.v", "test/fram_i2c.v", "test/fram_spi.v",
        "src/pe_engine.v", "src/pe_store.v", "src/project.v"]
OUT = os.path.join(ROOT, "probe_ra1")
os.makedirs(OUT, exist_ok=True)
banner(SIM if SIM == "verilator" else "iverilog")


def build(arm, defs):
    if SIM == "iverilog":
        out = os.path.join(OUT, "iv_%s.vvp" % arm)
        cmd = [tool("iverilog"), "-g2012", "-I", "test", "-I", "."] + \
              ["-D" + d for d in defs] + ["-o", out, "-s", "tb_trace"] + SRCS
        r = subprocess.run(cmd, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-500:]
        return ("iverilog", out)
    bdir = "/tmp/ra1_%s" % arm
    subprocess.run(["rm", "-rf", bdir])
    cmd = [tool("verilator"), "--cc", "--exe", "--main", "--timing",
           "--public-flat-rw", "-Wno-fatal"] + ["-D" + d for d in defs] + \
          ["+incdir+test", "+incdir+.", "-Mdir", bdir, "-o", "ra1.sim",
           "--top-module", "tb_trace"] + SRCS
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]
    r = subprocess.run(["make", "-C", bdir, "-f", "Vtb_trace.mk", "-j", "4"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]
    return ("bin", bdir)


def run_cmd(built, args, images):
    """The run command for what `build` made, through the one helper."""
    kind, where = built
    if kind == "iverilog":
        return sim_run.vvp([where] + args, images=images)
    return sim_run.argv([os.path.join(where, "ra1.sim")] + args, images=images)


res = {}
for arm, defs in ARMS:
    run = build(arm, defs)
    for img in IMAGES:
        args = ["+IMG=%s/test/%s.hex" % (ROOT, img), "+NBYTES=%d" % _STORE_BYTES,
                "+PEER=none", "+NCYC=60000", "+SCLHOLD=0",
                "+OUT=%s/tr.txt" % OUT]
        if SIM == "verilator":
            args += ["--x-initial", "unique", "+verilator+rand+reset+2"]
        r = subprocess.run(run_cmd(run, args, sim_run.images_in(args)),
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        log = os.path.join(OUT, "%s_%s_%s.log" % (SIM, arm, img))
        open(log, "w", encoding="utf-8").write(r.stdout + r.stderr)
        R = rc.parse(log)
        res["%s:%s" % (arm, img)] = R
        r4, r5 = R.get("r4") or {}, R.get("r5") or {}
        print("%-6s %-18s R %-5s acts=%-4s worst=%-3s over=%-4s | R4 %-4s "
              "slots=%s inflight=%s viol=%s | R5 non-retiring=%s"
              % (arm, img, R["verdict"], R["actions"], R["worst"], R["over"],
                 r4.get("verdict"), r4.get("worst_slots"),
                 r4.get("max_inflight"), r4.get("violations"),
                 r5.get("non_retiring")))
json.dump(res, open(os.path.join(OUT, "%s.json" % SIM), "w"), indent=1,
          default=str)
