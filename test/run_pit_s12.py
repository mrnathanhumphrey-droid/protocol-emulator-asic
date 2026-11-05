#!/usr/bin/env python3
"""v2 PIT stages 1-2 gate (Wilson 10-31, Track 3): the per-wire RESULTS RECORDS,
bytes 40..119, BIT FOR BIT against the frozen golden model.

THE ONE CLAIM: for every case, the 10-byte record the RTL writes for wire w at
40 + 10w equals record(w), built from model/pit_golden.py at f19f2177 (LF)
-- classify_bus(the capture AS STORED) for the class, its condition and the R2
guard, and stage1(wire_ivs) for P_hat, the phase, the score and n. The capture
as stored is the bench's own edge log through pit_capture_golden.encode /
decode, exactly as gate pit-s0 builds it (its cases are reused).
Layout (src/project.v, pe_pit_s12):
  b0 {cls[2:0], why[2:0], cond, wh}   b1 {idle, p16[18:16], fb[12:9]}
  b2 p16[15:8]  b3 p16[7:0]  b4 {fb[8], phase[14:8]}  b5 phase[7:0]
  b6 score (sat 255, 0 unless stage 1 OK)  b7 n (sat 255)  b8 frames (sat 255)  b9 fb[7:0]
                                                    token: GATE pit-s12: PASSED
"""
from __future__ import annotations

import os
import random
import sys
import tempfile
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "model")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from toolchain import banner                # noqa: E402
import pe_isa as I                          # noqa: E402
import sim_run                              # noqa: E402
import run_pit_capture as RP                # noqa: E402
import run_pit_s0 as R0                     # noqa: E402
import pit_s0_golden as S0                  # noqa: E402

REC_AT, REC_BYTES = 40, 10

# ---------------------------------------------------------------------------
# the gate's OWN cases: one wire each (or one plus a busy neighbour), short --
# stages 1-2 walk the capture ~500 times per wire, so a long capture is a long
# simulation (gate pit-s0's uarts_2to1, 497 edges: 601 s under iverilog)
# ---------------------------------------------------------------------------
def clock(half=20, n=60, j=0, seed=1):
    r = random.Random(seed); return [(i & 1, half + (r.randint(-j, j) if j else 0)) for i in range(n)]
def manch(half=16, nbits=40, seed=2):
    r = random.Random(seed); lv = []
    for _ in range(nbits):
        b = r.randint(0, 1); lv += [b, 1 - b]
    # the leading idle is > 15 bit periods: a shorter one is stored as a BODY run
    # (201 cycles = m 13 at P 16), and {1, 2, 13} is not Manchester (measured)
    segs = [(1, 600)]
    for l in lv:
        if segs[-1][0] == l: segs[-1] = (l, segs[-1][1] + half)
        else: segs.append((l, half))
    segs.append((1, 600)); return segs
def uart(bit=24, data=(0x55, 0xA3, 0x0F, 0x81, 0x3C, 0xE7), gap=400):
    segs = [(1, gap)]
    def put(l, c):
        if segs[-1][0] == l: segs[-1] = (l, segs[-1][1] + c)
        else: segs.append((l, c))
    for d in data:
        put(0, bit)
        for k in range(8): put(d >> k & 1, bit)
        put(1, bit); put(1, gap)
    return segs
def level(bit=20, n=60, seed=0):
    r = random.Random(seed); return [(i & 1, bit * r.choice([1, 1, 2, 3, 4, 5, 8, 9])) for i in range(n)]
def nobody(P0=20, n=40, seed=1):
    """every interval 16..23 periods of P0: stage 1 is OK (P0), every run idle"""
    r = random.Random(seed); return [(i & 1, P0 * r.choice([16, 17, 18, 19, 21, 23])) for i in range(n)]
def irreg(half=20, n=64):
    """a clock with every 5th half-period stretched x3, at both levels"""
    return [(i & 1, half * (3 if i % 5 == 2 else 1)) for i in range(n)]
