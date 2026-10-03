"""Build a tiny program image and emit it as a Verilog memory file.

⛔⛔ THIS EXISTS BECAUSE "IT ELABORATES" IS NOT EVIDENCE. This project has
already recorded a gate-level sim passing for weeks on a stub with ZERO
flip-flops -- the flow was broken the whole time and nothing noticed, because
the artefact was too simple to reach the broken path. So the engine gets a
program that makes it DO something, and the test asserts on PIN MOVEMENT.

⭐ The image layout here is the SPEC, hand-assembled, so if the RTL's unpacking
disagrees with the documented layout the simulation says so rather than both
sides drifting together. ⛔ A second implementation by the same author is not an
independent witness -- but a hand-assembled image against a generated unpacker
CAN diverge, which is what makes the check worth running.

HEADER, 6 bytes, MSB-aligned in 48 bits:
    [47:44] pin        [43:40] clkpin     [39:30] t
    [29:26] C_i        [25:18] D_sched    [17:10] D_tol
    [9:2]   base       [1:0]   spare
ACTION, 3 bytes, MSB-aligned in 24 bits:
    [23:21] opcode     [20:17] pin        [16] level
    [15:6]  delay      [5:2]   count      [1:0] spare
"""

from __future__ import annotations

import os
import sys

N_LANES, AW, DLY_W, PINW, CW, D_W = 5, 8, 10, 4, 4, 8
HDR_BITS = PINW * 2 + 1 + DLY_W + CW + D_W + D_W + AW   # +1 = drive mode
HDR_BYTES = (HDR_BITS + 7) // 8
ACT_W = 3 + PINW + 1 + DLY_W + 4
ACT_BYTES = (ACT_W + 7) // 8
ACT_BASE = N_LANES * HDR_BYTES

OP_LEVEL, OP_SHIFT, OP_SHIFTIN, OP_READBIT = 0, 1, 2, 3
OP_START, OP_STOP, OP_ARM, OP_REARM = 4, 5, 6, 7

# pin indices: 0..7 = uio, 8..11 = uo_out[0..3]
UO0, UO1, UO2, UO3 = 8, 9, 10, 11


def hdr(pin, clkpin, mode, t, c, dsched, dtol, base) -> bytes:
    """`mode`: 1 = push-pull, 0 = open-drain. ⛔ open-drain is only MEANINGFUL on
    a `uio` pin -- `uo_out` has no enable, so an open-drain lane there drives
    low once and sticks."""
    w = 0
    for val, width in ((pin, PINW), (clkpin, PINW), (mode, 1), (t, DLY_W), (c, CW),
                       (dsched, D_W), (dtol, D_W), (base, AW)):
        w = (w << width) | (val & ((1 << width) - 1))
    w <<= (HDR_BYTES * 8 - HDR_BITS)            # MSB-align, spare at the bottom
    return w.to_bytes(HDR_BYTES, "big")


def act(op, pin, level, delay, count=0) -> bytes:
    w = 0
    for val, width in ((op, 3), (pin, PINW), (level, 1), (delay, DLY_W),
                       (count, 4)):
        w = (w << width) | (val & ((1 << width) - 1))
    w <<= (ACT_BYTES * 8 - ACT_W)
    return w.to_bytes(ACT_BYTES, "big")


def build():
    """Lane 0 toggles uo_out[0]; lane 1 toggles uo_out[1] at a different rate.

    ⭐ TWO LIVE LANES ON PURPOSE. `M-PREFETCH-STALE` is VACUOUS with one live
    lane -- the previous winner IS the current winner, so a stale prefetch word
    is coincidentally correct. Two lanes at different rates make the scheduler
    actually alternate, which is the only condition under which a stale
    prefetch produces a wrong pin.
    """
    prog = []
    # lane 0: drive uo_out[0] low, then high, then re-arm. delay in cycles.
    l0 = ACT_BASE
    prog.append(act(OP_LEVEL, UO0, 0, 20))
    prog.append(act(OP_LEVEL, UO0, 1, 20))
    prog.append(act(OP_REARM, 0, 1, 20))        # level=1 => loop to base
    # lane 1: a different period, so the EDF winner changes hands
    l1 = l0 + 3 * ACT_BYTES
    prog.append(act(OP_LEVEL, UO1, 0, 31))
    prog.append(act(OP_LEVEL, UO1, 1, 31))
    prog.append(act(OP_REARM, 0, 1, 31))
    # lanes 2..4 parked on a NON-looping re-arm: live, but never move a pin
    l2 = l1 + 3 * ACT_BYTES
    prog.append(act(OP_REARM, 0, 0, 500))

    headers = [
        hdr(UO0, UO0, 1, 20, 2, 40, 60, l0),       # lane 0
        hdr(UO1, UO1, 1, 31, 2, 60, 90, l1),       # lane 1
        hdr(0, 0, 0, 500, 2, 200, 240, l2),
        hdr(1, 1, 0, 500, 2, 200, 240, l2),
        hdr(2, 2, 0, 500, 2, 200, 240, l2),
    ]
    img = b"".join(headers) + b"".join(prog)
    assert len(headers[0]) == HDR_BYTES
    return img


