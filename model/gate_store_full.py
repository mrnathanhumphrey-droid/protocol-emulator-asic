"""Ruling M -- every image writes the WHOLE store, and no lane can leave its program.

⛔⛔ WHY. The program store has no reset. A 51-byte image left 205 of the 256
store bytes NEVER WRITTEN, holding whatever the SRAM powered up as. A lane whose
PC reaches one of them executes it -- a random action on a real pin, the silent
class. The defect was found as a bench symptom (readback seeds disagreeing past
byte 51) but it is the chip's, and a host that loads a short program carries it.

⇒ M1: every image is `pe_isa.full_store(program)` -- the program, then the one
  defined word `pe_isa.STORE_FILLER` to the end of the store.
⇒ M3 (static half; `test/store_run.sh` is the simulated half): the PC moves in
  exactly three ways (+ACT_BYTES on a retiring non-REARM; to `l_base` on a
  looping REARM; not at all on a chaining REARM) and the prefetch reads only
  `l_pc`, `l_base` or `l_fpc` = last fetch + ACT_BYTES. So a lane leaves its
  program only if (a) its program has no terminating REARM, or (b) its header
  base lies outside the program. Both are refused here, per lane.
⇒ M2: this gate, over every image on disk.

THE FILLER, AND WHERE IT IS CLASSIFIED: a chaining `OP_REARM` (level 0) on
`PIN_NONE` at maximum delay, count 0, q 0. Its one non-default field is the pin,
and `gate_degenerate_fields.TABLE` row `("REARM", "pin", "PIN_NONE or >=
N_PINS")` classifies exactly that as DEFINED. It drives nothing (`OP_ARM,
OP_REARM: ;` in the dispatch arm) and it does not retire (`act_retire`), so a
lane that ever reached it would PARK there rather than walk on.
⚠ SAFE, NOT REFUSED: no encoding is refused for every lane, so a run-off is
silent in silicon. That is why (a) and (b) are refused HERE, before load.
"""

from __future__ import annotations

import glob
import io
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "test")):
    sys.path.insert(0, _p)

import gate_degenerate_fields as dgf                              # noqa: E402
import pe_isa as I                                                # noqa: E402

VH = os.path.join(ROOT, "test", "store_filler.vh")


def program_end(img):
    """Smallest aligned L with img == full_store(img[:L]); None if none."""
    for L in range(I.ACT_BASE, len(img) + 1, I.ACT_BYTES):
        try:
            if I.full_store(img[:L]) == img:
                return L
        except ValueError:
            return None
    return None


def audit(name, img):
    """Problems for one image. Pure, so the must-fires can price it."""
    if len(img) != I.STORE_BYTES:
        return ["%s is %d bytes: %d store byte(s) are NEVER WRITTEN and hold "
                "power-up contents" % (name, len(img),
                                       I.STORE_BYTES - len(img))], None
    L = program_end(img)
    if L is None:
        return ["%s does not end in the store filler (or ends mid-action)"
                % name], None
    probs = []
    for ln in range(I.N_LANES):
        h = dgf.unpack(I.HDR_FIELDS,
                       img[ln * I.HDR_BYTES:(ln + 1) * I.HDR_BYTES],
                       I.HDR_BYTES)
        b = h["base"]
        if not (I.ACT_BASE <= b < L) or (b - I.ACT_BASE) % I.ACT_BYTES:
            probs.append("%s lane %d: header base %d is outside its program "
                         "[%d, %d) or misaligned" % (name, ln, b, I.ACT_BASE, L))
            continue
    last = {}
    for ln, h, a in dgf.walk(img):
        last[ln] = (h["base"], a)
    for ln in range(I.N_LANES):
        if ln not in last:
            continue
        pc = _end_pc(img, ln)
        a = last[ln][1]
        if a["op"] != I.OP_REARM or pc is None or pc >= L:
            probs.append("%s lane %d runs off its program: its first REARM is "
                         "%s -- the fall-through path M3 names"
                         % (name, ln, "the store filler at %d" % pc
                            if pc is not None and pc >= L else "missing"))
    return probs, L


