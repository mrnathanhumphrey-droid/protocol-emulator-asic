# The clocked SCL high phase, and a checker blind to timing

Decision trace for the F1/F2/F3/F4 + G1/G2 + C1/C2 ruling. Evidence first,
decision second, what was rejected third.

---

## 1. The finding, measured

On an **open-drain** clocked lane the SCL **high** phase was the synchroniser
latency and nothing else — not the programmed delay.

| programmed `d` | 9 | 25 | 60 | 120 |
| --- | --- | --- | --- | --- |
| **t_HIGH** (pre-fix) | 6 | 6 | 6 | 6 |
| t_LOW (pre-fix) | 7 | 26 | 58 | 119 |

`d` spans **13×**; t_HIGH does not move. t_LOW tracks `d`. Against UM10204
minima at 50 MHz — **200** cycles (Sm), **30** (Fm), **13** (Fm+) — the clocked
scheme met **no** I2C mode, and no choice of `d` could fix it, because the high
phase was not programmable at all.

**Control arm, same bench, same cycle:** push-pull `ckfive` read t_HIGH = 25 =
`d`, symmetric. So the bench was not the explanation.

**Root cause.** `src/pe_engine.v` arms the post-HIGH park on
`ck_act & ck_is_high & ck_park_en & ~l_mode`, with `ck_act = ck_shift |
ck_shiftin` and `ck_park_en` hardwired 1 — so *every* open-drain clocked high
phase parks. On release, `arm_hit` rebased `l_timestamp := now`, making the
next dispatch eligible immediately.

**Scope, measured not assumed.** The *certified* I2C frame is unaffected:
`build_i2cframe`'s `OP_SHIFT` actions carry `lvl = 0`, so they are not clocked,
and SCL is driven by explicit `OP_LEVEL` actions whose high phase is the
programmed delay. It does not appear in the clocked set at all. Nothing sigrok
adjudicated is invalidated. Affected are the clocked images —
`corpus_i2c`, `corpus_all5` lane 0, `ckdegen2` — and the FRAM write / random
read, which are built from clocked actions.

## 2. The decision

**F1 — `eligible = observed_rise + d`.** UM10204's own clock-synchronisation
rule: a master counts its HIGH period from the moment it *sees* SCL high. The
synchroniser lag therefore only adds to t_HIGH, which is the safe direction.
Zero new encoding bits — `d` is the existing delay field, and `ACT_FIELDS` is
24 of 24 bits with nothing spare. Implemented as a per-lane combinational
`ck_rebase`, with `ck_dly` read from the lane's **head slot** (sound because
`ST_WB`'s `ck_hold_eff` arm skips the invalidation, so a held action's word
stays put) — **zero added flops**, against 50 for a per-lane delay register.

An ordinary `OP_ARM` still rebases to `now`, and must: Ruling 1's
`ARM → no-op(half) → sample` idiom anchors UART-rx's grid to the peer's edge.
`l_ckpark` is the only thing separating the two.

**F2 — the RTL's park scope was right; the model was wrong.** The golden model
parked only for `SHIFTIN`, because only a receive has a bit to collect. But a
target may stretch on *any* bit, including one we are transmitting.
`model/clocked_phase.py` now parks after every open-drain clocked high phase
and carries the lane's pin mode.

**Post-fix, measured:**

| programmed `d` | 9 | 25 | 60 | 120 |
| --- | --- | --- | --- | --- |
| **t_HIGH** | 13 | 29 | 64 | 125 |
| t_LOW | 7 | 20 | 54 | 107 |

t_HIGH ≥ `d` + 4 on every lane, and **unchanged** by a 200- or 4000-cycle
stretch. Model invariant **I10** asserts t_HIGH ≥ `d` from the observed rise at
four periods × four stretch regimes; the pre-fix behaviour, reachable as
`m_eligible_at_rise`, fails it at every point.

## 3. G2 — the ledger entry: a checker blind to its own dimension

**Layer B reported "every clocked action matched the model exactly" throughout.
It was telling the truth, about dispatch counts.** A park changes *when* a
dispatch happens and never *how many* there are, so model and RTL disagreed
about timing for an entire arc with every check green.

This is the **same class** as the sweep-verdict hole recorded in
`test/tb_verdict.v`: there, the per-arm verdict could not see watchdog failures
because the grep pattern and the log cut each discarded them, so a broken
checker read exactly like a passing one. Both are *a checker blind to the
dimension it was trusted on*.

⇒ Closed by **G1**: `test/clocked_conform.vh` now also checks inter-dispatch
**gaps**.

**G1 checks a bound, not an equality, and the reason is measured.** The engine's
timestamp advances from the previous timestamp absolutely (P8), so a dispatch
serviced late under EDF contention is followed by one that is on time and the
gap comes out *shorter* than `d` — observed at **2, 5, 6 and 13** cycles below
`d` on a four-lane image. A cycle-exact check would fail on every multi-lane
program for correct behaviour, and widening the tolerance until it passed would
stop it checking anything. So G1 checks the half that is
contention-independent, which is exactly the F1 property: **the gap after an
open-drain clocked HIGH is at least `d`**, because the park's release is
`rise + d` and contention can only delay further. LOW gaps carry no such bound
and are not claimed.

| arm | `corpus_i2c` | `corpus_all5` | `ckod_image` |
| --- | --- | --- | --- |
| clean | ok, 736 gaps, margin 4 | ok, 712 gaps, margin 4 | ok, 1190 gaps, margin 4 |
| `M_CK_RISE_ELIGIBLE` | **1104 failures** | **853 failures** | **1967 failures** |

## 4. C1/C2 — measured against UM10204, and named honestly

`model/a2/gate_um10204.py` adjudicates a measurement produced by
`test/phases_run.sh` (clean + mutant + two stretch arms + a push-pull control).

**This is not foreign certification.** It is our code checking our traces
against a table **transcribed** from a third-party standard. UM10204 is not
vendored and cannot be — `refs/` is gitignored with the guard committed,
because the submission is open source. sigrok certifies that a foreign
*decoder* reads our frame; a decoder will happily decode a frame whose high
phase is a tenth of the legal minimum. The gate reports "measured vs UM10204
minima" and never "compliant".

One independent cross-check agreed: the t_LOW minima give `d ≥ 25` (Fm+),
`65` (Fm), `235` (Sm) at 50 MHz, derived separately in the ruling that ordered
the gate.

**C2 — `d ≥ t_LOW(min)` is not the rule, and the measurement is why.** t_LOW
came out *below* the programmed `d` on every lane (shortfall 2/5/6/13), because
the LOW dispatch competes under EDF. The high phase is immune — it is counted
from the rise. So only t_LOW needs margin:

| mode | t_LOW min | observed shortfall | `d` floor | `DLY_W=10` reaches? |
| --- | --- | --- | --- | --- |
| Sm 100 kHz | 235 | 13 | 248 | yes |
| Fm 400 kHz | 65 | 13 | 78 | yes |
| Fm+ 1 MHz | 25 | 13 | 38 | yes |

⚠ The shortfall column is an **observation on a four-lane image, not a bound**.
The bound is A2's `r_i - C` for the lane. Quoting a measured maximum as a bound
is the error that retracted a universal `J`, so the `d` column is a floor to
check against A2, not a shipped number.

## 5. Owed

* **t_HD;DAT = 0 against the 300 ns bridging note.** Measured: three of four
  lanes provide **zero** data hold across the SCL fall — SDA changes in the same
  dispatch that takes SCL low. UM10204 Table 10's tabulated t_HD;DAT minimum is
  0 ns, which 0 meets; the table's own note requires a device to internally
  provide ≥ 300 ns (15 cycles) to bridge the undefined region of SCL's falling
  edge, which it does not. The gate reports both and does not fail on the
  weaker test. **Owed: a ruling on whether the bridging note is in scope.** This
  is the previously-owed electrical item, now a number.
* **t_SU;STA, t_HD;STA, t_SU;STO** — need START/STOP conditions, which the
  clocked images do not contain. Owed against the certified two-action frame.
* **t_r / t_f** — edge rates are a board and pull-up property; a
  cycle-resolution trace cannot see them.
* **`L_SYNC` 3 vs 4.** The model's `L_SYNC = 3` against a measured post-rise
  offset of 4–5 cycles. The difference is dispatch latency, which the model
  does not represent (it models release times, not pin-move times). Safe
  direction for compliance — the RTL's t_HIGH exceeds the model's prediction —
  but the two numbers mean different things and should not be compared without
  saying so.

## 6. Rejected

* **`max(timestamp, observed rise)`** — the first proposal, and wrong exactly
  when it matters. Once the peer stretches past `d` the max resolves to the
  rise, the next dispatch fires one synchroniser latency later, and t_HIGH
  collapses back to ~`L_sync` — immediately after a stretch, which is when the
  rule is being tested.
* **A per-lane delay register** to carry `d` to the park release — 50 flops to
  store a word already sitting in `l_act[hix[i]]`.
* **Parking only for `SHIFTIN`** (matching the old model) — does not fix
  compliance; the ACK bit's high phase would still be the synchroniser latency.
* **Clocked = push-pull/SPI only**, with I2C staying on the certified
  two-action idiom — held as the fallback if F1 fails its gates. It loses the
  action-budget halving precisely where the FRAM budget wanted it.

## 7. Consequence for `d_min`

The `d_min` closed form in `model/a2/gate_dmin_clocked.py` was **re-derived**,
not carried: both its premises changed. At `d = 25` the FRAM write is now
**81** (was 53) and the random read **50**, both ≥ `D* = 20`, both `J = 1` —
the pre-registered admissibility claim still holds, with more margin.

Re-evaluated at a **mode-legal** `d` as well, since these two programs are I2C
and `D_MIN_SHIPPED = 25` is the shipped *SPI* period: admissible with `J = 1` at
every declared mode — `d_min` 81/50 (Fm+ at d=25), 201/130 (Fm at 65), 711/470
(Sm at 235). The claim does not rest on the SPI period.

⚠ **Two errors in that re-derivation are worth recording.** The first rewrite
charged each spacing the gap after its *own* retiring dispatch instead of its
predecessor's; the totals still matched (66 + 341 = 63 + 344) so a sum check
would have passed while every individual spacing was misattributed by exactly
`L_SYNC` — and `d_min` is a minimum over individuals. The two-route cross-check
caught it on the first run, which is the entire reason that gate computes the
same quantity twice.

Second, the §3a **must-fire stopped firing**, and the cause was the fix rather
than the check: before F1 the post-HIGH gap was the 3-cycle park, so the naive
all-dispatch `d_min` was 3 on every clocked program and the wrong definition
refused everything. F1 made the tightest inter-dispatch gap `d` itself, so no
sub-`d` gap remains. The must-fire was rewritten to test what §3a still buys —
it understates `d_min` by 2.0–3.2×, and between the utilisation floor and twice
it the two definitions still disagree about admission (fires at `d` = 9, 12, 14).
A must-fire that silently stops firing because its target was fixed is not a
pass.

---

## 8. The clocked I2C lane in A2 — `D_tol` and `r` derived

`model/a2/gate_clocked_lane_a2.py`, pyRTA as the PRIMARY bound.

**The two-action row could not be reused.** `bursty.py` carries
`BLane("I2C 400 kHz", T=45, D_tol=15, J=J_SHIPPED+L_JIT)`. `T = 45` is the short
half of an **asymmetric 80/45** SCL built from `OP_SHIFT` + `OP_LEVEL`, and
`D_tol = 15` was derived from UM10204 T11 for that geometry. The clocked scheme
makes a *symmetric* clock from one action per bit.

**`D_tol = d − t_LOW(min)`**, derived rather than assumed. Writeback advances
the timestamp absolutely (P8), so the HIGH's release is `d` after the LOW's
however late the LOW was served:
`t_LOW(observed) = d + (HIGH start delay) − (LOW start delay)`, minimised at
`d − (r_i − C_i)`. Only t_LOW needs margin — F1 counts the high phase from the
observed rise, so service lateness only *lengthens* it.

**The stream simplified, as predicted.** Before F1 a clocked lane presented
*pairs* of jobs 3 cycles apart — a two-level burst `BLane`'s uniform inner
spacing cannot express. After F1 every gap is `d` or `d + L_sync`, so the lane
is an ordinary periodic one at `d`. The fix removed a modelling problem as well
as a compliance one.

**`d` is a fixed point**, not a formula: `D_tol` depends on `d`, and the `r_i`
it must cover depends on a lane set containing the lane whose `T` is `d`.

| mode | t_LOW min | `d` feasible | `d` **shippable** | D_tol | SCL rate | ≤ mode max |
| --- | --- | --- | --- | --- | --- | --- |
| Fm+ 1 MHz | 25 | 29 | **33** | 8 | 725 kHz | yes |
| Fm 400 kHz | 65 | 69 | **73** | 8 | 336 kHz | yes |
| Sm 100 kHz | 235 | 239 | **249** | 14 | 100 kHz | yes |

⛔ **Every feasible margin is exactly 0, by construction** — the search returns
the first `d` where `d − t_LOW(min)` only just reaches `r − C`. A zero-margin
number is feasible and **not shippable**; the shippable column clears the
4-cycle margin bar *and* the mode's rate ceiling, whichever binds. For Sm the
**rate** binds (239 would be 104 kHz, over the ceiling); for Fm and Fm+ t_LOW
binds. All three sit inside `DLY_W = 10`.

⚠ **A symmetric clock cannot reach a mode's nominal maximum.** Fm+ tops out at
725 kHz and Fm at 336 kHz. That is legal — an I2C mode is a *maximum* rate — but
it is a throughput statement the clocked scheme owes, not a free win.

**Must-fire:** inheriting the fixed `D_tol = 15` gives a *different* feasible
`d` at all three modes (26/66/236 against 29/69/239), so the re-derivation
changes the answer rather than decorating it. The inherited tolerance does not
scale with `d`, so it understates a slow clock's real tolerance and overstates a
fast one's.

⚠ Not a shipped number yet: the other four rows in the set are still the shipped
two-action ones. If the clocked scheme replaces more than the I2C lane, this is
recomputed, not carried.

---

## 9. Ruling H — the SDA data hold, and a regression it nearly caused

**In scope, and the gate fails on it.** UM10204 Table 10 tabulates
`t_HD;DAT` min = 0 ns, but the table's own note requires a **device** to
internally provide ≥ 300 ns (15 cycles at 50 MHz), and this chip is the device
driving SDA. The hazard is concrete: SCL takes up to 300 ns (Fm) to fall through
a receiver's undefined region, so SDA moving in the same cycle we pull SCL low
reads as a START or a STOP. On a FRAM that aborts the transfer at best.

**Baseline, measured before anything changed:**

| | t_HD;DAT | transitions |
| --- | --- | --- |
| clocked lanes | **0** | 1719 / 696 / 296 |
| **certified two-action frame** | **0** | 266 |

H4 is therefore answered and it mattered: `build_i2cframe`'s
`OP_SHIFT(sda, lvl=0, clk=SCL)` "puts the data bit on SDA and takes SCL LOW in
one dispatch" — the clocked defect's shape on the *certified* path. sigrok
certified its **decode**, which says nothing about timing. The fix covers both.

### Mechanism (H2)

A per-lane hold pipeline: a dispatch that takes the clock low no longer writes
the data pin, it loads `l_hval`/`l_hoe`/`l_hcnt`, and the expiry writes the pin
`SDA_HOLD` cycles later at block level, every cycle, outside `case (st)`. The
hold becomes the **only** writer for that path, so there is no same-cycle race
and no second `always` block (a second writer of `pin_out` would be N_PINS
multiple-driver nets — the defect that made this engine unsynthesizable once
while simulating cleanly).

* **Cost: +30 flops, measured** off the netlist (3253 → 3283), matching 6 bits
  × 5 lanes. The pin index is *not* stored — `l_pin[i]` already holds it, and a
  held action cannot change it.
* **Expressed as a time, not a cycle count:** `SDA_HOLD_NS = 300` with
  `CLK_PERIOD_NS = 20`, the cycle count derived. `part1_param_contract` flagged
  a bare `15` in the RTL as a protocol constant — correctly — and the ns form
  is both the honest shape and portable to another clock rate.
