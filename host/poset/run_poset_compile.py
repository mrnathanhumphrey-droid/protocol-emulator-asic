#!/usr/bin/env python3
"""run_poset_compile -- the gate for the compiler skeleton (host/poset/compile.py).

  C1 the end-to-end slice: emitter v2's SPI spec (v1 SPI image + golden records) compiles;
     the image is BYTE-IDENTICAL to run_pit_rt.emulation on the same parsed claims and seed
     (one source, no second lowering); width 1; words used <= 120; the WINDOW predicate in
     cycles equals the golden's own min / max for that bus; the cert says OWED / UNCERTIFIED
  C2 a cycle (A -> B, B -> A) is refused, naming the cycle
  C3 six independent chains are refused, naming the Dilworth width 6 > 5
  C4 Dilworth on a DAG where a path cover (3) is not a chain cover (2): width 2
  C5 a compound pattern is refused by name
  C6 a v1 spec the lowering cannot emulate is refused with the lowering's own reason
  C7 the USB co-resident threshold (Wilson 11-12 (i)): a USB image with a co-resident lane at
     dstar_retire_usb - 1 is refused naming that lane; at dstar_retire_usb that lane is not
     named (the image is still refused for its USB lane's pairs, C9); the same lane at - 1 in an
     image WITHOUT USB accepted
  C9 per-pair retirement spacing (Wilson 11-13): run_usbrx's receive image is refused naming
     EXACTLY its short pairs -- the last byte -> LEVEL (the floor rean_floor(d) / d nominal) and
     REARM -> ARM (the REARM's delay) -- and ARM -> LEVEL as outside the model; LEVEL -> the
     first byte carries the byte's held bits at the floor; on a plain lane every pair at
     dstar_retire_usb is ok and at - 1 every pair is short
Must-fires: every compile.MUTANTS entry, run IN-PROCESS through the same judge, turns this gate red.

POSITIVE TOKEN: `GATE poset_compile: PASSED`.
"""
from __future__ import annotations

import os
import random
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.join(ROOT, "test"))
import compile as C  # noqa: E402
import emit2 as E2  # noqa: E402
import golden as G  # noqa: E402
import run_poset_golden as RG  # noqa: E402
import run_pit_emit as V1T  # noqa: E402
from golden import key  # noqa: E402

#: gate_mutant_kills' scratch-mutant registry (ruling AC2): this gate is the killer
SCRATCH_MUTANTS = {
    "M_PC_NO_CYCLE": "killed in-process by this gate",
    "M_PC_NO_CLOSURE": "killed in-process by this gate",
    "M_PC_WINDOW_SWAP": "killed in-process by this gate",
    "M_PC_COMPOUND_PASS": "killed in-process by this gate",
    "M_PC_USB_NOCHECK": "killed in-process by this gate",
    "M_PC_PAIRS_NOCHECK": "killed in-process by this gate",
}
#: the literal above must name exactly the module's MUTANTS (checked at start-up)
if set(SCRATCH_MUTANTS) != set(C.MUTANTS):
    raise SystemExit("GATE poset_compile: FAILED -- SCRATCH_MUTANTS differs from C.MUTANTS")

HZ = G.clock.hz()
pit_emit = C.S.pit_emit


def body(*stmts):
    base = pit_emit.emit(bytes(V1T.IMAGES["spi"]()), HZ).rstrip("\n").splitlines()
    return "\n".join(base[:-1] + ["  " + s for s in stmts] + [base[-1]]) + "\n"


