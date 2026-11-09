/* tb_usbrx.v -- v2 primitive 3, bundle 3 (Wilson 11-08): the USB receive --
 * NRZI decode, unstuffing and re-anchoring on the self-timed SHIFTIN.
 *
 * ONE RUN PER INVOCATION; `test/run_usbrx.py` builds the image AND the host's
 * line (a transition list), predicts every line below (its golden) and
 * compares exactly. The bench drives and records, it judges nothing.
 *
 *   +IMG=<hex>    the image
 *   +WAVE=<txt>   the host's D- line: "<cycle> <level>" per transition, cycles
 *                 counted from run entry (fractional = a sub-cycle phase),
 *                 ascending; idle (J) is 1
 *   +NCYC=<n>     cycles to record after run entry
 *
 * Prints, cycles counted from run entry:
 *   RX <c> <data> <lane>   every received byte
 *   SA <c> <ts>            every USB-receive sample: its writeback cycle and its
 *                          scheduled release (the USB lane's timestamp)
 *   SE <c> <0|1>           every change of the USB lane's stuff-error flag
 *   CE <c>                 config_err rising (the chip refused the program)
 *   MK <c> <b1 b0>         every change of uo_out[1:0] (bundle 4's ACK / NAK markers)
 *   BR <c> <pin> <bit>     every BRANCH_BIT writeback: the pin it sampled and the value
 *   PH <n> <of>            how many of the period's 1 ns phase bins the host's edges hit
 *   END
 */

`default_nettype none
`timescale 1ns / 1ps

`include "test/imgload.vh"
module tb_usbrx;

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
  reg [8*256-1:0] imgfile, wavefile;

  localparam integer PIN_PROG = 7;
  localparam integer PIN_PTR  = 5;
  localparam integer PIN_WR   = 6;
  localparam integer DM       = 2;      // uio[2] = the host's D- (LS: J = 1)

  integer i, k, cyc, ncyc, wfd, wc, wl, wok, dbg;
  reg prev_se, prev_ce;
  real    t_neg0, wtr, tq, phs;            // the host's absolute-time drive
  reg     run_go = 1'b0;
  reg [31:0] ph_hit = 32'd0;
  integer phn, phb;
  reg [1:0] prev_mk;

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
      // RUN: the bench drives only uio[2], the host's D-, idle J (high)
      @(negedge clk); ui_in[PIN_PROG] = 1'b0;
      uio_oe_tb = 8'h04;
      uio_drv   = 8'hFF;
    end
  endtask

  initial begin
    if (!$value$plusargs("IMG=%s", imgfile)) imgfile = "none";
    if (!$value$plusargs("WAVE=%s", wavefile)) wavefile = "none";
    if (!$value$plusargs("NCYC=%d", ncyc)) ncyc = 2000;
    if (!$value$plusargs("DBG=%d", dbg)) dbg = 0;
    $readmemh(imgfile, img);
    `PE_REQUIRE_IMG_LOADED(imgfile)
    img_bytes = 0;
    for (i = 0; i < IMG_MAX; i = i + 1)
      if (^img[i] !== 1'bx) img_bytes = i + 1;
    wfd = $fopen(wavefile, "r");
    if (wfd == 0) begin
      $display("NO WAVE %0s", wavefile);
      $finish;
    end
    wok = $fscanf(wfd, "%f %d\n", wtr, wl);
    hf_init;                     // the host feed idle: this bench sends nothing
    load_and_run;
    t_neg0 = $realtime;          // the negedge the run starts on: cycle c = t_neg0 + c * period
    run_go = 1'b1;
    cyc = 0;
    prev_se = dut.u_eng.usb_serr;
    prev_ce = dut.u_eng.cfg_err;
    prev_mk = uo_out[1:0];
    for (k = 0; k < ncyc; k = k + 1) begin
      @(posedge clk); cyc = cyc + 1;
      if (dut.u_eng.rx_push === 1'b1)
        $display("RX %0d %0d %0d", cyc, dut.u_eng.rx_data, dut.u_eng.rx_lane);
      // the sample's writeback cycle AND its scheduled release (the lane
      // timestamp, not yet advanced at writeback): the grid the claim is about
      if (dut.u_eng.usb_act === 1'b1 && dut.u_eng.st === 2'd2)
        $display("SA %0d %0d", cyc, dut.u_eng.l_timestamp[0]);
      // bundle 4: the program's decision markers (uo_out[0] = ACK, [1] = NAK)
      // and every BRANCH_BIT's sampled pin at its writeback
      if (uo_out[1:0] !== prev_mk)
        $display("MK %0d %b", cyc, uo_out[1:0]);
      prev_mk = uo_out[1:0];
      if (dut.u_eng.st === 2'd2 && dut.u_eng.a_op === 5'd8)
        $display("BR %0d %0d %0d", cyc, dut.u_eng.a_pin, dut.u_eng.rx_bit);
      if (dbg && dut.u_eng.st === 2'd1)
        $display("DS %0d %0d", cyc, dut.u_eng.cur);
      if (dut.u_eng.usb_serr !== prev_se)
        $display("SE %0d %0d", cyc, dut.u_eng.usb_serr);
      prev_se = dut.u_eng.usb_serr;
      if (dut.u_eng.cfg_err === 1'b1 && prev_ce !== 1'b1)
        $display("CE %0d", cyc);
      prev_ce = dut.u_eng.cfg_err;
      @(negedge clk);
    end
    phn = 0;
    for (phb = 0; phb < PE_PHASES; phb = phb + 1) phn = phn + ph_hit[phb];
    $display("PH %0d %0d", phn, PE_PHASES);
    $display("END");
    $finish;
  end

  // ---- THE HOST: every transition at an ABSOLUTE time ----------------------
  // `c` (cycles, may be fractional) lands at t_neg0 + c * period, so a WHOLE c
  // is the negedge after posedge c -- the instant the integer cases have
  // always used -- and a fractional c walks the sub-cycle phase (Wilson 10-20
  // standing rule; phase_coverage IN_SUITE). Never ON a posedge: within 0.5 ns
  // of one it moves 0.5 ns past it (tb_uartrx's rule). The 1 ns bin after the
  // posedge of every edge actually driven is MEASURED, not assumed.
  initial begin : host
    wait (run_go === 1'b1);
    while (wok == 2) begin
      tq  = t_neg0 + wtr * PE_CLK_NS;
      phs = (tq - t_neg0 - PE_CLK_HALF_NS) - PE_CLK_NS * $floor((tq - t_neg0 - PE_CLK_HALF_NS) / PE_CLK_NS);
      if (phs < 0.5) tq = tq + (0.5 - phs);
      else if (phs > PE_CLK_NS - 0.5) tq = tq + (PE_CLK_NS - phs) + 0.5;
      phs = (tq - t_neg0 - PE_CLK_HALF_NS) - PE_CLK_NS * $floor((tq - t_neg0 - PE_CLK_HALF_NS) / PE_CLK_NS);
      if (tq > $realtime) #(tq - $realtime);
      if (uio_drv[DM] !== wl[0]) ph_hit[$rtoi(phs)] = 1'b1;
      uio_drv[DM] = wl[0];
      wok = $fscanf(wfd, "%f %d\n", wtr, wl);
    end
  end

  parameter integer SPL_CFG = 2;

  tt_um_protocol_emulator #(.SPL(SPL_CFG)) dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );

`include "test/host_feed.vh"
`include "test/progress.vh"

endmodule

`default_nettype wire
