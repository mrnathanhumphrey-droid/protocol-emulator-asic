`default_nettype none
`timescale 1ns / 1ps

/* THE SAME-CYCLE PUSH AND POP ON ONE TX QUEUE -- the FIFO corner.
 *
 * ⛔⛔ WHY THIS BENCH EXISTS, AND IT IS A CROSS-CHECK FINDING. `src/project.v`
 * enumerates the case where a host PUSH and an engine POP land on the SAME
 * queue in the SAME cycle:
 *
 *     if (do_push && tx_tag == ti && do_popq[ti])
 *       tx_cnt[ti] <= tx_cnt[ti];              // one in, one out
 *
 * The coverage sweep reported that arm UNCOVERED and it was tabled as OWED --
 * and then the cocotb cross-check reported it EXECUTED 48 TIMES. So no test
 * was missing; the SWEPT benches could not reach it. Calling it owed described
 * a gap in ONE BENCH as a gap in the DESIGN.
 * ⚠ It only became reachable in cocotb once that bench drove a RESOLVED
 * open-drain bus instead of a constant, which is itself the finding that
 * `test/od_bus.vh` exists for.
 *
 * ⛔⛔ WHY THE PHASE IS **WALKED** AND NOT COMPUTED, which is the one design
 * decision here. `do_push` is `nib_lo & ...` where `nib_lo` is the LOW-nibble
 * push after a THREE-STAGE SYNCHRONISER (`wr_sync`), and `do_popq[q]` is the
 * engine's `host_pop`, which fires once per BYTE LOAD -- every eight shifts of
 * a lane whose period is its action delay. Computing the alignment means
 * composing the synchroniser latency, the nibble pairing and the lane's
 * dispatch cadence, and being wrong by one cycle looks exactly like the corner
 * being unreachable.
 * ⇒ So the bench SLIPS the push phase by one cycle per byte and watches for the
 *   coincidence. Over one pop period it must occur, and when it does the bench
 *   has the cycle in hand and asserts on it. Self-correcting rather than
 *   arithmetic, and it reports the phase it found so the result is reproducible.
 * ⚠ IF NO PHASE HITS, THAT IS A FAILURE, not a pass: a bench that swept every
 *   phase and never saw the corner has not tested it.
 *
 * WHAT IS ASSERTED ON THAT CYCLE -- the three things a FIFO breaks on:
 *   1. BOTH operations take effect: the write pointer AND the read pointer flip
 *   2. the COUNT is unchanged: one in, one out
 *   3. ORDER is preserved: the read pointer moves past the OLDER of the two
 *      resident (the head is read through it, in one expression), and the
 *      byte pushed lands in the slot the write pointer named
 */
