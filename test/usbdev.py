#!/usr/bin/env python3
"""The USB DEVICE's golden, program and bench driver -- shared by
`test/run_usbaddr.py` and `test/run_usbrst.py` (v2 primitive 3, bundle 6;
Wilson 11-09, step 7a). Not a gate itself.

THE GOLDEN is written from the USB 2.0 spec (usb.org usb_20_20240604):
  * packets: SYNC KJKJKJKK = 0x80 LSB first (§8.2), PIDs (Table 8-1), tokens
    ADDR[6:0] ENDP[3:0] CRC5 (§8.4.1), CRC5 G = x^5 + x^2 + 1, register preset
    to ones, the remainder INVERTED and sent MSB first, a good token leaving
    the residual 01100 (§8.3.5.1); CRC16 as run_usbrx's (§8.3.5.2);
    stuffing and NRZI from run_usbrx / run_usbbuf, which built them from §7.1.
  * the CRC5 is checked against the spec's own premises: the residual, and the
    published SETUP-to-address-0 token 2D 00 10.
The device's packets are predicted bit for bit; addresses, READY, the fence
and the reset notice are predicted from the step 7a rules, never from the RTL.

THE PROGRAM (one lane, the USB lane, D- = uio[2], D+ = uio[3]) makes every
decision AFTER a packet ends (Wilson 11-09: a self-timed receive cannot branch
between consecutive bits). Its shape is set by two timing facts:
  * after a SETUP or OUT the host's DATA packet may start 2 bit times after
    the token's EOP, so the receive for it must be ARMED within ~80 cycles:
    the token's PID is decided FIRST (SETUP, then OUT), and its ADDR_OK is
    checked after the DATA packet (ADDR_OK is the most recent TOKEN's verdict);
  * a branch's successor may not be a branch, so decisions are spaced by a
    20-cycle no-op.
An IN is answered on the lane timestamp re-anchored at the token's last bit
(no J wait: the EOP has ended before the IN is decided), ~185 cycles after the
nominal EOP end -- inside 80..260 for any EOP width Table 7-10 allows.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

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
import run_usbbuf as B                   # noqa: E402

BENCH = "test/tb_usbdev.v"
DM, DP = 2, 3
D = 40
W = I.BR_W_MIN
SPC = 20                      # the no-op between two decisions (d >= 20)
TA = 33                       # the READY branch's wait
TURN_LO, TURN_HI = 80, 260
J_MAX = 2
PID_OUT, PID_IN, PID_SETUP = 0xE1, 0x69, 0x2D
PID_DATA0, PID_DATA1, PID_ACK, PID_NAK = 0xC3, 0x4B, 0xD2, 0x5A


# ---- the golden ------------------------------------------------------------
def crc5_reg(bits):
    """§8.3.5.1's register: preset to ones, shifted toward x^4, G = 00101"""
    c = 0x1F
    for b in bits:
        fb = ((c >> 4) & 1) ^ b
        c = (c << 1) & 0x1F
        if fb:
            c ^= 0x05
    return c


def token_bits(addr, ep, flip=None):
    """the 16 bits after the PID, wire order: ADDR, ENDP (LSB first), then
    the inverted CRC5 MSB first. `flip`: invert that bit index (0..15)"""
    bits = [(addr >> i) & 1 for i in range(7)] + [(ep >> i) & 1 for i in range(4)]
    crc = crc5_reg(bits) ^ 0x1F
    bits += [(crc >> (4 - i)) & 1 for i in range(5)]
    if flip is not None:
        bits[flip] ^= 1
    return bits


def token(pid, addr, ep=0, flip=None, sync=0x80):
    b = token_bits(addr, ep, flip)
    return [sync, pid, sum(b[i] << i for i in range(8)), sum(b[8 + i] << i for i in range(8))]


def data(pid, payload, sync=0x80):
    return [sync, pid] + list(payload) + U.crc16(payload)


def premise_problems():
    out = []
    if token(PID_SETUP, 0)[1:] != [PID_SETUP, 0x00, 0x10]:
        out.append("golden: SETUP to address 0 is %s, the spec's 2D 00 10" % token(PID_SETUP, 0)[1:])
    for a, e in ((0, 0), (5, 0), (5, 1), (0x7F, 0xF), (0x2A, 0x5)):
        if crc5_reg(token_bits(a, e)) != 0b01100:
            out.append("golden: token (%d, %d) leaves residual %s, not 01100" % (
                a, e, bin(crc5_reg(token_bits(a, e)))))
    return out


