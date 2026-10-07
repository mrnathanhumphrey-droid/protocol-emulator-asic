"""THE TRACE CORPUS -- protocol-shaped programs that actually move `uio`.

Wilson's BROADEN ruling after `53623c2`. The cycle-exact result was true and
NARROW: `uio_out` and `uio_oe` were **constant across the whole trace**, so the
agreement came almost entirely from `uo_out`, and everything the two simulators
are most likely to disagree on was unexercised.

⛔⛔ THE CAUSE WAS IN THE PROGRAMS, NOT THE BENCH. Every image this project had
built -- `smoke`, `census`, `five`, `chain`, `stress` -- drives `UO0..UO3`,
which are pins 8..11, the `uo_out` bank. `build_census`'s own docstring says it
is "a coverage program, not a protocol ... its pin waveform means nothing". So
the trace had nothing to show on `uio` because no program had ever asked for
anything there. ⇒ Broadening the corpus is a PROGRAM job.

⛔⛔ AND BOTH FRAM PEERS WERE WIRED INTO NOTHING. `test/fram_spi.v` and
`test/fram_i2c.v` are lint-clean in two simulators and were instantiated by no
bench at all -- "SPI master -> SPI FRAM peer" had never once run against the
DUT. A peer that compiles is not a peer that is connected.

## The ruled pin map, derived rather than written down twice

The two-bank ruling (`model/a2/gate_pin_subsets.py`, `PINS_DIR`) says `uio`
carries inputs + open-drain + tri-state-out -- everything that must be able to
STOP driving -- and `uo_out` carries push-pull only.

⭐ UNDER THAT RULING ALL FIVE LANES FIT, which the "12 protocol pins against 8
`uio`" framing in `PHASE1_CLOSEOUT_PART4.md` predates: `bank_need(all five)`
is `(8, 4)`, exactly `N_UIO = 8` plus the 4 push-pull protocol outputs, and
`addressable_pins() = 12 = N_PINS`. Both banks are exactly full, so the
allocation is FORCED up to ordering, and a five-lane program is pin-feasible.

⭐⭐ AND THE ORDERING IS CONFIRMED BY THE RTL, not chosen to match it. Walking
the lanes in shipped order puts SPI-target's CS on `uio[6]` and its tri-state
MISO on `uio[7]`; `src/project.v` independently declares `CS_PIN = 6` and
`MISO_PIN = 7`. That agreement is checked at import (`_assert_rtl_agrees`),
because those two are build parameters of the async-release path and a silent
disagreement would make the async-clear arm test the wrong pin.

## What can move `uio_oe` at all

Only three of the eight `uio` bits are ever DRIVEN by the engine: I2C's two
open-drain pins and SPI-target's tri-state MISO. The other five are inputs
(SPI-master MISO, UART-rx RX, SPI-target SCLK/MOSI/CS).

⛔ So "every program must produce non-constant `uio_out`/`uio_oe`" is
satisfiable only by a program containing **I2C or SPI-target**. For the
SPI-master, UART-tx and UART-rx lanes the ruled map puts every driven pin on
`uo_out` and leaves their `uio` pin an INPUT -- those lanes move `uio_in`, not
`uio_out`. The precondition is therefore asserted PER PROGRAM against what that
program's lanes can drive (`expect` below), and the trace gained a `uio_in`
column so peer-driven activity is compared at all rather than being invisible.
"""

from __future__ import annotations

import glob
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "model", "a2"))
sys.path.insert(0, os.path.join(ROOT, "model"))
# ⛔ ONE IMAGE DECODER, TOO. `walk`/`load` already exist in
# `model/gate_degenerate_fields.py` and are the only implementation; a second
# decoder here would be the duplicated-unpacker shape this project refuses on
# the ENCODER side, with the same failure mode -- two readers of one layout
# that drift and both look right.
import gate_degenerate_fields as dgf      # noqa: E402

# ⛔ ONE ENCODER. `hdr`/`act` are IMPORTED, never re-implemented here: two
# copies of a bit-packer is the exact failure `lane_digest` exists to catch,
# and a corpus encoded by a second builder would be a different ISA.
from make_smoke_image import (            # noqa: E402
    ACT_BASE, ACT_BYTES, AW, D_FM_SHIPPABLE, HDR_BYTES, N_LANES,
    OP_ARM, OP_LEVEL, OP_READBIT, OP_REARM, OP_SHIFT, OP_SHIFTIN, OP_START,
    SELF_CLOCKED,
    OP_STOP, PIN_NONE, act, hdr,
)

# ---------------------------------------------------------------------------
# THE PIN MAP, derived from the ruling
# ---------------------------------------------------------------------------
N_UIO = 8

# (lane, signal, class) in shipped lane order. `class` is the PINS_DIR bucket:
#   "in" = input, "od" = open-drain, "tri" = tri-state out, "pp" = push-pull
_WIRES = [
    ("UART-tx 115200",   "TX",   "pp"),
    ("SPI-tx 1 MHz",     "SCLK", "pp"),
    ("SPI-tx 1 MHz",     "MOSI", "pp"),
    ("SPI-tx 1 MHz",     "CS",   "pp"),
    ("SPI-tx 1 MHz",     "MISO", "in"),
    ("I2C 400 kHz",      "SCL",  "od"),
    ("I2C 400 kHz",      "SDA",  "od"),
    ("UART-rx 115200",   "RX",   "in"),
    ("SPI-target 1 MHz", "SCLK", "in"),
    ("SPI-target 1 MHz", "MOSI", "in"),
    ("SPI-target 1 MHz", "CS",   "in"),
    ("SPI-target 1 MHz", "MISO", "tri"),
]

_LANE_ORDER = ["UART-tx 115200", "SPI-tx 1 MHz", "I2C 400 kHz",
               "UART-rx 115200", "SPI-target 1 MHz"]


