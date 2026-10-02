"""B5 -- THE GENERIC MACHINE REPRODUCES TA-01 EXACTLY.

⛔⛔ THE CLAIM IS BYTE IDENTITY OF THE EMITTED WAVEFORM, NOT BISIMULATION. A
bisimulation claim between a table interpreter and a bespoke FSM is either trivial
(they produce the same trace) or unprovable at this layer (their state spaces are
different shapes by construction, which is the whole point of the interpreter).
Byte identity is what can actually be checked, and it is checked with `cmp` --
a foreign byte comparator, not our own equality operator.

Three things must agree, and all three are needed:
  1. the WAVEFORM is byte-identical (`cmp`), over every idle phase
  2. the VERDICT is identical, from the UNCHANGED TA-01 monitor and the
     UNCHANGED `conformance` driver -- same monitor, same driver, two executors
  3. the TOLERANCE BAND is identical, measured by sweeping Te on both

⭐ (3) IS THE ONE THAT COULD GO WRONG QUIETLY. Identical waveforms at the nominal
period do not imply identical waveforms off-nominal: a rounding difference in how
each side computes bit boundaries shows up only under drift, and it would move the
band by a cycle at exactly the edge TA-01c synthesized. Measuring the band on both
columns is the only way that failure is visible.
"""

from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "ta01"))

from interp import Interp, table_uart_tx                       # the generic machine
from uart_ta import (BAUD_DEFAULT, F_CLK, UartExecutor,         # the bespoke one
                     UartReceiver, bit_period, conformance)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


class TableUartExecutor:
    """Adapter: presents the GENERIC interpreter through TA-01's executor
    interface, so the unchanged monitor and the unchanged `conformance` driver
    can judge it without knowing which executor it is holding."""

    def __init__(self, byte: int, t_bit: int, pin: int = 0):
        self.byte, self.t_bit, self.pin = byte, t_bit, pin

    def levels(self, idle_cycles: int) -> list:
        # the bespoke executor emits: idle, start, 8 data, stop, then 2*t_bit idle
        tbl = table_uart_tx([self.byte], self.t_bit, idle_cycles, pin=self.pin,
                            loop=False, tail=2 * self.t_bit)
        n = idle_cycles + 12 * self.t_bit
        return Interp(tbl).run(n, pin=self.pin)


def dump(levels, path: str) -> int:
    """⛔ TEMP FILE, VERIFY, REPLACE -- `open(p,"wb")` truncates before the write
    can fail, and a short file compares as a different waveform."""
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(bytes(v & 1 for v in levels))
    assert os.path.getsize(tmp) == len(levels)
    os.replace(tmp, path)
    return len(levels)


def cmp_files(a: str, b: str) -> dict:
    """`cmp` -- a FOREIGN byte comparator. Our own `==` is the thing under test."""
    r = subprocess.run(["wsl.exe", "-d", "Ubuntu", "--", "cmp", "-l",
                        _wsl(a), _wsl(b)], capture_output=True, text=True)
    diffs = [l for l in (r.stdout or "").splitlines() if l.strip()]
    return {"rc": r.returncode, "n_diff": len(diffs), "first": diffs[:3],
            "stderr": (r.stderr or "").strip()[:200]}


def _wsl(p: str) -> str:
    p = os.path.abspath(p).replace("\\", "/")
    return ("/mnt/" + p[0].lower() + p[2:]) if len(p) > 1 and p[1] == ":" else p


def band(make_exec, rx: UartReceiver, byte: int, t_nom: int) -> tuple:
    """Sweep the executor's actual bit period and return the conforming window.
    ⭐ Swept on BOTH columns, because off-nominal is where a rounding difference
    between the two executors would first appear."""
    lo = hi = None
    for te in range(int(t_nom * 0.80), int(t_nom * 1.20) + 1):
        ok = conformance(make_exec(byte, te), rx, byte)["conforms"]
        if ok:
            lo = te if lo is None else lo
            hi = te
    return (lo, hi)


