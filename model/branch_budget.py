"""branch_budget -- the branch-1 budget B of an image, CERTIFIED per image (Wilson 11-14, option 1).

B bounds the port cycles the lanes' urgent (branch-1) refills can take from another lane's refill
in any window of 23 + B cycles; every head-valid theorem takes it as `hB`. Under (b'), a branch-1
refill goes only to a released lane with an empty head -- a LATE word -- and a lane takes at most
one per late word (Br1Once.br1_once / br1_count). This evaluates, per image, a joint fixpoint of
three proved bounds:
  * each lane's per-word lateness L: GapRun.head_late_gap's certificate (lane_cert.certificate),
    with response Rr = L + R_lane;
  * each lane's response R_lane: RespWinN.wb_bound_win_n -- K = 3M + S + 3, R = K - 1, M the other
    lanes' decisions in a K-window (a lane with min span G(m) >= K + 1 + its worst response is
    decided at most m times; lane_cert's other-lanes rule), S = 0 under (b');
  * B = l_refill x (late words per 23 + B window, summed over lanes: lane_cert.br1_window_count).
The USB lane (an image using the USB receive) keeps its priority response and its own premises:
its figures come from lane_cert.full_report.
No fixpoint (B or R growing without bound) -> "no finite B": the image is A2-UNCERTIFIED with
that reason, not refused. Static, seconds.
"""
from __future__ import annotations

import contextlib
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "test")]
import lane_cert as LC  # noqa: E402
import proof_constants as PC  # noqa: E402

LIMIT = 400          # B or a response this large: no fixpoint

#: THE GUARANTEED SLOT (Wilson 11-16: one requester, one buffer, 1b at depth 2 and F1's PC+2).
#: None = off (the record; nothing moves). An int = the buffer depth: every ARM's next words are
#: fetched while the ARM is the head, through a reserved slot, so they are READY at release
#: (lane_cert.certificate's `ready`) -- a plain ARM's successors to that depth (not the two-pin
#: LEVEL ARM, which P1b excludes), a FALLTHROUGH ARM's PC+1 and PC+2. The cost: each ARM's
#: fetch takes the port from the other lanes' refills, charged in B (l_refill per fetch, per
#: 23 + B window, summed over lanes) -- the term both schemes read. [assumed: the bound's Lean
#: brick is owed; this is the certificate side, labelled]
SLOT = None
#: fetches charged per ARM (Wilson's term: one)
SLOT_PER_ARM = 1
#: counterfactual switch: charge a lane's own ARM fetches to its own B too (the image-wide B).
#: Off = the proofs' shape: Port.charge counts only refills for lanes OTHER than y, and every hB
#: is per y, so the slot's term is per victim lane
SLOT_SELF = False


def slot_ready(g, I, depth):
    """{word}: the words the guaranteed slot makes ready at release on one lane"""
    out = set()
    for a in g:
        x = g[a][0]
        if x["op"] != I.OP_ARM or x["mod"] & I.ARM_MOD_LEVEL2:
            continue
        if x["mod"] & I.ARM_MOD_FT:
            out |= {w for w in g[a][1] if w in g}         # PC+1 (timeout), PC+2 (edge)
            continue
        front = set(g[a][1])
        for _ in range(depth):
            out |= {w for w in front if w in g}
            front = {s for w in front if w in g for s in g[w][1]}
    return out


def arm_window_count(g, gaps, lat, W, I):
    """The most ARM words on one path whose releases fit a W-cycle window (each ARM's slot fetch
    happens while it is the head: by its release plus its lateness) -- lane_cert.br1_window_count's
    walk, counting ARMs."""
    arms = {w for w in g if g[w][0]["op"] == I.OP_ARM}
    best = 0
    for s in arms:
        budget = W - 1 + lat[s]
        stack, seen = [(s, 0, 1)], set()
        while stack:
            w, dist, n = stack.pop()
            best = max(best, n)
            if (w, dist) in seen:
                continue
            seen.add((w, dist))
            step = sum(gaps[w])
            for nx in g[w][1]:
                d2 = dist + step
                if d2 <= budget:
                    stack.append((nx, d2, n + (1 if nx in arms else 0)))
    return best

