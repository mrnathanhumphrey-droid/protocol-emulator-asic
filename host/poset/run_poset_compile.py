#!/usr/bin/env python3
"""run_poset_compile -- the gate for the compiler skeleton (host/poset/compile.py).

  C1 the end-to-end slice: emitter v2's SPI spec (v1 SPI image + golden records) compiles;
     the image is BYTE-IDENTICAL to run_pit_rt.emulation on the same parsed claims and seed
     (one source, no second lowering); width 1; words used <= 120; the WINDOW predicate in
     cycles equals the golden's own min / max for that bus; the cert says OWED / UNCERTIFIED
  C2 a cycle (A -> B, B -> A) is refused, naming the cycle
  C3 six independent chains are refused, naming the Dilworth width 6 > 5
  C4 Dilworth on a DAG where a path cover (3) is not a chain cover (2): width 2
  C5 a compound pattern is refused by name
  C6 a v1 spec the lowering cannot emulate is refused with the lowering's own reason
  C7 the USB co-resident threshold (Wilson 11-13, revised: coresident_usb = R_usb +
     pending_slack + br1_budget, usb_nostall): a USB image with a co-resident lane at
     coresident_usb - 1 is refused naming that lane and stating the restriction; at
     coresident_usb accepted with the threshold in the certificate; the same lane at - 1 in an
     image WITHOUT USB accepted; coresident_usb implies coresident_min_d
  C9 every reachable word is checked: a co-resident lane whose fast section (coresident_usb - 1)
     sits past its first REARM, reached only by a branch, is refused naming that word
  C10 `within (lo, hi) else abort | continue` (Wilson 11-15), on the SPI slice with B on an
     unconnected wire: one window per CS fall; READ BACK FROM THE IMAGE -- the ARM on the routed
     uio input, plain (abort) or FALLTHROUGH with a no-op PC+1 and a non-SHIFT PC+2 (continue);
     on the certified lateness, armed before B can be seen and a deadline covering a B at hi;
     the recorded lanes re-assemble to the image; a WINDOW predicate for the bound. Static
     must-fires, each refused BY NAME: too tight, a timeout over the 10-bit field and lo > 0
     without a datasheet bound ("needs window counter"), B on a wire we drive, A not ours, B
     not one edge; a window inside a LOOP body keeps every LOOP head on its action (UART TX)
     `else continue` is UNCERTIFIED by name (Wilson 11-16): the 1.6a queue check with the
     lateness in J -- FlushLate's PC+2 floor plus B accumulating on D*-spaced bit words; needs
     the FALLTHROUGH PC+2 prefetch (F1; Wilson 11-16, was "1b") -- each part generated from the
     certificate with the check off
  C11 the premise mechanism (Wilson 11-15 call 1, model/premises.py): a registered datasheet
     whose SHA-256 matches puts its ID in the stamp, the window certificate and A2's line, its
     gap in the certificate: certified at lane 0 lateness 0; a SHA mismatch or an unregistered
     part: image-only, UNCERTIFIED by the 1.6a check (Wilson 11-16)
  C10/C11 one input, one verdict (Wilson 11-16): every `within` compile's A2 line agrees with its
     window certificate's budget (must-fire M_PC_A2_NOPREM: A2 without the premise gaps)
  C12 ArmRetire (JLane/ArmRetire.lean): the SPI-master `else abort` window at 5 cycles of
     spacing certifies at J 1 (must-fire M_PC_ARMRETIRE_OFF: the cap off -> red)
  C13 the drain (Wilson 11-15): generated per window (the least drain certifying J 1), equal to
     the closed form on every window; the default certifies; `nodrain` stamps UNCERTIFIED; a
     next action bounded tighter than the drain is refused; no `within` -> byte-identical
     (must-fire M_PC_DRAIN_OFFBY1: the drain one past the search -> the closed form disagrees).
     The agreement is checked on the DEFAULT path (arm late) only: early arming is withdrawn.
     Wilson 11-20: also on every `else abort` / `else continue` window of the SPI-master and
     UART-TX lowerings, slot off and on (drain_closed_form_ft: the timeout path's refetched PC+2);
     `else continue` slot on: the default certifies J 1, `nodrain` stamps UNCERTIFIED, a tighter
     next action is refused (must-fire M_PC_FT_EDGEONLY: the drain on the edge path only)
  C14 arm='early' refused as withdrawn (the drain table alone uses it, counterfactual=True); more
     than MAX_PLAIN_ARM_RUN = 2 plain edge ARMs in a row refused (item 1b two deep; an FT ARM
     is outside the run) (must-fire M_PC_ARM3_PASS)
  C15 a FALLTHROUGH ARM at another ARM's PC+1 refused (plain, two-pin or FALLTHROUGH A; Wilson
     11-17: BufFifo has no theorem for it); one word between them compiles (must-fire
     M_PC_FTPC1_PASS)
Must-fires added 11-15: M_PC_WITHIN_LO_PASS (lo > 0 without a datasheet compiles), and pe_asm's
M_ASM_MOD_ANY_OP / M_ASM_MOD_ANY_VALUE (the mod field's two refusals), each killed by C10
Must-fires: every compile.MUTANTS entry, run IN-PROCESS through the same judge, turns this gate red.

POSITIVE TOKEN: `GATE poset_compile: PASSED`.
"""
from __future__ import annotations

import os
import random
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.join(ROOT, "test"))
import compile as C  # noqa: E402
import emit2 as E2  # noqa: E402
import golden as G  # noqa: E402
import run_poset_golden as RG  # noqa: E402
import run_pit_emit as V1T  # noqa: E402
from golden import key  # noqa: E402

