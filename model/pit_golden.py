"""PIT golden models (v2_tile_pit_design.md §2-§3). The future RTL is checked
against these bit for bit, so every stage uses INTEGER arithmetic as the RTL
would (the bank, the histogram, GF(2)); there are no floats in a stage.

Input to every stage: the capture -- a list of (interval, level) pairs, one per
edge of the sniffed pin: `interval` cycles (saturating at 0xFFFF = OVF) since
the previous edge, `level` the pin's value DURING that interval.
"""
from __future__ import annotations

OVF = 0xFFFF
FRAC = 4                                    # P_hat is 16.4 fixed point

# ---------------------------------------------------------------------------
# stage 1 -- timing (the hypothesis bank)
# ---------------------------------------------------------------------------


def candidates(lo=4, hi=16384):
    """The bank: P(k+1) = P(k) + max(1, P(k) >> 5), shift-add only."""
    out, p = [], lo
    while p <= hi:
        out.append(p)
        p += max(1, p >> 5)
    return out


def _score(ivs, p):
    hits, si, sm, ms = 0, 0, 0, []
    tol = p >> 3
    for i, _lvl in ivs:
        if i >= OVF:
            continue
        m = (i + (p >> 1)) // p
        if m >= 1 and abs(i - m * p) <= tol:
            hits += 1
            si += i
            sm += m
            ms.append(m)
    return hits, si, sm, ms


def _gcd(a, b):
    while b:
        a, b = b, a % b
    return a


