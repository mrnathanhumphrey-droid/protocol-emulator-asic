/* tb_witness.v -- the WITNESS TRACE for a worst-case prefetch stall.
 *
 * THE ONE CLAIM: when a lane stalls waiting for its head slot, this prints the
 * CHAIN -- which lanes' refills the single fetch port served while the winner
 * waited, in order. That chain is what a derivation has to be built from.
 *
 * ⛔⛔ WHY A TRACE AND NOT ANOTHER SCALAR. The published universal J was a
 * scalar fitted to a recorded sweep, and it was unsound at ten admissible
 * points. The replacement candidate (`U_port`) was a scalar too, and its
 * pre-registered falsifier fired. Two scalars have now failed on the same
 * question, and the measured stalls come in two distinct sizes -- exactly 7
 * (= L_CAP, a lane's own refill round-trip) for mixed programs with an idle
 * port, and 11 for uniform sub-D* programs where the port is contended. TWO
 * MECHANISMS CANNOT BE EXPRESSED BY ONE NUMBER, so the next step is to look at
 * what actually happens rather than fit a third constant.
 *
 * ⚠ IT REPORTS A FLOOR, NOT A BOUND. One image, one phase alignment. A
 * derivation built from this chain must land at or above what is seen here for
 * every alignment, which this bench cannot establish by itself.
 */

`default_nettype none
`timescale 1ns / 1ps

