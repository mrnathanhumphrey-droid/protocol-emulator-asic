// pa100t_top.v -- Puzhi PA100T-EDU (XC7A100T-2FGG484) top for pe_fpga_core.
//
// 200 MHz differential (the board's only clock) -> MMCM -> 50 MHz, the chip's
// design clock. The reset key (R14, ~47 ms RC, idles high) resets the MMCM
// directly (its RST is asynchronous by design) and is SYNCHRONISED before it
// reaches fabric; the core leaves reset only once the MMCM is locked.
// Board facts and their provenance: pa100t_uart.xdc.
//
// PE_OW (defined by `build.tcl ow` only): the 1-Wire build -- J11 pin 4 (A20)
// is DQ, OPEN DRAIN: pulled low or released, never driven high (the 4.7k on the
// breadboard pulls it up; pa100t_j11_ow.xdc). Without PE_OW this file is the
// UART build exactly as before.
`default_nettype none
module pa100t_top #(
    parameter IMG = "uart_rx_434.hex"
`ifdef PE_OW
  , parameter FEED = "onewire_fpga_feed.hex",
    parameter integer NFEED = 0, POLLIDX = 0, PER2 = 0, MARGIN = 0
`endif
) (
    input  wire       sys_clk_p,
    input  wire       sys_clk_n,
    input  wire       sys_rstn,
    input  wire       uart_rx,
    output wire       uart_tx,
`ifdef PE_OW
    inout  wire       j11_dq,
`endif
    output wire [5:0] led
);
  wire clk_in, clk_fb, clk50_u, clk50, locked;
  IBUFDS u_ibuf (.I(sys_clk_p), .IB(sys_clk_n), .O(clk_in));
  // VCO = 200 x 5 = 1000 MHz (600..1200 for -2); /20 = 50 MHz
  MMCME2_BASE #(
      .CLKIN1_PERIOD(5.000), .DIVCLK_DIVIDE(1), .CLKFBOUT_MULT_F(5.000),
      .CLKOUT0_DIVIDE_F(20.000)
  ) u_mmcm (
      .CLKIN1(clk_in), .CLKFBIN(clk_fb), .CLKFBOUT(clk_fb),
      .CLKOUT0(clk50_u), .LOCKED(locked), .RST(~sys_rstn), .PWRDWN(1'b0),
      .CLKOUT0B(), .CLKOUT1(), .CLKOUT1B(), .CLKOUT2(), .CLKOUT2B(),
      .CLKOUT3(), .CLKOUT3B(), .CLKOUT4(), .CLKOUT5(), .CLKOUT6(),
      .CLKFBOUTB()
  );
  BUFG u_bufg (.I(clk50_u), .O(clk50));

  // reset: locked AND key, synchronised into clk50 (3 flops)
  (* ASYNC_REG = "TRUE" *) reg [2:0] rs;
  always @(posedge clk50 or negedge locked)
    if (!locked) rs <= 3'b000;
    else         rs <= {rs[1:0], sys_rstn};
  wire rst_n = rs[2];

  // the board UART input crosses into clk50: 2 flops (the chip synchronises
  // its pins again, as it would a real pad)
  (* ASYNC_REG = "TRUE" *) reg [1:0] rxs;
  always @(posedge clk50) rxs <= {rxs[0], uart_rx};

  wire [5:0] core_led;
  wire       running;
`ifdef PE_OW
  wire dq_low;
  assign j11_dq = dq_low ? 1'b0 : 1'bz;          // open drain
  pe_fpga_core #(.IMG(IMG), .OW(1), .FEED(FEED), .NFEED(NFEED),
                 .POLLIDX(POLLIDX), .PER2(PER2), .MARGIN(MARGIN)) u_core (
      .clk(clk50), .rst_n(rst_n), .uart_rx(rxs[1]), .uart_tx(uart_tx),
      .led(core_led), .running(running), .dq_in(j11_dq), .dq_low(dq_low)
  );
`else
  pe_fpga_core #(.IMG(IMG)) u_core (
      .clk(clk50), .rst_n(rst_n), .uart_rx(rxs[1]), .uart_tx(uart_tx),
      .led(core_led), .running(running), .dq_in(1'b1), .dq_low()
  );
`endif
  assign led = {core_led[5:2], locked, core_led[0]};
endmodule
`default_nettype wire
