/* fram_i2c.v -- a behavioural I2C F-RAM peer, MB85RC256V shape.
 *
 * ⛔⛔⛔ SAME-HAND, like fram_spi.v. My reading of the datasheet, so
 * engine-agrees-with-model is two artefacts from one reading of one document
 * agreeing. A peer for EXERCISING the protocol, never a witness that it is
 * right. The foreign peer is rung-5 silicon (A2: no vendor HDL model found).
 *
 * ⭐⭐ OPEN-DRAIN, AND THAT CHANGES THE CONTENTION RULE. Per Wilson's Q2, the
 * net classes are judged differently:
 *     push-pull        any overlapping drive is a FAILURE
 *     tri-state shared any two enables in one cycle is a FAILURE   (MISO)
 *     open-drain       SIMULTANEOUS PULL-LOW IS LEGAL              (SCL, SDA)
 * ⛔ So an overlap check that treats SDA like MISO would FALSE-FIRE on every
 * ACK -- the slave pulling SDA low while the master releases it IS the
 * acknowledge -- and on every clock-synchronisation and stretch. The only
 * open-drain failure is a PUSH-PULL HIGH fighting a low.
 * ⇒ This model therefore exports PULL-LOW ENABLES (`sda_oe`, `scl_oe`) and
 *   NEVER a high. `sda`/`scl` values are tied low; the enable is the signal.
 *   A peer that drove a 1 would be modelling a part we did not buy.
 *
 * ⛔ ONE DRIVING BLOCK PER SIGNAL, learned on fram_spi.v where Verilator
 * rejected six MULTIDRIVEN signals that iverilog had accepted in silence --
 * the same class that killed an engine harden. The START/STOP detector is a
 * single `always @(sda)` block that owns `bus_active` alone, and the two SCL
 * blocks own disjoint state and detect a fresh START through their own
 * `prev_active` register rather than by clearing someone else's pulse.
 *
 * CLOCK STRETCHING is modelled, because three rulings depend on the engine
 * handling it: N1a (the HIGH count starts when SCL *goes* high, so `tr` leaves
 * the controller's budget), A2-P4 (a stretch lengthens the low phase, so
 * consecutive releases move FURTHER apart and schedulability is unaffected --
 * while a BUSY-WAIT would make C_i unbounded and take every lane with it), and
 * R3 (the SDA read lands on the observed rise).
 * ⚠ The stretch timer needs a reference the stretched clock cannot provide --
 * if the slave holds SCL low there are no more SCL edges to count on -- so the
 * model takes `clk`. That is a MODELLING CONVENIENCE and is stated: a real part
 * times the stretch internally, and nothing about the engine may depend on the
 * stretch being clk-aligned.
 *
 * PROTOCOL, from facts already extracted into this repository:
 *   "the master outputs 8 bits x 2 memory address to the slave. When the each
 *    memory address input ends, the slave again outputs the acknowledge"
 *   -- TWO address bytes, each with its own ACK, which is F1's correction.
 *   Waveform: S | 1010 A2 A1 A0 R/W | A | Addr | A | Addr | A | Data | A | P
 *   A read re-STARTs: address as for a write, then a repeated START and the
 *   device address with R/W = 1.
 */

`default_nettype none
// PEER_DLY_NS is in NANOSECONDS whatever the compile order, so the unit is
// pinned here -- only when the delay is in use, leaving default builds as they were
`ifdef PEER_DLY_NS
`timescale 1ns / 1ps
`endif

