"""pe_proto -- SP2: the protocol front-end to `pe_asm`.

A TRANSACTION goes in; the lane's actions come out, with the bus conditions
(START, repeated START, STOP; SPI chip-select framing) GENERATED FROM CONTEXT.
The user writes "write 3 bytes, then read 2", not the conditions.

⭐ WHY THE CONDITIONS MUST BE GENERATED, NOT WRITTEN. Each condition's action
sequence depends on the SCL level the PREVIOUS action left behind, and the
hand-written programs got that wrong twice before sigrok caught it (rulings
RC1 / TX8): a bare OP_STOP after a clocked SHIFTIN released SDA with SCL low
(no STOP at all), and three actions after a NACK put a spurious START on the
wire. Here the level is TRACKED and the sequence chosen from it:

    clocked SHIFT   (self-clocked, level 1)  ends with SCL HIGH
    clocked SHIFTIN (self-clocked, level 1)  ends with SCL LOW (its COLLECT)
    START / STOP / repeated START            end with SCL HIGH
    unclocked READBIT on SDA                 leaves SCL where it was

    rSTART from SCL low  : SDA rel, SCL rel, START
    rSTART from SCL high : SCL low, SDA rel, SCL rel, START
    STOP   from SCL low  : SDA low, SCL rel, STOP
    STOP   from SCL high : SCL low, SDA low, SCL rel, STOP

Context rules (the whole of the "front-end" contract):
  * a transaction begins with START (bus idle: both lines released);
  * a segment AFTER the first is preceded by a repeated START (a direction
    change, write-then-read, is the case the FRAM random read needs);
  * the transaction ends with STOP, then the loop REARM.

⚠ THE COUNT FIELD OF OPCODES THAT IGNORE IT. START/STOP/LEVEL/READBIT/REARM
never read `count`, and the shipped builders disagree on what they write
there: `corpus._assemble` writes 8, `run_ckack.image` writes 0. That is a
don't-care in silicon and a byte difference in the image, so the front-end
takes it as a parameter (`nc_count`) and the SP2 gate reports which value
each reference used -- it is not hidden.

Every image still goes through `pe_asm.assemble`, so every admissibility
check applies to front-end programs exactly as to hand-written ones.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "test"))

from pe_isa import (OP_ARM, OP_LEVEL, OP_READBIT, OP_REARM,  # noqa: E402
                    OP_SHIFT, OP_SHIFTIN, OP_START, OP_STOP, ORDER_LSB,
                    ORDER_MSB, PIN_NONE, SELF_CLOCKED)

SCL_LOW, SCL_HIGH = 0, 1


class ProtoError(Exception):
    """A transaction the front-end cannot express. Names the segment."""


# ---------------------------------------------------------------------------
# I2C
# ---------------------------------------------------------------------------
class I2C:
    """One open-drain I2C lane (master), self-clocked bytes.

    `rules` holds the context rules as data so a must-fire can MUTATE one
    (e.g. STOP + START in place of the repeated START) and the byte-identity
    check must go red. Callers never pass it.
    """

    def __init__(self, sda, scl, d, nc_count=8, rules=None):
        self.sda, self.scl, self.d, self.nc = sda, scl, d, nc_count
        self.rules = dict(DEFAULT_I2C_RULES)
        self.rules.update(rules or {})

    # -- primitives ---------------------------------------------------------
    def _a(self, op, pin, lvl, cnt=None):
        return (op, pin, lvl, self.d, 0, self.nc if cnt is None else cnt)

    def _tx(self, nbits):
        return (OP_SHIFT, self.sda, SELF_CLOCKED, self.d, 0, nbits - 1)

    def _rx(self, nbits):
        return (OP_SHIFTIN, self.sda, SELF_CLOCKED, self.d, 0, nbits)

    def _cond(self, kind, scl):
        """The action list for condition `kind` ('start'/'rstart'/'stop')
        given the current SCL level."""
        L = []
        for step in self.rules[(kind, scl)]:
            if step == "SDA0":
                L.append(self._a(OP_LEVEL, self.sda, 0))
            elif step == "SDA1":
                L.append(self._a(OP_LEVEL, self.sda, 1))
            elif step == "SCL0":
                L.append(self._a(OP_LEVEL, self.scl, 0))
            elif step == "SCL1":
                L.append(self._a(OP_LEVEL, self.scl, 1))
            elif step == "START":
                L.append(self._a(OP_START, self.sda, 0))
            elif step == "STOP":
                L.append(self._a(OP_STOP, self.sda, 1))
            else:
                raise ProtoError("unknown condition step %r" % step)
        return L

    # -- the transaction ----------------------------------------------------
    def transaction(self, segments, loop=True):
        """`segments`: a list of
            ("write", n)  -- n bytes out (the first is the address+W), each
                             followed by the target's ACK slot (1-bit receive)
            ("read", n)   -- the address+R byte out + ACK slot, then n bytes
                             in, each followed by the master's ACK (1-bit
                             transmit), the LAST by its NACK
            ("raw", action[, scl_after]) -- a pass-through action; scl_after
                             None = leaves SCL where it was
        Returns the lane's action list (pe_asm form, count included)."""
        if not segments or segments[0][0] == "raw":
            raise ProtoError("a transaction must begin with a write or read "
                             "segment (the START needs an address phase)")
        acts, scl, nseg = [], SCL_HIGH, 0
        for i, seg in enumerate(segments):
            kind = seg[0]
            if kind in ("write", "read"):
                n = int(seg[1])
                if n < 1:
                    raise ProtoError("segment %d: %s of %d bytes" % (i, kind, n))
                acts += self._cond("start" if nseg == 0 else "rstart", scl)
                scl = SCL_HIGH
                nseg += 1
                if kind == "write":
                    for _b in range(n):
                        acts += [self._tx(8), self._rx(1)]
                    scl = SCL_LOW
                else:
                    acts += [self._tx(8), self._rx(1)]
                    for b in range(n):
                        acts += [self._rx(8), self._tx(1)]   # ACK / last NACK
                    scl = SCL_HIGH
            elif kind == "raw":
                a = seg[1]
                if a[0] in (OP_START, OP_STOP):
                    raise ProtoError("segment %d: a raw START/STOP -- the "
                                     "conditions are generated, not written" % i)
                acts.append(tuple(a))
                if len(seg) > 2 and seg[2] is not None:
                    scl = seg[2]
            else:
                raise ProtoError("segment %d: unknown kind %r" % (i, kind))
        acts += self._cond("stop", scl)
        if loop:
            acts.append(self._a(OP_REARM, 0, 1))
        return acts

    def header(self, flags=0):
        d = self.d
        return (self.sda, self.scl, 0, d, 2 * d, 3 * d, flags)


