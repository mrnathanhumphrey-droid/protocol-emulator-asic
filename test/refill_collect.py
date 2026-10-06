"""Collect `clocked_conform[R]` verdicts from a refill measurement directory.

⛔⛔ IT PARSES THE BENCH'S OWN LINES AND RE-DERIVES NOTHING. The refill count,
the action count and the bound all come from `test/clocked_conform.vh`'s
printed verdict, so this file cannot disagree with the layer about what was
measured -- it can only fail to find it, which is reported as `None` and never
as zero.

⚠ `None` IS NOT `0`. A run whose layer R never spoke has measured nothing, and
an absent measurement recorded as a zero refill count would read as the
strongest possible pass. `model/gate_port_demand.py` treats `None` as red.
"""

from __future__ import annotations

import argparse
import glob
import io
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

#: the three shapes `cb_report` can print for layer R, in one place
_OK = re.compile(r"clocked_conform\[R\]: ok -- (\d+) retired clocked "
                 r"action\(s\), worst (\d+) refill\(s\) against a bound of "
                 r"(-?\d+)")
_FAIL = re.compile(r"clocked_conform\[R\]: (\d+) of (\d+) retired clocked "
                   r"actions took more than (-?\d+) prefetch refill\(s\); "
                   r"worst (\d+)")
_VAC = re.compile(r"clocked_conform\[R\]: 0 retired clocked actions")


def parse(path):
    with io.open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    m = _OK.search(text)
    if m:
        return {"verdict": "ok", "actions": int(m.group(1)),
                "worst": int(m.group(2)), "bound": int(m.group(3)),
                "over": 0}
    m = _FAIL.search(text)
    if m:
        return {"verdict": "red", "actions": int(m.group(2)),
                "worst": int(m.group(4)), "bound": int(m.group(3)),
                "over": int(m.group(1))}
    if _VAC.search(text):
        return {"verdict": "not_exercised", "actions": 0, "worst": None,
                "bound": None, "over": 0}
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--json", required=True)
    a = ap.parse_args()
    blob = {}
    for p in sorted(glob.glob(os.path.join(a.dir, "run_*.log"))):
        label = os.path.basename(p)[4:-4]        # run_<label>.log
        blob[label] = parse(p)
    with io.open(a.json, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(blob, fh, indent=1, sort_keys=True)
    print()
    print("  %-26s %-14s %-8s %-7s %s"
          % ("arm_image", "verdict", "actions", "worst", "bound"))
    for label in sorted(blob):
        r = blob[label]
        if r is None:
            print("  %-26s %s" % (label, "*** NO VERDICT FOUND"))
            continue
        print("  %-26s %-14s %-8s %-7s %s"
              % (label, r["verdict"], r["actions"], r["worst"], r["bound"]))
    print("  -> %s (%d arm-image rows)" % (a.json, len(blob)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
