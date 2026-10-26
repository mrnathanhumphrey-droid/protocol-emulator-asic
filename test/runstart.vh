/* runstart.vh -- THE RUN-START ANCHOR AND THE ENGINE-STARTED GUARD, one place.
 *
 * ⛔⛔ WHY (v2 step 2, Wilson R3 + Nate's option 1, 10-25). v2's store is 512
 * bytes and the engine does not run until all of them are written
 * (`eng_run = run & store_full & ~bad_magic` in `src/project.v`). So the SAME
 * bench on v2 starts its engine ~256 load-writes later than on v1, and two
 * hazards follow:
 *   (1) a bench that loads FEWER bytes than the store never starts its engine
 *       at all. MEASURED: `tb_v2win` looped `i < 256`, and `run_v2window`
 *       came back "the dry run found 0 slot(s)". It failed loudly -- but an arm
 *       that DECLARES quiescence (`pg_quiescent_ok`, a refusal test) would have
 *       PASSED on an engine that never started, because "nothing retired" is
 *       exactly what it expects. That is the hollow pass R3 names.
 *   (2) a cycle counted FROM RESET moves by the load length, so a v1 number
 *       and a v2 number for the same run no longer agree. Every measured
 *       window must be anchored at RUN START -- the first cycle the engine
 *       runs -- so the run figures of v1 and v2 can be compared at all.
 *
 * ⇒ This file gives every bench, from ONE definition:
 *   `rs_start`  the cycle (counted from rst_n high, posedges) on which
 *               `dut.eng_run` was first seen high; -1 if it never was;
 *   `rs_starts` how many times the engine (re)started -- a reload stops it;
 *   and a `final` verdict: an engine that NEVER STARTED is `*** FAIL`, unless
 *   the arm DECLARES it with `rs_nostart_ok` (a load-mode trace, a refused
 *   load) -- a claim the bench makes about itself, as with `pg_quiescent_ok`.
 * ⭐ It prints the start cycle on every bench, so the anchor is MEASURED in
 *   each log rather than assumed: v1 vs v2 differ there by the load and by
 *   nothing else.
 *
 * ⛔ `dut.eng_run` IS A WIRE, NOT A LOCALPARAM, so the hierarchical reference
 *   is a real signal (progress.vh's ST_WB trap cannot recur here); and the
 *   never-started arm of this file is priced by a must-fire (a 256-byte load).
 *
 * USAGE:  `include "test/runstart.vh"   after the `dut` instance. Already
 *         included by `test/progress.vh`; include it directly only in a bench
 *         that does not include progress.vh.
 */
`ifndef PE_RUNSTART_VH
`define PE_RUNSTART_VH
integer rs_cyc    = 0;     // posedges since rst_n went high
integer rs_start  = -1;    // first cycle eng_run was high
integer rs_starts = 0;
reg     rs_prev   = 1'b0;
reg     rs_nostart_ok = 1'b0;  // this arm EXPECTS the engine never to start

always @(posedge dut.clk) if (dut.rst_n === 1'b1) begin
  rs_cyc = rs_cyc + 1;
  if (dut.eng_run === 1'b1 && rs_prev !== 1'b1) begin
    rs_starts = rs_starts + 1;
    if (rs_start < 0) rs_start = rs_cyc;
  end
  rs_prev = dut.eng_run;
end

final begin
  if (rs_start >= 0)
    $display("  runstart.vh: engine started at cycle %0d after reset (%0d start(s))", rs_start, rs_starts);
  else if (rs_nostart_ok)
    $display("  runstart.vh: engine never started BY DECLARATION -- this arm expects it (load-mode trace or refused load)");
  else
    $display("*** FAIL runstart.vh: the engine NEVER STARTED (eng_run never high) -- the store was not filled, or the magic was refused; nothing this bench measured ran");
end
`endif
