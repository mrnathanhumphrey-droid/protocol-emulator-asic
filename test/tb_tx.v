/* tb_tx.v -- T5.1: TWO TX LANES INTERLEAVE, EACH EMITTING ONLY ITS OWN BYTES.
 *
 * ⛔⛔ THE HOST DATA CHANNEL HAD NEVER BEEN DRIVEN BY ANY BENCH. `pe_isa.py`
 * has carried `host_pushes` since F1 was built and nothing in `test/` called
 * it, so every `OP_SHIFT` the suite ever executed found `host_valid = 0` and
 * took the UNDERRUN branch. The census image runs SHIFT -- which is how
 * `gate_cj_bounds` gets C on 8 of 8 opcodes -- and had never run it with a
 * BYTE IN THE QUEUE. The path from a queue to a wire was built, encoded in the
 * ISA, allowed for in the pin map, and unexercised.
 *
 * THE CLAIM UNDER TEST, from `src/project.v`'s own reasoning: with more than
 * one TX-consuming lane active, consumption order is the EDF dispatch
 * interleave, which depends on phase and timing, so THE HOST CANNOT PREDICT
 * WHICH LANE TAKES THE NEXT BYTE. A single tagged queue head-of-line blocks;
 * PER-LANE queues cannot.
 *
 * ⭐ CONTINUOUSLY FED, NOT PRE-LOADED, and that is a correction to this
 * bench's first version. It pushed four bytes, ran, and checked the first two
 * out of each lane -- after which both lanes STARVED and the run reported
 * 11,221 underrun cycles. It passed, but it could not satisfy Wilson's
 * standing precondition (ruling 0: a bench running a SHIFT must assert that a
 * push landed AND that underrun stayed clear), and it only ever checked two
 * bytes. `test/host_feed.vh` keeps both queues topped up from a repeating
 * 4-byte pattern, so the stream must equal that pattern CYCLICALLY for the
 * whole run and the lane never starves.
 *
 * ⭐ WHY A WRONG ANSWER HERE WOULD BE SILENT. Nothing flags a lane
 * transmitting another lane's byte: the engine pops a queue, the lane shifts
 * what it got, and the wire carries a well-formed frame with the wrong
 * contents. That is the forbidden direction one level up from a wrong number
 * -- the same class as a timeout that proceeds -- so it is asserted rather
 * than inspected.
 *
 * ⚠ WHAT THIS BENCH DOES NOT SETTLE: protocol framing (the program is eight
 * SHIFTs and a re-arm, not UART), channel timing margin, and the tag's 2-bit
 * width limit. It settles ownership and order.
 */

`default_nettype none
`timescale 1ns / 1ps

