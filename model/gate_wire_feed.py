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

THE UNIVERSE: `model/image_universe.py`, shared by every image-enumerating
writer and gate -- `test/*.hex` on disk minus `probe_*`, every `+IMG=` a
`test/benchset.py` arm names (its `gen` images built by the sweep's own
builder), and `fpga/images/*.hex`. (This said "N1's" universe; N1 scanned
test/ only until the unify, so the claim was false.)
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
    INTERNAL   not a published claim, checked ANOTHER way (Wilson): names the
               CI check that already runs it (`checked_by`, in CI with a
               token) and what that check proves. Not a witness, and no
               further work is owed.
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
INTERNAL = "INTERNAL"

#: ⛔⛔ THE REGISTRY. One entry per accepted image with a feed.
REGISTRY = {
    # ---- witnessed ---------------------------------------------------------
    "uart_rx_image.hex": (WITNESS, {
        "runner": "test/run_uartrx.py",
        "how": "tb_uartrx compares every push with what the PEER sent "
               "(`sent[]`), count exact, at T = 434 and T_MIN, +-3 %"}),
    "uart_tx_image.hex": (WITNESS, {
        "runner": "test/run_uarttx.py",
        "how": "tb_uarttx's peer on its own clock at 115200: every frame "
               "from the first the host's byte in order, stop "
               "bits 1, middle-80 % timing window; V3 exact; V3-T in bound"}),
    "uart_tx_busy_image.hex": (WITNESS, {
        "runner": "test/run_uarttx.py",
        "how": "the same, beside four push-pull lanes at d = D*"}),
    "ws2812_sub3_rearm21.hex": (WITNESS, {
        "runner": "test/run_wirefeed_mf.py",
        "how": "the WS2812 3-sub-bit control (REARM d = 21) beside four "
               "d = 20 lanes: V3 content exact on the bus, count exact, and "
               "V3-T worst response within its pyRTA bound"}),
    "uart_rx_434.hex": (WITNESS, {
        "same_as": "uart_rx_image.hex",
        "how": "the board's BRAM image is byte-identical to the bench image"}),
    # ⚠ SIMULATION: the hardware witness is the FPGA with the real MB85RS64V
    "corpus_spim25.hex": (WITNESS, {
        "runner": "test/run_spim_witness.py",
        "how": "SIMULATION, tb_trace + fram_spi model: every CS frame's MOSI "
               "decoded at the pins is the feed's frame in order (count "
               "exact), every READ's MISO is the peer's 5B C4, the chip's "
               "serial-host bytes equal the wire's; SCK at 1 MHz, phases >= "
               "the image's own A2 floor; one must-fire per check"}),
    # ⭐ HARDWARE, RECORDED: a bench witness re-checked in CI (Wilson 10-17) --
    # not a hardware run in CI. The board ran it; the record is checked here.
    "i2c_fram_fpga.hex": (WITNESS, {
        "runner": "model/gate_i2c_hw_witness.py",
        "how": "RECORDED BENCH WITNESS (PA100T-EDU, MB85RC256V, ~3.2 kOhm "
               "pull-ups, breadboard; DSLogic captures): sigrok's decoded "
               "events == the feed's transaction exactly in both captured "
               "runs, the FRAM's bytes == each run's old / new, persistence "
               "across a power-off, Fm timings in spec (fSCL 370.4 kHz "
               "measured); the record's image / feed SHA-256 must equal the "
               "repository's"}),
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
    # ---- internal: not published claims, checked another way (Wilson) -------
    # ⛔ INTERNAL IS NOT WITNESSED. Each names the CI check that already runs
    # it; that check proves what it proves (a digest proves which image ran
    # and that its streams match a record, not that its wire matched its
    # feed). The label stays true; no further work is owed on these.
    "census_image.hex": (INTERNAL, {
        "checked_by": "test/run_lockstep.py",
        "how": "dispatch and pin streams byte-identical to the recorded "
               "digests (TF4); also the two-simulator corpus trace"}),
    "ckheavy_image.hex": (INTERNAL, {
        "checked_by": "test/run_lockstep.py",
        "how": "lockstep digests; its A2 bound by gate_a2_program"}),
    "half_image.hex": (INTERNAL, {
        "checked_by": "test/run_lockstep.py",
        "how": "lockstep digests; tb_half's own 4-byte-per-lane and rx_e2e "
               "checks in the bench sweep"}),
    "i2cframe_image.hex": (INTERNAL, {
        "checked_by": "model/gate_sda_hold.py",
        "how": "every chip-driven SDA move holds across the fall (Layer H); "
               "the peer ACKs"}),
    "i2caddr_image.hex": (INTERNAL, {
        "checked_by": "test/run_lockstep.py",
        "how": "lockstep digests; the peer's address register end state"}),
    "onewire_image.hex": (INTERNAL, {
        "checked_by": "test/run_onewire.py",
        "how": "CE5: ROM and scratchpad exact against the model with CRC-8, "
               "every slot inside the DS18B20 windows, five must-fires"}),
    # ⭐ HARDWARE, RECORDED (Wilson lock order, the I2C pattern): capture 182359
    # of the OW = 1 build, re-checked in CI -- not a hardware run in CI.
    "onewire_fpga_image.hex": (WITNESS, {
        "runner": "model/gate_onewire_hw_witness.py",
        "how": "RECORDED BENCH WITNESS (PA100T-EDU, DS18B20 probe, 4.7 kOhm, "
               "breadboard; DSLogic capture 182359): sigrok's decoded events "
               "== DS18B20_TXN exactly, the probe's ROM and both CRC-8s, wire "
               "== the PC's run, every DQ low accounted for, DS18B20 windows "
               "met; the record's image / feed / params SHA-256 must equal the "
               "repository's. CE5's FPGA-timing arm (test/run_onewire.py) "
               "still runs it in simulation"}),
    "corpus_i2c.hex": (INTERNAL, {
        "checked_by": "test/gate_corpus_trace.py",
        "how": "the two-simulator pin trace; V2 + rx_e2e bit-exact on "
               "clocked bits; UM10204 phases (gate_um10204)"}),
    "ckread_image.hex": (INTERNAL, {
        "checked_by": "model/gate_sda_hold.py",
        "how": "Layer H on its SDA moves; V2 + rx_e2e; lockstep digests"}),
    "ckfive_image.hex": (INTERNAL, {
        "checked_by": "test/run_lockstep.py",
        "how": "lockstep digests; V2 on its clocked bits"}),
    "ckod_image.hex": (INTERNAL, {
        "checked_by": "model/gate_sda_hold.py",
        "how": "Layer H; V2 on its clocked bits; port demand measured"}),
    "probe_cov_pindiv.hex": (INTERNAL, {
        "checked_by": "test/gate_coverage.py",
        "how": "the coverage sweep's pin-diversity arm; V2 on its clocked "
               "SHIFTs"}),
    "probe_cov_cemodes.hex": (INTERNAL, {
        "checked_by": "test/gate_coverage.py",
        "how": "the coverage sweep's CE-modes arm; V2 on its clocked bits"}),
}


