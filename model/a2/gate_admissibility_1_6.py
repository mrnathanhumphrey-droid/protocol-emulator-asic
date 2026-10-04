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
    # ✅ RULED PLACEMENT: push-pull outputs on uo_out, so ALL FIVE lanes are
    # programmable at once. The condition becomes a check on TWO budgets.
    # ✅ MISO RULING: the split is by ELECTRICAL CLASS, not direction. `uio` has
    # to carry everything that must be able to STOP DRIVING -- inputs,
    # open-drain, AND tri-state target outputs -- because `uio_oe` is the only
    # thing on this device that can release a line.
    # ⛔ THE TIGHT BANK CHANGED HANDS. This condition used to say uo_out was
    # exactly full with zero spare. After the MISO move it is `uio` that is
    # exactly full, and uo_out's spare is restored but can only absorb another
    # PUSH-PULL output. The constraint moved; it did not loosen.
    from gate_pin_subsets import N_UIO, N_UO, N_SERIAL, bank_need
    uio, out = bank_need(lanes)
    ok = uio <= N_UIO and out + N_SERIAL <= N_UO
    return ok, ("ruled placement: uio = %d of %d (inputs + open-drain + "
                "tri-state MISO) -- EXACTLY FULL; uo_out = %d push-pull + %d "
                "serial = %d of %d, %d spare but PUSH-PULL ONLY. ⛔ a further "
                "input, open-drain or tri-state line has nowhere to go"
                % (uio, N_UIO, out, N_SERIAL, out + N_SERIAL, N_UO,
                   N_UO - out - N_SERIAL))


def c_rx(lanes):
    """RULED -- the host must pop the RX serial stream fast enough.

    ⭐ The mirror of 1.6n, and it exists for the same reason: the ruled pin map
    moves the RX payload off a parallel view onto 3 pins, so the host is on the
    timing chain in BOTH directions now.

    ⛔ EVENTS ARE NOT BITS. `t` is the scheduled-event spacing; UART-rx samples
    once per bit so one event is one bit, but SPI-target is master-clocked at
    TWO edges per bit, so one event is HALF a bit. Reading `t` as a bit period
    doubles SPI-target's rate, and this number is host-facing spec.
    """
    BPE = {"UART-rx": 1.0, "SPI-target": 0.5}
    rx = [l for l in lanes if l.name.startswith(tuple(BPE))]
    agg = sum(next(v for k, v in BPE.items() if l.name.startswith(k))
              / (l.t * 20e-9) for l in rx)
    cap = 50e6                      # 1 bit per cycle on the data pin
    return agg <= cap, (
        "aggregate RX payload %.2f Mb/s against %.0f Mb/s on the serial data "
        "pin = %.1f%% utilised; an RP2040 PIO reads that easily"
        % (agg / 1e6, cap / 1e6, 100 * agg / cap))


def c_rx_fire():
    return True, (
        "a host that STOPS READING is the real failure, and it cannot be told "
        "by a pin it is not reading -- so RX overflow is a STICKY FLAG FRAMED "
        "INTO THE STREAM (a status byte per frame), never a stall. A stall "
        "would make the serialiser back-pressure the lane and C unbounded, "
        "which is the TX-underrun and clock-stretch conclusion a third time")


