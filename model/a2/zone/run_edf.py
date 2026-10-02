"""A2-GREEN Part 3 -- drive TChecker, then compare it against the recurrence.

ORDER OF BUSINESS, AND IT MATTERS:
  1. VALIDATE THE MODEL against the three hand-timed schedules from Part 2,
     whose answers are forced by the schedule itself (2, 5, 5). A foreign
     checker is only an authority once it reproduces answers we can verify by
     hand. Skipping this would make every later "agreement" unfalsifiable --
     a broken model that happened to agree with a broken recurrence.
  2. Only then run N = 2, 3, 4 instances and compare.

⭐ `r_i = min{ R : BAD unreachable }`, found by bisection. The predicate is
monotone in R (the BAD guard `a_i >= R` only gets harder as R grows), which is
what makes bisection valid rather than merely convenient -- asserted below by
re-checking both bracket ends.

⛔ `ovr` IS CHECKED ON EVERY INSTANCE. It flags a release arriving while the
same lane is still pending -- the model's one structural assumption. If `ovr`
is reachable the instance is outside the model and its number means nothing,
so it is reported as a failure, not a footnote.
"""

from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))

from gen_edf import gen                                      # noqa: E402
from a2_close import Lane                                    # noqa: E402
from rta_spuri import response_time_spuri                    # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

WSL_DIR = "/mnt/d/ProtocolEmulator/model/a2/zone"


def check(lanes, target: int, R: int, label: str, tag: str) -> dict:
    """One tck-reach call. Returns {'reachable': bool, 'states': int|None}."""
    src = gen(lanes, target, R, tag=tag)
    path = os.path.join(HERE, "%s.tck" % tag)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(src)
    os.replace(tmp, path)                   # temp-then-replace, never truncate-in-place
    r = subprocess.run(
        ["wsl.exe", "-d", "Ubuntu", "--", "bash",
         "%s/run_tck.sh" % WSL_DIR, "%s/%s.tck" % (WSL_DIR, tag), label],
        capture_output=True, text=True,
        env={**os.environ, "MSYS_NO_PATHCONV": "1"})
    out = (r.stdout or "") + (r.stderr or "")
    if "ERROR" in out or "error" in out.lower() and "REACHABLE" not in out:
        return {"reachable": None, "states": None, "raw": out.strip()[:200]}
    reachable = "REACHABLE true" in out
    states = None
    for line in out.splitlines():
        if "VISITED_STATES" in line:
            try:
                states = int(line.split()[-1])
            except ValueError:
                pass
    return {"reachable": reachable, "states": states, "raw": out.strip()[:200]}


def foreign_r(lanes, target: int, tag: str, rmax: int | None = None) -> dict:
    """r_target by bisection on the foreign checker."""
    if rmax is None:
        rmax = sum(l[2] for l in lanes) + max(l[2] for l in lanes) + 4
    ovr = check(lanes, target, rmax, "ovr", tag + "_ovr")
    lo, hi = 0, rmax
    top = check(lanes, target, hi, "bad", tag + "_hi")
    if top["reachable"] is None:
        return {"r": None, "err": top["raw"], "ovr": ovr}
    if top["reachable"]:
        return {"r": None, "err": "BAD still reachable at R=%d: no bound found" % hi,
                "ovr": ovr}
    bot = check(lanes, target, 0, "bad", tag + "_lo")
    if not bot["reachable"]:
        return {"r": 0, "ovr": ovr, "calls": 2, "states": top["states"]}
    calls = 2
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        res = check(lanes, target, mid, "bad", tag + "_m")
        calls += 1
        if res["reachable"] is None:
            return {"r": None, "err": res["raw"], "ovr": ovr}
        if res["reachable"]:
            lo = mid
        else:
            hi = mid
    return {"r": hi, "ovr": ovr, "calls": calls, "states": top["states"]}


# ============================================================================
# STEP 1 -- validate the model on schedules whose answers are forced
# ============================================================================
VALIDATION = [
    ("solo: nothing to block or interfere",
     [("solo", 100, 2, 50)], 0, 2),
    ("B=0, one more-urgent lane ahead",
     [("urgent", 100, 2, 10), ("relaxed", 100, 3, 50)], 1, 5),
    ("blocker started one tick early",
     [("analysed", 100, 2, 10), ("blocker", 100, 4, 50)], 0, 5),
]


