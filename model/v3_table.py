"""v3_table -- GENERATE `test/v3_table.vh`: V3's per-image facts, keyed by the
image's own bytes.

⛔⛔ WHY A TABLE AND NOT A PLUSARG (WF2, found by the first full gate run).
V3 (`test/clocked_conform.vh`) needs three facts per image: whether it is
EXEMPT (NON_ADMISSIBLE / DELIBERATE -- Wilson's ruling 2), each lane's
published response bound r_i (pyRTA, ruling 1) and each lane's D_tol. Handing
them over as plusargs from `test/benchset.py` covered the coverage sweep and
nothing else: SIX other runners invoke the same benches directly
(gate_corpus_trace, run_mutants, run_cktx, ...), with scratch-named copies, and
every one went red for want of a bound or an exemption it was never given.
⇒ The bench identifies the program ITSELF: it snoops the store's write port
  during load and hashes what it wrote. This table, GENERATED from the
  registry and `test/lane_response_bounds.json`, maps that hash to the facts.
  No runner can forget it; a renamed copy is the same program; a program not
  in the table gets no bound (and V3-T is red if it transmits unclocked).

THE HASH (mirrored exactly by the bench): FNV-1a, 32 bit, over the 256 store
positions in address order, each position the written byte (0..255) or 256 if
the load never wrote it -- so a short load is not the same program as a full
one.
`gate_wire_feed.py` regenerates this text and requires the tracked file to be
identical (stale = red), with a must-fire.

Usage:  python model/v3_table.py          (writes test/v3_table.vh)
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(HERE, "a2"), os.path.join(ROOT, "test")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

OUT = os.path.join(ROOT, "test", "v3_table.vh")
RESP = os.path.join(ROOT, "test", "lane_response_bounds.json")
N_LANES = 5


def fnv(img):
    """The bench's hash of a loaded image (bytes written at 0..len-1)."""
    h = 0x811C9DC5
    for a in range(256):
        v = img[a] if a < len(img) else 256
        h = ((h ^ v) * 0x01000193) & 0xFFFFFFFF
    return h


def _gen_old_ws2812():
    import pe_asm
    import zero_spacing
    real = zero_spacing.find
    zero_spacing.find = lambda *_a, **_k: []
    try:
        return bytes(pe_asm.assemble(*pe_asm.ws2812_sub3(0)))
    finally:
        zero_spacing.find = real


def _gen_cktx():
    import tempfile
    import gate_degenerate_fields as dgf
    import run_cktx
    p = os.path.join(tempfile.mkdtemp(prefix="v3tab_"), "cktx.hex")
    run_cktx.image(p)
    return bytes(dgf.load(p))


def _gen_spim_d4():
    import corpus
    import pe_isa
    return bytes(pe_isa.full_store(bytes(corpus.build_spi_master(d=4)[0])))


def _gen_uart(T, variant):
    def f():
        import uart_rx
        return bytes(uart_rx.build(T, None, variant))
    return f


def _gen_uart_tx_msb():
    import uart_tx
    return bytes(uart_tx.build(uart_tx.T_NOMINAL, False, True))


def _gen_rxfast60():
    # ⛔ THE FULL STORE, as the runner writes it (make_smoke_image --rxfast 60
    # goes through pe_isa.write_image). This returned the bare 60-byte
    # program, whose hash no bench ever loads -- so the d = 60 arm was
    # V3-unknown from the day it was registered, and nobody saw: that arm is
    # a must-fire that is SUPPOSED to fail, and the V3-ID line was absorbed
    # into its expected red. Fatal V3-ID exposed it (WF2 #8 follow-up).
    import make_smoke_image
    import pe_isa
    return bytes(pe_isa.full_store(bytes(make_smoke_image.build_rxfast(60))))


def _gen_rxfast(d):
    """run_rxbw's sweep image at delay d (make_smoke_image --rxfast d, written
    through pe_isa.write_image -- the full store, as the bench loads it)."""
    def f():
        import make_smoke_image
        import pe_isa
        return bytes(pe_isa.full_store(bytes(make_smoke_image.build_rxfast(d))))
    return f


#: ⛔ run_rxbw's sweep points (10-22, documented-numbers audit item 1): every
#: one but d = 24 (the tracked rxfast_image.hex) had been V3-UNKNOWN -- fatal
#: -- since V3 became image-keyed, and run_rxbw is not in the suite, so its
#: boundary sweep sat broken unseen. Spelled out, not imported, so this table
#: does not depend on a runner's module state.
RXBW_SWEEP_D = (32, 40, 44, 45, 46, 47, 48, 49, 50, 52, 64)


