"""WF1 -- every ACCEPTED bench image names its wire == feed witness, by name.

⛔⛔ WHY (Wilson, delay-0 REARM ruling, step 4). pe_asm ACCEPTED two programs
whose wire stream was not their feed -- the WS2812 3-sub-bit lane and the
shipped UART-rx build, each beside four d = 20 lanes -- and nothing in the bench
set noticed, because no check compared what reached the wire with what was fed
for those images. "Every program pe_asm accepts runs correctly" is the claim the
assembler and the flexibility story rest on; this gate makes every image's
standing against it VISIBLE, by name, on day one (WF1). WF2 (a pin-level
decoder, V2 tightened) and WF3 (each gap closed) turn OWED entries into
witnesses; the lock checklist requires OWED = 0 at the `sub-v1` SHA.

THE UNIVERSE: every image the bench set runs -- N1's (`test/*.hex` on disk,
minus `probe_*`), every `+IMG=` a `test/benchset.py` arm names (its `gen`
images built here by the sweep's own builder), and `fpga/images/*.hex`.
EXEMPT, by declaration elsewhere: N1's NON_ADMISSIBLE and the DELIBERATE refusal
images (wire != feed is allowed there). PINMAP images are NOT exempt (Wilson Q1:
real programs, refused only over a measurement pin).

THE FEED, DERIVED FROM THE IMAGE (never declared): a lane with OP_SHIFT carries
a TX feed (host bytes -> wire), one with OP_SHIFTIN / OP_READBIT an RX feed
(wire -> host bytes). An image with neither has no feed and needs no entry.

EVERY ACCEPTED IMAGE WITH A FEED HAS EXACTLY ONE ENTRY:
    WITNESS    an EXACT check (every byte, count exact, against the PEER /
               the feed, not the chip's own sampling), run by a CI gate: the
               runner must be in `ci/run_gates.sh`, carry a positive token in
               `ci/gate_tokens.txt`, and name the image -- or the image must be
               byte-identical to one that has such a witness (`same_as`).
    OWED       no exact witness yet; the gap and the step that closes it.
    MECHANISM  wire != feed BY DESIGN, with the reason -- AND a `check`: the
               CI runner that checks EXACTLY what the image is for, held to the
               witness rules (Wilson: MECHANISM must not become a third way for
               an absent result to pass).
RED: an accepted image with a feed and no entry; an entry for an image that is
exempt, absent, or has no feed (stale); a witness whose runner is not in CI,
has no token, or does not name its image; a `same_as` that is not identical.
"""

from __future__ import annotations

import glob
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(HERE, "a2"), os.path.join(ROOT, "test")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import gate_degenerate_fields as dgf                              # noqa: E402
import nonadmissible as NA                                        # noqa: E402
import pe_isa as I                                                # noqa: E402

WITNESS, OWED, MECHANISM = "WITNESS", "OWED", "MECHANISM"