def _allocate():
    """uio gets in/od/tri; uo_out gets pp. Lanes walked in SHIPPED ORDER."""
    pin, uio_n, uo_n = {}, 0, 0
    for lane in _LANE_ORDER:
        for ln, sig, cls in _WIRES:
            if ln != lane or cls == "pp":
                continue
            pin[(lane, sig)] = uio_n
            uio_n += 1
        for ln, sig, cls in _WIRES:
            if ln != lane or cls != "pp":
                continue
            pin[(lane, sig)] = N_UIO + uo_n
            uo_n += 1
    assert uio_n == N_UIO, "uio allocation %d != %d" % (uio_n, N_UIO)
    assert uo_n == 4, "uo_out protocol allocation %d != 4" % uo_n
    return pin


PIN = _allocate()

# the names the benches and gates use
P_TX        = PIN[("UART-tx 115200", "TX")]
P_M_SCLK    = PIN[("SPI-tx 1 MHz", "SCLK")]
P_M_MOSI    = PIN[("SPI-tx 1 MHz", "MOSI")]
P_M_CS      = PIN[("SPI-tx 1 MHz", "CS")]
P_M_MISO    = PIN[("SPI-tx 1 MHz", "MISO")]
P_SCL       = PIN[("I2C 400 kHz", "SCL")]
P_SDA       = PIN[("I2C 400 kHz", "SDA")]
P_RX        = PIN[("UART-rx 115200", "RX")]
P_T_SCLK    = PIN[("SPI-target 1 MHz", "SCLK")]
P_T_MOSI    = PIN[("SPI-target 1 MHz", "MOSI")]
P_T_CS      = PIN[("SPI-target 1 MHz", "CS")]
P_T_MISO    = PIN[("SPI-target 1 MHz", "MISO")]

MODE_OD, MODE_PP = 0, 1


def _assert_rtl_agrees():
    """⛔⛔ THE ALLOCATION MUST MATCH `project.v`'s BUILD PARAMETERS.

    `MISO_PIN` and `CS_PIN` are not decoration: `cs_deasserted = uio_in[CS_PIN]`
    is the async-clear source for `miso_oe_q`, and the enable that reaches the
    pin is rebuilt around `MISO_PIN`. If this map disagreed with them, the
    async-clear arm would drive CS on one pin and watch the enable of another,
    and would pass by watching a pin that never moves.
    """
    src = open(os.path.join(ROOT, "src", "project.v"), encoding="utf-8").read()
    got = {}
    for name in ("MISO_PIN", "CS_PIN"):
        m = re.search(r"parameter\s+integer\s+%s\s*=\s*(\d+)" % name, src)
        if not m:
            raise AssertionError(
                "%s not found in src/project.v -- the corpus cannot confirm "
                "its pin map against the RTL, so it must not run." % name)
        got[name] = int(m.group(1))
    if got["MISO_PIN"] != P_T_MISO or got["CS_PIN"] != P_T_CS:
        raise AssertionError(
            "PIN MAP DISAGREES WITH THE RTL: derived MISO=%d CS=%d, "
            "project.v MISO_PIN=%d CS_PIN=%d. One of them moved."
            % (P_T_MISO, P_T_CS, got["MISO_PIN"], got["CS_PIN"]))
    return got


RTL_PINS = _assert_rtl_agrees()


# ---------------------------------------------------------------------------
# THE PROGRAMS
# ---------------------------------------------------------------------------
# Each builder returns (image_bytes, expect), where `expect` names the ports
# this program MUST make non-constant. That is the precondition Wilson asked
# for, and it is per-program because the ruled map leaves three of the five
# lanes unable to drive any `uio` pin at all.

def _park(off):
    """A live-but-inert lane: re-arm that does not loop, naming no real pin."""
    return act(OP_REARM, 0, 0, 500), off + ACT_BYTES


ASSEMBLED = []          # every program _assemble has built, for the audit


def _assemble(seqs, headers_spec, park_at, queues=None):
    """seqs: list of (lane, [(op, pin, lvl, dly)]). Returns image bytes.

    ⛔⛔ `queues` IS {lane: tx_queue}, AND IT WAS MISSING. Every corpus action
    was emitted with the default `q = 0`, so `build_all5` -- which has THREE
    shifting lanes -- had all three drawing from TX queue 0. Consumption order
    is the EDF interleave, so whichever lane dispatched first took the byte and
    the other two got whatever was left: the head-of-line blocking that
    per-lane queues exist to prevent, in the one program that has three
    transmitters. `model/pe_asm.check_queue_ownership` REJECTS exactly that,
    and it had never been run against a corpus program.
    ⚠ INVISIBLE UNTIL RULING 0. No bench fed the host channel, so all three
    lanes drew nothing from queue 0 and shifted zeros; the collision could not
    produce a wrong byte because there were no bytes.
    """
    queues = queues or {}
    # ⭐ WHAT WAS ASSEMBLED IS RECORDED, so the programs can be AUDITED rather
    # than only built. `audit_programs()` below runs the loader's own rules
    # over this, which is how the two defects ruling 0 uncovered are kept out:
    # a shifting lane whose clock pin is its data pin (1.6x) and two shifting
    # lanes sharing a TX queue. Both were present here for the lifetime of the
    # corpus and neither was checkable, because the builders returned only
    # bytes.
    ASSEMBLED.append({"seqs": seqs, "spec": dict(headers_spec),
                      "queues": dict(queues)})
    prog, base, off = [], {}, ACT_BASE
    for lane, seq in seqs:
        base[lane] = off
        # ⛔ COUNT IS NOW PER ACTION, with 8 as the default this always used.
        # It had to become explicit for the self-clocked shifts: `count` is the
        # BIT COUNT there, and the two opcodes read it differently (SHIFT
        # compares the pre-increment pointer against `a_cnt`, SHIFTIN against
        # `a_cnt - 1`), so a hardcoded 8 would have made a clocked transmit
        # nine bits long and a clocked ACK eight.
        for entry in seq:
            op, pin, lvl, dly = entry[:4]
            cnt = entry[4] if len(entry) > 4 else 8
            prog.append(act(op, pin, lvl, dly, count=cnt,
                            q=queues.get(lane, 0)))
            off += ACT_BYTES
    lp = off
    prog.append(act(OP_REARM, 0, 0, 500))
    headers = []
    for lane in range(N_LANES):
        if lane in base:
            pin, clkpin, mode, t, dsched, dtol = headers_spec[lane]
            headers.append(hdr(pin, clkpin, mode, t, 2, dsched, dtol,
                               base[lane]))
        else:
            headers.append(hdr(park_at, park_at, MODE_OD, 500, 2, 200, 240, lp))
    img = b"".join(headers) + b"".join(prog)
    assert len(img) <= (1 << AW), "image %d > 2**AW" % len(img)
    return img


