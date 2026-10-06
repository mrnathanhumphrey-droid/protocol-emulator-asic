"""The clocked I2C lane's A2 row, DERIVED -- not inherited from the two-action row.

THE ONE CLAIM: under the clocked scheme the I2C lane's job stream is
near-periodic at `d`, its deadline tolerance is `d - t_LOW(min)` rather than the
15 cycles the two-action row carries, and the feasible `d` per I2C mode is a
FIXED POINT of that tolerance against the lane set's own response time.

⛔⛔ WHY THE SHIPPED ROW CANNOT BE REUSED. `bursty.py` carries
`BLane("I2C 400 kHz", T=45, D_tol=15, J=J_SHIPPED+L_JIT)`. Both numbers belong
to the TWO-ACTION idiom: `T = 45` is the short half of an ASYMMETRIC 80/45 SCL
built from `OP_SHIFT` + `OP_LEVEL`, and `D_tol = 15` was derived from UM10204
T11 for that geometry. The clocked scheme produces a DIFFERENT clock -- after
F1 it is symmetric, `low = d` and `high = d + L_sync` -- driven by one action
per bit. A row describing the other scheme would be a number that no longer
measures anything.

⭐⭐ AND THE STREAM SIMPLIFIED, which was predicted before it was computed.
BEFORE F1 the post-HIGH gap was the `L_sync` park, so a clocked lane presented
PAIRS of jobs 3 cycles apart -- a two-level burst that `BLane`'s uniform inner
spacing cannot express, and that would have needed either a pessimistic
`n = 2n+1, t = L_sync` encoding or a second lane per phase. AFTER F1 every gap
is `d` (after a LOW) or `d + L_sync` (after a HIGH), so the stream is ordinary
and periodic and the tightest spacing is `d`. The fix removed a modelling
problem as well as a compliance one.

THE DERIVATION OF `D_tol`, which is the part that must not be hand-waved:

    the LOW dispatch drives SDA and takes SCL low; the HIGH dispatch releases
    SCL. Both are released by the lane's timestamp and serviced with some start
    delay. Writeback advances the timestamp ABSOLUTELY (P8), so the HIGH's
    release is `d` after the LOW's regardless of how late the LOW was served:

        t_LOW(observed) = d + (HIGH start delay) - (LOW start delay)

    which is minimised when the LOW is as late as possible and the HIGH is on
    time. A start delay is bounded by `r_i - C_i`, so

        min t_LOW = d - (r_i - C_i)      and the requirement is
        d - (r_i - C_i) >= t_LOW(min, mode)
        ⇒ D_tol = d - t_LOW(min, mode)   in START-DELAY terms, which is what
                                         `BLane.D_tol` means.

⭐ THE MEASUREMENT AGREES ON THE SHAPE: `t_LOW` came out BELOW the programmed
`d` on every lane of the four-lane probe image -- shortfalls of 2, 5, 6 and 13
cycles -- which is this term, observed. ⚠ It is NOT used as the bound. The
shortfall on one image is an observation; `r_i - C_i` from A2 is the bound, and
quoting a measured maximum as a bound is the error that retracted a universal
`J` once already.

⛔ THE HIGH PHASE NEEDS NO SUCH TERM, and that is F1's doing. It is counted from
the OBSERVED RISE, so service lateness delays the rise-plus-`d` release and only
LENGTHENS `t_HIGH`. Only `t_LOW` has to buy margin.

⚠ `J` IS UNCHANGED AT `J_SHIPPED + L_JIT`, and the reason is stronger than
before rather than weaker: under the clocked scheme EVERY post-HIGH release is
reactive -- half of all dispatches -- where the two-action idiom had one
asynchronously captured release per byte. Charging the async-capture cycle to
the whole lane was conservative then and is closer to exact now.
"""

from __future__ import annotations

import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import gate_um10204 as um                                          # noqa: E402
import lane_digest                                                 # noqa: E402
import pyrta_bound                                                 # noqa: E402
from bursty import (C_SHIPPED, J_SHIPPED, L_JIT, L_SYNC, SPI_RX,   # noqa: E402
                    TX, UART_RX, BLane, response_time_b)
from pyrta_src import require_pyrta                                # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

#: the shipped set, and the row the clocked scheme replaces
BASE = list(TX) + [UART_RX, SPI_RX]
I2C_NAME_PREFIX = "I2C"

#: the mode ceilings, in Hz -- an I2C mode is a MAXIMUM rate, so running slower
#: is always legal and only the upper edge is a constraint.
MODE_MAX_HZ = {"Sm  100 kHz": 100_000,
               "Fm  400 kHz": 400_000,
               "Fm+ 1 MHz": 1_000_000}
