/* tb_csat.v -- INTER-DISPATCH SPACING UNDER SATURATION.
 *
 * ⛔⛔ THE HYPOTHESIS AND THE FALSIFIER ARE PRE-REGISTERED IN
 * `docs/PREREG_C_SAT.md`, COMMITTED BEFORE THIS FILE EXISTED (2bdc109).
 * `min inter-dispatch spacing = 2`; falsifier: `3`. Read that document before
 * reading a number out of here.
 *
 * WHAT IT MEASURES, and why the number already on record cannot answer it.
 * `tb_smoke` reports `svc_cycles / svc_jobs = 688 / 344 = 2.00`, counting
 * cycles where `st != ST_IDLE`. That is the engine's OCCUPANCY per job. The
 * dispatch FSM is a THREE-state cycle --
 *     ST_IDLE --(cond)--> ST_DRIVE --> ST_WB --> ST_IDLE
 * -- and `ST_WB` assigns `st <= ST_IDLE` UNCONDITIONALLY, so the next
 * dispatch decision cannot be taken until the cycle after writeback. A
 * three-state cycle delivers one job every three cycles however many of those
 * cycles are labelled service. This bench measures the SPACING between
 * dispatch decisions, which is the quantity response-time analysis charges as
 * `C`.
 *
 * ⭐ THE MINIMUM, NOT THE MEAN. Refill queueing and EDF idleness can only make
 * a spacing LARGER, so one observed spacing of 2 anywhere refutes `C = 3`. A
 * mean would measure the program's arrival rate instead.
 *
 * ⛔⛔ AND THE MINIMUM IS ONLY EVIDENCE IF THE FLOOR WAS EXERCISED. `3` on a
 * program whose lanes arrive 3 cycles apart says nothing about the engine. So
 * the deciding number is `btbmin`: the minimum spacing taken ONLY over pairs
 * whose predecessor had a BACK-TO-BACK OPPORTUNITY -- some other live lane
 * already ready with a valid head during the predecessor's `ST_WB` cycle, so a
 * dispatch was eligible before the current one finished. `btb` counts those
 * opportunities and is a PRECONDITION, not a statistic.
 *
 * ⚠ IT REPORTS A FLOOR ON THE FLOOR: finitely many arms, one phase alignment
 * each, and RTL simulation rather than the post-synthesis path.
 */

`default_nettype none
`timescale 1ns / 1ps

