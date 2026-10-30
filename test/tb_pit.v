// tb_pit -- v2 PIT chunk 1: the SNIFF-mode capture, checked BIT FOR BIT against
// model/pit_capture_golden.py by test/run_pit_capture.py.
//   +IMG=<sniff image .hex> +NBYTES=512 +STIM=<stimulus> +OUT=<dump> +NCYC=<n>
// The stimulus: one line per uio change, "<cycles after the PIT starts> <hex>".
// The bench logs every change of the MASKED synchronised bus (dut.uio_q1) as
// "E <pit cycle> <hex changed-mask>" -- cycle 0 = the PIT's first cycle, the
// numbering pit_capture_golden.encode takes -- then dumps store 0..511 as
// "M <addr> <hex>".
`timescale 1ns / 1ps

`include "test/imgload.vh"
module tb_pit;

  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00, uio_drv = 8'h00;
  wire [7:0] uo_out, uio_out, uio_oe;
  wire [7:0] uio_in = (uio_oe & uio_out) | (~uio_oe & uio_drv);
`include "test/store_filler.vh"
  localparam integer IMG_MAX = PE_STORE_BYTES;
  localparam integer PIN_PROG = 7, PIN_PTR = 5, PIN_WR = 6;

  reg  [7:0] img [0:IMG_MAX-1];
  integer    img_bytes, i, ncyc, fd, sfd, pc = -1, a, n_st, st_cyc, st_val, r, s0wait;
  reg [8*256-1:0] imgfile, stimfile, outfile;
  reg [7:0]  prevq, mk;
  reg        done = 1'b0;

  always #10 clk = ~clk;

  tt_um_protocol_emulator #(.SPL(2)) dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );

  // the edge log, from the bench's own view of the synchronised bus
  always @(posedge clk) if (rst_n === 1'b1 && !done) begin
    if (dut.pit_run === 1'b1) begin
      mk = (dut.pit_mask == 8'h00) ? 8'hFF : dut.pit_mask;
      if (pc < 0) begin
        pc = 0;
        prevq = dut.uio_q1;
        // the starting levels the capture must write to byte 39 (Wilson 10-29)
        $fdisplay(fd, "L %h", dut.uio_q1 & mk);
      end else begin
        pc = pc + 1;
        if (((dut.uio_q1 ^ prevq) & mk) != 8'h00)
          $fdisplay(fd, "E %0d %h", pc, (dut.uio_q1 ^ prevq) & mk);
        prevq = dut.uio_q1;
      end
    end
  end

  initial begin
    if (!$value$plusargs("IMG=%s", imgfile)) begin $display("tb_pit: FATAL -- +IMG required"); $finish; end
    if (!$value$plusargs("NBYTES=%d", img_bytes)) begin $display("tb_pit: FATAL -- +NBYTES required"); $finish; end
    if (!$value$plusargs("STIM=%s", stimfile)) begin $display("tb_pit: FATAL -- +STIM required"); $finish; end
    if (!$value$plusargs("OUT=%s", outfile)) begin $display("tb_pit: FATAL -- +OUT required"); $finish; end
    if (!$value$plusargs("NCYC=%d", ncyc)) ncyc = 200000;
    // +S0WAIT=1: end as soon as stage 0 (chunk 2) has written its table
    if (!$value$plusargs("S0WAIT=%d", s0wait)) s0wait = 0;
    $readmemh(imgfile, img);
    `PE_REQUIRE_IMG_LOADED(imgfile)
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
    // a first line at a NEGATIVE cycle is the bus's level BEFORE the PIT
    // starts (the start-levels byte, coverage 10-29); otherwise the bus is 0
    sfd = $fopen(stimfile, "r");
    st_cyc = 0;
    r = $fscanf(sfd, "%d %h\n", st_cyc, st_val);
    uio_drv = (r == 2 && st_cyc < 0) ? st_val[7:0] : 8'h00;
    ui_in[PIN_PROG] = 1'b0;
    ui_in = 8'h00;
    // wait for the PIT to start, then play the stimulus on its own clock
    while (pc < 0) @(negedge clk);
    if (r == 2 && st_cyc >= 0) begin
      while (pc < st_cyc) @(negedge clk);
      uio_drv = st_val[7:0];
    end
    while (!$feof(sfd)) begin
      r = $fscanf(sfd, "%d %h\n", st_cyc, st_val);
      if (r == 2) begin
        while (pc < st_cyc) @(negedge clk);
        uio_drv = st_val[7:0];
      end
    end
    $fclose(sfd);
    while (pc < ncyc && !(s0wait != 0 && dut.u_s0.done === 1'b1)) @(negedge clk);
    done = 1'b1;
    // generate-block scopes need constant indices: one loop per bank
    for (a = 0; a < IMG_MAX / 4; a = a + 1) begin
      $fdisplay(fd, "M %0d %h", 4 * a + 0, dut.u_store.g_bank[0].mem[a]);
      $fdisplay(fd, "M %0d %h", 4 * a + 1, dut.u_store.g_bank[1].mem[a]);
      $fdisplay(fd, "M %0d %h", 4 * a + 2, dut.u_store.g_bank[2].mem[a]);
      $fdisplay(fd, "M %0d %h", 4 * a + 3, dut.u_store.g_bank[3].mem[a]);
    end
    $fdisplay(fd, "X stopped=%0d", dut.pit_stopped);
    $fdisplay(fd, "S s0done=%0d pc=%0d", dut.u_s0.done, pc);
    $fclose(fd);
    $display("tb_pit: %0d PIT cycles -> %0s", pc, outfile);
    $finish;
  end
endmodule
