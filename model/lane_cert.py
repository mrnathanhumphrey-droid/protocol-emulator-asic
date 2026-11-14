"""lane_cert -- the stage 6 checker (branch brick): evaluates the per-retirement conditions of the
Lean theorems on an image's reachable words, and the USB deadline chains, statically.

What each number is checked against (lean/JLane/JLane):
  gaps        GapRun.gp / Armed.arm_release / BrRefine (a branch's W) / UsbLane.reanFloor
              (a USB receive bit's re-anchor floor) -- per writeback, read off the words;
  Z, L, Rr    GapRun.head_late_gap's certificate (Rr <= Z; Rr + D* + B <= Z at a branch;
              Z x + D* + B <= gp x + Z x2; L from HD / HN) with Rr = L + 2 from
              PrioResp.prio_resp (+ the usb_wins tail under (b'), Wilson 11-13) -- a fixpoint
              over the word graph, reported DIVERGENT when there is none;
  other lanes RespSpan.wb_close_span: m consecutive USB writebacks advance its release by G(m);
              R_y + 1 + R_u <= G(m), 3 (m + 3) + S + 3 <= R_y + 1;
  deadlines   PrioResp.ts_chain (a release is the earlier release plus the gaps in between)
              + prio_resp (writeback <= release + L + 4).
PREMISES (read / assumed, cited): the edge premises of the ARM kinds and the bus timing below.
Static: no simulation. The Lean theorems are general; this file is where an image's numbers
meet them. Numbers come from proof_constants / clock.py / the spec table cited, never typed.
"""
from __future__ import annotations

import math
import os
import sys
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "test")]
import clock  # noqa: E402
import proof_constants as PC  # noqa: E402

# ---- premises: USB 2.0 (usb_20.pdf, SHA-256 pinned in clock.py) and the input synchroniser ----
#: TLEOPR, Table 7-10 (PDF p.211, printed 183): the shortest EOP SE0 a receiver must accept --
#: the SE0 our pins are guaranteed to see (Wilson 11-13: 39 cycles, not the 56 / 74 readings)
USB_TLEOPR_NS = 670
#: TLDRATE max, Table 7-10 (PDF p.210): the fastest LS host bit, for "2 bit times" of TIPD
USB_TLDRATE_MAX = 1_522_500
#: the input synchroniser (project.v l.258-318, read): a pin edge is seen 1..2 cycles after it
#: lands (q0 samples within one cycle; rise = q1 & ~q2)
SYNC_MIN, SYNC_MAX = 1, 2
#: TRSPIPD1, §7.1.19.1: a device's response starts within 6.5 bit times of the host's EOP
USB_TRSPIPD1_HALF_BITS = 13


def premises(k=None):
    k = k or PC.load()
    f = clock.hz()
    bit = clock.usb_bit_cycles()
    tleopr = math.floor(Fraction(USB_TLEOPR_NS) * f / 10 ** 9)
    tipd_fast = math.floor(Fraction(clock.USB_TIPD_BITS * f, USB_TLDRATE_MAX))
    return {
        "bit": bit,
        # an ARM's release gap floor: release >= writeback + 2 (arm_release, edge >= wb + 1),
        # writeback >= release + 2 (a dispatch) -- every ARM kind
        "arm_floor": 4,
        # arm_j: its J edge comes TLEOPR after the SE0 began; arm_j is released one cycle after
        # arm_se0 saw that SE0; the two detections differ by at most SYNC_MAX - SYNC_MIN
        "arm_j": tleopr - (SYNC_MAX - SYNC_MIN),
        # the host's next SOP is >= 2 fast bit times after an EOP (TIPD, §7.1.18.1)
        "tipd_fast": tipd_fast,
        "deadline_sop": math.floor(Fraction(clock.USB_TIPD_BITS * bit) / Fraction(1015, 1000))
                        + 2 - 2,
        "trspipd1": USB_TRSPIPD1_HALF_BITS * bit // 2,
        "rean_floor": PC.rean_floor(bit, k),
        "tleopr": tleopr,
        # a receive bit's timestamp drifts from the bus bit by at most 7 bits (bit stuffing:
        # an edge every <= 7 bits re-anchors it) at the host's rate tolerance (TLDRATE max)
        "rean_drift": math.ceil(Fraction(7 * bit) * (Fraction(USB_TLDRATE_MAX, 1_500_000) - 1)),
    }


