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

## 2c. WILSON'S RULINGS — accepted, and two are now standing law

**STANDING LAW 1 — agreement is not corroboration unless the copies can fail
independently.** `_enabled` was built *specifically* to be the independent
re-derivation that stops the determinism/totality gate proving the implementation
against itself — and it carried the identical off-by-one, so the gate passed
because both copies shared the bug. Look at what actually caught things in this
project: **sigrok, Imitator, TChecker — the foreign authorities.** Our own
"independent" re-derivations caught nothing, because they were the same hand.
Therefore: **a same-author re-derivation is weak corroboration; foreign authority
is the real thing.** And never file a boundary signal as "just phrasing" without
re-deriving it from scratch.
⭐ This also matters in the room we are aiming at: *"independently re-derived" gets
eaten alive by a verification reviewer unless you can show the copies CAN diverge.*
So every independence claim in the write-up must come with a demonstration that the
two routes are capable of disagreeing.

**STANDING LAW 2 — the plan is checked against the pre-reg falsifiers before it is
a plan.** Three instances now of generating a good pre-registered guard and then
not honouring it: the off-by-one waved off as phrasing, F5 ordering (tri-state
behind two rungs of protocol work), and `ARCH_PREREG_01`'s tile count "closed in
the wrong direction by omission."

**CONFIRMED STANDING — the method survives and transfers; only the architecture is
retracted.** Conformance-as-a-decidable-query, the band proved over a
reprogrammable field, and foreign-authority adjudication all carry forward. The 24×
budget error made a minimal, no-arithmetic, one-`pc` machine look *necessary* when
it never was. Concurrency plus the **provable jitter bound were always the
differentiator** — the thing the six-repo prior-art sweep found unclaimed — so the
red team corrected a **target error**, not a bug. The method was never the thing
that was wrong.

### ⭐⭐ THE RULING THAT RESHAPES THE NEXT RUNG: A2 comes out of the RTL rung

I had "A2 derived then proved" *inside* the queue-engine RTL rung. **Wilson pulled
it out and ahead, and gated the RTL on it.**

Reason: A2 — the lateness bound, which F2 calls the entry's premise — has never
been derived, and **a concurrent, arithmetic, multi-lane queue engine is a far
harder formal object than single-clock UART.** It may not sit in a clean decidable
fragment, and the bound is precisely the thing that could fail to be provable on
it. So prove the bound exists and holds **on the abstraction** — the way Imitator
synthesized the UART band — *before* building the engine in silicon. If A2 is not
derivable on the model, we learn the entry's premise is unsupported **now and
cheaply**, instead of after building the engine around it.

**That is the TA-01c discipline — band on the model before any RTL — applied to the
one claim the whole submission rests on. Method before machine, and here the method
IS the bound.**

### Load path (§6) — ACCEPTED, with three amendments

1. **Mode-select and pointer-reset come from the DEDICATED inputs (`ui_in` / `ena`),
   never from the 8 `uio`** — so the protocol pins stay free. (This is what §6
   already specifies; it is now a hard constraint rather than a convenience.)
2. **Mutual exclusion is an explicit SCOPE CHOICE, stated as such:** reprogram =
   **halt, reload, resume**. No mid-transaction swap. Writing it down as a choice is
   what stops it being read later as an oversight.
3. **Pre-register the load readback / checksum even if it is not built yet.**
   "Reprogrammable" + "provably correct" implies **"provably loaded correctly"**,
   and the load path is a new surface where that can go wrong. §6's L3 falsifier
   already names it; it is now pre-registered rather than optional.

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
### ⭐ WHAT THE LITERATURE PULL CHANGED (see `A2_FRAMEWORK.md`)

Four things moved, and three of them change this rung list:

1. **P3 is CLOSED, not a constraint.** Non-preemption gives mutual exclusion for
   free — corroborated by two foreign sources. **Rung 4 may share a shift register
   or a memory port across lanes with no extra blocking term.** That is an area
   saving we were about to forbid ourselves on a false premise.
2. **The FIFO stops being a convenience and becomes the SCHEDULABILITY REMEDY.**
   Joseph & Pandya: when a lane's response time exceeds its inter-arrival time,
   *"buffers can be added"* — with a method for computing **how many**. So the data
   source is no longer "a real emulator wants one"; it is what makes a reactive lane
   provable, and its depth must be **derived, not guessed**.
3. **The blocking term is a max over the OTHER lanes' service times**, not `(k-1)`
   of the lane analysed. Our lanes have heterogeneous `C` by construction (a UART
   bit-action, an SPI edge and an I²C action differ), so the engine's spec must
   record a per-lane worst-case service time, not one global `k`.
4. **EDF buys one cycle over static priority** on that term. The discipline was
   already chosen; this is a consequence, not a preference.

3. **⭐⭐ A2 DERIVED AND PROVED ON THE MODEL — THE GATING PREMISE.** Not inside the
   RTL rung; ahead of it, as its gate. A concurrent multi-lane queue engine is a
   much harder formal object than single-clock UART and may not sit in a clean
   decidable fragment — so if the bound is not derivable on the abstraction, the
   entry's premise is unsupported and we find out cheaply. Same discipline as
   TA-01c: the band on the model before any RTL.
