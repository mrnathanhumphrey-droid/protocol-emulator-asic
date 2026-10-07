"""Ruling Z -- our recurrence searches Spuri's full candidate set, and the old
search is shown failing against the exact witness.

⛔⛔ WHAT WAS WRONG. `bursty.response_time_b` evaluated r(a) only at the
subject's own release offsets. Spuri's EDF analysis (INRIA RR-2772, 1996) needs
every offset where a term of the recurrence steps -- including each
interferer's `kT_j + m*t_j - J_j + D_j - D_i`. Missing them under-estimates r:
MEASURED below TChecker's exact worst case on 7 of 8 queue-depth-one instances,
and below the full set on 184 of 6,601 lane-instances with NO jitter. Our
recurrence is the cross-check on pyRTA and the ONLY floor CI has (pyRTA is not
in CI), so an under-estimate there is a CI that accepts what the published
bound would refuse.

THE CHECKS (no pyRTA, no WSL -- the exact verdicts are RECORDED in
`model/a2/jitter_instances.py` by `model/a2/zone/run_z.py`):
  1. on every recorded exact instance (Z, LJ, Z4 ties under both tie rules),
     the fixed recurrence is >= the truth
  2. must-fire: the old search (`spuri_candidates=False`) is below the truth on
     7 of the 8 Z instances -- the count is a LIVE pin
  3. the step set is COMPLETE: on a deterministic sweep it equals a dense
     brute-force candidate set on every lane-instance
  4. must-fire: on the same sweep's no-jitter half the old search falls short
     of the fixed one on the recorded number of lane-instances (LIVE pin)
"""

from __future__ import annotations

import os
import random
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "a2"))

import bursty                                                     # noqa: E402
from bursty import BLane                                          # noqa: E402
from jitter_instances import (LJ_INSTANCES, LJ_RECORDED,        # noqa: E402
                              TIE_INSTANCES, TIE_RECORDED, Z_INSTANCES,
                              Z_RECORDED)

#: the deterministic sweep: (seed, trials) -> (lane-instances, old < fixed on
#: the no-jitter half). LIVE: recomputed every run and compared.
SWEEP = {"seed": 3, "trials": 3000, "expect": (6601, 184)}


def lanes_of(spec):
    return [BLane(n, T, C, D, n=nb, t=t, J=J) for (n, T, C, D, nb, t, J) in spec]


def r_of(objs, k, full=True):
    return bursty.response_time_b(objs[k], objs, spuri_candidates=full)["r"]


def dense(objs, k):
    """A brute-force candidate set: every offset in [0, 40] plus +-2 around
    every step of every lane, with and without J -- strictly larger than the
    step set, so equality says no step is missing."""
    sub = objs[k]
    hz = bursty.busy_period_b(objs) + max(o.T for o in objs)
    c = set(bursty.BLane.arrivals(sub, hz))
    c.update(range(0, min(hz, 40) + 1))
    for o in objs:
        for kk in range(0, hz // o.T + 3):
            for m in range(o.n):
                for a in (kk * o.T + m * o.t + o.D - o.J - sub.D,
                          kk * o.T + m * o.t + o.D - sub.D):
                    c.update(x for x in range(a - 2, a + 3) if 0 <= x <= hz)
    sub.arrivals = lambda h, cc=sorted(c): [x for x in cc if x <= h]
    try:
        return bursty.response_time_b(sub, objs, spuri_candidates=False)["r"]
    finally:
        del sub.arrivals


def main() -> int:
    rc = 0
    print()
    print("=" * 78)
    print("  Z -- SPURI'S CANDIDATE SET, AGAINST THE EXACT WITNESS")
    print("=" * 78)

    # ---- 1 + 2: recorded exact instances ----------------------------------
    print()
    print("  --- 1. fixed recurrence >= TChecker on every recorded instance ---")
    below, n, old_below = [], 0, 0
    for name, k, spec in Z_INSTANCES:
        objs = lanes_of(spec)
        new, old, tck = r_of(objs, k), r_of(objs, k, False), Z_RECORDED[name]["tck"]
        n += 1
        if new < tck:
            below.append((name, new, tck))
        if old < tck:
            old_below += 1
        if old != Z_RECORDED[name]["old"]:
            print("    *** %s: old search gives %d, recorded %d"
                  % (name, old, Z_RECORDED[name]["old"]))
            rc = 1
        print("    %-14s tck %2d   fixed %2d   old %2d%s"
              % (name, tck, new, old, "   <-- old BELOW truth" if old < tck
                 else ""))
    for name, spec in LJ_INSTANCES:
        objs = lanes_of(spec)
        for k in range(len(spec)):
            if (name, k) not in LJ_RECORDED:
                continue
            new, tck = r_of(objs, k), LJ_RECORDED[(name, k)]
            n += 1
            if new < tck:
                below.append(("%s/%d" % (name, k), new, tck))
    for name, k, spec in TIE_INSTANCES:
        objs = lanes_of(spec)
        new = r_of(objs, k)
        for tie in ("nondet", "index"):
            n += 1
            if new < TIE_RECORDED[name][tie]:
                below.append(("%s %s" % (name, tie), new,
                              TIE_RECORDED[name][tie]))
    for b in below:
        print("    *** %s: fixed recurrence %d < exact %d -- UNSOUND" % b)
        rc = 1
    print("    %d exact verdict(s): fixed recurrence >= truth on %d"
          % (n, n - len(below)))
    print()
    print("  --- 2. must-fire: the OLD search is below the truth ---")
    want = sum(1 for nm, _k, _s in Z_INSTANCES
               if Z_RECORDED[nm]["old"] < Z_RECORDED[nm]["tck"])
    ok2 = old_below == want == 7
    print("    old search below TChecker on %d of %d Z instances (recorded %d)"
          "   %s" % (old_below, len(Z_INSTANCES), want,
                     "ok" if ok2 else "*** WRONG"))
    if not ok2:
        rc = 1

    # ---- 3 + 4: the sweep -------------------------------------------------
    print()
    print("  --- 3/4. deterministic sweep: step set complete; no-jitter "
          "shortfall ---")
    random.seed(SWEEP["seed"])
    tot = short = gaps = 0
    for _t in range(SWEEP["trials"]):
        nl = random.choice([2, 3])
        ln = [(random.randint(6, 14), random.randint(1, 3)) for _ in range(nl)]
        ln = [(T, C, random.randint(C + 1, T)) for T, C in ln]
        if sum(C / T for T, C, _D in ln) > 0.8:
            continue
        objs = [BLane("l%d" % i, T, C, D, J=0) for i, (T, C, D) in enumerate(ln)]
        for k in range(nl):
            new, old = r_of(objs, k), r_of(objs, k, False)
            tot += 1
            if old < new:
                short += 1
            if new != dense(objs, k):
                gaps += 1
    ok3 = gaps == 0
    ok4 = (tot, short) == SWEEP["expect"]
    print("    %d no-jitter lane-instances: step set == dense set on all%s   %s"
          % (tot, "" if ok3 else " EXCEPT %d" % gaps,
             "ok" if ok3 else "*** INCOMPLETE"))
    print("    old search short of the fixed one on %d (recorded %d of %d)   %s"
          % (short, SWEEP["expect"][1], SWEEP["expect"][0],
             "ok" if ok4 else "*** DRIFT"))
    if not (ok3 and ok4 and short > 0):
        rc = 1

    print()
    print("=" * 78)
    print("  GATE spuri-candidates: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
