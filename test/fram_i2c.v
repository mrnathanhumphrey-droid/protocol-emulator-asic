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

module fram_i2c #(
    parameter integer AW = 15,              // 32768 x 8 = MB85RC256V
    parameter [2:0]   DEV_SEL = 3'b000,     // the A2/A1/A0 strap
    parameter integer STRETCH = 0           // cycles of SCL stretch per ACK
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

  // ---- block B (posedge scl) owns these -------------------------------
  reg [3:0]    bitn;
  reg [7:0]    shin;
  reg          byte_done;
  reg          prev_active_b;

  // ---- block C (negedge scl) owns these -------------------------------
  reg [2:0]    phase;
  reg          rw;              // 1 = master reads
  reg [AW-1:0] addr;
  reg [7:0]    shout;
  reg          ack_low;         // pulling SDA low for an ACK
  reg          data_low;        // pulling SDA low for a data 0
  reg          selected;
  reg          prev_active_c;
  reg [15:0]   stretch_n;

  // ⭐ THE EXPORTED ENABLES. Two sources of pull-low on SDA -- the ACK and a
  // read data 0 -- are ORed, which is exactly how an open-drain line behaves
  // and is why the ENABLE rather than the value is the thing to export.
  assign sda_oe = bus_active & (ack_low | data_low);
  assign scl_oe = (stretch_n != 16'd0);

  // =====================================================================
  // BLOCK A -- START / STOP. Owns `bus_active` and nothing else.
  // =====================================================================
  // ⭐ ONE block for BOTH edges of SDA, level-checking SCL. Splitting it into
  // `negedge sda` and `posedge sda` would be two drivers on `bus_active` --
  // the defect Verilator caught in the SPI peer.
  always @(sda_in) begin
    if (scl_in) begin
      if (!sda_in) bus_active <= 1'b1;    // START: SDA falls while SCL high
      else         bus_active <= 1'b0;    // STOP : SDA rises while SCL high
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
    end else if (!prev_active_b) begin    // a fresh START
      bitn      <= 4'd7;
      shin      <= {7'h00, sda_in};
      byte_done <= 1'b0;
    end else if (bitn == 4'd8) begin
      byte_done <= 1'b0;                  // the ACK bit slot: sample nothing
      bitn      <= 4'd7;
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
    end else if (!prev_active_c) begin
      // ⭐ A repeated START lands here: the phase returns to P_DEV but `addr`
      // is DELIBERATELY KEPT. That is the part's documented read sequence --
      // "specifying the address in the same way as for a write, and then
      // issuing another start condition" -- so a model that cleared the
      // address on a repeated START could never read the location just set.
      phase    <= P_DEV;
      ack_low  <= 1'b0;
      data_low <= 1'b0;
    end else if (byte_done) begin
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
        default: ack_low <= 1'b0;
      endcase
      if (STRETCH != 0) stretch_n <= STRETCH[15:0];
    end else begin
      ack_low <= 1'b0;                    // the ACK lasts ONE clock
      // a read presents the next bit, MSB first, as a PULL-LOW for 0
      if (selected && rw && phase == P_RDATA) begin
        data_low <= ~shout[7];
        shout    <= {shout[6:0], 1'b0};
      end else begin
        data_low <= 1'b0;
      end
    end
    prev_active_c <= bus_active;
  end

  // ---- the stretch countdown, on `clk` (see the header caveat) --------
  always @(posedge clk) begin
    if (stretch_n != 16'd0) stretch_n <= stretch_n - 16'd1;
  end

  initial begin
    bus_active = 1'b0; bitn = 4'd7; shin = 8'h00; byte_done = 1'b0;
    prev_active_b = 1'b0; prev_active_c = 1'b0;
    phase = P_DEV; rw = 1'b0; shout = 8'h00;
    ack_low = 1'b0; data_low = 1'b0; selected = 1'b0; stretch_n = 16'd0;
  end

endmodule

`default_nettype wire
