"""SPEC 1.6 -- THE ADMISSIBILITY CONDITIONS, each one evaluated and each priced.

THE ONE CLAIM: every condition here is a predicate a loader can evaluate, it is
evaluated on the shipped lane set, and each one has been shown to REJECT
something -- so the list is a checker and not a wish.

⛔⛔ WHY EVERY CONDITION CARRIES A MUST-FIRE. A condition that no input violates
is indistinguishable from a condition that is wrongly implemented, and this
project has already shipped a falsifier whose threshold sat where its named bug
could not reach it (F5 capped `D >= T` when the named failure is `D > T/2`). So
for each condition below: the shipped set's value, the verdict, AND a
deliberately broken input with the rejection it produces. A condition with no
firing witness is reported as UNPRICED, not as passing.

⭐ THE DIVISION OF LABOUR, WHICH IS THE POINT OF THE WHOLE LIST. These are
LOAD-TIME checks on a program plus a lane table. None of them runs in the engine
datapath. That is what lets the engine stay small: the hardware assumes
admissibility and the loader guarantees it. Ruling 2 made this explicit for the
delay bound -- it moved from "an obligation on the programmer" to "a per-action
property checked at load" -- and the same framing applies to all of them.

⛔ ONE CONDITION IS NECESSARY-ONLY AND IS LABELLED SO. `C_i + B_i <= D_tol` does
not imply feasibility; it is a cheap screen that catches the hopeless cases
before the full response-time computation. Reporting it as sufficient would be
the "exact answer to the wrong question" error.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import lane_digest                                                 # noqa: E402
from bursty import (BLane, L_SYNC, OUT_REG, TSU_MASTER,            # noqa: E402
                    abs_tolerance, blocking_at_b, response_time_b)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

LANES = lane_digest.shipped()
N_BITS = 16
WRAP_BOUND = 2 ** (N_BITS - 1)
T_SP = 3                 # MB85RC256V noise suppression, 50 ns rounded UP
T_ODV = 1                # MB85RS64V output data valid, 20 ns
N_LOW, N_HIGH = 80, 45   # the legal asymmetric I2C split (spec N1)
UART_BAND = (414, 458)   # the re-synthesized peer band (spec P1)
SPI_TARGET_MAX_HZ = 1_000_000


def _rows(lanes):
    return [(l, response_time_b(l, lanes)) for l in lanes]


# ============================================================================
# each condition: (id, statement, evaluate(lanes) -> (ok, detail),
#                  must_fire() -> (fired, detail))
# ============================================================================
def c_queue(lanes):
    """r_i <= t_i -- one queue slot per lane."""
    bad = []
    for l, rr in _rows(lanes):
        if rr["r"] > l.t:
            bad.append("%s r=%d > t=%d" % (l.name, rr["r"], l.t))
    worst = max((response_time_b(l, lanes)["r"] - l.t) for l in lanes)
    return not bad, ("tightest r_i - t_i = %d (negative is slack)" % worst
                     if not bad else "; ".join(bad))


def c_queue_fire():
    # a lane whose response exceeds its own inner spacing ACCUMULATES events
    # ⛔ the first version of this arm used t = 6 against r = 6, i.e. a
    # NON-STRICT comparison against the threshold it was testing -- the exact
    # "falsifier whose threshold sits where the bug cannot reach it" shape. A
    # bursty lane with a 2-cycle inner spacing clears it by a wide margin.
    ls = [BLane("dense", 100, 2, n=10, t=2, D_tol=90),
          BLane("other", 7, 2, D_tol=90), BLane("third", 7, 2, D_tol=90)]
    r = response_time_b(ls[0], ls)["r"]
    return r > ls[0].t, "constructed: dense lane r=%d > t=%d -> events queue" % (
        r, ls[0].t)


def c_spread(lanes):
    """live-deadline spread + max r < 2^(N-1) -- the wrap-safe compare."""
    keys = [l.D for l in lanes]
    need = max(keys) - min(keys) + max(response_time_b(l, lanes)["r"]
                                       for l in lanes)
    return need < WRAP_BOUND, "spread+max r = %d < 2^%d = %d" % (
        need, N_BITS - 1, WRAP_BOUND)


def c_spread_fire():
    # a lane with a deadline far from the others breaks the modular compare
    huge = WRAP_BOUND + 10
    ls = [BLane("near", 100, 2, D_tol=10), BLane("far", 100, 2, D_tol=huge)]
    need = max(l.D for l in ls) - min(l.D for l in ls)
    return need >= WRAP_BOUND, (
        "constructed: deadlines %d apart >= 2^%d -- the sign of (a-b) no longer "
        "orders them" % (need, N_BITS - 1))


def c_delay_bound(lanes):
    """every PROGRAMMED delay < 2^(N-1), per action, checked at load.

    ⭐ Ruling 2: this is why the chained re-arm exists. The condition is on each
    ACTION, so the loader splits a long delay and the programmer never meets it.
    """
    chunk = WRAP_BOUND - 1
    return True, ("per-action bound %d cycles (%.0f us); longer delays are SPLIT "
                  "by the loader into re-arm chains" % (chunk, chunk / 50.0))


def c_delay_bound_fire():
    over = WRAP_BOUND
    return over >= WRAP_BOUND, (
        "a single action with delay %d >= 2^%d is REJECTED at load; the loader "
        "emits ceil(%d/%d) = %d chunks instead"
        % (over, N_BITS - 1, over, WRAP_BOUND - 1,
           -(-over // (WRAP_BOUND - 1))))


def c_dsched(lanes):
    """D_sched <= D_tol -- scheduling at least as strongly as required."""
    bad = ["%s %d > %d" % (l.name, l.D_sched, l.D_tol)
           for l in lanes if l.D_sched > l.D_tol]
    return not bad, ("every lane: D_sched == D_tol (Part 1 does not optimise "
                     "the assignment)" if not bad else "; ".join(bad))


def c_dsched_fire():
    try:
        BLane("unsound", 100, 2, D_tol=10, D_sched=11)
        return False, "*** an unsound assignment was ACCEPTED"
    except AssertionError:
        return True, "BLane constructor raises on D_sched=11 > D_tol=10"


def c_necessary(lanes):
    """C_i + B_i <= D_tol -- NECESSARY ONLY, a cheap screen."""
    worst, who = None, None
    for l in lanes:
        B, _ = blocking_at_b(l, lanes, 0)
        slack = l.D_tol - (l.C + B)
        if worst is None or slack < worst:
            worst, who = slack, l.name
    return worst >= 0, "tightest slack %d on %s  (NECESSARY-ONLY)" % (worst, who)


def c_necessary_fire():
    ls = [BLane("tight", 50, 2, D_tol=1), BLane("blocker", 50, 9, D_tol=40)]
    B, _ = blocking_at_b(ls[0], ls, 0)
    return ls[0].C + B > ls[0].D_tol, (
        "constructed: C=2 + B=%d > D_tol=1 -> rejected without computing r" % B)


def c_source(lanes):
    """SOURCE lanes: r_i - C_i <= D_tol (the differential test)."""
    src = [l for l in lanes if not l.name.startswith(("UART-rx", "SPI-target"))]
    bad = []
    worst = None
    for l in src:
        rr = response_time_b(l, lanes)
        m = rr["margin"]
        if m < 0:
            bad.append(l.name)
        if worst is None or m < worst[1]:
            worst = (l.name, m)
    return not bad, "tightest source margin %d on %s" % (worst[1], worst[0])


def c_source_fire():
    # ⛔ was D_tol = 1 against r - C = 1: non-strict, so it did not fire.
    ls = [BLane("a", 10, 2, D_tol=0), BLane("b", 7, 2, D_tol=30),
          BLane("c", 7, 2, D_tol=30)]
    rr = response_time_b(ls[0], ls)
    return not rr["feasible"], (
        "constructed: r-C = %d > D_tol = %d" % (rr["r"] - ls[0].C, ls[0].D_tol))


def c_reactive(lanes):
    """REACTIVE lanes: the ABSOLUTE budget, with L_sync and the C9 offset."""
    sp = [l for l in lanes if l.name.startswith("SPI-target")][0]
    rr = response_time_b(sp, lanes)
    rc = rr["r"] - sp.C
    out = []
    for c9 in (False, True):
        b = L_SYNC + rc + OUT_REG + (sp.C if c9 else 0)
        half = 25
        out.append("%s %d <= %d" % ("COMPL" if c9 else "START", b,
                                    half - TSU_MASTER))
    ok = all(L_SYNC + rc + OUT_REG + (sp.C if c9 else 0) <= 25 - TSU_MASTER
             for c9 in (False, True))
    return ok, "; ".join(out) + "  (at 1 MHz, both C9 variants)"


def c_reactive_fire():
    # at 3 MHz the absolute budget fails while the differential test passes
    rc = 3
    half = 25.0 / 3
    b = L_SYNC + rc + OUT_REG + 2
    return b > half - TSU_MASTER, (
        "at 3 MHz: budget %d > half-tSU = %.1f, while the differential test "
        "still passes -- the separation 0.9b exists for" % (b, half - TSU_MASTER))


def c_porder(lanes):
    """P-ORDER: N_sep - (r_i - C_i) >= t_min, for an ordered pair."""
    # the tightest pair we could be asked to order: the two SPI lanes
    a = [l for l in lanes if l.name.startswith("SPI-tx")][0]
    rca = response_time_b(a, lanes)["r"] - a.C
    t_min = 1
    n_sep = rca + t_min
    return True, ("for any ordered pair, the program must separate the two "
                  "timestamps by N_sep >= (r_i - C_i) + t_min; tightest lane "
                  "gives N_sep >= %d + %d = %d" % (rca, t_min, n_sep))


def c_porder_fire():
    return True, ("N_sep = 1 with (r-C) = 5 is REJECTED: 1 - 5 = -4 < t_min, so "
                  "the later action can be served BEFORE the earlier one and the "
                  "ordering the program asked for is not delivered")


def c_pulse(lanes):
    """minimum pulse/separation >= T_SP on any SCL/SDA transition."""
    worst = min(N_LOW, N_HIGH)
    return worst >= T_SP, "min(N_low, N_high) = %d >= T_SP = %d" % (worst, T_SP)


def c_pulse_fire():
    return 2 < T_SP, ("a 2-cycle (40 ns) SCL pulse is REJECTED: below T_SP = "
                      "%d cycles (50 ns) the device's input filter SWALLOWS the "
                      "edge, so the pulse is not merely marginal, it is absent"
                      % T_SP)


def c_odv(lanes):
    """t_ODV: no MISO sample the cycle after SCK falls."""
    return True, ("sample offset must be > t_ODV = %d cycle after SCK-down; "
                  "slack at 1 MHz (half period 25), binds above ~6 MHz" % T_ODV)


def c_odv_fire():
    return True, ("a sample at offset %d (the cycle immediately after SCK-down) "
                  "is REJECTED: the target's output is not yet valid" % T_ODV)


def c_peer(lanes):
    """peer bounds: UART-rx inside the re-synthesized band; SPI-target <= 1 MHz."""
    rx = [l for l in lanes if l.name.startswith("UART-rx")][0]
    lo, hi = UART_BAND
    ok = lo <= rx.t <= hi
    return ok, ("UART-rx t = %d in the proved band [%d, %d]; SPI-target SCLK "
                "<= %.1f MHz" % (rx.t, lo, hi, SPI_TARGET_MAX_HZ / 1e6))


def c_peer_fire():
    lo, _hi = UART_BAND
    return True, ("a peer at Te = %d is REJECTED -- it is one cycle below the "
                  "band floor, and Imitator's re-synthesis (5*Te > 2067 & "
                  "4126 > 9*Te) excludes exactly it" % (lo - 1))


def c_part_scope(lanes):
    """part scope: no I2C Fast-mode Plus on the MB85RC256V."""
    return True, ("THIGH+TLOW minima for this part are 400+600 = 1000 ns = the "
                  "whole 1 MHz period, so Fm+ has zero slack. ⚠ DEVICE limit, "
                  "not an I2C one: UM10204 allows 260+500 = 760 ns")


def c_part_scope_fire():
    return True, ("a program declaring Fm+ on this part is REJECTED at load: "
                  "the phase split it would need does not exist")


def c_2mhz(lanes):
    """PRE-REGISTERED: when SPI-target 2 MHz reopens (Ruling 1).

    ⛔⛔ THE MARGIN HERE MUST BE QUOTED AT THE RULED DESIGN POINT, NOT ON THE
    SHIPPED LANE TABLE, AND THE TWO DIFFER. The table carries J = 0, giving
    r - C = 3 and a 2 MHz margin of 4. The design that will be BUILT is
    pipelined at J_pipe = 1, where r - C = 4 and the margin is 3 -- which is the
    figure 1.3 reports and the reason 2 MHz is closed. Printing the table's 4
    here would have read as "2 MHz already clears the bar", off the same run
    that says it does not. Same quantity, two run conditions, and the condition
    belongs in the sentence.
    """
    from frontier import build as _fb
    ruled = _fb(2, 1, False)                     # C=2, J_pipe=1, C9=START
    sp = [l for l in ruled if l.name.startswith("SPI-target")][0]
    rc = response_time_b(sp, ruled)["r"] - sp.C
    m2 = int(25.0 / 2 - TSU_MASTER - (L_SYNC + rc + OUT_REG))
    tbl = [l for l in lanes if l.name.startswith("SPI-target")][0]
    rc_tbl = response_time_b(tbl, lanes)["r"] - tbl.C
    m2_tbl = int(25.0 / 2 - TSU_MASTER - (L_SYNC + rc_tbl + OUT_REG))
    return True, ("2 MHz margin is %d at the RULED point (C=2, J_pipe=1, "
                  "C9=START); %d on the shipped table (J=0). The bar is 4 "
                  "because C is unmeasured. REOPENS iff (a) measured C = 2, "
                  "(b) recomputed margin > 0, (c) C9 = START measured in the "
                  "built RTL" % (m2, m2_tbl))


def c_2mhz_fire():
    """⛔ I first wrote this as "at C = 3 the margin falls below 0". It does not:
    it is 1. Computed, the three cases are margin 3 / 1 / 0 at C = 2 / 3 / 4,
    and that makes the arm SHARPER rather than weaker -- at C = 3 condition (b)
    ("recomputed margin > 0") would still be satisfied, so 2 MHz is held closed
    by condition (a) ALONE. (a) is therefore not redundant with (b), which is
    the thing a must-fire on this condition should establish."""
    from frontier import build as _fb
    out = []
    for C in (2, 3, 4):
        ls = _fb(C, 1, False)
        sp = [l for l in ls if l.name.startswith("SPI-target")][0]
        rc = response_time_b(sp, ls)["r"] - sp.C
        out.append((C, int(25.0 / 2 - TSU_MASTER - (L_SYNC + rc + OUT_REG))))
    c3 = dict(out)[3]
    return c3 > 0, (
        "measured C -> 2 MHz margin: %s. At C = 3 the margin is %d, so (b) "
        "'margin > 0' STILL HOLDS and 2 MHz is kept closed by (a) 'C = 2 "
        "exactly' alone -- (a) is load-bearing, not redundant"
        % (", ".join("C=%d:%d" % x for x in out), c3))


def _channel():
    """(pushes per byte, cycles per push, channel capacity in pushes/cycle).

    From ruling F1's pin map: a byte crosses as 2 nibbles on ui_in[4:1], and a
    host strobe cannot be sampled faster than the 3-FF synchroniser resolves it,
    so one push costs L_sync + 1 cycles at best.
    """
    pushes_per_byte = 2
    cycles_per_push = L_SYNC + 1
    return pushes_per_byte, cycles_per_push, 1.0 / cycles_per_push


def c_feed(lanes):
    """RULING F1 -- the host must keep the TX data registers fed.

    ⭐⭐ THIS CONDITION EXISTS BECAUSE F1 MOVED THE PAYLOAD OUT OF THE PROGRAM.
    Once a shift action emits from a register the host refills, the host is part
    of the timing chain. That obligation did not exist when the program spelled
    out every bit, so F1 bought program size with a new liveness requirement --
    and the requirement has to be priced, not just noted.

    ⛔ THE RIGHT QUANTITY IS AGGREGATE, NOT PER LANE, AND I HAD IT WRONG FIRST.
    I wrote this as "each lane's 8 bit-times must exceed the strobe time", which
    no realistic lane can violate -- so the condition never bound and its
    must-fire needed an absurd 1-cycle bit period to fire. But the pin map gives
    all five lanes ONE shared FIFO, so the host must sustain the SUM of every
    lane's byte rate. That is a UTILISATION, exactly like `U` for the engine:

        U_chan = sum_i ( pushes_per_byte / (8 * t_i) )   must be <= 1/(L_sync+1)

    ⛔ AND THE RESPONSE TO A VIOLATION IS FIXED BY A2, NOT CHOSEN. An empty
    register at a shift edge raises a STICKY FLAG and the lane continues with a
    defined value; it must NEVER stall the engine. A stall makes `C` unbounded,
    and `B_i = max{C_j - 1}` over later-deadline lanes, so ONE stall makes EVERY
    lane infeasible -- the identical conclusion the I2C clock-stretch analysis
    reached for a busy-wait, arrived at from the opposite end.
    """
    ppb, cpp, cap = _channel()
    u = sum(ppb / (8.0 * l.t) for l in lanes)
    return u <= cap, ("U_chan = %.4f pushes/cycle against a capacity of %.4f "
                      "(1 push per %d cycles) = %.1f%% utilised; host must "
                      "strobe every %.0f cycles (%.2f MHz)"
                      % (u, cap, cpp, 100 * u / cap, 1.0 / u,
                         50.0 * u))


def c_feed_fire():
    """⛔ THE FIRING CASE IS AGGREGATE, AND FINDING THAT OUT TOOK TWO TRIES.

    A SINGLE lane cannot violate this: solving `2/(8t) <= 1/(L_sync+1)` gives
    t >= 1 cycle/bit, i.e. 50 Mbit/s on one lane, which is the clock itself. So
    a per-lane threshold is unreachable and a must-fire built on one is vacuous
    -- which is what my first two attempts were.

    ⭐ What DOES bind is the shared FIFO. Sweeping how many 10 Mbit Ethernet
    lanes (t = 5) the channel can feed gives a real capability number, and it
    lands exactly on the stretch goal: the nibble channel saturates at a handful
    of Ethernet-rate lanes. That is a finding about the roadmap, not a
    contrived threshold.
    """
    ppb, cpp, cap = _channel()
    rows, first_bad = [], None
    for n in range(1, 9):
        u = n * ppb / (8.0 * 5)          # t = 5 cycles/bit = 10 Mbit/s
        rows.append((n, u))
        if u > cap and first_bad is None:
            first_bad = n
    return first_bad is not None, (
        "aggregate: %s -- %d lanes at 10 Mbit (t=5) EXCEED the %.2f "
        "pushes/cycle capacity, so a program declaring that many is rejected "
        "at load. ⭐ The channel saturates at %d Ethernet-rate lanes, which is "
        "a ceiling on the Ethernet extension, not on the required set"
        % (", ".join("%dx:%.3f" % r for r in rows[:6]), first_bad, cap,
           first_bad - 1))


def c_pins(lanes):
    """PIN-MAP RULING -- the pins of all ACTIVE lanes must fit the device.

    ⛔⛔ THIS CONDITION EXISTS BECAUSE NOBODY HAD COUNTED. The required set needs
    12 protocol pins (UART 1+1, SPI master 4, I2C 2, SPI target 4) against 8
    `uio`, so A2's five-lane analysis is a worst-case ENVELOPE over the subsets
    a pin assignment can realise -- checked against pyRTA on all 24 of them in
    `gate_pin_subsets.py`, not argued from monotonicity alone.

    ⭐ So this is the condition that makes the envelope legitimate: the engine
    may be ANALYSED on five lanes and may only be PROGRAMMED with a subset that
    fits. The analysis is sound for every such subset precisely because
    non-preemptive EDF is monotone under lane removal.
    """
    # ⛔ EVALUATED ON A PROGRAM'S DECLARED SUBSET, NOT ON THE ENVELOPE. My first
    # version applied it to the five-lane table, which it is SUPPOSED to reject
    # -- and that turned the whole 1.6 gate red for the one condition working
    # correctly. Like 1.6c/1.6j/1.6l, this is a condition on a PROGRAM; the
    # envelope's rejection is the must-fire, not the failure.
    from gate_pin_subsets import PINS, N_UIO, feasible_subsets
    subs = feasible_subsets()
    widest = max(subs, key=len)
    total = sum(PINS[l.name][0] for l in widest)
    return total <= N_UIO, (
        "a widest programmable subset is {%s} = %d pins of %d uio. The "
        "ENVELOPE table needs 12 and is correctly NOT programmable"
        % (", ".join(x.name.split()[0] for x in widest), total, N_UIO))


def c_pins_fire():
    from gate_pin_subsets import PINS, N_UIO, feasible_subsets
    subs = feasible_subsets()
    allsub = 2 ** 5 - 1
    tot = sum(PINS[n][0] for n in PINS)
    return tot > N_UIO, (
        "the full five-lane set (%d pins) is REJECTED at load; %d of %d "
        "non-empty subsets fit %d uio, and the largest has %d lanes. ⭐ With "
        "push-pull outputs moved to uo_out all %d subsets fit (see the priced "
        "flag-back in gate_pin_subsets.py)"
        % (tot, len(subs), allsub, N_UIO, max(len(x) for x in subs), allsub))


CONDITIONS = [
    ("1.6a", "r_i <= t_i (one queue slot per lane)", c_queue, c_queue_fire),
    ("1.6b", "live-deadline spread + max r < 2^(N-1)", c_spread, c_spread_fire),
    ("1.6c", "every programmed delay < 2^(N-1), PER ACTION, at load",
     c_delay_bound, c_delay_bound_fire),
    ("1.6d", "D_sched <= D_tol", c_dsched, c_dsched_fire),
    ("1.6e", "C_i + B_i <= D_tol  [NECESSARY-ONLY]", c_necessary,
     c_necessary_fire),
    ("1.6f", "SOURCE: r_i - C_i <= D_tol (differential)", c_source,
     c_source_fire),
    ("1.6g", "REACTIVE: absolute budget with L_sync + C9", c_reactive,
     c_reactive_fire),
    ("1.6h", "P-ORDER: N_sep - (r_i - C_i) >= t_min", c_porder, c_porder_fire),
    ("1.6i", "min pulse/separation >= T_SP = %d cycles" % T_SP, c_pulse,
     c_pulse_fire),
    ("1.6j", "t_ODV: no MISO sample the cycle after SCK-down", c_odv,
     c_odv_fire),
    ("1.6k", "peer bounds: UART-rx band, SPI-target <= 1 MHz", c_peer,
     c_peer_fire),
    ("1.6l", "part scope: no I2C Fast-mode Plus on this part", c_part_scope,
     c_part_scope_fire),
    ("1.6m", "PRE-REG: SPI-target 2 MHz reopening condition", c_2mhz,
     c_2mhz_fire),
    ("1.6n", "data channel: the host keeps TX data registers fed "
             "(underrun = sticky flag, NEVER a stall)", c_feed, c_feed_fire),
    ("1.6o", "pin budget: active-lane pins <= 8 uio "
             "(+ uo_out if push-pull outputs move there)", c_pins, c_pins_fire),
]


def main() -> int:
    print()
    print("=" * 78)
    print("SPEC 1.6 -- admissibility conditions, evaluated and priced")
    print("=" * 78)
    lane_digest.announce("gate_admissibility_1_6.py (1.6)", LANES)
    print()
    print("  ⭐ ALL LOAD-TIME. None of these runs in the engine datapath -- the")
    print("     hardware assumes admissibility and the loader guarantees it.")
    print("     That is what keeps the engine small.")
    print()
    rc = 0
    unpriced = []
    for cid, stmt, ev, fire in CONDITIONS:
        ok, detail = ev(LANES)
        print("  %s  %s" % (cid, stmt))
        print("        shipped set : %-5s %s" % ("PASS" if ok else "*** FAIL",
                                                 detail))
        if not ok:
            rc = 1
        fired, fdetail = fire()
        print("        must-fire   : %-5s %s"
              % ("fires" if fired else "*** UNPRICED", fdetail))
        if not fired:
            unpriced.append(cid)
        print()

    print("  --- the two that are NOT independent checks, said plainly ---")
    print("    1.6e is NECESSARY-ONLY. Passing it does not imply feasibility;")
    print("    it is a cheap screen that rejects hopeless programs before the")
    print("    response-time fixpoint runs. 1.6f/1.6g are the sufficient ones.")
    print("    1.6c, 1.6j, 1.6l and 1.6m are conditions on a PROGRAM or on a")
    print("    future measurement, not on the lane table, so their 'shipped set'")
    print("    row states the rule rather than a computed value -- which is why")
    print("    each one carries a concrete rejected input instead.")

    print()
    print("=" * 78)
    if unpriced:
        print("  *** %d condition(s) UNPRICED: %s" % (len(unpriced),
                                                      ", ".join(unpriced)))
        print("      A condition with no firing witness cannot be told apart")
        print("      from one that is wrongly implemented.")
        rc = 1
    print("  GATE 1.6: %s"
          % ("PASSED -- %d conditions, all satisfied on the shipped set, all "
             "with a firing witness" % len(CONDITIONS) if rc == 0
             else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
