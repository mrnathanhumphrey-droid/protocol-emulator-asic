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
    parameter integer AW       = 9,
    parameter         MEM_TYPE = "flops",
    parameter integer WIDE_B   = 4      // bytes per wide read (one action word)
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
    input  wire [AW-1:0]   wraddr,     // WORD-aligned (the low WB_W bits are 0)
    output reg  [WIDE_B*8-1:0] wrdata
);

  localparam integer DEPTH = (1 << AW);
  // ⭐⭐ v2 (Wilson ruling on design 5cf27c1f): THE STORE IS WORD-ORGANISED --
  // WIDE_B byte BANKS of NW entries, byte k in bank k % WIDE_B at row
  // k / WIDE_B. Every action read is word-aligned (word w at ACT_BASE + 4w,
  // ACT_BASE a multiple of 4), so the wide read is ONE row of all banks: a
  // NW:1 mux per bank (128:1 at AW = 9), not WIDE_B separate 2**AW:1 byte
  // muxes, and no address adder at all. Only the narrow port (header load)
  // needs byte addressing, and it is the same rows plus a WIDE_B:1 select.
  localparam integer WB_W = (WIDE_B <= 1) ? 1 : (WIDE_B <= 2) ? 1 :
                            (WIDE_B <= 4) ? 2 : 3;
  localparam integer NW   = DEPTH / WIDE_B;
  generate
    if ((1 << WB_W) != WIDE_B) begin : g_wide_pow2
      STORE_WIDE_B_NOT_A_POWER_OF_TWO _static_assert ();
    end
  endgenerate

  // --------------------------------------------------------------------
  // ⭐ ONE storage array, TWO generate arms that differ only in how they
  // are written -- so the read side cannot diverge between the arms. The
  // "same-author re-derivation is not an independent witness" lesson
  // applies to RTL too: two copies of a read path WILL drift.
  // --------------------------------------------------------------------
  // ⚠ ONE array per bank; both MEM_TYPE arms share these and differ only in
  // how they would be bound, so the read side cannot diverge between arms.
  // (The "sram" arm is still blocked -- S0's Metal4 conflict -- and is now
  // WIDE_B narrow banks, which is what a macro binding would see.)
  // ⛔ R1 (Wilson 10-25): TM2's mutant guarded store ADDRESSING; the class
  // survives the adder, so three must-fires replace it: M_STORE_BANK_SWAP
  // (the write bank select wired wrong), M_STORE_ROW_OFF1 (the wide read one
  // row off), M_STORE_WRONG_BANK (bank 3's writes land in bank 0).
`ifdef M_STORE_BANK_SWAP
  wire [WB_W-1:0]    wsel = waddr[WB_W-1:0] ^ {{(WB_W-1){1'b0}}, 1'b1};
`else
  wire [WB_W-1:0]    wsel = waddr[WB_W-1:0];
`endif
  wire [AW-WB_W-1:0] wrow = waddr[AW-1:WB_W];
  wire [WB_W-1:0]    rsel = raddr[WB_W-1:0];
  wire [AW-WB_W-1:0] rrow = raddr[AW-1:WB_W];
`ifdef M_STORE_ROW_OFF1
  wire [AW-WB_W-1:0] xrow = wraddr[AW-1:WB_W] + {{(AW-WB_W-1){1'b0}}, 1'b1};
`else
  wire [AW-WB_W-1:0] xrow = wraddr[AW-1:WB_W];
`endif
  wire [7:0] rbyte [0:WIDE_B-1];
  genvar gb;
  generate
    for (gb = 0; gb < WIDE_B; gb = gb + 1) begin : g_bank
      reg [7:0] mem [0:NW-1];
      always @(posedge clk) begin
`ifdef M_STORE_WRONG_BANK
        if (we && ((wsel == gb && gb != WIDE_B-1) || (gb == 0 && wsel == WIDE_B-1))) mem[wrow] <= wdata;
`else
        if (we && wsel == gb) mem[wrow] <= wdata;
`endif
        // byte gb of the word is the gb-th LOWEST address = the MSB-first
        // byte position WIDE_B-1-gb, as the v1 byte read put it
        if (wre) wrdata[(WIDE_B-1-gb)*8 +: 8] <= mem[xrow];
      end
      assign rbyte[gb] = mem[rrow];
    end
  endgenerate
  always @(posedge clk) begin
    if (re) rdata <= rbyte[rsel];
  end

  // ⛔ RULING TM2's per-byte address registers are GONE with the byte-wide
  // array: a word read has no `wraddr + k` add to move out of the mux path.
  // (So is `M_TM2_STORE_ADD`, the mutant that restored that add.)
  wire _unused_lo = &{1'b0, wraddr[WB_W-1:0]};

  // ⚠ `rst_n` is intentionally NOT used to clear the array. Clearing 2**AW
  // bytes would add a reset fanout to every storage bit for no benefit: the
  // loader writes the whole image before run mode is entered, and 1.6's
  // load-time screen is what guarantees the image is admissible. Listed so the
  // omission reads as a decision.
  wire _unused_store = &{rst_n, 1'b0};

endmodule
