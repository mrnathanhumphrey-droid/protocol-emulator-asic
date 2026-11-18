"""gate_lane_cert -- the stage 6 certificate as a gate (Wilson 11-14: red now, green after the
program fix). Runs model/lane_cert.py on usbdev's image and checks the SHIFTI spacing rule;
every must-fire must turn its check red, or the gate is not testing what it says.

  check 1  proof_constants.spacing_of reads SHIFTI's low 8 delay bits (RTL l.1892)
  check 2  lane_cert on usbdev: certificate, release-after-writeback, arming, next-SOP fetch
           deadline, first sample, turnaround, other lanes, correction A -- all green
  M_LC_ARMJ_FLOOR   arm_j's premise weakened to the ARM floor     -> check 2 red at an arm_j
  M_LC_LATE_SOP     an extra 40-cycle nop before a handshake copy's arm_sop -> red (armed after
                    the earliest SOP: the certificate's own premise fails)
  M_LC_SHIFTI_FULL  spacing_of reads SHIFTI's whole delay field   -> check 1 red
  M_LC_LAT_IGNORED  the certificate's lateness zeroed -> check 3 red (the flush refill's
                    lateness on PC+2 vanishes: the gate notices it lost its teeth)
  check 3  FALLTHROUGH (ArmFT, F4): usbdev with one handshake copy's (HALF) arm_sop made
           FALLTHROUGH (ARM_MOD_FT) must be refused twice (a SHIFTIN at PC+2; HALF with
           FALLTHROUGH), and the certificate must put flush_refill_late on its PC+2
  check 4  CORESIDENT_USB (Wilson 11-14 ruling 2): proof_constants' certified usb_other_R is
           the current certificate's (gen_cert_constants), and the rule it derives refuses an
           image whose other lanes act every coresident_usb - 1 cycles and accepts one at
           coresident_usb (56 refused, 57 accepted today)
  M_LC_CERT_STALE   a stored usb_other_R one below the certificate -> check 4 red
  check 5  the branch-1 budget B and per-lane lateness per image (Wilson 11-14): model/branch_budget.json
           is today's certificate (gen_branch_budget) for every image (universe + run_branch_check)
  M_LC_BUDGET_STALE a recorded B four above its certificate      -> check 5 red
  M_LC_NOPIN_ALL    every word counted as touching a pin (the NopSplit classifier off) -> the
                    record's max_late_pin is stale on every image the split moves (check 5 red)
  M_LC_ARMGATE_OFF  no generic-lane ARM gated (branch_budget.arm_gate off) -> the UART-receive
                    images' max_late_pin is stale (check 5 red)
  M_LC_UART_FRAME_SHORT the arming premise's frame one bit short (the next start edge a bit
                    earlier: the arming margin negative, the ARM stays in J) -> stale (red)
  check 6  a negative UART arming margin (arm_gate) is refused: uart_rx_board with its REARM
           70 cycles longer is uncertified, by name
  M_LC_ARMMARGIN_OFF  the refusal off -> check 6 fails (its image certifies)
  check 7  the USB lane report's failures (lane_cert.full_report) are a refusal: usbrx_main
           (arm_sop at EOP + 311 against TIPD 78) is uncertified, by name
  M_LC_USBFAIL_OFF  the report's failures ignored -> check 7 fails
  check 8  the 1.6a queue check with the certified lateness in J (program_a2.queue_slot,
           lateness=True) is part of A2's verdict: branch_cmp_lo's window certificate fails it
           and is refused; what image_budget returns passes it
  M_LC_QUEUE_OFF  the 1.6a check skipped -> the returned certificate fails 1.6a
  M_LC_EDF_OFF      the EDF response scheme (RespEdfClose.wb_close_edf) never tried -> every
                    image it certifies loses its B (check 5 red)
  THE ARMING PREMISE (Wilson 11-14 ruling 1): a handshake copy's arm_sop moved late by raising
  the READBIT before it by n (the chain grows by exactly n; no word shifts), n0 = the generated
  deadline (lane_cert.arm_premise_bounds) - its armed-by bound on the real program:
  M_LC_ARM_EDGE_PASS  n0: armed exactly at the deadline           -> must PASS
  M_LC_ARM_EDGE_FAIL  n0 + 1: one past it                          -> must be red
  M_LC_ARM_100        n = 100 (armed at EOP + 163 on today's program) -> must be red
  check 9  branch_budget.slot_ready names its theorem's premise (Wilson 11-17): PC+2 after a plain
           PC+1 is ready only at d >= p1b2_plain_min_d (Buf.p1b2_margin_plain_scan: 4);
           not ready at d = 3, ready at d = 4, ready after an ARM PC+1 (m1 / m3) at d = 3
  M_LC_SLOT_SPACING_OFF  the premise unchecked -> PC+2 ready at d = 3 (check 9 red)
  check 10 a FALLTHROUGH ARM's timeout word is ready only while P1B2_FILL_SCAN + L <= T
           (Buf.p1b2_margin_timeout_scan), tested directly (Wilson 11-17): L passed in, for
           L = 0 and L = 5 the rule drops it at T = FILL + L - 1 and keeps it at FILL + L; end
           to end, spacing 60 / T 35 certifies and the certificate loop called the rule
           (image_budget timeout_rule_calls). Image header through pe_isa.d_fields
  M_LC_SLOT_TIMEOUT_OFF  the rule off -> the word stays ready at T = FILL + L - 1 (check 10 red)
  check 11 a branch at a plain ARM's PC+1: its fall-through PC+2 is ready (d >= 4), its taken
           target is not -- the buffer fetches ARM + 2 only (Wilson 11-17, rule (1) removed)
  M_LC_SLOT_BRANCH_OFF  the taken target marked ready (check 11 red)
  check 12 a FALLTHROUGH ARM B at plain ARM A's PC+1: A's slot gives PC+1, PC+2, never PC+3 (A
           fetches two words; Wilson 11-17, rule (2) removed); B's own rule keeps its two words
  M_LC_SLOT_PC3_OFF  A's PC+3 marked ready (check 12 red)
  check 13 the readiness registry (branch_budget.READY_RULES, Wilson 11-17): every rule names its
           theorem(s); a proved rule's are at the Lean gate (gate_lean_build.KEY); every emitted
           rule is registered and every registered rule exercised; owed / counterfactual words
           never reach slot_ready (the certificate)
  M_LC_REG_NOTHEOREM  a proved rule with no theorem          (check 13 red)
  M_LC_REG_NOTLEAN    a theorem not at the Lean gate          (check 13 red)
  M_LC_REG_UNREG      an emitted rule not registered          (check 13 red)
  M_LC_REG_LEAK       owed / counterfactual words reach ready (check 13 red)
  check 14 the slot under contention (ContendB.slot_wait_fcfs_two, FCFS by capture): another
           lane with an ARM is an older requester, wait contend_per_lane (8) each; a word is
           ready only while its free-port margin covers the wait (PC+1 not at wait 8; PC+2 from
           d = dmin + 8; the FALLTHROUGH timeout word from T = FILL + 8 + L); idle neighbours 0
  M_LC_CONTEND_OFF    contention ignored, wait 0 (check 14 red)
  check 15 slot depth above slot_depth (2) is refused by the certificate (no theorem; Wilson
           11-17), and the record / stamp sources never read the counterfactual (drain_table's
           prefetch columns, a `ready` set, counterfactual=True)
  M_LC_DEPTH_GT2     depth 3 certified (check 15 red)
  M_LC_STAMP_READS_CF a stamp source importing drain_table (check 15 red)
  check 16 the host-interval premises (tipd_fast, min_packet) count device cycles at the device
           clock's slow edge, clock.SOURCE_PPM: a stand-in 20000 ppm moves both below 0 ppm's
  M_LC_PPM_IGNORED    SOURCE_PPM left out (check 16 red)
  check 17 an edge-paced lane with no T_ext and a late lane: queue_refusal refuses by name
           ("1.6a not checkable"), never raises out of the certificate
  M_LC_EDGEPACED_CRASH  the catch removed (check 17 red)
  check 18 the window bound's S counts the FALLTHROUGH disarms (ArmFT.disarm_noDec; (b') removes
           stalls only, Wilson 11-18): usbdev_dev's lanes 1-4 are charged USB lane 0's one disarm
           per window, R 24 (23 without it), and a lane with no FALLTHROUGH neighbour gets S 0
  M_LC_DISARM_S_OFF   the disarms left out of S (check 18 red)
  M_LC_FT_UNSEEN    no ARM read as FALLTHROUGH                    -> check 3 red
  M_LC_FT_NOFLOOR   no lateness floor after the flush             -> check 3 red
Static, < 2 s. Usage: python model/gate_lane_cert.py [dir holding usbdev.py]
"""
from __future__ import annotations

