# SPDX-FileCopyrightText: © 2026 Nathan Humphrey
# SPDX-License-Identifier: Apache-2.0
"""The pin-level suite: serial readback, open-drain, and the engine at the pins.

⛔⛔ EVERY CHECK HERE IS AT THE PINS, DELIBERATELY. Nothing reads `dut.mem` or any
internal signal, so the IDENTICAL suite runs against the RTL and against the
synthesized gate-level netlist (`gl_test` in CI). A test that peeks inside passes
on RTL and cannot run on the netlist, which is where the model and the silicon
are first able to disagree.

⛔⛔⛔ THIS FILE WAS REWRITTEN BECAUSE IT HAD BEEN RED FOR SIX RUNS, and a
permanently red job trains everyone to ignore CI. Four of its five tests asserted
a SUPERSEDED LOAD PATH:

  * `uo_out` no longer echoes the load pointer. The pins are now 4 push-pull
    protocol outputs, a 3-pin serial host view and a spare, so the old pointer
    tests read `0x6F` and asserted `111 == 3`.
  * There is no "read walk" putting raw image bytes on `uo_out` one per 256
    clocks. Readback moved to the serial trio, which is the fix for the
    constructed-image FRAM write.
  * A four-raw-byte "image" is not an I2C program any more, so the open-drain
    enable never asserted and the F5 must-fire fired correctly -- on a stimulus
    that could no longer express the property.

⇒ The load-path tests are RETIRED, readback is ported onto the serial path, and
  the open-drain and engine arms now load REAL PROGRAMS from the trace corpus.

⚠ AND ONE TEST IS AN `expect_fail` RECORDING A MEASURED DEFECT, not a stylistic
choice -- see `test_readback_reaches_byte_zero`.
"""

import os
import sys

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# ⛔ THE PIN NUMBERS ARE IMPORTED, NOT RESTATED. `test/corpus.py` derives the
# two-bank map and checks it against project.v's own MISO_PIN/CS_PIN at import.
# A hand-written copy here would be the table that drifts, and a drifted pin map
# passes every check while watching the wrong wire.
from corpus import P_SCL, P_SDA                      # noqa: E402

CLK_NS = 20                        # 50 MHz, matching info.yaml clock_hz
PIN_PROG, PIN_WR, PIN_PTR = 7, 6, 5

# the 3-pin serial host view, `uo_out` indices (project.v SER_DATA/STRB/VLD)
SER_DATA, SER_STRB, SER_VLD = 4, 5, 6
PROTO_LO, PROTO_HI = 0, 3          # uo_out[3:0] = the 4 push-pull protocol pins

FRAME_BITS = 9                     # 8 payload bits LSB-first + a marker bit
MARK_STATUS, MARK_PAYLOAD = "1", "0"


def ctrl(prog=0, wr=0, ptr=0):
    return (prog << PIN_PROG) | (wr << PIN_WR) | (ptr << PIN_PTR)


async def start(dut):
    dut._log.info("start: 50 MHz, reset low for 10 cycles")
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)


async def write_byte(dut, val, offset=0):
    """One load write. `wr` is held several clocks because it is treated as an
    ASYNCHRONOUS pin strobe: two flops to resolve metastability, a third to see
    the edge. `offset` nudges the pulse to exercise exactly that."""
    dut.uio_in.value = val
    dut.ui_in.value = ctrl(prog=1, wr=0)
    await ClockCycles(dut.clk, 3)
    dut.ui_in.value = ctrl(prog=1, wr=1)
    await ClockCycles(dut.clk, 3 + offset)
    dut.ui_in.value = ctrl(prog=1, wr=0)
    await ClockCycles(dut.clk, 3)


async def load_image(dut, img):
    """Pointer-reset, then write every byte. Load mode only, pins only."""
    dut.ui_in.value = ctrl(prog=1, ptr=1)
    await ClockCycles(dut.clk, 3)
    dut.ui_in.value = ctrl(prog=1)
    await ClockCycles(dut.clk, 2)
    for b in img:
        await write_byte(dut, b)


def read_hex(name):
    """A corpus image, one hex byte per line. ⭐ The SAME images the two-simulator
    trace corpus uses, so this suite and that comparison speak about the same
    programs rather than about two sets of bytes that happen to share a name."""
    path = os.path.join(HERE, name)
    with open(path, encoding="ascii") as fh:
        return [int(t, 16) for t in fh.read().split()]