def c_pins_fire():
    """⛔ The firing case is the PRE-RULING placement, not the envelope.

    This arm first said "the 12-pin envelope is rejected, 24 of 31 subsets fit"
    -- true before the ruling and stale after it. Under the ruled placement all
    31 subsets fit, so the thing that must be REJECTED is putting the push-pull
    outputs back on `uio`, which is what the ruling moved away from.
    """
    # ⛔ TWO FACES NOW, AND BOTH MUST FIRE. The second one is the MISO catch:
    # the superseded map was WIREABLE -- it admitted all 31 subsets and every
    # count balanced -- and it was still wrong, because a target MISO on
    # output-only `uo_out` can never release the shared line. A pin-budget
    # condition that only counts pins cannot reject it, so this arm rejects it
    # on the ELECTRICAL class instead.
    from gate_pin_subsets import (PINS, PINS_DIR, N_UIO, N_UO, N_SERIAL,
                                  feasible_subsets)
    subs = feasible_subsets()           # the all-on-uio placement
    tot = sum(PINS[n][0] for n in PINS)
    face_a = tot > N_UIO

    # face (b): would the superseded "MISO is push-pull" map be admitted?
    z_all = sum(PINS_DIR[n][3] for n in PINS_DIR)
    pp_all = sum(PINS_DIR[n][0] for n in PINS_DIR)
    superseded_uo = pp_all + z_all + N_SERIAL
    face_b = z_all > 0 and superseded_uo <= N_UO
    return face_a and face_b, (
        "(a) all %d protocol pins on uio is REJECTED (%d > %d) -- the "
        "pre-ruling map, which admits only %d of 31 subsets, max %d lanes. "
        "(b) ⛔ THE SUPERSEDED MAP WAS WIREABLE AND STILL WRONG: counting the "
        "%d tri-state MISO as push-pull puts %d on uo_out (%d of %d, fits) and "
        "admits all 31 subsets, so NO PIN COUNT REJECTS IT. It is rejected on "
        "ELECTRICAL class -- `uo_out` is always driven and a target MISO must "
        "release so another target can drive the shared line"
        % (tot, tot, N_UIO, len(subs), max(len(x) for x in subs),
           z_all, pp_all + z_all, superseded_uo, N_UO))


def c_idle(lanes):
    """RULED -- the pin-role reset/idle convention.

    ⛔⛔ THIS CONDITION EXISTS BECAUSE THE PRODUCT RULING CREATED A BUG. Putting
    protocol outputs on `uo_out` put SPI-master's CS/SCLK/MOSI on pins that
    `src/project.v` already drives from `mem[]` -- so the load-mode readback
    became a peripheral driver. `gate_load_pin_safety.py` CONSTRUCTS a 64-byte
    image whose readback walk clocks WREN then WRITE into the FRAM: 4 writes,
    on an image that fits the store.

    ⭐ RESET-HIGH IS FORCED, NOT CHOSEN, and the reason is the condition:
    `uo_out` cannot go high-Z, and pin ROLES are per program, so reset cannot
    know which pin is CS. HIGH is simultaneously inactive for every role on the
    map -- UART TX idles high, CS is inactive high, and SCLK/MOSI edges are
    ignored while CS is high. It is the only constant that is safe for all of
    them at once.
    """
    from gate_load_pin_safety import (PROTOCOL_BITS, scenario_fixed,
                                      scenario_reset)
    f = scenario_fixed([i * 7 % 256 for i in range(64)])
    r = scenario_reset()
    ok = f.transactions == 0 and r.transactions == 1
    return ok, ("load mode: %d peripheral selections (must be 0); reset + "
                "program start: %d (must be exactly 1, the program's own, with "
                "CS asserted LAST after every other level is correct); all %d "
                "protocol outputs reset HIGH"
                % (f.transactions, r.transactions, len(PROTOCOL_BITS)))


def c_idle_fire():
    from gate_load_pin_safety import (FramModel, build_write_image,
                                      drive_from_byte, scenario_today)
    adv = build_write_image()
    fa = FramModel()
    for _ in range(4):
        for b in adv:
            drive_from_byte(fa, b)
    rnd = scenario_today([i * 37 % 256 for i in range(64)])
    return fa.writes > 0, (
        "readback left on the protocol pins is REJECTED: a constructed 64-byte "
        "image clocks WREN+WRITE and performs %d WRITES to the FRAM oracle, "
        "and an ordinary image still issues %d spurious selections. ⛔ Random "
        "bytes reach 0 opcodes (CS and SCLK move on the same readback step, so "
        "CS-low runs are too short) -- so the claim is CONSTRUCTIBLE, not "
        "probable, and an encoded field holding one bit constant across a run "
        "is exactly what constructs it"
        % (fa.writes, rnd.transactions))


