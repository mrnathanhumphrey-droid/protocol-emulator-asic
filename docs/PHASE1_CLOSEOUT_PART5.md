# Phase 1 close-out, part 5 — SRAM provenance, and the product call

Answers the rulings issued after `49ff6ca`. Continues
[`PHASE1_CLOSEOUT_PART4.md`](PHASE1_CLOSEOUT_PART4.md).

---

## ⛔⛔ The red flag was right, and it was my error

**The macro geometry I quoted came from the SG13G2 PDK tree, not from
sg13cmos5l.** I fetched it from `IHP-Open-PDK/ihp-sg13g2/libs.ref/sg13g2_sram/lef/`,
wrote that path down honestly, and then reasoned as if it were ours. This
competition targets **sg13cmos5l** — our own netlist's cells are `sg13cmos5l_*`,
not `sg13g2_*`.

⭐ **The origin rule is what caught it.** The path was recorded, so "which PDK
tree?" was an askable question. Quoted as a bare "26,138 µm²", nothing would have
exposed it. That is the second time in two batches the rule has paid for itself.

### What is established now, and from where

| # | finding | source | strength |
|---|---|---|---|
| 1 | `IHP-Open-PDK` has exactly one PDK directory, `ihp-sg13g2`. No sg13cmos5l tree. | the repo's own top-level listing | **primary** |
| 2 | SG13CMOS5L is the same process minus the HBTs and minus Metal5/TopMetal2 — 5 metals, `Metal1..Metal4` + `TopMetal1` | tooling/project documentation summaries | **secondary**, labelled |
| 3 | The macro's top routing layer is **Metal4** — *below* both removed layers, so it does not use what CMOS5L lacks | the LEF's own `OBS` section | **primary** |
| 4 | **TinyTapeout's own tooling supports SRAM macros in CMOS5L** | `tt-support-tools` PR #187 | **primary, first-party** |

On (4), verbatim: PR #187 is **merged** into the branch
`TinyTapeout:ihp-sg13cmos5l`, adding the `SRAM.drawing` and `DigiBnd.drawing`
marker layers to the **SG13CMOS5L** valid-layer list because "the SG13CMOS5L DRC
deck" uses them and "without these layers, the macro is either rejected by the
layer check or incorrectly checked under non-SRAM DRC rules". It states: **"Tested
with `RM_IHPSG13_1P_1024x8_c2_bm_bist`; full Tiny Tapeout precheck passes."**

⭐ And the change is **layer-based, not macro-based**, so it admits the whole
`RM_IHPSG13_1P_*` family rather than one part number. This is first-party to the
competition's own flow — not a competitor's claim.

**So precheck — the risk I had named as the one that "kills the approach
regardless of the area argument" — is answered.** The remaining risks are
placement and power, not admissibility.

### Still not verified: the gate before `MEM_TYPE=SRAM` locks

A hardening run with the macro **instantiated** in the CMOS5L template: DRC and
LVS with macro placement, and a PDN that reaches its Metal4-only power pins.

⚠ **That last one is the likeliest way this falls over.** "PDN cannot reach the
SRAM macro's Metal4-only power pins — blocked at `GeneratePDN`" is a named,
observed failure for this macro family in public issue titles, which **I have not
reproduced.**

⭐ **One hypothesis worth testing first, because it would be good news: CMOS5L
has no Metal5.** So its PDN must already live on Metal4/TopMetal1 — *adjacent* to
the macro's pins rather than two layers above them. The reports are against
SG13G2, where Metal5 sits in between. **The problem may not transfer.**
Hypothesis, not a finding, and cheap to check first because it decides the whole
approach.

⛔ **And if the harden fails, that is not a degradation.** The flop store becomes
the **shipped** design, because F1's encoding already fits one transaction per
protocol into 62 of 64 bytes. SRAM would survive only as a scaling-tier option.
The decision is reversible in one direction, so Part 1 is not betting on it.

---

## ✅ Product call: 5 lanes, push-pull outputs on `uo_out`, RX bit-serial

