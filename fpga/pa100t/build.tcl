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

#
# THE 1-WIRE BUILD (Wilson 10-17):  ... -source fpga/pa100t/build.tcl -tclargs ow
#   defines PE_OW (pa100t_top.v: J11 pin 4 = DQ, open drain), adds
#   pa100t_j11_ow.xdc, loads test/onewire_fpga_image.hex + the feed
#   fpga/feeds/onewire_fpga_feed.{hex,params} -- the files
#   fpga/sim/run_fpga_onewire.py simulated and checks are tracked unchanged.
#   Output: fpga/build/pa100t_ow/pa100t_ow1wire.bit (its own folder and name,
#   so it is never mistaken for the UART build).
#
# THE I2C BUILD (Wilson 10-17):  ... -source fpga/pa100t/build.tcl -tclargs i2c
#   defines PE_I2C (J11 pin 3 = SCL, pin 4 = SDA, both open drain), adds
#   pa100t_j11_i2c.xdc, loads fpga/images/i2c_fram_fpga.hex + the feed
#   fpga/feeds/i2c_fram_{feed,falls}.hex + i2c_fram.params -- the files
#   fpga/sim/run_fpga_i2c.py simulated and checks are tracked unchanged.
#   Output: fpga/build/pa100t_i2c/pa100t_i2cfram.bit. BOTH pins must be open
#   drain in the netlist, or no bitstream.

set root [file normalize [file join [file dirname [info script]] .. ..]]
set ow   [expr {[lsearch -exact $argv ow] >= 0}]
set i2c  [expr {[lsearch -exact $argv i2c] >= 0}]
if {$ow && $i2c} { puts "PE_FPGA: *** ow and i2c are separate builds"; exit 1 }
set out  [file join $root fpga build [expr {$ow ? "pa100t_ow" : $i2c ? "pa100t_i2c" : "pa100t"}]]
set bitname [expr {$ow ? "pa100t_ow1wire.bit" : $i2c ? "pa100t_i2cfram.bit" : "pa100t_top.bit"}]
file mkdir $out
set part xc7a100tfgg484-2

foreach f {pe_engine.v pe_store.v project.v} {
  read_verilog [file join $root src $f]
}
read_verilog [file join $root fpga rtl pe_fpga_core.v]
read_verilog [file join $root fpga pa100t pa100t_top.v]
read_xdc     [file join $root fpga pa100t pa100t_uart.xdc]

# the ROM image: $readmemh resolves against the working directory
if {$ow} {
  read_xdc [file join $root fpga pa100t pa100t_j11_ow.xdc]
  file copy -force [file join $root test onewire_fpga_image.hex] [file join $out onewire_fpga_image.hex]
  file copy -force [file join $root fpga feeds onewire_fpga_feed.hex] [file join $out onewire_fpga_feed.hex]
  set fh [open [file join $root fpga feeds onewire_fpga_feed.params]]
  array set prm [string map {"\n" " "} [read $fh]]
  close $fh
  set gen [list "IMG=\"onewire_fpga_image.hex\"" "FEED=\"onewire_fpga_feed.hex\"" \
               NFEED=$prm(NFEED) POLLIDX=$prm(POLLIDX) PER2=$prm(PER2) MARGIN=$prm(MARGIN)]
  puts "PE_FPGA: 1-Wire build, generics $gen"
} elseif {$i2c} {
  read_xdc [file join $root fpga pa100t pa100t_j11_i2c.xdc]
  file copy -force [file join $root fpga images i2c_fram_fpga.hex] [file join $out i2c_fram_fpga.hex]
  file copy -force [file join $root fpga feeds i2c_fram_feed.hex] [file join $out i2c_fram_feed.hex]
  file copy -force [file join $root fpga feeds i2c_fram_falls.hex] [file join $out i2c_fram_falls.hex]
  set fh [open [file join $root fpga feeds i2c_fram.params]]
  array set prm [string map {"\n" " "} [read $fh]]
  close $fh
  set gen [list "IMG=\"i2c_fram_fpga.hex\"" "FEED=\"i2c_fram_feed.hex\"" \
               "FALLS=\"i2c_fram_falls.hex\"" NFEED=$prm(NFEED) NRX=$prm(NRX)]
  puts "PE_FPGA: I2C build, generics $gen"
} else {
  set img [file join $root fpga images uart_rx_434.hex]
  file copy -force $img [file join $out uart_rx_434.hex]
}
cd $out

if {$ow} {
  synth_design -top pa100t_top -part $part -verilog_define PE_OW -generic $gen
} elseif {$i2c} {
  synth_design -top pa100t_top -part $part -verilog_define PE_I2C -generic $gen
} else {
  synth_design -top pa100t_top -part $part
}
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
# ⭐ EVERY J11 PIN IS OPEN DRAIN IN THE NETLIST (Wilson's check): the pad's
# buffer is an OBUFT / IOBUF whose data input is constant 0 -- it can only
# pull low or release. Printed for the record, and a hard stop if not.
proc od_check {port site out} {
  set pin [get_ports $port]
  set buf [get_cells -of_objects [get_nets -of_objects $pin]]
  puts "PE_FPGA: $port -> [get_property PACKAGE_PIN $pin] [get_property IOSTANDARD $pin] PULLUP=[get_property PULLUP $pin], buffer(s): [get_property REF_NAME $buf]"
  if {[get_property PACKAGE_PIN $pin] ne $site} {
    puts "PE_FPGA: *** $port is not on $site -- no bitstream written"; exit 1
  }
  set tbuf [get_cells -quiet $buf -filter {REF_NAME == IOBUF || REF_NAME == OBUFT}]
  set ok_od 0
  if {[llength $tbuf] == 1} {
    set inet [get_nets -of_objects [get_pins -of_objects $tbuf -filter {REF_PIN_NAME == I}]]
    set ntype [get_property TYPE $inet]
    puts "PE_FPGA: $port [get_property REF_NAME $tbuf] data input I <- net $inet (TYPE $ntype)"
    set ok_od [expr {$ntype eq "GROUND"}]
  }
  if {!$ok_od} {
    puts "PE_FPGA: *** $port is NOT open drain (I not tied to ground) -- no bitstream written"; exit 1
  }
  puts "PE_FPGA: $port OPEN DRAIN: data input tied to ground; it only pulls low or releases"
}
if {$ow} {
  report_io -file [file join $out io.rpt]
  od_check j11_dq A20 $out
}
if {$i2c} {
  report_io -file [file join $out io.rpt]
  od_check j11_scl B20 $out
  od_check j11_sda A20 $out
}
write_bitstream -force [file join $out $bitname]
puts "PE_FPGA: bitstream [file join $out $bitname]"
