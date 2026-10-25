"""THE I2C PEER-DELAY SWEEP -- full phase coverage for the I2C timing benches.

    python test/sweep_i2c_delay.py [--record model/phase_sweep_i2c.json]

The suite's I2C arms put the peer's edges at two phases (+0 and +11 ns), so
their FULL coverage is this sweep (model/phase_coverage.py, class SWEEP): the
peer's pull-low enables delayed by PEER_DLY_NS (test/fram_i2c.v, `ifdef) at
0, 1, 3, 7, 11, 15, 19 ns -- 7 phases after the chip's posedge -- under the
three UNCHANGED I2C runners (tb_i2c, tb_ckack, tb_trace's I2C classes, each
judged by sigrok). 21 runs; every one must pass on its own token.

⭐ TRACKED SINCE 10-25 (it was a scratch script, 10-21, whose numbers are in
probe_reports/i2c_peer_delay_outcome.txt): a record must cite a recipe the
repo holds. The define is injected by a SHIM in place of iverilog (via
PE_IVERILOG, ruling V's resolver), .cmd on Windows and sh elsewhere, so the
runners and the benches run exactly as the suite runs them.
⚠ LOCAL ONLY: the runners need sigrok-cli (WSL here).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from toolchain import banner, tool          # noqa: E402  ruling V
import sweep_record                         # noqa: E402

DELAYS = (0, 1, 3, 7, 11, 15, 19)
RUNNERS = {"test/run_i2c.py": "GATE i2c-foreign: PASSED",
           "test/run_ckack.py": "GATE ckack: PASSED",
           "test/run_recert.py": "GATE recert: PASSED"}


def shim(d, real, where):
    if os.name == "nt":
        p = os.path.join(where, "iv_dly%d.cmd" % d)
        with open(p, "w") as fh:
            fh.write('@"%s" -DPEER_DLY_NS=%d %%*\r\n' % (real, d))
    else:
        p = os.path.join(where, "iv_dly%d.sh" % d)
        with open(p, "w") as fh:
            fh.write('#!/bin/sh\nexec "%s" -DPEER_DLY_NS=%d "$@"\n' % (real, d))
        os.chmod(p, 0o755)
    return p


def main() -> int:
    rec_path = sys.argv[sys.argv.index("--record") + 1] if "--record" in sys.argv else None
    banner("iverilog", "vvp")
    real_iv, real_vvp = tool("iverilog"), tool("vvp")
    where = tempfile.mkdtemp(prefix="pe_i2cdly_")
    print("I2C PEER-DELAY SWEEP -- %d delays x %d runners" % (len(DELAYS), len(RUNNERS)))
    runs = []
    for d in DELAYS:
        env = dict(os.environ)
        if d:
            env["PE_IVERILOG"] = shim(d, real_iv, where)
            env["PE_VVP"] = real_vvp
        for r, token in RUNNERS.items():
            p = subprocess.run([sys.executable, r], cwd=ROOT, env=env,
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            out = p.stdout + p.stderr
            # the shim must really have been used (the 10-21 check, kept)
            seen_iv = re.search(r"tool iverilog\s*:\s*(\S+)", out)
            used = (seen_iv.group(1) if seen_iv else "?")
            shim_ok = (d == 0) or ("iv_dly%d" % d) in used
            ok = p.returncode == 0 and re.search(r"^\s*%s\s*$" % re.escape(token),
                                                 out, re.M) is not None and shim_ok
            runs.append({"delay_ns": d, "runner": r, "exit": p.returncode,
                         "token": ok, "iverilog": used})
            print("  d=%2d %-20s exit %d  %s%s" % (d, r[5:], p.returncode,
                  "PASSED" if ok else "*** FAIL",
                  "" if shim_ok else "  (*** the shim was NOT used)"), flush=True)
    passed = sum(r["token"] for r in runs)
    phases = sorted({r["delay_ns"] for r in runs if r["token"]})
    print("  %d of %d runs passed; peer-edge phases covered: %s ns after posedge"
          % (passed, len(runs), phases))
    good = passed == len(runs)
    if rec_path and good:
        rec = sweep_record.write(rec_path, "i2c_peer_delay",
                                 {"runs": runs, "passed": passed, "total": len(runs),
                                  "phases_ns": phases}, list(RUNNERS) +
                                 ["test/sweep_i2c_delay.py"])
        print("  record: %d inputs, %s... -> %s" % (len(rec["inputs"]["files"]),
              rec["inputs"]["sha256"][:12], rec_path))
    print("  SWEEP i2c_peer_delay: %s" % ("PASSED" if good else "FAILED"))
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
