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

PIECES 2-3 -- THE GCD AND init / xorout: the whole 16-byte record at 120..135
equals frozen stage3's. 128..135 are the record's and written LAST (option (a),
Wilson 11-05), so the messages are read from the store as that write starts
(tb_pit's snapshot); pieces 2-3's own preloaded-store bench is gate pit-gcd.
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

# ⭐ CI RUNS THIS ON VERILATOR (Wilson 11-12: GATE, "Verilator where the runtime
# needs it"; iverilog took 186 s + 1,179 s for two of run_pit_s3's cases). An
# explicit PE_SIM wins (iverilog nightly / at the lock). Set before run_pit_capture
# is imported, which reads it.
os.environ.setdefault("PE_SIM", "verilator")
from toolchain import banner                # noqa: E402
import run_pit_capture as RP                # noqa: E402
import run_pit_s0 as R0                     # noqa: E402
import run_pit_s12 as R12                   # noqa: E402
import pit_s0_golden as S0                  # noqa: E402

DEC_AT = 128
S3_AT = 120          # the stage 3 record, 120..135 (Wilson 11-05; 128..135 written last)


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


MUTANTS = [("M_S3_LAST_KEEP", "the last message kept as evidence", "s3_cut_full"),
           # the SRAM store's write buffer (Wilson 11-07): every write treated as
           # meeting a read -- stage 0's back-to-back table writes overflow it,
           # and the store's check stops the run (no record: red)
           ("M_SRAM_WBUF_OVF", "the SRAM write buffer overflowed", "s3_crc32_full")]
MODBUS = (16, 0x8005, 0xFFFF, 0x0000, True)
CRC32 = (32, 0x04C11DB7, 0xFFFFFFFF, 0xFFFFFFFF, True)
S3_WAVES = {
    "s3_uart": {0: R12.uart()},                          # one message, 6 bytes (32 edges: fast)
    "s3_modbus": {0: crc_waves(MODBUS, 2, 1000, nshort=5)},   # 7 messages; 5 short: the last decoded is never evidence (Wilson 11-06)
    "s3_crc32_full": {0: crc_waves(CRC32, 1, 1005, nshort=5)},  # FULL cuts the capture mid-frame; 5 short (11-06)
}


def cut_waves(seed=3, n=12):
    """⭐ THE CUT MESSAGE (Wilson 11-06): MODBUS frames of 2 and 3 data bytes
    (L, L+1, L ...) with NO budget, so the capture stops FULL -- for this seed
    exactly between the 4th and 5th byte of a 5-byte frame (found by search on
    the golden, asserted per run below). The decoder cannot tell the cut frame
    from a whole 4-byte one; in the 4-byte group it spoiled the old GCD
    (crc_poly_gcd_s3_fit: UNKNOWN). The last message is never evidence: the
    polynomial must come out RIGHT (0x8005), or UNKNOWN, never wrong."""
    rng = random.Random(seed)
    msgs = [frame([rng.getrandbits(8) for _ in range(3 if k % 3 == 1 else 2)], *MODBUS) for k in range(n)]
    return uart_waves(msgs)


def cases():
    out = []
    for name, wv in S3_WAVES.items():
        t_end = max(sum(c for _l, c in segs) for segs in wv.values())
        out.append((name, wv, 0x00, R0.budget_for(t_end + R0.T0 + 200), None, None))
    out.append(("s3_cut_full", {0: cut_waves()}, 0x00, 0, None, None))     # budget off: FULL
    return out


def expect(cap):
    """(stage 1-2's 80 record bytes, the decoded-message bytes from 128, detail);
    detail["rec"] = the WHOLE stage 3 record, 120..135 (pieces 1-3)"""
    G = S0.frozen_model()
    recs, _res = R12.expect(cap)
    rec, out = G.stage3_rc(cap, 0, G.classify_bus(cap, 0))
    out["rec"] = bytes(rec)
    enc = []
    for m in out.get("msgs") or []:
        enc += [len(m)] + list(m)
    return recs, bytes(enc), out


def main() -> int:
    banner("iverilog", "vvp")
    print()
    print("=" * 78)
    print("PIT STAGE 3 (pieces 1-3: decode, GCD, init / xorout) -- bit for bit against frozen stage3")
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
        # option (a) (Wilson 11-05): the record's 128..135 are written LAST, so
        # the messages are read from the store as that write started
        pre = (st or {}).get("pre") or {}
        if not pre:
            probs.append("%s: no snapshot -- stage 3 never reached its record write" % name)
        dec = bytes((pre.get(DEC_AT + i, -1) & 0xFF) for i in range(len(enc)))
        bad = []
        if got != want12:
            bad.append("stage 1-2 records")
        r16 = bytes((mem.get(S3_AT + i, -1) & 0xFF) for i in range(16))
        if r16 != out["rec"]:
            bad.append("record %d..%d: RTL %s, golden %s" % (S3_AT, S3_AT + 15, r16.hex(), out["rec"].hex()))
        if mem.get(3, -1) != 0:                 # UART: no clocked-bus descriptor (byte 3)
            bad.append("byte 3 = %02x on a UART capture, want 00" % (mem.get(3, -1) & 0xFF))
        if dec != enc:
            i = next(i for i in range(len(enc)) if dec[i] != enc[i])
            bad.append("messages at byte %d: RTL %s, golden %s" % (
                DEC_AT + i, dec[max(0, i - 4):i + 8].hex(), enc[max(0, i - 4):i + 8].hex()))
        msgs = out.get("msgs") or []
        if name == "s3_cut_full":
            # the case's teeth, on the golden: the last decoded message IS a cut
            # 5-byte frame, the old rule lost the polynomial, the new one finds it
            old = S0.frozen_model().crc_poly_gcd_s3_fit(msgs) if msgs else {}
            ok = (len(msgs) > 1 and len(msgs[-1]) == 4 and old.get("status") == "UNKNOWN"
                  and (out.get("poly") or {}).get("poly") == MODBUS[1])
            if not ok:
                bad.append("PATH: not the cut-message case (lengths %s, old %s, new %s)" % (
                    [len(m) for m in msgs], old.get("status"), (out.get("poly") or {}).get("poly")))
        print("  %-16s edges %4d  %6.1fs  %-8s msgs %2d bytes %3d  %s" % (
            name, len(log), time.time() - t0, out.get("status"), len(msgs), sum(map(len, msgs)),
            "bit-exact" if not bad else "*** " + "; ".join(bad)))
        probs += ["%s: %s" % (name, b) for b in bad]
    # the must-fire (Wilson 11-06): the last message kept as evidence -- the cut
    # case's poisoned 4-byte group comes back, and its polynomial is lost
    if not only and os.environ.get("PE_S3_MUTANTS", "1") == "1":
        print("  must-fires (each mutant must turn its case red):")
        cs = {c[0]: c for c in cases()}
        for define, what, name in MUTANTS:
            mv = os.path.join(tmp, "mut_%s.vvp" % define)
            RP.build(mv, [define])
            tag = "%s_%s" % (define, name)
            log, st, cap, got, want12, _res = R12.run_case(mv, tmp, cs[name], tag)
            _r, _enc, out = expect(cap)
            r16 = bytes((R12_MEM.get(tag, {}).get(S3_AT + i, -1) & 0xFF) for i in range(16))
            red = r16 != out["rec"]
            print("    %-16s %-36s %s" % (define, what, "red (fires)" if red else "*** stayed GREEN"))
            if not red:
                probs.append("must-fire %s (%s) stayed green" % (define, what))
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
