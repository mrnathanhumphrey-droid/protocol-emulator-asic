# Phase 1 close-out, part 3 — rulings F1, F2, F3

Answers the rulings issued after `4f297ed`. Continues
[`PHASE1_CLOSEOUT_PART2.md`](PHASE1_CLOSEOUT_PART2.md).

**Reproduce:**
```
python model/a2/run_a2.py                      # 18 of 18, one lane table
python model/a2/gate_encoding_f1.py            # F1: program vs payload
python model/f2_flop_driven_outputs.py --selftest   # F2: the static check
bash  model/price_gates.sh                     # 9 of 9 red
```

---

## F1 — the store was never too small. I had the symptom.

**My diagnosis was right in every number and wrong in its cause, and the fix I
recommended would have cost most of the chip.**

I reported "the program store is an order of magnitude too small, recommend
`AW ≥ 8`" from a correct count: a 3-byte action word, 21 actions in 64 bytes,
44 needed. The root cause is that **the action word carries a level bit**, so the
program spells out the data — one action per bit. Program size then grows
**linearly with message length**, which makes the chip a **waveform player rather
than a protocol emulator**. The brief contrasts exactly those two things.

### ⛔ And "area is free at 6.28 %" was wrong

6.28 % is **die-area utilisation including filler** (68,161 of 71,107 instances),
not a cell budget. Itemised from the shipped cell inventory, the 64-byte store
already costs **~2,070 of the design's 2,946 logic cells**:

| | cells |
|---|---|
| flip-flops (`dfrbpq_1`) | 512 |
| `mux2_1` — the inventory names it "the 64-entry readback mux tree" | 515 |
| `tiehi` | 512 |
| `dlygate4sd3_1` share (pro-rata of 555 hold-fix buffers) | 531 |
| **itemised total** | **2,070 → ~4.04 cells per stored bit** |

| `AW` | bits | cells @4.04 | cells @5.75 | vs a practical budget |
|---|---|---|---|---|
| 6 | 512 | 2,070 | 2,946 | 7–10 % |
| 8 | 2,048 | 8,280 | 11,784 | 27–39 % |
| **9** | **4,096** | **16,560** | **23,568** | **54–77 %** |
| 10 | 8,192 | 33,120 | 47,136 | 109–155 % |

⚠ The budget is a **range, not a number**, and the two estimates disagree: the
pre-reg's tile geometry gives 24 × 18,036 µm² = 432,864 µm², while the hardened
core is 902,417 µm² (→ ~19.2 µm²/cell → ~46,900 cells at 100 %, ~30,500 at a
routable 65 %). **The ruling survives either**: `AW = 9` is thousands of cells
spent storing data that should not be in the store.

### The encoding fix, and the slope that matters

| transaction | per-bit actions | shift/repeat | how |
|---|---|---|---|
| UART tx frame (8N1) | 10 | **3** | start, SHIFT 8 @ T=434, stop |
| SPI byte (CS + 8 bits) | 18 | **3** | CS low, SHIFT 8 with clock pin, CS high |
| I²C write txn (addr+data) | 40 | **8** | START, SHIFT 8 addr, ACK, SHIFT 8 data, ACK, STOP |
| **total** | **68** | **14** | |

⭐ **The point is the slope, not the constant.** Under shift/repeat an M-byte UART
transfer is still 3 actions: the program is the *protocol* and the message flows
through it.

### Pre-registered magnitude: it fits

| delay field | action bits | action bytes | header B | program B | total | fits ≤ 64 B |
|---|---|---|---|---|---|---|
| 16 | 30 | 4 | 20 | 56 | 76 | no |
| 12 | 26 | 4 | 20 | 56 | 76 | no |
| **10** | **24** | **3** | **20** | **42** | **62** | **YES** |
| 9 | 23 | 3 | 20 | 42 | 62 | YES |

**62 of 64 bytes at the existing `AW = 6`.** ⛔ My first F1 count omitted the
**header** — the image carries per-lane descriptor init and, per F3, `D_tol`.

⭐⭐ **The 10 bits come from 1.5's own headroom.** 1.5 derived the timestamp floor
as 9 bits and called 16 "headroom with 7 bits to give back"; this is what they
were for. ⛔ The two widths are *not the same object*: the timestamp **register**
stays 16 bits for the wrap-safe compare, the program's **delay field** is 10, and
long delays still chain (Ruling 2) into more chunks.

⚠ **2 spare bytes is 0 further actions.** The magnitude is met and the headroom is
zero, so **SRAM** (the TT IHP examples) is the next step for anything beyond one
transaction each — the ruling's own trigger, reached on the first real program.

### A2 is untouched, and the `C = 2` claim is stated

Each bit edge is still its own job: a shift/repeat action of N bits *releases* N
(or 2N, clocked) events at period T. The lane digest is identical, so this is an
encoding change and not a re-derivation.