Adopted. Every lane A2 proves becomes a lane that runs — **31 of 31 subsets
feasible** instead of 24. "We proved five and you can run all five" is a
different claim from "we proved five, pick four", and closing that gap is this
entry's whole personality.

### The serialiser is off the engine, and that is the load-bearing part

⛔ If the RX serialiser were an engine lane it would take a scheduling slot,
enter every other lane's interference sum, and — being the longest action —
become the blocking term `max{C_j − 1}` for all of them. **That is the re-arm
lesson and the clock-stretch lesson in a third place.** As dedicated hardware it
costs **zero** schedulability budget, so nothing in A2, the frontier or 1.6 moves.

### The RX rate, corrected

| lane | bits per scheduled event | event every | rate |
|---|---|---|---|
| UART-rx | 1.0 — one sample per bit | 414 cyc | 0.12 Mb/s |
| SPI-target | **0.5** — two SCK edges per bit | 25 cyc | 1.00 Mb/s |
| **total** | | | **1.12 Mb/s** |

3 pins (data, strobe, valid) at one bit per cycle carry up to 50 Mb/s, so the
channel is **2.2 % utilised**. An RP2040 PIO reads that without effort.

⛔ **My first figure was 2.12 Mb/s, double the truth, because I read `t` as a bit
period.** `t` is the *scheduled-event* spacing: UART-rx samples once per bit so an
event is a bit, but SPI-target is master-clocked at two edges per bit so an event
is half a bit. That number was heading into a host-facing spec at twice its real
value. It now carries an explicit bits-per-event factor per lane.

### Pin placement is exactly full on `uo_out`

| budget | contents | used |
|---|---|---|
| `uio` | 5 inputs + 2 open-drain (I²C) | **7 of 8** |
| `uo_out` | 5 push-pull protocol outputs + 3 serial | **8 of 8** |

⛔ **`uo_out` has zero spare**, so any further output pin re-breaks the placement.
Recorded in 1.6o as part of the condition, not as a footnote.

### Two flag-backs carried to 1.5

1. **Status flags lose their view mode.** Sticky `ovr`, TX underrun and RX
   overflow had an 8-bit parallel view; it is gone. They must be **framed into
   the serial stream** — a status byte per frame — so the frame format carries
   liveness information, not just payload.
2. **The serial format becomes host-facing spec**: framing, bit order, and what
   happens when the host stops reading. ⛔ That is RX overflow, and it has to be
   **in** the stream — *a host that has stopped reading cannot be told by a pin it
   is not reading.* Same answer as TX underrun: a sticky flag, never a stall.

---

## 1.6 — two conditions updated, now 16

| id | condition | shipped | must-fire |
|---|---|---|---|
| 1.6o | **pin budget, ruled placement** | `uio` 7/8, `uo_out` **8/8 exactly full** | all-on-`uio` (12 > 8) rejected |
| 1.6p | **RX serial: host pops fast enough** | 1.12 Mb/s of 50 = 2.2 % | host stops reading → sticky flag *in* the stream |

⛔ 1.6o's must-fire was stale the moment the ruling landed — it still rejected the
*envelope*, which under the ruled placement is now programmable. The thing that
must be rejected is putting the outputs back on `uio`, so that is what it fires
on.

---

## Part 1 contract gains `RX_SERIAL`

`MEM_TYPE` now carries two jobs — portability for the predictive-node tier, **and**
the fallback if the CMOS5L harden fails. And `RX_SERIAL` (0 = parallel view,
1 = 3-pin serial) joins the list, because the sweep needs to be able to turn the
serialiser off to measure what it costs.

The contract remains **red**, correctly: the engine does not exist.

---

## Status

**19 of 19 model gates green**, one lane table (`8ea5756203e1`).

**Next:** the CMOS5L hardening gate (PDN hypothesis first) → re-close 1.5 on
memory tech, the `uo_out` map and the serialiser → Part 1 RTL, which must turn
both the parameter contract and F2 face 3 green.

**Still owed:** `C` unmeasured; the engine is not built; `nptest` exactness;
H4 (`refs/ieee_try.bin`, `refs/t2.bin` — safe to delete, Nate's hand); the
memory-index compaction (Nate's go).
