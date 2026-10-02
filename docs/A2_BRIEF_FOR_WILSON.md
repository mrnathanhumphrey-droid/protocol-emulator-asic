# Rung 3 — A2. Everything extracted from the papers, so you don't re-read them.

**This is a working brief, not a result.** Nothing below is proved for our engine.
Every formula and quote is transcribed from a paper I read; the citation after each
tells you where to look **only if you want to verify it**, not because you need to
read it.

⛔ **Two gaps I could not fill, so don't assume they're covered:**
- **RR-2966 Annex B, Theorems 21–24** — the *closed-form* polynomial sufficient
  conditions. The PDF's math is symbol-positioned and extracted scrambled. **The
  recurrences below survived; the closed forms did not.** You have the PDF.
- **Spuri RR-2772** — subset font, zero extractable text under two engines. You're
  parsing it.

---

## 1. What A2 is, and why it is currently stated wrong

`ARCH_PREREG_01` A2 says:

> "worst-case queue lateness is **exactly** `(Q-1) x k` cycles and is **provable**,
> not just measured"

**Three defects:**

**(a) It conflates two different objects.** Split them — both needed, neither
implies the other:

| | claim | instrument |
|---|---|---|
| **A2a** | the task set is schedulable at all | Jeffay conditions (1)+(2), §2 |
| **A2b** | worst-case response time ≤ a bound | critical instant + blocking, §3 |

**(b) The blocking term is missing** — see §3.

**(c) "exactly" must go.** What the theory gives is `≤`. Claiming equality invites a
counterexample.

---

## 2. A2a — FEASIBILITY. Jeffay, Stanat & Martel 1991 (RTSS, pp. 129–139)

Our engine is **non-preemptive** (one event serviced to completion) and
**EDF** (`ARCH_PREREG`: "deadline-ordered … earliest deadline served first").
This paper is exactly that case.

### Theorem 4.1 — transcribed

For periodic tasks `τp = {T1 … Tn}`, `Ti = (ci, pi)`, **sorted non-decreasing by
period**. If `τp` is schedulable non-preemptively without inserted idle time, then:

```
(1)   Σ(i=1..n)  ci / pi   ≤  1

(2)   ∀i, 1 < i ≤ n;  ∀L,  p1 < L < pi:

          L  ≥  ci  +  Σ(j=1..i-1)  ⌊ (L-1) / pj ⌋ · cj
```

**Corollary 4.2** extends both conditions to **sporadic** task sets.

**From the abstract:** the conditions are **necessary and sufficient for arbitrary
release times**, and *"any set of periodic or sporadic tasks that satisfies
conditions C can be scheduled with an earliest deadline first (EDF) scheduling
algorithm."*

⭐ **So EDF is not just adequate — it is universal for any task set passing the
test.** The discipline we already chose is the one the theorem is about.

### Condition (1) is our duty-cycle table, and it already closes

`ARCH_PREREG`'s measured table **is** `Σ ci/pi`, at 50 MHz, one event per bit,
2 clk/event:

| lane | clks/bit | duty |
|---|---|---|
| UART 115200 | 434 | 0.5% |
| SPI 1 MHz | 50 | 8.0% |
| I²C 400 kHz | 125 | 3.2% |
| **all three** | | **11.7%** |
| 10 Mbit Ethernet | 5 | **40%** ← pressure point |

`U ≈ 0.117`, ~9× headroom. **Condition (1) passes with enormous margin.** The
headroom table was A2's precondition all along.

### ⛔ Condition (2) is the one that can bite, and it is NOT a closed form

It is a **test over all L** in `(p1, pi)`. Jeffay's own footnote gives the contrast:

> "In [Liu & Layland 73] it was shown that a concrete set of periodic tasks … where
> `Ri = 0` for all *i* … is schedulable on a uniprocessor **when preemption is
> allowed** … if and only if **condition (1) alone** is satisfied."

**Condition (2) is precisely what non-preemption costs.** With `U = 0.117` but
`p1 = 50` (SPI) against `pi = 434` (UART), (2) is a real test, not a formality.

⭐ **New falsifier worth pre-registering: A2-F4 — (2) fails while (1) passes.**
That is **not** a failure of A2. It means non-preemption, not utilization, is the
binding constraint — it bounds `Q` or `k`, and is a genuine design result.

### ⛔ The tractability caveat — decidable, but not exactly

> "for sets of periodic tasks with specified release times, the conditions C, while
> sufficient, are not necessary. In fact, we show that determining whether a set of
> periodic tasks with specified release times is schedulable is intractable (*i.e.*,
> **NP-hard in the strong sense**). Moreover … would imply that P = NP."

