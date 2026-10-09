/* fram_spi.v -- a behavioural SPI F-RAM peer, MB85RS64V shape.
 *
 * ⛔⛔⛔ SAME-HAND, AND LABELLED AS SUCH. This model is MY reading of the
 * datasheet. When the engine agrees with it, that is two artefacts built from
 * one reading of one document agreeing -- the class of agreement this project
 * treats as worth nothing on its own (the gate-0.9b lesson, and R3's "costs
 * nothing" priced against a register that did not exist). It is a peer for
 * EXERCISING the protocol, never a witness that the protocol is right.
 *
 * ⭐ THE FOREIGN PEER WAS SEARCHED FOR AND NOT FOUND (Wilson's amendment A2):
 *   - MB85RS64V / MB85RC256V (RAMXEED, ex-Fujitsu): datasheets only, no HDL.
 *   - Infineon F-RAM (FM25V02 / FM24V10): no HDL model found. Infineon DOES
 *     publish Verilog/VHDL models for its NOR FLASH (S25FL...), a different
 *     device class.
 *   ⚠ Not exhaustive -- a vendor may supply one on request to a registered
 *     account -- so this records "NOT FOUND", never "does not exist".
 * ⇒ Per A2 the foreign peer arrives at RUNG 5, the real part on the Artix.
 *   Until then this model carries no independent authority.
 *
 * ⛔⛔ AND A VENDOR MODEL COULD NOT BE COMMITTED EVEN IF FOUND. The submission
 * is OPEN SOURCE and a vendor model is third-party code under its own licence,
 * like the datasheets already quarantined in the gitignored `refs/`. It would
 * have to follow pyRTA's pattern exactly: not vendored, located through an env
 * var, and the gate RED without it so the dependency stays priceable.
 *
 * ⭐⭐ IT EXPORTS ITS DRIVE ENABLE (`so_oe`). Wilson's Q2 ruling makes ENABLE
 * OVERLAP the primary contention detector, because X requires the two drivers
 * to DISAGREE -- measured this batch, a peer and the engine both driving LOW
 * fought while the bus resolved cleanly with X = 0 -- and because Verilator is
 * 2-state and has no X at all. A peer exposing only a pin value cannot support
 * that check.
 *
 * NET CLASS: SO/MISO is a TRI-STATE SHARED net, so per Q2 ANY two enables
 * asserted in the same cycle is a failure -- unlike the open-drain I2C lines,
 * where simultaneous pull-low is legal.
 *
 * ⛔⛔⛔ ONE DRIVING BLOCK PER SIGNAL, AND VERILATOR IS WHY. The first version
 * of this file drove `bitn`, `shin`, `shout`, `phase`, `drive` and `byte_done`
 * from four blocks (negedge cs_n, posedge cs_n, posedge sck, negedge sck) --
 * the natural way to write a peer model, and iverilog ACCEPTED IT SILENTLY.
 * Verilator rejected all six as MULTIDRIVEN. ⭐ That is the SAME DEFECT CLASS
 * that made the engine unsynthesizable and killed a harden after three
 * minutes: multiple procedural drivers are last-write-wins in simulation and
 * an error in synthesis. The engine's "ONE SEQUENTIAL BLOCK" discipline
 * applies to the peers too, and a second simulator is what enforced it.
 * ⇒ CS now acts as a SYNCHRONOUS reset inside each block, and `so_oe` carries
 *   the one genuinely asynchronous requirement (release on deselect) through a
 *   combinational gate rather than a second always block.
 *
 * PROTOCOL, from facts already extracted into this repository rather than by
 * re-reading the PDF into the tree:
 *   "WRITE op-code, arbitrary 16 bits of address and 8 bits of writing data
 *    are input to SI. The 3-bit upper address bit is invalid"  -- so a WRITE
 *   carries TWO address bytes, which is F1's corrected transaction count.
 *   Opcodes: WREN 0x06, WRDI 0x04, RDSR 0x05, WRSR 0x01, READ 0x03,
 *            WRITE 0x02, RDID 0x9F.  CS active LOW, MSB first, latch on SCK
 *   rise and present on SCK fall.
 */