module fram_i2c #(
    parameter integer AW = 15,              // 32768 x 8 = MB85RC256V
    parameter [2:0]   DEV_SEL = 3'b000,     // the A2/A1/A0 strap
    parameter integer STRETCH = 0,          // cycles of SCL stretch per ACK
    // ⭐ RULING ACK (b) -- LATE DATA. With LATE > 0 a READ data bit is not
    // presented at the SCL fall: the peer holds SCL low for LATE cycles,
    // releases SDA meanwhile, and puts the bit on SDA only at the END of the
    // stretch, just before letting SCL go. Legal I2C (data may change while
    // SCL is low), and it is what makes "sampled on the OBSERVED rise"
    // distinguishable from "sampled when the controller released SCL": with
    // the bit presented at the fall, both instants read the same value and a
    // wrong-instant sampler cannot fail. LATE_SKIP read bits are presented
    // normally first; LATE_ONCE stretches only the next one (the arm just
    // under the chip's stretch timeout would otherwise run for hours).
    parameter integer LATE = 0,
    parameter integer LATE_SKIP = 0,
    parameter integer LATE_ONCE = 0
) (
    input  wire clk,        // ⚠ stretch timer reference only -- see header
    input  wire scl_in,     // the RESOLVED line, as the device sees it
    input  wire sda_in,     // the RESOLVED line
    output wire sda_oe,     // ⭐ PULL-LOW enable (never drives high)
    output wire scl_oe      // ⭐ PULL-LOW enable, for stretching
);

  localparam [2:0] P_DEV = 3'd0, P_AHI = 3'd1, P_ALO = 3'd2,
                   P_WDATA = 3'd3, P_RDATA = 3'd4, P_IDLE = 3'd5;

  reg [7:0]    mem [0:(1 << AW) - 1];

  // ---- block A owns these ---------------------------------------------
  reg          bus_active;
  // A START COUNTER, BECAUSE `bus_active` ALONE IS INVISIBLE ACROSS A
  // STOP-THEN-START PAIR. Both state blocks below latch `bus_active` on an SCL
  // edge and detect a fresh START as "it was 0 and now it is 1". But a STOP and
  // the next START both happen while SCL is HIGH -- that is what the conditions
  // ARE -- so between two SCL edges the flag goes 1 -> 0 -> 1 and each block
  // samples 1 then 1. The restart is missed, and a device that had gone to
  // P_IDLE on an address that was not its own STAYS THERE FOR EVER.
  // THAT IS WHAT THIS MODEL DID, and it mattered the moment anything sent it a
  // decodable byte: our program's first transaction carries the reset byte 0x00
  // (an address this device correctly refuses), so the peer went idle and never
  // acknowledged any of the hundreds of valid transactions that followed.
  // A real part has an asynchronous START/STOP detector that resets its state
  // machine immediately. A monotonic counter is the same information in a form
  // an edge-sampled block can read without a second driver on any signal --
  // which the header's one-driver rule requires.
  reg [7:0]    start_cnt;

  // ---- block B (posedge scl) owns these -------------------------------
  reg [3:0]    bitn;
  reg [7:0]    shin;
  reg          byte_done;
  reg          prev_active_b;
  reg [7:0]    seen_b;

  // ---- block C (negedge scl) owns these -------------------------------
  reg [2:0]    phase;
  reg          rw;              // 1 = master reads
  reg [AW-1:0] addr;
  reg [7:0]    shout;
  reg          ack_low;         // pulling SDA low for an ACK
  reg          data_low;        // pulling SDA low for a data 0
  reg          selected;
  reg          prev_active_c;
  reg [7:0]    seen_c;
  reg [15:0]   stretch_n;
  reg          ackslot_c;       // the fall that ends a master ACK/NACK slot
  reg          late_gate;       // this bit is presented late (block D drives)
  reg          late_bit;        // the late bit's pull-low, for block D
  reg [7:0]    late_req;        // a request counter, read by block D
  integer      late_cnt;        // read data bits presented so far

  // ---- block B also owns the master's ACK/NACK sample -------------------
  reg          mack;            // SDA at the ACK slot's rise: 1 = NACK

  // ---- block D (posedge clk) owns these: the late-data stretch ---------
  reg [7:0]    late_seen;
  reg [31:0]   late_n;
  reg          late_low;

  // ⭐ THE EXPORTED ENABLES. Two sources of pull-low on SDA -- the ACK and a
  // read data 0 -- are ORed, which is exactly how an open-drain line behaves
  // and is why the ENABLE rather than the value is the thing to export.
  // ⭐ PEER_DLY_NS: an OUTPUT DELAY on both pull-low enables, as a real
  // part's tAA / output hold (phase-coverage rule, Wilson 10-20). Without it
  // the peer's edges all land in the chip posedge's own timestep (after the
  // NBA, so deterministic -- but ONE clock phase). Undefined = 0 = the
  // historical behaviour, byte-identical builds.
`ifdef PEER_DLY_NS
  assign #(`PEER_DLY_NS) sda_oe = bus_active & (ack_low | data_low | (late_gate & late_low));
  assign #(`PEER_DLY_NS) scl_oe = (stretch_n != 16'd0) | (late_n != 32'd0);