def bit(binstr, idx):
    """One bit of a port, X-tolerant. ⛔ `int(value)` RAISES on a port carrying
    X -- it killed the first version of the serial decoder outright -- and at
    gate level X on a pin is a thing that happens. Read the binstr instead and
    decide explicitly what to do about an unknown."""
    return binstr[len(binstr) - 1 - idx]


async def harvest_frames(dut, ncyc):
    """Decode the 3-pin serial stream into frames, framing on `valid`.

    ⛔⛔ FRAMED ON THE `valid` EDGE, NOT A FIXED STRIDE. `ser_v` is high only
    while a frame shifts, so its rising edge IS the frame boundary. Chunking the
    strobed bits into fixed groups of nine assumes the harvest began exactly at a
    boundary; it does not, and the whole stream decoded one bit out -- image
    bytes appeared labelled as status frames.

    Returns [(marker, payload)] with payload None where any bit was unknown.
    """
    frames, cur, prev_v = [], [], "0"
    for _ in range(ncyc):
        await ClockCycles(dut.clk, 1)
        b = str(dut.uo_out.value)
        d, st, v = bit(b, SER_DATA), bit(b, SER_STRB), bit(b, SER_VLD)
        if v not in "01" or st not in "01":
            continue                       # the trio itself is unknown: skip
        if v == "1" and prev_v == "0":
            cur = []
        if v == "1" and st == "1":
            cur.append(d)
        if v == "0" and prev_v == "1":
            if len(cur) == FRAME_BITS:
                if any(c not in "01" for c in cur):
                    frames.append((cur[8] if cur[8] in "01" else "?", None))
                else:
                    pay = 0
                    for k in range(8):
                        pay |= int(cur[k]) << k
                    frames.append((cur[8], pay))
            cur = []
        prev_v = v
    return frames


def payloads(frames):
    return [p for m, p in frames if m == MARK_PAYLOAD]


async def rewind_readback(dut):
    """Return the readback walk to the start WITHOUT losing the image.

    ⭐ `rb_ptr` is cleared only by `rst_n`, and the program store is DELIBERATELY
    UNRESET (it is allowlisted in `model/gate_reset_audit.py` precisely so a read
    past the loaded region returns X rather than a plausible 0). So a reset
    rewinds the readback pointer and keeps the image -- which is also why
    readback has to be rewound at all: it streams CONCURRENTLY with loading, so
    by the time the last byte is written the walk is already past it.
    """
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 4)
    dut.rst_n.value = 1
    dut.ui_in.value = ctrl(prog=1)
    await ClockCycles(dut.clk, 2)


# =====================================================================
# 1. load mode releases every `uio` -- kept from the old suite, still true
# =====================================================================
@cocotb.test()
async def test_uio_released_during_prog(dut):
    """Every `uio` is an INPUT throughout load mode, which is what lets the 8
    protocol pins double as the load data port at zero pin cost.

    ⭐ KEPT UNCHANGED: it was the one test of the five that still passed, and it
    is now also the F2 property's pin-level witness -- the engine clears
    `pin_oe` in its `!run` branch, so the release happens behind the flop rather
    than through a combinational mux on a raw asynchronous input.
    """
    await start(dut)
    dut.ui_in.value = ctrl(prog=1)
    await ClockCycles(dut.clk, 2)
    for _ in range(40):
        oe = str(dut.uio_oe.value)
        assert set(oe) <= set("0"), "uio_oe = %s during load mode; must be all 0" % oe
        await ClockCycles(dut.clk, 1)
    dut._log.info("all 8 uio released for the whole of load mode")


# =====================================================================
# 2. the protocol outputs idle HIGH in load mode
# =====================================================================
@cocotb.test()
async def test_protocol_outputs_idle_high_in_load(dut):
    """In load mode the 4 push-pull protocol outputs are HELD AT IDLE (high).

    `uo_out` cannot release -- it has no enable -- so idle-high is forced rather
    than chosen, and it is what stops the load phase looking like a START
    condition or a clock edge to an attached peer. Readback deliberately does
    NOT go out on these pins; it goes out on the serial trio.
    """
    await start(dut)
    dut.ui_in.value = ctrl(prog=1)
    await ClockCycles(dut.clk, 4)
    for _ in range(60):
        b = str(dut.uo_out.value)
        got = "".join(bit(b, i) for i in range(PROTO_HI, PROTO_LO - 1, -1))
        assert got == "1111", "protocol outputs = %s in load mode, want 1111" % got
        await ClockCycles(dut.clk, 1)
    dut._log.info("uo_out[3:0] held at 1111 for the whole of load mode")