def build_i2c(d: int = D_FM_SHIPPABLE):
    """I2C on the OPEN-DRAIN uio pins, with the I2C FRAM peer in the loop.

    ⛔⛔ THE DELAY WAS 9 AND IS NOW `D_FM_SHIPPABLE` (ruling D5), AND THE CHIP
    NO LONGER RUNS IT AT 9. D1 refuses a clocked open-drain action with
    `d <= SDA_HOLD`, so at d = 9 this program sets `config_err` on its first
    clocked SHIFT and the engine halts: MEASURED as ZERO SCL transitions in
    60,000 cycles, against 2,667 at d = 16. The old delay was never a legal
    I2C delay -- 9 cycles is a 2.7 MHz clock, above every mode in UM10204 --
    and the clamp that used to make it merely non-compliant is gone.
    ⚠ IT COSTS SIM TIME AND COVERAGE REACH, which is reported rather than
    absorbed: the bit period goes from 24 cycles to 146, so a fixed `+NCYC`
    buys ~6x fewer transactions. See `docs/SPEC_V4_CLOCKED_HIGH_PHASE.md`.

    ⭐ THIS IS THE PROGRAM THAT MOVES `uio_oe`. Open-drain never drives high:
    the engine holds `pin_out = 0` and modulates `pin_oe = ~level`, so a 1 in
    the program RELEASES the line and the peer's pull-up (or its ACK pull-low)
    decides the value. That makes `uio_oe[SCL]`/`uio_oe[SDA]` the signal and
    `uio_out` constant-0 on those bits BY CONSTRUCTION -- so this program's
    precondition is `uio_oe`, not `uio_out`.
    """
    # ⛔⛔ REWRITTEN TO THE SELF-CLOCKED SHIFTS, and the old idiom was not
    # merely verbose -- it was WRONG. It read:
    #       (OP_SHIFT, P_SDA, 1, d),   # "a bit, clocked on SCL"
    #       (OP_SHIFT, P_SDA, 0, d),
    # Two SHIFT actions, one per clock level -- but EACH ONE advances `tx_bitp`
    # and shifts `l_tx`, so the pair consumed TWO payload bits per clock cycle
    # and put only the first on the wire. Invisible for the corpus's whole life
    # because no bench fed the host channel, so every lane shifted zeros and
    # losing alternate bits changed nothing observable -- the same blindness
    # that hid the 1.6x alias defect.
    # ⭐ Now ONE action carries the whole byte, one payload bit per clock, and
    # the ACK is a one-bit clocked receive sampled on the OBSERVED SCL rise.
    seq = [
        (OP_START, P_SDA, 0, d),      # START: SDA low while SCL high
        (OP_SHIFT, P_SDA, SELF_CLOCKED, d, 7),    # a whole byte, 8 bits
        (OP_SHIFTIN, P_SDA, SELF_CLOCKED, d, 1),  # the ACK slot, 1 bit
        (OP_READBIT, P_SDA, 0, d),
        (OP_STOP, P_SDA, 1, d),       # STOP
        (OP_REARM, 0, 1, d),
    ]
    img = _assemble([(0, seq)],
                    {0: (P_SDA, P_SCL, MODE_OD, d, 2 * d, 3 * d)},
                    park_at=P_SCL)
    return img, {"uio_oe": True, "uio_out": False, "uo_out": False,
                 "od_pins": (P_SCL, P_SDA)}


def build_spi_master(d: int = 7):
    """SPI master: SCLK/MOSI/CS on `uo_out`, MISO read from the FRAM peer.

    ⚠ ITS PRECONDITION IS NOT `uio_oe`. Under the ruled map the master's three
    driven pins are push-pull and live on `uo_out`, and its only `uio` pin is
    MISO, an INPUT. So this program moves `uo_out` and `uio_in` and must NOT be
    asked to move `uio_oe` -- a precondition demanding that here would be
    unsatisfiable, and "fixing" it by putting the master on `uio` would violate
    the two-bank ruling.
    """
    seq = [
        (OP_LEVEL, P_M_CS, 0, d),       # select
        # ⛔ SAME REWRITE AS build_i2c, same defect: the old (level=1, level=0)
        # SHIFT pair advanced `tx_bitp` twice per clock. ⭐ SPI MODE 0 IS THE
        # SUPPORTED ORDER here -- data settles with the clock low and is read on
        # the rise -- which is what the self-clocked shift emits. Modes 1 and 2
        # would need the reverse order and stay on the unclocked idiom.
        (OP_SHIFT, P_M_MOSI, SELF_CLOCKED, d, 7),    # a whole command byte
        (OP_SHIFTIN, P_M_MISO, SELF_CLOCKED, d, 8),  # a whole reply byte
        (OP_READBIT, P_M_MISO, 0, d),
        (OP_LEVEL, P_M_CS, 1, d),       # deselect
        (OP_REARM, 0, 1, d),
    ]
    img = _assemble([(0, seq)],
                    {0: (P_M_MOSI, P_M_SCLK, MODE_PP, d, 2 * d, 3 * d)},
                    park_at=P_SCL)
    return img, {"uio_oe": False, "uio_out": False, "uo_out": True,
                 "uio_in": True, "od_pins": (P_SCL,)}


