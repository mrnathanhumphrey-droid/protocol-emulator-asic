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
        if got != want:
            probs.append("table RTL %s, golden %s" % (got.hex(), want.hex()))
    return probs, want, roles, int((s0 or {}).get("pc", "0"))


def role_codes(table_bytes):
    word = int.from_bytes(table_bytes, "little")
    return {(word >> (7 * w)) & 7 for w in range(8)}


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
        stim = RP.waves_to_stim(waves)
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
            log, mem, lv0, s0 = sim(mv, tmp, tname + "_m", RP.sniff_image(c[2], c[3]), RP.waves_to_stim(c[1]),
                                    NCYC_MAX)
            got = bytes((mem.get(S0.TABLE_AT + i, -1) & 0xFF) for i in range(S0.TABLE_BYTES))
            if got != results[tname][2]:
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
