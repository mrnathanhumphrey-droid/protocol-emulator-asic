# A2 — the framework, from the literature. Foundation, not yet a result.

**Status: nothing is proved here yet.** This file fixes *what* A2 is, what theorem
it needs, and which conditions it rests on, with every claim quoted from a paper on
disk rather than recalled. Deriving the bound on our real tables is the probe
(`A2-RTA`); Wilson owns it. This is the ground it stands on.

⛔ **Papers live in `refs/`, which is gitignored and must stay that way.** The
submission is open source and public; third-party copyrighted PDFs must never enter
it.

---

## 1. ⭐⭐ THE REFRAME — A2 is schedulability, not model-checking

I had been treating A2 as *"does a concurrent, arithmetic, multi-lane engine sit in
a decidable timed-automaton fragment?"* — and worrying it might not, since
multi-clock parametric TA reachability is undecidable. **That was the wrong frame.**

UART conformance genuinely *was* a timed-automaton problem: it is about waveform
timing. **A2 is not.** "Worst-case lateness of one server serving Q event streams"
is a classical real-time **scheduling** question with forty years of closed-form
theory behind it. So:

| role | method | why |
|---|---|---|
| **primary** | closed-form schedulability / response-time analysis | a theorem, no state space, no decidability question |
| **cross-check** | Imitator on small instances (Q = 2, 3, 4) | independent method, same number — real corroboration per standing law 1 |
| **soundness** | Lean, on the derived inequality | far cleaner target than a TA metatheory |

## 2. ⛔ But "no decidability question" needs one refinement — and it is load-bearing

Jeffay, Stanat & Martel (1991) prove the exact feasibility problem is **decidable
but not tractable** in the case that matters:

> "for sets of periodic tasks with specified release times, the conditions C, while
> sufficient, are not necessary. In fact, we show that determining whether a set of
> periodic tasks with specified release times is schedulable is intractable (*i.e.*,
> **NP-hard in the strong sense**). Moreover, we show that the existence of a
> universal algorithm for scheduling periodic tasks with specified release times
> would imply that P = NP."

⭐ **This does not threaten A2 — it tells us which object to aim at.** We want a
*sound upper bound*, not an exact feasibility oracle. The sufficient conditions give
one and sidestep the NP-hardness entirely. The thing to avoid is quietly promising
an exact answer; the thing to deliver is a proved bound.

## 3. The theorem A2 actually needs — quoted

**Jeffay, Stanat & Martel 1991, Theorem 4.1.** For periodic tasks
`τp = {T1 … Tn}`, `Ti = (ci, pi)`, **sorted non-decreasing by period**. If `τp` is
schedulable (non-preemptively, no inserted idle time) then:

```
1)   Σ(i=1..n)  ci / pi   ≤  1

2)   ∀i, 1 < i ≤ n;  ∀L, p1 < L < pi:

         L  ≥  ci  +  Σ(j=1..i-1)  floor( (L-1) / pj ) · cj
```

**Corollary 4.2** extends both conditions to **sporadic** task sets. And from the
abstract: the conditions are **necessary and sufficient for arbitrary release
times**, and *"any set of periodic or sporadic tasks that satisfies conditions C can
be scheduled with an earliest deadline first (EDF) scheduling algorithm."*

⭐⭐ **That is a direct hit on our engine.** `ARCH_PREREG_01` already commits to a
*"deadline-ordered action queue … earliest deadline served first"* — i.e. EDF. So
the universality result applies to the discipline we already chose, rather than
requiring us to change it.

⭐ **Condition (1) is the duty-cycle table, and it was A2's precondition all
along.** `ARCH_PREREG_01`'s measured aggregate duty — UART 0.5 % + SPI 8.0 % + I²C
3.2 % = **11.7 %**, ~9× headroom — *is* `Σ ci/pi ≤ 1`. The headroom table was never
decoration; it is the feasibility condition, and it closes with enormous margin.

⛔ **Condition (2) is the price of non-preemption, and it is NOT a closed form.** It
is a *test over all L* in a range. Liu & Layland (1973) is the contrast, per Jeffay's
own footnote:

