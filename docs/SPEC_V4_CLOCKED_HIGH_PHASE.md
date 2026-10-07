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
