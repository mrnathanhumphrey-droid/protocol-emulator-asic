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
#: the host's next token after an unanswered packet: "the host will wait at least 18 bit times for
#: a response to start before it will start a new transaction" (7.1.19.1; agent 1 11-14 -- the 16
#: in that paragraph is the device's own timeout). Read from clock.usb_host_next_min_cycles.


def premises(k=None):
    k = k or PC.load()
    f = clock.hz()
    bit = clock.usb_bit_cycles()
    # TLEOPR in cycles at the clock band's SLOW edge (the fewest cycles; agent 1's
    # clock.usb_se0q_bounds upper end), the conservative side for every use below
    tleopr = clock.usb_se0q_bounds()[1]
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
        # the latest a legal responder's SOP starts after a token's EOP (TRSPIPD2, slowest rate)
        "resp_window": clock.usb_resp_window_cycles(),
        # the shortest packet a SOP starts: SYNC + PID = 16 bits, at the fastest host rate
        "min_packet": math.floor(Fraction(16 * bit * 1_500_000, USB_TLDRATE_MAX)),
    }


def retry_fetch_deadline(B, nop_gap, k=None, prem=None):
    """Wilson 11-14, correction A's window inequality: the latest TOP arm_sop retirement after
    OUR EOP (a packet that expects the host's handshake) at which the first receive word is
    fetched before the host's earliest retry token (its timeout, 16 bit times at the fastest
    rate). Same GapRun HN rule as next_sop_fetch_deadline, anchored on that token."""
    k = k or PC.load()
    prem = prem or premises(k)
    tok = clock.usb_host_next_min_cycles()          # 18 bit times at the fastest rate (7.1.19.1)
    release = tok + SYNC_MIN + 1 + nop_gap - (k["sop_fetch_slack"] + B)
    return release + k["usb_rr_on_time"] + k["dispatch_cycles"] - 1


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


def arm_half(x, I):
    """HALF (ARM count[0]): the rebase is the edge + l_t/2 (pe_engine.v l.1630 ck_rebase)"""
    return x["op"] == I.OP_ARM and bool(x["count"] & getattr(I, "ARM_CNT_HALF", 0))


def arm_qual(x, I):
    """QUAL (ARM count[1], USB lane): the edge fires only after an SE0 run >= USB_N_J"""
    return x["op"] == I.OP_ARM and bool(x["count"] & getattr(I, "ARM_CNT_QUAL", 0))


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
        elif PC.arm_is_ft(x, I):
            succ = [w + 1, w + 2]                       # timeout: PC+1; edge (flush): PC+2
        else:
            succ = [w + 1]
        g[w] = (x, [s for s in succ if s in ws])
    return g


def word_gaps(x, after_arm, after_se0, prem, I, half_t=0):
    """the release gaps of the word's writebacks, in order (the last one is its retirement).
    `half_t`: the lane's l_t // 2, added to a HALF ARM's release (rebase edge + l_t/2)."""
    op = x["op"]
    if op in I.BRANCH_OPS:
        return [I.branch_wait(x)]
    if op == I.OP_ARM:
        g = prem["arm_j"] if (arm_kind(x, I) == "edge" and after_se0) else prem["arm_floor"]
        g += half_t if arm_half(x, I) else 0
        if PC.arm_is_ft(x, I):
            # ArmFT.arm_release_T: released at min(edge + 1, D), D = ts + a_dly (less the
            # rebase's cycle after an ARM): the gap is at least the smaller
            g = min(g, x["delay"] - (1 if after_arm else 0))
        return [g]
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
    half_t = I.read_header(img, lane)["t"] // 2
    preds = {w: [] for w in g}
    for w, (_x, succ) in g.items():
        for s in succ:
            preds[s].append(w)
    gaps = {}
    for w, (x, _s) in g.items():
        after_arm = any(g[p][0]["op"] == I.OP_ARM for p in preds[w])
        # arm_j: an edge ARM entered only from an SE0 (two-pin level) ARM -- its J edge ends that SE0
        after_se0 = bool(preds[w]) and all(arm_kind(g[p][0], I) == "se0" for p in preds[w])
        gaps[w] = word_gaps(x, after_arm, after_se0, prem, I, half_t)
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


