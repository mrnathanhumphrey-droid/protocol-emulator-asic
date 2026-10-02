"""TA-02 -- the generic table-driven executor.

⛔⛔ THE WHOLE CLAIM IS THAT THIS FILE CONTAINS NO PROTOCOL. State is
(pc, clock); the output is a pure function of pc; the step function reads the
CURRENT TABLE ENTRY and nothing else. You get UART by loading the UART table.

⛔ AND THE GENERICITY TEST IS BEHAVIOURAL, NOT LEXICAL. "The diff across loads is
empty" is just not-editing-a-file and proves nothing; a scan for the literal 434
passes a UART-shaped machine with the constant renamed. The tests that can
actually fail are: (1) a BRANCH-POINT AUDIT -- every branch depends only on the
current entry -- and (2) a second protocol coming off the unchanged machine and
being read by a foreign decoder.

⛔ THIS IS A MODEL OF AN INTERPRETER, AND THAT MATTERS. TA-02 freezes the
semantics RTL must implement, so every descriptor field is paid for in silicon.
That is the argument for the minimal descriptor AND for exercising every field
kept -- an unexercised field is silicon nobody has ever run.
"""

from __future__ import annotations

import sys
from collections import namedtuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ---------------------------------------------------------------------------
# THE DESCRIPTOR. Minimal: six fields, and every one is exercised by a table in
# this probe. Resisting generality the tables do not need is the rule -- but the
# INPUT GUARD is kept because a machine that can only drive and never sample is a
# waveform player, not an emulator, and the competition's stated use case is
# reading buses. It is exercised by `table_input_branch` before the freeze.
# ---------------------------------------------------------------------------
Entry = namedtuple("Entry", "g out in_pin in_pol next_a next_b")
# g       : hold this long (in clock units) before the transition fires
# out     : pin vector driven for the whole hold -- output is a function of pc
# in_pin  : input pin to sample at the transition, or -1 for unconditional
# in_pol  : take next_a when the sampled pin equals this, else next_b
# next_a  : successor on match / unconditional
# next_b  : successor on mismatch (ignored when in_pin < 0)


def E(g, out, next_a, in_pin=-1, in_pol=0, next_b=0):
    return Entry(g, out, in_pin, in_pol, next_a, next_b)


def wellformed(table, n_pins: int = 8) -> list:
    """⛔⛔ THE DESCRIPTOR FREEZE WAS INCOMPLETE WITHOUT THIS, and B5 is what found
    it: the byte-identity comparison against TA-01 failed at `idle=0` only, because
    a `g=0` entry STILL EMITS ONE CYCLE of output and shifted the whole waveform
    by one.

    `g = 0` is a ZERO-TIME TRANSITION. In RTL that is a combinational path from the
    table memory back into the address it is being read at, and a CYCLE of such
    entries is a combinational loop -- unsynthesizable, and not the sort of thing to
    discover after the semantics are frozen. So `g >= 1` is a WELL-FORMEDNESS RULE
    of the format, enforced here at construction rather than hoped for in the table
    builders: `g >= 1` on every entry makes every loop in the table graph take at
    least one clock, which is non-starvation by construction.

    ⭐ Enforced AT THE ASSEMBLY POINT. A checker the table builders are supposed to
    remember to call is a checker one step away from where the hazard fires.
    """
    errs, n = [], len(table)
    if n == 0:
        return [(-1, "empty table")]
    for i, e in enumerate(table):
        if e.g < 1:
            errs.append((i, "g=%d -- a zero-length guard is a ZERO-TIME "
                            "transition (combinational path in RTL); g >= 1" % e.g))
        if not 0 <= e.next_a < n:
            errs.append((i, "next_a=%d out of range [0,%d)" % (e.next_a, n)))
        if not -1 <= e.in_pin < n_pins:
            errs.append((i, "in_pin=%d outside [-1,%d)" % (e.in_pin, n_pins)))
        if e.in_pol not in (0, 1):
            errs.append((i, "in_pol=%r not a bit" % (e.in_pol,)))
        if e.in_pin >= 0 and not 0 <= e.next_b < n:
            errs.append((i, "next_b=%d out of range [0,%d) on a BRANCHING entry"
                            % (e.next_b, n)))
        if not 0 <= e.out < (1 << n_pins):
            errs.append((i, "out=%r outside the pin vector" % (e.out,)))
    return errs