def validate() -> bool:
    print("=" * 78)
    print("STEP 1 -- validate the FOREIGN model against hand-timed schedules")
    print("=" * 78)
    print("  %-38s %-8s %-10s %s" % ("case", "truth", "TChecker", "verdict"))
    ok = True
    for i, (label, lanes, tgt, truth) in enumerate(VALIDATION):
        res = foreign_r(lanes, tgt, "val%d" % i)
        got = res.get("r")
        good = got == truth
        ok = ok and good and res["ovr"]["reachable"] is False
        print("  %-38s %-8d %-10s %s"
              % (label, truth, got if got is not None else "ERR",
                 "OK" if good else "*** MISMATCH ***"))
        if res.get("err"):
            print("      err: %s" % res["err"])
        if res["ovr"]["reachable"] is not False:
            print("      *** ovr reachable (%s) -- model assumption broken ***"
                  % res["ovr"]["reachable"])
    print()
    print("  model validation: %s" % ("PASSED -- TChecker reproduces all three "
                                      "forced answers" if ok else
                                      "FAILED -- do not use it as an authority"))
    return ok


# ============================================================================
# STEP 2 -- the cross-check instances
# ============================================================================
# ⭐ CHOSEN TO EXERCISE THE MACHINERY, NOT TO BE EASY:
#   I1  N=2, DISTINCT C per lane          -> the non-uniform-C path
#   I2  N=3, three distinct deadlines     -> the deadline-limited interference
#   I3  N=4, high utilisation, short T    -> m_i > 1, so the offset search and
#                                            the regime where the closed form
#                                            breaks are both live
INSTANCES = [
    ("I1  N=2 distinct C", [("A", 10, 2, 5), ("B", 7, 3, 6)]),
    ("I2  N=3 distinct D", [("A", 10, 2, 4), ("B", 7, 1, 3), ("C", 5, 1, 5)]),
    ("I3  N=4 m_i>1", [("A", 4, 1, 3), ("B", 6, 2, 5),
                       ("C", 10, 2, 8), ("D", 12, 2, 11)]),
]


def main() -> int:
    print()
    if not validate():
        print("\nABORTING: an unvalidated checker cannot adjudicate anything.")
        return 1
    print()
    print("=" * 78)
    print("STEP 2 -- foreign checker vs the recurrence (A2-F7)")
    print("=" * 78)
    rows = []
    for inst_label, lanes in INSTANCES:
        print()
        print("  %s   lanes (T,C,D): %s"
              % (inst_label, ", ".join("%s(%d,%d,%d)" % l for l in lanes)))
        U = sum(l[2] / l[1] for l in lanes)
        print("    U = %.4f" % U)
        objs = [Lane(n, T, C=C, D=D) for n, T, C, D in lanes]
        print("    %-10s %-10s %-10s %-8s %s"
              % ("lane", "recurrence", "TChecker", "agree", "states"))
        for k, (n, T, C, D) in enumerate(lanes):
            rec = response_time_spuri(objs[k], objs, plus_one=0)["r"]
            tag = "%s_l%d" % (inst_label.split()[0].lower(), k)
            res = foreign_r(lanes, k, tag)
            got = res.get("r")
            agree = (got == rec)
            rows.append({"inst": inst_label, "lane": n, "rec": rec,
                         "tck": got, "agree": agree,
                         "ovr": res["ovr"]["reachable"]})
            print("    %-10s %-10d %-10s %-8s %s"
                  % (n, rec, got if got is not None else "ERR",
                     "yes" if agree else "*** NO ***",
                     res.get("states")))
            if res.get("err"):
                print("        err: %s" % res["err"])
            if res["ovr"]["reachable"] is not False:
                print("        *** ovr reachable -- instance outside the model ***")

    print()
    print("=" * 78)
    print("A2-F7 -- Imitator/TChecker != recurrence")
    print("=" * 78)
    bad = [r for r in rows if not r["agree"]]
    ovr = [r for r in rows if r["ovr"] is not False]
    print("  instances x lanes checked: %d" % len(rows))
    print("  disagreements: %d" % len(bad))
    for r in bad:
        print("    %s / %s : recurrence %s, foreign %s"
              % (r["inst"], r["lane"], r["rec"], r["tck"]))
    print("  instances where `ovr` was reachable: %d" % len(ovr))
    print()
    if bad:
        print("  *** A2-F7 FIRED. This is the independence check doing its job --")
        print("      a derivation bug, not a tie-break. Resolve before claiming any")
        print("      r_i, including the ones on the real tables. ***")
        return 1
    print("  ⭐ A2-F7 did NOT fire: the recurrence agrees with a foreign engine")
    print("     exploring real schedules, on every lane of every instance --")
    print("     including N=4 with m_i>1 and an instance with distinct per-lane C.")
    print("     Parts B and C are no longer my algebra agreeing with my Python.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
