/* tb_lock.v -- THE SCHEDULE FREEZE: every dispatch and every pin change.
 *
 * ⛔⛔ RULING TF4. The timing fix (TF1 registered readiness, TF2 tree select,
 * TF3 registered winner for the prefetch) is required to change NOTHING
 * where a claim is made. "Nothing" is made concrete here: on every shipped
 * admissible image, the stream of dispatches (cycle, lane, action word) and
 * of output-pin changes must be BYTE-IDENTICAL to the stream the pre-fix RTL
 * produced. `test/run_lockstep.py` holds those streams' digests and compares.
 *
 * ⭐ WHY A STREAM AND NOT A PROPERTY. The smoke bench checks J, C and edge
 * counts, and it PASSED on M_TF1_LATE -- a build where every release is seen a
 * cycle late and a lane can dispatch its next action straight after its own
 * writeback. Properties with slack do not see a one-cycle schedule shift. An
 * exact stream does.
 *
 * Lines:
 *   C primed_at <cycle>                    the cycle priming completed
 *   D <cycle> <lane> <action word hex>     at each ST_DRIVE cycle
 *   P <cycle> <uo_out> <uio_out> <uio_oe>  whenever any output changes
 * Cycles are counted from priming, and the run is NCYC cycles AFTER it, so a
 * change in priming time alone (a cold-start difference TF4 allows) moves
 * only the `C` line. tb_smoke's uio read-back model.
 */
`default_nettype none
`timescale 1ns / 1ps

`include "test/imgload.vh"
module tb_lock;

  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00, uio_drv = 8'h00;
  wire [7:0] uo_out, uio_out, uio_oe;
  wire [7:0] uio_in = (uio_oe & uio_out) | (~uio_oe & uio_drv);

  localparam integer IMG_MAX = 256;
  localparam integer PIN_PROG = 7, PIN_PTR = 5, PIN_WR = 6;
  // priming takes ~130 cycles on the shipped images; this is a ceiling, and
  // hitting it is reported rather than silently truncating the stream
  localparam integer PRIME_CAP = 20000;

  reg  [7:0] img [0:IMG_MAX-1];
  integer    img_bytes, i, cyc, ncyc, nd, t0;
  reg [8*256-1:0] imgfile;
  reg [23:0] po;

  always #10 clk = ~clk;

  tt_um_protocol_emulator #(.SPL(2)) dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );
`include "test/inv_curck.vh"       // PR2: cur_ck == l_clkpin[cur], every cycle

  initial begin
    if (!$value$plusargs("IMG=%s", imgfile)) begin
      $display("tb_lock: FATAL -- +IMG required"); $finish;
    end
    if (!$value$plusargs("NBYTES=%d", img_bytes)) begin
      $display("tb_lock: FATAL -- +NBYTES required"); $finish;
    end
    if (!$value$plusargs("NCYC=%d", ncyc)) ncyc = 60000;
    $readmemh(imgfile, img);
    `PE_REQUIRE_IMG_LOADED(imgfile)

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

    po = 24'hxxxxxx; nd = 0; cyc = 0; t0 = -1;
    while (t0 < 0 ? (cyc < PRIME_CAP) : (cyc - t0 < ncyc)) begin
      @(posedge clk);
      if (t0 < 0 && dut.u_eng.primed) begin
        t0 = cyc;
        $display("C primed_at %0d", t0);
      end
      if (t0 >= 0) begin
        if (dut.u_eng.st == 1) begin
          $display("D %0d %0d %h", cyc - t0, dut.u_eng.cur, dut.u_eng.cur_act);
          nd = nd + 1;
        end
        if ({uo_out, uio_out, uio_oe} !== po) begin
          $display("P %0d %h %h %h", cyc - t0, uo_out, uio_out, uio_oe);
          po = {uo_out, uio_out, uio_oe};
        end
      end
      cyc = cyc + 1;
    end
    if (t0 < 0) $display("*** FAIL tb_lock: never primed in %0d cycles", PRIME_CAP);
    $display("END dispatches=%0d", nd);
    $finish;
  end
endmodule
