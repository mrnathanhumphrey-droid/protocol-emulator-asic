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
    // write port (program load). ⭐ step 1b: ONE ENABLE PER BANK (all equal),
    // each from its own replicated prog_mode flop in project.v
    input  wire [WIDE_B-1:0] we,
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
    // WORD-aligned (the low WB_W bits are 0); ONE COPY PER BANK, bank k at
    // [k*AW +: AW] (v2 slack recovery step 2: the fan-out is the bank's own)
    input  wire [WIDE_B*AW-1:0] wraddr_bk,
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
  genvar gb, gr, gh;
  generate
    if (MEM_TYPE == "latch") begin : g_mem
      // ⭐⭐ THE LATCH ARM (Wilson 10-31, Track 2): the same 512 bytes in IHP
      // latches -- ~-45 % of the store, -30 % of the chip, stock cells only.
      // WRITE: the request is STAGED at posedge t0 (data, bank, row, valid). One
      // clock gate per row per bank (pe_icg = sg13cmos5l_lgcp_1), clocked by
      // ~clk, opens that row's 8 latches for the LOW half of the next cycle;
      // the staged data holds still for the whole window. READ: the flop arm's
      // registered row selects, unchanged.
      // ⛔ READ-AFTER-WRITE (Wilson's risk 3): a byte written in cycle C is
      // only safe to read from cycle C+2 -- a read in C+1 samples on the edge
      // that closes the latch (a half-cycle path). The modes keep that apart
      // (RUN only reads; LOAD and SNIFF read later), and the contract check
      // below proves it in every bench; its must-fire is gate store-latch.
      // ⛔ HOLD (Wilson's risk 2): the latch closes on the rising edge through
      // the inverter and the gate, the SAME edge that restages the data -- so
      // the data passes 8 hold buffers by design (pe_hold_buf, kept by
      // RSZ_DONT_TOUCH_RX in config.json).
      reg  [7:0]          wd_q;
      reg  [WB_W-1:0]     wsel_q;
      reg  [AW-WB_W-1:0]  wrow_q;
      reg                 wv_q;
      always @(posedge clk or negedge rst_n)
        if (!rst_n) wv_q <= 1'b0;
        else        wv_q <= |we;
      always @(posedge clk) begin
        wd_q   <= wdata;
        wsel_q <= wsel;
        wrow_q <= wrow;
      end
`ifndef SYNTHESIS
      // the contract checks below are ARMED only once this store has seen its
      // reset low on an edge: before that every flop is power-up state (seed
      // 1 of the 2-state seed sweep fired SHARED READ at the first edge, 10 ns;
      // rst_n itself comes from a synchroniser and is random there)
      reg chk_armed = 1'b0;
      always @(posedge clk) if (rst_n === 1'b0) chk_armed <= 1'b1;
`endif
      wire       clk_n = ~clk;
      wire [7:0] wd_h;
      for (gh = 0; gh < 8; gh = gh + 1) begin : g_hold
        pe_hold_buf u_hold (.A(wd_q[gh]), .X(wd_h[gh]));
      end
      wire [7:0] rbyte [0:WIDE_B-1];
      // every byte, flat (address order), for `peek` -- Verilator cannot reach
      // a net array inside a nested generate from a function (cov sweep, 10-31)
      wire [7:0] lmem [0:(1 << AW) - 1];
      for (gb = 0; gb < WIDE_B; gb = gb + 1) begin : g_bank
`ifdef M_STORE_WRONG_BANK
        wire bank_hit = (wsel_q == gb && gb != WIDE_B-1) || (gb == 0 && wsel_q == WIDE_B-1);
`else
        wire bank_hit = (wsel_q == gb);
