# SPEC v4 — S0 and S1 results

Answers S0 (read PR #187's test design) and S1 (program-size census) of SPEC v4.
Continues [`PHASE1_CLOSEOUT_PART7.md`](PHASE1_CLOSEOUT_PART7.md).

Reproduce: `python model/a2/run_a2.py` (22 of 22) ·
`python model/a2/gate_program_census.py` · `python model/macro_harden_gate.py`
(red on purpose) · `bash model/price_gates.sh` (9 of 9).

---

# S0 — verdict: **SRAM-BLOCKED**

## ⛔⛔ First, the premise correction: PR #187's test design is a rival's

The spec said *"It's TT's own repo, not a rival's, so the quarantine doesn't
apply."* The **PR** is in TT's repo. The **test design** is not.

PR #187's body, verbatim:

> "The IHP SRAM macro includes SRAM.drawing and DigiBnd.drawing marker layers
> used by the SG13CMOS5L DRC deck. Without these layers, the macro is either
> rejected by the layer check or incorrectly checked under non-SRAM DRC rules.
> This adds both layers to the SG13CMOS5L valid-layer list. Tested with
> RM_IHPSG13_1P_1024x8_c2_bm_bist; full Tiny Tapeout precheck passes. Evidence:
> https://github.com/WilliamZhang20/protocol-emulator/actions/runs/35163996266
> **This is for the ASIC Design Challenge by Jane Street which required CMOS5l
> on IHP.**"

⇒ **PR #187 was contributed by another entrant**, and the hardened design whose
PDN config S0(a)/(b) asked for is **their project**. Those two sub-items were
**not performed**. The quarantine applies after all.

⭐ **But the PR's own diff is first-party TT tooling, and it answers S0(c)
outright.**

## ⭐⭐ S0(c): TopMetal1 is reserved, and the allowlist enforces it

`precheck/tech_data.py` @ `cfa06bae536d00282cb2fdb3d0bdeebc562c6365` (the merge
commit), variable `valid_layers_ihp_sg13cmos5l`. Verified against the **full
file**, not the patch hunk:

| layer | entries in the CMOS5L allowlist |
|---|---|
| Metal1–Metal4 | `.drawing`, `.label`, `.nofill`, `.pin`, `.slit`, `.text`, `.res` |
| **TopMetal1** | **`.nofill` only** |
| Metal5 / TopMetal2 | none |

**`TopMetal1.drawing` appears nowhere in the file.**

⇒ **You cannot draw TopMetal1 geometry in a CMOS5L TT project.** `.nofill` is a
fill-exclusion marker, not drawable routing. ⭐ This confirms the structural
hypothesis the spec raised: TopMetal1 is reserved for the chip-level power grid,
exactly as top metal is in TT's sky130 flow, and the precheck allowlist is the
enforcement mechanism. **That is also why TT's template ships
`FP_PDN_MULTILAYER: 0`.**

## The verdict, from three first-party facts

| # | fact | source, pinned |
|---|---|---|
| 1 | PDN verticals are on **Metal4** | IHP-Open-PDK @ `2bbec75`, `ihp-sg13cmos5l/libs.tech/librelane/config.tcl` |
| 2 | the macro's `OBS` blocks **Metal1–Metal4** | the macro's own LEF |
| 3 | **`TopMetal1.drawing` is not allowlisted** | tt-support-tools @ `cfa06ba`, `precheck/tech_data.py` |

⇒ The vertical straps are on the one layer the macro is opaque to, **and remedy
A (enable the TopMetal1 horizontals) is forbidden by precheck.**

⛔ **The one remaining remedy is the quarantined one.** A Metal4-only same-layer
connection — stop the verticals at the macro boundary and tie to its own Metal4
power pins — is geometrically conceivable without TopMetal1. It is also the
precise shape of the fix in the other entrant's pull request, a paraphrase of
which reached this session through a search summary. **It will not be
reconstructed from that.**

⇒ **S0 = SRAM-BLOCKED for us.** Not "impossible" — *blocked*, because the only
path left is one we are not entitled to derive this way. ⭐ The honest statement
is that the integrity constraint, not the physics, is what closes it.

**Legitimate ways it could reopen, none of them required:**
- a **general** TT Discord question: *"in a CMOS5L project, how should a macro
  with Metal4-only power pins be connected, given the PDN verticals are Metal4
  and `TopMetal1.drawing` is not allowlisted?"* — a tooling question about their
  flow, naming no design;
- independent derivation from the PDN documentation, with the search summary
  treated as never having arrived.

**⇒ S4 is skipped. Flops ship. Nothing in S3 changes.**

---

# S1 — census verdict: **`AW = 8`**, and the pre-registered falsifier fired

New gate: `model/a2/gate_program_census.py`, in `run_a2.py` (22 of 22).

## ⛔⛔ A correction to F1, found by doing the census

F1 costed an I²C write transaction at **8 actions** — *"START, SHIFT 8 addr, ACK
read, SHIFT 8 data, ACK read, STOP (+2 setup)"*. **That is a one-byte-address
device, and ours is not.**

Primary, **MB85RC256V** (RAMXEED), its own protocol section: *"the master
outputs 8 bits × 2 memory address to the slave. When the each memory address
input ends, the slave again outputs the acknowledge"*, and its waveform reads
`S 1 0 1 0 A2 A1 A0 0 A | Address A | Address A | Write A | ... P` — **two
address bytes, each with its own ACK**. So the real transaction is **4 actions
longer** than F1 costed it.

Primary, **MB85RS64V**: *"WRITE op-code, arbitrary 16 bits of address and 8 bits
of writing data are input to SI. The 3-bit upper address bit is invalid"*,
waveform `SI OP-CODE | 16-bit Address | Data In`. So a WRITE carries **two**
address bytes.

⛔ **The lesson is an earlier error repeating in a new place:** a transaction
count taken from a protocol *in general* rather than from **the part we ship.**

## The census

Action word **24 bits = 3 bytes** (opcode 3, pin 3, level/dir 1, delay 10, clock
pin 3, bit count 4). Per-lane header **36 bits × 5 lanes = 25 bytes** (`D_tol`
included, as F3's image metadata).

Every action is enumerated in the gate; the totals:

| program | lane | actions |
|---|---|---|
| UART tx frame | UART-tx | 3 |
| UART rx frame | UART-rx | 3 |
| SPI WREN + WRITE (FRAM) | SPI-tx | 9 |
| SPI READ (FRAM oracle) | SPI-tx | 6 |
| I²C write (FRAM) | I²C | 10 |
| I²C addressed read, repeated START | I²C | 13 |
| SPI-target respond | SPI-target | 2 |
| + re-arm `WAIT` (one per lane, Ruling 2) | — | 5 |
| **all-five-lanes demo, total** | | **51** |

**51 actions × 3 B = 153 B program + 25 B header = 178 BYTES.**

⭐ The demo is what sizes the store, not the largest single transaction — one
FIFO, one action stream, all lanes live, because F1's shift action names its lane
and there is no lane-select field.

## The choice

| AW | bytes | cells @ 4.04/bit | % practical budget | holds 178 B + 25 %? |
|---|---|---|---|---|
| 6 | 64 | 2,070 | 6.8 % | no |
| 7 | 128 | 4,140 | 13.6 % | **no** |
| **8** | **256** | **8,280** | **27.2 %** | **YES** |
| 9 | 512 | 16,560 | 54.3 % | (stays dead) |

⇒ **`AW = 8`**, leaving 78 B = **26 spare actions**.

**⛔ The pre-registered falsifier FIRED: AW = 7 does not suffice.**

⭐⭐ **And the headroom rule is not doing the work.** The demo is **178 B against
AW=7's 128 B**, so AW=7 fails at **zero headroom**. `AW = 8` is forced by the
*programs*; the 25 % is then a separate, free cushion. A sizing rule that only
yields its answer at one chosen margin is not a measurement.

## ⚠ Read the 27.2 % correctly

**It is the store alone.** The engine is not built, so it is not priced. This is
**not** "the chip is 27 % full". ⛔ Quoting a store fraction as a chip fraction is
the shape of the error that produced *"area is free at 6.28 %"* — that was
die-area utilisation including 68,161 filler instances, read as headroom.

What **is** known: the store takes **8,280 of 30,492** practical cells, leaving
**22,212** for the engine — and the engine's cost becomes a **measurement in
S3**, not an estimate here.

## Why AW=8 is affordable where AW=9 was not

Not because the budget moved. **F1 took the payload out of the program**, so the
store scales with the number of **transactions**, not with message length.

⛔ And **F2 is what makes a deeper store safe**: store depth sat on the
18.44-of-20 ns combinational pad feedthrough, and the registered readback took it
off. Growing `AW` *before* F2 would have deepened the critical path. ⇒ **The two
rulings compose, and the order mattered.**

---

# Net effect on the plan

| item | status |
|---|---|
| S0 | **SRAM-BLOCKED** — three first-party facts; S4 skipped |
| S1 | **`AW = 8`** — falsifier fired; 27.2 % of budget for the store |
| S2 | ready: `MEM_TYPE` defaults **flops at AW=8**, both paths stay parameterised |
| S3 | unchanged and unblocked |
| S4 | **skipped** |

**Still owed:** re-read the TopMetal1 pitch (2.28 vs 3.28); `C` and `J`
unmeasured; the engine is not built; H4 (`refs/ieee_try.bin`, `refs/t2.bin` —
Nathan's hand).
