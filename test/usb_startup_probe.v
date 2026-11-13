// usb_startup_probe.v -- THE START-UP STALL ON THE USB LANE, MEASURED (Wilson 11-13, D)
//
// A second top-level beside tb_usbrx (iverilog -s tb_usbrx -s usb_startup_probe),
// reading the engine hierarchically, so tb_usbrx.v itself is unchanged (it is an
// input of the CDC sweep records).
//
// ⭐ THE STALL, AS AGENT 2 DEFINED IT (the 76 cycles Wilson's ruling D is about):
// ST_IDLE, a winner chosen, the winner not armed, its head word not valid.
// ⚠ THIS IS WIDER THAN THE RTL'S jitter branch (pe_engine.v ST_IDLE), which also
// needs `primed`: before the program is primed the engine may not dispatch at
// all, so those cycles are a stall in this sense and NOT a jitter count. The
// probe prints `primed` per cycle so the runner can say how many are which.
// Sampled at the negedge (every posedge update settled; `winner`, `w_hv`,
// `w_armed` are the combinational picks of the state the next posedge acts on).
//   JS <cyc> <lane> <primed>   one stall cycle, charged to the winning lane
module usb_startup_probe;
  always @(negedge tb_usbrx.clk) if (tb_usbrx.run_go === 1'b1) begin
    if (tb_usbrx.dut.u_eng.st === 2'd0 && tb_usbrx.dut.u_eng.winner_v === 1'b1
        && tb_usbrx.dut.u_eng.w_armed === 1'b0 && tb_usbrx.dut.u_eng.w_hv === 1'b0)
      $display("JS %0d %0d %0d", tb_usbrx.cyc, tb_usbrx.dut.u_eng.winner,
               tb_usbrx.dut.u_eng.primed);
  end
endmodule
