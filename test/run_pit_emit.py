#!/usr/bin/env python3
"""v2 PIT item 2, step 1 (Wilson 11-06): the RPL EMITTER's unit check on
HAND-MADE results images -- the bytes are written field by field from the
layouts in src/project.v (pe_pit_s0 table, pe_pit_s12 records, the stage 3
record), not from the emitter's own decoder, so a decode slip is a mismatch.

Checks:
  1. three images against hand-written spec text, line for line;
  2. every image: parse(emit(img)) == claims(img) (the spec carries every claim);
  3. the real-time rates recover the record's 16.4 period exactly, every p16
     from 4.0 to 16384 cycles, at 60 MHz and 50 MHz, as Bd and as ns;
  4. the parser refuses bad specs (each named), and accepts a v2 pattern line.
                                                    token: GATE pit-emit: PASSED
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "model"))
import pit_emit as E                                              # noqa: E402

HZ = 60_000_000


def img():
    return bytearray(136)


def table(b, ent):
    """ent: {wire: 7-bit entry} -- {code[2:0], partner[5:3], level[6]}"""
    word = 0
    for w, e in ent.items():
        word |= e << (7 * w)
    b[32:39] = word.to_bytes(7, "little")


def rec(b, w, cls, why=0, cond=0, wh=0, idle=0, p16=0, phase=0, score=0, n=0, frames=0, fb=0):
    o = 40 + 10 * w
    b[o + 0] = cls << 5 | why << 2 | cond << 1 | wh
    b[o + 1] = idle << 7 | ((p16 >> 16) & 7) << 4 | ((fb >> 9) & 0xF)
    b[o + 2], b[o + 3] = (p16 >> 8) & 0xFF, p16 & 0xFF
    b[o + 4] = ((fb >> 8) & 1) << 7 | ((phase >> 8) & 0x7F)
    b[o + 5] = phase & 0xFF
    b[o + 6], b[o + 7], b[o + 8], b[o + 9] = score, n, frames, fb & 0xFF


def s3(b, w, poly=None, width=16, refl=0, frame=0, init=None, xorout=None, multi=0, diffs=5, nmsg=20):
    b[120] = w | 1 << 3
    b[123] = nmsg
    if poly is None:
        return
    b[120] |= 1 << 4 | refl << 6
    b[121] = {8: 1, 16: 2, 32: 3}[width] | frame << 2
    b[122] = diffs
    b[124:128] = poly.to_bytes(4, "little")
    if init is not None:
        b[120] |= 1 << 5 | multi << 7
        b[128:132] = init.to_bytes(4, "little")
        b[132:136] = xorout.to_bytes(4, "little")


def uart_crc():
    b = img()
    rec(b, 0, E.C_ASYNC, cond=1, idle=1, p16=24 * 16, phase=7, score=250, n=200, frames=40, fb=10)
    s3(b, 0, poly=0x8005, refl=1, frame=3, init=0xFFFF, xorout=0x0000)
    return b


UART_CRC_TEXT = """\
-- PE PIT spec v1: the chip's claims only (results bytes 0..135)
spec sniff is
  captured at 60000000 Hz;
  wire uio0 : NRZ_ASYNC idle 1 rate 2500000.000 Bd frame 10 bits given all-wires-sniffed;
  crc on uio0 : width 16 refin refout poly 0x8005 frame 3 bytes init 0xFFFF xorout 0x0000 source catalogue "CRC-16/MODBUS" class 1;
