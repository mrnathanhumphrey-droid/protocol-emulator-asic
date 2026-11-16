"""gate_uart_spacing -- the UART pre-ARM spacing, generated (Wilson 11-15, call 1).

The case: test/uart_rx.py's receive program on lane 0 beside four lanes spaced 25, 30, 45, 87
(the shape of b3b's busy neighbours): uncertified as built (the UART ARM's lateness charges B).

  U1 THE DEFAULT certifies: uart_spacing.space adds the least pad (generated, today 22 at the
     115200-baud bit) and every lane certifies at J 1 (pin words); one cycle less does not
  U2 NODRAIN'S TWIN: nospacing=True returns the image unchanged and opt_out_stamp stamps it
     UNCERTIFIED, the reason naming the spacing the default would have used
  U3 THE PROTOCOL CHECK: at a 250-cycle bit the certificate needs 22 cycles but the back-to-back
     limit is 13 -- space() is Refused, naming both numbers
  U4 an image with no UART receive lane is byte-identical after space()
Report: the fastest bit period the standalone receive program certifies, with and without the
generated spacing (the spacing's cost as a number).
Must-fire: M_US_NO_LIMIT (the limit not enforced -> U3 compiles -> red).
POSITIVE TOKEN: `GATE uart_spacing: PASSED`.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(HERE, "a2"), os.path.join(ROOT, "test")):
    if _p not in sys.path:
        sys.path.append(_p)
import uart_spacing as US  # noqa: E402

#: the busy neighbours' spacings (b3b's shape) and the bit period of the U3 case
BUSY = (25, 30, 45, 87)
T_TIGHT = 250


def busy_image(t=None):
    import pe_asm
    import pe_isa as I
    import uart_rx
    lanes, hdr = uart_rx.lanes_headers(t or uart_rx.T_NOMINAL)
    for ln, p, d in zip((1, 2, 3, 4), (I.UO0, I.UO0 + 1, I.UO0 + 2, I.UO0 + 3), BUSY):
        lanes[ln] = [(I.OP_LEVEL, p, 1, d, 0), (I.OP_LEVEL, p, 0, d, 0), (I.OP_REARM, 0, 1, d, 0)]
        hdr[ln] = (p, I.PIN_NONE, 1, d, d, 2 * d)
    return bytes(pe_asm.assemble(lanes, hdr))


def judge():
    import branch_budget as BB
    import cert_stamp as CS
    probs, info = [], {}
    img = busy_image()
    if US._all_j1(BB.image_budget(img)):
        probs.append("U1 the case certifies without spacing: no test")
    out, p = US.space(img)
    pad = p["lanes"][0]["spacing"] if 0 in p["lanes"] else None
    info["pad"] = pad
    if pad is None or not US._all_j1(BB.image_budget(out)):
        probs.append("U1 the default does not certify (plan %s)" % p["lanes"])
    elif pad and US._all_j1(BB.image_budget(US.apply(img, 0, pad - 1))):
        probs.append("U1 %d is not the least spacing" % pad)
    same, p2 = US.space(img, nospacing=True)
    st = US.opt_out_stamp(CS.stamp(same), p2)
    if same != img or st["status"] != "uncertified" or "nospacing" not in st["reason"]:
        probs.append("U2 nospacing: image changed %s, stamp %s" % (same != img, st))
    try:
        US.space(busy_image(T_TIGHT))
        probs.append("U3 a spacing past the back-to-back limit was not refused")
    except US.Refused as e:
        info["U3"] = str(e)
        lim = US.plan(busy_image(T_TIGHT))["lanes"][0]
        if str(lim["beyond"]) not in str(e) or str(lim["limit"]) not in str(e):
            probs.append("U3 refused without naming both numbers: %s" % e)
    import gen_branch_budget as GB
    plain = dict(GB.corpus())["sptgt_m0_image.hex"]
    if US.space(plain)[0] != plain:
        probs.append("U4 an image with no UART receive lane changed")
    return probs, info


def main():
    import clock
    probs, info = judge()
    print("U1 the default spacing certifies the busy UART case: %s cycles" % info.get("pad"))
    print("U3 refusal: %s" % info.get("U3", "-"))
    t0, t1 = US.fastest_bit(0), US.fastest_bit(info.get("pad") or 0)
    print("fastest certifiable bit (standalone receiver): no spacing %s cycles (%.0f baud); "
          "with %s: %s cycles (%.0f baud)" % (t0, clock.hz() / t0, info.get("pad"), t1,
                                              clock.hz() / t1))
    for p in probs:
        print("  ***", p)
    US.NO_LIMIT_MUT = True
    try:
        mp, _ = judge()
    finally:
        US.NO_LIMIT_MUT = False
    red = any(m.startswith("U3") for m in mp)
    print("  must-fire M_US_NO_LIMIT %s" % ("RED (killed)" if red else "*** SURVIVED"))
    if not red:
        probs.append("mutant M_US_NO_LIMIT survived")
    print("GATE uart_spacing: %s" % ("PASSED" if not probs else "FAILED (%d)" % len(probs)))
    return 1 if probs else 0


if __name__ == "__main__":
    raise SystemExit(main())