#: ⛔⛔ THE REGISTRY. One entry per accepted image with a feed.
REGISTRY = {
    # ---- witnessed ---------------------------------------------------------
    "uart_rx_image.hex": (WITNESS, {
        "runner": "test/run_uartrx.py",
        "how": "tb_uartrx compares every push with what the PEER sent "
               "(`sent[]`), count exact, at T = 434 and T_MIN, +-3 %"}),
    "uart_rx_434.hex": (WITNESS, {
        "same_as": "uart_rx_image.hex",
        "how": "the board's BRAM image is byte-identical to the bench image"}),
    # ---- mechanism images: wire != feed by design ---------------------------
    # ⛔⛔ MECHANISM IS NOT "UNCHECKED" (Wilson): each names the CI runner that
    # checks EXACTLY what the image is for, held to the witness rules (in CI,
    # positive token, names the image).
    "uart_rx_434_nostop.hex": (MECHANISM, {
        "why": "the PC loader's count-back demonstrator and run_uartrx's "
               "`nostop` must-fire: the stop sample is dropped ON PURPOSE, so "
               "the framing check is gone and the host stream is one byte per "
               "frame, not the program's two",
        "runner": "test/run_uartrx.py",
        "check": "tracked == pe_asm nostop build, byte exact; +PPF=1 at "
                 "-3..+3 %, two seeds: ONE push per frame, each the peer's "
                 "byte, count exact"}),
    "rxfast_image.hex": (MECHANISM, {
        "why": "tb_rxbw's link-capacity probe: a receiving lane completes a "
               "byte every 24 cycles against the 50-cycle payload slot, so "
               "the one-deep `rx_pend` DROPS bytes by design",
        "runner": "test/run_rxfast.py",
        "check": "tb_rxbw +SATURATED=1: every slot used, payload = capacity, "
                 "drops = completions - capacity - in flight, exactly; "
                 "must-fire: d = 60 (unsaturated) is red"}),
    # ---- owed (WF2 / WF3) ----------------------------------------------------
    "census_image.hex": (OWED, {
        "gap": "TX (unclocked SHIFT) and RX (SHIFTIN/READBIT): no wire check "
               "at all", "closes": "WF3"}),
    "ckheavy_image.hex": (OWED, {
        "gap": "three clocked SHIFT lanes, never fed where a verdict is read",
        "closes": "WF3 (a fed arm graded by WF2)"}),
    "half_image.hex": (OWED, {
        "gap": "tb_half checks 4 bytes per lane, TX from the drive decision "
               "not the pin; unclocked SHIFT is outside V2",
        "closes": "WF2 (unclocked TX at the pin) + WF3"}),
    "i2cframe_image.hex": (OWED, {
        "gap": "bit-banged I2C: only 'the peer ACKed'; sigrok frame check is "
               "local, not CI", "closes": "WF2 + WF3"}),
    "i2caddr_image.hex": (OWED, {
        "gap": "only the peer's address register end state",
        "closes": "WF2 + WF3"}),
    "onewire_image.hex": (OWED, {
        "gap": "RX exact (ROM, scratchpad vs the model); TX only via the "
               "chip's self-sampled echo -- the peer's decoded command stream "
               "is not compared, reset/poll symbols unchecked",
        "closes": "WF3 (parse OW-MODEL cmd)"}),
    "onewire_fpga_image.hex": (OWED, {
        "gap": "as onewire_image.hex", "closes": "WF3"}),
    "corpus_i2c.hex": (OWED, {
        "gap": "V2 + rx_e2e: bit-exact on clocked bits, but the chip's drive "
               "not the bus, and the count is partial",
        "closes": "WF2 (bus per ownership window, count exact)"}),
    "ckread_image.hex": (OWED, {
        "gap": "as corpus_i2c (V2 + rx_e2e; sigrok check local only)",
        "closes": "WF2"}),
    "ckfive_image.hex": (OWED, {
        "gap": "V2 only (drive not bus, partial count)", "closes": "WF2"}),
    "ckod_image.hex": (OWED, {
        "gap": "V2 only (drive not bus, partial count)", "closes": "WF2"}),
    "probe_cov_pindiv.hex": (OWED, {
        "gap": "V2 covers its clocked SHIFTs; its unclocked SHIFTs are not "
               "checked", "closes": "WF2"}),
    "probe_cov_cemodes.hex": (OWED, {
        "gap": "V2 only (drive not bus, partial count)", "closes": "WF2"}),
}


def feed_of(img):
    """{'TX', 'RX'} the image's lanes carry, from its opcodes."""
    out = set()
    for _ln, _h, a in dgf.walk(img):
        if a["op"] == I.OP_SHIFT:
            out.add("TX")
        elif a["op"] in (I.OP_SHIFTIN, I.OP_READBIT):
            out.add("RX")
    return out


