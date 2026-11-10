"""PC-UART loader -- load a program image into the chip on the board, no rebuild.

The FPGA stand-in for the real chip's host (the Pico 2): the board's glue
(fpga/rtl/pe_fpga_core.v) enters its loader on a long BREAK, takes
    A5 5A <STORE_BYTES image bytes> <ck>   (sum of image bytes + ck == 0 mod 256)
where STORE_BYTES and the image's v2 MAGIC come from test/pe_isa.py (F1.5:
the v2 chip refuses a short load or a missing MAGIC with CONFIG_ERR).
and replies 'K' after restarting the chip's load through its real host
interface (PROG / PTR_RST / WR), or 'E' on a bad header or checksum.

Usage:  python fpga/host/load.py COM3 <image.hex> [--corrupt]
        (--corrupt sends a wrong checksum: the board must answer 'E')
Needs pyserial.
"""
import os
import sys
import time

import serial

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "test"))
import pe_isa                                   # noqa: E402  the one encoder

BAUD = 115200
BREAK_S = 0.05            # > the glue's 20 ms threshold; the UART test's
                          # framing breaks are 2 ms, so they never enter it


def read_image(path):
    with open(path, encoding="ascii") as fh:
        toks = [t for t in fh.read().split() if not t.startswith("//")]
    img = bytes(int(t, 16) for t in toks)
    if len(img) != pe_isa.STORE_BYTES:
        raise SystemExit("image %s is %d bytes, expected the full %d-byte "
                         "store" % (path, len(img), pe_isa.STORE_BYTES))
    if img[pe_isa.HDR_REGION:pe_isa.ACT_BASE] != pe_isa.MAGIC:
        raise SystemExit("image %s has %s at bytes %d-%d, not the v2 MAGIC %s: "
                         "the chip would refuse it (CONFIG_ERR)" % (
                             path, img[pe_isa.HDR_REGION:pe_isa.ACT_BASE].hex(),
                             pe_isa.HDR_REGION, pe_isa.ACT_BASE - 1, pe_isa.MAGIC.hex()))
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
