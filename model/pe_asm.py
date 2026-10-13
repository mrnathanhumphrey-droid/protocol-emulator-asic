"""pe_asm -- the program assembler. First cut.

A protocol description goes in; out come the image, the admissibility verdict
with the failing lane and inequality NAMED, the program's computed `J`, and the
pyRTA margins.

⭐ WHY IT IS ON THE CRITICAL PATH AND NOT A CONVENIENCE. Without it nobody
outside this repo can write a program for the chip: the claim
"reprogrammable within its timing constraints" is only checkable if someone can
write a protocol and get back accept or reject. With it, the claim is something
a reader can run.

⛔⛔ AND IT IS WHERE TWO RULINGS LIVE THAT SILICON SHOULD NOT CARRY:

  * QUEUE OWNERSHIP. The TX queue is named per ACTION, which is what removed the
    baked lane->queue mapping -- but it re-opens the routing race it was built to
    kill: two lanes may name the SAME queue, or one lane may switch queues
    mid-transfer, and then bytes split by EDF interleave again. Enforcing it in
    silicon needs cross-action tracking over a whole program; checking it here
    costs a loop.
  * 1.6t, REWORDED. The ruling said "the loader COMPUTES the program's J from
    d_min". The chip NEVER USES J -- it is an input to the schedulability
    argument, not to the hardware -- so computing it on-chip buys nothing. The
    assembler computes it; the chip enforces only what is structural (1.6s).

⭐ SP2: THE PROTOCOL FRONT-END is `model/pe_proto.py` (I2C transactions with
START / repeated START / STOP generated from context, SPI CS framing, the CE5
1-Wire slot engine); it emits through `assemble` below, and
`model/gate_sp2_frontend.py` holds it byte-identical to the shipped FRAM images.
⚠ FIRST CUT, AND WHAT IS NOT HERE YET: the full 23-condition
1.6 report. `gate_admissibility_1_6.py` already carries those conditions against
the shipped set; wiring them per-program is the next step. The two rulings above
are complete.
"""

from __future__ import annotations

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "test"))
sys.path.insert(0, os.path.join(HERE, "a2"))

import hold_bound                         # noqa: E402
import count_ranges                       # noqa: E402  ruling SP2/P1
import nonadmissible                      # noqa: E402  ruling SP2/P4
import park_class                         # noqa: E402  ruling SP2/P3
import zero_spacing                       # noqa: E402  delay-0 REARM ruling
# ⭐ D2's per-program floor reuses ruling S's derivation and gate_um10204's
# transcribed table: one model of r_i, one table of minima, no copies here.
import gate_um10204 as um                 # noqa: E402
import program_a2                         # noqa: E402
from bursty import C_SHIPPED, L_SYNC      # noqa: E402
from pyrta_src import PINNED_COMMIT, pinned_pyrta  # noqa: E402
from make_smoke_image import (            # noqa: E402
    ACT_BASE, ACT_BYTES, AW, N_LANES, OP_ARM, OP_LEVEL, OP_READBIT,
    OP_REARM,
    OP_SHIFT,
    OP_SHIFTIN, PIN_NONE, act, hdr,
)
from pe_isa import full_store                  # noqa: E402
from pe_isa import i2c_order_problems, order_for  # noqa: E402  ruling RC4
from pe_isa import (flag_problems, FLAG_HALF_HIGH,  # noqa: E402  ruling HDR
                    FLAG_CLK_INV)

# ⚠ N_PINS IS THE PIN-MAP BOUND, not a pin count the ISA encodes:
# `PINW = 4` addresses 0..15 and only 12 pins exist, which is the whole
# reason a receive can name something unsamplable.
N_PINS = 12
N_TXQ = 4           # TX queues; goes into the parametric contract


class Reject(Exception):
    """An inadmissible program. The message names the lane and the rule."""


# ---------------------------------------------------------------------------
# RULING 1: queue ownership
# ---------------------------------------------------------------------------
def check_queue_ownership(lanes):
    """Each queue is consumed by AT MOST ONE lane, and a lane uses ONE queue.

    `lanes` is {lane_index: [(op, pin, level, delay, queue), ...]}.

    ⛔ BOTH HALVES MATTER, AND FOR THE SAME REASON. Two lanes on one queue means
    the queue's head is claimed by whichever lane the EDF interleave dispatches
    first, which is timing-dependent, so the host cannot know which lane gets
    the byte it pushed. A lane switching queues mid-program is the same fault
    seen from the other side: the host cannot know which queue the lane will
    draw from next. Either way bytes land in the wrong transmitter and NOTHING
    FLAGS IT -- the engine cannot tell a misrouted byte from an intended one.
    ⭐ Only actions that CONSUME are considered: `OP_SHIFT` reads `l_tx`, so a
    lane whose actions never shift has no queue and cannot collide with one.
    """
    owner = {}          # queue -> lane
    used = {}           # lane  -> set of queues
    for ln in sorted(lanes):
        for (op, _pin, _lvl, _dly, q) in lanes[ln]:
            if op != OP_SHIFT:
                continue
            if not 0 <= q < N_TXQ:
                raise Reject("lane %d names TX queue %d, outside 0..%d"
                             % (ln, q, N_TXQ - 1))
            used.setdefault(ln, set()).add(q)
            if q in owner and owner[q] != ln:
                raise Reject(
                    "TX queue %d is consumed by BOTH lane %d and lane %d. "
                    "Consumption order is the EDF interleave, so the host "
                    "cannot know which lane receives a byte it pushed; give "
                    "each transmitting lane its own queue."
                    % (q, owner[q], ln))
            owner.setdefault(q, ln)
    for ln, qs in sorted(used.items()):
        if len(qs) > 1:
            raise Reject(
                "lane %d draws from more than one TX queue (%s). A lane must "
                "use one queue throughout, or the host cannot know which queue "
                "the lane will take its next byte from."
                % (ln, sorted(qs)))
    return owner


# ---------------------------------------------------------------------------
# RULING 1.6x: a SHIFT lane's clock pin must not be its data pin
# ---------------------------------------------------------------------------
def check_shift_clock_alias(lanes, headers):
    """A lane that executes `OP_SHIFT` must name a clock pin OTHER than its
    data pin.

    ⛔⛔ WHY, AND IT IS A SILENT-CORRUPTION BUG. `OP_SHIFT` writes the data pin
    and then the CLOCK pin, clock SECOND (`src/pe_engine.v`, the OP_SHIFT case).
    With `clkpin == pin` the clock assignment overwrites the data bit with the
    action's `level` field, so at `level = 0` EVERY 1 BIT BECOMES A 0. The wire
    then carries a well-formed frame of the wrong data and nothing in the
    design can tell: no assertion, no flag, no timing anomaly.

    ⚠ IT WAS UNREACHABLE UNTIL T5.1 AND THEN IMMEDIATELY REAL. No bench had
    ever driven the host channel, so every `OP_SHIFT` in the suite's history
    ran on an all-zero shift register where losing the 1 bits changed nothing
    observable. `build_census` had declared `clkpin == pin` on its shifting
    lane the whole time.

    ⭐ SCOPED TO SHIFTING LANES, NOT A BLANKET RULE, and the scope is load-
    bearing. `l_clkpin` reaches the pins ONLY inside the `OP_SHIFT` case, so
    for a lane that never shifts the alias is a don't-care -- and `build_five`
    declares it on all five lanes while running only `OP_LEVEL`. That BUILDER
    is the measurement base for T1's per-lane `J` and for Theorem 3's 35
    port-feasible cells; refusing it for a hazard it cannot reach would
    invalidate both and buy nothing. ⚠ THE BUILDER, AT EACH RUNNER'S OWN
    DELAYS -- Theorem 3's cells are `run_dstar_check` at d = 20..60, every
    point admissible. The TRACKED `five_image.hex` (d = 12..16, U = 1.083) is
    a declared non-admissible MECHANISM image and backs neither (ruling Q3).

    ⛔ THE CHIP ALSO REFUSES IT (1.6x in silicon), at DISPATCH rather than at
    header load: at header-load time the chip cannot know whether a lane's
    program contains a SHIFT, because actions are fetched lazily. Here the
    whole program is visible, so the refusal is static and names the lane.
    """
    # ⛔⛔ RULING CI5: THE ACTION's PIN, NOT THE HEADER's. The chip's 1.6x
    # refusal is `l_clkpin[cur] == a_pin` -- the pin the SHIFT action names --
    # and this check compared the HEADER pin. So it ACCEPTED a SHIFT whose
    # own pin is the clock (the chip refuses it at dispatch), and REFUSED a
    # header alias whose actions drive another pin (the chip runs it). Found by
    # the pin-field audit (PN2): every program tested had action pin == header
    # pin, where the two readings agree.
    for ln in sorted(lanes):
        if ln not in headers:
            continue
        clkpin = headers[ln][1]
        bad = [pin for (op, pin, _l, _d, _q) in lanes[ln]
               if op == OP_SHIFT and pin == clkpin]
        if bad:
            pin = bad[0]
            raise Reject(
                "lane %d executes OP_SHIFT and names pin %d as BOTH its data "
                "and its clock pin. OP_SHIFT writes the data pin and then the "
                "clock pin, so the clock write would overwrite every data bit "
                "with the action's level field -- at level = 0 every 1 bit "
                "becomes a 0, and the wire carries a well-formed frame of the "
                "wrong data with nothing flagging it. Give the lane a distinct "
                "clock pin (or PIN_NONE if it needs no clock)."
                % (ln, pin))



# ---------------------------------------------------------------------------
# RULING 1 (toolchain half): a receive must name a pin it can sample
# ---------------------------------------------------------------------------
def check_clocked_hold_delay(lanes, headers):
    """A CLOCKED OPEN-DRAIN action must ask for `d > SDA_HOLD` (ruling D2).

    ⛔⛔ WHY, AND IT IS THE SILENT-CORRUPTION CLASS AGAIN. The SDA data hold
    (ruling H) defers a data-pin write by `SDA_HOLD` cycles so the bit stays
    stable across the SCL fall, which is what `t_HD;DAT` requires. That only
    works if the bit period is LONGER than the hold: at `d <= SDA_HOLD` the
    held value lands AFTER the next clock rise, and data moving while SCL is
    high is a START or a STOP to any receiver. The wire then carries a
    well-formed frame of the wrong thing.

    ⭐ THE CHIP ALSO REFUSES IT (D1 in silicon), at DISPATCH: `ck_refuse` sets
    `config_err` and halts the engine, so a store corrupted by a bad load
    cannot run it either. This refusal is the other half -- the chip must not
    be ASKED -- and here the whole program is visible, so the lane, the
    opcode and the legal floor are all named.

    ⭐⭐ THE BOUNDARY IS **READ FROM THE RTL**, never typed here. A second copy
    of 15 in the assembler would keep refusing at 15 after the hold moved,
    which is the direction that matters: the assembler would ACCEPT programs
    silicon refuses, and the toolchain would be telling people their program
    is fine. See `model/hold_bound.py`.

    ⭐ THIS IS ONE OF D2's TWO HALVES. It is the HARD floor -- `SDA_HOLD`
    holds for every program and every mode -- and it landed first. The
    PER-PROGRAM half, `d >= t_LOW(min, mode) + (r_i - C)` from that program's
    own lane set, is `check_mode_floor`, which landed with ruling S and runs on
    the assembled image. A lane can clear this check and still fail that one
    (d = 20: above the hold, under every t_LOW), which is exactly the gap the
    static half used to leave open and the reason both run.
    """
    try:
        hold = hold_bound.bound()
    except hold_bound.HoldBoundError as exc:
        # ⛔ A BOUNDARY THAT CANNOT BE READ IS A REFUSAL, NOT A SKIP. Returning
        # quietly here would accept every program in exactly the situation
        # where the assembler has no idea what silicon does.
        raise Reject(
            "the SDA hold boundary could not be read from the RTL, so no "
            "clocked delay can be judged: %s" % exc)
    if hold == 0:
        return hold
    for ln in sorted(lanes):
        if ln not in headers:
            continue
        _pin, clkpin, mode = headers[ln][0], headers[ln][1], headers[ln][2]
        if clkpin >= N_PINS or mode != 0:
            continue                      # no real clock, or push-pull
        for (op, _p, lvl, dly, _q) in lanes[ln]:
            clocked = op in (OP_SHIFT, OP_SHIFTIN) and lvl
            # ⛔ RULING U: the UNCLOCKED open-drain SHIFT that takes its own
            # clock low (level 0, real clock pin) is held by the same pipeline
            # and REFUSED by the same silicon rule (`uc_hold` in pe_engine.v).
            # This check accepted it until U -- the assembler would have told
            # a user that a program the chip refuses was fine.
            unclocked_low = op == OP_SHIFT and not lvl
            if not (clocked or unclocked_low):
                continue
            if dly <= hold:
                raise Reject(
                    "lane %d runs an OPEN-DRAIN %s%s with delay %d, which "
                    "is not above the %d-cycle SDA data hold. The held data bit "
                    "would reach the pin after the next clock rise -- data "
                    "moving while SCL is high, which to any receiver is a START "
                    "or a STOP rather than a bit. The chip REFUSES this program "
                    "(CONFIG_ERR, engine-wide halt), so it would not run. Use "
                    "d >= %d, and note that the MODE floor is higher still: "
                    "Fm+ needs t_LOW >= 25 cycles, Fm 65, Sm 235, plus that "
                    "program's own service jitter (ruling S)."
                    % (ln, "CLOCKED " if clocked else "UNCLOCKED clock-low ",
                       "SHIFT" if op == OP_SHIFT else "SHIFTIN", dly,
                       hold, hold + 1))
    return hold