def bench_images():
    """Every `+IMG=` a benchset arm names, its `gen` images built first."""
    import benchset
    names, probs = set(), []
    for top, cfg in sorted(benchset.CONFIG.items()):
        err = benchset.generate(cfg, top)
        if err:
            probs.append(err)
        arms = cfg.get("arms")
        if not isinstance(arms, list):
            continue
        for arm in arms:
            args = [a for f in arm[1:] if isinstance(f, list) for a in f]
            for a in args:
                m = re.match(r"\+IMG=(.+\.hex)$", a)
                if m:
                    names.add(os.path.normpath(os.path.join(ROOT, m.group(1))))
    return names, probs


def universe():
    paths, probs = bench_images()
    for p in glob.glob(os.path.join(ROOT, "test", "*.hex")):
        if not os.path.basename(p).startswith("probe_"):
            paths.add(os.path.normpath(p))
    for p in glob.glob(os.path.join(ROOT, "fpga", "images", "*.hex")):
        paths.add(os.path.normpath(p))
    imgs = {}
    for p in sorted(paths):
        n = os.path.basename(p)
        if not os.path.isfile(p):
            probs.append("%s is named by a bench arm but is not on disk" % n)
            continue
        imgs[n] = dgf.load(p)
    return imgs, probs


def ci_runners():
    with open(os.path.join(ROOT, "ci", "run_gates.sh"), encoding="utf-8") as fh:
        listed = {ln.strip() for ln in fh if ln.strip()
                  and not ln.strip().startswith("#")}
    with open(os.path.join(ROOT, "ci", "gate_tokens.txt"),
              encoding="utf-8") as fh:
        tok = {ln.split()[0] for ln in fh
               if ln.strip() and not ln.startswith("#")}
    return listed, tok


def audit(imgs, registry, exempt, listed, tokens):
    """Problems + rows. Pure, so the must-fires can price it."""
    probs, rows = [], []
    for n, img in sorted(imgs.items()):
        fd = feed_of(img)
        if n in exempt:
            rows.append((n, fd, "exempt", exempt[n]))
            if n in registry:
                probs.append("%s is exempt (%s) but has a wire-feed entry -- "
                             "stale" % (n, exempt[n]))
            continue
        ent = registry.get(n)
        if not fd:
            rows.append((n, fd, "no feed", ""))
            if ent:
                probs.append("%s has no SHIFT/SHIFTIN/READBIT, so no feed, but "
                             "has a %s entry -- stale" % (n, ent[0]))
            continue
        if ent is None:
            probs.append("%s carries a %s feed and has NO wire-feed entry "
                         "(WITNESS, OWED or MECHANISM)" % (n, "+".join(sorted(fd))))
            rows.append((n, fd, "UNDECLARED", ""))
            continue
        kind, d = ent
        rows.append((n, fd, kind, d.get("gap") or d.get("why")
                     or d.get("how", "")))
        if kind == MECHANISM and not d.get("check"):
            probs.append("%s is MECHANISM with no `check`: a mechanism image "
                         "is still checked exactly for what it is for" % n)
        if kind in (WITNESS, MECHANISM):
            if "same_as" in d:
                src = d["same_as"]
                if src not in imgs or imgs[src] != img:
                    probs.append("%s claims same_as %s but the bytes differ (or "
                                 "%s is absent)" % (n, src, src))
                elif registry.get(src, ("",))[0] != WITNESS:
                    probs.append("%s is same_as %s, which is not itself "
                                 "WITNESSED" % (n, src))
                continue
            r = d.get("runner", "")
            if r not in listed:
                probs.append("%s: witness runner %s is not in ci/run_gates.sh"
                             % (n, r))
            if r not in tokens:
                probs.append("%s: witness runner %s has no positive token in "
                             "ci/gate_tokens.txt" % (n, r))
            p = os.path.join(ROOT, r)
            body = open(p, encoding="utf-8").read() if os.path.isfile(p) else ""
            if n not in body:
                probs.append("%s: witness runner %s does not name the image"
                             % (n, r))
        elif kind != OWED:
            probs.append("%s: unknown entry kind %r" % (n, kind))
    for n in sorted(set(registry) - set(imgs)):
        probs.append("%s has a wire-feed entry but no such image exists -- "
                     "stale" % n)
    return probs, rows


