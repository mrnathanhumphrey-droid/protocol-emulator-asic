`default_nettype none
`timescale 1ns / 1ps

/* THE TWO HOST STATUS BITS, ACTUALLY SET (Wilson's ruling (a) item 1).
 *
 * ⛔⛔ WHY THIS BENCH EXISTS, AND IT IS A COVERAGE FINDING. `lane_underrun` and
 * `tx_full_sticky` are status bits the HOST READS, and the coverage sweep showed
 * that no test had ever SET EITHER OF THEM:
 *
 *     pe_engine.v:1627  `if (host_valid) ... else lane_underrun[cur] <= 1'b1;`
 *     project.v:412     `if (nib_lo && !do_push) tx_full_sticky <= 1'b1;`
 *
 * Both arms read as uncovered while every bench ASSERTED THEM CLEAR as a
 * precondition -- `tb_tx`'s verdict and `host_feed.vh`'s `hf_check` both do.
 * ⇒ Every run to date proved only that they do not fire SPURIOUSLY. Their set
 * paths, and therefore the status a host would act on, were unverified.
 *
 * ⚠ THE TWO CLAIMS NEED OPPOSITE SETUPS, which is why one bench carries two
 * modes rather than two benches sharing a program:
 *   +MODE=0  STARVE   -- run the engine with the feeder NEVER enabled, so a
 *                        SHIFT reaches its byte-load point with an empty queue
 *   +MODE=1  OVERRUN  -- stay in LOAD mode so the engine never pops, and push
 *                        past the 2-byte queue depth
 *
 * ⛔ AND EACH ASSERTS ATTRIBUTION, NOT JUST THAT SOMETHING SET. A blanket
 * `lane_underrun != 0` would pass if the flag set on a lane that never drew
 * from a queue, which is a different defect wearing the same flag.
 */
`include "test/imgload.vh"
module tb_status ();

  parameter integer SPL_CFG = 2;

  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00, uio_in = 8'h00;
  wire [7:0] uo_out, uio_out, uio_oe;
  integer    i, fails = 0, mode, img_bytes, ncyc, cyc;
  reg [8*256-1:0] imgfile;
`include "test/store_filler.vh"   // v2: PE_STORE_BYTES, never a typed 256
  reg  [7:0] img [0:PE_STORE_BYTES-1];

  localparam integer PIN_PROG = 7, PIN_PTR = 5, PIN_WR = 6;
  localparam integer N_LANES = 5;

  // ⭐ THE TX LANES OF `tx_image`, COPIED FROM ITS BUILDER, not recalled.
  // `make_smoke_image.py::build_tx` documents the program it emits:
  //     lane 0:  8 x SHIFT(pin=UO0, count=cnt, q=0), REARM(d0)   clk = UO2
  //     lane 1:  8 x SHIFT(pin=UO1, count=cnt, q=1), REARM(d1)   clk = UO3
  // ⚠ THE FIRST DRAFT SAID LANES 0 AND 2, from a half-remembered `pe_asm`
  // line about a different program, and the starve arm then reported lane 1's
  // perfectly correct underrun as a MIS-ATTRIBUTION and lane 2's absent one as
  // a missing flag -- two failures, both the bench's.
  localparam integer TXL_A = 0, TXL_B = 1;

  // ⛔ A PRIVATE COPY OF AN RTL CONSTANT, DECLARED AS ONE. `tx_mem` is indexed
  // `{q_sel, tx_rp[q_sel]}`, so queue q occupies `q*TXD .. q*TXD+TXD-1`, and
  // TXD = 2 in `project.v`. ⚠ `gate_bench_indices` guards `l_sel` slot
  // indices, not this, and the parameter sweep varies SPL -- NOTHING varies
  // TXD -- so this copy has no automatic guard. What it does have is a LOUD
  // failure mode: the arm asserts the two pushed bytes are AT these indices,
  // so a changed depth makes the test fail rather than silently pass.
  localparam integer TXD_MIRROR = 2;
  localparam integer Q2_BASE = 2 * TXD_MIRROR;

  always #5 clk = ~clk;

  tt_um_protocol_emulator #(.SPL(SPL_CFG)) dut (
      .ui_in(ui_in), .uo_out(uo_out), .uio_in(uio_in),
      .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );

`include "test/progress.vh"
`include "test/clocked_conform.vh"
`include "test/host_feed.vh"

  task fail;
    input [8*72-1:0] msg;
    begin
      $display("  *** FAIL: %0s", msg);
      fails = fails + 1;
    end
  endtask

  task load_image;
    begin
      // ⛔ on a FALLING edge, like the rest of this load (audit #3): the task
      // is entered right after a rising edge, where a blocking write races
      // the chip's input flops and the simulators order it differently
      @(negedge clk); ui_in[PIN_PROG] = 1'b1;
      repeat (3) @(negedge clk); ui_in[PIN_PTR] = 1'b1; repeat (3) @(negedge clk);  // CDC3: prog >= 3 cy before ptr; ptr >= 3 cy wide
      ui_in[PIN_PTR] = 1'b0; repeat (3) @(negedge clk);
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
      $display("tb_status: FATAL -- +IMG=<file> is required");
      $finish;
    end
    if (!$value$plusargs("NBYTES=%d", img_bytes)) begin
      $display("tb_status: FATAL -- +NBYTES=<n> is required. An image that");
      $display("  never loaded dispatches nothing, and 'no underrun' would");
      $display("  then read as a pass.");
      $finish;
    end
    if (!$value$plusargs("NCYC=%d", ncyc)) ncyc = 20000;
    if (!$value$plusargs("MODE=%d", mode)) mode = 0;
    // ⭐ MODE=1 (OVERRUN) pushes into a queue NO LANE DRAINS and asserts the
    // sticky sets; the engine is not expected to retire anything. MODE=0
    // (STARVE) runs the engine and IS checked, which is why this is per-arm.
    pg_quiescent_ok = (mode == 1);
    $readmemh(imgfile, img);
    `PE_REQUIRE_IMG_LOADED(imgfile)
    hf_init;

    $display("# status img=%0s bytes=%0d mode=%0d SPL=%0d",
             imgfile, img_bytes, mode, SPL_CFG);

    repeat (4) @(posedge clk);
    @(negedge clk); rst_n = 1;               // falling edge: audit #3
    @(posedge clk);
    load_image;

    if (mode == 0) begin
      // ================= STARVE =================
      // ⛔ THE FEEDER IS NEVER ENABLED. `hf_en` stays 0, so no byte is ever
      // pushed and every SHIFT that reaches its load point finds the queue
      // empty. ⚠ The program must actually RUN -- `img_bytes` is asserted
      // above because an image that never loaded would also push nothing.
      hf_en = 1'b0;
      for (cyc = 0; cyc < ncyc; cyc = cyc + 1) @(posedge clk);

      $display();
      $display("=========== tb_status: STARVE -- lane_underrun must SET ======");
      $display("  the feeder is never enabled, so a SHIFT reaching its");
      $display("  byte-load point finds an empty queue. The engine must set");
      $display("  the lane's sticky underrun flag and NOT stall.");
      $write("    lane_underrun            :");
      for (i = 0; i < N_LANES; i = i + 1)
        $write(" %0b", dut.u_eng.lane_underrun[i]);
      $display();
      $display("    host pushes issued       : %0d %0s", hf_pushes,
               (hf_pushes == 0) ? "ok -- starved by construction"
               : "*** FAIL -- something fed the queues");
      if (hf_pushes != 0)
        fail("the starve arm pushed bytes, so it is not a starve");
      $display("    engine host pops         : %0d %0s", hf_pops,
               (hf_pops == 0) ? "ok -- nothing was consumed"
               : "*** FAIL -- a byte was consumed from an empty queue");
      if (hf_pops != 0)
        fail("a pop happened with no push -- the queue reported data it lacked");

      // ⭐ ATTRIBUTION: the flag must set on the lanes that DRAW from a queue
      // and on no others.
      $display("    lane %0d (TX) underrun     : %0b %0s", TXL_A,
               dut.u_eng.lane_underrun[TXL_A],
               dut.u_eng.lane_underrun[TXL_A] ? "ok -- SET" : "*** FAIL");
      if (!dut.u_eng.lane_underrun[TXL_A])
        fail("the starved TX lane did not set its underrun flag");
      $display("    lane %0d (TX) underrun     : %0b %0s", TXL_B,
               dut.u_eng.lane_underrun[TXL_B],
               dut.u_eng.lane_underrun[TXL_B] ? "ok -- SET" : "*** FAIL");
      if (!dut.u_eng.lane_underrun[TXL_B])
        fail("the second starved TX lane did not set its underrun flag");
      for (i = 0; i < N_LANES; i = i + 1)
        if (i != TXL_A && i != TXL_B && dut.u_eng.lane_underrun[i]) begin
          $display("    lane %0d underrun          : 1 *** FAIL -- this lane", i);
          $display("        draws from no queue, so an underrun on it is a");
          $display("        MIS-ATTRIBUTION, not the flag working.");
          fail("underrun set on a lane that never draws from a queue");
        end
      // ⛔ AND IT MUST NOT HAVE STALLED. The flag exists so that C stays
      // bounded; a lane that stopped dispatching instead would make the whole
      // schedule unbounded, which is the clock-stretch conclusion again.
      $display("    lane %0d still live         : %0b %0s", TXL_A,
               dut.u_eng.l_live[TXL_A],
               dut.u_eng.l_live[TXL_A] ? "ok -- flagged, not halted"
               : "*** FAIL -- the lane stalled instead of flagging");
      if (!dut.u_eng.l_live[TXL_A])
        fail("the starved lane halted; underrun must flag, never stall");
      $display("    tx_full_sticky           : %0b %0s", dut.tx_full_sticky,
               dut.tx_full_sticky ? "*** FAIL -- nothing was pushed" : "ok");
      if (dut.tx_full_sticky)
        fail("tx_full_sticky set in a run that pushed nothing");

    end else begin
      // ================= OVERRUN =================
      // ⛔⛔ THE OVERRUN GOES INTO A QUEUE NO LANE DRAWS FROM, and the first
      // draft got this wrong in an instructive way. It held the chip in LOAD
      // mode so the engine could not pop -- but the host push strobe IS
      // `ui_in[6]`, which in LOAD mode is `PIN_WR`, the program-write strobe.
      // The pins are multiplexed by `PIN_PROG`, so those three "pushes" went
      // to the IMAGE LOADER: `tx_mem[0]` and `[1]` read `xx` and the queue was
      // never touched. ⇒ Host bytes can only be pushed while RUNNING.
      // ⭐ `tx_image` draws from queues 0 and 1 only (its builder says so), so
      // queue 2 fills and is never drained -- which is how `tb_tx`'s own
      // must-fire 4 avoids polluting the lanes' streams.
      hf_en = 1'b0;                    // the feeder stays off; these are ours
      hf_push_byte(8'h5B, 2'd2);       // queue 2, byte 1 -- fits
      hf_push_byte(8'h7A, 2'd2);       // queue 2, byte 2 -- fills it
      hf_push_byte(8'hC7, 2'd2);       // queue 2, byte 3 -- MUST OVERRUN
      repeat (8) @(posedge clk);

      $display();
      $display("========= tb_status: OVERRUN -- tx_full_sticky must SET ======");
      $display("  the TX queue is 2 bytes deep and QUEUE 2 IS DRAWN BY NO");
      $display("  LANE of this program, so it fills and is never drained. A");
      $display("  third byte has nowhere to go: the host has no back-pressure");
      $display("  pin, so the chip must REPORT it rather than stall.");
      // ⭐ THE QUEUE IS SHOWN TO BE FULL, not assumed. `tx_cnt[2]` at the
      // depth is what makes the third push an overrun rather than a push the
      // engine happened to have drained first.
      $display("    tx_cnt[2] (depth 2)      : %0d %0s", dut.tx_cnt[2],
               (dut.tx_cnt[2] == 2'd2) ? "ok -- FULL"
               : "*** FAIL -- the queue is not full, so nothing overran");
      if (dut.tx_cnt[2] !== 2'd2)
        fail("queue 2 was not full, so the third push was not an overrun");
      $display("    bytes pushed to queue 2  : %0d", hf_bytes);
      if (hf_bytes != 3)
        fail("the overrun arm did not push three bytes");
      $display("    tx_full_sticky           : %0b %0s", dut.tx_full_sticky,
               dut.tx_full_sticky ? "ok -- SET"
               : "*** FAIL -- the overrun was not reported");
      if (!dut.tx_full_sticky)
        fail("a push onto a full queue did not set tx_full_sticky");
      // ⭐ AND THE QUEUE'S EXISTING CONTENTS SURVIVE, which Wilson's ruling
      // asks for by name. A flag that sets while the stored bytes are
      // corrupted is a worse outcome than a silent drop: the host would read
      // "overrun" and the lane would then transmit the wrong data.
      $display("    queue 2 byte 0           : %02h %0s", dut.tx_mem[Q2_BASE],
               (dut.tx_mem[Q2_BASE] == 8'h5B) ? "ok -- intact" : "*** FAIL");
      if (dut.tx_mem[Q2_BASE] !== 8'h5B)
        fail("the overrun corrupted the first stored byte");
      $display("    queue 2 byte 1           : %02h %0s", dut.tx_mem[Q2_BASE+1],
               (dut.tx_mem[Q2_BASE+1] == 8'h7A) ? "ok -- intact" : "*** FAIL");
      if (dut.tx_mem[Q2_BASE+1] !== 8'h7A)
        fail("the overrun corrupted the second stored byte");
      // ⚠ `lane_underrun` IS REPORTED, NOT CLAIMED, in this arm. The run is
      // only long enough to push three bytes, so the lanes have not reached a
      // SHIFT load point yet and the flags read clear -- but that is an
      // artefact of the window, not a property worth asserting. MODE=0 owns
      // the underrun claim and gives the engine 20000 cycles to reach it.
      $write("    lane_underrun (expected) :");
      for (i = 0; i < N_LANES; i = i + 1)
        $write(" %0b", dut.u_eng.lane_underrun[i]);
      $display("   -- not a claim here; MODE=0 owns it");
    end

    $display();
    if (fails == 0)
      $display("  tb_status: PASS (%0s)", (mode == 0) ? "starve" : "overrun");
    else
      $display("  tb_status: *** FAILED %0d check(s)", fails);
    $finish;
  end

endmodule
`default_nettype wire
