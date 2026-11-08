#!/usr/bin/env python3
"""The PAIR, SHIFTI and the SELF-TIMED BYTE's gate (v2 primitive 3, bundle 2;
Wilson 11-08).

THE ONE CLAIM: on a push-pull pair (uio[0] = D+, uio[1] = D-) the chip drives
EXACTLY the waveform the golden derives from the program -- every cycle, two
whole passes -- with D- the complement of D+ except in a LEVEL mod-11 SE0
window, the only encoding that drives both low; a self-timed byte (SHIFTI,
SHIFT and SHIFTIN with mod[1]) is ONE action of `count` bits paced `d` apart
by the lane timestamp, its bit counter running 1..count-1 then retiring; and a
received self-timed byte arrives exactly once with the value sent.

THE GOLDEN: the TX program is a list of segments (oe pair, D+/D- pair,
cycles): a SHIFTI / SHIFT bit is `d` cycles of (11, ~b b), LEVEL pair is
(11, ~l l), SE0 is (11, 00), the READBIT pair release is oe 00 with the values
held, through the REARM's delay. Aligned at the first drive edge (`t0`), the
bench's reconstructed waveform must equal it cycle for cycle.

Bench: test/tb_pair.v. Images built here from pe_isa.
  P1  TX alone: the waveform, the both-low census, the bit counter cadence.
  P2  RX: a self-timed SHIFTIN receives the peer's byte, once, its 8 samples
      d apart.
  P3  TX with the four other lanes dispatching every D* cycles: report the
      worst edge deviation from the golden grid (Wilson's condition 2, the E
      term) -- a measurement, not a verdict.
  P4  pe_isa refuses the bad encodings.
  P5  must-fires: M_PAIR_COPY, M_PAIR_SE0_SHIFT, M_ST_EARLY each turn P1 red.

POSITIVE TOKEN: `GATE pair: PASSED`.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "model")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from toolchain import banner, tool      # noqa: E402
import pe_isa as I                      # noqa: E402
import sim_run                          # noqa: E402

BENCH = "test/tb_pair.v"
RTL = ["src/pe_engine.v", "src/pe_store.v", "src/project.v"]
GEN = "run_pair"
DP, DM, RXP = 0, 1, 2          # uio[0] = D+, uio[1] = D-, uio[2] = the RX peer
D = 40                         # USB LS: 40 cycles a bit at 60 MHz
SHI_BYTE = 0x2D
FEED = (0xA5, 0x3C, 0x96, 0x0F)
RX_BYTE, RX_T = 0x5A, 300


def _hdrs(lane0, busy=False):
    out = [lane0]
    for n in range(1, I.N_LANES):
        if busy:
            out.append(None)
        else:
            out.append(I.hdr(n + 2, n + 2, 0, 500, 0, 200, 240, 0))
    return out


def tx_program():
    """lane 0's words, and its golden segments for ONE pass + its bytes used."""
    words = [I.act_shifti(SHI_BYTE, DP, D, pinb=DM),
             I.act_shift_timed(DP, D, 8, q=0, pinb=DM),
             I.act_level_pair(DP, DM, 1, D),
             I.act_se0(DP, DM, 2 * D),
             I.act_level_pair(DP, DM, 0, D),
             I.act(I.OP_READBIT, DP, 0, D, pinb=DM, mod=I.MOD_PAIR),
             I.act(I.OP_REARM, 0, 1, D)]
    return words


def tx_golden(npass):
    """[(oe, out)] per cycle from t0 for `npass` passes; oe/out as 2-bit
    strings (bit 1 = D-, bit 0 = D+)."""
    cyc = []
    for p in range(npass):
        def bits(b):
            for i in range(8):
                v = (b >> i) & 1
                cyc.extend([("11", "%d%d" % (1 - v, v))] * D)
        bits(SHI_BYTE)
        bits(FEED[p % len(FEED)])
        cyc.extend([("11", "01")] * D)            # LEVEL pair 1: D+ 1, D- 0
        cyc.extend([("11", "00")] * (2 * D))      # SE0
        cyc.extend([("11", "10")] * D)            # LEVEL pair 0
        cyc.extend([("00", "10")] * (2 * D))      # released through READBIT + REARM
    return cyc


