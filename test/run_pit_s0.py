#!/usr/bin/env python3
"""v2 PIT chunk 2 gate: STAGE 0 in RTL, the role table BIT FOR BIT.

THE ONE CLAIM (prediction pit_rtl_c2.ea932f34, Wilson 10-29): for every case,
the role table the RTL writes to store bytes 32..38 equals
model/pit_s0_golden.table(frozen stage0(the capture AS STORED)) -- the bench's
own edge log through pit_capture_golden.encode / decode (whole records,
saturating intervals), levels rebuilt from the bench's starting levels. The
frozen rule set is model/pit_golden.py at e55d0b63 (refused otherwise).
Every role code must appear in some case (CLOCK, SYNC_DATA, FRAME, AMBIGUOUS,
the I2C bus, REFUSED), and every must-fire must turn some case's table red.
Where the frozen model has the must-fire's own switch (the 1 + 9n rule, the
ambiguity rule, the rate floor), the gate also checks that the case it relies
on really changes the model's outcome -- a case without teeth is refused.
                                                    token: GATE pit-s0: PASSED
"""
from __future__ import annotations

import glob
import json
import os
import random
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

from toolchain import banner                # noqa: E402
import pe_isa as I                          # noqa: E402
import sim_run                              # noqa: E402
import run_pit_capture as RP                # noqa: E402
import pit_s0_golden as S0                  # noqa: E402

CASE_DIR = os.path.join(HERE, "pit_s0_cases")
NCYC_MAX = 12_000_000                      # far past S4's 10 M; +S0WAIT ends at `done`
T0 = 60


def edges_to_waves(edges, init, t_end):
    """{wire: [(t, level)]} ideal edges -> {wire: [(level, cycles)]}."""
    waves = {}
    for w, lvl0 in init.items():
        segs, lvl, last = [], lvl0, 0
        for t, v in sorted(edges.get(w, [])):
            segs.append((lvl, t - last))
            lvl, last = v, t
        segs.append((lvl, max(1, t_end - last)))
        waves[w] = segs
    return waves


def cap_to_waves(cap):
    """a stage-0 capture [(t, mask, levels after)] -> waves, shifted to T0."""
    lv0 = cap[0][2] ^ cap[0][1]
    edges = {w: [] for w in range(8)}
    for t, mask, lv in cap:
        for w in range(8):
            if mask >> w & 1:
                edges[w].append((t + T0, lv >> w & 1))
    used = {w for w in range(8) if edges[w]}
    return edges_to_waves({w: edges[w] for w in used}, {w: lv0 >> w & 1 for w in used},
                          cap[-1][0] + T0 + 200)


def spi_cpol1(B, n_bursts, half, n_cs=1, mosi=False, seed=0):
    """SCK 0 (idle high), CS 1 (+ CS 2 if n_cs = 2), MOSI 3 if `mosi`."""
    rng = random.Random(seed)
    edges = {0: [], 1: []}
    if n_cs == 2:
        edges[2] = []
    if mosi:
        edges[3] = []
    t, m = 300, 0
    for _g in range(n_bursts):
        for cs in range(1, 1 + n_cs):
            edges[cs].append((t - half - 10, 0))
        for _k in range(B):
            byte = rng.getrandbits(8)
            for i in range(7, -1, -1):
                bit = (byte >> i) & 1
                edges[0] += [(t, 0), (t + half, 1)]
                if mosi and bit != m:
                    edges[3].append((t + 1, bit))
                    m = bit
                t += 2 * half
        for cs in range(1, 1 + n_cs):
            edges[cs].append((t - half + 10, 1))
        t += 260 + rng.randint(0, 140)
    init = {w: 1 for w in edges}
    if mosi:
        init[3] = 0
    return edges_to_waves(edges, init, t + 100), t + 100


def mosi_cs_only(seed=7, B=8, n_bursts=8, half=12):
    """the adversarial case for 1 + 9n: MOSI 1 + CS 2, SCK OFF the pins."""
    rng = random.Random(seed)
    edges = {1: [], 2: []}
    t, m = 300, 0
    for _g in range(n_bursts):
        edges[2].append((t - half - 10, 0))
        for _k in range(B):
            byte = rng.getrandbits(8)
            for i in range(7, -1, -1):
                bit = (byte >> i) & 1
                if bit != m:
                    edges[1].append((t + 1, bit))
                    m = bit
                t += 2 * half
        edges[2].append((t - half + 10, 1))
        t += 260 + rng.randint(0, 140)
    return edges_to_waves(edges, {1: 0, 2: 1}, t + 100), t + 100