DEFAULT_I2C_RULES = {
    ("start", SCL_HIGH): ("START",),
    ("rstart", SCL_LOW): ("SDA1", "SCL1", "START"),
    ("rstart", SCL_HIGH): ("SCL0", "SDA1", "SCL1", "START"),
    ("stop", SCL_LOW): ("SDA0", "SCL1", "STOP"),
    ("stop", SCL_HIGH): ("SCL0", "SDA0", "SCL1", "STOP"),
}

#: the must-fire mutation: a STOP followed by a START in place of the
#: repeated START (the bus is released between the two address phases, which
#: a FRAM's random read does not survive -- the address pointer it set is
#: kept, but another master may take the bus)
MUTANT_RSTART_AS_STOP_START = {
    ("rstart", SCL_LOW): ("SDA0", "SCL1", "STOP", "START"),
}


# ---------------------------------------------------------------------------
# SPI (master, self-clocked, MSB-first)
# ---------------------------------------------------------------------------
class SPI:
    """One push-pull SPI master lane. Transactions are CS-framed: CS low,
    bytes out, bytes in, CS high -- generated, never written. `mode0` parks
    SCK low before each select (CPOL from SCK at CS fall).

    ⛔ `order` HAS NO DEFAULT (Wilson, SP2/P2). SPI has no START/STOP for
    `order_for` to derive an order from, and pe_asm's documented default is
    LSB (UART's) -- so an SPI lane that forgot to say would go out
    bit-reversed with nothing flagging it. In the front-end the order is
    stated or the lane is refused (`image` checks the header too)."""

    def __init__(self, mosi, sclk, cs, miso, d, order, nc_count=8,
                 mode0=False):
        if order not in (ORDER_LSB, ORDER_MSB):
            raise ProtoError("SPI order must be ORDER_MSB or ORDER_LSB, "
                             "stated explicitly; got %r" % (order,))
        self.mosi, self.sclk, self.cs, self.miso = mosi, sclk, cs, miso
        self.d, self.nc, self.mode0, self.order = d, nc_count, mode0, order

    def _a(self, op, pin, lvl):
        return (op, pin, lvl, self.d, 0, self.nc)

    def transactions(self, txns, loop=True):
        """`txns`: a list of (n_out, n_in) per CS frame."""
        acts = []
        for i, (n_out, n_in) in enumerate(txns):
            if n_out < 0 or n_in < 0 or n_out + n_in == 0:
                raise ProtoError("frame %d: (%d out, %d in)" % (i, n_out, n_in))
            if self.mode0:
                acts.append(self._a(OP_LEVEL, self.sclk, 0))
            acts.append(self._a(OP_LEVEL, self.cs, 0))
            acts += [(OP_SHIFT, self.mosi, SELF_CLOCKED, self.d, 0, 7)] * n_out
            acts += [(OP_SHIFTIN, self.miso, SELF_CLOCKED, self.d, 0, 8)] * n_in
            acts.append(self._a(OP_LEVEL, self.cs, 1))
        if loop:
            acts.append(self._a(OP_REARM, 0, 1))
        return acts

    def header(self, flags=0):
        d = self.d
        return (self.mosi, self.sclk, 1, d, 2 * d, 3 * d, flags, self.order)