def _harmonic(a, b):
    """b is within one grid step (~3 %) of a / k or a * k for an integer k."""
    lo, hi = (a, b) if a <= b else (b, a)
    k = (hi + lo // 2) // lo
    return k >= 1 and abs(hi - k * lo) * 8 <= hi        # within P/8: same hypothesis


def stage1(ivs, min_iv=16):
    """-> {status, p16 (P_hat x 16), phase, score, n, gcd}. status: OK,
    FACTOR_UNRESOLVED or UNKNOWN (with a reason)."""
    data = [(i, l) for i, l in ivs if i < OVF]
    n = len(data)
    if n < min_iv:
        return {"status": "UNKNOWN", "why": "%d intervals < %d" % (n, min_iv), "n": n}
    # ⛔ QUALIFICATION ON THE NON-IDLE LEVEL (run 4's lesson, 10-28): an async
    # line's inter-frame gap is an idle-level interval of ARBITRARY length, off
    # every grid. So a candidate qualifies on >= 7/8 of the NON-idle-level
    # intervals (all intra-frame) and >= 1/2 of the idle-level ones. The idle
    # level = the level of the longest interval; a clock or Manchester line is
    # on-grid at both levels, so it qualifies either way.
    idle_lvl = max(data, key=lambda x: x[0])[1]
    act = [x for x in data if x[1] != idle_lvl]
    idl = [x for x in data if x[1] == idle_lvl]
    qual = []
    for p in candidates():
        ha = _score(act, p)[0]
        hi_ = _score(idl, p)[0]
        if ha >= len(act) - (len(act) >> 3) and 2 * hi_ >= len(idl):
            h, si, sm, ms = _score(data, p)
            qual.append((p, h, si, sm, ms))
    if not qual:
        return {"status": "UNKNOWN", "why": "no candidate reaches 7/8", "n": n}
    best = max(qual, key=lambda q: q[0])     # the LARGEST qualifying period
    p, h, si, sm, ms = best
    for q in qual:                           # a non-harmonic rival = ambiguous
        if not _harmonic(p, q[0]) and q[1] + (n >> 4) >= h:
            return {"status": "UNKNOWN", "why": "non-harmonic rival P=%d" % q[0], "n": n}
    p16 = (si * 16 + sm // 2) // sm
    # ⭐ M2 (Wilson 10-28 Q6): a SECOND refine at P_hat over the FULL hit set --
    # the grid winner sits above the truth and its own hits bias the first
    # refine upward (measured +1.5 % on a jittered clock)
    si2 = sm2 = 0
    for i, _l in data:
        m = (i * 16 + p16 // 2) // p16
        if m >= 1 and abs(i * 16 - m * p16) * 8 <= p16:
            si2 += i
            sm2 += m
    if sm2:
        p16 = (si2 * 16 + sm2 // 2) // sm2
    t0 = data[0][0]
    phase = (t0 * 16) % p16 // 16
    # ⛔ M3: no FACTOR_UNRESOLVED -- under the largest-P rule it cannot fire.
    # P_hat IS "the largest period consistent with the edges; the true period
    # may be P_hat / k" (stated in the results schema, not flagged)
    return {"status": "OK", "p16": p16, "phase": phase, "score": h, "n": n,
            "grid_p": p}


# ---------------------------------------------------------------------------
# stage 2 -- encoding class (run-length statistics)
# ---------------------------------------------------------------------------
IDLE_M = 15


def runs(ivs, p16):
    """[(m, level)] with m = round(I / P_hat), m > IDLE_M (or OVF) = idle."""
    out = []
    for i, l in ivs:
        if i >= OVF:
            out.append((IDLE_M + 1, l))
        else:
            out.append(((i * 16 + p16 // 2) // p16, l))
    return out


def async_frame_len(r, idle_lvl, lo=7, hi=12, min_frames=4):
    """Stop-bit consistency: expand the runs to a bit sequence (idles = 16 idle
    bits), parse greedily from each start bit, and return the SMALLEST frame
    length L whose bit L-1 (the stop) is at the idle level on every frame."""
    bits = []
    for m, l in r:
        bits += [l] * (m if m <= IDLE_M else IDLE_M + 1)
    for L in range(lo, hi + 1):
        i, n, ok = 0, 0, True
        while i < len(bits):
            if bits[i] == idle_lvl:
                i += 1
                continue
            if i + L > len(bits):
                break
            if bits[i + L - 1] != idle_lvl:
                ok = False
                break
            n += 1
            i += L
        if ok and n >= min_frames:
            return L
    return None


def stage2(ivs, s1, other_edges=(), guard=True):
    """`other_edges`: edge counts of the OTHER uio wires in the same window.
    ⛔ R2 (Wilson 10-28), until stage 0 exists: NRZ_ASYNC / MANCHESTER from ONE
    wire is a confident claim that no clock exists; if another wire is at least
    as active it could be that clock, so the answer is UNKNOWN (sync-possible).
    `guard=False` is the must-fire's mutant."""
    r2 = _stage2(ivs, s1)
    # ⭐ (b) (Wilson 10-28): a data class inferred from ONE wire assumes no clock
    # hides outside the sniffed pins -- a CONDITIONED claim, its condition a bit
    # in the results region and a line in the emitted RPL spec
    if r2["cls"] in ("NRZ_ASYNC", "MANCHESTER", "NRZI_STUFFED"):
        r2["condition"] = "every wire of the bus is on the sniffed pins"
    if guard and r2["cls"] in ("NRZ_ASYNC", "MANCHESTER") and             any(n >= len(ivs) for n in other_edges):
        return {"cls": "UNKNOWN", "why": "sync-possible: another wire is as active "
                "(a clock?) -- %s withheld until stage 0" % r2["cls"], "withheld": r2["cls"]}
    return r2


def _stage2(ivs, s1):
    if s1["status"] == "UNKNOWN":
        return {"cls": "UNKNOWN", "why": "stage 1 UNKNOWN"}
    r = runs(ivs, s1["p16"])
    body = [(m, l) for m, l in r if m <= IDLE_M]
    idle = [(m, l) for m, l in r if m > IDLE_M]
    ms = [m for m, _ in body]
    if not ms:
        return {"cls": "UNKNOWN", "why": "no non-idle runs"}
    if not idle and set(ms) == {1} and {l for _, l in body} == {0, 1}:
        return {"cls": "CLOCK", "half_period16": s1["p16"]}
    if set(ms) == {1, 2} and len(ms) >= 16:
        return {"cls": "MANCHESTER", "bit16": 2 * s1["p16"]}
    if idle and len({l for _, l in idle}) == 1 and len(idle) >= 2:
        L = async_frame_len(r, idle[0][1])
        if L:
            return {"cls": "NRZ_ASYNC", "bit16": s1["p16"], "idle": idle[0][1],
                    "frame_bits": L, "frames": None}
        # frames: the runs between idles; span = start bit .. last edge
        spans, cur = [], 0
        for m, l in r:
            if m > IDLE_M:
                if cur:
                    spans.append(cur)
                cur = 0
            else:
                cur += m
        if cur:
            spans.append(cur)
        if len(spans) >= 2:
            return {"cls": "NRZ_ASYNC", "bit16": s1["p16"], "idle": idle[0][1],
                    "frame_bits": max(spans) + 1, "frames": len(spans)}
    if not idle and max(ms) <= 7 and 7 in ms and len(ms) >= 64:
        return {"cls": "NRZI_STUFFED", "bit16": s1["p16"]}
    # ⛔ CLOCK-SHAPED BUT IRREGULAR (chunk 3, corpus_all5 SCL): runs mostly
    # one period at BOTH levels look like a stretched clock, not data -- a data
    # code is not claimed; the answer is UNKNOWN (possible clock)
    for lvl in (0, 1):
        lv = [m for m, l in body if l == lvl]
        if not lv or sum(1 for m in lv if m <= 1) * 4 < 3 * len(lv):
            break
    else:
        return {"cls": "UNKNOWN", "why": "clock-shaped but irregular: a stretched clock?"}
    return {"cls": "LEVEL_CODE", "bit16": s1["p16"],
            "why": "NRZ / NRZI not separable from timing alone"}


# ---------------------------------------------------------------------------
# stage 3 -- frames, then the polynomial (GF(2)[x], ints as bit vectors)
# ---------------------------------------------------------------------------


def deg(a):
    return a.bit_length() - 1


def pmod(a, b):
    db = deg(b)
    while a and deg(a) >= db:
        a ^= b << (deg(a) - db)
    return a


def pgcd(a, b):
    while b:
        a, b = b, pmod(a, b)
    return a


def bits_to_poly(bits):
    """first bit = highest degree."""
    v = 0
    for b in bits:
        v = (v << 1) | b
    return v


def async_bytes(ivs, p16, frame_bits, msg_gap_bits=20):
    """NRZ_ASYNC decode: walk the waveform, sample 8 data bits at mid-bit after
    each start edge (LSB first), split messages at long idles.
    -> [[byte, ...], ...]"""
    t, edges = 0, []
    for i, l in ivs:
        edges.append((t, l))
        t += i
    total = t

    def level_at(x):
        lv = edges[0][1]
        for et, l in edges:
            if et > x:
                break
            lv = l
        return lv

    msgs, cur, k, last_end = [], [], 0, None
    idle_lvl = None
    # idle level = the level of the longest interval
    idle_lvl = max(ivs, key=lambda x: x[0])[1]
    x = 0
    while x < total:
        # find next start edge: idle -> not idle
        while x < total and level_at(x) == idle_lvl:
            x += 1 if p16 < 64 else p16 // 64
        if x >= total:
            break
        # back up to the edge
        s = x
        while s > 0 and level_at(s - 1) != idle_lvl:
            s -= 1
        if last_end is not None and (s - last_end) * 16 > msg_gap_bits * p16 and cur:
            msgs.append(cur)
            cur = []
        byte = 0
        for b in range(8):
            mid = s + ((2 * (b + 1) + 1) * p16) // 32
            byte |= level_at(mid) << b          # UART: the line level IS the bit
        cur.append(byte)
        last_end = s + (frame_bits * p16) // 16
        x = last_end
    if cur:
        msgs.append(cur)
    return msgs


def msg_bits(msg, lsb_first):
    out = []
    for byte in msg:
        rng = range(8) if lsb_first else range(7, -1, -1)
        out += [(byte >> i) & 1 for i in rng]
    return out


WIDTHS = (8, 16, 32)
MIN_DIFFS = 3        # same-length differences before a polynomial is claimed
#: the canonical-member catalogue (R3): name -> (width, poly, init, xorout,
#: reflected), init/xorout in the model's own (transmission-order) domain
CATALOGUE = {
    "CRC-8":              (8, 0x07, 0x00, 0x00, False),
    "CRC-8/MAXIM":        (8, 0x31, 0x00, 0x00, True),
    "CRC-16/CCITT-FALSE": (16, 0x1021, 0xFFFF, 0x0000, False),
    "CRC-16/XMODEM":      (16, 0x1021, 0x0000, 0x0000, False),
    "CRC-16/ARC":         (16, 0x8005, 0x0000, 0x0000, True),
    "CRC-16/MODBUS":      (16, 0x8005, 0xFFFF, 0x0000, True),
    "CRC-32":             (32, 0x04C11DB7, 0xFFFFFFFF, 0xFFFFFFFF, True),
}


def crc_poly_gcd(msgs):
    """GCD of same-length message differences, both bit orders.
    -> {status, width, poly, reflected, diffs_used} or UNKNOWN."""
    by_len = {}
    for m in msgs:
        by_len.setdefault(len(m), []).append(m)
    best = None
    for lsb in (False, True):
        for L, group in sorted(by_len.items(), key=lambda kv: -len(kv[1])):
            if len(group) < 2:
                continue
            polys = [bits_to_poly(msg_bits(m, lsb)) for m in group]
            # ⛔ EVERY same-length difference, and >= MIN_DIFFS of them: stopping at
            # the first gcd of a supported width let two random tails' chance
            # common factor through as a polynomial (T9, CRC-32 tails -> 0x3a).
            # Each further difference a wrong g survives with p ~ 2^-w.
            g, used = 0, 0
            for a in polys[1:]:
                d = a ^ polys[0]
                if d == 0:
                    continue
                g = pgcd(g, d) if g else d
                used += 1
            if g and deg(g) in WIDTHS and used >= MIN_DIFFS:
                cand = {"status": "OK", "width": deg(g), "poly": g & ((1 << deg(g)) - 1),
                        "full": g, "reflected": lsb, "diffs_used": used, "frame_len": L}
                if best is None or cand["diffs_used"] > best["diffs_used"]:
                    best = cand
    if best is None:
        return {"status": "UNKNOWN", "why": "no difference GCD of a supported width"}
    return best


def _crc_reg(bits, g, w, init):
    """the register after shifting `bits` (MSB-first polynomial division form)."""
    r = init
    top = 1 << (w - 1)
    mask = (1 << w) - 1
    for b in bits:
        fb = ((r & top) >> (w - 1)) ^ b
        r = ((r << 1) & mask) ^ (g & mask if fb else 0)
    return r


def crc_init_xorout(msgs, res):
    """With g known: init and xorout from frames of TWO lengths (linear algebra
    over GF(2)); UNKNOWN unless both lengths are present."""
    w, g, lsb = res["width"], res["full"], res["reflected"]
    nb = w // 8
    lens = sorted({len(m) for m in msgs if len(m) > nb})
    if len(lens) < 2:
        return {"init": None, "xorout": None, "why": "one frame length only"}

    def split(m):
        bits = msg_bits(m, lsb)
        return bits[:-w], bits[-w:]

    def obs(m):
        d, c = split(m)
        return bits_to_poly(c), d
    m1 = next(m for m in msgs if len(m) == lens[0])
    m2 = next(m for m in msgs if len(m) == lens[1])
    c1, d1 = obs(m1)
    c2, d2 = obs(m2)
    # c = reg(d, init) ^ xorout, reg linear in init: reg(d, init) = reg(d, 0) ^ A_d(init)
    y = c1 ^ c2 ^ _crc_reg(d1, g, w, 0) ^ _crc_reg(d2, g, w, 0)

    def A(d, v):
        return _crc_reg([0] * len(d), g, w, v)        # the init's own evolution
    cols = [A(d1, 1 << j) ^ A(d2, 1 << j) for j in range(w)]
    # solve sum x_j cols_j = y
    rows = []                                 # gaussian elimination, columns as ints
    piv = {}
    basis = []
    for j, c in enumerate(cols):
        v, tag = c, 1 << j
        for bit in sorted(piv, reverse=True):
            if v >> bit & 1:
                pv, pt = piv[bit]
                v ^= pv
                tag ^= pt
        if v:
            piv[deg(v)] = (v, tag)
    v, tag = y, 0
    for bit in sorted(piv, reverse=True):
        if v >> bit & 1:
            pv, pt = piv[bit]
            v ^= pv
            tag ^= pt
    if v:
        return {"init": None, "xorout": None, "why": "no init solves the two lengths"}
    # ⭐ M4 / R3 (Wilson 10-28): the KERNEL -- inits the two lengths cannot tell
    # apart. For g with an (x + 1) factor it is non-empty, and (init ^ k,
    # xorout ^ A(k)) gives the SAME CRC for every length: one class, reported
    # as a canonical member + the kernel, never as "the" values.
    kernel = []
    for j, c in enumerate(cols):
        vv, tg = c, 1 << j
        for bit in sorted(piv, reverse=True):
            if vv >> bit & 1:
                pv, pt = piv[bit]
                vv ^= pv
                tg ^= pt
        if vv == 0 and tg:
            kernel.append(tg)
    span = {0}
    for k in kernel:
        span |= {x ^ k for x in span}
    members = sorted({(tag ^ k, c1 ^ _crc_reg(d1, g, w, tag ^ k)) for k in span})
    name = None
    for nm, (cw, cp, ci, cx, crefl) in CATALOGUE.items():
        if cw == w and cp == (g & ((1 << w) - 1)) and crefl == lsb:
            for mi, mx in members:
                if (mi, mx) == (ci, cx):
                    name, member = nm, (mi, mx)
    if name is None:
        member = members[0]                    # the smallest init
    return {"init": member[0], "xorout": member[1], "class_size": len(members),
            "kernel": kernel, "catalogue": name}


def gf2_rank(rows, n):
    piv = {}
    for r in rows:
        v = r
        for bit in sorted(piv, reverse=True):
            if v >> bit & 1:
                v ^= piv[bit]
        if v:
            piv[deg(v)] = v
    return len(piv)


def blind_frames(bits, n_max=56, extra_rows=8):
    """The blind-recognition fallback: the smallest n (and offset t) whose
    n-wide matrix of consecutive chunks is rank-deficient. -> (n, t) or None."""
    for n in range(8, n_max + 1):
        rows_n = n + extra_rows
        best_n = None
        for t in range(n):
            chunks = []
            for r in range(rows_n):
                s = t + r * n
                if s + n > len(bits):
                    break
                chunks.append(bits_to_poly(bits[s:s + n]))
            if len(chunks) < rows_n:
                break
            # affine-safe: differences of consecutive rows
            diffs = [chunks[i] ^ chunks[i + 1] for i in range(len(chunks) - 1)]
            rk = gf2_rank(diffs, n)
            if rk < n - 2 and (best_n is None or rk < best_n[0]):
                best_n = (rk, t, chunks)
        if best_n is not None:
            return n, best_n[1], best_n[2]
    return None


def stage3_blind(bits):
    f = blind_frames(bits)
    if f is None:
        return {"status": "UNKNOWN", "why": "no rank-deficient (n, t) within n <= 56"}
    n, t, chunks = f
    g = 0
    for i in range(len(chunks) - 1):
        d = chunks[i] ^ chunks[i + 1]
        if d:
            g = pgcd(g, d) if g else d
    if not g or deg(g) not in WIDTHS:
        return {"status": "UNKNOWN", "why": "frames found (n=%d) but gcd degree %d" % (n, deg(g) if g else -1),
                "n": n, "t": t}
    return {"status": "OK", "n": n, "t": t, "width": deg(g), "poly": g & ((1 << deg(g)) - 1)}


# ---------------------------------------------------------------------------
# stage 0 -- multi-wire roles (Wilson 10-28 Q1): find a CLOCK before classifying
# ---------------------------------------------------------------------------
# The capture: [(t, mask, levels)] -- the cycle of each change on ANY uio wire,
# the wires that changed (bit w), and all 8 levels just after it.
S0_MIN_CLOCK_EDGES = 16
#: ⛔ RATE FLOOR (Wilson 10-28): a wire whose median interval is under this many
#: samples and that gets no role may be a clock too fast to resolve -> stage 0
#: refuses the WHOLE bus (clock_like cannot see a half-period < 8 through the
#: synchroniser's 0 / +1). 0 = off (the must-fire's mutant).
S0_RATE_FLOOR = 8
#: the I2C branch's 1 + 9n SCL-fall rule; False = off (the must-fire's mutant)
I2C_MOD9 = True
#: the all-zero-I2C / CPOL-1 SPI-CS ambiguity rule; False = off (the must-fire's mutant)
S0_AMBIG = True


def wire_edges(cap, w):
    return [t for t, mask, _lv in cap if mask >> w & 1]


def wire_ivs(cap, w, lv0):
    """a wire's own single-wire capture [(interval, level during it)]."""
    ts = wire_edges(cap, w)
    out, lvl = [], None
    prev = None
    for t, mask, lv in cap:
        if mask >> w & 1:
            if prev is not None:
                out.append((min(t - prev, OVF), lvl))
            prev, lvl = t, lv >> w & 1
    return out


def bracket(cap, c, d):
    """(fraction of d's edges inside c's phases of its best level, that level,
    d edges, c edges). An edge at the same cycle as a c edge counts in the
    level c takes AT that cycle (data that changes on the clock edge)."""
    in_lvl = [0, 0]
    nd = nc = 0
    for t, mask, lv in cap:
        if mask >> c & 1:
            nc += 1
        if mask >> d & 1:
            nd += 1
            in_lvl[lv >> c & 1] += 1
    if nd == 0:
        return 0, None, 0, nc
    best = 0 if in_lvl[0] >= in_lvl[1] else 1
    return in_lvl[best] * 8, best, nd, nc          # x8 so the 7/8 test is integer


def clock_like(cap, c):
    """A CLOCK is REGULAR: at each level, >= 3/4 of its intervals lie within
    +-1/8 of that level's median (stretching / parking allowed as the rest).
    ⛔ Added after the corpus run: a data sender passed the bracket test as the
    'clock' of a receiver whose outputs are timed to its bits (cmp images)."""
    ts, out = [], {0: [], 1: []}
    prev = None
    for t, mask, lv in cap:
        if mask >> c & 1:
            if prev is not None:
                out[prev[1]].append(t - prev[0])
            prev = (t, lv >> c & 1)
    for lvl, iv in out.items():
        if len(iv) < 4:
            return False
        med = sorted(iv)[len(iv) // 2]
        near = sum(1 for i in iv if abs(i - med) * 8 <= med)
        if near * 4 < 3 * len(iv):
            return False
    return True


def in_idle_gaps(cap, c, d):
    """d frames c's bursts: none of its edges falls inside a burst."""
    import bisect
    ce = wire_edges(cap, c)
    if len(ce) < 2:
        return False
    half = sorted(b - a for a, b in zip(ce, ce[1:]))[len(ce) // 2]
    # FRAME: no edge of d lies INSIDE a clock burst -- between two clock edges
    # at most 2 half-periods apart. A data line changes inside bursts; a chip
    # select changes only at a burst's ends (its far-side clock neighbour is
    # the inter-burst gap), however short its setup time.
    for x in wire_edges(cap, d):
        k = bisect.bisect_left(ce, x)
        if 0 < k < len(ce) and ce[k] - ce[k - 1] <= 2 * half:
            return False
    return True


def i2c_signature(cap, c, d):
    """I2C's own signature (Nate/Wilson 10-28): SDA (d) changes while SCL (c) is
    HIGH only at START (falling) and STOP (rising); they bracket the bursts
    (>= 9 SCL pulses -- a byte + ACK -- between consecutive events, repeated
    START allowed); both wires idle high. An IRREGULAR (stretched) clock is
    accepted ONLY with this signature -- the regularity test is not loosened."""
    ev = []                                  # (index, kind) of d edges with c high
    pulses = 0
    gaps = []
    for t, mask, lv in cap:
        if mask >> c & 1 and not (lv >> c & 1):
            pulses += 1                      # an SCL falling edge
        if mask >> d & 1 and (lv >> c & 1):
            kind = "START" if not (lv >> d & 1) else "STOP"
            ev.append(kind)
            gaps.append(pulses)
            pulses = 0
    if len(ev) < 2:
        return False
    # >= 9 SCL pulses after every START (a byte + ACK) before the next event;
    # STOP -> START has none (the bus idles) -- measured on corpus_i2c
    # ⛔ I2C's OWN STRUCTURE (Wilson 10-28, after the near-coincident held-out
    # run: a fast SPI's MOSI / CS read as SCL / SDA): between a START and the
    # next STOP or repeated START the SCL falls are 1 + 9n -- the fall after
    # START, then one after each of the 9n pulses (8 data bits + ACK per byte).
    # Structural, rate-free, and keeps an all-zero transfer.
    for k in range(1, len(ev)):
        if ev[k - 1] == "START" and gaps[k] < 9:
            return False
        if I2C_MOD9 and ev[k - 1] == "START" and (gaps[k] < 10 or (gaps[k] - 1) % 9):
            return False
        if ev[k - 1] == "STOP" and ev[k] == "STOP":
            return False                     # two STOPs with no START between
    # (idle high is implied: a STOP is SDA rising with SCL high)
    return ev.count("START") >= 2


def stage0(cap, guard=True):
    """-> {wire: role}: CLOCK (of data wires), SYNC_DATA (clock, change level),
    FRAME (edges only in the clock's idle gaps), or absent = no role found.
    `guard=False` is the must-fire's mutant (stage 0 off)."""
    roles = {}
    if not guard:
        return roles
    act = [w for w in range(8) if len(wire_edges(cap, w)) >= 2]
    for c in act:
        if len(wire_edges(cap, c)) < S0_MIN_CLOCK_EDGES:
            continue
        regular = clock_like(cap, c)
        for d in act:
            if d == c:
                continue
            f8, lvl, nd, nc = bracket(cap, c, d)
            # a wire already holding a different role is not re-assigned
            if (c in roles and roles[c]["role"] != "CLOCK") or d in roles:
                continue
            if regular and nd >= 4 and f8 >= 7 * nd and 16 * nd <= 9 * nc:
                # >= 7/8 of d's edges in ONE level of c, and d changes at most
                # about once per clock cycle (nd <= nc/2 + 1/8 slack)
                roles.setdefault(c, {"role": "CLOCK", "of": []})["of"].append(d)
                # ⛔ FRAME BEFORE DATA (corpus_sptgt wire 6 = CS came out
                # SYNC_DATA): none of d's edges inside a clock burst
                if in_idle_gaps(cap, c, d):
                    roles[d] = {"role": "FRAME", "clock": c}
                else:
                    roles[d] = {"role": "SYNC_DATA", "clock": c, "change_level": lvl,
                                "sample_edge": "rising" if lvl == 0 else "falling"}
            elif i2c_signature(cap, c, d):
                # I2C (Nate/Wilson 10-28): START/STOP -- SDA moving with SCL high
                # -- are not data edges; the 7/8 applies to the REST, which must
                # sit in SCL low. Short transactions make START/STOP a large
                # share (31 % on corpus_i2c), past the plain test's 1/8 slack.
                n_ev = sum(1 for t, mask, lv in cap if mask >> d & 1 and lv >> c & 1)
                nd2 = nd - n_ev
                in_low = nd2                       # every non-event edge is in SCL low by definition
                if nd2 >= 4 and 16 * nd2 <= 9 * nc:
                    roles.setdefault(c, {"role": "CLOCK", "of": []})["of"].append(d)
                    roles[c]["bus"] = "I2C"
                    roles[d] = {"role": "SYNC_DATA", "clock": c, "change_level": 0,
                                "sample_edge": "rising", "bus": "I2C"}
    # FRAME: a wire with no role whose every edge falls in a clock's idle gap
    # (no clock edge within 4 clock half-periods either side)
    clocks = [w for w, r in roles.items() if r["role"] == "CLOCK"]
    for c in clocks:
        ce = wire_edges(cap, c)
        if len(ce) < 2:
            continue
        half = sorted(b - a for a, b in zip(ce, ce[1:]))[len(ce) // 2]
        for e in act:
            if e in roles:
                continue
            ee = wire_edges(cap, e)
            import bisect
            ok = all(not any(abs(x - y) <= 4 * half
                             for y in ce[max(0, bisect.bisect_left(ce, x) - 1):bisect.bisect_left(ce, x) + 1])
                     for x in ee)
            if ee and ok:
                roles[e] = {"role": "FRAME", "clock": c}
    # ⛔ THE AMBIGUITY RULE (Wilson 10-28): a FRAME whose every edge falls with
    # its clock HIGH and that also satisfies I2C's structure (START / STOP, 1 + 9n
    # SCL falls) is all-zero I2C OR CPOL-1 SPI with CS and no data wire on the
    # pins -- the same waveform. Unless a SYNC_DATA of that clock breaks the tie
    # (a data wire on the pins = SPI), both hypotheses, never either one alone.
    if S0_AMBIG:
        for d, r in list(roles.items()):
            if r["role"] != "FRAME":
                continue
            c = r["clock"]
            if any(x["role"] == "SYNC_DATA" and x.get("clock") == c for x in roles.values()):
                continue
            all_high = all(lv >> c & 1 for t, mask, lv in cap if mask >> d & 1)
            if all_high and i2c_signature(cap, c, d):
                hyp = ["I2C", "SPI-CS"]
                roles[c] = {"role": "AMBIGUOUS", "hyp": hyp, "as": {"I2C": "SCL", "SPI-CS": "SCK"}, "with": d}
                roles[d] = {"role": "AMBIGUOUS", "hyp": hyp, "as": {"I2C": "SDA", "SPI-CS": "CS"}, "clock": c}
    # ⛔ RATE FLOOR (Wilson 10-28): a role-less wire faster than the floor could
    # be the bus's real clock, unresolved -- no role on this bus is trusted
    for w in act:
        ee = wire_edges(cap, w)
        if w not in roles and S0_RATE_FLOOR and \
                sorted(b - a for a, b in zip(ee, ee[1:]))[(len(ee) - 1) // 2] < S0_RATE_FLOOR:
            return {"refused": "wire %d: a clock too fast to resolve may be present" % w}
    return roles


def classify_bus(cap, lv0=0, guard=True):
    """stage 0 then stage 1-2 per wire. -> {wire: result}. A wire with a role
    gets it as an UNCONDITIONED claim (its clock is visible); the rest go
    through the single-wire stages and keep the (b) condition."""
    roles = stage0(cap, guard)
    act = [w for w in range(8) if len(wire_edges(cap, w)) >= 2]
    if "refused" in roles:
        return {w: {"cls": "UNKNOWN", "why": "stage 0 refused the bus: " + roles["refused"]} for w in act}
    out = {}
    for w in act:
        if w in roles:
            out[w] = dict(roles[w], cls=roles[w]["role"])
            continue
        iv = wire_ivs(cap, w, lv0)
        others = [len(wire_edges(cap, x)) for x in act if x != w]
        s1 = stage1(iv)
        out[w] = stage2(iv, s1, others)
    return out


# ---------------------------------------------------------------------------
# stage 3 composition (Wilson 11-04) -- APPENDED; everything above is the
# f19f2177 rule set byte for byte (pit_s0_golden checks the prefix hash).
# One record per bus at bytes 120..135, from the FIRST NRZ_ASYNC wire in index
# order (classify_bus). Little-endian:
#   120  wire[2:0] | found<<3 | poly_ok<<4 | io_ok<<5 | reflected<<6 | kernel<<7
#   121  width code[1:0] (0 none, 1 = 8, 2 = 16, 3 = 32) | frame length [7:2] (sat 63)
#   122  differences used (sat 255)
#   123  frames decoded (sat 255)
#   124..127 poly (normal form, implicit top bit; 0 unless poly_ok)
#   128..131 init   (0 unless io_ok)
#   132..135 xorout (0 unless io_ok)
# The catalogue name lives in the emitter, not on chip.
# ---------------------------------------------------------------------------
S3_AT, S3_BYTES = 120, 16
_WCODE = {8: 1, 16: 2, 32: 3}
S3_MIN_FRAME_BITS = 9   # start + 8 data bits


def crc_poly_gcd_s3(msgs):
    """crc_poly_gcd with every factor of x stripped from the GCD before the
    width check (Wilson 11-04, fix 3): a CRC generator has constant term 1, so
    x is never part of one. (x+1) is NEVER stripped (0x8005, 0x1021 carry it)."""
    by_len = {}
    for m in msgs:
        by_len.setdefault(len(m), []).append(m)
    best = None
    for lsb in (False, True):
        for L, group in sorted(by_len.items(), key=lambda kv: -len(kv[1])):
            if len(group) < 2:
                continue
            polys = [bits_to_poly(msg_bits(m, lsb)) for m in group]
            g, used = 0, 0
            for a in polys[1:]:
                d = a ^ polys[0]
                if d == 0:
                    continue
                g = pgcd(g, d) if g else d
                used += 1
            while g and not g & 1:
                g >>= 1
            if g and deg(g) in WIDTHS and used >= MIN_DIFFS:
                cand = {"status": "OK", "width": deg(g), "poly": g & ((1 << deg(g)) - 1),
                        "full": g, "reflected": lsb, "diffs_used": used, "frame_len": L}
                if best is None or cand["diffs_used"] > best["diffs_used"]:
                    best = cand
    if best is None:
        return {"status": "UNKNOWN", "why": "no difference GCD of a supported width"}
    return best


S3_DEC_AT, S3_STORE = 128, 512     # the decoded messages, [len][bytes...] from 128


def crc_poly_gcd_s3_fit(msgs):
    """crc_poly_gcd_s3 under the store's CAPACITY RULE (Wilson 11-05): the chip
    runs the GCD in two L-byte buffers in the store after the decoded messages,
    so a length group is tried only if 2 L <= 512 - (the end of the decoded
    messages); otherwise it is skipped like a group with too few frames. If no
    group with >= 2 frames fits, the reason is "insufficient store for the GCD"."""
    free = S3_STORE - (S3_DEC_AT + sum(len(m) + 1 for m in msgs))
    by_len = {}
    for m in msgs:
        by_len.setdefault(len(m), []).append(m)
    best, tried, skipped = None, False, False
    for lsb in (False, True):
        for L, group in sorted(by_len.items(), key=lambda kv: -len(kv[1])):
            if len(group) < 2:
                continue
            if 2 * L > free:
                skipped = True
                continue
            tried = True
            polys = [bits_to_poly(msg_bits(m, lsb)) for m in group]
            g, used = 0, 0
            for a in polys[1:]:
                d = a ^ polys[0]
                if d == 0:
                    continue
                g = pgcd(g, d) if g else d
                used += 1
            while g and not g & 1:
                g >>= 1
            if g and deg(g) in WIDTHS and used >= MIN_DIFFS:
                cand = {"status": "OK", "width": deg(g), "poly": g & ((1 << deg(g)) - 1),
                        "full": g, "reflected": lsb, "diffs_used": used, "frame_len": L}
                if best is None or cand["diffs_used"] > best["diffs_used"]:
                    best = cand
    if best is None:
        return {"status": "UNKNOWN", "why": "insufficient store for the GCD" if skipped and not tried
                else "no difference GCD of a supported width"}
    return best


def io_evidence(msgs, res):
    """the frames init/xorout may be solved from (Wilson 11-04, fixes 1-2):
    ⛔ the last decoded frame is never evidence, whatever the stop (budget,
    FULL or OVERRUN can each cut it);
    ⛔ a length counts only with >= 2 frames whose differences are all
    multiples of g -- one frame per length is one equation that always has an
    answer, so a corrupted frame became a confident wrong init/xorout."""
    g, lsb = res["full"], res["reflected"]
    by_len = {}
    for m in msgs[:-1]:
        by_len.setdefault(len(m), []).append(m)
    keep = []
    for L in sorted(by_len):
        group = by_len[L]
        if len(group) < 2:
            continue
        p0 = bits_to_poly(msg_bits(group[0], lsb))
        if all(pmod(bits_to_poly(msg_bits(m, lsb)) ^ p0, g) == 0 for m in group[1:]):
            keep += group
    return keep


def canonical_member(msgs, res, io):
    """the SMALLEST-INIT member of the (init, xorout) class (Wilson 11-05,
    option 1). A kernel class cannot be told apart by the data; the frozen
    solver's catalogue pick is a prior, so the chip reports the canonical
    member + the kernel flag and the EMITTER names any catalogue match.
    xorout follows from the same frame the frozen solver anchors on (the first
    of the shorter length): c1 = reg(d1, init) ^ xorout."""
    if io.get("init") is None:
        return io
    w, g, lsb = res["width"], res["full"], res["reflected"]
    nb = w // 8
    span = {0}
    for k in io["kernel"]:
        span |= {x ^ k for x in span}
    init = min(io["init"] ^ k for k in span)
    lens = sorted({len(m) for m in msgs if len(m) > nb})
    bits = msg_bits(next(m for m in msgs if len(m) == lens[0]), lsb)
    xorout = bits_to_poly(bits[-w:]) ^ _crc_reg(bits[:-w], g, w, init)
    return dict(io, init=init, xorout=xorout)


def stage3(cap, lv0, cls):
    """-> (the 16-byte record, detail). cls = classify_bus(cap, lv0)."""
    rec = bytearray(S3_BYTES)
    w = next((x for x in sorted(cls) if cls[x].get("cls") == "NRZ_ASYNC"), None)
    if w is None:
        return bytes(rec), {"status": "UNKNOWN", "why": "no NRZ_ASYNC wire"}
    c = cls[w]
    rec[0] = w | 1 << 3
    # ⛔ (Wilson 11-05) a frame shorter than start + 8 data bits is not a UART
    # byte: async_bytes would restart its search INSIDE the byte it just read
    # (last_end < the 8th sample), stepping back in time. Refused, not decoded;
    # with frame_bits >= 9 the decode only moves forward (write-behind is safe).
    if c["frame_bits"] < S3_MIN_FRAME_BITS:
        return bytes(rec), {"status": "UNKNOWN", "wire": w,
                            "why": "frame shorter than start + 8 data bits"}
    msgs = async_bytes(wire_ivs(cap, w, lv0), c["bit16"], c["frame_bits"])
    res = crc_poly_gcd_s3_fit(msgs)
    out = {"wire": w, "msgs": msgs, "poly": res}
    if res.get("why") == "insufficient store for the GCD":
        out["why"] = res["why"]
    rec[3] = min(len(msgs), 255)
    if res["status"] != "OK":
        out["status"] = "UNKNOWN"
        return bytes(rec), out
    ev = io_evidence(msgs, res)
    out["evidence"] = ev
    io = canonical_member(ev, res, crc_init_xorout(ev, res))
    out["io"] = io
    rec[0] |= 1 << 4 | (1 << 6 if res["reflected"] else 0)
    rec[1] = _WCODE[res["width"]] | min(res["frame_len"], 63) << 2
    rec[2] = min(res["diffs_used"], 255)
    rec[4:8] = res["poly"].to_bytes(4, "little")
    if io.get("init") is not None:
        rec[0] |= 1 << 5 | (1 << 7 if io["class_size"] > 1 else 0)
        rec[8:12] = io["init"].to_bytes(4, "little")
        rec[12:16] = io["xorout"].to_bytes(4, "little")
    out["status"] = "OK"
    return bytes(rec), out


# ---------------------------------------------------------------------------
# stage 3 on a CLOCKED bus (Wilson 11-06): a SAMPLED SECOND CAPTURE -- APPENDED.
# The edge capture holds 1.5-4 whole I2C / SPI frames (22 records a byte), too
# few for the GCD. When classify_bus gives NO NRZ_ASYNC wire (UART keeps
# priority: its records never change) and stage 0 named a clocked bus, the PIT
# captures the bus AGAIN, storing one bit per sample edge of the data wire as
# the decoded messages themselves, [len][bytes...] from 128, the layout the
# UART decode writes; stage 3's solver then runs unchanged. The record's layout
# does not change: the bus type is in the role table (32..38).
#  * the bus: the first SYNC_DATA wire in index order that has frame markers.
#    SPI: a FRAME wire (the CS) of the same clock, the lowest-indexed. I2C: stage
#    0's I2C tag, or no CS and the pair passes i2c_signature (a REGULAR SCL is
#    typed by stage 0's plain bracket test first and never gets the tag).
#    An AMBIGUOUS or REFUSED bus never qualifies (no SYNC_DATA in it).
#  * THE SAMPLE EDGE, inferred from the FIRST capture: the clock edge data never
#    changes on -- no counted data edge within 1 cycle of it (the synchroniser's
#    0 / +1). Counted: SPI, the data edges with CS active before and after; I2C,
#    the data edges that are not START / STOP. One clean edge -> it. Both clean
#    -> the edge that ENDS the clock level every counted data edge lies in (the
#    level after the record, as stage 0's bracket reads it). Neither clean, or
#    both clean with data in both levels -> REFUSED: no clocked record, a reason.
#  * CS's active level: the CS level at >= 7/8 of the clock's edges; else refused.
#  * the second capture (cycle 0 = its first cycle, levels lv2 before any change):
#    a sample = the data wire's level in the cycle BEFORE the sample edge.
#    SPI: a frame opens on CS going active and closes on CS going inactive (a
#    sample edge in the cycle CS goes active is not in it); bits are sampled
#    while it is open, packed MSB-first as sent; a frame that is not whole bytes
#    is dropped. I2C: START (SDA falls, SCL high before and after) opens a frame,
#    STOP (SDA rises, the same) closes it, a repeated START closes one and opens
#    the next; a bit sampled on SCL's rise counts only when SCL falls again
#    before any START / STOP; of each 9 the 9th (ACK) is dropped; a frame of not
#    9n bits is dropped. A frame with no bytes, or still open when the capture
#    stops, is dropped.
#  * it stops on the budget (2^b cycles from ITS cycle 0, edges at t >= budget
#    unseen -- a quiet bus ends it) or when a byte would pass S3_SAMP_END: the
#    window 128..383 leaves 128 bytes for the GCD's two buffers (frames <= 64).
# ---------------------------------------------------------------------------
S3_SAMP_END = 384


def clocked_bus(cap, lv0, cls):
    """-> the bus the sampled capture reads, or a dict with "why" (no record)."""
    data = [w for w in sorted(cls) if cls[w].get("cls") == "SYNC_DATA"]
    if not data:
        return {"why": "no clocked bus with a data wire"}
    for d in data:
        c = cls[d]["clock"]
        if cls[d].get("bus") == "I2C":
            bus = {"kind": "I2C", "clock": c, "data": d}
            break
        fr = [w for w in sorted(cls) if cls[w].get("cls") == "FRAME" and cls[w].get("clock") == c]
        if fr:
            bus = {"kind": "SPI", "clock": c, "data": d, "cs": fr[0]}
            break
        if i2c_signature(cap, c, d):          # a regular SCL passes stage 0's plain test first
            bus = {"kind": "I2C", "clock": c, "data": d}
            break
    else:
        return {"why": "no clocked bus with frame markers"}
    c, d = bus["clock"], bus["data"]
    if bus["kind"] == "SPI":
        f = bus["cs"]
        at = [lv >> f & 1 for t, mask, lv in cap if mask >> c & 1]
        hi = sum(at)
        if 8 * hi >= 7 * len(at):
            bus["cs_active"] = 1
        elif 8 * (len(at) - hi) >= 7 * len(at):
            bus["cs_active"] = 0
        else:
            return dict(bus, why="CS active level unclear")
    counted, before = [], lv0              # (cycle, clock level after the record)
    for t, mask, lv in cap:
        if mask >> d & 1:
            if bus["kind"] == "I2C":
                if not (before >> c & 1 and lv >> c & 1):
                    counted.append((t, lv >> c & 1))
            elif before >> bus["cs"] & 1 == bus["cs_active"] and lv >> bus["cs"] & 1 == bus["cs_active"]:
                counted.append((t, lv >> c & 1))
        before = lv
    rise = [t for t, mask, lv in cap if mask >> c & 1 and lv >> c & 1]
    fall = [t for t, mask, lv in cap if mask >> c & 1 and not (lv >> c & 1)]

    def clean(edges):
        import bisect
        for t, _l in counted:
            k = bisect.bisect_left(edges, t - 1)
            if k < len(edges) and edges[k] <= t + 1:
                return False
        return True
    cr, cf = clean(rise), clean(fall)
    if cr and not cf:
        bus["edge"] = 1                       # sample on the rise
    elif cf and not cr:
        bus["edge"] = 0                       # sample on the fall
    elif cr and cf:
        lvls = {l for _t, l in counted}
        if len(lvls) != 1:
            return dict(bus, why="no clean sample edge (data changes in both clock levels)")
        bus["edge"] = 1 - lvls.pop()          # the edge that ENDS the data's level
    else:
        return dict(bus, why="no clean sample edge (data changes on both clock edges)")
    return bus


def sampled_capture(log2, lv2, bus, budget=None, ncyc=None):
    """the second capture -> (msgs as stored, why it stopped: "budget", "full"
    or None = still listening at ncyc). log2 = [(cycle >= 1, mask)]."""
    c, d = bus["clock"], bus["data"]
    unit = 9 if bus["kind"] == "I2C" else 8
    st = {"cur": None, "nbit": 0, "byte": 0, "wp": S3_DEC_AT}
    msgs, pend, lv, why = [], None, lv2, None

    def close():
        cur = st["cur"]
        if cur is not None and cur and st["nbit"] == 0:
            msgs.append(cur)
            st["wp"] += len(cur) + 1
        st["cur"] = None

    def open_():
        close()
        st["cur"], st["nbit"], st["byte"] = [], 0, 0

    def bit(b):
        if st["nbit"] < 8:
            st["byte"] = (st["byte"] << 1) | b
        st["nbit"] += 1

    for t, mask in log2:
        assert t >= 1
        if budget is not None and t >= budget:
            why = "budget"
            break
        new = lv ^ mask
        cb, ca = lv >> c & 1, new >> c & 1
        if bus["kind"] == "SPI":
            f, a = bus["cs"], bus["cs_active"]
            if mask >> f & 1 and (new >> f & 1) != a:
                close()                       # CS inactive: the frame ends (ragged -> dropped)
            elif mask >> c & 1 and ca == bus["edge"] and st["cur"] is not None:
                bit(lv >> d & 1)
            if mask >> f & 1 and (new >> f & 1) == a:
                open_()
        else:
            if mask >> d & 1 and cb and ca:   # SDA moves with SCL high: START / STOP
                close()
                pend = None
                if not (new >> d & 1):
                    open_()
            elif mask >> c & 1:
                if ca and st["cur"] is not None:
                    pend = lv >> d & 1        # sampled on the rise
                elif not ca and pend is not None:
                    bit(pend)                 # confirmed by the fall
                    pend = None
        if st["cur"] is not None and st["nbit"] == unit:
            if st["wp"] + 1 + len(st["cur"]) + 1 > S3_SAMP_END:
                st["cur"], why = None, "full"
                break
            st["cur"].append(st["byte"])
            st["nbit"], st["byte"] = 0, 0
        lv = new
    if why is None and budget is not None and (ncyc is None or budget <= ncyc):
        why = "budget"
    return msgs, why


def stage3_clocked(cap, lv0, cls, log2, lv2, budget=None, ncyc=None):
    """-> (the 16-byte record, detail). stage3 when there is an NRZ_ASYNC wire
    (UART keeps priority); else the clocked bus's sampled second capture."""
    if any(cls[x].get("cls") == "NRZ_ASYNC" for x in cls):
        return stage3(cap, lv0, cls)
    rec = bytearray(S3_BYTES)
    bus = clocked_bus(cap, lv0, cls)
    if "why" in bus:
        return bytes(rec), {"status": "UNKNOWN", "bus": bus, "why": bus["why"], "second": False}
    msgs, stop = sampled_capture(log2, lv2, bus, budget, ncyc)
    w = bus["data"]
    rec[0] = w | 1 << 3
    res = crc_poly_gcd_s3_fit(msgs)
    out = {"wire": w, "bus": bus, "msgs": msgs, "poly": res, "stop": stop, "second": True}
    if res.get("why") == "insufficient store for the GCD":
        out["why"] = res["why"]
    rec[3] = min(len(msgs), 255)
    if res["status"] != "OK":
        out["status"] = "UNKNOWN"
        out.setdefault("why", res.get("why"))
        return bytes(rec), out
    ev = io_evidence(msgs, res)
    out["evidence"] = ev
    io = canonical_member(ev, res, crc_init_xorout(ev, res))
    out["io"] = io
    rec[0] |= 1 << 4 | (1 << 6 if res["reflected"] else 0)
    rec[1] = _WCODE[res["width"]] | min(res["frame_len"], 63) << 2
    rec[2] = min(res["diffs_used"], 255)
    rec[4:8] = res["poly"].to_bytes(4, "little")
    if io.get("init") is not None:
        rec[0] |= 1 << 5 | (1 << 7 if io["class_size"] > 1 else 0)
        rec[8:12] = io["init"].to_bytes(4, "little")
        rec[12:16] = io["xorout"].to_bytes(4, "little")
    out["status"] = "OK"
    return bytes(rec), out


# ---------------------------------------------------------------------------
# THE LAST MESSAGE IS NEVER EVIDENCE, AND THE RECORD SAYS WHY (Wilson 11-06) --
# APPENDED; every function above is unchanged.
#  * the polynomial: crc_poly_gcd_s3_fit's groups are built from msgs[:-1]
#    (io_evidence's rule since 11-04). A capture that stops between two bytes
#    of a message leaves a shorter one that looks whole; in a group of that
#    length it spoiled the GCD (the round trip, s3_modbus). The capacity rule
#    still counts every decoded message: they are all in the store.
#  * the REASON CODE, a 4-bit nibble in the low half of byte 128 (the record's
#    byte 8, init's low byte -- zero whenever there is a reason: init is not
#    written). Byte 120 has no free bit. 0 = no reason (init / xorout found).
# ---------------------------------------------------------------------------
WHY3 = {
    "frame shorter than start + 8 data bits": 1,
    "insufficient store for the GCD": 2,
    "no difference GCD of a supported width": 3,
    "one frame length only": 4,
    "no init solves the two lengths": 5,
    "no clocked bus with a data wire": 6,
    "no clocked bus with frame markers": 7,
    "CS active level unclear": 8,
    "no clean sample edge (data changes on both clock edges)": 9,
    "no clean sample edge (data changes in both clock levels)": 10,
}
WHY3_AT = 8                  # the record's byte 8 = store byte 128, bits 3..0


def crc_poly_gcd_s3_last(msgs):
    """crc_poly_gcd_s3_fit with the LAST decoded message out of every group."""
    free = S3_STORE - (S3_DEC_AT + sum(len(m) + 1 for m in msgs))
    by_len = {}
    for m in msgs[:-1]:
        by_len.setdefault(len(m), []).append(m)
    best, tried, skipped = None, False, False
    for lsb in (False, True):
        for L, group in sorted(by_len.items(), key=lambda kv: -len(kv[1])):
            if len(group) < 2:
                continue
            if 2 * L > free:
                skipped = True
                continue
            tried = True
            polys = [bits_to_poly(msg_bits(m, lsb)) for m in group]
            g, used = 0, 0
            for a in polys[1:]:
                d = a ^ polys[0]
                if d == 0:
                    continue
                g = pgcd(g, d) if g else d
                used += 1
            while g and not g & 1:
                g >>= 1
            if g and deg(g) in WIDTHS and used >= MIN_DIFFS:
                cand = {"status": "OK", "width": deg(g), "poly": g & ((1 << deg(g)) - 1),
                        "full": g, "reflected": lsb, "diffs_used": used, "frame_len": L}
                if best is None or cand["diffs_used"] > best["diffs_used"]:
                    best = cand
    if best is None:
        return {"status": "UNKNOWN", "why": "insufficient store for the GCD" if skipped and not tried
                else "no difference GCD of a supported width"}
    return best


def _s3_solve(rec, w, msgs, out):
    """the solver on decoded messages, into the record (stage3 / stage3_clocked's
    tail, with crc_poly_gcd_s3_last); -> the reason text or None"""
    rec[0] = w | 1 << 3
    res = crc_poly_gcd_s3_last(msgs)
    out.update(wire=w, msgs=msgs, poly=res)
    rec[3] = min(len(msgs), 255)
    if res["status"] != "OK":
        out["status"] = "UNKNOWN"
        return res["why"]
    ev = io_evidence(msgs, res)
    out["evidence"] = ev
    io = canonical_member(ev, res, crc_init_xorout(ev, res))
    out["io"] = io
    rec[0] |= 1 << 4 | (1 << 6 if res["reflected"] else 0)
    rec[1] = _WCODE[res["width"]] | min(res["frame_len"], 63) << 2
    rec[2] = min(res["diffs_used"], 255)
    rec[4:8] = res["poly"].to_bytes(4, "little")
    out["status"] = "OK"
    if io.get("init") is None:
        return io["why"]
    rec[0] |= 1 << 5 | (1 << 7 if io["class_size"] > 1 else 0)
    rec[8:12] = io["init"].to_bytes(4, "little")
    rec[12:16] = io["xorout"].to_bytes(4, "little")
    return None


def _s3_why(rec, out, why):
    if why is not None:
        out["why"] = why
        rec[WHY3_AT] |= WHY3[why]
    return bytes(rec), out


def stage3_rc(cap, lv0, cls):
    """stage3 with the last message out of the GCD and the reason code."""
    rec = bytearray(S3_BYTES)
    w = next((x for x in sorted(cls) if cls[x].get("cls") == "NRZ_ASYNC"), None)
    if w is None:
        return bytes(rec), {"status": "UNKNOWN", "why": "no NRZ_ASYNC wire"}
    c = cls[w]
    if c["frame_bits"] < S3_MIN_FRAME_BITS:
        rec[0] = w | 1 << 3
        return _s3_why(rec, {"status": "UNKNOWN", "wire": w}, "frame shorter than start + 8 data bits")
    msgs = async_bytes(wire_ivs(cap, w, lv0), c["bit16"], c["frame_bits"])
    out = {}
    return _s3_why(rec, out, _s3_solve(rec, w, msgs, out))


def stage3_clocked_rc(cap, lv0, cls, log2, lv2, budget=None, ncyc=None):
    """stage3_clocked with the last message out of the GCD and the reason code."""
    if any(cls[x].get("cls") == "NRZ_ASYNC" for x in cls):
        return stage3_rc(cap, lv0, cls)
    rec = bytearray(S3_BYTES)
    bus = clocked_bus(cap, lv0, cls)
    if "why" in bus:
        return _s3_why(rec, {"status": "UNKNOWN", "bus": bus, "second": False}, bus["why"])
    msgs, stop = sampled_capture(log2, lv2, bus, budget, ncyc)
    out = {"bus": bus, "stop": stop, "second": True}
    return _s3_why(rec, out, _s3_solve(rec, bus["data"], msgs, out))


# ---------------------------------------------------------------------------
# THE CLOCKED-BUS DESCRIPTOR, results byte 3 (Wilson 11-06) -- APPENDED.
# Written when stage 3's clocked path chose a bus and armed its second capture
# (no NRZ_ASYNC wire; clocked_bus gave no "why"); 0 otherwise.
#   bit 7  valid
#   bit 6  CPOL known: the clock level BEFORE each record where CS goes ACTIVE,
#          agreed on >= 7/8 of them (SPI; never for I2C, which has no CS)
#   bit 5  CPOL (the clock's idle level, from those records)
#   bit 4  the sample edge clocked_bus inferred (1 = rise)
#   bit 3  CS active level (SPI; 0 for I2C)
# The bus KIND is not stored: it follows from the record's data wire and the
# role table, in clocked_bus's order. The BIT ORDER is not inferred: the
# sampled capture packs MSB first by rule (an LSB-first bus with a normal CRC
# looks the same as MSB-first bytes with a reflected one).
# ---------------------------------------------------------------------------
DESC_AT = 3


def clocked_desc(cap, lv0, cls):
    """-> results byte 3 (0 = no clocked bus armed)."""
    if any(cls[x].get("cls") == "NRZ_ASYNC" for x in cls):
        return 0
    bus = clocked_bus(cap, lv0, cls)
    if "why" in bus:
        return 0
    v = 0x80 | bus["edge"] << 4
    if bus["kind"] == "SPI":
        c, f, act = bus["clock"], bus["cs"], bus["cs_active"]
        v |= act << 3
        n = hi = 0
        before = lv0
        for t, mask, lv in cap:
            if mask >> f & 1 and lv >> f & 1 == act:
                n += 1
                hi += before >> c & 1
            before = lv
        if n and 8 * hi >= 7 * n:
            v |= 0x40 | 0x20
        elif n and 8 * (n - hi) >= 7 * n:
            v |= 0x40
    return v
