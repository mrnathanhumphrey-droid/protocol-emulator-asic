/* tb_usbdev.v -- v2 primitive 3, bundle 6 (Wilson 11-09, step 7a): the USB
 * device's reflexes against a host on the D- / D+ pair (uio[2] = D-, uio[3] =
 * D+; low speed: J = D- high, D+ low). Shared by `test/run_usbaddr.py` and
 * `test/run_usbrst.py`, which build the images, the host's packets and the
 * RP2040's pushes, predict every line below (their golden) and compare
 * exactly. The bench drives and records; it judges nothing.
 *
 * THE BUS. D- idles HIGH through the device's 1.5k pull-up (od_bus's
 * released level); D+ idles LOW through the host's 15k pull-down, modelled as
 * the bench driving 0 whenever neither the host script nor the device drives
 * it -- so a released bus is J, as on a real port. (tb_usbbuf releases both
 * lines HIGH, which only works there because its ARM watches D- falling.)
 *
 *   +IMG=<hex>    the image
 *   +HOST=<txt>   "P <A|R|H> <t> <n>" then n lines "<offset> <dm> <dp>"
 *                 (a level of 2 releases both). A = start at cycle t; R = t
 *                 cycles after the device's most recent release of D- that
 *                 came after this host's previous packet; H = t cycles after
 *                 this host's own previous packet released the bus.
 *   +LOAD=<txt>   RP2040 TX pushes "L <A|S|K> <t> <byte> <tag>". A = at cycle
 *                 t; S = t cycles after the device's NEXT drive start; K = t
 *                 cycles after the most recent host packet released the bus
 *                 (as of when the previous push finished).
 *   +NCYC=<n>     cycles to record after run entry
 *   +W0, +W1      the window (cycles) for the lane-0 dispatch count N0
 *
 * Prints, cycles counted from run entry:
 *   TX <c> <oe3 oe2> <out3 out2>  every change of the device's drive of D+/D-
 *   HP <c> <k> / HR <c> <k>       host packet k starts / releases
 *   LP <c> <tag> <byte>           an RP2040 byte pushed (its second nibble)
 *   RD <c> <0|1>                  every change of READY
 *   TF <c>                        the TX-full refusal bit rising
 *   AD <c> <addr>                 every change of the device address
 *   PV <c> <pv> <pend>            every change of the pending address
 *   FE <c> <0|1>                  every change of the reset fence
 *   BR <c>                        the bus-reset pulse
 *   RN <c>                        a kind-5 (reset notice) frame starts on the RX link
 *   SV <c> <hex>                  every change of the USB state vector
 *   AF <c>                        an ARM firing on lane 0
 *   N0 <n>                        lane-0 dispatches inside [W0, W1)
 *   END
 */

`default_nettype none
`timescale 1ns / 1ps