def _rtl_pin(name):
    """`name`'s value in src/project.v (MISO_PIN, CS_PIN): the silicon's own
    pins, read from the RTL rather than restated."""
    import re
    with open(os.path.join(ROOT, "src", "project.v"), encoding="utf-8") as fh:
        m = re.search(r"parameter\s+integer\s+%s\s*=\s*(\d+)" % name, fh.read())
    if not m:
        raise ProtoError("%s not found in src/project.v" % name)
    return int(m.group(1))


def spi_lanes_without_order(lanes, headers):
    """-> [lane]: every SPI lane whose header does not STATE its order (no 8th
    element). Two kinds:
      * an SPI MASTER: push-pull, a real clock pin, a self-clocked SHIFT or
        SHIFTIN;
      * an SPI TARGET: push-pull, NO clock pin (the master supplies SCK), a
        SHIFT or SHIFTIN on the silicon's MISO_PIN. ⛔ Found building the
        target (10-20): the master-only test skipped it, so a target header
        with no order assembled LSB-first -- every byte bit-reversed on MISO,
        accepted, header byte 5 the only difference. MISO_PIN is the one pin
        whose CS-release hardware exists only for an SPI target, so a lane
        shifting there is one.
    ⭐ I2C lanes are open-drain and their order is DERIVED (START/STOP, ruling
    RC4); UART and 1-Wire have no clock and shift elsewhere, and keep pe_asm's
    documented default (LSB, which is theirs)."""
    from pe_isa import N_PINS
    miso = _rtl_pin("MISO_PIN")
    bad = []
    for ln in sorted(headers):
        h = headers[ln]
        if int(h[2]) != 1 or len(h) >= 8:
            continue
        acts = lanes.get(ln, ())
        if int(h[1]) < N_PINS:
            if any(a[0] in (OP_SHIFT, OP_SHIFTIN) and a[2] == SELF_CLOCKED
                   for a in acts):
                bad.append(ln)
        elif any(a[0] in (OP_SHIFT, OP_SHIFTIN) and a[1] == miso
                 for a in acts):
            bad.append(ln)
    return bad


