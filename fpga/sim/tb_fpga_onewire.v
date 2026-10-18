/* tb_fpga_onewire.v -- SIMULATION TWIN of the OW = 1 FPGA build (1-Wire on
 * J11, Wilson 10-17): the whole pe_fpga_core against the DS18B20 model
 * (test/ds18b20_model.v, SAME-HAND) on a pulled-up DQ net, and a model of the
 * PC on the board UART (115200 8N1).
 *
 * THE PC sends 'G' and prints every byte the board sends back (`OW-RX`) --
 * the runner (fpga/sim/run_fpga_onewire.py) judges those bytes, as the real
 * PC will. Nothing here reads the chip to produce them.
 *
 * MEASURED HERE (simulation-only introspection, labelled):
 *   OW-ISO    every fall on DQ while the core is loading / holding / has the
 *             chip in reset -- the load-isolation rule: must be 0
 *   OW-LOADCYC the cycles observed in load mode (positive evidence a load
 *             happened under the monitor)
 *   OW-REPLY / OW-POP  each poll reply's arrival cycle and every queue pop,
 *             for the poll-decision slack
 *   OW-STATUS the status bits the glue decoded (the host's view of the flags)
 *   OW-STICKY the chip's own sticky flags
 * End token: `OW-BENCH: END`.
 */
`default_nettype none
`timescale 1ns / 1ps
module tb_fpga_onewire;
  parameter integer RISE_NS  = 2003;
  parameter FEED             = "";
  parameter integer NFEED    = 0;
  parameter integer POLLIDX  = 0;
  parameter integer PER2     = 12800;
  parameter integer MARGIN   = 6400;
  parameter integer BAD_AT   = -1;
  parameter integer BAD_SHIFT = 0;
  parameter integer LATE     = 0;
  parameter integer ISO_MF   = 0;
  parameter integer NCYC_MAX = 6000000;

  reg clk = 0, rst_n = 0, rx = 1;
  wire tx;
  wire [5:0] led;
  wire running;
  always #10 clk = ~clk;

  // ---- the DQ net: open drain, pull-up rise RISE_NS (inertial) -------------
  wire dq_low_raw, dev_pull, dq;
  wire m_low;
  assign #1 m_low = dq_low_raw;                // off the clock edges
  assign #(RISE_NS, 0) dq = ~(m_low | dev_pull);

  pe_fpga_core #(.IMG("test/onewire_fpga_image.hex"), .BRK_CYC(20000),
                 .OW(1), .FEED(FEED), .NFEED(NFEED), .POLLIDX(POLLIDX),
                 .PER2(PER2), .MARGIN(MARGIN), .BAD_AT(BAD_AT),
                 .BAD_SHIFT(BAD_SHIFT), .LATE(LATE), .ISO_MF(ISO_MF)) dut (
      .clk(clk), .rst_n(rst_n), .uart_rx(rx), .uart_tx(tx),
      .led(led), .running(running), .dq_in(dq), .dq_low(dq_low_raw));

  ds18b20_model u_ds (.dq(dq), .pull(dev_pull));

  // ---- the PC ---------------------------------------------------------------
  localparam real BT = 1.0e9 / 115200.0;
  integer n_rx = 0;
  reg [7:0] b;
  integer k;
  initial forever begin
    @(negedge tx);
    #(BT * 1.5);
    for (k = 0; k < 8; k = k + 1) begin b[k] = tx; #(BT); end
    $display("OW-RX %0d %02h", n_rx, b);
    n_rx = n_rx + 1;
    #(BT * 0.25);
  end
  task send(input [7:0] v);
    integer j;
    begin
      rx = 0; #(BT);
      for (j = 0; j < 8; j = j + 1) begin rx = v[j]; #(BT); end
      rx = 1; #(BT);
    end
  endtask

  // ---- monitors (simulation introspection) ---------------------------------
  integer cyc = 0, iso_falls = 0, load_cyc = 0, npop = 0;
  wire isolating = dut.loading || dut.hold || !dut.chip_rst_n;
  always @(posedge clk) begin
    cyc = cyc + 1;
    // LOAD MODE proper (not the idle hold before 'G'): the bytes are going in
    if (dut.loading && !dut.hold && dut.chip_rst_n) load_cyc = load_cyc + 1;
  end
  always @(negedge dq) if (isolating) begin
    iso_falls = iso_falls + 1;
    if (iso_falls <= 3)
      $display("OW-ISO-FALL at cyc %0d (loading %0b hold %0b chip_rst_n %0b)",
               cyc, dut.loading, dut.hold, dut.chip_rst_n);
  end
  always @(posedge clk) if (!isolating) begin
    if (dut.chip.u_eng.host_pop) begin
      $display("OW-POP %0d %0d", npop, cyc);
      npop = npop + 1;
    end
    if (dut.fst == 3'd6 && dut.pay && dut.rx_cnt == POLLIDX + dut.pg)
      $display("OW-REPLY %0d %0d %02h kb=%0d", dut.pg, cyc, dut.f_data, dut.kb);
  end
  // a load restarts the pop count (the chip's queue restarts with it)
  always @(posedge dut.go_ld) npop = 0;

  initial begin
    $display("# fpga_onewire feed=%0s nfeed=%0d pollidx=%0d per2=%0d margin=%0d bad_at=%0d bad_shift=%0d late=%0d iso_mf=%0d rise=%0d",
             FEED, NFEED, POLLIDX, PER2, MARGIN, BAD_AT, BAD_SHIFT, LATE, ISO_MF, RISE_NS);
    repeat (8) @(posedge clk); rst_n = 1;
    #(200_000);                                // the board sits idle, J11 released
    if (running !== 1'b0) $display("*** FAIL fpga_onewire: chip running before 'G'");
    send("G");
    // done: the feed is consumed, every reply forwarded, the UART drained
    wait ((dut.feed_done && !dut.fwd && dut.wp == dut.rp && !dut.tx_busy)
          || cyc >= NCYC_MAX);
    #(BT * 30);
    // ⭐ THREE MORE BYTE TIMES OF IDLE: the timer keeps the lane fed after
    // the feed (0xFF), so no underrun may appear afterwards either
    repeat (3 * PER2) @(posedge clk);
    u_ds.report;
    $display("OW-ISO falls=%0d", iso_falls);
    $display("OW-LOADCYC %0d", load_cyc);
    $display("OW-STATUS %02h", dut.st_or);
    $display("OW-STICKY underrun=%0b rx_drop=%0b config_err=%0b tx_full=%0b",
             dut.chip.u_eng.lane_underrun[0], dut.chip.rx_drop_sticky,
             dut.chip.u_eng.config_err, dut.chip.tx_full_sticky);
    $display("OW-HOST pushed=%0d fed=%0d rx_cnt=%0d polls=%0d pc_rx=%0d cyc=%0d",
             dut.kb, dut.nfed, dut.rx_cnt, dut.pg, n_rx, cyc);
    if (cyc < NCYC_MAX) $display("OW-BENCH: END");
    else $display("*** FAIL fpga_onewire: NCYC_MAX reached");
    $finish;
  end
endmodule
`default_nettype wire
