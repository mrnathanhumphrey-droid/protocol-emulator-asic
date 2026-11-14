#!/usr/bin/env python3
"""The USB DEVICE ADDRESS, the token check and the decisions after a packet
(v2 primitive 3, bundle 6; Wilson 11-09, step 7a §3 / §4, additions B-D).

THE CLAIMS, on one device program (test/usbdev.py) against a host on D-/D+:
  * SET_ADDRESS: the pending address (TX tag 2, `1aaaaaaa`) does not move the
    device until the status stage completes; meanwhile address 0 is answered
    and a THIRD address is not (ADDR_OK accepts exactly {current, pending});
  * the commit is in HARDWARE: on the ACK that clears READY (trigger 1), or on
    a CRC5-valid IN/OUT/SETUP token to the pending address (trigger 2, the
    lost-ACK case), which also clears READY so the stale ZLP never goes out;
  * READY is per endpoint: an EP1 IN never receives an EP0 response;
  * a token whose CRC5 fails -- in any bit, the last included -- is ignored;
  * a bad SYNC, a DATA packet where a token belongs, an OUT to another device
    and its DATA: no reply, and the next packet is answered;
  * a DATA packet shaped like a token to the pending address commits nothing;
  * every reply starts 80..260 cycles after the host's EOP (M19: worst reported).

THE GOLDEN: test/usbdev.py (USB 2.0 §7.1, §8). Bench: test/tb_usbdev.v.
  A7   pending window: ADDR 0 answered, ADDR 6 ignored
  A8   after the status ACK: commit, ADDR 0 ignored
  A9   after the commit: SETUP to 5 ACKed
  A10  lost ZLP (no ACK): the retry gets the ZLP again; no commit until the ACK
  A10b lost ACK (corrupted): the next SETUP to 5 commits in hardware, ACKed
  A10c ACK absent: the next SETUP to 5 lands in the handshake wait and is lost;
       the host's retry commits and is ACKed (the step 2 ARM timeout closes this)
  A11  EP1 IN while the buffer holds EP0: NAK, buffer kept; EP0 IN: the data
  A12  CRC5 bit flipped (middle): ignored      A12b  the LAST CRC5 bit: ignored
  A13  bad SYNC on a long packet: no reply, next IN answered
  A13b OUT to 7 + its DATA0: no reply; next SETUP ACKed
  A13c a DATA0 with no token: no reply; next SETUP ACKed
  A13d a DATA0 shaped like a token to the pending address: no commit
  Q2   pe_isa refuses a USB image drawing queue 2 (and accepts the device's)
  must-fires: M_ADDR_EARLY M_ADDR_NOCHECK M_ADDR_ACK_ONLY M_EP_NOCHECK
     M_CRC5_OK M_ADDR_OK_EARLY M_COMMIT_ON_DATA M_CTL_AS_QUEUE (RTL), and
     M_SYNC_ABORT_REARM M_PID_ANY (program) -- each red in its target scenario

POSITIVE TOKEN: `GATE usbaddr: PASSED`.
"""

from __future__ import annotations

import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from toolchain import banner             # noqa: E402
import pe_isa as I                       # noqa: E402
import sim_run                           # noqa: E402
import usbdev as V                       # noqa: E402
import clock                             # noqa: E402

GEN = "run_usbaddr"
T = V.token
P = V.pkt
S, IN, OUT = V.PID_SETUP, V.PID_IN, V.PID_OUT
#: STIMULUS: SET_ADDRESS(5) and GET_DESCRIPTOR(device) setup data
SETADDR5 = [0x00, 0x05, 0x05, 0x00, 0x00, 0x00, 0x00, 0x00]
GETDESC = [0x80, 0x06, 0x00, 0x01, 0x00, 0x00, 0x12, 0x00]
D0 = lambda pay: P(V.data(V.PID_DATA0, pay))
ACKP = P([0x80, V.PID_ACK])
BADACK = P([0x80, 0xD3])                   # the ACK with its check field broken


def at(t0, items, step=60):
    return [("A", t0 + k * step, b, tag) for k, (b, tag) in enumerate(items)]


# the SET_ADDRESS(5) exchange up to the ZLP: SETUP + DATA0 (ACKed); the RP2040
# writes the pending address, then loads the ZLP; an IN to 0 takes it
SA_HOST = [("A", 800, P(T(S, 0))), ("H", 0, D0(SETADDR5))]


