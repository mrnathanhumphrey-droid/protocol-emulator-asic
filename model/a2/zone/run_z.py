"""Re-run TChecker on the Y-R / Z / Z4 instances and check the records.

THE ONE CLAIM: every exact verdict in `jitter_instances.py`'s Z_RECORDED,
LJ_RECORDED and TIE_RECORDED is what TChecker says TODAY, and `ovr` is
unreachable on every instance (an instance where a job can still be pending
at its successor's release is outside what the exact model adjudicates, so a
verdict there would settle nothing -- the first search for these cases found
six such instances and threw them out for exactly that reason).

⚠ NEEDS WSL + TChecker (/opt/ta/tchecker/bin), like `run_jitter.py`, so it is
the RECIPE behind the records rather than a CI gate. `model/gate_spuri_candidates.py`
judges our recurrence against the records in CI; `gate_pyrta_jitter.py`
judges the two pyRTA framings against them under `run_a2.py`.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))

from run_edf import foreign_r                                  # noqa: E402
from run_jitter import rmax_for                                # noqa: E402
from jitter_instances import (LJ_INSTANCES, LJ_RECORDED,       # noqa: E402
                              TIE_INSTANCES, TIE_RECORDED, Z_INSTANCES,
                              Z_RECORDED)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def one(lanes, k, tag, tie="nondet"):
    f = foreign_r(lanes, k, tag, rmax=rmax_for(lanes), tie_mode=tie)
    return f.get("r"), (f.get("ovr") or {}).get("reachable")


def main() -> int:
    rc = 0
    print("=" * 78)
    print("  run_z -- TChecker re-check of the Y-R / Z / Z4 records")
    print("=" * 78)
    rows = []
    for name, k, lanes in Z_INSTANCES:
        rows.append(("Z  " + name, lanes, k, "nondet", Z_RECORDED[name]["tck"]))
    for name, lanes in LJ_INSTANCES:
        for k in range(len(lanes)):
            if (name, k) in LJ_RECORDED:
                rows.append(("LJ %s/%d" % (name, k), lanes, k, "nondet",
                             LJ_RECORDED[(name, k)]))
    for name, k, lanes in TIE_INSTANCES:
        for tie in ("nondet", "index"):
            rows.append(("T  %s %s" % (name, tie), lanes, k, tie,
                         TIE_RECORDED[name][tie]))
    for i, (label, lanes, k, tie, want) in enumerate(rows):
        r, ovr = one(lanes, k, "rz_%d" % i, tie)
        ok = (r == want) and (ovr is False)
        print("  %-26s tck=%s recorded=%s ovr=%s   %s"
              % (label, r, want, ovr, "ok" if ok else "*** MISMATCH"))
        sys.stdout.flush()
        if not ok:
            rc = 1
    print("  run_z: %s" % ("ALL RECORDS REPRODUCED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