def build_stress(d0: int, d1: int):
    """A program whose inter-action delays are SHORT ENOUGH TO STRESS THE
    REFILL PATH. This exists because the default program cannot measure J.

    ⛔⛔ THE DEFAULT PROGRAM MEASURES NOTHING ABOUT JITTER, AND THAT WAS FOUND
    THE HARD WAY. Its delays are 20 and 31 cycles against a refill latency of
    about 4, so the prefetcher always wins the race -- with ONE buffer or TWO.
    Measured steady-state stall is 0 either way; the `J = 5` the bench has been
    reporting all along is entirely a COLD START, and the `M_BUF_SWAP` mutant
    (which removes the double buffer's swap) SURVIVED against it. A bench that
    cannot distinguish the design from the mutant cannot evidence the design.

    ⭐ WHERE THE DOUBLE BUFFER CAN SHOW UP, derived rather than guessed. With a
    single buffer the slot frees at writeback and the refill must finish before
    the NEXT DISPATCH, a window of `d`. With two buffers the head is already
    valid at the swap, and the refill of the freed slot has until the dispatch
    AFTER next -- about `2d`. So for a refill latency `L`:

        single buffer stalls when   d < L
        double buffer stalls when  2d < L

    The design is therefore distinguishable from its mutant only for
    `L/2 <= d < L`, which for L ~ 6 is `d` in [3, 6). At d = 20 both are clean
    and at d = 1 both stall -- in neither case does the measurement say
    anything about the buffering.
    """
    prog = []
    l0 = ACT_BASE
    prog.append(act(OP_LEVEL, UO0, 0, d0))
    prog.append(act(OP_LEVEL, UO0, 1, d0))
    prog.append(act(OP_REARM, 0, 1, d0))
    l1 = l0 + 3 * ACT_BYTES
    prog.append(act(OP_LEVEL, UO1, 0, d1))
    prog.append(act(OP_LEVEL, UO1, 1, d1))
    prog.append(act(OP_REARM, 0, 1, d1))
    l2 = l1 + 3 * ACT_BYTES
    prog.append(act(OP_REARM, 0, 0, 500))
    # ⛔ D_sched/D_tol are scaled with the delay: leaving them at the default
    # 40/60 against a 5-cycle period would make every lane permanently late and
    # the run would be measuring an OVERLOADED system, not a jitter mechanism.
    headers = [
        hdr(UO0, UO0, 1, d0, 2, 2 * d0, 3 * d0, l0),
        hdr(UO1, UO1, 1, d1, 2, 2 * d1, 3 * d1, l1),
        hdr(0, 0, 0, 500, 2, 200, 240, l2),
        hdr(1, 1, 0, 500, 2, 200, 240, l2),
        hdr(2, 2, 0, 500, 2, 200, 240, l2),
    ]
    return b"".join(headers) + b"".join(prog)


def build_five(delays):
    """FIVE active lanes at the SHIPPED inter-action delays. The one that is
    representative of the real design's refill demand.

    ⛔ THE TWO-LANE PROGRAMS UNDERSTATE REFILL CONTENTION BY A FACTOR OF ~2.5.
    One shared fetch port serves every lane, so the question "does a dispatch
    ever wait on a refill" depends on TOTAL refill demand, and measuring it with
    2 of 5 lanes active answers a different question. The shipped inner action
    spacings are about 25 (SPI 1 MHz at 50 MHz), 45 (I2C 400 kHz), 434
    (UART 115200), 414 (UART-rx inner) and 25 (SPI-target inner).
    """
    prog, headers, base = [], [], []
    off = ACT_BASE
    for n, d in enumerate(delays):
        base.append(off)
        prog.append(act(OP_LEVEL, n, 0, d))
        prog.append(act(OP_LEVEL, n, 1, d))
        prog.append(act(OP_REARM, 0, 1, d))
        off += 3 * ACT_BYTES
    for n, d in enumerate(delays):
        # D_tol capped at the 8-bit field; the shipped lanes' real keys are
        # derived in the A2 model, not here -- this program exists to load the
        # REFILL PORT, and its deadlines only have to keep the set schedulable.
        headers.append(hdr(n, n, 1, min(d, 1023), 2,
                           min(2 * d, 255), min(3 * d, 255), base[n]))
    return b"".join(headers) + b"".join(prog)


