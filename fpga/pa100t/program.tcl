# program.tcl -- load fpga/build/pa100t/pa100t_top.bit into the PA100T-EDU's
# configuration SRAM over JTAG. ⛔ Flash is never written: a power cycle
# returns the board to whatever it held before.
#
# Usage (repo root):
#   C:\AMDDesignTools\2026.1\Vivado\bin\vivado.bat -mode batch -source fpga/pa100t/program.tcl
#
# The board has TWO USB ports and only one is JTAG: the FT232H. The CH340E is
# UART only -- a cable on it alone looks exactly like a dead board.

#   ... -source fpga/pa100t/program.tcl -tclargs ow   -> the 1-Wire build
#   (fpga/build/pa100t_ow/pa100t_ow1wire.bit)

set root [file normalize [file join [file dirname [info script]] .. ..]]
if {[lsearch -exact $argv ow] >= 0} {
  set bit [file join $root fpga build pa100t_ow pa100t_ow1wire.bit]
} else {
  set bit [file join $root fpga build pa100t pa100t_top.bit]
}
if {![file exists $bit]} { error "no bitstream at $bit -- run build.tcl first" }
puts "PE_PROGRAM: bitstream $bit ([file size $bit] bytes, built [clock format [file mtime $bit] -format {%Y-%m-%d %H:%M:%S}])"

open_hw_manager
connect_hw_server -url localhost:3121
if {[llength [get_hw_targets -quiet]] == 0} {
  error "PE_PROGRAM: no JTAG target -- is the cable on the FT232H (JTAG) port and the board powered?"
}
open_hw_target
current_hw_device [lindex [get_hw_devices] 0]
set dev [current_hw_device]
refresh_hw_device -update_hw_probes false $dev
puts "PE_PROGRAM: device $dev part [get_property PART $dev] IDCODE 0x[get_property IDCODE_HEX $dev]"
if {![string match "xc7a100t*" [get_property PART $dev]]} {
  error "PE_PROGRAM: wrong part on the JTAG chain -- nothing programmed"
}
set_property PROGRAM.FILE $bit $dev
program_hw_devices $dev
# success is Vivado's own "End of startup status: HIGH" (Labtools 27-3164) in the
# log; this Vivado has no REGISTER.CONFIG_STATUS.BIT13_DONE_PIN property
puts "PE_PROGRAM: programmed -- check the log for 'End of startup status: HIGH'"
close_hw_target
disconnect_hw_server
close_hw_manager
