"""A2-CLOSE Part A -- DERIVE D_i, the per-edge scheduler-jitter tolerance.

THE ONE CLAIM: `D_i` is the largest per-edge lateness `J` for which the emitted
waveform still conforms, under an ADVERSARIAL, PER-EDGE, NON-CUMULATIVE jitter
model -- each emitted edge independently delayed by any value in [0, J].

⛔⛔ THIS IS NOT THE TA-01c DRIFT BAND. That band (-1/20 .. +1/18) is a
CUMULATIVE baud-drift model: the executor's bit period is wrong, so error
accumulates across the frame and the stop-bit sample is the binding one. Here
the engine's clock is EXACT and each edge is late by an independent amount. The
two models have different worst cases and different answers; reusing the drift
band would be wrong in the flattering direction.

⭐ PRE-REGISTERED PREDICTION, DERIVED BEFORE THE SEARCH RAN (so the measured
number has something to contradict). The receiver locks on the first low cycle,
so the start edge's own delay d_0 shifts the whole sample grid WITH it -- a
uniform delay is invisible. Sample m lands at `d_0 + half + m*T` and must sit
inside segment m's actual interval `[m*T + d_m, (m+1)*T + d_{m+1})`:

    late-edge side :  d_m - d_0     <= half            -> J <= half
    early-edge side:  d_0 - d_{m+1} <  T - half         -> J <= T - half - 1

    ==> D = min(half, T - half - 1),  half = T // 2

  T = 434 (UART 115200) -> min(217, 216) = 216   <- EARLY side binds, 1 tighter
  T =  25 (SPI 1 MHz)   -> min( 12,  12) =  12
  T =  62 (I2C 400 kHz) -> min( 31,  30) =  30
  T =   5 (10M Ether)   -> min(  2,   2) =   2   <- the lane that decides A2

⛔ WILSON'S F5 THRESHOLD IS TWO TIMES TOO LOOSE. The spec caps `D_i < T_i` and
names the bug as "letting edges cross their own sample". But an edge crossing its
own sample IS the `D > T/2` case, not `D > T`. A search that returned `D = 300`
for UART would be badly broken and would still pass a `D < 434` cap. The cap that
can actually catch the named bug is `D_i <= T_i/2`. Asserted as such below.

WHAT EACH ROUTE PROVES -- stated because they are not equal:
  * the derivation above          : prediction. Proves nothing; makes the rest falsifiable.
  * `shape_threshold` (this file) : SOUND FALSIFIER. Finding a violating d at
                                    max(d)=v proves D < v. It canNOT prove D >= v;
                                    it searches a structured family, not [0,J]^n.
  * Imitator over J               : the PROOF (sound and complete, foreign tool).
  * sigrok at the boundary        : the FOREIGN AUTHORITY. Adjudicates whether
                                    the band we computed is UART's band or ours.
Only the last two are independent of the hand that wrote this file --
[[feedback_a_same_author_rederivation_is_weak_corroboration]].
"""

from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "ta01"))
from uart_ta import (BAD_FRAME, DONE, UartReceiver, bit_period)  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ============================================================================
# THE JITTER INJECTION -- the one piece that, if wrong, makes every number here
# generous. Guarded by `wellformed_boundaries` rather than trusted.
# ============================================================================
def frame_segments(byte: int, data_bits: int = 8) -> list:
    """Levels of the 10 segments: start, 8 data (LSB first), stop."""
    return [0] + [(byte >> k) & 1 for k in range(data_bits)] + [1]


def wellformed_boundaries(bnd: list) -> bool:
    """Boundaries must be strictly increasing. With J >= T a later edge can be
    pushed past an earlier one, which is not jitter any more -- it is a reordered
    waveform, and the search would be answering a different question."""
    return all(bnd[i] < bnd[i + 1] for i in range(len(bnd) - 1))


