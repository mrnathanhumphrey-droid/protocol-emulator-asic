/* tb_w.v -- RULING W: Theorem 3 on the bench, conclusion and port ledger.
 *
 * Driven by `test/run_w_sweep.py`, which owns the arms and the verdicts; this
 * bench only measures. Sampled at posedge: pre-edge state, the state the
 * engine decides from.
 *
 * W2  THE CONCLUSION, per lane: every freed slot is valid before the decision
 *     that consumes it. A VIOLATION is a decision cycle (ST_IDLE, primed,
 *     winner valid and not armed) whose head slot is INVALID -- the stall the
 *     theorem excludes. Counted as cycles and as episodes (a new slot or a
 *     fresh start). SLACK is the consuming decision's cycle minus the cycle
 *     the refill was captured; its minimum is the margin left.
 * W3  per lane, over the window after WARMUP:
 *       owed_max      most slots owed at one instant (freed, not captured)
 *       ahead_*_max   refills captured for OTHER slots between an owed
 *                     fill's free and its issue, split by the branch that
 *                     issued them (b1 winner-first, b2 round-robin)
 *       r_max         worst release -> decision, R_i
 *       gap_min       smallest same-lane decision-to-decision gap (PS2)
 * The branch of a refill is the engine's own latched `pbr1`.
 */
`default_nettype none
`timescale 1ns / 1ps

`include "test/imgload.vh"
module tb_w;

  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00, uio_drv = 8'h00;
  wire [7:0] uo_out, uio_out, uio_oe;
  // tb_smoke's model: the DUT reads its own drive back, the host elsewhere
  wire [7:0] uio_in = (uio_oe & uio_out) | (~uio_oe & uio_drv);

`include "test/store_filler.vh"   // v2: PE_STORE_BYTES, never a typed 256
  localparam integer IMG_MAX = PE_STORE_BYTES;
  localparam integer PIN_PROG = 7, PIN_PTR = 5, PIN_WR = 6;
  localparam integer NL = 5, NS = 10;

  reg  [7:0] img [0:IMG_MAX-1];
  integer    img_bytes, i, s, o, L, cyc, ncyc, warmup, warm_from;
  integer    rel, ts_diff, owed_now;
  reg [8*256-1:0] imgfile;

  always #10 clk = ~clk;

  tt_um_protocol_emulator #(.SPL(2)) dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );
`include "test/inv_curck.vh"       // PR2: cur_ck == l_clkpin[cur], every cycle

  // ---- per slot ---------------------------------------------------------
  reg     pv    [0:NS-1];       // l_actv at the previous sample
  reg     open_ [0:NS-1];       // freed, refill not yet captured
  reg     fresh [0:NS-1];       // captured, not yet consumed by a decision
  reg     iss_br[0:NS-1];       // branch of the refill issued for this slot
  integer owe_t [0:NS-1], iss_t[0:NS-1], cap_t[0:NS-1];
  integer ahd   [0:NS-1], ah1  [0:NS-1], ah2  [0:NS-1];
  // ---- per lane, window maxima and counts ---------------------------------
  integer n_owe  [0:NL-1], wi_max [0:NL-1], wc_max [0:NL-1], vw_max[0:NL-1];
  integer ah_max [0:NL-1], ah1_max[0:NL-1], ah2_max[0:NL-1];
  integer owed_max[0:NL-1], slk_min[0:NL-1], n_slk  [0:NL-1];
  integer v_ev   [0:NL-1], v_cyc  [0:NL-1];
  integer r_max  [0:NL-1], n_dec  [0:NL-1], wb_t   [0:NL-1], elig_t[0:NL-1];
  integer last_d [0:NL-1], gap_min[0:NL-1], gap_le13[0:NL-1];
  integer n_iss_head, n_iss_scan, n_cold_fill, n_anom, prev_stall_slot;
  reg     prev_scan, prev_stall;

  wire [3:0] whead = dut.u_eng.hix[dut.u_eng.winner];
  wire       decide = dut.u_eng.primed && !dut.u_eng.config_err
                      && (dut.u_eng.st == 0) && dut.u_eng.winner_v
                      && !dut.u_eng.l_armed[dut.u_eng.winner];
  wire       stall  = decide && !dut.u_eng.l_actv[whead];
  wire       in_win = (warm_from > 0) && (cyc > warm_from);

  initial begin
    if (!$value$plusargs("IMG=%s", imgfile)) begin
      $display("tb_w: FATAL -- +IMG required"); $finish;
    end
    if (!$value$plusargs("NBYTES=%d", img_bytes)) begin
      $display("tb_w: FATAL -- +NBYTES required"); $finish;
    end
    if (!$value$plusargs("NCYC=%d", ncyc))     ncyc = 200000;
    if (!$value$plusargs("WARMUP=%d", warmup)) warmup = 20000;
    $readmemh(imgfile, img);
    `PE_REQUIRE_IMG_LOADED(imgfile)
    $display("# tb_w img=%0s bytes=%0d ncyc=%0d warmup=%0d", imgfile,
             img_bytes, ncyc, warmup);

    for (s = 0; s < NS; s = s + 1) begin
      pv[s] = 0; open_[s] = 0; fresh[s] = 0; iss_br[s] = 0;
      owe_t[s] = 0; iss_t[s] = -1; cap_t[s] = 0;
      ahd[s] = 0; ah1[s] = 0; ah2[s] = 0;
    end
    for (L = 0; L < NL; L = L + 1) begin
      n_owe[L] = 0; wi_max[L] = 0; wc_max[L] = 0; vw_max[L] = 0;
      ah_max[L] = 0; ah1_max[L] = 0; ah2_max[L] = 0; owed_max[L] = 0;
      slk_min[L] = 1 << 30; n_slk[L] = 0; v_ev[L] = 0; v_cyc[L] = 0;
      r_max[L] = -1; n_dec[L] = 0; wb_t[L] = -10; elig_t[L] = -1;
      last_d[L] = -1; gap_min[L] = 1 << 30; gap_le13[L] = 0;
    end
    n_iss_head = 0; n_iss_scan = 0; n_cold_fill = 0; n_anom = 0;
    prev_scan = 0; prev_stall = 0; prev_stall_slot = -1;
    cyc = 0; warm_from = 0;

    repeat (4) @(negedge clk);
    rst_n = 1;
    @(negedge clk);
    ui_in[PIN_PROG] = 1'b1;
    repeat (3) @(negedge clk); ui_in[PIN_PTR] = 1'b1; repeat (3) @(negedge clk);  // CDC3: prog >= 3 cy before ptr; ptr >= 3 cy wide
    ui_in[PIN_PTR] = 1'b0; repeat (3) @(negedge clk);
    for (i = 0; i < img_bytes; i = i + 1) begin
      uio_drv = img[i];
      @(negedge clk); @(negedge clk);
      ui_in[PIN_WR] = 1'b1;
      @(negedge clk); @(negedge clk); @(negedge clk);
      ui_in[PIN_WR] = 1'b0;
      @(negedge clk);
    end
    ui_in[PIN_PROG] = 1'b0;
    uio_drv = 8'hFF;

    for (i = 0; i < ncyc; i = i + 1) begin
      @(posedge clk);
      cyc = cyc + 1;
      if (warm_from == 0 && dut.u_eng.hdr_done) warm_from = cyc + warmup;

      // ---- issue: this sample is P_REQ and the previous one was P_SCAN ---
      if (dut.u_eng.pst == 1 && prev_scan) begin
        s = dut.u_eng.fix;
        if (dut.u_eng.pbr1) n_iss_head = n_iss_head + 1;
        else                n_iss_scan = n_iss_scan + 1;
        if (open_[s] && iss_t[s] < 0) iss_t[s] = cyc;
        iss_br[s] = dut.u_eng.pbr1;
      end
      prev_scan = (dut.u_eng.pst == 0) && dut.u_eng.hdr_done;

      // ---- captures FIRST: a refill landing on the same edge as a free was
      // already in flight, so it is not "ahead" of the owe that edge opens.
      for (s = 0; s < NS; s = s + 1) begin
        if (!pv[s] && dut.u_eng.l_actv[s]) begin
          for (o = 0; o < NS; o = o + 1)
            if (o != s && open_[o] && iss_t[o] < 0) begin
              ahd[o] = ahd[o] + 1;
              if (iss_br[s]) ah1[o] = ah1[o] + 1; else ah2[o] = ah2[o] + 1;
            end
          cap_t[s] = cyc; fresh[s] = 1;
          if (open_[s]) begin
            L = s / 2;
            if (iss_t[s] < 0) n_anom = n_anom + 1;
            if (warm_from > 0 && owe_t[s] > warm_from) begin
              n_owe[L] = n_owe[L] + 1;
              // valid from WB: the WB is the cycle BEFORE the free is visible
              if (cyc - (owe_t[s] - 1) > vw_max[L]) vw_max[L] = cyc - (owe_t[s] - 1);
              if (iss_t[s] - owe_t[s] > wi_max[L]) wi_max[L] = iss_t[s] - owe_t[s];
              if (cyc - owe_t[s] > wc_max[L])      wc_max[L] = cyc - owe_t[s];
              if (ahd[s] > ah_max[L])              ah_max[L] = ahd[s];
              if (ah1[s] > ah1_max[L])             ah1_max[L] = ah1[s];
              if (ah2[s] > ah2_max[L])             ah2_max[L] = ah2[s];
            end
            open_[s] = 0;
          end else begin
            n_cold_fill = n_cold_fill + 1;
          end
        end
      end
      for (s = 0; s < NS; s = s + 1) begin
        if (pv[s] && !dut.u_eng.l_actv[s]) begin
          if (open_[s]) n_anom = n_anom + 1;
          open_[s] = 1; owe_t[s] = cyc; iss_t[s] = -1;
          ahd[s] = 0; ah1[s] = 0; ah2[s] = 0;
        end
        pv[s] = dut.u_eng.l_actv[s];
      end

      // ---- W3: slots owed per lane at this instant -------------------------
      if (in_win)
        for (L = 0; L < NL; L = L + 1) begin
          owed_now = open_[2*L] + open_[2*L+1];
          if (owed_now > owed_max[L]) owed_max[L] = owed_now;
        end

      // ---- R_i: eligibility re-arms at the lane's WB -----------------------
      for (L = 0; L < NL; L = L + 1)
        if (elig_t[L] < 0 && dut.u_eng.ready[L]) elig_t[L] = cyc;
      if (dut.u_eng.st == 2) begin
        elig_t[dut.u_eng.cur] = -1;
        wb_t[dut.u_eng.cur]   = cyc;
      end

      // ---- a decision with a valid head: slack, R_i, gap -------------------
      if (decide && dut.u_eng.l_actv[whead]) begin
        L = dut.u_eng.winner;
        if (fresh[whead]) begin
          fresh[whead] = 0;
          if (in_win) begin
            n_slk[L] = n_slk[L] + 1;
            if (cyc - cap_t[whead] < slk_min[L]) slk_min[L] = cyc - cap_t[whead];
          end
        end
        // masked to the 16-bit timestamp, so a wrapped `now` is not negative
        ts_diff = (dut.u_eng.now - dut.u_eng.l_timestamp[L]) & 32'hFFFF;
        rel = cyc - ts_diff;
        // a release that arrived while this lane's previous job was still in
        // the pipe is not eligible before that job's WB
        if (rel < wb_t[L] + 1) rel = wb_t[L] + 1;
        if (in_win && elig_t[L] >= 0) begin
          n_dec[L] = n_dec[L] + 1;
          if (cyc - rel > r_max[L]) r_max[L] = cyc - rel;
        end
        if (in_win && last_d[L] >= 0) begin
          if (cyc - last_d[L] < gap_min[L]) gap_min[L] = cyc - last_d[L];
          if (cyc - last_d[L] <= 13)        gap_le13[L] = gap_le13[L] + 1;
        end
        last_d[L] = cyc;
      end

      // ---- W2: the conclusion's violation ----------------------------------
      if (stall && in_win) begin
        s = whead;
        v_cyc[s / 2] = v_cyc[s / 2] + 1;
        if (!prev_stall || prev_stall_slot != s) v_ev[s / 2] = v_ev[s / 2] + 1;
      end
      if (stall) prev_stall_slot = whead;
      prev_stall = stall;
    end

    for (L = 0; L < NL; L = L + 1)
      $display("W lane=%0d viol_ev=%0d viol_cyc=%0d slack_min=%0d consumed=%0d owed_max=%0d ahead_max=%0d ahead_b1_max=%0d ahead_b2_max=%0d wi_max=%0d wc_max=%0d vfwb_max=%0d r_max=%0d decisions=%0d gap_min=%0d gap_le13=%0d",
               L, v_ev[L], v_cyc[L], n_slk[L] ? slk_min[L] : -1, n_slk[L],
               owed_max[L], ah_max[L], ah1_max[L], ah2_max[L], wi_max[L],
               wc_max[L], vw_max[L], r_max[L], n_dec[L],
               (last_d[L] >= 0 && gap_min[L] < (1 << 30)) ? gap_min[L] : -1,
               gap_le13[L]);
    $display("ISSUE head=%0d scan=%0d cold_fills=%0d anomalies=%0d warm_from=%0d",
             n_iss_head, n_iss_scan, n_cold_fill, n_anom, warm_from);
    $display("END tb_w cycles=%0d", cyc);
    $finish;
  end
`include "test/runstart.vh"   // v2: the engine-started guard (R3)
endmodule
