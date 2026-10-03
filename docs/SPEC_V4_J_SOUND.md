# SPEC v4 — the jitter-sound pipeline

Wilson's ruling after `1fece60`, executed in order: recurrence fix → TChecker →
pyRTA → re-baseline. The headline is that **step 4 did not produce a new
published table**, and the reason is a result rather than a delay.

---

## 0. What the ruling asked, and what each step returned

| step | asked | returned |
|---|---|---|
| 1 | jitter into interference + blocking eligibility, with a must-fire | **done**; must-fire fires on 3 faces, and it was *worse* than diagnosed |
| 2 | TChecker on constructed instances with material `J` | **done**; 11 lane-instances, **0 unsound**, 9 exact, 2 pessimistic by 1 |
| 3 | pyRTA via its arrival model, option (a) or (b), labelled | **option (a)**; and a blocker I had raised was **false** |
| 4 | re-baseline, digest bump, ledger | **not done, deliberately** — the verdict is bound-dependent |

---

## 1. The recurrence fix — and the gate that should have caught it

`response_time_b` summed `min(o.N(L), o.N(a + D_i − D_j)) · C_j`: the **nominal**
arrival curve, with no `J` anywhere. Jitter entered the subject's own response
(`r = L + C + J − a`) and **nothing** in the interference a jittery lane imposes
on the others.

**It was not a generalisation gap.** The periodic form it was gated against
already had the term — `rta_spuri.w_contribution` reads
`floor((t + J_j)/T_j) + 1` and `floor((a + J_j + D_i − D_j)/T_j) + 1`. The bursty
rewrite dropped both while keeping the vocabulary.

> ⛔ **And `assert_reduces_to_periodic` — the mechanical gate whose entire job is
> to catch exactly this — passed.** Every lane it constructed took the default
> `J = 0`, and at `J = 0` the two curves are *identically equal* for every `T`,
> every `delta`, every deadline. The gate sampled thousands of points, all of
> them inside the subspace where no disagreement can exist. **An identity filter,
> sitting in the soundness checker.**

The fix is `BLane.N_J(delta) = N(delta + J)`, which at `n = 1` is Spuri's term
exactly. The gate now sweeps `J ∈ {0,1,2,3,7,11}` — **8,190 cells at `J > 0`** —
and asserts the `J > 0` cell count is non-zero, so a future refactor that drops
the jitter arm fails here instead of passing vacuously.

### The must-fire, and the face that matters

Subject carries `J = 0`; the interferer carries all the jitter. So `r_i` cannot
move through `J_i`, and any change is the interference term alone.

| | subject's `r` |
|---|---|
| `J_j = 0` | 3 |
| `J_j = 1`, **old** nominal sum | **3** ← identical: the old form was *blind* |
| `J_j = 1`, jitter-inflated | 5 |

The decisive face is the second one. The old term was not understated, it was
**absent**. A sweep found **181** such instances, so this is representative.

### Blocking eligibility: no `J`, derived not inherited

The ruling asked for jitter in the blocking filter too. Worked through, the
shipped filter `D_j > a + D_i` is **already the widest case**: deadlines are
relative to the nominal release, so a blocker admitted by jitter has nominal
release `s ∈ [−J_j, 0]` and deadline `s + D_j ∈ [D_j − J_j, D_j]` — the maximum
is at `s = 0`, the un-inflated value. Jitter adds only blockers with *earlier*
deadlines, which the filter rejects.

> ⛔ **The first probe for this was a strawman and fired falsely.** It tested
> `D_j + J_j > a + D_i` and reported **184 of 432** instances changed — which read
> as "the derivation is wrong, escalate". `D_j` is a *relative* deadline;
> `D_j + J_j` is not the absolute deadline of any job. **A late release has less
> slack, not a later deadline.** The probe was the bug. Replaced with one that
> enumerates the max from the jitter model: **0 of 432 disagree.**

---

## 2. TChecker — the foreign check

Per-job release delay, re-rolled nondeterministically in `[0, J]` at **every**
nominal release, with the deadline and the response still measured from the
nominal release.

> ⛔ **The pre-existing phase nondeterminism was not jitter coverage.** A phase
> offset is chosen once and the lane is exactly periodic forever. Release jitter
> re-rolls per job, so consecutive releases can close to `T − J` and **bunch** —
> and bunching is precisely what the inflated arrival count exists to bound.

The `J = 0` path is emitted **byte-identically**: 92 models regenerated and
diffed against the generator at `HEAD`, 0 differing. The Part-3 validated
artefact does not move.

**Results — 11 lane-instances, `ovr` unreachable on all:**

| | count |
|---|---|
| ours **exact** (== TChecker) | 9 |
| ours **larger** (safe, pessimistic) | 2 |
| ours **smaller** (unsound — forbidden) | **0** |
| **old nominal-curve sum below TChecker** | **2** ← the bug, measured |

