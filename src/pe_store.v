/*
 * Copyright (c) 2026 Nathan Humphrey
 * SPDX-License-Identifier: Apache-2.0
 *
 * THE PROGRAM STORE -- byte-wide, 2**AW deep, with MEM_TYPE selecting the
 * implementation and NOTHING ELSE changing.
 *
 * ⭐ MEM_TYPE IS NOT TIDINESS. It is the parameter that keeps two evidence
 * paths alive at once:
 *   "flops"  a register array. Hardenable at ANY node, so the Nangate45 and
 *            ASAP7 predictive-node runs can be built. ⭐ AND IT IS THE SHIPPED
 *            DEFAULT, because S0 found the CMOS5L PDN verticals are on Metal4
 *            -- the exact layer the IHP SRAM macro's OBS blocks -- while
 *            TopMetal1.drawing is not on TinyTapeout's CMOS5L precheck
 *            allowlist, so the one layer that could cross the macro cannot be
 *            drawn.
 *   "sram"   a single-port synchronous RAM, coded so a macro can replace it.
 *            ⛔ NO PDK CELL IS NAMED HERE, deliberately: naming one would pin
 *            this RTL to a single PDK and make the predictive-node runs
 *            impossible rather than merely awkward. The macro binding is a
 *            FILE SUBSTITUTION in the flow, not an instance in this file.
 *
 * ⚠ BOTH PATHS ARE SYNCHRONOUS ONE-CYCLE READ, ON PURPOSE. If the flop path
 * were combinational-read and the sram path registered, swapping MEM_TYPE would
 * silently change the pipeline depth -- and the engine's C would change with
 * it. A parameter that changes timing behaviour is not a build option, it is
 * two designs sharing a filename.
 *
 * ⛔ THE READ IS REGISTERED, WHICH IS RULING F2 AND NOT A STYLE CHOICE. The
 * previous design exposed `mem[rd_ptr]` combinationally at `uo_out`, and that
 * path was 18.4388 ns of a 20 ns period -- the only nearly-full path on the
 * chip. Registering it is what takes STORE DEPTH off the critical path, which
 * is in turn what makes AW = 8 affordable where AW = 9 was not.
 */

`default_nettype none

module pe_store #(
    parameter integer AW       = 8,
    parameter         MEM_TYPE = "flops",
    parameter integer WIDE_B   = 3      // bytes per wide read (one action)
) (
    input  wire            clk,
    input  wire            rst_n,
    // write port (program load)
    input  wire            we,
    input  wire [AW-1:0]   waddr,
    input  wire [7:0]      wdata,
    // read port -- SYNCHRONOUS, one cycle
    input  wire            re,
    input  wire [AW-1:0]   raddr,
    output reg  [7:0]      rdata,
    // ⭐⭐ WIDE READ PORT: WIDE_B consecutive bytes in ONE registered cycle.
    // ⛔ THIS EXISTS BECAUSE THE MEASURED JITTER WAS 20 CYCLES AGAINST A2's
    // BUDGET OF 1. A 3-byte action fetched a byte at a time through a shared
    // port costs 9 cycles before contention, and with 5 lanes competing the
    // observed worst case was 20. The prefetch that BOUGHT C = 2 was spending
    // it all back as J.
    // ⭐ AND IT IS ONLY CHEAP BECAUSE S0 BLOCKED THE SRAM. MEM_TYPE = "flops"
    // means the store is a REGISTER ARRAY, so a wider read is a wider MUX and
    // not more storage. A byte-wide SRAM macro could not do this in one cycle.
    // ⚠ SO J DEPENDS ON MEM_TYPE, which breaks this file's own rule that a
    // build parameter must not change timing behaviour. Stated, not hidden:
    // with "flops" J can be ~1; with "sram" J >= 3. The flop path is what
    // ships, so the rule is violated only on a path that is currently blocked.
    input  wire            wre,
    input  wire [AW-1:0]   wraddr,
    output reg  [WIDE_B*8-1:0] wrdata
);

  localparam integer DEPTH = (1 << AW);

  // --------------------------------------------------------------------
  // ⭐ ONE storage array, TWO generate arms that differ only in how they
  // are written -- so the read side cannot diverge between the arms. The
  // "same-author re-derivation is not an independent witness" lesson
  // applies to RTL too: two copies of a read path WILL drift.
  // --------------------------------------------------------------------
  reg [7:0] mem [0:DEPTH-1];

  generate
    if (MEM_TYPE == "sram") begin : g_sram
      // Single-port synchronous RAM shape: write-first is NOT modelled, so a
      // read and write to the same address in one cycle returns OLD data.
      // ⛔ The engine never does that -- load and run are mutually exclusive
      // (HALT, RELOAD, RESUME) -- but it is written down because an SRAM macro
      // would behave this way and the flop arm must not accidentally be nicer.
      always @(posedge clk) begin
        if (we) mem[waddr] <= wdata;
        if (re) rdata      <= mem[raddr];
      end
    end else begin : g_flops
      // Register array. Same timing contract: registered read, one cycle.
      always @(posedge clk) begin
        if (we) mem[waddr] <= wdata;
        if (re) rdata      <= mem[raddr];
      end
    end
  endgenerate

  // ---- the wide read, shared by both arms so they cannot drift ----------
  integer wb;
  always @(posedge clk) begin
    if (wre) begin
      for (wb = 0; wb < WIDE_B; wb = wb + 1)
        wrdata[(WIDE_B-1-wb)*8 +: 8] <= mem[(wraddr + wb[AW-1:0])];
    end
  end

  // ⚠ `rst_n` is intentionally NOT used to clear the array. Clearing 2**AW
  // bytes would add a reset fanout to every storage bit for no benefit: the
  // loader writes the whole image before run mode is entered, and 1.6's
  // load-time screen is what guarantees the image is admissible. Listed so the
  // omission reads as a decision.
  wire _unused_store = &{rst_n, 1'b0};

endmodule
