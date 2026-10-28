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

/* THE ENGINE'S RESET LIST, ONE COPY (candidate #11, WF2).
 *
 * ⛔⛔ THE HALT STATE EQUALS THE RESET STATE (Wilson, #10/#11). Before this
 * list the power-on reset and the halt clear were two hand-written lists, and
 * they had drifted: the halt cleared PCs, arms and `pin_oe` and nothing else,
 * so the bit pointers (#9), the pads' levels (#10) and the clocked-lane phase
 * state (#11: `l_ckbit` left at 7 made the first clocked SHIFT after a reload
 * 16 bits long) all survived a reload into the next program.
 * ⇒ Every always block with a power-on reset expands ONE macro below in BOTH
 *   its async power-on branch and its synchronous `!run` (halt) branch, so the
 *   two cannot drift: there is only one list. `model/gate_halt_reset.py` is
 *   the second check -- any flop reset at power-on outside these macros, and
 *   any keep-list entry beyond the named status flags, is red.
 * ⚠ IN THIS FILE, NOT AN INCLUDE: an `include needs every tool (iverilog,
 *   Verilator, slang, yosys, the harden flow, the gates that copy this file
 *   to a scratch directory) to be given the include path, and the first run
 *   of the gates with one showed most of them were not. One place is the
 *   requirement; this is one place.
 *
 * THE KEEP-LIST (`PE_RST_KEEP`, power-on only) is STATUS the host reads AFTER
 * halting -- clearing it at the halt would erase the reason the host halted:
 *     l_timeout, sticky_ovr, config_err, clk_stretch_err,
 *     lane_underrun, lane_overflow
 * Nothing else may be on it.
 *
 * Notes carried from the old hand-written lists:
 *   * `pin_out` all ones: reset-HIGH on the pins; the TOP decides which can
 *     release (`uo_out` cannot). At a HALT this is #10: a pad no longer keeps
 *     the halted program's last level.
 *   * `pin_pp` all ones (all push-pull), matching `pin_out`'s reset-high: a
 *     lane cannot drive until its header sets the pin's class; resetting to 0
 *     would mask the `uo_out` idle-high. `pin_inv` 0: a stale inverted clock
 *     is not carried into the next program.
 *   * `pin_oe` 0 -- RELEASE EVERY PIN ON HALT (F2 face 3): the release is
 *     behind the existing flop, so the top needs no combinational prog_mode
 *     mux. It costs one cycle of release latency; `gate_load_pin_safety` and
 *     the benches' load-mode counters hold the host to it.
 *   * `paddr` IS RESET (TM2): write-before-read made it invisible, and the
 *     reset removes the name from the audit's concern.
 *   * EVERY ARM REGISTER RESETS, `l_armpin` included: an X pin index would
 *     index `pin_rise` with X and poison the scheduler. DISARM ON HALT: an
 *     armed lane would otherwise fire on the previous program's edge.
 *   * The slot arrays are 2*N_LANES long, so they take their OWN loop -- the
 *     lane loop would leave every odd slot's valid bit X.
 *   * `cur_ck == l_clkpin[cur]` (PR2) holds through the clear: both go to 0.
 *   * `hz_q` all ones == every `l_hcnt` 0, because `l_hcr` clears with it.
 */

