"""TA-01b runner -- WRITTEN AFTER THE FACT, because it never existed.

⛔⛔ `docs/TA01bc_RESULTS.md` opens with "Re-run: `python model/ta01b/run_ta01b.py`
(fixpoint)". That file has never been in the repository -- `git log --all` has no
record of it. The documented TA-01b numbers (13,023 states, 34,086 combinations,
the T-axis table, the rejection arms) were produced by ad-hoc invocation and were
NOT re-runnable as documented. A result you cannot re-run is a result you cannot
re-derive, which is exactly what the receiver fix now demands.

⛔ AND EVERY NUMBER BELOW IS RE-DERIVED, NOT RE-WORDED. `StreamReceiver` carried
the same +1-cycle-per-bit defect as TA-01's `UartReceiver`, so the state counts and
the "30 states per clock tick" law were both computed under it. The reset
diagnostic TA-01b reported --

    "max clock == T, not < T; the clock reaches T at the sample then resets.
     Off-by-one in the spec's phrasing, not a failure."

-- WAS THE DEFECT ANNOUNCING ITSELF, and it was explained away. It is also
load-bearing for the BFS-termination argument, i.e. a guard that passed BECAUSE of
the thing it was screening for. Under the fix the max reachable clock must now be
`T - 1`, because the counter runs 0..T-1. That change is the receipt for the fix.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from uart_stream import (BAD_STATES, M_BAD_DATA, M_BAD_FRAME, STREAM_DEFAULT,
                         StreamExecutor, StreamReceiver, bit_period,
                         determinism_totality, fixpoint)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def banner(s: str) -> None:
    print()
    print("=" * 74)
    print(s)
    print("=" * 74)


def main() -> int:
    T = bit_period()
    failures = []

    banner("GATE 1 -- determinism AND totality over the FULL cross-product")
    rx = StreamReceiver(STREAM_DEFAULT, T)
    print("  thresholds: s_start=%d s_bit=%d  (t=%d, half=%d)"
          % (rx.s_start, rx.s_bit, rx.t, rx.half))
    rep = determinism_totality(rx)
    print("  %d combinations checked (%d states x %d clocks x %d positions x 2)"
          % (rep["checked"], rep["states"], rep["clock_values"], rep["positions"]))
    print("  deterministic: %s     total: %s"
          % (rep["deterministic"], rep["total"]))
    if not (rep["deterministic"] and rep["total"]):
        failures.append("determinism/totality")
    print("  ⛔ `pos` is in the cross-product on purpose: the periodic expected")
    print("     stream added a counter, and forgetting it reopens the totality")
    print("     hole on a fresh axis.")

    banner("GATE 2 -- the fixpoint CLOSES, and the reset diagnostics")
    ex = StreamExecutor(STREAM_DEFAULT, T)
    fp = fixpoint(ex, rx)
    print("  closed: %s     states: %d     BFS steps: %d"
          % (fp["closed"], fp["states"], fp.get("steps", -1)))
    print("  BAD reachable: %s     reasons: %s"
          % (fp["bad_reachable"], fp["reasons"] or "none"))
    print("  max reachable clock: %d" % fp["max_clock"])
    print()
    print("  ⛔⛔ THE RE-DERIVED RESET DIAGNOSTIC. TA-01b reported max clock == T")
    print("     (%d) and called the discrepancy 'the spec's phrasing'. Under the" % T)
    print("     fixed threshold the counter runs 0..T-1, so the max reachable")
    print("     clock must be T-1 = %d. Measured: %d -- %s"
          % (T - 1, fp["max_clock"],
             "CONSISTENT with the fix" if fp["max_clock"] == T - 1
             else "*** NOT T-1: the fix did not reach this receiver ***"))
    if not fp["closed"]:
        failures.append("fixpoint did not close")
    if fp["bad_reachable"]:
        failures.append("BAD reachable on the nominal stream")
    if fp["max_clock"] != T - 1:
        failures.append("max clock is %d, expected T-1 = %d"
                        % (fp["max_clock"], T - 1))
    print("  ⭐ A CLOSED set with BAD outside it is a safety proof over EVERY run,")
    print("     including the infinite one. BFS terminating at all is the other")
    print("     half of the reset diagnostic: a non-resetting clock makes the")
    print("     state space unbounded and this would simply not return.")

    banner("GATE 3 -- both conjuncts load-bearing, each dying by its OWN reason")
    print("  ⛔ 'reaches BAD' is a colour, not a reason. BAD is split by conjunct")
    print("     so a framing arm cannot be credited to the data comparison.")
    print()
    print("  %-34s %-14s %s" % ("arm", "dies by", "ok"))
    arms = [
        ("R1 stop bit dropped @pos1",
         dict(bad_frame=1, bad_kind="stoplow"), M_BAD_FRAME),
        ("R3 data bit flipped @pos1",
         dict(bad_frame=1, bad_kind="databit"), M_BAD_DATA),
    ]
    for label, kw, want in arms:
        try:
            exm = StreamExecutor(STREAM_DEFAULT, T, **kw)
        except TypeError as e:
            print("  %-34s %-14s *** arm not expressible: %s"
                  % (label, "-", e))
            failures.append("%s not expressible" % label)
            continue
        r = fixpoint(exm, rx)
        got = r["reasons"]
        ok = (got == [want])
        print("  %-34s %-14s %s"
              % (label, ",".join(got) or "none",
                 "OK" if ok else "*** want exactly [%s] ***" % want))
        if not ok:
            failures.append("%s died by %s" % (label, got))

    banner("GATE 4 -- the T-axis: is the state count a LAW or a coincidence?")
    print("  ⛔ RE-DERIVED under the fix. The published law was '30 states per")
    print("     clock tick', fitted to counts computed with the +1 defect.")
    print()
    print("  %-8s %-9s %-14s %s" % ("baud", "T", "states", "states/T"))
    rows = []
    for baud in (115200, 57600, 38400, 19200):
        t = bit_period(baud)
        r = fixpoint(StreamExecutor(STREAM_DEFAULT, t), StreamReceiver(STREAM_DEFAULT, t))
        rows.append((baud, t, r["states"]))
        print("  %-8d %-9d %-14d %.4f" % (baud, t, r["states"], r["states"] / t))
    if len(rows) >= 2:
        d = [(rows[i + 1][2] - rows[i][2]) / float(rows[i + 1][1] - rows[i][1])
             for i in range(len(rows) - 1)]
        print()
        print("  slope between consecutive points: %s"
              % ", ".join("%.4f" % v for v in d))
        print("  ⭐ A constant slope is the law; the INTERCEPT is what the old")
        print("     'states/T' ratio hid. Report the slope, not the ratio.")

    banner("SUMMARY")
    if failures:
        print("  *** %d FAILURE(S):" % len(failures))
        for f in failures:
            print("      - %s" % f)
    else:
        print("  all gates green, every number re-derived under the fixed receiver")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
