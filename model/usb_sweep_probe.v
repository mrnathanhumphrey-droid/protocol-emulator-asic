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
  integer k;
  always @(negedge tb_usbrx.clk) if (tb_usbrx.run_go === 1'b1) begin
    // (b') (Wilson 11-14): a stall is now a lane RELEASED with an EMPTY head
    // (`pf_rdy`), one line per such lane -- the winner never has an empty head
    for (k = 0; k < 5; k = k + 1)
      if (tb_usbrx.dut.u_eng.rdy_rel[k] === 1'b1 && tb_usbrx.dut.u_eng.hv[k] === 1'b0)
        $display("STL %0d %0d", tb_usbrx.cyc, k);
    if (tb_usbrx.dut.u_eng.pst === 3'd1 && tb_usbrx.dut.u_eng.pbr1 === 1'b1)
      $display("B1 %0d %0d", tb_usbrx.cyc, tb_usbrx.dut.u_eng.pl);
    if (tb_usbrx.dut.u_eng.st === 2'd2 && tb_usbrx.dut.u_eng.cur === 0
        && tb_usbrx.dut.u_eng.act_retire === 1'b1)
      $display("RT %0d %0d", tb_usbrx.cyc, tb_usbrx.dut.u_eng.a_op);
  end
endmodule
