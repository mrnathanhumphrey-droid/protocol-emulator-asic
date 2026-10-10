`default_nettype none
`timescale 1ns / 1ps

/* This testbench just instantiates the module and makes some convenient wires
   that can be driven / tested by the cocotb test.py.
*/
module tb ();

  // Dump the signals to a FST file. You can view it with gtkwave or surfer.
  initial begin
    $dumpfile("tb.fst");
    $dumpvars(0, tb);
    #1;
  end

  // Wire up the inputs and outputs:
  reg clk;
  reg rst_n;
  reg ena;
  reg [7:0] ui_in;
  // ⛔⛔ THE BUS IS RESOLVED IN VERILOG, BY THE SAME INCLUDE THE OTHER BENCHES
  // USE. `uio_in` used to be a `reg` that cocotb wrote directly, which meant
  // the electrical layer existed a THIRD time -- in Python -- and for most of
  // its life it was a CONSTANT 0xFF: pull-ups modelled, the DUT's pull-downs
  // not, so the bus never TRANSITIONED. Two open-drain tests then hung the
  // moment the engine started parking on an observed SCL rise.
  // ⇒ cocotb now drives the PEER SIDE (`ob_oe`/`ob_val`) and reads the
  //   resolved wire, exactly as a peer model does in tb_trace.
  wire [7:0] uio_in;
  reg  [7:0] ob_oe  = 8'h00;   // the bench side: nothing driven at reset
  reg  [7:0] ob_val = 8'h00;
  wire [7:0] uo_out;
  wire [7:0] uio_out;
  wire [7:0] uio_oe;

  // ⭐⭐ THE BUFFER DEPTH, SO THE COCOTB SUITE RUNS AT BOTH PARAMETER POINTS.
  // `iverilog -Ptb.SPL_CFG=1` builds the single-buffer engine under the same
  // toplevel CI uses. ⛔ Four benches kept a private copy of an RTL index that
  // silently assumed SPL = 2 and each broke the moment SPL = 1 existed, so the
  // suite sweeps the parameter instead of trusting that nothing assumes it.
  parameter integer SPL_CFG = 2;

  // ⛔⛔⛔ THE PARAMETER OVERRIDE IS RTL-ONLY, AND OMITTING THIS GUARD BROKE A
  // CHECKPOINT HARDEN. At gate level `user_project` is the flat synthesised
  // netlist, which has NO PARAMETERS, so `#(.SPL(...))` is an elaboration
  // error:
  //     test/tb.v:33: error: parameter `SPL' not found in `tb.user_project'.
  // `gl_test` died in 55 seconds on it, after `gds` had already spent 3h50m
  // and `precheck` 2h11m succeeding.
  // ⚠ WHY NOTHING CAUGHT IT: gate-level elaboration happens ONLY inside the
  // ~4-hour harden. CI's `test` job and `run_param_points.py` both build the
  // RTL, so the parameter was added, swept at two values, and never once
  // elaborated the way `gl_test` does. `ci/run_gates.sh` now does that in
  // under a second against a parameterless stub.
  // ⭐ SPL IS BAKED INTO THE GATES ANYWAY. The harden synthesises the default
  // SPL = 2, so there is nothing to override at gate level -- the override is
  // meaningful only where the source is still parametric.
`ifdef GL_TEST
  tt_um_protocol_emulator user_project (
`else
  tt_um_protocol_emulator #(.SPL(SPL_CFG)) user_project (
`endif
      .ui_in  (ui_in),    // Dedicated inputs
      .uo_out (uo_out),   // Dedicated outputs
      .uio_in (uio_in),   // IOs: Input path
      .uio_out(uio_out),  // IOs: Output path
      .uio_oe (uio_oe),   // IOs: Enable path (active high: 0=input, 1=output)
      .ena    (ena),      // enable - goes high when design is selected
      .clk    (clk),      // clock
      .rst_n  (rst_n)     // not reset
  );

`include "test/od_bus.vh"
// PR2: cur_ck == l_clkpin[cur] on every cycle. RTL only -- the gate-level
// netlist has no `u_eng` hierarchy to read.
`ifndef GL_TEST
`define INV_DUT user_project
`include "test/inv_curck.vh"
`endif

endmodule