def build_spi_target(d: int = 6):
    """SPI-target: the DUT drives the TRI-STATE MISO; the peer drives SCK/CS/MOSI.

    ⭐⭐ THIS IS THE ASYNC-CLEAR PROGRAM. `uio_oe[MISO]` does not come from the
    engine directly -- it comes from `miso_oe_q`, a flop on
    `always @(posedge clk or posedge cs_deasserted or negedge rst_n)`. The lane
    must actually assert `e_pin_oe[MISO]` or that flop's D side is always 0 and
    the whole arm is vacuous, which is why the MISO drive below is SHIFT in
    push-pull mode rather than a release-only sequence.
    """
    seq = [
        (OP_SHIFT, P_T_MISO, 1, d),     # drive MISO, clocked on the lane's clk
        (OP_SHIFT, P_T_MISO, 0, d),
        (OP_LEVEL, P_T_MISO, 1, d),     # hold it driven, so CS can clear it
        (OP_LEVEL, P_T_MISO, 0, d),
        (OP_REARM, 0, 1, d),
    ]
    # ⛔⛔ `PIN_NONE` AS THE CLOCK PIN, AND IT USED TO BE `P_T_MISO` -- THE
    # LANE'S OWN DATA PIN. `OP_SHIFT` writes the data pin and then the clock
    # pin, clock SECOND, so with the two aliased the clock write overwrote
    # every data bit with the action's level field: at level 0, every 1 bit
    # became a 0. This program is the ONLY one that exercises the tri-state
    # MISO and the async-clear path, and it was transmitting corrupted data
    # the whole time -- invisibly, because no bench fed the queue, so the
    # shift register was all zeros and losing the 1 bits changed nothing.
    # ⭐ PIN_NONE IS THE RIGHT ANSWER, NOT A SPARE PIN: an SPI **TARGET** does
    # not drive a clock at all -- the master supplies SCK -- so the lane has
    # nothing legitimate to point `clkpin` at. `pe_engine`'s `clk_real` guard
    # (added with this fix) is what makes the non-driving code safe rather
    # than an out-of-range write.
    img = _assemble([(0, seq)],
                    {0: (P_T_MISO, PIN_NONE, MODE_PP, d, 2 * d, 3 * d)},
                    park_at=P_SCL)
    return img, {"uio_oe": True, "uio_out": True, "uo_out": False,
                 "od_pins": (P_SCL,)}


def build_uart_rx(d: int = 11, timeout: int = 300):
    """UART-rx through EDGE CAPTURE: ARM on the RX input, peer drives it.

    The lane arms on a FALL of `uio[RX]` (the UART start bit) and then runs a
    sampling sequence rebased on the captured edge. `uio_in` is the signal;
    the lane's own output is on `uo_out`, which is where a UART-rx host view
    would land.
    """
    seq = [
        (OP_ARM, P_RX, 0, timeout),     # arm on FALL = start bit
        (OP_LEVEL, P_TX, 1, d),         # a visible marker on uo_out
        (OP_LEVEL, P_TX, 0, d),
        (OP_REARM, 0, 1, d),
    ]
    img = _assemble([(0, seq)],
                    {0: (P_TX, P_TX, MODE_PP, d, 2 * d, 3 * d)},
                    park_at=P_SCL)
    return img, {"uio_oe": False, "uio_out": False, "uo_out": True,
                 "uio_in": True, "od_pins": (P_SCL,)}


