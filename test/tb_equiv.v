/* tb_equiv.v -- THE v1 == v2 EQUIVALENCE BENCH (Wilson, v2 step 2 item 5).
 *
 * ONE bench, compiled against BOTH the v1-lock RTL and v2's, by
 * `model/gate_v2_equiv.py`. It reads only names both RTLs have -- the decoded
 * action fields (`a_op a_pin a_lvl a_dly a_cnt a_q`), the lane (`cur`), the
 * FSM state, `eng_run`, `cfg_err_any`, the pins -- so the two runs are
 * compared on what the engine DID, not on how its words are encoded.
 *
 * Output, every cycle counted from rst_n (posedges), so a free-running
 * counter (the status serialiser) is compared too:
 *   D <cycle> <lane> <op> <pin> <lvl> <dly> <cnt> <q>   per dispatch
 *   P <cycle> <uo_out> <uio_out> <uio_oe>                per output change
 *   S <cycle>                                            the engine's start
 *   END cfg_err=<b> started=<0|1>
 *
 * ⛔⛔ THE OFFSET IS NOT HERE. `+PROGDLY=n` holds PROG n cycles past the last
 * load write; the GATE derives n from the load spec (the extra store bytes x
 * LOAD_CYC_PER_BYTE below) and never searches for it. LOAD_CYC_PER_BYTE is
 * the loader's own shape, printed so the gate reads it from here (one place).
 *
 * Plusargs: IMG NBYTES (required)  NCYC (cycles after the start, 6000)
 *           PROGDLY (0)
 */
`default_nettype none
`timescale 1ns / 1ps

`include "test/imgload.vh"
module tb_equiv;

  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00, uio_drv = 8'h00;
  wire [7:0] uo_out, uio_out, uio_oe;
  wire [7:0] uio_in = (uio_oe & uio_out) | (~uio_oe & uio_drv);

  // the image buffer is sized for the LARGER store (v2's); a v1 build simply
  // loads NBYTES = 256 of it
`include "test/store_filler.vh"
  localparam integer IMG_MAX = PE_STORE_BYTES;
  localparam integer PIN_PROG = 7, PIN_PTR = 5, PIN_WR = 6;
  // the loader below: data, 2 cycles, WR high 3, low 1 -- 6 cycles a byte
  localparam integer LOAD_CYC_PER_BYTE = 6;

  reg  [7:0] img [0:IMG_MAX-1];
  integer    img_bytes, i, ncyc, progdly, ecyc = 0, nd = 0, start = -1;
  reg [8*256-1:0] imgfile;
  reg [23:0] po = 24'hxxxxxx;
  reg        done = 1'b0;

  always #10 clk = ~clk;

  tt_um_protocol_emulator #(.SPL(2)) dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );
`include "test/progress.vh"
`include "test/host_feed.vh"

  // ⚠ ONE BLOCK for the count and every record, so nothing reads another
  // block's same-edge write (ruling RA3)
  always @(posedge clk) if (rst_n === 1'b1 && !done) begin
    ecyc = ecyc + 1;
    if (start < 0 && dut.eng_run === 1'b1) begin
      start = ecyc;
      $display("S %0d", start);
    end
    if (dut.u_eng.st == 1) begin
      $display("D %0d %0d %0d %0d %0d %0d %0d %0d", ecyc, dut.u_eng.cur,
               dut.u_eng.a_op, dut.u_eng.a_pin, dut.u_eng.a_lvl,
               dut.u_eng.a_dly, dut.u_eng.a_cnt, dut.u_eng.a_q);
      nd = nd + 1;
    end
    if ({uo_out, uio_out, uio_oe} !== po) begin
      $display("P %0d %h %h %h", ecyc, uo_out, uio_out, uio_oe);
      po = {uo_out, uio_out, uio_oe};
    end
  end

  initial begin
    if (!$value$plusargs("IMG=%s", imgfile)) begin
      $display("tb_equiv: FATAL -- +IMG required"); $finish;
    end
    if (!$value$plusargs("NBYTES=%d", img_bytes)) begin
      $display("tb_equiv: FATAL -- +NBYTES required"); $finish;
    end
    if (!$value$plusargs("NCYC=%d", ncyc)) ncyc = 6000;
    if (!$value$plusargs("PROGDLY=%d", progdly)) progdly = 0;
    $readmemh(imgfile, img);
    `PE_REQUIRE_IMG_LOADED(imgfile)
    $display("LOAD_CYC_PER_BYTE %0d", LOAD_CYC_PER_BYTE);
    hf_init;
    hf_set(0, 8'h5B, 8'h01, 8'h7A, 8'hC7);
    hf_set(1, 8'h5B, 8'h01, 8'h7A, 8'hC7);
    hf_set(2, 8'h5B, 8'h01, 8'h7A, 8'hC7);
    hf_set(3, 8'h5B, 8'h01, 8'h7A, 8'hC7);

    repeat (4) @(negedge clk);
    rst_n = 1;
    @(negedge clk);
    ui_in[PIN_PROG] = 1'b1;
    repeat (3) @(negedge clk); ui_in[PIN_PTR] = 1'b1; repeat (3) @(negedge clk);  // CDC3
    ui_in[PIN_PTR] = 1'b0; repeat (3) @(negedge clk);
    for (i = 0; i < img_bytes; i = i + 1) begin
      uio_drv = img[i];
      @(negedge clk); @(negedge clk);
      ui_in[PIN_WR] = 1'b1;
      @(negedge clk); @(negedge clk); @(negedge clk);
      ui_in[PIN_WR] = 1'b0;
      @(negedge clk);
    end
    repeat (progdly) @(negedge clk);
    ui_in[PIN_PROG] = 1'b0;
    uio_drv = 8'hFF;
    ui_in = 8'h00;
    hf_en = 1'b1;

    // run NCYC cycles past the start, or (no start) as long as a v2 run would
    i = 0;
    while (start < 0 ? (i < ncyc + 2 * LOAD_CYC_PER_BYTE * IMG_MAX) : (ecyc - start < ncyc)) begin
      @(posedge clk);
      i = i + 1;
    end
    done = 1'b1;
    if (start < 0) begin
      // a refusal arm: the engine must never have started
      pg_quiescent_ok = 1'b1;
      rs_nostart_ok   = 1'b1;
    end
    $display("END cfg_err=%0b started=%0d dispatches=%0d", dut.cfg_err_any,
             (start >= 0) ? 1 : 0, nd);
    $finish;
  end
endmodule
