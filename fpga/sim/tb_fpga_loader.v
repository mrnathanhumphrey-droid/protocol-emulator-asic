/* tb_fpga_loader.v -- SIMULATION TWIN of the PC-UART loader (Wilson: the
 * FPGA stand-in for the Pico 2's role; every image passes its sim first).
 *
 * The whole FPGA core against a model of the PC on one 115200 8N1 port:
 *   1. boot from BRAM (uart_rx_434.hex): frames come back as 2 bytes each
 *   2. BREAK, then a frame with a CORRUPT checksum: the board says 'E' and
 *      the chip stays silent (in reset)
 *   3. a good frame carrying uart_rx_434_nostop.hex: 'K', and frames now come
 *      back as ONE byte each -- the loaded program is the one running
 *   4. BREAK, reload uart_rx_434.hex: 'K', 2 bytes per frame again
 * Verdict: `FPGA-LOADER: ok -- ...` or `*** FAIL fpga_loader: ...`.
 */
`default_nettype none
`timescale 1ns / 1ps
module tb_fpga_loader;
  reg clk = 0, rst_n = 0, rx = 1;
  wire tx;
  wire [5:0] led;
  wire running;
  always #10 clk = ~clk;

  localparam integer BRK = 20000;          // 0.4 ms in simulation
  pe_fpga_core #(.IMG("fpga/images/uart_rx_434.hex"), .BRK_CYC(BRK)) dut (
      .clk(clk), .rst_n(rst_n), .uart_rx(rx), .uart_tx(tx),
      .led(led), .running(running));

  localparam real BT = 1.0e9 / 115200.0;
  reg [7:0] img_ok [0:255];
  reg [7:0] img_ns [0:255];
  reg [7:0] got [0:1023];
  integer   ngot = 0, fails = 0, i, k, base;
  reg [7:0] b, sum;

  // ---- the PC, receiving ----
  initial forever begin
    @(negedge tx);
    #(BT * 1.5);
    for (k = 0; k < 8; k = k + 1) begin b[k] = tx; #(BT); end
    got[ngot] = b; ngot = ngot + 1;
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
  task brk;
    begin rx = 0; #(20.0 * (BRK + 5000)); rx = 1; #(BT * 20); end
  endtask
  task load(input integer which, input integer corrupt);
    begin
      send(8'hA5); send(8'h5A); sum = 0;
      for (i = 0; i < 256; i = i + 1) begin
        b = which ? img_ns[i] : img_ok[i];
        send(b); sum = sum + b;
      end
      send(corrupt ? (8'h00 - sum + 8'h01) : (8'h00 - sum));
      #(BT * 40);
    end
  endtask
  // send n frames of known data; return how many bytes came back
  task frames(input integer n, output integer back);
    integer s;
    begin
      s = ngot;
      for (i = 0; i < n; i = i + 1) begin send(8'h30 + i); #(BT * 3); end
      #(BT * 10 * 2 * n + BT * 20);
      back = ngot - s;
    end
  endtask
  task expect_reply(input [7:0] want, input [8*40-1:0] what);
    begin
      if (ngot == base + 1 && got[base] == want)
        $display("  %0s: board replied '%c'", what, want);
      else begin
        fails = fails + 1;
        $display("*** FAIL fpga_loader: %0s: expected one reply '%c', got %0d byte(s)%0s",
                 what, want, ngot - base, (ngot > base) ? "" : " (none)");
      end
    end
  endtask

  integer back;
  initial begin
    $readmemh("fpga/images/uart_rx_434.hex", img_ok);
    $readmemh("fpga/images/uart_rx_434_nostop.hex", img_ns);
    repeat (8) @(posedge clk); rst_n = 1;
    wait (running === 1'b1); #(50_000);

    frames(6, back);
    if (back != 12) begin fails = fails + 1;
      $display("*** FAIL fpga_loader: boot image: %0d bytes for 6 frames, expected 12", back); end
    else $display("  boot (BRAM) image: 6 frames -> 12 bytes (data + stop)");

    brk; base = ngot; load(1, 1); expect_reply("E", "corrupt checksum");
    base = ngot; frames(4, back);
    if (back != 0) begin fails = fails + 1;
      $display("*** FAIL fpga_loader: after a rejected load the chip answered (%0d bytes)", back); end
    else $display("  after the rejected load: chip silent (held in reset)");

    base = ngot; load(1, 0); expect_reply("K", "nostop image");
    frames(6, back);
    if (back != 6) begin fails = fails + 1;
      $display("*** FAIL fpga_loader: nostop image: %0d bytes for 6 frames, expected 6", back); end
    else $display("  loaded nostop image: 6 frames -> 6 bytes (data only)");

    brk; base = ngot; load(0, 0); expect_reply("K", "reload of the normal image");
    frames(6, back);
    if (back != 12) begin fails = fails + 1;
      $display("*** FAIL fpga_loader: reloaded image: %0d bytes for 6 frames, expected 12", back); end
    else $display("  reloaded normal image: 6 frames -> 12 bytes");

    if (fails == 0)
      $display("FPGA-LOADER: ok -- boot, rejected load ('E', chip silent), PC load of a different program ('K', 1 byte/frame), reload ('K', 2 bytes/frame)");
    $finish;
  end
endmodule
`default_nettype wire