#: the device's own packets (line bits, D- per bit)
NAK_LINE = B.line_bits([0x80, PID_NAK])
ACK_LINE = B.line_bits([0x80, PID_ACK])
ZLP_LINE = B.line_bits(data(PID_DATA1, []))
DATA_LINE = B.DATA_LINE                          # DATA1 + bundle 5's 8-byte payload
LINES = {"NAK": NAK_LINE, "ACK": ACK_LINE, "ZLP": ZLP_LINE, "DATA": DATA_LINE}


def load(line, ep=0):
    """the RP2040's tag-3 buffer load for one packet"""
    return [(I.buf_len_byte(len(line), ep), I.USB_BUF_Q)] + [(b, I.USB_BUF_Q) for b in B.pack(line)]


def ctl(byte):
    return [(byte, I.USB_CTL_Q)]


def pkt(byts):
    return B.host_packet(byts)


def se0(n, j=True):
    """the host holds SE0 for n cycles, then J for a bit, then releases (a
    keep-alive EOP or a bus reset). The 'EOP end' is the SE0 -> J edge."""
    tr = [(0, 0, 0)]
    if j:
        tr += [(n, 1, 0), (n + D, 2, 2)]
    else:
        tr += [(n, 2, 2)]
    return tr, n


def cut_then_reset(byts, nbits, n_se0):
    """a packet cut after `nbits` line bits by a bus reset's SE0"""
    lv = B.line_bits(byts)[:nbits]
    tr, prev = [(0, 1, 0)], None
    for k, l in enumerate(lv):
        if l != prev:
            tr.append(((k + 1) * D, l, 1 - l))
            prev = l
    t = (len(lv) + 1) * D
    tr += [(t, 0, 0), (t + n_se0, 1, 0), (t + n_se0 + D, 2, 2)]
    return tr, t + n_se0


# ---- the program -----------------------------------------------------------
def _assemble(spec):
    """spec: [(label or None, fn(L) -> bytes)] -> [bytes], labels resolved"""
    L = {}
    for i, (lab, _f) in enumerate(spec):
        if lab:
            L[lab] = i
    return [f(L) for _lab, f in spec]


