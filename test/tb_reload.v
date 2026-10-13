/* tb_reload.v -- A RELOAD IS A CLEAN SLATE (candidates #9 and #10, Wilson Q2).
 *
 * ⛔ THE DEFECTS.
 *   #9   The halt block re-initialised the lanes' PCs, arms and pins but NOT
 *        the bit pointers (`tx_bitp`, `rx_bitp`) or the TX register: they
 *        reset only at power-on. A program loaded while a byte was in flight
 *        inherited the old position -- its first TX frame carried leftover
 *        bits and its first RX push a partial byte.
 *   #10  `uo_out` has no enable, and `pin_out` was set to all ones only at
 *        power-on. After a reload a pad kept the halted program's last level
 *        until the new program first drove it: a UART TX cut on a 0 bit showed
 *        a start bit ~290 cycles early. Principle: THE HALT STATE EQUALS THE
 *        RESET STATE.
 *   Q2   Rule 1: the synchronised PROG rise empties the TX queues and the RX
 *        pending byte. Host contract: after a reload TX starts with the first
 *        byte pushed after PROG falls, and a received byte not yet read when
 *        PROG rises is gone (docs/HOST_INTERFACE.md).
 *
 * ⭐ THE VERDICT IS WHAT A PEER SEES ON THE WIRE (Wilson). Each reload is a
 * real one -- PROG high, the whole image rewritten, PROG low -- TRIGGERED BY
 * THE PEER'S OWN TIMING, not by reading the chip (mode 3's trigger is the one
 * exception, and says why). The bit pointers are printed at resume
 * (`# diag:`) as the DIAGNOSTIC that says why a red run is red; they decide
 * nothing here.
 *
 *   +MODE=0  TX, same image (test/uart_tx_image.hex): a UART peer on its own
 *            clock (nominal grid, every bit held over the middle 80 % of its
 *            window) counts every start edge, the cut frame included. Before
 *            the reload, frame i is the host's pattern byte i; after it, the
 *            first whole frame is the first byte pushed after PROG fell and
 *            the rest follow in order. Cut at bit RLB of frame RLF.
 *   +MODE=1  RX, same image (test/uart_rx_image.hex, 2 pushes per frame):
 *            the reload is triggered mid-frame and PROG is held until the peer
 *            has finished that frame and idled (a receiver resumed mid-frame
 *            may lock onto a data edge -- that is UART, not this defect). The
 *            cut frame is never pushed; the pushes after the reload are the
 *            peer's next whole frames, in order, count exact.
 *   +MODE=2  RX image -> TX image: a reload into a DIFFERENT program (lane
 *            reconfiguration). After it the TX frames are the feed from its
 *            first byte and the old receive lane pushes nothing. ⚠ A stale
 *            receive counter cannot affect a transmit lane, so this arm covers
 *            reconfiguration, NOT #9.
 *   +MODE=3  RX, an UNREAD received byte across the reload. The serialiser is
 *            kept busy with status frames (TX-FULL set on purpose), and PROG
 *            is raised the moment frame RLF's data byte is pushed, so the byte
 *            is still pending when PROG rises -- ⚠ that trigger reads the
 *            push pulse, because nothing on the wire precedes it; the arm's
 *            PRECONDITION (a byte pending at the PROG rise) is asserted, so an
 *            arm that failed to create the state is red, not vacuously green.
 *            VERDICT, off the 3-pin serial host stream: the first payload
 *            frame after PROG falls is the peer's NEXT whole frame, never the
 *            pending byte.
 *   +MODE=4  SPI master, mode 0 (+IMG, the `mode0` build), FRAM peer
 *            (test/fram_spi.v). Cut at the SCK fall after bit RLB of byte RLF
 *            (bytes counted over every CS frame). VERDICTS: at the halt CS
 *            rises AT LEAST ONE CLOCK before any SCK edge the halt causes
 *            (option 1': a same-cycle rise is red -- pad skew would decide
 *            it); the cut byte is NOT written; after the
 *            reload the whole transaction runs from the first byte pushed and
 *            the READ returns the bytes written.
 *
 * Plusargs: IMG (required: the program reloaded) MODE(0) RLF(3) RLB(5)
 *           NPOST(12)
 * Verdict: `RELOAD: ok -- ...` or `*** FAIL reload: ...`.
 */
