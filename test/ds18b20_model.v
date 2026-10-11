/* ds18b20_model.v -- a BEHAVIOURAL DS18B20 (VDD-powered), written from the
 * datasheet, with TIMING-WINDOW CHECKS that fail the run.
 *
 * ⛔⛔ A SAME-HAND MODEL. It was written by the same hand as the 1-Wire
 * program it judges (test/onewire.py, model/pe_proto.py OneWire), so it can
 * share a misreading of the datasheet with it. The FOREIGN witness is the
 * real DS18B20 on order, at FPGA bring-up. Nothing here may be quoted as
 * "the part accepts it".
 *
 * SOURCE: Analog Devices (Maxim) DS18B20 datasheet 19-7487; Rev 6; 7/19.
 * Every number below is from its "AC Electrical Characteristics" table
 * (p. 3) or the "1-Wire Signaling" section (pp. 15-16):
 *   tSLOT 60..120 us; tREC >= 1 us; tLOW0 60..120 us; tLOW1 1..15 us;
 *   tRDV 15 us; tRSTH >= 480 us; tRSTL >= 480 us; tPDHIGH 15..60 us;
 *   tPDLOW 60..240 us; tCONV 750 ms max at 12 bits.
 *   "The DS18B20 samples the 1-Wire bus during a window that lasts from 15us
 *   to 60us after the master initiates the write time slot."
 *   "Output data from the DS18B20 is valid for 15us after the falling edge
 *   that initiated the read time slot."
 *   VDD mode, after Convert T: "the DS18B20 will respond by transmitting a 0
 *   while the temperature conversion is in progress and a 1 when the
 *   conversion is done."
 *   "Infinite recovery time can occur between bits so long as the 1-Wire bus
 *   is in the inactive (high) state during the recovery period." -- so the
 *   tSLOT MAXIMUM is not checkable from the wire alone; the slot's bounded
 *   parts are (tLOW0 <= 120 is).
 *
 * WORST-CASE DEVICE CHOICES, so the master's margins are tested, not given:
 *   * a read-0 is held for EXACTLY tRDV = 15 us from the master's fall (the
 *     guaranteed minimum) -- a master sampling after 15 us reads 1;
 *   * the write sample is the WHOLE 15..60 us window: a write slot whose line
 *     changes inside it is a VIOLATION (this is "low < 15 or low >= 60");
 *   * presence wait and pulse are parameters (defaults 30 / 120 us).
 * ⚠ tCONV IS SHORTENED (T_CONV_NS, default 2.5 ms) to keep the simulation
 * short; the program POLLS for completion, so it is independent of tCONV.
 *
 * Plusargs: FLIPROM=<bit 0..63> flips one ROM bit AFTER its CRC is computed
 * (the CRC must-fire).
 * Reports: `OW-T <name> n= min_ns= max_ns= lo_ns= hi_ns= ok|VIOLATION`,
 * `*** FAIL ow-model: ...` per violation, `OW-MODEL ROM ..`, `OW-MODEL SP ..`.
 */
