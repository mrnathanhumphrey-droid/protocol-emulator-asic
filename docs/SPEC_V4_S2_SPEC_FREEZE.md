# SPEC v4 — S2: the spec freeze

1.5 re-closed on every ruling that landed after it. Continues
[`SPEC_V4_S0_S1_RESULTS.md`](SPEC_V4_S0_S1_RESULTS.md).

Reproduce: `python model/a2/run_a2.py` (23 of 23) ·
`python model/a2/gate_spec_freeze_s2.py` · `python model/a2/gate_program_census.py`
· `python model/a2/gate_encoding_f1.py` · `bash model/price_gates.sh` (9 of 9).

---

## ⛔⛔ The freeze found a functional break and a duplicate

That is what a freeze is for. 1.5 froze a descriptor, then six rulings moved its
ground — the two-bank pin map, the RX serialiser, the load-mode pin safety fix,
reset-high, 1.6r's async-clear release, and S1's `AW`. **A freeze that is not
re-closed after its inputs move is a stale document with authority.**

### (1) `N_PINS = 8` was hardcoded in two gates — and the chip could not name its own output pins

`gate_encoding_f1.py` and `gate_descriptor_1_5.py` both carried
`N_PINS = 8`, commented *"tt_um_* gives 8 bidirectional uio"*. True before the
two-bank ruling; **false after it.**

The ruling put **4 push-pull protocol outputs on `uo_out`**, so a program action
must address **12** pins — 8 `uio` + 4 `uo_out`. At `bits_for(7) = 3` the action
word's `pin` field **cannot name the `uo_out` protocol pins at all.**

⛔ **That is not a sizing nicety.** UART TX, SPI SCLK, MOSI and CS all live on
`uo_out` under the ruled map. A 3-bit pin field means **no program can drive
them.**

⇒ Now **derived** from the pin map, in one place:
`gate_pin_subsets.addressable_pins()` = `N_UIO + bank_need(LANES)[1]` = **12**,
needing **4 bits**. ⭐ A constant that must be updated in two files when a ruling
lands is a constant that will be updated in one.

⚠ Note what is *excluded*: the 3 serial pins. The serialiser owns them and no
program action may name them — which is also what stops a program glitching SCLK
by switching the host view (F2).

### (2) The action word's `clock pin` was a duplicate

Its rationale was right about the **mechanism** and wrong about the **scope**:
*"a clocked protocol needs the shifter to drive its OWN clock, or the data and
clock become two actions that must stay in lockstep — which is P-ORDER on every
bit."* True — but that says a SHIFT must **drive** a clock. It does not say the
clock pin must be named **per action**.

⭐ **The clock pin is a lane property, and the per-lane image header already
carries it.** A lane cannot drive two clocked buses — the ruled pin map gives
SPI-tx exactly one SCLK — so the per-action copy **can never differ** from the
header's. **Cut.**

⭐ This is the *third* time this cut has been made. 1.5 already merged "shift
reg" with "data register" and "bit counter" with "bit pointer", which had cost
**60 flops** for two names for one thing.

### ⭐ The two cancel — and that is a result, not a coincidence to hide

| | action word | demo | AW |
|---|---|---|---|
| before S2 (3-bit pin, clock pin present) | 24 b = 3 B | 178 B | 8 |
| **fix alone** (4-bit pin, clock pin present) | **26 b = 4 B** | **229 B** | **9 — 54 % of budget** |
| **cut alone** (3-bit pin, no clock pin) | 18 b = 3 B | 178 B | 8 — *but the chip can't drive its pins* |
| **both (shipped)** | **22 b = 3 B** | **178 B** | **8** |

So S1's `AW = 8` and F1's 62-of-64 both **survive** — and F1 now fits at
**delay = 12 bits** where it previously needed 10, so **the cut bought 2 bits of
delay range for free.**

⛔ **Had only the fix landed**, `AW` would have gone to 9 — **54 % of the cell
budget for the store alone** — and on the *headroom rule*, since 229 B still fits
256 B unpadded. My own census gate warns against exactly that: a sizing rule
that only yields its answer at one chosen margin is not a measurement.
⛔ **Had only the cut landed**, the chip could not name its own output pins.

---

## The gate: traceability, and duplicate detection

New gate `model/a2/gate_spec_freeze_s2.py`, in `run_a2.py`.

