"""live_price -- price a program assembled AT RUN TIME (Wilson 11-15, item 5).

The generated record (model/branch_budget.json) covers the image universe. A program assembled
at run time -- the PIT round trip's emulation, a compiler output, a builder called with new
parameters -- has no record entry, so the stamp's R lookup finds nothing and the image reads
"UNCERTIFIED: no budget record". Wilson: price them live and put the stamp in the report.

`price(img)` evaluates the SAME certificate the record generator writes
(gen_branch_budget.current -> branch_budget.image_budget, cert_stamp.stamp with that budget),
on the image's bytes, now. For an image that IS in the record the result equals the record's
entry (gate_live_price L1). Static: the certificate only, no simulation; ~0.1 s an image.

Result: {"source": "live", "stamp", "B", "reason", "J": {lane: J}, "J_pin": {lane: J or None}}
  J      1 + the lane's certified lateness (branch_budget.lane_j)
  J_pin  the observable J over pin words (branch_budget.lane_j_pin; NopSplit / ArmSplit)
`line(p)` is the one-line form a report prints.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(HERE, "a2"), os.path.join(ROOT, "test")):
    if _p not in sys.path:
        sys.path.append(_p)

#: must-fire switch (gate_live_price M_LP_RECORD_ONLY): price from the record lookup only
RECORD_ONLY_MUT = False


def price(img):
    import branch_budget as BB
    import cert_stamp as CS
    img = bytes(img)
    if RECORD_ONLY_MUT:
        st = CS.stamp(img)
        return {"source": "record lookup", "stamp": st, "B": None, "reason": st["reason"],
                "J": {}, "J_pin": {}}
    r = BB.image_budget(img)
    st = CS.stamp(img, budget=r)
    entry = {"B": r["B"], "lanes": {str(l): v for l, v in r["lanes"].items()}}
    lanes = sorted(r["lanes"])
    return {"source": "live", "stamp": st, "B": r["B"], "reason": r["reason"],
            "J": {l: BB.lane_j(entry, l) for l in lanes},
            "J_pin": {l: BB.lane_j_pin(entry, l) for l in lanes}}


def line(p):
    """the report's one line"""
    import cert_stamp as CS
    if p["B"] is None:
        a2 = "A2-UNCERTIFIED: %s" % p["reason"]
    else:
        a2 = "A2 B = %d; %s" % (p["B"], ", ".join(
            "lane %d J %s" % (l, p["J_pin"].get(l) or p["J"][l]) for l in sorted(p["J"])))
    return "priced %s -- %s; %s" % (p["source"], CS.line(p["stamp"]), a2)
