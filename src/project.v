/*
 * Copyright (c) 2026 Nathan Humphrey
 * SPDX-License-Identifier: Apache-2.0
 *
 * RUNGS 1 + 2 -- the program-load path, and open-drain through `uio_oe`.
 *
 * ⛔⛔ THIS IS NOT THE ENGINE. The queue engine is rung 4 and is GATED on A2 being
 * derived and proved on the model (rung 3). Nothing here schedules, counts bits or
 * emulates a protocol. What is here is the two things the plan needs first:
 *
 *   RUNG 1  a byte-wide sequential program-load path, answering the brief's
 *           central ask -- "reprogrammable enough to support new protocols AFTER
 *           fabrication" -- which NOTHING in TA-01, TA-02 or ARCH_PREREG_01
 *           specified. There was no address port, no data port, no handshake.
 *
 *   RUNG 2  proof that open-drain is expressible through `uio_oe`. F5 says a pin
 *           abstraction failure "must be fixed before any protocol work
 *           continues", and the previous plan had this third, behind two rungs of
 *           protocol work -- violating a falsifier we pre-registered ourselves.
 *
 * ⭐ THEY ARE ONE INCREMENT BECAUSE THEY SHARE THE PIN CONTROL. The load path
 * requires `uio_oe = 0` throughout `prog_mode` so the protocol pins are released
 * to the host; that release IS a tri-state exercise. Building them apart would
 * have meant writing the same `uio_oe` mux twice.
 *
 * THE PIN TRICK, AND WHY IT COSTS NOTHING. ARCH_PREREG spends all 8 bidirectional
 * pins on protocols (UART 2 + SPI 4 + I2C 2 = exactly 8), so there is no room for
 * an address bus, a data bus and a handshake -- IF loading and running are
 * simultaneous. They are not. So `uio` is reused as the load data port and the
 * address bus is deleted entirely by AUTO-INCREMENT.
 *
 * ⛔ MODE-SELECT AND POINTER-RESET COME FROM THE DEDICATED INPUTS (`ui_in`, `ena`)
 * AND NEVER FROM THE 8 `uio` -- a hard constraint, so the protocol pins stay free.
 *
 * ⛔ MUTUAL EXCLUSION IS AN EXPLICIT SCOPE CHOICE, NOT AN OVERSIGHT:
 *      reprogram = HALT, RELOAD, RESUME.  No mid-transaction swap.
 *   Writing it down as a choice is what stops it being read later as a gap.
 *
 * ⛔ `wr` IS PIN-DRIVEN AND THEREFORE ASYNCHRONOUS TO `clk`. It gets a two-flop
 * synchroniser and a rising-edge detector. A load port that samples an async
 * strobe combinationally double-writes or drops bytes, and both are silent.
 *
 * ⭐ READBACK COMES FREE, AND IT MATTERS AT GATE LEVEL. In run mode `uo_out`
 * presents `mem[ptr]`, so loaded content is observable AT THE PINS. "Reprogrammable"
 * + "provably correct" implies "provably loaded correctly", and a pin-observable
 * readback lets the SAME cocotb test run against RTL and the synthesized netlist
 * without peeking at internal signals. The stronger checksum/attestation form is
 * PRE-REGISTERED (plan §6 L3) and deliberately NOT built yet.
 */