# =====================================================================
# 3. the serial readback walks the image in order
# =====================================================================
@cocotb.test()
async def test_serial_readback_walks_the_image(dut):
    """RUNG 1, PORTED: the loaded image is OBSERVABLE AT THE PINS, over the
    3-pin serial host view.

    ⭐ This is what makes "provably loaded correctly" checkable from outside.
    The old test read raw bytes off `uo_out`, which is no longer what that port
    carries; the readback moved to the serial trio and is framed, alternating a
    payload frame with a sticky STATUS frame so liveness is in the stream even
    when no payload is moving.

    ⚠ THE ASSERTION STARTS AT image[1] AND DROPS THE FIRST FRAME, AND NEITHER IS
    A CONVENIENCE. Byte 0 is not reachable through this path, and the first
    payload frame carries data from no requested address -- both measured, both
    recorded in `test_readback_reaches_byte_zero` below. This test asserts what
    the hardware guarantees today; that one asserts what it should.
    """
    await start(dut)
    img = [0xAA, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]
    await load_image(dut, img)
    await rewind_readback(dut)

    frames = await harvest_frames(dut, 900)
    pay = payloads(frames)
    known = [p for p in pay if p is not None]
    dut._log.info("frames=%d payload frames=%d known=%s"
                  % (len(frames), len(pay), [hex(p) for p in known]))

    assert len(frames) >= 8, "only %d frames in 900 cycles" % len(frames)

    # ⚠ THE FIRST PAYLOAD FRAME IS DISCARDED, AND IT IS THE SAME DEFECT. The
    # load-mode branch queues the frame from `s_rdata` BEFORE its own read
    # lands, so frame 1 carries whatever that register held from the previous
    # walk -- X on a cold part, or a stale byte after a rewind (measured: 0x33
    # where the image's second byte is 0x22). It is not a sampling artefact of
    # this bench: the frame genuinely carries data from no requested address.
    want = img[1:]
    got = known[1:1 + len(want)]
    assert got == want, ("serial readback after the stale first frame = %s, "
                         "image[1:] = %s"
                         % ([hex(x) for x in got], [hex(x) for x in want]))

    # the status frames must alternate with the payloads and carry the alive bit
    marks = [m for m, _ in frames]
    assert MARK_STATUS in marks, "no STATUS frame in the stream"
    for m, p in frames:
        if m == MARK_STATUS and p is not None:
            assert p & 1, "status byte 0x%02X has the alive bit clear" % p
    dut._log.info("readback reproduces image[1:] in order, status framed in")


# =====================================================================
# 4. THE DEFECT, recorded as an executable expect_fail
# =====================================================================
@cocotb.test(expect_fail=True)
async def test_readback_reaches_byte_zero(dut):
    """⛔⛔ EXPECTED TO FAIL: program byte 0 is NOT observable through readback.

    MEASURED, not inferred. Loading `[0xAA, 0x22, 0x33, ...]` and harvesting the
    serial stream from the first cycle after a readback rewind yields payload
    frames `0x22, 0x33, 0x44, ...` -- `0xAA` never appears, and the walk runs off
    the end into X exactly one byte early.

    THE CAUSE, in `src/project.v`'s load-mode readback branch:
        ser_sh <= {1'b0, s_rdata};   // the PREVIOUS read's data
        rb_ptr <= rb_ptr + 1'b1;     // increments
        rb_re  <= 1'b1;              // and requests a read
    `rb_re` is asserted for the cycle in which `rb_ptr` has ALREADY incremented,
    and the store's `raddr` is `rb_ptr`, so address 0 is never requested and the
    first frame carries `s_rdata` from before any read -- which is X, since
    `s_rdata` is allowlisted unreset on the argument that "H_CAP only runs after
    H_REQ". ⚠ THAT ARGUMENT DOES NOT COVER THIS PATH: the load-mode readback
    also consumes `s_rdata`, and there the ordering does not hold. The reset
    allowlist's stated reason for `s_rdata` is incomplete.

    WHY IT MATTERS: byte 0 is the first byte of lane 0's header -- its `pin` and
    `clkpin` fields -- so the one thing a host cannot verify is part of the
    descriptor that decides which physical pin lane 0 drives. For a feature whose
    stated purpose is proving the image loaded, that is the wrong byte to lose.

    PROPOSED FIX (one register, offered -- not applied, because the readback
    path is a design ruling): latch the address to be read separately from the
    walk, `rb_addr <= rb_ptr` alongside `rb_ptr <= rb_ptr + 1`, and point the
    store at `rb_addr` so the read uses the PRE-increment pointer.

    ⭐ THIS TEST IS THE RECORD. It is `expect_fail` so CI is honest rather than
    permanently red, and it ANNOUNCES ITS OWN OBSOLESCENCE: the moment the
    readback is fixed this test passes unexpectedly, CI goes red, and whoever
    fixed it is told to delete the marker. A defect recorded only in prose does
    not do that.
    """
    await start(dut)
    img = [0xAA, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]
    await load_image(dut, img)
    await rewind_readback(dut)

    frames = await harvest_frames(dut, 900)
    known = [p for p in payloads(frames) if p is not None]
    dut._log.info("payloads seen: %s" % [hex(p) for p in known])
    assert known[:len(img)] == img, (
        "readback = %s, image = %s -- byte 0 (0x%02X) is missing"
        % ([hex(x) for x in known[:len(img)]], [hex(x) for x in img], img[0]))