def build_all5(d: int = 9, d0: int = D_FM_SHIPPABLE):
    """All five lanes live at once -- pin-feasible under the two-bank ruling.

    ⭐ `bank_need` for the full set is `(8, 4)`: both banks exactly full. This
    is the program that exercises the scheduler WITH the protocol pins moving,
    rather than the opcode-coverage census that moves only `uo_out`.

    ⛔⛔ TWO DELAYS, AND THE SPLIT IS THE POINT (ruling D5). D1 refuses a
    CLOCKED OPEN-DRAIN action with `d <= SDA_HOLD`, and lane 0 is the only lane
    here that is both -- lane 1 names `PIN_NONE` as its clock so nothing it
    does is clocked, lane 2 is push-pull, and lanes 3 and 4 run LEVEL/ARM/
    READBIT only. ⇒ Lane 0 moves to a mode-legal `d0` and the OTHER FOUR STAY
    AT 9, because this image's job is SCHEDULER CONTENTION: raising all five to
    70 would cut the dispatch rate ~7x and quietly turn the stress image into a
    relaxed one. The asymmetry (70 against 9..13) is also a harder EDF mix than
    the arithmetic-progression periods it replaces.
    ⚠ MEASURED, NOT ASSUMED, that lane 0 was the only one refused: at the old
    `d = 9` this program produced ZERO SCL transitions on lane 0's clock pin in
    60,000 cycles.
    """
    # ⛔⛔ LANES 0 AND 2 ARE THE OTHER TWO OF THE FOUR SELF-CLOCKED SITES, and
    # this builder has its OWN sequences rather than reusing `build_i2c` /
    # `build_spi_master` -- so rewriting those two did NOT fix these. Caught by
    # checking the manifest hash instead of assuming: `corpus_all5` read
    # UNCHANGED while the decode said it had two affected lanes, and an
    # unchanged hash there would have meant the two sites were still emitting
    # the old two-bits-per-clock pair through the new clocked path.
    # ⚠ LANE 1 IS **NOT** ONE OF THEM: its clock pin is PIN_NONE, so
    # `clk_real` is false and its `level = 1` keeps the old meaning. It stays
    # exactly as it was -- which is the UART/SPI-target case the ruling asked
    # be defined, visible here in a program.
    s_i2c = [(OP_START, P_SDA, 0, d0),
             (OP_SHIFT, P_SDA, SELF_CLOCKED, d0, 7),     # a whole byte
             (OP_SHIFTIN, P_SDA, SELF_CLOCKED, d0, 1),   # the ACK slot
             (OP_STOP, P_SDA, 1, d0),
             (OP_REARM, 0, 1, d0)]
    s_tgt = [(OP_SHIFT, P_T_MISO, 1, d + 1), (OP_LEVEL, P_T_MISO, 0, d + 1),
             (OP_REARM, 0, 1, d + 1)]
    s_mst = [(OP_LEVEL, P_M_CS, 0, d + 2),
             (OP_SHIFT, P_M_MOSI, SELF_CLOCKED, d + 2, 7),
             (OP_SHIFTIN, P_M_MISO, SELF_CLOCKED, d + 2, 8),
             (OP_LEVEL, P_M_CS, 1, d + 2),
             (OP_REARM, 0, 1, d + 2)]
    s_tx  = [(OP_LEVEL, P_TX, 0, d + 3), (OP_LEVEL, P_TX, 1, d + 3),
             (OP_REARM, 0, 1, d + 3)]
    s_rx  = [(OP_ARM, P_RX, 0, 300), (OP_READBIT, P_RX, 0, d + 4),
             (OP_REARM, 0, 1, d + 4)]
    seqs = [(0, s_i2c), (1, s_tgt), (2, s_mst), (3, s_tx), (4, s_rx)]
    spec = {
        0: (P_SDA,    P_SCL,     MODE_OD, d0,    2 * d0,      min(3 * d0, 255)),
        # lane 1 is the SPI TARGET: no clock to drive, so PIN_NONE. It read
        # `P_T_MISO` -- its own data pin -- so OP_SHIFT's clock write
        # overwrote every data bit. See `build_spi_target`.
        1: (P_T_MISO, PIN_NONE,  MODE_PP, d + 1, 2 * (d + 1), 3 * (d + 1)),
        2: (P_M_MOSI, P_M_SCLK,  MODE_PP, d + 2, 2 * (d + 2), 3 * (d + 2)),
        # lanes 3 and 4 keep `clkpin == pin` DELIBERATELY: neither runs
        # OP_SHIFT (LEVEL/ARM/READBIT only), so the alias is a don't-care and
        # 1.6x is scoped to shifting lanes. Changing them would move two
        # programs for a hazard they cannot reach.
        3: (P_TX,     P_TX,      MODE_PP, d + 3, 2 * (d + 3), 3 * (d + 3)),
        4: (P_RX,     P_RX,      MODE_PP, d + 4, 2 * (d + 4), 3 * (d + 4)),
    }
    # ⛔⛔ ONE TX QUEUE PER TRANSMITTING LANE. All three shifting lanes used
    # the default queue 0, which is the head-of-line collision
    # `pe_asm.check_queue_ownership` refuses: consumption order is the EDF
    # interleave, so the host could not know which lane took the byte it
    # pushed. Unfed, all three drew nothing and the collision was unobservable.
    img = _assemble(seqs, spec, park_at=P_SCL,
                    queues={0: 0, 1: 1, 2: 2})
    return img, {"uio_oe": True, "uio_out": True, "uo_out": True,
                 "uio_in": True, "od_pins": (P_SCL, P_SDA)}



# ---------------------------------------------------------------------------
# `od_pins` -- THE OPEN-DRAIN INVARIANT'S SUBJECT
# ---------------------------------------------------------------------------
# Every builder names the pins ITS headers declare open-drain, so the invariant
# below is checked against what each program actually asked for rather than
# against a separately-maintained list that could drift from the programs.
# ⛔ NOTE `P_SCL` APPEARS IN EVERY PROGRAM: the parked lanes are declared
# open-drain on it, so even a program whose active lane is push-pull still has
# an open-drain pin whose invariant must hold. That is the case D2 escaped
# through -- a lane mode respected on the data pin and ignored on the clock.

# ---------------------------------------------------------------------------
# KNOWN-OPEN ARMS, with the reason stated
# ---------------------------------------------------------------------------
# ⛔⛔ AN OPEN ARM IS RECORDED, NOT QUIETLY WEAKENED. `corpus_spim`'s
# precondition -- that the FRAM peer actually answers -- FAILS, and the fix is
# not a bench fix:
#
#   1. THE PAYLOAD COMES FROM THE HOST, NOT THE PROGRAM. `l_data` is loaded
#      only at `if (host_valid) l_data[cur] <= host_data`, where
#      `host_data = uio_q1` and `host_valid = run & ui_in[0]` -- so the command
#      byte arrives on the `uio` BUS, which in this configuration is also where
#      MISO lives. The host payload path and the protocol pins share a bank.
#   2. `OP_SHIFT` SETS THE CLOCK TO THE ACTION'S OWN LEVEL FIELD and shifts in
#      the same cycle (`pin_out[l_clkpin] <= a_lvl`, then `l_data >>= 1`), so
#      whether the peer samples valid `si` at the SCK edge depends on the
#      SHIFT/clock phase the ISA intends. That is a protocol-semantics ruling.
#
# With `l_data` at its reset `8'h00` the master clocks out an invalid opcode,
# the peer stays High-Z exactly as the datasheet says it should, and `uio_in`
# is constant 0xFF. ⇒ The peer is behaving correctly; the PROGRAM cannot yet
# speak to it. Both points need a ruling, so the arm stays red with its reason.
#
# ⭐ AND IT MUST NOT BE MADE GREEN THE EASY WAY. Having the bench drive
# `uio[7:1]` as host payload WOULD make `uio_in` non-constant -- while the peer
# still never answered. That is a precondition satisfied by the wrong
# mechanism, so the check below is sharpened to the ONE BIT the peer drives:
# `uio_in[MISO]` must take both values, which only a real response can do.
OPEN = {
    "corpus_spim":
        "the FRAM peer cannot be addressed yet: the command byte must come "
        "from the HOST (l_data <- host_data, gated by ui_in[0]) over the same "
        "uio bank MISO uses, and the SHIFT/clock phase the ISA intends is "
        "unruled. The peer is correct to stay High-Z on opcode 0x00.",
}