import contextlib
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _setup(img_dir=None):
    sys.path[:0] = [HERE, os.path.join(ROOT, "test")]
    import lane_cert as LC                           # (puts test/ first on the path itself)
    import proof_constants as PC
    if img_dir:
        sys.path.insert(0, img_dir)                  # the image module given wins
    import usbdev as V
    return LC, PC, V


def check_spacing(PC, I):
    w = I._unpack(I.ACT_FIELDS, I.act_shifti(0xA5, 1, 40), I.ACT_BYTES)
    got = PC.spacing_of(w, I)
    return got == 40, "spacing_of(SHIFTI 0xA5 @ 40) = %d (want 40)" % got


def run_cert(LC, img, quiet=True):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf) if quiet else contextlib.nullcontext():
        fails = LC.full_report(img, "usbdev")
    return fails, buf.getvalue()


def ft_program(LC, V, I):
    """usbdev's program with one handshake copy's arm_sop (an edge ARM, not after an SE0 ARM, not
    the lane's first word, whose PC+2 is a SHIFTIN) made FALLTHROUGH: (program, word)"""
    img = V.image()
    g = LC.lane_graph(img, I.USB_LANE, I)
    base = min(g)
    preds = {w: [p for p in g if w in g[p][1]] for w in g}
    for w in sorted(g):
        if (w == base or LC.arm_kind(g[w][0], I) != "edge" or not preds[w] or
                all(LC.arm_kind(g[q][0], I) == "se0" for q in preds[w])):
            continue
        if w + 2 in g and g[w + 2][0]["op"] == I.OP_SHIFTIN:
            p = V.device_program()
            x = g[w][0]
            bit = I.ARM_MOD_FT
            p[w - base] = I.act(x["op"], x["pin"], x["level"], 500, count=x["count"], q=x["q"],
                                pinb=x["pinb"], mod=x["mod"] | bit)
            return p, w
    return None, None


def check_ft(LC, V, I):
    """the FALLTHROUGH paths on a handshake copy's arm_sop made FALLTHROUGH (it keeps its HALF bit):
    the refusals fire (a SHIFTIN at PC+2; HALF with FALLTHROUGH) and the certificate puts the
    flush refill's lateness (proof_constants flush_refill_late) on PC+2"""
    p, w = ft_program(LC, V, I)
    if p is None:
        return False, "no handshake arm_sop with a SHIFTIN at PC+2 to test on"
    img = V.image(prog=p)
    fails, _o = run_cert(LC, img)
    refused = any(f[0] == "FT" and f[1].startswith("w%d PC+2" % w) for f in fails)
    halfed = any(f[0] == "FT" and f[1].startswith("w%d HALF" % w) for f in fails)
    import proof_constants as PC
    k = PC.load()
    g, preds, gaps = LC.build(img, I.USB_LANE, LC.premises(k), I)
    fts = LC.ft_paths(g, I)
    floor = {c2: LC.ft_flush_late(0) for _c1, c2 in fts.values() if c2 in g}
    xr = {c1: 1 for c1, _c2 in fts.values() if c1 in g}
    cert = LC.certificate(g, preds, gaps, k, 0, 2, floor=floor, xr=xr)
    floored = (w in fts and cert is not None and
               cert[0].get(fts[w][1], 0) >= k["flush_refill_late"])
    ok = refused and floored and halfed
    return ok, ("arm_sop w%d made FALLTHROUGH: PC+2 refused %s, PC+2 late by the flush refill %s, "
                "HALF + FALLTHROUGH refused %s" % (w, refused, floored, halfed))


def image_others_at(V, I, d):
    """usbdev's image with every other lane's word acting every `d` cycles (usbdev.image's own
    layout; its other lanes act every 500)"""
    p = V.device_program()
    l0 = I.ACT_BASE
    lp = l0 + len(p) * I.ACT_BYTES
    p = p + [I.act(I.OP_REARM, 0, 0, d)]
    hs = [I.hdr(V.DM, I.PIN_NONE, 1, V.D, 0, 2 * V.D, 3 * V.D, l0)]
    hs += [I.hdr(I.UO0 + n - 1, I.UO0 + n - 1, 1, 500, 0, 200, 240, lp)
           for n in range(1, I.N_LANES)]
    return I.join_image(hs, p)


def arming_case(LC, V, I, n):
    """(armed late?, armed-by, deadline, word) with the READBIT before the first handshake copy's
    arm_sop raised by n"""
    g = LC.lane_graph(V.image(), I.USB_LANE, I)
    base = min(g)
    for w in sorted(g):
        x = g[w][0]
        if x["op"] == I.OP_READBIT and any(LC.arm_kind(g[t][0], I) == "edge" for t in g[w][1]):
            sop = next(t for t in g[w][1] if LC.arm_kind(g[t][0], I) == "edge")
            p = V.device_program()
            p[w - base] = I.act(x["op"], x["pin"], x["level"], x["delay"] + n, count=x["count"],
                                q=x["q"], pinb=x["pinb"], mod=x["mod"])
            f, _o = run_cert(LC, V.image(prog=p))
            wb, dl = LC.full_report.last.get("arm_wb", {}).get(sop, (None, None))
            return any(e[1] == "armed late w%d" % sop for e in f), wb, dl, sop
    return None, None, None, None


def check_coresident(PC, V, I):
    import gen_cert_constants as G
    k = PC.load()
    cur = G.certified()
    fresh = all(k.get(c) == v for c, v in cur.items())
    lim = k["coresident_usb"]
    refused = bool(PC.usb_coresident_problems(image_others_at(V, I, lim - 1), k))
    accepted = not PC.usb_coresident_problems(image_others_at(V, I, lim), k)
    ok = fresh and refused and accepted
    return ok, ("usb_other_R stored %s, certificate %s (%s); coresident_usb %d: %d refused %s, "
                "%d accepted %s" % (k.get("usb_other_R"), cur.get("usb_other_R"),
                                    "current" if fresh else "STALE", lim, lim - 1, refused, lim,
                                    accepted))


