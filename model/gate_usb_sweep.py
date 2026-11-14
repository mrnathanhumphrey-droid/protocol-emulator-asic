#!/usr/bin/env python3
"""gate_usb_sweep -- the USB lane's no-stall theorem, measured on the RTL (Wilson 11-13, condition 4).

What lean/JLane/JLane/UsbNoStall.lean proves, checked on every run of an admissible sweep:
  * the bytes decode exactly and every receive sample keeps one edge-to-sample latency
    (run_usbrx.judge, the receive gate's own golden);
  * J <= J_MAX: the receive-sample dispatch wait (usb_j2_nb);
  * zero dispatch stalls after the USB lane's first retirement (usb_nostall; the cold start
    before it is outside the theorem's primed start, and run_usbrx U7 covers it);
  * at most usb_br1_per_window USB-lane branch-1 refills in any 23 + br1_budget cycles
    (usb_br1_window), counted after the first retirement.
THE SWEEP (admissible: every number from model/proof_constants.load()): run_usbrx's receive
program on lane 0 (D_sched 2D); the four other lanes at period coresident_usb, D_sched = the
USB lane's + usb_deadline_margin; 1 or 2 of them BRANCH_BIT lanes at W = coresident_usb and
coresident_usb + 10; the host's packets (run_usbrx.PAYLOADS) shifted over 14 phase offsets
x run_usbrx.DRIFTS.

MUST-FIRE (judged by the same `judge`):
  M_USB_MARGIN1  the other lanes' D_sched only 1 above the USB lane's (the old "strictly
                 earliest" rule): the bytes must go wrong and J must exceed J_MAX
                 (measured 11-13: wrong bytes in 9 of 42 runs, J = 10)

POSITIVE TOKEN: `GATE usb_sweep: PASSED`.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "test")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import proof_constants as PC          # noqa: E402
import pe_isa as I                    # noqa: E402
import run_usbrx as RX                # noqa: E402
import sim_run                        # noqa: E402
from toolchain import banner, tool    # noqa: E402

GEN = "gate_usb_sweep"
PROBE = "model/usb_sweep_probe.v"
#: the dispatch-wait bound usb_j2 / usb_j2_nb prove: decided within 2 cycles (SPEC: the theorem)
J_MAX = 2
#: gate_mutant_kills' scratch-mutant registry (ruling AC2): this gate is the killer
SCRATCH_MUTANTS = {
    "M_USB_MARGIN1": "the other lanes' D_sched 1 above the USB lane's; judged in-process by this gate",
}
PHASES = 14


def image(k, nbr, w_branch, ds_other):
    """lane 0: run_usbrx's receive program; lanes 1-4 at period coresident_usb, the last `nbr`
    of them looping LEVEL -> BRANCH_BIT (W = w_branch, on the host's D-, taken or not)."""
    D, DM, per = RX.D, RX.DM, k["coresident_usb"]
    prog = [I.act_arm(DM, 0, 0, half=True)]       # HALF (11-14): no nop(D/2)
    prog += [I.act_shiftin_usb(DM, D, 8) for _ in range(RX.NBYTES)]
    prog += [I.act(I.OP_LEVEL, I.PIN_NONE, 0, RX.POST), I.act(I.OP_REARM, 0, 1, D // 2)]
    hs = [I.hdr(DM, I.PIN_NONE, 1, D, 0, 2 * D, 3 * D, I.ACT_BASE)]
    for n in range(1, I.N_LANES):
        pin = I.UO0 + n - 1
        base = I.ACT_BASE + len(prog) * I.ACT_BYTES
        if n > I.N_LANES - 1 - nbr:
            body = [I.act(I.OP_LEVEL, pin, 1, per), I.act_branch_bit(DM, 1, I.base_word(base), w_branch),
                    I.act(I.OP_REARM, 0, 1, per)]
        else:
            body = [I.act(I.OP_LEVEL, pin, 1, per), I.act(I.OP_LEVEL, pin, 0, per),
                    I.act(I.OP_REARM, 0, 1, per)]
        prog += body
        hs.append(I.hdr(pin, pin, 1, per, 0, ds_other, ds_other + 20, base))
    return I.join_image(hs, prog)


def arms(k):
    usb_ds = 2 * RX.D
    clean = [("W=%d, %d branch lane(s)" % (w, n), image(k, n, w, usb_ds + k["usb_deadline_margin"]))
             for w in (k["coresident_usb"], k["coresident_usb"] + 10) for n in (1, 2)]
    margin1 = [("M_USB_MARGIN1", image(k, 0, k["coresident_usb"], usb_ds + 1))]
    return clean, margin1


def stimuli():
    pk = [RX.packet(*p) for p in RX.PAYLOADS]
    out, t0 = [], RX.T_FIRST
    try:
        for s in range(0, PHASES * 3, 3):
            for e in RX.DRIFTS:
                RX.T_FIRST = t0 + s
                tr, t_end = RX.line(pk, e, 8, 500 + int(1000 * e) + s)
                out.append((s, e, pk, tr, t_end))
    finally:
        RX.T_FIRST = t0
    return out


def sim(vvp, img, wave, ncyc):
    r = RX.run(sim_run.vvp([vvp, "+IMG=%s" % img, "+WAVE=%s" % wave, "+NCYC=%d" % ncyc], images=[img]))
    o = r.stdout + r.stderr
    ev = lambda t: [(int(a), int(b)) for a, b in re.findall(r"^%s (\d+) (\d+)$" % t, o, re.M)]
    return {"rx": [(int(c), int(v), int(l)) for c, v, l in re.findall(r"^RX (\d+) (\d+) (\d+)$", o, re.M)],
            "se": ev("SE"), "ce": [int(c) for c in re.findall(r"^CE (\d+)$", o, re.M)], "sa": ev("SA"),
            "stl": ev("STL"), "b1": ev("B1"), "rt": ev("RT"), "end": "END" in o, "tail": o[-300:]}


def judge(name, runs, k):
    """[problem] for one arm's runs: (stimulus, result) pairs. The clean arms and the must-fire
    go through this one function."""
    probs = []
    win = 23 + k["br1_budget"]
    for (s, e, pk, tr, _t), r in runs:
        tag = "%s s=%d e=%+.3f" % (name, s, e)
        pr, _ks, jit = RX.judge(tag, pk, r["rx"], r["se"], r["ce"], r["sa"], tr, r["end"], r["tail"], [])
        probs += pr
        if jit > J_MAX:
            probs.append("%s: receive-sample wait J = %d > %d (usb_j2_nb)" % (tag, jit, J_MAX))
        c0 = r["rt"][0][0] if r["rt"] else None
        if c0 is None:
            probs.append("%s: the USB lane never retired -- the run measured nothing" % tag)
            continue
        stl = [c for c, _l in r["stl"] if c > c0]
        if stl:
            probs.append("%s: %d stall cycle(s) after the first retirement, first at %d (usb_nostall)"
                         % (tag, len(stl), stl[0]))
        ub = sorted(c for c, l in r["b1"] if c > c0 and l == I.USB_LANE)
        most = max((sum(1 for d in ub if c <= d < c + win) for c in ub), default=0)
        if most > k["usb_br1_per_window"]:
            probs.append("%s: %d USB-lane branch-1 refills in one %d-cycle window > %d (usb_br1_window)"
                         % (tag, most, win, k["usb_br1_per_window"]))
    return probs


def run_arm(vvp, tmp, pool, name, img, stim, tag):
    ip = os.path.join(tmp, "usbsweep_%s.hex" % tag)
    I.write_image(ip, img)
    sim_run.scratch_image(GEN, ip)
    futs = []
    for i, (s, e, pk, tr, t_end) in enumerate(stim):
        wp = os.path.join(tmp, "wave_%s_%d.txt" % (tag, i))
        RX.write_wave(wp, tr)
        futs.append(((s, e, pk, tr, t_end), pool.submit(sim, vvp, ip, wp, t_end + 400)))
    return [(st, f.result()) for st, f in futs]


def main() -> int:
    banner("iverilog", "vvp")          # ruling V2: the log names the binaries
    k = PC.load()
    clean, margin1 = arms(k)
    for name, img in clean:
        pr = I.usb_problems(img) + I.branch_problems(img) + PC.usb_coresident_problems(img, k)
        if pr:
            print("GATE usb_sweep: FAILED -- a clean arm is not admissible (%s): %s" % (name, pr[0]))
            return 1
    stim = stimuli()
    print("USB no-stall sweep: %d admissible arms x %d stimuli; margin %d, co-resident %d, window %d, "
          "bound %d, J <= %d" % (len(clean), len(stim), k["usb_deadline_margin"], k["coresident_usb"],
                                 23 + k["br1_budget"], k["usb_br1_per_window"], J_MAX))
    tmp = tempfile.mkdtemp(prefix="pe_usbsweep_")
    vvp = os.path.join(tmp, "usbsweep.vvp")
    b = RX.run([tool("iverilog"), "-g2012", "-I", ROOT, "-o", vvp, "-s", "tb_usbrx",
                "-s", "usb_sweep_probe", RX.BENCH, PROBE] + RX.RTL)
    if b.returncode != 0:
        print("GATE usb_sweep: FAILED -- build: %s" % (b.stdout + b.stderr)[-400:])
        return 1
    probs = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for i, (name, img) in enumerate(clean):
            runs = run_arm(vvp, tmp, pool, name, img, stim, "c%d" % i)
            p = judge(name, runs, k)
            ub = sum(1 for _s, r in runs for c, l in r["b1"]
                     if l == I.USB_LANE and r["rt"] and c > r["rt"][0][0])
            print("    %-26s %3d runs  %s  (USB branch-1 after start-up: %d)"
                  % (name, len(runs), "exact: no stall, J <= %d, window bound held" % J_MAX if not p
                     else "*** " + p[0][:90], ub))
            probs += p
        name, img = margin1[0]
        mp = judge(name, run_arm(vvp, tmp, pool, name, img, stim, "m1"), k)
        wrong = [p for p in mp if "bytes, golden" in p]
        late = [p for p in mp if "J = " in p]
        red = bool(wrong) and bool(late)
        print("  must-fire M_USB_MARGIN1  %s  (%d wrong-byte runs, %d J > %d runs)"
              % ("RED (killed)" if red else "*** SURVIVED", len(wrong), len(late), J_MAX))
        if not red:
            probs.append("must-fire M_USB_MARGIN1 survived: the margin-1 arm did not lose bytes and J")
    for p in probs[:20]:
        print("  ***", p)
    if probs:
        print("GATE usb_sweep: FAILED (%d)" % len(probs))
        return 1
    print("GATE usb_sweep: PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