`include "test/imgload.vh"
module tb_tx;

  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00, uio_in = 8'h00;
  wire [7:0] uo_out, uio_out, uio_oe;

`include "test/store_filler.vh"   // v2: PE_STORE_BYTES, never a typed 256
  localparam integer IMG_MAX  = PE_STORE_BYTES;
  localparam integer PIN_PROG = 7, PIN_PTR = 5, PIN_WR = 6;
  localparam integer NL       = 5;
  localparam integer MAXB     = 24;   // recorded bytes per lane
  localparam integer CHECKB   = 8;    // bytes compared against the pattern
  // ⭐ PIN_LAG IS DERIVED FROM THE TWO REGISTER STAGES, NOT TUNED. `pin_out`
  // is assigned non-blocking in ST_DRIVE (valid the next cycle) and `uo_q`
  // registers `proto_out` once more, so a bit decided in cycle n appears on
  // `uo_out` in cycle n+2. ⛔ IT IS CHECKED against every candidate lag below.
  localparam integer PIN_LAG  = 2;

  reg  [7:0] img [0:IMG_MAX-1];
  integer    img_bytes, i, cyc, ncyc, badclk;
  reg [8*256-1:0] imgfile;

  // ---- per-lane bit/byte reconstruction ---------------------------------
  // ⭐ RECONSTRUCTED FROM THE DRIVE DECISION, which is what reaches the pin:
  // `OP_SHIFT` drives `pin_out[a_pin] <= l_tx[cur][0]`, LSB first. The pin
  // itself is cross-checked below, so the byte-level claim and the pin path
  // are two separate readings rather than one.
  reg  [7:0] acc   [0:1];
  integer    nbit  [0:1];
  reg  [7:0] got   [0:1][0:MAXB-1];
  integer    ngot  [0:1];
  integer    nshift [0:1];
  integer    n_shift_all;

  // ---- the pin cross-check, AT EVERY CANDIDATE LAG -----------------------
  // ⛔⛔ THE LAG IS MEASURED, NOT ASSUMED, AND THE FIRST VERSION ASSUMED IT.
  // It compared only at PIN_LAG = 2 -- derived from "pin_out then uo_q, two
  // register stages" -- and reported 8 mismatches on each pin out of ~440.
  // An assumed pipeline depth that is wrong on a FRACTION of events is worse
  // than one wrong on all of them: it looks like a flaky pin instead of a
  // bookkeeping error. ⇒ Every lag in 1..LAGMAX is counted, the whole profile
  // is printed, SOME lag must explain every event, and PIN_LAG is checked
  // against the lag that did.
  localparam integer LAGMAX = 5;
  reg        px_v  [0:1];
  reg        px_b  [0:1];
  reg        px_hit [0:1];
  integer    px_age [0:1];
  integer    px_m  [0:1][0:LAGMAX];
  reg        px_pend [0:1][0:LAGMAX];
  integer    px_n  [0:1];
  integer    best_lag, best_hits, lg, n_diag;

  integer    fails, j;
  reg        primed_seen, cfgerr_seen;
  reg  [7:0] uo_seen_0, uo_seen_1;

  always #10 clk = ~clk;

  parameter integer SPL_CFG = 2;

  tt_um_protocol_emulator #(.SPL(SPL_CFG)) dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );

  // ⛔ THE ONE HOST-CHANNEL DRIVER. This bench used to carry private
  // `push_nib`/`push_byte` tasks; they are now shared, because a push sequence
  // copied per bench is the same shape as the four private slot-index copies
  // that cost a published column.
