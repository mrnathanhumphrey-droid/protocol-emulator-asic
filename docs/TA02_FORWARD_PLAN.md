# Forward plan as it currently stands — the audit target

⚠️ **This file exists so the plan can be red-teamed.** Everything below is the plan
*as currently understood*, written down explicitly including the parts that are
assumption rather than measurement. Where something is an assumption it says so.
**Nothing here is a commitment and nothing here has been reviewed.**

---

## 1. Where we actually are

| rung | claim | status |
|---|---|---|
| TA-01 | UART-TX conformance is a **decidable** reachability query, non-vacuous | committed `e3c1b05` |
| TA-01b | conformance over an **unbounded** run (fixpoint closes) + zone cross-check | committed `e3c1b05` |
| TA-01c | tolerance band **synthesized**, not tested (`−1/20 < ε < 1/18`) | committed `e3c1b05` |
| TA-02 | **generic table interpreter** — UART + SPI + PWM off one protocol-free machine | **green 8/8, UNCOMMITTED** |

**Everything is the model. No RTL implements any of it.** The interpreter is a model
of the semantics RTL must implement.

## 2. The open decision, not a chore

TA-02 found **two defects in TA-01's `UartReceiver`** (see `TA02_RESULTS.md`
findings 1 and 2): an effective bit period of `T+1` cycles (114,943 baud, not
115,200) and a level check where the formal models check phase.

Fixing it **re-triggers TA-01, the TA-01b fixpoint and the TA-01c comparison as one
unit.** Options, none chosen:

- **(a)** fix and re-certify everything as one commit — clean, costs a full re-run
- **(b)** fix only the receiver's period, leave the level check, document the
  remaining gap — cheaper, leaves a known divergence in the record
- **(c)** ⛔ **WITHDRAWN — its stated reason was false.** It argued "the formal
  models already check phase, so the Python model was the outlier". But TChecker
  **checks the line level**, exactly as the Python receiver does, and still lands on
  458 — `TA02_RESULTS.md` says so in its own isolation table. The outlier is the
  **T+1 period**, not the level predicate. (c) retired the level check on a false
  premise, and would have done it precisely when RTL — which reads levels, not
  phases — is about to need it. (b) banks the same false premise more cheaply.

**DECIDED: option (a).** Fix and re-certify as one unit. The fixpoint re-run is
sub-second at `T = 434`, so the cheap options were never buying much.

⛔⛔ **And the re-certification cannot be a re-wording.** TA-01b's reset diagnostic
— *"max clock `== T`, not `< T` … off-by-one in the spec's phrasing, not a
failure"* — **is the defect**, and it is load-bearing for the BFS-termination
argument: a guard that passed *because of* the thing it was screening for. The
"13,023 states / 30 states per clock tick" law is likewise defect-derived. Both
must be **re-derived under the fix**, not re-phrased.

⚠️ Still an assumption, now narrowed: decidability, determinism and totality are
argument-level and genuinely independent of both defects. The *diagnostics that
certify them* are not. Verified so far: determinism and totality still green over
11,362 (state × clock × level) configurations.

## 3. Rungs intended next, in order

1. **TA-03 — full SPI conformance.** Not just emission (TA-02 did that) but a
   deterministic+total SPI monitor, the same decidability argument, and a
   synthesized band over the table's guard field. ⚠️ **Unpriced:** SPI has no
   baud-drift axis the way UART does (the clock is carried on a wire), so it is not
   obvious the band story transfers at all. The interesting SPI axis is probably
   setup/hold and CS-to-first-edge, which is a *different* kind of parameter.
2. **The data-source extension.** TA-02's descriptor bakes the payload into the
   table (one entry per bit), so changing the data means reloading the table. A
   real emulator wants a FIFO or shift register. This is the **first descriptor
   extension** and it has to be priced before RTL, because it adds state the
   branch-point audit currently proves absent.
