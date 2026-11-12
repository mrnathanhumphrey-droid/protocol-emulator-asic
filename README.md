![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg) ![](../../workflows/fpga/badge.svg)

# Protocol Emulator

**One programmable engine that speaks UART, SPI, I²C, 1-Wire and USB low-speed —
with its worst-case timing analysed, not asserted.**

An entry to the Jane Street ASIC competition, for the Tiny Tapeout `sg13cmos5l`
shuttle (IHP 130 nm). A program loaded over the host pins decides which protocol
the silicon speaks, so it can speak one nobody had written down at tape-out, as
long as it fits the instruction set and the timing envelope.

Five protocol lanes share one engine under non-preemptive EDF. Their response
times are bounded, the bound is cross-checked against an independent
real-time-analysis library, and the RTL is held to it by a test suite in which
every check has been shown to fail on a deliberately broken design.

## Contents

- [Status](#status)
- [How it works](#how-it-works)
- [What v2 adds](#what-v2-adds)
- [Timing](#timing)
- [How it is verified](#how-it-is-verified)
- [On real hardware](#on-real-hardware)
- [Reproduce it](#reproduce-it)
- [Repository map](#repository-map)
- [Open items](#open-items)

## Status

Pre-submission, for the March 2027 `sg13cmos5l` shuttle.

| | v1 — tagged `v1-lock` | v2 — in development |
|---|---|---|
| **Die** | 6×4 tiles, 50 MHz | 8×4 tiles, 60 MHz |
| **Program store** | flops | IHP SRAM macro (256 × 32) |
| **Instruction set** | 8 opcodes | 12 opcodes, 32-bit action word |
| **Protocols** | UART, SPI master + target, I²C, 1-Wire | + USB low-speed device reflexes, + protocol inference (PIT) |
| **Timing** | **closed**: harden of record, slow-corner setup +2.676 ns, hold +0.105 ns, 0 violations at every corner; precheck and gate-level cocotb green | **open**: last signed-off reading −1.882 ns slow-corner setup at 60 MHz, the worst path in PIT's GCD step; the fixes are in the RTL and the routed result is being measured; the bar is +2.4 ns; the v2 harden of record follows |
| **Verification** | every gate green at the tag | the same suite, grown to 102 gates; records that depend on the final layout are declared stale until the v2 lock |

v1 is the fallback and stays locked. v2 replaces it only when it closes to the
same bar: a harden of record, the full gate suite, and bench witnesses.

---

## How it works

A program is a table: five **lane headers**, then **action words**. The engine
picks the lane whose deadline is earliest, fetches its next action, and drives
the pins.

```
          ui_in   prog · wr/push · ptr · tx nibble  (synchronised, strobe-qualified)
             │
   ┌─────────▼──────────┐      ┌──────────────────────────────┐
   │  loader (pointer)  │─────▶│  pe_store — IHP SRAM macro   │  512 B program
   └────────────────────┘      │  + USB response buffer       │  (of 1 KB)
                               └──────────────┬───────────────┘
                                              │ one shared fetch port
   ┌──────────────────────────────────────────▼───────────────────┐
   │  pe_engine                                                   │
   │   · non-preemptive EDF scheduler over 5 lanes                │
   │   · double-buffered action prefetch (head + spare per lane)  │
   │   · edge capture: reactive release on a peer transition      │
   │   · branch / compare / loop, USB NRZI + unstuff + CRC16      │
   │   · per-pin drive class (push-pull / open-drain / tri-state) │
   └──────────────┬──────────────────────────────┬────────────────┘
                  │ uio[7:0]                     │ uo_out[3:0]
          inputs, open-drain,              push-pull protocol
          tri-state (must release)         outputs (always driven)
```

**The instruction set.** One 32-bit action word per instruction. An action
carries a pin, a level, a delay and a count; a lane header carries the lane's
pins, drive mode, bit spacing, scheduling deadline and program address.

| | opcodes |
|---|---|
| drive and sample | `LEVEL` `SHIFT` `SHIFTI` `SHIFTIN` `READBIT` `START` `STOP` |
| time | `ARM` (wait for an edge, with timeout) · `REARM` (periodic release) |
| decide | `BRANCH_BIT` · `CMP_BRANCH` (byte vs immediate, under a mask) · `LOOP` (per-lane counter) |

Two choices carry most of the weight:

- **`REARM` adds to the stored timestamp, never to "now".** The relative form
  drifts by the service time on every repeat — 15,260 cycles over a one-second
  delay — and the drift is invisible after a single repeat.
- **`ARM` is the reactive release.** `pin` names the pin to watch, `level` picks
  rise or fall, `delay` is the timeout. The deadline comparator the scheduler
  already has *is* the timeout, so no second comparator was needed.

**The toolchain.** `model/pe_proto.py` turns a protocol transaction — an I²C read
with its repeated START, an SPI frame, a 1-Wire exchange — into actions, and
`model/pe_asm.py` assembles them. What comes back is the image plus a verdict:
accepted, or rejected with the failing lane and inequality named, together with
the program's jitter and pyRTA's margins. "Reprogrammable within its timing" is
something a reader can run rather than take on trust.

**Two pin banks.** `uio` carries everything that must be able to stop driving:
inputs, open-drain lines, tri-state outputs. `uo_out` has no output enable, so
it carries push-pull only. An I²C line must release so the other side can pull
it low, and an SPI target's MISO must release so several targets can share it —
on `uo_out` either would fight the bus.

Pin map, load protocol, serial framing and readback:
[`docs/HOST_INTERFACE.md`](docs/HOST_INTERFACE.md).

---

## What v2 adds

**Decisions on chip.** `BRANCH_BIT`, `CMP_BRANCH` and `LOOP` let a lane react to
what it receives — an address, a PID, a status bit — without a round trip to the
host. A two-pin `ARM` releases when both of its lines sit at one level — USB's
SE0.

**USB low-speed device reflexes** on one lane: NRZI receive, bit unstuffing and
re-anchoring on edges, CRC16 checked on chip and exposed as a virtual pin, a
response buffer in the SRAM's spare half, bus reset, device address and token
check. The host microcontroller builds the packets; the chip meets the
turnaround. Enumerating as a keyboard on a laptop is the goal and is not yet
done.

**PIT — the Protocol Inference Tile.** Point it at an unknown bus and it records
the edges, classifies each wire (clock, synchronous data, framing, I²C bus,
ambiguous), measures period and phase, decodes asynchronous frames and recovers
the CRC polynomial with its init and xorout — on chip, written to the store.
The CRC solver is checked bit for bit against a frozen golden model on 3,696
sets. A round trip — sniff, emit a spec, assemble, emulate, sniff again — runs
in simulation.

**The SRAM store.** The program lives in the IHP `RM_IHPSG13_1P_256x32` macro,
powered the way Tiny Tapeout's SRAM example does it. No raw input pin reaches
the macro's inputs: a gate proves every one of its 76 input bits is driven only
through registers.

**Clock-domain crossing, proved.** Every host input is synchronised. The data
nibble is not — it is sampled only on the synchronised write edge — and a
yosys induction proof shows no flop changes on a raw qualified pin unless that
edge is up: 11,640 of 11,641 flop bits proven, the one remaining being the
declared synchroniser.

---

## Timing

The five lanes are derived from the protocols, not chosen:

| lane | `T` | `C` | `n` | `t` | `J` | `D_tol` |
|---|---|---|---|---|---|---|
| UART-tx 115200 | 434 | 3 | 1 | 434 | 1 | 216 |
| SPI-master 1 MHz | 25 | 3 | 1 | 25 | 1 | 23 |
| I²C Fast-mode | 45 | 3 | 1 | 45 | 2 | 15 |
| UART-rx 115200 | 4210 | 3 | 10 | 421 | 1 | 213 |
| SPI-target (MISO 1 MHz, MOSI 500 kHz) | 400 | 3 | 8 | 50 | 1 | 17 |

Cycles at **50 MHz**: period `T`, service time `C` (measured), release jitter
`J`, tolerated response `D_tol`. `n` and `t` describe the bursty lanes — UART-rx
is 10 bits spaced 421 apart, SPI-target 8 bits spaced 50 — because a periodic
model using the outer period alone would understate the burst.

**The scheduler.** Non-preemptive EDF with a deadline-limited interference
bound. Jitter enters through inflated arrival counts `⌈(t + J_j)/T_j⌉` for every
interfering lane, and `J` is derived from the program rather than assumed.

```
r = {16, 12, 7, 15, 9}      min margin 11      bar ≥ 4
```

The published bound is pyRTA's. Our own analysis is a cross-check that may only
be *more* pessimistic — and a gate fails if it is ever smaller. Removing a lane
can only help non-preemptive EDF, so the five-lane numbers bound every subset;
that argument is checked rather than trusted: 24 of 31 pin-feasible subsets, 54
(lane, subset) pairs, 0 disagreements with pyRTA.

**Refill spacing.** `d_min ≥ D* = 20 → J = 1`: a lane whose actions are at least
20 cycles apart never waits on the shared fetch port — measured (zero refill
stalls at every port-feasible point of the d = 20–60 runs) and proved in Lean on
a model of the engine ([`docs/J_LANE_PROOF.md`](docs/J_LANE_PROOF.md)).

**Why one shared engine, not a barrel.** A barrel gives each lane a fixed time
slice: isolation comes free, but every idle slot is wasted and the slice sets
every lane's resolution. Here a lane costs a header, not a hardware context, and
what sharing costs is bounded — the response times above — rather than designed
away.

### The clock

Programs are written in real time — a rate, or a minimum in nanoseconds — and
the toolchain converts them to cycles for each target, with a 5% guard band on
every minimum. The clock is written once per target: `info.yaml` (the chip,
60 MHz) and `fpga/board.yaml` (the FPGA board, 50 MHz), and a gate holds every
other copy to those two.

- **The formal analysis holds at 50 MHz**, the clock it was derived at. Its
  re-certification at 60 MHz, including USB's data-dependent receive length, is
  an open item.
- **60 MHz is verified in simulation and by the assembler's per-target checks.**
  The shipped I²C, SPI and UART programs are built for both clocks and their wire
  timing must match in nanoseconds.

**Rates, with their conditions.** I²C has three numbers: 397 kHz from the
formula, 393.7 kHz in simulation (ideal edges), 370.4 kHz on the FPGA prototype
with ~3.2 kΩ pull-ups — the chip waits for each real rise of SCL, so the rate
depends on the bus by design. UART receive is certified down to 232 cycles per
bit, about 258.6 kbaud at 60 MHz, verified across a ±3% baud-error sweep.

---

## How it is verified

The method matters more than the pass count, so here is the method.

**Two independent simulators, cycle-exact at the pins.** Icarus and Verilator
run the same RTL on the same stimulus and must produce byte-identical traces of
every port, every cycle. This found two testbench races that neither simulator
could see alone, and a seed sweep that had silently been testing nothing.

**Every check is tested by breaking the design.** Each check has a deliberate
defect that must turn it red, and the kill is confirmed by the failure
*message*, not just the exit code. Drive an open-drain clock high instead of
releasing it, and the bus check reports 2,680 cycles of a hard-driven high where
the clean design has none.

**Every check is also stubbed.** A meta-test replaces each gate's check with one
that always passes and requires the gate to go red anyway — so a must-fire that
no longer exercises the real check is caught.

**Independent tools carry real weight, and that is checked too.** pyRTA,
TChecker, IMITATOR and sigrok each decide a verdict somewhere; removing each one
must turn its gate red, so no verdict quietly falls back to our own arithmetic.

**Property proofs, not only equivalence.** The Lean model proves the engine
never stalls a dispatch when every lane's actions are at least D* apart
(`dstar`, `dstar29`, `dstar39`, resting only on Lean's standard axioms, checked
in CI). The model is tied to the RTL by replaying RTL traces through it on every
push.

**Checks on the netlist that ships.** Some properties only exist after
synthesis. The tool flow's own synthesis — not a generic one — is run in CI to
confirm that registers duplicated for timing survive as separate copies, with
the duplication removed as the must-fire.

| | |
|---|---|
| `ci/run_gates.sh` — every push, 10 parallel shards | **102 gates** |
| `model/gate_mutant_kills.py` — injected defects | **122** with a named killer; **5** declared survivors, each with the reason no check should see it |
| `model/gate_meta.py` — every check stubbed to pass | the gate must still go red |
| `model/gate_formal_miters.py` — SymbiYosys | **2** equivalence proofs; **4** mutants refuted |
| `model/gate_cdc_qual.py` — yosys induction | no flop changes on a raw pin outside its strobe |
| `test/run_pit_gcd.py` — PIT CRC solver vs golden | 3,696 sets bit-exact (nightly); a fixed 214-set subset every push |

### Things found this way

- **Program byte 0 could not be read back.** The read pointer advanced in the
  same cycle the read was requested — and byte 0 is the header that decides
  which physical pin lane 0 drives.
- **An open-drain clock was driven push-pull.** An I²C peer stretching the clock
  would have met a short circuit, not a stretch.
- **75 of the SRAM's 76 input bits had a raw path from an input pin.** A raw
  pin on a macro's input is metastability inside a black box no property can
  see into; the write strobe and data are now registered, and a gate holds it.
- **A timing fix that only the real synthesis could undo.** Duplicated selects
  stayed separate in every generic synthesis we ran and merged back in the
  tool flow's own. Hence the check on the netlist that ships.

---

## On real hardware

The v1 RTL runs on an Artix-7 FPGA prototype (Puzhi PA100T-EDU), talking to real
parts on a breadboard:

| protocol | part | what was shown |
|---|---|---|
| UART-rx 115,200 baud | USB-UART adapter | every byte received at nominal and ±2.5% baud |
| I²C Fast-mode | MB85RC256V FRAM | write, read back, data kept across a power-off; 370.4 kHz measured |
| 1-Wire | DS18B20 temperature probe | ROM, Convert T and scratchpad read; CRCs valid; every slot inside the datasheet windows |

The I²C and 1-Wire runs are **recorded bench witnesses**: a logic analyser
captured the wire, the decode and timings live in `fpga/witness/`, and CI
re-checks that record on every push — bytes against the program, the part's
answers, the timing windows, and the SHA-256 of the program that ran. The UART
run (2026-10-12) was measured but its raw output was not kept, so it is a dated
account rather than evidence CI can re-check. Bench runs of the v2 RTL follow.

---

## Reproduce it

Everything that gates a push, in one command:

```bash
bash ci/run_gates.sh                 # or one shard: --shard fast
```

By area:

```bash
python test/corpus.py && python test/gate_corpus_trace.py   # two simulators, cycle-exact
python test/run_local.py                                     # cocotb at the pins
python model/gate_formal_miters.py                           # SymbiYosys equivalence
PYRTA_SRC=/path/to/pyrta/src python model/a2/run_a2.py      # the timing analysis
```

Tools: Icarus Verilog, Verilator 5.053 (pinned), Yosys, SymbiYosys, Python 3.11;
CI pins the OSS CAD Suite by date. The harden uses Tiny Tapeout's flow at
LibreLane 3.1.0.dev4 and runs only at deliberate checkpoints.

## Repository map

```
src/        the chip: project.v (top, pins, host interface, PIT), pe_engine.v,
            pe_store.v, the IHP cell and SRAM bindings, the PDN script
test/       cocotb suite, Verilog benches, the two-simulator trace corpus, and
            behavioural peers (SPI and I²C FRAM, DS18B20) written from datasheets
model/      the timing model, the CI gates, the protocol front-end and assembler
model/a2/   the EDF analysis, jitter, and the pyRTA cross-check
formal/     SymbiYosys equivalence proofs
lean/       the Lean model of the engine and its proofs
fpga/       the Artix-7 prototype: board top, host scripts, recorded witnesses
ci/         the gate runner, its shard map and pass-token table
docs/       specifications, proofs and the decision record
```

The documents are indexed in [`docs/README.md`](docs/README.md).

## Open items

- **60 MHz timing closure and the v2 harden of record.** Last signed-off
  reading −1.882 ns against a bar of +2.4 ns, the worst path in PIT's GCD
  step. Its fixes are in the RTL — registered step decode, a registered
  divisor mask, per-register-group select copies, a log-depth compare — all
  bit-exact on 3,696 sets with zero added cycles; the routed result is being
  measured.
- **Re-certify the timing analysis at 60 MHz**, including USB's data-dependent
  receive length.
- **USB enumeration end to end** — as a keyboard, on a laptop.
- **Bench runs of the v2 RTL** on the FPGA prototype; hardware runs of the SPI
  target (simulation-witnessed in all four modes today).
- **The trace corpus at gate level.** The cocotb suite runs on the hardened
  netlist; the corpus bench is ports-only and can, but has not yet.

---

Nathan Humphrey · Apache-2.0
