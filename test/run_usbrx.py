#!/usr/bin/env python3
"""The USB RECEIVE's gate: NRZI decode, unstuffing and re-anchoring on the
self-timed SHIFTIN (v2 primitive 3, bundle 3; Wilson 11-08).

THE ONE CLAIM: on the USB lane, a program of one ARM (the SOP edge), a d/2
no-op and twelve USB-receive bytes decodes every low-speed DATA packet the host
sends -- SYNC, PID, 8 data bytes, CRC16 -- EXACTLY, with the host's bit time
off by -1.5 %, 0 and +1.5 % (the device tolerance the host may use) and every
edge placed up to E = 8 cycles late, including the longest packet (8 x 0xFF,
the most stuffing: 100 bits after SYNC). A run of seven ones sets the
stuff-error flag, which clears when the next packet starts.

THE GOLDEN: the host side is built here -- SYNC + PID + payload + CRC16,
stuffed from SYNC's first bit, NRZI-encoded on D- (J = 1), bit k's edge at
round(t0 + k * T) plus 0..E cycles, EOP = 2 bits of SE0 then J. The receive is
predicted by decoding those wire bits with the chip's rule (NRZI; the bit after
six ones is dropped and counted as an error if it is a 1), and that decode is
itself checked equal to the bytes sent. The bench's pushes and flag changes
must equal the prediction exactly.

Bench: test/tb_usbrx.v. Images built here from pe_isa.
  U1  each drift x E: four packets, every byte and the flag sequence exact
  U2  stuff error: a stuffed 0 replaced by 1 (seven ones) -> flag 1, the bytes
      still exact (the slot is dropped either way), flag 0 at the next packet
  U3  the encoding off the USB lane: the chip refuses it (config_err), and
      pe_isa refuses it statically
  U4  must-fires: M_NO_REANCHOR (one anchor at SOP: ±1.5 % must lose bytes),
      M_UNSTUFF_KEEP (the stuffed bit kept as data), M_STUFF_NOFLAG (seven ones
      not flagged) each turn the gate red

POSITIVE TOKEN: `GATE usbrx: PASSED`.
"""

from __future__ import annotations

import os
import random
import re
import subprocess
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

from toolchain import banner, tool      # noqa: E402
import clock                            # noqa: E402
import pe_isa as I                      # noqa: E402
import sim_run                          # noqa: E402

BENCH = "test/tb_usbrx.v"
RTL = ["src/pe_engine.v", "src/pe_store.v", "src/project.v"]
GEN = "run_usbrx"
DM = 2                 # uio[2] = the host's D- (low speed: J = D- high)
D = 40                 # LS: 40 cycles a bit at 60 MHz
NBYTES = 12            # SYNC + PID + 8 data + CRC16
T_FIRST, GAP, POST = 600, 500, 300

# ---- the host side ---------------------------------------------------------


def crc16(data):
    c = 0xFFFF
    for b in data:
        for i in range(8):
            c = ((c >> 1) ^ 0xA001) if ((c ^ (b >> i)) & 1) else (c >> 1)
    c ^= 0xFFFF
    return [c & 0xFF, c >> 8]


def bits_lsb(bs):
    return [(b >> i) & 1 for b in bs for i in range(8)]


def stuff(bits):
    """-> (stuffed bits, indices of the stuffed zeros)"""
    out, run, where = [], 0, []
    for b in bits:
        out.append(b)
        run = run + 1 if b else 0
        if run == 6:
            where.append(len(out))
            out.append(0)
            run = 0
    return out, where


def packet(pid, payload, corrupt=False):
    """(wire bits from SYNC's first, the bytes the receive must push). With
    `corrupt`, the FIRST stuffed 0 becomes a 1: seven ones on the wire."""
    sent = [0x80, pid] + list(payload) + crc16(payload)
    wire, where = stuff(bits_lsb(sent))
    if corrupt:
        if not where:
            raise ValueError("no stuffed bit to corrupt")
        wire[where[0]] = 1
    return wire, sent


