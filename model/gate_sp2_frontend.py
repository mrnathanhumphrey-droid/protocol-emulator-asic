"""SP2 -- the pe_asm protocol front-end (`model/pe_proto.py`), held to the
shipped FRAM programs BYTE FOR BYTE.

THE CLAIM. A user writes the TRANSACTION ("write 3 bytes, then read 2"; "CS
frames of (1,0) (1,0) (6,0) (3,2)") and the front-end generates START,
repeated START, STOP and CS framing from context. The strong regression:
every hand-written FRAM program this repo verified on the wire is re-expressed
in front-end form, and the emitted image must equal the verified image
EXACTLY (all 256 store bytes). A difference is a FINDING, reported with the
first differing byte -- never absorbed by editing the reference.

THE SUBJECTS (reference = the tracked image where one exists, AND the
hand-written builder that produced it):
  corpus_i2c        test/corpus_i2c.hex      corpus.build_i2c        (write)
  corpus_spim       test/corpus_spim.hex     corpus.build_spi_master
                    + the mode0 / CLK_INV / both variants run_spifram builds
  ckread            test/ckread_image.hex    make_smoke_image.build_ckread
  ckack             run_ckack.image (scratch; certified by sigrok in
                    run_ckack -- S A0 A 01 A 23 A Sr A1 A d A d NACK P)
  ckack_half        run_ckack.image(d_half_fm, HALF_HIGH)

THE ADMISSIBILITY VERDICT is reported beside each identity: the front-end
goes through `pe_asm.assemble`, and `corpus_spim` at d = 7 is a declared
non-admissible TRACE image (N1) that the per-program 1.6a check refuses. It is
emitted for the identity with `timing_checks=False` -- under its name in the
non-admissible registry (`model/nonadmissible.py`), which is the only way
pe_asm will skip the pair -- and its refusal is EXPECTED BY NAME
(`expect_refused`, derived from that registry); any other refusal is red.
  M3  SP2/P2: an SPI header with no stated order is refused by the front-end
      (raw pe_asm keeps its documented LSB default, shown on the same header).

MUST-FIRES (each needs POSITIVE evidence of red, not just a non-zero exit):
  M1  a context rule mutated -- the repeated START emitted as STOP + START --
      must make ckack differ, at a NAMED byte, and the mutant image must be
      seen (decoded) to contain STOP immediately followed by START.
  M2  the comparator itself: the ckack reference with one planted flipped byte
      must be reported as differing at exactly that byte.

POSITIVE-TOKEN RULE (Wilson): `SP2-FRONTEND: PASSED` is printed only on the
success path, after the banner proves the comparison ran (encoder digest,
subject count, bytes compared). Anything else is red.
"""

from __future__ import annotations

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "test"))

import pe_asm                                  # noqa: E402
import pe_isa                                  # noqa: E402
import pe_proto as P                           # noqa: E402

import nonadmissible as NA                     # noqa: E402

#: SP2 subject -> its name in the non-admissible registry
#: (`model/nonadmissible.py`): a tracked image by its file name, a scratch
#: variant by its own registered name.
REG_NAME = {"corpus_spim": "corpus_spim.hex", "corpus_i2c": "corpus_i2c.hex",
            "ckread": "ckread_image.hex"}

#: subjects whose program is refused by the per-program timing checks, BY
#: NAME. ⭐ DERIVED FROM THE REGISTRY (Wilson, SP2/P4), no longer a second
#: list here: a subject is expected refused iff the registry lets it skip the
#: timing pair. Each must actually be refused (stale = red).
def expect_refused(names):
    return {n: NA.TIMING_EXEMPT[REG_NAME.get(n, n)]["why"] for n in names
            if NA.TIMING_OFF in NA.TIMING_EXEMPT.get(REG_NAME.get(n, n),
                                                     {"permits": ()})["permits"]}


def _read_hex(path):
    with open(path, encoding="ascii") as fh:
        return bytes(int(t, 16) for t in fh.read().split())


def first_diff(a, b):
    """-> None if identical, else the first differing index (length counts)."""
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            return i
    return None if len(a) == len(b) else min(len(a), len(b))


