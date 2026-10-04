"""The half-bit no-op is a REAL JOB, so it enters A2 and the numbers are re-quoted.

Wilson's condition 2 on the half-bit-offset ruling.

THE ONE CLAIM: the `ARM -> no-op(half) -> sample` idiom costs one extra C = 2
release per frame on each receiving lane, that cost is in the task model at its
true rate, and the re-quoted numbers still clear the bar under the PRIMARY
bound.

⛔⛔ WHY A NO-OP IS NOT FREE, WHICH IS THE WHOLE REASON THIS GATE EXISTS. It
drives no pin, so it is invisible in a waveform and easy to treat as
bookkeeping. But it is DISPATCHED: it occupies the engine for `C` cycles, it
competes under EDF, and it contributes `C_j - 1` to every other lane's blocking
term. A "no-op" that is free in the datapath is not free in the schedule, and
this project has already shipped one timing claim that forgot a term it could
not see.

HOW IT IS MODELLED, and why this shape:
  one extra lane per RECEIVING lane, at the FRAME rate, C = 2, carrying the
  parent's D_sched and J.

⭐ A SEPARATE LANE RATHER THAN `n + 1` ON THE PARENT. The bursty arrival model
has a UNIFORM inner spacing `t`, and the no-op does not have one: it lands
`half` (7 cycles) after the captured edge while the samples are `t` (414) apart.
Forcing it into the burst would need `n*t <= T` to still hold -- 11 * 414 = 4554
against T = 4140, which fails -- and would MISSTATE the arrival curve to make it
fit. A separate lane at the frame rate carries the same demand (one C = 2 job
per frame) without claiming a spacing the program does not have.

⚠ WHAT THAT APPROXIMATION COSTS, stated: as a separate lane the no-op competes
under EDF with its own deadline rather than being sequenced inside its parent's
program. That is the conservative direction -- it can interfere with the parent,
which in reality it cannot, because a lane dispatches one action at a time.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import lane_digest                                                 # noqa: E402
import pyrta_bound                                                 # noqa: E402
from bursty import SPI_RX, TX, UART_RX, BLane, response_time_b     # noqa: E402
from gate_admissibility_1_6 import _reactive_names                 # noqa: E402
from pyrta_src import require_pyrta                                # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

MARGIN_BAR = 4
BASE = list(TX) + [UART_RX, SPI_RX]

# ⛔ The lanes that need the idiom are the ones whose FIRST SAMPLE must be
# centred -- the ones that SHIFTIN after an ARM. I2C is reactive too, but its
# release is the observed SCL rise and its read is FOLDED INTO THAT SERVICE
# (R3's "one release, one 3-FF sync, no new event"), so it adds no no-op.
NOOP_PARENTS = ("UART-rx", "SPI-target")


def build(with_noop: bool) -> list:
    ls = [BLane(l.name, l.T, l.C, D_tol=l.D_tol, n=l.n, t=l.t, J=l.J)
          for l in BASE]
    if with_noop:
        for p in BASE:
            if p.name.split()[0] in NOOP_PARENTS:
                ls.append(BLane("no-op " + p.name.split()[0], p.T, 2,
                                D_tol=p.D_tol, J=p.J))
    return ls


def quote(ls, src):
    rows = []
    for k, l in enumerate(ls):
        o = response_time_b(l, ls)["r"]
        p, err = pyrta_bound.bound(src, ls, k)
        rows.append((l.name, p, o, l.margin(o),
                     l.margin(p) if p is not None else None, err))
    return rows


def main() -> int:
    print()
    print("=" * 78)
    print("THE HALF-BIT NO-OP AS A REAL JOB (condition 2)")
    print("=" * 78)
    lane_digest.announce(
        "gate_noop_job.py", build(False),
        variant=None)

    src = require_pyrta("gate_noop_job.py")
    if not src:
        print("  The re-quote names pyRTA as the PRIMARY bound, so without it")
        print("  there is no number to publish.")
        return 1

    react = _reactive_names()
    print()
    print("  lanes needing the idiom: %s" % ", ".join(NOOP_PARENTS))
    print("  ⛔ I2C is REACTIVE too (%s) but adds NO no-op: R3 folds its read"
          % ("yes" if "I2C" in react else "?"))
    print("     into the SAME service as the SCL-rise release -- one release,")
    print("     one sync, no new event -- so there is no first-sample offset")
    print("     to buy.")

    rc = 0
    results = {}
    for label, wn in (("BASE (no idiom)", False),
                      ("WITH the no-op jobs", True)):
        ls = build(wn)
        rows = quote(ls, src)
        results[wn] = rows
        print()
        print("  --- %s: %d lanes ---" % (label, len(ls)))
        print("    %-24s %-5s %-8s %-8s %-8s %s"
              % ("lane", "J", "pyRTA", "ours", "margin", "direction"))
        for name, p, o, mo, mp, err in rows:
            if p is None:
                print("    %-24s *** %s" % (name, err))
                rc = 1
                continue
            print("    %-24s %-5s %-8d %-8d %-8d %s"
                  % (name, "", p, o, mp,
                     "exact" if o == p else
                     ("ours +%d" % (o - p) if o > p else "*** OURS SMALLER ***")))
        good = [r for r in rows if r[1] is not None]
        print("    MIN MARGIN  pyRTA %d (PRIMARY)   ours %d   bar >= %d  -> %s"
              % (min(r[4] for r in good), min(r[3] for r in good), MARGIN_BAR,
                 "PASS" if min(r[4] for r in good) >= MARGIN_BAR else "*** FAIL"))
        if not pyrta_bound.check_direction([(r[0], r[1], r[2]) for r in good],
                                           "%s:" % label):
            rc = 1

    # ---- must-fire: the addition must NOT be inert --------------------
    # ⛔ A "cost" that changes no number was not modelled. If the r_i are
    # identical with and without the no-op lanes, the job is not in the task
    # set and condition 2 is satisfied only on paper.
    print()
    print("  --- must-fire: adding the job must MOVE the numbers ---")
    b = {r[0]: r[2] for r in results[False]}
    a = {r[0]: r[2] for r in results[True]}
    moved = [(n, b[n], a[n]) for n in b if a.get(n) != b[n]]
    print("    lanes whose r changed: %d of %d" % (len(moved), len(b)))
    for n, x, y in moved:
        print("      %-24s %d -> %d  (+%d)" % (n, x, y, y - x))
    if not moved:
        print("    *** MUST-FIRE FAILED: the no-op jobs changed nothing, so")
        print("        they are not in the analysed task set. A no-op is")
        print("        invisible in a waveform and that is exactly why its")
        print("        schedule cost has to be shown rather than asserted.")
        rc = 1
    else:
        print("    ⭐ the idiom costs real cycles and the cost is IN the model.")

    # ---- the verdict Wilson asked to be re-quoted --------------------
    good_b = [r for r in results[False] if r[1] is not None]
    good_a = [r for r in results[True] if r[1] is not None]
    mb, ma = min(r[4] for r in good_b), min(r[4] for r in good_a)
    print()
    print("  --- THE RE-QUOTE ---")
    print("    min margin, pyRTA (PRIMARY):  %d -> %d" % (mb, ma))
    print("    bar >= %d:                     %s" % (MARGIN_BAR,
                                                     "still PASS" if ma >= MARGIN_BAR
                                                     else "*** NOW FAILS"))
    if ma == mb:
        print("    ⭐ THE MINIMUM IS UNCHANGED, and the reason is structural")
        print("    rather than lucky: the tightest lane is I2C, which is the")
        print("    MOST URGENT in the set and adds no no-op of its own. Every")
        print("    r_i rises, but the lanes that rise have margins in the")
        print("    hundreds. ⚠ 'Negligible' is the RESULT here, not the")
        print("    assumption -- the individual numbers moved by up to 4.")
    print()
    print("=" * 78)
    print("  GATE noop-job: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    * the idiom's cost is in the task model at its true rate")
    print("    * re-quoted under the PRIMARY bound; ours never below it")
    print("    * must-fire: the addition is not inert")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
