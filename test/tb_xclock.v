/* tb_xclock.v -- THE CROSS-CLOCK BENCH (Wilson 11-03): one program image, run
 * at the clock it was assembled for, its pins logged with the cycle they
 * moved on, so model/gate_clock_cross.py can compare the REAL-TIME behaviour
 * of the same program assembled at two clocks.
 *
 * ⭐ THE CLOCK IS A BUILD INPUT: `-DPE_CLK_PS=<ps>` sets both this bench's
 * clock (test/pe_clock.vh) and the chip's CLK_PERIOD_PS, so a program
 * assembled for a clock runs on a chip sized for it -- the per-target build.
 * ⭐ NO PEER: every uio pin is pulled up (an open-drain bus with nothing on
 * it; a driven pin reads back), so a clocked I2C lane sees its own released
 * SCL rise and is never stretched. The host feeds every queue so no SHIFT
 * runs starved. The judge is the gate, in nanoseconds; this bench only
 * records. It carries no V3 layer (sim_run: no_v3_layer).
 *
 * OUTPUT (+OUT): `# ps <period>` then one line per change after the load,
 *   `<cycle> <uo_out> <uio_out> <uio_oe>` in binary.
 */
`default_nettype none
`timescale 1ns / 1ps

`include "test/imgload.vh"
module tb_xclock ();

  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00, ld_uio = 8'h00;
  reg        loading = 1'b1;
  wire [7:0] uo_out, uio_out, uio_oe;
  wire [7:0] uio_in = loading ? ld_uio : ((uio_oe & uio_out) | ~uio_oe);
  integer    i, img_bytes, ncyc, cyc, fd;
  reg [8*256-1:0] imgfile, outfile;
`include "test/store_filler.vh"   // v2: PE_STORE_BYTES, never a typed 256
  reg  [7:0] img [0:PE_STORE_BYTES-1];
  reg  [7:0] p_uo, p_out, p_oe;

  localparam integer PIN_PROG = 7, PIN_PTR = 5, PIN_WR = 6;

  `include "test/pe_clock.vh"
  always #(PE_CLK_HALF_NS) clk = ~clk;   // the target's clock, never typed

  tt_um_protocol_emulator #(.CLK_PERIOD_PS(PE_CLK_PERIOD_PS)) dut (
      .ui_in(ui_in), .uo_out(uo_out), .uio_in(uio_in),
      .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );

`include "test/progress.vh"
`include "test/host_feed.vh"

  task load_image;
    begin
      @(negedge clk); ui_in[PIN_PROG] = 1'b1;
      repeat (3) @(negedge clk); ui_in[PIN_PTR] = 1'b1; repeat (3) @(negedge clk);
      ui_in[PIN_PTR] = 1'b0; repeat (3) @(negedge clk);
      for (i = 0; i < img_bytes; i = i + 1) begin
        ld_uio = img[i];
        @(negedge clk); @(negedge clk);
        ui_in[PIN_WR] = 1'b1;
        @(negedge clk); @(negedge clk); @(negedge clk);
        ui_in[PIN_WR] = 1'b0;
        @(negedge clk);
      end
      ui_in[PIN_PROG] = 1'b0;
      ui_in = 8'h00;
      loading = 1'b0;
    end
  endtask

  initial begin
    if (!$value$plusargs("IMG=%s", imgfile)) begin
      $display("tb_xclock: FATAL -- +IMG=<file> is required");
      $finish;
    end
    if (!$value$plusargs("NBYTES=%d", img_bytes)) begin
      $display("tb_xclock: FATAL -- +NBYTES=<n> is required");
      $finish;
    end
    if (!$value$plusargs("OUT=%s", outfile)) outfile = "xclock.txt";
    if (!$value$plusargs("NCYC=%d", ncyc)) ncyc = 40000;
    $readmemh(imgfile, img);
    `PE_REQUIRE_IMG_LOADED(imgfile)
    fd = $fopen(outfile, "w");
    if (fd == 0) begin
      $display("*** FAIL tb_xclock: $fopen could not open the trace file");
      $finish;
    end
    $fwrite(fd, "# ps %0d\n", PE_CLK_PERIOD_PS);
    hf_init;
    hf_set(0, 8'h5B, 8'hA5, 8'h3C, 8'hC3);
    hf_set(1, 8'h5B, 8'hA5, 8'h3C, 8'hC3);
    hf_set(2, 8'h5B, 8'hA5, 8'h3C, 8'hC3);
    hf_set(3, 8'h5B, 8'hA5, 8'h3C, 8'hC3);
    repeat (4) @(posedge clk);
    @(negedge clk); rst_n = 1;
    @(posedge clk);
    load_image;
    hf_en = 1'b1;
    p_uo = uo_out; p_out = uio_out; p_oe = uio_oe;
    for (cyc = 0; cyc < ncyc; cyc = cyc + 1) begin
      @(posedge clk); #1;
      if (uo_out !== p_uo || uio_out !== p_out || uio_oe !== p_oe) begin
        $fwrite(fd, "%0d %b %b %b\n", cyc, uo_out, uio_out, uio_oe);
        p_uo = uo_out; p_out = uio_out; p_oe = uio_oe;
      end
    end
    $fclose(fd);
    $display("tb_xclock: END ncyc=%0d", ncyc);
    $finish;
  end

endmodule
`default_nettype wire
