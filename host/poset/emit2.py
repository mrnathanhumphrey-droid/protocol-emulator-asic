"""poset emit2 -- EMITTER v2: PIT results bytes + the host golden's order-and-bounds records
-> one poset spec (host/poset/POSET_SPEC.md).

The v1 part is emitter v1's own text, unchanged (model/pit_emit.emit): the chip's claims only.
The v2 part is appended inside the same `spec sniff` block. It holds:
  * ORDER / BOTH records -> their `pattern` statements (every bound `observed n`)
  * VIOLATION / ABSTAIN  -> v1-style `? unknown order.<A>.<B> -- <reason>;` lines,
    never a pattern. An order that broke, or was never seen, is not a claim.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import golden  # noqa: E402
import spec  # noqa: E402
from spec import pit_emit  # noqa: E402

HEAD = "  -- order and bounds: host golden over the capture; every bound observed"


def _field(r):
    return "order.%s.%s" % (golden.name(r["a"]).replace(" ", ""), golden.name(r["b"]).replace(" ", ""))


def emit2(results, records, clock_hz=None):
    v1 = pit_emit.emit(results, clock_hz).rstrip("\n").splitlines()
    if not v1 or v1[-1].strip() != "end sniff;":
        raise ValueError("emitter v1 text does not end with `end sniff;`")
    add = [HEAD]
    for r in records:
        if r["verdict"] in ("ORDER", "BOTH"):
            add.append("  " + r["text"])
        elif r["verdict"] == "VIOLATION":
            add.append("  ? unknown %s -- %s %s violated in %d of %d instance pairs;"
                       % (_field(r), r["op"], "order", r["violations"], r["n"] + r["violations"]))
        else:
            add.append("  ? unknown %s -- no evidence (no instance pair seen);" % _field(r))
    return "\n".join(v1[:-1] + add + [v1[-1]]) + "\n"
