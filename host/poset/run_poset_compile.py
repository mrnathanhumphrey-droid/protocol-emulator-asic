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
Must-fires: every compile.MUTANTS entry, in a subprocess, turns this gate red.

POSITIVE TOKEN: `GATE poset_compile: PASSED`.
"""
from __future__ import annotations

import os
import random
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

HZ = G.clock.hz()
pit_emit = C.S.pit_emit


def body(*stmts):
    base = pit_emit.emit(bytes(V1T.IMAGES["spi"]()), HZ).rstrip("\n").splitlines()
    return "\n".join(base[:-1] + ["  " + s for s in stmts] + [base[-1]]) + "\n"


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
        if not all(v.startswith(("OWED", "UNCERTIFIED")) for v in r["cert"].values()):
            probs.append("C1 cert claims more than the skeleton does: %s" % r["cert"])
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
        env = dict(os.environ, POSET_COMPILE_MUTANT=m)
        rr = subprocess.run([sys.executable, os.path.abspath(__file__)], env=env,
                            capture_output=True, text=True)
        red = rr.returncode != 0 and ("MUTANT %s: RED" % m) in rr.stdout
        why = next((ln.strip() for ln in rr.stdout.splitlines()[1:2]), "")
        print("  must-fire %-19s %s  %s" % (m, "RED (killed)" if red else "*** SURVIVED", why[:80]))
        if not red:
            probs.append("mutant %s survived" % m)
    if probs:
        print("GATE poset_compile: FAILED (%d)" % len(probs))
        return 1
    print("GATE poset_compile: PASSED (C1-C6; %d / %d mutants killed)" % (len(C.MUTANTS), len(C.MUTANTS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
