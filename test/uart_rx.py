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
    SHIFTIN  RX, count 1, delay D*         -- the mid-STOP sample, pushed as a
                                              second byte {stop, d7..d1}
    REARM    loop to the ARM, delay D*     -- re-armed ~46 cycles after
                                              mid-stop, before the next start
                                              edge while T >= T_MIN
⛔⛔ NO DELAY-0 CHAIN (Wilson's delay-0 REARM ruling). The first build ended
`SHIFTIN(stop) -> REARM -> ARM` at delay 0 -- three back-to-back dispatches,
a ZERO release spacing that pe_asm could not see ("d_min 64, J 1"). Beside
four d = 20 lanes it was ACCEPTED and mis-received at -3 % baud. pe_asm now
refuses any delay-0 action but an ARM's (`model/zero_spacing.py`), and this
build spaces both at D* = 20. That build is RETIRED, not kept as a declared
image; its board results (3,600 bytes, +-2.5 %) are history.
⭐ THE COST IS A SPEED LIMIT, MEASURED AND PUBLISHED: `T_MIN` below.
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
from gate_j_program import D_STAR                                # noqa: E402
from make_smoke_image import (OP_ARM, OP_LEVEL, OP_REARM,         # noqa: E402
                              OP_SHIFTIN, PIN_NONE)

P_RX = 3            # uio[3], test/pinmap.vh
# ⭐ THE BENCH RUNS AT THE BOARD'S OWN RATE (Wilson's (a)): 50 MHz / 115200
# baud = 434 cycles per bit, the rate the FPGA board receives at.
T_NOMINAL = 434
# ⛔⛔ THE SPEED LIMIT -- the smallest T this program is certified at
# (Wilson: "fastest certified baud at 50 MHz" is a measured, published
# number, not a gap). 232 cycles/bit = 215.5 kbaud at 50 MHz.
# DERIVED: the ARM is armed ~46 cycles after the mid-stop sample (stop D* +
# REARM D* + the dispatches). A peer 3 % FAST starts its next back-to-back
# frame (0.5 - 9.5 * 0.03) T = 0.215 T after that sample, so the ARM is in
# time iff 0.215 T >= ~46, i.e. T >= ~214, and the edge-to-rebase latency
# and sample jitter take the rest.
# MEASURED (tb_uartrx, 40 frames, -3/0/+3 %, delay-20 build, 2026-10-12):
# failures at T = 192, 204, 216 (seed-dependent: 200 and 208 passed, so the
# edge is not monotonic); CLEAN at 224 on 8 seeds and at 232 on 16 seeds
# alone and 8 seeds beside four push-pull lanes toggling at d = 20. 232 is
# the first value clean beyond the last failure with an 8-cycle step.
# `run_uartrx` keeps a +-3 % arm AT T_MIN, and `build` refuses below it.
T_MIN = 232
# ⭐ MEASURED, NOT DERIVED (offset sweep, tb_uartrx, T = 64, 40 frames, seeds
# 1-2): nominal baud passes for offsets 64..112; ALL of -3/-2/0/+2/+3 % pass
# only for 80..92 (9.5 bits of 3 % drift eat ~18 of the 32-cycle half bit).
# Centred: 86 = 1.5 T - 10, the 10 being the ARM's edge-to-rebase latency plus
# the dispatch and the pin's 2-sample input path -- an ABSOLUTE latency, so
# the same 10 holds at T = 434 and T_MIN (both arms pass +-3 % with it).
# Re-measure if any changes.
OFFSET_LAT = 10


def default_offset(T):
    return (3 * T) // 2 - OFFSET_LAT


def lanes_headers(T=T_NOMINAL, offset=None, variant="ok"):
    if T < T_MIN:
        raise pe_asm.Reject(
            "UART-rx at T = %d cycles/bit is below T_MIN = %d: the ARM is "
            "re-armed ~46 cycles after the mid-stop sample (stop and REARM at "
            "D* = %d, no delay-0 chain), and a peer 3 %% fast starts its next "
            "back-to-back frame only ~0.215 T later -- the start edge would be "
            "missed. Measured; see T_MIN in test/uart_rx.py."
            % (T, T_MIN, D_STAR))
    if offset is None:
        offset = default_offset(T)
    if variant == "edge":
        offset = offset - T // 2          # sample 0 at bit 0's start edge
    seq = [(OP_ARM, P_RX, 0, 0, 0),
           (OP_LEVEL, PIN_NONE, 0, offset, 0)]
    seq += [(OP_SHIFTIN, P_RX, 0, T, 0, 8) for _ in range(8)]
    if variant != "nostop":
        seq.append((OP_SHIFTIN, P_RX, 0, D_STAR, 0, 1))
    seq.append((OP_REARM, 0, 1, D_STAR, 0))
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
