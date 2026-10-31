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
  genvar gb;
  generate
    if (MEM_TYPE == "sram") begin : g_mem
      // ⭐⭐ THE SRAM ARM (Wilson 10-30, the SRAM trial). ONE single-port word
      // RAM (inline below: the IHP 1P_bm_bist macro's behaviour; the macro is
      // bound by file substitution). The modes are exclusive -- PROG writes and
      // reads back, RUN reads the header then refills, SNIFF captures then
      // runs stage 0 -- so a request mux is the whole arbitration, with ONE
      // same-cycle pair to order: a PROG loader write and a readback read.
      // The WRITE wins and the read issues the next cycle (the readback is
      // bit-serial, many cycles per byte). Read timing is the flop arm's: the
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
      // a narrow read that met a write waits one cycle
      reg               rd_pend;
      reg  [AW-1:0]     rd_addr_q;
      wire              rd_now  = (re | rd_pend) & ~wr;
      wire [AW-1:0]     rd_addr = rd_pend ? rd_addr_q : raddr;
      // the written byte's lane: byte k of a word at bit (WIDE_B-1-k)*8 (the flop arm's order)
`ifdef M_STORE_WRONG_BANK
      wire [WB_W-1:0]   wlane = (wsel == WIDE_B-1) ? {WB_W{1'b0}} : wsel;
`else
      wire [WB_W-1:0]   wlane = wsel;
`endif
      wire [WIDE_B*8-1:0] bm  = {{(WIDE_B-1)*8{1'b0}}, 8'hFF} << {~wlane, 3'b000};   // lane WIDE_B-1-k = ~k (WIDE_B a power of 2)
      wire              men = wr | wre | rd_now;
      wire              ren = ~wr & (wre | rd_now);
      wire [AWW-1:0]    ram_a = wr  ? {{(AWW-(AW-WB_W)){1'b0}}, wrow}
                              : wre ? {{(AWW-(AW-WB_W)){1'b0}}, xrow}
                              :       {{(AWW-(AW-WB_W)){1'b0}}, rd_addr[AW-1:WB_W]};
      // ---- the RAM: the macro in the canary flow, its exact behaviour here ----
      // (inline, not a submodule: the bench's peek below reads the array, and
      // a design function cannot reach into a child instance under Verilator)
      wire [WIDE_B*8-1:0] din = {WIDE_B{wdata}};
`ifdef PE_SRAM_MACRO
      // the flow binds the macro: pe_sram_macro is defined by the canary
      // branch's PDK-specific file (src/pe_sram_macro_ihp.v), NOT here
      wire [WIDE_B*8-1:0] dout;
      pe_sram_macro #(.AWW(AWW), .DW(WIDE_B*8)) u_macro (.clk(clk), .men(men), .wen(wr),
          .ren(ren), .addr(ram_a), .din(din), .bm(bm), .dout(dout));
`else
      // the IHP RM_IHPSG13_1P_*_bm_bist macro's behaviour, as its own model:
      //   men & wen   mem[a] = (mem & ~bm) | (din & bm)  (ren is never with wen:
      //               ren = ~wr & ..., so the macro's write-through is not modelled)
      //   men & ren   dout <= mem[a];  otherwise dout HOLDS (it changes only on a read)
      reg  [WIDE_B*8-1:0] mem [0:(1 << AWW) - 1];
      reg  [WIDE_B*8-1:0] dout;
      wire [WIDE_B*8-1:0] merged = (mem[ram_a] & ~bm) | (din & bm);
      always @(posedge clk) begin
        if (men && wr) begin
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
      reg  [WB_W-1:0]   rsel_q;
      always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin rd_pend <= 1'b0; rd_addr_q <= {AW{1'b0}}; rsel_q <= {WB_W{1'b0}}; end
        else begin
          rd_pend <= re & wr;
          if (re) rd_addr_q <= raddr;
          if (rd_now && !wre) rsel_q <= rd_addr[WB_W-1:0];
        end
      end
      always @(*) begin
        rdata  = dout[{~rsel_q, 3'b000} +: 8];
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
      always @(posedge clk) if (rst_seen && rst_n === 1'b1 && wre === 1'b1 && (wr === 1'b1 || re === 1'b1)) begin
        $display("pe_store: *** ONE-PORT CONTRACT BROKEN at %0t: wre with %s", $time, wr ? "a write" : "a narrow read");
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