def device_program(variant=None):
    """the USB lane's program. `variant`: a PROGRAM must-fire --
    'M_SYNC_ABORT_REARM' (the unexpected-PID abort re-arms at once, without
    waiting for the packet's SE0) or 'M_PID_ANY' (a PID that is not SETUP / OUT
    / IN is taken as a SETUP)."""
    nak_s, nak_p = B.pack(NAK_LINE)
    ack_s, ack_p = B.pack(ACK_LINE)
    rx = lambda crc=False: (lambda L: I.act_shiftin_usb(DP, D, 8, crc=crc))
    nop = lambda n: (lambda L: I.act(I.OP_LEVEL, I.PIN_NONE, 0, n))
    top = lambda L: I.act(I.OP_REARM, 0, 1, 20)
    arm_sop = lambda L: I.act(I.OP_ARM, DP, 1, 0)           # D+ rising: a packet's first K
    arm_se0 = lambda L: I.act_arm2(DM, DP, 0, 0)            # the packet's EOP
    arm_j = lambda L: I.act(I.OP_ARM, DM, 1, 0)             # ... and the J after it
    cmp_pid = lambda pid, tgt: (lambda L: I.act_cmp_branch(pid, L[tgt], W, pid=True))
    bit = lambda pin, lvl, tgt, w=W: (lambda L: I.act_branch_bit(pin, lvl, L[tgt], w))
    send = lambda b: (lambda L: I.act_shifti(b, DM, D, pinb=DP))
    eop = [(None, lambda L: I.act_se0(DM, DP, 2 * D)),
           (None, lambda L: I.act_level_pair(DM, DP, 1, D)),
           (None, lambda L: I.act(I.OP_READBIT, DM, 0, 20, pinb=DP, mod=I.MOD_PAIR))]
    if variant == "M_SYNC_ABORT_REARM":
        unx = [("UNX", nop(SPC)), (None, top)]
    elif variant == "M_PID_ANY":
        unx = [("UNX", nop(SPC)), (None, bit(I.UO0, 0, "SET")), (None, top)]
    else:
        unx = [("UNX", arm_se0), (None, arm_j), (None, top)]
    # the token head: wait for a packet, read it as a token (4 bytes), decide on its PID
    head = lambda: ([(None, arm_sop), (None, nop(D // 2))] + [(None, rx())] * 4 +
                    [(None, cmp_pid(PID_SETUP, "SET")), (None, nop(SPC)),
                     (None, cmp_pid(PID_OUT, "OUT")), (None, nop(SPC)),
                     (None, cmp_pid(PID_IN, "IN"))] + [(None, f) for _l, f in unx])
    # ⛔⛔ AFTER OUR ACK / NAK, THE HOST'S NEXT PACKET MAY START 2 BIT TIMES AFTER OUR
    # EOP (TIPD, §7.1.18.1; agent 2's deadline: the packet ARM retires <= 78 cycles
    # after the SE0 -> J edge). Looping back through REARM to TOP's ARM cost
    # J 40 + release 20 + REARM 20 = 80 (measured 80 / 81). Each handshake tail
    # therefore carries its OWN copy of the token head, so the ARM follows the
    # release directly (40 + 20 = 60), as the DATA tail's ACK wait already did.
    # A branch into TOP would cost W >= BR_W_MIN (33) and move the first sample.
    spec = (
        # TOP: any packet, received as a token (4 bytes); decide after it
        [("TOP", arm_sop), (None, nop(D // 2))] + [(None, rx())] * 4 +
        [(None, cmp_pid(PID_SETUP, "SET")), (None, nop(SPC)),
         (None, cmp_pid(PID_OUT, "OUT")), (None, nop(SPC)),
         (None, cmp_pid(PID_IN, "IN"))] + unx +
        # SETUP: its DATA0 (8 bytes + CRC16), then DATA0? ADDR_OK? CRC_OK? -> ACK
        [("SET", arm_sop), (None, nop(D // 2)), (None, rx()), (None, rx())] +
        [(None, rx(True))] * 10 +
        [(None, arm_se0), (None, arm_j), (None, cmp_pid(PID_DATA0, "DOK")), (None, top)] +
        # OUT: a zero-length DATA0/1 (step 7a; SET_REPORT data is step 7b)
        [("OUT", arm_sop), (None, nop(D // 2)), (None, rx()), (None, rx()),
         (None, rx(True)), (None, rx(True)),
         (None, arm_se0), (None, arm_j), (None, cmp_pid(PID_DATA1, "DOK")), (None, nop(SPC)),
         (None, cmp_pid(PID_DATA0, "DOK")), (None, top)] +
        # a DATA packet's verdict: the token's ADDR_OK, then CRC_OK -> ACK
        [("DOK", nop(SPC)), (None, bit(I.VPIN_ADDR_OK, 0, "RTOP")), (None, nop(SPC)),
         (None, bit(I.VPIN_CRC_OK, 1, "ACK")), (None, top)] +
        [("ACK", send(ack_s)), (None, send(ack_p))] + eop + head() +
        # IN: ADDR_OK, READY -> the buffer, else NAK
        [("IN", nop(SPC)), (None, bit(I.VPIN_ADDR_OK, 0, "RTOP")), (None, nop(SPC)),
         (None, bit(I.VPIN_READY, 1, "DS", TA)),
         (None, send(nak_s)), (None, send(nak_p))] + eop + head() +
        [("DS", lambda L: I.act_send_buf(DM, DP, D))] + eop +
        # after our DATA: the host's handshake (2 bytes); ACK clears READY
        [(None, arm_sop), (None, nop(D // 2)), (None, rx()), (None, rx()),
         (None, cmp_pid(PID_ACK, "EAK")), (None, arm_se0), (None, arm_j), (None, top),
         ("EAK", arm_se0), (None, arm_j), (None, lambda L: I.act_ready_clear(20)), (None, top),
         ("RTOP", top)])
    return _assemble(spec)


def image(variant=None, prog=None):
    p = device_program(variant) if prog is None else prog
    l0 = I.ACT_BASE
    lp = l0 + len(p) * I.ACT_BYTES
    p = p + [I.act(I.OP_REARM, 0, 0, 500)]
    hs = [I.hdr(DM, I.PIN_NONE, 1, D, 0, 2 * D, 3 * D, l0)]
    hs += [I.hdr(I.UO0 + n - 1, I.UO0 + n - 1, 1, 500, 0, 200, 240, lp) for n in range(1, I.N_LANES)]
    return I.join_image(hs, p)


def image_nousb():
    """Wilson 11-09 choice 3: lane 0 names the pair in an SE0 wait but never
    receives USB -- so the USB lane is never live"""
    p = [I.act_arm2(DM, DP, 0, 0), I.act(I.OP_LEVEL, I.PIN_NONE, 0, 200), I.act(I.OP_REARM, 0, 1, 20)]
    l0 = I.ACT_BASE
    lp = l0 + len(p) * I.ACT_BYTES
    p.append(I.act(I.OP_REARM, 0, 0, 500))
    hs = [I.hdr(DM, I.PIN_NONE, 1, D, 0, 2 * D, 3 * D, l0)]
    hs += [I.hdr(I.UO0 + n - 1, I.UO0 + n - 1, 1, 500, 0, 200, 240, lp) for n in range(1, I.N_LANES)]
    return I.join_image(hs, p)


def image_q2():
    """the must-fail image: the device program plus a lane drawing queue 2"""
    p = device_program()
    l0 = I.ACT_BASE
    lp = l0 + len(p) * I.ACT_BYTES
    p = p + [I.act_shift_timed(I.UO1, D, 8, q=I.USB_CTL_Q), I.act(I.OP_REARM, 0, 1, 500)]
    hs = [I.hdr(DM, I.PIN_NONE, 1, D, 0, 2 * D, 3 * D, l0)]
    hs += [I.hdr(I.UO0 + n - 1, I.UO0 + n - 1, 1, 500, 0, 200, 240, lp) for n in range(1, I.N_LANES)]
    return I.join_image(hs, p)


# ---- the bench -------------------------------------------------------------
def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


_BANNER = []


def build(out, defines=()):
    if not _BANNER:                   # the log names the binaries this module runs
        banner("iverilog", "vvp")
        _BANNER.append(1)
    r = run([tool("iverilog"), "-g2012", "-I", ROOT, "-o", out, "-s", "tb_usbdev"]
            + ["-D%s" % d for d in defines] + [BENCH] + U.RTL)
    if r.returncode != 0:
        raise RuntimeError("build %s failed: %s" % (out, (r.stdout + r.stderr)[-600:]))


def write_scripts(tmp, tag, host, loads):
    hf = os.path.join(tmp, "host_%s.txt" % tag)
    with open(hf, "w") as fh:
        for mode, t, (tr, _eop) in host:
            fh.write("P %s %d %d\n" % (mode, t, len(tr)))
            fh.write("".join("%d %d %d\n" % x for x in tr))
    lf = os.path.join(tmp, "load_%s.txt" % tag)
    with open(lf, "w") as fh:
        fh.write("".join("L %s %d %d %d\n" % x for x in loads))
    return hf, lf


def sim(vvp, img, hf, lf, ncyc, w0=0, w1=0):
    r = run(sim_run.vvp([vvp, "+IMG=%s" % img, "+HOST=%s" % hf, "+LOAD=%s" % lf,
                         "+NCYC=%d" % ncyc, "+W0=%d" % w0, "+W1=%d" % w1], images=[img]))
    out = r.stdout + r.stderr
    g = lambda pat: re.findall(pat, out, re.M)
    n0 = g(r"^N0 (\d+)$")
    return {
        "tx": [(int(c), oe, o) for c, oe, o in g(r"^TX (\d+) (\d\d) (\d\d)$")],
        "hp": [(int(c), int(k)) for c, k in g(r"^HP (\d+) (\d+)$")],
        "lp": [(int(c), int(t), int(b)) for c, t, b in g(r"^LP (\d+) (\d+) (\d+)$")],
        "rd": [int(v) for _c, v in g(r"^RD (\d+) (\d)$")],
        "tf": [int(c) for c in g(r"^TF (\d+)$")],
        "ad": [int(v) for _c, v in g(r"^AD (\d+) (\d+)$")],
        "pv": [(int(p), int(a)) for _c, p, a in g(r"^PV (\d+) (\d) (\d+)$")],
        "fe": [int(v) for _c, v in g(r"^FE (\d+) (\d)$")],
        "br": [int(c) for c in g(r"^BR (\d+)$")],
        "rn": [int(c) for c in g(r"^RN (\d+)$")],
        "sv": [(int(c), h) for c, h in g(r"^SV (\d+) ([0-9a-fx]+)$")],
        "af": [int(c) for c in g(r"^AF (\d+)$")],
        "n0": int(n0[0]) if n0 else -1,
        "end": "END" in out, "tail": out[-300:]}


def device_packets(tx):
    """[(start, [(dm, dp) per bit], edge offsets)] per device drive, sampled
    mid-bit. As run_usbbuf's, but the bit count is ROUNDED: the SOP edge may
    be the one dispatched late (J), which must not cost the packet a bit."""
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
            for k in range((c - t0 + D // 2) // D):
                t = t0 + k * D + D // 2
                while j + 1 < len(ev) and ev[j + 1][0] <= t:
                    j += 1
                o2 = ev[j][1]
                bits.append((int(o2[1]), int(o2[0])))
            out.append((t0, bits, [e[0] - t0 for e in ev]))
            cur = None
        st = {"oe": oe, "o": o}
    return out


def expect_bits(kind):
    return [(l, 1 - l) for l in LINES[kind]] + [(0, 0), (0, 0), (1, 0)]


def classify(bits):
    for k in ("DATA", "ZLP", "ACK", "NAK"):
        n = len(LINES[k])
        if bits[:n] == expect_bits(k)[:n]:
            return k
    return "?"


def judge(name, res, host, exp):
    """exp: {"pk": [kinds], "ad": [...], "rd": [...]|None, "tf": bool|None,
    "br": n, "rn": n, "fe": [...]|None, "pv": [...]|None}. -> (problems, sops, jits)"""
    if not res["end"]:
        return ["%s: no END (%s)" % (name, res["tail"])], [], []
    probs, sops, jits = [], [], []
    pk = device_packets(res["tx"])
    kinds = []
    for t0, bits, offs in pk:
        k = classify(bits)
        # WHICH host packet it answers: the last one to start before it
        prev_k = [kk for c, kk in res["hp"] if c < t0]
        kinds.append((k, prev_k[-1] if prev_k else None))
        if k != "?" and bits != expect_bits(k):
            probs.append("%s: the %s packet at %d is not bit-exact (%d bits, golden %d)"
                         % (name, k, t0, len(bits), len(expect_bits(k))))
        # edge positions on the bit grid, as signed residues: the SOP edge
        # itself may be the late one, so the claim is the SPREAD (<= J)
        res_ = [((o % D) + D // 2) % D - D // 2 for o in offs]
        spread = (max(res_) - min(res_)) if res_ else 0
        if spread > J_MAX:
            probs.append("%s: device edges spread %d cycles on the bit grid at %d (J = %d): %s"
                         % (name, spread, t0, J_MAX, sorted(set(res_))))
        jits.append(spread)
        prev = [(c, kk) for c, kk in res["hp"] if c < t0]
        if prev:
            c, kk = prev[-1]
            sops.append(t0 - (c + host[kk][2][1]))
    if kinds != exp["pk"]:
        probs.append("%s: device packets %s, golden %s" % (name, kinds, exp["pk"]))
    bad = [x for x in sops if not TURN_LO <= x <= TURN_HI]
    if bad:
        probs.append("%s: SOP %s cycles after the host's EOP, outside %d..%d" % (name, bad, TURN_LO, TURN_HI))
    for key in ("ad", "rd", "fe", "pv"):
        if exp.get(key) is not None and res[key] != exp[key]:
            probs.append("%s: %s changes %s, golden %s" % (name, key.upper(), res[key], exp[key]))
    if exp.get("tf") is not None and bool(res["tf"]) != exp["tf"]:
        probs.append("%s: TX-full refusal %s, golden %s" % (name, bool(res["tf"]), exp["tf"]))
    for key in ("br", "rn"):
        if len(res[key]) != exp.get(key, 0):
            probs.append("%s: %d %s, golden %d" % (name, len(res[key]),
                                                   {"br": "bus resets", "rn": "reset notices"}[key],
                                                   exp.get(key, 0)))
    return probs, sops, jits