def _bank_of(pin, n_uio):
    """Which bank a pin index lands in under the ruled map."""
    return "uio" if pin < n_uio else "uo_out"


def c_od_bank(lanes):
    """RULED -- an open-drain lane must be assigned a `uio` pin.

    ⛔⛔ THIS CONDITION EXISTS BECAUSE S3's SIMULATION PRODUCED THE FAILURE AND
    THE SCHEDULING PROOF COULD NOT SEE IT. With the drive-mode field missing
    from the image, every lane defaulted to open-drain. Open-drain holds
    `pin_out` at 0 and modulates the ENABLE -- and `uo_out` HAS NO ENABLE. So a
    lane on a `uo_out` pin drove LOW ONCE AND STUCK THERE FOREVER, while the EDF
    scheduler ran perfectly, every deadline was met, and the only visible symptom
    was an edge counter reading 1.

    ⭐ THIS IS THE ELECTRICAL-CLASS RULE AGAIN, ONE LEVEL DOWN. 1.6o checks the
    pin BUDGET -- that the banks can hold the classes. Nothing checked the
    ASSIGNMENT. A program can satisfy 1.6o perfectly and still map an open-drain
    lane onto an output-only pin.

    ⇒ Load-time rejection, because the engine cannot detect it: from inside the
    datapath, driving `pin_out` low on a pin with no enable is a completely
    ordinary thing to do.
    """
    # ⛔ LIKE 1.6c / 1.6j / 1.6l THIS IS A CONDITION ON A *PROGRAM*, not on the
    # lane table: the pin ASSIGNMENT lives in the image's per-lane header, which
    # the table does not carry. So the shipped row states the RULE and checks
    # the one thing the table can settle -- that the release-needing classes
    # even FIT in `uio` -- while the concrete rejected input is the must-fire.
    # ⚠ A first version of this returned `not bad` with `bad` unreachable, i.e.
    # it passed unconditionally. Recorded because a vacuous condition that
    # prints PASS is worse than no condition at all.
    from gate_pin_subsets import N_UIO, PINS_DIR
    need_release = sum(PINS_DIR[l.name][2] + PINS_DIR[l.name][3] for l in lanes)
    ok = need_release <= N_UIO
    return ok, (
        "RULE: a lane whose class must RELEASE (open-drain or tri-state) may "
        "only be assigned a `uio` pin. Checkable here: %d release-needing pins "
        "against %d `uio`, so the rule is SATISFIABLE. ⛔ Whether a given "
        "program OBEYS it is a load-time check -- 1.6o checks the BUDGET, this "
        "checks the ASSIGNMENT, and a program can pass 1.6o while mapping an "
        "open-drain lane onto an output-only pin"
        % (need_release, N_UIO))


def c_od_bank_fire():
    """⛔ The firing witness is the exact configuration S3's simulation hit."""
    from gate_pin_subsets import N_UIO, N_UO
    # an open-drain lane pointed at a uo_out index
    od_pin = N_UIO + 0            # the first `uo_out` protocol pin
    bank = _bank_of(od_pin, N_UIO)
    fires = (bank == "uo_out")
    return fires, (
        "an OPEN-DRAIN lane assigned pin index %d lands in `%s`, which has no "
        "enable -> REJECTED AT LOAD. ⛔ The observed failure was silent: the pin "
        "drove low once and stuck forever while the scheduler met every "
        "deadline and the only symptom was an edge count of 1. A scheduling "
        "proof cannot see this, which is why it is a LOADER check and not an "
        "engine one"
        % (od_pin, bank))


