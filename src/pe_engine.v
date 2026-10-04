/*
 * Copyright (c) 2026 Nathan Humphrey
 * SPDX-License-Identifier: Apache-2.0
 *
 * THE ENGINE -- non-preemptive EDF over N_LANES lanes, C = 2, J = 1, C9 = START.
 *
 * ⛔⛔ BUILT WITH NO REFERENCE TO ANY OTHER COMPETITION ENTRANT'S REPOSITORY OR
 * PULL-REQUEST CONTENT. The quarantine recorded in S2 covers the engine, not
 * only the PDN question.
 *
 * ⭐ NOT ONE PROTOCOL CONSTANT APPEARS IN THIS FILE, and that is checked by
 * `model/part1_param_contract.py` against a named list. Bit periods, deadlines
 * and phase splits all live in the LOADED IMAGE. A protocol constant in the
 * engine is the waveform-player failure in source form.
 *
 * =====================================================================
 * THE SCHEDULER
 * =====================================================================
 * A lane is READY when its stored next-action timestamp has arrived. The
 * comparison is WRAP-SAFE: `now - ts` is interpreted as a signed difference, so
 * it stays correct across the counter rolling over. ⛔ This is the form Ruling 2
 * demanded -- an ABSOLUTE counter with absolute per-lane timestamps, not
 * per-lane countdowns -- and 1.6b is the condition that makes it sound (the live
 * deadline spread plus max response time must stay under 2**(TS_W-1)).
 *
 * The EDF key is the ABSOLUTE DEADLINE `ts + D_sched`, and the winner is the
 * READY lane whose deadline is nearest. ⭐ Deadlines are compared as OFFSETS
 * FROM NOW (`key - now`) rather than as raw values, for the same wrap reason.
 *
 * ⛔ NON-PREEMPTIVE: once a job is dispatched it runs to completion. That is not
 * a simplification, it is the model A2 proved, and it is also what makes exactly
 * one atomic group sufficient (INV-ATOMIC-1).
 *
 * =====================================================================
 * ⛔⛔ THE FETCH PROBLEM, AND WHY PER-LANE PREFETCH REGISTERS EXIST
 * =====================================================================
 * An action word is 3 bytes and the store is BYTE-WIDE with a one-cycle
 * registered read. So fetching an action takes THREE reads -- and C = 2 cannot
 * contain three reads. The options were:
 *
 *   (a) widen the store to a 24-bit word. 2**AW words would be 3x the bits, and
 *       at the measured 4.04 cells per stored bit that is roughly 25,000 cells
 *       against a ~30,500 practical budget. Rejected on cost.
 *   (b) narrow the action to 2 bytes. opcode+pin+level+count is already 12 bits,
 *       leaving 4 for the delay, which cannot express a UART bit period.
 *       Rejected: it puts a protocol limit back in the encoding.
 *   (c) ⭐ PREFETCH. Keep the byte-wide store, and hold each lane's NEXT action
 *       in a register that a background FSM refills during idle cycles. The
 *       channel has the room: U = 0.21388, so most cycles are idle.
 *
 * (c) is implemented. ⭐ AND IT IS WHAT `M-PREFETCH-STALE` IS ACTUALLY ABOUT:
 * the prefetch register MUST be invalidated when the lane's program counter
 * advances, or a dispatched job replays the previous action. The named mutant is
 * removing that invalidation -- and it needs a MULTI-LANE program to be
 * non-vacuous, because with one live lane the previous winner IS the current
 * winner and the stale word is coincidentally correct.
 *
 * ⛔⛔ AND THIS IS A FIELD THE S2 FREEZE DID NOT HAVE. The freeze's table was
 * derived from the DESCRIPTOR documents, which describe lane STATE; the fetch
 * machinery that Ruling 1's C = 2 implies is not in any descriptor. Per lane
 * this adds a program counter (AW bits) and a prefetch word (ACT_W + 1 bits).
 * ⭐ THE GATE COULD NOT HAVE CAUGHT IT: traceability detects a FIELD WITH NO
 * RULING. It cannot detect a RULING WITH NO FIELD. That asymmetry is recorded
 * in the S3 results rather than quietly absorbed.
 */

