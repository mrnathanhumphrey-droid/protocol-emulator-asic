/* tb_jlane.v -- THE PER-LANE JITTER INSTRUMENT.
 *
 * Measures, for ONE identified lane, the cycles its dispatch waited because
 * its own action word was not in the register yet -- and nothing else.
 *
 * ⛔⛔ THE HYPOTHESIS AND THE FALSIFIER ARE PRE-REGISTERED IN
 * `docs/PREREG_J_LANE.md`, COMMITTED BEFORE THIS FILE EXISTED (8bc6979).
 * `J_lane <= 2*L_REFILL + 1 = 9`; falsifier: any complete release interval on
 * any identified lane in any arm with `sum > 9`. Read that document before
 * reading a number out of here.
 *
 * ⛔ WHY NOT `jitter_max`. The engine's counter is ENGINE-WIDE: `jitter_cnt`
 * increments whenever the CURRENT winner is blocked, and the witness ring
 * showed the winner CHANGING mid-stall. So it is an "any-winner-blocked run
 * length", and the aggregate 12 on record may be several lanes' waits laid
 * end to end. This bench pins the winner to one lane.
 *
 * ⛔ WHY NOT RELEASE-TO-DISPATCH WALL TIME. That includes EDF interference --
 * cycles when the lane is ready but another lane legitimately holds the engine
 * -- which the response analysis already charges through C. Counting it as
 * jitter double-charges it and would falsify any small bound trivially on a
 * 5-lane image. It is measured anyway, as `wall`, so that a passing J_lane is
 * never misread as "dispatches within 9 cycles of release".
 *
 * ⚠ IT REPORTS A FLOOR, NOT A BOUND: finitely many arms and one phase
 * alignment each.
 */

`default_nettype none
`timescale 1ns / 1ps