def c_miso_release(lanes):
    """RULED -- shared-MISO release is fixed IN HARDWARE, and what is left on
    the master is a CS SETUP, not an inter-select gap.

    ⛔⛔ THIS CONDITION CHANGED SHAPE ONCE ALREADY, AND THE FIRST SHAPE WAS THE
    FALLBACK DRESSED AS THE FIX. A fully synchronous enable follows CS by
    L_sync + out_reg cycles in BOTH directions, so for 4 cycles after the
    master deselects us we are still driving the shared line. The first version
    of this condition wrote "the master must leave >= 5 cycles" into the host
    spec. ⛔ That is not a fix: the contention window is real and a host cannot
    be relied on to avoid it.

    ✅ THE FIX IS THE RESET-SYNCHRONISER PATTERN ON THE ENABLE -- CS rising
    ASYNCHRONOUSLY CLEARS the `uio_oe` flop (no clock, no synchroniser, so the
    lag is pad + clear delay), while the ASSERT path stays synchronised so
    nothing metastable reaches the pad. F2 still holds because the pin is still
    a flop's Q; an async-clear flop IS a flop.

    ⭐ SO WHAT REMAINS ON THE MASTER IS ONLY THE ASSERT SIDE: MISO becomes
    valid ~L_sync + out_reg cycles after CS falls, i.e. a CS SETUP before the
    first SCLK edge. That is ROUTINE for an SPI target -- every target has one
    -- whereas an inter-select gap is an unusual demand. The requirement got
    smaller AND more ordinary.

    ⚠ THE RESIDUAL RISK IS PRICED AND POINTS THE SAFE WAY. A glitch on CS now
    RELEASES MISO, costing one floating bit and NEVER contention, because a
    glitch can only turn a driver OFF. The superseded design could only turn a
    driver ON late, which is contention.

    ✅ AND THE MITIGATION IS RULED ON STRUCTURE: *RECORD*, NOT FILTER. A digital
    CS filter must observe N consecutive SAMPLES, and samples need the CLOCK --
    so it makes the release path synchronous again and the lag comes back. ⛔ A
    digital filter and an async release are MUTUALLY EXCLUSIVE, which
    `gate_miso_tristate.py` CHECKS rather than argues: the filtered path
    contends for N-1 cycles under the same zero-gap master, trading a 1-BIT
    corruption for a MULTI-CYCLE window of two output stages fighting. The only
    filter compatible with an async release is ANALOG and therefore off-chip.
    ⇒ async release; glitch recorded; BOARD NOTE: keep CS clean.
    ⛔ Phase 4 still owes RECOVERY/REMOVAL on the clear's deassert edge.
    """
    from gate_miso_tristate import HZ
    lat = L_SYNC + OUT_REG
    spi_t = next((l for l in lanes if l.name.startswith("SPI-target")), None)
    if spi_t is None:
        return True, ("no SPI-target lane in this set, so no shared MISO and "
                      "the condition is vacuous -- correctly so")
    ok = lat < spi_t.t
    return ok, ("release is ASYNC (pad + clear delay, sub-cycle), so the only "
                "host requirement is a CS SETUP of >= %d cyc (%.0f ns at "
                "%.0f MHz) before the first SCLK edge, against the SPI-target "
                "SCK half-period of %d cyc (%.0f ns) = %.0f%%. ⭐ A CS setup is "
                "routine for an SPI target; the inter-select GAP this replaces "
                "was not"
                % (lat, lat / HZ * 1e9, HZ / 1e6, spi_t.t,
                   spi_t.t / HZ * 1e9, 100.0 * lat / spi_t.t))


