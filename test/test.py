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

⭐ TWO OF THESE TESTS WERE `expect_fail` ARMS RECORDING MEASURED DEFECTS, and
both defects are now FIXED IN THE RTL -- D1 (program byte 0 unreadable) and D2
(an open-drain lane's clock pin driven push-pull). The self-announcing mechanism
worked as designed: once fixed, each arm reported "passed but we expected a
failure" and told whoever fixed it to delete the marker. The markers are gone
and the tests now assert the corrected behaviour; their docstrings keep the
defect description, because that is why each test exists.
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

# THE FRAME IS 12 BITS: 8 data LSB-first, then a 3-bit `kind`, then the
# marker. It was 9 (data + marker), which could not say WHICH LANE produced a
# received byte -- and a readback byte and an RX payload byte BOTH carried
# marker 0, so the two were indistinguishable on the wire and were being told
# apart by which mode the host believed it was in.
#   marker 1              -> STATUS            (kind = KIND_NONE)
#   marker 0, kind 0..4   -> RX PAYLOAD from THAT LANE
#   marker 0, kind 7      -> READBACK byte, not a lane
# THE MARKER SHIFTS OUT LAST, so the two frame types had to widen together:
# the host cannot know a frame's width until it has already read most of it.
FRAME_BITS = 12
KIND_NONE = 7                      # "not a lane"
MARK_STATUS, MARK_PAYLOAD = "1", "0"


def ctrl(prog=0, wr=0, ptr=0):
    return (prog << PIN_PROG) | (wr << PIN_WR) | (ptr << PIN_PTR)


async def start(dut):
    dut._log.info("start: 50 MHz, reset low for 10 cycles")
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.ob_oe.value = 0                 # the bench drives nothing yet
    dut.ob_val.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)


async def write_byte(dut, val, offset=0):
    """One load write. `wr` is held several clocks because it is treated as an
    ASYNCHRONOUS pin strobe: two flops to resolve metastability, a third to see
    the edge. `offset` nudges the pulse to exercise exactly that."""
    # ⭐ THE LOADER IS A BUS DRIVER LIKE ANY OTHER: enable all eight and
    # present the byte. The resolution in `test/od_bus.vh` does the rest.
    dut.ob_oe.value = 0xFF
    dut.ob_val.value = val
    dut.ui_in.value = ctrl(prog=1, wr=0)
    await ClockCycles(dut.clk, 3)
    dut.ui_in.value = ctrl(prog=1, wr=1)
    await ClockCycles(dut.clk, 3 + offset)
    dut.ui_in.value = ctrl(prog=1, wr=0)
    await ClockCycles(dut.clk, 3)


async def load_image(dut, img):
    """Pointer-reset, then write every byte. Load mode only, pins only."""
    # CDC3 ordering (docs/HOST_INTERFACE.md): `prog` settles >= 3 cycles
    # before the `ptr` pulse it qualifies; `ptr` is held >= 3 cycles
    dut.ui_in.value = ctrl(prog=1)
    await ClockCycles(dut.clk, 3)
    dut.ui_in.value = ctrl(prog=1, ptr=1)
    await ClockCycles(dut.clk, 3)
    dut.ui_in.value = ctrl(prog=1)
    await ClockCycles(dut.clk, 2)
    for b in img:
        await write_byte(dut, b)


# ---------------------------------------------------------------------------
# THE HOST DATA CHANNEL (Wilson's ruling 0)
# ---------------------------------------------------------------------------
# ⛔⛔ NO BENCH IN THIS PROJECT HAD EVER DRIVEN IT. `pe_isa.host_pushes` had
# been in the ISA since the channel was built and nothing called it, so every
# `OP_SHIFT` ever executed found `host_valid = 0` and took the UNDERRUN branch.
# Three tests in this file load shifting corpus programs -- `corpus_i2c.hex`
# (twice) and `corpus_all5.hex` -- so all three measured the STARVED path while
# reading as evidence about the open-drain and engine behaviour of a
# transmitting lane.
# ⭐ THE PUSH SHAPE IS `pe_isa`'s, NOT A LOCAL GUESS: two pushes per byte, HIGH
# NIBBLE FIRST, with the 2-bit queue tag on BOTH pushes because the hardware
# latches it with the high nibble. `test/host_feed.vh` is the Verilog side of
# the same contract; this is the cocotb side.
# ⛔⛔ NON-PALINDROMIC (ruling 1b). This was [0x5A, 0xC3, 0x3C, 0xA5] -- FOUR
# BIT-REVERSAL PALINDROMES out of four, so it passed under either bit order and
# tested nothing about order. That is how the engine's LSB-first wire order
# went unnoticed while `pe_isa.py` documented MSB-first: the only byte checked
# end to end read the same both ways. These reverse to DA/80/5E/E3, and 0x01 is
# the asymmetric extreme.
HOST_PAT = [0x5B, 0x01, 0x7A, 0xC7]
TXQ = 4
TXD = 2

# ⛔⛔ GATE LEVEL HAS NO INTERNALS, AND PRETENDING OTHERWISE BROKE A HARDEN.
# `GATES=yes` builds against the flat synthesised netlist: `u_eng`, `tx_cnt`,
# `host_pop` and `lane_underrun` do not exist there -- synthesis does not keep
# the hierarchy or the names. ⚠ `tb.v`'s parameter override had the same
# problem and killed `gl_test` in 55 seconds after `gds` had spent 3h50m
# succeeding, which is how expensive this class is to discover late.
# ⭐ ONE NAMED PREDICATE, not a scatter of try/except. A bare `except` around
# each read would make a gate-level run SILENTLY SKIP the host-channel
# precondition while still printing a pass -- which is the "a guard can pass
# because what it guards is absent" shape this project has already paid for.
# What degrades is declared, loudly, at the point of use.
GL = os.environ.get("GATES", "") == "yes"
GL_WHY = ("gate level: the synthesised netlist keeps no hierarchy, so "
          "tx_cnt / host_pop / lane_underrun do not exist")


def push_ctrl(nib, tag, wr):
    """`ui_in` in RUN mode: prog=0, nibble on [4:1], tag on {[5], [0]}."""
    return ((wr << PIN_WR) | ((tag >> 1) << 5) | ((nib & 0xF) << 1)
            | (tag & 1))


async def push_nibble(dut, nib, tag):
    """One push. ⛔ `wr` is an ASYNCHRONOUS strobe behind a 3-stage
    synchroniser, so it is held -- a missed push is INVISIBLE: the byte never
    arrives and the lane underruns, which looks exactly like the starved
    regime this exists to leave."""
    dut.ui_in.value = push_ctrl(nib, tag, 0)
    await ClockCycles(dut.clk, 2)
    dut.ui_in.value = push_ctrl(nib, tag, 1)
    await ClockCycles(dut.clk, 3)
    dut.ui_in.value = push_ctrl(nib, tag, 0)
    await ClockCycles(dut.clk, 1)