def check_mode_floor(img):
    """Every clocked open-drain lane must clear SOME UM10204 mode (ruling D2).

    ⭐⭐ THE PER-PROGRAM HALF OF D2, landed on ruling S's machinery rather than a
    second model. The floor is

        worst-case t_LOW = d - (r_i - C)  >=  t_LOW(min, mode)

    and `r_i` belongs to the pair (PROGRAM, LANE): this program's own lane set,
    from its own headers, delays and `J`, through `model/a2/program_a2.py` with
    pyRTA primary. ⛔ The fixed 38/78/248 floor this replaces was `ckod`'s
    observed jitter promoted to a law -- a number from one lane set applied to
    every program, the same error ruling S removed from the bench.

    ⚠ "SOME MODE", AND THE ISA IS WHY. Nothing in a program declares which
    I2C mode a lane intends, so the assembler can only refuse a lane that
    claims NONE: Fm+ has the smallest minima, so a lane under Fm+'s floor is
    illegal at every rate. The mode each lane DOES clear is reported, so a
    program meant for 400 kHz can see that it only reaches Fm+.

    ⛔ OVERLOADED IS A REFUSAL, NOT A PASS. A lane set with U > 1 has no
    finite `r_i`, so no `t_LOW` floor can be certified for its clocked lane.
    ⭐⭐ THE START DELAY IS `r_floor` -- the LARGER of our recurrence and pyRTA
    when both exist, our recurrence alone when pyRTA is absent -- and the
    report names which. ⛔ The first version REFUSED outright without pyRTA,
    and `pe_asm` is in `ci/run_gates.sh`, where pyRTA is deliberately absent
    (not vendored; every pyRTA-primary gate runs under `run_a2.py` instead).
    CI went red. Our recurrence measured `>=` pyRTA on every clocked lane in
    the repo, so it is the STRICTER floor on all of them -- the safe direction
    for a refusal -- and when pyRTA is present the max is taken rather than
    that observation trusted.
    """
    # ⛔ P6: an unpinned pyRTA is treated as ABSENT -- the floor then rests
    # on our recurrence alone and says so, rather than on an unknown copy.
    src = pinned_pyrta(quiet=True)
    res = program_a2.derive(img, src)
    tc = um.table_cycles()
    claims = {}
    for ln, e in sorted(res["lanes"].items(), key=lambda kv: int(kv[0])):
        if e["r_floor"] is None:
            raise Reject(
                "lane %s is a clocked open-drain lane in a program whose lane "
                "set has no finite worst-case response (%s), so its low phase "
                "has no certifiable floor and no UM10204 mode can be claimed."
                % (ln, e["why"]))
        lag = e["r_floor"] - C_SHIPPED
        lo = e["T"] - lag
        hi = e["T"] + L_SYNC
        mode = um.claimable(lo, hi, tc)
        if mode is None:
            need = min(tc[m]["t_LOW"] for m in tc) + lag
            raise Reject(
                "lane %s runs a clocked open-drain action at d = %d, and in "
                "THIS program's lane set its dispatch can start up to %d "
                "cycle(s) late (r_i - C, pyRTA), so its low phase can shrink to "
                "%d cycles -- under every UM10204 mode's t_LOW minimum. The "
                "floor for this lane in this program is d >= %d. It is per "
                "program: the same lane beside lighter traffic could pass."
                % (ln, e["T"], lag, lo, need))
        claims[int(ln)] = (mode, lo, lag)
    claims.update(check_unclocked_floor(img, src))
    # ⛔ RULING A7: a REFUSAL THRESHOLD, not a published number -- it reads
    # ours when pyRTA is absent, ON PURPOSE: after ruling Z ours is >= pyRTA on
    # every admissible lane (gate_a2_program §1b), so this can only refuse
    # MORE than the published bound would, never accept what it refuses.
    check_mode_floor.basis = (
        "max(our recurrence, pyRTA @ %s)" % PINNED_COMMIT[:12] if src
        else "our recurrence only -- pyRTA absent or unpinned; INTENDED for a "
             "refusal threshold: ours >= pyRTA on every admissible lane, so "
             "this is the stricter side (ruling A7)")
    return claims


def claim_mode(lo, hi, su, tc):
    """The loosest mode whose t_LOW, t_HIGH AND t_SU;DAT minima all hold."""
    for m in reversed(list(tc)):
        if (lo >= tc[m]["t_LOW"] and hi >= tc[m]["t_HIGH"]
                and su >= tc[m]["t_SU_DAT"]):
            return m
    return None


def unclocked_phases(h, acts):
    """Nominal SCL phases of an UNCLOCKED open-drain frame, from its actions.

    Returns (lows, highs, held setups, direct setups) in cycles, or None if
    the lane never drives its clock with the unclocked idiom. SCL moves on
    `OP_SHIFT` at level 0 (data + clock low in one dispatch) and on `OP_LEVEL`
    aimed at the clock pin.
    An action's delay is the time to the NEXT action's release (P8), so the
    phase lengths are sums of delays. A setup is measured from each SDA move
    inside a low phase to the rise that ends it: a HELD move (SHIFT at level 0,
    the SHIFTIN/READBIT release on the lane's own pin) lands SDA_HOLD after
    its dispatch, so the hold is subtracted; an `OP_LEVEL` on the data pin is
    driven directly.
    """
    clk, pin = h["clkpin"], h["pin"]
    hold = hold_bound.bound()
    drives = False
    ev = []                             # (scl after or None, sda move kind)
    for a in acts:
        op, p, lvl = a["op"], a["pin"], a["level"]
        scl, sda = None, None
        # ⚠ A level-1 SHIFT with a real clock pin is the CLOCKED shift
        # (`ck_shift`), and the caller sends any lane that has one to the
        # clocked floor -- so only level 0 can appear here.
        if op == OP_SHIFT and not lvl:
            scl, sda, drives = 0, "held", True
        elif op == OP_LEVEL and p == clk:
            scl, drives = lvl, True
        elif op == OP_LEVEL and p == pin:
            sda = "direct"
        elif op in (OP_SHIFTIN, OP_READBIT) and p == pin:
            sda = "held"
        ev.append((scl, sda, a["delay"]))
    if not drives:
        return None
    loops = bool(acts) and acts[-1]["op"] == OP_REARM and acts[-1]["level"]
    seq = ev * (3 if loops else 1)
    lows, highs, held, direct = [], [], [], []
    t, state, edge, moves = 0, 1, None, []
    for scl, sda, dly in seq:
        changed = scl is not None and scl != state
        if changed:
            if edge is not None:
                (lows if state == 0 else highs).append(t - edge)
                if state == 0:
                    for tm, k in moves:
                        if k == "held":
                            held.append(t - tm - hold)
                        else:
                            direct.append(t - tm)
            state, edge, moves = scl, t, []
        if sda is not None and state == 0:
            moves.append((t, sda))
        t += dly
    return lows, highs, held, direct


def check_unclocked_floor(img, src=None):
    """RULING W7: UNCLOCKED open-drain frames clear SOME mode too.

    ⛔⛔ WHY. `check_mode_floor` judged clocked lanes only, so the unclocked
    frame (`build_i2cframe`) at d = 16 -- above the 15-cycle hold, so the
    silicon runs it -- was accepted by the toolchain while its low phase sat
    under every mode's t_LOW. W1 now keeps it safe on the wire (no SDA move
    with SCL released); this is the COMPLIANCE half: t_LOW, t_HIGH and
    t_SU;DAT against UM10204 per mode, with this program's own start delay.
    The worst case takes the earlier dispatch of a pair late by `r_i - C` and
    the later one on time, exactly as the clocked floor does.
    ⚠ t_HIGH here is NOT stretch-safe: an unclocked lane does not observe the
    SCL rise (only a clocked park does, F1), so a stretching peer shortens it.
    That limitation is the unclocked idiom's, recorded, not new.
    ⭐ t_SU;DAT is never taken below SDA_SETUP + 1: W1 holds the rise back that
    far behind a held move in silicon, whatever the schedule does.
    """
    tc = um.table_cycles()
    su_floor = hold_bound.setup() + 1
    resp = None
    claims = {}
    for ln, h, acts in program_a2.lanes_of(img):
        if h["mode"] != 0 or h["clkpin"] >= N_PINS:
            continue
        if any(program_a2.is_clocked(h, a) for a in acts):
            continue                    # judged by the clocked floor
        ph = unclocked_phases(h, acts)
        if ph is None or not ph[0]:
            continue                    # no complete SCL low phase to judge
        if resp is None:
            resp = program_a2.lane_responses(img, src)
        r, why = resp.get(ln, (None, "lane not in the lane set"))
        if r is None:
            raise Reject(
                "lane %d is an unclocked open-drain frame in a program whose "
                "lane set has no finite worst-case response (%s), so its low "
                "phase has no certifiable floor and no UM10204 mode can be "
                "claimed." % (ln, why))
        lag = r - C_SHIPPED
        lows, highs, held, direct = ph
        lo = min(lows) - lag
        hi = (min(highs) - lag) if highs else lo
        # held moves get W1's silicon floor; a direct move (`OP_LEVEL` on the
        # data pin) gets none
        sus = [max(min(held) - lag, su_floor)] if held else []
        sus += [s - lag for s in direct]
        su = min(sus) if sus else su_floor
        mode = claim_mode(lo, hi, su, tc)
        if mode is None:
            need = min(tc[m]["t_LOW"] for m in tc) + lag
            raise Reject(
                "lane %d is an UNCLOCKED open-drain frame whose shortest SCL "
                "low phase is %d cycles nominal; in THIS program its dispatches "
                "can start up to %d cycle(s) late (r_i - C), so t_LOW can "
                "shrink to %d (t_HIGH %d, t_SU;DAT %d) -- under every UM10204 "
                "mode. The chip runs it and W1 keeps SDA still while SCL is "
                "high, but it is mode-illegal. The floor for this lane in this "
                "program is a low phase >= %d, per program."
                % (ln, min(lows), lag, lo, hi, su, need))
        claims[ln] = (mode, lo, lag)
    return claims


