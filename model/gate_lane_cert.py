"""gate_lane_cert -- the stage 6 certificate as a gate (Wilson 11-14: red now, green after the
program fix). Runs model/lane_cert.py on usbdev's image and checks the SHIFTI spacing rule;
every must-fire must turn its check red, or the gate is not testing what it says.

  check 1  proof_constants.spacing_of reads SHIFTI's low 8 delay bits (RTL l.1892)
  check 2  lane_cert on usbdev: certificate, release-after-writeback, arming, next-SOP fetch
           deadline, first sample, turnaround, other lanes, correction A -- all green
  M_LC_ARMJ_FLOOR   arm_j's premise weakened to the ARM floor     -> check 2 red at an arm_j
  M_LC_LATE_SOP     an extra 40-cycle nop before a handshake copy's arm_sop -> red (armed after
                    the earliest SOP: the certificate's own premise fails)
  M_LC_SHIFTI_FULL  spacing_of reads SHIFTI's whole delay field   -> check 1 red
  M_LC_LAT_IGNORED  the certificate's lateness zeroed -> check 3 red (the flush refill's
                    lateness on PC+2 vanishes: the gate notices it lost its teeth)
  check 3  FALLTHROUGH (ArmFT, F4): usbdev with one handshake copy's (HALF) arm_sop made
           FALLTHROUGH (ARM_MOD_FT) must be refused twice (a SHIFTIN at PC+2; HALF with
           FALLTHROUGH), and the certificate must put flush_refill_late on its PC+2
  check 4  CORESIDENT_USB (Wilson 11-14 ruling 2): proof_constants' certified usb_other_R is
           the current certificate's (gen_cert_constants), and the rule it derives refuses an
           image whose other lanes act every coresident_usb - 1 cycles and accepts one at
           coresident_usb (56 refused, 57 accepted today)
  M_LC_CERT_STALE   a stored usb_other_R one below the certificate -> check 4 red
  M_LC_FT_UNSEEN    no ARM read as FALLTHROUGH                    -> check 3 red
  M_LC_FT_NOFLOOR   no lateness floor after the flush             -> check 3 red
Static, < 2 s. Usage: python model/gate_lane_cert.py [dir holding usbdev.py]
"""
from __future__ import annotations

import contextlib
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _setup(img_dir=None):
    sys.path[:0] = [HERE, os.path.join(ROOT, "test")]
    import lane_cert as LC                           # (puts test/ first on the path itself)
    import proof_constants as PC
    if img_dir:
        sys.path.insert(0, img_dir)                  # the image module given wins
    import usbdev as V
    return LC, PC, V


def check_spacing(PC, I):
    w = I._unpack(I.ACT_FIELDS, I.act_shifti(0xA5, 1, 40), I.ACT_BYTES)
    got = PC.spacing_of(w, I)
    return got == 40, "spacing_of(SHIFTI 0xA5 @ 40) = %d (want 40)" % got


def run_cert(LC, img, quiet=True):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf) if quiet else contextlib.nullcontext():
        fails = LC.full_report(img, "usbdev")
    return fails, buf.getvalue()


def ft_program(LC, V, I):
    """usbdev's program with one handshake copy's arm_sop (an edge ARM, not after an SE0 ARM, not
    the lane's first word, whose PC+2 is a SHIFTIN) made FALLTHROUGH: (program, word)"""
    img = V.image()
    g = LC.lane_graph(img, I.USB_LANE, I)
    base = min(g)
    preds = {w: [p for p in g if w in g[p][1]] for w in g}
    for w in sorted(g):
        if (w == base or LC.arm_kind(g[w][0], I) != "edge" or not preds[w] or
                all(LC.arm_kind(g[q][0], I) == "se0" for q in preds[w])):
            continue
        if w + 2 in g and g[w + 2][0]["op"] == I.OP_SHIFTIN:
            p = V.device_program()
            x = g[w][0]
            bit = I.ARM_MOD_FT
            p[w - base] = I.act(x["op"], x["pin"], x["level"], 500, count=x["count"], q=x["q"],
                                pinb=x["pinb"], mod=x["mod"] | bit)
            return p, w
    return None, None


