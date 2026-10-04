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
    ACT_BASE, ACT_BYTES, AW, N_LANES, OP_REARM, OP_SHIFT, act, hdr,
)

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
    ⭐ Only actions that CONSUME are considered: `OP_SHIFT` reads `l_data`, so a
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
# 1.6t: the program's J, computed HERE and not on the chip
# ---------------------------------------------------------------------------
def compute_j(lanes):
    """`J` from the program's minimum inter-action delay, per gate_j_program."""
    import gate_j_program as jp
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
    # (U = k*C/(d+C) <= 1, so d >= 8). Every dispatched action must also be
    # REFILLED through ONE shared fetch port, which needs d >= k*L_REFILL.
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


def _demo_tight():
    """A program inside the regime where the published J was found unsound."""
    lanes, headers = _demo_ok()
    lanes[0] = [(OP_SHIFT, 8, 1, 12, 0), (OP_REARM, 0, 1, 12, 0)]
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
            ("d_min below D*", _demo_tight, ("D* = 20", "LANE"))):
        try:
            lanes_b = build()[0]
            check_queue_ownership(lanes_b)
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
    print()
    print("=" * 78)
    print("  pe_asm: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
