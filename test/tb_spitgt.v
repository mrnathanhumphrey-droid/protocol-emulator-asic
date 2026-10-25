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
 *   HALFPS(0: SCK half period in ps, overriding HALF -- the B3b detune)
 *   BOUND(-1: the A2 pad bound r + 4, passed by the runner from program_a2;
 *   edge -> MISO above it is a FAIL) FIVE(0: the B3b contention bench, below)
 *   NOI2C(0: the image has no I2C lane -- queue 2 unfed, its check skipped)
 *   RXT(434: the UART-rx peer's cycles per bit -- nominal 115200. ⛔ NOT 414:
 *   back-to-back at -4.6 % the receiver misses every start after the first,
 *   outside its verified +-3 % band; B3b run 1 measured it, 10-20)
 *
 * ⭐ B3b, +FIVE=1 (Wilson 10-20): the image carries the other four shipped
 * lanes (SPI master q1, I2C q2, UART-tx q3, UART-rx), and every one is kept
 * busy and checked on its own wire against its own reference:
 *   uio[1:2]  I2C SCL/SDA, a wired-AND bus with pull-ups (no peer: NACKs)
 *   uio[3]    UART-rx stimulus, back-to-back 8N1 at RXT (414) cycles/bit
 *   uio[0]    the SPI master's MISO, held at 1
 *   queues 1..3 fed 16 distinct bytes each; the SPI master's MOSI bytes, the
 *   I2C bytes after START and the UART-tx bytes must equal their feeds, and
 *   the chip's UART-rx bytes (rx_lane 4) the stimulus's.
 * The worst SPI-target bit also logs which lanes were DISPATCHED between its
 * change-edge and the pad carrying it (st == ST_DRIVE, `cur`).
 */