# ports whose single BIT must vary, where a whole-port check would be gameable
BIT_PRECONDITION = {
    "corpus_spim": ("uio_in", P_M_MISO),
}

CORPUS = {
    "corpus_i2c":    (build_i2c,        "i2c"),
    "corpus_spim":   (build_spi_master, "spi"),
    "corpus_sptgt":  (build_spi_target, "tgt"),
    "corpus_uartrx": (build_uart_rx,    "rx"),
    "corpus_all5":   (build_all5,       "all"),
}
"""name -> (builder, the PEER wiring the bench must use for it)."""


#: ⛔⛔ IMAGES WHOSE LANES COLLIDE WITH THE PAD OVERRIDE, declared BY NAME with
#: the colliding LANES (ruling P5). `src/project.v` rebuilds `uio_oe[MISO_PIN]`
#: from the SPI target's own release path --
#:     uio_oe_run = (uio_oe_eng & ~(1 << MISO_PIN)) | (miso_oe_q << MISO_PIN)
#: -- so a lane that drives pin 7 has its output enable REPLACED, and pin 6 is
#: the CS **input** the release path reads. A lane on either is not measurable
#: and its pin waveform is not its own.
#: ⭐ THIS IS NOT A THEORY, IT IS WHY A CORRECTION WAS NEEDED. `ckfive` lane 3
#: reported a modal t_HIGH of 434 against a programmed 120, and that number was
#: briefly taken for a design finding before the override was identified. P4
#: re-established the control on lane 0 (pins 0/1, which collide with nothing)
#: and the record stood -- but the near-miss is the reason the collision is
#: DECLARED now rather than left to be rediscovered.
#: ⇒ An image with an undeclared collision is RED, and a declaration whose
#:   image no longer collides is RED too: both mean the map and the programs
#:   moved apart.
#: ⚠ THESE ARE STRESS AND MEASUREMENT IMAGES, NOT SHIPPABLE CONFIGURATIONS.
#: None of them is a corpus program and none claims the ruled placement; the
#: lane sets exist to saturate the scheduler and to span `d`. Listing them is
#: how that stays true on purpose instead of by accident.
PAD_COLLISION = {
    "ckfive_image.hex": (
        [3],
        "five self-clocked lanes on consecutive pin pairs, so lane 3 lands on "
        "pins 6/7 -- CS_PIN and MISO_PIN. Its clock pin is 7, whose output "
        "enable the SPI-target release path overwrites, so the lane's own "
        "clock is not what reaches the pad. MEASURED: modal t_HIGH 434 against "
        "a programmed 120. Lanes 0, 1 and 2 (pins 0/1, 2/3, 4/5) are clean and "
        "lane 0 is F4's control."),
    "ckdense_image.hex": (
        [3],
        "ruling S's must-fire subject, built on `ckod`'s consecutive-pairs "
        "layout at d = 22..25, so lane 3 is on pins 6/7 for the same reason. "
        "Harmless to its purpose: A2 bounds DISPATCH TIMING, which the "
        "bench reads from the engine, not from the overridden pad."),
    "ckod_image.hex": (
        [3],
        "the same consecutive-pairs layout, so its highest-delay lane (d = 240) "
        "is also on pins 6/7. `model/a2/gate_um10204.py` SKIPS that lane by "
        "name rather than quoting it, and the three lanes below it carry the "
        "F1 span (33, 60, 120) on their own."),
}


def pad_collisions(img):
    """Lanes in `img` whose data or clock pin collides with the pad override.

    ⭐ THE PREDICATE IS THE SAME ONE `test/measure_phases.py` USES to mark a
    lane `pad_overridden`, and both read the pin numbers from `src/project.v`
    through this module's `_assert_rtl_agrees` -- so a pin that moves in the
    RTL moves in the audit, the measurement and the pin map together.
    """
    # ⛔⛔ SCOPED TO LANES THAT CAN ACTUALLY DRIVE, and the scope is the same
    # argument `pe_asm.check_shift_clock_alias` makes about the 1.6x alias: for
    # a lane that never writes the pin, the pin assignment is a DON'T-CARE.
    # ⚠ MEASURED THE HARD WAY -- the first version of this audit flagged five
    # images whose only offender was a PARKED FILLER LANE running `OP_REARM`
    # and nothing else. Declaring those would have been five vacuous entries
    # burying the two real ones, which is how a named exemption list stops
    # being read. ⇒ The clock pin matters only for a lane that CLOCKS
    # (SHIFT/SHIFTIN), the data pin only for a lane that WRITES it.
    clk_drivers = (OP_SHIFT, OP_SHIFTIN)
    pin_writers = (OP_LEVEL, OP_SHIFT, OP_START, OP_STOP)
    ops = {}
    hdrs = {}
    for ln, h, a in dgf.walk(img):
        ops.setdefault(ln, set()).add(a["op"])
        hdrs[ln] = h
    bad = {}
    for ln, h in sorted(hdrs.items()):
        drives_clk = bool(ops[ln] & set(clk_drivers))
        writes_pin = bool(ops[ln] & set(pin_writers))
        hits = []
        if drives_clk and h["clkpin"] == P_T_MISO:
            hits.append("clock on pin %d (MISO_PIN): its output enable is "
                        "rebuilt from miso_oe_q, so the lane does not drive "
                        "its own clock" % P_T_MISO)
        if drives_clk and h["clkpin"] == P_T_CS:
            hits.append("clock on pin %d (CS_PIN): an INPUT in the ruled "
                        "two-bank map" % P_T_CS)
        if writes_pin and h["pin"] == P_T_CS:
            hits.append("data on pin %d (CS_PIN): an INPUT in the ruled map"
                        % P_T_CS)
        if hits:
            bad[ln] = hits
    return bad