The ruling required the shift/advance to be shown to fit `C = 2`. Per-event work
is (1) drive pin ← `data_reg[bit_ptr]`, (2) `bit_ptr++` and reload the timestamp.
**Both register-only** — a mux select off a 3-bit pointer, an increment, an add,
and no store access, because the descriptor is already in per-lane registers
(Ruling 1 (i)). ⚠ An estimate until Phase 2; the frontier already prices the
overrun (at `C = 3` the minimum margin is 11).

### The run-mode pin map — flag-back

Constraint: in run mode all 8 `uio` are protocol pins, so the channel comes out
of `ui_in`/`uo_out` alone.

| pin | use |
|---|---|
| `ui_in[7]` | `prog_mode` — unchanged; mode select never comes from `uio` |
| `ui_in[6]` | prog: WR strobe / run: **TX payload PUSH** |
| `ui_in[5]` | prog: ptr reset / run: **RX payload POP** |
| `ui_in[4:1]` | **TX payload nibble** (2 pushes per byte) |
| `ui_in[0]` | `uo_out` view select: 0 = RX payload byte, 1 = **status** |
| `uo_out[7:0]` | RX payload byte **or** status (sticky `ovr`, TX-underrun, TX-full, RX-valid) |
| `uio[7:0]` | **protocol pins only** — zero spent on the data channel |

⭐ **No lane-select field, and that is rung 1's trick again.** A host-side lane
select would need 3 input pins we do not have. It is unnecessary: **the shift
action names its lane** (via its pin field), so the host pushes bytes into **one
FIFO** and the engine routes them as the program consumes them. Rung 1 deleted the
address bus by auto-increment; this deletes the lane select by letting the program
do the addressing.

⚠ What it costs: a byte is 2 pushes; `uo_out` becomes dual-view (prog-mode
readback keeps its meaning, run-mode RX moves behind `ui_in[0]`); and a TX
underrun must be a **sticky flag, never a stall**.

---

## F2 — registered readback, extended to every output pin. Approved and built.

`model/f2_flop_driven_outputs.py` checks, on the **netlist**, that every bit of
`uo_out`, `uio_out` and `uio_oe` traces back to a flop through single-input cells
only.

⭐ **The property is "no combinational reconvergence on an output path"**, and
"driven by a flop" is its shorthand — a single-input cell (buffer, inverter,
delay) cannot create a glitch, so the walk passes *through* them and stops at the
first cell with ≥ 2 inputs. That matters concretely: this design has **555
hold-fix delay cells**, and a checker that called them combinational would red
the real netlist for the wrong reason.

**⛔⛔ Two real bugs in my own checker, found by requiring each mutant to die for
its stated reason:**

1. The flop pattern `(^|_)(df|dl|…)` **matched `_dlygate4sd3_1` via `dl`**, so all
   555 hold-fix cells classified as *flops*. The trace then stopped at the delay
   cell and never walked back — **wrong in the unsafe direction**: a combinational
   path hidden behind a hold-fix buffer would have read as compliant.
2. There was no pattern for ordinary combinational cells, so `and2`/`mux2` fell
   through to "unknown" and **all three mutants died with the same finding**.
   Three mutants dying for one reason is one mutant wearing three hats, and it
   made the unknown-cell arm vacuous. `check()` now takes `expect_verdict` and
   certifies the kill by its reason.

| face | subject | verdict |
|---|---|---|
| 1 | flop → buf → dly → pin | **PASS**, path shown through both single-input cells |
| 2 | `and2_1` drives `uio_out[0]` | dies **COMBINATIONAL** (×2-in) |
| 3 | `mux2_1` readback → `uo_out` — **today's RTL** | dies **COMBINATIONAL** (×3-in) |
| 4 | an unclassified cell | dies **UNKNOWN-CELL**, fail-closed, cell named |

⭐⭐ **Face 3 is the shipped design and it fails, which is the point.**
`uo_out = mem[rd_ptr]` is the 18.4388-of-20 ns feedthrough. The check is
**expected red against the current netlist and must go green once the readback is
registered**, which makes it a falsifiable acceptance test for F2 rather than a
lint. A tie reads as `CONST` and is allowed — a tie cannot glitch.

⚠ Not in CI: the netlist comes from the third-party `tt-gds-action` artifact and
`test/gate_level_netlist.v` is gitignored, so this runs by hand like
`model/a4_precondition.py`. `--selftest` needs no artifact, which is what makes
the checker itself priced.

---

## F3 — `D_tol` is not a silicon register. Applied.

It lives in the **program-image format** as loader metadata, so a 5.3 load-time
screen reads it from the store. **40 flops not spent**, and the certificate path
stays open at zero runtime cost. The 1.5 field table now lists it as `image`.

---

## 1.5 re-closed — and three more problems in my own field list

**Derived encoding: 45 bits × 5 lanes = 225 flops, +17 global = 242 new engine
flops** (down from 277, because F3 removed `D_tol` and two duplicates were
merged).

