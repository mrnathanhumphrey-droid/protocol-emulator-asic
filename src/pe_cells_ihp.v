/*
 * Copyright (c) 2026 Nathan Humphrey
 * SPDX-License-Identifier: Apache-2.0
 *
 * LATCH STORE CANARY ONLY (Wilson 10-31, Track 2): the three generic cells of
 * pe_store.v's latch arm, bound to IHP sg13cmos5l stock cells. pe_store.v
 * defines the generic (behavioural) versions under `ifndef PE_IHP_CELLS`;
 * config.json sets PE_IHP_CELLS so these replace them. No other file names a
 * PDK cell.
 *   pe_icg      -> sg13cmos5l_lgcp_1         latch_posedge clock gate
 *   pe_latch8   -> 8 x sg13cmos5l_dlhq_1     transparent-high latch
 *   pe_hold_buf -> sg13cmos5l_dlygate4sd3_1  hold delay on the write data
 *                  (RSZ_DONT_TOUCH_RX keeps the resizer from removing it)
 */

`default_nettype none

`ifdef PE_IHP_CELLS
module pe_icg (
    input  wire CLK,
    input  wire GATE,
    output wire GCLK
);
  sg13cmos5l_lgcp_1 u_cg (.CLK(CLK), .GATE(GATE), .GCLK(GCLK));
endmodule

module pe_latch8 (
    input  wire       G,
    input  wire [7:0] D,
    output wire [7:0] Q
);
  genvar i;
  generate
    for (i = 0; i < 8; i = i + 1) begin : g_bit
      sg13cmos5l_dlhq_1 u_l (.GATE(G), .D(D[i]), .Q(Q[i]));
    end
  endgenerate
endmodule

module pe_hold_buf (
    input  wire A,
    output wire X
);
  sg13cmos5l_dlygate4sd3_1 u_d (.A(A), .X(X));
endmodule
`endif