`timescale 1ns / 1ps
module ds18b20_model #(
    parameter integer T_PDH_NS  = 30000,
    parameter integer T_PDL_NS  = 120000,
    parameter integer T_RDV_NS  = 15000,
    parameter integer T_CONV_NS = 2500000
) (
    input  wire dq,          // the bus as the part sees it
    output reg  pull         // 1 = the part pulls the bus low
);
  // datasheet bounds, ns (AC Electrical Characteristics, 19-7487 Rev 6)
  localparam real TLOW1_MIN = 1000.0,   TLOW1_MAX = 15000.0;
  localparam real TLOW0_MIN = 60000.0,  TLOW0_MAX = 120000.0;
  localparam real TRSTL_MIN = 480000.0, TRSTH_MIN = 480000.0;
  localparam real TREC_MIN  = 1000.0,   TSLOT_MIN = 60000.0;

  localparam integer S_IDLE = 0, S_ROMCMD = 1, S_FUNC = 2, S_TXROM = 3,
                     S_TXSP = 4, S_CONV = 5, S_DEAD = 6, S_PRES = 7;
  integer    state;
  integer    nbit, n_viol, flip, i, k;
  reg  [7:0] cmd;
  reg  [7:0] rom [0:7];
  reg  [7:0] sp  [0:8];
  realtime   t_fall, t_rise, t_rst_rise, low, t_conv_done;
  reg        after_reset, have_rise, conv_on, txbit;

  // ---- per-type statistics ------------------------------------------------
  integer    st_n [0:5];
  real       st_mn [0:5], st_mx [0:5];
  localparam integer K_LOW1 = 0, K_LOW0 = 1, K_RSTL = 2, K_RSTH = 3,
                     K_REC = 4, K_SLOT = 5;

  task stat(input integer kk, input real v);
    begin
      if (st_n[kk] == 0 || v < st_mn[kk]) st_mn[kk] = v;
      if (st_n[kk] == 0 || v > st_mx[kk]) st_mx[kk] = v;
      st_n[kk] = st_n[kk] + 1;
    end
  endtask

  task viol(input [8*128-1:0] what, input real v);
    begin
      n_viol = n_viol + 1;
      if (n_viol <= 12)
        $display("*** FAIL ow-model: %0s = %0.1f ns at t=%0.1f ns", what, v, $realtime);
    end
  endtask

  // ---- Dallas CRC-8 (X^8 + X^5 + X^4 + 1, LSB first), datasheet Fig. 11 ---
  function [7:0] crc8_byte(input [7:0] c, input [7:0] b);
    integer j;
    reg [7:0] r;
    reg       fb;
    begin
      r = c;
      for (j = 0; j < 8; j = j + 1) begin
        fb = r[0] ^ b[j];
        r = {1'b0, r[7:1]};
        if (fb) r = r ^ 8'h8C;
      end
      crc8_byte = r;
    end
  endfunction

  task sp_crc;
    reg [7:0] c;
    begin
      c = 8'h00;
      for (k = 0; k < 8; k = k + 1) c = crc8_byte(c, sp[k]);
      sp[8] = c;
    end
  endtask

  initial begin
    pull = 1'b0; state = S_IDLE; nbit = 0; n_viol = 0; cmd = 8'h00;
    after_reset = 1'b0; have_rise = 1'b0; conv_on = 1'b0;
    t_fall = 0; t_rise = 0; t_rst_rise = 0; t_conv_done = 0;
    for (i = 0; i < 6; i = i + 1) begin st_n[i] = 0; st_mn[i] = 0; st_mx[i] = 0; end
    // ROM: family code 28h (datasheet "64-BIT LASERED ROM CODE"), a serial
    // number, and the CRC of the first 56 bits
    rom[0] = 8'h28; rom[1] = 8'hA2; rom[2] = 8'hC3; rom[3] = 8'h4D;
    rom[4] = 8'h05; rom[5] = 8'h00; rom[6] = 8'h00;
    rom[7] = 8'h00;
    for (k = 0; k < 7; k = k + 1) rom[7] = crc8_byte(rom[7], rom[k]);
    // scratchpad power-up state (datasheet Figure 9): 85 C = 0550h, TH, TL,
    // config (12-bit), FFh, reserved, 10h, CRC
    sp[0] = 8'h50; sp[1] = 8'h05; sp[2] = 8'h4B; sp[3] = 8'h46;
    sp[4] = 8'h7F; sp[5] = 8'hFF; sp[6] = 8'h0C; sp[7] = 8'h10;
    sp_crc;
    if ($value$plusargs("FLIPROM=%d", flip)) begin
      rom[flip / 8] = rom[flip / 8] ^ (8'h01 << (flip % 8));
      $display("OW-MODEL FLIPROM bit %0d (after the CRC was computed)", flip);
    end
    $display("OW-MODEL ROM %02h %02h %02h %02h %02h %02h %02h %02h",
             rom[0], rom[1], rom[2], rom[3], rom[4], rom[5], rom[6], rom[7]);
  end

  function tx_state(input integer s);
    tx_state = (s == S_TXROM) || (s == S_TXSP) || (s == S_CONV);
  endfunction

  // the bit the part sends in the read slot that starts now
  function next_txbit(input integer s);
    begin
      if (s == S_TXROM) next_txbit = (nbit < 64) ? rom[nbit / 8][nbit % 8] : 1'b1;
      else if (s == S_TXSP) next_txbit = (nbit < 72) ? sp[nbit / 8][nbit % 8] : 1'b1;
      else next_txbit = ($realtime >= t_conv_done);         // S_CONV
    end
  endfunction

  // ---- a MASTER fall: the bus falls while the part is not pulling ---------
  realtime t_prev_fall;
  reg      have_prev_fall, pres_done;
  initial begin have_prev_fall = 1'b0; pres_done = 1'b0; end
  // ⚠ the bus is X until the chip leaves reset: an edge counts only between
  // DEFINED levels, and only once the bus has been seen idle (high)
  reg seen_idle;
  initial seen_idle = 1'b0;
  always @(negedge dq) if (!pull && dq === 1'b0 && seen_idle) begin
    t_fall = $realtime;
    if (state == S_PRES) begin
      viol("master fall during the presence sequence (tRSTH)", t_fall - t_rst_rise);
    end else if (after_reset) begin
      stat(K_RSTH, t_fall - t_rst_rise);
      if (t_fall - t_rst_rise < TRSTH_MIN)
        viol("tRSTH (reset release -> next master fall) < 480 us", t_fall - t_rst_rise);
      after_reset = 1'b0;
    end else begin
      if (have_rise) begin
        stat(K_REC, t_fall - t_rise);
        if (t_fall - t_rise < TREC_MIN)
          viol("tREC (release -> next fall) < 1 us", t_fall - t_rise);
      end
      if (have_prev_fall) begin
        stat(K_SLOT, t_fall - t_prev_fall);
        if (t_fall - t_prev_fall < TSLOT_MIN + TREC_MIN)
          viol("slot (fall -> next fall) < tSLOT + tREC = 61 us", t_fall - t_prev_fall);
      end
    end
    t_prev_fall = t_fall;
    have_prev_fall = 1'b1;
    if (tx_state(state)) begin
      txbit = next_txbit(state);
      if (state != S_CONV) nbit = nbit + 1;
      if (!txbit) begin
        pull = 1'b1;                       // read-0: hold for exactly tRDV
        #(T_RDV_NS) pull = 1'b0;
      end
    end
  end

  // ---- the bus rises ------------------------------------------------------
  always @(posedge dq) if (dq === 1'b1) begin
    if (!seen_idle) begin
      seen_idle = 1'b1;                    // first defined high: the idle bus
    end else if (state == S_PRES) begin
      // the part's own presence pulse ending -- not a master event. The
      // command phase starts when the bus is actually back up.
      if (pres_done) begin
        pres_done = 1'b0;
        state = S_ROMCMD; after_reset = 1'b1; cmd = 8'h00; nbit = 0;
        have_rise = 1'b0;
      end
    end else begin
      low = $realtime - t_fall;
      if (low >= TRSTL_MIN) begin
        stat(K_RSTL, low);
        state = S_PRES;
        t_rst_rise = $realtime;
        nbit = 0;
        fork : presence
          begin
            #(T_PDH_NS) pull = 1'b1;
            #(T_PDL_NS) pres_done = 1'b1;
            pull = 1'b0;
          end
        join_none
      end else if (tx_state(state)) begin
        // a read slot (the part may have held it): the slot length is the
        // master's, judged fall-to-fall below; nothing to classify here
        have_rise = 1'b1;
        t_rise = $realtime;
      end else begin
        have_rise = 1'b1;
        t_rise = $realtime;
        if (low < TLOW1_MAX) begin
          stat(K_LOW1, low);
          if (low < TLOW1_MIN) viol("tLOW1 < 1 us", low);
          take_bit(1'b1);
        end else if (low >= TLOW0_MIN && low <= TLOW0_MAX) begin
          stat(K_LOW0, low);
          take_bit(1'b0);
        end else begin
          stat(K_LOW0, low);
          viol(low < TLOW0_MIN
               ? "write slot low inside the 15..60 us sample window (tLOW1 > 15 and tLOW0 < 60)"
               : "tLOW0 > 120 us (and < tRSTL)", low);
          take_bit(1'b0);
        end
      end
    end
  end

  task take_bit(input b);
    begin
      if (state == S_ROMCMD || state == S_FUNC) begin
        cmd = {b, cmd[7:1]};              // LSB first
        nbit = nbit + 1;
        if (nbit == 8) begin
          nbit = 0;
          if (state == S_ROMCMD) begin
            if (cmd == 8'h33) state = S_TXROM;
            else if (cmd == 8'hCC) state = S_FUNC;
            else state = S_DEAD;
          end else begin
            if (cmd == 8'h44) begin
              state = S_CONV;
              t_conv_done = $realtime + T_CONV_NS;
              conv_on = 1'b1;
            end else if (cmd == 8'hBE) state = S_TXSP;
            else state = S_DEAD;
          end
          $display("OW-MODEL cmd %02h at t=%0.1f ns -> state %0d", cmd, $realtime, state);
        end
      end
      // a write slot in any other state is ignored by the part
    end
  endtask

  // the conversion's result: +25.0625 C = 0191h (datasheet Table 1)
  always @(posedge conv_on) begin
    #(T_CONV_NS);
    sp[0] = 8'h91; sp[1] = 8'h01;
    sp_crc;
    conv_on = 1'b0;
    $display("OW-MODEL conversion done at t=%0.1f ns", $realtime);
  end

  task report;
    begin
      $display("OW-T tLOW1 n=%0d min_ns=%0.1f max_ns=%0.1f lo_ns=%0.1f hi_ns=%0.1f",
               st_n[K_LOW1], st_mn[K_LOW1], st_mx[K_LOW1], TLOW1_MIN, TLOW1_MAX);
      $display("OW-T tLOW0 n=%0d min_ns=%0.1f max_ns=%0.1f lo_ns=%0.1f hi_ns=%0.1f",
               st_n[K_LOW0], st_mn[K_LOW0], st_mx[K_LOW0], TLOW0_MIN, TLOW0_MAX);
      $display("OW-T tRSTL n=%0d min_ns=%0.1f max_ns=%0.1f lo_ns=%0.1f hi_ns=inf",
               st_n[K_RSTL], st_mn[K_RSTL], st_mx[K_RSTL], TRSTL_MIN);
      $display("OW-T tRSTH n=%0d min_ns=%0.1f max_ns=%0.1f lo_ns=%0.1f hi_ns=inf",
               st_n[K_RSTH], st_mn[K_RSTH], st_mx[K_RSTH], TRSTH_MIN);
      $display("OW-T tREC n=%0d min_ns=%0.1f max_ns=%0.1f lo_ns=%0.1f hi_ns=inf",
               st_n[K_REC], st_mn[K_REC], st_mx[K_REC], TREC_MIN);
      $display("OW-T tSLOT+tREC n=%0d min_ns=%0.1f max_ns=%0.1f lo_ns=%0.1f hi_ns=inf",
               st_n[K_SLOT], st_mn[K_SLOT], st_mx[K_SLOT], TSLOT_MIN + TREC_MIN);
      $display("OW-MODEL SP %02h %02h %02h %02h %02h %02h %02h %02h %02h",
               sp[0], sp[1], sp[2], sp[3], sp[4], sp[5], sp[6], sp[7], sp[8]);
      $display("OW-MODEL violations=%0d", n_viol);
    end
  endtask
endmodule