# ⛔⛔ THE PYTHON BUS MODEL IS GONE, and that is the point of this change.
# It used to live here as `open_drain_bus`, re-deriving in Python what
# `tb_trace.v` and `tb_edge.v` each re-derived in Verilog -- THREE models of
# the same wire. The bus is now resolved ONCE, in `test/od_bus.vh`, which
# `tb.v` includes alongside the other benches; cocotb drives the PEER SIDE
# (`ob_oe`/`ob_val`) and reads the resolved `uio_in`, exactly as a peer model
# does. ⭐ M_BUS_NO_PULLDOWN now breaks the cocotb suite AND the Verilog
# benches together, which is the only way to show there is one model.
# ⚠ The Python copy was also WRONG for most of its life -- a constant 0xFF,
# pull-ups without the DUT's pull-downs -- and nothing noticed until the
# engine began parking on an OBSERVED rise.

async def feed_host(dut, state):
    """Top up every TX queue that has space, from a repeating pattern.

    ⛔ ONLY QUEUES WITH SPACE. A push onto a full queue is DROPPED and sets
    `tx_full_sticky` -- the host has no back-pressure pin -- so a blind feeder
    would drop bytes and the lane would emit a stream with gaps, which is the
    FEEDER's bug reported as the engine's.
    ⚠ Runs forever; start it with `cocotb.start_soon` and read `state`
    afterwards.
    """
    idx = [0] * TXQ
    while True:
        for q in range(TXQ):
            if GL:
                # ⛔ NO `tx_cnt` TO READ, so the feeder cannot top up on
                # demand. It PACES itself instead: a byte takes ~24 clocks to
                # push and the fastest consumer here takes one every ~400, so
                # a fixed gap keeps the queues fed without overrunning them.
                # ⚠ A blind feeder that pushed flat out WOULD overrun and set
                # `tx_full_sticky`, and the dropped bytes would be the
                # FEEDER's bug reported as the engine's -- which is why the
                # RTL path reads the depth and this path waits instead.
                room = True
                await ClockCycles(dut.clk, 200)
            else:
                room = int(dut.user_project.tx_cnt[q].value) != TXD
            if room:
                b = HOST_PAT[idx[q]]
                await push_nibble(dut, (b >> 4) & 0xF, q)
                await push_nibble(dut, b & 0xF, q)
                idx[q] = (idx[q] + 1) % len(HOST_PAT)
                state["bytes"] += 1
        await ClockCycles(dut.clk, 1)


async def watch_pops(dut, state):
    """Count `host_pop` pulses -- bytes the ENGINE actually consumed.

    ⛔⛔ WITHOUT THIS THE PRECONDITION PASSES VACUOUSLY, which is the exact
    defect class this whole ruling is about. "No underrun" is trivially true if
    no `OP_SHIFT` ever reached its byte load: the load fires only at
    `l_bitp == a_cnt`, so a program with `count = 8` loads once every nine
    shifts and a short window can contain shifts but no load at all. A run like
    that has not exercised the payload path and must not be allowed to say it
    did.
    """
    if GL:
        # ⛔ NOT COUNTABLE AT GATE LEVEL. `host_pop` is an internal pulse with
        # no port, so this monitor has nothing to watch. It returns rather
        # than spinning, and `assert_host_fed` knows not to require pops --
        # stated there, not inferred from a zero.
        return
    while True:
        await ClockCycles(dut.clk, 1)
        if int(dut.user_project.u_eng.host_pop.value) == 1:
            state["pops"] += 1


def assert_host_fed(dut, state, expect_pops=True, why=""):
    """THE STANDING PRECONDITION (ruling 0): a run that executes a SHIFT must
    have had a byte pushed, must have had one CONSUMED, and must not have set
    any lane's underrun flag. Otherwise the run is STARVED and does not count
    -- the same class as "the image loaded" and "the window is long enough".

    ⛔⛔ `expect_pops=False` IS A DECLARATION, NOT AN ESCAPE HATCH. It asserts
    that the engine consumed EXACTLY ZERO bytes, and the caller must say why.
    So a design change that makes the load reachable turns the test RED and
    forces the declaration to be revisited -- the opposite of a weakened check.
    """
    assert state["bytes"] > 0, (
        "STARVED: the program shifts and no host byte was ever pushed, so "
        "every OP_SHIFT took the underrun branch")
    # ⛔⛔ AT GATE LEVEL ONLY THE PUSH HALF IS CHECKABLE, AND THAT IS SAID
    # RATHER THAN QUIETLY SKIPPED. `pops` and `lane_underrun` are internal and
    # the netlist keeps neither, so the two strongest clauses of this
    # precondition cannot be evaluated here at all.
    # ⚠ THE RTL RUN IS WHAT CARRIES THEM. Every one of these tests runs at RTL
    # in CI on the same program with the full precondition, so the claim is
    # made where it is checkable and the gate-level run asserts the subset it
    # can see. Silently returning "pass" with no note would be the defect
    # this project keeps finding: a guard that passes because what it guards
    # is absent.
    if GL:
        dut._log.warning(
            "HOST-CHANNEL PRECONDITION PARTIAL -- %d bytes pushed; `pops` and "
            "`lane_underrun` NOT CHECKED (%s). The full precondition is "
            "carried by the RTL run of this same test."
            % (state["bytes"], GL_WHY))
        return
    if not expect_pops:
        assert why, "a declared zero-pop expectation must carry its reason"
        assert state["pops"] == 0, (
            "THE DECLARATION IS STALE: %d bytes were consumed where zero were "
            "expected. Reason on record: %s -- re-check it."
            % (state["pops"], why))
        dut._log.info("host channel: %d pushed, 0 consumed AS DECLARED -- %s"
                      % (state["bytes"], why))
        return
    assert state["pops"] > 0, (
        "VACUOUS: %d bytes were pushed but the engine consumed NONE, so no "
        "OP_SHIFT reached its byte load and the payload path was never "
        "exercised. `no underrun` here means `nothing tried`."
        % state["bytes"])
    ur = int(dut.user_project.u_eng.lane_underrun.value)
    assert ur == 0, (
        "STARVED: lane_underrun = %d -- a shift found an empty queue, so this "
        "run measured the underrun path and does not count" % ur)
    dut._log.info("host channel: %d bytes pushed, %d consumed, no underrun"
                  % (state["bytes"], state["pops"]))


