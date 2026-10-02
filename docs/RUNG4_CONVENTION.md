# Rung 4 Part 0 — the scheduler convention the RTL must implement

The seam where rung 4 can silently void A2. Each item below is the convention the
**validated** model implements, where in the code it lives, and what it costs if
the RTL differs. Nothing here is a preference; it is the contract the proved
bound was proved under.

**Reproduce:** `python model/a2/zone/run_tiebreak.py`

Two categories, and the distinction is the whole point:

- **MAX-ED OVER** — the bound was computed as the worst case across every
  possible behaviour, so the RTL may do any of them. Free.
- **ASSUMED** — the bound presumes one specific behaviour. Differ and the number
  moves or the proof does not transfer.

---

## C1 — EDF by absolute deadline · ASSUMED

Serve the ready action with the smallest `release + D_i`. In the model the guard
is `a_j − a_k ≤ D_j − D_k`, which is `D_k − a_k ≤ D_j − a_j`, which is "k's
absolute deadline is no later than j's" (`gen_edf.py`, SC phase).

The RTL compares **absolute deadlines**, not periods, not lane indices, not
remaining service. A fixed-priority scheduler is a *different* scheduler and the
bound says nothing about it.

## C2 — tie-break · **MAX-ED OVER. FREE.**

⭐ **Measured, not argued.** The model's guard uses `<=` against every rival, so
on an equal deadline every candidate transition is enabled and the checker
explores all orderings — the reported `r_i` is the **maximum over all
tie-breaks**. Re-running all three Part 3 instances under a deterministic
lowest-index-wins rule:

| instance | lane | nondet (all tie-breaks) | index (deterministic) | |
|---|---|---|---|---|
| I1 | A, B | 4, 5 | 4, 5 | equal |
| I2 | A, B, C | 3, 2, 4 | 3, 2, 4 | equal |
| **I3** | A, B, C | **3, 5, 8** | **2, 4, 7** | det **1 lower** on each |
| I3 | D | 11 | 11 | equal |

`det ≤ nondet` on **9 of 9** lanes, strictly lower on 3. The deterministic rule is
a subset of the explored runs, exactly as the soundness argument predicts.

⛔ **R4-F2 is tighter than it needs to be.** The RTL does **not** have to
reproduce a specific tie-break. Use whatever is cheapest in cells — a priority
encoder on lane index is covered by the proved bound.

⚠ **The caveat that survives:** tie-break freedom holds for the **bound**
(`r_i ≤ D_i`), **not** for byte-exact waveform equality. Two tie-breaks emit
different orderings when deadlines collide, so the **golden model must be pinned
to whichever rule the RTL picks**. It just does not have to be any particular one.
Pick the rule in RTL first, then configure the golden model to match — not the
reverse.

## C3 — same-cycle ready · ASSUMED, and here is the price

An action whose timestamp **equals** the current cycle counter is ready **in that
cycle** and may begin service in that cycle. In the model the release phase
(`R0..RN`) runs before the schedule phase (`SC`) inside the same time step, and
the recurrence's release count is `floor(t/T) + 1` — which counts the release at
exactly `t`. (That `+1` is the Part 3 soundness fix; it is not the deleted `+1`.)

**If the RTL makes an action ready one cycle late, every `r_i` grows by one.**
Modelled as release jitter `J`, since the proof already carries a `J_i` term:

| `J` | UART-tx | SPI-tx | I²C | UART-rx | SPI-target | verdict |
|---|---|---|---|---|---|---|
| **0** (as proved) | 10 / 216 | **5 / 12** | 7 / 30 | 10 / 216 | **5 / 12** | all feasible |
| 1 | 11 / 216 | **6 / 12** | 8 / 30 | 11 / 216 | **6 / 12** | all feasible |
| 2 | 12 / 216 | **7 / 12** | 9 / 30 | 12 / 216 | **7 / 12** | all feasible |