def span(bit=20, nfr=6, gap=40):
    """frames between long idle-high gaps: a 12-bit low run first, so every L in
    7..12 fails its stop bit -- the class comes from the SPAN fallback"""
    segs = [(1, bit * gap)]
    for f in range(nfr):
        segs += [(0, bit * 12), (1, bit), (0, bit), (1, bit), (0, bit * (1 + f % 3)), (1, bit * gap)]
    return segs
def noise(n=60, seed=3):
    r = random.Random(seed); return [(i & 1, r.randint(17, 400)) for i in range(n)]
def nrzi(bit=10, n=80, seed=4):
    r = random.Random(seed); segs = []
    for i in range(n):
        m = 7 if i % 9 == 4 else r.randint(1, 6)
        segs.append((i & 1, m * bit))
    return segs

S12_WAVES = {
  "s12_clock": {0: clock()},
  "s12_clock_jit": {0: clock(half=40, n=80, j=3, seed=9)},
  # refine 2 MOVES P_hat here (golden, ideal capture: refine 1 -> 389, refine 2 -> 397): M_S12_NO_REF2's target
  "s12_clock_ref2": {0: clock(half=24, n=70, j=3, seed=0)},
  "s12_level": {0: level()},
  "s12_manch": {0: manch()},
  "s12_uart": {0: uart()},
  "s12_uart_busy": {0: uart(), 1: clock(half=30, n=140)},
  "s12_noise": {0: noise()},
  "s12_short": {0: clock(n=12)},
  "s12_nrzi": {0: nrzi()},
  # Wilson 10-31: the three paths no case reached
  "s12_nobody": {0: nobody()},
  "s12_irreg": {0: irreg()},
  "s12_span": {0: span()},
}

#: from gate pit-s0's set: the empty walk, and stage 0 refusing the bus
FROM_S0 = ["empty", "near_trip_D0_h4_m1", "k0", "frame2"]


def cases():
    """[(name, waves, mask, budget b, ncyc, None)] -- gate pit-s0's tuple shape"""
    out = []
    for name, wv in S12_WAVES.items():
        t_end = max(sum(c for _l, c in segs) for segs in wv.values())
        out.append((name, wv, 0x00, R0.budget_for(t_end + R0.T0 + 200), None, None))
    out += [c for c in R0.cases() if c[0] in FROM_S0]
    return out
C_NONE, C_CLOCK, C_MANCH, C_ASYNC, C_NRZI, C_LEVEL, C_UNK, C_ROLE = range(8)
CLS = {"CLOCK": C_CLOCK, "MANCHESTER": C_MANCH, "NRZ_ASYNC": C_ASYNC, "NRZI_STUFFED": C_NRZI,
       "LEVEL_CODE": C_LEVEL, "UNKNOWN": C_UNK}
#: the golden's `why` text -> the record's code (the first matching prefix)
WHY = [("%d intervals < " , 1), ("no candidate reaches", 2), ("non-harmonic rival", 3),
       ("no non-idle runs", 4), ("clock-shaped but irregular", 5), ("stage 0 refused", 6),
       ("sync-possible", 7)]


def why_code(text):
    for pre, code in WHY:
        if pre.startswith("%d"):
            if " intervals < " in text:
                return code
        elif text.startswith(pre):
            return code
    raise ValueError("unmapped why: %r" % text)


def sat(v):
    return min(int(v or 0), 255)


def record(cls, why=0, cond=0, wh=0, idle=0, p16=0, phase=0, score=0, n=0, frames=0, fb=0):
    return bytes([
        (cls << 5) | (why << 2) | (cond << 1) | wh,
        (idle << 7) | ((p16 >> 16) & 7) << 4 | ((fb >> 9) & 0xF),
        (p16 >> 8) & 0xFF, p16 & 0xFF,
        ((fb >> 8) & 1) << 7 | ((phase >> 8) & 0x7F), phase & 0xFF,
        sat(score), sat(n), sat(frames), fb & 0xFF])


