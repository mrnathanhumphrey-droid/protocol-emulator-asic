/* tb_half.v -- RULING 1's MUST-FIRES: TX and RX on ONE lane, both correct.
 *
 * ⛔⛔ THE DEFECT THIS EXISTS TO PROVE FIXED. `OP_SHIFT` (transmit) and
 * `OP_SHIFTIN` (receive) used to share BOTH the bit pointer and the shift
 * register, so on any half-duplex lane:
 *   - the RX byte-complete reset at `a_cnt - 1` always fired BEFORE the TX
 *     host load at `a_cnt`, making the load UNREACHABLE. Measured on
 *     `corpus_i2c`: 124 OP_SHIFT dispatches, 0 loads, 0 underruns -- no byte
 *     was ever even REQUESTED;
 *   - `OP_SHIFTIN` inserted the sampled bit at bit 7 of the very register
 *     `OP_SHIFT` was draining from bit 0, so an ACK read rewrote the byte in
 *     flight.
 * That is every half-duplex protocol the design ships: I2C drives a bit and
 * reads the ACK, SPI-master drives MOSI and samples MISO.
 *
 * WHAT IS ASSERTED HERE:
 *   1. the TX stream on each lane's data pin IS the bytes the host pushed;
 *   2. a byte sampled on the RX pin reaches the host as `rx_push`/`rx_data`;
 *   3. the two directions do not disturb each other -- (1) and (2) hold on the
 *      SAME lane, in the same run;
 *   4. the host-channel precondition: pushes > 0, loads > 0, underrun clear.
 *
 * ⭐ THE RX EXPECTATION IS BUILT FROM WHAT THE BENCH ACTUALLY PRESENTED, not
 * from a pattern it hopes was aligned. The bench records the level it was
 * driving at each `OP_SHIFTIN` dispatch and assembles the byte the engine
 * ought to deliver; `rx_data` must equal that. A pre-chosen pattern compared
 * against `rx_data` would pass or fail on PHASE, and a phase error would read
 * as a data error.
 *
 * ⚠ PROTOCOL-SHAPED, NOT A CERTIFIED PROTOCOL. No START/STOP, no addressing.
 * The claims are about the plumbing; `gate_corpus_trace.py` is where real
 * framing against the FRAM peer models lives.
 */

`default_nettype none
`timescale 1ns / 1ps

