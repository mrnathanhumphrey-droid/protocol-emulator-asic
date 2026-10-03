# Phase 1 close-out, part 4 — the pin conflict, and the memory decision

Answers the rulings issued after `4d99946`. Continues
[`PHASE1_CLOSEOUT_PART3.md`](PHASE1_CLOSEOUT_PART3.md).

**Reproduce:**
```
python model/a2/run_a2.py              # 19 of 19, one lane table
python model/a2/gate_pin_subsets.py    # the envelope, checked on every subset
python model/sram_spike.py             # program memory technology
```

---

## The pin conflict — 12 protocol pins against 8 `uio`

| lane | pins | which |
|---|---|---|
| UART-tx | 1 | TX |
| UART-rx | 1 | RX |
| SPI-master | 4 | SCLK, MOSI, MISO, CS |
| I²C | 2 | SCL, SDA |
| SPI-target | 4 | SCLK, MOSI, MISO, CS |
| **total** | **12** | **against 8 `uio`** |

**Nobody had counted.** Every `r_i` this project has published is for a task set
no single pin assignment can realise.

### The envelope claim, checked rather than argued

Non-preemptive EDF is monotone under removing lanes — the interference sum loses
a term, `B_i` is a max over a smaller set, and the busy period and its candidate
offsets shrink with it. So the five-lane numbers bound every subset.

⛔ **But that is an argument, and this project has already shipped three
arguments of exactly that shape that only fell to a foreign tool** (the `a == T−1`
period guard, the strict-vs-non-strict release count, the degenerate zero
fixpoint). So it is enumerated and checked:

| check | result |
|---|---|
| pin-feasible subsets | **24** of 31 non-empty |
| (a) our recurrence: `r_subset ≤ r_envelope` | **54 of 54** (lane, subset) pairs hold |
| (b) strict monotonicity on every subset/superset pair | **90 pairs, 0 violations** |
| (c) **pyRTA on every subset** | 54 results, **0 disagreements, 0 envelope breaches** |

⭐ Check (b) is the stronger claim and it is not implied by (a): comparing only
against the *full* set would pass even if `r` jumped around in between.

**The three maximal wireable configurations:**

| pins | lanes |
|---|---|
| 8 | SPI-master + SPI-target |
| 8 | UART-tx + SPI-master + I²C + UART-rx |
| 8 | UART-tx + I²C + UART-rx + SPI-target |

**So 4 of the 5 lanes can run at once**, and the only real exclusion is that the
two SPI roles cannot coexist with the rest.

### And the published margins are conservative for real hardware

| lane | envelope `r` | worst **realisable** `r` | attained on |
|---|---|---|---|
| UART-tx | 10 | **8** | UART-tx, SPI-tx, I²C, UART-rx |
| SPI-tx | 7 | **5** | UART-tx, SPI-tx, I²C |
| I²C | 3 | 3 | UART-tx, I²C |
| UART-rx | 9 | **7** | UART-tx, SPI-tx, I²C, UART-rx |
| SPI-target | 5 | 5 | UART-tx, I²C, SPI-target |

Three of five lanes are strictly better on any chip you can wire.

### ⭐⭐ The `uo_out` trade-off is bigger than a serialisation cost

Split by direction (`uo_out` is output-only, so it can carry a push-pull output
and **cannot** carry an input or an open-drain line that must release — I²C is
pinned to `uio` either way):

| lane | push-pull | inputs | open-drain |
|---|---|---|---|
| UART-tx | 1 | 0 | 0 |
| SPI-master | 3 | 1 | 0 |
| I²C | 0 | 0 | 2 |
| UART-rx | 0 | 1 | 0 |
| SPI-target | 1 | 3 | 0 |
| **total** | **5** | **5** | **2** |

| placement | `uio` used | `uo_out` used | all 5 lanes? |
|---|---|---|---|
| everything on `uio` (today) | 12 | 0 | **no** — needs 12 of 8 |
| push-pull outputs → `uo_out` | **7** of 8 | **5** of 8 | **YES** |

**Moving the push-pull outputs makes the whole five-lane set wireable** — 31 of
31 subsets feasible instead of 24. The envelope stops being an envelope and
becomes a configuration.

⚠ **And the cost is sharper than "serialise the view".** With 5 of 8 `uo_out`
pins on protocol outputs, 3 remain. The F1 data channel wanted a *parallel* RX
byte there. 3 pins cannot carry a nibble plus a valid flag, so the RX path goes
**bit-serial** — or the view time-multiplexes against the protocol outputs, which
**F2 forbids**, because switching the view on a pin that is also driving SCLK
would glitch it.

⛔ **The real trade is: 5 lanes with a bit-serial host readback, against 4 lanes
with a parallel one.** That is a product decision about what the demo shows, so
it is flagged back, not taken.

---

## Memory: SRAM, decided before Part 1 RTL

⛔ **The trigger was already past and "if it doesn't fit" was the wrong framing.**
F1 fitted one transaction per protocol into 62 of 64 bytes. The rung-5 FRAM
readback oracle needs **two transaction shapes** — a write (address + data) and a
read (address + repeated START + read) — not one shape looped. The demo the plan
depends on does not fit.

**Why it is a Part-1 decision:** a flop array reads combinationally; an SRAM macro
reads **synchronously, one cycle later**. The RTL has to be written for one or the
other.

### The numbers, each with its origin