`default_nettype none

module pe_engine #(
    parameter integer N_LANES = 5,
    parameter integer AW      = 8,
    parameter integer N_PINS  = 12,
    // ⭐ THE BANK BOUNDARY, PASSED IN. This module otherwise does not know the
    // banks -- see the reset comment -- and 1.6s is the one check that needs to:
    // an open-drain lane assigned a `uo_out` pin can never release, because that
    // bank has no enable. So the boundary is a parameter rather than knowledge
    // the engine helps itself to.
    parameter integer N_UIO    = 8,
    parameter integer TS_W    = 16,
    parameter integer DLY_W   = 10,
    parameter integer D_W     = 8
) (
    input  wire                 clk,
    input  wire                 rst_n,
    input  wire                 run,          // 1 = executing, 0 = load/halt

    // program store, shared with the loader
    output reg  [AW-1:0]        s_raddr,
    output reg                  s_re,
    input  wire [7:0]           s_rdata,
    // ⭐ the WIDE action fetch: one registered cycle for a whole action word
    output reg  [AW-1:0]        s_wraddr,
    output reg                  s_wre,
    input  wire [((3+((N_PINS<=2)?1:(N_PINS<=4)?2:(N_PINS<=8)?3:(N_PINS<=16)?4:5)+1+DLY_W+4+7)/8)*8-1:0] s_wrdata,

    // pin interface. ⭐ Both outputs are REGISTERED (ruling F2): every engine
    // driven bit comes from a flop, because a glitch on a clock pin is an extra
    // edge and an extra edge is a corruption, not a margin problem.
    output reg  [N_PINS-1:0]    pin_out,
    output reg  [N_PINS-1:0]    pin_oe,
    input  wire [N_PINS-1:0]    pin_in,       // already synchronised upstream
    // ⭐ EDGE DETECT, one bit per pin per polarity, combinational off the top
    // module's 3-stage sync chain. `OP_ARM` selects the polarity with the
    // action's existing level bit, because the three reactive releases do NOT
    // agree on one: UART-rx arms on the start bit's FALL, SPI-target on CS
    // FALL, I2C on the SCL RISE.
    input  wire [N_PINS-1:0]    pin_rise,
    input  wire [N_PINS-1:0]    pin_fall,

    // host data channel (F1): payload enters here, never through the program
    input  wire [7:0]           host_data,
    input  wire                 host_valid,
    // ⭐ host_pop: the engine tells the host channel it CONSUMED a byte.
    // ⛔⛔ F1 ruled ONE FIFO that "the engine routes as the program consumes"
    // and no FIFO was ever built: the byte had to be present in the exact cycle
    // a lane needed it or that lane recorded an underrun, which no real host can
    // meet. Popping on consumption is what lets a byte be staged ahead.
    output reg                  host_pop,
    // ⭐ host_lane: WHICH lane is consuming, so the host channel can serve that
    // lane's own queue. ⛔ A single shared queue with no routing is only correct
    // with ONE TX-consuming lane; with more, consumption order is the EDF
    // interleave -- timing-dependent -- so a host cannot order its pushes and
    // the wrong lane transmits the wrong byte SILENTLY.
    output wire [LW-1:0]        host_lane,
    // ⭐ WHICH QUEUE the consuming action names. The lane index is exported
    // only for diagnostics now; the ROUTING is by queue.
    output wire [1:0]           host_q,
    output reg  [N_LANES-1:0]   lane_underrun,
    output reg  [N_LANES-1:0]   lane_overflow,
    output reg                  sticky_ovr,
    output reg                  cfg_err,

    // RX payload out to the serialiser (which is NOT a lane -- zero budget)
    output reg  [7:0]           rx_data,
    output reg                  rx_push,

    output wire                 busy
);

  // ---- derived widths. ⛔ NO LITERAL WIDTHS ANYWHERE: a bare `[15:0]` would
  // also be the I2C D_tol constant, and the parameter contract rejects it.
  localparam integer PINW  = (N_PINS <= 2)  ? 1 :
                             (N_PINS <= 4)  ? 2 :
                             (N_PINS <= 8)  ? 3 :
                             (N_PINS <= 16) ? 4 : 5;
  localparam integer LW    = (N_LANES <= 2) ? 1 : (N_LANES <= 4) ? 2 :
                             (N_LANES <= 8) ? 3 : 4;
  localparam integer BPW   = 4;                      // bit pointer 0..8
  localparam integer CW    = 4;                      // C_i 1..8
  // ⭐⭐ BQW: THE TX QUEUE FIELD, AND IT COSTS NO IMAGE LAYOUT. The action word
  // was 22 bits inside 3 bytes, so the bottom 2 bits were ZERO PADDING that the
  // engine dropped. Widening ACT_W to 24 absorbs them as a queue index: the word
  // is still 3 bytes, ACT_BASE does not move, and because the padding was zeros
  // EVERY EXISTING IMAGE STAYS BIT-COMPATIBLE with queue 0.
  // ⛔ WHY HERE AND NOT IN THE HEADER, which is where the ruling put it: the
  // header is 47 bits inside 48, so it has ONE spare bit per lane, not two. A
  // 2-bit-per-lane field needs HDR_BYTES 6 -> 7, which moves ACT_BASE from 30 to
  // 35 and regenerates every image in the repo. Measured, not assumed.
  // ⭐ AND THE ACTION FIELD IS STRICTLY MORE GENERAL. The ruling's goal was that
  // the tag name a QUEUE rather than a lane, so any lane may transmit and the
  // program does the assigning. An action already names its lane and its pin;
  // naming its queue too is the same idea one level finer, and it drops the
  // baked lane->queue mapping entirely.
  localparam integer BQW   = 2;                      // TX queue index
  localparam integer ACT_W = 3 + PINW + 1 + DLY_W + BPW + BQW;

  // ---- opcodes. ⭐ Eight, which is exactly the 3-bit field: level, shift,
  // shift-in, read-bit, start, stop, arm, no-op re-arm.
  localparam [2:0] OP_LEVEL   = 3'd0;
  localparam [2:0] OP_SHIFT   = 3'd1;
  localparam [2:0] OP_SHIFTIN = 3'd2;
  localparam [2:0] OP_READBIT = 3'd3;
  localparam [2:0] OP_START   = 3'd4;
  localparam [2:0] OP_STOP    = 3'd5;
  localparam [2:0] OP_ARM     = 3'd6;
  localparam [2:0] OP_REARM   = 3'd7;

  // ---- image layout, all derived -------------------------------------
  // ⛔⛔ `base` IS A THIRD FIELD THE S2 FREEZE DID NOT HAVE. Without it every
  // lane's program counter initialises to the same ACT_BASE and ALL FIVE LANES
  // EXECUTE THE SAME ACTION STREAM. Like D_tol it is IMAGE metadata, read once
  // at header load into l_pc, so it costs image BYTES and zero extra flops.
  // ⭐ Same root cause as the PC and the prefetch word: the freeze's table came
  // from the DESCRIPTOR documents, which describe lane STATE, and said nothing
  // about the IMAGE's structure.
  // ⛔⛔ A FIFTH MISSING FIELD: the DRIVE MODE. The S2 freeze lists it as a
  // per-lane register and NOTHING IN THE IMAGE SET IT, so `l_mode` stayed at
  // its reset value of 0 = open-drain for every lane. On a `uo_out` pin that is
  // silently fatal: open-drain holds `pin_out` at 0 and modulates the ENABLE,
  // and `uo_out` HAS NO ENABLE -- so the pin went low on its first action and
  // stuck there forever while the scheduler ran perfectly.
  localparam integer HDR_BITS  = PINW + PINW + 1 + DLY_W + CW + D_W + D_W + AW;
  localparam integer HDR_BYTES = (HDR_BITS + 7) / 8;
  // ⭐⭐ SIZED COMPARISON CONSTANTS, so every comparison is width-matched.
  // ⛔ WHY, AND WHY NOT A LINT WAIVER. Verilator rejects the design on six
  // width warnings at five sites -- `hl == N_LANES-1`, `hb == HDR_BYTES-1`,
  // `pl == N_LANES-1` (x2) and the `s_raddr` assign below. NONE of them is a
  // bug today: the narrow side zero-extends and the truncation cannot
  // overflow at the shipped configuration. But `/* verilator lint_off WIDTH */`
  // would hide a REAL overflow if one ever appeared, and the `s_raddr`
  // truncation is exactly where one could -- see HDR_FITS_AW below.
  // ⭐ Widths stay PARAMETER-DERIVED. `part1_param_contract` forbids the
  // protocol constants (434, 414, 216, 213, 23, 18, 15, 80, 45, 125...) as
  // bare literals anywhere in the RTL, so a `[15:0]` would be rejected for
  // containing 15 -- the D_tol of I2C.
  localparam integer HBW      = 4;                       // width of `hb`
  localparam [HBW-1:0] HB_LAST = HDR_BYTES[HBW-1:0] - {{(HBW-1){1'b0}}, 1'b1};
  localparam [LW-1:0]  LANE_LAST = N_LANES[LW-1:0] - {{(LW-1){1'b0}}, 1'b1};

  // ⛔⛔ THE STATIC ASSERTION, AND IT IS THE REASON THE WIDTH FIX IS NOT
  // COSMETIC. `hl * HDR_BYTES + hb` addresses the header region and lands in
  // an AW-wide register. At the shipped configuration the maximum is
  // 4*6 + 5 = 29 against 2**8 = 256, so it fits -- and NOTHING CHECKED THAT.
  // The scaling sweeps move N_LANES and AW, and the truncation would wrap
  // silently exactly when someone swept upward. Same class as the wrap-safe
  // timestamp compare: an arithmetic edge invisible until the parameter hiding
  // it changes.
  //
  // ⛔⛔⛔ THE FIRST TWO IDIOMS I TRIED DO NOT FIRE, AND PRICING IS THE ONLY
  // REASON I KNOW THAT. Both of these ELABORATE CLEANLY in iverilog with the
  // condition false -- a static assertion that asserts nothing:
  //     localparam integer A = COND ? 0 : (1/0);     // divide by zero
  //     reg [ (COND ? 0 : -1) : 0 ] b;               // negative vector range
  // ⭐ Instantiating an UNDEFINED MODULE inside a `generate if` does fire, in
  // iverilog ("error: Unknown module type") and in Verilator, and the module
  // NAME carries the diagnostic. No $fatal (runtime, not elaboration), no SVA
  // (not plain Verilog), nothing synthesis has to ignore.
  localparam integer HDR_SPAN = N_LANES * HDR_BYTES + HDR_BYTES;
  generate
    if (HDR_SPAN >= (1 << AW)) begin : g_hdr_fits
      HEADER_REGION_DOES_NOT_FIT_IN_AW _static_assert ();
    end
  endgenerate

  function [AW-1:0] hdr_byte_addr(input [LW-1:0] ln, input [HBW-1:0] by);
    reg [AW-1:0] base;
    begin
      base          = ln * HDR_BYTES[AW-1:0];
      hdr_byte_addr = base + {{(AW-HBW){1'b0}}, by};
    end
  endfunction
  localparam integer ACT_BYTES = (ACT_W + 7) / 8;
  localparam integer ACT_BASE  = N_LANES * HDR_BYTES;

  // =====================================================================
  // PER-LANE STATE
  // =====================================================================
  reg [PINW-1:0]  l_pin    [0:N_LANES-1];   // data pin / armed pin
  reg [PINW-1:0]  l_clkpin [0:N_LANES-1];   // ⭐ a LANE property; the per-ACTION
                                            //   copy was cut by S2 as a duplicate
  reg             l_mode   [0:N_LANES-1];   // 0 = open-drain, 1 = push-pull

  // ⛔⛔⛔ RULING 1.5, THE DRIVE-MODE CONSTRUCTION -- AND IT HAD NEVER BEEN
  // BUILT. 1.5 ruled that the output be formed as `out[i] = data[i] &
  // pushpull[i]`, so "an open-drain pin drives a 1" is unsatisfiable BY
  // CONSTRUCTION whatever the opcode paths do. Nothing of the kind existed:
  // `uio_out` was `e_pin_out[7:0]` raw, and the only open-drain discipline was
  // an `if (l_mode[cur])` inside two opcode branches -- per LANE, where 1.5
  // specified per PIN. D2 is exactly the predicted consequence: a third branch
  // (the clock pin) was added later without the test, and drove a hard 1.
  // ⚠ THIS IS THE THIRD DAY-ONE COMMITMENT FOUND UNBUILT, after edge capture
  // and the no-op half-bit.
  //
  // ⭐ PER PIN, DERIVED FROM THE HEADERS AT LOAD. A pin's drive class follows
  // the lane that owns it, so `pin_pp` is set for a lane's `pin` AND `clkpin`
  // when its header lands -- before `hdr_done`, hence before any dispatch.
  // ⛔ NOT a build-time constant, though the ruled pin map would allow one:
  // `five_image` and `chain_image` legitimately drive `uio` pins PUSH-PULL
  // (`hdr(n, n, 1, ...)` on pins 0..4), so a compile-time mask of the ruled map
  // would freeze those synthetic refill-load programs dead. ⚠ That also means
  // those two images are NOT pin-map-legal: they need five push-pull pins and
  // the ruled map provides four. Reported rather than silently changed, because
  // their numbers feed published refill-contention results.
  //
  // ⭐ APPLIED AT THE FLOP'S D INPUT, which is what keeps F2 intact. ANDing
  // after the flop would put a gate on the pin and fail F2's structural check;
  // a separate output stage would add a cycle of latency to every protocol pin
  // and move measured timing. At the D input the pin stays a flop Q and the
  // mask costs nothing.
  reg [N_PINS-1:0] pin_pp;                  // 1 = this pin may drive a 1
  reg              config_err;              // sticky: 1.6s violation
  reg [7:0]       l_data   [0:N_LANES-1];   // THE PAYLOAD lives here, not in
                                            //   the program (ruling F1)
  reg [BPW-1:0]   l_bitp   [0:N_LANES-1];
  reg [TS_W-1:0]  l_timestamp     [0:N_LANES-1];   // ABSOLUTE next-action timestamp
  reg [CW-1:0]    l_c      [0:N_LANES-1];
  reg [D_W-1:0]   l_d      [0:N_LANES-1];   // D_sched -- the EDF key, in a
                                            //   REGISTER (Ruling 1)
  reg [DLY_W-1:0] l_t      [0:N_LANES-1];   // inner period
  reg             l_live   [0:N_LANES-1];
  // ---- the fetch machinery the freeze did not have --------------------
  reg [AW-1:0]    l_pc     [0:N_LANES-1];
  // ⛔⛔ A FOURTH FIELD THE FREEZE DID NOT HAVE: the lane's program BASE, kept
  // in silicon because a PERIODIC protocol has to REPEAT and nothing in the
  // encoding could express that. A lane's PC advanced linearly and fell off
  // the end of its program into whatever bytes followed. ⭐ Fixed by giving
  // OP_REARM a second meaning selected by the action's existing level bit:
  //    level = 0  extend the delay, PC unchanged   (Ruling 2's chaining)
  //    level = 1  extend the delay AND jump to base (loop)
  // so looping reuses an opcode and a field that already existed, and costs
  // only this register.
  reg [AW-1:0]    l_base   [0:N_LANES-1];

  // ---------------------------------------------------------------------
  // ⭐⭐ DOUBLE-BUFFERED ACTION FETCH. Two slots per lane, not one.
  // ---------------------------------------------------------------------
  // ⛔ WHY, IN ONE LINE: with a single slot, the slot is invalidated at
  // writeback and the lane's NEXT dispatch waits for a full refill -- that wait
  // IS the jitter term J, it measured 5, and the derived bound is 8. The
  // jitter-sound analysis then showed the design one cycle outside its own
  // margin bar at J = 8 under our bound (docs/SPEC_V4_J_SOUND.md), so reducing
  // J stopped being an optimisation.
  //
  // ⛔⛔ AND A SINGLE SHARED FETCH PORT CANNOT BE SCHEDULED OUT OF IT. That was
  // measured, not assumed: kicking a refill at writeback to overlap it with the
  // lane's own delay took J from 5 to 7, because a busy port makes a DIFFERENT
  // lane wait. The record is in the writeback block below. Two slots are the
  // structural answer; a better refill policy is not.
  //
  //   l_act[lane][slot]   the action words. `l_sel` picks the HEAD -- the one
  //                       that dispatches next. The other is the FILL slot.
  //   l_actv[lane][slot]  per-slot valid
  //   l_sel[lane]         which slot is the head. Flips at writeback, so the
  //                       already-fetched successor becomes head with NO refill
  //                       on the dispatch path.
  //   l_fpc[lane]         the FETCH pointer, which runs AHEAD of l_pc.
  //
  // INVARIANT (checked by the bench, see M-BUF-SWAP): the head slot always
  // holds the action at `l_pc`, and the fill slot -- when valid -- holds the
  // action at the address the head's own semantics select next.
  //
  // ⛔⛔⛔ THE PRE-REGISTERED DECOMPOSITION MISSED A TERM, AND IT IS RECORDED
  // RATHER THAN QUIETLY FIXED. `bursty.DOUBLE_BUFFER_PREREG` predicts J = 2 by
  // zeroing the two refill terms. It did not account for OP_REARM with
  // level = 1, which jumps `l_pc` to `l_base`: a plain double buffer has
  // already prefetched `l_pc + ACT_BYTES`, which after a loop is the WRONG
  // action, so both slots must flush and the next dispatch pays a FULL refill.
  // A periodic program loops once per iteration, so J would have landed near 7
  // and the falsifier would have fired -- on an incomplete decomposition, not
  // on the double buffer.
  // ⭐ THE REMEDY IS CHEAP BECAUSE THE LOOP TARGET IS ALREADY A REGISTER: the
  // prefetcher decodes the HEAD slot and, when it is a looping re-arm, fetches
  // `l_base` instead of `l_fpc`. See `fetch_addr` below. So the loop is
  // prefetched like any other control flow and never flushes anything.
  // ⛔ FLAT ARRAYS INDEXED `lane*2 + slot`, NOT `[0:N_LANES-1][0:1]`. A 2-D
  // UNPACKED array is legal Verilog-2001 and iverilog takes it happily -- and
  // that is exactly the trap this project already fell into once. The
  // multi-driver bug passed the local bench and died in Yosys, because a
  // simulator and a synthesiser do not accept the same language. A flat array
  // with explicit index arithmetic is accepted by both, so the construct is not
  // the thing being tested here.
  // ---------------------------------------------------------------------
  // ⭐⭐ ARM STATE -- the reactive release, and the timeout that bounds it
  // ---------------------------------------------------------------------
  // ⛔ `l_armed` IS THE EDGE LATCH, and arming IS the clear. An earlier sketch
  // carried a separate `l_edge_seen` bit; it is unnecessary and worse, because
  // the question "may this edge release the lane" is exactly "was the lane armed
  // when the edge arrived". Ruling 3 asks for `l_edge_seen` cleared at ARM
  // dispatch; making `l_armed` the latch gives that BY CONSTRUCTION -- an edge
  // arriving before ARM dispatches cannot be seen, because there is nothing
  // holding it. One bit fewer and one fewer way to get the clear wrong.
  //
  // ⛔⛔ RULING 2: A TIMEOUT MUST NEVER LOOK LIKE AN EDGE. If both simply made
  // the lane ready, a program could not tell them apart and a SILENT PEER would
  // make the lane carry on as though it had answered -- the forbidden direction
  // one level up from an unsound bound. So a timeout HALTS the lane and sets a
  // sticky flag; only an edge lets the program proceed.
  //
  // ⭐ AND THE TIMEOUT COSTS NO COMPARATOR. `ST_WB` already does
  // `l_timestamp += a_dly` and `ready` already tests `now - l_timestamp`, so an
  // ARM with a delay IS a deadline and the existing machinery enforces it. The
  // edge is an EARLY release against that deadline. That is Ruling 2's
  // stored-timestamp discipline paying for red-team 3's deadline-mode primitive.
  reg             l_armed  [0:N_LANES-1];   // armed, waiting on an edge
  reg [PINW-1:0]  l_armpin [0:N_LANES-1];   // which pin. ⛔ FULL WIDTH: it
                                            // cannot be narrowed to a choice of
                                            // {l_pin, l_clkpin}, because
                                            // SPI-target needs THREE pins --
                                            // MISO (data), SCK (clock) and CS
                                            // (arm) -- and narrowing it would
                                            // erode "pins are assigned per
                                            // program" for a 15-flop saving.
  reg             l_armedge[0:N_LANES-1];   // 1 = rise, 0 = fall
  reg             l_notmo  [0:N_LANES-1];   // "no timeout": wait indefinitely
  reg             l_timeout[0:N_LANES-1];   // STICKY: the peer went silent

  localparam integer NSLOT = 2 * N_LANES;
  reg [ACT_W-1:0] l_act    [0:NSLOT-1];
  reg             l_actv   [0:NSLOT-1];
  reg             l_sel    [0:N_LANES-1];   // 0/1: which slot is the HEAD
  reg [AW-1:0]    l_fpc    [0:N_LANES-1];   // the FETCH pointer, ahead of l_pc

  // =====================================================================
  // GLOBAL STATE -- one incrementer, not N_LANES decrementers (Ruling 2)
  // =====================================================================
  reg [TS_W-1:0] now;

  // ⭐ J IS MEASURED, NOT ASSERTED. `jitter_max` is the largest dispatch delay
  // caused purely by a prefetch miss, in cycles. A2 ships J = 1.
  localparam integer JW = 8;
  reg [JW-1:0] jitter_cnt, jitter_max;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)      now <= {TS_W{1'b0}};
    // ⭐⭐ `now` DOES NOT ADVANCE UNTIL PRIMED, and that is the half of
    // prime-before-release that actually removes the cold start. Gating only
    // DISPATCH would relocate the problem, not remove it: `now` would run on
    // through the priming refills, every lane's absolute timestamp would fall
    // behind, and the first job would be released ALREADY LATE -- the same
    // delay, now charged to the schedule instead of to start-up. Freezing the
    // clock makes the refill latency elapse before t = 0 of the schedule
    // exists, so no job's response time can contain it.
    // ⛔ M_NO_PRIME removes both halves and the bench must fail.
`ifdef M_NO_PRIME
    else if (run)    now <= now + 1'b1;
`else
    else if (run && primed) now <= now + 1'b1;
`endif
  end

  // =====================================================================
  // ⭐⭐ EDGE CAPTURE AND REBASE -- Ruling 1, the one that would break UART
  // =====================================================================
  // ⛔⛔ ON AN EDGE RELEASE THE LANE'S TIMESTAMP IS REBASED TO THE EDGE, NOT
  // LEFT AT THE ARM'S DEADLINE. `ST_WB` sets `l_timestamp += a_dly`
  // unconditionally, so after an EARLY (edge) release every following action
  // would be timed from the ARM's TIMEOUT instant -- an arbitrary moment with
  // no relation to the peer. For UART-rx that is fatal rather than imprecise:
  // 0.9b derives the sample grid as `edge + half + m*T`, anchored to the START
  // BIT, and a grid anchored to the deadline misses every bit.
  // ⇒ On capture: `l_timestamp := now`. The sync latency is then a KNOWN
  //   CONSTANT offset (2..3 cycles, derived in gate_edge_capture.py) which is
  //   already inside UART-rx's 213-cycle tolerance, and the first sample's
  //   programmed delay is measured from the edge like every later one.
  // ⭐ This also removes the need for a per-lane `l_edge_time` register: there
  //   is nothing to remember, because the rebase happens AT capture rather than
  //   at dispatch. 16 bits x 5 lanes = 80 flops not spent.
  //
  // ⛔ CAPTURE DISARMS. A second edge while the lane is waiting to be dispatched
  // must not re-rebase the timestamp -- that would slide the grid forward on
  // every subsequent peer transition, which on a clocked bus is every bit.
  wire [N_LANES-1:0] arm_hit;
  generate
    for (gi = 0; gi < N_LANES; gi = gi + 1) begin : g_arm
      assign arm_hit[gi] = l_armed[gi] &
                           (l_armedge[gi] ? pin_rise[l_armpin[gi]]
                                          : pin_fall[l_armpin[gi]]);
    end
  endgenerate

  // =====================================================================
  // READY + EDF SELECT. ⛔ Both comparisons are wrap-safe.
  // =====================================================================
  wire [N_LANES-1:0] ready;
  wire [TS_W-1:0]    edf_key_off [0:N_LANES-1];

  genvar gi;
  generate
    for (gi = 0; gi < N_LANES; gi = gi + 1) begin : g_ready
      // ⭐ signed difference: ready when the stored timestamp has ARRIVED.
      wire [TS_W-1:0] diff = now - l_timestamp[gi];
      // ⛔⛔ READINESS MUST NOT DEPEND ON THE PREFETCH. It used to read
      // `l_live & l_actv & ~diff[...]`, which conflated "I have this lane's
      // next action in a register" with "this lane's job has been RELEASED".
      // The effect was that at most ONE lane was ever ready, so the EDF
      // comparison never had two candidates and the schedule degenerated to
      // round-robin-by-prefetch-availability -- while every lane still moved
      // its pins, so the smoke test passed. ⭐ A2 assumes every RELEASED lane
      // competes; this is the line that makes that true.
      // ⛔⛔ AN ARMED LANE WITH "NO TIMEOUT" IS NOT READY ON ITS TIMESTAMP.
      // `l_notmo` is how a lane that must wait indefinitely (UART-rx idling
      // between frames) encodes it -- an ARM whose delay field is ZERO. Without
      // this term such a lane's stale timestamp is already in the past, so it
      // would be instantly "ready", instantly time out, and halt itself the
      // moment it armed.
      // ⭐ An ARMED lane with a timeout IS ready at its deadline, and that
      // readiness is exactly the timeout firing -- see ST_IDLE, where arriving
      // ready while still armed halts the lane instead of dispatching.
      assign ready[gi] = l_live[gi] & ~diff[TS_W-1]
                       & ~(l_armed[gi] & l_notmo[gi]);
      // ⭐ deadline as an OFFSET FROM NOW, so a wrapped key still orders
      //   correctly. 1.6b is what bounds the spread that makes this sound.
      assign edf_key_off[gi] = (l_timestamp[gi] + {{(TS_W-D_W){1'b0}}, l_d[gi]}) - now;
    end
  endgenerate

  // combinational min-offset over READY lanes. ⭐ Reads REGISTERED keys only,
  // which is Ruling 1's condition (i): without the key registers this mux would
  // sit after the store read and the pipeline register would land behind the mux
  // it was added to avoid.
  reg [LW-1:0]   winner;
  reg            winner_v;
  reg [TS_W-1:0] best;
  integer        k;
  always @* begin
    winner   = {LW{1'b0}};
    winner_v = 1'b0;
    best  = {TS_W{1'b1}};
    for (k = 0; k < N_LANES; k = k + 1) begin
      if (ready[k] && (!winner_v || edf_key_off[k] < best)) begin
        winner   = k[LW-1:0];
        winner_v = 1'b1;
        best  = edf_key_off[k];
      end
    end
  end

  // =====================================================================
  // THE DISPATCH PIPELINE -- C = 2, J = 1, C9 = START
  //   cycle 1 : DRIVE the pin (this is what C9 = START means)
  //   cycle 2 : write back lane state, advance the PC, invalidate prefetch
  // ⭐ The pipeline and C9 are ONE decision: an unpipelined engine reads its
  //   descriptor in cycle 1 and so CANNOT drive at START.
  // =====================================================================
  localparam [1:0] ST_IDLE = 2'd0, ST_DRIVE = 2'd1, ST_WB = 2'd2;
  reg [1:0]       st;
  reg [LW-1:0]    cur;
  assign host_lane = cur;
  assign host_q    = a_q;
  always @(*) cfg_err = config_err;
  reg [ACT_W-1:0] cur_act;

  assign busy = (st != ST_IDLE);

  // ---- action field slices -------------------------------------------
  wire [2:0]       a_op    = cur_act[ACT_W-1 -: 3];
  wire [PINW-1:0]  a_pin   = cur_act[ACT_W-4 -: PINW];
  wire             a_lvl   = cur_act[ACT_W-4-PINW];
  wire [DLY_W-1:0] a_dly   = cur_act[BQW+BPW +: DLY_W];
  wire [BPW-1:0]   a_cnt   = cur_act[BQW +: BPW];
  // ⭐ WHICH TX QUEUE THIS ACTION DRAWS FROM. Per-ACTION, so a lane's queue is
  // assigned by the PROGRAM and no lane number is baked into the hardware.
  wire [BQW-1:0]   a_q     = cur_act[0 +: BQW];

  // ⭐⭐ THE RESERVED NON-DRIVING PIN INDEX. PINW encodes 2**PINW codes and only
  // N_PINS are real, so `PIN_NONE` costs nothing: it is a value that already
  // existed and had no meaning.
  // ⛔ `pin_real` GUARDS ON THE WHOLE OUT-OF-RANGE SET, not just on PIN_NONE,
  // and that is deliberate: an index of 12..14 would otherwise write
  // `pin_out[12]` on a 12-wide vector, which is an out-of-range write whose
  // behaviour differs between simulators and synthesis -- exactly the class of
  // thing that passed iverilog and died in Yosys once already. Treating every
  // out-of-range code as non-driving is the safe reading; 1.6w REJECTS the
  // unreserved ones at load, so a typo'd pin index is a loader error rather
  // than a silent no-op.
  localparam [PINW-1:0] PIN_NONE = {PINW{1'b1}};
`ifdef M_NOOP_DRIVES
  wire pin_real = 1'b1;           // the mutant: a no-op DRIVES its pin
`else
  wire pin_real = (a_pin < N_PINS[PINW-1:0]);
`endif

  // =====================================================================
  // HEADER LOAD -- on entering run, pull N_LANES headers out of the image.
  // ⛔ D_tol is in the image and is NOT loaded into any register (ruling F3):
  //    the loader's screen reads it, the datapath never does. 40 flops unspent.
  // =====================================================================
  // ⛔⛔ FOUR STATES, NOT THREE, AND THE SMOKE BENCH IS WHAT FOUND IT. `s_re`
  // and `s_raddr` are REGISTERED by the arbiter, and the store read is itself
  // registered, so data requested while hst == H_REQ in cycle n is not valid
  // until cycle n+2. A three-state H_REQ -> H_WAIT -> sample sequence samples
  // the PREVIOUS byte. ⭐ Every header field then unpacks from shifted-in
  // garbage, no lane ever becomes live, and the engine sits idle while
  // elaborating perfectly cleanly.
  localparam [2:0] H_IDLE = 3'd0, H_REQ  = 3'd1, H_WAIT = 3'd2,
                   H_RD   = 3'd3, H_DONE = 3'd4;
  reg [2:0]            hst;
  reg [LW-1:0]         hl;
  reg [3:0]            hb;
  reg [HDR_BYTES*8-1:0] hsh;
  reg                  hdr_done;
  // ⛔⛔ UNPACK FROM THE POST-SHIFT VALUE. The last byte is shifted into `hsh`
  // with a NON-BLOCKING assignment in the same cycle the fields are unpacked,
  // so reading `hsh` there sees the value WITHOUT that byte and every field
  // comes out 8 bits adrift. The symptom was l_pc = 63 instead of 30 and a
  // timestamp of X, which made `ready` X and left the engine idle forever --
  // while elaborating perfectly cleanly.
  wire [HDR_BYTES*8-1:0] hsh_n = {hsh[HDR_BYTES*8-9:0], s_rdata};

  // =====================================================================
  // PREFETCH -- refill one lane's action register per visit, round robin.
  // =====================================================================
  // same one-cycle-too-early bug, same fix
  // ⭐ TWO STATES NOW, NOT FOUR. The wide port returns a whole action word in
  // one registered cycle, so the byte-shift register and its three-cycle walk
  // are gone -- and with them the 20-cycle jitter they caused.
  // ⛔ FOUR STATES: the arbiter REGISTERS s_wre/s_wraddr and the store read is
  // itself registered, so data requested in P_REQ is valid two cycles later.
  // Capturing in P_WAIT grabs the PREVIOUS fetch -- the same off-by-one as the
  // header FSM, in a second place, which is why it is called out twice.
  localparam [2:0] P_SCAN = 3'd0, P_REQ = 3'd1, P_WAIT = 3'd2, P_CAP = 3'd3;
  reg [2:0]             pst;
  reg [LW-1:0]          pl;
  reg                   pslot;        // which slot this refill is filling
  reg [AW-1:0]          paddr;        // and from which address -- both latched
                                      // at the scan, see the arbiter comment

  integer i;

  // =====================================================================
  // THE FETCH ADDRESS -- loop-aware, so a looping re-arm never flushes
  // =====================================================================
  // ⛔⛔ THE TERM THE PRE-REGISTRATION MISSED. Without this, a plain double
  // buffer prefetches `l_pc + ACT_BYTES` while the head action is a looping
  // re-arm whose successor is `l_base`. The prefetched word would be wrong, so
  // both slots would have to flush at the loop and the next dispatch would pay
  // a full refill -- once per program iteration, which for a 10-action UART
  // byte is 1 dispatch in 10 and would have put measured J near 7.
  //
  // ⭐ The loop target is ALREADY a per-lane register (`l_base`, added in S3
  // for Ruling 2), so the whole remedy is to decode the head slot's opcode and
  // pick the address the head's own semantics imply. No new storage.
  //
  // THREE CASES, which are exactly the three PC behaviours in the writeback:
  //   head is a looping re-arm  (OP_REARM, level 1) -> successor is l_base
  //   head is a chaining re-arm (OP_REARM, level 0) -> PC does NOT advance, so
  //                                the successor IS the head: nothing to fetch
  //   anything else                                 -> l_fpc, the running
  //                                successor pointer
  // ⛔ The `head valid` guard matters: with an INVALID head there is no opcode
  // to decode, and the slot being filled is the head itself, at `l_pc`.
  function [AW-1:0] fetch_addr(input [LW-1:0] ln);
    reg [ACT_W-1:0] hact;
    reg             hvalid;
    begin
      hvalid = l_actv[ln*2 + (l_sel[ln] ? 1 : 0)];
      hact   = l_act [ln*2 + (l_sel[ln] ? 1 : 0)];
      if (!hvalid)
        fetch_addr = l_pc[ln];                       // filling the head itself
      else if (hact[ACT_W-1 -: 3] == OP_REARM && hact[ACT_W-4-PINW])
        fetch_addr = l_base[ln];                     // the loop, prefetched
      else
        fetch_addr = l_fpc[ln];
    end
  endfunction


  // Is there anything worth fetching for this lane?
  // ⛔⛔ A CHAINING RE-ARM IS NOT PREFETCHED PAST -- AND THE REASON IS CHEAPER
  // THAN THE ONE THIS COMMENT FIRST GAVE. It claimed that flipping on a
  // chaining re-arm would "dispatch the WRONG action", i.e. a correctness
  // break. ⛔ THAT WAS WRONG, and the mutant is what showed it: with
  // `M_BUF_CHAINFLIP` the flip makes an unfilled slot the head, `fetch_addr`
  // sees an invalid head and reloads it from `l_pc` -- which, because a
  // chaining re-arm does NOT advance the PC, is the SAME action. Behaviour is
  // correct, the buffer-swap invariant holds, and the pins are right.
  // ⇒ The asymmetry is a PERFORMANCE choice: it avoids one needless refill per
  //   park dispatch. Recorded as such rather than left overstated, because a
  //   comment that calls an optimisation a correctness requirement is how a
  //   later simplification gets rejected for a reason that is not true.
  function want_fetch(input [LW-1:0] ln);
    reg [ACT_W-1:0] hact;
    reg             hvalid, fvalid;
    begin
      hvalid = l_actv[ln*2 + (l_sel[ln] ? 1 : 0)];
      fvalid = l_actv[ln*2 + (l_sel[ln] ? 0 : 1)];
      hact   = l_act [ln*2 + (l_sel[ln] ? 1 : 0)];
      if (!hvalid)
        want_fetch = 1'b1;                           // head is empty: urgent
      else if (hact[ACT_W-1 -: 3] == OP_REARM && !hact[ACT_W-4-PINW])
        want_fetch = 1'b0;                           // chaining: successor is
                                                     // the head; spare unused
      else
        want_fetch = !fvalid;                        // fill the spare
    end
  endfunction

  // =====================================================================
  // ⭐⭐ PRIME BEFORE RELEASE -- the cold start removed, not redefined
  // =====================================================================
  // ⛔⛔ WHY NOT JUST EXCLUDE IT. The measured J = 5 this project quoted since
  // S3 turned out to be entirely a COLD START: at `hdr_done` both slots of
  // every lane are empty, so each lane's FIRST action waits for a full refill.
  // The tempting move is to declare the first job out of scope. ⛔ THAT WOULD BE
  // WRONG, and the reason is specific: on a SOURCE lane a late first edge
  // followed by an on-time second edge IS differential jitter against `D_tol` --
  // the peer sees a short first bit. Excluding it by definition would be
  // excluding a real timing error because it happens to be first.
  //
  // ⭐ SO IT IS REMOVED STRUCTURALLY INSTEAD. No lane is released until EVERY
  // live lane's buffers are primed, and `now` does not advance until then. The
  // refill latency becomes a fixed START-UP LATENCY that elapses entirely
  // BEFORE job 1 exists, so it is outside every job's response time -- and the
  // exclusion is then earned by the design rather than asserted in the model.
  //
  // ⭐ `!want_fetch(i)` IS THE PRIMING CONDITION, and reusing it is not a
  // shortcut: that function already encodes exactly "this lane needs nothing
  // more fetched", including the chaining-re-arm case where the spare is
  // DELIBERATELY left unfilled. A hand-written "both slots valid" would deadlock
  // on precisely that case, waiting forever for a slot the design never fills.
  //
  // ⛔ PRIMING WAITS FOR THE SPARE, NOT JUST THE HEAD. With only the head
  // primed, the first dispatch is clean and then the first WRITEBACK empties it
  // with no successor resident -- so the stall reappears on action 2 and
  // first-edge jitter would still differ from steady state. The must-fire is
  // `cold == steady`, which only holds if the steady-state invariant (spare
  // resident) holds at the first dispatch too.
  // ⛔⛔ PRIMING IS A ONE-SHOT, AND A CONTINUOUS GATE DEADLOCKED THE ENGINE.
  // "every lane wants nothing fetched" is true at start-up and then FALSE again
  // one cycle after every writeback, because the swap leaves the freed slot
  // empty. Used as a continuous gate it de-asserted immediately after the first
  // dispatch, froze `now`, and the design produced ZERO EDGES -- the first
  // smoke run of prime-before-release was a total stall, not a jitter result.
  // ⭐ "Primed" is a START-UP MILESTONE, not an invariant: latched once, and the
  // ordinary refill churn afterwards must not revoke it.
  //
  // ⛔⛔⛔ AND THE SECOND BUG HERE IS A VERILOG TRAP WORTH THE COMMENT. The
  // first version computed this with a generate + CONTINUOUS ASSIGN:
  //     assign lane_unprimed[gi] = l_live[gi] & want_fetch(gi);
  // A function call in a continuous assignment is sensitive ONLY TO ITS
  // ARGUMENTS. `gi` is a genvar constant, so `want_fetch` was evaluated once at
  // time 0 -- when every array was still X -- and NEVER RE-EVALUATED.
  // `lane_unprimed` sat at `xxxxx` for the whole run, `prime_now` never
  // asserted, and the engine produced zero edges again, for an entirely
  // different reason than the first time.
  // ⭐ EVALUATING IT IN THE CLOCKED BLOCK FIXES IT PROPERLY, and is better than
  // an `always @(*)`: `@*`'s sensitivity to signals read INSIDE a called
  // function is tool-dependent, so that would have been the same latent bug
  // with a different trigger. Here the function is called at a clock edge with
  // current values, and -- importantly -- `want_fetch` stays the SINGLE
  // definition of "this lane needs nothing more fetched", rather than being
  // duplicated into a priming-specific copy that could drift from it.
  reg primed_q;
  reg prime_unp;
  integer pi;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)      primed_q <= 1'b0;
    else if (!run)   primed_q <= 1'b0;      // HALT re-primes on the next run
    else if (!primed_q) begin
      prime_unp = 1'b0;
      for (pi = 0; pi < N_LANES; pi = pi + 1)
        if (l_live[pi] && want_fetch(pi[LW-1:0])) prime_unp = 1'b1;
      if (hdr_done && !prime_unp) primed_q <= 1'b1;
    end
  end
  wire primed = primed_q;

  // ---- the one arbiter for the shared store read port ----------------
  // ⭐ Header load has priority, then prefetch. The engine's own dispatch does
  //   NOT read the store -- that is the whole point of the prefetch registers,
  //   and it is what keeps C at 2.
  always @(posedge clk or negedge rst_n) begin
    // ⛔⛔ THIS BLOCK IS THE SOLE DRIVER OF ALL FOUR STORE-REQUEST REGS, AND
    // THAT HAD TO BE FIXED. `s_wre`/`s_wraddr` were ALSO reset in the main
    // sequential block below, so two always blocks drove them: 1 + AW = 9 nets,
    // which Yosys reported as exactly "9 multiple conflicting drivers" and
    // LibreLane refused to harden.
    // ⭐⭐ AND iverilog ACCEPTED IT SILENTLY. Multiple procedural drivers are
    // last-write-wins in simulation and a hard error in synthesis, so the local
    // smoke bench passed -- with correct edge counts and correct C -- on a
    // design that CANNOT BE BUILT. ⇒ A simulation bench cannot see multi-driver;
    // only synthesis can. That is why CI is a gate and not a formality.
    if (!rst_n) begin
      s_re     <= 1'b0;
      s_raddr  <= {AW{1'b0}};
      s_wre    <= 1'b0;
      s_wraddr <= {AW{1'b0}};
    end else begin
      s_re <= 1'b0;
      if (hst == H_REQ) begin
        s_re    <= 1'b1;
        // ⭐ SIZED: the product and the sum are formed at AW, not at the
        // 32 bits an unsized integer parameter forces, so the assign cannot
        // silently truncate. HDR_FITS_AW is what guarantees it cannot
        // overflow either -- and that assertion is the load-bearing half.
        s_raddr <= hdr_byte_addr(hl, hb);
      end
      s_wre <= 1'b0;
      if (pst == P_REQ) begin
        s_wre    <= 1'b1;
        // ⛔ `paddr` IS LATCHED AT THE SCAN, NOT RECOMPUTED HERE. `fetch_addr`
        // reads l_pc / l_sel / l_actv, and a writeback in the intervening cycle
        // moves all three -- so recomputing at P_REQ could request one address
        // while P_CAP files the word into the slot chosen for a different one.
        // Latching the (lane, slot, address) triple together is what keeps the
        // refill atomic with respect to the dispatch pipeline.
        s_wraddr <= paddr;
      end
    end
  end

  // =====================================================================
  // THE ONE SEQUENTIAL BLOCK for lane state, so no field has two writers.
  // =====================================================================
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      st       <= ST_IDLE;
      jitter_cnt <= {JW{1'b0}};
      jitter_max <= {JW{1'b0}};
      cur      <= {LW{1'b0}};
      cur_act  <= {ACT_W{1'b0}};
      hst      <= H_IDLE;
      hl       <= {LW{1'b0}};
      hb       <= 4'd0;
      hsh      <= {(HDR_BYTES*8){1'b0}};
      hdr_done <= 1'b0;
      pst      <= P_SCAN;
      pl       <= {LW{1'b0}};
      // ⭐ RESET-HIGH on the pins is handled in the TOP module, not here:
      //   which pins can RELEASE differs between the two banks, and this
      //   module does not know the banks. See pe_top's reset comment.
      pin_out  <= {N_PINS{1'b1}};
      // ⛔ RESET TO ALL PUSH-PULL, matching `pin_out`'s reset-high: at reset
      // `pin_oe` is 0 so nothing is driven, and a lane cannot drive until its
      // header has set this pin's class. Resetting to 0 instead would mask the
      // reset-HIGH value of the `uo_out` protocol pins to 0 and break the
      // forced idle-high that bank requires.
      pin_pp   <= {N_PINS{1'b1}};
      pin_oe   <= {N_PINS{1'b0}};
      rx_data  <= 8'h00;
      rx_push  <= 1'b0;
      sticky_ovr    <= 1'b0;
      config_err    <= 1'b0;
      host_pop      <= 1'b0;
      lane_underrun <= {N_LANES{1'b0}};
      lane_overflow <= {N_LANES{1'b0}};
      for (i = 0; i < N_LANES; i = i + 1) begin
        l_pin[i]    <= {PINW{1'b0}};
        l_clkpin[i] <= {PINW{1'b0}};
        l_mode[i]   <= 1'b0;
        l_data[i]   <= 8'h00;
        l_bitp[i]   <= {BPW{1'b0}};
        l_timestamp[i]     <= {TS_W{1'b0}};
        l_c[i]      <= {CW{1'b0}};
        l_d[i]      <= {D_W{1'b0}};
        l_t[i]      <= {DLY_W{1'b0}};
        l_live[i]   <= 1'b0;
        l_pc[i]     <= {AW{1'b0}};
        l_base[i]   <= {AW{1'b0}};
        l_fpc[i]    <= {AW{1'b0}};
        l_sel[i]    <= 1'b0;
        // ⛔ EVERY ARM REGISTER RESETS, including `l_armpin`. An X in the pin
        // index would index `pin_rise` with X and make `arm_hit` X, which the
        // ready term then propagates into the scheduler -- the same class of
        // failure as the X action word that killed a lane permanently.
        l_armed[i]   <= 1'b0;
        l_armpin[i]  <= {PINW{1'b0}};
        l_armedge[i] <= 1'b0;
        l_notmo[i]   <= 1'b0;
        l_timeout[i] <= 1'b0;
      end
      // ⛔ A SEPARATE LOOP, because the slot arrays are 2*N_LANES long and
      // reusing the lane loop would leave the odd slots unreset -- X on the
      // valid bit of every spare, which in simulation reads as "maybe valid"
      // and in synthesis as a don't-care the tools may resolve either way.
      for (i = 0; i < NSLOT; i = i + 1) begin
        l_act[i]  <= {ACT_W{1'b0}};
        l_actv[i] <= 1'b0;
      end
    end else if (!run) begin
      // HALT, RELOAD, RESUME -- an explicit scope choice, never a mid
      // transaction swap. Everything re-initialises on the next run entry.
      st       <= ST_IDLE;
      hst      <= H_IDLE;
      hdr_done <= 1'b0;
      pst      <= P_SCAN;
      rx_push  <= 1'b0;
      // ⭐⭐ RELEASE EVERY PIN ON HALT, AND THIS IS WHAT FIXES F2 FACE 3.
      // `pin_oe` used to survive a halt, so the TOP had to force release with
      // `assign uio_oe = prog_mode ? 0 : uio_oe_run` -- a COMBINATIONAL mux
      // whose select is `ui_in[7]`, a RAW ASYNCHRONOUS INPUT PIN. The real
      // netlist showed the consequence: all 16 `uio_out`/`uio_oe` bits driven
      // by `and2`/`nor2` instead of a flop, so a host transition on prog_mode
      // can GLITCH every uio pin -- and SCL and SCLK are in that bank, where a
      // glitch is an extra clock edge and therefore a corruption, not a margin
      // problem. That is exactly what ruling F2 forbids.
      // ⇒ Clearing it HERE moves the release behind the existing flop, so the
      //   top module needs no mux at all and every uio bit is a flop Q.
      // ⛔ It costs ONE CYCLE of release latency, not zero: prog_mode is async
      //   and this clear is synchronous, so the host must leave at least one
      //   clock between asserting prog_mode and driving `uio`. The load
      //   sequence already does, and `gate_load_pin_safety` plus the bench's
      //   load-mode violation counters are what hold that.
      pin_oe   <= {N_PINS{1'b0}};
      for (i = 0; i < N_LANES; i = i + 1) begin
        l_live[i] <= 1'b0;
        l_pc[i]   <= {AW{1'b0}};
        l_fpc[i]  <= {AW{1'b0}};
        l_sel[i]  <= 1'b0;
        // ⛔ DISARM ON HALT. A lane left armed across a reload would fire on an
        // edge belonging to the PREVIOUS program. `l_timeout` is deliberately
        // NOT cleared here: it is sticky status the host reads AFTER halting,
        // and clearing it on halt would erase the reason the host halted.
        l_armed[i]   <= 1'b0;
        l_notmo[i]   <= 1'b0;
      end
      for (i = 0; i < NSLOT; i = i + 1) l_actv[i] <= 1'b0;
    end else begin
      rx_push <= 1'b0;
        host_pop <= 1'b0;   // one-cycle pulse; the consume site re-asserts

      // ---------------- header load ----------------------------------
      case (hst)
        H_IDLE: if (!hdr_done) begin
                  hst <= H_REQ; hl <= {LW{1'b0}}; hb <= 4'd0;
                end
        H_REQ:  hst <= H_WAIT;
        H_WAIT: hst <= H_RD;             // the registered read's dead cycle
        H_RD:   begin
                  hsh <= {hsh[HDR_BYTES*8-9:0], s_rdata};
                  if (hb == HB_LAST) begin
                    // ⭐ unpack: pin, clkpin, t, C_i, D_sched. D_tol is the
                    //   remaining field and is DELIBERATELY NOT STORED.
                    // ⛔⛔ MSB-ALIGNED INSIDE HDR_BYTES*8, NOT HDR_BITS.
                    // The header is HDR_BITS = 38 bits inside a HDR_BYTES*8 =
                    // 40-bit byte-shift register, so slicing from HDR_BITS-1
                    // reads 2 bits LOW and every field straddles a byte
                    // boundary that the image writer did not intend. Aligning
                    // to the top of the shift register makes the layout
                    // hand-assemblable: byte0 = {pin, clkpin}, and the 2 spare
                    // bits land at the BOTTOM where nothing reads them.
                    l_pin[hl]    <= hsh_n[HDR_BYTES*8-1 -: PINW];
                    l_clkpin[hl] <= hsh_n[HDR_BYTES*8-1-PINW -: PINW];
                    l_mode[hl]   <= hsh_n[HDR_BYTES*8-1-2*PINW];
                    // ⛔⛔ 1.6s IN SILICON. It was ruled as "the loader REJECTS"
                    // and no load-time rejection existed anywhere -- not in the
                    // RTL, and not asserted in the toolchain, which only stated
                    // it in a docstring. An open-drain lane on a `uo_out` pin
                    // cannot release, so it drives low once and sticks; that is
                    // a configuration the chip must refuse, not emulate.
                    // ⭐ CHECKED ON BOTH PINS the header names, because the
                    // clock pin is as unreleasable as the data pin -- which is
                    // exactly the asymmetry D2 was.
                    if (hsh_n[HDR_BYTES*8-1-2*PINW] == 1'b0) begin
                      if (hsh_n[HDR_BYTES*8-1 -: PINW] >= N_UIO[PINW-1:0])
                        config_err <= 1'b1;
                      if (hsh_n[HDR_BYTES*8-1-PINW -: PINW] >= N_UIO[PINW-1:0])
                        config_err <= 1'b1;
                    end
                    // ⭐ RULING 1.5: the per-PIN drive class, derived here from
                    // the lane that owns the pin. Both the data pin and the
                    // clock pin take the lane's mode, and this lands during the
                    // header window -- before `hdr_done`, so before any
                    // dispatch can read it.
                    // ⛔ RANGE-GUARDED. PINW = 4 addresses 0..15 while
                    // N_PINS = 12, and a header may legitimately name the
                    // reserved non-driving index -- an unguarded write here
                    // would be the out-of-range `pin_out[12]` class this
                    // project has already paid for once.
                    if (hsh_n[HDR_BYTES*8-1 -: PINW] < N_PINS[PINW-1:0])
                      pin_pp[hsh_n[HDR_BYTES*8-1 -: PINW]]
                          <= hsh_n[HDR_BYTES*8-1-2*PINW];
                    if (hsh_n[HDR_BYTES*8-1-PINW -: PINW] < N_PINS[PINW-1:0])
                      pin_pp[hsh_n[HDR_BYTES*8-1-PINW -: PINW]]
                          <= hsh_n[HDR_BYTES*8-1-2*PINW];
                    l_t[hl]      <= hsh_n[HDR_BYTES*8-2-2*PINW -: DLY_W];
                    l_c[hl]      <= hsh_n[HDR_BYTES*8-2-2*PINW-DLY_W -: CW];
                    l_d[hl]      <= hsh_n[HDR_BYTES*8-2-2*PINW-DLY_W-CW -: D_W];
                    l_pc[hl]     <= hsh_n[HDR_BYTES*8-2-2*PINW-DLY_W-CW-D_W-D_W -: AW];
                    l_base[hl]   <= hsh_n[HDR_BYTES*8-2-2*PINW-DLY_W-CW-D_W-D_W -: AW];
                    // ⭐ the fetch pointer starts WITH the PC, not ahead of it:
                    // both slots are empty, so the first refill targets the
                    // head at `l_pc` and `fetch_addr` reads `l_pc` directly.
                    // `l_fpc` then takes over from P_CAP onward.
                    l_fpc[hl]    <= hsh_n[HDR_BYTES*8-2-2*PINW-DLY_W-CW-D_W-D_W -: AW];
                    l_live[hl]   <= 1'b1;
                    hb <= 4'd0;
                    if (hl == LANE_LAST) begin
                      hst <= H_DONE; hdr_done <= 1'b1;
                    end else begin
                      hl <= hl + 1'b1; hst <= H_REQ;
                    end
                  end else begin
                    hb  <= hb + 4'd1;
                    hst <= H_REQ;
                  end
                end
        default: hst <= H_DONE;
      endcase

      // ---------------- prefetch -------------------------------------
      // ⛔ Only refills a lane whose prefetch is INVALID. The invalidation on
      //    PC advance is in the writeback below, and removing it is
      //    M-PREFETCH-STALE.
      if (hdr_done) begin
        case (pst)
          P_SCAN: begin
            // ⭐ THE EDF WINNER IS SERVED FIRST. A round-robin refill makes the
            // jitter above depend on scan position rather than on the schedule,
            // which is how a prefetch policy silently becomes the scheduler.
            // ⭐ WITH TWO SLOTS THE PRIORITY IS SHARPER, not just inherited: an
            // EMPTY HEAD on the EDF winner is the only case that can still
            // stall a dispatch, so it is served first; filling a SPARE is
            // speculative work that can wait. `want_fetch` folds both.
            if (winner_v && !l_actv[winner*2 + (l_sel[winner] ? 1 : 0)]) begin
              pl    <= winner;
              pslot <= l_sel[winner];        // the head: it is what stalls
              paddr <= l_pc[winner];
              pst   <= P_REQ;
            end else if (l_live[pl] && want_fetch(pl)) begin
              // fill the head if empty, otherwise the spare
              pslot <= l_actv[pl*2 + (l_sel[pl] ? 1 : 0)] ? (!l_sel[pl])
                                                          : l_sel[pl];
              paddr <= fetch_addr(pl);
              pst   <= P_REQ;
            end else begin
              pl <= (pl == LANE_LAST) ? {LW{1'b0}} : pl + 1'b1;
            end
          end
          // ⛔⛔ M_PFETCH_NOWAIT IS THE PRICE OF ALLOWLIST ENTRY #2. The reset
          //    audit allows `s_wrdata` unreset because "captured at P_CAP,
          //    which only runs after a real P_REQ -- so it is
          //    write-before-read". THIS WAIT STATE IS THAT SENTENCE. Deleting
          //    it makes P_CAP sample `s_wrdata` in the cycle the store is
          //    still registering the read, so the FIRST refill captures a
          //    never-written register: X in iverilog, a per-seed random
          //    pattern under `--x-initial unique`, and therefore traces that
          //    DISAGREE ACROSS SEEDS. That disagreement is the detector the
          //    allowlist's prose otherwise only asserts.
`ifdef M_PFETCH_NOWAIT
          P_REQ:  pst <= P_CAP;
`else
          P_REQ:  pst <= P_WAIT;         // request registered
`endif
          P_WAIT: pst <= P_CAP;          // store read registered
          P_CAP:  begin
            // MSB-aligned: byte0 = {opcode, pin, level}, 2 spare at the bottom
            l_act [pl*2 + (pslot ? 1 : 0)] <= s_wrdata[ACT_BYTES*8-1 -: ACT_W];
            l_actv[pl*2 + (pslot ? 1 : 0)] <= 1'b1;
            // ⭐ THE SUCCESSOR POINTER ADVANCES FROM THE ADDRESS JUST FETCHED,
            // which is what makes the loop case need no special handling here:
            // after a `l_base` fetch, `l_fpc` becomes `l_base + ACT_BYTES`,
            // exactly the successor of the action now resident.
            l_fpc[pl] <= paddr + ACT_BYTES[AW-1:0];
            pst       <= P_SCAN;
            pl        <= (pl == LANE_LAST) ? {LW{1'b0}} : pl + 1'b1;
          end
          default: pst <= P_SCAN;
        endcase
      end

      // ---------------- dispatch, C = 2 ------------------------------
      // ⛔ REFUSES TO RUN on a 1.6s violation. Not a warning: the program names
      //    a pin that physically cannot do what it asked, so dispatching would
      //    emulate a protocol incorrectly rather than fail visibly. The host
      //    sees CONFIG_ERR in the status stream.
      // ⛔⛔ THE `ifdef` BELOW WRAPS THE MINIMAL DELTA -- ONE EXPRESSION, NOTHING
      //    ELSE, NOT EVEN THIS COMMENT. `!config_err` first went in on the
      //    M_NO_PRIME arm ONLY, because the two arms each carried a full copy of
      //    the guard line and a text edit hit the wrong copy; the default path
      //    never had it and the violating program ran. A FIX THAT LANDS IN A
      //    MUTANT ARM IS NOT IN THE DESIGN. `gate_mutant_arms.py` now
      //    preprocesses with and without every define and requires the diff to
      //    be exactly the intended mutation, so arms cannot drift again.
      case (st)
        ST_IDLE: if (
`ifdef M_NO_PRIME
                     hdr_done
`else
                     primed
`endif
                     && !config_err && winner_v) begin
                   // ⛔⛔ RULING 2: ARRIVING READY WHILE STILL ARMED IS A
                   // TIMEOUT, AND A TIMEOUT IS AN ERROR. The lane armed, its
                   // deadline passed, and no edge of the requested polarity ever
                   // came -- so the peer is silent or absent. The lane HALTS and
                   // sets a sticky flag; it does NOT execute its next action.
                   // ⭐ WHY IT CANNOT JUST PROCEED: a program would then be
                   // unable to tell "the peer answered" from "the peer never
                   // answered", and would read a frame out of an idle line. That
                   // is the forbidden direction one level up from an unsound
                   // bound -- not a number that is too small, but a chip that
                   // reports data it never received.
                   // ⛔ M_TIMEOUT_PROCEED removes the halt and the bench fails.
`ifndef M_TIMEOUT_PROCEED
                   if (l_armed[winner]) begin
                     l_live[winner]    <= 1'b0;      // HALT this lane
                     l_armed[winner]   <= 1'b0;
                     l_timeout[winner] <= 1'b1;      // STICKY -- status stream
                     sticky_ovr        <= 1'b1;
                   end else
`endif
                   // ⭐ dispatch reads the HEAD slot. With the spare already
                   // filled, the usual case after a writeback is that the head
                   // is valid IMMEDIATELY -- which is the whole J reduction.
                   if (l_actv[winner*2 + (l_sel[winner] ? 1 : 0)]) begin
                     cur     <= winner;
                     cur_act <= l_act[winner*2 + (l_sel[winner] ? 1 : 0)];
                     st      <= ST_DRIVE;
                   end else begin
                     // ⭐⭐ THIS STALL IS THE JITTER TERM J. The EDF winner is
                     // chosen, its release has arrived, and dispatch waits only
                     // because its action word is not in the register yet.
                     // ⛔ A2 budgets J = 1. If this can exceed 1, the shipped
                     // r_i do not hold -- so it is COUNTED, not assumed, and
                     // the maximum is observable for the bench to assert on.
                     jitter_cnt <= jitter_cnt + 1'b1;
                     if (jitter_cnt >= jitter_max) jitter_max <= jitter_cnt + 1'b1;
                   end
                 end else begin
                   jitter_cnt <= {JW{1'b0}};
                 end

        ST_DRIVE: begin
          // ⭐ C9 = START: the pin moves in the FIRST cycle of service.
          // ⛔⛔ EVERY DRIVING CASE IS GUARDED BY `pin_real`, WHICH IS THE
          // NON-DRIVING NO-OP (the half-bit offset ruling, option (b)).
          // `PIN_NONE` is a RESERVED pin index: PINW = 4 encodes 16 values and
          // only N_PINS = 12 are real, so the code was already there and the
          // whole mechanism is a decode tweak -- no new opcode, no new field.
          // ⭐ WHY A NO-OP IS NEEDED AT ALL: the edge rebase sets
          // `l_timestamp := now`, so the FIRST action after ARM dispatches AT
          // the edge -- while UART-rx needs its first sample at `edge + half`.
          // ARM's delay field is the TIMEOUT, and a delay only takes effect at
          // an action's WRITEBACK, so it delays the NEXT action and not its
          // own. The idiom is therefore `ARM -> no-op(delay = half) -> sample`.
          // ⭐⭐ AND RULING 2 IS WHAT MAKES IT EXACT: writeback adds to the
          // STORED timestamp, so the sample lands at `t_edge + half` however
          // late the no-op itself is serviced. The no-op's own service jitter
          // never reaches the sampling grid.
          // ⛔ IT MUST BE GUARANTEED NON-DRIVING, not merely intended to be:
          // on a reactive lane the lane's pin is an INPUT, and a no-op that
          // drove it would fight the peer -- the same contention class 1.6r
          // closed on MISO. `pin_real` is that guarantee, and
          // `M_NOOP_DRIVES` removes it so the bench can show the difference.
          case (a_op)
            OP_LEVEL, OP_START, OP_STOP: if (pin_real) begin
              if (l_mode[cur]) begin
                // push-pull: drive both levels. ⭐ `& pin_pp[...]` is RULING
                // 1.5 -- see the `pin_pp` declaration. It makes "an open-drain
                // pin drives a 1" unsatisfiable at the flop's D input rather
                // than relying on this branch being written correctly.
                pin_out[a_pin] <= a_lvl & pin_pp[a_pin];
                pin_oe[a_pin]  <= 1'b1;
              end else begin
                pin_out[a_pin] <= 1'b0;         // open-drain: NEVER drives 1
                pin_oe[a_pin]  <= ~a_lvl;       // low = drive, high = release
              end
            end
            OP_SHIFT: if (pin_real) begin
              if (l_mode[cur]) begin
                pin_out[a_pin] <= l_data[cur][0] & pin_pp[a_pin];
                pin_oe[a_pin]  <= 1'b1;
              end else begin
                pin_out[a_pin] <= 1'b0;
                pin_oe[a_pin]  <= ~l_data[cur][0];
              end
              // ⛔⛔⛔ D2: THE CLOCK PIN HONOURS `l_mode` TOO, AND IT DID NOT.
              // It was driven `pin_out <= a_lvl; pin_oe <= 1` unconditionally,
              // so an OPEN-DRAIN lane drove a HARD 1 on its clock. Measured on
              // the I2C program: `uio_oe=00000110 uio_out=11111011` -- SDA
              // correctly pulled low, SCL actively driven high.
              // ⚠ THAT IS AN ELECTRICAL HAZARD, NOT A MISSING FEATURE. A peer
              // stretches I2C by holding SCL LOW; against a push-pull high that
              // is a SHORT. `test/fram_i2c.v` exports `scl_oe` as a pull-low
              // stretch enable and the A2 stretch reasoning assumes a
              // releasable SCL, so the peer model and the schedulability
              // argument both relied on something the engine could not do. It
              // also broke I2C compliance and made N1a's observed-rise release
              // meaningless: there is no rise to observe if we drive it.
              // ⭐ Open-drain now pulls low with oe=1/out=0 and RELEASES with
              // oe=0; the high phase comes from the observed SCL rise through
              // edge capture, which is what N1a says it should.
              // ⚠ The comment this replaces justified driving the clock HERE --
              // "so data and clock never need P-ORDER per bit" -- which is
              // about ORDERING and holds under either drive style.
              // ⛔ M_OD_CLK_PUSHPULL restores the defect exactly as it was, so
              // the cross-program open-drain invariant is PRICED rather than
              // only ever seen to pass. A guard that has never been observed to
              // fail has unknown strength, and this one is new.
`ifdef M_OD_CLK_PUSHPULL
              pin_out[l_clkpin[cur]] <= a_lvl;
              pin_oe[l_clkpin[cur]]  <= 1'b1;
`else
              if (l_mode[cur]) begin
                pin_out[l_clkpin[cur]] <= a_lvl & pin_pp[l_clkpin[cur]];
                pin_oe[l_clkpin[cur]]  <= 1'b1;
              end else begin
                pin_out[l_clkpin[cur]] <= 1'b0;
                pin_oe[l_clkpin[cur]]  <= ~a_lvl;
              end
`endif
            end
            OP_SHIFTIN, OP_READBIT: if (pin_real) begin
              pin_oe[a_pin] <= 1'b0;            // release to sample
            end
            // ⭐ OP_ARM moves no pin -- it RELEASES the lane on a peer edge.
            // Its state goes in at writeback, below.
            OP_ARM, OP_REARM: ;                 // no pin movement
            default: ;
          endcase
          st <= ST_WB;
        end

        ST_WB: begin
          // ⛔⛔ RULING 2: the re-arm ADDS TO THE STORED TIMESTAMP, never to
          //    `now`. The relative form drifts k*(r-C) -- 15,260 cycles on a
          //    one-second delay -- and is INVISIBLE at k = 1.
          l_timestamp[cur] <= l_timestamp[cur] + {{(TS_W-DLY_W){1'b0}}, a_dly};

          // ⭐⭐ ARM: the reactive release, armed here and fired by the edge
          // capture below. The timestamp add above IS the timeout deadline --
          // no second comparator, no second register. The action's EXISTING
          // fields carry everything: `pin` names the pin, `level` selects the
          // polarity (rise for I2C's SCL, fall for a UART start bit and for
          // SPI-target's CS), and `delay` is the timeout.
          // ⛔ `delay == 0` MEANS "NO TIMEOUT", which is how a lane that must
          // wait indefinitely (UART-rx between frames) is expressed. It is an
          // encoding choice in an existing field rather than a new one, and the
          // `ready` term above is what makes it mean "not ready on time".
          if (a_op == OP_ARM) begin
            l_armed[cur]   <= 1'b1;
            l_armpin[cur]  <= a_pin;
            l_armedge[cur] <= a_lvl;
            l_notmo[cur]   <= (a_dly == {DLY_W{1'b0}});
          end

          case (a_op)
            OP_SHIFT: begin
              l_data[cur] <= {1'b0, l_data[cur][7:1]};
              l_bitp[cur] <= l_bitp[cur] + {{(BPW-1){1'b0}}, 1'b1};
            end
            OP_SHIFTIN: begin
              l_data[cur] <= {pin_in[a_pin], l_data[cur][7:1]};
              l_bitp[cur] <= l_bitp[cur] + {{(BPW-1){1'b0}}, 1'b1};
              if (l_bitp[cur] == a_cnt - {{(BPW-1){1'b0}}, 1'b1}) begin
                rx_data <= {pin_in[a_pin], l_data[cur][7:1]};
                rx_push <= 1'b1;
                l_bitp[cur] <= {BPW{1'b0}};
              end
            end
            OP_READBIT: l_data[cur] <= {pin_in[a_pin], l_data[cur][7:1]};
            default: ;
          endcase

          // ---- PC advance, and the invalidation M-PREFETCH-STALE removes ----
          // ⭐ A no-op re-arm does NOT advance the PC: that is what makes a
          //   chained re-arm re-execute the same action at a later timestamp,
          //   which is Ruling 2's mechanism for long delays.
          // ⭐⭐ THE SWAP. The head is consumed, so it is invalidated AND
          // `l_sel` flips: the spare -- already holding this action's successor
          // -- becomes the head, and the next dispatch of this lane finds a
          // valid head with NO refill on its path. The freed slot becomes the
          // new spare and the prefetcher refills it in the background.
          // ⛔ BOTH PC-ADVANCING BRANCHES SWAP, and a CHAINING re-arm swaps
          // NEITHER: its PC does not move, so its successor IS the head, and
          // flipping would dispatch the spare's unrelated word. That asymmetry
          // is the buffer-swap invariant, and M-BUF-SWAP mutates it.
          // ⛔⛔ THE THREE MUTANTS ARE WIRED HERE, not described in a comment.
          // `M-PREFETCH-STALE` was NAMED in this file for the single-buffer
          // design and never mechanically runnable -- so it was a mutant nobody
          // had ever seen kill anything. `test/run_mutants.py` builds each of
          // these and REQUIRES the bench to fail; a mutant that survives means
          // the bench does not test the thing the mutant breaks.
          //   M_BUF_NOINVAL   swap without invalidating -> after two
          //                   writebacks the lane dispatches the CONSUMED
          //                   action again. Correctness; the invariant catches it.
          //   M_BUF_SWAP      invalidate without swapping -> correct action,
          //                   but every dispatch pays a full refill. The J
          //                   split catches it, which is the point: it proves
          //                   the SWAP is what buys the J reduction.
          //   M_BUF_CHAINFLIP swap on a CHAINING re-arm too. ⛔ A CHARACTERISED
          //                   SURVIVOR, not a kill: it takes effect (the sel
          //                   flip count changes) but costs only one needless
          //                   refill per park dispatch, which no program the
          //                   bench can build makes visible in the worst-case
          //                   stall. So the chaining asymmetry is correct by
          //                   DERIVATION and unevidenced by TEST, and that is
          //                   recorded rather than papered over with a
          //                   program contrived to kill it.
          if (a_op != OP_REARM) begin
            l_pc[cur]   <= l_pc[cur] + ACT_BYTES[AW-1:0];
`ifndef M_BUF_NOINVAL
            l_actv[cur*2 + (l_sel[cur] ? 1 : 0)] <= 1'b0;   // ⛔ INVALIDATION
`endif
`ifndef M_BUF_SWAP
            l_sel[cur]  <= !l_sel[cur];                     // ⭐ THE SWAP
`endif
          end else if (a_lvl) begin
            l_pc[cur]   <= l_base[cur];         // loop back to the start
`ifndef M_BUF_NOINVAL
            l_actv[cur*2 + (l_sel[cur] ? 1 : 0)] <= 1'b0;
`endif
`ifndef M_BUF_SWAP
            l_sel[cur]  <= !l_sel[cur];
`endif
          end
          // ⛔ M_BUF_CHAINFLIP swaps the slot on a CHAINING re-arm, where the
          //    PC does not move -- so the head would point at the word the lane
          //    just executed. The comment lives OUTSIDE the arm: a comment that
          //    exists in only one arm proves the `ifdef` wraps more than the
          //    delta, and `gate_mutant_arms.py` fails on exactly that.
`ifdef M_BUF_CHAINFLIP
          else begin
            l_sel[cur] <= !l_sel[cur];
          end
`endif

          // ⛔⛔ A "CHEAP WIN" THAT MADE IT WORSE, KEPT AS A RECORD.
          // The J decomposition said the dominant terms were the prefetch
          // FSM's scan notice (1) plus waiting behind another lane's in-flight
          // refill (3). So this block used to kick a refill for `cur` at
          // writeback, to overlap it with the lane's own inter-action delay.
          // ⭐ MEASURED J WENT 5 -> 7. Starting a refill at EVERY writeback
          // keeps the single shared fetch port busy, so a DIFFERENT lane that
          // becomes the EDF winner now waits behind it. The optimisation moved
          // the contention it was meant to remove.
          // ⇒ REVERTED. And the lesson is structural: with ONE shared fetch
          //   port, J cannot be driven to 1 by scheduling the refills better.
          //   It needs either a larger derived J in the baseline, or per-lane
          //   DOUBLE BUFFERING (hold current + next, ~110 more flops) so a
          //   dispatch never waits on a fetch at all. That is an architecture
          //   choice, not a tweak, and margin 9 already clears the bar -- so it
          //   is optimisation, not rescue.

          // ---- the host data channel (F1), and its sticky flag ----------
          // ⛔ underrun is a STICKY FLAG, NEVER A STALL: a stall would make C
          //    unbounded, which is the clock-stretch conclusion a third time.
          if (a_op == OP_SHIFT && l_bitp[cur] == a_cnt) begin
            if (host_valid) begin
              l_data[cur] <= host_data;
              host_pop    <= 1'b1;        // consumed: advance the host FIFO
            end else begin
              lane_underrun[cur] <= 1'b1;
            end
            l_bitp[cur] <= {BPW{1'b0}};
          end

          st <= ST_IDLE;
          jitter_cnt <= {JW{1'b0}};
        end

        default: st <= ST_IDLE;
      endcase

      // ---- sticky ovr: a lane was still ready when its own next release
      //      arrived, i.e. the queue-depth-one assumption (1.6a) was violated.
      for (i = 0; i < N_LANES; i = i + 1) begin
        if (l_live[i] && ready[i] && busy && (i[LW-1:0] != cur))
          sticky_ovr <= sticky_ovr;             // observed, not an error here
      end

      // ---- ⭐⭐ EDGE CAPTURE AND REBASE (Ruling 1) ---------------------
      // ⛔⛔ IT LIVES IN *THIS* BLOCK, and that is not a style choice. This is
      // the ONE sequential block for lane state, and `l_timestamp` is written
      // by ST_WB above. A second always block writing it would be
      // TS_W x N_LANES = 80 multiple-driver nets -- the same defect that made
      // the engine unsynthesizable once, passed the local bench in silence
      // (last-write-wins in simulation, a hard error in synthesis) and killed a
      // harden after three minutes.
      //
      // ⭐ ORDERING IS SAFE WITHOUT A PRIORITY TERM: a lane being dispatched
      // cannot be armed in the same cycle it arms, because `l_armed[cur] <= 1`
      // above is non-blocking, so `l_armed[cur]` still reads 0 here and
      // `arm_hit[cur]` is 0. An ARM therefore cannot be fired by an edge in its
      // own writeback cycle -- which is correct: the window opens when the ARM
      // completes, not while it is executing.
      //
      // ⛔ M_NO_REBASE leaves the timestamp at the ARM's DEADLINE, which is
      // Ruling 1's failure: the sample grid anchors to an arbitrary timeout
      // instant instead of to the peer's edge, and UART-rx misses every bit.
      for (i = 0; i < N_LANES; i = i + 1) begin
        if (arm_hit[i]) begin
          l_armed[i] <= 1'b0;                   // capture DISARMS: a second
                                                // edge must not re-rebase and
                                                // slide the grid forward on
                                                // every peer transition
`ifndef M_NO_REBASE
          l_timestamp[i] <= now;                // ⭐ THE REBASE
`endif
        end
      end
    end
  end

  // ⚠ NOT CLAIMED HERE: that C is exactly 2 in silicon. The dispatch FSM spends
  // two cycles per action BY CONSTRUCTION (ST_DRIVE then ST_WB), which is the
  // intended C -- but the number A2 needs is the one a SIMULATION and a
  // post-synthesis path report agree on. ⛔ "Two states therefore C = 2" is a
  // same-author re-derivation of my own design intent, and this project has
  // already recorded that such a thing is not an independent witness. S3's
  // results file states it as owed.
  wire _unused_eng = &{l_pin[0], 1'b0};

endmodule
