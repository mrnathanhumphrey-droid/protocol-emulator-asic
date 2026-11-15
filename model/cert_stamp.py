"""cert_stamp -- an image's certification STAMP: certified, or uncertified with the reason
(Wilson 11-15: "UNCERTIFIED is a stamp, refusal is opt-in").

  1. Default, every path: an image whose program pe_asm.compute_j refuses (d_min below
     D* = 20, an inadmissible set, a zero spacing) is still BUILT, and stamped
         UNCERTIFIED: compute_j refuses: <compute_j's reason>
     -- the d = 12 test images assemble and run as uncertified stress tests.
  2. Opt-in refusal: `--require-cert` (here `require()`) turns an uncertified stamp into a
     failure with the same reason and a nonzero exit. Every image that ships or goes on
     the board is built with it (IMAGES_OF_RECORD).
  3. Machine-readable: the stamp is a FIELD -- `stamp(img)` returns it, `write()` puts it
     beside the image as `<image>.cert.json` -- not a printed line. Without
     --require-cert the exit code stays 0, so the field is the only signal and gates
     read it (`read()`; `gate_cert_stamp.py` checks every sidecar is current).

ONE FUNCTION OF THE IMAGE. The stamp is computed from the image's bytes, never from a
builder's private lanes, so the compiler, pe_asm's command line and every gate get the same
field for the same image. `image_lanes` decodes each lane's words back into the
`(op, pin, level, delay, q)` tuples compute_j reads (the inverse of pe_asm.assemble: a
LOOP's spacing is its wait W = count:pinb, every other word's is its delay field), from
the lane's base to its first REARM / LOOP or the next lane's base. Lanes parked on the
shared REARM are left out, as pe_asm.assemble leaves them out of `lanes`. The compiler
cross-checks the decode against the lanes the lowering actually handed pe_asm.assemble
(run_poset_compile C1), and the gate round-trips every pe_asm self-test program.

The image bytes are never changed: the chip loads all of them, and every image's sha is a
tracked artefact.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(HERE, "a2"), os.path.join(ROOT, "test")):
    if _p not in sys.path:
        sys.path.append(_p)
import pe_isa as I  # noqa: E402

SUFFIX = ".cert.json"

#: Images that ship or go on the board: built with --require-cert (ruling 2). Paths are
#: repo-relative; each has a sidecar that must say "certified".
IMAGES_OF_RECORD = (
    "fpga/images/usbdev_fpga.hex",
)
#: Images of record built by another agent's builder; their builders take --require-cert
#: when that agent wires it (listed so the gate names them, not silently skipped).
IMAGES_OF_RECORD_PENDING = (
    ("usbdev_dev.hex", "test/run_usbaddr.py (agent 1): pass --require-cert to its writer"),
)


class Uncertified(Exception):
    """--require-cert on an uncertified image; str() is the stamp's reason."""


def _words(img, base):
    a = base
    while a + I.ACT_BYTES <= min(len(img), I.STORE_BYTES):
        yield a, I._unpack(I.ACT_FIELDS, img[a:a + I.ACT_BYTES], I.ACT_BYTES)
        a += I.ACT_BYTES


def _tuple(x):
    if x["op"] == I.OP_LOOP:
        return (x["op"], 0, 0, (x["count"] << I.PINB_W) | x["pinb"], x["q"])
    return (x["op"], x["pin"], x["level"], x["delay"], x["q"])


def image_lanes(img):
    """{lane: [(op, pin, level, delay, q)]} decoded from the image, as compute_j reads them"""
    img = bytes(img)
    heads = {ln: I.read_header(img, ln)["base"] for ln in range(I.N_LANES)}
    bases = sorted(set(heads.values()))
    # the shared park word: a base several lanes share whose word is a lone REARM
    parked = set()
    for b in bases:
        sharers = [ln for ln, v in heads.items() if v == b]
        first = next(_words(img, b), (None, None))[1]
        if len(sharers) > 1 and first is not None and first["op"] == I.OP_REARM:
            parked.add(b)
    out = {}
    for ln in range(I.N_LANES):
        b = heads[ln]
        if b in parked:
            continue
        nxt = min([x for x in bases if x > b] or [I.STORE_BYTES])
        acts = []
        for a, x in _words(img, b):
            if a >= nxt:
                break
            acts.append(_tuple(x))
            if x["op"] in (I.OP_REARM, I.OP_LOOP):
                break
        out[ln] = acts
    return out


def stamp_lanes(lanes):
    """the stamp of a program given as pe_asm lanes (5- or 6-tuples)"""
    import pe_asm
    ln, _c = pe_asm.split_counts(lanes)
    try:
        d_min, j = pe_asm.compute_j(ln)
    except pe_asm.Reject as e:
        return {"status": "uncertified", "reason": "compute_j refuses: %s" % e,
                "d_min": None, "J": None}
    return {"status": "certified", "reason": "pe_asm.compute_j", "d_min": d_min, "J": j}


def stamp(img):
    """THE FIELD: {'status': 'certified' | 'uncertified', 'reason', 'd_min', 'J'}"""
    return stamp_lanes(image_lanes(img))


def line(st):
    """the field as one line (the compiler's cert J_floor, pe_asm's report)"""
    if st["status"] == "certified":
        return "certified: J %d at d_min %d (pe_asm.compute_j)" % (st["J"], st["d_min"])
    return "UNCERTIFIED: %s" % st["reason"]


def require(st, what="image"):
    """--require-cert: raise Uncertified (same reason) unless the stamp is certified"""
    if st["status"] != "certified":
        raise Uncertified("%s: UNCERTIFIED: %s" % (what, st["reason"]))
    return st


def sidecar(path):
    return path + SUFFIX


def write(path, img, require_cert=False):
    """write `path` (the full store, pe_isa.write_image) and its stamp sidecar; with
    require_cert, an uncertified image raises Uncertified and NOTHING is written"""
    st = stamp(img)
    if require_cert:
        require(st, os.path.basename(path))
    full = I.write_image(path, img)
    rec = dict(st, image=os.path.basename(path), require_cert=bool(require_cert))
    with open(sidecar(path), "w", encoding="ascii", newline="\n") as fh:
        json.dump(rec, fh, indent=1, sort_keys=True)
        fh.write("\n")
    return full, st


def read(path):
    """the sidecar's field, or None if the image has none"""
    p = sidecar(path)
    if not os.path.exists(p):
        return None
    with open(p, encoding="ascii") as fh:
        return json.load(fh)


def read_hex(path):
    with open(path, encoding="ascii") as fh:
        return bytes(int(t, 16) for t in fh.read().split())