end sniff;
"""


def uart_poly_only():
    b = img()
    rec(b, 5, E.C_ASYNC, cond=1, idle=1, p16=521 * 16 + 5, n=90, frames=12, fb=11)
    s3(b, 5, poly=0x04C11DB7, width=32, refl=1, frame=9)
    return b


def spi():
    b = img()
    table(b, {1: E.R_CLOCK, 2: E.R_SYNC | 1 << 3 | 0 << 6, 3: E.R_FRAME | 1 << 3})
    for w in (1, 2, 3):
        rec(b, w, E.C_ROLE)
    s3(b, 2, poly=0x1021, frame=4, init=0x0000, xorout=0x0000, multi=1)
    b[39] = 0x08
    return b


SPI_TEXT = """\
-- PE PIT spec v1: the chip's claims only (results bytes 0..135)
spec sniff is
  captured at 60000000 Hz;
  wire uio1 : role CLOCK;
  wire uio2 : role SYNC_DATA of uio1 change 0;
  wire uio3 : role FRAME of uio1;
  crc on uio2 : width 16 poly 0x1021 frame 4 bytes init 0x0000 xorout 0x0000 source catalogue "CRC-16/XMODEM" class multi;
end sniff;
"""


def i2c():
    b = img()
    table(b, {6: E.R_CLOCK_I2C, 7: E.R_SYNC_I2C | 6 << 3 | 1 << 6})
    rec(b, 6, E.C_ROLE)
    rec(b, 7, E.C_ROLE)
    s3(b, 7, poly=0x07, width=8, frame=5, init=0x00, xorout=0x00)
    return b


def refused():
    b = img()
    table(b, {w: E.R_REFUSED | 3 << 3 for w in range(8)})
    for w in (2, 3):
        rec(b, w, E.C_UNK, why=6)
    return b


def no_cs():
    b = img()
    table(b, {0: E.R_CLOCK, 4: E.R_SYNC | 0 << 3 | 1 << 6})
    rec(b, 0, E.C_ROLE)
    rec(b, 4, E.C_ROLE)
    return b


NO_CS_TEXT = """\
-- PE PIT spec v1: the chip's claims only (results bytes 0..135)
spec sniff is
  captured at 60000000 Hz;
  wire uio0 : role CLOCK;
  wire uio4 : role SYNC_DATA of uio0 change 1;
  ? unknown crc -- no stage 3 record: a clocked bus with no frame wire;
