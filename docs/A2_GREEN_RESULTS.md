# A2-GREEN — Parts 1, 2, 3 closed. Part 4 outstanding.

Answers A2-GREEN. **Supersedes the `r_i` values in `A2_CLOSE_RESULTS.md`** —
every response time there was computed with an over-counted interference sum and
a spurious `+1`, and two further bugs were found on the way. `D_i` (Part A) is
unchanged and still stands.

**Reproduce:**
```
python model/a2/rta_spuri.py        # Parts 1 and 2
python model/a2/zone/run_edf.py     # Part 3 (needs WSL + TChecker at /opt/ta)
```

---

## Final numbers

**Three required protocols — A2a and A2b both pass:**

| lane | `T_i` | `C_i` | `D_i` | `B_i` | `r_i` | margin |
|---|---|---|---|---|---|---|
| UART 115200 | 434 | 2 | 216 | 0 | **6** | 210 |
| SPI 1 MHz | 25 | 2 | 12 | 1 | **3** | 9 |
| I²C 400 kHz | 62 | 2 | 30 | 1 | **5** | 25 |

`U = 0.11687`, condition (2) passes at all 37 scheduling points (tightest `d=12`,
slack 9). **No lane at zero margin — A2-F6 does not fire.**

**With Ethernet — still RED, for the same structural reason:**

| lane | `D_i` | `r_i` | margin | |
|---|---|---|---|---|
| UART 115200 | 216 | 10 | 206 | OK |
| SPI 1 MHz | 12 | 5 | 7 | OK |
| I²C 400 kHz | 30 | 9 | 21 | OK |
| 10 Mbit Ethernet | 2 | **3** | −1 | INFEASIBLE |

⭐ `r_Ethernet = 3` is **exactly `C + B = 2 + 1`**, the hand-derived structural
floor from `A2_CLOSE_RESULTS` — reached independently by the recurrence. With the
`+1` in, the recurrence said 4 and disagreed with the floor by one cycle. The
floor was right; the discrepancy was the double-count.

---

## Part 1 (O9) — deadline-limited interference

Spuri's form, implemented as written:
```
W_i(a,t) = Σ_{j≠i} min{ floor((t+J_j)/T_j) + 1,  floor((a+J_j+D_i-D_j)/T_j) + 1 }_0 · C_j
L_i(a)   = floor(a/T_i)·C_i + B_i(a) + W_i(a, L_i(a))
r_i      = max over a ∈ A_i ( L_i(a) + C_i + J_i − a )
```

| lane | `r` loose | `r` Spuri | delta |
|---|---|---|---|
| UART | 7 | 7 | 0 |
| **SPI** | **8** | **4** | **−4** |
| I²C | 8 | 6 | −2 |

**`r_SPI` is settled: a genuine pass, not a buffered one.** Margin 4→8 on the
three required lanes, and 0→6 with Ethernet. **SPI's zero margin was an artefact
of the over-count, not a property of the design.**

Why SPI gains most: it holds the **earliest** deadline (12 < 30 < 216), so under
EDF no UART or I²C instance released in the busy period can carry a deadline
≤ 12 — both contribute exactly **zero**. The loose sum charged SPI for all of them.

Two findings the spec did not anticipate:
- **`B_i` is a function of `a`.** A job can block only if its deadline exceeds the
  analysed instance's *absolute* deadline `a + D_i`, so blocking shrinks as `a`
  grows. The uniform `B_i` was the `a = 0` case.
- **The pre-registered falsifier did not fire, but one lane legitimately did not
  move.** UART is unchanged, because the latest-deadline lane is never over-charged
  — every other lane is more urgent. 2 of 3 and 3 of 4 lanes moved.
- **The offset search always lands on `a = 0`** for the real tables, over 25–96
  candidates per lane. That is a measured result, not an assumption; Lemma 4.1's
  warning is implemented and simply does not bite here.

## Part 2 (O8) — the `+1` double-counts

⚠ **I did not source it, and I will not invent an equation number.** Instead:
three schedules whose answers are forced by the schedule itself.

| case | truth | with `+1` | without |
|---|---|---|---|
| N=1, nothing to block or interfere | 2 | 3 | **2** |
| N=2, `B=0`, one more-urgent lane ahead | 5 | 6 | **5** |
| N=2, blocker started one tick early | 5 | 6 | **5** |

All three agree with the form **without** the `+1`, which is wrong by exactly 1 in
every case — **including the case with no blocker at all.** That rules out the
reading that the `+1` is the critical-instant offset: with nothing blocking there
is no offset to account for, and the term still adds a cycle.

**Conclusion: the `+1` double-counts the tick that `(C_k − 1)` already encodes.**
Direction: conservative by 1 on every lane. Removed. If RR-2966 does carry a `+1`,
it sits in a formulation that differs elsewhere (continuous time, or `B` defined
as `C_k` rather than `C_k − 1`) and the two cannot be mixed — same conclusion.

## Part 3 — the foreign checker, and what it caught

TChecker could not take the natural encoding. One clock per lane with the EDF
choice as a diagonal guard `x_j − x_i ≤ D_j − D_i` passes `tck-syntax` and then:
```
ERROR: unsupported diagonal constraints
```
A hard limit of the zone algorithm. The replacement is better than a workaround:
**discrete time, one clock driving a tick, every scheduling variable a bounded
int.** The recurrence under test *is* a discrete-time formulation — its blocking
term is `C_k − 1`, one tick — so a dense-time zone model would have been
cross-checking a different semantics and any disagreement would be
uninterpretable. The state space is finite, so reachability is complete.

