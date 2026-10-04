/* param_dump.v -- let the TOOLS say what the Verilog parameters resolve to.
 *
 * ⛔⛔ WHY THIS REPLACES A PARSER. `gate_one_encoder` first read the widths with
 * a regex plus a hand-written Verilog-ternary translator -- a SECOND, SAME-HAND
 * implementation of Verilog constant semantics. It failed in the worst way: a
 * parsing miss reports "not found", which is indistinguishable from a real drift
 * finding, and it was chased twice. The next unusual expression -- a function,
 * a `$clog2`, a deeper ternary -- would do it again.
 * ⇒ The simulators are the authority on what Verilog means. This module
 *   instantiates the REAL top and prints the resolved values by HIERARCHICAL
 *   REFERENCE, so nothing is recomputed anywhere.
 * ⭐ Elaborated by BOTH iverilog and Verilator, because agreement between two
 *   independent elaborators is the same argument the cycle-exact trace rests on.
 */
`default_nettype none
`timescale 1ns / 1ps

module param_dump;
  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00;
  wire [7:0] uo_out, uio_out, uio_oe;
  reg  [7:0] uio_in = 8'h00;

  tt_um_protocol_emulator dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );

  initial begin
    $display("PARAM PINW=%0d",      dut.u_eng.PINW);
    $display("PARAM DLY_W=%0d",     dut.u_eng.DLY_W);
    $display("PARAM BQW=%0d",       dut.u_eng.BQW);
    $display("PARAM ACT_W=%0d",     dut.u_eng.ACT_W);
    $display("PARAM ACT_BYTES=%0d", dut.u_eng.ACT_BYTES);
    $display("PARAM HDR_BITS=%0d",  dut.u_eng.HDR_BITS);
    $display("PARAM HDR_BYTES=%0d", dut.u_eng.HDR_BYTES);
    $display("PARAM N_LANES=%0d",   dut.u_eng.N_LANES);
    $display("PARAM AW=%0d",        dut.u_eng.AW);
    $display("PARAM CW=%0d",        dut.u_eng.CW);
    $display("PARAM D_W=%0d",       dut.u_eng.D_W);
    $display("PARAM N_UIO=%0d",     dut.u_eng.N_UIO);
    $finish;
  end
endmodule

`default_nettype wire