def glitch(pk, before_eop, n):
    """`pk` with an n-cycle SE0 planted on a quiet stretch of its data, about
    `before_eop` cycles before its EOP: a transition-SE0 glitch (TLST-class)."""
    tr, end = pk
    eop = tr[-3][0]
    lev = None
    for k in range(len(tr) - 3):
        t0 = tr[k][0]
        nxt = tr[k + 1][0]
        if t0 >= eop - before_eop and nxt - t0 > n + 10:
            lev = tr[k]
            break
    assert lev is not None, "no quiet stretch for the glitch"
    at = lev[0] + 5
    k = tr.index(lev)
    return tr[:k + 1] + [(at, 0, 0), (at + n, lev[1], lev[2])] + tr[k + 1:], end


def short_eop(pk, n):
    """`pk` with its EOP's SE0 cut to n cycles (the shortest a receiver must
    honour is TLEOPR, 670 ns: 39 cycles at the slow band edge)."""
    tr, _end = pk
    eop = tr[-3][0]
    return tr[:-3] + [(eop, 0, 0), (eop + n, 1, 0), (eop + n + V.D, 2, 2)], eop + n
SA_LOAD = at(7000, V.ctl(I.ctl_pending_addr(5)) + V.load(V.ZLP_LINE))
IN0 = P(T(IN, 0))
PEND5 = [(1, 5)]
COMMIT5 = [(1, 5), (0, 5)]

