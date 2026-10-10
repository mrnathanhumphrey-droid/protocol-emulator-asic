/* rx_e2e.vh -- RULING RX2: END-TO-END RECEIVE. The chip's received bytes must
 * equal what the WIRE carried, with no model of the chip's capture timing.
 *
 * ⛔⛔ WHY. Layer V-RX rebuilt every received bit from the pads AT THE CHIP'S
 * OWN CAPTURE INSTANT, and credited a capture to the next consume. When a
 * late HIGH dispatch let the LOW consume a bit before its capture (silicon
 * fix #7, 552 of ~3,300 lane-2 bits on corpus_all5 seed 1), the model made
 * the same mistake as the chip and agreed with it: 5 of the losses were
 * flagged, the rest PREDICTED. A reference that shares the design's timing
 * cannot catch a timing defect.
 *
 * THE REFERENCE HERE IS THE WIRE AT THE PROTOCOL'S SAMPLING EDGE:
 *   * each clocked bit a lane dispatches (its HIGH writeback) is queued in
 *     order, with whether it is a SHIFTIN and its data pin;
 *   * each RISING edge of that lane's LOGICAL clock -- the `uo_out` pad XOR
 *     its CLK_INV bit, or the resolved `uio` bus (an open-drain SCL rises
 *     when the bus does, stretch included) -- retires the OLDEST queued bit.
 *     The pairing is by ORDER only: no latency constant appears anywhere;
 *   * a SHIFTIN bit's value is the data pin's WIRE value at that edge (what
 *     the peer -- the FRAM, the I2C target -- drove, or the pull-up);
 *   * bits accumulate exactly as the chip's `l_rx` does ({bit, R[7:1]},
 *     reversed at the push on an MSB-first lane), and each push of a clocked
 *     receive must equal the next rebuilt byte, in order, per lane.
 * ⚠ SCOPE: CLOCKED receive (SPI master, I2C). An unclocked READBIT (UART-rx)
 * has no clock edge on the wire to anchor to; it stays on Layer V-RX.
 * Included INSIDE a module; `INV_DUT` names the instance (default `dut`).
 */