def usb_image(d_other, usb=True):
    """lane 0: a USB receive (or, without USB, plain LEVELs); lane 1: a co-resident lane whose
    every action is spaced `d_other`; lanes 2-4 parked. Shapes as run_usbrx.image()."""
    I = C.I
    D, DM = 40, 2                                   # the USB LS bit at 60 MHz; D- = uio[2]
    if usb:
        p0 = [I.act(I.OP_ARM, DM, 0, 0), I.act(I.OP_LEVEL, I.PIN_NONE, 0, D // 2),
              I.act_shiftin_usb(DM, D, 8), I.act_shiftin_usb(DM, D, 8),
              I.act(I.OP_REARM, 0, 1, D // 2)]
    else:
        p0 = [I.act(I.OP_LEVEL, I.PIN_NONE, 0, D)] * 3 + [I.act(I.OP_REARM, 0, 1, D)]
    p1 = [I.act(I.OP_LEVEL, I.UO0, 1, d_other), I.act(I.OP_LEVEL, I.UO0, 0, d_other),
          I.act(I.OP_REARM, 0, 1, d_other)]
    park = [I.act(I.OP_REARM, 0, 0, 500)]
    b0 = I.ACT_BASE
    b1 = b0 + len(p0) * I.ACT_BYTES
    bp = b1 + len(p1) * I.ACT_BYTES
    hdrs = [I.hdr(DM, I.PIN_NONE, 1, D, 0, 2 * D, 3 * D, b0),
            I.hdr(I.UO0, I.UO0, 1, d_other, 0, d_other, d_other + 20, b1)]
    hdrs += [I.hdr(n + 2, n + 2, 0, 500, 0, 200, 240, bp) for n in range(2, I.N_LANES)]
    return I.join_image(hdrs, p0 + p1 + park)


def refused_with(text, needle):
    try:
        C.compile_spec(text)
    except C.Refused as e:
        return needle in str(e), str(e)
    return False, "compiled"


def judge():
    probs = []
    # C1
    b, leads = RG.spi(1)
    ev = G.extract(*b.trace())
    recs = G.infer(ev, [(key("Fall", 3), "|>", key("Rise", 1))], HZ)
    res = bytes(V1T.IMAGES["spi"]())
    text = E2.emit2(res, recs, HZ)
    try:
        r = C.compile_spec(text, seed=7)
    except C.Refused as e:
        probs.append("C1 refused: %s" % e)
        r = None
    if r:
        import run_pit_rt as RT
        ref = bytes(RT.emulation(pit_emit.parse(pit_emit.emit(res, HZ)), random.Random(7))[0])
        if r["image"] != ref:
            probs.append("C1 image differs from run_pit_rt.emulation's (a second lowering?)")
        if r["width"] != 1:
            probs.append("C1 width %d, expected 1" % r["width"])
        if not 0 < r["words"] <= C.N_WORDS:
            probs.append("C1 words used %d, outside 1..%d" % (r["words"], C.N_WORDS))
        win = [p for p in r["checkset"] if p["pred"] == "WINDOW"]
        if len(win) != 1 or (win[0]["lo_cycles"], win[0]["hi_cycles"]) != (min(leads), max(leads)):
            probs.append("C1 window %s, the golden bus drew %d..%d cycles"
                         % ([(p["lo_cycles"], p["hi_cycles"]) for p in win], min(leads), max(leads)))
        rest = {a: v for a, v in r["cert"].items() if a != "usb_coresident"}
        if not all(v.startswith(("OWED", "UNCERTIFIED")) for v in rest.values()):
            probs.append("C1 cert claims more than the skeleton does: %s" % r["cert"])
        if r["cert"].get("usb_coresident") != "not applicable (no USB receive)":
            probs.append("C1 SPI image: usb_coresident %r" % r["cert"].get("usb_coresident"))
    # C8: POSET_SPEC.md's generated passages match the constants file
    import gen_spec_doc
    probs += ["C8 %s" % p for p in gen_spec_doc.stale()]
    # C7: the USB co-resident threshold (Wilson 11-12, option (i)), on images built by pe_isa
    lim = C.PC.load()["dstar_retire_usb"]
    for usb, d, want in ((True, lim - 1, "lane 1 refused"), (True, lim, "lane 1 clear"),
                         (False, lim - 1, "n/a")):
        try:
            _u, line = C.target_check(usb_image(d, usb))
            got = "n/a" if line.startswith("not applicable") else \
                  "lane 1 clear" if line.startswith("checked") else line
        except C.Refused as e:
            m = str(e)
            got = "lane 1 refused" if re.search(r"lane 1 word \d+: spacing %d < %d" % (d, lim), m) \
                else "lane 1 clear" if "lane 1 " not in m else "lane 1 refused otherwise: %s" % m
        if got != want:
            probs.append("C7 %s image, co-resident lane at d=%d: %s, expected %s"
                         % ("USB" if usb else "non-USB", d, got, want))
    # C9: per-pair retirement spacing (Wilson 11-13), on run_usbrx's own receive image
    import run_usbrx as RX
    I = C.I
    img = RX.image()
    h, acts = I.lane_programs(img)[I.USB_LANE]
    b0 = h["base_word"]
    rx = [i for i, x in enumerate(acts)
          if x["op"] == I.OP_SHIFTIN and x["mod"] & I.MOD_SELF_TIMED and x["level"]]
    rearm = [i for i, x in enumerate(acts) if x["op"] == I.OP_REARM]
    arm = [i for i, x in enumerate(acts) if x["op"] == I.OP_ARM]
    want_short = {(b0 + rx[-1], b0 + rx[-1] + 1), (b0 + rearm[-1], b0)}
    want_out = {(b0 + a, b0 + a + 1) for a in arm}
    try:
        C.target_check(img)
        msg = ""
    except C.Refused as e:
        msg = str(e)
    pat = r"lane %d pair word (\d+) \([^)]*\) -> word (\d+) \([^)]*\): " % I.USB_LANE
    short = {(int(a), int(b)) for a, b in re.findall(pat + "spacing", msg)}
    outside = {(int(a), int(b)) for a, b in re.findall(pat + "outside", msg)}
    if short != want_short:
        probs.append("C9 run_usbrx image: short pairs %s, expected exactly %s"
                     % (sorted(short), sorted(want_short)))
    if outside != want_out:
        probs.append("C9 run_usbrx image: outside-the-model pairs %s, expected %s"
                     % (sorted(outside), sorted(want_out)))
    pr = {(p["a"], p["b"]): p for p in C.PC.retire_pairs(img, I.USB_LANE)}
    first = acts[rx[0]]
    exp = {(b0 + rx[-1], b0 + rx[-1] + 1): (C.PC.rean_floor(RX.D), RX.D),
           (b0 + rearm[-1], b0): (acts[rearm[-1]]["delay"], acts[rearm[-1]]["delay"]),
           (b0 + rx[0] - 1, b0 + rx[0]): (
               acts[rx[0] - 1]["delay"] + (first["count"] - 1) * C.PC.rean_floor(first["delay"]),
               acts[rx[0] - 1]["delay"] + (first["count"] - 1) * first["delay"])}
    for key_, (s, n) in sorted(exp.items()):
        p = pr.get(key_)
        if not p or (p["spacing"], p["nominal"]) != (s, n):
            probs.append("C9 pair %s: %s, expected spacing %d / nominal %d"
                         % (key_, p and (p["spacing"], p["nominal"]), s, n))
    for d, want in ((lim, "ok"), (lim - 1, "short")):
        sts = {p["status"] for p in C.PC.retire_pairs(usb_image(d), 1)}
        if sts != {want}:
            probs.append("C9 plain lane at d=%d: pair statuses %s, expected all %s" % (d, sts, want))
    # C2
    ok, msg = refused_with(body("pattern Rise(uio1) -> Rise(uio2);", "pattern Rise(uio2) -> Rise(uio1);"),
                           "cycle")
    if not ok:
        probs.append("C2 cycle not refused by name: %s" % msg)
    # C3
    six = ["pattern Rise(uio%d) -> Fall(uio%d);" % (w, w) for w in range(6)]
    ok, msg = refused_with(body(*six), "Dilworth width 6 > 5")
    if not ok:
        probs.append("C3 width 6 not refused by name: %s" % msg)
    # C4
    nodes, edges = ["A", "B", "C", "D", "E"], {("A", "B"), ("D", "B"), ("B", "C"), ("B", "E")}
    w = C.dilworth_width(nodes, edges)
    if w != 2:
        probs.append("C4 Dilworth width %d on A,D < B < C,E; expected 2" % w)
    # C5
    ok, msg = refused_with(body("pattern Rise(uio1) or Fall(uio1);"), "not in the compiler skeleton")
    if not ok:
        probs.append("C5 compound pattern not refused by name: %s" % msg)
    # C6
    t = pit_emit.emit(bytes(V1T.IMAGES["refused"]()), HZ)
    ok, msg = refused_with(t, "lowering (run_pit_rt.emulation)")
    if not ok:
        probs.append("C6 non-emulable v1 spec not refused through the lowering: %s" % msg)
    return probs, r


def main() -> int:
    if os.environ.get("POSET_COMPILE_MUTANT"):
        try:
            probs, _ = judge()
        except Exception as e:
            probs = ["crash: %r" % e]
        print("MUTANT %s: %s" % (os.environ["POSET_COMPILE_MUTANT"], "RED" if probs else "green"))
        for p in probs[:3]:
            print("   ", p)
        return 1 if probs else 0
    print("poset compile: the compiler skeleton (clock %d Hz, %d program words)" % (HZ, C.N_WORDS))
    probs, r = judge()
    if r:
        for ln in r["log"]:
            print("   ", ln)
        for p in r["checkset"]:
            print("    checkset:", p)
        print("    cert:", r["cert"])
    for p in probs:
        print("  ***", p)
    for m in C.MUTANTS:
        # IN-PROCESS, through the same `judge` (gate_meta's stub hides the mutants too)
        C.MUT = m
        try:
            mp, _ = judge()
        except Exception as e:
            mp = ["crash: %r" % e]
        finally:
            C.MUT = ""
        red = bool(mp)
        print("  must-fire %-19s %s  %s" % (m, "RED (killed)" if red else "*** SURVIVED",
                                            (mp[0] if mp else "")[:80]))
        if not red:
            probs.append("mutant %s survived" % m)
    if probs:
        print("GATE poset_compile: FAILED (%d)" % len(probs))
        return 1
    print("GATE poset_compile: PASSED (C1-C9; %d / %d mutants killed)" % (len(C.MUTANTS), len(C.MUTANTS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