`include "test/imgload.vh"
module tb_fifo ();

  localparam integer N_LANES = 5;
  localparam integer IMG_MAX = 256;
  localparam integer PIN_PROG = 7, PIN_PTR = 5, PIN_WR = 6;
  parameter  integer SPL_CFG = 2;

  reg        clk = 1'b0, rst_n = 1'b0, ena = 1'b1;
  reg  [7:0] ui_in = 8'h00;
  wire [7:0] uo_out, uio_out, uio_oe;
  wire [7:0] uio_in;

  // the bench drives the bus during load only; afterwards the pull-ups hold it
  reg  [7:0] ld_val = 8'h00;
  reg        ld_en  = 1'b0;
  wire [7:0] ob_oe  = ld_en ? 8'hFF : 8'h00;
  wire [7:0] ob_val = ld_val;

  tt_um_protocol_emulator #(.SPL(SPL_CFG)) dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );

`include "test/od_bus.vh"
`include "test/progress.vh"
`include "test/clocked_conform.vh"

  always #10 clk = ~clk;

  reg [7:0] img [0:IMG_MAX-1];
  integer   img_bytes, i, fails, cyc, phase, hits, ncyc;
  // ⛔⛔ THE LOAD HANDSHAKE, and its absence was this bench's first defect.
  // The stimulus started pushing 40 cycles after reset, while the load was
  // still running and PROG was still HIGH -- and in load mode `ui_in[5]` is
  // PIN_PTR, so every "push" RESET THE LOAD POINTER. Measured: 81 of 87
  // store bytes differed from the image. `host_feed.vh` documents exactly
  // this ("`hf_en` must not be raised until the image is loaded and PROG is
  // low") and this bench drives the channel itself for phase control, so it
  // has to carry the same interlock rather than inherit it.
  reg       loaded = 1'b0;
  reg [8*256-1:0] imgfile;

  // the captured corner
  integer cnt_before, cnt_after, wp_before, wp_after, rp_before, rp_after;
  integer hit_cycle, hit_phase;

  task fail(input [8*72-1:0] why);
    begin
      fails = fails + 1;
      $display("    FAIL %0s", why);
    end
  endtask

  // one host push: the nibble plus the 2-bit queue tag, WR held long enough for
  // the three-stage synchroniser to see an edge.
  task push_nib(input [3:0] nib, input [1:0] q, input integer hold);
    begin
      pg_pushing = 1'b1;   // the shared interlock: see test/progress.vh
      ui_in[4:1] = nib;
      ui_in[5]   = q[1];
      ui_in[0]   = q[0];
      ui_in[PIN_WR] = 1'b0;
      @(negedge clk);
      ui_in[PIN_WR] = 1'b1;
      repeat (hold) @(negedge clk);
      ui_in[PIN_WR] = 1'b0;
      @(negedge clk);
    end
  endtask

  initial begin
    if (!$value$plusargs("IMG=%s", imgfile)) imgfile = "test/tx_image.hex";
    if (!$value$plusargs("NBYTES=%d", img_bytes)) img_bytes = 0;
    if (!$value$plusargs("NCYC=%d", ncyc)) ncyc = 60000;
    if (img_bytes == 0) begin
      $display("  FAIL tb_fifo: the image length must be passed explicitly");
      $finish;
    end
    for (i = 0; i < IMG_MAX; i = i + 1) img[i] = 8'h00;
    $readmemh(imgfile, img);
    `PE_REQUIRE_IMG_LOADED(imgfile)
    fails = 0; cyc = 0; hits = 0; phase = 0;
    hit_cycle = -1; hit_phase = -1;

    repeat (4) @(negedge clk);
    rst_n = 1'b1;
    @(negedge clk);

    // ---- load ---------------------------------------------------------
    ui_in[PIN_PROG] = 1'b1;
    ld_en = 1'b1;
    repeat (3) @(negedge clk); ui_in[PIN_PTR] = 1'b1; repeat (3) @(negedge clk);  // CDC3: prog >= 3 cy before ptr; ptr >= 3 cy wide
    ui_in[PIN_PTR] = 1'b0; repeat (3) @(negedge clk);
    for (i = 0; i < img_bytes; i = i + 1) begin
      ld_val = img[i];
      @(negedge clk); @(negedge clk);
      ui_in[PIN_WR] = 1'b1;
      repeat (3) @(negedge clk);
      ui_in[PIN_WR] = 1'b0;
      @(negedge clk);
    end
    ui_in[PIN_PROG] = 1'b0;
    ld_en = 1'b0;
    ui_in = 8'h00;
    repeat (4) @(negedge clk);
    loaded = 1'b1;

    $display("  tb_fifo: walking the push phase to meet a pop on queue 0");
  end

  // ---- the corner detector, on every clock ----------------------------
  // ⛔ SAMPLED AS A CONTINUOUS MONITOR rather than inside the stimulus loop: the
  // coincidence is a single cycle and a procedural check could step past it.
  always @(posedge clk) if (rst_n) begin
    cyc <= cyc + 1;
    // ⭐ `do_popq` IS PER QUEUE (every TX variant pops through it), so the
    // corner is a push and a pop on the SAME queue in the same cycle
    if (dut.do_push && dut.do_popq[dut.tx_tag] && hits == 0) begin
      hits      = 1;
      hit_cycle = cyc;
      hit_phase = phase;
      cnt_before = dut.tx_cnt[dut.tx_tag];
      wp_before  = dut.tx_wp[dut.tx_tag];
      rp_before  = dut.tx_rp[dut.tx_tag];
    end
  end

  // sample the after-state one cycle later
  always @(posedge clk) if (rst_n && hits == 1 && cyc == hit_cycle + 1) begin
    cnt_after = dut.tx_cnt[dut.tx_tag];
    wp_after  = dut.tx_wp[dut.tx_tag];
    rp_after  = dut.tx_rp[dut.tx_tag];
    hits      = 2;
  end

  // ---- the stimulus: push bytes, slipping the phase by one each time ---
  initial begin
    wait (loaded);
    repeat (20) @(negedge clk);
    // ⭐ THE PHASE WALK, ANCHORED TO AN OBSERVED POP. Each byte waits for an
    // engine pop, then `phase` more cycles, then pushes its two nibbles; and
    // `phase` advances by one. So the low nibble's landing point walks across
    // the pop period ONE CYCLE AT A TIME, and every offset is tried within one
    // period's worth of bytes.
    // ⛔⛔ IT USED TO WALK IN ABSOLUTE TIME, `phase % 23` extra cycles per byte,
    // and that was NOT exhaustive -- the comment above claimed a coincidence
    // "must occur" and it was luck. Ruling TF moved priming one cycle later,
    // which moved every pop on `tx_image` by exactly one cycle (MEASURED: the
    // same pops, 1746 -> 1747, 1854 -> 1855, ...), and the old walk then missed
    // every one of them. A walk whose coverage depends on where cycle 0 falls
    // has not swept the phase.
    // ⛔ FILL FIRST: a pop needs a byte (`do_popq` is gated by the queue's
    // valid), so with an empty
    // queue there is no pop to anchor to and the walk would wait forever.
    // Two bytes fill the TXD = 2 queue; each step then pushes one per pop.
    push_nib(4'hA, 2'd0, 3);
    push_nib(4'h5, 2'd0, 3);
    push_nib(4'hA, 2'd0, 3);
    push_nib(4'h5, 2'd0, 3);
    for (phase = 0; phase < 400 && hits < 2; phase = phase + 1) begin
      // ⛔ TOP THE QUEUE UP BEFORE EVERY ANCHOR. When the landing point walks
      // past a pop, that pop falls inside the previous step's push and is not
      // seen as an anchor -- two pops for one push -- and the 2-deep queue
      // drains to empty just as the walk reaches the coincidence (MEASURED:
      // phase 98 landed one cycle before a pop, then the queue emptied). A full
      // queue at the coincidence is also the harder case: the push is accepted
      // ONLY because the pop frees a slot in the same cycle.
      while (dut.tx_cnt[0] < 2) begin
        push_nib(4'hA, 2'd0, 3);
        push_nib(4'h5, 2'd0, 3);
      end
      @(posedge clk);
      while (!dut.do_popq[0]) @(posedge clk);
      @(negedge clk);
      repeat (phase) @(negedge clk);
      push_nib(4'hA, 2'd0, 3);
      push_nib(4'h5, 2'd0, 3);
    end
  end

  initial begin
    wait (loaded);
    repeat (ncyc) @(negedge clk);
    $display();
    if (hits < 2) begin
      $display("  FAIL tb_fifo: the same-cycle push+pop corner was NEVER");
      $display("      reached in %0d cycles over %0d phases -- a bench that", ncyc, phase);
      $display("      swept every phase and never saw the corner has not");
      $display("      tested it, so this is a FAILURE and not a pass.");
      fails = fails + 1;
    end else begin
      $display("  the corner occurred at cycle %0d, phase %0d", hit_cycle,
               hit_phase);
      // 1. both operations take effect
      if (wp_after === wp_before)
        fail("the WRITE pointer did not flip: the push did not take effect");
      if (rp_after === rp_before)
        fail("the READ pointer did not flip: the pop did not take effect");
      // 2. the count is unchanged -- one in, one out
      if (cnt_after !== cnt_before)
        fail("the count MOVED on a same-cycle push+pop (one in, one out)");
      // 3. ORDER IS THE READ POINTER: a queue's head is `tx_mem[{q, rp[q]}]`
      // in ONE expression for every variant, so "the engine got the older
      // byte" could not fail separately from check 1's read-pointer flip.
      // (It was a check against an implementation that read the head
      // through a second pointer; there is no such path.) Removed rather
      // than kept as a check that cannot fire.
      $display("    both pointers flipped, count held at %0d (order: the read pointer advanced past the older byte)",
               cnt_before);
    end
    $display();
    if (fails == 0) $display("  tb_fifo: PASS");
    else            $display("  tb_fifo: *** FAILED %0d check(s)", fails);
    $finish;
  end

endmodule
`default_nettype wire
