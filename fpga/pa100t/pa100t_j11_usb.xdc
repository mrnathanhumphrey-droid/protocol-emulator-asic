# Puzhi PA100T-EDU -- J11 + the SD slot for the USB build (read by `build.tcl usb` only,
# Wilson 11-14; design delta comms/USB_PIN_DELTA.md, read off the Puzhi schematic rev 1.0
# D:\Chips_And_Stuff\fpga\vendor\Puzhi_PA-EDU_Schematic_rev1.0_2025-08-27.pdf).
#
# J11 = SIP4 2.54 mm: 1 GND, 2 3V3, 3 B20 (IO_L16P_T2_16), 4 A20 (IO_L16N_T2_16); bank 16 at
#   3.3 V (VCCO_16 <- VDD_3V3 via R26 0R; R27/R28 to 2.5/1.8 V not fitted). No board pull-up or
#   series resistor on either line (sheet 15).
# D+ = J11 pin 3 (B20) = uio[3]; D- = J11 pin 4 (A20) = uio[2]; PUSH-PULL from pa100t_top.v,
#   high-Z unless the program runs.
# Soft attach = SD slot DAT0 (AB18, IO_L17N_T2_A13_D29_14, bank 14 at 3.3 V; no board pull-up or
#   series resistor, sheet 10; NOT CMD, whose R80 4.7k pulls up): driven high only while the
#   program runs, through the breadboard's 1.5k to D-.
# Configuration never drives these pins (mode 001 Master SPI; their dual functions are BPI
#   lines), and PUDC_B is high (R45), so they float while the FPGA configures.
#
# ⛔ NO PULLUP on any of the three: an internal pull-up of tens of kOhm against the host's
#   15k pull-down is a partial attach (the ow / i2c builds set PULLUP on B20/A20; not here).
# Wilson 11-14: SLEW SLOW + DRIVE 4 slow the edges at the source; series 27-68 Ohm on the
#   breadboard damp the ringing.
set_property -dict {PACKAGE_PIN B20  IOSTANDARD LVCMOS33 DRIVE 4 SLEW SLOW} [get_ports j11_dp]
set_property -dict {PACKAGE_PIN A20  IOSTANDARD LVCMOS33 DRIVE 4 SLEW SLOW} [get_ports j11_dm]
set_property -dict {PACKAGE_PIN AB18 IOSTANDARD LVCMOS33 DRIVE 4 SLEW SLOW} [get_ports usb_pu]

set_false_path -from [get_ports {j11_dp j11_dm}]
set_false_path -to   [get_ports {j11_dp j11_dm usb_pu}]
