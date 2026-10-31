/*
 * Copyright (c) 2026 Nathan Humphrey
 * SPDX-License-Identifier: Apache-2.0
 *
 * THE PDK BINDING of the store's RAM (SRAM trial, canary branches only):
 * pe_store.v's "sram" arm instantiates `pe_sram_macro` when PE_SRAM_MACRO is
 * defined, and THIS file -- listed in info.yaml on the canary branch only --
 * binds it to the IHP 1 KB single-port macro. BIST tied off, A_DLY = 1 (the
 * nominal delay setting; Ken Pettit's IHP TT walkthrough does the same).
 */

`default_nettype none

module pe_sram_macro #(
    parameter integer AWW = 8,
    parameter integer DW  = 32
) (
    input  wire            clk,
    input  wire            men,
    input  wire            wen,
    input  wire            ren,
    input  wire [AWW-1:0]  addr,
    input  wire [DW-1:0]   din,
    input  wire [DW-1:0]   bm,
    output wire [DW-1:0]   dout
);
  RM_IHPSG13_1P_256x32_c2_bm_bist u_sram (
      .A_CLK(clk), .A_MEN(men), .A_WEN(wen), .A_REN(ren),
      .A_ADDR(addr), .A_DIN(din), .A_BM(bm), .A_DLY(1'b1), .A_DOUT(dout),
      .A_BIST_CLK(1'b0), .A_BIST_EN(1'b0), .A_BIST_MEN(1'b0), .A_BIST_WEN(1'b0),
      .A_BIST_REN(1'b0), .A_BIST_ADDR(8'd0), .A_BIST_DIN(32'd0), .A_BIST_BM(32'd0));
endmodule

// synthesis sees the macro as a black box (its .lib / .lef come from the flow)
(* blackbox *)
module RM_IHPSG13_1P_256x32_c2_bm_bist (
    input  wire        A_CLK, A_MEN, A_WEN, A_REN, A_DLY,
    input  wire [7:0]  A_ADDR,
    input  wire [31:0] A_DIN, A_BM,
    output wire [31:0] A_DOUT,
    input  wire        A_BIST_CLK, A_BIST_EN, A_BIST_MEN, A_BIST_WEN, A_BIST_REN,
    input  wire [7:0]  A_BIST_ADDR,
    input  wire [31:0] A_BIST_DIN, A_BIST_BM
);
endmodule