⛔ **Duplicate fields.** ARCH_PREREG's "shift reg" and F1's "data register" are
**the same register**; its "bit counter" and F1's "bit pointer" are the same
counter. Shipping both pairs would have cost 12 bits × 5 lanes = 60 flops and
given the descriptor two names for one thing — which is how a second
implementation of the same state later disagrees with the first.

⛔⛔ **The action word is the MAX over opcode variants, not the sum.** Summing
every `prog` field gave 31 bits → 4 bytes and **contradicted `gate_encoding_f1`'s
24 bits → 3 bytes off the same field list**. The fields are mutually exclusive by
opcode:

| variant | bits | bytes |
|---|---|---|
| drive (level) | 17 | 3 |
| shift/repeat | 24 | 3 |
| wait / no-op re-arm | 16 | 2 |
| atomic group | 32 | 4 |

An encoding costed as the sum of all variants is an encoding nobody would build,
and two files disagreeing about the same word is exactly the drift A1 exists to
stop. Both now derive 24 bits.

### P-ATOMIC: 350 vs 46, reconciled — and it settles the design

⛔ **Correction first.** I said "I was handed about 350 cells and can find no
basis for it in this repo". The repo part is true; **the framing was wrong — 350
was my own figure from an earlier round** (~60 bits × ~5.8 cells/bit, 5 lanes of
mask+data). I treated my own estimate as an external one and asked where it came
from.

The two differ on **two** axes: **scope** (5 per-lane groups vs 1 shared) and
**cells per bit** (5.8, a *store* bit including the readback mux tree, vs ~2 for a
plain register bit). Carrying the store's 5.8 into a 16-bit register over-prices
it ~3×.

| variant | bits | @2/bit | +apply | total |
|---|---|---|---|---|
| 1 shared group | 16 | 32 | 30 | **~62** |
| 5 per-lane groups | 80 | 160 | 150 | **~310** |
| 5 per-lane, w=6 | 60 | 120 | 150 | ~270 |

The earlier ~350 lands on the per-lane row; the ~46 was the shared row with flops
at 1 cell. Both arithmetics were fine — **they were pricing different designs.**

⭐⭐ **And the reconciliation settles it: P-ATOMIC needs ONE shared mask+data
register, not five, because the scheduler is NON-PREEMPTIVE.** Exactly one job is
in service at any instant, so at most one atomic group can be mid-apply; five
registers would be four copies that provably cannot be live together. **~248 cells
for nothing.** ⛔ The guarding condition is worth naming because it is losable: if
the engine ever overlapped two services (a deeper pipeline than Ruling 1's two
stages), the shared register stops being sufficient.

---

## 1.6 — a fourteenth condition, and I had its formulation wrong twice

**1.6n — the host must keep the TX data registers fed.** This condition exists
*because* F1 moved the payload out of the program: the host is now part of the
timing chain, an obligation that did not exist when the program spelled out every
bit. F1 bought program size with a new liveness requirement, so the requirement
gets priced.

⛔ **The right quantity is aggregate, not per lane.** I first wrote it as "each
lane's 8 bit-times must exceed the strobe time", which **no realistic lane can
violate** — so the condition never bound and its must-fire needed an absurd
1-cycle bit period to fire. The pin map gives all five lanes **one shared FIFO**,
so the host must sustain the *sum* of every lane's byte rate. That is a
utilisation, exactly like `U`:

```
U_chan = Σ_i ( pushes_per_byte / (8 · t_i) )   ≤   1 / (L_sync + 1)
```

**Shipped set: `U_chan` = 0.0267 against a capacity of 0.25 — 10.7 % utilised**,
host strobing every 37 cycles (1.34 MHz).

⭐ **The firing case lands on the roadmap, not on a contrived threshold.** Sweeping
10 Mbit lanes (`t = 5`): 1× 0.050, 2× 0.100, 3× 0.150, 4× 0.200, 5× **0.250**,
6× 0.300. **The nibble channel saturates at 5 Ethernet-rate lanes** — a ceiling on
the Ethernet *extension*, not on the required set.

⛔ **And the response to a violation is fixed by A2, not chosen.** An empty
register at a shift edge raises a **sticky flag** and the lane continues with a
defined value; it must never **stall**. A stall makes `C` unbounded, and
`B_i = max{C_j − 1}` over later-deadline lanes, so **one stall makes every lane
infeasible** — the identical conclusion the I²C clock-stretch analysis reached for
a busy-wait, arrived at from the opposite end.

---

## Status

**18 of 18 model gates green**, one lane table (`8ea5756203e1`), no gate opted
out. **9 of 9 foreign gates priced red.** F2's netlist check self-tests green and
is **expected red against today's netlist**, by design.

**Open:** the run-mode pin map (flag-back above). Then Part 1 RTL.

**Still owed:** `C` unmeasured on every lane (the ≥ 4 bar is its reserve and
retires after Phase 2); the engine is not built; `nptest` exactness not run; H4
(`refs/ieee_try.bin`, `refs/t2.bin` — safe to delete, Nate's hand).
