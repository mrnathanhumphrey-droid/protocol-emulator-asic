/* tb_cktx.v -- RULING TX4: clocked transmit VALUES over the cases the fix
 * touched. Driven by `test/run_cktx.py`, which owns the images and verdicts;
 * the checking is Layer V of `clocked_conform.vh` (V1 against the golden
 * model's load point and bit order, V2 against the host-pushed bytes decoded
 * off the pins).
 *
 * The bus is tb_smoke's loopback (the DUT reads its own drive, a released
 * pin reads 1), so an open-drain clock rises when the engine releases it and
 * a push-pull lane needs nothing. The host feed carries NON-PALINDROMIC
 * bytes on every queue (ruling 1b), so a byte sent in the wrong order or
 * shifted by a bit is a different byte.
 *
 * +STARVE=<cyc> +STARVE_LEN=<cyc>: stop topping up the queues at <cyc> for
 * <len> cycles, so they run EMPTY and refill -- the underrun boundary, which
 * V2 models (the residue goes out) and counts.
 */
`default_nettype none
`timescale 1ns / 1ps

`include "test/imgload.vh"
module tb_cktx;

  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00, uio_drv = 8'hFF;
  wire [7:0] uo_out, uio_out, uio_oe;
  wire [7:0] uio_in = (uio_oe & uio_out) | (~uio_oe & uio_drv);

  localparam integer IMG_MAX = 256;
  localparam integer PIN_PROG = 7, PIN_PTR = 5, PIN_WR = 6;

  reg  [7:0] img [0:IMG_MAX-1];
  integer    img_bytes, i, cyc, ncyc, starve, starve_len;
  reg [8*256-1:0] imgfile;

  always #10 clk = ~clk;

  tt_um_protocol_emulator #(.SPL(2)) dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );

`include "test/progress.vh"
`include "test/clocked_conform.vh"
`include "test/host_feed.vh"

  initial begin
    if (!$value$plusargs("IMG=%s", imgfile)) begin
      $display("tb_cktx: FATAL -- +IMG required"); $finish;
    end
    if (!$value$plusargs("NBYTES=%d", img_bytes)) begin
      $display("tb_cktx: FATAL -- +NBYTES required"); $finish;
    end
    if (!$value$plusargs("NCYC=%d", ncyc)) begin
      $display("tb_cktx: FATAL -- +NCYC required"); $finish;
    end
    if (!$value$plusargs("STARVE=%d", starve)) begin
      $display("tb_cktx: FATAL -- +STARVE required (0 = never)"); $finish;
    end
    if (!$value$plusargs("STARVE_LEN=%d", starve_len)) begin
      $display("tb_cktx: FATAL -- +STARVE_LEN required"); $finish;
    end
    $readmemh(imgfile, img);
    `PE_REQUIRE_IMG_LOADED(imgfile)
    // ⭐ NON-PALINDROMIC, AND DISJOINT BETWEEN QUEUES (ruling 1b)
    hf_init;
    hf_set(0, 8'h5B, 8'hC4, 8'h1E, 8'hA7);    // rev DA 23 78 E5
    hf_set(1, 8'h2D, 8'h96, 8'hE1, 8'h4C);    // rev B4 69 87 32
    $display("# cktx img=%0s ncyc=%0d starve=%0d+%0d", imgfile, ncyc,
             starve, starve_len);

    repeat (4) @(negedge clk);
    rst_n = 1;
    @(negedge clk);
    ui_in[PIN_PROG] = 1'b1;
    ui_in[PIN_PTR] = 1'b1; @(negedge clk);
    ui_in[PIN_PTR] = 1'b0; @(negedge clk);
    for (i = 0; i < img_bytes; i = i + 1) begin
      uio_drv = img[i];
      @(negedge clk); @(negedge clk);
      ui_in[PIN_WR] = 1'b1;
      @(negedge clk); @(negedge clk); @(negedge clk);
      ui_in[PIN_WR] = 1'b0;
      @(negedge clk);
    end
    ui_in[PIN_PROG] = 1'b0;
    uio_drv = 8'hFF;
    hf_en = 1'b1;

    for (cyc = 0; cyc < ncyc; cyc = cyc + 1) begin
      @(posedge clk);
      // the feeder tops up only queues in `hf_mask`, so clearing it starves
      if (starve != 0 && cyc == starve)              hf_mask = 4'b0000;
      if (starve != 0 && cyc == starve + starve_len) hf_mask = 4'b0011;
    end
    $display("CKTX underrun=%b config_err=%0b tx_full=%0b pushes=%0d pops=%0d",
             dut.u_eng.lane_underrun, dut.u_eng.config_err,
             dut.tx_full_sticky, hf_bytes, hf_pops);
    $display("END tb_cktx");
    $finish;
  end
endmodule
