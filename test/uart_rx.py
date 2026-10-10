"""UART-rx 8N1 -- the first program that RECEIVES a real UART byte stream.

Wilson's UART ruling: five lanes are published including UART-rx, and until
this file no program received a real byte stream (`corpus_uartrx` is an ARM
stub, `rxfast` a one-sample overflow test). Written with pe_asm.

THE PROGRAM (one lane, LSB first, T cycles per bit):
    ARM      fall on RX, no timeout        -- the start bit's falling edge
    LEVEL    PIN_NONE, delay = offset      -- a no-op that places sample 0
                                              at mid-bit 0 (offset ~ 1.5 T)
    SHIFTIN  RX, count 8, delay T   x 8    -- 8 mid-bit samples; the 8th pushes
                                              the byte
    SHIFTIN  RX, count 1, delay 0          -- the mid-STOP sample, pushed as a
                                              second byte {stop, d7..d1}
    REARM    loop to the ARM, delay 0      -- re-armed within a few cycles, so
                                              back-to-back frames are caught
⚠ THE ISA HAS NO COMPARE OR BRANCH, so the stop-bit (framing) check is the
host's: every second byte's bit 7 is the stop level and must be 1. The stop
byte costs a second push T after the data byte, so T must exceed the host
link's payload slot (~48 cycles) or `rx_pend` (one deep) drops it.

Variants (must-fires, Wilson): "edge" samples at the bit's START edge instead
of mid-bit; "nostop" drops the stop sample (the framing check is gone).

Usage:  python test/uart_rx.py <out.hex> [T] [offset] [variant]
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "model"))
import pe_asm                                                    # noqa: E402
from make_smoke_image import (OP_ARM, OP_LEVEL, OP_REARM,         # noqa: E402
                              OP_SHIFTIN, PIN_NONE)

P_RX = 3            # uio[3], test/pinmap.vh
T_NOMINAL = 64
# ⭐ MEASURED, NOT DERIVED (offset sweep, tb_uartrx, T = 64, 40 frames, seeds
# 1-2): nominal baud passes for offsets 64..112; ALL of -3/-2/0/+2/+3 % pass
# only for 80..92 (9.5 bits of 3 % drift eat ~18 of the 32-cycle half bit).
# Centred: 86 = 1.5 T - 10, the 10 being the ARM's edge-to-rebase latency plus
# the dispatch and the pin's 2-sample input path. Re-measure if any changes.
OFFSET_LAT = 10


def default_offset(T):
    return (3 * T) // 2 - OFFSET_LAT


def lanes_headers(T=T_NOMINAL, offset=None, variant="ok"):
    if offset is None:
        offset = default_offset(T)
    if variant == "edge":
        offset = offset - T // 2          # sample 0 at bit 0's start edge
    seq = [(OP_ARM, P_RX, 0, 0, 0),
           (OP_LEVEL, PIN_NONE, 0, offset, 0)]
    seq += [(OP_SHIFTIN, P_RX, 0, T, 0, 8) for _ in range(8)]
    if variant != "nostop":
        seq.append((OP_SHIFTIN, P_RX, 0, 0, 0, 1))
    seq.append((OP_REARM, 0, 1, 0, 0))
    headers = {0: (P_RX, PIN_NONE, 1, T, min(2 * T, 255), min(3 * T, 255))}
    return {0: seq}, headers


def build(T=T_NOMINAL, offset=None, variant="ok"):
    lanes, headers = lanes_headers(T, offset, variant)
    return pe_asm.assemble(lanes, headers)


def main():
    out = sys.argv[1]
    T = int(sys.argv[2]) if len(sys.argv) > 2 else T_NOMINAL
    off = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] != "-" else None
    var = sys.argv[4] if len(sys.argv) > 4 else "ok"
    img = build(T, off, var)
    with open(out, "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join("%02x" % b for b in img) + "\n")
    print("uart_rx: T=%d offset=%s variant=%s -> %s (%d bytes)"
          % (T, off if off is not None else default_offset(T), var, out, len(img)))


if __name__ == "__main__":
    main()
