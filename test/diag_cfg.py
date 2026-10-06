"""THROWAWAY: is config_err set, and does dispatch really stop? Safe to delete."""
import os, sys
import cocotb
from cocotb.triggers import ClockCycles
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test import start, load_image, read_hex, ctrl, bit


@cocotb.test()
async def diag(dut):
    await start(dut)
    img = read_hex("cfgerr_image.hex")
    await load_image(dut, img)
    dut._log.info("after load: hdr_done=%s config_err=%s"
                  % (dut.user_project.u_eng.hdr_done.value, dut.user_project.u_eng.config_err.value))
    dut._log.info("  l_pin[0]=%s l_mode[0]=%s pin_pp=%s"
                  % (dut.user_project.u_eng.l_pin[0].value, dut.user_project.u_eng.l_mode[0].value,
                     dut.user_project.u_eng.pin_pp.value))
    dut.ui_in.value = ctrl(prog=0)
    dut.uio_in.value = 0xFF
    seen = {}
    first0 = None
    for c in range(1210):
        await ClockCycles(dut.clk, 1)
        b = str(dut.uo_out.value)
        v = b[7]                      # uo_out[0]
        seen[v] = seen.get(v, 0) + 1
        if v == "0" and first0 is None:
            first0 = (c, b, str(dut.user_project.u_eng.config_err.value),
                      str(dut.user_project.u_eng.hdr_done.value))
    dut._log.info("uo_out[0] histogram: %s" % seen)
    dut._log.info("first 0 at: %s" % (first0,))