def expect(cap):
    """the 80 bytes of records for a stored capture (golden classify_bus + stage1)."""
    G = S0.frozen_model()
    act = [w for w in range(8) if len(G.wire_edges(cap, w)) >= 2]
    roles = G.stage0(cap)
    res = G.classify_bus(cap)
    out = b""
    for w in range(8):
        if w not in act:
            out += record(C_NONE)
            continue
        if "refused" in roles:
            out += record(C_UNK, why=6)
            continue
        if w in roles:
            out += record(C_ROLE)
            continue
        iv = G.wire_ivs(cap, w, 0)
        s1 = G.stage1(iv)
        s2 = res[w]
        cls = CLS[s2["cls"]]
        why = wh = 0
        if s1["status"] != "OK":
            why = why_code(s1["why"])
        elif cls == C_UNK:
            why = why_code(s2["why"])
            wh = 1 if s2.get("withheld") == "NRZ_ASYNC" else 0
        ok = s1["status"] == "OK"
        out += record(cls, why=why, cond=1 if "condition" in s2 else 0, wh=wh,
                      idle=s2.get("idle", 0) if cls == C_ASYNC else 0,
                      p16=s1["p16"] if ok else 0, phase=s1["phase"] if ok else 0,
                      score=s1["score"] if ok else 0, n=s1.get("n", 0),
                      frames=s2.get("frames") or 0, fb=s2.get("frame_bits", 0) if cls == C_ASYNC else 0)
    return out, res


def sim(vvp, tmp, tag, img, stim, ncyc):
    """gate pit-s0's sim, but run until stages 1-2 are done (+S0WAIT=2)."""
    ip = os.path.join(tmp, "pitcap_s12_%s.hex" % tag)
    I.write_image(ip, img)
    sim_run.scratch_image(RP.GEN, ip)
    sp = os.path.join(tmp, "s12_%s.stim" % tag)
    with open(sp, "w", encoding="ascii", newline="\n") as fh:
        for t, v in stim:
            fh.write("%d %02x\n" % (t, v))
    op = os.path.join(tmp, "s12_%s.out" % tag)
    RP.run(sim_run.vvp([vvp, "+IMG=%s" % ip, "+NBYTES=%d" % I.STORE_BYTES, "+STIM=%s" % sp,
                        "+OUT=%s" % op, "+NCYC=%d" % ncyc, "+S0WAIT=2"], images=[ip]))
    log, mem, lv0, st = [], {}, None, None
    with open(op, encoding="ascii") as fh:
        for ln in fh:
            t = ln.split()
            if not t:
                continue
            if t[0] == "E":
                log.append((int(t[1]), int(t[2], 16)))
            elif t[0] == "M":
                mem[int(t[1])] = int(t[2], 16) if all(c in "0123456789abcdefABCDEF" for c in t[2]) else -1
            elif t[0] == "L":
                lv0 = int(t[1], 16)
            elif t[0] == "S":
                st = dict(kv.split("=") for kv in t[1:])
    return log, mem, lv0, st


#: PATH ASSERTS (Wilson 10-31): a case meant for a path must REACH it in the
#: golden's expected record -- the class alone would pass on the wrong reason.
#: name -> (cls, why) or (cls, "span"): the span fallback writes the frames byte
PATHS = {
    "s12_nobody": (C_UNK, 4),
    "s12_irreg": (C_UNK, 5),
    "s12_span": (C_ASYNC, "span"),
}


def path_problems(name, want, res):
    """[] if the golden's expected record for `name` reaches its intended path"""
    if name not in PATHS:
        return []
    cls, how = PATHS[name]
    rec = want[0:REC_BYTES]                    # wire 0
    got_cls, got_why = rec[0] >> 5, (rec[0] >> 2) & 7
    if got_cls != cls:
        return ["%s: the golden's class is %d, not the path's %d (%s)" % (name, got_cls, cls, res.get(0))]
    if how == "span":
        if not (res.get(0) or {}).get("frames") or rec[8] == 0:
            return ["%s: NRZ_ASYNC but NOT by the span fallback (frames %r, byte 8 = %d)"
                    % (name, (res.get(0) or {}).get("frames"), rec[8])]
    elif got_why != how:
        return ["%s: UNKNOWN for reason %d, not the path's %d (%s)" % (name, got_why, how, res.get(0))]
    return []


