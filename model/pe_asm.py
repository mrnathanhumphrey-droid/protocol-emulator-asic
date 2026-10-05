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

⚠ FIRST CUT, AND WHAT IS NOT HERE YET: a protocol front-end (programs are given
as lane/action tuples, not as a protocol description), and the full 23-condition
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

from make_smoke_image import (            # noqa: E402
    ACT_BASE, ACT_BYTES, AW, N_LANES, OP_LEVEL, OP_READBIT, OP_REARM,
    OP_SHIFT,
    OP_SHIFTIN, PIN_NONE, act, hdr,
)

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
    declares it on all five lanes while running only `OP_LEVEL`. That image is
    the measurement base for T1's per-lane `J` and for Theorem 3's 35
    port-feasible cells; refusing it for a hazard it cannot reach would
    invalidate both and buy nothing.

    ⛔ THE CHIP ALSO REFUSES IT (1.6x in silicon), at DISPATCH rather than at
    header load: at header-load time the chip cannot know whether a lane's
    program contains a SHIFT, because actions are fetched lazily. Here the
    whole program is visible, so the refusal is static and names the lane.
    """
    for ln in sorted(lanes):
        if not any(op == OP_SHIFT for (op, _p, _l, _d, _q) in lanes[ln]):
            continue
        if ln not in headers:
            continue
        pin, clkpin = headers[ln][0], headers[ln][1]
        if pin == clkpin:
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
    names = {OP_SHIFTIN: "OP_SHIFTIN", OP_READBIT: "OP_READBIT"}
    for ln in sorted(lanes):
        for (op, pin, _lvl, _dly, _q) in lanes[ln]:
            if op not in names:
                continue
            if pin < N_PINS:
                continue
            raise Reject(
                "lane %d executes %s on pin %d, which is not a real pin "
                "(N_PINS = %d, so only 0..%d exist%s). A receive with nothing "
                "to sample cannot mean anything, and an out-of-range read is "
                "X in simulation and an UNSPECIFIED synthesised value in "
                "silicon. PIN_NONE is legal as a CLOCK pin (an SPI target "
                "needs that) and as a no-op's action pin, but not as the pin a "
                "receive samples."
                % (ln, names[op], pin, N_PINS, N_PINS - 1,
                   "; %d is PIN_NONE" % PIN_NONE if pin == PIN_NONE else ""))


# ---------------------------------------------------------------------------
# 1.6t: the program's J, computed HERE and not on the chip
# ---------------------------------------------------------------------------
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


def assemble(lanes, headers):
    """Emit the image. `headers` is {lane: (pin, clkpin, mode, t, dsched, dtol)}."""
    check_queue_ownership(lanes)
    check_shift_clock_alias(lanes, headers)
    check_receive_pin(lanes, headers)
    prog, base, off = [], {}, ACT_BASE
    for ln in sorted(lanes):
        base[ln] = off
        for (op, pin, lvl, dly, q) in lanes[ln]:
            prog.append(act(op, pin, lvl, dly, count=8, q=q))
            off += ACT_BYTES
    lp = off
    prog.append(act(OP_REARM, 0, 0, 500))
    hs = []
    for ln in range(N_LANES):
        if ln in headers:
            pin, clkpin, mode, t, ds, dt = headers[ln]
            hs.append(hdr(pin, clkpin, mode, t, 2, ds, dt, base[ln]))
        else:
            hs.append(hdr(1, 1, 0, 500, 2, 200, 240, lp))
    img = b"".join(hs) + b"".join(prog)
    if len(img) > (1 << AW):
        raise Reject("image is %d bytes, over the %d-byte program store"
                     % (len(img), 1 << AW))
    return img


def report(lanes, headers):
    print()
    print("=" * 78)
    print("pe_asm -- assemble and judge a program")
    print("=" * 78)
    try:
        owner = check_queue_ownership(lanes)
        check_shift_clock_alias(lanes, headers)
        check_receive_pin(lanes, headers)
        d_min, j = compute_j(lanes)
        img = assemble(lanes, headers)
    except Reject as e:
        print("  REJECTED: %s" % e)
        return 1
    print("  ACCEPTED")
    print("    image            : %d bytes" % len(img))
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
             ())):
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
    print()
    print("=" * 78)
    print("  pe_asm: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