* **Open-drain only, by scope:** the requirement is UM10204's, i.e. I2C. A
  push-pull SPI lane's setup/hold come from the part's SPI AC table, already the
  source of SPI-tx's `D_tol = 23`, and SPI changes data on a clock edge by
  design with no undefined region to bridge.
* **Dispatch timing untouched**, so A2's `C` and `J` are unaffected — and H5 is
  verified rather than asserted: the A2 fixed point is unchanged at
  **33 / 73 / 249**.

### Result

t_HD;DAT = **15** on every lane with a transition to measure, including the
certified frame, and unchanged under 200- and 4000-cycle stretches. Both H3
must-fires fire: `SDA_HOLD_NS=0` misses the floor on every measured lane,
`SDA_HOLD_NS=800` moves SDA while SCL is high and exceeds the Fm+ `t_VD;DAT`
budget. A requirement with a floor and no ceiling is half a requirement.

### The clamp, and the regression that forced it

⛔ **The fix nearly shipped a worse defect than the one it fixed.** A hold longer
than the action's low phase lands the data **after** the next rise — data
changing while SCL is high, which is a START or STOP to any receiver.

Measured: `corpus_i2c` runs at **d = 9**, below the 15-cycle hold. With the hold
applied unconditionally the stretching I2C peer went from **242 cycles of
SCL-low to 0** — it stopped decoding entirely, and two `fram_i2c` stretch
branches went dark. The only visible symptom was lost coverage in a file that
was never edited.

⚠ **And the first diagnosis was wrong.** I measured `PEER=i2c`, which never ACKs
on that image in either build, so the check looked exonerating. The stretching
instance `PEER=i2cs` is what showed the difference.

⇒ `ck_hold_fits`: if the action's delay cannot fit the hold, do not hold.
Stretch restored to 242; legal delays (33/60/120) still measure 15.

⭐ **It deliberately does not make such a program compliant.** A lane whose delay
cannot fit the hold keeps its old zero-hold behaviour and `gate_um10204` still
reports it below the requirement. The violation stays visible instead of being
converted into a harder one — which is also why the two dark branches were
**not** classified as justified-uncovered. That would have re-scoped a
regression into a pass.

### The minimum legal `d`, and what is still owed

`d > SDA_HOLD + t_SU;DAT(min)` — **18 / 20 / 28** cycles. Every mode-legal
program clears it (the t_LOW floors are 25/65/235), but a program can still ask
for a smaller delay and the engine will run it. **Whether silicon should refuse
`d ≤ SDA_HOLD` is owed a ruling**: the clamp bounds the damage, it does not
settle the question. It is the silent-corruption class — a well-formed frame of
the wrong data.

### What the coverage gate found in the new code

Not a formality — it reviewed the implementation:

* **Four dead coverage points were dead code.** Inside the hold arm `l_mode[cur]`
  is provably 0 (it appears in the condition that routes control there), so the
  `l_mode ? a : b` ternaries could only take one side. Removed at both sites.
* **The hold-taking path was never executed by the sweep.** Every clocked
  open-drain corpus image runs at d = 9, so the clamp routes them all to the
  direct path; `ckod` is the only image that reaches the hold, and it was not an
  arm. Added to `tb_trace` (33 arms / 14 benches) — it needs the pull-up bus
  model, which is why it cannot run in `tb_csat`.
