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
    parameter integer AW       = 9,     // 2**AW program bytes (v2: 512 B)
    parameter integer N_PINS   = 12,    // addressable protocol pins, both banks
    parameter integer TS_W     = 16,    // global counter / timestamp width
    parameter integer DLY_W    = 10,    // program delay field
    parameter integer D_W      = 8,     // D_sched field
    // ⭐ THE LATCH STORE (Wilson 10-31, Track 2): the 512 bytes in latches, one
    // clock gate per row -- -30 % of the chip in stock cells. "flops" is the
    // reference arm (and v1-lock's store).
    // ⭐ THE SRAM STORE IS THE STORE (Wilson 11-07): the latch store fails CTS at
    // density 60 and worse at 58 (DPL-0036 on its gated-row clock buffers, a
    // local clock-tree wall); the IHP 1P 256x32 macro clears CTS and global
    // routing and saves ~146k placed. The fallbacks stay selectable:
    // PE_MEM_LATCH (the latch store), PE_MEM_FLOPS (the reference / v1-lock).
`ifdef PE_MEM_LATCH
    parameter         MEM_TYPE = "latch",
`elsif PE_MEM_FLOPS
    parameter         MEM_TYPE = "flops",
`else
    parameter         MEM_TYPE = "sram",
`endif
    // ⛔ `RX_SERIAL` WAS DELETED HERE, by ruling. It was overridden nowhere in
    // the tree, so its `else` was source no configuration executed; the serial
    // RX view is now unconditional at its one use site. It is NOT coming back
    // as an `ifdef`: the point of the deletion is that an unexercised knob is
    // not a priced alternative, and an `ifdef` would restore the dead arm
    // without restoring a build that runs it.
    // ⛔ fixed at build time because the async release path cannot be muxed
    // ⛔⛔ THE CHIP'S CLOCK, in whole picoseconds, rounded down (Wilson
    // 11-03). `model/gate_clock_consistency.py` holds it to info.yaml's
    // clock_hz, config.json's CLOCK_PERIOD and pe_engine.v's default. The FPGA
    // core passes its own board's period. See src/pe_engine.v.
    parameter integer CLK_PERIOD_PS = 16666,
    // the clock-stretch BUS-FAULT bound: 35 ms (the SMBus figure), as ticks
    // of a 16384-cycle prescaler -- 107 at 50 MHz, 129 at 60. See
    // src/pe_engine.v.
    // ⛔ PASSED THROUGH so the two t_HD;DAT must-fire builds are ordinary
    // builds with one number changed: `-GSDA_HOLD=0` restores the measured
    // zero-hold defect, `-GSDA_HOLD=40` runs past `t_VD;DAT` at Fm+.
    parameter integer SDA_HOLD_NS = 300,
    parameter integer CK_STRETCH_NS  = 35000000,
    // ⭐ THE TICK COUNT IS DERIVED FROM THE SHIPPED PRESCALER, NOT FROM
    // `CK_STRETCH_PRE`: a bench shortens the prescaler to reach the SAME
    // tick bound in hundreds of cycles (`corpus_i2c_sclfault`), so the bound
    // must not grow when it does.
    parameter integer CK_TICK_SHIPPED = 16384,
    parameter integer CK_STRETCH_PRE = CK_TICK_SHIPPED,
    parameter integer CK_STRETCH_TO  =
        (CK_STRETCH_NS + (CK_TICK_SHIPPED * CLK_PERIOD_PS) / 1000 - 1)
        / ((CK_TICK_SHIPPED * CLK_PERIOD_PS) / 1000),
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
  wire prog_n  = ui_in[PIN_PROG];
  wire ena_n   = ena;
`else
  wire rst_n_s = rst_sync[1];
  wire prog_s  = prog_sync[1];
  wire ptr_s   = ptr_sync[1];
  wire ena_s   = ena_sync[1];
  wire prog_n  = prog_sync[0];   // prog_s's NEXT value (step 1: the mode flops)
  wire ena_n   = ena_sync[0];
`endif

  // ⛔⛔ v2 SLACK RECOVERY (Wilson 10-27), steps 1 + 1b. `prog_mode` and `run`
  // ARE FLOPS, and `prog_mode` IS REPLICATED. They are mode signals (they
  // change only on entering / leaving load mode); as a gate, `prog_mode` led
  // the slow corner's worst path -- ena_s -> nand -> inv -> one buffer tree
  // across the store (canary 40421958249, +0.870 ns; +2.073 as one flop,
  // +3.124 replicated). Each flop loads `prog_n & ena_n` -- prog_s/ena_s's
  // NEXT value -- so it EQUALS the old `prog_s & ena_s` in every cycle after
  // the synchronised reset releases (gate_v2_equiv 42/42 is the check).
  // ⚠ RESET FROM `rst_n_s`, like all non-synchroniser logic (gate_cdc): the
  // one difference from the old gate is a PROG held high THROUGH reset
  // release, which this flop sees one cycle later.
  // REPLICATION: one copy per consumer cone (loader, store read select, pins)
  // and one per store bank (the write enable), each a `pe_dup_ff` (end of
  // this file) marked (* keep_hierarchy *) -- measured on yosys 0.69,
  // identical flops are merged back into one by opt_merge after flattening
  // whatever `keep` on a reg or an instance says; only a kept hierarchy
  // stops it. Under M_CDC_RAW the same flops load the RAW pins.
  wire prog_mode, pm_rd, pm_pin;
  wire pm_next = prog_n & ena_n;
  pe_dup_ff u_pm_ld  (.clk(clk), .rst_n(rst_n_s), .d(pm_next), .q(prog_mode));
  pe_dup_ff u_pm_rd  (.clk(clk), .rst_n(rst_n_s), .d(pm_next), .q(pm_rd));
  pe_dup_ff u_pm_pin (.clk(clk), .rst_n(rst_n_s), .d(pm_next), .q(pm_pin));
  reg run;
  always @(posedge clk or negedge rst_n_s) begin
    if (!rst_n_s) run <= 1'b0;
    else          run <= ~prog_n & ena_n;
  end

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
  // ⭐ PE_SIM_LATE_WR -- SIMULATION ONLY (Wilson 11-10, the host hold rule): the
  // synchroniser's first flop RESOLVING LATE, the case a zero-delay simulator
  // never produces. The pad level reaches wr_sync[0] one cycle later, so every
  // push captures on the 4th edge after the pad edge instead of the 3rd -- the
  // worst case docs/HOST_FIRMWARE.md FW-1 is sized for. Never in a flow config
  // (gate_clock_consistency check 5 refuses bench-only defines in synthesis).
`ifdef PE_SIM_LATE_WR
  reg wr_pad_late;
  always @(posedge clk) wr_pad_late <= ui_in[PIN_WR];
`endif
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wr_sync <= 3'b000;
      uio_q0  <= 8'h00;
      uio_q1  <= 8'h00;
      uio_q2  <= 8'h00;
    end else begin
`ifdef PE_SIM_LATE_WR
      wr_sync <= {wr_sync[1:0], wr_pad_late};
`else
      wr_sync <= {wr_sync[1:0], ui_in[PIN_WR]};
`endif
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
  // ⛔⛔ v2 (Wilson Q3): THE IMAGE'S 16-BIT MAGIC + VERSION, checked AS IT
  // LOADS. In v1 byte 30 was the first action's first byte, so a v1 image can
  // hold anything there; bytes 30-31 = 0x56 0x32 leave 1 in 65,536. Latched
  // from the write stream -- ZERO cycles at run, so a good image's trace is
  // untouched -- and an image without it is refused exactly as a short load
  // is: the engine does not run and CONFIG_ERR is reported.
  // MAGIC_AT is derived from the header layout (model/gate_one_encoder.py
  // holds it to test/pe_isa.py's HDR_REGION).
  localparam integer MAGIC_PINW = (N_PINS <= 2) ? 1 : (N_PINS <= 4) ? 2 :
                                  (N_PINS <= 8) ? 3 : (N_PINS <= 16) ? 4 : 5;
  localparam integer MAGIC_AT = N_LANES *
      ((MAGIC_PINW * 2 + 1 + DLY_W + 4 + D_W + D_W + 8 + 1 + 7) / 8);
  localparam [7:0] MAGIC_HI = 8'h56, MAGIC_LO = 8'h32;
  localparam [AW-1:0] MAGIC_A0 = MAGIC_AT[AW-1:0];
  localparam [AW-1:0] MAGIC_A1 = MAGIC_A0 + {{(AW-1){1'b0}}, 1'b1};
  reg magic_hi, magic_lo;
  // ⭐ v2 PIT (Wilson 10-28): the SNIFF magic 'S' 'N' at the same two bytes
  // selects SNIFF mode -- NO new pin (all 8 ui_in are used). Byte 0 of a
  // SNIFF image is the wire mask. The engine never runs on a SNIFF image.
  localparam [7:0] SNIFF_HI = 8'h53, SNIFF_LO = 8'h4E;
  reg sniff_hi, sniff_lo;
  reg [7:0] pit_mask;
  reg [7:0] pit_bud;     // SNIFF image byte 1: the capture budget, 2^b cycles (0 = off)
  always @(posedge clk or negedge rst_n_s) begin
    if (!rst_n_s) begin
      magic_hi <= 1'b0;
      magic_lo <= 1'b0;
      sniff_hi <= 1'b0;
      sniff_lo <= 1'b0;
      pit_mask <= 8'h00;
      pit_bud  <= 8'h00;
    end else if (prog_mode & wr_rise) begin
      if (ptr == MAGIC_A0) magic_hi <= (uio_q1 == MAGIC_HI);
      if (ptr == MAGIC_A1) magic_lo <= (uio_q1 == MAGIC_LO);
      if (ptr == MAGIC_A0) sniff_hi <= (uio_q1 == SNIFF_HI);
      if (ptr == MAGIC_A1) sniff_lo <= (uio_q1 == SNIFF_LO);
      if (ptr == {AW{1'b0}}) pit_mask <= uio_q1;
      if (ptr == {{(AW-1){1'b0}}, 1'b1}) pit_bud <= uio_q1;
    end
  end
  wire sniff = sniff_hi & sniff_lo;
`ifdef M_NO_MAGIC
  wire bad_magic = 1'b0;
