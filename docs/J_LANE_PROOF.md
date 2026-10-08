# R1 — the `J = 9` claim, proved from the RTL, and where it stops

Wilson's R1. **Claim under test:** a lane's release→dispatch wait is at most

```
remaining in-flight refill (≤ L_REFILL) + own refill (L_REFILL) + winner reg (1)  =  4 + 4 + 1  =  9
```

**Verdict up front: the claim is a theorem for the *winner-blocked* portion of
the wait, and FALSE for the release→dispatch wait as stated.** The gap is a
specific, reachable case; it is measured at **29 cycles** where the claim allows
9, and **no constant derived from `k` and `L_REFILL` bounds it** — including the
`k · L_REFILL + 1 = 21` that was this document's first repair, which the same
measurement refuted.

---

## 1. Premises, each cited

| # | premise | citation |
|---|---|---|
| P1 | **One prefetch FSM, one refill in flight engine-wide.** A single `pst`/`pl` pair; there is no per-lane fetch engine. | `src/pe_engine.v:663–665` |
| P2 | **A refill is 4 cycles and non-preemptible**: `P_SCAN → P_REQ → P_WAIT → P_CAP`, each transition unconditional once started. Nothing in the FSM returns to `P_SCAN` early. | `src/pe_engine.v:1096–1101` |
| P3 | **Winner-first strict priority.** At `P_SCAN` the port serves the current EDF winner's head whenever that head is invalid, *before* considering any other lane. | `src/pe_engine.v:1070` |
| P4 | **Spare fills are strictly lower priority** — the `else if` branch, reached only when the winner's head is already valid. | `src/pe_engine.v:1075–1082` |
| P5 | **Dispatch is gated only on the head slot.** `ST_IDLE` dispatches iff the winner's head is valid; otherwise it stalls and counts. | `src/pe_engine.v:1131, 1161` |
| P6 | **At `SPL = 2`, at most one slot per lane is owed in steady state.** Writeback invalidates the consumed head and flips the select, so the prefetched spare becomes the head and the freed slot becomes the new spare. | `src/pe_engine.v:1353, 1367` |
| P7 | **Winner registration costs 1 cycle** — the select is combinational over *registered* EDF keys, so a readiness change is reflected in `winner` one cycle later. | `src/pe_engine.v:559–577` |

`L_REFILL = 4` and `k = N_LANES = 5` throughout; `D* = k · L_REFILL = 20`.

---

## 2. What *is* proved: the winner-blocked bound

**Theorem 1.** Let lane A be the EDF winner with an invalid head, and suppose A
*remains* the winner until it dispatches. Then A's wait is at most 9 cycles.

*Proof.* By P5, A waits only for its head to become valid. By P3, at the first
`P_SCAN` after A becomes the winner the port starts A's head refill, since A is
the winner and its head is invalid; by P4 no spare fill can take that slot. The
port may be mid-refill when A becomes the winner, and by P2 that refill is
non-preemptible, so A first waits out its remainder — at most `L_REFILL = 4`
cycles. By P2 A's own refill then takes `L_REFILL = 4`. By P6 only one refill is
owed for A, so no second refill intervenes. Adding the winner-registration cycle
(P7) gives `4 + 4 + 1 = 9`. ∎

**This is the quantity `test/tb_jlane.v` measures** as `sum_L`: cycles where
`st == ST_IDLE ∧ winner_v ∧ winner == A ∧ ¬l_actv[head(A)]`, which is the
engine's own stall predicate with the winner pinned to A. Measured maximum
across both arms and all lanes: **7 ≤ 9.** ✓ Theorem 1 is consistent with the
T1 data, and the pre-registered falsifier never fired.

---

## 3. The case the ruling demanded be addressed, and it breaks the premise

Theorem 1 assumes *A remains the winner*. `winner` is combinational over all
ready lanes by absolute deadline (P7), so it can change mid-wait.
When A loses winner status to lane B, there are exactly two sub-cases:

### (b) B's head is **valid** → B dispatches

The engine enters `ST_DRIVE`/`ST_WB` and **executes** B's action: 2 cycles,
`C = 2`. This is ordinary EDF interference from a job with an earlier absolute
deadline, and **pyRTA's recurrence charges it** through B's `C_j` term in the
interference sum. It is (b), it is counted once, and it must not also be charged
to `J`.