| quantity | value | origin |
|---|---|---|
| macro list | 30 macros | PDK tree, `ihp-sg13g2/libs.ref/sg13g2_sram/gds` |
| `RM_IHPSG13_1P_256x8_c3_bm_bist` | `SIZE 236.8 BY 74.1` → 17,547 µm² | that macro's LEF |
| `RM_IHPSG13_1P_512x8_c3_bm_bist` | `SIZE 236.8 BY 110.38` → 26,138 µm² | that macro's LEF |
| flop cost | **4.04 cells/bit** | itemised from *our own* shipped cell inventory |
| cell area | 19.24 µm² | our shipped run: 2,946 cells at 6.28 % of a 902,417 µm² core |
| 6×4 budget | 432,864 µm² | `ARCH_PREREG_01` §110: 167 × 108 µm per tile |

| capacity | SRAM | flops | SRAM is |
|---|---|---|---|
| 2,048 bits (256 B) | 17,547 µm² | 159,281 µm² | **9.1× smaller** |
| 4,096 bits (512 B) | 26,138 µm² | 318,562 µm² | **12.2× smaller** |

**512 bytes of program memory costs 6.0 % of the 6×4 area as a macro and 74 % as
flops.** ⭐ That also cross-checks the F1 area finding by a **different route** —
F1 counted cells, this counts µm² — and the two agree that a flop store at this
size is most of the chip.

### It uses the pipeline stage Ruling 1 already bought

A synchronous read puts the address out in cycle *k* and the data in *k+1*,
landing in the pipeline register Ruling 1 already requires. **So the macro does
not cost a stage.** Nothing in the `(C, J)` frontier moves: the descriptor is in
per-lane registers (Ruling 1 (i)), so the SRAM is on the **program** path only,
never the EDF path.

### Integration risks, named rather than discovered later

1. **Metal4 top, and the power pins are Metal4-only** while a TT PDN typically
   lands on Metal5/TopMetal1. ⚠ I have seen this referenced in public
   OpenROAD/TT issue titles for this macro family but have **not reproduced it**,
   so it is a risk to check in the spike, not a measured fact.
2. **BIST pins.** The macro carries `A_BIST_*` (EN, CLK, REN, WEN, MEN, ADDR,
   DIN, BM). They must be tied off deliberately — a floating BIST enable is a
   write port nobody declared.
3. **Geometry.** 236.8 µm wide against a 167 µm tile, so it spans ~1.4 tiles
   horizontally and more than one tile row. It fits a 6×4 (1002 × 432 µm) with
   room, but it is **not** a drop-in inside one tile.
4. **Precheck.** ⚠ Whether the macro's GDS layers pass the CMOS5L precheck
   allowlist is **not verified here**, and it should be the spike's first step —
   a precheck failure kills the approach regardless of the area argument.

**Reclaim, applies either way:** `D_tol` in the image header costs **5 bytes**
for 5 lanes and exists only for a 5.3 load-time screen. If that screen does not
ship, drop it. ⛔ But not silently while 5.3 is still planned — that removes the
input the certificate path reads, which is the one thing F3 kept it for.

---

## Smaller items

**`INV-ATOMIC-1`: at most one atomic apply in flight.** Added to the INV set for
Phase 4 k-induction, so the property that makes one shared P-ATOMIC register
sufficient is checked rather than remembered. ⭐ It is the cheapest kind of
invariant to prove: it follows from the pipeline having exactly two stages, which
is a *structural* fact about the RTL rather than a behavioural one.

**The origin rule, adopted.** Every estimate in a spec or ledger now carries
where it was computed and from what; an unsourced number is treated as
unverified, **including our own**. Applied in `sram_spike.py`,
`gate_pin_subsets.py` and the 1.5 field table, which now separates *measured*
constants (read from `SILICON_EVIDENCE.md`) from *my estimates* (the P-ATOMIC
apply network) instead of mixing them.

⭐ The diagnosis that this was a **compaction artefact rather than a slip** is the
useful part: a figure produced in one round and quoted in the next with no
provenance attached is indistinguishable from one handed to us by someone else —
which is exactly how I came to ask where my own number came from.

**1.6 gains two conditions** (now 15):

| id | condition | shipped | must-fire |
|---|---|---|---|
| 1.6n | data channel: host keeps TX registers fed | `U_chan` 10.7 % utilised | saturates at 5 Ethernet lanes |
| 1.6o | **pin budget: active-lane pins ≤ 8 `uio`** | widest subset = 8 of 8 | the 12-pin envelope is rejected |

⛔ 1.6o first evaluated the *envelope*, which it is supposed to reject — turning
the whole 1.6 gate red for the one condition working correctly. Like 1.6c/j/l it
is a condition on a **program**, so it evaluates a declared subset and the
envelope's rejection is the must-fire.

---

## Status

**19 of 19 model gates green**, one lane table (`8ea5756203e1`), no gate opted
out. F2's netlist check self-tests green and is expected red against today's
netlist, by design.

**Open flag-back:** the `uo_out` placement — 5 lanes with bit-serial readback, or
4 lanes with a parallel one.

**Then:** re-close 1.5 on the memory decision and the per-program pin assignment,
then Part 1 RTL (which must pass F2 face 3).

**Still owed:** `C` unmeasured (the ≥ 4 bar is its reserve, retires after Phase
2); the engine is not built; `nptest` exactness not run; the SRAM spike's three
build steps (precheck, trial harden, PDN bridge); H4 (`refs/ieee_try.bin`,
`refs/t2.bin` — safe to delete, Nate's hand).