def subjects():
    """name -> (front-end args, [(reference label, reference bytes)])."""
    import corpus
    import make_smoke_image as msi
    import run_ckack
    scratch = os.environ.get("PE_SP2_TMP") or os.path.join(
        os.environ.get("TEMP", "/tmp"), "pe_sp2")
    os.makedirs(scratch, exist_ok=True)
    ck = run_ckack.image(os.path.join(scratch, "ckack.hex"))
    dh = run_ckack.d_half_fm()
    ckh = run_ckack.image(os.path.join(scratch, "ckack_half.hex"), d=dh,
                          flags=pe_isa.FLAG_HALF_HIGH)
    full = pe_isa.full_store
    out = {
        "corpus_i2c": (P.i2c_fram_write(),
                       [("test/corpus_i2c.hex",
                         _read_hex(os.path.join(ROOT, "test", "corpus_i2c.hex"))),
                        ("corpus.build_i2c()", full(corpus.build_i2c()[0]))]),
        "corpus_spim": (P.spi_fram(),
                        [("test/corpus_spim.hex",
                          _read_hex(os.path.join(ROOT, "test", "corpus_spim.hex"))),
                         ("corpus.build_spi_master()",
                          full(corpus.build_spi_master()[0]))]),
        "ckread": (P.i2c_read_timing(),
                   [("test/ckread_image.hex",
                     _read_hex(os.path.join(ROOT, "test", "ckread_image.hex"))),
                    ("make_smoke_image.build_ckread()",
                     full(msi.build_ckread()))]),
        "ckack": (P.i2c_fram_random_read(),
                  [("run_ckack.image()", _read_hex(ck))]),
        "ckack_half": (P.i2c_fram_random_read(d=dh,
                                              flags=pe_isa.FLAG_HALF_HIGH),
                       [("run_ckack.image(d=%d, HALF_HIGH)" % dh,
                         _read_hex(ckh))]),
    }
    for m0, inv in ((True, False), (False, True), (True, True)):
        nm = "corpus_spim%s%s" % ("_mode0" if m0 else "", "_inv" if inv else "")
        out[nm] = (P.spi_fram(mode0=m0, clkinv=inv),
                   [("corpus.build_spi_master(mode0=%s, clkinv=%s)" % (m0, inv),
                     full(corpus.build_spi_master(mode0=m0, clkinv=inv)[0]))])
    return out


def emit(args, name=None):
    """-> (image, verdict). The verdict is pe_asm's FULL one; the image is
    emitted with the timing pair skipped only if that verdict refused -- and
    only under the subject's REGISTERED name (pe_asm refuses otherwise)."""
    lanes, headers, park = args
    try:
        return P.image(lanes, headers, park), "accepted"
    except pe_asm.Reject as e:
        return (P.image(lanes, headers, park, timing_checks=False,
                        exempt_as=REG_NAME.get(name, name)),
                "REFUSED: " + str(e)[:90])


