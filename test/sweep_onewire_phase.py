"""THE 1-WIRE PHASE SWEEP -- full phase coverage for tb_onewire (CE5).

    python test/sweep_onewire_phase.py [--record model/phase_sweep_onewire.json]

The suite's 1-Wire arms sit at a few phases, so tb_onewire's FULL coverage is
this sweep (model/phase_coverage.py, class SWEEP) -- Wilson's independent-offset
design (probe_reports/onewire_phase_addendum.txt), per arm (ok: the TT image,
base RISE 503 ns; fpga: base 2003 ns):
  S1  the master's release rise walked k = 0..19 ns, the part at 0;
  S2  the part's own delays walked k = 0..19 ns (T_PH_NS), the rise at base;
  S3  20 golden-ratio (rise, part) pairs -- the RELATIVE phase.
= 120 runs, each judged by run_onewire's own judge(). The union of the bench's
measured OW-PHASE masks is the evidence: S1 and S2 release-rise 20/20 and
part-fall 20/20; S3 relative phases >= 15/20.

⭐ TRACKED SINCE 10-25 (a scratch script on 10-21; outcome in
probe_reports/onewire_phase_outcome.txt): a record must cite a recipe the
repo holds.
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import run_onewire as R                     # noqa: E402
import sweep_record                         # noqa: E402

G, H = 0.618034, 0.754878
PLAN = ([("S1", k, 0) for k in range(20)] + [("S2", 0, k) for k in range(20)]
        + [("S3", int(20 * ((i * G) % 1)), int(20 * ((i * H) % 1))) for i in range(1, 21)])
ARMS = [("ok", "tt", R.P.DS18B20_TXN, 503), ("fpga", "fpga", R.ROM_TXN, 2003)]
#: the claim the union must meet (model/phase_coverage.py holds the row to it)
CLAIM = {"S1": (20, 20), "S2": (20, 20), "S3_relative": 15}


def union(masks):
    u = [0] * 20
    for m in masks:
        for i, c in enumerate(m):
            u[i] |= c == "1"
    return sum(u)


def main() -> int:
    rec_path = sys.argv[sys.argv.index("--record") + 1] if "--record" in sys.argv else None
    os.chdir(ROOT)
    print("1-WIRE PHASE SWEEP -- %d runs per arm x %d arms" % (len(PLAN), len(ARMS)))
    runs = []
    for an, var, txn, base in ARMS:
        for s, kr, kp in PLAN:
            R.build_vvp(base + kr, kp)
            txt, rxmap = R.sim("ph_%s_%s_%d_%d" % (an, s, kr, kp), var, txn,
                               base + kr, (), kp)
            d = R.parse(txt)
            ck = R.judge(d, rxmap)
            m = re.search(r"rise_bins=([01]{20}) partfall_bins=([01]{20})", txt)
            runs.append({"arm": an, "set": s, "k_rise": kr, "k_part": kp,
                         "pass": all(c[1] for c in ck),
                         "rise": m.group(1) if m else None,
                         "partfall": m.group(2) if m else None})
            print("  %-4s %s kr=%2d kp=%2d %s" % (an, s, kr, kp,
                  "PASS" if runs[-1]["pass"] else "*** FAIL"), flush=True)
    good = all(r["pass"] and r["rise"] for r in runs)
    res = {"passed": sum(r["pass"] for r in runs), "total": len(runs), "union": {}}
    for an, *_x in ARMS:
        u = {}
        for s in ("S1", "S2", "S3"):
            sel = [r for r in runs if r["arm"] == an and r["set"] == s and r["rise"]]
            u[s] = (union(r["rise"] for r in sel), union(r["partfall"] for r in sel))
        rel = len({(r["k_part"] - r["k_rise"]) % 20 for r in runs
                   if r["arm"] == an and r["set"] == "S3"})
        u["S3_relative"] = rel
        res["union"][an] = u
        meets = (u["S1"] >= CLAIM["S1"] and u["S2"] >= CLAIM["S2"]
                 and rel >= CLAIM["S3_relative"])
        good = good and meets
        print("  %s: S1 %d/20 rise %d/20 part-fall; S2 %d/%d; S3 %d/%d, relative %d/20 %s"
              % (an, u["S1"][0], u["S1"][1], u["S2"][0], u["S2"][1], u["S3"][0],
                 u["S3"][1], rel, "ok" if meets else "*** BELOW THE CLAIM"))
    print("  %d of %d runs passed" % (res["passed"], res["total"]))
    if rec_path and good:
        res["claim"] = CLAIM
        rec = sweep_record.write(rec_path, "onewire_phase", res,
                                 ["test/run_onewire.py", "test/sweep_onewire_phase.py"])
        print("  record: %d inputs, %s... -> %s" % (len(rec["inputs"]["files"]),
              rec["inputs"]["sha256"][:12], rec_path))
    print("  SWEEP onewire_phase: %s" % ("PASSED" if good else "FAILED"))
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