class SPITarget:
    """One SPI-TARGET lane: the master drives SCK, MOSI and CS; this lane
    shifts a host-fed byte out on MISO, one bit per change-edge of SCK, and
    (`mosi=True`) samples MOSI after each. Wilson's ruling (10-18): MISO out
    witnessed at 1 MHz, MOSI capture at <= 500 kHz, all four modes, a fixed
    2-byte transaction.

    ⭐ HOW IT IS TIMED (model/zero_spacing.py E1-E3): a delay-0 ARM waits on
    its edge, and the edge releases its successor at once; an action's delay
    spaces it from the NEXT action. So `ARM(edge) ; SHIFT(MISO, d)` drives
    MISO a fixed latency after the edge, and the next ARM opens `d` later.
    ⭐ THE MODE IS THE CHANGE-EDGE: CPHA 0 (modes 0, 2) drives bit 7 at CS
    fall and every later bit on SCK's trailing edge; CPHA 1 (modes 1, 3)
    drives each bit on SCK's leading edge. CPOL picks which level those
    edges are: falling for modes 0 and 3, rising for modes 1 and 2.
    ⛔ LIMITS, STATED (spi_target_proposal.md): no abort or resync on CS
    rising mid-byte (no two-pin wait); an edge before the ARM's window opens
    is lost; MOSI at 1 MHz has ~0-4 cycles of margin, hence <= 500 kHz."""

    CHG_RISE = {0: 0, 1: 1, 2: 1, 3: 0}   # mode -> 1 if the change-edge rises

    def __init__(self, mode, sck, mosi_pin, d=20, nbytes=2, mosi=False,
                 order=ORDER_MSB):
        if mode not in self.CHG_RISE:
            raise ProtoError("SPI mode must be 0..3; got %r" % (mode,))
        if order not in (ORDER_LSB, ORDER_MSB):
            raise ProtoError("SPI order must be ORDER_MSB or ORDER_LSB, "
                             "stated explicitly; got %r" % (order,))
        if nbytes < 1:
            raise ProtoError("an SPI-target frame needs at least one byte")
        self.mode, self.sck, self.mosi_pin = mode, sck, mosi_pin
        self.cs, self.miso = _rtl_pin("CS_PIN"), _rtl_pin("MISO_PIN")
        self.d, self.nbytes, self.mosi, self.order = d, nbytes, mosi, order

    def _bit(self):
        out = [(OP_SHIFT, self.miso, 0, self.d, 0, 7)]
        if self.mosi:
            out.append((OP_SHIFTIN, self.mosi_pin, 0, self.d, 0, 8))
        return out

    def program(self):
        edge = self.CHG_RISE[self.mode]
        acts = [(OP_ARM, self.cs, 0, 0, 0)]              # frame start: CS fall
        nbits = 8 * self.nbytes
        first = 0
        if self.mode in (0, 2):                          # CPHA 0: bit 7 at CS
            acts += self._bit()
            first = 1
        for _ in range(first, nbits):
            acts.append((OP_ARM, self.sck, edge, 0, 0))
            acts += self._bit()
        acts.append((OP_REARM, 0, 1, self.d, 0))
        return acts

    def t_ext(self, sck_hz=1_000_000, f_clk=50_000_000):
        """{lane 0: T_ext}: the master's claimed maximum SCK period, in cycles
        -- the period of this edge-paced lane (program_a2.T_EXT). 50 at
        1 MHz MISO-only; the MOSI variant is witnessed at <= 500 kHz."""
        return {0: f_clk // sck_hz}

    def header(self, dsched=25, dtol=17, flags=0):
        """MISO, no clock pin, push-pull, the bit order STATED. dsched 25 is
        the ruled deadline (half of a 1 MHz SCK period), dtol 17 the ledger's
        SPI-target D_tol."""
        return (self.miso, PIN_NONE, 1, self.d, dsched, dtol, flags,
                self.order)


def image(lanes, headers, park_pins=None, timing_checks=True, exempt_as=None,
          t_ext=None):
    """Through `pe_asm.assemble` -- every admissibility check applies (the
    per-program timing pair only when `timing_checks`, and then only for an
    image the non-admissible registry names: `exempt_as`, see pe_asm).

    ⛔ SP2/P2: an SPI lane must STATE its bit order here; raw pe_asm keeps its
    documented default (order_for: LSB unless START/STOP)."""
    bad = spi_lanes_without_order(lanes, headers)
    if bad:
        raise ProtoError(
            "lane(s) %s are SPI lanes (a master: push-pull, real clock, "
            "self-clocked shifts; or a target: no clock, shifting on "
            "MISO_PIN) whose header does not state a bit order. SPI has no "
            "START/STOP to derive it from and the raw default is LSB-first; "
            "the front-end requires the 8th header element (ORDER_MSB for "
            "SPI mode 0/3 parts)." % bad)
    import pe_asm
    return pe_asm.assemble(lanes, headers, park_pins=park_pins,
                           timing_checks=timing_checks, exempt_as=exempt_as,
                           t_ext=t_ext)


# ---------------------------------------------------------------------------
# THE SHIPPED FRAM PROGRAMS, RE-EXPRESSED (the SP2 regression's subjects)
# ---------------------------------------------------------------------------
def i2c_fram_write(d=70, sda=2, scl=1):
    """`corpus_i2c`: one address byte + ACK slot, the corpus's coverage
    READBIT on SDA (raw; it does not move SCL), then STOP."""
    m = I2C(sda, scl, d, nc_count=8)
    lanes = {0: m.transaction([("write", 1),
                               ("raw", (OP_READBIT, sda, 0, d, 0, 8))])}
    return lanes, {0: m.header()}, None


def i2c_fram_random_read(d=70, flags=0, sda=2, scl=1, rules=None):
    """`run_ckack.image`: the MB85RC random read
    S A0 A 01 A 23 A Sr A1 A data A data NACK P -- written as a 3-byte write
    then a 2-byte read; the Sr and the P are generated."""
    m = I2C(sda, scl, d, nc_count=0, rules=rules)
    lanes = {0: m.transaction([("write", 3), ("read", 2)])}
    return lanes, {0: m.header(flags)}, {1: 0, 2: 3, 3: 4, 4: 5}


def i2c_read_timing(d=70, sda=2, scl=1):
    """`ckread_image`: a 2-byte read (address + ACK slot, 2 bytes in, ACK,
    NACK), then STOP."""
    m = I2C(sda, scl, d, nc_count=0)
    lanes = {0: m.transaction([("read", 2)])}
    return lanes, {0: m.header()}, {1: 0, 2: 3, 3: 4, 4: 5}


class OneWire:
    """CE5: a 1-Wire master (DS18B20) on the frozen ISA -- a SLOT ENGINE.

    ⛔⛔ WHY THE PROGRAM IS A SLOT ENGINE AND NOT THE TRANSACTION. The ISA has
    no counter, compare or branch, and a lane's only loop is REARM back to its
    base. Unrolled, READ ROM's 64 read slots alone are 64 x 3 = 192 actions,
    and the whole store holds (256 - 30) / 3 = 75. So the transaction cannot
    live on the chip (docs/CE5_LOG.md, OW1). What CAN live on the chip -- and
    is the timing-critical part -- is the SHAPE of every slot: when the line
    falls, when it is released, when it is sampled. The host supplies, per
    slot, WHICH shape (four bits from the TX queue), exactly the split real
    1-Wire masters (DS2480B / DS2482) make between host and line driver.

    ONE ITERATION of the loop (period P) is one SYMBOL, four TX bits b0..b3,
    on the open-drain DQ pin `q` (0 = pull low, 1 = release):

        t = 0      SHIFT q <- b0            0: the slot's falling edge
        t = A      SHIFT q <- b1            1: release (write-1 / read)
        t = A+B    SHIFTIN s  (sample)      the read / presence sample
        t = TW0    SHIFT q <- b2            1: release (end of a write-0)
        t = T3     SHIFT q <- b3            1: release (end of a reset)
        t = P      (REARM, loop)

        symbol  b3..b0  wire
        W1/READ  1110   low A, sample at A+B         (tLOW1 / tINIT)
        W0       1100   low TW0                      (tLOW0)
        RST      0000   low the whole iteration      (tRSTL, chained)
        RSTEND   1000   low until T3, then released  (end of tRSTL)
        IDLE     1111   released; its sample at A+B is the PRESENCE sample
                        when it follows RSTEND: (P - T3) + A + B after release

    ⛔ THE SAMPLE IS ON A SECOND PIN `s`, wired to the same DQ net. An
    unclocked SHIFTIN RELEASES the pin it samples (`pin_oe[a_pin] <= 0`), so
    sampling DQ itself would end a write-0 at the 12 us sample point. The
    engine cannot sample a line it is holding low (CE5_LOG, OW2).

    ⛔ AND A THIRD PIN `c`, THE CLOCK THE PROTOCOL DOES NOT HAVE. Silicon
    refuses an open-drain lane whose clock pin is not a `uio` pin (1.6s, at
    header load), so a clockless open-drain lane cannot say PIN_NONE. `c`
    must be a spare `uio` pin left UNCONNECTED: every SHIFT (level 0, real
    clock) pulls it low, and routes the data move through the SDA hold
    pipeline (+SDA_HOLD cycles, a constant shift of every edge) -- CE5_LOG,
    OW3.

    RECEIVE: `count = 8` on the SHIFTIN, LSB-first lane: every 8 symbols the
    chip PUSHES one byte = those 8 samples, first sample in bit 0 -- 1-Wire's
    own bit order. Every block of the transaction is a multiple of 8 symbols,
    so each pushed byte is exactly one 1-Wire byte (or one reset block half).
    """

    SYM = {"W1": 0xE, "W0": 0xC, "RST": 0x0, "RSTEND": 0x8, "IDLE": 0xF}

    def __init__(self, q=2, s=3, c=4, f_mhz=50, A_us=3.0, B_us=9.0,
                 TW0_us=70.0, D_us=2.0, TAIL_us=56.0, nc_count=8):
        self.q, self.s, self.c, self.f, self.nc = q, s, c, f_mhz, nc_count
        cy = lambda us: int(round(us * f_mhz))
        self.A, self.B, self.TW0 = cy(A_us), cy(B_us), cy(TW0_us)
        self.D, self.TAIL = cy(D_us), cy(TAIL_us)
        if self.TW0 <= self.A + self.B + 20:
            raise ProtoError("TW0 must follow the sample by >= D*")
        self.T3 = self.TW0 + self.D
        self.P = self.T3 + self.TAIL

    @staticmethod
    def _chunks(total, cap=1000, floor=20):
        """`total` cycles as delays each in [floor, cap] (DLY_W = 10 bits:
        one action waits at most 1023 cycles = 20.46 us at 50 MHz)."""
        n = -(-total // cap)
        out = [total // n] * n
        out[-1] += total - sum(out)
        if min(out) < floor:
            raise ProtoError("a %d-cycle wait splits below D*" % total)
        return out

    def program(self):
        q, s, nc = self.q, self.s, self.nc
        sh = lambda d: (OP_SHIFT, q, 0, d, 0, 7)              # one TX bit
        nop = lambda d: (OP_LEVEL, 15, 0, d, 0, nc)           # PIN_NONE no-op
        acts = [sh(self.A), sh(self.B)]
        c = self._chunks(self.TW0 - self.A - self.B)
        acts.append((OP_SHIFTIN, s, 0, c[0], 0, 8))
        acts += [nop(x) for x in c[1:]]
        acts.append(sh(self.D))
        t = self._chunks(self.TAIL)
        acts.append(sh(t[0]))
        acts += [nop(x) for x in t[1:-1]] if len(t) > 2 else []
        last = t[-1] if len(t) > 1 else None
        if last is None:
            raise ProtoError("TAIL must span at least two waits")
        acts.append((OP_REARM, 0, 1, last, 0, nc))
        return acts

    def header(self):
        a = self.A
        return (self.q, self.c, 0, a, min(2 * a, 255), min(3 * a, 255))

    def lanes_headers(self):
        return {0: self.program()}, {0: self.header()}

    # -- the host side: transaction -> TX symbols, and the receive map -------
    RESET_BLOCK = ["RST"] * 4 + ["RSTEND"] + ["IDLE"] * 11   # 16 symbols
    PRESENCE_BIT = 5                                          # first IDLE

    def feed(self, txn):
        """`txn`: [("reset",), ("write", byte), ("read", n), ("poll",)].
        -> (feed words, rx map). A feed word is ("byte", b) or ("poll", [4
        bytes]) -- a poll group the host repeats until a pushed byte is
        non-zero (VDD mode: Convert T answers 0 while busy, 1 when done).
        The rx map names what each PUSHED byte is, in order.
        ⭐ EVERY SYMBOL IS THE HOST'S, the first reset block included
        (silicon fix #8, WF2). Before it the shift register's reset 0x00 went
        out first, so the first 8 SHIFTs sent RST RST before any host byte and
        the first reset block was cut to 14 host symbols to absorb them. The
        fix takes a byte's first bit from the queue head, so that workaround
        is gone: the first block is the full 16, like every other."""
        syms, rxmap, words = [], [], []
        polls = []

        def flush_syms():
            if len(syms) % 2:
                raise ProtoError("odd symbol count at a byte boundary")
            for k in range(0, len(syms), 2):
                words.append(("byte", self.SYM[syms[k]]
                              | self.SYM[syms[k + 1]] << 4))
            del syms[:]

        for step in txn:
            kind = step[0]
            if kind == "reset":
                syms += list(self.RESET_BLOCK)
                rxmap += [("reset", 0), ("reset", 1)]
            elif kind == "write":
                b = int(step[1])
                syms += ["W1" if (b >> i) & 1 else "W0" for i in range(8)]
                rxmap.append(("echo", b))
            elif kind == "read":
                for i in range(int(step[1])):
                    syms += ["W1"] * 8
                    rxmap.append(("read", step[2] if len(step) > 2 else "",
                                  i))
            elif kind == "poll":
                flush_syms()
                grp = [self.SYM["W1"] | self.SYM["W1"] << 4] * 4
                words.append(("poll", grp))
                rxmap.append(("poll",))
                polls.append(len(rxmap) - 1)
            else:
                raise ProtoError("unknown 1-Wire step %r" % (kind,))
        flush_syms()
        return words, rxmap

    def feed_file(self, txn, idle_bytes=8):
        """The bench's feed file: `0xx` = push byte xx; `1xx` = the poll
        group's first byte (the next 3 lines complete the group); after the
        transaction, IDLE bytes so the lane never underruns while the last
        pushes drain."""
        words, rxmap = self.feed(txn)
        lines = []
        for w in words:
            if w[0] == "byte":
                lines.append("%03x" % w[1])
            else:
                g = w[1]
                lines.append("%03x" % (0x100 | g[0]))
                lines += ["%03x" % b for b in g[1:]]
        lines += ["%03x" % 0xFF] * idle_bytes
        return lines, rxmap


#: CE5's transaction (DS18B20 datasheet 19-7487 Rev 6, "Transaction
#: Sequence"): READ ROM; SKIP ROM + CONVERT T, poll to done; SKIP ROM + READ
#: SCRATCHPAD (9 bytes, CRC last)
DS18B20_TXN = [("reset",), ("write", 0x33), ("read", 8, "rom"),
               ("reset",), ("write", 0xCC), ("write", 0x44), ("poll",),
               ("reset",), ("write", 0xCC), ("write", 0xBE),
               ("read", 9, "sp")]


def onewire_tt():
    """The TT image: DQ = uio[2] (open-drain), sense = uio[3] (input)."""
    return OneWire()


def onewire_fpga():
    """The Puzhi PA100T-EDU variant: the same engine at 50 MHz, with the read
    slot's master-low cut to 2 us and the sample moved to 13 us -- datasheet
    Figure 18's advice (keep T_INIT short, sample late in the 15 us window)
    for a real 4.7 kOhm pull-up whose rise time the bench cannot know."""
    return OneWire(A_us=2.0, B_us=11.0)


def spi_fram(d=7, mode0=False, clkinv=False):
    """`corpus_spim`: WREN, WRITE a a d d d, READ a a [in] [in].
    ⭐ ONE WREN since silicon fix #8 (the program had sent it twice to absorb
    the reset 0x00 that went out first)."""
    import corpus
    from pe_isa import FLAG_CLK_INV
    m = SPI(corpus.P_M_MOSI, corpus.P_M_SCLK, corpus.P_M_CS, corpus.P_M_MISO,
            d, ORDER_MSB, nc_count=8, mode0=mode0)
    lanes = {0: m.transactions([(1, 0), (6, 0), (3, 2)])}
    return lanes, {0: m.header(FLAG_CLK_INV if clkinv else 0)}, None