def check_ft(LC, V, I):
    """the FALLTHROUGH paths on a handshake copy's arm_sop made FALLTHROUGH (it keeps its HALF bit):
    the refusals fire (a SHIFTIN at PC+2; HALF with FALLTHROUGH) and the certificate puts the
    flush refill's lateness (proof_constants flush_refill_late) on PC+2"""
    p, w = ft_program(LC, V, I)
    if p is None:
        return False, "no handshake arm_sop with a SHIFTIN at PC+2 to test on"
    img = V.image(prog=p)
    fails, _o = run_cert(LC, img)
    refused = any(f[0] == "FT" and f[1].startswith("w%d PC+2" % w) for f in fails)
    halfed = any(f[0] == "FT" and f[1].startswith("w%d HALF" % w) for f in fails)
    import proof_constants as PC
    k = PC.load()
    g, preds, gaps = LC.build(img, I.USB_LANE, LC.premises(k), I)
    fts = LC.ft_paths(g, I)
    floor = {c2: LC.ft_flush_late(0) for _c1, c2 in fts.values() if c2 in g}
    xr = {c1: 1 for c1, _c2 in fts.values() if c1 in g}
    cert = LC.certificate(g, preds, gaps, k, 0, 2, floor=floor, xr=xr)
    floored = (w in fts and cert is not None and
               cert[0].get(fts[w][1], 0) >= k["flush_refill_late"])
    ok = refused and floored and halfed
    return ok, ("arm_sop w%d made FALLTHROUGH: PC+2 refused %s, PC+2 late by the flush refill %s, "
                "HALF + FALLTHROUGH refused %s" % (w, refused, floored, halfed))


def image_others_at(V, I, d):
    """usbdev's image with every other lane's word acting every `d` cycles (usbdev.image's own
    layout; its other lanes act every 500)"""
    p = V.device_program()
    l0 = I.ACT_BASE
    lp = l0 + len(p) * I.ACT_BYTES
    p = p + [I.act(I.OP_REARM, 0, 0, d)]
    hs = [I.hdr(V.DM, I.PIN_NONE, 1, V.D, 0, 2 * V.D, 3 * V.D, l0)]
    hs += [I.hdr(I.UO0 + n - 1, I.UO0 + n - 1, 1, 500, 0, 200, 240, lp)
           for n in range(1, I.N_LANES)]
    return I.join_image(hs, p)


def check_coresident(PC, V, I):
    import gen_cert_constants as G
    k = PC.load()
    cur = G.certified()
    fresh = all(k.get(c) == v for c, v in cur.items())
    lim = k["coresident_usb"]
    refused = bool(PC.usb_coresident_problems(image_others_at(V, I, lim - 1), k))
    accepted = not PC.usb_coresident_problems(image_others_at(V, I, lim), k)
    ok = fresh and refused and accepted
    return ok, ("usb_other_R stored %s, certificate %s (%s); coresident_usb %d: %d refused %s, "
                "%d accepted %s" % (k.get("usb_other_R"), cur.get("usb_other_R"),
                                    "current" if fresh else "STALE", lim, lim - 1, refused, lim,
                                    accepted))