**Aim at the sufficient condition, not an exact oracle.** We want a sound bound;
the sufficient conditions give one and sidestep the hardness entirely. The thing to
avoid is promising exactness.

---

## 3. A2b — THE BOUND. George, Rivierre & Spuri 1996, INRIA RR-2966, §5.1.1

**EDF, non-preemptive, with release jitter.** Transcribed as it extracts:

```
w(i,q) = q·Ci + 1 + Σ(j ∈ hp(i)) ⌈(w(i,q) + Jj)/Tj⌉·Cj  +  max(k ∈ lp(i)){ Ck − 1 }

r(i)   = max over q of ( w(i,q) + Ci + Ji − q·Ti )

feasible iff  ∀i ∈ [1,n]:  r(i) ≤ Di
```

⭐ **The blocking term is `max_{k ∈ lp(i)} (Ck − 1)`.** Your `(k−1)` is real and
exactly where you put it.

### Figure 6 — the construction, so you can rebuild the proof

The blocking task is the **lower-priority task with the largest `C`**, released at
**`t1 − 1`** — one tick before the critical instant, so it is already in service and
blocks for `Ck − 1`. Figure 6's caption carries `Ck = max_{j ∈ lp(i)} {Cj}` and the
release at `t1 − 1`. That is "at most one non-preemptible job already running", with
the picture.

### ⛔ TWO REFINEMENTS THAT CHANGE WHAT WE WRITE DOWN

**R-a — it is a max over the OTHER lanes, not `(k−1)` of the lane analysed.**
`(Q-1)k + (k-1)` is correct **only if every lane has the same `C`**. Ours do not —
a UART bit-action, an SPI edge and an I²C action differ. General form:

```
L  ≤  Σ(other lanes) Cj  +  max(k ∈ lp(i))( Ck − 1 )
```

⛔ **Assuming equal `k` makes the bound wrong in the direction that flatters us**
whenever the slowest lane is slower than the lane analysed. **The engine spec must
carry a per-lane worst-case service time, not one global `k`.**

**R-b — EDF buys exactly one cycle over static priority.** For fixed priority the
same report uses `Bi = max_{j ∈ lp(i)} {Cj}` — **no `−1`**. We already chose EDF, so
we get the `−1`. A consequence of the discipline, not a preference.

---

## 4. The critical instant — it chains cleanly across three papers

**Joseph & Pandya 1986**, *Finding Response Times in a Real-Time System*,
Computer Journal 29(5) p. 391 — the exact **preemptive** RTA that RR-2966 extends:

```
                ( i-1                    )
   RT_i    =    ( Σ    ⌈ RT_i / T_j ⌉ · C_j )  +  C_i                       (1)
                ( j=1                    )

   Inputs([t,t'), j)  =  ⌈ t'/T_j ⌉  −  ⌈ t/T_j ⌉                           (2)
```

> **Definition.** "The critical instant for level *i* is defined to be the instant
> when an input at this level will have the largest response time."
>
> **Theorem 1.** "A critical instant for level *i* occurs whenever an input at this
> level occurs simultaneously with the inputs of all higher-priority tasks."
> *Proof. As in Liu and Layland.*

⭐ So the chain is **Liu & Layland → Joseph & Pandya (Thm 1) → RR-2966 (Fig. 6,
plus the `t1 − 1` release)**. You are not inventing the critical-instant argument;
you are instantiating a 50-year-old one and adding the non-preemptive release.

---

## 5. ⛔⛔ THREE DIFFERENT THINGS ARE CALLED "BLOCKING". ONLY ONE IS OURS.

I conflated two of these once already. Worth 30 seconds of your attention:

| source | its `B` | ours? |
|---|---|---|
| Joseph & Pandya 1986 | none — independent, preemptive | no |
| **Audsley et al. 1993** (SEJ 8(5)) | `Bi` = **resource** blocking: *"the longest critical section of any lower priority task accessing a semaphore with ceiling of equal or higher priority"* (per Sha et al.) | **no** |
| **RR-2966 §5.1.1** | `max_{k∈lp(i)}(Ck − 1)` — **non-preemption** blocking | ⭐ **YES** |

Audsley's `R_i = C_i + B_i + I_i` is the right *shape* but its `B` is a different
quantity. **And for us it is zero** — see §6.

---

## 6. ⭐⭐ P3 IS CLOSED — non-preemption gives mutual exclusion for free

Your P3 said: *keep lanes resource-independent or priority-ceiling analysis enters.*
**Two foreign authorities say the constraint is unnecessary — it is a consequence of
non-preemption, not a rule we must impose:**

