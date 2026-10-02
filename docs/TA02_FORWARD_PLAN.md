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

> ⛔⛔ **THE SECOND HALF OF THAT CLAIM IS REFUTED — BY DOING IT.** Re-derived, the
> state count is **13,023 before and after** and the law is **slope exactly
> 30.0000** (`30T + 3`) both ways. It is defect-**invariant**: the reachable set
> counts `(executor, monitor)` pairs along a phase-locked trajectory plus idle
> branching, and moving *where within a bit* the sample fires does not change how
> many distinct pairs occur. **Only `max_clock` ever depended on the threshold**
> (434 → 433). ⭐ Re-deriving includes reporting that a number you predicted would
> move did not — otherwise "re-derive, don't re-word" just relocates the guesswork.

✅ **DONE.** Fix applied, every certificate re-run green, `run_ta01b.py` written
(it had never existed despite being the documented re-run command), and
`phase_oracle.py` added so the oracle's band `[413, 458]` matches the synthesis.

⚠️ Still an assumption, now narrowed: decidability, determinism and totality are
argument-level and genuinely independent of both defects. The *diagnostics that
certify them* are not. Verified so far: determinism and totality still green over
11,362 (state × clock × level) configurations.

## 2b. ⛔⛔ THE ARCHITECTURE RETRACTION — two pre-registered architectures existed

The repo carried **two incompatible architectures, both called pre-registered.**

`ARCH_PREREG_01.md` commits to *"a single shared action engine serving all lanes,
driven by a deadline-ordered action queue"*, with a per-lane descriptor of
*"pin, drive mode, **shift reg, bit counter, divider**, next-action timestamp"*,
**A2** (worst-case lateness `(Q-1)×k`, *"provable, not just measured"*), and **A5**
(all three protocols **simultaneously** on one engine). **F2** states that losing
the lateness bound *"invalidates the entry's premise, not just a number."*

TA-02 built a machine whose state is `(pc, clock)` **and nothing else**, and whose
audit **kills a bit-counter mutant by name**. It has no queue, no shift register,
no bit counter, and `out` is a pure function of `pc` — so it can drive exactly
**one lane at a time**, making A5 unreachable from it by construction.

### ⛔ RETRACTED: TA-02's architecture claim. The queue architecture stands.

Not a compromise — the queue wins on four independent counts:

1. **It is what the brief asks for:** *"a tiny CPU with an instruction set designed
   for reading pins, writing pins, counting cycles."* A table with no arithmetic is
   not an instruction set.
2. **It is the only one that can reach A5.** Concurrency needs the queue.
3. **It is the only one that survives the stretch protocols.** USB needs NRZI plus
   bit-stuffing, Ethernet Manchester plus CRC32, CAN stuffing plus CRC15. The
   pre-reg's descriptor *already has* the shift register and counter these need;
   TA-02's has no arithmetic at all.
4. **The 24-tile budget removes the reason TA-02 was minimal.** "No state but
   `(pc, clock)`" was a virtue under a 1K-cell ceiling that does not exist.

### ⭐ What TA-02 keeps, re-aimed rather than discarded

- **The method, which is the actual asset:** a tolerance band *synthesized over the
  fields an operator reprograms*. That transfers directly — the pre-reg's descriptor
  already carries a reprogrammable **`divider`** and **`next-action timestamp`**,
  and those are the same kind of field as TA-02's `G`. The band becomes a constraint
  on the descriptor, not on a table that no longer exists.
- **The behavioural genericity result:** one mechanism, three protocols, three
  foreign decoders, byte-identity. That is evidence about *table-driven sequencing*
  and it survives the machine around it changing.
- **The two TA-01 defects**, which are about the receiver and independent of all of
  this.
- **`g >= 1`** — zero-time transitions are a combinational path in RTL whatever the
  surrounding architecture.

### ⛔ The debt this exposes, stated rather than quietly carried

**A2 and A5 are pre-registered and addressed by NO rung.** The lateness bound that
F2 calls the entry's premise has never been derived, let alone proved, and nothing
built so far runs two lanes at once. Five of five planned rungs were verification
rungs for a machine that is now retracted. **That is the single largest hole in the
plan, and it is larger than any individual defect the red team found.**

## 3. Rungs intended next — REORDERED

⛔ The previous order put RTL fourth of five. The brief says *"**Run synthesis
early**, check the mapped cell area, and leave room for clock-tree buffers and
routing."* And `ARCH_PREREG_01`'s own **F5** says a `uio_oe` pin-abstraction failure
*"must be fixed before any protocol work continues"* — while the old order made
tri-state **rung 3**, behind two rungs of protocol work. The plan was violating a
falsifier it had pre-registered itself.

0. **DONE — scaffold and run the flow at `6x4`.** Settles the area budget with a
   measurement and tests the `6x4`-vs-template conflict in CI.
1. **The program-load path** (§6). The brief's central ask has no owner; everything
   downstream inherits its pin budget and its memory shape.
2. **Tri-state, settled against the RTL stub.** F5 demands it first and it is a
   20-line test, not a rung.
3. **The queue engine in RTL, with A2 derived and then proved.** This is the
   premise. It has never been attempted.