F_CLK = 50_000_000

#: the reserve this project requires of a shipped margin. ⛔ IMPORTED IN SPIRIT
#: from `gate_noop_job`'s bar rather than invented here: a feasible margin of 0
#: is not a shippable one.
MARGIN_BAR = 4


def scl_period_cycles(d):
    """low = d, high = d + L_SYNC after F1, so the bit period is 2d + L_SYNC."""
    return 2 * d + L_SYNC


def scl_hz(d):
    return F_CLK / float(scl_period_cycles(d))


def clocked_i2c_lane(d, t_low_min):
    """The clocked I2C lane's A2 row at delay `d`."""
    return BLane("I2C clocked d=%d" % d, T=d, C=C_SHIPPED,
                 D_tol=d - t_low_min, J=J_SHIPPED + L_JIT,
                 note="clocked scheme: one action per bit, symmetric clock "
                      "(low=d, high=d+L_sync); D_tol = d - t_LOW(min)")


def build(d, t_low_min):
    """The shipped set with the two-action I2C row replaced by the clocked one."""
    out = []
    for l in BASE:
        if l.name.startswith(I2C_NAME_PREFIX):
            continue
        out.append(BLane(l.name, l.T, l.C, D_tol=l.D_tol, n=l.n, t=l.t, J=l.J))
    out.append(clocked_i2c_lane(d, t_low_min))
    return out


def quote(ls, src):
    rows = []
    for k, l in enumerate(ls):
        o = response_time_b(l, ls)["r"]
        p, err = pyrta_bound.bound(src, ls, k)
        rows.append((l.name, p, o, l.margin(o),
                     l.margin(p) if p is not None else None, err))
    return rows


def feasible(d, t_low_min, src):
    """Is the clocked I2C lane schedulable at this `d`? pyRTA is PRIMARY."""
    if d - t_low_min <= 0:
        return False, None, None, "D_tol <= 0"
    try:
        ls = build(d, t_low_min)
    except AssertionError as exc:
        return False, None, None, str(exc)[:60]
    k = len(ls) - 1                      # the clocked lane is last
    ours = response_time_b(ls[k], ls)["r"]
    prim, err = pyrta_bound.bound(src, ls, k)
    use = prim if prim is not None else ours
    if prim is None:
        return False, ours, None, err or "pyRTA gave no bound"
    # every lane must still meet its own tolerance, not just this one
    worst = min(l.margin(response_time_b(l, ls)["r"]) for l in ls)
    return (ls[k].margin(use) >= 0 and worst >= 0), ours, prim, None


