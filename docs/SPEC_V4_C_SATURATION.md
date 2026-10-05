# C UNDER SATURATION — the round's record

**Ruling (Wilson), after `e8435cd`:** the dispatch FSM is a three-state cycle
while the analysis charges `C = 2`; measure the inter-dispatch spacing before
T5.1, because published-number soundness outranks new features. And fix the
1.6t table's `adm = yes` labels either way.

**Result: the falsifier fired. `C = 3`.** The shipped minimum margin moves
`12 → 11` and nothing we ship becomes infeasible.

| | |
|---|---|
| pre-registration | [`PREREG_C_SAT.md`](PREREG_C_SAT.md), committed alone at `2bdc109` |
| instrument | [`test/tb_csat.v`](../test/tb_csat.v), [`test/run_csat.py`](../test/run_csat.py) |
| re-quote | [`model/a2/gate_c3_requote.py`](../model/a2/gate_c3_requote.py), in `run_a2.py` |
| 1.6t fix | [`model/a2/gate_j_program.py`](../model/a2/gate_j_program.py), in CI |

---

## 1. The measurement

| arm | lanes | `btbmin` | `dmin` | `dmax` | `btb` | `ndisp` | role |
|---|---|---|---|---|---|---|---|
| **S** | `40 ×5` | **3** | 3 | 28 | 17,992 | 22,490 | the measurement |
| **T** | `60 ×5` | **3** | 3 | 48 | 11,994 | 14,993 | slack control |
| U | `2 ×5` | 3 | 3 | 32,772 | 58 | 22,335 | oversubscribed |
| V | shipped | 3 | 3 | 20 | 2,633 | 15,878 | the shipped program |

**`btbmin` is the deciding number, not `dmin`.** It is the minimum spacing over
pairs whose predecessor had a successor *already eligible* during its `ST_WB`
cycle — another live lane, ready, unarmed, head valid. Without that scoping, a
reading of 3 would only say the lanes arrived 3 apart. Across the four arms
**32,677** spacings had that opportunity and **not one was 2**.

Arm S's histogram is two values wide, and that *is* the structure: spacing 3
occurs 2,792 times, spacing ≥ 15 occurs 697 times — 697 bursts of five
simultaneous releases, four in-burst spacings each, then idle. `P8`'s absolute
timestamp advance is what keeps five equal-delay lanes phase-aligned forever,
which is what makes the burst reproducible rather than incidental.

**The controls did their jobs.** S and T agree exactly, so the floor is the FSM
and not the fetch port. U cannot beat it. And arm V is *stronger than it was
scoped for*: the shipped program has 2,633 back-to-back spacings with a minimum
of 3, so the floor is exercised by what we ship, not only by a synthetic burst.

### 1.1 Why the figure on record missed it

`svc_cycles / svc_jobs = 688 / 344 = 2.00` counts cycles where
`st != ST_IDLE` — the engine's **occupancy** per job. `ST_WB` assigns
`st <= ST_IDLE` unconditionally, so the next dispatch decision cannot be taken
until the cycle after writeback.

**Occupancy is 2 and spacing is 3, both exactly.** The mean was the correct
answer to the question it was asked. `C` in a response-time analysis is the
resource time a job denies to every other job, and that is the spacing.

