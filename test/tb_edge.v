/* tb_edge.v -- the four must-fires for the REACTIVE release (edge capture).
 *
 * THE ONE CLAIM: a peer edge releases a lane, the lane's timing grid anchors to
 * THAT EDGE, a silent peer halts the lane instead of letting it invent data,
 * and an edge arriving before ARM is ignored.
 *
 * ⛔⛔ A SEPARATE BENCH ON PURPOSE. `tb_smoke.v` owns C, J, the buffer-swap
 * invariant and the cold/steady split -- it is the artefact every published
 * timing number is measured on, and it passes. Bolting input-driving and four
 * new assertions onto it would put all of that at risk to test something
 * orthogonal. This bench drives PROTOCOL INPUTS during run, which `tb_smoke`
 * never does.
 *
 * ⭐ WHY DRIVING INPUTS IS THE REAL COST OF THIS WORK, not the 46 flops: the
 * reactive direction cannot be tested at all without a peer, and a peer is a
 * stimulus generator the project did not have. Phase 2 needs exactly this for
 * the two-simulator byte-exact harness, so it is not spent twice.
 *
 * THE FOUR MUST-FIRES (Wilson, after the edge-capture flag-back):
 *   1 REBASE     the grid anchors to the edge, not to the ARM's deadline.
 *                Checked DIFFERENTIALLY -- the edge is placed at several phases
 *                relative to the deadline and `t_out - t_edge` must be
 *                CONSTANT. ⭐ That proves the anchor without depending on the
 *                unresolved half-bit-offset question.
 *   2 NO EDGE    no edge means no release.
 *   3 TIMEOUT    silence halts the lane, sets the sticky TIMEOUT flag, and
 *                executes ZERO further actions.
 *   4 STRETCH    an I2C SCL held low delays the high phase -- the release
 *                waits for the OBSERVED rise, so the following action slides
 *                by exactly the stretch.
 */

`default_nettype none
`timescale 1ns / 1ps

