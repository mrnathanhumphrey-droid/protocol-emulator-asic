#!/usr/bin/env python3
"""The USB RESPONSE BUFFER, READY, and the IN -> DATA -> ACK turnaround
(v2 primitive 3, bundle 5; Wilson 11-08).

THE ONE CLAIM: with one program on the USB lane -- receive a packet's SYNC and
PID; on IN wait out the token's EOP and answer, on ACK clear READY -- the chip,
as a low-speed device on the D-/D+ pair:
  * answers an IN with NAK while READY is clear;
  * once the RP2040 has loaded a packet through tag 3 (byte 0 its length in
    bits, then its line bits), answers the IN with EXACTLY those bits, then
    EOP, starting inside the 80-260-cycle turnaround window;
  * keeps READY set until the host ACKs: with the ACK withheld, the next IN
    gets a BIT-IDENTICAL packet; the ACK clears READY and the next IN is NAKed;
  * refuses (TX-full) any tag-3 write while READY is set -- one landing
    mid-send changes nothing on the wire;
  * and in a program WITHOUT a USB receive, tag 3 is an ordinary TX queue.

THE GOLDEN: every host packet, every handshake's line bits and the loaded
packet are built here (SYNC/PID/payload/CRC16, stuffed, NRZI from J on D-);
the device's packets are predicted bit for bit (D- per bit, D+ its complement,
then SE0 SE0 J), READY's changes and the refusal are predicted, and each
device SOP is measured from the end of the host's EOP.

Bench: test/tb_usbbuf.v. Images built here from pe_isa.
  B1  READY clear: IN -> NAK
  B2  load, IN -> DATA, ACK -> READY clear, IN -> NAK
  B3  retransmit: load, IN -> DATA, no ACK, IN -> the SAME DATA, ACK, IN -> NAK
  B4  a new load pushed mid-send: refused (TX-full), the wire packet exactly the loaded one
  B5  no USB receive in the program: tag 3 feeds SHIFT q = 3 as a queue
  B6  must-fires: M_READY_ALWAYS (B1 sends), M_READY_CLR_ON_SEND (B3's retry
      NAKed), M_BUF_NO_REFUSE (B4's packet overwritten), M_TAG3_ALWAYS_BUF
      (B5's queue starved) each turn the gate red

POSITIVE TOKEN: `GATE usbbuf: PASSED`.
"""

from __future__ import annotations

import os
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

from toolchain import banner, tool       # noqa: E402
import clock                             # noqa: E402
import pe_isa as I                       # noqa: E402
import sim_run                           # noqa: E402
import run_usbrx as U                    # noqa: E402

BENCH = "test/tb_usbbuf.v"
GEN = "run_usbbuf"
DM, DP = 2, 3                 # uio[2] = D-, uio[3] = D+
D = 40
W = I.BR_W_MIN
TA = 100                      # the READY branch's wait: puts SOP inside 80..260
PID_IN, PID_ACK, PID_NAK, PID_DATA1 = 0x69, 0xD2, 0x5A, 0x4B
TURN_LO, TURN_HI = 80, 260    # the device turnaround window, cycles after the host's EOP
J_MAX = 2                     # the budget's dispatch jitter (Wilson 11-08), cycles late
#: STIMULUS: the DATA packet's payload (8 bytes) the RP2040 loads
PAYLOAD = [0x55, 0x53, 0x42, 0x2D, 0x4B, 0x42, 0x44, 0x21]


def nrzi(bits, lvl=1):
    """D- levels, NRZI from J (1): a 0 toggles, a 1 holds"""
    out = []
    for b in bits:
        if b == 0:
            lvl ^= 1
        out.append(lvl)
    return out


def line_bits(byts):
    """stuffed from SYNC's first bit, NRZI from J: the D- level of every bit"""
    return nrzi(U.stuff(U.bits_lsb(byts))[0])


