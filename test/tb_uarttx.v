/* tb_uarttx.v -- UART-tx 8N1 at its RATED speed, judged by a PEER on the wire
 * (WF2 round 2, Wilson: every published lane needs an exact end-to-end
 * witness at its published rating, with peer-side timing judged).
 *
 * THE PEER is a UART receiver on `uo_out[0]` with its OWN clock: it detects
 * the start bit's falling edge and samples every bit at its NOMINAL centre,
 * (k + 0.5) * T after that edge, T = BITP cycles x (1 + ERR/1000). It does not
 * look at the engine at all.
 *   CONTENT  every frame, FROM THE FIRST, is the next byte the host pushed on
 *            queue 0, in order (the feeder's repeating pattern); the stop bit
 *            is 1. ⛔ Frame 0 used to be expected as 0x00 -- the reset
 *            register went out first (silicon fix #8, WF2); a 00 is now red.
 *   TIMING   each bit's level must hold over the middle 80 % of its nominal
 *            window (centre +- 0.4 T), so an edge more than 10 % of a bit off
 *            the peer's grid is RED, not merely "decoded anyway".
 *   COUNT    at least the frames the run's length allows, every one decoded.
 * Layer V3 (clocked_conform.vh) checks the same lane's bits on the bus, the
 * count exact, and its scheduler conformance against the published bound.
 *
 * Plusargs: IMG NBYTES NCYC (required)  BITP(434)  ERR(0, per mille)
 * Verdict: `UART-TX: ok -- ...` or `*** FAIL uart_tx: ...`.
 */
`default_nettype none
`timescale 1ns / 1ps

