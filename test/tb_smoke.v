/*
 * SMOKE TESTBENCH -- loads an image through the real pin-level load port and
 * asserts that the engine MOVES PINS.
 *
 * ⛔⛔ "IT ELABORATES" IS NOT EVIDENCE, and this project has the receipt: a
 * gate-level sim passed for weeks on a stub with ZERO flip-flops. So this bench
 * drives the actual `ui_in`/`uio_in` load protocol, enters run mode, and counts
 * EDGES on the protocol outputs. Zero edges = the engine did not run, however
 * cleanly it compiled.
 *
 * ⭐ IT ALSO CHECKS THE THREE THINGS THE RULINGS CARE ABOUT:
 *   (a) in LOAD mode the protocol outputs are HELD AT IDLE -- the fix for the
 *       constructed 64-byte image that clocked WREN+WRITE into the FRAM;
 *   (b) `uio_oe` is 0 throughout load mode, so the host owns the byte port;
 *   (c) the MISO enable RELEASES ASYNCHRONOUSLY when CS goes high (1.6r).
 */

`default_nettype none
`timescale 1ns / 1ps

module tb_smoke;

  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00;
  reg  [7:0] uio_drv = 8'h00;
  wire [7:0] uo_out, uio_out, uio_oe;
  // the host drives uio where the DUT has released it
  wire [7:0] uio_in = (uio_oe & uio_out) | (~uio_oe & uio_drv);

  // ⭐ BUFFER DEPTH, SELECTED AT ELABORATION: `iverilog -Ptb_smoke.SPL_CFG=1`
  // builds the single-buffer engine. ⛔⛔ WHY THE SMOKE BENCH NEEDS IT AT ALL:
  // the single-buffer configuration's PERFORMANCE cannot be quoted until its
  // CORRECTNESS is established, and this is the bench that asserts pin
  // movement, edge counts and C. A slower engine is a design alternative; a
  // broken one producing a smaller stall number is a measurement of nothing,
  // and the retracted "11 -> 7" benefit was computed from an arm whose
  // correctness had never been established because it could not be built.
  parameter integer SPL_CFG = 2;

  tt_um_protocol_emulator #(.SPL(SPL_CFG)) dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );

  // DO NOT REORDER: the shared host-channel driver needs `dut`, `clk`,
  // `rst_n` and `ui_in`, all declared above.
  // THE HOST CHANNEL, WHICH THIS BENCH NEVER DROVE. Ruling 0: every
  // `OP_SHIFT` the suite ever executed found `host_valid = 0` and took the
  // UNDERRUN branch, so the per-opcode `C` this bench writes to
  // `cj_measured*.txt` -- including the "8 of 8 opcodes" claim measured on the
  // census image -- was taken in the STARVED regime without saying so.
  // The feeder is a concurrent process inside the include; this bench only
  // declares which queues to feed and raises `hf_en` after load.
