/* branch_check.vh -- BRANCH_BIT's bench-side checks (v2 primitive 1, Wilson 10-26/27).
 *
 * Included by test/tb_equiv.v, ON only with +BRCHECK=1 (so gate_v2_equiv's
 * v1-RTL builds are untouched). Two checks, computed HERE from the word's own
 * fields and the image -- never from the engine's branch logic:
 *   (1) THE PC CHOICE: at a BRANCH_BIT writeback the expected next PC is
 *       `pin_in[pin] == level ? ACT_BASE + ACT_BYTES * target : pc + ACT_BYTES`;
 *       that lane's NEXT dispatch must be at exactly that PC.
 *   (2) THE HEAD IS THE IMAGE: every dispatched word equals the image's word at
 *       the lane's PC -- the buffer-swap invariant, which is what a word fetched
 *       PAST a branch (M_BR_FETCH_PAST) breaks.
 * And Wilson's R2 measurement under option A, per branch: the successor's
 * LATENESS (its dispatch minus its OWN release -- the branch's release plus
 * the branch's wait W) and the STALL cycles (lane released, head slot empty).
 * ⛔ Every message is a plain literal (progress.vh's lesson).
 */
integer bc_dbg, bc_on, bc_k, bc_wb = 0, bc_taken = 0, bc_not = 0, bc_bad = 0, bc_inv = 0;
integer bc_disp = 0, bc_late_max = 0, bc_late_sum = 0, bc_late_n = 0, bc_stall = 0;
integer bc_exp [0:7];
integer bc_rel [0:7];
integer bc_pc, bc_tgt, bc_late, bc_samp, bc_samp_max = 0, bc_samp_sum = 0;
integer bc_ctl, bc_ctl_n = 0, bc_ctl_max = 0, bc_ctl_sum = 0;   // R2b's CONTROL
reg     bc_bit;
reg [PE_ACT_W-1:0] bc_word;
initial begin
  if (!$value$plusargs("BRCHECK=%d", bc_on)) bc_on = 0;
  if (!$value$plusargs("BRDBG=%d", bc_dbg)) bc_dbg = 0;
  for (bc_k = 0; bc_k < 8; bc_k = bc_k + 1) begin bc_exp[bc_k] = -1; bc_rel[bc_k] = 0; end
end

