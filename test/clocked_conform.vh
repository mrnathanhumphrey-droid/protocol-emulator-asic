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

/* ⛔⛔⛔ THE PORT-DEMAND BOUND (ruling R): **ONE REFILL PER SLOT** per retired
 * clocked action, which is `SPL`. Amendment A1 says a HELD clocked dispatch
 * owes no refill -- `ST_WB`'s hold arm skips the PC advance, the invalidation
 * and the buffer swap -- so inside one action's window a lane can take:
 *
 *   * at most ONE head refill, the one the PREVIOUS action's retire triggered,
 *     landing just inside this window; and
 *   * at most ONE spare fill, because `want_fetch` fills the spare when it is
 *     empty and it then stays valid until the head retires and the swap
 *     consumes it.
 *
 * ⇒ `SPL` slots, at most one fill each: the bound is the BUFFER DEPTH, not a
 *   number fitted to an image. It is read from `dut.u_eng.SPL` so it follows
 *   the design -- and becomes 1 automatically on an `SPL = 1` build, which
 *   `run_param_points.py` really does run.
 *
 * ⛔⛔ THE FIRST VERSION OF THIS BOUND WAS 1, MEASURED ON TOO NARROW AN IMAGE
 * SET, AND THAT IS RECORDED RATHER THAN QUIETLY BUMPED. `ckod` (184 actions)
 * and `corpus_i2c` (72) each have exactly ONE live clocked lane, and both show
 * worst = 1. `corpus_all5` has FIVE live lanes and shows worst = **2**: under
 * contention the speculative spare fill really does land inside a clocked
 * action's window. ⚠ SAME CATEGORY ERROR AS THREE ALREADY IN THIS SESSION'S
 * LEDGER -- a bound measured on the shipped single-lane case and then applied
 * to the 5-lane stress image. The fix is to DERIVE it from the depth, which
 * also explains both numbers instead of accommodating one.
 *
 * ⚠ STILL TIGHT, and declared: `corpus_all5` touches the bound exactly, so
 * anything that adds a refill to a clocked window goes RED here. That is a
 * request to re-derive `D*`, never a licence to raise this.
 *
 * ⛔ `M_CK_HOLD_INVAL` IS THE MUST-FIRE: it invalidates the head on every held
 * dispatch, so a clocked byte takes a refill PER DISPATCH -- measured 16, 16
 * and 17 against a bound of 2. That mutant survives Layer A1 (the PC does not
 * move, so the refill restores an identical word) and Layer B (a refill changes
 * no dispatch count). This is the layer that sees it.
 */

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
 * R -- PORT DEMAND PER RETIRED ACTION, which is the premise `D*` rests on.
 *
 * ⛔⛔ THE HOLE THIS CLOSES, AND IT WAS FOUND BY A MUTANT THAT SURVIVED
 * EVERYTHING. `M_CK_HOLD_INVAL` invalidates the lane's head slot on every HELD
 * clocked dispatch. Layer A1 cannot see it: the PC does NOT advance during a
 * hold, so the prefetch re-reads the SAME address and restores an IDENTICAL
 * word -- every delay the park reads is still correct, and A1's subject is the
 * head-slot WORD. Layer B cannot see it either, because a refill changes no
 * dispatch count.
 * ⇒ WHAT IT BREAKS IS AMENDMENT A1's **PORT PREMISE**: a refill per DISPATCH
 *   instead of per ACTION. `D* = N_LANES * L_REFILL` and every port-feasibility
 *   cell in Theorem 3 assume a held clocked dispatch owes NO refill. With the
 *   mutant a single clocked byte costs up to 16 refills instead of one, and
 *   re-dispatch counts moved 1229 -> 1061 on `corpus_i2c` -- so the schedule
 *   the whole A2 argument quotes is for a different machine.
 * ⚠ SO THE TREE WAS GREEN ON A PREMISE NOTHING CHECKED. That is the reason
 *   this layer exists and the reason it is NOT optional on clocked arms.
 *
 * THE OBSERVABLE, read from the engine rather than inferred: one refill is one
 * cycle in `pst == P_CAP` with `pl` naming the lane (`P_CAP` is where
 * `l_act[fix]` is written and `l_actv[fix]` set). Counted per lane over the
 * window Layer B already delimits -- from the dispatch that starts an action to
 * the one that starts the next.
 *
 * ⛔ THE BOUND IS **MEASURED, THEN ENFORCED**, and the order matters. The
 * verdict is gated on `+RBOUND`, exactly as A2's is, so the first runs REPORT
 * the distribution and a number nobody has derived is never asserted. What the
 * design should give is at most ONE refill per clocked action -- the retire's
 * own invalidation, which belongs to the NEXT action -- plus at most one
 * speculative SPARE fill at SPL = 2.
 * ⚠ `P_CAP` IS COUNTED FOR **EVERY** LANE, not just clocked ones, because the
 * window is per lane and a refill for lane 2 says nothing about lane 0's
 * action. A single shared counter would have made every multi-lane arm look
 * like a violation.
 * ======================================================================= */