`include "test/imgload.vh"
module tb_uarttx;

  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00, uio_drv = 8'hFF;
  wire [7:0] uo_out, uio_out, uio_oe;
  wire [7:0] uio_in = (uio_oe & uio_out) | (~uio_oe & uio_drv);

`include "test/store_filler.vh"   // v2: PE_STORE_BYTES, never a typed 256
  localparam integer IMG_MAX = PE_STORE_BYTES;
  localparam integer PIN_PROG = 7, PIN_PTR = 5, PIN_WR = 6;
  localparam integer TX_BIT = 0;              // uo_out[0], P_TX_UO

  reg  [7:0] img [0:IMG_MAX-1];
  integer    img_bytes, i, ncyc, bitp, err;
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

  // ---- THE PEER: a UART receiver on its own clock ------------------------
  real       bt;                              // the peer's bit time, ns
  real       t0;
  integer    n_frames = 0, n_bad = 0, n_tbad = 0, n_ferr = 0, k;
  integer    pat_i = 0;
  reg        running = 1'b0;
  reg  [7:0] got, want;
  reg        lvl, ok_win;
  initial begin
    wait (running);
    forever begin
      @(negedge uo_out[TX_BIT]);              // a start bit's falling edge
      t0 = $realtime;
      got = 8'h00; ok_win = 1'b1;
      // the start bit, 8 data bits LSB first, the stop bit: k = 0..9. Each
      // is read at its CENTRE (t0 + (k + 0.5) T) and must hold the same level
      // at t0 + (k + 0.1) T and t0 + (k + 0.9) T: the middle 80 %.
      for (k = 0; k < 10; k = k + 1) begin
        #(t0 + bt * (k + 0.1) - $realtime);
        lvl = uo_out[TX_BIT];
        #(t0 + bt * (k + 0.5) - $realtime);
        if (uo_out[TX_BIT] !== lvl) ok_win = 1'b0;
        lvl = uo_out[TX_BIT];
        #(t0 + bt * (k + 0.9) - $realtime);
        if (uo_out[TX_BIT] !== lvl) ok_win = 1'b0;
        if (k == 0 && lvl !== 1'b0) ok_win = 1'b0;
        if (k >= 1 && k <= 8) got[k - 1] = lvl;
        if (k == 9 && lvl !== 1'b1) n_ferr = n_ferr + 1;
      end
      want = hf_pat[0][pat_i];
      pat_i = (pat_i + 1) % hf_len[0];
      if (got !== want) begin
        n_bad = n_bad + 1;
        if (n_bad <= 6)
          $display("*** FAIL uart_tx: frame %0d decoded %02h, the host fed %02h%0s",
                   n_frames, got, want,
                   (n_frames == 0 && got === 8'h00) ? " (the reset register -- silicon fix #8 undone?)" : "");
      end
      if (!ok_win) begin
        n_tbad = n_tbad + 1;
        if (n_tbad <= 6)
          $display("*** FAIL uart_tx: frame %0d -- a bit's level did not hold over the middle 80%% of its nominal window", n_frames);
      end
      n_frames = n_frames + 1;
    end
  end

  integer fails;
  initial begin
    if (!$value$plusargs("IMG=%s", imgfile)) begin
      $display("tb_uarttx: FATAL -- +IMG required"); $finish;
    end
    if (!$value$plusargs("NBYTES=%d", img_bytes)) begin
      $display("tb_uarttx: FATAL -- +NBYTES required"); $finish;
    end
    if (!$value$plusargs("NCYC=%d", ncyc)) begin
      $display("tb_uarttx: FATAL -- +NCYC required"); $finish;
    end
    if (!$value$plusargs("BITP=%d", bitp)) bitp = 434;
    if (!$value$plusargs("ERR=%d", err)) err = 0;
    bt = 20.0 * bitp * (1000.0 + err) / 1000.0;
    $readmemh(imgfile, img);
    `PE_REQUIRE_IMG_LOADED(imgfile)
    // ⭐ NON-PALINDROMIC (ruling 1b): a byte sent MSB-first by mistake is a
    // different byte
    hf_init;
    hf_set(0, 8'h5B, 8'hC4, 8'h1E, 8'hA7);    // rev DA 23 78 E5
    $display("# uarttx img=%0s ncyc=%0d bitp=%0d err=%0d", imgfile, ncyc,
             bitp, err);

    repeat (4) @(negedge clk);
    rst_n = 1;
    @(negedge clk);
    ui_in[PIN_PROG] = 1'b1;
    repeat (3) @(negedge clk); ui_in[PIN_PTR] = 1'b1; repeat (3) @(negedge clk);
    ui_in[PIN_PTR] = 1'b0; repeat (3) @(negedge clk);
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
    running = 1'b1;
    hf_en = 1'b1;

    repeat (ncyc) @(posedge clk);
    running = 1'b0;
    fails = 0;
    hf_check(n_frames * 8);
    fails = fails + hf_bad;
    // ⛔ THE COUNT: the run's length allows floor(ncyc / (10 * bitp)) frames;
    // one may be in flight at the end, so at least that many minus one must
    // have been decoded -- a lane that stopped sending is red here
    if (n_frames < ncyc / (10 * bitp) - 1) begin
      fails = fails + 1;
      $display("*** FAIL uart_tx: only %0d frame(s) decoded in %0d cycles -- at %0d cycles/bit the run allows %0d",
               n_frames, ncyc, bitp, ncyc / (10 * bitp));
    end
    if (n_bad != 0) begin
      fails = fails + 1;
      $display("*** FAIL uart_tx: %0d of %0d frame(s) are not the bytes the host fed", n_bad, n_frames);
    end
    if (n_tbad != 0) begin
      fails = fails + 1;
      $display("*** FAIL uart_tx: %0d frame(s) broke the peer's timing window", n_tbad);
    end
    if (n_ferr != 0) begin
      fails = fails + 1;
      $display("*** FAIL uart_tx: %0d frame(s) with a stop bit of 0", n_ferr);
    end
    if (fails == 0)
      $display("UART-TX: ok -- %0d frame(s) at %0d cycles/bit (peer error %0d/1000): every frame from the first the host's byte in order, stop bits 1, every bit level held over the middle 80%% of its nominal window",
               n_frames, bitp, err);
    $finish;
  end
endmodule
`default_nettype wire