def floor_edge(m=40):
    """ONE wire whose intervals sit ON the rate floor: as STORED (a cut tail
    record drops the last edge -- measured, 10-29), sorted(...)[(len(ee) - 1)
    // 2] is a 7 and the next index an 8, so an off-by-one median flips the
    refusal. The eights first, then m + 2 sevens: whichever edge a cut drops,
    the median index still lands on the last 7 (asserted in main())."""
    ivs = [8, 7] * m + [7, 7]
    edges, t, lvl = {4: []}, 300, 0
    for i in ivs:
        lvl ^= 1
        edges[4].append((t, lvl))
        t += i
    lvl ^= 1
    edges[4].append((t, lvl))
    return edges_to_waves(edges, {4: 0}, t + 100), t + 100


def frame2(B=1, n_bursts=6, half=12, seed=5):
    """the second FRAME pass and the ambiguity rule's refusal (coverage, 10-29):
    SCK 0 CPOL 0 (idle low), CS 1 per burst (the pair loop's FRAME, which makes
    SCK a CLOCK), CS 2 around ONE burst only -- 2 edges, so the pair loop
    rejects it and only the FRAME pass can claim it -- and a stray wire 3 with
    3 edges mid-burst: a rise with SCK high, a fall with it low, a rise with it
    high (the I2C check's STOP after STOP; not in an idle gap, so no FRAME).
    Both CS idle HIGH from cycle 0: the start-levels byte is not 0. SCK is low
    at every CS edge, so no FRAME is AMBIGUOUS."""
    rng = random.Random(seed)
    edges = {0: [], 1: [], 2: [], 3: []}
    t = 300
    for g in range(n_bursts):
        edges[1].append((t - half - 10, 0))
        if g == 2:
            # > 4 SCK half-periods (48) from any SCK edge: the FRAME pass's test
            edges[2].append((t - 100, 0))
        for k in range(B):
            for i in range(8):
                edges[0] += [(t, 1), (t + half, 0)]
                if g == 3 and k == 0 and i in (1, 3, 5):
                    # SCK is high over [t, t + half): rise, then fall low, then rise
                    edges[3].append((t + 2, 1) if i != 3 else (t + half + 2, 0))
                t += 2 * half
            rng.getrandbits(8)
        edges[1].append((t - half + 10, 1))
        if g == 2:
            edges[2].append((t - half + 100, 1))
        t += 260 + rng.randint(0, 140)
    return edges_to_waves(edges, {0: 0, 1: 1, 2: 1, 3: 0}, t + 100), t + 100


def midstream(k=7):
    """plugging into a bus ALREADY MID-TRANSFER (Nate 10-29): CPOL-1 SPI with CS
    + MOSI, 1-byte bursts, the capture starting 2 cycles before SCK's k-th fall
    inside burst 0 -- CS asserted (0), SCK high, MOSI at its data level, the
    first edge in the first few cycles (asserted on the bench's log in main())."""
    w, te = spi_cpol1(1, 10, 12, mosi=True, seed=11)
    ev = {}
    for wire, segs in w.items():
        t, out = 0, []
        for lvl, c in segs:
            out.append((t, lvl))
            t += c
        ev[wire] = out                       # [(t, level from t)], the first at 0
    falls = [t for t, l in ev[0][1:] if l == 0]
    tc = falls[k] - 2
    init, edges = {}, {}
    for wire, out in ev.items():
        init[wire] = [l for t, l in out if t <= tc][-1]
        edges[wire] = [(t - tc, l) for t, l in out[1:] if t > tc]
    return edges_to_waves(edges, init, te - tc), te - tc


def k0(n=40):
    """the coded record with NO low bits (k = 0, coverage 10-29): a wire that
    toggles 3, 3, 3, 2 cycles apart from cycle 1, so the first 16 raw
    intervals average under 3 (k_of -> 0) while the accumulator stays under
    its 64 bits (asserted on the stored capture in main())."""
    edges, t, lvl = {5: []}, 1, 0
    for i in range(n):
        lvl ^= 1
        edges[5].append((t, lvl))
        t += 2 if i % 4 == 3 else 3
    return edges_to_waves(edges, {5: 0}, t + 100), t + 100


