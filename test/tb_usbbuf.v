/* tb_usbbuf.v -- v2 primitive 3, bundle 5 (Wilson 11-08): the USB response
 * buffer, READY, and the IN -> DATA -> ACK turnaround, against a host on the
 * shared D- / D+ pair (uio[2] = D-, uio[3] = D+; low speed: J = D- high).
 *
 * ONE RUN PER INVOCATION; `test/run_usbbuf.py` builds the image, the host's
 * packets and the buffer loads, predicts every line below (its golden) and
 * compares exactly. The bench drives and records, it judges nothing.
 *
 *   +IMG=<hex>    the image
 *   +HOST=<txt>   the host's packets: "P <A|R> <t> <n>" then n lines
 *                 "<offset> <dm> <dp>" (cycles from the packet's start; a level
 *                 of 2 RELEASES both lines). A = start at cycle t; R = start t
 *                 cycles after the device's most recent release of D- that came
 *                 after this host's previous packet ended; H = t cycles after
 *                 this host's own previous packet released the bus.
 *   +LOAD=<txt>   tag-3 byte pushes: "L <A|S> <t> <byte>". A = at cycle t;
 *                 S = t cycles after the device's NEXT drive start (D- enable).
 *   +NCYC=<n>     cycles to record after run entry
 *
 * Prints, cycles counted from run entry:
 *   TX <c> <oe3 oe2> <out3 out2>  every change of the device's drive of D+/D-
 *   HP <c> <k>                    host packet k starts driving
 *   HR <c> <k>                    host packet k releases the bus
 *   RD <c> <0|1>                  every change of READY
 *   TF <c>                        the TX-full refusal bit rising
 *   UB <c> <bit>                  every SHIFT writeback on lane 0: the bit on uo_out[0]
 *   UO <c> <0|1>                  every change of the USB-lane-live flag
 *   END
 */

`default_nettype none
`timescale 1ns / 1ps

