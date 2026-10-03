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


def main() -> int:
    img = build()
    here = os.path.dirname(os.path.abspath(__file__))
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