def _slot_graph(I, d, pc1_arm=False):
    """ARM w0 -> PC+1 w1 -> PC+2 w2 -> w3 -> w0, PC+1 -> PC+2 released d apart (rd = gaps[w1][-1]
    + the held part of gaps[w2], here none)"""
    arm = {"op": I.OP_ARM, "mod": 0, "delay": 0}
    plain = {"op": I.OP_LEVEL, "mod": 0, "delay": 0}
    g = {0: (arm, [1]), 1: (arm if pc1_arm else plain, [2]), 2: (plain, [3]), 3: (plain, [0])}
    gaps = {0: [1], 1: [d], 2: [5], 3: [5]}
    return g, gaps


def check_slot_spacing(BB, PC, I):
    """check 9: branch_budget.slot_ready marks PC+2 ready only under its theorem's premise --
    Buf.p1b2_margin_plain_scan needs d >= p1b2_plain_min_d (4): at d = 3 PC+2 is NOT ready, at
    d = 4 it is; PC+1 ready either way; PC+1 a plain edge ARM (p1b2_margin_arm_scan, m1 / m3, no
    premise) keeps PC+2 ready at d = 3"""
    k = PC.load()
    dmin = k["p1b2_plain_min_d"]
    g3, gp3 = _slot_graph(I, dmin - 1)
    g4, gp4 = _slot_graph(I, dmin)
    gm, gpm = _slot_graph(I, dmin - 1, pc1_arm=True)
    lo = BB.slot_ready(g3, I, 2, gp3, k)
    hi = BB.slot_ready(g4, I, 2, gp4, k)
    m13 = BB.slot_ready(gm, I, 2, gpm, k)
    # dmin == 4: the literal premise of Buf.p1b2_margin_plain_scan (`4 ≤ d`)
    ok = dmin == 4 and 1 in lo and 2 not in lo and 2 in hi and 2 in m13
    return ok, ("slot_ready PC+2: d = %d %s, d = %d %s, m1/m3 at d = %d %s (p1b2_plain_min_d %d)"
                % (dmin - 1, "not ready" if 2 not in lo else "READY",
                   dmin, "ready" if 2 in hi else "NOT READY",
                   dmin - 1, "ready" if 2 in m13 else "NOT READY", dmin))


def check_slot_contend(BB, PC, I):
    """check 14: the slot under contention (ContendB, FCFS by capture, Wilson 11-17) -- another
    lane with an ARM is an older requester (slot_contenders 1, slot_wait = contend_per_lane);
    a word is ready only while its free-port margin covers the wait: at wait 8, PC+1 (margin 0)
    is not ready, PC+2 at d = dmin + 8 is and at dmin + 7 is not; the FALLTHROUGH timeout word
    needs T >= FILL + wait + L; an image whose other lanes have no ARM waits 0"""
    import lane_cert as LC
    k = PC.load()
    cpl = k["contend_per_lane"]
    dmin = k["p1b2_plain_min_d"]
    fill = k["p1b2_fill_scan"]
    probs = []
    gA, gpA = _slot_graph(I, dmin)
    idle = {0: ({"op": I.OP_LEVEL, "mod": 0, "delay": 0}, [0])}
    graphs = {0: (gA, None, gpA), 1: (gA, None, gpA), 2: (idle, None, {0: [5]})}
    nc, wt = BB.slot_contenders(graphs, I, 0), BB.slot_wait(graphs, I, 0, k)
    if nc != 1 or wt != cpl:
        probs.append("contenders %d, wait %d (want 1, %d)" % (nc, wt, cpl))
    free = BB.slot_ready(gA, I, 2, gpA, k, contend=0)
    busy = BB.slot_ready(gA, I, 2, gpA, k, contend=cpl)
    if not ({1, 2} <= free) or (busy & {1, 2}):
        probs.append("free port %s, wait %d %s (want {1, 2} then none)"
                     % (sorted(free), cpl, sorted(busy)))
    g8, gp8 = _slot_graph(I, dmin + cpl)
    g7, gp7 = _slot_graph(I, dmin + cpl - 1)
    if 2 not in BB.slot_ready(g8, I, 2, gp8, k, contend=cpl) or \
            2 in BB.slot_ready(g7, I, 2, gp7, k, contend=cpl):
        probs.append("PC+2 at d = dmin + wait not ready, or at dmin + wait - 1 ready")
    prem = LC.premises(k)
    tres = {}
    for T in (fill + cpl - 1, fill + cpl):
        g, _p, gaps = LC.build(_ft_slot_image(I, T, d1=60), 0, prem, I)
        (a, (c1, _c2)), = LC.ft_paths(g, I).items()
        rdy = BB.slot_ready(g, I, 2, gaps, k, contend=cpl)
        tres[T] = c1 in rdy and c1 not in BB.slot_timeout_drop(g, I, rdy, {a: 0}, k, contend=cpl)
    if tres[fill + cpl - 1] or not tres[fill + cpl]:
        probs.append("timeout word at wait %d: T %d %s, T %d %s"
                     % (cpl, fill + cpl - 1, tres[fill + cpl - 1], fill + cpl, tres[fill + cpl]))
    img = _ft_slot_image(I, TIMEOUT_E2E[0], d1=TIMEOUT_E2E[1])
    g_img = {l: LC.build(img, l, prem, I) for l in I.lane_programs(img)}
    if BB.slot_wait(g_img, I, 0, k) != 0:
        probs.append("check 10's image (other lanes idle) waits %d" % BB.slot_wait(g_img, I, 0, k))
    return not probs, ("; ".join(probs[:3]) if probs else
                       "one older requester: wait %d; PC+1 / PC+2 ready free, not at wait %d; "
                       "PC+2 ready from d = %d; timeout word from T = FILL + %d; idle neighbours "
                       "wait 0" % (cpl, cpl, dmin + cpl, cpl))


#: the sources that make the record and the stamp, and what they must never read (Wilson 11-17)
CF_SOURCES = ("model/gen_branch_budget.py", "model/cert_stamp.py")
CF_TOKENS = ("drain_table", "ready=", "counterfactual=True")


def cf_reads(texts):
    """[(source, token)]: a record / stamp source that reads the counterfactual"""
    return [(src, t) for src, txt in texts.items() for t in CF_TOKENS if t in txt]


def check_depth(BB, PC, I, texts=None):
    """check 15: depth above the buffer's is refused (Wilson 11-17): with SLOT = slot_depth + 1
    check 10's image has no certificate and the reason names the depth; at slot_depth it
    certifies. And the record / stamp sources never read the counterfactual (the drain table's
    prefetch columns, a `ready` set, `counterfactual=True`)."""
    k = PC.load()
    dep = k["slot_depth"]
    img = _ft_slot_image(I, TIMEOUT_E2E[0], d1=TIMEOUT_E2E[1])
    saved = BB.SLOT
    try:
        BB.SLOT = dep + 1
        r3 = BB.image_budget(img)
        BB.SLOT = dep
        r2 = BB.image_budget(img)
    finally:
        BB.SLOT = saved
    if texts is None:
        texts = {}
        for src in CF_SOURCES:
            with open(os.path.join(ROOT, src), encoding="utf-8") as fh:
                texts[src] = fh.read()
    reads = cf_reads(texts)
    ok = (r3["B"] is None and "slot depth" in (r3["reason"] or "") and r2["B"] is not None
          and not reads)
    return ok, ("SLOT %d: %s; SLOT %d: %s; record / stamp read the counterfactual: %s"
                % (dep + 1, "refused" if r3["B"] is None else "CERTIFIED B %s" % r3["B"],
                   dep, "B %s" % r2["B"] if r2["B"] is not None else "NO CERTIFICATE",
                   ", ".join("%s (%s)" % x for x in reads) if reads else "none"))