always @(posedge clk) if (rst_n === 1'b1 && bc_on != 0 && !done) begin
  // ---- stalls: a lane whose successor is owed (after a branch), released, head empty
  for (bc_k = 0; bc_k < 5; bc_k = bc_k + 1)
    if (bc_exp[bc_k] >= 0 && dut.u_eng.rel_due[bc_k] === 1'b1 &&
        dut.u_eng.l_actv[dut.u_eng.hix[bc_k]] !== 1'b1)
      bc_stall = bc_stall + 1;
  // ---- (1) a BRANCH_BIT writeback: the expected next PC, from the word itself
  if (dut.u_eng.st == 2 && dut.u_eng.a_op == PE_N_BUILT_OPS - 1) begin
    bc_bit = (dut.u_eng.a_pin < 12) ? dut.u_eng.pin_in[dut.u_eng.a_pin] : 1'b0;
    bc_tgt = PE_ACT_BASE + PE_ACT_BYTES * (dut.u_eng.a_dly % 128);
    bc_pc  = dut.u_eng.l_pc[dut.u_eng.cur];
    if (bc_bit === dut.u_eng.a_lvl) begin
      bc_exp[dut.u_eng.cur] = bc_tgt;  bc_taken = bc_taken + 1;
    end else begin
      bc_exp[dut.u_eng.cur] = bc_pc + PE_ACT_BYTES;  bc_not = bc_not + 1;
    end
    // the SUCCESSOR's own release: the branch's plus its wait W (R2c: a
    // timed branch; reading the branch's release alone counted W as lateness)
    bc_rel[dut.u_eng.cur] = dut.u_eng.l_timestamp[dut.u_eng.cur] + dut.u_eng.wb_dly;
    // the SAMPLE-TIME jitter: the branch reads its bit at writeback, this
    // late after its own release (Wilson R2: priced like READBIT's J?)
    bc_samp = (dut.u_eng.now - dut.u_eng.l_timestamp[dut.u_eng.cur]) & 16'hFFFF;
    bc_samp_sum = bc_samp_sum + bc_samp;
    if (bc_samp > bc_samp_max) bc_samp_max = bc_samp;
    bc_wb = bc_wb + 1;
  end
  // ---- a dispatch: (1) the PC after a branch, (2) the head is the image
  if (dut.u_eng.st == 1) begin
    bc_disp = bc_disp + 1;
    bc_pc   = dut.u_eng.l_pc[dut.u_eng.cur];
    if (bc_exp[dut.u_eng.cur] >= 0) begin
      if (bc_pc != bc_exp[dut.u_eng.cur]) begin
        if (bc_bad < 5)
          $display("*** FAIL branch_check: lane %0d dispatched pc %0d after a branch, expected %0d", dut.u_eng.cur, bc_pc, bc_exp[dut.u_eng.cur]);
        bc_bad = bc_bad + 1;
      end
      bc_late = (dut.u_eng.now - bc_rel[dut.u_eng.cur]) & 16'hFFFF;
      bc_late_sum = bc_late_sum + bc_late;  bc_late_n = bc_late_n + 1;
      if (bc_late > bc_late_max) bc_late_max = bc_late;
      if (bc_dbg != 0)
        $display("BRDBG suc lane %0d op %0d late %0d now %0d", dut.u_eng.cur, dut.u_eng.cur_act[PE_ACT_W-1 -: PE_OP_W], bc_late, dut.u_eng.now);
      bc_exp[dut.u_eng.cur] = -1;
    end else if (dut.u_eng.cur_act[PE_ACT_W-1 -: PE_OP_W] != PE_N_BUILT_OPS - 1) begin
      // the CONTROL (Wilson R2b): an ordinary action -- not a branch, not a
      // branch's successor -- dispatch minus its own release
      bc_ctl = (dut.u_eng.now - dut.u_eng.l_timestamp[dut.u_eng.cur]) & 16'hFFFF;
      bc_ctl_sum = bc_ctl_sum + bc_ctl;  bc_ctl_n = bc_ctl_n + 1;
      if (bc_ctl > bc_ctl_max) bc_ctl_max = bc_ctl;
      if (bc_dbg != 0)
        $display("BRDBG ctl lane %0d op %0d late %0d now %0d", dut.u_eng.cur, dut.u_eng.cur_act[PE_ACT_W-1 -: PE_OP_W], bc_ctl, dut.u_eng.now);
    end
    bc_word = {img[bc_pc], img[bc_pc + 1], img[bc_pc + 2], img[bc_pc + 3]};
    if (dut.u_eng.cur_act !== bc_word) begin
      if (bc_inv < 5)
        $display("*** FAIL branch_check: lane %0d dispatched %h at pc %0d, the image holds %h there", dut.u_eng.cur, dut.u_eng.cur_act, bc_pc, bc_word);
      bc_inv = bc_inv + 1;
    end
  end
end

final if (bc_on != 0)
  $display("BRCHECK wb=%0d taken=%0d not=%0d pc_bad=%0d head_bad=%0d dispatches=%0d late_n=%0d late_max=%0d late_sum=%0d stall_cycles=%0d samp_max=%0d samp_sum=%0d ctl_n=%0d ctl_max=%0d ctl_sum=%0d cfgerr=%0d live1=%0d", bc_wb, bc_taken, bc_not, bc_bad, bc_inv, bc_disp, bc_late_n, bc_late_max, bc_late_sum, bc_stall, bc_samp_max, bc_samp_sum, bc_ctl_n, bc_ctl_max, bc_ctl_sum, dut.u_eng.config_err, dut.u_eng.l_live[1]);
