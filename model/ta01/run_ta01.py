"""TA-01 runner -- all gates, one table. Re-runnable by anyone with sigrok-cli.

Gate order is the ruled order and it matters: gate 0 first, because if a foreign
decoder cannot read our line then nothing downstream is worth running.
"""

from __future__ import annotations

import os
import sys
import time

# the Windows console is cp1252; without this every marker glyph raises
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uart_ta import (BAUD_DEFAULT, F_CLK, UartExecutor, UartReceiver,
                     bit_period, conformance, determinism_totality_report)
from gate0_external import rev8, run_case


def first_wrong_data_bit(t_mon: int, t_exec: int, n: int = 8) -> int | None:
    """Which data bit does the monitor FIRST sample from the wrong executor bit?

    ⛔ THIS IS THE MECHANISM ASSERTION, AND IT IS THE POINT. A mutant that goes
    red tells you a colour; it does not tell you WHY. M1 is a baud-drift mutant,
    so it must die BECAUSE the sample point drifts out of its bit -- not because
    something else incidentally broke. The monitor samples Dk at
    half + T_mon*(k+1); the executor holds Dk over [T_exec*(k+1), T_exec*(k+2)).
    """
    half = t_mon // 2
    for k in range(n):
        s = half + t_mon * (k + 1)
        idx = (s // t_exec) - 1          # executor bit index the sample lands in
        if idx != k:
            return k
    return None


def banner(s: str) -> None:
    print()
    print("=" * 74)
    print(s)
    print("=" * 74)


def main() -> int:
    T = bit_period()
    rx = UartReceiver(T)
    failures: list[str] = []

    # ---------------------------------------------------------------- GATE 1
    banner("GATE 1 -- determinism AND totality (two separate checks)")
    rep = determinism_totality_report(rx)
    print("  %d combinations checked (%d states x %d clock values x 2 levels)"
          % (rep["checked"], rep["states"], rep["clock_values"]))
    print("  deterministic (no state >=2 enabled): %s  violations %d"
          % (rep["deterministic"], len(rep["nondeterministic"])))
    print("  TOTAL         (no state  0 enabled): %s  violations %d"
          % (rep["total"], len(rep["incomplete"])))
    print("  ⛔ totality is the dangerous half: a state with no enabled transition")
    print("     DROPS the behaviour, never reaches BAD, and reads as CONFORMING.")
    if not (rep["deterministic"] and rep["total"]):
        failures.append("gate1")

    # ---------------------------------------------------- GATE 0 + 2, good cases
    banner("GATE 0 + GATE 2 -- good programs conform, and sigrok agrees")
    print("  %-8s %-14s %-7s %-8s %-8s %s"
          % ("byte", "bit-order", "ours", "sigrok", "decoded", "agree"))
    good_rows = []
    for b in (0x55, 0x0F, 0x01, 0x00, 0xFF, 0xA5):
        r = run_case("%02X" % b, UartExecutor(b, T), b, rx)
        good_rows.append(r)
        sens = "sensitive" if rev8(b) != b else "PALINDROME"
        print("  0x%02X     %-14s %-7s %-8s %-8s %s"
              % (b, sens, "CONF" if r["ours"] else "VIOL",
                 "CONF" if r["theirs"] else "VIOL",
                 ("0x%02X" % r["decoded"]) if r["decoded"] is not None else "-",
                 "OK" if r["agree"] else "*** DISAGREE ***"))
        if not (r["ours"] and r["agree"]):
            failures.append("good 0x%02X" % b)
    ns = sum(1 for b in (0x55, 0x0F, 0x01, 0x00, 0xFF, 0xA5) if rev8(b) != b)
    print("  ⛔ %d of 6 bytes are bit-order SENSITIVE -- a palindrome cannot catch"
          % ns)
    print("     an LSB/MSB swap, and 0x00/0xFF/0xA5 are all palindromes.")

    # ----------------------------------------------------------------- ARMS
    banner("MUST-FIRE / MUST-NOT-FIRE ARM  (byte 0x55)")
    B = 0x55
    arms = [
        ("M0 +2% baud",    UartExecutor(B, round(T / 1.02)), B, True,
         "9.5*0.02 = 0.19 bit < 0.5 -> MUST STILL CONFORM (false-fail guard)"),
        ("M1 +10% baud",   UartExecutor(B, 478),             B, False,
         "9.5*0.10 = 0.95 bit > 0.5 -> must fail, by DRIFT"),
        ("M2 stop low",    UartExecutor(B, T, stop_level=0), B, False,
         "stop sample not high -> framing conjunct"),
        ("M3 inverted",    UartExecutor(B, T, invert=True),  B, False,
         "idle low / start high -> edge detection"),
        ("M4 7 data bits", UartExecutor(B, T, data_bits=7),  B, False,
         "stop sample misaligns"),
        # ⭐ M5 IS THE GAP THE ARM SET HAD: every other mutant dies on the FRAMING
        # conjunct, so the BYTE-COMPARISON conjunct was never exercised on its own.
        # One data bit flipped, framing perfect -> it can ONLY die by comparison.
        ("M5 bit3 flipped", UartExecutor(B ^ 0x08, T),       B, False,
         "framing PERFECT, one data bit wrong -> must die by COMPARISON conjunct"),
    ]
    print("  %-17s %-9s %-7s %-8s %-7s %s"
          % ("mutant", "expected", "ours", "sigrok", "agree", "died by"))
    for name, ex, expect_byte, should_conform, why in arms:
        r = run_case(name.split()[0], ex, expect_byte, rx)
        ok_dir = (r["ours"] == should_conform)
        reason = "-" if r["ours"] else r["ours_detail"].get("reason", "?")
        print("  %-17s %-9s %-7s %-8s %-7s %s"
              % (name, "CONFORM" if should_conform else "VIOLATE",
                 "CONF" if r["ours"] else "VIOL",
                 "CONF" if r["theirs"] else "VIOL",
                 "OK" if r["agree"] else "*DIS*", reason))
        print("        %s" % why)
        if not ok_dir:
            print("        <<< WRONG DIRECTION")
            failures.append(name + " direction")
        if not r["agree"]:
            failures.append(name + " disagreement")

    # ------------------------------------------------- M1 MECHANISM ASSERTION
    banner("M1 MECHANISM -- it must die BECAUSE of drift, not incidentally")
    fw = first_wrong_data_bit(T, 478)
    print("  monitor samples Dk at %d + %d*(k+1); executor holds Dk over [478(k+1), 478(k+2))"
          % (T // 2, T))
    print("  first data bit sampled from the WRONG executor bit: D%s" % fw)
    print("  predicted by 44*(k+1) > %d  =>  k+1 > %.2f  =>  first wrong at D4"
          % (T // 2, (T // 2) / 44))
    if fw != 4:
        print("  *** MECHANISM MISMATCH -- M1 is not dying by drift ***")
        failures.append("M1 mechanism")
    else:
        print("  ✅ mechanism confirmed: drift corrupts data from D4 onward.")
    print()
    print("  ⛔ BUT NOTE WHERE IT IS DETECTED. A wrong data bit is silently")
    print("     RECORDED -- nothing checks it until the byte comparison -- so the")
    print("     framing error at the stop sample reaches BAD first. M1 therefore")
    print("     exercises the FRAMING conjunct, not the DATA conjunct. That gap is")
    print("     exactly why M5 exists.")

    # ------------------------------------------------------- GATE 4, scaling
    banner("GATE 4 -- scaling, not termination (one data point is the trap)")
    print("  %-10s %-8s %-14s %-12s %s"
          % ("baud", "T(cyc)", "product steps", "wall (ms)", "verdict"))
    for baud in (9600, 115200, 1_000_000):
        t = bit_period(baud)
        r2 = UartReceiver(t)
        ex = UartExecutor(0x55, t)
        t0 = time.perf_counter()
        res = conformance(ex, r2, 0x55)
        ms = (time.perf_counter() - t0) * 1000
        print("  %-10d %-8d %-14d %-12.1f %s"
              % (baud, t, res["explored"], ms,
                 "CONFORMS" if res["conforms"] else "VIOLATES"))
    print("  growth is LINEAR in T -- finite-state enumeration, one frame.")
    print("  ⛔ THE FRAME-COUNT AXIS IS NOT RUN HERE, AND THAT IS DELIBERATE: a")
    print("     second frame needs the monitor to return DONE -> IDLE, i.e. to LOOP.")
    print("     Looping is precisely what forces the clock to RESET and what makes")
    print("     finite-state enumeration blow up -- so it belongs to TA-01b, where")
    print("     the zone-based formulation earns its keep rather than decorating.")

    banner("TA-01 VERDICT")
    if failures:
        print("  ⛔ NOT GREEN -- %d failing item(s): %s" % (len(failures), failures))
        return 1
    print("  ✅ GREEN. UART conformance is a decidable, non-vacuous query:")
    print("     - gate 0: an INDEPENDENT decoder reads our line and agrees on every")
    print("       waveform, good and mutant (the only foreign authority in the stack)")
    print("     - gate 1: monitor deterministic AND total")
    print("     - gate 2: correct programs conform, 3 of 6 bytes bit-order sensitive")
    print("     - arms:   M0 conforms (over-strictness guard); M1-M5 violate, each")
    print("               with agreement from the external decoder")
    print("     - M1 dies by its STATED mechanism (first wrong bit D4), verified")
    print("     - M5 closes the arm set's gap: the BYTE-COMPARISON conjunct is")
    print("       exercised on its own, framing intact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