def _gen_store_falloff():
    """store_run.sh's M3 must-fire: a lane with no terminating REARM."""
    import pe_isa
    import store_probe
    return bytes(pe_isa.full_store(store_probe.build_falloff()[0]))


def _gen_store_short51():
    """store_run.sh's M5 arm: corpus_i2c loaded as its 51 program bytes only
    -- the bench hashes exactly the bytes written, so 51, not 256."""
    import gate_degenerate_fields as dgf
    return bytes(dgf.load(os.path.join(ROOT, "test", "corpus_i2c.hex"))[:51])


def _gen_spim(mode0, clkinv):
    """run_spifram's scratch builds of corpus_spim (CI4 mode 0, CE2 CLK_INV)."""
    def f():
        import corpus
        import pe_isa
        img = corpus.build_spi_master(mode0=mode0, clkinv=clkinv)[0]
        return bytes(pe_isa.full_store(bytes(img)))
    return f


def _gen_ckack(half):
    """run_ckack's random read (`ckack.hex`), or its CE1 HALF_HIGH variant at
    the derived Fm delay (`ckack_half.hex`): the same calls it makes."""
    def f():
        import tempfile
        import gate_degenerate_fields as dgf
        import run_ckack
        from pe_isa import FLAG_HALF_HIGH
        p = os.path.join(tempfile.mkdtemp(prefix="v3tab_"), "ckack.hex")
        if half:
            run_ckack.image(p, d=run_ckack.d_half_fm(), flags=FLAG_HALF_HIGH)
        else:
            run_ckack.image(p)
        return bytes(dgf.load(p))
    return f


def _gen_ckhalf():
    """phases_run.sh's CE1 arm (`make_smoke_image --ckhalf`): the same call."""
    import make_smoke_image
    return make_smoke_image.ckhalf_store()


def _gen_sda_frame(k):
    """gate_sda_hold's `frame_image(hold + k)`: the same call it makes."""
    def f():
        import hold_bound
        import make_smoke_image
        import pe_isa
        return bytes(pe_isa.full_store(bytes(
            make_smoke_image.build_i2cframe(hold_bound.bound() + k))))
    return f


#: ⛔⛔ IMAGES A RUNNER BUILDS ON THE FLY (Wilson, WF2 round 2): registered
#: through their GENERATOR -- the same call the runner makes -- never waved
#: through. (name, generator, exempt, why). Found by making an unknown
#: fingerprint red and running the whole gate list. An exempt entry is a
#: declared non-admissible or refused program, with its reason.
GENERATED = (
    ("run_uartrx: uart_rx.build(T_MIN=232)", _gen_uart(232, "ok"), 0,
     "the published speed limit arm"),
    ("run_uartrx: uart_rx.build(434, edge)", _gen_uart(434, "edge"), 0,
     "the edge-sampling must-fire variant"),
    ("run_cktx: cktx.hex", _gen_cktx, 0, "TX4's clocked widths 1..8 image"),
    ("run_uarttx: uart_tx MSB-first", _gen_uart_tx_msb, 0,
     "the byte-order must-fire variant"),
    ("run_rxfast: rxfast d=60", _gen_rxfast60, 0,
     "the unsaturated must-fire (link not overrun)"),
    ("gate_corpus_trace: spim_d4", _gen_spim_d4, 1,
     "corpus_spim at d = 4 (EX1): the NON_ADMISSIBLE corpus_spim family"),
    # ⛔ FOUND LATE (WF2 #8 follow-up): gate_sda_hold reads only Layer H's
    # verdict, so its generated frames ran V3-red (unknown image, no bound)
    # without failing anything. Registered here; exempt because every one is
    # BELOW D* (d = hold .. hold + 3 = 15..18 < 20): a hold-window probe that
    # pe_asm would refuse, never a published program.
    # ⛔ FOUND LATE TOO: run_ckack runs only in the local A2 suite, which the
    # unknown-fingerprint sweep never ran, so its images were V3-red there.
    # ⛔ AND THESE, exposed by FATAL V3-ID on its first full run: every one
    # ran on an unknown image, and every runner still passed, because each
    # arm either failed anyway by design or read only one layer.
    ("run_spifram: corpus_spim mode0", _gen_spim(True, False), 0,
     "ruling CI4's mode-0 arm (SCK parked low before each select)"),
    ("run_spifram: corpus_spim CLK_INV", _gen_spim(False, True), 0,
     "ruling CE2's inverted-clock arm (SPI mode 1)"),
    ("run_spifram: corpus_spim mode0 + CLK_INV", _gen_spim(True, True), 0,
     "both: SCK parked and inverted (SPI mode 2)"),
    ("store_run: falloff", _gen_store_falloff, 1,
     "M3's must-fire: a lane with no terminating REARM -- broken on purpose"),
    ("store_run: corpus_i2c as 51 bytes", _gen_store_short51, 1,
     "M5's short load: REFUSED by the clean build, RUN by M_NO_STORE_FULL"),
    ("run_ckack: ckack.hex", _gen_ckack(False), 0,
     "the clocked random read (ruling ACK), sigrok-judged"),
    ("run_ckack: ckack_half.hex", _gen_ckack(True), 0,
     "the same read at CE1's HALF_HIGH Fm delay"),
    # ⛔ FOUND 10-22 (S1g): unregistered since V3-ID went fatal (3133e4c,
    # 10-13), so both CE1 half arms stopped at 34 us and gate_um10204 passed
    # on zero lanes. Nothing was red because phases_run checked only that a
    # trace file existed.
    ("phases_run: probe_ckhalf.hex", _gen_ckhalf, 0,
     "CE1's HALF_HIGH phase measurement (and its M_HALF_IGNORED must-fire)"),
    ("gate_sda_hold: i2cframe d = hold", _gen_sda_frame(0), 1,
     "the hold-window probe at d = SDA_HOLD, below D*"),
    ("gate_sda_hold: i2cframe d = hold + 1", _gen_sda_frame(1), 1,
     "the hold-window probe at d = SDA_HOLD + 1, below D*"),
    ("gate_sda_hold: i2cframe d = hold + 2", _gen_sda_frame(2), 1,
     "the hold-window probe at d = SDA_HOLD + 2, below D*"),
    ("gate_sda_hold: i2cframe d = hold + 3", _gen_sda_frame(3), 1,
     "the hold-window probe at d = SDA_HOLD + 3, below D*"),
    ("run_wirefeed_mf: old WS2812 (REARM d=0)", _gen_old_ws2812, 1,
     "the delay-0 build pe_asm REFUSES today; run only as the must-fire, "
     "with its V3 facts supplied by allowlisted override"),
)

