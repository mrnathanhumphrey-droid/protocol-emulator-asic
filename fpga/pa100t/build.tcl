# build.tcl -- non-project Vivado build of the phase-0 UART-rx bring-up for the
# Puzhi PA100T-EDU (xc7a100tfgg484-2).
#
# Usage (from the repo root):
#   C:\AMDDesignTools\2026.1\Vivado\bin\vivado.bat -mode batch -source fpga/pa100t/build.tcl
# Output: fpga/build/pa100t/ -- pa100t_top.bit, timing and utilisation reports.
#
# ⛔ THE CHIP RTL IS READ FROM src/ UNCHANGED -- the same three files the TT
# flow hardens (info.yaml). Nothing here may define an `M_*` mutant macro.
# ⛔ A NEGATIVE WNS IS A FAILED BUILD: the script exits non-zero and writes no
# bitstream, so a board never runs a design that does not meet 50 MHz.

set root [file normalize [file join [file dirname [info script]] .. ..]]
set out  [file join $root fpga build pa100t]
file mkdir $out
set part xc7a100tfgg484-2

foreach f {pe_engine.v pe_store.v project.v} {
  read_verilog [file join $root src $f]
}
read_verilog [file join $root fpga rtl pe_fpga_core.v]
read_verilog [file join $root fpga pa100t pa100t_top.v]
read_xdc     [file join $root fpga pa100t pa100t_uart.xdc]

# the ROM image: $readmemh resolves against the working directory
set img [file join $root fpga images uart_rx_434.hex]
file copy -force $img [file join $out uart_rx_434.hex]
cd $out

synth_design -top pa100t_top -part $part
opt_design
place_design
route_design

report_timing_summary -file [file join $out timing_summary.rpt]
report_utilization    -file [file join $out utilization.rpt]
set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
set whs [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -hold]]
puts "PE_FPGA: setup WNS = $wns ns, hold WHS = $whs ns"
if {$wns < 0 || $whs < 0} {
  puts "PE_FPGA: *** TIMING NOT MET -- no bitstream written"
  exit 1
}
write_bitstream -force [file join $out pa100t_top.bit]
puts "PE_FPGA: bitstream [file join $out pa100t_top.bit]"
