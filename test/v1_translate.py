"""v1 -> v2 IMAGE TRANSLATION -- the bijective v1 subset, applied to a whole image.

    python test/v1_translate.py <v1 image.hex> [<out.hex>]

v2 step 2 (Wilson ruling on design 5cf27c1f): every v1 program must mean the
same thing in v2. This maps a v1 image (24-bit words, byte-address header
`base`, 256-byte store) onto v2 (32-bit words, word-index `base`, the magic at
bytes 30-31, 512-byte store):

  * every v1 action word k (bytes 30 + 3k) -> v2 word k (bytes 32 + 4k), each
    field carried by NAME (op, pin, level, delay, count, q) with pinb = mod = 0
    -- the bijective subset; v1's filler maps to v2's filler (E2, checked);
  * every header field carried; `base` b -> word index (b - 30) / 3;
  * v2's words past v1's 75 are the v2 filler (pe_isa.full_store).

⭐ v1's FORMAT IS READ FROM v1-lock's OWN pe_isa (`git show v1-lock:test/pe_isa.py`),
never re-typed here: a translator with a private copy of the v1 layout would be
the two-copies defect the one-encoder rule exists to prevent.
"""
from __future__ import annotations

import os
import subprocess
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import pe_isa as V2                           # noqa: E402

V1_REF = "v1-lock"
_V1 = None


def v1():
    """v1-lock's pe_isa, loaded from its git blob (cached)."""
    global _V1
    if _V1 is None:
        r = subprocess.run(["git", "show", "%s:test/pe_isa.py" % V1_REF], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8")
        if r.returncode != 0:
            raise RuntimeError("cannot read %s:test/pe_isa.py -- %s" % (V1_REF, r.stderr))
        m = types.ModuleType("pe_isa_v1")
        exec(compile(r.stdout, "%s:test/pe_isa.py" % V1_REF, "exec"), m.__dict__)
        _V1 = m
    return _V1


def translate_word(raw1: bytes, field_map=None) -> bytes:
    """One v1 action word -> its v2 word (fields by name; pinb = mod = 0).
    `field_map` exists for the equivalence gate's must-fires (a mutated
    encoder); None is the real translation."""
    V1 = v1()
    f = V1._unpack(V1.ACT_FIELDS, raw1, V1.ACT_BYTES)
    if field_map:
        f = field_map(dict(f))
    vals = [f.get(n, 0) for n, _w in V2.ACT_FIELDS]
    return V2._pack(V2.ACT_FIELDS, vals, V2.ACT_BYTES)


def translate(img1: bytes, field_map=None, base_off=0) -> bytes:
    """A whole v1 image -> its v2 image (the full 512-byte store)."""
    V1 = v1()
    img1 = bytes(img1)
    if len(img1) != V1.STORE_BYTES:
        raise ValueError("v1 image is %d bytes, not v1's %d-byte store"
                         % (len(img1), V1.STORE_BYTES))
    hdrs = []
    for ln in range(V1.N_LANES):
        h = V1._unpack(V1.HDR_FIELDS, img1[ln * V1.HDR_BYTES:(ln + 1) * V1.HDR_BYTES],
                       V1.HDR_BYTES)
        b = h["base"]
        if b < V1.ACT_BASE or (b - V1.ACT_BASE) % V1.ACT_BYTES:
            raise ValueError("v1 lane %d base %d is not a v1 word address" % (ln, b))
        word = (b - V1.ACT_BASE) // V1.ACT_BYTES + base_off
        vals = [word if n == "base" else h[n] for n, _w in V2.HDR_FIELDS]
        hdrs.append(V2._pack(V2.HDR_FIELDS, vals, V2.HDR_BYTES))
    n1 = (V1.STORE_BYTES - V1.ACT_BASE) // V1.ACT_BYTES
    words = [translate_word(img1[V1.ACT_BASE + k * V1.ACT_BYTES:
                                 V1.ACT_BASE + (k + 1) * V1.ACT_BYTES], field_map)
             for k in range(n1)]
    return V2.full_store(V2.join_image(hdrs, words))


def main(argv) -> int:
    if len(argv) < 2:
        print(__doc__.splitlines()[2].strip())
        return 2
    with open(argv[1], encoding="ascii") as fh:
        img1 = bytes(int(x, 16) for x in fh.read().split())
    out = translate(img1)
    if len(argv) > 2:
        V2.write_image(argv[2], out)
    print("translated %s: %d -> %d bytes" % (argv[1], len(img1), len(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
