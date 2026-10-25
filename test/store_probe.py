"""Ruling M3 -- the probe images for `test/store_run.sh`.

Writes `probe_store/*.hex` (gitignored): each a FULL-STORE image whose unused
bytes hold `pe_isa.STORE_FILLER`, so a lane whose fetch path ever leaves its
program fetches the filler and `clocked_conform.vh` Layer M names it.

    pad_<name>.hex   a shipped image, padded: Layer M must stay QUIET
    falloff.hex      THE MUST-FIRE: lane 0 drives two LEVEL actions and has NO
                     terminating REARM, placed LAST in the store, so its next
                     fetch is the first filler word. Layer M must name lane 0
                     at address ACT_BASE + 9 (the speculative spare fetch, one
                     past the program's end) -- the fall-through path, shown.

⚠ The probe writes only `probe_store/`. It never edits a tracked image.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import pe_isa as I                                                # noqa: E402

OUT = os.path.join(ROOT, "probe_store")
SHIPPED = ("corpus_i2c.hex", "ckod_image.hex", "corpus_all5.hex",
           "smoke_image.hex")


def load(path):
    with open(path) as fh:
        return bytes(int(t, 16) for t in fh.read().split())


def save(path, img):
    with open(path, "w", newline="\n") as fh:
        fh.write("\n".join("%02x" % b for b in img) + "\n")


def build_falloff():
    """Lane 0 at the END of the program area, with no REARM; lanes 1..4 parked."""
    park = I.ACT_BASE
    prog = [I.act(I.OP_REARM, 0, 0, 500)]            # the parked-lane idiom
    l0 = park + I.ACT_BYTES
    prog.append(I.act(I.OP_LEVEL, I.UO0, 0, 20))
    prog.append(I.act(I.OP_LEVEL, I.UO0, 1, 20))     # ...and nothing after it
    headers = [I.hdr(I.UO0, I.UO0, 1, 20, 0, 40, 60, l0)]
    headers += [I.hdr(p, p, 0, 500, 0, 200, 240, park) for p in (0, 1, 2, 3)]
    return I.join_image(headers, prog), l0 + 2 * I.ACT_BYTES


def main() -> int:
    # ⛔ R4 #S (10-23): the caller's directory. store_run.sh takes an OUT and
    # ran its arms from it, while this always wrote probe_store/ -- so any
    # non-default OUT ran no arm at all.
    global OUT
    if len(sys.argv) > 1:
        OUT = os.path.abspath(sys.argv[1])
    os.makedirs(OUT, exist_ok=True)
    for name in SHIPPED:
        img = load(os.path.join(HERE, name))
        save(os.path.join(OUT, "pad_" + name), I.full_store(img))
        print("  pad_%-22s %3d -> %d bytes" % (name, len(img), I.STORE_BYTES))
    img, first_filler = build_falloff()
    save(os.path.join(OUT, "falloff.hex"), I.full_store(img))
    print("  falloff.hex                %3d -> %d bytes; first filler word at %d"
          % (len(img), I.STORE_BYTES, first_filler))
    with open(os.path.join(OUT, "falloff_addr.txt"), "w") as fh:
        fh.write("%d\n" % first_filler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