end sniff;
"""


def mixed():
    """partial overrun; an ambiguous pair; a withheld UART (timing known); a
    Manchester wire; a stage-1 failure; a data-source CRC (no catalogue entry)."""
    b = img()
    b[2], b[28], b[29] = 0x80, 0x80 | 0x01, 0x2C
    table(b, {0: E.R_AMBIG | 1 << 3, 1: E.R_AMBIG | 0 << 3})
    rec(b, 0, E.C_ROLE)
    rec(b, 1, E.C_ROLE)
    rec(b, 2, E.C_UNK, why=7, wh=1, p16=33 * 16 + 3, n=120)
    rec(b, 3, E.C_MANCH, cond=1, p16=16 * 16, n=80)
    rec(b, 4, E.C_UNK, why=1, n=9)
    rec(b, 5, E.C_LEVEL, p16=0x7FFFF, n=30)
    rec(b, 6, E.C_ASYNC, cond=1, idle=0, p16=48 * 16 + 15, n=60, fb=9)
    s3(b, 6, poly=0x1D, width=8, frame=63, init=0x5A, xorout=0xC3)
    return b


def uart_nopoly():
    b = img()
    rec(b, 0, E.C_ASYNC, cond=1, idle=1, p16=10 * 16, fb=10)
    s3(b, 0, nmsg=7)
    return b


IMAGES = {"uart_crc": uart_crc, "uart_poly_only": uart_poly_only, "spi": spi, "i2c": i2c,
          "refused": refused, "no_cs": no_cs, "mixed": mixed, "uart_nopoly": uart_nopoly,
          "empty": img}
TEXTS = {"uart_crc": UART_CRC_TEXT, "spi": SPI_TEXT, "no_cs": NO_CS_TEXT}

BAD = {
    "no end line": "spec sniff is\n  captured at 60000000 Hz;\n",
    "no clock": "spec sniff is\nend sniff;\n",
    "refin alone": "spec sniff is\n  captured at 60000000 Hz;\n"
                   "  crc on uio0 : width 8 refin poly 0x07 frame 3 bytes;\nend sniff;\n",
    "init without xorout": "spec sniff is\n  captured at 60000000 Hz;\n"
                           "  crc on uio0 : width 8 poly 0x07 frame 3 bytes init 0x00 source data class 1;\nend sniff;\n",
    "unknown with no reason": "spec sniff is\n  captured at 60000000 Hz;\n  ? unknown crc;\nend sniff;\n",
    "wire with no rate": "spec sniff is\n  captured at 60000000 Hz;\n  wire uio0 : NRZ_ASYNC idle 1;\nend sniff;\n",
    "bad wire name": "spec sniff is\n  captured at 60000000 Hz;\n  wire uio9 : role CLOCK;\nend sniff;\n",
    "provenance as a comment": "spec sniff is\n  captured at 60000000 Hz;\n"
                               "  crc on uio0 : width 8 poly 0x07 frame 3 bytes init 0x00 xorout 0x00; -- source data\nend sniff;\n",
    "bad pattern": "spec sniff is\n  captured at 60000000 Hz;\n  pattern Frame(uio0) => Frame(uio0);\nend sniff;\n",
}
GOOD_PATTERN = ("spec sniff is\n  captured at 60000000 Hz;\n"
                "  pattern Frame(uio0) -> Frame(uio0) during (100 ns, 2000.5 ns);\n"
                "  pattern Start(uio1) || Start(uio2);\nend sniff;\n")


def main() -> int:
    probs = []
    print("PIT RPL EMITTER v1 -- hand-made results images (Wilson 11-06, item 2 step 1)")
    for name, mk in IMAGES.items():
        b = bytes(mk())
        cl = E.claims(b, HZ)
        text = E.render(cl)
        back = E.parse(text)
        ok = back == cl
        if not ok:
            probs.append("%s: parse(emit) != claims" % name)
        if name in TEXTS and text != TEXTS[name]:
            probs.append("%s: text differs from the hand-written spec" % name)
            for a, c in zip(text.splitlines(), TEXTS[name].splitlines()):
                if a != c:
                    print("    got  %s\n    want %s" % (a, c))
        print("  %-15s %2d lines  %s" % (name, text.count("\n"),
                                         "round-trips" if ok else "*** parse(emit) differs"))
    print("  --- spec text, image `mixed`:")
    for ln in E.emit(bytes(mixed()), HZ).splitlines():
        print("    " + ln)
    nbad = 0
    for hz in (60_000_000, 50_000_000):
        for p16 in range(4 * 16, 16384 * 16 + 1):
            if round(hz * 16.0 / float(E._bd(p16, hz))) != p16 or \
                    round(float(E._ns(p16, hz)) * 1e-9 * hz * 16.0) != p16:
                nbad += 1
    print("  rates: every p16 in 4..16384 cycles at 60 / 50 MHz recovered exactly, Bd and ns: %s"
          % ("yes" if not nbad else "*** %d miss" % nbad))
    if nbad:
        probs.append("rate precision: %d p16 values not recovered" % nbad)
    for why, t in BAD.items():
        try:
            E.parse(t)
            probs.append("parser accepted a bad spec: %s" % why)
            print("  refuse %-24s *** accepted" % why)
        except E.SpecError as e:
            print("  refuse %-24s ok (%s)" % (why, e))
    try:
        pats = E.parse(GOOD_PATTERN)["patterns"]
        print("  v2 pattern lines parse with no new syntax: %d" % len(pats))
    except E.SpecError as e:
        probs.append("v2 pattern line refused: %s" % e)
    import pit_s0_golden as S0
    same = S0.frozen_model().CATALOGUE == E.CATALOGUE
    print("  the emitter's catalogue = the frozen golden's: %s" % ("yes" if same else "*** NO"))
    if not same:
        probs.append("CATALOGUE differs from the frozen golden's")
    for p in probs:
        print("  *** " + p)
    print("  GATE pit-emit: %s" % ("FAILED" if probs else "PASSED"))
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())
