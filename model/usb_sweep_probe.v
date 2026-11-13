// usb_sweep_probe.v -- the probes for model/gate_usb_sweep.py (Wilson 11-13, condition 4).
//
// A second top-level beside tb_usbrx (iverilog -s tb_usbrx -s usb_sweep_probe), reading the
// engine hierarchically, so tb_usbrx.v is unchanged (as test/usb_startup_probe.v does).
// Sampled at the negedge: every posedge update settled; the combinational picks are those of
// the state the next posedge acts on.
//   STL <cyc> <lane>   a dispatch stall: ST_IDLE, a winner chosen, not armed, its head invalid
//                      (pe_engine.v ST_IDLE, the w_hv else-branch; usb_nostall's NoStall)
//   B1  <cyc> <lane>   a refill issued by branch 1 (pst == P_REQ with pbr1, l.3084-3087)
//   RT  <cyc> <op>     a USB-lane retirement (st == ST_WB, cur == lane 0, act_retire l.2231)
module usb_sweep_probe;
  always @(negedge tb_usbrx.clk) if (tb_usbrx.run_go === 1'b1) begin
    if (tb_usbrx.dut.u_eng.st === 2'd0 && tb_usbrx.dut.u_eng.winner_v === 1'b1
        && tb_usbrx.dut.u_eng.w_armed === 1'b0 && tb_usbrx.dut.u_eng.w_hv === 1'b0)
      $display("STL %0d %0d", tb_usbrx.cyc, tb_usbrx.dut.u_eng.winner);
    if (tb_usbrx.dut.u_eng.pst === 3'd1 && tb_usbrx.dut.u_eng.pbr1 === 1'b1)
      $display("B1 %0d %0d", tb_usbrx.cyc, tb_usbrx.dut.u_eng.pl);
    if (tb_usbrx.dut.u_eng.st === 2'd2 && tb_usbrx.dut.u_eng.cur === 0
        && tb_usbrx.dut.u_eng.act_retire === 1'b1)
      $display("RT %0d %0d", tb_usbrx.cyc, tb_usbrx.dut.u_eng.a_op);
  end
endmodule