def audit_pad_collisions() -> int:
    """Every image, against `PAD_COLLISION`. Undeclared or stale is RED."""
    print("  --- ruling P5: lanes colliding with the pad override ---")
    print("    project.v MISO_PIN=%d CS_PIN=%d"
          % (RTL_PINS["MISO_PIN"], RTL_PINS["CS_PIN"]))
    rc, seen = 0, set()
    imgs = sorted(glob.glob(os.path.join(HERE, "*.hex")))
    imgs = [p for p in imgs if not os.path.basename(p).startswith("probe_")]
    for p in imgs:
        name = os.path.basename(p)
        bad = pad_collisions(dgf.load(p))
        if not bad:
            continue
        if name not in PAD_COLLISION:
            print("    *** %-22s lanes %s collide and the image is NOT in"
                  % (name, sorted(bad)))
            print("        PAD_COLLISION. Either put it on the ruled map or")
            print("        declare it here with the colliding lanes named.")
            for ln, hits in sorted(bad.items()):
                for h in hits:
                    print("          lane %d: %s" % (ln, h))
            rc = 1
            continue
        seen.add(name)
        want, _why = PAD_COLLISION[name]
        if sorted(bad) != sorted(want):
            print("    *** %-22s declares lanes %s but lanes %s collide"
                  % (name, sorted(want), sorted(bad)))
            rc = 1
            continue
        print("    %-22s DECLARED non-legal, lanes %s" % (name, sorted(want)))
    for name in sorted(set(PAD_COLLISION) - seen):
        print("    *** %s is declared as colliding but no lane of it does"
              % name)
        print("        -- either the image or the pin map moved")
        rc = 1
    if rc == 0:
        print("    %d image(s) scanned, %d declared, every collision named"
              % (len(imgs), len(seen)))
    # ⛔⛔ PRICE IT. The predicate's whole value is its SCOPE -- a driving lane
    # on an overridden pin is a finding, a parked one is a don't-care -- so
    # both directions are probed on hand-built images rather than left to the
    # shipped set, which happens to contain only one of the two shapes.
    # ⚠ IT HAS ALREADY FIRED FOR REAL, five times, on the first version of
    # this audit: `ckdegen`, `ckdegen2` and the three `ckhold` images were all
    # reported because a parked filler lane sat on pin 6. That is what sent
    # `build_ckhold`'s fillers to PIN_NONE and scoped the predicate.
    print("    --- must-fire: the scope holds in both directions ---")
    base = bytearray(ACT_BASE + 4 * ACT_BYTES)
    for ln in range(1, N_LANES):
        base[ln * HDR_BYTES:(ln + 1) * HDR_BYTES] = \
            hdr(PIN_NONE, PIN_NONE, 1, 500, 2, 200, 240, ACT_BASE)
    cases = [
        ("a SHIFT lane clocked on MISO_PIN", P_T_MISO, P_T_SCLK,
         (OP_SHIFT, P_T_SCLK, SELF_CLOCKED), True),
        ("a REARM-only lane sitting on CS_PIN", PIN_NONE, P_T_CS,
         (OP_REARM, 0, 1), False),
        ("a LEVEL lane writing CS_PIN", PIN_NONE, P_T_CS,
         (OP_LEVEL, P_T_CS, 1), True),
    ]
    for label, clkpin, pin, (op, apin, lvl), want in cases:
        img = bytearray(base)
        img[0:HDR_BYTES] = hdr(pin, clkpin, 1, 70, 2, 140, 210, ACT_BASE)
        img[ACT_BASE:ACT_BASE + ACT_BYTES] = act(op, apin, lvl, 70, count=7)
        img[ACT_BASE + ACT_BYTES:ACT_BASE + 2 * ACT_BYTES] = \
            act(OP_REARM, 0, 1, 70)
        got = bool(pad_collisions(bytes(img)))
        ok = (got == want)
        print("      %-44s %s"
              % (label, "ok" if ok else
                 "*** wanted %s" % ("a collision" if want else "none")))
        if not ok:
            rc = 1
    return rc