def _end_pc(img, ln):
    """The address of the action `walk` stops on for lane `ln`."""
    h = dgf.unpack(I.HDR_FIELDS, img[ln * I.HDR_BYTES:(ln + 1) * I.HDR_BYTES],
                   I.HDR_BYTES)
    pc, seen = h["base"], 0
    while pc + I.ACT_BYTES <= len(img) and seen < 200:
        a = dgf.unpack(I.ACT_FIELDS, img[pc:pc + I.ACT_BYTES], I.ACT_BYTES)
        if a["op"] == I.OP_REARM:
            return pc
        seen += 1
        pc += I.ACT_BYTES
    return None


def filler_checks():
    probs = []
    f = dgf.unpack(I.ACT_FIELDS, I.STORE_FILLER, I.ACT_BYTES)
    if not (f["op"] == I.OP_REARM and f["level"] == 0
            and f["pin"] == I.PIN_NONE and f["count"] == 0 and f["q"] == 0):
        probs.append("STORE_FILLER is not a chaining REARM on PIN_NONE with "
                     "count 0, q 0: %r" % (f,))
    row = dgf.TABLE.get(("REARM", "pin", "PIN_NONE or >= N_PINS"))
    if not row or row[0] != dgf.DEFINED:
        probs.append("the degenerate-field audit no longer classifies a REARM "
                     "on PIN_NONE as DEFINED -- the filler's classification")
    with io.open(VH, encoding="utf-8") as fh:
        if fh.read() != I.filler_vh():
            probs.append("test/store_filler.vh is STALE against "
                         "pe_isa.filler_vh() -- the bench sentinel would look "
                         "for a different word than the images hold")
    return probs


def sim_check(path):
    """Judge `test/store_run.sh`'s JSON. Returns 1 on any problem."""
    import json
    if not path or not os.path.isfile(path):
        print("    *** no sentinel measurement at PE_STORE_JSON -- run "
              "`bash test/store_run.sh`; the gate is RED rather than skipped")
        return 1
    with io.open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    rc = 0
    runs = d.get("runs", {})
    pads = {k: v for k, v in runs.items() if k.startswith("pad_")}
    if not pads:
        print("    *** no shipped-image arm in the measurement")
        rc = 1
    for k, v in sorted(pads.items()):
        good = v["captures"] > 0 and v["filler_fetches"] == 0
        print("    %-26s %6d capture(s), %d filler fetch(es)   %s"
              % (k, v["captures"], v["filler_fetches"],
                 "ok" if good else "*** RED"))
        if not good:
            rc = 1
    f = runs.get("falloff")
    hit = bool(f) and f["filler_fetches"] >= 1 \
        and f["lane0_named_at_first_filler"] == 1
    print("    %-26s must-fire: lane 0 named at address %s   %s"
          % ("falloff", d.get("first_filler_addr"),
             "ok" if hit else "*** MISSED"))
    rc |= 0 if hit else 1

    # ---- M5: silicon refuses a partial load ----------------------------------
    # ⛔ A FULL load must run unrefused, a 51-byte load must be refused before
    # any dispatch, and the same short load must RUN on M_NO_STORE_FULL -- or
    # the refusal is not the guard's doing.
    print("    --- M5: the chip refuses a partial load ---")
    for k, v in sorted(pads.items()):
        ok = v.get("store_full") == 1 and v.get("config_err") == 0 \
            and v.get("writebacks", 0) > 0
        print("    %-26s full load: store_full=%s config_err=%s, %s writebacks"
              "   %s" % (k, v.get("store_full"), v.get("config_err"),
                         v.get("writebacks"), "ok" if ok else "*** RED"))
        rc |= 0 if ok else 1
    s = runs.get("short51")
    ok = bool(s) and s.get("store_full") == 0 and s.get("config_err") == 1 \
        and s.get("writebacks") == 0
    print("    %-26s 51 bytes: refused (CONFIG_ERR, 0 writebacks)   %s"
          % ("short51", "ok" if ok else "*** MISSED"))
    rc |= 0 if ok else 1
    m = runs.get("mut_short51")
    ok = bool(m) and m.get("build") == "nofull" and m.get("writebacks", 0) > 0
    print("    %-26s M_NO_STORE_FULL: the same load RUNS (%s wb)   %s"
          % ("mut_short51", m.get("writebacks") if m else "-",
             "ok" if ok else "*** MISSED"))
    rc |= 0 if ok else 1
    return rc


