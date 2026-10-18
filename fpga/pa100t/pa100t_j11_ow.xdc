################################################################################
# Puzhi PA100T-EDU -- J11 for the 1-Wire build (read by `build.tcl ow` only,
# ON TOP OF pa100t_uart.xdc).
#
# J11 = SIP4 2.54 mm: 1 GND, 2 3V3, 3 B20 (IO_L16P_T2_16), 4 A20
# (IO_L16N_T2_16), all 3.3 V -- [SCH] (vendor pack, not in this repository),
# Nathan's notes 10-14. `pa100t_edu_timing_master.xdc` (Downloads) is BOGUS.
#
# DQ = J11 pin 4 (A20), OPEN DRAIN in pa100t_top.v (low or released).
# ⭐ The real pull-up is the 4.7k on the breadboard (DQ -> 3V3, DS18B20
#    datasheet); the FPGA's internal PULLUP is a backup only (Wilson 10-17).
################################################################################
set_property -dict {PACKAGE_PIN A20 IOSTANDARD LVCMOS33 PULLUP TRUE DRIVE 8 SLEW SLOW} [get_ports j11_dq]
# asynchronous to the fabric: synchronised (2 flops) in pe_fpga_core
set_false_path -from [get_ports j11_dq]
set_false_path -to   [get_ports j11_dq]