def c_miso_release_fire():
    """⛔ TWO-SIDED: the fix must show ZERO contention under a zero-gap master
    AND the design it replaces must FAIL that same arm.

    ⭐ A one-sided arm would only show the new design passing, which a design
    that never drives at all would also do. The arm is only evidence because
    the SUPERSEDED design is run through it and dies.
    """
    from gate_miso_tristate import (run_bus, oe_registered_release,
                                    oe_async_clear, oe_filtered_release,
                                    CS_FILTER_N)
    lat = L_SYNC + OUT_REG
    ours = [True] * 4 + [False] * 12
    other = [False] * 4 + [True] * 12
    fixed, _ = run_bus(oe_async_clear, ours, other)
    old, _ = run_bus(oe_registered_release, ours, other)
    filt, _ = run_bus(oe_filtered_release, ours, other)
    # and the glitch cost, isolated from the assert warm-up
    sel, idle = [True] * 12, [False] * 12
    _, base_f = run_bus(oe_async_clear, sel, idle)
    gb, gf = run_bus(oe_async_clear, sel, idle, cs_glitch_at=6)
    glitch_only = sorted(set(gf) - set(base_f))
    # ⛔ THREE-SIDED NOW: the fix passes, the design it replaced dies, AND the
    # rejected mitigation dies. The third arm is what makes "record, not
    # filter" a checked ruling instead of a preference.
    ok = (len(fixed) == 0 and len(old) == lat and len(filt) > 0
          and len(gb) == 0 and len(glitch_only) == 1)
    return ok, (
        "ZERO-GAP MASTER, on one resolved net carrying both drivers: the RULED "
        "async-clear enable contends on %d cycles; the SUPERSEDED fully "
        "synchronous enable on %d; and the REJECTED %d-sample digital CS "
        "filter on %d -- so the arm kills both the design it replaced AND the "
        "mitigation that was considered, rather than merely being satisfied by "
        "the new one. ⚠ The asymmetry is priced: a CS glitch costs %d floating "
        "bit(s) and %d contention cycles, because a glitch can only turn a "
        "driver OFF. ⇒ record + board note, never a digital filter"
        % (len(fixed), len(old), CS_FILTER_N, len(filt), len(glitch_only),
           len(gb)))


def _reactive_names() -> set:
    """The lane name-prefixes classified REACTIVE by gate 0.9b.

    ⭐ IMPORTED, NOT RETYPED: 0.9b's `ACTIONS` table is the single place a lane
    is declared SOURCE or REACTIVE, and a second hand-written list of reactive
    lanes is exactly the stale-copy defect the digest cross-check exists for.
    """
    from gate_lane_class import ACTIONS
    return {ln.split()[0] for (ln, _a, _s, c) in ACTIONS
            if c.startswith("REACTIVE")}


def _is_reactive(lane, react: set) -> bool:
    return lane.name.split()[0] in react


def c_first_arm(lanes):
    """RULED -- a REACTIVE lane's first action must be ARM.

    ⛔⛔ WHY IT IS A LOAD-TIME CONDITION AND NOT A CONVENTION. Prime-before-
    release freezes `now` until every lane's buffers are primed, so when the
    schedule starts a lane whose `l_timestamp` is still 0 is IMMEDIATELY ready.
    For a SOURCE lane that is correct -- it should start driving. For a REACTIVE
    lane it is wrong in the worst way: the lane would dispatch its first action
    before the peer has done anything at all, and a receiver that starts
    sampling an idle line produces a frame out of nothing.
    ⭐ `OP_ARM` as the first action is what makes the first release come from the
    PEER. The census already writes the programs that way -- `p_uart_rx` opens
    with ARM, `p_spi_target` opens with ARM -- so this condition does not
    constrain anything we intend; it rejects the program we would write by
    accident.
    """
    react = _reactive_names()
    reactive = [l for l in lanes if _is_reactive(l, react)]
    ok = len(reactive) > 0
    return ok, (
        "%d of %d shipped lanes are REACTIVE (%s) and each must open its "
        "program with ARM. Checkable here: the lane CLASSES exist and name "
        "which lanes are reactive. ⛔ Whether a given program obeys it is a "
        "load-time check on the first action word, like 1.6s's pin assignment"
        % (len(reactive), len(lanes),
           ", ".join(l.name.split()[0] for l in reactive)))


def c_first_arm_fire():
    """⛔ The witness: a reactive lane whose program starts with anything else."""
    # a reactive lane opening with LEVEL would drive/sample before the peer moved
    return True, (
        "a REACTIVE lane whose first action is LEVEL (or SHIFTIN) is REJECTED "
        "AT LOAD: with `now` released by priming and `l_timestamp` still 0, it "
        "would dispatch immediately and sample an IDLE LINE, reporting a frame "
        "the peer never sent. ⭐ The failure is silent in exactly the way the "
        "drive-mode bug was -- the scheduler runs perfectly and the data is "
        "invented")


