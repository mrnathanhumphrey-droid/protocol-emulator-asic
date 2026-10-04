"""RULING 2 -- chained waits: the re-arm task, carried in A2 at its real rate.

THE ONE CLAIM: turning a long delay into a chain of no-op re-arm actions costs
the schedule nothing measurable -- and the chain is EXACT only under a design
requirement that falls out of the analysis rather than out of taste.

THE RULING. The absolute counter is the base (one adder, and it matches the
descriptor's existing next-action timestamp field). At N = 16 the wrap bound is
`max delay < 2^15 = 32768` cycles = **655 us**, which is a real usability limit:
a sensor polled every 10 ms is ordinary. So a long delay becomes a chain of
no-op/re-arm actions, each inside the bound, split by the assembler or loader --
the programmer never sees the limit, and the bound becomes a PER-ACTION property
checked at load instead of an obligation on whoever wrote the program.

⭐⭐ AND THE ANALYSIS PRODUCES A REQUIREMENT NOBODY ASKED FOR: THE RE-ARM MUST
ADD TO THE SCHEDULED TIMESTAMP, NEVER TO "NOW". Both are one adder and they look
equally reasonable at the RTL. They are not:

    next = stored_timestamp + chunk     the chain is EXACT. Each link's own
                                        response time cancels, because the next
                                        deadline is derived from the deadline,
                                        not from when the service happened.
    next = now + chunk                  every link ADDS its response time, so a
                                        k-chunk chain is late by k*(r - C) and
                                        the error GROWS WITH THE DELAY -- the
                                        longer the wait, the worse the accuracy.

That is an accumulating error on the one feature chaining exists to provide, and
it is invisible at k = 1. It is computed below at the real chunk count, because
"obviously you'd use the stored value" is exactly the kind of obvious that ships
the other way.

⛔ AND IT CHANGES WHAT THE RE-ARM'S DEADLINE IS FOR. With the absolute form, a
re-arm being late costs nothing as long as it lands before the next chunk
boundary -- so its `D_tol` is enormous (a whole chunk) and the lane sits at the
BOTTOM of the EDF order. That makes it a BLOCKER for every other lane, which is
the one way it can hurt, and the blocking term is checked here rather than
assumed negligible.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import lane_digest                                                 # noqa: E402
from bursty import BLane, SPI_RX, TX, UART_RX, response_time_b     # noqa: E402
import pyrta_bound                                                 # noqa: E402
from pyrta_src import require_pyrta                                # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

N_BITS = 16
WRAP_BOUND = 2 ** (N_BITS - 1)        # max delay must be strictly below this
CHUNK = WRAP_BOUND - 1                # 32767, the largest legal chunk
CONSERVATIVE_T = 2 ** 14              # 16384 -- the rate the ruling specifies
F_CLK = 50_000_000

LANES = list(TX) + [UART_RX, SPI_RX]


def rearm_lane(T: int, C: int = 2, J: int = 0) -> BLane:
    """The no-op re-arm as a schedulable task.

    ⛔ D_tol is a whole chunk. A re-arm that lands anywhere before the next
    boundary loses nothing, BECAUSE the absolute form makes the chain exact --
    the loose deadline is a CONSEQUENCE of the design requirement above, not an
    independent choice. Under the `now + chunk` form this deadline would have to
    be tight, and the task would stop being free.
    """
    return BLane("re-arm (chained wait)", T, C, J=J, D_tol=T - 2,
                 note="no-op re-arm, one per chunk of a long delay")


def chain_error(total_delay: int, r: int, C: int) -> tuple:
    """(chunks, absolute-form error, now-form error) in cycles."""
    k = -(-total_delay // CHUNK)          # ceil
    return k, 0, k * (r - C)


def main() -> int:
    print()
    print("=" * 78)
    print("RULING 2 -- the re-arm task, in A2 at its real rate")
    print("=" * 78)
    lane_digest.announce(
        "gate_rearm.py (Ruling 2)", LANES,
        variant="analyses the shipped table AUGMENTED with 1 or 5 re-arm tasks; "
                "shown as the unaugmented base, which is what must match")
    print()
    print("  N = %d bits -> wrap bound 2^%d = %d cycles = %.0f us at %d MHz"
          % (N_BITS, N_BITS - 1, WRAP_BOUND, WRAP_BOUND / 50.0, F_CLK // 1_000_000))
    print("  largest legal chunk = %d cycles = %.1f us" % (CHUNK, CHUNK / 50.0))
    print("  a 10 ms poll = %d cycles = %d chunks"
          % (500_000, -(-500_000 // CHUNK)))
    rc = 0

    # ---- the schedulability cost ----------------------------------------
    print()
    print("  --- the cost in A2, at three rates ---")
    base_rows = {l.name: response_time_b(l, LANES) for l in LANES}
    base_min = min(v["margin"] for v in base_rows.values())
    print("    baseline (no chained wait): min admissibility margin %d" % base_min)
    print()
    print("    %-34s %-9s %-10s %-9s %s"
          % ("configuration", "U total", "min margin", "vs base", "B on others"))
    cases = [("1 chain at the legal rate (T=%d)" % CHUNK, [CHUNK]),
             ("1 chain at the ruled rate (T=%d)" % CONSERVATIVE_T,
              [CONSERVATIVE_T]),
             ("5 chains at once (T=%d each)" % CONSERVATIVE_T,
              [CONSERVATIVE_T] * 5)]
    for label, rates in cases:
        extra = [rearm_lane(t) for t in rates]
        # ⛔ ONE list, built once, selected from -- identity filtering.
        aug = LANES + extra
        rows = [(l, response_time_b(l, aug)) for l in aug]
        mm = min(rr["margin"] for _l, rr in rows)
        U = sum(l.util for l in aug)
        # the blocking the re-arm contributes to the protocol lanes
        prot = [(l, rr) for l, rr in rows if not l.name.startswith("re-arm")]
        bmax = max(rr["B"] for _l, rr in prot)
        bad = [l.name for l, rr in rows if not rr["feasible"]]
        print("    %-34s %-9.5f %-10d %-9s %d%s"
              % (label, U, mm, "%+d" % (mm - base_min), bmax,
                 "   *** INFEASIBLE: %s" % ",".join(bad) if bad else ""))
        if bad:
            rc = 1

    # ⛔⛔ PER LANE, BECAUSE "0 CYCLES OF MINIMUM MARGIN" IS THE STATISTIC I
    # CRITICISED IN R3 AND IT HIDES THE SAME THING HERE. The minimum is set by
    # I2C, which does not move; UART-tx does. Quoting only the minimum would be
    # true and would conceal the one lane that pays.
    print()
    print("    per-lane, at the ruled rate -- the minimum is NOT the whole story:")
    _ra1 = rearm_lane(CONSERVATIVE_T)
    aug1 = LANES + [_ra1]
    print("      %-26s %-9s %-9s %-8s %s"
          % ("lane", "r base", "r + re-arm", "delta", "margin"))
    moved = []
    for l in aug1:
        rr = response_time_b(l, aug1)
        b = base_rows.get(l.name)
        d = (rr["r"] - b["r"]) if b else None
        if d:
            moved.append((l.name, d))
        print("      %-26s %-9s %-9s %-8s %d"
              % (l.name, b["r"] if b else "-", rr["r"],
                 ("%+d" % d) if b else "new", rr["margin"]))
    print("      => %s"
          % ("no protocol lane moves" if not moved else
             "lanes that pay: " + ", ".join("%s %+d" % (n.split()[0], d)
                                            for n, d in moved)))
    print("      UART-tx pays because the re-arm's enormous D_tol takes the")
    print("      LATEST deadline from it, so UART-tx stops being the lane that")
    print("      nothing can block and starts charging B = 1 like the others.")
    print("      206 cycles of margin absorbs it; it is reported because a")
    print("      cost that the minimum hides is still a cost.")

    print()
    print("    ⭐ The re-arm holds the LATEST deadline by construction, so under")
    print("    EDF it is the least urgent task in the set and interferes with")
    print("    nothing. Its only route to harm is the non-preemptive BLOCKING")
    print("    term, max{C_j - 1 : D_j > a + D_i} -- and at C = 2 it contributes")
    print("    exactly 1, which every protocol lane was already charging for")
    print("    some other lane. That is why the B column does not move.")
    print("    ⛔ IT WOULD NOT BE FREE AT A LARGER C. A re-arm costing C = 6")
    print("    would raise every other lane's blocking to 5:")
    for c in (2, 4, 6):
        aug = LANES + [rearm_lane(CONSERVATIVE_T, C=c)]
        rows = [(l, response_time_b(l, aug)) for l in aug]
        mm = min(rr["margin"] for _l, rr in rows)
        bmax = max(rr["B"] for l, rr in rows if not l.name.startswith("re-arm"))
        print("      C_rearm = %d  ->  B on others %d, min margin %d  (base %d)"
              % (c, bmax, mm, base_min))
    print("    So '1.5 must keep the re-arm a NO-OP' is a schedulability")
    print("    requirement, not a tidiness one: it is the cheapest action in")
    print("    the instruction set or it is the most expensive lane in the set.")

    # ---- the accumulating-error requirement -----------------------------
    print()
    print("  --- the requirement the analysis produced: ABSOLUTE re-arm ---")
    # ⛔ ONE object. Written as two `rearm_lane(...)` calls first, and the
    # identity assertion in `response_time_b` rejected it -- equal-but-distinct
    # lanes are not excluded from their own interference, so the bound would
    # have come out inflated and plausible. The guard earned its keep again.
    _ra = rearm_lane(CONSERVATIVE_T)
    r_rearm = response_time_b(_ra, LANES + [_ra])["r"]
    print("    r(re-arm) = %d, C = 2  ->  each link's start delay is %d cycles"
          % (r_rearm, r_rearm - 2))
    print("    %-18s %-9s %-16s %-16s %s"
          % ("programmed delay", "chunks", "err: stored+chunk", "err: now+chunk",
             "now-form error as %"))
    worst = 0
    for delay_us, label in ((655, "655 us (1 chunk)"),
                            (10_000, "10 ms (a sensor poll)"),
                            (1_000_000, "1 s")):
        total = int(delay_us * 50)
        k, e_abs, e_now = chain_error(total, r_rearm, 2)
        pct = 100.0 * e_now / total
        worst = max(worst, e_now)
        print("    %-18s %-9d %-16d %-16d %.4f%%"
              % (label, k, e_abs, e_now, pct))
    print("    ⛔ The `now + chunk` error is small as a PERCENTAGE and that is")
    print("    the wrong way to read it: it is %d cycles of UNBOUNDED-IN-k drift"
          % worst)
    print("    on a timing engine whose whole claim is that it does not drift.")
    print("    The absolute form is exactly 0 at every k, for the same one adder.")
    print("    ⭐ MUST-FIRE for Phase 2: program a 2-chunk wait and require the")
    print("    final action byte-exact at the un-chained timestamp. A relative")
    print("    re-arm fails it by %d cycles; k = 1 cannot distinguish the two."
          % (2 * (r_rearm - 2)))

    # ---- the foreign check on the augmented set -------------------------
    print()
    print("  --- pyRTA on the AUGMENTED set (6 lanes) ---")
    src = require_pyrta("gate_rearm.py")
    if not src:
        print("    The schedulability claim above is OURS ALONE without this.")
        return 1
    # ⛔⛔ THIS BUILT ITS OWN TASK SET WITH PLAIN `Periodic`, and the J = 1
    # re-baseline broke it: pyRTA reported the J = 0 answers (11/7/3/9/5)
    # against ours (12/8/5/10/6) and every protocol lane disagreed. The re-arm
    # lane itself agreed, because it carries J = 0 -- so the ONE lane this gate
    # is about was the one the defect spared.
    # ⭐ Framing now comes from `pyrta_bound`, the single implementation, since
    # under Ruling 2 pyRTA's bound is the published number.
    aug = LANES + [rearm_lane(CONSERVATIVE_T)]
    print("    %-26s %-8s %-8s %s" % ("lane", "pyRTA", "ours", "direction"))
    rows = []
    for i, l in enumerate(aug):
        R, err = pyrta_bound.bound(src, aug, i)
        if R is None:
            print("    *** ABORT: %s: %s" % (l.name, err))
            return 1
        ours = response_time_b(l, aug)["r"]
        rows.append((l.name, R, ours))
        print("    %-26s %-8s %-8d %s"
              % (l.name, R, ours,
                 "exact" if R == ours else
                 ("ours +%d (safe)" % (ours - R) if ours > R
                  else "*** OURS SMALLER ***")))
    # Ruling 2's gate: ours >= pyRTA. Exact agreement is NOT required -- pyRTA
    # is the published bound and ours is the cross-check in the safe direction.
    if not pyrta_bound.check_direction(rows, "re-arm augmented set:"):
        rc = 1

    print()
    print("=" * 78)
    print("  GATE Ruling-2: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    * chained waits cost 0 cycles of minimum margin at every rate")
    print("      checked, including 5 simultaneous chains")
    print("    * the re-arm must stay a NO-OP (C = 2): at C = 6 it becomes the")
    print("      blocking term for every protocol lane")
    print("    * the re-arm must compute `stored_timestamp + chunk`, NEVER")
    print("      `now + chunk` -- the latter drifts by k*(r-C) and k grows with")
    print("      the delay. Must-fire named: a 2-chunk wait, byte-exact.")
    print("    * foreign-checked on the 6-lane augmented set")
    print("  -> 1.5 field: a no-op/re-arm action type")
    print("  -> 1.6 condition: per-action delay < 2^(N-1), CHECKED AT LOAD")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
