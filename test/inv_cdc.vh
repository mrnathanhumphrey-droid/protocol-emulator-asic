/* inv_cdc.vh -- RULING CDC2 D5: the SPI-target CS async clear is benign.
 *
 * `miso_oe_q` is cleared ASYNCHRONOUSLY while CS is high (`src/project.v`),
 * and that clear is RELEASED by CS falling -- at any instant relative to
 * `clk`, so the release can land inside the flop's recovery window. It is
 * harmless only if the flop's D input (`miso_oe_d`) is 0 on the first two
 * clock edges after CS falls; then a marginal release resolves to 0 either
 * way. ⛔ The first version of this check ARGUED that from the engine's own
 * synchroniser and was refuted on the first CS fall of corpus_sptgt (D = 1:
 * the engine holds the enable between transactions) -- silicon fix #6, which
 * qualifies D with the synchronised CS. This checks the D net on exactly
 * those edges, in every bench with a DUT, and counts the falls it examined
 * so a vacuous pass is visible. Must-fire: M_CS_RAW_D.
 * Included INSIDE a module; `INV_DUT` names the instance (default `dut`).
 */
`ifndef INV_DUT
`define INV_DUT dut
`endif
reg     inv_cs_q   = 1'b1;
integer inv_cs_age = 99;
integer inv_cs_n   = 0;
integer inv_cs_run = 0;   // v2 (option 1): the falls while the engine RAN
always @(posedge `INV_DUT.clk) begin
  if (`INV_DUT.rst_n === 1'b1) begin
    if (inv_cs_q === 1'b1 && `INV_DUT.uio_in[`INV_DUT.CS_PIN] === 1'b0) begin
      inv_cs_age = 0;
      inv_cs_n   = inv_cs_n + 1;
      if (`INV_DUT.eng_run === 1'b1) inv_cs_run = inv_cs_run + 1;
    end else if (inv_cs_age < 99) begin
      inv_cs_age = inv_cs_age + 1;
    end
    // reads the flop's ACTUAL D net, so M_CS_RAW_D (silicon fix #6 undone)
    // fires here and the fix passes
    if (inv_cs_age <= 1 && `INV_DUT.miso_oe_d !== 1'b0) begin
      $display("*** FAIL inv_cdc: miso_oe_q's D input is %b on edge %0d after CS fell -- a marginal async release of the CS clear could resolve to 1 (CDC2 D5, silicon fix #6)",
               `INV_DUT.miso_oe_d, inv_cs_age);
      $finish;
    end
  end
  inv_cs_q = `INV_DUT.uio_in[`INV_DUT.CS_PIN];
end
// ⭐ v2: the total includes the LOAD (every load write strobes the shared
// pins), so it grows with the store; the run count is the comparable one
final if (inv_cs_n > 0) $display("  inv_cdc: %0d CS fall(s) checked, %0d while the engine ran", inv_cs_n, inv_cs_run);
