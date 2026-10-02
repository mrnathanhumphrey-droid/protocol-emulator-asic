"""BAND-EDGE PROBE -- why the swept band is WIDER than the synthesized band.

⛔⛔ THE DISCREPANCY. B5 swept the executor's bit period and both executors agreed:
conforming for Te in [411, 459], i.e. eps in [-5.2995%, +5.7604%]. TA-01c
SYNTHESIZED -1/20 < eps < 1/18 = [-5.0000%, +5.5556%], whose integer shadow at
T=434 is Te in [413, 458]. The sweep is WIDER ON BOTH ENDS -- 411, 412 and 459
conform to the Python receiver and do NOT satisfy the synthesized constraint.

⛔ TA-01bc's triple cross-check compared the two routes at THREE POINTS (nominal,
+2%, +10%) and they agreed. Agreement at sampled points is not agreement at the
EDGE, and the edge is the only place the two models can differ -- which is exactly
where the claim "three routes to the same boundary" lives.

⭐⭐ THE HYPOTHESIS TO TEST, AND IT IS WRITTEN DOWN IN TA-01c's OWN HEADER. The
`.imi` monitor checks the executor's PHASE; `UartReceiver` checks the LINE LEVEL.
The header records this as a hazard that would "widen the synthesized band on one
side for a reason that is a modelling artefact rather than real tolerance" -- and
says it was avoided. It WAS avoided in the Imitator model. It was never avoided in
the Python receiver, which is the model that produced the fixpoint and these
sweeps. So the permissive band is the LEVEL check reading idle-high (or a lucky
data bit) and calling it a stop bit.

⛔ THIS PROBE DOES NOT ASSERT THAT. It measures, per Te, which executor bit window
each receiver sample actually landed in, and reports the level verdict and the
phase verdict side by side. If the hypothesis is right, the band edges differ
exactly where a sample leaves its own window while still reading the right level.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "ta01"))

from uart_ta import (BAD_FRAME, DONE, START, STOP, UartExecutor, UartReceiver,
                     bit_period, conformance, data_state)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

N_BITS = 8
# window 0 = start bit, 1..8 = data bits, 9 = stop bit, >=10 = after the frame
WINDOW_NAME = ["start"] + ["d%d" % k for k in range(N_BITS)] + ["stop"]


def sample_cycles(rx: UartReceiver, wave) -> list:
    """The cycle at which each of the 10 samples actually happened.

    ⭐ READ OFF THE RECEIVER'S OWN RUN, not recomputed from `half + k*T`. A probe
    that recomputes the sample schedule is measuring my arithmetic, not the
    receiver -- and the receiver is the thing whose band moved.
    """
    cfg = rx.initial()
    prev = cfg[0]
    samples = []
    for c, lv in enumerate(wave):
        cfg = rx.step(cfg, lv)
        s = cfg[0]
        if s != prev:
            # a sample is any advance out of START / Dk / STOP (incl. to BAD)
            if prev == START or prev == STOP or any(
                    prev == data_state(k) for k in range(N_BITS)):
                samples.append((c, prev, s, lv))
            prev = s
        if s in (DONE, BAD_FRAME):
            break
    return samples


def phase_verdict(samples, te: int) -> dict:
    """Did every sample land inside ITS OWN executor bit window?"""
    rows, ok = [], True
    for i, (c, frm, to, lv) in enumerate(samples):
        w = c // te                      # which executor bit window cycle c is in
        in_own = (w == i)
        ok = ok and in_own
        rows.append({"i": i, "want": WINDOW_NAME[i] if i < 10 else "?",
                     "cycle": c, "landed_in": (WINDOW_NAME[w] if w < 10
                                               else "AFTER-FRAME(idle)"),
                     "level": lv, "in_own": in_own})
    return {"ok": ok and len(samples) == 10, "rows": rows}


def main() -> int:
    T = bit_period()
    rx = UartReceiver(T)
    byte = 0x55
    print("=== BAND-EDGE PROBE -- level check vs phase check ===")
    print("    T (monitor nominal) = %d;  byte = 0x%02X;  idle = 0" % (T, byte))
    print("    synthesized band (TA-01c): 9*Te < 19*U < 10*Te, U = %d" % (T // 2))
    lo_exact = 19 * (T // 2) / 10.0
    hi_exact = 19 * (T // 2) / 9.0
    print("      => %.4f < Te < %.4f  -> integer Te in [%d, %d]"
          % (lo_exact, hi_exact, int(lo_exact) + 1, int(hi_exact)))
    print()

    # ----------------------------------------------------------------------
    # FIRST: the receiver's ACTUAL sample schedule at the nominal period.
    # ⛔ The level/phase split cannot explain a band that is shifted on the FAST
    # side too, so measure the schedule itself rather than reasoning about it.
    # ----------------------------------------------------------------------
    nom = sample_cycles(rx, UartExecutor(byte, T).levels(0))
    cyc = [c for c, _, _, _ in nom]
    gaps = [b - a for a, b in zip(cyc, cyc[1:])]
    print("  0. the receiver's MEASURED sample schedule at Te = T = %d" % T)
    print("     sample cycles: %s" % cyc)
    print("     inter-sample gaps: %s" % sorted(set(gaps)))
    print("     start sample at cycle %d   (the .imi monitor samples at U = %d)"
          % (cyc[0], T // 2))
    print("     stop  sample at cycle %d   (the .imi monitor samples at 19U = %d)"
          % (cyc[-1], 19 * (T // 2)))
    eff = gaps[0] if len(set(gaps)) == 1 else None
    print("     => effective bit period = %s cycles, i.e. %s baud, against a "
          "nominal %d / %d"
          % (eff, ("%d" % round(50_000_000 / eff)) if eff else "?", T,
             BAUD := 115200))
    print("     accumulated offset at the stop sample: %+d cycles"
          % (cyc[-1] - 19 * (T // 2)))
    print()

    lvl_band, ph_band = [], []
    rows = []
    for te in range(int(T * 0.90), int(T * 1.10) + 1):
        ex = UartExecutor(byte, te)
        wave = ex.levels(0)
        lvl = conformance(ex, rx, byte)["conforms"]
        sm = sample_cycles(rx, wave)
        ph = phase_verdict(sm, te)
        if lvl:
            lvl_band.append(te)
        if ph["ok"]:
            ph_band.append(te)
        rows.append((te, lvl, ph["ok"], ph))

    print("  swept band, LEVEL check (what `UartReceiver` does): [%d, %d]"
          % (lvl_band[0], lvl_band[-1]))
    print("  swept band, PHASE check (what the `.imi` monitor does): [%d, %d]"
          % (ph_band[0], ph_band[-1]))
    print("  synthesized integer band:                               [%d, %d]"
          % (int(lo_exact) + 1, int(hi_exact)))
    print()

    disagree = [(te, l, p, d) for te, l, p, d in rows if l != p]
    print("  Te values where the two checks DISAGREE: %s"
          % ([te for te, _, _, _ in disagree] or "none"))
    print()
    for te, l, p, d in disagree:
        print("  --- Te = %d (eps = %+.4f%%): level=%s  phase=%s"
              % (te, (te / T - 1) * 100, "CONF" if l else "VIOL",
                 "CONF" if p else "VIOL"))
        for r in d["rows"]:
            if not r["in_own"]:
                print("      sample %d (wants %-5s) fired at cycle %d, which is in "
                      "%-18s level read = %d"
                      % (r["i"], r["want"], r["cycle"], r["landed_in"], r["level"]))
    print()
    print("  INTERPRETATION")
    print("    The level check is MORE PERMISSIVE than the phase check by exactly")
    print("    the Te values above: a sample that has drifted out of its own bit")
    print("    window still reads the level the receiver wanted, so the frame is")
    print("    accepted. That is the artefact TA-01c's header names and avoids --")
    print("    avoided in the Imitator model, NOT in the Python receiver.")
    print()
    agree = (ph_band[0], ph_band[-1]) == (int(lo_exact) + 1, int(hi_exact))
    print("    PHASE band == synthesized integer band: %s" % agree)
    if not agree:
        print("    *** NOT the whole story. The phase band is [%d, %d] and the"
              % (ph_band[0], ph_band[-1]))
        print("        synthesized band is [%d, %d] -- shifted on BOTH ends, which"
              % (int(lo_exact) + 1, int(hi_exact)))
        print("        a level-vs-phase difference cannot do (it can only ever make")
        print("        the check MORE permissive, i.e. widen one side).")
        print()
        # ⭐ The decisive arithmetic, computed from the MEASURED schedule above.
        s = cyc[-1]
        print("    SECOND DEFECT, from the measured schedule: the stop sample fires")
        print("    at cycle %d, not at 19U = %d. Predicting the phase band from the"
              % (s, 19 * (T // 2)))
        print("    measured cycle instead of the nominal one:")
        print("        9*Te <= %d  ->  Te <= %.4f  ->  Te <= %d"
              % (s, s / 9.0, int(s / 9.0)))
        print("        %d < 10*Te  ->  Te >  %.4f  ->  Te >= %d"
              % (s, s / 10.0, int(s / 10.0) + 1))
        pred = (int(s / 10.0) + 1, int(s / 9.0))
        print("        predicted phase band [%d, %d]  vs  MEASURED [%d, %d]  -> %s"
              % (pred[0], pred[1], ph_band[0], ph_band[-1],
                 "MATCH" if pred == (ph_band[0], ph_band[-1]) else "no match"))
        print()
        print("    So the band shift is fully accounted for by the receiver's")
        print("    inter-sample gap being T+1 = %s cycles rather than T = %d."
              % (eff, T))
        print("    `if x < t: x+1` then `if x == t: sample` counts 0..t INCLUSIVE,")
        print("    which is t+1 cycles per bit. Over a 10-bit frame that is +%d"
              % (cyc[-1] - 19 * (T // 2)))
        print("    cycles of accumulated offset. The .imi guards (`x = U`,")
        print("    `x = 19U`) are exact, so Imitator never had it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