module tb_edge;

  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00;
  reg  [7:0] uio_drv = 8'h00;
  reg  [7:0] uio_oe_tb = 8'h00;     // which uio bits the BENCH drives
  wire [7:0] uo_out, uio_out, uio_oe;
  wire [7:0] uio_in;

  // ⛔ A RESOLVED BUS, not a driven input. `uio` is bidirectional: the engine
  // drives a bit when `uio_oe` is set and the bench drives it otherwise. Simply
  // forcing `uio_in` would hide a contention bug -- the engine driving the same
  // pin the peer is driving -- which is a real failure on a shared bus and
  // exactly what 1.6r's MISO work was about.
  genvar b;
  generate
    for (b = 0; b < 8; b = b + 1) begin : g_bus
      assign uio_in[b] = uio_oe[b]    ? uio_out[b]
                       : uio_oe_tb[b] ? uio_drv[b]
                       : 1'b1;                       // idle high (pull-up)
    end
  endgenerate

  always #10 clk = ~clk;

  localparam integer IMG_MAX = 256;
  reg [7:0] img [0:IMG_MAX-1];
  integer   img_bytes;
  reg [8*64-1:0] imgfile;

  integer i, errors, cyc;
  integer t_edge, t_out, seen_out;
  reg     prev_uo0;
  integer arm_pin;

  localparam integer PIN_PROG = 7;   // ui_in[7] prog_mode
  localparam integer PIN_PTR  = 5;
  localparam integer PIN_WR   = 6;

  // ------------------------------------------------------------------
  task load_and_run;
    begin
      ui_in = 8'h00; uio_oe_tb = 8'h00; uio_drv = 8'h00;
      rst_n = 0;
      repeat (4) @(posedge clk);
      rst_n = 1;
      @(posedge clk);
      // LOAD
      ui_in[PIN_PROG] = 1'b1;
      uio_oe_tb = 8'hFF;                  // the bench owns uio during load
      ui_in[PIN_PTR] = 1'b1; @(posedge clk);
      ui_in[PIN_PTR] = 1'b0; @(posedge clk);
      for (i = 0; i < img_bytes; i = i + 1) begin
        uio_drv = img[i];
        @(posedge clk); @(posedge clk);
        ui_in[PIN_WR] = 1'b1;
        @(posedge clk); @(posedge clk); @(posedge clk);
        ui_in[PIN_WR] = 1'b0;
        @(posedge clk);
      end
      // RUN. ⛔ release every uio bit EXCEPT the arm pin, which the bench now
      // drives as the peer. The engine must not be driving it either -- an
      // input pin is one no action targets.
      ui_in[PIN_PROG] = 1'b0;
      uio_oe_tb = (8'h01 << arm_pin);
      uio_drv   = 8'hFF;                  // peer idle HIGH
      @(posedge clk);
    end
  endtask

  // ⛔⛤ WAIT FOR THE LANE TO BE ARMED BEFORE STIMULATING IT. The first version
  // of this bench drove the peer edge at a fixed cycle after run entry, and
  // every edge landed BEFORE `OP_ARM` had dispatched -- the header load plus
  // prime-before-release take ~100 cycles, and the phases were 40..109. The
  // edges were therefore correctly IGNORED (Ruling 3: an edge before ARM has
  // nothing holding it), the lane then timed out, and must-fires 1 and 4
  // reported "no output edge at all".
  // ⭐ That was the BENCH measuring the wrong window, not the design failing --
  // and the pass of must-fire 2/3 next to the failure of 1/4 is what said so:
  // the absence tests passed because absence is what an unarmed lane produces.
  // `phase` now means CYCLES AFTER ARMING, which is the quantity Ruling 1 is
  // about: where the edge falls relative to the ARM's deadline.
  task wait_armed(input integer limit);
    begin
      armed_at = -1;
      for (i = 0; i < limit; i = i + 1) begin
        @(posedge clk);
        cyc = cyc + 1;
        prev_uo0 = uo_out[0];
        if (dut.u_eng.l_armed[0] === 1'b1 && armed_at < 0) begin
          armed_at = cyc;
          i = limit;                     // leave the loop
        end
      end
    end
  endtask

  // run `n` cycles, recording the first uo_out[0] change after `from`
  task run_cycles(input integer n);
    begin
      for (i = 0; i < n; i = i + 1) begin
        @(posedge clk);
        cyc = cyc + 1;
        if (uo_out[0] !== prev_uo0 && seen_out == 0 && t_edge >= 0
            && cyc > t_edge) begin
          t_out = cyc; seen_out = 1;
        end
        prev_uo0 = uo_out[0];
      end
    end
  endtask

  // ------------------------------------------------------------------
  integer k, phase, delta, delta0, mismatch, armed_at;
  integer to_lane_live, to_flag, acts_after;

  initial begin
    errors = 0;
    if (!$value$plusargs("IMG=%s", imgfile)) imgfile = "test/edge_image.hex";
    $readmemh(imgfile, img);
    img_bytes = 0;
    for (i = 0; i < IMG_MAX; i = i + 1)
      if (^img[i] !== 1'bx) img_bytes = i + 1;
    arm_pin = 0;
    $display("");
    $display("==== tb_edge: the REACTIVE release ====");
    $display("  image %0s: %0d bytes   arm pin uio[%0d]", imgfile, img_bytes,
             arm_pin);
    if (img_bytes < 20) begin
      $display("FAIL: image too short (%0d bytes)", img_bytes);
      errors = errors + 1;
    end

    // =================================================================
    // MUST-FIRE 1 -- REBASE: t_out - t_edge must not depend on the phase
    // =================================================================
    $display("");
    $display("  --- 1 REBASE: the grid anchors to the EDGE, not the deadline ---");
    $display("      %-10s %-10s %-10s %s", "phase", "t_edge", "t_out",
             "t_out - t_edge");
    delta0 = -1; mismatch = 0;
    for (k = 0; k < 4; k = k + 1) begin
      phase = 20 + k * 30;            // cycles AFTER arming, all well inside
                                      // the 200-cycle timeout
      cyc = 0; t_edge = -1; t_out = -1; seen_out = 0; prev_uo0 = 1;
      load_and_run;
      wait_armed(400);
      if (armed_at < 0) begin
        $display("      *** the lane never ARMED within 400 cycles");
        errors = errors + 1;
      end
      run_cycles(phase);
      // THE PEER EDGE: drive the arm pin low (the program arms on a FALL)
      uio_drv[arm_pin] = 1'b0;
      t_edge = cyc;
      run_cycles(120);
      delta = (t_out < 0) ? -1 : (t_out - t_edge);
      $display("      %-10d %-10d %-10d %0d", phase, t_edge, t_out, delta);
      if (delta < 0) begin
        $display("      *** no output edge at all after the peer edge");
        mismatch = mismatch + 1;
      end else if (delta0 < 0) begin
        delta0 = delta;
      end else if (delta != delta0) begin
        mismatch = mismatch + 1;
      end
    end
    if (mismatch != 0 || delta0 < 0) begin
      $display("      *** MUST-FIRE 1 FAILED: `t_out - t_edge` varies with the");
      $display("          phase (%0d mismatches). The lane's grid is anchored to", mismatch);
      $display("          the ARM's DEADLINE, not to the peer's edge. For UART-rx");
      $display("          that misses every bit -- 0.9b derives the sample grid");
      $display("          as edge + half + m*T.");
      errors = errors + 1;
    end else begin
      $display("      MUST-FIRE 1 PASS -- constant at %0d cycles across 4 phases.",
               delta0);
      $display("      ⭐ The offset is the sync latency plus dispatch, a KNOWN");
      $display("      CONSTANT, which is what makes it absorbable into D_tol.");
    end

    // =================================================================
    // MUST-FIRE 2 -- NO EDGE, NO RELEASE (timeout = 0, wait forever)
    // =================================================================
    $display("");
    $display("  --- 2 NO EDGE: no release, and no invented data ---");
    $readmemh("test/edge_image_noto.hex", img);
    img_bytes = 0;
    for (i = 0; i < IMG_MAX; i = i + 1)
      if (^img[i] !== 1'bx) img_bytes = i + 1;
    cyc = 0; t_edge = -1; t_out = -1; seen_out = 0; prev_uo0 = 1;
    load_and_run;
    t_edge = 0;                       // count output changes from the start
    run_cycles(600);                  // peer stays HIGH: no falling edge
    $display("      output edges after 600 cycles with NO peer edge: %0d",
             seen_out);
    if (seen_out != 0) begin
      $display("      *** MUST-FIRE 2 FAILED: the lane moved its pin without");
      $display("          ever being released. A reactive lane that fires on");
      $display("          nothing is a chip reporting data it never received.");
      errors = errors + 1;
    end else begin
      $display("      MUST-FIRE 2 PASS -- armed with timeout=0, stayed put.");
    end

    // =================================================================
    // MUST-FIRE 3 -- TIMEOUT halts the lane and is STICKY
    // =================================================================
    $display("");
    $display("  --- 3 TIMEOUT: silence halts the lane, flag sticky, 0 actions ---");
    $readmemh("test/edge_image.hex", img);   // timeout = 200
    img_bytes = 0;
    for (i = 0; i < IMG_MAX; i = i + 1)
      if (^img[i] !== 1'bx) img_bytes = i + 1;
    cyc = 0; t_edge = 0; t_out = -1; seen_out = 0; prev_uo0 = 1;
    load_and_run;
    run_cycles(700);                  // peer silent, well past the 200 timeout
    to_lane_live = dut.u_eng.l_live[0];
    to_flag      = dut.u_eng.l_timeout[0];
    acts_after   = seen_out;
    $display("      lane 0 live after the timeout : %0d (want 0)", to_lane_live);
    $display("      sticky TIMEOUT flag           : %0d (want 1)", to_flag);
    $display("      output edges after timeout    : %0d (want 0)", acts_after);
    if (to_lane_live !== 0 || to_flag !== 1 || acts_after != 0) begin
      $display("      *** MUST-FIRE 3 FAILED. A timeout that lets the lane");
      $display("          PROCEED is indistinguishable from the peer having");
      $display("          answered, so the program would read a frame out of an");
      $display("          idle line. Forbidden direction, one level up.");
      errors = errors + 1;
    end else begin
      $display("      MUST-FIRE 3 PASS -- halted, flagged, silent.");
    end

    // =================================================================
    // MUST-FIRE 4 -- I2C STRETCH: held low delays the high phase
    // =================================================================
    // ⭐ Arms on a RISE this time (the I2C case: the controller waits for SCL
    // to actually go high). Holding the line low past the nominal release must
    // push the following action out by exactly the stretch.
    $display("");
    $display("  --- 4 STRETCH: a held-low SCL delays the high phase ---");
    $readmemh("test/edge_image_rise.hex", img);
    img_bytes = 0;
    for (i = 0; i < IMG_MAX; i = i + 1)
      if (^img[i] !== 1'bx) img_bytes = i + 1;
    $display("      %-12s %-10s %-10s %s", "stretch", "t_rise", "t_out",
             "t_out - t_rise");
    delta0 = -1; mismatch = 0;
    for (k = 0; k < 3; k = k + 1) begin
      phase = 30 + k * 40;            // how long the peer holds SCL LOW
                                      // AFTER the lane has armed
      cyc = 0; t_edge = -1; t_out = -1; seen_out = 0; prev_uo0 = 1;
      load_and_run;
      uio_drv[arm_pin] = 1'b0;        // peer holds SCL LOW from the start
      wait_armed(400);
      if (armed_at < 0) begin
        $display("      *** the lane never ARMED within 400 cycles");
        errors = errors + 1;
      end
      run_cycles(phase);              // keep stretching
      uio_drv[arm_pin] = 1'b1;        // peer finally releases -> RISE
      t_edge = cyc;
      run_cycles(120);
      delta = (t_out < 0) ? -1 : (t_out - t_edge);
      $display("      %-12d %-10d %-10d %0d", phase, t_edge, t_out, delta);
      if (delta < 0) mismatch = mismatch + 1;
      else if (delta0 < 0) delta0 = delta;
      else if (delta != delta0) mismatch = mismatch + 1;
    end
    if (mismatch != 0 || delta0 < 0) begin
      $display("      *** MUST-FIRE 4 FAILED: the action after the arm is not");
      $display("          timed from the OBSERVED rise, so clock stretching is");
      $display("          ignored. N1a's `tr` argument and A2-P4's stretch");
      $display("          argument both rest on this.");
      errors = errors + 1;
    end else begin
      $display("      MUST-FIRE 4 PASS -- constant at %0d cycles for stretches",
               delta0);
      $display("      of 30/70/110 cycles after arming, so the high phase");
      $display("      follows the LINE");
      $display("      and not the controller's count. ⭐ That is what takes `tr`");
      $display("      out of the controller's budget (N1a) and makes unbounded");
      $display("      stretching a LATENCY question rather than a C_i one.");
    end

    $display("");
    if (errors == 0) $display("  tb_edge: PASS (4 of 4 must-fires)");
    else             $display("  tb_edge: %0d FAILURE(S)", errors);
    $finish;
  end

  tt_um_protocol_emulator dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );

endmodule

`default_nettype wire
