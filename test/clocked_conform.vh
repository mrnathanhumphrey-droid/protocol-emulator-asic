/* clocked_conform.vh -- LAYER B of the bench watchdog: exact per-action
 * conformance of the RTL to the GOLDEN MODEL.
 *
 * ⛔⛔ THE MODEL IS THE SINGLE AUTHORITY FOR THE COUNTS. This file performs NO
 * arithmetic at all -- not even the SHIFT/SHIFTIN off-by-one (`OP_SHIFT`
 * counts `a_cnt + 1` bits, `OP_SHIFTIN` counts `a_cnt`). It looks the answer
 * up in `clocked_bounds.vh`, which `model/clocked_phase.py` GENERATES by
 * running the machine and MEASURING. "2n+1" restated in Verilog would be the
 * duplicated-constant shape that has cost this project a published column.
 *
 * ⛔ IT SHIPS WITH THE CLOCKED RTL AND NOT BEFORE. Its "is this a clocked
 * action" predicate is `clk_real & level`, which only MEANS self-clocked in
 * this engine; landed earlier it would have mis-fired on the pre-clocked
 * corpus. An `ifdef` nobody defines would have been worse -- a check that
 * never runs is the very thing layer A's header is about.
 *
 * ⭐ WHAT IT CAUGHT, on the build that preceded this one: 144 failures, naming
 * the defect exactly -- "lane 0 op=1 cnt=7 at pc=33 took 1 dispatch(es), the
 * model says 16". Layer A reported 0, correctly, because nothing hung. That
 * split is why there are two layers.
 *
 * ⛔ EVERY FORMAT STRING IS ONE PLAIN LITERAL, AND EVERY FAILURE LINE
 * CARRIES THE `*** FAIL` PREFIX the sweep actually greps for. Brace-concatenated formats
 * printed NOTHING here while the counter beside them reached 144 --
 * `model/gate_bench_lint.py` now refuses them.
 *
 * USAGE:  `include "test/clocked_conform.vh"   // after `include progress.vh
 */
