"""DOES THE START-BIT GUARD REALLY BUY TOLERANCE? -- the impossibility test.

⛔⛔ THE DRAMATIC RESULT, AND WHY IT IS SUSPECT. Imitator's general region is
    19*U > G0 + 8*G  &  G0 + 9*G > 19*U  &  G0 > U
which is 2-dimensional: for almost any data-bit guard `G` there is SOME start-bit
guard `G0` that satisfies it. Taken at face value, giving the start bit its own
table field widens the admissible data period from TA-01c's +-5% band to
roughly (2, 2.25*U) -- a reprogrammable table conforming at a data rate a
fixed-function UART never could.

⛔ A RESULT THAT LARGE FROM ONE EXTRA FIELD IS A RESULT TO ATTACK. The step that
makes it impossible: THE MONITOR BEING SYNTHESIZED OVER CHECKS ONLY TWO OF THE TEN
SAMPLES. TA-01c's model deliberately records the data bits without judging their
phase, because "the framing conjunct is value-independent" -- which is correct for
FRAMING and silently wrong for the BYTE. Satisfying start-and-stop while the eight
middle samples slip into neighbouring bits decodes a DIFFERENT BYTE, and the
synthesized region cannot see that.

So the region is a FRAMING region. This probe measures whether it is also a
DECODING region, by checking all ten sample phases and the decoded byte at each
(G0, G) the region admits. Whatever it finds, the claim gets stated at the
strength that survives: `#synth` being exact and complete says the constraint is
the true answer TO THE QUESTION ASKED, which is not the same as the question
being the right one.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from interp import E, Interp

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

U = 217                      # monitor half bit-period; monitor bit period T = 2U
N = 8


def uart_table(byte: int, g0: int, g: int, pin: int = 0) -> list:
    """UART with the start-bit entry carrying its OWN guard field G0.

    Built here rather than in `interp.py`: this is a SPECULATIVE table convention
    under test, and the frozen descriptor should not grow a builder for it until
    the convention is shown to be worth having.
    """
    hi, lo = (1 << pin), 0
    t = [E(g0, lo, 1)]                                     # start bit, guard G0
    for k in range(N):
        t.append(E(g, hi if (byte >> k) & 1 else lo, len(t) + 1))
    t.append(E(g, hi, len(t) + 1))                         # stop bit
    t.append(E(4 * g, hi, len(t)))                         # park idle
    return t


def ideal_samples() -> list:
    """The textbook schedule: bit centres at U, 3U, 5U, ..., 19U.

    ⛔ EXACT, with no off-by-one. TA-02's band-edge probe measured TA-01's
    `UartReceiver` sampling every T+1 = 435 cycles instead of T = 434 -- an
    effective 114,943 baud -- which shifted its band by a cycle on both ends.
    Reusing that receiver here would fold its defect into this measurement.
    """
    return [U + 2 * U * k for k in range(N + 2)]           # 10 samples


def windows(g0: int, g: int) -> list:
    """Executor bit windows: [0,G0) then nine spans of G."""
    out, t = [(0, g0)], g0
    for _ in range(N + 1):
        out.append((t, t + g))
        t += g
    return out                                             # 10 windows


def evaluate(byte: int, g0: int, g: int) -> dict:
    tbl = uart_table(byte, g0, g)
    n = g0 + 10 * g + 4 * g
    wave = Interp(tbl).run(n)
    smp = ideal_samples()
    wins = windows(g0, g)

    phases, levels = [], []
    for i, c in enumerate(smp):
        w = next((j for j, (a, b) in enumerate(wins) if a <= c < b), None)
        phases.append(w == i)
        levels.append(wave[c] if c < len(wave) else 1)

    framing_ok = phases[0] and phases[-1]                  # what Imitator checked
    all_phase_ok = all(phases)
    bits = levels[1:N + 1]
    decoded = sum(b << k for k, b in enumerate(bits))
    level_frame_ok = (levels[0] == 0 and levels[-1] == 1)
    return {"framing_phase": framing_ok, "all_phase": all_phase_ok,
            "decoded": decoded, "byte_ok": decoded == byte,
            "level_frame_ok": level_frame_ok,
            "slipped": [i for i, p in enumerate(phases) if not p]}


def g0_range(g: int) -> range:
    """Integer G0 satisfying Imitator's region at this G."""
    lo = max(U + 1, 19 * U - 9 * g + 1)
    hi = 19 * U - 8 * g - 1
    return range(lo, hi + 1)