def check_ppm(LC):
    """check 16: the host-interval premises count device cycles at the device clock's slow edge
    (clock.SOURCE_PPM): with a stand-in 20000 ppm, tipd_fast and min_packet both drop below
    their values at 0 ppm; at the declared ppm they equal floor(nominal x (1 - ppm / 1e6))"""
    import clock
    saved = dict(clock.SOURCE_PPM)
    try:
        cur = LC.premises()
        clock.SOURCE_PPM.clear()
        clock.SOURCE_PPM.update({t: 0 for t in saved})
        p0 = LC.premises()
        clock.SOURCE_PPM.update({t: 20000 for t in saved})
        p2 = LC.premises()
    finally:
        clock.SOURCE_PPM.clear()
        clock.SOURCE_PPM.update(saved)
    moved = p2["tipd_fast"] < p0["tipd_fast"] and p2["min_packet"] < p0["min_packet"]
    return moved, ("tipd_fast %d / min_packet %d at the declared %d ppm; at 0 ppm %d / %d, at "
                   "20000 ppm %d / %d" % (cur["tipd_fast"], cur["min_packet"],
                                          max(saved.values()), p0["tipd_fast"],
                                          p0["min_packet"], p2["tipd_fast"], p2["min_packet"]))


def check_edge_paced(BB):
    """check 17: an edge-paced lane (a peer-released SPI target, gate_a2_program's image) with no
    T_ext registered for its image, and a late lane: queue_refusal refuses by name ("1.6a not
    checkable ... EDGE-PACED") instead of raising out of the certificate"""
    import pe_proto
    tg = pe_proto.SPITarget(mode=0, sck=4, mosi_pin=5, nbytes=3)
    img = pe_proto.image({0: tg.program()}, {0: tg.header()}, t_ext=tg.t_ext())
    try:
        why = BB.queue_refusal(img, 0, {0: {"max_late": 1}})
    except ValueError as exc:      # EdgePacedNoTExt (a ValueError) escaping: the defect, red
        return False, "queue_refusal raised %s: %s" % (type(exc).__name__, str(exc)[:70])
    ok = bool(why) and "not checkable" in why and "EDGE-PACED" in why
    return ok, "edge-paced lane, no T_ext, a late lane: %s" % ((why or "NOT REFUSED")[:90])


#: check 18's expected figures (Wilson 11-18): usbdev_dev's lanes 1-4 response with USB lane 0's
#: FALLTHROUGH disarm charged (23 before the disarm was counted)
DISARM_IMAGE, DISARM_LANES, DISARM_R = "usbdev_dev.hex", (1, 2, 3, 4), 24


def check_disarm_s(BB, LC):
    """check 18: S counts the other lanes' FALLTHROUGH disarms -- usbdev_dev's lanes 1-4 at R 24
    with B and J 1 unchanged; and _disarm_S is 0 for a lane whose neighbours have no FALLTHROUGH
    ARM (a plain-ARM image's lane 1)"""
    import gen_branch_budget as GB
    import proof_constants as PC
    corp = dict(GB.corpus())
    r = BB.image_budget(corp[DISARM_IMAGE])
    if r["B"] is None:
        return False, "%s not certified: %s" % (DISARM_IMAGE, (r["reason"] or "")[:70])
    Rs = {l: (r["lanes"].get(l) or {}).get("R") for l in DISARM_LANES}
    js = {l: 1 + (r["lanes"].get(l) or {}).get("max_late", 0) for l in DISARM_LANES}
    I = LC._isa()
    prem = LC.premises(PC.load())
    plain = corp["sptgt_m0_image.hex"]
    progs = I.lane_programs(plain)
    graphs = {l: LC.build(plain, l, prem, I) for l in progs}
    s0 = BB._disarm_S(1, sorted(progs), graphs, {l: 0 for l in progs}, 40)
    ok = all(v == DISARM_R for v in Rs.values()) and all(v == 1 for v in js.values()) and s0 == 0
    return ok, ("%s lanes 1-4 R %s (want %d), J %s; plain image S %d"
                % (DISARM_IMAGE, sorted(set(Rs.values()), key=str), DISARM_R,
                   sorted(set(js.values())), s0))


def check_slot_branch(BB, PC, I):
    """check 11: a branch at a plain ARM's PC+1 -- its fall-through PC+2 (ARM + 2) is ready at
    d >= p1b2_plain_min_d, its taken target (word 4) is not (Wilson 11-17, rule (1) removed)"""
    k = PC.load()
    dmin = k["p1b2_plain_min_d"]
    arm = {"op": I.OP_ARM, "mod": 0, "delay": 0}
    br = {"op": min(I.BRANCH_OPS), "mod": 0, "delay": 0}
    plain = {"op": I.OP_LEVEL, "mod": 0, "delay": 0}
    g = {0: (arm, [1]), 1: (br, [2, 4]), 2: (plain, [3]), 3: (plain, [0]), 4: (plain, [0])}
    gaps = {0: [1], 1: [dmin], 2: [5], 3: [5], 4: [5]}
    r = BB.slot_ready(g, I, 2, gaps, k)
    ok = 1 in r and 2 in r and 4 not in r
    return ok, ("branch at PC+1 (d = %d): fall-through PC+2 %s, taken target %s"
                % (dmin, "ready" if 2 in r else "NOT READY",
                   "not ready" if 4 not in r else "READY"))


def check_slot_pc3(BB, PC, I):
    """check 12: a FALLTHROUGH ARM B at plain ARM A's PC+1 -- A's slot makes PC+1 and PC+2 ready,
    never PC+3 (A fetches two words; Wilson 11-17, rule (2) removed); B's own FALLTHROUGH rule
    keeps its PC+1 / PC+2 (A's PC+2 / PC+3)"""
    k = PC.load()
    dmin = k["p1b2_plain_min_d"]
    arm = {"op": I.OP_ARM, "mod": 0, "delay": 0}
    ft = {"op": I.OP_ARM, "mod": I.ARM_MOD_FT, "delay": 40}
    plain = {"op": I.OP_LEVEL, "mod": 0, "delay": 0}
    g = {0: (arm, [1]), 1: (ft, [2, 3]), 2: (plain, [4]), 3: (plain, [4]), 4: (plain, [0])}
    gaps = {0: [1], 1: [dmin], 2: [5], 3: [5], 4: [5]}
    by = BB.slot_ready_by_arm(g, I, 2, gaps, k)
    a, b = by.get(0, set()), by.get(1, set())
    ok = 1 in a and 2 in a and 3 not in a and b == {2, 3}
    return ok, ("FALLTHROUGH ARM at PC+1: ARM A's slot PC+1 %s, PC+2 %s, PC+3 %s; ARM B's own %s"
                % ("ready" if 1 in a else "NOT READY", "ready" if 2 in a else "NOT READY",
                   "not ready" if 3 not in a else "READY", sorted(b)))