def main() -> int:
    rc = 0
    print()
    print("=" * 78)
    print("  THE CLOCKED I2C LANE IN A2 -- D_tol AND r DERIVED, NOT INHERITED")
    print("=" * 78)
    tc = um.table_cycles()
    print("  C = %d   J = J_SHIPPED + L_JIT = %d   L_SYNC = %d"
          % (C_SHIPPED, J_SHIPPED + L_JIT, L_SYNC))
    print("  the row being REPLACED:")
    for l in BASE:
        if l.name.startswith(I2C_NAME_PREFIX):
            print("    %s  T=%d  C=%d  D_tol=%d  J=%d"
                  % (l.name, l.T, l.C, l.D_tol, l.J))
            print("    ⛔ T=45 is the short half of an ASYMMETRIC 80/45 SCL and")
            print("       D_tol=15 was derived for that geometry. Neither")
            print("       describes a symmetric one-action-per-bit clock.")

    src = require_pyrta("gate_clocked_lane_a2.py")
    if not src:
        print()
        print("  *** FAIL pyRTA is the PRIMARY bound for this re-derivation, so")
        print("      without it there is no number to publish. This gate is RED")
        print("      rather than falling back to our own recurrence -- the same")
        print("      rule every pyRTA-primary gate here follows.")
        return 1

    # -----------------------------------------------------------------
    # 1. the fixed point: the tightest feasible d per mode
    # -----------------------------------------------------------------
    print()
    print("  --- 1. the fixed point: tightest feasible d per I2C mode ---")
    print("    ⛔ `d` APPEARS ON BOTH SIDES, which is why this is a search and")
    print("    not a formula: D_tol = d - t_LOW(min) depends on d, and the r_i")
    print("    it must cover depends on the whole lane set, which contains the")
    print("    lane whose T is d. The tightest feasible d is the fixed point.")
    print()
    print("    %-13s %-9s %-8s %-8s %-8s %-9s %-11s %s"
          % ("mode", "t_LOW min", "d*", "D_tol", "r (pyRTA)", "margin",
             "SCL rate", "<= mode max?"))
    results = {}
    for mname in sorted(tc, key=lambda m: tc[m]["t_LOW"]):
        tl = tc[mname]["t_LOW"]
        found = None
        # ⭐ SEARCH UPWARD FROM THE BARE MINIMUM. A larger d both raises D_tol
        # and lengthens the lane's period, so feasibility is monotone in d
        # once it is reached -- but the FIRST feasible point is what bounds the
        # achievable bit rate, so it is searched for rather than assumed.
        for d in range(tl + 1, tl + 400):
            ok, ours, prim, why = feasible(d, tl, src)
            if ok:
                found = (d, prim, ours)
                break
        if found is None:
            print("    %-13s %-9d *** FAIL no feasible d within t_LOW+400"
                  % (mname, tl))
            rc = 1
            continue
        d, prim, ours = found
        ls = build(d, tl)
        lane = ls[-1]
        hz = scl_hz(d)
        under = hz <= MODE_MAX_HZ[mname]
        results[mname] = (d, prim, hz)
        print("    %-13s %-9d %-8d %-8d %-8d %-9d %-11s %s"
              % (mname, tl, d, lane.D_tol, prim, lane.margin(prim),
                 "%.0f kHz" % (hz / 1000.0), "yes" if under else "NO"))
        if not under:
            print("        ⚠ FASTER THAN THE MODE'S CEILING at the tightest")
            print("          feasible d -- so the binding constraint for this")
            print("          mode is the RATE, not t_LOW. See §2.")

    # -----------------------------------------------------------------
    # 2. the rate ceiling, which binds where t_LOW does not
    # -----------------------------------------------------------------
    print()
    print("  --- 2. the d each mode's RATE CEILING demands ---")
    print("    ⭐ AN I2C MODE IS A MAXIMUM RATE, so running slower is always")
    print("    legal. The two constraints therefore bind in different places,")
    print("    and the shipped d is the larger of the two.")
    print("    %-13s %-13s %-13s %-13s %s"
          % ("mode", "d from t_LOW", "d from rate", "d required", "SCL rate"))
    for mname in sorted(tc, key=lambda m: tc[m]["t_LOW"]):
        if mname not in results:
            continue
        d_tlow = results[mname][0]
        # 2d + L_SYNC >= F_CLK / f_max
        need_cycles = -(-F_CLK // MODE_MAX_HZ[mname])
        d_rate = -(-(need_cycles - L_SYNC) // 2)
        d_req = max(d_tlow, d_rate)
        print("    %-13s %-13d %-13d %-13d %.0f kHz"
              % (mname, d_tlow, d_rate, d_req, scl_hz(d_req) / 1000.0))
    print("    ⚠ THE RATE COLUMN IS NOT A COMPLIANCE REQUIREMENT, it is what")
    print("      the mode's NAME means. A clock slower than the ceiling is a")
    print("      legal clock of that mode; one faster is a different mode and")
    print("      must meet that mode's minima instead.")

    # -----------------------------------------------------------------
    # 3. must-fire: the inherited row must give a DIFFERENT answer
    # -----------------------------------------------------------------
    print()
    print("  --- 3. must-fire: inheriting D_tol = 15 must change the verdict ---")
    print("    ⛔ If the two-action row's tolerance happened to give the same")
    print("    feasible d, this whole re-derivation would be decoration. It")
    print("    does not, and here is the difference:")
    old = [l for l in BASE if l.name.startswith(I2C_NAME_PREFIX)][0]
    fired = 0
    for mname in sorted(tc, key=lambda m: tc[m]["t_LOW"]):
        if mname not in results:
            continue
        tl = tc[mname]["t_LOW"]
        d_derived = results[mname][0]
        # the inherited reading: D_tol fixed at 15 regardless of d
        d_inherited = None
        for d in range(tl + 1, tl + 400):
            ls = [BLane(l.name, l.T, l.C, D_tol=l.D_tol, n=l.n, t=l.t, J=l.J)
                  for l in BASE if not l.name.startswith(I2C_NAME_PREFIX)]
            ls.append(BLane("I2C inherited", T=d, C=C_SHIPPED,
                            D_tol=old.D_tol, J=old.J))
            k = len(ls) - 1
            prim, _err = pyrta_bound.bound(src, ls, k)
            if prim is not None and ls[k].margin(prim) >= 0:
                d_inherited = d
                break
        differs = (d_inherited != d_derived)
        if differs:
            fired += 1
        print("      %-13s derived d* = %-6s inherited d* = %-6s %s"
              % (mname, d_derived, d_inherited,
                 "DIFFERS" if differs else "*** SAME -- no consequence"))
    if fired == 0:
        print("    *** MUST-FIRE FAILED: the inherited tolerance gives the same")
        print("        answer at every mode, so nothing here depends on the")
        print("        re-derivation.")
        rc = 1
    else:
        print("    ⇒ differs at %d mode(s). The inherited row's fixed D_tol = %d"
              % (fired, old.D_tol))
        print("      does not scale with `d`, so it understates the tolerance a")
        print("      slow clock actually has and overstates a fast one's.")

    # -----------------------------------------------------------------
    # 4. the full set at the shipped mode, both bounds
    # -----------------------------------------------------------------
    print()
    print("  --- 4. the whole lane set with the clocked row, both bounds ---")
    pick = "Fm+ 1 MHz" if "Fm+ 1 MHz" in results else next(iter(results), None)
    if pick is None:
        print("    *** FAIL no mode produced a feasible set")
        rc = 1
    else:
        d = results[pick][0]
        ls = build(d, tc[pick]["t_LOW"])
        # ⛔ THE VARIANT IS DECLARED, because analysing one without saying so
        # is itself a finding in this project. The set is the shipped five with
        # the TWO-ACTION I2C row replaced by the clocked row -- a different
        # scheme on the same wire, not a tweak to the shipped table.
        lane_digest.announce(
            "gate_clocked_lane_a2.py", ls,
            variant=("the shipped set with the two-action I2C row (T=45, "
                     "D_tol=15) REPLACED by the clocked row (T=d, "
                     "D_tol=d-t_LOW(min)) -- see this file's header"))
        print("    at %s, d = %d" % (pick, d))
        print("    %-22s %-10s %-10s %-9s %s"
              % ("lane", "r (pyRTA)", "r (ours)", "margin", "ok?"))
        rows = quote(ls, src)
        for nm, p, o, mo, mp, err in rows:
            if p is None:
                print("    %-22s *** FAIL %s" % (nm, err))
                rc = 1
                continue
            print("    %-22s %-10d %-10d %-9d %s"
                  % (nm, p, o, mp, "ok" if mp >= 0 else "*** FAIL"))
            if mp < 0:
                rc = 1
        good = [(r[0], r[1], r[2]) for r in rows if r[1] is not None]
        if good and not pyrta_bound.check_direction(good):
            print("    *** FAIL pyRTA and our recurrence disagree in the")
            print("        unsafe direction on some lane")
            rc = 1

    # -----------------------------------------------------------------
    # 5. the SHIPPABLE d: the fixed point has no reserve
    # -----------------------------------------------------------------
    print()
    print("  --- 5. the fixed point is TIGHT; the shippable d is larger ---")
    print("    ⛔⛔ EVERY MARGIN IN §1 IS EXACTLY 0, AND THAT IS BY")
    print("    CONSTRUCTION, NOT BY LUCK: the search returns the FIRST feasible")
    print("    `d`, which is the one where `d - t_LOW(min)` only just reaches")
    print("    `r - C`. A zero-margin number is feasible and NOT shippable --")
    print("    this project holds a margin bar of %d cycles, and a lane with no"
          % MARGIN_BAR)
    print("    reserve fails the next correction that moves any r_i by one.")
    print()
    print("    %-13s %-9s %-9s %-10s %-11s %s"
          % ("mode", "d (feas)", "d (bar)", "D_tol", "SCL rate", "<= mode max?"))
    for mname in sorted(tc, key=lambda m: tc[m]["t_LOW"]):
        if mname not in results:
            continue
        tl = tc[mname]["t_LOW"]
        d_bar = None
        for d in range(results[mname][0], results[mname][0] + 400):
            ls = build(d, tl)
            k = len(ls) - 1
            prim, _e = pyrta_bound.bound(src, ls, k)
            if prim is None:
                continue
            if ls[k].margin(prim) >= MARGIN_BAR and                min(l.margin(response_time_b(l, ls)["r"]) for l in ls) >= 0:
                d_bar = d
                break
        if d_bar is None:
            print("    %-13s %-9d *** FAIL no d clears the margin bar"
                  % (mname, results[mname][0]))
            rc = 1
            continue
        need_cycles = -(-F_CLK // MODE_MAX_HZ[mname])
        d_rate = -(-(need_cycles - L_SYNC) // 2)
        d_ship = max(d_bar, d_rate)
        hz = scl_hz(d_ship)
        print("    %-13s %-9d %-9d %-10d %-11s %s"
              % (mname, results[mname][0], d_ship, d_ship - tl,
                 "%.0f kHz" % (hz / 1000.0),
                 "yes" if hz <= MODE_MAX_HZ[mname] else "NO"))
    print("    ⇒ THE SHIPPABLE COLUMN IS THE ANSWER TO THE RULING's QUESTION.")
    print("      It is `max(d clearing the margin bar, d meeting the rate")
    print("      ceiling)`, and it is what a clocked I2C program must declare.")
    print("    ⚠ NOT YET A SHIPPED NUMBER: it rests on `r_i` for a lane set in")
    print("      which the OTHER four rows are still the shipped ones. If the")
    print("      clocked scheme replaces more than the I2C lane, this is")
    print("      recomputed, not carried.")

    # -----------------------------------------------------------------
    # 6. A2 -- the bench's gap budget must still cover `r_i - C`
    # -----------------------------------------------------------------
    print()
    print("  --- 6. the bench's post-HIGH gap budget, checked against A2 ---")
    print("    ⛔⛔ THE CONSTANT LIVES IN THE BENCH AND IS CHECKED HERE. "
          "`clocked_conform.vh`")
    print("    bounds a post-HIGH gap at `d + L_SYNC + 1 + (r_i - C)`, and the")
    print("    `r_i - C` term is an A2 number that the RTL cannot know. Copying")
    print("    it into this gate as well would be the two-copies defect that")
    print("    has already cost this project a published column, so the bench")
    print("    HOLDS it and this gate PARSES and adjudicates it.")
    vh = os.path.join(os.path.dirname(os.path.dirname(HERE)), "test",
                      "clocked_conform.vh")
    slack = None
    try:
        import re as _re
        txt = io.open(vh, encoding="utf-8").read()
        m = _re.search(r"localparam\s+integer\s+CK_GAP_SLACK\s*=\s*(\d+)",
                       txt)
        if m:
            slack = int(m.group(1))
    except Exception as exc:                            # noqa: BLE001
        print("    *** FAIL could not read %s: %s" % (vh, exc))
        rc = 1
    if slack is None:
        print("    *** FAIL no `CK_GAP_SLACK` localparam found in")
        print("        test/clocked_conform.vh -- the bound this gate is")
        print("        supposed to adjudicate is not there to read.")
        rc = 1
    else:
        pick2 = "Fm+ 1 MHz" if "Fm+ 1 MHz" in results else next(iter(results),
                                                                None)
        if pick2 is None:
            print("    *** FAIL no feasible mode to take r_i from")
            rc = 1
        else:
            d2 = results[pick2][0]
            ls2 = build(d2, tc[pick2]["t_LOW"])
            # ⛔⛔ THE CLOCKED LANE'S OWN `r - C`, NOT THE MAX OVER THE SET,
            # and the first version of this check took the max and failed at 13.
            # The quantity being bounded is how late THE CLOCKED LANE's own
            # post-HIGH dispatch can be served; UART-tx's 13 bounds UART-tx.
            # ⭐ THE MEASUREMENT SETTLES IT: the observed gap margin topped out
            # at exactly 8 = L_SYNC + 1 + 4, and 4 is this lane's r - C. A term
            # taken from another lane would have been loose by 9 cycles and the
            # bound would have stopped catching anything.
            ck_lane = ls2[-1]
            worst_rc = response_time_b(ck_lane, ls2)["r"] - ck_lane.C
            need = L_SYNC + 1 + worst_rc
            ok = slack >= need
            if not ok:
                rc = 1
            print()
            print("      %-26s %d" % ("CK_GAP_SLACK (bench)", slack))
            print("      %-26s %d" % ("L_SYNC", L_SYNC))
            print("      %-26s %d" % ("+ 1 (the dispatch)", 1))
            print("      %-26s %d  (at %s)"
                  % ("the clocked lane's r_i - C", worst_rc, pick2))
            print("      %-26s %d   %s"
                  % ("=> required", need,
                     "ok -- the bench budget covers it" if ok
                     else "*** FAIL the bench budget is TOO SMALL"))
            if ok and slack == need:
                print("      ⚠ EXACTLY EQUAL, so there is no slack above the")
                print("        derivation. A red in the bench's A2 arm is a")
                print("        request to RE-DERIVE this, never a licence to")
                print("        raise the constant until it passes.")

    print()
    print("=" * 78)
    print("  GATE clocked-lane-a2: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    * D_tol = d - t_LOW(min), derived from the clocked geometry")
    print("    * the feasible d is a FIXED POINT, searched not assumed")
    print("    * pyRTA is the PRIMARY bound; RED without it")
    print("    * must-fire: the inherited D_tol = 15 gives a different answer")
    print("    * the stream is periodic at d -- F1 removed the L_sync burst")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