def main() -> int:
    print("=" * 78)
    print("SP2 -- pe_asm protocol front-end, byte identity vs the shipped FRAM "
          "programs")
    print("=" * 78)
    print("  encoder digest %s; python %s" % (pe_isa.digest(),
                                              sys.version.split()[0]))
    rc = 0
    subj = subjects()
    EXPECT_REFUSED = expect_refused(subj)
    print("  expected refused (from model/nonadmissible.py): %s"
          % ", ".join(sorted(EXPECT_REFUSED)))
    compared = 0
    print("  %-22s %-9s %-44s %s" % ("program", "identity", "reference",
                                     "pe_asm verdict"))
    for name, (args, refs) in subj.items():
        img, verdict = emit(args, name)
        if len(img) != pe_isa.STORE_BYTES:
            print("  *** %s: front-end image is %d bytes" % (name, len(img)))
            rc = 1
            continue
        for label, ref in refs:
            ref = pe_isa.full_store(ref)
            i = first_diff(img, ref)
            compared += len(ref)
            if i is None:
                print("  %-22s %-9s %-44s %s" % (name, "IDENTICAL", label,
                                                 verdict[:40]))
            else:
                rc = 1
                print("  *** %-18s DIFFERS at byte %d (front-end %02X, %s %02X)"
                      % (name, i, img[i], label, ref[i]))
        refused = verdict.startswith("REFUSED")
        if refused != (name in EXPECT_REFUSED):
            rc = 1
            print("  *** %s: pe_asm %s but EXPECT_REFUSED %s it"
                  % (name, "refused" if refused else "accepted",
                     "lists" if name in EXPECT_REFUSED else "does not list"))
    # the same SPI transaction at a 1 MHz-class delay IS admissible -- the
    # refusal above is the trace image's d, not the front-end
    try:
        P.image(*P.spi_fram(d=25))
        print("  info: spi_fram(d = 25), the same transaction, passes pe_asm's "
              "full verdict")
    except pe_asm.Reject as e:
        print("  *** spi_fram(d = 25) refused: %s" % str(e)[:80])
        rc = 1

    # ---- M1: a mutated context rule must go red, with positive evidence ----
    print("  --- must-fire M1: repeated START emitted as STOP + START ---")
    ref = pe_isa.full_store(subj["ckack"][1][0][1])
    mimg, _v = emit(P.i2c_fram_random_read(
        rules=P.MUTANT_RSTART_AS_STOP_START), "ckack")
    i = first_diff(mimg, ref)
    ops = [a["op"] for a in pe_isa.lane_programs(mimg)[0][1]]
    stop_start = any(a == pe_isa.OP_STOP and b == pe_isa.OP_START
                     for a, b in zip(ops, ops[1:]))
    if i is not None and stop_start:
        print("    red: the mutant image DIFFERS at byte %d, and its lane 0 "
              "decodes STOP->START (%d actions vs %d)"
              % (i, len(ops), len(pe_isa.lane_programs(ref)[0][1])))
    else:
        print("    *** MUST-FIRE FAILED: diff=%s, STOP->START seen=%s"
              % (i, stop_start))
        rc = 1

    # ---- M2: the comparator itself, on a planted byte ----------------------
    print("  --- must-fire M2: one planted byte in the ckack reference ---")
    k = 77
    planted = bytearray(ref)
    planted[k] ^= 0x10
    img, _v = emit(subj["ckack"][0], "ckack")
    j = first_diff(img, bytes(planted))
    if j == k:
        print("    red: reported DIFFERS at byte %d, the planted byte" % j)
    else:
        print("    *** MUST-FIRE FAILED: comparator reported %s, planted %d"
              % (j, k))
        rc = 1

    # ---- M3: SP2/P2 -- an SPI lane must STATE its order in the front-end ---
    # ⭐ BOTH SIDES: the corpus SPI header with its 8th element (order)
    # stripped must be refused BY THE FRONT-END, naming the lane; the same
    # 7-element header through RAW pe_asm must still assemble (its documented
    # default) -- and come out LSB, which is exactly why the front-end refuses.
    print("  --- must-fire M3: an SPI header with no stated order ---")
    sl, sh, spark = P.spi_fram(d=25)
    bare = {ln: tuple(h[:7]) for ln, h in sh.items()}
    try:
        P.image(sl, bare, spark)
        print("    *** MUST-FIRE FAILED: the front-end accepted an SPI lane "
              "with no stated order")
        rc = 1
    except P.ProtoError as e:
        ok = "lane(s) [0]" in str(e) and "order" in str(e)
        print("    red: front-end REFUSED (%s)%s" % (str(e)[:60],
              "" if ok else " *** but did not name lane 0 / order"))
        rc |= 0 if ok else 1
    try:
        raw = pe_asm.assemble(sl, bare, park_pins=spark)
        o = pe_isa.lane_programs(raw)[0][0]["order"]
        print("    raw pe_asm, same header: accepted, order %s (the documented "
              "default)%s" % ("MSB" if o else "LSB",
                              "" if o == pe_isa.ORDER_LSB else " *** WRONG"))
        rc |= 0 if o == pe_isa.ORDER_LSB else 1
    except pe_asm.Reject as e:
        print("    *** raw pe_asm refused the default-order header: %s"
              % str(e)[:70])
        rc = 1
    try:
        P.SPI(1, 2, 3, 4, 25, None)
        print("    *** P.SPI accepted order=None")
        rc = 1
    except P.ProtoError:
        print("    red: P.SPI(order=None) refused at construction")

    print()
    print("  subjects %d, reference bytes compared %d" % (len(subj), compared))
    if rc == 0 and compared >= 256 * len(subj):
        print("  SP2-FRONTEND: PASSED")
        return 0
    print("  *** SP2-FRONTEND: FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
