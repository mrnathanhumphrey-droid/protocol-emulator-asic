`default_nettype none
`timescale 1ns / 1ps

/* PINS OUTSIDE THE REAL RANGE: refused, or driving nothing (ruling (a) item 1).
 *
 * `PINW = 4` addresses 0..15 while `N_PINS = 12`, and the two cases are NOT the
 * same thing. The engine must tell them apart:
 *
 *   MODE=0  an OPEN-DRAIN lane on a `uo_out` pin (`pin >= N_UIO`). `uo_out` has
 *           no output enable, so such a lane drives low once and STICKS. The
 *           loader must REFUSE the program -- sticky `config_err`, nothing
 *           emitted.                        pe_engine.v:1143 and :1145
 *
 *   MODE=1  a lane on the RESERVED NON-DRIVING INDEX (`PIN_NONE = 15`). This is
 *           LEGAL: the lane runs, and every pin write is simply suppressed.
 *           ⛔ It must NOT be refused -- a refusal here would break the no-op
 *           half-bit idiom, which names the reserved index on purpose.
 *                     pe_engine.v:1158 (the `pin_pp` write guard),
 *                     :1352 (OP_SHIFT), :1446 (OP_SHIFTIN / OP_READBIT)
 *
 * ⛔⛔ WHY MODE=0 EXISTS WHEN COCOTB ALREADY TESTS IT -- AND IT IS A CORRECTION.
 * I reported to Wilson that "half the 1.6s load-time refusal has never fired".
 * That was WRONG. `cfgerr_image.hex` is `hdr(UO0, UO0, 0, ...)` -- open-drain
 * with BOTH pins at UO0 = 8 >= N_UIO = 8 -- and `test/test.py` has run it as
 * `test_config_error_refuses_to_run` all along. Measured directly: under that
 * image, 1143's and 1145's taken arms each fire once.
 * ⇒ The point read as uncovered because the COCOTB TOPLEVEL `tb.v` is the one
 * bench `benchset.py` excludes (it has no self-checking PASS line, so a
 * `--binary` run cannot read a verdict from it). A sweep with a blind spot
 * keeps manufacturing false gaps, so the arm is brought somewhere the sweep can
 * see it AND given a Verilog-side assertion, rather than left to cocotb alone.
 *
 * ⚠ WHAT THE X CHECK IS WORTH, STATED. `^pins === 1'bx` catches the
 * out-of-range-write / contention class under IVERILOG, which starts a flop at
 * X. Verilator is two-state, so the same check is VACUOUS there -- and the
 * coverage sweep runs Verilator. The check earns its keep in the parameter
 * sweep and by-hand iverilog runs; it is not evidence under the sweep.
 */