def certificate(g, preds, gaps, k, B, tail, iters=200, floor=None, xr=None):
    """GapRun's certificate on the word graph with Rr = L + 2 (+ tail): returns (lat, Z, Rr) or
    None when the values keep growing (no fixpoint: no certificate exists for this image).
    `floor`: a lateness floor per word (a FALLTHROUGH ARM's PC+2, refilled after its flush);
    `xr`: extra response cycles per word (a FALLTHROUGH timeout's PC+1: the disarm cycle)."""
    floor = floor or {}
    xr = xr or {}
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
        Rr = {w: lat[w] + 2 + (tail if lat[w] > 0 else 0) + xr.get(w, 0) for w in g}
        Zn = {}
        for w in g:
            z = Rr[w] + (D + B if npf[w] else 0)
            for p in preds[w]:
                z = max(z, Z[p] + D + B - rd[(p, w)])
            Zn[w] = z
        ln = {}
        for c in g:
            v = floor.get(c, 0)
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


def br1_window_count(g, gaps, lat, W):
    """The most branch-1 refills the USB lane can take in any window of W cycles under (b'):
    one per late word (a refill goes only to a released lane with an empty head, and fills it),
    during that word's lateness; two late words on a path are at least the gaps between their
    releases apart, less the first one's lateness."""
    late = {w for w in g if lat[w] > 0}
    best = 0
    for s in late:
        budget = W - 1 + lat[s]
        stack = [(s, 0, 1)]                      # (word, release distance from s, late words)
        seen = set()
        while stack:
            w, dist, k = stack.pop()
            best = max(best, k)
            if (w, dist) in seen:
                continue
            seen.add((w, dist))
            step = sum(gaps[w])                  # all of w's writebacks before its successor
            for n in g[w][1]:
                d2 = dist + step
                if d2 > budget:
                    continue
                stack.append((n, d2, k + (1 if n in late else 0)))
    return best


def br1_budget_fixpoint(g, gaps, lat, k):
    """B for the other lanes: l_refill per USB branch-1 refill in a 23 + B window, to a fixpoint."""
    B = k["br1_budget"]
    for _ in range(20):
        n = br1_window_count(g, gaps, lat, 23 + B)
        nb = k["l_refill"] * n
        if nb == B:
            return B, n
        B = nb
    return None, None


def ft_flush_late(B):
    """FlushRestart.flush_head_refill: after a flush at f the lane's head is captured from a CAP
    state within the 3 cycles to Wf plus the 23 + B window (the last such state f + 3 + (23 + B)
    - 1), valid the cycle after; the view releases the lane at f + 1 (FlushStep.tsF). So the
    PC+2 word's head is valid by its release + this."""
    return PC.load()["flush_refill_late"] + B         # FlushLate.flush_head_late


def ft_paths(g, I):
    """{FALLTHROUGH ARM: (PC+1, PC+2)} -- the timeout and the edge continuations"""
    return {a: (a + 1, a + 2) for a in g if PC.arm_is_ft(g[a][0], I)}


def upper_gaps(x, I):
    """the release gaps' UPPER bound for a word on a deadline chain (exact for fixed delays);
    None where no upper bound holds (an ARM, a USB receive: their releases are the bus's)"""
    op = x["op"]
    if op in I.BRANCH_OPS:
        return I.branch_wait(x)
    if PC.arm_is_ft(x, I):
        return x["delay"]                             # min(edge + 1, D) <= D (arm_release_T)
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


