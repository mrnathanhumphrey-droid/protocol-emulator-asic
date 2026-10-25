/* tb_uartrx.v -- UART-rx 8N1 against a BAUD-ERRORED peer, bytes compared with
 * what the PEER SENT, count exact (Wilson's UART ruling).
 *
 * ⛔ WHY. Five lanes are published including UART-rx, and until this bench no
 * program received a real byte stream. The only receive checks on unclocked
 * lanes (V-RX, rx_e2e's mirror) rebuild bits from the pads at the CHIP'S OWN
 * sampling instant -- the same-hand reference that already encoded one defect.
 * HERE THE REFERENCE IS THE PEER: it knows every byte it sent and how many, so
 * the comparison is byte-for-byte and the count is exact. That also closes the
 * DL1 residual (a clean stop between bytes) for this lane.
 *
 * THE PEER: 8N1, LSB first, bit time = BITP cycles x (1 + ERR/1000) -- ERR in
 * per-mille, +20 = 2% slow, -30 = 3% fast. Edges are placed in REAL time, so
 * an off-nominal baud drifts across the clock grid as a real one does
 * (never ON a clock edge: an edge within 0.5 ns of one is moved 1 ns later, so
 * no sampler races it). Idle gaps are drawn per frame: a quarter are
 * BACK-TO-BACK (stop bit straight into the next start), the rest 1..2 bit
 * times of idle.
 *
 * THE PROGRAM pushes TWO bytes per frame (test/uart_rx.py): the data byte, and
 * {stop, d7..d1} from the mid-stop sample -- the ISA has no compare, so the
 * framing check is this bench's (the host's): bit 7 of every second byte.
 *
 * Plusargs: IMG NBYTES (required) BITP(434) ERR(0) NFR(40) SEED(1)
 *           BADSTOP(-1: frame index sent with stop = 0 -- the framing must-fire)
 * Verdict: `UART-RX: ok -- ...` or `*** FAIL uart_rx: ...`.
 */
`default_nettype none
`timescale 1ns / 1ps
`include "test/imgload.vh"
module tb_uartrx;
  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00;
  wire [7:0] uo_out, uio_out, uio_oe;
  reg  [7:0] peer = 8'hFF;
  wire [7:0] uio_in = peer;
  localparam integer PIN_PROG = 7, PIN_PTR = 5, PIN_WR = 6;
`include "test/store_filler.vh"   // v2: PE_STORE_BYTES, never a typed 256
  localparam integer IMG_MAX = PE_STORE_BYTES;
  localparam integer P_RX = 3;
  localparam integer FMAX = 4096;

  reg  [7:0] img [0:IMG_MAX-1];
  integer    img_bytes, i, cyc, ncyc;
  reg [8*256-1:0] imgfile;
  integer    bitp, err, nfr, seed, badstop, f, b, gapc;
  // ⭐ PUSHES PER FRAME (Wilson: a MECHANISM image is still checked exactly).
  // 2 = the program (data + {stop, d7..d1}); 1 = the `nostop` image, whose
  // ONE push per frame must equal the peer's byte, count exact.
  integer    ppf;
  real       bt, tnext, tq;
  reg [31:0] rnd;
  reg  [7:0] sent [0:FMAX-1];
  integer    n_sent, n_push, n_bad, n_frame_err, fails, n_b2b;
  reg        peer_done, drop_seen;
  reg  [7:0] want;

  always #10 clk = ~clk;

  tt_um_protocol_emulator dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );

`include "test/progress.vh"
`include "test/clocked_conform.vh"

  function [31:0] lcg(input [31:0] s);
    lcg = s * 32'd1103515245 + 32'd12345;
  endfunction

  // drive the RX pad at an absolute real time, never ON a clock edge
  task at(input real t, input reg v);
    begin
      tq = t;
      if (tq - 10.0 * $floor(tq / 10.0) < 0.5) tq = tq + 1.0;
      if (tq > $realtime) #(tq - $realtime);
      // phase coverage, MEASURED: the bin (1 ns, after the posedge at
      // 10 + 20n) of every edge the peer actually drives
      if (peer[P_RX] !== v)
        ph_rx[$rtoi((tq - 10.0) - 20.0 * $floor((tq - 10.0) / 20.0))] = 1'b1;
      peer[P_RX] = v;
    end
  endtask
  reg [19:0] ph_rx = 20'd0;
  integer    phwalk, phb, phn;
  real       ph_d;

  // ---- THE PEER -----------------------------------------------------------
  initial begin
    peer_done = 1'b0;
    wait (rst_n === 1'b1 && ui_in[PIN_PROG] === 1'b0 && cyc > 200);
    tnext = $realtime + 3.0;
    for (f = 0; f < nfr; f = f + 1) begin
      rnd = lcg(rnd);
      sent[f] = rnd[23:16];
      n_sent = f + 1;                    // counted at its START: the data byte
      // ⭐ +PHWALK (phase coverage, Wilson 10-20): frame f starts at a sub-
      // cycle offset 20 * frac(f * 0.618034) ns. The step from frame f-1's
      // offset is taken MOD 20 so it is always >= 0: the idle (or a back-to-
      // back stop bit) before the frame lengthens by < 20 ns, never shortens.
      if (phwalk && f > 0) begin
        ph_d = 20.0 * ((f * 0.618034) - $floor(f * 0.618034))
             - 20.0 * (((f - 1) * 0.618034) - $floor((f - 1) * 0.618034));
        if (ph_d < 0.0) ph_d = ph_d + 20.0;
        tnext = tnext + ph_d;
      end
      at(tnext, 1'b0);                   // is pushed before the stop bit ends
      for (b = 0; b < 8; b = b + 1) begin
        tnext = tnext + bt;
        at(tnext, sent[f][b]);                           // LSB first
      end
      tnext = tnext + bt;
      at(tnext, (f == badstop) ? 1'b0 : 1'b1);           // STOP
      tnext = tnext + bt;
      rnd = lcg(rnd);
      gapc = (rnd[17:16] == 2'd0) ? 0 : 1 + (rnd[25:18] % (2 * bitp));
      if (f == badstop && gapc == 0) gapc = bitp;        // the line must idle
      if (gapc == 0 && f + 1 < nfr) n_b2b = n_b2b + 1;
      at(tnext, 1'b1);                                   // (idle high)
      tnext = tnext + 20.0 * gapc;
    end
    peer_done = 1'b1;
  end

  // ---- THE COMPARISON: chip pushes vs the peer's bytes, in order ----------
  always @(posedge clk) if (rst_n === 1'b1 && dut.u_eng.rx_push === 1'b1) begin
    if (dut.u_eng.rx_lane !== 0) begin
      n_bad = n_bad + 1;
      $display("*** FAIL uart_rx: a push from lane %0d (only lane 0 receives)", dut.u_eng.rx_lane);
    end else if (n_push / ppf >= n_sent) begin
      n_bad = n_bad + 1;
      $display("*** FAIL uart_rx: push %0d with only %0d frame(s) sent -- an extra byte", n_push, n_sent);
    end else begin
      f = n_push / ppf;
      if (n_push % ppf == 0) want = sent[f];
      else want = {(f == badstop) ? 1'b0 : 1'b1, sent[f][7:1]};
      if (n_push % ppf == 1 && dut.u_eng.rx_data[7] !== 1'b1) begin
        n_frame_err = n_frame_err + 1;
        $display("  uart_rx: FRAMING ERROR reported on frame %0d (stop sampled 0)", f);
      end
      if (dut.u_eng.rx_data !== want) begin
        n_bad = n_bad + 1;
        if (n_bad <= 6)
          $display("*** FAIL uart_rx: frame %0d %s byte: chip %02h, peer sent %02h",
                   f, (n_push % ppf) ? "stop" : "data", dut.u_eng.rx_data, want);
      end
    end
    n_push = n_push + 1;
  end

  initial begin
    if (!$value$plusargs("IMG=%s", imgfile)) begin
      $display("tb_uartrx: FATAL -- +IMG=<file> is required."); $finish;
    end
    if (!$value$plusargs("NBYTES=%d", img_bytes)) begin
      $display("tb_uartrx: FATAL -- +NBYTES=<n> is required."); $finish;
    end
    if (!$value$plusargs("BITP=%d", bitp)) bitp = 434;
    if (!$value$plusargs("ERR=%d", err)) err = 0;
    if (!$value$plusargs("NFR=%d", nfr)) nfr = 40;
    if (!$value$plusargs("SEED=%d", seed)) seed = 1;
    if (!$value$plusargs("BADSTOP=%d", badstop)) badstop = -1;
    if (!$value$plusargs("PPF=%d", ppf)) ppf = 2;
    if (!$value$plusargs("PHWALK=%d", phwalk)) phwalk = 0;
    if (nfr > FMAX) nfr = FMAX;
    bt = 20.0 * bitp * (1000.0 + err) / 1000.0;
    rnd = seed;
    n_sent = 0; n_push = 0; n_bad = 0; n_frame_err = 0; fails = 0; n_b2b = 0;
    drop_seen = 1'b0; cyc = 0;
    $readmemh(imgfile, img);
    `PE_REQUIRE_IMG_LOADED(imgfile)
    $display("# uartrx img=%0s bitp=%0d err=%0d/1000 nfr=%0d seed=%0d badstop=%0d",
             imgfile, bitp, err, nfr, seed, badstop);

    repeat (4) @(negedge clk);
    rst_n = 1;
    @(negedge clk);
    ui_in[PIN_PROG] = 1'b1;
    repeat (3) @(negedge clk); ui_in[PIN_PTR] = 1'b1; repeat (3) @(negedge clk);  // CDC3
    ui_in[PIN_PTR] = 1'b0; repeat (3) @(negedge clk);
    for (i = 0; i < img_bytes; i = i + 1) begin
      peer = img[i];
      @(negedge clk); @(negedge clk);
      ui_in[PIN_WR] = 1'b1;
      @(negedge clk); @(negedge clk); @(negedge clk);
      ui_in[PIN_WR] = 1'b0;
      @(negedge clk);
    end
    ui_in[PIN_PROG] = 1'b0;
    ui_in = 8'h00;
    peer  = 8'hFF;

    // run until the peer is done, then 20 bit times for the last frame
    while (!peer_done) begin
      @(posedge clk); cyc = cyc + 1;
      if (dut.rx_drop_sticky) drop_seen = 1'b1;
    end
    repeat (20 * bitp) begin
      @(posedge clk); cyc = cyc + 1;
      if (dut.rx_drop_sticky) drop_seen = 1'b1;
    end

    if (n_push != ppf * n_sent) begin
      fails = fails + 1;
      $display("*** FAIL uart_rx: %0d push(es) for %0d frame(s) -- expected EXACTLY %0d (%0s per frame)",
               n_push, n_sent, ppf * n_sent,
               (ppf == 2) ? "data + stop" : "data only");
    end
    if (n_bad != 0) begin
      fails = fails + 1;
      $display("*** FAIL uart_rx: %0d byte(s) differ from what the peer sent", n_bad);
    end
    if (drop_seen) begin
      fails = fails + 1;
      $display("*** FAIL uart_rx: rx_drop_sticky set -- a received byte was lost before the host");
    end
    if (n_frame_err != ((badstop >= 0 && badstop < n_sent) ? 1 : 0)) begin
      fails = fails + 1;
      $display("*** FAIL uart_rx: %0d framing error(s) reported, expected %0d",
               n_frame_err, (badstop >= 0 && badstop < n_sent) ? 1 : 0);
    end
    phn = 0;
    for (phb = 0; phb < 20; phb = phb + 1) phn = phn + ph_rx[phb];
    $display("UART-PHASE edges=%0d/20 bins=%020b phwalk=%0d (1 ns bins after the posedge, every RX edge the peer drove)",
             phn, ph_rx, phwalk);
    if (fails == 0)
      $display("UART-RX: ok -- %0d frame(s) (%0d back-to-back) at %0d cycles/bit, baud error %0d/1000: %0d push(es) exact (%0d per frame), every byte equals the peer's, framing errors %0d (expected %0d)",
               n_sent, n_b2b, bitp, err, n_push, ppf, n_frame_err,
               (badstop >= 0 && badstop < n_sent) ? 1 : 0);
    $finish;
  end
endmodule