`include "test/imgload.vh"
module tb_usbbuf;

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
  reg [8*256-1:0] imgfile, hostfile, loadfile;

  localparam integer PIN_PROG = 7;
  localparam integer PIN_PTR  = 5;
  localparam integer PIN_WR   = 6;
  localparam integer DM = 2, DP = 3;

  integer i, k, cyc, ncyc;
  reg [3:0] prev_drv;
  reg prev_rd, prev_tf, prev_uo;
  reg run_go = 1'b0;
  integer dev_rel_n = 0, dev_drv_n = 0;       // device D- releases / drive starts seen
  integer dev_rel_cyc = 0;

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
      // RUN: the bus idles RELEASED (the pull-ups); the host drives it in packets
      @(negedge clk); ui_in[PIN_PROG] = 1'b0;
      uio_oe_tb = 8'h00;
      uio_drv   = 8'hFF;
    end
  endtask

  initial begin
    if (!$value$plusargs("IMG=%s", imgfile)) imgfile = "none";
    if (!$value$plusargs("HOST=%s", hostfile)) hostfile = "none";
    if (!$value$plusargs("LOAD=%s", loadfile)) loadfile = "none";
    if (!$value$plusargs("NCYC=%d", ncyc)) ncyc = 2000;
    $readmemh(imgfile, img);
    `PE_REQUIRE_IMG_LOADED(imgfile)
    img_bytes = 0;
    for (i = 0; i < IMG_MAX; i = i + 1)
      if (^img[i] !== 1'bx) img_bytes = i + 1;
    hf_init;                     // no background feeding: the LOAD script pushes
    load_and_run;
    run_go = 1'b1;
    cyc = 0;
    prev_drv = {uio_oe[3:2], uio_out[3:2]};
    prev_rd = dut.ub_ready; prev_tf = dut.tx_full_sticky; prev_uo = dut.e_usb_on;
    for (k = 0; k < ncyc; k = k + 1) begin
      @(posedge clk); cyc = cyc + 1;
      if ({uio_oe[3:2], uio_out[3:2]} !== prev_drv) begin
        $display("TX %0d %b%b %b%b", cyc, uio_oe[3], uio_oe[2], uio_out[3], uio_out[2]);
        if (uio_oe[2] === 1'b1 && prev_drv[2] !== 1'b1) dev_drv_n = dev_drv_n + 1;
        if (uio_oe[2] !== 1'b1 && prev_drv[2] === 1'b1) begin
          dev_rel_n = dev_rel_n + 1; dev_rel_cyc = cyc;
        end
      end
      prev_drv = {uio_oe[3:2], uio_out[3:2]};
      if (dut.ub_ready !== prev_rd) $display("RD %0d %0d", cyc, dut.ub_ready);
      prev_rd = dut.ub_ready;
      if (dut.tx_full_sticky === 1'b1 && prev_tf !== 1'b1) $display("TF %0d", cyc);
      prev_tf = dut.tx_full_sticky;
      if (dut.e_usb_on !== prev_uo) $display("UO %0d %0d", cyc, dut.e_usb_on);
      prev_uo = dut.e_usb_on;
      if (dut.u_eng.st === 2'd2 && dut.u_eng.a_op === 5'd1 && dut.u_eng.cur === 3'd0)
        $display("UB %0d %0d", cyc, dut.u_eng.pin_out[8]);
      @(negedge clk);
    end
    $display("END");
    $finish;
  end

  // ---- THE HOST: packets on D- / D+ ----------------------------------------
  integer hfd, hok, hn, hj, hk, hmode_r, hrel_seen, hlast;
  real    ht, hstart, hoff;
  integer hdm, hdp;
  reg [8*2-1:0] hmode;
  initial begin : host
    wait (run_go === 1'b1);
    hfd = $fopen(hostfile, "r");
    hk = 0;
    hrel_seen = 0;
    if (hfd != 0) begin
      hok = $fscanf(hfd, "P %s %f %d\n", hmode, ht, hn);
      while (hok == 3) begin
        if (hmode == "R") begin
          // wait for a device release that came AFTER our previous packet
          wait (dev_rel_n > hrel_seen);
          hstart = dev_rel_cyc + ht;
        end else if (hmode == "H") begin
          hstart = hlast + ht;                 // after OUR previous packet's release
        end else begin
          hstart = ht;
        end
        while (cyc < hstart) @(negedge clk);
        $display("HP %0d %0d", cyc, hk);
        hstart = cyc;
        for (hj = 0; hj < hn; hj = hj + 1) begin
          hok = $fscanf(hfd, "%f %d %d\n", hoff, hdm, hdp);
          while (cyc < hstart + hoff) @(negedge clk);
          if (hdm == 2) begin
            uio_oe_tb[DM] = 1'b0; uio_oe_tb[DP] = 1'b0;
            uio_drv[DM] = 1'b1;   uio_drv[DP] = 1'b1;
          end else begin
            uio_oe_tb[DM] = 1'b1; uio_oe_tb[DP] = 1'b1;
            uio_drv[DM] = hdm[0]; uio_drv[DP] = hdp[0];
          end
        end
        $display("HR %0d %0d", cyc, hk);
        hlast = cyc;
        hrel_seen = dev_rel_n;
        hk = hk + 1;
        hok = $fscanf(hfd, "P %s %f %d\n", hmode, ht, hn);
      end
    end
  end

  // ---- THE RP2040's buffer loads: tag-3 pushes --------------------------------
  integer lfd, lok, lt, lb, ldrv_seen, lstart;
  reg [8*2-1:0] lmode;
  initial begin : loader
    wait (run_go === 1'b1);
    lfd = $fopen(loadfile, "r");
    ldrv_seen = 0;
    if (lfd != 0) begin
      lok = $fscanf(lfd, "L %s %d %d\n", lmode, lt, lb);
      while (lok == 3) begin
        if (lmode == "S") begin
          ldrv_seen = dev_drv_n;               // the NEXT drive start, not one already past
          wait (dev_drv_n > ldrv_seen);
          ldrv_seen = dev_drv_n;
          lstart = cyc + lt;
        end else begin
          lstart = lt;
        end
        while (cyc < lstart) @(negedge clk);
        hf_push_byte(lb[7:0], 2'd3);
        lok = $fscanf(lfd, "L %s %d %d\n", lmode, lt, lb);
      end
    end
  end

  parameter integer SPL_CFG = 2;

  tt_um_protocol_emulator #(.SPL(SPL_CFG)) dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );

`include "test/progress.vh"
`include "test/host_feed.vh"

endmodule

`default_nettype wire
