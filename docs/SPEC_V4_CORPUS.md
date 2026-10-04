# Broadening the two-simulator comparison — the trace corpus

Wilson's BROADEN ruling after `53623c2`. The cycle-exact result was true and
narrow: `uio_out` and `uio_oe` were **constant across the whole trace**, so the
agreement was carried almost entirely by `uo_out`, and the open-drain bank, the
tri-state MISO, the peer-driven inputs and the edge-capture path contributed
nothing.

## Result

**5 of 6 arms cycle-exact, 1 open with a stated cause, 0 failed.**

| arm | ports it must move | result |
| --- | --- | --- |
| `corpus_i2c` | `uio_oe` (4 values) | cycle-exact, phases 1 and 7 |
| `corpus_sptgt` | `uio_out`, `uio_oe` | cycle-exact, phases 1 and 7 |
| `corpus_uartrx` | `uo_out`, `uio_in` | cycle-exact, phases 1 and 7 |
| `corpus_all5` | all four (31/3/7/41 values) | cycle-exact, phases 1 and 7 |
| **async-clear arm** | `uio_oe[MISO]`, CS off-edge | **cycle-exact** |
| `corpus_spim` | `uio_in[MISO]` | **OPEN** — needs a ruling, below |

Each arm also passes the 3-seed `--x-initial` sweep with the rand-reset
precondition asserted, at every phase.

## Why the first result was narrow: it was the programs

Every image this project had built — `smoke`, `census`, `five`, `chain`,
`stress` — drives `UO0..UO3`, which are pins 8..11, the **`uo_out` bank**.
`build_census`'s own docstring says it is "a coverage program, not a protocol
… its pin waveform means nothing". The trace had nothing to show on `uio`
because no program had ever asked for anything there.

**And both FRAM peers were wired into nothing.** `test/fram_spi.v` and
`test/fram_i2c.v` were lint-clean in two simulators and instantiated by no
bench at all — "SPI master → SPI FRAM peer" had never once run against the DUT.
A peer that compiles is not a peer that is connected.

## All five lanes fit, and "12 against 8" is superseded

`PHASE1_CLOSEOUT_PART4.md` frames the pin budget as 12 protocol pins against 8
`uio` and lists three maximal wireable configurations. That predates the
two-bank ruling. Computed from `PINS_DIR`:

- `bank_need(all five) = (8, 4)` — `uio` needs exactly 8, `uo_out` exactly 4
- `addressable_pins() = 12 = N_PINS`, and `feasible_ruled(all five) = True`

Both banks are exactly full, so **a five-lane program is pin-feasible** and the
allocation is forced up to ordering. `corpus_all5` is that program.

⭐ The ordering is **confirmed by the RTL rather than chosen to match it**:
walking the lanes in shipped order puts SPI-target's CS on `uio[6]` and its
tri-state MISO on `uio[7]`, and `project.v` independently declares `CS_PIN = 6`,
`MISO_PIN = 7`. `corpus.py` asserts that agreement at import, because those are
the async-release path's build parameters — a silent disagreement would drive CS
on one pin and watch the enable of another.

| pin | bank | lane | signal |
| --- | --- | --- | --- |
| 0 | `uio[0]` | SPI-tx | MISO (in) |
| 1–2 | `uio[1:2]` | I²C | SCL, SDA (open-drain) |
| 3 | `uio[3]` | UART-rx | RX (in) |
| 4–6 | `uio[4:6]` | SPI-target | SCLK, MOSI, CS (in) |
| 7 | `uio[7]` | SPI-target | MISO (tri-state) |
| 8 | `uo_out[0]` | UART-tx | TX (push-pull) |
| 9–11 | `uo_out[1:3]` | SPI-tx | SCLK, MOSI, CS (push-pull) |

The map is **generated** into `test/pinmap.vh` and included by the bench, so
there is no second copy to drift — the `lane_digest` lesson applied to a pin map.

## `uio_in` is now in the trace

Five of the eight `uio` bits are peer-driven **inputs**. The first comparison
recorded `uo_out`, `uio_out` and `uio_oe` only, so every peer-driven edge and
the whole edge-capture path was **invisible to the comparison**, not merely
unexercised.

## The precondition, and why it is per program

Only three `uio` bits are ever driven by the engine: I²C's two open-drain pins
and SPI-target's tri-state MISO. So "every program must make `uio_out`/`uio_oe`
non-constant" is satisfiable only by a program containing **I²C or
SPI-target**. For SPI-master, UART-tx and UART-rx the ruled map puts every
driven pin on `uo_out` and leaves their `uio` pin an input — those lanes move
`uio_in`. Demanding `uio_oe` of them would be unsatisfiable, and the obvious
"fix" (putting the master on `uio`) would violate the ruling that `uio` is for
pins that must be able to stop driving.

Each program therefore declares the ports it must move, and the gate checks
that claim against the trace it actually produced.

**Must-fire: the precondition rejects the old census image.** Fed to the
all-lane expectations, `census_image.hex` gives `uo_out` 3 distinct values and
`uio_oe` **1** — rejected. The precondition has been seen to fail, on the very
trace that motivated it.

## The async-clear arm

`uio_oe[MISO]` comes from `miso_oe_q`, a flop on
`always @(posedge clk or posedge cs_deasserted or negedge rst_n)` — a
**triple-edge async clear**, the construct where two simulators most plausibly
diverge. CS deasserts **mid-cycle at a seeded offset in 1..9 ns**, strictly
between the negedge and the following posedge so it can never land on an edge.
Clocking CS on an edge like everything else would have hidden the asynchronous
path behind the synchronous one.

