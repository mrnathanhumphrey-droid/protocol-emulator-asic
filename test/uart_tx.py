"""UART-tx 8N1 -- the published UART-tx lane's program, at its rated speed.

WF2 round 2 (Wilson): every published lane needs an ACCEPTED image, at its
published rating, that a CI check witnesses EXACT on the wire. This is
UART-tx's. Written with pe_asm, so it is certified by the same assembler
that refuses what the chip cannot run.

THE PROGRAM (one lane, push-pull on uo_out[0] -- `pinmap.vh` P_TX_UO --
LSB first, T cycles per bit; the lane loops on a REARM):
    LEVEL    TX low,  delay T              -- the start bit
    SHIFT    TX, count 7, delay T   x 8    -- 8 data bits; the 8th loads the
                                              next host byte (queue 0)
    LEVEL    TX high, delay T - D*         -- the stop bit ...
    REARM    loop, delay D*                -- ... completed by the REARM, so
                                              the stop bit is exactly T and no
                                              delay is 0 (the delay-0 ruling)
⭐ EVERY FRAME IS THE HOST'S, FROM THE FIRST (silicon fix #8, WF2). This
witness is where the defect was found: a TX lane loaded the next byte at the
END of each byte (`tx_bitp == a_cnt`), so the first frame after a load shifted
out the register's reset value 0x00 before any host byte was in it -- a real
receiver saw a NUL, and the ISA could not prime around it. The fix takes a
byte's first bit from the queue head; the witness now expects the feed from
frame 0, and a leading 0x00 is red.

`busy=True` places four push-pull lanes toggling at d = D* beside it (the
WS2812 finding's neighbour set), so the witness holds under contention.

Usage:  python test/uart_tx.py <out.hex> [busy]
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "model"))
import pe_asm                                                    # noqa: E402
from gate_j_program import D_STAR                                # noqa: E402
from make_smoke_image import (OP_LEVEL, OP_REARM, OP_SHIFT,       # noqa: E402
                              PIN_NONE)

P_TX = 8            # uo_out[0], test/pinmap.vh P_TX_UO
T_NOMINAL = 434     # 50 MHz / 115200 baud


def lanes_headers(T=T_NOMINAL, busy=False, msb=False):
    """`msb=True` is the MUST-FIRE variant (run_uarttx): the same lane sent
    MSB-first, which a UART peer must read as a different byte."""
    seq = [(OP_LEVEL, P_TX, 0, T, 0)]
    seq += [(OP_SHIFT, P_TX, 0, T, 0, 7) for _ in range(8)]
    seq += [(OP_LEVEL, P_TX, 1, T - D_STAR, 0), (OP_REARM, 0, 1, D_STAR, 0)]
    lanes = {0: seq}
    # D_sched / D_tol are 8-bit header fields: capped at 255, as UART-rx's
    # (the encoder now REFUSES a value that does not fit -- it used to mask)
    headers = {0: (P_TX, PIN_NONE, 1, T, min(T, 255), min(2 * T, 255))
               + ((0, 1) if msb else ())}
    if busy:
        for ln, p in zip((1, 2, 3, 4), (9, 10, 11, 0)):
            lanes[ln] = [(OP_LEVEL, p, 1, D_STAR, 0),
                         (OP_LEVEL, p, 0, D_STAR, 0),
                         (OP_REARM, 0, 1, D_STAR, 0)]
            headers[ln] = (p, PIN_NONE, 1, D_STAR, D_STAR, 2 * D_STAR)
    return lanes, headers


def build(T=T_NOMINAL, busy=False, msb=False):
    lanes, headers = lanes_headers(T, busy, msb)
    return pe_asm.assemble(lanes, headers)


def main():
    out = sys.argv[1]
    busy = len(sys.argv) > 2 and sys.argv[2] == "busy"
    img = build(T_NOMINAL, busy)
    with open(out, "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join("%02x" % b for b in img) + "\n")
    print("uart_tx: T=%d busy=%s -> %s (%d bytes)" % (T_NOMINAL, busy, out,
                                                     len(img)))


if __name__ == "__main__":
    main()