Non-preemption and blocking are **emergent, not encoded**: the schedule phase only
fires when the engine is idle, so a less urgent job that started before a more
urgent release runs to completion and delays it. Release phases and deadline ties
are both **nondeterministic**, so the checker explores every alignment and every
tie-break rather than assuming the critical instant or a tie-break rule.

**Step 1 — the model is validated before it is trusted**, against the same three
hand-timed schedules: returns 2, 5, 5. A foreign checker is only an authority once
it reproduces answers that can be verified by hand.

**Step 2 — 9 of 9 lane-instances agree, `ovr` unreachable everywhere:**

| instance | `U` | lanes (recurrence = TChecker) | states |
|---|---|---|---|
| I1 N=2, distinct `C` | 0.629 | A 4=4, B 5=5 | 1,196 |
| I2 N=3, distinct `D` | 0.543 | A 3=3, B 2=2, C 4=4 | 9,160 |
| **I3 N=4, `m_i>1`** | 0.950 | A 3=3, B 5=5, C 8=8, D 11=11 | 119,156 |

### ⛔ Two bugs in my own code, both found by this part

**1. A degenerate zero fixpoint, masked by the `+1`.** Seeding the iteration at
`base` let `base = 0` (no blocking, no earlier instance) sit on a fixpoint:
`ceil(0/T_j) = 0` counts no interference, `nxt = 0 = L`, and the recurrence
terminated before it started. With the `+1` present `base` was never 0 — **the
spurious term and the bad seed cancelled each other.** Exposed by Part 2's case
(2), the only forced case with `B = 0` *and* real interference.

**2. The recurrence was UNSOUND at `m_i > 1`.** Eligibility was non-strict
(`D_j ≤ a + D_i`, so deadline ties interfere) but the release count was
`ceil(t/T_j)`, which counts releases in the *open* interval `[0, t)` and so
excludes a job released at exactly `t`. **Non-strict eligibility with a strict
release count under-counts interference, and an under-counted interference term
is an under-estimated response time** — the one direction a bound may not err in.

TChecker reported `r_D = 11` against the recurrence's 8 on I3. The hand trace
confirms 11: all four lanes released at `t=0`, deadlines 3/5/8/11, and the two
11-vs-11 ties both break against D. Fixed to `floor(t/T_j) + 1`, which also
removes the degenerate fixpoint from bug 1.

**The real tables never changed from this** — every required lane has `m_i = 1`,
where the period never enters the first-instance worst case. ⛔ **But it would have
bitten any higher-rate lane**, which is precisely the direction the project is
heading.

### ⛔ And one bug in the TChecker model, caught by its own assumption check

The release guard fired at `a == T−1`, making every period one tick short. For I3
that lifted real utilisation from 0.95 to **1.137** — an overloaded system. It then
disagreed with the recurrence on three lanes and **looked exactly like "the
recurrence is unsound"**. The `ovr` label (a release arriving while the same lane
is still pending) is what said otherwise, and the `m_i>1` instance is what
triggered it: with `m_i = 1` the period never enters the answer, so I1 and I2
agreed with a broken model.

⭐ Three of this section's four findings only exist because the spec insisted on
an instance with `m_i > 1`. I1 and I2 agreed under three separate bugs.

---

## The Ethernet escape is cheaper than it looked — `w = 1`

Recomputed with the corrected recurrence. Every lane re-checked at each `w`:

| `w` | `T` | `D` | `U` | `r_Eth` | verdict |
|---|---|---|---|---|---|
| **1** | **5** | **4** | **0.5169** | **3** | **FEASIBLE** |
| 2 | 10 | 9 | 0.3169 | 3 | FEASIBLE |
| 4 | 20 | 19 | 0.2169 | 5 | FEASIBLE |

**The derived minimum is `w = 1`, not the `w = 4` in `A2_CLOSE_RESULTS`** — a
**1-bit shadow register**, not a 4-bit shift register. Materially cheaper on a
24-tile budget.

The mechanism: buffering moves Ethernet's deadline from the per-edge jitter
tolerance (`D = 2`) to a full outer period minus the latch tick (`D = 5w − 1 = 4`),
because a double-buffered pin decouples edge timing from service timing entirely.
Ethernet then holds the earliest deadline, takes **zero** interference, and
`r = B + C = 1 + 2 = 3 ≤ 4`.

O5's trigger is what makes this mandatory rather than optional: unbuffered,
`D = 2 < 3 = C + B`, so a buffer is required and its width is **derived**.

---

## Gate status

| part | state |
|---|---|
| 1 — O9 deadline-limited interference, `r_SPI` settled | ✅ `r_SPI = 3`, margin 9, genuine pass |
| 2 — O8 the `+1` | ✅ settled by construction; ⚠ **not** sourced in the literature |
| 3 — foreign cross-check, N=2,3,4 | ✅ 9/9, model validated first, `m_i>1` and distinct `C` both covered |
| 4 — P1 reactive lanes | ❌ **not started** |

**A2 is not green.** Parts 1–3 are closed and the three required protocols pass
in the driving direction with a foreign engine agreeing. **Part 4 is untouched** —
UART-rx and I²C clock-stretch have no `D_i`, no arrival model, and no
classification, so the receiving direction is unanalysed. Per the spec's own gate,
A2 GREEN requires all four.

Outstanding beyond Part 4:
- `D_i` for SPI/I²C/Ethernet remains **modeled, not derived** (O4) — TA-03's job.
- The `+1` still wants a real citation, or an explicit note that the discrete
  formulation used here is ours.
