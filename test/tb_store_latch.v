// tb_store_latch -- the LATCH STORE's own bench (Wilson 10-31, Track 2), driven by
// test/gate_store_latch.py. pe_store at MEM_TYPE "latch", alone.
//   default      power-up fill is random (not X, not one value); every byte written,
//                read back from cycle C+2 on both ports; prints "STORE-LATCH PASS"
//   ARM_RAW      a narrow read of the byte written the cycle before -> the store's
//                READ-AFTER-WRITE contract must stop the bench
//   ARM_RAW_WIDE the same for a wide read of the row written the cycle before
//   ARM_SHARED   a narrow and a wide read in one cycle -> the shared read tree's
//                precondition check must stop the bench
// Must-fires through the store's own defines: M_STORE_NO_FILL (the fill check
// fails), M_STORE_DROP_ROW0 (row 0's writes are lost; only the random fill shows it).
`timescale 1ns/1ps
`default_nettype none

module tb_store_latch;
  localparam integer AW = 9, WB = 4;
  reg            clk = 1'b0, rst_n = 1'b0;
  reg  [WB-1:0]  we = 0;
  reg  [AW-1:0]  waddr = 0, raddr = 0;
  reg  [7:0]     wdata = 0;
  reg            re = 1'b0, wre = 1'b0;
  reg  [WB*AW-1:0] wraddr_bk = 0;
  wire [7:0]     rdata;
  wire [WB*8-1:0] wrdata;
  always #5 clk = ~clk;   // clock-ok: a cycle-only unit bench -- nothing here is timed in ns

  pe_store #(.AW(AW), .MEM_TYPE("latch"), .WIDE_B(WB)) dut (
      .clk(clk), .rst_n(rst_n), .we(we), .waddr(waddr), .wdata(wdata),
      .re(re), .raddr(raddr), .rdata(rdata), .wre(wre), .wraddr_bk(wraddr_bk), .wrdata(wrdata));

  function [7:0] pat;               // a byte per address that no two neighbours share
    input [AW-1:0] a;
    pat = a[7:0] ^ {a[8], 7'h35} ^ (a[7:0] << 3);
  endfunction

  integer a, k, nd, bad, nx;
  reg [255:0] seen;
  reg [7:0] v, first;

  task wr(input [AW-1:0] addr, input [7:0] d);
    begin
      @(negedge clk); we = {WB{1'b1}}; waddr = addr; wdata = d;
      @(negedge clk); we = 0;
    end
  endtask

  initial begin
    repeat (2) @(negedge clk);
    rst_n = 1'b1;
    // ---- the power-up fill: random, never X and never one value ----
    seen = 0; nd = 0; nx = 0; first = dut.g_mem.peek(0);
    for (a = 0; a < (1 << AW); a = a + 1) begin
      v = dut.g_mem.peek(a[AW-1:0]);
      if (^v === 1'bx) nx = nx + 1;
      else if (!seen[v]) begin seen[v] = 1'b1; nd = nd + 1; end
    end
    if (nx != 0 || nd < 64) begin
      $display("STORE-LATCH *** FILL NOT RANDOM: %0d X bytes, %0d distinct values", nx, nd);
      $finish;
    end
    $display("STORE-LATCH fill random: %0d distinct values over %0d bytes", nd, 1 << AW);
    bad = 0;
    // ---- write every byte ----
    for (a = 0; a < (1 << AW); a = a + 1) wr(a[AW-1:0], pat(a[AW-1:0]));
    @(negedge clk); @(negedge clk);
    // ---- narrow reads (registered: data on the edge after `re`) ----
    for (a = 0; a < (1 << AW); a = a + 1) begin
      @(negedge clk); re = 1'b1; raddr = a[AW-1:0];
      @(negedge clk); re = 1'b0;
      if (rdata !== pat(a[AW-1:0])) begin
        bad = bad + 1;
        if (bad <= 4) $display("STORE-LATCH *** narrow read of %0d: %h, wrote %h", a, rdata, pat(a[AW-1:0]));
      end
    end
    // ---- wide reads: row r = bytes 4r .. 4r+3, MSB-first ----
    for (a = 0; a < (1 << AW); a = a + WB) begin
      @(negedge clk); wre = 1'b1; for (k = 0; k < WB; k = k + 1) wraddr_bk[k*AW +: AW] = a[AW-1:0];
      @(negedge clk); wre = 1'b0;
      if (wrdata !== {pat(a), pat(a + 1), pat(a + 2), pat(a + 3)}) begin
        bad = bad + 1;
        if (bad <= 8) $display("STORE-LATCH *** wide read of row %0d: %h", a / WB, wrdata);
      end
    end
`ifdef ARM_RAW
    // a narrow read issued in the cycle right after the write's cycle
    @(negedge clk); we = {WB{1'b1}}; waddr = 9'd77; wdata = 8'h5A;
    @(negedge clk); we = 0; re = 1'b1; raddr = 9'd77;
    @(negedge clk); re = 1'b0;
    $display("STORE-LATCH *** ARM_RAW: the read-after-write was NOT stopped");
    $finish;
`endif
`ifdef ARM_RAW_WIDE
    @(negedge clk); we = {WB{1'b1}}; waddr = 9'd77; wdata = 8'h5A;
    @(negedge clk); we = 0; wre = 1'b1; for (k = 0; k < WB; k = k + 1) wraddr_bk[k*AW +: AW] = 9'd76;
    @(negedge clk); wre = 1'b0;
    $display("STORE-LATCH *** ARM_RAW_WIDE: the read-after-write was NOT stopped");
    $finish;
`endif
`ifdef ARM_SHARED
    // a narrow read (byte 42 = bank 2, row 10) and a wide read (row 20, every bank)
    // in ONE cycle -> the shared tree's precondition check must stop the bench
    @(negedge clk); re = 1'b1; raddr = 9'd42;
    wre = 1'b1; for (k = 0; k < WB; k = k + 1) wraddr_bk[k*AW +: AW] = 9'd80;
    @(negedge clk); re = 1'b0; wre = 1'b0;
    $display("STORE-LATCH *** ARM_SHARED: the shared read was NOT stopped");
    $finish;
`endif
    if (bad == 0) $display("STORE-LATCH PASS: 512 bytes written, read back on both ports");
    else $display("STORE-LATCH *** FAIL: %0d mismatches", bad);
    $finish;
  end
endmodule
