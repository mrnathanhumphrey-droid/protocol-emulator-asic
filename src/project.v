/*
 * Copyright (c) 2026 Nathan Humphrey
 * SPDX-License-Identifier: Apache-2.0
 *
 * TOP -- the pin banks, the mode control, the program loader, the readback
 * serialiser, and the SPI-target MISO release path.
 *
 * ⛔⛔ BUILT WITH NO REFERENCE TO ANY OTHER COMPETITION ENTRANT'S REPOSITORY OR
 * PULL-REQUEST CONTENT (the S2 quarantine covers the engine, not only the PDN).
 *
 * =====================================================================
 * THE TWO BANKS, AND WHY THE SPLIT IS BY ELECTRICAL CLASS
 * =====================================================================
 * `uo_out` is output-only AND ALWAYS DRIVEN. `uio` has an enable. So the split
 * is not by DIRECTION -- on that axis an SPI target's MISO is just "an output"
 * and lands on `uo_out`, which is exactly the error the pin table used to
 * contain. The question is whether a pin must be able to STOP DRIVING:
 *
 *   push-pull output      drive 0 and 1            -> either bank
 *   input                 not drive at all         -> uio
 *   open-drain (I2C)      release, pull-up wins    -> uio ONLY
 *   tri-state target MISO release, another target  -> uio ONLY
 *                         drives the shared line
 *
 * ⭐ Primary evidence for the last row is the part this demo writes: MB85RS64V's
 * own pin table says that with CS high the device "is in deselect (standby)
 * status and SO becomes High-Z".
 *
 * MAP:  pin index 0..7   -> uio[0..7]
 *       pin index 8..11  -> uo_out[0..3]   (the push-pull protocol outputs)
 *       uo_out[4..6]                       (the 3-pin serial host view)
 *       uo_out[7]                          (spare -- PUSH-PULL ONLY)
 * ⛔ `uio` is EXACTLY FULL at 8 of 8. The one spare `uo_out` pin can absorb
 *    another push-pull output and NOTHING ELSE: the constraint moved banks when
 *    MISO moved, it did not loosen.
 *
 * =====================================================================
 * ⛔⛔ RESET, AND A REFINEMENT TO "RESET HIGH"
 * =====================================================================
 * The ruling was: protocol outputs reset HIGH, because `uo_out` cannot go
 * high-Z and pin roles are per program, so reset cannot know which pin is CS --
 * and HIGH is simultaneously inactive for every role (UART TX idles high, CS is
 * inactive high, SCLK/MOSI are ignored while CS is high).
 *
 * ⭐ THAT REASONING IS SPECIFIC TO `uo_out`, AND `uio` CAN DO BETTER. A `uio`
 * pin CAN release, and releasing is strictly safer than driving a level onto a
 * bus whose other devices are unknown at reset. So:
 *       uo_out protocol pins  -> reset HIGH   (forced: release is impossible)
 *       uio pins              -> reset RELEASED (oe = 0; available, so used)
 * The ruling's REASON applies where its premise does. Recorded as a refinement
 * rather than silently implemented.
 *
 * ⛔ Program start drives the idle levels and asserts CS LAST.
 *
 * =====================================================================
 * ⛔⛔ THE MISO RELEASE PATH, AND A SCOPE LIMIT IT FORCES
 * =====================================================================
 * 1.6r: release is ASYNCHRONOUS. CS rising async-clears the MISO output enable,
 * so the release lag is a pad plus a flop's clear delay instead of
 * L_sync + out_reg = 4 cycles (80 ns at 50 MHz). The ASSERT path stays
 * synchronised, so nothing metastable reaches the pad. F2 still holds: the pin
 * is a flop's Q, and an async-clear flop IS a flop.
 *
 * ⛔ AND THIS FORCES MISO_PIN / CS_PIN TO BE BUILD PARAMETERS, NOT PROGRAM
 * FIELDS. A programmable mux selecting which pin async-clears the enable would
 * put a COMBINATIONAL MUX ON AN ASYNCHRONOUS RESET. A glitch there releases
 * MISO mid-transfer, and the whole reason the asymmetry is allowed is that the
 * release direction is glitch-SAFE -- an argument that collapses if the glitch
 * can come from the mux itself.
 * ⇒ SO THE GENERALITY CLAIM HAS A NAMED EXCEPTION: pins are assigned per
 *   program, EXCEPT the SPI-target MISO/CS pair, which is fixed at build time.
 *   That is a real limit on "pins are assigned per program" and it is recorded
 *   here rather than discovered later.
 * ⚠ Phase 4 owes RECOVERY/REMOVAL constraints on the clear's deassert edge: an
 *   async clear releasing near a clock edge is its own metastability hazard,
 *   moved rather than removed.
 *
 * ⛔ GLITCH SENSITIVITY IS RECORDED, NOT FILTERED. A digital CS filter needs the
 * clock, so it re-introduces the very release lag the async clear removes
 * (the filtered path contends for N-1 cycles under a zero-gap master). The only
 * compatible filter is analog and therefore off-chip.
 * ⇒ BOARD NOTE: KEEP CS CLEAN. A CS glitch costs ONE floating bit and can never
 *   cause contention, because a glitch can only turn a driver OFF.
 */