#: ⛔⛔ THE FIVE PUBLISHED LANES (Wilson, WF2 ruling 2): each needs an ACCEPTED
#: image, at or inside its published rating, that a CI check witnesses EXACT
#: (wire == feed, count exact). Found on the way: only UART-rx has one. Each
#: OWED line here counts toward OWED, which must be 0 at the sub-v1 SHA.
#: ⭐ Wilson (WF2 round 2): the RATED SPEED is a NUMBER for every lane
#: (`rate_hz`, the bit or clock rate the claim is made at, 50 MHz design
#: clock), and each witness runs AT that rate with V2/V3 tightened.
#: ⭐⭐ THE KEY IS THE DISPLAY LABEL; `ledger_id` IS THE TIMING LEDGER'S
#: STABLE INTERNAL NAME (Wilson: IDs are not claims). The README's lane table
#: shows these labels, and RD1 (`gate_stored_numbers`) matches each README row
#: to its ledger lane through `ledger_id` -- so a rating change is an edit
#: here, never ledger churn.
PUBLISHED = {
    "UART-rx 115200": (WITNESS, {"image": "uart_rx_image.hex",
                                 "rate_hz": 115200,
                                 "ledger_id": "UART-rx 115200"}),
    "UART-tx 115200": (WITNESS, {"image": "uart_tx_image.hex",
                                 "rate_hz": 115200,
                                 "ledger_id": "UART-tx 115200"}),
    # ⭐ CLOSED (was OWED: corpus_spim.hex is NON_ADMISSIBLE at d = 7 and the
    # d = 25 transaction existed only as run_spifram's local-only variants).
    # In SIMULATION; the hardware witness is the FPGA bring-up's.
    "SPI-master 1 MHz": (WITNESS, {"image": "corpus_spim25.hex",
                                   "rate_hz": 1000000,
                                   "ledger_id": "SPI-tx 1 MHz"}),
    # ⭐ Wilson: the ACHIEVED rate (CE1 HALF_HIGH), not the mode's nominal
    # 400 kHz -- so the rated number and the witnessed number are one number.
    # ⭐⭐ CLOSED ON HARDWARE (Wilson 10-17): BOTH numbers are published, each
    # with its conditions -- 397 kHz nominal (simulation, ideal edges) and
    # 370.4 kHz MEASURED (PA100T, ~3.2 kOhm pull-ups, breadboard; 365.0-374.5).
    # The rate depends on the bus by design: the chip waits for each real
    # rise. The rise-matched simulation reproduces the measured rate.
    "I²C Fast-mode 397 kHz nominal, 370.4 kHz measured": (WITNESS, {
        "image": "i2c_fram_fpga.hex",
        "rate_hz": 397000,
        "measured_hz": 370400,
        "ledger_id": "I2C 400 kHz"}),
    "SPI-target 1 MHz": (OWED, {"rate_hz": 1000000,
                                "ledger_id": "SPI-target 1 MHz",
        "gap": "NO functional SPI-target program exists: corpus_sptgt.hex is "
               "the async MISO-clear MECHANISM image (self-timed SHIFTs at "
               "d = 6, no clock pin, never synchronised to the master's SCK); "
               "nothing receives SCK and shifts a fed byte out on MISO"}),
}


