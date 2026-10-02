"""THE INPUT-BRANCH EXERCISER AND THE DESCRIPTOR-COVERAGE MATRIX.

⛔⛔ WHY THE INPUT GUARD SURVIVED THE MINIMAL DESCRIPTOR. A machine that can only
drive and never sample is a waveform player, not an emulator, and reading a bus is
the stated use case. But every descriptor field is a silicon commitment, so a kept
field has to be EXERCISED BEFORE THE FREEZE -- an unexercised field is silicon
nobody has ever run.

⛔ AND "EXERCISED" IS NOT "PRESENT IN A TABLE". The first honest definition is the
only one worth having: PERTURB THE FIELD AND SEE WHETHER THE RUN CHANGES. A field
whose every single-entry mutation leaves the waveform and the path byte-identical
did not participate in anything, however many tables mention it. That is the
difference between a coverage matrix and a coverage claim.

⭐ THE BRANCH IS A REAL CONTROL DIVERGENCE, NOT A STALL. A wait-for-high entry
would technically read the pin while leaving the automaton a straight-line timed
sequence. `table_input_branch` takes DIFFERENT SUCCESSORS with DIFFERENT OUTPUTS,
which is the shape SPI-read and I2C-ACK will need, and the shape that makes
`next_b` and `in_pol` mean something.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from interp import (Entry, Interp, table_input_branch, table_spi_write,
                    table_uart_tx)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

IN_PIN, OUT_PIN, HOLD = 3, 0, 4


def trace_run(table, n, in_trace=None):
    """The observable: the pin waveform AND the path taken. Both, because a
    different path that happens to emit the same levels is still a different
    machine, and a same path emitting different levels is too."""
    m = Interp(table)
    st, wave, path = m.initial(), [], []
    for c in range(n):
        wave.append(m.output(st))
        path.append(st[0])
        st = m.step(st, 0 if in_trace is None else in_trace[c])
    return (tuple(wave), tuple(path))


# ---------------------------------------------------------------------------
# 1. THE DIVERGENCE TEST
# ---------------------------------------------------------------------------
def divergence() -> dict:
    t = table_input_branch(HOLD, in_pin=IN_PIN, out_pin=OUT_PIN)
    n = HOLD * 12
    hi, lo = (1 << IN_PIN), 0
    tr_hi = [hi] * n                                  # pin held 1
    tr_lo = [lo] * n                                  # pin held 0
    # ⭐ alternating: the machine must take BOTH arms within ONE run, which is
    # what proves the guard is evaluated at every visit rather than latched once.
    tr_alt = [hi if (c // (HOLD * 3)) % 2 == 0 else lo for c in range(n)]

    w_hi, p_hi = trace_run(t, n, tr_hi)
    w_lo, p_lo = trace_run(t, n, tr_lo)
    w_al, p_al = trace_run(t, n, tr_alt)

    # the two arms are states 2 (saw 1 -> drive high) and 3 (saw 0 -> drive low)
    return {
        "wave_differs": w_hi != w_lo,
        "path_differs": p_hi != p_lo,
        "hi_visits": sorted(set(p_hi)),
        "lo_visits": sorted(set(p_lo)),
        "alt_visits": sorted(set(p_al)),
        "alt_takes_both": {2, 3} <= set(p_al),
        "hi_drove_high": any((v >> OUT_PIN) & 1 for v in w_hi),
        "lo_drove_high": any((v >> OUT_PIN) & 1 for v in w_lo),
    }


def polarity_swap() -> dict:
    """⭐ EXERCISES `in_pol` SPECIFICALLY. Flipping only the polarity field must
    swap which arm a given input selects -- otherwise `in_pin` is doing all the
    work and `in_pol` is a field that exists but decides nothing."""
    t1 = table_input_branch(HOLD, in_pin=IN_PIN, out_pin=OUT_PIN)
    t0 = [e._replace(in_pol=1 - e.in_pol) if e.in_pin >= 0 else e for e in t1]
    n = HOLD * 12
    hi = [(1 << IN_PIN)] * n
    w1, p1 = trace_run(t1, n, hi)
    w0, p0 = trace_run(t0, n, hi)
    return {"swapped": (w1 != w0) and (p1 != p0),
            "pol1_visits": sorted(set(p1)), "pol0_visits": sorted(set(p0))}


def guard_ignored_mutant() -> dict:
    """THE MUST-FIRE ARM FOR THE WHOLE TEST. A machine that ignores the input
    guard must make the two traces IDENTICAL -- if they still differ, the
    divergence above was measuring something other than the guard."""
    class Blind(Interp):
        def step(self, st, in_bits=0):
            pc, x = st
            e = self.table[pc]
            if x + 1 < e.g:
                return (pc, x + 1)
            return (e.next_a, 0)                      # guard deleted

    t = table_input_branch(HOLD, in_pin=IN_PIN, out_pin=OUT_PIN)
    n = HOLD * 12
    outs = []
    for tr in ([(1 << IN_PIN)] * n, [0] * n):
        m, st, w = Blind(t), Interp(t).initial(), []
        for c in range(n):
            w.append(m.output(st))
            st = m.step(st, tr[c])
        outs.append(tuple(w))
    return {"blind_identical": outs[0] == outs[1]}


# ---------------------------------------------------------------------------
# 2. THE COVERAGE MATRIX, BY PERTURBATION
# ---------------------------------------------------------------------------
def _perturb(e: Entry, field: str, n: int) -> Entry:
    if field == "g":
        return e._replace(g=e.g + 1)
    if field == "out":
        return e._replace(out=e.out ^ 1)
    if field == "in_pin":
        return e._replace(in_pin=(-1 if e.in_pin >= 0 else IN_PIN))
    if field == "in_pol":
        return e._replace(in_pol=1 - e.in_pol)
    if field == "next_a":
        return e._replace(next_a=(e.next_a + 1) % n)
    if field == "next_b":
        return e._replace(next_b=(e.next_b + 1) % n)
    raise KeyError(field)


def field_exercised(table, field: str, n_cycles: int, in_trace=None) -> bool:
    """True iff SOME single-entry mutation of `field` changes the observable run."""
    base = trace_run(table, n_cycles, in_trace)
    for i in range(len(table)):
        mut = list(table)
        mut[i] = _perturb(mut[i], field, len(table))
        try:
            if trace_run(mut, n_cycles, in_trace) != base:
                return True
        except (IndexError, RecursionError):
            return True          # it changed the run -- into a broken one
    return False


def main() -> int:
    print("=== TA-02 -- INPUT-BRANCH EXERCISER + DESCRIPTOR COVERAGE ===")
    print()

    d = divergence()
    print("  1. control divergence on a sampled input")
    print("     pin held 1 -> path states %s, drove high: %s"
          % (d["hi_visits"], d["hi_drove_high"]))
    print("     pin held 0 -> path states %s, drove high: %s"
          % (d["lo_visits"], d["lo_drove_high"]))
    print("     waveforms differ: %s     paths differ: %s"
          % (d["wave_differs"], d["path_differs"]))
    print("     alternating input visits %s -- takes BOTH arms in one run: %s"
          % (d["alt_visits"], d["alt_takes_both"]))
    p = polarity_swap()
    print("     `in_pol` flipped alone swaps the arm: %s  (%s -> %s)"
          % (p["swapped"], p["pol1_visits"], p["pol0_visits"]))
    b = guard_ignored_mutant()
    print("     MUST-FIRE: a guard-blind machine makes the two traces identical: %s"
          % b["blind_identical"])
    div_ok = (d["wave_differs"] and d["path_differs"] and d["alt_takes_both"]
              and d["hi_drove_high"] and not d["lo_drove_high"]
              and p["swapped"] and b["blind_identical"])
    print("     => %s" % ("the input guard is a REAL branch, and the test can fail"
                          if div_ok else "*** NOT ESTABLISHED ***"))
    print()

    tables = [
        ("uart_tx",      table_uart_tx([0x55, 0x0F, 0x01], 8, 16), 8 * 40, None),
        ("spi_write",    table_spi_write([0xDE, 0xAD], 8), 8 * 48, None),
        ("input_branch", table_input_branch(HOLD, IN_PIN, OUT_PIN), HOLD * 12,
         [(1 << IN_PIN) if (c // (HOLD * 3)) % 2 == 0 else 0
          for c in range(HOLD * 12)]),
    ]
    fields = list(Entry._fields)
    print("  2. descriptor coverage -- a field counts as EXERCISED only if some")
    print("     single-entry mutation of it CHANGES the run. Presence is not use.")
    print()
    print("     %-14s %s" % ("table", "  ".join("%-7s" % f for f in fields)))
    cov = {f: False for f in fields}
    for name, tbl, n, tr in tables:
        marks = []
        for f in fields:
            hit = field_exercised(tbl, f, n, tr)
            cov[f] = cov[f] or hit
            marks.append("%-7s" % ("yes" if hit else "-"))
        print("     %-14s %s   (%d entries)" % (name, "  ".join(marks), len(tbl)))
    print()
    unexercised = [f for f in fields if not cov[f]]
    print("     fields exercised by at least one table: %d of %d"
          % (len(fields) - len(unexercised), len(fields)))
    print("     UNEXERCISED (= silicon nobody has run): %s"
          % (unexercised if unexercised else "none"))
    print()

    # ⭐ THE TABLE-SIZE BUDGET, PRE-REGISTERED. Going over it is a real
    # falsifier -- the format is too verbose to be worth putting in silicon.
    uart = table_uart_tx([0x55, 0x0F, 0x01], 8, 16)
    budget = 64
    print("  3. pre-registered table-size budget for UART: %d entries" % budget)
    print("     3-byte periodic UART stream: %d entries -- %s"
          % (len(uart), "within budget" if len(uart) <= budget else
             "*** OVER: format-too-verbose falsifier FIRES ***"))
    print("     (one entry per bit: 1 idle + 3 x (start + 8 data + stop) = %d)"
          % len(uart))
    size_ok = len(uart) <= budget
    print()

    ok = div_ok and not unexercised and size_ok
    print("  VERDICT: %s" %
          ("PASSED -- every field of the frozen descriptor changes some run, the "
           "input guard is a genuine branch, and UART fits the budget."
           if ok else "FAILED -- see above."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
