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


def line(packets, e, E, seed):
    """the D- transitions [(cycle, level)] for `packets`, bit time D*(1+e),
    each edge 0..E cycles late; and the cycle the last one ends"""
    rng = random.Random(seed)
    T = D * (1.0 + e)
    tr, t0, lvl = [], float(T_FIRST), 1
    for wire, _sent in packets:
        for k, b in enumerate(wire):
            if b == 0:
                lvl ^= 1
                tr.append((int(round(t0 + k * T)) + rng.randint(0, E), lvl))
        t_eop = t0 + len(wire) * T
        if lvl == 1:
            tr.append((int(round(t_eop)) + rng.randint(0, E), 0))      # SE0
        tr.append((int(round(t_eop + 2 * T)) + rng.randint(0, E), 1))  # J
        lvl = 1
        t0 = t_eop + 3 * T + GAP
    return tr, int(t0)


# ---- the program -----------------------------------------------------------


def image(lane=I.USB_LANE):
    """one USB packet receive per pass on `lane`; every other lane idle"""
    prog = [I.act(I.OP_ARM, DM, 0, 0),                 # the SOP edge (J -> K), no timeout
            I.act(I.OP_LEVEL, I.PIN_NONE, 0, D // 2)]  # half a bit: sample mid-bit
    prog += [I.act_shiftin_usb(DM, D, 8) for _ in range(NBYTES)]
    prog += [I.act(I.OP_LEVEL, I.PIN_NONE, 0, POST),   # past the EOP
             I.act(I.OP_REARM, 0, 1, D // 2)]          # loop to the ARM
    l0 = I.ACT_BASE
    lp = l0 + len(prog) * I.ACT_BYTES
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
    return rx, se, ce, ("END" in out), out[-300:]


def judge(name, packets, rx, se, ce, end, tail, expect_se):
    probs = []
    if not end:
        return ["%s: no END (%s)" % (name, tail)]
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
    return probs


def run_suite(vvp, tmp, tag, pool):
    """-> {case name: [problem]}"""
    img = os.path.join(tmp, "usbrx_main.hex")
    if not os.path.exists(img):
        I.write_image(img, image())
        sim_run.scratch_image(GEN, img)
    jobs = {}
    for name, packets, e, E, seed, exp in cases():
        wave = os.path.join(tmp, "wave_%s_%s.txt" % (tag, re.sub(r"[^A-Za-z0-9]+", "_", name)))
        tr, t_end = line(packets, e, E, seed)
        with open(wave, "w") as fh:
            fh.write("".join("%d %d\n" % x for x in tr))
        jobs[name] = (packets, exp, pool.submit(sim, vvp, img, wave, t_end + 400))
    res = {}
    for name, (packets, exp, fut) in jobs.items():
        rx, se, ce, end, tail = fut.result()
        res[name] = judge(name, packets, rx, se, ce, end, tail, exp)
    return res


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
        res = run_suite(vvp, tmp, "base", pool)
        print("\n  U1/U2 the receive")
        for name, pr in res.items():
            print("    %-16s %s" % (name, "exact" if not pr else "*** " + pr[0]))
            probs += pr

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
        with open(wwave, "w") as fh:
            fh.write("".join("%d %d\n" % x for x in tr))
        rx, _se, ce, end, tail = sim(vvp, wimg, wwave, t_end + 400)
        ok = end and ce and not rx
        print("    chip:   %s" % ("config_err at cycle %d, no byte pushed" % ce[0] if ok
                                  else "*** not refused (pushes %d, config_err %s)" % (len(rx), ce)))
        if not ok:
            probs.append("the chip did not refuse a USB receive on lane 1")

        print("\n  U4 must-fires")
        for d, what in MUTANTS:
            mv = os.path.join(tmp, "usbrx_%s.vvp" % d)
            try:
                build(mv, [d])
            except RuntimeError as exc:
                probs.append("%s: %s" % (d, exc))
                continue
            r = run_suite(mv, tmp, d, pool)
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
]


if __name__ == "__main__":
    sys.exit(main())