`include "test/imgload.vh"
module tb_witness;

  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00, uio_in = 8'h00;
  wire [7:0] uo_out, uio_out, uio_oe;

  localparam integer IMG_MAX = 256;
  localparam integer PIN_PROG = 7, PIN_PTR = 5, PIN_WR = 6;
  localparam integer RING = 48;          // cycles of history kept

  reg  [7:0] img [0:IMG_MAX-1];
  integer    img_bytes, i, cyc, ncyc, warmup, warm_from, best, best_at;
  integer    stall, head, n;
  // ⛔⛔ THE DUMP TASK GETS ITS OWN LOOP INDEX, and it did not. `dump` shared
  // `i` with the main run loop below, so every dump reset `i` to RING and THIS
  // BENCH RAN LONGER THAN `NCYC` -- by whatever multiple the number of dumps
  // happened to produce. ⚠ WHAT THAT DOES AND DOES NOT INVALIDATE: `cyc`
  // counts iterations actually executed, so the printed cycle numbers and the
  // chains themselves are real observations, and the run was LONGER than
  // requested rather than shorter -- the safe direction for a worst-case
  // search. What was wrong is the RUN LENGTH CONTROL: a bench whose duration
  // depends on how often it printed is not reproducible, and the "window"
  // figure it reported was not the window that was asked for.
  // ⭐ Found in `tb_jlane.v`, which was written from this file's structure and
  // inherited the defect; it showed up there only because that bench prints
  // its window as a precondition with a known ceiling.
  integer    di, dn;
  reg [8*256-1:0] imgfile;

  // the ring: what the fetch port was doing, cycle by cycle
  integer r_cyc  [0:RING-1];
  integer r_pst  [0:RING-1];
  integer r_pl   [0:RING-1];
  integer r_win  [0:RING-1];
  integer r_act  [0:RING-1];
  integer r_st   [0:RING-1];

  always #10 clk = ~clk;

  // ⭐⭐ THE BUFFER DEPTH IS A PARAMETER, AND THE SUITE RUNS BOTH VALUES.
  // Build the single-buffer configuration with
  //     iverilog -Ptb_witness.SPL_CFG=1 ...
  // ⛔⛔ WHY EVERY BENCH CARRIES THIS. Four benches kept a PRIVATE COPY of the
  // engine's slot index (`lane*2 + l_sel`), every copy silently assumed
  // SPL = 2, and every one of them broke the moment SPL = 1 existed -- one of
  // them after measuring and publishing a column. That is the generic
  // detector: a hidden constant in a bench fails as soon as the parameter it
  // assumes becomes variable. So the parameter point is swept rather than
  // trusted, by `test/run_param_points.py`.
  parameter integer SPL_CFG = 2;

  tt_um_protocol_emulator #(.SPL(SPL_CFG)) dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );

`include "test/progress.vh"
`include "test/clocked_conform.vh"

  // ⛔ THE SAME STALL CONDITION THE ENGINE COUNTS ON, reconstructed here:
  // winner chosen, schedule running, and waiting ONLY on its own head slot.
  // Reading a different condition would witness a different event.
  // ⛔⛔ THIS WAS A 3-BIT PRIVATE COPY OF THE SLOT INDEX, AND 3 BITS IS TOO
  // FEW. `NSLOT = SPL * N_LANES = 10`, so when lane 4 is the winner its head
  // slot is 8 or 9 and a 3-bit index WRAPS TO 0 OR 1 -- this bench then read
  // LANE 0's valid bit while reporting lane 4 as the winner. ⚠ The published
  // chains in `docs/PREREG_U_PORT.md` both have winners 0 and 1, where three
  // bits suffice, and they still reproduce exactly (chain 1: stall 8 at cycle
  // 4870) -- but the worst-case SEARCH that found them ran with this index, so
  // the fix is required before any further number comes out of here.
  // ⭐ FOURTH COPY OF THIS INDEX FOUND IN ONE SESSION, after the RTL's ten
  // were collapsed into `hix`: the swap invariant and the stall
  // reconstruction in `tb_smoke`, `tb_jlane`'s head index, and this. Reading
  // the engine's own wire is the only form that cannot drift or alias.
  wire [3:0] w_sel  = dut.u_eng.hix[dut.u_eng.winner];
  wire       waiting = (dut.u_eng.st == 0) && dut.u_eng.winner_v
                       && !dut.u_eng.l_actv[w_sel];

  task dump;
    begin
      $display("  WITNESS: worst steady stall = %0d, ending at cycle %0d",
               best, best_at);
      $display("    the %0d cycles up to it -- `pl` is the lane the ONE fetch",
               RING);
      $display("    port was serving, `pst` its state (0=SCAN 1=REQ 2=WAIT 3=CAP):");
      $display("      %-8s %-5s %-5s %-7s %-6s %s",
               "cycle", "pst", "pl", "winner", "head?", "stall");
      for (di = 0; di < RING; di = di + 1) begin
        dn = (head + di) % RING;
        if (r_cyc[dn] > 0)
          $display("      %-8d %-5d %-5d %-7d %-6d %0d",
                   r_cyc[dn], r_pst[dn], r_pl[dn], r_win[dn], r_act[dn],
                   r_st[dn]);
      end
    end
  endtask

  initial begin
    if (!$value$plusargs("IMG=%s", imgfile)) imgfile = "test/five_image.hex";
    if (!$value$plusargs("NCYC=%d", ncyc))   ncyc = 200000;
    if (!$value$plusargs("WARMUP=%d", warmup)) warmup = 4000;
    if (!$value$plusargs("NBYTES=%d", img_bytes)) begin
      $display("tb_witness: FATAL -- +NBYTES=<n> is required.");
      $display("  Deriving it from unwritten-array state is simulator-");
      $display("  dependent, and this bench must not report a number that");
      $display("  came from a program which never loaded.");
      $finish;
    end
    $readmemh(imgfile, img);
    `PE_REQUIRE_IMG_LOADED(imgfile)
    $display("# witness img=%0s bytes=%0d ncyc=%0d warmup=%0d",
             imgfile, img_bytes, ncyc, warmup);

    for (i = 0; i < RING; i = i + 1) begin
      r_cyc[i] = 0; r_pst[i] = 0; r_pl[i] = 0;
      r_win[i] = 0; r_act[i] = 0; r_st[i] = 0;
    end
    cyc = 0; stall = 0; best = 0; best_at = 0; head = 0; warm_from = 0;

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

    // ---- run, keeping the ring -----------------------------------------
    for (i = 0; i < ncyc; i = i + 1) begin
      @(posedge clk);
      cyc = cyc + 1;
      if (warm_from == 0 && dut.u_eng.hdr_done) warm_from = cyc + warmup;

      r_cyc[head] = cyc;
      r_pst[head] = dut.u_eng.pst;
      r_pl[head]  = dut.u_eng.pl;
      r_win[head] = dut.u_eng.winner;
      r_act[head] = dut.u_eng.l_actv[w_sel];
      r_st[head]  = stall;
      head = (head + 1) % RING;

      if (waiting) begin
        stall = stall + 1;
        // ⭐ CAPTURED AT THE NEW MAXIMUM, inside the warm window only. A ring
        // snapshot taken at the end of the run would show a quiet port and
        // explain nothing.
        if (warm_from > 0 && cyc > warm_from && stall > best) begin
          best = stall;
          best_at = cyc;
          dump;
        end
      end else begin
        stall = 0;
      end
    end

    $display("# witness done: worst steady stall %0d at cycle %0d (window %0d)",
             best, best_at, (cyc > warm_from) ? (cyc - warm_from) : 0);
    $finish;
  end

endmodule

`default_nettype wire