`include "test/progress.vh"
`include "test/clocked_conform.vh"
`include "test/host_feed.vh"

  // ⭐ THE DRIVE EVENT, read literally off the FSM: `st == ST_DRIVE` with the
  // current action a SHIFT. `cur`/`cur_act` are registered at the ST_IDLE ->
  // ST_DRIVE edge, so in ST_DRIVE they already name this job.
  wire       shifting = (dut.u_eng.st == 1) && (dut.u_eng.a_op == 3'd1);
  wire [2:0] sh_lane  = dut.u_eng.cur;
  // ⛔ THE BIT THE ENGINE DRIVES (`tx_bit`), not `l_tx[cur][0]`: since
  // silicon fix #8 a byte's FIRST bit comes from the queue head and is never
  // in the register, so mirroring the register lost every byte's bit 0 --
  // the #6 lesson (a check that mirrors the chip's register encodes its
  // design). The pin-lag check below still holds this bit to the pad.
  wire       sh_bit   = dut.u_eng.tx_bit;

  task fail;
    input [8*72-1:0] msg;
    begin
      $display("  *** FAIL: %0s", msg);
      fails = fails + 1;
    end
  endtask

  task load_image;
    begin
      ui_in[PIN_PROG] = 1'b1;
      repeat (3) @(negedge clk); ui_in[PIN_PTR] = 1'b1; repeat (3) @(negedge clk);  // CDC3: prog >= 3 cy before ptr; ptr >= 3 cy wide
      ui_in[PIN_PTR] = 1'b0; repeat (3) @(negedge clk);
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
    end
  endtask

  // ---- the run, reconstructing both lanes' byte streams -----------------
  task observe;
    begin
      for (i = 0; i < ncyc; i = i + 1) begin
        @(posedge clk);
        cyc = cyc + 1;
        if (dut.u_eng.primed)     primed_seen = 1'b1;
        if (dut.u_eng.config_err) cfgerr_seen = 1'b1;
        uo_seen_0 = uo_seen_0 | (uo_out[0] ? 8'h01 : 8'h02);
        uo_seen_1 = uo_seen_1 | (uo_out[1] ? 8'h01 : 8'h02);

        // the pin cross-check: score EVERY lag, decide afterwards
        for (j = 0; j < 2; j = j + 1) begin
          if (px_v[j]) begin
            px_age[j] = px_age[j] + 1;
            // ⛔⛔ MATCHES ARE ACCUMULATED PER EVENT AND COMMITTED ONLY WHEN
            // THE EVENT RESOLVES. Incrementing `px_m` directly let the run's
            // final, unresolved event contribute a match while `px_n` never
            // counted it, so the gate printed "842 of 841 events" -- more
            // matches than events, which is impossible and was the same
            // boundary defect as `px_n` itself, in the opposite direction.
            if (px_age[j] <= LAGMAX) begin
              if (uo_out[j] === px_b[j]) begin
                px_pend[j][px_age[j]] = 1'b1;
                px_hit[j] = 1'b1;
              end
            end
            if (px_age[j] >= LAGMAX) begin
              px_v[j] = 1'b0;
              // ⛔⛔ AN EVENT IS COUNTED AS SCORED ONLY WHEN IT RESOLVES, and
              // counting it at the START was wrong at the run boundary. A
              // drive in the last few cycles never gets its lag window, so it
              // could never match -- and at SPL = 1 that produced exactly ONE
              // unexplained event out of 847, which read as a pin-path
              // finding and was a bench artefact. ⚠ The giveaway was that the
              // count differed between the two depths (407 vs 406) while the
              // ownership result was identical: a reading whose denominator
              // moves with a parameter that cannot affect it.
              px_n[j] = px_n[j] + 1;
              for (lg = 1; lg <= LAGMAX; lg = lg + 1)
                if (px_pend[j][lg]) px_m[j][lg] = px_m[j][lg] + 1;
              // ⭐ AN EVENT THE PIN NEVER CARRIED, PRINTED WHEN IT HAPPENS.
              // This is what turned "8 mismatches out of 440, which looks
              // flaky" into a diagnosis in one run: every unexplained event
              // read `drove=1 uo=0`, and exactly 8 per lane is exactly the
              // number of 1 bits in each queue's payload -- so EVERY 1 was
              // being lost, which pointed straight at the clock-pin write
              // overwriting the data bit. A count alone would not say that.
              if (!px_hit[j] && n_diag < 12) begin
                $display("    DIAG cyc=%0d pin=%0d drove=%0b uo=%0b",
                         cyc, j, px_b[j], uo_out[j]);
                n_diag = n_diag + 1;
              end
            end
          end
        end

        // ⭐ THE BIT, AND THE BYTE IT BUILDS. LSB FIRST, because that is the
        // order `l_tx` shifts right in.
        if (shifting) begin
          n_shift_all = n_shift_all + 1;
          if (sh_lane < 3'd2) begin
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
            // together than LAGMAX would overlap, and the second would be
            // scored against a pin the first had already changed. Those
            // events are SKIPPED rather than mis-scored.
            if (!px_v[j]) begin
              px_v[j] = 1'b1; px_b[j] = sh_bit; px_age[j] = 0;
              px_hit[j] = 1'b0;
              for (lg = 0; lg <= LAGMAX; lg = lg + 1) px_pend[j][lg] = 1'b0;
            end
          end
        end
      end
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
    if (!$value$plusargs("NCYC=%d", ncyc)) ncyc = 6000;
    // ⛔⛔ 1.6x MUST-FIRE MODE. With +BADCLK=1 the image is a program
    // whose SHIFT lane names its DATA pin as its CLOCK pin, which the
    // engine must REFUSE (sticky CONFIG_ERR, lane halted) rather than
    // transmit bytes with every 1 bit overwritten by the clock write.
    // ⭐ THE SAME BENCH, THE OPPOSITE VERDICT, so the guard is priced
    // both ways: a run that PASSES here with the refusal removed
    // (M_SHIFT_CLK_ALIAS) is the defect, and the mode makes that
    // observable instead of requiring a reader to notice a missing flag.
    if (!$value$plusargs("BADCLK=%d", badclk)) badclk = 0;
    // ⭐ THE BADCLK ARM IS THE 1.6x REFUSAL: the lane HALTS and emits no
    // wrong data, so nothing retires. The `clean` arm must still be checked,
    // which is exactly why the declaration is per-arm and not per-bench.
    pg_quiescent_ok = (badclk != 0);
    $readmemh(imgfile, img);
    `PE_REQUIRE_IMG_LOADED(imgfile)

    hf_init;
    // ⛔ DISJOINT PATTERNS, AND NOT BIT-ROTATIONS OF EACH OTHER. No value in
    // one queue is a rotation or complement of a value in the other, so a
    // reconstruction that is off by a bit cannot accidentally match the wrong
    // queue's byte -- which is how a framing error would otherwise present as
    // a queue-ownership failure.
    hf_set(0, 8'hB1, 8'h4E, 8'h7C, 8'h13);
    hf_set(1, 8'h2D, 8'hD2, 8'h68, 8'hA7);
    // ⚠ THE BAD-CLOCK PROGRAM HAS ONE LANE. Feeding queue 1 there would leave
    // it permanently full and `tx_full_sticky` would latch -- the FEEDER's
    // artefact, reported as the engine's.
    if (badclk) hf_mask = 4'b0001;

    for (j = 0; j < 2; j = j + 1) begin
      acc[j] = 8'h00; nbit[j] = 0; ngot[j] = 0; nshift[j] = 0;
      px_v[j] = 1'b0; px_b[j] = 1'b0; px_age[j] = 0; px_n[j] = 0;
      px_hit[j] = 1'b0;
      for (lg = 0; lg <= LAGMAX; lg = lg + 1) begin
        px_m[j][lg] = 0; px_pend[j][lg] = 1'b0;
      end
      for (i = 0; i < MAXB; i = i + 1) got[j][i] = 8'h00;
    end
    cyc = 0; fails = 0; n_shift_all = 0;
    best_lag = 0; best_hits = -1; n_diag = 0;
    primed_seen = 1'b0; cfgerr_seen = 1'b0;
    uo_seen_0 = 8'h00; uo_seen_1 = 8'h00;

    $display("# tx img=%0s bytes=%0d ncyc=%0d SPL=%0d",
             imgfile, img_bytes, ncyc, SPL_CFG);

    repeat (4) @(negedge clk);
    rst_n = 1;
    @(negedge clk);
    load_image;

    // ---- MUST-FIRE 4 FIRST, BEFORE THE FEEDER OWNS THE PINS ------------
    // ⛔ THE RULE BROKEN ON PURPOSE. A byte is pushed with tag 0 on its HIGH
    // nibble and tag 1 on its LOW nibble. The hardware latches at the first
    // push, so the whole byte must land in QUEUE 0 -- queue 1 must be
    // untouched. If the tag were sampled per push the byte would split, and a
    // split byte is unrecoverable: half of it would surface on the wrong wire.
    // ⚠ IT RUNS HERE because `hf_feed` owns ui_in[6], ui_in[5], ui_in[4:1]
    // and ui_in[0] once `hf_en` is high, and two processes driving one reg is
    // a race. Before the feeder starts, this bench still owns them.
    if (!badclk) begin : mf4
      integer c0b, c1b;
      // ⛔⛔ ON QUEUES 2 AND 3, WHICH NO LANE IN THIS PROGRAM CONSUMES, and
      // the first version used 0 and 1. Pushing 0xA5 into queue 0 to test the
      // latch left a REAL BYTE at the head of lane 0's payload, so lane 0
      // emitted `a5` and then the pattern -- every subsequent byte compared
      // one position out and must-fire 2 failed on all eight. ⚠ A test byte
      // injected into the stream under test is stimulus, not instrumentation.
      c0b = dut.tx_cnt[2];
      c1b = dut.tx_cnt[3];
      hf_push_nib(4'hA, 2'd2);        // high nibble, tag 2 -- LATCHED
      hf_push_nib(4'h5, 2'd3);        // low nibble, tag 3 -- must be IGNORED
      repeat (4) @(negedge clk);
      $display("  MUST-FIRE 4: the tag is LATCHED with the high nibble");
      $display("    tx_cnt[2] %0d -> %0d, tx_cnt[3] %0d -> %0d",
               c0b, dut.tx_cnt[2], c1b, dut.tx_cnt[3]);
      if (dut.tx_cnt[2] != c0b + 1)
        fail("the latched byte did not land in queue 2");
      else if (dut.tx_cnt[3] != c1b)
        fail("the low nibble tag reached queue 3 -- the tag is not latched");
      else
        $display("    landed in queue 2, queue 3 untouched  ok");
    end

    // ---- run, continuously fed -----------------------------------------
    // ⭐ SAMPLED AT POSEDGE, ON PURPOSE. The engine's regs use non-blocking
    // assignment, so a posedge read sees the PRE-EDGE state -- the state the
    // FSM's next-state decision is taken from.
    // ⭐ ONE LINE: the feeder is a concurrent process inside the include.
    hf_en = 1'b1;
    observe;

    // ---- the verdict ---------------------------------------------------
    $display();
    if (badclk) begin
      $display("========= tb_tx: 1.6x -- SHIFT with clkpin == pin =========");
      $display("  the program names UO0 as BOTH the data and the clock pin of");
      $display("  a shifting lane. OP_SHIFT writes the data pin and then the");
      $display("  clock pin, so the clock write would overwrite every data");
      $display("  bit with a_lvl. The engine must refuse it.");
      $display("    config_err (sticky)     : %0b %0s", dut.u_eng.config_err,
               dut.u_eng.config_err ? "ok -- REFUSED"
               : "*** FAIL -- the program ran");
      if (!dut.u_eng.config_err) fail("1.6x: the aliased SHIFT was not refused");
      $display("    lane 0 live             : %0b %0s", dut.u_eng.l_live[0],
               dut.u_eng.l_live[0] ? "*** FAIL -- still running" : "ok -- halted");
      if (dut.u_eng.l_live[0]) fail("1.6x: the lane was not halted");
      // ⛔ AND IT MUST NOT HAVE EMITTED DATA. A flag set beside a lane that
      // transmitted anyway is not a refusal. The first byte is 00 by
      // construction (l_tx resets to 0), so the assertion is that NOTHING
      // beyond that ever came out.
      $display("    bytes emitted by lane 0 : %0d %0s", ngot[0],
               (ngot[0] <= 1) ? "ok -- nothing beyond the reset byte"
               : "*** FAIL -- it transmitted");
      if (ngot[0] > 1) fail("1.6x: the refused lane still emitted bytes");
      $display();
      $display("================ VERDICT ================");
      if (fails == 0)
        $display("  tb_tx: PASS (1.6x refusal)");
      else
        $display("  tb_tx: *** FAILED %0d check(s)", fails);
      $finish;
    end
    $display("================ tb_tx: TX queue ownership ================");
    $display("  PRECONDITIONS");
    $display("    image bytes loaded      : %0d", img_bytes);
    $display("    primed observed         : %0b %0s", primed_seen,
             primed_seen ? "ok" : "*** FAIL");
    if (!primed_seen) fail("the engine never primed");
    $display("    config_err observed     : %0b %0s", cfgerr_seen,
             cfgerr_seen ? "*** FAIL" : "ok");
    if (cfgerr_seen) fail("config_err -- the program was refused at load");
    $display("    pin 0 saw both levels   : %0b %0s", (uo_seen_0 == 8'h03),
             (uo_seen_0 == 8'h03) ? "ok" : "*** FAIL");
    $display("    pin 1 saw both levels   : %0b %0s", (uo_seen_1 == 8'h03),
             (uo_seen_1 == 8'h03) ? "ok" : "*** FAIL");
    if (uo_seen_0 != 8'h03 || uo_seen_1 != 8'h03)
      fail("a TX pin never changed -- the output path is dead");
    $display("    shifts lane 0 / lane 1  : %0d / %0d", nshift[0], nshift[1]);
    $display("    bytes seen lane0/lane1  : %0d / %0d", ngot[0], ngot[1]);
    hf_check(n_shift_all);
    fails = fails + hf_bad;

    $display("  MUST-FIRE 1: the first byte out of each lane is its queue's FIRST byte");
    // ⭐ THE ALIGNMENT PROOF: the first byte must be the first one the host
    // pushed on the lane's queue. If the framing were off by a bit this
    // breaks first, so every later comparison fails for a queue reason only.
    // ⛔ It used to assert 00 -- the reset register went out first on every
    // TX lane (silicon fix #8, WF2); a 00 here is now that defect.
    for (j = 0; j < 2; j = j + 1) begin
      if (ngot[j] < 1) begin
        $display("    lane %0d: *** FAIL -- no complete byte", j);
        fails = fails + 1;
      end else begin
        $display("    lane %0d: %02h %0s", j, got[j][0],
                 (got[j][0] == hf_pat[j][0]) ? "ok"
                 : (got[j][0] == 8'h00) ? "*** FAIL (the reset register -- fix #8 undone?)"
                 : "*** FAIL (not byte-aligned)");
        if (got[j][0] != hf_pat[j][0]) fails = fails + 1;
      end
    end

    $display("  MUST-FIRE 2: each lane emits ONLY its own queue's pattern");
    $display("    queue 0 pattern: %02h %02h %02h %02h",
             hf_pat[0][0], hf_pat[0][1], hf_pat[0][2], hf_pat[0][3]);
    $display("    queue 1 pattern: %02h %02h %02h %02h",
             hf_pat[1][0], hf_pat[1][1], hf_pat[1][2], hf_pat[1][3]);
    for (j = 0; j < 2; j = j + 1) begin
      if (ngot[j] < CHECKB + 1) begin
        $display("    lane %0d: *** FAIL -- only %0d bytes, need %0d",
                 j, ngot[j], CHECKB + 1);
        fails = fails + 1;
      end else begin
        $write("    lane %0d:", j);
        for (i = 1; i <= CHECKB; i = i + 1) $write(" %02h", got[j][i]);
        $display("");
        $write("    want  :");
        for (i = 1; i <= CHECKB; i = i + 1)
          $write(" %02h", hf_pat[j][i % hf_len[j]]);
        $display("");
        for (i = 1; i <= CHECKB; i = i + 1) begin
          if (got[j][i] != hf_pat[j][i % hf_len[j]]) begin
            $display("    lane %0d byte %0d: got %02h want %02h *** FAIL",
                     j, i, got[j][i], hf_pat[j][i % hf_len[j]]);
            fails = fails + 1;
          end
        end
      end
    end
    // ⛔⛔ AND THE CROSS-LANE DIAGNOSIS, EXPLICITLY. The comparison above
    // already fails if a lane emits the wrong byte -- but it fails with "got
    // 4e want 2d", which reads like a corrupt byte. Naming the OTHER QUEUE as
    // the source turns a value mismatch into a diagnosis, and that is the
    // finding this bench exists for.
    // ⚠ SCANNED OVER EVERY EMITTED BYTE AGAINST EVERY BYTE OF THE OTHER
    // PATTERN, because the first version compared only byte 0 against byte 0
    // and did NOT fire: under `M_TX_IGNORE_TAG` lane 1 emits queue 0's SECOND
    // byte, since lane 0 took the first. The mutant then died of a value
    // mismatch -- not its stated reason, which this project does not accept.
    for (j = 0; j < 2; j = j + 1) begin
      for (i = 1; i <= CHECKB; i = i + 1) begin
        if (ngot[j] > i) begin
          for (lg = 0; lg < hf_len[1 - j]; lg = lg + 1) begin
            if (got[j][i] == hf_pat[1 - j][lg]) begin
              if (j == 0)
                fail("lane 0 emitted a QUEUE 1 byte -- the queue tag was ignored");
              else
                fail("lane 1 emitted a QUEUE 0 byte -- the queue tag was ignored");
            end
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
      $display("        explained at lag %0d, so the path is deterministic",
               best_lag);
      $display("        and the DERIVATION was wrong -- correct PIN_LAG, do");
      $display("        not weaken the check.");
      fails = fails + 1;
    end else begin
      $display("    ⇒ every scored event matches at the derived lag  ok");
    end

    $display();
    $display("================ VERDICT ================");
    if (fails == 0)
      $display("  tb_tx: PASS (4 of 4 must-fires)");
    else
      $display("  tb_tx: *** FAILED %0d check(s)", fails);
    $display("  ⚠ SCOPE: ownership and ORDER, on a two-lane program at");
    $display("    d = 12/13, continuously fed. Not protocol framing, not");
    $display("    channel timing, and not the tag's 2-bit width limit.");
    $finish;
  end

endmodule

`default_nettype wire