`ifdef M_SHARED_BITP
`define PE_RST_SHBITP l_bitp_shared <= {BPW{1'b0}};
`else
`define PE_RST_SHBITP
`endif

// ---- the main dispatch block --------------------------------------------
`define PE_RST_MAIN \
      st         <= ST_IDLE; \
      jitter_cnt <= {JW{1'b0}}; \
      jitter_max <= {JW{1'b0}}; \
      cur        <= {LW{1'b0}}; \
      cur_act    <= {ACT_W{1'b0}}; \
      cur_ck     <= {PINW{1'b0}}; \
      cur_ckr    <= 1'b1; \
      br_take_q  <= 1'b0; \
      hst        <= H_IDLE; \
      hl         <= {LW{1'b0}}; \
      hb         <= 4'd0; \
      hsh        <= {(HDR_BYTES*8){1'b0}}; \
      hdr_done   <= 1'b0; \
      pst        <= P_SCAN; \
      pl         <= {LW{1'b0}}; \
      prr        <= {LW{1'b0}}; \
      pbr1       <= 1'b0; \
      hz_q       <= {N_LANES{1'b1}}; \
      hl_v       <= 1'b0; \
      hl_l       <= {LW{1'b0}}; \
      paddr      <= {AW{1'b0}}; \
      rel_q      <= {N_LANES{1'b0}}; \
      pin_out    <= {N_PINS{1'b1}}; \
      pin_pp     <= {N_PINS{1'b1}}; \
      pin_inv    <= {N_PINS{1'b0}}; \
      pin_oe     <= {N_PINS{1'b0}}; \
      rx_data    <= 8'h00; \
      rx_lane    <= {LW{1'b0}}; \
      rx_push    <= 1'b0; \
      ck_pre     <= 14'd0; \
      ppc_v      <= 1'b0; \
      ppc_l      <= {LW{1'b0}}; \
      ppc_n      <= 2'd0; \
      host_pop   <= 1'b0; \
      for (i = 0; i < N_LANES; i = i + 1) begin \
        l_pin[i]       <= {PINW{1'b0}}; \
        l_clkpin[i]    <= {PINW{1'b0}}; \
        l_order[i]     <= 1'b0; \
        l_mode[i]      <= 1'b0; \
        l_tx[i]        <= 8'h00; \
        l_txv[i]       <= 1'b0; \
        l_rx[i]        <= 8'h00; \
        l_loop[i]      <= 8'h00; \
        tx_bitp[i]     <= {BPW{1'b0}}; \
        rx_bitp[i]     <= {BPW{1'b0}}; \
        l_ckph[i]      <= CK_LOW; \
        l_ckbit[i]     <= {BPW{1'b0}}; \
        l_ckwait[i]    <= 1'b0; \
        l_ckpark[i]    <= 1'b0; \
        l_ckwdog[i]    <= 7'd0; \
        l_cksamp[i]    <= 1'b0; \
        l_ckgot[i]     <= 1'b0; \
        l_hcr[i]       <= {HOLDW{1'b0}}; \
        l_hval[i]      <= 1'b0; \
        l_hoe[i]       <= 1'b0; \
        `PE_RST_SHBITP \
        l_timestamp[i] <= {TS_W{1'b0}}; \
        l_half[i]      <= 1'b0; \
        l_clkinv[i]    <= 1'b0; \
        l_d[i]         <= {D_W{1'b0}}; \
        l_t[i]         <= {DLY_W{1'b0}}; \
        l_live[i]      <= 1'b0; \
        l_pc[i]        <= {AW{1'b0}}; \
        l_base[i]      <= {AW{1'b0}}; \
        l_fpc[i]       <= {AW{1'b0}}; \
        l_sel[i]       <= 1'b0; \
        l_armed[i]     <= 1'b0; \
        l_armpin[i]    <= {PINW{1'b0}}; \
        l_armedge[i]   <= 1'b0; \
        l_notmo[i]     <= 1'b0; \
      end \
      for (i = 0; i < NSLOT; i = i + 1) begin \
        l_act[i]  <= {ACT_W{1'b0}}; \
        l_actv[i] <= 1'b0; \
      end

// ---- the keep-list: POWER-ON ONLY (status the host reads after halting) --
`define PE_RST_KEEP \
      sticky_ovr_m      <= 1'b0; \
      config_err_m      <= 1'b0; \
      clk_stretch_err_m <= 1'b0; \
      lane_underrun_m   <= {N_LANES{1'b0}}; \
      lane_overflow_m   <= {N_LANES{1'b0}}; \
      for (i = 0; i < N_LANES; i = i + 1) l_timeout_m[i] <= 1'b0;

// ---- the other blocks, one macro each -------------------------------------
`define PE_RST_NOW    now <= {TS_W{1'b0}};
`define PE_RST_SCHED \
      for (ti = 0; ti < N_LANES; ti = ti + 1) key_q[ti] <= {TS_W{1'b0}}; \
      winner_q   <= {LW{1'b0}}; \
      winner_v_q <= 1'b0;
`define PE_RST_PRIMED primed_q <= 1'b0;
`define PE_RST_PORT \
      s_re      <= 1'b0; \
      s_raddr   <= {AW{1'b0}}; \
      s_wre     <= 1'b0; \


// ---- MUST-FIRE MUTANTS: re-assert a register's own value AFTER the halt
// clear (the last nonblocking assignment wins), so the list itself is never
// edited by a mutant.
// ⭐ RESET-NETWORK HALT: the halt IS the reset branch now, so the mutants sit
// at its end GUARDED BY `por_n` -- they keep their register across a HALT
// (the defect each must-fire names) but never at power-on, where keeping an
// unreset value would make the bench die of X, a wrong reason.
// ⛔ THE CLEAN BUILD EXPANDS TO NOTHING: an `if (por_n)` around the lane loop
// in an async reset branch is NOT synthesisable (yosys PROC_ARST: "async
// reset yields non-constant value for signal i") -- iverilog accepted it,
// the netlist build refused it. So the guard exists only in a mutant build.
`ifdef M_NO_RELOAD_RESET
`define PE_ANY_HALT_MUT
`endif
`ifdef M_HALT_KEEP_CKBIT
`define PE_ANY_HALT_MUT
`endif
`ifdef M_HALT_KEEP_HOLD
`define PE_ANY_HALT_MUT
`endif
`ifdef M_NO_HALT_IDLE
`define PE_ANY_HALT_MUT
`endif
`ifdef PE_ANY_HALT_MUT
`define PE_HALT_MUTANTS \
      if (por_n) begin \
        for (i = 0; i < N_LANES; i = i + 1) begin \
          `PE_MUT_RELOAD_RESET \
          `PE_MUT_CKBIT \
          `PE_MUT_HOLD \
        end \
        `PE_MUT_HALT_IDLE \
      end
`else
`define PE_HALT_MUTANTS
`endif

`ifdef M_NO_RELOAD_RESET
`define PE_MUT_RELOAD_RESET l_txv[i] <= l_txv[i]; tx_bitp[i] <= tx_bitp[i]; rx_bitp[i] <= rx_bitp[i];
`else
`define PE_MUT_RELOAD_RESET
`endif
`ifdef M_HALT_KEEP_CKBIT
`define PE_MUT_CKBIT l_ckbit[i] <= l_ckbit[i];
`else
`define PE_MUT_CKBIT
`endif
`ifdef M_HALT_KEEP_HOLD
`define PE_MUT_HOLD l_hval[i] <= l_hval[i]; l_hoe[i] <= l_hoe[i]; l_hcr[i] <= l_hcr[i];
`else
`define PE_MUT_HOLD
`endif
`ifdef M_NO_HALT_IDLE
`define PE_MUT_HALT_IDLE pin_out <= pin_out;
`else
`define PE_MUT_HALT_IDLE
`endif

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
    // ⛔⛔⛔ SDA DATA HOLD ACROSS THE SCL FALL -- UM10204's DEVICE-INTERNAL
    // REQUIREMENT, AND A MEASURED VIOLATION BEFORE THIS EXISTED. A clocked LOW
    // dispatch drove the data pin and took the clock pin low IN THE SAME
    // CYCLE, so the data hold was ZERO: measured t_HD;DAT = 0 over 1719, 696
    // and 296 transitions on the clocked image, AND over 266 on the CERTIFIED
    // two-action frame, which has the same shape. UM10204 Table 10 tabulates
    // t_HD;DAT min = 0 ns, so 0 meets the TABLE -- but the table's own note
    // requires a device to internally provide >= 300 ns (15 cycles at 50 MHz)
    // so SDA bridges the undefined region of SCL's falling edge.
    // ⚠ THE HAZARD IS CONCRETE, NOT A FORMALITY: SCL takes up to 300 ns (Fm)
    // to fall through a receiver's undefined region. If SDA moves in the same
    // cycle we pull SCL low, a receiver can see SDA change while it still
    // reads SCL high -- which is a START or a STOP. On a FRAM that aborts the
    // transfer at best and corrupts the write at worst.
    // ⭐ ONE GLOBAL CONSTANT, NO ENCODING BITS: `ACT_FIELDS` is 24 of 24 bits
    // and nothing is spare, so this is a build parameter rather than a field.
    // ⭐ A PARAMETER AND NOT AN `ifdef` so both must-fires are ordinary builds:
    // `-GSDA_HOLD=0` restores the measured defect, and a too-large hold runs
    // past `t_VD;DAT`. ⚠ IT MUST STAY BELOW THE LANE'S `d`, or a hold would
    // still be pending when the next action drives the same pin; the mode
    // floors (Fm+ 25) all clear 15 with room.
    // ⛔⛔ OPEN-DRAIN ONLY, AND THAT IS SCOPE RATHER THAN CONVENIENCE. The
    // requirement is UM10204's, which is I2C, which is open-drain. A push-pull
    // SPI lane's setup and hold are governed by the PART's SPI AC table -- the
    // same table the SPI-tx lane's `D_tol = 23` is already derived from -- and
    // SPI changes data on a clock edge BY DESIGN, with no undefined-region
    // START/STOP hazard to bridge. Charging an I2C hold to an SPI lane would
    // be applying one standard's rule to another standard's wire.
    // ⚠ WHAT MADE ME CHECK THE SCOPE: with the hold applied unconditionally,
    // the PUSH-PULL control image grew eight 15-cycle clock-low phases that
    // the zero-hold build does not have. The hold's direct effect was exactly
    // the intended 15 cycles on the DATA pin, and the clock pin's release
    // pattern was identical in both builds (17 transitions), so the phase of
    // an action-boundary artifact had shifted rather than anything breaking.
    // ⭐⭐ THAT INTERACTION IS NOW EXPLAINED, AND IT WAS A PIN-MAP ARTEFACT OF
    // THE STRESS IMAGE RATHER THAN A PATH IN THIS LOGIC. `MISO_PIN = 7` and
    // `CS_PIN = 6`, and `project.v`'s boundary OVERRIDES `uio_oe[MISO_PIN]`
    // with the SPI target's `miso_oe_q` -- the engine's clock write to that pin
    // never reaches the pad. `build_ckfive` declares lane 3 on pin 6 / clkpin 7,
    // colliding with both, which it is allowed to do only because it says of
    // itself that it is NOT a pin-map-legal program. So the hold delayed that
    // lane's DATA pin, which IS the target's chip select; the delayed CS edge
    // moved when the target drove MISO; and `uio_oe[7]` followed by exactly the
    // hold's 15 cycles. ⛔ MEASURED, not argued: the hold expiry writes pins
    // 0, 2, 4 and 6 and NEVER pin 7, the per-dispatch streams of the two builds
    // are byte-identical (3571 records), and rand-reset +0 and +2 agree -- so
    // it is neither a scheduling effect nor an initialisation one.
    // ⇒ The open-drain scoping therefore stands on UM10204 alone, which is
    //   where it always belonged; it was never load-bearing for this effect.
    // ⭐⭐ EXPRESSED AS A TIME, NOT A CYCLE COUNT, and that is the honest
    // form: the requirement is 300 ns, and "15 cycles" is only correct at
    // 50 MHz. `part1_param_contract` flags a bare protocol constant in the
    // RTL -- correctly, since 15 is one -- and writing the ns requirement with
    // the clock period makes the cycle count DERIVED and the design portable
    // to another clock rate without editing a magic number.
    parameter integer SDA_HOLD_NS   = 300,
    // ⛔⛔ RULING W1: t_SU;DAT, the SETUP that follows the hold. A lane may not
    // dispatch again until its held SDA change has landed AND this long has
    // passed, so the next SCL release always finds SDA settled. ONE global
    // constant covering the strictest declared mode: Fm+ is 50 ns (UM10204
    // Table 10), 3 cycles at 50 MHz. Sm (250) and Fm (100) are mode floor
    // business (`pe_asm.check_mode_floor`); silicon guarantees the strictest.
    parameter integer SDA_SETUP_NS  = 50,
    parameter integer CLK_PERIOD_NS = 20,
    parameter integer TS_W    = 16,
    parameter integer DLY_W   = 10,
    parameter integer D_W     = 8,
    // ⭐⭐ SLOTS PER LANE -- the action buffer depth, 2 = double, 1 = single.
    // ⛔ WHY IT IS A PARAMETER AND NOT A MUTANT `ifdef`. The single-buffer
    // configuration is a DESIGN ALTERNATIVE that has to be measured against
    // the shipped one, not a defect to be killed. It was previously neither:
    // `NSLOT = 2 * N_LANES` was fixed in this file, so the stored
    // single-buffer sweep (`SWEEP_SINGLE`) described a configuration with no
    // build option at all -- a recorded measurement that could not be
    // reproduced even in principle, while the double buffer's advertised
    // "11 -> 7" benefit was computed from it. A parameter puts both
    // configurations in the parametric contract where either can be built and
    // measured. An `ifdef` would have left the alternative un-buildable by
    // anything except a mutation run, which is the wrong frame for a
    // 169-flop decision.
    // ⛔⛔ THE CLOCK-STRETCH FAULT BOUND, and it is a BUS-FAULT detector rather
    // than a stretch limit. A peer may hold SCL low for as long as it likes
    // (UM10204 sets NO limit) and the lane parks on the observed rise; but a
    // peer that VANISHES, or a bus whose clock never rises at all, would park
    // the lane FOR EVER. Past the bound the lane HALTS and `clk_stretch_err`
    // is raised -- the same "a timeout means ERROR, never success" rule
    // `OP_ARM` follows.
    // ⛔⛔ THE DEFAULT IS THE **SMBus BUS-FAULT FIGURE**, and the first one was
    // WRONG BY THREE ORDERS OF MAGNITUDE. It was 1023 cycles -- about 20 us at
    // 50 MHz -- which would declare a bus fault on LEGITIMATE devices: real
    // peripherals (sensors, microcontroller-based targets) stretch for
    // MILLISECONDS. SMBus is the published standard for "this bus is stuck"
    // and puts it at 25-35 ms, so 35 ms is the number: 1,753,088 cycles at
    // 50 MHz, which is 107 ticks of a 16384-cycle prescaler.
    // ⭐ A SHARED PRESCALER, NOT FIVE WIDE COUNTERS. 35 ms needs 21 bits, and
    // five of those is 105 flops; a 14-bit prescaler shared across lanes plus
    // a 7-bit per-lane tick counter is 49. The prescaler costs granularity
    // (0.33 ms) which is irrelevant to a 35 ms fault bound.
    // ⚠ BOTH ARE BUILD PARAMETERS so a bench can SHORTEN the prescaler and
    // reach the fault in a few hundred cycles instead of simulating 1.75
    // million -- which is how `corpus_i2c_sclfault` exercises the halt without
    // a minute of wall clock. A fault detector nothing ever triggers has
    // unknown strength.
    // ⭐ FOUND BY CI, not by reasoning: the cocotb bench held `uio_in` CONSTANT,
    // so a released SCL never TRANSITIONED and `pin_rise` never fired. Two
    // open-drain tests hung. A dead board does the same thing.
    parameter integer CK_STRETCH_PRE = 16384,   // cycles per watchdog tick
    parameter integer CK_STRETCH_TO  = 107,     // ticks before a bus fault
    parameter integer SPL     = 2
) (
    input  wire                 clk,
    // ⭐ CANARY (reset-network halt, Wilson): `rst_n` is now POWER-ON OR HALT
    // -- a single flop's Q in the top (async-cleared by the synchronised
    // power-on reset, set/cleared synchronously from the run condition), so
    // no gate sits on the reset net. `por_n` is power-on ONLY: it resets the
    // keep-list twins, the status that must survive a halt.
    input  wire                 rst_n,
    input  wire                 por_n,
    input  wire                 run,          // 1 = executing, 0 = load/halt

    // program store, shared with the loader
    output reg  [AW-1:0]        s_raddr,
    output reg                  s_re,
    input  wire [7:0]           s_rdata,
    // ⭐ the WIDE action fetch: one registered cycle for a whole action word
    // ⭐ v2 slack recovery step 2 (Wilson 10-27): ONE COPY OF THE REFILL READ
    // ADDRESS PER STORE BANK, bank k at [k*AW +: AW] (ACT_BYTES copies,
    // INLINED as s_wrdata's width is). The single register drove every
    // bank's 128:1 row mux through a 17-buffer tree, the canary's worst
    // family (+2.10 ns). Zero latency: each copy loads `paddr` at P_REQ, as
    // the one register did; (* keep_hierarchy *) pe_dup_ffe stops opt_merge.
    output wire [((5+((N_PINS<=2)?1:(N_PINS<=4)?2:(N_PINS<=8)?3:(N_PINS<=16)?4:5)+1+DLY_W+4+2+4+2+7)/8)*AW-1:0] s_wraddr_bk,
    // ⭐ v2: the store is WORD-organised (4 byte banks), so a wide read is one
    // word address -- the TM2 per-byte address registers (`s_wraddrk`) went
    // with the byte-wide array they existed for.
    output reg                  s_wre,
    // = ACT_BYTES*8, INLINED (see host_lane): OP_W + PINW + 1 + DLY_W + BPW +
    // BQW + PINB_W + MOD_W, rounded up to bytes
    input  wire [((5+((N_PINS<=2)?1:(N_PINS<=4)?2:(N_PINS<=8)?3:(N_PINS<=16)?4:5)+1+DLY_W+4+2+4+2+7)/8)*8-1:0] s_wrdata,

    // pin interface. ⭐ Both outputs are REGISTERED (ruling F2): every engine
    // driven bit comes from a flop, because a glitch on a clock pin is an extra
    // edge and an extra edge is a corruption, not a margin problem.
    output reg  [N_PINS-1:0]    pin_out,
    output reg  [N_PINS-1:0]    pin_oe,
    // CE2: 1 = this pin is a CLK_INV lane's clock -- the TOP inverts it at the
    // `uo_out` register (a flop; set only at header load, static in run)
    output reg  [N_PINS-1:0]    pin_inv,
    // ⭐ OPTION 1' (Wilson): 1 = some lane's header declares this pin its
    // CLOCK. The top holds these pads back one cycle at the halt, so every
    // other output (CS among them) goes idle first. Read from `l_clkpin`, the
    // same registers that gate CLK_INV -- no new header field.
    output wire [N_PINS-1:0]    pin_isck,
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
    // ⛔ PORTABILITY (FPGA bring-up): `LW` is a BODY localparam, so naming it
    // here is a use before its declaration -- Vivado refuses the class and a
    // strict front end (slang) rejects it. The expression is `LW`'s, INLINED,
    // as `s_wrdata` inlines PINW's; `model/gate_slang_lint.py` holds the two
    // texts equal so they cannot drift.
    output wire [((N_LANES <= 2) ? 1 : (N_LANES <= 4) ? 2 : (N_LANES <= 8) ? 3 : 4)-1:0] host_lane,
    // ⭐ WHICH QUEUE the consuming action names. The lane index is exported
    // only for diagnostics now; the ROUTING is by queue.
    output wire [1:0]           host_q,
    output wire [N_LANES-1:0]   lane_underrun,
    output wire [N_LANES-1:0]   lane_overflow,
    output wire                 sticky_ovr,
    output reg                  cfg_err,
    // ⭐ ITS OWN STATUS BIT rather than folding into `cfg_err`: a config error
    // means THE PROGRAM is wrong and the lane is halted; this means THE PEER
    // was late. A host that cannot tell them apart can act on neither.
    output reg                  clk_stretch,

    // RX payload out to the serialiser (which is NOT a lane -- zero budget)
    output reg  [7:0]           rx_data,
    // RX LANE IDENTITY. `rx_data`/`rx_push` were engine-wide with no way to
    // say WHICH lane completed the byte, so a host with two receiving lanes
    // could not attribute one -- the mirror image of the TX queue-tag problem
    // that per-lane queues solved, and found the same way: by feeding the
    // channel and watching the arithmetic fail to add up (50 bytes delivered
    // where 40 were assembled, the difference being exactly the other lane's).
    // REGISTERED ALONGSIDE `rx_data`, not derived from `cur` downstream:
    // `rx_push` is a pulse that goes high the cycle AFTER the writeback that
    // completes the byte, and `cur` is free to change before anyone reads it.
    // A consumer sampling `cur` at the pulse would be reading whichever lane
    // the scheduler moved to -- right most of the time, which is the worst
    // kind of wrong.
    output reg  [((N_LANES <= 2) ? 1 : (N_LANES <= 4) ? 2 : (N_LANES <= 8) ? 3 : 4)-1:0] rx_lane,   // = LW, inlined (see host_lane)
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
  // ⭐⭐ v2 STEP 2 (Wilson ruling on design 5cf27c1f): THE 32-BIT WORD.
  // op 3 -> 5 bits (v1's eight keep their values), + PINB (a second pin) and
  // MOD (two per-action modifiers) at the bottom. RESERVED opcodes 8..31 are
  // refused by the assembler and given NO behaviour here until a primitive
  // step builds one. LOWX = the bits below the v1 fields.
  localparam integer OP_W   = 5;
  localparam integer PINB_W = 4;
  localparam integer MOD_W  = 2;
  localparam integer LOWX   = PINB_W + MOD_W;
  localparam integer ACT_W = OP_W + PINW + 1 + DLY_W + BPW + BQW + PINB_W + MOD_W;
  // header `base` is a WORD INDEX (v2), so the header does not grow with AW
  localparam integer BASE_W = 8;

  // ---- opcodes. ⭐ Eight, which is exactly the 3-bit field: level, shift,
  // shift-in, read-bit, start, stop, arm, no-op re-arm.
  localparam [OP_W-1:0] OP_LEVEL   = 0;
  localparam [OP_W-1:0] OP_SHIFT   = 1;
  localparam [OP_W-1:0] OP_SHIFTIN = 2;
  localparam [OP_W-1:0] OP_READBIT = 3;
  localparam [OP_W-1:0] OP_START   = 4;
  localparam [OP_W-1:0] OP_STOP    = 5;
  localparam [OP_W-1:0] OP_ARM     = 6;
  localparam [OP_W-1:0] OP_REARM   = 7;
  // ⭐ v2 PRIMITIVE 1 (Wilson 10-26/27, option A): BRANCH ON BIT. `pin` = the
  // bit sampled (as READBIT samples it), `level` = the TAKEN value,
  // `delay[6:0]` = the ABSOLUTE target word. ZERO-TIME: its writeback adds 0
  // to the timestamp. OPTION A: nothing is prefetched past a branch head, so
  // the successor is fetched at the branch's writeback from the chosen PC --
  // at most one refill per retired action still holds.
  localparam [OP_W-1:0] OP_BRANCH_BIT = 8;
  // ⭐ v2 primitive 2: CMP_BRANCH (9) -- the same timed branch, its condition
  // a compare of the lane's received byte (in WIRE order) with an immediate
  // under a mask. 8 and 9 differ ONLY in bit 0, so "is a branch" is ONE
  // compare on a_op[4:1] (the a_op family the canary named) and bit 0
  // picks the condition.
  localparam [OP_W-1:0] OP_CMP_BRANCH = 9;
  // ⭐ v2 primitive 2, bundle 2: LOOP (10) -- repeat a body n times, the same
  // timed branch with a per-lane counter. 8..11 share a_op[4:2] = 3'b010
  // (11 is reserved and refused at load), so "is a branch" stays ONE
  // compare and a_op[1:0] picks BIT / CMP / LOOP.
  localparam [OP_W-1:0] OP_LOOP       = 10;

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
  // ⭐ +1 FOR `order`, THE LAST SPARE BIT (ruling 1). The header was 47 bits
  // inside 6 bytes with one spare at the bottom; the per-lane bit-order bit
  // takes it, so the word is now exactly 48 of 48 and FULL.
  // ⛔ `gate_one_encoder.py` IS WHAT CAUGHT THIS BEING STALE: `pe_isa.py` was
  // updated to 48 and this line still said 47, and the gate exists precisely
  // to refuse two definitions of one layout. It compares both elaborators and
  // the Python encoder, which is why a one-line omission in the RTL could not
  // slip through as "the images still load".
  localparam integer HDR_BITS  = PINW + PINW + 1 + DLY_W + CW + D_W + D_W
                                 + BASE_W + 1;
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
  // ⛔ v2: bytes HDR_REGION..+1 are the image's 16-bit MAGIC + version (the
  // loader checks it in project.v); word 0 starts after it, word-aligned
  localparam integer MAGIC_BYTES = 2;
  localparam integer ACT_BASE  = N_LANES * HDR_BYTES + MAGIC_BYTES;
  // BRANCH_BIT's target: a WORD index into the action region. BR_NWORDS words
  // fit the store; a target >= BR_NWORDS (which includes any of delay[9:7]
  // set) is refused at dispatch -- config_err, the lane halts.
  localparam integer BR_NWORDS = ((1 << AW) - ACT_BASE) / ACT_BYTES;
  localparam integer BR_W      = AW - $clog2(ACT_BYTES);
  // BRANCH_BIT's WAIT W (Wilson 10-27, R2b): count:pinb, >= D* + B. The
  // successor releases W after the branch, so its refill has a window
  // (option A fetches nothing past a branch head). pe_isa.BR_W_MIN mirrors it.
  // 32 -> 33 (measured, 10-28): + the winner-registration cycle; pe_isa.BR_W_MIN
  localparam integer BR_W_MIN  = N_LANES * 4 + (N_LANES - 1) * 3 + 1;   // 33
  generate
    if ((ACT_BASE % ACT_BYTES) != 0) begin : g_act_aligned
      ACTION_REGION_NOT_WORD_ALIGNED _static_assert ();
    end
  endgenerate

  // =====================================================================
  // PER-LANE STATE
  // =====================================================================
  reg [PINW-1:0]  l_pin    [0:N_LANES-1];   // data pin / armed pin
  reg [PINW-1:0]  l_clkpin [0:N_LANES-1];   // ⭐ a LANE property; the per-ACTION
                                            //   copy was cut by S2 as a duplicate
  // ⭐ OPTION 1': which pins are some lane's declared clock (see `pin_isck`)
  genvar gck;
  generate
    for (gck = 0; gck < N_PINS; gck = gck + 1) begin : g_isck
      reg isck;
      integer lk;
      always @(*) begin
        isck = 1'b0;
        for (lk = 0; lk < N_LANES; lk = lk + 1)
          if (l_clkpin[lk] == gck[PINW-1:0]) isck = 1'b1;
      end
      assign pin_isck[gck] = isck;
    end
  endgenerate
  reg             l_mode   [0:N_LANES-1];   // 0 = open-drain, 1 = push-pull
  // BIT ORDER, PER LANE, FROM THE HEADER'S LAST SPARE BIT (ruling 1).
  //     0 = LSB first -- UART, and the engine's original behaviour
  //     1 = MSB first -- I2C and SPI mode 0
  // The shift path is UNCHANGED and still walks `l_tx[0]` outward; what the
  // bit selects is whether the byte is REVERSED as it is loaded, and whether
  // a received byte is reversed as it completes. A reversal at the two load
  // points is a pair of muxes; reversing the shift path itself would have
  // meant two shift directions in the dispatch arm.
  // WHY PER LANE AND NOT PER ACTION: a lane runs one protocol. Per action it
  // would be the same answer repeated for every action, and the action word
  // has no spare bit anyway (ACT_W is 24 of 24).
  // IT WAS AN UNSTATED GLOBAL BEFORE, and `pe_isa.py` documented the opposite
  // of what this file did. Nothing decoded the wire against a standard, and
  // the one byte checked end to end (0x5A) is a bit-reversal PALINDROME.
  reg             l_order  [0:N_LANES-1];

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
  reg              config_err_m;            // sticky: 1.6s violation (see twins)
  // sticky: a clocked SHIFTIN consume point found no captured bit -- the peer
  // held the clock past this lane's next dispatch. ⛔ IT IS NOT A PROGRAM
  // ERROR: a slow peer is legal. It says the bit REPORTED WAS NOT SAMPLED,
  // which for an ACK is the difference between "acknowledged" and "never
  // answered" -- and the substituted 0 reads as the former.
  reg              clk_stretch_err_m;
  // ⛔⛔⛔ TX AND RX HAVE SEPARATE STATE, AND THEY USED TO SHARE IT. Ruling 1
  // after `beb8862`, and the defect it fixes is the one T5.1's host-channel
  // audit uncovered: on a lane that mixes `OP_SHIFT` (transmit) with
  // `OP_SHIFTIN` (receive) -- which is every half-duplex protocol we ship --
  // the two directions corrupted each other through BOTH shared objects:
  //
  //   the POINTER. `OP_SHIFTIN`'s byte-complete resets it at `a_cnt - 1`,
  //   which always fires BEFORE `OP_SHIFT`'s host byte load at `a_cnt`. So
  //   the TX load was UNREACHABLE: measured on `corpus_i2c`, 124 OP_SHIFT
  //   dispatches produced 0 loads and 0 underruns -- no byte was ever even
  //   REQUESTED. Every I2C and SPI-master result in this project's history
  //   exercised the shift mechanics without ever sending a real byte.
  //
  //   the REGISTER. `OP_SHIFTIN` inserts the sampled bit at bit 7 of the very
  //   register `OP_SHIFT` is draining from bit 0, so an ACK read rewrites the
  //   byte in flight and a transmit shift disturbs the word being received.
  //   ⚠ THE RULING NAMED THE POINTER; THE REGISTER HAD TO GO WITH IT. Splitting
  //   only the pointer would have made the TX load fire and then deliver
  //   corrupted data -- a worse failure than the unreachable one, because it
  //   produces plausible bytes instead of none.
  //
  // ⭐ THE INVARIANT IS NOW STRUCTURAL: no opcode writes the other direction's
  // state, by construction, so there is nothing to reason about per program.
  // That is why this shape was chosen over a combined shift-exchange action --
  // which would also have needed an encoding bit the action word does not have
  // (ACT_W is exactly 24 of 24 bits).
  // ⛔ `M_SHARED_BITP` re-merges the pointers so the defect is PRICED.
  // COST: 40 flops for `l_rx` plus 20 for `rx_bitp`, 60 total.
  // =====================================================================
  // THE SELF-CLOCKED SHIFT (ruled Option C), BUILT FROM THE GOLDEN MODEL
  // `model/clocked_phase.py`. A SHIFT or SHIFTIN whose lane has a REAL clock
  // pin AND whose action carries `level = 1` drives BOTH clock phases itself,
  // so ONE ACTION CARRIES A WHOLE BYTE: 20 actions per I2C wire byte become 2,
  // which brings a full FRAM write (291 bytes) and a random read (360) inside
  // the 256-byte store at 75 and 90.
  //
  // ⛔⛔ WHY `level` AND NOT A NEW BIT OR OPCODE: there is none. Measured --
  // ACT_FIELDS is 24 of 24 bits, HDR_FIELDS 48 of 48, all 8 opcodes used.
  // Reuse was FORCED. And `level` is the right field rather than merely the
  // available one: on a self-clocked shift "the clock level to write this
  // dispatch" is vacuous, because the action writes both levels. ⛔ With NO
  // real clock pin, `level` keeps its exact old meaning -- which is what
  // leaves every UART lane untouched, and why the six certified and
  // measurement-base images stay bit-identical.
  //
  // THE PHASE MACHINE, AND IT IS THE MODEL'S, NOT A SECOND DESIGN:
  //     SHIFT    LOW (drive the bit, clock low, count it) -> HIGH (clock high)
  //              ... n times, retire on the last HIGH.           2n dispatches
  //     SHIFTIN  LOW (release data, clock low) -> HIGH (clock high, ARM the
  //              capture) ... n times, then ONE trailing COLL.  2n+1 dispatches
  //
  // ⛔⛔⛔ THE +1 IS FORCED, NOT A CHOICE. The bit must be sampled on the
  // OBSERVED clock rise, so a stretching peer is read when it answers rather
  // than when we guessed. That rise lands AFTER the high phase's writeback, in
  // the idle window following it -- so at the instant 2n dispatches have
  // elapsed the last bit DOES NOT EXIST YET. For n > 1 the intermediate bits
  // cost nothing extra: bit k is consumed at bit k+1's LOW phase. Only the
  // last bit has no successor, so the cost is +1 per ACTION, not per bit.
  // ⚠ WAITING for the rise inside a dispatch is the stall this design refuses
  // everywhere ("underrun is a STICKY FLAG, NEVER A STALL: a stall would make
  // C unbounded"), so the high phase ARMS a capture and returns. The tolerance
  // is therefore ONE LANE PERIOD: a rise later than the next dispatch of that
  // lane loses its bit, and `clk_stretch_err` is what says so.
  //
  // ⛔⛔ THE PHASE IS RESET AT EVERY ACTION START, and that is the whole
  // defect of the first attempt. Per-lane ownership was never wrong -- a lane
  // runs one action at a time, in order -- but a new action INHERITED the
  // previous one's leftover phase, so a clocked SHIFTIN following a clocked
  // SHIFT started mid-sequence and retired after one dispatch, sampling
  // nothing. Layer B of the bench watchdog caught it against the model: "op=1
  // cnt=7 took 1 dispatch, the model says 16". The reset is written at the
  // RETIRE, which IS the next-action load, so it cannot be forgotten by a
  // later arm.
  localparam [1:0] CK_LOW  = 2'd0;
  localparam [1:0] CK_HIGH = 2'd1;
  localparam [1:0] CK_COLL = 2'd2;
  reg [1:0]       l_ckph   [0:N_LANES-1];   // the phase this lane is in
  // ⛔ A DEDICATED BIT COUNTER, and it is NOT redundant with `tx_bitp`: the
  // host-byte load fires on the last bit's LOW phase and RESETS `tx_bitp` to
  // zero, so by the following HIGH it can no longer say which bit this was.
  // Counting the action's own progress is the only thing that survives it.
  reg [BPW-1:0]   l_ckbit  [0:N_LANES-1];
  reg             l_ckwait [0:N_LANES-1];   // a capture armed on the rise
  // ⭐ parked for a CLOCK phase rather than for a program's `OP_ARM`, so a
  // stretch fault can be told from a peer-silent ARM timeout when the bound
  // lands.
  reg             l_ckpark [0:N_LANES-1];
  // the parked-TICK count, per lane. ⚠ 49 flops all told, which is the price
  // of not hanging on a dead bus.
  reg [6:0]       l_ckwdog [0:N_LANES-1];   // ticks, not cycles
  // ⭐ ONE prescaler for every lane. It advances whenever ANY lane is parked,
  // which is sound for a FAULT bound: it can only make the bound fire up to
  // one tick EARLY for a lane that parked mid-prescale, and 0.33 ms of
  // jitter on a 35 ms fault detector decides nothing.
  reg [13:0]      ck_pre;
  // ⛔⛔ SILICON FIX #3 PART (b) (ruling CI1): THE PUSH-PULL CAPTURE SLOT. A
  // push-pull clock cannot be stretched, so a clocked SHIFTIN on one must
  // not wait for an OBSERVED rise -- and on a `uo_out` clock (the SPI master's
  // SCLK) there is nothing to observe: `uo_out` has no input path and its
  // `pin_rise` is tied low, so the capture NEVER fired and every received byte
  // read 0. The engine raised that edge itself, so it captures at a known
  // cycle instead: the HIGH phase's writeback loads this slot, which fires
  // when `pin_in` shows the data pad AS IT STOOD AT THE CLOCK PAD'S RISE (CI2:
  // rise + the 2-cycle input path seen from here; the `uo_out` pad rises one
  // cycle later than a `uio` pad, behind its output register). ONE SLOT, 6
  // flops: dispatches are >= C = 3 cycles apart and the slot fires within
  // 2 cycles of its writeback, so it is free again before the next one.
  reg             ppc_v;
  reg [LW-1:0]    ppc_l;
  reg [1:0]       ppc_n;
  // declared AHEAD of first use (portability: declare-before-use, slang lint)
  wire [N_LANES-1:0] ck_parked; // packed view of `l_ckpark`, for the shared
                               // prescaler's enable
  wire            ck_any_park = |{ck_parked};
  wire            ck_tick = ck_any_park & (ck_pre >= CK_STRETCH_PRE[13:0] - 14'd1);
  reg             l_cksamp [0:N_LANES-1];   // the bit latched AT the rise
  reg             l_ckgot  [0:N_LANES-1];   // ... and it is unconsumed
  // ⛔⛔ THE SDA HOLD PIPELINE (ruling H). A dispatch that takes the clock pin
  // LOW no longer writes the data pin: it LOADS the value here, and the pin is
  // written `SDA_HOLD` cycles later. The clock still moves immediately, so the
  // data change lands AFTER the fall, which is the whole requirement.
  // ⭐⭐ THE HOLD BECOMES THE ONLY WRITER FOR THAT PATH, which is what makes it
  // safe: with the direct write removed there is no same-cycle race between a
  // dispatch and an expiry for the data pin, and no second always block (a
  // second writer of `pin_out` would be N_PINS multiple-driver nets -- the
  // defect that made this engine unsynthesizable once while simulating fine).
  // ⭐ THE PIN INDEX IS **NOT** STORED: the lane's data pin is already in
  // `l_pin[i]`, which a held action cannot change (it retires nothing). Storing
  // it would have cost another PINW bits per lane for a value already in a
  // register -- the same reasoning as `ck_dly` reading the head slot.
  // ⇒ COST: SDA_HOLD = 15 needs HOLDW = 4, so 4 + 1 + 1 = 6 bits per lane and
  //   30 flops at N_LANES = 5. Measured against the alternative of storing the
  //   pin index too, which would have been 50.
  // ceil(SDA_HOLD_NS / CLK_PERIOD_NS) -- a minimum is not met by rounding down
  localparam integer SDA_HOLD = (SDA_HOLD_NS + CLK_PERIOD_NS - 1)
                                / CLK_PERIOD_NS;
  // ⛔⛔ RULING W1 -- THE SAME COUNTER CARRIES THE SETUP. It is loaded with
  // SDA_HOLD + SDA_SETUP, the pin is written when it reaches SDA_SETUP + 1
  // (SDA_HOLD cycles after the load, exactly as before), and it keeps counting
  // to 0. `ready` is gated on it reaching 0, so the lane cannot dispatch its
  // next edge -- the SCL release -- until the data has landed and settled.
  // ⭐ CONTENTION-INDEPENDENT BY CONSTRUCTION: the counter starts at the
  // dispatch that ACTUALLY happened, not the scheduled one, so a lane that was
  // dispatched late by contention is held back by exactly what it lost. A
  // constant floor on `d` cannot do that (W3), since the jitter grows with the
  // lane set. ⇒ COST: one more counter bit per lane (18 needs 5), 5 flops.
  // ⚠ AT SDA_HOLD = 0 nothing loads the counter, so nothing is gated: that
  //   build is the MEASURED defect and stays exactly that.
  localparam integer SDA_SETUP = (SDA_SETUP_NS + CLK_PERIOD_NS - 1)
                                 / CLK_PERIOD_NS;
  localparam integer SDA_HS = SDA_HOLD + SDA_SETUP;
  localparam integer SDA_SETUP1 = SDA_SETUP + 1;   // the count the pin lands at
  localparam integer HOLDW = (SDA_HS < 2)   ? 1 :
                             (SDA_HS < 4)   ? 2 :
                             (SDA_HS < 8)   ? 3 :
                             (SDA_HS < 16)  ? 4 :
                             (SDA_HS < 32)  ? 5 :
                             (SDA_HS < 64)  ? 6 : 7;
  // ⛔⛔ RULING TM1 -- THE HOLD LOAD IS REGISTERED, AND `l_hcnt` IS UNCHANGED.
  // The slow-corner worst path (117e55c: -0.074 ns, and 7 of the 10 paths
  // under the +0.5 ns bar) ran from `cur` through the DRIVE arms' `hold_ld`
  // and the `cur` decode into all 5 x HOLDW counter flops. The DRIVE arm now
  // only records the load (`hl_v` / `hl_l`, one lane, 1 + LW flops), and the
  // countdown writes `SDA_HS - 1` one cycle later. `l_hcnt` is the EFFECTIVE
  // count, a wire: the pending load reads as `SDA_HS` in exactly the cycle
  // the old register held it, so every reader -- `hz_q`, the pin landing,
  // Layer H in the benches -- sees the same value in every cycle.
  // ⭐ "LOAD WINS ONLY ON AN IDLE COUNTER" IS KEPT: the old load was overwritten
  // by the countdown's later NBA whenever the counter was still running, so
  // `hl_v` is set only when `hz_q[cur]` (== `l_hcnt[cur] == 0`) holds.
  // ⭐ ONE PENDING SLOT SUFFICES: `hold_ld` is raised in ST_DRIVE, once per
  // dispatch, and dispatches are >= C = 3 cycles apart; the slot is consumed
  // the cycle after it is set. `M_TM1_UNREG` keeps the old direct load.
  reg [HOLDW-1:0] l_hcr    [0:N_LANES-1];   // the counter REGISTER (raw)
  wire [HOLDW-1:0] l_hcnt  [0:N_LANES-1];   // cycles left before SDA may move
  reg             hl_v;                     // a hold load is pending ...
  reg [LW-1:0]    hl_l;                     // ... for this lane
  reg             l_hval   [0:N_LANES-1];   // the pending pin_out value
  reg             l_hoe    [0:N_LANES-1];   // the pending pin_oe value
  reg [7:0]       l_tx     [0:N_LANES-1];   // THE TX PAYLOAD lives here, not
                                            //   in the program (ruling F1)
  // ⛔⛔ CANDIDATE #8 (WF2): `l_txv` -- the register holds THIS byte's host
  // data. Clear at the start of every byte, so the byte's FIRST bit is taken
  // from the queue head and popped at that bit's writeback: no byte reaches
  // the wire that the host did not push (the reset 0x00 used to).
  reg             l_txv    [0:N_LANES-1];
  reg [7:0]       l_rx     [0:N_LANES-1];   // the RX accumulator
  reg [7:0]       l_loop   [0:N_LANES-1];   // LOOP's counter: 0 = idle / fresh
  reg [BPW-1:0]   tx_bitp  [0:N_LANES-1];   // advanced/reset ONLY by OP_SHIFT
  reg [BPW-1:0]   rx_bitp  [0:N_LANES-1];   // ... ONLY by OP_SHIFTIN
  // THE MUTANT'S SHARED POINTER: one for both directions, which is what
  // shipped. It is per-ENGINE rather than per-lane, deliberately -- the defect
  // being reproduced is "the two directions share a pointer", and sharing it
  // engine-wide reproduces it on any lane the bench drives while keeping the
  // arm to one declaration.
  // NOTE the comment sits OUTSIDE the `ifdef`: `gate_mutant_arms` counts any
  // comment line inside an arm as the arm wrapping more than the delta, and
  // it is right to -- a mutant whose diff is mostly prose is not a measured
  // one-line mutation.
`ifdef M_SHARED_BITP
  reg [BPW-1:0]   l_bitp_shared;
`endif
  reg [TS_W-1:0]  l_timestamp     [0:N_LANES-1];   // ABSOLUTE next-action timestamp
  // ⛔ RULING HDR: the header field that was `c` -- loaded into `l_c`, which
  // NOTHING read -- is now the lane's mode bits. bit0 HALF_HIGH (CE1), bit1
  // CLK_INV (CE2); bits 2-3 are reserved (refused by the toolchain, ignored
  // here). `l_c` is gone: it was dead state.
  reg             l_half   [0:N_LANES-1];   // CE1: the HIGH phase lasts d/2
  reg             l_clkinv [0:N_LANES-1];   // CE2: the clock pin is inverted
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
  reg             l_timeout_m[0:N_LANES-1]; // STICKY: the peer went silent

  // ⭐⭐ CANARY (reset-network halt): THE KEEP-LIST TWINS. The `_m` flags live
  // in the main block, whose reset is now power-on OR halt; each has a twin
  // here, reset at POWER-ON ONLY, that latches `twin | flag` every cycle.
  // Every reader sees `twin | flag` under the flag's old name, so a halt can
  // never erase status: a flag set before the halt is in its twin by the
  // edge the halt reset asserts on (that reset is itself a flop's Q, so the
  // twin samples the pre-reset value on that edge).
  reg             config_err_k, clk_stretch_err_k, sticky_ovr_k;
  reg [N_LANES-1:0] lane_underrun_k, lane_overflow_k, l_timeout_k;
  reg               sticky_ovr_m;
  reg [N_LANES-1:0] lane_underrun_m, lane_overflow_m;
  wire config_err      = config_err_k | config_err_m;
  wire clk_stretch_err = clk_stretch_err_k | clk_stretch_err_m;
  assign sticky_ovr    = sticky_ovr_k | sticky_ovr_m;
  assign lane_underrun = lane_underrun_k | lane_underrun_m;
  assign lane_overflow = lane_overflow_k | lane_overflow_m;
  integer kt;
  // `M_KEEP_ON_HALT`: the twins on the HALTING reset -- a reload erases the
  // status the host reads after halting (run_reload's KEEP must-fire)
`ifdef M_KEEP_ON_HALT
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
`else
  always @(posedge clk or negedge por_n) begin
    if (!por_n) begin
`endif
      config_err_k <= 1'b0; clk_stretch_err_k <= 1'b0; sticky_ovr_k <= 1'b0;
      lane_underrun_k <= {N_LANES{1'b0}}; lane_overflow_k <= {N_LANES{1'b0}};
      l_timeout_k <= {N_LANES{1'b0}};
    end else begin
      config_err_k      <= config_err_k | config_err_m;
      clk_stretch_err_k <= clk_stretch_err_k | clk_stretch_err_m;
      sticky_ovr_k      <= sticky_ovr_k | sticky_ovr_m;
      lane_underrun_k   <= lane_underrun_k | lane_underrun_m;
      lane_overflow_k   <= lane_overflow_k | lane_overflow_m;
      for (kt = 0; kt < N_LANES; kt = kt + 1)
        l_timeout_k[kt] <= l_timeout_k[kt] | l_timeout_m[kt];
    end
  end

  localparam integer NSLOT = SPL * N_LANES;
  // index width for a slot number 0..NSLOT-1
  localparam integer SIW   = (NSLOT <= 2)  ? 1 : (NSLOT <= 4)  ? 2 :
                             (NSLOT <= 8)  ? 3 : (NSLOT <= 16) ? 4 :
                             (NSLOT <= 32) ? 5 : 6;
  reg [ACT_W-1:0] l_act    [0:NSLOT-1];
  reg             l_actv   [0:NSLOT-1];
  reg             l_sel    [0:N_LANES-1];   // 0/1: which slot is the HEAD
  reg [AW-1:0]    l_fpc    [0:N_LANES-1];   // the FETCH pointer, ahead of l_pc

  // ⭐⭐ ONE EXPRESSION FOR "WHICH SLOT", IN ONE PLACE. The index
  // `ln*2 + (l_sel[ln] ? 1 : 0)` was written out at TEN separate sites, which
  // is the shape of defect this project keeps paying for: `tb_smoke`'s private
  // action-word slice, `run_local.py`'s third source list, three gates each
  // building their own pyRTA task set. Ten copies of an index cannot be made
  // depth-independent one at a time.
  // ⛔ AND THE WIDTH IS WHY IT MATTERS HERE SPECIFICALLY: with N_LANES = 5 and
  // SPL = 2 the slot index runs 0..9 and needs FOUR bits, so a 3-bit copy of
  // this expression silently aliases lane 4's slots onto lane 0's. That is
  // exactly the bug the per-lane instrument hit when it declared `l_head` as
  // [2:0].
  // ⛔⛔ WIRES, NOT A FUNCTION, AND YOSYS DECIDED THAT. A `slot_ix(ln, sel)`
  // function was the obvious form and iverilog plus the smoke bench accepted
  // it -- but `fetch_addr` and `want_fetch` are themselves functions, and the
  // Verilog-2005 frontend rejects A FUNCTION CALL INSIDE A FUNCTION BODY:
  // "Non-constant function call in constant expression". Two rounds of that
  // error, one per calling function.
  // ⇒ The index becomes a combinational wire per lane, computed in ONE place.
  //   `hix[ln]` the HEAD slot, `six[ln]` the SPARE (SPL > 1 only), `fix` the
  //   slot a refill in flight is filling.
  // ⭐ This is strictly better than the function was: there is now exactly one
  //   arithmetic site instead of one function with three call forms, and the
  //   `*2` literal that was written out at TEN sites is gone from all of them.
  //   With N_LANES = 5 and SPL = 2 the index runs 0..9 and needs FOUR bits, so
  //   a 3-bit copy aliases lane 4's slots onto lane 0's -- which is exactly
  //   the bug the per-lane instrument hit with `l_head` declared [2:0].
  genvar gs;
  wire [SIW-1:0] hix [0:N_LANES-1];
  wire [SIW-1:0] six [0:N_LANES-1];
  generate
    for (gs = 0; gs < N_LANES; gs = gs + 1) begin : g_slot
      assign hix[gs] = gs * SPL + (((SPL > 1) &&  l_sel[gs]) ? 1 : 0);
      assign six[gs] = gs * SPL + (((SPL > 1) && !l_sel[gs]) ? 1 : 0);
    end
  endgenerate

  // =====================================================================
  // GLOBAL STATE -- one incrementer, not N_LANES decrementers (Ruling 2)
  // =====================================================================
  reg [TS_W-1:0] now;
  // declared AHEAD of first use (portability: declare-before-use, slang lint);
  // their drivers stay where they were (`assign now_inc`, `assign primed`)
  wire primed;
  wire now_inc;

  // ⭐ J IS MEASURED, NOT ASSERTED. A2 ships J = 1.
  //
  // ⛔⛔ WHAT `jitter_max` IS: THE LONGEST **ANY-WINNER-BLOCKED RUN LENGTH**,
  // engine-wide, in cycles. It is NOT a per-lane jitter term, and it must not
  // be quoted as one.
  //   `jitter_cnt` is a SINGLE counter shared by all lanes. It increments
  //   whenever the CURRENT winner is blocked on its head slot, and clears only
  //   when no lane is winner or at writeback -- so if the winner CHANGES
  //   mid-stall, the count carries straight on across two different lanes'
  //   waits and reports their sum as one run. The witness ring
  //   (`test/tb_witness.v`) shows exactly that happening.
  // ⇒ It is an upper bound on any single lane's prefetch-miss wait, which is
  //   the safe direction, but it is a LOOSE one, and the earlier description
  //   ("the largest dispatch delay caused purely by a prefetch miss") read as
  //   though it were per-lane. The per-lane quantity is measured separately by
  //   `test/tb_jlane.v` against the pre-registration in
  //   `docs/PREREG_J_LANE.md`.
  // ⚠ It is also a WHOLE-RUN max, so one startup transient pins it forever --
  //   see `tb_smoke`, which splits cold start from steady state for that
  //   reason.
  localparam integer JW = 8;
  reg [JW-1:0] jitter_cnt, jitter_max;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)      `PE_RST_NOW         // CANARY: rst_n IS the halt now
    // ⭐⭐ `now` DOES NOT ADVANCE UNTIL PRIMED, and that is the half of
    // prime-before-release that actually removes the cold start. Gating only
    // DISPATCH would relocate the problem, not remove it: `now` would run on
    // through the priming refills, every lane's absolute timestamp would fall
    // behind, and the first job would be released ALREADY LATE -- the same
    // delay, now charged to the schedule instead of to start-up. Freezing the
    // clock makes the refill latency elapse before t = 0 of the schedule
    // exists, so no job's response time can contain it.
    // ⛔ M_NO_PRIME removes both halves and the bench must fail.
    // ⭐ RULING TF1: the increment condition is the wire `now_inc`, declared
    // below, so the registered readiness reads the SAME condition this block
    // advances on rather than a second copy of it.
    else if (now_inc) now <= now + 1'b1;
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
  // (`ck_parked` is declared ahead, beside its first use, `ck_any_park`)
  wire [N_LANES-1:0] ck_hit;    // a clocked SHIFTIN's rise, OBSERVED
  wire [N_LANES-1:0] ck_bit;    // ... and the data pin at that instant
  // ⭐⭐ THE PARKED LANE'S OWN ACTION DELAY, COMBINATIONAL AND ZERO FLOPS (F1).
  // The HIGH period is counted from the rise we OBSERVE, so the release after
  // a park is `rise + d` -- which needs `d` for a lane that is NOT `cur`.
  // ⛔ IT COMES FROM THE LANE'S HEAD SLOT, AND THAT IS SOUND ONLY BECAUSE A
  // HELD CLOCKED ACTION RETIRES NOTHING: `ST_WB`'s `ck_hold_eff` arm skips the
  // PC advance, the INVALIDATION and the buffer swap, so `l_act[hix[gi]]` still
  // holds the action being clocked for the whole park. Capturing `a_dly` into a
  // per-lane register instead would have cost N_LANES * DLY_W = 50 flops to
  // store a word that is already sitting in a register.
  // ⚠ THE PRECONDITION IS LOAD-BEARING, so it is named here rather than left
  // to be rediscovered: if a held action ever began invalidating its slot, this
  // would silently read the NEXT action's delay.
  wire [DLY_W-1:0] ck_dly [0:N_LANES-1];
  wire [DLY_W-1:0] ck_hdly [0:N_LANES-1];   // CE1: the HIGH length in force
  // ⛔⛔⛔ THE HOLD IS CLAMPED OUT WHEN IT WOULD NOT FIT, and this is a
  // CORRECTNESS clamp rather than a tidy-up. A hold longer than the action's
  // own delay lands the data AFTER the next clock rise -- data moving while
  // SCL is high, which to any receiver is a START or a STOP. That is a WORSE
  // defect than the zero hold it replaces, so the fix must not be able to
  // create it.
  // ⚠ MEASURED, AND IT COST A PAID TEST BEFORE THE CLAMP EXISTED: `corpus_i2c`
  // runs at d = 9, below the 15-cycle hold, and with the hold applied
  // unconditionally the I2C peer stopped decoding -- the STRETCHING peer held
  // SCL low for 242 cycles without the hold and for 0 cycles with it, so two
  // `fram_i2c` stretch branches went dark. A regression visible only because
  // the coverage debt is recorded.
  // ⭐ WHAT THE CLAMP DOES **NOT** DO: it does not make such a program
  // compliant. A lane whose delay cannot fit the hold keeps its old
  // zero-hold behaviour and `gate_um10204` reports it as BELOW the
  // requirement -- the violation stays visible instead of being converted
  // into a harder one. The honest reading is that `d <= SDA_HOLD` is not a
  // legal I2C delay; the clamp only refuses to make it worse.
  // ⛔⛔⛔ AND THAT READING IS NOW THE RULING (D1/D3). A CLOCKED open-drain
  // action with `d <= SDA_HOLD` is REFUSED, so the clamp is unreachable on the
  // clocked path and has been removed from it. ⇒ WHAT IS LEFT IS THE
  // **UNCLOCKED** SITE, and it is left deliberately: D1 is scoped to `ck_act`,
  // and an unclocked open-drain SHIFT that takes its own clock low in the same
  // dispatch (`clk_real & ~a_lvl`) is the CERTIFIED two-action frame's shape --
  // `build_i2cframe` runs it, and at a short delay it would push data past the
  // rise with nothing refusing it.
  // ⛔⛔ RULING U TOOK THAT SCOPE DECISION: the refusal (`ck_holdviol`) now
  // covers the unclocked idiom too, so the clamp had no reachable case left and
  // is RETIRED -- its wire, its per-lane compare and its term at the unclocked
  // site are gone. History above is kept because it is why the refusal exists.
  // ⛔⛔⛔ F1 -- A CLOCKED PARK COUNTS ITS HIGH PERIOD FROM THE RISE IT
  // OBSERVES, so it releases at `now + d` rather than at `now`. This is the fix
  // for a MEASURED compliance failure: rebasing a parked clocked lane to `now`
  // made the next dispatch eligible immediately, so the SCL HIGH phase was the
  // synchroniser latency and nothing else -- measured FLAT at 6 cycles while
  // the programmed delay spanned 13x (d = 9, 25, 60, 120), with t_LOW tracking
  // d exactly. UM10204 wants t_HIGH >= 13 cycles (Fm+), 30 (Fm) and 200 (Sm) at
  // 50 MHz, so the clocked scheme met NO I2C mode -- and could not be brought
  // into compliance by programming it, because the high phase was not
  // programmable at all.
  // ⭐ IT IS UM10204's OWN CLOCK-SYNCHRONISATION RULE, not an invention here: a
  // master starts timing its HIGH period when it SEES SCL high. The
  // synchroniser lag therefore only ADDS to t_HIGH (measured d + L_sync), which
  // is the safe direction for compliance.
  // ⛔ WHY NOT `max(timestamp, observed rise)`, WHICH WAS THE FIRST PROPOSAL AND
  // IS WRONG EXACTLY WHEN IT MATTERS: once the peer stretches past `d` the max
  // resolves to the rise, the next dispatch fires one synchroniser latency
  // later, and t_HIGH collapses back to ~L_sync -- right after a stretch, which
  // is the moment the rule is being tested. Counting from the rise is
  // stretch-safe at ANY stretch length.
  // ⭐ ZERO NEW ENCODING BITS: `d` is the action's existing delay field, and
  // `ACT_FIELDS` is 24 of 24 bits with nothing spare for a second duration.
  // ⚠ THE CLOCK IS THEREFORE SYMMETRIC (low = d, high = d + L_sync), so `d`
  // must clear the LARGER of the mode's two UM10204 minima, which is t_LOW.
  // ⛔⛔ AN ORDINARY `OP_ARM` STILL REBASES TO `now`, AND MUST. Ruling 1's
  // `ARM -> no-op(half) -> sample` idiom anchors UART-rx's sample grid to the
  // peer's detected edge; adding a delay there would slide the whole grid and
  // break every reactive lane. `l_ckpark` is the ONLY thing separating the two
  // cases.
  // ⛔ M_CK_RISE_ELIGIBLE restores the pre-fix behaviour so the compliance
  // checker has a must-fire: under it t_HIGH is the synchroniser latency again.
  // ⛔ M_CK_REBASE_2D releases at `rise + 2d` instead, which is the "too LATE"
  // direction. It prices A2's UPPER bound: `t_HIGH >= d` is still satisfied, so
  // G1 and the UM10204 floor both stay green while the clock period is wrong --
  // which is precisely why a one-sided bound is half a check.
  wire [TS_W-1:0] ck_rebase [0:N_LANES-1];
  // ⛔⛔ RULING CE1 -- HALF_HIGH. A symmetric clock cannot reach I2C Fm's
  // nominal rate: t_LOW >= 1.3 us fixes d >= 69 and the HIGH phase then wastes
  // the 0.7 us beyond Fm's 0.6 us t_HIGH (336 kHz). A HALF_HIGH lane's HIGH
  // phase lasts d/2 -- on an open-drain clock d/2 after the OBSERVED rise (the
  // park rebase), on a push-pull clock the HIGH-phase writeback adds d/2 --
  // so Fm runs up to ~397 kHz (ideal edges; pull-up dependent). The LOW phase
  // is untouched, so every t_LOW / hold / setup argument stands. `pe_asm`
  // refuses HALF_HIGH when d/2 < D*: J = 1's premise holds PER GAP.
  // `M_HALF_IGNORED` reads every lane as symmetric.
  wire [N_LANES-1:0] half_v;
  genvar gh;
  // ⛔ DECLARED HERE, BEFORE ITS FIRST USE (g_arm below). It was declared ~130
  // lines further down: iverilog, Verilator and yosys accepted that, Vivado
  // refused it ("generate loop index 'gi' is not defined as a genvar") and the
  // FPGA bring-up could not build the chip. `model/gate_slang_lint.py`.
  genvar gi;
  generate
    for (gh = 0; gh < N_LANES; gh = gh + 1) begin : g_half
`ifdef M_HALF_IGNORED
      assign half_v[gh] = 1'b0;
`else
      assign half_v[gh] = l_half[gh];
`endif
    end
  endgenerate
  generate
    for (gi = 0; gi < N_LANES; gi = gi + 1) begin : g_arm
      // ⛔⛔⛔ RANGE-GUARDED, AND THIS WAS A LIVE THIRD INSTANCE OF THE CLASS.
      // `l_armpin` is `[PINW-1:0]` -- 4 bits, 0..15 -- and `pin_rise`/
      // `pin_fall` are `[N_PINS-1:0]` = [11:0], so an ARM naming 12..15 reads
      // OUT OF RANGE. `l_armpin[cur] <= a_pin` is written straight from the
      // action's pin field with nothing refusing it.
      // ⭐ MEASURED, not reasoned: with the ARM pin at PIN_NONE, `arm_hit` is
      // X for ALL 198 armed cycles of the probe program, against 0 for the
      // same program arming on a real pin. The armed window exists in both, so
      // the result is not vacuous.
      // ⚠ WHAT WAS **NOT** SHOWN: `ready` did NOT go X in that program -- the
      // X was contained by the other terms it is ANDed with. So this is a real
      // out-of-range read with a real X, and it has NOT been demonstrated to
      // reach the scheduler. Guarding it anyway, because an X at a flop's
      // input depending on which terms happen to mask it is not a property to
      // rely on.
      // ⇒ `arm_hit = 0` is the right meaning, not merely the safe one: an ARM
      // on a pin that does not exist can never legitimately fire, so the lane
      // waits for its timeout, which is exactly what a non-firing arm does.
      // ⚠ This is the THIRD site in the family (writes, then the RX sample,
      // now the edge select), which is why `model/gate_program_index.py`
      // enumerates the class rather than fixing sites one at a time.
`ifdef M_UNGUARDED_ARMPIN
      wire arm_real = 1'b1;                 // the mutant: the defect restored
`else
      wire arm_real = (l_armpin[gi] < N_PINS[PINW-1:0]);
`endif
      assign arm_hit[gi] = l_armed[gi] & arm_real &
                           (l_armedge[gi] ? pin_rise[l_armpin[gi]]
                                          : pin_fall[l_armpin[gi]]);

      // ⭐⭐ THE CLOCKED SHIFTIN'S SAMPLE, TAKEN ON THE OBSERVED CLOCK RISE.
      // Same shape as `arm_hit` above and for the same reason: a peer that
      // stretches releases the clock LATE, so the only honest sampling
      // instant is the one the PEER chooses. ⛔ CAPTURED IN THE IDLE WINDOW,
      // never waited for, so `C` stays bounded.
      // ⛔ RANGE-GUARDED, and this is the FOURTH site of the class the index
      // gate enumerates (pin_out writes, the RX sample, the edge select, and
      // now this): an SPI TARGET legitimately declares PIN_NONE as its clock
      // pin because the master supplies it, and `pin_rise` is [11:0].
      // `ck_hit = 0` is the RIGHT meaning, not merely the safe one -- a
      // self-clocked shift is impossible without a real clock pin.
      // ⛔⛔ SILICON FIX #3 (ruling PN1): THE SAMPLED PIN IS THE ACTION'S, not
      //    the lane header's `l_pin`. The unclocked SHIFTIN and READBIT read
      //    `pin_in[a_pin]` and `pe_asm` validates the action pin, but this
      //    capture read `l_pin` -- so a clocked SPI master (header pin MOSI,
      //    SHIFTIN on MISO) sampled its OWN OUTPUT and received 00 while MISO
      //    carried 5B C4. Hidden because every clocked receive ever run had
      //    action pin == header pin (I2C). ⭐ ZERO FLOPS: the action is still
      //    in the lane's head slot while its capture is pending (the hold
      //    keeps it there -- A1 checks the word is stable), so the pin is read
      //    straight from it, the same way `ck_dly` reads the delay (F1). The
      //    capture is off the dispatch path. `M_CKRX_HEADER_PIN` restores the
      //    header pin.
`ifdef M_CKRX_HEADER_PIN
      wire [PINW-1:0] ck_rpin = l_pin[gi];
`else
      wire [PINW-1:0] ck_rpin = l_act[hix[gi]][ACT_W-1-OP_W -: PINW];
`endif
      wire ckp_real = (l_clkpin[gi] < N_PINS[PINW-1:0]);
      wire ckd_real = (ck_rpin      < N_PINS[PINW-1:0]);
      // ⛔ CI1: an OPEN-DRAIN clock is observed (a peer may stretch it, and
      // the I2C stretch behaviour is certified on exactly this); a PUSH-PULL
      // clock fires from the capture slot, at the engine's own rise.
      // `M_CKRX_PP_OBSERVED` restores the observed rise for both.
`ifdef M_CKRX_PP_OBSERVED
      assign ck_hit[gi] = l_ckwait[gi] & ckp_real & pin_rise[l_clkpin[gi]];
`else
      assign ck_hit[gi] = l_ckwait[gi] & (l_mode[gi]
                          ? (ppc_v & (ppc_l == gi) & (ppc_n == 2'd0))
                          : (ckp_real & pin_rise[l_clkpin[gi]]));
`endif
      assign ck_parked[gi] = l_ckpark[gi];
      // ⛔ THE SAMPLED PIN IS GUARDED SEPARATELY from the clock pin: a lane
      // may name a real clock and a RESERVED data pin, and reading
      // `pin_in[15]` would put X into the accumulator and from there into the
      // serial readback -- the defect `pinnone_image.hex` exists to catch on
      // the unclocked path, guarded here at birth instead.
      assign ck_bit[gi] = ckd_real ? pin_in[ck_rpin] : 1'b0;
      // the delay field of the action this lane is currently clocking
      assign ck_dly[gi] = l_act[hix[gi]][LOWX+BQW+BPW +: DLY_W];
      // ⭐ CE1: the parked lane's HIGH length after the observed rise --
      // `d`, or `d/2` on a HALF_HIGH lane (the rebase below adds it)
      assign ck_hdly[gi] = half_v[gi] ? (ck_dly[gi] >> 1) : ck_dly[gi];
`ifdef M_CK_REBASE_2D
      assign ck_rebase[gi] = now + {{(TS_W-DLY_W-1){1'b0}}, ck_dly[gi], 1'b0};
`elsif M_CK_RISE_ELIGIBLE
      assign ck_rebase[gi] = now;
`else
      assign ck_rebase[gi] = now + (l_ckpark[gi] ? {{(TS_W-DLY_W){1'b0}}, ck_hdly[gi]} : {TS_W{1'b0}});
`endif
    end
  endgenerate

  // =====================================================================
  // READY + EDF SELECT. ⛔ Both comparisons are wrap-safe.
  // =====================================================================
  wire [N_LANES-1:0] ready;
  wire [N_LANES-1:0] rel_due;
  wire [TS_W-1:0]    edf_key_off [0:N_LANES-1];

  // ⛔⛔ RULING TF1 -- READINESS AND THE EDF KEY ARE REGISTERED, COMPUTED ONE
  // CYCLE AHEAD FROM NEXT-STATE VALUES. The 50 MHz slow-corner path started
  // at `now`, ran through the 16-bit release compare and the key subtract,
  // then the five-way select, into the dispatch and prefetch registers.
  // Registering the compare and the key takes `now` off that path.
  // ⭐ NOT A PIPELINE STAGE: `rel_q`, `key_q` and `hz_q` hold, in every cycle,
  // exactly the value the old combinational expression has in that cycle.
  // They are computed from the NEXT values of `now`, `l_timestamp`, `l_d` and
  // `l_hcnt` -- `now_n`, `ts_n`, `ld_n` below and the hold term in the
  // sequential block -- so no lane becomes eligible one cycle earlier or
  // later than before. Lockstep simulation against the old RTL is the check.
  // ⛔ THE NAIVE VERSION IS THE MUTANT. Registering the CURRENT values (a
  // plain retiming register) makes readiness lag a cycle: a lane that has
  // just written back still reads its OLD timestamp for one cycle, and its
  // next release is seen one cycle late. M_TF1_LATE builds exactly that.
  // ⭐ TF2-R3: `rel_q` == `l_live & (now - l_timestamp >= 0)
  //                       & ~(l_armed & l_notmo)`, the whole release term --
  // so `l_live` no longer STARTS a path into the select (it did after TF1:
  // all 28 remaining violators began at `l_live[2]`).
  reg  [N_LANES-1:0] rel_q;
  reg  [N_LANES-1:0] live_n, armed_n, notmo_n;   // lane block's next values
  reg  [N_LANES-1:0] hz_q;                  // == (l_hcnt == 0)
  reg  [TS_W-1:0]    key_q [0:N_LANES-1];   // == l_timestamp + l_d - now
  reg                hold_ld;               // a DRIVE arm starts an SDA hold

  // (`genvar gi` is declared ahead, before g_arm)
  // TM1: the effective hold count -- the pending load reads as SDA_HS
  generate
    for (gi = 0; gi < N_LANES; gi = gi + 1) begin : g_hcnt
`ifdef M_TM1_UNREG
      assign l_hcnt[gi] = l_hcr[gi];
`else
      assign l_hcnt[gi] = (hl_v && hl_l == gi) ? SDA_HS[HOLDW-1:0]
                                               : l_hcr[gi];
`endif
    end
  endgenerate
  generate
    for (gi = 0; gi < N_LANES; gi = gi + 1) begin : g_ready
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
      // ⛔⛔ RULING W1: `rel_due` is "the release has arrived"; `ready` adds
      // "and this lane's own SDA hold + setup is over". A lane is INELIGIBLE
      // while its hold counter runs, so the dispatch that would release SCL
      // cannot overtake the data it is meant to clock. Kept as two wires so a
      // bench can count how often W1 actually delays a dispatch
      // (`rel_due & ~ready`). M_NO_HOLD_GATE drops the gate: the hold still
      // lands on time, and the data moves after SCL is released again.
      // ⭐ TF1 + TF2-R3: `rel_q` is the registered release term (live, the
      // timestamp ARRIVED by signed difference, and not armed-without-
      // timeout); `hz_q` the registered "hold counter is zero".
      assign rel_due[gi] = rel_q[gi];
      // ⭐⭐ RULING RX1 -- SILICON FIX #7, THE W1 ANALOG FOR RECEIVE. A
      // push-pull clocked SHIFTIN lane is INELIGIBLE while its capture is
      // pending (`l_ckwait`: set by the HIGH dispatch, cleared on the edge
      // the capture lands and sets `l_ckgot`). Without it, a late HIGH
      // dispatch followed by an on-time LOW shrank the HIGH phase below the
      // capture latency under contention, and the LOW consumed the bit
      // before it was captured -- reading 0 (552 of ~3,300 lane-2 SHIFTINs
      // on corpus_all5 seed 1). Contention-independent by construction; it
      // adds at most the capture latency to a late LOW (A2: like W6).
      // Open-drain lanes are excluded: they PARK on the observed rise.
      // ⛔ M_RX_NO_CAPGATE removes it (the pre-fix behaviour).
      // ⭐ EXACT, NOT CONSERVATIVE. A LOW picked in cycle c consumes at its
      // writeback in c + 2, so it needs the capture to have LANDED by then:
      // the capture slot fires this cycle or next (`ppc_n <= 1`). The first
      // version blocked until the capture had landed BEFORE the pick, 2 cycles
      // stricter than needed, and moved a dispatch on ce_spim_inv_m0 where the
      // old RTL lost no bit -- against RX1's "cycle-identical except where the
      // old behaviour lost a bit".
      // ⛔ EX1's two exactness mutants move the boundary by one cycle each
      // way (EARLY: allowed while ppc_n = 2, the bit is consumed before its
      // capture; LATE: only at ppc_n = 0, one cycle of slack lost). Each has
      // its own `ifdef -- the drift and kill gates discover no `elsif`.
`ifdef M_RX_CAPGATE_EARLY
      wire cap_early = 1'b1;
`else
      wire cap_early = 1'b0;
`endif
`ifdef M_RX_CAPGATE_LATE
      wire cap_late = 1'b1;
`else
      wire cap_late = 1'b0;
`endif
      wire [1:0] cap_lead = 2'd1 + {1'b0, cap_early} - {1'b0, cap_late};
`ifdef M_RX_NO_CAPGATE
      wire cap_ok = 1'b1;
`else
      wire cap_ok = ~(l_ckwait[gi] & l_mode[gi])
                    | (ppc_v & (ppc_l == gi) & (ppc_n <= cap_lead));
`endif
`ifdef M_NO_HOLD_GATE
      assign ready[gi] = rel_due[gi] & cap_ok;
`else
      assign ready[gi] = rel_due[gi] & hz_q[gi] & cap_ok;
`endif
      // ⭐ deadline as an OFFSET FROM NOW, so a wrapped key still orders
      //   correctly. 1.6b is what bounds the spread that makes this sound.
      //   Registered by TF1; see `key_q`.
      assign edf_key_off[gi] = key_q[gi];
    end
  endgenerate

  // combinational min-offset over READY lanes. ⭐ Reads REGISTERED keys only,
  // which is Ruling 1's condition (i): without the key registers this mux would
  // sit after the store read and the pipeline register would land behind the mux
  // it was added to avoid.
  // ⛔⛔ RULING TF2 -- A TREE, NOT A CHAIN. The serial loop below compared
  // lane k against the running best of lanes 0..k-1, four dependent compares
  // deep. The tree compares (0,1) and (2,3) in parallel, then their winners,
  // then lane 4: three deep.
  // ⭐ THE TIE RULE IS PRESERVED BY CONSTRUCTION: at every node the HIGHER-
  // index side wins only on a STRICT `<`, and every index on the left of a
  // node is lower than every index on its right -- so equal keys keep the
  // lowest index, exactly as the serial `<` did.
  // ⭐ PROVED, NOT ARGUED: `formal/argmin_equiv.sby` extracts the text between
  // the BEGIN/END markers from this file and proves it equal to the serial
  // loop for every `ready` and every key (SymbiYosys, unbounded).
  reg [LW-1:0]   winner;
  reg            winner_v;
  reg [N_LANES-1:0] winner_oh;   // one-hot winner, all zero when !winner_v
  generate if (N_LANES == 5) begin : g_argmin_tree
  // ---- BEGIN ARGMIN TREE ----
    // ⛔⛔ RULING TM2 -- EVERY COMPARE IS ONE COMPARATOR DEEP. The tree used to
    // compare, MUX THE 16-BIT WINNING KEY, compare again, mux again, compare a
    // third time: three comparators and two wide muxes in series, the third
    // family under the +0.5 ns bar (117e55c: `edf_key_off` -> `a_cnt`, +0.197,
    // 50 cells). The node decisions only ever compare KEYS OF LANES, so all
    // eight lane-pair compares run in parallel off the registered keys, and
    // each node SELECTS the bit for the pair its children chose -- `k23 < k01`
    // is `l31`, `l30`, `l21` or `l20` by (t3, t1). Same function by
    // definition (k01 WAS edf_key_off[i01]); proved by the same miter.
    reg            t1, t3, t23, t4, v01, v23, v03;
    reg            l10, l32, l20, l21, l30, l31, l40, l41, l42, l43;
    reg [LW-1:0]   i01, i23, i03;
    always @* begin
      l10 = edf_key_off[1] < edf_key_off[0];
      l32 = edf_key_off[3] < edf_key_off[2];
      l20 = edf_key_off[2] < edf_key_off[0];
      l21 = edf_key_off[2] < edf_key_off[1];
      l30 = edf_key_off[3] < edf_key_off[0];
      l31 = edf_key_off[3] < edf_key_off[1];
      l40 = edf_key_off[4] < edf_key_off[0];
      l41 = edf_key_off[4] < edf_key_off[1];
      l42 = edf_key_off[4] < edf_key_off[2];
      l43 = edf_key_off[4] < edf_key_off[3];
      t1  = ready[1] && (!ready[0] || l10);
      v01 = ready[0] | ready[1];
      i01 = t1 ? 3'd1 : 3'd0;
      t3  = ready[3] && (!ready[2] || l32);
      v23 = ready[2] | ready[3];
      i23 = t3 ? 3'd3 : 3'd2;
      // k23 < k01, the pair chosen by (t3, t1)
      t23 = v23 && (!v01 || (t3 ? (t1 ? l31 : l30) : (t1 ? l21 : l20)));
      v03 = v01 | v23;
      i03 = t23 ? i23 : i01;
      // edf_key_off[4] < k03, k03 being the key of lane i03
      t4  = ready[4] && (!v03 || (t23 ? (t3 ? l43 : l42)
                                      : (t1 ? l41 : l40)));
      winner   = t4 ? 3'd4 : i03;
      winner_v = v03 | ready[4];
      // ⭐ TF2-R2: the SAME decisions, as five select lines. Each lane's line
      // is the AND of the node outcomes on its path to the root, so the
      // dispatch mux after the winner is a flat AND-OR with no decoder.
      // `!t1 & v01` names lane 0: with lane 1 not taken, `v01` can only be
      // lane 0's ready.
      winner_oh[4] = t4;
      winner_oh[3] = !t4 &  t23 &  t3;
      winner_oh[2] = !t4 &  t23 & !t3;
      winner_oh[1] = !t4 & !t23 &  t1;
      winner_oh[0] = !t4 & !t23 & !t1 & v01;
    end
  // ---- END ARGMIN TREE ----
  end else begin : g_argmin_serial
    // any other lane count keeps the serial form the tree is proved against
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
      winner_oh = {N_LANES{1'b0}};
      for (k = 0; k < N_LANES; k = k + 1)
        if (winner_v && winner == k[LW-1:0]) winner_oh[k] = 1'b1;
    end
  end endgenerate

  // ⛔⛔ RULING TF2-R1/R2 -- THE WINNER'S ACTION, PICKED FROM PER-LANE HEADS.
  // The 50 MHz path after TF1/TF2 was mostly BUFFERS: one binary winner index
  // decoded into a 10-way, 24-bit select over every slot (`l_act[hix[winner]]`)
  // plus the head-valid and armed bits. Each lane's own head word and head-
  // valid bit are now selected by that lane's own `l_sel` -- a 2:1 mux on
  // flops, in parallel with the tree -- and the winner only picks one of five
  // with the one-hot lines: a flat AND-OR, no decoder after the select.
  // ⭐ CHOSEN OVER A REGISTERED SHADOW (Nathan, TF2-R): `hw[i]` IS
  // `l_act[hix[i]]` by definition, so there is no second copy of state to
  // keep in step and no update site that could be missed.
  wire [ACT_W-1:0] hw [0:N_LANES-1];
  wire [N_LANES-1:0] hv;
  generate
    for (gi = 0; gi < N_LANES; gi = gi + 1) begin : g_head
      assign hw[gi] = l_act[hix[gi]];
      assign hv[gi] = l_actv[hix[gi]];
    end
  endgenerate
  reg [ACT_W-1:0] w_act;           // == l_act[hix[winner]] when winner_v
  reg             w_hv;            // == l_actv[hix[winner]]
  reg             w_armed;         // == l_armed[winner]
  reg [PINW-1:0]  w_ck;            // == l_clkpin[winner]           (PR2)
  reg             w_ckr;           // == (l_clkpin[winner] < N_PINS) (PR2)
  integer         wk;
  always @* begin
    w_act = {ACT_W{1'b0}}; w_hv = 1'b0; w_armed = 1'b0;
    w_ck = {PINW{1'b0}}; w_ckr = 1'b0;
    for (wk = 0; wk < N_LANES; wk = wk + 1) begin
      w_act   = w_act   | ({ACT_W{winner_oh[wk]}} & hw[wk]);
      w_hv    = w_hv    | (winner_oh[wk] & hv[wk]);
      w_armed = w_armed | (winner_oh[wk] & l_armed[wk]);
      w_ck    = w_ck    | ({PINW{winner_oh[wk]}} & l_clkpin[wk]);
      w_ckr   = w_ckr   | (winner_oh[wk]
                           & (l_clkpin[wk] < N_PINS[PINW-1:0]));
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
  // ⛔⛔ M_TX_IGNORE_TAG: THE ACTION'S QUEUE FIELD IS WHAT MAKES TWO
  // TRANSMITTERS SAFE. `host_q` selects which per-lane TX queue the host
  // channel presents and pops, so dropping it to a constant makes every lane
  // draw from queue 0 -- and NOTHING FLAGS IT. The engine pops a queue, the
  // lane shifts what it got, and the wire carries a well-formed frame with
  // another lane's payload. That is the silent-corruption class, one level
  // above a wrong number, so the field is PRICED rather than trusted.
  // ⚠ IT WAS UNPRICEABLE UNTIL T5.1, and that is the point: no bench had ever
  // driven the host channel, so every OP_SHIFT in the suite found an empty
  // queue and took the underrun branch. A mutant on a path that never carries
  // data cannot die. `test/tb_tx.v` is what gives this one something to break.
  wire [BQW-1:0]   a_q;     // declared ahead of first use; driven below
`ifdef M_TX_IGNORE_TAG
  assign host_q    = 2'd0;
`else
  assign host_q    = a_q;
`endif
  always @(*) cfg_err = config_err;
  always @(*) clk_stretch = clk_stretch_err;
  reg [ACT_W-1:0] cur_act;

  assign busy = (st != ST_IDLE);

  // ---- action field slices -------------------------------------------
  wire [OP_W-1:0]  a_op    = cur_act[ACT_W-1 -: OP_W];
  wire [PINW-1:0]  a_pin   = cur_act[ACT_W-1-OP_W -: PINW];
  wire             a_lvl   = cur_act[ACT_W-1-OP_W-PINW];
  wire [DLY_W-1:0] a_dly   = cur_act[LOWX+BQW+BPW +: DLY_W];
  wire [BPW-1:0]   a_cnt   = cur_act[LOWX+BQW +: BPW];
  // ⭐ WHICH TX QUEUE THIS ACTION DRAWS FROM. Per-ACTION, so a lane's queue is
  // assigned by the PROGRAM and no lane number is baked into the hardware.
  assign           a_q     = cur_act[LOWX +: BQW];
  // BRANCH_BIT's WAIT W: count is its high nibble, pinb its low
  wire [BPW+PINB_W-1:0] br_wait = {a_cnt, cur_act[MOD_W +: PINB_W]};
  wire [MOD_W-1:0] a_mod  = cur_act[MOD_W-1:0];
  // a branch op (BRANCH_BIT or CMP_BRANCH): opcodes 8 / 9, one 4-bit compare
  wire             a_is_br = (a_op[OP_W-1:2] == OP_BRANCH_BIT[OP_W-1:2]);

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
  // ⛔⛔ THE SAME GUARD ON THE CLOCK PIN, AND IT WAS MISSING. Every DATA write
  // is guarded by `pin_real`; `OP_SHIFT`'s CLOCK write was not, so
  // `pin_out[l_clkpin[cur]]` could index out of range with no guard at all --
  // the identical out-of-range hazard the comment above calls "the class of
  // thing that passed iverilog and died in Yosys once already", on the
  // parallel axis. A fix applied to one axis and not to the symmetric one.
  // ⭐ AND IT IS WHAT MAKES "THIS LANE HAS NO CLOCK" EXPRESSIBLE, which the
  // design needs: an SPI **TARGET** does not drive a clock -- the master
  // supplies SCK -- so a target lane's `clkpin` has nothing legitimate to
  // point at. `test/corpus.py`'s SPI-target program had been pointing it at
  // its own MISO pin, which 1.6x now refuses, and the only honest alternative
  // is PIN_NONE.
  // ⚠ FOUND BY RULING 0's AUDIT, not by a failing test: feeding the host
  // channel turned the aliased clock write from invisible into a refusal, and
  // the refusal had nowhere for the corpus to go.
  // ⭐⭐ RULING PR2: THE CURRENT LANE'S CLOCK PIN IS A REGISTER. Signoff at
  // 94cebb7 put every top-10 slow path through `cur` -> the 5-way
  // `l_clkpin[cur]` select -> `pin_out` / `pin_oe` (-0.624 ns). `cur_ck` is
  // loaded with `cur` from the one-hot winner pick (`w_ck`, as `cur_act`
  // from `w_act`) and on a header write to the current lane, so
  // `cur_ck == l_clkpin[cur]` holds on every cycle -- asserted by every bench
  // through `test/inv_curck.vh`. Every DRIVE/WB use reads `ck_pin`.
  // ⛔ M_PR_CURSEL restores the select (the 94cebb7 form); the registers are
  // kept in both arms so the invariant check compiles against the mutant.
  reg  [PINW-1:0] cur_ck;
  reg             cur_ckr;
`ifdef M_PR_CURSEL
  wire [PINW-1:0] ck_pin = l_clkpin[cur];
  wire clk_real = (l_clkpin[cur] < N_PINS[PINW-1:0]);
`else
  wire [PINW-1:0] ck_pin = cur_ck;
  wire clk_real = cur_ckr;
`endif

  // =====================================================================
  // THE SELF-CLOCKED DECODE. Both terms of the trigger matter and neither is
  // redundant: without `clk_real` there is no clock to drive and `level` keeps
  // its old meaning; without `a_lvl` this would capture the 83 existing
  // `clk_real, level = 0` SHIFTs in the shipped images.
  wire ck_shift   = clk_real & a_lvl & (a_op == OP_SHIFT);
  wire ck_shiftin = clk_real & a_lvl & (a_op == OP_SHIFTIN);
  wire ck_act     = ck_shift | ck_shiftin;
  wire ck_is_low  = (l_ckph[cur] == CK_LOW);
  wire ck_is_high = (l_ckph[cur] == CK_HIGH);
  // ⭐ CI1: a PUSH-PULL clocked SHIFTIN's HIGH phase is writing back -- load
  // the capture slot (`ppc_*`), since its rise cannot be observed
  wire ppc_set    = (st == ST_WB) & ck_shiftin & ck_is_high & l_mode[cur];
  wire ck_is_coll = (l_ckph[cur] == CK_COLL);
  // ⭐ CE1: what a writeback adds to the timestamp -- the action's delay, or
  // half of it for the HIGH phase of a HALF_HIGH lane's clocked action. ONE
  // wire, read by both the WB and TF1's next-state mirror `ts_n`, so the two
  // cannot drift. (On an open-drain lane the park rebase then overrides it.)
  // ⭐ BRANCH_BIT is TIMED: its delay field is the target, so it adds its
  // WAIT W (count:pinb) instead -- `a_dly_wb`, read by the line below in
  // place of `a_dly` (a branch is never `ck_act`, so the half arm cannot
  // see it). M_BR_W_ZERO restores the zero-time branch R2b measured.
`ifdef M_BR_W_ZERO
  wire [DLY_W-1:0] a_dly_wb = a_is_br ? {DLY_W{1'b0}} : a_dly;
`else
  wire [DLY_W-1:0] a_dly_wb = a_is_br ? {{(DLY_W-BPW-PINB_W){1'b0}}, br_wait} : a_dly;
`endif
  wire [DLY_W-1:0] wb_dly = (ck_act & ck_is_high & half_v[cur])
                            ? (a_dly >> 1) : a_dly_wb;
  // ⚠ THE TWO OPCODES COUNT BITS DIFFERENTLY, and this is pre-existing ISA
  // semantics preserved rather than tidied: `OP_SHIFT` compares the
  // PRE-increment pointer against `a_cnt` (so a_cnt = 7 is eight bits, and it
  // is the same comparison the host-byte load uses, which is why the load and
  // the last bit coincide), while `OP_SHIFTIN` compares against `a_cnt - 1`
  // (so a_cnt = 8 is eight bits and a_cnt = 1 is the single-bit ACK).
  wire [BPW-1:0] ck_nbits = ck_shift ? (a_cnt + {{(BPW-1){1'b0}}, 1'b1})
                                     : a_cnt;
  // ⛔⛔ A DEGENERATE CLOCKED ACTION IS A CONFIG ERROR, NOT UNDEFINED. A
  // clocked action whose BIT COUNT is zero has no defined meaning, and
  // "undefined" is not acceptable on an entry whose whole claim is defined
  // behaviour. ⚠ TWO WAYS TO REACH IT, which is why the guard is on
  // `ck_nbits` and not on `a_cnt`: a clocked SHIFTIN with `count = 0` reads
  // nbits 0 directly, and a clocked SHIFT with `count = 15` computes
  // `a_cnt + 1` = 16, which WRAPS to 0 in the 4-bit field. The second was
  // found by writing the guard, not by testing.
  // ⭐ `pe_asm` refuses both statically, but a static refusal only covers
  // programs WE assemble -- a store corrupted by a bad load reaches the
  // engine anyway, which is exactly what happened while building `tb_fifo`.
  // ⇒ The lane HALTS and the EXISTING `config_err` sticky is set: no new
  //   status bit, and the standing rule that an illegal state is an ERROR
  //   rather than silent success.
  wire ck_degen = ck_act & (ck_nbits == {BPW{1'b0}});
  // ⛔⛔⛔ D1 -- A CLOCKED OPEN-DRAIN ACTION WHOSE DELAY CANNOT HOLD ITS DATA
  // IS REFUSED, and the refusal replaces a CLAMP that merely declined to make
  // things worse. `SDA_HOLD` cycles of data hold only satisfy `t_HD;DAT` if
  // the bit period is longer than the hold: at `d <= SDA_HOLD` the held value
  // would land AFTER the next clock rise, which to any receiver is a START or
  // a STOP rather than a data bit. The old `ck_hold_fits` term detected that
  // and fell back to the ZERO-hold behaviour -- correct as far as it went, but
  // it left the program RUNNING while `gate_um10204` reported it below the
  // `t_HD;DAT` requirement. A chip that emulates a protocol incorrectly and
  // reports success is the silent-corruption class; the entry's claim is
  // DEFINED behaviour, so the honest answer is to refuse.
  // ⚠ WHY `d <= SDA_HOLD` AND NOT `d < SDA_HOLD`: at `d == SDA_HOLD` the data
  // reaches the pin on the SAME cycle the next phase dispatches, so there is
  // ZERO setup before the rise -- `t_SU;DAT` is violated even though the hold
  // itself fits. The legal floor is strictly greater.
  // ⭐ OPEN-DRAIN ONLY, for the same reason the park is: a push-pull clocked
  // lane is SPI, where `t_HD;DAT` is the master's own choice and no pull-up
  // slews the line. `l_mode[cur]` already routes those straight past the hold.
  // ⇒ AT `SDA_HOLD == 0` THERE IS NO HOLD TO NOT FIT, so nothing is refused.
  //   That build (`-GSDA_HOLD_NS=0`) exists to MEASURE the original defect, and
  //   a refusal there would leave the measurement arm with no traffic to
  //   measure -- the shape `project.v` already warns about, where a chip that
  //   refuses to run produces no evidence by definition.
  // ⛔⛔ RULING U: THE SCOPE IS EVERY OPEN-DRAIN DATA DRIVE THE HOLD APPLIES
  // TO, not only the clocked ones. The UNCLOCKED open-drain SHIFT that takes
  // its own clock low in the same dispatch (`clk_real & ~a_lvl` -- the
  // certified two-action frame's shape) is held by the same pipeline, so a
  // delay that cannot fit the hold is the same defect there. It used to fall
  // back to a CLAMP (zero hold, program left running and reported below the
  // requirement); D1's reasoning applies unchanged, so it is now REFUSED and
  // the clamp is retired. `M_HOLD_CLOCKED_ONLY` restores the old scope.
  wire uc_hold = (a_op == OP_SHIFT) & clk_real & ~a_lvl;
`ifdef M_HOLD_CLOCKED_ONLY
  wire ck_holdviol = ck_act & ~l_mode[cur] & (SDA_HOLD != 0)
                     & (a_dly <= SDA_HOLD[DLY_W-1:0]);
`else
  wire ck_holdviol = (ck_act | uc_hold) & ~l_mode[cur] & (SDA_HOLD != 0)
                     & (a_dly <= SDA_HOLD[DLY_W-1:0]);
`endif
  // ⛔⛔ THE TWO REFUSALS SHARE ONE CHAIN-HEAD WIRE, and that is the lesson of
  // `ck_degen`'s own history written down: a guard bolted onto a BRANCH let a
  // refused clocked SHIFT fall through into the unclocked body and drive the
  // data pin on its way to being refused, and the identical mistake had
  // already been made once on the retire chain. One wire, used at the head of
  // every chain that dispatches a clocked action.
  // ⭐ THE CAUSE STAYS DISTINGUISHABLE without a second status bit: the bench
  // reads `ck_degen` and `ck_holdviol` separately (D6 -- a refusal image that
  // trips a SECOND refusal is red), while the host sees one `config_err`.
  wire ck_refuse = ck_degen | ck_holdviol;
  // the n-th bit has been counted (`l_ckbit` advances on the LOW phase)
  wire ck_bits_done = (l_ckbit[cur] == ck_nbits);
  // ⭐ RETIRE: a transmit on the last HIGH, a receive on its trailing COLL.
  wire ck_retire  = (ck_shift   & ck_is_high & ck_bits_done) |
                    (ck_shiftin & ck_is_coll);
  // ⛔ EVERY OTHER PHASE RE-DISPATCHES: no PC advance, no head invalidation,
  // no buffer swap -- the same mechanism a chaining `OP_REARM` already uses.
  // This is also Amendment A1 in silicon: a held dispatch owes NO refill, so
  // the proof's "exactly one slot per lane" became "at most one".
  wire ck_hold    = ck_act & ~ck_retire;
  // A CONSUME POINT: where a captured bit is taken. The first LOW of an action
  // has nothing pending yet (`l_ckbit` is still 0), every later LOW takes the
  // previous bit, and the COLL takes the last one -- n consumes for n bits.
  wire ck_consume = ck_shiftin & (ck_is_coll |
                                  (ck_is_low & (l_ckbit[cur] !=
                                                {BPW{1'b0}})));

  // THE NEXT PHASE, as a wire so the mutant is a one-line substitution.
  wire [1:0] ck_norm = ck_shift
                       ? (ck_is_low ? CK_HIGH : CK_LOW)
                       : ck_is_low  ? CK_HIGH
                       : ck_is_high ? (ck_bits_done ? CK_COLL : CK_LOW)
                       : CK_LOW;
`ifdef M_CK_NO_ALTERNATE
  wire [1:0] ck_next = CK_LOW;            // the mutant: the phase never moves
`else
  wire [1:0] ck_next = ck_norm;
`endif
  // ⛔ M_CK_NEVER_RETIRE holds for ever, which is LAYER A of the bench
  // watchdog's must-fire: a lane that never retires must trip the coarse
  // liveness check in every bench that runs a clocked program.
`ifdef M_CK_NEVER_RETIRE
  wire ck_hold_eff = ck_act;              // the mutant: it never lets go
`else
  wire ck_hold_eff = ck_hold;
`endif
  // ⭐ "THIS ACTION RETIRES ON THIS DISPATCH", named ONCE and used by the
  // retire chain, the phase reset and the bit-counter reset. Writing the
  // condition three times is how the three drift apart -- and the phase
  // reset getting it wrong is precisely the defect being fixed.
  wire act_retire = ~ck_hold_eff & ((a_op != OP_REARM) | a_lvl);
  // ⛔ M_CK_NO_PARK removes the post-HIGH park, so the capture races the
  // lane's own next dispatch again and a long stretch LOSES BITS. MEASURED
  // both ways: without the park a 500-cycle SCL hold sets `clk_stretch_err`
  // and a 50-cycle one does not; with it, 5000 cycles lose nothing. That is
  // what makes the compliance claim evidence rather than an assertion.
`ifdef M_CK_NO_PARK
  wire ck_park_en = 1'b0;                 // the mutant: no park
`else
  wire ck_park_en = 1'b1;
`endif
  // CONDITION (a): the clocked ACK releases the data pin on BOTH phases.
  // `{oe, out}` as a wire, so the mutant is one line against one line.
  // ⛔ M_ACK_DRIVES_SDA makes it a PUSH-PULL HIGH on an open-drain net while
  // the peer pulls low to acknowledge -- a SHORT, which the per-net-type
  // overlap rule must refuse. ⭐ In the clean build `ack_drv[1]` is 0, so the
  // `pin_out` write it feeds never happens and the unclocked SHIFTIN path is
  // bit-for-bit what it was.
`ifdef M_ACK_DRIVES_SDA
  wire [1:0] ack_drv = 2'b11;             // the mutant: DRIVE the ACK high
`else
  wire [1:0] ack_drv = 2'b00;             // release: oe = 0, both phases
`endif

  // ---- the bit-order reversals (ruling 1) ------------------------------
  // SPELLED OUT AS A CONCATENATION, NOT A FUNCTION OR A LOOP. A Verilog
  // function here is the "non-constant function call in constant expression"
  // shape that Yosys rejected TWICE in this design while iverilog accepted
  // it; an explicit reversal cannot be read two ways by two tools.
  // ⛔⛔ CANDIDATE #8: the bit a SHIFT drives -- the register's, or, when the
  // register does not yet hold this byte, the queue head's first bit (0 on an
  // empty queue: an underrun, flagged at the writeback).
  wire [7:0] host_data_rev = {host_data[0], host_data[1], host_data[2],
                              host_data[3], host_data[4], host_data[5],
                              host_data[6], host_data[7]};
  // the queue head in WIRE order: REVERSED ON AN MSB-FIRST LANE, so the
  // shift path, which walks `l_tx[0]` outward, puts the MSB on the wire
  // first. ONE site for the order, read by the first bit and by the pop.
`ifdef M_IGNORE_ORDER
  wire [7:0] host_ord = host_data;
`else
  wire [7:0] host_ord = l_order[cur] ? host_data_rev : host_data;
`endif
  // `M_TX_PRELOAD` is silicon fix #8 undone (the must-fire): the register
  // alone drives, the next byte preloads at the end of each byte, and the
  // first byte after a load is the reset 0x00.
`ifdef M_TX_PRELOAD
  wire tx_bit   = l_tx[cur][0];
`else
  wire tx_bit   = l_txv[cur] ? l_tx[cur][0] : (host_valid & host_ord[0]);
`endif
  // ⛔⛔⛔ THE SAMPLE IS RANGE-GUARDED, AND IT IS ONE WIRE SO THERE IS ONE
  // GUARD. `a_pin` is a 4-bit PROGRAM-CONTROLLED field addressing 0..15 while
  // only `N_PINS = 12` pins exist, so `pin_in[a_pin]` on the reserved index
  // reads OUT OF RANGE. Found by `pinnone_image.hex`: `OP_SHIFTIN` on
  // PIN_NONE put X into `l_rx`, then `rx_data`, then the serial readback, and
  // the X LEFT THE CHIP on `ser_d` while `ser_v` was high -- 112 cycles, one
  // per SHIFT dispatch.
  // ⭐ IT IS THE MIRROR OF A DEFECT ALREADY FIXED. The WRITE side was guarded
  // after the `pin_out[12]` incident (`pin_real` at the OP_SHIFT arm,
  // `clk_real` on the clock write, the `pin_pp` header guard) and the READ
  // side was not -- "a fix on one axis repeats the error on a parallel one",
  // twice over now.
  // ⚠ AND IN SILICON IT IS NOT X. An out-of-range read synthesises to
  // whatever the tool made of it: deterministic but UNSPECIFIED, which is
  // worse than X because simulation stops warning about it. Sampling a
  // defined 0 makes the behaviour a property of the RTL rather than of the
  // synthesiser.
  // ⇒ Every one of the three sample sites uses this wire, so a future site
  // cannot pick up the unguarded form by copying its neighbour.
`ifdef M_UNGUARDED_SAMPLE
  wire       rx_bit     = pin_in[a_pin];      // the mutant: the defect restored
`else
  wire       rx_bit     = pin_real ? pin_in[a_pin] : 1'b0;
`endif
  // ⭐ BRANCH_BIT: the bit is `rx_bit` (READBIT's guarded sample), read at
  // writeback; taken when it equals `level`. The target address is formed as
  // the header base is: ACT_BASE + word * ACT_BYTES.
  wire [AW-1:0] br_tgt_w = {{(AW-BR_W){1'b0}}, a_dly[BR_W-1:0]};
`ifdef M_BR_TGT_OFF1
  wire [AW-1:0] br_tgt   = ACT_BASE[AW-1:0] + (br_tgt_w + {{(AW-1){1'b0}}, 1'b1}) * ACT_BYTES[AW-1:0];
`else
  wire [AW-1:0] br_tgt   = ACT_BASE[AW-1:0] + br_tgt_w * ACT_BYTES[AW-1:0];
`endif
  // the target the bound is checked on: BRANCH_BIT's whole delay field
  // (delay[9:7] set is >= 120, refused), CMP_BRANCH's delay[6:0] only --
  // its delay[9:7] carry the immediate (opcode bit 0 tells them apart)
  wire [DLY_W-1:0] br_tdly = (a_op[1:0] != 2'b00) ? {{(DLY_W-BR_W){1'b0}}, a_dly[BR_W-1:0]} : a_dly;
  wire          br_bad   = (br_tdly >= BR_NWORDS[DLY_W-1:0])
                         | (br_wait < BR_W_MIN[BPW+PINB_W-1:0]);
  // ⭐ v2 primitive 2 (Wilson 10-27 Q4): THE DECISION IS REGISTERED AT DRIVE
  // (`br_take_q`), for both branch ops, so the WB cone sees one flop. A
  // branch's own DRIVE -> WB is one cycle and nothing writes l_rx[cur] in
  // between (only a SHIFTIN/READBIT's own WB does), so the compare reads the
  // same byte either side; BRANCH_BIT's pin sample moves WB -> DRIVE.
`ifdef M_BR_LVL_INV
  wire          br_bit_take = (rx_bit != a_lvl);
`else
  wire          br_bit_take = (rx_bit == a_lvl);
`endif
  // CMP_BRANCH: the received byte in WIRE order -- l_rx shifts LSB-first on
  // every lane, so an MSB-first lane (l_order) compares it bit-reversed
  // (Nate 10-28, option 1: chosen by the lane's own order, no word field).
  wire [7:0]    cmp_rev  = {l_rx[cur][0], l_rx[cur][1], l_rx[cur][2], l_rx[cur][3],
                            l_rx[cur][4], l_rx[cur][5], l_rx[cur][6], l_rx[cur][7]};
`ifdef M_CMP_ORDER_IGN
  wire [7:0]    cmp_src  = l_rx[cur];
`else
  wire [7:0]    cmp_src  = l_order[cur] ? cmp_rev : l_rx[cur];
`endif
  // the immediate: {pin, delay[9:7], level}, in the byte's natural order
`ifdef M_CMP_IMM_OFF1
  wire [7:0]    cmp_imm  = {a_pin, a_dly[DLY_W-1 -: 3], a_lvl} + 8'd1;
`else
  wire [7:0]    cmp_imm  = {a_pin, a_dly[DLY_W-1 -: 3], a_lvl};
`endif
  // mod: 0 all 8 bits, 1 ignore bit 0, 2 high nibble, 3 low nibble
`ifdef M_CMP_MASK_IGN
  wire [7:0]    cmp_mask = 8'hFF;
`else
  wire [7:0]    cmp_mask = (a_mod == 2'd1) ? 8'hFE : (a_mod == 2'd2) ? 8'hF0
                         : (a_mod == 2'd3) ? 8'h0F : 8'hFF;
`endif
  // q[0] = inv: taken on MISMATCH
`ifdef M_CMP_INV
  wire          br_cmp_take = (((cmp_src ^ cmp_imm) & cmp_mask) == 8'h00);
`else
  wire          br_cmp_take = (((cmp_src ^ cmp_imm) & cmp_mask) == 8'h00) ^ a_q[0];
`endif
  // LOOP: n = {pin, delay[9:7], level} (as CMP's immediate); the effective
  // count is n on a fresh entry (l_loop = 0), else the running counter.
  // taken = eff != 1, and the WB writes eff - 1, so the body runs EXACTLY n
  // times and the counter is 0 again at the exit (re-entrant).
  wire [7:0]    lp_cur  = l_loop[cur];
`ifdef M_LOOP_OFF1
  wire [7:0]    lp_n    = {a_pin, a_dly[DLY_W-1 -: 3], a_lvl} + 8'd1;
`else
  wire [7:0]    lp_n    = {a_pin, a_dly[DLY_W-1 -: 3], a_lvl};
`endif
  wire [7:0]    lp_eff  = (lp_cur == 8'd0) ? lp_n : lp_cur;
`ifdef M_LOOP_NOEXIT
  wire          br_loop_take = 1'b1;
`else
  wire          br_loop_take = (lp_eff != 8'd1);
`endif
`ifdef M_LOOP_NORESET
  wire [7:0]    lp_next = (lp_eff == 8'd1) ? 8'd1 : lp_eff - 8'd1;
`else
  wire [7:0]    lp_next = lp_eff - 8'd1;
`endif
  reg           br_take_q;     // the decision, registered at ST_DRIVE
`ifdef M_BR_ALWAYS
  wire          br_taken = 1'b1;
`elsif M_BR_NEVER
  wire          br_taken = 1'b0;
`else
  wire          br_taken = br_take_q;
`endif
  // the byte an OP_SHIFTIN completes: the sample being taken now, followed by
  // the seven already in `l_rx`
  // ⭐⭐ ON A CLOCKED SHIFTIN THE BIT COMES FROM THE CAPTURE, NOT A LIVE READ.
  // `rx_bit` reads the pin AT WRITEBACK, which on a clocked receive is the
  // wrong instant by construction: the writeback of the high phase happens
  // when the engine RELEASED the clock, and the peer may not have let it rise
  // yet. `l_cksamp` holds the value the data pin had AT THE OBSERVED RISE.
  // ⛔ FALLS BACK TO 0 RATHER THAN TO A LIVE READ when no rise was seen: a
  // live read would silently substitute a plausible bit for a missing one,
  // and `clk_stretch_err` is what distinguishes them.
  wire       ck_rxbit  = l_ckgot[cur] & l_cksamp[cur];
  wire       rx_bit_sel = ck_shiftin ? ck_rxbit : rx_bit;
  wire [7:0] rx_asm     = {rx_bit_sel, l_rx[cur][7:1]};
  wire [7:0] rx_asm_rev = {rx_asm[0], rx_asm[1], rx_asm[2], rx_asm[3],
                           rx_asm[4], rx_asm[5], rx_asm[6], rx_asm[7]};

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
  // ⭐ v2: the header's `base` is a WORD INDEX; the PC stays a BYTE address
  // (unchanged PC logic, stepping by ACT_BYTES), so it is converted ONCE here:
  // ACT_BASE + base * ACT_BYTES. pe_asm refuses a base past the store.
  wire [BASE_W-1:0] hbase = hsh_n[HDR_BYTES*8-2-2*PINW-DLY_W-CW-D_W-D_W -: BASE_W];
  // the zero-extension written out (what Verilog does anyway): the product is
  // AW bits on both sides -- no ArithOpMismatch (model/gate_slang_lint.py)
  wire [AW-1:0] hbase_addr = ACT_BASE[AW-1:0]
                           + {{(AW-BASE_W){1'b0}}, hbase} * ACT_BYTES[AW-1:0];

  // =====================================================================
  // ⛔⛔ RULING TF1 -- THE NEXT-STATE VALUES THE REGISTERED READINESS READS
  // =====================================================================
  // Each wire is the value its register WILL hold after this edge, written
  // from the same conditions the register's own write uses:
  //   now_n  the `now` block: +1 when `now_inc`
  //   ts_n   the lane block: ST_WB adds `a_dly` for `cur`; the edge capture's
  //          rebase, written LATER in that block, wins over it; nothing moves
  //          while `!run`
  //   ld_n   the header unpack: `l_d[hl]` at H_RD on the header's last byte
  // ⚠ `l_d` IS IN THE LIST BECAUSE OF ONE EDGE. The last lane's `l_d` is
  // written on the same edge that sets `hdr_done`, and the prefetch reads the
  // winner from the very next cycle -- so a key computed from the current
  // `l_d` would be stale for exactly that cycle.
  // ⛔ M_TF1_LATE registers the CURRENT values instead: the naive retiming,
  // which makes every release, and every post-writeback readiness, a cycle
  // late. It is the must-fire for this block.
`ifdef M_NO_PRIME
  assign now_inc = run;
`else
  assign now_inc = run && primed;
`endif
  wire [TS_W-1:0] now_n = now + {{(TS_W-1){1'b0}}, now_inc};
  wire            hdr_wr = run && (hst == H_RD) && (hb == HB_LAST);
  wire [TS_W-1:0] ts_n [0:N_LANES-1];
  wire [D_W-1:0]  ld_n [0:N_LANES-1];
  generate
    for (gi = 0; gi < N_LANES; gi = gi + 1) begin : g_next
      assign ts_n[gi] =
          !run ? l_timestamp[gi]
`ifndef M_NO_REBASE
        : arm_hit[gi] ? ck_rebase[gi]
`endif
        : (st == ST_WB && cur == gi)
            ? l_timestamp[gi] + {{(TS_W-DLY_W){1'b0}}, wb_dly}
            : l_timestamp[gi];
      assign ld_n[gi] = (hdr_wr && hl == gi)
          ? hsh_n[HDR_BYTES*8-2-2*PINW-DLY_W-CW -: D_W] : l_d[gi];
    end
  endgenerate

  // the sign of a wrap-safe difference: 1 when `t` is still in the future
  function tf_diff(input [TS_W-1:0] a, input [TS_W-1:0] t);
    reg [TS_W-1:0] d;
    begin
      d = a - t;
      tf_diff = d[TS_W-1];
    end
  endfunction

  // its own loop index: sharing `i` with the lane block would make two
  // always blocks write one variable on the same edge
  integer ti;
  // ⭐ TF3: branch 1 reads the PREVIOUS cycle's winner, a register, so the
  // prefetch scan is no longer at the end of the select path. Above D* the
  // branch never fires after priming (TH3), so nothing there changes.
  // Declared HERE, ahead of this block that writes them (declare-before-use).
  reg [LW-1:0]          winner_q;
  reg                   winner_v_q;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      // `now`, every `l_timestamp` and every `l_d` reset to 0. The release
      // term `rel_q` lives in the lane block (TF2-R3), beside the writes of
      // `l_live` / `l_armed` / `l_notmo` it needs the next values of.
      `PE_RST_SCHED                     // CANARY: rst_n IS the halt now
    end else begin
      for (ti = 0; ti < N_LANES; ti = ti + 1) begin
`ifdef M_TF1_LATE
        key_q[ti] <= (l_timestamp[ti] + {{(TS_W-D_W){1'b0}}, l_d[ti]}) - now;
`else
        key_q[ti] <= (ts_n[ti] + {{(TS_W-D_W){1'b0}}, ld_n[ti]}) - now_n;
`endif
      end
      winner_q   <= winner;
      winner_v_q <= winner_v;
    end
  end

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
  reg [LW-1:0]          pl;           // the lane the in-flight refill serves
  // ⛔⛔ RULING TF3 -- THE ROUND-ROBIN POINTER IS ITS OWN REGISTER. It used
  // to BE `pl`, so the winner-first branch, which sets `pl <= winner`, also
  // moved the scan position to `winner + 1` after every capture. Below D*
  // that starved a lane for 16,468 cycles (2,473 refills served ahead of
  // it; docs/PORT_SPEC.md §6). `prr` is advanced ONLY by the round-robin
  // path, so the winner-first branch borrows the port without moving it.
  reg [LW-1:0]          prr;
  reg                   pbr1;         // the in-flight refill came from branch 1
  // (`winner_q` / `winner_v_q`, TF3's registered winner, are declared ahead,
  // before the block that writes them)
  reg                   pslot;        // which slot this refill is filling
  reg [AW-1:0]          paddr;        // and from which address -- both latched
                                      // at the scan, see the arbiter comment
  // ⭐ The slot the in-flight refill targets. Same one arithmetic form as
  // `hix`/`six`, but keyed on the LATCHED `pl`/`pslot` rather than on a lane's
  // current select -- a refill must land in the slot that was chosen when it
  // was issued, not in whatever is the head by the time it completes.
  wire [SIW-1:0]        fix = pl * SPL + (((SPL > 1) && pslot) ? 1 : 0);

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
      hvalid = l_actv[hix[ln]];
      hact   = l_act [hix[ln]];
      if (!hvalid)
        fetch_addr = l_pc[ln];                       // filling the head itself
      else if (hact[ACT_W-1 -: OP_W] == OP_REARM && hact[ACT_W-1-OP_W-PINW])
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
      hvalid = l_actv[hix[ln]];
      fvalid = l_actv[six[ln]];
      hact   = l_act [hix[ln]];
      if (!hvalid)
        want_fetch = 1'b1;                           // head is empty: urgent
      // ⭐⭐ SINGLE BUFFER: THERE IS NO SPARE TO FILL, so a valid head means
      // nothing to fetch. ⛔ This branch must come BEFORE the spare logic:
      // with SPL = 1 the spare index aliases the head, so `!fvalid` would read
      // HEAD's own valid bit, answer "already full", and happen to be right --
      // by coincidence, through an index that means something else. A
      // coincidence in an index is how lane 4's slots aliased onto lane 0's.
      else if (SPL == 1)
        want_fetch = 1'b0;
      else if (hact[ACT_W-1 -: OP_W] == OP_REARM && !hact[ACT_W-1-OP_W-PINW])
        want_fetch = 1'b0;                           // chaining: successor is
                                                     // the head; spare unused
      // OPTION A: a branch head's successor is unknown until it writes back
`ifndef M_BR_FETCH_PAST
      else if (hact[ACT_W-1 -: OP_W-2] == OP_BRANCH_BIT[OP_W-1:2])
        want_fetch = 1'b0;
`endif
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
    if (!rst_n)      `PE_RST_PRIMED      // CANARY: rst_n IS the halt now
    else if (!primed_q) begin
      prime_unp = 1'b0;
      for (pi = 0; pi < N_LANES; pi = pi + 1)
        if (l_live[pi] && want_fetch(pi[LW-1:0])) prime_unp = 1'b1;
      if (hdr_done && !prime_unp) primed_q <= 1'b1;
    end
  end
  assign primed = primed_q;     // `primed` is declared ahead, beside `now`

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
      `PE_RST_PORT                      // CANARY: rst_n IS the halt now
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
        // (the address itself: the per-bank copies below, same condition)
        // TM2: each byte's address, added HERE (off the store read path)

      end
    end
  end

  // =====================================================================
  // THE ONE SEQUENTIAL BLOCK for lane state, so no field has two writers.
  // =====================================================================
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      // ⛔⛔ ONE LIST FOR RESET AND HALT: the macros at the top of this
      // file (#11).
      // ⭐ RESET-NETWORK HALT (Wilson): this branch IS the halt -- rst_n is
      // power-on OR halt, so "halt state = reset state" is literal. The
      // keep-list `_m` flags clear here too; their twins (power-on only)
      // hold the status across the halt. The must-fire mutants come LAST
      // (last write wins), guarded to a halt.
      `PE_RST_MAIN
      `PE_RST_KEEP
      `PE_HALT_MUTANTS
    end else begin
      rx_push <= 1'b0;
        host_pop <= 1'b0;   // one-cycle pulse; the consume site re-asserts
      // ⭐ TF1: the DRIVE arms that start an SDA hold raise this instead of
      // writing `l_hcnt` themselves; the one write, and the matching `hz_q`
      // update, are in the hold-expiry block below. One site, so the counter
      // and its registered zero-flag cannot disagree.
      hold_ld = 1'b0;
      // ⭐ TF2-R3: every run-time write to `l_live`, `l_armed` and `l_notmo`
      // lands in these next-value temporaries; the registers -- and the
      // registered readiness `rel_q`, which needs their NEXT values -- are
      // written from them ONCE, at the end of this branch. Reads of the
      // registers inside the block still see this cycle's value, exactly as
      // they did when the writes were non-blocking.
      for (i = 0; i < N_LANES; i = i + 1) begin
        live_n[i]  = l_live[i];
        armed_n[i] = l_armed[i];
        notmo_n[i] = l_notmo[i];
      end

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
                    // The header is HDR_BITS = 48 bits inside a HDR_BYTES*8 =
                    // 48-bit byte-shift register (the order bit took the last
                    // spare), so the two coincide today; slicing from
                    // HDR_BITS-1 would read LOW the moment they differ. Aligning
                    // to the top of the shift register keeps the layout
                    // hand-assemblable: byte0 = {pin, clkpin}, and any spare
                    // bits land at the BOTTOM where nothing reads them.
                    l_pin[hl]    <= hsh_n[HDR_BYTES*8-1 -: PINW];
                    l_clkpin[hl] <= hsh_n[HDR_BYTES*8-1-PINW -: PINW];
                    // ⭐ PR2: `cur_ck` mirrors `l_clkpin[cur]`, so a header
                    // write to the CURRENT lane updates it too. Dispatch is
                    // gated on `primed`, which rises only after the header
                    // load, so the two never land on the same edge.
                    if (hl == cur) begin
                      cur_ck  <= hsh_n[HDR_BYTES*8-1-PINW -: PINW];
                      cur_ckr <= (hsh_n[HDR_BYTES*8-1-PINW -: PINW]
                                  < N_PINS[PINW-1:0]);
                    end
                    l_mode[hl]   <= hsh_n[HDR_BYTES*8-1-2*PINW];
                    // the LAST bit of the header word; see `l_order`
                    l_order[hl]  <= hsh_n[0];
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
                        config_err_m <= 1'b1;
                      if (hsh_n[HDR_BYTES*8-1-PINW -: PINW] >= N_UIO[PINW-1:0])
                        config_err_m <= 1'b1;
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
                    // ⭐ RULING HDR: the old `c` field's low two bits.
                    l_half[hl]   <= hsh_n[HDR_BYTES*8-2-2*PINW-DLY_W-CW+1];
                    l_clkinv[hl] <= hsh_n[HDR_BYTES*8-2-2*PINW-DLY_W-CW+2];
                    // ⛔ CE2: only a PUSH-PULL lane whose clock is a `uo_out`
                    // pin (8..11) is inverted. `uo_out` is re-registered in
                    // the top, so the XOR lands BEFORE a flop and F2 (every
                    // output bit a flop Q) holds; a `uio` clock would put the
                    // XOR after the last flop, so it is refused by pe_asm and
                    // the image audit, and ignored here.
                    if (hsh_n[HDR_BYTES*8-1-PINW -: PINW] < N_PINS[PINW-1:0]
                        && hsh_n[HDR_BYTES*8-1-PINW -: PINW] >= 4'd8)
                      pin_inv[hsh_n[HDR_BYTES*8-1-PINW -: PINW]]
                          <= hsh_n[HDR_BYTES*8-2-2*PINW-DLY_W-CW+2]
                             & hsh_n[HDR_BYTES*8-1-2*PINW];
                    l_d[hl]      <= hsh_n[HDR_BYTES*8-2-2*PINW-DLY_W-CW -: D_W];
                    l_pc[hl]     <= hbase_addr;
                    l_base[hl]   <= hbase_addr;
                    // ⭐ the fetch pointer starts WITH the PC, not ahead of it:
                    // both slots are empty, so the first refill targets the
                    // head at `l_pc` and `fetch_addr` reads `l_pc` directly.
                    // `l_fpc` then takes over from P_CAP onward.
                    l_fpc[hl]    <= hbase_addr;
                    live_n[hl]   = 1'b1;
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
            // ⭐ TF3: the registered winner, re-checked live -- a lane can halt
            // (timeout, stretch fault) in the cycle after it won, and a refill
            // for a halted lane is four cycles of port time for nothing.
            if (winner_v_q && l_live[winner_q] && !l_actv[hix[winner_q]]) begin
              pl    <= winner_q;
              pbr1  <= 1'b1;
              pslot <= l_sel[winner_q];      // the head: it is what stalls
              paddr <= l_pc[winner_q];
              pst   <= P_REQ;
            end else if (l_live[prr] && want_fetch(prr)) begin
              // fill the head if empty, otherwise the spare
              pl    <= prr;
              pbr1  <= 1'b0;
              pslot <= l_actv[hix[prr]] ? (!l_sel[prr])
                                                          : l_sel[prr];
              paddr <= fetch_addr(prr);
              pst   <= P_REQ;
            end else begin
              prr <= (prr == LANE_LAST) ? {LW{1'b0}} : prr + 1'b1;
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
            l_act [fix] <= s_wrdata[ACT_BYTES*8-1 -: ACT_W];
            l_actv[fix] <= 1'b1;
            // ⭐ THE SUCCESSOR POINTER ADVANCES FROM THE ADDRESS JUST FETCHED,
            // which is what makes the loop case need no special handling here:
            // after a `l_base` fetch, `l_fpc` becomes `l_base + ACT_BYTES`,
            // exactly the successor of the action now resident.
            l_fpc[pl] <= paddr + ACT_BYTES[AW-1:0];
            pst       <= P_SCAN;
            // ⛔ TF3: only a round-robin refill advances the pointer. A
            // winner-first refill leaves it where the scan had reached.
            if (!pbr1) prr <= (pl == LANE_LAST) ? {LW{1'b0}} : pl + 1'b1;
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
                   if (w_armed) begin
                     live_n[winner]    = 1'b0;       // HALT this lane
                     armed_n[winner]   = 1'b0;
                     l_timeout_m[winner] <= 1'b1;    // STICKY -- status stream
                     sticky_ovr_m        <= 1'b1;
                   end else
`endif
                   // ⭐ dispatch reads the HEAD slot. With the spare already
                   // filled, the usual case after a writeback is that the head
                   // is valid IMMEDIATELY -- which is the whole J reduction.
                   // ⭐ TF2-R: the one-hot picks (`w_hv`, `w_act`, `w_armed`
                   // above) are exactly `l_actv[hix[winner]]`,
                   // `l_act[hix[winner]]` and `l_armed[winner]`.
                   if (w_hv) begin
                     cur     <= winner;
                     cur_act <= w_act;
                     cur_ck  <= w_ck;          // PR2: == l_clkpin[winner]
                     cur_ckr <= w_ckr;
                     st      <= ST_DRIVE;
                   end else begin
                     // ⭐⭐ THIS STALL IS THE JITTER TERM J. The EDF winner is
                     // chosen, its release has arrived, and dispatch waits only
                     // because its action word is not in the register yet.
                     // ⛔ A2 budgets J = 1. If this can exceed 1, the shipped
                     // r_i do not hold -- so it is COUNTED, not assumed, and
                     // the maximum is observable for the bench to assert on.
                     // ⚠ ONE COUNTER FOR ALL LANES: `winner` may change while
                     // this is counting, so the run it measures can span two
                     // lanes' waits. That is why it is an AGGREGATE and why
                     // `tb_jlane.v` exists.
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
            // ⛔⛔ THE SELF-CLOCKED ARM IS FIRST INSIDE `OP_SHIFT` BELOW, and
            // the unclocked body after it is untouched -- the whole point of
            // gating on `level = 1` is that every existing
            // `clk_real, level = 0` SHIFT still takes the identical path.
            // ⛔ THE 1.6x ALIAS REFUSAL WRAPS BOTH ARMS AND IS WRITTEN ONCE.
            // The first attempt duplicated it into the clocked arm and
            // `gate_mutant_arms` caught that immediately -- `M_SHIFT_CLK_ALIAS`
            // went from 6 diff lines to 12. A refusal that exists twice can be
            // fixed in one place and left broken in the other.
            // ⛔⛔ THIS COMMENTARY SITS ABOVE THE CASE LABEL ON PURPOSE.
            // `model/gate_program_index.py` requires each program-indexed
            // write's guard within 60 lines; left inside the arm this block
            // pushed the label's own `if (pin_real)` out of that window. The
            // fix is to move the PROSE, never to widen the window -- the gate's
            // docstring records a `clk_real` 30 lines away falsely guarding a
            // deliberately unguarded mutant arm.
            // ⛔⛔ `ck_refuse` IS THE FIRST ARM OF THIS CHAIN, and that is a bug
            // fix. The first version wrote `if (ck_shift & ~ck_degen)` and
            // left the chain alone -- so a refused clocked SHIFT fell
            // through into the UNCLOCKED body and DROVE THE DATA PIN on its
            // way to being refused. MEASURED: `tb_pinrange +MODE=3` on the
            // wrapping route reported "pin edges after load : 1".
            // ⚠ SECOND TIME THIS EXACT MISTAKE: the retire chain had a term
            // added to one arm while a LATER arm (`else if (a_lvl)`) still
            // matched. A guard belongs at the HEAD of a chain, not bolted to
            // a branch of it.
            OP_SHIFT: if (pin_real && !ck_refuse) begin
`ifndef M_SHIFT_CLK_ALIAS
              if (ck_pin == a_pin) begin
                config_err_m <= 1'b1;
                sticky_ovr_m <= 1'b1;
                live_n[cur]  = 1'b0;
              end else begin
`endif
              if (ck_shift) begin
                // ⛔ PHASE ORDER IS DATA-THEN-CLOCK-LOW, THEN CLOCK-HIGH, and
                // it is a SUPPORTED-MODE statement rather than an arbitrary
                // choice: data settling while the clock is low and read on the
                // rise is I2C, and SPI MODES 0 AND 3 -- which covers both FRAM
                // parts. ⚠ SPI MODES 1 AND 2 change data on the RISING edge and
                // are NOT expressible this way; they stay on the unclocked
                // idiom (`level = 0` plus `OP_LEVEL`), which is untouched and
                // still available. A limitation, recorded, not an omission.
                if (ck_is_low) begin
                  // ⛔ `pin_real` LOCALLY, redundant only in the sense that the
                  // case label carries it. A reader of this block -- and the
                  // index gate, which stops at 60 lines and at the enclosing
                  // arm -- should not have to scroll out to learn that a
                  // program-controlled index is bounded. Synthesis folds it.
                  // ⛔⛔ THE DATA BIT IS HELD, NOT DRIVEN HERE (ruling H). It
                  // goes into the hold pipeline and reaches the pin SDA_HOLD
                  // cycles after the clock falls below. At SDA_HOLD = 0 it is
                  // driven immediately, which is the measured defect and the
                  // must-fire build.
                  if (pin_real) begin
                  // ⛔⛔⛔ D3: THE `ck_hold_fits` CLAMP IS GONE FROM **THIS**
                  // SITE, because D1 made it unreachable here. A clocked
                  // open-drain action with `d <= SDA_HOLD` no longer reaches
                  // dispatch at all -- `ck_refuse` stops it at the head of
                  // this chain -- so the clamp's only remaining job here would
                  // be to handle a case the engine refuses to run.
                  // ⛔ AND RULING U RETIRED IT AT THE UNCLOCKED SITE TOO: the
                  // refusal now covers an unclocked open-drain SHIFT that takes
                  // its own clock low, so `build_i2cframe(d <= SDA_HOLD)` is
                  // refused rather than clamped to zero hold.
                  if (SDA_HOLD == 0 || l_mode[cur]) begin
                    if (l_mode[cur]) begin
                      pin_out[a_pin] <= tx_bit & pin_pp[a_pin];
                      pin_oe[a_pin]  <= 1'b1;
                    end else begin
                      pin_out[a_pin] <= 1'b0;
                      pin_oe[a_pin]  <= ~tx_bit;
                    end
                  end else begin
                    // ⛔ OPEN-DRAIN VALUES, UNCONDITIONALLY, AND THE
                    // TERNARIES THAT USED TO BE HERE WERE DEAD CODE. This arm
                    // is reached only when the condition above is FALSE, and
                    // that condition contains `l_mode[cur]` -- so `l_mode` is
                    // provably 0 here and a `l_mode ? a : b` could only ever
                    // take the `b` side. ⭐ FOUND BY THE COVERAGE GATE, which
                    // reported the `cond_then` halves as uncovered: they were
                    // not under-tested, they were unreachable.
                    l_hval[cur] <= 1'b0;
                    l_hoe[cur]  <= ~tx_bit;
                    hold_ld = 1'b1;
                  end
                  end
                  if (clk_real) begin
                    pin_out[ck_pin] <= 1'b0;
                    pin_oe[ck_pin]  <= 1'b1;   // pull/drive LOW
                  end
                end else begin
                  // ⭐ CLOCK HIGH ONLY -- the data pin is NOT rewritten, so the
                  // bit stays on the wire across the rise.
                  // ⛔ OPEN-DRAIN RELEASES rather than driving 1: a peer
                  // stretches by holding the clock LOW, and against a push-pull
                  // high that is a SHORT. This is D2's lesson, and the release
                  // is also what MAKES the stretch observable.
                  // ⛔⛔ M_CK_OD_CLK_DRIVE IS D2's MUST-FIRE NOW, AND IT HAD TO
                  // MOVE HERE. D2's original mutant, M_OD_CLK_PUSHPULL, sits in
                  // the UNCLOCKED arm -- and since the self-clocked rework every
                  // `clk_real & level = 1` SHIFT comes HERE instead, so in that
                  // arm `a_lvl` is always 0 whenever `clk_real` holds. Its
                  // `pin_out <= a_lvl; pin_oe <= 1` then only ever writes the
                  // same pull-low the clean design writes: an EQUIVALENT mutant
                  // no image can kill. Found when `gate_corpus_trace` ran again
                  // after being dark since `7a672b0` (ruling Q2).
                  if (clk_real) begin
                  if (l_mode[cur]) begin
                    pin_out[ck_pin] <= 1'b1 & pin_pp[ck_pin];
                    pin_oe[ck_pin]  <= 1'b1;
                  end else begin
`ifdef M_CK_OD_CLK_DRIVE
                    pin_out[ck_pin] <= 1'b1;
                    pin_oe[ck_pin]  <= 1'b1;
`else
                    pin_out[ck_pin] <= 1'b0;
                    pin_oe[ck_pin]  <= 1'b0;   // RELEASE
`endif
                  end
                  end
                end
              end else begin
              // ⛔⛔⛔ 1.6x -- A SHIFT LANE WHOSE CLOCK PIN IS ITS DATA PIN IS
              // REFUSED. This block writes the DATA pin and then the CLOCK pin,
              // clock SECOND. With `clkpin == pin` the clock assignment
              // OVERWRITES the data bit with `a_lvl`, so at `a_lvl = 0` every
              // 1 bit becomes a 0 -- and NOTHING FLAGGED IT: the wire carries a
              // well-formed frame of the wrong data, which is the
              // silent-corruption class, one level above a wrong number.
              // ⚠ FOUND BY T5.1, AND ONLY REACHABLE THEN. No bench had ever
              // driven the host channel, so every OP_SHIFT in the suite's
              // history ran on an all-zero shift register where losing the 1
              // bits changed nothing observable. `tb_tx` read 8 unexplained pin
              // events per lane, which is exactly the number of 1 bits in each
              // payload.
              // ⭐ WHY AT DISPATCH AND NOT AT HEADER LOAD, which is where 1.6s
              // lives. The hazard needs OP_SHIFT: `l_clkpin` reaches the pins
              // in THIS CASE ARM AND NOWHERE ELSE, so for a lane that never
              // shifts, `clkpin == pin` is a don't-care and refusing it would
              // be a FALSE REFUSAL. At header-load time the chip cannot know
              // whether the lane's program contains a SHIFT -- actions are
              // fetched lazily -- so the correctly scoped check can only be
              // made where the opcode is known. ⚠ `build_five` declares
              // `clkpin == pin` on all five lanes and is LEGAL under this
              // scope, which matters: it is the measurement base for T1's
              // J_lane and for Theorem 3's 35 port-feasible cells, and
              // refusing it would invalidate both for a hazard it cannot hit.
              // ⇒ The toolchain (`pe_asm`) refuses it STATICALLY, where the
              //   whole program is visible; this is the silicon backstop.
              // ⛔ M_SHIFT_CLK_ALIAS removes the refusal, so the guard is
              // PRICED rather than only ever seen to pass.
              // ⛔ THE REFUSAL MUST SUPPRESS **BOTH** WRITES, and the first
              // version of this guard only suppressed the DATA one -- the
              // `else` bound to the data branch and the clock write below ran
              // regardless, driving the aliased pin with `a_lvl`. A refusal
              // that still drives the pin it is refusing to drive is not a
              // refusal; it is the defect with a flag set beside it.
              // ⇒ THE REFUSAL NOW LIVES ONCE, above the clocked/unclocked
              // split, so this arm is covered by it rather than carrying a
              // second copy. It used to be written here.
              // ⛔ `pin_real` LOCALLY HERE TOO: the label's guard is further
              // than 60 lines away now that the clocked arm sits between
              // them, and the index gate correctly refuses to search past
              // the enclosing arm.
              // ⛔⛔ THE SAME HOLD ON THE UNCLOCKED PATH (ruling H), AND IT IS
              // NEEDED HERE TOO -- MEASURED, NOT ASSUMED. This arm is what the
              // CERTIFIED two-action frame runs: `OP_SHIFT(sda, lvl=0,
              // clk=SCL)` puts the data bit on SDA and takes SCL low in one
              // dispatch, exactly the clocked defect's shape, and it measured
              // t_HD;DAT = 0 over 266 transitions. sigrok certified the frame's
              // DECODE, which says nothing about its timing.
              // ⚠ ONLY WHEN THE CLOCK IS GOING LOW. At `a_lvl = 1` the clock
              // rises and the data must already be stable -- holding there
              // would move SDA across the RISE, which is the opposite error.
              // A lane with no real clock pin (an SPI target, where the master
              // supplies SCK) drives immediately for the same reason.
              if (pin_real) begin
              // ⛔ RULING U RETIRED THE CLAMP that stood here
              // (`|| !ck_hold_fits[cur]`): an unclocked open-drain SHIFT whose
              // delay cannot fit the hold is now REFUSED by `ck_holdviol` at
              // the head of this arm, so it never reaches this branch.
              if (SDA_HOLD == 0 || l_mode[cur] || !clk_real || a_lvl) begin
                if (l_mode[cur]) begin
                  pin_out[a_pin] <= tx_bit & pin_pp[a_pin];
                  pin_oe[a_pin]  <= 1'b1;
                end else begin
                  pin_out[a_pin] <= 1'b0;
                  pin_oe[a_pin]  <= ~tx_bit;
                end
              end else begin
                // ⛔ OPEN-DRAIN VALUES ONLY -- same reasoning as the clocked
                // site above: `l_mode[cur]` appears in the condition that sent
                // control here, so it is provably 0 and the ternaries it used
                // to carry were unreachable on their push-pull side.
                l_hval[cur] <= 1'b0;
                l_hoe[cur]  <= ~tx_bit;
                hold_ld = 1'b1;
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
              // GUARDED BY `clk_real`, so a lane that declares PIN_NONE as
              // its clock pin drives no clock -- which is what an SPI TARGET
              // needs, since the master supplies SCK.
              if (clk_real) begin
`ifdef M_OD_CLK_PUSHPULL
              pin_out[ck_pin] <= a_lvl;
              pin_oe[ck_pin]  <= 1'b1;
`else
              if (l_mode[cur]) begin
                pin_out[ck_pin] <= a_lvl & pin_pp[ck_pin];
                pin_oe[ck_pin]  <= 1'b1;
              end else begin
                pin_out[ck_pin] <= 1'b0;
                pin_oe[ck_pin]  <= ~a_lvl;
              end
`endif
              end
              end                             // closes the local pin_real
              end                             // closes the `ck_shift` else
              // the next `end` closes the 1.6x else-begin, which wraps BOTH
              // arms -- see the refusal above the split.
`ifndef M_SHIFT_CLK_ALIAS
              end
`endif
            end
            OP_SHIFTIN, OP_READBIT: if (pin_real && !ck_refuse) begin
              // ⭐⭐ CONDITION (a): A CLOCKED SHIFTIN RELEASES THE DATA PIN ON
              // **BOTH** PHASES. This assignment is unconditional, so it
              // covers every phase: driving SDA during an ACK would fight
              // the peer's acknowledge, which on an open-drain net is a
              // push-pull high against a pull-low -- a SHORT, not a wrong
              // bit. Priced by M_ACK_DRIVES_SDA.
              // ⛔⛔ RULING K: THE RELEASE IS HELD ON A CLOCK-LOW DISPATCH.
              // The FIRST LOW of a clocked SHIFTIN takes SCL down and releases
              // SDA in the same dispatch, so the transition from the last
              // transmitted bit into the ACK slot had ZERO hold -- MEASURED,
              // 14 of 14 SHIFTIN releases at t_HD;DAT = 0 on corpus_i2c
              // (Layer H), the class ruling H fixed on the transmit side and
              // did not reach here. ⇒ On an open-drain lane with a real clock
              // that release now goes through the SAME hold pipeline the
              // transmit path uses and lands SDA_HOLD cycles after the fall.
              // HIGH/COLL dispatches find SDA already released, so releasing
              // there directly moves nothing. The mutant's DRIVE (ack_drv[1])
              // stays direct, so M_ACK_DRIVES_SDA still prices condition (a).
              // ⚠ The pipeline writes the LANE's pin (`l_pin`), as on the
              // transmit side, so the hold applies only when the action names
              // that pin; any other falls back to the direct release, and
              // Layer H would report it.
              // ⛔ W1/W6: ONLY A RELEASE THAT MOVES SDA (`pin_oe[a_pin]`). The
              // later LOW and COLL dispatches find SDA already released; they
              // used to load the pipeline anyway, a no-op on the wire that W1
              // now turns into a dispatch delay -- and COLL followed by the
              // next action's LOW made two hold loads back to back, which is
              // the one shape A2's W1 term cannot bound (W6).
`ifndef M_SHIFTIN_UNHELD
              if (ck_shiftin & clk_real & ~ck_is_high & ~l_mode[cur]
                  & (SDA_HOLD != 0) & ~ack_drv[1] & (a_pin == l_pin[cur])
                  & pin_oe[a_pin]) begin
                l_hval[cur] <= 1'b0;
                l_hoe[cur]  <= 1'b0;
                hold_ld = 1'b1;
              end else
`endif
              // ⛔⛔ RULING W2: THE UNCLOCKED RELEASE IS HELD TOO. In the
              // certified frame the clock fall is a separate `OP_LEVEL` and
              // the release follows one delay later, so its hold was only the
              // inter-dispatch gap minus contention -- MEASURED 14 at d = 16.
              // Through the pipeline it lands SDA_HOLD after the dispatch, on
              // top of that gap, and W1 then keeps the SCL rise behind it.
              // ⚠ ONLY A RELEASE THAT MOVES SDA (`pin_oe[a_pin]` set): one
              // that finds the pin already released changes nothing on the
              // wire, has no hold to protect, and must not cost the lane a
              // W1 delay. M_SHIFTIN_UC_UNHELD restores the direct release.
`ifndef M_SHIFTIN_UC_UNHELD
              if (~ck_shiftin & clk_real & ~l_mode[cur] & (SDA_HOLD != 0)
                  & ~ack_drv[1] & (a_pin == l_pin[cur]) & pin_oe[a_pin]) begin
                l_hval[cur] <= 1'b0;
                l_hoe[cur]  <= 1'b0;
                hold_ld = 1'b1;
              end else
`endif
              pin_oe[a_pin] <= ack_drv[1];      // release to sample (0)
              // ⭐ NEVER TAKEN IN THE CLEAN BUILD -- `ack_drv[1]` is 0 -- so
              // `pin_out` is not written on any SHIFTIN and the unclocked
              // path is unchanged.
              if (ck_shiftin & ack_drv[1]) pin_out[a_pin] <= ack_drv[0];
              if (ck_shiftin & clk_real) begin
                if (ck_is_high) begin
                  // RELEASE, not drive -- see D2. The release is what makes
                  // the stretch observable: the rise happens when the PEER
                  // allows it, and `l_ckwait` is what catches that instant.
                  if (l_mode[cur]) begin
                    pin_out[ck_pin] <= 1'b1 & pin_pp[ck_pin];
                    pin_oe[ck_pin]  <= 1'b1;
                  end else begin
                    pin_out[ck_pin] <= 1'b0;
                    pin_oe[ck_pin]  <= 1'b0;
                  end
                end else begin
                  // LOW and COLL both take the clock down. ⭐ I6: an action
                  // ENDS with the clock low, so the next one's LOW phase
                  // starts from a known level and no program needs a
                  // separating OP_LEVEL between bytes.
                  pin_out[ck_pin] <= 1'b0;
                  pin_oe[ck_pin]  <= 1'b1;
                end
              end
            end
            // ⭐ OP_ARM moves no pin -- it RELEASES the lane on a peer edge.
            // Its state goes in at writeback, below.
            OP_ARM, OP_REARM: ;                 // no pin movement
            // BRANCH_BIT moves no pin; a target outside the store is refused
            OP_BRANCH_BIT, OP_CMP_BRANCH, OP_LOOP: if (br_bad) begin
              config_err_m <= 1'b1;
              live_n[cur]  = 1'b0;
            end
            default: ;
          endcase
          br_take_q <= a_op[1] ? br_loop_take : a_op[0] ? br_cmp_take : br_bit_take;
          st <= ST_WB;
        end

        ST_WB: begin
          // ⛔⛔ RULING 2: the re-arm ADDS TO THE STORED TIMESTAMP, never to
          //    `now`. The relative form drifts k*(r-C) -- 15,260 cycles on a
          //    one-second delay -- and is INVISIBLE at k = 1.
          l_timestamp[cur] <= l_timestamp[cur] + {{(TS_W-DLY_W){1'b0}}, wb_dly};

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
            armed_n[cur]   = 1'b1;
            l_armpin[cur]  <= a_pin;
            l_armedge[cur] <= a_lvl;
            notmo_n[cur]   = (a_dly == {DLY_W{1'b0}});
          end

          // ⭐⭐ THE PHASE, ADVANCED OR RESET, ahead of the opcode case so it
          // happens on every clocked dispatch whichever arm runs.
          // ⛔⛔ THE RESET AT RETIRE **IS** THE ACTION-START RESET, and it is
          // the ruled fix: a new action must begin in LOW. Writing it here,
          // where the PC advances, means it cannot be forgotten by a later
          // arm -- the first attempt let a clocked SHIFTIN inherit the
          // preceding SHIFT's leftover phase and retire after one dispatch.
          // ⛔ IT ALSO COVERS AN **UNCLOCKED** RETIRE, which matters: a
          // clocked action following a plain one must still start in LOW.
          // ⛔ A CHAINING `OP_REARM` RETIRES NOTHING and so resets nothing --
          // correct, because it re-dispatches the SAME action.
          // ⚠⚠ M_CK_NO_PHASE_RESET IS A **CHARACTERISED SURVIVOR**, and saying
          // so is more useful than the reset itself. The ruling diagnosed the
          // original defect as a clocked action inheriting a stale phase, and
          // ordered this reset. It is correct and it is here -- but the mutant
          // that removes it KILLS NOTHING, and the reason is structural: with
          // the phase machine as the model specifies it, every clocked action
          // already LEAVES the phase at LOW (a SHIFT retires from HIGH -> LOW,
          // a SHIFTIN from COLL -> LOW), and power-on resets it too. So the
          // reset is DEFENSIVE -- it covers a lane halted mid-action and
          // restarted -- not load-bearing for any program the suite builds.
          // ⛔⛔ AND THE REAL ROOT CAUSE WAS ELSEWHERE, which this mutant is
          // what proved: the retire chain below used to read
          // `if (a_op != OP_REARM && !ck_hold)`, so a HELD clocked action --
          // which carries `level = 1` BY DEFINITION of the trigger -- fell
          // through into the `else if (a_lvl)` LOOPING-REARM arm and jumped
          // its PC to `l_base`. That is what made an action look like it
          // retired after one dispatch. Correct by DERIVATION, unevidenced by
          // TEST, and recorded rather than papered over with a contrived
          // program -- the same treatment `M_BUF_CHAINFLIP` gets.
`ifdef M_CK_NO_PHASE_RESET
          if (ck_act) l_ckph[cur] <= ck_next;
`else
          if (act_retire)  l_ckph[cur] <= CK_LOW;
          else if (ck_act) l_ckph[cur] <= ck_next;
`endif
          // ⛔ THE REFUSAL HALT -- degenerate bit count (`ck_degen`) or a
          // delay that cannot hold the data (`ck_holdviol`, D1). Checked at
          // WRITEBACK so it fires once per dispatch of the offending action,
          // and the drive arms above are gated on `~ck_refuse` so NO CLOCK
          // EDGE and NO DATA EDGE is emitted for either.
          // ⭐ ONE STICKY FOR BOTH: `config_err` also gates `ST_IDLE`, so a
          // set sticky stops the whole engine dispatching -- the ENGINE-WIDE
          // halt, on top of this lane's own `l_live` clear. The lane clear is
          // not redundant: it is what makes the halt survive a host that
          // clears the sticky without reloading the program.
          if (ck_refuse) begin
            config_err_m <= 1'b1;
            sticky_ovr_m <= 1'b1;
            live_n[cur] = 1'b0;         // HALT: the action has no meaning
          end
          if (ck_act) begin
            // the action's own bit counter: advances on LOW, cleared at the
            // retire that starts the next action. ⛔ NOT `tx_bitp`, which the
            // host-byte load zeroes on the last bit's LOW phase.
            if (act_retire)     l_ckbit[cur] <= {BPW{1'b0}};
            else if (ck_is_low) l_ckbit[cur] <= l_ckbit[cur] +
                                                {{(BPW-1){1'b0}}, 1'b1};
            // ARM THE CAPTURE as the high phase leaves: the clock has just
            // been released and the rise -- whenever the peer allows it --
            // lands in `l_cksamp` during the idle window.
            // ⛔⛔⛔ AFTER THE HIGH PHASE THE LANE IS **PARKED ON THE OBSERVED
            // RISE**, and this is a compliance fix, not an optimisation. The
            // previous build let the capture race the lane's own next dispatch, so
            // a peer holding SCL longer than that gap LOST a bit -- MEASURED: a
            // 500-cycle hold set `clk_stretch_err`, a 50-cycle hold did not. That
            // contradicts A2 Part 4 (the SCL wait is a HARDWARE CONDITION ON THE
            // LANE, never engine occupancy) and N1a/R3 (stretching DELAYS, never
            // loses data); UM10204 sets no upper limit on how long a target may
            // hold SCL low.
            // ⭐⭐ IT REUSES `OP_ARM`'s MACHINERY WHOLE rather than adding a second
            // way to wait: `l_armed` + `arm_hit` already watch a pin for an edge
            // and REBASE the timestamp to `now` when it lands, which IS "released
            // by the rise".
            // ⚠⚠ A FAULT BOUND IS OWED, stated rather than hidden: `l_notmo = 1`
            // makes the wait UNBOUNDED, which compliance requires, but a peer that
            // VANISHES then parks the lane for ever. The ARM alternative
            // (`l_notmo = 0`) bounds the wait at the action's `delay` -- ONE BIT
            // PERIOD -- which is the very bound being removed, and the action word
            // is 24 of 24 bits so no field can carry a second, longer timeout. A
            // fault detector needs a build-time parameter plus per-lane counters
            // (~50 flops), so it is RULED, not assumed.
            // ⛔⛔ OPEN-DRAIN ONLY, AND THAT IS PHYSICS RATHER THAN A
            // CONVENIENCE. Stretching is a peer PULLING A RELEASED LINE LOW;
            // on a PUSH-PULL clock the engine drives both levels and no peer
            // can hold it, so there is nothing to wait for. ⚠ MEASURED THE
            // HARD WAY: parking unconditionally hung the push-pull SPI master
            // lane -- it waited for a rise on a clock it drives itself -- and
            // four `fram_spi` coverage points that the clocked corpus had just
            // PAID went dark again. A regression visible only because the
            // paid debt was recorded.
            if (ck_act & ck_is_high & ck_park_en & ~l_mode[cur]) begin
              armed_n[cur]   = 1'b1;
              l_armpin[cur]  <= ck_pin;
              l_armedge[cur] <= 1'b1;        // a RISE
              notmo_n[cur]   = 1'b1;         // unbounded: a slow peer is legal
              l_ckpark[cur]  <= 1'b1;
            end
            if (ck_shiftin & ck_is_high) begin
              l_ckwait[cur] <= 1'b1;
              l_ckgot[cur]  <= 1'b0;
            end
          end

          case (a_op)
            OP_SHIFT: if (!ck_shift || ck_is_low) begin
              // TX ONLY. Neither `l_rx` nor `rx_bitp` is named here.
              // ⛔ ON A CLOCKED SHIFT ONLY THE LOW PHASE SHIFTS: the high
              // phase emits no new bit, so shifting there would drain the
              // byte at twice the clock rate -- exactly the two-bits-per-
              // clock defect the old corpus idiom had.
              // ⛔⛔ CANDIDATE #8: a byte's FIRST bit came from the queue
              // head (`tx_bit`); its writeback POPS that byte and keeps its
              // remaining bits. Empty queue: an underrun, and the rest of the
              // byte is zeros (aligned -- the next byte starts fresh).
`ifdef M_TX_PRELOAD
              if (1'b1) begin
`else
              if (l_txv[cur]) begin
`endif
                l_tx[cur] <= {1'b0, l_tx[cur][7:1]};
              end else begin
                if (host_valid) begin
                  l_tx[cur] <= {1'b0, host_ord[7:1]};
                  host_pop  <= 1'b1;        // consumed: advance the host FIFO
                end else begin
                  l_tx[cur] <= 8'h00;
                  lane_underrun_m[cur] <= 1'b1;
                end
                l_txv[cur] <= 1'b1;
              end
`ifdef M_SHARED_BITP
              l_bitp_shared <= l_bitp_shared + {{(BPW-1){1'b0}}, 1'b1};
`else
              tx_bitp[cur] <= tx_bitp[cur] + {{(BPW-1){1'b0}}, 1'b1};
`endif
            end
            // ⛔⛔ ON A CLOCKED SHIFTIN THE ACCUMULATE HAPPENS ONLY AT A
            // CONSUME POINT, and takes the bit the OBSERVED RISE captured --
            // never a live pin read, which at writeback is the wrong instant
            // by construction (the clock has only just been released).
            // ⛔ AND A CONSUME POINT WITH NOTHING PENDING IS REPORTED: the
            // peer held the clock past this lane's next dispatch, so the bit
            // is not late, it is ABSENT. The substituted 0 reads as an ACK,
            // which is why this needs a status bit and not a comment.
            OP_SHIFTIN: if (!ck_shiftin || ck_consume) begin
              if (ck_consume & ~l_ckgot[cur]) begin
                clk_stretch_err_m <= 1'b1;
                sticky_ovr_m    <= 1'b1;
              end
              if (ck_consume) l_ckgot[cur] <= 1'b0;
              // RX ONLY. Neither `l_tx` nor `tx_bitp` is named here, which
              // is what makes the TX host load at `a_cnt` REACHABLE: this
              // reset used to clear the pointer that load was waiting on.
              // REVERSED ON AN MSB-FIRST LANE: the accumulator shifts the
              // first-received bit toward bit 0, so an MSB-first protocol's
              // byte arrives reversed and is corrected as it completes. The
              // expression is identical in both arms below -- the mutant only
              // changes WHICH POINTER decides when a byte is complete -- and
              // it is commented HERE rather than inside an arm because
              // `gate_mutant_arms` counts a comment inside an `ifdef` as the
              // arm wrapping more than its delta, and is right to.
              l_rx[cur] <= {rx_bit_sel, l_rx[cur][7:1]};
`ifdef M_SHARED_BITP
              l_bitp_shared <= l_bitp_shared + {{(BPW-1){1'b0}}, 1'b1};
              if (l_bitp_shared == a_cnt - {{(BPW-1){1'b0}}, 1'b1}) begin
                rx_data <= l_order[cur] ? rx_asm_rev : rx_asm;
`else
              rx_bitp[cur] <= rx_bitp[cur] + {{(BPW-1){1'b0}}, 1'b1};
              if (rx_bitp[cur] == a_cnt - {{(BPW-1){1'b0}}, 1'b1}) begin
                rx_data <= l_order[cur] ? rx_asm_rev : rx_asm;
`endif
                rx_lane <= cur;
                rx_push <= 1'b1;
`ifdef M_SHARED_BITP
                l_bitp_shared <= {BPW{1'b0}};
`else
                rx_bitp[cur] <= {BPW{1'b0}};
`endif
              end
            end
            // ⭐ READBIT accumulates into the RX register and moves NO
            // pointer -- it is the single-bit sample (an I2C ACK, a UART stop
            // bit), so there is no byte to complete.
            OP_READBIT: l_rx[cur] <= {rx_bit, l_rx[cur][7:1]};
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
          // ⭐⭐⭐ A CLOCKED ACTION MID-BYTE RETIRES NOTHING. While `ck_hold_eff`
          // is high the PC does not advance, the head is not invalidated and
          // the buffer does not swap -- so the SAME action is dispatched
          // again and emits its next phase. Not a new mechanism: a chaining
          // `OP_REARM` already re-dispatches by not advancing the PC.
          // ⛔⛔ THIS IS ALSO AMENDMENT A1 IN SILICON. Theorem 3 argued from
          // "a dispatch leaves EXACTLY one slot per lane to be refilled"; a
          // held dispatch leaves ZERO. The bound survives because it only
          // ever needed an UPPER bound and a re-dispatch owes fewer -- but
          // the proof text had to stop saying "exactly", and
          // docs/J_LANE_PROOF.md Amendment A1 is where it does.
          // ⛔⛔ THE HOLD IS THE **FIRST** ARM OF THIS CHAIN, and that is a bug
          // fix, not a style preference. The first version bolted
          // `&& !ck_hold_eff` onto the `a_op != OP_REARM` arm and left the
          // chain alone -- so a HELD clocked action, which carries
          // `level = 1` BY DEFINITION of the trigger, fell through into the
          // `else if (a_lvl)` LOOPING-REARM arm and jumped its PC to
          // `l_base`. It looked exactly like retiring after one dispatch.
          // ⇒ A term added to a chained if/else must be checked against
          //   EVERY later arm, and the arms here are selected by `a_lvl`,
          //   which the new trigger also uses.
          if (ck_hold_eff) begin
            // a held clocked action retires NOTHING: no PC advance, no
            // invalidation, no buffer swap. Amendment A1 in silicon.
            // ⛔⛔ AND F1's ZERO-FLOP REBASE RESTS ON THAT, which is why the
            // emptiness of this arm is now a CHECKED invariant rather than a
            // comment. `ck_dly` reads the lane's delay out of
            // `l_act[hix[gi]]` during the park -- sound only because a held
            // action does not invalidate its slot, so the prefetch cannot
            // refill it with the NEXT action's word underneath the park. If it
            // ever did, the park would release on some other action's delay.
            // ⛔ M_CK_HOLD_RETIRES MAKES A HELD ACTION RETIRE LIKE A NORMAL
            // ONE -- invalidate AND advance the PC -- and that is the mutation
            // that actually reaches the hazard: the slot goes free, the
            // prefetch refills it from the NEW pc, and the parked lane
            // releases on a delay belonging to the NEXT action.
            // ⚠ IT TAKES BOTH LINES, AND FINDING THAT OUT COST TWO ATTEMPTS.
            // Invalidating alone leaves the PC put, so the refill re-reads the
            // same address and restores an identical word. Advancing the PC
            // alone leaves the slot VALID, so no refill happens at all and
            // nothing is re-read. Only together do they change what the park
            // reads -- which is why a must-fire has to be built against the
            // MECHANISM rather than against the name of the invariant.
            // ⚠ M_CK_HOLD_INVAL -- invalidating the slot on a hold -- was
            // tried FIRST as the must-fire and DOES NOT break A1, which is
            // worth recording rather than discarding. Because the PC does not
            // advance during a hold, the prefetch re-reads the SAME address
            // and restores an IDENTICAL word, so the delay the park reads is
            // still right. It is not harmless -- it costs a refill per
            // DISPATCH instead of per ACTION, which is precisely the port
            // demand Amendment A1 says a re-dispatch does not owe, and it
            // moved re-dispatch counts 1229 -> 1061 on `corpus_i2c` -- but it
            // is a `D*`/port defect, not a delay-corruption one.
`ifdef M_CK_HOLD_INVAL
            l_actv[hix[cur]] <= 1'b0;
`endif
`ifdef M_CK_HOLD_RETIRES
            l_actv[hix[cur]] <= 1'b0;
            l_pc[cur] <= l_pc[cur] + ACT_BYTES[AW-1:0];
`endif
          end else if (a_is_br) begin
            if (a_op[1]) l_loop[cur] <= lp_next;   // LOOP's counter step
            // ⭐ THE PC CHOICE, merged into the writeback: retire as any
            // action does (invalidate the head, swap), to the target or on
            l_pc[cur]   <= br_taken ? br_tgt : l_pc[cur] + ACT_BYTES[AW-1:0];
            l_actv[hix[cur]] <= 1'b0;
            if (SPL > 1) l_sel[cur] <= !l_sel[cur];
          end else if (a_op != OP_REARM) begin
            l_pc[cur]   <= l_pc[cur] + ACT_BYTES[AW-1:0];
`ifndef M_BUF_NOINVAL
            l_actv[hix[cur]] <= 1'b0;   // ⛔ INVALIDATION
`endif
`ifdef M_PFETCH_BOTH_INVAL
            l_actv[six[cur]] <= 1'b0;
`endif
          // ⭐ THE SWAP IS GUARDED ON DEPTH. With SPL = 1 `l_sel` must stay
          // 0: `hix` ignores it at that depth, so a toggling select would be
          // harmless BY ACCIDENT, and a bit that changes while nothing reads
          // it is how a later reader inherits a value nobody maintained.
          // ⛔ THIS COMMENT SITS OUTSIDE THE `ifndef`, AND THE DRIFT GUARD IS
          // WHY. It was written inside the arm and `gate_mutant_arms.py` went
          // red: "5 COMMENT line(s) inside an arm ... DRIFT: 7 diff lines,
          // expected 2". A mutant arm wraps the MINIMAL DELTA and nothing
          // else -- the same rule that caught the 1.6s config guard landing
          // in an `M_NO_PRIME` arm, where a fix that is inside a mutant arm
          // is not in the design.
`ifndef M_BUF_SWAP
            if (SPL > 1) l_sel[cur] <= !l_sel[cur];
`endif
          end else if (a_lvl) begin
            l_pc[cur]   <= l_base[cur];         // loop back to the start
`ifndef M_BUF_NOINVAL
            l_actv[hix[cur]] <= 1'b0;
`endif
`ifndef M_BUF_SWAP
            if (SPL > 1) l_sel[cur] <= !l_sel[cur];
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
          // ⛔⛔ SILICON FIX #2 (ruling TX1): ON A CLOCKED SHIFT THE LOAD IS
          //    GATED TO THE LOW PHASE. `tx_bitp` advances on LOW only, but this
          //    test ran at EVERY writeback, so the HIGH phase after the 7th
          //    LOW already read `tx_bitp == a_cnt` and loaded the next byte:
          //    the 8th LOW put that byte's first bit on the wire and every
          //    later byte drifted one bit (5B, 5B, ... went out 00, B5, 6A,
          //    D5). Every clocked check measured edges and timing, never
          //    values, so the dispatch stream was exact and the bytes wrong.
          //    `M_TX_LOAD_ANYPHASE` restores the ungated test.
`ifdef M_SHARED_BITP
          if (a_op == OP_SHIFT && (!ck_shift || ck_is_low) && l_bitp_shared == a_cnt) begin
`else
`ifdef M_TX_LOAD_ANYPHASE
          if (a_op == OP_SHIFT && tx_bitp[cur] == a_cnt) begin
`else
          if (a_op == OP_SHIFT && (!ck_shift || ck_is_low) && tx_bitp[cur] == a_cnt) begin
`endif
`endif
            // ⛔⛔ CANDIDATE #8: NO PRELOAD at the end of a byte. The next
            // byte is taken LAZILY at its own first bit (above; reversed there
            // on an MSB-first lane), so the register never carries a byte the
            // host did not push -- the reset 0x00 used to go out first on
            // every TX lane.
`ifdef M_TX_PRELOAD
            if (host_valid) begin
              l_tx[cur] <= host_ord;
              host_pop  <= 1'b1;
            end else lane_underrun_m[cur] <= 1'b1;
`else
            l_txv[cur] <= 1'b0;
`endif
`ifdef M_SHARED_BITP
            l_bitp_shared <= {BPW{1'b0}};
`else
            tx_bitp[cur] <= {BPW{1'b0}};
`endif
          end

          st <= ST_IDLE;
          jitter_cnt <= {JW{1'b0}};
        end

        default: st <= ST_IDLE;
      endcase

      // ---- ⛔⛔ THE SDA HOLD EXPIRY (ruling H) --------------------------
      // ⛔ IT RUNS EVERY CYCLE AND AT BLOCK LEVEL, not inside `case (st)`: the
      // countdown continues while the engine dispatches other lanes, which is
      // the point -- the hold is a PIN pipeline and must not depend on the FSM
      // reaching any state. Putting it in `ST_DRIVE` would stall a hold
      // whenever the lane that owns it is not the one being served.
      // ⛔ AND IN *THIS* BLOCK, for the reason the rebase below gives: this is
      // the one sequential block that writes `pin_out`/`pin_oe`, and a second
      // one would be N_PINS multiple-driver nets -- the defect that made this
      // engine unsynthesizable once while simulating cleanly.
      // ⭐ ENGINE DISPATCH TIMING IS UNTOUCHED. Nothing here reads or writes
      // `st`, `l_timestamp`, `ready` or the EDF key, so A2's C and J are
      // unaffected by construction rather than by measurement -- though the
      // measurement is taken anyway, because "by construction" is exactly the
      // kind of claim that stops holding silently.
      // ⚠ `l_pin[i]` IS RANGE-GUARDED HERE TOO. It is the fifth site of the
      // family `model/gate_program_index.py` enumerates: a program-controlled
      // pin index reaching an array, where `PINW = 4` encodes 16 values and
      // only N_PINS are real.
      // ⭐ TF1: the hold LOAD, raised by a DRIVE arm. It sits BEFORE the
      // countdown on purpose: the countdown's write is the later one, so for
      // a lane whose counter is still running the countdown wins -- the same
      // order the loads had when they were written inside the DRIVE arms.
      // ⭐ TM1: the load is RECORDED here and lands through `l_hcnt` next
      // cycle; only an idle counter takes it (the old NBA order).
`ifdef M_TM1_UNREG
      if (hold_ld) l_hcr[cur] <= SDA_HS[HOLDW-1:0];
`else
      hl_v <= hold_ld & hz_q[cur];
      hl_l <= cur;
`endif
      for (i = 0; i < N_LANES; i = i + 1) begin
        // ⭐ TF1: `hz_q` is `l_hcnt == 0` for the NEXT cycle, written by the
        // same branches that write the counter, in the same priority.
        if (l_hcnt[i] != {HOLDW{1'b0}})
          hz_q[i] <= (l_hcnt[i] == {{(HOLDW-1){1'b0}}, 1'b1});
        else if (hold_ld && (i[LW-1:0] == cur))
          hz_q[i] <= (SDA_HS[HOLDW-1:0] == {HOLDW{1'b0}});
        // ⛔ W1: the pin lands at SDA_SETUP + 1, SDA_HOLD cycles after the
        // load as before; the remaining SDA_SETUP counts are the setup the
        // gate on `ready` enforces before the lane's next dispatch.
        if (l_hcnt[i] != {HOLDW{1'b0}}) begin
          if (l_hcnt[i] == SDA_SETUP1[HOLDW-1:0]) begin
            if (l_pin[i] < N_PINS[PINW-1:0]) begin
              pin_out[l_pin[i]] <= l_hval[i];
              pin_oe[l_pin[i]]  <= l_hoe[i];
            end
          end
          l_hcr[i] <= l_hcnt[i] - {{(HOLDW-1){1'b0}}, 1'b1};
        end
      end

      // ---- sticky ovr: a lane was still ready when its own next release
      //      arrived, i.e. the queue-depth-one assumption (1.6a) was violated.
      for (i = 0; i < N_LANES; i = i + 1) begin
        if (l_live[i] && ready[i] && busy && (i[LW-1:0] != cur))
          sticky_ovr_m <= sticky_ovr_m;         // observed, not an error here
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
      // ⭐ THE SHARED PRESCALER. It runs only while SOME lane is parked and
      // clears when none is, so a short legitimate stretch leaves no residue
      // to shorten the NEXT lane's fault bound.
      if (!ck_any_park)  ck_pre <= 14'd0;
      else if (ck_tick)  ck_pre <= 14'd0;
      else               ck_pre <= ck_pre + 14'd1;
      // ⭐ CI1: load the push-pull capture slot at a push-pull clocked
      // SHIFTIN's HIGH-phase writeback; it fires when it reaches 0 (CI2's
      // instant: 1 more cycle for a `uio` clock pad, 2 for a `uo_out` one)
      if (ppc_set) begin
        ppc_v <= 1'b1;
        ppc_l <= cur;
        ppc_n <= (ck_pin >= 8) ? 2'd2 : 2'd1;
      end else if (ppc_v) begin
        if (ppc_n == 2'd0) ppc_v <= 1'b0;
        else               ppc_n <= ppc_n - 2'd1;
      end
      for (i = 0; i < N_LANES; i = i + 1) begin
        // ⭐⭐ THE CLOCKED SHIFTIN'S CAPTURE, in the idle window after the
        // high phase. ⛔ FIRST RISE ONLY -- `l_ckwait` clears here -- so a
        // peer that glitches the clock twice cannot overwrite the bit it
        // already answered with. The same "capture DISARMS" property the ARM
        // below needs, for the same reason.
        // ⛔⛔ THE FAULT BOUND. A parked lane counts cycles; past
        // CK_STRETCH_TO the bus is declared FAULTY -- the lane halts, the
        // park and the arm are released and the sticky is raised. ⭐ IT
        // HALTS RATHER THAN PROCEEDING, for the reason the ARM timeout
        // already gives: a program that proceeded could not tell "the peer
        // answered" from "the peer never answered", and would read a frame
        // out of an idle line.
        if (l_ckpark[i]) begin
          if (l_ckwdog[i] >= CK_STRETCH_TO[6:0]) begin
            live_n[i]       = 1'b0;         // HALT this lane
            armed_n[i]      = 1'b0;
            l_ckpark[i]     <= 1'b0;
            l_ckwait[i]     <= 1'b0;
            clk_stretch_err_m <= 1'b1;        // STICKY -- status bit 7
            sticky_ovr_m    <= 1'b1;
          end else if (ck_tick) begin
            l_ckwdog[i] <= l_ckwdog[i] + 7'd1;
          end
        end else begin
          l_ckwdog[i] <= 7'd0;
        end
        if (ck_hit[i]) begin
          l_cksamp[i] <= ck_bit[i];
          l_ckgot[i]  <= 1'b1;
          l_ckwait[i] <= 1'b0;
          l_ckpark[i] <= 1'b0;
        end
        if (arm_hit[i]) begin
          armed_n[i] = 1'b0;                    // capture DISARMS: a second
                                                // edge must not re-rebase and
                                                // slide the grid forward on
                                                // every peer transition
          // ⭐ THE REBASE. `ck_rebase` is `now` for an ordinary `OP_ARM` and
          // `now + d` for a lane released from a CLOCKED PARK -- see its
          // declaration for why, which is a measured compliance failure.
`ifndef M_NO_REBASE
          l_timestamp[i] <= ck_rebase[i];
`endif
        end
      end

      // ---- ⭐ TF2-R3: the one write of the live/armed/no-timeout registers,
      // and the registered release term computed from their NEXT values.
      // `rel_q` therefore holds, every cycle, what the combinational
      // `l_live & arrived & ~(armed & no-timeout)` held -- and a lane halted
      // this cycle is NOT eligible next cycle. M_TF2_LIVE_LATE reads the
      // CURRENT `l_live` instead: the halted lane stays eligible one cycle.
      for (i = 0; i < N_LANES; i = i + 1) begin
        l_live[i]  <= live_n[i];
        l_armed[i] <= armed_n[i];
        l_notmo[i] <= notmo_n[i];
        // ⛔ NO `elsif`: the drift and kill gates discover mutants from
        // `ifdef` / `ifndef` only, so each mutant gets its own arm.
`ifdef M_TF1_LATE
        rel_q[i] <= l_live[i] & ~tf_diff(now, l_timestamp[i]) & ~(l_armed[i] & l_notmo[i]);
`else
        rel_q[i] <= (
`ifdef M_TF2_LIVE_LATE
                     l_live[i]
`else
                     live_n[i]
`endif
                     ) & ~tf_diff(now_n, ts_n[i]) & ~(armed_n[i] & notmo_n[i]);
`endif
      end
    end
  end

  // ⛔⛔ C IS 3, NOT 2, AND THIS COMMENT USED TO SAY 2. The dispatch FSM spends
  // two cycles per action in SERVICE (ST_DRIVE then ST_WB) -- but it is a
  // THREE-STATE CYCLE, because ST_WB assigns `st <= ST_IDLE` unconditionally
  // and the next dispatch decision cannot be taken until the cycle after
  // writeback. So the engine delivers one action every THREE cycles, and the
  // number a response-time analysis charges is that SPACING, not the
  // occupancy. `svc_cycles/svc_jobs = 2.00` measured the occupancy and was
  // exactly right about it.
  // ⭐ MEASURED, NOT ARGUED: `docs/PREREG_C_SAT.md` pre-registered the minimum
  // inter-dispatch spacing at 2 and named 3 as the falsifier;
  // `test/run_csat.py` measured 3 on four arms, over 32,677 spacings in which
  // another lane was ALREADY ELIGIBLE during the predecessor's writeback and
  // not one of them 2. Margins are re-quoted in `model/a2/gate_c3_requote.py`
  // (shipped min margin 12 -> 11, bar 4).
  // ⚠ STILL OWED: the post-synthesis path report. This is a simulation
  // reading, and "three states therefore C = 3" would be the same
  // same-author re-derivation the old comment correctly refused -- which is
  // why the spacing was measured directly instead of inferred from the state
  // count a second time.
  wire _unused_eng = &{l_pin[0], 1'b0};

  // ⭐ step 2: the per-bank refill-address copies (see the s_wraddr_bk port)
  // ⛔ ONE BIT PER pe_dup_ffe, not a W-bit parameterised register: yosys
  // names a kept PARAMETERISED module `$paramod\...`, and LibreLane's
  // unmapped-cell checker reads a `$` cell type as an unmapped internal --
  // the first step-2 canary stopped at synthesis on exactly the 4 copies.
  genvar gwa, gwb;
  generate
    for (gwa = 0; gwa < ACT_BYTES; gwa = gwa + 1) begin : g_wraddr
      for (gwb = 0; gwb < AW; gwb = gwb + 1) begin : g_bit
        pe_dup_ffe u_wra (.clk(clk), .rst_n(rst_n), .en(pst == P_REQ),
                          .d(paddr[gwb]), .q(s_wraddr_bk[gwa*AW + gwb]));
      end
    end
  endgenerate

endmodule

