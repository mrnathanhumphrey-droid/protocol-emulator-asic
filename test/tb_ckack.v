/* tb_ckack.v -- RULING ACK (b)-(c): a CLOCKED I2C read against a real peer,
 * dumped for sigrok.
 *
 * Driven by `test/run_ckack.py`, which owns the arms and the verdicts. The
 * program (built there) is two transactions per loop:
 *     S | dev W | A | addr hi | A | addr lo | A | P
 *     S | dev R | A | data in | master ACK | data in | master NACK | P
 * every byte and every ACK slot a SELF-CLOCKED action, so every SCL edge is
 * the chip's own and every bit it receives is captured on the OBSERVED rise.
 *
 * ⭐ THE PEER IS STIMULUS ONLY (AC1). `fram_i2c` puts its two bytes on the
 * wire; sigrok decodes the wire; the gate compares the CHIP's received bytes
 * against SIGROK's decode. With LATE > 0 the peer holds SCL low and presents
 * each read bit only at the end of the hold, so a sampler on the controller's
 * own release reads the line before the bit is there.
 *
 * Prints, for the runner:
 *   RX cyc=<n> cnt=<a_cnt> data=<hh>   every byte the chip delivered from
 *                                      lane 0 (cnt 1 = an ACK slot, 8 = data)
 *   PARK max=<cycles>                  the longest the lane sat parked on an
 *                                      observed rise (vs the stretch timeout)
 *   STICKY clk_stretch_err=<b> config_err=<b> underrun=<b>
 * and writes one byte per cycle to +DUMP: bit0 = SCL, bit1 = SDA.
 */

`default_nettype none
`timescale 1ns / 1ps