def check_receive_pin(lanes, headers):
    """`OP_SHIFTIN` and `OP_READBIT` must name a REAL data pin.

    ⛔⛔ WHY IT IS ALWAYS A PROGRAM ERROR. A receive with nothing to sample
    cannot mean anything: the opcode exists to put a bit from a pin into
    `l_rx`. `PINW = 4` addresses 0..15 while only `N_PINS = 12` pins exist, so
    a receive on 12..15 reads out of range -- and that is not theoretical. It
    shipped: `pin_in[a_pin]` was read with no range guard, so `OP_SHIFTIN` on
    PIN_NONE put X into `l_rx`, then `rx_data`, then the serial readback, and
    the X LEFT THE CHIP on `ser_d` while `ser_v` was high.

    ⭐ THE SILICON NOW SAMPLES A DEFINED 0 (`rx_bit = pin_real ? ... : 1'b0`),
    so the chip is safe whatever it is handed. This refusal is the other half:
    the chip must not be ASKED. In silicon an out-of-range read is not X at
    all but whatever synthesis made of it -- deterministic and UNSPECIFIED --
    so "it is defined now" is a reason to keep programs away from it, not a
    reason to allow them.

    ⚠ SCOPED TO THE DATA PIN OF A RECEIVE, and the scope is load-bearing in
    two directions:
      * PIN_NONE as a CLOCK pin stays legal -- an SPI TARGET names it
        deliberately, because the master supplies SCK. `clk_real` is what
        guards that path.
      * PIN_NONE as the action pin of a NO-OP stays legal -- the half-bit
        offset idiom is built on it (`build_noop`), and `OP_LEVEL` on a
        non-real pin is precisely how a no-op moves nothing.
    Refusing either would break a shipped mechanism and buy nothing.

    ⛔ AND IT IS A STATIC REFUSAL BECAUSE IT CAN BE. The chip cannot know at
    header-load time whether a lane's program contains a receive -- actions are
    fetched lazily -- so silicon guards at dispatch. Here the whole program is
    visible, so the error is named with its lane and its opcode.
    """
    # ⛔⛔ `OP_ARM` JOINS THE SAME REFUSAL (Wilson's addition, from the third
    # instance of the out-of-range family). An ARM names the pin whose EDGE
    # releases the lane, and `pin_rise[l_armpin]` indexes a [N_PINS-1:0]
    # vector -- so an ARM on 12..15 can never see an edge and can only ever
    # time out. Measured before the silicon guard existed: `arm_hit` was X for
    # all 198 armed cycles. A lane armed on a pin that does not exist is
    # always a program error, exactly as a receive with nothing to sample is.
    # ⚠ `OP_REARM` IS **NOT** INCLUDED, and that is deliberate: every program
    # in the suite ends its loop with `act(OP_REARM, 0, 1, d)` where the pin
    # field is not an arm pin at all -- re-arm reuses the lane's existing
    # `l_armpin`. Refusing on its pin field would reject every program here.
    names = {OP_SHIFTIN: "OP_SHIFTIN", OP_READBIT: "OP_READBIT",
             OP_ARM: "OP_ARM"}
    for ln in sorted(lanes):
        for (op, pin, _lvl, _dly, _q) in lanes[ln]:
            if op not in names:
                continue
            if pin < N_PINS:
                continue
            raise Reject(
                "lane %d executes %s on pin %d, which is not a real pin "
                "(N_PINS = %d, so only 0..%d exist%s). A receive with nothing "
                "to sample -- or an edge on a pin that does not exist -- cannot "
                "mean anything, and an out-of-range read is "
                "X in simulation and an UNSPECIFIED synthesised value in "
                "silicon. PIN_NONE is legal as a CLOCK pin (an SPI target "
                "needs that) and as a no-op's action pin, but not as the pin a "
                "receive samples."
                % (ln, names[op], pin, N_PINS, N_PINS - 1,
                   "; %d is PIN_NONE" % PIN_NONE if pin == PIN_NONE else ""))


# ---------------------------------------------------------------------------
# 1.6t: the program's J, computed HERE and not on the chip
# ---------------------------------------------------------------------------
def ws2812_sub3(rearm_d):
    """THE PROGRAM THE DELAY-0 REARM RULING IS ABOUT, in one place: the WS2812
    3-sub-bit lane (SHIFT-only at d = 21 on uo_out[0], queue 0, its loop closed
    by a REARM at `rearm_d`) beside four push-pull lanes toggling at d = 20.
    `rearm_d = 0` is the build pe_asm once ACCEPTED ("J 1") whose wire stream
    was not its feed; `rearm_d = 21` is its control. Used by pe_asm's own
    must-fire (refused / accepted) and by `test/run_wirefeed_mf.py` (the old
    image's wire stream must be RED under V3, the control's green)."""
    lanes_b = {ln: [(OP_LEVEL, p, 1, 20, 0), (OP_LEVEL, p, 0, 20, 0),
                    (OP_REARM, 0, 1, 20, 0)]
               for ln, p in zip((1, 2, 3, 4), (9, 10, 11, 0))}
    headers_b = {ln: (p, PIN_NONE, 1, 20, 20, 40)
                 for ln, p in zip((1, 2, 3, 4), (9, 10, 11, 0))}
    lanes_b[0] = [(OP_SHIFT, 8, 0, 21, 0, 7), (OP_REARM, 0, 1, rearm_d, 0)]
    headers_b[0] = (8, PIN_NONE, 1, 21, 21, 42)
    return lanes_b, headers_b


def check_zero_spacing(lanes, engine_text=None):
    """DELAY-0 REARM RULING: refuse any zero release spacing -- a delay-0
    action other than an ARM, whose delay 0 means "no timeout" and whose lane
    waits on its edge (`model/zero_spacing.py`, RTL anchors E1-E3; with an
    anchor gone the ARM is refused too). No J exists for a lane that
    dispatches back to back, so the program is refused, never quoted."""
    try:
        zero_spacing.check([(ln, i, a[0], a[3]) for ln in sorted(lanes)
                            for i, a in enumerate(lanes[ln])], engine_text)
    except zero_spacing.ZeroSpacingError as exc:
        raise Reject(str(exc))


def compute_j(lanes, spl=2):
    """`J` from the program's minimum inter-action delay, per gate_j_program.

    ⛔⛔ THE SCOPED CLAIM IS CONDITIONAL ON `SPL = 2`, AND THAT IS MEASURED,
    NOT ASSUMED. `SPL` (action slots per lane) is now a real parameter, and
    `test/run_spl_compare.py` measures both depths on the J sweep's own recipe:

        d >= D* = 20   SPL = 2 stalls 0        SPL = 1 stalls up to 5
        cliff          SPL = 2 at d = 19       SPL = 1 at d = 25

    The cliff STRADDLES `D* = 20`. So `d_min >= D* -> J = 1` is a property of
    the double-buffered engine, not of the architecture, and certifying a
    program against a single-buffer build would hand over a guarantee that
    build does not provide.
    ⇒ This refuses rather than adjusting the number. A `J` for `SPL = 1` would
      need its own derivation and its own measured check, and neither exists.
    """
    import gate_j_program as jp
    if spl != 2:
        raise Reject(
            "this build has SPL = %d (action slots per lane) and the timing "
            "guarantee is scoped to SPL = 2. Measured on the same recipe, the "
            "stall cliff sits at d = 19 with the double buffer and d = 25 "
            "without it -- straddling D* = %d -- so `d_min >= D* -> J = 1` "
            "holds only at SPL = 2. No J is published for SPL = 1: it would "
            "need its own derivation and its own measured check."
            % (spl, jp.D_STAR))
    # ⛔⛔ DELAY-0 REARM RULING (Wilson): a delay-0 action is a ZERO spacing,
    # and filtering `d > 0` below used to make it invisible -- the WS2812
    # 3-sub-bit lane and the old UART-rx chain were both "J 1" here. Refused
    # FIRST, so the filter below only ever drops an exempt ARM's "no timeout".
    check_zero_spacing(lanes)
    delays = [d for ln in lanes for (_o, _p, _l, d, _q) in lanes[ln] if d > 0]
    if not delays:
        raise Reject("the program has no positive action delay, so d_min is "
                     "undefined and its J cannot be computed")
    d_min = min(delays)
    # ⛔ `admissible` FIRST. `j_of` is only meaningful on an admissible d_min:
    # below the feasible floor the set is overloaded and a J derived there would
    # manufacture a worse number than any runnable program can produce -- the
    # exclusion that kept the universal J at 8 rather than something larger.
    # ⛔⛔ PORT FEASIBILITY FIRST, AND IT IS STRICTLY STRONGER THAN
    # ADMISSIBILITY. `admissible` only asks whether the DISPATCHER keeps up
    # (U = k*C/d <= 1, so d >= k*C = 15). Every dispatched action must also be
    # REFILLED through ONE shared fetch port, which needs d >= k*L_REFILL.
    # ⚠ THIS CHECK IS UNREACHABLE AS A REJECTION PATH, AND WAS BEFORE THE
    # CORRECTION TOO. Port feasibility is tested FIRST and needs d >= 20,
    # which strictly dominates d >= 15 (and dominated d >= 8 by more). So no
    # program reaches the `admissible` refusal below -- every sub-D* program
    # is refused by the port screen with the port arithmetic named, which is
    # the better message anyway. It is kept rather than deleted because it is
    # the SOUNDNESS condition: if D* ever fell (more fetch bandwidth), this is
    # the screen that would start binding, and a loader that had dropped it
    # would admit an overloaded set.
    # ⚠ THE GAP IS WHERE THE PUBLISHED UNIVERSAL J WAS FOUND UNSOUND: live
    # measurement puts the steady stall at 8..12 for admissible-but-saturated
    # programs (d = 8..18) where the old derivation predicted 0..7. The chip
    # has no bound there, so the assembler REFUSES rather than quoting one.
    if not jp.port_feasible(d_min):
        worst = min((d, ln) for ln in lanes
                    for (_o, _p, _l, d, _q) in lanes[ln] if d > 0)
        raise Reject(
            "d_min = %d is below D* = %d: with %d lanes a refill occupies the "
            "single fetch port for %d cycles, so %d lanes consuming one action "
            "every %d cycles saturate it. LANE %d carries the tightest spacing. "
            "The timing guarantee is SCOPED to d_min >= D*; below it the "
            "steady-state jitter is measured at 8..12 and no bound is published."
            % (d_min, jp.D_STAR, N_LANES, jp.L_REFILL, N_LANES, d_min,
               worst[1]))
    if not jp.admissible(d_min):
        raise Reject(
            "d_min = %d is INADMISSIBLE: utilisation %.3f > 1 with %d lanes, so "
            "the set is overloaded and no J applies. Space the actions further "
            "apart." % (d_min, jp.utilisation(d_min), N_LANES))
    return d_min, jp.j_of(d_min)


def header_flags(h):
    """The lane's mode bits (ruling HDR): an optional 7th header element,
    FLAG_HALF_HIGH | FLAG_CLK_INV; 0 when absent."""
    return int(h[6]) if len(h) > 6 else 0