`include "test/imgload.vh"
module tb_csat;

  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00, uio_in = 8'h00;
  wire [7:0] uo_out, uio_out, uio_oe;

  localparam integer IMG_MAX  = 256;
  localparam integer PIN_PROG = 7, PIN_PTR = 5, PIN_WR = 6;
  localparam integer NL       = 5;
  localparam integer HMAX     = 16;

  // ---- the pre-registered constants, named here so a run cannot drift ----
  localparam integer DELTA_PREREG = 2;        // the hypothesis
  localparam integer MIN_WINDOW   = 100000;
  localparam integer MIN_DISP     = 1000;
  localparam integer MIN_BTB      = 100;

  reg  [7:0] img [0:IMG_MAX-1];
  integer    img_bytes, i, cyc, ncyc, warmup, warm_from, mid;
  reg [8*256-1:0] imgfile;

  // ---- spacing state ----------------------------------------------------
  integer    last_disp, n_disp, n_sp, dmin, dmax, dsum;
  // per-opcode spacing: the MAX over FSM-limited back-to-back gaps, which is
  // the quantity `docs/PREREG_C_CLOCKED.md` fixes the decision rule on.
  integer    last_op;
  integer    op_max [0:7];
  integer    op_max_at [0:7];
  integer    op_n [0:7];
  integer    oi, op_tot, occ, occ_op;
  integer    btb, btb_min, btb_min_at, btb_h1, btb_h2;
  reg        wb_elig;
  integer    hist [0:HMAX-1];
  // ⛔⛔ THE CROSS-CHECK'S OWN COUNTER. `n_disp` is the `ST_IDLE` arm's
  // condition read literally; `n_trans` counts `st` 0 -> 1 edges. They are two
  // independent detections of the SAME event and must agree exactly. A
  // predicate that drifts from the FSM it claims to mirror is how this project
  // got a per-interval sum of 1870 against a bound of 9 -- so the instrument
  // is checked against the design rather than trusted.
  integer    n_trans, prev_st;
  // ⛔ AND ITS OWN LOOP INDEX. `tb_jlane`'s dump task shared `i` with the run
  // loop and the bench ran 2.3x longer than NCYC. Any second loop gets its own.
  integer    jb;
  reg        live_seen, primed_seen, cfgerr_seen, halt_seen, ovr_seen;
  reg  [4:0] live_mask;

  always #10 clk = ~clk;

  parameter integer SPL_CFG = 2;

  tt_um_protocol_emulator #(.SPL(SPL_CFG)) dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );

`include "test/progress.vh"
`include "test/clocked_conform.vh"

  // ⛔⛔ `pe_engine.v`'s ST_IDLE ARM READ LITERALLY. Every term earns its place:
  //   `primed && !config_err` gate the whole arm, so a cycle before priming is
  //     not a dispatch opportunity;
  //   `!l_armed[winner]` because an armed winner arriving ready takes the
  //     TIMEOUT-HALT branch, not the dispatch branch;
  //   `l_actv[hix[winner]]` is the dispatch condition itself -- without it the
  //     cycle is the prefetch-miss stall, not a dispatch.
  // ⛔ THE ENGINE'S OWN HEAD INDEX, NEVER A COPY. Four private copies of this
  // index have been found in two benches, one of which produced a whole
  // published column that had to be retracted. `hix` is depth-independent and
  // removes the class.
  wire       disp = dut.u_eng.primed && !dut.u_eng.config_err
                    && (dut.u_eng.st == 0) && dut.u_eng.winner_v
                    && !dut.u_eng.l_armed[dut.u_eng.winner]
                    && dut.u_eng.l_actv[dut.u_eng.hix[dut.u_eng.winner]];

  // ⭐ ARM IDENTITY, DECODED FROM THE FILE THAT ACTUALLY LOADED. A run
  // attributed to the wrong arm is a wrong result that looks right. Layout
  // counted from `pe_isa.HDR_FIELDS`, 47 bits in 6 bytes MSB-aligned:
  //   [47:44] pin [43:40] clkpin [39] mode [38:29] t [28:25] C
  //   [24:17] D_sched [16:9] D_tol [8:1] base [0] spare
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
      $display("tb_csat: FATAL -- +IMG=<file> is required.");
      $finish;
    end
    if (!$value$plusargs("NBYTES=%d", img_bytes)) begin
      $display("tb_csat: FATAL -- +NBYTES=<n> is required. A program that");
      $display("  never loaded dispatches nothing, and 'no dispatches' is");
      $display("  not distinguishable from a saturated engine by the number");
      $display("  alone -- which is how a probe in this project produced the");
      $display("  OPPOSITE of the right answer.");
      $finish;
    end
    if (!$value$plusargs("NCYC=%d", ncyc))     ncyc = 200000;
    if (!$value$plusargs("WARMUP=%d", warmup)) warmup = 20000;
    $readmemh(imgfile, img);
    `PE_REQUIRE_IMG_LOADED(imgfile)
    $display("# csat img=%0s bytes=%0d ncyc=%0d warmup=%0d prereg=%0d SPL=%0d",
             imgfile, img_bytes, ncyc, warmup, DELTA_PREREG, SPL_CFG);
    echo_arm;

    for (i = 0; i < HMAX; i = i + 1) hist[i] = 0;
    cyc = 0; warm_from = 0; mid = 0;
    last_disp = 0; n_disp = 0; n_sp = 0; dmin = 0; dmax = 0; dsum = 0;
    last_op = 0; occ = 0; occ_op = 0;
    for (oi = 0; oi < 8; oi = oi + 1) begin
      op_max[oi] = 0; op_max_at[oi] = 0; op_n[oi] = 0;
    end
    btb = 0; btb_min = 0; btb_min_at = 0; btb_h1 = 0; btb_h2 = 0;
    wb_elig = 1'b0;
    n_trans = 0; prev_st = 0;
    live_seen = 1'b0; primed_seen = 1'b0; cfgerr_seen = 1'b0;
    halt_seen = 1'b0; ovr_seen = 1'b0; live_mask = 5'd0;

    repeat (4) @(negedge clk);
    rst_n = 1;
    @(negedge clk);

    // ---- load ----------------------------------------------------------
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
    uio_in = 8'hFF;

    // ---- run -----------------------------------------------------------
    // ⭐ SAMPLED AT POSEDGE, ON PURPOSE. The engine's regs use non-blocking
    // assignment, so a posedge read sees the PRE-EDGE state -- the state the
    // FSM's own next-state decision is taken from. A negedge read would shift
    // every cycle's verdict by one and the spacings would not be the FSM's.
    for (i = 0; i < ncyc; i = i + 1) begin
      @(posedge clk);
      cyc = cyc + 1;
      if (warm_from == 0 && dut.u_eng.hdr_done) begin
        warm_from = cyc + warmup;
        mid       = warm_from + (ncyc - warm_from) / 2;
      end
      if (dut.u_eng.primed)     primed_seen = 1'b1;
      if (dut.u_eng.config_err) cfgerr_seen = 1'b1;
      if (dut.u_eng.sticky_ovr) ovr_seen    = 1'b1;
      for (jb = 0; jb < NL; jb = jb + 1) begin
        if (dut.u_eng.l_live[jb]) begin
          live_seen      = 1'b1;
          live_mask[jb]  = 1'b1;
        end else if (live_mask[jb]) begin
          halt_seen      = 1'b1;
        end
      end

      // ---- the cross-check's independent detection of a dispatch -------
      if (prev_st == 0 && dut.u_eng.st != 0 && warm_from > 0 && cyc > warm_from)
        n_trans = n_trans + 1;

      // ---- BACK-TO-BACK OPPORTUNITY, observed in the predecessor's WB --
      // ⛔ `jb != cur` IS LOAD-BEARING. During `ST_WB` the timestamp add is
      // non-blocking, so `ready[cur]` is STILL HIGH and `winner` may still be
      // `cur` -- a lane that is about to stop being ready. Counting it would
      // make this flag true in nearly every writeback and the precondition
      // would certify itself. The question is whether ANOTHER lane was
      // already eligible.
      if (dut.u_eng.st == 2) begin
        for (jb = 0; jb < NL; jb = jb + 1) begin
          if (jb != dut.u_eng.cur
              && dut.u_eng.l_live[jb] && dut.u_eng.ready[jb]
              && !dut.u_eng.l_armed[jb]
              && dut.u_eng.l_actv[dut.u_eng.hix[jb]])
            wb_elig = 1'b1;
        end
      end

      // ---- per-opcode OCCUPANCY, which is the only service-only measure --
      // ⛔⛔ A MAX OVER *GAPS* DOES NOT MEASURE `C`, and the first version of
      // this tried. It took the maximum back-to-back gap per opcode over the
      // same `wb_elig` qualification `btb_min` uses -- but that qualification
      // holds only at the gap's START, and eligibility can lapse inside it.
      // MEASURED on `five_image`, an UNCLOCKED program: max 11 for OP_LEVEL
      // and OP_REARM, which would have read as `C = 11` on a design that is
      // perfectly fine. A baseline that fails is how an instrument says it is
      // measuring the wrong thing.
      // ⭐ OCCUPANCY IS IMMUNE TO ARRIVAL LIMITS: cycles the engine spends
      // with `st != ST_IDLE` for one dispatch. The FSM is ST_IDLE -> ST_DRIVE
      // -> ST_WB, so this is 2 for every action and `C` is that plus the
      // mandatory idle cycle = 3. An opcode that needed more engine time --
      // which is the risk the clocked scheme introduces -- shows up here and
      // nowhere else.
      if (dut.u_eng.st != 2'd0) begin
        occ = occ + 1;
        occ_op = dut.u_eng.a_op;
      end else if (occ > 0) begin
        if (occ > op_max[occ_op]) begin
          op_max[occ_op]    = occ;
          op_max_at[occ_op] = cyc;
        end
        op_n[occ_op] = op_n[occ_op] + 1;
        occ = 0;
      end

      // ---- spacing bookkeeping ----------------------------------------
      if (disp && warm_from > 0 && cyc > warm_from) begin
        n_disp = n_disp + 1;
        if (last_disp > 0) begin
          n_sp = n_sp + 1;
          dsum = dsum + (cyc - last_disp);
          if (dmin == 0 || (cyc - last_disp) < dmin) dmin = cyc - last_disp;
          if ((cyc - last_disp) > dmax) dmax = cyc - last_disp;
          if ((cyc - last_disp) < HMAX) hist[cyc - last_disp] =
                                            hist[cyc - last_disp] + 1;
          else hist[HMAX-1] = hist[HMAX-1] + 1;
          // ⭐ THE DECIDING NUMBER: only spacings whose predecessor had a
          // successor already eligible are FSM-limited rather than
          // arrival-limited.
          if (wb_elig) begin
            btb = btb + 1;
            if (cyc < mid) btb_h1 = btb_h1 + 1;
            else           btb_h2 = btb_h2 + 1;
            if (btb_min == 0 || (cyc - last_disp) < btb_min) begin
              btb_min    = cyc - last_disp;
              btb_min_at = cyc;
            end
          end
        end
        last_disp = cyc;
        last_op   = dut.u_eng.a_op;   // whose service the NEXT gap measures
        wb_elig   = 1'b0;
      end
      prev_st = dut.u_eng.st;
    end

    // ---- the verdict, with its preconditions ---------------------------
    $display();
    $display("================ tb_csat: inter-dispatch spacing ============");
    $display("  PRECONDITIONS");
    $display("    image bytes loaded      : %0d", img_bytes);
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
    $display("    primed observed         : %0b %0s", primed_seen,
             primed_seen ? "ok" : "*** FAIL");
    $display("    config_err observed     : %0b %0s", cfgerr_seen,
             cfgerr_seen ? "*** FAIL" : "ok");
    $display("    a lane halted mid-run   : %0b %0s", halt_seen,
             halt_seen ? "*** FAIL (timeout halt -- not a timing reading)"
                       : "ok");
    $display("    dispatch decisions      : %0d  (need >= %0d) %0s",
             n_disp, MIN_DISP, (n_disp >= MIN_DISP) ? "ok" : "*** FAIL");
    // ⛔⛔ THE INSTRUMENT CROSS-CHECK. Two independent detections of one
    // event: the ST_IDLE arm's condition, and the `st` 0 -> 1 edge it causes.
    // ⚠ THEY ARE OFF BY AT MOST ONE BY CONSTRUCTION, because a decision taken
    // in the window's LAST cycle has its transition outside it. Anything
    // larger means the predicate is not the FSM's.
    $display("    decisions vs st 0->1    : %0d / %0d %0s", n_disp, n_trans,
             ((n_disp - n_trans) <= 1 && (n_trans - n_disp) <= 1) ? "ok"
             : "*** VOID -- the predicate is not the FSM's dispatch");
    $display("    back-to-back opportunities: %0d  (need >= %0d) %0s",
             btb, MIN_BTB, (btb >= MIN_BTB) ? "ok"
             : "*** FAIL -- the floor was NOT exercised, so a spacing of 3");
    if (btb < MIN_BTB)
      $display("      ^ would mean the lanes arrived 3 apart, NOT that the");
    if (btb < MIN_BTB)
      $display("        engine cannot do better. NO READING (prereg 5.3).");
    $display("    btb 1st/2nd half        : %0d / %0d %0s", btb_h1, btb_h2,
             (btb_h1 > 0 && btb_h2 > 0
              && btb_h2 <= 3 * btb_h1 && btb_h1 <= 3 * btb_h2)
             ? "ok" : "*** FAIL -- not stationary");
    $display("    last new btb minimum at : %0d  (window midpoint %0d) %0s",
             btb_min_at, mid,
             (btb_min == 0 || (mid > 0 && btb_min_at < mid))
             ? "ok" : "*** FAIL -- a new minimum appeared in the second half");
    $display("    sticky_ovr observed     : %0b  (recorded, not a failure)",
             ovr_seen);
    $display("  MEASURED");
    $display("    btbmin (THE NUMBER)     : %0d", btb_min);
    // ⭐⭐ THE PER-OPCODE MAXIMUM, and the verdict the pre-registration fixed
    // BEFORE this ran: < 3 means the engine is faster than charged and we
    // KEEP CHARGING 3; = 3 is unchanged; > 3 is FORBIDDEN and stops
    // everything until every margin resting on C = 3 is re-quoted.
    $display();
    $display("    per-opcode MAX OCCUPANCY (cycles with st != ST_IDLE);");
    $display("    C is this plus the mandatory idle cycle, so 2 means C = 3:");
    $display("      %-9s %-6s %-7s %s", "opcode", "gaps", "max", "verdict");
    for (oi = 0; oi < 8; oi = oi + 1) begin
      if (op_n[oi] > 0)
        $display("      op %0d      %-6d %-7d %0s", oi, op_n[oi], op_max[oi],
                 (op_max[oi] > 2) ? "*** FAIL -- C EXCEEDS 3, FORBIDDEN"
                 : (op_max[oi] == 2) ? "ok -- C = 3, the charged value"
                                     : "ok -- faster than charged (keep 3)");
      else
        $display("      op %0d      %-6d %-7s %0s", oi, 0, "-",
                 "not dispatched in this arm");
      // ⛔ NO TALLY VARIABLE: this bench reports by PRINTING `*** FAIL`,
      // which is what the sweep's per-arm grep matches. Adding a counter
      // here would be a second verdict mechanism in one bench.
    end
    // ⛔ AND AN ANTI-VACUITY CHECK ON THE BREAKDOWN ITSELF: if no opcode
    // recorded a single FSM-limited gap, the per-opcode verdict above is
    // vacuous and must not read as a pass.
    op_tot = 0;
    for (oi = 0; oi < 8; oi = oi + 1) op_tot = op_tot + op_n[oi];
    $display("      jobs attributed: %0d %0s", op_tot,
             (op_tot > 0) ? "ok -- the breakdown has subjects"
             : "*** FAIL -- no job was attributed, so the per-opcode verdict is vacuous");
    $display("      ^ minimum spacing where a successor was ALREADY eligible");
    $display("        during the predecessor's ST_WB cycle. This is the FSM's");
    $display("        floor and therefore the C that RTA must charge.");
    $display("    min spacing (all pairs) : %0d", dmin);
    $display("    max spacing             : %0d", dmax);
    if (n_sp > 0)
      $display("    mean spacing x100       : %0d  (arrival-limited, NOT C)",
               (dsum * 100) / n_sp);
    $display("    spacings counted        : %0d", n_sp);
    $display("    histogram (spacing: n)  :");
    for (i = 1; i < HMAX-1; i = i + 1)
      if (hist[i] > 0) $display("      spacing %0d : %0d", i, hist[i]);
    if (hist[HMAX-1] > 0)
      $display("      spacing >= %0d : %0d", HMAX-1, hist[HMAX-1]);
    $display("  VERDICT vs docs/PREREG_C_SAT.md");
    $display("    hypothesis  btbmin = %0d", DELTA_PREREG);
    $display("    measured    btbmin = %0d", btb_min);
    if (btb >= MIN_BTB && btb_min > DELTA_PREREG)
      $display("    *** FALSIFIER FIRED: the FSM cannot dispatch faster than");
    if (btb >= MIN_BTB && btb_min > DELTA_PREREG)
      $display("        %0d cycles with a successor already eligible.", btb_min);
    if (btb >= MIN_BTB && btb_min == DELTA_PREREG)
      $display("    the falsifier did not fire: C = 2 stands.");
    // ⛔ IMPOSSIBLE-BY-CONSTRUCTION CHECK. `dmin` is a minimum over a SUPERSET
    // of the pairs `btb_min` is taken over, so it can be smaller but never
    // larger. If it is larger the bookkeeping is wrong and both are void.
    if (btb_min > 0 && dmin > btb_min) begin
      $display("  *** VOID: min over all pairs (%0d) exceeds min over the",
               dmin);
      $display("      back-to-back subset (%0d). The subset is a SUBSET, so",
               btb_min);
      $display("      that is impossible -- the bookkeeping is wrong.");
    end
    $display("  CSAT img=%0s btbmin=%0d dmin=%0d dmax=%0d btb=%0d nsp=%0d ndisp=%0d ntrans=%0d win=%0d halt=%0b cfgerr=%0b ovr=%0b h1=%0d h2=%0d at=%0d mid=%0d",
             imgfile, btb_min, dmin, dmax, btb, n_sp, n_disp, n_trans,
             (warm_from > 0 && cyc > warm_from) ? (cyc - warm_from) : 0,
             halt_seen, cfgerr_seen, ovr_seen, btb_h1, btb_h2,
             btb_min_at, mid);
    $finish;
  end

endmodule

`default_nettype wire
