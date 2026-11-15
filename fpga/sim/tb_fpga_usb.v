/* tb_fpga_usb.v -- the USB build's glue, simulated before any Vivado run (Wilson 11-14).
 *
 * The whole FPGA core (USB = 1) boots usbdev_fpga.hex (the certified device program). The
 * bench is the board's pads plus the host's 15k pull-downs (weak 0 on D+ and D-); it checks
 * the glue's three promises (comms/USB_PIN_DELTA.md):
 *   A. RELEASED UNLESS RUNNING: while the glue's run_ok is low (reset, the boot load), D+, D-
 *      and the soft-attach pin are never driven (checked every cycle, after the registered
 *      output's USB_OUT_LAT);
 *   B. THE PULL-UP IS run_ok, one register late: high while the program runs, off otherwise;
 *   C. THE MAPPING, both ways: the raw pads reach uio_in[3] (D+) and uio_in[2] (D-) in the same
 *      cycle; uio_out/uio_oe bits 3 / 2 reach D+ / D- (the chip drives only when it answers a
 *      packet, so this part FORCES the chip's uio_out / uio_oe -- the glue is what is tested).
 * Verdict: `FPGA-USB: ok -- ...` or `*** FAIL fpga_usb: ...`.
 */
`default_nettype none
`timescale 1ns / 1ps
module tb_fpga_usb;
  reg clk = 0, rst_n = 0, rx = 1;
  wire tx;
  wire [5:0] led;
  wire running;
  `include "fpga/sim/fpga_clock.vh"
  always #(PE_CLK_HALF_NS) clk = ~clk;   // the target's clock, never typed

  wire dp_oe, dp_o, dm_oe, dm_o, pu;
  // the pads, as pa100t_top.v drives them; the host's 15k pull-downs as weak 0
  wire dp, dm, pu_pin;
  assign dp = dp_oe ? dp_o : 1'bz;
  assign dm = dm_oe ? dm_o : 1'bz;
  assign pu_pin = pu ? 1'b1 : 1'bz;
  assign (weak0, weak1) dp = 1'b0;
  assign (weak0, weak1) dm = 1'b0;
  // the bench may drive the bus itself (part C, inputs) with a strong level
  reg drv = 0, drv_dp = 0, drv_dm = 0;
  assign dp = drv ? drv_dp : 1'bz;
  assign dm = drv ? drv_dm : 1'bz;

  pe_fpga_core #(.IMG("fpga/images/usbdev_fpga.hex"), .CLK_HZ(PE_FPGA_CLK_HZ), .USB(1)) dut (
      .clk(clk), .rst_n(rst_n), .uart_rx(rx), .uart_tx(tx),
      .led(led), .running(running),
      .dq_in(dm), .dq_low(), .p3_in(dp), .p3_low(),
      .usb_dp_oe(dp_oe), .usb_dp_o(dp_o), .usb_dm_oe(dm_oe), .usb_dm_o(dm_o), .usb_pu(pu));

  integer fails = 0, cyc = 0, drove_off = 0, pu_bad = 0, run_cycles = 0, t_run = -1;
  reg run_ok_q = 0;
  // A + B, every cycle: the outputs follow run_ok one register late
  always @(posedge clk) begin
    cyc <= cyc + 1;
    run_ok_q <= dut.run_ok;
    if (!run_ok_q && (dp_oe || dm_oe || pu)) drove_off <= drove_off + 1;
    if (pu !== run_ok_q) pu_bad <= pu_bad + 1;
    if (run_ok_q) run_cycles <= run_cycles + 1;
    if (run_ok_q && t_run < 0) t_run <= cyc;
  end

  task fail(input [8*96-1:0] msg);
    begin
      $display("*** FAIL fpga_usb: %0s", msg);
      fails = fails + 1;
    end
  endtask

  integer i, k;
  initial begin
    repeat (20) @(posedge clk);
    rst_n = 1;
    // the boot load, then the program runs (bounded: the whole store at the loader's pace)
    for (i = 0; i < 200000 && !dut.run_ok; i = i + 1) @(posedge clk);
    if (!dut.run_ok) fail("the program never started (run_ok low after 200000 cycles)");
    repeat (50) @(posedge clk);
    if (pu_pin !== 1'b1) fail("soft-attach pin not driven high while running");
    // C, inputs: the raw pads reach uio_in in the same cycle
    drv = 1; drv_dp = 1; drv_dm = 0; #1;
    if (dut.uio_in[3] !== 1'b1 || dut.uio_in[2] !== 1'b0) fail("pads -> uio_in (D+ = 1, D- = 0) wrong");
    drv_dp = 0; drv_dm = 1; #1;
    if (dut.uio_in[3] !== 1'b0 || dut.uio_in[2] !== 1'b1) fail("pads -> uio_in (D+ = 0, D- = 1) wrong");
    drv = 0;
    // C, outputs: force the chip's uio_out / uio_oe bits 3 and 2
    @(negedge clk);
    force dut.uio_oe = 8'b0000_1100;
    force dut.uio_out = 8'b0000_1000;          // D+ high, D- low
    // THE OUTPUT LATENCY IS USB_OUT_LAT EXACTLY (model/fpga_consts reads the same localparam):
    // not yet at USB_OUT_LAT - 1 clock edges, there at USB_OUT_LAT
    for (k = 0; k < dut.USB_OUT_LAT - 1; k = k + 1) @(posedge clk);
    #1;
    if (dp_oe === 1'b1 && dp_o === 1'b1 && dm_oe === 1'b1)
      fail("the pads changed before USB_OUT_LAT clock edges");
    @(posedge clk); #1;
    if (!(dp_oe === 1'b1 && dp_o === 1'b1 && dm_oe === 1'b1 && dm_o === 1'b0))
      fail("the pads had not changed after USB_OUT_LAT clock edges");
    repeat (2) @(posedge clk); #1;
    if (dp !== 1'b1 || dm !== 1'b0) fail("uio_out -> pads (D+ = 1, D- = 0) wrong");
    force dut.uio_out = 8'b0000_0100;
    repeat (2) @(posedge clk); #1;
    if (dp !== 1'b0 || dm !== 1'b1) fail("uio_out -> pads (D+ = 0, D- = 1) wrong");
    force dut.uio_oe = 8'b0000_0000;
    repeat (2) @(posedge clk); #1;
    if (dp_oe || dm_oe) fail("uio_oe low but a pad still driven");
    release dut.uio_oe;
    release dut.uio_out;
    repeat (5) @(posedge clk);
    if (drove_off) fail("a pad or the pull-up was driven while run_ok was low");
    if (pu_bad) fail("the pull-up did not follow run_ok (one register late)");
    if (fails == 0)
      $display("FPGA-USB: ok -- released for the %0d cycles before the program ran, pull-up = run_ok, D+/D- mapped both ways, outputs %0d cycle(s) after uio_out, inputs same cycle", t_run, dut.USB_OUT_LAT);
    $finish;
  end
endmodule
