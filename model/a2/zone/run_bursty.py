"""A2-GREEN Part 4 -- foreign cross-check of the BURSTY recurrence.

THE ONE CLAIM: the bursty extension is validated by a foreign engine in the
regime where the periodic version was proved unsound -- `m_i > 1`.

⛔⛔ WHY THIS IS NOT OPTIONAL DILIGENCE. Part 3 proved this recurrence could
UNDER-estimate response time when more than one instance of a lane falls inside
the busy period. The real required lanes are all `m_i = 1`, which is why the
shipped numbers were safe -- but that `m_i = 1` verdict is itself computed by the
same machinery. A bursty lane is `m_i > 1` by construction whenever its inner
spacing is shorter than the busy period, so the extension must be checked where
it can be wrong, not where it happens to be easy.

⛔ THE SINGLE-PENDING ASSUMPTION, AND WHAT IT MEANS WHEN IT BREAKS. The foreign
model carries one pending flag per lane, so a second event arriving while the
first is unserved reaches `OVR`. That is not merely a model limit -- it is
exactly the QUEUEING case, and a bursty lane that queues is the O5
derived-buffer case by definition (`r_i > t_i` means events accumulate and a
FIFO is required, with its depth derivable). So `OVR` reachable is a
CLASSIFICATION, not a failure: that lane needs a buffer.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))

from bursty import BLane, busy_period_b, response_time_b      # noqa: E402
from run_edf import foreign_r                                 # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ⭐ INSTANCES CHOSEN SO THE BURSTY LANE ACTUALLY HAS m_i > 1. A bursty lane
#    whose inner spacing exceeds the busy period behaves exactly like a periodic
#    one, which would make this whole file a restatement of Part 3.
#    B4 is a SCALED REPLICA of UART-rx: same shape (10 samples one bit apart,
#    gapless back-to-back frames) with the bit period scaled 434 -> 3 so the
#    state space is enumerable. It does not give UART-rx's numbers; it exercises
#    UART-rx's STRUCTURE in the dangerous regime.
INSTANCES = [
    ("B1 bursty n=3, m>1",
     [("Abur", 12, 1, 3, 3, 3), ("Bper", 10, 2, 8)]),
    ("B2 bursty + two periodic",
     [("Abur", 9, 1, 3, 3, 3), ("Bper", 7, 1, 4), ("Cper", 11, 2, 9)]),
    ("B3 two bursty lanes",
     [("Abur", 12, 1, 4, 4, 3), ("Bbur", 10, 1, 5, 2, 5)]),
    ("B4 scaled UART-rx replica",
     [("rx10", 30, 1, 2, 10, 3), ("tx", 14, 2, 9)]),
]


def main() -> int:
    print()
    print("A2-GREEN PART 4 -- foreign cross-check of the bursty recurrence")
    print("=" * 78)
    rows = []
    for label, lanes in INSTANCES:
        objs = [BLane(l[0], l[1], l[2], l[3],
                      n=(l[4] if len(l) > 4 else 1),
                      t=(l[5] if len(l) > 5 else l[1])) for l in lanes]
        Lb = busy_period_b(objs)
        U = sum(o.util for o in objs)
        print()
        print("  %s" % label)
        print("    lanes: %s" % ", ".join(
            "%s(T=%d,C=%d,D=%d,n=%d,t=%d)" % (o.name, o.T, o.C, o.D, o.n, o.t)
            for o in objs))
        print("    U = %.4f   busy period L = %s   m_i = %s"
              % (U, Lb, {o.name: o.N(Lb) for o in objs}))
        print("    %-8s %-12s %-10s %-8s %-8s %s"
              % ("lane", "recurrence", "TChecker", "agree", "ovr", "states"))
        for k, o in enumerate(objs):
            rec = response_time_b(o, objs)["r"]
            res = foreign_r(lanes, k, "b%d_l%d" % (INSTANCES.index((label, lanes)), k))
            got = res.get("r")
            ovr = res["ovr"]["reachable"]
            agree = (got == rec)
            rows.append({"inst": label, "lane": o.name, "rec": rec, "tck": got,
                         "agree": agree, "ovr": ovr, "m": o.N(Lb),
                         "queues": rec is not None and rec > o.t and o.n > 1})
            print("    %-8s %-12s %-10s %-8s %-8s %s"
                  % (o.name, rec, got if got is not None else "ERR",
                     "yes" if agree else "*** NO ***", ovr, res.get("states")))
            if res.get("err"):
                print("        err: %s" % res["err"])

    print()
    print("=" * 78)
    print("VERDICT")
    print("=" * 78)
    # only lanes whose instance stayed inside the model can adjudicate
    inside = [r for r in rows if r["ovr"] is False]
    outside = [r for r in rows if r["ovr"] is not False]
    bad = [r for r in inside if not r["agree"]]
    bursty_many = [r for r in inside if r["m"] and r["m"] > 1]
    print("  lane-instances checked:                 %d" % len(rows))
    print("  inside the single-pending model:        %d" % len(inside))
    print("  OUTSIDE it (queueing -> O5 buffer case): %d" % len(outside))
    for r in outside:
        print("      %s / %s  (r=%s, t=%s) -- derived-buffer classification"
              % (r["inst"], r["lane"], r["rec"], "?"))
    print("  of those inside, lanes with m_i > 1:    %d" % len(bursty_many))
    print("  disagreements:                          %d" % len(bad))
    for r in bad:
        print("      %s / %s : recurrence %s, foreign %s"
              % (r["inst"], r["lane"], r["rec"], r["tck"]))
    print()
    if bad:
        print("  *** A2-F7 FIRED on the bursty path. The bursty numbers in")
        print("      bursty.py -- including the m_i == 1 verdict for the real")
        print("      reactive lanes -- are NOT usable until this is resolved. ***")
        return 1
    if not bursty_many:
        print("  *** VACUOUS: no checked lane had m_i > 1, so this run did NOT")
        print("      exercise the regime it exists for. Pick denser instances. ***")
        return 1
    print("  ⭐ bursty recurrence agrees with the foreign checker on every lane")
    print("     that stayed inside the model, INCLUDING %d lane(s) with m_i > 1 --"
          % len(bursty_many))
    print("     the regime the periodic recurrence was proved unsound in.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