def check_registry(BB, PC, I, rules=None):
    """check 13: the readiness registry (Wilson 11-17). Every rule in branch_budget.READY_RULES
    names its theorem(s) (none only when counterfactual); a proved rule's theorems are all at the
    Lean gate (gate_lean_build.KEY); every rule slot_ready_tagged emits on graphs exercising each
    rule is registered, and each registered rule is exercised; no owed / counterfactual word
    reaches slot_ready (the certificate's ready set)."""
    import gate_lean_build as LB
    rules = BB.READY_RULES if rules is None else rules
    k = PC.load()
    dmin = k["p1b2_plain_min_d"]
    probs = []
    for rid, r in sorted(rules.items()):
        st, th = r.get("status"), tuple(r.get("theorems") or ())
        if st not in ("proved", "owed", "counterfactual"):
            probs.append("%s: status %r" % (rid, st))
        if st != "counterfactual" and not th:
            probs.append("%s: no theorem" % rid)
        if st == "proved":
            probs += ["%s: %s not at the Lean gate" % (rid, t) for t in th
                      if t.split(".")[-1] not in LB.KEY]
    arm = {"op": I.OP_ARM, "mod": 0, "delay": 0}
    ft = {"op": I.OP_ARM, "mod": I.ARM_MOD_FT, "delay": 40}
    plain = {"op": I.OP_LEVEL, "mod": 0, "delay": 0}
    cases = [(_slot_graph(I, dmin), 2), (_slot_graph(I, dmin, pc1_arm=True), 2),
             (_slot_graph(I, dmin), 3),
             (({0: (ft, [1, 2]), 1: (plain, [3]), 2: (plain, [3]), 3: (plain, [0])},
               {0: [1], 1: [5], 2: [5], 3: [5]}), 2),
             (({0: (arm, [1]), 1: (ft, [2, 3]), 2: (plain, [4]), 3: (plain, [4]),
                4: (plain, [0])}, {0: [1], 1: [dmin], 2: [5], 3: [5], 4: [5]}), 2)]
    seen = set()
    for (g, gaps), depth in cases:
        tagged = BB.slot_ready_tagged(g, I, depth, gaps, k)
        ready = BB.slot_ready(g, I, depth, gaps, k)
        seen |= {r for _a, _w, r in tagged}
        unreg = {r for _a, _w, r in tagged if r not in rules}
        probs += ["rule %s emitted, not registered" % r for r in sorted(unreg)]
        good = {w for _a, w, r in tagged if rules.get(r, {}).get("status") == "proved"}
        leak = {w for _a, w, r in tagged if w in ready and w not in good}
        probs += ["word %d ready through an unproved rule" % w for w in sorted(leak)]
    probs += ["rule %s registered, never exercised" % r for r in sorted(set(rules) - seen)]
    st = {}
    for r in rules.values():
        st[r.get("status")] = st.get(r.get("status"), 0) + 1
    return not probs, (("; ".join(probs[:3])) if probs else
                       "%d rules (%s), all exercised; unproved words kept out of ready"
                       % (len(rules), ", ".join("%d %s" % (n, s) for s, n in sorted(st.items()))))


def _ft_slot_image(I, T, d1=80):
    """lane 0: ARM(fall, timeout T, FALLTHROUGH) -> REARM (timeout path, PC+1) -> LEVEL 1 (edge
    path, PC+2) -> LEVEL 0 -> REARM; the other lanes idle (run_arm2.ft_race_image's shape at
    spacing d1). The header goes through pe_isa.d_fields, the encoder the real images use
    (Wilson 11-17: a check never tests a packing the images do not have)"""
    l0 = I.ACT_BASE
    prog = [I.act_arm(1, 0, T, ft=True), I.act(I.OP_REARM, 0, 1, d1),
            I.act(I.OP_LEVEL, I.UO0, 1, d1), I.act(I.OP_LEVEL, I.UO0, 0, d1),
            I.act(I.OP_REARM, 0, 1, d1)]
    lp = l0 + len(prog) * I.ACT_BYTES
    prog.append(I.act(I.OP_REARM, 0, 0, 500))
    headers = [I.hdr(I.UO0, I.UO0, 1, d1, 0, *I.d_fields(d1), l0)]
    for j in range(1, I.N_LANES):
        headers.append(I.hdr(j + 1, j + 1, 0, 500, 0, 200, 240, lp))
    return I.join_image(headers, prog)


#: check 10's end-to-end image (Wilson 11-17): certifies under proved rules only (sweep 11-17:
#: spacing 60 / 80, T >= 35 at B 4 before ft_edge was proved; B 0 since)
TIMEOUT_E2E = (35, 60)


def check_slot_timeout(BB, PC, I):
    """check 10 (Wilson 11-17 ruling, direct readiness): a FALLTHROUGH ARM's timeout word (PC+1)
    is ready only while Buf.p1b2_margin_timeout_scan's premise P1B2_FILL_SCAN + L <= T holds.
    The rule is tested directly, L passed in: for L = 0 and L = 5 the word is in slot_ready and
    the rule drops it at T = FILL + L - 1, keeps it at T = FILL + L (two Ls: the rule reads L,
    not FILL alone). End to end: the image at spacing 60, T 35 certifies and the certificate
    loop called the rule (image_budget's trace, timeout_rule_calls)"""
    import lane_cert as LC
    k = PC.load()
    fill = k["p1b2_fill_scan"]
    prem = LC.premises(k)
    res, bad = {}, []
    for L in (0, 5):
        for T in (fill + L - 1, fill + L):
            g, _p, gaps = LC.build(_ft_slot_image(I, T, d1=60), 0, prem, I)
            fts = LC.ft_paths(g, I)
            if len(fts) != 1:
                bad.append("T %d: %d FALLTHROUGH ARMs (want 1)" % (T, len(fts)))
                continue
            (a, (c1, _c2)), = fts.items()
            ready = BB.slot_ready(g, I, 2, gaps, k)
            if c1 not in ready:
                bad.append("L %d T %d: timeout word %d not in slot_ready before the rule"
                           % (L, T, c1))
                continue
            res[(L, T)] = c1 not in BB.slot_timeout_drop(g, I, ready, {a: L}, k)
    saved = BB.SLOT
    BB.SLOT = 2
    try:
        T, d1 = TIMEOUT_E2E
        r = BB.image_budget(_ft_slot_image(I, T, d1=d1))
    finally:
        BB.SLOT = saved
    calls = r.get("timeout_rule_calls", 0)
    ok = (fill == 9 and not bad and not res[(0, fill - 1)] and res[(0, fill)]
          and not res[(5, fill + 4)] and res[(5, fill + 5)]
          and r["B"] is not None and calls > 0)
    if bad:
        return False, "; ".join(bad[:3])
    return ok, ("FALLTHROUGH timeout word (FILL %d): L 0: T %d %s, T %d %s; L 5: T %d %s, T %d %s; "
                "end to end spacing %d T %d: %s, rule called %d time(s)"
                % (fill, fill - 1, "dropped" if not res[(0, fill - 1)] else "READY",
                   fill, "kept" if res[(0, fill)] else "DROPPED",
                   fill + 4, "dropped" if not res[(5, fill + 4)] else "READY",
                   fill + 5, "kept" if res[(5, fill + 5)] else "DROPPED",
                   d1, T, "B %s" % r["B"] if r["B"] is not None else
                   "NO CERTIFICATE (%s)" % r["reason"][:80], calls))


