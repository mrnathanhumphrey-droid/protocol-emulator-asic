#!/usr/bin/env python3
"""v2 PIT stage 3 on a CLOCKED bus (Wilson 11-06): the sampled second capture,
BIT FOR BIT against the frozen golden's stage3_clocked (model/pit_golden.py,
81ae9563 LF; the stages 0-2 prefix f19f2177).

THE CLAIM: on the full chip, when classify_bus gives no NRZ_ASYNC wire and
stage 0 named a clocked bus, the PIT captures the bus again (cycle 0 = the
bench's "K" line: an edge logged at PIT cycle t is the second capture's edge
t - K) and the store from 128 holds golden sampled_capture's frames as
[length][bytes...]; the 16-byte record at 120..135 equals stage3_clocked's.
A case the golden refuses (no clocked bus, no frame markers, CS level
unclear, no clean sample edge) must NOT arm, and its record is the golden's.
The first capture as stored is the bench's own edge log through
pit_capture_golden, exactly as gates pit-s0 / pit-s12 / pit-s3 build it.
                                                    token: GATE pit-clk: PASSED
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

DEC_AT, S3_AT = 128, 120
CK, DA, CS = 0, 1, 2                         # the bus's wires (uio 0..2)


# ---------------------------------------------------------------------------
# the stimulus: textbook MSB-first CRC frames (not the model's code) on SPI
# (modes 0-3, CS active low) or I2C (START .. STOP, ACK low), data changing
# `skew` cycles after the shift edge ("mid" = mid-level)
# ---------------------------------------------------------------------------
def crc_msb(data, w, poly, init, xorout):
    r = init
    for b in data:
        for i in range(7, -1, -1):
            top = (r >> (w - 1)) & 1
            r = ((r << 1) & ((1 << w) - 1)) ^ (poly if top ^ ((b >> i) & 1) else 0)
    return r ^ xorout


def frames(seed, n, lens, p):
    rnd = random.Random(seed)
    w, poly, init, xorout = p
    out = []
    for k in range(n):
        d = [rnd.randrange(256) for _ in range(lens[k % len(lens)])]
        c = crc_msb(d, w, poly, init, xorout)
        out.append(d + [(c >> (8 * i)) & 0xFF for i in range(w // 8 - 1, -1, -1)])
    return out


class Bus:
    def __init__(self, init):
        self.init, self.lv, self.ev = dict(init), dict(init), {w: [] for w in init}

    def set(self, t, w, v):
        if self.lv[w] != v:
            self.ev[w].append((t, v))
            self.lv[w] = v

    def waves(self, t_end):
        return R0.edges_to_waves(self.ev, self.init, t_end)


def spi_bus(msgs, mode=0, H=20, skew=1, gap=600, bits=None, cs=True, t=100, extra=None):
    """bits: per-frame bit counts (None = whole bytes). extra = (k, at): every
    k-th bit the data also changes `at` cycles after the SAMPLE edge (0 = on it:
    no clean edge; H // 2 = mid-level: both clean, data in both levels).
    k >= 12 keeps those changes under stage 0's 1/8, so the wire stays SYNC_DATA."""
    cpol, cpha = mode >> 1, mode & 1
    bus = Bus({CK: cpol, DA: 0, CS: 1} if cs else {CK: cpol, DA: 0})
    nb = [0]
    for k, m in enumerate(msgs):
        bl = [(b >> (7 - i)) & 1 for b in m for i in range(8)]
        if bits:
            bl = bl[:bits[k % len(bits)]]
        if cs:
            bus.set(t, CS, 0)
        t += H
        for i, b in enumerate(bl):
            nb[0] += 1
            xtra = extra is not None and nb[0] % extra[0] == 0
            if cpha == 0:
                bus.set(t - H // 2 if skew == "mid" else (t - H + skew if i else t - H + 1), DA, b)
                bus.set(t, CK, 1 - cpol)
                if xtra:
                    bus.set(t + extra[1], DA, 1 - b)
                bus.set(t + H, CK, cpol)
            else:
                bus.set(t, CK, 1 - cpol)
                bus.set(t + (H // 2 if skew == "mid" else skew), DA, b)
                bus.set(t + H, CK, cpol)
                if xtra:
                    bus.set(t + H + extra[1], DA, 1 - b)
            t += 2 * H
        t += H
        if cs:
            bus.set(t, CS, 1)
        t += gap
    return bus, t


def i2c_bus(msgs, H=20, skew=1, gap=600, sr_every=0, t=100):
    """sr_every = k: every k-th frame ends in a repeated START, not a STOP"""
    bus = Bus({CK: 1, DA: 1})
    k = 0
    while k < len(msgs):
        bus.set(t, DA, 0)
        t += H                                          # START
        while True:
            for b in msgs[k]:
                for bit in [(b >> (7 - i)) & 1 for i in range(8)] + [0]:
                    bus.set(t, CK, 0)
                    bus.set(t + (H // 2 if skew == "mid" else skew), DA, bit)
                    bus.set(t + H, CK, 1)
                    t += 2 * H
            k += 1
            if sr_every and k % sr_every and k < len(msgs):   # repeated START
                bus.set(t, CK, 0); bus.set(t + H // 2, DA, 1); bus.set(t + H, CK, 1)
                bus.set(t + 2 * H, DA, 0)
                t += 3 * H
                continue
            break
        bus.set(t, CK, 0); bus.set(t + H // 2, DA, 0); bus.set(t + H, CK, 1); bus.set(t + 2 * H, DA, 1)
        t += 3 * H + gap                                # STOP
    return bus, t


XMODEM = (16, 0x1021, 0x0000, 0x0000)
CCITT = (16, 0x1021, 0xFFFF, 0x0000)
SMBUS = (8, 0x07, 0x00, 0x00)
NFR = int(os.environ.get("PE_CLK_NFR", "400"))


def case_list():
    """[(name, waves, budget b, what the golden must say: "ok" / a refusal's why)]"""
    out = []

    def add(name, bus_t, b, want):
        bus, t = bus_t
        out.append((name, bus.waves(t + 400), b, want))
    for mode in range(4):
        add("spi_m%d" % mode, spi_bus(frames(10 + mode, NFR, (1, 2), CCITT), mode=mode), 0, "ok")
    add("spi_mid", spi_bus(frames(20, NFR, (1, 2), XMODEM), mode=0, skew="mid"), 0, "ok")
    add("i2c_pec", i2c_bus(frames(30, NFR, (1, 2), SMBUS)), 0, "ok")
    add("i2c_sr", i2c_bus(frames(31, NFR, (1, 2), SMBUS), sr_every=3), 0, "ok")
    add("spi_ragged", spi_bus(frames(40, NFR, (1, 2), XMODEM), bits=(24, 32, 24, 12)), 0, "ok")
    # quiet: the bus stops; the budget ends the second capture
    add("spi_quiet", spi_bus(frames(50, 280, (1, 2), XMODEM)), 0, "ok")
    # refusals
    add("no_cs", spi_bus(frames(60, NFR // 8, (1, 2), XMODEM), cs=False), 0, "no clocked bus with frame markers")
    add("no_clean_edge", spi_bus(frames(61, NFR // 8, (1, 2), XMODEM), extra=(12, 0)), 0,
        "no clean sample edge (data changes on both clock edges)")
    add("both_levels", spi_bus(frames(62, NFR // 8, (1, 2), XMODEM), skew="mid", extra=(32, 10)), 0,
        "no clean sample edge (data changes in both clock levels)")
    return out


#: every case has a budget: 2^21 cycles from each capture's cycle 0 -- the first
#: capture fills long before; the second ends on full, or on the budget once the
#: bus is quiet (spi_quiet goes quiet ~30 frames after the arm at ~450 k)
BUDGET_B = 21


def sim(vvp, tmp, tag, img, stim, ncyc):
    """run_pit_s12.sim's run (+S0WAIT=2: until stages 0-3 are done), plus the K line"""
    ip = os.path.join(tmp, "pitcap_clk_%s.hex" % tag)
    I.write_image(ip, img)
    sim_run.scratch_image(RP.GEN, ip)
    sp = os.path.join(tmp, "clk_%s.stim" % tag)
    with open(sp, "w", encoding="ascii", newline="\n") as fh:
        for t, v in stim:
            fh.write("%d %02x\n" % (t, v))
    op = os.path.join(tmp, "clk_%s.out" % tag)
    RP.run(RP.simcmd([vvp, "+IMG=%s" % ip, "+NBYTES=%d" % I.STORE_BYTES, "+STIM=%s" % sp,
                      "+OUT=%s" % op, "+NCYC=%d" % ncyc, "+S0WAIT=2"], images=[ip]))
    log, mem, pre, lv0, st, arm = [], {}, {}, None, {}, None
    with open(op, encoding="ascii") as fh:
        for ln in fh:
            t = ln.split()
            if not t:
                continue
            if t[0] == "E":
                log.append((int(t[1]), int(t[2], 16)))
            elif t[0] in ("M", "P"):
                v = int(t[2], 16) if all(c in "0123456789abcdefABCDEF" for c in t[2]) else -1
                (mem if t[0] == "M" else pre)[int(t[1])] = v
            elif t[0] == "L":
                lv0 = int(t[1], 16)
            elif t[0] == "K":
                arm = int(t[1])
            elif t[0] == "S":
                st = dict(kv.split("=") for kv in t[1:])
    return log, mem, pre, lv0, st, arm


def expect(log, lv0, b, arm, pc_end):
    G = S0.frozen_model()
    bud = RP.PG.budget_cycles(b)
    cap = S0.stored_capture(log, lv0, bud, R0.NCYC_MAX)
    if cap is None:
        return None, None, None
    cls = G.classify_bus(cap, lv0)
    lv2, log2 = lv0, []
    if arm is not None:
        for t, m in log:
            if t <= arm:
                lv2 ^= m
            else:
                log2.append((t - arm, m))
    rec, out = G.stage3_clocked_rc(cap, lv0, cls, log2, lv2, bud, (pc_end - arm) if arm is not None else 0)
    enc = []
    for m in out.get("msgs") or []:
        enc += [len(m)] + list(m)
    return bytes(rec), bytes(enc), out


def run_case(vvp, tmp, case, tag=None):
    name, waves, b0, want = case
    b = b0 or BUDGET_B
    stim = RP.waves_to_stim(waves, pre=True)
    img = RP.sniff_image(0x00, b)
    log, mem, pre, lv0, st, arm = sim(vvp, tmp, tag or name, img, stim, R0.NCYC_MAX * 40)
    pc_end = int((st or {}).get("pc", "0"))
    rec, enc, out = expect(log, lv0, b, arm, pc_end)
    bad = []
    if rec is None:
        return ["%s: the first capture never stopped" % name], None, arm, st
    if (st or {}).get("s12done") != "1":
        bad.append("stages 0-3 never finished (pc %s)" % pc_end)
    if out.get("second") != (arm is not None):
        bad.append("armed %s, golden second capture %s" % (arm is not None, out.get("second")))
    r16 = bytes((mem.get(S3_AT + i, -1) & 0xFF) for i in range(16))
    if r16 != rec:
        bad.append("record %d..%d: RTL %s, golden %s" % (S3_AT, S3_AT + 15, r16.hex(), rec.hex()))
    if enc:
        src = pre if pre else mem
        dec = bytes((src.get(DEC_AT + i, -1) & 0xFF) for i in range(len(enc)))
        if dec != enc:
            i = next(i for i in range(len(enc)) if dec[i] != enc[i])
            bad.append("messages at byte %d: RTL %s, golden %s" % (
                DEC_AT + i, dec[max(0, i - 4):i + 8].hex(), enc[max(0, i - 4):i + 8].hex()))
    # PATH: the case reaches what it is for
    if want == "ok" and out.get("status") != "OK":
        bad.append("PATH: golden status %s (%s), the case is for OK" % (out.get("status"), out.get("why")))
    if want != "ok" and out.get("why") != want:
        bad.append("PATH: golden why %r, the case is for %r" % (out.get("why"), want))
    return bad, out, arm, st


#: (define, what, the cases it must turn red)
MUTANTS = [
    ("M_CK_ACK_KEEP", "the I2C ACK bit kept", ["i2c_pec"]),
    ("M_CK_EDGE_INV", "the sampler on the other edge", ["spi_m1"]),   # CPHA 0: either edge reads the same bit
    ("M_CK_NO_SR", "a repeated START ignored", ["i2c_sr"]),
    ("M_CK_CS_INV", "CS polarity inverted", ["spi_m1"]),
    ("M_CK_LSB", "bits packed LSB-first", ["spi_m2"]),
    ("M_CK_NO_REFUSE", "no clean edge: guess, not refuse", ["no_clean_edge"]),
    # the reason code (11-06): "no frame markers" <-> "no data wire" swapped
    ("M_CK_WHY_SWAP", "reason codes 6 / 7 swapped", ["no_cs"]),
]


def main() -> int:
    banner("iverilog", "vvp")
    print()
    print("=" * 78)
    print("PIT STAGE 3 ON A CLOCKED BUS (the sampled second capture) -- bit for bit against frozen stage3_clocked")
    print("=" * 78)
    S0.frozen_model()
    only = set(filter(None, os.environ.get("PE_CLK_CASES", "").split(",")))
    tmp = tempfile.mkdtemp(prefix="pe_pitclk_")
    vvp = os.path.join(tmp, "clk.vvp")
    RP.build(vvp)
    probs = []
    for case in case_list():
        name = case[0]
        if only and name not in only:
            continue
        t0 = time.time()
        bad, out, arm, st = run_case(vvp, tmp, case)
        msgs = (out or {}).get("msgs") or []
        print("  %-14s arm %-9s pc %-9s %6.1fs  %-8s frames %3d  %s" % (
            name, arm, (st or {}).get("pc"), time.time() - t0, (out or {}).get("status"), len(msgs),
            "bit-exact" if not bad else "*** " + "; ".join(bad)), flush=True)
        probs += ["%s: %s" % (name, b) for b in bad]
    if not only and os.environ.get("PE_CLK_MUTANTS", "1") == "1":
        print("  must-fires (each mutant must turn its case red):")
        cases = {c[0]: c for c in case_list()}
        for define, what, names in MUTANTS:
            mv = os.path.join(tmp, "mut_%s.vvp" % define)
            RP.build(mv, [define])
            red = []
            for n in names:
                bad, _o, _a, _s = run_case(mv, tmp, cases[n], "%s_%s" % (define, n))
                red.append(bool(bad))
            ok = all(red)
            print("    %-16s %-36s %s" % (define, what, "red (fires)" if ok else "*** stayed GREEN"), flush=True)
            if not ok:
                probs.append("must-fire %s (%s) stayed green" % (define, what))
    for p in probs:
        print("  *** " + p)
    print("  GATE pit-clk: %s" % ("FAILED" if probs else "PASSED"))
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())
