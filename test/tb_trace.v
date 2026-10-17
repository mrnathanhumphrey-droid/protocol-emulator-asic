/* tb_trace.v -- emit a per-cycle PORT trace, for cross-simulator comparison.
 *
 * THE ONE CLAIM: two independent simulators, given the same RTL and the same
 * stimulus, produce byte-identical traces -- and a disagreement is a real tool
 * or netlist problem rather than a modelling one, because both sides are the
 * same design.
 *
 * ⭐⭐ PORTS ONLY, AND THAT IS A HARD CONSTRAINT RATHER THAN A PREFERENCE. The
 * same bench has to run against the GATE-LEVEL NETLIST, which has no internal
 * signal names at all -- `dut.u_eng.l_armed` does not exist after synthesis.
 * Every other bench in this project reaches inside (tb_smoke reads
 * `jitter_max`, tb_edge reads `l_armed`), which is right for what they measure
 * and makes them RTL-only. This one trades that away deliberately so one
 * artefact covers RTL, the 2-state engine and GL.
 * ⭐ THE PEERS DO NOT BREAK THAT. They attach to `uio`/`uo_out`, which survive
 * synthesis, so adding them kept the bench gate-level-ready.
 *
 * ⛔ AND IT IS WHY THE COMPARISON NEEDS NO GOLDEN MODEL. Per Wilson's Q1, the
 * simulator-vs-simulator arm compares resolved driven pin values per cycle and
 * nothing else; the two engines are each other's witness. Bringing the golden
 * model in here would mean growing it into a cycle-accurate second
 * implementation of the pipeline, which Law 1 says is worth nothing.
 *
 * ⛔⛔ UNINITIALISED STATE IS THE FIRST THING THIS WOULD HAVE TRIPPED ON.
 * iverilog starts a flop at X; the 2-state engine at 0 or at a per-flop random
 * pattern. `model/gate_reset_audit.py` had to come first and name all 2,087
 * unreset flops before a disagreement here could mean anything -- and the seed
 * sweep (>= 3 seeds, traces identical) is the RUNTIME check behind that
 * allowlist's otherwise-only-stated write-before-read reasons.
 *
 * ⚠ X IS PRINTED AS A DISTINCT TOKEN, not folded to 0 or 1. iverilog can emit
 * X and the 2-state engine cannot, so a trace containing X will differ between
 * them BY CONSTRUCTION -- which is information, not noise: it means a port is
 * driven from something uninitialised, or two drivers are contending, and the
 * comparison is not yet meaningful.
 *
 * ⛔⛔⛔ `uio_in` IS IN THE TRACE, AND ITS ABSENCE IS WHY THE FIRST RESULT WAS
 * NARROW. The first cycle-exact pass compared `uo_out`, `uio_out` and `uio_oe`
 * only -- and under the ruled two-bank pin map FIVE of the eight `uio` bits are
 * peer-driven INPUTS (SPI-master MISO, UART-rx RX, SPI-target SCLK/MOSI/CS).
 * Every peer-driven edge and the whole edge-capture path was therefore
 * invisible to the comparison, not merely unexercised.
 */

`default_nettype none
`timescale 1ns / 1ps

