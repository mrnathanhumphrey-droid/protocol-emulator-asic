/* tb_tx.v -- T5.1: TWO TX LANES INTERLEAVE, EACH EMITTING ONLY ITS OWN BYTES.
 *
 * ⛔⛔ THE HOST DATA CHANNEL HAD NEVER BEEN DRIVEN BY ANY BENCH. `pe_isa.py`
 * has carried `host_pushes` since F1 was built and nothing in `test/` called
 * it, so every `OP_SHIFT` the suite ever executed found `host_valid = 0` and
 * took the UNDERRUN branch. The census image runs SHIFT -- which is how
 * `gate_cj_bounds` gets C on 8 of 8 opcodes -- and has never run it with a
 * BYTE IN THE QUEUE. The path from a queue to a wire was built, encoded in the
 * ISA, allowed for in the pin map, and unexercised.
 *
 * THE CLAIM UNDER TEST, from `src/project.v`'s own reasoning: with more than
 * one TX-consuming lane active, consumption order is the EDF dispatch
 * interleave, which depends on phase and timing, so THE HOST CANNOT PREDICT
 * WHICH LANE TAKES THE NEXT BYTE. A single tagged queue head-of-line blocks;
 * PER-LANE queues cannot. This bench pushes a fixed HOST-ORDERED sequence into
 * two queues and requires each lane to emit only its own, in order, however
 * the scheduler interleaves them.
 *
 * ⭐ WHY A WRONG ANSWER HERE WOULD BE SILENT. Nothing flags a lane
 * transmitting another lane's byte: the engine pops a queue, the lane shifts
 * what it got, and the wire carries a well-formed frame with the wrong
 * contents. That is the forbidden direction one level up from a wrong number
 * -- the same class as a timeout that proceeds -- so it is asserted rather
 * than inspected.
 *
 * ⚠ WHAT THIS BENCH DOES NOT SETTLE: the pin PATH beyond `uo_out`, protocol
 * framing (the program is eight SHIFTs and a re-arm, not UART), and the
 * channel's timing margin. It settles ownership and order.
 */

`default_nettype none
`timescale 1ns / 1ps

