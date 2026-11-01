// tb_rowmux -- the latch store's row-read TREE alone (Wilson 11-01), driven by
// test/gate_store_latch.py. pe_rowmux against d[s*8 +: 8] for every row address,
// 4 random fills, at SW = 7 (the store's 128 rows), 4 (even: no 2:1 root) and
// 3 (odd, one 4:1 level); prints "ROWMUX PASS".
// Must-fire: M_ROWMUX_NODE (one leaf-level node reads its children reversed).
`timescale 1ns/1ps
`default_nettype none

module tb_rowmux;
  localparam integer N = 128;
  reg  [8*N-1:0] d;
  reg  [6:0]     s;
  wire [7:0]     y7, y4, y3;
  integer f, r, k, bad, n;

  pe_rowmux #(.SW(7)) u7 (.d(d),           .s(s),      .y(y7));
  pe_rowmux #(.SW(4)) u4 (.d(d[8*16-1:0]), .s(s[3:0]), .y(y4));
  pe_rowmux #(.SW(3)) u3 (.d(d[8*8-1:0]),  .s(s[2:0]), .y(y3));

  initial begin
    bad = 0; n = 0;
    for (f = 0; f < 4; f = f + 1) begin
      for (k = 0; k < N; k = k + 1) d[k*8 +: 8] = $random;
      for (r = 0; r < N; r = r + 1) begin
        s = r; #1;
        n = n + 1;
        if (y7 !== d[r*8 +: 8]) begin
          bad = bad + 1;
          if (bad <= 4) $display("ROWMUX *** SW=7 row %0d: %h, want %h", r, y7, d[r*8 +: 8]);
        end
        if (r < 16) begin
          n = n + 1;
          if (y4 !== d[r*8 +: 8]) begin
            bad = bad + 1;
            if (bad <= 4) $display("ROWMUX *** SW=4 row %0d: %h, want %h", r, y4, d[r*8 +: 8]);
          end
        end
        if (r < 8) begin
          n = n + 1;
          if (y3 !== d[r*8 +: 8]) begin
            bad = bad + 1;
            if (bad <= 4) $display("ROWMUX *** SW=3 row %0d: %h, want %h", r, y3, d[r*8 +: 8]);
          end
        end
      end
    end
    if (bad == 0) $display("ROWMUX PASS: %0d checks, 0 mismatches", n);
    else          $display("ROWMUX *** FAIL: %0d of %0d checks mismatched", bad, n);
    $finish;
  end
endmodule