`default_nettype none

module tt_um_protocol_emulator #(
    // ⛔ PARAMETERIZED ON PURPOSE. The tile allocation is a contested number: the
    // brief says 6x4, this template's own info.yaml lists only 1x1..8x2, and
    // precheck accepted 6x4. One precheck pass licenses proceeding, not re-locking
    // a budget -- the 24x area error came from treating a soft number as hard.
    parameter AW = 6                          // 2**AW program bytes
) (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
    input  wire       ena,      // always 1 when the design is powered
    input  wire       clk,      // clock
    input  wire       rst_n     // reset_n - low to reset
);

  // ---- the dedicated-input control map (never on uio) ---------------------
  localparam integer PIN_PROG = 7;            // 1 = programming, 0 = running
  localparam integer PIN_WR   = 6;            // rising edge writes uio_in at ptr
  localparam integer PIN_RST  = 5;            // reset the write pointer to 0

  wire prog_mode = ui_in[PIN_PROG] & ena;

  // ---- `wr` synchroniser + edge detector ---------------------------------
  // Two flops to resolve metastability, a third to see the edge.
  reg [2:0] wr_sync;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) wr_sync <= 3'b000;
    else        wr_sync <= {wr_sync[1:0], ui_in[PIN_WR]};
  end
  wire wr_rise = (wr_sync[2:1] == 2'b01);

  // ---- the program store and its write pointer ---------------------------
  reg [7:0]    mem [0:(1<<AW)-1];
  reg [AW-1:0] ptr;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      ptr <= {AW{1'b0}};
    end else if (prog_mode) begin
      if (ui_in[PIN_RST]) begin
        ptr <= {AW{1'b0}};
      end else if (wr_rise) begin
        mem[ptr] <= uio_in;                   // sequential write...
        ptr      <= ptr + 1'b1;               // ...and the address bus is gone
      end
    end
  end

  // ---- run-mode read pointer: makes the loaded image pin-observable ------
  // A slow walk so a host (or a scope) can watch the program come back out.
  reg [AW-1:0] rd_ptr;
  reg [7:0]    div;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      rd_ptr <= {AW{1'b0}};
      div    <= 8'h00;
    end else if (prog_mode) begin
      rd_ptr <= {AW{1'b0}};                   // halt/reload/resume: restart the walk
      div    <= 8'h00;
    end else begin
      div <= div + 1'b1;
      if (div == 8'hFF) rd_ptr <= rd_ptr + 1'b1;
    end
  end

  wire [7:0] rd_data = mem[prog_mode ? ptr : rd_ptr];

  // ---- outputs -----------------------------------------------------------
  // prog_mode: echo the low pointer bits so a host can confirm a write LANDED.
  //   ⚠️ that confirms A write happened, not WHAT was written -- which is exactly
  //   why run-mode readback below exists, and why the checksum is pre-registered.
  assign uo_out = prog_mode ? {{(8-AW){1'b0}}, ptr} : rd_data;

  // ---- RUNG 2: open-drain through uio_oe ---------------------------------
  // ⛔ THE F5 PROPERTY, STRUCTURAL BY CONSTRUCTION RATHER THAN BY ASSERTION:
  // an open-drain pin may pull LOW or RELEASE, and must NEVER drive HIGH. So
  // `uio_out` is tied to 0 for these pins and only the ENABLE is modulated --
  // which makes `uio_oe[i] && uio_out[i]` unsatisfiable for them, not merely
  // untested. Data comes from the loaded image, so this also demonstrates that a
  // loaded program can reach the pins.
  localparam integer OD_SCL = 0;              // I2C-shaped: pull low or release
  localparam integer OD_SDA = 1;

  wire od_scl_low = ~rd_data[0];              // 0 in the image => pull low
  wire od_sda_low = ~rd_data[1];

  wire [7:0] od_oe = (8'b1 << OD_SCL) & {8{od_scl_low}}
                   | (8'b1 << OD_SDA) & {8{od_sda_low}};

  // In prog_mode every uio is released so the host can drive the data byte.
  assign uio_oe  = prog_mode ? 8'h00 : od_oe;
  assign uio_out = 8'h00;                     // never drives 1 -- open-drain, by construction

  // ⛔⛔ WHAT THIS DOES *NOT* SETTLE, SAID PLAINLY SO IT CANNOT READ AS DONE.
  // Tying `uio_out` to 0 makes "never drives high" unsatisfiable, which is the
  // strongest possible form of the F5 property -- for OPEN-DRAIN pins. But it
  // means this design currently cannot drive a 1 on ANY `uio` pin, and UART TX
  // and SPI SCLK/MOSI are PUSH-PULL: they must drive both levels.
  //
  // So F5 is answered for I2C ("open-drain IS expressible through uio_oe") and the
  // GENERAL pin abstraction is not yet built. The missing piece is a per-pin
  // DRIVE MODE, which ARCH_PREREG_01's descriptor already names -- "pin, drive
  // mode, shift reg, bit counter, divider, next-action timestamp". Open-drain
  // modulates the enable with `uio_out` held low; push-pull holds the enable high
  // and modulates `uio_out`. One mode bit per pin selects which.
  //
  // That bit belongs with the queue engine (rung 4), because its descriptor is
  // where drive mode lives -- and rung 4 is gated on A2. Pulling it forward here
  // would be building the descriptor before the premise it has to carry is proved.

  // List all unused inputs to prevent warnings
  wire _unused = &{ui_in[4:0], 1'b0};

endmodule
