"""proof_constants -- the proof's thresholds, DERIVED from the primitives in
lean/JLane/proof_constants.json (Wilson 11-12: one source, never typed).

    R_usb             = R_base + dispatch_cycles * usb_extra_decisions        (17)
    noWB_min          = R_usb + dispatch_cycles                                (20)
    dstar_retire      = R_base + pending_slack     (no re-anchoring lane)      (39)
    dstar_retire_usb  = R_usb + pending_slack      (co-resident with USB)      (42)
    rean_floor(d)     = rean_pipe + d // rean_halving                          (23 at d = 40)

The Lean side pins every value with an `rfl` lemma (Params.lean); gate_lean_build compares.
"""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(os.path.dirname(HERE), "lean", "JLane", "proof_constants.json")


def load(path=PATH):
    with open(path) as fh:
        k = {a: b for a, b in json.load(fh).items() if not a.startswith("_")}
    k["R_usb"] = k["R_base"] + k["dispatch_cycles"] * k["usb_extra_decisions"]
    k["noWB_min"] = k["R_usb"] + k["dispatch_cycles"]
    k["dstar_retire"] = k["R_base"] + k["pending_slack"]
    k["dstar_retire_usb"] = k["R_usb"] + k["pending_slack"]
    return k


def rean_floor(d, k=None):
    k = k or load()
    return k["rean_pipe"] + d // k["rean_halving"]


def _isa():
    import sys
    t = os.path.join(os.path.dirname(HERE), "test")
    if t not in sys.path:
        sys.path.insert(0, t)
    import pe_isa
    return pe_isa


def usb_receive_live(progs, I=None):
    """the USB lane carries a USB receive (a self-timed SHIFTIN with level 1) -- the same
    predicate as pe_isa.usb_problems' `usb_live` (extraction into pe_isa requested, 11-12)"""
    I = I or _isa()
    return I.USB_LANE in progs and any(
        x["op"] == I.OP_SHIFTIN and x["mod"] & I.MOD_SELF_TIMED and x["level"]
        for x in progs[I.USB_LANE][1])


def spacing_of(x, I=None):
    """an action's dispatch spacing: a branch's wait W, else its delay (0 = none, skipped)"""
    I = I or _isa()
    return I.branch_wait(x) if x["op"] in I.BRANCH_OPS else x["delay"]


def usb_coresident_problems(img, k=None):
    """[problem] for an image that turns on the USB receive and has another lane with a
    positive per-action spacing below dstar_retire_usb (Wilson 11-12, option (i)).
    THE ONE CHECK: the compiler and gate_admissible_images both call this."""
    I = _isa()
    k = k or load()
    progs = I.lane_programs(img)
    if not usb_receive_live(progs, I):
        return []
    lim, out = k["dstar_retire_usb"], []
    for ln, (h, acts) in sorted(progs.items()):
        if ln == I.USB_LANE:
            continue
        for i, x in enumerate(acts):
            s = spacing_of(x, I)
            if 0 < s < lim:
                out.append("lane %d word %d: spacing %d < %d -- in an image using the USB receive, "
                           "every other lane's per-action spacing must be >= R_usb + pending_slack "
                           "= %d + %d (the USB lane may be decided twice per Lemma-A window, so the "
                           "response bound is %d, not %d)"
                           % (ln, h["base_word"] + i, s, lim, k["R_usb"], k["pending_slack"],
                              k["R_usb"], k["R_base"]))
    return out


if __name__ == "__main__":
    for a, b in sorted(load().items()):
        print("%-20s %s" % (a, b))
