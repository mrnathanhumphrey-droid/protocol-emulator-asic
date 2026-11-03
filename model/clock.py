"""THE CLOCK -- the one place a clock frequency is read (Wilson 11-03).

⛔⛔ EVERY CONVERSION BETWEEN TIME AND CYCLES GOES THROUGH HERE. The chip moved
from 50 to 60 MHz and the RTL, five benches, the assembler's I2C mode floors
and every shipped program still assumed 20 ns a cycle: the SDA hold became
15 x 16.667 = 250 ns against a 300 ns minimum, and the 400 kHz I2C program
became 472 kHz. Each copy of "50 MHz" was correct where it was written and
wrong the day the clock moved. `model/gate_clock_literals.py` refuses a new
copy anywhere but here and the board configs.

⭐ RETARGETABLE, NOT RE-PINNED. Programs describe REAL TIME (rates, minimum
nanoseconds); a TARGET says what clock they run on, and the cycles are derived
for it. The chip and the FPGA board are both targets of one toolchain:

    chip   info.yaml          project.clock_hz   (Tiny Tapeout)
    fpga   fpga/board.yaml    clock_hz           (PA100T, MMCM output)

The target is `PE_TARGET` (default `chip`), or `at(hz)` for code that has to
hold two clocks in one process (the cross-clock gate).

⛔⛔ THE GUARD BAND (Wilson 11-03, addition 1). A minimum met exactly is met
with no margin for a fast clock source or a user who overclocks, so every
real-time MINIMUM is converted as ceil(min x BAND / period). The rule it
rests on: running SLOWER than the design clock is always safe for minima and
running faster is not, so sizing for the target plus the band keeps the
design correct at any slower clock -- a 60 MHz build on a 50 MHz board too.
Nominal values (a baud rate's bit period) are rounded, not banded: they are
targets, not floors.
"""

from __future__ import annotations

import contextlib
import os
import re
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

#: the guard band on every real-time minimum. ⚠ 1 (OFF) in the clock commit:
#: the source and every reader land first as a pure refactor, byte-identical at
#: 50 MHz; the band (21/20, +5 %) is switched on WITH the real-time programs
#: and the 60 MHz move, so every cycle-typed edge is re-derived once.
BAND = Fraction(1, 1)

#: target -> (file, the line that carries its clock in Hz). A board config is
#: the ONLY other place a frequency is written down.
TARGETS = {
    "chip": ("info.yaml", re.compile(r"^\s*clock_hz:\s*(\d+)", re.M)),
    "fpga": (os.path.join("fpga", "board.yaml"),
             re.compile(r"^\s*clock_hz:\s*(\d+)", re.M)),
}

_override: list = []


class ClockError(Exception):
    pass


def target():
    t = os.environ.get("PE_TARGET", "chip")
    if t not in TARGETS:
        raise ClockError("PE_TARGET=%r names no target (%s)"
                         % (t, ", ".join(sorted(TARGETS))))
    return t


def target_hz(name):
    """The clock a target's board config declares, in Hz. A missing or zero
    value is an error, never a default: a default IS the hard-coded copy."""
    rel, rx = TARGETS[name]
    path = os.path.join(ROOT, rel)
    try:
        with open(path, encoding="utf-8") as fh:
            m = rx.search(fh.read())
    except OSError as exc:
        raise ClockError("target %s: cannot read %s (%s)" % (name, rel, exc))
    if not m or int(m.group(1)) <= 0:
        raise ClockError("target %s: %s declares no positive clock_hz"
                         % (name, rel))
    return int(m.group(1))


def hz():
    """The clock in force: `at(hz)` if inside one, else the target's."""
    return _override[-1] if _override else target_hz(target())


@contextlib.contextmanager
def at(f):
    """Hold a clock for the duration -- for code that must compare two."""
    _override.append(int(f))
    try:
        yield
    finally:
        _override.pop()


def period_ps(f=None):
    """The period in WHOLE picoseconds, rounded DOWN. The RTL can only carry an
    integer; a shorter period derives MORE cycles for a minimum, which is the
    safe side (16666 at 60 MHz, never 16667)."""
    f = hz() if f is None else int(f)
    return 10 ** 12 // f


def cycles_min(ns, f=None, band=BAND):
    """Whole cycles that MEET a real-time minimum of `ns`, with the band:
    ceil(ns x band x f / 1e9). Rounding down would not meet it."""
    f = hz() if f is None else int(f)
    x = Fraction(ns) * band * f / 10 ** 9
    return -(-x.numerator // x.denominator)


def cycles_nominal(ns, f=None):
    """Nearest whole cycles to a NOMINAL duration (a target, not a floor)."""
    f = hz() if f is None else int(f)
    return round(Fraction(ns) * f / 10 ** 9)


def per_rate(rate_hz, f=None):
    """Nearest whole cycles per period of a nominal rate (a baud, a PWM)."""
    f = hz() if f is None else int(f)
    return round(Fraction(f, int(rate_hz)))


def ns(n_cycles, f=None):
    """Cycles -> ns at the clock in force."""
    f = hz() if f is None else int(f)
    return float(Fraction(int(n_cycles) * 10 ** 9, f))


def us(n_cycles, f=None):
    return ns(n_cycles, f) / 1000.0


def mhz(f=None):
    f = hz() if f is None else int(f)
    return f / 1e6


def rtl_hold_cycles(min_ns, ps, num=BAND.numerator, den=BAND.denominator):
    """The RTL's own integer formula, mirrored: ceil(min_ns x 1000 x num /
    (den x ps)). `gate_clock_consistency` holds the two to agree."""
    return (min_ns * 1000 * num + den * ps - 1) // (den * ps)


def main():
    for t in sorted(TARGETS):
        f = target_hz(t)
        print("  %-5s %s  %d Hz  period %d ps"
              % (t, TARGETS[t][0], f, period_ps(f)))
    print("  band  x%s on every real-time minimum" % BAND)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
