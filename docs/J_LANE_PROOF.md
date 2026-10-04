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

**This is now the load-bearing claim.** The published guarantee is
`d_min ≥ D* = k · L_REFILL = 20  →  J = 1`, and §4–§5 showed what it actually
rests on: that the **uncounted refill-queueing term is zero above `D*`**, not
merely bounded. That deserves the same treatment `J = 9` just got.

## Premises (additional to P1–P7)

| # | premise | citation |
|---|---|---|
| P8 | **A lane's period is exactly its action delay `d`.** The timestamp advances **absolutely** — `l_timestamp[cur] <= l_timestamp[cur] + a_dly` — not from completion, so consecutive releases of a lane are `d` apart with no drift. | `src/pe_engine.v:1278` |
| P9 | **Readiness is that timestamp arriving.** `ready` tests `now - l_timestamp`, so a lane is released at its timestamp and not before. | `src/pe_engine.v` — the `g_ready` generate |
| P10 | **At `SPL = 2` the dispatched slot is the HEAD and the refill owed is for the SPARE.** Writeback invalidates the consumed head and flips the select, so the already-prefetched spare becomes the head and the freed slot becomes the new spare. | `src/pe_engine.v:1353, 1367` (= P6) |

## Statement

> **Theorem 3.** In steady state, for a program whose minimum action delay
> satisfies `d_min ≥ D* = k · L_REFILL`, every lane's head slot is valid at
> every release. Hence no lane is ever winner-blocked, and the refill-queueing
> term `RQ` — idle cycles spent refilling for a lane that outranks the subject
> — is **zero**.

*Proof.* By P10 a dispatch consumes a valid head and leaves exactly one slot
per lane to be refilled, and by P8/P9 a lane dispatches at most once per `d`
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