class Interp:
    """The machine. Protocol-agnostic by construction."""

    def __init__(self, table, check: bool = True):
        self.table = list(table)
        if check:
            errs = wellformed(self.table)
            if errs:
                raise ValueError("ill-formed table: " + "; ".join(
                    "entry %d: %s" % (i, m) for i, m in errs[:4]))

    def initial(self):
        return (0, 0)                       # (pc, clock)

    def output(self, st):
        """Pin vector. A pure function of pc -- no stored output state."""
        return self.table[st[0]].out

    def step(self, st, in_bits=0):
        """One clock. Exactly three branches, ALL on the current entry.

        ⭐ THE BRANCH-POINT AUDIT IS ABOUT THIS FUNCTION. If any branch here
        consulted anything other than `e` (a bit counter, a frame counter, a
        notion of "data phase"), the machine would be protocol-shaped even with
        zero protocol literals in the file.
        """
        pc, x = st
        e = self.table[pc]
        if x + 1 < e.g:                                  # branch 1: still holding
            return (pc, x + 1)
        if e.in_pin < 0:                                 # branch 2: unconditional
            return (e.next_a, 0)
        matched = ((in_bits >> e.in_pin) & 1) == e.in_pol   # branch 3: input guard
        return ((e.next_a if matched else e.next_b), 0)

    # -- waveform ---------------------------------------------------------
    def run(self, n_cycles: int, in_trace=None, pin: int = 0) -> list:
        """Emit `n_cycles` levels of one output pin. `in_trace` supplies inputs."""
        st, out = self.initial(), []
        for c in range(n_cycles):
            out.append((self.output(st) >> pin) & 1)
            st = self.step(st, 0 if in_trace is None else in_trace[c])
        return out

    def run_bus(self, n_cycles: int, in_trace=None) -> list:
        """Emit the full pin vector per cycle (for multi-pin protocols)."""
        st, out = self.initial(), []
        for c in range(n_cycles):
            out.append(self.output(st))
            st = self.step(st, 0 if in_trace is None else in_trace[c])
        return out


# ===========================================================================
# TABLES. These carry the protocols. The machine above carries none.
# ===========================================================================
def table_uart_tx(data_bytes, t_bit: int, idle: int, pin: int = 0,
                  loop: bool = True, tail: int = 0) -> list:
    """UART 8N1 transmit, LSB first, over `data_bytes`.

    `loop=False` parks in a terminal idle entry of length `tail` instead of
    starting another frame -- a one-shot table, which is what the byte-identity
    comparison against the bespoke TA-01 executor needs.

    ⛔ THE DATA IS BAKED INTO THE TABLE, and that is an honest limit of this
    descriptor: one entry per bit means reprogramming the PAYLOAD means reloading
    the table. A real emulator wants a data source (FIFO / shift register), which
    is a descriptor EXTENSION this probe deliberately does not add -- adding it
    now would be generality the genericity proof does not need, and it would be
    silicon paid for before anything exercised it.
    """
    hi, lo = (1 << pin), 0
    t = []
    # ⛔ A ZERO-LENGTH IDLE IS OMITTED, NOT EMITTED AS g=0. `g >= 1` is a
    # well-formedness rule of the format (see `wellformed`), so "no idle" is the
    # ABSENCE of an entry -- not an entry that lasts no time.
    if idle >= 1:
        t.append(E(idle, hi, 1))                          # 0: inter-frame idle
    for bi, b in enumerate(data_bytes):
        t.append(E(t_bit, lo, len(t) + 1))                # start bit
        for k in range(8):
            t.append(E(t_bit, hi if (b >> k) & 1 else lo, len(t) + 1))
        last = (bi == len(data_bytes) - 1)
        if last and not loop:
            t.append(E(t_bit, hi, len(t) + 1))            # stop bit -> park
        else:
            t.append(E(t_bit, hi, 0 if last else len(t) + 1))
    if not loop:
        if tail >= 1:
            t.append(E(tail, hi, len(t)))                 # terminal idle, self-loop
        else:
            t[-1] = t[-1]._replace(next_a=len(t) - 1)     # park on the stop bit
    return t