The pessimism is named, not averaged: `J1/subject` 5 vs 4, `J3/B` 6 vs 5. Both
`+1`, both on a lane *interfered with* by a jittery lane, never on the jittery
lane itself — the inflated count rounding a partial period up to a whole job.

> ⚠ **My must-fire criterion was wrong and demanded exactness.** Spuri's
> recurrence is an **upper bound**; requiring `r_ours == r_TChecker` asks it to be
> something it never claimed to be, and would have driven a "fix" that tightened
> the bound until it broke. Corrected to the two faces that matter: the old form
> below the truth, the new form at or above it.

---

## 3. pyRTA — a retraction, and a trap

> ⛔⛔ **RETRACTED: "pyRTA's task model has no jitter parameter."** It ships
> `PeriodicWithJitter(period, jitter)` whose upper arrival curve is literally
> `ceil((delta + jitter)/period)` — Spuri's inflated release count, exactly what
> `BLane.N_J` implements. There was nothing to work around; this is **option (a)**
> of the ruling, the exact one.
>
> **How the false absence was reached:** I read the `Task` constructor, saw four
> fields, and claimed an absence about the **module**. `Periodic` is *itself* an
> arrival model occupying the first field — the jitter lives in a **sibling**, one
> import away. Same error as the two "full-tree reads" that were truncation
> artefacts: *an absence claimed from a partial read of the place it would have
> been.*

Arm 0 verifies the two curves pointwise: **1,740 points, 0 mismatches.**

### The real obstacle, which is sharper than the one retracted

pyRTA's `Deadline(D)` is relative to the **arrival**; ours to the **nominal
release**. Without jitter those coincide. With jitter they give **different EDF
priority orders** — a job nominally early but actually delayed still carries its
early deadline in our semantics, and so can outrank a job released after it.

> ⛔⛔ **The naive arm returns exactly our old bug's numbers.**
>
> | instance / lane | old (buggy) sum | pyRTA **naive** | TChecker (truth) |
> |---|---|---|---|
> | J1 / subject | 3 | **3** | 4 |
> | J3 / B | 4 | **4** | 5 |
>
> Asked the obvious way, pyRTA would have **confirmed the bug** on both lanes
> where the bug was visible. **Two engines sharing an assumption are one
> witness.** This is the arm that must not be shipped — it is kept, red, as the
> honest measure of how much the framing is doing.

### The sound construction

Per subject `k`: others get `D_j − J_j` (most urgent theirs can appear); the
subject's own delay `delta` is **swept over `[0, J_k]`** with deadline `D_k − delta`
and the answer `+ delta`, taking the max.

> ⛔⛔ **The first version double-counted and raised a false unsoundness alarm.**
> It gave the subject deadline `D_k` *and* added `J_k` — contradictory statements
> about one job: deadline `D_k` says it was *not* delayed, `+J_k` says it was
> delayed fully. The inflation landed above our own number and printed
> `*** OURS SMALLER ***` on I²C at `J_pipe = 2` and `7`. **It was the probe.**
> Corrected: at `J_pipe = 2` pyRTA gives 6 and ours 6 (exact); at `7`, 11 vs 13
> (ours pessimistic, safe side).
>
> ⛔ **Second broken probe of this work.** Both produced dramatic findings about
> the recurrence; both were bugs in the measuring instrument. In both cases what
> made the result impossible was that the probe asserted something no schedule
> does.

**Arm 2: 11 of 11 exact against TChecker, 0 below it, ours never smaller.**

**Arm 3** covers the two `m_i > 1` shipped lanes that TChecker *cannot* — its
generator refuses bursty-with-jitter — by encoding our bursty jittered curve as
an `ArrivalCurvePrefix` (21 steps, verified pointwise against `N_J`, 0
mismatches over the full 8,280-cycle horizon).

> ⚠ Those two lanes therefore carry **one** foreign witness at `J > 0` where every
> other number in this project carries two.

---

## 4. Why there is no re-baselined table

### The sweep (our bound), bar = margin ≥ 4

| `J_pipe` | `r` (5 lanes) | min margin | bar |
|---|---|---|---|
| 0 | {10,7,4,9,5} | 13 | PASS |
| 2 | {12,9,6,11,7} | **11** | PASS |
| 7 | {17,14,13,18,14} | 4 | PASS (exactly) |
| **8** | {18,15,16,19,15} | **1** | **FAIL** |

I²C is the tightest lane at every `J` — it is the only one carrying
`J_PIPE + L_JIT`. The drop from 4 to 1 between `J = 7` and `8` is **a whole
interferer job crossing into I²C's window**, not a rounding effect, so no amount
of tightening elsewhere recovers it.

### The number that was about to be published

`bursty.py` carried *"at J = 8 the set is still FEASIBLE: r = {18,15,12,17,13},
MIN MARGIN 5, which still clears the margin ≥ 4 bar"*. That was computed with the
**unsound** sum. **"Min margin 5" had already reached a commit message.** It is
kept as `gate_j_sound.py`'s face (b) must-fire, because a fix that moves a
verdict has to be able to show the number it replaced.