def decode(wire):
    """the chip's rule on decoded wire bits -> (bytes, stuff errors). NRZI is
    already undone: the wire bits ARE the decoded bits."""
    out, run, errs, cur = [], 0, 0, []
    for b in wire:
        if run == 6:
            errs += b
            run = 0
            continue
        cur.append(b)
        run = run + 1 if b else 0
        if len(cur) == 8:
            out.append(sum(v << i for i, v in enumerate(cur)))
            cur = []
    return out[:NBYTES], errs


def line(packets, e, E, seed, walk=False):
    """the D- transitions [(cycle, level)] for `packets`, bit time D*(1+e),
    each edge 0..E cycles late; and the cycle the last one ends. `walk`: the
    edge times stay FRACTIONAL (each packet starts a golden-ratio fraction of a
    cycle later, lateness is real-valued in 0..E), so the bench's absolute-
    time host walks the sub-cycle phase; otherwise every edge is a whole cycle."""
    rng = random.Random(seed)
    T = D * (1.0 + e)
    tr, t0, lvl = [], float(T_FIRST), 1
    q = (lambda t: t + rng.uniform(0, E)) if walk else (lambda t: int(round(t)) + rng.randint(0, E))
    for p, (wire, _sent) in enumerate(packets):
        if walk:
            t0 += (p * 0.618034) % 1.0
        for k, b in enumerate(wire):
            if b == 0:
                lvl ^= 1
                tr.append((q(t0 + k * T), lvl))
        t_eop = t0 + len(wire) * T
        if lvl == 1:
            tr.append((q(t_eop), 0))           # SE0
        tr.append((q(t_eop + 2 * T), 1))       # J
        lvl = 1
        t0 = t_eop + 3 * T + GAP
    return tr, int(t0)


def write_wave(path, tr):
    with open(path, "w") as fh:
        fh.write("".join("%.4f %d\n" % (c, l) for c, l in tr))


#: PHASE COVERAGE (Wilson 10-20 standing rule; model/phase_coverage.py holds
#: this runner's row IN_SUITE): the walk arm must put the host's edges in all
#: but PHASE_SHORT of the period's 1 ns bins -- MEASURED by the bench.
PHASE_SHORT = 0
PHASE_FLOOR = clock.phases() - PHASE_SHORT


# ---- the program -----------------------------------------------------------