`include "test/host_feed.vh"

  always #10 clk = ~clk;                   // 50 MHz, the shipped clock

  // ---- image ----------------------------------------------------------
  // ⛔⛔⛔ THIS WAS `localparam IMG_BYTES = 51` AND IT SILENTLY TRUNCATED. The
  // loader shifted in exactly 51 bytes regardless of the image's real size, so
  // a longer program had its tail left UNWRITTEN in the store -- and the
  // engine then fetched an X action word, `l_timestamp` took
  // `l_timestamp + a_dly` with `a_dly` = X in ST_WB, and the lane went
  // PERMANENTLY unready because `ready` tests `now - l_timestamp`. One lane
  // died, the other kept running, and the bench reported its results as if the
  // program were complete.
  //
  // ⭐⭐ IT HAD NEVER FIRED BECAUSE EVERY IMAGE SO FAR WAS EXACTLY 51 BYTES.
  // The default, stress, five-lane and chain programs all have 5 headers plus
  // 7 actions = 30 + 21 = 51, so the constant matched by coincidence of
  // construction. The census image -- the first one with a different action
  // count -- broke on its first run. ⇒ A constant that encodes the shape of
  // one artefact is a trap that waits for the second artefact, and this is the
  // same class as the must-fire whose witness was a hard-coded 3 MHz.
  //
  // The length is now DERIVED: `$readmemh` leaves unwritten entries X, so the
  // highest initialised index + 1 is the image size. The array is sized to the
  // STORE (2**AW = 256) so no image can overflow it either.
  localparam integer IMG_MAX = 256;
  reg [7:0] img [0:IMG_MAX-1];
  integer img_bytes;

  integer i, errors;
  reg [3:0] prev_proto;
  integer   edges0, edges1, load_drive_viol, load_oe_viol;
  // ⭐ C AND J ARE MEASURED HERE. A2 ships C = 2 and J = 1, and "the FSM has
  // two states therefore C = 2" is a same-author re-derivation of my own
  // design intent -- which this project has already recorded is not an
  // independent witness. So the bench counts cycles.
  integer   svc_cycles, svc_jobs, svc_max, prev_st;
  // ⛔⛔ PER-OPCODE MIN *AND* MAX, NOT A MEAN. A mean of 2.00 is consistent with
  // every job taking exactly 2 AND with some taking 1 and some taking 3. A2
  // needs C_max, so the bench records both bounds per action type and a
  // separate gate checks them against a derivation from the RTL's structure.
  integer   op_min [0:7];
  integer   op_max [0:7];
  integer   op_n   [0:7];
  integer   cur_svc, cur_op, j, fd;
  // J, decomposed. `jitter_max` counts only the PREFETCH-MISS stall; the
  // winner-registration cycle is structural and is derived, not counted.
  integer   jmiss_max;

  // ⭐⭐ COLD START AND STEADY STATE ARE MEASURED SEPARATELY, and that split is
  // the whole result of the double buffer. `dut.u_eng.jitter_max` is a MAX OVER
  // THE WHOLE RUN, so a single startup transient pins it forever and the
  // steady-state behaviour becomes invisible -- which is exactly what happened:
  // after double-buffering, `jitter_max` still read 5 while the steady-state
  // stall was ZERO. A max over a run that contains a transient is not a
  // measurement of the steady state, and reading it as one would have made the
  // double buffer look like it had done nothing.
  //
  // ⛔ THE COLD START IS REAL, NOT AN ARTEFACT. At `hdr_done` both slots of
  // every lane are empty, so each lane's FIRST action waits for a full refill,
  // contended with the other lanes' first refills. It is confined to a few
  // hundred cycles after the header load and never recurs.
  integer   cyc, stall, jcold, jwarm, jwarm_at, warm_from, hdr_cyc, n_warm_ev;
  integer   warmup, ncyc_run;
  integer   win_slot, lk, inv_viol, inv_checks, nflip;
  reg       now_running;
  reg [31:0] prev_now;
  reg [4:0] prev_sel;
  reg [8*64-1:0] imgfile;
  reg [23:0] exp_act;
  // ⛔ 24, NOT 22, AND IT USED TO BE 22. The action word's bottom 2 bits were
  // zero padding and this bench compared `exp_act[23:2]` to match. Those bits
  // are now the TX QUEUE field, so the comparison is the WHOLE word -- and this
  // is a second copy of the action layout living in a bench, which is why the
  // invariant failed the moment the field was added rather than silently
  // ignoring it.
  reg [23:0] got_act;

  initial begin
    // ⭐ THE IMAGE IS SELECTABLE so the same bench can run the default program
    // and the REFILL-STRESS program. The default cannot measure J at all (its
    // delays are 20/31 against a ~4-cycle refill), which is why the stress
    // image exists -- see make_smoke_image.build_stress.
    // ⛔ COUNTERS ZEROED FIRST. They used to be cleared AFTER the short-image
    // check below, which wiped that check's own increment -- a guard whose
    // failure was erased one line later by initialisation. Found by reading the
    // order rather than by it firing, which is the only way it could be found:
    // the guard reports correctly and then the count is thrown away.
    errors = 0; edges0 = 0; edges1 = 0;
    load_drive_viol = 0; load_oe_viol = 0;
    cyc = 0; stall = 0; jcold = 0; jwarm = 0; jwarm_at = 0;
    warm_from = 0; hdr_cyc = -1; n_warm_ev = 0;
    inv_viol = 0; inv_checks = 0; nflip = 0; prev_sel = 5'b0;
    now_running = 0; prev_now = 32'hFFFFFFFF;

    if (!$value$plusargs("WARMUP=%d", warmup)) warmup = 200;
    if (!$value$plusargs("NCYC=%d", ncyc_run)) ncyc_run = 4000;
    if (!$value$plusargs("IMG=%s", imgfile)) imgfile = "test/smoke_image.hex";
    $readmemh(imgfile, img);
    // derive the real length: highest initialised byte + 1
    img_bytes = 0;
    for (i = 0; i < IMG_MAX; i = i + 1)
      if (^img[i] !== 1'bx) img_bytes = i + 1;
    $display("image %0s: %0d bytes", imgfile, img_bytes);
    // ⛔ ASSERTED, not trusted: a zero-length read means the path was wrong and
    // every result below would be about an empty store. $readmemh warns on a
    // missing file but does NOT stop the run.
    if (img_bytes < 20) begin
      $display("FAIL: image is %0d bytes -- too short to contain %0d lane headers.",
               img_bytes, 5);
      $display("      Either the path is wrong or the generator did not run.");
      errors = errors + 1;
    end
    hf_init;
    repeat (4) @(posedge clk);
    rst_n = 1;
    @(posedge clk);

    // ---- check reset state: uo_out protocol pins HIGH, uio released ----
    if (uo_out[3:0] !== 4'b1111) begin
      $display("FAIL reset: uo_out[3:0]=%b, expected 1111 (reset-high is FORCED on uo_out -- it cannot release)", uo_out[3:0]);
      errors = errors + 1;
    end
    if (uio_oe !== 8'h00) begin
      $display("FAIL reset: uio_oe=%h, expected 00 (uio CAN release, so it does -- strictly safer than driving a level onto an unknown bus)", uio_oe);
      errors = errors + 1;
    end

    // ---- LOAD MODE ------------------------------------------------------
    ui_in[7] = 1'b1;                       // prog_mode
    ui_in[5] = 1'b1;  @(posedge clk);      // pointer reset
    ui_in[5] = 1'b0;  @(posedge clk);

    for (i = 0; i < img_bytes; i = i + 1) begin
      uio_drv  = img[i];
      @(posedge clk); @(posedge clk);
      ui_in[6] = 1'b1;                     // WR rising edge
      @(posedge clk); @(posedge clk); @(posedge clk);
      ui_in[6] = 1'b0;
      @(posedge clk); @(posedge clk);
      // (a) protocol outputs must stay at IDLE while loading
      if (uo_out[3:0] !== 4'b1111) load_drive_viol = load_drive_viol + 1;
      // (b) the host must own the byte port
      if (uio_oe !== 8'h00)        load_oe_viol    = load_oe_viol + 1;
    end

    // ---- RUN MODE -------------------------------------------------------
    uio_drv  = 8'hFF;                      // CS high = deselected
    ui_in[7] = 1'b0;
    ui_in[6] = 1'b0;
    // FEED EVERY QUEUE. This bench runs whatever image it is given, so it
    // cannot know which queues the program names -- and a queue nobody draws
    // from simply stays full, because the feeder tops up to the depth and
    // stops rather than pushing blindly. `hf_check` reports the result.
    // ⛔⛔ NON-PALINDROMIC VECTORS (ruling 1b). This pattern was
    // {5A, C3, 3C, A5} -- FOUR BIT-REVERSAL PALINDROMES out of four, so it
    // passed under EITHER bit order and tested nothing about order at all.
    // That is how the engine's LSB-first wire order went unnoticed while
    // `pe_isa.py` documented the opposite: the only byte ever checked end to
    // end read the same both ways.
    // 0x5B/0x01/0x7A/0xC7 reverse to DA/80/5E/E3 -- all different, and 0x01
    // is the asymmetric extreme the ruling asks for.
    hf_set(0, 8'h5B, 8'h01, 8'h7A, 8'hC7);
    hf_set(1, 8'h5B, 8'h01, 8'h7A, 8'hC7);
    hf_set(2, 8'h5B, 8'h01, 8'h7A, 8'hC7);
    hf_set(3, 8'h5B, 8'h01, 8'h7A, 8'hC7);
    hf_en = 1'b1;
    prev_proto = uo_out[3:0];
    svc_cycles = 0; svc_jobs = 0; svc_max = 0; prev_st = 0;
    cur_svc = 0; cur_op = 0;
    for (j = 0; j < 8; j = j + 1) begin
      op_min[j] = 9999; op_max[j] = 0; op_n[j] = 0;
    end
    // ⛔⛔ THE RUN LENGTH IS SETTABLE, AND 4000 WAS A SILENT CEILING ON WHAT
    //    "STEADY STATE" COULD MEAN. With the warm-up at 200 that is a 3.4k
    //    window, which is ample for the shipped program -- and far too short
    //    for a 5-lane stress set whose contended transient outlives it. Worse,
    //    pushing the warm-up out to find the end of the transient silently
    //    emptied the window: `warm_from > 4000` reports ZERO EVENTS, which
    //    reads exactly like "no stalls" and is really "no measurement".
    // ⚠ That vacuity cost me two wrong conclusions in a row -- first that the
    //    record was unsound, then that it reproduced.
    for (i = 0; i < ncyc_run; i = i + 1) begin
      @(posedge clk);
      if (uo_out[0] !== prev_proto[0]) edges0 = edges0 + 1;
      if (uo_out[1] !== prev_proto[1]) edges1 = edges1 + 1;
      prev_proto = uo_out[3:0];
      // service time: cycles with the dispatch FSM out of IDLE, per job
      if (dut.u_eng.st != 0) begin
        svc_cycles = svc_cycles + 1;
        cur_svc = cur_svc + 1;
        if (prev_st == 0) cur_op = dut.u_eng.a_op;
      end
      if (prev_st == 0 && dut.u_eng.st != 0) svc_jobs = svc_jobs + 1;
      // a service ENDED this cycle: record its length against its opcode
      if (prev_st != 0 && dut.u_eng.st == 0) begin
        if (cur_svc < op_min[cur_op]) op_min[cur_op] = cur_svc;
        if (cur_svc > op_max[cur_op]) op_max[cur_op] = cur_svc;
        op_n[cur_op] = op_n[cur_op] + 1;
        cur_svc = 0;
      end
      prev_st = dut.u_eng.st;

      // ---- J, split into cold start and steady state ------------------
      // ⛔ THE STALL CONDITION IS READ OFF THE ENGINE, not inferred from a
      // counter the engine keeps. `jitter_max` is a whole-run max and cannot
      // distinguish the two regimes; this reconstructs the condition the engine
      // increments on -- winner chosen, released, and waiting ONLY on its head
      // slot -- so the two numbers come from the same event, sliced by time.
      cyc = cyc + 1;
      if (hdr_cyc < 0 && dut.u_eng.hdr_done) begin
        hdr_cyc   = cyc;
        // ⛔⛔ THE WARM-UP IS SETTABLE, AND 200 WAS SIZED FOR THE SHIPPED
        //    PROGRAM. The shipped lanes have periods 25..4140, so a few hundred
        //    cycles covers five first refills. A 5-lane STRESS program at
        //    periods 12..16 has a longer contended transient, and its last
        //    stall event landed at cycle 299 -- just inside a window that
        //    starts around 250. A fixed constant is a steady-state definition
        //    that silently depends on the program.
        // ⚠ Reading a transient as steady state is exactly the error this
        //    cold/warm split exists to prevent, one program class over.
        warm_from = cyc + warmup;
      end

      // ---- THE BUFFER-SWAP INVARIANT, against the IMAGE -----------------
      // ⭐⭐ THE HEAD SLOT MUST HOLD THE ACTION AT `l_pc`, and this is checked
      // against the loaded IMAGE rather than against another engine register.
      // That matters: comparing two engine registers to each other would be
      // satisfied by any self-consistent wrong state, which is precisely what a
      // stale buffer IS. The image is the independent reference.
      // ⛔ This is what the double buffer owes. Two slots, a select bit and a
      // fetch pointer that runs ahead of the PC are four pieces of state that
      // must agree, and "the edges still look right" does not check them --
      // a lane dispatching a stale action can still toggle its pin.
      for (lk = 0; lk < 2; lk = lk + 1) begin
        if (dut.u_eng.hdr_done && dut.u_eng.l_live[lk]
            // ⛔⛔ THE ENGINE'S OWN HEAD INDEX, NOT A COPY OF IT. This bench
            // used to write out `lk*2 + (l_sel[lk] ? 1 : 0)` itself, and at
            // SPL = 1 that is the WRONG SLOT: lane 1's head is slot 1, while
            // the formula gives 2 -- so the invariant compared lane 1's PC
            // against lane 2's action word and failed 3207 times on a design
            // that was behaving correctly. ⭐ Exactly the defect class this
            // file has already supplied once, with its private `exp_act[23:2]`
            // slice of the action word, which broke the moment a field used
            // the padding. `hix` is the single arithmetic site in the engine;
            // reading it makes the bench depth-independent for free.
            && dut.u_eng.l_actv[dut.u_eng.hix[lk]]
            && dut.u_eng.st == 0) begin
          exp_act = {img[dut.u_eng.l_pc[lk]], img[dut.u_eng.l_pc[lk] + 1],
                     img[dut.u_eng.l_pc[lk] + 2]};
          got_act = dut.u_eng.l_act[dut.u_eng.hix[lk]];
          inv_checks = inv_checks + 1;
          if (got_act !== exp_act) begin
            if (inv_viol == 0)
              $display("FAIL buffer-swap invariant: cyc %0d lane %0d pc %0d sel %0d -- head holds %h, image says %h",
                       cyc, lk, dut.u_eng.l_pc[lk], dut.u_eng.l_sel[lk],
                       got_act, exp_act);
            inv_viol = inv_viol + 1;
          end
        end
      end
      // ⭐ SELECT-BIT FLIPS, counted so a mutation of the swap is required to
      // TAKE EFFECT. A "characterised survivor" that turned out to be a no-op
      // would otherwise read exactly like one whose cost is merely small.
      for (lk = 0; lk < 5; lk = lk + 1)
        if (dut.u_eng.l_sel[lk] !== prev_sel[lk]) nflip = nflip + 1;
      for (lk = 0; lk < 5; lk = lk + 1) prev_sel[lk] = dut.u_eng.l_sel[lk];
      // ⛔⛔ THE THIRD PRIVATE COPY OF THE SLOT INDEX IN THIS SESSION, and
      // the one that mattered most: THIS is the slot the steady-stall
      // reconstruction below reads, so at SPL = 1 it read the WRONG LANE's
      // slot and the single-buffer column of the T3 comparison was measured
      // against it. The other two were the buffer-swap invariant in this same
      // file and `tb_jlane`'s head index.
      // ⚠ Three copies, found one at a time, in two files, in one sitting --
      // after the RTL's ten copies had already been collapsed into `hix`. A
      // fix on one axis repeats the error on the parallel one unless the whole
      // class is swept, so: no bench computes a slot index any more.
      win_slot = dut.u_eng.hix[dut.u_eng.winner];
      // ⛔⛔ THE GATE IS "SCHEDULE TIME IS RUNNING", NOT `hdr_done`, AND THE
      // DIFFERENCE IS A WHOLE RULING. With `hdr_done` this counted the
      // PRIMING refills as jitter -- it reported cold = 4 while the engine's
      // own counter said 0, and the cross-check below fired on the
      // disagreement. The engine is right: before priming completes `now` is
      // frozen, no job has been released, and a cycle in which nothing is
      // dispatched is not a release-to-dispatch delay.
      // ⭐ IT KEYS OFF `now` ADVANCING RATHER THAN OFF `primed`, deliberately.
      // Reading `primed` would make this a copy of the engine's control signal
      // instead of an independent reconstruction -- and worse, it would make
      // the M_NO_PRIME mutant INVISIBLE: that mutant releases jobs while the
      // schedule runs unprimed, and a bench keyed on `primed` would simply not
      // look during the window where the mutant does its damage. `now` moving
      // is the datapath fact that the schedule has started, under the design
      // and under the mutant alike.
      now_running = (dut.u_eng.now !== prev_now);
      prev_now = dut.u_eng.now;
      if (dut.u_eng.st == 0 && now_running && dut.u_eng.winner_v
          && !dut.u_eng.l_actv[win_slot]) begin
        stall = stall + 1;
        if (stall > jcold) jcold = stall;
        if (warm_from > 0 && cyc > warm_from && stall > jwarm) begin
          jwarm    = stall;
          jwarm_at = cyc;
        end
      end else begin
        if (stall > 0 && warm_from > 0 && cyc > warm_from)
          n_warm_ev = n_warm_ev + 1;
        stall = 0;
      end
    end

    // ---- report ---------------------------------------------------------
    $display("");
    $display("==== SMOKE RESULTS ====");
    $display("  load-mode protocol-output drive violations : %0d (must be 0)",
             load_drive_viol);
    $display("  load-mode uio_oe violations                : %0d (must be 0)",
             load_oe_viol);
    $display("  edges on uo_out[0] (lane 0)                : %0d (must be >0)",
             edges0);
    $display("  edges on uo_out[1] (lane 1)                : %0d (must be >0)",
             edges1);

    if (load_drive_viol != 0) begin
      $display("FAIL: load mode drove a protocol output. That is the bug that let a constructed image clock WREN+WRITE into the FRAM.");
      errors = errors + 1;
    end
    if (load_oe_viol != 0) begin
      $display("FAIL: uio_oe non-zero in load mode.");
      errors = errors + 1;
    end
    if (edges0 == 0) begin
      $display("FAIL: lane 0 never moved its pin -- THE ENGINE DID NOT RUN. This is the 'artefact too simple to reach the path' failure, and it is why this bench counts edges instead of trusting a clean elaboration.");
      errors = errors + 1;
    end
    if (edges1 == 0) begin
      $display("FAIL: lane 1 never moved its pin -- only ONE lane ran, so the scheduler never changed hands and M-PREFETCH-STALE would be vacuous.");
      errors = errors + 1;
    end

    $display("");
    $display("==== MEASURED C AND J ====");
    $display("  jobs dispatched            : %0d", svc_jobs);
    $display("  total service cycles       : %0d", svc_cycles);
    // ⛔ reported x100 because integer division TRUNCATES: 75/38 is 1.97 and
    // prints as 1, which would read as "C = 1" and look like good news.
    if (svc_jobs > 0)
      $display("  measured C (x100 cycles/job): %0d  [A2 ships C = 2 -> 200]",
               (svc_cycles * 100) / svc_jobs);
    // ⛔ LABELLED AS THE AGGREGATE IT IS. This printed "measured J (max
    // prefetch stall)", which reads as a per-lane jitter term. `jitter_cnt` is
    // one counter for all lanes and does not clear when the winner changes, so
    // the run it reports can span two lanes' waits. It upper-bounds any single
    // lane's wait (the safe direction) but is not that quantity; the per-lane
    // measurement is `tb_jlane.v` / `docs/PREREG_J_LANE.md`.
    $display("  any-winner-blocked run (aggregate, NOT per-lane J) : %0d  [A2 ships J = 1]",
             dut.u_eng.jitter_max);
    if (svc_jobs > 0 && ((svc_cycles * 100) / svc_jobs < 195 ||
                         (svc_cycles * 100) / svc_jobs > 205)) begin
      $display("  *** C IS NOT 2. A2's shipped r_i are scoped to C = 2, so this");
      $display("      goes back to 1.3 and is NOT absorbed.");
      errors = errors + 1;
    end
    $display("");
    $display("  --- J SPLIT: cold start vs steady state (the double buffer) ---");
    $display("  hdr_done at cycle            : %0d", hdr_cyc);
    $display("  warm-up window ends at cycle : %0d", warm_from);
    // ⭐ THE WINDOW LENGTH IS PRINTED, so an empty one cannot be read as a
    //    clean zero. A steady-state number from a zero-length window is not a
    //    measurement, and nothing downstream can tell unless it is stated.
    $display("  steady window length         : %0d cycles%0s",
             (cyc > warm_from) ? (cyc - warm_from) : 0,
             (cyc > warm_from) ? "" : "   *** EMPTY -- no measurement");
    $display("  cycles observed              : %0d", cyc);
    $display("  max prefetch stall, COLD     : %0d", jcold);
    $display("  max prefetch stall, STEADY   : %0d  (last at cycle %0d)",
             jwarm, jwarm_at);
    $display("  stall EVENTS in steady state : %0d", n_warm_ev);
    $display("");
    $display("  --- BUFFER-SWAP INVARIANT (head slot == image at l_pc) ---");
    $display("  checks performed             : %0d", inv_checks);
    $display("  violations                   : %0d (must be 0)", inv_viol);
    $display("  select-bit flips             : %0d", nflip);
    // ⛔ A ZERO-VIOLATION RESULT IS WORTHLESS IF THE CHECK NEVER RAN, and that
    // is the shape of half the defects in this project. The check is guarded on
    // `hdr_done && l_live && head valid && st == IDLE`, every one of which
    // could be false for the whole run -- so the COUNT is asserted too.
    if (inv_checks < 100) begin
      $display("  *** THE INVARIANT RAN %0d TIMES. It is guarded on four", inv_checks);
      $display("      conditions and a vacuous pass is indistinguishable from a");
      $display("      real one. Treated as a FAILURE, not as 0 violations.");
      errors = errors + 1;
    end
    if (inv_viol > 0) begin
      $display("  *** THE HEAD SLOT DOES NOT HOLD THE ACTION AT l_pc. The");
      $display("      double buffer is dispatching a word the program counter");
      $display("      does not point at -- a stale or mis-swapped buffer.");
      errors = errors + 1;
    end
    if (jcold != dut.u_eng.jitter_max) begin
      // ⛔ the arguments used to sit on the LAST $display while the format
      // specifiers were on the first two, so iverilog warned and printed
      // "(<%0d>)" -- a diagnostic that fires correctly and then cannot be read.
      $display("  *** the bench's cold max (%0d) disagrees with the engine's own",
               jcold);
      $display("      jitter_max (%0d). One of the two reconstructions of the",
               dut.u_eng.jitter_max);
      $display("      stall condition is wrong, and neither number is usable");
      $display("      until it is known which.");
      errors = errors + 1;
    end
    // ⛔⛔ THE BUDGET IS CHECKED AGAINST THE STEADY STATE, AND THE COLD START IS
    // REPORTED SEPARATELY RATHER THAN DROPPED. The shipped r_i are a
    // steady-state claim about inter-action timing; the cold start is a
    // one-off offset on each lane's FIRST action, before the protocol has
    // begun, and a uniform start offset is not inter-action jitter.
    // ⚠ THAT IS A MODELLING CLAIM AND IT IS WILSON'S TO RULE, not mine to
    // assume: Spuri's RTA bounds EVERY job including the first. So the cold
    // number is printed, written to cj_measured.txt, and left visible.
    // ⭐⭐ RULING 1(a) MUST-FIRE: FIRST-EDGE JITTER == STEADY-STATE JITTER.
    // This is what makes excluding the start-up latency EARNED rather than
    // asserted. The old design had cold = 5 against steady = 0, so a lane's
    // first edge was late while its second was on time -- and on a SOURCE lane
    // that difference IS differential jitter against D_tol: the peer sees a
    // short first bit. Declaring the first job out of scope would have excluded
    // a real timing error for the sole reason that it happened first.
    // ⛔ Prime-before-release removes it structurally instead: no lane is
    // released until every live lane's buffers are primed, and `now` does not
    // advance until then, so the refill latency elapses before job 1 exists.
    // The equality below is the evidence that it worked. M_NO_PRIME breaks it.
    if (jcold != jwarm) begin
      $display("  *** PRIME-BEFORE-RELEASE MUST-FIRE FAILED: cold %0d != steady %0d.",
               jcold, jwarm);
      $display("      A lane's FIRST action is delayed differently from its");
      $display("      later ones, so the start-up latency is NOT outside every");
      $display("      job's response time and cannot be excluded from J.");
      errors = errors + 1;
    end
    if (jwarm > 2) begin
      $display("  *** STEADY-STATE J EXCEEDS THE PRE-REGISTERED 2. The double");
      $display("      buffer's falsifier (bursty.DOUBLE_BUFFER_PREREG) has");
      $display("      FIRED. Report it; do not re-argue the decomposition.");
      errors = errors + 1;
    end
    $display("");

    // ---- write the measurements for the derivation gate to check ------
    jmiss_max = dut.u_eng.jitter_max;
    // ⛔⛔ THE OUTPUT PATH DEPENDS ON THE INPUT, so the default program's
    // measurements CANNOT be overwritten by a stress run. Detecting the clobber
    // (the `image` line below, asserted by gate_cj_bounds) was the first fix,
    // and it worked -- it caught `sim 7` from a program the gate was not
    // measuring. But detection leaves the hazard in place: running
    // `test/run_mutants.py` legitimately exercises the stress images and then
    // left the C/J gate RED until someone re-ran the default bench. The
    // standing rule is to make N+1 IMPOSSIBLE, not merely visible, so a
    // non-default image writes somewhere else entirely.
    // ⭐ The `image` provenance line is KEPT anyway: two independent guards on
    // the same hazard, one structural and one asserted, and the asserted one is
    // what would catch a future third image path added without thinking.
    // ⛔⛔ AND `SPL` IS A SECOND DIMENSION OF THE SAME HAZARD, ADDED LATER AND
    // MISSED AT FIRST. The guard above was written for the IMAGE argument;
    // when the action-buffer depth became a parameter, a single-buffer run
    // wrote this same path and clobbered the shipped measurement -- jobs 344
    // became 345, `op 7 n 130` became 131 -- and `gate_cj_bounds` then
    // validated the shipped C against a SINGLE-BUFFER run.
    // ⭐ IT PASSED, which is the instructive part: C is 2.00 at both depths,
    // so the gate agreed with a measurement of a design it was not measuring.
    // A guard can pass BECAUSE the two values happen to coincide.
    // ⇒ Any non-default value on EITHER axis writes somewhere else entirely.
    if (imgfile == "test/smoke_image.hex" && SPL_CFG == 2)
      fd = $fopen("test/cj_measured.txt", "w");
    else
      fd = $fopen("test/cj_measured_alt.txt", "w");
    // the depth travels WITH the numbers, and the gate asserts it
    $fwrite(fd, "spl %0d\n", SPL_CFG);
    // ⛔⛔ THE IMAGE IS RECORDED IN THE FILE, and the gate asserts it. This file
    // has ONE constant path while the bench now takes an IMAGE argument, which
    // is the textbook clobber hazard -- and it bit immediately: a refill-stress
    // run overwrote the default program's measurements and gate_cj_bounds
    // reported "sim 7" for a program it was not measuring, while looking
    // perfectly green. Env-selected input plus a constant output path silently
    // produces the wrong artefact, so the provenance travels WITH the numbers.
    $fwrite(fd, "image %0s\n", imgfile);
    // THE FED STATE TRAVELS WITH THE NUMBERS, for exactly the reason the
    // image and the depth do. A per-opcode `C` measured with every queue
    // EMPTY is a measurement of the UNDERRUN PATH, and it is
    // indistinguishable from a fed one by the numbers alone -- SHIFT takes
    // two cycles either way. That is how "C measured on 8 of 8 opcodes"
    // came to describe the starved regime for the whole life of the host
    // channel. `gate_cj_bounds` now REFUSES a file whose SHIFT count is
    // non-zero while `fed` is 0.
    $fwrite(fd, "fed %0d\n", hf_bytes);
    $fwrite(fd, "pops %0d\n", hf_pops);
    $fwrite(fd, "underrun %0d\n",
            (dut.u_eng.lane_underrun != 5'b00000) ? 1 : 0);
    $fwrite(fd, "jobs %0d\n", svc_jobs);
    $fwrite(fd, "svc_cycles %0d\n", svc_cycles);
    $fwrite(fd, "jmiss_max %0d\n", jmiss_max);
    $fwrite(fd, "jmiss_cold %0d\n", jcold);
    $fwrite(fd, "jmiss_steady %0d\n", jwarm);
    $fwrite(fd, "steady_stall_events %0d\n", n_warm_ev);
    $fwrite(fd, "cycles %0d\n", cyc);
    $fwrite(fd, "hdr_cyc %0d\n", hdr_cyc);
    for (j = 0; j < 8; j = j + 1)
      if (op_n[j] > 0)
        $fwrite(fd, "op %0d n %0d min %0d max %0d\n", j, op_n[j],
                op_min[j], op_max[j]);
    $fclose(fd);
    $display("");
    $display("==== PER-OPCODE SERVICE, MIN AND MAX ====");
    for (j = 0; j < 8; j = j + 1)
      if (op_n[j] > 0)
        $display("  opcode %0d : n=%0d  min=%0d  max=%0d", j, op_n[j],
                 op_min[j], op_max[j]);
    $display("  (written to test/cj_measured.txt for the bounds gate)");
    $display("");

    if (errors == 0) $display("  SMOKE: PASS");
    else             $display("  SMOKE: %0d FAILURE(S)", errors);
    $display("");
    $finish;
  end

endmodule