def main():
    img_dir = sys.argv[1] if len(sys.argv) > 1 else None
    LC, PC, V = _setup(img_dir)
    I = LC._isa()
    print("gate_lane_cert: image module %s" % V.__file__)
    ok1, msg1 = check_spacing(PC, I)
    print("  check 1 %s  %s" % ("GREEN" if ok1 else "RED", msg1))
    fails, out = run_cert(LC, V.image())
    print("  check 2 %s  %s" % ("GREEN" if not fails else "RED",
                               "lane_cert PASS" if not fails else "%d failure(s): %s"
                               % (len(fails), sorted({f[1] for f in fails}))))
    ok3, msg3 = check_ft(LC, V, I)
    print("  check 3 %s  %s" % ("GREEN" if ok3 else "RED", msg3))
    ok4, msg4 = check_coresident(PC, V, I)
    print("  check 4 %s  %s" % ("GREEN" if ok4 else "RED", msg4))
    kills = []
    # M_LC_CERT_STALE: a stored usb_other_R one below the certificate
    orig_load = PC.load
    PC.load = lambda path=PC.PATH: dict(orig_load(path), usb_other_R=orig_load(path)["usb_other_R"] - 1)
    try:
        k4, _m = check_coresident(PC, V, I)
    finally:
        PC.load = orig_load
    kills.append(("M_LC_CERT_STALE", not k4, "a stale certified usb_other_R"))
    # M_LC_FT_UNSEEN / M_LC_FT_NOFLOOR
    orig_ft = PC.arm_is_ft
    PC.arm_is_ft = lambda x, I=None: False
    try:
        k3, _m = check_ft(LC, V, I)
    finally:
        PC.arm_is_ft = orig_ft
    kills.append(("M_LC_FT_UNSEEN", not k3, "no ARM read as FALLTHROUGH"))
    orig_fl = LC.ft_flush_late
    LC.ft_flush_late = lambda B: 0
    try:
        k3, _m = check_ft(LC, V, I)
    finally:
        LC.ft_flush_late = orig_fl
    kills.append(("M_LC_FT_NOFLOOR", not k3, "no lateness floor after the flush"))
    # M_LC_ARMJ_FLOOR
    orig_prem = LC.premises
    LC.premises = lambda k=None: dict(orig_prem(k), arm_j=orig_prem(k)["arm_floor"])
    f, _o = run_cert(LC, V.image())
    LC.premises = orig_prem
    kills.append(("M_LC_ARMJ_FLOOR", any(x[1].startswith("arm w") and x[1] not in
                                         {y[1] for y in fails} for x in f),
                  "arm_j premise at the floor"))
    # M_LC_LATE_SOP: a 40-cycle nop before the first handshake copy's arm_sop (the word after
    # our EOP's READBIT): its chain from our EOP grows by 40
    p = V.device_program()
    g = LC.lane_graph(V.image(), I.USB_LANE, I)
    target = None
    for w in sorted(g):
        x = g[w][0]
        if x["op"] == I.OP_READBIT and any(LC.arm_kind(g[s][0], I) == "edge" for s in g[w][1]):
            target = w - min(g)
            break
    if target is not None:
        p2 = p[:target + 1] + [I.act(I.OP_LEVEL, I.PIN_NONE, 0, 40)] + p[target + 1:]
        try:
            f, _o = run_cert(LC, V.image(prog=p2))
            hit = any(x[1].startswith("armed late") and x[1] not in {y[1] for y in fails}
                      for x in f)
        except Exception as ex:                      # a shifted branch target may not assemble
            hit, _o = False, str(ex)
    else:
        hit = False
    kills.append(("M_LC_LATE_SOP", hit, "a 40-cycle nop before a handshake copy's arm_sop"))
    # M_LC_SHIFTI_FULL
    orig_sp = PC.spacing_of
    PC.spacing_of = lambda x, I=None: x["delay"]
    ok, _m = check_spacing(PC, I)
    PC.spacing_of = orig_sp
    kills.append(("M_LC_SHIFTI_FULL", not ok, "spacing_of reads the whole field"))
    # M_LC_LAT_IGNORED: zero lateness everywhere -> the known first-sample failures vanish
    orig_cert = LC.certificate

    def no_lat(*a, **kw):
        r = orig_cert(*a, **kw)
        if r is None:
            return r
        lat, Z, Rr = r
        return {w: 0 for w in lat}, Z, Rr
    LC.certificate = no_lat
    try:
        k3, _m = check_ft(LC, V, I)
    finally:
        LC.certificate = orig_cert
    kills.append(("M_LC_LAT_IGNORED", not k3, "lateness zeroed: check 3 loses the flush floor"))
    for name, killed, what in kills:
        print("  must-fire %-18s %s  %s" % (name, "RED (killed)" if killed else "SURVIVED", what))
    teeth = all(k for _n, k, _w in kills)
    green = ok1 and not fails and ok3 and ok4
    verdict = "PASSED" if (green and teeth) else ("FAILED (must-fire survived)" if not teeth
                                                   else "FAILED")
    print("GATE lane-cert: %s" % verdict)
    return 0 if verdict == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main())
