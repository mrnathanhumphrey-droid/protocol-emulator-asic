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
            cert = LC.certificate(g, preds, gaps, k, B, 0, rbase=R[l])
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
            out = {l: {"R": R[l], "late_words": sorted(w for w, v in lat[l].items() if v),
                       "max_late": max(lat[l].values())} for l in generic}
            if usb:
                # the word-class split (ArmSplit.arm_release_bus): receive words carry their own
                # lateness; an ARM word's lateness shows only in its arming check's margin
                out[I.USB_LANE] = {"R": None, "late_words": None, "max_late": usb_late,
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