def write_pinmap_vh() -> str:
    """Emit the pin map as Verilog, so the bench does not hold a SECOND COPY.

    ⛔⛔ THIS IS THE `lane_digest` LESSON APPLIED TO A PIN MAP. The bench needs
    the same twelve indices the programs are built from, and hand-writing them
    in Verilog would be two tables that must agree -- the precise shape that
    let `periodic_equivalence` certify a lane table nobody was using any more.
    A pin map that drifts is worse than a wrong one: the program drives SDA and
    the bench watches SCL, and every check passes while measuring nothing.
    ⇒ GENERATED. Per the standing rule, no edit to this file is cosmetic:
      regenerate it and re-run the gate.
    """
    out = os.path.join(HERE, "pinmap.vh")
    lines = [
        "/* pinmap.vh -- GENERATED by test/corpus.py. DO NOT EDIT.",
        " *",
        " * The ruled two-bank pin map: `uio` carries inputs, open-drain and",
        " * tri-state outputs; `uo_out` carries push-pull. Derived by walking",
        " * the shipped lane order, and checked against project.v's MISO_PIN",
        " * and CS_PIN at generation time.",
        " */",
    ]
    for nm, val in (("P_M_MISO", P_M_MISO), ("P_SCL", P_SCL), ("P_SDA", P_SDA),
                    ("P_RX", P_RX), ("P_T_SCLK", P_T_SCLK),
                    ("P_T_MOSI", P_T_MOSI), ("P_T_CS", P_T_CS),
                    ("P_T_MISO", P_T_MISO), ("P_TX_UO", P_TX - N_UIO),
                    ("P_M_SCLK_UO", P_M_SCLK - N_UIO),
                    ("P_M_MOSI_UO", P_M_MOSI - N_UIO),
                    ("P_M_CS_UO", P_M_CS - N_UIO)):
        lines.append("localparam integer %-12s = %d;" % (nm, val))
    with open(out, "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return out


def audit_programs() -> int:
    """⛔⛔ EVERY CORPUS PROGRAM AGAINST THE LOADER'S OWN RULES.

    `model/pe_asm.py` holds the admissibility checks the toolchain applies, and
    they had NEVER been run against a corpus program -- so the corpus carried
    two violations of rules this project had already written down:

      1.6x  `build_spi_target` and `build_all5` lane 1 named `P_T_MISO` as
            BOTH the data and the clock pin of a SHIFTING lane. OP_SHIFT writes
            the data pin and then the clock pin, so every 1 bit was overwritten
            with the action's level field. That program is the only one
            exercising the tri-state MISO and the async-clear path.
      queue `build_all5`'s THREE shifting lanes all drew from TX queue 0,
            which is the head-of-line collision per-lane queues exist to
            prevent.

    ⚠ BOTH WERE UNOBSERVABLE UNTIL RULING 0. No bench fed the host channel, so
    every shift ran on an all-zero register: losing the 1 bits changed nothing
    and three lanes colliding over an empty queue produced no wrong byte.
    ⇒ Running the checks here is the structural guard. Writing the images is
      not the same as checking them, exactly as `main()` says about the
      preconditions.
    """
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "model"))
    import pe_asm
    rc = 0
    print()
    print("  --- the loader's rules, applied to every corpus program ---")
    print("    %-15s %-10s %s" % ("program", "verdict", "detail"))
    for name, (fn, _peer) in sorted(CORPUS.items()):
        del ASSEMBLED[:]
        fn()
        if not ASSEMBLED:
            print("    %-15s *** NOT RECORDED -- the builder bypassed"
                  " _assemble" % name)
            rc = 1
            continue
        a = ASSEMBLED[-1]
        lanes, headers = {}, {}
        for lane, seq in a["seqs"]:
            q = a["queues"].get(lane, 0)
            # ⛔ TOLERATES THE OPTIONAL PER-ACTION COUNT. The self-clocked
            # shifts carry a 5th element, and this audit is the ONLY path that
            # feeds the corpus to the toolchain's own rules -- so if it could
            # not parse an action shape, the new actions would go UNAUDITED by
            # the checks that exist to catch exactly this class of program.
            lanes[lane] = [(e[0], e[1], e[2], e[3], q) for e in seq]
        for lane, sp in a["spec"].items():
            headers[lane] = sp
        try:
            pe_asm.check_queue_ownership(lanes)
            pe_asm.check_shift_clock_alias(lanes, headers)
            print("    %-15s %-10s %s" % (name, "ok", "queue ownership + 1.6x"))
        except pe_asm.Reject as e:
            print("    %-15s *** REJECTED  %s" % (name, str(e)[:70]))
            rc = 1
    if rc:
        print("    ⛔ A CORPUS PROGRAM THE TOOLCHAIN WOULD REFUSE IS NOT A")
        print("       WITNESS FOR ANYTHING. Fix the program, not the check.")
    # ⛔⛔ PRICED. Five programs passing says nothing about whether this audit
    # can fail -- and it is reporting on two defects it did NOT catch for the
    # whole life of the corpus, because it did not exist. The two rejections
    # below reconstruct exactly those defects.
    print("    --- must-fire: the audit rejects what it claims to ---")
    bad = [
        ("a SHIFT lane whose clk pin is its data pin",
         {0: [(OP_SHIFT, P_T_MISO, 1, 6, 0)]},
         {0: (P_T_MISO, P_T_MISO, MODE_PP, 6, 12, 18)},
         "OP_SHIFT"),
        ("two SHIFT lanes sharing TX queue 0",
         {0: [(OP_SHIFT, P_SDA, 1, 9, 0)],
          1: [(OP_SHIFT, P_T_MISO, 1, 9, 0)]},
         {0: (P_SDA, P_SCL, MODE_OD, 9, 18, 27),
          1: (P_T_MISO, PIN_NONE, MODE_PP, 9, 18, 27)},
         "queue 0"),
    ]
    for label, lanes_b, headers_b, needle in bad:
        try:
            pe_asm.check_queue_ownership(lanes_b)
            pe_asm.check_shift_clock_alias(lanes_b, headers_b)
            print("      *** %-44s ACCEPTED -- the audit is blind" % label)
            rc = 1
        except pe_asm.Reject as e:
            if needle in str(e):
                print("      %-44s rejected, naming %r" % (label, needle))
            else:
                print("      *** %-44s rejected but did not name %r"
                      % (label, needle))
                rc = 1
    return rc


def main() -> int:
    print("THE TRACE CORPUS")
    print("=" * 70)
    print("  ruled pin map, derived from PINS_DIR in shipped lane order:")
    for (lane, sig), p in sorted(PIN.items(), key=lambda kv: kv[1]):
        bank = "uio[%d]" % p if p < N_UIO else "uo_out[%d]" % (p - N_UIO)
        print("    pin %2d  %-10s %-16s %s" % (p, bank, lane, sig))
    print("  RTL agrees: project.v MISO_PIN=%d CS_PIN=%d"
          % (RTL_PINS["MISO_PIN"], RTL_PINS["CS_PIN"]))
    print()
    rc = 0
    for name, (fn, peer) in sorted(CORPUS.items()):
        img, expect = fn()
        out = os.path.join(HERE, name + ".hex")
        with open(out, "w", encoding="ascii") as fh:
            for b in img:
                fh.write("%02x\n" % b)
        want = ",".join(k for k, v in sorted(expect.items()) if v)
        print("  %-15s %3d bytes  peer=%-4s must move: %s"
              % (name, len(img), peer, want))
    print()
    print("  pin map for the bench -> %s" % write_pinmap_vh())
    print()
    rc |= audit_programs()
    print()
    rc |= audit_pad_collisions()
    print()
    print("  ⛔ writing the image is not running it. The preconditions above")
    print("     are CLAIMS until test/gate_corpus_trace.py checks each one")
    print("     against the trace that program actually produced.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
