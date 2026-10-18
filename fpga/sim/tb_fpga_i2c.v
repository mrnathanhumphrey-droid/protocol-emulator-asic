/* tb_fpga_i2c.v -- SIMULATION TWIN of the OW = 2 FPGA build (I2C FRAM on
 * J11, Wilson 10-17): the whole pe_fpga_core against the MB85RC256V model
 * (test/fram_i2c.v, SAME-HAND) on two pulled-up open-drain lines (RISE_NS),
 * and a model of the PC on the board UART (115200 8N1).
 *
 * THE PC sends 'G' + the 4 data bytes (DATA), then prints every byte the
 * board sends back (`I2C-RX`); the runner (fpga/sim/run_fpga_i2c.py) judges
 * those, as fpga/host/i2c_run.py will on the board. The FRAM's 0x0010..13
 * start as OLD.
 *
 * GLITCH_AT = n (Wilson 1b): just after the n-th SCL fall the FPGA's SCL
 * INPUT (not the bus) bounces high for GL_CYC cycles -- noise near the
 * threshold on a slow edge. It must be counted once (DEGLITCH), and the
 * chip does not see it (it reads back its own pin while it drives SCL low).
 *
 * MEASURED HERE (simulation-only introspection, labelled):
 *   I2C-ISO    falls on SCL or SDA, and STARTs the FRAM saw, while the core is
 *              loading / holding / has the chip in reset: must be 0
 *   I2C-LOADCYC load-mode cycles observed (evidence a load happened)
 *   I2C-POP k g b c   byte k's queue pop: the glue's filtered fall count g,
 *              the bus's own fall count b, cycle c -- the count model check
 *   I2C-PUSH k c      byte k's low-nibble PUSH edge, cycle c
 *   I2C-STICKY / I2C-MEM  the chip's sticky flags; the FRAM's 0x10..0x13
 * End token: `I2C-BENCH: END`.
 */