#: per-case stimulus options (waves_to_stim): the start levels driven BEFORE
#: the PIT starts, and k0's first edge right after it (coverage, 10-29)
STIM_OPTS = {"frame2": {"pre": True}, "k0": {"pre": True, "t0": 1},
             "midstream": {"pre": True, "t0": 1}}


def budget_for(t_end):
    """the smallest power-of-two budget past the case's own end."""
    b = 1
    while (1 << b) <= t_end + 64:
        b += 1
    return b


def cases():
    """[(name, waves, mask, budget b, ncyc, expected role codes that must appear)]"""
    out = []
    for name, waves, mask in RP.CASES:
        b = RP.BUDGET_FOR.get(name, 0)
        out.append((name, waves, mask, b, RP.NCYC_FOR.get(name, RP.NCYC), None))
    for p in sorted(glob.glob(os.path.join(CASE_DIR, "*.json"))):
        d = json.load(open(p))
        cap = [tuple(x) for x in d["cap"]]
        w = cap_to_waves(cap)
        out.append((os.path.basename(p)[:-5], w, 0x00, budget_for(cap[-1][0] + T0 + 200), None, None))
    w, te = spi_cpol1(8, 8, 12)
    out.append(("twin", w, 0x00, budget_for(te), None, None))
    w, te = spi_cpol1(8, 8, 12, n_cs=2)
    out.append(("twin2cs", w, 0x00, budget_for(te), None, None))
    w, te = spi_cpol1(8, 6, 10, mosi=True, seed=3)
    out.append(("spi_cpol1_mosi", w, 0x00, budget_for(te), None, None))
    w, te = mosi_cs_only()
    out.append(("mosi_cs_offpin", w, 0x00, budget_for(te), None, None))
    w, te = floor_edge()
    out.append(("floor_edge", w, 0x00, budget_for(te), None, None))
    w, te = frame2()
    out.append(("frame2", w, 0x00, budget_for(te), None, None))
    w, te = k0()
    out.append(("k0", w, 0x00, budget_for(te), None, None))
    w, te = midstream()
    out.append(("midstream", w, 0x00, budget_for(te), None, None))
    # the empty walk: the budget ends a capture that recorded nothing
    out.append(("empty", {0: [(0, 2000)]}, 0x00, 10, None, None))
    return out


#: (define, what, the cases it must turn red, the frozen model's switch or None)
MUTANTS = [
    ("M_S0_PAIR_ORDER", "the d loop descending", ["twin2cs"], None),
    ("M_S0_MED_OFF1", "every median one index high", ["floor_edge"], None),
    ("M_S0_NO_MOD9", "the 1 + 9n rule dropped", ["mosi_cs_offpin"], ("I2C_MOD9", False)),
    ("M_S0_NO_FLOOR", "the rate floor dropped", ["near_trip_D0_h4_m1"], ("S0_RATE_FLOOR", 0)),
    ("M_S0_NO_AMBIG", "the ambiguity rule off", ["twin"], ("S0_AMBIG", False)),
    ("M_PIT_LV0_INV", "one wire's starting level inverted", ["spi0"], None),
]


def sim(vvp, tmp, tag, img, stim, ncyc):
    ip = os.path.join(tmp, "pitcap_s0_%s.hex" % tag)
    I.write_image(ip, img)
    sim_run.scratch_image(RP.GEN, ip)
    sp = os.path.join(tmp, "s0_%s.stim" % tag)
    with open(sp, "w", encoding="ascii", newline="\n") as fh:
        for t, v in stim:
            fh.write("%d %02x\n" % (t, v))
    op = os.path.join(tmp, "s0_%s.out" % tag)
    RP.run(sim_run.vvp([vvp, "+IMG=%s" % ip, "+NBYTES=%d" % I.STORE_BYTES, "+STIM=%s" % sp,
                        "+OUT=%s" % op, "+NCYC=%d" % ncyc, "+S0WAIT=1"], images=[ip]))
    log, mem, lv0, s0 = [], {}, None, None
    with open(op, encoding="ascii") as fh:
        for ln in fh:
            t = ln.split()
            if not t:
                continue
            if t[0] == "E":
                log.append((int(t[1]), int(t[2], 16)))
            elif t[0] == "M":
                mem[int(t[1])] = int(t[2], 16) if re.fullmatch(r"[0-9a-fA-F]+", t[2]) else -1
            elif t[0] == "L":
                lv0 = int(t[1], 16)
            elif t[0] == "S":
                s0 = dict(kv.split("=") for kv in t[1:])
    return log, mem, lv0, s0


