"""PC-UART loader -- load a program image into the chip on the board, no rebuild.

The FPGA stand-in for the real chip's host (the Pico 2): the board's glue
(fpga/rtl/pe_fpga_core.v) enters its loader on a long BREAK, takes
    A5 5A <256 image bytes> <ck>      (sum of image bytes + ck == 0 mod 256)
and replies 'K' after restarting the chip's load through its real host
interface (PROG / PTR_RST / WR), or 'E' on a bad header or checksum.

Usage:  python fpga/host/load.py COM3 <image.hex> [--corrupt]
        (--corrupt sends a wrong checksum: the board must answer 'E')
Needs pyserial.
"""
import sys
import time

import serial

BAUD = 115200
BREAK_S = 0.05            # > the glue's 20 ms threshold; the UART test's
                          # framing breaks are 2 ms, so they never enter it


def read_image(path):
    with open(path, encoding="ascii") as fh:
        toks = [t for t in fh.read().split() if not t.startswith("//")]
    img = bytes(int(t, 16) for t in toks)
    if len(img) != 256:
        raise SystemExit("image %s is %d bytes, expected the full 256-byte "
                         "store" % (path, len(img)))
    return img


def load(port, img, corrupt=False):
    ck = (-sum(img)) & 0xFF
    if corrupt:
        ck = (ck + 1) & 0xFF
    s = serial.Serial(port, BAUD, timeout=1.0)
    s.reset_input_buffer()
    s.send_break(duration=BREAK_S)
    time.sleep(0.01)
    s.reset_input_buffer()          # anything the old program sent
    s.write(b"\xA5\x5A" + img + bytes([ck]))
    s.flush()
    reply = s.read(1)
    s.close()
    return reply


def main():
    port, path = sys.argv[1], sys.argv[2]
    corrupt = "--corrupt" in sys.argv
    img = read_image(path)
    reply = load(port, img, corrupt)
    want = b"E" if corrupt else b"K"
    ok = reply == want
    print("load %s -> %s: board replied %r (expected %r)%s"
          % (path, port, reply, want, "" if ok else "  *** UNEXPECTED"))
    print("PC-LOADER: %s" % ("ok" if ok else "*** FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