def published_problems(registry, published):
    """A published lane claimed WITNESS must point at a WITNESSED image."""
    probs = []
    for lane, (kind, d) in sorted(published.items()):
        if not isinstance(d.get("rate_hz"), int) or d["rate_hz"] <= 0:
            probs.append("published lane %s has no numeric rated speed "
                         "(rate_hz)" % lane)
        if kind == WITNESS:
            img = d.get("image")
            if registry.get(img, ("",))[0] != WITNESS:
                probs.append("published lane %s claims WITNESS via %s, which "
                             "is not WITNESSED in the registry" % (lane, img))
        elif kind != OWED:
            probs.append("published lane %s: unknown kind %r" % (lane, kind))
    return probs


def feed_of(img):
    """{'TX', 'RX'} the image's lanes carry, from its opcodes."""
    out = set()
    for _ln, _h, a in dgf.walk(img):
        if a["op"] == I.OP_SHIFT:
            out.add("TX")
        elif a["op"] in (I.OP_SHIFTIN, I.OP_READBIT):
            out.add("RX")
    return out


def universe():
    """{name: image}, problems -- THE SHARED UNIVERSE (`model/image_universe.py`,
    Wilson 10-18). This gate's own enumeration was the widest of eight and is
    now the one every writer and gate uses."""
    import image_universe
    u = image_universe.default()
    return ({n: dgf.load(p) for n, p in u.items()}, list(u.probs))


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
                     or (("by %s: " % d["checked_by"]) if "checked_by" in d else "")
                     + d.get("how", "")))
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
        elif kind == INTERNAL:
            r = d.get("checked_by", "")
            if r not in listed:
                probs.append("%s is INTERNAL but its check %s is not in "
                             "ci/run_gates.sh" % (n, r))
            if r not in tokens:
                probs.append("%s is INTERNAL but its check %s has no positive "
                             "token" % (n, r))
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
    ok &= fires("an INTERNAL image's check dropped from CI (onewire)",
                REGISTRY, lst=listed - {"test/run_onewire.py"},
                needle="onewire_image.hex is INTERNAL but its check")
    r3 = dict(REGISTRY)
    r3["corpus_all5.hex"] = (OWED, {"gap": "x", "closes": "x"})
    ok &= fires("an entry on an exempt (NON_ADMISSIBLE) image", r3,
                needle="corpus_all5.hex is exempt")
    rc |= 0 if ok else 1

    # ---- V3's per-image table is current (WF2) ------------------------------
    # ⛔ The bench takes exempt / r_i / D_tol from `test/v3_table.vh` by its
    # loaded bytes; a stale table would judge a program by another's facts.
    import v3_table
    print()
    print("  --- test/v3_table.vh matches the registry, the bounds and the images ---")
    want = v3_table.text()
    try:
        with open(v3_table.OUT, encoding="utf-8") as fh:
            have = fh.read().replace("\r\n", "\n")
    except OSError:
        have = None
    if have != want:
        print("  *** test/v3_table.vh is %s -- run `python model/v3_table.py`"
              % ("absent" if have is None else "STALE"))
        rc = 1
    else:
        print("    current -- %d image(s), keyed by their bytes"
              % want.count("endcase  //"))
    # must-fire: an edited table, and a moved image byte, are both seen
    edited = want.replace("v3_tab = 16;", "v3_tab = 17;", 1)
    moved = bytearray(imgs["half_image.hex"])
    moved[200] ^= 1
    seen_edit = edited != want
    seen_move = v3_table.fnv(bytes(moved)) != v3_table.fnv(imgs["half_image.hex"])
    print("    must-fire: a hand-edited bound is not the generated text  %s"
          % ("red  ok" if seen_edit else "*** MISSED"))
    print("    must-fire: one image byte moved changes its key           %s"
          % ("red  ok" if seen_move else "*** MISSED"))
    rc |= 0 if (seen_edit and seen_move) else 1

    # ---- the five published lanes ------------------------------------------
    print()
    print("  --- the published lanes: an exact witness at the published rate ---")
    for lane, (kind, d) in sorted(PUBLISHED.items()):
        print("    %-18s %9s Hz %-8s %s" % (lane, d.get("rate_hz"), kind,
                                            d.get("image")
                                            or d.get("gap", "")[:80]))
    pp = published_problems(REGISTRY, PUBLISHED)
    for p in pp:
        print("  *** %s" % p)
        rc = 1
    bent = dict(PUBLISHED)
    bent["UART-tx 115200"] = (WITNESS, {"image": "census_image.hex"})
    hit = bool(published_problems(REGISTRY, bent))
    print("    must-fire: a lane claiming an OWED image as witness   %s"
          % ("red  ok" if hit else "*** MISSED"))
    rc |= 0 if hit else 1
    norate = dict(PUBLISHED)
    k, (kind0, d0) = next(iter(sorted(norate.items())))
    norate[k] = (kind0, {x: v for x, v in d0.items() if x != "rate_hz"})
    hit = any("rated speed" in p for p in published_problems(REGISTRY, norate))
    print("    must-fire: a lane with no numeric rated speed        %s"
          % ("red  ok" if hit else "*** MISSED"))
    rc |= 0 if hit else 1

    owed_lanes = sum(1 for k, _d in PUBLISHED.values() if k == OWED)
    print()
    # ⭐ THE LOCK RULE (Wilson): zero OWED PUBLISHED lanes -- the claims made
    # to the outside world. INTERNAL images are not published claims.
    print("  OWED published lanes: %d -- the lock requires 0 at the sub-v1 SHA. "
          "INTERNAL images (%d) are checked another way and are not published "
          "claims." % (owed_lanes, counts.get(INTERNAL, 0)))
    print("  GATE wire-feed: %s" % ("PASSED" if rc == 0 else "*** FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