def next_sop_fetch_deadline(B, nop_gap, k=None, prem=None):
    """Wilson 11-14, the corrected next-SOP deadline: the latest arm_sop retirement after the bus
    EOP at which the first receive word after it (behind a nop of release gap `nop_gap`) is still
    fetched on time. GapRun HN with Z = Rr = usb_rr_on_time, L = 0: arm_sop's gap before the
    SOP (seen >= EOP + tipd_fast + SYNC_MIN, released one past it) + nop_gap >= sop_fetch_slack
    + B; arm_sop retires within usb_rr_on_time + (dispatch_cycles - 1) of its release
    (prio_resp). Assumes arm_sop itself on time; the per-path first-sample test is exact."""
    k = k or PC.load()
    prem = prem or premises(k)
    release = prem["tipd_fast"] + SYNC_MIN + 1 + nop_gap - (k["sop_fetch_slack"] + B)
    return release + k["usb_rr_on_time"] + k["dispatch_cycles"] - 1


# ---- the word graph ----------------------------------------------------------------------------
def _isa():
    return PC._isa()


def arm_kind(x, I):
    if x["op"] != I.OP_ARM:
        return None
    if x["mod"] & I.ARM_MOD_LEVEL2:
        return "se0"
    return "edge"


def lane_graph(img, lane, I=None):
    """{word: (action, [successors])} for every word reachable from `lane`'s base."""
    I = I or _isa()
    ws = dict(PC.lane_words(img, lane, I))
    base = min(ws)
    g = {}
    for w, x in ws.items():
        if x["op"] == I.OP_REARM:
            succ = [base] if x["level"] else [w]       # looping: the base; chaining: itself
        elif x["op"] in I.BRANCH_OPS:
            succ = [w + 1, I.branch_target(x)]
        else:
            succ = [w + 1]
        g[w] = (x, [s for s in succ if s in ws])
    return g


def word_gaps(x, after_arm, after_se0, prem, I):
    """the release gaps of the word's writebacks, in order (the last one is its retirement)"""
    op = x["op"]
    if op in I.BRANCH_OPS:
        return [I.branch_wait(x)]
    if op == I.OP_ARM:
        if arm_kind(x, I) == "edge" and after_se0:
            return [prem["arm_j"]]
        return [prem["arm_floor"]]
    st = (op in (I.OP_SHIFT, I.OP_SHIFTIN) and x["mod"] & I.MOD_SELF_TIMED) or op == I.OP_SHIFTI
    if op == I.OP_SHIFTI:
        d = x["delay"] & 0xFF
        return [d] * 8
    if st and op == I.OP_SHIFTIN:
        return [min(x["delay"], prem["rean_floor"])] * max(1, x["count"])
    if st:
        return [x["delay"]] * 8
    d = x["delay"] - (1 if after_arm else 0)
    return [max(d, 0)]


def build(img, lane, prem, I=None):
    I = I or _isa()
    g = lane_graph(img, lane, I)
    preds = {w: [] for w in g}
    for w, (_x, succ) in g.items():
        for s in succ:
            preds[s].append(w)
    gaps = {}
    for w, (x, _s) in g.items():
        after_arm = any(g[p][0]["op"] == I.OP_ARM for p in preds[w])
        # arm_j: an edge ARM entered only from an SE0 (two-pin level) ARM -- its J edge ends that SE0
        after_se0 = bool(preds[w]) and all(arm_kind(g[p][0], I) == "se0" for p in preds[w])
        gaps[w] = word_gaps(x, after_arm, after_se0, prem, I)
    return g, preds, gaps


def span_min(g, gaps, m):
    """G(m): the least sum of m consecutive writeback gaps along any path (RespSpan.hspan)"""
    memo = {}

    def best(w, i, n):
        if n == 0:
            return 0
        key = (w, i, n)
        if key in memo:
            return memo[key]
        gs = gaps[w]
        if i < len(gs):
            r = gs[i] + best(w, i + 1, n - 1)
        else:
            nxt = g[w][1]
            r = min((best(s, 0, n) for s in nxt), default=10 ** 9)
        memo[key] = r
        return r
    return min(best(w, i, m) for w in g for i in range(len(gaps[w])))