def images():
    out = []
    for p in sorted(glob.glob(os.path.join(ROOT, "test", "*.hex"))):
        n = os.path.basename(p)
        if not n.startswith("probe_"):
            out.append((n, dgf.load(p)))
    return out


def main() -> int:
    print()
    print("=" * 78)
    print("  M -- EVERY IMAGE WRITES THE WHOLE STORE; NO LANE LEAVES ITS PROGRAM")
    print("=" * 78)
    fw = dgf.unpack(I.ACT_FIELDS, I.STORE_FILLER, I.ACT_BYTES)
    print("  filler  : %s = OP_REARM level %d pin %d delay %d count %d q %d"
          % (I.STORE_FILLER.hex(), fw["level"], fw["pin"], fw["delay"],
             fw["count"], fw["q"]))
    print("  classed : gate_degenerate_fields row (REARM, pin, PIN_NONE or "
          ">= N_PINS) = DEFINED")
    rc = 0
    probs = filler_checks()
    imgs = images()
    print("  images  : %d on disk" % len(imgs))
    print()
    print("  %-24s %6s %8s %7s" % ("image", "bytes", "program", "filler"))
    for name, img in imgs:
        p, L = audit(name, img)
        probs += p
        print("  %-24s %6d %8s %7s" % (name, len(img),
                                       "-" if L is None else L,
                                       "-" if L is None else len(img) - L))
    for p in probs:
        print("  *** %s" % p)
        rc = 1
    if not probs:
        print("  every image is the full store; every lane's base is inside its "
              "program and every lane ends on its own REARM")

    # ---- must-fires ---------------------------------------------------------
    print()
    print("  --- must-fire ---")
    i2c = next(img for n, img in imgs if n == "corpus_i2c.hex")
    L = program_end(i2c)
    checks = []
    p1, _ = audit("short51.hex", i2c[:L])
    checks.append(("a %d-byte image (the pre-M corpus_i2c)" % L,
                   any("NEVER WRITTEN" in x for x in p1)))
    import store_probe
    fall, _ = store_probe.build_falloff()
    p2, _ = audit("falloff.hex", I.full_store(fall))
    checks.append(("a lane with no terminating REARM",
                   any("runs off" in x for x in p2)))
    bad = bytearray(i2c)
    bad[0:I.HDR_BYTES] = I.hdr(I.UO0, I.UO0, 1, 20, 0, 40, 60, L)
    p3, _ = audit("base_in_filler.hex", bytes(bad))
    checks.append(("a header base pointing into the filler",
                   any("outside its program" in x for x in p3)))
    ok_clean, _ = audit("corpus_i2c.hex", i2c)
    checks.append(("the clean image is accepted", not ok_clean))
    for label, hit in checks:
        print("    %-46s %s" % (label, "ok" if hit else "*** MISSED"))
        if not hit:
            rc = 1

    # ---- the SIMULATED half: the bench sentinel (Layer M) ------------------
    # ⛔⛔ RED WITHOUT THE MEASUREMENT, like R and S. Layer M runs in every
    # bench, but on a clean image it can only ever say "0 filler fetches"; the
    # `falloff` arm of `test/store_run.sh` is what shows it CAN say otherwise.
    print()
    print("  --- the bench sentinel, measured (test/store_run.sh) ---")
    if sim_check(os.environ.get("PE_STORE_JSON")):
        rc = 1

    print()
    print("=" * 78)
    print("  GATE store-full: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
