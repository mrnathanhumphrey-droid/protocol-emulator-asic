// LN1 trace export (TR-2) for the Lean replay of JLane.step -- see ci/ln1_replay.py.
// Promoted from probe_tr1/probe_tr1_mon.v unchanged apart from the names.
// A second top beside tb_w; reads tb_w.dut.u_eng by hierarchical reference,
// so no other tracked file changes. Sampled at negedge + 1: registers hold what
// the edge that STARTED cycle t wrote (what the edge ending it reads), and the
// combinational winner / wb_dly are their cycle-t values.
// `E / `CLK name the engine and clock: tb_w.* under iverilog (two tops);
// the Verilator build takes one top, so it builds tr_top below and redefines them.
`default_nettype none
`timescale 1ns / 1ps
`ifndef E
`define E tb_w.dut.u_eng
`define CLK tb_w.clk
`endif
`ifdef TR1_VL_TOP
module tr_top;
  tb_w u_tb ();
  tr_mon u_mon ();
endmodule
`endif
module tr_mon;
  integer fd, cyc, maxrows, l, s, sel, actv, oos, live, started, aw;
  integer hk [0:4];                  // TR-2
  integer hop, hlv, armm, notm, capm;
  reg [63:0] hd;
  initial aw = $bits(`E.l_act[0]);   // ACT_W; PINW = 4 at N_PINS = 12
  reg [8*512-1:0] path, meta;
  initial begin
    if (!$value$plusargs("TRACE=%s", path)) begin
      $display("tr_mon: FATAL -- +TRACE required"); $finish;
    end
    if (!$value$plusargs("META=%s", meta)) meta = "";
    if (!$value$plusargs("MAXROWS=%d", maxrows)) maxrows = 200000;
    fd = $fopen(path, "w");
    cyc = 0; started = 0;
  end

  always @(negedge `CLK) begin
    #1;
    if (!started && `E.primed && `E.now_inc) begin
      started = 1;
      live = 0;
      for (l = 0; l < 5; l = l + 1)
        live = live | (`E.l_live[l] << l);
      $fwrite(fd, "# arm=%0s live=%0d dly=%0d,%0d,%0d,%0d,%0d spl=2 k=5 lrefill=4\n",
              meta, live,
              `E.l_t[0], `E.l_t[1],
              `E.l_t[2], `E.l_t[3],
              `E.l_t[4]);
      // TR-2: the v1 header unchanged up to `oos`, the v2 columns after it
      $fwrite(fd, "cycle,now,st,cur,pst,pl,prr,pbr1,pslot,winq_v,winq,win_v,win,wb_dly,ts0,ts1,ts2,ts3,ts4,sel,actv,oos,hkind0,hkind1,hkind2,hkind3,hkind4,hcnt0,hcnt1,hcnt2,hcnt3,hcnt4,ckph0,ckph1,ckph2,ckph3,ckph4,armed,notmo,cappend\n");
    end
    if (started && cyc < maxrows) begin
      sel = 0; actv = 0; oos = 0;
      // the slot index s (= 2*lane + slot) walked directly: a bench never
      // recomputes an RTL-internal index (gate_bench_indices)
      for (s = 0; s < 10; s = s + 1)
        actv = actv | (`E.l_actv[s] << s);
      for (l = 0; l < 5; l = l + 1) begin
        sel = sel | (`E.l_sel[l] << l);
        if (`E.l_hcnt[l] != 0) oos = oos | 8;
        // bit 4 (value 16) widened (Lean agent, TR-1 decisions): ANY armed lane,
        // timeout or not -- an armed winner takes the timeout-halt branch v1 lacks
        if (`E.l_armed[l]) oos = oos | 16;
        // bit 2 (value 4) widened (Lean agent, OOS GO): the STATE "a live lane's
        // head is a chaining re-arm" (REARM, level 0), not only its WB event --
        // want_fetch leaves that lane's spare empty, which v1 does not model.
        // Field offsets as pe_engine: op = act[W-1 -: 3], lvl = act[W-4-PINW].
        hd = `E.l_act[`E.hix[l]];
        if (`E.l_live[l] && `E.l_actv[`E.hix[l]]
            && ((hd >> (aw - 3)) & 7) == 7 && !((hd >> (aw - 4 - 4)) & 1))
          oos = oos | 4;
      end
      if ((`E.st == 1 || `E.st == 2)
          && `E.ck_act)                          oos = oos | 1;
      if (`E.st == 2 && `E.ck_hold_eff) oos = oos | 2;
      if (`E.st == 2 && `E.a_op == 3'd7
          && !`E.a_lvl)                           oos = oos | 4;
      if (!`E.run)                                oos = oos | 32;
      if (`E.config_err)                          oos = oos | 64;
      if (`E.hst == 1 || `E.hst == 2
          || `E.hst == 3)                         oos = oos | 128;
      // ---- TR-2 (PORT_SPEC §7): head kind, hold count, phase, arm masks ----
      // hkind: 0 ordinary, 1 looping re-arm, 2 chaining re-arm, 3 clocked
      // phase (SHIFT/SHIFTIN, level 1, real clock pin), 4 OP_ARM, 5 invalid
      armm = 0; notm = 0; capm = 0;
      for (l = 0; l < 5; l = l + 1) begin
        hd = `E.l_act[`E.hix[l]];
        hop = (hd >> (aw - 3)) & 7;
        hlv = (hd >> (aw - 4 - 4)) & 1;
        if (!`E.l_actv[`E.hix[l]])                       hk[l] = 5;
        else if (hop == 7)                               hk[l] = hlv ? 1 : 2;
        else if ((hop == 1 || hop == 2) && hlv
                 && `E.l_clkpin[l] < 12)                 hk[l] = 3;
        else if (hop == 6)                               hk[l] = 4;
        else                                             hk[l] = 0;
        armm = armm | (`E.l_armed[l] << l);
        notm = notm | (`E.l_notmo[l] << l);
        capm = capm | ((`E.l_ckwait[l] & `E.l_mode[l]) << l);
      end
      $fwrite(fd, "%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,",
              cyc, `E.now, `E.st, `E.cur,
              `E.pst, `E.pl, `E.prr,
              `E.pbr1, `E.pslot,
              `E.winner_v_q, `E.winner_q,
              `E.winner_v, `E.winner,
              `E.wb_dly,
              `E.l_timestamp[0], `E.l_timestamp[1],
              `E.l_timestamp[2], `E.l_timestamp[3],
              `E.l_timestamp[4], sel, actv, oos);
      $fwrite(fd, "%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d\n",
              hk[0], hk[1], hk[2], hk[3], hk[4],
              `E.l_hcnt[0], `E.l_hcnt[1], `E.l_hcnt[2], `E.l_hcnt[3],
              `E.l_hcnt[4],
              `E.l_ckph[0], `E.l_ckph[1], `E.l_ckph[2], `E.l_ckph[3],
              `E.l_ckph[4], armm, notm, capm);
      cyc = cyc + 1;
      if (cyc == maxrows) $fflush(fd);
    end
  end
endmodule