`default_nettype none
`timescale 1ns / 1ps
module tb_fpga_i2c;
  parameter integer RISE_NS  = 300;
  parameter IMG              = "";
  parameter FEED             = "";
  parameter FALLS            = "";
  parameter integer NFEED    = 0;
  parameter integer NRX      = 0;
  parameter integer DEGLITCH = 8;
  parameter integer BAD_AT   = -1;
  parameter integer BAD_SHIFT = 0;
  parameter integer ISO_MF   = 0;
  parameter integer GLITCH_AT = -1;
  parameter integer GL_CYC   = 3;
  parameter [31:0]  DATA     = 32'h0;     // D0 in [31:24]
  parameter [31:0]  OLD      = 32'h0;
  parameter integer NCYC_MAX = 400000;

  reg clk = 0, rst_n = 0, rx = 1;
  wire tx;
  wire [5:0] led;
  wire running;
  always #10 clk = ~clk;

  // ---- the bus: open drain, pull-up rise RISE_NS (inertial) -------------
  wire scl_low_raw, sda_low_raw, f_scl, f_sda, scl, sda;
  wire m_scl, m_sda;
  assign #1 m_scl = scl_low_raw;               // off the clock edges
  assign #1 m_sda = sda_low_raw;
  assign #(RISE_NS, 0) scl = ~(m_scl | f_scl);
  assign #(RISE_NS, 0) sda = ~(m_sda | f_sda);
  reg glitch = 1'b0;
  wire scl_fpga = scl | glitch;                // the FPGA's input only

  pe_fpga_core #(.IMG(IMG), .BRK_CYC(20000), .OW(2), .FEED(FEED),
                 .FALLS(FALLS), .NFEED(NFEED), .NRX(NRX), .DEGLITCH(DEGLITCH),
                 .BAD_AT(BAD_AT), .BAD_SHIFT(BAD_SHIFT), .ISO_MF(ISO_MF)) dut (
      .clk(clk), .rst_n(rst_n), .uart_rx(rx), .uart_tx(tx),
      .led(led), .running(running), .dq_in(sda), .dq_low(sda_low_raw),
      .p3_in(scl_fpga), .p3_low(scl_low_raw));

  fram_i2c u_fram (.clk(clk), .scl_in(scl), .sda_in(sda), .sda_oe(f_sda),
                   .scl_oe(f_scl));

  // ---- the PC ---------------------------------------------------------------
  localparam real BT = 1.0e9 / 115200.0;
  integer n_rx = 0;
  reg [7:0] b;
  integer k;
  initial forever begin
    @(negedge tx);
    #(BT * 1.5);
    for (k = 0; k < 8; k = k + 1) begin b[k] = tx; #(BT); end
    $display("I2C-RX %0d %02h", n_rx, b);
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
  integer cyc = 0, iso_falls = 0, load_cyc = 0, npop = 0, bus_falls = 0;
  reg [7:0] iso_start0;
  wire isolating = dut.loading || dut.hold || !dut.chip_rst_n;
  always @(posedge clk) begin
    cyc = cyc + 1;
    if (dut.loading && !dut.hold && dut.chip_rst_n) load_cyc = load_cyc + 1;
  end
  always @(negedge scl) if (isolating) iso_falls = iso_falls + 1;
                        else bus_falls = bus_falls + 1;
  // every SCL rise on the bus, in ns -- fSCL is measured from these exactly
  // as from the DSLogic capture (rise to rise, inside bytes)
  always @(posedge scl) if (!isolating) $display("I2C-SCLRISE %0.1f", $realtime);
  always @(negedge sda) if (isolating) iso_falls = iso_falls + 1;
  always @(posedge clk) if (!isolating) begin
    if (dut.chip.u_eng.host_pop) begin
      $display("I2C-POP %0d %0d %0d %0d", npop, dut.falls, bus_falls, cyc);
      npop = npop + 1;
    end
    // the low-nibble PUSH edge: F_PUSH, phase 8 (p_wr rises)
    if (dut.fst == 3'd5 && dut.fph == 4'd8)
      $display("I2C-PUSH %0d %0d", dut.kb, cyc);
  end
  always @(posedge dut.go_ld) begin npop = 0; bus_falls = 0; end
  // the glitch: GL_CYC cycles high on the FPGA's SCL input, 2 cycles after
  // the GLITCH_AT-th bus fall
  always @(negedge scl) if (!isolating && bus_falls == GLITCH_AT) begin
    repeat (2) @(posedge clk);
    glitch = 1'b1;
    repeat (GL_CYC) @(posedge clk);
    glitch = 1'b0;
    $display("I2C-GLITCH injected after bus fall %0d, %0d cycles", GLITCH_AT, GL_CYC);
  end

  integer i;
  initial begin
    $display("# fpga_i2c img=%0s feed=%0s falls=%0s nfeed=%0d nrx=%0d deglitch=%0d bad_at=%0d bad_shift=%0d iso_mf=%0d glitch_at=%0d rise=%0d data=%08h old=%08h",
             IMG, FEED, FALLS, NFEED, NRX, DEGLITCH, BAD_AT, BAD_SHIFT, ISO_MF,
             GLITCH_AT, RISE_NS, DATA, OLD);
    for (i = 0; i < 4; i = i + 1) u_fram.mem[16 + i] = OLD[31 - 8 * i -: 8];
    repeat (8) @(posedge clk); rst_n = 1;
    #(200_000);
    if (running !== 1'b0) $display("*** FAIL fpga_i2c: chip running before 'G'");
    iso_start0 = u_fram.start_cnt;
    send("G");
    for (i = 0; i < 4; i = i + 1) send(DATA[31 - 8 * i -: 8]);
    wait ((!isolating) || cyc >= NCYC_MAX);
    $display("I2C-ISO starts=%0d", u_fram.start_cnt - iso_start0);
    wait ((dut.feed_done && !dut.fwd && dut.st_sent == 2'd2 && dut.wp == dut.rp
           && !dut.tx_busy) || cyc >= NCYC_MAX);
    #(BT * 30);
    $display("I2C-ISO falls=%0d", iso_falls);
    $display("I2C-LOADCYC %0d", load_cyc);
    $display("I2C-STATUS %02h", dut.st_or);
    $display("I2C-STICKY underrun=%0b rx_drop=%0b config_err=%0b tx_full=%0b",
             dut.chip.u_eng.lane_underrun[0], dut.chip.rx_drop_sticky,
             dut.chip.u_eng.config_err, dut.chip.tx_full_sticky);
    $display("I2C-MEM %02h %02h %02h %02h", u_fram.mem[16], u_fram.mem[17],
             u_fram.mem[18], u_fram.mem[19]);
    $display("I2C-HOST pushed=%0d rx_cnt=%0d glue_falls=%0d bus_falls=%0d pc_rx=%0d cyc=%0d",
             dut.kb, dut.rx_cnt, dut.falls, bus_falls, n_rx, cyc);
    if (cyc < NCYC_MAX) $display("I2C-BENCH: END");
    else $display("*** FAIL fpga_i2c: NCYC_MAX reached");
    $finish;
  end
endmodule
`default_nettype wire
