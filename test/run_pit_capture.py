#!/usr/bin/env python3
"""v2 PIT chunk 1 gate: the SNIFF capture, BIT FOR BIT (Wilson 10-28).

THE ONE CLAIM: for every case, the store bytes the RTL writes in SNIFF mode
(capture 128..511, status 2 / 28 / 29) equal model/pit_capture_golden.py's
encoding of the SAME edge log -- the bench's own record of every change of the
masked synchronised uio bus -- byte for byte; and each must-fire (k off by
one, a mask bit dropped, no overrun stop) breaks that equality.

Cases: SPI mode 0 and 3 with CS, SPI with the wire mask 0x03, I2C, two UARTs
at 2:1, and a fast line that must OVERRUN.   token: GATE pit-capture: PASSED
"""
from __future__ import annotations

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

from toolchain import banner, tool          # noqa: E402
import pe_isa as I                          # noqa: E402
import sim_run                              # noqa: E402
import pit_capture_golden as PG             # noqa: E402

BENCH = "test/tb_pit.v"
RTL = ["src/pe_engine.v", "src/pe_store.v", "src/project.v"]
GEN = "run_pit_capture"
NCYC = 60000
MUTANTS = [("M_PIT_K_OFF1", "k one too large"), ("M_PIT_MASK_DROP", "mask bit 0 never recorded"),
           ("M_PIT_NO_OVERRUN", "no stop on an accumulator overrun")]
RNG = random.Random(20261028)


def sniff_image(mask):
    img = bytearray(I.STORE_BYTES)
    img[0] = mask
    img[30], img[31] = 0x53, 0x4E          # the SNIFF magic 'S' 'N'
    return bytes(img)


def waves_to_stim(waves, t0=50):
    """{wire: [(level, cycles)]} -> [(cycle, uio value)] (one line per change)."""
    ev = {}
    for w, segs in waves.items():
        t, prev = t0, None
        for lvl, c in segs:
            if prev is not None and lvl != prev:
                ev.setdefault(t, {})[w] = lvl
            elif prev is None:
                ev.setdefault(t0 - 1, {})[w] = lvl
            prev = lvl
            t += c
    out, v = [], 0
    for t in sorted(ev):
        for w, lvl in ev[t].items():
            v = (v & ~(1 << w)) | (lvl << w)
        out.append((t, v))
    return out


def spi(mode, nbytes=40, half=19):
    cpol, cpha = mode >> 1, mode & 1
    sck, mosi, cs = [(cpol, 100)], [(0, 103 - (half if cpha == 0 else 0))], [(1, 90), (0, 10)]
    for k in range(nbytes):
        b = RNG.getrandbits(8)
        for i in range(7, -1, -1):
            sck += [(1 - cpol, half), (cpol, half)]
            mosi.append(((b >> i) & 1, 2 * half))
        if k % 4 == 3:
            g = 200 + RNG.randint(0, 80)
            sck.append((cpol, g))
            mosi.append((mosi[-1][0], g))
            cs += [(0, 4 * 16 * half + 10), (1, g - 20), (0, 10)]
    return {0: sck, 1: mosi, 2: cs}


