#!/usr/bin/env python3
"""The USB RX CRC16 and the flags as virtual pins (v2 primitive 3, bundle 4;
Wilson 11-08).

THE ONE CLAIM: a program that receives a low-speed DATA packet (SYNC and PID
without the CRC, the eight data bytes and the CRC16 with it), then branches to
NAK on STUFF_ERR (virtual pin 14) and to ACK on CRC_OK (virtual pin 13), ACKs
EXACTLY the packets whose CRC checks and that carry no stuffing error, and NAKs
every other one -- at host drift -1.5 %, 0 and +1.5 %. A corrupted packet never
shows CRC_OK = 1 at the decision, so no program can branch to ACK on one.

THE GOLDEN: the host side (run_usbrx's): the packets are built here, some
corrupted AFTER their CRC is computed (a data bit, a CRC bit, two bits), one
with seven ones (a stuffing error, CRC intact). The decision is predicted in
Python: ACK iff crc16(payload) == the received CRC and no stuffing error. The
bench's markers (active-low pulses: uo_out[0] = ACK, [1] = NAK) must give exactly that sequence,
and each branch's sampled flag must equal the predicted flag.

Bench: test/tb_usbrx.v (its MK / BR lines). Images built here from pe_isa.
  C1  per drift: good / data-bit / good / CRC-bit / seven-ones / two-bit /
      good packets -> ACK, NAK, ACK, NAK, NAK, NAK, ACK; every received byte
      exact; the flags at each branch exact
  C2  forty seeded random packets at 0 drift, half corrupted (1-3 bits)
  C3  pe_isa: branching on READY (12, bundle 5) and on 15 is refused
  C4  must-fires: M_CRC_ALWAYS_OK (a corrupted packet ACKed), M_CRC_NO_PRIME
      (the CRC carried over from the previous packet) each turn the gate red

POSITIVE TOKEN: `GATE usbcrc: PASSED`.
"""

from __future__ import annotations

import os
import random
import re
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

from toolchain import banner             # noqa: E402
import pe_isa as I                       # noqa: E402
import sim_run                           # noqa: E402
import run_usbrx as U                    # noqa: E402

GEN = "run_usbcrc"
W = I.BR_W_MIN                           # the branch wait
ACK_PIN, NAK_PIN = I.UO0, I.UO1