def certificate(g, preds, gaps, k, B, tail, iters=200):
    """GapRun's certificate on the word graph with Rr = L + 2 (+ tail): returns (lat, Z, Rr) or
    None when the values keep growing (no fixpoint: no certificate exists for this image)."""
    I = _isa()
    D, HS = k["dstar"], k["head_slack"]
    npf = {w: g[w][0]["op"] in I.BRANCH_OPS for w in g}
    gp = {w: gaps[w][-1] for w in g}
    # the release distance between consecutive retirements a -> b: a's retiring gap plus b's
    # held writebacks (GapRun.rd)
    rd = {(a, b): gp[a] + sum(gaps[b][:-1]) for a in g for b in g[a][1]}
    lat = {w: 0 for w in g}
    Z = {w: 0 for w in g}
    for _ in range(iters):
        Rr = {w: lat[w] + 2 + (tail if lat[w] > 0 else 0) for w in g}
        Zn = {}
        for w in g:
            z = Rr[w] + (D + B if npf[w] else 0)
            for p in preds[w]:
                z = max(z, Z[p] + D + B - rd[(p, w)])
            Zn[w] = z
        ln = {}
        for c in g:
            v = 0
            for b in preds[c]:
                if npf[b]:
                    v = max(v, Rr[b] + HS + B - gp[b])
                for a in preds[b]:
                    v = max(v, Zn[a] + HS + B - rd[(a, b)] - gp[b])
            ln[c] = v
        if ln == lat and Zn == Z:
            return lat, Z, Rr
        if max(ln.values()) > 10 ** 4:
            return None
        lat, Z = ln, Zn
    return None


def upper_gaps(x, I):
    """the release gaps' UPPER bound for a word on a deadline chain (exact for fixed delays);
    None where no upper bound holds (an ARM, a USB receive: their releases are the bus's)"""
    op = x["op"]
    if op in I.BRANCH_OPS:
        return I.branch_wait(x)
    if op == I.OP_ARM or (op == I.OP_SHIFTIN and x["mod"] & I.MOD_SELF_TIMED):
        return None
    if op == I.OP_SHIFTI:
        return 8 * (x["delay"] & 0xFF)
    if op in (I.OP_SHIFT, I.OP_SHIFTIN) and x["mod"] & I.MOD_SELF_TIMED:
        return None                                   # a buffer send: its length is the data's
    return x["delay"]


def is_our_j(x, I):
    """our EOP's J: the pair driven to J (act_level_pair(DM, DP, 1, d))"""
    return x["op"] == I.OP_LEVEL and x["level"] == 1 and x["pinb"] != 0


def chains_into(g, preds, s, I, prem, depth=24):
    """every chain back from word `s` to an EOP anchor, as (kind, offset): the release of `s`
    is at most `offset` after the bus EOP's end (ts_chain), or (None, None) when a chain meets
    a word with no upper gap before an anchor."""
    out = []

    def walk(w, acc, d):
        for p in preds[w]:
            x = g[p][0]
            if arm_kind(x, I) == "edge" and preds[p] and all(
                    arm_kind(g[q][0], I) == "se0" for q in preds[p]):
                out.append(("host EOP", SYNC_MAX + 1 + acc))      # arm_j: J seen <= SYNC_MAX
                continue
            if is_our_j(x, I):
                out.append(("our EOP", (upper_gaps(x, I) or 0) + acc - 1))  # J driven >= rel+1
                continue
            if x["op"] == I.OP_SHIFTIN and x["mod"] & I.MOD_SELF_TIMED:
                # a receive word: its packet's EOP ends >= its last bit's release (mid-bit,
                # +/- drift) + half a bit + the SE0 (TLEOPR); the next word is released a bit
                # after that last bit
                dd = x["delay"]
                out.append(("packet EOP", dd - dd // 2 - prem["tleopr"] + prem["rean_drift"]
                            + acc))
                continue
            u = upper_gaps(x, I)
            if u is None or d == 0:
                out.append((None, None))
                continue
            walk(p, acc + u, d - 1)
    walk(s, 0, depth)
    return out


