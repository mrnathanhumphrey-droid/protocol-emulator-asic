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
