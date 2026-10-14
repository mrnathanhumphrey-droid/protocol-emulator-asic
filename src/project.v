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
    // ⛔ `RX_SERIAL` WAS DELETED HERE, by ruling. It was overridden nowhere in
    // the tree, so its `else` was source no configuration executed; the serial
    // RX view is now unconditional at its one use site. It is NOT coming back
    // as an `ifdef`: the point of the deletion is that an unexercised knob is
    // not a priced alternative, and an `ifdef` would restore the dead arm
    // without restoring a build that runs it.
    // ⛔ fixed at build time because the async release path cannot be muxed
    // the clock-stretch BUS-FAULT bound: 35 ms at 50 MHz (the SMBus figure),
    // as 107 ticks of a 16384-cycle prescaler. See src/pe_engine.v.
    // ⛔ PASSED THROUGH so the two t_HD;DAT must-fire builds are ordinary
    // builds with one number changed: `-GSDA_HOLD=0` restores the measured
    // zero-hold defect, `-GSDA_HOLD=40` runs past `t_VD;DAT` at Fm+.
    parameter integer SDA_HOLD_NS = 300,
    parameter integer CK_STRETCH_PRE = 16384,
    parameter integer CK_STRETCH_TO  = 107,
    parameter integer MISO_PIN = 7,     // uio index of the SPI-target MISO
    parameter integer CS_PIN   = 6,     // uio index of its CS input
    // ⭐ ACTION SLOTS PER LANE: 2 = double buffer (shipped), 1 = single.
    // ⛔ IN THE PARAMETRIC CONTRACT, NOT AN `ifdef`. The single-buffer engine
    // is a design alternative worth 169 flops, so it has to be BUILDABLE to
    // be measured; the stored `SWEEP_SINGLE` sweep described a configuration
    // that no command could produce. Passed through here so a bench can
    // elaborate either depth without editing the engine.
    parameter integer SPL      = 2
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

  // =====================================================================
  // ⭐⭐ RULING CDC2 -- SILICON FIXES #4 AND #5: THE HOST LEVEL CONTROLS AND
  // THE RESET RELEASE ARE SYNCHRONISED. `ui_in[7]` (PROG) fed `run` straight
  // into the engine's time counter and key adders, `ui_in[5]` (PTR_RST) fed
  // the load pointer, and `rst_n` released ~3,430 flops directly. All three
  // are asynchronous to `clk` (TT: "`clk` and `rst_n` pins are handled like
  // any other input pins"), so a transition near an edge could split the
  // state -- part of the engine running, part not; some pointer bits reset,
  // some not. Invisible to simulation and to STA (the SDC's 4 ns input delay
  // assumes a synchronous host); found because the worst timing path of
  // the 29aaeb3 canary STARTED AT A PORT.
  //   D1 `rst_n`: asserts asynchronously, RELEASES through two flops
  //      (`rst_n_s`, k = 2). Every core flop resets on `rst_n_s`; only the
  //      synchronisers themselves see the raw pin.
  //   D2/D3 `ena`, PROG, PTR_RST: two flops each (k = 2). All logic reads
  //      the synchronised copies.
  //   D4 the TX nibble and tag are NOT per-bit synchronised (a bus through
  //      per-bit synchronisers can resolve bits differently): they are
  //      sampled when the synchronised WR edge is detected, and the host
  //      holds them stable until then (docs/HOST_INTERFACE.md).
  // ⛔ M_CDC_RAW restores the 94cebb7 wiring (raw pins, raw reset release).
  // Cost: 8 flops.
  // =====================================================================
  reg [1:0] rst_sync, prog_sync, ptr_sync, ena_sync;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      rst_sync  <= 2'b00;
      prog_sync <= 2'b00;
      ptr_sync  <= 2'b00;
      ena_sync  <= 2'b00;
    end else begin
      rst_sync  <= {rst_sync[0], 1'b1};
      prog_sync <= {prog_sync[0], ui_in[PIN_PROG]};
      ptr_sync  <= {ptr_sync[0], ui_in[PIN_RST]};
      ena_sync  <= {ena_sync[0], ena};
    end
  end
`ifdef M_CDC_RAW
  wire rst_n_s = rst_n;
  wire prog_s  = ui_in[PIN_PROG];
  wire ptr_s   = ui_in[PIN_RST];
  wire ena_s   = ena;
`else
  wire rst_n_s = rst_sync[1];
  wire prog_s  = prog_sync[1];
  wire ptr_s   = ptr_sync[1];
  wire ena_s   = ena_sync[1];
`endif

  wire prog_mode = prog_s & ena_s;
  wire run       = ~prog_s & ena_s;

  // =====================================================================
  // INPUT SYNCHRONISERS. ⛔ Every pin input is asynchronous to `clk`; sampling
  // one combinationally is how a load port double-writes or drops a byte, and
  // both are silent. L_sync in the model is this chain.
  // =====================================================================
  reg [2:0] wr_sync;
  reg [1:0] uio_s0, uio_s1;             // two-flop sync, per uio bit
  // ⭐⭐ THREE STAGES NOW, NOT TWO, AND THE THIRD IS WHAT MAKES `L_sync = 3`
  // TRUE OF THE CHIP. The A2 model has carried `L_SYNC = 3` and an async-capture
  // uncertainty `L_JIT = 1` for reactive lanes since 0.9b; the chip had two
  // stages and no edge detect at all, so those constants described a mechanism
  // that did not exist. `uio_q2` completes the chain and gives edge detection
  // for free off it.
  reg [7:0] uio_q0, uio_q1, uio_q2;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wr_sync <= 3'b000;
      uio_q0  <= 8'h00;
      uio_q1  <= 8'h00;
      uio_q2  <= 8'h00;
    end else begin
      wr_sync <= {wr_sync[1:0], ui_in[PIN_WR]};
      uio_q0  <= uio_in;
      uio_q1  <= uio_q0;
      uio_q2  <= uio_q1;
    end
  end
  wire wr_rise = (wr_sync[2:1] == 2'b01);

  // ---- EDGE DETECT on every protocol input pin -------------------------
  // ⛔⛔ THIS IS THE SECOND DAY-ONE COMMITMENT, BUILT LATE. ARCH_PREREG_01
  // commitment 1: "edge timestamping on input pins -- cheap (a counter and a
  // capture register), and it is the entire substrate for protocol discovery.
  // Built even though nothing consumes it yet." It was not built, and because
  // it was not, `OP_ARM` was a no-op and the two REACTIVE lanes (UART-rx,
  // SPI-target) plus three I2C rulings rested on a mechanism that was absent.
  //
  // ⛔ AND THE RULINGS SAID IT ALREADY EXISTED. R3: "the engine already has a
  // reactive release on the observed SCL rise ... the correct rule costs
  // nothing". N1a: "the same sampled-SCL-high condition is already required by
  // A2 Part 4, so no new mechanism is needed." Both were true of the MODEL and
  // false of the CHIP: gate 0.9b CLASSIFIES a lane REACTIVE-J, and a
  // classification is not an implementation. Each ruling cited the other's
  // requirement as evidence the mechanism was there.
  //
  // ⭐ `rise = q1 & ~q2` IS A COMBINATIONAL READ OF THE SYNC CHAIN -- the edge
  // detect itself costs no flops, only the third stage does. Both polarities are
  // emitted because `OP_ARM` selects one with the action's existing level bit:
  // UART-rx arms on the START BIT'S FALL, SPI-target on CS FALL, I2C on the
  // SCL RISE. One of those is not like the others, so the polarity cannot be
  // fixed in hardware.
  wire [7:0] uio_rise = uio_q1 & ~uio_q2;
  wire [7:0] uio_fall = ~uio_q1 &  uio_q2;

  // ---- the engine's view of the pins, both banks -----------------------
  // ⭐ Inputs only ever come from `uio`; `uo_out` has no input path, which is
  //   precisely why the open-drain and tri-state classes cannot live there.
  // ⛔ The upper bits are TIED LOW for `pin_in` and for both edge vectors, so a
  //   program that arms on a `uo_out` pin can never see an edge -- it will time
  //   out rather than release, which is the safe direction and is what 1.6
  //   rejects at load time.
  wire [N_PINS-1:0] pin_in   = {{(N_PINS-8){1'b0}}, uio_q1};
  wire [N_PINS-1:0] pin_rise = {{(N_PINS-8){1'b0}}, uio_rise};
  wire [N_PINS-1:0] pin_fall = {{(N_PINS-8){1'b0}}, uio_fall};

  // =====================================================================
  // PROGRAM LOADER -- the address bus is deleted by AUTO-INCREMENT, and the
  // byte port is `uio` reused, because loading and running are mutually
  // exclusive (HALT, RELOAD, RESUME).
  // =====================================================================
  reg [AW-1:0] ptr;
  always @(posedge clk or negedge rst_n_s) begin
    if (!rst_n_s)          ptr <= {AW{1'b0}};
    else if (prog_mode) begin
      if (ptr_s)           ptr <= {AW{1'b0}};
      else if (wr_rise)    ptr <= ptr + 1'b1;
    end
  end

  // =====================================================================
  // RULING M5 -- THE CHIP REFUSES A PARTIAL LOAD.
  // ⛔⛔ The store has no reset. A host that loads 51 bytes leaves 205 holding
  // power-up contents, and the image audit cannot reach a host's bytes. So the
  // chip counts: `wr_run` is the number of CONSECUTIVE writes since the last
  // pointer reset, and its top bit -- `store_full` -- is set once 2^AW of them
  // have landed. Because the pointer auto-increments and wraps, 2^AW
  // consecutive writes from ANY start cover every address, so the flag means
  // exactly "every store byte has been written since power-on".
  // ⭐ STICKY UNTIL `rst_n`, because a byte once written stays written: a
  //   later partial re-load over a fully written store leaves no power-up byte.
  // ⛔ A POINTER RESET BEFORE SATURATION RESTARTS THE COUNT. Counting all
  //   writes instead would accept "200 bytes, pointer reset, 60 bytes" -- 260
  //   writes with 200..255 never written.
  // ⇒ TWO CONSEQUENCES, deliberately split:
  //   * the ENGINE does not run until the flag is set (`eng_run` below). That
  //     covers the power-up window too: with PROG low at reset release the
  //     engine used to start on whatever the store powered up holding.
  //   * RELEASING load mode with the flag clear sets `short_load`, a sticky
  //     reported as CONFIG_ERR (status bit 5), so the host is told WHY the
  //     part is silent. It is set at the RELEASE, not at every run entry, so
  //     a reset with PROG low -- no load attempted yet -- is not an error.
  // ⚠ The first cut set CONFIG_ERR inside the engine at run entry, and every
  //   full load was refused: benches (and hosts) release reset with PROG low
  //   for a cycle, the check fired on the empty store, and the sticky outlived
  //   the full load that followed. Measured by `test/store_run.sh`.
  // Cost: AW+3 flops.
  // =====================================================================
  reg [AW:0] wr_run;
  wire       store_full = wr_run[AW];
  reg        prog_q, short_load;
  wire       prog_rise = prog_mode & ~prog_q;   // Q2: the reload flush
  // ⭐ Q2 rule 1's switch: the queues and the RX pending byte clear on it.
  // `M_NO_RELOAD_FLUSH` is the must-fire (no flush: A7 re-sent after a
  // reload, an unread byte reaches the host).
`ifdef M_NO_RELOAD_FLUSH
  wire       reload_flush = 1'b0;
`else
  wire       reload_flush = prog_rise;
`endif
  always @(posedge clk or negedge rst_n_s) begin
    if (!rst_n_s) begin
      wr_run     <= {(AW+1){1'b0}};
      prog_q     <= 1'b0;
      short_load <= 1'b0;
    end else begin
      prog_q <= prog_mode;
      if (prog_q && !prog_mode && !store_full) short_load <= 1'b1;
      if (prog_mode && !store_full) begin
        if (ptr_s)                       wr_run <= {(AW+1){1'b0}};
        else if (wr_rise)                wr_run <= wr_run + 1'b1;
      end
    end
  end
  // ⛔ M_NO_STORE_FULL restores the old behaviour: the engine runs whatever
  //   the store holds. `test/store_run.sh` requires a 51-byte load to RUN on
  //   that build, so the gate below is shown to be what refuses it.
`ifdef M_NO_STORE_FULL
  wire eng_run = run;
`else
  wire eng_run = run & store_full;
`endif
  // ⭐⭐ CANARY (reset-network halt, Wilson): THE ENGINE'S RESET IS ONE FLOP.
  // Async-cleared by the synchronised power-on reset; otherwise it follows
  // `eng_run` on the clock, so a halt (PROG high, or a store not yet full)
  // ASSERTS it synchronously and a run DEASSERTS it synchronously. A flop's
  // Q drives the reset net: no gate, so no glitch, and STA times its
  // recovery/removal like any reset. ⚠ It is one cycle behind `eng_run` in
  // both directions -- the engine starts one cycle later than the
  // synchronous-halt design did (cycle digests would move; timing-canary only).
  reg eng_rst_n;
  always @(posedge clk or negedge rst_n_s)
    if (!rst_n_s) eng_rst_n <= 1'b0;
    else          eng_rst_n <= eng_run;
  wire cfg_err_any;          // the engine's CONFIG_ERR, or a short load

  // =====================================================================
  // THE STORE -- one instance, shared between the loader and the engine.
  // =====================================================================
  wire [AW-1:0] e_raddr;
  wire          e_re;
  wire [7:0]    s_rdata;

  // readback walk for load-mode verification
  reg [AW-1:0] rb_ptr;
  // ⛔⛔ D1: `rb_addr` IS THE ADDRESS ACTUALLY READ, AND IT EXISTS BECAUSE
  // PROGRAM BYTE 0 WAS UNREADABLE WITHOUT IT. The readback branch queues a
  // frame, increments `rb_ptr` and asserts `rb_re` on the SAME EDGE; with the
  // store's `raddr` wired to `rb_ptr` the read therefore used the
  // ALREADY-INCREMENTED pointer, so address 0 was never requested and the first
  // frame carried `s_rdata` from before any read at all.
  // ⭐ Measured, not inferred: loading [0xAA,0x22,0x33,...] and harvesting the
  // serial stream yielded 0x22,0x33,... and 0xAA never appeared.
  // ⚠ IT ALSO MADE THE RESET ALLOWLIST'S REASON FOR `s_rdata` FALSE. That entry
  // argues write-before-read because "H_CAP only runs after H_REQ", which says
  // nothing about this path; the first readback frame consumed `s_rdata`
  // unwritten. With the pre-increment address latched here, `s_rdata` is
  // consumed only after a real read and the stated reason becomes true.
  reg [AW-1:0] rb_addr;
  // ⭐ THE READBACK PRIME COUNTER, and the HOST CONTRACT it implements:
  //   * readback starts at ADDRESS 0 and the first payload frame IS byte 0;
  //   * the rewind trigger is `rst_n` -- NOT entering load mode, because the
  //     stream runs CONCURRENTLY with loading, so by the last write the walk is
  //     already past the image. The program store is deliberately unreset, so a
  //     reset rewinds the walk and keeps the image;
  //   * the stream is only meaningful once the load is COMPLETE.
  // This is written into docs/ as the host-facing contract next to the framing.
  reg [1:0]    rb_prime;
  reg [2:0]    rb_bit;
  reg          rb_re;

  wire [AW-1:0]  e_wraddr;
  wire [3*AW-1:0] e_wraddrk;                  // TM2: per-byte addresses
  wire           e_wre;
  wire [3*8-1:0] s_wrdata;

  pe_store #(.AW(AW), .MEM_TYPE(MEM_TYPE), .WIDE_B(3)) u_store (
      .clk(clk), .rst_n(rst_n_s),
      .we(prog_mode & wr_rise), .waddr(ptr), .wdata(uio_q1),
      .re(prog_mode ? rb_re : e_re),
      .raddr(prog_mode ? rb_addr : e_raddr),
      .rdata(s_rdata),
      .wre(e_wre & run), .wraddr(e_wraddr), .wraddrk(e_wraddrk),
      .wrdata(s_wrdata)
  );

  // =====================================================================
  // THE ENGINE
  // =====================================================================
  wire [N_PINS-1:0]  e_pin_out, e_pin_oe;
  wire [N_PINS-1:0]  e_pin_inv;                // CE2: inverted clock pins
  wire [N_PINS-1:0]  e_pin_isck;               // 1': declared clock pins
  wire [N_LANES-1:0] e_under, e_ovf;
  wire               e_ovr, e_busy, e_rx_push;
  wire               e_host_pop;
  wire               e_cfg_err;
  assign cfg_err_any = e_cfg_err | short_load;   // M5: one status bit
  wire               e_clk_stretch;
  wire [7:0]         e_rx_data;
  // DECLARED WITH AN EXPLICIT WIDTH, NOT `LW`, because `LW` is a localparam
  // defined further down this file. iverilog and yosys both accepted the
  // forward reference, but a width that depends on a parameter declared after
  // it is the kind of thing that elaborates in two tools and not a third --
  // and this project has already lost a harden to tool-dependent elaboration.
  // The width is checked against `LW` by an assertion below.
  wire [2:0]         e_rx_lane;

  // =====================================================================
  // THE HOST TX DATA CHANNEL -- F1's nibble channel, AS RULED
  // =====================================================================
  // ⛔⛔⛔ THIS WAS THE FOURTH DAY-ONE COMMITMENT FOUND UNBUILT, after edge
  // capture, the no-op half-bit and ruling 1.5 -- and unlike those it was the
  // direct CAUSE of a blocked work item. PHASE1_CLOSEOUT_PART3 ruled:
  //     ui_in[6]   prog: WR strobe / run: TX payload PUSH
  //     ui_in[4:1] TX payload nibble (2 pushes per byte)
  //     uio[7:0]   protocol pins ONLY -- zero spent on the data channel
  // What was built instead took `host_data` from `uio_q1` -- EIGHT BITS OF THE
  // PROTOCOL BUS -- and pushed on `ui_in[0]`, while `ui_in[4:1]` sat in the
  // `_unused` concatenation. So a host could not deliver a payload byte without
  // driving the very pins a live protocol was using, which is exactly why
  // `corpus_spim` could not address the SPI FRAM and why no I2C ACK (and
  // therefore no peer-driven clock stretch) was reachable.
  // ⚠ PART4 superseded the RX HALF of that table -- 3 spare `uo_out` pins
  // cannot carry a nibble plus a valid, so RX went bit-serial -- and PART5 framed
  // status INTO the stream, which retires the `ui_in[5]` pop and the `ui_in[0]`
  // view select. Neither supersedes the TX nibble or "zero uio spent".
  //
  // ⭐ AND ONE FIFO, which was also unbuilt. The engine's consume site read
  // `if (host_valid) l_data[cur] <= host_data; else underrun`, so the byte had to
  // be present in the EXACT cycle a lane wanted it. No real host can meet that;
  // it would simply log underruns. Two entries is enough to stage a byte ahead
  // of the lane that consumes it, and the engine pops what it takes.
  // ⛔ ONE FIFO, NOT ONE PER LANE, per the ruling: "the shift action names its
  // lane, so the host pushes bytes into one FIFO and the engine routes them as
  // the program consumes them" -- the same trick that deleted the address bus.
  // ⛔⛔⛔ PER-LANE QUEUES WITH A TAG ON PUSH, and a single shared queue was
  // WRONG. The one-FIFO design rested on "the shift action already names its
  // lane, so the program does the addressing" -- which holds only if the HOST
  // CAN PREDICT WHICH LANE CONSUMES THE NEXT BYTE. With more than one
  // TX-consuming lane active, consumption order is the EDF dispatch interleave,
  // which depends on phase and timing, so the host would have to simulate the
  // scheduler. Get it wrong and the wrong lane transmits the wrong byte, and
  // NOTHING FLAGS IT.
  //
  // ⚠ AND THERE ARE FOUR TX-CONSUMING LANES, NOT THREE. `OP_SHIFT` reads
  // `l_data[cur][0]`, so any lane that shifts consumes payload -- and the
  // SPI-TARGET transmits on MISO. The shipped set is lanes 0 (UART-tx),
  // 1 (SPI-master MOSI), 2 (I2C SDA) and 4 (SPI-target MISO); lane 3 (UART-rx)
  // is the only receive-only lane.
  // ⛔ SO THE TAG IS EXACTLY FULL AT 2 BITS, with no headroom, and "lane 3
  // cannot be fed" is baked into hardware. That is a real restriction on a
  // table-driven design, and it is here because only two input pins came free
  // (the retired RX pop and view select). ⭐ THE ESCAPE HATCH, if a fifth
  // transmitter is ever wanted, is to carry the tag IN THE DATA STREAM rather
  // than on pins -- 1.6n measures the channel at 10.7 % utilised, so a third
  // push per byte is affordable and the tag width stops being pin-limited.
  //
  // ⭐ PER-LANE QUEUES RATHER THAN ONE TAGGED QUEUE, and the difference is
  // correctness, not cost. A single queue whose entries carry a tag HEAD-OF-LINE
  // BLOCKS: if the head is tagged for lane A and lane B consumes first, B
  // underruns while A's byte sits in front of it -- the ordering problem back in
  // another form. Each lane popping its own queue cannot do that.
  // ⛔ THE SAME DERIVATION AS pe_engine.v, COPIED VERBATIM rather than
  // written as a literal 3: a lane-index width kept in two files as two
  // different expressions is the drift this project keeps paying for, and a
  // bare literal would also break the no-bare-widths rule the RTL follows.
  localparam integer LW    = (N_LANES <= 2) ? 1 : (N_LANES <= 4) ? 2 :
                             (N_LANES <= 8) ? 3 : 4;
  localparam integer TXD  = 2;                // depth per lane, bytes
  localparam integer TXN  = 4;                // queues = TX-consuming lanes

  wire push_rise = run & wr_rise;             // `ui_in[6]` is WR in load mode
  wire [1:0] tx_tag_pins = {ui_in[5], ui_in[0]};

  // flat arrays with index arithmetic: a 2-D unpacked array is legal
  // Verilog-2001 but risks the non-SystemVerilog reader the synthesis gate uses.
  reg  [7:0] tx_mem [0:TXN*TXD-1];
  reg  [1:0] tx_cnt [0:TXN-1];
  reg        tx_wp  [0:TXN-1];
  reg        tx_rp  [0:TXN-1];
  reg  [7:0] tx_asm;                          // the half-assembled byte
  reg        tx_half;                         // 0 = expect HIGH nibble
  reg  [1:0] tx_tag;                          // LATCHED at the first push
  reg        tx_full_sticky;
  integer    ti;

  // ---- the queue is named by the ACTION, not by the lane ---------------
  // ⛔⛔ THE FIRST VERSION BAKED LANE NUMBERS INTO HARDWARE: tag -> lanes
  // {0,1,2,4}, which made "lane 3 cannot be fed" a hardware fact in a chip whose
  // whole premise is that roles are assigned per program. A protocol constant in
  // disguise. Now the 2-bit tag names a QUEUE, each SHIFT action names the queue
  // it draws from, and ANY lane may transmit.
  wire [LW-1:0] e_host_lane;                  // diagnostics only
  wire [1:0]    e_host_q;
  wire [1:0]    q_sel    = e_host_q;
  wire          tx_valid = (tx_cnt[q_sel] != 2'd0);
  wire [7:0]    tx_head  = tx_mem[{q_sel, tx_rp[q_sel]}];

  // ⭐ THE POP AS A PER-QUEUE VECTOR, so the queue block below is the same
  // for every variant of the TX path (silicon fix #8's (a) pops one queue,
  // the action's; (b4) may pop several) and the benches read one interface.
  wire [3:0] do_popq = (e_host_pop & tx_valid) ? (4'b0001 << q_sel) : 4'b0000;

  wire nib_lo  = push_rise & tx_half;         // the push that completes a byte
  wire do_push = nib_lo & ((tx_cnt[tx_tag] != TXD[1:0]) | do_popq[tx_tag]);

  always @(posedge clk or negedge rst_n_s) begin
    if (!rst_n_s) begin
      tx_asm <= 8'h00; tx_half <= 1'b0; tx_tag <= 2'd0;
      tx_full_sticky <= 1'b0;
      for (ti = 0; ti < TXN; ti = ti + 1) begin
        tx_cnt[ti] <= 2'd0;
        tx_wp[ti]  <= 1'b0;
        tx_rp[ti]  <= 1'b0;
      end
    end else begin
      // ⭐ HIGH NIBBLE FIRST, and THE TAG IS LATCHED WITH IT. A host that
      // changed the tag pins between the two pushes of one byte would otherwise
      // split that byte across two queues; latching at the first push makes the
      // byte and its destination one object.
      if (push_rise) tx_half <= ~tx_half;
      if (push_rise && !tx_half) begin
        tx_asm[7:4] <= ui_in[4:1];
        tx_tag      <= tx_tag_pins;
      end

      if (do_push) begin
        tx_mem[{tx_tag, tx_wp[tx_tag]}] <= {tx_asm[7:4], ui_in[4:1]};
        tx_wp[tx_tag]                   <= ~tx_wp[tx_tag];
      end
      // ⭐ ONE ASSIGNMENT PER COUNTER, with the same-queue push+pop enumerated.
      // Different queues are independent, so each updates on its own.
      for (ti = 0; ti < TXN; ti = ti + 1) begin
        if (do_popq[ti]) tx_rp[ti] <= ~tx_rp[ti];
        if (do_push && tx_tag == ti[1:0] && do_popq[ti])
          tx_cnt[ti] <= tx_cnt[ti];             // one in, one out
        else if (do_push && tx_tag == ti[1:0])
          tx_cnt[ti] <= tx_cnt[ti] + 2'd1;
        else if (do_popq[ti])
          tx_cnt[ti] <= tx_cnt[ti] - 2'd1;
      end

      // ⛔ A PUSH ON A FULL QUEUE IS REPORTED, NEVER A STALL. The host has no
      // back-pressure pin, so the only honest answer is a sticky flag in the
      // status frame -- the same reasoning as RX overflow: a host that has
      // stopped reading cannot be told by a pin it is not reading.
      if (nib_lo && !do_push) tx_full_sticky <= 1'b1;
      // ⛔⛔ RELOAD IS A CLEAN SLATE (Wilson Q2, rule 1): the synchronised PROG
      // rise empties every TX queue and a half-assembled byte. Pushes while
      // PROG is high are store writes (`push_rise` is gated by `run`), so no
      // legitimate byte is lost. After a reload, TX starts with the first byte
      // pushed after PROG falls. Last assignment wins over a same-cycle push.
      // The sticky TX-FULL is status, not queue state, and is kept.
      if (reload_flush) begin
        tx_half <= 1'b0;
        for (ti = 0; ti < TXN; ti = ti + 1) begin
          tx_cnt[ti] <= 2'd0;
          tx_wp[ti]  <= 1'b0;
          tx_rp[ti]  <= 1'b0;
        end
      end
    end
  end

  pe_engine #(
      .N_LANES(N_LANES), .AW(AW), .N_PINS(N_PINS), .N_UIO(8),
      .TS_W(TS_W), .DLY_W(DLY_W), .D_W(D_W), .SPL(SPL),
      // ⭐ PASSED THROUGH so a bench can shorten the prescaler and reach the
      // bus-fault bound in hundreds of cycles instead of 1.75 million.
      .CK_STRETCH_PRE(CK_STRETCH_PRE), .CK_STRETCH_TO(CK_STRETCH_TO),
      // ⭐ PASSED THROUGH so a bench can build the zero-hold defect and an
      // over-long hold, which is what prices the t_HD;DAT requirement at both
      // ends rather than only at its floor.
      .SDA_HOLD_NS(SDA_HOLD_NS)
  ) u_eng (
      .clk(clk), .rst_n(eng_rst_n), .por_n(rst_n_s), .run(eng_run),
      .s_raddr(e_raddr), .s_re(e_re), .s_rdata(s_rdata),
      .s_wraddr(e_wraddr), .s_wraddrk(e_wraddrk), .s_wre(e_wre),
      .s_wrdata(s_wrdata),
      .pin_out(e_pin_out), .pin_oe(e_pin_oe), .pin_inv(e_pin_inv),
      .pin_isck(e_pin_isck),
      .pin_in(pin_in),
      .pin_rise(pin_rise), .pin_fall(pin_fall),
      .host_data(tx_head), .host_valid(tx_valid), .host_pop(e_host_pop),
        .host_lane(e_host_lane), .host_q(e_host_q),
      .lane_underrun(e_under), .lane_overflow(e_ovf), .sticky_ovr(e_ovr),
        .cfg_err(e_cfg_err),
        .clk_stretch(e_clk_stretch),
      .rx_data(e_rx_data), .rx_lane(e_rx_lane), .rx_push(e_rx_push),
      .busy(e_busy)
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
  // THE FRAME IS 12 BITS: {marker, kind[2:0], data[7:0]}, and it was 9.
  // It carried only {marker, data}, so a payload frame could not say WHICH
  // lane produced it -- and worse, a READBACK byte and an RX payload byte
  // BOTH used marker = 0, so the two were already indistinguishable on the
  // wire and were being told apart by which mode the host believed it was in.
  // THE MARKER IS SHIFTED OUT LAST, so a variable-length frame is not an
  // option: the host cannot know a frame's width until it has already read
  // most of it. Both frame types therefore widen together.
  // `kind` RESOLVES BOTH QUESTIONS AT ONCE:
  //     marker 1              -> STATUS           (kind = KIND_NONE)
  //     marker 0, kind 0..4   -> RX PAYLOAD from THAT LANE
  //     marker 0, kind 7      -> READBACK byte, not a lane
  // Cost: 3 flops on `ser_sh`. `ser_cnt` already had the range.
  localparam [2:0] KIND_NONE = 3'd7;    // "not a lane"
  // THE EXPLICIT WIDTH ABOVE MUST EQUAL `LW`, AND THE CHECK IS IN THE
  // TOOLCHAIN, NOT HERE. `e_rx_lane` is declared [2:0] because `LW` is not in
  // scope that early; if `N_LANES` grew past 8 then `LW` would become 4 and
  // the explicit 3 would SILENTLY TRUNCATE the lane id -- a byte attributed to
  // the WRONG lane, which is the exact failure this field exists to prevent.
  // The `kind` field in the frame is 3 bits too, so growing past 7 lanes needs
  // the frame widened as well.
  // A generate-guarded zero-width net was tried here as a compile-time
  // assertion and iverilog accepted `wire x[-1:0]` SILENTLY -- it was
  // decoration, which is worse than nothing because it reads as a guard.
  // Priced by inverting it: the build stayed green. ⇒ The real check lives in
  // `model/part1_param_contract.py`, which runs in CI.
  reg [11:0] ser_sh;                    // {marker, kind[2:0], data[7:0]}
  reg [3:0] ser_cnt;
  localparam [3:0] FRAME_LEN = 4'd12;
  reg       ser_phase;
  reg [7:0] status_byte;
  reg       status_turn;
  // the ERROR bits only -- status_byte[0] is the always-1 alive bit, so
  // including it would make the stream permanently busy.
  // ⛔⛔ AN RX PENDING REGISTER, BECAUSE PRIORITY AT THE QUEUE POINT IS NOT
  // ENOUGH. `e_rx_push` is a ONE-CYCLE PULSE, so a payload arriving while any
  // frame is shifting was simply LOST -- and once a sticky flag trips,
  // self-started status fills every idle slot, so "status competes with RX"
  // would have meant dropped bytes, not just delay. Holding the payload one
  // deep makes "no RX payload pending" a thing that can be tested, which is
  // what lets status self-start safely.
  // ⚠ ONE DEEP, NOT A FIFO: the serialiser takes 18 cycles per frame and the
  // fastest RX lane delivers a byte every 414, so one holding register is two
  // orders of margin. A second pulse arriving while one is still pending is a
  // genuine overrun and is reported, never silently dropped.
  reg       rx_pend;
  reg [7:0] rx_pend_data;
  reg [LW-1:0] rx_pend_lane;            // travels WITH the byte
  reg       rx_drop_sticky;           // status bit 6

  wire      status_pending = cfg_err_any | tx_full_sticky | e_ovr
                           | rx_drop_sticky
                           | (|e_ovf) | (|e_under);

  always @(posedge clk or negedge rst_n_s) begin
    if (!rst_n_s) begin
      ser_d <= 1'b0; ser_s <= 1'b0; ser_v <= 1'b0;
      rx_pend <= 1'b0; rx_pend_data <= 8'h00;
      rx_pend_lane <= {LW{1'b0}};
      rx_drop_sticky <= 1'b0;
      ser_sh <= 12'h000; ser_cnt <= 4'd0; ser_phase <= 1'b0;
      status_byte <= 8'h00; status_turn <= 1'b0;
      rb_ptr <= {AW{1'b0}}; rb_addr <= {AW{1'b0}}; rb_bit <= 3'd0; rb_re <= 1'b0;
      rb_prime <= 2'd0;
    end else begin
      // the sticky status, assembled once so both modes frame the same byte
      // ⭐ bit 4 = TX-FULL, which F1's status list named and nothing carried.
      // ⭐ bit 5 = CONFIG_ERR (1.6s): the program named an open-drain lane on
      // a `uo_out` pin, so the chip REFUSED TO RUN it. The host learns why
      // from the stream rather than from a part that sits silent.
      // ⭐ bit 6 = RX-DROP: a payload arrived while one was still pending.
      // ⭐ bit 7 = CLOCK-STRETCH: a clocked SHIFTIN consume point found no
      // captured bit, so the peer held the clock past this lane's next
      // dispatch. ⛔ THIS BIT WAS THE HARDCODED 0, which is why adding it
      // changes no existing program's status byte: any image that never runs
      // a clocked SHIFTIN leaves it 0, exactly as the literal did. The
      // bit-identity condition is not weakened by it.
      status_byte <= {e_clk_stretch, rx_drop_sticky, cfg_err_any, tx_full_sticky,
                      e_ovr, |e_ovf, |e_under, 1'b1};
      rb_re <= 1'b0;
      // capture the RX pulse the instant it appears, whatever the serialiser
      // is doing. ⛔ A second pulse while one is pending is an OVERRUN: the
      // host is told, because the alternative is a byte that never existed.
      if (e_rx_push) begin
        if (rx_pend) rx_drop_sticky <= 1'b1;
        else begin
          rx_pend      <= 1'b1;
          rx_pend_data <= e_rx_data;
          rx_pend_lane <= e_rx_lane;
        end
      end

      // ⛔ Q2 RX side: a received byte the host has not read yet is cleared
      // by the reload too (HOST_INTERFACE: drain RX before raising PROG).
      if (reload_flush) rx_pend <= 1'b0;
      if (ser_cnt != 4'd0) begin
        // shifting a frame out: one bit per two cycles, strobe in the middle
        ser_phase <= ~ser_phase;
        if (ser_phase) begin
          ser_sh  <= {1'b0, ser_sh[11:1]};
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
          ser_sh      <= {1'b1, KIND_NONE, status_byte};
          ser_cnt     <= FRAME_LEN;
          status_turn <= 1'b0;
        end else if (prog_mode) begin
          // ⛔ THE SERIAL RX VIEW IS UNCONDITIONAL. This was wrapped in
          // `if (RX_SERIAL != 0)` until the coverage sweep showed the
          // parameter was overridden NOWHERE in the tree: its only two
          // references were the declaration and this use, so the implicit
          // `else` was shipped source that no configuration executed. The
          // sweep offered two honest resolutions -- sweep it as a build arm
          // the way `SPL_CFG = 1` is, or delete it -- and DELETE was ruled.
          // ⚠ The parameter's stated justification in the Part 1 contract and
          // the S2 freeze was "the sweep needs to be able to turn it off to
          // measure what it costs". That was never exercised in any arm, which
          // is exactly why it went: an unexercised knob is not a priced one.
          // ⛔⛔ PRIME BEFORE FRAMING, and `rb_addr` alone was not enough.
          // Latching the pre-increment address made byte 0 REACHABLE, but a
          // frame is queued from `s_rdata` in the same breath as the read is
          // REQUESTED, so frame 1 still carried whatever the register held
          // from the previous walk: the stream read 0x22(stale), 0xAA, 0x22,
          // ... with the image's own byte 0 arriving SECOND.
          // ⭐ So the first two visits issue the read and let it land,
          // queueing NO frame; from then on every frame carries the byte its
          // own request fetched and byte 0 is the FIRST payload. This is the
          // same prime-before-release shape the engine already uses, for the
          // same reason: a pipeline's first output is not data.
          if (rb_prime != 2'd2) begin
            if (rb_prime == 2'd0) begin
              rb_addr <= rb_ptr;            // address 0, pre-increment
              rb_ptr  <= rb_ptr + 1'b1;
              rb_re   <= 1'b1;
            end
            rb_prime <= rb_prime + 2'd1;
          end else begin
            ser_sh  <= {1'b0, KIND_NONE, s_rdata};
            ser_cnt <= FRAME_LEN;
            rb_addr <= rb_ptr;          // THE PRE-INCREMENT ADDRESS
            rb_ptr  <= rb_ptr + 1'b1;
            rb_re   <= 1'b1;
            status_turn <= 1'b1;
          end
        end else if (rx_pend) begin
          // ⭐ A PAYLOAD ALWAYS WINS THE NEXT FRAME SLOT. Checked before the
          // self-started status below, so a set sticky flag can never push data
          // out of the stream -- it only fills slots the payload did not want.
          // THE LANE TRAVELS WITH THE BYTE, which is the whole point: it is
          // taken from `rx_pend_lane`, captured at the push, and NOT from
          // whatever lane the engine happens to be running now.
          // M_RX_NO_LANE pins the field to 0, which is what shipped in effect
          // -- every received byte looking like lane 0's -- so the field is
          // PRICED rather than only ever seen to carry the right value. ⚠ Note
          // the mutant is NOT "no field at all": the frame keeps its width, so
          // the bench still decodes and the failure is an ATTRIBUTION error
          // rather than a framing one. A mutant that broke the framing would
          // be killed by the wrong assertion.
`ifdef M_RX_NO_LANE
          ser_sh      <= {1'b0, 3'd0, rx_pend_data};
`else
          ser_sh      <= {1'b0, rx_pend_lane, rx_pend_data};
`endif
          ser_cnt     <= FRAME_LEN;
          rx_pend     <= 1'b0;
          status_turn <= 1'b1;
        end else if (status_pending) begin
          // ⛔⛔ A SILENT PART CANNOT REPORT WHY IT IS SILENT. In run mode the
          // stream only ever carried a status frame AFTER a payload frame, so
          // with no RX traffic NOTHING was emitted at all -- and a program the
          // chip REFUSES to run produces no traffic by definition. CONFIG_ERR
          // was therefore unreadable exactly when it mattered.
          // ⚠ The comment above claims "liveness is in the stream even when no
          // payload is moving". That was true of the intent and not of the code.
          // ⭐ RATE-LIMITED BY THE FLAGS THEMSELVES, not by a timer: status is
          // self-started only while a sticky error is set. An unconditional
          // idle heartbeat would emit a frame every 18 cycles and, because
          // `e_rx_push` is a PULSE that is lost while a frame shifts, would
          // turn the heartbeat into RX overflow -- paying for liveness with the
          // data it exists to report. 1.6p prices that channel at 2.2 %.
          ser_sh      <= {1'b1, KIND_NONE, status_byte};
          ser_cnt     <= FRAME_LEN;
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

  // ⭐⭐ SILICON FIX #6 (ruling CS1): THE CLEAR'S RELEASE MUST FIND D = 0.
  // CS falls at any instant relative to `clk`, so the async clear can be
  // released inside the flop's recovery window -- harmless only if D is
  // already 0 then. It was NOT: the engine holds `pin_oe[MISO]` = 1 between
  // transactions, and `test/inv_cdc.vh` saw D = 1 on the first CS fall of
  // corpus_sptgt (CDC2 D5; the "benign" argument was refuted by its own
  // check). So D is qualified by the SYNCHRONISED CS (`uio_q1`): it stays 0
  // until the uio synchroniser has seen CS low, and a marginal release
  // resolves to 0 by construction. The clear on CS high is unchanged: MISO
  // still releases the instant the master deselects. Cost: one gate. The
  // enable now rises 2 cycles after CS falls (docs/HOST_INTERFACE.md).
  // ⛔ M_CS_RAW_D restores the unqualified D input.
  reg miso_oe_q;
`ifdef M_CS_RAW_D
  wire miso_oe_d = e_pin_oe[MISO_PIN] & run;
`else
  wire miso_oe_d = e_pin_oe[MISO_PIN] & run & ~uio_q1[CS_PIN];
`endif
  always @(posedge clk or posedge cs_deasserted or negedge rst_n_s) begin
    if (!rst_n_s)            miso_oe_q <= 1'b0;
    else if (cs_deasserted)  miso_oe_q <= 1'b0;   // ASYNC release
    else                     miso_oe_q <= miso_oe_d;
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

  // ⛔⛔ THE `prog_mode` MUX IS GONE, AND F2 FACE 3 IS WHY. It used to read
  //   assign uio_oe  = prog_mode ? 8'h00 : uio_oe_run;
  //   assign uio_out = prog_mode ? 8'h00 : e_pin_out[7:0];
  // which is a COMBINATIONAL function of `prog_mode` = `ui_in[7] & ena`, a RAW
  // ASYNCHRONOUS INPUT. The first real gate-level netlist showed all 16
  // `uio_out`/`uio_oe` bits driven by `and2`/`nor2` rather than a flop: a host
  // transition on prog_mode could glitch every uio pin, and SCL and SCLK are in
  // that bank, where a glitch is an EXTRA CLOCK EDGE -- a corruption, not a
  // margin problem. Ruling F2 exists for precisely this.
  // ⭐ LOAD MODE STILL RELEASES EVERY `uio`, but now at the SOURCE: the engine
  // clears `pin_oe` in its `!run` branch, so the release happens behind the
  // flop that was already there and every bit here is a flop Q.
  // ⭐⭐ AND MISO'S ASYNC CLEAR SURVIVES, which a 16-flop output register would
  // have destroyed: 1.6r requires `uio_oe[MISO]` to release ASYNCHRONOUSLY on
  // CS, so re-registering it would have made the release synchronous and broken
  // the ruling while satisfying F2. `miso_oe_q` reaches the pin directly, still
  // a flop Q, still async-cleared -- the two rulings are compatible only
  // because the fix went upstream rather than downstream.
  // ⛔ M_COMB_OUT restores the defect, so the local F2 check is PRICED: a
  // structural check that has only ever been seen pass has unknown strength,
  // and this one is new. The mutant must make it RED.
`ifdef M_COMB_OUT
  assign uio_oe  = prog_mode ? 8'h00 : uio_oe_run;
  assign uio_out = prog_mode ? 8'h00 : e_pin_out[7:0];
`else
  assign uio_oe  = uio_oe_run;
  assign uio_out = e_pin_out[7:0];
`endif

  // ---- `uo_out`: 4 protocol + 3 serial + 1 spare
  // ⛔ In LOAD MODE the 4 protocol outputs are HELD AT IDLE (high), not used for
  //    readback. Readback goes out on the serial trio above. This is the fix for
  //    the constructed-image FRAM write.
  // ⛔⛔ RULING CE2 -- CLK_INV, AND WHY ONLY HERE. An inverted clock pin turns
  // SPI mode 3 into mode 1 and mode 0 into mode 2 with the phase machine
  // untouched (the push-pull capture fires at the engine's own HIGH phase,
  // which on an inverted pin IS the falling edge modes 1/2 sample on). The XOR
  // sits BEFORE `uo_q`, so every `uo_out` bit is still a flop Q (F2). On `uio`
  // the only place left would be after the last flop -- F2 forbids it, so a
  // `uio` clock with CLK_INV is refused by the toolchain and never set.
  // ⚠ THE IDLE LEVEL FLIPS ONCE, when the header loads: before it every
  // protocol output idles high; after it an inverted SCK idles low. Headers
  // load before any dispatch, so CS is still deasserted -- a bench checks it.
  // `M_CLKINV_IGNORED` drops the XOR.
  // ⛔⛔ OPTION 1' (Wilson): A TWO-PHASE HALT. Forcing all four protocol
  // outputs high in ONE cycle raised CS and SCK on the same edge, and on real
  // pads skew decides which lands first: SCK first after 7 bits makes an SPI
  // peer complete a byte with a stale 8th bit and WRITE it. So in the FIRST
  // PROG cycle (`prog_rise`) every output except a declared clock pin goes
  // idle, and the clock pins hold their running level; from the second cycle
  // all four are forced as before. CS therefore leads any halt-caused SCK
  // edge by a full clock. `M_ONE_PHASE_HALT` restores the single-phase force.
`ifdef M_ONE_PHASE_HALT
  wire [3:0] halt_force = 4'b1111;
`else
  wire [3:0] halt_force = prog_rise ? ~e_pin_isck[11:8] : 4'b1111;
`endif
`ifdef M_CLKINV_IGNORED
  wire [3:0] run_out   = e_pin_out[11:8];
`else
  wire [3:0] run_out   = e_pin_out[11:8] ^ e_pin_inv[11:8];
`endif
  wire [3:0] proto_out = prog_mode ? (halt_force | (run_out & ~halt_force))
                                   : run_out;

  reg [7:0] uo_q;
  always @(posedge clk or negedge rst_n_s) begin
    // ⭐ RESET: the 4 protocol outputs go HIGH (forced -- `uo_out` cannot
    //    release), the serial trio goes low, the spare goes low.
    if (!rst_n_s) uo_q <= 8'h0F;
    else        uo_q <= {1'b0, ser_v, ser_s, ser_d, proto_out};
  end
  assign uo_out = uo_q;

  // ---- unused -----------------------------------------------------------
  // ⭐ `ui_in[4:1]` IS NO LONGER UNUSED -- it is the TX payload nibble, which
  // is the whole point of the fix above. `uio_q2` is the edge-detect tail.
  wire _unused = &{e_busy, uio_q2, 1'b0};   // `ena` is read via `ena_sync` (CDC2)

endmodule
