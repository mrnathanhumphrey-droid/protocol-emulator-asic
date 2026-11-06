#!/usr/bin/env python3
"""PIT stage 3 piece 3: model-side evidence for the solver's METHOD (Wilson 11-05).

The frozen golden (crc_init_xorout + canonical_member, model/pit_golden.py)
solves init by Gaussian elimination: column j is A(d1, 1<<j) ^ A(d2, 1<<j), the
init's own evolution over the two data lengths. A(d, v) = v * x^n mod g (the
register shifts n zeros), so column j = x^j * P mod g with P = x^n1 + x^n2 --
the system is ONE modular equation:

    P * init = y  (mod g),   y = c1 ^ c2 ^ reg(d1, 0) ^ reg(d2, 0)

With h = gcd(P, g) and f = g / h:
  * no solution unless h divides y            ("no init solves the two lengths")
  * the kernel is the multiples of f below degree w: non-empty <=> deg h > 0
  * the canonical member -- the golden's SMALLEST init -- is init mod f: every
    other member has degree >= deg f. Smallest NUMBER and lowest DEGREE agree
    because the golden's init is the REGISTER value, bit i = the x^i
    coefficient, in BOTH bit orders (reflection orders only the message bits).
    Checked on reflected CRCs below, kernels of size 2 among them.
  * xorout = c1 ^ reg(d1, init), as canonical_member anchors it.
The chip computes s with s*P = h (mod g) by an extended binary GCD, then
init = (y / h) * s mod f -- no matrix.

THE CHECK: random catalogue and random polynomials, both bit orders, two frame
lengths, 15% with one corrupted bit, through the golden's own io_evidence;
the method must equal crc_init_xorout + canonical_member on every case.
                                          token: PIT SOLVER METHOD: PASSED
"""
from __future__ import annotations

import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import pit_s0_golden as S0                  # noqa: E402

G = S0.frozen_model()
N_CASES = 6000
SEED = 1105


def _deg(a):
    return a.bit_length() - 1


def pmul(a, b):
    r = 0
    while b:
        if b & 1:
            r ^= a
        a <<= 1
        b >>= 1
    return r


def pdivmod(a, b):
    q, db = 0, _deg(b)
    while a and _deg(a) >= db:
        s = _deg(a) - db
        q ^= 1 << s
        a ^= b << s
    return q, a


def egcd(a, b):
    """(h, s) with s * a = h (mod b), h = gcd(a, b)"""
    r0, r1, s0, s1 = a, b, 1, 0
    while r1:
        q, r = pdivmod(r0, r1)
        r0, r1, s0, s1 = r1, r, s1, s0 ^ pmul(q, s1)
    return r0, s0


def method(ev, res):
    """the chip's method -> (init, xorout, kernel?) or ("none", why)"""
    w, g, lsb = res["width"], res["full"], res["reflected"]
    lens = sorted({len(m) for m in ev if len(m) > w // 8})
    if len(lens) < 2:
        return ("none", "one frame length only")
    b1 = G.msg_bits(next(m for m in ev if len(m) == lens[0]), lsb)
    b2 = G.msg_bits(next(m for m in ev if len(m) == lens[1]), lsb)
    d1, c1, d2, c2 = b1[:-w], G.bits_to_poly(b1[-w:]), b2[:-w], G.bits_to_poly(b2[-w:])
    y = c1 ^ c2 ^ G._crc_reg(d1, g, w, 0) ^ G._crc_reg(d2, g, w, 0)
    P = pdivmod((1 << len(d1)) ^ (1 << len(d2)), g)[1]
    h, s = egcd(P, g)
    q, r = pdivmod(y, h)
    if r:
        return ("none", "no init solves the two lengths")
    init = pdivmod(pmul(q, s), pdivmod(g, h)[0])[1]
    return (init, c1 ^ G._crc_reg(d1, g, w, init), _deg(h) > 0)


def golden(ev, res):
    io = G.canonical_member(ev, res, G.crc_init_xorout(ev, res))
    if io.get("init") is None:
        return ("none", io["why"])
    return (io["init"], io["xorout"], io["class_size"] > 1)


def frame(data, w, poly, init, xorout, refl):
    """an independent textbook (Rocksoft) CRC frame"""
    def rf(v, n):
        return int(bin(v)[2:].zfill(n)[::-1], 2)
    r, top, mask = init, 1 << (w - 1), (1 << w) - 1
    for b in data:
        r ^= (rf(b, 8) if refl else b) << (w - 8)
        for _ in range(8):
            r = ((r << 1) ^ poly) & mask if r & top else (r << 1) & mask
    c = (rf(r, w) if refl else r) ^ xorout
    return list(data) + list(c.to_bytes(w // 8, "little" if refl else "big"))


#: published Rocksoft polynomials (width, poly) -- specifications; 40% of the
#: cases draw a random odd polynomial instead
POLYS = [(8, 0x07), (8, 0x31), (8, 0x9B), (16, 0x8005), (16, 0x1021), (32, 0x04C11DB7)]


def main() -> int:
    rng = random.Random(SEED)
    bad, n = 0, {}
    for _ in range(N_CASES):
        w, p = rng.choice(POLYS)
        if rng.random() < 0.4:
            p = rng.getrandbits(w) | 1
        refl = rng.random() < 0.5
        ini, xo = rng.getrandbits(w), rng.getrandbits(w)
        L1, L2 = rng.sample(range(w // 8 + 1, 14), 2)
        ms = [frame([rng.getrandbits(8) for _ in range(L)], w, p, ini, xo, refl) for L in (L1, L1, L2, L2, L1)]
        if rng.random() < 0.15:
            m = rng.choice(ms)
            m[rng.randrange(len(m))] ^= 1 << rng.randrange(8)
        res = {"width": w, "full": (1 << w) | p, "reflected": refl}
        ev = G.io_evidence(ms, res)
        a, b = method(ev, res), golden(ev, res)
        if a != b:
            bad += 1
            if bad <= 5:
                print("  *** w%d poly %x refl %d: method %s, golden %s" % (w, p, refl, a, b))
        key = ("reflected" if refl else "normal",
               "none" if b[0] == "none" else
               "kernel %d" % (G.crc_init_xorout(ev, res)["class_size"]) if b[2] else "unique")
        n[key] = n.get(key, 0) + 1
    print("PIT stage 3 solver method vs frozen crc_init_xorout + canonical_member, %d cases" % N_CASES)
    for k in sorted(n):
        print("  %-9s %-10s %5d" % (k[0], k[1], n[k]))
    need = [("reflected", "kernel 2"), ("normal", "kernel 2"), ("reflected", "unique"), ("reflected", "none")]
    thin = [k for k in need if not n.get(k)]
    if thin:
        print("  *** vacuous: no case of %s" % thin)
    print("  mismatches %d" % bad)
    ok = not bad and not thin
    print("PIT SOLVER METHOD: %s" % ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