SCEN = {
    # pk: (the device's packet, the index of the host packet it answers)
    "A7 pending": (SA_HOST + [("A", 9000, P(T(IN, 6))), ("H", 1500, IN0)], SA_LOAD,
                   dict(pk=[("ACK", 1), ("ZLP", 3)], ad=[], rd=[1], pv=PEND5), 18000),
    "A8 commit": (SA_HOST + [("A", 11000, IN0), ("R", 120, ACKP), ("H", 1500, IN0)], SA_LOAD,
                  dict(pk=[("ACK", 1), ("ZLP", 2)], ad=[5], rd=[1, 0], pv=COMMIT5), 22000),
    "A9 new addr": (SA_HOST + [("A", 11000, IN0), ("R", 120, ACKP),
                               ("H", 1500, P(T(S, 5))), ("H", 0, D0(GETDESC))], SA_LOAD,
                    dict(pk=[("ACK", 1), ("ZLP", 2), ("ACK", 5)], ad=[5], rd=[1, 0], pv=COMMIT5), 28000),
    # ⚠ A DELIBERATE STRESS CASE, NOT HOST TIMING (11-13, agents 1 + 2): the retry IN is
    # timed H 1500 from the host's own last packet, so it starts while our ZLP is still
    # on the line (its SOP before our release). A real host retries only after its
    # 16-18-bit timeout after our EOP; kept because it re-arms under a host SOP that
    # lands before our release -- harder than the spec asks, and it passes (+60).
    "A10 lost ZLP": (SA_HOST + [("A", 11000, IN0), ("H", 1500, IN0), ("H", 1500, IN0),
                                ("R", 120, ACKP)], SA_LOAD,
                     dict(pk=[("ACK", 1), ("ZLP", 2), ("ZLP", 4)], ad=[5], rd=[1, 0], pv=COMMIT5), 26000),
    "A10b lost ACK": (SA_HOST + [("A", 11000, IN0), ("R", 120, BADACK),
                                 ("H", 300, P(T(S, 5))), ("H", 0, D0(GETDESC)), ("H", 1500, IN0)],
                      SA_LOAD, dict(pk=[("ACK", 1), ("ZLP", 2), ("ACK", 5)], ad=[5], rd=[1, 0],
                                    pv=COMMIT5), 30000),
    # ⚠ A DELIBERATE STRESS CASE, NOT HOST TIMING (11-13, agents 1 + 2): the retry IN is
    # timed H 1500 from the host's own last packet, so it starts while our ZLP is still
    # on the line (its SOP before our release). A real host retries only after its
    # 16-18-bit timeout after our EOP; kept because it re-arms under a host SOP that
    # lands before our release -- harder than the spec asks, and it passes (+60).
    "A10c ACK absent": (SA_HOST + [("A", 11000, IN0), ("H", 1500, P(T(S, 5))), ("H", 0, D0(GETDESC)),
                                   ("H", 1500, P(T(S, 5))), ("H", 0, D0(GETDESC))],
                        SA_LOAD, dict(pk=[("ACK", 1), ("ZLP", 2), ("ACK", 6)], ad=[5], rd=[1, 0],
                                      pv=COMMIT5), 34000),
    "A11 endpoint": ([("A", 800, IN0), ("A", 7000, P(T(IN, 0, 1))), ("R", 300, IN0), ("R", 120, ACKP)],
                     at(3000, V.load(V.DATA_LINE, 0)),
                     dict(pk=[("NAK", 0), ("NAK", 1), ("DATA", 2)], rd=[1, 0]), 22000),
    "A12 CRC5 mid": ([("A", 800, P(T(IN, 0, flip=13))), ("H", 1500, IN0)], [],
                     dict(pk=[("NAK", 1)]), 9000),
    "A12b CRC5 last": ([("A", 800, P(T(IN, 0, flip=15))), ("H", 1500, IN0)], [],
                       dict(pk=[("NAK", 1)]), 9000),
    "A13 bad SYNC": ([("A", 800, P(V.data(V.PID_DATA0, GETDESC, sync=0x84))), ("H", 200, IN0)], [],
                     dict(pk=[("NAK", 1)]), 12000),
    # gap 1 (Wilson 11-14): the addressed device's handshake follows its DATA at
    # T_IPD ("H", 0); we skip it (never transmit) and catch the host's next
    # SETUP. Red under the old RTOP (back to TOP at once: armed mid-reply).
    "A13b OUT to 7": ([("A", 800, P(T(OUT, 7))), ("H", 0, D0(GETDESC)), ("H", 0, ACKP),
                       ("H", 300, P(T(S, 0))), ("H", 0, D0(GETDESC))], [],
                      dict(pk=[("ACK", 4)]), 22000),
    # a FOREIGN IN, the addressed device's DATA at T_IPD, then an IN to us
    "A13e foreign IN": ([("A", 800, P(T(IN, 7))), ("H", 0, D0(GETDESC)),
                         ("H", 300, IN0)], [],
                        dict(pk=[("NAK", 2)]), 16000),
    # correction A's must-fires (Wilson 11-14): a responder starting JUST INSIDE
    # the window (window_end - 1 bit) is skipped; and with NO responder, an IN to
    # us arriving at the host's EARLIEST next token (18 bit times, fastest host)
    # is caught -- the FALLTHROUGH ARM timed out and TOP is armed in time.
    "A13f inside window": ([("A", 800, P(T(IN, 7))), ("H", V.resp_window() - V.D, D0(GETDESC)),
                            ("H", 300, IN0)], [],
                           dict(pk=[("NAK", 2)]), 16000),
    "A13g host timeout": ([("A", 800, P(T(IN, 7))), ("H", clock.usb_host_next_min_cycles(), IN0)], [],
                          dict(pk=[("NAK", 1)]), 12000),
    # QUAL's must-fires (Wilson 11-13/14, item 3): the reply we skip carries a
    # 12-cycle SE0 glitch near its end -- arm_j must NOT take it for the EOP
    # (M_QUAL_IGNORED re-arms TOP mid-reply and loses the IN that follows at
    # T_IPD); and a reply whose EOP is only 39 cycles -- arm_j MUST fire on it
    "Q1 glitch": ([("A", 800, P(T(IN, 7))), ("H", 0, glitch(D0(GETDESC), 400, 12)),
                   ("H", 0, IN0)], [],
                  dict(pk=[("NAK", 2)]), 16000),
    "Q2 short EOP": ([("A", 800, P(T(IN, 7))), ("H", 0, short_eop(D0(GETDESC), 39)),
                      ("H", 0, IN0)], [],
                     dict(pk=[("NAK", 2)]), 16000),
    "A13c stray DATA": ([("A", 800, D0(GETDESC)), ("H", 300, P(T(S, 0))), ("H", 0, D0(GETDESC))], [],
                        dict(pk=[("ACK", 2)]), 18000),
    "A13d data commit": ([("A", 800, IN0), ("A", 4000, D0(T(S, 5)[2:] + [0] * 6)), ("H", 1500, IN0)],
                         at(3000, V.ctl(I.ctl_pending_addr(5))),
                         dict(pk=[("NAK", 0), ("NAK", 2)], ad=[], pv=PEND5), 16000),
}

