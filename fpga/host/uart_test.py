"""PC side of the FPGA UART-rx bring-up -- the FOREIGN WITNESS (Wilson): a real
UART (the board's CH340E, the PC's own crystal) sends; the chip receives; the
board returns the chip's received bytes RAW; THIS SCRIPT judges every byte.

Per frame the board returns two bytes: the data byte, and {stop, d7..d1} from
the chip's mid-stop sample (the ISA has no compare, so the framing check is the
host's -- here). The checks:
  * every data byte equals what was sent, in order, count EXACT;
  * every stop byte is {1, d7..d1};
  * FRAMING: a BREAK (line low ~2 ms) is a frame of zeros with 0 where the
    chip samples the stop bit: it must come back as data 00, stop byte 00 --
    the framing error reported.
  * BURSTS: frames sent back-to-back (no idle between them).

The same checks run in simulation first (fpga/sim/tb_fpga_uart.v, the twin).

Usage:  python fpga/host/uart_test.py COM5 [frames] [seed]
Needs pyserial (pip install pyserial).
"""
import random
import sys
import time

import serial

BAUD = 115200


def main():
    port = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 600
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    rng = random.Random(seed)
    s = serial.Serial(port, BAUD, bytesize=8, parity=serial.PARITY_NONE,
                      stopbits=1, timeout=2.0)
    s.reset_input_buffer()
    print("uart_test: %s at %d, %d frames, seed %d" % (port, BAUD, n, seed))

    # ⛔ LINE SETTINGS ARE NEVER CHANGED WITH BYTES IN FLIGHT. The first version
    # switched to SPACE parity right after flush() -- which returns before the
    # CH340 has shifted its own buffer out -- so whole bursts went out garbled
    # (182 of 200 bytes back, misaligned from frame 1) while the chip was fine:
    # paced plain 8N1 came back 30/30 exact. A framing frame is now sent ALONE:
    # idle the line, switch, one byte, wait for it to leave, switch back.
    # ⛔⛔ AND NOT BY PARITY AT ALL: ONE PORT HAS ONE PARITY SETTING FOR BOTH
    # DIRECTIONS. While the PC sent 8S1 its RECEIVER also expected parity, and
    # the board's 8N1 reply arrives mid-frame -- before the PC can switch back --
    # so the reply was misread or dropped (MARK and SPACE alike; 8N1 6/6 exact).
    # ⇒ THE FRAMING ERROR IS A BREAK: the line held low ~2 ms. The chip sees a
    # frame of zeros with 0 at its stop sample -> data 00, stop byte 00 (the
    # framing error reported); the PC's receiver mode never changes. The twin
    # (fpga/sim/tb_fpga_uart.v) sends the same break.
    sent, space = [], []
    i = 0
    while i < n:
        if rng.random() < 0.1:                           # a framing frame, alone
            time.sleep(0.02)
            s.send_break(duration=0.002)
            time.sleep(0.02)
            sent.append(0x00)
            space.append(True)
            i += 1
            continue
        burst = rng.choice((1, 1, 4, 16, 64))           # 64 back-to-back max
        frames = [rng.randrange(256) for _ in range(min(burst, n - i))]
        s.write(bytes(frames))
        s.flush()
        sent += frames
        space += [False] * len(frames)
        i += len(frames)
        time.sleep(rng.choice((0, 0, 0.001, 0.01)))

    want = 2 * len(sent)
    back = b""
    t0 = time.time()
    while len(back) < want and time.time() - t0 < 30:
        back += s.read(want - len(back))
    extra = s.read(64)                                   # anything beyond = bad
    s.close()

    bad = []
    for k, d in enumerate(sent):
        if 2 * k + 1 >= len(back):
            break
        stop = 0 if space[k] else 1
        exp = (d, (stop << 7) | (d >> 1))
        got = (back[2 * k], back[2 * k + 1])
        if got != exp:
            bad.append((k, exp, got))
    nsp = sum(space)
    ok = len(back) == want and not extra and not bad
    print("  sent %d frames (%d as BREAK framing frames); got %d bytes back, expected EXACTLY %d%s"
          % (len(sent), nsp, len(back), want,
             (", plus %d EXTRA" % len(extra)) if extra else ""))
    for k, exp, got in bad[:8]:
        print("  *** frame %d: expected %02x %02x, board returned %02x %02x"
              % (k, exp[0], exp[1], got[0], got[1]))
    print("UART-RX ON THE BOARD: %s" % ("ok -- every byte as sent, framing "
          "reported on every break frame" if ok else "*** FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