def header_order(h, ops):
    """The lane's bit order (SP2): an optional 8th header element, else the
    one `order_for` derives from the program.

    ⭐ FOUND BY THE SP2 BYTE-IDENTITY REGRESSION: an SPI FRAM lane is
    MSB-first and has no START/STOP for `order_for` to see, so `corpus.py`
    states the order in its own spec -- and pe_asm could not, so the shipped
    SPI FRAM image was not expressible here at all. ⛔ A STATED order may not
    contradict a DERIVED I2C one: `check_i2c_order` still runs on the image.
    """
    return int(h[7]) if len(h) > 7 else order_for(ops)


def split_counts(lanes):
    """An action is `(op, pin, level, delay, q[, count])`; count defaults to 8.

    ⭐ FOUND BY THE UART-rx DEMO (Wilson's UART ruling): the count was
    hard-wired to 8, so pe_asm could not express a ONE-bit SHIFTIN -- the
    mid-stop sample that turns the stop bit into a pushed byte the host checks.
    The checks below all read 5-tuples; the count is split off here, once.
    Returns (lanes with 5-tuples, {(lane, index): count}).
    """
    # ⭐⭐ SP2: THE LEGAL COUNT RANGE IS PER OPCODE, and a single 1..15 range
    # made two SHIPPED programs inexpressible. Found by the SP2 byte-identity
    # regression (`model/gate_sp2_frontend.py`):
    #   * a ONE-bit clocked SHIFT (the I2C master's ACK/NACK) is `count = 0`
    #     -- OP_SHIFT counts `nbits - 1` (`pe_isa.act_shift_clocked`) -- so the
    #     FRAM random read could not be written through pe_asm at all;
    #   * START/STOP/LEVEL/READBIT/ARM/REARM never read the field, and
    #     `run_ckack.image` writes 0 there (the corpus writes 8).
    # The refusals that remain are the chip's own: a clocked SHIFT at 15
    # (count + 1 wraps to zero bits) and a SHIFTIN at 0 (zero bits) are
    # CONFIG_ERR in silicon (HOST_INTERFACE, "What counts as illegal").
    # ⛔⛔ WILSON'S CONDITION: THE TABLE IS DERIVED FROM THE RTL DECODE, never
    # typed here (`model/count_ranges.py`: BPW, `ck_nbits`, `ck_degen`, each a
    # text anchor in src/pe_engine.v; `model/gate_count_ranges.py` prints the
    # file:line of each). A missing anchor is a REFUSAL, not a fallback table.
    try:
        rr = count_ranges.ranges()
    except count_ranges.CountRangeError as exc:
        raise Reject("the per-opcode count range could not be derived from "
                     "the RTL, so no count can be judged: %s" % exc)
    lo_hi = {OP_SHIFT: rr[count_ranges.OP_SHIFT],
             OP_SHIFTIN: rr[count_ranges.OP_SHIFTIN]}
    other = rr[None]
    five, counts = {}, {}
    for ln in lanes:
        five[ln] = []
        for i, a in enumerate(lanes[ln]):
            if len(a) not in (5, 6):
                raise Reject("lane %d action %d has %d fields; an action is "
                             "(op, pin, level, delay, q[, count])"
                             % (ln, i, len(a)))
            cnt = int(a[5]) if len(a) == 6 else 8
            lo, hi = lo_hi.get(int(a[0]), other)
            if not lo <= cnt <= hi:
                raise Reject("lane %d action %d: count %d is outside %d..%d "
                             "for this opcode -- the range is derived from "
                             "the RTL decode (`ck_nbits` / `ck_degen` in "
                             "src/pe_engine.v, model/count_ranges.py): a "
                             "zero bit count is CONFIG_ERR in silicon"
                             % (ln, i, cnt, lo, hi))
            counts[(ln, i)] = cnt
            five[ln].append(tuple(a[:5]))
    return five, counts


def check_open_drain_bank(headers, park_pins=None):
    """1.6s: an OPEN-DRAIN lane's data pin AND clock pin must be `uio` pins.

    ⛔⛔ FOUND BY CE5 (the 1-Wire demo), AND IT WAS A TOOLCHAIN-SILICON
    DISAGREEMENT. The chip refuses such a header at LOAD (`pe_engine.v`, the
    1.6s block: mode 0 with `pin >= N_UIO` or `clkpin >= N_UIO` sets
    CONFIG_ERR), and pe_asm never checked it -- so a 1-Wire lane written with
    no clock (`clkpin = PIN_NONE`, which is what a clockless protocol means)
    ASSEMBLED CLEANLY and the chip ran nothing: CONFIG_ERR, zero writebacks.
    ⚠ PIN_NONE IS A "NO CLOCK" ONLY ON A PUSH-PULL LANE (the SPI target). On
    an open-drain lane the clock pin must exist even if the protocol has no
    clock -- see docs/CE5_LOG.md, OW3.
    """
    for ln, h in sorted(headers.items()):
        if int(h[2]) == 0:
            for what, p in (("data", h[0]), ("clock", h[1])):
                if not 0 <= int(p) < 8:
                    raise Reject(
                        "lane %d is OPEN-DRAIN and names %s pin %d, which is "
                        "not a `uio` pin (0..7). The chip REFUSES this header "
                        "at load (1.6s, CONFIG_ERR, engine-wide halt): a "
                        "`uo_out` pin cannot release, and PIN_NONE is not a "
                        "clock an open-drain lane may name. Give the lane a "
                        "real `uio` clock pin even if the protocol has none."
                        % (ln, what, p))
    for ln, p in sorted((park_pins or {}).items()):
        if not 0 <= int(p) < 8:
            raise Reject("parked lane %d is open-drain on pin %d, not a `uio` "
                         "pin -- the chip refuses it at load (1.6s)" % (ln, p))


#: the parked lanes' header pin when the caller names none -- pin 1 (I2C SCL
#: in the ruled map), what `assemble` and `corpus._assemble` have always used
PARK_PIN = 1


def active_pins(lanes, headers):
    """{pin: [(lane, mode, what), ...]} for every REAL pin an active lane
    names: its header data and clock pin, and every action's pin. EVERY user,
    not the first: the park rule needs the drive class of all of them."""
    out = {}
    for ln in sorted(headers):
        h = headers[ln]
        for what, p in (("data", h[0]), ("clock", h[1])):
            if int(p) < N_PINS:
                out.setdefault(int(p), []).append(
                    (ln, int(h[2]), what + " pin"))
        for (op, p, _l, _d, _q) in lanes.get(ln, ()):
            if int(p) < N_PINS and op not in (OP_REARM,):
                out.setdefault(int(p), []).append(
                    (ln, int(h[2]), "action pin"))
    return out


def check_park_overlap(lanes, headers, park_pins, engine_text=None):
    """SP2/P3, ONE RULE FOR EXPLICIT AND IMPLICIT PARKS (Wilson): a PARKED lane
    may name a pin an ACTIVE lane uses iff it is RELEASE-ONLY there for the
    whole program, proven from RTL anchors (`model/park_class.py`, K1..K5).

    ⛔⛔ WHY IT IS NOT COSMETIC. A parked lane's header is LOADED like any other
    (`pe_engine.v`, ruling 1.5 at header load): it writes `pin_pp[pin]` -- the
    pin's DRIVE CLASS -- from its own mode (open-drain, 0), and lanes load in
    order, so a parked lane after an active PUSH-PULL lane on the same pin
    turns that pin open-drain: the active lane's 1s stop being driven. Nothing
    flags it.
    ⭐ THE ANCHORS PROVE THAT IS ITS ONLY EFFECT: the class write (K1-K3), no
    `pin_inv` write on a `uio` park pin (K4), and a park word that moves no
    pin (K5). So the overlap is a no-op exactly when every active user of the
    pin is open-drain -- `pin_pp[p]` is 0 whichever lane loads last.
    ⇒ The earlier two rules (explicit refused on ANY overlap, implicit only on
      a push-pull conflict) are gone. `corpus_i2c`'s implicit park on its own
      open-drain SCL is accepted by THIS rule, as is an explicit park on an
      open-drain lane's pin; a push-pull user is refused either way. A missing
      anchor refuses every overlap (unproven is red).
    """
    act = active_pins(lanes, headers)
    for ln in range(N_LANES):
        if ln in headers:
            continue
        p = int(park_pins.get(ln, PARK_PIN))
        if p not in act:
            continue
        users = act[p]
        try:
            ok = park_class.release_only([m for _l, m, _w in users],
                                         engine_text)
        except park_class.ParkClassError as exc:
            raise Reject("parked lane %d's header names pin %d, which active "
                         "lane %d uses, and the overlap cannot be proven "
                         "release-only: %s" % (ln, p, users[0][0], exc))
        if not ok:
            aln, _m, what = next(u for u in users if u[1] != 0)
            raise Reject(
                "parked lane %d's header names pin %d, which active lane %d "
                "uses as its %s in PUSH-PULL mode. A parked header still LOADS "
                "(ruling 1.5): it sets that pin's drive class to open-drain, "
                "so it can turn the active lane's driven 1s into releases "
                "(lanes load in order). Park the lane on a pin no push-pull "
                "lane uses." % (ln, p, aln, what))


def assemble(lanes, headers, park_pins=None, timing_checks=True,
             exempt_as=None):
    """Emit the image. `headers` is {lane: (pin, clkpin, mode, t, dsched, dtol
    [, flags[, order]])}; an action is `(op, pin, level, delay, q[, count])`.

    `park_pins` (SP2) is {lane: pin} for lanes with no program: the header pin
    of each parked lane, default `PARK_PIN`. ⭐ It is an IMAGE property, not a
    protocol one, and the SP2 regression found the shipped images disagree on
    it: the corpus parks every idle lane on pin 1, `run_ckack`/`build_ckread`
    on pins 0/3/4/5 (off the pad-override pins). Without this the front-end
    could not reproduce the ACK image byte for byte.

    `timing_checks=False` is ACCEPTED ONLY THROUGH THE REGISTRY (Wilson,
    SP2/P4): `exempt_as` must name an image `model/nonadmissible.py` registers
    with that permit, or the call is refused before anything is emitted."""
    if not timing_checks:
        try:
            nonadmissible.require(exempt_as, nonadmissible.TIMING_OFF)
        except nonadmissible.ExemptionError as exc:
            raise Reject(str(exc))
    park_pins = park_pins or {}
    lanes, counts = split_counts(lanes)
    # ⛔⛔ DELAY-0 REARM RULING: `assemble` never called `compute_j`, and its
    # 1.6a verdict (`check_queue_slot`) read the same positive-delays-only
    # lane set -- the path that certified the WS2812 3-sub-bit build. Checked
    # here, UNCONDITIONALLY: no registry entry may take a zero spacing (Wilson:
    # the delay-0 build is retired, not declared).
    check_zero_spacing(lanes)
    check_open_drain_bank(headers, park_pins)
    check_park_overlap(lanes, headers, park_pins)
    check_queue_ownership(lanes)
    check_shift_clock_alias(lanes, headers)
    check_receive_pin(lanes, headers)
    check_clocked_hold_delay(lanes, headers)
    prog, base, off = [], {}, ACT_BASE
    # ⛔⛔ A FIELD THAT DOES NOT FIT IS A REFUSAL (WF2). The encoder used to
    # MASK: a header asking for D_sched 434 was emitted as 178, so the image
    # said different numbers than the program. `pe_isa._pack` now raises, and
    # the assembler names it.
    try:
        for ln in sorted(lanes):
            base[ln] = off
            for i, (op, pin, lvl, dly, q) in enumerate(lanes[ln]):
                prog.append(act(op, pin, lvl, dly, count=counts[(ln, i)],
                                q=q))
                off += ACT_BYTES
        lp = off
        prog.append(act(OP_REARM, 0, 0, 500))
        hs = []
        for ln in range(N_LANES):
            if ln in headers:
                pin, clkpin, mode, t, ds, dt = headers[ln][:6]
                flags = header_flags(headers[ln])
                # ⛔ RULING RC4: the order is derived from the lane's program
                # (START/STOP framing = I2C = MSB-first), never left to
                # `hdr()`'s LSB default, which put every I2C byte on the wire
                # reversed
                hs.append(hdr(pin, clkpin, mode, t, flags, ds, dt, base[ln],
                              order=header_order(headers[ln],
                                                 [a[0] for a in lanes[ln]])))
            else:
                pp = park_pins.get(ln, PARK_PIN)
                hs.append(hdr(pp, pp, 0, 500, 0, 200, 240, lp))
    except ValueError as exc:
        raise Reject("a value does not fit its encoding: %s" % exc)
    img = b"".join(hs) + b"".join(prog)
    if len(img) > (1 << AW):
        raise Reject("image is %d bytes, over the %d-byte program store"
                     % (len(img), 1 << AW))
    # ⛔ RULING HDR / CE1 / CE2: the header mode bits, judged on the image as
    # emitted, by the same function the image audit runs (`pe_isa`).
    import gate_j_program as jp
    fp = flag_problems(img, jp.D_STAR)
    if fp:
        raise Reject("; ".join(fp))
    # ⛔⛔ THE ACCEPTED IMAGE IS THE WHOLE STORE (ruling M1). The store has no
    # reset; a short image leaves the rest of it holding whatever powered up,
    # one missing REARM away from running on real pins. Every byte past the
    # program is `pe_isa.STORE_FILLER`, the defined non-driving word.
    assemble.program_bytes = len(img)
    img = full_store(img)
    # ⛔ AFTER THE IMAGE EXISTS, ON THE IMAGE. The floor is derived from the
    # program's own lane set, and the image is the one representation that
    # every route into the chip shares -- deriving it from the tuples instead
    # would be a second decoder of the same program.
    # ⚠ `timing_checks=False` (SP2) skips ONLY the two per-program TIMING
    # verdicts, so a declared non-admissible TRACE image (`corpus_spim` at
    # d = 7, refused by 1.6a) can still be emitted for a byte-identity
    # comparison. Every structural check above has already run. No caller
    # that ships an image passes it; `gate_sp2_frontend` reports the full
    # verdict of every program beside its identity. ⛔ And only for an image
    # REGISTERED for it (`exempt_as`, checked at the top of this function).
    if timing_checks:
        check_mode_floor(img)
        check_queue_slot(img)
    check_i2c_order(img)
    return img