def i2c(nbytes=30, q=23):
    scl, sda = [(1, 120)], [(1, 120)]
    for k in range(nbytes):
        if k % 3 == 0:
            sda.append((0, q)); scl.append((1, q))
        b = RNG.getrandbits(8)
        for i in list(range(7, -1, -1)) + [None]:
            bit = 0 if i is None else (b >> i) & 1
            scl.append((0, q)); sda.append((sda[-1][0], q // 2)); sda.append((bit, q - q // 2))
            scl.append((1, 2 * q)); sda.append((bit, 2 * q))
        if k % 3 == 2:
            scl.append((0, q)); sda.append((0, q)); scl.append((1, 4 * q))
            sda.append((0, q)); sda.append((1, 3 * q))
    return {3: scl, 4: sda}


def uarts():
    def u(P, n):
        s = [(1, 3 * P)]
        for _ in range(n):
            b = RNG.getrandbits(8)
            s.append((0, P)); s += [((b >> i) & 1, P) for i in range(8)]
            s.append((1, P + RNG.randint(P, 12 * P)))
        return s
    return {5: u(40, 60), 6: u(80, 30)}


def fast():
    """two wires toggling on alternate cycles: during the RAW phase a 24-bit
    record arrives every cycle against a one-byte-per-cycle drain -- the
    accumulator MUST overflow (the stop reason is checked, not just the flag)."""
    return {6: [((k & 1), 2) for k in range(200)], 7: [(0, 1)] + [((k & 1), 2) for k in range(200)]}


CASES = [("spi0", spi(0), 0x00), ("spi3", spi(3), 0x00), ("spi0_mask03", spi(0), 0x03),
         ("i2c", i2c(), 0x00), ("uarts_2to1", uarts(), 0x00), ("fast_overrun", fast(), 0x00)]


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")


def build(out, defines=()):
    r = run([tool("iverilog"), "-g2012", "-I", ROOT, "-o", out, "-s", "tb_pit"]
            + ["-D%s" % d for d in defines] + [BENCH] + RTL)
    if r.returncode != 0:
        raise RuntimeError("build failed: %s" % (r.stdout + r.stderr)[-400:])


def sim(vvp, tmp, name, img, stim):
    ip = os.path.join(tmp, "pitcap_%s.hex" % name)
    I.write_image(ip, img)
    sim_run.scratch_image(GEN, ip)
    sp = os.path.join(tmp, "pitcap_%s.stim" % name)
    with open(sp, "w", encoding="ascii", newline="\n") as fh:
        for t, v in stim:
            fh.write("%d %02x\n" % (t, v))
    op = os.path.join(tmp, "pitcap_%s.out" % name)
    r = run(sim_run.vvp([vvp, "+IMG=%s" % ip, "+NBYTES=%d" % I.STORE_BYTES, "+STIM=%s" % sp,
                         "+OUT=%s" % op, "+NCYC=%d" % NCYC], images=[ip]))
    log, mem = [], {}
    with open(op, encoding="ascii") as fh:
        for ln in fh:
            t = ln.split()
            if t and t[0] == "E":
                log.append((int(t[1]), int(t[2], 16)))
            elif t and t[0] == "M":
                mem[int(t[1])] = int(t[2], 16) if re.fullmatch(r"[0-9a-fA-F]+", t[2]) else -1
    return log, mem, r.stdout + r.stderr


def compare(log, mem):
    """-> [problem]: every RTL byte against the golden encoding of the log."""
    cap, n, ovf, why = PG.encode(log)
    probs = []
    for i in range(PG.CAP_BYTES):
        if mem.get(PG.CAP_BASE + i) != cap[i]:
            probs.append("capture byte %d: RTL %s, golden %02x" % (PG.CAP_BASE + i, mem.get(PG.CAP_BASE + i), cap[i]))
            break
    want = {2: 0x80 if ovf else 0x00, 28: (n >> 8) & 0xFF if ovf else 0, 29: n & 0xFF if ovf else 0}
    for a, v in want.items():
        if mem.get(a) != v:
            probs.append("status byte %d: RTL %s, golden %02x" % (a, mem.get(a), v))
    return probs, n, ovf, why


def main() -> int:
    banner("iverilog", "vvp")
    print()
    print("=" * 78)
    print("PIT CAPTURE -- SNIFF mode, bit for bit against model/pit_capture_golden.py")
    print("=" * 78)
    tmp = tempfile.mkdtemp(prefix="pe_pitcap_")
    probs = []
    vvp = os.path.join(tmp, "pit.vvp")
    build(vvp)
    for name, waves, mask in CASES:
        log, mem, raw = sim(vvp, tmp, name, sniff_image(mask), waves_to_stim(waves))
        p, n, ovf, why = compare(log, mem)
        print("  %-14s edges %5d  records %4d  stop %-7s %s" % (name, len(log), n, why,
                                                                    "bit-exact" if not p else "*** " + p[0]))
        if not log:
            p.append("no edge was logged -- the case is vacuous")
        if name == "fast_overrun" and why != "overrun":
            p.append("the overrun case stopped on %r, not an overrun" % why)
        probs += ["%s: %s" % (name, x) for x in p]
    print("\n  must-fires")
    for define, what in MUTANTS:
        mv = os.path.join(tmp, "pit_%s.vvp" % define.lower())
        build(mv, [define])
        broke = []
        for name, waves, mask in CASES:
            log, mem, _raw = sim(mv, tmp, name + "_m", sniff_image(mask), waves_to_stim(waves))
            if compare(log, mem)[0]:
                broke.append(name)
        print("    %-18s %-36s %s" % (define, what, ("RED on " + ", ".join(broke)) if broke else "*** SURVIVED ***"))
        if not broke:
            probs.append("%s survived" % define)
    print()
    for p_ in probs:
        print("  *** " + p_)
    print("  GATE pit-capture: %s" % ("FAILED" if probs else "PASSED"))
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())
