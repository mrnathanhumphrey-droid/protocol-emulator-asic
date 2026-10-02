"""TA-02 -- run every gate, in the endorsed day-one order.

⛔⛔ PRINT THE LIST AND RUN THE LIST. The standing failure this guards against is
running 3 of 26 suites and reporting "full gate green" -- twice. The gates are
enumerated here, the runner executes every one of them, and the summary says
"N of M" or it says nothing. The suites skipped for being slow are the ones that
touch what changed.

⛔ AND EARLIER GREENS DO NOT CARRY. `interp.py` grew a well-formedness check and
two table builders after the first gates had already passed, so every gate is
re-run from the current source rather than remembered.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# (label, kind, command) -- in the endorsed day-one order
GATES = [
    ("gate0-spi      behavioural genericity (the falsifier that can fail)",
     "gate", [sys.executable, "-u", os.path.join(HERE, "gate0_spi.py")]),
    ("gate0-branches structural genericity + mutation pricing",
     "gate", [sys.executable, "-u", os.path.join(HERE, "audit_branches.py")]),
    ("fields         input-branch exerciser + descriptor coverage + size budget",
     "gate", [sys.executable, "-u", os.path.join(HERE, "gate_fields.py")]),
    ("B5             byte-identical UART reproduction of TA-01",
     "gate", [sys.executable, "-u", os.path.join(HERE, "gate_uart_identity.py")]),
    ("band-edge      close-out: level vs phase vs synthesized (PROBE)",
     "probe", [sys.executable, "-u", os.path.join(HERE, "probe_band_edge.py")]),
    ("re-synthesis   parametric band over the TABLE FIELD G",
     "gate", ["wsl.exe", "-d", "Ubuntu", "--", "bash",
              "/mnt/d/ProtocolEmulator/model/ta02/run_imi.sh"]),
    ("price-imi      mutation-pricing the re-synthesis assertions",
     "gate", ["wsl.exe", "-d", "Ubuntu", "--", "bash",
              "/mnt/d/ProtocolEmulator/model/ta02/price_imi_gate.sh"]),
    ("start-bit      does the extra field buy tolerance? (PROBE)",
     "probe", [sys.executable, "-u",
               os.path.join(HERE, "probe_startbit_tradeoff.py")]),
    ("zone-edge      zone band edge: isolates the TA-01 receiver defect",
     "gate", ["wsl.exe", "-d", "Ubuntu", "--", "bash",
              "/mnt/d/ProtocolEmulator/model/ta02/run_zone_edge.sh"]),
    ("third-table    off-pattern PWM, written last, third foreign decoder",
     "gate", [sys.executable, "-u", os.path.join(HERE, "gate_pwm.py")]),
]


def main() -> int:
    print("=== TA-02 FULL GATE -- %d entries ===" % len(GATES))
    for i, (label, kind, _) in enumerate(GATES, 1):
        print("   %d. [%-5s] %s" % (i, kind, label))
    print()
    env = dict(os.environ, PYTHONPATH=HERE, PYTHONIOENCODING="utf-8")
    results = []
    for label, kind, cmd in GATES:
        t0 = time.time()
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env)
        dt = time.time() - t0
        out = (r.stdout or "") + (r.stderr or "")
        results.append((label, kind, r.returncode, dt, out))
        print("  [%-4s] %-6s %5.1fs  %s"
              % ("PASS" if r.returncode == 0 else "FAIL", kind, dt,
                 label.split()[0]))
    print()
    gates = [x for x in results if x[1] == "gate"]
    passed = [x for x in gates if x[2] == 0]
    print("  GATES: %d of %d passed" % (len(passed), len(gates)))
    probes = [x for x in results if x[1] == "probe"]
    print("  PROBES: %d run (probes MEASURE; they do not pass or fail)"
          % len(probes))
    for label, kind, rc, dt, out in results:
        if rc != 0:
            print()
            print("  --- FAILED: %s" % label)
            print("\n".join("      " + l for l in out.splitlines()[-25:]))
    ok = len(passed) == len(gates)
    print()
    print("  TA-02: %s" % ("%d of %d gates green" % (len(passed), len(gates))
                           if ok else
                           "*** %d of %d -- NOT GREEN ***"
                           % (len(passed), len(gates))))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