### (a) B's head is **invalid** → nothing executes

By P3 the port now serves **B's** head, because B is the winner. The engine
stays in `ST_IDLE` for the whole of B's 4-cycle refill. During those cycles:

- **no job executes**, so pyRTA's interference sum charges **nothing** — its
  recurrence accumulates `C_j` terms, i.e. *execution*, not stall;
- **A is not the winner**, so `sum_L` skips them too.

⛔⛔ **So this class of cycle belongs to neither model.** The ruling requires it
belong to exactly one. **It is (a): it must be charged to `J`.** It is
processor-unavailability with nothing running — a blocking term — and the only
place the analysis has for it is the jitter/blocking budget.

### It is reachable, and measured

Not an argument from possibility. `tb_jlane` now counts the three classes
separately inside each release interval — `exec` (`st ≠ ST_IDLE`), `mine`
(idle, I am the winner-blocked lane), **`gap`** (idle, I am *not* the winner).

On arm A (d = 12…16, sub-`D*`), lane 1: **`gap` = 7 cycles in a single release
interval.** The case is real.

⇒ Sub-case (a) occurs precisely when two or more lanes hold invalid heads at
once, which is the definition of the port failing to keep up — i.e. `d < D*`.
At `d ≥ D*` the port serves every lane's refill within the shortest action
period, nothing is ever found missing, and the measured stall is 0 at every
port-feasible point. **The gap exists only in the regime the reopening needs.**

---


## 4. My first repair was also unsound, and measurement caught it

The obvious repair is to charge the other lanes' refills too:

> **Attempted Theorem 2.** The non-execution portion of a release→dispatch wait
> is at most `k · L_REFILL + 1 = 21`, because (P6) each lane is owed at most one
> refill, so at most `k` refills can be served between A's release and A's
> dispatch.

**This is false, and the instrument refutes it.** Measured worst full
non-execution wait: **40 cycles**, on arm C lane 4 — of which **29 is refill
queueing (RQ)** and 11 is other lanes' dispatch-decision cycles (DD).

⚠ **The 29 is the figure that matters, and the first version of this document
quoted the 40.** `gap` was a single counter until the `D*` theorem forced it to
be split: an idle cycle in which the subject is not the winner is either the
port refilling for a lane that outranks it (RQ — the uncounted term) or that
lane's dispatch-decision cycle (DD — ordinary EDF ordering). Quoting the sum
overstated the uncounted term by 11 cycles. **29 still exceeds both 9 and 21,
so nothing in the verdict moves** — but the number is now the right number.

```
arm C (d = 8, 100, 100, 100, 100)      gap   FULL   wall
  lane 0  (earliest deadline)            0      7      7
  lane 1                                 4      4      7
  lane 2                                 8      8     15
  lane 3                                12     12     23
  lane 4  (latest deadline)             40     40     63
```

⛔ **The error in the proof, precisely: P6 bounds the refills owed at one
INSTANT, not over an interval.** Lane 4 waits a long time; during that wait
lane 0 (d = 8) *dispatches repeatedly*, and **every dispatch invalidates a head
and owes a fresh refill** (P6a). Seven of lane 0's refills were served while lane
4 waited: 7 × `L_REFILL` = 28, with one cycle of scan overhead — RQ = 29. Nothing in P1–P7 limits how many times a faster
lane may come round.

⭐ And the shape of the data says so without the argument: `gap` is **4, 8, 12,
40** across arm C's lanes in exact EDF deadline order. It is not a constant
being approached — it is a queue, and the lane at the back of it waits longest.

⚠ **This is the same failure as the retracted universal `J = 8`**, one step
further up: a constant assembled from `k` and `L_REFILL` that looked structural
and was not. It was caught here only because the measurement was taken before
the document was committed.

## 5. What the delay actually is

The non-execution wait is a **queueing delay at the single fetch port** — a
second scheduling problem nested inside the EDF one. Bounding it needs a
response-time analysis *of the port*, with each lane's refill demand as a task,
and no constant derived from `k` and `L_REFILL` can stand in for that.