def check_i2c_order(img):
    """A lane that frames with OP_START/OP_STOP is I2C and must be MSB-first
    (ruling RC4). ⛔ On the IMAGE, like the floor above, so a header written
    by any route -- not only by `assemble` -- is held to it; the assembler
    accepts NO exemption (the image audit names its one, census, by name)."""
    probs = i2c_order_problems(img)
    if probs:
        raise Reject("; ".join(probs) + ". Three corpus images shipped this "
                     "way and sent every byte reversed until sigrok read them.")


def check_queue_slot(img):
    """RULING DT-A: condition 1.6a per program -- `r_i <= t_i` on every lane.

    A lane whose worst-case response (from its nominal release, W1's jitter
    included) exceeds its tightest action delay can still be pending when its
    successor is released. The engine holds one job per lane, so that program
    is outside the model every bound here rests on, and outside what TChecker
    can adjudicate (`ovr` reachable). `program_a2.queue_slot` has the exact
    form and why equality is admissible. ⭐ pyRTA when pinned, else our
    recurrence -- which is >= pyRTA on every admissible lane (DT-F), so the CI
    form can only refuse MORE, never accept what pyRTA would refuse.
    """
    src = pinned_pyrta(quiet=True)
    for ln, v in sorted(program_a2.queue_slot(img, src).items(),
                        key=lambda kv: int(kv[0])):
        # ⛔⛔ NO SKIP PATH (Wilson, WF2 round 2, finding 1). This line used to
        # `continue` with the comment "overload: refused by compute_j" -- but
        # `assemble` never calls compute_j, and the None was not only overload:
        # the 1-Wire images (lane 0 chaining hold loads) had NO bound on every
        # lane and were ACCEPTED here. A missing result is red, the same lesson
        # as the delay-0 REARM hole: a lane with no response bound is REFUSED.
        if v["r"] is None:
            raise Reject(
                "lane %s has NO worst-case response bound in this program (%s). "
                "Condition 1.6a needs r_i <= t_i, and a lane with no r_i cannot "
                "be shown to clear its own next release -- so the program is "
                "refused, never certified around the gap."
                % (ln, v.get("why") or "no bound"))
        if not v["ok"]:
            raise Reject(
                "lane %s can still be pending at its own next release: its "
                "worst-case response in THIS program is %d cycles (from its "
                "nominal release, W1 jitter included) against a tightest "
                "action delay of %d. The engine holds one job per lane "
                "(condition 1.6a, r_i <= t_i), so this program is outside "
                "every timing bound -- space that lane's actions to >= %d, "
                "or lighten its neighbours. It is per program."
                % (ln, v["r"], v["T"], v["r"]))


def report(lanes, headers):
    print()
    print("=" * 78)
    print("pe_asm -- assemble and judge a program")
    print("=" * 78)
    full = lanes
    try:
        lanes, _counts = split_counts(lanes)
        owner = check_queue_ownership(lanes)
        check_shift_clock_alias(lanes, headers)
        check_receive_pin(lanes, headers)
        hold = check_clocked_hold_delay(lanes, headers)
        d_min, j = compute_j(lanes)
        img = assemble(full, headers)
    except Reject as e:
        print("  REJECTED: %s" % e)
        return 1
    print("  ACCEPTED")
    print("    image            : %d bytes (program %d, store filler %d)"
          % (len(img), assemble.program_bytes,
             len(img) - assemble.program_bytes))
    print("    SDA hold floor   : d > %d on a clocked open-drain lane "
          "(read from src/pe_engine.v)" % hold)
    for ln, (mode, lo, lag) in sorted(check_mode_floor(img).items()):
        print("    lane %d mode     : clears %s -- worst t_LOW %d cycles "
              "after %d of start delay (this program's own r_i - C)"
              % (ln, mode, lo, lag))
    print("    start-delay basis: %s" % check_mode_floor.basis)
    print("    queue ownership  : %s"
          % (", ".join("q%d -> lane %d" % (q, l)
                       for q, l in sorted(owner.items())) or "no TX consumers"))
    print("    d_min            : %d" % d_min)
    print("    J (computed here, NOT on the chip) : %d" % j)
    print("    ⚠ pyRTA margins are not wired into this cut -- see the")
    print("      module docstring for what the first cut does and does not do.")
    return 0


def _demo_ok():
    lanes = {0: [(OP_SHIFT, 8, 1, 25, 0), (OP_SHIFT, 8, 0, 25, 0),
                 (OP_REARM, 0, 1, 25, 0)],
             2: [(OP_SHIFT, 2, 1, 45, 1), (OP_REARM, 0, 1, 45, 1)]}
    headers = {0: (8, 9, 1, 25, 50, 75), 2: (2, 1, 0, 45, 90, 135)}
    return lanes, headers


def _hold_demo(delay, mode=0, level=1):
    """`_demo_ok` with lane 2's clocked delay, mode and level moved.

    ⭐ ONE BUILDER FOR FIVE ARMS rather than five near-copies: the arms differ
    in exactly the three things the refusal is scoped on, so writing them as
    separate functions would have let one drift and still read as a probe of
    the same thing.
    """
    lanes, headers = _demo_ok()
    lanes[2] = [(OP_SHIFT, 2, level, delay, 1), (OP_REARM, 0, 1, delay, 1)]
    headers[2] = (2, 1, mode, delay, min(2 * delay, 255),
                  min(3 * delay, 255))
    return lanes, headers


def _demo_hold_at():
    """Clocked open-drain AT the boundary: refused, because t_SU;DAT is zero."""
    return _hold_demo(hold_bound.bound())


def _demo_hold_under():
    return _hold_demo(hold_bound.bound() - 1)


def _demo_hold_over():
    """One cycle above: accepted. A refusal that is too wide rejects this."""
    return _hold_demo(hold_bound.bound() + 1)


def _demo_hold_pp():
    """PUSH-PULL below the hold: accepted -- SPI has no t_HD;DAT to miss."""
    return _hold_demo(hold_bound.bound() - 1, mode=1)


def _demo_hold_unclocked():
    """An UNCLOCKED open-drain SHIFT below the hold: REFUSED since ruling U.

    ⛔ IT WAS ACCEPTED HERE, and silicon clamped it to zero hold (the
    `ck_hold_fits` term at the unclocked site). Ruling U widened the silicon
    refusal to this class and retired the clamp, so the assembler refuses it
    too -- otherwise it would accept a program the chip refuses to run.
    """
    return _hold_demo(hold_bound.bound() - 1, level=0)


def _floor_demo(d, heavy):
    """One clocked open-drain lane at `d`, alone or beside three busy lanes.

    ⭐ THE SAME LANE IN TWO PROGRAMS is the whole point: D2's floor belongs to
    the pair (program, lane), so the lane's legality must change with its
    neighbours while its own fields do not move. The neighbours are push-pull
    `OP_LEVEL` lanes on `uo_out` pins with tight EDF keys -- real contention,
    and nothing a refusal elsewhere in this file would object to.
    """
    lanes = {2: [(OP_SHIFT, 2, 1, d, 1), (OP_REARM, 0, 1, d, 1)]}
    headers = {2: (2, 1, 0, d, min(2 * d, 255), min(3 * d, 255))}
    if heavy:
        for ln, pin in ((0, 8), (1, 9), (3, 10)):
            lanes[ln] = [(OP_LEVEL, pin, 0, 21, 0), (OP_LEVEL, pin, 1, 21, 0),
                         (OP_REARM, 0, 1, 21, 0)]
            headers[ln] = (pin, pin, 1, 21, 22, 30)
    return lanes, headers


def _demo_shared_queue():
    lanes, headers = _demo_ok()
    lanes[2] = [(OP_SHIFT, 2, 1, 45, 0),        # queue 0, same as lane 0
                (OP_REARM, 0, 1, 45, 0)]
    return lanes, headers


def _demo_switching():
    lanes, headers = _demo_ok()
    lanes[0] = [(OP_SHIFT, 8, 1, 25, 0), (OP_SHIFT, 8, 0, 25, 3),
                (OP_REARM, 0, 1, 25, 0)]
    return lanes, headers


def _demo_clkalias():
    """1.6x: lane 0 shifts, and names pin 8 as both its data and clock pin."""
    lanes, headers = _demo_ok()
    headers[0] = (8, 8, 1, 25, 50, 75)
    return lanes, headers


def _demo_action_alias():
    """CI5: the HEADER pin is distinct from the clock, but a SHIFT ACTION
    names the clock pin -- the old header check ACCEPTED it; the chip refuses
    it at dispatch (`l_clkpin == a_pin`)."""
    lanes, headers = _demo_ok()
    lanes[0] = [(OP_SHIFT, 9, 1, 25, 0), (OP_REARM, 0, 1, 25, 0)]
    return lanes, headers


def _demo_header_alias_only():
    """CI5: the header pin equals the clock, but every SHIFT drives another
    pin -- the old check REFUSED it; the chip runs it."""
    lanes, headers = _demo_ok()
    headers[0] = (9, 9, 1, 25, 50, 75)
    lanes[0] = [(OP_SHIFT, 8, 1, 25, 0), (OP_REARM, 0, 1, 25, 0)]
    return lanes, headers


def _demo_tight():
    """A program inside the regime where the published J was found unsound."""
    lanes, headers = _demo_ok()
    lanes[0] = [(OP_SHIFT, 8, 1, 12, 0), (OP_REARM, 0, 1, 12, 0)]
    return lanes, headers


