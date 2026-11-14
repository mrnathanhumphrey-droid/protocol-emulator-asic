/* tb_arm2.v -- v2 primitive 3, bundle 1 (Wilson 11-08): the TWO-PIN LEVEL ARM.
 *
 * ONE SCENARIO PER RUN, set by plusargs; `test/run_arm2.py` builds the images,
 * predicts every cycle below from the drive times (its golden), and compares
 * them exactly. The bench only drives and records -- it judges nothing, so a
 * wrong expectation cannot hide in here.
 *
 * The peer is uio[0] (the ARM's `pin`) and uio[1] (`pinb`). The lane's
 * program moves uo_out[0] after it is released (as tb_edge's does).
 *
 *   +IMG=<hex>   the image
 *   +IDLE=<0|1>  both peer pins' level at run entry
 *   +PHA=<n>     cycles after ARMING at which uio[0] flips to ~IDLE (-1 never)
 *   +PHB=<n>     the same for uio[1]
 *   +NCYC=<n>    cycles to record after arming
 *
 * Prints one line: ARM2 armed=<c> ta=<c> tb=<c> fire=<c> out=<c> oe=<n> x=<n>
 *                  live=<0|1> to=<0|1>
 * (cycles count posedges from run entry; -1 = did not happen). `fire` is the
 * first cycle `arm_hit[0]` is high, sampled mid-cycle on the falling edge.
 */

`default_nettype none
`timescale 1ns / 1ps

`include "test/imgload.vh"
module tb_arm2;

  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00;
  reg  [7:0] uio_drv = 8'h00;
  reg  [7:0] uio_oe_tb = 8'h00;     // which uio bits the BENCH drives
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

  localparam integer PIN_PROG = 7;   // ui_in[7] prog_mode
  localparam integer PIN_PTR  = 5;
  localparam integer PIN_WR   = 6;

  integer i, cyc, idle, pha, phb, ncyc;
  integer t_armed, t_a, t_b, t_fire, t_out, oe_viol, x_viol, pha_abs;
  reg     prev_uo0;

  // the load sequence is tb_edge's, every input write on a falling edge
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
      // RUN: the bench keeps driving uio[1:0] as the peer, at IDLE
      @(negedge clk); ui_in[PIN_PROG] = 1'b0;
      uio_oe_tb = 8'h03;
      uio_drv   = idle ? 8'hFF : 8'h00;
    end
  endtask

  initial begin
    if (!$value$plusargs("IMG=%s", imgfile)) imgfile = "none";
    if (!$value$plusargs("IDLE=%d", idle)) idle = 1;
    if (!$value$plusargs("PHA=%d", pha)) pha = -1;
    if (!$value$plusargs("PHB=%d", phb)) phb = -1;
    // +PHA_ABS: flip uio[0] at an ABSOLUTE run cycle, also while still waiting for
    // the lane to arm -- the FT scan-race must-fire (run_arm2 A4) needs the edge on
    // the cycle the prefetch scan selects the lane, which is the cycle AFTER arming,
    // so the pin must move before the bench has seen l_armed (2-flop synchroniser)
    if (!$value$plusargs("PHA_ABS=%d", pha_abs)) pha_abs = -1;
    if (!$value$plusargs("NCYC=%d", ncyc)) ncyc = 400;
    $readmemh(imgfile, img);
    `PE_REQUIRE_IMG_LOADED(imgfile)
    img_bytes = 0;
    for (i = 0; i < IMG_MAX; i = i + 1)
      if (^img[i] !== 1'bx) img_bytes = i + 1;

    t_armed = -1; t_a = -1; t_b = -1; t_fire = -1; t_out = -1;
    oe_viol = 0; x_viol = 0; cyc = 0;
    load_and_run;
    prev_uo0 = uo_out[0];
    // ARMING: the first falling edge that reads l_armed[0] high (or a fire
    // already under way: a level ARM whose condition holds fires the cycle it
    // arms, and l_armed may never be seen high on its own)
    for (i = 0; i < 2000 && t_armed < 0; i = i + 1) begin
      @(posedge clk); cyc = cyc + 1;
      @(negedge clk);
      if (pha_abs >= 0 && cyc == pha_abs) begin uio_drv[0] = ~uio_drv[0]; t_a = cyc; end
      if (dut.u_eng.l_armed[0] === 1'b1) t_armed = cyc;
      if (dut.u_eng.arm_hit[0] === 1'b1 && t_fire < 0) t_fire = cyc;
    end
    // RECORD: drives land on falling edges, after that edge's sample
    for (i = 0; i < ncyc; i = i + 1) begin
      @(posedge clk); cyc = cyc + 1;
      if (uo_out[0] !== prev_uo0 && t_out < 0) t_out = cyc;
      prev_uo0 = uo_out[0];
      if (uio_oe !== 8'h00) oe_viol = oe_viol + 1;
      if (^uio_in === 1'bx) x_viol = x_viol + 1;
      @(negedge clk);
      if (dut.u_eng.arm_hit[0] === 1'b1 && t_fire < 0) t_fire = cyc;
      if (pha_abs >= 0 && cyc == pha_abs) begin
        uio_drv[0] = ~uio_drv[0]; t_a = cyc;
      end
      if (t_armed >= 0 && pha >= 0 && cyc == t_armed + pha) begin
        uio_drv[0] = ~uio_drv[0]; t_a = cyc;
      end
      if (t_armed >= 0 && phb >= 0 && cyc == t_armed + phb) begin
        uio_drv[1] = ~uio_drv[1]; t_b = cyc;
      end
    end
    $display("ARM2 armed=%0d ta=%0d tb=%0d fire=%0d out=%0d oe=%0d x=%0d live=%0d to=%0d",
             t_armed, t_a, t_b, t_fire, t_out, oe_viol, x_viol,
             dut.u_eng.l_live[0], dut.u_eng.l_timeout_m[0] | dut.u_eng.l_timeout_k[0]);
    $finish;
  end

  parameter integer SPL_CFG = 2;

  tt_um_protocol_emulator #(.SPL(SPL_CFG)) dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );

`include "test/progress.vh"

  // ⛔ QUIESCENT BY DECLARATION (the coverage sweep, 11-13): the `none` (uo-bank
  // guard) and `timeout` scenarios retire no action BY DESIGN -- the guard never
  // fires and the timeout halts the lane -- so progress.vh's vacuity rule would
  // read them as "nothing to check". The runner declares it with +QUIESCENT,
  // the same pattern as tb_equiv / tb_status / tb_reload.
  initial if ($test$plusargs("QUIESCENT")) pg_quiescent_ok = 1'b1;

endmodule

`default_nettype wire
