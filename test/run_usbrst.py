#!/usr/bin/env python3
"""The USB BUS RESET, the reset fence and the reset notice (v2 primitive 3,
bundle 6; Wilson 11-09, step 7a §1 / §2, addition A, choices 3-4).

THE CLAIMS, on the device program (test/usbdev.py) against a host on D-/D+:
  * a keep-alive EOP (80 or 90 cycles of SE0) every 1 ms for 10 ms resets
    nothing, fires no ARM and dispatches nothing on the USB lane; the address
    is kept (M1, M15);
  * a 10 ms SE0 resets exactly once (M2), at cycle N_RST of the SE0 -- N_RST
    from model/clock.py, the RTL's own formula -- and an SE0 one cycle shorter
    does not (M4); our own EOPs never do (M3: every scenario counts resets);
  * the reset returns the device to Default: address 0, READY clear, the token
    to the old address ignored; one reset notice (RX kind 5) (M5); a reset in
    the middle of a received DATA packet: no ACK, and the next SETUP is ACKed
    once the RP2040 has acknowledged (M6);
  * THE FENCE: records the RP2040 sent before its acknowledgement are refused
    -- a buffer load and a pending address -- and a load after it is accepted
    (M18); an acknowledgement with no reset changes no state (M18b);
  * a program WITHOUT a USB receive holding lane 0's pins low for 10 ms fires
    no reset (Wilson 11-09 choice 3: counting only while the USB lane is live).

Bench: test/tb_usbdev.v. Golden: test/usbdev.py.
  must-fires: M_RST_NEVER M_RST_SHORT M_RST_KEEP_ADDR M_RST_KEEP_READY
     M_RST_NO_FENCE M_RST_ANY -- each red in its target scenario. The 10 ms
     scenarios (R1, R2, R20) run under their own target mutant only.

POSITIVE TOKEN: `GATE usbrst: PASSED`.
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
for _p in (HERE, os.path.join(os.path.dirname(HERE), "model")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from toolchain import banner             # noqa: E402
import clock                             # noqa: E402
import pe_isa as I                       # noqa: E402
import sim_run                           # noqa: E402
import usbdev as V                       # noqa: E402

GEN = "run_usbrst"
T = V.token
P = V.pkt
IN, S = V.PID_IN, V.PID_SETUP
N_RST = clock.usb_n_rst(clock.target_hz("chip"))
MS = clock.cycles_nominal(1_000_000, clock.target_hz("chip"))    # 1 ms in cycles
GETDESC = [0x80, 0x06, 0x00, 0x01, 0x00, 0x00, 0x12, 0x00]
D0 = P(V.data(V.PID_DATA0, GETDESC))
IN0, IN5 = P(T(IN, 0)), P(T(IN, 5))
ACKP = P([0x80, V.PID_ACK])
ACK_REC = V.ctl(I.CTL_RST_ACK)


def at(t0, items, step=60):
    return [("A", t0 + k * step, b, tag) for k, (b, tag) in enumerate(items)]


# address 5 the short way: the pending address, then an IN to 5 (the hardware
# commit on a token to the pending address)
TO5_HOST = [("A", 800, IN0), ("A", 4000, IN5)]
TO5_LOAD = at(3000, V.ctl(I.ctl_pending_addr(5)))
KA0 = 10_000
KAS = [("A", KA0 + k * MS, V.se0(80 if k % 2 == 0 else 90)) for k in range(10)]
T_END_KA = KA0 + 10 * MS
RST = V.se0(2000)

#: name -> (host, loads, expectation, ncyc, (w0, w1) or None, long?)
SCEN = {
    "R1 keep-alive": (TO5_HOST + KAS + [("A", T_END_KA + 2000, IN5), ("H", 1500, IN0)], TO5_LOAD,
                      dict(pk=[("NAK", 0), ("NAK", 1), ("NAK", 12)], ad=[5], br=0, rn=0),
                      T_END_KA + 9000, (KA0 - 500, T_END_KA + 1000), True),
    "R2 10ms reset": ([("A", 800, IN0), ("A", 5000, V.se0(10 * MS)), ("H", 1500, IN0)], [],
                      dict(pk=[("NAK", 0), ("NAK", 2)], ad=[], fe=[1], br=1, rn=1),
                      5000 + 10 * MS + 6000, None, True),
    "R4 boundary": ([("A", 800, IN0), ("A", 3000, V.se0(N_RST - 1)), ("A", 6000, V.se0(N_RST)),
                     ("H", 1500, IN0)], [],
                    dict(pk=[("NAK", 0), ("NAK", 3)], fe=[1], br=1, rn=1), 12000, None, False),
    "R5 default": (TO5_HOST + [("A", 11000, RST), ("H", 1500, IN0), ("H", 1500, IN5)],
                   TO5_LOAD + at(7000, V.load(V.DATA_LINE)),
                   dict(pk=[("NAK", 0), ("NAK", 1), ("NAK", 3)], ad=[5, 0], rd=[1, 0], fe=[1], br=1, rn=1),
                   22000, None, False),
    "R6 mid-DATA": ([("A", 800, P(T(S, 0))), ("H", 0, V.cut_then_reset(V.data(V.PID_DATA0, GETDESC), 40, 6000)),
                     ("A", 16000, P(T(S, 0))), ("H", 0, D0)],
                    at(14000, ACK_REC),
                    dict(pk=[("ACK", 3)], fe=[1, 0], br=1, rn=1), 26000, None, False),
    "R18 fence": ([("A", 800, IN0), ("A", 5000, RST), ("A", 10000, IN0), ("A", 15000, IN0),
                   ("R", 120, ACKP)],
                  at(8000, V.load(V.DATA_LINE) + V.ctl(I.ctl_pending_addr(5)))
                  + at(12000, ACK_REC) + at(12200, V.load(V.DATA_LINE)),
                  dict(pk=[("NAK", 0), ("NAK", 2), ("DATA", 3)], rd=[1, 0], pv=[], tf=True, fe=[1, 0], br=1, rn=1),
                  24000, None, False),
    "R18b ack no-op": ([("A", 800, IN0), ("A", 5000, IN0)], at(3000, ACK_REC),
                       dict(pk=[("NAK", 0), ("NAK", 1)], fe=[], tf=False, sv=[], br=0, rn=0), 9000, None, False),
    "R20 no USB": ([("A", 1000, V.se0(10 * MS))], [],
                   dict(pk=[], br=0, rn=0), 1000 + 10 * MS + 2000, None, True),
}
IMAGE_OF = {"R20 no USB": "nousb"}

#: (define, what, target scenario)
MUTANTS = [
    ("M_RST_NEVER", "the reset never fires", "R2 10ms reset"),
    ("M_RST_SHORT", "threshold 64: a keep-alive resets", "R1 keep-alive"),
    ("M_RST_KEEP_ADDR", "the reset keeps the address", "R5 default"),
    ("M_RST_KEEP_READY", "the reset keeps READY", "R5 default"),
    ("M_RST_NO_FENCE", "the fence never rises", "R18 fence"),
    ("M_RST_ANY", "counting without a live USB lane", "R20 no USB"),
]


def run_all(vvp, tmp, tag, pool, imgs, names):
    jobs = {}
    for name in names:
        host, loads, exp, ncyc, win, _lng = SCEN[name]
        hf, lf = V.write_scripts(tmp, "%s_%s" % (tag, name.split()[0]), host, loads)
        w0, w1 = win or (0, 0)
        img = imgs[IMAGE_OF.get(name, "dev")]
        jobs[name] = (host, exp, win, pool.submit(V.sim, vvp, img, hf, lf, ncyc, w0, w1))
    res, sops, extra = {}, [], {}
    for name, (host, exp, win, fut) in jobs.items():
        r = fut.result()
        p, s, _j = V.judge(name, r, host, exp)
        if "sv" in exp and r["sv"] != exp["sv"]:
            p.append("%s: USB state changed %s, golden unchanged" % (name, r["sv"][:3]))
        if win:
            afw = [c for c in r["af"] if win[0] <= c < win[1]]
            if r["n0"] != 0 or afw:
                p.append("%s: in the keep-alive window lane 0 dispatched %d time(s) and "
                         "%d ARM(s) fired, golden 0 / 0" % (name, r["n0"], len(afw)))
        extra[name] = r
        res[name] = p
        sops += s
    return res, sops, extra


def write_img(tmp, nm, im):
    path = os.path.join(tmp, "usbrst_%s.hex" % nm)
    I.write_image(path, im)
    sim_run.scratch_image(GEN, path)
    return path


def main() -> int:
    banner("iverilog", "vvp")
    print()
    print("=" * 78)
    print("The USB bus reset, the fence, the reset notice (v2 primitive 3, bundle 6)")
    print("=" * 78)
    probs = V.premise_problems()
    print("  N_RST = %d cycles at %g MHz (model/clock.py, the RTL's formula); 1 ms = %d cycles"
          % (N_RST, clock.target_hz("chip") / 1e6, MS))
    for nm, im in (("dev", V.image()), ("nousb", V.image_nousb())):
        pr = I.branch_problems(im)
        if pr:
            probs.append("the %s image refused by pe_isa: %s" % (nm, pr))
    tmp = tempfile.mkdtemp(prefix="pe_usbrst_")
    imgs = {"dev": write_img(tmp, "dev", V.image()), "nousb": write_img(tmp, "nousb", V.image_nousb())}
    vvp = os.path.join(tmp, "usbrst.vvp")
    V.build(vvp)
    short = [n for n, s in SCEN.items() if not s[5]]
    with ThreadPoolExecutor(max_workers=8) as pool:
        res, sops, ex = run_all(vvp, tmp, "base", pool, imgs, list(SCEN))
        print("\n  R1-R20")
        for name, p in res.items():
            print("    %-16s %s" % (name, "exact" if not p else "*** " + p[0]))
            probs += p
        # M2 / M4: WHEN the reset fires, against the SE0's first cycle at the pins
        for name in ("R2 10ms reset", "R4 boundary"):
            r = ex[name]
            hp = dict((k, c) for c, k in r["hp"])
            k_se0 = 1 if name.startswith("R2") else 2
            if r["br"]:
                lat = r["br"][0] - hp[k_se0]
                print("    %s: the reset fires %d cycles after the host's SE0 starts (N_RST %d + "
                      "%d of synchroniser and register)" % (name.split()[0], lat, N_RST, lat - N_RST))
                if not 0 <= lat - N_RST <= 4:
                    probs.append("%s: the reset fired %d cycles into the SE0, not N_RST + <=4" % (name, lat))
        print("    device SOP after the host's EOP: %s cycles" % sorted(set(sops)))
        print("\n  must-fires (each red in its target scenario)")
        for d, what, target in MUTANTS:
            mv = os.path.join(tmp, "usbrst_%s.vvp" % d)
            try:
                V.build(mv, [d])
            except RuntimeError as exc:
                probs.append("%s: %s" % (d, exc))
                continue
            names = sorted(set(short) | {target})
            r, _s, _x = run_all(mv, tmp, d, pool, imgs, names)
            red = [(n, p[0]) for n, p in r.items() if p]
            hit = target in dict(red)
            print("    %-18s %-36s %s" % (d, what, ("RED in %d of %d; target %s: %s" % (
                len(red), len(r), target, dict(red)[target][:60])) if hit else
                "*** target %s GREEN (red: %s)" % (target, [n for n, _ in red])))
            if not hit:
                probs.append("%s did not turn its target %s red" % (d, target))
    print()
    if probs:
        print("  GATE usbrst: FAILED (%d)" % len(probs))
        for x in probs:
            print("    - %s" % x)
        return 1
    print("  GATE usbrst: PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