def table_problems(got, want):
    """THE ONE COMPARE (the meta seam): [problem] if the RTL's table is not the
    golden's. Used by the cases (must be empty) and the must-fires (must not)."""
    return [] if got == want else ["table RTL %s, golden %s" % (got.hex(), want.hex())]


def judge(case, log, mem, lv0, s0):
    """-> (problems, golden table, roles, stage-0 pc)."""
    name, _w, _m, b, ncyc, _e = case
    # the bench ran NCYC_MAX cycles (or ended at stage 0's done): a budget at or
    # below that has expired; with no budget only FULL / OVERRUN stop it
    want, roles = S0.expect(log, lv0, RP.PG.budget_cycles(b), NCYC_MAX)
    got = bytes((mem.get(S0.TABLE_AT + i, -1) & 0xFF) for i in range(S0.TABLE_BYTES))
    probs = []
    if want is None:
        # the capture never stopped: stage 0 never runs, the table stays as loaded (0)
        if got != bytes(S0.TABLE_BYTES):
            probs.append("stage 0 wrote a table although the capture never stopped")
    else:
        if s0 is None or s0.get("s0done") != "1":
            probs.append("stage 0 never finished (pc %s)" % (s0 or {}).get("pc"))
        probs += table_problems(got, want)
    return probs, want, roles, int((s0 or {}).get("pc", "0"))


def role_codes(table_bytes):
    word = int.from_bytes(table_bytes, "little")
    return {(word >> (7 * w)) & 7 for w in range(8)}


def role_of(table_bytes, w):
    """wire w's role code in a stage-0 table (entry w at bit 7w, role in [2:0])."""
    word = int.from_bytes(table_bytes, "little")
    return (word >> (7 * w)) & 7


