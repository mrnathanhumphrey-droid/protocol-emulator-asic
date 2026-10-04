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

# ⛔ ONE ENCODER. `hdr`/`act` are IMPORTED, never re-implemented here: two
# copies of a bit-packer is the exact failure `lane_digest` exists to catch,
# and a corpus encoded by a second builder would be a different ISA.
from make_smoke_image import (            # noqa: E402
    ACT_BASE, ACT_BYTES, AW, HDR_BYTES, N_LANES,
    OP_ARM, OP_LEVEL, OP_READBIT, OP_REARM, OP_SHIFT, OP_SHIFTIN, OP_START,
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


def _assemble(seqs, headers_spec, park_at):
    """seqs: list of (lane, [(op, pin, lvl, dly)]). Returns image bytes."""
    prog, base, off = [], {}, ACT_BASE
    for lane, seq in seqs:
        base[lane] = off
        for op, pin, lvl, dly in seq:
            prog.append(act(op, pin, lvl, dly, count=8))
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


def build_i2c(d: int = 9):
    """I2C on the OPEN-DRAIN uio pins, with the I2C FRAM peer in the loop.

    ⭐ THIS IS THE PROGRAM THAT MOVES `uio_oe`. Open-drain never drives high:
    the engine holds `pin_out = 0` and modulates `pin_oe = ~level`, so a 1 in
    the program RELEASES the line and the peer's pull-up (or its ACK pull-low)
    decides the value. That makes `uio_oe[SCL]`/`uio_oe[SDA]` the signal and
    `uio_out` constant-0 on those bits BY CONSTRUCTION -- so this program's
    precondition is `uio_oe`, not `uio_out`.
    """
    seq = [
        (OP_START, P_SDA, 0, d),      # START: SDA low while SCL high
        (OP_SHIFT, P_SDA, 1, d),      # a bit, clocked on SCL (the lane's clkpin)
        (OP_SHIFT, P_SDA, 0, d),
        (OP_SHIFTIN, P_SDA, 0, d),    # release to read the ACK
        (OP_READBIT, P_SDA, 0, d),
        (OP_STOP, P_SDA, 1, d),       # STOP
        (OP_REARM, 0, 1, d),
    ]
    img = _assemble([(0, seq)],
                    {0: (P_SDA, P_SCL, MODE_OD, d, 2 * d, 3 * d)},
                    park_at=P_SCL)
    return img, {"uio_oe": True, "uio_out": False, "uo_out": False}


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
        (OP_SHIFT, P_M_MOSI, 1, d),     # clock a command bit out
        (OP_SHIFT, P_M_MOSI, 0, d),
        (OP_SHIFTIN, P_M_MISO, 0, d),   # release + sample the peer
        (OP_READBIT, P_M_MISO, 0, d),
        (OP_LEVEL, P_M_CS, 1, d),       # deselect
        (OP_REARM, 0, 1, d),
    ]
    img = _assemble([(0, seq)],
                    {0: (P_M_MOSI, P_M_SCLK, MODE_PP, d, 2 * d, 3 * d)},
                    park_at=P_SCL)
    return img, {"uio_oe": False, "uio_out": False, "uo_out": True,
                 "uio_in": True}


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
    img = _assemble([(0, seq)],
                    {0: (P_T_MISO, P_T_MISO, MODE_PP, d, 2 * d, 3 * d)},
                    park_at=P_SCL)
    return img, {"uio_oe": True, "uio_out": True, "uo_out": False}


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
                 "uio_in": True}


def build_all5(d: int = 9):
    """All five lanes live at once -- pin-feasible under the two-bank ruling.

    ⭐ `bank_need` for the full set is `(8, 4)`: both banks exactly full. This
    is the program that exercises the scheduler WITH the protocol pins moving,
    rather than the opcode-coverage census that moves only `uo_out`.
    """
    s_i2c = [(OP_START, P_SDA, 0, d), (OP_SHIFT, P_SDA, 1, d),
             (OP_SHIFTIN, P_SDA, 0, d), (OP_STOP, P_SDA, 1, d),
             (OP_REARM, 0, 1, d)]
    s_tgt = [(OP_SHIFT, P_T_MISO, 1, d + 1), (OP_LEVEL, P_T_MISO, 0, d + 1),
             (OP_REARM, 0, 1, d + 1)]
    s_mst = [(OP_LEVEL, P_M_CS, 0, d + 2), (OP_SHIFT, P_M_MOSI, 1, d + 2),
             (OP_SHIFTIN, P_M_MISO, 0, d + 2), (OP_LEVEL, P_M_CS, 1, d + 2),
             (OP_REARM, 0, 1, d + 2)]
    s_tx  = [(OP_LEVEL, P_TX, 0, d + 3), (OP_LEVEL, P_TX, 1, d + 3),
             (OP_REARM, 0, 1, d + 3)]
    s_rx  = [(OP_ARM, P_RX, 0, 300), (OP_READBIT, P_RX, 0, d + 4),
             (OP_REARM, 0, 1, d + 4)]
    seqs = [(0, s_i2c), (1, s_tgt), (2, s_mst), (3, s_tx), (4, s_rx)]
    spec = {
        0: (P_SDA,    P_SCL,     MODE_OD, d,     2 * d,       3 * d),
        1: (P_T_MISO, P_T_MISO,  MODE_PP, d + 1, 2 * (d + 1), 3 * (d + 1)),
        2: (P_M_MOSI, P_M_SCLK,  MODE_PP, d + 2, 2 * (d + 2), 3 * (d + 2)),
        3: (P_TX,     P_TX,      MODE_PP, d + 3, 2 * (d + 3), 3 * (d + 3)),
        4: (P_RX,     P_RX,      MODE_PP, d + 4, 2 * (d + 4), 3 * (d + 4)),
    }
    img = _assemble(seqs, spec, park_at=P_SCL)
    return img, {"uio_oe": True, "uio_out": True, "uo_out": True,
                 "uio_in": True}


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
    print("  ⛔ writing the image is not running it. The preconditions above")
    print("     are CLAIMS until test/gate_corpus_trace.py checks each one")
    print("     against the trace that program actually produced.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