> "In [Liu & Layland 73] it was shown that a concrete set of periodic tasks … where
> `Ri = 0` for all *i* … is schedulable on a uniprocessor **when preemption is
> allowed** … if and only if **condition (1) alone** is satisfied."

So condition (2) is exactly what non-preemption costs us. Our engine is
non-preemptive by design (one event serviced to completion in ≤ k cycles), so (2)
must be checked, not assumed.

## 3b. ⭐⭐ THE BLOCKING TERM, FROM RR-2966 — CONFIRMED, AND REFINED

RR-2966 obtained (Nate pulled it past the bot-wall). **George, Rivierre & Spuri
1996, §5.1.1** — EDF with non-preemption. The recurrence, as it extracts:

```
w(i,q) = q·Ci + 1 + Σ_{j ∈ hp(i)} ⌈(w(i,q) + Jj)/Tj⌉·Cj  +  max_{k ∈ lp(i)} {Ck − 1}
r(i)   = max_q ( w(i,q) + Ci + Ji − q·Ti )
```

⭐ **The blocking term is `max_{k ∈ lp(i)} (Ck − 1)`** — so the `(k−1)` is real and
it is exactly where Wilson put it. **Figure 6** gives the construction: the
blocking task is the lower-priority task with the largest `C`, **released at
`t1 − 1`** — one tick before the critical instant, hence already in flight and
blocking for `Ck − 1`. That is the "at most one non-preemptible job already
running" argument, with the picture.

### ⛔ Two refinements that change what we must write down

**R-a — it is a max over the OTHER lanes, not `k−1` of the lane being analysed.**
The term is `max over lower-priority tasks of THEIR Ck, minus 1`. Writing
`(Q−1)k + (k−1)` is only right when **every lane has the same worst-case service
time `k`**. Our lanes will not: a UART bit-action, an SPI edge and an I²C action
have different `C`. So the honest general form is

```
L  ≤  Σ_{other lanes} C_j  +  max_{k ∈ lp(i)} (C_k − 1)
```

which collapses to `(Q−1)k + (k−1)` only under equal service times. ⛔ **Assume
equal `k` and the bound is wrong in the direction that flatters us** whenever the
slowest lane is slower than the lane being analysed.

**R-b — EDF is ONE CYCLE BETTER than static priority here, and that is an argument
for the choice already made.** For fixed-priority the report uses
`Bi = max_{j ∈ lp(i)} {Cj}` — **no `−1`**. `ARCH_PREREG` already chose EDF
("deadline-ordered action queue, earliest deadline served first"), so we get the
`−1`. Small, but it is a real consequence of the discipline rather than a
preference.

## 3c. ⭐⭐ P3 IS RELAXED — non-preemption gives mutual exclusion for free

Wilson's P3: *"Shared resources beyond the engine pull in priority-ceiling/blocking
analysis. Keep lanes resource-independent except for the engine and this never
arises."* **Two foreign authorities say the constraint is unnecessary** — it is a
*consequence* of non-preemption, not a design rule we must impose:

> **George, Rivierre & Spuri, §5.1.2:** "it is also interesting to notice that
> resource sharing is quite simple to manage in non-preemptive context since, owing
> to the absence of preemption, **there is no need of any particular protocol**. The
> only possible priority inversions are caused by the absence of preemption."

> **Jeffay, Stanat & Martel, §1:** "Non-preemptive scheduling on a uni-processor
> **naturally guarantees exclusive access to shared resources and data**, thus
> eliminating both the need for synchronization and its associated overhead."

⭐ Different authors, different years, different papers, and **neither is a
same-hand re-derivation** — real corroboration under standing law 1.

**Design consequence for rung 4: lanes MAY share a shift register or a memory port
without paying a priority-ceiling blocking term.** The only inversion is
non-preemption itself, already counted in `max(Ck − 1)`. P3 stops being a
constraint on the architecture and becomes a note that the architecture already
satisfies it. Sha/Rajkumar/Lehoczky is therefore **not needed** — do not fetch it.