`include "test/imgload.vh"
module tb_trace;

  // ⭐ RULING CI3: the SPI peer's MISO delay in system cycles (its tODV,
  // adjustable), so `test/run_spidelay.py` can find the chip's sample edge
  parameter integer SPI_MISO_DLY = 0;

  // ⛔ THE PIN MAP IS GENERATED, NOT RESTATED. test/corpus.py derives it from
  //    the two-bank ruling and checks it against project.v's MISO_PIN/CS_PIN;
  //    a hand-written copy here would be the second table that drifts, and a
  //    drifted pin map passes every check while watching the wrong wire.
`include "pinmap.vh"

  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00;
  wire [7:0] uo_out, uio_out, uio_oe;
  wire [7:0] uio_in;

  // ---- the bench-side drivers ------------------------------------------
  // ⛔⛔⛔ EVERY ONE OF THESE IS INITIALISED AT ITS DECLARATION, AND THE SEED
  // SWEEP IS WHAT FOUND OUT WHY. They were assigned in the main `initial`
  // block instead, which looks equivalent and is not: under
  // `+verilator+rand+reset+2` the bench's OWN regs are randomised at
  // construction, and `run_go` starting at 1 let the peer-master processes
  // fall straight through their `wait (run_go)` and begin driving before the
  // main block had cleared it. Three of the five corpus programs -- exactly
  // the three that use a bench master -- then disagreed across x-initial
  // seeds, by 1,492 to 2,888 body lines.
  // ⭐ A declaration initialiser is applied at elaboration, before any
  // `initial` block runs, so it is not something a later assignment races.
  // ⚠ AND THE FINDING WAS IN THE BENCH, NOT THE DUT. `gate_reset_audit.py`
  // allowlists the DESIGN's unreset flops; nothing audits the testbench, and
  // read-before-write there produces exactly the same seed-dependent trace.
  // The sweep does not care which side of the port list the defect is on.
  reg  [7:0] ld_val  = 8'h00;         // LOAD mode drives all 8 bits
  reg        ld_en   = 1'b0;
  reg  [7:0] mst_val = 8'hFF;         // the bench acting as a peer MASTER;
  reg  [7:0] mst_oe  = 8'h00;         //   idle high = CS deselected, RX idle
  reg        en_i2c  = 1'b0;
  reg        en_i2cs = 1'b0;   // the STRETCHING peer
  // ⛔⛔ A BENCH-DRIVEN SCL HOLD, AND IT EXISTS BECAUSE THE PEER-DRIVEN STRETCH
  // ARM CAME OUT VACUOUS. `fram_i2c` stretches per ACK, and it never ACKs: it
  // needs a START plus a matching device address, which no program can send yet
  // for exactly the reason `corpus_spim` is OPEN -- the payload arrives from the
  // HOST over the same `uio` bank, and the SHIFT/clock phase is unruled. With
  // the peer silent, the mutant arm produced no contention either and all four
  // measurements were identical: a must-fire that fires on nothing.
  // ⭐ The bench can pull SCL low unconditionally, which tests the ELECTRICAL
  // claim directly and needs no transaction: against a RELEASED SCL the hold
  // simply wins, and against a push-pull HIGH it is a short, which the resolved
  // bus shows as X.
  reg        hold_scl = 1'b0;
  integer    sclhold;
  // ⭐ STAYLOAD keeps the part in LOAD MODE for the trace window, so the
  // SERIAL READBACK STREAM is what gets compared -- D1's ruling asks for the
  // readback to sit under the seed sweep, because randomised init is exactly
  // what would have caught the stale first frame that `rb_addr` alone left.
  integer    stayload;
  reg        en_spi  = 1'b0;
  reg        en_tgt  = 1'b0;
  reg        en_rx   = 1'b0;

  wire i2c_scl_oe, i2c_sda_oe;        // PULL-LOW enables, never drive high
  wire i2cs_scl_oe, i2cs_sda_oe;      // the stretching peer's, same shape
  wire spi_so, spi_so_oe;

  // ⭐ ONE DRIVER PER BIT, STRUCTURALLY. Each `uio` bit below is assigned
  // exactly once, so a bench-side overlap is impossible by construction rather
  // than forbidden by an assertion that could itself be wrong. The ruled map
  // accounts for all eight bits with nothing left over.
  wire [7:0] peer_oe, peer_val;
  assign peer_oe [P_M_MISO] = en_spi & spi_so_oe;
  assign peer_val[P_M_MISO] = spi_so;
  assign peer_oe [P_SCL]    = (en_i2c  & i2c_scl_oe)
                            | (en_i2cs & i2cs_scl_oe)
                            | hold_scl;
  assign peer_val[P_SCL]    = 1'b0;             // open-drain: pull low or let go
  assign peer_oe [P_SDA]    = (en_i2c  & i2c_sda_oe)
                            | (en_i2cs & i2cs_sda_oe);
  assign peer_val[P_SDA]    = 1'b0;
  assign peer_oe [P_RX]     = en_rx  & mst_oe[P_RX];
  assign peer_val[P_RX]     = mst_val[P_RX];
  assign peer_oe [P_T_SCLK] = en_tgt & mst_oe[P_T_SCLK];
  assign peer_val[P_T_SCLK] = mst_val[P_T_SCLK];
  assign peer_oe [P_T_MOSI] = en_tgt & mst_oe[P_T_MOSI];
  assign peer_val[P_T_MOSI] = mst_val[P_T_MOSI];
  assign peer_oe [P_T_CS]   = en_tgt & mst_oe[P_T_CS];
  assign peer_val[P_T_CS]   = mst_val[P_T_CS];
  assign peer_oe [P_T_MISO] = 1'b0;             // the DUT owns it: tri-state out
  assign peer_val[P_T_MISO] = 1'b0;

  wire [7:0] tb_oe  = ld_en ? 8'hFF  : peer_oe;
  wire [7:0] tb_val = ld_en ? ld_val : peer_val;

  // ⭐ THE RESOLUTION NOW LIVES ONCE, in test/od_bus.vh. This block used to
  // carry its own copy, and its comment said "same semantics as tb_edge" --
  // a copy admitting it was a copy.
  wire [7:0] ob_oe  = tb_oe;
  wire [7:0] ob_val = tb_val;