def full_report(img, name="image"):
    I = _isa()
    k = PC.load()
    prem = premises(k)
    u = I.USB_LANE
    g, preds, gaps = build(img, u, prem, I)
    sops = [w for w in g if arm_kind(g[w][0], I) == "edge" and not (
        preds[w] and all(arm_kind(g[q][0], I) == "se0" for q in preds[w]))]
    off, unanch = {}, {}
    for s in sops:
        ch = chains_into(g, preds, s, I, prem)
        offs = [o for kd, o in ch if kd]
        off[s] = max(offs) if offs else None
        unanch[s] = sum(1 for kd, _o in ch if kd is None)
        # the SOP is seen >= tipd_fast + SYNC_MIN after the EOP; arm_sop's gap is to one past it
        if off[s] is not None and not unanch[s]:
            gaps[s] = [max(prem["arm_floor"], prem["tipd_fast"] + SYNC_MIN + 1 - off[s])]
    print("lane_cert: %s  (clock %d Hz, LS bit %d)" % (name, clock.hz(), prem["bit"]))
    print("  premises: arm floor %d, arm_j %d (TLEOPR %d ns - sync skew), TIPD fast %d, "
          "next-SOP deadline %d, TRSPIPD1 %d, rean floor %d, sync %d..%d"
          % (prem["arm_floor"], prem["arm_j"], USB_TLEOPR_NS, prem["tipd_fast"],
             prem["deadline_sop"], prem["trspipd1"], prem["rean_floor"], SYNC_MIN, SYNC_MAX))
    fails = []
    for sched, tail in (("b'", 2), ("shipped", 0)):
        cert = certificate(g, preds, gaps, k, 0, tail)
        print("== scheduler %s" % sched)
        if cert is None:
            print("  USB certificate: DIVERGENT (no fixpoint)")
            fails.append((sched, "certificate"))
            continue
        lat, Z, Rr = cert
        late = sorted((w, v) for w, v in lat.items() if v)
        print("  USB certificate: max Z %d, max Rr %d; %d late words: %s"
              % (max(Z.values()), max(Rr.values()), len(late),
                 ", ".join("w%d+%d" % kv for kv in late)))
        # release after writeback (wb_close's hrel; a non-ARM word's retiring gap >= Rr + 3)
        bad = [w for w in g if g[w][0]["op"] != I.OP_ARM and gaps[w][-1] < Rr[w] + 3]
        print("  release-after-writeback: %s" % ("OK" if not bad else "FAILS at " +
              ", ".join("w%d (gap %d, Rr %d)" % (w, gaps[w][-1], Rr[w]) for w in bad)))
        if bad:
            fails.append((sched, "hrel"))
        # every edge ARM armed before its edge: writeback <= release + L + 4 < edge
        for w in sorted(g):
            if arm_kind(g[w][0], I) != "edge":
                continue
            ok = lat[w] + 4 < gaps[w][0] - 1
            if not ok:
                fails.append((sched, "arm w%d" % w))
            if w not in off:
                print("  arm_j w%d: armed by release + %d, J edge >= release + %d  %s"
                      % (w, lat[w] + 4, gaps[w][0] - 1, "OK" if ok else "LATE"))
        # next-SOP deadline and the first sample
        for s in sops:
            if off[s] is None or unanch[s]:
                print("  arm_sop w%d: %s" % (s, "no EOP anchor on %d chain(s): boot / untimed entry"
                                             % unanch[s] if unanch[s] else "no anchored chain"))
                continue
            wb = off[s] + lat[s] + 4
            nop_gap = min(gaps[n][-1] for n in g[s][1])
            fdl = next_sop_fetch_deadline(0, nop_gap, k, prem)
            ok = wb <= fdl
            f = [n2 for n in g[s][1] for n2 in g[n][1]]
            fl = max((lat[n2] for n2 in f), default=0)
            print("  arm_sop w%d: retired <= EOP + %d (fetch deadline %d; plain %d) %s; SOP gap %d; "
                  "first sample lateness %d %s" % (s, wb, fdl, prem["deadline_sop"],
                                                   "OK" if ok else "LATE", gaps[s][0], fl,
                                                   "OK" if fl == 0 else "LATE"))
            if not ok:
                fails.append((sched, "next-SOP w%d" % s))
            if fl:
                fails.append((sched, "first sample after w%d" % s))
        # turnaround: from a host EOP (arm_j) to our first transmitted edge
        worst = None
        for j in g:
            x = g[j][0]
            if not (arm_kind(x, I) == "edge" and preds[j] and
                    all(arm_kind(g[q][0], I) == "se0" for q in preds[j])):
                continue
            stack = [(n, SYNC_MAX + 1) for n in g[j][1]]
            seen = set()
            while stack:
                w, acc = stack.pop()
                if (w, acc) in seen or acc > 10 ** 4:
                    continue
                seen.add((w, acc))
                xw = g[w][0]
                if xw["op"] == I.OP_SHIFTI or (xw["op"] == I.OP_SHIFT and
                                                xw["mod"] & I.MOD_SELF_TIMED):
                    t = acc + lat[w] + 3
                    worst = t if worst is None else max(worst, t)
                    continue
                up = upper_gaps(xw, I)
                if up is None:
                    continue
                for n in g[w][1]:
                    stack.append((n, acc + up))
        if worst is not None:
            ok = worst <= prem["trspipd1"]
            print("  turnaround: our first edge <= host EOP + %d (TRSPIPD1 %d) %s"
                  % (worst, prem["trspipd1"], "OK" if ok else "LATE"))
            if not ok:
                fails.append((sched, "turnaround"))
        # the other lanes (RespSpan.wb_close_span, S = 0 under (b'))
        if sched == "b'":
            ru = max(Rr.values())
            for m in range(1, 9):
                G = span_min(g, gaps, m)
                ry = 3 * (m + 3) + 0 + 3 - 1
                if G >= ry + 1 + ru:
                    print("  other lanes: R = %d (USB decided <= %d times per window; "
                          "G(%d) = %d >= R + 1 + R_u %d)" % (ry, m, m, G, ru))
                    break
            else:
                print("  other lanes: no m <= 8 meets the span rule")
                fails.append((sched, "other lanes"))
    print("lane_cert: %s" % ("PASS" if not fails else "FAIL: %s" % fails))
    return fails

