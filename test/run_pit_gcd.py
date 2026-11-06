#!/usr/bin/env python3
"""v2 PIT stage 3 piece 2 bench (Wilson 11-05): the CRC-polynomial GCD on
pe_pit_s12, started AT the GCD (tb_gcd.v) on PRELOADED stores of decoded
messages [len][bytes...] from 128, the record at 120..127 compared BIT FOR BIT
with the frozen golden crc_poly_gcd_s3_fit's (model/pit_golden.py).

Preloading is the only way to reach the capacity rule -- no real capture can
(<= 314 stored edges, ~157 decoded bytes).

THE SETS:
  * random -- framed traffic over five CRCs plus unframed noise; a third with
    long frames and padding (the capacity rule), duplicates (d = 0) and single
    bit flips mixed in.
  * directed count ties -- ⛔ ON RECORD (Wilson 11-05): 600 random sets never
    reached the count tie-break; a mutant with the count rule FLIPPED passed
    600/600. These 40 sets are two valid groups with the same bit order and the
    same differences used but different counts (the bigger one padded with
    copies of its own first frame), each checked here, before the run, to pick
    the BIGGER group -- so a flipped count rule cannot match. Measured: the
    flipped mutant 0/40.
The messages themselves must come back untouched (the buffers live after them).
                                                    token: GATE pit-gcd: PASSED
"""
from __future__ import annotations

import os
import random
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

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
import run_pit_capture as RP                # noqa: E402
import run_pit_s3 as R3                     # noqa: E402
import pit_s0_golden as S0                  # noqa: E402

G = S0.frozen_model()
BENCH = "test/tb_gcd.v"
DEC_AT = 128
REC_AT = 120
WC = {8: 1, 16: 2, 32: 3}                   # the record's width code
CRCS = [(16, 0x8005, 0xFFFF, 0, True), (8, 7, 0, 0, False), (32, 0x04C11DB7, 0xFFFFFFFF, 0xFFFFFFFF, True),
        (16, 0x1021, 0, 0, False), (16, 0x1021, 0xFFFF, 0, False), None]
N_RANDOM, N_TIE = 3000, 40
SEED, TIE_SEED = 20261105, 20261106


def golden_rec(msgs):
    """the 8 record bytes the golden's result implies (wire 0)"""
    res = G.crc_poly_gcd_s3_fit(msgs)
    rec = [1 << 3, 0, 0, min(len(msgs), 255), 0, 0, 0, 0]
    if res["status"] == "OK":
        rec[0] |= 1 << 4 | (1 << 6 if res["reflected"] else 0)
        rec[1] = WC[res["width"]] | min(res["frame_len"], 63) << 2
        rec[2] = min(res["diffs_used"], 255)
        rec[4:8] = list(res["poly"].to_bytes(4, "little"))
    return rec, res


def random_sets(n, seed):
    rng = random.Random(seed)
    out = []
    for t in range(n):
        msgs = []
        long_ = t % 3 == 2                                  # a third with long frames (capacity)
        for _ in range(rng.randint(1, 4)):
            p = rng.choice(CRCS)
            L = rng.randint(20, 80) if long_ else rng.randint(1, 12)
            for _ in range(rng.randint(1, 8)):
                d = [rng.getrandbits(8) for _ in range(L)]
                msgs.append(R3.frame(d, *p) if p else d + [rng.getrandbits(8) for _ in range(2)])
        if long_:
            msgs += [[rng.getrandbits(8)] for _ in range(rng.randint(0, 40))]
        if rng.random() < 0.3:
            msgs.append(list(rng.choice(msgs)))             # a duplicate: d = 0
        if rng.random() < 0.3:
            m = rng.choice(msgs)
            m[rng.randrange(len(m))] ^= 1 << rng.randrange(8)
        rng.shuffle(msgs)
        while sum(len(m) + 1 for m in msgs) > 384 - (0 if long_ else 200):
            msgs.pop()
        out.append(msgs)
    return out