4. **The queue engine in RTL, REFINING the A2-carrying model.** Gated on rung 3.
   It has never been attempted.
5. **One protocol end-to-end through RTL** — model, Verilog, gate level — bridged by
   the existing foreign decoders: dump the cocotb waveform into the *same* sigrok
   PDs and `cmp` against the model's bytes, at RTL **and** gate level, in CI. That
   bridge does not exist today; `test/test.py` is still the stock stub asserting
   `uo_out == 50`.
6. **FPGA.** In the brief, owed in both results docs, and there is an unused
   `.github/workflows/fpga.yaml` — yet it appeared in no rung. It is also the only
   place finding 2's level-check hazard meets a real receiver.
7. **The remaining protocols**, then the band re-synthesized over the descriptor.
   ⭐ The **FIFO depth per lane comes out of A2**, not out of taste — build it only
   for the lanes A2 says need it, sized by Joseph & Pandya's method.
8. **Lean, for soundness** — the `BAD`-unreachable ⟺ conformance equivalence is
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
- ✅ **The conflict is RESOLVED BY MEASUREMENT, not by arithmetic.** The template's
  own `info.yaml` reads *"Valid values: 1x1, 1x2, 2x2, 3x2, 4x2, 6x2 or 8x2"* —
  `6x4` is not in that list — but **`precheck` PASSED at `6x4`** (run 37043643942,
  14m27s). The TT tooling itself is a primary source and it accepts the brief's
  instruction; the comment is stale. No organizer mail needed.
  ⛔ **Wilson's instruction to keep this soft still stands and was written without
  this datum:** the cell budget stays a **soft target with margin** and the tile
  allocation stays **parameterizable**. One precheck pass licenses proceeding at
  `6x4`; it does not license re-locking a contested number, which is how the 24×
  error happened in the first place.
- ⚠️ `CLOCK_PERIOD: 20` → 50 MHz is a **template default** in a file headed "DO NOT
  EDIT THIS FILE unless you know what you are doing", and the brief mandates no
  frequency — it says "too slow at **your chosen** clock frequency". `T = 434`, the
  band, the 64-entry budget and every model number re-derive if PnR closes slower.
- the submission must be **open source** (Apache-2.0 LICENSE is already present)
- submission deadline **2027-01-18**; the brief "strongly recommend[s] working in
  teams"

### ✅ MEASURED — the flow has now been run at `6x4`

`gds` run 37043643942, 51m52s, on the template stub. **The two primary sources'
conflict is resolved empirically: `precheck` PASSED at `6x4`** (14m27s), despite
`info.yaml`'s own comment listing only `1x1 … 8x2`. The comment is stale; the
brief's instruction works. GDS built, `tt_submission` artefact produced, gate-level
test green.

| measured | value |
|---|---|
| die area @ `6x4` | **916,214 µm² (0.916 mm²)** |
| core area | 902,417 µm² |
| instances (stub) | 53 — 52 multi-input combinational + 1 inverter |
| std-cell utilization | **0.0573 %** |
| avg cell area, this mix | 9.76 µm² |

⭐⭐ **The measured die is ~31 % LARGER than Jane Street's own "about 0.7 mm²"
nominal figure, and ~2.1× the 0.43 mm² that the template's 167×108 µm comment
implies.** `ARCH_PREREG_01`'s unresolved discrepancy #1 is therefore settled by
measurement, and **the real number is bigger than either side of the argument** —
which is exactly why it was logged as "not to be resolved by arithmetic".

**Capacity, derived from this run rather than from published per-tile guidance:**
902,417 µm² core ÷ 9.76 µm² ≈ **92 K cells at 100 % utilization for this cell mix**.
⛔ That is an upper bound tied to the mix: a flop-heavy design has cells 2–3× larger,
so realistically ≈30–45 K at 100 % and ≈15–25 K at a routable ~50 %. That brackets
the 24 K paper estimate and confirms the conclusion: **comfortable at 24 tiles,
impossible at 1.**

The table-memory point survives and is now sharper: 64 entries × 41 bits =
**2,624 bits**, which at Tiny Tapeout's published ~320 DFFs/tile is ≈8 tiles — a
third of the chip in flip-flops. **That is the measured case for SRAM**, and the
brief agrees: "For instruction memory, **SRAM can be more area-efficient than
flip-flops**."

⛔⛔ **A4 ("closes timing at 50 MHz") IS NOT TESTED BY THIS RUN, and the reports
look like it is.** Post-PnR WNS (setup) reads **0.0 at all three corners**
(`nom_slow_1p08V_125C`, `nom_typ_1p20V_25C`, `nom_fast_1p32V_m40C`) — but the stub
is *purely combinational*, 53 cells and **zero flip-flops**, so there is no
registered path to time. `0.0` here means "no path", not "met with zero margin".
Banking that as a green would be reading the wrong field, the way `metrics.csv`'s
`wns` was once mistaken for a CTS worst slack. **A4 stays open until real
sequential logic goes through the flow.**

⚠️ `viewer` failed, and it is **not** a design failure: "Failed to deploy to GitHub
Pages." The repo is private and Pages is not enabled. Cosmetic.

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