#: gate_mutant_kills' scratch-mutant registry (ruling AC2): this gate is the killer
SCRATCH_MUTANTS = {
    "M_PC_NO_CYCLE": "killed in-process by this gate",
    "M_PC_NO_CLOSURE": "killed in-process by this gate",
    "M_PC_WINDOW_SWAP": "killed in-process by this gate",
    "M_PC_COMPOUND_PASS": "killed in-process by this gate",
    "M_PC_USB_NOCHECK": "killed in-process by this gate",
    "M_PC_JFLOOR_HEAD": "killed in-process by this gate",
    "M_PC_WITHIN_NOARM": "killed in-process by this gate",
    "M_PC_WITHIN_LO_PASS": "killed in-process by this gate",
    "M_PC_ARMRETIRE_OFF": "killed in-process by this gate (C12)",
    "M_PC_DRAIN_OFFBY1": "killed in-process by this gate (C13)",
    "M_PC_ARM3_PASS": "killed in-process by this gate (C14)",
    "M_PC_FTPC1_PASS": "killed in-process by this gate (C15)",
    "M_PC_A2_NOPREM": "killed in-process by this gate (C11: A2 and the window certificate disagree)",
    "M_PC_FT_EDGEONLY": "killed in-process by this gate (C13: else continue does not certify)",
    "M_ASM_MOD_ANY_OP": "pe_asm.MODS_MUT, killed in-process by this gate (C10)",
    "M_ASM_MOD_ANY_VALUE": "pe_asm.MODS_MUT, killed in-process by this gate (C10)",
}
#: the literal above must name exactly the module's MUTANTS (checked at start-up)
#: pe_asm's mod-field must-fires (Wilson 11-15: one per refusal), run in-process like C.MUTANTS
ASM_MUTANTS = ("M_ASM_MOD_ANY_OP", "M_ASM_MOD_ANY_VALUE")
if set(SCRATCH_MUTANTS) != set(C.MUTANTS) | set(ASM_MUTANTS):
    raise SystemExit("GATE poset_compile: FAILED -- SCRATCH_MUTANTS differs from C.MUTANTS")

HZ = G.clock.hz()
pit_emit = C.S.pit_emit


def body(*stmts):
    base = pit_emit.emit(bytes(V1T.IMAGES["spi"]()), HZ).rstrip("\n").splitlines()
    return "\n".join(base[:-1] + ["  " + s for s in stmts] + [base[-1]]) + "\n"


