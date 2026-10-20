/* tb_spitgt.v -- the SPI-TARGET program against an SPI MASTER on its own
 * clock: MISO compared with what the HOST FED, at the master's own sampling
 * edges, count exact (Wilson 10-18 ruling; build plan step B3).
 *
 * ⛔ WHY A MASTER MODEL, NOT THE CORPUS `tgt` PEER. The corpus peer toggles
 * SCK every clock edge -- it exercises the async MISO release, not a target
 * answering a real master. Here the master runs SCK at a real rate on its own
 * real-time grid (edges never on a chip clock edge, as tb_uartrx), frames
 * transactions with CS and a stated tCSS / tCSH, and samples MISO where a
 * real master does. THE REFERENCE IS THE HOST FEED (host_feed.vh), not the
 * chip: every byte the master reads must be the next byte the host pushed.
 *
 * THE MASTER: modes 0-3 (CPOL = idle SCK level; CPHA 0 samples on the LEADING
 * edge and changes on the trailing, CPHA 1 the reverse). NTX back-to-back
 * transactions of NB bytes (MSB first); between them CS is high for GAP
 * cycles. MOSI carries an LCG byte stream (the MOSI variant checks the chip's
 * received bytes against it).
 *
 * MEASURED, every transaction:
 *   wire == feed       each sampled MISO bit vs the fed byte's bit, count exact
 *   oe with CS high    MISO's enable must be 0 whenever CS has been high a cycle
 *   edge -> MISO       cycles from a change-edge to the pad carrying a CHANGED
 *                      bit (worst, against D_tol 17)
 *   re-arm margin      cycles from the lane's ARM arming to the change-edge it
 *                      catches (minimum); an edge that finds it UNARMED is MISSED
 *   tCSS seen          CS fall -> the pad carrying bit 7 (CPHA 0 modes)
 * Plusargs: IMG NBYTES (required) MODE(0) HALF(25: SCK half period, cycles)
 *   NTX(8) NB(2) TCSS(30) TCSH(30) GAP(60) MOSI(0) NOFEED(0)
 *   SHORT(-1: this transaction's last byte gets 7 clocks -- the desync
 *   must-fire) RECOVER(0: after the short transaction the host reloads the
 *   program, the documented recovery) CSEARLY(0: CS rises this many cycles
 *   after the LAST CHANGE-EDGE instead of tCSH after the last edge)
 * Verdict: `SPI-TGT: ok -- ...` or `*** FAIL spi_tgt: ...`.
 */