def pack(levels):
    return [sum(levels[8 * k + i] << i for i in range(8) if 8 * k + i < len(levels))
            for k in range((len(levels) + 7) // 8)]


DATA_LINE = line_bits([0x80, PID_DATA1] + PAYLOAD + U.crc16(PAYLOAD))
NAK_LINE = line_bits([0x80, PID_NAK])
LOAD = [len(DATA_LINE)] + pack(DATA_LINE)


def host_packet(byts):
    """[(offset, dm, dp)] from the packet's start: J one bit, the line bits,
    SE0 two bits, J one bit, release; and the offset its EOP ends (J starts)"""
    lv = line_bits(byts)
    tr, prev = [(0, 1, 0)], None
    for k, l in enumerate(lv):
        if l != prev:
            tr.append(((k + 1) * D, l, 1 - l))
            prev = l
    n = len(lv)
    tr += [((n + 1) * D, 0, 0), ((n + 3) * D, 1, 0), ((n + 4) * D, 2, 2)]
    return tr, (n + 3) * D


IN_PKT = host_packet([0x80, PID_IN, 0x00, 0x10])
ACK_PKT = host_packet([0x80, PID_ACK])


def image_usb():
    """the USB lane's whole program (word indices are branch targets)"""
    nak_sync, nak_pid = pack(NAK_LINE)
    p = [I.act(I.OP_ARM, DM, 0, 0),                              # 0  any packet's SOP
         I.act(I.OP_LEVEL, I.PIN_NONE, 0, D // 2),               # 1
         I.act_shiftin_usb(DM, D, 8),                            # 2  SYNC
         I.act_shiftin_usb(DM, D, 8),                            # 3  PID
         I.act_cmp_branch(PID_IN, 12, W),                        # 4  IN  -> 12
         I.act(I.OP_LEVEL, I.PIN_NONE, 0, 20),                   # 5
         I.act_cmp_branch(PID_ACK, 9, W),                        # 6  ACK -> 9
         I.act(I.OP_LEVEL, I.PIN_NONE, 0, U.POST),               # 7  anything else: ignore
         I.act(I.OP_REARM, 0, 1, 20),                            # 8
         I.act_ready_clear(20),                                  # 9  ACK: clear READY
         I.act(I.OP_LEVEL, I.PIN_NONE, 0, U.POST),               # 10
         I.act(I.OP_REARM, 0, 1, 20),                            # 11
         I.act(I.OP_ARM, DM, 0, 0, pinb=DP, mod=1),              # 12 IN: the token's SE0
         I.act(I.OP_ARM, DM, 1, 0),                              # 13 ... then J
         I.act_branch_bit(I.VPIN_READY, 1, 21, TA),              # 14 READY -> DATA
         I.act_shifti(nak_sync, DM, D, pinb=DP),                 # 15 NAK
         I.act_shifti(nak_pid, DM, D, pinb=DP),                  # 16
         I.act_se0(DM, DP, 2 * D),                               # 17 EOP
         I.act_level_pair(DM, DP, 1, D),                         # 18 J
         I.act(I.OP_READBIT, DM, 0, 20, pinb=DP, mod=I.MOD_PAIR),  # 19 release
         I.act(I.OP_REARM, 0, 1, 20),                            # 20
         I.act_send_buf(DM, DP, D),                              # 21 DATA: the buffer
         I.act_se0(DM, DP, 2 * D),                               # 22 EOP
         I.act_level_pair(DM, DP, 1, D),                         # 23 J
         I.act(I.OP_READBIT, DM, 0, 20, pinb=DP, mod=I.MOD_PAIR),  # 24 release
         I.act(I.OP_REARM, 0, 1, 20)]                            # 25
    l0 = I.ACT_BASE
    lp = l0 + len(p) * I.ACT_BYTES
    p.append(I.act(I.OP_REARM, 0, 0, 500))
    hs = [I.hdr(DM, I.PIN_NONE, 1, D, 0, 2 * D, 3 * D, l0)]
    hs += [I.hdr(I.UO0 + n - 1, I.UO0 + n - 1, 1, 500, 0, 200, 240, lp) for n in range(1, I.N_LANES)]
    return I.join_image(hs, p)


#: B5's queue bytes (STIMULUS) and the cycle each is pushed
Q_BYTES = [0xA5, 0x3C, 0x96, 0x0F, 0x81]
Q_FIRST, Q_STEP = 100, 860


def image_queue():
    """no USB receive: lane 0 sends each queue-3 byte on uo_out[0] (one
    self-timed SHIFT per byte), with a 500-cycle pause between bytes"""
    p = [I.act(I.OP_LEVEL, I.PIN_NONE, 0, 500),
         I.act_shift_timed(I.UO0, D, 8, q=3),
         I.act(I.OP_REARM, 0, 1, 20)]
    l0 = I.ACT_BASE
    lp = l0 + len(p) * I.ACT_BYTES
    p.append(I.act(I.OP_REARM, 0, 0, 500))
    hs = [I.hdr(I.UO0, I.PIN_NONE, 1, D, 0, 2 * D, 3 * D, l0)]
    hs += [I.hdr(n + 2, n + 2, 0, 500, 0, 200, 240, lp) for n in range(1, I.N_LANES)]
    return I.join_image(hs, p)


# ---- the scenarios: (host packets, loads, expected device packets, READY changes, TF) ----
def loads_at(t0, byts, step=40):
    return [("A", t0 + k * step, b) for k, b in enumerate(byts)]


SCEN = {
    "B1 nak": ([("A", 800, IN_PKT)], [], ["NAK"], [], False),
    "B2 data+ack": ([("A", 800, IN_PKT), ("A", 6000, IN_PKT), ("R", 120, ACK_PKT), ("H", 1500, IN_PKT)],
                    loads_at(4000, LOAD), ["NAK", "DATA", "NAK"], [1, 0], False),
    "B3 retransmit": ([("A", 800, IN_PKT), ("A", 6000, IN_PKT), ("R", 1500, IN_PKT),
                       ("R", 120, ACK_PKT), ("H", 1500, IN_PKT)],
                      loads_at(4000, LOAD), ["NAK", "DATA", "DATA", "NAK"], [1, 0], False),
    "B4 mid-send": ([("A", 800, IN_PKT), ("A", 6000, IN_PKT), ("R", 120, ACK_PKT), ("H", 1500, IN_PKT)],
                    loads_at(4000, LOAD) + [("S", 400, 24)],   # a new packet's length byte, mid-send
                    ["NAK", "DATA", "NAK"], [1, 0], True),
}


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def build(out, defines=()):
    r = run([tool("iverilog"), "-g2012", "-I", ROOT, "-o", out, "-s", "tb_usbbuf"]
            + ["-D%s" % d for d in defines] + [BENCH] + U.RTL)
    if r.returncode != 0:
        raise RuntimeError("build %s failed: %s" % (out, (r.stdout + r.stderr)[-400:]))


def write_scripts(tmp, tag, host, loads):
    hf = os.path.join(tmp, "host_%s.txt" % tag)
    with open(hf, "w") as fh:
        for mode, t, (tr, _eop) in host:
            fh.write("P %s %d %d\n" % (mode, t, len(tr)))
            fh.write("".join("%d %d %d\n" % x for x in tr))
    lf = os.path.join(tmp, "load_%s.txt" % tag)
    with open(lf, "w") as fh:
        fh.write("".join("L %s %d %d\n" % x for x in loads))
    return hf, lf


#: ⭐ THE COVERAGE SWEEP'S tb_usbbuf ARMS (Wilson 11-13): the gate's own four buffer
#: scenarios (30,000 cycles each, as run_all) and B5's queue image, so the response
#: buffer's send path is reached. Reach only; judged here.
COV_DIR = "probe_cov_usbbuf"


def coverage_arms():
    """[(label, plusargs)] for test/benchset.py's tb_usbbuf; scripts + images under COV_DIR."""
    d = os.path.join(ROOT, COV_DIR)
    os.makedirs(d, exist_ok=True)
    I.write_image(os.path.join(d, "usb.hex"), image_usb())
    I.write_image(os.path.join(d, "queue.hex"), image_queue())
    rel = lambda p: COV_DIR + "/" + os.path.basename(p)
    arms = []
    for name, (host, loads, _pk, _rd, _tf) in SCEN.items():
        tag = name.split()[0]
        hf, lf = write_scripts(d, tag, host, loads)
        arms.append((tag, ["+IMG=%s/usb.hex" % COV_DIR, "+HOST=" + rel(hf), "+LOAD=" + rel(lf), "+NCYC=30000"]))
    qf, ql = write_scripts(d, "B5", [], [("A", Q_FIRST + k * Q_STEP, b) for k, b in enumerate(Q_BYTES)])
    arms.append(("B5", ["+IMG=%s/queue.hex" % COV_DIR, "+HOST=" + rel(qf), "+LOAD=" + rel(ql),
                        "+NCYC=%d" % (Q_FIRST + len(Q_BYTES) * Q_STEP + 400)]))
    return arms


def sim(vvp, img, hf, lf, ncyc):
    r = run(sim_run.vvp([vvp, "+IMG=%s" % img, "+HOST=%s" % hf, "+LOAD=%s" % lf,
                         "+NCYC=%d" % ncyc], images=[img]))
    out = r.stdout + r.stderr
    g = lambda pat: re.findall(pat, out, re.M)
    return {
        "tx": [(int(c), oe, o) for c, oe, o in g(r"^TX (\d+) (\d\d) (\d\d)$")],
        "hp": [(int(c), int(k)) for c, k in g(r"^HP (\d+) (\d+)$")],
        "rd": [int(v) for _c, v in g(r"^RD (\d+) (\d)$")],
        "tf": [int(c) for c in g(r"^TF (\d+)$")],
        "ub": [int(b) for _c, b in g(r"^UB (\d+) (\d)$")],
        "uo": [int(v) for _c, v in g(r"^UO (\d+) (\d)$")],
        "end": "END" in out, "tail": out[-300:]}


def device_packets(tx):
    """[(start cycle, [(dm, dp) per bit], edge offsets)] for each stretch the
    device drives D-, sampled mid-bit from its first edge"""
    out, cur = [], None
    st = {"oe": "00", "o": "11"}
    for c, oe, o in tx:
        if oe[1] == "1" and st["oe"][1] != "1":
            cur = (c, [(c, o)])
        elif cur is not None and oe[1] == "1":
            cur[1].append((c, o))
        if oe[1] != "1" and st["oe"][1] == "1" and cur is not None:
            t0, ev = cur
            bits, j = [], 0
            for k in range((c - t0) // D):
                t = t0 + k * D + D // 2
                while j + 1 < len(ev) and ev[j + 1][0] <= t:
                    j += 1
                o2 = ev[j][1]
                bits.append((int(o2[1]), int(o2[0])))
            offs = [e[0] - t0 for e in ev]
            out.append((t0, bits, offs))
            cur = None
        st = {"oe": oe, "o": o}
    return out


def expect_bits(kind):
    lv = DATA_LINE if kind == "DATA" else NAK_LINE
    return [(l, 1 - l) for l in lv] + [(0, 0), (0, 0), (1, 0)]


def judge(name, res, host, exp_pk, exp_rd, exp_tf):
    if not res["end"]:
        return ["%s: no END (%s)" % (name, res["tail"])], []
    probs, turns, jits = [], [], []
    pk = device_packets(res["tx"])
    kinds = []
    for t0, bits, offs in pk:
        k = "DATA" if bits[:len(DATA_LINE)] == expect_bits("DATA")[:len(DATA_LINE)] else (
            "NAK" if bits[:len(NAK_LINE)] == expect_bits("NAK")[:len(NAK_LINE)] else "?")
        kinds.append(k)
        if k != "?" and bits != expect_bits(k):
            probs.append("%s: the %s packet at %d is not bit-exact (%d bits, golden %d)"
                         % (name, k, t0, len(bits), len(expect_bits(k))))
        # every edge ON the bit grid or up to J = 2 cycles LATE (a dispatch waits
        # behind at most one other lane's service under the deadline rule), never early
        late = [o % D for o in offs]
        if any(x > J_MAX for x in late):
            probs.append("%s: a device edge %s cycles off the bit grid in the packet at %d (J = %d)"
                         % (name, [x for x in late if x > J_MAX][:4], t0, J_MAX))
        jits.append(max(late) if late else 0)
    if kinds != exp_pk:
        probs.append("%s: device packets %s, golden %s" % (name, kinds, exp_pk))
    # SOP against the host's EOP (every device packet answers the host packet before it)
    for t0, _b, _o in pk:
        prev = [(c, k) for c, k in res["hp"] if c < t0]
        if prev:
            c, k = prev[-1]
            eop_end = c + host[k][2][1]
            turns.append(t0 - eop_end)
    bad = [x for x in turns if not TURN_LO <= x <= TURN_HI]
    if bad:
        probs.append("%s: SOP %s cycles after the host's EOP, outside %d..%d" % (name, bad, TURN_LO, TURN_HI))
    if res["rd"] != exp_rd:
        probs.append("%s: READY changes %s, golden %s" % (name, res["rd"], exp_rd))
    if bool(res["tf"]) != exp_tf:
        probs.append("%s: TX-full refusal %s, golden %s" % (name, bool(res["tf"]), exp_tf))
    return probs, turns + [("J", j) for j in jits]


def run_all(vvp, tmp, tag, pool):
    img = os.path.join(tmp, "usbbuf_usb.hex")
    if not os.path.exists(img):
        I.write_image(img, image_usb())
        sim_run.scratch_image(GEN, img)
    qimg = os.path.join(tmp, "usbbuf_queue.hex")
    if not os.path.exists(qimg):
        I.write_image(qimg, image_queue())
        sim_run.scratch_image(GEN, qimg)
    jobs = {}
    for name, (host, loads, pk, rd, tf) in SCEN.items():
        hf, lf = write_scripts(tmp, "%s_%s" % (tag, name.split()[0]), host, loads)
        jobs[name] = (host, pk, rd, tf, pool.submit(sim, vvp, img, hf, lf, 30000))
    qf, ql = write_scripts(tmp, "%s_B5" % tag, [], [("A", Q_FIRST + k * Q_STEP, b) for k, b in enumerate(Q_BYTES)])
    qjob = pool.submit(sim, vvp, qimg, qf, ql, Q_FIRST + len(Q_BYTES) * Q_STEP + 400)
    res, turns = {}, []
    for name, (host, pk, rd, tf, fut) in jobs.items():
        res[name], t = judge(name, fut.result(), host, pk, rd, tf)
        turns += t
    q = qjob.result()
    want = [(b >> i) & 1 for b in Q_BYTES for i in range(8)]
    qp = []
    if not q["end"]:
        qp.append("B5: no END")
    if q["ub"][:len(want)] != want:
        qp.append("B5: queue-3 bits %s..., golden %s..." % (q["ub"][:16], want[:16]))
    if q["uo"]:
        qp.append("B5: the USB lane went live in a program with no USB receive")
    res["B5 tag-3 queue"] = qp
    return res, turns


MUTANTS = [
    ("M_READY_ALWAYS", "READY reads set"),
    ("M_READY_CLR_ON_SEND", "READY cleared by the send"),
    ("M_BUF_NO_REFUSE", "a write while READY lands"),
    ("M_TAG3_ALWAYS_BUF", "tag 3 never a queue"),
]


def main() -> int:
    banner("iverilog", "vvp")
    print()
    print("=" * 78)
    print("The USB response buffer, READY, IN -> DATA -> ACK (v2 primitive 3, bundle 5)")
    print("=" * 78)
    probs = []
    print("  the loaded DATA packet: %d line bits (%d bytes + the length byte)" % (len(DATA_LINE), len(LOAD) - 1))
    if len(DATA_LINE) > I.USB_BUF_MAX_BITS:
        probs.append("the DATA packet is %d bits > %d" % (len(DATA_LINE), I.USB_BUF_MAX_BITS))
    for nm, im in (("usb", image_usb()), ("queue", image_queue())):
        pr = I.branch_problems(im)
        if pr:
            probs.append("valid %s image refused by pe_isa: %s" % (nm, pr))
    tmp = tempfile.mkdtemp(prefix="pe_usbbuf_")
    vvp = os.path.join(tmp, "usbbuf.vvp")
    build(vvp)
    with ThreadPoolExecutor(max_workers=6) as pool:
        res, turns = run_all(vvp, tmp, "base", pool)
        print("\n  B1-B5")
        for name, p in res.items():
            print("    %-16s %s" % (name, "exact" if not p else "*** " + p[0]))
            probs += p
        sops = sorted(set(t for t in turns if not isinstance(t, tuple)))
        jmax = max([j for tag, j in [t for t in turns if isinstance(t, tuple)]] or [0])
        print("    device SOP after the host's EOP: %s cycles (window %d..%d)" % (sops, TURN_LO, TURN_HI))
        print("    MEASURED: worst device edge lateness off the bit grid: %d cycle(s) (J = %d)" % (jmax, J_MAX))
        # ⭐ bundle 6 (step 7a M16): the measured driver term in ns against
        # USB 2.0 Table 7-10's TUDJ1 / TUDJ2 (jitter INCLUDING frequency
        # tolerance), the rest charged to the clock source over the longest
        # runs Table 7-5 budgets (7 / 14 bits), against the declared source
        f = clock.target_hz("chip")
        jt = clock.ns(jmax, f)
        tb = 1e9 / clock.USB_LS_RATE
        q = float(clock.usb_quant_err(f))
        src = clock.SOURCE_PPM["chip"] / 1e6
        nxt = jt + 7 * tb * (q + src)
        pair = jt + 14 * tb * (q + src)
        print("    M16 MEASURED driver term %.1f ns (%d cyc); with the declared %d ppm source: next "
              "transition %.1f of %d ns, paired %.1f of %d ns" % (jt, jmax, clock.SOURCE_PPM["chip"],
                                                                   nxt, clock.USB_TUDJ1_NS, pair, clock.USB_TUDJ2_NS))
        if nxt > clock.USB_TUDJ1_NS or pair > clock.USB_TUDJ2_NS:
            probs.append("M16: device TX jitter %.1f / %.1f ns over TUDJ1 / TUDJ2" % (nxt, pair))
        print("\n  B6 must-fires")
        for d, what in MUTANTS:
            mv = os.path.join(tmp, "usbbuf_%s.vvp" % d)
            try:
                build(mv, [d])
            except RuntimeError as exc:
                probs.append("%s: %s" % (d, exc))
                continue
            r, _t = run_all(mv, tmp, d, pool)
            red = [(n, p[0]) for n, p in r.items() if p]
            print("    %-20s %-28s %s" % (d, what, ("RED in %d of %d: %s -- %s" % (
                len(red), len(r), red[0][0], red[0][1][:70])) if red else "*** SURVIVED"))
            if not red:
                probs.append("%s survived" % d)
    print()
    if probs:
        print("  GATE usbbuf: FAILED (%d)" % len(probs))
        for x in probs:
            print("    - %s" % x)
        return 1
    print("  GATE usbbuf: PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