def read_hex(name):
    """A corpus image, one hex byte per line. ⭐ The SAME images the two-simulator
    trace corpus uses, so this suite and that comparison speak about the same
    programs rather than about two sets of bytes that happen to share a name."""
    path = os.path.join(HERE, name)
    # ⛔ cocotb's "run" loads its program here, in Python, not by a plusarg:
    # the one lookup (test/sim_run.py) refuses a clocked image with no A2
    # bound before the program reaches the chip (Wilson 10-19)
    import sim_run
    print(sim_run.check([path]), flush=True)
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
    # THE END CYCLE TRAVELS WITH EACH FRAME, so frame SPACING is measurable
    # from the same harvest rather than needing a second pass. The spacing is
    # what sets readback throughput and the RX payload slot, and both were
    # quoted from arithmetic until now.
    t = 0
    for _ in range(ncyc):
        await ClockCycles(dut.clk, 1)
        t += 1
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
                mk = cur[FRAME_BITS - 1]
                if any(c not in "01" for c in cur):
                    frames.append((mk if mk in "01" else "?", None, None, t))
                else:
                    pay = 0
                    for k in range(8):
                        pay |= int(cur[k]) << k
                    kind = 0
                    for k in range(3):
                        kind |= int(cur[8 + k]) << k
                    frames.append((mk, pay, kind, t))
            cur = []
        prev_v = v
    return frames


def payloads(frames):
    """Every payload byte, whatever its kind.

    A frame is now `(marker, payload, kind)`. Callers that only want the bytes
    use this; callers that care WHICH LANE a byte came from use
    `lane_payloads`, which is the whole reason the field exists.
    """
    return [p for m, p, _k, _t in frames if m == MARK_PAYLOAD]


def lane_payloads(frames, lane):
    """The payload bytes a GIVEN LANE produced.

    This is the question the 9-bit frame could not answer. It also excludes
    readback frames, which carry `kind = KIND_NONE` and are not lane data --
    they used to be indistinguishable from payload.
    """
    return [p for m, p, k, _t in frames
            if m == MARK_PAYLOAD and p is not None and k == lane]


def readback_payloads(frames):
    """The program bytes from a readback walk -- `kind = KIND_NONE`."""
    return [p for m, p, k, _t in frames
            if m == MARK_PAYLOAD and p is not None and k == KIND_NONE]


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

    ⭐ IT ASSERTS THE WHOLE IMAGE, INCLUDING BYTE 0. It did not always: byte 0
    was unreachable and the first frame carried data from no requested address,
    so this test asserted image[1:] with the first frame discarded and the
    defect was recorded as an expect_fail. Both are now fixed in the RTL, and
    `test_readback_reaches_byte_zero` holds the specific must-fire.
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

    # ⭐ THE WHOLE IMAGE, FROM THE FIRST PAYLOAD FRAME. This assertion used to
    # start at image[1] and discard frame 1, because byte 0 was unreachable and
    # the first frame carried data from no requested address. Both are fixed:
    # `rb_addr` latches the pre-increment pointer and the readback primes before
    # it frames, so frame 1 IS byte 0.
    want = img
    got = known[:len(want)]
    assert got == want, ("serial readback = %s, image = %s"
                         % ([hex(x) for x in got], [hex(x) for x in want]))

    # the status frames must alternate with the payloads and carry the alive bit
    marks = [m for m, _p, _k, _t in frames]
    assert MARK_STATUS in marks, "no STATUS frame in the stream"
    for m, p, _k, _t in frames:
        if m == MARK_STATUS and p is not None:
            assert p & 1, "status byte 0x%02X has the alive bit clear" % p
    # ⛔⛔ THE FRAME SPACING, MEASURED. `HOST_INTERFACE.md` quotes a 25-clock
    # frame, a 50-clock payload slot and a 256 us full-store walk, and all
    # three came from arithmetic: 12 bits at two clocks PLUS one clock to queue
    # the next, doubled by the status frame that always follows a payload.
    # ⚠ THE FIRST VERSION OF THAT ARITHMETIC SAID 48, having forgotten the
    # queue clock, and a sweep measured 50 at every point. So it is measured
    # here rather than trusted.
    ends = [t for _m, _p, _k, t in frames]
    gaps = sorted({ends[i + 1] - ends[i] for i in range(len(ends) - 1)})
    FRAME_CLK = FRAME_BITS * 2 + 1
    SLOT = 2 * FRAME_CLK
    dut._log.info("frame-to-frame gaps seen: %s (a frame is %d clocks, a "
                  "payload slot %d)" % (gaps, FRAME_CLK, SLOT))
    assert gaps, "fewer than two frames, so there is no spacing to measure"
    assert min(gaps) == FRAME_CLK, (
        "consecutive frames are %d clocks apart; the serialiser's structure "
        "gives %d (%d bits at 2 clocks + 1 to queue the next). A shorter gap "
        "means the frame costs fewer clocks than the RTL allows."
        % (min(gaps), FRAME_CLK, FRAME_BITS))
    dut._log.info("readback: %d clocks per byte -> a 256-byte walk is %.1f us "
                  "at 50 MHz" % (SLOT, 256 * SLOT / 50.0))
    dut._log.info("readback reproduces image[1:] in order, status framed in")


