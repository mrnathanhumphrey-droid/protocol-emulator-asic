/* tb_ds.v -- DRIVE_SAMPLE (opcode 12, Wilson 11-20): drive one pin, sample
 * another at the drive instant.
 *
 * ONE RUN PER INVOCATION; `test/run_drive_sample.py` builds the images and
 * judges every line below. The bench drives and records, it judges nothing.
 *
 *   +IMG=<hex>     the image
 *   +NCYC=<n>      cycles to record after run entry
 *   +FEED=<0|1>    feed TX queue 0 with the bytes A5 3C 96 0F (host_feed.vh)
 *   +PEER=<0|1|2>  what drives uio[2]:
 *                    0  idle HIGH
 *                    1  an SPI MODE-0 TARGET, independent of the engine: SCK =
 *                       uio[1], MOSI = uio[0], MISO = uio[2]; it shifts out
 *                       +PTX=<byte> LSB first (bit 0 on MISO from run entry,
 *                       the next bit after each SCK FALL) and shifts MOSI in on
 *                       each SCK RISE, LSB first
 *                    2  a per-cycle pseudo-random line (16-bit LFSR, seed ACE1,
 *                       x^16 + x^14 + x^13 + x^11), one new bit every cycle
 *
 * Cycles are counted from run entry; the bench reads the pads at the NEGEDGE
 * after edge <c>, so a change printed at <c> reached the pad at edge <c>, and a
 * PR bit printed at <c> is on the pad from then until the next negedge -- the
 * input synchroniser's first flop latches it at edge <c + 1>.
 *   EV <c> <oe1><oe0> <out1><out0>   every change of uio[1:0]'s drive
 *   PR <c> <bit>                     PEER=2: the bit put on uio[2]
 *   RX <c> <data> <lane>             every received byte
 *   PEER rx=<byte> bits=<n>          PEER=1: the target's first 8 MOSI bits
 *   FLT cfg=<0|1> ovr=<0|1>          the engine's two fault flags
 *   END
 */

`default_nettype none
`timescale 1ns / 1ps

`include "test/imgload.vh"
`include "test/imgpatch.vh"
module tb_ds;

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

  integer i, k, cyc, ncyc, feed, peer, ptx;
  reg [3:0]  prev_drv;
  reg [15:0] lfsr;
  reg        sck_prev;
  reg [7:0]  p_rx;
  integer    p_nrx, p_ntx;
  reg        p_done;

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
      // RUN: the bench drives only uio[2] (the peer)
      @(negedge clk); ui_in[PIN_PROG] = 1'b0;
      uio_oe_tb = 8'h04;
      uio_drv   = 8'hFF;
    end
  endtask

  initial begin
    if (!$value$plusargs("IMG=%s", imgfile)) imgfile = "none";
    if (!$value$plusargs("NCYC=%d", ncyc)) ncyc = 2000;
    if (!$value$plusargs("FEED=%d", feed)) feed = 0;
    if (!$value$plusargs("PEER=%d", peer)) peer = 0;
    if (!$value$plusargs("PTX=%d", ptx)) ptx = 0;
    $readmemh(imgfile, img);
    `PE_REQUIRE_IMG_LOADED(imgfile)
    `PE_APPLY_IMG_PATCHES(img)
    img_bytes = 0;
    for (i = 0; i < IMG_MAX; i = i + 1)
      if (^img[i] !== 1'bx) img_bytes = i + 1;
    hf_init;
    if (feed) hf_set(0, 8'hA5, 8'h3C, 8'h96, 8'h0F);
    load_and_run;
    if (feed) hf_en = 1'b1;
    lfsr = 16'hACE1;
    p_rx = 8'h00; p_nrx = 0; p_ntx = 0; p_done = 1'b0;
    if (peer == 1) uio_drv[2] = ptx & 1;
    cyc = 0;
    prev_drv = {uio_oe[1:0], uio_out[1:0]};
    sck_prev = uio_oe[1] & uio_out[1];
    for (k = 0; k < ncyc; k = k + 1) begin
      @(posedge clk); cyc = cyc + 1;
      @(negedge clk);
      if ({uio_oe[1:0], uio_out[1:0]} !== prev_drv)
        $display("EV %0d %b%b %b%b", cyc, uio_oe[1], uio_oe[0], uio_out[1], uio_out[0]);
      prev_drv = {uio_oe[1:0], uio_out[1:0]};
      if (dut.u_eng.rx_push === 1'b1)
        $display("RX %0d %0d %0d", cyc, dut.u_eng.rx_data, dut.u_eng.rx_lane);
      if (peer == 1) begin
        // the SPI mode-0 target: MOSI in on the rise, the next MISO bit on the fall
        if ((uio_oe[1] & uio_out[1]) && !sck_prev && p_nrx < 8) begin
          p_rx  = {uio_oe[0] & uio_out[0], p_rx[7:1]};
          p_nrx = p_nrx + 1;
          if (p_nrx == 8 && !p_done) begin
            $display("PEER rx=%0d bits=%0d", p_rx, p_nrx);
            p_done = 1'b1;
          end
        end
        if (!(uio_oe[1] & uio_out[1]) && sck_prev) begin
          p_ntx = p_ntx + 1;
          uio_drv[2] = (ptx >> (p_ntx % 8)) & 1;
        end
        sck_prev = uio_oe[1] & uio_out[1];
      end else if (peer == 2) begin
        lfsr = {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
        uio_drv[2] = lfsr[0];
        $display("PR %0d %0d", cyc, lfsr[0]);
      end
    end
    $display("FLT cfg=%0d ovr=%0d", dut.u_eng.config_err_m, dut.u_eng.sticky_ovr_m);
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