* **Two points classified OWED, not waived**, each naming its witness: the
  expiry's `l_pin[i] < N_PINS` guard (needs a reserved data pin on a lane that
  is also open-drain, clocked and fitting), and the unclocked open-drain direct
  drive (needs `build_i2cframe(d=12)` — an illegal delay, which is exactly what
  makes it the right witness for the clamp's fallback).
* ⚠ **And a mistake of mine:** those entries were first added with no
  `ANCHOR_TEXT`, so `reanchor.py` could not move them when the hold's own edits
  shifted the file, and the gate failed on a classification that had slid off its
  line. The gate already demanded it; I had not met it.

Uncovered: 24 → 33 → **26**, all classified. 20 of 20 gates pass.

## 10. Ruling T — symmetric clock throughput

Accepted: Fm+ 725 kHz, Fm 336 kHz, Sm 100 kHz, all legal since an I2C mode is a
*maximum* rate.

**Named reach item, not built:** Fm's minimum high phase is 30 cycles against a
minimum low of 65, so a high phase of `d/2` — a wire shift, zero flops — would
roughly reach Fm nominal. It is not valid for Sm, which needs a near-symmetric
clock and already runs at 100 kHz. It needs a selector bit (header or global),
so it waits on an encoding decision.

---

## 11. A1 / A2 — teeth for what was accepted

### A1 — head-slot stability across a clocked park

F1's rebase reads the parked lane's delay out of `l_act[hix[gi]]`, and that costs
**zero flops** only because a held clocked action does not invalidate its slot.
The whole saving rests on an *emptiness* — on an `ST_WB` arm that does nothing —
and an emptiness cannot be read as deliberate. So the action word is snapshotted
when a clocked action begins and compared on every re-dispatch: **884 / 1229
re-dispatches stable**.

⚠ **It false-fired on the clean build first.** The snapshot sat after the
if/else, so at the *retiring* dispatch it cleared `ca_have` and immediately
re-took the snapshot with the outgoing action's word — and the next action
compared itself against its predecessor. A check that fires on a correct design
is worse than no check: it trains the reader to ignore it.

⛔ **The must-fire took three attempts, and the failures are the result.**

| mutant | fires A1? | why |
| --- | --- | --- |
| `M_CK_HOLD_INVAL` (invalidate on hold) | **no** | the PC does not advance during a hold, so the prefetch re-reads the same address and restores an *identical* word |
| advance the PC on hold | **no** | the slot stays **valid**, so no refill happens and nothing is re-read |
| `M_CK_HOLD_RETIRES` (both) | **yes** | slot goes free *and* the PC moves, so the refill brings the next action's word |

`M_CK_HOLD_INVAL` is kept as its own arm with that recorded. It is not harmless —
it costs a refill per **dispatch** instead of per **action**, which is exactly
the port demand Amendment A1 says a re-dispatch does not owe, and it moved
re-dispatch counts 1229 → 1061 on `corpus_i2c`. It is a `D*` defect, not a
delay-corruption one. ⭐ A mutant that does not fire is a statement about the
design, not a failed attempt to be deleted — and a must-fire has to be built
against the **mechanism**, not against the name of the invariant.

### A2 — the upper bound, measured from the observed rise

`gap ≤ d + L_SYNC + 1 + (r_i − C)` = **d + 8**, derived first and then confirmed:
the measured post-rise lateness tops out at **4..6** against the budget of 8.
`M_CK_REBASE_2D` fires it (306/306 and 552/552) while `t_HIGH ≥ d`, G1's lower
bound and the UM10204 hold floor all stay green — which is the whole argument
for bounding both sides.

⚠ **The first version measured from the HIGH dispatch and was wrong**: that gap
*contains* the peer's stretch, so a 200-cycle hold inflates it legitimately. It
fired 684 times across the sweep on arms that were behaving correctly, three of
which exist precisely to stretch the clock. F1 counts the high period from the
rise it *sees*, so the bound starts there too and the stretch is excluded by
construction rather than by a term that would have to guess at it.

**The constant lives in the bench; `gate_clocked_lane_a2.py` parses and
adjudicates it** rather than holding a second copy. That cross-check caught an
error on its first run: it took `max(r_i − C)` over the whole lane set (**13**,
from UART-tx) when the bound is on the *clocked lane's own* lateness (**4**). A
term from another lane would have been loose by 9 cycles and the bound would
have stopped catching anything. The measurement settled it — 8 = 3 + 1 + 4
exactly.

### ⛔⛔ The same category error, three times in one arc

Written down because once is a slip and three times is a habit:

1. A **d = 25** lane failed for missing **Sm's** 250 ns setup — a requirement
   that only applies at 100 kHz.
2. The budget cross-check took **`max(r_i − C)` over every lane** when the bound
   is on one lane's own lateness.
3. The shipped set's `r_i − C = 4` was checked against **`corpus_all5`**, a
   five-lane stress image whose own post-rise lateness measures **19**.

Each is the same shape: a bound derived for one configuration applied to
another, which reads as a design violation when it is a mismatched comparison.

⇒ **Only the verdict is scoped, never the measurement.** `+A2BOUND=1` enforces
the bound on the one arm whose lane set A2 models; every other arm still
measures and reports its widest post-rise lateness, so `corpus_all5`'s 19 stays
in the log instead of being scoped out of existence. ⚠ If that lane set ever
becomes something we ship, A2's `r_i − C` needs re-deriving for it and the bound
with it.

### Harness friction, observed not fixed

Every RTL edit in this arc shifted the coverage gate's line anchors, and
`reanchor.py` ran five times (11 / 6 / 13 anchors, by measured shift). The tool
behaves correctly — it refuses on ambiguity rather than guessing — but the loop
is *edit RTL → suite red on anchors → reanchor → re-run the ten-minute suite*,
and two full suite runs went to nothing but anchor arithmetic. Keying the table
on anchor **text** with the line as a hint, rather than the reverse, would
absorb the shift. Recorded as an observation about the harness; not changed.

---

## 12. Ruling P — the push-pull clock-low growth, explained

**P2(b): a bench artifact, with the trace.** `project.v:686` overrides the pad:

```verilog
uio_oe_run = (uio_oe_eng & ~(1<<MISO_PIN)) | (miso_oe_q << MISO_PIN)
```

With `MISO_PIN = 7`, `CS_PIN = 6`, and `build_ckfive` putting lane 3 on
**pin 6 / clkpin 7** — colliding with both — the chain is: the hold delays that
lane's **data** pin (6), pin 6 *is* the SPI target's **chip select**, the delayed
CS edge moves when the target drives MISO, `miso_oe_q` moves, and `uio_oe[7]`
follows by exactly the hold's 15 cycles.

**The hold never touched a clock pin.** Pin 7 is not that lane's clock at the pad.

Three falsifiers, each killing a candidate rather than confirming a story:

| test | result | kills |
| --- | --- | --- |
| rand-reset +0 vs +2 | identical | an initialisation artifact |
| per-dispatch stream diff | **byte-identical, 3571 records** | any scheduling effect |
| pins the hold expiry writes | **0, 2, 4, 6 — never 7** | a hold → clock path |

**P3 n/a**: it cannot occur on an open-drain lane via the hold, because it is not
a hold path — it is a pad override of one pin, and no pin-map-legal program may
place a lane on 6 or 7. `build_ckfive` is allowed the collision only because it
declares itself not pin-map-legal; the MEASUREMENT was not allowed to believe it.

⇒ `M_SDA_HOLD_ALL` removed (the effect is explained, not priced). **The
open-drain hold scoping stands on UM10204 alone**, which is where it belonged; it
was never load-bearing for this effect.

### P4 — the original control arm stands

| lane | pin/clk | status | modal t_HIGH vs d |
| --- | --- | --- | --- |
| 0 | 0/1 | legal + measurable | **25 = 25** ← the original F4 control |
| 1 | 2/3 | legal + measurable | 45 = 45 |
| 2 | 4/5 | legal + measurable | 123 vs 120 (+3, **unexplained**) |
| 3 | 6/7 | pad-overridden | 434 — meaningless |
| 4 | 8/9 | outside uio (`uo_out`) | unmeasurable |

The first F4 control reported `ckfive lane 0, pin=0 clkpin=1, modal t_HIGH = 25
against programmed 25`. That lane collides with nothing. **So the control did run
on a legal lane and the record does not change**; the 428/421 correction applies
only to lane 3, which was a later extra row in the gate's table and never the
control claim. F1 keeps all three legs: the 13× scaling falsifier, the
fix/mutant split (13/29/64/125 vs 5/5/5/6), and a control on a legal lane.

⚠ **OPEN:** lane 2 reads modal 123 against d = 120 — about `+L_SYNC` on a
push-pull lane that does not park, while lanes 0 and 1 are exact. Not explained.

### Corrections recorded

* `428/421` for ckfive lane 3 was the **SPI target's output**, not a clock.
* `gate_um10204`'s control arm now **skips pad-overridden lanes** with the reason
  printed, and `MISO_PIN`/`CS_PIN` are asserted against `project.v` at run time.
* ⛔ **That drift check could not fire when first written.** `measure_phases.py`
  did not import `io`, so `io.open` raised `NameError` into a bare `except` that
  returned `None` every call — a deliberately wrong `MISO_PIN` went unreported.
  Fixed and priced: `[]` on the real tree, `['MISO_PIN']` when wrong. The shape
  appeared inside the very function written to prevent a silent disagreement,
  and it is the **third check-that-could-not-fire this session** after the
  sweep's grep and the backspace regex — which is what Ruling E now gates.

---

## 13. Ruling D — `d <= SDA_HOLD` is refused, in silicon and in the assembler

The hold (§9) only satisfies `t_HD;DAT` if the bit period is **longer** than the
hold. Below that, the held value lands after the next rise — data moving while
SCL is high, which to any receiver is a START or a STOP. §9 shipped a *clamp*
that detected this and fell back to the zero hold: correct as far as it went,
but it left the program **running and non-compliant**. The ruling replaces the
clamp with a refusal.

### D1 — silicon

`ck_holdviol = ck_act & ~l_mode[cur] & (SDA_HOLD != 0) & (a_dly <= SDA_HOLD)`,
joined with `ck_degen` into one `ck_refuse` wire used at the **head** of every
chain that dispatches a clocked action. `config_err` is set, the lane's
`l_live` is cleared, and `ST_IDLE`'s existing `!config_err` term makes the halt
**engine-wide**. **+0 flops** — the comparison is combinational on a word
already in a register.

* **One wire, three sites**, because this exact mistake has been made twice: a
  guard bolted to a *branch* let a refused clocked SHIFT fall through into the
  unclocked body and **drive the data pin on its way to being refused**, and
  the retire chain had the same shape. A guard belongs at a chain's head.
* **`<=`, not `<`.** At `d == SDA_HOLD` the data reaches the pin on the same
  cycle the next phase dispatches, so `t_SU;DAT` is **zero**. The hold fits and
  the program is still illegal.
* **Open-drain only**, for the reason the park is: a push-pull clocked lane is
  SPI, where `t_HD;DAT` is the master's own choice.
* **`SDA_HOLD == 0` refuses nothing**, or `test/phases_run.sh`'s `hold0` arm —
  which exists to *measure* the original defect — would have no traffic to
  measure.

**Measured:** `corpus_i2c` at `d = 9` produces **0 SCL transitions in 60,000
cycles** (against 2,667 at `d = 16`) and exactly **one** SDA transition — the
`OP_START` that precedes the refused SHIFT. The status stream keeps shifting on
`uo_out[4..6]` while the engine is halted, which is the host learning *why*.

### D2 — assembler, the static half

`pe_asm.check_clocked_hold_delay` refuses the same programs statically, naming
the lane, the opcode and the floor. The boundary is **read from the RTL**
(`model/hold_bound.py`), never typed: a second copy of `15` would keep
accepting programs silicon refuses after the hold moved, and the toolchain
would be telling people their program is fine.

⚠ **This is the static half and it says so.** The full ruling refuses below the
**per-program** floor `d >= t_LOW(min, mode) + (r_i − C)`, which needs **S**.
`SDA_HOLD` is a hard floor for every program and every mode, so it lands now;
the mode floor is strictly tighter and lands with S. A program this check
accepts is **hold-legal, not yet certified mode-legal**, and the report says so.

### D3 — the clamp, removed where it became unreachable

Removed from the **clocked** site. **Kept at the unclocked site**, and that is
scope rather than oversight: D1 is scoped to `ck_act`, so an *unclocked*
open-drain SHIFT that takes its own clock low in the same dispatch
(`clk_real & ~a_lvl`) can still ask for a short delay — `build_i2cframe(d=12)`
is exactly that program, and it is the shape of the **certified** frame.
Removing the clamp there would push data past the rise for a program silicon
still accepts.

⇒ **Owed, and it is a scope decision rather than mine to take:** extending the
refusal to the unclocked idiom would retire the clamp entirely.

### D4 — the boundary, from both sides

Three images, one point each, built from `hold_bound.bound()` plus an offset so
the boundary is stated once:

| image | `d` | expected | where |
| --- | --- | --- | --- |
| `ckhold_under_image.hex` | `SDA_HOLD − 1` | refused | `tb_pinrange +MODE=4` |
| `ckhold_at_image.hex` | `SDA_HOLD` | refused | `tb_pinrange +MODE=4` |
| `ckhold_over_image.hex` | `SDA_HOLD + 1` | **runs** | `tb_trace +CKRUNS=1` |

* Each is **legal in every other field** (real distinct clock pin, both pins
  inside `uio`, count 7, fillers on `PIN_NONE`), so the delay is the only thing
  that can refuse it — enforced by D6 rather than asserted in a docstring.
* **The positive arm is in `tb_trace`, not `tb_pinrange`, and that is a
  measured constraint.** An open-drain clocked lane parks on an *observed*
  rise; `tb_pinrange` holds `uio_in` at a constant `8'hFF`, so a released SCL
  reads high and never **transitions** — the lane would park until the
  stretch-fault bound halted it and the arm would measure a hang.
* **"It runs" is asserted on retired clocked actions**, never on an absent
  flag: `config_err == 0` is also true of an engine that never started.
  Measured: `tb_trace[D4]: ok — 131 clocked action(s) retired`.
* Without the `over` arm, a refusal that was too **wide** — rejecting every
  clocked open-drain program — would pass every other arm in this ruling.

### D5 — the corpus, raised to a mode-legal delay

Both clocked corpus programs ran at `d = 9`, which D1 now refuses, so they had
to move. **`d = 70`**, derived and then corrected by measurement:

* The corpus I2C lane is named **"I2C 400 kHz"** in `corpus.py`'s ruled pin map
  — it is the shipped lane set's Fm row — so its floor is Fm's, not Fm+'s. A
  program running at 694 kHz under a 400 kHz label is the mislabel class this
  project refuses elsewhere.
* Fm needs `t_LOW >= 1300 ns` = 65 cycles, so **65 is the arithmetic floor**.
  At `d = 65` the *observed* floor came out **63** on `corpus_i2c` and **64** on
  `corpus_all5` — two cycles short, EDF service jitter eating into the low
  phase, the C2 finding in a second place. At `d = 70`: `t_LOW` **68** = 1360 ns,
  `t_HIGH` 74 = 1480 against 600, `t_SU;DAT` 53 against 5, bit period 146
  cycles = **342 kHz**, inside the ceiling. The 5 cycles over the arithmetic
  floor are measured jitter, not padding.
* **`corpus_all5` raises lane 0 only.** It is the only lane that is both clocked
  and open-drain — lane 1 names `PIN_NONE` as its clock, lane 2 is push-pull,
  lanes 3 and 4 run LEVEL/ARM/READBIT. The other four stay at 9..13 because the
  image's job is **scheduler contention**, and raising all five would cut the
  dispatch rate ~7× and quietly turn a stress image into a relaxed one. The
  resulting 70-against-9..13 mix is a harder EDF spread than the arithmetic
  progression it replaces.

**Cost, reported rather than absorbed:**

| | `d = 9` | `d = 70` |
| --- | --- | --- |
| bit period | 24 cycles | 146 cycles (6.1×) |
| complete periods per 60,000 cycles (`corpus_i2c`) | — (refused) | 327 |
| the same at `d = 16`, for scale | 1,332 | — |

`+NCYC` is fixed per arm, so **simulated time did not grow**; what shrank is
protocol work per cycle, ~6× fewer I2C transactions in the same budget.

**Coverage: 26 uncovered before, 26 after, and the same 26 points.** Not just
the count — `test/gate_coverage.py`'s diff is **27 line-number moves and
nothing else**, and the gate reds both on an uncovered point with no entry and
on an entry whose point is no longer uncovered. So no point was traded for
another.

That took one deliberate addition. D3's removal left **one** branch reachable
only at `SDA_HOLD == 0` — the open-drain side of the clocked direct-drive arm,
since every clocked open-drain action now routes to the hold path. The sweep
duly reported it as the one new uncovered point (27 against 26).

⇒ **The parameter point was built rather than waived.** A written reason would
have said "unreachable at the default", which is true and is *not* the same as
unreachable. `tb_trace ckod_hold0` (`-GSDA_HOLD_NS=0`) joins the sweep, the
same shape as `tb_smoke`'s `spl1` arm — and it is a build we already ship a
*measurement* arm for, so it was being simulated and simply never swept.

### D6 — one image, one refusal

`gate_degenerate_fields.DELIBERATE` now names **one refusal class** per refusal
image and reds if the image trips a second. The reason is mechanical:
`config_err` halts dispatch engine-wide, so whichever refusal fires **first** is
the only one that ever runs — an arm certifying refusal A would be passing on
refusal B. Five classes are decoded: `ck_degen`, `pin_real`, 1.6x, 1.6s and D1.

Two findings came out of writing it:

* **`cfgerr_image.hex` was undeclared** — the 1.6s refusal image, run by
  `tb_pinrange +MODE=0` and by cocotb before that, for the whole life of the
  gate. Not an oversight in the list: until D6 added the 1.6s predicate,
  `violations()` **could not decode** the refusal the image exists to exercise,
  so it tripped nothing and the gate had nothing to ask about. An audit can
  only miss what it cannot decode.
* **The gate's own selftest ran every probe at `d = 9`** with mode 0 and a real
  clock pin. Under D1 all five would trip the hold refusal — including the
  three asserting *no* refusal, which would have gone red, and the two
  asserting one, which would have passed **for the wrong reason**. The probes
  moved to `hold + 1`, and the comparison moved from `bool(v)` to the refusal
  **class**, which is the distinction D6 exists to make.

Current state: 32 images, 8 declared deliberate, **0 undeclared, 0 tripping
more than one refusal**.

### P5 — `build_ckfive`'s pin-map collisions, named

`test/corpus.PAD_COLLISION` declares, by image, the **lanes** that collide with
`project.v`'s pad override
(`uio_oe_run = (uio_oe_eng & ~(1 << MISO_PIN)) | (miso_oe_q << MISO_PIN)`).
Undeclared collision is red; a declaration whose image no longer collides is
red too.

| image | lanes | why |
| --- | --- | --- |
| `ckfive_image.hex` | 3 | consecutive pin pairs put it on 6/7; its **clock** is pin 7, whose OE the SPI-target release path overwrites. Measured modal `t_HIGH` 434 against a programmed 120. |
| `ckod_image.hex` | 3 | same layout, so the `d = 240` lane lands there too. `gate_um10204` already skips it **by name**. |

Those are the only two. The predicate is the same one `measure_phases` uses to
mark a lane `pad_overridden`, and both read the pin numbers from `project.v`.

⚠ **Scoped to lanes that can drive**, and the scope was forced by measurement:
the first version flagged five images whose only offender was a parked
`OP_REARM`-only filler lane sitting on pin 6. Declaring those would have been
five vacuous entries burying the two real ones. It also sent `build_ckhold`'s
fillers to `PIN_NONE` — a must-fire image should not rest on a don't-care
staying one.

### Findings that came out of ruling D

**⛔ The clocked `OP_SHIFTIN`'s SDA release is not held.** `t_HD;DAT` on
`corpus_i2c` histograms as `{0: 20, 15: 93, 280: 35, 282: 1}` — 93 correctly
held data bits and **20 transitions with zero hold**. Attributed by a falsifier
set rather than a story, because the certified frame contains START and STOP and
measures 15:

| variant | zero-hold samples |
| --- | --- |
| full sequence | 20 |
| drop `OP_READBIT` | 21 |
| drop `OP_START`/`OP_STOP` | 23 |
| **SHIFT only** (drop the clocked `OP_SHIFTIN`) | **0** — all 140 at 15 |

The clocked SHIFTIN releases SDA unconditionally on its first (LOW) dispatch,
so the transition **from the last transmitted data bit into the ACK slot**
carries no hold. A master must hold its last data bit past the fall before
releasing for the ACK, so this is a real `t_HD;DAT` violation — the same class
§9 fixed, in a place §9 did not reach.

⇒ **The whole ruling-H measurement set is blind to it.** `build_ckod` is
**SHIFT-only**, and `i2cframe` escapes it because its SCL fall and its SDA
release are *different dispatches*, `d` apart. So §4b(a)'s green is sound for
the transmit path and says nothing about the receive handover. This is ACK item
(a)'s own question — Wilson asked it be *confirmed*; the answer is **no**, so it
becomes a fix.

**⛔ `holdbig` stopped being able to fire, because the chip got stricter.** The
hold-ceiling must-fire ran at `-GSDA_HOLD_NS=800` = 40 cycles, and `ckod`'s
smallest delay is 33 — so under D1 the program is **refused**, the engine halts,
and the arm that was demonstrating the ceiling violation produces no traffic.
It read as `0 lane(s) moved SDA while SCL high, 0 over the budget`: a must-fire
failing in the one direction that is not a design regression.

* Fixed at **500 ns = 25 cycles**, which must sit strictly between the Fm+
  `t_VD;DAT − t_r` budget (17) and the image's smallest delay (33). Now fires on
  **3 lanes**.
* The gate was printing a **literal** `SDA_HOLD=40` while the script decided the
  real value. Each arm's `SDA_HOLD_NS` now travels **in its own JSON**
  (`measure_phases --hold-ns`), and the gate reports the boundary it actually
  measured. A run condition that lives only in the launching script cannot be
  checked against the data it produced.
* The gate also now names **vacuity separately from failure**, because the fix
  differs: "no lane measured anything" means choose a different hold, not that
  the design regressed.

**⛔ `benchset`'s plusarg scanner could not see a name containing a digit.** Its
pattern was `[A-Z_]+`, so `+A2BOUND` was invisible — read by **thirteen**
benches and supplied by one arm, for a whole arc, with this check silent.
`+CKRUNS` was caught in one run. Widening the pattern turned up twelve benches
running on an undeclared default.

* ⇒ `SHARED_INCLUDE_DEFAULTS` declares a shared include's plusarg **default
  once**, with its reason, instead of repeating `+A2BOUND=0` on 36 arms — and
  the excuse is **scoped to benches that actually include the file**, so a bench
  reading the name in its own body still has to supply it.
* Priced in both directions, plus the digit case, in the gate's own must-fires.
* **Fourth check-that-could-not-fire in this arc**, after the sweep's grep, the
  backspace regex and the swallowed `NameError`. Ruling E's ledger.

### Not claimed

* **`gate_corpus_trace.py` cannot build**, and has not been able to since
  `7a672b0`: `final procedures cannot enable/call tasks` on `progress.vh:214`
  and `clocked_conform.vh:382` under iverilog. It is the **two-simulator**
  corpus comparison and the thing that turns `corpus.py`'s `must move`
  preconditions from claims into checks. It is not in `ci/run_gates.sh`, so the
  suite is green without it. ⇒ **The corpus at `d = 70` was certified by the
  Verilator sweep (3 rand-reset modes, no `*** FAIL`), by the loader audit and
  by `measure_phases` — NOT by the iverilog cross-check.** Pre-existing, outside
  this ruling, and owed.
* **`t_HD;DAT` on the corpus programs is not adjudicated by §4b(a)**, because
  their zero-hold samples come from the clocked SHIFTIN release above. Until
  that is fixed, a `min >= 15` verdict on those arms would be a verdict about
  the wrong transition.

---

## 14. Ruling R — the port premise, which nothing checked

`M_CK_HOLD_INVAL` — **one line**, invalidating a clocked lane's head slot on
every *held* dispatch — **survived every gate in this repo for an entire arc**,
while the suite read 20 of 20.

| layer | why it cannot see the mutant |
| --- | --- |
| A1 (head-slot word) | the PC does **not** advance during a hold, so the prefetch re-reads the **same address** and restores an **identical word**. Every delay the zero-flop rebase reads is still correct. |
| B (dispatch counts) | a refill changes no dispatch count. |
| coverage sweep | the lines it touches are covered either way. |

What it breaks is **Amendment A1's port premise**: a refill per *dispatch*
instead of per *action*. `D* = N_LANES × L_REFILL` and every port-feasible cell
in Theorem 3 are computed **from** that premise, so under the mutant the
schedule the whole A2 argument quotes is for a different machine. Re-dispatch
counts moved 1229 → 1061 on `corpus_i2c`.

⇒ **That is the finding.** Not that a mutant survived — that the premise a
published bound rests on was unchecked, and the only reason it looked fine is
that no layer was measuring it.

### The observable

One refill is one cycle in `pst == P_CAP` with `pl` naming the lane — where
`l_act[fix]` is written and `l_actv[fix]` set. Counted **per lane**, over the
window Layer B already delimits (the dispatch that starts an action to the one
that starts the next), and attributed to the action that just **ended** via
`cb_ck` — the off-by-one that would otherwise charge a clocked action's refills
to its unclocked successor.

A single shared counter would have made every multi-lane arm look like a
violation, since a refill for lane 2 says nothing about lane 0's action.

### The bound is `SPL`, derived — and the first version was wrong

Inside one action's window a lane can take **at most one fill per slot**:

* one **head** refill — the one the *previous* action's retire triggered,
  landing just inside this window; and
* one **spare** fill, because `want_fetch` fills the spare when empty and it
  then stays valid until the head retires and the swap consumes it.

⇒ `SPL` slots, one fill each. `clocked_conform.vh` reads **`dut.u_eng.SPL`**, so
the bound follows the design and becomes 1 automatically on an `SPL = 1` build.

⛔ **The first bound was `1`, measured on too narrow an image set, and it is
recorded rather than quietly bumped.** `ckod` (184 actions) and `corpus_i2c`
(72) each have exactly **one** live clocked lane and both measure 1. I set the
constant from those two. `corpus_all5` has **five** live lanes and measures
**2** — under contention the speculative spare fill really does land inside a
clocked action's window.

⚠ That is the **same category error** as three already in this session's
ledger: a bound measured on the shipped single-lane case and applied to the
5-lane stress image. Deriving it from the buffer depth explains *both* numbers
instead of accommodating one.

### Measured

| arm | image | retired actions | worst refills | bound |
| --- | --- | --- | --- | --- |
| clean | `ckod` | 184 | 1 | 2 |
| clean | `corpus_i2c` | 72 | 1 | 2 |
| clean | `corpus_all5` | 376 | **2** | 2 |
| `M_CK_HOLD_INVAL` | `ckod` | 184 | **16** | 2 |
| `M_CK_HOLD_INVAL` | `corpus_i2c` | 108 | **16** | 2 |
| `M_CK_HOLD_INVAL` | `corpus_all5` | 408 | **17** | 2 |

632 retired clocked actions across the clean arms. The mutant costs a refill
per dispatch, and a clocked byte is 16 dispatches — `gate_port_demand` requires
a worst of **≥ 8** so a mutant that barely took effect cannot pass as a kill.

Also checked on arms `refill_run.sh` does *not* measure, across all three
rand-reset modes: `ckfive` (five push-pull clocked lanes) 310 actions worst 1;
`ckhold_over` 196 worst 1; `corpus_all5` 2 in every mode. ⚠ **`corpus_all5`
touches the bound exactly**, so there is no slack — anything that adds a refill
to a clocked window goes red, and that is a request to re-derive `D*`, never a
licence to raise the constant.

### Enforced, not gated

`+RBOUND` defaults to **`dut.u_eng.SPL`** and is **on**. A2's bound defaults to
*off* because a lighter lane set's bound on a heavier program is unsound
(ruling S) — R's is a per-action structural property of the buffer depth, so
the same reasoning does not apply. A layer defaulting to report-only would have
rebuilt the hole it closes. `+RBOUND` exists only to **raise** it, and no
shipped arm passes it.

Declared once in `benchset.SHARED_INCLUDE_DEFAULTS` — the mechanism built for
`+A2BOUND` after the scanner's digit blind spot — because
`clocked_conform.vh` is included by thirteen benches.

### Why it is a script plus a gate

`M_CK_HOLD_INVAL` is a `define`, and `benchset`'s arms carry plusargs and `-G`
*parameters*; there is no define channel, and adding one to the coverage sweep
would rebuild every bench for a mutation one layer reads. `test/refill_run.sh`
+ `model/gate_port_demand.py` follows the shape the clocked measurement already
has (`phases_run.sh` + `gate_um10204`), and the gate is **RED without the
measurement** rather than skipping — the strictest case of that rule in the
file, since this is the premise that went unchecked while the suite was green.

### What ruling R does NOT check

* **It bounds refills per action, not `D*` itself.** `D*` is a
  port-feasibility statement over a whole lane *set*; this layer checks the
  per-action premise `D*` is computed from. A design respecting this bound that
  still oversubscribed the port would pass here and fail
  `gate_admissibility_1_6`.
* **The spare fill is charged to whichever action is running**, so the bound is
  per-*slot* rather than per-*cause*. A per-cause split needs the prefetch's own
  reason exported — flops for a bound that already holds.

### Answer to Q2 — `gate_corpus_trace`

**It is not in the gate list, and nothing runs it.** `ci/run_gates.sh`'s
`GATES` array does not contain it, and no `.sh` or `.yml` in the repo invokes
it. So 20 of 20 never included it — the suite was not passing *over* a broken
gate, it was never asking.

**It is also not fail-open**, contrary to the hypothesis: on an iverilog build
failure it prints `*** iverilog build FAILED` and `return 1`, and the real exit
code is **1**. ⛔ My earlier report of `RC=0` was my own measurement error — I
read `$?` after a pipe into `tail`, so I got `tail`'s status, not python's. That
is the **vacuous `$?`** mistake from earlier in this session, made a second
time, in the same session, while checking something else.

⇒ So the defect is a different and arguably worse one: **a gate that correctly
reports RED and that nobody ever runs.** A fifth instance of the class — not a
check that cannot fire, but a check nothing listens to. Fixing it means adding
it to the list (which goes red immediately) *and* repairing the iverilog build
(`final procedures cannot enable/call tasks`, `progress.vh:214` and
`clocked_conform.vh:382`). Ordered after S.


---

## 15. R4 / R5 — checking the premise, not a paraphrase of it

Ruling R landed a layer that checks **refills per retired clocked action ≤ SPL**.
That kills `M_CK_HOLD_INVAL` and is worth having, but it is **not the sentence
`docs/J_LANE_PROOF.md` reasons from**. R4 and R5 close that gap.

### R4 — the two premises, verbatim

| # | sentence, as the proof states it | what the bench counts |
| --- | --- | --- |
| **P10** (amended 2026-10-05, A1) | "a dispatch consumes a valid head and leaves **at most one** slot per lane to be refilled" | slots this dispatch **invalidated** |
| **P1** | "One prefetch FSM, one refill in flight engine-wide. A single `pst`/`pl` pair; there is no per-lane fetch engine." | refills in flight, and slots filled **per episode** |

⭐ **R4a counts what the dispatch LEAVES, not what the prefetch later does.**
"Leaves to be refilled" is a property of the dispatch; measuring the prefetch's
subsequent activity would measure the consequence instead of the premise.

⭐ **R4b has two halves**, because P1 does: at most one refill in flight, *and*
each episode fills **exactly one** slot. An episode satisfying two slots would
be a second fetch engine hiding inside one FSM — the thing P1 asserts does not
exist. ⚠ The in-flight counter **cannot exceed 1 with one `pst` register**, so
that half is a *regression guard* against adding a second server rather than a
check that can fail on the shipped design. Declared as such, not presented as
priced.

⚠ **One cycle late, by construction.** `l_actv` is written by a non-blocking
assignment, so a bench `always @(posedge clk)` reads its pre-edge value. Each
edge is compared against the previous edge's sample and attributed to the
previous cycle's dispatch. Reading after the edge would race the DUT's own NBA
ordering — the hazard this bench family already hit once on `pin_out`.

**The wording is compared, not trusted.** `gate_port_demand.check_premise_text()`
reads `J_LANE_PROOF.md` and fails if either sentence no longer appears
verbatim, so a reworded premise is a deliberate act that updates both places.
Priced in §6 of the gate: a sentence the doc does not contain is reported.

⚠ **The Lean formalisation has not started.** When it does, its premise is
copied from this same sentence — one wording in three places rather than three
paraphrases.

### The three-way separation, measured

| arm | R4 (premise) | R5 non-retiring | Layer R (rate) |
| --- | --- | --- | --- |
| clean | **ok** — worst 1 slot, 1 in flight | **0** | **ok** — 1 / 1 / 2 |
| `M_CK_HOLD_INVAL` | **ok** | **2820 / 586 / 5260** | **red** — 16 / 16 / 17 |
| `M_PFETCH_BOTH_INVAL` | **red** | 0 | **ok** — 2 / 2 / 2 |

⇒ **Neither layer is redundant, and that is now a measurement.**
`M_CK_HOLD_INVAL` raises the refill *rate* while still leaving exactly one slot
per dispatch — **so P10 holds under it** — and `M_PFETCH_BOTH_INVAL` keeps the
rate while breaking the per-dispatch premise. Each mutant is caught by exactly
the layer whose sentence it violates.

⛔ **A correction inside this work:** the first version added R5's non-retiring
count to R4's failure tally, so `M_CK_HOLD_INVAL` reported an "R4 premise
violation" when P10 actually holds under it. One counter shared between two
claims makes every verdict mean "one of these two things" — the opposite of
what R4 was ordered for. Split.

### R5 — are the refill-bearing dispatches the ones §1 assumes?

`gate_dmin_clocked` (§1) computes `d_min` over **refill-bearing** dispatches as
if those are the action-**begin** ones, spaced ≥ 2d. Layer R had measured a
second refill landing inside a clocked window on `corpus_all5`, so the question
was whether some *other* dispatch is refill-bearing.

**Answer: case (a).** **Zero non-retiring refill-bearing dispatches** on every
clean arm — `corpus_i2c`, `corpus_all5`, `corpus_spim`, `corpus_sptgt`, `ckod`,
`ckfive`, `ckhold_over`. Every refill is owed by a **retiring** dispatch, which
is exactly the set §1's closed form covers. **§1 stands, unchanged.** The
`corpus_all5` second refill is a *speculative spare fill*, which Theorem 3's own
note already counts as "the one unit of work this argument counts per lane per
period".

⛔ **A correction to my own first predicate.** It used `cb_n[lane] > 1`
("any dispatch after the first") and fired 310 times on `ckfive` — because
dispatch 16 of an 8-bit clocked SHIFT **is** the retiring one (2n = 16). The
engine's own `act_retire` is the predicate; Amendment A1 is phrased about
*retiring*, not about position.

### The spacing, and the comparison that would have been wrong

| program | per-lane min gap | port-wide min | `port_feasible` | `J` |
| --- | --- | --- | --- | --- |
| `corpus_i2c` (d = 70) | **69** | 69 | yes | 1 |
| `ckod` (d = 33…240) | **37** | 3 | yes | 1 |
| `ckfive` (d = 25…) | **23** | 3 | yes | 1 |
| `ckhold_over` (d = 16) | **20** | 20 | yes | 1 |
| `corpus_spim` (d = 7) | 5 | 5 | **no** | 8 |
| `corpus_sptgt` (d = 6) | 3 | 3 | **no** | 8 |
| `corpus_all5` (lanes at d = 9…13) | 3 | 3 | **no** | 8 |

⛔ **`D*` is a RATE bound, not a minimum separation** — "in any window of `d`
cycles the port is asked for at most `k` refills". Five lanes at `d ≈ 9…13`
legitimately put refill-bearing dispatches **3 cycles apart** on the port; that
is the demand `D*` is sized *for*. Reporting the port-wide minimum against
`D* = 20` would have manufactured a failure on every multi-lane program, so the
gate prints both numbers and asserts neither against `D*`.

⇒ **The measured per-lane minimum tracks admissibility exactly.** Every program
`gate_j_program.port_feasible` admits clears `D* = 20`; the three that do not
are the coverage and stress images, which run below `D*` **on purpose** and
claim `J = 8`, not `J = 1`. A spacing under `D*` is a statement about that
program's `J`, not a design failure.

**The FRAM programs, explicitly** (Wilson asked either way): §1's FRAM write
and random read have `d_min` **81** and **50**, both far above `D* = 20`, each
with one clocked lane. `corpus_spim` at `d = 7` is a *trace* image for the SPI
path, not the shipped FRAM configuration — the shipped SPI lane is 1 MHz = 25
cycles. So no FRAM program is affected either way.

### Also not claimed

* **`worst dispatch-to-next-fill` is an upper bound, not a latency.** A fill may
  target the lane's *other* slot, so the number is "cycles to the next fill for
  that lane", not "cycles to fill the slot this dispatch freed". Reported as a
  bound and labelled one. ⚠ Its first version was worse: `p5_owe` was never
  cleared, so a speculative fill was charged against a long-retired dispatch and
  reported 6,940 cycles — a number with no referent.
* Theorem 3's **conclusion** (no lane ever winner-blocked, `RQ = 0`) is not what
  these layers check. They check its premises; the stall counters check the
  conclusion.


---

## 16. Ruling S — A2's bound belongs to (program, lane)

### The defect, in its original form

`clocked_conform.vh` bounded every clocked lane's post-HIGH release at
`d + CK_GAP_SLACK`, with `CK_GAP_SLACK = 8 = L_SYNC + 1 + (r_i − C)`. That
`r_i` came from `gate_clocked_lane_a2.build()` — the **A2 model's shipped lane
set** (UART-tx, SPI-tx, UART-rx, SPI-rx, one clocked I2C lane). The bound was
then **enforced on `ckod`**, which is four clocked open-drain lanes at
33 / 60 / 120 / 240 and nothing else. The arm's own comment said `ckod`'s
"lane set is the one A2 models". It is not.

Every other clocked arm ran with the bound **off**, for want of a number for
its lane set. So the check was simultaneously aimed at the wrong lane set on
one arm and absent on all the others.

### Derived per program

`model/a2/program_a2.py` builds each program's lane set **from its own image**
and computes each clocked open-drain lane's `r_i` with pyRTA primary:

| field | taken from | why |
| --- | --- | --- |
| `T` | the lane's minimum action delay | P8: timestamps advance absolutely, so the tightest delay is the tightest release |
| `C` | `C_SHIPPED` | measured dispatch service |
| `D_sched` | the header's `dsched` | that **is** the engine's EDF key; any other priority would describe a different machine |
| `D_tol` | the header's `dtol` | admissibility only; does not move `r_i` |
| `J` | `j_of(d_min, k)`, + `L_JIT` on an edge-released lane | `J` is a function of the program (ruling 1(b)) |

| image | U | lane budgets (`L_SYNC + 1 + r_i − C`) | measured widest |
| --- | --- | --- | --- |
| `corpus_i2c` | 0.067 | **8** | 4 |
| `ckod` | 0.184 | **8 / 11 / 17 / 18** | 7 |
| `ckdense` | 0.518 | **11 / 13 / 15 / 17** | 4 / 7 / 10 / 4 |
| `ckhold_over` | 0.212 | **10** | 4 |
| `corpus_all5` | **1.096** | **none — overloaded** | **131** |

⇒ **The shared 8 was tighter than the worst case of three of `ckod`'s four
lanes.** It held only because the measured schedule (widest 7) was gentler
than the worst case — exactly the situation in which nobody finds out.

⛔ **`corpus_all5`'s lateness is 131, not the 19 the handoff recorded.** That
number went stale when D5 moved lane 0 to `d = 70` beside four lanes still at
9–13. The lane set has `U = 1.096`, so **no finite worst-case response
exists**: the RTA has no fixed point and a number returned anyway would be the
horizon, not a bound. It is reported **unbounded** with that reason, and the
bench measures its lateness without a verdict — the status Wilson's earlier
ruling gave the stress image, now stated with its cause.

### Generated, never typed

`model/a2/program_a2.py` → `test/clocked_a2_bounds.json` → `test/benchset.py`
**generates** `+A2SLACK=s0,s1,s2,s3,s4` for every arm whose image has a clocked
open-drain lane. No arm carries a hand-typed bound and none can be left out —
the two failures the constant had at once. Fourteen clocked arms now carry
their own row. `-1` in a field means that lane's set is overloaded.

The bench reads it with `$sscanf` and **refuses a malformed value** rather than
treating it as unbounded, so a typo in a generated plusarg cannot switch the
check off. It reports **per lane**, because a program-wide "widest" would
compare one lane's lateness against another lane's budget — the max-over-the-set
error this ruling removes.

### The must-fire

No shipped image could demonstrate it. `ckod` measures 7 and `corpus_i2c` 4, so
a lighter budget of 8 never fails on either; the only image over 8 was
`corpus_all5`, which is overloaded and has no bound to compare against. So it
had to be built:

**`ckdense`** — `ckod`'s layout at d = 22 / 23 / 24 / 25 — is **feasible**
(U = 0.518, J = 1) and heavier than `corpus_i2c`. `test/a2_run.sh` runs it
twice:

| budget | verdict | widest per lane |
| --- | --- | --- |
| its own, 11 / 13 / 15 / 17 | **ok** | 4 / 7 / 10 / 4 |
| `corpus_i2c`'s, 8 on every lane | **red** | 4 / 7 / 10 / 4 |

⚠ **It fires on one release** — lane 2's 10 against 8 — deterministically
across all three rand-reset modes, but a single release is a thin margin, so the
gate requires the **verdict**, not a count. `ckdense` is also swept under its
own bound on every run, so the derived numbers are held continuously and not
only in the must-fire. It is a **scheduling stress image**, not a mode-legal
I2C program (at d = 22 the low phase is under Fm+'s 500 ns), and it inherits
`ckod`'s pin pairs, so lane 3 is declared in `PAD_COLLISION`.

### D2's per-program floor, on the same machinery

`pe_asm.check_mode_floor` runs **on the assembled image** through the same
`program_a2.derive`, so there is one model of `r_i`, not two. For each clocked
open-drain lane, the worst low phase `d − (r_i − C)` must clear **some**
UM10204 mode's `t_LOW` (via `gate_um10204.claimable`). "Some", because nothing
in the ISA declares which mode a lane intends: the assembler can only refuse a
lane that claims **none**, and it reports which mode each lane does clear.

| case | verdict |
| --- | --- |
| d = 20, above `SDA_HOLD` but under every `t_LOW` | **rejected** — the gap D2's static half used to leave open |
| d = 32, the clocked lane **alone** | accepted |
| d = 32, the **same lane** beside three busy lanes | **rejected** |

The last two were **searched, not guessed**: alone the lane clears Fm+ from
d = 30, beside the neighbours only from d = 38. A floor independent of the
neighbours would give one verdict for both. ⛔ The fixed 38 / 78 / 248 this
replaces was `ckod`'s observed jitter promoted to a law.

Overloaded and no-pyRTA are **refusals**, not passes: an assembler certifying
mode legality without the bound it rests on certifies nothing.

### Declared, not hidden

* **`J` is conservative.** It comes from the minimum **action** delay, which is
  a lower bound on §1's refill-bearing `d_min`, so `J`, `r_i` and the budget can
  only come out *larger* than exact. The bound stays sound and may be loose.
  It changes nothing for any program at `d ≥ D*` (all `J = 1` either way); it
  loosens the `ckhold_*` images, whose delays sit just above `SDA_HOLD`.
  Extending §1's composer to whole images would make it exact; not done here.
* **`k` is `N_LANES`** for every program, including idle filler lanes — the same
  conservative direction.
* **A2 is a model of the engine, not the engine.** What makes it more than
  arithmetic is that every swept clocked arm is now held to its own derived
  number.
* `gate_clocked_lane_a2` §6 no longer parses a bench constant; it reports the
  model's own shipped-set number (still 8) **as a reference for that lane set
  only**, and fails if a shared constant ever reappears in the bench.


### ⛔ First push was CI-red at 20 of 22 — my error, caught by CI1

`992c298` put two **pyRTA-dependent** checks into `ci/run_gates.sh`:
`gate_a2_program`'s currency check and `pe_asm.check_mode_floor`. This project
keeps **every pyRTA-primary gate out of CI by design** — pyRTA is not vendored,
and `model/a2/run_a2.py` runs those gates by hand at each checkpoint. Both
passed locally **only because a pyRTA clone sits in a scratch directory on the
development box**. CI (`37558472597`) went red. Checking CI on the exact SHA is
what caught it, which is ruling CI1 working as intended.

**Fixed without falling back on the principle:**

* `program_a2.derive(img, src=None)` computes **everything except the pyRTA
  column** — lane set, U, J, our own recurrence `r_ours`.
* **CI's `gate_a2_program`** re-derives all of that and compares; an image
  changed without the JSON being regenerated is caught on every push. It says
  plainly that the pyRTA column is not re-derived there. Priced: a lane's `T`
  moved by one is reported stale; the committed rows read as current.
* **`gate_a2_bounds_pyrta.py`** re-derives the pyRTA column (and so the bench
  budgets) under `run_a2.py`, **RED without pyRTA** — where the other
  pyRTA-primary gates live.
* **`pe_asm`'s floor uses `r_floor`** = max(our recurrence, pyRTA) when both
  exist, our recurrence alone otherwise, and the report names the basis. Our
  recurrence measured **≥ pyRTA on every clocked lane in the repo**, so it is
  the *stricter* floor — the safe direction for a refusal — but that is an
  observation, so the max is taken when pyRTA is present. The d = 32 must-fire
  boundaries are **identical** both ways (alone from 30, beside traffic from 38).
* ⇒ **The local suite now runs with `PYRTA_SRC=/nonexistent`**, so a local
  green is a prediction of CI rather than of this box.


---

## 17. Q2 + CI3 — the witness nobody ran, and every name buffer

### Q2 — `gate_corpus_trace`, restored, and what it found

It is the **two-simulator** corpus comparison — iverilog against Verilator,
cycle for cycle, on every corpus program. It was **not fail-open** (it returns
1 on a build failure); it was **unrun**: in no list, invoked by nothing, and
unable to build since `7a672b0`. Four things had to change before it could be
listed, and running it found two more defects.

| change | why |
| --- | --- |
| `pg_report` / `cb_report` folded into their `final` blocks | iverilog refuses `final` procedures that call tasks; Verilator accepts it. Each task had exactly one caller. That one shape kept the witness from building. |
| no path names a machine | it hardcoded `wsl.exe -d Ubuntu`, `/mnt/d/ProtocolEmulator`, `C:\tmp\corpus`, so it could only ever run on the development box. Scratch is now inside the checkout; the Verilator half runs natively where `verilator` is on PATH (CI) and through WSL where it is not, with one `vpath()` translation instead of two hand spellings. |
| window 1500 → **8000** cycles | at D5's d = 70 a bit period is 146 cycles, so 1500 cycles was **under one START + byte + ACK + STOP**. Runtime does not scale with it (66 s either way). |
| a **stale OPEN** entry now fails | it only printed; a program could start passing while still exempted. And the prose claimed an open arm "stays red" while the exit code never did that — corrected to say what the gate does. |

**Found by running it:**

1. **D2's must-fire mutant had become EQUIVALENT.** `M_OD_CLK_PUSHPULL` mutates
   the *unclocked* SHIFT arm's clock write. Since the self-clocked rework, every
   `clk_real & level = 1` SHIFT goes to the clocked arm, so in that branch
   `a_lvl` is always 0 whenever `clk_real` holds — and the mutant writes exactly
   the pull-low the clean design writes. **No image can kill it.** It read
   0 hard-1 and 0 contended cycles. Recorded as equivalent, not deleted.
   ⇒ **`M_CK_OD_CLK_DRIVE`** puts D2's defect in the arm it can still reach — the
   open-drain clocked HIGH drives a hard 1 instead of releasing. Measured:
   **2,961 hard-1 cycles** under it on `corpus_i2c`, and a bench-held SCL
   contends for **43 cycles** against it versus **0** for the real design.
2. **The readback stream's seeds disagreed at the honest window**, from cycle
   ~2247. Falsified rather than argued: the readback pointer increments freely
   and wraps at 2^AW, so a 51-byte image leaves 205 store addresses never
   written, and the store is **allowlisted unreset**. The same program padded to
   the full store gives **SEEDS AGREE**. So it is the store doing what its
   allowlist entry says, not an unreset engine flop. The arm now reads back a
   store-filling image — which also crosses the pointer's **wrap**, a framing
   edge the short window never reached. ⚠ A host reading past the bytes it
   loaded gets uninitialised store contents; that is now written down.

**Result: 7 of 8, 0 failed, 1 open** (`corpus_spim`, the stated FRAM-addressing
cause). **`corpus_i2c` and `corpus_all5` at d = 70 are CYCLE-EXACT across both
simulators**, every seed and phase, with the open-drain invariant holding —
the foreign witness on exactly the corpus that changed, as required before
sigrok re-certifies.

### GATES completeness

`model/gate_gates_complete.py` (in CI) requires every `gate_*.py` to be in
`ci/run_gates.sh`, in `model/a2/run_a2.py`, or **excluded by name** with a
reason, and reds on a stale exclusion. Priced: an unlisted dummy gate and a
stale exclusion are both reported. Its first run found **nine** gate files
nothing ran:

| gate | state | placed |
| --- | --- | --- |
| `gate_differential`, `gate_j9_margins`, `gate_jitter_sigrok`, `gate_reactive_2mhz` | pass (with and without pyRTA) | `run_a2.py` |
| `gate_fields`, `gate_pwm`, `gate_uart_identity` | pass (7 of 7) | via `run_ta02.py`, which was **itself invoked by nothing** — now in `run_a2.py` |
| `gate_flow_netlist` | needs the 3.5 h hardening netlist | excluded, by name |
| **`gate_cj_bounds`** | **RED** | excluded so the list describes the tree — **owed** |

⛔ `ci/run_gates.sh`'s header said every pyRTA-primary gate, **naming
`gate_j9_margins`**, runs under `run_a2.py`. It did not. Each of those gates'
last verdict was whatever it was the day it was written.

⛔ **`gate_cj_bounds` is red for a real reason it reports correctly**: its
census-coverage claim reads `test/cj_measured_alt.txt`, an **untracked** scratch
file that `tb_smoke` writes for any non-default image — last written by a
`five_image` run — so its own provenance check refuses the claim. Unrun since
`cb7f376`. Its live content (J as a function of the program) is carried by
`gate_j_program` / `gate_dmin_clocked`. **Owed, and a decision:** give its input
a recipe and track it, or retire it.

### CI3 — every bench's name buffer

* All thirteen benches: name buffers **256 bytes** (were 64, two were 160).
* **`test/imgload.vh`** — one macro, used after every plusarg-driven load,
  failing loudly if the name **fills** the buffer (it may be truncated) or the
  file **cannot be opened**.
* ⛔ **The first version of that macro could not fire under Verilator.** It
  tested `^img[0] === 1'bx`, but Verilator is two-state: with randomised reset an
  unloaded store holds random bits, never X. **Measured:** a 299-byte path was
  truncated, `$readmem file not found` printed, and the macro stayed silent
  while the bench ran on an empty store — the check-that-could-not-fire class
  inside the fix for it. Both tests are now about the name and the file, which
  mean the same in a two-state and a four-state simulator. `tb_smoke`'s older
  X-scan length check has the same Verilator blind spot; the macro now covers
  that bench in both.
* **Must-fire arm:** `tb_tx longpath` runs the `clean` arm unchanged through a
  **139-byte** `+IMG`, and must give the same passing assertions — proof the
  image loaded, not merely that nothing complained. Priced on one build:
  17 bytes clean, 139 bytes clean, **299 bytes refused** with both messages.
* **`gate_bench_lint`** refuses any filename buffer under 256 bytes on every
  bench, priced on the exact 64-byte declaration that broke CI.
* `tb_smoke`'s measurement-file `$fopen` is now fatal on failure; `tb_i2c`'s
  already was.


---

## 18. P6 + N1 — which pyRTA, and which images break the rules on purpose

### P6 — the timing witness, pinned

The primary foreign authority for every timing claim was being picked up from a
scratch-directory clone with **no recorded commit**. An unpinned witness is an
unverified one: a pyRTA change between two runs would move every bound it
certifies, and the record could not say whether it had.

* **Pinned**: `PROSA-Project/pyRTA` at **`1f3a649`** (2026-06-16), a clean clone,
  in `pyrta_src.PINNED_COMMIT`.
* **`pinned_pyrta()` / `require_pyrta()`** accept a clone only if it is a clean
  git checkout of exactly that commit, or if the run declares the difference by
  name: `PYRTA_DECLARED="<commit|UNKNOWN>: <reason>"`, which is then printed.
  An unpinned copy is treated as **absent**, so the pyRTA-primary gates go red
  and the CI-side derivations fall back to their own recurrence and say so.
* **Every pyRTA-reaching path prints the commit**: `require_pyrta`, `run_a2.py`'s
  banner, `program_a2`, `gate_a2_program`, and `pe_asm`'s floor basis
  (`max(our recurrence, pyRTA @ 1f3a649ced61)`).
* **Priced** (`pyrta_src` face 4): the real clone is PINNED; a pyRTA-shaped copy
  outside any git repo is refused; declared with a reason it is accepted and
  labelled; declared without a reason it is refused.
* **Recorded beside `65bc3c8114e5`** in `lane_digest.PYRTA_PIN`. At the pin,
  `gate_pyrta` reproduces that entry's responses **exactly** — r = {16, 12, 7,
  15, 9} on all five lanes. ⚠ That is a **reproduction**: which clone produced
  the entry first was never written down, which is the defect P6 closes.
  `lane_digest.selftest` fails if the ledger's hash and the enforced pin ever
  disagree.

### N1 — non-admissible images, declared

`model/gate_admissible_images.py` (in CI) derives three conditions from each
image and requires every violation to be declared by name with a reason:

| condition | test |
| --- | --- |
| OVERLOAD | U > 1 over the program's own lane set |
| PORT | refill-bearing `d_min` below `D* = 20` (`port_feasible`), so not J = 1 |
| PINMAP | a driving lane on an overridden pad — declared in `corpus.PAD_COLLISION` (P5), read from there |

Refusal images are exempt here because `gate_degenerate_fields.DELIBERATE`
already declares each one's refusal.

**The derived list is larger than the ruling's.** Beyond the four it named:

* **`five_image.hex` is OVERLOADED** (U = 1.083) — `build_five`'s stress image,
  the base for T1 and Theorem 3's port cells, never declared as such.
* **Nine more are below `D*`**: `corpus_uartrx`, `chain`, three `edge` images,
  three `noop` images, `tx`. Each is a mechanism test whose spacing is below
  `D*` by construction, and each now says so.

**The `d_min` is the refill-bearing release spacing, not the raw delay.**
Refills follow retires (R5), so the spacing that matters is between a lane's
consecutive retires: `d_i` after an unclocked retire, `d_i + L_SYNC + 1` after a
clocked open-drain one (it parks on the observed rise — the same term as A2's
slack), plus `(m − 1)·d` for the next action's remaining dispatches. Statically
this gives **37 on `ckod`** (R5 measured 37) and **20 on `ckhold_over`** (R5
measured 20), so `ckhold_over` is correctly *not* flagged. The raw minimum delay
would have flagged it — the conservative-but-wrong reading §1 already refuted.

⚠ It is the **nominal release** spacing, which is Theorem 3's quantity. A
measured *dispatch* spacing can sit up to J below it: R5 measured 69 on
`corpus_i2c` against a nominal 70.

Priced: an undeclared U > 1 image (the real `five_image` bytes under an
undeclared name) is reported, and so is a stale declaration.

### ⛔ The vacuous `$?`, a fourth time

My quick "fast gates" loops printed `"$(basename $g)" "$?"` — the command
substitution runs first and resets `$?`, so **every rc=0 those loops printed was
vacuous**. It surfaced here because `gate_stored_numbers` printed `***` lines
while the loop said 0 (real exit code: 1). No false green reached a commit: the
full suite reads exit codes correctly and ran before every commit. It is the
same shape as the three earlier instances in this arc, and E+'s lint gate is
what makes it mechanical rather than a matter of noticing.


---

## 19. E+ and Q3 — exit codes made mechanical; `five_image` was never evidence

### E+ — a shell exit code is read only where it can belong

Four times in this arc a checking loop printed an exit code that belonged to
something else, and once it hid a gate that was really exiting 1:

| shape | whose status `$?` actually held |
| --- | --- |
| `cmd \| tail; echo $?` | `tail`'s |
| `cmd \| head; echo "rc=$?"` | `head`'s |
| `printf "%s %s" "$(basename $g)" "$?"` | `basename`'s — the substitution ran first |

The third has **no pipe**, so `set -o pipefail` alone could not have caught it.

* **E1** — every `.sh` under `ci/`, `test/`, `model/` already sets `pipefail`;
  the gate keeps it so. One named exception: `ci/rc.sh`, a **sourced** helper,
  where setting shell options would silently change the caller's shell — and
  the gate reds if that helper ever gains a pipe.
* **E2** — `ci/rc.sh`: `run_rc` / `run_rc_quiet` capture the code on the next
  statement and print `rc=<n>  <command>`. Quick loops use it.
* **E3** — `model/gate_shell_rc.py` (in CI): no substitution before `$?` on its
  line, no `$?` reading a pipeline, and `$?` read on the very next line (or the
  same line after `;`). Backslash continuations are joined; single-quoted text
  is not scanned.
* **E4** — priced: a failing command piped into `tail` (both one- and two-line
  forms), `$?` after `$(basename …)` in a loop, a blank line before `$?`, and a
  script without `pipefail` are all red; a redirected command, a continued
  command, `cmd; rc=$?` and `'$?'` in single quotes are all accepted.

**Every committed `$?` read was already clean** (17 of them) — all four vacuous
instances were in throwaway interactive loops, not files. So the gate guards the
committed scripts going forward, and the helper fixes the practice.

⛔ **A check-that-could-not-fire, caught before it shipped:** the first version
of the "sourced helper must stay pipe-free" check ran over the whole file, and
the comment-stripper stops at the first `#` — the shebang. It is now per line
and priced.

### Q3 — was `five_image` ever evidence?

**No claim scoped to admissible programs rests on a non-admissible run.** The
deciding distinction is between the **builder** and the **tracked file**: the
claim-bearing runners rebuild `--five` at their own delays into their own output
names, so each run point is judged at the delays it used.

| runner | delays | admissible? | role |
| --- | --- | --- | --- |
| `run_dstar_check` — Theorem 3's **35 cells**, the live J = 1 sweep | d … d+4, d = 20…60 | **all 7 points** (U ≤ 0.685) | claim |
| `run_csat` S / T — **C = 3** | 40×5, 60×5 | yes | claim |
| `run_csat` U | 2×5 | no — U = 7.5 | one-sided contrast ("may only be larger") |
| `run_spl_compare` | d = 8…30 | the claim is **scoped** to d ≥ 20, all admissible | claim |
| `run_jlane` A / C | 12…16; 8,100×4 | no, on purpose | sub-D* J characterisation; the aggregate 8 recorded on A was later **retracted** (ledger `b4e51034e283`) |
| **tracked `five_image.hex`** | 12…16 | **no** — U = 1.083 | `tb_witness` stall chain (a floor), `M_BUF_SWAP`'s kill, `gate_cj_bounds` (owed, CJ) |

⇒ **The tracked `five_image` is mechanism only**, and its N1 entry now says so.

⛔ **My own N1 entry was wrong** — it called the tracked file "the measurement
base for T1's per-lane J and Theorem 3's port-feasible cells", conflating the
file with the builder at other delays. `pe_asm`'s and `gate_ruling_audit`'s
comments made the same conflation; all three are corrected.

### Found while answering Q3 — README, for Nathan (not edited: the write-up is his)

* **The README's shipped-program row is the pre-C = 3 table.** It shows
  `r = {11, 8, 5, 10, 6}, min margin 12`; ledger entry `65bc3c8114e5` re-quoted
  it to `r = {16, 12, 7, 15, 9}, min margin 11` when C was corrected 2 → 3 — and
  that is what `gate_pyrta` reproduces at the pinned pyRTA.
* **The README still presents the universal `J = 8` row** ("over every
  admissible program"). Ledger entry `b4e51034e283` **withdrew** universal J = 8
  as unsound and replaced it with the scoped claim `d_min ≥ D* = 20 → J = 1`.

---

## 20. M — the store is written whole; README traced to the ledger

### M3 — can a lane's PC reach a byte past its program? (answered first)

**From the RTL.** A lane's PC changes in exactly three places, all in the
writeback (`src/pe_engine.v`): `+ACT_BYTES` when a non-REARM retires, `l_base`
when a looping REARM (level 1) retires, and **not at all** on a chaining REARM
(level 0), which never retires (`act_retire`). There is no branch or jump
opcode. The prefetch reads only `l_pc` (empty head), `l_base` (head is a
looping REARM) or `l_fpc` = last fetch + `ACT_BYTES`, and fetches nothing past a
chaining REARM head (`want_fetch`). So, case by case:

| path | reaches past the program? |
| --- | --- |
| branch / jump target | none exist |
| refill speculation | the spare is the head's successor; for a terminated program that is still inside it |
| end-of-lane fall-through | **only if the lane has no terminating REARM** |
| header base outside the program | **yes, from the first fetch** |
| wrap at 2^AW (`l_pc`, `l_fpc` are AW bits) | only after (a) or (b) carries the PC to 255 |

**From the bench** — `test/store_run.sh`, pinned Verilator 5.053, with the
sentinel Layer M in `test/clocked_conform.vh` (every P_CAP compared against the
filler word):

| image (full store) | prefetch captures | filler fetched |
| --- | --- | --- |
| `corpus_i2c` | 223 | **0** |
| `ckod_image` | 378 | **0** |
| `corpus_all5` | 11,422 | **0** |
| `smoke_image` | 4,933 | **0** |
| `falloff` (must-fire: a lane with no terminating REARM) | 7 | **1** — lane 0 at address 39 |

The must-fire shows the path: the **speculative spare fetch** one word past the
lane's last action, while the head was still its final LEVEL. After that the
lane parked on the filler (1 of 7 captures, not a walk through the store).

### M1 — every image is the whole store, with a defined filler

`pe_isa.STORE_FILLER` = `feffc0` = **`OP_REARM`, level 0 (chaining), pin
`PIN_NONE`, delay 1023, count 0, q 0**. Classified in the degenerate-field
audit by the existing row `("REARM", "pin", "PIN_NONE or >= N_PINS")` =
**DEFINED**. Non-driving (`OP_ARM, OP_REARM: ;`), non-retiring, so a lane that
ever reached it parks instead of walking on.

* ⛔ **q = 0 on purpose.** The first draft set q = 3 to make the word
  distinctive; `host_q = a_q` steers `project.v`'s TX-queue mux while the
  action is current. Nothing pops on a REARM, but a "non-driving" filler should
  not move a select line, so it matches every REARM already shipped.
* `pe_isa.write_image` is the one writer: all 22 writers in
  `make_smoke_image.py` and the corpus writer go through it, and
  `pe_asm.assemble` returns the full store (reporting program and filler bytes).
* All **33 images** are now 256 bytes (23 tracked, 10 regenerated from recipes);
  the manifest is re-pinned.
* `test/run_param_points.py` hard-coded `+NBYTES=87` and `+NBYTES=54` — loads
  that would have left the rest of the store unwritten. Now `STORE_BYTES`.
* `gate_corpus_trace`'s readback arm zero-padded `corpus_i2c` itself; it now
  runs the tracked image and refuses a short one.

⛔ **A walker that would have misread the filler, fixed with it.**
`gate_degenerate_fields.walk` stopped only at a *looping* REARM and ran on past
a chaining one. That was harmless while every parked lane's REARM was its
image's last word. Measured before the change: walks are identical on every
tracked image. Padded, the old walk read 60–70 phantom filler actions per
parked lane. It now stops at any REARM, as the RTL does.

### M2 — the audit (`model/gate_store_full.py`, in CI)

Per image on disk: exactly 256 bytes; the tail is the filler from an action
boundary; every lane's header base is inside its program and aligned; every
lane's walk ends on **its own** REARM, not on the filler. Also checks the
filler's fields and classification, and that `test/store_filler.vh` matches
`pe_isa.filler_vh()`. **Must-fires:** the 51-byte pre-M `corpus_i2c` (red), a
lane with no terminating REARM (red), a header base pointing into the filler
(red), and the clean image (accepted).

It also judges the **simulated** half: `ci/run_gates.sh` runs
`test/store_run.sh` as a measurement step (one Verilator build, ~40 s) and the
gate is **red without `PE_STORE_JSON`**, the same rule as R and S. Layer M runs
in every bench, but on a clean image it can only ever report zero. The
`falloff` arm is what shows it can name a lane.

⚠ **Found, not ruled on:** `corpus_all5` offset 87 is the one unreachable word
in any image. `corpus._assemble` always appends a park REARM, and in all5 every
lane is live, so nothing uses it. It is a defined, inert word; no dead-code rule
was added.

### M4 — load time

Every Verilog bench's loader takes **6 cycles/byte** (`tb_smoke` 7); cocotb's
`load_image` takes 9.

| image | before | at 256 bytes |
| --- | --- | --- |
| smallest (39 B, the ckhold/ckdegen set) | 234 cy | 1,536 cy |
| `corpus_i2c` (51 B) | 306 cy | 1,536 cy |
| largest (`i2caddr`, 231 B) | 1,386 cy | 1,536 cy |
| `tb_smoke` | 357 cy (51 B) | 1,792 cy |
| cocotb | 464 cy (51 B) | 2,309 cy |

**No bench's window assumption changes.** Every `+NCYC` run loop starts after
the load loop; `progress.vh`'s watchdog counts dispatches, not time; cocotb
sets no wall-time limits; every bench's image buffer is already 256. The two
cocotb readback tests that load 8 literal bytes stay in load mode and never
run the engine, so M does not reach them.

### README, option (a), with RD1

Nathan chose (a). Only ledger numbers were changed:

| README item | was | now | source |
| --- | --- | --- | --- |
| lane table `C` (all five) | 2 | **3** | `65bc3c8114e5`, live `bursty` table |
| SPI-target `D_tol` | 18 | **17** | same entry ("two fields moved") |
| shipped row | `{11,8,5,10,6}`, margin 12 | **`{16,12,7,15,9}`, margin 11** | same entry; = `PYRTA_PIN` |
| shipped `J = 1` row | 12 / 12 | **11 / 11** | same entry |
| universal `J = 8` row | present | **removed**; `d_min ≥ D* = 20 → J = 1` stated | `b4e51034e283` |

⚠ **Two things beyond "the two rows", stated rather than hidden.** The lane
table's C column and SPI-target D_tol come from the same ledger entry as the
shipped row; leaving them would have made RD1 a gate that passes by not
looking. And the sentence after the table, "The universal row is the honest
one: over every admissible program …", *is* the withdrawn claim, so it was
removed with its row. Nothing else in the README changed; framing and prose
are Nathan's (F7b).

**RD1** (`gate_stored_numbers.readme_check`, in CI): lane table against
`lane_digest.shipped()`, r and margin against the newest `DIGEST_LEDGER` entry
(and that entry against `PYRTA_PIN`), D* against `gate_j_program.D_STAR`, and
`WITHDRAWN` patterns red anywhere in the README. On the unedited README it
reported 13 findings. **Must-fires:** the universal `J = 8` row re-inserted,
the pre-C = 3 shipped row restored, and a lane-table C reverted to 2 are all
red.

---

## 21. M5 and M6 — the chip, not just the toolchain

The audit covers images our toolchain writes. M5 and M6 are about what the chip
does with an image that **didn't** come from it.

### M5 — the loader auto-increments, so silicon refuses a partial load

**The addressing:** `project.v`'s `ptr` resets on `ptr` (`ui_in[5]`) and steps
+1 on each write strobe. There is no address bus, so a write counter is enough.

**What was built (`src/project.v`, AW + 3 flops):**

* `wr_run` (AW + 1 bits) counts **consecutive** writes; a `ptr` pulse clears it
  until it saturates. Its top bit, `store_full`, means "every store byte has
  been written since power-on". 2^AW consecutive writes from any start cover
  every address, and a written byte stays written, so it is **sticky until
  `rst_n`**.
* ⛔ **Consecutive, not total.** Counting every write would accept "200 bytes,
  `ptr`, 60 bytes": 260 writes with 200..255 never written.
* The engine's run input is `run & store_full`, so the engine never executes an
  unwritten store, **including the power-up window** with `prog` low.
* `short_load`: releasing load mode with `store_full` clear sets a sticky that
  is OR-ed into **CONFIG_ERR** (status bit 5).

⛔ **The first cut refused every full load.** It set the engine's
`config_err` at run entry when `store_full` was clear. Benches, and real hosts,
release reset with `prog` low for a cycle or more, so the check fired on the
empty store and the sticky outlived the full load that followed (`store_run.sh`:
CONFIG_ERR on all four full images, 0 writebacks). The refusal now fires **at
the release from load mode**, as ruled, and the power-up window is covered by
the silent run gate instead of an error.

**Measured (`test/store_run.sh`, pinned Verilator 5.053):**

| arm | build | bytes | store_full | CONFIG_ERR | writebacks |
| --- | --- | --- | --- | --- | --- |
| `corpus_i2c` | clean | 256 | 1 | 0 | 1,317 |
| `ckod_image` | clean | 256 | 1 | 0 | 3,309 |
| `corpus_all5` | clean | 256 | 1 | 0 | 16,745 |
| `smoke_image` | clean | 256 | 1 | 0 | 5,286 |
| **`short51`** (corpus_i2c's 51 program bytes) | clean | 51 | 0 | **1** | **0** |
| **`mut_short51`** | `M_NO_STORE_FULL` | 51 | 0 | 1 | **1,317** |

Full loads run with prefetch counts identical to §20's M3 table, so the gate
changes no timing. The mutant runs the same 51-byte load exactly as the full one
does, so it's the gate that refuses. `M_NO_STORE_FULL` is registered in
`gate_mutant_arms` (2 lines, minimal) and `gate_store_full` holds every row
above.

⛔ **What the silicon refusal caught on its first full-suite run:** three
corpus programs and the async-clear arm in `gate_corpus_trace` went
"constant", meaning the engine never ran. That gate sized its loads from the
builder's program length (`len(img_bytes)` = 51 for `corpus_i2c`), not from the
256-byte file. It had been loading partial stores all along, which is exactly
what M5 refuses. It now loads the file. `verilator_trace.sh`'s default byte
count of 51 is now 256. The coverage sweep gained a `shortload` arm (tb_trace,
corpus_i2c, `+NBYTES=51`) because the release-time refusal was the one new
uncovered branch. `benchset.plan()` no longer appends the file's byte count
when an arm names its own, because a plusarg's first occurrence wins. `docs/HOST_INTERFACE.md` now states **"load the full store"**, the
counting rule, and the release-time CONFIG_ERR.

### M6 — loud filler: no existing encoding is refused for every lane

Every refusal the engine raises at dispatch depends on the **lane's header**:

| refusal | needs |
| --- | --- |
| 1.6x clock alias (`OP_SHIFT`, clkpin == pin) | the lane's `clkpin` to equal the action's pin |
| `ck_degen`, D1 `ck_holdviol` | a real clock pin in the header (`clk_real`) |
| 1.6s open-drain on `uo_out` | header-time, not dispatch |

The "refused" receive and arm rows in the degenerate-field table
(`SHIFTIN` / `READBIT` / `ARM` on `PIN_NONE`) are **silent guards**
(`pin_real`, `arm_real`): the read is suppressed and **CONFIG_ERR is not set**.
So no word is refused at dispatch on every lane without new logic.

⇒ **`feffc0` stays, and the trade is recorded: a lane that escapes its program
parks silently.** What makes that acceptable now is that both ways to escape
are closed before the engine runs. A missing terminating REARM or an
out-of-program base is refused by `gate_store_full` on every image the
toolchain writes. A host-written partial image is refused by M5 in silicon.
What remains is a host that writes a *full* store containing a malformed
program, which the chip runs and the escaping lane parks on the filler without
telling anyone.

---

## 22. V, MU, CJ — what runs is named, what is killed is re-killed, what is superseded says so

### M7 and the silicon-fix ledger

`HOST_INTERFACE.md` now says the full-store rule binds the **first** load after
`rst_n`. After that, partial reloads run, because every byte is still defined.
The handoff gained a "silicon fixes" ledger; its first entry is the power-up run
(PROG low at reset release, engine running the power-up store), closed by M5's
`store_full` gate.

### V — one resolver per language, and every log names the binary

* `ci/tools.sh` (shell, sourced, pipe-free) and `test/toolchain.py tool()` /
  `banner()` (Python). Each reads `PE_VERILATOR` / `PE_IVERILOG` / `PE_VVP` /
  `PE_YOSYS` first, then PATH, and returns an absolute path. `vvp` defaults to
  the iverilog install's sibling.
* **Converted:** 13 Python files (30 argv sites, plus 2 private resolvers) and
  13 shell scripts. 14 Python entry points and every resolver-using script print
  `tool <name>: <path>  <version>`.
* **`model/gate_tool_pinning.py` (CI):** refuses a bare tool in command
  position, a Python argv headed by a bare tool name, a `which("<tool>")`, a
  private `${PE_X:-<tool>}` or `environ.get("PE_X", "<tool>")`, a script that
  runs a resolved tool without a banner, and a resolved run without sourcing
  the resolver. **Must-fire:** `verilator_trace.sh` as it stood at `f8f952c`
  (committed as a fixture, because CI checks out at depth 1, and compared
  byte-for-byte with `git show` where history exists), plus one synthetic case
  per rule.
* **The witness must show 5.053, enforced:** `gate_corpus_trace` parses every
  Verilator-side run's `tool verilator` banner and reds unless it is the pin
  (`toolchain.pinned_ok`, token equality). `gate_coverage.PINNED_TOOL` now
  reads `toolchain.PINNED_VERILATOR`, so the pin is stated once.

⛔ **Three more instances of the defect V names, found answering it:**

| where | what it ran |
| --- | --- |
| `test/artefacts.sha256` header (`toolchain` probe) | a bare WSL `verilator` = **apt 5.032**, which built nothing; now the pinned path, header reads 5.053 |
| `gate_corpus_trace` on this machine (`wsl.exe -- bash verilator_trace.sh`) | the WSL side resolved its own PATH; now `env PE_VERILATOR=<pin>` in the fixed argv |
| `gate_one_encoder` → `param_dump.sh` via WSL | same; same fix |

### MU — every mutant killed by a killer that runs, or declared

**What answering it measured:**

* `test/run_mutants.py` (12 kills, ~10 s) was run by **nothing**: not CI, not
  `run_a2`.
* Six clocked mutants (`M_CK_NEVER_RETIRE`, `M_CK_NO_ALTERNATE`,
  `M_CK_NO_PARK`, `M_CK_HOLD_RETIRES`, `M_CK_REBASE_2D`, plus the R/R4 pair
  under iverilog) were named by **no script**; each was killed once by a
  hand-run probe and recorded here. The same was true of `M_ACK_DRIVES_SDA`,
  `M_BUS_NO_PULLDOWN` and `M_PFETCH_NOWAIT`. `M_COMB_OUT` was priced only by
  hand, and `M_IGNORE_ORDER`'s killer (`run_i2c.py`) was run by nothing.
* ⛔ **Layer R failed the CLEAN design under iverilog**: 13 of 64 clocked
  actions "over the bound", worst 9. It closed its window by reading Layer B's
  `cb_*` variables, which another `always @(posedge)` block writes with blocking
  assignments. Verilator happened to run R first; iverilog ran B first, so R
  never saw the PC change. The verdict was a property of block ordering. **R now
  keeps its own window state** (`cr_pc`, `cr_ck`, `cr_op`, `cr_cnt`, `cr_n`).
  Clean is 0 failures on both simulators, and the R/R4 mutants still die. The
  only other cross-block read (R5's `cb_ck`/`cb_n`) is of a value written at
  least one edge earlier and is safe.

**Wired:**

| killer | runs in | kills |
| --- | --- | --- |
| `test/run_mutants.py` (new clocked family on `tb_trace`, baseline 0 FAIL / 0 hard-1 required) | **CI** | 22 |
| `model/gate_f2_local.py`: F2 face 3 on the real yosys graph, clean must pass, `-D M_COMB_OUT` must fail (both netlists ~5 s, built in the netlist step) | **CI** | `M_COMB_OUT` |
| `gate_store_full`, `gate_corpus_trace` | CI | `M_NO_STORE_FULL`, `M_CK_OD_CLK_DRIVE` |
| `test/run_i2c.py` (sigrok, local only) | **run_a2** | `M_IGNORE_ORDER` |
| declared survivors | — | `M_NOOP_DRIVES`, `M_CK_NO_PHASE_RESET`, `M_OD_CLK_PUSHPULL` |

Clocked kills, each of its named layer: progress[A] (`NEVER_RETIRE`,
`NO_ALTERNATE`), G1 (`NO_PARK`), A1 (`HOLD_RETIRES`), A2 with the image's own
budget (`REBASE_2D`), R (`HOLD_INVAL`), R4a (`PFETCH_BOTH_INVAL`), Layer M
(`PFETCH_NOWAIT`: the capture files the previous read's word, which on a
full-store image is a filler fetch), an open-drain **hard-1** in the trace
(`ACK_DRIVES_SDA`, 6,818 cycles against 0 clean), "no action retired"
(`BUS_NO_PULLDOWN`).

**`model/gate_mutant_kills.py` (CI):** 29 defines across `src/` and the bench
includes. Each is killed by a file that is in CI's or `run_a2`'s list and names
it (for `run_mutants.py`, in a RUN list, not prose), or is a declared survivor.
**Must-fires:** an unregistered dummy, a mutant named only in prose, a killer
nothing runs, a stale entry, and a mutant whose arms are identical to clean
(empty preprocessed diff) are all red.

### CJ — `gate_cj_bounds` retired, with a pointer per claim

| its claim | now |
| --- | --- |
| C_max = 2, every opcode | occupancy; RTA charges spacing C = 3 → `gate_c3_requote` + `run_csat` (`65bc3c8114e5`) |
| J_max = 8, universal | **withdrawn** → `d_min ≥ D* = 20 → J = 1`, `gate_j_program` / `gate_dmin_clocked` (`b4e51034e283`) |
| opcode coverage 8/8 | its census input was written by `five_image` → the coverage sweep, `gate_coverage` |
| double buffer: 2 pre-registered, 7 measured | `bursty.DOUBLE_BUFFER_PREREG` (a LEDGER site) |
| J = 0..10 margin table | pre-C = 3 → `gate_c3_requote` |

The file stays, for its history. Its header carries `RETIRED (ruling CJ)`; run
plainly it prints the pointers and exits 0, and `--legacy` runs the old checks.
`gate_gates_complete` has a `RETIRED` class: banner required, not in any run
list, every successor run. Its three new must-fires fire.

⚠ **Found following the pointer:** `gate_c3_requote` face (c) still called
J = 8 "the derived worst-case J … nothing admitted can reach". That is the
withdrawn claim, in a live `run_a2` gate. **Relabelled only**, as the J = 8
*stress point* (the retracted universal figure). Every number and check is
unchanged.

### Found on the way: the artefact manifest was stale since `9ebcaeb`

All five `corpus_*.hex` hashes in `test/artefacts.sha256` were the
pre-final-filler bytes. In M, `make_smoke_image.py --all` (which writes the
manifest) ran before `corpus.py` rewrote the corpus, and nothing in CI compares
the manifest. Fixed in place; and `--all` now runs `corpus.py` itself before
hashing, so one command writes every artefact it pins.

---

## 23. RA + MF — what the racy Layer R measured, re-measured; two holes closed

### RA1 / RA2 — every accepted Layer R number re-measured on both simulators

Every R figure accepted before `0e29fe7` was measured with the racy Layer R.
`test/race_remeasure.py` re-runs Layer R, R4 and R5 with the fixed bench, on
**iverilog 12.0 and Verilator 5.053 separately**: 5 images × 3 builds, 60,000
cycles each, parsed by `refill_collect`'s own patterns.

**The two simulators' tables are identical, field for field, on all 15 runs.**

| build | ckod | corpus_i2c | corpus_all5 | ckfive | ckhold_over |
| --- | --- | --- | --- | --- | --- |
| clean: R worst (actions) | 1 (184) | 1 (72) | **2** (376) | 1 (310) | 1 (196) |
| clean: R4 / R5 | ok, 1 slot, 1 in flight / 0 non-retiring | same | same | same | same |
| `M_CK_HOLD_INVAL`: R worst | **16** | **16** | **17** | 17 | 16 |
| `M_CK_HOLD_INVAL`: R4 | ok | ok | ok | ok | ok |
| `M_PFETCH_BOTH_INVAL`: R worst | 2 (ok) | 2 | 2 | 2 | 2 |
| `M_PFETCH_BOTH_INVAL`: R4 violations | 185 | 181 | 1,374 | 310 | 197 |

* **Clean worst 1/1/2/1/1**, as expected. **`corpus_all5` still measures 2**,
  so RA2 does not trigger: the `SPL` bound keeps both its structural argument
  and its measured confirmation.
* **The kills stand: 16/16/17** on the three accepted images (17/16 on the two
  added).
* **The orthogonality stands:** `M_CK_HOLD_INVAL` fails R and passes R4;
  `M_PFETCH_BOTH_INVAL` fails R4 and passes R (worst 2 against a bound of 2).
* ⇒ Verilator's block order had happened to give the right answer every time,
  which is why the race was invisible there. That is now a measured fact, not a
  "probably".

### RA3 — `model/gate_bench_races.py` (CI)

The race class as a gate. For every bench in `test/*.v`, with its `include`s
expanded (a bench and its layers share one module scope), a variable written by
a **blocking** `=` in one `always @(<edge>)` block and read by another block on
the **same** sensitivity is red. The exception is a read declared in `SAFE`
with its reason; a declaration names the reading block by an anchor token, so
the same variable read elsewhere is not covered. Non-blocking writes are exempt,
because the language orders them. **18 files, 2 declared safe reads** (R5's
`cb_ck`/`cb_n`, latched one edge earlier), **0 undeclared.**
**Must-fires:** Layer R as it stood at `231b37c` (a committed fixture, because
CI checks out at depth 1) is red on exactly `cb_pc`, `cb_ck`, `cb_op`,
`cb_cnt` and `cb_n`. A synthetic blocking race is red; the same read of a
non-blocking write passes.

### MF1 — `test/gate_manifest.py` (CI)

Every hash in `test/artefacts.sha256` is checked against its file.
⛔ **Which manifest matters:** a fresh CI clone lacks the 10 generated images,
so `benchset.base_images()` runs `--all`, which **rewrites the working-copy
manifest from the files it just built**. A check against that copy cannot fail,
and is exactly how the stale lines would have passed CI. So in CI the gate reads
the **committed** manifest (`git show HEAD:`), and locally the working copy
(a commit in progress changes it). **Must-fires:** one flipped byte; an empty
manifest; and **the manifest as committed at `231b37c`** (fixture), which it
reds on exactly the five stale `corpus_*.hex` lines and nothing else.

---

## 24. K + U + RL1 — every chip-driven SDA move holds; the refusal covers the unclocked frame

### RL1 — Verilator lint on `src/` (`model/gate_rtl_lint.py`, CI)

No Verilator lint ran on the RTL before. `-Wall` on `src/` reports BLKSEQ 2,
COMBDLY 0, plus UNUSEDSIGNAL 9, UNUSEDPARAM 5, WIDTHTRUNC 3, SYNCASYNCNET 1 and
DECLFILENAME 1 (reported, not judged). Both BLKSEQs are `prime_unp`, the
priming block's loop accumulator; the comment above it records why it isn't an
`always @*`. It is declared a **block-local temporary**, and the gate *checks*
that claim (every use inside one `always` block) rather than taking it.
**Must-fires** (planted copies under `probe_rl1/`): `ptr = ptr + 1` in a
clocked block is red; `cfg_err <= config_err` in a combinational block is red.

### K — the clocked SHIFTIN's release is held

**Layer H** (`test/clocked_conform.vh`). On every open-drain lane with a real
clock pin it records the chip's own SCL falls and every chip-driven SDA change,
and attributes each change to the opcode that caused it: the dispatch itself,
or the dispatch that loaded the hold pipeline. A data class (SHIFT, the 1-bit
SHIFT a master ACK/NACK is, SHIFTIN's release, READBIT's release) landing less
than `SDA_HOLD` after the fall is red. Before the fix it reproduced the finding
with attribution instead of a falsifier set: **corpus_i2c, SHIFTIN release,
14 of 14 at hold 0.**

**The fix** (`pe_engine.v`, the SHIFTIN arm). On an open-drain lane with a real
clock, a clock-low SHIFTIN dispatch now loads the **same hold pipeline** the
transmit path uses, instead of releasing SDA directly. HIGH/COLL dispatches find
SDA already released. `M_ACK_DRIVES_SDA`'s drive stays direct. The hold applies
when the action names the lane's pin, as on the transmit side.
`M_SHIFTIN_UNHELD` restores the unheld release.

**K2: class × image (`model/gate_sda_hold.py`, CI, 60,000 cycles, iverilog).**
Holds are in cycles after the chip's SCL fall; "high" counts moves with SCL
released.

| image | class | n | hold min..max | high |
| --- | --- | --- | --- | --- |
| corpus_i2c | SHIFT data | 109 | 15..365 | 0 |
| corpus_i2c | **SHIFTIN release** | 20 | **15..15** | 0 |
| corpus_all5 | SHIFT data / SHIFTIN release | 113 / 21 | 15.. / 15..15 | 0 |
| ckod | SHIFT data | 535 | 15..15 | 0 |
| **ckread** | SHIFT data | 45 | 15..15 | 0 |
| **ckread** | SHIFTIN release | 10 | 15..15 | 0 |
| **ckread** | **SHIFT 1-bit (ACK/NACK)** | 14 | 85..85 | 0 |
| i2cframe (d = 62) | SHIFT data / SHIFTIN release | 156 / 11 | 15..77 / 62 | 0 |

Required cells: corpus_i2c {SHIFT, SHIFTIN}, ckod {SHIFT}, **ckread {SHIFT,
SHIFTIN, ACK/NACK}**, i2cframe {SHIFT}. An empty one is red. `ckread_image` is
new (`make_smoke_image.py --ckread`). Every program in the tree was a write, so
none had a master ACK/NACK or the release that follows it. Its A2 budget is
generated into `clocked_a2_bounds.json` (7/8, the same row as corpus_i2c).

**K3:** `M_SHIFTIN_UNHELD` on corpus_i2c reads SHIFTIN release hold **0** and
Layer H is red. **K4:** Layer H is clean on corpus_i2c, and at the wire level
`phases_run.sh` gained a **corpus_i2c arm** that `gate_um10204`'s hold floor now
**requires**. It measured `t_HD;DAT` min **15 over 217 periods**, against
`{0: 20, 15: 93, ...}` before the fix. The ruling-H arm set had been
`ckod`-only, which is why it could not see this.

### U — the refusal covers every open-drain data drive the hold applies to

`ck_holdviol` is now `(ck_act | uc_hold) & ~l_mode & (SDA_HOLD != 0) &
d <= SDA_HOLD`, where `uc_hold` is the unclocked open-drain SHIFT that takes its
own clock low, the certified frame's shape. **The `ck_hold_fits` clamp is
retired** (its wire, per-lane compare and term are gone), because nothing can
reach it. `M_HOLD_CLOCKED_ONLY` restores the old scope.
The static mirrors follow: `gate_degenerate_fields.violations()` (no tracked
image is newly refused) and **`pe_asm.check_clocked_hold_delay`**, which
*accepted* the unclocked program below the hold until now and would have told a
user that a program the chip refuses was fine. Its demo now expects a
rejection.
**U2:** `build_i2cframe` at d = 15 is refused (CONFIG_ERR) and at d = 16 runs.
**U3:** the certified frames (`i2cframe`, `i2caddr`) are at d = 62, so no delay
moved. **Must-fire:** `M_HOLD_CLOCKED_ONLY` runs d = 15, which the clean build
refuses, with 635 data moves while SCL is released.

### ⛔ Three findings past what K/U ruled, measured and NOT acted on

1. **The silicon floor `d > SDA_HOLD` guarantees the HOLD, not SETUP.**
   With one cycle of release jitter, d = SDA_HOLD + 1 leaves no setup:

   | program | d | holds | data moves with SCL released |
   | --- | --- | --- | --- |
   | `ckhold_over` (clocked, D4's "must RUN" point) | 16 | all 15 | **11 of 562** |
   | `build_i2cframe` (unclocked) | 16 | 15..31 | **10 of 606** |
   | `build_i2cframe` | 17 | 15..33 | **3 of 572** |
   | `build_i2cframe` | 18…30 | ≥ 15 | 0 |

   Setup is the mode floor's job (D2), and `pe_asm.check_mode_floor` rejects
   `ckhold_over`. So Layer H only *reports* setup moves, and `gate_sda_hold`
   reds them only on images that a floor covers and passes; the gate checks
   that marking rather than assuming it.
2. **The mode floor does not cover unclocked lanes.** `check_mode_floor`
   returns `{}` for `i2cframe`, so `pe_asm` accepts the unclocked frame at
   d = 16 that moves SDA with SCL released.
3. **The unclocked SHIFTIN release is not held.** Its hold is the inter-dispatch
   delay minus jitter: **14 at d = 16**, ≥ 15 from d = 17. K's fix covers the
   *clocked* SHIFTIN, which is the only one that takes the clock low itself.

Options for a ruling: (a) extend the mode floor to unclocked open-drain frames
(toolchain only); (b) in silicon, make a lane ineligible to dispatch while its
own hold is pending, so the clock cannot rise before the data lands, whatever
the jitter; (c) raise the silicon floor to `SDA_HOLD + 2`. These are recorded,
not chosen.

## 25. W — no SDA change while SCL is high, in silicon

Ruling W chose (b) for the safety net and (a) for compliance, and rejected (c):
a constant floor on `d` cannot bound contention jitter, which grows with the
lane set. Findings 1 and 3 above are the ACK bug's hazard: a data bit that moves
after SCL is released is SDA changing while SCL is high, which is a START or a
STOP to any receiver.

### W1 — a lane is ineligible while its own hold + setup is pending

`SDA_SETUP_NS = 50` (Fm+'s t_SU;DAT, the strictest declared mode) gives
`SDA_SETUP = 3` cycles at 50 MHz, by the same ceiling formula as the hold. The
hold counter now carries both. It is loaded with `SDA_HOLD + SDA_SETUP` = 18,
the pin is written when it reaches `SDA_SETUP + 1`, which is SDA_HOLD cycles
after the load exactly as before, and it keeps counting to 0. `ready` is split
into `rel_due` (the release has arrived) and `ready = rel_due & (l_hcnt == 0)`,
so the lane cannot dispatch its next edge, the SCL release, until the data has
landed and settled. The counter starts at the dispatch that actually happened,
so a lane dispatched late by contention is held back by exactly what it lost.
That makes it contention-independent by construction. **Cost:** `HOLDW` goes
from 4 to 5 bits (one flop per lane). At `SDA_HOLD = 0` nothing loads the
counter and nothing is gated, so that build is still the measured defect.
**Mutant:** `M_NO_HOLD_GATE` (`ready = rel_due`).

Only releases that **move** SDA load the pipeline now (`& pin_oe[a_pin]` on
K's clocked SHIFTIN arm). Later LOW/COLL dispatches find SDA already released,
and they used to load anyway. That was a no-op on the wire, but W1 would have
turned it into a dispatch delay. It also put two hold loads back to back (COLL,
then the next action's LOW), which is the one shape W6's bound cannot handle.

### W2 — the unclocked SHIFTIN/READBIT release goes through the hold pipeline

In the certified frame the clock fall is a separate `OP_LEVEL` and the release
follows one delay later. Its hold was therefore the inter-dispatch gap minus
contention: **14 at d = 16**. When the lane has a real clock, is open-drain,
the action names the lane's pin and SDA is actually driven, the release now
loads the pipeline. It lands SDA_HOLD after the dispatch, on top of the gap,
and W1 keeps the next SCL rise behind it. **Mutant:** `M_SHIFTIN_UC_UNHELD`.

### W4 — measured (`model/gate_sda_hold.py`, CI, iverilog, 60,000 cycles)

Layer H now reds a data move with SCL released whenever `SDA_HOLD != 0`. It
used to count those moves and leave them to the mode floor, but silicon now
promises this on every program. Layer W is new in `clocked_conform.vh`. It
reports `setup_min`: from the last data move of a low phase to the SCL release
that ends it. It also counts W1 delays as cycles where `rel_due & ~ready` while
the lane is not being served, with a per-lane maximum.

| program | d | data moves | hold min | moved with SCL released | setup min | W1 delays / cycles |
| --- | --- | --- | --- | --- | --- | --- |
| ckhold_over | 16 | 509 | 15 | **0** (was 11 of 562) | 5 | 1424 / 5746 |
| i2cframe | 16 | 647 | 15 | **0** (was 10) | 5 | 1344 / 5407 |
| i2cframe | 17 | 611 | 15 | **0** (was 3) | 5 | 1265 / 3829 |
| i2cframe | 18 | 577 | 15 | 0 | 5 | 1195 / 2418 |

The i2cframe SHIFTIN release class now holds 29..31 at d = 16, up from 14.
Setup min is 5 = SDA_SETUP + 2: the IDLE pick plus the DRIVE edge.

**How often W1 binds** on the shipped and corpus images:

| image | mode floor | W1 delays / cycles |
| --- | --- | --- |
| corpus_i2c, ckod, ckread, i2cframe (d = 62), i2caddr | passes (Fm+) | **0 / 0** |
| half, every push-pull or unclocked-SPI image | — | 0 / 0 |
| corpus_all5 | overloaded, claims none | 2 / 34 |
| ckdense, old span 22..25 | rejected | 56 / 75 (max 2 / 2 / 4 on lanes 1–3) |
| ckdense, re-spanned 20..23 (below) | rejected | 833 / 1574 (max 4 / 4 / 6 / 6) |
| ckhold_over, i2cframe d = 16..18 | rejected | above |

On every mode-legal program W1 never binds. It binds on programs that are below
every mode floor, and under the overload stress image's contention.

### W5 — must-fires (all in `gate_sda_hold`, registered in `gate_mutant_kills`)

| mutant | subject | reproduces |
| --- | --- | --- |
| `M_NO_HOLD_GATE` | ckhold_over | **11 of 562** data moves with SCL released, Layer H red |
| `M_NO_HOLD_GATE` | i2cframe d = 16 / 17 | **10 / 3**, Layer H red |
| `M_SHIFTIN_UC_UNHELD` | i2cframe d = 16 | SHIFTIN release hold **14**, Layer H red |

`M_HOLD_CLOCKED_ONLY` (ruling U) used to be caught by its setup moves. W1 removes
those in silicon (0 of 695), so its must-fire is now the run itself: clean
refuses d = 15 and the mutant runs it.

### W6 — W1 is own-lane blocking; A2 carries it as release jitter

W1 binds on `ckdense`, which is A2-admissible, under contention: d = 20..25 with
five lanes. So "it cannot bind at the mode floor" does not hold in general, and
the bound has to account for it. A loading job is picked at lateness
`j <= r_i - C`. The hold is loaded one cycle later, at the DRIVE edge, and runs
HS = 18 cycles. The lane's next job, released T_i after the loading one, is
therefore held back by at most

    J_w1(i) = max(0, HS + 1 + (r_i - C) - T_i)

`program_a2.w1_jitter` solves this by fixed point.
- **Other lanes** see it as release jitter on lane i (`BLane.N_J`): one C per
  release, up to J_w1 later. A blocked lane costs the engine nothing.
- **Lane i itself**: the delayed job is the SCL release, which loads no hold.
  The bench's A2 check bounds the gap after the high, not before it, so the
  subject keeps its base J.

**Theorem 3 (D\*) and P9.** Its premise "readiness is the timestamp arriving"
is now `rel_due` (P9, re-anchored). W1's gate is its own premise, P9w, in
`gate_j_proof_anchors`.
- **Clocked lane:** the W1-delayed job is the HIGH. The next job is rebased from
  the observed rise, so W1 cannot put two of the lane's dispatches inside `d`.
- **Unclocked frame:** the job after a delayed SCL rise is timed absolutely, so
  it can bunch by up to J_w1, which changes the per-period port demand the
  theorem counts.

W7 refuses every short frame where that happens alone (J_w1 > 0 needs roughly
`d < 19 + lag`, while the i2cframe floor is 28). Under heavy contention it is
measurable, and the **D\* sweep + live window check next in the order is where
it gets measured**. Recorded, not asserted.

That argument needs one condition: a loading job is never itself W1-delayed,
i.e. no lane runs two hold loads back to back. It is checked per lane
(`hold_profile`), and such a lane is reported unbounded rather than given a
number. No tracked image has one.

**Re-derived** (`test/clocked_a2_bounds.json`):
- At its old span (22..25), only ckdense moved (J_w1 = 10 / 9 / 8 / 7):
  - r_ours went from 10 / 13 / 16 / 16 to 16 / 16 / 16 / 16.
  - r_pyrta went to 16 / 19 / 21 / 22.
  - The measured W1 maximum per lane was 2 / 2 / 4 (within J_w1), and the
    widest post-HIGH gap past d was 4 / 7 / 8 / 4.
- Every other image has J_w1 = 0 or an unchanged r.

⛔ **That 8 broke ruling S's must-fire** (`gate_a2_program` §3). The light
budget is 8, so the heavier program no longer failed under it, and the
per-program bound was indistinguishable from one shared number. W1 takes a
lane with a pending hold out of contention at exactly the moments it used to
contend. **ckdense is re-spanned to [20, 21, 22, 23]** (U = 0.566,
d_min = D*). That was probed, not guessed: this span measures 6 / 7 / **10** / 5,
while [20, 20, 21, 21], [20, 21, 21, 22], [21, 22, 23, 24] and [20, 22, 24, 26]
all stay at or under 8. New row:
- J_w1 = 12 / 11 / 10 / 12.
- r_ours = 16 / 16 / 16 / 19 and r_pyrta = 21 / 23 / 25 / 25.
- Bench slack is 22 / 24 / 26 / 26. The widest gap holds under it and fails the
  light 8 on lane 2.
- W1 maximum is 4 / 4 / 6 / 6, within J_w1.

The §16 table above records the old span as it was. `gate_a2_program` now
reads U and J from the JSON instead of a typed "0.518".

⛔⛔ **WITHDRAWN (ruling Y-R1, §26).** This paragraph claimed pyrta_bound's
framing "charges J twice", which made pyRTA the pessimistic number on ckdense.
That claim had no witness, and TChecker refutes it. On the large-jitter
instances the D − J framing is exact on 8 of 8 lanes, and the "charge once"
framing falls below the truth on 5 of 8. The real defect was the other way
round: **our recurrence searched too few candidate offsets** and fell below the
exact worst case. The probe that "left ours unchanged" happened to sit on a
program where the missing offsets didn't bind. Ruling Z fixed the recurrence.
ckdense then turned out to be outside the model altogether: it fails 1.6a, so
it is a declared stress image (ruling DT). The numbers above are kept as they
were measured.

### W7 — the mode floor covers unclocked open-drain frames

`pe_asm.check_unclocked_floor` (called from `check_mode_floor`) reads a lane's
SCL phases from its own actions. SCL moves on `OP_SHIFT` at level 0/1 and on
`OP_LEVEL` aimed at the clock pin, and phase lengths are sums of delays. The
check judges t_LOW, t_HIGH and t_SU;DAT against UM10204 per mode. The worst case
takes the earlier dispatch of a pair as late as `r_i − C` (`lane_responses`, W1
included) and the later one on time. Held moves get W1's silicon floor
(`SDA_SETUP + 1`); direct moves get none. **The d = 16 frame is refused** as
mode-illegal (worst t_LOW 11). d = 16/17/18 floors are 30/29/28, and i2cframe
clears Fm+ from d = 28. The certified d = 62 frame and i2caddr clear Fm+ (worst
t_LOW 59). `half_image`, an unclocked open-drain bench image at low phase 24
that never claimed a mode, is now called mode-illegal by the toolchain.
**Must-fire** (in `pe_asm`'s demo): i2cframe d = 16 is rejected and names
UNCLOCKED / t_LOW / per program; d = 62 is accepted.
⚠ t_HIGH on an unclocked frame is not stretch-safe. Only a clocked park observes
the SCL rise (F1). That limitation belongs to the unclocked idiom and is
recorded, not new.
⚠ A shape that looked like a hole, and isn't one: an `OP_SHIFT` at level 1
that moves SDA and releases SCL in one dispatch. With a real clock pin, level 1
*is* the clocked SHIFT (`ck_shift = clk_real & a_lvl & OP_SHIFT`), which
alternates LOW/HIGH and holds its data. The unclocked arm only ever sees
`a_lvl = 0` when `clk_real` holds, as `pe_engine.v` already records at
`M_CK_OD_CLK_DRIVE`. The phase reader therefore treats only level-0 SHIFTs and
`OP_LEVEL` on the clock pin as unclocked SCL moves, and a lane with any clocked
action goes to the clocked floor.

## 26. Y-R, Z, DT, A — a retracted premise, a recurrence fixed, every claim inside the exact witness

### Y-R — "pyRTA double-counts jitter" is withdrawn

Ruling Y ordered pyrta_bound changed on the claim, made in §25, that its
D − J framing charges jitter twice. That claim had no witness. TChecker settles
it. On 8 lanes with jitter around half the period (`jitter_instances.LJ_*`):

- the wrapper as it stands (interferer deadline D − J) is **exact on 8 of 8**;
- the "charge once" framing (deadline D) is **below the truth on 5 of 8**, which
  makes it unsound.

The wrapper stays. `pyrta_bound.bound_charge_once` is kept only so it can be
shown failing (`gate_pyrta_jitter` arm 4). Across both probe sets, pyRTA matches
TChecker on 15 of 16 lanes and is one cycle pessimistic on the other.

### Z — our recurrence searched too few offsets

`bursty.response_time_b` evaluated r(a) only at the analysed lane's own
release offsets. Spuri's EDF analysis (INRIA RR-2772, 1996) needs every offset
where a term steps, which includes each interferer's
`kT_j + m·t_j − J_j + D_j − D_i`. Missing them under-estimates r:

| evidence | old search | fixed (Spuri step set) |
| --- | --- | --- |
| 8 queue-depth-one instances, TChecker exact | **below the truth on 7** | ≥ truth on 8 |
| 24 recorded exact verdicts (Z, LJ, Z4 ties) | — | ≥ truth on 24 |
| 6,601 no-jitter lane-instances | short of the full set on **184** | equals a dense brute-force set on all |

`model/gate_spuri_candidates.py` (CI) holds all of this, and
`model/a2/zone/run_z.py` re-runs TChecker on the records. They reproduce 24 of
24, with `ovr` unreachable throughout.

**Z4: I2C and UART-rx.** On the shipped table our fixed recurrence reads I2C 9
and UART-rx 16, against pyRTA's 7 and 15. TChecker on scaled versions of both
shapes, in both lane-index orders and under both nondeterministic and
lowest-index tie-breaks, gives 7 and 6: pyRTA's values. So ours is pessimistic
there (2 and 1 cycles), and pyRTA doesn't miss the hardware's tie rule. The
published numbers stand.

### DT — the exact witness's boundary is 1.6a, not D > T

TChecker can't adjudicate a model where a lane's job can still be pending at its
next release (`ovr` reachable). Measured against TChecker, the exact boundary is
**r_i ≤ t_i**, with r counted from the nominal release. r already contains the
lane's own jitter, so r + J would charge it twice. Equality is admissible:
- solo T = 5, r = 5 and a blocked T = 7, r = 7 both leave `ovr` unreachable;
- a blocked T = 6 lane at r = 7 reaches it.

That is condition 1.6a, which had only ever been checked on the shipped table.

- **DT-A.** 1.6a applies per program (`program_a2.queue_slot`, W1's jitter on
  every lane including the subject). `pe_asm.check_queue_slot` refuses a program
  that fails it, and `gate_admissible_images` derives a new condition, QUEUE.
  Both have must-fires.
- **DT-B.** ckdense (r far above t = 20–23 under either bound; its pyRTA-side
  W1 term nearly diverges, A8) and ckhold_over (18 against 16) are declared
  QUEUE. Every other 1.6a failure was already PORT.
- **DT-C.** Ruling S's must-fire subject is now **ckheavy**: three clocked
  open-drain lanes at d = 30/31/32 beside two busy push-pull lanes on `uo_out`.
  It is admissible (U = 0.583, d_min = D*, no PINMAP), and it fails the light
  budget of 8 on **all three** clocked lanes (widest 10/11/13) while its own
  budgets hold. `gate_a2_program` checks that the subject is admissible.
- **DT-D.** D_sched ≤ D_tol on every lane of all 35 images, asserted, with a
  must-fire.
- **DT-E.** W1 never binds in measurement on any admissible image, ckheavy
  included. ckheavy's analytic W1 term is non-zero, so the term stays.
- **DT-F.** CI's floor (ours) is ≥ pyRTA on every lane of every admissible
  program (`gate_a2_program` §1b).

### A — pyRTA primary wherever a number is published or a verdict judged

| | published (pyRTA) | ours (cross-check, asserted ≥ pyRTA) |
| --- | --- | --- |
| shipped r | {16, 12, 7, 15, 9} | {16, 12, 9, 16, 9} |
| shipped min margin (J = 1) | **11** | 9 |
| J sweep, bar 4 | clears at every J = 0…8 (12 → 4) | fails at J ≥ 6; J = 5 sits exactly at the bar |
| 2 MHz SPI-target margin, C = 2/3/4 (1.6m) | 3 / **1** / −1 | 3 / 0 / −2 |

- **A1** README's `J = 1` row reads `9 | 11` with a one-line note. Whether to
  keep the ours column is Nathan's prose call. RD1 reads the ours figure from
  the analysis ledger.
- **A2** `gate_pyrta`: pyRTA pinned as published, ours pinned as a cross-check.
  The gap set must equal the cited one (I2C +2, UART-rx +1, Z4).
- **A3** `gate_pin_subsets`: ours ≥ pyRTA on all 80 subset results. The 16
  gapped subsets each contain the Z4 shape that explains them. Must-fire: ours
  below pyRTA, and a gap no shape explains.
- **A4** `gate_j_sound`: the verdict is on pyRTA's sweep, which is recorded
  (the gate must run without pyRTA) and recomputed whenever the pin is present.
  The double-buffer pre-registration is reproduced with the search it was
  computed by, and the fixed recurrence's reading of the same configuration
  (10) is reported beside it.
- **A5** `gate_c3_requote`: the history is untouched and reproduced with the
  pre-Z search. A fixed-recurrence record sits beside it, at or below pyRTA's
  margin on every row.
- **A6** 1.6m priced on pyRTA. At C = 3 the margin is 1, so (a) "measured
  C = 2" is the only thing keeping 2 MHz closed. Under ours it is 0, where (b)
  would close it too. Both readings are recorded.
- **A7** Refusal thresholds (mode floor, 1.6a, CI QUEUE) read ours when pyRTA
  is absent. That is intended and only stricter, and the gates say so.
- **A8** W1's jitter is now computed on pyRTA's side (`w1_jitter(src=...)`) for
  every pyRTA figure, and ours keeps its own term. ckheavy: pyRTA's term is
  1/1/1 against ours 4/4/1, so its published r is 15/16/17 (budgets 16/17/18)
  and ours stays above at 18/19/17. ckdense's pyRTA-side term nearly diverges
  (36–38, r ≈ 43). It sits outside 1.6a, so nothing rests on it.
- **A9** `lane_digest.ANALYSIS_LEDGER`, a new ledger for changes to the
  analysis of an unchanged table. Its newest entry must analyse the current
  digest, and its ours figures are checked live: "our recurrence moved under Z1
  (Spuri step set); published (pyRTA) numbers unchanged; shipped
  r {16,12,7,15,9}, min margin 11; ours {16,12,9,16,9}, min margin 9
  (pessimistic, Z4)."