`include "test/imgload.vh"
module tb_jlane;

  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00, uio_in = 8'h00;
  wire [7:0] uo_out, uio_out, uio_oe;

  localparam integer IMG_MAX  = 256;
  localparam integer PIN_PROG = 7, PIN_PTR = 5, PIN_WR = 6;
  localparam integer RING     = 48;
  localparam integer NL       = 5;

  // ---- the pre-registered constants, named here so a run cannot drift ----
  localparam integer L_REFILL      = 4;
  localparam integer J_PREREG      = 2 * L_REFILL + 1;   // = 9
  localparam integer MIN_WINDOW    = 100000;
  localparam integer MIN_INTERVALS = 100;

  reg  [7:0] img [0:IMG_MAX-1];
  integer    img_bytes, i, cyc, ncyc, warmup, warm_from, lane;
  reg [8*256-1:0] imgfile;

  // ---- interval state ---------------------------------------------------
  reg        in_iv;
  integer    iv_start, iv_sum, iv_run, cur_run;
  integer    max_sum, max_sum_at, max_run, max_wall, max_wall_at;
  integer    n_iv, n_drop, n_fire, n_over;
  // ⭐⭐ INTERVAL-INDEPENDENT READINGS, so a lane with no usable release edges
  // still produces a number rather than a silence. A BACKLOGGED lane -- one
  // whose timestamp is permanently in the past because it is not keeping up
  // with its own period -- is continuously `ready`, so it has almost no
  // ready RISING edges and therefore almost no release intervals. Without
  // these counters that case is indistinguishable from "a quiet lane with no
  // waits", which is the shape of the probe error that once produced the
  // OPPOSITE of the right answer.
  // ⚠ `free_run` is NOT the pre-registered quantity. It is the longest
  // blocked run anywhere in the window, ignoring interval membership.
  integer    n_rdy, n_blk, free_run, cur_free, free_at;
  // ⛔⛔ STATIONARITY, MEASURED RATHER THAN ASSUMED. The first controlled run
  // of this bench found arm A lane 0 completing SIX release intervals in the
  // first 196k cycles and several thousand in the next 272k -- so a 4000-cycle
  // warm-up was nowhere near the end of the transient on this program, and a
  // maximum taken from the early window would be a transient reading dressed
  // as a steady-state one. That is the error that made 500 and 1000 both read
  // 7 in the J investigation, in the opposite direction.
  // ⇒ The window is split in half and both halves are reported. A run whose
  //   two halves disagree is not stationary and yields NO READING.
  integer    mid, n_iv_h1, n_iv_h2;
  // ⛔⛔ THE THIRD BUCKET -- R1's crux. Inside one release interval a cycle is
  // exactly one of:
  //   EXEC  st != ST_IDLE            some lane is executing an action. That is
  //                                  EDF interference and pyRTA's recurrence
  //                                  already charges it through C_j.
  //   MINE  idle, and I am the winner-blocked lane. That is the prefetch-miss
  //                                  wait the J = 9 bound is about.
  //   GAP   idle, and I am NOT the winner. The engine is stalled on ANOTHER
  //                                  lane's refill: nothing executes, so pyRTA
  //                                  charges nothing, and `sum_L` skips it
  //                                  because the winner is not me.
  // ⇒ GAP IS THE CYCLE THAT BELONGS TO NEITHER MODEL, and the ruling demands
  //   it belong to exactly one. If it is ever non-zero the J = 9 bound does
  //   not cover the delay RTA needs, and the sound bound is the full
  //   non-execution wait `sum + gap`.
  integer    iv_gap, iv_exec, max_gap, max_full, max_full_at;
  // ⛔⛔ `gap` SPLITS, AND THE D* THEOREM IS ABOUT ONLY HALF OF IT. An idle
  // cycle in which I am not the winner is one of two quite different things:
  //   RQ  the winner's HEAD IS INVALID -- the engine is idle because the one
  //       fetch port is refilling for a lane that outranks me. This is R1's
  //       uncounted term, the one measured at 40 cycles below D*.
  //   DD  the winner's head is VALID -- it is about to dispatch, and this is
  //       its ST_IDLE decision cycle. Ordinary EDF ordering, not refill
  //       queueing at all.
  // ⚠ CONFLATING THEM UNDERSTATES THE D* THEOREM AND OVERSTATES R1. At d = 20
  // the first spot check read `gap` = 1..3 with the winner-blocked stall at
  // ZERO, which looked like a nonzero refill wait above D* -- and would have
  // falsified the published claim. It is DD: other lanes taking their turn.
  integer    iv_rq, iv_dd, max_rq, max_rq_at, max_dd;
  reg        prev_ready, live_seen, primed_seen, cfgerr_seen, halt_seen;

  // ---- the witness ring, so a FALSIFYING interval arrives with its chain --
  integer r_cyc [0:RING-1];
  integer r_pst [0:RING-1];
  integer r_pl  [0:RING-1];
  integer r_win [0:RING-1];
  integer r_hd  [0:RING-1];
  integer r_sum [0:RING-1];
  integer head, n;
  // ⛔⛔ THE DUMP TASK GETS ITS OWN LOOP INDEX. It shared `i` with the main
  // run loop, so every chain dump reset `i` to RING and THE BENCH RAN LONGER
  // THAN `NCYC` -- by a factor of 2.3 on one lane. The giveaway was a reported
  // window of 468099 cycles on a 200000-cycle run, which is impossible; only
  // the lanes that actually dumped were affected, so four cells were wrong and
  // six were right. ⭐ Caught because the window is a PRINTED PRECONDITION
  // with a known ceiling. A run length that depends on how often the bench
  // printed is not a controlled measurement.
  integer di, dn;

  always #10 clk = ~clk;

  // ⭐⭐ THE BUFFER DEPTH IS A PARAMETER, SELECTED AT ELABORATION. Build the
  // single-buffer configuration with
  //     iverilog -Ptb_jlane.SPL_CFG=1 ...
  // ⛔ A PARAMETER, NOT A `define`. `SPL` is in the engine's parametric
  // contract because the single-buffer engine is a DESIGN ALTERNATIVE worth
  // 169 flops, not a defect to be killed -- and the stored `SWEEP_SINGLE`
  // sweep described a configuration no command could build, which is how its
  // benefit claim became unverifiable. A root-module parameter override keeps
  // the selection out of the RTL entirely.
  parameter integer SPL_CFG = 2;

  tt_um_protocol_emulator #(.SPL(SPL_CFG)) dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );

`include "test/progress.vh"
`include "test/clocked_conform.vh"

  // ⛔⛔ THE PREDICATE IS `pe_engine.v:1076-1089` READ LITERALLY, with the
  // winner pinned to `lane`. Every term earns its place:
  //   `primed && !config_err` -- the ST_IDLE arm is gated on both, so a cycle
  //     before priming is not a dispatch opportunity and must not count;
  //   `!l_armed` -- an armed winner arriving ready takes the TIMEOUT-HALT
  //     branch, not the stall branch, and does not increment `jitter_cnt`.
  //     ⚠ `tb_witness.v`'s `waiting` wire omits this and so counts a halting
  //     lane as a stalling one; harmless there, not inherited here.
  // ⛔⛔ THE ENGINE'S OWN HEAD INDEX, NOT A COPY OF IT -- AND THIS FILE IS WHY
  // THAT RULE EXISTS TWICE. It first read `lane*2 + (l_sel[lane] ? 1 : 0)`,
  // declared [2:0], which aliased lane 4's slots (8, 9) onto lane 0's. That
  // was widened to [3:0] and the comment here warned about exactly it -- and
  // the SAME copy then produced a second, worse failure at SPL = 1, where
  // lane 1's head is slot 1 while `1*2` reads LANE 2's slot: the instrument
  // reported a per-interval sum of 1870 against a bound of 9, a five-alarm
  // result that was entirely its own bug.
  // ⚠ A FIX REPRODUCED ON THE UNEXAMINED AXIS. `tb_smoke` had the identical
  // copy, was found and fixed in the same session, and this file -- the one
  // carrying the warning -- was not. Reading `hix` makes the bench
  // depth-independent and removes the class.
  wire [3:0] l_head  = dut.u_eng.hix[lane];
  wire       at_idle = dut.u_eng.primed && !dut.u_eng.config_err
                       && (dut.u_eng.st == 0) && dut.u_eng.winner_v
                       && (dut.u_eng.winner == lane[2:0])
                       && !dut.u_eng.l_armed[lane];
  wire       blocked  = at_idle && !dut.u_eng.l_actv[l_head];
  wire       dispatch = at_idle &&  dut.u_eng.l_actv[l_head];
  wire       rdy      = dut.u_eng.ready[lane];

  task dump_chain;
    begin
      $display("    --- witness chain, new max sum=%0d ending at cycle %0d",
               max_sum, max_sum_at);
      $display("        `pl` is the lane the ONE fetch port was serving,");
      $display("        `pst` its state (0=SCAN 1=REQ 2=WAIT 3=CAP).");
      $display("      %-8s %-5s %-5s %-7s %-6s %s",
               "cycle", "pst", "pl", "winner", "head?", "sum");
      for (di = 0; di < RING; di = di + 1) begin
        dn = (head + di) % RING;
        if (r_cyc[dn] > 0)
          $display("      %-8d %-5d %-5d %-7d %-6d %0d",
                   r_cyc[dn], r_pst[dn], r_pl[dn], r_win[dn], r_hd[dn],
                   r_sum[dn]);
      end
    end
  endtask

  // ⭐ ARM IDENTITY, DECODED FROM THE FILE THAT ACTUALLY LOADED, not from the
  // command line -- a run attributed to the wrong arm is a wrong result that
  // looks right.
  //
  // ⛔ THE LAYOUT, COUNTED FROM `pe_isa.HDR_FIELDS` RATHER THAN FROM THE
  // PROSE. 47 bits in 6 bytes, MSB-aligned, 1 spare at the bottom:
  //   [47:44] pin  [43:40] clkpin  [39] mode  [38:29] t  [28:25] C
  //   [24:17] D_sched  [16:9] D_tol  [8:1] base  [0] spare
  // The first version of this task used `make_smoke_image.py`'s docstring,
  // which omits the `mode` bit -- so every field below it was one bit adrift
  // and the d=12 arm echoed "518". ⭐ IT WAS CAUGHT BECAUSE THE ECHO IS A
  // PRECONDITION WITH A KNOWN ANSWER: a decode of a field nobody checks
  // against an expected value would have shipped.
  task echo_arm;
    integer j, t;
    begin
      $write("# arm t =");
      for (j = 0; j < NL; j = j + 1) begin
        t = ((img[j*6 + 1] & 8'h7F) << 3) | (img[j*6 + 2] >> 5);
        $write(" %0d", t);
      end
      $write("\n");
    end
  endtask

  initial begin
    if (!$value$plusargs("IMG=%s", imgfile)) begin
      $display("tb_jlane: FATAL -- +IMG=<file> is required.");
      $finish;
    end
    if (!$value$plusargs("LANE=%d", lane)) begin
      $display("tb_jlane: FATAL -- +LANE=<n> is required. This bench measures");
      $display("  ONE IDENTIFIED LANE; defaulting it would silently report");
      $display("  lane 0 for every arm.");
      $finish;
    end
    if (!$value$plusargs("NCYC=%d", ncyc))     ncyc = 200000;
    if (!$value$plusargs("WARMUP=%d", warmup)) warmup = 4000;
    if (!$value$plusargs("NBYTES=%d", img_bytes)) begin
      $display("tb_jlane: FATAL -- +NBYTES=<n> is required.");
      $display("  Deriving it from unwritten-array state is simulator-");
      $display("  dependent, and a program that never loaded reads as");
      $display("  'no stalls' -- which is how a probe in this investigation");
      $display("  produced the OPPOSITE of the right answer.");
      $finish;
    end
    $readmemh(imgfile, img);
    `PE_REQUIRE_IMG_LOADED(imgfile)
    // ⛔ THE CONFIGURATION IS ECHOED, for the same reason the arm's delays
    // are: a single-buffer number reported under the double-buffer name is a
    // wrong result that looks right, and the whole point of T3 is comparing
    // the two.
    $display("# jlane img=%0s bytes=%0d lane=%0d ncyc=%0d warmup=%0d prereg=%0d SPL=%0d",
             imgfile, img_bytes, lane, ncyc, warmup, J_PREREG, SPL_CFG);
    echo_arm;

    for (i = 0; i < RING; i = i + 1) begin
      r_cyc[i] = 0; r_pst[i] = 0; r_pl[i] = 0;
      r_win[i] = 0; r_hd[i] = 0; r_sum[i] = 0;
    end
    cyc = 0; warm_from = 0; head = 0;
    in_iv = 1'b0; iv_start = 0; iv_sum = 0; iv_run = 0; cur_run = 0;
    max_sum = 0; max_sum_at = 0; max_run = 0; max_wall = 0; max_wall_at = 0;
    n_iv = 0; n_drop = 0; n_fire = 0; n_over = 0;
    n_rdy = 0; n_blk = 0; free_run = 0; cur_free = 0; free_at = 0;
    mid = 0; n_iv_h1 = 0; n_iv_h2 = 0;
    iv_gap = 0; iv_exec = 0; max_gap = 0; max_full = 0; max_full_at = 0;
    iv_rq = 0; iv_dd = 0; max_rq = 0; max_rq_at = 0; max_dd = 0;
    prev_ready = 1'b0;
    live_seen = 1'b0; primed_seen = 1'b0; cfgerr_seen = 1'b0; halt_seen = 1'b0;

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
    uio_in = 8'hFF;

    // ---- run -----------------------------------------------------------
    // ⭐ SAMPLED AT POSEDGE, ON PURPOSE. The engine's regs use non-blocking
    // assignment, so a posedge read here sees the PRE-EDGE state -- which is
    // exactly the state the engine's own `jitter_cnt` increment is decided
    // from. Reading at the negedge would shift every cycle's verdict by one
    // and no longer be comparable with the counter it is decomposing.
    for (i = 0; i < ncyc; i = i + 1) begin
      @(posedge clk);
      cyc = cyc + 1;
      if (warm_from == 0 && dut.u_eng.hdr_done) begin
        warm_from = cyc + warmup;
        mid       = warm_from + (ncyc - warm_from) / 2;
      end
      if (dut.u_eng.primed)      primed_seen = 1'b1;
      if (dut.u_eng.config_err)  cfgerr_seen = 1'b1;
      if (dut.u_eng.l_live[lane]) live_seen  = 1'b1;
      else if (live_seen)         halt_seen  = 1'b1;

      r_cyc[head] = cyc;
      r_pst[head] = dut.u_eng.pst;
      r_pl[head]  = dut.u_eng.pl;
      r_win[head] = dut.u_eng.winner;
      r_hd[head]  = dut.u_eng.l_actv[l_head];
      r_sum[head] = in_iv ? iv_sum : -1;
      head = (head + 1) % RING;

      // ---- interval-independent readings, inside the window only -------
      if (warm_from > 0 && cyc > warm_from) begin
        if (rdy)     n_rdy = n_rdy + 1;
        if (blocked) begin
          n_blk    = n_blk + 1;
          cur_free = cur_free + 1;
          if (cur_free > free_run) begin
            free_run = cur_free;
            free_at  = cyc;
          end
        end else begin
          cur_free = 0;
        end
      end

      // ---- interval bookkeeping ---------------------------------------
      if (in_iv) begin
        // ⭐ the three buckets, mutually exclusive by construction
        if (dut.u_eng.st != 0)        iv_exec = iv_exec + 1;
        else if (!(dut.u_eng.winner_v
                   && dut.u_eng.winner == lane[2:0])) begin
          iv_gap = iv_gap + 1;
          // ⭐ which kind of idle: refill queueing, or someone else's turn
          if (dut.u_eng.winner_v
              && !dut.u_eng.l_actv[dut.u_eng.hix[dut.u_eng.winner]])
            iv_rq = iv_rq + 1;
          else
            iv_dd = iv_dd + 1;
        end
        if (blocked) begin
          iv_sum  = iv_sum + 1;
          cur_run = cur_run + 1;
          if (cur_run > iv_run) iv_run = cur_run;
        end else begin
          cur_run = 0;
        end

        if (dispatch) begin
          // ⭐ COMPLETE interval. Only intervals that OPENED inside the
          // asserted window are counted, so nothing from the transient can
          // set a maximum -- the error that made 500 and 1000 both read 7.
          if (warm_from > 0 && iv_start > warm_from) begin
            n_iv = n_iv + 1;
            if (iv_start < mid) n_iv_h1 = n_iv_h1 + 1;
            else                n_iv_h2 = n_iv_h2 + 1;
            if (iv_sum > J_PREREG) n_fire = n_fire + 1;
            if (iv_sum > max_sum) begin
              max_sum    = iv_sum;
              max_sum_at = cyc;
              dump_chain;
            end
            if (iv_run > max_run) max_run = iv_run;
            if (iv_gap > max_gap) max_gap = iv_gap;
            if (iv_dd > max_dd) max_dd = iv_dd;
            if (iv_rq > max_rq) begin
              max_rq    = iv_rq;
              max_rq_at = cyc;
            end
            if ((iv_sum + iv_gap) > max_full) begin
              max_full    = iv_sum + iv_gap;
              max_full_at = cyc;
            end
            if ((cyc - iv_start) > max_wall) begin
              max_wall    = cyc - iv_start;
              max_wall_at = cyc;
            end
          end
          in_iv = 1'b0;
        end else if (!rdy) begin
          // ⛔ THE RELEASE WAS WITHDRAWN, NOT SERVED. `ready` drops without a
          // dispatch when the lane ARMS (an armed lane with no timeout is not
          // ready on its timestamp), so this interval never had a dispatch to
          // wait for. Attributing its cycles to a wait would invent one.
          // ⚠ Dropped intervals are COUNTED and printed: a large drop
          // fraction means this instrument is not seeing the behaviour it
          // claims to measure, which is a reading problem, not a pass.
          if (warm_from > 0 && iv_start > warm_from) n_drop = n_drop + 1;
          in_iv = 1'b0;
        end
      end else if (rdy && !prev_ready) begin
        in_iv = 1'b1; iv_start = cyc; iv_sum = 0; iv_run = 0; cur_run = 0;
        iv_gap = 0; iv_exec = 0; iv_rq = 0; iv_dd = 0;
        if (blocked) begin iv_sum = 1; iv_run = 1; cur_run = 1; end
      end

      // a lane already ready at the first sampled cycle has no observable
      // release edge, so it opens no interval -- correct, and counted as
      // neither a reading nor a drop.
      prev_ready = rdy;
    end

    // ---- the verdict, with its preconditions ---------------------------
    $display();
    $display("================ tb_jlane: lane %0d ================", lane);
    $display("  PRECONDITIONS");
    $display("    image bytes loaded      : %0d", img_bytes);
    // ⛔⛔ THE RUN EXECUTED THE REQUESTED NUMBER OF CYCLES. Added after the
    // dump task was found sharing the run loop's index, which made the bench
    // run 2.3x longer than `NCYC` on the lanes that printed. An uncontrolled
    // run length invalidates the window precondition it is supposed to feed.
    $display("    cycles run vs requested : %0d / %0d %0s", cyc, ncyc,
             (cyc == ncyc) ? "ok"
             : "*** FAIL -- the run loop did not execute NCYC times");
    $display("    window (cycles)         : %0d  (need >= %0d) %0s",
             (warm_from > 0 && cyc > warm_from) ? (cyc - warm_from) : 0,
             MIN_WINDOW,
             (warm_from > 0 && cyc > warm_from
              && (cyc - warm_from) >= MIN_WINDOW) ? "ok" : "*** FAIL");
    $display("    warm-up ended at cycle  : %0d %0s", warm_from,
             (warm_from > 0 && warm_from < cyc) ? "ok"
             : "*** FAIL (never primed, or warm-up outruns the run)");
    $display("    lane live observed      : %0b %0s", live_seen,
             live_seen ? "ok" : "*** FAIL");
    $display("    lane halted mid-run     : %0b %0s", halt_seen,
             halt_seen ? "*** FAIL (timeout halt -- not a timing reading)"
                       : "ok");
    $display("    primed observed         : %0b %0s", primed_seen,
             primed_seen ? "ok" : "*** FAIL");
    $display("    config_err observed     : %0b %0s", cfgerr_seen,
             cfgerr_seen ? "*** FAIL" : "ok");
    $display("    complete intervals      : %0d  (need >= %0d) %0s",
             n_iv, MIN_INTERVALS, (n_iv >= MIN_INTERVALS) ? "ok" : "*** FAIL");
    $display("    withdrawn (dropped)     : %0d", n_drop);
    // ⛔ STATIONARITY: the two halves of the window must behave alike. The
    // factor of 3 is a floor on sameness, not a statistical test -- it exists
    // to catch the 6-vs-4457 case, which is a factor of 700.
    $display("    intervals 1st/2nd half  : %0d / %0d %0s", n_iv_h1, n_iv_h2,
             (n_iv_h1 > 0 && n_iv_h2 > 0
              && n_iv_h2 <= 3 * n_iv_h1 && n_iv_h1 <= 3 * n_iv_h2)
             ? "ok" : "*** FAIL -- not stationary, the window is inside a transient");
    // ⛔ CONVERGENCE: a strictly larger maximum appearing in the second half
    // means the search had not finished, so the number is a floor on a floor.
    $display("    last new max at cycle   : %0d  (window midpoint %0d) %0s",
             max_sum_at, mid,
             (max_sum == 0 || (mid > 0 && max_sum_at < mid))
             ? "ok" : "*** FAIL -- a new maximum appeared in the second half");
    // ⭐ WHY the intervals are few, if they are. A lane that is ready in
    // nearly every cycle of the window is BACKLOGGED -- not keeping up with
    // its own period -- so it has almost no release edges to measure between.
    // That is a different finding from "a quiet lane", and the sweep must be
    // able to tell them apart rather than printing one shortfall for both.
    $display("    ready cycles in window  : %0d of %0d", n_rdy,
             (warm_from > 0 && cyc > warm_from) ? (cyc - warm_from) : 0);
    if (n_iv < MIN_INTERVALS)
      $display("    ⚠ diagnosis: %0s",
               (warm_from > 0 && cyc > warm_from
                && n_rdy > ((cyc - warm_from) * 9) / 10)
               ? "BACKLOGGED -- ready almost always, so release edges are rare"
               : "few releases, and the lane is NOT continuously ready");
    $display("  MEASURED");
    $display("    J_lane (max sum)        : %0d  at cycle %0d",
             max_sum, max_sum_at);
    $display("    max single run          : %0d", max_run);
    // ⛔⛔ R1'S DECIDING NUMBERS. `gap` is the cycle class that belongs to
    // NEITHER model: idle engine, another lane winner-blocked on its refill,
    // so nothing executes (pyRTA charges nothing) and the winner is not me
    // (`sum` skips it). If it is non-zero, the bound RTA needs is `sum + gap`,
    // not `sum`.
    $display("    max gap (idle, not mine): %0d   = RQ %0d + DD %0d (per-interval maxima, not additive)",
             max_gap, max_rq, max_dd);
    // ⛔⛔ THE NUMBER BOTH THEOREMS TURN ON. RQ is idle time spent refilling
    // for a lane that outranks me: uncounted by pyRTA (nothing executes) and
    // by `sum` (the winner is not me). The D* theorem says RQ = 0 for
    // d_min >= D*; R1 measured it at 40 below D*.
    $display("    max RQ (refill queueing): %0d  at cycle %0d",
             max_rq, max_rq_at);
    $display("    max DD (others' turn)   : %0d  -- EDF ordering, not refill",
             max_dd);
    $display("    max FULL non-exec wait  : %0d  at cycle %0d",
             max_full, max_full_at);
    $display("      ^ sum + gap. This is the delay a response-time analysis");
    $display("        must charge as jitter, because no job executes during");
    $display("        it -- EDF interference is the separate `exec` class.");
    $display("    intervals over prereg   : %0d", n_fire);
    $display("    wall release->dispatch  : %0d  at cycle %0d",
             max_wall, max_wall_at);
    $display("      ^ NOT bounded by the hypothesis: includes EDF interference");
    $display("    blocked cycles in window: %0d", n_blk);
    $display("    longest blocked run     : %0d  at cycle %0d",
             free_run, free_at);
    $display("      ^ interval-INDEPENDENT; not the pre-registered quantity");
    $display("    engine aggregate jitter_max : %0d", dut.u_eng.jitter_max);
    $display("      ^ any-winner-blocked run length, engine-wide, NOT per-lane");
    // ⭐⭐ A CONSISTENCY CHECK AGAINST THE RTL'S OWN COUNTER. A consecutive
    // run of blocked-with-winner==lane is also a consecutive run of
    // any-winner-blocked, so `max_run` CANNOT exceed `jitter_max`. If it
    // does, this bench's predicate is reading something the engine does not
    // call a stall, and the number is void -- the cheapest available check
    // that the instrument is wired to the right event.
    if (free_run > dut.u_eng.jitter_max) begin
      $display("  *** VOID: longest blocked run %0d exceeds the engine",
               free_run);
      $display("      aggregate %0d. Impossible if this predicate is the",
               dut.u_eng.jitter_max);
      $display("      engine's own stall condition -- instrument is wrong.");
    end
    if (max_run > dut.u_eng.jitter_max) begin
      $display("  *** VOID: per-lane run %0d exceeds the engine aggregate %0d",
               max_run, dut.u_eng.jitter_max);
      $display("      That is impossible if this predicate is the engine's own");
      $display("      stall condition, so the instrument is wrong, not the");
      $display("      design. The number above is void.");
    end else begin
      $display("    consistency: max_run %0d <= jitter_max %0d  ok",
               max_run, dut.u_eng.jitter_max);
    end
    $display("  JLANE lane=%0d sum=%0d run=%0d wall=%0d iv=%0d drop=%0d fire=%0d win=%0d agg=%0d rdy=%0d blk=%0d free=%0d gap=%0d full=%0d rq=%0d dd=%0d",
             lane, max_sum, max_run, max_wall, n_iv, n_drop, n_fire,
             (warm_from > 0 && cyc > warm_from) ? (cyc - warm_from) : 0,
             dut.u_eng.jitter_max, n_rdy, n_blk, free_run, max_gap,
             max_full, max_rq, max_dd);
    $finish;
  end

endmodule

`default_nettype wire
