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
    # Wilson 11-13: the USB lane's D_sched must sit this far below every other live lane's
    # for J <= 2 (EdfUsb.lean usb_wins / usb_j2: a lane beating the ready USB lane would have
    # waited more than R_usb). Sufficient, worst case; 9 measured on one periodic config.
    k["usb_deadline_margin"] = k["R_usb"]
    # Wilson 11-13, revised no-stall ruling (UsbNoStall.lean usb_nostall / usb_br1_window): the
    # USB lane may take branch 1 on any retirement; at most usb_br1_per_window of them in any
    # 23 + br1_budget window (proved), each costing another lane's refill one l_refill (read:
    # SCAN -> REQ -> WAIT -> CAP, pe_engine.v l.2703).
    k["dstar"] = k["n_lanes"] * k["l_refill"]
    k["br1_budget"] = k["usb_br1_per_window"] * k["l_refill"]
    k["coresident_usb"] = k["R_usb"] + k["pending_slack"] + k["br1_budget"]
    k["coresident_min_d"] = k["dstar"] + k["br1_budget"]
    if k["coresident_usb"] < k["coresident_min_d"]:
        raise ValueError("proof_constants: coresident_usb %d no longer implies the co-resident "
                         "delay floor coresident_min_d %d (head_valid_ret's D* + B)"
                         % (k["coresident_usb"], k["coresident_min_d"]))
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


def lane_words(img, lane, I=None):
    """[(word index, action dict)] for EVERY word reachable from `lane`'s base: the next word,
    a branch's target, a looping REARM back to the base (a chaining REARM ends the walk).
    pe_isa.lane_programs stops at the first REARM, which under-checks a program with several
    sections reached by branches (usbdev.py's device program); this walks them all."""
    I = I or _isa()
    h = I.read_header(img, lane)
    nwords = (I.STORE_BYTES - I.ACT_BASE) // I.ACT_BYTES
    seen, todo, out = set(), [h["base_word"]], []
    while todo:
        w = todo.pop()
        a = I.ACT_BASE + w * I.ACT_BYTES
        if w in seen or not 0 <= w < nwords or a + I.ACT_BYTES > len(img):
            continue
        seen.add(w)
        x = I._unpack(I.ACT_FIELDS, img[a:a + I.ACT_BYTES], I.ACT_BYTES)
        out.append((w, x))
        if x["op"] == I.OP_REARM:
            continue                      # looping: back to the base (seen); chaining: parks
        todo.append(w + 1)
        if x["op"] in I.BRANCH_OPS:
            todo.append(I.branch_target(x))
    return sorted(out, key=lambda p: p[0])


def usb_coresident_problems(img, k=None):
    """[problem] for an image that turns on the USB receive and has another lane with a
    positive per-action spacing below coresident_usb (Wilson 11-13, revised no-stall ruling:
    UsbNoStall.lean usb_nostall, hypothesis `CORESIDENT_USB <= P.dly l` for every other live
    lane; coresident_usb = R_usb + pending_slack + br1_budget, which also implies the delay
    floor coresident_min_d). Every word reachable from each lane is checked (lane_words).
    THE ONE CHECK: the compiler and gate_admissible_images both call this."""
    I = _isa()
    k = k or load()
    progs = I.lane_programs(img)
    if not usb_receive_live(progs, I):
        return []
    lim, out = k["coresident_usb"], []
    for ln in range(I.N_LANES):
        if ln == I.USB_LANE:
            continue
        for w, x in lane_words(img, ln, I):
            s = spacing_of(x, I)
            if 0 < s < lim:
                out.append("lane %d word %d: spacing %d < %d -- in an image using the USB "
                           "receive, every other lane's per-action spacing must be >= R_usb + "
                           "pending_slack + br1_budget = %d + %d + %d (usb_nostall). A lane that "
                           "needs actions faster than %d cycles (fast SPI, for instance) cannot "
                           "share an image with the USB receive"
                           % (ln, w, s, lim, k["R_usb"], k["pending_slack"], k["br1_budget"], lim))
    return out


if __name__ == "__main__":
    for a, b in sorted(load().items()):
        print("%-20s %s" % (a, b))