module tb_pinrange ();

  parameter integer SPL_CFG = 2;

  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00, uio_in = 8'h00;
  wire [7:0] uo_out, uio_out, uio_oe;
  integer    i, fails = 0, mode, img_bytes, ncyc, cyc;
  integer    edges, busy_cyc, xseen, xser;
  reg  [3:0] prev_proto;
  reg  [7:0] prev_uio;
  reg [8*160-1:0] imgfile;
  reg  [7:0] img [0:255];

  localparam integer PIN_PROG = 7, PIN_PTR = 5, PIN_WR = 6;
  localparam integer N_LANES = 5;
  localparam [1:0]   ST_IDLE = 2'd0;

  always #5 clk = ~clk;

  tt_um_protocol_emulator #(.SPL(SPL_CFG)) dut (
      .ui_in(ui_in), .uo_out(uo_out), .uio_in(uio_in),
      .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );

  task fail;
    input [8*72-1:0] msg;
    begin
      $display("  *** FAIL: %0s", msg);
      fails = fails + 1;
    end
  endtask

  task load_image;
    begin
      ui_in[PIN_PROG] = 1'b1;
      ui_in[PIN_PTR] = 1'b1; @(negedge clk);
      ui_in[PIN_PTR] = 1'b0; @(negedge clk);
      for (i = 0; i < img_bytes; i = i + 1) begin
        uio_in = img[i];
        @(negedge clk); @(negedge clk);
        ui_in[PIN_WR] = 1'b1;
        @(negedge clk); @(negedge clk); @(negedge clk);
        ui_in[PIN_WR] = 1'b0;
        @(negedge clk);
      end
      ui_in[PIN_PROG] = 1'b0;
      ui_in = 8'h00;
      uio_in = 8'hFF;
    end
  endtask

  initial begin
    if (!$value$plusargs("IMG=%s", imgfile)) begin
      $display("tb_pinrange: FATAL -- +IMG=<file> is required");
      $finish;
    end
    if (!$value$plusargs("NBYTES=%d", img_bytes)) begin
      $display("tb_pinrange: FATAL -- +NBYTES=<n> is required. An image that");
      $display("  never loaded drives nothing, and 'no pin moved' would then");
      $display("  read as a PASS for the wrong reason.");
      $finish;
    end
    if (!$value$plusargs("NCYC=%d", ncyc)) ncyc = 8000;
    if (!$value$plusargs("MODE=%d", mode)) mode = 0;
    $readmemh(imgfile, img);
    $display("# pinrange img=%0s bytes=%0d mode=%0d SPL=%0d",
             imgfile, img_bytes, mode, SPL_CFG);

    repeat (4) @(posedge clk);
    rst_n = 1;
    @(posedge clk);
    load_image;

    edges = 0; busy_cyc = 0; xseen = 0; xser = 0;
    prev_proto = uo_out[3:0];
    prev_uio   = uio_out;
    for (cyc = 0; cyc < ncyc; cyc = cyc + 1) begin
      @(posedge clk);
      // ⭐ EVERY PROTOCOL PIN, not just the one the lane names. Neither image
      // should move ANY pin: MODE=0 is refused before dispatch, and in MODE=1
      // lane 0 names the reserved index while the filler lanes carry only
      // `OP_REARM`, which moves no pin by construction.
      if (uo_out[3:0] !== prev_proto) edges = edges + 1;
      if (uio_out !== prev_uio)       edges = edges + 1;
      prev_proto = uo_out[3:0];
      prev_uio   = uio_out;
      // ⛔⛔ THE TWO X POPULATIONS ARE COUNTED SEPARATELY, and conflating them
      // is how this check first reported a pass as a failure. `^uo_out` spans
      // all eight bits, but only `uo_out[3:0]` are PROTOCOL pins --
      // `uo_q <= {1'b0, ser_v, ser_s, ser_d, proto_out}`, so bits 6:4 are the
      // serial readback. An X there is a different defect from an X on a
      // driven pin, and this bench's claim is about pin WRITES.
      if ((^uo_out[3:0] === 1'bx) || (^uio_out === 1'bx)) begin
        if (xseen == 0)
          $display("    DIAG first protocol X at cyc %0d: uo=%b uio=%b oe=%b",
                   cyc, uo_out, uio_out, uio_oe);
        xseen = xseen + 1;
      end
      if (^uo_out[6:4] === 1'bx) begin
        if (xser == 0)
          $display("    DIAG first serial X at cyc %0d: uo=%b (bit 4 = ser_d)",
                   cyc, uo_out);
        xser = xser + 1;
      end
      if (dut.u_eng.st !== ST_IDLE) busy_cyc = busy_cyc + 1;
    end

    $display();
    if (mode == 0) begin
      $display("===== tb_pinrange: OPEN-DRAIN ON uo_out MUST BE REFUSED =====");
      $display("  `uo_out` has no output enable, so an open-drain lane there");
      $display("  drives low once and sticks. The loader must refuse it.");
      $display("    config_err (sticky)      : %0b %0s",
               dut.u_eng.config_err,
               dut.u_eng.config_err ? "ok -- REFUSED"
               : "*** FAIL -- the program was accepted");
      if (!dut.u_eng.config_err)
        fail("an open-drain lane on uo_out was not refused");
      // ⛔ AND THE REFUSAL MUST SUPPRESS THE OUTPUT. A flag set beside a lane
      // that drove anyway is not a refusal; it is the defect with a flag
      // next to it -- the same thing the 1.6x guard had to be fixed for.
      $display("    protocol pin edges       : %0d %0s", edges,
               (edges == 0) ? "ok -- nothing was emitted"
               : "*** FAIL -- a refused program drove its pins");
      if (edges != 0)
        fail("the refused program still moved a pin");
    end else begin
      $display("===== tb_pinrange: THE RESERVED INDEX IS LEGAL, DRIVES NONE ==");
      $display("  PIN_NONE = 15 names no pin. The lane must RUN -- the no-op");
      $display("  half-bit idiom depends on it -- and every pin write must be");
      $display("  suppressed, including OP_SHIFT's CLOCK write.");
      $display("    config_err (sticky)      : %0b %0s",
               dut.u_eng.config_err,
               dut.u_eng.config_err ? "*** FAIL -- refused, but it is legal"
               : "ok -- accepted");
      if (dut.u_eng.config_err)
        fail("a lane on the reserved index was refused; it is legal");
      $display("    lane 0 live              : %0b %0s", dut.u_eng.l_live[0],
               dut.u_eng.l_live[0] ? "ok -- running" : "*** FAIL -- halted");
      if (!dut.u_eng.l_live[0])
        fail("the reserved-index lane was halted");
      // ⛔ IT MUST HAVE ACTUALLY DISPATCHED. "No pin moved" is trivially true
      // of a lane that never ran, and that is the vacuous pass this bench
      // would otherwise report -- the same shape as a bench whose image never
      // loaded.
      $display("    cycles with the FSM busy : %0d %0s", busy_cyc,
               (busy_cyc > 0) ? "ok -- the lane dispatched"
               : "*** FAIL -- nothing ran, so 'no pin moved' is vacuous");
      if (busy_cyc == 0)
        fail("the engine never dispatched, so the claim is vacuous");
      $display("    protocol pin edges       : %0d %0s", edges,
               (edges == 0) ? "ok -- every pin write suppressed"
               : "*** FAIL -- a pin moved for a lane that names no pin");
      if (edges != 0)
        fail("a pin moved although the lane names the reserved index");
    end
    $display("    X on the PROTOCOL pins   : %0d %0s", xseen,
             (xseen == 0) ? "ok -- no out-of-range write reached a pin"
             : "*** FAIL -- out-of-range write or contention");
    if (xseen != 0)
      fail("X appeared on a driven protocol pin");
    // ⛔⛔ FIXED UNDER RULING 1, AND NOW ASSERTED. It was an open defect
    // when this bench first ran, and is kept as a hard check because the
    // reserved-index arm puts X on `ser_d` (uo_out[4]) for exactly as many
    // cycles as it dispatches SHIFTs, and the cause is an UNGUARDED
    // OUT-OF-RANGE READ: `pin_in[a_pin]` at pe_engine.v:745, :1502 and :1524
    // is read with no `pin_real` guard, so `OP_SHIFTIN`/`OP_READBIT` on
    // PIN_NONE = 15 samples `pin_in[15]` against a [11:0] vector. The X lands
    // in `l_rx`, then `rx_data`, then the serial readback, and leaves the chip.
    // ⭐ IT IS THE MIRROR OF A DEFECT ALREADY FIXED: the WRITE side was
    // guarded after the `pin_out[12]` incident (`pin_real` at 1352, `clk_real`
    // at 1428, the `pin_pp` guard at 1158) and the SAMPLE side was not -- "a
    // fix on one axis repeats the error on a parallel one".
    // ⚠ CONTROL RUN, so this is not a property of the check: smoke_image,
    // five_image and cfgerr_image all give ZERO serial X; only the
    // reserved-index program produces it.
    // ⇒ RULED (Wilson 1): silicon samples a DEFINED 0 on a non-real pin
    // (`rx_bit = pin_real ? pin_in[a_pin] : 1'b0`, one wire for all three
    // sites), so X can never leave the chip by construction. PRICED: build
    // with `M_UNGUARDED_SAMPLE` and this count goes 0 -> 112.
    $display("    X on ser_d (uo_out[4])   : %0d %0s", xser,
             (xser == 0) ? "ok -- the sample guard holds"
             : "*** FAIL -- an out-of-range sample reached the serial output");
    if (xser != 0)
      fail("X on ser_d: the pin_in[a_pin] range guard is gone");
    $display("      ⚠ both X checks are VACUOUS under Verilator (two-state),");
    $display("        so they are evidence only in an iverilog run.");

    $display();
    if (fails == 0)
      $display("  tb_pinrange: PASS (%0s)",
               (mode == 0) ? "open-drain on uo refused"
                           : "reserved index legal, drives nothing");
    else
      $display("  tb_pinrange: *** FAILED %0d check(s)", fails);
    $finish;
  end

endmodule
`default_nettype wire
