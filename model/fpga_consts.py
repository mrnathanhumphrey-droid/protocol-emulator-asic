"""fpga_consts -- FPGA-board timing facts, READ from the glue's one source, never typed.

usb_out_lat(): the cycles from the chip's uio_out to the J11 USB pins in the USB build -- the
glue's `localparam integer USB_OUT_LAT` (fpga/rtl/pe_fpga_core.v), checked by the glue
simulation (fpga/sim/tb_fpga_usb.v: the pins change exactly that many clock edges after uio_out).
usb_in_lat(): 0 -- the USB build feeds the raw pads into uio_in (the chip's own synchroniser does
the work; agent 1 11-14), checked by the same simulation (pads reach uio_in in the same cycle).
A WITNESS (hw) comparison subtracts these: the board answers USB_OUT_LAT cycles later than the
chip on outputs and 0 on inputs (Wilson 11-14).
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(ROOT, "fpga", "rtl", "pe_fpga_core.v")


def usb_out_lat():
    m = re.search(r"localparam\s+integer\s+USB_OUT_LAT\s*=\s*(\d+)\s*;",
                  open(CORE, encoding="utf-8").read())
    if not m:
        raise ValueError("pe_fpga_core.v: no USB_OUT_LAT localparam")
    return int(m.group(1))


def usb_in_lat():
    return 0


if __name__ == "__main__":
    print("USB_OUT_LAT", usb_out_lat(), "USB_IN_LAT", usb_in_lat())
