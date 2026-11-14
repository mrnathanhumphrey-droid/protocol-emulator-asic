"""gate_lane_cert -- the stage 6 certificate as a gate (Wilson 11-14: red now, green after the
program fix). Runs model/lane_cert.py on usbdev's image and checks the SHIFTI spacing rule;
every must-fire must turn its check red, or the gate is not testing what it says.

  check 1  proof_constants.spacing_of reads SHIFTI's low 8 delay bits (RTL l.1892)
  check 2  lane_cert on usbdev: certificate, release-after-writeback, arming, next-SOP fetch
           deadline, first sample, turnaround, other lanes, correction A -- all green
  M_LC_ARMJ_FLOOR   arm_j's premise weakened to the ARM floor     -> check 2 red at an arm_j
  M_LC_LATE_SOP     an extra 40-cycle nop before a handshake copy's arm_sop -> next-SOP red
  M_LC_SHIFTI_FULL  spacing_of reads SHIFTI's whole delay field   -> check 1 red
  M_LC_LAT_IGNORED  the certificate's lateness ignored on deadline chains -> check 2 green on a
                    known-late image (the gate must notice it lost its teeth)
  check 3  FALLTHROUGH (ArmFT, F4): usbdev with one handshake copy's arm_sop made FALLTHROUGH
           must be refused (its PC+2 is the first receive SHIFTIN), its first sample must be
           late by the flush refill (flush_head_refill), and on a HALF lane refused again
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
            bit = getattr(I, "ARM_MOD_FALLTHROUGH", 0)
            p[w - base] = I.act(x["op"], x["pin"], x["level"], 500, count=x["count"], q=x["q"],
                                pinb=x["pinb"], mod=x["mod"] | bit)
            return p, w
    return None, None


def check_ft(LC, V, I):
    p, w = ft_program(LC, V, I)
    if p is None:
        return False, "no handshake arm_sop with a SHIFTIN at PC+2 to test on"
    fails, _o = run_cert(LC, V.image(prog=p))
    refused = any(f[0] == "FT" and f[1].startswith("w%d PC+2" % w) for f in fails)
    floored = any(f[1] == "first sample after w%d" % w for f in fails)
    orig_rh = I.read_header

    def half_rh(img, ln):
        h = orig_rh(img, ln)
        if ln == I.USB_LANE:
            h = dict(h, flags=h["flags"] | I.FLAG_HALF_HIGH)
        return h
    I.read_header = half_rh
    try:
        fh, _o = run_cert(LC, V.image(prog=p))
    finally:
        I.read_header = orig_rh
    halfed = any(f[0] == "FT" and "HALF" in f[1] for f in fh)
    ok = refused and floored and halfed
    return ok, ("arm_sop w%d made FALLTHROUGH: PC+2 refused %s, first sample late by the flush %s, "
                "HALF refused %s" % (w, refused, floored, halfed))


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
    kills = []
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
            hit = any(x[1].startswith("next-SOP") and x[1] not in {y[1] for y in fails}
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
    f, _o = run_cert(LC, V.image())
    LC.certificate = orig_cert
    lost = len(f) < len(fails)
    kills.append(("M_LC_LAT_IGNORED", lost or not fails,
                  "lateness ignored: failures %d -> %d" % (len(fails), len(f))))
    for name, killed, what in kills:
        print("  must-fire %-18s %s  %s" % (name, "RED (killed)" if killed else "SURVIVED", what))
    teeth = all(k for _n, k, _w in kills)
    green = ok1 and not fails and ok3
    verdict = "PASSED" if (green and teeth) else ("FAILED (must-fire survived)" if not teeth
                                                   else "FAILED")
    print("GATE lane-cert: %s" % verdict)
    return 0 if verdict == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main())