def table_spi_write(data_bytes, half: int, sclk=0, mosi=1, cs=2) -> list:
    """SPI master, mode 0, MSB first. Deliberately UNLIKE UART: three pins, a
    generated clock, and no sampled bit period at all.

    ⭐ That structural distance is the point -- if the interpreter were secretly
    UART-shaped (one pin, bit-period sampling), SPI could not come off it.
    """
    CS, MO, CK = (1 << cs), (1 << mosi), (1 << sclk)
    idle_lvl = CS                                          # CS high, clk+mosi low
    t = [E(half * 4, idle_lvl, 1)]                         # 0: idle, CS deasserted
    t.append(E(half * 2, 0, 2))                            # 1: CS low (asserted)
    for b in data_bytes:
        for k in range(7, -1, -1):                         # MSB first
            d = MO if (b >> k) & 1 else 0
            t.append(E(half, d, len(t) + 1))               # clk LOW, data set up
            t.append(E(half, d | CK, len(t) + 1))          # clk HIGH, sampled here
    t[-1] = t[-1]._replace(next_a=len(t))
    t.append(E(half * 2, 0, 0))                            # CS stays low, then idle
    return t


def table_pwm(duties, period: int, pin: int = 0) -> list:
    """⭐ THE OFF-PATTERN TABLE, WRITTEN LAST AND ON PURPOSE.

    A pulse train is nothing like the two protocols the descriptor was designed
    against: no framing, no data, no clock line, no transfer -- just a periodic
    level with a duty cycle, running forever. Writing it AFTER the descriptor was
    frozen is what makes it a witness: had it been written first, the format would
    have been shaped to fit it, and "the format generalises" would be unfalsifiable.

    `duties` is one duty count per period, so the train may VARY period to period
    -- which is the part a two-entry fixed oscillator would not exercise.

    ⛔ 1 <= duty <= period-1. A duty of 0 or `period` needs a zero-length entry,
    which `wellformed` forbids as a zero-time transition; the honest encoding of
    "always low" is one entry, not two with one of them lasting no time.
    """
    hi, lo = (1 << pin), 0
    t = []
    for i, d in enumerate(duties):
        assert 1 <= d <= period - 1, "duty %d outside [1,%d]" % (d, period - 1)
        nxt = 0 if i == len(duties) - 1 else len(t) + 2
        t.append(E(d, hi, len(t) + 1))                    # high phase
        t.append(E(period - d, lo, nxt))                  # low phase
    return t


def table_input_branch(hold: int, in_pin: int = 3, out_pin: int = 0) -> list:
    """⭐ THE FIELD-EXERCISER. Samples an input and takes a DIFFERENT path with a
    DIFFERENT output depending on what it saw.

    Not a wait-for-high stall -- a genuine control divergence, which is the shape
    SPI-read and I2C-ACK will need, and the shape that stops the automaton being a
    straight-line timed sequence. An unexercised descriptor field is silicon
    nobody has run.
    """
    hi, lo = (1 << out_pin), 0
    return [
        E(hold, lo, 1),                                     # 0: settle low
        E(hold, lo, next_a=2, in_pin=in_pin, in_pol=1, next_b=3),   # 1: SAMPLE
        E(hold, hi, 0),                                     # 2: saw 1 -> drive high
        E(hold, lo, 0),                                     # 3: saw 0 -> drive low
    ]