3. **I²C.** Needs bidirectional pins and open-drain — `uio_oe` on Tiny Tapeout. The
   input guard exists; **tri-state does not**, so this is a second descriptor
   extension, not just a new table.
4. **The RTL refinement probe.** Does the Verilog implement the TA-02 interpreter?
   This is the first rung where the model and the silicon can diverge.
5. **Lean, for soundness.** The claim "BAD unreachable ⟺ every behaviour conforms"
   rests on determinism + totality. Those are checked mechanically but the
   *equivalence* is argued in prose.

## 4. Hard constraints — ⛔⛔ THIS SECTION WAS WRONG BY 24×

**RETRACTED as first written:** it stated "one tile = 167 × 108 µm, roughly **1K
cells**" as a *hard constraint*. The primary source says the opposite, verbatim:

> "**Set the tile size in info.yaml to 6x4.**" … "An 6x4 allocation is **24 tiles**.
> At approximately 200um × 150um per tile, that's about **0.7 mm²** of nominal tile
> area. As a rough estimate, budget for about **1K logic cells per tile**." … "We
> are working on the possibility of scaling up to 8x4 tiles (~30% more area)."

So **1K cells is the per-tile figure and the entry gets ~24K cells.** The one-tile
target was **self-imposed**, and it is what the "minimal descriptor" was optimized
against — a budget that does not exist.

⛔⛔ **Worse than a mistake: `ARCH_PREREG_01.md:110` had already logged the tile
count as "SPEC DISCREPANCY, UNRESOLVED, NOT TO BE RESOLVED BY ARITHMETIC."** This
section silently resolved it, in the wrong direction, by writing one side down as
settled. A recorded open question was closed by omission.

**Actual constraints:**

- module `tt_um_*`, pins `ui_in[7:0]`, `uo_out[7:0]`, `uio_in|out|oe[7:0]`
- **`tiles: "6x4"` = 24 tiles ≈ 24K logic cells**; `info.yaml` currently says `1x1`
- ⚠️ **The two primary sources conflict.** The `cmos5l` template's own `info.yaml`
  reads *"Valid values: 1x1, 1x2, 2x2, 3x2, 4x2, 6x2 or 8x2"* — **`6x4` is not in
  the list**, so precheck may reject the instructed setting. Resolve with the
  organizers, not by arithmetic (the mistake above).
- ⚠️ `CLOCK_PERIOD: 20` → 50 MHz is a **template default** in a file headed "DO NOT
  EDIT THIS FILE unless you know what you are doing", and the brief mandates no
  frequency — it says "too slow at **your chosen** clock frequency". `T = 434`, the
  band, the 64-entry budget and every model number re-derive if PnR closes slower.
- the submission must be **open source** (Apache-2.0 LICENSE is already present)
- submission deadline **2027-01-18**; the brief "strongly recommend[s] working in
  teams"

**On fitting:** no longer the live worry. Paper estimate: 64 entries × (g 16 + out 8
+ in_pin 4 + in_pol 1 + next_a 6 + next_b 6) = **2,624 bits**; Tiny Tapeout
publishes ~**320 DFFs per tile**, so ≈**8 tiles in flops**, ≈2 in SRAM — and the
brief itself says "For instruction memory, **SRAM can be more area-efficient than
flip-flops**." Comfortable in 24; impossible in 1. ⛔ Still an estimate: one `gds`
run reporting mapped cell area is what would make it a measurement.

## 5. Things on the plan that are assumption, stated plainly

- that a table interpreter is the right architecture at all, rather than a small
  fixed set of hard protocol engines
- that the formal-methods angle is what distinguishes the entry, rather than area,
  throughput or pin count
- that one tile is the target (vs. a multi-tile submission)
- that genericity proved on UART + SPI + PWM predicts genericity on the protocols a
  judge will care about
- that the descriptor will not need a third and fourth extension once I²C and a
  data source land — i.e. that the "minimal descriptor" is actually stable