`default_nettype none
`timescale 1ns / 1ps
`include "test/imgload.vh"
module tb_reload;
  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00, uio_drv = 8'hFF;
  wire [7:0] uo_out, uio_out, uio_oe;
  reg        rxline = 1'b1, loading = 1'b0;
  wire       spi_so, spi_so_oe;
  localparam integer IMG_MAX = 256, PIN_PROG = 7, PIN_PTR = 5, PIN_WR = 6;
  localparam integer P_RX = 3, TX_BIT = 0, BITP = 434;
  localparam integer SCK_UO = 1, MOSI_UO = 2, CS_UO = 3, P_MISO = 0;
  localparam integer SER_D = 4, SER_S = 5, SER_V = 6;
  localparam integer NBYTES = 256;
  integer    mode;
  // ---- the shared reload handshake ----------------------------------------
  reg req_reload = 1'b0, req_quiet = 1'b0, in_reload = 1'b0, reloaded = 1'b0;
  // ---- the I2C bus (modes 5, 7): open-drain, pull-ups on both sides ------
  // ⭐ THE BUS SWITCH (Wilson, HOST_INTERFACE): a peer on the `uio` protocol
  // pins must be ISOLATED during ANY load, because `uio` is the load data
  // port. `sw` models a bidirectional FET switch: closed, the peer and the
  // chip share the lines; open, the peer sees its own pull-ups (idle high).
  // Mode 7 keeps it CLOSED through the load -- the harm demonstration.
  localparam integer P_SCL = 1, P_SDA = 2;
  wire       i2c_sda_oe, i2c_scl_oe;
  reg        sw = 1'b0;
  // ⚠ A REG SET FROM `mode` AT START, not a wire: a continuous assign would
  // not yet have updated when the main block tests it in the same time step
  reg        i2c_mode = 1'b0;
  wire       chip_scl_low = uio_oe[P_SCL] & ~uio_out[P_SCL];
  wire       chip_sda_low = uio_oe[P_SDA] & ~uio_out[P_SDA];
  wire       host_scl = loading ? uio_drv[P_SCL] : 1'b1;   // load data
  wire       host_sda = loading ? uio_drv[P_SDA] : 1'b1;
  wire       bus_scl = host_scl & ~chip_scl_low & ~(sw & i2c_scl_oe);
  wire       bus_sda = host_sda & ~chip_sda_low & ~(sw & i2c_sda_oe);
  wire       peer_scl = sw ? bus_scl : 1'b1;
  wire       peer_sda = sw ? bus_sda : 1'b1;
  wire [7:0] drv = (loading && !i2c_mode) ? uio_drv
                 : {uio_drv[7:4], (loading ? uio_drv[3] : rxline),
                    i2c_mode ? bus_sda : uio_drv[2],
                    i2c_mode ? bus_scl : uio_drv[1],
                    (mode == 4 && spi_so_oe && !loading) ? spi_so : uio_drv[0]};
  wire [7:0] uio_in = (uio_oe & uio_out) | (~uio_oe & drv);
  reg  [7:0] img [0:IMG_MAX-1];
  integer    i, rlf, rlb, npost, fails;
  reg [8*256-1:0] imgfile;
  real       bt;
  always #10 clk = ~clk;

  tt_um_protocol_emulator #(.SPL(2)) dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );
`include "test/progress.vh"
`include "test/host_feed.vh"

  fram_spi u_spi (
      .clk(clk), .cs_n(uo_out[CS_UO]), .sck(uo_out[SCK_UO]),
      .si(uo_out[MOSI_UO]), .so(spi_so), .so_oe(spi_so_oe)
  );
  fram_i2c #(.DEV_SEL(3'b000), .STRETCH(0)) u_i2c (
      .clk(clk), .scl_in(peer_scl), .sda_in(peer_sda),
      .sda_oe(i2c_sda_oe), .scl_oe(i2c_scl_oe)
  );

  // ---- I2C PEER WATCH (modes 5, 7): 9 clocks per byte (8 + the ACK),
  // counted from each START the peer sees; cut at the SCL fall after bit RLB
  // of byte RLF (0 = the device address)
  integer i2_rise = 0, i2_byte = -1, i2_bit = 0, i2_starts0, i2_acks = 0;
  always @(negedge peer_sda) if (i2c_mode && peer_scl === 1'b1) i2_rise = 0;
  always @(posedge peer_scl) if (i2c_mode && !in_reload) begin
    i2_rise = i2_rise + 1;
    i2_byte = (i2_rise - 1) / 9;
    i2_bit  = (i2_rise - 1) % 9 + 1;
    // stop the feeder a byte early, so no push is in flight at the cut
    if (!reloaded && i2_byte == rlf && i2_bit == 1) req_quiet = 1'b1;
  end
  always @(negedge peer_scl) if (i2c_mode && !reloaded && !in_reload)
    if (i2_byte == rlf && i2_bit == rlb) req_reload = 1'b1;
  always @(posedge i2c_sda_oe) if (in_reload) i2_acks = i2_acks + 1;

  // ---- THE QUIET WINDOW (every mode): for 64 cycles after PROG falls no pad
  // may move -- headers alone take ~290 cycles to re-read, so nothing the new
  // program does can reach a pin yet. Anything here is state that survived
  // the halt (a pending hold, a stale level). `M_HALT_KEEP_HOLD` lands here.
  integer qw = -1, qw_bad = 0;
  always @(posedge clk) begin
    if (reloaded && qw < 0 && !ui_in[PIN_PROG]) qw = 0;
    else if (qw >= 0 && qw < 64) begin
      qw = qw + 1;
      if (uio_oe !== 8'h00 || uo_out[3:0] !== 4'b1111) begin
        qw_bad = qw_bad + 1;
        if (qw_bad == 1)
          $display("*** FAIL reload: +%0d cycles after PROG fell a pad moved (uio_oe=%b uo_out[3:0]=%b) -- no dispatch can have happened yet",
                   qw, uio_oe, uo_out[3:0]);
      end
    end
  end

  // ---- the loader: PROG high, the whole image; PROG is left HIGH ----------
  // (the caller drops it, so the RX arms can hold it until the peer idles)
  task write_image;
    input [8*256-1:0] f;
    begin
      $readmemh(f, img);
      `PE_REQUIRE_IMG_LOADED(f)
      loading = 1'b1;
      ui_in[PIN_PROG] = 1'b1;
      repeat (3) @(negedge clk); ui_in[PIN_PTR] = 1'b1; repeat (3) @(negedge clk);
      ui_in[PIN_PTR] = 1'b0; repeat (3) @(negedge clk);
      for (i = 0; i < NBYTES; i = i + 1) begin
        uio_drv = img[i];
        @(negedge clk); @(negedge clk);
        ui_in[PIN_WR] = 1'b1;
        @(negedge clk); @(negedge clk); @(negedge clk);
        ui_in[PIN_WR] = 1'b0;
        @(negedge clk);
      end
      uio_drv = 8'hFF;
    end
  endtask
  task run_now;
    begin
      ui_in[PIN_PROG] = 1'b0;
      loading = 1'b0;
    end
  endtask


  // ---- TX PEER (modes 0, 2): a UART receiver on uo_out[0], its own clock ---
  real       t0;
  integer    tx_starts = 0, tx_post = 0, tx_bad = 0, k;
  integer    tx_base = 0, pat_off = 0;
  reg        tx_on = 1'b0, cut, ok_win, lvl;
  reg  [7:0] got, want;
  initial begin
    wait (tx_on);
    forever begin
      @(negedge uo_out[TX_BIT]);
      if (in_reload || !tx_on) begin
        wait (!in_reload && tx_on);
      end else begin
        t0 = $realtime; got = 8'h00; ok_win = 1'b1; cut = 1'b0;
        for (k = 0; k < 10 && !cut; k = k + 1) begin
          if (k == rlb && tx_starts == rlf && mode == 0 && !reloaded)
            req_reload = 1'b1;
          #(t0 + bt * (k + 0.1) - $realtime);
          lvl = uo_out[TX_BIT];
          #(t0 + bt * (k + 0.5) - $realtime);
          if (uo_out[TX_BIT] !== lvl) ok_win = 1'b0;
          lvl = uo_out[TX_BIT];
          #(t0 + bt * (k + 0.9) - $realtime);
          if (uo_out[TX_BIT] !== lvl) ok_win = 1'b0;
          if (in_reload) cut = 1'b1;
          if (k == 0 && lvl !== 1'b0) ok_win = 1'b0;
          if (k >= 1 && k <= 8) got[k - 1] = lvl;
          if (k == 9 && lvl !== 1'b1) ok_win = 1'b0;
        end
        if (cut) begin
          $display("  tx peer: frame %0d cut by the reload (not judged)", tx_starts);
        end else begin
          // before the reload frame i is pattern byte i; after it the first
          // whole frame is the first byte pushed after PROG fell (`pat_off`)
          want = reloaded ? hf_pat[0][(pat_off + tx_starts - tx_base) % hf_len[0]]
                          : hf_pat[0][tx_starts % hf_len[0]];
          if (got !== want || !ok_win) begin
            tx_bad = tx_bad + 1;
            if (tx_bad <= 6)
              $display("*** FAIL reload: TX frame %0d (%0s the reload) decoded %02h, want %02h%0s",
                       tx_starts, reloaded ? "after" : "before", got, want,
                       ok_win ? "" : " -- and a bit broke its timing window");
          end
          if (reloaded) tx_post = tx_post + 1;
        end
        tx_starts = tx_starts + 1;
        if (in_reload) wait (!in_reload);
      end
    end
  end

  // ---- RX PEER (modes 1, 2, 3): distinct bytes, 8N1, 2 bit times idle ------
  localparam integer FMAX = 64;
  reg  [7:0] sent [0:FMAX-1];
  integer    rx_sent = 0, b, rx_cut = -1;
  reg        rx_on = 1'b0, rx_idle = 1'b1;
  initial begin
    for (i = 0; i < FMAX; i = i + 1) sent[i] = 8'h11 + 8'd37 * i[7:0];
    wait (rx_on);
    forever begin
      if (!rx_on) wait (rx_on);
      rx_idle = 1'b0;
      // counted at its START: the data byte is pushed before the stop bit
      // ends (the same convention as tb_uartrx)
      rx_sent = rx_sent + 1;
      rxline = 1'b0; repeat (BITP) @(posedge clk);
      for (b = 0; b < 8; b = b + 1) begin
        if (b + 1 == rlb && rx_sent - 1 == rlf && !reloaded
            && (mode == 1 || mode == 2)) begin
          req_reload = 1'b1; rx_cut = rx_sent - 1;
        end
        rxline = sent[rx_sent - 1][b]; repeat (BITP) @(posedge clk);
      end
      rxline = 1'b1; repeat (BITP) @(posedge clk);          // stop
      rx_idle = 1'b1;
      repeat (2 * BITP) @(posedge clk);                     // idle
      // after a reload the chip re-reads its headers before it can arm
      // (~290 cycles), so the peer idles 2 bit times, as a host would; a
      // frame started the cycle PROG fell would find the lane not yet armed
      if (in_reload) begin
        wait (!in_reload);
        repeat (2 * BITP) @(posedge clk);
      end
      if (rx_sent >= FMAX) rx_on = 1'b0;
    end
  end

  // ---- RX pushes vs the peer's frames (modes 1, 2) -------------------------
  integer rx_push = 0, rx_bad = 0, rx_frame, rx_post = 0;
  reg [7:0] post_push [0:15];
  always @(posedge clk) if (rst_n === 1'b1 && dut.u_eng.rx_push === 1'b1) begin
    if (mode == 2 && reloaded) begin
      rx_bad = rx_bad + 1;
      $display("*** FAIL reload: a receive push (%02h from lane %0d) AFTER reloading into the TX program",
               dut.u_eng.rx_data, dut.u_eng.rx_lane);
    end else if (mode == 1) begin
      // frame index: the cut frame is never pushed, so the pushes skip it
      rx_frame = rx_push / 2;
      if (rx_cut >= 0 && reloaded && rx_frame >= rx_cut) rx_frame = rx_frame + 1;
      if (rx_push % 2 == 0) want = sent[rx_frame];
      else want = {1'b1, sent[rx_frame][7:1]};
      if (dut.u_eng.rx_data !== want || rx_frame >= rx_sent) begin
        rx_bad = rx_bad + 1;
        if (rx_bad <= 6)
          $display("*** FAIL reload: RX push %0d (%0s the reload) = %02h, the peer's frame %0d %0s byte is %02h%0s",
                   rx_push, reloaded ? "after" : "before", dut.u_eng.rx_data,
                   rx_frame, (rx_push % 2) ? "stop" : "data", want,
                   (rx_frame >= rx_sent) ? " -- and that frame has not been sent" : "");
      end
    end
    if (reloaded && rx_post < 16) post_push[rx_post] = dut.u_eng.rx_data;
    if (reloaded) rx_post = rx_post + 1;
    rx_push = rx_push + 1;
  end

  // ---- THE SERIAL HOST STREAM (mode 3): 12-bit frames off uo_out[6:4] ------
  // {marker, kind[2:0], data[7:0]} shifted LSB first, one bit per SER_S rise;
  // marker 0 in run mode = an RX payload. Frames that START while PROG is high
  // (or before it fell) are the store readback and are not judged.
  reg  [11:0] sf;
  integer     sbits = 0, s_pay_post = 0;
  reg         s_lasts = 1'b0, s_post = 1'b0;
  reg  [7:0]  s_first_post;
  always @(posedge clk) begin
    if (uo_out[SER_V] !== 1'b1) sbits = 0;
    else if (uo_out[SER_S] === 1'b1 && s_lasts !== 1'b1) begin
      if (sbits == 0) s_post = reloaded && !in_reload && !ui_in[PIN_PROG];
      sf = {uo_out[SER_D], sf[11:1]};
      sbits = sbits + 1;
      if (sbits == 12) begin
        sbits = 0;
        if (s_post && sf[11] == 1'b0) begin
          if (s_pay_post == 0) s_first_post = sf[7:0];
          s_pay_post = s_pay_post + 1;
        end
      end
    end
    s_lasts = uo_out[SER_S];
  end
  reg pend_at_rise = 1'b0;
  initial begin
    @(posedge rst_n);
    forever begin
      @(posedge dut.prog_mode);
      if (reloaded || in_reload) pend_at_rise = dut.rx_pend;
    end
  end

  // ---- SPI PEER WATCH (mode 4): bytes over every CS frame -----------------
  integer sp_rise = 0, sp_byte, sp_bit;
  real    t_cs_up = -1.0, t_sck_up = -1.0;
  reg     sp_cut_seen = 1'b0;
  // any SCK edge the halt causes, either direction (an inverted clock idles
  // the other way)
  always @(uo_out[SCK_UO]) if (mode == 4 && in_reload && t_sck_up < 0)
    t_sck_up = $realtime;
  always @(posedge uo_out[SCK_UO]) if (mode == 4) begin
    if (uo_out[CS_UO] === 1'b0 && !in_reload) begin
      sp_rise = sp_rise + 1;
      sp_byte = (sp_rise - 1) / 8;
      sp_bit  = (sp_rise - 1) % 8 + 1;
      // stop the feeder a byte early, so no push is in flight at the cut
      if (!reloaded && sp_byte == rlf && sp_bit == 1) req_quiet = 1'b1;
    end
  end
  always @(negedge uo_out[SCK_UO]) if (mode == 4 && !reloaded && !in_reload)
    if (uo_out[CS_UO] === 1'b0 && sp_byte == rlf && sp_bit == rlb)
      req_reload = 1'b1;
  always @(posedge uo_out[CS_UO]) if (mode == 4 && in_reload && t_cs_up < 0)
    t_cs_up = $realtime;

  // ---- THE DIAGNOSTIC: the bit pointers at resume -------------------------
  integer ln;
  task diag;
    begin
      $write("# diag: at resume");
      for (ln = 0; ln < 5; ln = ln + 1)
        $write("  L%0d tx_bitp=%0d rx_bitp=%0d", ln, dut.u_eng.tx_bitp[ln],
               dut.u_eng.rx_bitp[ln]);
      $display("");
    end
  endtask

  integer cyc_post, a;
  reg [7:0] snap [0:7];
  reg [7:0] msnap [0:32767];          // the I2C FRAM, before the reload
  integer   i2_mchg = 0, i2_halt_starts = 0;
  reg       snap_bad;
  initial begin
    if (!$value$plusargs("MODE=%d", mode)) mode = 0;
    i2c_mode = (mode == 5 || mode == 7);
    if (!$value$plusargs("RLF=%d", rlf)) rlf = 3;
    if (!$value$plusargs("RLB=%d", rlb)) rlb = 5;
    if (!$value$plusargs("NPOST=%d", npost)) npost = 12;
    // +IMG is the program RELOADED (and, except in mode 2, the one run first):
    // 0 test/uart_tx_image.hex, 1/3 test/uart_rx_image.hex, 2 the TX image
    // (the RX image runs first), 4 the mode0 SPI build, 5/7 the I2C write
    if (!$value$plusargs("IMG=%s", imgfile)) begin
      $display("tb_reload: FATAL -- +IMG is required (the program reloaded)"); $finish;
    end
    bt = 20.0 * BITP;
    hf_init;
    if (mode == 4) begin
      // corpus.FEEDS["corpus_spim"]: WREN WRITE 01 23 5B C4 1E READ 01 23
      hf_n(0, 10);
      hf_put(0, 0, 8'h06); hf_put(0, 1, 8'h02); hf_put(0, 2, 8'h01);
      hf_put(0, 3, 8'h23); hf_put(0, 4, 8'h5B); hf_put(0, 5, 8'hC4);
      hf_put(0, 6, 8'h1E); hf_put(0, 7, 8'h03); hf_put(0, 8, 8'h01);
      hf_put(0, 9, 8'h23);
    end else if (i2c_mode) begin
      // S | A0 | 01 23 | 5B C4 | P: write 5B C4 at 0x0123
      hf_n(0, 5);
      hf_put(0, 0, 8'hA0); hf_put(0, 1, 8'h01); hf_put(0, 2, 8'h23);
      hf_put(0, 3, 8'h5B); hf_put(0, 4, 8'hC4);
    end else begin
      hf_set(0, 8'h5B, 8'hC4, 8'h1E, 8'hA7);  // non-palindromic (ruling 1b)
    end
    hf_mask = 4'b0000;
    $display("# reload mode=%0d rlf=%0d rlb=%0d npost=%0d img=%0s", mode, rlf,
             rlb, npost, imgfile);

    repeat (4) @(negedge clk); rst_n = 1; @(negedge clk);
    sw = (mode == 7);                   // isolated through the first load too
    write_image(mode == 2 ? "test/uart_rx_image.hex" : imgfile);
    run_now;
    if (mode == 5) sw = 1'b1;           // reconnect once PROG is low
    if (mode == 0 || mode == 4 || i2c_mode) begin
      hf_mask = 4'b0001; hf_en = 1'b1; tx_on = (mode == 0);
    end else begin
      if (mode == 3) begin
        // keep the serialiser busy: three bytes on a queue no lane pops sets
        // TX-FULL, and a sticky flag self-starts status frames
        hf_push_byte(8'h00, 2'd1); hf_push_byte(8'h00, 2'd1);
        hf_push_byte(8'h00, 2'd1);
      end
      repeat (BITP) @(posedge clk);
      rx_on = 1'b1;
    end

    fork : wt
      begin
        if (mode == 3) begin
          // the data byte of frame RLF: raise PROG on the push itself
          wait (rx_push == 2 * rlf + 1);
        end else begin
          if (mode == 4 || i2c_mode) begin
            wait (req_quiet); hf_mask = 4'b0000;
          end
          wait (req_reload);
        end
        disable wt;
      end
      begin repeat (2000000) @(posedge clk);
        $display("*** FAIL reload: the peer never reached the reload point"); $finish; end
    join

    if (mode == 0) begin
      // ⛔ PAUSE THE FEEDER FIRST: in load mode ui_in[5]/[6] are PTR/WR, so a
      // push in flight would be a pointer reset or a store write. Masking
      // stops a new push; one already started finishes within 12 clocks.
      hf_mask = 4'b0000;
      repeat (40) @(posedge clk);
    end
    hf_en = 1'b0;
    // the host opens the bus switch BEFORE it raises PROG (mode 5)
    if (mode == 5) sw = 1'b0;
    in_reload = 1'b1;
    if (mode == 4)
      for (a = 0; a < 8; a = a + 1) snap[a] = u_spi.mem[13'h0120 + a];
    if (i2c_mode) begin
      for (a = 0; a < 32768; a = a + 1) msnap[a] = u_i2c.mem[a];
      i2_starts0 = u_i2c.start_cnt;
    end
    write_image(imgfile);
    if (i2c_mode) begin
      i2_mchg = 0;
      for (a = 0; a < 32768; a = a + 1)
        if (u_i2c.mem[a] !== msnap[a]) begin
          if (i2_mchg < 4)
            $display("  i2c peer: during the reload 0x%04h changed %02h -> %02h", a, msnap[a], u_i2c.mem[a]);
          i2_mchg = i2_mchg + 1;
        end
      i2_halt_starts = (u_i2c.start_cnt - i2_starts0 + 256) % 256;
    end
    if (mode == 4) begin
      snap_bad = 1'b0;
      for (a = 0; a < 8; a = a + 1)
        if (u_spi.mem[13'h0120 + a] !== snap[a]) snap_bad = 1'b1;
    end
    // RX: hold PROG until the peer has finished the cut frame and idles
    if (mode == 1 || mode == 2 || mode == 3) wait (rx_idle);
    if (mode == 2) rx_on = 1'b0;
    reloaded = 1'b1;
    run_now;
    if (mode == 5) sw = 1'b1;           // reconnect once PROG is low
    @(posedge clk); #1;
    diag;
    in_reload = 1'b0;
    if (mode == 0 || mode == 2 || mode == 4 || i2c_mode) begin
      // the host's pushes after PROG fell: mode 0 continues its pattern from
      // wherever the feeder stands, the new programs start theirs at byte 0
      if (mode != 0) hf_idx[0] = 0;
      tx_base = tx_starts; pat_off = hf_idx[0];
      hf_mask = 4'b0001; hf_en = 1'b1; tx_on = (mode == 0 || mode == 2);
    end
    i2_starts0 = u_i2c.start_cnt;

    cyc_post = 0;
    while (cyc_post < (npost + 2) * 12 * BITP
           && ((mode == 1) ? rx_post < 2 * npost
               : (mode == 3) ? s_pay_post < 2
               : (mode == 4) ? rx_post < 2
               : i2c_mode ? (u_i2c.mem[15'h0123] !== 8'h5B
                             || u_i2c.mem[15'h0124] !== 8'hC4
                             || u_i2c.start_cnt == i2_starts0)
               : tx_post < npost)) begin
      @(posedge clk); cyc_post = cyc_post + 1;
    end
    repeat (2 * BITP) @(posedge clk);

    fails = 0;
    if (mode == 1) begin
      if (rx_cut < 0) begin
        fails = fails + 1; $display("*** FAIL reload: the RX reload never cut a frame");
      end
      if (rx_post < 2 * npost) begin
        fails = fails + 1;
        $display("*** FAIL reload: only %0d RX push(es) after the reload, %0d required", rx_post, 2 * npost);
      end
      if (rx_bad != 0) begin
        fails = fails + 1;
        $display("*** FAIL reload: %0d RX push(es) are not the peer's whole frames in order", rx_bad);
      end
    end else if (mode == 3) begin
      if (!pend_at_rise) begin
        fails = fails + 1;
        $display("*** FAIL reload: ARM PRECONDITION -- no received byte was pending when PROG rose, so this arm tested nothing");
      end
      if (s_pay_post == 0) begin
        fails = fails + 1;
        $display("*** FAIL reload: no RX payload frame on the serial stream after the reload");
      end else if (s_first_post !== sent[rlf + 1]) begin
        fails = fails + 1;
        $display("*** FAIL reload: the first RX payload after the reload is %02h, the peer's next whole frame is %02h%0s",
                 s_first_post, sent[rlf + 1],
                 (s_first_post === sent[rlf]) ? " -- it is the byte left UNREAD across the reload" : "");
      end
    end else if (mode == 4) begin
      $display("  spi: at the halt CS rose at %0.0f ns, SCK moved at %0.0f ns%0s", t_cs_up,
               t_sck_up, (t_cs_up >= 0 && t_cs_up == t_sck_up)
               ? " -- THE SAME INSTANT (fram_spi would resolve it as a deselect; a real pad pair may not)"
               : "");
      // ⛔ OPTION 1' (Wilson): CS high AT LEAST ONE FULL CLOCK before any SCK
      // edge the halt causes -- a same-cycle rise is RED, because on real
      // pads skew decides the order and SCK first commits a stale bit
      if (t_sck_up >= 0 && (t_cs_up < 0 || t_sck_up - t_cs_up < 20.0)) begin
        fails = fails + 1;
        $display("*** FAIL reload: at the halt SCK moved %0.0f ns after CS rose -- CS must lead any halt-caused SCK edge by at least one clock (20 ns)",
                 t_sck_up - t_cs_up);
      end
      if (snap_bad) begin
        fails = fails + 1;
        $display("*** FAIL reload: the FRAM's memory at 0x0120..0x0127 changed during the halt -- the cut byte was written");
      end
      if (rx_post < 2 || post_push[0] !== 8'h5B || post_push[1] !== 8'hC4) begin
        fails = fails + 1;
        $display("*** FAIL reload: after the reload the READ returned %0d byte(s) %02h %02h, want 5B C4",
                 rx_post, post_push[0], post_push[1]);
      end
      if (u_spi.mem[13'h0123] !== 8'h5B || u_spi.mem[13'h0124] !== 8'hC4
          || u_spi.mem[13'h0125] !== 8'h1E) begin
        fails = fails + 1;
        $display("*** FAIL reload: FRAM 0x0123.. = %02h %02h %02h, want 5B C4 1E",
                 u_spi.mem[13'h0123], u_spi.mem[13'h0124], u_spi.mem[13'h0125]);
      end
    end else if (i2c_mode) begin
      $display("  i2c peer during the reload: %0d START(s), %0d pull-down(s) (ACK/data), %0d memory byte(s) changed",
               i2_halt_starts, i2_acks, i2_mchg);
      if (u_i2c.start_cnt == i2_starts0) begin
        fails = fails + 1;
        $display("*** FAIL reload: no I2C transaction reached the peer after the reload");
      end
      if (u_i2c.mem[15'h0123] !== 8'h5B || u_i2c.mem[15'h0124] !== 8'hC4) begin
        fails = fails + 1;
        $display("*** FAIL reload: after the reload FRAM 0x0123.. = %02h %02h, want 5B C4 -- the next transaction was not clean",
                 u_i2c.mem[15'h0123], u_i2c.mem[15'h0124]);
      end
    end else begin
      if (tx_post < npost) begin
        fails = fails + 1;
        $display("*** FAIL reload: only %0d whole TX frame(s) after the reload, %0d required", tx_post, npost);
      end
      if (tx_bad != 0) begin
        fails = fails + 1;
        $display("*** FAIL reload: %0d TX frame(s) are not the host's bytes in order", tx_bad);
      end
      if (rx_bad != 0) fails = fails + 1;
    end
    if (qw_bad != 0) fails = fails + 1;
    if (mode == 7) begin
      // ⛔ THE HARM DEMONSTRATION -- A MEASUREMENT OF THE DOCUMENTED LIMIT, NOT
      // A PASS. The peer stayed connected through the load (no bus switch),
      // so it saw the image on `uio`; what it did is recorded, never judged.
      $display("RELOAD-DEMO: mode 7 (I2C peer CONNECTED through the load -- the HOST_INTERFACE limit): %0d START(s), %0d peer pull-down(s), %0d FRAM byte(s) changed during the reload",
               i2_halt_starts, i2_acks, i2_mchg);
      $finish;
    end
    if (fails == 0)
      $display("RELOAD: ok -- mode %0d, reloaded at bit %0d of %0s %0d: %0s",
               mode, rlb, (mode == 4) ? "byte" : "frame", rlf,
               mode == 0 ? "every whole TX frame is the host's byte in order; the first after the reload is the first byte pushed after PROG fell"
               : mode == 1 ? "the cut frame was never pushed; every push after is the peer's next whole frame, count exact"
               : mode == 2 ? "after reloading RX -> TX the frames are the feed from its first byte; the old receive lane pushed nothing"
               : mode == 3 ? "a byte pending when PROG rose never reached the host stream; the first payload after is the peer's next frame"
               : mode == 5 ? "the I2C peer, isolated by the bus switch during the load, saw a clean write after the reload (FRAM 0x0123 = 5B C4); no pad moved before dispatch"
               : "CS rose at least one clock before any halt-caused SCK edge, the cut byte was not written, and after the reload the READ returned 5B C4");
    $finish;
  end
endmodule
`default_nettype wire