Note arm C is **not** port-saturated: `U_port = 4/8 + 4·(4/100) = 0.66`. The
queue is finite, and still 40 cycles deep for the lane at the back. So this is
not an overload artefact — it is ordinary queueing, which is exactly why
`U_port ≤ 1` was falsified as a sufficient condition earlier.

⭐⭐ **And this is what `D*` is.** `d ≥ D* = k · L_REFILL` is the condition that
the port can serve *every* live lane's refill within the shortest action period
— so at or above it no lane ever finds its head missing, the queue is empty at
the moment of need, and the delay is zero rather than bounded. That is why the
measured steady stall is **0 at every port-feasible point** and why the scoped
claim needs no jitter term beyond winner registration.

⇒ `D*` is not a conservative margin applied to a feasible region. **It is the
boundary at which this term vanishes**, and below it the term is not a constant
at all.

## 6. The falsifier, as pre-stated

> Any path in the RTL giving a wait greater than the stated bound.

**It fired twice.**

1. Against the claim as written (≤ 9): §3(a), a waiting lane losing winner
   status to a lane whose head is also invalid. Measured RQ = 8 on arm A and **29** on arm C — above 9.
2. Against the repair (≤ 21): the same path iterated, because a faster lane
   re-earns winner status and owes a new refill each time. Measured RQ = 29 > 21.

Theorem 1 (the winner-blocked subset ≤ 9) survived both: measured maximum **7**,
and the pre-registered falsifier `sum_L > 9` fired on **0 of 10 cells**.

## 7. Verdict

| statement | status |
|---|---|
| `sum_L ≤ 9` — the winner-blocked wait (Theorem 1) | **holds**, cited to the RTL, measured 7 |
| release→dispatch wait `≤ 9` (the claim under test) | **FALSE** — RQ measured 29 |
| release→dispatch non-execution wait `≤ k·L_REFILL + 1 = 21` | **FALSE** — RQ measured 29 |
| a universal constant bound below `D*` | **none exists** from P1–P7 |

The ruling's dichotomy is answered: the winner-loss delay splits, with the
interfering lane's **execution** as (b), charged by pyRTA through `C_j`, and its
**refill** as (a), which must be charged to `J`. Exactly one each. But (a) is
**not bounded by a constant** below `D*`, so there is no `J` to charge.

**R1 does not deliver `J = 9` as a theorem, and no fixed `J` is available for
`d_min < D*`. Per the ruling, the reopening does not proceed, and the failing
check is named: §3(a) iterated — the unmodelled refill queueing of
earlier-deadline lanes, measured at 29 cycles where the claim allowed 9.**

⚠ **`J = 9` is still a sound figure for what it describes** — the winner-blocked
stall — and the T1 record stands. It is simply not the quantity a response-time
analysis needs.

What would reopen the question: a **response-time analysis of the fetch port**
itself, giving a per-program bound on the refill queueing delay. That is a real
piece of work and a genuine result if it lands; it is not a number to be read
off the measurement. Until then `d_min ≥ D*` is the only region with a sound
timing claim, and `pe_asm`'s refusal below it is correct for the reason it
gives.

---

# Theorem 3 — the `D*` theorem

> ⛔⛔ **STATUS (Ruling TH1): proof gap identified.** The utilisation argument
> is insufficient, and the deadline is tied to the wrong release and slot.
> The **statement** is supported by measurement. A formal proof is in
> progress (Lean). The proof below is kept as written so the gap can be
> audited against it. See **Amendment A2** for what is wrong with it, and
> `docs/PORT_SPEC.md` for the RTL facts a repaired proof has to use.

**This is now the load-bearing claim.** The published guarantee is
`d_min ≥ D* = k · L_REFILL = 20  →  J = 1`, and §4–§5 showed what it actually
rests on: that the **uncounted refill-queueing term is zero above `D*`**, not
merely bounded. That deserves the same treatment `J = 9` just got.

## Premises (additional to P1–P7)

