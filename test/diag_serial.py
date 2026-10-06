"""THROWAWAY DIAGNOSTIC -- decode the 3-pin serial host view at the pins.

Not a test. Measures the readback stream's framing and alignment so the real
test asserts the DESIGN's behaviour rather than being fitted to whatever came
out. Safe to delete.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

CLK_NS = 20
PIN_PROG, PIN_WR, PIN_PTR = 7, 6, 5
SER_DATA, SER_STRB, SER_VLD = 4, 5, 6


def ctrl(prog=0, wr=0, ptr=0):
    return (prog << PIN_PROG) | (wr << PIN_WR) | (ptr << PIN_PTR)


async def start(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)


async def write_byte(dut, val):
    dut.uio_in.value = val
    dut.ui_in.value = ctrl(prog=1, wr=0)
    await ClockCycles(dut.clk, 3)
    dut.ui_in.value = ctrl(prog=1, wr=1)
    await ClockCycles(dut.clk, 3)
    dut.ui_in.value = ctrl(prog=1, wr=0)
    await ClockCycles(dut.clk, 3)


@cocotb.test()
async def diag(dut):
    await start(dut)
    img = [0xAA, 0x22, 0x33, 0x44, 0x55, 0x66]
    dut.ui_in.value = ctrl(prog=1, ptr=1)
    await ClockCycles(dut.clk, 3)
    dut.ui_in.value = ctrl(prog=1)
    await ClockCycles(dut.clk, 2)
    for b in img:
        await write_byte(dut, b)
    dut._log.info("loaded %s" % [hex(b) for b in img])

    # ---- REWIND readback with a reset, which the store should survive ----
    # rb_ptr resets only on rst_n; the store is deliberately UNRESET, so a
    # reset should rewind the readback walk while keeping the image.
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 4)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)
    dut.ui_in.value = ctrl(prog=1)
    await ClockCycles(dut.clk, 2)
    # ---- FRAME ON `valid`, not on a fixed stride --------------------
    # ser_v is high only while a frame is shifting, so its rising edge is the
    # frame boundary. Chunking the strobed bits into fixed groups of 9 assumes
    # the harvest began exactly at a boundary, and misaligned the whole stream.
    frames = []
    cur = []
    prev_v = "0"
    firstx = None
    for c in range(900):
        await ClockCycles(dut.clk, 1)
        b = str(dut.uo_out.value)              # binstr, MSB first, X-tolerant
        d, st, v = b[7 - SER_DATA], b[7 - SER_STRB], b[7 - SER_VLD]
        if v not in "01" or st not in "01":
            if firstx is None:
                firstx = (c, b)
            continue
        if v == "1" and prev_v == "0":
            cur = []
        if v == "1" and st == "1":
            cur.append(d)
        if v == "0" and prev_v == "1":
            if len(cur) == 9:
                frames.append(cur)
            cur = []
        prev_v = v
    dut._log.info("frames: %d   first X on the trio: %s"
                  % (len(frames), firstx))
    out = []
    for nine in frames:
        if any(ch not in "01" for ch in nine):
            out.append((nine[8] if nine[8] in "01" else "?", "X"))
            continue
        pay = 0
        for k in range(8):
            pay |= int(nine[k]) << k
        out.append((nine[8], "0x%02X" % pay))
    frames = out
    dut._log.info("frames (marker, payload):")
    for k, (m, p) in enumerate(frames[:14]):
        kind = {"1": "STATUS", "0": "payload"}.get(m, "?mark=" + str(m))
        dut._log.info("  %2d  %-7s %s" % (k, kind, p))