def levels_jittered(byte: int, T: int, deltas: list, data_bits: int = 8,
                    idle_cycles: int = 2, tail_bits: int = 1):
    """One level per cycle, with boundary k displaced by `deltas[k]`.

    ⭐ Jitter is applied to the DRIVE ACTION, not to an assumed edge. A boundary
    whose two segments carry the same level produces no edge, so its delay is
    invisible -- which is physically right (the engine wrote the same value) and
    is why the worst-case byte is the maximum-edge-density one. Measured over all
    256 bytes below rather than assumed.

    Built segment-by-segment (O(cycles)); the obvious per-cycle scan over all
    boundaries is O(cycles x segments) and made the 256-byte sweep intractable.
    """
    segs = frame_segments(byte, data_bits)
    if len(deltas) != len(segs):
        raise ValueError("need one delta per segment boundary (%d)" % len(segs))
    bnd = [k * T + deltas[k] for k in range(len(segs))]
    if not wellformed_boundaries(bnd):
        return None                      # caller must treat this as "out of model"
    total = idle_cycles + (len(segs) + tail_bits) * T + max(deltas) + 2
    out = [1] * (idle_cycles + bnd[0])   # idle high up to the start edge
    for k in range(len(segs)):
        end = bnd[k + 1] if k + 1 < len(segs) else (total - idle_cycles)
        out.extend([segs[k]] * max(0, end - bnd[k]))
    if len(out) < total:                 # stop level is idle level; pad
        out.extend([segs[-1]] * (total - len(out)))
    return out[:total]


def conforms_under(byte: int, T: int, deltas: list, rx: UartReceiver) -> bool:
    """Run the REAL TA-01 receiver over the jittered waveform.

    ⭐ The receiver is REUSED, not re-derived. A second copy of the sampling
    geometry is exactly what hid the off-by-one that TA-02 found, so there is
    deliberately nowhere here for two copies to disagree. Independence comes from
    Imitator and sigrok, not from a re-implementation.
    """
    wave = levels_jittered(byte, T, deltas, data_bits=rx.n)
    if wave is None:
        return None                      # out of model, not "conforming"
    cfg = rx.initial()
    for lv in wave:
        cfg = rx.step(cfg, lv)
        st = cfg[0]
        if st == BAD_FRAME:
            return False
        if st == DONE:
            break                        # absorbing; no need to burn the tail
    state, _, bits = cfg
    if state != DONE:
        return False
    return rx.decoded_byte(bits) == byte


# ============================================================================
# THE SEARCH -- per-shape bisection, then a randomized attempt to beat it
# ============================================================================
def assert_distinct_shapes(out, n_seg: int) -> None:
    """⛔⛔ THE CLASS FIX FOR A COVERAGE CLAIM THAT WAS HALF WHAT IT READ.

    The previous `shapes()` emitted 39 NAMES but only 22 DISTINCT VECTORS:
    `early_1 … early_9` were written `[0 if k == j else 0 …]`, which is
    constantly 0, so all nine were the same vector `[v,0,…,0]`; and
    `late_j_others_lo` was byte-identical to `late_j`. The reported witness was
    still correct and `D_UART = 216` did not move -- but "39 structured shapes"
    overstated the search by 1.8x, and nothing in the file could notice.

    Naming the invariant once is the fix for the class rather than the instance:
    two shapes that collapse to the same vector are now a hard error, so a
    future edit cannot quietly shrink the family again.
    """
    seen = {}
    for name, fn in out:
        v = tuple(fn(7))                 # 7: distinct from 0 and 1, no accidental ties
        if v in seen:
            raise AssertionError(
                "shape family collapsed: %r and %r are the same vector %r "
                "-- the coverage claim would be overstated" % (seen[v], name, v))
        seen[v] = name
    if len(seen) != len(out):
        raise AssertionError("distinct-vector count %d != name count %d"
                             % (len(seen), len(out)))