#: must-fire switch (gate_lane_cert M_LC_NOPIN_ALL): count every word as touching a pin
NOPIN_MUT = False
#: must-fire switches (gate_lane_cert): M_LC_ARMGATE_OFF -- no generic-lane ARM gated;
#: M_LC_UART_FRAME_SHORT -- the frame premise this many bits short
ARMGATE_MUT = False
UART_FRAME_MUT = 0
#: must-fire switch (gate_lane_cert M_LC_ARMMARGIN_PASS): a negative UART arming margin not refused
ARMMARGIN_MUT = False
#: must-fire switch (gate_lane_cert M_LC_USBFAIL_OFF): the USB lane report's failures ignored
USBFAIL_MUT = False
#: must-fire switch (gate_lane_cert M_LC_QUEUE_OFF): 1.6a with the lateness in J not applied
QUEUE_MUT = False

#: the record fields 1.6a's J reads (program_a2.lane_set -> lane_j); gen_branch_budget writes
#: the same ones
RECORD_LANE_KEYS = ("max_late", "max_late_pin", "R", "max_late_rx", "arm_margin")


def queue_refusal(img, B, lanes):
    """None, or the reason A2 refuses: condition 1.6a (program_a2.queue_slot, r <= T on every
    lane) with each lane's certified lateness in J (J = 1 + max_late, lane_j) -- Wilson 11-15,
    the UART blocker ruling item 1: a failure that exists only with the lateness in J is a
    certification question. The entry is not in the record yet (this IS the record's source),
    so it is written to a one-image record that queue_slot reads (budget_path). Only when some
    lane is late: at J = 1 the check is pe_asm's, at the proved J."""
    if QUEUE_MUT or not any((v or {}).get("max_late") for v in lanes.values()):
        return None
    import json
    import tempfile
    if os.path.join(HERE, "a2") not in sys.path:
        sys.path.append(os.path.join(HERE, "a2"))
    import program_a2 as P
    ent = {"sha": P.image_sha(img), "B": B,
           "lanes": {str(l): {k: v[k] for k in RECORD_LANE_KEYS if k in v}
                     for l, v in lanes.items()}}
    fd, tmp = tempfile.mkstemp(suffix=".json", prefix="a2_q16a_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"images": {"live": ent}}, fh)
        q = P.queue_slot(img, lateness=True, budget_path=tmp)
    finally:
        os.remove(tmp)
    bad = sorted(((int(ln), v) for ln, v in q.items() if not v["ok"]), key=lambda kv: kv[0])
    if not bad:
        return None
    return ("1.6a queue check fails with the certified lane lateness in J: %s (J = 1 + max_late, "
            "lane_j; Wilson 11-15 UART ruling item 1)"
            % "; ".join("lane %d r %s > T %s (J %d)" % (ln, v["r"], v["T"], 1 + lanes[ln]["max_late"])
                      for ln, v in bad))


def uart_peer_err():
    """the peer's bit error band, per mille -- READ: the band the receiver is verified to
    decode back-to-back (test/run_uartrx.ERRS; gate_admissibility_1_6.UART_BAND)"""
    import run_uartrx
    return max(abs(e) for e in run_uartrx.ERRS)


def arm_gate(img, lane, graph, lat, I):
    """{ARM word: margin} for a generic lane's UART-receive ARMs (Wilson 11-15: the arming
    premise gated beyond the USB lane). ArmSplit.arm_release_bus is lane-generic: an ARM's
    successor is released at E + 1, E the first edge after the ARM's release, whatever the
    ARM's writeback time before E. So an ARM's lateness reaches no sample iff, on every frame,
      lower: it is armed no earlier than the line goes idle (the stop bit's start, slowest
             peer, seen), so the first edge after arming is the next start edge; and
      upper: it is armed (release + L + 4, the USB lane's armed-by bound) before that next
             start edge can be seen (fastest peer: frame bits after the previous start).
    The shape (one straight loop from the ARM back to itself, no other ARM, every word with an
    upper gap, >= 1 SHIFTIN sampling the ARM's pin at the header's bit t) is read from the
    image; the frame = start + those data bits + one stop is the ASSUMED peer framing (8N1 on
    today's images); the peer's bit is t * (1 +- uart_peer_err / 1000) (read). Margin = the
    smaller of the two slacks; gated iff >= 0. A lane of any other shape: nothing gated."""
    from fractions import Fraction
    import math
    g, _preds, gaps = graph
    bit = I.read_header(img, lane)["t"]
    skew = LC.SYNC_MAX - LC.SYNC_MIN
    out = {}
    for a, (x, succ) in g.items():
        if LC.arm_kind(x, I) != "edge" or PC.arm_is_ft(x, I) or LC.arm_half(x, I):
            continue
        path, w = [], (succ[0] if len(succ) == 1 else None)
        while w is not None and w != a and len(path) <= len(g):
            path.append(w)
            s = g[w][1]
            w = s[0] if len(s) == 1 else None
        if w != a or any(g[p][0]["op"] == I.OP_ARM for p in path):
            continue
        # ⛔ THE UART RECEIVE SHAPE EXACTLY (found by the drain table: probe_cov_pindiv's lane
        # 3 -- a RISING ARM, a READBIT, SHIFTINs at the bit -- passed the looser test): the ARM
        # waits for the start bit's FALL (idle high, l_armedge 0), and the loop holds only
        # timed no-ops (LEVEL on a pin outside N_PINS), SHIFTINs on the ARM's pin and the REARM
        if x["level"] != 0 or not all(
                (g[p][0]["op"] == I.OP_LEVEL and g[p][0]["pin"] >= I.N_PINS)
                or (g[p][0]["op"] == I.OP_SHIFTIN and g[p][0]["pin"] == x["pin"])
                or g[p][0]["op"] == I.OP_REARM for p in path):
            continue
        data = [p for p in path if g[p][0]["op"] == I.OP_SHIFTIN and g[p][0]["pin"] == x["pin"]
                and g[p][0]["delay"] == bit and not g[p][0]["mod"] & I.MOD_SELF_TIMED]
        ups = [LC.upper_gaps(g[p][0], I) for p in path]
        if not data or any(u is None for u in ups):
            continue
        frame = len(data) + 2 - UART_FRAME_MUT
        err = Fraction(uart_peer_err(), 1000)
        # releases from the previous start edge as seen (E_seen): the successor at E_seen + 1
        # (arm_release), then the path's release gaps -- lower (word_gaps) and upper bounds
        lo = 1 + sum(sum(gaps[p]) for p in path)
        hi = 1 + sum(ups)
        armed_hi = hi + lat[a] + 4
        # E_seen - E_true in [SYNC_MIN, SYNC_MAX]: the next start seen >= E_seen + frame bits
        # (fastest) - skew; the stop bit's start seen <= E_seen + (frame - 1) bits (slowest) + skew
        edge_min = math.floor(frame * bit * (1 - err)) - skew
        idle_max = math.ceil((frame - 1) * bit * (1 + err)) + skew
        out[a] = min(edge_min - 1 - armed_hi, lo - idle_max)
    return {} if ARMGATE_MUT else out


def no_pin(x, I):
    """a word whose dispatch touches no pin (NopSplit.lean, Wilson 11-15): a LEVEL on a pin
    outside N_PINS (`pin_real` false: PIN_NONE) with mod = 0 (no complementary pinb, no SE0).
    Its lateness does not move its successor's release (`ord_late_free`) and is invisible on
    the wire, so the lane's observable J is taken over the other words (`lane_j_pin`)."""
    if NOPIN_MUT:
        return False
    return x["op"] == I.OP_LEVEL and x["pin"] >= I.N_PINS and x["mod"] == 0


def _decisions(g, gaps, K, rmax, mmax=40):
    """at most this many decisions of a lane in a K-window (lane_cert's other-lanes rule)"""
    for m in range(1, mmax + 1):
        if LC.span_min(g, gaps, m) >= K + 1 + rmax:
            return m
    return None


#: must-fire switch (gate_lane_cert M_LC_EDF_OFF): the EDF response scheme never tried
EDF_MUT = False


def _edf_R(y, lanes, graphs, rmax, lmax, ds, mmax=40):
    """RespEdfClose.wb_close_edf's per-lane bound: R y = 3 * sum_{z != y} m(y, z) + S + 2 with
    S = 0 under (b'), m(y, z) the least m >= 1 whose span G_z(m) (lane_cert.span_min: the least
    release advance over m consecutive writebacks, `hspan`) meets
        G_z(m) >= ds y - ds z + Q z - L y          (`hG`)
    Q z = z's response including its lateness (rmax), L y = y's largest lateness. None if no
    m <= mmax meets it."""
    M = 0
    for z in lanes:
        if z == y:
            continue
        g, _p, gaps = graphs[z]
        need = ds[y] - ds[z] + rmax[z] - lmax.get(y, 0)
        m = 1
        while LC.span_min(g, gaps, m) < need:
            m += 1
            if m > mmax:
                return None
        M += m
    return 3 * M + 0 + 3 - 1


def image_budget(img, iters=80, premise_gaps=None, ready=None):
    """The certificate with the window response bound (RespWinN.wb_bound_win_n), and, when that
    finds none, with the EDF response bounds (RespEdfClose.wb_close_edf, Wilson 11-15): one
    scheme per image, so each certificate rests on one closure theorem. The record's images
    certified by the window scheme keep their numbers."""
    r = _image_budget(img, iters, premise_gaps, ready, "window")
    if r["B"] is not None or EDF_MUT:
        return r
    r2 = _image_budget(img, iters, premise_gaps, ready, "edf")
    if r2["B"] is None:
        return dict(r, reason="%s; EDF response bounds: %s" % (r["reason"], r2["reason"]))
    return r2


def _image_budget(img, iters=80, premise_gaps=None, ready=None, scheme="window"):
    """{'B': int or None, 'reason': str, 'lanes': {lane: {...}}} for `img`.
    `premise_gaps` {lane: {ARM word: cycles}}: a NAMED peer premise (model/premises.py,
    Wilson 11-15 call 1) -- the earliest the ARM's edge can come after its release, so its
    successor's release gap is at least that (ArmSplit.arm_release_bus: released at E + 1).
    `ready` {lane: {word}}: the prefetch counterfactual (lane_cert.certificate). Both default
    to none: the record (gen_branch_budget) never passes them."""
    premise_gaps = premise_gaps or {}
    ready = ready or {}
    I = LC._isa()
    k = PC.load()
    prem = LC.premises(k)
    progs = I.lane_programs(img)
    lanes = sorted(progs)
    usb = PC.usb_receive_live(progs, I)
    if scheme == "edf" and usb:
        # one closure theorem per image: wb_close_edf needs EVERY lane, the USB lane included,
        # to meet its conditions; the USB lane's bound is PrioResp's, so a USB image is not
        # certified by the EDF scheme
        return {"B": None, "reason": "not applied to a USB image (the USB lane's response is "
                "PrioResp's; one closure theorem per image)", "lanes": {}}
    graphs = {l: LC.build(img, l, prem, I) for l in lanes}
    if SLOT:
        ready = {l: set(ready.get(l, ())) | slot_ready(graphs[l][0], I, SLOT) for l in lanes}
    for l, pg in premise_gaps.items():
        for w, gp in pg.items():
            if l in graphs and w in graphs[l][2]:
                graphs[l][2][w] = [max(graphs[l][2][w][0], gp)] + graphs[l][2][w][1:]
    usb_n, usb_rmax = 0, None
    if usb:
        with contextlib.redirect_stdout(io.StringIO()):
            ufails = LC.full_report(img, "image")
        last = LC.full_report.last
        # the USB lane's own report lists its failures (an arm_sop armed after the host's
        # earliest SOP, a late first sample, the turnaround, ...): any one of them means its
        # certificate's premises fail, so the image is not certified (found 11-15: usbbuf_usb and
        # usbrx_main armed their SOP ARM at EOP + 417 / 311 against TIPD 78 and stayed certified)
        if ufails and not USBFAIL_MUT:
            return {"B": None, "reason": "USB lane: lane_cert report fails: %s"
                    % "; ".join(sorted({"%s (%s)" % (w, sch) for sch, w in ufails}))[:200],
                    "lanes": {}}
        if last.get("br1_B") is None:
            return {"B": None, "reason": "USB lane: no certificate", "lanes": {}}
        usb_n, usb_rmax = last["usb_refills"], last["usb_maxRr"]
        usb_R = last["usb_R"]
        ug, ugaps, ulat = last["usb_graph"]
        graphs[I.USB_LANE] = (ug, None, ugaps)
        usb_late = max(ulat.values()) if ulat else 0
        usb_rx_late = last.get("usb_rx_late", 0)
        usb_arm_margin = min(last.get("arm_margins") or [0])
    generic = [l for l in lanes if not (usb and l == I.USB_LANE)]
    B = k["l_refill"] * usb_n
    R = {l: k["R_base"] for l in generic}
    SB = {l: 0 for l in generic}          # the guaranteed slot's charge on lane l (per victim)
    for _ in range(iters):
        lat, rmax = {}, {}
        for l in generic:
            g, preds, gaps = graphs[l]
            # a FALLTHROUGH ARM on a generic lane (the poset compiler's `else continue`):
            # as on the USB lane (lane_cert.full_report) -- the edge flushes, so PC+2's head is
            # valid by its release + flush_refill_late + B (FlushLate.flush_head_late); the
            # timeout's decision only disarms, so PC+1 waits one more decision (disarm_noDec)
            fts = LC.ft_paths(g, I)
            Bl = B + SB[l]
            floor = {c2: LC.ft_flush_late(Bl) for _c1, c2 in fts.values() if c2 in g}
            xr = {c1: 1 for c1, _c2 in fts.values() if c1 in g}
            cert = LC.certificate(g, preds, gaps, k, Bl, 0, floor=floor, xr=xr, rbase=R[l],
                                  ready=ready.get(l))
            if cert is None:
                return {"B": None, "reason": "lane %d: no lateness certificate at B = %d%s"
                        % (l, Bl, " (slot charge %d)" % SB[l] if SB[l] else ""), "lanes": {}}
            lat[l] = cert[0]
            rmax[l] = max(cert[2].values())
        if usb:
            rmax[I.USB_LANE] = usb_rmax
        Rn = {}
        for y in generic:
            if scheme == "edf":
                ds = {l: I.read_header(img, l)["dsched"] for l in lanes}
                lmax = {l: max(lat[l].values()) for l in generic}
                Re = _edf_R(y, lanes, graphs, rmax, lmax, ds)
                if Re is None:
                    return {"B": None, "reason": "lane %d: no EDF span meets ds + Q - L" % y,
                            "lanes": {}}
                Rn[y] = Re
                continue
            K = k["lemmaA_window"]
            for _ in range(60):
                M = 0
                for l in lanes:
                    if l == y:
                        continue
                    g, _p, gaps = graphs[l]
                    m = _decisions(g, gaps, K, rmax[l])
                    if m is None:
                        return {"B": None, "reason": "lane %d: decided too often for any window "
                                "(response of lane %d unbounded)" % (l, y), "lanes": {}}
                    M += m
                Kn = 3 * M + 0 + 3
                if Kn == K:
                    break
                K = Kn
            Rn[y] = K - 1
        late = sum(LC.br1_window_count(graphs[l][0], graphs[l][2], lat[l], 23 + B) for l in generic)
        if usb and late:
            return {"B": None, "reason": "a non-USB lane is late beside the USB receive (its refills "
                    "would charge the USB lane: not covered)", "lanes": {}}
        SBn = {l: 0 for l in generic}
        if SLOT:
            per = {l: SLOT_PER_ARM * arm_window_count(graphs[l][0], graphs[l][2], lat[l],
                                                      23 + B + SB[l], I) for l in generic}
            if usb and any(per.values()):
                return {"B": None, "reason": "guaranteed slot: a non-USB lane's ARM fetches "
                        "beside the USB receive (they would charge the USB lane: not covered)",
                        "lanes": {}}
            if usb:
                # the USB lane's ARMs fetch through the slot too (their cost is charged; no
                # readiness is claimed for them: the USB lane's figures are full_report's)
                per[I.USB_LANE] = SLOT_PER_ARM * arm_window_count(ug, ugaps, ulat, 23 + B, I)
            # Slot.chargeS_le: SLOT_CHARGE per fetch for another lane (proof_constants)
            SBn = {l: k["slot_charge"] * sum(n for z, n in per.items() if z != l or SLOT_SELF)
                   for l in generic}
        Bn = k["l_refill"] * (late + usb_n)
        if Bn == B and Rn == R and SBn == SB:
            out = {}
            for l in generic:
                ag = arm_gate(img, l, graphs[l], lat[l], I)
                gated = {w for w, m in ag.items() if m >= 0}
                out[l] = {"R": R[l], "late_words": sorted(w for w, v in lat[l].items() if v),
                          "max_late": max(lat[l].values()),
                          # the plain-lane split (NopSplit.ord_late_free) and the arming
                          # premise (ArmSplit, arm_gate): lateness over the words that touch a
                          # pin, less the ARMs whose arming check holds
                          "max_late_pin": max([v for w, v in lat[l].items()
                                               if not no_pin(graphs[l][0][w][0], I)
                                               and w not in gated] or [0])}
                if SLOT:
                    out[l]["slot_B"] = SB[l]
                if ag:
                    out[l]["arm_margin"] = min(ag.values())
                # per word (the poset compiler's arming check reads it; not in the record)
                out[l]["lat"] = dict(lat[l])
            # a UART-shaped lane whose ARM may be armed AFTER the next start edge can be seen
            # misses that frame: its certificate's premise (ArmSplit's hedge) fails, so the image
            # is not certified (found 11-15: a pre-ARM pad of 70 gave margin -3 and still J 1)
            neg = sorted((v["arm_margin"], l) for l, v in out.items() if v.get("arm_margin", 0) < 0)
            if neg and not ARMMARGIN_MUT:
                m, l = neg[0]
                return {"B": None, "reason": "lane %d: UART arming margin %d < 0 -- the ARM may be "
                        "armed after the next start edge can be seen (branch_budget.arm_gate)"
                        % (l, m), "lanes": {}}
            if usb:
                # the word-class split (ArmSplit.arm_release_bus): receive words carry their own
                # lateness; an ARM word's lateness shows only in its arming check's margin
                # R: the USB lane's certified response past its lateness (Wilson 11-15, R_usb;
                # lane_cert: max over words of Rr - L, Rr from PrioResp.prio_resp)
                out[I.USB_LANE] = {"R": usb_R, "late_words": None, "max_late": usb_late,
                                   "max_late_rx": usb_rx_late, "arm_margin": usb_arm_margin}
            # 1.6a with the certified lateness in J (Wilson 11-15): one verdict with the stamp
            why = queue_refusal(img, B, out)
            if why:
                return {"B": None, "reason": why, "lanes": {}}
            return {"B": B, "reason": "certified" if scheme == "window" else
                    "certified (EDF response bounds, RespEdfClose.wb_close_edf)", "lanes": out}
        if Bn > LIMIT or any(v > LIMIT for v in Rn.values()):
            return {"B": None, "reason": "no finite B (B %d -> %d, max R %d)"
                    % (B, Bn, max(Rn.values())), "lanes": {}}
        B, R, SB = Bn, Rn, SBn
    return {"B": None, "reason": "no fixpoint in %d rounds (B %d)" % (iters, B), "lanes": {}}


def lane_j(entry, lane):
    """A lane's dispatch jitter from a certified record entry (gen_branch_budget): 1 + its
    largest certified per-word lateness (GapRun.head_late_gap; J = 1 exactly when no word of the
    lane is late). None when the image has no finite B (A2-UNCERTIFIED)."""
    if entry.get("B") is None:
        return None
    ln = entry.get("lanes", {}).get(str(lane), entry.get("lanes", {}).get(lane))
    return None if ln is None else 1 + ln["max_late"]


def lane_j_pin(entry, lane):
    """A lane's OBSERVABLE dispatch jitter (Wilson 11-15, the plain-lane split, NopSplit): 1 +
    its largest certified lateness over the words that touch a pin -- a no-pin word's
    lateness reaches no sample and no later release. None if not recorded / no finite B."""
    if entry.get("B") is None:
        return None
    ln = entry.get("lanes", {}).get(str(lane), entry.get("lanes", {}).get(lane))
    return None if ln is None or ln.get("max_late_pin") is None else 1 + ln["max_late_pin"]


def lane_j_rx(entry, lane):
    """The USB lane's receive-word jitter (Wilson 11-14, the word-class split, ArmSplit): 1 + the
    largest certified lateness over its receive words; None if not recorded / no finite B."""
    if entry.get("B") is None:
        return None
    ln = entry.get("lanes", {}).get(str(lane), entry.get("lanes", {}).get(lane))
    return None if ln is None or ln.get("max_late_rx") is None else 1 + ln["max_late_rx"]


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(HERE, "a2"))
    import image_universe as U
    import program_a2 as P
    for name, img in U.images():
        bl = P.branch_lanes(img)
        if not bl:
            continue
        r = image_budget(img)
        print("%-28s branch lanes %-10s B = %-5s %s" % (name, ",".join(map(str, bl)),
              r["B"] if r["B"] is not None else "-", r["reason"]))
