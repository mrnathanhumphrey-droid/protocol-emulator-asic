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
// ⛔⛔ REDEFINED BY (b') (Wilson 11-14): the dispatcher no longer picks a lane
// with an empty head, so "a winner with an empty head" never occurs and the old
// predicate would read 0 HOLLOWLY. A lane is now late for its own word exactly
// while it is RELEASED with an EMPTY head (`rdy_rel & ~hv`, pe_engine.v -- NOT `pf_rdy`, which counts only once the schedule runs, and this probe measures the start-up) -- one line
// per such lane per cycle, charged to that lane.
module usb_startup_probe;
  integer k;
  always @(negedge tb_usbrx.clk) if (tb_usbrx.run_go === 1'b1) begin
    for (k = 0; k < 5; k = k + 1)
      if (tb_usbrx.dut.u_eng.rdy_rel[k] === 1'b1 && tb_usbrx.dut.u_eng.hv[k] === 1'b0)
        $display("JS %0d %0d %0d", tb_usbrx.cyc, k, tb_usbrx.dut.u_eng.primed);
  end
endmodule