#: run_rxbw's sweep images, registered the same way (see RXBW_SWEEP_D)
GENERATED_RXBW = tuple(("run_rxbw: rxfast d=%d" % _d, _gen_rxfast(_d), 0,
                        "run_rxbw's boundary sweep point d = %d" % _d)
                       for _d in RXBW_SWEEP_D)


#: GENERATED entries whose runner loads FEWER than 256 bytes on purpose (the
#: bench hashes exactly the bytes written)
SHORT_LOADS = {"store_run: corpus_i2c as 51 bytes"}


#: ⛔⛔ OVERRIDES MAY ONLY TIGHTEN (Wilson, WF2 round 2). A `+V3...` plusarg
#: that LOOSENS what the table says -- a wider bound, a bound where the table
#: has none, a higher D_tol, EXEMPT where the table judges, any underrun mode
#: other than "fed" -- is RED in the bench unless it is listed here with its
#: reason. (image name, field, value or None for any, why). Fields: "bound",
#: "dtol", "exempt", "underrun".
ALLOW = (
    ("ckfive_image.hex", "underrun", 1,
     "tb_csat measures dispatch spacing and pushes no host byte by design: "
     "every load underruns (held to that exactly)"),
    ("run_cktx: cktx.hex", "underrun", 2,
     "run_cktx's STARVE arm stops topping up the queues for a window on "
     "purpose (held to: at least one underrun)"),
    ("probe_cov_pindiv.hex", "underrun", 2,
     "run_cktx's STARVE arm on the pindiv image (same declared window)"),
    ("run_wirefeed_mf: old WS2812 (REARM d=0)", "bound", None,
     "the refused delay-0 build has no lane set of its own, so it is judged "
     "against its CONTROL's published bound (same five lanes, only the "
     "REARM's delay differs)"),
)
FIELD = {"bound": 1, "dtol": 2, "exempt": 3, "underrun": 4}