`include "test/od_bus.vh"

  always #10 clk = ~clk;

  localparam integer IMG_MAX = 256;
  localparam integer PIN_PROG = 7, PIN_PTR = 5, PIN_WR = 6;

  reg [7:0]  img [0:IMG_MAX-1];
  integer    img_bytes, i, jt, jr, cyc, fd, ncyc, seed, async_arm;
  // ⛔⛔⛔ 256 BYTES, NOT 64, AND THAT WAS A FIVE-COMMIT CI FAILURE. A Verilog
  // string reg SILENTLY TRUNCATES a longer `$value$plusargs("%s")` value, and
  // `test/phases_run.sh` passes ABSOLUTE paths. On this box
  // `/mnt/d/ProtocolEmulator/probe_phases/trace_clean.txt` is 59 bytes and
  // fitted; in CI the checkout is
  // `/home/runner/work/protocol-emulator-asic/protocol-emulator-asic/...`, so
  // `+OUT` is 99 bytes and `+IMG` 83. Both truncated, `$fopen` returned 0, and
  // every arm reported "no trace" -- while the simulation printed a clean
  // `$finish` and exit 0.
  // ⇒ `gate_um10204` CANNOT-RUN on every push from `6abb6dd` to `80ff8d7`,
  //   five commits, at 19 of 20, while the same tree measured 20 of 20 locally.
  //   The gate was right: it reds rather than skipping. The LOCAL green was
  //   real and the difference was the length of the checkout path.
  // ⚠ PRICED, NOT ARGUED: the same binary writes 2,001 lines to a 39-byte path
  // and nothing to a 107-byte one.
  // ⭐ EVERY OTHER BENCH NOW DOES THE SAME (ruling CI3). They had kept 64-byte
  // buffers, safe only because `benchset` passes them RELATIVE paths -- the
  // latent form of this defect. All take 256 bytes and `test/imgload.vh`'s
  // macro fails loudly on an image that did not load.
  reg [8*256-1:0] imgfile, outfile, peersel;
  reg [127:0]     feedv;          // ruling SP1: +FEED, up to 16 bytes
  integer         feedn, fi;

  // ---- A PORTABLE PRNG, AND $random IS NOT ONE -------------------------
  // ⛔⛔ `$random`'s GENERATOR IS NOT THE SAME IN THE TWO SIMULATORS. Seeded
  // peer phases drawn from it would differ between them, so every trace would
  // disagree BY CONSTRUCTION and the disagreement would look like a design
  // fault in the edge-capture path. A 32-bit LCG written out in Verilog
  // arithmetic is identical in both, because truncating multiplication is
  // defined.
  // ⛔⛔⛔ ONE LCG STATE PER PROCESS, AND SHARING ONE WAS A CROSS-SIMULATOR
  // BUG. A portable generator is necessary and NOT sufficient: the two
  // peer-master processes both read-modify-write their state, and both run in
  // every configuration (the `en_*` masks gate their DRIVE, not their
  // execution), so a single shared `rnd` made the draw sequence depend on which
  // process the scheduler ran first. That ordering is not guaranteed identical
  // across simulators, and the two disagreed on 2,392 to 2,896 lines for every
  // program using a bench master, while the I2C program -- whose peer is driven
  // only by the DUT -- stayed cycle-exact. The same applied to the shared loop
  // index `j`.
  // ⭐ Seeded deterministically from the one phase seed, so the stimulus is
  // still reproducible from the provenance header alone.
  reg [31:0] rnd_t = 32'd1;           // the SPI-target master's own state
  reg [31:0] rnd_r = 32'd1;           // the UART-rx driver's own state
  function [31:0] lcg;
    input [31:0] s;
    begin
      lcg = s * 32'd1103515245 + 32'd12345;
    end
  endfunction
  function integer draw;                // 0 .. n-1, from the high bits
    input [31:0] s;
    input integer n;
    begin
      draw = (s >> 16) % n;
    end
  endfunction

  // ⛔ A SINGLE FORMATTING FUNCTION, so the two simulators cannot differ in
  // how they RENDER a value and have that look like a design disagreement.
  // `%b` on an 8-bit vector prints X as `x`, the distinct token the header
  // asks for.
  task emit;
    begin
      $fwrite(fd, "%0d %b %b %b %b\n", cyc, uo_out, uio_out, uio_oe, uio_in);
    end
  endtask

  // =====================================================================
  // THE PEERS. Always instantiated, connected by a RUNTIME enable.
  // =====================================================================
  // ⛔ Verilog cannot instantiate conditionally on a plusarg, so all peers are
  // elaborated and the `en_*` regs gate their drive onto the bus. That also
  // means every program in the corpus elaborates the SAME netlist, so a trace
  // difference between programs cannot be a different build.
  // ⛔⛔ AND UNTIL NOW BOTH PEERS WERE INSTANTIATED NOWHERE. They were
  // lint-clean in two simulators and connected to nothing, so "SPI master ->
  // SPI FRAM peer" had never once run against the DUT. A peer that compiles is
  // not a peer that is wired.
  // ⛔⛔ THE BUS SWITCH (HOST_INTERFACE, WF2): `uio` is the LOAD DATA PORT, so
  // a peer on those pins must be isolated during ANY load or it sees the image
  // as bus traffic. Both I2C peers were wired straight to `uio_in` through the
  // load, and passed only because the corpus image happens to put no START on
  // SCL/SDA. Now they see their own pull-ups (idle high) while `ld_en` is set
  // -- a bidirectional FET switch the host opens for the load.
  wire sw_scl = ld_en ? 1'b1 : uio_in[P_SCL];
  wire sw_sda = ld_en ? 1'b1 : uio_in[P_SDA];
  fram_i2c u_i2c (
      .clk(clk),
      .scl_in(sw_scl), .sda_in(sw_sda),
      .sda_oe(i2c_sda_oe), .scl_oe(i2c_scl_oe)
  );

  // ⭐ THE SAME PEER WITH CLOCK STRETCHING ENABLED, which is D2's second
  // must-fire. STRETCH is a module PARAMETER, so it cannot be switched at run
  // time -- hence a second instance, selected by `+PEER=i2cs`. Only one of the
  // two is ever enabled, so they never both drive.
  // ⛔ A STRETCH IS ONLY POSSIBLE AGAINST A RELEASED SCL. Before D2's fix the
  // engine drove SCL push-pull HIGH, so a peer pulling low met an active
  // driver: the resolved bus turns that into X, which is the simulator telling
  // you it is a SHORT rather than a stretch.
  fram_i2c #(.STRETCH(12)) u_i2cs (
      .clk(clk),
      .scl_in(sw_scl), .sda_in(sw_sda),
      .sda_oe(i2cs_sda_oe), .scl_oe(i2cs_scl_oe)
  );

  // ⭐ RULING CE2: `+SPI_SCK_INV=1` makes this peer a MODE 1 / MODE 2 device.
  // ⚠ SAME-HAND, AND LABELLED AS SUCH: it is the mode 0/3 model behind an SCK
  // inverter -- which is what a CPHA=1-vs-0 device IS, edge for edge -- so it
  // can only show the chip drives a self-consistent inverted clock. The
  // foreign judge of the MODE is sigrok's decoder, given that mode's
  // CPOL/CPHA (`run_spifram`).
  reg spi_sck_inv = 1'b0;
  integer spi_inv_arg;
  fram_spi #(.MISO_DLY(SPI_MISO_DLY)) u_spi (
      .clk (clk),
      .cs_n(uo_out[P_M_CS_UO]),
      .sck (uo_out[P_M_SCLK_UO] ^ spi_sck_inv),
      .si  (uo_out[P_M_MOSI_UO]),
      .so  (spi_so), .so_oe(spi_so_oe)
  );

  // =====================================================================
  // THE BENCH AS A PEER MASTER -- SPI-target's SCK/CS/MOSI, and UART-rx's RX
  // =====================================================================
  // ⛔ SEE THE DRIVER BLOCK ABOVE: `run_go` must be 0 from elaboration, or the
  //    two peer-master processes race their own start condition.
  reg run_go = 1'b0;

  // ⛔⛔ EVERY STIMULUS WRITE BELOW IS NON-BLOCKING, because the trace sampler
  // (`emit`, in the main loop) wakes on `@(negedge clk)` -- the SAME event these
  // master processes apply their stimulus on. With blocking writes, two
  // processes woken by one edge run in an order the language leaves UNDEFINED,
  // so whether a sample shows the old or the new value is the simulator's
  // choice. Non-blocking writes land in the NBA region, after every
  // active-region read at that edge, in every simulator. The DUT samples these
  // pins at the following POSEDGE, so what the design sees is unchanged --
  // measured: the same 26 coverage points, every measurement gate unchanged.
  // ⚠⚠ RECORDED AS A WRONG DIAGNOSIS, NOT A FIX. This change was made because
  // the async-clear arm disagreed in CI on 666 lines of `uio_in[6]` (CS), and
  // the race above looked like the cause. CI DISPROVED IT: the same 666 lines
  // disagreed after the change. The real cause was that `verilator_trace.sh`
  // called a bare `verilator`, which in CI is apt's 5.020 rather than the
  // pinned 5.053 (`PE_VERILATOR`). The change is kept because the race is real
  // and removing an undefined order is right on its own terms -- but it fixed
  // nothing that was observed.
  // SPI-target: clock bytes into the DUT at a seeded phase. ⭐ This is the only
  // way the SPI-target lane sees anything: under the ruled map its SCLK, MOSI
  // and CS are all INPUTS, so with no master driving them the lane is inert and
  // `uio_oe[MISO]` never moves -- which would make the async-clear arm vacuous.
  initial begin
    wait (run_go);
    forever begin
      repeat (draw(rnd_t, 7) + 3) @(negedge clk);
      rnd_t = lcg(rnd_t);
      mst_val[P_T_CS] <= 1'b0;                   // select, active low
      @(negedge clk);
      for (jt = 0; jt < 8; jt = jt + 1) begin
        mst_val[P_T_MOSI] <= rnd_t[jt];
        mst_val[P_T_SCLK] <= 1'b1;
        @(negedge clk);
        mst_val[P_T_SCLK] <= 1'b0;
        @(negedge clk);
      end
      // ---- CS DEASSERT: the ASYNC-CLEAR ARM ----------------------------
      // ⛔⛔ WITH `async_arm`, CS RISES MID-CYCLE, OFF BOTH CLOCK EDGES, AND
      //    THAT IS THE POINT. `uio_oe[MISO]` comes from `miso_oe_q`, a flop on
      //    `always @(posedge clk or posedge cs_deasserted or negedge rst_n)`.
      //    A triple-edge async-clear flop is the construct where two
      //    simulators most plausibly diverge, and clocking CS on an edge like
      //    everything else would HIDE it: the clear would coincide with the
      //    synchronous path, and agreement would say nothing about the
      //    asynchronous one.
      // ⭐ The offset is drawn in 1..9 ns, strictly BETWEEN the negedge and the
      //    following posedge, so it can never land ON an edge -- a randomised
      //    phase that is still guaranteed off-edge.
      @(negedge clk);
      if (async_arm) begin
        #(draw(rnd_t, 9) + 1);
        mst_val[P_T_CS] <= 1'b1;
        rnd_t = lcg(rnd_t);
      end else begin
        mst_val[P_T_CS] <= 1'b1;
      end
    end
  end

  // UART-rx: a start bit then 8 data bits, at a seeded phase, so the ARM and
  // edge-capture path is driven across its timing range rather than at one
  // fixed offset.
  initial begin
    wait (run_go);
    forever begin
      repeat (draw(rnd_r, 23) + 5) @(negedge clk);
      rnd_r = lcg(rnd_r);
      mst_val[P_RX] <= 1'b0;                     // the START bit: a FALL
      repeat (4) @(negedge clk);
      for (jr = 0; jr < 8; jr = jr + 1) begin
        mst_val[P_RX] <= rnd_r[jr];
        repeat (4) @(negedge clk);
      end
      mst_val[P_RX] <= 1'b1;                     // idle high
      repeat (4) @(negedge clk);
    end
  end

  // =====================================================================
  initial begin
    if (!$value$plusargs("IMG=%s", imgfile)) imgfile = "test/smoke_image.hex";
    if (!$value$plusargs("OUT=%s", outfile)) outfile = "trace.txt";
    if (!$value$plusargs("NCYC=%d", ncyc))   ncyc = 2000;
    if (!$value$plusargs("SEED=%d", seed))   seed = 1;
    if (!$value$plusargs("ASYNC=%d", async_arm)) async_arm = 0;
    if (!$value$plusargs("SCLHOLD=%d", sclhold)) sclhold = 0;
    if (!$value$plusargs("STAYLOAD=%d", stayload)) stayload = 0;
    if (!$value$plusargs("PEER=%s", peersel)) peersel = "none";
    if (!$value$plusargs("SPI_SCK_INV=%d", spi_inv_arg)) spi_inv_arg = 0;
    spi_sck_inv = (spi_inv_arg != 0);

    // ⛔⛔ THE LENGTH IS PASSED IN, NOT DERIVED FROM UNINITIALISED STATE, AND
    // THE REASON IS A BUG THIS BENCH ALREADY HAD. tb_smoke derives it by
    // scanning for the first X (`$readmemh` leaves unwritten entries X), which
    // is correct in iverilog and SILENTLY WRONG in the 2-state engine: that one
    // initialises the array to 0, so every one of the 256 entries looks written
    // and the derivation returned 256 instead of 51.
    // ⭐ The provenance header caught it -- added for the clobber hazard, it
    // reported `bytes=256` against iverilog's `bytes=51` before a single trace
    // line was compared. A cross-simulator bench cannot depend on
    // uninitialised-array semantics, which is the same X-vs-zero hazard the
    // reset audit exists for, inside the bench itself.
    if (!$value$plusargs("NBYTES=%d", img_bytes)) begin
      // ⛔ SEPARATE $display CALLS: there is no C-style adjacent string
      // concatenation in Verilog, and this project has made that mistake.
      $display("tb_trace: FATAL -- +NBYTES=<n> is required.");
      $display("  The image length must be passed explicitly; deriving it");
      $display("  from unwritten-array state is simulator-dependent.");
      $finish;
    end
    $readmemh(imgfile, img);
    `PE_REQUIRE_IMG_LOADED(imgfile)

    rnd_t   = seed;
    rnd_r   = seed ^ 32'h5f5f5f5f;
    ld_en   = 1'b0;
    ld_val  = 8'h00;
    mst_oe  = 8'h00;
    mst_val = 8'hFF;                    // idle high: CS deselected, RX idle
    run_go  = 1'b0;
    en_i2c  = 1'b0; en_spi = 1'b0; en_tgt = 1'b0; en_rx = 1'b0;

    // the peer wiring this program needs. ⛔ Selected by name rather than
    // "everything on", because a peer driving a pin the program never touches
    // is a second driver on a line nobody is watching.
    if (peersel == "i2c") en_i2c = 1'b1;
    if (peersel == "i2cs") en_i2cs = 1'b1;
    if (peersel == "spi") en_spi = 1'b1;
    if (peersel == "tgt") begin
      en_tgt = 1'b1;
      mst_oe = (8'b1 << P_T_SCLK) | (8'b1 << P_T_MOSI) | (8'b1 << P_T_CS);
    end
    if (peersel == "rx") begin
      en_rx  = 1'b1;
      mst_oe = (8'b1 << P_RX);
    end
    if (peersel == "all") begin
      en_i2c = 1'b1; en_spi = 1'b1; en_tgt = 1'b1; en_rx = 1'b1;
      mst_oe = (8'b1 << P_T_SCLK) | (8'b1 << P_T_MOSI)
             | (8'b1 << P_T_CS)   | (8'b1 << P_RX);
    end

    fd = $fopen(outfile, "w");
    // ⛔⛔ AN UNOPENED TRACE FILE IS FATAL AND NAMED. It was neither: `$fwrite`
    // to fd = 0 writes nothing, the run finished with a clean `$finish` and
    // exit 0, and the only symptom anywhere was `*** no trace` from the
    // launching script with no reason attached. Five CI runs said exactly that
    // and nothing more. A bench that cannot record its measurement must say so
    // itself rather than leave the caller to guess.
    if (fd == 0) begin
      $display("*** FAIL tb_trace: $fopen could not open the trace file.");
      $display("    OUT = %0s", outfile);
      $display("    The filename buffer is 256 bytes and a LONGER +OUT is");
      $display("    silently TRUNCATED, which is what this check caught in");
      $display("    CI; the other cause is a missing output directory.");
      $finish;
    end
    // ⭐ The header records what produced the trace. A trace file with no
    // provenance is the clobber hazard the C/J measurements already hit once,
    // and it has since caught a real mismatch: `bytes=256` vs `bytes=51`.
    // ⛔ PEER, SEED AND ASYNC ARE IN IT. Two runs of the same image with
    // different peers or a different seed are DIFFERENT EXPERIMENTS, and
    // comparing them would read as a design disagreement.
    $fwrite(fd, "# img=%0s bytes=%0d ncyc=%0d peer=%0s seed=%0d async=%0d stayload=%0d sclhold=%0d\n",
            imgfile, img_bytes, ncyc, peersel, seed, async_arm,
            stayload, sclhold);

    // ⛔⛔⛔ EVERY EDGE IN THIS BENCH IS A NEGEDGE, AND THAT IS WHAT MAKES THE
    //    TWO SIMULATORS COMPARABLE AT ALL. Driving stimulus in the SAME
    //    TIMESTEP as the posedge is a race: the DUT samples at that posedge,
    //    and whether it sees the old or the new value depends on the
    //    simulator's region ordering. The iverilog DUT saw the OLD value and
    //    the 2-state one saw the NEW one, so its program ran ONE CYCLE EARLY:
    //    `vl[n] == iv[n+1]` with EXACTLY 0 mismatches across all 1500 cycles
    //    once the shift was applied.
    // ⛔ AND NO COMMENT LINE HERE MAY BEGIN WITH THAT TOOL'S NAME: such a
    //    line is read as a LINT PRAGMA, case- and whitespace-insensitively,
    //    and then rejected as an unknown one. This paragraph broke the build
    //    THREE TIMES -- as the explanation, as the warning about the
    //    explanation, and as the quoted error text -- because each rewrite
    //    rewrapped the name onto the start of a line. A comment is not inert.
    //    The build failure is itself the standing guard, so no gate is owed.
    // ⚠ THE FIRST FIX WAS THE WRONG HALF. Seeing the offset, I moved only the
    //    SAMPLING off the edge; the traces stayed one cycle apart because the
    //    race was upstream in the stimulus. A pure shift with zero residual is
    //    the signature of a whole program displaced, not of a sampled value.
    // ⇒ The clock is driven off its own timer and the bench lives entirely on
    //   the negedge: inputs change half a period before the DUT samples them,
    //   and outputs are read half a period after it drove them. No bench event
    //   ever shares a timestep with the active edge.
    // ⚠ THE ONE DELIBERATE EXCEPTION IS THE ASYNC-CLEAR ARM, which must be
    //   off-edge to mean anything -- see the CS deassert above.
    cyc = 0;
    hf_init;
    repeat (4) @(negedge clk);
    rst_n = 1;
    @(negedge clk);

    // ---- LOAD ----------------------------------------------------------
    ui_in[PIN_PROG] = 1'b1;
    ld_en = 1'b1;
    repeat (3) @(negedge clk); ui_in[PIN_PTR] = 1'b1; repeat (3) @(negedge clk);  // CDC3: prog >= 3 cy before ptr; ptr >= 3 cy wide
    ui_in[PIN_PTR] = 1'b0; repeat (3) @(negedge clk);
    for (i = 0; i < img_bytes; i = i + 1) begin
      ld_val = img[i];
      @(negedge clk); @(negedge clk);
      ui_in[PIN_WR] = 1'b1;
      @(negedge clk); @(negedge clk); @(negedge clk);
      ui_in[PIN_WR] = 1'b0;
      @(negedge clk);
    end

    // ---- RUN, tracing every cycle --------------------------------------
    // ⛔ STAYLOAD TRACES THE READBACK INSTEAD OF THE ENGINE. In load mode the
    // protocol pins idle high and `uo_out[6:4]` carries the framed readback, so
    // the trace is the host-visible stream. The bus stays released either way.
    if (stayload == 0) ui_in[PIN_PROG] = 1'b0;
    ld_en  = 1'b0;                  // release the bus; engine and peers own it
    run_go = (stayload == 0);       // the peer masters start
    // FEED THE HOST QUEUES (ruling 0). Corpus programs draw from queue 0, but
    // every queue is fed because this bench runs whatever image it is given
    // and an unused queue simply stays full.
    // NOT IN `stayload` MODE: PROG stays HIGH there to trace the readback
    // stream, and `ui_in[5]` is PIN_PTR in load mode -- a push would be a
    // POINTER RESET, which would corrupt the very stream being traced.
    // ⛔⛔ NON-PALINDROMIC VECTORS (ruling 1b). This pattern was
    // {5A, C3, 3C, A5} -- FOUR BIT-REVERSAL PALINDROMES out of four, so it
    // passed under EITHER bit order and tested nothing about order at all.
    // That is how the engine's LSB-first wire order went unnoticed while
    // `pe_isa.py` documented the opposite: the only byte ever checked end to
    // end read the same both ways.
    // 0x5B/0x01/0x7A/0xC7 reverse to DA/80/5E/E3 -- all different, and 0x01
    // is the asymmetric extreme the ruling asks for.
    // ⛔ NO QUEUE-ATTRIBUTION CLAIM (Wilson). Every queue carries the SAME
    // pattern, so a lane sending another queue's byte cannot be seen here --
    // this bench's job is scheduling and trace coverage, and its feed is
    // pinned (the TR traces the Lean replay and LN1 are pinned to), so it is
    // NOT re-patterned. Attribution is held where the per-queue data is
    // DISTINCT: S_QUEUE_SWAP is killed by tb_tx (run_mutants) and by V2
    // pins-only on run_cktx's two-queue `fed` arm.
    hf_set(0, 8'h5B, 8'h01, 8'h7A, 8'hC7);
    hf_set(1, 8'h5B, 8'h01, 8'h7A, 8'hC7);
    hf_set(2, 8'h5B, 8'h01, 8'h7A, 8'hC7);
    hf_set(3, 8'h5B, 8'h01, 8'h7A, 8'hC7);
    // ⭐ RULING SP1: `+FEED=<hex>` with `+FEEDN=<n>` (n <= 16) puts an
    // image's own byte sequence on queue 0, most significant byte first -- a
    // real transaction's opcodes and addresses, which the default pattern can
    // never spell (`corpus.FEEDS`). `+FEEDN=0` keeps the default.
    if (!$value$plusargs("FEEDN=%d", feedn)) feedn = 0;
    // ⛔ AT MOST `feedv`'s 16 BYTES, AND A LONGER FEED USED TO RUN SILENTLY:
    // the hex parse truncates to `feedv` and `hf_put` drops entries past
    // host_feed's HF_PAT, so the lane sent 00 in their place with no FAIL
    // line (a 30-byte probe feed: 14 bytes went out as 00). Must-fire:
    // `run_mutants.py`, +FEEDN=17 red and +FEEDN=16 clean.
    if (feedn > $bits(feedv) / 8) begin
      $display("tb_trace: FATAL -- +FEEDN=%0d exceeds the %0d-byte feed", feedn, $bits(feedv) / 8);
      $finish;
    end
    if (feedn > 0) begin
      if (!$value$plusargs("FEED=%h", feedv)) begin
        $display("tb_trace: FATAL -- +FEEDN=%0d without +FEED", feedn);
        $finish;
      end
      hf_n(0, feedn);
      for (fi = 0; fi < feedn; fi = fi + 1)
        hf_put(0, fi, feedv[(feedn - 1 - fi) * 8 +: 8]);
    end
    if (stayload == 0) hf_en = 1'b1;
    for (i = 0; i < ncyc; i = i + 1) begin
      @(negedge clk);
      cyc = cyc + 1;
      // ⭐ the hold window: a peer holding SCL LOW, which is what an I2C
      // stretch physically is. Outside it the bench leaves the line alone.
      if (sclhold != 0)
        hold_scl = (cyc > 100) && (cyc <= 100 + sclhold);
      emit;
    end

    $fclose(fd);
    $display("tb_trace: %0d cycles -> %0s", ncyc, outfile);
    $finish;
  end

  // ⭐⭐ THE BUFFER DEPTH IS A PARAMETER, AND THE SUITE RUNS BOTH VALUES.
  // Build the single-buffer configuration with
  //     iverilog -Ptb_trace.SPL_CFG=1 ...
  // ⛔⛔ WHY EVERY BENCH CARRIES THIS. Four benches kept a PRIVATE COPY of the
  // engine's slot index (`lane*2 + l_sel`), every copy silently assumed
  // SPL = 2, and every one of them broke the moment SPL = 1 existed -- one of
  // them after measuring and publishing a column. That is the generic
  // detector: a hidden constant in a bench fails as soon as the parameter it
  // assumes becomes variable. So the parameter point is swept rather than
  // trusted, by `test/run_param_points.py`.
  parameter integer SPL_CFG = 2;
  // ⭐ THE STRETCH PRESCALER, OVERRIDABLE FROM THE SWEEP. The shipped bound is
  // 35 ms (the SMBus bus-fault figure) = 107 ticks of 16384 cycles, which is
  // 1.75 MILLION cycles -- far too long to simulate. Shortening the prescaler
  // reaches the SAME halt in hundreds of cycles, so the fault path is
  // EXERCISED rather than reasoned about. ⛔ The bound itself (`CK_STRETCH_TO`)
  // is NOT touched: the arm tests the mechanism, not a different number.
  parameter integer CK_PRE = 16384;

  // ⛔ THE SDA DATA HOLD, overridable so the t_HD;DAT requirement is priced at
  // BOTH ends: 0 restores the measured defect, 40 runs past `t_VD;DAT` at Fm+.
  parameter integer SDA_HOLD_NS = 300;

  // THE HOST CHANNEL (Wilson's ruling 0). Every corpus program shifts, and
  // until now every one of those shifts found an empty queue and took the
  // UNDERRUN branch -- so the cycle-exact two-simulator agreement and the
  // cross-seed sweep were established on the STARVED path. Feeding them is
  // what makes those claims about the payload path they were read as covering.
  // The include is placed AFTER the dut because it references `dut.tx_cnt`.
  tt_um_protocol_emulator #(.SPL(SPL_CFG), .CK_STRETCH_PRE(CK_PRE),
                            .SDA_HOLD_NS(SDA_HOLD_NS)) dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );

`include "test/progress.vh"
`include "test/clocked_conform.vh"
`include "test/host_feed.vh"

// ⭐⭐ D4's POSITIVE POINT: a clocked open-drain delay ONE CYCLE ABOVE
// `SDA_HOLD` must RUN. D1's two refusing points run in `tb_pinrange`, where no
// bus model is needed because a refused program never dispatches -- but this
// one must get all the way through a byte, and an open-drain clocked lane
// PARKS ON AN OBSERVED RISE. `tb_pinrange` holds `uio_in` at a constant
// 8'hFF, so a released SCL reads high and never TRANSITIONS: `pin_rise` never
// fires, the lane parks until the stretch-fault bound halts it, and the arm
// would measure a hang. ⇒ It belongs here, in the bench that has `od_bus`.
// ⛔⛔ AND IT IS READ **HERE** RATHER THAN IN `clocked_conform.vh`, which is
// where the first version put it. That include is shared by THIRTEEN benches,
// and `test/benchset.py` requires every plusarg a bench reads to be supplied
// by one of that bench's own arms -- so a read in the include made twelve
// unrelated benches depend on an undeclared default, and the gate said so
// immediately. The verdict needs `cb_acts` from the include, so this block
// sits after it.
// ⛔ "IT RAN" IS ASSERTED ON RETIRED CLOCKED ACTIONS, never on an absent flag:
// `config_err == 0` is also true of an engine that never started, which is the
// vacuous pass this bench family has already reported once.
integer d4_runs;
initial if (!$value$plusargs("CKRUNS=%d", d4_runs)) d4_runs = 0;

final begin
  if (d4_runs != 0) begin
    if (dut.u_eng.config_err !== 1'b0)
      $display("*** FAIL tb_trace[D4]: config_err is SET on a program whose clocked delay is ABOVE SDA_HOLD -- the D1 refusal is too wide and rejects legal programs");
    else if (cb_acts == 0)
      $display("*** FAIL tb_trace[D4]: config_err is clear but NO clocked action retired, so 'it runs' is vacuous -- the lane never dispatched or is still parked");
    else
      $display("  tb_trace[D4]: ok -- %0d clocked action(s) retired with config_err clear at d = SDA_HOLD + 1", cb_acts);
  end
end

// ⛔ RULING M5 -- `+EXPECT_REFUSED=1` IS A LOAD THE CHIP MUST REFUSE (the
// sweep's `shortload` arm: 51 of 256 store bytes written). It declares the arm
// quiescent to `progress.vh`, which otherwise reds an arm with no writeback,
// and then asserts the refusal itself: the status CONFIG_ERR set, `store_full`
// clear, and ZERO writebacks. Quiescence alone would also be true of an engine
// that never started for some other reason.
integer m5_refused;
initial begin
  if (!$value$plusargs("EXPECT_REFUSED=%d", m5_refused)) m5_refused = 0;
  pg_quiescent_ok = (m5_refused != 0);
end

final begin
  if (m5_refused != 0) begin
    if (dut.cfg_err_any !== 1'b1 || dut.store_full !== 1'b0 || cm_wbs != 0)
      $display("*** FAIL tb_trace[M5]: a partial load was NOT refused -- CONFIG_ERR=%0b store_full=%0b writebacks=%0d", dut.cfg_err_any, dut.store_full, cm_wbs);
    else
      $display("  tb_trace[M5]: ok -- the partial load was refused: CONFIG_ERR set, 0 writebacks");
  end
end

endmodule

`default_nettype wire