## 4. ⛔⛔ A2 AS PRE-REGISTERED IS WRONG ON TWO COUNTS

`ARCH_PREREG_01` A2: *"worst-case queue lateness is **exactly** `(Q-1) × k` cycles
and is **provable**, not just measured."*

**Count 1 — the non-preemptive blocking term is missing.** The event of interest
waits for the `(Q-1)` others released at the critical instant **plus at most one
non-preemptible job already in flight**:

```
        L  ≤  (Q-1)·k  +  (k-1)   <  Q·k
```

⭐ This is the term a scheduling-theory reviewer checks for **first**, and it is
precisely the off-by-one class we were just burned by in the receiver. Derive it
tight or it gets eaten. **It must be proved explicitly, never inherited.**

**Count 2 — "lateness bound" and "feasibility" are different objects**, and A2
conflates them. They are both needed and neither implies the other:

| | claim | instrument |
|---|---|---|
| **A2a** | the task set is schedulable at all | Jeffay conditions (1) + (2), checked on the real tables |
| **A2b** | worst-case response time ≤ `(Q-1)k + (k-1)` | critical-instant + non-preemptive-blocking argument |

⛔ **A2 must be amended in `ARCH_PREREG_01` to say both, and to drop "exactly".**
A bound proved as `≤` is not an equality, and claiming equality invites a
counterexample we would deserve.

## 5. The three preconditions — each per-protocol checkable, none a theorem-killer

**P1 — every reactive stream needs a minimum inter-arrival time.** Jeffay's model
states the requirement in its own words:

> "We assume that events are generated repeatedly with some maximum frequency; thus,
> the time interval between successive invocations of a task will be of some minimal
> length." … "If T is sporadic, `p` specifies a **minimum** interval between
> invocations."

⭐⭐ **This is the hard part, and it is where A2 can genuinely fail.** UART *receive*
and I²C *clock-stretch* are reactive: driven by a peer, not by our clock. If a
reactive event can arrive arbitrarily often, lateness is unbounded and no theorem
saves it. The resolution is protocol-specific and **checkable** — a UART receive
event cannot recur faster than one bit period; an I²C stretch is bounded by the
peer's own spec or it is not boundable at all. Each one either carries a minimum
inter-arrival or **becomes the named obstacle**.

**P2 — bounded worst-case service time `k`.** The bound uses worst-case `k`, so
every table's service time must be finite and known. This is where the *arithmetic*
(CRC for Ethernet/CAN, bit-stuffing for USB) has to be priced: data-dependent work
is fine, data-*unbounded* work is not.

**P3 — the engine is the only shared resource.** If lanes share a shift register or
a memory port, priority-ceiling/blocking analysis enters (Sha, Rajkumar & Lehoczky
1990) and the bound grows a term. **Keep lanes resource-independent except for the
engine and P3 holds by construction** — which is a design constraint on rung 4, not
an analysis to do later.

## 6. The fallback trigger — a named obstacle, never an expired clock

No timer. The primary runs until it either **closes** (A2 proved, rung 4 unblocked)
or **fails to close for a specific named reason** — and that reason is itself the
result. The only two reasons it can fail are P1 and P2 above. When one fires it
tells us exactly which protocols are provably boundable and which are not, and the
fallback is scoped: a per-instance synthesized bound via the TA cross-check for the
boundable ones, and **"measured, not proved" only as a last resort, labelled as
such.** The research ends at a result or at a named obstacle.

## 7. Pre-registered predictions and falsifiers for the A2-RTA probe

**Predictions:** the closed form closes for the periodic (TX / master) protocols;
the reactive (receive / clock-stretch) protocols either carry a min-inter-arrival
bound or are flagged as the named obstacle; the TA cross-check agrees for small Q;
`U ≈ 0.12` on the real tables.

**Falsifiers:**