def _demo_recv_nonreal():
    """A receive on the reserved index: lane 0 runs OP_SHIFTIN on PIN_NONE."""
    lanes, headers = _demo_ok()
    lanes[0] = [(OP_SHIFTIN, PIN_NONE, 0, 25, 0), (OP_REARM, 0, 1, 25, 0)]
    return lanes, headers


def _demo_readbit_nonreal():
    """The same error on the single-bit sample: OP_READBIT on PIN_NONE."""
    lanes, headers = _demo_ok()
    lanes[0] = [(OP_READBIT, PIN_NONE, 0, 25, 0), (OP_REARM, 0, 1, 25, 0)]
    return lanes, headers


def _demo_arm_nonreal():
    """An ARM on the reserved index: no edge can ever arrive, only a timeout."""
    lanes, headers = _demo_ok()
    lanes[0] = [(OP_ARM, PIN_NONE, 0, 200, 0), (OP_REARM, 0, 1, 25, 0)]
    return lanes, headers


def _demo_spi_target():
    """An SPI TARGET: lane 0 receives, and names PIN_NONE as its CLOCK pin.

    ⛔ THIS MUST BE ACCEPTED. The master supplies SCK, so a target lane has no
    clock of its own -- `clk_real` is what makes that work in silicon. A
    refusal keyed on PIN_NONE anywhere, rather than on the receive's DATA pin,
    would refuse the SPI target outright.
    """
    lanes, headers = _demo_ok()
    lanes[0] = [(OP_SHIFTIN, 2, 0, 25, 0), (OP_REARM, 0, 1, 25, 0)]
    headers[0] = (2, PIN_NONE, 0, 25, 50, 75)
    return lanes, headers


def _demo_noop_pin_none():
    """The half-bit offset idiom: `OP_LEVEL` on PIN_NONE, moving no pin.

    ⛔ THIS MUST BE ACCEPTED TOO. `build_noop` is built on it, and the no-op
    is how a UART receiver lands its first sample at `edge + half`. The refusal
    is about RECEIVES, which have something to sample by definition; a no-op's
    whole purpose is to move nothing.
    """
    lanes, headers = _demo_ok()
    lanes[0] = [(OP_LEVEL, PIN_NONE, 0, 25, 0), (OP_REARM, 0, 1, 25, 0)]
    return lanes, headers


