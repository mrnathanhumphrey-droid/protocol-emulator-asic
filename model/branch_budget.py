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

#: must-fire switch (gate_lane_cert M_LC_NOPIN_ALL): count every word as touching a pin
NOPIN_MUT = False
#: must-fire switches (gate_lane_cert): M_LC_ARMGATE_OFF -- no generic-lane ARM gated;
#: M_LC_UART_FRAME_SHORT -- the frame premise this many bits short
ARMGATE_MUT = False
UART_FRAME_MUT = 0


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


def image_budget(img, iters=80):
    """{'B': int or None, 'reason': str, 'lanes': {lane: {...}}} for `img`"""
    I = LC._isa()
    k = PC.load()
    prem = LC.premises(k)
    progs = I.lane_programs(img)
    lanes = sorted(progs)
    usb = PC.usb_receive_live(progs, I)
    graphs = {l: LC.build(img, l, prem, I) for l in lanes}
    usb_n, usb_rmax = 0, None
    if usb:
        with contextlib.redirect_stdout(io.StringIO()):
            LC.full_report(img, "image")
        last = LC.full_report.last
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
    for _ in range(iters):
        lat, rmax = {}, {}
        for l in generic:
            g, preds, gaps = graphs[l]
            # a FALLTHROUGH ARM on a generic lane (the poset compiler's `else continue`):
            # as on the USB lane (lane_cert.full_report) -- the edge flushes, so PC+2's head is
            # valid by its release + flush_refill_late + B (FlushLate.flush_head_late); the
            # timeout's decision only disarms, so PC+1 waits one more decision (disarm_noDec)
            fts = LC.ft_paths(g, I)
            floor = {c2: LC.ft_flush_late(B) for _c1, c2 in fts.values() if c2 in g}
            xr = {c1: 1 for c1, _c2 in fts.values() if c1 in g}
            cert = LC.certificate(g, preds, gaps, k, B, 0, floor=floor, xr=xr, rbase=R[l])
            if cert is None:
                return {"B": None, "reason": "lane %d: no lateness certificate at B = %d" % (l, B),
                        "lanes": {}}
            lat[l] = cert[0]
            rmax[l] = max(cert[2].values())
        if usb:
            rmax[I.USB_LANE] = usb_rmax
        Rn = {}
        for y in generic:
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
        Bn = k["l_refill"] * (late + usb_n)
        if Bn == B and Rn == R:
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
                if ag:
                    out[l]["arm_margin"] = min(ag.values())
                # per word (the poset compiler's arming check reads it; not in the record)
                out[l]["lat"] = dict(lat[l])
            if usb:
                # the word-class split (ArmSplit.arm_release_bus): receive words carry their own
                # lateness; an ARM word's lateness shows only in its arming check's margin
                # R: the USB lane's certified response past its lateness (Wilson 11-15, R_usb;
                # lane_cert: max over words of Rr - L, Rr from PrioResp.prio_resp)
                out[I.USB_LANE] = {"R": usb_R, "late_words": None, "max_late": usb_late,
                                   "max_late_rx": usb_rx_late, "arm_margin": usb_arm_margin}
            return {"B": B, "reason": "certified", "lanes": out}
        if Bn > LIMIT or any(v > LIMIT for v in Rn.values()):
            return {"B": None, "reason": "no finite B (B %d -> %d, max R %d)"
                    % (B, Bn, max(Rn.values())), "lanes": {}}
        B, R = Bn, Rn
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
