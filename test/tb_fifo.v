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

  // ⭐⭐ THE ORDER CLAIM, MADE FALSIFIABLE (Wilson). This bench pushed `A5`
  // every time, so no value check could see an ordering defect -- the old
  // check 3 was vacuous for that reason, and a planted "head read from the
  // newer slot" passed. Now the bench pushes DISTINCT ALTERNATING bytes
  // (A5, 3C, ...), records the BENCH'S OWN byte at every ACCEPTED push on
  // queue 0 (`do_push` says only whether it was taken, never what), and
  // rebuilds lane 0's emitted bytes from the bit the engine drives
  // (`tx_bit`, LSB first, as tb_tx). Underrun bytes are 00, which neither
  // pushed byte is, so dropping them leaves exactly the bytes that were fed:
  // they must be the pushed sequence, in order.
  localparam integer OMAX = 1024;
  reg  [7:0] cur_byte = 8'h00, b_alt = 8'h00;
  reg  [7:0] pushed [0:OMAX-1];
  reg  [7:0] emit   [0:OMAX-1];
  integer    npushed = 0, nemit = 0, nunder = 0, o_nbit = 0;
  reg  [7:0] o_acc = 8'h00;
  integer    o_k, o_bad, o_first;

  // ⭐⭐ THE CLOSED-LOOP WALK'S MEASUREMENTS (Wilson: deterministic, and the
  // corner COUNTED). Kept in THIS block with the order capture so nothing
  // reads another block's same-edge write (ruling RA3); the stimulus reads
  // them only on negedges. `m_land` is where the low nibble LANDED (`nib_lo`
  // on queue 0, taken or dropped); `m_pop` logs every queue-0 pop; `m_corner`
  // counts EVERY same-cycle push+pop on queue 0, not just the first.
  localparam integer PMAX = 4096;
  integer    m_cyc = 0, m_land = -1, m_npop = 0, m_corner = 0;
  integer    m_pop [0:PMAX-1];
  // the walk: targets OFF_LO..OFF_HI (0 = the corner), ATT_MAX tries each
  localparam integer OFF_LO = -3, OFF_HI = 3, ATT_MAX = 8;
  integer    w_ph, w_t, w_a, w_i, w_r, w_got = 0, w_miss = 0, w_done = 0;
  integer    w_hist [0:(OFF_HI - OFF_LO + 16)];
  initial for (w_i = 0; w_i <= OFF_HI - OFF_LO + 16; w_i = w_i + 1) w_hist[w_i] = 0;

  always @(posedge clk) if (rst_n) begin
    m_cyc = m_cyc + 1;
    if (dut.nib_lo === 1'b1 && dut.tx_tag == 2'd0) m_land = m_cyc;
    if (dut.do_popq[0] === 1'b1 && m_npop < PMAX) begin
      m_pop[m_npop] = m_cyc;
      m_npop = m_npop + 1;
    end
    if (dut.do_push === 1'b1 && dut.tx_tag == 2'd0 && dut.do_popq[0] === 1'b1)
      m_corner = m_corner + 1;
    if (dut.do_push === 1'b1 && dut.tx_tag == 2'd0 && npushed < OMAX) begin
      pushed[npushed] = cur_byte;
      npushed = npushed + 1;
    end
    if (dut.u_eng.st == 1 && dut.u_eng.a_op == 3'd1 && dut.u_eng.cur == 0) begin
      o_acc  = {dut.u_eng.tx_bit, o_acc[7:1]};
      o_nbit = o_nbit + 1;
      if (o_nbit == 8) begin
        if (o_acc == 8'h00) nunder = nunder + 1;
        else if (nemit < OMAX) begin emit[nemit] = o_acc; nemit = nemit + 1; end
        o_nbit = 0;
      end
    end
  end

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

  // one whole byte on queue 0, ALTERNATING A5 / 3C (distinct, both non-zero)
  task push_byte;
    begin
      b_alt    = (b_alt == 8'hA5) ? 8'h3C : 8'hA5;
      cur_byte = b_alt;
      push_nib(b_alt[7:4], 2'd0, 3);
      push_nib(b_alt[3:0], 2'd0, 3);
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
    push_byte;
    push_byte;
    // ⛔⛔ CLOSED LOOP, NOT OPEN (Wilson). The open walk advanced `phase` by one
    // per byte and hoped the landing crossed the next pop; but the pop PERIOD
    // jitters by +-1 cycle (EDF arbitration: 107/108/109 on tx_image), so the
    // realised offset jumped -1 -> +1 and skipped 0 -- MEASURED under (b4),
    // 400 phases, never the corner. Now each attempt MEASURES its realised
    // offset r = (low-nibble landing) - (the first pop after the anchor) and
    // steers `phase` by (target - r). Targets sweep OFF_LO..OFF_HI around 0,
    // each until realised or ATT_MAX attempts; a bounded jitter cannot skip
    // a target the loop corrects toward. The realised histogram is printed.
    w_ph = 90;                                   // a first guess; r corrects it
    for (w_t = OFF_LO; w_t <= OFF_HI; w_t = w_t + 1) begin
      for (w_a = 0; w_a < ATT_MAX && !w_got; w_a = w_a + 1) begin
        // ⛔ TOP THE QUEUE UP BEFORE EVERY ANCHOR. A full queue at the
        // coincidence is also the harder case: the push is accepted ONLY
        // because the pop frees a slot in the same cycle.
        while (dut.tx_cnt[0] < 2) push_byte;
        @(negedge clk);
        w_i = m_npop;                            // the anchor = the next pop
        while (m_npop <= w_i) @(negedge clk);
        @(negedge clk);
        phase = w_ph;
        repeat (w_ph) @(negedge clk);
        push_byte;
        while (m_npop <= w_i + 1) @(negedge clk);  // the first pop after it
        w_r = m_land - m_pop[w_i + 1];
        if (w_r >= OFF_LO - 8 && w_r <= OFF_HI + 8)
          w_hist[w_r - OFF_LO + 8] = w_hist[w_r - OFF_LO + 8] + 1;
        if (w_r == w_t) w_got = 1;
        else begin
          w_ph = w_ph + (w_t - w_r);
          if (w_ph < 0) w_ph = 0;
        end
      end
      if (!w_got) w_miss = w_miss + 1;
      w_got = 0;
    end
    w_done = 1;
  end

  initial begin
    wait (loaded);
    repeat (ncyc) @(negedge clk);
    $display();
    $write("  walk: realised offset histogram (push landing - next pop):");
    for (w_i = 0; w_i <= OFF_HI - OFF_LO + 16; w_i = w_i + 1)
      if (w_hist[w_i] != 0) $write(" %0d:%0d", w_i + OFF_LO - 8, w_hist[w_i]);
    $display("");
    $display("  same-cycle push+pop on queue 0 (the corner): %0d time(s)", m_corner);
    if (!w_done)
      fail("the closed-loop walk did not finish its targets within the run");
    else if (w_miss != 0) begin
      $display("    %0d target offset(s) in [%0d, %0d] never realised in %0d tries",
               w_miss, OFF_LO, OFF_HI, ATT_MAX);
      fail("the walk did not realise every target offset -- not by construction");
    end
    if (m_corner == 0 || hits < 2) begin
      $display("  FAIL tb_fifo: the same-cycle push+pop corner was NEVER");
      $display("      reached in %0d cycles -- a corner that was never", ncyc);
      $display("      exercised is not a pass (Wilson), so this is a FAILURE.");
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
    // 3. ORDER ON THE WIRE (Wilson): the fed bytes lane 0 emitted are the
    // pushed bytes, in push order. A minimum count, so it cannot pass on
    // nothing: a check over zero bytes is the vacuous check it replaces.
    o_bad = 0; o_first = -1;
    for (o_k = 0; o_k < nemit; o_k = o_k + 1)
      if (o_k >= npushed || emit[o_k] !== pushed[o_k]) begin
        o_bad = o_bad + 1;
        if (o_first < 0) o_first = o_k;
      end
    $display("    order: %0d fed byte(s) emitted, %0d pushed, %0d underrun byte(s)",
             nemit, npushed, nunder);
    if (nemit < 20)
      fail("ORDER: fewer than 20 fed bytes emitted -- the order check is vacuous");
    else if (o_bad != 0) begin
      $display("    ORDER: emitted byte %0d is %02h, pushed byte %0d was %02h",
               o_first, emit[o_first], o_first, pushed[o_first]);
      fail("ORDER: lane 0 emitted the pushed bytes out of order");
    end else
      $display("    ok -- every fed byte left in push order (A5/3C alternating)");
    $display();
    if (fails == 0) $display("  tb_fifo: PASS");
    else            $display("  tb_fifo: *** FAILED %0d check(s)", fails);
    $finish;
  end

endmodule
`default_nettype wire