`endif
        wire [7:0] mem [0:NW-1];
        for (gr = 0; gr < NW; gr = gr + 1) begin : g_row
          wire gclk;
          // M_STORE_DROP_ROW0, the must-fire of the power-up fill: row 0's writes
          // are lost, so its bytes keep their RANDOM power-up value -- only the
          // fill exposes it
`ifdef M_STORE_DROP_ROW0
          pe_icg u_icg (.CLK(clk_n), .GATE(wv_q && bank_hit && wrow_q == gr && gr != 0), .GCLK(gclk));
`else
          pe_icg u_icg (.CLK(clk_n), .GATE(wv_q && bank_hit && wrow_q == gr), .GCLK(gclk));
`endif
          pe_latch8 u_row (.G(gclk), .D(wd_h), .Q(mem[gr]));
          assign lmem[gr * WIDE_B + gb] = mem[gr];
        end
        // this bank's own copy of the wide-read row
`ifdef M_STORE_ROW_OFF1
        wire [AW-WB_W-1:0] xrow = wraddr_bk[gb*AW+WB_W +: AW-WB_W] + {{(AW-WB_W-1){1'b0}}, 1'b1};
`else
        wire [AW-WB_W-1:0] xrow = wraddr_bk[gb*AW+WB_W +: AW-WB_W];