def check_budget():
    import gen_branch_budget as GB
    cur = GB.current()
    probs = GB.stale(GB.load(), cur)
    cert = sum(1 for v in cur.values() if v["B"] is not None)
    return not probs, ("%d image(s): %d certified, %d A2-UNCERTIFIED; record %s%s"
                       % (len(cur), cert, len(cur) - cert, "current" if not probs else "STALE",
                          "" if not probs else " (" + "; ".join(probs[:3]) + ")")), cur


def main():
    img_dir = sys.argv[1] if len(sys.argv) > 1 else None
    LC, PC, V = _setup(img_dir)
    I = LC._isa()
    print("gate_lane_cert: image module %s" % V.__file__)
    ok1, msg1 = check_spacing(PC, I)
    print("  check 1 %s  %s" % ("GREEN" if ok1 else "RED", msg1))
    fails, out = run_cert(LC, V.image())
    print("  check 2 %s  %s" % ("GREEN" if not fails else "RED",
                               "lane_cert PASS" if not fails else "%d failure(s): %s"
                               % (len(fails), sorted({f[1] for f in fails}))))
    ok3, msg3 = check_ft(LC, V, I)
    print("  check 3 %s  %s" % ("GREEN" if ok3 else "RED", msg3))
    ok4, msg4 = check_coresident(PC, V, I)
    print("  check 4 %s  %s" % ("GREEN" if ok4 else "RED", msg4))
    ok5, msg5, cur5 = check_budget()
    print("  check 5 %s  %s" % ("GREEN" if ok5 else "RED", msg5))
    kills = []
    # THE ARMING PREMISE at its boundary (Wilson 11-14 ruling 1)
    _l0, wb0, dl0, sop0 = arming_case(LC, V, I, 0)
    if wb0 is None:
        kills.append(("M_LC_ARM_EDGE_PASS", False, "no handshake arm_sop found"))
    else:
        n0 = dl0 - wb0
        lp, wbp, _d, _s = arming_case(LC, V, I, n0)
        lf, wbf, _d, _s = arming_case(LC, V, I, n0 + 1)
        lh, wbh, _d, _s = arming_case(LC, V, I, 100)
        print("  arming premise at w%d: armed by EOP + %d, deadline %d (generated); +%d -> %d %s; "
              "+%d -> %d %s; +100 -> %d %s" % (sop0, wb0, dl0, n0, wbp, "late" if lp else "ok",
                                              n0 + 1, wbf, "late" if lf else "ok", wbh,
                                              "late" if lh else "ok"))
        kills.append(("M_LC_ARM_EDGE_PASS", (not lp) and wbp == dl0, "armed exactly at the deadline passes"))
        kills.append(("M_LC_ARM_EDGE_FAIL", lf and wbf == dl0 + 1, "one past the deadline is red"))
        kills.append(("M_LC_ARM_100", lh and wbh == wb0 + 100, "armed at EOP + %d is red" % (wb0 + 100)))
    # M_LC_CERT_STALE: a stored usb_other_R one below the certificate
    orig_load = PC.load
    PC.load = lambda path=PC.PATH: dict(orig_load(path), usb_other_R=orig_load(path)["usb_other_R"] - 1)
    try:
        k4, _m = check_coresident(PC, V, I)
    finally:
        PC.load = orig_load
    kills.append(("M_LC_CERT_STALE", not k4, "a stale certified usb_other_R"))
    # M_LC_BUDGET_STALE: one certified image's recorded B four above its certificate
    import gen_branch_budget as GB
    orig_gl = GB.load
    victim = next((n for n, v in sorted(cur5.items()) if v["B"] is not None), None)

    def bad_load():
        r = orig_gl()
        r = dict(r, images=dict(r["images"]))
        if victim:
            r["images"][victim] = dict(r["images"][victim], B=r["images"][victim]["B"] + 4)
        return r
    GB.load = bad_load
    try:
        k5 = GB.stale(GB.load(), cur5)
    finally:
        GB.load = orig_gl
    kills.append(("M_LC_BUDGET_STALE", bool(victim) and bool(k5), "a stale certified branch budget"))
    # M_LC_NOPIN_ALL: the plain-lane split's classifier off -> every image it moves goes stale
    import branch_budget as BB
    import gen_branch_budget as GB
    rec = GB.load()["images"]
    moved = sorted(n for n, v in rec.items() if v.get("B") is not None and any(
        ln.get("max_late_pin") is not None and ln["max_late_pin"] < ln["max_late"]
        for ln in v["lanes"].values()))
    corpus = dict(GB.corpus())
    BB.NOPIN_MUT = True
    try:
        stale = [n for n in moved if [ln.get("max_late_pin") for _k, ln in sorted(rec[n]["lanes"].items())]
                 != [v.get("max_late_pin") for _k, v in sorted(
                     ((str(l), x) for l, x in BB.image_budget(corpus[n])["lanes"].items()))]]
    finally:
        BB.NOPIN_MUT = False
    print("  plain-lane split (NopSplit): %d image(s) with a lane whose pin-word J is below its "
          "whole-lane J: %s" % (len(moved), ", ".join(moved)))
    kills.append(("M_LC_NOPIN_ALL", bool(moved) and stale == moved,
                  "no-pin words counted: %d / %d moved images stale" % (len(stale), len(moved))))
    # M_LC_ARMGATE_OFF / M_LC_UART_FRAME_SHORT: the arming premise on generic lanes (ArmSplit,
    # branch_budget.arm_gate) -- off, or its frame one bit short (the next start edge one bit
    # earlier: the margin goes negative) -> every image whose pin-word J it lowers goes stale
    # images with a generic lane carrying an arming margin (the USB lane has no max_late_pin)
    gated = sorted(n for n, v in rec.items() if v.get("B") is not None and any(
        "arm_margin" in ln and ln.get("max_late_pin") is not None for ln in v["lanes"].values()))
    pinj = lambda n: [ln.get("max_late_pin") for _k, ln in sorted(rec[n]["lanes"].items())]
    nowj = lambda n: [v.get("max_late_pin") for _k, v in sorted(
        (str(l), x) for l, x in BB.image_budget(corpus[n])["lanes"].items())]
    off = [n for n in gated if pinj(n) != nowj(n)]       # unmutated: the record is current
    for mname, attr, val in (("M_LC_ARMGATE_OFF", "ARMGATE_MUT", True),
                             ("M_LC_UART_FRAME_SHORT", "UART_FRAME_MUT", 1)):
        old = getattr(BB, attr)
        setattr(BB, attr, val)
        try:
            st = [n for n in gated if pinj(n) != nowj(n)]
        finally:
            setattr(BB, attr, old)
        print("  arming premise (ArmSplit, generic lanes): %s -> %d image(s) stale: %s"
              % (mname, len(st), ", ".join(st)))
        kills.append((mname, bool(st) and not off, "%s: %d image(s) stale" % (attr, len(st))))
    # the UART arming margin is a REFUSAL (11-15): uart_rx_board with its REARM before the ARM
    # 70 cycles longer -- the ARM armed after the next start edge can be seen -- is uncertified,
    # by name; M_LC_ARMMARGIN_OFF lets it through
    def neg_margin_case():
        img = corpus["uart_rx_board.hex"]
        g, p, _gp = LC.build(img, 0, LC.premises(PC.load()), I)
        arm = next(w for w in g if g[w][0]["op"] == I.OP_ARM)
        out = bytearray(img)
        for q in p[arm]:
            a = I.ACT_BASE + q * I.ACT_BYTES
            x = I._unpack(I.ACT_FIELDS, bytes(out[a:a + I.ACT_BYTES]), I.ACT_BYTES)
            out[a:a + I.ACT_BYTES] = I.act(x["op"], x["pin"], x["level"], x["delay"] + 70,
                                           count=x["count"], q=x["q"], pinb=x["pinb"], mod=x["mod"])
        return BB.image_budget(bytes(out))
    r = neg_margin_case()
    ok6 = r["B"] is None and "arming margin" in r["reason"]
    print("  check 6 %s  UART arming margin refused: uart_rx_board, REARM + 70 -> %s"
          % ("GREEN" if ok6 else "RED  ", r["reason"][:80]))
    BB.ARMMARGIN_MUT = True
    try:
        rm = neg_margin_case()
    finally:
        BB.ARMMARGIN_MUT = False
    kills.append(("M_LC_ARMMARGIN_OFF", not (rm["B"] is None and "arming margin" in rm["reason"]),
                  "refusal off: check 6 fails (B %s)" % rm["B"]))
    # check 7: the USB lane report's failures are a refusal (11-15): usbrx_main arms its SOP ARM
    # at EOP + 311 against TIPD 78 -> uncertified by name; M_LC_USBFAIL_OFF ignores the report
    r7 = BB.image_budget(corpus["usbrx_main.hex"])
    ok7 = r7["B"] is None and "USB lane: lane_cert report fails" in r7["reason"]
    print("  check 7 %s  USB report failures refused: usbrx_main -> %s"
          % ("GREEN" if ok7 else "RED  ", r7["reason"][:80]))
    BB.USBFAIL_MUT = True
    try:
        r7m = BB.image_budget(corpus["usbrx_main.hex"])
    finally:
        BB.USBFAIL_MUT = False
    kills.append(("M_LC_USBFAIL_OFF", r7m["B"] is not None,
                  "report failures ignored: check 7 fails (B %s)" % r7m["B"]))
    # check 8: the 1.6a queue check with the certified lateness in J is part of A2's verdict
    # (Nate 11-16, option 1): branch_cmp_lo's window certificate fails it, so that certificate is
    # refused and the next proved scheme is tried; whatever A2 returns passes 1.6a.
    # M_LC_QUEUE_OFF skips the check -> the window certificate comes back and fails 1.6a.
    q_img = corpus["branch_cmp_lo_image.hex"]
    r8 = BB.image_budget(q_img)
    why8 = None if r8["B"] is None else BB.queue_refusal(q_img, r8["B"], r8["lanes"])
    BB.QUEUE_MUT = True
    try:
        r8m = BB.image_budget(q_img)
    finally:
        BB.QUEUE_MUT = False
    why8m = None if r8m["B"] is None else BB.queue_refusal(q_img, r8m["B"], r8m["lanes"])
    ok8 = why8 is None and why8m is not None
    print("  check 8 %s  1.6a (lateness in J) in A2's verdict: branch_cmp_lo -> B %s, %s"
          % ("GREEN" if ok8 else "RED  ", r8["B"], (r8["reason"] or "")[:60]))
    kills.append(("M_LC_QUEUE_OFF", why8m is not None,
                  "1.6a check off: B %s fails it: %s" % (r8m["B"], (why8m or "")[:60])))
    # M_LC_EDF_OFF: the EDF response scheme (RespEdfClose.wb_close_edf, Wilson 11-15) never
    # tried -> every image it certifies goes stale (B back to none)
    edf = sorted(n for n, v in rec.items() if "RespEdfClose" in (v.get("reason") or ""))
    BB.EDF_MUT = True
    try:
        st = [n for n in edf if BB.image_budget(corpus[n])["B"] != rec[n]["B"]]
    finally:
        BB.EDF_MUT = False
    print("  EDF response bounds (RespEdfClose.wb_close_edf): %d image(s): %s"
          % (len(edf), ", ".join(edf)))
    kills.append(("M_LC_EDF_OFF", bool(edf) and st == edf,
                  "EDF scheme off: %d / %d EDF-certified images stale" % (len(st), len(edf))))
    # check 9: slot_ready names its theorem's premise (Wilson 11-17)
    ok9, msg9 = check_slot_spacing(BB, PC, I)
    print("  check 9 %s  %s" % ("GREEN" if ok9 else "RED  ", msg9))
    BB.SLOT_SPACING_MUT = True
    try:
        k9, _m = check_slot_spacing(BB, PC, I)
    finally:
        BB.SLOT_SPACING_MUT = False
    kills.append(("M_LC_SLOT_SPACING_OFF", not k9, "PC+2 ready below p1b2_plain_min_d: check 9 red"))
    # check 10: the FALLTHROUGH timeout word's premise (Wilson 11-17)
    ok10, msg10 = check_slot_timeout(BB, PC, I)
    print("  check 10 %s  %s" % ("GREEN" if ok10 else "RED  ", msg10))
    BB.SLOT_TIMEOUT_MUT = True
    try:
        k10, _m = check_slot_timeout(BB, PC, I)
    finally:
        BB.SLOT_TIMEOUT_MUT = False
    kills.append(("M_LC_SLOT_TIMEOUT_OFF", not k10,
                  "timeout word ready at T = FILL + L - 1: check 10 red"))
    # check 11: a branch PC+1's taken target is never ready (Wilson 11-17, rule (1))
    ok11, msg11 = check_slot_branch(BB, PC, I)
    print("  check 11 %s  %s" % ("GREEN" if ok11 else "RED  ", msg11))
    BB.SLOT_BRANCH_MUT = True
    try:
        k11, _m = check_slot_branch(BB, PC, I)
    finally:
        BB.SLOT_BRANCH_MUT = False
    kills.append(("M_LC_SLOT_BRANCH_OFF", not k11,
                  "a branch PC+1's taken target ready: check 11 red"))
    # check 12: no PC+3 for ARM A behind a FALLTHROUGH ARM at PC+1 (Wilson 11-17, rule (2))
    ok12, msg12 = check_slot_pc3(BB, PC, I)
    print("  check 12 %s  %s" % ("GREEN" if ok12 else "RED  ", msg12))
    BB.SLOT_PC3_MUT = True
    try:
        k12, _m = check_slot_pc3(BB, PC, I)
    finally:
        BB.SLOT_PC3_MUT = False
    kills.append(("M_LC_SLOT_PC3_OFF", not k12,
                  "ARM A's PC+3 ready behind a FALLTHROUGH PC+1: check 12 red"))
    # check 13: the readiness registry (Wilson 11-17)
    ok13, msg13 = check_registry(BB, PC, I)
    print("  check 13 %s  %s" % ("GREEN" if ok13 else "RED  ", msg13))
    reg = BB.READY_RULES
    m_noth = {**reg, "pc2_plain": {**reg["pc2_plain"], "theorems": ()}}
    m_lean = {**reg, "pc2_plain": {**reg["pc2_plain"],
                                   "theorems": ("Buf.p1b2_margin_plain_scan_unbuilt",)}}
    m_unreg = {r: v for r, v in reg.items() if r != "ft_edge"}
    for name, rules, what in (("M_LC_REG_NOTHEOREM", m_noth, "a proved rule with no theorem"),
                              ("M_LC_REG_NOTLEAN", m_lean, "a theorem not at the Lean gate"),
                              ("M_LC_REG_UNREG", m_unreg, "an emitted rule not registered")):
        kr, _m = check_registry(BB, PC, I, rules)
        kills.append((name, not kr, "%s: check 13 red" % what))
    BB.REG_LEAK_MUT = True
    try:
        kr, _m = check_registry(BB, PC, I)
    finally:
        BB.REG_LEAK_MUT = False
    kills.append(("M_LC_REG_LEAK", not kr, "owed / counterfactual words reach ready: check 13 red"))
    # check 14: the slot under contention (ContendB, Wilson 11-17)
    ok14, msg14 = check_slot_contend(BB, PC, I)
    print("  check 14 %s  %s" % ("GREEN" if ok14 else "RED  ", msg14))
    BB.CONTEND_MUT = True
    try:
        k14, _m = check_slot_contend(BB, PC, I)
    finally:
        BB.CONTEND_MUT = False
    kills.append(("M_LC_CONTEND_OFF", not k14, "contention ignored (wait 0): check 14 red"))
    # check 15: depth above the buffer's refused; the record / stamp never read the counterfactual
    ok15, msg15 = check_depth(BB, PC, I)
    print("  check 15 %s  %s" % ("GREEN" if ok15 else "RED  ", msg15))
    BB.DEPTH_MUT = True
    try:
        k15, _m = check_depth(BB, PC, I)
    finally:
        BB.DEPTH_MUT = False
    kills.append(("M_LC_DEPTH_GT2", not k15, "slot depth 3 certified: check 15 red"))
    k15b, _m = check_depth(BB, PC, I, texts={"model/cert_stamp.py": "import drain_table as DT\n"})
    kills.append(("M_LC_STAMP_READS_CF", not k15b,
                  "a stamp source importing drain_table: check 15 red"))
    # check 16: the device clock's own error in the host-interval premises
    ok16, msg16 = check_ppm(LC)
    print("  check 16 %s  %s" % ("GREEN" if ok16 else "RED  ", msg16))
    LC.PPM_MUT = True
    try:
        k16, _m = check_ppm(LC)
    finally:
        LC.PPM_MUT = False
    kills.append(("M_LC_PPM_IGNORED", not k16, "SOURCE_PPM left out of tipd_fast: check 16 red"))
    # check 17: an edge-paced lane with no T_ext is refused by name, not a crash
    ok17, msg17 = check_edge_paced(BB)
    print("  check 17 %s  %s" % ("GREEN" if ok17 else "RED  ", msg17))
    BB.EDGEPACED_MUT = True
    try:
        k17, _m = check_edge_paced(BB)
    finally:
        BB.EDGEPACED_MUT = False
    kills.append(("M_LC_EDGEPACED_CRASH", not k17,
                  "queue_refusal lets EdgePacedNoTExt out: check 17 red"))
    # check 18: the FALLTHROUGH disarms are charged in the window bound's S
    ok18, msg18 = check_disarm_s(BB, LC)
    print("  check 18 %s  %s" % ("GREEN" if ok18 else "RED  ", msg18))
    BB.DISARM_S_MUT = True
    try:
        k18, _m = check_disarm_s(BB, LC)
    finally:
        BB.DISARM_S_MUT = False
    kills.append(("M_LC_DISARM_S_OFF", not k18, "the disarms left out of S: check 18 red"))
    # M_LC_FT_UNSEEN / M_LC_FT_NOFLOOR
    orig_ft = PC.arm_is_ft
    PC.arm_is_ft = lambda x, I=None: False
    try:
        k3, _m = check_ft(LC, V, I)
    finally:
        PC.arm_is_ft = orig_ft
    kills.append(("M_LC_FT_UNSEEN", not k3, "no ARM read as FALLTHROUGH"))
    orig_fl = LC.ft_flush_late
    LC.ft_flush_late = lambda B: 0
    try:
        k3, _m = check_ft(LC, V, I)
    finally:
        LC.ft_flush_late = orig_fl
    kills.append(("M_LC_FT_NOFLOOR", not k3, "no lateness floor after the flush"))
    # M_LC_ARMJ_FLOOR
    orig_prem = LC.premises
    LC.premises = lambda k=None: dict(orig_prem(k), arm_j=orig_prem(k)["arm_floor"])
    f, _o = run_cert(LC, V.image())
    LC.premises = orig_prem
    kills.append(("M_LC_ARMJ_FLOOR", any(x[1].startswith("arm w") and x[1] not in
                                         {y[1] for y in fails} for x in f),
                  "arm_j premise at the floor"))
    # M_LC_LATE_SOP: a 40-cycle nop before the first handshake copy's arm_sop (the word after
    # our EOP's READBIT): its chain from our EOP grows by 40
    p = V.device_program()
    g = LC.lane_graph(V.image(), I.USB_LANE, I)
    target = None
    for w in sorted(g):
        x = g[w][0]
        if x["op"] == I.OP_READBIT and any(LC.arm_kind(g[s][0], I) == "edge" for s in g[w][1]):
            target = w - min(g)
            break
    if target is not None:
        p2 = p[:target + 1] + [I.act(I.OP_LEVEL, I.PIN_NONE, 0, 40)] + p[target + 1:]
        why = ""
        try:
            f, _o = run_cert(LC, V.image(prog=p2))
            hit = any(x[1].startswith("armed late") and x[1] not in {y[1] for y in fails}
                      for x in f)
        except ValueError as ex:
            # the encoder refuses the shifted image (pe_isa: a field / the store does not
            # fit): the must-fire did not run -- recorded in its verdict line, never a pass
            hit, why = False, " (image not built: %s)" % str(ex)[:80]
    else:
        hit, why = False, " (no handshake arm_sop found)"
    kills.append(("M_LC_LATE_SOP", hit, "a 40-cycle nop before a handshake copy's arm_sop" + why))
    # M_LC_SHIFTI_FULL
    orig_sp = PC.spacing_of
    PC.spacing_of = lambda x, I=None: x["delay"]
    ok, _m = check_spacing(PC, I)
    PC.spacing_of = orig_sp
    kills.append(("M_LC_SHIFTI_FULL", not ok, "spacing_of reads the whole field"))
    # M_LC_LAT_IGNORED: zero lateness everywhere -> the known first-sample failures vanish
    orig_cert = LC.certificate

    def no_lat(*a, **kw):
        r = orig_cert(*a, **kw)
        if r is None:
            return r
        lat, Z, Rr = r
        return {w: 0 for w in lat}, Z, Rr
    LC.certificate = no_lat
    try:
        k3, _m = check_ft(LC, V, I)
    finally:
        LC.certificate = orig_cert
    kills.append(("M_LC_LAT_IGNORED", not k3, "lateness zeroed: check 3 loses the flush floor"))
    for name, killed, what in kills:
        ok_txt = ("PASS (as required)" if name.endswith("_PASS") else "RED (killed)")
        print("  must-fire %-18s %s  %s" % (name, ok_txt if killed else "SURVIVED", what))
    teeth = all(k for _n, k, _w in kills)
    green = (ok1 and not fails and ok3 and ok4 and ok5 and ok6 and ok7 and ok8 and ok9 and ok10
             and ok11 and ok12 and ok13 and ok14 and ok15 and ok16 and ok17 and ok18)
    verdict = "PASSED" if (green and teeth) else ("FAILED (must-fire survived)" if not teeth
                                                   else "FAILED")
    print("GATE lane-cert: %s" % verdict)
    return 0 if verdict == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main())