| # | premise | citation |
|---|---|---|
| P8 | **A lane's period is exactly its action delay `d`.** The timestamp advances **absolutely** — `l_timestamp[cur] <= l_timestamp[cur] + a_dly` — not from completion, so consecutive releases of a lane are `d` apart with no drift. | `src/pe_engine.v:1278` |
| P9 | **Readiness is that timestamp arriving.** `ready` tests `now - l_timestamp`, so a lane is released at its timestamp and not before. | `src/pe_engine.v` — the `g_ready` generate |
| P10 | **At `SPL = 2` the dispatched slot is the HEAD and the refill owed is for the SPARE.** Writeback invalidates the consumed head and flips the select, so the already-prefetched spare becomes the head and the freed slot becomes the new spare. **⚠ AMENDED 2026-10-05 — see Amendment A1:** a *retiring* dispatch owes one refill; a clocked SHIFT's **re-dispatch retires nothing and owes none**. Read as "**at most** one". | `src/pe_engine.v:1353, 1367` (= P6) |

## Statement

> **Theorem 3.** In steady state, for a program whose minimum action delay
> satisfies `d_min ≥ D* = k · L_REFILL`, every lane's head slot is valid at
> every release. Hence no lane is ever winner-blocked, and the refill-queueing
> term `RQ` — idle cycles spent refilling for a lane that outranks the subject
> — is **zero**.

*Proof.* By P10 a dispatch consumes a valid head and leaves **at most one** slot
per lane to be refilled *(amended 2026-10-05 from "exactly one" — see Amendment
A1; the bound is preserved because demand only decreases)*, and by P8/P9 a lane
dispatches at most once per `d`
cycles. So in any window of `d` cycles the port is asked for at most `k`
refills, one per live lane, each costing `L_REFILL` by P2 — a demand of
`k · L_REFILL` cycles of port time per `d` cycles of wall time. When
`d ≥ k · L_REFILL = D*` that demand is at most the capacity, so every refill
issued at a lane's writeback completes before that lane's next release.

A head is therefore never found invalid at a release. By P5 dispatch is gated
only on the head, so no lane ever stalls (`sum = 0`); and since `RQ` counts
idle cycles in which **the winner's head is invalid**, and no head is ever
invalid, `RQ = 0`. ∎

⭐ **Why no extra `L_REFILL` term for speculative spare fills.** By P4 a spare
fill only starts when the current winner's head is already valid, and by P10
the spare fill *is* the one unit of work this argument counts per lane per
period — it is not additional traffic competing with head refills. Above `D*`
there are no head refills to compete with, which is the content of the theorem.

⚠ **Steady state is part of the statement, not a hedge.** On a lane's *first*
action both slots are empty by construction, so a head *is* invalid and the
cold start is a different regime — `tb_smoke` reports cold and steady
separately for exactly this reason, and whether the cold start belongs in the
published `J` is a separate open ruling.

## Check — and it is a check, not the proof

`test/run_dstar_check.py`. Per-lane `RQ` at the **seven port-feasible points**
`price_j_sweep.sh` measures (d = 20, 21, 22, 25, 30, 40, 60) × five lanes, plus
**two controls below `D*`** (d = 12, 18) which must come out **non-zero** — a
gate that only ever looks above the threshold cannot show the threshold is
where anything happens.

⛔ **The quantity is `RQ`, not `gap`.** The first spot check at d = 20 read
`gap` = 1…3 with the stall at zero, which looks like a nonzero refill wait
above `D*` and **would have falsified a true claim**. It is `DD` — other lanes'
dispatch-decision cycles — and it rises **1, 1, 2, 3, 3** across the lanes in
exact EDF deadline order. Ordering, not refill. The split exists because a gate
that asserts the wrong quantity refutes the thing it was built to confirm.

## Falsifier, pre-stated

> Any program with `d_min ≥ D*` and a nonzero per-lane refill wait.

## Flagged while proving this, and queued rather than acted on

P8 says a lane's period is exactly `d`. But
`model/a2/gate_j_program.py:231` computes `utilisation(d) = k·C/(d + C)` — a
period of `d + C`. On the RTL's absolute timestamp advance the period is `d`,
so that denominator looks optimistic; and separately, the dispatch FSM is a
**three**-state cycle (`ST_IDLE → ST_DRIVE → ST_WB → ST_IDLE`, the exit from
`ST_WB` unconditional), so the engine cannot dispatch two actions less than
**3** cycles apart while `C = 2` counts only the two busy ones.

