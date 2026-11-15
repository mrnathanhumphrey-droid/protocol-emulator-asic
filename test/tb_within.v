// tb_within -- the `within` / `else` SIMULATION must-fires (Wilson 11-15, agent 2).
// One chip runs a program the poset compiler lowered with a window (host/poset/compile.py
// P4b); a PEER drives B. Driven by test/run_within_mf.py.
//   +IMG=<image> +NBYTES=<n> +OUT=<log> +NCYC=<n> +FEED=<host bytes, queue 0>
//   +CS=<uo_out index of A's wire>  +SCK=<uo_out index>  +B=<uio pin of B>
//   +DLY=<cycles>: the peer pulls B LOW this many cycles after each CS fall it sees,
//                  and releases it when CS rises (0 = the peer never answers)
// Log: A <cycle> (CS fall), B <cycle> (B pulled low), K <cycle> (an SCK edge),
//      T <cycle> (lane 0's timeout sticky rises), and a final
//      S cycles=<n> live0=<0|1> timeout0=<0|1> ovr=<0|1>.
// The load sequence and the host feed are tb_rt's emulator half (test/tb_rt.v).
`timescale 1ns / 1ps

`include "test/imgload.vh"
`define HF_PAT_N 4096
module tb_within;

  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00, uio_drv = 8'h00;
  wire [7:0] uo_out, uio_out, uio_oe;
  wire [7:0] uio_in = (uio_oe & uio_out) | (~uio_oe & uio_drv);

`include "test/store_filler.vh"
  localparam integer IMG_MAX = PE_STORE_BYTES;
  localparam integer PIN_PROG = 7, PIN_PTR = 5, PIN_WR = 6;

  reg  [7:0] img [0:IMG_MAX-1];
  integer    img_bytes, i, ncyc, fd, ffd, r, nfeed, cyc = 0;
  integer    cs_k, sck_k, b_k, dly, t_fall = -1;
  reg [8*256-1:0] imgfile, outfile, feedfile;
  reg [7:0]  fb;
  reg        running = 1'b0, cs_q = 1'b1, sck_q = 1'b0, to_q = 1'b0;

  `include "test/pe_clock.vh"

  always #(PE_CLK_HALF_NS) clk = ~clk;   // the target's clock, never typed

  tt_um_protocol_emulator #(.SPL(2)) dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );

`include "test/progress.vh"
`include "test/host_feed.vh"

  wire to0 = dut.u_eng.l_timeout_k[0] | dut.u_eng.l_timeout_m[0];

  // the PEER and the log, from the cycle the program starts
  always @(posedge clk) if (running) begin
    cyc <= cyc + 1;
    if (cs_q && !uo_out[cs_k]) begin
      $fdisplay(fd, "A %0d", cyc);
      t_fall <= cyc;
    end
    if (!cs_q && uo_out[cs_k]) begin
      t_fall <= -1;
      uio_drv[b_k] <= 1'b1;                        // released with CS
    end
    if (dly > 0 && t_fall >= 0 && cyc == t_fall + dly && !uo_out[cs_k]) begin
      uio_drv[b_k] <= 1'b0;                        // the peer answers: B falls
      $fdisplay(fd, "B %0d", cyc);
    end
    if (uo_out[sck_k] !== sck_q) $fdisplay(fd, "K %0d", cyc);
    if (to0 && !to_q) $fdisplay(fd, "T %0d", cyc);
    cs_q <= uo_out[cs_k];
    sck_q <= uo_out[sck_k];
    to_q <= to0;
  end

  initial begin
    if (!$value$plusargs("IMG=%s", imgfile)) begin $display("tb_within: FATAL -- +IMG required"); $finish; end
    if (!$value$plusargs("NBYTES=%d", img_bytes)) begin $display("tb_within: FATAL -- +NBYTES required"); $finish; end
    if (!$value$plusargs("OUT=%s", outfile)) begin $display("tb_within: FATAL -- +OUT required"); $finish; end
    if (!$value$plusargs("CS=%d", cs_k)) begin $display("tb_within: FATAL -- +CS required"); $finish; end
    if (!$value$plusargs("SCK=%d", sck_k)) begin $display("tb_within: FATAL -- +SCK required"); $finish; end
    if (!$value$plusargs("B=%d", b_k)) begin $display("tb_within: FATAL -- +B required"); $finish; end
    if (!$value$plusargs("DLY=%d", dly)) dly = 0;
    if (!$value$plusargs("NCYC=%d", ncyc)) ncyc = 20000;
    $readmemh(imgfile, img);
    begin : chk_img
      `PE_REQUIRE_IMG_LOADED(imgfile)
    end
    hf_init;
    nfeed = 0;
    if ($value$plusargs("FEED=%s", feedfile)) begin
      ffd = $fopen(feedfile, "r");
      while (!$feof(ffd) && nfeed < HF_PAT) begin
        r = $fscanf(ffd, "%h\n", fb);
        if (r == 1) begin hf_put(0, nfeed, fb); nfeed = nfeed + 1; end
      end
      $fclose(ffd);
      if (nfeed > 0) hf_n(0, nfeed);
    end
    fd = $fopen(outfile, "w");
    repeat (4) @(negedge clk);
    rst_n = 1;
    @(negedge clk);
    ui_in[PIN_PROG] = 1'b1;
    repeat (3) @(negedge clk); ui_in[PIN_PTR] = 1'b1; repeat (3) @(negedge clk);
    ui_in[PIN_PTR] = 1'b0; repeat (3) @(negedge clk);
    for (i = 0; i < img_bytes; i = i + 1) begin
      uio_drv = img[i];
      @(negedge clk); @(negedge clk);
      ui_in[PIN_WR] = 1'b1;
      @(negedge clk); @(negedge clk); @(negedge clk);
      ui_in[PIN_WR] = 1'b0;
      @(negedge clk);
    end
    // run: the bus pulled up (B idles high), the host feeding queue 0
    ui_in[PIN_PROG] = 1'b0;
    uio_drv = 8'hFF;
    hf_en = (nfeed > 0);
    running = 1'b1;
    while (cyc < ncyc) @(negedge clk);
    running = 1'b0;
    $fdisplay(fd, "S cycles=%0d live0=%0d timeout0=%0d ovr=%0d", cyc, dut.u_eng.l_live[0], to0,
              dut.u_eng.sticky_ovr);
    $fclose(fd);
    $finish;
  end
endmodule