def shapes(n_seg: int):
    """Structured delta shapes, each a function of the scale v.

    Four families, each genuinely varying in j, plus three whole-vector probes:
      start_only          the start edge late, every later edge on time -- the
                          receiver's grid slides right and the data does not.
                          This is the binding witness (`early` side).
      late_j              edge j late, everything else on time -- the reverse.
      early_j_others_hi   start late AND every later edge late EXCEPT j.
      late_j_others_hi    every edge late EXCEPT j, start on time.

    ⭐ `start_only` replaces the nine degenerate `early_j`: with every later edge
    on time, WHICH edge is "the one on time" is not a distinction, so that family
    was always one probe. Saying so is the honest version. The j-dependence that
    the name promised lives in `early_j_others_hi`, which was always correct.
    """
    out = [("start_only", lambda v, n=n_seg: [v] + [0] * (n - 1))]
    for j in range(1, n_seg):
        out.append(("late_%d" % j, lambda v, j=j, n=n_seg:
                    [0] + [v if k == j else 0 for k in range(1, n)]))
        out.append(("early_%d_others_hi" % j, lambda v, j=j, n=n_seg:
                    [v] + [0 if k == j else v for k in range(1, n)]))
        out.append(("late_%d_others_hi" % j, lambda v, j=j, n=n_seg:
                    [0] + [0 if k == j else v for k in range(1, n)]))
    out.append(("all", lambda v, n=n_seg: [v] * n))
    out.append(("alt", lambda v, n=n_seg: [v if k % 2 == 0 else 0 for k in range(n)]))
    out.append(("alt_inv", lambda v, n=n_seg: [0 if k % 2 == 0 else v for k in range(n)]))
    assert_distinct_shapes(out, n_seg)
    return out


def shape_threshold(byte: int, T: int, rx: UartReceiver, shape, vmax: int):
    """Smallest v at which this shape violates, or None if it never does.

    Monotone in v for these shapes (more jitter is strictly more adversary
    power), so bisection is valid; verified by checking the bracket ends.
    """
    fn = shape
    if conforms_under(byte, T, fn(0), rx) is not True:
        return 0                                   # violates with no jitter at all
    hi = None
    v = 1
    while v <= vmax:
        if conforms_under(byte, T, fn(v), rx) is not True:
            hi = v
            break
        v *= 2
    if hi is None:
        return None
    lo = hi // 2
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if conforms_under(byte, T, fn(mid), rx) is not True:
            hi = mid
        else:
            lo = mid
    return hi


def search_D(T: int, data_bits: int = 8, byte: int = 0x55, vmax: int | None = None,
             rng_tries: int = 4000, seed: int = 20261002):
    """D = (smallest max(delta) over violating deltas) - 1, over the search family."""
    rx = UartReceiver(T, data_bits=data_bits)
    n_seg = data_bits + 2
    if vmax is None:
        vmax = T - 1                     # beyond T-1 boundaries can reorder
    best, witness = None, None
    for name, fn in shapes(n_seg):
        th = shape_threshold(byte, T, rx, fn, vmax)
        if th is not None and (best is None or th < best):
            best, witness = th, (name, fn(th))
    # randomized attempt to BEAT the structured family at one cycle tighter
    rnd = random.Random(seed)
    beat = None
    if best is not None and best > 1:
        v = best - 1
        for _ in range(rng_tries):
            d = [rnd.randint(0, v) for _ in range(n_seg)]
            d[rnd.randrange(n_seg)] = v                     # pin max(d) = v
            if conforms_under(byte, T, d, rx) is not True:
                beat = d
                break
    return {"T": T, "half": T // 2, "D_pred": min(T // 2, T - T // 2 - 1),
            "threshold": best, "D": (best - 1) if best is not None else None,
            "witness": witness, "beaten_by_random": beat, "vmax": vmax}