`default_nettype none

module tt_um_protocol_emulator #(
    // ⭐ EVERY quantity a scaling sweep would vary is a PARAMETER, so scaling
    //    costs a RUN and not a refactor. Checked by part1_param_contract.py.
    parameter integer N_LANES  = 5,     // lanes the engine schedules
    parameter integer AW       = 8,     // 2**AW program bytes -- S1 census
    parameter integer N_PINS   = 12,    // addressable protocol pins, both banks
    parameter integer TS_W     = 16,    // global counter / timestamp width
    parameter integer DLY_W    = 10,    // program delay field
    parameter integer D_W      = 8,     // D_sched field
    parameter         MEM_TYPE = "flops",  // ⛔ default: S0 = SRAM-BLOCKED
    parameter integer RX_SERIAL = 1,    // 1 = 3-pin serial host view
    // ⛔ fixed at build time because the async release path cannot be muxed
    parameter integer MISO_PIN = 7,     // uio index of the SPI-target MISO
    parameter integer CS_PIN   = 6      // uio index of its CS input
) (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);

  // ---- dedicated-input control map. ⛔ NEVER on uio: the protocol pins stay
  //      free, which is what deleted the address bus in the first place.
  localparam integer PIN_PROG = 7;      // 1 = loading, 0 = running
  localparam integer PIN_WR   = 6;      // rising edge writes uio_in at ptr
  localparam integer PIN_RST  = 5;      // reset the write pointer

  localparam integer SER_DATA = 4;      // uo_out indices of the serial trio
  localparam integer SER_STRB = 5;
  localparam integer SER_VLD  = 6;

  wire prog_mode = ui_in[PIN_PROG] & ena;
  wire run       = ~ui_in[PIN_PROG] & ena;

  // =====================================================================
  // INPUT SYNCHRONISERS. ⛔ Every pin input is asynchronous to `clk`; sampling
  // one combinationally is how a load port double-writes or drops a byte, and
  // both are silent. L_sync in the model is this chain.
  // =====================================================================
  reg [2:0] wr_sync;
  reg [1:0] uio_s0, uio_s1;             // two-flop sync, per uio bit
  reg [7:0] uio_q0, uio_q1;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wr_sync <= 3'b000;
      uio_q0  <= 8'h00;
      uio_q1  <= 8'h00;
    end else begin
      wr_sync <= {wr_sync[1:0], ui_in[PIN_WR]};
      uio_q0  <= uio_in;
      uio_q1  <= uio_q0;
    end
  end
  wire wr_rise = (wr_sync[2:1] == 2'b01);

  // ---- the engine's view of the pins, both banks -----------------------
  // ⭐ Inputs only ever come from `uio`; `uo_out` has no input path, which is
  //   precisely why the open-drain and tri-state classes cannot live there.
  wire [N_PINS-1:0] pin_in = {{(N_PINS-8){1'b0}}, uio_q1};

  // =====================================================================
  // PROGRAM LOADER -- the address bus is deleted by AUTO-INCREMENT, and the
  // byte port is `uio` reused, because loading and running are mutually
  // exclusive (HALT, RELOAD, RESUME).
  // =====================================================================
  reg [AW-1:0] ptr;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)            ptr <= {AW{1'b0}};
    else if (prog_mode) begin
      if (ui_in[PIN_RST])  ptr <= {AW{1'b0}};
      else if (wr_rise)    ptr <= ptr + 1'b1;
    end
  end

  // =====================================================================
  // THE STORE -- one instance, shared between the loader and the engine.
  // =====================================================================
  wire [AW-1:0] e_raddr;
  wire          e_re;
  wire [7:0]    s_rdata;

  // readback walk for load-mode verification
  reg [AW-1:0] rb_ptr;
  reg [2:0]    rb_bit;
  reg          rb_re;

  wire [AW-1:0]  e_wraddr;
  wire           e_wre;
  wire [3*8-1:0] s_wrdata;

  pe_store #(.AW(AW), .MEM_TYPE(MEM_TYPE), .WIDE_B(3)) u_store (
      .clk(clk), .rst_n(rst_n),
      .we(prog_mode & wr_rise), .waddr(ptr), .wdata(uio_q1),
      .re(prog_mode ? rb_re : e_re),
      .raddr(prog_mode ? rb_ptr : e_raddr),
      .rdata(s_rdata),
      .wre(e_wre & run), .wraddr(e_wraddr), .wrdata(s_wrdata)
  );

  // =====================================================================
  // THE ENGINE
  // =====================================================================
  wire [N_PINS-1:0]  e_pin_out, e_pin_oe;
  wire [N_LANES-1:0] e_under, e_ovf;
  wire               e_ovr, e_busy, e_rx_push;
  wire [7:0]         e_rx_data;

  pe_engine #(
      .N_LANES(N_LANES), .AW(AW), .N_PINS(N_PINS),
      .TS_W(TS_W), .DLY_W(DLY_W), .D_W(D_W)
  ) u_eng (
      .clk(clk), .rst_n(rst_n), .run(run),
      .s_raddr(e_raddr), .s_re(e_re), .s_rdata(s_rdata),
      .s_wraddr(e_wraddr), .s_wre(e_wre), .s_wrdata(s_wrdata),
      .pin_out(e_pin_out), .pin_oe(e_pin_oe), .pin_in(pin_in),
      .host_data(uio_q1), .host_valid(run & ui_in[0]),
      .lane_underrun(e_under), .lane_overflow(e_ovf), .sticky_ovr(e_ovr),
      .rx_data(e_rx_data), .rx_push(e_rx_push), .busy(e_busy)
  );

  // =====================================================================
  // THE READBACK / RX SERIALISER -- 3 pins, and it is OFF THE ENGINE.
  // ⛔ As a LANE it would take a scheduling slot, enter every other lane's
  //    interference sum and -- being the longest action -- become the blocking
  //    term max{C_j - 1} for all of them. As dedicated hardware it costs ZERO
  //    schedulability budget, so nothing in A2, the frontier or 1.6 moves.
  // ⭐ It has TWO jobs: the RX payload in run mode, and the program readback in
  //    load mode. The second exists because leaving the readback on the
  //    protocol pins made it a PERIPHERAL DRIVER -- a constructed 64-byte image
  //    clocked WREN+WRITE into the FRAM, 4 writes, on an image that fits.
  // ⛔ The STATUS BYTE is framed INTO the stream, because a host that has
  //    stopped reading cannot be told by a pin it is not reading. RX overflow is
  //    a sticky flag in-stream, never a stall.
  // =====================================================================
  reg       ser_d, ser_s, ser_v;
  reg [8:0] ser_sh;                     // 8 payload bits + a frame marker
  reg [3:0] ser_cnt;
  reg       ser_phase;
  reg [7:0] status_byte;
  reg       status_turn;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      ser_d <= 1'b0; ser_s <= 1'b0; ser_v <= 1'b0;
      ser_sh <= 9'h000; ser_cnt <= 4'd0; ser_phase <= 1'b0;
      status_byte <= 8'h00; status_turn <= 1'b0;
      rb_ptr <= {AW{1'b0}}; rb_bit <= 3'd0; rb_re <= 1'b0;
    end else begin
      // the sticky status, assembled once so both modes frame the same byte
      status_byte <= {4'b0000, e_ovr, |e_ovf, |e_under, 1'b1};
      rb_re <= 1'b0;

      if (ser_cnt != 4'd0) begin
        // shifting a frame out: one bit per two cycles, strobe in the middle
        ser_phase <= ~ser_phase;
        if (ser_phase) begin
          ser_sh  <= {1'b0, ser_sh[8:1]};
          ser_cnt <= ser_cnt - 4'd1;
          ser_s   <= 1'b0;
        end else begin
          ser_d <= ser_sh[0];
          ser_s <= 1'b1;
        end
        ser_v <= 1'b1;
      end else begin
        ser_s <= 1'b0;
        ser_v <= 1'b0;
        ser_phase <= 1'b0;
        // ⭐ ALTERNATE payload and status, so liveness is in the stream even
        //   when no payload is moving.
        if (status_turn) begin
          ser_sh      <= {1'b1, status_byte};
          ser_cnt     <= 4'd9;
          status_turn <= 1'b0;
        end else if (prog_mode) begin
          if (RX_SERIAL != 0) begin
            ser_sh  <= {1'b0, s_rdata};
            ser_cnt <= 4'd9;
            rb_ptr  <= rb_ptr + 1'b1;
            rb_re   <= 1'b1;
            status_turn <= 1'b1;
          end
        end else if (e_rx_push) begin
          ser_sh      <= {1'b0, e_rx_data};
          ser_cnt     <= 4'd9;
          status_turn <= 1'b1;
        end
      end
    end
  end

  // =====================================================================
  // ⛔⛔ THE MISO OUTPUT ENABLE -- ASYNC CLEAR ON CS RISING (1.6r)
  // =====================================================================
  // CS is active LOW, so "deselected" is CS high, and that level async-clears
  // the enable. ⭐ The pin is still a flop's Q, so F2 holds.
  wire cs_deasserted = uio_in[CS_PIN];

  reg miso_oe_q;
  always @(posedge clk or posedge cs_deasserted or negedge rst_n) begin
    if (!rst_n)              miso_oe_q <= 1'b0;
    else if (cs_deasserted)  miso_oe_q <= 1'b0;   // ASYNC release
    else                     miso_oe_q <= e_pin_oe[MISO_PIN] & run;
  end

  // =====================================================================
  // OUTPUT MUX -- every bit below is a REGISTERED value or a constant tie.
  // ⛔ No combinational function of the store reaches a pin. That is ruling F2,
  //    and it is also what retired the 18.4388-of-20 ns feedthrough.
  // =====================================================================
  // ---- `uio`: engine bits 0..7, with MISO's enable from the async-clear flop
  wire [7:0] uio_oe_eng = e_pin_oe[7:0];
  wire [7:0] uio_oe_run = (uio_oe_eng & ~(8'b1 << MISO_PIN))
                        | ({7'b0, miso_oe_q} << MISO_PIN);

  // ⛔ LOAD MODE RELEASES EVERY `uio`: the host drives the data byte, and the
  //    protocol lines must not be driven by a readback walk.
  assign uio_oe  = prog_mode ? 8'h00 : uio_oe_run;
  assign uio_out = prog_mode ? 8'h00 : e_pin_out[7:0];

  // ---- `uo_out`: 4 protocol + 3 serial + 1 spare
  // ⛔ In LOAD MODE the 4 protocol outputs are HELD AT IDLE (high), not used for
  //    readback. Readback goes out on the serial trio above. This is the fix for
  //    the constructed-image FRAM write.
  wire [3:0] proto_out = prog_mode ? 4'b1111 : e_pin_out[11:8];

  reg [7:0] uo_q;
  always @(posedge clk or negedge rst_n) begin
    // ⭐ RESET: the 4 protocol outputs go HIGH (forced -- `uo_out` cannot
    //    release), the serial trio goes low, the spare goes low.
    if (!rst_n) uo_q <= 8'h0F;
    else        uo_q <= {1'b0, ser_v, ser_s, ser_d, proto_out};
  end
  assign uo_out = uo_q;

  // ---- unused -----------------------------------------------------------
  wire _unused = &{ui_in[4:1], ena, e_busy, 1'b0};

endmodule