def main() -> int:
    T = bit_period()
    rx = UartReceiver(T)
    print("=== TA-02 / B5 -- the GENERIC machine reproduces TA-01 exactly ===")
    print("    T = %d cycles/bit @ %d Hz, baud %d" % (T, F_CLK, BAUD_DEFAULT))
    print("    bespoke: ta01/uart_ta.py::UartExecutor   generic: ta02/interp.py")
    print()

    bytes_ = [0x55, 0x0F, 0x01, 0x00, 0xFF, 0xA5]
    idles = [0, 1, 2, 3]
    print("  1. byte-identical waveform, via `cmp` (foreign comparator)")
    print("     %-6s %-6s %-9s %-9s %s" % ("byte", "idle", "len", "cmp", "diffs"))
    ident_ok, verdict_ok = True, True
    for b in bytes_:
        for idle in idles:
            wa = UartExecutor(b, T).levels(idle)
            wb = TableUartExecutor(b, T).levels(idle)
            pa = os.path.join(HERE, "id_bespoke.bin")
            pb = os.path.join(HERE, "id_generic.bin")
            dump(wa, pa)
            dump(wb, pb)
            c = cmp_files(pa, pb)
            same = (c["rc"] == 0 and c["n_diff"] == 0 and len(wa) == len(wb))
            ident_ok = ident_ok and same
            if not same or (b == 0x55 and idle == 0):
                print("     0x%02X   %-6d %-9s %-9s %s"
                      % (b, idle, "%d/%d" % (len(wa), len(wb)),
                         "IDENTICAL" if same else "*** DIFFERS ***", c["first"]))
    print("     all %d (byte, idle) pairs byte-identical: %s"
          % (len(bytes_) * len(idles), ident_ok))
    print()

    print("  2. identical verdicts from the UNCHANGED TA-01 monitor + driver")
    print("     %-6s %-12s %-12s %s" % ("byte", "bespoke", "generic", "agree"))
    for b in bytes_:
        va = conformance(UartExecutor(b, T), rx, b)
        vb = conformance(TableUartExecutor(b, T), rx, b)
        ag = va["conforms"] == vb["conforms"]
        verdict_ok = verdict_ok and ag and va["conforms"]
        print("     0x%02X   %-12s %-12s %s"
              % (b, "CONF" if va["conforms"] else "VIOL",
                 "CONF" if vb["conforms"] else "VIOL", "OK" if ag else "*** NO ***"))
    print()

    print("  3. identical tolerance band, swept on BOTH columns")
    ba = band(lambda b, te: UartExecutor(b, te), rx, 0x55, T)
    bb = band(lambda b, te: TableUartExecutor(b, te), rx, 0x55, T)
    print("     bespoke  conforming Te in [%s, %s]" % ba)
    print("     generic  conforming Te in [%s, %s]" % bb)
    band_ok = (ba == bb and ba[0] is not None)
    print("     bands identical: %s" % band_ok)
    if band_ok:
        eps_lo = ba[0] / T - 1.0
        eps_hi = ba[1] / T - 1.0
        print("     => eps in [%+.4f%%, %+.4f%%] at T=%d; TA-01c synthesized"
              % (eps_lo * 100, eps_hi * 100, T))
        print("        -1/20 < eps < 1/18 = [-5.0000%, +5.5556%] -- the integer")
        print("        sweep is the discrete shadow of that continuous band, so it")
        print("        lands inside it and cannot be expected to equal it.")
    print()

    ok = ident_ok and verdict_ok and band_ok
    print("  B5: %s" %
          ("PASSED -- the generic table interpreter emits the SAME BYTES as the "
           "bespoke TA-01 executor, earns the same verdict from the same monitor, "
           "and has the same tolerance band. TA-01's results transfer."
           if ok else
           "FAILED -- the generic machine is not a reproduction of TA-01, so "
           "TA-01's conformance results do NOT transfer to it."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