def image():
    """lane 0: receive one DATA packet, decide, mark ACK or NAK, loop"""
    D = U.D
    p = [I.act(I.OP_ARM, U.DM, 0, 0),                         # 0  SOP
         I.act(I.OP_LEVEL, I.PIN_NONE, 0, D // 2),            # 1  mid-bit
         I.act_shiftin_usb(U.DM, D, 8),                       # 2  SYNC
         I.act_shiftin_usb(U.DM, D, 8)]                       # 3  PID
    p += [I.act_shiftin_usb(U.DM, D, 8, crc=True) for _ in range(10)]   # 4..13 data + CRC16
    nak, ack = 17, 21
    p += [I.act_branch_bit(I.VPIN_STUFF_ERR, 1, nak, W),      # 14 stuffing error -> NAK
          I.act(I.OP_LEVEL, I.PIN_NONE, 0, 20),               # 15 (no branch->branch chain)
          I.act_branch_bit(I.VPIN_CRC_OK, 1, ack, W),         # 16 CRC_OK -> ACK
          I.act(I.OP_LEVEL, NAK_PIN, 0, 20),                  # 17 NAK marker (active LOW:
          I.act(I.OP_LEVEL, NAK_PIN, 1, 20),                  #    pin_out resets HIGH)
          I.act(I.OP_LEVEL, I.PIN_NONE, 0, U.POST),
          I.act(I.OP_REARM, 0, 1, 20),                        # 20 loop
          I.act(I.OP_LEVEL, ACK_PIN, 0, 20),                  # 21 ACK marker (active LOW)
          I.act(I.OP_LEVEL, ACK_PIN, 1, 20),
          I.act(I.OP_LEVEL, I.PIN_NONE, 0, U.POST),
          I.act(I.OP_REARM, 0, 1, 20)]                        # 24 loop
    l0 = I.ACT_BASE
    lp = l0 + len(p) * I.ACT_BYTES
    p.append(I.act(I.OP_REARM, 0, 0, 500))
    hs = [I.hdr(U.DM, I.PIN_NONE, 1, D, 0, 2 * D, 3 * D, l0)]
    hs += [I.hdr(n + 2, n + 2, 0, 500, 0, 200, 240, lp) for n in range(1, I.N_LANES)]
    return I.join_image(hs, p)


def pkt(pid, payload, flips=(), seven=False):
    """(wire bits, the bytes the receive pushes, predicted ACK, predicted
    flags (stuff_err, crc_ok)). `flips` are bit indices into the bytes AFTER
    SYNC and PID (data, then CRC), applied after the CRC is computed."""
    sent = [0x80, pid] + list(payload) + U.crc16(payload)
    for f in flips:
        sent[2 + f // 8] ^= 1 << (f % 8)
    wire, where = U.stuff(U.bits_lsb(sent))
    if seven:
        wire[where[0]] = 1
    crc_ok = U.crc16(sent[2:10]) == sent[10:12]
    return wire, sent, (crc_ok and not seven), (int(seven), int(crc_ok))


def base_packets():
    P = U.PAYLOADS
    return [pkt(*P[3]),                        # good
            pkt(*P[1], flips=(13,)),           # one data bit
            pkt(*P[2]),                        # good
            pkt(*P[3], flips=(70,)),           # one CRC bit
            pkt(*P[0], seven=True),            # seven ones, CRC intact
            pkt(*P[1], flips=(5, 40)),         # two data bits
            pkt(*P[0])]                        # good (the 100-bit packet)


def random_packets(n=40, seed=8):
    rng = random.Random(seed)
    out = []
    for k in range(n):
        pay = [rng.getrandbits(8) for _ in range(8)]
        fl = tuple(rng.sample(range(80), rng.randint(1, 3))) if k % 2 else ()
        out.append(pkt(rng.choice((0xC3, 0x4B)), pay, flips=fl))
    return out


def sim(vvp, img, wave, ncyc):
    r = U.run(sim_run.vvp([vvp, "+IMG=%s" % img, "+WAVE=%s" % wave, "+NCYC=%d" % ncyc],
                          images=[img]))
    out = r.stdout + r.stderr
    rx = [int(v) for _c, v, _l in re.findall(r"^RX (\d+) (\d+) (\d+)$", out, re.M)]
    mk = [(int(c), m) for c, m in re.findall(r"^MK (\d+) (\d\d)$", out, re.M)]
    br = [(int(c), int(p), int(b)) for c, p, b in re.findall(r"^BR (\d+) (\d+) (\d+)$", out, re.M)]
    return rx, mk, br, ("END" in out), out[-300:]


def judge(name, packets, rx, mk, br, end, tail):
    if not end:
        return ["%s: no END (%s)" % (name, tail)]
    probs = []
    gold_rx = []
    for wire, sent, _a, _f in packets:
        gold_rx += U.decode(wire)[0]
    if rx != gold_rx:
        i = next((k for k, (a, b) in enumerate(zip(rx, gold_rx)) if a != b), min(len(rx), len(gold_rx)))
        probs.append("%s: %d bytes, golden %d, first difference at byte %d" % (name, len(rx), len(gold_rx), i))
    # active-low pulses from the reset-high state: uo0 low = ACK, uo1 low = NAK
    got = ["ACK" if m == "10" else "NAK" for _c, m in mk if m in ("01", "10")]
    want = ["ACK" if a else "NAK" for _w, _s, a, _f in packets]
    if got != want:
        probs.append("%s: decisions %s, golden %s" % (name, got, want))
    # the flags at each decision: STUFF_ERR at the first branch, CRC_OK at the
    # second (taken only when STUFF_ERR is 0)
    fl = []
    i = 0
    for _w, _s, _a, (se, ok) in packets:
        fl.append((I.VPIN_STUFF_ERR, se))
        if not se:
            fl.append((I.VPIN_CRC_OK, ok))
    seen = [(p, b) for _c, p, b in br]
    if seen != fl:
        k = next((j for j, (a, b) in enumerate(zip(seen, fl)) if a != b), min(len(seen), len(fl)))
        probs.append("%s: branch flags differ at branch %d: got %s, golden %s"
                     % (name, k, seen[k] if k < len(seen) else "-", fl[k] if k < len(fl) else "-"))
    for (c, p, b), (_w, _s, a, (se, ok)) in zip([x for x in br if x[1] == I.VPIN_CRC_OK],
                                                [q for q in packets if not q[3][0]]):
        if b and not a:
            probs.append("%s: CRC_OK = 1 at cycle %d on a CORRUPTED packet" % (name, c))
    return probs


def run_cases(vvp, tmp, tag, pool):
    img = os.path.join(tmp, "usbcrc_main.hex")
    if not os.path.exists(img):
        I.write_image(img, image())
        sim_run.scratch_image(GEN, img)
    cases = [("e%+.3f" % e, base_packets(), e, 8, 40 + int(1000 * e)) for e in U.DRIFTS]
    cases.append(("random40", random_packets(), 0.0, 8, 9))
    jobs = []
    for name, pk, e, E, seed in cases:
        tr, t_end = U.line([(w, s) for w, s, _a, _f in pk], e, E, seed)
        safe = name.replace("+", "p").replace("-", "m").replace(".", "_")
        wv = os.path.join(tmp, "wave_%s_%s.txt" % (tag, safe))
        with open(wv, "w") as fh:
            fh.write("".join("%d %d\n" % x for x in tr))
        jobs.append((name, pk, pool.submit(sim, vvp, img, wv, t_end + 600)))
    return {name: judge(name, pk, *fut.result()) for name, pk, fut in jobs}


MUTANTS = [
    ("M_CRC_ALWAYS_OK", "CRC_OK stuck at 1"),
    ("M_CRC_NO_PRIME", "the CRC not restarted at SOP"),
]


def main() -> int:
    banner("iverilog", "vvp")
    print()
    print("=" * 78)
    print("The USB RX CRC16 and the flags as virtual pins (v2 primitive 3, bundle 4)")
    print("=" * 78)
    probs = []
    pr = I.branch_problems(image())
    if pr:
        probs.append("valid image refused by pe_isa: %s" % pr)
    tmp = tempfile.mkdtemp(prefix="pe_usbcrc_")
    vvp = os.path.join(tmp, "usbcrc.vvp")
    U.build(vvp)
    with ThreadPoolExecutor(max_workers=8) as pool:
        res = run_cases(vvp, tmp, "base", pool)
        print("\n  C1/C2 decisions (ACK iff CRC good and no stuffing error), bytes, flags at each branch")
        for name, p in res.items():
            print("    %-10s %s" % (name, "exact" if not p else "*** " + p[0]))
            probs += p

        print("\n  C3 pe_isa: branching on a virtual pin that is not built")
        for pin, why in ((I.VPIN_READY, "READY (bundle 5)"), (I.PIN_NONE, "PIN_NONE")):
            bad = bytearray(image())
            a = I.ACT_BASE + 16 * I.ACT_BYTES
            bad[a:a + I.ACT_BYTES] = I.act_branch_bit(pin, 1, 21, W)
            st = I.branch_problems(bytes(bad))
            print("    pin %-2d %-18s %s" % (pin, why, "refused" if st else "*** ACCEPTED"))
            if not st:
                probs.append("pe_isa accepted BRANCH_BIT on pin %d" % pin)

        print("\n  C4 must-fires")
        for d, what in MUTANTS:
            mv = os.path.join(tmp, "usbcrc_%s.vvp" % d)
            try:
                U.build(mv, [d])
            except RuntimeError as exc:
                probs.append("%s: %s" % (d, exc))
                continue
            r = run_cases(mv, tmp, d, pool)
            red = [(n, p[0]) for n, p in r.items() if p]
            print("    %-16s %-32s %s" % (d, what, ("RED in %d of %d: %s -- %s" % (
                len(red), len(r), red[0][0], red[0][1][:80])) if red else "*** SURVIVED"))
            if not red:
                probs.append("%s survived" % d)

    print()
    if probs:
        print("  GATE usbcrc: FAILED (%d)" % len(probs))
        for x in probs:
            print("    - %s" % x)
        return 1
    print("  GATE usbcrc: PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
