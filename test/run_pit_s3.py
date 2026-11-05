#!/usr/bin/env python3
"""v2 PIT stage 3 gate (Wilson 11-04 / 11-05): CRC recovery on the first
NRZ_ASYNC wire, BIT FOR BIT against the frozen golden model's stage3
(model/pit_golden.py, df3552da LF; the stages 0-2 prefix f19f2177).

PIECE 1 -- THE DECODE WALK. THE CLAIM: on the full chip, after stages 0-3 are
done, the store from byte 128 holds golden async_bytes' messages as
[length][bytes...] (written BEHIND the decoder's read pointer, over the consumed
capture), and stage 1-2's records at 40..119 are unchanged. The capture as
stored is the bench's own edge log through pit_capture_golden.encode / decode,
exactly as gates pit-s0 / pit-s12 build it.
                                                    token: GATE pit-s3: PASSED
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
import run_pit_capture as RP                # noqa: E402
import run_pit_s0 as R0                     # noqa: E402
import run_pit_s12 as R12                   # noqa: E402
import pit_s0_golden as S0                  # noqa: E402

DEC_AT = 128


# ---------------------------------------------------------------------------
# the stimulus: framed UART traffic with a known CRC (an independent textbook
# Rocksoft CRC, not the model's code), plus a sacrificial last frame
# ---------------------------------------------------------------------------
def _refl(v, n):
    return int(bin(v)[2:].zfill(n)[::-1], 2)


def crc(data, w, poly, init, xorout, refl):
    r, top, mask = init, 1 << (w - 1), (1 << w) - 1
    for b in data:
        if refl:
            b = _refl(b, 8)
        r ^= b << (w - 8)
        for _ in range(8):
            r = ((r << 1) ^ poly) & mask if r & top else (r << 1) & mask
    if refl:
        r = _refl(r, w)
    return r ^ xorout


def frame(data, w, poly, init, xorout, refl):
    c = crc(data, w, poly, init, xorout, refl)
    return list(data) + list(c.to_bytes(w // 8, "little" if refl else "big"))


def uart_waves(msgs, bit=24, byte_gap=1, msg_gap=40):
    segs = [(1, 60 * bit)]

    def put(l, c):
        if segs[-1][0] == l:
            segs[-1] = (l, segs[-1][1] + c)
        else:
            segs.append((l, c))
    for m in msgs:
        for d in m:
            put(0, bit)
            for k in range(8):
                put(d >> k & 1, bit)
            put(1, bit * (1 + byte_gap))
        put(1, bit * msg_gap)
    return segs


def crc_waves(p, L, seed, nshort=4, longs=(1, 3), **kw):
    """4 short + 2 long frames (the long ones 2nd and 4th, not last), then a
    sacrificial 1-byte frame: the open tail is never evidence"""
    rng = random.Random(seed)
    msgs = []
    for k in range(nshort + len(longs)):
        n = L + 1 if k in longs else L
        d = [rng.getrandbits(8) for _ in range(n)]
        msgs.append(frame(d, *p) if p else d + [rng.getrandbits(8) for _ in range(2)])
    return uart_waves(msgs + [[0x00]], **kw)


MODBUS = (16, 0x8005, 0xFFFF, 0x0000, True)
CRC32 = (32, 0x04C11DB7, 0xFFFFFFFF, 0xFFFFFFFF, True)
S3_WAVES = {
    "s3_uart": {0: R12.uart()},                          # one message, 6 bytes (32 edges: fast)
    "s3_modbus": {0: crc_waves(MODBUS, 2, 1000)},        # 6 messages, split at the gaps
    "s3_crc32_full": {0: crc_waves(CRC32, 1, 1005)},     # FULL cuts the capture mid-frame
}


def cases():
    out = []
    for name, wv in S3_WAVES.items():
        t_end = max(sum(c for _l, c in segs) for segs in wv.values())
        out.append((name, wv, 0x00, R0.budget_for(t_end + R0.T0 + 200), None, None))
    return out


def expect(cap):
    """(stage 1-2's 80 record bytes, the decoded-message bytes from 128, detail)"""
    G = S0.frozen_model()
    recs, _res = R12.expect(cap)
    rec, out = G.stage3(cap, 0, G.classify_bus(cap, 0))
    enc = []
    for m in out.get("msgs") or []:
        enc += [len(m)] + list(m)
    return recs, bytes(enc), out


def main() -> int:
    banner("iverilog", "vvp")
    print()
    print("=" * 78)
    print("PIT STAGE 3 (piece 1: the decode walk) -- bit for bit against frozen stage3")
    print("=" * 78)
    S0.frozen_model()
    only = set(filter(None, os.environ.get("PE_S3_CASES", "").split(",")))
    tmp = tempfile.mkdtemp(prefix="pe_pits3_")
    vvp = os.path.join(tmp, "s3.vvp")
    RP.build(vvp)
    probs = []
    for case in cases():
        name = case[0]
        if only and name not in only:
            continue
        t0 = time.time()
        log, st, cap, got, want12, _res = R12.run_case(vvp, tmp, case, name)
        if cap is None:
            probs.append("%s: the capture never stopped" % name)
            continue
        if (st or {}).get("s12done") != "1":
            probs.append("%s: stages 1-3 never finished (pc %s)" % (name, (st or {}).get("pc")))
        _r, enc, out = expect(cap)
        mem = R12_MEM.get(name, {})
        dec = bytes((mem.get(DEC_AT + i, -1) & 0xFF) for i in range(len(enc)))
        bad = []
        if got != want12:
            bad.append("stage 1-2 records")
        if dec != enc:
            i = next(i for i in range(len(enc)) if dec[i] != enc[i])
            bad.append("messages at byte %d: RTL %s, golden %s" % (
                DEC_AT + i, dec[max(0, i - 4):i + 8].hex(), enc[max(0, i - 4):i + 8].hex()))
        msgs = out.get("msgs") or []
        print("  %-16s edges %4d  %6.1fs  %-8s msgs %2d bytes %3d  %s" % (
            name, len(log), time.time() - t0, out.get("status"), len(msgs), sum(map(len, msgs)),
            "bit-exact" if not bad else "*** " + "; ".join(bad)))
        probs += ["%s: %s" % (name, b) for b in bad]
    for p in probs:
        print("  *** " + p)
    print("  GATE pit-s3: %s" % ("FAILED" if probs else "PASSED"))
    return 1 if probs else 0


# run_pit_s12.sim keeps only 40..119; the decoded messages need the whole dump
R12_MEM = {}
_sim12 = R12.sim


def _sim_keep(vvp, tmp, tag, img, stim, ncyc):
    log, mem, lv0, st = _sim12(vvp, tmp, tag, img, stim, ncyc)
    R12_MEM[tag] = mem
    return log, mem, lv0, st


R12.sim = _sim_keep

if __name__ == "__main__":
    sys.exit(main())