`else
  wire bad_magic = store_full & ~((magic_hi & magic_lo) | sniff);
`endif
  // ⭐ v2: one action word = ACT_BYTES bytes, read as one store row. DERIVED
  // (the engine's ACT_W, inlined: OP_W 5 + PINW + 1 + DLY_W + BPW 4 + BQW 2 +
  // PINB_W 4 + MOD_W 2); model/gate_one_encoder.py holds it to pe_isa.
  localparam integer ACT_BYTES_T =
      (5 + MAGIC_PINW + 1 + DLY_W + 4 + 2 + 4 + 2 + 7) / 8;
  // ⛔⛔ v2 (Wilson 10-26): A RESERVED OPCODE IS REFUSED AT LOAD. The engine's
  // `case (a_op)` names only the BUILT opcodes; v2's opcode is 5 bits, so a
  // raw image (no pe_asm) holding opcode >= N_BUILT_OPS would reach its
  // `default:` and dispatch a SILENT no-op on silicon. The loader already
  // sees every byte (the magic check above): the FIRST byte of each action
  // word carries the opcode in its top OP_W bits, so it is tested as it
  // streams in -- zero run-time cost, nothing behind `cur` -- and an image
  // holding one is refused exactly as a bad magic is: the engine never
  // starts, CONFIG_ERR is reported. A new load (pointer reset) starts clean.
  // N_BUILT_OPS and OP_W are held to test/pe_isa.py by gate_one_encoder.
  localparam integer N_BUILT_OPS = 12;  // 11 -> 12: SHIFTI (primitive 3, bundle 2)
  localparam integer OP_W_T      = 5;
  localparam integer ACT_BASE_T  = MAGIC_AT + 2;
  localparam [AW-1:0] ACT_BASE_A = ACT_BASE_T[AW-1:0];
  localparam [AW-1:0] ACT_MASK_A = ACT_BYTES_T[AW-1:0] - {{(AW-1){1'b0}}, 1'b1};
  reg bad_op;
  always @(posedge clk or negedge rst_n_s) begin
    if (!rst_n_s) begin
      bad_op <= 1'b0;
    end else if (prog_mode & ptr_s) begin
      bad_op <= 1'b0;
    end else if (prog_mode & wr_rise & ~store_full & (ptr >= ACT_BASE_A)
                 & (((ptr - ACT_BASE_A) & ACT_MASK_A) == {AW{1'b0}})
                 & (uio_q1[7 -: OP_W_T] >= N_BUILT_OPS[OP_W_T-1:0])) begin
      bad_op <= 1'b1;
    end
  end
`ifdef M_NO_STORE_FULL
  wire eng_run = run & ~bad_magic & ~bad_op & ~sniff;
`else
  wire eng_run = run & store_full & ~bad_magic & ~bad_op & ~sniff;
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

  wire [ACT_BYTES_T*AW-1:0] e_wraddr_bk;   // step 2: one copy per bank
  wire           e_wre;
  wire [ACT_BYTES_T*8-1:0] s_wrdata;

  // ⭐ step 1b: ONE prog_mode copy PER STORE BANK for the write enable
  wire [ACT_BYTES_T-1:0] pm_we;
  genvar gpw;
  generate
    for (gpw = 0; gpw < ACT_BYTES_T; gpw = gpw + 1) begin : g_pm_we
      pe_dup_ff u_pm_we (.clk(clk), .rst_n(rst_n_s), .d(pm_next), .q(pm_we[gpw]));
    end
  endgenerate

  // ⭐ v2 PIT: SNIFF mode's capture is the store's third write source (the
  // engine never writes it; the loader writes only in load mode)
  wire           pit_run = run & store_full & sniff;
  wire           pit_we;
  wire [AW-1:0]  pit_waddr;
  wire [7:0]     pit_wdata;
  wire           pit_stopped;
  wire           pit_cap_done;
  wire [13:0]    pit_cap_n;
  wire [7:0]     pit_cap_lv0;
  // the clocked bus's second capture (Wilson 11-06): stage 0 configures it
  wire           ck_arm, ck_i2c, ck_act, ck_edge, ck_done;
  wire [2:0]     ck_c, ck_d, ck_f;
  wire [AW-1:0]  ck_wp;
  wire [7:0]     ck_nmsg;
  pe_pit #(.AW(AW)) u_pit (
      .clk(clk), .rst_n(rst_n_s), .run(pit_run), .uio(uio_q1), .mask_cfg(pit_mask), .bud_cfg(pit_bud),
      .we(pit_we), .waddr(pit_waddr), .wdata(pit_wdata), .stopped(pit_stopped),
      .cap_done(pit_cap_done), .cap_n(pit_cap_n), .cap_lv0(pit_cap_lv0),
      .ck_arm(ck_arm), .ck_i2c(ck_i2c), .ck_c(ck_c), .ck_d(ck_d), .ck_f(ck_f), .ck_act(ck_act),
      .ck_edge(ck_edge), .ck_done(ck_done), .ck_wp(ck_wp), .ck_nmsg(ck_nmsg));
  // ⭐ v2 PIT chunk 2: STAGE 0, run once the capture has stopped. It READS the
  // store through the narrow port (the engine is halted in SNIFF, so the
  // select never contends with refill) and writes the role table, 32..38.
  wire           s0_re, s0_we, s0_done;
  wire [AW-1:0]  s0_raddr, s0_waddr;
  wire [7:0]     s0_wdata;
  pe_pit_s0 #(.AW(AW)) u_s0 (
      .clk(clk), .rst_n(rst_n_s), .run(pit_run), .start(pit_cap_done), .n_rec(pit_cap_n),
      .lv0(pit_cap_lv0), .re(s0_re), .raddr(s0_raddr), .rdata(s_rdata),
      .we(s0_we), .waddr(s0_waddr), .wdata(s0_wdata), .done(s0_done),
      .ck_arm(ck_arm), .ck_i2c(ck_i2c), .ck_c(ck_c), .ck_d(ck_d), .ck_f(ck_f), .ck_act(ck_act),
      .ck_edge(ck_edge), .ck_done(ck_done), .ck_wp(ck_wp), .ck_nmsg(ck_nmsg));
  wire _unused_s0 = &{1'b0, s0_done};
  // bundle 5: the USB response buffer's store side, declared ahead of the
  // store (the buffer block below the TX queue drives them)
  reg  [4:0]    ub_wp;
  reg  [3:0]    ub_rp;
  wire [4:0]    ub_wpe;                         // the load index this byte takes
  wire          ub_bwe, ub_bre, ub_bre_go;
  wire [7:0]    ub_in, ub_brd;
  // ⛔⛔ CDC bundle (Wilson 11-10): NO RAW PIN REACHES THE SRAM MACRO. The write
  // strobe and index are registered (ub_bwe / ub_wpe are decided from the raw
  // nibble: the length check, the refusal), and the data is tx_asm, captured
  // on nib_lo -- one cycle of write latency. Checked: model/gate_macro_inputs.py.
  reg           ub_bwe_q;
  reg  [3:0]    ub_bwi_q;
  reg  [7:0]    tx_asm;                         // the half-assembled byte
  pe_store #(.AW(AW), .MEM_TYPE(MEM_TYPE), .WIDE_B(ACT_BYTES_T)) u_store (
      .clk(clk), .rst_n(rst_n_s),
      .we((pm_we & {ACT_BYTES_T{wr_rise}}) | {ACT_BYTES_T{pit_we | s0_we}}),
      .waddr(pit_we ? pit_waddr : s0_we ? s0_waddr : ptr),
      .wdata(pit_we ? pit_wdata : s0_we ? s0_wdata : uio_q1),
      // the SNIFF-only select sits on the ENGINE side of pm_rd's mux: pm_rd's
      // own level is unchanged (sniff is a static mode bit)
      .re(pm_rd ? rb_re : (sniff ? s0_re : e_re)),
      .raddr(pm_rd ? rb_addr : (sniff ? s0_raddr : e_raddr)),
      .rdata(s_rdata),
      .wre(e_wre & run), .wraddr_bk(e_wraddr_bk),
      .wrdata(s_wrdata),
      // M_MACRO_RAW_BWD: the pre-CDC-bundle data path (the raw byte) restored --
      // gate_macro_inputs must go red on A_DIN
`ifdef M_MACRO_RAW_BWD
      .bwe(ub_bwe_q), .bwi(ub_bwi_q), .bwd(ub_in),
`else
      .bwe(ub_bwe_q), .bwi(ub_bwi_q), .bwd(tx_asm),
`endif
      .bre(ub_bre), .bri(ub_rp), .bre_go(ub_bre_go), .brd(ub_brd)
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
  assign cfg_err_any = e_cfg_err | short_load | bad_magic | bad_op;   // M5: one status bit
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
  // (tx_asm, the half-assembled byte, is declared above the store: its low
  // nibble is the response buffer's write data since the CDC bundle)
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
  // ⭐ v2 primitive 3 bundle 5 (Wilson 11-08): while the USB lane is live
  // (`e_usb_on`), queue 3 IS the response buffer -- on both sides: the
  // engine's q = 3 reads the buffer's next line byte, and a host byte tagged 3
  // is written to the buffer instead of the queue. Before that, and in every
  // program without a USB receive, tag 3 is an ordinary TX queue.
  wire          e_usb_on, e_usb_sent, e_usb_clr;
  wire          e_usb_brst, e_usb_acmt;         // bundle 6: bus reset, hardware address commit
  reg           ub_bv;                          // the next line byte is ready
  reg  [7:0]    ub_byte;
`ifdef M_TAG3_ALWAYS_BUF
  wire          ub_sel   = (q_sel == 2'd3);     // the mutant: tag 3 is never a queue
  wire          ub_tag   = (tx_tag == 2'd3);
`else
  wire          ub_sel   = e_usb_on & (q_sel == 2'd3);
  wire          ub_tag   = e_usb_on & (tx_tag == 2'd3);
`endif
  wire          tx_valid = ub_sel ? ub_bv : (tx_cnt[q_sel] != 2'd0);
  wire [7:0]    tx_head  = ub_sel ? ub_byte : tx_mem[{q_sel, tx_rp[q_sel]}];

  // ⭐ THE POP AS A PER-QUEUE VECTOR, so the queue block below is the same
  // for every variant of the TX path (silicon fix #8's (a) pops one queue,
  // the action's; (b4) may pop several) and the benches read one interface.
  wire [3:0] do_popq = (e_host_pop & tx_valid & ~ub_sel) ? (4'b0001 << q_sel) : 4'b0000;

  // ⭐ BUNDLE 6 (Wilson 11-09, step 7a §3a, E2): while the USB lane is live,
  // TX TAG 2 IS THE USB CONTROL CHANNEL -- one-byte records, never queued:
  //     1aaaaaaa  the pending address aaaaaaa (refused while READY or the
  //               reset fence is up)
  //     0x01      the reset acknowledgement: lowers the fence
  //     other     reserved: refused
  // A refusal sets the existing TX-full bit. Before usb_on, and in every
  // program without a USB receive, tag 2 is an ordinary queue (pe_isa refuses
  // a USB image whose actions draw queue 2).
`ifdef M_CTL_AS_QUEUE
  wire ctl_tag = 1'b0;                        // the mutant: the record lands in queue 2
`else
  wire ctl_tag = e_usb_on & (tx_tag == 2'd2);
`endif
  wire nib_lo  = push_rise & tx_half;         // the push that completes a byte
  wire do_push = nib_lo & ~ub_tag & ~ctl_tag & ((tx_cnt[tx_tag] != TXD[1:0]) | do_popq[tx_tag]);

  // =====================================================================
  // ⭐ BUNDLE 5: THE USB RESPONSE BUFFER (Wilson 11-08)
  // =====================================================================
  // The host loads one packet through tag 3: byte 0 is its length in BITS
  // (1..112), then ceil(length/8) bytes of LINE bits (stuffed and NRZI-coded
  // by the RP2040; D- levels, first bit in bit 0). The length is kept here
  // (7 flops); the line bytes go to the SRAM's spare half. READY sets when the
  // last byte lands. While READY is set every tag-3 byte is REFUSED with the
  // existing TX-full bit -- so an unACKed packet cannot be overwritten, and a
  // write landing mid-send (a send needs READY) is refused, never mixed in.
  // A send never touches READY; the program clears it after an ACK
  // (`e_usb_clr`), which also rewinds the load address. A finished send
  // (`e_usb_sent`) rewinds the READ side, so a retransmit sends the same bits.
  reg           ub_ready, ub_pend, ub_on_q;
  reg  [6:0]    ub_len;
  // ⭐ BUNDLE 6 (Wilson 11-09, step 7a §2-§3): the device address, the pending
  // one, the reset fence, the buffer's endpoint and the reset notice.
  //   usb_addr      the address we answer (0 after a bus reset)
  //   usb_apend/pv  the pending address (tag 2), committed in HARDWARE on the
  //                 first ACK-clear of READY (trigger 1) or on a CRC5-valid
  //                 IN/OUT/SETUP token to it (trigger 2, `e_usb_acmt`, which
  //                 also clears READY: the stale ZLP is never sent)
  //   usb_fence     set by a bus reset, lowered by the RP2040's
  //                 acknowledgement (tag 2, 0x01); while up, tag-3 and
  //                 pending-address writes are refused. Correct because the TX
  //                 link is in order: a stale record sent before the
  //                 acknowledgement arrives while the fence is still up. An
  //                 acknowledgement with the fence down changes nothing.
  //   ub_ep         bit 7 of the buffer's length byte: the endpoint it is for
  //   rn_pend       the reset notice (RX kind 5), its own pending flop: never
  //                 dropped behind a busy link; two resets give one notice
  reg  [6:0]    usb_addr, usb_apend;
  reg           usb_apv, usb_fence, ub_ep;
  wire          ctl_byte  = nib_lo & ctl_tag;
  wire          ctl_addr  = ctl_byte & ub_in[7];
  wire          ctl_ack   = ctl_byte & (ub_in == 8'h01);
  wire          ctl_refuse = (ctl_addr & (ub_ready | usb_fence)) |
                             (ctl_byte & ~ub_in[7] & (ub_in != 8'h01));
`ifdef M_ADDR_ACK_ONLY
  wire          acmt      = 1'b0;               // the mutant: trigger 2 never commits
`else
  wire          acmt      = e_usb_acmt;
`endif
`ifdef M_ADDR_EARLY
  wire          commit    = ctl_addr & ~ctl_refuse;   // the mutant: switch on the write itself
`else
  wire          commit    = usb_apv & (e_usb_clr | acmt);
`endif
  always @(posedge clk or negedge rst_n_s) begin
    if (!rst_n_s) begin
      usb_addr <= 7'd0; usb_apend <= 7'd0; usb_apv <= 1'b0;
      usb_fence <= 1'b0;
    end else begin
      if (ctl_addr && !ctl_refuse) begin
        usb_apend <= ub_in[6:0];
        usb_apv   <= 1'b1;
      end
      if (ctl_ack) usb_fence <= 1'b0;
`ifdef M_ADDR_EARLY
      if (commit) begin usb_addr <= ub_in[6:0]; usb_apv <= 1'b0; end
`else
      if (commit) begin usb_addr <= usb_apend; usb_apv <= 1'b0; end
`endif
      if (e_usb_brst) begin
`ifndef M_RST_KEEP_ADDR
        usb_addr  <= 7'd0;
`endif
        usb_apend <= 7'd0;
        usb_apv   <= 1'b0;
`ifndef M_RST_NO_FENCE
        usb_fence <= 1'b1;
`endif
      end
    end
  end
  // ub_wp: bytes taken this load, the length byte included; ub_rp: the next
  // line byte for the engine (both declared above the store)
  assign        ub_in   = {tx_asm[7:4], ui_in[4:1]};     // the byte this push completes
  wire [3:0]    ub_nb   = ub_len[6:3] + {3'd0, |ub_len[2:0]};   // ceil(length / 8)
  // M_CDC_RAW_WR (Wilson 11-10, CDC bundle): ONE capture site qualified by the
  // UNSYNCHRONISED WR pad instead of nib_lo -- gate_cdc_qual must go red
`ifdef M_CDC_RAW_WR
  wire          ub_wbyte  = ui_in[6] & tx_half & ub_tag;
`else
  wire          ub_wbyte  = nib_lo & ub_tag;
`endif
  // bundle 6 (Q5): bit 7 of the length byte is the endpoint, 6:0 the length
  wire          ub_len_ok = (ub_in[6:0] != 7'd0) && (ub_in[6:0] <= 7'd112);
  // bundle 6: and refused while the reset fence is up (addition A).
  // `M_BUF_NO_REFUSE`: a write while READY is not refused -- it starts a new
  // load OVER the unACKed packet (what an unguarded buffer would do)
`ifdef M_BUF_NO_REFUSE
  assign        ub_wpe    = ub_ready ? 5'd0 : ub_wp;
  wire          ub_refuse = usb_fence | ((ub_wpe == 5'd0) & ~ub_len_ok);
`else
  assign        ub_wpe    = ub_wp;
  wire          ub_refuse = ub_ready | usb_fence | ((ub_wp == 5'd0) & ~ub_len_ok);
`endif
  assign        ub_bwe    = ub_wbyte & ~ub_refuse & (ub_wpe != 5'd0);
  // ⛔ CDC bundle: the buffer write lands one cycle after its push (ub_bwe_q),
  // so a read must not meet it -- a 1-byte packet's only byte is written in
  // the cycle READY first allows a read (the SRAM arm already holds bre off
  // on bwe; the flop / latch arms' ubuf has no such order)
  assign        ub_bre    = ub_ready & ~ub_bv & ~ub_pend & (ub_rp < ub_nb) & ~ub_bwe_q;
  wire          ub_pop    = e_host_pop & ub_sel & ub_bv;
  always @(posedge clk or negedge rst_n_s) begin
    if (!rst_n_s) begin
      ub_ready <= 1'b0; ub_pend <= 1'b0; ub_on_q <= 1'b0; ub_bv <= 1'b0;
      ub_len <= 7'd0; ub_wp <= 5'd0; ub_rp <= 4'd0; ub_byte <= 8'h00;
      ub_ep <= 1'b0; ub_bwe_q <= 1'b0; ub_bwi_q <= 4'd0;
    end else begin
      ub_on_q <= e_usb_on;
      ub_bwe_q <= ub_bwe;                          // CDC bundle: registered write
      ub_bwi_q <= ub_wpe[3:0] - 4'd1;
      // M_CDC_UB_UNGATED (Wilson 11-10, CDC bundle): the length register samples
      // the raw nibble pins every cycle -- gate_cdc_qual must go red on ub_len
`ifdef M_CDC_UB_UNGATED
      ub_len <= ub_in[6:0];
`endif
      // load
      if (ub_wbyte && !ub_refuse) begin
        if (ub_wpe == 5'd0) ub_len <= ub_in[6:0];
        if (ub_wpe == 5'd0) ub_ep  <= ub_in[7];
        ub_wp <= ub_wpe + 5'd1;
        if (ub_wpe == 5'd0) ub_ready <= 1'b0;    // (only the mutant writes while READY)
        if (ub_wpe != 5'd0 && ub_wpe[3:0] == ub_nb) begin
          ub_ready <= 1'b1;
          ub_rp    <= 4'd0;
          ub_bv    <= 1'b0;
        end
      end
      // read: one line byte ahead of the engine
      if (ub_bre_go) ub_pend <= 1'b1;
      if (ub_pend) begin
        ub_byte <= ub_brd;
        ub_bv   <= 1'b1;
        ub_pend <= 1'b0;
      end
      if (ub_pop) begin
        ub_bv <= 1'b0;
        ub_rp <= ub_rp + 4'd1;
      end
      // a finished send rewinds the read side (a retransmit resends it)
      if (e_usb_sent) begin
        ub_rp <= 4'd0; ub_bv <= 1'b0; ub_pend <= 1'b0;
      end
      // the program's clear (after an ACK), the lane going live, a reload:
      // the load starts again at the length byte
      // bundle 6: and the hardware address commit on a token to the pending
      // address (the lost-ACK case: the stale ZLP must never go out)
      if (e_usb_clr || (e_usb_on && !ub_on_q) || reload_flush || (usb_apv && acmt)) begin
        ub_ready <= 1'b0; ub_wp <= 5'd0; ub_rp <= 4'd0; ub_bv <= 1'b0; ub_pend <= 1'b0;
      end
      // bundle 6: a bus reset empties the buffer (Default state, §2)
      if (e_usb_brst) begin
`ifndef M_RST_KEEP_READY
        ub_ready <= 1'b0;
`endif
        ub_wp <= 5'd0; ub_rp <= 4'd0; ub_bv <= 1'b0; ub_pend <= 1'b0; ub_ep <= 1'b0;
      end
    end
  end

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
      // ⛔⛔ CDC bundle (Wilson 11-10): the LOW nibble is captured too, on the
      // same synchronised edge, so the response buffer's write data comes from
      // a flop -- no raw pin reaches the SRAM macro's inputs (bwd = tx_asm)
      if (nib_lo) tx_asm[3:0] <= ui_in[4:1];

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
      if (nib_lo && !do_push && !ub_tag && !ctl_tag) tx_full_sticky <= 1'b1;
      if (ub_wbyte && ub_refuse)         tx_full_sticky <= 1'b1;   // bundle 5: refused
      if (ctl_refuse)                    tx_full_sticky <= 1'b1;   // bundle 6: a refused control record
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
      .SDA_HOLD_NS(SDA_HOLD_NS), .CLK_PERIOD_PS(CLK_PERIOD_PS)
  ) u_eng (
      .clk(clk), .rst_n(eng_rst_n), .por_n(rst_n_s), .run(eng_run),
      .s_raddr(e_raddr), .s_re(e_re), .s_rdata(s_rdata),
      .s_wraddr_bk(e_wraddr_bk), .s_wre(e_wre),
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
      .usb_ready(ub_ready), .usb_blen(ub_len),
      .usb_on(e_usb_on), .usb_sent(e_usb_sent), .usb_clr(e_usb_clr),
      .usb_addr(usb_addr), .usb_apend(usb_apend), .usb_apv(usb_apv), .usb_bep(ub_ep),
      .usb_brst(e_usb_brst), .usb_acmt(e_usb_acmt),
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
  // ⭐ bundle 6 (Wilson 11-09, Q2): kind 5 = the USB BUS RESET notice
  // (marker 0, data 0). Kinds 5 and 6 were free; 6 stays free.
  localparam [2:0] KIND_USBRST = 3'd5;
  reg       rn_pend;                    // a reset notice not yet framed
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
      rn_pend <= 1'b0;
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
      // bundle 6: a bus reset raises the notice; it is framed below, after
      // any pending payload. Its own flop, so it is never dropped.
      if (e_usb_brst) rn_pend <= 1'b1;
      if (reload_flush) rn_pend <= 1'b0;
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
        end else if (rn_pend && !e_usb_brst) begin
          // bundle 6: the USB bus reset notice (kind 5)
          ser_sh      <= {1'b0, KIND_USBRST, 8'h00};
          ser_cnt     <= FRAME_LEN;
          rn_pend     <= 1'b0;
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
  assign uio_oe  = pm_pin ? 8'h00 : uio_oe_run;
  assign uio_out = pm_pin ? 8'h00 : e_pin_out[7:0];
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
  wire [3:0] proto_out = pm_pin ? (halt_force | (run_out & ~halt_force))
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

// ---------------------------------------------------------------------------
// ============================================================================
// pe_pit_s0 -- v2 PIT chunk 2: STAGE 0 (multi-wire roles) IN RTL. Bit-exact
// against the frozen model's stage0 (pit_golden.py e55d0b63) run on the capture
// AS STORED (pit_capture_golden.decode: whole records, saturating intervals,
// levels rebuilt from byte 39). Stamped prediction: rulings pit_rtl_c2.ea932f34.
// FULLY SEQUENTIAL (Wilson 10-29): every quantity is a FOLD over one WALK of the
// stored records -- a bit-serial decode of bytes 128.. through the store's
// narrow read port, idle in SNIFF -- and the phases replay stage0 in its exact
// order: the pair loop (c ascending, d ascending, roles mutated in place), the
// FRAME pass (clocks ascending), the AMBIGUOUS rule (FRAME wires in INSERTION
// order, as a Python dict iterates), the rate floor. Medians are exact: a
// binary search on value, one walk per bit, the model's own indices.
// The role table (bytes 32..38): wire w's 7 bits {change level, partner (3),
// role (3)} at bit 7w of a 56-bit word; byte 32 + i = its bits 8i+7 .. 8i.
// ============================================================================
module pe_pit_s0 #(parameter integer AW = 9) (
    input  wire          clk,
    input  wire          rst_n,
    input  wire          run,          // SNIFF running (low: clear, ready for a new capture)
    input  wire          start,        // the capture has stopped and written its status
    input  wire [13:0]   n_rec,        // whole records stored
    input  wire [7:0]    lv0,          // the starting levels (byte 39)
    output wire          re,           // the decoder's reads, or stage 3's (after every walk)
    output wire [AW-1:0] raddr,
    input  wire [7:0]    rdata,
    output wire          we,
    output wire [AW-1:0] waddr,
    output wire [7:0]    wdata,
    output reg           done,
    // the clocked bus's second capture (Wilson 11-06): its configuration to pe_pit
    output reg           ck_arm,
    output reg           ck_i2c,
    output reg  [2:0]    ck_c, ck_d, ck_f,
    output reg           ck_act,
    output reg           ck_edge,
    input  wire          ck_done,
    input  wire [AW-1:0] ck_wp,
    input  wire [7:0]    ck_nmsg
);
  // ---- widths and codes -----------------------------------------------------
  localparam integer TW  = 25;               // t: ~341 records x 0xFFFF
  localparam integer NW  = 9;                // a count of records / edges
  localparam integer IVW = 16;               // a stored interval
  localparam [13:0] N_RAW = 14'd16;
  localparam [2:0] R_NONE = 3'd0, R_CLOCK = 3'd1, R_SYNC = 3'd2, R_FRAME = 3'd3,
                   R_AMBIG = 3'd4, R_CLOCK_I2C = 3'd5, R_SYNC_I2C = 3'd6, R_REFUSED = 3'd7;
  localparam [NW-1:0] MIN_CLOCK_EDGES = 9'd16;   // S0_MIN_CLOCK_EDGES
  localparam [TW-1:0] RATE_FLOOR      = 25'd8;   // S0_RATE_FLOOR
  localparam [AW-1:0] CAP_BASE = 9'd128, TABLE_AT = 9'd32;
  localparam [NW-1:0] ONE = {{(NW-1){1'b0}}, 1'b1};

  // ===========================================================================
  // THE DECODER: one walk = every stored record in order, one bit a cycle.
  // ===========================================================================
  localparam [1:0] D_IDLE = 2'd0, D_REQ = 2'd1, D_LAT = 2'd2, D_BIT = 2'd3;
  localparam [2:0] F_RAW = 3'd0, F_K = 3'd1, F_Q = 3'd2, F_LO = 3'd3, F_ESC = 3'd4, F_MASK = 3'd5;
  reg  [1:0]     ds;
  reg            dload;
  reg  [7:0]     sh;
  reg  [3:0]     nb;
  reg  [2:0]     fs;
  reg  [4:0]     fc;
  reg  [3:0]     kk;
  reg  [IVW-1:0] iv;
  reg  [7:0]     mk;
  reg  [13:0]    r;
  reg  [AW-1:0]  ba;
  reg  [TW-1:0]  t;                     // the record's time (valid with rec_v)
  reg  [7:0]     lv;                    // every wire's level just after it
  reg  [7:0]     rm;                    // its change mask
  reg            rec_v, walk_done, walk_go;
  wire           s12_walk_go, s12_hold, s12_we, s12_done, s12_re;
  wire [AW-1:0]  s12_raddr;
  reg            dre;                   // the decoder's own read (stage 3 reads only after every walk)
  reg  [AW-1:0]  draddr;
  wire           s3_found, s3_fbs;
  wire [7:0]     s3_nmsg;
  wire           ck_req;                // stage 3 found no UART wire: the clocked bus, if any
  reg            ck_fin, ck_ok;         // ... answered: ck_ok = its second capture's messages are in
  reg  [3:0]     ck_why;                // ... else why (golden WHY3 6..10, Wilson 11-06)
  reg            k_seen;                // P_KSEL met a SYNC_DATA wire (6 vs 7)
  assign re    = dre | s12_re;
  assign raddr = s12_re ? s12_raddr : draddr;
  wire [2:0]     s12_w;
  wire [AW-1:0]  s12_waddr;
  wire [7:0]     s12_wdata;
  wire           b    = sh[7];
  wire [7:0]     mk_n = {mk[6:0], b};
  wire [13:0]    r_n  = r + 14'd1;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      ds <= D_IDLE; dload <= 1'b0; sh <= 8'h00; nb <= 4'd0; fs <= F_RAW; fc <= 5'd0; kk <= 4'd0;
      iv <= {IVW{1'b0}}; mk <= 8'h00; r <= 14'd0; ba <= CAP_BASE; t <= {TW{1'b0}}; lv <= 8'h00;
      rm <= 8'h00; rec_v <= 1'b0; walk_done <= 1'b0; dre <= 1'b0; draddr <= {AW{1'b0}};
    end else if (!run) begin
      ds <= D_IDLE; rec_v <= 1'b0; walk_done <= 1'b0; dre <= 1'b0;
    end else begin
      rec_v <= 1'b0; walk_done <= 1'b0; dre <= 1'b0;
      // ⭐ HOLD (Wilson 10-31): stages 1-2 freeze the walk while an interval divides
      // (29 cycles; records are >= 8 apart). Never raised during stage 0, which
      // stays bit-exact (gate pit-s0).
      if (!s12_hold)
      case (ds)
        D_IDLE: if (walk_go | s12_walk_go) begin
          t <= {TW{1'b0}}; lv <= lv0; r <= 14'd0; fs <= F_RAW; fc <= 5'd0; ba <= CAP_BASE;
          if (n_rec == 14'd0) walk_done <= 1'b1;
          else ds <= D_REQ;
        end
        D_REQ: begin dre <= 1'b1; draddr <= ba; ba <= ba + {{(AW-1){1'b0}}, 1'b1}; dload <= 1'b0; ds <= D_LAT; end
        // the store registers rdata on the edge that sees `re`: one cycle to wait
        D_LAT: begin
          if (dload) begin sh <= rdata; nb <= 4'd8; ds <= D_BIT; end
          dload <= 1'b1;
        end
        default: begin   // D_BIT
          sh <= {sh[6:0], 1'b0};
          nb <= nb - 4'd1;
          if (nb == 4'd1) ds <= D_REQ;
          case (fs)
            F_RAW: begin iv <= {iv[IVW-2:0], b}; fc <= fc + 5'd1;
                     if (fc == 5'd15) begin fc <= 5'd0; fs <= F_MASK; end end
            F_K:   begin kk <= {kk[2:0], b}; fc <= fc + 5'd1;
                     if (fc == 5'd3) begin fc <= 5'd0; fs <= F_Q; end end
            F_Q:   if (b) begin
                     fc <= fc + 5'd1;
                     if (fc == 5'd15) begin fc <= 5'd0; fs <= F_ESC; end   // 16 ones: the escape
                   end else begin
                     iv <= {11'd0, fc}; fc <= 5'd0; fs <= (kk == 4'd0) ? F_MASK : F_LO;
                   end
            F_LO:  begin iv <= {iv[IVW-2:0], b}; fc <= fc + 5'd1;
                     if (fc + 5'd1 == {1'b0, kk}) begin fc <= 5'd0; fs <= F_MASK; end end
            F_ESC: begin iv <= {iv[IVW-2:0], b}; fc <= fc + 5'd1;
                     if (fc == 5'd15) begin fc <= 5'd0; fs <= F_MASK; end end
            default: begin   // F_MASK: the record completes on its 8th mask bit
              mk <= mk_n; fc <= fc + 5'd1;
              if (fc == 5'd7) begin
                fc <= 5'd0;
                t <= t + {{(TW-IVW){1'b0}}, iv};
                lv <= lv ^ mk_n; rm <= mk_n; rec_v <= 1'b1; r <= r_n;
                if (r_n == n_rec) begin ds <= D_IDLE; walk_done <= 1'b1; end
                else if (r_n == N_RAW) fs <= F_K;
                else if (r_n < N_RAW) fs <= F_RAW;
                else fs <= F_Q;
              end
            end
          endcase
        end
      endcase
    end
  end

  // ===========================================================================
  // THE FOLDS: one consumer per walk, chosen by `wk`, over wires c / d.
  // ===========================================================================
  // W_S12: stages 1-2's walks -- no stage-0 fold reads them (cnt[] keeps W_CNT's counts)
  localparam [2:0] W_CNT = 3'd0, W_LVL = 3'd1, W_PROBE = 3'd2, W_NEAR = 3'd3, W_PAIR = 3'd4, W_S12 = 3'd5;
  reg  [2:0]    wk;
  reg  [2:0]    wc, wd;
  reg  [1:0]    psel;                  // W_PROBE: 0 / 1 = the level-0 / level-1 intervals, 2 = all
  reg  [NW-1:0] cnt [0:7];             // edges per wire (W_CNT)
  reg           has_c, last_l;         // the walk's previous c edge, and c's level after it
  reg  [TW-1:0] last_t;
  // ⛔ THE FOLD IS PIPELINED (canary 10-30: u_s0.t -> near1, 42 stages, +0.334 ns,
  // the binder). Each record passes two register stages before it is folded:
  // P1 takes the record and the two subtractions against the fold's state
  // (t - last_t, t - pend_x), P2 takes |interval - median|; the fold then reads
  // only registers. Free because records are >= 8 cycles apart (8 mask bits
  // are decoded one per cycle), so the state P1 reads was folded long before;
  // the walk's done signal is delayed to match. Bit-exact: gate pit-s0.
  // ⭐ TRIMMED (lever 3, 10-30): P1 LOADS ONLY ON A RECORD and so holds it
  // until the next (>= 8 cycles) -- the fold reads P1 directly, and only
  // |interval - median| needs a second stage. last_t and pend_x update as the
  // record enters P1 (the next record's P1 is >= 8 cycles later), so no copy
  // of t is kept. 216 pipeline flops -> 91.
  reg           p1_v, p2_v;
  reg  [7:0]    p1_rm, p1_lv;
  reg  [1:0]    p1_dt;                 // the record's own interval, saturated at 2
  reg  [TW-1:0] p1_civ;
  // ⭐ p_aux: ONE register for two walks' values (lever 3, 10-30): in a W_PAIR
  // walk it is t - pend_x (the FRAME pass's right neighbour), loaded as the
  // record enters P1; in every other walk it is |interval - median| (W_NEAR's
  // fold), registered in P2. `wk` is fixed for a whole walk, so they never meet.
  reg  [TW-1:0] p_aux;
  reg           wdone_p1, wdone_p2;
  wire          ce = p1_rm[wc], de = p1_rm[wd];
  wire          cl = p1_lv[wc], dl = p1_lv[wd];
  wire [TW-1:0] civ = p1_civ;          // the interval this record closes on c (valid if has_c)
  reg  [NW-1:0] nlv0, nlv1, near0, near1;
  reg  [TW-1:0] med0, med1;
  // ⭐ half SHARES med0's register (lever 3): the two medians are dead once
  // clock_like's near walk is done, before half is computed for that c, and
  // half is dead before the next c's clock_like overwrites med0.
  wire [TW-1:0] half = med0;
  // the median unit (k-th smallest of the selected intervals, MSB first)
  reg  [TW-1:0] m_ans;
  reg  [4:0]    m_bit;
  reg  [NW-1:0] m_k, pcnt;
  wire [TW-1:0] m_cand = m_ans | ({{(TW-1){1'b0}}, 1'b1} << m_bit);
  // the pair folds
  reg  [NW-1:0] in0, in1, nd, nc;
  reg           idle_ok, frame_ok, all_high;
  reg           pend_i, pend_f;        // d edges waiting for the next c edge (idle / FRAME)
  reg  [TW-1:0] pend_x;                // the latest of them (the closest to that c edge)
  reg           ev_any, ev_prev_start, sig_bad;
  reg  [1:0]    starts;
  reg  [3:0]    g_sat, g_m9;           // SCL falls since the last event: min(g, 10) and g mod 9
  wire [TW+1:0] two_h  = {1'b0, half, 1'b0};
  wire [TW+1:0] four_h = {half, 2'b00};
  wire [TW-1:0] med_l  = last_l ? med1 : med0;
  wire [TW-1:0] dlt    = p_aux;      // |interval - median| (not in a W_PAIR walk)
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      p1_v <= 1'b0; p2_v <= 1'b0; wdone_p1 <= 1'b0; wdone_p2 <= 1'b0;
      p1_rm <= 8'h00; p1_lv <= 8'h00; p1_dt <= 2'd0;
      p1_civ <= {TW{1'b0}}; p_aux <= {TW{1'b0}};
      last_t <= {TW{1'b0}}; pend_x <= {TW{1'b0}};
    end else begin
      p1_v <= rec_v; p2_v <= p1_v; wdone_p1 <= walk_done; wdone_p2 <= wdone_p1;
      if (rec_v) begin
        p1_rm <= rm; p1_lv <= lv;
        p1_dt <= (iv >= 16'd2) ? 2'd2 : iv[1:0];          // the clocked fold's ages (sat 2)
        p1_civ <= t - last_t;
        if (wk == W_PAIR) p_aux <= t - pend_x;
        if (rm[wc]) last_t <= t;                          // the fold's c edge
        if (wk == W_PAIR && rm[wd] && !rm[wc]) pend_x <= t;   // the fold's pending d edge
      end
      if (wk != W_PAIR) p_aux <= (p1_civ > med_l) ? p1_civ - med_l : med_l - p1_civ;
    end
  end
  // a START's gap is bad when < 9 falls, or (Wilson 10-28) not 1 + 9n with n >= 1
`ifdef M_S0_NO_MOD9
  wire          gap_bad = (g_sat < 4'd9);
`else
  wire          gap_bad = (g_sat < 4'd10) | (g_m9 != 4'd1);
`endif
  integer i;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (i = 0; i < 8; i = i + 1) cnt[i] <= {NW{1'b0}};
      has_c <= 1'b0; last_l <= 1'b0;
      nlv0 <= {NW{1'b0}}; nlv1 <= {NW{1'b0}}; near0 <= {NW{1'b0}}; near1 <= {NW{1'b0}};
      pcnt <= {NW{1'b0}};
      in0 <= {NW{1'b0}}; in1 <= {NW{1'b0}}; nd <= {NW{1'b0}}; nc <= {NW{1'b0}};
      idle_ok <= 1'b1; frame_ok <= 1'b1; all_high <= 1'b1;
      pend_i <= 1'b0; pend_f <= 1'b0;
      ev_any <= 1'b0; ev_prev_start <= 1'b0; sig_bad <= 1'b0; starts <= 2'd0;
      g_sat <= 4'd0; g_m9 <= 4'd0;
    end else if (walk_go) begin
      has_c <= 1'b0;
      if (wk == W_CNT) for (i = 0; i < 8; i = i + 1) cnt[i] <= {NW{1'b0}};
      if (wk == W_LVL) begin nlv0 <= {NW{1'b0}}; nlv1 <= {NW{1'b0}}; end
      if (wk == W_NEAR) begin near0 <= {NW{1'b0}}; near1 <= {NW{1'b0}}; end
      pcnt <= {NW{1'b0}};
      in0 <= {NW{1'b0}}; in1 <= {NW{1'b0}}; nd <= {NW{1'b0}}; nc <= {NW{1'b0}};
      idle_ok <= 1'b1; frame_ok <= 1'b1; all_high <= 1'b1; pend_i <= 1'b0; pend_f <= 1'b0;
      ev_any <= 1'b0; ev_prev_start <= 1'b0; sig_bad <= 1'b0; starts <= 2'd0;
      g_sat <= 4'd0; g_m9 <= 4'd0;
    end else if (p2_v) begin
      if (wk == W_CNT)
        for (i = 0; i < 8; i = i + 1) if (p1_rm[i]) cnt[i] <= cnt[i] + ONE;
      // ---- the c wire's own intervals: LVL / PROBE / NEAR ----
      if (ce) begin
        if (has_c) begin
          if (wk == W_LVL) begin
            if (last_l) nlv1 <= nlv1 + ONE; else nlv0 <= nlv0 + ONE;
          end
          if (wk == W_PROBE && (psel == 2'd2 || psel[0] == last_l) && civ < m_cand)
            pcnt <= pcnt + ONE;
          if (wk == W_NEAR && ({dlt, 3'b000} <= {3'b000, med_l})) begin
            if (last_l) near1 <= near1 + ONE; else near0 <= near0 + ONE;
          end
        end
        has_c <= 1'b1; last_l <= cl;          // last_t: set as the record entered P1
      end
      // ---- the pair (c, d): bracket, in_idle_gaps, FRAME pass, I2C, all_high ----
      if (wk == W_PAIR) begin
        if (ce) begin
          nc <= nc + ONE;
          // in_idle_gaps: d edges with a c edge before them (k > 0), closing on
          // this c edge (ce[k], possibly in the same record): its gap vs 2 half
          if (has_c && (pend_i || de) && ({2'b00, civ} <= two_h)) idle_ok <= 1'b0;
          // FRAME pass, the right neighbour: this c edge vs the latest d edge
          if (pend_f && ({2'b00, p_aux} <= four_h)) frame_ok <= 1'b0;   // t - pend_x
          if (de) frame_ok <= 1'b0;            // a c edge AT the d edge: distance 0
          pend_i <= 1'b0; pend_f <= 1'b0;
        end
        if (de) begin
          nd <= nd + ONE;
          if (cl) in1 <= in1 + ONE; else in0 <= in0 + ONE;
          if (!cl) all_high <= 1'b0;
          if (!ce) begin
            pend_i <= has_c; pend_f <= 1'b1;   // pend_x: set as the record entered P1
            // FRAME pass, the left neighbour: the c edge before it (ce[k-1])
            if (has_c && ({2'b00, civ} <= four_h)) frame_ok <= 1'b0;
          end
        end
        // the I2C signature (c = SCL, d = SDA). A fall (c low after) and an
        // event (c high after) cannot share a record, so the order is moot.
        if (ce && !cl) begin
          g_sat <= (g_sat == 4'd10) ? 4'd10 : g_sat + 4'd1;
          g_m9  <= (g_m9 == 4'd8) ? 4'd0 : g_m9 + 4'd1;
        end
        if (de && cl) begin
          if (ev_any && ev_prev_start && gap_bad) sig_bad <= 1'b1;
          if (ev_any && !ev_prev_start && dl) sig_bad <= 1'b1;   // STOP after STOP
          ev_any <= 1'b1; ev_prev_start <= ~dl;
          if (!dl && starts != 2'd3) starts <= starts + 2'd1;
          g_sat <= 4'd0; g_m9 <= 4'd0;
        end
      end
    end
  end

  // ---- THE CLOCKED BUS's folds (golden clocked_bus, Wilson 11-06), in W_PAIR
  // walks on (c = ck_c, d = ck_d) with f = ck_f. Pass 0 (and stage 0's own
  // pair folds): CS high at c's edges (ck_hi, of nc), and the I2C signature.
  // Pass 1: is any COUNTED data edge within 1 cycle of a rise / a fall?
  // Counted: I2C, not START / STOP (c high before and after); SPI, CS active
  // before and after. Ages since the last rise / fall / counted edge, from
  // each record's own interval, saturate at 2: only <= 1 is ever asked.
  reg           ck_pass;
  reg  [NW-1:0] ck_hi;
  reg           ck_dr, ck_df, ck_sn0, ck_sn1;      // dirty rise / fall; counted edges seen in c level 0 / 1
  reg  [1:0]    ck_ar, ck_af, ck_ad;
  reg           ck_vr, ck_vf, ck_vd;
  // THE DESCRIPTOR's CPOL (Wilson 11-06, golden clocked_desc), pass 1: the
  // records where CS goes ACTIVE (ck_cn) and, of them, those with the clock
  // HIGH before the record (ck_ch: cl ^ ce, the level the record left)
  reg  [NW-1:0] ck_cn, ck_ch;
  wire          k_fe = p1_rm[ck_f], k_fl = p1_lv[ck_f];
  wire          k_rise = ce & cl, k_fall = ce & ~cl;
  wire          k_cnt = de & (ck_i2c ? ~(cl & ~ce) : (~k_fe & (k_fl == ck_act)));
  wire [2:0]    k_ar = {1'b0, ck_ar} + {1'b0, p1_dt};
  wire [2:0]    k_af = {1'b0, ck_af} + {1'b0, p1_dt};
  wire [2:0]    k_ad = {1'b0, ck_ad} + {1'b0, p1_dt};
  wire          k_nr = ck_vr & (k_ar <= 3'd1), k_nf = ck_vf & (k_af <= 3'd1), k_nd = ck_vd & (k_ad <= 3'd1);
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      ck_hi <= {NW{1'b0}}; ck_dr <= 1'b0; ck_df <= 1'b0; ck_sn0 <= 1'b0; ck_sn1 <= 1'b0;
      ck_ar <= 2'd0; ck_af <= 2'd0; ck_ad <= 2'd0; ck_vr <= 1'b0; ck_vf <= 1'b0; ck_vd <= 1'b0;
      ck_cn <= {NW{1'b0}}; ck_ch <= {NW{1'b0}};
    end else if (walk_go) begin
      ck_hi <= {NW{1'b0}}; ck_dr <= 1'b0; ck_df <= 1'b0; ck_sn0 <= 1'b0; ck_sn1 <= 1'b0;
      ck_vr <= 1'b0; ck_vf <= 1'b0; ck_vd <= 1'b0;
      ck_cn <= {NW{1'b0}}; ck_ch <= {NW{1'b0}};
    end else if (p2_v && wk == W_PAIR) begin
      if (ce && k_fl) ck_hi <= ck_hi + ONE;
      if (ck_pass) begin
        if (k_cnt && (k_nr || k_rise)) ck_dr <= 1'b1;
        if (k_cnt && (k_nf || k_fall)) ck_df <= 1'b1;
        if (k_rise && k_nd) ck_dr <= 1'b1;
        if (k_fall && k_nd) ck_df <= 1'b1;
        if (k_cnt) begin if (cl) ck_sn1 <= 1'b1; else ck_sn0 <= 1'b1; end
        if (k_fe && k_fl == ck_act) begin
          ck_cn <= ck_cn + ONE;
          if (cl ^ ce) ck_ch <= ck_ch + ONE;
        end
      end
      ck_ar <= k_rise ? 2'd0 : (k_ar[2:1] != 2'd0) ? 2'd2 : k_ar[1:0];
      ck_af <= k_fall ? 2'd0 : (k_af[2:1] != 2'd0) ? 2'd2 : k_af[1:0];
      ck_ad <= k_cnt  ? 2'd0 : (k_ad[2:1] != 2'd0) ? 2'd2 : k_ad[1:0];
      if (k_rise) ck_vr <= 1'b1;
      if (k_fall) ck_vf <= 1'b1;
      if (k_cnt)  ck_vd <= 1'b1;
    end
  end

  // ===========================================================================
  // THE ROLE TABLE + the insertion order the AMBIGUOUS pass walks
  // ===========================================================================
  reg  [2:0] role [0:7];
  reg  [2:0] part [0:7];
  reg        clvl [0:7];
  reg  [2:0] rank [0:7];
  reg  [3:0] nrank;
  wire [7:0] act;
  genvar ga;
  generate
    for (ga = 0; ga < 8; ga = ga + 1) begin : g_act
      assign act[ga] = (cnt[ga] >= {{(NW-2){1'b0}}, 2'd2});
    end
  endgenerate
  wire          c_none  = (role[wc] == R_NONE);
  wire          c_clock = (role[wc] == R_CLOCK) | (role[wc] == R_CLOCK_I2C);
  // stage0's bracket test and its I2C branch, on the folded pair
  wire [NW-1:0] best = (in0 >= in1) ? in0 : in1;
  wire          blvl = ~(in0 >= in1);
  reg           regular;
  wire          brk  = regular && (nd >= 9'd4) && ({best, 3'b000} >= ({nd, 3'b000} - {3'b000, nd}))
                       && ({nd, 4'b0000} <= ({1'b0, nc, 3'b000} + {4'b0000, nc}));
  wire          sig_ok = !sig_bad && (starts >= 2'd2);
  wire          i2c  = sig_ok && (in0 >= 9'd4) && ({in0, 4'b0000} <= ({1'b0, nc, 3'b000} + {4'b0000, nc}));
  reg           sync_of_c;              // a SYNC_DATA of clock c exists (the tie-break)
  reg           ar_hit;
  reg  [2:0]    ar_w;                   // the wire with insertion rank `ar`
  reg  [3:0]    ar;
  reg           refused;
  reg  [2:0]    refuse_w;
  reg  [55:0]   tword;
  integer       j;
  always @(*) begin
    sync_of_c = 1'b0; ar_hit = 1'b0; ar_w = 3'd0; tword = 56'd0;
    for (j = 0; j < 8; j = j + 1) begin
      if ((role[j] == R_SYNC || role[j] == R_SYNC_I2C) && part[j] == wc) sync_of_c = 1'b1;
      if (role[j] != R_NONE && {1'b0, rank[j]} == ar && !ar_hit) begin ar_hit = 1'b1; ar_w = j[2:0]; end
      tword = tword | ({49'd0, (refused ? {1'b0, refuse_w, R_REFUSED} : {clvl[j], part[j], role[j]})} << (7 * j));
    end
  end

  // ===========================================================================
  // STAGES 1-2 (Wilson 10-31): after the table, per role-less active wire
  // ===========================================================================
  wire [7:0]  roled;
  wire [71:0] cnt_flat;
  genvar gs;
  generate
    for (gs = 0; gs < 8; gs = gs + 1) begin : g_s12
      assign roled[gs] = (role[gs] != R_NONE);
      assign cnt_flat[gs*9 +: 9] = cnt[gs];
    end
  endgenerate
  wire           s12_go;               // = (ph == P_S12), assigned after the sequencer's declarations
  pe_pit_s12 #(.AW(AW)) u_s12 (
      .clk(clk), .rst_n(rst_n), .run(run), .go(s12_go),
      .act(act), .roled(roled), .refused(refused), .cnt_flat(cnt_flat),
      .walk_go(s12_walk_go), .hold(s12_hold), .w(s12_w),
      .p1_v(p1_v), .p1_rm(p1_rm), .p1_lv(p1_lv), .p1_civ(p1_civ), .wdone_p1(wdone_p1),
      .we(s12_we), .waddr(s12_waddr), .wdata(s12_wdata), .done(s12_done),
      .re(s12_re), .raddr(s12_raddr), .rdata(rdata),
      .s3_found(s3_found), .s3_fbs(s3_fbs), .s3_nmsg(s3_nmsg),
      .ck_req(ck_req), .ck_fin(ck_fin), .ck_ok(ck_ok), .ck_w(ck_d), .ck_wp(ck_wp), .ck_nmsg(ck_nmsg),
      .ck_why(ck_why));

  // ===========================================================================
  // THE SEQUENCER: stage0's phases, in its order.
  // ===========================================================================
  localparam [4:0] P_IDLE  = 5'd0,  P_CNEXT = 5'd1,  P_CLVL  = 5'd2,  P_CMED0 = 5'd3,
                   P_CMED1 = 5'd4,  P_CNEAR = 5'd5,  P_CHALF = 5'd6,  P_DNEXT = 5'd7,
                   P_DASGN = 5'd8,  P_FCNEXT = 5'd9, P_FHALF = 5'd10, P_FENEXT = 5'd11,
                   P_FASGN = 5'd12, P_ARANK = 5'd13, P_AASGN = 5'd14, P_RNEXT = 5'd15,
                   P_RMED  = 5'd16, P_WRITE = 5'd17, P_DONE = 5'd18,
                   P_MSTART = 5'd19, P_MSTEP = 5'd20, P_WAIT = 5'd21, P_S12 = 5'd22,
                   P_KSEL = 5'd23, P_KC1 = 5'd24, P_KC2 = 5'd25, P_KCAP = 5'd26, P_KFIN = 5'd27;
  reg  [4:0] ph, m_ret, w_ret;          // the median and a walk return to these
  reg            we0;                   // stage 0's own table write
  reg            tbl_done;              // stage 0's table is written (stages 1-2 may still run)
  reg  [AW-1:0]  waddr0;
  reg  [7:0]     wdata0;
  // after the declarations (WSL iverilog: no use before declaration)
  assign s12_go = (ph == P_S12);
  assign we    = we0 | s12_we;
  assign waddr = s12_we ? s12_waddr : waddr0;
  assign wdata = s12_we ? s12_wdata : wdata0;
  reg  [3:0] ci, di;
  reg  [2:0] wbyte;
  // the clocked bus: candidate d = di's wire; its FRAME (CS) = the lowest of its clock's
  reg        k_maybe;                   // no tag, no CS: I2C only if the signature holds
  reg        ck_used;                   // one answer per run
  wire [2:0] k_d  = di[2:0];
  wire       k_dsync = !refused && (role[k_d] == R_SYNC || role[k_d] == R_SYNC_I2C);
  reg        k_hf;
  reg  [2:0] k_fw;
  integer    kj;
  always @(*) begin
    k_hf = 1'b0; k_fw = 3'd0;
    for (kj = 7; kj >= 0; kj = kj - 1)
      if (role[kj] == R_FRAME && part[kj] == part[k_d]) begin k_hf = 1'b1; k_fw = kj[2:0]; end
  end
  // pass 0's CS level: active 1 at >= 7/8 of c's edges high, 0 at >= 7/8 low
  wire [NW+2:0] k_hi8 = {ck_hi, 3'b000}, k_lo8 = {nc - ck_hi, 3'b000}, k_nc7 = {3'b000, nc} * 7;
  // the descriptor (results byte 3): CPOL known / CPOL, >= 7/8 of CS's activations
  wire [NW+2:0] k_ch8 = {ck_ch, 3'b000}, k_cl8 = {ck_cn - ck_ch, 3'b000}, k_cn7 = {3'b000, ck_cn} * 7;
  wire          k_cphi = !ck_i2c && (ck_cn != {NW{1'b0}}) && (k_ch8 >= k_cn7);
  wire          k_cplo = !ck_i2c && (ck_cn != {NW{1'b0}}) && (k_cl8 >= k_cn7);
`ifdef M_CK_CPOL_INV
  wire          k_cpol = !k_cphi && k_cplo;
`else
  wire          k_cpol = k_cphi;
`endif
  wire [7:0]    k_desc = {1'b1, k_cphi | k_cplo, k_cpol, ck_edge, !ck_i2c && ck_act, 3'b000};
  wire          k_cr = !ck_dr, k_cf = !ck_df;
`ifdef M_S0_MED_OFF1
  wire [NW-1:0] m_keff = m_k + ONE;     // the must-fire: every median one index high
`else
  wire [NW-1:0] m_keff = m_k;
`endif
  // ⛔ ITS OWN loop variable: `i` belongs to the counting block above, and an
  // integer written by two processes is 32 conflicting drivers to synthesis
  // (LibreLane's pre-synth check, canary 10-30) though simulation never minds
  integer ri;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      ph <= P_IDLE; m_ret <= P_IDLE; w_ret <= P_IDLE; walk_go <= 1'b0; wk <= W_CNT;
      wc <= 3'd0; wd <= 3'd0; psel <= 2'd0; regular <= 1'b0; ci <= 4'd0; di <= 4'd0; ar <= 4'd0;
      refuse_w <= 3'd0; refused <= 1'b0; wbyte <= 3'd0; done <= 1'b0; tbl_done <= 1'b0;
      med0 <= {TW{1'b0}}; med1 <= {TW{1'b0}};
      m_ans <= {TW{1'b0}}; m_bit <= 5'd0; m_k <= {NW{1'b0}};
      we0 <= 1'b0; waddr0 <= {AW{1'b0}}; wdata0 <= 8'h00; nrank <= 4'd0;
      ck_arm <= 1'b0; ck_i2c <= 1'b0; ck_c <= 3'd0; ck_d <= 3'd0; ck_f <= 3'd0; ck_act <= 1'b0;
      ck_edge <= 1'b0; ck_pass <= 1'b0; ck_fin <= 1'b0; ck_ok <= 1'b0; ck_used <= 1'b0; k_maybe <= 1'b0;
      ck_why <= 4'd0; k_seen <= 1'b0;
      for (ri = 0; ri < 8; ri = ri + 1) begin role[ri] <= R_NONE; part[ri] <= 3'd0; clvl[ri] <= 1'b0; rank[ri] <= 3'd0; end
    end else if (!run) begin
      ph <= P_IDLE; walk_go <= 1'b0; we0 <= 1'b0; done <= 1'b0; tbl_done <= 1'b0; refused <= 1'b0; nrank <= 4'd0;
      ck_arm <= 1'b0; ck_fin <= 1'b0; ck_ok <= 1'b0; ck_used <= 1'b0;
      for (ri = 0; ri < 8; ri = ri + 1) begin role[ri] <= R_NONE; part[ri] <= 3'd0; clvl[ri] <= 1'b0; rank[ri] <= 3'd0; end
    end else begin
      walk_go <= 1'b0;
      we0 <= 1'b0;
      ck_arm <= 1'b0; ck_fin <= 1'b0;
      case (ph)
        P_IDLE: if (start && !done) begin
                  wk <= W_CNT; walk_go <= 1'b1; ph <= P_WAIT; w_ret <= P_CNEXT; ci <= 4'd0;
                end
        // a walk is running: wait for its last record
        P_WAIT: if (wdone_p2) ph <= w_ret;
        // ---- the exact median (k = m_k): one probe walk per bit ----
        P_MSTART: begin wk <= W_PROBE; walk_go <= 1'b1; ph <= P_WAIT; w_ret <= P_MSTEP; end
        P_MSTEP: begin
                   if (pcnt <= m_keff) m_ans <= m_cand;    // fewer than k + 1 below: the bit is set
                   if (m_bit == 5'd0) ph <= m_ret;
                   else begin m_bit <= m_bit - 5'd1; ph <= P_MSTART; end
                 end
        // ---- the pair loop: c ascending ----
        P_CNEXT: if (ci == 4'd8) begin ph <= P_FCNEXT; ci <= 4'd0; end
                 else if (act[ci[2:0]] && cnt[ci[2:0]] >= MIN_CLOCK_EDGES
                          && (role[ci[2:0]] == R_NONE || role[ci[2:0]] == R_CLOCK || role[ci[2:0]] == R_CLOCK_I2C)) begin
                   wc <= ci[2:0]; wk <= W_LVL; walk_go <= 1'b1; ph <= P_WAIT; w_ret <= P_CLVL;
                 end else ci <= ci + 4'd1;
        // clock_like: each level needs >= 4 intervals, then its median and near count
        P_CLVL: if (nlv0 < 9'd4 || nlv1 < 9'd4) begin regular <= 1'b0; ph <= P_CHALF; end
                else begin
                  psel <= 2'd0; m_k <= nlv0 >> 1; m_ans <= {TW{1'b0}}; m_bit <= 5'd24;
                  ph <= P_MSTART; m_ret <= P_CMED0;
                end
        P_CMED0: begin
                   med0 <= m_ans;
                   psel <= 2'd1; m_k <= nlv1 >> 1; m_ans <= {TW{1'b0}}; m_bit <= 5'd24;
                   ph <= P_MSTART; m_ret <= P_CMED1;
                 end
        P_CMED1: begin med1 <= m_ans; wk <= W_NEAR; walk_go <= 1'b1; ph <= P_WAIT; w_ret <= P_CNEAR; end
        P_CNEAR: begin
                   regular <= ({near0, 2'b00} >= ({nlv0, 1'b0} + {1'b0, nlv0}))
                            && ({near1, 2'b00} >= ({nlv1, 1'b0} + {1'b0, nlv1}));
                   ph <= P_CHALF;
                 end
        // half = sorted(every c interval)[len(ce) // 2]
        P_CHALF: begin
                   psel <= 2'd2; m_k <= cnt[wc] >> 1; m_ans <= {TW{1'b0}}; m_bit <= 5'd24;
                   ph <= P_MSTART; m_ret <= P_DNEXT; di <= 4'd0;
                 end
        P_DNEXT: begin
                   if (m_ret == P_DNEXT) begin med0 <= m_ans; m_ret <= P_IDLE; end   // = half
                   if (di == 4'd8) begin ci <= ci + 4'd1; ph <= P_CNEXT; end
                   else begin
`ifdef M_S0_PAIR_ORDER
                     wd <= 3'd7 - di[2:0];            // the must-fire: d descending
`else
                     wd <= di[2:0];
`endif
                     ph <= P_DASGN; w_ret <= P_IDLE;
                   end
                 end
        P_DASGN: begin
                   // stage0's skip: d == c, d inactive, c holding a non-CLOCK role, d holding any
                   if (w_ret == P_IDLE) begin
                     if (wd == wc || !act[wd] || (!c_none && !c_clock) || role[wd] != R_NONE) begin
                       di <= di + 4'd1; ph <= P_DNEXT;
                     end else begin
                       wk <= W_PAIR; walk_go <= 1'b1; ph <= P_WAIT; w_ret <= P_DASGN;
                     end
                   end else begin
                     w_ret <= P_IDLE;
                     if (brk || i2c) begin
                       // insertion order: c (setdefault) first, then d
                       if (c_none) begin rank[wc] <= nrank[2:0]; rank[wd] <= nrank[2:0] + 3'd1; nrank <= nrank + 4'd2; end
                       else begin rank[wd] <= nrank[2:0]; nrank <= nrank + 4'd1; end
                       part[wd] <= wc;
                       if (brk) begin
                         if (c_none) role[wc] <= R_CLOCK;
                         if (idle_ok) begin role[wd] <= R_FRAME; clvl[wd] <= 1'b0; end
                         else begin role[wd] <= R_SYNC; clvl[wd] <= blvl; end
                       end else begin   // the I2C branch: c's bus becomes I2C
                         role[wc] <= R_CLOCK_I2C;
                         role[wd] <= R_SYNC_I2C; clvl[wd] <= 1'b0;
                       end
                     end
                     di <= di + 4'd1; ph <= P_DNEXT;
                   end
                 end
        // ---- the FRAME pass: clocks ascending, role-less active e ascending ----
        P_FCNEXT: if (ci == 4'd8) begin ph <= P_ARANK; ar <= 4'd0; end
                  else if (role[ci[2:0]] == R_CLOCK || role[ci[2:0]] == R_CLOCK_I2C) begin
                    wc <= ci[2:0]; psel <= 2'd2; m_k <= cnt[ci[2:0]] >> 1; m_ans <= {TW{1'b0}};
                    m_bit <= 5'd24; ph <= P_MSTART; m_ret <= P_FHALF;
                  end else ci <= ci + 4'd1;
        P_FHALF: begin med0 <= m_ans; di <= 4'd0; ph <= P_FENEXT; end   // = half
        P_FENEXT: if (di == 4'd8) begin ci <= ci + 4'd1; ph <= P_FCNEXT; end
                  else if (!act[di[2:0]] || role[di[2:0]] != R_NONE) di <= di + 4'd1;
                  else begin wd <= di[2:0]; wk <= W_PAIR; walk_go <= 1'b1; ph <= P_WAIT; w_ret <= P_FASGN; end
        P_FASGN: begin
                   if (frame_ok) begin
                     role[wd] <= R_FRAME; part[wd] <= wc; clvl[wd] <= 1'b0;
                     rank[wd] <= nrank[2:0]; nrank <= nrank + 4'd1;
                   end
                   di <= di + 4'd1; ph <= P_FENEXT;
                 end
        // ---- the AMBIGUOUS rule: FRAME wires in insertion order ----
        P_ARANK:
`ifdef M_S0_NO_AMBIG
                 begin ph <= P_RNEXT; ci <= 4'd0; end
`else
                 if (ar == 4'd8) begin ph <= P_RNEXT; ci <= 4'd0; end
                 else if (!ar_hit || role[ar_w] != R_FRAME) ar <= ar + 4'd1;
                 else begin wd <= ar_w; wc <= part[ar_w]; ph <= P_AASGN; w_ret <= P_IDLE; end
`endif
        P_AASGN: begin
                   if (w_ret == P_IDLE) begin
                     // the tie-break reads the CURRENT table, as stage0's roles.values()
                     if (sync_of_c) begin ar <= ar + 4'd1; ph <= P_ARANK; end
                     else begin wk <= W_PAIR; walk_go <= 1'b1; ph <= P_WAIT; w_ret <= P_AASGN; end
                   end else begin
                     w_ret <= P_IDLE;
                     if (all_high && sig_ok) begin
                       role[wc] <= R_AMBIG; part[wc] <= wd; clvl[wc] <= 1'b0;
                       role[wd] <= R_AMBIG; part[wd] <= wc; clvl[wd] <= 1'b0;
                     end
                     ar <= ar + 4'd1; ph <= P_ARANK;
                   end
                 end
        // ---- the rate floor: role-less active wires, ascending ----
        P_RNEXT: if (ci == 4'd8) begin ph <= P_WRITE; wbyte <= 3'd0; end
                 else if (!act[ci[2:0]] || role[ci[2:0]] != R_NONE) ci <= ci + 4'd1;
                 else begin   // sorted(intervals)[(len(ee) - 1) // 2] < 8: the bus is refused
                   wc <= ci[2:0]; psel <= 2'd2; m_k <= (cnt[ci[2:0]] - ONE) >> 1;
                   m_ans <= {TW{1'b0}}; m_bit <= 5'd24; ph <= P_MSTART; m_ret <= P_RMED;
                 end
        P_RMED: begin
`ifdef M_S0_NO_FLOOR
                  if (1'b0) begin
`else
                  if (m_ans < RATE_FLOOR) begin
`endif
                    refused <= 1'b1; refuse_w <= ci[2:0]; ph <= P_WRITE; wbyte <= 3'd0;
                  end else begin ci <= ci + 4'd1; ph <= P_RNEXT; end
                end
        // ---- write the table, bytes 32..38 ----
        P_WRITE: begin
                   we0 <= 1'b1; waddr0 <= TABLE_AT + {{(AW-3){1'b0}}, wbyte};
                   wdata0 <= tword[{wbyte, 3'b000} +: 8];
                   // ⭐ then stages 1-2 (Wilson 10-31), on this decoder, over the role-less wires
                   if (wbyte == 3'd6) begin ph <= P_S12; wk <= W_S12; end else wbyte <= wbyte + 3'd1;
                 end
        // stages 1-2 read wire s12_w's intervals off this fold (`wc`)
        P_S12:  begin
                  tbl_done <= 1'b1; wc <= s12_w;
                  if (s12_done) ph <= P_DONE;
                  else if (ck_req && !ck_used) begin
                    di <= 4'd0; ck_ok <= 1'b0; ck_why <= 4'd0; k_seen <= 1'b0; ph <= P_KSEL;
                  end
                end
        // ---- stage 3 on a clocked bus (golden clocked_bus, Wilson 11-06) ----
        // the first SYNC_DATA wire with frame markers: I2C's tag, a CS (FRAME) of
        // its clock, or (neither) the I2C signature, from pass 0
        P_KSEL: if (di == 4'd8) begin                              // none: no clocked record
`ifdef M_CK_WHY_SWAP
                  ck_why <= k_seen ? 4'd6 : 4'd7;
`else
                  ck_why <= k_seen ? 4'd7 : 4'd6;                   // no frame markers / no data wire
`endif
                  ph <= P_KFIN;
                end
                else if (!k_dsync) di <= di + 4'd1;
                else begin
                  k_seen <= 1'b1;
                  ck_d <= k_d; ck_c <= part[k_d]; ck_f <= k_fw;
                  ck_i2c <= (role[k_d] == R_SYNC_I2C) || !k_hf;
                  k_maybe <= (role[k_d] != R_SYNC_I2C) && !k_hf;
                  wk <= W_PAIR; wc <= part[k_d]; wd <= k_d; ck_pass <= 1'b0;
                  walk_go <= 1'b1; ph <= P_WAIT; w_ret <= P_KC1;
                end
        P_KC1:  if (k_maybe && !sig_ok) begin di <= di + 4'd1; ph <= P_KSEL; end
                else begin
                  k_maybe <= 1'b0;
                  if (!ck_i2c && k_hi8 >= k_nc7) ck_act <= 1'b1;
                  else if (!ck_i2c && k_lo8 >= k_nc7) ck_act <= 1'b0;
                  if (!ck_i2c && k_hi8 < k_nc7 && k_lo8 < k_nc7) begin    // CS level unclear
                    ck_why <= 4'd8; ph <= P_KFIN;
                  end
                  else begin ck_pass <= 1'b1; walk_go <= 1'b1; ph <= P_WAIT; w_ret <= P_KC2; end
                end
        // the sample edge: the clean one; both clean -> the edge ending the data's level
        P_KC2:  begin
                  ph <= P_KCAP; ck_arm <= 1'b1;
                  if (k_cr && !k_cf) ck_edge <= 1'b1;
                  else if (k_cf && !k_cr) ck_edge <= 1'b0;
`ifdef M_CK_NO_REFUSE
                  else ck_edge <= ck_sn0;
`else
                  else if (k_cr && k_cf && (ck_sn0 ^ ck_sn1)) ck_edge <= ck_sn0;
                  else begin                                       // no clean sample edge:
                    ph <= P_KFIN; ck_arm <= 1'b0;                  // both clean = data in both levels
                    ck_why <= (k_cr && k_cf) ? 4'd10 : 4'd9;
                  end
`endif
                end
        P_KCAP: if (ck_done) begin ck_ok <= 1'b1; ph <= P_KFIN; end
        P_KFIN: begin
                  ck_fin <= 1'b1; ck_used <= 1'b1; wk <= W_S12; ph <= P_S12;
                  // the clocked-bus descriptor (golden clocked_desc), once its capture is in
                  if (ck_ok) begin we0 <= 1'b1; waddr0 <= 9'd3; wdata0 <= k_desc; end
                end
        P_DONE: done <= 1'b1;
        default: ph <= P_IDLE;
      endcase
    end
  end
endmodule

// ===========================================================================
// pe_pit_s12 -- PIT STAGES 1-2 (Wilson 10-31, Track 3): per role-less active
// wire, model/pit_golden.py's stage1 (the hypothesis bank, both refines, the
// phase) and stage2 (the encoding class, its condition and the R2 guard), as
// classify_bus runs them. Bit-exact target: the frozen golden (f19f2177 LF).
// It runs AFTER stage 0 has written its table, on stage 0's own decoder walk
// (one walk per pass; nothing per-interval or per-candidate is stored -- a
// value needed twice is recomputed by another walk), and it writes one 10-byte
// record per wire at 40 + 10w (Wilson 10-31: bytes 40..119):
//   b0 {cls[2:0], why[2:0], cond, wh}   b1 {idle, p16[18:16], fb[12:9]}
//   b2 p16[15:8]  b3 p16[7:0]  b4 {fb[8], phase[14:8]}  b5 phase[7:0]
//   b6 score (sat 255)  b7 n (sat 255)  b8 frames (sat 255)  b9 fb[7:0]
// cls: 0 inactive, 1 CLOCK, 2 MANCHESTER, 3 NRZ_ASYNC, 4 NRZI_STUFFED,
//      5 LEVEL_CODE, 6 UNKNOWN, 7 a stage-0 role (see bytes 32..38)
// why (UNKNOWN): 1 < 16 intervals, 2 no candidate reaches 7/8, 3 a
//      non-harmonic rival, 4 no non-idle runs, 5 clock-shaped but irregular,
//      6 stage 0 refused the bus, 7 withheld by R2 (wh: 0 MANCHESTER, 1 NRZ_ASYNC)
// cond: the (b) condition -- "every wire of the bus is on the sniffed pins".
// ⭐ ONE divider, no multiplier: m = round(I/P) is q or q+1, so |I - mP| is the
//   remainder or P minus it. ⭐ ONE accumulator for every pass (measured lever).
// ===========================================================================
module pe_pit_s12 #(parameter integer AW = 9) (
    input  wire          clk,
    input  wire          rst_n,
    input  wire          run,
    input  wire          go,           // stage 0 has written its table
    input  wire [7:0]    act,          // >= 2 edges (stage 0's W_CNT)
    input  wire [7:0]    roled,        // stage 0 gave the wire a role
    input  wire          refused,      // stage 0 refused the bus
    input  wire [71:0]   cnt_flat,     // edges per wire, 8 x 9 bits
    output reg           walk_go,      // a walk of stage 0's decoder
    output reg           hold,         // freeze the decoder: an interval is in flight
    output reg  [2:0]    w,            // the wire: stage 0 points its fold's `wc` at it
    // cut 1 (Wilson's budget, 10-31): STAGE 0'S OWN FOLD gives the interval --
    // its P1 stage holds the record and `t - last_t` of wire wc until the next
    // record, which `hold` keeps from coming. No second subtractor, no copy of t.
    input  wire          p1_v,         // a record entered P1 this cycle
    input  wire [7:0]    p1_rm,
    input  wire [7:0]    p1_lv,
    input  wire [24:0]   p1_civ,       // t - (wire wc's previous edge)
    input  wire          wdone_p1,     // the walk's last record is in P1
    output reg           we,
    output reg  [AW-1:0] waddr,
    output reg  [7:0]    wdata,
    output reg           done,
    // stage 3 (Wilson 11-05): its reads of stage 2's records and of the decoded
    // messages, through stage 0's read port (idle once its walks are done)
    output reg           re,
    output wire [AW-1:0] raddr,
    input  wire [7:0]    rdata,
    output reg           s3_found,     // an NRZ_ASYNC wire exists
    output reg           s3_fbs,       // ... with frame_bits < 9: UNKNOWN, not decoded
    output reg  [7:0]    s3_nmsg,      // messages decoded (sat 255)
    // no NRZ_ASYNC wire: ask stage 0 for the clocked bus's second capture (Wilson 11-06)
    output wire          ck_req,
    input  wire          ck_fin,       // answered; ck_ok = messages in, from data wire ck_w
    input  wire          ck_ok,
    input  wire [2:0]    ck_w,
    input  wire [AW-1:0] ck_wp,        // their end
    input  wire [7:0]    ck_nmsg,
    input  wire [3:0]    ck_why        // its refusal's reason code (golden WHY3)
);
  localparam [15:0] OVF     = 16'hFFFF;
  localparam [14:0] P_FIRST = 15'd4, P_LAST = 15'd16384;
  localparam [3:0]  IDLE_M  = 4'd15;
  localparam [2:0]  C_NONE = 3'd0, C_CLOCK = 3'd1, C_MANCH = 3'd2, C_ASYNC = 3'd3, C_NRZI = 3'd4,
                    C_LEVEL = 3'd5, C_UNK = 3'd6, C_ROLE = 3'd7;

  // ---------------- the shared divider: 29 / 23 bits, restoring, 29 cycles ------
  reg  [28:0] dv_q;                 // dividend in, quotient out
  reg  [23:0] dv_r;                 // remainder
  reg  [22:0] dv_d;                 // divisor
  reg  [4:0]  dv_n;
  reg         dv_busy;
  wire [23:0] dv_try = {dv_r[22:0], dv_q[28]} - {1'b0, dv_d};
  // round(dividend / divisor) and its distance, from the quotient and remainder
  wire        rnd_c  = ({dv_r[22:0], 1'b0} >= {1'b0, dv_d});
  wire [22:0] err_c  = rnd_c ? (dv_d - dv_r[22:0]) : dv_r[22:0];
  wire [28:0] m_r_c  = dv_q + {28'd0, rnd_c};
  // THE DIVIDER'S TAIL REGISTER (Wilson 11-07, the slow corner): the round / distance / hit chain above ran on
  // through stage 1's harmonic test and stage 2's steps into p / acc in the same cycle. Its results are
  // registered every cycle; a divide holds dv_busy one cycle past its last step, so every reader (all wait
  // on !dv_busy) sees the registered values of the finished divide.
  reg  [22:0] err;
  reg  [28:0] m_r;
  reg         hit;
  reg  [4:0]  m16;                  // a run in bit periods (> 15 = idle)
  always @(posedge clk or negedge rst_n)
    if (!rst_n) begin err <= 23'd0; m_r <= 29'd0; hit <= 1'b0; m16 <= 5'd0; end
    else begin
      err <= err_c; m_r <= m_r_c;
      hit <= (m_r_c != 29'd0) && ({err_c, 3'b000} <= {3'b000, dv_d});
      m16 <= (m_r_c > 29'd15) ? 5'd16 : {1'b0, m_r_c[3:0]};
    end

  // ---------------- control ---------------------------------------------------------
  localparam [4:0] S_IDLE = 5'd0,  S_WIRE = 5'd1,  S_PRE = 5'd2,  S_BANK = 5'd3,  S_RIVAL = 5'd4,
                   S_HARM = 5'd5,  S_RB = 5'd6,    S_REF1 = 5'd7, S_REF2 = 5'd8,  S_REF2D = 5'd9,
                   S_PHASE = 5'd10, S_ST2 = 5'd11, S_ASYNC = 5'd12, S_SPAN = 5'd13, S_CLASS = 5'd14,
                   S_WR = 5'd15,   S_NEXT = 5'd16, S_S3 = 5'd17;
  reg  [4:0]  st;
  reg  [14:0] p;
  wire [14:0] p_step = (p[14:5] == 10'd0) ? 15'd1 : {5'd0, p[14:5]};
  wire [15:0] p_next = {1'b0, p} + {1'b0, p_step};
  wire        p_end  = (p_next > {1'b0, P_LAST});

  // the walk: one wire's intervals, one in flight at a time
  reg         has_prev, last_l, wend;
  reg         x_v, x_lvl;
  reg  [1:0]  x_ph;                 // 0 new, 1 dividing, 2 stepping (ASYNC)
  // the interval in flight, saturated (golden wire_ivs: min(t - prev, OVF)).
  // P1 holds it: `hold` keeps the next record out
  wire [15:0] x_iv = (p1_civ > {9'd0, OVF}) ? OVF : p1_civ[15:0];

  // stage 1
  reg  [8:0]  n, n1;                // non-OVF intervals, and those at level 1
  reg         idle_lvl;
  wire [8:0]  n_act = idle_lvl ? (n - n1) : n1;
  wire [8:0]  n_idl = idle_lvl ? n1 : (n - n1);
  reg  [14:0] bp;
  reg  [8:0]  bh;
  reg         bq, rival, s1ok;          // s1ok: stage 1 returned OK (P_hat, phase, score are claims)
  // cut 2: the harmonic test's larger period, from P and P_best (both stable)
  wire [14:0] rv_hi = (p > bp) ? p : bp;
  reg  [18:0] p16;
  // ⭐ ONE accumulator for every pass (Wilson 10-31, measured lever 3):
  //   stage 1:  HA [8:0]  HI [17:9]  H [26:18]  SI [51:27]  SM [74:52]
  //   stage 2:  BODY [8:0]  IDLE [17:9]  LE0 [26:18]  LE1 [35:27]  N0 [44:36]  N1 [53:45]
  //             ILV [55:54]  BLV [57:56]  M1 58  M2 59  MO 60  M7 61  MMAX [65:62]
  //   ASYNC:    FR [8:0]  FJ [12:9]  INFR 13  ABAD 14  RUN [19:15]
  //   SPAN:     CUR [21:9]  MAX [34:22]  NSP [43:35]
  //   PRE:      IVMAX [15:0] (cut 3: the longest interval, free before the bank)
  //   PHASE:    PH [58:44]  PHDONE 59 (cut 7: the phase from a closing walk -- the
  //             first interval again, divided by the FINAL P_hat; no t0, no phase register)
  reg  [74:0] acc;
  wire        qual   = (acc[8:0] >= n_act - {3'd0, n_act[8:3]}) && ({acc[17:9], 1'b0} >= {1'b0, n_idl});
  // stage 2's tests, reduced to flags as its walk ends (frees the accumulator)
  reg         f_clock, f_manch, f_nrzi, f_irreg, f_atry, f_body, a_idle;
  // ASYNC: the frame length under test, and the one found
  reg  [3:0]  L, a_L;
  // the record. cut 4: frame bits and frames are READ from the accumulator as
  // the record is written (SPAN's result stays there until the next wire)
  reg  [2:0]  cls, why;
  reg         cond, wh, f_span;
  reg  [3:0]  wb;
  wire [12:0] fb     = (cls != C_ASYNC) ? 13'd0 : f_span ? acc[34:22] + 13'd1 : {9'd0, a_L};
  wire [7:0]  frames = (cls != C_ASYNC || !f_span) ? 8'd0 : (acc[43:35] > 9'd255) ? 8'd255 : acc[42:35];   // v1-literal-ok: an 8-bit saturation clamp, not a store address

  wire [8:0]  cnt_w [0:7];
  genvar gi;
  generate for (gi = 0; gi < 8; gi = gi + 1) begin : g_cnt
    assign cnt_w[gi] = cnt_flat[gi*9 +: 9];
  end endgenerate
  // R2: another active wire with at least as many edges as this wire has intervals
  reg r2_hit;
  integer j;
  always @(*) begin
    r2_hit = 1'b0;
    for (j = 0; j < 8; j = j + 1)
      if (j[2:0] != w && act[j] && cnt_w[j] >= cnt_w[w] - 9'd1) r2_hit = 1'b1;
  end
  wire [7:0] sc8 = (bh > 9'd255) ? 8'd255 : bh[7:0];   // v1-literal-ok: an 8-bit saturation clamp, not a store address
  wire [7:0] n8  = (n  > 9'd255) ? 8'd255 : n[7:0];   // v1-literal-ok: an 8-bit saturation clamp, not a store address


  // ===========================================================================
  // STAGE 3, PIECE 1 (Wilson 11-05): the decode walk -- golden async_bytes on
  // the first NRZ_ASYNC wire, its messages written BEHIND the read pointer from
  // byte 128 as [length][bytes...] (frame_bits >= 9 keeps the decode moving
  // forward; each decoded byte costs >= 2 records of >= 9 bits). ONE 26-bit ALU
  // (its borrow is every compare), a few cycles a step, and every wide value in
  // a register stages 1-2 are done with (their records are written):
  // ===========================================================================
`define S3_X     acc[24:0]                  // the scan point; the byte's start s while sampling
`define S3_LQ    acc[49:25]                 // le + p16 + p16/4 (the gap test); the sample point while sampling
`define S3_P30   acc[29:0]                  // the fl product {LQ[4:0], X}, before the decode
`define S3_SA    acc[72:50]                 // (2b + 3) p16 (< 17 x 2^18)
`define S3_FB    acc[62:50]                 // frame_bits, before the multiply
`define S3_OPEN  acc[73]                    // a message is open
`define S3_MBYTE acc[74]                    // sampling a byte (else scanning)
`define S3_E     dv_q[24:0]                 // the current interval's end
`define S3_TOT   {dv_q[25], dv_r[23:0]}     // the total time (< 341 x 0xFFFF < 2^25)
`define S3_FL    {dv_q[28:26], dv_d[21:0]}  // (fb p16) >> 4, all ones if >= 2^25
`define S3_CLEN  {dv_d[22], bp}             // the current interval's length; the pre-pass maximum
`define S3_BY    bh[7:0]
`define S3_MLEN  n[7:0]
`define S3_WP    p[8:0]
`define S3_LA    n1
`define S3_BI    L[2:0]
`define S3_HLE   a_L[0]                     // last_end exists (the multiply's sticky overflow before)
`define S3_CUR   a_L[1]                     // an interval is current
`define S3_L     a_L[2]                     // its level
`define S3_IDLE  a_L[3]                     // the idle level
  localparam [6:0] T_RD = 7'd0, T_RW = 7'd1, T_RV = 7'd2, T_MUL = 7'd3, T_PRE = 7'd4, T_PRE1 = 7'd5,
                   T_CHK = 7'd6, T_LOC = 7'd7, T_ADV = 7'd8, T_STEP = 7'd9, T_FOUND = 7'd10,
                   T_SPL = 7'd11, T_SA0 = 7'd12, T_MID = 7'd13, T_MLOC = 7'd14, T_SAI = 7'd15,
                   T_XE = 7'd16, T_LQ1 = 7'd17, T_LQ2 = 7'd18, T_END = 7'd19, T_DRAIN = 7'd20,
                   T_DONE = 7'd21, T_CK = 7'd115;
  localparam [12:0] S3_MIN_FB = 13'd9;      // start + 8 data bits (Wilson 11-05)
  localparam [AW-1:0] S3_CAP = 9'd128;
  reg  [6:0]  t3;
  // THE REASON CODE (Wilson 11-06; golden WHY3): why the record has no
  // polynomial or no init, written in byte 128's low nibble when init is not.
  // g_try / g_skip: a group of >= 2 frames fit the store / was too big for it
  // (golden: "insufficient store" = skipped and none tried)
  reg  [3:0]  s3_why;
  reg         g_try, g_skip;
  // the benches' snapshot point: the record's last write is about to start
  // (option (a): the messages are checked from a dump taken here)
  wire        s3_rec_wr = (st == S_S3) && (t3 == 7'd112);
  assign      ck_req = (st == S_S3) && (t3 == T_CK);
  wire        t3_walk = (st == S_S3) && (t3 >= T_PRE) && (t3 <= T_DRAIN);
  wire        exh = wend & ~x_v & ~walk_go;      // no interval will come (not the last walk's wend)
  // ===========================================================================
  // STAGE 3, PIECE 2 (Wilson 11-05): the GCD -- golden crc_poly_gcd_s3_fit,
  // bit for bit. Per length group (first-appearance order, >= 4 frames, and
  // 2 L <= 512 - end of messages), per bit order: the differences m_a ^ m_0 into
  // two L-byte buffers after the messages, polynomials RIGHT-ALIGNED (constant
  // term = bit 0 of the last byte), and the BINARY gcd on odd parts (over GF(2)
  // odd(gcd(d...)) = gcd(odd(d)...), which is what the golden keeps): swap so
  // deg x >= deg y, x ^= y, shift x right by its trailing zeros, until x = 0.
  // The best candidate lives in the record (120..127) and the golden's order is
  // a key: more differences, then bit order MSB-first, then the larger group,
  // then the earlier (= the one found first). Every value in an idle register.
  // ===========================================================================
`define G_RA     acc[8:0]                   // the read address
`define G_DX     acc[19:9]                  // deg x (the buffer being reduced)
`define G_DY     acc[30:20]                 // deg y (= g between differences)
`define G_DN     acc[41:31]                 // a pass's top set bit
`define G_TZ     acc[52:42]                 // a pass's lowest set bit (the shift)
`define G_CB     acc[60:53]                 // a byte held across reads
`define G_GRD    acc[68:61]                 // the byte read
`define G_RRET   p16[6:0]                   // where a read returns
`define G_J      dv_q[7:0]                  // byte index from the top (counts down)
`define G_K      dv_q[15:8]                 // byte index from the bottom; the record byte
`define G_S      dv_q[25:16]                // the shift's source index
`define G_HP     dv_r[8:0]                  // the group's first message
`define G_Q      dv_r[17:9]                 // the counting scan
`define G_A      dv_d[8:0]                  // the member being differenced
`define G_BB     dv_d[17:9]                 // buffer B = end + L (buffer A = end)
`define G_LEN    bh[7:0]
`define G_CNT    n[7:0]                     // frames of this length
`define G_USED   n1[7:0]                    // nonzero differences
`define G_SRET   bp[5:0]                    // where a shift returns
`define G_BU     bp[13:6]                   // the best's differences
`define G_LSB    a_L[0]
`define G_GV     a_L[1]                     // g exists
`define G_YS     a_L[2]                     // y's buffer (1 = B)
`define G_XS     a_L[3]                     // x's buffer
`define G_NZ     L[0]                       // a pass saw a set bit
`define G_PAST   L[1]                       // the counting scan has passed the group's first
`define G_NF     L[2]                       // not the first of its length
`define G_NX0    L[3]                       // the shift's source ran out (zeros)
`define G_BF     wb[0]                      // the record holds a candidate
`define G_BL     wb[1]                      // ... in LSB-first order
  localparam [6:0] G_INI = 7'd22, G_HDR = 7'd23, G_HDR1 = 7'd24, G_CS = 7'd25, G_CS1 = 7'd26,
                   G_CSE = 7'd27, G_CAP = 7'd28, G_CAP1 = 7'd29, G_GRP = 7'd30, G_MS = 7'd31,
                   G_MS1 = 7'd32, G_D0 = 7'd33, G_D1 = 7'd34, G_D2 = 7'd35, G_D3 = 7'd36,
                   G_D4 = 7'd37, G_DEND = 7'd38, G_DSH = 7'd39, G_NXM = 7'd40, G_ST = 7'd41,
                   G_X0 = 7'd42, G_X1 = 7'd43, G_X2 = 7'd44, G_X3 = 7'd45, G_X4 = 7'd46,
                   G_XEND = 7'd47, G_SH0 = 7'd48, G_SH1 = 7'd49, G_SH3 = 7'd50, G_SH3B = 7'd51,
                   G_SH4 = 7'd52, G_SH5 = 7'd53, G_SHE = 7'd54, G_GEND = 7'd55, G_C0 = 7'd56,
                   G_C1 = 7'd57, G_C2 = 7'd58, G_C3 = 7'd59, G_CW = 7'd60, G_CW1 = 7'd61,
                   G_GNX = 7'd62, G_RD = 7'd63, G_RW = 7'd64, G_RV = 7'd65, G_FIN = 7'd66, G_SH2 = 7'd67;
  wire [AW-1:0] g_xb = `G_XS ? `G_BB : `S3_WP;  // the buffers' bases
  wire [AW-1:0] g_yb = `G_YS ? `G_BB : `S3_WP;
  function [2:0] g_msb(input [7:0] v);          // the top set bit of a nonzero byte
    g_msb = v[7] ? 3'd7 : v[6] ? 3'd6 : v[5] ? 3'd5 : v[4] ? 3'd4 :
            v[3] ? 3'd3 : v[2] ? 3'd2 : v[1] ? 3'd1 : 3'd0;
  endfunction
  function [2:0] g_lsb(input [7:0] v);          // the lowest set bit of a nonzero byte
    g_lsb = v[0] ? 3'd0 : v[1] ? 3'd1 : v[2] ? 3'd2 : v[3] ? 3'd3 :
            v[4] ? 3'd4 : v[5] ? 3'd5 : v[6] ? 3'd6 : 3'd7;
  endfunction
  // the difference byte, in the group's bit order (LSB-first = each byte reversed)
  wire [7:0]  g_dv  = `G_CB ^ `G_GRD;
  wire [7:0]  g_d   = `G_LSB ? {g_dv[0], g_dv[1], g_dv[2], g_dv[3], g_dv[4], g_dv[5], g_dv[6], g_dv[7]} : g_dv;
  wire [7:0]  g_xv  = `G_CB ^ `G_GRD;            // x ^ y
  wire [7:0]  g_nx  = `G_NX0 ? 8'd0 : `G_GRD;    // the shift's next-higher source byte
  wire [15:0] g_fn  = {g_nx, `G_CB} >> acc[44:42];
  wire [1:0]  g_wc  = (`G_DY == 11'd8) ? 2'd1 : (`G_DY == 11'd16) ? 2'd2 : 2'd3;
  wire        g_cand = `G_GV && (`G_USED >= 8'd3) &&
                       ((`G_DY == 11'd8) || (`G_DY == 11'd16) || (`G_DY == 11'd32));
  // the golden's order as a key (the record holds the best so far)
  wire        g_better = !`G_BF || (`G_USED > `G_BU) ||
                         ((`G_USED == `G_BU) && ((!`G_LSB && `G_BL) || ((`G_LSB == `G_BL) && (`G_CNT > `G_GRD))));
  // the poly bytes: the low w bits of g are its last w / 8 bytes
  wire        g_pb  = (`G_K == 8'd4) || ((`G_K == 8'd5) && (g_wc != 2'd1)) || (dv_q[15:9] == 7'd3 && g_wc == 2'd3);
  assign      raddr = (t3 >= G_INI) ? `G_RA : 9'd40 + {3'd0, w, 3'b000} + {5'd0, w, 1'b0} + {5'd0, wb};
  // ===========================================================================
  // STAGE 3, PIECE 3 (Wilson 11-05): init and xorout -- golden io_evidence +
  // crc_init_xorout + canonical_member, bit for bit, WITHOUT the golden's
  // matrix (method evidence: model/pit_solver_evidence.py, 6000/6000):
  //   * evidence: lengths in increasing order over every message but the LAST;
  //     a length counts with >= 2 frames whose differences are all 0 mod g (a
  //     shift register over m ^ m_0 must end at 0); the first two lengths
  //     longer than w / 8 bytes give m1, m2 (the first frame of each)
  //   * the golden's columns are x^j P mod g: ONE equation, P init = y (mod g).
  //     Times x^w both sides take WHOLE frames: y' = reg(m1) ^ reg(m2) and
  //     P' = x^(8 L1) + x^(8 L2) mod g, each a shift-register pass
  //   * binary gcd as a modular DIVISION: (a, u) = (P', y'), (b, v) = (g, 0),
  //     keeping a init = u and b init = v (mod g). Halve a (u / x mod g: g is
  //     odd), or swap so a >= b, then a ^= b, u ^= v. At a = 0: u must be 0
  //     (else no init solves), b = h = gcd(P', g), h init = v (mod g):
  //     h | v or no solution, and the canonical member -- the golden's SMALLEST
  //     init -- is (v / h) mod (g / h); a kernel exactly when h != 1
  //   * xorout = c1 ^ reg(d1, init): the register over m1's data, then its last
  //     w / 8 bytes rotated in (the register's top out, XORed with the CRC bit)
  // Every degree test is ONE 33-bit compare: a < b for the swap; in a division
  // step, (r ^ d) < r <=> deg r = deg d. SPACE RULE (Wilson 11-05): NONE --
  // every value is in a register stages 1-2 or piece 2 are done with; the store
  // is only read. The record's last 8 bytes (128..135) are written LAST
  // (option (a)): init, xorout little-endian, zeros when there is none.
  // ===========================================================================
`define P_A      acc[41:9]                  // a: the register passes, the gcd's a, the remainder
`define P_V      {dv_d[22:13], p16[18:7], acc[51:42]}   // v (32)
`define P_B      {dv_r[3:0], dv_q[28:0]}    // b (33): P', then the gcd's b = h, then init
`define P_U      {dv_d[12:0], dv_r[23:4]}   // u (33)
`define P_G      {n[7:0], bh[8:0], bp[14:0]}             // g without its top bit (32)
`define P_A1     n1[8:0]                    // m1's header
`define P_A2     {acc[74:69], wb[2:0]}      // m2's header
`define P_J      {x_ph, why, cls}           // bytes / steps left in a pass
`define P_BI     {f_clock, f_manch, f_nrzi} // the bit in the byte
`define P_NV     {f_irreg, f_atry}          // lengths found as evidence
`define P_OK     f_body                     // every difference so far is 0 mod g
`define P_KER    a_idle                     // the kernel flag (h != 1)
`define P_IO     wh                         // init / xorout found
`define P_YF     n[8]                       // the second frame's pass; xorout's CRC bytes
`define P_LSB    a_L[0]
`define P_WC     a_L[2:1]
`define P_LP     dv_r[11:4]                 // the evidence scan: the last length tried
`define P_LC     dv_r[19:12]                // ... the next (0 = none)
`define P_Q      dv_q[8:0]                  // ... the header scan
`define P_M0     dv_q[17:9]                 // ... the group's first frame
`define P_PM     dv_q[26:18]                // ... the member's byte
`define P_M0F    dv_q[27]
`define P_TWO    dv_q[28]                   // ... a second frame was seen
`define P_PZ     dv_d[8:0]                  // ... m_0's byte
// writes: one per register (yosys refuses some multi-register LHS concatenations)
`define P_V_W(x) begin dv_d[22:13] <= (x) >> 22; p16[18:7] <= (x) >> 10; acc[51:42] <= (x); end
`define P_B_W(x) begin dv_r[3:0] <= (x) >> 29; dv_q[28:0] <= (x); end
`define P_U_W(x) begin dv_d[12:0] <= (x) >> 20; dv_r[23:4] <= (x); end
`define P_G_W(x) begin n[7:0] <= (x) >> 24; bh[8:0] <= (x) >> 15; bp[14:0] <= (x); end
`define P_A2_W(x) begin acc[74:69] <= (x) >> 3; wb[2:0] <= (x); end
`define P_J_W(x) begin x_ph <= (x) >> 6; why <= (x) >> 3; cls <= (x); end
`define P_BI_W(x) begin f_clock <= (x) >> 2; f_manch <= (x) >> 1; f_nrzi <= (x); end
`define P_NV_W(x) begin f_irreg <= (x) >> 1; f_atry <= (x); end
  localparam [6:0] P_R0 = 7'd68, P_R1 = 7'd69, P_R2 = 7'd70, P_R3 = 7'd71, P_E0 = 7'd72, P_E1 = 7'd73,
                   P_E2 = 7'd74, P_E3 = 7'd75, P_G1 = 7'd76, P_G2 = 7'd77, P_D1 = 7'd78, P_D2 = 7'd79,
                   P_D3 = 7'd80, P_D4 = 7'd81, P_D5 = 7'd82, P_D6 = 7'd83, P_G5 = 7'd84, P_P0 = 7'd85,
                   P_P1 = 7'd86, P_P2 = 7'd87, P_P3 = 7'd88, P_P4 = 7'd89, P_P5 = 7'd90, P_P6 = 7'd91,
                   P_Y1 = 7'd92, P_Y2 = 7'd93, P_Y3 = 7'd94, P_Y4 = 7'd95, P_Y5 = 7'd96, P_Y6 = 7'd97,
                   P_S0 = 7'd98, P_V0 = 7'd99, P_V1 = 7'd100, P_V2 = 7'd101, P_V3 = 7'd102, P_V4 = 7'd103,
                   P_V5 = 7'd104, P_V6 = 7'd105, P_X1 = 7'd106, P_X2 = 7'd107, P_X3 = 7'd108, P_X4 = 7'd109,
                   P_X5 = 7'd110, P_F = 7'd111, P_W0 = 7'd112, P_W1 = 7'd113, P_W2 = 7'd114;
  // ===========================================================================
  // ⭐ s12 NOTE §1 (Wilson 11-09 correction): THE STEP DECODES, REGISTERED FROM
  // THE VALUE t3 IS ABOUT TO TAKE. Every ``T3((X` is `T3(X), which writes t3
  // and f3 = t3fl(X) in the same statement, so f3 is ALWAYS the decode of the
  // current t3: the datapath sees exactly the decode it saw before, from a flop
  // instead of a 7-bit compare (the slow corner's worst path started with that
  // compare and its buffer). Zero cycles. Conditions on DATA stay combinational.
  // Proved every cycle in simulation (the assertion at the end of the module)));
  // M_DECODE_STALE decodes the OLD t3 and must make it fire.
  // ===========================================================================
  localparam integer NF3 = 19;
  localparam integer F_S0 = 0, F_V0 = 1, F_V1 = 2, F_V2 = 3, F_V3 = 4, F_V4 = 5, F_V5 = 6, F_DV = 7, F_P25 = 8, F_X4 = 9, F_Y6 = 10, F_G2 = 11, F_SHX = 12, F_ONE = 13, F_ZERO = 14, F_PBA = 15, F_P6 = 16, F_F = 17, F_W2 = 18;
  function [NF3-1:0] t3fl(input [6:0] v);
    begin
      t3fl = {NF3{1'b0}};
      t3fl[F_S0] = (v == P_S0);
      t3fl[F_V0] = (v == P_V0);
      t3fl[F_V1] = (v == P_V1);
      t3fl[F_V2] = (v == P_V2);
      t3fl[F_V3] = (v == P_V3);
      t3fl[F_V4] = (v == P_V4);
      t3fl[F_V5] = (v == P_V5);
      t3fl[F_DV] = (v == P_V1 || v == P_V3 || v == P_V5);
      t3fl[F_P25] = (v == P_P2 || v == P_P5);
      t3fl[F_X4] = (v == P_X4);
      t3fl[F_Y6] = (v == P_Y6);
      t3fl[F_G2] = (v == P_G2);
      t3fl[F_SHX] = (v == P_D4 || v == P_P2 || v == P_P5 || v == P_Y4 || v == P_X4);
      t3fl[F_ONE] = (v == P_P1 || v == P_P4);
      t3fl[F_ZERO] = (v == P_Y1 || v == P_V0 || v == P_V4);
      t3fl[F_PBA] = (v == P_P3 || v == P_V6);
      t3fl[F_P6] = (v == P_P6);
      t3fl[F_F] = (v == P_F);
      t3fl[F_W2] = (v == P_W2);
    end
  endfunction
  reg  [NF3-1:0] f3;
`ifdef M_DECODE_STALE
`define T3(x) {t3, f3} <= {(x), t3fl(t3)}
`else
`define T3(x) {t3, f3} <= {(x), t3fl(x)}
`endif
  // the width: w = 8 / 16 / 32 (code 1 / 2 / 3), w / 8 CRC bytes, g with its top bit
  wire [7:0]  p_nb  = (`P_WC == 2'd1) ? 8'd1 : (`P_WC == 2'd2) ? 8'd2 : 8'd4;
  wire [32:0] p_gf  = {1'b0, `P_G} | ((`P_WC == 2'd1) ? 33'h100 : (`P_WC == 2'd2) ? 33'h10000 : 33'h100000000);
  // one shift of the register (golden _crc_reg): fb = top ^ bit; and the rotate
  // that takes the CRC bytes for xorout (no feedback: top ^ bit shifts in)
  wire [7:0]  p_cb  = `G_CB;
  wire        p_bit = `P_LSB ? p_cb[`P_BI] : p_cb[3'd7 - `P_BI];
  wire [31:0] p_ar  = acc[40:9];
  wire        p_top = (`P_WC == 2'd1) ? p_ar[7] : (`P_WC == 2'd2) ? p_ar[15] : p_ar[31];
  wire [31:0] p_sh  = (`P_WC == 2'd1) ? {24'd0, p_ar[6:0], 1'b0} :
                      (`P_WC == 2'd2) ? {16'd0, p_ar[14:0], 1'b0} : {p_ar[30:0], 1'b0};
  wire        p_in  = f3[F_P25] ? 1'b0 : p_bit;       // P': zeros
  wire [31:0] p_lf  = p_sh ^ ((p_top ^ p_in) ? `P_G : 32'd0);
  wire [31:0] p_rot = p_sh | {31'd0, p_top ^ p_in};
  // the division step: {r, Q} <<= 1, subtract when deg r = deg d. Q shifts
  // left, its top bit into r, the quotient bit in at the bottom: 32 steps for
  // a 32-bit dividend (v), 33 for g with its top (u) -- leading zeros do nothing
  wire [32:0] p_uu  = `P_U;
  wire [31:0] p_vv  = `P_V;
  wire        p_qv  = f3[F_V3] ? p_uu[32] : p_vv[31];
  wire [32:0] p_ri  = {acc[40:9], p_qv};
  wire [32:0] p_d   = f3[F_V5] ? `P_U : `P_B;
  // ⭐ s12 NOTE §2: THE compare (one 33-bit magnitude compare behind a t3 select)
  // is SPLIT BY USE. The gcd swap (P_S0) compares two flop groups directly, no
  // select in front. A division step's degree test (r ^ d) < r is r[top(d)]: r and
  // r ^ d differ only where d has ones, the highest at top(d) (both 0 when d = 0).
  // d is FIXED for a whole loop (P_B across V1 and V3, P_U across V5; nothing in
  // the loops writes them), so its one-hot top is loaded the step BEFORE each loop
  // (V0, V2, V4) into p_dm, and the test is an AND-OR tree with no ripple.
  // Bit-exact by the identity, 0 cycles; the assertion at the end of the module
  // checks it against the old compare on every division step, and
  // M_DIVMASK_LATE (the mask loaded a step late) must break it.
  // ⭐ §4 (Wilson 11-12): THE SWAP TEST AS A TREE. `P_A < `P_B written as `<`
  // was mapped as a ~25-gate ripple behind a weak driver, and acc -> dv_q swung
  // 2.7 ns across placements whenever it was exposed. lt33 is a balanced
  // prefix tree (6 levels of lt = lt_hi | eq_hi & lt_lo, eq = eq_hi & eq_lo),
  // zero cycles; assertion s12-4 holds it to `<` every S3 cycle, and
  // M_LTTREE_NOEQ (the combine without its eq term) must break the record.
  function lt33(input [32:0] a, input [32:0] b);    // a < b, unsigned
    reg [63:0] l, e;
    integer s, i;
    begin
      l = 64'd0;
      e = {64{1'b1}};
      l[32:0] = ~a & b;                              // a bit where a < b
      e[32:0] = ~(a ^ b);                            // a bit where a == b
      for (s = 1; s < 64; s = s * 2)
        for (i = 0; i < 64; i = i + 2 * s) begin     // [i, i+s) lo, [i+s, i+2s) hi
`ifdef M_LTTREE_NOEQ
          l[i] = l[i + s] | l[i];
`else
          l[i] = l[i + s] | (e[i + s] & l[i]);
`endif
          e[i] = e[i + s] & e[i];
        end
      lt33 = l[0];
    end
  endfunction
  wire        p_lt_s0  = lt33(`P_A, `P_B);           // the gcd swap test
  reg  [32:0] p_dm;                                  // one-hot top(d)
  wire        p_lt_div = |(p_ri & p_dm);             // (r ^ d) < r
  function [32:0] top1(input [32:0] v);              // v's highest set bit, one-hot
    integer k;
    begin
      top1 = 33'd0;
      for (k = 0; k < 33; k = k + 1) if (v[k]) top1 = 33'd1 << k;
    end
  endfunction
  // MESSAGE POINTERS as 10 bits (Wilson 11-06, found by the reason code):
  // messages that fill the store end at 512, which a 9-bit pointer holds as 0
  // -- the end then read as an empty store (the capacity rule saw a free one)
  // and a scan's next header wrapped to address 0 and ran on. A message
  // pointer is never otherwise 0 (they start at 128), so 0 IS 512.
  function [9:0] e10(input [8:0] v);
    e10 = {(v == 9'd0), v};
  endfunction
  wire [9:0]  s3_end = e10(`S3_WP);
  // THE ALU: a + b or a - b (+ a carry in); on a subtract, al_lt = (a < b)
  reg  [25:0] al_a, al_b;
  reg         al_sub, al_ci;
  wire [26:0] al_c  = {1'b0, al_a} + {1'b0, al_sub ? ~al_b : al_b} + {26'd0, al_sub | al_ci};
  // THE ALU'S REGISTER (Wilson 11-07, the slow corner): a step that reads the ALU takes two cycles -- the
  // first (a_ph 0) only registers al_c, the second runs the step on the registered al. The carry chain
  // ends at a flop instead of running on through the step's muxes into acc / dv_q in the same cycle.
  // The operands stay put across the pair (nothing in stage 3 writes in the first cycle).
  reg  [26:0] al;                   // the ALU result, a cycle late
  reg         al_lt;                // on a subtract, (a < b), a cycle late
  reg         a_ph;                 // 1: this step's result is in al
  wire [4:0]  hi5   = {1'b0, acc[28:25]} + {4'd0, al[26]};      // the product's top, doubled + carry
  wire [25:0] w_p16 = {7'd0, p16};
  always @(*) begin
    al_sub = 1'b0; al_ci = 1'b0; al_a = {1'b0, `S3_X}; al_b = 26'd0;
    case (t3)
      // piece 2: addresses, scans and degrees (a + b + 1 steps over a [len] header)
      G_HDR:   begin al_a = {16'd0, e10(`G_HP)}; al_b = {16'd0, s3_end}; al_sub = 1'b1; end
      G_CS:    begin al_a = {16'd0, e10(`G_Q)};  al_b = {16'd0, s3_end}; al_sub = 1'b1; end
      G_CS1:   begin al_a = {17'd0, `G_Q};  al_b = {18'd0, `G_GRD}; al_ci = 1'b1; end
      G_CAP:   begin al_a = {16'd0, s3_end}; al_b = {17'd0, `G_LEN, 1'b0}; end
      G_CAP1:  begin al_a = {17'd0, `S3_WP}; al_b = {18'd0, `G_LEN}; end
      G_GRP:   begin al_a = {17'd0, `G_HP}; al_b = {18'd0, `G_LEN}; al_ci = 1'b1; end
      G_MS:    begin al_a = {16'd0, e10(`G_A)};  al_b = {16'd0, s3_end}; al_sub = 1'b1; end
      G_MS1:   begin al_a = {17'd0, `G_A};  al_b = {18'd0, `G_GRD}; al_ci = 1'b1; end
      G_D1:    begin al_a = {17'd0, `G_A};  al_b = {18'd0, `G_J}; al_ci = 1'b1; end
      G_D2:    begin al_a = {17'd0, `G_HP}; al_b = {18'd0, `G_J}; al_ci = 1'b1; end
      G_D3, G_X1, G_X3, G_SH4:
               begin al_a = {17'd0, g_xb};  al_b = {18'd0, `G_J}; end
      G_X2, G_CW:
               begin al_a = {17'd0, g_yb};  al_b = {18'd0, `G_J}; end
      G_NXM:   begin al_a = {17'd0, `G_A};  al_b = {18'd0, `G_LEN}; al_ci = 1'b1; end
      G_GNX:   begin al_a = {17'd0, `G_HP}; al_b = {18'd0, `G_LEN}; al_ci = 1'b1; end
      G_ST:    begin al_a = {15'd0, `G_DX}; al_b = {15'd0, `G_DY}; al_sub = 1'b1; end
      G_SH0:   begin al_a = {18'd0, `G_LEN}; al_b = ~{18'd0, acc[52:45]}; end   // L - q - 1
      G_SH1, G_SH3B:
               begin al_a = {17'd0, g_xb};  al_b = {16'd0, `G_S}; end
      G_SHE:   begin al_a = {15'd0, `G_DX}; al_b = {15'd0, `G_TZ}; al_sub = 1'b1; end
      // piece 3: the evidence scan (q < end; q + len + 1)
      P_E1, P_G1:
               begin al_a = {16'd0, e10(`P_Q)};  al_b = {16'd0, s3_end}; al_sub = 1'b1; end
      P_E2, P_G2:
               begin al_a = {17'd0, `P_Q};  al_b = {18'd0, `G_GRD}; al_ci = 1'b1; end
      T_MUL:   begin al_a = {acc[24:0], 1'b0}; al_b = acc[7'd50 + {3'd0, wb}] ? w_p16 : 26'd0; end
      T_PRE:   begin al_a = {1'b0, `S3_TOT}; al_b = {10'd0, x_iv}; end
      T_PRE1:  begin al_a = {10'd0, `S3_CLEN}; al_b = {10'd0, x_iv}; al_sub = 1'b1; end
      T_CHK:   begin al_b = {1'b0, `S3_TOT}; al_sub = 1'b1; end
      T_LOC:   begin al_b = {1'b0, `S3_E}; al_sub = 1'b1; end
      T_ADV:   begin al_a = {1'b0, `S3_E}; al_b = {10'd0, x_iv}; end
      T_STEP:  al_b = {13'd0, p16[18:6]};                  // p16 >= 64: stage 1's smallest P is 4
      T_FOUND: begin al_a = {1'b0, `S3_E}; al_b = {10'd0, `S3_CLEN}; al_sub = 1'b1; end
      T_SPL:   begin al_a = {1'b0, `S3_LQ}; al_b = {1'b0, `S3_X}; al_sub = 1'b1; end
      T_SA0:   begin al_a = w_p16; al_b = {w_p16[24:0], 1'b0}; end
      T_MID:   al_b = {8'd0, acc[72:55]};
      T_MLOC:  begin al_a = {1'b0, `S3_LQ}; al_b = {1'b0, `S3_E}; al_sub = 1'b1; end
      T_SAI:   begin al_a = {3'd0, `S3_SA}; al_b = {w_p16[24:0], 1'b0}; end
      T_XE:    al_b = {1'b0, `S3_FL};
      T_LQ1:   al_b = w_p16;
      T_LQ2:   begin al_a = {1'b0, `S3_LQ}; al_b = {9'd0, p16[18:2]}; end
      default: ;
    endcase
  end
  // ⭐ AREA (Wilson 11-05): a, b, u, v are written by a FEW OPERATIONS, chosen
  // per state, through ONE write each -- a write per state put a mux input on
  // every reused bit per state (measured: +25.9k; this is the first cut)
  localparam [3:0] PA_HOLD = 4'd0, PA_ZERO = 4'd1, PA_ONE = 4'd2, PA_SHX = 4'd3,
                   PA_B = 4'd5, PA_XB = 4'd6, PA_SH = 4'd7, PA_S8 = 4'd9;
  localparam [2:0] PB_HOLD = 3'd0, PB_A = 3'd1, PB_XA = 3'd2, PB_GF = 3'd3, PB_ZERO = 3'd4, PB_S8 = 3'd5;
  localparam [2:0] PU_HOLD = 3'd0, PU_HALF = 3'd2, PU_V = 3'd3, PU_XV = 3'd4, PU_GF = 3'd5,
                   PU_DIV = 3'd6;
  localparam [2:0] PV_HOLD = 3'd0, PV_A = 3'd1, PV_ZERO = 3'd2, PV_U = 3'd3, PV_DIV = 3'd4;
  // ⭐ s12 NOTE §3: THE OP SELECT, ONE KEPT COPY PER REGISTER GROUP. The swap test
  // chose every group's operation through ONE driver (b6: `_24011_`, a 7-buffer chain
  // across the die; the new pin: `_72831_`, one weak cell on a 0.30 pF net). Each
  // copy drives only its own group: A = acc (`P_A`), B = dv_r/dv_q (`P_B`, the low
  // `P_U`), D = dv_d (the high `P_U`, `P_V`). Their inputs are the §1 flags,
  // never t3.
  // ⭐ THE COPIES ARE KEPT BY (* keep_hierarchy *) ON pe_s3_opsel (Wilson 11-12,
  // the copy-mechanism ruling). (* keep *) on these select nets was tried
  // (0dd6777) and does NOT hold on the shipping flow: LibreLane 3.1.0.dev4's
  // synthesis merged 6 nets past the compare into all three groups (CI
  // 43329075711; local dev4 mirror identical) against 7 with no keep at all,
  // while keep_hierarchy merged 0. (On dev3 both read 0.) Held by
  // model/gate_select_copies.py, whose must-fire strips the keep_hierarchy.
  // ⚠ keep_hierarchy WITH the log-depth compare (71a0668) has never been
  // placed: the dev4 routed runs are its first measurement.
  wire [3:0] pa_op;
  wire [3:0] pa_op_b, pa_op_d;
  wire [2:0] pb_op;
  wire [2:0] pb_op_a, pb_op_d;
  wire [2:0] pu_op_lo;
  wire [2:0] pu_op_hi;
  wire [2:0] pu_op_a;
  wire [2:0] pv_op;
  wire [2:0] pv_op_a, pv_op_b;
  wire       op_s3  = (st == S_S3);
  wire       op_g2  = (`G_GRD == `P_LC) && (al[8:0] != `S3_WP) && `P_M0F && `P_OK;
  wire       op_anz = (`P_A != 33'd0);
  wire       op_j4  = (`P_J < 8'd4);
  wire [9:0] op_f   = {f3[F_G2], f3[F_SHX], f3[F_ONE], f3[F_ZERO], f3[F_PBA], f3[F_P6],
                       f3[F_Y6], f3[F_S0], f3[F_V2], f3[F_F]};
  wire [2:0] op_fx  = {f3[F_V1] | f3[F_V5], f3[F_V3], f3[F_W2]};
  pe_s3_opsel u_ops_a (.s3(op_s3), .f(op_f), .fx(op_fx), .g2(op_g2), .yf(`P_YF), .anz(op_anz),
                       .aodd(acc[9]), .lt(p_lt_s0), .j4(op_j4),
                       .pa_op(pa_op), .pb_op(pb_op_a), .pu_op(pu_op_a), .pv_op(pv_op_a));
  pe_s3_opsel u_ops_b (.s3(op_s3), .f(op_f), .fx(op_fx), .g2(op_g2), .yf(`P_YF), .anz(op_anz),
                       .aodd(acc[9]), .lt(p_lt_s0), .j4(op_j4),
                       .pa_op(pa_op_b), .pb_op(pb_op), .pu_op(pu_op_lo), .pv_op(pv_op_b));
  pe_s3_opsel u_ops_d (.s3(op_s3), .f(op_f), .fx(op_fx), .g2(op_g2), .yf(`P_YF), .anz(op_anz),
                       .aodd(acc[9]), .lt(p_lt_s0), .j4(op_j4),
                       .pa_op(pa_op_d), .pb_op(pb_op_d), .pu_op(pu_op_hi), .pv_op(pv_op));
  wire _unused_ops = &{1'b0, pa_op_b, pa_op_d, pb_op_a, pb_op_d, pu_op_a, pv_op_a, pv_op_b};
  reg [32:0] pa_nx, pb_nx, pu_nx_lo, pu_nx_hi;
  // a's shift-left step, (a << 1 | bit) ^ (c ? K : 0): the register (fb, g), the
  // rotate (top ^ bit, 1: sh | x = sh ^ x as sh[0] = 0), the division (lt, d)
  wire        p_dv  = f3[F_DV];
  wire [32:0] p_sx  = p_dv ? p_ri : {1'b0, p_sh};
  wire        p_sc  = p_dv ? p_lt_div : (p_top ^ p_in);
  wire [32:0] p_sk  = p_dv ? p_d : (f3[F_X4] && `P_YF) ? 33'd1 : {1'b0, `P_G};
  reg [31:0] pv_nx;
  always @(*) begin
    case (pa_op)
      PA_ONE:  pa_nx = 33'd1;
      PA_SHX:  pa_nx = p_sx ^ (p_sc ? p_sk : 33'd0);
      PA_B:    pa_nx = `P_B;
      PA_XB:   pa_nx = `P_A ^ `P_B;
      PA_SH:   pa_nx = `P_A >> 1;
      PA_S8:   pa_nx = `P_A >> 8;
      default: pa_nx = 33'd0;
    endcase
    case (pb_op)
      PB_A:    pb_nx = `P_A;
      PB_XA:   pb_nx = `P_A ^ `P_B;
      PB_GF:   pb_nx = p_gf;
      PB_S8:   pb_nx = `P_B >> 8;
      default: pb_nx = 33'd0;
    endcase
    // u twice: its dv_r part on group B's op, its dv_d part on group D's (§3)
    case (pu_op_lo)
      PU_HALF: pu_nx_lo = p_uu[0] ? ((p_uu ^ p_gf) >> 1) : (p_uu >> 1);   // u / x mod g
      PU_V:    pu_nx_lo = {1'b0, p_vv};
      PU_XV:   pu_nx_lo = (f3[F_Y6] ? `P_A : p_uu) ^ {1'b0, p_vv};   // y' = a ^ v; the gcd's u ^= v
      PU_GF:   pu_nx_lo = p_gf;
      default: pu_nx_lo = {p_uu[31:0], p_lt_div};                       // PU_DIV
    endcase
    case (pu_op_hi)
      PU_HALF: pu_nx_hi = p_uu[0] ? ((p_uu ^ p_gf) >> 1) : (p_uu >> 1);   // u / x mod g
      PU_V:    pu_nx_hi = {1'b0, p_vv};
      PU_XV:   pu_nx_hi = (f3[F_Y6] ? `P_A : p_uu) ^ {1'b0, p_vv};   // y' = a ^ v; the gcd's u ^= v
      PU_GF:   pu_nx_hi = p_gf;
      default: pu_nx_hi = {p_uu[31:0], p_lt_div};                       // PU_DIV
    endcase
    case (pv_op)
      PV_A:    pv_nx = acc[40:9];
      PV_U:    pv_nx = p_uu[31:0];
      PV_DIV:  pv_nx = {p_vv[30:0], p_lt_div};
      default: pv_nx = 32'd0;
    endcase
  end
  // the pass that consumes a divided interval
  wire div_ip  = (st == S_BANK) || (st == S_RIVAL) || (st == S_RB);   // I / P
  wire div_i16 = (st == S_REF2) || (st == S_ST2) || (st == S_ASYNC) || (st == S_SPAN) || (st == S_PHASE);  // 16 I / P_hat
  // ⛔ ONLY ITS OWN WALKS: stage 0's decoder walks for stage 0 first, and an
  // interval taken then would raise `hold` and freeze a decoder that must not
  // miss stage 0's one-cycle walk_go (measured: stage 0 hung in P_WAIT)
  wire mine = (st == S_PRE) || (st == S_BANK) || (st == S_RIVAL) || (st == S_RB) ||
              (st == S_REF2) || (st == S_ST2) || (st == S_ASYNC) || (st == S_SPAN) || (st == S_PHASE) ||
              t3_walk;
  // !walk_go: the cycle a new walk is issued still sees the last walk's `wend`
  wire pass_end = wend && !x_v && !dv_busy && !walk_go;
  // the stage 3 steps that read al / al_lt / hi5 (in the step or in piece 3's pa_op): each takes the pair
  wire s3_alu = (t3 == T_MUL) || (t3 == T_PRE) || (t3 == T_PRE1) || (t3 == T_CHK) || (t3 == T_LOC) ||
                (t3 == T_ADV) || (t3 == T_STEP) || (t3 == T_FOUND) || (t3 == T_SPL) || (t3 == T_SA0) ||
                (t3 == T_MID) || (t3 == T_MLOC) || (t3 == T_SAI) || (t3 == T_XE) || (t3 == T_LQ1) ||
                (t3 == T_LQ2) || (t3 == G_HDR) || (t3 == G_CS) || (t3 == G_CS1) || (t3 == G_CAP) ||
                (t3 == G_CAP1) || (t3 == G_GRP) || (t3 == G_MS) || (t3 == G_MS1) || (t3 == G_D1) ||
                (t3 == G_D2) || (t3 == G_D3) || (t3 == G_NXM) || (t3 == G_ST) || (t3 == G_X1) ||
                (t3 == G_X2) || (t3 == G_X3) || (t3 == G_SH0) || (t3 == G_SH1) || (t3 == G_SH3B) ||
                (t3 == G_SH4) || (t3 == G_SHE) || (t3 == G_CW) || (t3 == G_GNX) || (t3 == P_E1) ||
                (t3 == P_E2) || (t3 == P_G1) || (t3 == P_G2);

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      dv_q <= 29'd0; dv_r <= 24'd0; dv_d <= 23'd0; dv_n <= 5'd0; dv_busy <= 1'b0;
      st <= S_IDLE; w <= 3'd0; p <= P_FIRST; walk_go <= 1'b0; hold <= 1'b0; done <= 1'b0;
      we <= 1'b0; waddr <= {AW{1'b0}}; wdata <= 8'h00;
      has_prev <= 1'b0; last_l <= 1'b0; wend <= 1'b0;
      x_v <= 1'b0; x_lvl <= 1'b0; x_ph <= 2'd0;
      n <= 9'd0; n1 <= 9'd0; idle_lvl <= 1'b0;
      bp <= 15'd0; bh <= 9'd0; bq <= 1'b0; rival <= 1'b0; s1ok <= 1'b0; p16 <= 19'd0;
      acc <= 75'd0; f_clock <= 1'b0; f_manch <= 1'b0; f_nrzi <= 1'b0; f_irreg <= 1'b0; f_atry <= 1'b0;
      f_body <= 1'b0; a_idle <= 1'b0; L <= 4'd7; a_L <= 4'd0;
      cls <= C_NONE; why <= 3'd0; cond <= 1'b0; wh <= 1'b0; f_span <= 1'b0; wb <= 4'd0;
      t3 <= T_RD; f3 <= t3fl(T_RD); re <= 1'b0; s3_found <= 1'b0; s3_fbs <= 1'b0; s3_nmsg <= 8'd0;
      s3_why <= 4'd0; g_try <= 1'b0; g_skip <= 1'b0;
      al <= 27'd0; al_lt <= 1'b0; a_ph <= 1'b0; p_dm <= 33'd0;
    end else if (!run) begin
      st <= S_IDLE; walk_go <= 1'b0; hold <= 1'b0; we <= 1'b0; done <= 1'b0; dv_busy <= 1'b0;
      x_v <= 1'b0; wend <= 1'b0; re <= 1'b0; a_ph <= 1'b0;
    end else begin
      walk_go <= 1'b0; we <= 1'b0; re <= 1'b0;
      // ---- the divider ----
      if (dv_busy) begin
        if (dv_n == 5'd0) dv_busy <= 1'b0;          // the tail: err / m_r / hit / m16 register this cycle
        else begin
          if (!dv_try[23]) begin dv_r <= dv_try; dv_q <= {dv_q[27:0], 1'b1}; end
          else begin dv_r <= {dv_r[22:0], dv_q[28]}; dv_q <= {dv_q[27:0], 1'b0}; end
          dv_n <= dv_n - 5'd1;
        end
      end
      // ---- the walk: this wire's next interval (golden wire_ivs) ----
      if (walk_go) begin has_prev <= 1'b0; wend <= 1'b0; end
      if (wdone_p1 && mine) wend <= 1'b1;
      if (p1_v && p1_rm[w] && mine) begin
        if (has_prev) begin
          x_v <= 1'b1; x_ph <= 2'd0; hold <= 1'b1;
          x_lvl <= last_l;
        end
        last_l <= p1_lv[w]; has_prev <= 1'b1;
      end
      // ---- one interval, by pass (stage 3 takes its own: S_S3 below) ----
      if (x_v && st != S_S3) begin
        if (st == S_PRE) begin
          if (x_iv != OVF) begin
            n <= n + 9'd1;
            if (x_lvl) n1 <= n1 + 9'd1;
            if (x_iv > acc[15:0]) begin acc[15:0] <= x_iv; idle_lvl <= x_lvl; end   // IVMAX
          end
          x_v <= 1'b0; hold <= 1'b0;
        end else if (x_ph == 2'd0) begin
          if (x_iv == OVF && div_ip) begin x_v <= 1'b0; hold <= 1'b0; end     // stage 1: data excludes OVF
          else if (x_iv == OVF && st == S_REF2) begin x_v <= 1'b0; hold <= 1'b0; end
          // the phase walk: golden t0 = the FIRST non-OVF interval, then nothing
          else if (st == S_PHASE && (x_iv == OVF || acc[59])) begin x_v <= 1'b0; hold <= 1'b0; end
          else if (x_iv == OVF) begin                                         // stage 2: an idle run
            x_ph <= 2'd1;                                                     // no divide: m is idle
          end else begin
            x_ph <= 2'd1; dv_busy <= 1'b1; dv_n <= 5'd29; dv_r <= 24'd0;
            dv_q <= div_ip ? {13'd0, x_iv} : {9'd0, x_iv, 4'd0};
            dv_d <= div_ip ? {8'd0, p} : {4'd0, p16};
          end
        end else if (x_ph == 2'd1 && !dv_busy) begin
          // the divide is done (an OVF interval arrives here with m forced idle)
          case (st)
            S_BANK, S_RIVAL, S_RB, S_REF2: begin
              if (hit) begin
                acc[26:18] <= acc[26:18] + 9'd1;                              // H
                if (x_lvl != idle_lvl) acc[8:0] <= acc[8:0] + 9'd1;           // HA
                else acc[17:9] <= acc[17:9] + 9'd1;                           // HI
                acc[51:27] <= acc[51:27] + {9'd0, x_iv};                      // SI
                acc[74:52] <= acc[74:52] + m_r[22:0];                         // SM
              end
              x_v <= 1'b0; hold <= 1'b0;
            end
            S_ST2: begin
              if (x_iv == OVF || m_r > 29'd15) begin
                acc[17:9] <= acc[17:9] + 9'd1; acc[54 + x_lvl] <= 1'b1;      // IDLE, ILV
              end else begin
                acc[8:0] <= acc[8:0] + 9'd1; acc[56 + x_lvl] <= 1'b1;        // BODY, BLV
                if (m_r == 29'd1) acc[58] <= 1'b1;
                else if (m_r == 29'd2) acc[59] <= 1'b1;
                else acc[60] <= 1'b1;
                if (m_r == 29'd7) acc[61] <= 1'b1;
                if (m_r[3:0] > acc[65:62]) acc[65:62] <= m_r[3:0];
                if (x_lvl) begin acc[53:45] <= acc[53:45] + 9'd1; if (m_r <= 29'd1) acc[35:27] <= acc[35:27] + 9'd1; end
                else begin acc[44:36] <= acc[44:36] + 9'd1; if (m_r <= 29'd1) acc[26:18] <= acc[26:18] + 9'd1; end
              end
              x_v <= 1'b0; hold <= 1'b0;
            end
            S_PHASE: begin
              acc[58:44] <= dv_r[18:4]; acc[59] <= 1'b1;                       // (16 t0) mod P_hat, / 16
              x_v <= 1'b0; hold <= 1'b0;
            end
            S_ASYNC: begin
              acc[19:15] <= (x_iv == OVF) ? 5'd16 : m16;                       // RUN
              x_ph <= 2'd2;
            end
            default: begin   // S_SPAN
              if (x_iv == OVF || m_r > 29'd15) begin
                if (acc[21:9] != 13'd0) begin
                  acc[43:35] <= acc[43:35] + 9'd1;
                  if (acc[21:9] > acc[34:22]) acc[34:22] <= acc[21:9];
                end
                acc[21:9] <= 13'd0;
              end else acc[21:9] <= acc[21:9] + {9'd0, m_r[3:0]};
              x_v <= 1'b0; hold <= 1'b0;
            end
          endcase
        end else if (x_ph == 2'd2) begin
          // ASYNC: one bit of the run per cycle (golden async_frame_len's bits)
          if (acc[19:15] == 5'd0) begin x_v <= 1'b0; hold <= 1'b0; end
          else begin
            acc[19:15] <= acc[19:15] - 5'd1;                                     // RUN
            if (!acc[14]) begin                                                 // !ABAD
              if (!acc[13]) begin                                               // !INFR
                if (x_lvl != a_idle) begin acc[13] <= 1'b1; acc[12:9] <= 4'd1; end
              end else if (acc[12:9] == L - 4'd1) begin
                acc[13] <= 1'b0;
                if (x_lvl != a_idle) acc[14] <= 1'b1;
                else acc[8:0] <= acc[8:0] + 9'd1;                             // FR
              end else acc[12:9] <= acc[12:9] + 4'd1;                            // FJ
            end
          end
        end
      end
      // ---- the passes ----
      case (st)
        S_IDLE: if (go && !done) begin w <= 3'd0; st <= S_WIRE; end
        S_WIRE: begin
          cls <= C_NONE; why <= 3'd0; cond <= 1'b0; wh <= 1'b0; f_span <= 1'b0; a_L <= 4'd0;
          bq <= 1'b0; rival <= 1'b0; s1ok <= 1'b0; bh <= 9'd0; p16 <= 19'd0; a_idle <= 1'b0;
          n <= 9'd0; n1 <= 9'd0; acc <= 75'd0; wb <= 4'd0;
          if (!act[w]) st <= S_WR;                                             // inactive: a zero record
          else if (refused) begin cls <= C_UNK; why <= 3'd6; st <= S_WR; end
          else if (roled[w]) begin cls <= C_ROLE; st <= S_WR; end
          else begin walk_go <= 1'b1; st <= S_PRE; end
        end
        S_PRE: if (pass_end) begin
          if (n < 9'd16) begin cls <= C_UNK; why <= 3'd1; acc <= 75'd0; st <= S_WR; end
          else begin p <= P_FIRST; acc <= 75'd0; walk_go <= 1'b1; st <= S_BANK; end
        end
        S_BANK: if (pass_end) begin
          // ascending P: the last qualifier is the LARGEST qualifying period
          if (qual) begin bq <= 1'b1; bp <= p; bh <= acc[26:18]; end
          acc <= 75'd0;
          if (p_end) begin
            if (!(bq || qual)) begin cls <= C_UNK; why <= 3'd2; st <= S_WR; end
            // `M_S12_NO_RIVAL`, the must-fire: no rival check -- a non-harmonic tie reports a period
`ifdef M_S12_NO_RIVAL
            else begin p <= bp; s1ok <= 1'b1; walk_go <= 1'b1; st <= S_RB; end
`else
            else begin p <= P_FIRST; walk_go <= 1'b1; st <= S_RIVAL; end
`endif
          end else begin p <= p_next[14:0]; walk_go <= 1'b1; end
        end
        S_RIVAL: if (pass_end) begin
          if (qual && acc[26:18] + {4'd0, n[8:4]} >= bh) begin
            // _harmonic(P_best, q): k = round(hi / lo), |hi - k lo| * 8 <= hi
            dv_busy <= 1'b1; dv_n <= 5'd29; dv_r <= 24'd0;
            dv_q <= {14'd0, (p > bp) ? p : bp}; dv_d <= {8'd0, (p > bp) ? bp : p};
            st <= S_HARM;
          end else if (p_end) begin p <= bp; s1ok <= 1'b1; walk_go <= 1'b1; st <= S_RB; end
          else begin p <= p_next[14:0]; walk_go <= 1'b1; end
          acc <= 75'd0;
        end
        S_HARM: if (!dv_busy) begin
          if (!(m_r != 29'd0 && {err, 3'b000} <= {11'd0, rv_hi})) begin
            rival <= 1'b1; cls <= C_UNK; why <= 3'd3; st <= S_WR;               // a non-harmonic rival
          end else if (p_end) begin p <= bp; s1ok <= 1'b1; walk_go <= 1'b1; st <= S_RB; end
          else begin p <= p_next[14:0]; walk_go <= 1'b1; st <= S_RIVAL; end
        end
        S_RB: if (pass_end) begin
          // refine 1: P_hat = (16 SI + SM / 2) / SM over the best's hits (recomputed by this walk)
          dv_busy <= 1'b1; dv_n <= 5'd29; dv_r <= 24'd0;
          dv_q <= {acc[51:27], 4'd0} + {7'd0, acc[74:53]}; dv_d <= acc[74:52];
          st <= S_REF1;
        end
        S_REF1: if (!dv_busy) begin
          p16 <= dv_q[18:0]; acc <= 75'd0; walk_go <= 1'b1; st <= S_REF2;
        end
        S_REF2: if (pass_end) begin
          // refine 2 over the full hit set at P_hat (M2)
          if (acc[74:52] != 23'd0) begin
            dv_busy <= 1'b1; dv_n <= 5'd29; dv_r <= 24'd0;
            dv_q <= {acc[51:27], 4'd0} + {7'd0, acc[74:53]}; dv_d <= acc[74:52];
          end
          st <= S_REF2D;
        end
        S_REF2D: if (!dv_busy) begin
`ifndef M_S12_NO_REF2
          if (acc[74:52] != 23'd0) p16 <= dv_q[18:0];
`endif
          acc <= 75'd0; walk_go <= 1'b1; st <= S_ST2;
        end
        S_PHASE: if (pass_end) st <= S_CLASS;
        S_ST2: if (pass_end) begin
          f_body  <= (acc[8:0] != 9'd0);
          f_clock <= (acc[17:9] == 9'd0) && acc[58] && !acc[59] && !acc[60] && (acc[57:56] == 2'b11);
          f_manch <= acc[58] && acc[59] && !acc[60] && (acc[8:0] >= 9'd16);
          f_atry  <= (acc[17:9] >= 9'd2) && (acc[55:54] != 2'b11);
          f_nrzi  <= (acc[17:9] == 9'd0) && (acc[65:62] <= 4'd7) && acc[61] && (acc[8:0] >= 9'd64);
          f_irreg <= (acc[44:36] != 9'd0) && (acc[53:45] != 9'd0)
                     && ({acc[26:18], 2'b00} >= {2'b00, acc[44:36]} + {1'b0, acc[44:36], 1'b0})
                     && ({acc[35:27], 2'b00} >= {2'b00, acc[53:45]} + {1'b0, acc[53:45], 1'b0});
          a_idle  <= acc[55];                                                   // the idle runs' one level
          acc <= 75'd0;
          st <= S_PHASE; walk_go <= 1'b1; a_L <= 4'd0; L <= 4'd7;
          // the async frame length is needed only on the NRZ_ASYNC branch
          if ((acc[8:0] != 9'd0)
              && !((acc[17:9] == 9'd0) && acc[58] && !acc[59] && !acc[60] && (acc[57:56] == 2'b11))
              && !(acc[58] && acc[59] && !acc[60] && (acc[8:0] >= 9'd16))
              && (acc[17:9] >= 9'd2) && (acc[55:54] != 2'b11)) begin
            st <= S_ASYNC; walk_go <= 1'b1;                                   // FJ, INFR, ABAD: clear (acc)
          end
        end
        S_ASYNC: if (pass_end) begin
          if (!acc[14] && acc[8:0] >= 9'd4) begin a_L <= L; acc <= 75'd0; walk_go <= 1'b1; st <= S_PHASE; end   // the SMALLEST such L
          else if (L == 4'd12) begin acc <= 75'd0; walk_go <= 1'b1; st <= S_SPAN; end
          else begin L <= L + 4'd1; acc <= 75'd0; walk_go <= 1'b1; end
        end
        S_SPAN: if (pass_end) begin
          // the open span at the end of the walk counts too
          if (acc[21:9] != 13'd0) begin
            acc[43:35] <= acc[43:35] + 9'd1;
            if (acc[21:9] > acc[34:22]) acc[34:22] <= acc[21:9];
          end
          acc[21:9] <= 13'd0;
          walk_go <= 1'b1; st <= S_PHASE;
        end
        S_CLASS: begin
          // golden _stage2's order, then stage2's condition and the R2 guard
`ifdef M_S12_NO_BODYCHK
          if (1'b0) begin end  // the must-fire: "no non-idle runs" never reported
`else
          if (!f_body) begin cls <= C_UNK; why <= 3'd4; end
`endif
          else if (f_clock) cls <= C_CLOCK;
          else if (f_manch) begin cls <= C_MANCH; cond <= 1'b1; end
          else if (f_atry && a_L != 4'd0) begin
            cls <= C_ASYNC; cond <= 1'b1;
`ifdef M_S12_NO_SPAN
          end else if (1'b0) begin      // the must-fire: the span fallback off
`else
          end else if (f_atry && acc[43:35] >= 9'd2) begin
`endif
            cls <= C_ASYNC; cond <= 1'b1; f_span <= 1'b1;
          end else if (f_nrzi) begin cls <= C_NRZI; cond <= 1'b1; end
`ifdef M_S12_NO_IRREG
          else if (1'b0) begin end      // the must-fire: the stretched-clock refusal off
`else
          else if (f_irreg) begin cls <= C_UNK; why <= 3'd5; end
`endif
          else cls <= C_LEVEL;
          st <= S_WR;
        end
        S_WR: begin
          // the R2 guard (golden stage2, guard=True), applied as the record is written
`ifdef M_S12_NO_R2
          if (1'b0) begin      // the must-fire: the R2 guard off (a clock on another pin is ignored)
`else
          if (wb == 4'd0 && r2_hit && (cls == C_MANCH || cls == C_ASYNC)) begin
`endif
            wh <= (cls == C_ASYNC); cls <= C_UNK; why <= 3'd7; cond <= 1'b0;
          end else begin
            we <= 1'b1;
            waddr <= 9'd40 + {3'd0, w, 3'b000} + {5'd0, w, 1'b0} + {5'd0, wb};
            case (wb)
              4'd0: wdata <= {cls, why, cond, wh};
              4'd1: wdata <= {(cls == C_ASYNC) ? a_idle : 1'b0, p16[18:16], fb[12:9]};
              4'd2: wdata <= p16[15:8];
              4'd3: wdata <= p16[7:0];
              4'd4: wdata <= {fb[8], acc[58:52]};                                 // PH
              4'd5: wdata <= acc[51:44];
              4'd6: wdata <= s1ok ? sc8 : 8'd0;
              4'd7: wdata <= n8;
              4'd8: wdata <= frames;
              default: wdata <= fb[7:0];
            endcase
            wb <= wb + 4'd1;
            if (wb == 4'd9) st <= S_NEXT;
          end
        end
        // stage 3 follows wire 7's record (Wilson 11-05): `done` is stages 1-3
        S_NEXT: if (w == 3'd7) begin
                  w <= 3'd0; wb <= 4'd0; st <= S_S3; `T3((T_RD));
                  s3_found <= 1'b0; s3_fbs <= 1'b0; s3_nmsg <= 8'd0;
                  s3_why <= 4'd0; g_try <= 1'b0; g_skip <= 1'b0;
                end else begin w <= w + 3'd1; st <= S_WIRE; end
        S_S3: if (s3_alu && !a_ph) begin
          al <= al_c; al_lt <= al_sub & ~al_c[26]; a_ph <= 1'b1;
        end else begin
          a_ph <= 1'b0;
          case (t3)
            // ---- stage 2's record of the first NRZ_ASYNC wire (40 + 10w + wb) ----
            T_RD: begin re <= 1'b1; `T3((T_RW)); end
            T_RW: `T3((T_RV));                          // the store registers rdata
            T_RV: begin
              `T3((T_RD));
              case (wb)
                4'd0: if (rdata[7:5] == C_ASYNC) begin s3_found <= 1'b1; wb <= 4'd1; end
                      else if (w == 3'd7) `T3((T_CK));         // no UART wire: a clocked bus?
                      else w <= w + 3'd1;
                4'd1: begin p16[18:16] <= rdata[6:4]; acc[62:59] <= rdata[3:0]; wb <= 4'd2; end
                4'd2: begin p16[15:8] <= rdata; wb <= 4'd3; end
                4'd3: begin p16[7:0] <= rdata; wb <= 4'd4; end
                4'd4: begin acc[58] <= rdata[7]; wb <= 4'd9; end
                default: begin
                  acc[57:50] <= rdata;
                  if ({acc[62:58], rdata} < S3_MIN_FB) begin
                    s3_fbs <= 1'b1; s3_why <= 4'd1; `T3((G_INI)); `G_K <= 8'd0;
                  end
                  else begin `S3_P30 <= 30'd0; `S3_HLE <= 1'b0; wb <= 4'd12; `T3((T_MUL)); end
                end
              endcase
            end
            // ---- fl = (fb * p16) >> 4 into the product {LQ[4:0], X}: 13 shift-adds;
            //      >= 2^29 (or a sticky overflow) saturates fl past any total ----
            T_MUL: begin
              `S3_P30 <= {hi5[3:0], al[25:0]};
              if (acc[29] | hi5[4]) `S3_HLE <= 1'b1;
              wb <= wb - 4'd1;
              if (wb == 4'd0) begin
                `S3_FL <= (`S3_HLE | acc[29] | hi5[4] | hi5[3]) ? {25{1'b1}} : {hi5[2:0], al[25:4]};
                `S3_TOT <= 25'd0; `S3_CLEN <= 16'd0; `S3_IDLE <= 1'b0;
                walk_go <= 1'b1; `T3((T_PRE));
              end
            end
            // ---- the pre-pass: total, and the level of the FIRST longest interval ----
            T_PRE: if (x_v) begin `S3_TOT <= al[24:0]; `T3((T_PRE1)); end
                   else if (pass_end) begin
                     walk_go <= 1'b1; `T3((T_CHK));
                     `S3_X <= 25'd0; `S3_E <= 25'd0; `S3_CUR <= 1'b0; `S3_HLE <= 1'b0;
                     `S3_OPEN <= 1'b0; `S3_MBYTE <= 1'b0; `S3_WP <= S3_CAP; s3_nmsg <= 8'd0;
                   end
            T_PRE1: begin
              if (al_lt) begin `S3_CLEN <= x_iv; `S3_IDLE <= x_lvl; end   // max < interval
              x_v <= 1'b0; hold <= 1'b0; `T3((T_PRE));
            end
            // ---- the decode (golden async_bytes): scan, locate, step / find ----
            T_CHK: `T3((al_lt ? T_LOC : T_END));                 // x < total
            T_LOC: if (!`S3_CUR) begin
                     if (x_v) `T3((T_ADV)); else if (exh) `T3((T_END));
                   end else if (al_lt | exh) `T3(((`S3_L == `S3_IDLE) ? T_STEP : T_FOUND));
                   else if (x_v) `T3((T_ADV));
            T_ADV: begin                                        // the next interval [e, e + len)
              `S3_E <= al[24:0]; `S3_CLEN <= x_iv; `S3_L <= x_lvl; `S3_CUR <= 1'b1;
              x_v <= 1'b0; hold <= 1'b0; `T3((`S3_MBYTE ? T_MLOC : T_LOC));
            end
            T_STEP:  begin `S3_X <= al[24:0]; `T3((T_CHK)); end  // x += step
            T_FOUND: begin `S3_X <= al[24:0]; `T3((T_SPL)); end  // s = e - len: back up to the edge
            T_SPL: begin                                        // s > le + 5 p16 / 4: a new message
              if (`S3_HLE & `S3_OPEN & al_lt) begin
                we <= 1'b1; waddr <= `S3_LA; wdata <= `S3_MLEN; `S3_OPEN <= 1'b0;
                if (s3_nmsg != 8'hFF) s3_nmsg <= s3_nmsg + 8'd1;
              end
              `T3((T_SA0));
            end
            T_SA0: begin `S3_SA <= al[22:0]; `S3_BI <= 3'd0; `S3_MBYTE <= 1'b1; `T3((T_MID)); end
            T_MID: begin `S3_LQ <= al[24:0]; `T3((T_MLOC)); end   // mid = s + (2b + 3) p16 / 32
            T_MLOC: if (al_lt | exh) begin `S3_BY <= {`S3_L, bh[7:1]}; `T3((T_SAI)); end
                    else if (x_v) `T3((T_ADV));
            T_SAI: begin
              `S3_SA <= al[22:0]; `S3_BI <= `S3_BI + 3'd1; `T3((T_MID));
              if (`S3_BI == 3'd7) begin
                we <= 1'b1; wdata <= `S3_BY; `T3((T_XE));
                if (`S3_OPEN) begin waddr <= `S3_WP; `S3_WP <= `S3_WP + 9'd1; `S3_MLEN <= `S3_MLEN + 8'd1; end
                else begin
                  `S3_LA <= `S3_WP; waddr <= `S3_WP + 9'd1; `S3_WP <= `S3_WP + 9'd2;
                  `S3_MLEN <= 8'd1; `S3_OPEN <= 1'b1;
                end
              end
            end
            T_XE:  begin `S3_X <= al[25] ? {25{1'b1}} : al[24:0]; `S3_MBYTE <= 1'b0; `T3((T_LQ1)); end
            T_LQ1: begin `S3_LQ <= al[24:0]; `T3((T_LQ2)); end
            T_LQ2: begin `S3_LQ <= al[24:0]; `S3_HLE <= 1'b1; `T3((T_CHK)); end
            T_END: begin
              if (`S3_OPEN) begin
                we <= 1'b1; waddr <= `S3_LA; wdata <= `S3_MLEN; `S3_OPEN <= 1'b0;
                if (s3_nmsg != 8'hFF) s3_nmsg <= s3_nmsg + 8'd1;
              end
              x_v <= 1'b0; hold <= 1'b0; `T3((T_DRAIN));
            end
            T_DRAIN: begin x_v <= 1'b0; hold <= 1'b0; if (pass_end) begin `T3((G_INI)); `G_K <= 8'd0; end end
            // ---- the clocked bus (Wilson 11-06): stage 0 picks it, pe_pit captures it
            //      again as messages; the solver below runs on them unchanged ----
            T_CK: if (ck_fin) begin
                    `T3((G_INI)); `G_K <= 8'd0;
                    if (ck_ok) begin s3_found <= 1'b1; w <= ck_w; `S3_WP <= ck_wp; s3_nmsg <= ck_nmsg; end
                    else s3_why <= ck_why;
                  end
            // ================= piece 2: the GCD (golden crc_poly_gcd_s3_fit) =================
            // the record 120..127: wire | 8 (0 with no NRZ_ASYNC wire), the rest 0
            G_INI: begin
              we <= 1'b1; waddr <= {6'b001111, dv_q[10:8]};
              wdata <= (dv_q[10:8] == 3'd0 && s3_found) ? {5'b00001, w} : 8'd0;
              `G_K <= `G_K + 8'd1;
              if (dv_q[10:8] == 3'd7) begin
                if (s3_found && !s3_fbs) begin `G_HP <= S3_CAP; `T3((G_HDR)); end
                else `T3((G_FIN));
              end
            end
            // ---- each message that is the FIRST of its length starts a group ----
            G_HDR:  if (!al_lt) `T3((G_FIN));                               // hp >= end
                    else begin `G_RA <= `G_HP; `G_RRET <= G_HDR1; `T3((G_RD)); end
            G_HDR1: begin
              `G_LEN <= `G_GRD; `G_Q <= S3_CAP; `G_CNT <= 8'd0; `G_NF <= 1'b0; `G_PAST <= 1'b0; `T3((G_CS));
            end
            G_CS:   if (!al_lt) `T3((G_CSE));                               // q >= end
                    else begin `G_RA <= `G_Q; `G_RRET <= G_CS1; `T3((G_RD)); end
            G_CS1: begin                                                    // count, and "first?"
              if (`G_Q == `G_HP) `G_PAST <= 1'b1;
              // the LAST message is never evidence (Wilson 11-06): its q + len + 1 is the end
`ifdef M_S3_LAST_KEEP
              if (`G_GRD == `G_LEN) begin
`else
              if (`G_GRD == `G_LEN && al[8:0] != `S3_WP) begin
`endif
                `G_CNT <= `G_CNT + 8'd1;
                if (!`G_PAST && `G_Q != `G_HP) `G_NF <= 1'b1;
              end
              `G_Q <= al[8:0]; `T3((G_CS));                                  // q + len + 1
            end
            // < 2 frames: not a group (golden); the capacity rule then decides
            // tried / skipped (the reason code), and < 4 frames (< 3
            // differences) is never a candidate
            G_CSE:  if (`G_NF || `G_CNT < 8'd2) begin `G_LSB <= 1'b1; `T3((G_GNX)); end
                    else `T3((G_CAP));
            // the capacity rule: end + 2 L <= 512
            G_CAP:  if (al[9] && al[8:0] != 9'd0) begin g_skip <= 1'b1; `G_LSB <= 1'b1; `T3((G_GNX)); end
                    else begin
                      g_try <= 1'b1;
                      if (`G_CNT < 8'd4) begin `G_LSB <= 1'b1; `T3((G_GNX)); end
                      else `T3((G_CAP1));
                    end
            G_CAP1: begin `G_BB <= al[8:0]; `G_LSB <= 1'b0; `T3((G_GRP)); end
            // ---- one group in one bit order ----
            G_GRP:  begin `G_USED <= 8'd0; `G_GV <= 1'b0; `G_A <= al[8:0]; `T3((G_MS)); end
            G_MS:   if (!al_lt) `T3((G_GEND));                              // a >= end
                    else begin `G_RA <= `G_A; `G_RRET <= G_MS1; `T3((G_RD)); end
`ifdef M_S3_LAST_KEEP
            G_MS1:  if (`G_GRD == `G_LEN) `T3((G_D0));
`else
            G_MS1:  if (`G_GRD == `G_LEN && al[8:0] != `S3_WP) `T3((G_D0));    // the last: not evidence
`endif
                    else begin `G_A <= al[8:0]; `T3((G_MS)); end
            // d = m_a ^ m_0 into x's buffer, bottom byte first: its top bit and lowest bit
            G_D0: begin
              `G_XS <= `G_GV ? ~`G_YS : 1'b0; `G_J <= `G_LEN - 8'd1; `G_K <= 8'd0; `G_NZ <= 1'b0; `T3((G_D1));
            end
            G_D1: begin `G_RA <= al[8:0]; `G_RRET <= G_D2; `T3((G_RD)); end
            G_D2: begin `G_CB <= `G_GRD; `G_RA <= al[8:0]; `G_RRET <= G_D3; `T3((G_RD)); end
            G_D3: begin
              we <= 1'b1; waddr <= al[8:0]; wdata <= g_d;
              if (g_d != 8'd0) begin
                `G_DN <= {`G_K, g_msb(g_d)};
                if (!`G_NZ) `G_TZ <= {`G_K, g_lsb(g_d)};
                `G_NZ <= 1'b1;
              end
              `T3((G_D4));
            end
            G_D4:   if (`G_J == 8'd0) `T3((G_DEND));
                    else begin `G_J <= `G_J - 8'd1; `G_K <= `G_K + 8'd1; `T3((G_D1)); end
            G_DEND: if (!`G_NZ) `T3((G_NXM));                               // d = 0: not counted
                    else begin
                      `G_USED <= `G_USED + 8'd1; `G_DX <= `G_DN;
                      if (`G_TZ != 11'd0) begin `G_SRET <= G_DSH[5:0]; `T3((G_SH0)); end
                      else `T3((G_DSH));
                    end
            G_DSH:  if (!`G_GV) begin `G_GV <= 1'b1; `G_YS <= `G_XS; `G_DY <= `G_DX; `T3((G_NXM)); end
                    else `T3((G_ST));
            G_NXM:  begin `G_A <= al[8:0]; `T3((G_MS)); end                 // a + L + 1
            // ---- the binary gcd: deg x >= deg y (a swap is two buffer bits), x ^= y ----
            G_ST: begin
              if (al_lt) begin `G_XS <= `G_YS; `G_YS <= `G_XS; `G_DX <= `G_DY; `G_DY <= `G_DX; end
              `G_J <= `G_LEN - 8'd1; `G_K <= 8'd0; `G_NZ <= 1'b0; `T3((G_X1));
            end
            G_X1: begin `G_RA <= al[8:0]; `G_RRET <= G_X2; `T3((G_RD)); end
            G_X2: begin `G_CB <= `G_GRD; `G_RA <= al[8:0]; `G_RRET <= G_X3; `T3((G_RD)); end
            G_X3: begin
              we <= 1'b1; waddr <= al[8:0]; wdata <= g_xv;
              if (g_xv != 8'd0) begin
                `G_DN <= {`G_K, g_msb(g_xv)};
                if (!`G_NZ) `G_TZ <= {`G_K, g_lsb(g_xv)};
                `G_NZ <= 1'b1;
              end
              `T3((G_X4));
            end
            G_X4:   if (`G_J == 8'd0) `T3((G_XEND));
                    else begin `G_J <= `G_J - 8'd1; `G_K <= `G_K + 8'd1; `T3((G_X1)); end
            G_XEND: if (!`G_NZ) `T3((G_NXM));                               // x = 0: gcd = y
                    else begin `G_DX <= `G_DN; `G_SRET <= G_ST[5:0]; `T3((G_SH0)); end
            // ---- x >>= tz, in place, top byte last: new[j] = ({old[j-q-1], old[j-q]} >> r) ----
            G_SH0:  begin `G_S <= al[9:0]; `G_J <= `G_LEN - 8'd1; `G_NX0 <= 1'b0; `T3((G_SH1)); end
            G_SH1:  begin `G_RA <= al[8:0]; `G_RRET <= G_SH2; `T3((G_RD)); end   // old[S]
            G_SH2:  begin `G_CB <= `G_GRD; `T3((G_SH3)); end
            G_SH3:  if (`G_S == 10'd0) begin `G_NX0 <= 1'b1; `T3((G_SH4)); end  // above the top: 0
                    else begin `G_S <= `G_S - 10'd1; `T3((G_SH3B)); end
            G_SH3B: begin `G_RA <= al[8:0]; `G_RRET <= G_SH4; `T3((G_RD)); end   // old[S - 1]
            G_SH4:  begin we <= 1'b1; waddr <= al[8:0]; wdata <= g_fn[7:0]; `G_CB <= g_nx; `T3((G_SH5)); end
            G_SH5:  if (`G_J == 8'd0) `T3((G_SHE));
                    else begin `G_J <= `G_J - 8'd1; `T3((G_SH3)); end
            G_SHE:  begin `G_DX <= al[10:0]; `T3(({1'b0, `G_SRET})); end     // deg -= tz
            // ---- the group's candidate against the record's best (the golden's order) ----
            G_GEND: if (g_cand) begin `G_RA <= 9'd120; `G_RRET <= G_C1; `T3((G_RD)); end
                    else `T3((G_GNX));
            G_C1: begin `G_BF <= acc[65]; `G_BL <= acc[67]; `G_RA <= 9'd122; `G_RRET <= G_C2; `T3((G_RD)); end
            G_C2: begin `G_BU <= `G_GRD; `G_RA <= 9'd123; `G_RRET <= G_C3; `T3((G_RD)); end
            G_C3:   if (g_better) begin `G_K <= 8'd0; `G_J <= `G_LEN - 8'd1; `T3((G_CW)); end
                    else `T3((G_GNX));
            // write it: 0..3 from registers (byte 3 = the group's size until G_FIN),
            // 4..7 = g's last w / 8 bytes (the low w bits: the poly without its top)
            G_CW: begin
              if (dv_q[10]) begin
                if (g_pb) begin `G_RA <= al[8:0]; `G_RRET <= G_CW1; `T3((G_RD)); end
                else begin
                  we <= 1'b1; waddr <= {6'b001111, dv_q[10:8]}; wdata <= 8'd0; `G_K <= `G_K + 8'd1;
                  if (dv_q[10:8] == 3'd7) `T3((G_GNX));
                end
              end else begin
                we <= 1'b1; waddr <= {6'b001111, dv_q[10:8]}; `G_K <= `G_K + 8'd1;
                case (dv_q[9:8])
                  2'd0:    wdata <= {1'b0, `G_LSB, 1'b0, 1'b1, 1'b1, w};
                  2'd1:    wdata <= {(`G_LEN > 8'd63) ? 6'd63 : bh[5:0], g_wc};
                  2'd2:    wdata <= `G_USED;
                  default: wdata <= `G_CNT;
                endcase
              end
            end
            G_CW1: begin
              we <= 1'b1; waddr <= {6'b001111, dv_q[10:8]}; wdata <= `G_GRD;
              `G_J <= `G_J - 8'd1; `G_K <= `G_K + 8'd1;
              `T3(((dv_q[10:8] == 3'd7) ? G_GNX : G_CW));
            end
            // the other bit order, else the next header (hp + L + 1)
            G_GNX:  if (!`G_LSB) begin `G_LSB <= 1'b1; `T3((G_GRP)); end
                    else begin `G_HP <= al[8:0]; `T3((G_HDR)); end
            G_FIN:  begin we <= 1'b1; waddr <= 9'd123; wdata <= s3_nmsg; `T3((P_R0)); end
            // ================= piece 3: init and xorout (golden io_evidence +
            // crc_init_xorout + canonical_member, the method in the header) =========
            // the GCD's result from the record: found? bit order, width, g
            P_R0:   begin `G_RA <= 9'd120; `G_RRET <= P_R1; `T3((G_RD)); end
            P_R1:   if (!acc[65]) begin                                    // byte 0 bit 4: a polynomial
                      `T3((P_F));
                      if (s3_found && !s3_fbs) s3_why <= (g_skip && !g_try) ? 4'd2 : 4'd3;
                    end
                    else begin `P_LSB <= acc[67]; `G_RA <= 9'd121; `G_RRET <= P_R2; `T3((G_RD)); end
            P_R2:   begin `P_WC <= acc[62:61]; `G_RA <= 9'd124; `G_RRET <= P_R3; `T3((G_RD)); end
            P_R3: begin
              `P_G_W(({`G_GRD, n[7:0], bh[8:0], bp[14:8]}))                   // little-endian, in from the top
              if (`G_RA == 9'd127) begin `P_NV_W((2'd0)) `P_LP <= 8'd0; `T3((P_E0)); end
              else begin `G_RA <= `G_RA + 9'd1; `T3((G_RD)); end
            end
            // ---- evidence: the next length (the smallest > the last tried), the last message excluded ----
            P_E0:   begin `P_Q <= S3_CAP; `P_LC <= 8'd0; `T3((P_E1)); end
            P_E1:   if (!al_lt) `T3((P_E3));                                // q >= end
                    else begin `G_RA <= `P_Q; `G_RRET <= P_E2; `T3((G_RD)); end
            P_E2: begin
              if (al[8:0] != `S3_WP && `G_GRD > `P_LP && (`P_LC == 8'd0 || `G_GRD < `P_LC)) `P_LC <= `G_GRD;
              `P_Q <= al[8:0]; `T3((P_E1));
            end
            P_E3:   if (`P_LC == 8'd0) begin `T3((P_F)); s3_why <= 4'd4; end  // fewer than two lengths
                    else begin
                      `P_LP <= `P_LC;
                      if (`P_LC <= p_nb) `T3((P_E0));                       // no data bits: not a length
                      else begin `P_Q <= S3_CAP; `P_M0F <= 1'b0; `P_TWO <= 1'b0; `P_OK <= 1'b1; `T3((P_G1)); end
                    end
            // ---- the group of length lc: every member's difference with the first, 0 mod g ----
            P_G1:   if (!al_lt) `T3((P_G5));
                    else begin `G_RA <= `P_Q; `G_RRET <= P_G2; `T3((G_RD)); end
            P_G2: begin
              `P_Q <= al[8:0]; `T3((P_G1));
              if (`G_GRD == `P_LC && al[8:0] != `S3_WP) begin
                if (!`P_M0F) begin `P_M0 <= `P_Q; `P_M0F <= 1'b1; end
                else begin
                  `P_TWO <= 1'b1;
                  if (`P_OK) begin
                    `P_PM <= `P_Q + 9'd1; `P_PZ <= `P_M0 + 9'd1; `P_J_W((`P_LC)) `T3((P_D1));
                  end
                end
              end
            end
            P_D1:   begin `G_RA <= `P_PM; `G_RRET <= P_D2; `T3((G_RD)); end
            P_D2:   begin `G_CB <= `G_GRD; `G_RA <= `P_PZ; `G_RRET <= P_D3; `T3((G_RD)); end
            P_D3:   begin `G_CB <= `G_CB ^ `G_GRD; `P_BI_W((3'd0)) `T3((P_D4)); end
            P_D4:   begin `P_BI_W((`P_BI + 3'd1)) if (`P_BI == 3'd7) `T3((P_D5)); end
            P_D5: begin
              `P_PM <= `P_PM + 9'd1; `P_PZ <= `P_PZ + 9'd1;
              if (`P_J == 8'd1) `T3((P_D6)); else begin `P_J_W((`P_J - 8'd1)) `T3((P_D1)); end
            end
            P_D6:   begin if (`P_A != 33'd0) `P_OK <= 1'b0; `T3((P_G1)); end
            P_G5:   if (`P_TWO && `P_OK) begin
                      if (`P_NV == 2'd0) begin `P_A1 <= `P_M0; `P_NV_W((2'd1)) `T3((P_E0)); end
                      else begin `P_A2_W((`P_M0)) `T3((P_P0)); end
                    end else `T3((P_E0));
            // ---- P' = x^(8 L1) + x^(8 L2) mod g: a register shifting zeros from 1 ----
            P_P0:   begin `G_RA <= `P_A1; `G_RRET <= P_P1; `T3((G_RD)); end
            P_P1:   begin `P_J_W((`G_GRD)) `P_BI_W((3'd0)) `T3((P_P2)); end
            P_P2: begin
              `P_BI_W((`P_BI + 3'd1))
              if (`P_BI == 3'd7) begin if (`P_J == 8'd1) `T3((P_P3)); else `P_J_W((`P_J - 8'd1)) end
            end
            P_P3:   begin `G_RA <= `P_A2; `G_RRET <= P_P4; `T3((G_RD)); end
            P_P4:   begin `P_J_W((`G_GRD)) `P_BI_W((3'd0)) `T3((P_P5)); end
            P_P5: begin
              `P_BI_W((`P_BI + 3'd1))
              if (`P_BI == 3'd7) begin if (`P_J == 8'd1) `T3((P_P6)); else `P_J_W((`P_J - 8'd1)) end
            end
            P_P6:   begin `P_YF <= 1'b0; `G_RA <= `P_A1; `G_RRET <= P_Y1; `T3((G_RD)); end
            // ---- y' = reg(m1) ^ reg(m2), whole frames ----
            P_Y1:   begin `P_J_W((`G_GRD)) `G_RA <= `G_RA + 9'd1; `T3((P_Y2)); end
            P_Y2:   begin `G_RRET <= P_Y3; `T3((G_RD)); end
            P_Y3:   begin `G_CB <= `G_GRD; `P_BI_W((3'd0)) `T3((P_Y4)); end
            P_Y4:   begin `P_BI_W((`P_BI + 3'd1)) if (`P_BI == 3'd7) `T3((P_Y5)); end
            P_Y5: begin
              `G_RA <= `G_RA + 9'd1;
              if (`P_J == 8'd1) `T3((P_Y6)); else begin `P_J_W((`P_J - 8'd1)) `T3((P_Y2)); end
            end
            P_Y6:   if (!`P_YF) begin `P_YF <= 1'b1; `G_RA <= `P_A2; `G_RRET <= P_Y1; `T3((G_RD)); end
                    else begin
                      `T3((P_S0));
                    end
            // ---- the binary gcd as a modular division (one step a cycle) ----
            // (a even: halve a, u / x mod g; else swap so a >= b; then a ^= b, u ^= v --
            //  the operations, pa_op .. pv_op)
            P_S0:   if (`P_A == 33'd0) `T3((P_V0));
            // u = 0, or no init solves; q = v / h (h | v, or none); f = g / h; init = q mod f
            P_V0:   if (p_uu != 33'd0) begin `T3((P_F)); s3_why <= 4'd5; end
                    else begin `P_KER <= (`P_B != 33'd1); `P_J_W((8'd32)) `T3((P_V1)); end
            P_V1, P_V3, P_V5:                                              // the steps: the operations
                    if (`P_J == 8'd1) `T3((t3 + 7'd1)); else `P_J_W((`P_J - 8'd1))
            P_V2:   if (`P_A != 33'd0) begin `T3((P_F)); s3_why <= 4'd5; end
                    else begin `P_J_W((8'd33)) `T3((P_V3)); end
            P_V4:   begin `P_J_W((8'd32)) `T3((P_V5)); end
            // ---- init is a; xorout = c1 ^ reg(d1, init) ----
            P_V6:   begin `P_IO <= 1'b1; `P_YF <= 1'b0; `G_RA <= `P_A1; `G_RRET <= P_X1; `T3((G_RD)); end
            P_X1:   begin `P_J_W((`G_GRD - p_nb)) `G_RA <= `G_RA + 9'd1; `T3((P_X2)); end
            P_X2:   begin `G_RRET <= P_X3; `T3((G_RD)); end
            P_X3:   begin `G_CB <= `G_GRD; `P_BI_W((3'd0)) `T3((P_X4)); end
            P_X4:   begin
              `P_BI_W((`P_BI + 3'd1)) if (`P_BI == 3'd7) `T3((P_X5));
            end
            P_X5: begin
              `G_RA <= `G_RA + 9'd1;
              if (`P_J != 8'd1) begin `P_J_W((`P_J - 8'd1)) `T3((P_X2)); end
              else if (!`P_YF) begin `P_YF <= 1'b1; `P_J_W((p_nb)) `T3((P_X2)); end
              else `T3((P_W0));
            end
            P_F:    begin `P_IO <= 1'b0; `P_KER <= 1'b0; `T3((P_W0)); end
            // ---- the record, LAST (option (a)): byte 0's io / kernel bits; 128..135 ----
            P_W0:   begin `G_RA <= 9'd120; `G_RRET <= P_W1; `T3((G_RD)); end
            P_W1: begin
              we <= 1'b1; waddr <= 9'd120; wdata <= `G_GRD | {`P_IO & `P_KER, 1'b0, `P_IO, 5'd0};
              `P_J_W((8'd0)) `T3((P_W2));
            end
            P_W2: begin
              we <= 1'b1; waddr <= 9'd128 + {1'b0, `P_J}; `P_J_W((`P_J + 8'd1))
              // init unsolved: 128..135 are zero but for the reason code (128, bits 3..0)
              wdata <= !`P_IO ? ((`P_J == 8'd0) ? {4'd0, s3_why} : 8'd0)
                       : (`P_J < 8'd4) ? dv_q[7:0] : acc[16:9];
              if (`P_J == 8'd7) `T3((T_DONE));
            end
            // a store read: data 2 cycles after the request
            G_RD:   begin re <= 1'b1; `T3((G_RW)); end
            G_RW:   `T3((G_RV));
            G_RV:   begin `G_GRD <= rdata; `T3((`G_RRET)); end
            default: begin done <= 1'b1; st <= S_IDLE; end      // T_DONE
          endcase
          // piece 3's a, b, u, v: one write each, its operation chosen above
          if (pa_op != PA_HOLD) `P_A <= pa_nx;
          if (pb_op != PB_HOLD) `P_B_W((pb_nx))
          if (pu_op_hi != PU_HOLD) dv_d[12:0] <= pu_nx_hi >> 20;
          if (pu_op_lo != PU_HOLD) dv_r[23:4] <= pu_nx_lo;
          // §2: the divisor's top, the step before each loop (d is fixed through it)
`ifdef M_DIVMASK_LATE
          if (f3[F_V1] | f3[F_V3]) p_dm <= top1(`P_B);
          else if (f3[F_V5]) p_dm <= top1(`P_U);
`else
          if (f3[F_V0] | f3[F_V2]) p_dm <= top1(`P_B);
          else if (f3[F_V4]) p_dm <= top1(`P_U);
`endif
          if (pv_op != PV_HOLD) `P_V_W((pv_nx))
        end
        default: st <= S_IDLE;
      endcase
    end
  end
  wire _unused = &{1'b0, rival};
`ifndef SYNTHESIS
`ifndef PE_S12_NOASSERT
  // ⛔ THE s12 NOTE'S PROOFS, EVERY CYCLE (the PIT suite runs with them on). A
  // failure STOPS the run, so no runner can read past it as a pass.
  // PE_S12_NOASSERT exists ONLY for run_pit_gcd's must-fire, which must show a
  // mutant breaks the RECORD itself, not merely trips the assertion.
  //  §1: the flags are the decode of the CURRENT t3 (zero cycles, by construction).
  //  §2: on a division step the mask test equals THE compare it replaced.
  //  §3: pe_s3_opsel's codes are this module's.
  // ⛔ ONLY AFTER A RESET HAS BEEN SEEN (11-12). `rst_n === 1'b1` alone held
  // in iverilog (registers start X) but not in Verilator, which has no X:
  // there rst_n reads 1 before the bench drives reset, t3 and f3 hold
  // arbitrary values, and s12-1 stopped the LN1 export at 8 ns (CI 43305666324).
  reg s12_rst_seen = 1'b0;
  always @(posedge clk or negedge rst_n)
    if (rst_n === 1'b0) s12_rst_seen <= 1'b1;
  always @(posedge clk)
    if (s12_rst_seen && rst_n === 1'b1 && f3 !== t3fl(t3)) begin
      $display("*** ASSERT pe_pit_s12 s12-1: f3 %b is not the decode of t3 = %0d (%b)", f3, t3, t3fl(t3));
      $finish;
    end
  always @(posedge clk)
    if (s12_rst_seen && rst_n === 1'b1 && run && st == S_S3 && f3[F_DV] && p_lt_div !== ((p_ri ^ p_d) < p_ri)) begin
      $display("*** ASSERT pe_pit_s12 s12-2: mask test %b != (r ^ d) < r at t3 = %0d", p_lt_div, t3);
      $finish;
    end
  //  §4: the tree compare equals `<` (11-12)
  always @(posedge clk)
    if (s12_rst_seen && rst_n === 1'b1 && run && st == S_S3 && p_lt_s0 !== (`P_A < `P_B)) begin
      $display("*** ASSERT pe_pit_s12 s12-4: lt33 %b != (P_A < P_B) at t3 = %0d", p_lt_s0, t3);
      $finish;
    end
  initial
    if (u_ops_a.PA_SHX != PA_SHX || u_ops_a.PA_SH != PA_SH || u_ops_a.PA_XB != PA_XB ||
        u_ops_a.PA_B != PA_B || u_ops_a.PA_S8 != PA_S8 || u_ops_a.PA_ONE != PA_ONE ||
        u_ops_a.PA_ZERO != PA_ZERO || u_ops_a.PB_A != PB_A || u_ops_a.PB_XA != PB_XA ||
        u_ops_a.PB_GF != PB_GF || u_ops_a.PB_ZERO != PB_ZERO || u_ops_a.PB_S8 != PB_S8 ||
        u_ops_a.PU_HALF != PU_HALF || u_ops_a.PU_V != PU_V || u_ops_a.PU_XV != PU_XV ||
        u_ops_a.PU_GF != PU_GF || u_ops_a.PU_DIV != PU_DIV || u_ops_a.PV_A != PV_A ||
        u_ops_a.PV_ZERO != PV_ZERO || u_ops_a.PV_U != PV_U || u_ops_a.PV_DIV != PV_DIV) begin
      $display("*** ASSERT pe_pit_s12 s12-3: pe_s3_opsel's op codes differ from pe_pit_s12's");
      $finish;
    end
`endif
`endif
`undef S3_X
`undef S3_LQ
`undef S3_P30
`undef S3_SA
`undef S3_FB
`undef S3_OPEN
`undef S3_MBYTE
`undef S3_E
`undef S3_TOT
`undef S3_FL
`undef S3_CLEN
`undef S3_BY
`undef S3_MLEN
`undef S3_WP
`undef S3_LA
`undef S3_BI
`undef S3_HLE
`undef S3_CUR
`undef S3_L
`undef S3_IDLE
`undef G_RA
`undef G_DX
`undef G_DY
`undef G_DN
`undef G_TZ
`undef G_CB
`undef G_GRD
`undef G_RRET
`undef G_J
`undef G_K
`undef G_S
`undef G_HP
`undef G_Q
`undef G_A
`undef G_BB
`undef G_LEN
`undef G_CNT
`undef G_USED
`undef G_SRET
`undef G_BU
`undef G_LSB
`undef G_GV
`undef G_YS
`undef G_XS
`undef G_NZ
`undef G_PAST
`undef G_NF
`undef G_NX0
`undef G_BF
`undef G_BL
`undef P_A
`undef P_V
`undef P_B
`undef P_U
`undef P_G
`undef P_A1
`undef P_A2
`undef P_J
`undef P_BI
`undef P_NV
`undef P_OK
`undef P_KER
`undef P_IO
`undef P_YF
`undef P_LSB
`undef P_WC
`undef P_LP
`undef P_LC
`undef P_Q
`undef P_M0
`undef P_PM
`undef P_M0F
`undef P_TWO
`undef P_PZ
`undef P_V_W
`undef P_B_W
`undef P_U_W
`undef P_G_W
`undef P_A2_W
`undef P_J_W
`undef P_BI_W
`undef P_NV_W
`undef T3
endmodule

// ---------------------------------------------------------------------------
// pe_s3_opsel -- pe_pit_s12 piece 3's operation select (s12 note §3, Wilson
// 11-09): which of a / b / u / v each step writes, and how. (* keep_hierarchy *)
// so the THREE instances (one per register group) survive opt_merge, as
// pe_dup_ff does. Deliberately NOT parameterised (a kept `$paramod` reads as an
// unmapped cell to LibreLane). Its inputs are pe_pit_s12's REGISTERED step
// flags (§1), never t3. ⛔ THE CODES MUST EQUAL pe_pit_s12's PA_/PB_/PU_/PV_
// localparams: pe_pit_s12 checks them at time 0 in simulation (s12-3).
//   f  = {G2, SHX, ONE, ZERO, PBA, P6, Y6, S0, V2, F}   fx = {V1|V5, V3, W2}
// ---------------------------------------------------------------------------
// (Wilson 11-12, the copy-mechanism ruling) keep_hierarchy RESTORED: (* keep *)
// on the select nets did not hold on LibreLane 3.1.0.dev4 (6 merged); this does
// (0). model/gate_select_copies.py holds it; its must-fire strips this line.
(* keep_hierarchy *)
module pe_s3_opsel (
    input  wire       s3,
    input  wire [9:0] f,
    input  wire [2:0] fx,
    input  wire       g2,      // P_G2's data condition
    input  wire       yf,      // P_YF
    input  wire       anz,     // P_A != 0
    input  wire       aodd,    // a's low bit (acc[9])
    input  wire       lt,      // the swap test, P_A < P_B
    input  wire       j4,      // P_J < 4
    output reg  [3:0] pa_op,
    output reg  [2:0] pb_op,
    output reg  [2:0] pu_op,
    output reg  [2:0] pv_op
);
  localparam [3:0] PA_HOLD = 4'd0, PA_ZERO = 4'd1, PA_ONE = 4'd2, PA_SHX = 4'd3,
                   PA_B = 4'd5, PA_XB = 4'd6, PA_SH = 4'd7, PA_S8 = 4'd9;
  localparam [2:0] PB_HOLD = 3'd0, PB_A = 3'd1, PB_XA = 3'd2, PB_GF = 3'd3, PB_ZERO = 3'd4, PB_S8 = 3'd5;
  localparam [2:0] PU_HOLD = 3'd0, PU_HALF = 3'd2, PU_V = 3'd3, PU_XV = 3'd4, PU_GF = 3'd5,
                   PU_DIV = 3'd6;
  localparam [2:0] PV_HOLD = 3'd0, PV_A = 3'd1, PV_ZERO = 3'd2, PV_U = 3'd3, PV_DIV = 3'd4;
  wire f_g2 = f[9], f_shx = f[8], f_one = f[7], f_zero = f[6], f_pba = f[5], f_p6 = f[4],
       f_y6 = f[3], f_s0 = f[2], f_v2 = f[1], f_f = f[0];
  wire f_v15 = fx[2], f_v3 = fx[1], f_w2 = fx[0];
  // the old `case (t3)`: its items are distinct steps, so its flags are exclusive
  always @(*) begin
    pa_op = PA_HOLD; pb_op = PB_HOLD; pu_op = PU_HOLD; pv_op = PV_HOLD;
    if (s3) begin
      if (f_g2) begin if (g2) pa_op = PA_ZERO; end
      else if (f_shx) pa_op = PA_SHX;
      else if (f_one) pa_op = PA_ONE;
      else if (f_zero) pa_op = PA_ZERO;
      else if (f_pba) pb_op = PB_A;
      else if (f_p6) pb_op = PB_XA;
      else if (f_y6) begin
        if (!yf) pv_op = PV_A;
        else begin pu_op = PU_XV; pa_op = PA_B; pb_op = PB_GF; pv_op = PV_ZERO; end
      end
      else if (f_s0) begin
        if (anz) begin
          if (!aodd) begin pa_op = PA_SH; pu_op = PU_HALF; end                            // a even
          else if (lt) begin pa_op = PA_B; pb_op = PB_A; pu_op = PU_V; pv_op = PV_U; end   // swap
          else begin pa_op = PA_XB; pu_op = PU_XV; end
        end
      end
      else if (f_v15) begin pa_op = PA_SHX; pv_op = PV_DIV; end
      else if (f_v3) begin pa_op = PA_SHX; pu_op = PU_DIV; end
      else if (f_v2) begin pa_op = PA_ZERO; pu_op = PU_GF; end
      else if (f_f) begin pa_op = PA_ZERO; pb_op = PB_ZERO; end
      else if (f_w2) begin if (j4) pb_op = PB_S8; else pa_op = PA_S8; end
    end
  end
endmodule


// pe_dup_ff -- ONE resettable flop that synthesis may NOT merge with its twins
// (step 1b, 10-27). (* keep_hierarchy *) keeps each instance a module through
// `flatten`, so yosys's opt_merge cannot fold identical copies back into one
// flop (measured: `keep` on a reg or an instance does not stop it). Used to
// REPLICATE a high-fanout mode signal (prog_mode) so each copy drives a local
// load instead of one buffer tree across the store.
// ---------------------------------------------------------------------------
(* keep_hierarchy *)
module pe_dup_ff (
    input  wire clk,
    input  wire rst_n,
    input  wire d,
    output reg  q
);
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) q <= 1'b0;
    else        q <= d;
  end
endmodule

// pe_dup_ff with a load enable (v2 slack recovery step 2: pe_engine's
// g_wraddr, one per address bit per bank). Deliberately NOT parameterised:
// a kept `$paramod` module reads as an unmapped cell to LibreLane.
(* keep_hierarchy *)
module pe_dup_ffe (input wire clk, input wire rst_n, input wire en,
                   input wire d, output reg q);
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) q <= 1'b0;
    else if (en) q <= d;
  end
endmodule

// =========================================================================
// v2 PIT, chunk 1 (Wilson 10-28): the SNIFF-mode capture. Records every change
// of the masked uio wires (after the existing 2-flop sync) as (interval since
// the previous record, changed-mask) into store bytes 128..511: the first 16
// raw (16 + 8 bits), then the Rice parameter k (4 bits), then Golomb-Rice
// records (q = I >> k unary, k low bits, the mask; q >= 16 escapes to 16 ones +
// the raw 16 bits). A 64-bit accumulator drains one byte per cycle; a record
// that does not fit it (OVERRUN) or the store (FULL) stops the capture, and the
// status (overflow, record count) is written to bytes 2, 28, 29 once drained.
// Bit-exact golden: pit/pit_capture_golden.py (internal), checked by
// test/run_pit_capture.py. Off every engine path: its inputs are uio_q1 and
// its own registers; its output is the store's byte write port.
// =========================================================================
module pe_pit #(parameter integer AW = 9) (
    input  wire          clk,
    input  wire          rst_n,
    input  wire          run,          // SNIFF mode, running
    input  wire [7:0]    uio,          // the synchronised uio bus
    input  wire [7:0]    mask_cfg,     // store byte 0 (0 = all 8 wires)
    input  wire [7:0]    bud_cfg,      // store byte 1: budget 2^b cycles (0 = off)
    output reg           we,
    output reg  [AW-1:0] waddr,
    output reg  [7:0]    wdata,
    output reg           stopped,
    // stage 0's inputs (chunk 2): the capture is done, its whole count, its start levels
    output wire          cap_done,
    output wire [13:0]   cap_n,
    output reg  [7:0]    cap_lv0,
    // ⭐ THE SECOND CAPTURE (Wilson 11-06): stage 3 found no UART wire but stage 0
    // named a clocked bus -- look again, SAMPLED: one bit per sample edge of the
    // data wire, written as the decoded messages, [len][bytes] from 128
    input  wire          ck_arm,       // pulse: cycle 0 of the second capture
    input  wire          ck_i2c,       // 1 = I2C (START / STOP frames), 0 = SPI (CS frames)
    input  wire [2:0]    ck_c, ck_d, ck_f,   // clock, data, CS wires
    input  wire          ck_act,       // CS's active level
    input  wire          ck_edge,      // the sample edge: 1 = rise, 0 = fall
    output reg           ck_done,
    output reg  [AW-1:0] ck_wp,        // the end of the messages
    output reg  [7:0]    ck_nmsg       // frames stored (sat 255)
);
  localparam integer CAP_BASE = 128, CAP_BITS = 384 * 8;
  localparam integer SLV_AT = 39;   // the starting-levels byte (results 32-39)
  // named widths: the interval / record counters (16 bits) and the k-choice
  // product (24) -- no bare protocol-looking literal in the RTL
  localparam integer CW = 16, MW = 24;
  // the capture limit as an UNSIGNED 17-bit value, the width `total + l_all` has
  localparam [16:0] CAP_LIM = CAP_BITS;
  // ⭐ THE BUDGET STOP (Wilson 10-29): "listened for as long as asked" -- a
  // NORMAL completion, not PARTIAL. b = image byte 1: 0 = off (every older
  // SNIFF image), 1 .. BMAX = 2^b cycles (b = 6 ~ 1 us .. 35 ~ 9.5 min at
  // 60 MHz), larger b clamps. A DOWN-counter loaded with 2^b - 1 at the PIT's
  // cycle 0 expires exactly at cycle 2^b -- no 36-bit variable shift (the
  // barrel-shifter lesson of chunk 1's area). An edge AT cycle 2^b is not
  // recorded: the budget is checked first.
  localparam integer BW = 36, BMAX = BW - 1;
  localparam [7:0] BMAX8 = BMAX;   // unsigned, the width bud_cfg has
  wire [5:0]    bsel   = (bud_cfg > BMAX8) ? BMAX8[5:0] : bud_cfg[5:0];
  wire          bud_en = (bud_cfg != 8'h00);
  reg  [BW-1:0] bud_cnt;
  // ⛔ THE RELOAD VALUE IN ITS OWN REGISTER (canary 10-30). Computed inside the
  // `!active` branch, `1 << bsel` was mutually exclusive with the record
  // builder's `<< ke` / `>> ke`, and yosys's `share` pass merged them into ONE
  // shifter with muxed inputs: bud_cnt's next state then carried k's whole
  // record-building path (k -> bud_cnt, +2.107 ns, the second-worst family).
  // bud_cfg is store byte 1, fixed long before the PIT starts, so a register
  // that follows it every cycle holds the same value -- and shares nothing.
  reg  [BW-1:0] bud_init;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) bud_init <= {BW{1'b0}};
    else        bud_init <= ({{(BW-1){1'b0}}, 1'b1} << bsel) - {{(BW-1){1'b0}}, 1'b1};
  reg           why_bud;
`ifdef M_PIT_NO_BUDGET
  wire          bud_hit = 1'b0;
`else
  wire          bud_hit = bud_en & (bud_cnt == {BW{1'b0}});
`endif
  wire [7:0] m = (mask_cfg == 8'h00) ? 8'hFF : mask_cfg;
  reg        active;
  reg [7:0]  prev;
  reg [CW-1:0] tcnt, n;
  reg [63:0] acc;
  reg [6:0]  acc_n;
  reg [11:0] total;
  reg [19:0] sum;
  reg [3:0]  k;
  reg [8:0]  wr_idx;
  reg [1:0]  st_phase;
  reg        st_done;
  // ⭐ the STOP REASON (Nate 10-28): 1 = OVERRUN (the accumulator would
  // overflow: the bus outran the drain), 0 = FULL (the store is used up)
  reg        why_ovr;
  wire [7:0]  chg   = (uio ^ prev) & m;
`ifdef M_PIT_MASK_DROP
  wire [7:0]  rmask = chg & 8'hFE;
`else
  wire [7:0]  rmask = chg;
`endif
`ifdef M_PIT_K_OFF1
  wire [4:0]  ke    = {1'b0, k} + 5'd1;
`else
  wire [4:0]  ke    = {1'b0, k};
`endif
  wire        rawr  = (n < 16'd16);
  wire [CW-1:0] q   = tcnt >> ke;
  wire        esc   = (q >= 16'd16);
  wire [63:0] kmask = (64'd1 << ke) - 64'd1;
  wire [63:0] unary = ((64'd1 << q[4:0]) - 64'd1) << 1;           // q ones, then a 0
  wire [63:0] v_raw = {40'd0, tcnt, rmask};
  wire [63:0] v_esc = {24'd0, 16'hFFFF, tcnt, rmask};
  wire [63:0] v_gr  = ((((unary << ke) | ({48'd0, tcnt} & kmask)) << 8) | {56'd0, rmask});
  wire [6:0]  l_gr  = {2'b0, q[4:0]} + 7'd1 + {2'b0, ke} + 7'd8;
  wire [63:0] v_rec = rawr ? v_raw : esc ? v_esc : v_gr;
  wire [6:0]  l_rec = rawr ? 7'd24 : esc ? 7'd40 : l_gr;
  wire [CW-1:0] n_whole = n - {{(CW-1){1'b0}}, (total[2:0] != 3'd0)};
  assign      cap_done = st_done;
  assign      cap_n    = n_whole[13:0];
  wire        kpre  = (n == 16'd16);                                // k precedes the first coded record
  wire [63:0] v_all = kpre ? (v_rec | ({60'd0, k} << l_rec)) : v_rec;
  wire [6:0]  l_all = kpre ? l_rec + 7'd4 : l_rec;
  // the drain happens first each cycle; the record goes in after it
  wire        drain   = (acc_n >= 7'd8);
  wire [63:0] acc_d   = drain ? (acc << 8) : acc;
  wire [6:0]  acc_n_d = drain ? acc_n - 7'd8 : acc_n;
`ifdef M_PIT_NO_OVERRUN
  wire        room  = ({5'd0, total} + {10'd0, l_all} <= CAP_LIM);
`else
  wire        room  = ({1'b0, acc_n_d} + {1'b0, l_all} <= 8'd64) &&
                      ({5'd0, total} + {10'd0, l_all} <= CAP_LIM);
`endif
`ifdef M_PIT_WHY_DROP
  wire        ovr   = 1'b0;
`else
  wire        ovr   = ({1'b0, acc_n_d} + {1'b0, l_all} > 8'd64);
`endif
  // ---- THE SECOND CAPTURE, sampled (golden sampled_capture, frozen 81ae9563).
  // It runs after the first capture stopped, through the same write port and
  // budget counter (reloaded at its cycle 0). Per cycle, from prev -> uio:
  //   SPI: CS going inactive closes the frame; else a sample edge while open
  //        shifts in the data level of the cycle BEFORE the edge (MSB-first);
  //        CS going active opens a frame.
  //   I2C: SDA moving with SCL high before and after is START (opens; closes
  //        any open frame first: a repeated START) or STOP (closes). A bit
  //        sampled on SCL's rise counts on its next fall; the 9th (ACK) of
  //        each 9 is dropped.
  //   A close KEEPS the frame only with >= 1 byte and no partial byte: its
  //   length goes to its slot. A whole byte that would pass 383 stops it
  //   ("full", the open frame dropped), as the budget does.
  localparam [9:0] S_END = 10'd384;   // 128..383: the GCD's two buffers keep 384..511
  reg         s_on, s_open, s_pv, s_pend;
  reg [AW-1:0] s_la;
  reg [7:0]   s_mlen, s_byte;
  reg [3:0]   s_nbit;
  wire        s_pc   = prev[ck_c], s_cn = uio[ck_c];
  wire        s_cch  = s_pc ^ s_cn;
  wire        s_dch  = prev[ck_d] ^ uio[ck_d];
  wire        s_fch  = prev[ck_f] ^ uio[ck_f];
  wire        s_ev   = ck_i2c & s_dch & s_pc & s_cn;
`ifdef M_CK_CS_INV
  wire        s_actv = ~ck_act;
`else
  wire        s_actv = ck_act;
`endif
`ifdef M_CK_NO_SR
  wire        s_close = ck_i2c ? (s_ev & uio[ck_d]) : (s_fch & (uio[ck_f] != s_actv));
  wire        s_openv = ck_i2c ? (s_ev & ~uio[ck_d] & ~s_open) : (s_fch & (uio[ck_f] == s_actv));
`else
  wire        s_close = ck_i2c ? s_ev : (s_fch & (uio[ck_f] != s_actv));
  wire        s_openv = ck_i2c ? (s_ev & ~uio[ck_d]) : (s_fch & (uio[ck_f] == s_actv));
`endif
`ifdef M_CK_EDGE_INV
  wire        s_edge = ~ck_edge;
`else
  wire        s_edge = ck_edge;
`endif
  wire        s_bit  = ck_i2c ? (~s_ev & s_cch & ~s_cn & s_pv)
                              : (~s_close & s_cch & (s_cn == s_edge) & s_open);
  wire        s_bv   = ck_i2c ? s_pend : prev[ck_d];
  wire [3:0]  s_nb_n = s_nbit + 4'd1;
`ifdef M_CK_ACK_KEEP
  wire [3:0]  s_unit = 4'd8;
`else
  wire [3:0]  s_unit = ck_i2c ? 4'd9 : 4'd8;
`endif
`ifdef M_CK_LSB
  wire [7:0]  s_by_n = (s_nbit < 4'd8) ? {s_bv, s_byte[7:1]} : s_byte;
`else
  wire [7:0]  s_by_n = (s_nbit < 4'd8) ? {s_byte[6:0], s_bv} : s_byte;
`endif
  wire        s_keep = s_close & s_open & (s_mlen != 8'd0) & (s_nbit == 4'd0);
  wire [AW-1:0] s_end = s_la + {{(AW-1){1'b0}}, 1'b1} + {1'b0, s_mlen};   // the next free byte
  wire        s_whole = s_bit & s_open & (s_nb_n == s_unit);
  wire        s_full  = s_whole & ({1'b0, s_end} + 10'd1 > S_END);
  wire [19:0] sum_n = sum + {4'd0, tcnt};
  wire [19:0] mean  = sum_n >> 4;
  wire [MW-1:0] v11 = ({4'd0, mean} * 24'd11) >> 4;
  reg  [3:0]  k_new;
  integer     bi;
  always @(*) begin
    k_new = 4'd0;
    for (bi = 0; bi < 16; bi = bi + 1)
      if (v11[bi]) k_new = bi[3:0];
  end
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      active <= 1'b0; prev <= 8'h00; tcnt <= 16'd0; n <= 16'd0; acc <= 64'd0;
      acc_n <= 7'd0; total <= 12'd0; sum <= 20'd0; k <= 4'd0; wr_idx <= 9'd0;
      st_phase <= 2'd0; st_done <= 1'b0; stopped <= 1'b0; why_ovr <= 1'b0;
      why_bud <= 1'b0; bud_cnt <= {BW{1'b0}}; cap_lv0 <= 8'h00;
      we <= 1'b0; waddr <= {AW{1'b0}}; wdata <= 8'h00;
      s_on <= 1'b0; s_open <= 1'b0; s_pv <= 1'b0; s_pend <= 1'b0; s_la <= {AW{1'b0}};
      s_mlen <= 8'd0; s_byte <= 8'd0; s_nbit <= 4'd0;
      ck_done <= 1'b0; ck_wp <= {AW{1'b0}}; ck_nmsg <= 8'd0;
    end else if (!run) begin
      active <= 1'b0;
      we <= 1'b0;
      s_on <= 1'b0; ck_done <= 1'b0;
    end else if (!active) begin
      // the PIT's cycle 0: take the levels, start the interval
      active <= 1'b1; prev <= uio; tcnt <= 16'd1; n <= 16'd0; acc <= 64'd0;
      acc_n <= 7'd0; total <= 12'd0; sum <= 20'd0; k <= 4'd0; wr_idx <= 9'd0;
      st_phase <= 2'd0; st_done <= 1'b0; stopped <= 1'b0; why_ovr <= 1'b0;
      why_bud <= 1'b0;
      bud_cnt <= bud_init;
      // ⭐ THE STARTING LEVELS (Wilson 10-29): stage 0 reads ABSOLUTE levels,
      // and the records carry only changes -- byte 39 = uio & mask here.
      we <= 1'b1; waddr <= SLV_AT[AW-1:0];
`ifdef M_PIT_LV0_INV
      wdata <= (uio & m) ^ 8'h01;
      cap_lv0 <= (uio & m) ^ 8'h01;
`else
      wdata <= uio & m;
      cap_lv0 <= uio & m;
`endif
    end else begin
      prev <= uio;
      we <= 1'b0;
      if (bud_cnt != {BW{1'b0}}) bud_cnt <= bud_cnt - {{(BW-1){1'b0}}, 1'b1};
      if (bud_hit && !stopped) begin
        stopped <= 1'b1;
        why_bud <= 1'b1;
      end
      if (drain) begin
        we    <= 1'b1;
        waddr <= CAP_BASE[AW-1:0] + wr_idx;
        wdata <= acc[63:56];
        wr_idx <= wr_idx + 9'd1;
      end
      acc   <= acc_d;
      acc_n <= acc_n_d;
`ifdef M_PIT_NO_SAT
      tcnt  <= tcnt + 16'd1;
`else
      tcnt  <= (tcnt == 16'hFFFF) ? tcnt : tcnt + 16'd1;   // an idle bus saturates
`endif
      if (chg != 8'h00 && !stopped && !bud_hit) begin
        if (room) begin
          acc   <= acc_d | (v_all << (7'd64 - acc_n_d - l_all));
          acc_n <= acc_n_d + l_all;
          total <= total + {5'd0, l_all};
          n     <= n + 16'd1;
          tcnt  <= 16'd1;
          if (rawr) sum <= sum_n;
          if (n == 16'd15) k <= k_new;
        end else begin
          stopped <= 1'b1;
          why_ovr <= ovr;
        end
      end
      // the status, once stopped and drained (every stop, budget included):
      // byte 2 bit 7 = TRUNCATED (FULL / OVERRUN: every result PARTIAL; a
      // budget stop is a normal completion), byte 28 bit 7 = overrun, bit 6 =
      // budget, {28[5:0], 29} = WHOLE records -- the last record is cut when
      // the bit total is not byte-aligned (every record is >= 9 bits, so at
      // most one), and the count excludes it (Wilson 10-29).
      if (stopped && !drain && !st_done) begin
        we <= 1'b1;
        case (st_phase)
          2'd0: begin waddr <= 9'd2;  wdata <= why_bud ? 8'h00 : 8'h80; end
          2'd1: begin waddr <= 9'd28; wdata <= {why_ovr, why_bud, n_whole[13:8]}; end
          default: begin waddr <= 9'd29; wdata <= n_whole[7:0]; st_done <= 1'b1; end
        endcase
        st_phase <= st_phase + 2'd1;
      end
      // ---- the second capture (after st_done: the first one's writes are over) ----
      if (ck_arm) begin                                  // its cycle 0: prev <= uio above
        s_on <= 1'b1; s_open <= 1'b0; s_pv <= 1'b0; s_nbit <= 4'd0; s_byte <= 8'd0;
        ck_done <= 1'b0; ck_wp <= CAP_BASE[AW-1:0]; ck_nmsg <= 8'd0;
        bud_cnt <= bud_init;
      end else if (s_on) begin
        if (bud_hit || s_full) begin                     // the budget (edges at 2^b unseen) or full
          s_on <= 1'b0; ck_done <= 1'b1;
        end else begin
          if (ck_i2c) begin
            if (s_ev) s_pv <= 1'b0;
            else if (s_cch && s_cn && s_open) begin s_pv <= 1'b1; s_pend <= prev[ck_d]; end
            else if (s_bit) s_pv <= 1'b0;
          end
          if (s_bit) begin s_nbit <= s_nb_n; s_byte <= s_by_n; end
          if (s_whole) begin                             // a whole byte -> its slot
            we <= 1'b1; waddr <= s_end; wdata <= s_by_n;
            s_mlen <= s_mlen + 8'd1; s_nbit <= 4'd0; s_byte <= 8'd0;
          end
          if (s_close) begin
            s_open <= 1'b0;
            if (s_keep) begin                            // the length, into the frame's slot
              we <= 1'b1; waddr <= s_la; wdata <= s_mlen;
              ck_wp <= s_end;
              if (ck_nmsg != 8'hFF) ck_nmsg <= ck_nmsg + 8'd1;
            end
          end
          if (s_openv) begin
            s_open <= 1'b1; s_la <= s_keep ? s_end : ck_wp;
            s_mlen <= 8'd0; s_nbit <= 4'd0; s_byte <= 8'd0;
          end
        end
      end
    end
  end
endmodule