### ⛔⛔ But the verdict is BOUND-DEPENDENT, and my first write-up overclaimed

I wrote "the design fails its bar at the derived J". What is true is narrower:
**our bound** fails it.

| `J_pipe` | min margin, **ours** | min margin, **pyRTA** | |
|---|---|---|---|
| 2 | 11 PASS | 11 PASS | identical on all five lanes |
| 7 | 4 PASS | 6 PASS | agree |
| **8** | **1 FAIL** | **5 PASS** | ⛔ **bound-dependent** |

Both are sound upper bounds; neither is contradicted by any foreign check. And
**the tighter one has the better record against ground truth** — on the 11
instances where TChecker supplies truth, pyRTA was exact 11/11 and ours 9/11. The
bound that fails the bar is the one with the worse record.

So the honest statement is *"our bound cannot show it passes, and the looseness
is located"* — not *"the design fails"*.

### Where our looseness comes from

Read against `docs/SPURI_RR2772_EXTRACT.md` §5 p13 — **the source, not my
reconstruction**. Our recurrence is Spuri's `J = 0` form with jitter added to the
interference terms. His jitter form differs in **three** further places we do not
implement:

1. **The subject's own term.** Ours `(N_i(a) − 1)·C_i`, a plain count. His
   `delta_i(a,t)·C_i` with `s_i(a) = a + J_i − floor((a+J_i)/T_i)·T_i` —
   phase-aware, dependent on `t`, hence *inside* the fixpoint, not in the constant.
2. **The response formula.** Ours `L + C_i + J_i − a`. His
   `r_i(a) = max{J_i + C_i, L_i(a) − a}` — the subject's service is already inside
   `L_i` via `delta_i`, so adding `C_i + J_i` on top of a differently-constructed
   base is not the same quantity.
3. **The offset range.** Ours searches `a` over nominal arrivals in `[0, horizon]`.
   His is `a ∈ [−J_i, L − J_i − C_i]` — it starts **negative**, and we never
   evaluate a negative offset at all.

> ⛔ **Not adopted here, deliberately.** Replacing the subject term, the response
> formula and the offset range is a rewrite of the core recurrence that every
> number in this project rests on. It needs its own must-fire, its own TChecker
> re-validation and a digest bump — and doing it in the same breath as discovering
> that the current form fails a bar is precisely the shape of *tightening the
> bound until the verdict improves*. **Located and reported; closing it is
> Wilson's call.**

---

## 5. The double buffer — pre-registered before the RTL

Nathan's call: **yes**. Sequenced after the pipeline, per the ruling.

```
winner registration                1   stays — the EDF key is registered
prefetch scan notice               1   stays — the scan is still a cycle
own refill (P_REQ/P_WAIT/P_CAP)    3 -> 0   absorbed by the spare buffer
in-flight refill for another lane  3 -> 0   shared port leaves the dispatch path
header load                        0   unchanged
                                  ---
J_PIPE_PREDICTED                    2
```

**Falsifier:** derived `J_pipe > 2` after the RTL lands. If it fires, report it —
do not re-argue the decomposition to reach 2.

**Owed:** a buffer-swap invariant, and a **stale-buffer mutant** (dispatch from
the buffer that was *not* refilled). If the suite stays green under that
mutation, the double buffer is untested and its `J` reduction unevidenced.

> ⭐ **The pipeline strengthened the case rather than merely confirming it.** At
> `J_pipe = 2` the two bounds **agree exactly** on all five lanes. So reducing `J`
> does not just buy margin — it buys a margin that **does not depend on which
> sound bound you quote**. That is a better reason than the one it was approved
> on.

---

## 6. State

- **A2 suite 26 of 26**, base digest **unchanged** at `8ea5756203e1`.
  The fix is **inert on the published table**, because the shipped lanes carry
  `J = 0` and there is nothing for the restored term to inflate. **No digest bump
  is owed for the fix itself.**
- `gate_pyrta_jitter.py` reports `used=10b327701c7c` — the digest the `J = 8`
  re-baseline would have carried — as a **declared variant**, not as the shipped
  table.
- **`price_gates.sh` 12 of 12 red**, including two new arms that revert the fix
  itself (`BURSTY_NOMINAL_INTERFERENCE=1`) and require the must-fire to fail. Both
  the must-fire and the reduction gate go red under the revert, so the fix is
  shown **load-bearing**, not merely present.
- Two meta-checks caught my own omissions before the suite went green:
  `gate_j_sound.py` analysing an **undeclared** lane-table variant, and
  `gate_pyrta_jitter.py` **opting out** of the digest. Both now declare.

### Still owed

- **Wilson's call on Spuri's full jitter form** (§4) — it decides whether the
  design clears its bar at large `J` or whether the margin stays bound-dependent.
- **TChecker for bursty-with-jitter**, so the two `m_i > 1` lanes get a second
  witness.
- The double-buffer RTL, then the `J` re-derivation against the falsifier.
- Reverse traceability: census programs on the golden model, which also clears
  the 6 unmeasured opcodes.
