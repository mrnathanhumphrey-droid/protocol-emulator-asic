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
      always @(posedge clk) wd_q <= wdata;
      // ⭐⭐ PRE-DECODE (Wilson 11-03). The row clock gate's GATE was
      // `wv_q && bank_hit && wrow_q == gr` -- a 7-bit compare through a
      // fanout-7 decode, the chip's binder at two of three densities (u_icg
      // GATE, a HALF-cycle check). The address is now decoded at the STAGING
      // edge into two one-hot groups, so every GATE is one flop pair -> one
      // 2-input AND: 16 flops over {row[1:0], bank} with the write valid
      // FOLDED IN (all zero when no write is staged), and 32 over row[6:2].
      // 16 x 32 = 512, one AND per byte row. The writers do not change.
      localparam integer RW  = AW - WB_W;            // row bits (7)
      localparam integer RLO = 2;                    // row bits in group A
      localparam integer NPA = 1 << (WB_W + RLO);    // 16
      localparam integer NPB = 1 << (RW - RLO);      // 32
`ifdef M_PREDECODE_LATE
      wire [WB_W+RLO-1:0] pka = {wrow_q[RLO-1:0], wsel_q};
`else
      wire [WB_W+RLO-1:0] pka = {wrow[RLO-1:0], wsel};
`endif
      wire [RW-RLO-1:0]   pkb = wrow[RW-1:RLO];
      reg  [NPA-1:0]      wpa_q;                     // {row[1:0], bank}, valid folded
      reg  [NPB-1:0]      wpb_q;                     // row[6:2]
      always @(posedge clk or negedge rst_n)
        if (!rst_n) wpa_q <= {NPA{1'b0}};
        else        wpa_q <= (|we) ? ({{(NPA-1){1'b0}}, 1'b1} << pka) : {NPA{1'b0}};
      always @(posedge clk) wpb_q <= {{(NPB-1){1'b0}}, 1'b1} << pkb;
`ifndef SYNTHESIS
      // ⭐ THE BINARY STAGING, KEPT FOR ITS ONLY READERS -- the contract
      // checks below (Wilson 11-03: keep a binary copy, never rebuild it from
      // the one-hot). Simulation-only, so silicon carries none of it; the
      // M_PREDECODE_LATE must-fire decodes from it, one cycle late.
      reg  [WB_W-1:0]     wsel_q;
      reg  [AW-WB_W-1:0]  wrow_q;
      reg                 wv_q;
      always @(posedge clk or negedge rst_n)
        if (!rst_n) wv_q <= 1'b0;
        else        wv_q <= |we;
      always @(posedge clk) begin
        wsel_q <= wsel;
        wrow_q <= wrow;
      end
`endif
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
`ifndef SYNTHESIS
        wire bank_hit = (wsel_q == gb);                // the contract check's
`endif
        // M_STORE_WRONG_BANK, on the pre-decoded group A: banks 0 and 3 read
        // each other's columns, so bank 3's writes land in bank 0 (and 0's in 3)
`ifdef M_STORE_WRONG_BANK
        localparam integer GBW = (gb == 0) ? WIDE_B - 1 : (gb == WIDE_B - 1) ? 0 : gb;
`else
        localparam integer GBW = gb;
`endif
        wire [7:0] mem [0:NW-1];
        for (gr = 0; gr < NW; gr = gr + 1) begin : g_row
          wire gclk;
          // M_STORE_DROP_ROW0, the must-fire of the power-up fill: row 0's writes
          // are lost, so its bytes keep their RANDOM power-up value -- only the
          // fill exposes it
          // ⭐ THE GATE: one flop of each group, one AND (pre-decode)
          wire wen = wpa_q[(gr % (1 << RLO)) * WIDE_B + GBW] & wpb_q[gr >> RLO];