# =====================================================================
# 4. D1's MUST-FIRE: byte 0 is the first payload
# =====================================================================
@cocotb.test()
async def test_readback_reaches_byte_zero(dut):
    """D1's MUST-FIRE: a distinctive byte 0 arrives as the FIRST payload frame.

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

    ⭐ FIXED, AND THIS IS THE MUST-FIRE. `rb_addr` latches the pre-increment
    pointer so address 0 is requested, and the readback PRIMES before it frames
    -- the first two visits issue the read and let it land without queueing a
    frame -- so the stream now opens with byte 0 instead of a stale register.
    Measured: frame 0 is `payload 0xAA`.
    ⚠ THE FIX WAS TWO PARTS AND THE FIRST ALONE WAS NOT ENOUGH. With only
    `rb_addr`, byte 0 became REACHABLE but arrived SECOND, behind one stale
    frame: 0x22(stale), 0xAA, 0x22, ... A pipeline's first output is not data.
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
    dut.ob_oe.value = 0                     # release: the pull-ups hold it high
    await ClockCycles(dut.clk, 8)
    # ⛔ RULING 0: FEED THE HOST CHANNEL. This program SHIFTS, and until now
    # every shift here found an empty queue and took the underrun branch --
    # so this test's evidence was about the starved path. The feeder owns
    # `ui_in` from here on, which is why it starts AFTER the line above sets
    # run mode and why the sampling loop below never writes that port.
    hostq = {"bytes": 0, "pops": 0}
    cocotb.start_soon(feed_host(dut, hostq))
    cocotb.start_soon(watch_pops(dut, hostq))

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
# 5b. D2's must-fire: the open-drain clock pin is released
# =====================================================================

    # ⛔ THE STANDING PRECONDITION (ruling 0). Checked at the END, because a
    # lane can be fed at the start and still starve later -- and a starved
    # run does not count whatever else it showed.
    # ⭐⭐ THIS WAS A DECLARED ZERO AND IS NOW A REAL READING. The lane mixes
    # OP_SHIFT with OP_SHIFTIN, which is how I2C works, and the two directions
    # used to SHARE both the bit pointer and the shift register -- so the RX
    # byte-complete reset at `a_cnt - 1` always fired before the TX host load
    # at `a_cnt`, and 124 OP_SHIFT dispatches produced ZERO loads. The
    # assertion was written as "exactly zero, and here is why" precisely so
    # that fixing it would turn this test RED and force the declaration to be
    # revisited. Ruling 1 split them (`tx_bitp`/`rx_bitp`, `l_tx`/`l_rx`), the
    # test went red as designed, and the ordinary precondition now applies.
    assert_host_fed(dut, hostq)
@cocotb.test()
async def test_open_drain_clock_pin_is_released(dut):
    """D2: an open-drain lane's CLOCK pin is RELEASED, never driven high.

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

    ⭐ FIXED. The clock pin now takes the same `l_mode` branch as the data pin,
    so an open-drain lane pulls SCL low with oe=1/out=0 and RELEASES it with
    oe=0, leaving the high phase to the observed rise through edge capture --
    which is what N1a requires. Ruling 1.5's per-pin drive mask (`pin_pp`) was
    also built, so the hard-1 is now unsatisfiable at the flop's D input
    whatever a future opcode path does.
    """
    await start(dut)
    img = read_hex("corpus_i2c.hex")
    await load_image(dut, img)
    dut.ui_in.value = ctrl(prog=0)
    dut.ob_oe.value = 0                     # release: the pull-ups hold it high
    await ClockCycles(dut.clk, 8)
    # ⛔ RULING 0: FEED THE HOST CHANNEL. This program SHIFTS, and until now
    # every shift here found an empty queue and took the underrun branch --
    # so this test's evidence was about the starved path. The feeder owns
    # `ui_in` from here on, which is why it starts AFTER the line above sets
    # run mode and why the sampling loop below never writes that port.
    hostq = {"bytes": 0, "pops": 0}
    cocotb.start_soon(feed_host(dut, hostq))
    cocotb.start_soon(watch_pops(dut, hostq))

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

    # ⛔ THE STANDING PRECONDITION (ruling 0). Checked at the END, because a
    # lane can be fed at the start and still starve later -- and a starved
    # run does not count whatever else it showed.
    # ⭐⭐ THIS WAS A DECLARED ZERO AND IS NOW A REAL READING. The lane mixes
    # OP_SHIFT with OP_SHIFTIN, which is how I2C works, and the two directions
    # used to SHARE both the bit pointer and the shift register -- so the RX
    # byte-complete reset at `a_cnt - 1` always fired before the TX host load
    # at `a_cnt`, and 124 OP_SHIFT dispatches produced ZERO loads. The
    # assertion was written as "exactly zero, and here is why" precisely so
    # that fixing it would turn this test RED and force the declaration to be
    # revisited. Ruling 1 split them (`tx_bitp`/`rx_bitp`, `l_tx`/`l_rx`), the
    # test went red as designed, and the ordinary precondition now applies.
    assert_host_fed(dut, hostq)
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
    dut.ob_oe.value = 0                     # release: the pull-ups hold it high
    await ClockCycles(dut.clk, 8)
    # ⛔ RULING 0: FEED THE HOST CHANNEL. This program SHIFTS, and until now
    # every shift here found an empty queue and took the underrun branch --
    # so this test's evidence was about the starved path. The feeder owns
    # `ui_in` from here on, which is why it starts AFTER the line above sets
    # run mode and why the sampling loop below never writes that port.
    hostq = {"bytes": 0, "pops": 0}
    cocotb.start_soon(feed_host(dut, hostq))
    cocotb.start_soon(watch_pops(dut, hostq))

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

    # ⛔ THE STANDING PRECONDITION (ruling 0). Checked at the END, because a
    # lane can be fed at the start and still starve later -- and a starved
    # run does not count whatever else it showed.
    assert_host_fed(dut, hostq)


# =====================================================================
# 7. 1.6s IN SILICON: a bad configuration must REFUSE TO RUN
# =====================================================================
ST_CFG_ERR = 5          # status byte bit 5


@cocotb.test()
async def test_config_error_refuses_to_run(dut):
    """1.6s MUST-FIRE: an open-drain lane on a `uo_out` pin never runs.

    `uo_out` has no output enable, so an open-drain lane assigned there can
    never release -- it drives low once and sticks. 1.6s ruled that the loader
    REJECTS such a program.

    ⛔⛔ AND NOTHING REJECTED IT. The ruling existed, the model gate checked the
    condition against programs WE author, and there was no load-time screen
    anywhere -- not in the RTL, and not asserted in the toolchain, whose
    `hdr()` only stated the rule in a docstring. Two RTL comments deferred to a
    screen that did not exist. Being inside a passing model gate is what let it
    read as built.

    Now the header load sets a sticky CONFIG_ERR and the engine refuses to
    dispatch. Both halves are asserted here, because either alone is weak:
      (a) the protocol pins never move -- the program really did not run;
      (b) CONFIG_ERR appears in the status stream -- the host is told WHY,
          rather than being left with a part that sits silent.
    """
    await start(dut)
    img = read_hex("cfgerr_image.hex")
    await load_image(dut, img)
    dut.ui_in.value = ctrl(prog=0)
    dut.ob_oe.value = 0                     # release: the pull-ups hold it high
    await ClockCycles(dut.clk, 8)

    # (a) the program must not run: its lane drives uo_out[0], which must not move
    seen = set()
    for _ in range(1200):
        b = str(dut.uo_out.value)
        seen.add(bit(b, PROTO_LO))
        await ClockCycles(dut.clk, 1)
    assert seen <= {"1"}, (
        "uo_out[0] took values %s -- a program that violates 1.6s DISPATCHED"
        % sorted(seen))

    # (b) and the host is told why, in the stream
    frames = await harvest_frames(dut, 900)
    status = [p for m, p, _k, _t in frames if m == MARK_STATUS and p is not None]
    assert status, "no status frame in the stream, so CONFIG_ERR is unreadable"
    assert any((p >> ST_CFG_ERR) & 1 for p in status), (
        "CONFIG_ERR never set in %d status frames (%s) -- the part refuses to "
        "run and does not say why"
        % (len(status), [hex(p) for p in status[:4]]))
    dut._log.info("1.6s: the violating program never dispatched, and "
                  "CONFIG_ERR is set in the status stream")


# =====================================================================
# 8. CHECKPOINT H-CK3 -- the silicon paths added since `d2b7d34`, at the pins
# =====================================================================
# ⛔⛔ WHY THESE FOUR ARMS EXIST. The checkpoint harden is the first gate-level
# run since `d2b7d34`, and every path below landed after it: M5's short-load
# refusal, D1/U's hold refusal, F1's clocked open-drain park and rebase, the
# SDA hold pipeline and W1's hold-pending ineligibility. The eight tests above
# reach none of them as a CHECK -- `corpus_i2c` runs the park and the hold, but
# nothing there measures a high phase, a hold or a setup, so the netlist could
# break any of them and stay green. Each arm is pins-only, so the identical
# check runs on the RTL and on the netlist.
# ⭐ The boundaries are READ, not restated: SDA_HOLD / SDA_SETUP from the RTL
# (`model/hold_bound.py`), delays from the image's own headers and actions.
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "model"))
import hold_bound                                    # noqa: E402
import pe_isa                                        # noqa: E402


def _unpack(fields, raw, nbytes):
    w = int.from_bytes(bytes(raw), "big") >> (nbytes * 8
                                              - sum(x for _n, x in fields))
    out = {}
    for name, width in reversed(fields):
        out[name] = w & ((1 << width) - 1)
        w >>= width
    return out


def lane_delays(img, lane):
    """Every action delay lane `lane` can reach, from the image itself."""
    h = _unpack(pe_isa.HDR_FIELDS,
                img[lane * pe_isa.HDR_BYTES:(lane + 1) * pe_isa.HDR_BYTES],
                pe_isa.HDR_BYTES)
    pc, out = h["base"], []
    for _ in range(200):
        a = _unpack(pe_isa.ACT_FIELDS, img[pc:pc + pe_isa.ACT_BYTES],
                    pe_isa.ACT_BYTES)
        if a["delay"]:
            out.append(a["delay"])
        if a["op"] == pe_isa.OP_REARM:
            break
        pc += pe_isa.ACT_BYTES
    return h, out


async def run_loaded(dut, img, feed=True, first=True):
    """Load `img` and run it. `first=False` re-resets WITHOUT a second clock:
    CONFIG_ERR and M5's `store_full` are sticky until `rst_n`, so every arm
    after the first needs a reset, and `start` would add another Clock."""
    if first:
        await start(dut)
    else:
        dut.ui_in.value = 0
        dut.ob_oe.value = 0
        dut.rst_n.value = 0
        await ClockCycles(dut.clk, 10)
        dut.rst_n.value = 1
        await ClockCycles(dut.clk, 2)
    await load_image(dut, img)
    dut.ui_in.value = ctrl(prog=0)
    dut.ob_oe.value = 0                     # release: the pull-ups hold it high
    await ClockCycles(dut.clk, 8)
    hostq = {"bytes": 0, "pops": 0}
    if feed:
        cocotb.start_soon(feed_host(dut, hostq))
        cocotb.start_soon(watch_pops(dut, hostq))
    return hostq


async def i2c_oe_trace(dut, ncyc):
    """[(scl_oe, sda_oe)] per cycle on the I2C pair, X as '?'."""
    out = []
    for _ in range(ncyc):
        oe = str(dut.uio_oe.value)
        out.append((bit(oe, P_SCL), bit(oe, P_SDA)))
        await ClockCycles(dut.clk, 1)
    return out


async def cfg_err_seen(dut, ncyc=900):
    frames = await harvest_frames(dut, ncyc)
    status = [p for m, p, _k, _t in frames if m == MARK_STATUS and p is not None]
    return bool(status), any((p >> ST_CFG_ERR) & 1 for p in status)


@cocotb.test()
async def test_short_load_refused(dut):
    """M5 at the pins: a load shorter than the store never runs.

    The store has no reset, so a partial load leaves power-up contents one
    missing REARM from running on real pins. Silicon gates the engine on
    2^AW consecutive writes since `rst_n` and raises CONFIG_ERR at release.
    Loaded here: `corpus_i2c`'s 51 program bytes, not its 256-byte image --
    the exact short load M5 caught `gate_corpus_trace` making.
    """
    img = read_hex("corpus_i2c.hex")[:51]
    await run_loaded(dut, img, feed=False)
    tr = await i2c_oe_trace(dut, 1500)
    pulled = sum(1 for s, d in tr if "1" in (s, d))
    assert pulled == 0, ("a 51-byte load RAN: the I2C pair was pulled low on "
                         "%d of %d cycles" % (pulled, len(tr)))
    have, err = await cfg_err_seen(dut)
    assert have, "no status frame in the stream, so CONFIG_ERR is unreadable"
    assert err, "a short load was refused silently -- CONFIG_ERR never set"
    dut._log.info("M5: the 51-byte load never ran, and CONFIG_ERR is set")


@cocotb.test()
async def test_hold_refusal(dut):
    """D1 + U at the pins: a delay the SDA hold cannot fit is REFUSED.

    D1, clocked: `ckhold_at` (a self-clocked open-drain byte at d = SDA_HOLD)
    must never move the pair and must raise CONFIG_ERR. U, unclocked:
    `build_i2cframe(SDA_HOLD)` STARTs (SDA low) and takes SCL low, then its
    first clock-low SHIFT is refused -- so a few moves, then a frozen pair and
    CONFIG_ERR. ⭐ The control arm is the same frame at SDA_HOLD + 1, which
    must RUN: a refusal that fired on both would prove nothing.
    """
    import make_smoke_image as msi
    hold = hold_bound.bound()
    # -- D1: the clocked byte at d = SDA_HOLD -----------------------------
    await run_loaded(dut, read_hex("ckhold_at_image.hex"), feed=False)
    tr = await i2c_oe_trace(dut, 1200)
    assert all(s != "1" and d != "1" for s, d in tr), (
        "D1: a clocked open-drain byte at d = %d moved the I2C pair" % hold)
    have, err = await cfg_err_seen(dut)
    assert have and err, "D1: refused without CONFIG_ERR in the stream"
    # -- U: the unclocked frame, refused at SDA_HOLD, running at +1 -------
    moves = {}
    for d in (hold, hold + 1):
        img = list(pe_isa.full_store(msi.build_i2cframe(d)))
        await run_loaded(dut, img, feed=False, first=False)
        tr = await i2c_oe_trace(dut, 2000)
        moves[d] = (sum(1 for a, b in zip(tr, tr[1:]) if a != b),
                    sum(1 for a, b in zip(tr[-600:], tr[-599:]) if a != b))
        have, err = await cfg_err_seen(dut)
        moves[d] += (err,)
    (n_at, tail_at, err_at), (n_ov, _t, err_ov) = moves[hold], moves[hold + 1]
    assert err_at and tail_at == 0 and n_at <= 3, (
        "U: the unclocked frame at d = %d was not refused cleanly: %d pair "
        "moves, %d in the last 600 cycles, CONFIG_ERR=%s"
        % (hold, n_at, tail_at, err_at))
    assert not err_ov and n_ov > 20, (
        "U control: the frame at d = %d should RUN (moves %d, CONFIG_ERR=%s)"
        % (hold + 1, n_ov, err_ov))
    dut._log.info("D1 + U: refused at d = %d (%d moves, then frozen), runs at "
                  "d = %d (%d moves)" % (hold, n_at, hold + 1, n_ov))


@cocotb.test()
async def test_clocked_park_high_phase(dut):
    """F1 at the pins: a clocked open-drain HIGH lasts at least `d`.

    The post-HIGH park counts its high period from the OBSERVED SCL rise and
    releases at `rise + d`. Before F1 it rebased to the rise itself, and t_HIGH
    measured FLAT at the synchroniser latency (~6 cycles) whatever `d` was --
    no I2C mode at any delay. Measured here on `corpus_i2c`: every complete
    SCL-released run between two pulls is >= the lane's minimum delay.
    """
    img = read_hex("corpus_i2c.hex")
    h, dl = lane_delays(img, 0)
    assert h["clkpin"] == P_SCL and h["pin"] == P_SDA and dl, (
        "corpus_i2c lane 0 is not the I2C pair this test watches: %s" % h)
    d = min(dl)
    hostq = await run_loaded(dut, img)
    tr = await i2c_oe_trace(dut, 4000)
    highs, run, seen_pull = [], 0, False
    for s, _d in tr:
        if s == "1":
            if seen_pull and run:
                highs.append(run)
            seen_pull, run = True, 0
        else:
            run += 1
    assert len(highs) >= 10, ("only %d complete SCL high phases -- the "
                              "measurement is vacuous" % len(highs))
    assert min(highs) >= d, (
        "t_HIGH fell to %d cycles, under the lane's delay d = %d: the park "
        "released before rise + d (F1)" % (min(highs), d))
    dut._log.info("F1: %d SCL high phases, %d..%d cycles, all >= d = %d"
                  % (len(highs), min(highs), max(highs), d))
    assert_host_fed(dut, hostq)


@cocotb.test()
async def test_sda_hold_and_setup(dut):
    """The SDA hold pipeline and W1 at the pins.

    `ckhold_over` is one self-clocked open-drain byte at d = SDA_HOLD + 1, the
    program the setup finding was measured on: with one cycle of contention
    the held bit used to land after the next SCL release (11 of 562 data moves
    with SCL released). W1 makes the lane ineligible until its hold + setup
    is over. At the pins, every SDA change must (a) come while SCL is pulled
    low, (b) >= SDA_HOLD after that low began, and (c) >= SDA_SETUP before
    the release that ends it. No START/STOP in this program, so every SDA
    change is a data move.
    """
    hold, setup = hold_bound.bound(), hold_bound.setup()
    img = read_hex("ckhold_over_image.hex")
    hostq = await run_loaded(dut, img)
    tr = await i2c_oe_trace(dut, 5000)
    fall, last, n_mv, n_su = None, None, 0, 0
    worst_hold, worst_su = None, None
    prev = tr[0]
    for cyc, (s, d) in enumerate(tr[1:], 1):
        ps, pd = prev
        if ps != "1" and s == "1":
            fall, last = cyc, None
        if ps == "1" and s != "1" and last is not None:
            su = cyc - last
            worst_su = su if worst_su is None else min(worst_su, su)
            n_su += 1
        if pd != d and fall is not None:
            assert s == "1" and ps == "1", (
                "cycle %d: SDA changed with SCL RELEASED -- t_SU;DAT <= 0, a "
                "START or STOP to any receiver (W1)" % cyc)
            hd = cyc - fall
            worst_hold = hd if worst_hold is None else min(worst_hold, hd)
            last = cyc
            n_mv += 1
        prev = (s, d)
    assert n_mv >= 20 and n_su >= 10, (
        "only %d SDA moves / %d releases after one -- vacuous" % (n_mv, n_su))
    assert worst_hold >= hold, ("t_HD;DAT fell to %d, under SDA_HOLD = %d"
                                % (worst_hold, hold))
    assert worst_su >= setup, ("t_SU;DAT fell to %d, under SDA_SETUP = %d (W1)"
                               % (worst_su, setup))
    dut._log.info("hold + W1: %d SDA moves, hold >= %d (min %d), setup >= %d "
                  "(min %d over %d releases)"
                  % (n_mv, hold, worst_hold, setup, worst_su, n_su))
    assert_host_fed(dut, hostq)


def decode_i2c(tr):
    """Bytes framed by START/STOP off an `i2c_oe_trace` (open-drain: a pin
    whose enable is set is LOW, a released one HIGH). -> [byte, ...], the 8
    data bits of each 9-clock group, MSB first as the wire carries them."""
    out, bits, ps, pd = [], [], 1, 1
    for scl_oe, sda_oe in tr:
        s = 0 if scl_oe == "1" else 1
        d = 0 if sda_oe == "1" else 1
        if s and ps and d != pd:
            bits = []                                   # START or STOP
        if s and not ps:
            bits.append(d)
            if len(bits) == 9:
                out.append(int("".join(str(b) for b in bits[:8]), 2))
                bits = []
        ps, pd = s, d
    return out


@cocotb.test()
async def test_clocked_tx_bytes_at_the_pins(dut):
    """SILICON FIX #2 (ruling TX6), PINS ONLY: a clocked SHIFT sends the byte
    the host pushed. 0x5B in, 0x5B out, every transaction.

    The clocked SHIFT's host load used to fire on the HIGH phase after the 7th
    bit, so the 8th bit was the next byte's first and the stream drifted one
    bit per byte: 5B fed went out 00, B5, 6A, D5. Every timing check passed
    it. This reads the BYTES off `uio_oe` alone, so it holds at gate level,
    where nothing internal exists. The program is one open-drain lane, MSB
    first: START, a clocked 8-bit SHIFT, a clocked ACK slot, STOP.
    ⭐ EVERY BYTE, FROM THE FIRST (silicon fix #8): the first byte out used to
    be the register's reset 0x00 and this test skipped it; now byte 0 is held
    to 0x5B too, so the test is also #8's pins-only, gate-level witness.
    ⛔ Must-fire: built with `M_TX_LOAD_ANYPHASE` this test FAILS in RTL
    simulation with the drifting pattern; with `M_TX_PRELOAD` it fails on
    byte 0.
    """
    sda, scl, d = P_SDA, P_SCL, 70
    prog = [pe_isa.act(pe_isa.OP_START, sda, 0, d),
            pe_isa.act_shift_clocked(sda, d, nbits=8, q=0),
            pe_isa.act_shiftin_clocked(sda, d, nbits=1),
            pe_isa.act(pe_isa.OP_LEVEL, sda, 0, d),
            pe_isa.act(pe_isa.OP_LEVEL, scl, 1, d),
            pe_isa.act(pe_isa.OP_STOP, sda, 1, d),
            pe_isa.act(pe_isa.OP_REARM, 0, 1, d)]
    park = pe_isa.ACT_BASE + len(prog) * pe_isa.ACT_BYTES
    prog.append(pe_isa.act(pe_isa.OP_REARM, 0, 0, 500))
    hdrs = [pe_isa.hdr(sda, scl, 0, d, 0, 2 * d, 3 * d, pe_isa.ACT_BASE,
                       order=pe_isa.ORDER_MSB)]
    hdrs += [pe_isa.hdr(p, p, 0, 500, 0, 200, 240, park)
             for p in range(8) if p not in (sda, scl)][:4]
    img = list(pe_isa.full_store(b"".join(hdrs) + b"".join(prog)))
    await run_loaded(dut, img, feed=False)

    async def feed_5b():
        # ⭐ ONE BYTE VALUE, so a push dropped on a full queue changes nothing
        # the check reads; paced, because gate level has no depth to read
        while True:
            await push_nibble(dut, 0x5, 0)
            await push_nibble(dut, 0xB, 0)
            await ClockCycles(dut.clk, 300)
    cocotb.start_soon(feed_5b())
    tr = await i2c_oe_trace(dut, 12000)
    got = decode_i2c(tr)
    dut._log.info("clocked TX bytes at the pins: %s"
                  % " ".join("%02X" % b for b in got))
    assert len(got) >= 5, ("only %d byte(s) on the wire in 12000 cycles -- "
                           "nothing to judge" % len(got))
    bad = [(i, b) for i, b in enumerate(got) if b != 0x5B]
    assert not bad, ("CLOCKED TX BYTES WRONG: 5B pushed, the wire carried %s "
                     "(index, byte) %s -- the drifting pattern 00 B5 6A D5 is "
                     "the pre-fix host load (silicon fix #2); a lone 00 at "
                     "index 0 is the reset register (silicon fix #8)"
                     % (" ".join("%02X" % b for b in got), bad[:4]))


@cocotb.test()
async def test_clocked_spi_read_at_the_pins(dut):
    """SILICON FIX #3 (ruling CI4), PINS ONLY: a clocked SPI master reads
    MISO. A byte in on MISO, the same byte out in the chip's RX frame.

    Two defects stood between them: (a) a clocked SHIFTIN sampled the lane
    HEADER's pin (MOSI) instead of the action's (MISO), and (b) a push-pull
    clocked receive waited for an OBSERVED clock rise -- and the master's SCK
    is a `uo_out` pin, which has no input path, so the capture never fired.
    Either one alone makes the chip receive 00. The program: CS low, one
    clocked 8-bit SHIFTIN on MISO, CS high; this test plays the SPI peer from
    the pins -- MISO's MSB when CS falls, the next bit on each SCK fall.
    ⛔ Must-fire: built with `M_CKRX_HEADER_PIN` or `M_CKRX_PP_OBSERVED`
    this FAILS in RTL simulation.
    """
    from corpus import P_M_CS, P_M_MISO, P_M_MOSI, P_M_SCLK
    d, want = 25, 0x5B
    prog = [pe_isa.act(pe_isa.OP_LEVEL, P_M_CS, 0, d),
            pe_isa.act_shiftin_clocked(P_M_MISO, d, nbits=8),
            pe_isa.act(pe_isa.OP_LEVEL, P_M_CS, 1, d),
            pe_isa.act(pe_isa.OP_REARM, 0, 1, d)]
    park = pe_isa.ACT_BASE + len(prog) * pe_isa.ACT_BYTES
    prog.append(pe_isa.act(pe_isa.OP_REARM, 0, 0, 500))
    hdrs = [pe_isa.hdr(P_M_MOSI, P_M_SCLK, 1, d, 0, 2 * d, 3 * d,
                       pe_isa.ACT_BASE, order=pe_isa.ORDER_MSB)]
    hdrs += [pe_isa.hdr(p, p, 0, 500, 0, 200, 240, park) for p in (1, 2, 3, 4)]
    img = list(pe_isa.full_store(b"".join(hdrs) + b"".join(prog)))
    await run_loaded(dut, img, feed=False)
    cs_b, sck_b = P_M_CS - 8, P_M_SCLK - 8          # uo_out bit indices

    # ⛔ THE MODE IS THE SCK LEVEL AT CS FALL, as the part decides it. Mode 3
    # (SCK high): the first SCK fall presents bit 7. Mode 0 (SCK low): bit 7
    # is presented at CS fall, the next bit at each fall. A clocked receive
    # ENDS WITH SCK LOW (I6), so the first read after reset is mode 3 and every
    # later one mode 0 -- both of ruling CI4's modes from one program. The
    # first version of this peer presented bit 7 at CS fall in both modes and
    # the mode-3 read came back B7: the peer one bit ahead, not the chip.
    modes = []

    async def peer():
        pcs, psck, k = "1", "1", 0
        while True:
            await ClockCycles(dut.clk, 1)
            uo = str(dut.uo_out.value)
            cs, sck = bit(uo, cs_b), bit(uo, sck_b)
            if cs == "0" and pcs == "1":
                modes.append(3 if sck == "1" else 0)
                k = -1 if sck == "1" else 0
            elif cs == "0" and sck == "0" and psck == "1":
                k += 1                               # each SCK fall: next bit
            if cs == "0" and k < 8:
                dut.ob_oe.value = 1 << P_M_MISO
                dut.ob_val.value = ((want >> (7 - max(k, 0))) & 1) << P_M_MISO
            else:
                dut.ob_oe.value = 0
            pcs, psck = cs, sck
    cocotb.start_soon(peer())
    frames = await harvest_frames(dut, 8000)
    got = lane_payloads(frames, 0)
    dut._log.info("clocked SPI read at the pins: %s (modes %s)"
                  % (" ".join("%02X" % b for b in got), modes[:len(got)]))
    assert len(got) >= 3, ("only %d RX frame(s) from lane 0 -- nothing to "
                           "judge" % len(got))
    assert {3, 0} <= set(modes[:len(got)]), (
        "the reads judged were not both modes: %s" % modes[:len(got)])
    assert all(b == want for b in got), (
        "CLOCKED SPI READ WRONG: %02X driven on MISO, the chip received %s -- "
        "00 is silicon fix #3 (header pin sampled, or the push-pull capture "
        "never fired)" % (want, " ".join("%02X" % b for b in got)))


def _spi_read_image(d, flags):
    """One clocked SPI read (CS low, 8-bit clocked SHIFTIN on MISO, CS high)
    on the master's ruled pins, header mode bits `flags` (ruling HDR)."""
    from corpus import P_M_CS, P_M_MISO, P_M_MOSI, P_M_SCLK
    prog = [pe_isa.act(pe_isa.OP_LEVEL, P_M_CS, 0, d),
            pe_isa.act_shiftin_clocked(P_M_MISO, d, nbits=8),
            pe_isa.act(pe_isa.OP_LEVEL, P_M_CS, 1, d),
            pe_isa.act(pe_isa.OP_REARM, 0, 1, d)]
    park = pe_isa.ACT_BASE + len(prog) * pe_isa.ACT_BYTES
    prog.append(pe_isa.act(pe_isa.OP_REARM, 0, 0, 500))
    hdrs = [pe_isa.hdr(P_M_MOSI, P_M_SCLK, 1, d, flags, 2 * d, 3 * d,
                       pe_isa.ACT_BASE, order=pe_isa.ORDER_MSB)]
    hdrs += [pe_isa.hdr(p, p, 0, 500, 0, 200, 240, park) for p in (1, 2, 3, 4)]
    return list(pe_isa.full_store(b"".join(hdrs) + b"".join(prog)))


@cocotb.test()
async def test_half_high_phase_at_the_pins(dut):
    """RULING CE1, PINS ONLY: a HALF_HIGH clocked lane's HIGH phase is d/2.

    A push-pull clocked receive on the master's SCLK (a `uo_out` pin, so no
    pull-up decides the edges): the pins must show SCK LOW = d and HIGH = d/2
    -- the phase the CE1 RTL adds. ⛔ Must-fire: built with `M_HALF_IGNORED`
    the HIGH phase is d, and this FAILS in RTL simulation.
    """
    from corpus import P_M_SCLK
    d = 82
    await run_loaded(dut, _spi_read_image(d, pe_isa.FLAG_HALF_HIGH),
                     feed=False)
    sck_b = P_M_SCLK - 8
    prev, t, edges = None, 0, []
    for _ in range(6000):
        await ClockCycles(dut.clk, 1)
        t += 1
        s = bit(str(dut.uo_out.value), sck_b)
        if prev is not None and s != prev and s in "01":
            edges.append((t, s))
        prev = s
    highs = sorted({b[0] - a[0] for a, b in zip(edges, edges[1:])
                    if a[1] == "1"})
    lows = sorted({b[0] - a[0] for a, b in zip(edges, edges[1:])
                   if a[1] == "0"})
    dut._log.info("HALF_HIGH at the pins: SCK HIGH widths %s, LOW widths %s "
                  "(d = %d)" % (highs[:6], lows[:6], d))
    assert len(edges) >= 20, "only %d SCK edges -- nothing to judge" % len(edges)
    assert (d >> 1) in highs and d not in highs, (
        "HALF_HIGH NOT AT THE PINS: SCK HIGH widths %s, want d/2 = %d (d = %d "
        "is the selector ignored)" % (highs, d >> 1, d))
    assert d in lows, "the LOW phase moved: widths %s, want d = %d" % (lows, d)


@cocotb.test()
async def test_clocked_spi_mode1_read_at_the_pins(dut):
    """RULING CE2, PINS ONLY: SPI MODE 1/2 -- an inverted SCLK, a byte in on
    MISO, the same byte out in the chip's RX frame.

    CLK_INV inverts the master's SCLK, so the chip samples on the pad's FALL.
    This test plays a mode 1/2 peer from the pins: the mode is the SCK level
    at CS fall (low = mode 1: the bit goes out on each RISE, the first rise
    presenting bit 7; high = mode 2: bit 7 at CS fall, the next on each rise).
    ⛔ Must-fire: built with `M_CLKINV_IGNORED` the clock is not inverted, the
    peer drives on the edge the chip samples, and this FAILS in RTL simulation.
    """
    from corpus import P_M_CS, P_M_MISO, P_M_SCLK
    d, want = 25, 0x5B
    await run_loaded(dut, _spi_read_image(d, pe_isa.FLAG_CLK_INV), feed=False)
    cs_b, sck_b = P_M_CS - 8, P_M_SCLK - 8
    modes = []

    async def peer():
        pcs, psck, k = "1", "1", 0
        while True:
            await ClockCycles(dut.clk, 1)
            uo = str(dut.uo_out.value)
            cs, sck = bit(uo, cs_b), bit(uo, sck_b)
            if cs == "0" and pcs == "1":
                modes.append(2 if sck == "1" else 1)
                k = 0 if sck == "1" else -1
            elif cs == "0" and sck == "1" and psck == "0":
                k += 1                               # each SCK RISE: next bit
            if cs == "0" and k < 8:
                dut.ob_oe.value = 1 << P_M_MISO
                dut.ob_val.value = ((want >> (7 - max(k, 0))) & 1) << P_M_MISO
            else:
                dut.ob_oe.value = 0
            pcs, psck = cs, sck
    cocotb.start_soon(peer())
    frames = await harvest_frames(dut, 8000)
    got = lane_payloads(frames, 0)
    dut._log.info("mode 1/2 SPI read at the pins: %s (modes %s)"
                  % (" ".join("%02X" % b for b in got), modes[:len(got)]))
    assert len(got) >= 3, ("only %d RX frame(s) from lane 0 -- nothing to "
                           "judge" % len(got))
    assert 1 in modes[:len(got)], (
        "no read was MODE 1 at the pins (modes %s): the clock was not "
        "inverted" % modes[:len(got)])
    assert all(b == want for b in got), (
        "MODE 1/2 SPI READ WRONG: %02X driven on MISO, the chip received %s"
        % (want, " ".join("%02X" % b for b in got)))
