"""L_sync DERIVED from the sync chain's structure, and checked against A2's value.

THE ONE CLAIM: the input-change-to-edge-visible latency of the shipped chain is
derived from `q0 -> q1 -> q2` with `rise = q1 & ~q2`, and it is <= the
`L_SYNC = 3` A2 has been carrying with uncertainty <= the `L_JIT = 1` it
budgets -- so the constants in the proof are now true of the chip.

⛔⛔ WHY THIS GATE EXISTS. `L_SYNC = 3` and `L_JIT = 1` have been in `bursty.py`
since 0.9b, used to derive every reactive lane's `D_tol`
(`D_tol = half - tSU - L_sync - out_reg - [C]`). The chip had TWO sync stages
and NO edge detect at all, so those two constants described a mechanism that did
not exist -- which is the same error as R3's "costs nothing" and N1a's "no new
mechanism is needed". A number used in a derivation has to be a number about the
hardware.

THE STRUCTURE, stated before it is modelled:

    uio_in --> q0 --> q1 --> q2            (three flops, project.v)
    rise = q1 & ~q2                        (combinational)

and the ENGINE samples `rise` on a clock edge, because the capture
(`l_armed`/`l_timestamp`) is registered. So "visible" means "sampled by the
engine", not "asserted on a wire".

⭐ THE UNCERTAINTY IS THE POINT, NOT THE LATENCY. A fixed offset is absorbable
into `D_tol` -- the bench measures a constant 18 cycles from peer edge to pin
move and that constant is accounted below. What cannot be absorbed is the
SPREAD: an input change can land anywhere inside a cycle, so the same physical
edge is seen one cycle earlier or later depending on phase, and that spread is
jitter on a reactive lane's release. `L_JIT` is that spread and nothing else.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from bursty import L_JIT, L_SYNC                                   # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# The shipped chain. ⛔ A PARAMETER, so the must-fires can vary it rather than
# the gate asserting one number about one structure.
N_STAGES = 3


def visible_cycle(change_at: float, n_stages: int = N_STAGES) -> int:
    """Cycle on which the engine SAMPLES the edge, for an input change at
    `change_at` (in cycles, fractional = where inside the cycle it lands).

    Model, one assumption at a time:
      * a flop samples at integer cycle boundaries, so a change at `t` is
        captured by q0 at `ceil(t)` -- and a change exactly ON the boundary is
        taken as captured there (setup met);
      * each further stage adds exactly one cycle, so q_{k} holds the value from
        cycle `ceil(t) + k`;
      * `rise = q1 & ~q2` is true during the cycle in which q1 has the new value
        and q2 still has the old one -- that is cycle `ceil(t) + (n-2)` for an
        n-stage chain (q1 is stage 2 of n, q2 is stage 3);
      * the engine REGISTERS the capture, so it samples that combinational term
        at the NEXT boundary.
    """
    import math
    cap = math.ceil(change_at)              # q0 gets it here
    # q1 valid from cap+1, q2 valid from cap+2 -> `rise` true during cap+1
    rise_cycle = cap + (n_stages - 2)
    return rise_cycle + 1                   # engine samples it one edge later


def latency_range(n_stages: int = N_STAGES, samples: int = 1024) -> tuple:
    """(min, max) latency in cycles over every sub-cycle arrival phase.

    ⛔⛔ THE FIRST VERSION FLOORED THE LATENCY TO WHOLE CYCLES AND REPORTED AN
    UNCERTAINTY OF ZERO -- destroying the one quantity this gate exists to
    measure. The latency is CONTINUOUS in the arrival phase: a change just after
    a clock edge waits almost a full cycle for q0, one just before it waits
    almost none. Flooring collapsed `(2, 3]` to the single value 2, which then
    also made the 4-stage must-fire unable to fire.
    ⭐ The spread IS the jitter. A fixed offset is absorbable into `D_tol`; the
    part that cannot be absorbed is that the same physical edge is seen a cycle
    earlier or later depending on where in the cycle it lands. Rounding that
    away produces a number that looks better and means nothing.
    """
    lo, hi = None, None
    for s in range(samples):
        t = s / float(samples)              # a change anywhere inside cycle 0
        lat = visible_cycle(t, n_stages) - t
        lo = lat if lo is None else min(lo, lat)
        hi = lat if hi is None else max(hi, lat)
    return lo, hi


def main() -> int:
    print()
    print("=" * 78)
    print("L_sync DERIVED FROM THE SYNC CHAIN (edge capture)")
    print("=" * 78)
    print("  structure: uio_in -> q0 -> q1 -> q2,  rise = q1 & ~q2,")
    print("             engine REGISTERS the capture (so +1 sampling edge)")
    print("  A2 carries: L_SYNC = %d   L_JIT = %d" % (L_SYNC, L_JIT))

    lo, hi = latency_range(N_STAGES)
    import math as _m
    spread = hi - lo
    # L_sync is the WORST case in whole cycles -- the budget has to hold for
    # every arrival phase, so it rounds UP.
    l_sync_derived = int(_m.ceil(hi - 1e-9))
    print()
    print("  --- derived, over every sub-cycle arrival phase ---")
    print("    stages        : %d" % N_STAGES)
    print("    latency min   : %.3f cycles" % lo)
    print("    latency max   : %.3f cycles" % hi)
    print("    L_sync (ceil) : %d cycles" % l_sync_derived)
    print("    uncertainty   : %.3f cycle(s)" % spread)

    ok_lat = l_sync_derived <= L_SYNC
    ok_jit = spread <= L_JIT + 1e-9
    print()
    print("    L_sync <= A2's %d       : %s" % (L_SYNC,
                                                "PASS" if ok_lat else "*** FAIL"))
    print("    spread <= L_JIT (%d)    : %s" % (L_JIT,
                                                "PASS" if ok_jit else "*** FAIL"))
    if not (ok_lat and ok_jit):
        print()
        print("    ⛔ THE CHIP'S SYNCHRONISER IS SLOWER OR JITTERIER THAN THE")
        print("    PROOF ASSUMES. Every reactive lane's D_tol is derived as")
        print("    `half - tSU - L_sync - out_reg - [C]`, so a larger L_sync")
        print("    shrinks a tolerance that is already the tightest in the set.")
        return 1

    # ---- must-fires: the derivation must be sensitive to the structure ----
    print()
    print("  --- must-fire: the derivation must DEPEND on the chain ---")
    # ⛔ A derivation that returns 3 for every structure is a constant wearing a
    # function's clothes. Two directions, both checked.
    lo2, hi2 = latency_range(2)
    lo4, hi4 = latency_range(4)
    print("    2 stages (the OLD chip, no q2): latency %.3f..%.3f" % (lo2, hi2))
    print("    4 stages                      : latency %.3f..%.3f" % (lo4, hi4))
    f_short = hi2 < hi
    f_long = int(_m.ceil(hi4 - 1e-9)) > L_SYNC
    print("    a 2-stage chain is FASTER than the shipped one   : %s"
          % ("PASS" if f_short else "*** FAIL"))
    print("    a 4-stage chain EXCEEDS L_SYNC and would be red  : %s"
          % ("PASS" if f_long else "*** FAIL"))
    if not (f_short and f_long):
        print("    *** the derivation does not move with the structure, so it")
        print("        is not a derivation. ***")
        return 1
    print("    ⭐ 2 stages is faster but has NO EDGE DETECT -- `rise = q1 & ~q2`")
    print("    needs a third stage to compare against. That is why the shipped")
    print("    chain is 3 and not 2: the stage buys the EDGE, and L_sync = 3 is")
    print("    the price. A2 budgeted that price before the chip paid it.")

    # ---- the bench's measured constant, accounted ----------------------
    print()
    print("  --- cross-check: tb_edge measures 18 cycles, accounted ---")
    # peer edge -> sync -> dispatch LEVEL#1 (no visible change: reset drives the
    # protocol outputs HIGH and the first action also drives HIGH) -> d1 -> the
    # SECOND LEVEL, which is the first visible change.
    D1, C_SVC = 12, 2
    predicted = l_sync_derived + C_SVC + D1 + 1
    print("    L_sync max            %2d" % l_sync_derived)
    print("    C of the first action  %d   (LEVEL drives HIGH -- reset already" % C_SVC)
    print("                               drives the protocol outputs HIGH, so")
    print("                               the first action makes NO visible")
    print("                               change; the measured edge is the")
    print("                               SECOND action)")
    print("    programmed delay d1   %2d" % D1)
    print("    drive cycle           %2d" % 1)
    print("    predicted             %2d   measured by tb_edge: 18" % predicted)
    if predicted != 18:
        print("    ⚠ the decomposition does not reproduce the measurement, so one")
        print("      of the two is wrong. Not fatal to the L_sync bound above,")
        print("      which is structural -- but it is reported rather than")
        print("      quietly dropped.")
    else:
        print("    ⭐ the derived latency, the service time and the programmed")
        print("    delay account for the measured constant EXACTLY, which is the")
        print("    cheapest available check that the model of the chain matches")
        print("    the chain.")

    print()
    print("=" * 78)
    print("  GATE edge-capture: PASSED")
    print("    * L_sync = %d (worst case %.3f cycles) derived from q0->q1->q2"
          % (l_sync_derived, hi))
    print("      plus a registered capture")
    print("    * uncertainty %.0f <= L_JIT %d, so A2's reactive budgets hold"
          % (spread, L_JIT))
    print("    * the derivation moves with the structure (2 and 4 stages both")
    print("      give different answers), so it is not a constant in disguise")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