`ifdef M_STORE_DROP_ROW0
          pe_icg u_icg (.CLK(clk_n), .GATE(wen && gr != 0), .GCLK(gclk));
`else
          pe_icg u_icg (.CLK(clk_n), .GATE(wen), .GCLK(gclk));
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
    end else if (MEM_TYPE == "sram") begin : g_mem
      // ⭐⭐ THE SRAM ARM (Wilson 10-30, the SRAM trial). ONE single-port word
      // RAM (inline below: the IHP 1P_bm_bist macro's behaviour; the macro is
      // bound by file substitution). The modes are exclusive -- PROG writes and
      // reads back, RUN reads the header then refills, SNIFF captures then
      // runs stage 0 -- so a request mux is the whole arbitration, with ONE
      // same-cycle pair to order: a write and a narrow read.
      // ⛔ THE READ WINS; THE WRITE WAITS (Wilson 11-07, the PIT on the SRAM).
      // The trial made the read wait, which suited the loader alone: stage 3
      // reads and writes the store back to back, and a read one cycle late
      // gave it stale data (5 same-cycle pairs on s3_crc32_full). Now the
      // write goes to a ONE-ENTRY BUFFER and drains on the next cycle with no
      // read; a narrow read of the buffered word is FORWARDED its bytes. So
      // every client sees the flop arm's timing exactly: a read in a write's
      // own cycle returns the old byte, any later read the new one. A second
      // write while one is buffered is a contract break (checked below).
      // Read timing is the flop arm's: the
      // RAM samples on the edge the flop arm registers rdata / wrdata, and its
      // dout holds until the next read -- so L_REFILL and the Lean core are
      // untouched, and only the read data's arrival time moves (~5.4 ns slow).
      localparam integer AWW = 8;                 // 256 words (the macro); AW = 9 uses 128
      wire              wr  = |we;
`ifdef M_STORE_ROW_OFF1
      wire [AW-WB_W-1:0] xrow = wraddr_bk[WB_W +: AW-WB_W] + {{(AW-WB_W-1){1'b0}}, 1'b1};
`else
      wire [AW-WB_W-1:0] xrow = wraddr_bk[WB_W +: AW-WB_W];   // the copies are equal: bank 0's
