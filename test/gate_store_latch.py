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


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")


def main() -> int:
    banner("iverilog", "vvp")
    probs = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, defs, want, refuse in ARMS:
            vvp = os.path.join(tmp, "store_latch_%s.vvp" % name.replace(" ", "_"))
            b = run([tool("iverilog"), "-g2012", "-o", vvp, "-s", "tb_store_latch"]
                    + ["-D%s" % d for d in defs] + [BENCH] + RTL)
            if b.returncode != 0:
                probs.append("%s: build failed: %s" % (name, (b.stdout + b.stderr)[-300:]))
                continue
            r = run(sim_run.vvp([vvp], images=[]))
            out = r.stdout + r.stderr
            got = want in out and refuse not in out
            kind = "legal    " if name == "legal" else "must-fire"
            line = next((l for l in out.splitlines() if want in l), out.strip().splitlines()[-1:] or [""])
            line = line if isinstance(line, str) else line[0]
            print("  %-9s %-14s %s  %s" % (kind, name, "ok " if got else "***", line.strip()[:90]))
            if not got:
                probs.append("%s: expected %r (and no %r)" % (name, want, refuse))
    for p in probs:
        print("  *** " + p)
    print("  GATE store-latch: %s" % ("FAILED" if probs else "PASSED"))
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())
