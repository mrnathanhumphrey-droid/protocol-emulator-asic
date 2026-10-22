![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg) ![](../../workflows/fpga/badge.svg)

# Protocol Emulator

An entry to the Jane Street ASIC competition: a programmable serial-protocol
engine for the Tiny Tapeout shuttle on IHP `sg13cmos5l`, in 6×4 tiles at 50 MHz.
The same silicon speaks UART, SPI (master or target), I²C or 1-Wire depending on the program
loaded into it — and it can speak a protocol nobody had written down when the
die was taped out, as long as that protocol fits the instruction set and the
timing envelope.

The interesting part is not that it toggles pins. Five protocol lanes share one
engine, scheduled by non-preemptive EDF, and **their worst-case timing is
analysed rather than asserted**: response times are bounded, the bound is
cross-checked against an independent real-time-analysis library, and the RTL is
held to it by a test suite in which every check has been shown to fail on a
deliberately broken design.

## Contents

- [Status](#status)
- [How it works](#how-it-works)
- [Timing](#timing)
- [How it is verified](#how-it-is-verified)
- [On real hardware](#on-real-hardware)
- [Reproduce it](#reproduce-it)
- [Repository map](#repository-map)
- [Open items](#open-items)
- [Silicon](#silicon)

## Status

Pre-submission, for the March 2027 `sg13cmos5l` shuttle.

| | |
|---|---|
| **Done** | RTL frozen; every CI gate green on every push; UART, SPI master, SPI target (all four modes), I²C and 1-Wire programs verified in simulation; UART, I²C and 1-Wire also on an FPGA prototype with real parts |
| **Measured, not yet of record** | local hardens close at 50 MHz with positive slack at three densities; the CI harden of record must reproduce them |
| **Open** | gate-level simulation of the full suite; hardware runs of the SPI target — see [Open items](#open-items) |

---

## How it works

A program is a table: five **lane headers**, then **action words**. The engine
picks the lane whose deadline is earliest, fetches its next action, and drives
the pins.

```
         ui_in[7:5]  PROG_MODE / WR / PTR_RST
             │
   ┌─────────▼──────────┐      ┌──────────────┐
   │  loader (pointer)  │─────▶│  pe_store    │  2**AW bytes, flop-backed
   └────────────────────┘      └──────┬───────┘
                                      │ one shared fetch port
   ┌──────────────────────────────────▼───────────────────────────┐
   │  pe_engine                                                   │
   │   · non-preemptive EDF scheduler over 5 lanes                │
   │   · double-buffered action prefetch (head + spare per lane)  │
   │   · edge capture: reactive release on a peer transition      │
   │   · per-pin drive class (push-pull / open-drain / tri-state) │
   └──────────────┬──────────────────────────────┬────────────────┘
                  │ uio[7:0]                     │ uo_out[3:0]
          inputs, open-drain,              push-pull protocol
          tri-state (must release)         outputs (always driven)
```

**Eight opcodes**, one action word each: `LEVEL`, `SHIFT`, `SHIFTIN`,
`READBIT`, `START`, `STOP`, `ARM`, `REARM`. An action carries a pin, a level, a
delay and a count. A lane header carries the lane's data and clock pins, its
drive mode, its bit spacing, a scheduling deadline and its program address.

**The toolchain.** `model/pe_proto.py` turns a protocol transaction — an I²C
read with its repeated START, an SPI frame, a 1-Wire exchange — into actions, and
`model/pe_asm.py` assembles them. What comes back is the image plus a verdict:
accepted, or rejected with the failing lane and inequality named, together with
the program's computed jitter and pyRTA's margins. That is what makes
"reprogrammable within its timing" something a reader can run rather than take
on trust.

Two choices carry most of the weight:

- **`REARM` adds to the stored timestamp, never to "now".** The relative form
  drifts by the service time on every repeat — 15,260 cycles over a one-second
  delay — and the drift is invisible after a single repeat.
- **`ARM` is the reactive release.** Its existing fields do all the work: `pin`
  names the pin to watch, `level` picks rise or fall, `delay` is the timeout, and
  `delay = 0` means no timeout. The deadline comparator the scheduler already has
  *is* the timeout, so no second comparator was needed.

**Two pin banks.** `uio` carries everything that must be able to stop driving:
inputs, open-drain lines, tri-state outputs. `uo_out` has no output enable, so it
carries push-pull only. Both banks are exactly full, at 8 and 4. The split is not
cosmetic: an I²C line must release so the other side can pull it low, and an
SPI target's MISO must release so several targets can share it — on `uo_out`
either would fight every other device on the bus.

Pin map, load protocol, serial framing and readback:
[`docs/HOST_INTERFACE.md`](docs/HOST_INTERFACE.md).

---

## Timing

The five lanes are derived from the protocols, not chosen:

| lane | `T` | `C` | `n` | `t` | `J` | `D_tol` |
|---|---|---|---|---|---|---|
| UART-tx 115200 | 434 | 3 | 1 | 434 | 1 | 216 |
| SPI-master 1 MHz | 25 | 3 | 1 | 25 | 1 | 23 |
| I²C Fast-mode 397 kHz formula, 393.7 kHz sim, 370.4 kHz board | 45 | 3 | 1 | 45 | 2 | 15 |
| UART-rx 115200 | 4210 | 3 | 10 | 421 | 1 | 213 |
| SPI-target: MISO 1 MHz; MOSI capture 500 kHz | 400 | 3 | 8 | 50 | 1 | 17 |

All in cycles at 50 MHz: period `T`, service time `C` (measured), release jitter
`J`, tolerated response `D_tol`. `n` and `t` describe the bursty lanes — UART-rx
is 10 bits spaced 421 apart (the fastest peer it is verified to decode back to
back, 3% fast), SPI-target 8 bits spaced 50 (one event per bit, at
the master's 1 MHz clock) — because a periodic model using the outer period
alone would understate the burst. The SPI target answers the master's clock one
bit per edge, so its period is the master's claimed maximum SCK, declared when
the program is built; a program that leaves it undeclared is refused.

**The scheduler.** Non-preemptive EDF with a deadline-limited interference
bound. The scheduling key is kept separate from the requirement `D_tol`, and
jitter enters the interference term through inflated arrival counts
`⌈(t + J_j)/T_j⌉` for every interfering lane, not only the one being analysed.
`J` is derived from the program rather than assumed as a chip constant.

Worst-case response times for the shipped program, and the margin against the
requirement:

```
r = {16, 12, 7, 15, 9}      min margin 11      bar ≥ 4
```

| | ours | pyRTA | bar |
|---|---|---|---|
| shipped `J = 1` | 9 | **11** — the published bound | PASS both |

The published bound is pyRTA's. Our own analysis is a cross-check that may only
be *more* pessimistic — 2 cycles above pyRTA on I²C, 1 on UART-rx, where an exact
model checker (TChecker) agrees with pyRTA — and a gate fails if it is ever
smaller.

Removing a lane can only help non-preemptive EDF, so the five-lane numbers bound
every subset. That is an argument, and this project has seen arguments of
exactly that shape fail against an independent tool, so it is checked instead:
24 of 31 non-empty pin-feasible subsets, 54 (lane, subset) pairs, 0
disagreements with pyRTA.

**Refill spacing.** `d_min ≥ D* = 20 → J = 1`: a lane whose actions are at
least 20 cycles apart never waits on the shared fetch port. This is
**measured** — zero refill stalls at every port-feasible point of the d = 20–60
runs (`test/run_dstar_check.py`) — and proved in Lean on a model of the engine
(`lean/JLane`), under two stated assumptions, below. The written argument is
[`docs/J_LANE_PROOF.md`](docs/J_LANE_PROOF.md).

**Why one shared engine, not a barrel.** A barrel gives each lane a fixed time
slice: isolation comes free, but every idle slot is wasted and the slice sets
every lane's resolution. Here a lane costs a header, not a hardware context.
Five lanes share one engine and are served by deadline, and what sharing costs
is bounded — the response times above — rather than designed away.

**Rates, with their conditions.**

- **I²C** has three numbers: 397 kHz from the formula (`d + d/2 + L_SYNC` =
  126 cycles), 393.7 kHz measured in simulation (127 cycles, ideal edges; the
  formula is one cycle short), and 370.4 kHz measured on the FPGA prototype
  (~3.2 kΩ pull-ups, breadboard; range 365.0–374.5). The chip waits for each real rise of SCL before timing the high
  phase, so the rate depends on the bus's pull-ups and capacitance by design. A
  simulation with the measured rise time reproduces the measured rate.
- **UART receive.** `pe_asm` certifies the UART-rx program down to 232
  cycles per bit, which is up to about 215.5 kbaud at the 50 MHz design clock.
  The simulation bench verifies it at that limit across a ±3% baud-error sweep,
  and the FPGA prototype measured every byte at ±2.5%. The timing analysis
  admits peers only inside that verified ±3%.
  The fastest standard rate inside the limit is 115,200 baud: 434 cycles per
  bit, with a 0.006% rate error. 230,400 baud would need 217 cycles per bit,
  which is outside the certified range.

---

## How it is verified

The method matters more than the pass count, so here is the method.

**Two independent simulators, cycle-exact at the pins.** Icarus and Verilator run
the same RTL on the same stimulus and must produce byte-identical traces of every
port, every cycle. Neither is a model of the other, so agreement is two engines
vouching for each other. This found two testbench races that neither simulator
could see alone — each produced a clean, plausible trace — and a seed sweep that
had silently been testing nothing.

**Every check is tested by breaking the design.** A check that has only ever been
seen to pass has unknown strength, so each one has a deliberate defect that must
turn it red, and the kill is confirmed by the failure *message*, not just the exit
code. For example: drive an open-drain clock high instead of releasing it, and the
bus check reports 2,680 cycles of a hard-driven high where the clean design has
none.

**Independent tools carry real weight, and that is checked too.** pyRTA
(response times), TChecker and IMITATOR (timed-automata model checking) and
sigrok (protocol decoding) each decide a verdict somewhere. `model/price_gates.sh`
removes each tool in turn and requires its gate to go red, so no verdict can
quietly fall back to our own arithmetic.

**Property proofs, not only equivalence.** The Lean model proves the engine
never stalls a dispatch when every lane's actions are at least D* apart
(theorems `dstar`, `dstar29`, `dstar39`; CI checks that they rest only on Lean's
standard axioms). The scope is stated in the theorems: they assume a response
bound and a branch budget as hypotheses, and the model is tied to the RTL by
replaying RTL traces through it on every push, not by a proof.

**Formal equivalence where the RTL was restructured.** The tree-shaped lane
select is proved equal to the serial loop it replaced, and the one-hot dispatch
pick to the indexed mux, with SymbiYosys on the shipped RTL text (`formal/`).
Each proof has mutants that must produce a counterexample.

| check | result |
|---|---|
| `ci/run_gates.sh` — every push | **68 of 68** gates |
| `test/gate_corpus_trace.py` — two simulators, protocol corpus | **10 of 10**, 0 open |
| `model/gate_mutant_kills.py` — injected defects | **50 of 56** killed, each by its named check; the other 6 are declared survivors, each with the reason no check should see it |
| `model/gate_formal_miters.py` — SymbiYosys | **2 proofs** hold; 4 mutants refuted |
| `model/price_gates.sh` — tool dependence | **13 of 13** red when the tool or fix is removed |
| `model/f2_flop_driven_outputs.py` — structure | **24 of 24** output bits flop-driven or constant |
| `model/gate_reset_audit.py` — initial state | 2,145 of 3,449 flops unreset, in **5 of 5** groups allowlisted with a reason |
| `model/a2/run_a2.py` — timing analysis (needs pyRTA) | 48 gates; run at each checkpoint |

### Things found this way

- **Program byte 0 could not be read back.** The read pointer advanced in the
  same cycle the read was requested. Byte 0 is lane 0's pin header — so the one
  byte a host could not verify was the one that decides which physical pin lane 0
  drives.
- **An open-drain clock was driven push-pull.** An I²C peer stretching the clock
  by holding SCL low would have been a short circuit, not a stretch.
- **"An open-drain pin never drives a 1" was not built in.** The spec required it
  by construction; the RTL had only a hand-written branch per opcode, and a later
  branch got it wrong. It is now enforced once, at the output register's input.

---

## On real hardware

The unchanged RTL runs on an Artix-7 FPGA prototype (Puzhi PA100T-EDU), talking
to real parts on a breadboard:

| protocol | part | what was shown |
|---|---|---|
| UART-rx 115,200 baud | USB-UART adapter | every byte received at nominal and ±2.5% baud |
| I²C Fast-mode | MB85RC256V FRAM | write, read back, data kept across a power-off; 370.4 kHz measured |
| 1-Wire | DS18B20 temperature probe | ROM, Convert T and scratchpad read; CRCs valid; every slot inside the datasheet windows |

The I²C and 1-Wire runs are **recorded bench witnesses**: a logic analyser
captured the wire, the decoded transaction and timings were written to
`fpga/witness/`, and CI re-checks that record on every push — the bytes on the
wire against the program's feed, the part's answers, the timing windows, and the
SHA-256 of the program that ran. It is not a hardware run in CI; it is the
bench's evidence, kept honest by the repository.

---

## Reproduce it

Everything that gates a push, in one command:

```bash
bash ci/run_gates.sh
```

By area:

```bash
# two simulators, cycle-exact, across the protocol corpus
python test/corpus.py && python test/gate_corpus_trace.py

# cocotb at the pins
python test/run_local.py

# formal equivalence of the dispatch select (SymbiYosys)
python model/gate_formal_miters.py

# the timing analysis -- pyRTA is not vendored; point PYRTA_SRC at a clone
PYRTA_SRC=/path/to/pyrta/src python model/a2/run_a2.py
PYRTA_SRC=/path/to/pyrta/src bash model/price_gates.sh

# structure and initial state
python model/f2_flop_driven_outputs.py && python model/gate_reset_audit.py
```

Tools: Icarus Verilog, Verilator 5.053 (pinned), Yosys, SymbiYosys, Python 3.11.
CI pins the OSS CAD Suite by date. The ~3.5-hour harden runs only on pushes to
`cmos5l`, so gate-level results land at deliberate checkpoints.

## Repository map

```
src/        the chip: project.v (top, pins, host interface), pe_engine.v, pe_store.v
test/       cocotb suite, Verilog benches, the two-simulator trace corpus, and
            behavioural peers (SPI and I²C FRAM, DS18B20) written from datasheets
model/      the timing model, the CI gates, the protocol front-end and assembler
model/a2/   the EDF analysis, jitter, and the pyRTA cross-check
formal/     SymbiYosys equivalence proofs
lean/       the Lean model of the engine and its proofs
fpga/       the Artix-7 prototype: board top, host scripts, recorded witnesses
ci/         the gate runner and its pass-token table
docs/       specifications, proofs and the decision record
```

The documents are indexed, by what each one is for, in
[`docs/README.md`](docs/README.md).

## Open items

- **The SPI target is witnessed in simulation only**, against a master model on
  its own clock: all four modes at 1 MHz, MOSI capture at 500 kHz. Under
  five-lane contention at shipped rates (every other lane busy, every clock
  phase visited) the worst bit reaches the pad in 8 cycles against A2's bound
  of 10 (r = 6 ≤ D_tol 17); with I²C at A2's envelope deadline, 10 against 13.
  The host must lead its first SCK edge by
  at least 6 cycles (120 ns measured, worst over every clock phase; 280 ns is
  the contract) after CS falls,
  which is more CS setup than a typical SPI FRAM needs, and hold CS through
  its final sampling edge. A transaction cut short desynchronises the lane
  until the host reloads the program. Hardware runs follow.
- **Gate-level simulation of the full suite is owed.** The bench is ports-only so
  it can run on the netlist unchanged.
- **The CI harden of record is pending.** Local hardens show slow-corner setup
  slack of +1.87 / +2.68 / +1.78 ns at 57 / 60 / 63 % density with hold clean;
  the harden of record must reproduce them.
- **Two synthetic refill-stress programs are not pin-map-legal** — they need five
  push-pull pins where the chip has four. They still measure refill contention;
  they are just not configurations the chip can be wired into.
- **The trace corpus sees only the ports**, 8,000 cycles per program (200,000
  for the five-lane stress program). A divergence that never reaches a pin inside
  the window is invisible to it.

## Silicon

| | |
|---|---|
| process | IHP `sg13cmos5l` |
| tiles | 6×4 |
| clock | 50 MHz |
| flops | 3,449 (Yosys, pre-layout) |
| flow | Tiny Tapeout / LibreLane |

Nathan Humphrey · Apache-2.0