module tb_tx;

  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00, uio_in = 8'h00;
  wire [7:0] uo_out, uio_out, uio_oe;

  localparam integer IMG_MAX  = 256;
  localparam integer PIN_PROG = 7, PIN_PTR = 5, PIN_WR = 6;
  localparam integer NL       = 5;
  localparam integer NB       = 2;    // payload bytes per queue
  localparam integer MAXB     = 8;    // recorded bytes per lane
  // ⭐ PIN_LAG IS DERIVED FROM THE TWO REGISTER STAGES, NOT TUNED. `pin_out`
  // is assigned non-blocking in ST_DRIVE (valid the next cycle) and `uo_q`
  // registers `proto_out` once more, so a bit decided in cycle n appears on
  // `uo_out` in cycle n+2. ⛔ IT IS CHECKED, and a mismatch prints the lag
  // that WOULD have matched -- an assumed pipeline depth that is silently
  // wrong is how a bench ends up asserting on the previous bit.
  localparam integer PIN_LAG  = 2;

  reg  [7:0] img [0:IMG_MAX-1];
  integer    img_bytes, i, cyc, ncyc;
  reg [8*64-1:0] imgfile;

  // ---- the payload, and what each lane must emit ------------------------
  // ⛔ DISJOINT BYTE SETS, so "lane 1 emitted lane 0's byte" is detectable at
  // all. Four distinct values: a shared value would make the mutant
  // indistinguishable from correct behaviour on half the stream.
  reg  [7:0] q0 [0:NB-1];
  reg  [7:0] q1 [0:NB-1];

  // ---- per-lane bit/byte reconstruction ---------------------------------
  // ⭐ RECONSTRUCTED FROM THE DRIVE DECISION, which is what reaches the pin:
  // `OP_SHIFT` drives `pin_out[a_pin] <= l_data[cur][0]`, LSB first. The pin
  // itself is cross-checked below at PIN_LAG, so the byte-level claim and the
  // pin path are two separate readings rather than one.
  reg  [7:0] acc   [0:1];
  integer    nbit  [0:1];
  reg  [7:0] got   [0:1][0:MAXB-1];
  integer    ngot  [0:1];
  integer    nshift [0:1];

  // ---- the pin cross-check, AT EVERY CANDIDATE LAG -----------------------
  // ⛔⛔ THE LAG IS MEASURED, NOT ASSUMED, AND THE FIRST VERSION ASSUMED IT.
  // It compared only at PIN_LAG = 2 -- derived from "pin_out then uo_q, two
  // register stages" -- and reported 8 mismatches on each pin out of ~400.
  // An assumed pipeline depth that is wrong on a FRACTION of events is worse
  // than one that is wrong on all of them: it looks like a flaky pin instead
  // of a bookkeeping error.
  // ⇒ Every lag in 1..LAGMAX is counted, the bench reports the whole profile,
  //   and it requires SOME lag to match every event. PIN_LAG is then checked
  //   against the lag that did -- so the derivation is confirmed or named
  //   wrong, and the check is never weakened to fit.
  localparam integer LAGMAX = 5;
  reg        px_v  [0:1];
  reg        px_b  [0:1];
  reg        px_hit [0:1];
  integer    px_age [0:1];
  integer    px_m  [0:1][0:LAGMAX];
  integer    px_n  [0:1];
  integer    best_lag, best_hits, lg, n_diag;

  // ---- liveness and failure bookkeeping ---------------------------------
  integer    n_under, n_full, n_pops, fails, j;
  reg        primed_seen, cfgerr_seen;
  reg  [7:0] uo_seen_0, uo_seen_1;

  always #10 clk = ~clk;

  parameter integer SPL_CFG = 2;

  tt_um_protocol_emulator #(.SPL(SPL_CFG)) dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );

  // ⭐ THE DRIVE EVENT, read literally off the FSM: `st == ST_DRIVE` with the
  // current action a SHIFT. `cur`/`cur_act` are registered at the ST_IDLE ->
  // ST_DRIVE edge, so in ST_DRIVE they already name this job.
  wire       shifting = (dut.u_eng.st == 1) && (dut.u_eng.a_op == 3'd1);
  wire [2:0] sh_lane  = dut.u_eng.cur;
  wire       sh_bit   = dut.u_eng.l_data[dut.u_eng.cur][0];

  // ---- ONE PUSH OF ONE NIBBLE, with its tag -----------------------------
  // ⛔⛔ THE TAG GOES ON **BOTH** PUSHES, and `pe_isa.host_pushes` returns it
  // that way for the same reason: the hardware latches the tag with the HIGH
  // nibble, so a host that changed it between the two pushes of one byte would
  // split that byte across two queues. Repeating it makes that impossible from
  // this side too -- and must-fire 4 below deliberately breaks the rule to
  // show the latch is real.
  // ⚠ `ui_in[5]` AND `ui_in[0]` ARE THE TAG, and `ui_in[5]` is PIN_PTR in LOAD
  // mode. The pins are reused, so a push issued while PIN_PROG is still high
  // would be a pointer reset instead. Pushing only happens after load.
  task push_nib;
    input [3:0] nib;
    input [1:0] tag;
    begin
      ui_in[4:1] = nib;
      ui_in[5]   = tag[1];
      ui_in[0]   = tag[0];
      @(negedge clk); @(negedge clk);
      ui_in[PIN_WR] = 1'b1;
      @(negedge clk); @(negedge clk); @(negedge clk);
      ui_in[PIN_WR] = 1'b0;
      @(negedge clk);
    end
  endtask

  task push_byte;
    input [7:0] b;
    input [1:0] tag;
    begin
      push_nib(b[7:4], tag);        // HIGH NIBBLE FIRST -- a ruling
      push_nib(b[3:0], tag);
    end
  endtask

  task fail;
    input [8*72-1:0] msg;
    begin
      $display("  *** FAIL: %0s", msg);
      fails = fails + 1;
    end
  endtask

  initial begin
    if (!$value$plusargs("IMG=%s", imgfile)) begin
      $display("tb_tx: FATAL -- +IMG=<file> is required.");
      $finish;
    end
    if (!$value$plusargs("NBYTES=%d", img_bytes)) begin
      $display("tb_tx: FATAL -- +NBYTES=<n> is required. An image that never");
      $display("  loaded dispatches nothing, and 'no bytes emitted' would");
      $display("  read as a queue fault.");
      $finish;
    end
    if (!$value$plusargs("NCYC=%d", ncyc)) ncyc = 4000;
    $readmemh(imgfile, img);

    // ⛔ DISJOINT, AND NOT BIT-ROTATIONS OF EACH OTHER. 0xB1/0x4E against
    // 0x2D/0xD2: no value is a rotation or complement of a value in the other
    // queue, so a reconstruction that is off by a bit cannot accidentally
    // match the wrong queue's byte.
    q0[0] = 8'hB1; q0[1] = 8'h4E;
    q1[0] = 8'h2D; q1[1] = 8'hD2;

    for (j = 0; j < 2; j = j + 1) begin
      acc[j] = 8'h00; nbit[j] = 0; ngot[j] = 0; nshift[j] = 0;
      px_v[j] = 1'b0; px_b[j] = 1'b0; px_age[j] = 0; px_n[j] = 0;
      px_hit[j] = 1'b0;
      for (lg = 0; lg <= LAGMAX; lg = lg + 1) px_m[j][lg] = 0;
      for (i = 0; i < MAXB; i = i + 1) got[j][i] = 8'h00;
    end
    cyc = 0; n_under = 0; n_full = 0; n_pops = 0; fails = 0;
    best_lag = 0; best_hits = -1; n_diag = 0;
    primed_seen = 1'b0; cfgerr_seen = 1'b0;
    uo_seen_0 = 8'h00; uo_seen_1 = 8'h00;

    $display("# tx img=%0s bytes=%0d ncyc=%0d SPL=%0d",
             imgfile, img_bytes, ncyc, SPL_CFG);

    repeat (4) @(negedge clk);
    rst_n = 1;
    @(negedge clk);

    // ---- load ----------------------------------------------------------
    ui_in[PIN_PROG] = 1'b1;
    ui_in[PIN_PTR] = 1'b1; @(negedge clk);
    ui_in[PIN_PTR] = 1'b0; @(negedge clk);
    for (i = 0; i < img_bytes; i = i + 1) begin
      uio_in = img[i];
      @(negedge clk); @(negedge clk);
      ui_in[PIN_WR] = 1'b1;
      @(negedge clk); @(negedge clk); @(negedge clk);
      ui_in[PIN_WR] = 1'b0;
      @(negedge clk);
    end
    ui_in[PIN_PROG] = 1'b0;
    ui_in = 8'h00;
    uio_in = 8'hFF;

    // ---- the HOST-ORDERED pushes ---------------------------------------
    // ⛔⛔ INTERLEAVED BY THE HOST, CONSUMED BY THE SCHEDULER. The host emits
    // q0[0], q1[0], q0[1], q1[1] in that order and never learns which lane
    // dispatched first. If the queues were one tagged FIFO this order alone
    // would head-of-line block: whichever lane dispatches second waits behind
    // a byte addressed to the other.
    // ⚠ TWO BYTES PER QUEUE IS THE DEPTH (TXD = 2), SO THE QUEUES ARE EXACTLY
    // FULL AFTER THIS. A third byte would exercise `tx_full_sticky` instead,
    // which must-fire 5 does on purpose.
    push_byte(q0[0], 2'd0);
    push_byte(q1[0], 2'd1);
    push_byte(q0[1], 2'd0);
    push_byte(q1[1], 2'd1);

    // ---- run and reconstruct -------------------------------------------
    for (i = 0; i < ncyc; i = i + 1) begin
      @(posedge clk);
      cyc = cyc + 1;
      if (dut.u_eng.primed)     primed_seen = 1'b1;
      if (dut.u_eng.config_err) cfgerr_seen = 1'b1;
      if (dut.u_eng.host_pop)   n_pops = n_pops + 1;
      uo_seen_0 = uo_seen_0 | (uo_out[0] ? 8'h01 : 8'h02);
      uo_seen_1 = uo_seen_1 | (uo_out[1] ? 8'h01 : 8'h02);

      // the pin cross-check: score EVERY lag, decide afterwards
      for (j = 0; j < 2; j = j + 1) begin
        if (px_v[j]) begin
          px_age[j] = px_age[j] + 1;
          if (px_age[j] <= LAGMAX) begin
            if (uo_out[j] === px_b[j]) begin
              px_m[j][px_age[j]] = px_m[j][px_age[j]] + 1;
              px_hit[j] = 1'b1;
            end
          end
          if (px_age[j] >= LAGMAX) begin
            px_v[j] = 1'b0;
            // ⛔⛔ AN EVENT IS COUNTED AS SCORED ONLY WHEN IT RESOLVES, and
            // counting it at the START was wrong at the run boundary. A drive
            // in the last few cycles never gets its lag window, so it could
            // never match -- and at SPL = 1 that produced exactly ONE
            // unexplained event out of 847, which read as a pin-path finding
            // and was a bench artefact. ⚠ The giveaway was that the count
            // differed between the two depths (407 vs 406) while the ownership
            // result was identical: a reading whose denominator moves with a
            // parameter that cannot affect it.
            px_n[j] = px_n[j] + 1;
            // ⭐ AN EVENT THE PIN NEVER CARRIED, PRINTED WHEN IT HAPPENS.
            // This is what turned "8 mismatches out of 440, which looks
            // flaky" into a diagnosis in one run: every unexplained event
            // read `drove=1 uo=0`, and exactly 8 per lane is exactly the
            // number of 1 bits in each queue's payload -- so EVERY 1 was
            // being lost, which pointed straight at the clock-pin write
            // overwriting the data bit. A count alone would not have said
            // that.
            if (!px_hit[j] && n_diag < 12) begin
              $display("    DIAG cyc=%0d pin=%0d drove=%0b uo=%0b",
                       cyc, j, px_b[j], uo_out[j]);
              n_diag = n_diag + 1;
            end
          end
        end
      end

      // ⭐ THE BIT, AND THE BYTE IT BUILDS. LSB FIRST, because that is the
      // order `l_data` shifts right in.
      if (shifting && sh_lane < 3'd2) begin
        j = sh_lane;
        nshift[j] = nshift[j] + 1;
        acc[j]    = {sh_bit, acc[j][7:1]};
        nbit[j]   = nbit[j] + 1;
        if (nbit[j] == 8) begin
          if (ngot[j] < MAXB) got[j][ngot[j]] = acc[j];
          ngot[j] = ngot[j] + 1;
          nbit[j] = 0;
        end
        // ⚠ ONLY WHEN NO CHECK IS PENDING. Two drives of one lane closer
        // together than LAGMAX would overlap, and the second would be scored
        // against a pin the first had already changed. Those events are
        // SKIPPED rather than mis-scored, and `px_n` counts the ones scored so
        // a run in which most were skipped cannot pass on a handful.
        if (!px_v[j]) begin
          px_v[j] = 1'b1; px_b[j] = sh_bit; px_age[j] = 0;
          px_hit[j] = 1'b0;
        end
      end

      for (j = 0; j < NL; j = j + 1) begin
        if (dut.u_eng.lane_underrun[j]) n_under = n_under + 1;
      end
      if (dut.tx_full_sticky) n_full = n_full + 1;
    end

    // ---- the verdict ---------------------------------------------------
    $display();
    $display("================ tb_tx: TX queue ownership ================");
    $display("  PRECONDITIONS");
    $display("    image bytes loaded      : %0d", img_bytes);
    $display("    primed observed         : %0b %0s", primed_seen,
             primed_seen ? "ok" : "*** FAIL");
    if (!primed_seen) fail("the engine never primed");
    $display("    config_err observed     : %0b %0s", cfgerr_seen,
             cfgerr_seen ? "*** FAIL" : "ok");
    if (cfgerr_seen) fail("config_err -- the program was refused at load");
    $display("    host pops observed      : %0d %0s", n_pops,
             (n_pops >= 2 * NB) ? "ok" : "*** FAIL");
    // ⛔⛔ THE PRECONDITION THAT MAKES THE REST MEAN ANYTHING. With no pops,
    // every lane shifts zeros out of a reset register and the byte comparison
    // below would be comparing the bench's expectation against silence. This
    // is the state the suite has ALWAYS been in.
    if (n_pops < 2 * NB)
      fail("fewer than 2*NB host pops -- the queues never delivered");
    $display("    pin 0 saw both levels   : %0b %0s", (uo_seen_0 == 8'h03),
             (uo_seen_0 == 8'h03) ? "ok" : "*** FAIL");
    $display("    pin 1 saw both levels   : %0b %0s", (uo_seen_1 == 8'h03),
             (uo_seen_1 == 8'h03) ? "ok" : "*** FAIL");
    if (uo_seen_0 != 8'h03 || uo_seen_1 != 8'h03)
      fail("a TX pin never changed -- the output path is dead");
    $display("    shifts lane 0 / lane 1  : %0d / %0d", nshift[0], nshift[1]);
    $display("    bytes seen lane0/lane1  : %0d / %0d", ngot[0], ngot[1]);
    $display("    underrun cycles         : %0d", n_under);
    $display("    tx_full_sticky cycles   : %0d", n_full);

    $display("  MUST-FIRE 1: the first byte out of each lane is 00");
    // ⭐ BY CONSTRUCTION, NOT BY LUCK: `l_data` resets to 0 and the first load
    // lands at the END of the first eight drives. Asserting it is what proves
    // the reconstruction is BYTE-ALIGNED -- if the framing were off by a bit
    // this would be the first thing to break, and every later comparison would
    // fail for a reason that had nothing to do with queues.
    for (j = 0; j < 2; j = j + 1) begin
      if (ngot[j] < 1) begin
        $display("    lane %0d: *** FAIL -- no complete byte", j);
        fails = fails + 1;
      end else begin
        $display("    lane %0d: %02h %0s", j, got[j][0],
                 (got[j][0] == 8'h00) ? "ok" : "*** FAIL (not byte-aligned)");
        if (got[j][0] != 8'h00) fails = fails + 1;
      end
    end

    $display("  MUST-FIRE 2: each lane emits ONLY its own queue, in order");
    $display("    host order was q0=%02h, q1=%02h, q0=%02h, q1=%02h",
             q0[0], q1[0], q0[1], q1[1]);
    for (j = 0; j < 2; j = j + 1) begin
      for (i = 0; i < NB; i = i + 1) begin
        if (ngot[j] < i + 2) begin
          $display("    lane %0d byte %0d: *** FAIL -- never emitted", j, i);
          fails = fails + 1;
        end else if (j == 0) begin
          $display("    lane 0 byte %0d: got %02h want %02h %0s", i,
                   got[0][i + 1], q0[i],
                   (got[0][i + 1] == q0[i]) ? "ok" : "*** FAIL");
          if (got[0][i + 1] != q0[i]) fails = fails + 1;
        end else begin
          $display("    lane 1 byte %0d: got %02h want %02h %0s", i,
                   got[1][i + 1], q1[i],
                   (got[1][i + 1] == q1[i]) ? "ok" : "*** FAIL");
          if (got[1][i + 1] != q1[i]) fails = fails + 1;
        end
      end
    end
    // ⛔⛔ AND THE CROSS-LANE CHECK, EXPLICITLY. The per-lane comparison above
    // already fails if a lane emits the wrong byte -- but it fails with "got
    // 2d want b1", which reads like a corrupt byte. Naming the OTHER QUEUE as
    // the source turns a value mismatch into a diagnosis, and that is the
    // whole finding this bench exists for.
    // ⛔ SCANNED OVER EVERY EMITTED BYTE AGAINST EVERY BYTE OF THE OTHER
    // QUEUE, and the first version compared only byte 0 against byte 0. Under
    // `M_TX_IGNORE_TAG` lane 1 emits queue 0's SECOND byte (lane 0 took the
    // first), so the narrow check did not fire and the mutant died only on
    // "got 4e want 2d" -- a value mismatch, which is not the stated reason.
    // A mutant that dies for a reason other than its own is a kill this
    // project does not accept.
    for (j = 0; j < 2; j = j + 1) begin
      for (i = 1; i <= NB; i = i + 1) begin
        if (ngot[j] > i) begin
          if (j == 0) begin
            if (got[0][i] == q1[0] || got[0][i] == q1[1])
              fail("lane 0 emitted a QUEUE 1 byte -- the queue tag was ignored");
          end else begin
            if (got[1][i] == q0[0] || got[1][i] == q0[1])
              fail("lane 1 emitted a QUEUE 0 byte -- the queue tag was ignored");
          end
        end
      end
    end

    $display("  MUST-FIRE 3: the pin carries the bit that was driven");
    $display("    match counts per lag, out of %0d / %0d scored events:",
             px_n[0], px_n[1]);
    for (j = 0; j < 2; j = j + 1) begin
      $write("      pin %0d:", j);
      for (lg = 1; lg <= LAGMAX; lg = lg + 1)
        $write("  lag%0d=%0d", lg, px_m[j][lg]);
      $display("");
    end
    // ⭐ THE LAG THAT EXPLAINS EVERY EVENT ON BOTH PINS, found rather than
    // assumed. A pin path cannot be correct at one lag for one pin and a
    // different lag for the other, so the same lag must account for both.
    best_lag = 0; best_hits = -1;
    for (lg = 1; lg <= LAGMAX; lg = lg + 1) begin
      if ((px_m[0][lg] + px_m[1][lg]) > best_hits) begin
        best_hits = px_m[0][lg] + px_m[1][lg];
        best_lag  = lg;
      end
    end
    $display("    best lag        : %0d  (%0d of %0d events on both pins)",
             best_lag, best_hits, px_n[0] + px_n[1]);
    $display("    PIN_LAG derived : %0d %0s", PIN_LAG,
             (best_lag == PIN_LAG) ? "ok -- the derivation holds"
             : "*** the derivation is WRONG, see below");
    if (px_n[0] < 8 || px_n[1] < 8) begin
      fail("too few scored pin events -- most drives overlapped");
    end else if (best_hits != (px_n[0] + px_n[1])) begin
      $display("    *** NO LAG EXPLAINS EVERY EVENT: the best accounts for");
      $display("        %0d of %0d. The pin does not simply follow the drive",
               best_hits, px_n[0] + px_n[1]);
      $display("        decision at a fixed depth, and THAT is the finding --");
      $display("        do not widen the tolerance to absorb it.");
      fails = fails + 1;
    end else if (best_lag != PIN_LAG) begin
      $display("    *** THE PIPELINE IS %0d DEEP, NOT %0d. Every event is",
               best_lag, PIN_LAG);
      $display("        explained at lag %0d, so the path is deterministic and",
               best_lag);
      $display("        the DERIVATION was wrong -- correct PIN_LAG, do not");
      $display("        weaken the check.");
      fails = fails + 1;
    end else begin
      $display("    ⇒ every scored event matches at the derived lag  ok");
    end

    $display("  MUST-FIRE 4: the tag is LATCHED with the high nibble");
    // ⛔ THE RULE BROKEN ON PURPOSE. A byte is pushed with tag 0 on its HIGH
    // nibble and tag 1 on its LOW nibble. The hardware latches at the first
    // push, so the whole byte must land in QUEUE 0 -- `tx_cnt[0]` rises and
    // `tx_cnt[1]` does not. If the tag were sampled per push the byte would
    // split, and a split byte is unrecoverable: half of it would eventually
    // appear on the wrong wire.
    begin : mf4
      integer c0_before, c1_before;
      c0_before = dut.tx_cnt[0];
      c1_before = dut.tx_cnt[1];
      push_nib(4'hA, 2'd0);          // high nibble, tag 0
      push_nib(4'h5, 2'd1);          // low nibble, tag 1 -- IGNORED
      repeat (4) @(negedge clk);
      $display("    tx_cnt[0] %0d -> %0d, tx_cnt[1] %0d -> %0d",
               c0_before, dut.tx_cnt[0], c1_before, dut.tx_cnt[1]);
      // ⚠ THE QUEUES ARE FULL BY NOW IF NOTHING HAS BEEN CONSUMED, so the
      // assertion is on queue 1 being UNTOUCHED, which holds either way. A
      // check that required queue 0 to RISE would be reporting the depth, not
      // the latch.
      // ⛔ COMPARED AS INTEGERS. `c1_before` is an `integer` and a
      // part-select on one is not portable Verilog-2001; `tx_cnt` zero-extends
      // into the comparison, which is what is wanted here.
      if (dut.tx_cnt[1] != c1_before)
        fail("the low nibble tag reached queue 1 -- the tag is not latched");
      else
        $display("    queue 1 untouched: tag latched with the high nibble  ok");
    end

    $display();
    $display("================ VERDICT ================");
    if (fails == 0)
      $display("  tb_tx: PASS (4 of 4 must-fires)");
    else
      $display("  tb_tx: *** FAILED %0d check(s)", fails);
    $display("  ⚠ SCOPE: ownership and ORDER, on a two-lane program at");
    $display("    d = 12/13. Not protocol framing, not channel timing, and");
    $display("    not the tag's 2-bit width limit (four queues, and the");
    $display("    escape hatch for a fifth is in project.v).");
    $finish;
  end

endmodule

`default_nettype wire
