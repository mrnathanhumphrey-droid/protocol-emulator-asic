#!/usr/bin/env python3
"""gen_spec_doc -- the generated passages of host/poset/POSET_SPEC.md (numbers never typed).

    python host/poset/gen_spec_doc.py --write   rewrite every <!-- gen:NAME --> ... <!-- /gen --> block
    python host/poset/gen_spec_doc.py           check only: exit 1 and name the block if stale

run_poset_compile's C8 arm calls `stale()`.
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "model"))
import proof_constants as PC  # noqa: E402

DOC = os.path.join(HERE, "POSET_SPEC.md")


def within_block(k):
    """the `within` lowering's limits, from the compiler's own constants (host/poset/compile.py)"""
    import clock
    import lane_cert as LC
    sys.path.insert(0, HERE)
    import compile as C
    hz = clock.hz()
    lead = C.WB_MIN + LC.SYNC_MIN - (C.ARMED_BY + 1)
    lo_min = k["dstar"] - lead
    return (
        "**Limits of `within` on this target (%d Hz).** The ARM's timeout is its 10-bit delay "
        "field: at most %d cycles (%.2f µs) from the ARM's release, so a window whose `hi` needs "
        "more is refused with \"%s\". The ARM must be armed before B can be seen: A's pin moves at "
        "its writeback, at least %d cycles after A's release; B is seen at least %d cycle(s) "
        "after it moves; the ARM is armed by its release + L + %d (L its certified lateness). "
        "So the ARM's lead after A is pre = lo − %d − L cycles, and pre must be at least D* = %d: "
        "**lo ≥ %d cycles (%.1f ns) at L = 0**, or the window is refused as too tight. The "
        "deadline covers a B at hi seen late: T = hi + L_A + %d + %d − pre (L_A, A's certified "
        "lateness). Every number here is the compiler's own constant or `proof_constants.json`'s."
        % (hz, C.T_MAX, C.T_MAX * 1e6 / hz, C.NEEDS_COUNTER, C.WB_MIN, LC.SYNC_MIN, C.ARMED_BY,
           -lead, k["dstar"], lo_min, lo_min * 1e9 / hz, C.ARMED_BY, LC.SYNC_MAX))


def blocks():
    k = PC.load()
    return {
        "within_limits": within_block(k),
        "usb_coresident": (
            "**In an image using the USB receive, every other lane's per-action spacing is "
            "≥ %d cycles** (a branch's wait W counts as its spacing; every word reachable from "
            "the lane is checked). So a protocol lane that needs actions faster than %d cycles "
            "(fast SPI, for instance) cannot share a chip image with the USB receive. Why: with "
            "the USB program co-resident, another lane's writeback can come up to R = %d cycles "
            "after its release (%d without the USB lane). R is certified, not typed: "
            "`model/lane_cert.py` evaluates `RespSpan.wb_close_span` on the USB program -- the "
            "USB lane's re-anchor can bring its next release as close as %d + ⌊d/%d⌋ cycles "
            "(%d at d = 40), its FALLTHROUGH flush path raises its worst response, and its "
            "disarm cycles count as idle -- and `model/gen_cert_constants.py` writes it to "
            "`proof_constants.json`. The USB lane may also take the slower refill path "
            "(branch 1) at most %d times in any %d-cycle window, each costing another lane's "
            "refill %d cycles (budget B = %d). The no-stall theorem (`usb_nostall`) then needs "
            "d ≥ R + %d + B = %d on every co-resident lane (Wilson 11-13; R certified, Wilson "
            "11-14). The compiler refuses a program that breaks this, by name; the A2 "
            "certificate records the threshold."
            % (k["coresident_usb"], k["coresident_usb"], k["usb_other_R"], k["R_base"],
               k["rean_pipe"], k["rean_halving"], PC.rean_floor(40, k),
               k["usb_br1_per_window"], k["pending_slack"] - 2 + k["br1_budget"], k["l_refill"],
               k["br1_budget"], k["pending_slack"], k["coresident_usb"])),
    }


def render(text):
    for name, body in blocks().items():
        # an empty block, a filled one, LF or CRLF
        pat = re.compile(r"<!-- gen:%s -->.*?<!-- /gen -->" % re.escape(name), re.S)
        if not pat.search(text):
            raise ValueError("POSET_SPEC.md: no <!-- gen:%s --> block" % name)
        nl = "\r\n" if "\r\n" in text else "\n"
        text = pat.sub(lambda m: "<!-- gen:%s -->%s%s%s<!-- /gen -->" % (name, nl, body, nl), text)
    return text


def stale():
    with open(DOC, encoding="utf-8", newline="") as f:
        text = f.read()
    return [] if render(text) == text else ["POSET_SPEC.md generated block(s) stale: run "
                                            "host/poset/gen_spec_doc.py --write"]


if __name__ == "__main__":
    if "--write" in sys.argv:
        # render FIRST (it raises on a missing block); then write a temp file and rename it
        # over the doc, so a failure can never leave POSET_SPEC.md truncated
        with open(DOC, encoding="utf-8", newline="") as f:
            t = f.read()
        out = render(t)
        tmp = DOC + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(out)
        os.replace(tmp, DOC)
        print("written" if out != t else "unchanged")
    else:
        p = stale()
        print(p[0] if p else "POSET_SPEC.md generated blocks current")
        sys.exit(1 if p else 0)