⚠ **Both would tighten the `admissible` floor — `k·3/d ≤ 1` gives `d ≥ 15`
rather than `d ≥ 8` — and neither changes the published claim**, because
`D* = 20` dominates and the whole affected band `[8, 19]` is already refused.
Per the interrupt rule this **queues**: it does not change the descriptor. It
is recorded here because `gate_j_program`'s 1.6t table currently prints
`adm (U≤1) = yes` for d = 8, 10, 12 and 18, which on this reading is an
optimistic label — inside a region nothing is claimed for, but a label is still
a statement. **Not changed without a ruling**, since `admissible` feeds the A2
suite.

---

# Amendments

## A1 — "exactly one refill" becomes "at most one" (2026-10-05)

**Ruled** alongside the clocked SHIFT/SHIFTIN build. A versioned amendment, not
a silent edit: the original wording is quoted here so the change is auditable
against any published copy.

**What changed.** Two places, both marked inline:

| where | was | is |
|---|---|---|
| P10 | "the refill owed is for the SPARE" | unchanged, **plus**: a re-dispatch retires nothing and owes **no** refill |
| Theorem 3 proof, the line beginning *"By P10 a dispatch consumes…"* | "leaves **exactly one** slot per lane to be refilled" | "leaves **at most one** slot per lane to be refilled" |

**Why.** Under the clocked SHIFT, when `l_clkpin` is real a single action is
**re-dispatched** — odd phase drives data and takes the clock low, even phase
releases it high, the bit pointer advancing on the low phase only. A
re-dispatch performs no writeback-retire and no store read, so it **leaves zero
slots to be refilled**. "Exactly one" is therefore false under the new scheme,
and was true before only because *one action had always equalled one dispatch*.

**Why the bound survives — and this is the whole reason the amendment is
bookkeeping rather than a re-proof.** The premise is used at exactly one step:
to conclude that *"in any window of `d` cycles the port is asked for at most `k`
refills"*. That step needs an **upper** bound on refills owed per dispatch. A
re-dispatch owes **fewer** (zero), never more. So weakening "exactly" to "at
most" preserves every inequality downstream, and `D* = k · L_REFILL = 20` is
unchanged. ⛔ Had the clocked scheme made a dispatch owe *more* than one refill,
this would have been a re-proof and a re-quote, not an amendment.

### Every other "exactly" in this document, checked for the same dependency

The ruling required the whole proof swept, not just the one line. Eight
occurrences; the verdicts:

| line | text | depends on refills-per-dispatch? |
|---|---|---|
| §3 | "there are **exactly two** sub-cases" | **No.** A dichotomy on whether B's head is valid. Exhaustive however many refills a dispatch owes. |
| §3(a) | "must belong to **exactly one**" | **No.** The ruling's requirement that a cycle class be charged to one model, not a count of refills. |
| §4 | "which is **exactly** why" | **No.** Rhetorical. |
| P8 | "a lane's period is **exactly** its action delay `d`" | **No, but see below.** |
| Thm 3 proof | "leaves **exactly one** slot" | **YES — amended above.** |
| §5 | "separately for **exactly** this reason" | **No.** Rhetorical. |
| queued note | "P8 says a lane's period is **exactly** `d`" | **No.** Quotes P8 inside the already-queued `utilisation(d)` finding. |

### P8 is literally unchanged, and the reason is worth recording

`l_timestamp[cur] <= l_timestamp[cur] + a_dly` fires in **`ST_WB`**, i.e. on
**every** dispatch — `src/pe_engine.v:1511`. A clocked re-dispatch is an
ordinary dispatch through `ST_IDLE → ST_DRIVE → ST_WB`, so it advances the
timestamp like any other. Consecutive **releases** therefore remain `d` apart
and P8 stays true as written.

⚠ **But the identity it was written under is gone.** P8 and P10 were both
written when *one action = one dispatch*, which made "period of a release" and
"period of an action" the same quantity. Under the clocked SHIFT an action
spans **16** dispatches (8 bits × 2 phases), so:

