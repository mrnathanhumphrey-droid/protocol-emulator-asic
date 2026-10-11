/* tb_onewire.v -- CE5: the 1-Wire slot engine (pe_asm program on the FROZEN
 * RTL) against a behavioural DS18B20 (test/ds18b20_model.v, SAME-HAND).
 *
 * THE BUS. DQ is one open-drain net with a pull-up: the chip pulls it low on
 * uio[Q] (open-drain lane), the part pulls it low on its own, and a released
 * line comes back up after RISE_NS (the pull-up's rise, inertial: a release
 * shorter than RISE_NS never reaches high). The same net is wired to uio[Q]
 * AND uio[S]: the program samples on S (an unclocked SHIFTIN releases the
 * pin it samples, so it cannot sample the pin that holds a write-0 low).
 * The master's pad is delayed 1 ns so no bus edge lands ON a clock edge.
 *
 * THE HOST. A feed file (+FEED, from test/onewire.py) of 12-bit words:
 * `0xx` push byte xx on queue 0; `1xx` begins a 4-byte POLL GROUP (8 read
 * slots), which the host repeats until a byte it RECEIVED (decoded from the
 * 3-pin serial stream, index >= +POLLIDX) is non-zero -- Convert T's VDD-mode
 * completion. The pushes go through `host_feed.vh`'s one push task.
 *
 * RECEIVED BYTES ARE READ FROM THE PINS: `uo_out[6:4]` frames, kind 0, as a
 * host would (`OW-RX` lines, in order). Nothing reads the model's memory for
 * them; the model's ROM / scratchpad are printed separately (`OW-MODEL`) for
 * the gate to compare against.
 *
 * MEASURED HERE (the master's side; the model measures the part's side):
 *   OW-SAMPLE read      every SHIFTIN sample in a read slot, from the slot's
 *                       fall (sample instant = the SHIFTIN writeback - 2
 *                       cycles of input synchroniser): must be <= 15 us
 *   OW-SAMPLE presence  the first sample after a reset release, from the
 *                       release: must be in [60, 75] us -- the part is
 *                       guaranteed low there (waits 15..60, low 60..240)
 *   OW-INIT             the master's own low time in read slots (pad): >= 1 us
 *
 * Plusargs: IMG NBYTES FEED NFEED POLLIDX (required), NCYC_MAX
 * Parameters: RISE_NS (pull-up rise), Q, S, and the model's timing.
 * End token: `OW-BENCH: END` (printed only when the feed was consumed).
 */