**24 fields, all traced to a named ruling, no duplicates.** A field with no
ruling is **cut**, not shipped.

⭐ **And duplicate detection is a separate check, because traceability does not
catch duplicates** — both copies of the clock pin traced to a real ruling. That
is precisely how the field survived.

| where | bits | cost |
|---|---|---|
| per-lane register | 47 | **× 5 lanes = 235 flops** |
| program word | 22 | = 3 bytes, agreeing with F1's `action_word()` |
| global | 17 | 17 flops |
| image / build param | — | not silicon |
| dedicated hardware | — | costed so it is not invisible |

⭐ **Section 4 reconciles the action word against the program-word fields, and
before S2 they disagreed** — F1 carried a clock-pin field the descriptor did not,
and both hardcoded `N_PINS = 8`. Two files describing one word is how RTL gets
built from whichever one its author opened.

### What was cut, and by which ruling

A freeze that lists only survivors cannot be audited for what it dropped. **8
cuts recorded**, each naming its ruling: the per-action clock pin (S2), `D_tol`
as a register (F3, 40 flops), the two 1.5 merges (60 flops), P-ATOMIC mask+data
(1.5 — one shared group suffices under non-preemptive scheduling, INV-ATOMIC-1),
per-lane countdown timers (Ruling 2), the parallel RX view (product call), and
the digital CS filter (1.6r).

---

## The budget, stated without the trap

| item | cost |
|---|---|
| engine **state** | 235 + 17 = **252 flops** |
| program store, `MEM_TYPE=flops`, `AW=8` | 2,048 bits = **8,280 cells = 27.2 %** |

⚠⚠ **The engine's *logic* is still not priced.** 252 flops of state is not the
engine's cell count — the comparators, the EDF mux, the shifters and the fetch
pipeline are all unbuilt. ⛔ **Adding state flops to store cells and calling it
"the chip" would be the 6.28 % error in a new costume.** S3 measures it.

What is known: the store takes **8,280 of 30,492** practical cells; **22,212
remain** for logic *and* the 252 state flops.

---

## Build parameters S3 must expose

| param | value | why |
|---|---|---|
| `N_LANES` | 5 | lane-count sweep + 1.6o |
| `AW` | **8** | S1 census; 178 B demo in 256 B |
| `N_PINS` | **12** | **derived** from the pin map, not written twice |
| `TS_W` | 16 | floor 9 derived; ships 16 |
| `DLY_W` | 10 | F1's fit |
| `D_W` | 8 | deadline spread |
| `MEM_TYPE` | **`flops`** | ⛔ default flops: **S0 = SRAM-BLOCKED**. The `sram` path stays a parameter for the predictive-node tier |
| ~~`RX_SERIAL`~~ | ~~1~~ | **DELETED BY RULING.** The row's own rationale was "the sweep must be able to turn it off to price it"; the coverage sweep measured that no arm ever did, and nothing in the tree overrode it. The parameter and its dead `else` are gone from `src/project.v`. ⚠ Recorded rather than erased — a freeze that quietly loses entries is not a freeze |

---

## ⛔⛔ Quarantine — it covers the engine, not just the PDN fix

The Part 1 engine and **every file in this repo** are built with **no reference
to the other entrant's repository or pull-request content.** A paraphrase of
their PDN diagnosis and fix reached this session through a web-search summary; it
was **not opened, is not recorded, and must not be reconstructed from memory of
that summary.** SPEC v4's S0(a) and S0(b) were deliberately **not performed** for
the same reason.

⭐ And the resulting position is stated plainly, because it is defensible in
public and it matches how this entry has been run:

> **SRAM is blocked for us by the integrity constraint, not by physics.**

---

## Status

**23 of 23** in-suite gates green, one lane table (`8ea5756203e1`, unchanged
through all of S0–S2). `price_gates.sh` **9 of 9**.

**Red on purpose, both verified red:** `part1_param_contract.py` (exit 1),
`macro_harden_gate.py` (exit 1). ⚠ `f2_flop_driven_outputs.py` exits **0** —
that is its *self-test* passing; face 3 is a mutant that must fail, and the real
netlist check is the red one.

**Next: S3** — the engine, against the parameter contract.

**Still owed:** re-read the TopMetal1 pitch (2.28 vs 3.28); `C` and `J`
unmeasured; H4 (`refs/ieee_try.bin`, `refs/t2.bin` — Nathan's hand).