- a lane's **release** period is `d` — P8, unchanged;
- a lane's **action** period is `16 d` — a new quantity the proof never needed
  a name for.

Anything that silently reads P8 as "a lane completes an action every `d`
cycles" is wrong under the clocked scheme. Nothing in this proof does — every
use is about releases — but the distinction is now load-bearing and is recorded
here rather than left to be rediscovered.

## A2 — Theorem 3's proof is unsound as written (Ruling TH1, 2026-10-07)

**Ruled:** the red-team is accepted. The proof is unsound as written. The
**statement is not refuted**: every measurement below is consistent with it.
The proof text above is left unedited so this amendment can be checked
against it.

### Defect 1: the utilisation argument is insufficient

The proof reasons that the port is asked for `k · L_REFILL` cycles of work
per `d` cycles, so when `d ≥ D*` demand fits capacity and "every refill
issued at a lane's writeback completes before that lane's next release".
The last step does not follow. Demand fitting capacity over a window is a
**utilisation** condition. Whether one particular owed refill meets its
deadline depends on the **order** in which the port serves refills, and the
proof never uses the order.

**This document had already measured the counterexample to the inference.**
§5 shows arm C has `U_port = 0.66` and still builds a 40-cycle queue. It
records that `U_port ≤ 1` was falsified as a sufficient condition.

The order is in `docs/PORT_SPEC.md` §1:
- the winner's head is served first;
- every other owed refill is served round-robin, by the position of the scan
  pointer;
- and every winner-head refill relocates that pointer.

### Defect 2: the deadline is tied to the wrong release and slot

The proof gives the refill owed at `WB(j)` the deadline *"before that lane's
next release"*, which is `j + 1`. But the slot freed at `WB(j)` refills with
job **`j + 2`**'s action. Job `j + 1` is served from the other slot, which
became the head at the swap. So the refill owed at `WB(j)` is needed at
**`decision(j + 2)`** (`PORT_SPEC.md` §4).

The event the conclusion needs is different: the head valid at `release(j + 1)`.
That is a fact about the refill owed at **`WB(j − 1)`**. The proof's chain
therefore checks one event and concludes about another. The correct slack is
`decision(j + 2) − WB(j) ≥ 2d − R_i − 2`, where `R_i` is the lane's release →
decision time. That term couples the port invariant to the EDF response
time, and the proof does not mention it.

### What the statement now rests on: measurement (TH3)

Probe `probe_tb_port.v` follows every slot from free to issue to capture, and
attributes every stall cycle to a cause.

- **Arms covered:**
  - the seven port-feasible points (d = 20, 21, 22, 25, 30, 40, 60, each
    `d..d+4`);
  - the 16 admissible images with the `uio` read-back model. 12 of them owe
    refills inside the window. `ckdegen`, `ckdegen2`, `ckhold_at` and
    `ckhold_under` owe none after warm-up, so they exercise nothing here;
  - adversarial arms with lanes 0–3 at the minimum delay and lane 4 slower,
    each run at 200k, 1M and 4M cycles.
- **Above `D*`:**
  - **0 stall cycles** of any cause on every arm.
  - The winner-head branch fires **once** per run, for the cold-start fill,
    and never again. The port is pure round-robin.
  - Worst owed fill: **19** cycles to issue and **23** to capture. At most
    **5** refills were captured ahead of one owed fill: the in-flight one
    plus one per other lane.
  - The adversarial arms' worst wait is **identical at 200k, 1M and 4M
    cycles**. It does not grow with run length, so there is no starvation.
- **Below `D*` (the d = 18 control and arm C):** every stall cycle in the
  measured window is **arbitration**: 204,371 of 204,371 at d = 18 and
  391,955 of 391,955 on arm C. **None** is pipeline latency (a refill issued
  at the first scan that still lands late), and **none** is cold start.
  - The winner-head branch fires 49,919 and 124,982 times respectively.
    Below `D*` the port is not round-robin, because branch 1 keeps
    relocating the pointer.