# =====================================================================
# 5. open-drain through `uio_oe`, on a REAL I2C program
# =====================================================================
@cocotb.test()
async def test_open_drain_data_pin(dut):
    """F5: open-drain IS expressible through `uio_oe`, shown on a real program.

    F5 was: "open-drain I2C cannot be expressed through uio_oe as modelled" =>
    "the pin abstraction is wrong and must be fixed before any protocol work
    continues."

    ⛔ THE OLD STIMULUS COULD NO LONGER EXPRESS THE PROPERTY. It wrote four raw
    bytes `0b00, 0b01, 0b10, 0b11` as an "image" and expected them to appear as
    SCL/SDA levels; with headers, action words and a scheduler those bytes are
    not an I2C program, the open-drain enable never asserted, and the must-fire
    fired on a test that had become unable to measure its own subject.
    ⇒ It now loads `corpus_i2c.hex`, the same open-drain program the
      two-simulator trace corpus uses.

    Two halves, and the second is what makes the first mean anything:
      (a) the design NEVER drives a hard 1 on the open-drain DATA pin
      (b) the enable DOES assert there -- otherwise (a) is vacuous

    ⚠ SCOPE: THE DATA PIN ONLY. The lane's CLOCK pin is driven push-pull
    regardless of the open-drain mode; that is a measured defect with its own
    test below, and folding it in here would have turned a real finding into a
    quietly narrowed assertion.
    """
    await start(dut)
    img = read_hex("corpus_i2c.hex")
    await load_image(dut, img)
    dut.ui_in.value = ctrl(prog=0)
    dut.uio_in.value = 0xFF                 # idle-high bus, as pull-ups give
    await ClockCycles(dut.clk, 8)

    asserted, released, samples = 0, 0, 0
    for _ in range(2500):
        oe = str(dut.uio_oe.value)
        ou = str(dut.uio_out.value)
        e, o = bit(oe, P_SDA), bit(ou, P_SDA)
        assert not (e == "1" and o == "1"), (
            "drove a HARD 1 on the open-drain data pin %d: uio_oe=%s uio_out=%s"
            % (P_SDA, oe, ou))
        if e == "1":
            asserted += 1
        else:
            released += 1
        samples += 1
        await ClockCycles(dut.clk, 1)

    assert asserted > 0, (
        "the open-drain enable never asserted on the data pin -- the 'never "
        "drives a 1' check above would have been VACUOUS")
    assert released > 0, "the pin was never released; open-drain needs both"
    dut._log.info("F5 satisfied on a real I2C program: SDA pulled low %d/%d "
                  "samples, released %d, never drove a 1"
                  % (asserted, samples, released))