def main() -> int:
    banner("iverilog", "vvp")
    print()
    print("=" * 78)
    print("PIT STAGE 0 -- the role table, bit for bit against frozen stage0 (e55d0b63)")
    print("=" * 78)
    S0.frozen_model()                      # refuses a model that is not the frozen one
    tmp = tempfile.mkdtemp(prefix="pe_pits0_")
    vvp = os.path.join(tmp, "s0.vvp")
    RP.build(vvp)
    probs, seen, worst, results = [], set(), 0, {}
    cs = cases()
    for case in cs:
        name, waves, mask, b, ncyc, _e = case
        stim = RP.waves_to_stim(waves, **STIM_OPTS.get(name, {}))
        # a no-budget case with its own cycle count is the IDLE line that never
        # stops (long_gap): stage 0 must not run, so it runs only that long
        run_len = ncyc if (not b and name in RP.NCYC_FOR) else NCYC_MAX
        log, mem, lv0, s0 = sim(vvp, tmp, name, RP.sniff_image(mask, b), stim, run_len)
        p, want, roles, pc = judge(case, log, mem, lv0, s0)
        results[name] = (log, lv0, want)
        if want is not None:
            seen |= role_codes(want)
            worst = max(worst, pc)
        print("  %-20s edges %4d  %-30s %s" % (
            name, len(log), ("table %s" % want.hex()) if want else "(capture never stopped)",
            "bit-exact" if not p else "*** " + p[0]))
        probs += ["%s: %s" % (name, x) for x in p]
    need = {S0.R_CLOCK, S0.R_SYNC, S0.R_FRAME, S0.R_AMBIG, S0.R_CLOCK_I2C, S0.R_SYNC_I2C, S0.R_REFUSED}
    if not need <= seen:
        probs.append("role codes never exercised: %s" % sorted(need - seen))
    print("  role codes exercised: %s; the slowest stage 0 ended at PIT cycle %d" % (sorted(seen), worst))
    # floor_edge has TEETH only if, AS STORED, the median index is a 7 and the
    # next one an 8 (the off-by-one median's flip) -- checked, not assumed
    log_fe, lv_fe, _w = results["floor_edge"]
    fe = [c for c in cs if c[0] == "floor_edge"][0]
    stored = S0.stored_capture(log_fe, lv_fe, RP.PG.budget_cycles(fe[3]), NCYC_MAX)
    ee = [t for t, m_, _l in stored if m_ >> 4 & 1]
    srt = sorted(y - x for x, y in zip(ee, ee[1:]))
    kf = (len(ee) - 1) // 2
    if not (srt[kf] < 8 <= srt[kf + 1]):
        probs.append("floor_edge has no teeth as stored: sorted[%d] = %d, sorted[%d] = %d"
                     % (kf, srt[kf], kf + 1, srt[kf + 1]))
    # k0 and frame2 have teeth only AS STORED (coverage arms, 10-29): k0's
    # first 16 raw intervals give k = 0 without an overrun; frame2's wire 2 is
    # a FRAME with 2 edges (only the FRAME pass can make it one)
    log_k, lv_k, _w = results["k0"]
    kc = [c for c in cs if c[0] == "k0"][0]
    st_k = S0.stored_capture(log_k, lv_k, RP.PG.budget_cycles(kc[3]), NCYC_MAX)
    tk = [t for t, _m_, _l in st_k]
    k_st = RP.PG.k_of([b_ - a for a, b_ in zip([0] + tk, tk)][:16])
    why_k = RP.PG.encode(log_k, RP.PG.budget_cycles(kc[3]), NCYC_MAX)[3]
    if len(tk) <= 16 or k_st != 0 or why_k != "budget":
        probs.append("k0 has no teeth as stored: %d records, k = %d, stop %s" % (len(tk), k_st, why_k))
    log_f, lv_f, want_f = results["frame2"]
    fc_ = [c for c in cs if c[0] == "frame2"][0]
    st_f = S0.stored_capture(log_f, lv_f, RP.PG.budget_cycles(fc_[3]), NCYC_MAX)
    n2 = sum(1 for _t, m_, _l in st_f if m_ >> 2 & 1)
    w2 = role_of(want_f, 2)
    if n2 != 2 or w2 != S0.R_FRAME or not (lv_f >> 1 & 1):
        probs.append("frame2 has no teeth as stored: wire 2 edges %d, role %d, start levels %02x" % (n2, w2, lv_f))
    # midstream has teeth only if the bench REALLY woke up mid-transfer: CS (1)
    # asserted and SCK (0) high at the start, the first edge within 8 cycles
    log_m, lv_m, _w = results["midstream"]
    if not log_m or log_m[0][0] > 8 or (lv_m >> 1 & 1) or not (lv_m & 1):
        probs.append("midstream did not start mid-transfer: start levels %02x, first edge at %s"
                     % (lv_m, log_m[0][0] if log_m else None))
    print("\n  must-fires")
    model = S0.frozen_model()
    by = {c[0]: c for c in cs}
    for define, what, targets, switch in MUTANTS:
        # the case must have TEETH in the model where the model can say so
        if switch is not None:
            attr, off = switch
            keep = getattr(model, attr)
            setattr(model, attr, off)
            try:
                for tname in targets:
                    log, lv0, want = results[tname]
                    c = by[tname]
                    alt, _r = S0.expect(log, lv0, RP.PG.budget_cycles(c[3]), None)
                    if alt == want:
                        probs.append("%s: case %s has no teeth -- the model with %s=%r gives the same table"
                                     % (define, tname, attr, off))
            finally:
                setattr(model, attr, keep)
        mv = os.path.join(tmp, "s0_%s.vvp" % define.lower())
        RP.build(mv, [define])
        broke = []
        for tname in targets:
            c = by[tname]
            log, mem, lv0, s0 = sim(mv, tmp, tname + "_m", RP.sniff_image(c[2], c[3]),
                                    RP.waves_to_stim(c[1], **STIM_OPTS.get(tname, {})),
                                    NCYC_MAX)
            got = bytes((mem.get(S0.TABLE_AT + i, -1) & 0xFF) for i in range(S0.TABLE_BYTES))
            if table_problems(got, results[tname][2]):
                broke.append(tname)
        print("    %-18s %-36s %s" % (define, what, ("RED on " + ", ".join(broke)) if broke else "*** SURVIVED ***"))
        if not broke:
            probs.append("%s survived" % define)
    print()
    for p_ in probs:
        print("  *** " + p_)
    print("  GATE pit-s0: %s" % ("FAILED" if probs else "PASSED"))
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())