`else
  assign sda_oe = bus_active & (ack_low | data_low | (late_gate & late_low));
  assign scl_oe = (stretch_n != 16'd0) | (late_n != 32'd0);
`endif

  // =====================================================================
  // BLOCK A -- START / STOP. Owns `bus_active` and nothing else.
  // =====================================================================
  // ⭐ ONE block for BOTH edges of SDA, level-checking SCL. Splitting it into
  // `negedge sda` and `posedge sda` would be two drivers on `bus_active` --
  // the defect Verilator caught in the SPI peer.
  always @(sda_in) begin
    if (scl_in) begin
      if (!sda_in) begin
        bus_active <= 1'b1;               // START: SDA falls while SCL high
        start_cnt  <= start_cnt + 8'd1;   // ... and it is COUNTED
      end else begin
        bus_active <= 1'b0;               // STOP : SDA rises while SCL high
      end
    end
  end

  // =====================================================================
  // BLOCK B -- latch on the OBSERVED SCL rise
  // =====================================================================
  // ⭐ `posedge scl_in` is the OBSERVED line, not a modelled phase. With
  // stretching that is the whole point: the device, like the controller, counts
  // from when the line actually goes high (N1a).
  always @(posedge scl_in) begin
    if (!bus_active) begin
      bitn      <= 4'd7;
      shin      <= 8'h00;
      byte_done <= 1'b0;
      seen_b    <= start_cnt;
    end else if (start_cnt != seen_b) begin   // a fresh START, however brief
      // THIS RISE ALREADY CARRIES BIT 7, so only SEVEN more are owed and the
      // counter starts at 6. It was 7, which made a byte complete on the
      // NINTH rise: `shin` then held samples 2..9 -- the byte shifted left by
      // one with the released ACK bit appended -- so a correct device address
      // of 0xA0 was decoded as 0x41 and NEVER MATCHED.
      // HOW IT SURVIVED: the P_DEV address comparison had never once fired.
      // Nothing in this project had ever sent this model a decodable byte --
      // `corpus.py`'s I2C program used two SHIFTs per bit, so it consumed two
      // payload bits per protocol bit and never put a coherent byte on the
      // wire, and the trace gate compares the two SIMULATORS against each
      // other rather than the bus against a standard. An unexercised branch
      // is not a correct one.
      // ADJUDICATED BY SIGROK, NOT BY ME. The foreign `i2c` decoder reads
      // the same waveform as `Start / Address write: 50 / NACK / Data write:
      // 5A / Stop` -- eight address bits with the ACK slot in the right
      // place -- so the WIRE is well formed and this model was counting
      // wrong. Without a foreign authority this would have been my framing
      // against my model, with no way to tell which was at fault.
      bitn      <= 4'd6;
      shin      <= {7'h00, sda_in};
      byte_done <= 1'b0;
      seen_b    <= start_cnt;
    end else if (bitn == 4'd8) begin
      byte_done <= 1'b0;                  // the ACK bit slot: no data bit,
      bitn      <= 4'd7;
      mack      <= sda_in;                // but a READ needs the master's
                                          // ACK (0) or NACK (1)
    end else begin
      shin      <= {shin[6:0], sda_in};
      byte_done <= (bitn == 4'd0);
      bitn      <= (bitn == 4'd0) ? 4'd8 : bitn - 4'd1;
    end
    prev_active_b <= bus_active;
  end

  // =====================================================================
  // BLOCK C -- decide and present on the SCL fall
  // =====================================================================
  always @(negedge scl_in) begin
    if (!bus_active) begin
      phase     <= P_DEV;
      ack_low   <= 1'b0;
      data_low  <= 1'b0;
      selected  <= 1'b0;
      shout     <= 8'h00;
      seen_c    <= start_cnt;
      late_gate <= 1'b0;
      ackslot_c <= 1'b0;
    end else if (start_cnt != seen_c) begin
      // ⭐ A repeated START lands here: the phase returns to P_DEV but `addr`
      // is DELIBERATELY KEPT. That is the part's documented read sequence --
      // "specifying the address in the same way as for a write, and then
      // issuing another start condition" -- so a model that cleared the
      // address on a repeated START could never read the location just set.
      phase    <= P_DEV;
      ack_low  <= 1'b0;
      data_low <= 1'b0;
      seen_c   <= start_cnt;
      late_gate <= 1'b0;
      ackslot_c <= 1'b0;
    end else if (byte_done) begin
      // ⛔ RULING ACK (AC4): THE NEXT SLOT IS AN ACK SLOT, so a read's last
      // data bit must come OFF the line. It used to stay on: a 0 in bit 0
      // held SDA low through the master's slot and turned its NACK into an
      // ACK on the wire.
      data_low  <= 1'b0;
      late_gate <= 1'b0;
      case (phase)
        P_DEV: begin
          // 1010 A2A1A0 R/W
          if (shin[7:4] == 4'b1010 && shin[3:1] == DEV_SEL) begin
            selected <= 1'b1;
            ack_low  <= 1'b1;             // ⭐ ACK: pull SDA LOW. Legal while
                                          //    the master releases it -- this
                                          //    is why open-drain overlap is
                                          //    not a failure.
            rw       <= shin[0];
            phase    <= shin[0] ? P_RDATA : P_AHI;
            if (shin[0]) shout <= mem[addr];
          end else begin
            selected <= 1'b0;
            ack_low  <= 1'b0;             // not us: stay off the bus entirely
            phase    <= P_IDLE;
          end
        end
        P_AHI: begin
          // ⛔ TWO ADDRESS BYTES, each ACKed. A one-byte-address model would
          // make our program's extra byte look like a protocol error -- and
          // F1 costed this transaction wrongly for exactly that reason.
          addr[AW-1:8] <= shin[AW-9:0];
          ack_low      <= 1'b1;
          phase        <= P_ALO;
        end
        P_ALO: begin
          addr[7:0] <= shin;
          ack_low   <= 1'b1;
          phase     <= P_WDATA;
        end
        P_WDATA: begin
          mem[addr] <= shin;
          addr      <= addr + 1'b1;       // auto-increment
          ack_low   <= 1'b1;
        end
        P_RDATA: begin
          // ⛔⛔ RULING ACK (AC4): THE SECOND READ BYTE. This fell to
          // `default`, so `shout` was never reloaded and `addr` never moved:
          // a second byte shifted out the zeros left behind and read 0x00.
          // Unexercised until ruling ACK -- no bench ever addressed this
          // peer for a read (tb_i2c and tb_trace only write). The master's
          // ACK/NACK lands in `mack` on the coming rise.
          ack_low   <= 1'b0;
          addr      <= addr + 1'b1;
          shout     <= mem[addr + 1'b1];
          ackslot_c <= 1'b1;
        end
        default: ack_low <= 1'b0;
      endcase
      if (STRETCH != 0) stretch_n <= STRETCH[15:0];
    end else begin
      ack_low   <= 1'b0;                  // the ACK lasts ONE clock
      ackslot_c <= 1'b0;
      if (selected && rw && phase == P_RDATA && ackslot_c && mack) begin
        // ⭐ THE MASTER SAID NACK: the read is over. Off the bus until the
        // next START, as the part's read sequence ends.
        phase     <= P_IDLE;
        selected  <= 1'b0;
        data_low  <= 1'b0;
        late_gate <= 1'b0;
      end else if (selected && rw && phase == P_RDATA) begin
        // a read presents the next bit, MSB first, as a PULL-LOW for 0 --
        // at this fall, or (LATE) at the end of a stretch, by block D
        if (LATE != 0 && late_cnt >= LATE_SKIP
            && (LATE_ONCE == 0 || late_cnt == LATE_SKIP)) begin
          data_low  <= 1'b0;
          late_gate <= 1'b1;
          late_bit  <= ~shout[7];
          late_req  <= late_req + 8'd1;
        end else begin
          data_low  <= ~shout[7];
          late_gate <= 1'b0;
        end
        late_cnt <= late_cnt + 1;
        shout    <= {shout[6:0], 1'b0};
      end else begin
        data_low  <= 1'b0;
        late_gate <= 1'b0;
      end
    end
    prev_active_c <= bus_active;
  end

  // ---- the stretch countdown, on `clk` (see the header caveat) --------
  always @(posedge clk) begin
    if (stretch_n != 16'd0) stretch_n <= stretch_n - 16'd1;
  end

  // =====================================================================
  // BLOCK D -- the LATE-DATA stretch (ruling ACK (b)), on `clk`
  // =====================================================================
  // A request from block C (the counter moved) starts a LATE-cycle hold of
  // SCL with SDA released; the bit goes on the line 4 cycles before the
  // hold ends, so it is set up before the rise the controller observes.
  always @(posedge clk) begin
    if (late_req != late_seen) begin
      late_seen <= late_req;
      late_n    <= LATE;
      late_low  <= 1'b0;
    end else if (late_n != 32'd0) begin
      late_n <= late_n - 32'd1;
      if (late_n == 32'd4) late_low <= late_bit;
    end
  end

  initial begin
    bus_active = 1'b0; bitn = 4'd7; shin = 8'h00; byte_done = 1'b0;
    prev_active_b = 1'b0; prev_active_c = 1'b0;
    start_cnt = 8'd0; seen_b = 8'd0; seen_c = 8'd0;
    phase = P_DEV; rw = 1'b0; shout = 8'h00;
    ack_low = 1'b0; data_low = 1'b0; selected = 1'b0; stretch_n = 16'd0;
    ackslot_c = 1'b0; mack = 1'b0; late_gate = 1'b0; late_bit = 1'b0;
    late_req = 8'd0; late_seen = 8'd0; late_n = 32'd0; late_low = 1'b0;
    late_cnt = 0;
  end

endmodule

`default_nettype wire
