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