`default_nettype none
`timescale 1ns / 1ps
`include "test/imgload.vh"
module tb_onewire;
  parameter integer RISE_NS = 503;
  parameter integer Q = 2;
  parameter integer S = 3;
  parameter integer T_PDH_NS = 30000;
  parameter integer T_PDL_NS = 120000;

  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00;
  wire [7:0] uo_out, uio_out, uio_oe;
  reg  [7:0] peer = 8'hFF;
  localparam integer PIN_PROG = 7, PIN_PTR = 5, PIN_WR = 6;
  localparam integer IMG_MAX = 256;
  localparam integer FEED_MAX = 1024;
  localparam integer SER_DATA = 4, SER_STRB = 5, SER_VLD = 6;
  localparam integer FRAME_BITS = 12;

  // ---- the 1-Wire bus ------------------------------------------------------
  reg loading = 1'b1;                          // load mode: uio is the data port
  wire m_low_raw = uio_oe[Q] & ~uio_out[Q];
  wire m_low;
  assign #1 m_low = m_low_raw;                 // off the clock edges
  wire dev_pull;
  wire pull_low = m_low | dev_pull;
  wire dq;
  assign #(RISE_NS, 0) dq = ~pull_low;         // released: up after RISE_NS
  wire [7:0] uio_in = loading ? peer
                     : ((peer & ~((8'h01 << Q) | (8'h01 << S)))
                        | ({7'd0, dq} << Q) | ({7'd0, dq} << S));
  // the model's read states, as LITERALS (a hierarchical reference to a
  // localparam is the trap progress.vh records): ds18b20_model.v S_TXROM = 3,
  // S_TXSP = 4, S_CONV = 5, S_PRES = 7
  wire ds_reading = (u_ds.state == 3) || (u_ds.state == 4) || (u_ds.state == 5);

  always #10 clk = ~clk;

  tt_um_protocol_emulator dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );

  ds18b20_model #(.T_PDH_NS(T_PDH_NS), .T_PDL_NS(T_PDL_NS)) u_ds (
      .dq(dq), .pull(dev_pull));

`include "test/progress.vh"
`include "test/host_feed.vh"

  reg  [7:0]  img [0:IMG_MAX-1];
  reg  [11:0] feed [0:FEED_MAX-1];
  integer     img_bytes, nfeed, pollidx, i, fi, g, cyc, ncyc_max;
  reg [8*256-1:0] imgfile, feedfile;

  // ---- the serial host view: decoded from the pins only --------------------
  reg  [11:0] fr_sh;
  integer     fr_cnt, n_rx, n_status;
  reg         prev_v, poll_active, poll_done;
  always @(posedge clk) begin
    if (rst_n !== 1'b1) begin
      fr_cnt = 0; prev_v = 1'b0;
    end else begin
      if (uo_out[SER_VLD] && !prev_v) begin fr_sh = 0; fr_cnt = 0; end
      if (uo_out[SER_VLD] && uo_out[SER_STRB] && fr_cnt < FRAME_BITS) begin
        fr_sh[fr_cnt] = uo_out[SER_DATA];
        fr_cnt = fr_cnt + 1;
      end
      if (!uo_out[SER_VLD] && prev_v && fr_cnt == FRAME_BITS) begin
        if (fr_sh[11]) n_status = n_status + 1;
        else if (fr_sh[10:8] == 3'd0) begin
          $display("OW-RX %0d %02h", n_rx, fr_sh[7:0]);
          if (poll_active && n_rx >= pollidx && fr_sh[7:0] != 8'h00)
            poll_done = 1'b1;
          n_rx = n_rx + 1;
        end
      end
      prev_v = uo_out[SER_VLD];
    end
  end

  // ---- master-side timing ---------------------------------------------------
  realtime t_mfall, t_mrise, t_rel, ts;
  reg      want_pres;
  integer  n_rd, n_pr, n_in;
  real     rd_mn, rd_mx, pr_mn, pr_mx, in_mn, in_mx;
  always @(posedge m_low) t_mfall = $realtime;
  always @(negedge m_low) begin
    t_mrise = $realtime;
    // a read slot's initiating low only: a reset pulse that STARTS while the
    // part is still in a read state is not one
    if (ds_reading && t_mrise - t_mfall < 60000.0) begin
      if (n_in == 0 || t_mrise - t_mfall < in_mn) in_mn = t_mrise - t_mfall;
      if (n_in == 0 || t_mrise - t_mfall > in_mx) in_mx = t_mrise - t_mfall;
      n_in = n_in + 1;
    end
  end
  // a reset release, as the part saw it
  always @(u_ds.state) if (u_ds.state == 7) begin
    t_rel = u_ds.t_rst_rise; want_pres = 1'b1;
  end

  // the sample instant: lane 0's SHIFTIN writeback (st == ST_WB = 2'd2, see
  // progress.vh for why the literal) minus the 2-flop input synchroniser
  always @(posedge clk) if (rst_n === 1'b1 && dut.u_eng.st === 2'd2
                            && dut.u_eng.cur == 0
                            && dut.u_eng.a_op === 3'd2) begin
    ts = $realtime - 40.0;
    if (want_pres) begin
      want_pres = 1'b0;
      if (n_pr == 0 || ts - t_rel < pr_mn) pr_mn = ts - t_rel;
      if (n_pr == 0 || ts - t_rel > pr_mx) pr_mx = ts - t_rel;
      n_pr = n_pr + 1;
    end else if (ds_reading && ts - t_mfall < 60000.0) begin
      if (n_rd == 0 || ts - t_mfall < rd_mn) rd_mn = ts - t_mfall;
      if (n_rd == 0 || ts - t_mfall > rd_mx) rd_mx = ts - t_mfall;
      n_rd = n_rd + 1;
    end
  end

  task push(input [7:0] b);
    begin
      while (dut.tx_cnt[0] == 2'd2 && cyc < ncyc_max) @(negedge clk);
      // past the cycle budget the run is already red; never push into a
      // full queue (that would be the FEEDER's tx_full, not the chip's)
      if (cyc < ncyc_max) hf_push_byte(b, 2'd0);
    end
  endtask

  initial begin
    if (!$value$plusargs("IMG=%s", imgfile)) begin
      $display("tb_onewire: FATAL -- +IMG=<file> is required."); $finish;
    end
    if (!$value$plusargs("NBYTES=%d", img_bytes)) begin
      $display("tb_onewire: FATAL -- +NBYTES=<n> is required."); $finish;
    end
    if (!$value$plusargs("FEED=%s", feedfile)) begin
      $display("tb_onewire: FATAL -- +FEED=<file> is required."); $finish;
    end
    if (!$value$plusargs("NFEED=%d", nfeed)) begin
      $display("tb_onewire: FATAL -- +NFEED=<n> is required."); $finish;
    end
    if (!$value$plusargs("POLLIDX=%d", pollidx)) begin
      $display("tb_onewire: FATAL -- +POLLIDX=<n> is required."); $finish;
    end
    if (!$value$plusargs("NCYC_MAX=%d", ncyc_max)) ncyc_max = 4000000;
    if (nfeed > FEED_MAX) begin
      $display("tb_onewire: FATAL -- feed of %0d words > %0d", nfeed, FEED_MAX); $finish;
    end
    n_rx = 0; n_status = 0; poll_active = 1'b0; poll_done = 1'b0; cyc = 0;
    n_rd = 0; n_pr = 0; n_in = 0; want_pres = 1'b0;
    rd_mn = 0; rd_mx = 0; pr_mn = 0; pr_mx = 0; in_mn = 0; in_mx = 0;
    $readmemh(imgfile, img);
    `PE_REQUIRE_IMG_LOADED(imgfile)
    // the feed is checked the same way, by hand: the macro names its block,
    // so it can appear once per scope
    if (feedfile[8*256-1 -: 8] != 8'h00) begin
      $display("*** FAIL tb_onewire: +FEED fills the 256-byte buffer (truncated?)"); $finish;
    end
    fi = $fopen(feedfile, "r");
    if (fi == 0) begin
      $display("*** FAIL tb_onewire: +FEED=%0s cannot be opened", feedfile); $finish;
    end
    $fclose(fi);
    $readmemh(feedfile, feed, 0, nfeed - 1);
    $display("# onewire img=%0s feed=%0s nfeed=%0d pollidx=%0d rise=%0d ns Q=%0d S=%0d",
             imgfile, feedfile, nfeed, pollidx, RISE_NS, Q, S);

    repeat (4) @(negedge clk);
    rst_n = 1;
    @(negedge clk);
    ui_in[PIN_PROG] = 1'b1;
    repeat (3) @(negedge clk); ui_in[PIN_PTR] = 1'b1; repeat (3) @(negedge clk);
    ui_in[PIN_PTR] = 1'b0; repeat (3) @(negedge clk);
    for (i = 0; i < img_bytes; i = i + 1) begin
      peer = img[i];
      @(negedge clk); @(negedge clk);
      ui_in[PIN_WR] = 1'b1;
      @(negedge clk); @(negedge clk); @(negedge clk);
      ui_in[PIN_WR] = 1'b0;
      @(negedge clk);
    end
    repeat (4) @(negedge clk);
    ui_in[PIN_PROG] = 1'b0;
    peer = 8'hFF;
    loading = 1'b0;
    repeat (4) @(negedge clk);

    // ---- the host: the feed, reactive only at the poll -------------------
    fi = 0;
    while (fi < nfeed && cyc < ncyc_max) begin
      if (feed[fi][8]) begin
        poll_active = 1'b1;
        g = 0;
        while (!poll_done && cyc < ncyc_max) begin
          push(feed[fi][7:0]); push(feed[fi + 1][7:0]);
          push(feed[fi + 2][7:0]); push(feed[fi + 3][7:0]);
          g = g + 1;
        end
        poll_active = 1'b0;
        $display("OW-POLL groups=%0d", g);
        fi = fi + 4;
      end else begin
        push(feed[fi][7:0]);
        fi = fi + 1;
      end
    end
    // the feed ends in IDLE bytes, so every real symbol is out by now; stop
    // ONE symbol later, well before the 2 queued bytes + the shift register
    // (6 symbols) run dry -- an underrun would hold DQ low (a reset, harmless
    // on the bus, but a STARVED run by the standing rule)
    repeat (6400) @(negedge clk);

    u_ds.report;
    $display("OW-SAMPLE read n=%0d min_ns=%0.1f max_ns=%0.1f hi_ns=15000.0",
             n_rd, rd_mn, rd_mx);
    $display("OW-SAMPLE presence n=%0d min_ns=%0.1f max_ns=%0.1f lo_ns=60000.0 hi_ns=75000.0",
             n_pr, pr_mn, pr_mx);
    $display("OW-INIT n=%0d min_ns=%0.1f max_ns=%0.1f lo_ns=1000.0",
             n_in, in_mn, in_mx);
    $display("OW-STICKY underrun=%0b rx_drop=%0b config_err=%0b tx_full=%0b",
             dut.u_eng.lane_underrun[0], dut.rx_drop_sticky,
             dut.u_eng.config_err, dut.tx_full_sticky);
    $display("OW-HOST pushes=%0d bytes=%0d pops=%0d rx=%0d status=%0d fed=%0d/%0d cyc=%0d",
             hf_pushes, hf_bytes, hf_pops, n_rx, n_status, fi, nfeed, cyc);
    if (fi >= nfeed) $display("OW-BENCH: END");
    else $display("*** FAIL tb_onewire: NCYC_MAX reached with the feed at %0d of %0d", fi, nfeed);
    $finish;
  end

  always @(posedge clk) if (rst_n === 1'b1 && !loading) begin
    cyc = cyc + 1;
    if (cyc % 250000 == 0) begin
      $display("# cyc %0d: fed %0d/%0d, rx %0d, model state %0d, config_err %0b, pops %0d",
               cyc, fi, nfeed, n_rx, u_ds.state, dut.u_eng.config_err, hf_pops);
      $fflush;
    end
  end
endmodule
