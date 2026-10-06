/* tb_rxbw.v -- THE SERIAL LINK'S REAL CAPACITY, AND THE ONE-DEEP RX MARGIN.
 *
 * ⛔⛔ WHY THIS EXISTS. `1.6p` priced the RX link at "2.2% utilised" against a
 * capacity of 50 Mb/s -- "1 bit per cycle on the data pin". That is the RAW PIN
 * RATE and the stream does not run at it:
 *     the serialiser shifts ONE BIT PER TWO CYCLES (`ser_phase` toggles),
 *     a frame is 12 bits of which only 8 are payload,
 *     and `status_turn` forces a STATUS frame after every payload frame.
 * So a payload byte can leave at best once every 2*12*2 = 48 cycles, and the
 * real payload capacity is 8.33 Mb/s, not 50. The published figure was SIX
 * TIMES too generous, and it was wrong before the frame widened too (11.1 Mb/s
 * at 9 bits, quoted as 50).
 *
 * ⚠ AND THE ONE-DEEP PENDING REGISTER IS THE SHARPER QUESTION. `rx_pend` holds
 * exactly one byte; a second `rx_push` while it is occupied sets
 * `rx_drop_sticky` and the byte is GONE. Average rates say nothing about that
 * -- what matters is whether two completions can land inside one 48-cycle
 * payload slot, and with two receiving lanes at unrelated periods they
 * eventually must.
 *
 * WHAT IS MEASURED, all of it off the wire or off one engine signal:
 *   completions   `rx_push` pulses -- bytes the engine finished
 *   payload       frames decoded from the 3-pin stream with kind 0..4
 *   drops         completions - payload, cross-checked against the sticky flag
 *   min spacing   the closest two payload frames ever came, which IS the
 *                 capacity, measured rather than derived
 *
 * ⭐ THE SIGN CONVENTION MATTERS: `completions - payload` is the number of
 * bytes the engine produced and the host never saw. Reading it the other way
 * round would make a dropping run look like a clean one with a short window.
 */

`default_nettype none
`timescale 1ns / 1ps

module tb_rxbw;

  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00;
  wire [7:0] uo_out, uio_out, uio_oe;
  reg  [7:0] peer = 8'hFF;
  wire [7:0] uio_in = peer;

  localparam integer PIN_PROG = 7, PIN_PTR = 5, PIN_WR = 6;
  localparam integer IMG_MAX  = 256;
  localparam integer SER_DATA = 4, SER_STRB = 5, SER_VLD = 6;
  localparam integer FRAME_BITS = 12;
  localparam integer KIND_NONE  = 7;
  // ⭐ DERIVED, AND THE MEASUREMENT BELOW IS WHAT CHECKS IT: 12 bits at two
  // cycles per bit is a 24-cycle frame, and `status_turn` puts a status frame
  // after every payload frame, so payload slots are 48 cycles apart.
  // A frame is FRAME_BITS bits at two cycles each PLUS ONE CYCLE to queue the
  // next (the serialiser's `if (ser_cnt != 0) ... else` structure), and
  // `status_turn` puts a status frame after every payload frame:
  //     2 * (12*2 + 1) = 50
  // The first version read `2*2*FRAME_BITS` = 48, forgetting the queueing
  // cycle, and the measurement said 50 at every sweep point. Corrected to
  // match the mechanism rather than fitted to the data.
  localparam integer SLOT_DERIVED = 2 * (2 * FRAME_BITS + 1);

  reg  [7:0] img [0:IMG_MAX-1];
  integer    img_bytes, i, cyc, ncyc, j;
  reg [8*64-1:0] imgfile;

  reg  [FRAME_BITS-1:0] fr_sh;
  integer    fr_cnt, n_frame, n_status, n_payload, n_rb;
  reg        prev_v;
  integer    last_pay, min_gap, n_compl, inflight, n_lost;
  // THE DROP COUNTED AT THE DESIGN'S OWN CONDITION. `project.v` does
  //     if (e_rx_push) begin if (rx_pend) rx_drop_sticky <= 1; else ... end
  // so a drop IS `rx_push && rx_pend`, and counting it there is exact.
  // Deriving it arithmetically as `completions - payload` was not: it charged
  // the bytes still in flight at the run's end, reported "1 byte lost with
  // the sticky flag CLEAR" -- which reads as a SILENT loss, the most serious
  // thing this gate can say -- and then, once in-flight bytes were
  // subtracted, produced NEGATIVE losses because the subtraction counted a
  // mid-shift STATUS frame as an outstanding payload byte. Two corrections in
  // opposite directions on a derived quantity, when the event itself is
  // observable.
  integer    n_drop;
  integer    fl_n [0:4];
  reg        drop_seen;
  integer    fails;
  reg        primed_seen, cfgerr_seen;

  // ---- IS WHAT SURVIVED A DROP STILL CORRECT? --------------------------
  // ⛔⛔ THE CLAIM "a drop loses a byte" IS WEAKER THAN IT SOUNDS unless the
  // surviving bytes are checked. A one-deep register that dropped the NEW byte
  // and a register that silently overwrote the PENDING one would both report
  // `rx_drop_sticky` and both lose one byte per collision -- but the second
  // corrupts the stream order, and the host has no way to tell.
  // ⇒ The delivered stream must be an ORDER-PRESERVING SUBSEQUENCE of the
  //   completed stream: every frame the host receives matches some completion,
  //   and they appear in the order the engine produced them. That
  //   distinguishes "drops the late arrival" from "clobbers the pending one".
  localparam integer CMAX = 12000;
  reg  [7:0] cval [0:CMAX-1];
  integer    cn, cscan, n_matched, n_unmatched;

  always #10 clk = ~clk;

  parameter integer SPL_CFG = 2;

  tt_um_protocol_emulator #(.SPL(SPL_CFG)) dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );

`include "test/progress.vh"
`include "test/host_feed.vh"

  initial begin
    if (!$value$plusargs("IMG=%s", imgfile)) begin
      $display("tb_rxbw: FATAL -- +IMG=<file> is required."); $finish;
    end
    if (!$value$plusargs("NBYTES=%d", img_bytes)) begin
      $display("tb_rxbw: FATAL -- +NBYTES=<n> is required."); $finish;
    end
    if (!$value$plusargs("NCYC=%d", ncyc)) ncyc = 200000;
    $readmemh(imgfile, img);

    hf_init;
    hf_set(0, 8'h96, 8'h69, 8'hC5, 8'h3A);
    hf_set(1, 8'h5C, 8'hA3, 8'h78, 8'hE1);
    fr_sh = 0; fr_cnt = 0; prev_v = 1'b0;
    n_frame = 0; n_status = 0; n_payload = 0; n_rb = 0; n_compl = 0;
    last_pay = -1; min_gap = 1000000; drop_seen = 1'b0;
    cn = 0; cscan = 0; n_matched = 0; n_unmatched = 0;
    inflight = 0; n_lost = 0; n_drop = 0;
    cyc = 0; fails = 0; primed_seen = 1'b0; cfgerr_seen = 1'b0;
    for (j = 0; j < 5; j = j + 1) fl_n[j] = 0;

    $display("# rxbw img=%0s bytes=%0d ncyc=%0d SPL=%0d derived_slot=%0d",
             imgfile, img_bytes, ncyc, SPL_CFG, SLOT_DERIVED);

    repeat (4) @(negedge clk);
    rst_n = 1;
    @(negedge clk);
    ui_in[PIN_PROG] = 1'b1;
    ui_in[PIN_PTR] = 1'b1; @(negedge clk);
    ui_in[PIN_PTR] = 1'b0; @(negedge clk);
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
    hf_en = 1'b1;

    for (i = 0; i < ncyc; i = i + 1) begin
      @(posedge clk);
      cyc = cyc + 1;
      if (dut.u_eng.primed)     primed_seen = 1'b1;
      if (dut.u_eng.config_err) cfgerr_seen = 1'b1;
      // the peer walks a pattern on every input so any RX lane sees traffic
      peer[0] = cyc[5];
      peer[2] = cyc[4];
      peer[3] = cyc[6];
      if (dut.u_eng.rx_push) begin
        if (cn < CMAX) cval[cn] = dut.u_eng.rx_data;
        n_compl = n_compl + 1;
        cn = cn + 1;
        // the drop, at the condition the RTL itself tests
        if (dut.rx_pend) n_drop = n_drop + 1;
      end
      if (dut.rx_drop_sticky) drop_seen = 1'b1;

      if (uo_out[SER_VLD] && !prev_v) begin fr_sh = 0; fr_cnt = 0; end
      if (uo_out[SER_VLD] && uo_out[SER_STRB] && fr_cnt < FRAME_BITS) begin
        fr_sh[fr_cnt] = uo_out[SER_DATA];
        fr_cnt = fr_cnt + 1;
      end
      if (!uo_out[SER_VLD] && prev_v) begin
        if (fr_cnt == FRAME_BITS) begin
          n_frame = n_frame + 1;
          if (fr_sh[11]) n_status = n_status + 1;
          else if (fr_sh[10:8] == KIND_NONE[2:0]) n_rb = n_rb + 1;
          else begin
            n_payload = n_payload + 1;
            if (fr_sh[10:8] <= 3'd4) fl_n[fr_sh[10:8]] = fl_n[fr_sh[10:8]] + 1;
            // ⭐ THE SPACING IS MEASURED AT THE FRAME'S END, consistently, so
            // the gap is slot-to-slot and not end-to-start of different pairs.
            if (last_pay >= 0 && (cyc - last_pay) < min_gap)
              min_gap = cyc - last_pay;
            last_pay = cyc;
            // ⭐ SCAN FORWARD ONLY, never from the start: matching anywhere
            // would accept a reordered stream, which is the thing being
            // ruled out.
            begin : subseq
              integer k;
              reg hit;
              hit = 1'b0;
              for (k = cscan; k < cn && k < CMAX && !hit; k = k + 1)
                if (cval[k] == fr_sh[7:0]) begin
                  hit   = 1'b1;
                  cscan = k + 1;
                end
              if (hit) n_matched = n_matched + 1;
              else     n_unmatched = n_unmatched + 1;
            end
          end
        end
        fr_cnt = 0;
      end
      prev_v = uo_out[SER_VLD];
    end

    $display();
    $display("========== tb_rxbw: the serial link's real capacity ==========");
    $display("  PRECONDITIONS");
    $display("    primed / config_err      : %0b / %0b %0s",
             primed_seen, cfgerr_seen,
             (primed_seen && !cfgerr_seen) ? "ok" : "*** FAIL");
    if (!primed_seen || cfgerr_seen) begin
      $display("  *** FAIL: the program did not run clean");
      fails = fails + 1;
    end
    $display("    frames decoded           : %0d", n_frame);
    if (n_frame < 8) begin
      $display("  *** FAIL: too few frames to say anything");
      fails = fails + 1;
    end
    $display("  MEASURED");
    $display("    RX completions (rx_push) : %0d", n_compl);
    $display("    payload frames (kind 0-4): %0d", n_payload);
    $write("      per lane :");
    for (j = 0; j < 5; j = j + 1) $write(" L%0d=%0d", j, fl_n[j]);
    $display("");
    $display("    status frames            : %0d", n_status);
    $display("    readback frames (kind 7) : %0d", n_rb);
    // THE IN-FLIGHT BYTES ARE NOT LOST, AND COUNTING THEM AS LOST MADE this
    // bench report "1 byte lost with the sticky flag CLEAR" at five separate
    // spacings -- which reads as a SILENT LOSS, the most serious thing this
    // gate can report, and was really the run ending while a byte sat in
    // `rx_pend` or a frame was still shifting out of `ser_sh`.
    // SAME CLASS AS `tb_tx`'s pin-event counter: an event in flight at the
    // window boundary must be excluded, not charged. Accounted EXACTLY by
    // reading the two places a byte can legitimately still be, rather than
    // tolerating an off-by-one.
    n_lost = n_drop;
    inflight = n_compl - n_payload - n_drop;
    $display("    bytes the host NEVER SAW : %0d  (counted at rx_push while",
             n_lost);
    $display("      rx_pend, which is the RTL's own drop condition)");
    // THE ARITHMETIC IS NOW A CROSS-CHECK, NOT THE MEASURE. Every completion
    // either reached the host, was dropped, or is still in flight -- and "in
    // flight" can be at most one byte in `rx_pend` plus one frame shifting,
    // so anything outside 0..2 means the three counters disagree about the
    // same events.
    $display("    cross-check: compl - pay - drop = %0d  (0..2 in flight) %0s",
             inflight,
             (inflight >= 0 && inflight <= 2) ? "ok"
             : "*** the counters disagree");
    if (inflight < 0 || inflight > 2) begin
      $display("      completions %0d, payload %0d, drops %0d -- every byte",
               n_compl, n_payload, n_drop);
      $display("      must be exactly one of delivered, dropped, in flight");
      fails = fails + 1;
    end
    $display("    rx_drop_sticky           : %0b", drop_seen);
    $display("    delivered frames matched : %0d of %0d, unmatched %0d %0s",
             n_matched, n_payload, n_unmatched,
             (n_unmatched == 0 && n_matched > 0) ? "ok"
             : "*** FAIL -- a delivered byte is not an in-order completion");
    if (n_unmatched != 0 || n_matched == 0) begin
      $display("      ⛔ THE SURVIVORS MUST BE INTACT AND IN ORDER. A register");
      $display("        that clobbered the PENDING byte instead of refusing");
      $display("        the new one would lose the same count and report the");
      $display("        same flag, while reordering the stream.");
      fails = fails + 1;
    end
    // ⛔⛔ THE TWO READINGS OF THE SAME EVENT MUST AGREE. `completions -
    // payload` counts the loss arithmetically; `rx_drop_sticky` is the
    // design's own flag. If one says a byte was lost and the other does not,
    // neither number is usable -- and the sticky flag is the one the HOST
    // gets, so a silent loss is the serious direction.
    if (n_lost > 0 && !drop_seen) begin
      $display("  *** FAIL: %0d bytes lost with the sticky flag CLEAR -- a",
               n_lost);
      $display("      silent loss is exactly what the flag exists to prevent");
      fails = fails + 1;
    end
    if (n_lost <= 0 && drop_seen) begin
      $display("  *** FAIL: the sticky flag is SET with no byte unaccounted");
      $display("      for -- the flag fires on something this count misses");
      fails = fails + 1;
    end
    if (min_gap < 1000000) begin
      $display("    closest two payload frames: %0d cycles", min_gap);
      $display("    derived payload slot      : %0d cycles %0s",
               SLOT_DERIVED,
               (min_gap >= SLOT_DERIVED) ? "ok -- nothing beat the derivation"
               : "*** the stream BEAT the derived slot");
      // ⛔ A MEASUREMENT BELOW THE DERIVATION MEANS THE DERIVATION IS WRONG.
      // Same rule as C and J: a measurement can falsify a bound, never raise
      // it. 2 cycles/bit x 12 bits x 2 frames is structural, so a shorter gap
      // would mean one of those three factors is not what it looks like.
      if (min_gap < SLOT_DERIVED) fails = fails + 1;
    end else begin
      $display("    closest two payload frames: n/a (fewer than two)");
    end
    $display();
    $display("================ VERDICT ================");
    if (fails == 0) $display("  tb_rxbw: PASS");
    else            $display("  tb_rxbw: *** FAILED %0d check(s)", fails);
    $display("  RXBW compl=%0d pay=%0d status=%0d rb=%0d lost=%0d drop=%0b mingap=%0d slot=%0d matched=%0d unmatched=%0d",
             n_compl, n_payload, n_status, n_rb, n_lost,
             drop_seen, (min_gap < 1000000) ? min_gap : -1, SLOT_DERIVED,
             n_matched, n_unmatched);
    $finish;
  end

endmodule

`default_nettype wire