`ifndef INV_DUT
`define INV_DUT dut
`endif
reg [1:0]  e2e_q   [0:5*64-1];      // per lane ring: {is_rx, last}
reg [3:0]  e2e_qp  [0:5*64-1];      //   and the data pin
integer    e2e_qw  [0:4], e2e_qr [0:4];
reg [7:0]  e2e_R   [0:4];
reg [7:0]  e2e_x   [0:5*64-1];      // rebuilt bytes, per lane ring
integer    e2e_xw  [0:4], e2e_xr [0:4];
reg        e2e_clk_p [0:4];
integer    e2e_k, e2e_c, e2e_chk, e2e_bad, e2e_early, e2e_rxbits = 0;
reg        e2e_lc, e2e_b;
reg [7:0]  e2e_byte;
reg [7:0]  e2e_h1 = 8'h00, e2e_h2 = 8'h00;   // uio pad history (2 samples)
reg        ex1_capv [0:4];                    // EX1: this HIGH's capture landed
integer    ex1_capc [0:4];                    //      ...in this cycle
integer    ex1_cyc = 0, ex1_n = 0, ex1_bad = 0, ex1_edge = 0, ex1_dmin = 1 << 30;
initial for (e2e_k = 0; e2e_k < 5; e2e_k = e2e_k + 1) begin
  ex1_capv[e2e_k] = 1'b0; ex1_capc[e2e_k] = 0;
end
initial begin
  e2e_chk = 0; e2e_bad = 0; e2e_early = 0;
  for (e2e_k = 0; e2e_k < 5; e2e_k = e2e_k + 1) begin
    e2e_qw[e2e_k] = 0; e2e_qr[e2e_k] = 0; e2e_xw[e2e_k] = 0; e2e_xr[e2e_k] = 0;
    e2e_R[e2e_k] = 8'h00; e2e_clk_p[e2e_k] = 1'b0;
  end
end
always @(posedge `INV_DUT.clk) begin
  if (`INV_DUT.rst_n === 1'b1) begin
    // ---- a clocked HIGH writeback: queue the bit, in dispatch order -------
    if (`INV_DUT.u_eng.st === 2'd2 && `INV_DUT.u_eng.ck_act === 1'b1
        && `INV_DUT.u_eng.ck_is_high === 1'b1 && `INV_DUT.u_eng.cur < 5) begin
      e2e_k = `INV_DUT.u_eng.cur;
      if (`INV_DUT.u_eng.ck_shiftin === 1'b1) e2e_rxbits = e2e_rxbits + 1;
      e2e_q[e2e_k * 64 + (e2e_qw[e2e_k] % 64)] =
        {`INV_DUT.u_eng.ck_shiftin === 1'b1,
         `INV_DUT.u_eng.rx_bitp[e2e_k] == `INV_DUT.u_eng.a_cnt - 1};
      e2e_qp[e2e_k * 64 + (e2e_qw[e2e_k] % 64)] = `INV_DUT.u_eng.a_pin;
      e2e_qw[e2e_k] = e2e_qw[e2e_k] + 1;
    end
    // ---- an UNCLOCKED receive (SHIFTIN at level 0, READBIT) on the lane --
    // ⛔ IT SHARES THE ACCUMULATOR. `l_rx` takes clocked AND unclocked bits;
    // the first version rebuilt clocked bits only and drifted one bit per
    // transaction on corpus_i2c (lane 0's unclocked read between ACK slots).
    // An unclocked receive has no protocol clock edge on the wire: its
    // sampling instant IS the chip's writeback, the pin 2 samples back (the
    // measured input path) -- the same rule as Layer V-RX, and the reason
    // this layer's end-to-end claim is about CLOCKED receive.
    if (`INV_DUT.u_eng.st === 2'd2 && `INV_DUT.u_eng.cur < 5
        && `INV_DUT.u_eng.ck_act !== 1'b1
        && (`INV_DUT.u_eng.a_op === 3'd2 || `INV_DUT.u_eng.a_op === 3'd3)) begin
      e2e_k = `INV_DUT.u_eng.cur;
      e2e_c = `INV_DUT.u_eng.a_pin;
      e2e_b = (e2e_c < 8) ? e2e_h2[e2e_c] : 1'b0;
      e2e_R[e2e_k] = {e2e_b, e2e_R[e2e_k][7:1]};
      if (`INV_DUT.u_eng.rx_bitp[e2e_k] == `INV_DUT.u_eng.a_cnt - 1) begin
        e2e_x[e2e_k * 64 + (e2e_xw[e2e_k] % 64)] =
          (`INV_DUT.u_eng.l_order[e2e_k] === 1'b1)
            ? {e2e_R[e2e_k][0], e2e_R[e2e_k][1], e2e_R[e2e_k][2],
               e2e_R[e2e_k][3], e2e_R[e2e_k][4], e2e_R[e2e_k][5],
               e2e_R[e2e_k][6], e2e_R[e2e_k][7]}
            : e2e_R[e2e_k];
        e2e_xw[e2e_k] = e2e_xw[e2e_k] + 1;
      end
    end
    // ---- each lane's LOGICAL clock: a rising edge retires the oldest bit --
    for (e2e_k = 0; e2e_k < 5; e2e_k = e2e_k + 1) begin
      e2e_c = `INV_DUT.u_eng.l_clkpin[e2e_k];
      if (e2e_c >= 8 && e2e_c < 12)
        e2e_lc = `INV_DUT.uo_out[e2e_c - 8] ^ `INV_DUT.u_eng.pin_inv[e2e_c];
      else if (e2e_c < 8)
        e2e_lc = `INV_DUT.uio_in[e2e_c];
      else
        e2e_lc = 1'b0;
      if (e2e_lc === 1'b1 && e2e_clk_p[e2e_k] === 1'b0
          && e2e_qr[e2e_k] < e2e_qw[e2e_k]) begin
        if (e2e_q[e2e_k * 64 + (e2e_qr[e2e_k] % 64)][1]) begin
          e2e_c = e2e_qp[e2e_k * 64 + (e2e_qr[e2e_k] % 64)];
          e2e_b = (e2e_c < 8) ? `INV_DUT.uio_in[e2e_c] : 1'b0;
          e2e_R[e2e_k] = {e2e_b, e2e_R[e2e_k][7:1]};
          if (e2e_q[e2e_k * 64 + (e2e_qr[e2e_k] % 64)][0]) begin
            e2e_x[e2e_k * 64 + (e2e_xw[e2e_k] % 64)] =
              (`INV_DUT.u_eng.l_order[e2e_k] === 1'b1)
                ? {e2e_R[e2e_k][0], e2e_R[e2e_k][1], e2e_R[e2e_k][2],
                   e2e_R[e2e_k][3], e2e_R[e2e_k][4], e2e_R[e2e_k][5],
                   e2e_R[e2e_k][6], e2e_R[e2e_k][7]}
                : e2e_R[e2e_k];
            e2e_xw[e2e_k] = e2e_xw[e2e_k] + 1;
          end
        end
        e2e_qr[e2e_k] = e2e_qr[e2e_k] + 1;
      end
      e2e_clk_p[e2e_k] = e2e_lc;
    end
    // ---- the chip's push of a clocked receive: it must be the wire's byte -
    if (`INV_DUT.u_eng.rx_push === 1'b1 && `INV_DUT.u_eng.rx_lane < 5) begin
      e2e_k = `INV_DUT.u_eng.rx_lane;
      if (e2e_xr[e2e_k] < e2e_xw[e2e_k]) begin
        e2e_byte = e2e_x[e2e_k * 64 + (e2e_xr[e2e_k] % 64)];
        e2e_xr[e2e_k] = e2e_xr[e2e_k] + 1;
        e2e_chk = e2e_chk + 1;
        if (`INV_DUT.u_eng.rx_data !== e2e_byte) begin
          e2e_bad = e2e_bad + 1;
          if (e2e_bad <= 4)
            $display("*** FAIL rx_e2e: lane %0d received %02h, but the wire carried %02h at its clock edges (ruling RX2)",
                     e2e_k, `INV_DUT.u_eng.rx_data, e2e_byte);
        end
      end
    end
  end
  // ---- RULING EX1: the capture gate, checked DIRECTLY at every consume ---
  // At each push-pull clocked SHIFTIN consume the lane's capture must have
  // LANDED in an EARLIER cycle (the chip's consume reads `l_ckgot` before the
  // edge's capture sets it, so the consume is processed before this cycle's
  // capture). `d = consume - capture`: d >= 1 always (safety); d == 1 is the
  // gate's exact boundary -- a LOW decided while the capture was still
  // pending -- and its count is what tells the exact gate from a late one.
  if (`INV_DUT.rst_n === 1'b1) begin
    if (`INV_DUT.u_eng.st === 2'd2 && `INV_DUT.u_eng.cur < 5
        && `INV_DUT.u_eng.ck_shiftin === 1'b1
        && `INV_DUT.u_eng.ck_is_high === 1'b1)
      ex1_capv[`INV_DUT.u_eng.cur] = 0;           // this HIGH's capture owed
    if (`INV_DUT.u_eng.st === 2'd2 && `INV_DUT.u_eng.cur < 5
        && `INV_DUT.u_eng.ck_shiftin === 1'b1
        && `INV_DUT.u_eng.ck_consume === 1'b1
        && `INV_DUT.u_eng.l_mode[`INV_DUT.u_eng.cur] === 1'b1) begin
      e2e_k = `INV_DUT.u_eng.cur;
      ex1_n = ex1_n + 1;
      if (!ex1_capv[e2e_k]) begin
        ex1_bad = ex1_bad + 1;
        if (ex1_bad <= 4)
          $display("*** FAIL EX1: lane %0d consumed a push-pull clocked receive bit whose capture had NOT landed (ruling EX1)", e2e_k);
      end else begin
        if (ex1_cyc - ex1_capc[e2e_k] < ex1_dmin) ex1_dmin = ex1_cyc - ex1_capc[e2e_k];
        if (ex1_cyc - ex1_capc[e2e_k] == 1) ex1_edge = ex1_edge + 1;
      end
    end
    for (e2e_k = 0; e2e_k < 5; e2e_k = e2e_k + 1)
      if (`INV_DUT.u_eng.ck_hit[e2e_k] === 1'b1
          && `INV_DUT.u_eng.l_mode[e2e_k] === 1'b1) begin
        ex1_capv[e2e_k] = 1;
        ex1_capc[e2e_k] = ex1_cyc;
      end
  end
  ex1_cyc = ex1_cyc + 1;
  e2e_h2 = e2e_h1;                    // AFTER this cycle's uses
  e2e_h1 = `INV_DUT.uio_in;
end
// ⛔ A RECEIVE THAT NEVER COMPLETES IS A FAILURE, NOT "NOT EXERCISED". Found
// by M_CKRX_PP_OBSERVED after RX1: its capture never fires, the capture gate
// holds the lane, the receive DEADLOCKS -- and every layer, this one
// included, reported "not exercised" while the coarse liveness check passed
// on the other lanes. Clocked-receive bits were dispatched; no byte came out.
final begin
  if (ex1_n > 0 && ex1_bad != 0)
    $display("*** FAIL EX1: %0d of %0d push-pull clocked consumes had no landed capture", ex1_bad, ex1_n);
  else if (ex1_n > 0)
    $display("  EX1: ok -- %0d push-pull clocked consume(s), every capture landed first; min (consume - capture) = %0d, boundary consumes (= 1): %0d", ex1_n, ex1_dmin, ex1_edge);
  if (e2e_chk == 0 && e2e_rxbits > 0)
    $display("*** FAIL rx_e2e: %0d clocked receive bit(s) dispatched but NO received byte ever completed -- a receive lane is stuck (ruling RX2)", e2e_rxbits);
  else if (e2e_chk == 0)
    $display("  rx_e2e: 0 clocked received byte(s) -- NOT EXERCISED");
  else if (e2e_bad != 0)
    $display("*** FAIL rx_e2e: %0d of %0d clocked received byte(s) differ from the wire", e2e_bad, e2e_chk);
  else
    $display("  rx_e2e: ok -- %0d clocked received byte(s) equal the wire at their clock edges", e2e_chk);
end