def main() -> int:
    rc = report(*_demo_ok())

    # ---- MUST-FIRES: the rejections have to fire, and NAME the lanes -----
    print()
    print("  --- must-fires: inadmissible programs must be REJECTED ---")
    for name, build, want in (
            ("two lanes on one queue", _demo_shared_queue,
             ("queue 0", "lane 0", "lane 2")),
            ("one lane, two queues", _demo_switching, ("lane 0",)),
            ("d_min below D*", _demo_tight, ("D* = 20", "LANE")),
            ("an ARM on a non-real pin", _demo_arm_nonreal,
             ("lane 0", "OP_ARM", "PIN_NONE")),
            ("a receive on a non-real pin", _demo_recv_nonreal,
             ("lane 0", "OP_SHIFTIN", "PIN_NONE"))):
        try:
            lanes_b = build()[0]
            check_queue_ownership(lanes_b)
            check_receive_pin(lanes_b, build()[1])
            compute_j(lanes_b)
            print("    *** %s was ACCEPTED -- the check does not fire" % name)
            rc = 1
        except Reject as e:
            msg = str(e)
            missing = [w for w in want if w not in msg]
            if missing:
                print("    *** %s fired but did not name %s" % (name, missing))
                rc = 1
            else:
                print("    %s -> REJECTED, naming %s" % (name, ", ".join(want)))
                print("        %s" % msg[:66])


    # ---- MUST-FIRE: the SDA hold floor, from BOTH sides and in SCOPE ------
    # ⛔⛔ THE BOUNDARY IS PROBED AT `SDA_HOLD`, ONE BELOW AND ONE ABOVE, and
    # the equal case is the one that matters: a check written `d < SDA_HOLD`
    # passes the `under` arm and accepts a program whose data reaches the pin
    # on the same cycle the next phase dispatches -- zero setup before the
    # rise. ⭐ AND THE SCOPE IS PRICED AS EXPLICITLY AS THE REFUSAL: a
    # PUSH-PULL clocked lane is SPI and has no `t_HD;DAT` requirement to miss,
    # and an UNCLOCKED SHIFT does not use the hold pipeline at all. Refusing
    # either would reject shipped programs for a hazard they cannot reach.
    print()
    print("  --- must-fire: a clocked open-drain delay must clear the hold ---")
    _hold = hold_bound.bound()
    for name, build, want_reject, want in (
            ("clocked open-drain at d = SDA_HOLD", _demo_hold_at, True,
             ("lane 2", "SHIFT", "SDA data hold")),
            ("... at d = SDA_HOLD - 1", _demo_hold_under, True,
             ("lane 2", "START")),
            ("... at d = SDA_HOLD + 1", _demo_hold_over, False, ()),
            ("a PUSH-PULL clocked lane below the hold", _demo_hold_pp,
             False, ()),
            ("an UNCLOCKED open-drain SHIFT below the hold (U)",
             _demo_hold_unclocked, True, ("lane 2", "UNCLOCKED"))):
        lanes_b, headers_b = build()
        try:
            check_clocked_hold_delay(lanes_b, headers_b)
            got_reject, msg = False, ""
        except Reject as e:
            got_reject, msg = True, str(e)
        if got_reject != want_reject:
            print("    *** %-42s %s" % (name, "REJECTED" if got_reject
                                        else "ACCEPTED"))
            print("        wanted %s (SDA_HOLD = %d)"
                  % ("a rejection" if want_reject else "acceptance", _hold))
            rc = 1
        else:
            missing = [w for w in want if w not in msg]
            if missing:
                print("    *** %-42s REJECTED but did not name %s"
                      % (name, missing))
                rc = 1
            else:
                print("    %-42s %s" % (name, "rejected" if got_reject
                                        else "accepted"))

    # ---- MUST-FIRE: D2's per-program mode floor ---------------------------
    # ⛔⛔ THREE CASES, AND THE FIRST IS THE ONE D2's STATIC HALF LEFT OPEN.
    # d = 20 clears the SDA hold (> 15) so `check_clocked_hold_delay` accepts
    # it -- yet its worst low phase is under every mode's t_LOW, so the
    # assembler used to call it "hold-legal" and wave it through.
    # ⭐ THE OTHER TWO ARE THE SAME LANE AT d = 32 IN TWO PROGRAMS. Searched,
    # not guessed: the lane alone clears Fm+ from d = 30, and beside three busy
    # lanes only from d = 38. A floor that did not depend on the neighbours
    # would give the same verdict for both, which is the shared-constant error
    # ruling S removed from the bench.
    print()
    print("  --- must-fire: D2's mode floor belongs to (program, lane) ---")
    for name, build, want_reject, want in (
            ("hold-legal (d = 20) but under every t_LOW",
             lambda: _floor_demo(20, False), True,
             ("lane 2", "t_LOW", "per program")),
            ("d = 32, the clocked lane ALONE",
             lambda: _floor_demo(32, False), False, ()),
            ("d = 32, the SAME lane beside three busy lanes",
             lambda: _floor_demo(32, True), True, ("lane 2", "per program"))):
        lanes_b, headers_b = build()
        try:
            check_clocked_hold_delay(lanes_b, headers_b)
            assemble(lanes_b, headers_b)
            got_reject, msg = False, ""
        except Reject as e:
            got_reject, msg = True, str(e)
        missing = [w for w in want if w not in msg]
        ok = (got_reject == want_reject) and not missing
        print("    %-46s %s"
              % (name, ("rejected" if got_reject else "accepted") if ok else
                 "*** %s%s" % ("REJECTED" if got_reject else "ACCEPTED",
                               (" but did not name %s" % missing)
                               if missing else "")))
        if not ok:
            rc = 1

    # ---- MUST-FIRE: W7, the mode floor covers UNCLOCKED open-drain frames --
    # ⛔ The certified frame's shape at d = 16 is above the hold, so silicon
    # runs it (and W1 keeps it safe on the wire), but its low phase is under
    # every t_LOW. Until W7 the toolchain accepted it. The certified d = 62
    # frame must still pass, or the floor is too wide.
    print()
    print("  --- must-fire: W7 -- an unclocked open-drain frame clears a mode ---")
    import make_smoke_image as _msi
    for name, d, want_reject, want in (
            ("build_i2cframe(d = 16)", 16, True,
             ("lane 0", "UNCLOCKED", "t_LOW", "per program")),
            ("build_i2cframe(d = 62), the certified frame", 62, False, ())):
        try:
            got = check_mode_floor(full_store(_msi.build_i2cframe(d)))
            got_reject, msg = False, ""
        except Reject as e:
            got, got_reject, msg = None, True, str(e)
        missing = [w for w in want if w not in msg]
        ok = (got_reject == want_reject) and not missing
        print("    %-46s %s" % (name, ("rejected" if got_reject else
                                       "accepted (%s)" % got[0][0]) if ok else
                                 "*** %s%s" % ("REJECTED" if got_reject
                                               else "ACCEPTED",
                                               (" but did not name %s"
                                                % missing) if missing
                                               else "")))
        if not ok:
            rc = 1

    # ---- MUST-FIRE: DT-A, condition 1.6a per program ----------------------
    print()
    print("  --- must-fire: DT-A -- one job per lane (1.6a), per program ---")
    for name, img_b, want_reject in (
            ("ckdense (four dense clocked lanes, W1 binding)",
             full_store(_msi.build_ckod(_msi.CKDENSE_DELAYS)), True),
            ("corpus_i2c", bytes(int(x, 16) for x in open(
                os.path.join(ROOT, "test", "corpus_i2c.hex")).read().split()),
             False)):
        try:
            check_queue_slot(img_b)
            got_reject, msg = False, ""
        except Reject as e:
            got_reject, msg = True, str(e)
        ok = got_reject == want_reject and (not want_reject or "1.6a" in msg)
        print("    %-46s %s" % (name, ("rejected" if got_reject else "accepted")
                                if ok else "*** WRONG (%s)" % msg[:60]))
        if not ok:
            rc = 1

    # ---- MUST-FIRE: the receive refusal's SCOPE, in both directions -------
    # ⛔ A REFUSAL THAT IS TOO WIDE BREAKS SHIPPED MECHANISMS, so the carve-outs
    # are priced as explicitly as the rejection. PIN_NONE is legal as a CLOCK
    # pin (the SPI target depends on it) and as a no-op's action pin (the
    # half-bit offset idiom is built on it).
    print()
    print("  --- must-fire: a receive must name a samplable pin ---")
    for name, build, want_reject, want in (
            ("OP_SHIFTIN on PIN_NONE", _demo_recv_nonreal, True,
             ("lane 0", "OP_SHIFTIN", "PIN_NONE")),
            ("OP_READBIT on PIN_NONE", _demo_readbit_nonreal, True,
             ("lane 0", "OP_READBIT")),
            ("OP_ARM on PIN_NONE", _demo_arm_nonreal, True,
             ("lane 0", "OP_ARM")),
            ("an SPI target: PIN_NONE as the CLOCK pin", _demo_spi_target,
             False, ()),
            ("a no-op: OP_LEVEL on PIN_NONE", _demo_noop_pin_none, False, ())):
        lanes_b, headers_b = build()
        try:
            check_receive_pin(lanes_b, headers_b)
            got_reject, msg = False, ""
        except Reject as e:
            got_reject, msg = True, str(e)
        if got_reject != want_reject:
            print("    *** %-42s %s" % (name,
                                        "REJECTED" if got_reject else "ACCEPTED"))
            print("        wanted %s" % ("a rejection" if want_reject
                                         else "acceptance"))
            rc = 1
        else:
            missing = [w for w in want if w not in msg]
            if missing:
                print("    *** %-42s REJECTED but did not name %s"
                      % (name, missing))
                rc = 1
            else:
                print("    %-42s %s" % (name, "REJECTED, naming the lane and "
                                        "the opcode" if want_reject
                                        else "accepted, as it must be"))

    # ---- MUST-FIRE: a single-buffer build must not get a certificate -----
    # ⛔ THE SCOPED CLAIM IS CONDITIONAL ON SPL = 2, measured: the stall cliff
    # is d = 19 with the double buffer and d = 25 without it, straddling
    # D* = 20. A program certified against an SPL = 1 build would carry a
    # guarantee that build does not provide.
    # ---- 1.6x, BOTH WAYS ------------------------------------------------
    # ⛔ A GUARD SEEN ONLY TO PASS HAS UNKNOWN STRENGTH, and this one is new:
    # it is checked on a program that violates it AND on one that does not, so
    # a check that rejected everything would be caught too.
    print()
    print("  --- must-fire: 1.6x, a SHIFT lane whose clock pin is its data pin ---")
    for name, build, want_reject, want in (
            ("clkpin == pin on a shifting lane", _demo_clkalias, True,
             ("lane 0", "pin 8", "OP_SHIFT")),
            ("the same program with a distinct clock pin", _demo_ok, False,
             ()),
            # ⭐ CI5: the check follows the ACTION's pin, as the chip does
            ("a SHIFT ACTION on the clock pin (header distinct)",
             _demo_action_alias, True, ("lane 0", "pin 9", "OP_SHIFT")),
            ("a header alias whose SHIFTs drive another pin",
             _demo_header_alias_only, False, ())):
        lanes_b, headers_b = build()
        try:
            check_shift_clock_alias(lanes_b, headers_b)
            got_reject = False
            msg = ""
        except Reject as e:
            got_reject = True
            msg = str(e)
        if got_reject != want_reject:
            print("    *** %-44s %s" % (name, "ACCEPTED" if not got_reject
                                        else "REJECTED"))
            print("        wanted %s" % ("a rejection" if want_reject
                                         else "acceptance"))
            rc = 1
        else:
            missing = [w for w in want if w not in msg]
            if missing:
                print("    *** %-44s REJECTED but did not name %s"
                      % (name, missing))
                rc = 1
            else:
                print("    %-44s %s" % (name, "REJECTED, naming the lane and "
                                        "the pin" if want_reject
                                        else "accepted"))
                if want_reject:
                    print("        %s" % msg[:76])

    print()
    print("  --- must-fire: certifying against an SPL = 1 build ---")
    good = _demo_ok()[0]
    try:
        compute_j(good, spl=1)
        print("    *** ACCEPTED at SPL = 1 -- the condition does not fire")
        rc = 1
    except Reject as e:
        m = str(e)
        need = ["SPL = 2", "19", "25"]
        gap = [w for w in need if w not in m]
        if gap:
            print("    *** fired but did not name %s" % gap)
            rc = 1
        else:
            print("    REJECTED, naming the depth and both measured cliffs")
            print("        %s" % m[:66])
    # ⭐ and the SAME program must still certify at SPL = 2, or the condition
    # is just a blanket refusal wearing a reason.
    try:
        d_min, j = compute_j(good, spl=2)
        print("    the same program at SPL = 2: d_min = %d -> J = %d  ok"
              % (d_min, j))
    except Reject as e:
        print("    *** the same program is refused at SPL = 2 too: %s" % e)
        rc = 1

    # ---- MUST-FIRE: an I2C lane is MSB-first (ruling RC4) ------------------
    # ⭐ BOTH SIDES: the image a header-writer produced LSB-first must be
    # REFUSED, and the same program through `assemble` must come out MSB and
    # pass -- a check that refused both would be a blanket ban on START.
    print()
    print("  --- must-fire: a START/STOP lane must be MSB-first (RC4) ---")
    from pe_isa import ACT_BASE as _AB, ORDER_LSB as _LSB, OP_START as _S, \
        OP_STOP as _P, lane_programs as _lp
    i2c = [act(_S, 2, 0, 70), act(OP_SHIFT, 2, 1, 70), act(_P, 2, 1, 70),
           act(OP_REARM, 0, 1, 70)]
    park = _AB + len(i2c) * ACT_BYTES
    bad = full_store(b"".join(
        [hdr(2, 1, 0, 70, 0, 140, 210, _AB, order=_LSB)]
        + [hdr(p, p, 0, 500, 0, 200, 240, park) for p in (0, 3, 4, 5)])
        + b"".join(i2c) + act(OP_REARM, 0, 0, 500))
    try:
        check_i2c_order(bad)
        print("    *** an LSB-first START/STOP lane was ACCEPTED")
        rc = 1
    except Reject as e:
        ok = "lane 0" in str(e) and "LSB-first" in str(e)
        print("    an LSB-first START/STOP lane -> REJECTED%s"
              % ("" if ok else " *** but did not name lane 0 / LSB-first"))
        rc |= 0 if ok else 1
    order = _lp(full_store(b"".join(
        [hdr(2, 1, 0, 70, 0, 140, 210, _AB,
             order=order_for([_S, OP_SHIFT, _P, OP_REARM]))]
        + [hdr(p, p, 0, 500, 0, 200, 240, park) for p in (0, 3, 4, 5)])
        + b"".join(i2c) + act(OP_REARM, 0, 0, 500)))[0][0]["order"]
    print("    the same lane, order derived by order_for: %s  %s"
          % ("MSB" if order else "LSB", "ok" if order else "*** WRONG"))
    rc |= 0 if order else 1

    # ---- MUST-FIRES: RULING HDR -- the header mode bits, both ways --------
    # ⭐ Each arm goes through `assemble`, the path a user's program takes, and
    # each refusal must NAME what it refused; the accepted arms are the ones
    # CE1 and CE2 exist to allow, so a check that refused them would be a ban.
    print()
    print("  --- must-fire: header mode bits (HDR / CE1 / CE2) ---")
    import gate_j_program as _jp

    def _one(lane_acts, header):
        return assemble({0: lane_acts}, {0: header})

    def _clocked(pin, dly):
        return [(OP_SHIFT, pin, 1, dly, 0), (OP_REARM, 0, 1, dly, 0)]

    for name, lane_acts, header, want in (
            ("HALF_HIGH Fm I2C at d = 82", _clocked(2, 82),
             (2, 1, 0, 82, 164, 246, FLAG_HALF_HIGH), None),
            ("HALF_HIGH with d/2 under D*", _clocked(2, 38),
             (2, 1, 0, 38, 76, 114, FLAG_HALF_HIGH),
             ("HALF_HIGH", "D* = %d" % _jp.D_STAR)),
            ("CLK_INV on a uo_out SPI clock", _clocked(10, 25),
             (10, 9, 1, 25, 50, 75, FLAG_CLK_INV), None),
            ("CLK_INV on an open-drain lane", _clocked(2, 82),
             (2, 1, 0, 82, 164, 246, FLAG_CLK_INV), ("CLK_INV", "OPEN-DRAIN")),
            ("CLK_INV on a uio clock", _clocked(3, 25),
             (3, 2, 1, 25, 50, 75, FLAG_CLK_INV), ("CLK_INV", "uio"))):
        try:
            _one(lane_acts, header)
            ok = want is None
            print("    %-36s accepted%s" % (name, "" if ok else
                                             "  *** should be REJECTED"))
        except Reject as e:
            msg = str(e)
            ok = want is not None and all(w in msg for w in want)
            print("    %-36s REJECTED%s" % (name, "" if ok else
                  "  *** %s" % ("should be accepted: " + msg[:50]
                                if want is None else "did not name %s" % (want,))))
        rc |= 0 if ok else 1
    # a RESERVED bit cannot be written through `hdr()` (it refuses), so it is
    # PLANTED in an image the way a corrupt load would carry it
    img = bytearray(_one(_clocked(10, 25), (10, 9, 1, 25, 50, 75, 0)))
    img[2] |= 0x08                         # flags bit 2 of lane 0's header
    rp = flag_problems(bytes(img), _jp.D_STAR)
    ok = any("RESERVED" in p and "lane 0" in p for p in rp)
    print("    %-36s %s" % ("a planted RESERVED flag bit",
                            "REFUSED" if ok else "*** NOT REFUSED"))
    rc |= 0 if ok else 1
    try:
        hdr(10, 9, 1, 25, 0x4, 50, 75, ACT_BASE)
        print("    hdr() with a reserved bit             *** ACCEPTED")
        rc = 1
    except ValueError:
        print("    hdr() with a reserved bit             refused at the encoder")

    # ---- MUST-FIRE: 1.6s, an open-drain lane's pins are `uio` (CE5) -------
    # ⭐ BOTH SIDES: the clockless open-drain lane CE5 first wrote (PIN_NONE
    # clock) must be REFUSED, as silicon refuses it; the same lane with a
    # real `uio` clock must be accepted, or the check is a ban on 1-Wire.
    print()
    print("  --- must-fire: 1.6s -- an open-drain lane names uio pins only ---")
    ow = [(OP_SHIFT, 2, 0, 150, 0, 7), (OP_SHIFTIN, 3, 0, 900, 0, 8),
          (OP_REARM, 0, 1, 900, 0, 8)]
    for name, header, want_reject in (
            ("open-drain, clock PIN_NONE", (2, PIN_NONE, 0, 150, 255, 255),
             True),
            ("open-drain, data on uo_out", (8, 4, 0, 150, 255, 255), True),
            ("open-drain, clock on uio[4]", (2, 4, 0, 150, 255, 255), False)):
        try:
            assemble({0: ow}, {0: header})
            got, msg = False, ""
        except Reject as e:
            got, msg = True, str(e)
        ok = got == want_reject and (not got or "1.6s" in msg)
        print("    %-36s %s" % (name, ("REJECTED (1.6s)" if got else "accepted")
                                if ok else "*** WRONG: %s" % (msg[:50] or
                                                             "accepted")))
        rc |= 0 if ok else 1

    # ---- MUST-FIRE: SP2/P3, a park pin on an active lane's pin -----------
    # ⭐ ONE RULE, BOTH SIDES (Wilson): an overlap is accepted iff it is
    # release-only, proven from the RTL anchors -- explicit or implicit alike.
    # The 1-Wire lane is OPEN-DRAIN, so an explicit park on its DQ pin, or on
    # its sense pin (an ACTION pin, the case a header-only check would miss),
    # is release-only and ACCEPTED; a park, explicit or the implicit default,
    # on a PUSH-PULL lane's pin is REFUSED; and with an anchor gone even the
    # open-drain overlap is refused (unproven is red).
    print()
    print("  --- must-fire: SP2/P3 -- a park overlap must be release-only ---")
    pp_lane = {0: [(OP_SHIFT, 1, 1, 25, 0, 7), (OP_REARM, 0, 1, 25, 0, 8)]}
    for name, lanes_b, headers_b, park, want_reject in (
            ("parked off the 1-Wire pins (0/5/6/7)", {0: ow},
             {0: (2, 4, 0, 150, 255, 255)}, {1: 0, 2: 5, 3: 6, 4: 7}, False),
            ("open-drain release: lane 3 on the SENSE pin 3", {0: ow},
             {0: (2, 4, 0, 150, 255, 255)}, {1: 0, 2: 5, 3: 3, 4: 7}, False),
            ("open-drain release: lane 1 on DQ pin 2", {0: ow},
             {0: (2, 4, 0, 150, 255, 255)}, {1: 2}, False),
            ("explicit park on a PUSH-PULL lane's uio 1", pp_lane,
             {0: (1, 0, 1, 25, 50, 75)}, {1: 1, 2: 5, 3: 6, 4: 7}, True),
            ("default park pin 1 under a PUSH-PULL lane on uio 1", pp_lane,
             {0: (1, 0, 1, 25, 50, 75)}, None, True)):
        try:
            assemble(lanes_b, headers_b, park_pins=park)
            got, msg = False, ""
        except Reject as e:
            got, msg = True, str(e)
        ok = got == want_reject and (not got or "PUSH-PULL mode" in msg)
        print("    %-50s %s" % (name, ("REJECTED" if got else "accepted")
                                if ok else "*** WRONG: %s" % (msg[:50] or
                                                             "accepted")))
        rc |= 0 if ok else 1
    with open(park_class.ENGINE, encoding="utf-8") as fh:
        no_k5 = fh.read().replace("OP_ARM, OP_REARM: ;", "OP_ARM: ;")
    try:
        check_park_overlap(split_counts({0: ow})[0],
                           {0: (2, 4, 0, 150, 255, 255)}, {1: 2}, no_k5)
        got, msg = False, ""
    except Reject as e:
        got, msg = True, str(e)
    ok = got and "K5" in msg
    print("    %-50s %s" % ("anchor K5 removed: the DQ-pin park",
                            "REJECTED (unproven)" if ok
                            else "*** WRONG: %s" % (msg[:50] or "accepted")))
    rc |= 0 if ok else 1

    # ---- MUST-FIRE: a field that does not fit is refused, never masked ------
    print()
    print("  --- must-fire: an oversize header field is refused (was masked) ---")
    try:
        assemble({0: [(OP_LEVEL, 8, 0, 434, 0), (OP_REARM, 0, 1, 434, 0)]},
                 {0: (8, PIN_NONE, 1, 434, 434, 868)})
        got, msg = False, ""
    except Reject as e:
        got, msg = True, str(e)
    ok = got and "does not fit" in msg
    print("    %-50s %s" % ("D_sched 434 / D_tol 868 in 8-bit fields",
                            "REJECTED" if ok else "*** WRONG: %s"
                            % (msg[:60] or "accepted (masked to 178 / 100)")))
    rc |= 0 if ok else 1

    # ---- MUST-FIRE: chained hold loads, and 1.6a's no-skip (WF2 round 2) ----
    # ⭐ The 1-Wire shape: an open-drain lane with a real clock pin whose
    # unclocked level-0 SHIFTs follow one another (each loads the SDA hold).
    # At a 100-cycle gap the induction holds (HS + 2 + (r - C) <= gap) and the
    # lane is BOUNDED; at 25 the next loading job can itself be W1-delayed, the
    # lane has NO bound, and 1.6a must REFUSE it -- it used to skip it.
    print()
    print("  --- must-fire: chained hold loads / 1.6a refuses an unbounded lane ---")
    # ⭐ THE EDGE (Wilson's condition 3): the inequality's own boundary, so an
    # off-by-one in it -- the HC1 bug class -- is caught. At gap 33 the window
    # is EXACTLY met (HS 18 + HOLD_PICK_LAG 2 + (r 16 - C 3) = 33, asserted
    # below from the live analysis, not typed): accepted; at 32 refused.
    import program_a2 as _pa
    from bursty import C_SHIPPED as _C
    edge_lanes = {0: [(OP_SHIFT, 2, 0, 33, 0, 7), (OP_SHIFT, 2, 0, 33, 0, 7),
                      (OP_LEVEL, PIN_NONE, 0, 100, 0),
                      (OP_REARM, 0, 1, 100, 0)]}
    edge_img = assemble(edge_lanes, {0: (2, 4, 0, 150, 255, 255)},
                        park_pins={1: 0, 2: 5, 3: 6, 4: 7})
    edge_r = _pa.queue_slot(edge_img, None)["0"]["r"]
    edge_w = _pa._hs() + _pa.HOLD_PICK_LAG + (edge_r - _C)
    ok = edge_w == 33
    print("    %-50s %s" % ("edge: HS + HOLD_PICK_LAG + (r - C) at gap 33",
                            ("= %d, exactly the gap" % edge_w) if ok
                            else "*** WRONG: = %d, not 33 -- re-derive the "
                                 "edge pair" % edge_w))
    rc |= 0 if ok else 1
    for name, gap, want_reject in (("chained hold loads 100 apart", 100, False),
                                   ("chained hold loads 25 apart", 25, True),
                                   ("edge: gap == window + lateness (33)", 33,
                                    False),
                                   ("edge: gap == window + lateness - 1 (32)",
                                    32, True)):
        lanes_b = {0: [(OP_SHIFT, 2, 0, gap, 0, 7), (OP_SHIFT, 2, 0, gap, 0, 7),
                       (OP_LEVEL, PIN_NONE, 0, 100, 0),
                       (OP_REARM, 0, 1, 100, 0)]}
        try:
            assemble(lanes_b, {0: (2, 4, 0, 150, 255, 255)},
                     park_pins={1: 0, 2: 5, 3: 6, 4: 7})
            got, msg = False, ""
        except Reject as e:
            got, msg = True, str(e)
        ok = got == want_reject and (not got or "NO worst-case response "
                                     "bound" in msg)
        print("    %-50s %s" % (name, ("REJECTED (no bound)" if got
                                        else "accepted (bounded)")
                                if ok else "*** WRONG: %s" % (msg[:70] or
                                                             "accepted")))
        rc |= 0 if ok else 1

    # ---- MUST-FIRE: the delay-0 REARM ruling (Wilson, must fix before lock) --
    # ⭐ THE EXACT CASE THAT WAS ACCEPTED: the WS2812 3-sub-bit lane, SHIFT-only
    # at d = 21 on uo_out[0], its loop closed by a delay-0 REARM, beside four
    # push-pull lanes toggling at d = 20 ("J 1" before; its SHIFT writebacks
    # were 3..139 cycles apart and the wire stream was not the feed). Its
    # control -- the same program with the REARM at 21 -- must be ACCEPTED, so
    # the refusal is the zero spacing and nothing else. Then the rule's two
    # sides: a delay-0 non-ARM refused (in `compute_j` too), a delay-0 ARM
    # accepted; and with the ARM's anchors gone the ARM is refused (unproven).
    print()
    print("  --- must-fire: delay-0 REARM -- a zero release spacing is refused ---")
    sub3 = ws2812_sub3

    arm0 = {0: [(OP_ARM, 3, 0, 0, 0), (OP_LEVEL, PIN_NONE, 0, 25, 0),
                (OP_SHIFTIN, 3, 0, 25, 0, 8), (OP_REARM, 0, 1, 25, 0)]}
    arm0_h = {0: (3, PIN_NONE, 1, 25, 50, 75)}
    lvl0 = {0: [(OP_LEVEL, 1, 1, 25, 0), (OP_LEVEL, 1, 0, 0, 0),
                (OP_REARM, 0, 1, 25, 0)]}
    lvl0_h = {0: (1, PIN_NONE, 1, 25, 50, 75)}
    for name, (lanes_b, headers_b), want_reject in (
            ("3-sub-bit d=21 + REARM d=0, four d=20 lanes", sub3(0), True),
            ("control: the same with the REARM at d=21", sub3(21), False),
            ("a delay-0 LEVEL mid-loop", (lvl0, lvl0_h), True),
            ("a delay-0 ARM (no timeout) before a d=25 loop",
             (arm0, arm0_h), False)):
        try:
            assemble(lanes_b, headers_b)
            got, msg = False, ""
        except Reject as e:
            got, msg = True, str(e)
        ok = got == want_reject and (not got or "ZERO release spacing" in msg)
        print("    %-50s %s" % (name, ("REJECTED" if got else "accepted")
                                if ok else "*** WRONG: %s" % (msg[:60] or
                                                             "accepted")))
        rc |= 0 if ok else 1
    # compute_j on its own (the `report` path) refuses it too
    try:
        compute_j(split_counts(sub3(0)[0])[0])
        got, msg = False, ""
    except Reject as e:
        got, msg = True, str(e)
    ok = got and "ZERO release spacing" in msg
    print("    %-50s %s" % ("compute_j on the 3-sub-bit program",
                            "REJECTED" if ok else "*** WRONG: %s"
                            % (msg[:60] or "accepted")))
    rc |= 0 if ok else 1
    with open(zero_spacing.ENGINE, encoding="utf-8") as fh:
        no_e2 = fh.read().replace("& ~(armed_n[i] & notmo_n[i]);", "")
    try:
        check_zero_spacing(split_counts(arm0)[0], no_e2)
        got, msg = False, ""
    except Reject as e:
        got, msg = True, str(e)
    ok = got and "ZERO release spacing" in msg
    print("    %-50s %s" % ("anchor E2 removed: the delay-0 ARM",
                            "REJECTED (exemption unproven)" if ok
                            else "*** WRONG: %s" % (msg[:60] or "accepted")))
    rc |= 0 if ok else 1
    # ⭐ THE IMAGE THE OLD ASSEMBLER EMITTED, judged by the image-side screens:
    # emitted with the zero-spacing check stubbed out (exactly the old
    # behaviour), then N1's `refill_dmin` must read 0 and `program_a2.lane_set`
    # (1.6a's input) must refuse to build a lane set from it.
    real_find = zero_spacing.find
    zero_spacing.find = lambda *_a, **_k: []
    try:
        old_img = assemble(*sub3(0))
    except Reject as e:
        old_img, why = None, str(e)
    finally:
        zero_spacing.find = real_find
    import gate_admissible_images as gai
    if old_img is None:
        print("    *** WRONG: the old assembler's image could not be emitted "
              "(%s)" % why[:60])
        rc |= 1
    else:
        dm = gai.refill_dmin(old_img)
        ok = dm == 0
        print("    %-50s %s" % ("old image: N1 refill_dmin",
                                "0 (PORT)" if ok else "*** WRONG: %s" % dm))
        rc |= 0 if ok else 1
        try:
            program_a2.lane_set(old_img)
            got, msg = False, ""
        except zero_spacing.ZeroSpacingError as e:
            got, msg = True, str(e)
        print("    %-50s %s" % ("old image: program_a2.lane_set (1.6a input)",
                                "REFUSED" if got else "*** WRONG: built"))
        rc |= 0 if got else 1

    # ---- MUST-FIRE: SP2/P4, timing_checks=False only through the registry --
    print()
    print("  --- must-fire: SP2/P4 -- timing_checks=False needs a registry entry ---")
    import pe_proto as _pp
    sl, sh, spark = _pp.spi_fram()
    for name, kw, want_reject in (
            ("corpus_spim, registered (exempt_as)",
             {"exempt_as": "corpus_spim.hex"}, False),
            ("the same program, no name", {}, True),
            ("the same program as an unregistered name",
             {"exempt_as": "corpus_i2c.hex"}, True),
            ("a registered name WITHOUT that permit (ckdense: no_rta only)",
             {"exempt_as": "ckdense_image.hex"}, True)):
        try:
            assemble(sl, sh, park_pins=spark, timing_checks=False, **kw)
            got, msg = False, ""
        except Reject as e:
            got, msg = True, str(e)
        ok = got == want_reject and (not got or "TIMING_EXEMPT" in msg)
        print("    %-62s %s" % (name, ("REJECTED" if got else "accepted")
                                if ok else "*** WRONG: %s" % (msg[:50] or
                                                             "accepted")))
        rc |= 0 if ok else 1
    print()
    print("=" * 78)
    print("  pe_asm: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