`include "test/imgload.vh"
module tb_ckack;

  parameter integer LATE = 0;
  parameter integer LATE_SKIP = 0;
  parameter integer LATE_ONCE = 0;

  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00;
  wire [7:0] uo_out, uio_out, uio_oe;

  localparam integer PIN_PROG = 7, PIN_PTR = 5, PIN_WR = 6;
  localparam integer IMG_MAX  = 256;
  localparam integer P_SDA = 2, P_SCL = 1;

  reg  [7:0] img [0:IMG_MAX-1];
  integer    img_bytes, i, cyc, ncyc, fd, nwr, park_now, park_max, n_rx;
  reg [8*256-1:0] imgfile, dumpfile;

  // ---- the resolved open-drain bus (as tb_i2c) --------------------------
  wire dut_sda_low = uio_oe[P_SDA] && !uio_out[P_SDA];
  wire dut_scl_low = uio_oe[P_SCL] && !uio_out[P_SCL];
  wire peer_sda_low, peer_scl_low;
  wire sda = !(dut_sda_low || peer_sda_low);
  wire scl = !(dut_scl_low || peer_scl_low);

  reg  [7:0] uio_drv;
  wire [7:0] uio_in = uio_drv;
  always @(*) begin
    uio_drv = 8'hFF;
    uio_drv[P_SDA] = sda;
    uio_drv[P_SCL] = scl;
  end

  always #10 clk = ~clk;

  tt_um_protocol_emulator #(.SPL(2)) dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );

  fram_i2c #(.DEV_SEL(3'b000), .STRETCH(0), .LATE(LATE),
             .LATE_SKIP(LATE_SKIP), .LATE_ONCE(LATE_ONCE)) peer (
      .clk(clk), .scl_in(scl), .sda_in(sda),
      .sda_oe(peer_sda_low), .scl_oe(peer_scl_low)
  );

`include "test/progress.vh"
`include "test/clocked_conform.vh"
`include "test/host_feed.vh"

  initial begin
    if (!$value$plusargs("IMG=%s", imgfile)) begin
      $display("tb_ckack: FATAL -- +IMG=<file> is required."); $finish;
    end
    if (!$value$plusargs("NBYTES=%d", img_bytes)) begin
      $display("tb_ckack: FATAL -- +NBYTES=<n> is required."); $finish;
    end
    if (!$value$plusargs("DUMP=%s", dumpfile)) begin
      $display("tb_ckack: FATAL -- +DUMP=<file> is required."); $finish;
    end
    if (!$value$plusargs("NCYC=%d", ncyc)) begin
      $display("tb_ckack: FATAL -- +NCYC=<n> is required."); $finish;
    end
    $readmemh(imgfile, img);
    `PE_REQUIRE_IMG_LOADED(imgfile)

    // ⭐ THE TWO BYTES THE PEER WILL DRIVE, both NON-PALINDROMIC (ruling 1b):
    // 0x5B reverses to 0xDA, 0xE2 to 0x47 -- so a byte that arrives in the
    // wrong bit order is a different byte, not the same one.
    peer.mem[15'h0123] = 8'h5B;
    peer.mem[15'h0124] = 8'hE2;
    // ⚠ AND THE ADDRESS REGISTER, which the model never resets: a program
    // that READS before it writes an address (the swept `ckread` arm) would
    // otherwise read mem[X] and put X on SDA -- measured, `data=xx`
    peer.addr = 15'h0123;

    // ⭐ EACH SHIFT's QUEUE TAG SUPPLIES THE *NEXT* SHIFT's BYTE: the host
    // load runs at the end of a byte, so the byte a SHIFT emits was popped
    // by the SHIFT before it. The runner tags the actions accordingly:
    //   q0 dev W  (A0 -- or A2, an address nobody answers, on the NACK arm)
    //   q1 the two address bytes, 01 then 23
    //   q2 dev R  (A1 -- or A3)
    //   q3 the master's ACK (2D, MSB 0) then NACK (C4, MSB 1)
    hf_init;
    if (!$value$plusargs("DEVW=%h", i)) i = 8'hA0;
    hf_set(0, i[7:0], i[7:0], i[7:0], i[7:0]);
    hf_set(1, 8'h01, 8'h23, 8'h01, 8'h23);
    if (!$value$plusargs("DEVR=%h", i)) i = 8'hA1;
    hf_set(2, i[7:0], i[7:0], i[7:0], i[7:0]);
    // ⭐ ONLY THE FIRST BIT (the MSB, on this MSB-first lane) of a 1-bit
    // SHIFT goes out, so ACK is any byte with MSB 0 and NACK any with MSB 1:
    // 2D and C4, NOT 00 and FF -- non-palindromic like every other payload
    // (ruling 1b), so a reversed lane would send the wrong ACK/NACK
    hf_set(3, 8'h2D, 8'hC4, 8'h2D, 8'hC4);

    cyc = 0; nwr = 0; park_now = 0; park_max = 0; n_rx = 0;
    fd = $fopen(dumpfile, "wb");
    if (fd == 0) begin
      $display("tb_ckack: FATAL -- cannot open %0s for writing", dumpfile);
      $finish;
    end
    $display("# ckack img=%0s bytes=%0d ncyc=%0d LATE=%0d SKIP=%0d ONCE=%0d",
             imgfile, img_bytes, ncyc, LATE, LATE_SKIP, LATE_ONCE);

    repeat (4) @(negedge clk);
    rst_n = 1;
    @(negedge clk);
    ui_in[PIN_PROG] = 1'b1;
    ui_in[PIN_PTR] = 1'b1; @(negedge clk);
    ui_in[PIN_PTR] = 1'b0; @(negedge clk);
    for (i = 0; i < img_bytes; i = i + 1) begin
      force uio_in = img[i];
      @(negedge clk); @(negedge clk);
      ui_in[PIN_WR] = 1'b1;
      @(negedge clk); @(negedge clk); @(negedge clk);
      ui_in[PIN_WR] = 1'b0;
      @(negedge clk);
    end
    release uio_in;
    ui_in[PIN_PROG] = 1'b0;
    ui_in = 8'h00;
    hf_en = 1'b1;

    for (i = 0; i < ncyc; i = i + 1) begin
      @(posedge clk);
      cyc = cyc + 1;
      $fwrite(fd, "%c", {6'b000000, sda, scl});
      nwr = nwr + 1;
      if (dut.u_eng.l_ckpark[0]) begin
        park_now = park_now + 1;
        if (park_now > park_max) park_max = park_now;
      end else begin
        park_now = 0;
      end
      if (dut.u_eng.rx_push && dut.u_eng.cur == 3'd0) begin
        $display("RX cyc=%0d cnt=%0d data=%02h", cyc, dut.u_eng.a_cnt,
                 dut.u_eng.rx_data);
        n_rx = n_rx + 1;
      end
    end
    $fclose(fd);
    hf_check(1);
    $display("PARK max=%0d", park_max);
    $display("STICKY clk_stretch_err=%0b config_err=%0b underrun=%0b hf_bad=%0d",
             dut.u_eng.clk_stretch_err, dut.u_eng.config_err,
             |dut.u_eng.lane_underrun, hf_bad);
    $display("END tb_ckack samples=%0d rx=%0d", nwr, n_rx);
    $finish;
  end

endmodule

`default_nettype wire
