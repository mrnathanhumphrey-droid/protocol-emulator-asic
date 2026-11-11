/* tb_pair.v -- v2 primitive 3, bundle 2 (Wilson 11-08): the complementary pin
 * pair, SHIFTI, and the self-timed byte.
 *
 * ONE RUN PER INVOCATION; `test/run_pair.py` builds the images, predicts every
 * line below (its golden) and compares exactly. The bench drives and records,
 * it judges nothing.
 *
 *   +IMG=<hex>    the image
 *   +NCYC=<n>     cycles to record after run entry
 *   +FEED=<0|1>   feed TX queue 0 with the bytes A5 3C 96 0F (host_feed.vh)
 *   +RXB=<byte>   drive a UART-shaped byte on uio[2] (start 0, 8 bits LSB
 *   +RXT=<c>        first, stop 1) from cycle c, +RXD=<d> cycles a bit
 *
 * Prints, cycles counted from run entry:
 *   EV <c> <oe1><oe0> <out1><out0>   every change of uio[1:0]'s drive
 *   CB <c> <l_ckbit[0]>              every change of lane 0's bit counter
 *   RX <c> <data> <lane>             every received byte
 *   END
 */

`default_nettype none
`timescale 1ns / 1ps

`include "test/imgload.vh"
module tb_pair;

  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00;
  reg  [7:0] uio_drv = 8'h00;
  reg  [7:0] uio_oe_tb = 8'h00;
  wire [7:0] uo_out, uio_out, uio_oe;
  wire [7:0] uio_in;

  wire [7:0] ob_oe  = uio_oe_tb;
  wire [7:0] ob_val = uio_drv;
`include "test/od_bus.vh"

  `include "test/pe_clock.vh"

  always #(PE_CLK_HALF_NS) clk = ~clk;

`include "test/store_filler.vh"
  localparam integer IMG_MAX = PE_STORE_BYTES;
  reg [7:0] img [0:IMG_MAX-1];
  integer   img_bytes;
  reg [8*256-1:0] imgfile;

  localparam integer PIN_PROG = 7;
  localparam integer PIN_PTR  = 5;
  localparam integer PIN_WR   = 6;

  integer i, k, cyc, ncyc, feed, rxb, rxt, rxd;
  reg [3:0] prev_drv;
  reg [3:0] prev_cb;

  // Included ABOVE the stimulus (as every other bench does): the `initial`
  // below assigns `hf_en`, and the pinned iverilog rejects a use before its
  // declaration. `progress.vh` first: `host_feed.vh` drives its `pg_pushing`.
`include "test/progress.vh"
`include "test/host_feed.vh"

  task load_and_run;
    begin
      @(negedge clk);
      ui_in = 8'h00; uio_oe_tb = 8'h00; uio_drv = 8'h00;
      rst_n = 0;
      repeat (4) @(posedge clk);
      @(negedge clk); rst_n = 1;
      @(posedge clk);
      @(negedge clk); ui_in[PIN_PROG] = 1'b1;
      uio_oe_tb = 8'hFF;
      repeat (3) @(posedge clk); @(negedge clk); ui_in[PIN_PTR] = 1'b1; repeat (3) @(posedge clk);
      @(negedge clk); ui_in[PIN_PTR] = 1'b0; repeat (3) @(posedge clk);
      for (i = 0; i < img_bytes; i = i + 1) begin
        @(negedge clk); uio_drv = img[i];
        @(posedge clk); @(posedge clk);
        @(negedge clk); ui_in[PIN_WR] = 1'b1;
        @(posedge clk); @(posedge clk); @(posedge clk);
        @(negedge clk); ui_in[PIN_WR] = 1'b0;
        @(posedge clk);
      end
      // RUN: the bench drives only uio[2] (the RX peer, idle HIGH)
      @(negedge clk); ui_in[PIN_PROG] = 1'b0;
      uio_oe_tb = 8'h04;
      uio_drv   = 8'hFF;
    end
  endtask

  initial begin
    if (!$value$plusargs("IMG=%s", imgfile)) imgfile = "none";
    if (!$value$plusargs("NCYC=%d", ncyc)) ncyc = 2000;
    if (!$value$plusargs("FEED=%d", feed)) feed = 0;
    if (!$value$plusargs("RXB=%d", rxb)) rxb = -1;
    if (!$value$plusargs("RXT=%d", rxt)) rxt = 200;
    if (!$value$plusargs("RXD=%d", rxd)) rxd = 40;
    $readmemh(imgfile, img);
    `PE_REQUIRE_IMG_LOADED(imgfile)
    img_bytes = 0;
    for (i = 0; i < IMG_MAX; i = i + 1)
      if (^img[i] !== 1'bx) img_bytes = i + 1;
    hf_init;
    if (feed) hf_set(0, 8'hA5, 8'h3C, 8'h96, 8'h0F);
    load_and_run;
    if (feed) hf_en = 1'b1;
    cyc = 0;
    prev_drv = {uio_oe[1:0], uio_out[1:0]};
    prev_cb  = dut.u_eng.l_ckbit[0];
    for (k = 0; k < ncyc; k = k + 1) begin
      @(posedge clk); cyc = cyc + 1;
      if ({uio_oe[1:0], uio_out[1:0]} !== prev_drv)
        $display("EV %0d %b%b %b%b", cyc, uio_oe[1], uio_oe[0], uio_out[1], uio_out[0]);
      prev_drv = {uio_oe[1:0], uio_out[1:0]};
      if (dut.u_eng.l_ckbit[0] !== prev_cb)
        $display("CB %0d %0d", cyc, dut.u_eng.l_ckbit[0]);
      prev_cb = dut.u_eng.l_ckbit[0];
      if (dut.u_eng.rx_push === 1'b1)
        $display("RX %0d %0d %0d", cyc, dut.u_eng.rx_data, dut.u_eng.rx_lane);
      // the RX peer: a start bit, 8 data bits LSB first, a stop bit
      @(negedge clk);
      if (rxb >= 0) begin
        if (cyc == rxt) uio_drv[2] = 1'b0;
        if (cyc > rxt && cyc <= rxt + 8 * rxd && ((cyc - rxt) % rxd) == 0)
          uio_drv[2] = (rxb >> ((cyc - rxt) / rxd - 1)) & 1;
        if (cyc == rxt + 9 * rxd) uio_drv[2] = 1'b1;
      end
    end
    $display("END");
    $finish;
  end

  parameter integer SPL_CFG = 2;

  tt_um_protocol_emulator #(.SPL(SPL_CFG)) dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );

endmodule

`default_nettype wire