- **⛔ Below `D*` the arbitration is not starvation-free (measured).** Arm
  `12, 12, 12, 12, 100` was run at 200k, 1M and 4M cycles:
  - lane 1's owed spare waited **16,468 cycles** to issue, with **2,473**
    refills served ahead of it;
  - lane 4's worst wait grew from **35** to **202** cycles between the 1M and
    4M runs.

  The mechanism is branch 1: every winner-head refill moves the pointer to
  `winner + 1`, so a lane can be passed over indefinitely. `pe_asm` refuses
  this region, and TH3c's bug condition (growth at `d_min = 20`) did **not**
  fire. But it means the round-robin bound is **conditional on branch 1
  staying silent**. A repaired proof must establish that silence by the
  induction, not assume it.

### What a repaired proof needs

`PORT_SPEC.md` §6 states the shape. It is an induction over owed refills:
1. While every owed refill lands before its slack, no head is invalid, so
   branch 1 never fires and the scan is round-robin.
2. Under round-robin, an owed fill waits behind at most:
   - the in-flight remainder;
   - one refill per other lane;
   - one scan cycle per lane passed over.
3. That wait must fit inside `2d − R_i − 2`.

The constant and the treatment of `R_i` are for the formal proof to fix. This
amendment does not supply them.

**PS1–PS3 (2026-10-07), details in `PORT_SPEC.md` §6:**
- The candidate boundary `2d ≥ 37` (`d ≥ 19`) is falsified: five lanes at
  `d = 19` stall. `D* = k · L_REFILL` is a throughput floor, and a repaired
  statement needs both throughput and latency.
- Lemma B's 23 is measured at 24 above `D*`.
- Lemma A's premise (same-lane gaps > 12) is false on `ckheavy` (gap 12),
  even though its `R_i ≤ 12` held on every stall-free arm.

**Claim status (README via RD1):** `d_min ≥ D* = 20 → J = 1` is carried as
**MEASURED**, with "written proof under revision", not as proved.
`gate_j_proof_anchors` keeps premises P1–P10, because they are RTL facts and
the red-team did not touch them.

## A3 — Ruling TF changes P3, P4, P7 and P9 (2026-10-07)

The 50 MHz timing fix changed four premises. The anchors in
`gate_j_proof_anchors.py` were updated with the RTL, and `PORT_SPEC.md` §0
has the details.

| premise | was | is |
|---|---|---|
| P3 | the port serves the **same-cycle** EDF winner's invalid head first | it serves the **previous cycle's** winner (`winner_q`), re-checked live. A winner's head refill starts **one cycle later** |
| P4 | spare fills at the pointer `pl`, and a winner-first refill **moved the pointer** to `winner + 1` | spare fills at the pointer `prr`. A winner-first refill **does not move it** (P4r) |
| P7 | the select is a serial loop over combinational keys | a tree, **proved equal** to the loop (`formal/argmin_equiv.sby`), over **registered** keys |
| P9 / P9w | `rel_due` and `ready` were combinational over `now`, `l_timestamp` and `l_hcnt` | the same values, held in registers computed from next-state inputs (P9t, P9h). The streams are byte-identical on every shipped admissible image (`test/run_lockstep.py`). Since TF2-R3 the whole release term, `l_live` and the armed/no-timeout guard included, is the one register `rel_q` |
| P5 (TF2-R) | dispatch tested `l_actv[hix[winner]]` | it tests `w_hv`, the one-hot pick of per-lane `hv[i] = l_actv[hix[i]]`. The same bit (P5h; the one-hot/binary equality is proved in `formal/argmin_equiv.sby`) |

### Theorem 1 is affected, and the measurement shows it

Theorem 1's arithmetic is `4 + 4 + 1 = 9`. It assumed the port starts the
winner's head refill at the first `P_SCAN` after the lane becomes the winner.
Under the new P3 the refill starts one cycle later. **The derivation as
written no longer covers the RTL.** Re-derived with `winner_q`, the bound is
expected to be `10`. That is for the formal proof to fix, not this amendment.

`test/run_jlane.py` on the TF RTL (1M cycles, arms A and C):
- arm A (`d = 12..16`): worst `sum_L` is **9** on lane 4 (8 on lanes 0–3).
  It was **7** on the pre-TF RTL. The pre-registered falsifier (`sum > 9`)
  did **not** fire, but the margin is now **zero**.