`include "test/imgload.vh"
module tb_usbdev;

  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00;
  reg  [7:0] uio_drv = 8'h00;
  reg  [7:0] uio_oe_tb = 8'h00;
  wire [7:0] uo_out, uio_out, uio_oe;
  wire [7:0] uio_in;
  reg        run_go = 1'b0;

  localparam integer DM = 2, DP = 3;
  // the host's D+ pull-down: active in RUN when neither side drives D+
  wire       dp_pd  = run_go & ~uio_oe_tb[DP] & (uio_oe[DP] !== 1'b1);
  wire [7:0] ob_oe  = uio_oe_tb | (dp_pd ? (8'h01 << DP) : 8'h00);
  wire [7:0] ob_val = dp_pd ? (uio_drv & ~(8'h01 << DP)) : uio_drv;
`include "test/od_bus.vh"

  `include "test/pe_clock.vh"

  always #(PE_CLK_HALF_NS) clk = ~clk;

`include "test/store_filler.vh"
  localparam integer IMG_MAX = PE_STORE_BYTES;
  reg [7:0] img [0:IMG_MAX-1];
  integer   img_bytes;
  reg [8*256-1:0] imgfile, hostfile, loadfile;

  localparam integer PIN_PROG = 7;
  localparam integer PIN_PTR  = 5;
  localparam integer PIN_WR   = 6;

  integer i, k, cyc, ncyc, w0, w1, n0;
  reg [3:0] prev_drv;
  reg prev_rd, prev_tf, prev_fe, prev_pv;
  reg [6:0] prev_ad, prev_pe;
  reg [31:0] prev_sv;
  reg [3:0]  prev_sc = 4'd0;
  integer dev_rel_n = 0, dev_drv_n = 0;       // device D- releases / drive starts seen
  integer dev_rel_cyc = 0;
  integer host_rel_cyc = 0;

  wire [31:0] sv = {dut.usb_addr, dut.usb_apend, dut.usb_apv, dut.usb_fence,
                    dut.ub_ready, dut.ub_wp, dut.ub_len, dut.ub_ep};

  task load_and_run;
    begin
      @(negedge clk);
      ui_in = 8'h00; uio_oe_tb = 8'h00; uio_drv = 8'h00;
      rst_n = 0;
      repeat (4) @(posedge clk);
      @(negedge clk); rst_n = 1;
      @(posedge clk);
      @(negedge clk); ui_in[PIN_PROG] = 1'b1;
      uio_oe_tb = 8'hFF;
      repeat (3) @(posedge clk); @(negedge clk); ui_in[PIN_PTR] = 1'b1; repeat (3) @(posedge clk);
      @(negedge clk); ui_in[PIN_PTR] = 1'b0; repeat (3) @(posedge clk);
      for (i = 0; i < img_bytes; i = i + 1) begin
        @(negedge clk); uio_drv = img[i];
        @(posedge clk); @(posedge clk);
        @(negedge clk); ui_in[PIN_WR] = 1'b1;
        @(posedge clk); @(posedge clk); @(posedge clk);
        @(negedge clk); ui_in[PIN_WR] = 1'b0;
        @(posedge clk);
      end
      // RUN: the bus idles at J (D- pulled up, D+ pulled down)
      @(negedge clk); ui_in[PIN_PROG] = 1'b0;
      uio_oe_tb = 8'h00;
      uio_drv   = 8'hFF;
      run_go    = 1'b1;
    end
  endtask

  initial begin
    if (!$value$plusargs("IMG=%s", imgfile)) imgfile = "none";
    if (!$value$plusargs("HOST=%s", hostfile)) hostfile = "none";
    if (!$value$plusargs("LOAD=%s", loadfile)) loadfile = "none";
    if (!$value$plusargs("NCYC=%d", ncyc)) ncyc = 2000;
    if (!$value$plusargs("W0=%d", w0)) w0 = 0;
    if (!$value$plusargs("W1=%d", w1)) w1 = 0;
    $readmemh(imgfile, img);
    `PE_REQUIRE_IMG_LOADED(imgfile)
    img_bytes = 0;
    for (i = 0; i < IMG_MAX; i = i + 1)
      if (^img[i] !== 1'bx) img_bytes = i + 1;
    hf_init;                     // no background feeding: the LOAD script pushes
    load_and_run;
    cyc = 0; n0 = 0;
    prev_drv = {uio_oe[3:2], uio_out[3:2]};
    prev_rd = dut.ub_ready; prev_tf = dut.tx_full_sticky;
    prev_ad = dut.usb_addr; prev_pe = dut.usb_apend; prev_pv = dut.usb_apv;
    prev_fe = dut.usb_fence; prev_sv = sv;
    for (k = 0; k < ncyc; k = k + 1) begin
      @(posedge clk); cyc = cyc + 1;
      if ({uio_oe[3:2], uio_out[3:2]} !== prev_drv) begin
        $display("TX %0d %b%b %b%b", cyc, uio_oe[3], uio_oe[2], uio_out[3], uio_out[2]);
        if (uio_oe[2] === 1'b1 && prev_drv[2] !== 1'b1) dev_drv_n = dev_drv_n + 1;
        if (uio_oe[2] !== 1'b1 && prev_drv[2] === 1'b1) begin
          dev_rel_n = dev_rel_n + 1; dev_rel_cyc = cyc;
        end
      end
      prev_drv = {uio_oe[3:2], uio_out[3:2]};
      if (dut.ub_ready !== prev_rd) $display("RD %0d %0d", cyc, dut.ub_ready);
      prev_rd = dut.ub_ready;
      if (dut.tx_full_sticky === 1'b1 && prev_tf !== 1'b1) $display("TF %0d", cyc);
      prev_tf = dut.tx_full_sticky;
      if (dut.usb_addr !== prev_ad) $display("AD %0d %0d", cyc, dut.usb_addr);
      prev_ad = dut.usb_addr;
      if (dut.usb_apv !== prev_pv || dut.usb_apend !== prev_pe)
        $display("PV %0d %0d %0d", cyc, dut.usb_apv, dut.usb_apend);
      prev_pv = dut.usb_apv; prev_pe = dut.usb_apend;
      if (dut.usb_fence !== prev_fe) $display("FE %0d %0d", cyc, dut.usb_fence);
      prev_fe = dut.usb_fence;
      if (sv !== prev_sv) $display("SV %0d %h", cyc, sv);
      prev_sv = sv;
      if (dut.e_usb_brst === 1'b1) $display("BR %0d", cyc);
      // the frame itself, as loaded into the serialiser: {marker 0, kind 5, 0x00}
      if (dut.ser_cnt === 4'd12 && prev_sc !== 4'd12 && dut.ser_sh === 12'h500)
        $display("RN %0d", cyc);
      prev_sc = dut.ser_cnt;
      if (dut.u_eng.arm_hit[0] === 1'b1) $display("AF %0d", cyc);
      if (dut.u_eng.st === 2'd2 && dut.u_eng.cur === 3'd0 && cyc >= w0 && cyc < w1) n0 = n0 + 1;
`ifdef USBDEV_DBG
      if (dut.u_eng.st === 2'd2 && dut.u_eng.cur === 3'd0)
        $display("DBG %0d pc=%0d op=%0d pin=%0d nb=%0d pid=%h sok=%b tok=%b crc=%b aok=%b rd=%b",
                 cyc, dut.u_eng.l_pc[0], dut.u_eng.a_op, dut.u_eng.a_pin, dut.u_eng.usb_nb,
                 dut.u_eng.usb_pid, dut.u_eng.usb_sok, dut.u_eng.usb_tok, dut.u_eng.usb_crc_ok,
                 dut.u_eng.usb_aok_v, dut.u_eng.usb_ready_v);