integer cr_ref  [0:7];     // refills seen inside the current action's window
integer cr_max  [0:7];     // the worst window this lane has shown
integer cr_checks, cr_fails, cr_worst, cr_bound, cr_k;

initial begin
  for (cr_k = 0; cr_k < 8; cr_k = cr_k + 1) begin
    cr_ref[cr_k] = 0;  cr_max[cr_k] = -1;
  end
  cr_checks = 0;  cr_fails = 0;  cr_worst = -1;
  // ⛔⛔ THE DEFAULT IS **ENFORCED**, not off, and that is the whole point of
  // ruling R: the tree was green on this premise because nothing checked it, so
  // a layer that defaults to report-only would reproduce the hole it closes.
  // `+RBOUND=<n>` only RAISES it for a lane set that legitimately needs more,
  // and `-1` disables it explicitly for a measurement run.
  // ⚠ THIS FILE IS INCLUDED BY THIRTEEN BENCHES, so the plusarg it reads is
  // declared once in `benchset.SHARED_INCLUDE_DEFAULTS` with its reason --
  // the mechanism built for `+A2BOUND` after the scanner's digit blind spot.
  // ⭐ THE DEFAULT IS THE DESIGN'S OWN BUFFER DEPTH, read hierarchically, so
  // the bound cannot drift from `SPL` and needs no second copy here.
  if (!$value$plusargs("RBOUND=%d", cr_bound)) cr_bound = dut.u_eng.SPL;
end