**The two simulators agree.** And the arm is not vacuous: the gate checks that
`uio_oe` actually moves first, because if the lane never asserts the enable
there is nothing for CS to clear.

## Five bugs broadening found — four of them in my own bench

1. **`-I test` is not an include path for the 2-state engine.** With a space it
   parses as an empty include dir plus a source file named `test`. `+incdir+`.
2. **The cross-seed check was defeated by the provenance header.** The header
   records the seed — correctly, so runs cannot be confused — and the check
   compared whole files, so every pair "differed" on exactly that line. It now
   compares bodies. A guard defeated by a field added to make runs
   distinguishable.
3. **Two different seeds were conflated.** `+verilator+seed+N` randomises
   uninitialised state and must **not** change the trace; `+SEED=N` seeds the
   bench's peer-phase LCG and deliberately **moves the stimulus**. Passing the
   sweep index to both made the check assert "different stimulus produces the
   same trace" — false on purpose — and `corpus_all5` duly disagreed on 2,904
   lines. The phase seed is now an argument held fixed across a sweep; varying
   it is a separate arm that re-runs the cross-simulator compare per phase.
4. **The bench's own state was unreset.** `run_go`, `mst_val`, `mst_oe` and the
   `en_*` flags were assigned in the main `initial` block, which looks
   equivalent to a declaration initialiser and is not: under
   `+verilator+rand+reset+2` the bench's regs are randomised at construction, so
   `run_go` starting at 1 let the peer-master processes fall straight through
   `wait (run_go)` and drive before the main block cleared it. Exactly the three
   programs with a bench master disagreed across seeds, by 1,492 to 2,888 lines.
   ⚠ **The reset audit allowlists the DESIGN's flops; nothing audits the
   testbench**, and read-before-write there produces the same seed-dependent
   trace. The sweep does not care which side of the port list the defect is on.
5. **A portable PRNG is necessary and not sufficient — the state must not be
   shared.** `$random` differs between the two simulators, so the phases use an
   LCG written out in Verilog arithmetic. But both peer-master processes ran in
   every configuration (the `en_*` masks gate their *drive*, not their
   execution) and both read-modify-wrote one shared `rnd`, plus one shared loop
   index `j`. The draw sequence then depended on which process the scheduler ran
   first, which is not guaranteed identical across simulators: every
   bench-master program disagreed by 2,392–2,896 lines while the I²C program —
   whose peer is driven only by the DUT — stayed cycle-exact. One state and one
   index per process.

## OPEN: `corpus_spim` needs a ruling

The FRAM peer cannot be addressed yet, and the fix is **not** a bench fix:

1. **The payload comes from the host, not the program.** `l_data` is loaded only
   at `if (host_valid) l_data[cur] <= host_data`, where `host_data = uio_q1` and
   `host_valid = run & ui_in[0]` — so the command byte arrives on the **`uio`
   bus**, which in this configuration is also where MISO lives. The host payload
   path and the protocol pins share a bank.
2. **`OP_SHIFT` sets the clock to the action's own level field** and shifts in
   the same cycle (`pin_out[l_clkpin] <= a_lvl`, then `l_data >>= 1`), so
   whether the peer samples valid `si` at the SCK edge depends on the
   SHIFT/clock phase the ISA intends. That is a protocol-semantics ruling, and
   `l_data` shifts LSB-first while the FRAM expects MSB-first.

With `l_data` at its reset `8'h00` the master clocks out an invalid opcode and
the peer stays High-Z **exactly as the datasheet says it should**. The peer is
behaving correctly; the program cannot yet speak to it.

⭐ **It must not be made green the easy way.** Having the bench drive `uio[7:1]`
as host payload *would* make `uio_in` non-constant while the peer still never
answered — a precondition satisfied by the wrong mechanism. So the check is
sharpened to the one bit the peer drives, `uio_in[MISO]`, which only a real
response can move. The arm stays red with its reason recorded in
`test/corpus.py` `OPEN`, and the gate counts it separately: an open arm is not a
pass.

## What this does NOT establish

- **Ports only.** Internal state is not compared, so a divergence that never
  reaches a pin inside the window is invisible.
- **RTL only.** The gate-level arm is the owed `gl_test` replacement; the bench
  is built to run there unchanged (the peers attach to ports, which survive
  synthesis) but has not.
- **The peers are same-hand models** of the datasheets. They witness the DUT's
  protocol timing, not the real devices'.
- **1,500 cycles per program, two phases, one seed triple.** Not a sweep.
- `corpus_sptgt` moves `uio_out`/`uio_oe` by only 2 distinct values each — MISO
  is one bit, so that arm's discriminating power is thin by construction.

## Reproduce

```bash
python test/corpus.py                 # regenerate the images and pinmap.vh
PE_TRACE_PHASES=1,7 python test/gate_corpus_trace.py
```

## Suite state at this commit

`run_a2` **30 of 30** (digest `b4e51034e283`) · `price_gates` **13 of 13 red** ·
`run_mutants` **4 of 4** · `tb_smoke` PASS · `tb_edge` **5 of 5** ·
`gate_reverse_trace` 8 of 8 opcodes · `gate_reset_audit` PASSED (2,087 unreset,
5 of 5 allowlisted) · the original smoke trace still cycle-exact through the
rebuilt bench (`sha e24f7d4066ddb143`; it moved from `697750201a64` only because
the trace gained a `uio_in` column).

`yosys_check.sh` was **not re-run**: nothing under `src/` changed in this round,
and that gate reads only `src/`.
