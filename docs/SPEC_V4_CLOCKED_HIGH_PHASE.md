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