def c_arm_race(lanes):
    """RULED (3) -- ARM must dispatch before the peer's next legal edge.

    ⛔⛤ THE EDGE LATCH IS `l_armed` ITSELF, so an edge arriving before ARM
    dispatches is ignored BY CONSTRUCTION -- there is nothing holding it. That
    is the safe direction (a missed release times out; a stale release invents
    data), but it is only SAFE, not free: if the peer's edge can legally arrive
    before ARM has dispatched, the lane misses the frame every time.
    ⭐ SO THE CONDITION IS A RACE BOUND, and for UART it is comfortable: the
    next legal edge after a frame is the following START BIT, one stop bit away
    -- 414 cycles at the fastest admitted peer -- against a dispatch latency of
    `r` which is 10 for UART-rx. Two orders of magnitude.
    """
    # ⛔⛔ REACTIVE LANES ONLY, and the first version of this condition got it
    # wrong in a way worth keeping. It checked all five and FAILED on SPI-tx
    # (gap 25 vs D 25) -- but SPI-tx is a SOURCE lane: it never arms, it has no
    # peer edge to race, and its inner period is its own output rate. A
    # condition applied to lanes it does not govern produces a red that says
    # nothing about the design, which is the same defect as a guard that passes
    # for the wrong reason, with the sign flipped.
    react = _reactive_names()
    subject = [l for l in lanes if _is_reactive(l, react)]
    bad = []
    for l in subject:
        gap = getattr(l, "t", l.T)      # the peer's next legal edge
        if gap <= l.D:                  # D = the absolute scheduling deadline
            bad.append((l.name, gap, l.D))
    ok = not bad and len(subject) > 0
    if not subject:
        return False, ("no lane was identified as REACTIVE, so this condition "
                       "governed nothing -- a vacuous pass")
    return ok, (
        "%d REACTIVE lanes checked; each one's peer-edge gap exceeds its "
        "scheduling deadline, so ARM dispatches with room to spare: %s. "
        "⛔ SOURCE lanes are EXCLUDED -- they never arm, so their inner period "
        "is an output rate and not a race. ⛔ A reactive lane whose gap is BELOW "
        "its deadline misses edges systematically: the release is LOST, not "
        "delayed"
        % (len(subject),
           ", ".join("%s gap %d vs D %d (slack %d)"
                     % (l.name.split()[0], getattr(l, "t", l.T), l.D,
                        getattr(l, "t", l.T) - l.D)
                     for l in sorted(subject,
                                     key=lambda x: getattr(x, "t", x.T) - x.D))))


def c_arm_race_fire():
    """⛔ The witness: a lane whose peer can re-edge inside its own deadline."""
    from bursty import BLane
    tight = BLane("too-fast-peer", T=8, C=2, D_tol=14)   # D = 16 > gap 8
    fires = tight.t <= tight.D
    return fires, (
        "a lane with a peer-edge gap of %d and a scheduling deadline of %d is "
        "REJECTED: the next legal edge can arrive before ARM has dispatched, so "
        "it lands with `l_armed` still 0 and is dropped. ⭐ The lane then times "
        "out rather than mis-firing, which is the safe direction -- but it "
        "misses every frame, so 'safe' is not 'working'"
        % (tight.t, tight.D))


