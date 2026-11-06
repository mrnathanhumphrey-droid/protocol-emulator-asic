// tb_rt -- v2 PIT item 2 (Wilson 11-06): THE ROUND-TRIP BENCH. Two chips on one
// board: `dut` EMULATES (an image pe_asm assembled from the emitted spec, fed
// by the one host-channel driver, test/host_feed.vh), `snf` SNIFFS the wires
// it drives. test/run_pit_rt.py compares snf's records with the originals.
//   +EIMG=<emulator image> +IMG=<sniff image> +NBYTES=512 +OUT=<dump> +NCYC=<n>
//   +FEED=<bytes, one hex per line, queue 0>  +ROUTE=<16 hex digits>  +WARM=<cycles>
// ROUTE: one byte per SNIFFED wire w (bits 8w+7..8w), how the board connects it:
//   0x00 tied low, 0x30 tied high, 0x1k dut's uo_out[k] (push-pull),
//   0x2k dut's uio[k] -- the bus line, pulled up, low while dut drives it low.
// The emulator starts first; `snf` leaves load mode WARM cycles later, so its
// capture opens on a settled line (its start-levels byte reads the idle).
// The sniffer side logs and dumps EXACTLY tb_pit's format (L / E / K / M / P /
// X / S lines), so the pit gates' readers parse it unchanged.
`timescale 1ns / 1ps

`include "test/imgload.vh"
`define HF_PAT_N 4096
module tb_rt;

  reg        clk = 0, rst_n = 0, ena = 1;
  // the EMULATOR: named `dut` -- host_feed.vh and progress.vh address it
  reg  [7:0] ui_in = 8'h00, uio_drv = 8'h00;
  wire [7:0] uo_out, uio_out, uio_oe;
  wire [7:0] uio_in = (uio_oe & uio_out) | (~uio_oe & uio_drv);
  // the SNIFFER
  reg  [7:0] s_ui = 8'h00, s_drv = 8'h00;
  reg        s_load = 1'b1;
  wire [7:0] s_uo, s_uio_out, s_uio_oe;
  reg  [63:0] route = 64'd0;
  reg  [7:0] wires;
  integer    rw;
  always @(*) for (rw = 0; rw < 8; rw = rw + 1)
    case (route[8 * rw + 4 +: 4])
      4'h1: wires[rw] = uo_out[route[8 * rw +: 3]];
      4'h2: wires[rw] = uio_in[route[8 * rw +: 3]];
      4'h3: wires[rw] = 1'b1;
      default: wires[rw] = 1'b0;
    endcase
  wire [7:0] s_uio_in = s_load ? s_drv : wires;

`include "test/store_filler.vh"
  localparam integer IMG_MAX = PE_STORE_BYTES;
  localparam integer PIN_PROG = 7, PIN_PTR = 5, PIN_WR = 6;

  reg  [7:0] eimg [0:IMG_MAX-1];
  reg  [7:0] img [0:IMG_MAX-1];
  reg  [7:0] pre [0:IMG_MAX-1];
  reg        snap = 1'b0;
  integer    sa;
  always @(posedge clk) if (rst_n === 1'b1 && !snap && snf.u_s0.u_s12.s3_rec_wr === 1'b1) begin
    snap <= 1'b1;
    for (sa = 0; sa < IMG_MAX; sa = sa + 1) pre[sa] <= snf.u_store.g_mem.peek(sa[8:0]);
  end
  integer    img_bytes, i, ncyc, fd, ffd, pc = -1, a, r, warm, nfeed;
  reg [8*256-1:0] imgfile, eimgfile, outfile, feedfile;
  reg [7:0]  prevq, mk, fb;
  reg        done = 1'b0;

  `include "test/pe_clock.vh"

  always #(PE_CLK_HALF_NS) clk = ~clk;   // the target's clock, never typed

  tt_um_protocol_emulator #(.SPL(2)) dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );
  tt_um_protocol_emulator #(.SPL(2)) snf (
      .ui_in(s_ui), .uo_out(s_uo),
      .uio_in(s_uio_in), .uio_out(s_uio_out), .uio_oe(s_uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );

`include "test/progress.vh"
`include "test/host_feed.vh"

  // the sniffer's edge log: tb_pit's, on `snf`
  always @(posedge clk) if (rst_n === 1'b1 && !done) begin
    if (snf.pit_run === 1'b1) begin
      mk = (snf.pit_mask == 8'h00) ? 8'hFF : snf.pit_mask;
      if (pc < 0) begin
        pc = 0;
        prevq = snf.uio_q1;
        $fdisplay(fd, "L %h", snf.uio_q1 & mk);
      end else begin
        pc = pc + 1;
        if (((snf.uio_q1 ^ prevq) & mk) != 8'h00)
          $fdisplay(fd, "E %0d %h", pc, (snf.uio_q1 ^ prevq) & mk);
        prevq = snf.uio_q1;
        if (snf.ck_arm === 1'b1) $fdisplay(fd, "K %0d", pc);
      end
    end
  end

  initial begin
    if (!$value$plusargs("IMG=%s", imgfile)) begin $display("tb_rt: FATAL -- +IMG required"); $finish; end
    if (!$value$plusargs("EIMG=%s", eimgfile)) begin $display("tb_rt: FATAL -- +EIMG required"); $finish; end
    if (!$value$plusargs("NBYTES=%d", img_bytes)) begin $display("tb_rt: FATAL -- +NBYTES required"); $finish; end
    if (!$value$plusargs("OUT=%s", outfile)) begin $display("tb_rt: FATAL -- +OUT required"); $finish; end
    if (!$value$plusargs("ROUTE=%h", route)) begin $display("tb_rt: FATAL -- +ROUTE required"); $finish; end
    if (!$value$plusargs("NCYC=%d", ncyc)) ncyc = 200000;
    if (!$value$plusargs("WARM=%d", warm)) warm = 2000;
    $readmemh(imgfile, img);
    begin : chk_snf
      `PE_REQUIRE_IMG_LOADED(imgfile)
    end
    $readmemh(eimgfile, eimg);
    begin : chk_emu
      `PE_REQUIRE_IMG_LOADED(eimgfile)
    end
    // the host's byte stream for queue 0 (the spec's frames, CRCs included)
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
    // load the EMULATOR
    ui_in[PIN_PROG] = 1'b1;
    repeat (3) @(negedge clk); ui_in[PIN_PTR] = 1'b1; repeat (3) @(negedge clk);
    ui_in[PIN_PTR] = 1'b0; repeat (3) @(negedge clk);
    for (i = 0; i < img_bytes; i = i + 1) begin
      uio_drv = eimg[i];
      @(negedge clk); @(negedge clk);
      ui_in[PIN_WR] = 1'b1;
      @(negedge clk); @(negedge clk); @(negedge clk);
      ui_in[PIN_WR] = 1'b0;
      @(negedge clk);
    end
    // load the SNIFFER (it stays in load mode until the line has settled)
    s_ui[PIN_PROG] = 1'b1;
    repeat (3) @(negedge clk); s_ui[PIN_PTR] = 1'b1; repeat (3) @(negedge clk);
    s_ui[PIN_PTR] = 1'b0; repeat (3) @(negedge clk);
    for (i = 0; i < img_bytes; i = i + 1) begin
      s_drv = img[i];
      @(negedge clk); @(negedge clk);
      s_ui[PIN_WR] = 1'b1;
      @(negedge clk); @(negedge clk); @(negedge clk);
      s_ui[PIN_WR] = 1'b0;
      @(negedge clk);
    end
    // run the emulator: the bus pulled up, the host feeding queue 0
    ui_in[PIN_PROG] = 1'b0;
    uio_drv = 8'hFF;
    hf_en = (nfeed > 0);
    repeat (warm) @(negedge clk);
    // the sniffer sees the board's wires from here on, then starts
    s_load = 1'b0;
    @(negedge clk);
    s_ui = 8'h00;
    while (pc < ncyc && snf.u_s0.done !== 1'b1) @(negedge clk);
    done = 1'b1;
    repeat (2) @(negedge clk);
    for (a = 0; a < IMG_MAX; a = a + 1)
      $fdisplay(fd, "M %0d %h", a, snf.u_store.g_mem.peek(a[8:0]));
    if (snap) for (a = 0; a < IMG_MAX; a = a + 1) $fdisplay(fd, "P %0d %h", a, pre[a]);
    $fdisplay(fd, "X stopped=%0d", snf.pit_stopped);
    $fdisplay(fd, "S s0done=%0d pc=%0d s12done=%0d", snf.u_s0.tbl_done, pc, snf.u_s0.done);
    $fdisplay(fd, "H pushes=%0d bytes=%0d pops=%0d underrun=%b full=%0d", hf_pushes, hf_bytes, hf_pops,
              dut.u_eng.lane_underrun, dut.tx_full_sticky);
    $fclose(fd);
    $display("tb_rt: %0d sniffer PIT cycles, %0d host bytes -> %0s", pc, hf_bytes, outfile);
    $finish;
  end
endmodule