`endif
      @(negedge clk);
    end
    $display("N0 %0d", n0);
    $display("END");
    $finish;
  end

  // ---- THE HOST: packets on D- / D+ ----------------------------------------
  integer hfd, hok, hn, hj, hk, hrel_seen, hlast;
  real    ht, hstart, hoff;
  integer hdm, hdp;
  reg [8*2-1:0] hmode;
  initial begin : host
    wait (run_go === 1'b1);
    hfd = $fopen(hostfile, "r");
    hk = 0;
    hrel_seen = 0;
    hlast = 0;
    if (hfd != 0) begin
      hok = $fscanf(hfd, "P %s %f %d\n", hmode, ht, hn);
      while (hok == 3) begin
        if (hmode == "R") begin
          wait (dev_rel_n > hrel_seen);
          hstart = dev_rel_cyc + ht;
        end else if (hmode == "H") begin
          hstart = hlast + ht;
        end else begin
          hstart = ht;
        end
        while (cyc < hstart) @(negedge clk);
        $display("HP %0d %0d", cyc, hk);
        hstart = cyc;
        for (hj = 0; hj < hn; hj = hj + 1) begin
          hok = $fscanf(hfd, "%f %d %d\n", hoff, hdm, hdp);
          while (cyc < hstart + hoff) @(negedge clk);
          if (hdm == 2) begin
            uio_oe_tb[DM] = 1'b0; uio_oe_tb[DP] = 1'b0;
            uio_drv[DM] = 1'b1;   uio_drv[DP] = 1'b1;
          end else begin
            uio_oe_tb[DM] = 1'b1; uio_oe_tb[DP] = 1'b1;
            uio_drv[DM] = hdm[0]; uio_drv[DP] = hdp[0];
          end
        end
        $display("HR %0d %0d", cyc, hk);
        hlast = cyc;
        host_rel_cyc = cyc;
        hrel_seen = dev_rel_n;
        hk = hk + 1;
        hok = $fscanf(hfd, "P %s %f %d\n", hmode, ht, hn);
      end
    end
  end

  // ---- THE RP2040's TX pushes (tag 2 control, tag 3 buffer) -----------------
  integer lfd, lok, lt, lb, ltag, ldrv_seen, lstart;
  reg [8*2-1:0] lmode;
  initial begin : loader
    wait (run_go === 1'b1);
    lfd = $fopen(loadfile, "r");
    ldrv_seen = 0;
    if (lfd != 0) begin
      lok = $fscanf(lfd, "L %s %d %d %d\n", lmode, lt, lb, ltag);
      while (lok == 4) begin
        if (lmode == "S") begin
          ldrv_seen = dev_drv_n;               // the NEXT drive start, not one already past
          wait (dev_drv_n > ldrv_seen);
          lstart = cyc + lt;
        end else if (lmode == "K") begin
          lstart = host_rel_cyc + lt;
        end else begin
          lstart = lt;
        end
        while (cyc < lstart) @(negedge clk);
        hf_push_byte(lb[7:0], ltag[1:0]);
        $display("LP %0d %0d %0d", cyc, ltag, lb);
        lok = $fscanf(lfd, "L %s %d %d %d\n", lmode, lt, lb, ltag);
      end
    end
  end

  parameter integer SPL_CFG = 2;

  tt_um_protocol_emulator #(.SPL(SPL_CFG)) dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );

`include "test/host_feed.vh"
`include "test/progress.vh"

endmodule

`default_nettype wire