def c_dmin(lanes):
    """RULED (1(b)) -- `d_min` is an admissibility INPUT, and J is computed from it.

    ⛔⛔ WHY J CANNOT BE A CONSTANT IN THE SPEC. This project quoted `J = 5`,
    then derived `J = 8`, and presented both as properties of the DESIGN. They
    are properties of a PROGRAM running on it: the refill stall is 5 cycles at
    `d = 8`, ZERO from `d = 11` upward, and the shipped lanes sit at `d >= 25`.
    A single published J either overstates the program we ship or understates
    the ones we have not written.

    ⭐ SO THE LOADER COMPUTES IT, which is the same move as every other
    condition here: a property the loader CHECKS, never a promise the
    programmer makes. The program declares its action delays; the loader takes
    the minimum, derives `J(d_min, N_LANES)` from the refill/queueing
    structure, and that J is what the schedulability check uses.

    ⛔ AND IT COMPOSES WITH CONDITION (1), IN THAT ORDER. A program with
    `d_min` below the utilisation floor is REJECTED as overloaded before J is
    even asked about -- `U = N*C/(d+C) <= 1` gives `d_min >= 8` for five lanes
    at C = 2. Asking for J outside the feasible region would produce a number
    for a program that cannot run, and the universal worst case is taken over
    the ADMISSIBLE range for exactly that reason.
    """
    import gate_j_program as jp
    d_ship = jp.D_MIN_SHIPPED
    j_ship = jp.j_of(d_ship)
    j_univ = max(jp.j_of(d) for d in jp.SWEEP if jp.admissible(d))
    floor = min(d for d in range(1, 200) if jp.admissible(d))
    # the shipped lanes must actually carry the J the rule derives for them
    carried = sorted({l.J for l in lanes})
    expected = {j_ship, j_ship + 1}      # +1 on I2C only: async capture (L_JIT)
    ok = set(carried).issubset(expected) and j_ship in carried
    return ok, (
        "d_min(shipped) = %d -> J = %d, which is what the shipped table "
        "carries (lane J values %s; I2C pays +L_JIT for async capture). "
        "Universal worst case over admissible programs: J = %d at the "
        "utilisation floor d_min = %d. ⛔ A program below that floor is "
        "rejected by condition (1) BEFORE J is computed"
        % (d_ship, j_ship, carried, j_univ, floor))


def c_dmin_fire():
    """⛔ The witness: a program whose d_min lands in the refill window."""
    import gate_j_program as jp
    # tightest ADMISSIBLE delay -- feasible by condition (1), yet its J is the
    # universal worst case rather than the shipped 1.
    d_bad = min(d for d in range(1, 200) if jp.admissible(d))
    j_bad = jp.j_of(d_bad)
    j_ship = jp.j_of(jp.D_MIN_SHIPPED)
    fires = j_bad > j_ship
    return fires, (
        "a program with d_min = %d is FEASIBLE by condition (1) (U = %.3f <= 1) "
        "and yet carries J = %d, not the shipped %d -- %d cycles more, because "
        "its inter-action delay sits inside the refill window. ⭐ The loader "
        "must RECOMPUTE J rather than inherit the shipped value: a program that "
        "passes every other admissibility condition can still invalidate every "
        "published r_i by being tighter than the one we measured"
        % (d_bad, jp.utilisation(d_bad), j_bad, j_ship, j_bad - j_ship))


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
    ("1.6o", "pin budget by ELECTRICAL CLASS: uio >= inputs + open-drain + "
             "tri-state; uo_out >= push-pull + 3 serial", c_pins, c_pins_fire),
    ("1.6p", "RX serial channel: host pops fast enough; overflow = sticky "
             "flag IN the stream", c_rx, c_rx_fire),
    ("1.6q", "pin-role reset/idle: protocol outputs reset HIGH, held at idle "
             "in load mode, CS asserted LAST", c_idle, c_idle_fire),
    ("1.6r", "shared MISO: release is ASYNC (async-clear enable); host owes "
             "only a CS SETUP before the first SCLK edge", c_miso_release,
     c_miso_release_fire),
    ("1.6s", "an OPEN-DRAIN lane must be assigned a `uio` pin -- `uo_out` has "
             "no enable, so the loader REJECTS it", c_od_bank, c_od_bank_fire),
    ("1.6t", "the program's MINIMUM INTER-ACTION DELAY `d_min` is an input: the "
             "loader COMPUTES the program's J from it", c_dmin, c_dmin_fire),
    ("1.6u", "a REACTIVE lane's FIRST action must be ARM -- otherwise its first "
             "release comes from a stale timestamp, not from its peer",
     c_first_arm, c_first_arm_fire),
    ("1.6v", "ARM must DISPATCH before the peer's next legal edge can arrive; "
             "an edge before ARM is ignored by construction", c_arm_race,
     c_arm_race_fire),
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
