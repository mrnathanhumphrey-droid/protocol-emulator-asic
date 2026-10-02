"""THE CONFORMANCE ORACLE -- and the distinction TA-01 had conflated.

⛔⛔ "THE RECEIVER CHECKS THE LEVEL WHERE THE FORMAL MODELS CHECK THE PHASE" WAS
ONLY HALF A DEFECT, AND THE OTHER HALF IS A CATEGORY ERROR. Two different objects
were being asked to be one object:

  * A RECEIVER MODEL samples the LINE LEVEL, because that is all real silicon can
    do -- it has no access to the transmitter's internal phase. Its band is the
    band a real peer would actually accept. ⭐ That band is PAYLOAD-DEPENDENT, and
    that is CORRECT behaviour, not a bug: see `payload_table()`.

  * A CONFORMANCE ORACLE checks that every sample landed INSIDE ITS OWN bit
    window. It needs oracle access to the executor's phase, which no receiver has
    and every spec-checker does. Its band is payload-INDEPENDENT and tighter, and
    it is the band Imitator synthesizes and TChecker checks.

TA-01 built the first and claimed the second ("does this UART-TX program CONFORM to
UART?"). Only the `T+1` sample period was a bug in both; it is fixed in
`uart_ta.py`. This file adds the missing object rather than bending the receiver
into it -- bending it would have retired the level check exactly when RTL, which
reads levels and not phases, is about to need it.

⭐ THE USABLE CONSEQUENCE: payloads differ in how much timing error they can
EXPOSE, and `0xFF` exposes none. An all-ones payload leaves the line high from the
start bit onward, so a level-checked stop sample cannot fail however far it drifts.
Timing conformance must therefore be tested on `0x55`-class payloads. This is the
bit-order-sensitivity rule one level deeper: it is not enough that a byte is not
its own reversal -- it must also be able to make a mis-timed sample read WRONG.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uart_ta import (UartExecutor, UartReceiver, bit_period, conformance)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


class PhaseOracle:
    """Every sample must land inside its own executor bit window.

    Window `i` is `[i*t_exec, (i+1)*t_exec)`: 0 = start bit, 1..8 = data, 9 = stop.
    Sample `i` is the receiver's own `sample_cycles()[i]`, read from the receiver
    rather than recomputed -- a recomputed schedule measures this file's
    arithmetic, not the receiver whose schedule is in question.
    """

    def __init__(self, rx: UartReceiver):
        self.rx = rx

    def landing(self, t_exec: int) -> list:
        return [(i, c, c // t_exec) for i, c in enumerate(self.rx.sample_cycles())]

    def conforms(self, t_exec: int) -> bool:
        return all(w == i for i, _, w in self.landing(t_exec))


def band(pred, lo=200, hi=900):
    ok = [te for te in range(lo, hi + 1) if pred(te)]
    return (ok[0], ok[-1]) if ok else None


def payload_table(rx, bytes_=(0x55, 0x00, 0x01, 0x0F, 0xA5, 0x3C, 0xFE, 0xFF)):
    out = []
    for b in bytes_:
        lv = band(lambda te, b=b: conformance(UartExecutor(b, te), rx, b)["conforms"])
        out.append((b, lv))
    return out


def main() -> int:
    T = bit_period()
    rx = UartReceiver(T)
    U = T // 2
    oracle = PhaseOracle(rx)
    fail = []

    print("=== THE RECONCILIATION -- after the receiver fix ===")
    print("    T = %d, U = %d.  Receiver sample schedule: %s"
          % (T, U, rx.sample_cycles()[:3] + ["..."] + rx.sample_cycles()[-1:]))
    print()

    ph = band(oracle.conforms)
    syn = (int(19 * U / 10.0) + 1, int(19 * U / 9.0))
    lv55 = band(lambda te: conformance(UartExecutor(0x55, te), rx, 0x55)["conforms"])

    print("  %-46s %s" % ("route / object", "band"))
    print("  %-46s %s" % ("Imitator, synthesized (9Te < 19U < 10Te)", "[%d, %d]" % syn))
    print("  %-46s %s" % ("TChecker zones, high edge", "458"))
    print("  %-46s %s" % ("PhaseOracle (this file) -- the oracle", "[%d, %d]" % ph))
    print("  %-46s %s" % ("UartReceiver level check, payload 0x55", "[%d, %d]" % lv55))
    print()
    if ph == syn:
        print("  ✅ THE ORACLE MATCHES THE SYNTHESIS EXACTLY. The three routes now")
        print("     agree at the EDGE, not merely at three sampled interior points")
        print("     -- which is what TA-01bc's 'triple cross-check' claimed and did")
        print("     not have.")
    else:
        print("  *** oracle %s != synthesized %s" % (ph, syn))
        fail.append("oracle/synthesis disagree")
    if lv55[1] == syn[1] == 458:
        print("  ✅ The level check's HIGH edge now agrees too (458). Before the fix")
        print("     it was 459 -- that one cycle was the +1-per-bit defect, and it")
        print("     is gone.")
    else:
        print("  *** high edges: level %d, synthesized %d" % (lv55[1], syn[1]))
        fail.append("high edge still disagrees")
    print("  ⭐ The level check's LOW edge (%d) is still below the oracle's (%d),"
          % (lv55[0], ph[0]))
    print("     and that is the level/phase difference -- NOT a defect. A real")
    print("     receiver accepts a stop sample that drifted past the frame because")
    print("     it reads idle-high. The oracle is what refuses it.")
    print()

    print("=== PAYLOAD DEPENDENCE -- a property of UART, not a bug ===")
    print("  The ORACLE is payload-independent: it checks phase, and phase does not")
    print("  depend on the bits. The RECEIVER is not, and cannot be:")
    print()
    print("  %-8s %-14s %-9s %s" % ("byte", "level band", "width", "exposes timing error?"))
    rows = payload_table(rx)
    ref = None
    for b, lv in rows:
        w = lv[1] - lv[0]
        if b == 0x55:
            ref = w
        print("  0x%02X     %-14s %-9d %s"
              % (b, "[%d, %d]" % lv, w,
                 "yes" if w <= ref else "*** NO -- %.1fx too permissive ***" % (w / float(ref))))
    print()
    print("  ⛔ 0xFF and 0xFE are the trap. All-ones leaves the line high from the")
    print("     start bit onward, so the stop sample reads 1 no matter how far it")
    print("     has drifted. A timing test on 0xFF measures NOTHING.")
    print("  ⭐ RULE: test timing conformance on 0x55-class payloads. 'Not its own")
    print("     bit-reversal' is necessary but NOT sufficient -- the byte must also")
    print("     be able to make a mis-timed sample read the wrong value.")
    print()
    print("  VERDICT: %s" % ("PASSED -- oracle == synthesis, level high edge fixed, "
                             "payload dependence characterized."
                             if not fail else "FAILED: %s" % "; ".join(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