def image(kind):
    l0 = I.ACT_BASE
    if kind in ("tx", "busy"):
        prog = tx_program()
        h0 = I.hdr(DP, I.PIN_NONE, 1, D, 0, 2 * D, 3 * D, l0)
    else:   # rx: ARM on the start bit, half a bit more, one self-timed byte
        prog = [I.act(I.OP_ARM, RXP, 0, 0),
                I.act(I.OP_LEVEL, I.PIN_NONE, 0, D + D // 2),
                I.act_shiftin_timed(RXP, D, 8),
                I.act(I.OP_REARM, 0, 1, D)]
        # push-pull: an open-drain lane needs a uio clock pin (1.6s); SHIFTIN releases its pin
        h0 = I.hdr(RXP, I.PIN_NONE, 1, D, 0, 2 * D, 3 * D, l0)
    lp = l0 + len(prog) * I.ACT_BYTES
    headers = [h0]
    if kind == "busy":
        # four lanes toggling uo_out[0..3] every D* = 20 cycles: the engine busy
        for n in range(1, I.N_LANES):
            b = lp + (n - 1) * 3 * I.ACT_BYTES
            prog += [I.act(I.OP_LEVEL, I.UO0 + n - 1, 1, 20), I.act(I.OP_LEVEL, I.UO0 + n - 1, 0, 20),
                     I.act(I.OP_REARM, 0, 1, 20)]
            headers.append(I.hdr(I.UO0 + n - 1, I.UO0 + n - 1, 1, 20, 0, 40, 60, b))
    else:
        prog.append(I.act(I.OP_REARM, 0, 0, 500))
        for n in range(1, I.N_LANES):
            headers.append(I.hdr(n + 2, n + 2, 0, 500, 0, 200, 240, lp))
    return I.join_image(headers, prog)


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def build(out, defines=()):
    r = run([tool("iverilog"), "-g2012", "-I", ROOT, "-o", out, "-s", "tb_pair"]
            + ["-D%s" % d for d in defines] + [BENCH] + RTL)
    if r.returncode != 0:
        raise RuntimeError("build %s failed: %s" % (out, (r.stdout + r.stderr)[-400:]))


def sim(vvp, img, plus):
    r = run(sim_run.vvp([vvp, "+IMG=%s" % img] + plus, images=[img]))
    out = r.stdout + r.stderr
    ev = [(int(c), oe, o) for c, oe, o in re.findall(r"^EV (\d+) (\d\d) (\d\d)$", out, re.M)]
    cb = [(int(c), int(v)) for c, v in re.findall(r"^CB (\d+) (\d+)$", out, re.M)]
    rx = [(int(c), int(v), int(ln)) for c, v, ln in re.findall(r"^RX (\d+) (\d+) (\d+)$", out, re.M)]
    return ev, cb, rx, ("END" in out), out[-300:]


def waveform(ev, t0, n):
    """per-cycle (oe, out) for cycles t0 .. t0+n-1 from the change events."""
    cur, j, w = None, 0, []
    evs = sorted(ev)
    for c in range(t0, t0 + n):
        while j < len(evs) and evs[j][0] <= c:
            cur = (evs[j][1], evs[j][2]); j += 1
        w.append(cur)
    return w


def tx_problems(ev, cb, npass=2):
    """[problem] for a TX run against the golden -- THE judge the must-fires
    turn red (gate_meta stubs it)."""
    first = [e for e in ev if e[1] == "11"]
    if not first:
        return ["no drive at all"]
    t0 = first[0][0]
    gold = tx_golden(npass)
    got = waveform(ev, t0, len(gold))
    out = []
    bad = [i for i, (g, x) in enumerate(zip(gold, got)) if g != x]
    if bad:
        i = bad[0]
        out.append("waveform: %d of %d cycles differ, first at t0+%d: got %s, golden %s"
                   % (len(bad), len(gold), i, got[i], gold[i]))
    se0_gold = sum(1 for g in gold if g == ("11", "00"))
    se0_got = sum(1 for x in got if x == ("11", "00"))
    if se0_got != se0_gold:
        out.append("both-low cycles %d, golden %d (SE0 windows only)" % (se0_got, se0_gold))
    # the self-timed cadence: 1..7 then 0 per byte, d apart
    seq = [v for _c, v in cb]
    want = ([1, 2, 3, 4, 5, 6, 7, 0] * 2) * npass
    if seq[:len(want)] != want:
        out.append("bit counter %s, golden %s" % (seq[:16], want[:16]))
    gaps = [b[0] - a[0] for a, b in zip(cb[:7], cb[1:8])]
    if gaps and any(g != D for g in gaps):
        out.append("self-timed bits not %d apart: %s" % (D, gaps))
    return out


def rx_problems(cb, rx):
    out = []
    if [(v, ln) for _c, v, ln in rx] != [(RX_BYTE, 0)]:
        out.append("received %s, golden one byte 0x%02X on lane 0" % ([(hex(v), ln) for _c, v, ln in rx], RX_BYTE))
    seq = [v for _c, v in cb]
    if seq[:8] != [1, 2, 3, 4, 5, 6, 7, 0]:
        out.append("RX bit counter %s" % seq[:8])
    gaps = [b[0] - a[0] for a, b in zip(cb[:7], cb[1:8])]
    if any(g != D for g in gaps):
        out.append("RX samples not %d apart: %s" % (D, gaps))
    return out


def run_all(vvp, tmp):
    hexes = {}
    for k in ("tx", "rx", "busy"):
        p = os.path.join(tmp, "pair_%s.hex" % k)
        I.write_image(p, image(k))
        sim_run.scratch_image(GEN, p)
        hexes[k] = p
    res = {}
    ev, cb, _rx, end, tail = sim(vvp, hexes["tx"], ["+NCYC=2600", "+FEED=1"])
    res["tx"] = (tx_problems(ev, cb) if end else ["tx: no END (%s)" % tail]), ev, cb
    ev, cb, rx, end, tail = sim(vvp, hexes["rx"], ["+NCYC=900", "+RXB=%d" % RX_BYTE, "+RXT=%d" % RX_T,
                                                    "+RXD=%d" % D])
    res["rx"] = (rx_problems(cb, rx) if end else ["rx: no END (%s)" % tail]), ev, cb
    ev, cb, _rx, end, tail = sim(vvp, hexes["busy"], ["+NCYC=2600", "+FEED=1"])
    res["busy"] = ([] if end else ["busy: no END"]), ev, cb
    return res


def jitter(ev, npass=2):
    """worst |edge - golden edge| over lane 0's drive changes, aligned at t0"""
    first = [e for e in ev if e[1] == "11"]
    if not first:
        return None
    t0 = first[0][0]
    gold = tx_golden(npass)
    gedges = [i for i in range(1, len(gold)) if gold[i] != gold[i - 1]]
    got = sorted(c - t0 for c, _oe, _o in ev if c > t0 and c - t0 < len(gold))
    if len(got) != len(gedges):
        return "edge count %d vs golden %d" % (len(got), len(gedges))
    return max(abs(a - b) for a, b in zip(got, gedges))


#: encodings pe_isa must refuse: name -> (lane-0 word, lane-0 header kind)
BAD = {
    "se0_level1": (I.act(I.OP_LEVEL, DP, 1, D, pinb=DM, mod=I.MOD_SE0), "pp"),
    "level_mod10": (I.act(I.OP_LEVEL, DP, 0, D, pinb=DM, mod=2), "pp"),
    "pair_on_od": (I.act_level_pair(DP, DM, 1, D), "od"),
    "pair_pinb_self": (I.act_level_pair(DP, DP, 1, D), "pp"),
    "pair_pinb_lane1": (I.act_level_pair(DP, 3, 1, D), "pp"),
    "timed_clocked": (I.act_shift_timed(DP, D, 8), "clk"),
    "timed_count0": (I.act(I.OP_SHIFTIN, DP, 0, D, count=0, mod=I.MOD_SELF_TIMED), "pp"),
    "shifti_level1": (I.act(I.OP_SHIFTI, DP, 1, D), "pp"),
    "readbit_mod1": (I.act(I.OP_READBIT, DP, 0, D, mod=I.MOD_SELF_TIMED), "pp"),
}

MUTANTS = [
    ("M_PAIR_COPY", "pinb a plain copy, not the complement"),
    ("M_PAIR_SE0_SHIFT", "SHIFT's mod 11 drives SE0"),
    ("M_ST_EARLY", "a self-timed byte retires one bit early"),
]


def main() -> int:
    banner("iverilog", "vvp")
    print()
    print("=" * 78)
    print("The pin pair, SHIFTI, the self-timed byte (v2 primitive 3, bundle 2)")
    print("=" * 78)
    probs = []
    tmp = tempfile.mkdtemp(prefix="pe_pair_")
    vvp = os.path.join(tmp, "pair.vvp")
    build(vvp)
    for k in ("tx", "rx", "busy"):
        pr = I.pair_problems(image(k)) + I.branch_problems(image(k))
        if pr:
            probs.append("valid image %s refused: %s" % (k, pr))
    res = run_all(vvp, tmp)
    print("\n  P1 TX alone: %d events, bit-counter steps %d" % (len(res["tx"][1]), len(res["tx"][2])))
    for x in res["tx"][0]:
        print("    *** %s" % x)
    probs += res["tx"][0]
    print("  P2 RX: %s" % ("ok" if not res["rx"][0] else res["rx"][0]))
    probs += ["rx: " + x for x in res["rx"][0]]
    jit = jitter(res["busy"][1])
    print("  P3 TX with four lanes dispatching every 20 cycles: worst edge deviation = %s cycle(s)" % (jit,))
    probs += res["busy"][0]
    if not isinstance(jit, int):
        probs.append("busy run: %s" % jit)

    print("\n  P4 pe_isa refusals")
    for n, (word, kind) in BAD.items():
        l0 = I.ACT_BASE
        if kind == "pp":
            h0 = I.hdr(DP, I.PIN_NONE, 1, D, 0, 2 * D, 3 * D, l0)
        elif kind == "od":
            h0 = I.hdr(DP, I.PIN_NONE, 0, D, 0, 2 * D, 3 * D, l0)
        else:
            h0 = I.hdr(DP, 5, 1, D, 0, 2 * D, 3 * D, l0)
        prog = [word, I.act(I.OP_REARM, 0, 1, D), I.act(I.OP_REARM, 0, 0, 500)]
        lp = l0 + 2 * I.ACT_BYTES
        hs = [h0] + [I.hdr(n2 + 2, n2 + 2, 0, 500, 0, 200, 240, lp) for n2 in range(1, I.N_LANES)]
        pr = I.pair_problems(I.join_image(hs, prog))
        print("    %-16s %s" % (n, "refused" if pr else "*** ACCEPTED"))
        if not pr:
            probs.append("pe_isa accepted %s" % n)

    print("\n  P5 must-fires")
    for d, what in MUTANTS:
        mv = os.path.join(tmp, "pair_%s.vvp" % d)
        try:
            build(mv, [d])
        except RuntimeError as exc:
            probs.append("%s: %s" % (d, exc))
            continue
        r = run_all(mv, tmp)
        red = r["tx"][0]
        print("    %-18s %-42s %s" % (d, what, ("RED: " + red[0][:60]) if red else "*** SURVIVED"))
        if not red:
            probs.append("%s survived" % d)

    print()
    if probs:
        print("  GATE pair: FAILED (%d)" % len(probs))
        for x in probs:
            print("    - %s" % x)
        return 1
    print("  GATE pair: PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