`include "test/clocked_bounds.vh"

integer cb_n   [0:7];      // dispatches on the current action
integer cb_pc  [0:7];
integer cb_op  [0:7];
integer cb_cnt [0:7];
integer cb_ck  [0:7];
integer cb_fails, cb_acts, cb_k;

initial begin
  for (cb_k = 0; cb_k < 8; cb_k = cb_k + 1) begin
    cb_n[cb_k] = 0;  cb_pc[cb_k] = -1;  cb_op[cb_k] = -1;
    cb_cnt[cb_k] = 0;  cb_ck[cb_k] = 0;
  end
  cb_fails = 0;  cb_acts = 0;
end

always @(posedge dut.clk) begin
  if (dut.rst_n !== 1'b1) begin
    for (cb_k = 0; cb_k < 8; cb_k = cb_k + 1) begin
      cb_n[cb_k] = 0;  cb_pc[cb_k] = -1;
    end
  end else if (dut.u_eng.st === 2'd2 && dut.u_eng.cur < 8) begin
    // ST_WB, as the LITERAL 2'd2: `src/pe_engine.v` has
    // `localparam [1:0] ST_IDLE = 2'd0, ST_DRIVE = 2'd1, ST_WB = 2'd2`.
    // A hierarchical reference to that localparam compiles and NEVER matches.
    if (dut.u_eng.a_op === 3'd7 && dut.u_eng.a_lvl === 1'b0) begin
      cb_n[dut.u_eng.cur]  = 0;                  // the chaining re-arm
      cb_pc[dut.u_eng.cur] = dut.u_eng.l_pc[dut.u_eng.cur];
    end else if (cb_pc[dut.u_eng.cur] !== dut.u_eng.l_pc[dut.u_eng.cur]) begin
      if (cb_pc[dut.u_eng.cur] !== -1 && cb_ck[dut.u_eng.cur]) begin
        cb_acts = cb_acts + 1;
        // ⭐⭐ A ONE-SHOT LIVENESS LINE, because `final` CANNOT BE RELIED ON
        // HERE: with two included files each declaring one, Verilator ran
        // only the first and this layer's summary never printed -- a
        // checker that is silent whether or not it ran, which is the exact
        // failure mode layer A's header is about. ⇒ Non-vacuity is now
        // visible from the FIRST check instead of at the end: no line at
        // all means layer B never saw a clocked action.
        if (cb_acts == 1)
          $display("  clocked_conform[B]: live -- checking clocked actions against the model");
        if (ck_expect(cb_op[dut.u_eng.cur], cb_cnt[dut.u_eng.cur]) < 0) begin
          $display("*** FAIL clocked_conform: no model entry for op=%0d cnt=%0d -- the generated table and the ISA disagree about what a clocked action is", cb_op[dut.u_eng.cur], cb_cnt[dut.u_eng.cur]);
          cb_fails = cb_fails + 1;
        end else if (cb_n[dut.u_eng.cur] !== ck_expect(cb_op[dut.u_eng.cur], cb_cnt[dut.u_eng.cur])) begin
          $display("*** FAIL clocked_conform: lane %0d op=%0d cnt=%0d at pc=%0d took %0d dispatch(es), the model says %0d", dut.u_eng.cur, cb_op[dut.u_eng.cur], cb_cnt[dut.u_eng.cur], cb_pc[dut.u_eng.cur], cb_n[dut.u_eng.cur], ck_expect(cb_op[dut.u_eng.cur], cb_cnt[dut.u_eng.cur]));
          cb_fails = cb_fails + 1;
        end
      end
      cb_pc[dut.u_eng.cur]  = dut.u_eng.l_pc[dut.u_eng.cur];
      cb_n[dut.u_eng.cur]   = 1;
      cb_op[dut.u_eng.cur]  = dut.u_eng.a_op;
      cb_cnt[dut.u_eng.cur] = dut.u_eng.a_cnt;
      // ⛔ READ FROM THE DUT, never inferred from the image: `clk_real & level`
      // is the engine's own trigger, so the bench cannot disagree with the
      // silicon about which actions this layer owns.
      cb_ck[dut.u_eng.cur]  = (dut.u_eng.clk_real === 1'b1 &&
                               dut.u_eng.a_lvl === 1'b1 &&
                               (dut.u_eng.a_op === 3'd1 ||
                                dut.u_eng.a_op === 3'd2)) ? 1 : 0;
    end else begin
      cb_n[dut.u_eng.cur] = cb_n[dut.u_eng.cur] + 1;
    end
  end
end

/* =======================================================================
 * G1 -- INTER-DISPATCH GAP CONFORMANCE, and why it checks a BOUND rather
 * than an equality.
 *
 * ⛔⛔ THE HOLE THIS CLOSES. Layer B above compares DISPATCH COUNTS. A park
 * changes WHEN a dispatch happens and never how many there are, so the model
 * and the RTL disagreed about clocked timing for an entire arc while this file
 * reported "every clocked action matched the model exactly" -- which was true,
 * about counts, and silent about the dimension that was wrong. A checker blind
 * to the dimension it is trusted on reads exactly like a checker that passed.
 *
 * ⛔⛔ WHY NOT CYCLE-EXACT EQUALITY, WHICH IS WHAT WAS ASKED FOR. Measured, it
 * cannot be: the engine's timestamp advances from the PREVIOUS TIMESTAMP
 * absolutely (P8), so a dispatch serviced LATE under EDF contention is
 * followed by one that is on time, and the gap between them comes out SHORTER
 * than the programmed delay. That is observed, not hypothetical -- t_LOW came
 * out 2, 5, 6 and 13 cycles BELOW `d` on a four-lane image. An equality check
 * would therefore fail on every multi-lane program for a reason that is
 * correct behaviour, and the only way to make it pass would be to widen the
 * tolerance until it stopped checking anything.
 *
 * ⇒ SO IT CHECKS THE HALF THAT IS CONTENTION-INDEPENDENT, and that half is
 *   exactly the F1 property:
 *
 *       the gap after an open-drain clocked HIGH is at least `d`
 *
 *   because the park sets the release to `observed rise + d`, and contention
 *   can only push a dispatch LATER than its release, never earlier. The LOW
 *   gaps carry no such bound and are not claimed here.
 *
 * ⭐ THE MUST-FIRE IS THE PRE-FIX RTL. Under `M_CK_RISE_ELIGIBLE` the release
 * is the rise itself, so the gap collapses to the synchroniser latency -- 4 or
 * 5 cycles -- and this check goes red on `corpus_i2c` and `corpus_all5` lane 0,
 * the two corpus programs that run a clocked SHIFT on an open-drain pin.
 *
 * ⛔ IT READS THE ENGINE'S OWN PREDICATES (`ck_is_high`, `l_mode`, `a_dly`)
 * rather than re-deriving them, so the bench cannot disagree with the silicon
 * about which dispatch was a high phase. `2'd1` is NOT used for the phase: the
 * engine already exposes `ck_is_high`, and a hierarchical reference to the
 * `CK_HIGH` localparam would compile and never match.
 * ======================================================================= */
integer cg_cyc;
integer cg_last [0:7];     // cycle of this lane's previous clocked dispatch
integer cg_hi   [0:7];     // ... and whether that dispatch was a HIGH phase
integer cg_od   [0:7];     // ... on an open-drain lane
integer cg_dly  [0:7];     // the delay in force for it
integer cg_fails, cg_checks, cg_worst, cg_k2;

initial begin
  cg_cyc = 0;  cg_fails = 0;  cg_checks = 0;  cg_worst = 1000000;
  for (cg_k2 = 0; cg_k2 < 8; cg_k2 = cg_k2 + 1) begin
    cg_last[cg_k2] = -1;  cg_hi[cg_k2] = 0;
    cg_od[cg_k2] = 0;  cg_dly[cg_k2] = 0;
  end
end

always @(posedge dut.clk) begin
  cg_cyc = cg_cyc + 1;
  if (dut.rst_n !== 1'b1) begin
    for (cg_k2 = 0; cg_k2 < 8; cg_k2 = cg_k2 + 1) cg_last[cg_k2] = -1;
  end else if (dut.u_eng.st === 2'd2 && dut.u_eng.cur < 8) begin
    if (dut.u_eng.clk_real === 1'b1 && dut.u_eng.a_lvl === 1'b1 &&
        (dut.u_eng.a_op === 3'd1 || dut.u_eng.a_op === 3'd2)) begin
      if (cg_last[dut.u_eng.cur] >= 0 && cg_hi[dut.u_eng.cur] === 1 &&
          cg_od[dut.u_eng.cur] === 1) begin
        cg_checks = cg_checks + 1;
        if ((cg_cyc - cg_last[dut.u_eng.cur]) < cg_dly[dut.u_eng.cur]) begin
          $display("*** FAIL clocked_conform[G1]: lane %0d gap after a HIGH was %0d cycle(s), under its delay d=%0d -- the park must release at the OBSERVED RISE plus d, not at the rise", dut.u_eng.cur, cg_cyc - cg_last[dut.u_eng.cur], cg_dly[dut.u_eng.cur]);
          cg_fails = cg_fails + 1;
        end
        if ((cg_cyc - cg_last[dut.u_eng.cur] - cg_dly[dut.u_eng.cur]) < cg_worst)
          cg_worst = cg_cyc - cg_last[dut.u_eng.cur] - cg_dly[dut.u_eng.cur];
      end
      cg_last[dut.u_eng.cur] = cg_cyc;
      cg_hi[dut.u_eng.cur]   = (dut.u_eng.ck_is_high === 1'b1) ? 1 : 0;
      cg_od[dut.u_eng.cur]   = (dut.u_eng.l_mode[dut.u_eng.cur] === 1'b0)
                                ? 1 : 0;
      cg_dly[dut.u_eng.cur]  = dut.u_eng.a_dly;
    end else begin
      cg_last[dut.u_eng.cur] = -1;   // a non-clocked action breaks the chain
    end
  end
end

task cb_report;
  begin
    $display("  clocked_conform[B]: %0d clocked action(s) checked against the model", cb_acts);
    // ⭐ THE GAP LAYER REPORTS ITS OWN NON-VACUITY. Zero checks means no
    // open-drain clocked HIGH was ever followed by another clocked dispatch in
    // this program -- which is true of the push-pull images and must read as
    // "not exercised here", never as a pass.
    if (cg_checks == 0)
      $display("  clocked_conform[G1]: 0 post-HIGH gaps on an open-drain clocked lane in this program -- NOT EXERCISED");
    else if (cg_fails != 0)
      $display("*** FAIL clocked_conform[G1]: %0d of %0d post-HIGH gaps were shorter than their delay", cg_fails, cg_checks);
    else
      $display("  clocked_conform[G1]: ok -- %0d post-HIGH gap(s), all >= d, tightest margin %0d cycle(s)", cg_checks, cg_worst);
    if (cb_fails != 0)
      $display("*** FAIL clocked_conform: %0d action(s) disagreed with the model", cb_fails);
    else if (cb_acts != 0)
      $display("  clocked_conform[B]: ok -- every clocked action matched the model exactly");
  end
endtask

final begin
  cb_report;
end