always @(posedge dut.clk) begin
  if (dut.rst_n !== 1'b1) begin
    for (cr_k = 0; cr_k < 8; cr_k = cr_k + 1) cr_ref[cr_k] = 0;
  end else begin
    // ---- count a refill against the lane it is for ----------------------
    if (dut.u_eng.pst === 3'd3 && dut.u_eng.pl < 8)
      cr_ref[dut.u_eng.pl] = cr_ref[dut.u_eng.pl] + 1;
    // ---- close the window on the same event Layer B uses ----------------
    if (dut.u_eng.st === 2'd2 && dut.u_eng.cur < 8) begin
      if (dut.u_eng.a_op === 3'd7 && dut.u_eng.a_lvl === 1'b0) begin
        cr_ref[dut.u_eng.cur] = 0;                  // the chaining re-arm
      end else if (cb_pc[dut.u_eng.cur] !== dut.u_eng.l_pc[dut.u_eng.cur]) begin
        // ⭐ `cb_ck` IS THE CLOSING action's class, set when its window opened,
        // so this counts the action that just ENDED rather than the one
        // starting -- the off-by-one that would have attributed a clocked
        // action's refills to its unclocked successor.
        if (cb_pc[dut.u_eng.cur] !== -1 && cb_ck[dut.u_eng.cur]) begin
          cr_checks = cr_checks + 1;
          if (cr_checks == 1)
            $display("  clocked_conform[R]: live -- counting refills per retired clocked action");
          if (cr_ref[dut.u_eng.cur] > cr_max[dut.u_eng.cur])
            cr_max[dut.u_eng.cur] = cr_ref[dut.u_eng.cur];
          if (cr_ref[dut.u_eng.cur] > cr_worst)
            cr_worst = cr_ref[dut.u_eng.cur];
          if (cr_bound >= 0 && cr_ref[dut.u_eng.cur] > cr_bound) begin
            $display("*** FAIL clocked_conform[R]: lane %0d retired a clocked op=%0d cnt=%0d after %0d dispatch(es) having taken %0d PREFETCH REFILL(S), over the bound of %0d -- a held clocked dispatch owes no refill, and Amendment A1's port premise (and D*) assume it does not", dut.u_eng.cur, cb_op[dut.u_eng.cur], cb_cnt[dut.u_eng.cur], cb_n[dut.u_eng.cur], cr_ref[dut.u_eng.cur], cr_bound);
            cr_fails = cr_fails + 1;
          end
        end
        cr_ref[dut.u_eng.cur] = 0;
      end
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
/* =======================================================================
 * A1 -- HEAD-SLOT STABILITY ACROSS A CLOCKED PARK.
 *
 * ⛔⛔ WHY THIS IS A CHECK AND NOT A COMMENT. F1's rebase reads the parked
 * lane's delay out of `l_act[hix[gi]]`, and that costs ZERO FLOPS only because
 * a held clocked action does not invalidate its slot -- `ST_WB`'s
 * `ck_hold_eff` arm skips the PC advance, the invalidation and the buffer
 * swap. The whole saving rests on an emptiness: on an arm that does nothing.
 * If a future change ever made a held action invalidate, the prefetch would
 * refill the head slot with the NEXT action's word while the park was still
 * waiting, and the lane would release on a delay belonging to a different
 * action -- silently, because the dispatch COUNT would be unchanged and the
 * clock would still look like a clock.
 * ⇒ So the action word is snapshotted when a clocked action begins and
 *   compared on every re-dispatch of it. `M_CK_HOLD_INVAL` is the mutant.
 * ======================================================================= */
integer ca_word [0:7];     // the action word this lane's current action began with
integer ca_have [0:7];
integer ca_fails, ca_checks, ca_k;

initial begin
  ca_fails = 0;  ca_checks = 0;
  for (ca_k = 0; ca_k < 8; ca_k = ca_k + 1) begin
    ca_word[ca_k] = 0;  ca_have[ca_k] = 0;
  end
end

always @(posedge dut.clk) begin
  if (dut.rst_n !== 1'b1) begin
    for (ca_k = 0; ca_k < 8; ca_k = ca_k + 1) ca_have[ca_k] = 0;
  end else if (dut.u_eng.st === 2'd2 && dut.u_eng.cur < 8) begin
    if (dut.u_eng.clk_real === 1'b1 && dut.u_eng.a_lvl === 1'b1 &&
        (dut.u_eng.a_op === 3'd1 || dut.u_eng.a_op === 3'd2)) begin
      // ⛔⛔ THE SNAPSHOT LIVES INSIDE THE HOLD BRANCH, AND THE FIRST
      // VERSION PUT IT AFTER THE if/else -- WHICH FALSE-FIRED ON THE CLEAN
      // BUILD. At the RETIRING dispatch it cleared `ca_have` and then
      // immediately re-snapshotted, storing the OUTGOING action's word with
      // `ca_have = 1`; the next action's first dispatch then compared its own
      // word against its predecessor's and reported a change that had not
      // happened. ⚠ A check that fires on a correct design is worse than no
      // check: it trains the reader to ignore it.
      if (dut.u_eng.ck_hold_eff === 1'b1) begin
        if (ca_have[dut.u_eng.cur] === 1) begin
          // a RE-DISPATCH of the same action: the word must not have moved,
          // and the slot must still be VALID.
          // ⛔⛔ VALIDITY IS THE PROPERTY THAT MATTERS, AND THE FIRST VERSION
          // CHECKED ONLY THE WORD -- so the mutant did not fire.
          // `M_CK_HOLD_INVAL` clears `l_actv`; it does not overwrite `l_act`.
          // The word therefore sat unchanged in a slot the prefetch was now
          // free to refill, and a check watching only the bits could not see
          // the hazard. ⚠ It DID change behaviour -- re-dispatches went 1229 ->
          // 1061 on `corpus_i2c` -- so the mutant was live and my check was
          // looking at the adjacent property.
          ca_checks = ca_checks + 1;
          if (dut.u_eng.l_actv[dut.u_eng.hix[dut.u_eng.cur]] !== 1'b1) begin
            $display("*** FAIL clocked_conform[A1]: lane %0d's head slot went INVALID during a clocked hold -- the park reads its delay from that slot, and an invalid slot is one the prefetch may refill with the NEXT action's word", dut.u_eng.cur);
            ca_fails = ca_fails + 1;
          end else if (ca_word[dut.u_eng.cur] !==
              dut.u_eng.l_act[dut.u_eng.hix[dut.u_eng.cur]]) begin
            $display("*** FAIL clocked_conform[A1]: lane %0d's head-slot action word changed DURING a clocked hold (was %0h, now %0h) -- the park reads its delay from that slot, so it would release on another action's delay", dut.u_eng.cur, ca_word[dut.u_eng.cur], dut.u_eng.l_act[dut.u_eng.hix[dut.u_eng.cur]]);
            ca_fails = ca_fails + 1;
          end
        end else begin
          // the FIRST dispatch of this clocked action: take the snapshot
          ca_word[dut.u_eng.cur] = dut.u_eng.l_act[dut.u_eng.hix[dut.u_eng.cur]];
          ca_have[dut.u_eng.cur] = 1;
        end
      end else begin
        // it RETIRED on this dispatch -- the next action snapshots itself
        ca_have[dut.u_eng.cur] = 0;
      end
    end else begin
      ca_have[dut.u_eng.cur] = 0;
    end
  end
end

/* A2 -- THE UPPER BOUND ON A POST-HIGH GAP.
 *
 * ⛔⛔ G1's LOWER BOUND CATCHES "TOO EARLY" AND SAYS NOTHING ABOUT "TOO LATE".
 * A park that released at `rise + 2d`, or one whose rebase was lost so the lane
 * waited for its ordinary timestamp instead, would sail through `gap >= d`
 * while producing a clock of the wrong period. So the gap is bounded on both
 * sides.
 *
 * THE BOUND:  gap <= d + L_SYNC + 1 + (r_i - C)
 *
 *   L_SYNC      3  the synchroniser depth before the rise is OBSERVED
 *   + 1            the dispatch that acts on it
 *   (r_i - C)   4  the lane's A2 start-delay bound -- how late EDF contention
 *                  can push the dispatch once it is eligible
 *
 * ⭐ DERIVED AND THEN CONFIRMED, in that order: the sum is 8, and the measured
 * margin came out 4..8 on the four-lane open-drain image and 4..6 on
 * `corpus_i2c`. The maximum touches the bound exactly, which is what a correct
 * bound should do.
 * ⚠ IT IS THEREFORE TIGHT, AND THAT IS DECLARED: there is no slack above the
 * observed maximum, so a change that adds contention to a clocked lane will go
 * red here. That is the point of a bound -- but it means a red here is a
 * REQUEST TO RE-DERIVE `r_i - C`, not a licence to raise the constant.
 * ⛔ `model/a2/gate_clocked_lane_a2.py` PARSES THIS CONSTANT out of this file
 * and asserts it still covers `max(r_i - C)` over the lane set it builds, so
 * the number lives in ONE place and A2 is what checks it. Copying it into the
 * gate would be the two-copies defect that this project has already shipped
 * once in a published column.
 */
localparam integer CK_GAP_SLACK = 8;
localparam integer N_LANES_CB   = 5;

integer cg_cyc;
integer cg_last [0:7];     // cycle of this lane's previous clocked dispatch
integer cg_hi   [0:7];     // ... and whether that dispatch was a HIGH phase
integer cg_od   [0:7];     // ... on an open-drain lane
integer cg_dly  [0:7];     // the delay in force for it
integer cg_fails, cg_checks, cg_worst, cg_widest, cg_k2;
integer cg_rise  [0:7];    // cycle the lane's parked rise was OBSERVED
integer cg_afails, cg_achecks, cg_awidest;
/* ⛔⛔ THE A2 BOUND IS ENFORCED ONLY WHERE ITS TERM IS DEFINED, and that is a
 * category point rather than a convenience. `r_i - C` is a property of a LANE
 * SET: the shipped five give 4, so the budget is L_SYNC + 1 + 4 = 8. A
 * five-lane STRESS image has different deadlines and therefore a different
 * r_i -- `corpus_all5` measures a post-rise lateness of up to 19 -- and
 * failing it against the shipped set's number would be checking one set's
 * bound against another's behaviour.
 * ⚠ THIS IS THE SAME MISTAKE THREE TIMES IN ONE ARC, which is why it is
 * written down here: a d = 25 lane was failed for missing Sm's setup minimum
 * (a requirement that only applies at 100 kHz), the budget cross-check took
 * `max(r_i - C)` over every lane when the bound is on ONE lane's own
 * lateness, and now this.
 * ⭐ THE MEASUREMENT IS NOT SCOPED, ONLY THE VERDICT: every arm reports its
 * widest post-rise lateness, so `corpus_all5`'s 19 stays visible instead of
 * being scoped out of existence. `+A2BOUND=1` is set on the arm whose lane
 * set A2 actually models.
 */
integer cg_abound;

initial begin
  cg_cyc = 0;  cg_fails = 0;  cg_checks = 0;  cg_worst = 1000000;
  cg_widest = 0;  cg_afails = 0;  cg_achecks = 0;  cg_awidest = 0;
  if (!$value$plusargs("A2BOUND=%d", cg_abound)) cg_abound = 0;
  for (cg_k2 = 0; cg_k2 < 8; cg_k2 = cg_k2 + 1) cg_rise[cg_k2] = -1;
  for (cg_k2 = 0; cg_k2 < 8; cg_k2 = cg_k2 + 1) begin
    cg_last[cg_k2] = -1;  cg_hi[cg_k2] = 0;
    cg_od[cg_k2] = 0;  cg_dly[cg_k2] = 0;
  end
end

always @(posedge dut.clk) begin
  cg_cyc = cg_cyc + 1;
  // the parked rise, as the ENGINE observes it (`arm_hit` is what rebases the
  // timestamp), so the stretch is already inside this timestamp
  for (cg_k2 = 0; cg_k2 < N_LANES_CB; cg_k2 = cg_k2 + 1) begin
    if (dut.u_eng.arm_hit[cg_k2] === 1'b1 &&
        dut.u_eng.l_ckpark[cg_k2] === 1'b1)
      cg_rise[cg_k2] = cg_cyc;
  end
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
        // ⛔⛔ A2 IS MEASURED FROM THE OBSERVED RISE, NOT FROM THE HIGH
        // DISPATCH, and the first version got that wrong. The gap from the
        // HIGH dispatch CONTAINS the peer's stretch -- a 200-cycle hold makes
        // it `stretch + L_SYNC + d` quite legitimately -- so the bound fired
        // 684 times across the sweep on arms that were behaving correctly,
        // three of which exist precisely to stretch the clock. F1 counts the
        // high period FROM THE RISE IT SEES, so the bound has to start there
        // too; the stretch is then excluded by construction instead of by a
        // term that would have to guess at it.
        if (cg_rise[dut.u_eng.cur] >= 0) begin
          cg_achecks = cg_achecks + 1;
          if (cg_abound != 0 && (cg_cyc - cg_rise[dut.u_eng.cur]) >
              (cg_dly[dut.u_eng.cur] + CK_GAP_SLACK)) begin
            $display("*** FAIL clocked_conform[A2]: lane %0d dispatched %0d cycle(s) after its rise was OBSERVED, over d=%0d plus the %0d-cycle budget -- the lane released too LATE, which a lower bound alone cannot see", dut.u_eng.cur, cg_cyc - cg_rise[dut.u_eng.cur], cg_dly[dut.u_eng.cur], CK_GAP_SLACK);
            cg_afails = cg_afails + 1;
          end
          if ((cg_cyc - cg_rise[dut.u_eng.cur] - cg_dly[dut.u_eng.cur])
              > cg_awidest)
            cg_awidest = cg_cyc - cg_rise[dut.u_eng.cur]
                         - cg_dly[dut.u_eng.cur];
          cg_rise[dut.u_eng.cur] = -1;
        end
        if ((cg_cyc - cg_last[dut.u_eng.cur] - cg_dly[dut.u_eng.cur]) < cg_worst)
          cg_worst = cg_cyc - cg_last[dut.u_eng.cur] - cg_dly[dut.u_eng.cur];
        if ((cg_cyc - cg_last[dut.u_eng.cur] - cg_dly[dut.u_eng.cur]) > cg_widest)
          cg_widest = cg_cyc - cg_last[dut.u_eng.cur] - cg_dly[dut.u_eng.cur];
      end
      cg_last[dut.u_eng.cur] = cg_cyc;
      cg_rise[dut.u_eng.cur] = -1;
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
    // ⭐ A1 reports its own non-vacuity for the same reason G1 does: zero
    // checks means no clocked action was ever RE-DISPATCHED in this program,
    // which is true of the degenerate-refusal images and must read as "not
    // exercised" rather than as a pass.
    if (ca_checks == 0)
      $display("  clocked_conform[A1]: 0 clocked re-dispatches in this program -- NOT EXERCISED");
    else if (ca_fails != 0)
      $display("*** FAIL clocked_conform[A1]: %0d of %0d re-dispatches saw the head-slot word change under a hold", ca_fails, ca_checks);
    else
      $display("  clocked_conform[A1]: ok -- head-slot word stable across %0d clocked re-dispatch(es)", ca_checks);
    if (cg_checks == 0)
      $display("  clocked_conform[G1]: 0 post-HIGH gaps on an open-drain clocked lane in this program -- NOT EXERCISED");
    else if (cg_fails != 0)
      $display("*** FAIL clocked_conform[G1]: %0d of %0d post-HIGH gaps were shorter than their delay", cg_fails, cg_checks);
    else
      $display("  clocked_conform[G1]: ok -- %0d post-HIGH gap(s), all >= d, margin %0d..%0d cycle(s)", cg_checks, cg_worst, cg_widest);
    if (cg_achecks == 0)
      $display("  clocked_conform[A2]: 0 observed-rise releases in this program -- NOT EXERCISED");
    else if (cg_abound == 0)
      $display("  clocked_conform[A2]: %0d release(s) measured, widest %0d past d -- BOUND NOT ENFORCED on this lane set (+A2BOUND=0)", cg_achecks, cg_awidest);
    else if (cg_afails != 0)
      $display("*** FAIL clocked_conform[A2]: %0d of %0d releases later than d + %0d after the observed rise", cg_afails, cg_achecks, CK_GAP_SLACK);
    else
      $display("  clocked_conform[A2]: ok -- %0d release(s) within d + %0d of the observed rise, widest %0d", cg_achecks, CK_GAP_SLACK, cg_awidest);
    // ⭐ R REPORTS ITS OWN NON-VACUITY like every other layer here: zero checks
    // means this program retired no clocked action at all, which is true of the
    // unclocked and refusal images and must read as "not exercised".
    if (cr_checks == 0)
      $display("  clocked_conform[R]: 0 retired clocked actions in this program -- NOT EXERCISED");
    else if (cr_fails != 0)
      $display("*** FAIL clocked_conform[R]: %0d of %0d retired clocked actions took more than %0d prefetch refill(s); worst %0d", cr_fails, cr_checks, cr_bound, cr_worst);
    else
      $display("  clocked_conform[R]: ok -- %0d retired clocked action(s), worst %0d refill(s) against a bound of %0d", cr_checks, cr_worst, cr_bound);
    if (cb_fails != 0)
      $display("*** FAIL clocked_conform: %0d action(s) disagreed with the model", cb_fails);
    else if (cb_acts != 0)
      $display("  clocked_conform[B]: ok -- every clocked action matched the model exactly");
  end
endtask

final begin
  cb_report;
end

