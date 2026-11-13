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


def _opname(op, I):
    return {v: n for n, v in I.OPCODES.items()}.get(op, "op%d" % op)


def word_timing(x, h, ln, usb_live, k=None, I=None):
    """One action word as lean/JLane/JLane/StRetire.lean sees it ->
    {kind, lx, dly, nominal}:
      kind  'st' (self-timed: SHIFT/SHIFTIN with mod[1], or SHIFTI, on a clockless lane --
            pe_engine.v l.1222 C_ST, l.2035 st_act = C_ST & ~clk_real, clk_real = clkpin <
            N_PINS l.1966), 'branch' (W; outside the proven fragment, Wilson 11-13 Question A),
            'arm' (outside the model), else 'plain'
      lx    held bits the word claims: st_lastix (l.2036: SHIFT / SHIFTI a_cnt, SHIFTI's fixed
            at 7 l.1895; SHIFTIN a_cnt - 1); the buffer send's last bit is the buffer length
            (l.2093), so it claims 0; every other kind 0
      dly   the writeback delay the model charges: a USB receive bit is re-anchored, so its
            floor rean_floor(delay) (ReanFloorModel); a branch its W; else the delay field
            (SHIFTI: its low 8 bits, the rest is the byte)
      nominal  the same without the re-anchor"""
    I = I or _isa()
    k = k or load()
    op, st_mod = x["op"], x["mod"] & I.MOD_SELF_TIMED
    clockless = h["clkpin"] >= I.N_PINS
    on_usb = usb_live and ln == I.USB_LANE
    if op in I.BRANCH_OPS:
        kind, d = "branch", I.branch_wait(x)
    elif op == I.OP_ARM:
        kind, d = "arm", x["delay"]
    elif clockless and (op == I.OP_SHIFTI or (op in (I.OP_SHIFT, I.OP_SHIFTIN) and st_mod)):
        kind, d = "st", (x["delay"] & 0xFF) if op == I.OP_SHIFTI else x["delay"]
    else:
        kind, d = "plain", x["delay"]
    lx = 0
    if kind == "st":
        if on_usb and op == I.OP_SHIFT and x["q"] == I.USB_BUF_Q:
            lx = 0
        elif op == I.OP_SHIFTI:
            lx = 7
        elif op == I.OP_SHIFT:
            lx = x["count"]
        else:
            lx = max(x["count"] - 1, 0)
    usb_rx = on_usb and kind == "st" and op == I.OP_SHIFTIN and x["level"]
    return {"kind": kind, "lx": lx, "dly": min(d, rean_floor(d, k)) if usb_rx else d,
            "nominal": d, "name": _opname(op, I) + ("-usb" if usb_rx else "")}


def retire_pairs(img, lane, k=None):
    """Every consecutive-retirement pair of `lane`'s program, in program order (Wilson 11-13):
    the earlier word's last writeback delay plus the next word's held bits, each at its delay,
    -> [{a, b, w1, w2, spacing, nominal, lim, status}] with word indices absolute.
    status 'ok' (spacing >= lim), 'short', or 'outside' (the earlier word is an ARM: its
    writeback is not in the model -- the branch-semantics brick).
    lim = R + pending_slack: dstar_retire_usb in an image with the USB receive, else
    dstar_retire. Successors: the next word; a looping REARM's is the lane's first word (a
    chaining REARM ends the program: no pair); a branch has both its next word and its target.
    The Lean side (StRetire.lean, PairCond) states the same sum over the run's consecutive
    retirements; the two agree when words reach the head in program order (named there)."""
    I = _isa()
    k = k or load()
    progs = I.lane_programs(img)
    live = usb_receive_live(progs, I)
    lim = k["dstar_retire_usb"] if live else k["dstar_retire"]
    h, acts = progs[lane]
    tw = [word_timing(x, h, lane, live, k, I) for x in acts]
    out = []
    for i, x in enumerate(acts):
        succ = []
        if x["op"] == I.OP_REARM:
            if x["level"]:
                succ = [0]
        else:
            if i + 1 < len(acts):
                succ.append(i + 1)
            if x["op"] in I.BRANCH_OPS:
                t = I.branch_target(x) - h["base_word"]
                if 0 <= t < len(acts) and t not in succ:
                    succ.append(t)
        for j in succ:
            a, b = tw[i], tw[j]
            sp = a["dly"] + b["lx"] * b["dly"]
            nom = a["nominal"] + b["lx"] * b["nominal"]
            st = "outside" if a["kind"] == "arm" else ("ok" if sp >= lim else "short")
            out.append({"a": h["base_word"] + i, "b": h["base_word"] + j, "w1": a["name"],
                        "w2": b["name"], "spacing": sp, "nominal": nom, "lim": lim, "status": st})
    return out


def pair_problems(img, lane, k=None):
    """[problem] for every pair of `lane` that is not 'ok' -- the per-pair rule's one wording."""
    k = k or load()
    out = []
    for p in retire_pairs(img, lane, k):
        if p["status"] == "short":
            out.append("lane %d pair word %d (%s) -> word %d (%s): spacing %d (%d nominal) < %d -- "
                       "the earlier word's last writeback delay plus the next word's held bits "
                       "must be >= R + pending_slack (Wilson 11-13, per pair)"
                       % (lane, p["a"], p["w1"], p["b"], p["w2"], p["spacing"], p["nominal"],
                          p["lim"]))
        elif p["status"] == "outside":
            out.append("lane %d pair word %d (%s) -> word %d (%s): outside the model (ARM's "
                       "writeback is not in the proven fragment; the branch-semantics brick) -- "
                       "not certifiable" % (lane, p["a"], p["w1"], p["b"], p["w2"]))
    return out


def usb_coresident_problems(img, k=None, pairs=True):
    """[problem] for an image that turns on the USB receive and has another lane with a
    positive per-action spacing below dstar_retire_usb (Wilson 11-12, option (i)), or a USB-lane
    retirement pair below it (Wilson 11-13, per pair; `pairs=False` is the compiler's mutant
    hook, M_PC_PAIRS_NOCHECK). THE ONE CHECK: the compiler and gate_admissible_images both call
    this. The other lanes keep the per-action rule: dstar_usb_pairs (Lean) still takes
    `dly >= DSTAR_RETIRE_USB` for them."""
    I = _isa()
    k = k or load()
    progs = I.lane_programs(img)
    if not usb_receive_live(progs, I):
        return []
    lim, out = k["dstar_retire_usb"], []
    if pairs:
        out += pair_problems(img, I.USB_LANE, k)
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