> **RR-2966 §5.1.2:** "it is also interesting to notice that resource sharing is
> quite simple to manage in non-preemptive context since, owing to the absence of
> preemption, **there is no need of any particular protocol**. The only possible
> priority inversions are caused by the absence of preemption."

> **Jeffay §1:** "Non-preemptive scheduling on a uni-processor **naturally
> guarantees exclusive access to shared resources and data**, thus eliminating both
> the need for synchronization and its associated overhead."

Different authors, different years, neither a same-hand re-derivation.

**Consequences:** lanes **may share a shift register or memory port** with no extra
term (an area saving we were about to forbid ourselves); Audsley's `Bi` = 0; and
**Sha/Rajkumar/Lehoczky is off the reading list.**

---

## 7. P1 — the minimum inter-arrival, corroborated FOUR times

This is where A2 can genuinely fail, and it is not one framing's quirk:

- **Jeffay:** *"if T is sporadic, `p` specifies a **minimum** interval between
  invocations"*
- **Joseph & Pandya §2:** *"let `T_i` be the **minimum time** between successive
  inputs from the device connected at priority level *i*"*
- **Audsley et al. §3:** `Ti` = the **lower bound** on the interval between releases
- **Liu & Layland**, via the periodic model both build on

⛔ **A reactive lane with no minimum inter-arrival has no bound in ANY of these
theories.** For us: **UART receive** and **I²C clock-stretch** are peer-driven. Each
must either carry a minimum inter-arrival from the peer's own protocol spec, or take
§8.

---

## 8. ⭐⭐ THE SECOND ESCAPE — buffering, and it is provable

Joseph & Pandya, §2:

> "a common requirement is for `RT_i` to be less than `T_i`. **If this condition
> cannot be met, buffers can be added to store successive inputs coming from
> devices**, or additional processors can be added"

and from their abstract: *"we show how the addition of buffers for inputs can be
useful"* — including a method to find **how many buffers** make a given assignment
feasible.

⛔ **This changes the fallback.** A reactive lane that can't be serviced in time was
going to be the named obstacle dropping to "measured, not proved". It now has a
**third, provable option: buffer it and derive the depth.**

⭐ And it lands on a descriptor extension already on our rung list — the **data
source / FIFO**, previously justified only as "a real emulator wants one". **It is
the schedulability remedy.** Build it only for the lanes A2 says need it, **with the
depth derived rather than guessed.**

---

## 9. The three preconditions, as they now stand

| | condition | status |
|---|---|---|
| **P1** | every reactive stream has a minimum inter-arrival | ⛔ **open — the real risk.** Per-protocol, checkable. §7 |
| **P2** | worst-case service time `k` is bounded per lane | open — where CRC / bit-stuffing arithmetic gets priced. Data-dependent is fine; data-**unbounded** is not |
| **P3** | engine is the only shared resource | ✅ **closed by §6** — free under non-preemption |

---

## 10. Deliverables, gate, falsifiers

**Derive and prove, on the model:**
1. The task model: Q lanes, periods from the real tables, **per-lane** worst-case
   `Ci`, non-preemptive single server, EDF.
2. **A2a:** check Jeffay (1) and (2) on the real tables. Expect (1) ≈ 0.117.
3. **A2b:** derive `L ≤ Σ_other Cj + max_{k∈lp(i)}(Ck − 1)` by critical instant,
   **proving the blocking term explicitly — do not inherit it.**
4. Check P1 per protocol; where it fails, size the buffer per §8.

**Independent cross-check** (standing law 1 — a same-author re-derivation is weak
corroboration): encode Q = 2, 3, 4 in Imitator; synthesized lateness must equal the
closed form. **A disagreement is a finding, not a tie-break.**

| # | falsifier | consequence |
|---|---|---|
| A2-F1 | closed form contradicts the TA cross-check | derivation bug |
| A2-F2 | a reactive protocol has no min inter-arrival | named obstacle → buffer it (§8), or measured-not-proved, **and say which** |
| A2-F3 | `U > 1` on real tables | engine oversubscribed, premise wrong (9× headroom says no) |
| A2-F4 | Jeffay (2) fails while (1) passes | **not** an A2 failure — non-preemption is binding; bounds `Q` or `k` |

**Gate:** bound proved with the blocking term derived + Jeffay (1) and (2) checked
on the real tables + TA cross-check agreeing for Q ≤ 4 ⇒ **A2 green, rung 4
unblocked.**

**No timer.** The primary runs until it closes or fails for a *named* reason, and
the reason is the result.

---