def build_chain(d_tog: int, d_park: int):
    """Two toggling lanes plus THREE lanes parked on CHAINING re-arms at a
    short delay, so the chaining path is exercised often.

    ⛔ WHY A THIRD PROGRAM. `M_BUF_CHAINFLIP` -- swapping on a chaining re-arm,
    whose PC does not advance -- SURVIVED both other images. It is not a
    correctness defect: the flip makes an unfilled slot the head, the refill
    then loads `l_pc` into it, and `l_pc` still points at the SAME action, so
    the buffer-swap invariant is satisfied and the pin behaviour is right. What
    it costs is a needless refill on every park dispatch, which steals shared
    fetch bandwidth from the lanes that are timing-critical.
    ⭐ So it is a JITTER mutant, not a correctness one, and it can only be
    killed DIFFERENTIALLY on a program where parks are frequent enough to
    compete for the port. A park at delay 500 (the default program) dispatches
    8 times in 4,000 cycles and steals nothing.
    """
    # ⭐ THREE toggling lanes, not two: the port has to be busy enough that the
    # bandwidth the mutant wastes is bandwidth something else needed. With two
    # toggling lanes the steady-state stall is 0 for the design AND the mutant,
    # and a differential test between two zeroes measures nothing.
    prog, headers, base = [], [], []
    off = ACT_BASE
    n_tog = 3
    for n in range(n_tog):
        base.append(off)
        prog.append(act(OP_LEVEL, n, 0, d_tog + n))
        prog.append(act(OP_LEVEL, n, 1, d_tog + n))
        prog.append(act(OP_REARM, 0, 1, d_tog + n))
        off += 3 * ACT_BYTES
    # the parked lanes: a CHAINING re-arm (level 0) at a SHORT delay, so they
    # dispatch often and the needless refill actually competes
    lp = off
    prog.append(act(OP_REARM, 0, 0, d_park))
    for n in range(n_tog):
        headers.append(hdr(n, n, 1, d_tog + n, 2,
                           min(2 * (d_tog + n), 255),
                           min(3 * (d_tog + n), 255), base[n]))
    for n in range(n_tog, N_LANES):
        headers.append(hdr(n, n, 0, d_park, 2, min(2 * d_park, 255),
                           min(3 * d_park, 255), lp))
    return b"".join(headers) + b"".join(prog)


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    if "--chain" in sys.argv:
        k = sys.argv.index("--chain")
        img = build_chain(int(sys.argv[k + 1]), int(sys.argv[k + 2]))
        out = os.path.join(here, "chain_image.hex")
        with open(out, "w", encoding="ascii") as fh:
            for b in img:
                fh.write("%02x\n" % b)
        print("chain image, %d bytes -> %s" % (len(img), out))
        return 0
    if "--five" in sys.argv:
        k = sys.argv.index("--five")
        delays = [int(x) for x in sys.argv[k + 1:k + 6]]
        img = build_five(delays)
        out = os.path.join(here, "five_image.hex")
        with open(out, "w", encoding="ascii") as fh:
            for b in img:
                fh.write("%02x\n" % b)
        print("five-lane image %s, %d bytes -> %s" % (delays, len(img), out))
        return 0
    if "--stress" in sys.argv:
        k = sys.argv.index("--stress")
        d0 = int(sys.argv[k + 1])
        d1 = int(sys.argv[k + 2])
        img = build_stress(d0, d1)
        out = os.path.join(here, "stress_image.hex")
        with open(out, "w", encoding="ascii") as fh:
            for b in img:
                fh.write("%02x\n" % b)
        print("stress image d0=%d d1=%d, %d bytes -> %s"
              % (d0, d1, len(img), out))
        return 0
    img = build()
    out = os.path.join(here, "smoke_image.hex")
    with open(out, "w", encoding="ascii") as fh:
        for b in img:
            fh.write("%02x\n" % b)
    print("HDR_BITS=%d HDR_BYTES=%d ACT_W=%d ACT_BYTES=%d ACT_BASE=%d"
          % (HDR_BITS, HDR_BYTES, ACT_W, ACT_BYTES, ACT_BASE))
    print("image is %d bytes -> %s" % (len(img), out))
    if len(img) > (1 << AW):
        print("*** image does not fit 2**AW = %d" % (1 << AW))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
