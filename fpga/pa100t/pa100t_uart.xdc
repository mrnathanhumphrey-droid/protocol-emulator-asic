################################################################################
# Puzhi PA100T-EDU (XC7A100T-2FGG484) -- the pins phase 0 uses.
#
# PROVENANCE. Every pin below was resolved from the vendor's own documentation
# and confirmed on this board in an earlier, separate project of Nathan's:
#   [SCH]    Puzhi PA-EDU schematic, rev 1.0, 2025-08-27 (vendor pack)
#   [VIVADO] get_package_pins PIN_FUNC on xc7a100tfgg484, Vivado 2026.1
#   [PUZHI]  Puzhi's reference XDCs (course demos 3_3/3_5/3_8/3_12)
# The vendor PDFs are third-party and are NOT in this repository.
################################################################################

# [SCH] VCCO_0 ties to 3.3 V.
set_property CFGBVS VCCO        [current_design]
set_property CONFIG_VOLTAGE 3.3 [current_design]

# SYSTEM CLOCK -- 200 MHz differential, bank 34, R4 (P) / T4 (N).
# ⛔ DIFF_SSTL135, NOT the vendor demos' DIFF_SSTL15: [SCH] VCCO_34 = 1.35 V
#    (DDR3L bank; MIG generates SSTL135 for it). ⛔ No DIFF_TERM: R47 = 100 ohm
#    already terminates the pair on the board.
set_property -dict {PACKAGE_PIN R4 IOSTANDARD DIFF_SSTL135} [get_ports sys_clk_p]
set_property -dict {PACKAGE_PIN T4 IOSTANDARD DIFF_SSTL135} [get_ports sys_clk_n]
create_clock -period 5.000 -name sys_clk -waveform {0.000 2.500} [get_ports sys_clk_p]

# RESET KEY -- active low, R14, 4.7K/10uF RC (slow): synchronised in the top.
set_property -dict {PACKAGE_PIN R14 IOSTANDARD LVCMOS33} [get_ports sys_rstn]
set_false_path -from [get_ports sys_rstn]

# LEDs -- bank 15 (3.3 V via strap R23 as shipped). [PUZHI] order.
set_property -dict {PACKAGE_PIN J21 IOSTANDARD LVCMOS33} [get_ports {led[0]}]
set_property -dict {PACKAGE_PIN J19 IOSTANDARD LVCMOS33} [get_ports {led[1]}]
set_property -dict {PACKAGE_PIN H19 IOSTANDARD LVCMOS33} [get_ports {led[2]}]
set_property -dict {PACKAGE_PIN K18 IOSTANDARD LVCMOS33} [get_ports {led[3]}]
set_property -dict {PACKAGE_PIN K19 IOSTANDARD LVCMOS33} [get_ports {led[4]}]
set_property -dict {PACKAGE_PIN L19 IOSTANDARD LVCMOS33} [get_ports {led[5]}]
set_false_path -to [get_ports {led[*]}]

# UART -- CH340E bridge on its OWN USB connector (JTAG is the FT232H; both run
# at once). Direction read off [SCH] sheet 9: CH340E TXD -> P14 (FPGA input),
# CH340E RXD <- P15 (FPGA output). ⛔ No flow control (CTS/RTS unconnected).
set_property -dict {PACKAGE_PIN P14 IOSTANDARD LVCMOS33} [get_ports uart_rx]
set_property -dict {PACKAGE_PIN P15 IOSTANDARD LVCMOS33} [get_ports uart_tx]
set_false_path -from [get_ports uart_rx]
set_false_path -to   [get_ports uart_tx]