def chains_into(g, preds, s, I, prem, depth=24, half_t=0):
    """every chain back from word `s` to an EOP anchor, as (kind, offset): the release of `s`
    is at most `offset` after the bus EOP's end (ts_chain), or (None, None) when a chain meets
    a word with no upper gap before an anchor."""
    out = []

    def walk(w, acc, d):
        for p in preds[w]:
            x = g[p][0]
            if PC.arm_is_ft(x, I) and w == p + 1:
                out.append(("FT timeout", acc + x["delay"]))   # correction A's path
                continue
            if arm_kind(x, I) == "edge" and preds[p] and all(
                    arm_kind(g[q][0], I) == "se0" for q in preds[p]):
                data = all(any(g[r][0]["op"] == I.OP_SHIFTIN and g[r][0]["mod"] & I.MOD_PAIR
                               for r in preds[q]) for q in preds[p])
                out.append(("host EOP, DATA" if data else "host EOP",
                            SYNC_MAX + 1 + (half_t if arm_half(x, I) else 0) + acc))
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
    fts = ft_paths(g, I)
    # ArmFT: the edge flushes, so PC+2 is refilled from empty (flush_head_refill, B = 0 on the
    # USB lane's own certificate); the timeout's decision only disarms, so PC+1 waits one more
    # decision (disarm_noDec)
    floor = {c2: ft_flush_late(0) for _c1, c2 in fts.values() if c2 in g}
    xr = {c1: 1 for c1, _c2 in fts.values() if c1 in g}
    certs = {}
    half_t = I.read_header(img, u)["t"] // 2
    sops = [w for w in g if arm_kind(g[w][0], I) == "edge" and w not in fts and not (
        preds[w] and all(arm_kind(g[q][0], I) == "se0" for q in preds[w]))]
    off, offd, unanch = {}, {}, {}
    for s in sops:
        ch = chains_into(g, preds, s, I, prem, half_t=half_t)
        offs = [o for kd, o in ch if kd and kd not in ("FT timeout", "host EOP, DATA")]
        dat = [o for kd, o in ch if kd == "host EOP, DATA"]
        off[s] = max(offs) if offs else None
        offd[s] = max(dat) if dat else None
        unanch[s] = sum(1 for kd, _o in ch if kd is None)
        # the SOP is seen >= tipd_fast + SYNC_MIN after the EOP; arm_sop's gap is to one past it
        if off[s] is not None and not unanch[s]:
            gs = max(prem["arm_floor"], prem["tipd_fast"] + SYNC_MIN + 1 - off[s])
            if offd[s] is not None:      # after an unanswered DATA: the host's next >= 18 bits
                gs = min(gs, max(prem["arm_floor"], clock.usb_host_next_min_cycles() + SYNC_MIN
                                 + 1 - offd[s]))
            gaps[s] = [gs + (half_t if arm_half(g[s][0], I) else 0)]
    # a FALLTHROUGH ARM on a reply's SOP: its edge is >= TIPD after the anchoring EOP; its
    # release is min(edge + 1, deadline) (arm_release_T)
    egap, ftoff = {}, {}
    for a in fts:
        ch = chains_into(g, preds, a, I, prem, half_t=half_t)
        offs = [o for kd, o in ch if kd]
        if offs and not any(kd is None for kd, _o in ch):
            ftoff[a] = max(offs)
            egap[a] = max(prem["arm_floor"], prem["tipd_fast"] + SYNC_MIN + 1 - max(offs))
            gaps[a] = [min(egap[a], g[a][0]["delay"])]
        c2 = a + 2
        if c2 in g and arm_kind(g[c2][0], I) == "se0":
            # PREMISE (FT edge path): PC+2 is released at the reply's SOP edge + 1; the reply's
            # EOP SE0 starts >= min_packet after that edge and is seen >= SYNC_MIN later
            gaps[c2] = [max(gaps[c2][0], prem["min_packet"] + SYNC_MIN)]
    print("lane_cert: %s  (clock %d Hz, LS bit %d)" % (name, clock.hz(), prem["bit"]))
    print("  premises: arm floor %d, arm_j %d (TLEOPR %d ns - sync skew), TIPD fast %d, "
          "next-SOP deadline %d, TRSPIPD1 %d, rean floor %d, sync %d..%d"
          % (prem["arm_floor"], prem["arm_j"], USB_TLEOPR_NS, prem["tipd_fast"],
             prem["deadline_sop"], prem["trspipd1"], prem["rean_floor"], SYNC_MIN, SYNC_MAX))
    fails = []
    for sched, tail in (("b'", 2), ("shipped", 0)):
        cert = certificate(g, preds, gaps, k, 0, tail, floor=floor, xr=xr)
        certs[sched] = cert
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
            if w in fts:
                # PREMISE (FT on a reply's SOP): it may be armed after the reply began -- it then
                # fires on a later D+ rise inside the reply; it must be armed before the reply can
                # end (TIPD + one minimum packet after the anchoring EOP)
                if w in ftoff:
                    armed = ftoff[w] + lat[w] + 4 + xr.get(w, 0)
                    need = prem["tipd_fast"] + prem["min_packet"]
                    okf = armed < need
                    print("  FT ARM w%d: armed <= EOP + %d, the reply ends >= EOP + %d  %s"
                          % (w, armed, need, "OK" if okf else "LATE"))
                    if not okf:
                        fails.append((sched, "ft arm w%d" % w))
                continue
            ok = lat[w] + 4 + xr.get(w, 0) < egap.get(w, gaps[w][0]) - 1
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
            wb = off[s] + lat[s] + 4 + xr.get(s, 0)
            if arm_half(g[s][0], I):
                # HALF: the half bit is in the ARM's own release; the first sample is PC+1
                nop_gap, f = half_t, list(g[s][1])
            else:
                nop_gap = min(gaps[n][-1] for n in g[s][1])
                f = [n2 for n in g[s][1] for n2 in g[n][1]]
            fdl = next_sop_fetch_deadline(0, nop_gap, k, prem)
            ok = wb <= fdl
            if offd[s] is not None:
                wbd = offd[s] + lat[s] + 4 + xr.get(s, 0)
                rdl = retry_fetch_deadline(0, nop_gap, k, prem)
                okd = wbd <= rdl
                print("  arm_sop w%d after an unanswered DATA: retired <= EOP + %d (host's next "
                      "packet deadline %d) %s" % (s, wbd, rdl, "OK" if okd else "LATE"))
                if not okd:
                    fails.append((sched, "after-DATA w%d" % s))
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
            stack = [(n, SYNC_MAX + 1 + (half_t if arm_half(x, I) else 0)) for n in g[j][1]]
            seen = set()
            while stack:
                w, acc = stack.pop()
                if (w, acc) in seen or acc > 10 ** 4:
                    continue
                seen.add((w, acc))
                xw = g[w][0]
                if xw["op"] == I.OP_SHIFTI or (xw["op"] == I.OP_SHIFT and
                                                xw["mod"] & I.MOD_SELF_TIMED):
                    t = acc + lat[w] + 3 + xr.get(w, 0)
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
        # the branch-1 budget the USB lane's late words impose on the other lanes (b')
        Bn = None
        if sched == "b'":
            Bn, nev = br1_budget_fixpoint(g, gaps, lat, k)
            if Bn is None:
                print("  branch-1 budget: no fixpoint")
                fails.append((sched, "br1 budget"))
            else:
                print("  branch-1 budget: <= %d USB refill(s) per %d-cycle window -> B = %d "
                      "(proof_constants br1_budget %d)" % (nev, 23 + Bn, Bn, k["br1_budget"]))
        # the other lanes (RespSpan.wb_close_span, S = 0 under (b'))
        if sched == "b'":
            ru = max(Rr.values())
            # S: the no-decision cycles a window can hold -- here the FALLTHROUGH disarms
            # (LemmaAN.lemmaA_n counts them; disarm_noDec), at most one per FALLTHROUGH ARM on
            # a path within the window
            ftlat = {w: (1 if w in fts else 0) for w in g}
            for m in range(1, 9):
                G = span_min(g, gaps, m)
                S = 0
                for _ in range(20):
                    ry = 3 * (m + 3) + S + 3 - 1
                    Sn = br1_window_count(g, gaps, ftlat, ry + 1) if fts else 0
                    if Sn == S:
                        break
                    S = Sn
                if G >= ry + 1 + ru:
                    print("  other lanes: R = %d (USB decided <= %d times per window, S = %d "
                          "disarm cycle(s); G(%d) = %d >= R + 1 + R_u %d)"
                          % (ry, m, S, m, G, ru))
                    Bc = Bn if Bn is not None else k["br1_budget"]
                    cs = ry + k["pending_slack"] + Bc
                    print("  co-resident spacing for other lanes: R %d + %d + B %d = %d "
                          "(proof_constants coresident_usb %d) %s"
                          % (ry, k["pending_slack"], Bc, cs, k["coresident_usb"],
                             "OK" if cs <= k["coresident_usb"] else "RULE TOO LOW"))
                    if cs > k["coresident_usb"]:
                        fails.append((sched, "coresident_usb"))
                    break
            else:
                print("  other lanes: no m <= 8 meets the span rule")
                fails.append((sched, "other lanes"))
    # the FALLTHROUGH ARMs (ArmFT; agent 1's pe_isa refusals, re-checked on the image)
    print("== FALLTHROUGH ARMs: %d (encoding %s)" % (len(fts), PC.ft_rule(I)))
    cb = certs.get("b'")
    for a in sorted(fts):
        c1, c2 = fts[a]
        probs = []
        if c1 not in g:
            probs.append("no PC+1")
        if c2 not in g:
            probs.append("no PC+2")
        elif g[c2][0]["op"] in (I.OP_SHIFT, I.OP_SHIFTIN):
            probs.append("PC+2 w%d is a SHIFT/SHIFTIN (refused: refilled after the flush)" % c2)
        if arm_half(g[a][0], I):
            probs.append("HALF with FALLTHROUGH (never combined: PC+2 is not prefetched)")
        lt = cb[0].get(c2) if cb is not None and c2 in g else None
        # the edge path: PC+2 is released at edge + 1 and written back by release + L + 4; if it
        # is an ARM it must be armed before the replying packet can end: its SE0 starts at least
        # one minimum packet after the SOP edge
        if lt is not None and g[c2][0]["op"] == I.OP_ARM:
            armed = 1 + lt + 4
            okp = armed < prem["min_packet"]
            print("  ARM w%d edge path: PC+2 w%d armed <= edge + %d, the reply's SE0 >= edge + %d %s"
                  % (a, c2, armed, prem["min_packet"], "OK" if okp else "LATE"))
            if not okp:
                probs.append("PC+2 w%d armed late on the edge path" % c2)
        print("  ARM w%d: timeout -> w%d released <= ts + %d, + 1 disarm cycle; edge -> flush, "
              "w%d head valid <= release + %s %s" % (a, c1, g[a][0]["delay"], c2,
                                                    "-" if lt is None else lt,
                                                    "OK" if not probs else "REFUSED: " +
                                                    "; ".join(probs)))
        for pr in probs:
            fails.append(("FT", "w%d %s" % (a, pr)))
    # correction A (Wilson 11-14): an ARM with a timeout (the FALLTHROUGH handshake wait) must not
    # time out before the host's latest legal handshake start (window_end = TRSPIPD1 after our
    # EOP), and its timeout path to TOP's arm_sop must meet the retry-token deadline
    tos = sorted(fts)
    if not tos:
        print("== correction A: no ARM with a timeout in this image (check inactive)")
    for a in sorted(tos):
        ch = chains_into(g, preds, a, I, prem, half_t=half_t)
        offs = [o for kd, o in ch if kd]
        if not offs or any(kd is None for kd, _o in ch):
            print("== correction A: ARM w%d has a timeout but an unanchored chain" % a)
            fails.append(("A", "w%d unanchored" % a))
            continue
        t_lo = min(offs) + g[a][0]["delay"]                 # earliest timeout after our EOP
        t_hi = max(offs) + g[a][0]["delay"]                 # latest
        ok1 = t_lo >= prem["resp_window"]
        worst = None
        stack = [(n, t_hi) for n in g[a][1] if n == a + 1]  # PC+1: the timeout continuation
        seen = set()
        while stack:
            w, acc = stack.pop()
            if (w, acc) in seen:
                continue
            seen.add((w, acc))
            xw = g[w][0]
            if arm_kind(xw, I) == "edge" and w in off:      # TOP's (or a copy's) arm_sop
                nop_gap = min(gaps[n][-1] for n in g[w][1])
                dl = retry_fetch_deadline(0, nop_gap, k, prem)
                t = acc + 4 + xr.get(w, 0)                  # released at acc, on time: + Rr + 2
                worst = (t, dl) if worst is None or t - dl > worst[0] - worst[1] else worst
                continue
            up = upper_gaps(xw, I)
            if up is None:
                continue
            for n in g[w][1]:
                stack.append((n, acc + up))
        ok2 = worst is not None and worst[0] <= worst[1]
        print("== correction A: ARM w%d times out at EOP + %d..%d (window_end %d) %s; TOP arm_sop "
              "retired <= EOP + %s (next-token deadline %s) %s"
              % (a, t_lo, t_hi, prem["resp_window"], "OK" if ok1 else "EARLY",
                 worst[0] if worst else "-", worst[1] if worst else "-", "OK" if ok2 else "LATE"))
        if not ok1:
            fails.append(("A", "w%d early timeout" % a))
        if not ok2:
            fails.append(("A", "w%d retry path" % a))
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