⭐ So this convention is **preferred but not load-bearing**: a one- or two-cycle
registration latency costs exactly that many cycles of margin and every lane
still passes, because SPI's margin is 7. **But the proved numbers would no longer
be the shipped numbers** — re-run `bursty.py` with the real `J` and quote those
instead. Do not keep quoting `r_SPI = 5` while the RTL registers requests.

## C4 — non-preemption · ASSUMED

Once service begins it runs to completion; nothing interrupts it. In the model
`SC` only fires when `cur == 0`. This is what makes the blocking term
`max_j(C_j − 1)` correct, so it is load-bearing in both directions: a preemptive
RTL would have a *different* (smaller) bound that this analysis does not compute.

## C5 — work-conserving · ASSUMED

If the engine is free and any action is ready, service begins **that cycle**. The
model emits no skip edge from `SC` when something is pending. An engine that
inserts an idle cycle while work is ready breaks the bound directly.

## C6 — service time · **the two obligations are different, and the spec conflates them**

The model serves exactly `C_i` cycles (`rem = C_k`, decrement to 0).

- For the **bound** (`r_i ≤ D_i`), occupancy **`≤ C_i`** suffices — finishing
  early only reduces response times.
- For **byte-exact refinement**, occupancy must be **exactly `C_i`**, or the
  emitted waveform shifts.

⛔ INV-3 as written in the rung-4 spec says "exactly", which is right for
refinement and stronger than the bound needs. Worth separating, because it changes
what a mutant means: **an RTL that finishes service early is caught by
byte-exactness and correctly *not* caught by INV-4.** That is the harness working,
not a hole — and without the distinction written down it would look like a hole.

## C7 — one outstanding action per lane · **DERIVED PERMISSION, not a constraint**

⭐ **The ready queue needs at most `N` entries — one per lane — not a deeper
FIFO.** Evidence: the foreign model carries exactly one pending flag per lane and
`ovr` (a second event arriving while the first is unserved) was proved
**unreachable on every instance** of Parts 3 and 4; and for both bursty lanes
`r_i ≤ t_i` with large margin (10 ≤ 434, 5 ≤ 25), so a second event of the same
lane cannot arrive before the first completes.

With five lanes that is a **5-entry deadline-ordered structure**. This is a
sizing fact for Part 1's descriptor memory, derived rather than chosen.

## C8 — single server · ASSUMED

One action in service at a time; no parallel issue. The model has a single `cur`.
Two engines would be a different analysis entirely (and the `U ≤ 1` test would
change).

---

## Summary for the RTL scheduler spec

| # | convention | status | if the RTL differs |
|---|---|---|---|
| C1 | EDF on absolute deadline | ASSUMED | proof does not transfer |
| C2 | tie-break | **FREE** | nothing — pin the golden model to the RTL's choice |
| C3 | same-cycle ready | ASSUMED | `+1` cycle per cycle of latency; still feasible to `J=2`, but re-quote the numbers |
| C4 | non-preemption | ASSUMED | blocking term invalid |
| C5 | work-conserving | ASSUMED | bound invalid |
| C6 | exactly `C_i` | ASSUMED for byte-exactness; `≤ C_i` for the bound | early finish breaks refinement, not the bound |
| C7 | ≤1 outstanding per lane | **DERIVED** | queue may be 5 entries, no FIFO |
| C8 | single server | ASSUMED | different analysis |

**Two edits to the rung-4 spec this produces:**

1. **R4-F2 relaxes.** Tie-break is free; the falsifier should instead read *"the
   golden model's tie-break does not match the RTL's"* — a harness-configuration
   failure, not a proof failure.
2. **INV-3 splits.** `occupancy ≤ C_i` is the bound obligation; `occupancy == C_i`
   is the refinement obligation. Keep both, name them separately, so that an
   early-finishing mutant is scored against the right one.

**Honest label carried forward unchanged:** `D_i` for SPI and I²C is still
**modeled**, not sigrok-derived (O4). Everything above is about preserving the
model in silicon; none of it upgrades the model's `D_i` inputs. TA-03 does that.
Rung-4-green must not be read as "SPI/I²C `D_i` now derived".