⛔ **How it survived: the two readings agreed.** A structural derivation ("two
states, so `C = 2`") and a simulation mean (`2.00`) confirmed each other — and
both were about occupancy. Agreement between two measurements of the same wrong
quantity is not corroboration. That is this project's own standing rule, met
again in a new place.

---

## 2. What moves

### 2.1 The shipped table — both bounds agree exactly

| lane | `D_tol` | `r` at C=2 | `r` at C=3 | margin C=2 | margin C=3 |
|---|---|---|---|---|---|
| UART-tx 115200 | 216 | 11 | 16 | 207 | 203 |
| SPI-tx 1 MHz | 23 | 8 | 12 | 17 | 14 |
| **I2C 400 kHz** | 15 | 5 | 7 | **12** | **11** |
| UART-rx 115200 | 213 | 10 | 15 | 205 | 201 |
| SPI-target 1 MHz | 18 | 6 | 9 | 14 | 12 |

Minimum margin **12 → 11**, against a pre-registered bar of 4. `B = max(C_j − 1)`
is **2**, not 1. pyRTA is primary and ours equals it on all five lanes at both
service times, so the direction check (ours ≥ pyRTA) holds.

### 2.2 The J sweep — and a claim this round does **not** make

| `J_pipe` | pyRTA C=2 | pyRTA C=3 | ours C=2 | ours C=3 |
|---|---|---|---|---|
| 0 | 13 | 12 | 13 | 12 |
| **1** (shipped) | **12** | **11** | 12 | 11 |
| 2 | 11 | 10 | 11 | 10 |
| 3 | 10 | 9 | 8 | 6 |
| 5 | 8 | 7 | 6 | 4 |
| 7 | 6 | 5 | 4 | 2 |
| 8 (derived `J_max`) | 5 | **4** | 1 | **−2** |

⛔ **The first draft of the re-quote gate published a finding it had to
retract.** It tabled only *our* recurrence and concluded "the bar crossing
moves from J = 7 to J = 5" and "the derived `J_max = 8` becomes INFEASIBLE at
margin −2". pyRTA is the primary bound and says neither: it clears the bar at
every swept `J` at both service times, and has the derived `J = 8` at **+4**,
exactly the bar. Ours is the conservative side — which is why it is kept, and
why it must never be the number quoted. **The bar crossing does not move.**

The two bounds agree exactly for `J ≤ 2` and diverge from `J = 3` upward, so
the shipped design point (`J = 1`) sits well inside the band where the published
figures do not depend on which bound is used.

⭐ What the `J = 8` row does say: its slack is now **zero above the bar** on the
primary bound and negative on the cross-check. Nothing admitted can reach it —
the `D*` screen refuses every program with `d_min < D*` and `J = 1` is derived
above it — but it has stopped being a comfortable fallback. **That makes the
`D*` screen load-bearing for feasibility, not merely for the size of a bound**,
which is a stronger reason to keep it than the one it was adopted for.

### 2.3 What does **not** move, and was not re-derived to compensate

Pre-registered in §5.2.5 before the number was known:

- **`D* = k · L_REFILL = 20` contains no `C`.** It is a port-throughput
  threshold; Theorem 3's premises (`gate_j_proof_anchors` P8/P9) are untouched.
- **`d_min ≥ D* → J = 1` is a jitter claim.** Unaffected. If `C = 3` had made a
  lane infeasible, that would have been a *margin* finding.
- `L_REFILL = 4`, `L_CAP = 7`, `J_WINNER_REG = 1` are refill-FSM and
  winner-registration structure. Unaffected.
- The refill-window `+ C` inside `j_stall` keeps the **occupancy** figure, and
  that is a decision with a direction: a larger `C` makes the shortfall smaller
  and the derived bound *weaker*, so 2 is the conservative choice for a bound
  that is already retracted. Re-deriving it is owed.

---

## 3. The 1.6t table — owed either way, and it compounded

```python
def utilisation(d, k):  return k * C_SVC / float(d + C_SVC)   # WRONG
```

**`d + C` is not a period.** `P8` advances a lane's timestamp from the previous
timestamp, absolutely, so a lane releases every `d` cycles however long its job
took. Dividing by `d + C` credited the system with a longer period than any lane
has — optimistic.

The two corrections compound: `d + C → d` alone moves the admissible floor from
`d ≥ 8` to `d ≥ 10`; with the measured `C` it is **`d ≥ k·C = 15`**.

| `d_min` | `adm` as published | `adm` corrected | loader verdict |
|---|---|---|---|
| 8 | yes | **NO** | REFUSED — U > 1 |
| 10 | yes | **NO** | REFUSED — U > 1 |
| 12 | yes | **NO** | REFUSED — U > 1 |
| 18 | yes | yes | REFUSED — admissible but `d < D*` |
| 25 | yes | yes | J = 1 (shipped) |

All four false labels Wilson named are gone. `pe_asm` imports this condition
rather than copying it, so the correction propagates to the loader — and the
`admissible` refusal there is **unreachable**, as it already was: port
feasibility is tested first and `d ≥ 20` strictly dominates `d ≥ 15`. It is kept
because it is the soundness condition, and would start binding if `D*` ever fell.

### 3.1 ⛔⛔ The trap, pre-registered in §6.1 — and a worse one found inside it

Tightening `admissible` has a convenient side effect: `gate_j_program`
**excludes** inadmissible points from its `sim ≤ derived` check, and the ten
points that retracted the universal `J = 8` are at `d = 8..18`. At `d ≥ 15`,
**seven of the ten leave the scope.**

Pre-registered before the measurement: the violations stay listed under their
own heading with both scopes printed, and the count is asserted so that an edit
dropping one goes red.

**⛔⛔ Writing that check found something worse: it printed `0 violations
total`.** The ten live measurements existed **only in a source comment**. The
gate's `sim ≤ derived` check ran against `SWEEP` — the *stale record* — found
nothing, and said so, four screens below prose asserting ten violations. The
two-copies defect in its purest form: **the gate was green because the numbers
that falsify it were not in any data structure.** They are now `SWEEP_LIVE`,
re-derivable with `price_j_sweep.sh`.

*A guard can pass because what it guards is absent.* The §6.1 check was written
to stop a retraction being re-opened by re-scoping, and it surfaced a case where
the retraction had never been checkable at all.

And the correction narrows two intervals that had been conflated: the
admissible-but-not-port-feasible gap is `d ∈ [15, 19]`, while the region where
measurement exceeded the derivation is `d = 8..18`. Both end at `D* − 1`; they
start in different places, because below `d = 15` the *dispatcher* saturates and
those stalls were never refill latency.

---

## 4. ⚠ Not done, and why — the canonical table still carries `C = 2`

`bursty.TX / UART_RX / SPI_RX` is unchanged, so every gate other than the
re-quote still computes with `C = 2`. **Flipping it is not a substitution**, and
attempting it is what established that:

`SPI-target`'s shipped `D_tol = 18` is **derived**, by
`abs_tolerance(25, c9_at_completion=True, C=2)`, and that function subtracts `C`
— a reactive lane whose pin moves at service completion spends its whole service
time out of the peer's setup window. At `C = 3` the same derivation gives **17**.

And `D_tol` is the **EDF key** (`D_sched` defaults to it, `D = D_sched + C`),
which is exactly the hazard spec R2 split the two fields to control: deriving
`D_SPI-master = 23` once silently re-ordered all five lanes because one field
was both the requirement and the schedule.

⭐ **The project already defends this.** `gate_lane_class.py` asserts
`sp.D_tol == abs_tolerance(25, True, sp.C)`, so a naive flip goes red and demands
the deadline be re-derived. The guard works, which is why this is a report.

**The question is bounded, and the published figure does not depend on it:**

| `SPI-target D_tol` | min margin | its own margin | EDF order |
|---|---|---|---|
| 18 — as shipped (C=2-derived) | 11 | 12 | unchanged |
| 17 — same derivation at C=3 | 11 | 11 | unchanged |
| 20 — C9 = START, C-independent | 11 | 14 | unchanged |

All three leave I2C the tightest lane, so the minimum stays 11 in every case.
Note that **20 is what the RTL actually does** — `ST_DRIVE`'s comment reads "the
pin moves in the FIRST cycle of service" — and 18 is the conservative label
because Phase 2 has not *measured* it. That measurement was already owed.

### Owed to Wilson

1. **Flip the canonical `C`?** It is a lane-table change: new digest, new ledger
   entry, and the recorded expectations of `gate_j_sound`, `gate_pyrta`,
   `jitter_instances` and `frontier` all move at once. Re-blessing several
   recorded tables in one commit is the operation this project treats with most
   suspicion, and the deadline above has to be ruled before it can be done.
2. **Which `C9` reading sets `SPI-target`'s deadline** — 17 (conservative,
   completion), or 20 once the pin is measured at service start.
3. **Re-derive `j_stall`'s refill-window `+ C`**, or leave it at the occupancy
   figure as the conservative choice.