4. **One protocol end-to-end through RTL** — model, Verilog, gate level — bridged by
   the existing foreign decoders: dump the cocotb waveform into the *same* sigrok
   PDs and `cmp` against the model's bytes, at RTL **and** gate level, in CI. That
   bridge does not exist today; `test/test.py` is still the stock stub asserting
   `uo_out == 50`.
5. **FPGA.** In the brief, owed in both results docs, and there is an unused
   `.github/workflows/fpga.yaml` — yet it appeared in no rung. It is also the only
   place finding 2's level-check hazard meets a real receiver.
6. **The remaining protocols**, then the band re-synthesized over the descriptor.
7. **Lean, for soundness** — the `BAD`-unreachable ⟺ conformance equivalence is
   still argued in prose.

⚠️ **TA-03 (full SPI conformance) is deliberately no longer rung 1.** It would have
proved determinism, totality and a band over a descriptor that is being replaced.
Its one durable observation stands: SPI has no baud-drift axis (the clock is on a
wire), so the band story does not transfer unexamined — the SPI parameters are
setup/hold and CS-to-first-edge, a different kind of quantity.

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

## 6. THE PROGRAM-LOAD PATH — spec, for review

⛔ **Why this is rung 1.** The brief's central ask is *"Your chip should be
reprogrammable enough to support new protocols **after** fabrication"*, and
describes the device as *"a tiny CPU with an instruction set designed for reading
pins, writing pins, counting cycles."* Nothing in TA-01, TA-02 or `ARCH_PREREG_01`
specifies how a program gets **in**. TA-02's state was *"`(pc, clock)` and nothing
else"* — no address port, no data port, no handshake. A judge asks this first.

### The pin problem, and why it dissolves

`ARCH_PREREG_01` spends all 8 bidirectional pins on protocols (UART 2 + SPI 4 +
I²C 2 = exactly 8), and `ui_in`/`uo_out` are 8 each. There is no room for an
address bus, a data bus and a handshake — **if loading and running are
simultaneous.** They are not: while programming, no protocol is being emulated.

⭐ **So `uio` is reused as the load data port, and the address bus is deleted
entirely by auto-increment.** Cost in pins: zero.

| signal | pin | in `prog_mode` | in run mode |
|---|---|---|---|
| `prog_mode` | `ui_in[7]` | 1 | 0 |
| `wr` strobe | `ui_in[6]` | write `uio_in[7:0]` at the pointer, then **pointer++** | — |
| `ptr_rst` | `ui_in[5]` | reset the write pointer to 0 | — |
| data byte | `uio_in[7:0]` | the byte being written | protocol pins |
| `uio_oe` | — | **all 0** (inputs) while `prog_mode` | per protocol |
| `ack` / loaded-byte count | `uo_out[7:0]` | echoes the low pointer bits, so a host can confirm the write landed | protocol outputs |

Writes are **sequential only** — a program is loaded front to back. This is what
removes the address bus, and it is sufficient: there is no use case for patching
one entry of a program in place that reloading does not also serve.

### Memory shape

Byte-wide, sequentially written, SRAM-backed. The brief says so directly: *"For
instruction memory, **SRAM can be more area-efficient than flip-flops**."* Paper
figures to be replaced by a `gds` measurement: a 64-entry × 41-bit table is **2,624
bits**; Tiny Tapeout publishes ~320 DFFs per tile, so flops cost ≈8 tiles while an
IHP single-port macro (256×8 ≈ 17.5 kµm²) costs ≈1–2. At 24 tiles either fits, but
only one of them leaves room for the engine.

### Area and the honest unknowns

The loader itself is a pointer counter, a write-enable, an edge detector on `wr`,
and a mux on `uio_oe` — on the order of **50–80 cells**, trivial against ~24K.

⚠️ **Unmeasured / undecided, flagged rather than buried:**
- **`wr` is a pin-driven strobe, so it is asynchronous to `clk`** and needs a
  synchroniser plus edge detection. Metastability on a load port is not fatal (a
  bad load is detectable by readback) but it must be explicit, not accidental.
- **No readback path is specified.** `uo_out` echoing the pointer confirms *a*
  write happened, not *what* was written. A CRC over the loaded image on `uo_out`
  would close that for ~60 cells, and is the honest version of RT3's "attestation"
  idea — a real signature core blows the budget.
- **Whether `prog_mode` should be allowed to interrupt a running emulation**, or
  only out of reset. Interrupting mid-protocol is a half-driven-bus hazard.
- **Whether the engine's descriptor and the action program share one memory** or
  two. This is coupled to the queue engine (§2b rung 3) and should not be decided
  before it.

### Falsifiers for this spec

| # | if | then |
|---|---|---|
| L1 | all 8 `uio` are genuinely needed *concurrently* with loading | the phase-exclusivity trick fails and a real load interface must be found — re-scope pins |
| L2 | a host cannot clock `wr` fast enough to load a program in acceptable time | widen to a `uio`-strobed burst, or accept the load time and say so |
| L3 | the loaded image cannot be verified from outside the chip | reprogrammability is unfalsifiable from a judge's seat — add the CRC readback |
| L4 | SRAM macros do not meet timing at the chosen clock | fall back to flops and re-derive the entry budget from the tile count |

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