`endif
      wire _unused_bk = &{1'b0, wraddr_bk[WIDE_B*AW-1:AW], wraddr_bk[WB_W-1:0]};
      // the read always goes now; a write meeting it waits in the buffer
      wire              rd_now  = re | wre;
      wire [AW-1:0]     rd_addr = raddr;
      // the written byte's lane: byte k of a word at bit (WIDE_B-1-k)*8 (the flop arm's order)
`ifdef M_STORE_WRONG_BANK
      wire [WB_W-1:0]   wlane = (wsel == WIDE_B-1) ? {WB_W{1'b0}} : wsel;
`else
      wire [WB_W-1:0]   wlane = wsel;
`endif
      wire [WIDE_B*8-1:0] bm  = {{(WIDE_B-1)*8{1'b0}}, 8'hFF} << {~wlane, 3'b000};   // lane WIDE_B-1-k = ~k (WIDE_B a power of 2)
      wire [WIDE_B*8-1:0] din = {WIDE_B{wdata}};
      // THE WRITE BUFFER: pw = a write is waiting (word pa, data pd, mask pbm)
      reg                 pw;
      reg  [AW-WB_W-1:0]  pa;
      reg  [WIDE_B*8-1:0] pd, pbm;
      wire              w_now = ~rd_now & (pw | wr);          // the port writes this cycle
      wire [AW-WB_W-1:0] w_row = pw ? pa : wrow;
      wire [WIDE_B*8-1:0] w_d  = pw ? pd : din;
      wire [WIDE_B*8-1:0] w_bm = pw ? pbm : bm;
      wire              men = w_now | rd_now;
      wire              ren = rd_now;
      wire [AWW-1:0]    ram_a = w_now ? {{(AWW-(AW-WB_W)){1'b0}}, w_row}
                              : wre   ? {{(AWW-(AW-WB_W)){1'b0}}, xrow}
                              :         {{(AWW-(AW-WB_W)){1'b0}}, rd_addr[AW-1:WB_W]};
      // ---- the RAM: the macro in the canary flow, its exact behaviour here ----
      // (inline, not a submodule: the bench's peek below reads the array, and
      // a design function cannot reach into a child instance under Verilator)
`ifdef PE_SRAM_MACRO
      // the flow binds the macro: pe_sram_macro is defined by the canary
      // branch's PDK-specific file (src/pe_sram_macro_ihp.v), NOT here
      wire [WIDE_B*8-1:0] dout;
      pe_sram_macro #(.AWW(AWW), .DW(WIDE_B*8)) u_macro (.clk(clk), .men(men), .wen(w_now),
          .ren(ren), .addr(ram_a), .din(w_d), .bm(w_bm), .dout(dout));
`else
      // the IHP RM_IHPSG13_1P_*_bm_bist macro's behaviour, as its own model:
      //   men & wen   mem[a] = (mem & ~bm) | (din & bm)  (ren is never with wen:
      //               w_now = ~rd_now & ..., so the macro's write-through is not modelled)
      //   men & ren   dout <= mem[a];  otherwise dout HOLDS (it changes only on a read)
      reg  [WIDE_B*8-1:0] mem [0:(1 << AWW) - 1];
      reg  [WIDE_B*8-1:0] dout;
      wire [WIDE_B*8-1:0] merged = (mem[ram_a] & ~w_bm) | (w_d & w_bm);
      always @(posedge clk) begin
        if (men && w_now) begin
          mem[ram_a] <= merged;
        end else if (men && ren) begin
          dout <= mem[ram_a];
        end
      end
`ifndef SYNTHESIS
      // ⛔ THE ARRAY POWERS UP RANDOM (Wilson's must-fire): neither the macro
      // nor the flop store it replaces has a reset
      integer pi;
      initial for (pi = 0; pi < (1 << AWW); pi = pi + 1) mem[pi] = $unsigned($random);
`endif
      // ⛔ dout before the first read: LN1's must-fire (M_PFETCH_NOWAIT)
      // captures the wide read before any read lands, and its pinned behaviour
      // is X under iverilog, and 0 when the simulator is Verilator (the
      // pinned LN1 signature). Otherwise random.
`ifdef M_PFETCH_NOWAIT
`ifdef VERILATOR
      initial dout = {WIDE_B*8{1'b0}};
`endif
`else
`ifndef SYNTHESIS
      initial dout = $unsigned($random);
`endif
`endif
`endif
      // the buffer, and the narrow read's forward: a read of the buffered word
      // (pw at the read's edge) takes those bytes over the RAM's (old) ones
      reg  [WB_W-1:0]     rsel_q;
      reg                 fw_q;
      reg  [WIDE_B*8-1:0] fd_q, fbm_q;
      always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
          pw <= 1'b0; pa <= {(AW-WB_W){1'b0}}; pd <= {WIDE_B*8{1'b0}}; pbm <= {WIDE_B*8{1'b0}};
          rsel_q <= {WB_W{1'b0}}; fw_q <= 1'b0; fd_q <= {WIDE_B*8{1'b0}}; fbm_q <= {WIDE_B*8{1'b0}};
        end else begin
          if (wr && (rd_now || pw)) begin                      // the new write waits
            pw <= 1'b1; pa <= wrow; pd <= din; pbm <= bm;
          end else if (w_now) pw <= 1'b0;                      // the buffer drained
          if (re) begin
            rsel_q <= rd_addr[WB_W-1:0];
            fw_q   <= pw && (pa == rd_addr[AW-1:WB_W]);
            fd_q   <= pd; fbm_q <= pbm;
          end
        end
      end
      wire [WIDE_B*8-1:0] rword = fw_q ? ((dout & ~fbm_q) | (fd_q & fbm_q)) : dout;
      always @(*) begin
        rdata  = rword[{~rsel_q, 3'b000} +: 8];
        wrdata = dout;
      end
`ifndef SYNTHESIS
      // ⛔ THE ONE-PORT CONTRACT, checked in every bench: never a wide read
      // with a write or a narrow read in the same cycle (the modes are
      // exclusive); the only allowed pair is a write with a narrow read.
      // ⚠ only after the store has SEEN a reset: before it, every request
      // register holds its power-up value (Verilator's random init put a write
      // and a wide read on the first edge at one seed), as silicon would --
      // and the RAM's contents are garbage until the loader writes them anyway
      reg rst_seen = 1'b0;
      always @(negedge rst_n) rst_seen <= 1'b1;
      always @(posedge clk) if (rst_seen && rst_n === 1'b1 && wre === 1'b1 && (wr === 1'b1 || re === 1'b1 || pw === 1'b1)) begin
        $display("pe_store: *** ONE-PORT CONTRACT BROKEN at %0t: wre with %s", $time,
                 wr ? "a write" : re ? "a narrow read" : "a buffered write");
        $finish;
      end
      // the buffer holds ONE write: a second while it is full and the port is
      // reading would be lost
      always @(posedge clk) if (rst_seen && rst_n === 1'b1 && wr === 1'b1 && pw === 1'b1 && rd_now === 1'b1) begin
        $display("pe_store: *** WRITE BUFFER OVERFLOW at %0t: a write, a buffered write and a read", $time);
        $finish;
      end
`endif
      // a bench's view of one byte (both arms define it)
      function [7:0] peek;
        input [AW-1:0] a;
        reg [WIDE_B*8-1:0] wd;
        begin
`ifdef PE_SRAM_MACRO
          wd   = {WIDE_B*8{1'b0}};          // the macro's array is not visible here
`else
          wd   = mem[{{(AWW-(AW-WB_W)){1'b0}}, a[AW-1:WB_W]}];
          if (pw && pa == a[AW-1:WB_W]) wd = (wd & ~pbm) | (pd & pbm);
`endif
          peek = wd[{~a[WB_W-1:0], 3'b000} +: 8];
        end
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
  genvar k, i;
  // ⛔ TWO DESCRIPTIONS OF ONE TREE (Wilson 11-02). Synthesis reads the flat
  // vector below, the text every canary hardened. Simulation reads the same
  // nodes as an UNPACKED array, one net per node: in iverilog every change to
  // the flat `t` re-sent all 8*NT bits to every slice reader, which made the
  // latch store's benches ~30x slower than the flop store's (11-02: one PIT
  // stage-0 sim 1,212.7 s flat, 182.0 s unpacked, byte-identical output).
  // model/gate_rowmux_equiv.py proves the two equal, at every SW the chip and
  // the benches use, on every push. ⛔ EDIT BOTH OR THE GATE GOES RED.
`ifdef SYNTHESIS
  (* keep *) wire [8*NT-1:0] t;
  assign t[0 +: 8*N] = d;
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
`else
  (* keep *) wire [7:0] t [0:NT-1];
  generate
    for (i = 0; i < N; i = i + 1) begin : g_leaf
      assign t[i] = d[i*8 +: 8];
    end
    for (k = 1; k <= L4; k = k + 1) begin : g_lv
      wire [1:0] q = s[2*k-1 -: 2];
      for (i = 0; i < (N >> (2*k)); i = i + 1) begin : g_n
        // the node's four children, in address order
        wire [7:0] c0 = t[lvl_off(k-1) + 4*i];
        wire [7:0] c1 = t[lvl_off(k-1) + 4*i + 1];
        wire [7:0] c2 = t[lvl_off(k-1) + 4*i + 2];
        wire [7:0] c3 = t[lvl_off(k-1) + 4*i + 3];
`ifdef M_ROWMUX_NODE
        assign t[lvl_off(k) + i] = (k == 1 && i == 1) ? (q[1] ? (q[0] ? c0 : c1) : (q[0] ? c2 : c3)) : (q[1] ? (q[0] ? c3 : c2) : (q[0] ? c1 : c0));
`else
        assign t[lvl_off(k) + i] = q[1] ? (q[0] ? c3 : c2) : (q[0] ? c1 : c0);
`endif
      end
    end
    if (SW % 2 == 1) begin : g_root2
      assign y = s[SW-1] ? t[lvl_off(L4) + 1] : t[lvl_off(L4)];
    end else begin : g_root
      assign y = t[lvl_off(L4)];
    end
  endgenerate
`endif
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