#: (define, what, the scenario it must turn red, program variant?)
MUTANTS = [
    ("M_ADDR_EARLY", "the address moves on the pending write", "A7 pending", False),
    ("M_ADDR_NOCHECK", "ADDR_OK reads 1", "A8 commit", False),
    ("M_ADDR_ACK_ONLY", "no commit on a token to the pending address", "A10b lost ACK", False),
    ("M_EP_NOCHECK", "READY ignores the endpoint", "A11 endpoint", False),
    ("M_CRC5_OK", "every CRC5 passes", "A12 CRC5 mid", False),
    ("M_ADDR_OK_EARLY", "ADDR_OK latched before the CRC5", "A12b CRC5 last", False),
    ("M_COMMIT_ON_DATA", "the commit without the PID qualifier", "A13d data commit", False),
    ("M_CTL_AS_QUEUE", "tag 2 lands in queue 2", "A9 new addr", False),
    ("M_SYNC_ABORT_REARM", "the abort re-arms without the SE0 wait", "A13 bad SYNC", True),
    ("M_PID_ANY", "an unexpected PID taken as SETUP", "A13c stray DATA", True),
    # the FALLTHROUGH window (Wilson 11-14): a timeout that HALTS loses the lane
    # (A7: nobody answers the foreign token); an edge that does NOT skip PC+1
    # takes the timeout path on a reply and re-arms TOP mid-packet (A13b)
    ("M_FT_HALTS", "the window's timeout halts the lane", "A7 pending", False),
    ("M_FT_NOSKIP", "the window's edge does not skip PC+1", "A13b OUT to 7", False),
    ("M_QUAL_IGNORED", "arm_j's SE0 qualifier ignored", "Q1 glitch", False),
]


#: ⭐ THE COVERAGE SWEEP'S tb_usbdev ARMS (Wilson 11-13: the v2 benches join the
#: sweep): this gate's 13 scenarios and run_usbrst's, each on its own image and
#: window, so the device side (address, token check, bus reset, handshakes) is
#: reached. Reach only; each scenario is judged by its own gate.
COV_DIR = "probe_cov_usbdev"


def coverage_arms():
    """[(label, plusargs)] for test/benchset.py's tb_usbdev; scripts + images under COV_DIR."""
    import run_usbrst as RS
    d = os.path.join(os.path.dirname(HERE), COV_DIR)
    os.makedirs(d, exist_ok=True)
    imgs = {"dev": V.image(), "nousb": V.image_nousb()}
    for k, im in imgs.items():
        I.write_image(os.path.join(d, "%s.hex" % k), im)
    rows = [("addr_" + n.split()[0], h, l, nc, (0, 0), "dev") for n, (h, l, _e, nc) in SCEN.items()]
    rows += [("rst_" + n.split()[0], h, l, nc, win or (0, 0), RS.IMAGE_OF.get(n, "dev"))
             for n, (h, l, _e, nc, win, _lng) in RS.SCEN.items()]
    arms = []
    for tag, host, loads, ncyc, (w0, w1), im in rows:
        hf, lf = V.write_scripts(d, tag, host, loads)
        rel = lambda p: COV_DIR + "/" + os.path.basename(p)
        arms.append((tag, ["+IMG=%s/%s.hex" % (COV_DIR, im), "+HOST=" + rel(hf), "+LOAD=" + rel(lf),
                           "+NCYC=%d" % ncyc, "+W0=%d" % w0, "+W1=%d" % w1]))
    return arms


def run_all(vvp, tmp, tag, pool, img, names=None):
    jobs = {}
    for name, (host, loads, exp, ncyc) in SCEN.items():
        if names is not None and name not in names:
            continue
        hf, lf = V.write_scripts(tmp, "%s_%s" % (tag, name.split()[0]), host, loads)
        jobs[name] = (host, exp, pool.submit(V.sim, vvp, img, hf, lf, ncyc))
    res, sops, jits = {}, [], []
    for name, (host, exp, fut) in jobs.items():
        p, s, j = V.judge(name, fut.result(), host, exp)
        res[name] = p
        sops += s
        jits += j
    return res, sops, jits


