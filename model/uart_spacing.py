"""uart_spacing -- the UART receive lane's pre-ARM spacing, GENERATED (Wilson 11-15, call 1).

The UART receive loop re-arms its ARM a fixed few dispatches after the stop sample (stop
SHIFTIN, REARM). Beside busy lanes that ARM is late, its late words charge the branch-1 budget
B for every lane, and lanes spaced at D* then never certify (b3b: B = 8). Spacing before the ARM
(more delay on the word(s) that precede it in the loop) drains that lateness; too much makes the
ARM armed after the next start edge can be seen, which arm_gate's margin refuses (7b4a6f1).

Like the drain (host/poset/compile.windows), the spacing is generated, never typed:

  plan(img, ready=None)  per UART receive lane (branch_budget.arm_gate's shape), the LEAST pad
                         (0 .. the lane's back-to-back limit) at which EVERY lane of the image
                         certifies at J 1 (as A2 quotes it: J over pin words). The limit is generated: the arming margin at pad 0
                         with zero lateness -- a larger pad leaves the ARM armed after the next
                         start edge can be seen.
  space(img, ready=None, nospacing=False) -> (image, plan)
                         the image with the planned pad applied; nospacing=True returns it
                         unchanged (stamp it with opt_out_stamp). A certificate that needs a pad
                         PAST the limit is Refused, naming both numbers.
  opt_out_stamp(st, plan)  the stamp for `nospacing`: UNCERTIFIED with the reason
  fastest_bit(pad)       the fastest bit period (cycles) at which the standalone receive program
                         (test/uart_rx.py) certifies, with that pad -- the spacing's cost
`ready` is branch_budget.image_budget's prefetch knob (item 1b), for images that also need it
(b3b's SPI-target lane). Static; the certificate only.

For agent 1's builders (test/uart_rx.py, test/make_smoke_image.py --b3b):
    img, p = uart_spacing.space(img)              # or nospacing=True
    st = cert_stamp.stamp(img); st = uart_spacing.opt_out_stamp(st, p) if p["opt_out"] else st
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(HERE, "a2"), os.path.join(ROOT, "test")):
    if _p not in sys.path:
        sys.path.append(_p)

#: must-fire switch (gate_uart_spacing M_US_NO_LIMIT): the back-to-back limit not enforced
NO_LIMIT_MUT = False


class Refused(Exception):
    pass


def uart_lanes(img):
    """{lane: (ARM word, [the words before it in the loop])} for every UART receive lane"""
    import branch_budget as BB
    import lane_cert as LC
    import proof_constants as PC
    I = LC._isa()
    prem = LC.premises(PC.load())
    out = {}
    for ln in sorted(I.lane_programs(img)):
        g, preds, gaps = LC.build(img, ln, prem, I)
        ag = BB.arm_gate(img, ln, (g, preds, gaps), {w: 0 for w in g}, I)
        for arm in sorted(ag):
            out[ln] = (arm, list(preds[arm]), ag[arm])
    return out


def apply(img, lane, pad, ul=None):
    """the image with `pad` cycles added to the word(s) before lane's UART ARM"""
    import lane_cert as LC
    I = LC._isa()
    ul = ul or uart_lanes(img)
    out = bytearray(img)
    for q in ul[lane][1]:
        a = I.ACT_BASE + q * I.ACT_BYTES
        x = I._unpack(I.ACT_FIELDS, bytes(out[a:a + I.ACT_BYTES]), I.ACT_BYTES)
        if x["delay"] + pad > (1 << I.DLY_W) - 1:
            raise Refused("UART spacing: lane %d word %d's delay %d + %d > %d"
                          % (lane, q, x["delay"], pad, (1 << I.DLY_W) - 1))
        out[a:a + I.ACT_BYTES] = I.act(x["op"], x["pin"], x["level"], x["delay"] + pad,
                                       count=x["count"], q=x["q"], pinb=x["pinb"], mod=x["mod"])
    return bytes(out)


def _all_j1(bb):
    """every lane at J 1 as A2 quotes it: J over pin words (branch_budget.lane_j_pin; NopSplit /
    ArmSplit), whole-lane J where no pin-word figure is recorded (the USB lane)"""
    if bb["B"] is None:
        return False
    return all((v["max_late_pin"] if v.get("max_late_pin") is not None else v["max_late"]) == 0
               for v in bb["lanes"].values())


def plan(img, ready=None):
    import branch_budget as BB
    img = bytes(img)
    ul = uart_lanes(img)
    res = {"lanes": {}, "certified": None, "opt_out": False}
    if not ul:
        res["certified"] = _all_j1(BB.image_budget(img, ready=ready))
        return res
    for ln, (arm, _pre, margin0) in sorted(ul.items()):
        limit = max(margin0, 0)
        found = None
        for pad in range(0, limit + 1):
            bb = BB.image_budget(apply(img, ln, pad, ul), ready=ready)
            if _all_j1(bb):
                found = pad
                break
        beyond = None
        if found is None:
            # what a certificate would need if the back-to-back limit were ignored
            old = BB.ARMMARGIN_MUT
            BB.ARMMARGIN_MUT = True
            try:
                for pad in range(limit + 1, limit + 201):
                    try:
                        bb = BB.image_budget(apply(img, ln, pad, ul), ready=ready)
                    except Refused:
                        break
                    if _all_j1(bb):
                        beyond = pad
                        break
            finally:
                BB.ARMMARGIN_MUT = old
        res["lanes"][ln] = {"arm": arm, "limit": limit, "spacing": found, "beyond": beyond}
    return res


def space(img, ready=None, nospacing=False):
    p = plan(img, ready)
    if nospacing:
        return bytes(img), dict(p, opt_out=True)
    out = bytes(img)
    for ln, v in sorted(p["lanes"].items()):
        if v["spacing"] is None and v["beyond"] is not None and not NO_LIMIT_MUT:
            raise Refused("UART spacing: lane %d needs %d cycles before its ARM, past the "
                          "back-to-back limit of %d (the ARM would be armed after the next "
                          "start edge can be seen)" % (ln, v["beyond"], v["limit"]))
        pad = v["spacing"] if v["spacing"] is not None else (
            v["beyond"] if NO_LIMIT_MUT and v["beyond"] is not None else 0)
        if pad:
            out = apply(out, ln, pad)
    return out, p


def opt_out_stamp(st, p):
    need = ", ".join("lane %d: %s" % (ln, v["spacing"]) for ln, v in sorted(p["lanes"].items()))
    return dict(st, status="uncertified",
                reason="UART pre-ARM spacing opted out (nospacing); the generated spacing would "
                       "be %s" % (need or "none (no UART receive lane)"))


def fastest_bit(pad, t_lo=None, t_hi=None):
    """the smallest bit period T (cycles) at which test/uart_rx.py's receive program, with `pad`
    before its ARM, certifies (every lane J 1, arming margin >= 0)"""
    import branch_budget as BB
    import pe_asm
    import uart_rx
    t_lo = t_lo or uart_rx.T_MIN
    t_hi = t_hi or uart_rx.T_NOMINAL
    for t in range(t_lo, t_hi + 1):
        img = bytes(pe_asm.assemble(*uart_rx.lanes_headers(t)))
        ul = uart_lanes(img)
        if not ul:
            continue
        try:
            im = apply(img, sorted(ul)[0], pad, ul) if pad else img
        except Refused:
            continue
        if _all_j1(BB.image_budget(im)):
            return t
    return None