| # | if | then |
|---|---|---|
| A2-F1 | the closed form gives a bound the TA cross-check contradicts | a derivation bug — ⛔ **a disagreement is a finding, not a tie-break** |
| A2-F2 | a reactive protocol has no minimum inter-arrival | the named obstacle fires; drop that protocol to per-instance/measured **and say so** |
| A2-F3 | `U > 1` on the real tables | the engine is oversubscribed and the premise is wrong — a major finding, though 9× headroom says it will not |
| A2-F4 | Jeffay condition (2) fails although (1) passes | non-preemption is the binding constraint, not utilization. **Not a failure of A2** — it bounds `Q` or `k`, and would be a genuine design result |

**Gate:** closed-form bound proved (with the blocking term derived, not inherited)
+ Jeffay (1) and (2) checked on the real tables + TA cross-check agreeing for Q ≤ 4
⇒ **A2 green on the model, rung 4 unblocked.**

## 8. Texts — READ vs DOWNLOADED, kept separate on purpose

⛔⛔ **"On disk" is not "read", and conflating them is how an unverified guess got
into this document.** The first version of this table said MPI-SWS 2018-003 "may
carry an equivalent result" to RR-2966. **Reading it refuted that.** The column
below is now what was actually read.

| paper | read? | role / what it gave |
|---|---|---|
| **George, Rivierre & Spuri 1996, INRIA RR-2966** | ✅ **read** (56 pp, text extracted) | ⭐ **the blocking term** `max_{k∈lp(i)}(Ck−1)`, Figure 6's critical-instant construction, the EDF-vs-FP difference, and the P3 relaxation. §3b/§3c quoted from it |
| **Jeffay, Stanat & Martel 1991**, RTSS pp. 129–139 | ✅ **read** (11 pp) | conditions C (Thm 4.1, Cor 4.2), the sporadic min-inter-arrival requirement, the NP-hardness result, the shared-resource corroboration |
| **Liu & Layland 1973**, CACM 20(1) | ⚠️ **extracted, not yet read** | cited so far only via Jeffay's footnote (condition (1) alone suffices under preemption) — that footnote WAS read |
| MPI-SWS TR 2018-003, *RTA for Non-Preemptive Job Sets* | ✅ **read enough to reject** | ⛔ **NOT a substitute for RR-2966.** It is **global multiprocessor** non-preemptive scheduling by **schedule-space exploration** — zero occurrences of "critical instant". Wrong problem, wrong method |
| Audsley & Burns, *Real-Time System Scheduling* (survey) | ✅ **read enough to reject for A2b** | its 31 "blocking" hits are all **resource** blocking — priority inheritance, ceiling protocols, remote blocking. P3 territory, and P3 is now closed (§3c) |
| TU/e, *WCRT under FPS with deferred preemption* | ⚠️ extracted, not read | 25 "critical instant" / 17 "non-preemptive" hits — best remaining on-disk cross-read for the blocking argument |
| Spuri 1996 (INRIA RR-2772), RTA for EDF | ⛔ not obtained | EDF response times specifically. Still wanted |
| Joseph & Pandya 1986, *Comp. J.* 29(5) 390–395 | ⛔ not obtained | the original RTA recurrence |
| Audsley, Burns, Richardson, Tindell & Wellings 1993, *SEJ* 8(5) 284–292 | ⛔ not obtained | ⚠️ the survey on disk is **not** this paper |
| Sha, Rajkumar & Lehoczky 1990 | — **no longer needed** | priority ceiling. §3c closes P3, so this is off the list |

### ⛔ A limitation of how these were read, stated plainly

The formulas in RR-2966 **extract badly** — the PDF's math is symbol-positioned, so
`pypdf` returns it scrambled (`maxk lp i( )∈ Ck 1±{ }` is the blocking term
surviving, barely). I recovered the blocking term, the FP-vs-EDF difference and
Figure 6's construction because those survive as near-ASCII. **Theorem 22 and
Theorem 23's closed-form upper bounds did NOT survive extraction**, and I have not
read them as rendered pages (`pdftoppm` is not installed here).

⭐ **So: the blocking term is confirmed from the source; the closed-form bound of
Theorem 23 is NOT yet transcribed and must be read off the rendered page before it
is quoted.** Annex B ("Polynomial sufficient conditions") is where the
closed-forms live — Theorems 21–24 — and that is the part for Wilson to read
directly.