def write_img(tmp, nm, im):
    path = os.path.join(tmp, "usbaddr_%s.hex" % nm)
    I.write_image(path, im)
    sim_run.scratch_image(GEN, path)
    return path


def main() -> int:
    banner("iverilog", "vvp")
    print()
    print("=" * 78)
    print("The USB device address, the token check, decisions after the packet (bundle 6)")
    print("=" * 78)
    probs = V.premise_problems()
    print("  golden premises (CRC5 residual 01100, SETUP-to-0 = 2D 00 10): %s"
          % ("hold" if not probs else "*** " + probs[0]))
    im = V.image()
    pr = I.branch_problems(im)
    if pr:
        probs.append("the device image refused by pe_isa: %s" % pr)
    print("  device program: %d words" % len(V.device_program()))
    q2 = I.branch_problems(V.image_q2())
    print("  Q2  pe_isa on a USB image drawing queue 2: %s" % ("refused" if q2 else "*** ACCEPTED"))
    # correction A (Wilson 11-14), GENERATED: the FALLTHROUGH window's latest
    # expiry + the timeout path to TOP's arm_sop <= the host's earliest next token
    wp = V.resp_window_problems()
    print("  W1  response window: walk %d + window %d + to TOP %d <= host %d: %s"
          % (V.rtop_walk_max(), V.resp_window(), V.rtop_to_top_max(),
             clock.usb_host_next_min_cycles(), "ok" if not wp else "*** " + wp[0]))
    probs += wp
    # must-fire: the host's TIMEOUT taken as the window (the error correction A
    # names) must be red
    wm = V.resp_window_problems(window=clock.USB_HOST_RESP_WAIT_BITS * V.D)
    print("  W1m the host's 18-bit timeout as the window -> %s" % ("red  ok" if wm else "*** STAYED GREEN"))
    if not wm:
        probs.append("must-fire: the host-timeout window stayed green")
    if not any("queue 2" in x for x in q2):
        probs.append("pe_isa accepted a USB image drawing queue 2")
    for v in ("M_SYNC_ABORT_REARM", "M_PID_ANY"):
        pv = I.branch_problems(V.image(v))
        if pv:
            probs.append("program mutant %s refused by pe_isa (it must assemble): %s" % (v, pv))
    tmp = tempfile.mkdtemp(prefix="pe_usbaddr_")
    img = write_img(tmp, "dev", im)
    vvp = os.path.join(tmp, "usbaddr.vvp")
    V.build(vvp)
    with ThreadPoolExecutor(max_workers=8) as pool:
        res, sops, jits = run_all(vvp, tmp, "base", pool, img)
        print("\n  A7-A13d")
        for name, p in res.items():
            print("    %-18s %s" % (name, "exact" if not p else "*** " + p[0]))
            probs += p
        print("    M19 MEASURED: device SOP after the host's EOP: %d..%d cycles over %d replies "
              "(window %d..%d); worst %d" % (min(sops), max(sops), len(sops), V.TURN_LO, V.TURN_HI,
                                             max(sops)))
        print("    MEASURED: worst device edge lateness off the bit grid: %d cycle(s) (J = %d)"
              % (max(jits or [0]), V.J_MAX))
        print("\n  must-fires (each red in its target scenario)")
        for d, what, target, prog in MUTANTS:
            if prog:
                mimg = write_img(tmp, d, V.image(d))
                mv = vvp
            else:
                mimg = img
                mv = os.path.join(tmp, "usbaddr_%s.vvp" % d)
                try:
                    V.build(mv, [d])
                except RuntimeError as exc:
                    probs.append("%s: %s" % (d, exc))
                    continue
            r, _s, _j = run_all(mv, tmp, d, pool, mimg)
            red = [(n, p[0]) for n, p in r.items() if p]
            hit = target in dict(red)
            print("    %-20s %-40s %s" % (d, what, ("RED in %d of %d; target %s: %s" % (
                len(red), len(r), target, dict(red)[target][:60])) if hit else
                "*** target %s GREEN (red: %s)" % (target, [n for n, _ in red])))
            if not hit:
                probs.append("%s did not turn its target %s red" % (d, target))
    print()
    if probs:
        print("  GATE usbaddr: FAILED (%d)" % len(probs))
        for x in probs:
            print("    - %s" % x)
        return 1
    print("  GATE usbaddr: PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