def usb_image(d_other, usb=True):
    """lane 0: a USB receive (or, without USB, plain LEVELs); lane 1: a co-resident lane whose
    every action is spaced `d_other`; lanes 2-4 parked. Shapes as run_usbrx.image()."""
    I = C.I
    D, DM = 40, 2                                   # the USB LS bit at 60 MHz; D- = uio[2]
    if usb:
        p0 = [I.act(I.OP_ARM, DM, 0, 0), I.act(I.OP_LEVEL, I.PIN_NONE, 0, D // 2),
              I.act_shiftin_usb(DM, D, 8), I.act_shiftin_usb(DM, D, 8),
              I.act(I.OP_REARM, 0, 1, D // 2)]
    else:
        p0 = [I.act(I.OP_LEVEL, I.PIN_NONE, 0, D)] * 3 + [I.act(I.OP_REARM, 0, 1, D)]
    p1 = [I.act(I.OP_LEVEL, I.UO0, 1, d_other), I.act(I.OP_LEVEL, I.UO0, 0, d_other),
          I.act(I.OP_REARM, 0, 1, d_other)]
    park = [I.act(I.OP_REARM, 0, 0, 500)]
    b0 = I.ACT_BASE
    b1 = b0 + len(p0) * I.ACT_BYTES
    bp = b1 + len(p1) * I.ACT_BYTES
    # the co-resident lane's D_sched is at least the USB lane's + the deadline margin
    # (pe_isa.usb_problems, usb_wins / usb_j2): C7 tests the action SPACING, not the deadline
    ds1 = max(d_other, 2 * D + I.usb_deadline_margin())
    hdrs = [I.hdr(DM, I.PIN_NONE, 1, D, 0, 2 * D, 3 * D, b0),
            I.hdr(I.UO0, I.UO0, 1, d_other, 0, ds1, ds1 + 20, b1)]
    hdrs += [I.hdr(n + 2, n + 2, 0, 500, 0, 200, 240, bp) for n in range(2, I.N_LANES)]
    return I.join_image(hdrs, p0 + p1 + park)


def multisection_image(lim):
    """the USB image's lane 0, and lane 1 with TWO sections: LEVEL / BRANCH_BIT / REARM (all at
    `lim`), then, reached only by the branch, LEVEL at `lim - 1` / REARM. -> (image, the fast
    word's index). pe_isa.lane_programs stops at lane 1's first REARM and never sees it."""
    I = C.I
    D, DM = 40, 2
    p0 = [I.act(I.OP_ARM, DM, 0, 0), I.act(I.OP_LEVEL, I.PIN_NONE, 0, D // 2),
          I.act_shiftin_usb(DM, D, 8), I.act(I.OP_REARM, 0, 1, D // 2)]
    b0 = I.ACT_BASE
    b1 = b0 + len(p0) * I.ACT_BYTES
    w1 = I.base_word(b1)
    p1 = [I.act(I.OP_LEVEL, I.UO0, 1, lim), I.act_branch_bit(DM, 1, w1 + 3, lim),
          I.act(I.OP_REARM, 0, 1, lim), I.act(I.OP_LEVEL, I.UO0, 0, lim - 1),
          I.act(I.OP_REARM, 0, 1, lim)]
    park = [I.act(I.OP_REARM, 0, 0, 500)]
    bp = b1 + len(p1) * I.ACT_BYTES
    ds1 = max(lim, 2 * D + I.usb_deadline_margin())   # the deadline margin, as usb_image
    hdrs = [I.hdr(DM, I.PIN_NONE, 1, D, 0, 2 * D, 3 * D, b0),
            I.hdr(I.UO0, I.UO0, 1, lim, 0, ds1, ds1 + 20, b1)]
    hdrs += [I.hdr(n + 2, n + 2, 0, 500, 0, 200, 240, bp) for n in range(2, I.N_LANES)]
    return I.join_image(hdrs, p0 + p1 + park), w1 + 3


def refused_with(text, needle):
    try:
        C.compile_spec(text)
    except C.Refused as e:
        return needle in str(e), str(e)
    return False, "compiled"


WIN = "pattern Fall(uio3) -> Fall(uio5) within (2000 ns, 10000 ns) else %s source datasheet \"X\";"
#: the static must-fires (Wilson 11-15 item (b)/(c), the proposal's three, and the shape rules)
WIN_REFUSE = {
    "window too tight": ("pattern Fall(uio3) -> Fall(uio5) within (300 ns, 10000 ns) else abort "
                         "source datasheet \"X\";", "window too tight"),
    "timeout over the 10-bit field": ("pattern Fall(uio3) -> Fall(uio5) within (2000 ns, 30000 ns) "
                                      "else abort source datasheet \"X\";", "needs window counter"),
    "lo > 0 the program would have to catch": ("pattern Fall(uio3) -> Fall(uio5) within "
                                               "(2000 ns, 10000 ns) else abort observed 3;",
                                               "needs window counter"),
    "B on a wire we drive": ("pattern Fall(uio3) -> Fall(uio1) within (2000 ns, 10000 ns) else abort "
                             "source datasheet \"X\";", "on a wire we drive"),
    "A not a wire we drive": ("pattern Fall(uio5) -> Fall(uio6) within (2000 ns, 10000 ns) else abort "
                              "source datasheet \"X\";", "not a wire the lowering drives"),
    "B not one edge": ("pattern Fall(uio3) -> Edge(uio5) within (2000 ns, 10000 ns) else abort "
                       "source datasheet \"X\";", "Rise / Fall"),
}


_SAID = set()


def say(line):
    """print a generated expected-result line once (the mutant passes re-run the same checks)"""
    if line not in _SAID:
        _SAID.add(line)
        print(line)


def a2_agrees(tag, r):
    """one input, one verdict (Wilson 11-16): a compile's A2 line and its window certificate's
    budget agree -- both certified at the same B and per-lane J, or both uncertified.
    Must-fire: M_PC_A2_NOPREM (A2's line without the window's premise gaps)."""
    wb = r.get("within_budget")
    if wb is None:
        return []
    a2 = r["cert"]["A2"]
    if wb["B"] is None:
        return [] if a2.startswith("A2-UNCERTIFIED") else [
            "%s: the window certificate is uncertified, A2 says %r" % (tag, a2[:90])]
    want = "certified: B = %d; %s" % (wb["B"], ", ".join(
        "lane %d J %d" % (l, 1 + v["max_late"]) for l, v in sorted(wb["lanes"].items())))
    return [] if a2.startswith(want) else [
        "%s: the window certificate says %r, A2 says %r" % (tag, want, a2[:90])]


def counterfactual_budget(r):
    """the window certificate's budget with the 1.6a check off (its inputs unchanged): the
    lateness an uncertified image is refused for, generated for the expected reason"""
    import branch_budget as BB
    pg, rd = r["within_inputs"]
    BB.QUEUE_MUT = True
    try:
        return C._budget(r["image"], pg, rd)
    finally:
        BB.QUEUE_MUT = False


def c10_continue(tag, r):
    """`else continue` (Wilson 11-16): UNCERTIFIED, named -- lateness past the proved release:
    FlushLate's PC+2 floor plus B on D*-spaced bit words; needs the FALLTHROUGH PC+2 prefetch
    (F1: the seed is the head after the FALLTHROUGH flush -- Wilson 11-16, correcting "1b", which
    covers a plain ARM's successor). Every part of the reason is generated from the certificate
    with the 1.6a check off."""
    import branch_budget as BB
    import lane_cert as LC
    probs = []
    within = r["cert"]["within"]
    if not within.startswith("UNCERTIFIED") or "1.6a queue check fails" not in within:
        probs.append("%s: within %r, want UNCERTIFIED by the 1.6a queue check" % (tag, within[:120]))
    cf = counterfactual_budget(r)
    if cf["B"] is None:
        return probs + ["%s: no certificate even with the 1.6a check off (%s)" % (tag, cf["reason"][:90])]
    lanes = sorted({w["lane"] for w in r["windows"]})
    for ln in lanes:
        lat = cf["lanes"][ln]["lat"]
        w0 = (C.I.read_header(r["image"], ln)["base"] - C.I.ACT_BASE) // C.I.ACT_BYTES
        pc2 =[w0 + w["ARM_word"] + 2 for w in r["windows"] if w["lane"] == ln]
        seed = min(lat.get(p, 0) for p in pc2)
        top = cf["lanes"][ln]["max_late"]
        if seed < LC.ft_flush_late(0):
            probs.append("%s: lane %d PC+2 lateness %d < FlushLate's floor %d (not the seed)"
                         % (tag, ln, seed, LC.ft_flush_late(0)))
        if not (cf["B"] > 0 and top > seed):
            probs.append("%s: lane %d B %d, max lateness %d -- nothing accumulates past the seed"
                         % (tag, ln, cf["B"], top))
        if BB.queue_refusal(r["image"], cf["B"], cf["lanes"]) is None:
            probs.append("%s: the counterfactual certificate passes 1.6a" % tag)
        say("  %s lane %d: UNCERTIFIED (expected) -- lateness past the proved release: "
              "FlushLate's PC+2 floor (%d) plus B = %d on D*-spaced bit words (lane J %d); "
              "needs the FALLTHROUGH PC+2 prefetch (F1)" % (tag, ln, seed, cf["B"], 1 + top))
    return probs


def c10():
    """`within` / `else` (Wilson 11-15): both lowerings read back FROM THE IMAGE, the arming
    and deadline inequalities on the certified lateness, and the static refusals."""
    import pe_asm
    import branch_budget as BB
    import lane_cert as LC
    import proof_constants as PC
    I, probs = C.I, []
    lo_c, hi_c = 2000 * HZ // 10 ** 9, -(-10000 * HZ // 10 ** 9)
    plain = C.compile_spec(body(), seed=7)
    cs_pin = C._route_pin(plain["route"], 3)
    falls = [i for i, a in enumerate(plain["lowered"][0][0])
             if a[0] == I.OP_LEVEL and a[1] == cs_pin and a[2] == 0]
    for kind in ("abort", "continue"):
        tag = "C10 else %s" % kind
        try:
            r = C.compile_spec(body(WIN % kind), seed=7)
        except C.Refused as e:
            probs.append("%s refused: %s" % (tag, e))
            continue
        lanes, hdr, a_, kw = r["lowered"]
        if bytes(pe_asm.assemble(lanes, hdr, *a_, **kw)) != r["image"]:
            probs.append("%s: the recorded lanes do not re-assemble to the image" % tag)
        probs += a2_agrees(tag, r)
        if kind == "continue":
            probs += c10_continue(tag, r)
        elif not r["cert"]["within"].startswith("certified"):
            probs.append("%s: within %r" % (tag, r["cert"]["within"]))
        if len(r["windows"]) != len(falls):
            probs.append("%s: %d windows, the lowering makes %d CS falls"
                         % (tag, len(r["windows"]), len(falls)))
        if not [p for p in r["checkset"] if p["pred"] == "WINDOW"
                and (p["lo_cycles"], p["hi_cycles"]) == (round(2000 * HZ / 1e9), round(10000 * HZ / 1e9))]:
            probs.append("%s: no WINDOW predicate for the obligation" % tag)
        pb = C._route_pin(r["route"], 5)
        img = r["image"]
        words = {ln: dict(PC.lane_words(img, ln, I)) for ln in lanes}
        named = {x["pin"] for ln in words for x in words[ln].values()
                 if x["op"] != I.OP_ARM and x["pin"] < I.N_PINS}
        if pb is None or pb >= I.N_UIO or pb in named:
            probs.append("%s: B routed to pin %s (want a uio input no other word names)" % (tag, pb))
        # the window certificate's own budget (one input: Wilson 11-16)
        bb = r["within_budget"]
        for w in r["windows"]:
            w0 = (I.read_header(img, w["lane"])["base"] - I.ACT_BASE) // I.ACT_BYTES
            ws = words[w["lane"]]
            arm = ws.get(w0 + w["ARM_word"])
            if not arm or arm["op"] != I.OP_ARM or arm["pin"] != pb or arm["level"] != 0:
                probs.append("%s: lane %d word %d is %s, want an ARM on pin %s for a fall"
                             % (tag, w["lane"], w["ARM_word"], arm, pb))
                continue
            ft = bool(arm["mod"] & I.ARM_MOD_FT)
            if ft != (kind == "continue"):
                probs.append("%s: ARM FALLTHROUGH %s" % (tag, ft))
            if kind == "continue":
                p1, p2 = ws.get(w0 + w["ARM_word"] + 1), ws.get(w0 + w["ARM_word"] + 2)
                if not p1 or p1["op"] != I.OP_LEVEL or p1["pin"] < I.N_PINS:
                    probs.append("%s: PC+1 is %s, want a no-op" % (tag, p1))
                if not p2 or p2["op"] in (I.OP_SHIFT, I.OP_SHIFTIN, I.OP_SHIFTI):
                    probs.append("%s: PC+2 is %s (a FALLTHROUGH edge path cannot start a SHIFT)"
                                 % (tag, p2))
                # uncertified (c10_continue): no certified lateness for the arming inequalities
                continue
            # the image's own numbers: the lead = A's delay + the no-ops before the ARM
            pre = sum(ws[w0 + j]["delay"] for j in range(w["A_word"], w["ARM_word"]))
            lat = bb["lanes"][w["lane"]]["lat"] if bb["B"] is not None else {}
            la, larm = lat.get(w0 + w["A_word"]), lat.get(w0 + w["ARM_word"])
            if la is None or larm is None:
                probs.append("%s: no certified lateness for the window's words" % tag)
                continue
            if not pre + larm + C.ARMED_BY + 1 <= lo_c + C.WB_MIN + LC.SYNC_MIN:
                probs.append("%s: armed by A + %d, B seen from A + %d" % (
                    tag, pre + larm + C.ARMED_BY, lo_c + C.WB_MIN + LC.SYNC_MIN))
            if not pre + arm["delay"] >= hi_c + la + C.ARMED_BY + LC.SYNC_MAX:
                probs.append("%s: deadline A + %d before a B at hi seen late (A + %d)" % (
                    tag, pre + arm["delay"], hi_c + la + C.ARMED_BY + LC.SYNC_MAX))
            if arm["delay"] > C.T_MAX:
                probs.append("%s: timeout %d > %d" % (tag, arm["delay"], C.T_MAX))
    for why, (st, needle) in WIN_REFUSE.items():
        ok, msg = refused_with(body(st), needle)
        if not ok:
            probs.append("C10 %s: not refused by name (%s)" % (why, msg[:120]))
    probs += c10_loops()
    # pe_asm's 7th field: the FALLTHROUGH ARM's mod only
    for bad in ((I.OP_LEVEL, I.UO0, 1, 20, 0, 0, I.ARM_MOD_FT), (I.OP_ARM, 0, 0, 40, 0, 0, I.ARM_MOD_LEVEL2)):
        try:
            pe_asm.split_mods({0: [bad]})
            probs.append("C10 pe_asm accepted mod on %s" % (bad,))
        except pe_asm.Reject:
            pass
    if plain["cert"].get("within") != "not applicable (no within)":
        probs.append("C10 a spec without `within`: %r" % plain["cert"].get("within"))
    return probs


def c10_loops():
    """a window inserted into a LOOP body keeps every LOOP's head on the SAME action (the
    drain table found the UART-TX lowering's head going stale): checked on the UART lowering"""
    import pit_emit as PE
    import run_pit_emit as V1
    probs = []
    base = PE.emit(bytes(V1.IMAGES["uart_crc"]()), HZ).rstrip("\n").splitlines()
    parsed0 = C.S.parse("\n".join(base) + "\n")
    _i, low0, route = C.lower(parsed0["v1"], 7)
    acts0 = low0[0][0]
    tx = [w for w in range(8) if C._route_pin(route, w) is not None][0]
    free = [w for w in range(8) if C._route_pin(route, w) is None][0]
    st = ("pattern Fall(uio%d) -> Fall(uio%d) within (2000 ns, 10000 ns) else continue "
          "source datasheet \"X\";" % (tx, free))
    text = "\n".join(base[:-1] + ["  " + st] + [base[-1]]) + "\n"
    try:
        lanes, _r, _w = C.windows(C.S.parse(text)["poset"], low0, route, HZ)
    except C.Refused as e:
        return ["C10 UART-TX window refused: %s" % e]
    heads0 = [acts0[a[2]][:3] for a in acts0 if a[0] == C.I.OP_LOOP]
    heads1 = [lanes[0][a[2]][:3] for a in lanes[0] if a[0] == C.I.OP_LOOP]
    if not heads0 or heads0 != heads1:
        probs.append("C10 LOOP heads moved off their actions: %s -> %s" % (heads0, heads1))
    return probs


def c11():
    """the premise mechanism (Wilson 11-15 call 1): a registered, SHA-matching datasheet puts
    its ID in the stamp and its gap in the certificate; a SHA mismatch or an unregistered part
    gives the image-only certificate. In-process, on a scratch registry entry."""
    import premises as PM
    import hashlib
    probs = list("C11 premises: %s" % p for p in PM.problems())
    src = os.path.join("host", "poset", "POSET_SPEC.md")
    sha = hashlib.sha256(open(os.path.join(ROOT, src), "rb").read()).hexdigest()
    st = WIN.replace('"X"', '"C11PART"') % "abort"
    saved = (dict(PM.REGISTRY), dict(PM.DATASHEETS))
    try:
        PM.REGISTRY["C11_DOC"] = {"kind": "document", "what": "gate scratch", "source": src,
                                  "sha256": sha, "label": "read"}
        PM.DATASHEETS["C11PART"] = "C11_DOC"
        with_p = C.compile_spec(body(st), seed=7, arm="early", counterfactual=True)
        PM.REGISTRY["C11_DOC"] = dict(PM.REGISTRY["C11_DOC"], sha256="0" * 64)
        bad_sha = C.compile_spec(body(st), seed=7, arm="early", counterfactual=True)
        del PM.DATASHEETS["C11PART"]
        unreg = C.compile_spec(body(st), seed=7, arm="early", counterfactual=True)
    finally:
        PM.REGISTRY.clear(); PM.REGISTRY.update(saved[0])
        PM.DATASHEETS.clear(); PM.DATASHEETS.update(saved[1])
    # one input, one verdict (Wilson 11-16): A2's line reads the window certificate's inputs
    for tag, r in (("registered", with_p), ("SHA mismatch", bad_sha), ("unregistered part", unreg)):
        probs += a2_agrees("C11 %s" % tag, r)
    # with the registered datasheet: certified, the premise ID in the stamp, the window
    # certificate and A2's line -- lane 0 at lateness 0
    wb = with_p["within_budget"]
    if (with_p["stamp"].get("premises") != ["C11_DOC"]
            or not with_p["cert"]["within"].startswith("certified")
            or "premises C11_DOC" not in with_p["cert"]["within"]
            or "premises C11_DOC" not in with_p["cert"]["A2"]
            or wb["B"] is None or wb["lanes"][0]["max_late"] != 0):
        probs.append("C11 a registered datasheet: stamp %s, within %r, A2 %r"
                     % (with_p["stamp"].get("premises"), with_p["cert"]["within"][:90],
                        with_p["cert"]["A2"][:90]))
    # without it (SHA mismatch, unregistered): image-only -- the plain ARM's floor with no
    # earliest-edge premise seeds the lateness, and 1.6a refuses it; J generated with the check off
    for tag, r in (("SHA mismatch", bad_sha), ("unregistered part", unreg)):
        cf = counterfactual_budget(r)
        j0 = None if cf["B"] is None else 1 + cf["lanes"][0]["max_late"]
        if ("premises" in r["stamp"] or not r["cert"]["within"].startswith("UNCERTIFIED")
                or "1.6a queue check fails" not in r["cert"]["within"]
                or "image-only" not in r["cert"]["A2"] or j0 is None or j0 <= 1):
            probs.append("C11 %s: stamp %s, within %r, A2 %r, J with the check off %s"
                         % (tag, r["stamp"].get("premises"), r["cert"]["within"][:90],
                            r["cert"]["A2"][:90], j0))
        say("  C11 %s: UNCERTIFIED (image-only), lane 0 J %s with the 1.6a check off; with the "
              "registered datasheet: certified, lane 0 J %s" % (tag, j0, 1 + wb["lanes"][0]["max_late"]
                                                              if wb["B"] is not None else None))
    return probs


def c12():
    """ArmRetire (Wilson 11-15): with the plain ARM's retire-before-release cap
    (JLane/ArmRetire.lean), the SPI-master `else abort` window certifies at J 1 with 5 cycles of
    spacing after it (20 without the cap)"""
    st = WIN % "abort"
    parsed = C.S.parse(body(st))
    _i, low, route = C.lower(parsed["v1"], 7)
    _l, _r, w = C.windows(parsed["poset"], low, route, HZ, drain=5)
    b = w["budget"]
    j = None if b["B"] is None else 1 + b["lanes"][0]["max_late"]
    return [] if j == 1 else ["C12 SPI-master else abort, drain 5: lane 0 J %s (ArmRetire gives 1)" % j]


def c13():
    """the drain (Wilson 11-15, "build the drain to your design"): generated per window, the
    least drain at which the certificate gives J 1; the closed form agrees on every window; the
    default certifies; `nodrain` stamps UNCERTIFIED; a next action bounded tighter than the
    drain is refused; an image with no `within` is byte-identical to the plain lowering"""
    probs = []
    r = C.compile_spec(body(WIN % "abort"), seed=7)
    ws = r["windows"]
    if not ws:
        return ["C13 the default compiled no window"]
    for x in ws:
        if x.get("drain") is None or x["drain"] != x.get("drain_cf"):
            probs.append("C13 lane %d window at word %s: generated drain %s, closed form %s"
                         % (x["lane"], x["ARM_word"], x.get("drain"), x.get("drain_cf")))
    parsed = C.S.parse(body(WIN % "abort"))
    _i, low, route = C.lower(parsed["v1"], 7)
    _l, _r, w = C.windows(parsed["poset"], low, route, HZ)
    lanes = {x["lane"] for x in w["windows"]}
    if w["budget"]["B"] is None or any(w["budget"]["lanes"][ln]["max_late"] for ln in lanes):
        probs.append("C13 the default drain does not certify J 1: %s" % w["budget"]["reason"])
    if r["stamp"]["status"] != "certified":
        probs.append("C13 the default's stamp: %s" % r["stamp"])
    nd = C.compile_spec(body(WIN % "abort nodrain"), seed=7)
    if nd["stamp"]["status"] != "uncertified" or "nodrain" not in nd["stamp"]["reason"]:
        probs.append("C13 nodrain: stamp %s" % nd["stamp"])
    if any(x.get("drain") for x in nd["windows"]):
        probs.append("C13 nodrain: a drain was added")
    tight = body(WIN % "abort", "pattern Fall(uio5) -> Rise(uio1) during (0 ns, 50 ns) observed 3;")
    ok, msg = refused_with(tight, "would push the next action past")
    if not ok:
        probs.append("C13 a next action bounded tighter than the drain: %s" % msg[:120])
    plain = C.compile_spec(body(), seed=7)
    p0 = C.S.parse(body())
    if plain["image"] != C.lower(p0["v1"], 7)[0]:
        probs.append("C13 an image with no `within` is not byte-identical to the plain lowering")
    return probs + c13_agree() + c13_continue()


#: the mutant passes that re-run c13_continue (the rest skip it; the main pass runs it in full)
CONTINUE_MUTANTS = ("M_PC_FT_EDGEONLY",)


def c13_continue():
    """Wilson 11-20 step 3: `else continue` on the same rules as `else abort`, slot on (SLOT = 2:
    PC+2 ready on its edge entry -- slot off nothing certifies, c13_agree): the default drains
    PC+1 and PC+2 and certifies J 1 at the closed form's drain; `nodrain` stamps UNCERTIFIED; a
    next action bounded tighter than the drain is refused. Must-fire M_PC_FT_EDGEONLY: the
    drain on the edge path only (PC+1 at D*) -> the timeout path's refetched PC+2 stays late."""
    import branch_budget as BB
    if C.MUT and C.MUT not in CONTINUE_MUTANTS:
        return []
    probs = []
    saved = BB.SLOT
    BB.SLOT = 2
    try:
        r = C.compile_spec(body(WIN % "continue"), seed=7)
        wb = r["within_budget"]
        lanes = sorted({x["lane"] for x in r["windows"]})
        if not r["windows"]:
            probs.append("C13 continue: no window compiled")
        if wb is None or wb["B"] is None or any(wb["lanes"][ln]["max_late"] for ln in lanes):
            probs.append("C13 continue: the default drain does not certify J 1 (%s)"
                         % ((wb or {}).get("reason", "no budget")[:100]))
        if r["stamp"]["status"] != "certified":
            probs.append("C13 continue: stamp %s" % r["stamp"])
        for x in r["windows"]:
            if x["drain_found"] is None or x["drain"] != x["drain_cf"]:
                probs.append("C13 continue lane %d ARM %d: drain %s (found %s), closed form %s"
                             % (x["lane"], x["ARM_word"], x["drain"], x["drain_found"],
                                x["drain_cf"]))
        say("  C13 continue (slot 2): %d windows, drain %s, stamp %s"
            % (len(r["windows"]), sorted({x["drain"] for x in r["windows"]}),
               r["stamp"]["status"]))
        nd = C.compile_spec(body(WIN % "continue nodrain"), seed=7)
        if nd["stamp"]["status"] != "uncertified" or "nodrain" not in nd["stamp"]["reason"]:
            probs.append("C13 continue nodrain: stamp %s" % nd["stamp"])
        if any(x.get("drain") for x in nd["windows"]):
            probs.append("C13 continue nodrain: a drain was added")
        tight = body(WIN % "continue",
                     "pattern Fall(uio5) -> Rise(uio1) during (0 ns, 50 ns) observed 3;")
        ok, msg = refused_with(tight, "would push the next action past")
        if not ok:
            probs.append("C13 continue: a next action bounded tighter than the drain: %s"
                         % msg[:120])
    finally:
        BB.SLOT = saved
    return probs


def uart_window_text(kind):
    """the UART-TX lowering (uart_crc) with one window from its TX pin to a free wire"""
    import pit_emit as PE
    import run_pit_emit as V1
    base = PE.emit(bytes(V1.IMAGES["uart_crc"]()), HZ).rstrip("\n").splitlines()
    _i, _low0, route = C.lower(C.S.parse("\n".join(base) + "\n")["v1"], 7)
    tx = [w for w in range(8) if C._route_pin(route, w) is not None][0]
    free = [w for w in range(8) if C._route_pin(route, w) is None][0]
    st = ("pattern Fall(uio%d) -> Fall(uio%d) within (2000 ns, 10000 ns) else %s "
          "source datasheet \"X\";" % (tx, free, kind))
    return "\n".join(base[:-1] + ["  " + st] + [base[-1]]) + "\n"


#: the mutant passes that re-run c13_agree (the ones that move the drain or its terms); every
#: other pass skips it -- the main pass runs it in full (Nate 11-21, gate time)
AGREE_MUTANTS = ("M_PC_DRAIN_OFFBY1", "M_PC_ARMRETIRE_OFF")


def c13_agree():
    """Wilson 11-20 step 2: the search and the closed form agree on EVERY window -- `else
    abort` (drain_closed_form) and `else continue` (drain_closed_form_ft) -- on the SPI-master
    and UART-TX lowerings, slot off and slot on (SLOT = 2, where a FALLTHROUGH PC+2 is ready on
    its edge entry). None on both sides where nothing certifies (PC+2 not edge-ready: the flush's
    refill floor; or the plain lowering's lane not J 1). Red on any disagreement."""
    import branch_budget as BB
    if C.MUT and C.MUT not in AGREE_MUTANTS:
        return []
    probs = []
    saved = BB.SLOT
    try:
        for slot in (None, 2):
            BB.SLOT = slot
            for name, mk in (("SPI", lambda kd: body(WIN % kd)), ("UART-TX", uart_window_text)):
                for kind in ("abort", "continue"):
                    parsed = C.S.parse(mk(kind))
                    _i, low, route = C.lower(parsed["v1"], 7)
                    _l, _r, w = C.windows(parsed["poset"], low, route, HZ)
                    # the drain the compiler chose (None where the search found none)
                    got = sorted({(x["drain"] if x["drain_found"] is not None else None,
                                   x["drain_cf"]) for x in w["windows"]}, key=repr)
                    tag = "C13 agree slot %s %s else %s" % (slot, name, kind)
                    for x in w["windows"]:
                        d = x["drain"] if x["drain_found"] is not None else None
                        if d != x["drain_cf"]:
                            probs.append("%s: lane %d ARM %d search %s, closed form %s"
                                         % (tag, x["lane"], x["ARM_word"], d, x["drain_cf"]))
                    say("  %s: %d windows, (search, closed form) %s" % (tag, len(w["windows"]), got))
    finally:
        BB.SLOT = saved
    return probs


def c14():
    """Wilson 11-15: early arming withdrawn from the compiler (refused by name; only the drain
    table's counterfactual uses it), and no lowering may make more than MAX_PLAIN_ARM_RUN plain
    edge ARMs in a row (item 1b is two words deep)"""
    probs = []

    try:
        parsed = C.S.parse(body(WIN % "abort"))
        _i, low, route = C.lower(parsed["v1"], 7)
        C.windows(parsed["poset"], low, route, HZ, arm="early")
        probs.append("C14 arm='early' compiled without counterfactual=True")
    except C.Refused as e:
        if "withdrawn" not in str(e):
            probs.append("C14 arm='early' refused, but not as withdrawn: %s" % e)
    I = C.I
    arm = (I.OP_ARM, 4, 0, 0, 0, 0)
    sh = (I.OP_SHIFT, 7, 0, 20, 0, 7)
    two = {0: [arm, arm, sh, (I.OP_REARM, 0, 1, 20, 0)]}
    three = {0: [arm, arm, arm, sh, (I.OP_REARM, 0, 1, 20, 0)]}
    ft3 = {0: [arm + (I.ARM_MOD_FT,), arm, arm, sh]}     # an FT ARM is outside 1b's run
    if C.plain_arm_run_problems(two) or C.plain_arm_run_problems(ft3):
        probs.append("C14 a run of %d plain ARMs refused" % C.MAX_PLAIN_ARM_RUN)
    if not C.plain_arm_run_problems(three):
        probs.append("C14 three plain ARMs in a row not refused")
    return probs


def c15():
    """Wilson 11-17: a FALLTHROUGH ARM at another ARM's PC+1 is refused (plain, two-pin or
    FALLTHROUGH A); one word between them compiles"""
    probs = []
    I = C.I
    arm = (I.OP_ARM, 4, 0, 0, 0, 0)
    ft = arm + (I.ARM_MOD_FT,)
    two = arm + (I.ARM_MOD_LEVEL2,)
    sh = (I.OP_SHIFT, 7, 0, 20, 0, 7)
    rearm = (I.OP_REARM, 0, 1, 20, 0)
    for name, a in (("plain", arm), ("two-pin", two), ("FALLTHROUGH", ft)):
        if not C.ft_after_arm_problems({0: [a, ft, sh, rearm]}):
            probs.append("C15 a FALLTHROUGH ARM after a %s ARM not refused" % name)
    if C.ft_after_arm_problems({0: [arm, sh, ft, sh, rearm]}):
        probs.append("C15 a FALLTHROUGH ARM one word after an ARM refused")
    return probs


#: the must-fire runs' section order (judge(first_red=True)): the static checks first, the
#: slot-off/on C13 windows last (11-22: ~140 s of each ~150 s judge)
FAST_FIRST = ("C2", "C3", "C4", "C5", "C6", "C8", "C7", "C9", "C1", "C12", "C14", "C15",
              "C10", "C11", "C13")


def judge(first_red=False):
    """(problems, C1's compile result). `first_red` (the must-fire runs, 11-22): the
    sections cheapest first, stopping at the first red one -- a mutant is killed by any red
    section, and one that survives still runs every section. The gate's own run
    (first_red=False) runs every section in the order it always has."""
    c1_out = {"r": None}

    def s_c1():
        probs = []
        # C1
        b, leads = RG.spi(1)
        ev = G.extract(*b.trace())
        recs = G.infer(ev, [(key("Fall", 3), "|>", key("Rise", 1))], HZ)
        res = bytes(V1T.IMAGES["spi"]())
        text = E2.emit2(res, recs, HZ)
        try:
            r = C.compile_spec(text, seed=7)
        except C.Refused as e:
            probs.append("C1 refused: %s" % e)
            r = None
        if r:
            import run_pit_rt as RT
            ref = bytes(RT.emulation(pit_emit.parse(pit_emit.emit(res, HZ)), random.Random(7))[0])
            if r["image"] != ref:
                probs.append("C1 image differs from run_pit_rt.emulation's (a second lowering?)")
            if r["width"] != 1:
                probs.append("C1 width %d, expected 1" % r["width"])
            if not 0 < r["words"] <= C.N_WORDS:
                probs.append("C1 words used %d, outside 1..%d" % (r["words"], C.N_WORDS))
            win = [p for p in r["checkset"] if p["pred"] == "WINDOW"]
            if len(win) != 1 or (win[0]["lo_cycles"], win[0]["hi_cycles"]) != (min(leads), max(leads)):
                probs.append("C1 window %s, the golden bus drew %d..%d cycles"
                             % ([(p["lo_cycles"], p["hi_cycles"]) for p in win], min(leads), max(leads)))
            # the certified fields must BE the certificate (recomputed here from model/branch_budget);
            # every other field claims nothing (OWED / UNCERTIFIED / not applicable)
            import compile as CC
            if r["cert"].get("A2") != CC.a2_line(r["image"]):
                probs.append("C1 cert A2 is not the certificate's: %r" % r["cert"].get("A2"))
            if r["cert"].get("branch_budget") != CC.branch_budget_line(r["image"]):
                probs.append("C1 cert branch_budget is not the certificate's: %r"
                             % r["cert"].get("branch_budget"))
            # J floor: the recorded lanes must re-assemble to the image, and J_floor must be
            # compute_j on ALL of them (recomputed here, unmutated)
            import pe_asm
            lanes, hdr, a, kw = r["lowered"]
            if bytes(pe_asm.assemble(lanes, hdr, *a, **kw)) != r["image"]:
                probs.append("C1 the recorded lowered lanes do not re-assemble to the image")
            import cert_stamp as CS
            st_img, st_lanes = CS.stamp(r["image"]), CS.stamp_lanes(lanes)
            if st_img != st_lanes:
                probs.append("C1 the image's stamp %s differs from compute_j on the lowered lanes %s"
                             % (st_img, st_lanes))
            if r["stamp"] != st_img or r["cert"].get("J_floor") != CS.line(st_img):
                probs.append("C1 cert J_floor %r / stamp %s, the image's stamp is %s"
                             % (r["cert"].get("J_floor"), r["stamp"], st_img))
            rest = {a: v for a, v in r["cert"].items()
                    if a not in ("usb_coresident", "A2", "branch_budget", "J_floor")}
            if not all(v.startswith(("OWED", "UNCERTIFIED", "not applicable")) for v in rest.values()):
                probs.append("C1 cert claims more than the skeleton does: %s" % r["cert"])
            if r["cert"].get("usb_coresident") != "not applicable (no USB receive)":
                probs.append("C1 SPI image: usb_coresident %r" % r["cert"].get("usb_coresident"))
        c1_out["r"] = r
        return probs

    def s_c8():
        probs = []
        # C8: POSET_SPEC.md's generated passages match the constants file
        import gen_spec_doc
        probs += ["C8 %s" % p for p in gen_spec_doc.stale()]
        return probs

    def s_c7():
        probs = []
        k = C.PC.load()
        lim = k["coresident_usb"]
        # C7: the USB co-resident threshold (Wilson 11-12, option (i)), on images built by pe_isa
        if k["coresident_min_d"] > lim:
            probs.append("C7 coresident_usb %d no longer implies coresident_min_d %d"
                         % (lim, k["coresident_min_d"]))
        for usb, d, want in ((True, lim - 1, "refused"), (True, lim, "checked"), (False, lim - 1, "n/a")):
            try:
                _u, line = C.target_check(usb_image(d, usb))
                got = "checked" if line.startswith("checked") and str(lim) in line else \
                      "n/a" if line.startswith("not applicable") else line
            except C.Refused as e:
                m = str(e)
                got = "refused" if (re.search(r"lane 1 word \d+: spacing %d < %d" % (d, lim), m)
                                    and "cannot share an image" in m) else "refused otherwise: %s" % m
            if got != want:
                probs.append("C7 %s image, co-resident lane at d=%d: %s, expected %s"
                             % ("USB" if usb else "non-USB", d, got, want))
        return probs

    def s_c9():
        probs = []
        lim = C.PC.load()["coresident_usb"]
        # C9: a co-resident lane whose fast section is reached only by a branch, past its first REARM
        img, fast_word = multisection_image(lim)
        first_rearm = [i for i, x in enumerate(C.I.lane_programs(img)[1][1])][-1]
        if fast_word <= C.I.read_header(img, 1)["base_word"] + first_rearm:
            probs.append("C9 the fast word is not past lane 1's first REARM (the case is void)")
        try:
            C.target_check(img)
            probs.append("C9 multi-section image accepted: lane 1 word %d (spacing %d) not checked"
                         % (fast_word, lim - 1))
        except C.Refused as e:
            if ("lane 1 word %d: spacing %d < %d" % (fast_word, lim - 1, lim)) not in str(e):
                probs.append("C9 multi-section image refused, but not for lane 1 word %d: %s"
                             % (fast_word, e))
        return probs

    def s_c2():
        probs = []
        # C2
        ok, msg = refused_with(body("pattern Rise(uio1) -> Rise(uio2);", "pattern Rise(uio2) -> Rise(uio1);"),
                               "cycle")
        if not ok:
            probs.append("C2 cycle not refused by name: %s" % msg)
        return probs

    def s_c3():
        probs = []
        # C3
        six = ["pattern Rise(uio%d) -> Fall(uio%d);" % (w, w) for w in range(6)]
        ok, msg = refused_with(body(*six), "Dilworth width 6 > 5")
        if not ok:
            probs.append("C3 width 6 not refused by name: %s" % msg)
        return probs

    def s_c4():
        probs = []
        # C4
        nodes, edges = ["A", "B", "C", "D", "E"], {("A", "B"), ("D", "B"), ("B", "C"), ("B", "E")}
        w = C.dilworth_width(nodes, edges)
        if w != 2:
            probs.append("C4 Dilworth width %d on A,D < B < C,E; expected 2" % w)
        return probs

    def s_c5():
        probs = []
        # C5
        ok, msg = refused_with(body("pattern Rise(uio1) or Fall(uio1);"), "not in the compiler skeleton")
        if not ok:
            probs.append("C5 compound pattern not refused by name: %s" % msg)
        return probs

    def s_c6():
        probs = []
        # C6
        t = pit_emit.emit(bytes(V1T.IMAGES["refused"]()), HZ)
        ok, msg = refused_with(t, "lowering (run_pit_rt.emulation)")
        if not ok:
            probs.append("C6 non-emulable v1 spec not refused through the lowering: %s" % msg)
        return probs

    sections = [("C1", s_c1), ("C10", c10), ("C11", c11), ("C12", c12), ("C13", c13),
                ("C14", c14), ("C15", c15), ("C8", s_c8), ("C7", s_c7), ("C9", s_c9),
                ("C2", s_c2), ("C3", s_c3), ("C4", s_c4), ("C5", s_c5), ("C6", s_c6)]
    if first_red:
        sections.sort(key=lambda s: FAST_FIRST.index(s[0]))
    probs = []
    for _name, f in sections:
        probs += f()
        if first_red and probs:
            break
    return probs, c1_out["r"]


def main() -> int:
    if os.environ.get("POSET_COMPILE_MUTANT"):
        try:
            probs, _ = judge()
        except Exception as e:
            probs = ["crash: %r" % e]
        print("MUTANT %s: %s" % (os.environ["POSET_COMPILE_MUTANT"], "RED" if probs else "green"))
        for p in probs[:3]:
            print("   ", p)
        return 1 if probs else 0
    print("poset compile: the compiler skeleton (clock %d Hz, %d program words)" % (HZ, C.N_WORDS))
    probs, r = judge()
    if r:
        for ln in r["log"]:
            print("   ", ln)
        for p in r["checkset"]:
            print("    checkset:", p)
        print("    cert:", r["cert"])
    for p in probs:
        print("  ***", p)
    for m in C.MUTANTS:
        # IN-PROCESS, through the same `judge` (gate_meta's stub hides the mutants too)
        C.MUT = m
        try:
            mp, _ = judge(first_red=True)
        except Exception as e:
            mp = ["crash: %r" % e]
        finally:
            C.MUT = ""
        red = bool(mp)
        print("  must-fire %-19s %s  %s" % (m, "RED (killed)" if red else "*** SURVIVED",
                                            (mp[0] if mp else "")[:80]))
        if not red:
            probs.append("mutant %s survived" % m)
    import pe_asm
    for m in ASM_MUTANTS:
        pe_asm.MODS_MUT = m
        try:
            mp = c10()
        except Exception as e:
            mp = ["crash: %r" % e]
        finally:
            pe_asm.MODS_MUT = ""
        print("  must-fire %-19s %s  %s" % (m, "RED (killed)" if mp else "*** SURVIVED",
                                            (mp[0] if mp else "")[:80]))
        if not mp:
            probs.append("mutant %s survived" % m)
    if probs:
        print("GATE poset_compile: FAILED (%d)" % len(probs))
        return 1
    print("GATE poset_compile: PASSED (C1-C15; %d / %d mutants killed)" % (len(C.MUTANTS) + len(ASM_MUTANTS), len(C.MUTANTS) + len(ASM_MUTANTS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
