"""PIT RTL chunk 1 golden: the CAPTURE ENCODING, bit-exact (prediction
rulings/pit_rtl_c1.a5b1ccee.stamped.txt). Input: the edge log -- [(cycle,
mask)] of changes of the masked uio_q1 wires, cycles counted from the PIT's
start (cycle 0 = the first PIT cycle). Output: the 384 capture bytes (store
128..511), the records stored, and the overflow flag -- what the RTL writes.

THE PACKER, as the RTL builds it: record bits enter a 64-bit accumulator at
the record's cycle; from the NEXT cycle on, one whole byte drains to the store
per cycle. A record that would not fit the accumulator is an OVERRUN, and one
that would push the written total past 384 bytes is FULL: either stops the
capture (overflow = 1; nothing after it is recorded). Bits that never make a
whole byte are not written (documented: up to 7 trailing bits are lost).
"""
CAP_BASE, CAP_BYTES = 128, 384
N_RAW = 16
QMAX = 16
SAT = 0xFFFF
ACC_BITS = 64


def k_of(raw_intervals):
    mean = sum(raw_intervals) >> 4
    return max(0, ((mean * 11) >> 4).bit_length() - 1)


def _b(v, n):
    return [(v >> b) & 1 for b in range(n - 1, -1, -1)]


def record_bits(i, mask, k, raw):
    i = min(i, SAT)
    if raw:
        return _b(i, 16) + _b(mask, 8)
    q = i >> k
    body = ([1] * QMAX + _b(i, 16)) if q >= QMAX else ([1] * q + [0] + _b(i, k))
    return body + _b(mask, 8)


#: the starting-levels byte (Wilson 10-29): uio & mask at the PIT's cycle 0
SLV_AT = 39


def budget_cycles(b):
    """SNIFF image byte 1 -> the budget in cycles (None = off): 2^b, b clamped to 35."""
    return None if b == 0 else 1 << min(b, 35)


def status(n, why):
    """the status bytes the RTL writes once stopped and drained (all zero if it
    never stopped). Every stop writes them, budget included (Wilson 10-29):
    byte 2 bit 7 = TRUNCATED (full / overrun: every result PARTIAL; a budget
    stop is a normal completion); byte 28 bit 7 = overrun, bit 6 = budget;
    {28[5:0], 29} = WHOLE records stored."""
    if why is None:
        return {2: 0x00, 28: 0x00, 29: 0x00}
    return {2: 0x00 if why == "budget" else 0x80,
            28: (0x80 if why == "overrun" else 0) | (0x40 if why == "budget" else 0) | ((n >> 8) & 0x3F),
            29: n & 0xFF}


def decode(cap, n):
    """THE INVERSE of `encode` (PIT chunk 2, stage 0's input): the first `n`
    records of the 384 capture bytes -> [(t, mask)], t accumulated from the
    STORED intervals (so a saturated interval reads 0xFFFF -- what the RTL sees).
    `n` is the results' count, which is WHOLE records (Wilson 10-29: a final
    record cut by the unwritten 0-7 trailing bits is not counted), so every
    one of the n is fully in the written bytes. -> (records, k)."""
    bits = []
    for byte in cap:
        bits += _b(byte, 8)
    pos, k, t, out = 0, 0, 0, []

    def take(w):
        nonlocal pos
        if pos + w > len(bits):
            raise EOFError
        v = 0
        for b in bits[pos:pos + w]:
            v = (v << 1) | b
        pos += w
        return v
    try:
        for r in range(n):
            if r < N_RAW:
                i = take(16)
            else:
                if r == N_RAW:
                    k = take(4)
                q = 0
                while q < QMAX and take(1):
                    q += 1
                i = take(16) if q >= QMAX else (q << k) | take(k)
            mask = take(8)
            t += i
            out.append((t, mask))
    except EOFError:
        pass
    return out, k


def encode(log, budget=None, ncyc=None):
    """-> (bytes[384], WHOLE records stored, overflow, why): why = "overrun"
    (the accumulator would overflow), "full" (the store would), "budget" (the
    capture reached `budget` cycles -- edges at t >= budget are not recorded),
    or None (still listening at `ncyc`). overflow = 1 for full / overrun only.
    The count excludes a final record cut by the unwritten 0-7 trailing bits."""
    bits, n, overflow, k, raws, why = [], 0, 0, 0, [], None
    acc, last_t = 0, 0
    for t, mask in log:
        if budget is not None and t >= budget:
            why = "budget"
            break
        if n > 0:
            acc -= 8 * min(acc // 8, t - last_t)      # one byte per cycle since the last record
        rb = record_bits(t - last_t, mask, k, n < N_RAW)
        if n == N_RAW:
            rb = _b(k, 4) + rb                         # k precedes the first coded record
        if acc + len(rb) > ACC_BITS or len(bits) + len(rb) > CAP_BYTES * 8:
            overflow = 1
            why = "overrun" if acc + len(rb) > ACC_BITS else "full"
            break
        bits += rb
        acc += len(rb)
        if n < N_RAW:
            raws.append(min(t - last_t, SAT))
            if n == N_RAW - 1:
                k = k_of(raws)
        n += 1
        last_t = t
    if why is None and budget is not None and (ncyc is None or budget <= ncyc):
        why = "budget"                                 # a quiet tail: the budget still ends it
    if len(bits) % 8:
        n -= 1                                         # the last record is cut (never fully written)
    out = bytearray(CAP_BYTES)
    whole = len(bits) - len(bits) % 8
    for i in range(0, whole, 8):
        v = 0
        for b in bits[i:i + 8]:
            v = (v << 1) | b
        out[i // 8] = v
    return bytes(out), n, overflow, why
