/* tb_fpga_uart.v -- the SIMULATION TWIN of the FPGA UART-rx bring-up (Wilson:
 * every image passes its sim bench before it goes on the board).
 *
 * The whole FPGA core (loader + unchanged chip + host-stream decoder + FIFO +
 * UART tx) against a model of the PC: 8N1 at 115200 x (1 + ERR/1000), random
 * idle gaps with bursts of back-to-back frames, and FRAMING frames sent as a
 * BREAK (line low 2 ms: a frame of zeros with 0 at the receiver's stop sample)
 * -- the same method the board test uses. The board's UART output is decoded
 * at exactly 115200 and must be, per frame, [data, {stop, data[7:1]}] --
 * data 00, stop byte 00 on a break -- in order, with the count EXACT. This is
 * what the PC test script checks on the real board.
 *
 * Plusargs: ERR(0) NFR(24) SEED(1) SPACEEVERY(7: every Nth frame is a break, 0=none)
 * Verdict: `FPGA-UART: ok -- ...` or `*** FAIL fpga_uart: ...`.
 */
`default_nettype none
`timescale 1ns / 1ps
module tb_fpga_uart;
  reg clk = 0, rst_n = 0, rx = 1;
  wire tx;
  wire [5:0] led;
  wire running;
  always #10 clk = ~clk;                       // 50 MHz

  pe_fpga_core #(.IMG("fpga/images/uart_rx_434.hex")) dut (
      .clk(clk), .rst_n(rst_n), .uart_rx(rx), .uart_tx(tx),
      .led(led), .running(running));

  localparam integer FMAX = 1024;
  integer err, nfr, seed, spacee, f, b, gap, n_sent, n_got, n_bad, i;
  real    bt, tn, tq;
  reg [31:0] rnd;
  reg [7:0]  sent [0:FMAX-1];
  reg        sp   [0:FMAX-1];
  reg [7:0]  got;
  reg        pc_done;

  function [31:0] lcg(input [31:0] s); lcg = s * 32'd1103515245 + 32'd12345; endfunction
  task at(input real t, input reg v);
    begin
      tq = t;
      if (tq - 10.0 * $floor(tq / 10.0) < 0.5) tq = tq + 1.0;   // never ON an edge
      if (tq > $realtime) #(tq - $realtime);
      rx = v;
    end
  endtask

  // ---- the PC, sending ------------------------------------------------------
  initial begin
    pc_done = 0;
    wait (running === 1'b1);
    #(50_000);
    tn = $realtime;
    for (f = 0; f < nfr; f = f + 1) begin
      rnd = lcg(rnd); sent[f] = rnd[23:16];
      sp[f] = (spacee != 0) && (f % spacee == spacee - 1);
      n_sent = f + 1;
      if (sp[f]) begin
        // ⛔ THE FRAMING FRAME IS A BREAK, as on the board (fpga/host/
        // uart_test.py): line low 2 ms, then high. One port has one parity
        // setting for both directions, so the board test cannot use 8S1.
        sent[f] = 8'h00;
        at(tn, 1'b0);
        tn = tn + 2.0e6;
        at(tn, 1'b1);
        tn = tn + 20.0 * bt;
      end else begin
        at(tn, 1'b0);                                     // start
        for (b = 0; b < 8; b = b + 1) begin tn = tn + bt; at(tn, sent[f][b]); end
        tn = tn + bt; at(tn, 1'b1);                       // stop
        tn = tn + bt;
      end
      rnd = lcg(rnd);
      gap = (rnd[17:16] == 2'd0) ? 0 : (rnd[25:18] % 3);  // bit times of idle
      tn = tn + bt * gap;
    end
    pc_done = 1;
  end

  // ---- the PC, receiving: exactly 115200, sampled mid-bit -------------------
  localparam real BT_RX = 1.0e9 / 115200.0;
  initial begin
    n_got = 0; n_bad = 0;
    forever begin
      @(negedge tx);
      #(BT_RX * 1.5);
      for (i = 0; i < 8; i = i + 1) begin got[i] = tx; #(BT_RX); end
      check(got);
      #(BT_RX * 0.25);
    end
  end
  task check(input [7:0] g);
    reg [7:0] w; integer k;
    begin
      k = n_got / 2;
      if (k >= n_sent) begin
        n_bad = n_bad + 1;
        $display("*** FAIL fpga_uart: byte %0d (%02h) with only %0d frame(s) sent", n_got, g, n_sent);
      end else begin
        w = (n_got % 2 == 0) ? sent[k] : {~sp[k], sent[k][7:1]};
        if (g !== w) begin
          n_bad = n_bad + 1;
          if (n_bad <= 6)
            $display("*** FAIL fpga_uart: frame %0d %s byte: board %02h, expected %02h",
                     k, (n_got % 2) ? "stop" : "data", g, w);
        end
      end
      n_got = n_got + 1;
    end
  endtask

  integer n_space;
  initial begin
    if (!$value$plusargs("ERR=%d", err)) err = 0;
    if (!$value$plusargs("NFR=%d", nfr)) nfr = 24;
    if (!$value$plusargs("SEED=%d", seed)) seed = 1;
    if (!$value$plusargs("SPACEEVERY=%d", spacee)) spacee = 7;
    if (nfr > FMAX) nfr = FMAX;
    rnd = seed; n_sent = 0;
    bt = 1.0e9 / 115200.0 * (1000.0 + err) / 1000.0;
    $display("# fpga_uart err=%0d/1000 nfr=%0d seed=%0d spaceevery=%0d", err, nfr, seed, spacee);
    repeat (8) @(posedge clk); rst_n = 1;
    wait (pc_done === 1'b1);
    // drain: the board answers 2 bytes per frame at the same baud
    #(BT_RX * 10 * (2 * nfr + 8));
    n_space = 0;
    for (f = 0; f < n_sent; f = f + 1) if (sp[f]) n_space = n_space + 1;
    if (n_got != 2 * n_sent)
      $display("*** FAIL fpga_uart: %0d byte(s) back for %0d frame(s) -- expected EXACTLY %0d",
               n_got, n_sent, 2 * n_sent);
    else if (n_bad != 0)
      $display("*** FAIL fpga_uart: %0d byte(s) differ", n_bad);
    else if (led[4] !== 1'b0 || led[3] !== 1'b0)
      $display("*** FAIL fpga_uart: FIFO overflow (%b) or chip status error (%b)", led[4], led[3]);
    else
      $display("FPGA-UART: ok -- %0d frame(s) (%0d framing-error frames) at 115200 x (1%+0d/1000): %0d byte(s) back, exact, every one as sent",
               n_sent, n_space, err, n_got);
    $finish;
  end
endmodule
`default_nettype wire
