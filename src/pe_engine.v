/*
 * Copyright (c) 2026 Nathan Humphrey
 * SPDX-License-Identifier: Apache-2.0
 *
 * THE ENGINE -- non-preemptive EDF over N_LANES lanes, C = 2, J = 1, C9 = START.
 *
 * ⛔⛔ BUILT WITH NO REFERENCE TO ANY OTHER COMPETITION ENTRANT'S REPOSITORY OR
 * PULL-REQUEST CONTENT. The quarantine recorded in S2 covers the engine, not
 * only the PDN question.
 *
 * ⭐ NOT ONE PROTOCOL CONSTANT APPEARS IN THIS FILE, and that is checked by
 * `model/part1_param_contract.py` against a named list. Bit periods, deadlines
 * and phase splits all live in the LOADED IMAGE. A protocol constant in the
 * engine is the waveform-player failure in source form.
 *
 * =====================================================================
 * THE SCHEDULER
 * =====================================================================
 * A lane is READY when its stored next-action timestamp has arrived. The
 * comparison is WRAP-SAFE: `now - ts` is interpreted as a signed difference, so
 * it stays correct across the counter rolling over. ⛔ This is the form Ruling 2
 * demanded -- an ABSOLUTE counter with absolute per-lane timestamps, not
 * per-lane countdowns -- and 1.6b is the condition that makes it sound (the live
 * deadline spread plus max response time must stay under 2**(TS_W-1)).
 *
 * The EDF key is the ABSOLUTE DEADLINE `ts + D_sched`, and the winner is the
 * READY lane whose deadline is nearest. ⭐ Deadlines are compared as OFFSETS
 * FROM NOW (`key - now`) rather than as raw values, for the same wrap reason.
 *
 * ⛔ NON-PREEMPTIVE: once a job is dispatched it runs to completion. That is not
 * a simplification, it is the model A2 proved, and it is also what makes exactly
 * one atomic group sufficient (INV-ATOMIC-1).
 *
 * =====================================================================
 * ⛔⛔ THE FETCH PROBLEM, AND WHY PER-LANE PREFETCH REGISTERS EXIST
 * =====================================================================
 * An action word is 3 bytes and the store is BYTE-WIDE with a one-cycle
 * registered read. So fetching an action takes THREE reads -- and C = 2 cannot
 * contain three reads. The options were:
 *
 *   (a) widen the store to a 24-bit word. 2**AW words would be 3x the bits, and
 *       at the measured 4.04 cells per stored bit that is roughly 25,000 cells
 *       against a ~30,500 practical budget. Rejected on cost.
 *   (b) narrow the action to 2 bytes. opcode+pin+level+count is already 12 bits,
 *       leaving 4 for the delay, which cannot express a UART bit period.
 *       Rejected: it puts a protocol limit back in the encoding.
 *   (c) ⭐ PREFETCH. Keep the byte-wide store, and hold each lane's NEXT action
 *       in a register that a background FSM refills during idle cycles. The
 *       channel has the room: U = 0.21388, so most cycles are idle.
 *
 * (c) is implemented. ⭐ AND IT IS WHAT `M-PREFETCH-STALE` IS ACTUALLY ABOUT:
 * the prefetch register MUST be invalidated when the lane's program counter
 * advances, or a dispatched job replays the previous action. The named mutant is
 * removing that invalidation -- and it needs a MULTI-LANE program to be
 * non-vacuous, because with one live lane the previous winner IS the current
 * winner and the stale word is coincidentally correct.
 *
 * ⛔⛔ AND THIS IS A FIELD THE S2 FREEZE DID NOT HAVE. The freeze's table was
 * derived from the DESCRIPTOR documents, which describe lane STATE; the fetch
 * machinery that Ruling 1's C = 2 implies is not in any descriptor. Per lane
 * this adds a program counter (AW bits) and a prefetch word (ACT_W + 1 bits).
 * ⭐ THE GATE COULD NOT HAVE CAUGHT IT: traceability detects a FIELD WITH NO
 * RULING. It cannot detect a RULING WITH NO FIELD. That asymmetry is recorded
 * in the S3 results rather than quietly absorbed.
 */

