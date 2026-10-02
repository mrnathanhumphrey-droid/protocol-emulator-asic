# SPDX-FileCopyrightText: © 2026 Nathan Humphrey
# SPDX-License-Identifier: Apache-2.0
"""Rungs 1 + 2 -- the program-load path and open-drain through `uio_oe`.

⛔⛔ EVERY CHECK HERE IS AT THE PINS, DELIBERATELY. Nothing reads `dut.mem` or any
internal signal, so the IDENTICAL test runs against the RTL and against the
synthesized gate-level netlist (`gl_test` in CI). A test that peeks inside passes
on RTL and cannot run on the netlist, which is where the model and the silicon are
first able to disagree.

⛔ AND THE F5 PROPERTY GETS A MUST-FIRE ARM. "The design never drives a 1 on an
open-drain pin" is trivially true of a design whose output enable is always 0, so
the test also proves the enable DOES assert. Everything in this project that went
wrong went wrong by passing vacuously.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

CLK_NS = 20              # 50 MHz, matching info.yaml clock_hz
PIN_PROG, PIN_WR, PIN_RST = 7, 6, 5
OD_SCL, OD_SDA = 0, 1
DIV = 256                # run-mode read-pointer holds each byte this many clocks


def ctrl(prog=0, wr=0, rst=0):
    return (prog << PIN_PROG) | (wr << PIN_WR) | (rst << PIN_RST)


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
    ASYNCHRONOUS pin strobe: two flops to resolve metastability, a third to see the
    edge. `offset` nudges the pulse off the clock edge to exercise exactly that."""
    dut.uio_in.value = val
    dut.ui_in.value = ctrl(prog=1, wr=0)
    await ClockCycles(dut.clk, 3)
    dut.ui_in.value = ctrl(prog=1, wr=1)
    await ClockCycles(dut.clk, 3 + offset)
    dut.ui_in.value = ctrl(prog=1, wr=0)
    await ClockCycles(dut.clk, 3)


@cocotb.test()
async def test_pointer_echo_and_autoincrement(dut):
    """RUNG 1: the address bus is deleted by auto-increment, and `uo_out` echoes
    the pointer so a host can confirm a write LANDED."""
    await start(dut)
    dut.ui_in.value = ctrl(prog=1, rst=1)
    await ClockCycles(dut.clk, 3)
    dut.ui_in.value = ctrl(prog=1)
    await ClockCycles(dut.clk, 2)
    assert int(dut.uo_out.value) == 0, "pointer did not start at 0"

    for n in range(1, 6):
        await write_byte(dut, 0xA0 + n)
        got = int(dut.uo_out.value)
        assert got == n, "after %d writes the pointer echo is %d" % (n, got)
    dut._log.info("pointer auto-increments 0->5 with no address bus")


@cocotb.test()
async def test_ptr_rst(dut):
    """RUNG 1: pointer reset comes from a DEDICATED input, never from `uio`."""
    await start(dut)
    for n in range(3):
        await write_byte(dut, 0x10 + n)
    assert int(dut.uo_out.value) == 3
    dut.ui_in.value = ctrl(prog=1, rst=1)
    await ClockCycles(dut.clk, 3)
    dut.ui_in.value = ctrl(prog=1)
    await ClockCycles(dut.clk, 2)
    assert int(dut.uo_out.value) == 0, "ptr_rst did not return the pointer to 0"


@cocotb.test()
async def test_load_then_readback(dut):
    """RUNG 1: the loaded image is OBSERVABLE AT THE PINS.

    ⭐ This is what makes "provably loaded correctly" checkable from outside, and
    it is why the pointer echo alone is not enough -- the echo says a write
    happened, this says WHAT was written.
    """
    await start(dut)
    img = [0x55, 0x0F, 0xA5, 0x3C]
    dut.ui_in.value = ctrl(prog=1, rst=1)
    await ClockCycles(dut.clk, 3)
    for b in img:
        await write_byte(dut, b)

    # halt, reload, resume -- leaving prog_mode restarts the read walk at 0
    dut.ui_in.value = ctrl(prog=0)
    dut.uio_in.value = 0
    await ClockCycles(dut.clk, 4)

    for i, want in enumerate(img):
        got = int(dut.uo_out.value)
        assert got == want, ("readback[%d] = 0x%02X, loaded 0x%02X"
                             % (i, got, want))
        dut._log.info("readback[%d] = 0x%02X  ok" % (i, got))
        await ClockCycles(dut.clk, DIV)      # advance to the next image byte


@cocotb.test()
async def test_uio_released_during_prog(dut):
    """RUNG 1 + 2: every `uio` is an INPUT throughout prog_mode, which is what
    lets the 8 protocol pins double as the load data port at zero pin cost."""
    await start(dut)
    dut.ui_in.value = ctrl(prog=1)
    await ClockCycles(dut.clk, 2)
    for _ in range(40):
        oe = int(dut.uio_oe.value)
        assert oe == 0, "uio_oe = 0x%02X during prog_mode; must be 0x00" % oe
        await ClockCycles(dut.clk, 1)
    dut._log.info("all 8 uio released for the whole of prog_mode")


@cocotb.test()
async def test_f5_open_drain(dut):
    """RUNG 2 / F5: open-drain IS expressible through `uio_oe`.

    F5: "open-drain I2C cannot be expressed through uio_oe as modelled" => "the pin
    abstraction is wrong and must be fixed before any protocol work continues."
    This is that test, and the old plan had it behind two rungs of protocol work.

    Two halves, and the second is the one that makes the first mean anything:
      (a) the design NEVER drives a 1 on an open-drain pin
      (b) the enable DOES assert -- otherwise (a) is vacuous
    """
    await start(dut)
    # load an image that exercises all four SCL/SDA combinations
    dut.ui_in.value = ctrl(prog=1, rst=1)
    await ClockCycles(dut.clk, 3)
    for b in (0b00, 0b01, 0b10, 0b11):
        await write_byte(dut, b)

    dut.ui_in.value = ctrl(prog=0)
    await ClockCycles(dut.clk, 4)

    od_mask = (1 << OD_SCL) | (1 << OD_SDA)
    asserted = 0
    released = 0
    samples = 0
    for _ in range(4 * DIV + 16):
        oe = int(dut.uio_oe.value)
        out = int(dut.uio_out.value)
        drives_high = oe & out & od_mask
        assert drives_high == 0, (
            "drove a HARD 1 on an open-drain pin: oe=0x%02X out=0x%02X" % (oe, out))
        if oe & od_mask:
            asserted |= oe & od_mask
        else:
            released += 1
        samples += 1
        await ClockCycles(dut.clk, 1)

    # (b) the must-fire arm
    assert asserted == od_mask, (
        "open-drain enable never asserted on both pins (saw 0x%02X of 0x%02X) -- "
        "the 'never drives high' check above would have been VACUOUS"
        % (asserted, od_mask))
    assert released > 0, "the pins were never released; open-drain needs both states"
    dut._log.info("F5 satisfied: pulled low on both pins, released %d/%d samples, "
                  "never drove a 1" % (released, samples))
