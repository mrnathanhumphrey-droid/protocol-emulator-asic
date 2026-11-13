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


def blocks():
    k = PC.load()
    return {
        "usb_coresident": (
            "**In an image using the USB receive, every other lane's per-action spacing is "
            "≥ %d cycles** (a branch's wait W counts as its spacing). Why: the USB lane's "
            "re-anchor can bring its next release as close as %d + ⌊d/%d⌋ cycles (%d at d = 40), "
            "so it may be decided twice inside one %d-cycle Lemma-A window. The response bound "
            "becomes R = %d + %d = %d instead of %d, and the no-stall theorem then needs "
            "d ≥ R + %d = %d on every co-resident lane (Wilson 11-12, option (i)). The compiler "
            "refuses a program that breaks this, by name; the A2 certificate records the threshold."
            % (k["dstar_retire_usb"], k["rean_pipe"], k["rean_halving"], PC.rean_floor(40, k),
               k["lemmaA_window"], k["R_base"], k["dispatch_cycles"] * k["usb_extra_decisions"],
               k["R_usb"], k["R_base"], k["pending_slack"], k["dstar_retire_usb"])),
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
