/* tb_i2c.v -- run a full I2C transaction and DUMP IT FOR A FOREIGN DECODER.
 *
 * ⛔⛔ WHY. Every I2C claim this project has made is SAME-HAND: our engine
 * against our own peer model -- `fram_i2c.v` says so in its own header -- and
 * our own benches reading our own expectations. `tb_half` proved the PLUMBING
 * (a pushed byte reaches the wire, a sampled byte reaches the host) and said so
 * explicitly; it did not prove a frame any I2C device would accept.
 * ⇒ This bench writes the two bus lines to a file in `sigrok`'s `binary` input
 *   format so sigrok's `i2c` protocol decoder -- code written from the standard
 *   by people who have never seen this design -- can adjudicate START, the
 *   address, the ACK and STOP. `test/run_i2c.py` runs it and reads the verdict.
 *
 * ⭐ THE PEER IS REAL, NOT A STUB. `fram_i2c` drives the acknowledge, so the
 * ACK on the wire is a device responding to an address it recognised, not the
 * bench holding a pin low on a schedule.
 *
 * ⛔ OPEN-DRAIN RESOLUTION IS DONE HERE, EXPLICITLY. Both the DUT and the peer
 * export PULL-LOW enables and never drive a high; the line is the AND of
 * everybody releasing it. Writing `uio_out` into the dump instead would record
 * what the DUT intended rather than what the bus carried -- and on an ACK those
 * differ, which is the whole point of the bit.
 *
 * ⚠ WHAT THE DUMP CANNOT SETTLE: timing against the UM10204 limits. sigrok's
 * decoder is tolerant of rate; it adjudicates FRAMING and BYTE VALUES. The
 * electrical timing is `gate_i2c_phase.py`'s claim, from the datasheet table.
 */

`default_nettype none
`timescale 1ns / 1ps

`include "test/imgload.vh"
module tb_i2c;

  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00;
  wire [7:0] uo_out, uio_out, uio_oe;

  localparam integer PIN_PROG = 7, PIN_PTR = 5, PIN_WR = 6;
`include "test/store_filler.vh"   // v2: PE_STORE_BYTES, never a typed 256
  localparam integer IMG_MAX  = PE_STORE_BYTES;
  localparam integer P_SDA = 2, P_SCL = 1;

  reg  [7:0] img [0:IMG_MAX-1];
  integer    img_bytes, i, cyc, ncyc, fd, nwr;
  integer    txb;   // bytes per I2C transaction: 2 (certified) or 3
  reg [8*256-1:0] imgfile, dumpfile;

  // ---- the resolved open-drain bus ------------------------------------
  // ⛔ A PULL-UP IS A RELEASE, NOT A DRIVE. `sda`/`scl` are 1 unless somebody
  // pulls them low, and "somebody" is the DUT's output enable or the peer's.
  // ⚠ `uio_oe[p] && !uio_out[p]` is the DUT pulling low; an open-drain lane
  // never sets `uio_out` high, and `pin_pp` makes that unsatisfiable at the
  // flop rather than relying on this expression being written correctly.
  wire dut_sda_low = uio_oe[P_SDA] && !uio_out[P_SDA];
  wire dut_scl_low = uio_oe[P_SCL] && !uio_out[P_SCL];
  wire peer_sda_low, peer_scl_low;
  wire sda = !(dut_sda_low || peer_sda_low);
  wire scl = !(dut_scl_low || peer_scl_low);

  // the DUT samples the RESOLVED lines, as a real device would
  reg  [7:0] uio_drv;
  wire [7:0] uio_in = uio_drv;
  always @(*) begin
    uio_drv = 8'hFF;
    uio_drv[P_SDA] = sda;
    uio_drv[P_SCL] = scl;
  end

  always #10 clk = ~clk;

  parameter integer SPL_CFG = 2;

  tt_um_protocol_emulator #(.SPL(SPL_CFG)) dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );

  fram_i2c #(.DEV_SEL(3'b000), .STRETCH(0)) peer (
      .clk(clk), .scl_in(scl), .sda_in(sda),
      .sda_oe(peer_sda_low), .scl_oe(peer_scl_low)
  );

