![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg) ![](../../workflows/fpga/badge.svg)

# Protocol Emulator

A table-driven serial-protocol engine on 6×4 Tiny Tapeout tiles, IHP
`sg13cmos5l`, 50 MHz. One piece of silicon speaks UART, SPI (master and target)
or I²C depending on the program loaded into it — including a protocol nobody had
written down when the die was taped out, provided it fits the instruction set and
the timing envelope.

The interesting part is not that it toggles pins. It is that **the timing is
analysed rather than asserted**: five concurrent protocol lanes are scheduled by
a non-preemptive EDF engine whose worst-case response times are bounded, the
bound is cross-checked against a third-party real-time-analysis library, and the
RTL is held to it by a test suite where every guard has been shown to fail on a
mutant.

> **Status: private, pre-submission.** Not yet public. Gate-level results for the
> current suite have not landed yet — see [Open items](#open-items).

---

## Architecture

A program is a table: five **lane headers** followed by **action words**. The
engine schedules lanes, fetches actions, and drives pins.

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

### The instruction set

Eight opcodes, each one action word: `LEVEL`, `SHIFT`, `SHIFTIN`, `READBIT`,
`START`, `STOP`, `ARM`, `REARM`. An action word carries a pin, a level, a delay
and a count; a lane header carries its data pin, clock pin, drive mode, inner
spacing `t`, mode bits (`HALF_HIGH`: a clocked HIGH phase of `d/2`;
`CLK_INV`: an inverted `uo_out` clock), scheduling deadline and base address.
The service time `C` (3 cycles, measured) belongs to the timing analysis, not
to the program.

Two design choices carry most of the weight:

- **`REARM` adds to the stored timestamp, never to `now`.** The relative form
  drifts `k·(r−C)` — 15,260 cycles on a one-second delay — and is invisible at
  `k = 1`.
- **`ARM` is the reactive release.** Its existing fields do all the work: `pin`
  names the pin to watch, `level` selects rise or fall, `delay` is the timeout,
  and `delay == 0` means *no* timeout. No second comparator, no second register.
  The deadline comparator already present *is* the timeout.

### Two pin banks, and why

`uio` carries everything that must be able to **stop driving** — inputs,
open-drain, tri-state. `uo_out` carries push-pull only, because it has no output
enable and is always driven. Both banks are exactly full at 8 and 4.

That split is not cosmetic. An SPI target's MISO must be able to release so
several targets can share a line; on `uo_out` it would contend with every other
device on the bus. An open-drain I²C line and a tri-stated target output are
different protocols making the same demand.

Full pin map, load protocol, serial framing and the readback contract:
[`docs/HOST_INTERFACE.md`](docs/HOST_INTERFACE.md).

---

## Timing

Five lanes, derived from the protocols rather than chosen:

| lane | `T` | `C` | `n` | `t` | `J` | `D_tol` |
|---|---|---|---|---|---|---|
| UART-tx 115200 | 434 | 3 | 1 | 434 | 1 | 216 |
| SPI-master 1 MHz | 25 | 3 | 1 | 25 | 1 | 23 |
| I²C Fast-mode 397 kHz | 45 | 3 | 1 | 45 | 2 | 15 |
| UART-rx 115200 | 4140 | 3 | 10 | 414 | 1 | 213 |
| SPI-target 1 MHz | 400 | 3 | 16 | 25 | 1 | 17 |

Cycles at 50 MHz. `n`/`t` describe the bursty lanes: UART-rx is 10 bits of 414,
SPI-target 16 bits of 25, so a periodic model with the outer period alone
understates the burst.

**UART receive speed.** `pe_asm` certifies the UART-rx program down to 232
cycles per bit, which is up to about 215.5 kbaud at the 50 MHz design clock.
The simulation bench verifies it at that limit across a ±3% baud-error sweep.
The fastest standard rate inside the limit is 115,200 baud: 434 cycles per
bit, with a 0.006% rate error. That rate is also verified on an Artix-7
prototype of the unchanged RTL, against an independent USB-UART adapter at
nominal and ±2.5% baud. 230,400 baud would need 217 cycles per bit, which is
outside the certified range.

**Non-preemptive EDF, with a deadline-limited interference bound.** The
scheduling key `D_sched` is deliberately separate from the requirement `D_tol`.
Release jitter `J` enters the interference term through inflated arrival counts
`⌈(t + J_j)/T_j⌉` — not just the subject's own release — and `J` is derived as a
function of the program, not asserted as a chip constant.

Shipped program:

```
r = {16, 12, 7, 15, 9}      min margin 11      bar ≥ 4
```

| | ours | pyRTA | bar |
|---|---|---|---|
| shipped `J = 1` | 9 | **11** — the published bound | PASS both |

Ours is a pessimistic cross-check: 2 cycles above pyRTA on I2C and 1 on UART-rx, where the exact model checker (TChecker) agrees with pyRTA.

`d_min ≥ D* = 20 → J = 1` — **measured**, not proved: zero refill-queueing
stall at every port-feasible point of the d = 20..60 runs
(`test/run_dstar_check.py`). The written proof is under revision
(`docs/J_LANE_PROOF.md`, Amendment A2).

**The primary bound is pyRTA's**, not ours; ours is a cross-check that is only
allowed to be *more* conservative, and a gate fails if it is ever smaller.

Non-preemptive EDF is monotone under removing lanes, so the five-lane numbers
bound every subset — but that is an argument, and three arguments of that exact
shape have already fallen to a foreign tool in this project. So it is
enumerated: 24 of 31 non-empty pin-feasible subsets, 54 (lane, subset) pairs,
**0 disagreements with pyRTA and 0 envelope breaches**.

---

## Verification

The method matters more than the pass count, so here is the method.

**Two independent simulators, cycle-exact at the pins.** Icarus and Verilator
run the same RTL against the same stimulus and must produce byte-identical port
traces — `uo_out`, `uio_out`, `uio_oe`, `uio_in`, every cycle. Neither is a model
of the other, so an agreement is two engines witnessing each other. The bench is
ports-only on purpose so the same artefact can run against the gate-level
netlist, where internal names do not exist.

This found two bench races that **neither simulator could see alone** — each
produced a clean, self-consistent, plausible trace. It also found that a
`--x-initial unique` seed sweep without the matching runtime flag is a no-op,
which had made an entire pass of that gate vacuous.

**Every guard is priced by a mutant.** A check that has only ever been seen to
pass has unknown strength. Each one has a deliberate defect that must make it
red, and the kill is certified by the failure *message*, not just the exit code:
restore the open-drain clock-pin defect and the cross-program invariant reports
196 violations against 0 clean; restore the read-before-write and three
`--x-initial` seeds stop agreeing.

**Foreign tools are load-bearing, and that is checked too.** 13 gates name an
external tool — pyRTA for response times, TChecker for timed-automata
reachability, yosys for structural properties — and `price_gates.sh` removes
each tool in turn and requires its gate to go **red**, so no verdict can quietly
come from our own arithmetic.

| suite | result |
|---|---|
| `model/a2/run_a2.py` — timing and scheduling | **30 of 30**, one lane table, digest `b4e51034e283` |
| `model/price_gates.sh` — foreign-tool dependence | **13 of 13 go red** when the tool is removed |
| `test/gate_corpus_trace.py` — two-simulator corpus | **7 of 8**, 1 open, 0 failed |
| `test/run_local.py` — cocotb at the pins | **7 of 7** |
| `test/run_mutants.py` — double-buffer state | **4 of 4** die, 0 of a wrong reason |
| `model/f2_flop_driven_outputs.py` — structural | **24 of 24** output bits flop-or-constant |
| `model/gate_reset_audit.py` — initial state | 2,087 unreset flops, **5 of 5 groups allowlisted with a stated reason** |
| `test/yosys_check.sh` — synthesis | clean, 0 multi-driver, static assertion fires |

### Things found this way

- **Program byte 0 was unreadable** through the serial readback — the pointer
  incremented in the same cycle the read was requested. Byte 0 is lane 0's pin
  header, so the one byte a host could not verify decided which physical pin
  lane 0 drives.
- **An open-drain lane's clock pin was driven push-pull.** A peer stretching I²C
  by holding SCL low against that is a short, not a stretch — and the peer model
  already exported a pull-low stretch enable the engine could not honour.
- **Ruling 1.5 had never been implemented.** The per-pin drive-mode construction
  that makes "an open-drain pin drives a 1" unsatisfiable did not exist; the only
  discipline was a hand-written branch per opcode path, and a later third branch
  duly got it wrong. Now built, masked at the output flop's D input so the pin
  stays a register Q.

---

## Layout

```
src/        project.v (top, pins, serial host view)  pe_engine.v  pe_store.v
test/       cocotb suite + Verilog benches + the two-simulator trace corpus
            fram_spi.v / fram_i2c.v — behavioural MB85RS64V / MB85RC256V peers
model/      the timing model, the gates, and the mutation harness
model/a2/   non-preemptive EDF analysis, jitter, the pyRTA cross-check
docs/       HOST_INTERFACE.md + the decision record (PHASE1_CLOSEOUT*, SPEC_V4_*)
```

Every doc names its own reproduce command. `docs/` is the durable record; when it
disagrees with anything else, the docs win.

## Running it

```bash
# the timing suite (pyRTA is NOT vendored -- point PYRTA_SRC at a clone)
PYRTA_SRC=/path/to/pyrta/src python model/a2/run_a2.py
PYRTA_SRC=/path/to/pyrta/src bash model/price_gates.sh

# RTL at the pins, and the same suite runs at gate level in CI
python test/run_local.py

# two simulators, cycle-exact, across the protocol corpus
python test/corpus.py && python test/gate_corpus_trace.py

# synthesis, structural, initial-state
bash test/yosys_check.sh && python model/f2_flop_driven_outputs.py
python model/gate_reset_audit.py
```

`dev` is the working branch; the ~3.5 h harden runs only on pushes to `cmos5l`,
so gate-level results land at deliberate checkpoints instead of being cancelled
by the next commit.

## Open items

Named rather than omitted.

- **Gate level is unverified for the current suite.** The bench is built to run
  there unchanged; the first harden meant to land is in flight.
- **No program can address a peer yet.** The payload register is loaded from the
  host over the same `uio` bank the protocol pins use, and the SHIFT/clock phase
  the ISA intends is unruled. So an SPI master clocks an invalid opcode and a
  conforming device correctly stays High-Z — which also blocks an I²C ACK and
  therefore any peer-driven clock-stretch test. One ruling unblocks all of it.
- **Two synthetic refill-load programs are not pin-map-legal** — they need five
  push-pull pins where the ruled map provides four. They still measure refill
  contention correctly; they are just not configurations the chip can be wired
  into.
- **The trace corpus is ports-only and 1,500 cycles per program.** A divergence
  that never reaches a pin inside the window is invisible to it.
- No timing closure claim. Only the real harden produces slack.

## Silicon

| | |
|---|---|
| process | IHP `sg13cmos5l` |
| tiles | 6×4 |
| clock | 50 MHz |
| cells | 16,517 |
| flops | 2,933 |
| flow | Tiny Tapeout / LibreLane |

Author: Nathan Humphrey. Apache-2.0.
