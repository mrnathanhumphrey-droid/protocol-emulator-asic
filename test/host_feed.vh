/* host_feed.vh -- THE ONE HOST-CHANNEL DRIVER, shared by every bench.
 *
 * ⛔⛔ WHY THIS FILE EXISTS. T5.1 found that NO BENCH HAD EVER DRIVEN THE HOST
 * CHANNEL: `pe_isa.host_pushes` had been in the ISA since F1 was built and
 * nothing in `test/` called it, so every `OP_SHIFT` the suite ever executed
 * found `host_valid = 0` and took the UNDERRUN branch. That reaches backwards
 * into every result a shifting program produced -- the census `C` measurement,
 * the trace corpus, the cross-seed sweep -- all of which measured the STARVED
 * regime without saying so.
 * ⇒ Wilson's ruling 0: re-run them fed. This is the driver they share.
 *
 * ⛔ ONE COPY, AND THE REASON IS THIS PROJECT'S WORST RECURRING DEFECT. Four
 * private copies of the slot index were found one at a time across two
 * benches, and one of them produced a whole published column that had to be
 * retracted. A push sequence copied into three benches is the same shape: the
 * tag is latched with the HIGH nibble, so a copy that got the nibble order
 * wrong would split bytes across queues in one bench and not another, and the
 * two would disagree for a reason no gate names.
 * ⚠ THE PUSH SHAPE IS ALSO HALF OF `pe_isa.digest()`, so the Python side and
 * this side are pinned to the same contract from opposite ends.
 *
 * HOW THE CHANNEL WORKS (src/project.v):
 *   ui_in[6]        PIN_WR -- a RISING edge is one push (3-stage sync, so it
 *                   must be held)
 *   ui_in[4:1]      the nibble
 *   {ui_in[5], ui_in[0]}  the 2-bit QUEUE TAG, latched with the HIGH nibble
 *   two pushes per byte, HIGH NIBBLE FIRST (a ruling: it matches the MSB-first
 *   bit order SPI and I2C shift with)
 *
 * ⛔ ui_in[5] IS `PIN_PTR` IN LOAD MODE. Pushing while `ui_in[7]` is still
 * high would be a pointer reset, not a push, so `hf_en` must not be raised
 * until the image is loaded and PROG is low. `hf_feed` waits on it.
 *
 * USAGE:
 *   `include "test/host_feed.vh"          // after the `dut` instance
 *   ...
 *   hf_init;                              // zero the counters
 *   hf_mask = 4'b0001;  hf_set(0, ...);   // which queues, what payload
 *   ... load the image, drop PROG ...
 *   hf_en = 1'b1;                         // the feeder is a concurrent
 *                                         // process in this file -- no fork
 *
 * ⚠ IT OWNS `ui_in` BITS 6, 5, 4:1 AND 0 WHILE `hf_en` IS HIGH. Two processes
 * writing one reg is a race, so a bench must not touch those bits after
 * raising `hf_en`.
 */

  // ---- payload: a repeating pattern per queue ---------------------------
  // ⭐ REPEATING, SO "EXACTLY THE PUSHED BYTES" IS CHECKABLE. A one-shot
  // payload runs out and the lane underruns, which is the regime being
  // replaced; a cycling pattern means the emitted stream must equal the
  // pattern cyclically, for as long as the run lasts.
  localparam integer HF_PAT = 4;
  reg  [7:0] hf_pat [0:3][0:HF_PAT-1];
  integer    hf_idx [0:3];
  // ⛔⛔ DECLARATION INITIALISERS, NOT JUST `hf_init`, AND THE DIFFERENCE IS A
  // RACE. `hf_init` is a TASK called from each bench's main `initial`, while
  // the feeder is its OWN `initial` block. Both start at time 0 and their
  // order is not guaranteed, so with `hf_en` holding an arbitrary power-on
  // value the feeder can push BEFORE `hf_init` clears it. Declaration
  // initialisers are applied before any process runs, which is the only
  // ordering that holds. ⚠ `hf_q` was never covered by `hf_init` at all.
  reg  [3:0] hf_mask = 4'b0000;
  reg        hf_en = 1'b0;
  integer    hf_pushes = 0, hf_bytes = 0, hf_q = 0;

  task hf_init;
    integer a, b;
    begin
      hf_en = 1'b0; hf_mask = 4'b0000;
      hf_pushes = 0; hf_bytes = 0;
      for (a = 0; a < 4; a = a + 1) begin
        hf_idx[a] = 0;
        for (b = 0; b < HF_PAT; b = b + 1) hf_pat[a][b] = 8'h00;
      end
    end
  endtask

  // ⭐ FOUR DISTINCT BYTES PER QUEUE, AND DISJOINT BETWEEN QUEUES, chosen so a
  // byte that surfaces on the wrong lane is identifiable rather than merely
  // wrong. `hf_set` takes them explicitly so each bench declares its own.
  task hf_set;
    input integer q;
    input [7:0] b0, b1, b2, b3;
    begin
      hf_pat[q][0] = b0; hf_pat[q][1] = b1;
      hf_pat[q][2] = b2; hf_pat[q][3] = b3;
      hf_idx[q] = 0;
      hf_mask[q] = 1'b1;
    end
  endtask

  // ---- one nibble -------------------------------------------------------
  // ⛔ THE HOLD TIMES ARE THE LOADER'S, NOT GUESSED. `wr_rise` is taken from a
  // 3-stage synchroniser (`wr_sync[2:1] == 2'b01`), so the level has to be
  // stable for several cycles either side or the edge is missed -- and a
  // MISSED push is invisible: the byte simply never arrives and the lane
  // underruns, which looks exactly like the starved regime this file exists
  // to leave.
  task hf_push_nib;
    input [3:0] nib;
    input [1:0] tag;
    begin
      ui_in[4:1] = nib;
      ui_in[5]   = tag[1];
      ui_in[0]   = tag[0];
      @(negedge clk); @(negedge clk);
      ui_in[6]   = 1'b1;
      @(negedge clk); @(negedge clk); @(negedge clk);
      ui_in[6]   = 1'b0;
      @(negedge clk);
      hf_pushes = hf_pushes + 1;
    end
  endtask

  task hf_push_byte;
    input [7:0] b;
    input [1:0] tag;
    begin
      hf_push_nib(b[7:4], tag);     // HIGH NIBBLE FIRST -- a ruling
      hf_push_nib(b[3:0], tag);
      hf_bytes = hf_bytes + 1;
    end
  endtask

  // ---- the feeder -------------------------------------------------------
  // ⛔⛔ TOPS UP ONLY QUEUES WITH SPACE, and that is not an optimisation. A
  // push onto a full queue is DROPPED and sets `tx_full_sticky` -- the host
  // has no back-pressure pin, so the only honest hardware answer is a sticky
  // flag. A feeder that pushed blindly would drop bytes, the emitted stream
  // would skip entries, and "the lane did not emit what was pushed" would be
  // the FEEDER's fault reported as the engine's.
  // ⚠ IT READS `dut.tx_cnt`, which is bench-side introspection of a host-side
  // counter, not of the engine. The claim under test is about the ENGINE
  // choosing a queue; the depth is the host's own bookkeeping.
  // ⭐ ITS OWN `initial` BLOCK, NOT A TASK THE BENCH MUST `fork`. The first
  // version was a `forever` task, which meant every bench had to wrap its own
  // run loop in `fork ... join_any` -- and `tb_smoke`'s run loop is 300 lines
  // inline, so adopting it would have meant restructuring the bench around the
  // instrument. A concurrent process in the include costs the bench one line
  // (`hf_en = 1'b1;`) and cannot change the shape of what it measures.
  // ⛔ IT WAITS ON `hf_en` AND NOTHING ELSE. `ui_in[5]` is PIN_PTR in load
  // mode, so a push issued before PROG drops is a pointer reset; the bench
  // raises `hf_en` only after the image is in.
  initial begin
    wait (hf_en);
    forever begin
      for (hf_q = 0; hf_q < 4; hf_q = hf_q + 1) begin
        if (hf_mask[hf_q] && dut.tx_cnt[hf_q] != 2'd2) begin
          hf_push_byte(hf_pat[hf_q][hf_idx[hf_q]], hf_q[1:0]);
          hf_idx[hf_q] = (hf_idx[hf_q] + 1) % HF_PAT;
        end
      end
      @(negedge clk);
    end
  end

  // ---- THE STANDING PRECONDITION (Wilson's ruling 0) --------------------
  // ⛔⛔ ANY BENCH THAT RUNS A `SHIFT` MUST ASSERT THIS, in the same class as
  // "the image loaded" and "the window is long enough": at least one host push
  // landed, and no lane's underrun flag is set. Without it a run is STARVED
  // and does not count -- and the whole suite was starved for the lifetime of
  // the host channel without a single check noticing.
  // ⭐ `hf_bad` is the count to add into a bench's own failure tally, so the
  // precondition cannot be printed and then ignored.
  integer hf_bad, hf_i;
  task hf_check;
    input integer n_shifts;
    begin
      hf_bad = 0;
      $display("  HOST-CHANNEL PRECONDITION (ruling 0)");
      $display("    SHIFT dispatches observed : %0d", n_shifts);
      $display("    host pushes issued        : %0d (%0d bytes) %0s",
               hf_pushes, hf_bytes,
               (n_shifts == 0 || hf_bytes > 0) ? "ok"
               : "*** STARVED -- a SHIFT ran with no byte ever pushed");
      if (n_shifts > 0 && hf_bytes == 0) hf_bad = hf_bad + 1;
      $display("    engine host pops          : %0d %0s",
               hf_pops,
               (n_shifts == 0 || hf_pops > 0) ? "ok"
               : "*** no byte was ever CONSUMED -- fed, but not reaching the lane");
      if (n_shifts > 0 && hf_pops == 0) hf_bad = hf_bad + 1;
      $write("    lane underrun flags       :");
      for (hf_i = 0; hf_i < 5; hf_i = hf_i + 1)
        $write(" %0b", dut.u_eng.lane_underrun[hf_i]);
      $display("  %0s", (dut.u_eng.lane_underrun == 5'b00000) ? "ok"
               : "*** UNDERRUN SET -- this run is STARVED and does not count");
      if (dut.u_eng.lane_underrun != 5'b00000) hf_bad = hf_bad + 1;
      $display("    tx_full_sticky            : %0b %0s",
               dut.tx_full_sticky,
               dut.tx_full_sticky
               ? "*** the FEEDER overran a queue -- dropped bytes are its bug"
               : "ok");
      if (dut.tx_full_sticky) hf_bad = hf_bad + 1;
    end
  endtask

  // ⭐ POPS ARE COUNTED HERE so every bench gets the same number from the same
  // place. `host_pop` is a one-cycle pulse.
  integer hf_pops;
  // ⭐ THE SHARED INTERLOCK (see test/progress.vh): `hf_en` IS this
  // bench's "I am driving the host channel" signal, so it feeds the guard
  // directly. The feeder already waits for PROG to drop; this is what
  // makes that wait CHECKED rather than merely documented.
  always @(*) pg_pushing = hf_en;

  always @(posedge clk) begin
    if (!rst_n) hf_pops <= 0;
    else if (dut.u_eng.host_pop) hf_pops <= hf_pops + 1;
  end
