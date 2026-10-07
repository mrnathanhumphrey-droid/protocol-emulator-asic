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

#: ⭐ R4/R5 (ruling R4 and R5). The same rule applies: parse what the bench
#: PRINTED and re-derive nothing.
_R4_OK = re.compile(r"clocked_conform\[R4\]: ok -- (\d+) dispatch\(es\), "
                    r"worst (\d+) slot\(s\) left to refill, max (\d+) "
                    r"refill\(s\) in flight")
_R4_FAIL = re.compile(r"clocked_conform\[R4\]: (\d+) premise violation\(s\) "
                      r"over (\d+) dispatch\(es\)")
_R5 = re.compile(r"clocked_conform\[R5\]: (\d+) refill-bearing dispatch\(es\); "
                 r"port-wide MIN gap (-?\d+) cy \(context, NOT vs D\*\); "
                 r"PER-LANE MIN gap (-?\d+) cy \(d_min's subject\); "
                 r"(\d+) non-retiring; (\d+) speculative fill\(s\); "
                 r"worst dispatch-to-next-fill (\d+) cy")


def parse_premise(text):
    """R4's verdict and R5's measurement, or `None` for either if absent."""
    out = {}
    m = _R4_OK.search(text)
    if m:
        out["r4"] = {"verdict": "ok", "dispatches": int(m.group(1)),
                     "worst_slots": int(m.group(2)),
                     "max_inflight": int(m.group(3)), "violations": 0}
    else:
        m = _R4_FAIL.search(text)
        if m:
            out["r4"] = {"verdict": "red", "dispatches": int(m.group(2)),
                         "worst_slots": None, "max_inflight": None,
                         "violations": int(m.group(1))}
        else:
            out["r4"] = None
    m = _R5.search(text)
    if m:
        out["r5"] = {"bearing": int(m.group(1)),
                     "port_min": int(m.group(2)),
                     "lane_min": int(m.group(3)),
                     "non_retiring": int(m.group(4)),
                     "speculative": int(m.group(5)),
                     "worst_to_fill": int(m.group(6))}
    else:
        out["r5"] = None
    return out


def parse(path):
    with io.open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    prem = parse_premise(text)
    m = _OK.search(text)
    if m:
        return dict(prem, verdict="ok", actions=int(m.group(1)),
                    worst=int(m.group(2)), bound=int(m.group(3)), over=0)
    m = _FAIL.search(text)
    if m:
        return dict(prem, verdict="red", actions=int(m.group(2)),
                    worst=int(m.group(4)), bound=int(m.group(3)),
                    over=int(m.group(1)))
    if _VAC.search(text):
        return dict(prem, verdict="not_exercised", actions=0, worst=None,
                    bound=None, over=0)
    # ⛔ LAYER R SILENT IS NOT "NOTHING HAPPENED". R4/R5 may still have spoken
    # (they count every dispatch, clocked or not), so the record is kept with
    # `verdict=None` rather than discarded -- an arm whose premise checks ran
    # and whose rate check did not is a different state from no run at all.
    return dict(prem, verdict=None, actions=None, worst=None, bound=None,
                over=0)


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
    print()
    print("  %-26s %-9s %-8s %-9s %-9s %s"
          % ("arm_image", "R4", "worst", "inflight", "non-retir", "lane-min"))
    for label in sorted(blob):
        r = blob[label] or {}
        r4, r5 = r.get("r4"), r.get("r5")
        print("  %-26s %-9s %-8s %-9s %-9s %s"
              % (label,
                 (r4 or {}).get("verdict", "ABSENT"),
                 (r4 or {}).get("worst_slots"),
                 (r4 or {}).get("max_inflight"),
                 (r5 or {}).get("non_retiring", "-"),
                 (r5 or {}).get("lane_min", "-")))
    print("  -> %s (%d arm-image rows)" % (a.json, len(blob)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
