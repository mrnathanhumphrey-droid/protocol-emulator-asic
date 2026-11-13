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

#: the guard band on every real-time minimum: +5 % (21/20). It landed OFF in
#: clock commit (a), a pure refactor, and was switched on WITH the real-time
#: programs and the 60 MHz move, so every cycle-typed edge was re-derived once.
BAND = Fraction(21, 20)

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


#: ⛔⛔ THE A2 ANALYSIS LAYER IS A RECORD AT THIS TARGET (Wilson 11-03). The
#: shipped lane table (model/a2/bursty.py) and every analysis on it -- the
#: Imitator band, the TChecker / pyRTA / recurrence records, the measured
#: bands -- were derived at 50 MHz, the FPGA board's clock, where they stay
#: true. Until A2 is RE-CERTIFIED at the chip's clock (its own pre-registered
#: item), A2 code converts at THIS target, never the chip's; the chip's 60 MHz
#: is covered by the assembler's per-target checks and the cross-clock gate's
#: simulation, NOT by formal analysis.
A2_TARGET = "fpga"


def a2_hz():
    """The clock the A2 record was derived at (see A2_TARGET)."""
    return target_hz(A2_TARGET)


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


def phases(f=None):
    """Whole 1 ns phases in one period -- the bins a phase walk can cover:
    20 at 50 MHz, 17 at 60 (16.666 ns: bins 0..16)."""
    return -(-period_ps(f) // 1000)


def mhz(f=None):
    f = hz() if f is None else int(f)
    return f / 1e6


def rtl_hold_cycles(min_ns, ps, num=BAND.numerator, den=BAND.denominator):
    """The RTL's own integer formula, mirrored: ceil(min_ns x 1000 x num /
    (den x ps)). `gate_clock_consistency` holds the two to agree."""
    return (min_ns * 1000 * num + den * ps - 1) // (den * ps)


# ---------------------------------------------------------------------------
# ⭐ THE I2C CLOCK-STRETCH FAULT BOUND -- ONE SOURCE (Wilson 11-12). project.v
# derives CK_STRETCH_TO from these two numbers and CLK_PERIOD_PS; every Python
# reader imports them from here. `run_ckack` regexed a literal out of
# pe_engine.v, which became an expression at 18bb252 ("clock (a)") and crashed
# it silently for weeks; `gate_clock_consistency` had a second hand copy.
# The gate now holds the RTL's ELABORATED value to ck_stretch_to() per target.
# ---------------------------------------------------------------------------
#: SMBus t_TIMEOUT (35 ms): project.v CK_STRETCH_NS
CK_STRETCH_NS = 35_000_000
#: the shipped watchdog prescaler, cycles per tick: project.v CK_TICK_SHIPPED
CK_TICK_SHIPPED = 16384


def ck_stretch_to(f=None, ns=CK_STRETCH_NS, tick=CK_TICK_SHIPPED):
    """Ticks before a bus fault -- project.v's CK_STRETCH_TO, the same integer
    formula: ceil(ns / tick_ns) with tick_ns = floor(tick x period_ps / 1000)."""
    tick_ns = (tick * period_ps(f)) // 1000
    return (ns + tick_ns - 1) // tick_ns


def ck_stretch_cycles(f=None):
    """The stretch timeout in cycles: CK_STRETCH_PRE (= the shipped tick) x
    CK_STRETCH_TO."""
    return CK_TICK_SHIPPED * ck_stretch_to(f)


# ---------------------------------------------------------------------------
# ⭐ USB LOW SPEED (step 7a §1 / §5, Wilson 11-09 Q1 + Q7). Every figure is the
# USB 2.0 spec's (usb.org usb_20_20240604, usb_20.pdf), cited where it is used.
# The copy cited: D:\ProtocolEmulator_internal\refs\usb_20.pdf (internal, not
# in this repo), SHA-256
# d39698a33486c399124af92bd02e4f978fd9a836b5cf4e52e6e4633eb1d89f61 (Wilson 11-13).
# ---------------------------------------------------------------------------
#: the bus-reset threshold the RTL derives N_RST from (pe_engine.v T_RST_NS)
USB_T_RST_NS = 4000
#: TDETRST, Table 7-14 / §7.1.7.5: a device MAY treat SE0 > 2.5 us as reset and
#: must have detected one within 10 ms (TDRST: the hub drives >= 10 ms)
USB_TDETRST_MIN_NS, USB_TDRST_MIN_NS = 2500, 10_000_000
#: TLEOPT, Table 7-10: the longest legal low-speed EOP SE0 a source sends
USB_TLEOPT_MAX_NS = 1500
#: the LS bit (TLDRATE nominal 1.5 Mb/s, Table 7-10) and the source jitter
#: TUDJ1 / TUDJ2 (Table 7-10, "including frequency tolerance") over the
#: longest runs the Table 7-5 budget charges them to (7 and 14 bits)
USB_LS_RATE = 1_500_000
USB_TUDJ1_NS, USB_TUDJ2_NS = 95, 150
#: the engine's dispatch jitter on a device edge (measured, bundle 5): J <= 2
USB_J_CYCLES = 2
#: TIPD, §7.1.18.1 (PDF page 196, printed p. 168): "The host must provide at
#: least two bit times of J after the SE0 of an EOP and the start of a new
#: packet (TIPD)." In LS bit times (USB_LS_RATE); convert with usb_bit_cycles().
#: (The device's own rule, just above it: at least two bit times too; its
#: response delay max is TRSPIPD1 = 6.5 bit times, detachable cable.)
USB_TIPD_BITS = 2

#: ⭐ THE CLOCK SOURCE'S ACCURACY, DECLARED PER TARGET (Wilson 11-09 Q7): the
#: rate requirement is TWO-SIDED, which BAND (a one-sided guard on minima)
#: never expressed. ⛔ BOTH VALUES ARE PROVISIONAL and each is a LOCK ITEM in
#: V2_MASTER_LIST: the TT demo board's project clock comes from its RP2040
#: (whether it lands on exactly 60.000 MHz, and to what ppm, comes from the TT
#: board docs); the PA100T's from its board oscillator's datasheet.
SOURCE_PPM = {"chip": 100, "fpga": 100}


def usb_n_rst(f=None, t_rst_ns=USB_T_RST_NS):
    """The RTL's N_RST at clock `f`: its own banded integer formula."""
    f = hz() if f is None else int(f)
    return rtl_hold_cycles(t_rst_ns, period_ps(f))


def usb_bit_cycles(f=None):
    """Whole cycles per LS bit: the device's TX bit (nominal, rounded)."""
    return per_rate(USB_LS_RATE, f)


def usb_quant_err(f=None):
    """|rate error| from the whole-cycle bit alone: |C x 1.5 MHz / f - 1|."""
    f = hz() if f is None else int(f)
    return abs(Fraction(usb_bit_cycles(f) * USB_LS_RATE, f) - 1)


def usb_ls_tol(f=None):
    """USB_LS_TOL: the TOTAL rate error a device may have at clock `f` and
    still meet TUDJ1/TUDJ2 with its dispatch jitter J x T charged as the
    driver term (Table 7-5's split; §7.1.11 lets driver jitter be traded
    against clock accuracy): min((95 - JT) / (7 Tb), (150 - JT) / (14 Tb))."""
    f = hz() if f is None else int(f)
    tb = Fraction(10 ** 9, USB_LS_RATE)
    jt = Fraction(USB_J_CYCLES * 10 ** 9, f)
    return min((USB_TUDJ1_NS - jt) / (7 * tb), (USB_TUDJ2_NS - jt) / (14 * tb))


def usb_osc_allowed(f=None):
    """What the clock SOURCE may be off by: USB_LS_TOL minus quantisation."""
    return usb_ls_tol(f) - usb_quant_err(f)


# ---------------------------------------------------------------------------
# ⭐ THE HOST'S PUSH TIMING (Wilson 11-10, CDC bundle). Every push holds the
# nibble / tag pins (ui_in[4:0]) from FW_SETUP_CYCLES before `wr` rises until
# FW_HOLD_CYCLES after it, in CHIP cycles. Derived from the RTL by
# gate_clock_consistency check 9 (`wr` passes WR_SYNC_FLOPS flops; the data is
# captured on edge WR_SYNC_FLOPS after the pad edge, or one later if the first
# flop resolves late): hold = that late edge + 1 cycle of margin (capture-flop
# hold, nibble-to-WR pin skew -- TT's FAQ puts the I/O round trip near 10 ns).
# Setup: the earliest capture is >= 2 cycles after the pad edge, so a nibble
# stable when `wr` rises is already safe; the 1 cycle is skew margin, the same
# margin the hold carries.
# ---------------------------------------------------------------------------
FW_HOLD_CYCLES = 5
FW_SETUP_CYCLES = 1


def slow_edge_hz(f=None):
    """The slowest clock the band covers: f / BAND (57.142857 MHz at 60)."""
    f = hz() if f is None else int(f)
    return Fraction(f) / BAND


def fw_ns(cycles, f=None):
    """A host-side time for `cycles` chip cycles, at the SLOW edge of the band
    (Wilson 11-10): the firmware must cover the longest cycle it may meet."""
    return Fraction(cycles * 10 ** 9) / slow_edge_hz(f)


def main():
    for t in sorted(TARGETS):
        f = target_hz(t)
        print("  %-5s %s  %d Hz  period %d ps"
              % (t, TARGETS[t][0], f, period_ps(f)))
    print("  band  x%s on every real-time minimum" % BAND)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