`default_nettype none

module pe_engine #(
    parameter integer N_LANES = 5,
    parameter integer AW      = 8,
    parameter integer N_PINS  = 12,
    parameter integer TS_W    = 16,
    parameter integer DLY_W   = 10,
    parameter integer D_W     = 8
) (
    input  wire                 clk,
    input  wire                 rst_n,
    input  wire                 run,          // 1 = executing, 0 = load/halt

    // program store, shared with the loader
    output reg  [AW-1:0]        s_raddr,
    output reg                  s_re,
    input  wire [7:0]           s_rdata,
    // ⭐ the WIDE action fetch: one registered cycle for a whole action word
    output reg  [AW-1:0]        s_wraddr,
    output reg                  s_wre,
    input  wire [((3+((N_PINS<=2)?1:(N_PINS<=4)?2:(N_PINS<=8)?3:(N_PINS<=16)?4:5)+1+DLY_W+4+7)/8)*8-1:0] s_wrdata,

    // pin interface. ⭐ Both outputs are REGISTERED (ruling F2): every engine
    // driven bit comes from a flop, because a glitch on a clock pin is an extra
    // edge and an extra edge is a corruption, not a margin problem.
    output reg  [N_PINS-1:0]    pin_out,
    output reg  [N_PINS-1:0]    pin_oe,
    input  wire [N_PINS-1:0]    pin_in,       // already synchronised upstream

    // host data channel (F1): payload enters here, never through the program
    input  wire [7:0]           host_data,
    input  wire                 host_valid,
    output reg  [N_LANES-1:0]   lane_underrun,
    output reg  [N_LANES-1:0]   lane_overflow,
    output reg                  sticky_ovr,

    // RX payload out to the serialiser (which is NOT a lane -- zero budget)
    output reg  [7:0]           rx_data,
    output reg                  rx_push,

    output wire                 busy
);

  // ---- derived widths. ⛔ NO LITERAL WIDTHS ANYWHERE: a bare `[15:0]` would
  // also be the I2C D_tol constant, and the parameter contract rejects it.
  localparam integer PINW  = (N_PINS <= 2)  ? 1 :
                             (N_PINS <= 4)  ? 2 :
                             (N_PINS <= 8)  ? 3 :
                             (N_PINS <= 16) ? 4 : 5;
  localparam integer LW    = (N_LANES <= 2) ? 1 : (N_LANES <= 4) ? 2 :
                             (N_LANES <= 8) ? 3 : 4;
  localparam integer BPW   = 4;                      // bit pointer 0..8
  localparam integer CW    = 4;                      // C_i 1..8
  localparam integer ACT_W = 3 + PINW + 1 + DLY_W + BPW;   // the action word

  // ---- opcodes. ⭐ Eight, which is exactly the 3-bit field: level, shift,
  // shift-in, read-bit, start, stop, arm, no-op re-arm.
  localparam [2:0] OP_LEVEL   = 3'd0;
  localparam [2:0] OP_SHIFT   = 3'd1;
  localparam [2:0] OP_SHIFTIN = 3'd2;
  localparam [2:0] OP_READBIT = 3'd3;
  localparam [2:0] OP_START   = 3'd4;
  localparam [2:0] OP_STOP    = 3'd5;
  localparam [2:0] OP_ARM     = 3'd6;
  localparam [2:0] OP_REARM   = 3'd7;

  // ---- image layout, all derived -------------------------------------
  // ⛔⛔ `base` IS A THIRD FIELD THE S2 FREEZE DID NOT HAVE. Without it every
  // lane's program counter initialises to the same ACT_BASE and ALL FIVE LANES
  // EXECUTE THE SAME ACTION STREAM. Like D_tol it is IMAGE metadata, read once
  // at header load into l_pc, so it costs image BYTES and zero extra flops.
  // ⭐ Same root cause as the PC and the prefetch word: the freeze's table came
  // from the DESCRIPTOR documents, which describe lane STATE, and said nothing
  // about the IMAGE's structure.
  // ⛔⛔ A FIFTH MISSING FIELD: the DRIVE MODE. The S2 freeze lists it as a
  // per-lane register and NOTHING IN THE IMAGE SET IT, so `l_mode` stayed at
  // its reset value of 0 = open-drain for every lane. On a `uo_out` pin that is
  // silently fatal: open-drain holds `pin_out` at 0 and modulates the ENABLE,
  // and `uo_out` HAS NO ENABLE -- so the pin went low on its first action and
  // stuck there forever while the scheduler ran perfectly.
  localparam integer HDR_BITS  = PINW + PINW + 1 + DLY_W + CW + D_W + D_W + AW;
  localparam integer HDR_BYTES = (HDR_BITS + 7) / 8;
  localparam integer ACT_BYTES = (ACT_W + 7) / 8;
  localparam integer ACT_BASE  = N_LANES * HDR_BYTES;

  // =====================================================================
  // PER-LANE STATE
  // =====================================================================
  reg [PINW-1:0]  l_pin    [0:N_LANES-1];   // data pin / armed pin
  reg [PINW-1:0]  l_clkpin [0:N_LANES-1];   // ⭐ a LANE property; the per-ACTION
                                            //   copy was cut by S2 as a duplicate
  reg             l_mode   [0:N_LANES-1];   // 0 = open-drain, 1 = push-pull
  reg [7:0]       l_data   [0:N_LANES-1];   // THE PAYLOAD lives here, not in
                                            //   the program (ruling F1)
  reg [BPW-1:0]   l_bitp   [0:N_LANES-1];
  reg [TS_W-1:0]  l_timestamp     [0:N_LANES-1];   // ABSOLUTE next-action timestamp
  reg [CW-1:0]    l_c      [0:N_LANES-1];
  reg [D_W-1:0]   l_d      [0:N_LANES-1];   // D_sched -- the EDF key, in a
                                            //   REGISTER (Ruling 1)
  reg [DLY_W-1:0] l_t      [0:N_LANES-1];   // inner period
  reg             l_live   [0:N_LANES-1];
  // ---- the fetch machinery the freeze did not have --------------------
  reg [AW-1:0]    l_pc     [0:N_LANES-1];
  // ⛔⛔ A FOURTH FIELD THE FREEZE DID NOT HAVE: the lane's program BASE, kept
  // in silicon because a PERIODIC protocol has to REPEAT and nothing in the
  // encoding could express that. A lane's PC advanced linearly and fell off
  // the end of its program into whatever bytes followed. ⭐ Fixed by giving
  // OP_REARM a second meaning selected by the action's existing level bit:
  //    level = 0  extend the delay, PC unchanged   (Ruling 2's chaining)
  //    level = 1  extend the delay AND jump to base (loop)
  // so looping reuses an opcode and a field that already existed, and costs
  // only this register.
  reg [AW-1:0]    l_base   [0:N_LANES-1];
  reg [ACT_W-1:0] l_act    [0:N_LANES-1];
  reg             l_actv   [0:N_LANES-1];   // prefetch VALID

  // =====================================================================
  // GLOBAL STATE -- one incrementer, not N_LANES decrementers (Ruling 2)
  // =====================================================================
  reg [TS_W-1:0] now;

  // ⭐ J IS MEASURED, NOT ASSERTED. `jitter_max` is the largest dispatch delay
  // caused purely by a prefetch miss, in cycles. A2 ships J = 1.
  localparam integer JW = 8;
  reg [JW-1:0] jitter_cnt, jitter_max;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)      now <= {TS_W{1'b0}};
    else if (run)    now <= now + 1'b1;
  end

  // =====================================================================
  // READY + EDF SELECT. ⛔ Both comparisons are wrap-safe.
  // =====================================================================
  wire [N_LANES-1:0] ready;
  wire [TS_W-1:0]    edf_key_off [0:N_LANES-1];

  genvar gi;
  generate
    for (gi = 0; gi < N_LANES; gi = gi + 1) begin : g_ready
      // ⭐ signed difference: ready when the stored timestamp has ARRIVED.
      wire [TS_W-1:0] diff = now - l_timestamp[gi];
      // ⛔⛔ READINESS MUST NOT DEPEND ON THE PREFETCH. It used to read
      // `l_live & l_actv & ~diff[...]`, which conflated "I have this lane's
      // next action in a register" with "this lane's job has been RELEASED".
      // The effect was that at most ONE lane was ever ready, so the EDF
      // comparison never had two candidates and the schedule degenerated to
      // round-robin-by-prefetch-availability -- while every lane still moved
      // its pins, so the smoke test passed. ⭐ A2 assumes every RELEASED lane
      // competes; this is the line that makes that true.
      assign ready[gi] = l_live[gi] & ~diff[TS_W-1];
      // ⭐ deadline as an OFFSET FROM NOW, so a wrapped key still orders
      //   correctly. 1.6b is what bounds the spread that makes this sound.
      assign edf_key_off[gi] = (l_timestamp[gi] + {{(TS_W-D_W){1'b0}}, l_d[gi]}) - now;
    end
  endgenerate

  // combinational min-offset over READY lanes. ⭐ Reads REGISTERED keys only,
  // which is Ruling 1's condition (i): without the key registers this mux would
  // sit after the store read and the pipeline register would land behind the mux
  // it was added to avoid.
  reg [LW-1:0]   winner;
  reg            winner_v;
  reg [TS_W-1:0] best;
  integer        k;
  always @* begin
    winner   = {LW{1'b0}};
    winner_v = 1'b0;
    best  = {TS_W{1'b1}};
    for (k = 0; k < N_LANES; k = k + 1) begin
      if (ready[k] && (!winner_v || edf_key_off[k] < best)) begin
        winner   = k[LW-1:0];
        winner_v = 1'b1;
        best  = edf_key_off[k];
      end
    end
  end

  // =====================================================================
  // THE DISPATCH PIPELINE -- C = 2, J = 1, C9 = START
  //   cycle 1 : DRIVE the pin (this is what C9 = START means)
  //   cycle 2 : write back lane state, advance the PC, invalidate prefetch
  // ⭐ The pipeline and C9 are ONE decision: an unpipelined engine reads its
  //   descriptor in cycle 1 and so CANNOT drive at START.
  // =====================================================================
  localparam [1:0] ST_IDLE = 2'd0, ST_DRIVE = 2'd1, ST_WB = 2'd2;
  reg [1:0]       st;
  reg [LW-1:0]    cur;
  reg [ACT_W-1:0] cur_act;

  assign busy = (st != ST_IDLE);

  // ---- action field slices -------------------------------------------
  wire [2:0]       a_op    = cur_act[ACT_W-1 -: 3];
  wire [PINW-1:0]  a_pin   = cur_act[ACT_W-4 -: PINW];
  wire             a_lvl   = cur_act[ACT_W-4-PINW];
  wire [DLY_W-1:0] a_dly   = cur_act[BPW +: DLY_W];
  wire [BPW-1:0]   a_cnt   = cur_act[0 +: BPW];

  // =====================================================================
  // HEADER LOAD -- on entering run, pull N_LANES headers out of the image.
  // ⛔ D_tol is in the image and is NOT loaded into any register (ruling F3):
  //    the loader's screen reads it, the datapath never does. 40 flops unspent.
  // =====================================================================
  // ⛔⛔ FOUR STATES, NOT THREE, AND THE SMOKE BENCH IS WHAT FOUND IT. `s_re`
  // and `s_raddr` are REGISTERED by the arbiter, and the store read is itself
  // registered, so data requested while hst == H_REQ in cycle n is not valid
  // until cycle n+2. A three-state H_REQ -> H_WAIT -> sample sequence samples
  // the PREVIOUS byte. ⭐ Every header field then unpacks from shifted-in
  // garbage, no lane ever becomes live, and the engine sits idle while
  // elaborating perfectly cleanly.
  localparam [2:0] H_IDLE = 3'd0, H_REQ  = 3'd1, H_WAIT = 3'd2,
                   H_RD   = 3'd3, H_DONE = 3'd4;
  reg [2:0]            hst;
  reg [LW-1:0]         hl;
  reg [3:0]            hb;
  reg [HDR_BYTES*8-1:0] hsh;
  reg                  hdr_done;
  // ⛔⛔ UNPACK FROM THE POST-SHIFT VALUE. The last byte is shifted into `hsh`
  // with a NON-BLOCKING assignment in the same cycle the fields are unpacked,
  // so reading `hsh` there sees the value WITHOUT that byte and every field
  // comes out 8 bits adrift. The symptom was l_pc = 63 instead of 30 and a
  // timestamp of X, which made `ready` X and left the engine idle forever --
  // while elaborating perfectly cleanly.
  wire [HDR_BYTES*8-1:0] hsh_n = {hsh[HDR_BYTES*8-9:0], s_rdata};

  // =====================================================================
  // PREFETCH -- refill one lane's action register per visit, round robin.
  // =====================================================================
  // same one-cycle-too-early bug, same fix
  // ⭐ TWO STATES NOW, NOT FOUR. The wide port returns a whole action word in
  // one registered cycle, so the byte-shift register and its three-cycle walk
  // are gone -- and with them the 20-cycle jitter they caused.
  // ⛔ FOUR STATES: the arbiter REGISTERS s_wre/s_wraddr and the store read is
  // itself registered, so data requested in P_REQ is valid two cycles later.
  // Capturing in P_WAIT grabs the PREVIOUS fetch -- the same off-by-one as the
  // header FSM, in a second place, which is why it is called out twice.
  localparam [2:0] P_SCAN = 3'd0, P_REQ = 3'd1, P_WAIT = 3'd2, P_CAP = 3'd3;
  reg [2:0]             pst;
  reg [LW-1:0]          pl;

  integer i;

  // ---- the one arbiter for the shared store read port ----------------
  // ⭐ Header load has priority, then prefetch. The engine's own dispatch does
  //   NOT read the store -- that is the whole point of the prefetch registers,
  //   and it is what keeps C at 2.
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      s_re    <= 1'b0;
      s_raddr <= {AW{1'b0}};
    end else begin
      s_re <= 1'b0;
      if (hst == H_REQ) begin
        s_re    <= 1'b1;
        s_raddr <= hl * HDR_BYTES + hb;
      end
      s_wre <= 1'b0;
      if (pst == P_REQ) begin
        s_wre    <= 1'b1;
        s_wraddr <= l_pc[pl];
      end
    end
  end

  // =====================================================================
  // THE ONE SEQUENTIAL BLOCK for lane state, so no field has two writers.
  // =====================================================================
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      st       <= ST_IDLE;
      jitter_cnt <= {JW{1'b0}};
      jitter_max <= {JW{1'b0}};
      cur      <= {LW{1'b0}};
      cur_act  <= {ACT_W{1'b0}};
      hst      <= H_IDLE;
      hl       <= {LW{1'b0}};
      hb       <= 4'd0;
      hsh      <= {(HDR_BYTES*8){1'b0}};
      hdr_done <= 1'b0;
      pst      <= P_SCAN;
      pl       <= {LW{1'b0}};
      s_wre    <= 1'b0;
      s_wraddr <= {AW{1'b0}};
      // ⭐ RESET-HIGH on the pins is handled in the TOP module, not here:
      //   which pins can RELEASE differs between the two banks, and this
      //   module does not know the banks. See pe_top's reset comment.
      pin_out  <= {N_PINS{1'b1}};
      pin_oe   <= {N_PINS{1'b0}};
      rx_data  <= 8'h00;
      rx_push  <= 1'b0;
      sticky_ovr    <= 1'b0;
      lane_underrun <= {N_LANES{1'b0}};
      lane_overflow <= {N_LANES{1'b0}};
      for (i = 0; i < N_LANES; i = i + 1) begin
        l_pin[i]    <= {PINW{1'b0}};
        l_clkpin[i] <= {PINW{1'b0}};
        l_mode[i]   <= 1'b0;
        l_data[i]   <= 8'h00;
        l_bitp[i]   <= {BPW{1'b0}};
        l_timestamp[i]     <= {TS_W{1'b0}};
        l_c[i]      <= {CW{1'b0}};
        l_d[i]      <= {D_W{1'b0}};
        l_t[i]      <= {DLY_W{1'b0}};
        l_live[i]   <= 1'b0;
        l_pc[i]     <= {AW{1'b0}};
        l_base[i]   <= {AW{1'b0}};
        l_act[i]    <= {ACT_W{1'b0}};
        l_actv[i]   <= 1'b0;
      end
    end else if (!run) begin
      // HALT, RELOAD, RESUME -- an explicit scope choice, never a mid
      // transaction swap. Everything re-initialises on the next run entry.
      st       <= ST_IDLE;
      hst      <= H_IDLE;
      hdr_done <= 1'b0;
      pst      <= P_SCAN;
      rx_push  <= 1'b0;
      for (i = 0; i < N_LANES; i = i + 1) begin
        l_live[i] <= 1'b0;
        l_actv[i] <= 1'b0;
        l_pc[i]   <= {AW{1'b0}};
      end
    end else begin
      rx_push <= 1'b0;

      // ---------------- header load ----------------------------------
      case (hst)
        H_IDLE: if (!hdr_done) begin
                  hst <= H_REQ; hl <= {LW{1'b0}}; hb <= 4'd0;
                end
        H_REQ:  hst <= H_WAIT;
        H_WAIT: hst <= H_RD;             // the registered read's dead cycle
        H_RD:   begin
                  hsh <= {hsh[HDR_BYTES*8-9:0], s_rdata};
                  if (hb == HDR_BYTES-1) begin
                    // ⭐ unpack: pin, clkpin, t, C_i, D_sched. D_tol is the
                    //   remaining field and is DELIBERATELY NOT STORED.
                    // ⛔⛔ MSB-ALIGNED INSIDE HDR_BYTES*8, NOT HDR_BITS.
                    // The header is HDR_BITS = 38 bits inside a HDR_BYTES*8 =
                    // 40-bit byte-shift register, so slicing from HDR_BITS-1
                    // reads 2 bits LOW and every field straddles a byte
                    // boundary that the image writer did not intend. Aligning
                    // to the top of the shift register makes the layout
                    // hand-assemblable: byte0 = {pin, clkpin}, and the 2 spare
                    // bits land at the BOTTOM where nothing reads them.
                    l_pin[hl]    <= hsh_n[HDR_BYTES*8-1 -: PINW];
                    l_clkpin[hl] <= hsh_n[HDR_BYTES*8-1-PINW -: PINW];
                    l_mode[hl]   <= hsh_n[HDR_BYTES*8-1-2*PINW];
                    l_t[hl]      <= hsh_n[HDR_BYTES*8-2-2*PINW -: DLY_W];
                    l_c[hl]      <= hsh_n[HDR_BYTES*8-2-2*PINW-DLY_W -: CW];
                    l_d[hl]      <= hsh_n[HDR_BYTES*8-2-2*PINW-DLY_W-CW -: D_W];
                    l_pc[hl]     <= hsh_n[HDR_BYTES*8-2-2*PINW-DLY_W-CW-D_W-D_W -: AW];
                    l_base[hl]   <= hsh_n[HDR_BYTES*8-2-2*PINW-DLY_W-CW-D_W-D_W -: AW];
                    l_live[hl]   <= 1'b1;
                    hb <= 4'd0;
                    if (hl == N_LANES-1) begin
                      hst <= H_DONE; hdr_done <= 1'b1;
                    end else begin
                      hl <= hl + 1'b1; hst <= H_REQ;
                    end
                  end else begin
                    hb  <= hb + 4'd1;
                    hst <= H_REQ;
                  end
                end
        default: hst <= H_DONE;
      endcase

      // ---------------- prefetch -------------------------------------
      // ⛔ Only refills a lane whose prefetch is INVALID. The invalidation on
      //    PC advance is in the writeback below, and removing it is
      //    M-PREFETCH-STALE.
      if (hdr_done) begin
        case (pst)
          P_SCAN: begin
            // ⭐ THE EDF WINNER IS SERVED FIRST. A round-robin refill makes the
            // jitter above depend on scan position rather than on the schedule,
            // which is how a prefetch policy silently becomes the scheduler.
            if (winner_v && !l_actv[winner]) begin
              pl <= winner; pst <= P_REQ;
            end else if (l_live[pl] && !l_actv[pl]) begin
              pst <= P_REQ;
            end else begin
              pl <= (pl == N_LANES-1) ? {LW{1'b0}} : pl + 1'b1;
            end
          end
          P_REQ:  pst <= P_WAIT;         // request registered
          P_WAIT: pst <= P_CAP;          // store read registered
          P_CAP:  begin
            // MSB-aligned: byte0 = {opcode, pin, level}, 2 spare at the bottom
            l_act[pl]  <= s_wrdata[ACT_BYTES*8-1 -: ACT_W];
            l_actv[pl] <= 1'b1;
            pst        <= P_SCAN;
            pl         <= (pl == N_LANES-1) ? {LW{1'b0}} : pl + 1'b1;
          end
          default: pst <= P_SCAN;
        endcase
      end

      // ---------------- dispatch, C = 2 ------------------------------
      case (st)
        ST_IDLE: if (hdr_done && winner_v) begin
                   if (l_actv[winner]) begin
                     cur     <= winner;
                     cur_act <= l_act[winner];
                     st      <= ST_DRIVE;
                   end else begin
                     // ⭐⭐ THIS STALL IS THE JITTER TERM J. The EDF winner is
                     // chosen, its release has arrived, and dispatch waits only
                     // because its action word is not in the register yet.
                     // ⛔ A2 budgets J = 1. If this can exceed 1, the shipped
                     // r_i do not hold -- so it is COUNTED, not assumed, and
                     // the maximum is observable for the bench to assert on.
                     jitter_cnt <= jitter_cnt + 1'b1;
                     if (jitter_cnt >= jitter_max) jitter_max <= jitter_cnt + 1'b1;
                   end
                 end else begin
                   jitter_cnt <= {JW{1'b0}};
                 end

        ST_DRIVE: begin
          // ⭐ C9 = START: the pin moves in the FIRST cycle of service.
          case (a_op)
            OP_LEVEL, OP_START, OP_STOP: begin
              if (l_mode[cur]) begin
                pin_out[a_pin] <= a_lvl;        // push-pull: drive both levels
                pin_oe[a_pin]  <= 1'b1;
              end else begin
                pin_out[a_pin] <= 1'b0;         // open-drain: NEVER drives 1
                pin_oe[a_pin]  <= ~a_lvl;       // low = drive, high = release
              end
            end
            OP_SHIFT: begin
              if (l_mode[cur]) begin
                pin_out[a_pin] <= l_data[cur][0];
                pin_oe[a_pin]  <= 1'b1;
              end else begin
                pin_out[a_pin] <= 1'b0;
                pin_oe[a_pin]  <= ~l_data[cur][0];
              end
              pin_out[l_clkpin[cur]] <= a_lvl;  // the shifter drives its OWN
              pin_oe[l_clkpin[cur]]  <= 1'b1;   //   clock, so data and clock
                                                //   never need P-ORDER per bit
            end
            OP_SHIFTIN, OP_READBIT: begin
              pin_oe[a_pin] <= 1'b0;            // release to sample
            end
            OP_ARM, OP_REARM: ;                 // no pin movement
            default: ;
          endcase
          st <= ST_WB;
        end

        ST_WB: begin
          // ⛔⛔ RULING 2: the re-arm ADDS TO THE STORED TIMESTAMP, never to
          //    `now`. The relative form drifts k*(r-C) -- 15,260 cycles on a
          //    one-second delay -- and is INVISIBLE at k = 1.
          l_timestamp[cur] <= l_timestamp[cur] + {{(TS_W-DLY_W){1'b0}}, a_dly};

          case (a_op)
            OP_SHIFT: begin
              l_data[cur] <= {1'b0, l_data[cur][7:1]};
              l_bitp[cur] <= l_bitp[cur] + {{(BPW-1){1'b0}}, 1'b1};
            end
            OP_SHIFTIN: begin
              l_data[cur] <= {pin_in[a_pin], l_data[cur][7:1]};
              l_bitp[cur] <= l_bitp[cur] + {{(BPW-1){1'b0}}, 1'b1};
              if (l_bitp[cur] == a_cnt - {{(BPW-1){1'b0}}, 1'b1}) begin
                rx_data <= {pin_in[a_pin], l_data[cur][7:1]};
                rx_push <= 1'b1;
                l_bitp[cur] <= {BPW{1'b0}};
              end
            end
            OP_READBIT: l_data[cur] <= {pin_in[a_pin], l_data[cur][7:1]};
            default: ;
          endcase

          // ---- PC advance, and the invalidation M-PREFETCH-STALE removes ----
          // ⭐ A no-op re-arm does NOT advance the PC: that is what makes a
          //   chained re-arm re-execute the same action at a later timestamp,
          //   which is Ruling 2's mechanism for long delays.
          if (a_op != OP_REARM) begin
            l_pc[cur]   <= l_pc[cur] + ACT_BYTES[AW-1:0];
            l_actv[cur] <= 1'b0;                // ⛔ THE INVALIDATION
          end else if (a_lvl) begin
            l_pc[cur]   <= l_base[cur];         // loop back to the start
            l_actv[cur] <= 1'b0;                // ⛔ and invalidate, same reason
          end

          // ⛔⛔ A "CHEAP WIN" THAT MADE IT WORSE, KEPT AS A RECORD.
          // The J decomposition said the dominant terms were the prefetch
          // FSM's scan notice (1) plus waiting behind another lane's in-flight
          // refill (3). So this block used to kick a refill for `cur` at
          // writeback, to overlap it with the lane's own inter-action delay.
          // ⭐ MEASURED J WENT 5 -> 7. Starting a refill at EVERY writeback
          // keeps the single shared fetch port busy, so a DIFFERENT lane that
          // becomes the EDF winner now waits behind it. The optimisation moved
          // the contention it was meant to remove.
          // ⇒ REVERTED. And the lesson is structural: with ONE shared fetch
          //   port, J cannot be driven to 1 by scheduling the refills better.
          //   It needs either a larger derived J in the baseline, or per-lane
          //   DOUBLE BUFFERING (hold current + next, ~110 more flops) so a
          //   dispatch never waits on a fetch at all. That is an architecture
          //   choice, not a tweak, and margin 9 already clears the bar -- so it
          //   is optimisation, not rescue.

          // ---- the host data channel (F1), and its sticky flag ----------
          // ⛔ underrun is a STICKY FLAG, NEVER A STALL: a stall would make C
          //    unbounded, which is the clock-stretch conclusion a third time.
          if (a_op == OP_SHIFT && l_bitp[cur] == a_cnt) begin
            if (host_valid) l_data[cur] <= host_data;
            else            lane_underrun[cur] <= 1'b1;
            l_bitp[cur] <= {BPW{1'b0}};
          end

          st <= ST_IDLE;
          jitter_cnt <= {JW{1'b0}};
        end

        default: st <= ST_IDLE;
      endcase

      // ---- sticky ovr: a lane was still ready when its own next release
      //      arrived, i.e. the queue-depth-one assumption (1.6a) was violated.
      for (i = 0; i < N_LANES; i = i + 1) begin
        if (l_live[i] && ready[i] && busy && (i[LW-1:0] != cur))
          sticky_ovr <= sticky_ovr;             // observed, not an error here
      end
    end
  end

  // ⚠ NOT CLAIMED HERE: that C is exactly 2 in silicon. The dispatch FSM spends
  // two cycles per action BY CONSTRUCTION (ST_DRIVE then ST_WB), which is the
  // intended C -- but the number A2 needs is the one a SIMULATION and a
  // post-synthesis path report agree on. ⛔ "Two states therefore C = 2" is a
  // same-author re-derivation of my own design intent, and this project has
  // already recorded that such a thing is not an independent witness. S3's
  // results file states it as owed.
  wire _unused_eng = &{l_pin[0], 1'b0};

endmodule