`default_nettype none

module fram_spi #(
    parameter integer AW = 13,              // 8192 x 8 = MB85RS64V
    parameter [7:0]   OP_WREN  = 8'h06,
    parameter [7:0]   OP_WRDI  = 8'h04,
    parameter [7:0]   OP_RDSR  = 8'h05,
    parameter [7:0]   OP_READ  = 8'h03,
    parameter [7:0]   OP_WRITE = 8'h02,
    parameter [7:0]   OP_RDID  = 8'h9F,
    // ⭐ RULING CI3: SO changes this many SYSTEM-CLOCK cycles after the SCK
    // fall that presents it (the part's tODV, made adjustable), so the chip's
    // sample instant can be FOUND rather than asserted: inside the window the
    // read is right, past it the read is wrong. 0 = combinational, as before.
    parameter integer MISO_DLY = 0
) (
    input  wire clk,        // ⚠ only the CI3 delay pipeline uses it
    input  wire cs_n,       // chip select, active LOW
    input  wire sck,
    input  wire si,         // master -> device
    output wire so,         // device -> master, VALUE
    output wire so_oe       // ⭐ device -> master, DRIVE ENABLE (exported)
);

  localparam [1:0] P_OP = 2'd0, P_AHI = 2'd1, P_ALO = 2'd2, P_DATA = 2'd3;

  reg [7:0]    mem [0:(1 << AW) - 1];
  reg [2:0]    bitn;       // driven ONLY by the posedge-sck block
  reg [7:0]    shin;       // driven ONLY by the posedge-sck block
  reg          byte_done;  // driven ONLY by the posedge-sck block
  reg [1:0]    phase;      // driven ONLY by the negedge-sck block
  reg [7:0]    opcode;     //   "
  reg [AW-1:0] addr;       //   "
  reg [7:0]    shout;      //   "
  reg          drive;      //   "
  reg          wel;        //   "

  // ⭐ THE ONE ASYNCHRONOUS REQUIREMENT, as a gate rather than a block: the
  // device must stop driving the instant CS goes high, not on the next clock.
  // A model that waited for an edge would hold the bus through a deselect and
  // MANUFACTURE the contention the overlap check is looking for.
  generate
    if (MISO_DLY == 0) begin : g_so_now
      assign so = shout[7];
    end else begin : g_so_dly
      reg [MISO_DLY-1:0] so_pipe = {MISO_DLY{1'b0}};
      always @(posedge clk) so_pipe <= {so_pipe, shout[7]};
      assign so = so_pipe[MISO_DLY-1];
    end
  endgenerate
  assign so_oe = drive & ~cs_n;

  // ⛔⛔ RULING SP1 -- MODE 3, WHICH THE PART SUPPORTS AND THIS MODEL DID NOT.
  // The datasheet: "corresponds to SPI mode 0 (CPOL 0, CPHA 0) and mode 3
  // (CPOL 1, CPHA 1)". This model was mode-0-only in two ways, invisible until
  // a program first addressed it for real:
  //   * deselect was a SYNCHRONOUS reset, so it needed an SCK edge while CS
  //     was high -- in mode 3 SCK idles HIGH and still, so `phase` never
  //     reset and every transaction after the first was decoded as DATA;
  //   * a byte was ACTED ON at the next SCK fall, so the last byte before CS
  //     rose (WREN; the final WRITE data byte) never acted -- in mode 3 there
  //     is no fall after it.
  // ⇒ Deselect is an ASYNCHRONOUS reset in each block (still one driver per
  //   signal), and a completed byte is counted (`nbyte`) and acted on ONCE --
  //   at the next fall, or at CS rise if no fall came. Mode 0 behaves exactly
  //   as before: its fall acts, and the CS rise then finds nothing pending.
  reg [7:0]    nbyte;      // driven ONLY by the rise block: bytes completed
  reg [7:0]    seen;       // driven ONLY by the fall block: bytes acted on

  // ---- LATCH on SCK rise; deselect resets asynchronously ---------------
  always @(posedge sck or posedge cs_n) begin
    if (cs_n) begin
      bitn      <= 3'd7;
      shin      <= 8'h00;
      byte_done <= 1'b0;
    end else begin
      shin      <= {shin[6:0], si};
      byte_done <= (bitn == 3'd0);
      bitn      <= (bitn == 3'd0) ? 3'd7 : bitn - 3'd1;
      if (bitn == 3'd0) nbyte <= nbyte + 8'd1;
    end
  end

  // ---- ACT on a completed byte, and present, on SCK fall -------------
  always @(negedge sck or posedge cs_n) begin
    if (cs_n) begin
      // a byte completed and never acted on (mode 3's last byte) acts NOW
      if (nbyte != seen) begin
        act_byte;
        seen <= nbyte;
      end
      // ⭐ "WEL is reset ... at the rising edge of CS after WRITE command
      // recognition" (datasheet) -- AFTER the last data byte has used it
      if (phase != P_OP && opcode == OP_WRITE) wel <= 1'b0;
      phase <= P_OP;
      drive <= 1'b0;
      shout <= 8'h00;
      // ⛔ `wel` is NOT cleared by deselect. WREN latches write-enable and the
      // part keeps it across the deselect that ends the WREN transaction --
      // that is the whole point of a separate WREN command, and clearing it
      // here would make every WRITE fail for a reason the program cannot see.
    end else if (nbyte != seen) begin
      act_byte;
      seen <= nbyte;
    end else if (drive) begin
      shout <= {shout[6:0], 1'b0};          // shift out, MSB first
    end
  end

  // ---- what a completed byte does, in its phase -------------------------
  task act_byte;
    begin
      case (phase)
        P_OP: begin
          opcode <= shin;
          case (shin)
            OP_WREN: begin wel <= 1'b1; drive <= 1'b0; end
            OP_WRDI: begin wel <= 1'b0; drive <= 1'b0; end
            OP_RDSR: begin
              shout <= {6'b0, wel, 1'b0};   // bit1 = WEL
              drive <= 1'b1;
              phase <= P_DATA;
            end
            OP_RDID: begin shout <= 8'h04; drive <= 1'b1; phase <= P_DATA; end
            OP_READ, OP_WRITE: begin phase <= P_AHI; drive <= 1'b0; end
            default:            begin drive <= 1'b0; end
          endcase
        end
        P_AHI: begin
          // ⛔ "the 3-bit upper address bit is invalid": a 13-bit array takes
          // only 5 bits of the high byte, so the top 3 are discarded rather
          // than wrapped. Discarding is what the part does; wrapping would
          // make an out-of-range address alias onto a real one.
          addr[AW-1:8] <= shin[AW-9:0];
          phase        <= P_ALO;
        end
        P_ALO: begin
          addr[7:0] <= shin;
          phase     <= P_DATA;
          if (opcode == OP_READ) begin
            shout <= mem[{addr[AW-1:8], shin}];
            drive <= 1'b1;                  // ⭐ only a READ sources SO
          end
        end
        P_DATA: begin
          if (opcode == OP_WRITE) begin
            // ⛔ WEL GATES THE WRITE, as the part does. A model that always
            // wrote would hide a missing WREN in our own program -- and the
            // census's SPI sequence is WREN then WRITE precisely because the
            // part requires it.
            if (wel) mem[addr] <= shin;
            addr <= addr + 1'b1;            // auto-increment within a burst
          end else if (opcode == OP_READ) begin
            addr  <= addr + 1'b1;
            shout <= mem[addr + 1'b1];
          end
        end
        default: ;
      endcase
    end
  endtask

  // ---- init ------------------------------------------------------------
  // ⛔ THE ARRAY IS LEFT X, NOT ZEROED. A zero-filled array makes a read of an
  // unwritten address return a plausible 0, so a program that reads before it
  // writes looks correct. X makes it a visible failure -- the same reason the
  // image loader asserts its length instead of trusting it, and the same
  // reason an undriven output is a finding rather than a 0.
  initial begin
    wel       = 1'b0;
    drive     = 1'b0;
    bitn      = 3'd7;
    shin      = 8'h00;
    shout     = 8'h00;
    phase     = P_OP;
    opcode    = 8'h00;
    byte_done = 1'b0;
    nbyte     = 8'd0;
    seen      = 8'd0;
  end

endmodule

`default_nettype wire