def rows():
    """[(name, hash, exempt, rb[5], dt[5])] for every image in WF1's universe
    and every image a runner generates (GENERATED)."""
    import gate_wire_feed as wf
    imgs, probs = wf.universe()
    if probs:
        raise RuntimeError("v3_table: " + "; ".join(probs))
    exempt = wf.exempt_set()
    for name, gen, ex, _why in GENERATED + GENERATED_RXBW:
        imgs[name] = gen()
        # ⛔ A GENERATOR RETURNS WHAT THE BENCH LOADS: the full store, since
        # every runner writes images through pe_isa.write_image. The rxfast
        # d = 60 entry returned the bare program and was unknown for a whole
        # arc. The one exception is declared: a deliberate short load.
        if len(imgs[name]) != 256 and name not in SHORT_LOADS:
            raise RuntimeError("v3_table: %s's generator returned %d bytes, "
                               "not the 256-byte store the bench loads"
                               % (name, len(imgs[name])))
        if ex:
            exempt[name] = "GENERATED (declared)"
    with open(RESP, encoding="utf-8") as fh:
        resp = json.load(fh)
    out, seen = [], {}
    for name, img in sorted(imgs.items()):
        h = fnv(img)
        rb, dt = [-1] * N_LANES, [-1] * N_LANES
        rec = resp.get(name)
        if rec:
            for ln, e in rec["lanes"].items():
                if e.get("r_pyrta") is not None:
                    rb[int(ln)] = int(e["r_pyrta"])
                dt[int(ln)] = int(e["dtol"])
        ex = 1 if name in exempt else 0
        row = (name, h, ex, rb, dt)
        if h in seen:
            # ⛔ two names, one program: identical facts are fine (the board
            # image IS the bench image); differing facts are a contradiction
            prev = seen[h]
            if prev[2:] != row[2:]:
                raise RuntimeError("v3_table: %s and %s are the same bytes but "
                                   "carry different V3 facts" % (prev[0], name))
            continue
        seen[h] = row
        out.append(row)
    return out


def text():
    lines = [
        "/* v3_table.vh -- GENERATED by model/v3_table.py. DO NOT EDIT.",
        " *",
        " * V3's per-image facts, keyed by the FNV-1a hash of the bytes the bench",
        " * loaded (position never written = 256). `field` 0: exempt (1) or not",
        " * (0); 1..5: lane 0..4 response bound r_i (pyRTA; -1 = none); 6..10:",
        " * lane 0..4 D_tol. Returns -2 for an image not in the table.",
        " * Sources: model/nonadmissible.py, model/gate_degenerate_fields.py",
        " * (DELIBERATE), test/lane_response_bounds.json (program_a2, pyRTA).",
        " */",
        "function integer v3_tab;",
        "  input [31:0] h;",
        "  input integer field;",
        "  begin",
        "    v3_tab = -2;",
        "    case (h)",
    ]
    names = []
    for name, h, ex, rb, dt in rows():
        vals = [ex] + rb + dt
        body = " ".join("%d: v3_tab = %d;" % (i, v) for i, v in enumerate(vals))
        lines.append("      32'h%08x: case (field) %s endcase  // %s"
                     % (h, body, name))
        names.append((h, name))
    lines += ["      default: v3_tab = -2;", "    endcase", "  end",
              "endfunction", "", "task v3_tab_name;", "  input [31:0] h;",
              "  begin", "    case (h)"]
    for h, name in names:
        lines.append("      32'h%08x: $display(\"  clocked_conform[V3] image: "
                     "%s (by its loaded bytes)\");" % (h, name))
    lines += ["      default: $display(\"  clocked_conform[V3] image: not in "
              "test/v3_table.vh (hash %h) -- no bound, not exempt\", h);",
              "    endcase", "  end", "endtask", ""]
    # the override allowlist, keyed by the same hash
    byname = {n: h for h, n in names}
    lines += ["/* the LOOSENING-override allowlist (model/v3_table.py ALLOW):",
              " * field 1 bound, 2 dtol, 3 exempt, 4 underrun; value -1 = any.",
              " * Returns 1 iff (image, field, value) is allowlisted. */",
              "function integer v3_allow;", "  input [31:0] h;",
              "  input integer field;", "  input integer value;", "  begin",
              "    v3_allow = 0;"]
    for name, field, value, why in ALLOW:
        if name not in byname:
            raise RuntimeError("v3_table ALLOW names %s, which is not in the "
                               "table" % name)
        cond = "h == 32'h%08x && field == %d" % (byname[name], FIELD[field])
        if value is not None:
            cond += " && value == %d" % value
        lines.append("    if (%s) v3_allow = 1;  // %s: %s" % (cond, name,
                                                                why[:60]))
    lines += ["  end", "endfunction", ""]
    return "\n".join(lines)


def main() -> int:
    t = text()
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(t)
    print("v3_table: %d image(s) -> %s" % (t.count("endcase  //"),
                                          os.path.relpath(OUT, ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