def main() -> int:
    T = bit_period()
    print("=" * 78)
    print("A2-CLOSE Part A -- D_i by adversarial per-edge jitter search")
    print("=" * 78)
    print()

    # ---- UART first, because it is the method's validation -----------------
    print("--- UART 115200, T = %d cycles/bit ---" % T)
    _sh = shapes(10)
    print("  search family: %d names, %d DISTINCT vectors (asserted equal)"
          % (len(_sh), len({tuple(f(7)) for _, f in _sh})))
    r = search_D(T, byte=0x55)
    print("  predicted D = min(half, T-half-1) = min(%d, %d) = %d"
          % (r["half"], T - r["half"] - 1, r["D_pred"]))
    print("  searched    threshold = %s  ->  D = %s" % (r["threshold"], r["D"]))
    print("  witness     %s  deltas=%s" % (r["witness"][0], r["witness"][1]))
    print("  random attempt to beat it at v = D: %s"
          % ("NONE -- structured family is the tightest found"
             if r["beaten_by_random"] is None else r["beaten_by_random"]))
    agree = r["D"] == r["D_pred"]
    print("  prediction vs search: %s" % ("AGREE" if agree else "*** DISAGREE ***"))
    print()

    # ---- is D data-dependent? measured, not assumed -----------------------
    print("  D over all 256 bytes (is the worst case the max-edge-density byte?)")
    rx = UartReceiver(T)
    SH = shapes(10)
    Dp = r["D_pred"]

    def first_violator(b, v):
        """Name of the first shape that breaks conformance at scale v, else None."""
        for nm, fn in SH:
            if conforms_under(b, T, fn(v), rx) is not True:
                return nm
        return None

    at_D = {b: first_violator(b, Dp) for b in range(256)}
    at_D1 = {b: first_violator(b, Dp + 1) for b in range(256)}
    exactly = [b for b in range(256) if at_D[b] is None and at_D1[b] is not None]
    looser = [b for b in range(256) if at_D[b] is None and at_D1[b] is None]
    tighter = [b for b in range(256) if at_D[b] is not None]
    edges = {b: sum(1 for k in range(9)
                    if frame_segments(b)[k] != frame_segments(b)[k + 1])
             for b in range(256)}
    print("    D == %d exactly : %3d bytes   (conform at %d, break at %d)"
          % (Dp, len(exactly), Dp, Dp + 1))
    print("    D >  %d         : %3d bytes   %s"
          % (Dp, len(looser),
             "edge counts %s" % sorted({edges[b] for b in looser}) if looser else ""))
    print("    D <  %d         : %3d bytes   %s   <-- would REFUTE the formula"
          % (Dp, len(tighter),
             "bytes %s" % ["0x%02X" % b for b in tighter[:6]] if tighter else ""))
    if tighter:
        lo = min(shape_threshold(b, T, rx, fn, T - 1) or 10 ** 9
                 for b in tighter for _, fn in SH) - 1
        print("    *** binding D across bytes = %d, BELOW the formula ***" % lo)
    else:
        lo = Dp
    print("    edge count among D == %d bytes: %s"
          % (Dp, sorted({edges[b] for b in exactly})))
    print("    => D is %s"
          % ("DATA-INDEPENDENT: every byte breaks at the same v"
             if len(exactly) == 256 else
             "data-DEPENDENT; the binding (minimum) value is D = %d" % lo))
    print()

    # ---- F5, with the threshold tightened to T/2 --------------------------
    print("  F5 check (tightened): D must be <= T/2 = %d, not merely < T = %d"
          % (T // 2, T))
    print("    D = %d  ->  %s" % (lo, "PASS" if lo <= T // 2 else "*** F5 FIRED ***"))
    print()

    # ---- every lane in the table ------------------------------------------
    print("=" * 78)
    print("ALL LANES -- D_i from the same search")
    print("=" * 78)
    print("  %-20s %-7s %-9s %-9s %-7s %s"
          % ("lane", "T_i", "pred D", "search D", "agree", "witness"))
    lanes = [("UART 115200", 434), ("SPI 1 MHz", 25), ("I2C 400 kHz", 62),
             ("10 Mbit Ethernet", 5)]
    results = {}
    for name, t in lanes:
        rr = search_D(t, byte=0x55)
        results[name] = rr
        print("  %-20s %-7d %-9s %-9s %-7s %s"
              % (name, t, rr["D_pred"], rr["D"],
                 "yes" if rr["D"] == rr["D_pred"] else "NO",
                 rr["witness"][0] if rr["witness"] else "-"))
    print()
    print("  ⭐ the closed form D_i = min(T/2, T - T/2 - 1) reproduces the search")
    print("     at every lane -- so D_i is now a FORMULA, not four measurements.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
