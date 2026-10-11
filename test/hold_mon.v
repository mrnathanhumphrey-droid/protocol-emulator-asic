// hold_mon.v -- the SDA-hold gating offsets, on RTL signals (HC1; read by
// model/gate_hold_offset.py). A second top beside tb_trace; sampled at
// negedge + 1 (cycle-t values). One line per hold load:
//   HOLD lane t_dec t_drive t_load t_zero t_hz t_ready t_rdue t_drv2 contended
// t_dec   = the last IDLE cycle before the loading DRIVE (winner_v & winner == l)
// t_drive = the loading DRIVE
// t_load  = first cycle l_hcnt[l] != 0
// t_zero  = first cycle after t_load with l_hcnt[l] == 0
// t_hz    = first cycle after t_load with hz_q[l] == 1  (the hold term of ready)
// t_ready = first cycle after t_load with ready[l] == 1
// t_rdue  = first cycle after t_load with rel_due[l] == 1
// t_drv2  = the lane's next DRIVE
// ⚠ `hold_ld` is a blocking temporary computed AT the edge that ends the DRIVE,
// so it reads 1 in the cycle AFTER the DRIVE: the DRIVE was cyc - 1.
`default_nettype none
`timescale 1ns / 1ps
module hold_mon;
`define HM_E tb_trace.dut.u_eng
  integer cyc = 0, l;
  integer st_p = 0, cur_p = 0, wv_p = 0, w_p = 0, st_pp = 0, wv_pp = 0, w_pp = 0;
  integer t_dec [0:4], t_drv [0:4], t_load [0:4], t_zero [0:4], t_hz [0:4],
          t_rdy [0:4], t_rdue [0:4], arm [0:4];
  initial for (l = 0; l < 5; l = l + 1) arm[l] = 0;
  always @(negedge tb_trace.clk) begin
    #1;
    if (tb_trace.dut.rst_n_s === 1'b1) begin
      if (`HM_E.st == 1 && `HM_E.cur < 5 && arm[`HM_E.cur] == 2 && cyc > t_drv[`HM_E.cur]) begin
        l = `HM_E.cur;
        $display("HOLD %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d", l, t_dec[l],
                 t_drv[l], t_load[l], t_zero[l], t_hz[l], t_rdy[l], t_rdue[l],
                 cyc, (t_rdy[l] >= 0 && t_rdy[l] < cyc - 1) ? 1 : 0);
        arm[l] = 0;
      end
      if (`HM_E.hold_ld === 1'b1 && st_p == 1 && cur_p < 5 && arm[cur_p] == 0) begin
        l = cur_p;
        arm[l] = 1; t_drv[l] = cyc - 1;
        t_dec[l] = (st_pp == 0 && wv_pp == 1 && w_pp == l) ? cyc - 2 : -1;
        t_load[l] = -1; t_zero[l] = -1; t_hz[l] = -1; t_rdy[l] = -1; t_rdue[l] = -1;
      end
      for (l = 0; l < 5; l = l + 1) if (arm[l] != 0) begin
        if (t_load[l] < 0 && `HM_E.l_hcnt[l] != 0) begin t_load[l] = cyc; arm[l] = 2; end
        else if (t_load[l] >= 0) begin
          if (t_zero[l] < 0 && `HM_E.l_hcnt[l] == 0) t_zero[l] = cyc;
          if (t_hz[l]   < 0 && `HM_E.hz_q[l] === 1'b1) t_hz[l] = cyc;
          if (t_rdy[l]  < 0 && `HM_E.ready[l] === 1'b1) t_rdy[l] = cyc;
          if (t_rdue[l] < 0 && `HM_E.rel_due[l] === 1'b1) t_rdue[l] = cyc;
        end
      end
      st_pp = st_p; wv_pp = wv_p; w_pp = w_p;
      st_p = `HM_E.st; cur_p = `HM_E.cur; wv_p = `HM_E.winner_v; w_p = `HM_E.winner;
    end
    cyc = cyc + 1;
  end
endmodule