`include "test/progress.vh"
`include "test/clocked_conform.vh"
`include "test/host_feed.vh"

  // ---- liveness, so a silent run cannot pass -------------------------
  integer n_sda_edge, n_scl_edge, n_peer_ack;
  reg prev_sda, prev_scl, prev_pack;
  reg primed_seen, cfgerr_seen;
  integer fails;

  // ---- a diagnostic on the PEER's byte assembly, behind a plusarg -------
  // The peer is same-hand and its address-match branch had never fired, so
  // when it refuses to acknowledge a frame sigrok calls well formed, the
  // question is which side is counting wrong. Reasoning about its counter
  // produced one wrong answer already; this prints it.
  integer ndiag, diag_on;
  initial begin
    ndiag = 0;
    if (!$value$plusargs("DIAG=%d", diag_on)) diag_on = 0;
  end
  always @(posedge scl) begin
    if (diag_on && dut.u_eng.primed && ndiag < 40) begin
      $display("    PEER cyc=%0d sda=%0b active=%0b bitn=%0d shin=%02h done=%0b phase=%0d ack=%0b",
               cyc, sda, peer.bus_active, peer.bitn, peer.shin,
               peer.byte_done, peer.phase, peer.ack_low);
      ndiag = ndiag + 1;
    end
  end

  initial begin
    if (!$value$plusargs("IMG=%s", imgfile)) begin
      $display("tb_i2c: FATAL -- +IMG=<file> is required."); $finish;
    end
    if (!$value$plusargs("NBYTES=%d", img_bytes)) begin
      $display("tb_i2c: FATAL -- +NBYTES=<n> is required."); $finish;
    end
    if (!$value$plusargs("DUMP=%s", dumpfile)) dumpfile = "probe_i2c.bin";
    if (!$value$plusargs("NCYC=%d", ncyc)) ncyc = 40000;
    $readmemh(imgfile, img);
    `PE_REQUIRE_IMG_LOADED(imgfile)

    if (!$value$plusargs("TXB=%d", txb)) txb = 2;
    hf_init;
    // ⭐ BYTES GO OUT IN PUSH ORDER, FROM THE FIRST (silicon fix #8). The
    // pattern used to be [data, addr, data, addr] so that every transaction
    // AFTER the first was valid -- the first byte out was the register's reset
    // 0x00, which made the first transaction a GENERAL CALL (every general-
    // call device on a real bus ACKs it). That workaround is removed.
    // `0xA0` is `1010 000 0` -- the MB85RC256V device address with A2/A1/A0
    // strapped to 0 and R/W = 0 (write).
    // ⭐ THE REFUSAL IS NOW BY DESIGN: TXB = 2 alternates the part's address
    // with 0xA2 (`1010 001 0`, address 0x51, which this part must NACK), so
    // `run_i2c`'s non-vacuity check sees both outcomes -- it used to lean on
    // the accidental 0x00.
    // ⭐ PUSHED AS THEMSELVES, because the lane header now declares
    // ORDER_MSB and the engine reverses at the load. 0xA0 is the MB85RC256V
    // device address (1010 000 0, write); 0x5B is the data byte and it is
    // NON-PALINDROMIC -- it reverses to 0xDA -- so sigrok reading `5B` is
    // evidence about the ORDER, which 0x5A could never have been.
    // ⚠ BEFORE THE ORDER BIT this read {5A, 05, 5A, 05}: the address had to be
    // pushed pre-reversed and the data byte was a palindrome, so the whole
    // frame passed under either bit order (ruling 1b).
    // ⭐⭐ `+TXB` SELECTS THE TRANSACTION LENGTH. At TXB = 2 (the certified
    // frame) the transactions alternate (0xA0, 0x5B) -- acknowledged -- and
    // (0xA2, 0x5B) -- refused. At TXB = 3 the pattern is the 3-byte cycle
    // [0xA0, 0x01, 0x23], so EVERY transaction is `dev A0, addrhi 01, addrlo
    // 23` and the peer's address register must land on 0x0123. (With the
    // reset 0x00 first, a 4-byte pattern rotated against the 3-byte frame and
    // only every FOURTH transaction was well-formed.)
    // ⚠ EVERY BYTE IS NON-PALINDROMIC (ruling 1b): A0/05, 5B/DA, A2/45,
    // 01/80, 23/C4, so every byte sigrok reads is evidence about bit ORDER.
    if (txb == 3) begin
      hf_n(0, 3);
      hf_put(0, 0, 8'hA0); hf_put(0, 1, 8'h01); hf_put(0, 2, 8'h23);
    end else begin
      hf_set(0, 8'hA0, 8'h5B, 8'hA2, 8'h5B);
    end

    cyc = 0; nwr = 0; fails = 0;
    n_sda_edge = 0; n_scl_edge = 0; n_peer_ack = 0;
    prev_sda = 1'b1; prev_scl = 1'b1; prev_pack = 1'b0;
    primed_seen = 1'b0; cfgerr_seen = 1'b0;

    fd = $fopen(dumpfile, "wb");
    if (fd == 0) begin
      $display("tb_i2c: FATAL -- cannot open %0s for writing", dumpfile);
      $finish;
    end
    $display("# i2c img=%0s bytes=%0d ncyc=%0d dump=%0s",
             imgfile, img_bytes, ncyc, dumpfile);

    repeat (4) @(negedge clk);
    rst_n = 1;
    @(negedge clk);
    ui_in[PIN_PROG] = 1'b1;
    repeat (3) @(negedge clk); ui_in[PIN_PTR] = 1'b1; repeat (3) @(negedge clk);  // CDC3: prog >= 3 cy before ptr; ptr >= 3 cy wide
    ui_in[PIN_PTR] = 1'b0; repeat (3) @(negedge clk);
    // ⛔ THE IMAGE GOES IN ON `uio_in`, WHICH THIS BENCH DRIVES FROM THE
    // RESOLVED BUS -- so during load the two uses collide. The load therefore
    // writes the byte through a dedicated override, and the bus model only
    // owns `uio_in` once PROG drops.
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

    // ---- run, writing one byte per CYCLE: bit0 = SCL, bit1 = SDA ------
    // ⛔ CHANNEL ORDER IS DECLARED AND MUST MATCH THE DECODER INVOCATION.
    // `sigrok-cli -P i2c:scl=0:sda=1` reads channel 0 as SCL and 1 as SDA; a
    // swap decodes nothing, which would look exactly like a bad frame.
    for (i = 0; i < ncyc; i = i + 1) begin
      @(posedge clk);
      cyc = cyc + 1;
      if (dut.u_eng.primed)     primed_seen = 1'b1;
      if (dut.u_eng.config_err) cfgerr_seen = 1'b1;
      if (sda !== prev_sda) n_sda_edge = n_sda_edge + 1;
      if (scl !== prev_scl) n_scl_edge = n_scl_edge + 1;
      if (peer_sda_low && !prev_pack) n_peer_ack = n_peer_ack + 1;
      prev_sda = sda; prev_scl = scl; prev_pack = peer_sda_low;
      $fwrite(fd, "%c", {6'b000000, sda, scl});
      nwr = nwr + 1;
    end
    $fclose(fd);

    $display();
    $display("========== tb_i2c: a transaction on the wire ==========");
    $display("  primed / config_err : %0b / %0b %0s", primed_seen, cfgerr_seen,
             (primed_seen && !cfgerr_seen) ? "ok" : "*** FAIL");
    if (!primed_seen || cfgerr_seen) fails = fails + 1;
    $display("  samples written     : %0d", nwr);
    $display("  SDA edges / SCL edges: %0d / %0d", n_sda_edge, n_scl_edge);
    // ⛔⛔ LIVENESS BEFORE DECODING. A dump of a line that never moved would
    // make sigrok report nothing, and "the decoder found no frame" reads the
    // same whether the bus was silent or the framing was wrong. Both lines
    // must have moved, and the PEER must have acknowledged at least once --
    // which also proves the address on the wire was one it recognised.
    if (n_sda_edge < 8 || n_scl_edge < 8) begin
      $display("  *** FAIL: the bus barely moved -- nothing to decode");
      fails = fails + 1;
    end
    $display("  peer ACK pulses     : %0d %0s", n_peer_ack,
             (n_peer_ack > 0) ? "ok -- the device recognised an address"
             : "*** FAIL -- the peer never acknowledged");
    if (n_peer_ack == 0) fails = fails + 1;
    // ⭐⭐ THE PEER'S ADDRESS REGISTER, WHICH IS THE PROOF `P_ALO` RAN. A
    // transaction of `dev | addrhi | addrlo` must leave the model holding the
    // assembled address, and the model builds it in two halves:
    //     P_AHI : addr[AW-1:8] <= shin[AW-9:0]   (0x01 & 0x7F = 0x01)
    //     P_ALO : addr[7:0]    <= shin           (0x23)
    // so `addr == 0x0123` is reachable ONLY by executing both phases. The
    // coverage sweep found `P_ALO` at zero; this is the claim that closes it,
    // rather than the count alone.
    // ⚠ ONLY AT TXB = 3. The certified 2-byte frame stops at P_AHI by
    // construction -- its second byte IS the high address byte -- and
    // asserting an assembled address there would assert something the frame
    // cannot produce.
    if (txb == 3) begin
      $display("  peer phase reached  : %0d %0s", peer.phase,
               (peer.phase >= 3'd2) ? "ok -- past P_AHI" : "(see addr below)");
      $display("  peer addr register  : %04h %0s", peer.addr,
               (peer.addr == 15'h0123) ? "ok -- P_AHI and P_ALO both ran"
               : "*** FAIL -- the two address bytes did not assemble");
      if (peer.addr !== 15'h0123) begin
        fails = fails + 1;
        $display("      expected 0x0123 from addrhi 0x01 and addrlo 0x23.");
        $display("      A value of 0x__23 with the high half wrong means");
        $display("      P_ALO ran and P_AHI did not; 0x01__ means the reverse.");
      end
    end
    $display();
    if (fails == 0) $display("  tb_i2c: PASS (dump written, bus live, peer ACKed)");
    else            $display("  tb_i2c: *** FAILED %0d check(s)", fails);
    $display("  I2CDUMP file=%0s samples=%0d sda_edges=%0d scl_edges=%0d acks=%0d",
             dumpfile, nwr, n_sda_edge, n_scl_edge, n_peer_ack);
    $finish;
  end

endmodule

`default_nettype wire