`default_nettype none
`timescale 1ns / 1ps
`include "test/imgload.vh"
module tb_spitgt;
  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00;
  wire [7:0] uo_out, uio_out, uio_oe;
  localparam integer PIN_PROG = 7, PIN_PTR = 5, PIN_WR = 6;
  localparam integer IMG_MAX = 256;
  localparam integer P_SCK = 4, P_MOSI = 5, P_CS = 6, P_MISO = 7;
  localparam integer D_TOL = 17;

  // the pads the master drives; MISO is the chip's (pulled up when released)
  reg        sck = 1'b0, mosi = 1'b1, cs = 1'b1;
  reg  [7:0] loadbus = 8'hFF;
  reg        loading = 1'b0;
  wire       miso_bus = uio_oe[P_MISO] ? uio_out[P_MISO] : 1'b1;
  wire [7:0] uio_in = loading ? loadbus
                              : {miso_bus, cs, mosi, sck, 4'b1111};

  reg  [7:0] img [0:IMG_MAX-1];
  integer    img_bytes, i, cyc;
  reg [8*256-1:0] imgfile;
  integer    mode, half, ntx, nb, tcss, tcsh, gap, mosi_on, nofeed, shortk,
             recover, csearly;
  reg        cpol, cpha;

  always #10 clk = ~clk;

  tt_um_protocol_emulator dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );

`include "test/progress.vh"
// ⭐ THE RECOVERY ARM IS BUILT WITHOUT THE CONFORMANCE LAYERS
// (-DSPITGT_WIRE_ONLY), as tb_reload is: a reload mid-run is the event under
// test, and V3 / R4a book a reload as an unexplained slot change. The verdict
// there is what the master reads on the wire, exactly as tb_reload's is.
`ifndef SPITGT_WIRE_ONLY
`include "test/clocked_conform.vh"
`endif
`include "test/host_feed.vh"

  function [31:0] lcg(input [31:0] s);
    lcg = s * 32'd1103515245 + 32'd12345;
  endfunction

  // an absolute real time, never ON a chip clock edge
  real tq;
  task wait_until(input real t);
    begin
      tq = t;
      if (tq - 10.0 * $floor(tq / 10.0) < 0.5) tq = tq + 1.0;
      if (tq > $realtime) #(tq - $realtime);
    end
  endtask

  // ---- the expected MISO stream: the host's pushes to queue 0, in order ----
  // ⭐ THE HOST'S, NEVER THE CHIP'S (candidate #8's lesson). The feeder pushes
  // its 16-byte pattern in order, so stream byte p is pattern[(p + off) % 16];
  // `off` is re-anchored at a recovery (the reload flushes the queues, and the
  // next byte out is the next one the feeder pushes).
  integer    off;
  function [7:0] expb(input integer p);
    expb = hf_pat[0][(p + off) % 16];
  endfunction

  // ---- MEASUREMENTS --------------------------------------------------------
  integer n_undriven;
  integer n_bits, n_bytes_rd, n_bad, n_oe_cs, lat_max, lat_n, n_missed,
          margin_min, n_margin, tcss_seen, fails, rd_idx, bit_i, n_rx, n_rx_bad;
  reg [7:0] rd_byte, want_byte;
  real    te, t_armed, t_csfall;
  reg     lat_pend, armed_pend, want_bit, tcss_pend, skip_txn;
  reg     prev_armed;
  reg [7:0] mosi_sent [0:4095];
  integer n_mosi;

  // the lane's ARM arming (lane 0): when it rose, for the re-arm margin
  always @(posedge clk) begin
    if (rst_n === 1'b1 && !loading) begin
      if (dut.u_eng.l_armed[0] === 1'b1 && prev_armed !== 1'b1) begin
        t_armed = $realtime;
        armed_pend = 1'b1;
      end
      prev_armed = dut.u_eng.l_armed[0];
    end
  end

  // MISO's enable with CS high: sampled every cycle once CS has been high one
  reg cs_q;
  always @(posedge clk) begin
    if (!loading && rst_n === 1'b1) begin
      if (cs_q === 1'b1 && cs === 1'b1 && uio_oe[P_MISO] === 1'b1) begin
        n_oe_cs = n_oe_cs + 1;
        if (n_oe_cs <= 3)
          $display("*** FAIL spi_tgt: MISO driven (oe = 1) while CS is high, cycle %0d", cyc);
      end
      cs_q <= cs;
    end
  end

  // edge -> MISO: from a change-edge to the pad carrying the CHANGED bit
  always @(posedge clk) begin
    if (lat_pend && uio_oe[P_MISO] === 1'b1 && uio_out[P_MISO] === want_bit) begin
      lat_pend = 1'b0;
      if ($rtoi(($realtime - te) / 20.0 + 0.999) > lat_max)
        lat_max = $rtoi(($realtime - te) / 20.0 + 0.999);
      lat_n = lat_n + 1;
    end
    if (tcss_pend && uio_oe[P_MISO] === 1'b1 && uio_out[P_MISO] === want_bit) begin
      tcss_pend = 1'b0;
      tcss_seen = $rtoi(($realtime - t_csfall) / 20.0 + 0.999);
    end
  end

  // the chip's received bytes (MOSI variant)
  always @(posedge clk) if (rst_n === 1'b1 && dut.u_eng.rx_push === 1'b1 && mosi_on) begin
    if (n_rx < n_mosi && dut.u_eng.rx_data !== mosi_sent[n_rx]) begin
      n_rx_bad = n_rx_bad + 1;
      if (n_rx_bad <= 4)
        $display("*** FAIL spi_tgt: received byte %0d = %02h, master sent %02h",
                 n_rx, dut.u_eng.rx_data, mosi_sent[n_rx]);
    end
    n_rx = n_rx + 1;
  end

  // ---- a change-edge happened: score the margin, arm the latency probe ----
  task change_edge(input integer gbit);   // gbit: index of the bit now driven
    begin
      te = $realtime;
      if (armed_pend) begin
        if ($rtoi((te - t_armed) / 20.0) < margin_min)
          margin_min = $rtoi((te - t_armed) / 20.0);
        n_margin = n_margin + 1;
        armed_pend = 1'b0;
      end else begin
        n_missed = n_missed + 1;
      end
      want_bit = expb(gbit / 8) >> (7 - (gbit % 8));
      lat_pend = (gbit % 8 == 0) ? 1'b1
                 : (((expb(gbit / 8) >> (7 - (gbit % 8))) & 1)
                    != ((expb((gbit - 1) / 8) >> (7 - ((gbit - 1) % 8))) & 1));
    end
  endtask

  // ---- the master samples MISO -------------------------------------------
  task sample(input integer gbit);
    begin
      if (!skip_txn) begin
        // ⛔⛔ A RELEASED MISO READS AS THE PULL-UP's 1, AND THAT CAN MATCH
        // THE DATA BY LUCK: found when tCSS = 2 PASSED because the first fed
        // byte (A5) has bit 7 = 1. So a sample of an UNDRIVEN MISO is red on
        // its own, whatever the bit happens to read.
        if (uio_oe[P_MISO] !== 1'b1) begin
          n_undriven = n_undriven + 1;
          if (n_undriven <= 3)
            $display("*** FAIL spi_tgt: the master sampled MISO while it was RELEASED (bit %0d) -- it read the pull-up, not the target", gbit);
        end
        rd_byte = {rd_byte[6:0], miso_bus};
        n_bits = n_bits + 1;
        if (gbit % 8 == 7) begin
          want_byte = expb(gbit / 8);
          if (rd_byte !== want_byte) begin
            n_bad = n_bad + 1;
            if (n_bad <= 6)
              $display("*** FAIL spi_tgt: byte %0d read %02h, host fed %02h",
                       gbit / 8, rd_byte, want_byte);
          end
          n_bytes_rd = n_bytes_rd + 1;
        end
      end
    end
  endtask

  // ---- program load (and the documented RECOVERY: a reload) ----------------
  task load_image;
    begin
      loading = 1'b1;
      @(negedge clk);
      ui_in[PIN_PROG] = 1'b1;
      repeat (3) @(negedge clk); ui_in[PIN_PTR] = 1'b1; repeat (3) @(negedge clk);
      ui_in[PIN_PTR] = 1'b0; repeat (3) @(negedge clk);
      for (i = 0; i < img_bytes; i = i + 1) begin
        loadbus = img[i];
        @(negedge clk); @(negedge clk);
        ui_in[PIN_WR] = 1'b1;
        @(negedge clk); @(negedge clk); @(negedge clk);
        ui_in[PIN_WR] = 1'b0;
        @(negedge clk);
      end
      ui_in[PIN_PROG] = 1'b0;
      ui_in = 8'h00;
      loadbus = 8'hFF;
      loading = 1'b0;
    end
  endtask

  // ---- THE MASTER ------------------------------------------------------------
  real tnow, hp;
  integer t_i, k, gb, nbits_tx;
  reg [31:0] rnd;
  reg [7:0] mbyte;
  initial begin
    if (!$value$plusargs("IMG=%s", imgfile)) begin
      $display("tb_spitgt: FATAL -- +IMG=<file> is required."); $finish;
    end
    if (!$value$plusargs("NBYTES=%d", img_bytes)) begin
      $display("tb_spitgt: FATAL -- +NBYTES=<n> is required."); $finish;
    end
    if (!$value$plusargs("MODE=%d", mode)) mode = 0;
    if (!$value$plusargs("HALF=%d", half)) half = 25;
    if (!$value$plusargs("NTX=%d", ntx)) ntx = 8;
    if (!$value$plusargs("NB=%d", nb)) nb = 2;
    if (!$value$plusargs("TCSS=%d", tcss)) tcss = 30;
    if (!$value$plusargs("TCSH=%d", tcsh)) tcsh = 30;
    if (!$value$plusargs("GAP=%d", gap)) gap = 60;
    if (!$value$plusargs("MOSI=%d", mosi_on)) mosi_on = 0;
    if (!$value$plusargs("NOFEED=%d", nofeed)) nofeed = 0;
    if (!$value$plusargs("SHORT=%d", shortk)) shortk = -1;
    if (!$value$plusargs("RECOVER=%d", recover)) recover = 0;
    if (!$value$plusargs("CSEARLY=%d", csearly)) csearly = 0;
    cpol = mode[1]; cpha = mode[0];
    hp = 20.0 * half;
    off = 0; n_undriven = 0; n_bits = 0; n_bytes_rd = 0; n_bad = 0; n_oe_cs = 0;
    lat_max = 0; lat_n = 0; n_missed = 0; margin_min = 1 << 20; n_margin = 0;
    tcss_seen = -1; fails = 0; rd_idx = 0; n_rx = 0; n_rx_bad = 0; n_mosi = 0;
    lat_pend = 0; armed_pend = 0; tcss_pend = 0; skip_txn = 0; cs_q = 1'b1;
    rnd = 32'h5EED;
    sck = cpol; cs = 1'b1; mosi = 1'b1;
    $readmemh(imgfile, img);
    `PE_REQUIRE_IMG_LOADED(imgfile)
    $display("# spitgt img=%0s mode=%0d half=%0d ntx=%0d nb=%0d tcss=%0d tcsh=%0d gap=%0d mosi=%0d nofeed=%0d short=%0d recover=%0d csearly=%0d",
             imgfile, mode, half, ntx, nb, tcss, tcsh, gap, mosi_on, nofeed,
             shortk, recover, csearly);
    // ⭐ the host's feed: 16 distinct bytes on queue 0, repeated
    hf_init;
    hf_n(0, 16);
    hf_put(0, 0, 8'hA5); hf_put(0, 1, 8'h3C); hf_put(0, 2, 8'h96); hf_put(0, 3, 8'h0F);
    hf_put(0, 4, 8'h5A); hf_put(0, 5, 8'hC3); hf_put(0, 6, 8'h69); hf_put(0, 7, 8'hF0);
    hf_put(0, 8, 8'h81); hf_put(0, 9, 8'h7E); hf_put(0, 10, 8'h24); hf_put(0, 11, 8'hDB);
    hf_put(0, 12, 8'h18); hf_put(0, 13, 8'hE7); hf_put(0, 14, 8'h42); hf_put(0, 15, 8'hBD);

    repeat (4) @(negedge clk);
    rst_n = 1;
    load_image;
    if (!nofeed) hf_en = 1'b1;
    repeat (200) @(negedge clk);                 // the feeder prefills 2 bytes

    gb = 0;                                       // global bit index read
    for (t_i = 0; t_i < ntx; t_i = t_i + 1) begin
      nbits_tx = 8 * nb - ((t_i == shortk) ? 1 : 0);
      skip_txn = (t_i == shortk);                // its truncated byte is not scored
      tnow = $realtime + 3.0;
      // CS falls; CPHA 0: bit 7 is driven by the target at CS fall
      wait_until(tnow); cs = 1'b0; t_csfall = $realtime;
      if (!cpha && !skip_txn) begin
        want_bit = expb(gb / 8) >> 7;
        tcss_pend = 1'b1;
      end
      if (mosi_on) begin
        rnd = lcg(rnd); mbyte = rnd[23:16];
        if (!cpha) mosi = mbyte[7];
      end
      tnow = tnow + 20.0 * tcss;
      for (k = 0; k < nbits_tx; k = k + 1) begin
        // M6: CS released EARLY -- CSEARLY cycles after the last change-edge,
        // i.e. before the master's final sample (it must be inside the loop:
        // after the loop every edge has already happened)
        if (csearly > 0 && k == nbits_tx - 1 && !cpha) begin
          wait_until(te + 20.0 * csearly);
          cs = 1'b1;
        end
        // LEADING edge
        wait_until(tnow); sck = ~cpol;
        if (cpha) begin                           // CPHA 1: target changes here
          change_edge(gb + k);
          if (mosi_on) mosi = mbyte[7 - (k % 8)];
        end else sample(gb + k);                  // CPHA 0: master samples here
        tnow = tnow + hp;
        // TRAILING edge
        wait_until(tnow); sck = cpol;
        if (cpha) sample(gb + k);
        else if (k + 1 < nbits_tx) begin          // CPHA 0: next bit changes here
          change_edge(gb + k + 1);
          if (mosi_on) begin
            if ((k + 1) % 8 == 0) begin
              mosi_sent[n_mosi] = mbyte; n_mosi = n_mosi + 1;
              rnd = lcg(rnd); mbyte = rnd[23:16];
            end
            mosi = mbyte[7 - ((k + 1) % 8)];
          end
        end
        tnow = tnow + hp;
      end
      if (mosi_on && !skip_txn) begin mosi_sent[n_mosi] = mbyte; n_mosi = n_mosi + 1; end
      // CS rises tCSH after the last edge (already high under CSEARLY)
      if (csearly == 0) wait_until(tnow - hp + 20.0 * tcsh);
      cs = 1'b1;
      armed_pend = 1'b0; lat_pend = 1'b0;
      if (!skip_txn) gb = gb + 8 * nb;
      if (skip_txn && recover) begin
        // ⭐ THE DOCUMENTED RECOVERY: the host stops feeding, reloads the
        // program (PROG rise clears the queues and resets the lane, fixes #8/#9),
        // and feeds again from where its OWN bookkeeping says the stream is.
        hf_mask[0] = 1'b0;                        // the feeder's own switch
        repeat (30) @(negedge clk);               // let an in-flight push finish
        hf_en = 1'b0;
        load_image;
        // the next byte out is the next one pushed: pattern[hf_idx[0]]
        off = (hf_idx[0] - (gb / 8) % 16 + 32) % 16;
        hf_mask[0] = 1'b1;
        hf_en = 1'b1;
        repeat (200) @(negedge clk);
        $display("  spi_tgt: RECOVERY -- program reloaded after transaction %0d; the stream resumes at byte %0d", t_i, gb / 8);
      end
      skip_txn = 1'b0;
      repeat (gap) @(negedge clk);
    end
    repeat (200) @(negedge clk);

    hf_check(n_bits);
    fails = fails + hf_bad * (nofeed ? 0 : 1);
    if (n_bytes_rd != (ntx - ((shortk >= 0 && shortk < ntx) ? 1 : 0)) * nb) begin
      fails = fails + 1;
      $display("*** FAIL spi_tgt: %0d byte(s) read, expected %0d", n_bytes_rd,
               (ntx - ((shortk >= 0 && shortk < ntx) ? 1 : 0)) * nb);
    end
    if (n_bad) fails = fails + 1;
    if (n_oe_cs) fails = fails + 1;
    if (lat_max > D_TOL) begin
      fails = fails + 1;
      $display("*** FAIL spi_tgt: edge -> MISO latency %0d cycles > D_tol %0d", lat_max, D_TOL);
    end
    if (n_undriven) begin
      fails = fails + 1;
      $display("*** FAIL spi_tgt: %0d sample(s) of a RELEASED MISO", n_undriven);
    end
    // ⚠ `missed` IS REPORTED, NOT JUDGED: it is this bench's view of the
    // ARM's level (a rise of l_armed since the last edge), and at a tight
    // SCK the ARM can re-arm without the level ever dropping, which this
    // counts as a miss. A REAL miss leaves a bit unshifted, so it shows in
    // wire != feed -- which IS judged, exactly.
    if (mosi_on && (n_rx != n_mosi || n_rx_bad)) begin
      fails = fails + 1;
      $display("*** FAIL spi_tgt: %0d byte(s) received (%0d wrong), master sent %0d", n_rx, n_rx_bad, n_mosi);
    end
    $display("  spi_tgt: bytes read %0d (wrong %0d); edge->MISO worst %0d cycles over %0d changes (D_tol %0d); re-arm margin min %0d cycles over %0d edges, missed %0d; tCSS seen %0d cycles; oe-with-CS-high %0d; MOSI rx %0d/%0d",
             n_bytes_rd, n_bad, lat_max, lat_n, D_TOL, (n_margin ? margin_min : -1),
             n_margin, n_missed, tcss_seen, n_oe_cs, n_rx, n_mosi);
    if (fails == 0)
      $display("SPI-TGT: ok -- mode %0d, SCK half %0d cycles, %0d transaction(s) of %0d byte(s): every byte equals the host's feed, count exact",
               mode, half, ntx, nb);
    else
      $display("*** FAIL spi_tgt: %0d check(s) failed", fails);
    $display("END tb_spitgt");
    $finish;
  end
endmodule