def image(lane=I.USB_LANE, busy=None):
    """one USB packet receive per pass on `lane`; every other lane idle -- or,
    with `busy = (usb D_sched, other D_sched)`, the four other lanes toggling
    `uo_out` every D* = 20 cycles (the dispatcher as loaded as it gets)"""
    prog = [I.act(I.OP_ARM, DM, 0, 0),                 # the SOP edge (J -> K), no timeout
            I.act(I.OP_LEVEL, I.PIN_NONE, 0, D // 2)]  # half a bit: sample mid-bit
    prog += [I.act_shiftin_usb(DM, D, 8) for _ in range(NBYTES)]
    prog += [I.act(I.OP_LEVEL, I.PIN_NONE, 0, POST),   # past the EOP
             I.act(I.OP_REARM, 0, 1, D // 2)]          # loop to the ARM
    l0 = I.ACT_BASE
    lp = l0 + len(prog) * I.ACT_BYTES
    if busy is not None:
        usb_ds, oth_ds = busy
        headers = [I.hdr(DM, I.PIN_NONE, 1, D, 0, usb_ds, 3 * D, l0)]
        for n in range(1, I.N_LANES):
            b = lp + (n - 1) * 3 * I.ACT_BYTES
            prog += [I.act(I.OP_LEVEL, I.UO0 + n - 1, 1, 20), I.act(I.OP_LEVEL, I.UO0 + n - 1, 0, 20),
                     I.act(I.OP_REARM, 0, 1, 20)]
            headers.append(I.hdr(I.UO0 + n - 1, I.UO0 + n - 1, 1, 20, 0, oth_ds, oth_ds + 20, b))
        return I.join_image(headers, prog)
    prog.append(I.act(I.OP_REARM, 0, 0, 500))
    idle = lambda n: I.hdr(n + 2, n + 2, 0, 500, 0, 200, 240, lp)
    usb = I.hdr(DM, I.PIN_NONE, 1, D, 0, 2 * D, 3 * D, l0)
    headers = []
    for n in range(I.N_LANES):
        if n == lane:
            headers.append(usb)
        elif n == I.USB_LANE:           # the USB lane idles on another pin
            headers.append(I.hdr(7, 7, 0, 500, 0, 200, 240, lp))
        else:
            headers.append(idle(n))
    return I.join_image(headers, prog)


# ---- the cases -------------------------------------------------------------

DATA0, DATA1 = 0xC3, 0x4B
#: STIMULUS: four payloads -- the most stuffing (8 x 0xFF, the 100-bit
#: packet), runs of six crossing byte boundaries, no stuffing and every bit an
#: edge (zeros), and a seeded random one
PAYLOADS = [(DATA0, [0xFF] * 8),
            (DATA1, [0x80, 0xFF, 0x01, 0xFC, 0x3F, 0xE0, 0x07, 0xFF]),
            (DATA0, [0x00] * 8),
            (DATA1, [random.Random(11).getrandbits(8) for _ in range(8)])]
#: the host's bit-time error (Wilson: ±1.5 %) and edge lateness (E, the note's 0..8)
DRIFTS = (-0.015, 0.0, 0.015)
EDGE_LATE = (0, 8)


def cases():
    """[(name, packets, e, E, seed, expect_errs_seq)]"""
    out = []
    for e in DRIFTS:
        for E in EDGE_LATE:
            out.append(("e%+.3f E%d" % (e, E), [packet(*p) for p in PAYLOADS], e, E,
                        int(1000 * e) * 10 + E, []))
    # U2: seven ones in the worst packet at the worst drift, then a clean one
    out.append(("stuff-error", [packet(*PAYLOADS[0], corrupt=True), packet(*PAYLOADS[3])],
                0.015, 8, 77, [1, 0]))
    return out


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def build(out, defines=()):
    r = run([tool("iverilog"), "-g2012", "-I", ROOT, "-o", out, "-s", "tb_usbrx"]
            + ["-D%s" % d for d in defines] + [BENCH] + RTL)
    if r.returncode != 0:
        raise RuntimeError("build %s failed: %s" % (out, (r.stdout + r.stderr)[-400:]))


def sim(vvp, img, wave, ncyc):
    r = run(sim_run.vvp([vvp, "+IMG=%s" % img, "+WAVE=%s" % wave, "+NCYC=%d" % ncyc],
                        images=[img]))
    out = r.stdout + r.stderr
    rx = [(int(c), int(v), int(ln)) for c, v, ln in re.findall(r"^RX (\d+) (\d+) (\d+)$", out, re.M)]
    se = [(int(c), int(v)) for c, v in re.findall(r"^SE (\d+) (\d+)$", out, re.M)]
    ce = [int(c) for c in re.findall(r"^CE (\d+)$", out, re.M)]
    sa = [(int(c), int(t)) for c, t in re.findall(r"^SA (\d+) (\d+)$", out, re.M)]
    return rx, se, ce, sa, ("END" in out), out[-300:]


def sample_timing(tr, sa):
    """-> (set of edge-to-sample latencies, writeback jitter, [problem]).
    THE TIMING CLAIM, exact, on each sample's SCHEDULED release `ts` (the lane
    timestamp -- jitter-free by construction): a sample with no host edge since
    the previous one is scheduled exactly D after it; a sample after an edge is
    scheduled a CONSTANT K after the last such edge -- the same K for the
    packet's first sample (the ARM + d/2 path) as for every re-anchor. `ts` is
    in `now` units and edges in bench cycles; the offset is constant, so K
    absorbs it. The registered re-anchor must keep that identity.
    MEASURED, not judged: the spread of (writeback - ts), the dispatch jitter
    a receive sample sees from other lanes' non-preemptive service."""
    edges = sorted(c for c, _l in tr)
    ks, probs, prev = set(), [], None
    for w, ts in sa:
        lo = prev if (prev is not None and w - prev[0] <= 3 * D) else None
        between = [c for c in edges if c < w and (lo is None or c > lo[0])]
        if lo is not None and not between:
            if ts - lo[1] != D:
                probs.append("samples scheduled at %d and %d are %d apart with no edge "
                             "between, not %d" % (lo[1], ts, ts - lo[1], D))
        elif between:
            ks.add(ts - between[-1])
        prev = (w, ts)
    lat = [w - ts for w, ts in sa]
    jit = (max(lat) - min(lat)) if lat else 0
    return ks, jit, probs


def judge(name, packets, rx, se, ce, sa, tr, end, tail, expect_se):
    probs = []
    if not end:
        return ["%s: no END (%s)" % (name, tail)], set(), 0
    ks, jit, tp = sample_timing(tr, sa)
    probs += ["%s: %s" % (name, x) for x in tp[:2]]
    if len(ks) != 1:
        probs.append("%s: edge-to-sample latency not constant: %s" % (name, sorted(ks)))
    gold = []
    for wire, sent in packets:
        dec, _errs = decode(wire)
        gold += dec
    got = [v for _c, v, _ln in rx]
    if any(ln != I.USB_LANE for _c, _v, ln in rx):
        probs.append("%s: a push from lane %s" % (name, sorted({ln for _c, _v, ln in rx})))
    if got != gold:
        i = next((k for k, (a, b) in enumerate(zip(got, gold)) if a != b), min(len(got), len(gold)))
        probs.append("%s: %d bytes, golden %d; first difference at byte %d: got %s, golden %s"
                     % (name, len(got), len(gold), i,
                        "%02X" % got[i] if i < len(got) else "-",
                        "%02X" % gold[i] if i < len(gold) else "-"))
    if [v for _c, v in se] != expect_se:
        probs.append("%s: stuff-error flag changes %s, golden %s" % (name, [v for _c, v in se], expect_se))
    if ce:
        probs.append("%s: config_err at cycle %d" % (name, ce[0]))
    return probs, ks, jit


def run_suite(vvp, tmp, tag, pool):
    """-> {case name: [problem]}"""
    img = os.path.join(tmp, "usbrx_main.hex")
    if not os.path.exists(img):
        I.write_image(img, image())
        sim_run.scratch_image(GEN, img)
    jobs = {}
    for name, packets, e, E, seed, exp in cases():
        # ⛔ the SIGN stays in the name: "e-0.015" and "e+0.015" once both became
        # "e_0_015" and the parallel runs overwrote each other's host line
        safe = re.sub(r"[^A-Za-z0-9]+", "_", name.replace("+", "p").replace("-", "m"))
        wave = os.path.join(tmp, "wave_%s_%s.txt" % (tag, safe))
        tr, t_end = line(packets, e, E, seed)
        write_wave(wave, tr)
        jobs[name] = (packets, exp, tr, pool.submit(sim, vvp, img, wave, t_end + 400))
    res, ks, jit = {}, set(), 0
    for name, (packets, exp, tr, fut) in jobs.items():
        rx, se, ce, sa, end, tail = fut.result()
        res[name], k, j = judge(name, packets, rx, se, ce, sa, tr, end, tail, exp)
        ks |= k
        jit = max(jit, j)
    # one latency across EVERY case: the identity is global, not per run
    if len(ks) != 1:
        res["latency"] = ["edge-to-sample latency differs across cases: %s" % sorted(ks)]
    else:
        res["latency"] = []
    return res, ks, jit


def main() -> int:
    banner("iverilog", "vvp")
    print()
    print("=" * 78)
    print("The USB receive: NRZI, unstuffing, re-anchoring (v2 primitive 3, bundle 3)")
    print("=" * 78)
    probs = []
    # the golden's own premise: the chip's decode rule recovers what was sent
    for pid, pay in PAYLOADS:
        wire, sent = packet(pid, pay)
        dec, errs = decode(wire)
        if dec != sent or errs:
            probs.append("golden: decode of %02X %s does not recover the bytes" % (pid, pay))
    wire0, _s = packet(*PAYLOADS[0])
    print("  longest packet: %d bits after SYNC (8 x 0xFF)" % (len(wire0) - 8))
    wire_c, sent_c = packet(*PAYLOADS[0], corrupt=True)
    if decode(wire_c) != (sent_c, 1):
        probs.append("golden: the corrupt packet does not decode to the bytes with one error")
    pr = I.branch_problems(image())
    if pr:
        probs.append("valid image refused by pe_isa: %s" % pr)

    tmp = tempfile.mkdtemp(prefix="pe_usbrx_")
    vvp = os.path.join(tmp, "usbrx.vvp")
    build(vvp)
    with ThreadPoolExecutor(max_workers=8) as pool:
        res, ks, jit = run_suite(vvp, tmp, "base", pool)
        print("\n  U1/U2 the receive (bytes, flag, and every scheduled sample instant)")
        for name, pr in res.items():
            print("    %-16s %s" % (name, "exact" if not pr else "*** " + pr[0]))
            probs += pr
        print("    edge-to-scheduled-sample latency: %s, the SOP path and every re-anchor alike"
              % (sorted(ks),))
        print("    MEASURED: receive-sample dispatch jitter (writeback - schedule spread): %d cycle(s)"
              % jit)

        # U3: off the USB lane
        print("\n  U3 the encoding off the USB lane")
        wimg = os.path.join(tmp, "usbrx_wrong.hex")
        I.write_image(wimg, image(lane=1))
        sim_run.scratch_image(GEN, wimg)
        st = I.usb_problems(image(lane=1))
        print("    pe_isa: %s" % ("refused" if st else "*** ACCEPTED"))
        if not st:
            probs.append("pe_isa accepted a USB receive on lane 1")
        tr, t_end = line([packet(*PAYLOADS[3])], 0.0, 0, 5)
        wwave = os.path.join(tmp, "wave_wrong.txt")
        write_wave(wwave, tr)
        rx, _se, ce, _sa, end, tail = sim(vvp, wimg, wwave, t_end + 400)
        ok = end and ce and not rx
        print("    chip:   %s" % ("config_err at cycle %d, no byte pushed" % ce[0] if ok
                                  else "*** not refused (pushes %d, config_err %s)" % (len(rx), ce)))
        if not ok:
            probs.append("the chip did not refuse a USB receive on lane 1")

        # U5: the deadline rule (Wilson 11-08) -- refused when broken, and
        # LOAD-BEARING: shown once by running the broken image anyway
        print("\n  U5 the deadline rule (USB lane D_sched strictly earliest), four lanes busy at D*")
        for tag, cfg, want_ok in (("obeyed", (30, 40), True), ("broken", (80, 40), False)):
            bimg = os.path.join(tmp, "usbrx_busy_%s.hex" % tag)
            I.write_image(bimg, image(busy=cfg))
            sim_run.scratch_image(GEN, bimg)
            st = I.usb_problems(image(busy=cfg))
            jobs = []
            for e in DRIFTS:
                pk = [packet(*p) for p in PAYLOADS]
                tr, t_end = line(pk, e, 8, 500 + int(1000 * e))
                wv = os.path.join(tmp, "wave_busy_%s_%s.txt" % (tag, "m" if e < 0 else ("p" if e > 0 else "0")))
                write_wave(wv, tr)
                jobs.append((e, pk, tr, pool.submit(sim, vvp, bimg, wv, t_end + 400)))
            worst, bad = 0, []
            for e, pk, tr, fut in jobs:
                rx, se, ce, sa, end, tail = fut.result()
                pr, _k, j = judge("busy %s e%+.3f" % (tag, e), pk, rx, se, ce, sa, tr, end, tail, [])
                worst = max(worst, j)
                bad += pr
            print("    %-7s D_sched usb %d / others %d: pe_isa %s; receive-sample wait %d cycle(s); %s"
                  % (tag, cfg[0], cfg[1], "refuses" if st else "accepts", worst,
                     "every byte and sample instant exact" if not bad else "*** " + bad[0][:80]))
            if want_ok:
                if st:
                    probs.append("deadline rule: pe_isa refused the obeying image: %s" % st[0])
                if bad:
                    probs.append("deadline rule obeyed, but: %s" % bad[0])
                if worst > 2:
                    probs.append("deadline rule obeyed, but the receive-sample wait is %d > 2" % worst)
            else:
                if not st:
                    probs.append("MUST-FIRE: pe_isa accepted a USB image whose deadline is not the earliest")
                if worst <= 2:
                    probs.append("deadline rule broken, yet the wait stayed %d <= 2: the rule is "
                                 "not shown load-bearing" % worst)

        # U6: PHASE COVERAGE -- the same packets with every host edge at a
        # fractional time; bytes and flag exact, and the MEASURED 1 ns bins
        # must reach PHASE_FLOOR (the IN_SUITE row in model/phase_coverage.py)
        print("\n  U6 the sub-cycle phase walk (host edges at fractional times)")
        wjobs = []
        for e in DRIFTS:
            pk = [packet(*p) for p in PAYLOADS]
            tr, t_end = line(pk, e, 8, 900 + int(1000 * e), walk=True)
            wv = os.path.join(tmp, "wave_walk_%s.txt" % ("m" if e < 0 else ("p" if e > 0 else "0")))
            write_wave(wv, tr)
            wjobs.append((e, pk, pool.submit(run, sim_run.vvp(
                [vvp, "+IMG=%s" % os.path.join(tmp, "usbrx_main.hex"), "+WAVE=%s" % wv,
                 "+NCYC=%d" % (t_end + 400)], images=[os.path.join(tmp, "usbrx_main.hex")]))))
        for e, pk, fut in wjobs:
            out = fut.result().stdout
            got = [int(v) for _c, v, _l in re.findall(r"^RX (\d+) (\d+) (\d+)$", out, re.M)]
            gold = [b for w, _s in pk for b in decode(w)[0]]
            ph = re.search(r"^PH (\d+) (\d+)$", out, re.M)
            nb = int(ph.group(1)) if ph else -1
            se = re.findall(r"^SE ", out, re.M)
            ok = ("END" in out and got == gold and not se and nb >= PHASE_FLOOR)
            print("    e%+.3f  %s  phase bins %d/%d (floor %d)"
                  % (e, "bytes exact" if got == gold else "*** %d bytes, golden %d" % (len(got), len(gold)),
                     nb, clock.phases(), PHASE_FLOOR))
            if not ok:
                probs.append("phase walk e%+.3f: bytes %s, stuff flag %s, bins %d < floor %d?"
                             % (e, got == gold, bool(se), nb, PHASE_FLOOR))

        print("\n  U4 must-fires")
        for d, what in MUTANTS:
            mv = os.path.join(tmp, "usbrx_%s.vvp" % d)
            try:
                build(mv, [d])
            except RuntimeError as exc:
                probs.append("%s: %s" % (d, exc))
                continue
            r, _k, _j = run_suite(mv, tmp, d, pool)
            red = [(n, p[0]) for n, p in r.items() if p]
            print("    %-16s %-40s %s" % (d, what, ("RED in %d of %d cases: %s -- %s"
                                                     % (len(red), len(r), red[0][0], red[0][1][:70]))
                                              if red else "*** SURVIVED"))
            if not red:
                probs.append("%s survived" % d)
            elif d == "M_NO_REANCHOR":
                # Wilson: re-anchoring disabled must FAIL at ±1.5 % -- each drift's own cases
                for e in (-0.015, 0.015):
                    if not any(n.startswith("e%+.3f" % e) for n, _p in red):
                        probs.append("M_NO_REANCHOR survived at e = %+.3f" % e)

    print()
    if probs:
        print("  GATE usbrx: FAILED (%d)" % len(probs))
        for x in probs:
            print("    - %s" % x)
        return 1
    print("  GATE usbrx: PASSED")
    return 0


MUTANTS = [
    ("M_NO_REANCHOR", "one anchor at SOP, none at the edges"),
    ("M_UNSTUFF_KEEP", "the stuffed bit kept as data"),
    ("M_STUFF_NOFLAG", "seven ones not flagged"),
    ("M_REAN_NOCOMP", "registered re-anchor, cycle not taken off"),
]


if __name__ == "__main__":
    sys.exit(main())