def report(img, name="image"):
    I = _isa()
    k = PC.load()
    prem = premises(k)
    u = I.USB_LANE
    print("lane_cert: %s  (clock %d Hz, LS bit %d)" % (name, clock.hz(), prem["bit"]))
    print("  premises: arm floor %d, arm_j %d (TLEOPR %d ns - sync skew), TIPD fast %d, "
          "deadline next-SOP %d, TRSPIPD1 %d, rean floor %d"
          % (prem["arm_floor"], prem["arm_j"], USB_TLEOPR_NS, prem["tipd_fast"],
             prem["deadline_sop"], prem["trspipd1"], prem["rean_floor"]))
    g, preds, gaps = build(img, u, prem, I)
    results = {}
    for sched, S, tail in (("b'", 0, 2), ("shipped", None, 0)):
        cert = certificate(g, preds, gaps, k, 0, tail)
        if cert is None:
            print("  [%s] USB certificate: DIVERGENT (no fixpoint)" % sched)
            results[sched] = None
            continue
        lat, Z, Rr = cert
        late = {w: v for w, v in lat.items() if v}
        print("  [%s] USB certificate: max Z %d, max Rr %d; late words %d: %s"
              % (sched, max(Z.values()), max(Rr.values()), len(late),
                 ", ".join("w%d+%d" % kv for kv in sorted(late.items())[:12])))
        results[sched] = cert
    return g, preds, gaps, results, prem


if __name__ == "__main__":
    # optional: a directory holding the image module (usbdev.py) to certify, first on the path
    if len(sys.argv) > 1:
        sys.path.insert(0, sys.argv[1])
    import usbdev as V
    print("  image module:", V.__file__)
    full_report(V.image(), "usbdev")