`endif
        wire _unused_lo = &{1'b0, wraddr_bk[gb*AW +: WB_W]};
        // ⭐ (a) (Wilson 11-01): the reads go through an explicit mux tree on the
        // row address. `mem[row]` on a wire array became 686 one-hot row selects,
        // and the placer then grouped the latches by BIT, so every row-level net
        // crossed the bank; with the tree it groups them by ROW (routes, 0 overflow).
        // ONE tree per bank, shared by both reads: `re` and `wre` are never high in
        // the same cycle (the mode flops, SNIFF's engine reset, hdr_done --
        // checked below in every bench).
        wire [8*NW-1:0] memf;
        for (gr = 0; gr < NW; gr = gr + 1) begin : g_flat
          assign memf[gr*8 +: 8] = mem[gr];
        end
        wire [7:0] sbyte;
        pe_rowmux #(.SW(AW-WB_W)) u_mux (.d(memf), .s(wre ? xrow : rrow), .y(sbyte));
        assign rbyte[gb] = sbyte;
        always @(posedge clk)
          if (wre) wrdata[(WIDE_B-1-gb)*8 +: 8] <= sbyte;
`ifndef SYNTHESIS
        // the read-after-write contract, per bank: no wide read of the row
        // whose latch closes on this edge
        always @(posedge clk) if (chk_armed && rst_n === 1'b1 && wv_q === 1'b1 && bank_hit && wre === 1'b1 && xrow == wrow_q) begin
          $display("pe_store: *** READ-AFTER-WRITE at %0t: a wide read of row %0d, written the previous cycle", $time, xrow);
          $finish;
        end
`endif
      end
      always @(posedge clk)
        if (re) rdata <= rbyte[rsel];
`ifndef SYNTHESIS
      // the shared tree's precondition: never both reads in one cycle
      always @(posedge clk) if (chk_armed && rst_n === 1'b1 && re === 1'b1 && wre === 1'b1) begin
        $display("pe_store: *** SHARED READ at %0t: re and wre both high", $time);
        $finish;
      end
      // the narrow read's half of the contract
      always @(posedge clk) if (chk_armed && rst_n === 1'b1 && wv_q === 1'b1 && re === 1'b1 && raddr == {wrow_q, wsel_q}) begin
        $display("pe_store: *** READ-AFTER-WRITE at %0t: a read of byte %0d, written the previous cycle", $time, raddr);
        $finish;
      end
`endif
`ifdef M_PFETCH_NOWAIT
`ifdef VERILATOR
      initial wrdata = {WIDE_B*8{1'b0}};
`endif
`endif
      // a bench's view of one byte (every arm defines it)
      function [7:0] peek;
        input [AW-1:0] a;
        peek = lmem[a];
      endfunction
    end else begin : g_mem
      wire [7:0] rbyte [0:WIDE_B-1];
      for (gb = 0; gb < WIDE_B; gb = gb + 1) begin : g_bank
        reg [7:0] mem [0:NW-1];
        // this bank's own copy of the wide-read row
`ifdef M_STORE_ROW_OFF1
        wire [AW-WB_W-1:0] xrow = wraddr_bk[gb*AW+WB_W +: AW-WB_W] + {{(AW-WB_W-1){1'b0}}, 1'b1};
`else
        wire [AW-WB_W-1:0] xrow = wraddr_bk[gb*AW+WB_W +: AW-WB_W];
`endif
        wire _unused_lo = &{1'b0, wraddr_bk[gb*AW +: WB_W]};
        always @(posedge clk) begin
`ifdef M_STORE_WRONG_BANK
          if (we[gb] && ((wsel == gb && gb != WIDE_B-1) || (gb == 0 && wsel == WIDE_B-1))) mem[wrow] <= wdata;
`else
          if (we[gb] && wsel == gb) mem[wrow] <= wdata;
`endif
          // byte gb of the word is the gb-th LOWEST address = the MSB-first
          // byte position WIDE_B-1-gb, as the v1 byte read put it
          if (wre) wrdata[(WIDE_B-1-gb)*8 +: 8] <= mem[xrow];
        end
        assign rbyte[gb] = mem[rrow];
      end
      always @(posedge clk) begin
        if (re) rdata <= rbyte[rsel];
      end
      // ⛔ LN1's must-fire (M_PFETCH_NOWAIT) skips P_WAIT, so P_CAP takes `wrdata`
      // before any read lands. Unreset, its value is the simulator's random init
      // -- and any new flop elsewhere moved that stream (LOOP's l_loop shifted the
      // pinned signature a row, 10-29). A CONSTANT keeps the mutant's signature a
      // property of the RTL, not of the random stream (Wilson 10-29).
      // ⛔ VERILATOR ONLY: under iverilog the register stays X, and run_mutants'
      // kill IS that X (the tree select propagates it until nothing retires);
      // a constant there moved its pinned reason (CI sim2, 10-29).
`ifdef M_PFETCH_NOWAIT
`ifdef VERILATOR
      initial wrdata = {WIDE_B*8{1'b0}};
`endif
`endif
      // a bench's view of one byte (both arms define it)
      function [7:0] peek;
        input [AW-1:0] a;
        reg [7:0] b;
        begin
          case (a[WB_W-1:0])
            0: b = g_bank[0].mem[a[AW-1:WB_W]];
            1: b = g_bank[1].mem[a[AW-1:WB_W]];
            2: b = g_bank[2].mem[a[AW-1:WB_W]];
            default: b = g_bank[3].mem[a[AW-1:WB_W]];
          endcase
          peek = b;
        end
      endfunction
    end
  endgenerate
  // ⛔ RULING TM2's per-byte address registers are GONE with the byte-wide
  // array: a word read has no `wraddr + k` add to move out of the mux path.
  // (So is `M_TM2_STORE_ADD`, the mutant that restored that add.)

  // ⚠ `rst_n` is intentionally NOT used to clear the array. Clearing 2**AW
  // bytes would add a reset fanout to every storage bit for no benefit: the
  // loader writes the whole image before run mode is entered, and 1.6's
  // load-time screen is what guarantees the image is admissible. Listed so the
  // omission reads as a decision.
  wire _unused_store = &{rst_n, 1'b0};

endmodule

// the latch arm's row read, shared by both reads (Wilson 11-01): a 2**SW:1 byte mux built as a
// tree of 4:1 muxes on address-bit pairs from the leaves up (s[1:0] first),
// with one 2:1 level at the root when SW is odd. Level k holds N/4**k nodes,
// stored back to back in `t` from offset lvl_off(k). Every level boundary is a
// KEPT wire, so synthesis cannot fold the tree back into a one-hot decode.
module pe_rowmux #(
    parameter integer SW = 7
) (
    input  wire [8*(1<<SW)-1:0] d,
    input  wire [SW-1:0]        s,
    output wire [7:0]           y
);
  localparam integer N  = 1 << SW;
  localparam integer L4 = SW / 2;           // 4:1 levels
  function integer lvl_off;                 // first node of level k
    input integer k;
    integer j;
    begin
      lvl_off = 0;
      for (j = 0; j < k; j = j + 1) lvl_off = lvl_off + (N >> (2*j));
    end
  endfunction
  localparam integer NT = lvl_off(L4 + 1);  // nodes in all levels
  (* keep *) wire [8*NT-1:0] t;
  assign t[0 +: 8*N] = d;
  genvar k, i;
  generate
    for (k = 1; k <= L4; k = k + 1) begin : g_lv
      wire [1:0] q = s[2*k-1 -: 2];
      for (i = 0; i < (N >> (2*k)); i = i + 1) begin : g_n
        // the node's four children, in address order
        wire [7:0] c0 = t[(lvl_off(k-1) + 4*i)*8 +: 8];
        wire [7:0] c1 = t[(lvl_off(k-1) + 4*i + 1)*8 +: 8];
        wire [7:0] c2 = t[(lvl_off(k-1) + 4*i + 2)*8 +: 8];
        wire [7:0] c3 = t[(lvl_off(k-1) + 4*i + 3)*8 +: 8];
        // M_ROWMUX_NODE, the tree bench's must-fire: one leaf-level node (level
        // 1, node 1 = rows 4..7) reads its children in reverse order
`ifdef M_ROWMUX_NODE
        assign t[(lvl_off(k) + i)*8 +: 8] = (k == 1 && i == 1) ? (q[1] ? (q[0] ? c0 : c1) : (q[0] ? c2 : c3)) : (q[1] ? (q[0] ? c3 : c2) : (q[0] ? c1 : c0));
`else
        assign t[(lvl_off(k) + i)*8 +: 8] = q[1] ? (q[0] ? c3 : c2) : (q[0] ? c1 : c0);
`endif
      end
    end
    if (SW % 2 == 1) begin : g_root2
      assign y = s[SW-1] ? t[(lvl_off(L4) + 1)*8 +: 8] : t[lvl_off(L4)*8 +: 8];
    end else begin : g_root
      assign y = t[lvl_off(L4)*8 +: 8];
    end
  endgenerate
endmodule

// ---------------------------------------------------------------------------
// The latch arm's three cells, GENERIC here (Part 1: no PDK cell names in RTL).
// A canary / tapeout tree binds them to IHP stock cells by FILE SUBSTITUTION:
// src/pe_cells_ihp.v (sg13cmos5l_lgcp_1,
// _dlhq_1, _dlygate4sd3_1) under PE_IHP_CELLS, listed in info.yaml there only.
// ---------------------------------------------------------------------------
`ifndef PE_IHP_CELLS
// a latch_posedge integrated clock gate: GATE is captured while CLK is low
module pe_icg (
    input  wire CLK,
    input  wire GATE,
    output wire GCLK
);
  reg en;
  always_latch if (!CLK) en = GATE;
  assign GCLK = CLK & en;
endmodule

// one row of the array: 8 transparent-high latches, no reset
module pe_latch8 (
    input  wire       G,
    input  wire [7:0] D,
    output wire [7:0] Q
);
  reg [7:0] q;
  always_latch if (G) q = D;
`ifndef SYNTHESIS
  // ⛔ THE ARRAY POWERS UP RANDOM: latches have no reset, so neither does the
  // model (gate store-latch checks it; its must-fire is M_STORE_NO_FILL)
  reg [31:0] seed_r;
`ifndef M_STORE_NO_FILL
  initial begin seed_r = $unsigned($random); q = seed_r[7:0]; end
`endif
`endif
  assign Q = q;
endmodule

// a hold buffer on the latch array's write data (a wire until bound to a cell)
module pe_hold_buf (
    input  wire A,
    output wire X
);
  assign X = A;
endmodule
`endif
