// tb_gcd -- pieces 2-3's bench (Wilson 11-05): pe_pit_s12 started AT the GCD
// (G_INI) on a PRELOADED store of decoded messages [len][bytes...] from 128 --
// the only way to reach the capacity rule, which no real capture can.
//   +MEM=<512-line hex> +END=<end of messages, hex> +NMSG=<n> +OUT=<dump>
`timescale 1ns / 1ps
module tb_gcd;
  reg clk = 0, rst_n = 0, run = 0, go = 0;
  reg  [7:0] act = 0, roled = 0; reg refused = 0; reg [71:0] cnt_flat = 0;
  reg        p1_v = 0, wdone_p1 = 0; reg [7:0] p1_rm = 0, p1_lv = 0; reg [16:0] p1_civ = 0;
  wire       walk_go, hold, re, we, done, found, fb_short;
  wire [2:0] w; wire [8:0] waddr, raddr; wire [7:0] wdata, nmsg;
  reg  [7:0] rdata = 0;
  reg  [7:0] mem [0:511];
  reg  [7:0] pre [0:511];                       // the store as the record's last write starts
  reg        snap = 1'b0;
  integer    fd, a, sa, cyc, ncyc, endm, nm;
  reg [8*256-1:0] memfile, outfile;
  always #5 clk = ~clk;
  pe_pit_s12 #(.AW(9)) dut (
      .clk(clk), .rst_n(rst_n), .run(run), .go(go), .act(act), .roled(roled), .refused(refused),
      .cnt_flat(cnt_flat), .walk_go(walk_go), .hold(hold), .w(w),
      .p1_v(p1_v), .p1_rm(p1_rm), .p1_lv(p1_lv), .p1_civ(p1_civ), .wdone_p1(wdone_p1),
      .we(we), .waddr(waddr), .wdata(wdata), .done(done),
      .re(re), .raddr(raddr), .rdata(rdata), .s3_found(found), .s3_fbs(fb_short), .s3_nmsg(nmsg));
  always @(posedge clk) begin
    if (re) rdata <= mem[raddr];
    // only out of reset: rst_n starts LOW with no negedge, so in simulation the
    // async reset lands at the first posedge -- on silicon it clears `we` at
    // once. Measured 11-05 under the random start-up arm: a random `we` wrote
    // one byte (310 <- 82) at that first edge.
    if (we && rst_n) mem[waddr] <= wdata;
    // option (a) (Wilson 11-05): 128..135 are the record's, written LAST -- the
    // messages are checked from the store as that write starts
    if (rst_n && dut.s3_rec_wr === 1'b1 && !snap) begin
      snap <= 1'b1;
      for (sa = 0; sa < 512; sa = sa + 1) pre[sa] <= mem[sa];
    end
  end
  initial begin
    if (!$value$plusargs("MEM=%s", memfile) || !$value$plusargs("OUT=%s", outfile)
        || !$value$plusargs("END=%h", endm) || !$value$plusargs("NMSG=%d", nm)) begin
      $display("tb_gcd: FATAL -- +MEM +OUT +END +NMSG required"); $finish;
    end
    if (!$value$plusargs("NCYC=%d", ncyc)) ncyc = 50000000;
    $readmemh(memfile, mem);
    repeat (3) @(negedge clk); rst_n = 1; run = 1;
    @(negedge clk);
    // the state piece 1 leaves: stage 3 on wire 0, messages decoded up to `end`
    dut.st = 5'd17; dut.t3 = 7'd22; dut.dv_q[15:8] = 8'd0;
    dut.p[8:0] = endm[8:0]; dut.s3_found = 1'b1; dut.s3_fbs = 1'b0; dut.s3_nmsg = nm[7:0];
    cyc = 0;
    while (!done && cyc < ncyc) begin @(negedge clk); cyc = cyc + 1; end
    repeat (2) @(negedge clk);
    fd = $fopen(outfile, "w");
    for (a = 0; a < 512; a = a + 1) $fdisplay(fd, "M %0d %h", a, mem[a]);
    if (snap) for (a = 0; a < 512; a = a + 1) $fdisplay(fd, "P %0d %h", a, pre[a]);
    $fdisplay(fd, "N done=%0d cyc=%0d snap=%0d", done, cyc, snap);
    $fclose(fd);
    $finish;
  end
endmodule