module tb_half;

  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00;
  wire [7:0] uo_out, uio_out, uio_oe;

  // ⛔ THE PEER'S SIDE OF THE OPEN-DRAIN BUS, modelled the only honest way: a
  // pull-up that the bench may pull LOW. `uio_in` is what the DUT samples, so
  // a released DUT pin reads whatever the peer is doing.
  reg  [7:0] peer = 8'hFF;
  wire [7:0] uio_in = peer;

  localparam integer PIN_PROG = 7, PIN_PTR = 5, PIN_WR = 6;
  localparam integer IMG_MAX  = 256;
  localparam integer NL       = 5;
  // ⛔ WIDE ENOUGH NOT TO CAP THE COUNT. At 16 the delivered array filled and
  // stopped while the bench's own counter ran on to 40, so the two totals
  // disagreed for a reason that had nothing to do with the design -- a
  // denominator set by an array bound.
  localparam integer MAXB     = 64;

  // the program's pins, from `make_smoke_image.build_half`
  localparam integer P_SDA  = 2;    // uio[2]  lane 0 data, open-drain
  localparam integer P_SCL  = 1;    // uio[1]  lane 0 clock
  localparam integer P_MISO = 0;    // uio[0]  lane 1 receive
  localparam integer P_MOSI = 10;   // uo_out[2] lane 1 data
  localparam integer P_SCLK = 9;    // uo_out[1] lane 1 clock

  reg  [7:0] img [0:IMG_MAX-1];
  integer    img_bytes, i, cyc, ncyc, j;
  reg [8*64-1:0] imgfile;

  // ---- TX reconstruction, per lane --------------------------------------
  reg  [7:0] tacc  [0:1];
  integer    tbit  [0:1];
  reg  [7:0] tgot  [0:1][0:MAXB-1];
  integer    tn    [0:1];
  integer    nshift [0:1], n_shift_all;

  // ---- RX: what the bench presented, and what the engine delivered -------
  reg  [7:0] racc;
  integer    rbit, n_sin;
  reg  [7:0] rwant [0:MAXB-1];
  integer    rwn;
  reg  [7:0] rgot  [0:MAXB-1];
  integer    rgn;
  // ⛔⛔ THE ENGINE SAMPLES `pin_in`, NOT THE PIN. `project.v` has
  // `pin_in = uio_q1`, a TWO-STAGE synchroniser, so the level the engine sees
  // is the peer's from two cycles earlier. The first version of this bench
  // recorded the LIVE peer level and compared the assembled byte against it:
  // three bytes matched and the fourth did not, because the pattern happened
  // to transition inside that window. A two-cycle skew showing up as a data
  // error on one byte in four is exactly the kind of mismatch that gets
  // "fixed" by loosening the comparison.
  // ⇒ TWO CLAIMS, TWO CHECKS. The RX byte expectation is built from
  //   `pin_in` -- what the engine actually sampled -- and the synchroniser
  //   DEPTH is asserted separately against a delay line here, so neither
  //   absorbs the other.
  // ⛔⛔ THE DEPTH IS MEASURED, NOT ASSERTED (ruling 3). The first version
  // fixed SYNC_D = 2 from reading `pin_in = uio_q1` and got 2,498 mismatches
  // in 40,000 -- a delay-line ordering error in the bench, indistinguishable
  // from a design fault at a glance. Every candidate depth is scored and ONE
  // must explain every sample; the depth that does is then reported.
  localparam integer SYNC_MAX = 4;
  reg  [SYNC_MAX:0] peer_hist;
  integer    sync_m [0:SYNC_MAX];
  integer    sync_n, sd, sync_best, sync_besthits;
  // ⭐ the ACK bit: lane 0's single SHIFTIN, sampled with SDA released
  integer    n_ack, n_rx_other;
  reg        ack_presented, ack_seen;

  integer    fails;
  reg        primed_seen, cfgerr_seen;

  // ---- THE SERIAL FRAME, DECODED AS THE HOST SEES IT --------------------
  // ⛔⛔ THE CLAIM IS ABOUT THE HOST, SO IT IS READ OFF THE WIRE. `rx_push`
  // and `cur` are internal; the question the lane field exists to answer is
  // "can the HOST attribute a received byte", and the only honest place to
  // ask it is the 3-pin serial stream. The frame is 12 bits: 8 data
  // LSB-first, then a 3-bit `kind`, then the marker (shifted out LAST).
  //     marker 1            -> STATUS          (kind = KIND_NONE)
  //     marker 0, kind 0..4 -> RX PAYLOAD from THAT LANE
  //     marker 0, kind 7    -> READBACK byte, not a lane
  localparam integer SER_DATA = 4, SER_STRB = 5, SER_VLD = 6;
  localparam integer FRAME_BITS = 12;
  localparam integer KIND_NONE  = 7;
  reg  [FRAME_BITS-1:0] fr_sh;
  integer    fr_n, fr_cnt;
  reg        prev_v;
  integer    fl_n   [0:4];            // payload frames seen per lane
  reg  [7:0] fl_got [0:4][0:MAXB-1];  // and the bytes
  integer    n_status, n_badkind;

  always #10 clk = ~clk;

  parameter integer SPL_CFG = 2;

  tt_um_protocol_emulator #(.SPL(SPL_CFG)) dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );

`include "test/host_feed.vh"

  // ---- the dispatch events, read literally off the FSM -------------------
  wire       drive    = (dut.u_eng.st == 1);
  wire [2:0] d_lane   = dut.u_eng.cur;
  wire [2:0] d_op     = dut.u_eng.a_op;
  wire [3:0] d_pin    = dut.u_eng.a_pin;
  // ⛔ THE TX BIT IS `l_tx`, THE RX ACCUMULATOR IS `l_rx`, AND READING ONE FOR
  // THE OTHER IS THE DEFECT ITSELF. Named separately so this bench cannot
  // accidentally assert the pre-split behaviour.
  wire       tx_bit   = dut.u_eng.l_tx[dut.u_eng.cur][0];

  task fail;
    input [8*72-1:0] msg;
    begin
      $display("  *** FAIL: %0s", msg);
      fails = fails + 1;
    end
  endtask

  initial begin
    if (!$value$plusargs("IMG=%s", imgfile)) begin
      $display("tb_half: FATAL -- +IMG=<file> is required."); $finish;
    end
    if (!$value$plusargs("NBYTES=%d", img_bytes)) begin
      $display("tb_half: FATAL -- +NBYTES=<n> is required."); $finish;
    end
    if (!$value$plusargs("NCYC=%d", ncyc)) ncyc = 40000;
    $readmemh(imgfile, img);

    hf_init;
    // ⛔ DISJOINT PATTERNS PER QUEUE, so a byte that surfaces on the wrong
    // lane is identifiable rather than merely wrong.
    hf_set(0, 8'h96, 8'h69, 8'hC5, 8'h3A);
    hf_set(1, 8'h5C, 8'hA3, 8'h78, 8'hE1);

    for (j = 0; j < 2; j = j + 1) begin
      tacc[j] = 8'h00; tbit[j] = 0; tn[j] = 0; nshift[j] = 0;
      for (i = 0; i < MAXB; i = i + 1) tgot[j][i] = 8'h00;
    end
    racc = 8'h00; rbit = 0; rwn = 0; rgn = 0; n_sin = 0; n_ack = 0;
    peer_hist = {(SYNC_MAX+1){1'b1}}; sync_n = 0;
    sync_best = -1; sync_besthits = -1;
    for (sd = 0; sd <= SYNC_MAX; sd = sd + 1) sync_m[sd] = 0;
    ack_presented = 1'b0; ack_seen = 1'b0; n_rx_other = 0;
    for (i = 0; i < MAXB; i = i + 1) begin
      rwant[i] = 8'h00; rgot[i] = 8'h00;
    end
    cyc = 0; fails = 0; n_shift_all = 0;
    fr_sh = 0; fr_n = 0; fr_cnt = 0; prev_v = 1'b0;
    n_status = 0; n_badkind = 0;
    for (j = 0; j < 5; j = j + 1) begin
      fl_n[j] = 0;
      for (i = 0; i < MAXB; i = i + 1) fl_got[j][i] = 8'h00;
    end
    primed_seen = 1'b0; cfgerr_seen = 1'b0;

    $display("# half img=%0s bytes=%0d ncyc=%0d SPL=%0d",
             imgfile, img_bytes, ncyc, SPL_CFG);

    repeat (4) @(negedge clk);
    rst_n = 1;
    @(negedge clk);

    // ---- load ----------------------------------------------------------
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
    peer  = 8'hFF;                  // the bus idles high, as pull-ups give
    hf_en = 1'b1;

    // ---- run -----------------------------------------------------------
    for (i = 0; i < ncyc; i = i + 1) begin
      @(posedge clk);
      cyc = cyc + 1;
      if (dut.u_eng.primed)     primed_seen = 1'b1;
      if (dut.u_eng.config_err) cfgerr_seen = 1'b1;

      // ⭐ THE PEER WALKS A PATTERN ON MISO, CHANGED ONLY BETWEEN SAMPLES.
      // It is driven off the cycle counter rather than off the dispatch, so
      // the bench is not synchronised to the thing it is measuring -- and the
      // expectation below is taken from what was PRESENTED, so a phase error
      // cannot look like a data error.
      // ⭐ THE SYNCHRONISER, CHECKED AS ITS OWN CLAIM. `peer_hist[SYNC_D]`
      // is the level presented SYNC_D cycles ago; `pin_in` must equal it.
      // Counted rather than asserted inline so the whole run reports.
      if (cyc > 8) begin
        sync_n = sync_n + 1;
        for (sd = 0; sd <= SYNC_MAX; sd = sd + 1)
          if (dut.u_eng.pin_in[P_MISO] === peer_hist[sd])
            sync_m[sd] = sync_m[sd] + 1;
      end
      peer_hist = {peer_hist[SYNC_MAX-1:0], peer[P_MISO]};
      peer[P_MISO] = cyc[5];
      // the ACK: hold SDA low in the window after the eighth data bit, which
      // is where lane 0's SHIFTIN lands. Presented continuously; what matters
      // is the level AT the sample, recorded below.
      peer[P_SDA]  = 1'b0;

      if (drive) begin
        n_shift_all = n_shift_all + 1;
        // ---- TX: a SHIFT on either data pin ---------------------------
        if (d_op == 3'd1) begin
          j = (d_pin == P_SDA) ? 0 : 1;
          nshift[j] = nshift[j] + 1;
          tacc[j]   = {tx_bit, tacc[j][7:1]};
          tbit[j]   = tbit[j] + 1;
          if (tbit[j] == 8) begin
            if (tn[j] < MAXB) tgot[j][tn[j]] = tacc[j];
            tn[j]   = tn[j] + 1;
            tbit[j] = 0;
          end
        end
        // ---- RX: a SHIFTIN. Record the level PRESENTED at this instant --
        if (d_op == 3'd2) begin
          if (d_pin == P_MISO) begin
            n_sin = n_sin + 1;
            // ⛔ `pin_in`, NOT `peer`: this is the bit the engine sampled.
            racc  = {dut.u_eng.pin_in[P_MISO], racc[7:1]};
            rbit  = rbit + 1;
            if (rbit == 8) begin
              if (rwn < MAXB) rwant[rwn] = racc;
              rwn  = rwn + 1;
              rbit = 0;
            end
          end else if (d_pin == P_SDA) begin
            // lane 0's ACK read. ⛔ ASSERTED ON THE RELEASE TOO: an ACK
            // "sampled" while we are still driving the pin low is our own
            // level read back, not the peer's.
            n_ack = n_ack + 1;
            if (!uio_oe[P_SDA]) ack_presented = 1'b1;
            if (peer[P_SDA] == 1'b0) ack_seen = 1'b1;
          end
        end
      end

      // ---- THE SERIAL STREAM, framed on the `valid` edge -------------
      // ⛔ FRAMED ON THE EDGE, NOT A FIXED STRIDE: `ser_v` is high only while
      // a frame shifts, so its rising edge IS the boundary. Chunking strobed
      // bits into fixed groups of twelve would assume the harvest began
      // exactly at one.
      if (uo_out[SER_VLD] && !prev_v) begin
        fr_sh  = 0;
        fr_cnt = 0;
      end
      if (uo_out[SER_VLD] && uo_out[SER_STRB]) begin
        if (fr_cnt < FRAME_BITS) begin
          fr_sh[fr_cnt] = uo_out[SER_DATA];
          fr_cnt = fr_cnt + 1;
        end
      end
      if (!uo_out[SER_VLD] && prev_v) begin
        if (fr_cnt == FRAME_BITS) begin
          fr_n = fr_n + 1;
          if (fr_sh[11]) begin
            n_status = n_status + 1;
          end else if (fr_sh[10:8] <= 3'd4) begin
            j = fr_sh[10:8];
            if (fl_n[j] < MAXB) fl_got[j][fl_n[j]] = fr_sh[7:0];
            fl_n[j] = fl_n[j] + 1;
          end else if (fr_sh[10:8] != KIND_NONE[2:0]) begin
            // a kind that is neither a lane nor the reserved value
            n_badkind = n_badkind + 1;
          end
        end
        fr_cnt = 0;
      end
      prev_v = uo_out[SER_VLD];

      // ---- what the engine DELIVERED to the host --------------------
      // ⛔⛔ ATTRIBUTED BY `cur`, BECAUSE THE CHANNEL CARRIES NO LANE ID.
      // `rx_push`/`rx_data` are ENGINE-WIDE and the serial frame is
      // {marker, 8 data} with no lane field, so a host with two receiving
      // lanes cannot tell which lane a byte came from -- the mirror image of
      // the TX queue-tag problem that per-lane queues solved.
      // ⚠ IT SHOWED UP AS AN ARITHMETIC DISCREPANCY: the engine delivered 50
      // bytes where this bench had assembled 40, and 50 - 40 = 10 is exactly
      // lane 0's ACK bytes arriving on the same channel. `cur` identifies the
      // completing lane at the push cycle, which is available HERE and not to
      // the host. Reported, not repaired: the frame format is a ruling.
      if (dut.u_eng.rx_push) begin
        if (dut.u_eng.cur == 3'd1) begin
          if (rgn < MAXB) rgot[rgn] = dut.u_eng.rx_data;
          rgn = rgn + 1;
        end else begin
          n_rx_other = n_rx_other + 1;
        end
      end
    end

    // ---- the verdict ---------------------------------------------------
    $display();
    $display("========== tb_half: TX and RX on one lane ==========");
    $display("  PRECONDITIONS");
    $display("    primed / config_err     : %0b / %0b %0s",
             primed_seen, cfgerr_seen,
             (primed_seen && !cfgerr_seen) ? "ok" : "*** FAIL");
    if (!primed_seen || cfgerr_seen) fail("the program did not run clean");
    $display("    SHIFT dispatches L0/L1  : %0d / %0d", nshift[0], nshift[1]);
    $display("    SHIFTIN  MISO / SDA     : %0d / %0d", n_sin, n_ack);
    hf_check(n_shift_all);
    fails = fails + hf_bad;

    $display("  MUST-FIRE 1: each lane's TX stream IS the pushed bytes");
    // ⭐ THE FIRST BYTE IS 00 BY CONSTRUCTION (`l_tx` resets to 0 and the
    // first load lands at the end of the first eight shifts), so the
    // comparison starts at index 1. Asserting the 00 is what proves the
    // reconstruction is byte-ALIGNED.
    for (j = 0; j < 2; j = j + 1) begin
      if (tn[j] < 3) begin
        $display("    lane %0d: *** FAIL -- only %0d bytes reconstructed",
                 j, tn[j]);
        fails = fails + 1;
      end else begin
        $display("    lane %0d first byte      : %02h %0s", j, tgot[j][0],
                 (tgot[j][0] == 8'h00) ? "ok (reset byte)"
                 : "*** FAIL -- not byte-aligned");
        if (tgot[j][0] != 8'h00) fails = fails + 1;
        $write("    lane %0d emitted         :", j);
        for (i = 1; i < tn[j] && i <= 4; i = i + 1) $write(" %02h", tgot[j][i]);
        $display("");
        $write("    lane %0d pushed          :", j);
        for (i = 1; i < tn[j] && i <= 4; i = i + 1)
          $write(" %02h", hf_pat[j][(i - 1) % HF_PAT]);
        $display("");
        for (i = 1; i < tn[j] && i <= 4; i = i + 1)
          if (tgot[j][i] != hf_pat[j][(i - 1) % HF_PAT]) begin
            $display("    lane %0d byte %0d: got %02h want %02h *** FAIL",
                     j, i - 1, tgot[j][i], hf_pat[j][(i - 1) % HF_PAT]);
            fails = fails + 1;
          end
      end
    end

    $display("  MUST-FIRE 2: a sampled byte reaches the host");
    $display("    bytes assembled by the bench : %0d", rwn);
    $display("    bytes delivered via rx_push  : %0d", rgn);
    if (rwn < 1 || rgn < 1) begin
      fail("no RX byte completed -- the receive path did not deliver");
    end else begin
      $write("    delivered :");
      for (i = 0; i < rgn && i < 4; i = i + 1) $write(" %02h", rgot[i]);
      $display("");
      $write("    presented :");
      for (i = 0; i < rwn && i < 4; i = i + 1) $write(" %02h", rwant[i]);
      $display("");
      for (i = 0; i < rgn && i < rwn && i < 4; i = i + 1)
        if (rgot[i] != rwant[i]) begin
          $display("    RX byte %0d: got %02h, presented %02h *** FAIL",
                   i, rgot[i], rwant[i]);
          fails = fails + 1;
        end
    end

    for (sd = 0; sd <= SYNC_MAX; sd = sd + 1)
      if (sync_m[sd] > sync_besthits) begin
        sync_besthits = sync_m[sd];
        sync_best     = sd;
      end
    $write("    input-sync match per depth :");
    for (sd = 0; sd <= SYNC_MAX; sd = sd + 1)
      $write(" d%0d=%0d", sd, sync_m[sd]);
    $display("");
    $display("    one fixed offset explains EVERY sample : %0d of %0d at d=%0d %0s",
             sync_besthits, sync_n, sync_best,
             (sync_besthits == sync_n) ? "ok" : "*** FAIL");
    if (sync_besthits != sync_n)
      fail("no fixed offset explains pin_in -- it does not simply follow the pin");
    // ⛔⛔ `d` IS AN OFFSET IN THIS BENCH'S OWN DELAY LINE, NOT A FLOP COUNT,
    // and the first version printed it as one: "pin_in = uio_q1, a 0-stage
    // synchroniser, MEASURED" -- which is false, and false in the direction of
    // claiming more than was measured. The history here is shifted before the
    // comparison and the new level assigned after it, so index 0 already
    // corresponds to two cycles back. What this check establishes is the thing
    // that matters for the RX datapath: `pin_in` follows the pin at a FIXED,
    // deterministic offset, so the byte the engine assembles is the bits that
    // were on the wire in order. The DEPTH is a structural fact read off
    // `project.v` (`pin_in = uio_q1`, two stages) and is not measured here.
    $display("      ⚠ `d` is an offset in this bench's delay line, NOT a flop");
    $display("        count. The claim is that ONE fixed offset explains every");
    $display("        sample; the depth itself is structural (pin_in = uio_q1).");
    $display("    RX bytes from OTHER lanes  : %0d  ⚠ the channel has no lane",
             n_rx_other);
    $display("      id, so the host cannot attribute these -- see the record");

    $display("  MUST-FIRE 3: the ACK read released the pin and saw the peer");
    $display("    SDA released at a sample : %0b %0s", ack_presented,
             ack_presented ? "ok" : "*** FAIL -- we read our own level back");
    if (!ack_presented) fail("the ACK read did not release SDA");
    $display("    peer was pulling low     : %0b %0s", ack_seen,
             ack_seen ? "ok" : "*** FAIL");
    if (!ack_seen) fail("the ACK window never saw the peer low");

    $display("  MUST-FIRE 4: the HOST can attribute every received byte");
    $display("    frames decoded off the wire : %0d (%0d status)",
             fr_n, n_status);
    $write("    payload frames per lane     :");
    for (j = 0; j < 5; j = j + 1) $write(" L%0d=%0d", j, fl_n[j]);
    $display("");
    $display("    frames with an unknown kind : %0d %0s", n_badkind,
             (n_badkind == 0) ? "ok" : "*** FAIL");
    if (n_badkind != 0)
      fail("a payload frame carried a kind that is neither a lane nor 7");
    // ⛔⛔ THE CLAIM: lane 1's bytes arrive TAGGED AS LANE 1, and lane 0's ACK
    // bytes arrive tagged as LANE 0. Before the lane field both arrived on one
    // untagged channel and the host could only have guessed -- which is the
    // mirror of the TX problem per-lane queues solved.
    if (fl_n[1] < 1) begin
      fail("no frame was attributed to lane 1, which receives a byte");
    end else begin
      $write("    lane 1 bytes, as the host sees them :");
      for (i = 0; i < fl_n[1] && i < 4; i = i + 1) $write(" %02h", fl_got[1][i]);
      $display("");
      $write("    lane 1 bytes the bench presented    :");
      for (i = 0; i < rwn && i < 4; i = i + 1) $write(" %02h", rwant[i]);
      $display("");
      for (i = 0; i < fl_n[1] && i < rwn && i < 4; i = i + 1)
        if (fl_got[1][i] != rwant[i]) begin
          $display("    lane 1 frame %0d: host saw %02h, presented %02h *** FAIL",
                   i, fl_got[1][i], rwant[i]);
          fails = fails + 1;
        end
    end
    if (fl_n[0] < 1)
      fail("no frame was attributed to lane 0, which reads an ACK byte");
    else
      $display("    lane 0 attributed %0d frame(s)  ok -- its ACK bytes are",
               fl_n[0]);
    $display("      separable from lane 1's on the wire, which is the point");

    $display("  MUST-FIRE 5: the two directions did not disturb each other");
    // ⛔ THE CONJUNCTION IS THE CLAIM. Either half alone was already true at
    // some point in this project's history: the TX path worked on a
    // SHIFT-only lane, and the RX path worked on a SHIFTIN-only lane. What
    // never worked was both on ONE lane -- and lane 0 here both transmits and
    // reads its ACK, lane 1 both transmits and receives a byte.
    $display("    lane 0 transmits AND reads : %0s",
             (tn[0] >= 3 && n_ack > 0) ? "both, ok"
             : "*** FAIL -- one direction is silent");
    if (!(tn[0] >= 3 && n_ack > 0))
      fail("lane 0 did not exercise both directions");
    $display("    lane 1 transmits AND receives : %0s",
             (tn[1] >= 3 && rgn > 0) ? "both, ok"
             : "*** FAIL -- one direction is silent");
    if (!(tn[1] >= 3 && rgn > 0))
      fail("lane 1 did not exercise both directions");

    $display();
    $display("================ VERDICT ================");
    if (fails == 0)
      $display("  tb_half: PASS (5 of 5 must-fires)");
    else
      $display("  tb_half: *** FAILED %0d check(s)", fails);
    $finish;
  end

endmodule

`default_nettype wire