# =====================================================================
# 5b. THE SECOND DEFECT, recorded as an executable expect_fail
# =====================================================================
@cocotb.test(expect_fail=True)
async def test_open_drain_clock_pin_is_released(dut):
    """⛔⛔ EXPECTED TO FAIL: an open-drain lane's CLOCK pin is driven push-pull.

    MEASURED on `corpus_i2c.hex`, whose lane declares open-drain with SDA as its
    data pin and SCL as its clock: `uio_oe=00000110 uio_out=11111011` -- SCL has
    its enable asserted AND its output high, a hard 1 on a line that must only
    ever be pulled low.

    THE CAUSE, in `src/pe_engine.v`'s `OP_SHIFT`: the DATA pin gets an
    open-drain-aware `if (l_mode[cur]) ... else ...`, and then the clock pin is
    driven with no such branch -- `pin_out[l_clkpin[cur]] <= a_lvl` and
    `pin_oe[l_clkpin[cur]] <= 1` unconditionally. `OP_LEVEL`, `OP_START` and
    `OP_STOP` all honour `l_mode` for the pin they name. The clock pin never
    does, so the mode is respected on SDA and ignored on SCL.

    WHY IT MATTERS, and it is not tidiness:
      * CLOCK STRETCHING BECOMES IMPOSSIBLE. A peer stretches by holding SCL
        LOW; against a push-pull driver that is a short, not a stretch.
        `test/fram_i2c.v` exports `scl_oe` as a PULL-LOW enable for exactly that
        purpose, and `docs/A2_GREEN_RESULTS.md` reasons about the stretch
        duration -- so the peer model and the schedulability argument both
        assume a releasable SCL the engine cannot provide.
      * MULTI-MASTER ARBITRATION AND BUS RECOVERY need every I2C line
        releasable.

    PROPOSED FIX (offered, not applied -- this is a protocol ruling): give the
    clock pin the same `l_mode` branch the data pin has, so an open-drain lane
    releases SCL instead of driving it high. The comment's stated reason for
    driving the clock there -- "so data and clock never need P-ORDER per bit" --
    is about ORDERING, and holds under either drive style.

    ⭐ `expect_fail`, so CI is honest rather than permanently red, and so this
    ANNOUNCES ITS OWN OBSOLESCENCE: the moment the clock pin honours the mode,
    this passes unexpectedly, CI goes red, and whoever fixed it is told to
    delete the marker.
    """
    await start(dut)
    img = read_hex("corpus_i2c.hex")
    await load_image(dut, img)
    dut.ui_in.value = ctrl(prog=0)
    dut.uio_in.value = 0xFF
    await ClockCycles(dut.clk, 8)

    for _ in range(2500):
        oe = str(dut.uio_oe.value)
        ou = str(dut.uio_out.value)
        e, o = bit(oe, P_SCL), bit(ou, P_SCL)
        assert not (e == "1" and o == "1"), (
            "drove a HARD 1 on the open-drain CLOCK pin %d: uio_oe=%s "
            "uio_out=%s -- SCL can be neither stretched nor shared"
            % (P_SCL, oe, ou))
        await ClockCycles(dut.clk, 1)
    dut._log.info("SCL was never driven high")


# =====================================================================
# 6. the engine, at the pins
# =====================================================================
@cocotb.test()
async def test_engine_runs_at_the_pins(dut):
    """THE ENGINE BENCH AT THE PINS: a five-lane program moves BOTH banks.

    ⛔⛔ THIS IS THE ARM THE OLD SUITE HAD NO EQUIVALENT OF, and its absence is
    why four load-path tests could rot for six CI runs without anything saying
    the engine still ran. It loads `corpus_all5.hex` -- the all-lane program from
    the trace corpus, pin-feasible because the two-bank ruling makes `uio` need
    exactly 8 and `uo_out` exactly 4 -- and asserts the engine is ALIVE where a
    host can see it:
      * the push-pull protocol outputs change (`uo_out[3:0]`)
      * `uio_oe` changes, so the open-drain and tri-state bank is being driven
      * no pin is left unknown

    ⚠ IT IS A LIVENESS AND NON-VACUITY CHECK, NOT A PROTOCOL CHECK. What the
    waveform MEANS is settled by the two-simulator corpus comparison and by the
    A2 margin gates; this says the silicon still does something at the pins, in
    the one place that also runs against the gate-level netlist.
    """
    await start(dut)
    img = read_hex("corpus_all5.hex")
    dut._log.info("loading the 5-lane program, %d bytes" % len(img))
    await load_image(dut, img)
    dut.ui_in.value = ctrl(prog=0)
    dut.uio_in.value = 0xFF
    await ClockCycles(dut.clk, 8)

    proto, oes, unknown = set(), set(), 0
    for _ in range(2500):
        uo = str(dut.uo_out.value)
        oe = str(dut.uio_oe.value)
        if any(c not in "01" for c in uo + oe):
            unknown += 1
        else:
            proto.add(uo[-(PROTO_HI + 1):])
            oes.add(oe)
        await ClockCycles(dut.clk, 1)

    dut._log.info("distinct protocol-output patterns=%d, uio_oe patterns=%d, "
                  "unknown samples=%d" % (len(proto), len(oes), unknown))
    assert unknown == 0, ("%d samples had X on uo_out/uio_oe -- a pin left "
                          "unknown is not a running engine" % unknown)
    assert len(proto) >= 2, ("the protocol outputs never changed (%s) -- the "
                             "engine is not driving the uo_out bank" % proto)
    assert len(oes) >= 2, ("uio_oe never changed (%s) -- nothing is driving the "
                           "open-drain / tri-state bank, so this program's "
                           "lanes are not running" % oes)
    dut._log.info("the engine is alive at the pins on all five lanes")