#: (define, what, the cases it must turn red)
MUTANTS = [
    ("M_S12_NO_RIVAL", "the rival check off", ["s12_clock"]),
    ("M_S12_NO_REF2", "refine 2 dropped", ["s12_clock_ref2"]),
    ("M_S12_NO_R2", "the R2 guard off", ["s12_uart_busy"]),
    ("M_S12_NO_BODYCHK", "no-non-idle-runs off", ["s12_nobody"]),
    ("M_S12_NO_IRREG", "stretched clock off", ["s12_irreg"]),
    ("M_S12_NO_SPAN", "span fallback off", ["s12_span"]),
]


def run_case(vvp, tmp, case, tag):
    name, waves, mask, b, ncyc, _e = case
    stim = RP.waves_to_stim(waves, **R0.STIM_OPTS.get(name, {}))
    run_len = ncyc if (not b and name in RP.NCYC_FOR) else R0.NCYC_MAX * 40
    img = RP.sniff_image(mask, b)
    log, mem, lv0, st = sim(vvp, tmp, tag, img, stim, run_len)
    cap = S0.stored_capture(log, lv0, RP.PG.budget_cycles(b), R0.NCYC_MAX)
    got = bytes((mem.get(REC_AT + i, -1) & 0xFF) for i in range(8 * REC_BYTES))
    if cap is None:
        want = bytes(img[REC_AT:REC_AT + 8 * REC_BYTES]) if len(img) >= REC_AT + 80 else bytes(80)
        res = {}
    else:
        want, res = expect(cap)
    return log, st, cap, got, want, res


def main() -> int:
    banner("iverilog", "vvp")
    print()
    print("=" * 78)
    print("PIT STAGES 1-2 -- per-wire records 40..119, bit for bit against frozen classify_bus")
    print("=" * 78)
    S0.frozen_model()
    only = set(filter(None, os.environ.get("PE_S12_CASES", "").split(",")))
    tmp = tempfile.mkdtemp(prefix="pe_pits12_")
    vvp = os.path.join(tmp, "s12.vvp")
    RP.build(vvp)
    probs, seen = [], set()
    for case in cases():
        name, waves, mask, b, ncyc, _e = case
        if only and name not in only:
            continue
        t0 = time.time()
        log, st, cap, got, want, res = run_case(vvp, tmp, case, name)
        probs += path_problems(name, want, res)
        if cap is not None and (st or {}).get("s12done") != "1":
            probs.append("%s: stages 1-2 never finished (pc %s)" % (name, (st or {}).get("pc")))
        for w in range(8):
            seen.add(want[w * REC_BYTES] >> 5)
        bad = [w for w in range(8) if got[w * 10:(w + 1) * 10] != want[w * 10:(w + 1) * 10]]
        print("  %-20s edges %4d  %5.1fs pc %-9s %s" % (
            name, len(log), time.time() - t0, (st or {}).get("pc"),
            "bit-exact " + " ".join("%d:%s%s" % (w, res[w].get("cls", "-"), ("(" + res[w].get("why", "")[:28] + ")") if res[w].get("cls") == "UNKNOWN" else "") for w in range(8) if res.get(w))
            if not bad else "*** wires %s" % bad))
        for w in bad:
            probs.append("%s wire %d: RTL %s, golden %s (%s)" % (
                name, w, got[w * 10:(w + 1) * 10].hex(), want[w * 10:(w + 1) * 10].hex(), res.get(w)))
    print("  classes exercised: %s" % sorted(seen))
    print()
    print("  must-fires")
    by = {c[0]: c for c in cases()}
    for define, what, targets in MUTANTS:
        mv = os.path.join(tmp, "s12_%s.vvp" % define.lower())
        RP.build(mv, [define])
        red = []
        for tname in targets:
            _l, _st, _c, got, want, _r = run_case(mv, tmp, by[tname], "%s_%s" % (tname, define))
            if got != want:
                red.append(tname)
        ok = len(red) == len(targets)
        print("    %-16s %-22s %s" % (define, what, ("red on %s  ok" % red) if ok else "*** NOT KILLED on %s" % sorted(set(targets) - set(red))))
        if not ok:
            probs.append("%s (%s) not killed" % (define, what))
    for p in probs:
        print("  *** " + p)
    print("  GATE pit-s12: %s" % ("FAILED" if probs else "PASSED"))
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())