def main() -> int:
    byte = 0x55
    print("=== DOES THE START-BIT FIELD BUY TOLERANCE? ===")
    print("    U = %d  (monitor bit period T = %d, the TA-01c convention T = 2U)"
          % (U, 2 * U))
    print("    Imitator region: G0 + 8G < 19U < G0 + 9G  &  G0 > U")
    print("    single-G close-out band: 9G < 19U < 10G  ->  %.2f < G < %.2f"
          % (19 * U / 10.0, 19 * U / 9.0))
    print()

    gs = [2, 50, 100, 200, 300, 350, 400, 413, 434, 458, 470, 480, 487]
    print("  %-6s %-14s %-9s %-9s %-9s %-8s %s"
          % ("G", "G0 admitted", "framing", "all-phase", "decoded", "byte", "slipped"))
    admits_framing, admits_byte = [], []
    for g in gs:
        r = g0_range(g)
        if not len(r):
            print("  %-6d %-14s %s" % (g, "(empty)", "region admits nothing"))
            continue
        g0 = r[len(r) // 2]                                # a representative
        ev = evaluate(byte, g0, g)
        admits_framing.append(g)
        if ev["byte_ok"] and ev["all_phase"]:
            admits_byte.append(g)
        print("  %-6d %-14s %-9s %-9s %-9s %-8s %s"
              % (g, "%d..%d (n=%d)" % (r[0], r[-1], len(r)),
                 "OK" if ev["framing_phase"] else "no",
                 "OK" if ev["all_phase"] else "**NO**",
                 "0x%02X" % ev["decoded"],
                 "OK" if ev["byte_ok"] else "**WRONG**",
                 ev["slipped"][:6]))
    print()

    # ⛔⛔ MEASURED ACROSS THE PAYLOAD, NOT ON ONE BYTE. Which sample a slipped
    # phase lands on decides the decoded value, so the band is byte-dependent by
    # construction. 0x55/0x0F/0x01 are bit-order SENSITIVE; 0x00/0xFF/0xA5 are
    # palindromes and cannot catch a bit-order error on their own.
    TEST = [0x55, 0x0F, 0x01, 0x00, 0xFF, 0xA5, 0x3C, 0x80]
    full_f, per_byte, shared = [], [], []
    for g in range(2, 600):
        r = g0_range(g)
        if not len(r):
            continue
        full_f.append(g)
        # (a) a G0 chosen PER BYTE -- legitimate, since the table is reloaded per
        #     payload anyway; the band is then the intersection over bytes.
        if all(any(evaluate(b, g0, g)["all_phase"]
                   and evaluate(b, g0, g)["byte_ok"] for g0 in r) for b in TEST):
            per_byte.append(g)
        # (b) ONE G0 that works for EVERY byte -- the real design claim, because a
        #     table convention you have to retune per payload is not a convention.
        if any(all(evaluate(b, g0, g)["all_phase"] and evaluate(b, g0, g)["byte_ok"]
                   for b in TEST) for g0 in r):
            shared.append(g)

    sg = (int(19 * U / 10.0) + 1, int(19 * U / 9.0))

    def band(v):
        return "[%d, %d]" % (v[0], v[-1]) if v else "none"

    def pct(v):
        return ("%+.2f%% .. %+.2f%%, width %.2f%% of T"
                % ((v[0] / (2.0 * U) - 1) * 100, (v[-1] / (2.0 * U) - 1) * 100,
                   (v[-1] - v[0]) / (2.0 * U) * 100)) if v else "-"

    print("  SWEEP over G in [2,600), %d test bytes, trying EVERY admitted G0:"
          % len(TEST))
    print("    FRAMING only (what Imitator was asked):   %-12s  %s"
          % (band(full_f), pct(full_f)))
    print("    + all 10 phases + byte, G0 per byte:      %-12s  %s"
          % (band(per_byte), pct(per_byte)))
    print("    + all 10 phases + byte, ONE shared G0:    %-12s  %s"
          % (band(shared), pct(shared)))
    print("    single-G band (TA-01c integer shadow):    %-12s  %s"
          % ("[%d, %d]" % sg, pct(list(range(sg[0], sg[1] + 1)))))
    print()
    print("  VERDICT")
    if not shared:
        print("    No shared G0 decodes every byte: the region is framing-only.")
    elif (shared[0], shared[-1]) == sg:
        print("    The widening is ENTIRELY AN ARTEFACT of the monitor checking only")
        print("    2 of 10 samples. Require all ten phases and the decoded byte and")
        print("    the admissible data period collapses back to exactly the single-G")
        print("    band. THE START-BIT FIELD BUYS NOTHING, and the framing region")
        print("    alone would have been a flattering overstatement.")
    else:
        w_new = shared[-1] - shared[0]
        w_old = sg[1] - sg[0]
        print("    The start-bit field DOES buy tolerance, but %.2fx -- not the"
              % (w_new / float(w_old)))
        print("    %.0fx the framing region advertises."
              % ((full_f[-1] - full_f[0]) / float(w_old)))
        print("    admissible data period: %s -> %s cycles (%d -> %d wide)"
              % ("[%d, %d]" % sg, band(shared), w_old, w_new))
        print()
        print("    ⛔ AND THE FRAMING REGION ON ITS OWN WAS THE FLATTERING ANSWER.")
        print("    `#synth` returned a constraint that is exact and complete -- for")
        print("    THE QUESTION ASKED. The question omitted 8 of the 10 samples, so")
        print("    an exact answer to it overstated the envelope by %.0fx."
              % ((full_f[-1] - full_f[0]) / float(w_new)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