`default_nettype none
`timescale 1ns / 1ps
`include "test/imgload.vh"
module tb_spitgt;
  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00;
  wire [7:0] uo_out, uio_out, uio_oe;
  localparam integer PIN_PROG = 7, PIN_PTR = 5, PIN_WR = 6;
`include "test/store_filler.vh"   // v2: PE_STORE_BYTES, never a typed 256
  localparam integer IMG_MAX = PE_STORE_BYTES;
  localparam integer P_SCK = 4, P_MOSI = 5, P_CS = 6, P_MISO = 7;
  localparam integer D_TOL = 17;

  // the pads the master drives; MISO is the chip's (pulled up when released)
  reg        sck = 1'b0, mosi = 1'b1, cs = 1'b1;
  reg  [7:0] loadbus = 8'hFF;
  reg        loading = 1'b0;
  wire       miso_bus = uio_oe[P_MISO] ? uio_out[P_MISO] : 1'b1;
  // B3b: the I2C pins are open-drain -- a driven 0 pulls the line low,
  // anything else leaves it to the pull-up
  localparam integer P_SCL = 1, P_SDA = 2, P_RX = 3;
  wire       scl_bus = !(uio_oe[P_SCL] === 1'b1 && uio_out[P_SCL] === 1'b0);
  wire       sda_bus = !(uio_oe[P_SDA] === 1'b1 && uio_out[P_SDA] === 1'b0);
  reg        rx_line = 1'b1;
  integer    five;
  wire [7:0] uio_in = loading ? loadbus
                    : five ? {miso_bus, cs, mosi, sck, rx_line, sda_bus, scl_bus, 1'b1}
                           : {miso_bus, cs, mosi, sck, 4'b1111};

  reg  [7:0] img [0:IMG_MAX-1];
  integer    img_bytes, i, cyc;
  reg [8*256-1:0] imgfile;
  integer    mode, half, ntx, nb, tcss, tcsh, gap, mosi_on, nofeed, shortk,
             recover, csearly, halfps, bound, noi2c, phwalk;
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

  // B3b: which lanes were dispatched inside the pending bit's window
  reg [4:0] win_mask, worst_mask;
  integer   worst_gbit, gbit_pend;

  // edge -> MISO: from a change-edge to the pad carrying the CHANGED bit
  always @(posedge clk) begin
    // ⛔ the dispatch mask is accumulated HERE, in the same block that clears
    // `lat_pend` -- a separate block raced it (gate_bench_races, 10-20)
    if (lat_pend && dut.u_eng.st === 2'd1 && dut.u_eng.cur < 5)
      win_mask[dut.u_eng.cur] = 1'b1;
    if (lat_pend && uio_oe[P_MISO] === 1'b1 && uio_out[P_MISO] === want_bit) begin
      lat_pend = 1'b0;
      if ($rtoi(($realtime - te) / 20.0 + 0.999) > lat_max) begin
        lat_max = $rtoi(($realtime - te) / 20.0 + 0.999);
        worst_mask = win_mask;
        worst_gbit = gbit_pend;
      end
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

  reg [19:0] ph_clk = 20'd0;
  reg [44:0] ph_i2c = 45'd0;
  function integer popc(input [44:0] v);
    integer b;
    begin popc = 0; for (b = 0; b < 45; b = b + 1) popc = popc + v[b]; end
  endfunction

  // ---- B3b: the other four lanes, each against its own reference -----------
  // UART-tx on uo_out[0], LSB first, T 434: bytes must equal queue 3's feed
  localparam integer UT = 434;
  integer n_utx = 0, n_utx_bad = 0, ub;
  reg [7:0] utx;
  initial begin
    wait (five == 1 && hf_en === 1'b1);
    forever begin
      @(negedge uo_out[0]);
      #(20.0 * UT * 1.5);
      for (ub = 0; ub < 8; ub = ub + 1) begin
        utx[ub] = uo_out[0];
        #(20.0 * UT);
      end
      if (utx !== hf_pat[3][n_utx % 16]) begin
        n_utx_bad = n_utx_bad + 1;
        if (n_utx_bad <= 3)
          $display("*** FAIL b3b: UART-tx byte %0d = %02h, host fed %02h", n_utx, utx, hf_pat[3][n_utx % 16]);
      end
      n_utx = n_utx + 1;
    end
  end
  // SPI master on uo_out[1] SCLK / [2] MOSI / [3] CS, sampled on the SCLK
  // rise: the first two bytes of each CS frame are its out-bytes (queue 1)
  integer n_spm = 0, n_spm_bad = 0, spm_bits = 0;
  reg [7:0] spm;
  always @(negedge uo_out[3]) spm_bits = 0;
  always @(posedge uo_out[1]) if (five == 1 && hf_en === 1'b1 && uo_out[3] === 1'b0) begin
    if (spm_bits < 16) begin
      spm = {spm[6:0], uo_out[2]};
      spm_bits = spm_bits + 1;
      if (spm_bits % 8 == 0) begin
        if (spm !== hf_pat[1][n_spm % 16]) begin
          n_spm_bad = n_spm_bad + 1;
          if (n_spm_bad <= 3)
            $display("*** FAIL b3b: SPI-master byte %0d = %02h, host fed %02h", n_spm, spm, hf_pat[1][n_spm % 16]);
        end
        n_spm = n_spm + 1;
      end
    end
  end
  // I2C: the first 8 bits after a START (SDA falling with SCL high), on the
  // SCL rise, MSB first: queue 2's bytes
  integer n_i2c = 0, n_i2c_bad = 0, i2c_bits = 99;
  reg [7:0] i2b;
  always @(negedge sda_bus) if (scl_bus) i2c_bits = 0;
  always @(posedge scl_bus) if (five == 1 && hf_en === 1'b1 && i2c_bits < 8) begin
    i2b = {i2b[6:0], sda_bus};
    i2c_bits = i2c_bits + 1;
    if (i2c_bits == 8) begin
      if (i2b !== hf_pat[2][n_i2c % 16]) begin
        n_i2c_bad = n_i2c_bad + 1;
        if (n_i2c_bad <= 3)
          $display("*** FAIL b3b: I2C byte %0d = %02h, host fed %02h", n_i2c, i2b, hf_pat[2][n_i2c % 16]);
      end
      n_i2c = n_i2c + 1;
    end
  end
  // UART-rx: back-to-back 8N1 frames at RXT cycles/bit on uio[3]; the chip's
  // rx pushes from lane 4 must equal what was sent. TWO pushes per frame, as
  // tb_uartrx reads them: the data byte, then the stop push {stop, data[7:1]}
  integer rxt, n_urx_sent = 0, n_urx = 0, n_urx_bad = 0, rb;
  reg [7:0] urx_sent [0:4095];
  reg [7:0] urx_want;
  reg [31:0] rxr = 32'hC0FFEE;
  reg urx_go = 1'b0;
  initial begin
    wait (urx_go === 1'b1);
    // a real line idles HIGH before its first frame: wait for the UART-rx
    // lane's ARM, then one bit time of idle; back-to-back from there on
    wait (dut.u_eng.l_armed[4] === 1'b1);
    // ⛔ +3 ns: `l_armed` rises ON a posedge and every bit time below is whole
    // cycles, so without it every RX edge landed in the posedge's own
    // timestep -- a scheduling race (phase audit 10-20). 3 ns off the edge is
    // tb_uartrx's convention.
    #(20.0 * rxt + 3.0);
    forever begin
      rxr = rxr * 32'd1103515245 + 32'd12345;
      urx_sent[n_urx_sent % 4096] = rxr[23:16];
      rx_line = 1'b0; #(20.0 * rxt);
      for (rb = 0; rb < 8; rb = rb + 1) begin rx_line = rxr[16 + rb]; #(20.0 * rxt); end
      rx_line = 1'b1; #(20.0 * rxt);
      n_urx_sent = n_urx_sent + 1;
    end
  end
  always @(posedge clk) if (five == 1 && rst_n === 1'b1 && dut.u_eng.rx_push === 1'b1
                            && dut.u_eng.rx_lane == 4) begin
    urx_want = (n_urx % 2 == 0) ? urx_sent[(n_urx / 2) % 4096]
                                : {1'b1, urx_sent[(n_urx / 2) % 4096][7:1]};
    if (dut.u_eng.rx_data !== urx_want) begin
      n_urx_bad = n_urx_bad + 1;
      if (n_urx_bad <= 3)
        $display("*** FAIL b3b: UART-rx frame %0d %s push = %02h, the peer sent %02h", n_urx / 2,
                 (n_urx % 2) ? "stop" : "data", dut.u_eng.rx_data, urx_want);
    end
    n_urx = n_urx + 1;
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
      win_mask = 5'b00000;
      gbit_pend = gbit;
      // phase coverage: the edge's phase within the 20 ns clock (1 ns bins)
      // and within the I2C lane's 45-cycle period
      ph_clk[$rtoi(te - 20.0 * $floor(te / 20.0))] = 1'b1;
      ph_i2c[$rtoi(te / 20.0) % 45] = 1'b1;
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
    if (!$value$plusargs("HALFPS=%d", halfps)) halfps = 0;
    // +PHWALK: the per-transaction golden-ratio offset WITHOUT a detune (the
    // non-FIVE arms; phase-coverage rule, Wilson 10-20)
    if (!$value$plusargs("PHWALK=%d", phwalk)) phwalk = 0;
    if (!$value$plusargs("BOUND=%d", bound)) bound = -1;
    if (!$value$plusargs("FIVE=%d", five)) five = 0;
    if (!$value$plusargs("NOI2C=%d", noi2c)) noi2c = 0;
    if (!$value$plusargs("RXT=%d", rxt)) rxt = 434;
    cpol = mode[1]; cpha = mode[0];
    hp = (halfps > 0) ? halfps / 1000.0 : 20.0 * half;
    worst_mask = 5'b00000; worst_gbit = -1;
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
    if (five) begin
      // B3b: queues 1..3, 16 distinct bytes each (distinct within a queue;
      // each lane is checked against its OWN queue, so overlap is harmless)
      for (k = 0; k < 16; k = k + 1) begin
        hf_put(1, k, 8'h10 + k * 8'h11 + 8'h01);
        hf_put(2, k, 8'h20 + k * 8'h0D + 8'h03);
        hf_put(3, k, 8'h30 + k * 8'h07 + 8'h05);
      end
      hf_n(1, 16); hf_n(3, 16);
      if (!noi2c) hf_n(2, 16);                   // NOI2C: the image has no lane 2
    end

    repeat (4) @(negedge clk);
    rst_n = 1;
    load_image;
    if (!nofeed) hf_en = 1'b1;
    if (five) urx_go = 1'b1;
    repeat (200) @(negedge clk);                 // the feeder prefills 2 bytes

    gb = 0;                                       // global bit index read
    for (t_i = 0; t_i < ntx; t_i = t_i + 1) begin
      nbits_tx = 8 * nb - ((t_i == shortk) ? 1 : 0);
      skip_txn = (t_i == shortk);                // its truncated byte is not scored
      // ⭐ B3b: each transaction starts at its OWN sub-cycle phase (a golden-
      // ratio walk over the 20 ns clock). Without it every transaction began
      // 3 ns after a clock edge -- the gap is counted in edges -- and the
      // detune walked only ~10 ns inside one transaction (9/20 phases seen).
      tnow = $realtime + 3.0
             + ((halfps > 0 || phwalk) ? 20.0 * (t_i * 0.618034 - $floor(t_i * 0.618034)) : 0.0);
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
    if (bound >= 0 && lat_max > bound) begin
      fails = fails + 1;
      $display("*** FAIL spi_tgt: edge -> MISO worst %0d cycles > the A2 pad bound %0d (r + L_SYNC + OUT_REG) -- A2 UNSOUND on this image", lat_max, bound);
    end
    if (five) begin
      // every other lane must have moved, and moved its own bytes
      if (n_utx < 2 || n_utx_bad) begin
        fails = fails + 1;
        $display("*** FAIL b3b: UART-tx %0d byte(s), %0d wrong", n_utx, n_utx_bad);
      end
      if (n_spm < 2 || n_spm_bad) begin
        fails = fails + 1;
        $display("*** FAIL b3b: SPI-master %0d byte(s), %0d wrong", n_spm, n_spm_bad);
      end
      if (!noi2c && (n_i2c < 2 || n_i2c_bad)) begin
        fails = fails + 1;
        $display("*** FAIL b3b: I2C %0d byte(s), %0d wrong", n_i2c, n_i2c_bad);
      end
      // every frame sent before the last one must have been received (the
      // last may still be in flight when the master finishes)
      if (n_urx < 4 || n_urx_bad || n_urx / 2 < n_urx_sent - 1) begin
        fails = fails + 1;
        $display("*** FAIL b3b: UART-rx %0d frame(s) received, %0d push(es) wrong (%0d sent)", n_urx / 2, n_urx_bad, n_urx_sent);
      end
      $display("  b3b: other lanes -- UART-tx %0d/%0d bad, SPI-master %0d/%0d bad, I2C %0d/%0d bad, UART-rx %0d frames/%0d bad pushes (%0d sent)",
               n_utx, n_utx_bad, n_spm, n_spm_bad, n_i2c, n_i2c_bad, n_urx / 2, n_urx_bad, n_urx_sent);
      $display("  b3b: worst bit %0d at %0d cycles (A2 pad bound %0d); lanes dispatched in its window %05b (lane 4..0); edge phases seen %0d/20 of the clock, %0d/45 of the I2C period",
               worst_gbit, lat_max, bound, worst_mask, popc({25'd0, ph_clk}), popc(ph_i2c));
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
    $display("  spi_tgt: bytes read %0d (wrong %0d); edge->MISO worst %0d cycles over %0d changes (D_tol %0d); re-arm margin min %0d cycles over %0d edges, level-heuristic misses %0d (diagnostic only: a real miss shows as a wrong byte); tCSS seen %0d cycles; oe-with-CS-high %0d; MOSI rx %0d/%0d",
             n_bytes_rd, n_bad, lat_max, lat_n, D_TOL, (n_margin ? margin_min : -1),
             n_margin, n_missed, tcss_seen, n_oe_cs, n_rx, n_mosi);
    // measured phase coverage of the master's change-edges, EVERY run
    $display("  SPI-PHASE edges=%0d/20 bins=%020b phwalk=%0d halfps=%0d",
             popc({25'd0, ph_clk}), ph_clk, phwalk, halfps);
    if (fails == 0)
      $display("SPI-TGT: ok -- mode %0d, SCK half %0d cycles, %0d transaction(s) of %0d byte(s): every byte equals the host's feed, count exact",
               mode, half, ntx, nb);
    else
      $display("*** FAIL spi_tgt: %0d check(s) failed", fails);
    $display("END tb_spitgt");
    $finish;
  end
endmodule