def exempt_set():
    out = {n: "NON_ADMISSIBLE" for n in NA.NON_ADMISSIBLE}
    out.update({n: "DELIBERATE" for n in dgf.DELIBERATE})
    return out


def main() -> int:
    print()
    print("=" * 78)
    print("  WF1 -- EVERY ACCEPTED IMAGE NAMES ITS WIRE == FEED WITNESS")
    print("=" * 78)
    imgs, probs = universe()
    listed, tokens = ci_runners()
    exempt = exempt_set()
    p2, rows = audit(imgs, REGISTRY, exempt, listed, tokens)
    probs += p2
    counts = {}
    print("  %-28s %-6s %-11s %s" % ("image", "feed", "status", "detail"))
    for n, fd, st, det in rows:
        counts[st] = counts.get(st, 0) + 1
        print("  %-28s %-6s %-11s %s" % (n, "+".join(sorted(fd)) or "-", st,
                                         det[:60]))
    print()
    print("  %d image(s): %s" % (len(rows), ", ".join(
        "%d %s" % (v, k) for k, v in sorted(counts.items()))))
    rc = 0
    for p in probs:
        print("  *** %s" % p)
        rc = 1

    # ---- must-fire ----------------------------------------------------------
    # ⛔ PRICED ON THE REAL UNIVERSE: an entry removed, a stale entry, a
    # witness whose runner left CI, and a same_as whose bytes moved.
    print()
    print("  --- must-fire ---")
    def fires(label, reg, ims=imgs, lst=listed, tok=tokens, needle=""):
        got = audit(ims, reg, exempt, lst, tok)[0]
        hit = any(needle in g for g in got)
        print("    %-52s %s" % (label, "red  ok" if hit else "*** MISSED"))
        return hit
    ok = True
    r1 = dict(REGISTRY)
    r1.pop("census_image.hex")
    ok &= fires("census_image's entry removed -> undeclared", r1,
                needle="census_image.hex carries")
    r2 = dict(REGISTRY)
    r2["smoke_image.hex"] = (OWED, {"gap": "x", "closes": "x"})
    ok &= fires("an entry on a no-feed image (smoke) -> stale", r2,
                needle="smoke_image.hex has no SHIFT")
    ok &= fires("the UART-rx witness's runner dropped from CI", REGISTRY,
                lst=listed - {"test/run_uartrx.py"},
                needle="not in ci/run_gates.sh")
    ims = dict(imgs)
    b = bytearray(ims["uart_rx_434.hex"])
    b[-1] ^= 1
    ims["uart_rx_434.hex"] = bytes(b)
    ok &= fires("the board image no longer the bench image", REGISTRY,
                ims=ims, needle="bytes differ")
    r4 = dict(REGISTRY)
    r4["rxfast_image.hex"] = (MECHANISM, {"why": "drops by design"})
    ok &= fires("a MECHANISM with no check (rxfast, 'why' only)", r4,
                needle="MECHANISM with no `check`")
    ok &= fires("the rxfast mechanism check's runner dropped from CI",
                REGISTRY, lst=listed - {"test/run_rxfast.py"},
                needle="rxfast_image.hex: witness runner")
    r3 = dict(REGISTRY)
    r3["corpus_all5.hex"] = (OWED, {"gap": "x", "closes": "x"})
    ok &= fires("an entry on an exempt (NON_ADMISSIBLE) image", r3,
                needle="corpus_all5.hex is exempt")
    rc |= 0 if ok else 1

    owed = counts.get(OWED, 0)
    print()
    print("  OWED: %d image(s) without an exact witness -- the lock checklist "
          "requires 0 at the sub-v1 SHA (WF2, WF3)" % owed)
    print("  GATE wire-feed: %s" % ("PASSED" if rc == 0 else "*** FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
