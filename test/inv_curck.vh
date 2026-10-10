/* inv_curck.vh -- RULING PR2: the registered clock pin equals the select it
 * replaced, on EVERY cycle, in every bench with a DUT.
 *
 *   cur_ck  == l_clkpin[cur]
 *   cur_ckr == (l_clkpin[cur] < N_PINS)
 *
 * `src/pe_engine.v` drives every DRIVE/WB clock-pin access from `cur_ck`
 * instead of the 5-way `l_clkpin[cur]` select; the fix is cycle-identical
 * only if this holds, so it is checked here rather than argued. Sampled at
 * negedge: both sides are register outputs that settled after the posedge.
 * Included INSIDE a module; `INV_DUT` names the instance (default `dut`).
 */
`ifndef INV_DUT
`define INV_DUT dut
`endif
always @(negedge `INV_DUT.clk) begin
  if (`INV_DUT.rst_n === 1'b1
      && (`INV_DUT.u_eng.cur_ck
              !== `INV_DUT.u_eng.l_clkpin[`INV_DUT.u_eng.cur]
          || `INV_DUT.u_eng.cur_ckr
              !== (`INV_DUT.u_eng.l_clkpin[`INV_DUT.u_eng.cur]
                   < `INV_DUT.u_eng.N_PINS))) begin
    $display("*** FAIL inv_curck: cur=%0d cur_ck=%0d cur_ckr=%0d but l_clkpin[cur]=%0d -- the registered clock pin (PR2) no longer mirrors the select it replaced",
             `INV_DUT.u_eng.cur, `INV_DUT.u_eng.cur_ck, `INV_DUT.u_eng.cur_ckr,
             `INV_DUT.u_eng.l_clkpin[`INV_DUT.u_eng.cur]);
    $finish;
  end
end