## 12. ⛔⛔ SPURI RR-2772 IS DECODED — AND IT BREAKS THE CRITICAL-INSTANT SHORTCUT

`SPURI_RR2772_EXTRACT.md` is in `docs/`. One finding in it **changes the derivation
method**, and it is the most important thing in this brief.

### Lemma 4.1 — for EDF the worst case is NOT necessarily the first busy period

Unlike fixed priority, EDF's worst-case response time **may not occur at the
synchronous release**. Spuri's own worked example (Tables 1–2, pp. 10–11) has
`r_3` maximised at **`a = 9`**, not in the first busy period. So the release offset
`a` must be **searched**, not assumed.

⛔ **Consequence: "derive `L ≤ (Q-1)k + (k-1)` by critical instant" is NOT a sound
derivation for EDF on its own.** The critical-instant theorem is a *fixed-priority*
result — Joseph & Pandya Thm 1, proved *"as in Liu and Layland"*, and L&L is
rate-monotonic. Carrying it to EDF unexamined is precisely the kind of step a
scheduling reviewer removes.

### ✅ But RR-2966 already does the search, so we are not stuck

I checked: RR-2966 **§5.1.2 is Dynamic priority (EDF) + Non-preemptive case** —
exactly ours — and its response time is

```
r_i      =  max over q = 0 .. Q  { w(i,q) + C_i − q·T_i }        ← the search
w(i,q)   =  q·C_i + 1 + Σ(j∈hp(i)) ⌈(w(i,q)+J_j)/T_j⌉·C_j
                       + max(k∈lp(i)){ C_k − 1 }
Q        =  ⌈ L_i / T_i ⌉
```

**That `max over q` IS Lemma 4.1's search.** The exact procedure is sound and in
hand. Two independent sources agreeing on the need for the search is the
corroboration; neither is a same-hand re-derivation.

### ⚠️ NAMING COLLISION — fix this before writing anything down

**`Q` means two different things** and both appear in A2:

| symbol | in RR-2966 | in our A2 |
|---|---|---|
| `Q` | `⌈L_i/T_i⌉` — number of **instances** in the busy period | number of **lanes** |

Pick different letters now. I suggest `Q` = lanes (as pre-registered) and `m` for
the instance index, or the derivation will quietly say something false.

### So the revised A2b plan

1. **The recurrence above is the sound procedure.** Evaluate it — periods are
   concrete integers and the instance is small.
2. **The closed form `(Q-1)k + (k-1)` is now a CONJECTURE to be proved as an upper
   bound on that recurrence**, not a derivation in its own right. Either prove
   `q = 0` dominates for our instance, or prove the closed form dominates all `q`.
3. ⭐ `L ≤ H` (hyperperiod) bounds the search, so for our `U ≈ 0.117`, small lane
   count and integer baud-derived periods, the **exhaustive check is cheap and
   exact**. Spuri's extract makes the useful observation that **Jeffay's NP-hardness
   is asymptotic** — it scopes an "arbitrary-N lanes" claim, not our concrete
   instance.

### ⭐ And a better model for the reactive lanes (P1)

Spuri §6 gives **bursty / sporadically-periodic** tasks: `n_i` arrivals per outer
period `T_i` at inner spacing `t_i` (assumes `n_i·t_i ≤ T_i`), with `I_i(t)`,
`W(t)` and `H_i(t)` all transcribed in the extract.

**That is a much better fit for reactive protocol events than pure sporadic.** A
UART receive burst is exactly *n bytes at minimum spacing, then a gap* — not an
arbitrary-rate stream. So P1 may be satisfiable for lanes that would fail a naive
"single minimum inter-arrival" test. **Try the bursty model before declaring the
named obstacle.**

### ⚠️ One discipline note from the extract

Spuri **Eq (2) is necessary and sufficient**, but **Thm 7.1 with blocking is
SUFFICIENT ONLY.** Same shape as dropping "exactly" from A2 — report `≤`, and say
"sufficient" where that is what we have.

## 11. What I could NOT transcribe — your two jobs in the PDFs

1. **RR-2966 Annex B, Theorems 21–24** — "Polynomial sufficient conditions".
   Theorem 22 = an upper bound on EDF worst-case response time via absolute
   deadlines in the synchronous busy period; Theorem 23 = a further upper bound
   eliminating the floor function; Theorem 24 = the same for static priority.
   **The closed forms are exactly what A2b wants and they did not survive
   extraction.**
2. **Spuri RR-2772** — EDF RTA specifically; you're parsing it. Watch for whether
   its EDF treatment supersedes or merely agrees with RR-2966 §5.1.1.
