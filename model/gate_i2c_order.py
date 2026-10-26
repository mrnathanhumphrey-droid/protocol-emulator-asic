"""RULING RC4 -- EVERY I2C LANE IS MSB-FIRST, IN EVERY TRACKED IMAGE.

⛔⛔ WHY. The clocked I2C corpus (`corpus_i2c`, `ckread`, `corpus_all5` lane 0)
framed I2C -- OP_START / OP_STOP -- on LSB-first lanes, because every builder
took `hdr()`'s LSB default. The chip sent exactly what it was told, in the
order the header asked (Layer V2 agrees), so `5B` went out as `DA`. Nothing
had put those programs in front of a real I2C decoder until the sigrok
re-certification, which saw it at once.

THE CLAIM: in every `test/*.hex` image (probe_* excluded), a lane whose
program uses OP_START or OP_STOP has an MSB-first header. The rule and the
decoder are `pe_isa.i2c_order_problems` -- the same code `pe_asm` refuses
with -- so the audit and the assembler cannot disagree.

EXEMPT, BY NAME AND WITH A REASON, never by pattern: an exemption that no
longer excuses anything (the lane is MSB, or no longer frames) is STALE and
red, so it cannot outlive the program it was written for.
MUST-FIRES: a planted LSB-first START/STOP image is red; the same program
with its order derived by `order_for` is clean; a stale exemption is red.
"""

from __future__ import annotations

import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "test"))
import pe_isa as I                                            # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

#: image -> {lane: reason}
EXEMPT = {
    "census_image.hex": {
        0: "a COVERAGE program, not a protocol (its builder says so): lane 0 "
           "walks the output opcodes, OP_START/OP_STOP among them, on UO0 to "
           "measure per-opcode service time. Its waveform means nothing, so a "
           "bit order has nothing to be right about; changing it would move "
           "the census lockstep stream for no protocol reason.",
    },
}


def images():
    """Paths of the shared image universe (`model/image_universe.py`, Wilson
    10-18): this scanned test/*.hex only."""
    import image_universe
    return [p for _n, p in image_universe.items()]


def read(p):
    with open(p, encoding="ascii") as fh:
        return bytes(int(t, 16) for t in fh.read().split())


def audit(named, exempt):
    """named: [(name, img)] -> [problem]"""
    probs = []
    for name, img in named:
        ex = exempt.get(name, {})
        for p in I.i2c_order_problems(img, exempt=tuple(ex)):
            probs.append("%s: %s" % (name, p))
        raw = I.i2c_order_problems(img)
        for ln in sorted(ex):
            if not any(p.startswith("lane %d " % ln) for p in raw):
                probs.append("%s: exemption for lane %d is STALE -- that lane "
                             "is no longer an LSB-first START/STOP lane" % (name,
                                                                         ln))
    for name in sorted(set(exempt) - {n for n, _ in named}):
        probs.append("exemption for %s names no image -- STALE" % name)
    return probs


def plant(order):
    i2c = [I.act(I.OP_START, 2, 0, 70), I.act(I.OP_SHIFT, 2, 1, 70),
           I.act(I.OP_STOP, 2, 1, 70), I.act(I.OP_REARM, 0, 1, 70)]
    park = I.ACT_BASE + len(i2c) * I.ACT_BYTES
    # v2: through the ONE assembler (pe_isa.join_image) -- it adds the magic
    return I.full_store(I.join_image(
        [I.hdr(2, 1, 0, 70, 0, 140, 210, I.ACT_BASE, order=order)]
        + [I.hdr(p, p, 0, 500, 0, 200, 240, park) for p in (0, 3, 4, 5)],
        i2c + [I.act(I.OP_REARM, 0, 0, 500)]))


def main() -> int:
    print()
    print("=" * 78)
    print("  RC4 -- EVERY START/STOP (I2C) LANE IS MSB-FIRST, IN EVERY IMAGE")
    print("=" * 78)
    named = [(os.path.basename(p), read(p)) for p in images()]
    i2c_lanes = sum(1 for _n, img in named
                    for _h, acts in I.lane_programs(img).values()
                    if any(a["op"] in (I.OP_START, I.OP_STOP) for a in acts))
    probs = audit(named, EXEMPT)
    print("  %d images, %d START/STOP lane(s), %d exempt by name"
          % (len(named), i2c_lanes, sum(len(v) for v in EXEMPT.values())))
    for name, lanes in sorted(EXEMPT.items()):
        for ln, why in sorted(lanes.items()):
            print("    exempt %s lane %d: %s" % (name, ln, why[:60]))
    rc = 0
    for p in probs:
        print("    *** %s" % p)
        rc = 1
    if not probs:
        print("    every START/STOP lane is MSB-first")
    print("  --- must-fires ---")
    order = I.order_for([I.OP_START, I.OP_SHIFT, I.OP_STOP, I.OP_REARM])
    for what, got, want_red in (
            ("an LSB-first START/STOP image",
             audit([("plant", plant(I.ORDER_LSB))], {}), True),
            ("the same program, order from order_for",
             audit([("plant", plant(order))], {}), False),
            ("a stale exemption",
             audit([("plant", plant(order))], {"plant": {0: "x"}}), True)):
        ok = bool(got) == want_red
        print("    %-44s %s" % (what, ("red  ok" if want_red else "clean  ok")
                                if ok else "*** WRONG"))
        if not ok:
            rc = 1
    print()
    print("  GATE i2c-order: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