- arm C (`8, 100, 100, 100, 100`): `sum_L` is 8 on lane 0 and 0 elsewhere.
  Lane 4's refill-queueing gap **fell from 40 to 4**, which is the TF3
  pointer fix.

Both arms are below `D*`, a region `pe_asm` refuses. **No published claim
moves.** Theorem 3's statement is unaffected: above `D*`, branch 1 fires only
during priming, before and after TF.

## A4 — Ruling W: Theorem 3 on the bench, and three corrections (2026-10-08)

`test/tb_w.v` checks Theorem 3's **conclusion** per lane: every freed slot is
valid before the decision that consumes it. A violation is a decision that
finds its head slot invalid. The full sweep is
`python test/run_w_sweep.py --full`, and its record `model/a2/sweep_w.json`
is checked by `gate_j_program` (stale if the RTL changes). A live subset runs
in CI.

**Result on the TF RTL (`18f2c0e`):**
- **0 violations on all 56 arms with every lane at `d ≥ 20`**, at 1M cycles,
  and on all 12 shipped admissible images at 200k.
  - The arm families at each `d`: uniform; `d..d+4`; four at `d` plus
    `d+4`; alternating `d, d+4`; four at `d` plus 100 or 1000; `d..d+3`
    plus 100 or 1000.
  - Minimum slack is 15 at `d = 20`. On the images it is 21 (`ckheavy`).
- **The must-fires are red:** `d = 18` (uniform and `18..22`), and a mutant
  that idles the port `L_REFILL` cycles after every refill, at `d = 20`.
- **`d = 19`:** `19..23` and `19..22, 100` are clean (slack 8 and 13);
  uniform 19 and `19 19 19 19 23` stall. **The published boundary stays
  `D* = 20`.** `d = 19` is "measured clean on some recipes; candidate bound
  `2d ≥ 37`; not claimed until the formal proof closes."

**F1. A lane can owe BOTH slots at once above `D*`.** This happens at
`d = 20` and `21` on the `d..d+4`, alternating and drift families. Nothing
stalls: the second refill waits one more round-robin pass (`PORT_SPEC.md`
§4). It is ≤ 1 at `d ≥ 22` and on every image. **⇒ The proof must allow up
to `SPL = 2` owed slots per lane**, and bound the doubly-owed lane's second
refill by a second pass. An invariant "at most one owed slot" is false.

**F2. Lemma A's bound is tight.** The worst `R_i` is exactly 12 =
`(k − 1)·C` on every stall-free arm, at every `d`.

**F3. Lemma A's premise fails on an admissible image.** The premise is
"every same-lane dispatch gap > 12". On `ckheavy`, lane 4 has a minimum gap
of **12**, with 10 gaps ≤ 13. Its measured `R_i` is still ≤ 12.
- **Ruling:** generalise Lemma A to count a dense lane's extra jobs in the
  window, which is the formal proof's work. `ckheavy` is not refused.
- **Until that proof closes, `ckheavy`'s timing is covered by measurement
  only.**

**Premises the repaired Theorem 3 needs, stated explicitly:**

| # | premise | status |
|---|---|---|
| T1 | throughput: every lane's `d ≥ D* = k · L_REFILL = 20` | `pe_asm` refuses below it |
| T2 | latency: an owed refill's wait fits inside `2d − R_i − 2` | candidate `2d ≥ 37`; necessary, not sufficient (PS1) |
| T3 | Lemma A: `R_i ≤ (k − 1)·C = 12` | tight (F2). Its gap premise fails on `ckheavy` (F3); generalisation owed |
| T4 | at most `SPL = 2` owed slots per lane, the second served within a second pass | F1 |
| T5 | P1–P10, as amended by A1 and A3 | RTL facts, anchored in `gate_j_proof_anchors` |

**Step 1 of the repair shape needs one change.** On the TF RTL, "branch 1
fired" is not evidence of a stall: at `d = 19` it fires with none
(`PORT_SPEC.md` §6). Above `D*` it fires once, at cold start, on every arm
and image, so step 1 holds there as measured. The induction must not use a
branch-1 fire as its stall signal.