def tie_sets(n, seed):
    """the directed count ties (see the docstring); every set is checked to
    have teeth before it is kept"""
    rng = random.Random(seed)
    nr = [p for p in CRCS if p and not p[4]]
    out = []
    while len(out) < n:
        pa, pb = rng.choice(nr), rng.choice(nr)
        la, lb = rng.sample(range(2, 13), 2)
        A = [R3.frame([rng.getrandbits(8) for _ in range(la)], *pa) for _ in range(5)]
        A = [A[0]] * rng.randint(2, 4) + A[1:]               # count 6..8, used 4
        B = [R3.frame([rng.getrandbits(8) for _ in range(lb)], *pb) for _ in range(5)]
        if len(A[0]) == len(B[0]):
            continue
        ra, rb = G.crc_poly_gcd_s3_fit(A), G.crc_poly_gcd_s3_fit(B)
        if ra["status"] != "OK" or rb["status"] != "OK" or ra["reflected"] or rb["reflected"] \
                or ra["diffs_used"] != rb["diffs_used"]:
            continue
        msgs = B + A if rng.random() < 0.5 else A + B         # first appearance both ways
        if G.crc_poly_gcd_s3_fit(msgs).get("frame_len") != len(A[0]):
            continue
        out.append(msgs)
    return out


def run_one(args):
    vbin, tmp, i, msgs = args
    mem = [0] * 512
    p = DEC_AT
    for m in msgs:
        mem[p] = len(m)
        mem[p + 1:p + 1 + len(m)] = m
        p += 1 + len(m)
    mp, op = os.path.join(tmp, "g%d.hex" % i), os.path.join(tmp, "g%d.out" % i)
    with open(mp, "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join("%02x" % b for b in mem) + "\n")
    cmd = RP.simcmd([vbin, "+MEM=" + mp, "+OUT=" + op, "+END=%x" % p, "+NMSG=%d" % min(len(msgs), 255)], [])
    r = RP.run(cmd)
    if r.returncode != 0:
        raise RuntimeError("sim failed: %s" % (r.stdout + r.stderr)[-400:])
    got, st = {}, {}
    with open(op, encoding="ascii") as fh:
        for ln in fh:
            t = ln.split()
            if t[0] == "M":
                got[int(t[1])] = int(t[2], 16) if t[2] not in ("xx", "zz") else -1
            elif t[0] == "N":
                st = dict(kv.split("=") for kv in t[1:])
    want, res = golden_rec(msgs)
    g = [got[REC_AT + k] for k in range(8)]
    intact = all(got[a] == mem[a] for a in range(DEC_AT, p))
    return g == want and st.get("done") == "1" and intact, g, want, res, int(st.get("cyc", -1)), intact


def main() -> int:
    print("PIT stage 3 piece 2: the GCD (tb_gcd, preloaded stores) vs golden crc_poly_gcd_s3_fit")
    if RP.SIM == "iverilog":
        banner("iverilog", "vvp")
    tmp = tempfile.mkdtemp(prefix="pe_gcd_")
    vbin = os.path.join(tmp, "gcd.vvp")
    if RP.SIM == "verilator":
        RP.vl_build(vbin, bench=BENCH, top="tb_gcd")
    else:
        r = RP.run([RP.tool("iverilog"), "-g2012", "-I", ROOT, "-o", vbin, "-s", "tb_gcd", BENCH] + RP.RTL)
        if r.returncode != 0:
            raise RuntimeError("build failed: %s" % (r.stdout + r.stderr)[-400:])
    sets = [("random", m) for m in random_sets(N_RANDOM, SEED)] + [("tie", m) for m in tie_sets(N_TIE, TIE_SEED)]
    ok = {"random": 0, "tie": 0}
    cand = refused = cmax = shown = 0
    with ThreadPoolExecutor(14) as ex:
        res_iter = ex.map(run_one, [(vbin, tmp, i, m) for i, (_, m) in enumerate(sets)])
        for k, ((kind, _), (good, g, want, res, cyc, intact)) in enumerate(zip(sets, res_iter), 1):
            if k % 500 == 0:                    # the heartbeat (red-team 4): watch.sh reads log growth
                print("  ... %d / %d sets" % (k, len(sets)), flush=True)
            ok[kind] += good
            cand += res["status"] == "OK"
            refused += res.get("why") == "insufficient store for the GCD"
            cmax = max(cmax, cyc)
            if not good and shown < 5:
                shown += 1
                print("  *** %s set: RTL %s / golden %s %s%s" % (kind, bytes(max(0, v) for v in g).hex(),
                      bytes(want).hex(), res.get("why", ""), "" if intact else " (MESSAGES CLOBBERED)"))
    print("  random: %d / %d bit-exact (%d with a polynomial, %d refused for space); max %d cycles"
          % (ok["random"], N_RANDOM, cand, refused, cmax))
    print("  count ties: %d / %d bit-exact" % (ok["tie"], N_TIE))
    good = ok["random"] == N_RANDOM and ok["tie"] == N_TIE
    print("GATE pit-gcd: %s" % ("PASSED" if good else "FAILED"))
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
