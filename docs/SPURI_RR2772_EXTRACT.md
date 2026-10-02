> ## ⚠️ UPDATE AFTER THIS FILE WAS WRITTEN — RR-2966 IS NOW IN HAND
>
> This extract was transcribed while **George/Rivierre/Spuri RR-2966 was still
> missing**, and reasonably proposed a *bridge*: instantiate Spuri §7's resource
> blocking `B_i` as non-preemptive blocking. **RR-2966 has since been obtained and
> read.** Its **§5.1.2 is EDF + non-preemptive directly**, so the bridge is no
> longer needed — use the exact source. See `A2_BRIEF_FOR_WILSON.md` §3 and §12.
>
> ⭐ **What this file still contributes, and it is a lot:** Lemma 4.1 (§12 of the
> brief — it threatens the critical-instant shortcut), the **bursty /
> sporadically-periodic model** (§6 here — a better fit for reactive protocol
> events than pure sporadic), `L ≤ H` tractability, and Eq (2) as the n&s
> preemptive feasibility test.

# Extract — Spuri 1996, "Analysis of Deadline Scheduled Real-Time Systems"

Source: Marco Spuri, INRIA Rapport de recherche **N° 2772**, Janvier 1996 (31 pp).
These are **our own transcribed notes** (formulas re-keyed from the scanned pages, attributed) —
NOT the PDF. Keep the PDF out of the public repo as usual; this notes file is our synthesis.

Formulas carry the paper's own equation numbers and page (printed page, not PDF page).

---

## ⛔⛔ READ FIRST — the caveat that governs how we use this

**Spuri RR-2772 analyses PREEMPTIVE EDF.** Our queue engine is **NON-preemptive** (a service
job of up to `k` cycles cannot be interrupted once started). So:

- This paper gives us, directly and soundly: the **EDF feasibility test** (necessary & sufficient,
  preemptive), the **only published EDF worst-case response-time procedure** (the abstract says
  so), the **busy-period machinery**, the jitter / bursty / blocking extensions, and the
  tractability bound `L ≤ H`.
- It does **NOT** give the exact non-preemptive bound. The exact non-preemptive-EDF treatment is
  **George / Rivierre / Spuri, RR-2966** (still NOT in hand). **Do not cite RR-2772's preemptive
  formulas as if they were the non-preemptive bound.**
- The **bridge** to our case is **Section 7 (Resource Sharing / blocking factor `B_i`)**:
  non-preemption is the special case where a running job holds, in effect, a ceiling-lock on the
  whole processor for its duration. So we instantiate Spuri's blocking term `B` as the
  **non-preemptive blocking** (longest single job that can be in progress when a deadline comes
  due) and add it exactly the way Section 7 adds `B_i`. The `(k-1)` blocking term in A2b is this,
  **derived from first principles** (per Wilson's ruling) and justified by Section 7's framework +
  cross-checked against Jeffay (1)&(2).

Three more honest flags, below in context:
1. **EDF worst-case response is NOT always in the first busy period** (Lemma 4.1) — must search `a`.
2. **Eq (2) is necessary & sufficient**; **Thm 7.1 with blocking is SUFFICIENT only** (keep the `≤` / "sufficient" discipline — matches the "drop *exactly*" ruling).
3. `L ≤ H` (hyperperiod) bounds the search → cheap/exact for our small, concrete instance.

---

## Notation (page 5–6) with our mapping

| Spuri | meaning | our A2 mapping |
|---|---|---|
| `C_i` | worst-case computation/execution time per release | per-event **service time**, ≤ `k` cycles |
| `D_i` | relative deadline (from arrival) | the event's timing deadline |
| `T_i` | outer period | event period (baud-derived) |
| `t_i` | inner period (bursty) | intra-burst spacing of reactive events |
| `n_i` | worst-case arrivals per outer period | burst size (reactive) |
| `J_i` | worst-case release jitter | jitter on reactive events |
| `B_i` | worst-case blocking (priority inversion) | **non-preemptive blocking** (our bridge) |
| `r_i` | worst-case response time (arrival→completion) | per-lane lateness |
| `I_i(t)` | # instances of `i` released before `t` | — |
| `H_i(t)` | # instances of `i` with deadline ≤ `t` | — |
| `s_i(a)` | release time of `i`'s first instance in a pattern where another `i` arrives at `a` | — |
| `L` | length of first busy period in the most-demanding (**asap**) pattern | our busy-period length |
| `U_S` | utilization allocated to an aperiodic server | 0 for us (no server) |

Non-bursty task: `t_i = T_i`, `n_i = 1`, `J_i = 0`, `B_i = 0`.

---

## A2a — FEASIBILITY (Section 3; extensions §5–7)

**Theorem 3.1 (Liu & Layland), p6.** Worst-case arrival pattern = **asap** (every task released at
`t=0`, then at its max rate). If there is any overflow, there is an overflow in the asap pattern
with no idle time before it.

**Busy-period length `L` — Eq (1), p7:**
```
L^(0)   = Σ_{i=1..n} C_i
L^(m+1) = W(L^(m)),   where   W(t) = Σ_{i=1..n} ceil(t / T_i) · C_i
stop when L^(m+1) = L^(m);  then L = L^(m).
```
Converges in finite steps **iff** `Σ C_i/T_i ≤ 1` (if this fails, the set is infeasible).

**Processor demand (workload with deadline ≤ t), p7:**
```
Σ_{D_i ≤ t} ( 1 + floor( (t − D_i) / T_i ) ) · C_i
```

**Feasibility — Eq (2), p8 (NECESSARY & SUFFICIENT, preemptive, no blocking):**
for every actual deadline `d` in the first busy period,
```
d ≥ Σ_{D_i ≤ d} ( 1 + floor( (d − D_i) / T_i ) ) · C_i
```
(= Baruah et al. [3] processor-demand criterion, generalised here to **arbitrary** deadlines,
i.e. `D_i` may exceed `T_i`.)

### with release jitter (Section 5, p12)
```
W(t) = Σ ceil( (t + J_i) / T_i ) · C_i
# of i-instances with deadline ≤ t:  1 + floor( ((t + J_i) − D_i) / T_i )
Feasibility (Eq 2 w/ jitter):
   d ≥ Σ_{D_i ≤ d + J_i} ( 1 + floor( (d + J_i − D_i) / T_i ) ) · C_i
```

### with bursty / sporadically-periodic tasks (Section 6, p14–15); assumes n_i·t_i ≤ T_i
```
I_i(t) = floor((t+J_i)/T_i)·n_i
         + min{ n_i, ceil( ( t + J_i − floor((t+J_i)/T_i)·T_i ) / t_i ) }
W(t)   = Σ I_i(t) · C_i
H_i(t) = floor((t+J_i−D_i)/T_i)·n_i
         + min{ n_i, 1 + floor( ( t+J_i−D_i − floor((t+J_i−D_i)/T_i)·T_i ) / t_i ) }
Feasibility:  d ≥ Σ_{D_i ≤ d + J_i} H_i(d) · C_i
```

### with resource sharing / blocking (Section 7, p16–17) — THE BRIDGE TO NON-PREEMPTION
Preemption level:  `π_i > π_j  ⟺  D_i − J_i < D_j − J_j`.
Semaphore ceiling:  `⌈s⌉ = max{ π_i : i may lock s }`.
Blocking term:  `B_i = max{ cs_j(s) : ⌈s⌉ ≥ π_i and π_j ≤ π_i }`  (`cs_j(s)` = max time `j` holds `s`).

**Theorem 7.1 / Eq (5), p17 — SUFFICIENT feasibility with blocking.** Order tasks by increasing
`D_i − J_i`; let `k(d) = max{ k : D_k − J_k ≤ d }`. For every deadline `d` in the first busy period:
```
d ≥ Σ_{D_i ≤ d + J_i} ( 1 + floor( (d + J_i − D_i) / T_i ) ) · C_i  +  B_{k(d)}
```
`L` is **unaffected** by blocking (priority inversion only deviates the schedule, doesn't change
arrived workload).

> **Our A2a (non-preemptive):** use Thm 7.1 / Eq (5) with `B` = the **non-preemptive blocking** =
> longest single job that can still be in progress when `d` comes due. In the uniform-`k` model
> `B = (k − 1)` (one in-flight non-preemptible job, discrete time). Check it for all `d` in the
> first busy period. Cross-check the feasibility verdict against **Jeffay (1)&(2)**.

---

## A2b — WORST-CASE RESPONSE TIME / THE BOUND (Section 4; extensions §5–7)

**Lemma 4.1, p8 — ⛔ worst-case response is found in an asap busy period, but NOT necessarily the
FIRST busy period** (unlike the fixed-priority critical instant). Consequence: we must search over
release offsets `a` (see Eq 4). The paper's own example (Table 1/2, p10–11) has `r_3`'s maximum at
`a = 9`, not in the first busy period — a concrete warning.

```
s_i(a) = a − floor(a / T_i) · T_i                                   (p9)

W_i(a,t) = Σ_{j≠i, D_j ≤ a+D_i} min{ ceil(t/T_j), 1 + floor((a+D_i−D_j)/T_j) } · C_j
           + δ_i(a,t) · C_i                                          (p9)

δ_i(a,t) = min{ ceil((t − s_i(a))/T_i), 1 + floor(a/T_i) }  if t > s_i(a)
         = 0                                                 otherwise   (p10)

Busy period relative to d = a+D_i  — Eq (3), p10:
   L_i^(0)(a)   = Σ_{j≠i, D_j ≤ a+D_i} C_j  +  I_{s_i(a)=0} · C_i
   L_i^(m+1)(a) = W_i( a, L_i^(m)(a) )
   where I_{s_i(a)=0} = 1 if s_i(a)=0 else 0.
   Converges finite iff Σ C_i/T_i ≤ 1.

Response time relative to a:   r_i(a) = max{ C_i, L_i(a) − a }         (p10)

Overall — Eq (4), p11:   r_i = max_{a ≥ 0} r_i(a)
   Evaluate a in [0, L − C_i], at local maxima: values of a where some task ≠ i has deadline
   exactly d, OR all tasks synchronised (s_i(a)=0).
```

### with release jitter (Section 5, p13)
```
s_i(a) = a + J_i − floor((a+J_i)/T_i) · T_i
W_i(a,t) = Σ_{j≠i, D_j ≤ a+D_i+J_j}
             min{ ceil((t+J_j)/T_j), 1 + floor((a+D_i+J_j−D_j)/T_j) } · C_j  +  δ_i(a,t)·C_i
δ_i(a,t) = min{ ceil((t−s_i(a)+J_i)/T_i), 1 + floor((a+J_i)/T_i) }  if t > s_i(a) else 0
L_i^(0)(a) = Σ_{j≠i, D_j ≤ a+D_i+J_j} C_j  +  I_{s_i(a)=0}·C_i
r_i(a) = max{ J_i + C_i, L_i(a) − a }
r_i    = max_{ a ∈ [ −J_i , L − J_i − C_i ] } r_i(a)
```

### with bursty (Section 6, p15–16)
```
S_i(a) = a + J_i − floor((a+J_i)/T_i) · T_i            (first choice, outer-period granularity)
s_i(a) = S_i(a) − min{ n_i − 1, floor(S_i(a)/t_i) } · t_i   (refine, inner period)
W_i(a,t) = Σ_{j≠i, D_j ≤ a+D_i+J_j} min{ I_j(t), H_j(a+D_i) } · C_j  +  δ_i(a,t)·C_i
δ_i(a,t) = min{ I_i(t − s_i(a)), H_i(a+D_i) }  if t > s_i(a) else 0
```

### with blocking (Section 7) — add `B` the same way as in feasibility.
For our non-preemptive bound: the critical-instant worst case (all `Q` deadlines coincident) gives
`L ≤ (Q−1)·k + (k−1) < Q·k`, which is consistent with plugging `B=(k−1)` into this busy-period
response-time machinery. **Derive it from first principles; use this machinery as the cross-check.**

---

## Tractability / termination (Appendix A.1, p27–28)

- General convergence requirement: `Σ C_i/T_i + U_S ≤ 1` (else surely infeasible). For us `U_S=0`.
- **`L ≤ H`** where `H` = hyperperiod = lcm of the periods. So the busy-period / feasibility search
  is over a **finite, bounded** interval.
- Computation of `L` is **pseudo-polynomial** when `Σ C_i/T_i + U_S ≤ p < 1`. Each iteration step
  increases by at least `C_min/(1−U_S)`.

> **Our A2a tractability:** periods are concrete baud-derived integers, `Q` small, `U ≈ 0.12` → `H`
> small → the "test over all L" is a cheap, **exhaustive, exact** check for the submission instance.
> (The NP-hardness in Jeffay is asymptotic; it scopes only an "arbitrary-N lanes" claim.)

---

## How to use this for A2 (summary)

- **A2a (feasibility):** Spuri Eq (2) is the n&s preemptive test; Eq (5)/Thm 7.1 adds a blocking
  term `B`. For our non-preemptive engine, check Eq (5) with `B` = non-preemptive blocking, over
  all `d` in the first busy period (`L ≤ H`, cheap for us). Cross-check against Jeffay (1)&(2).
- **A2b (the bound):** Spuri Lemma 4.1 + Eq (3)/(4) is the EDF worst-case response procedure (the
  only published one). Add `B` as in Section 7. Our closed-form target `L ≤ (Q−1)k + (k−1)` is the
  critical-instant instantiation; **derive it, then cross-check it** against this busy-period
  procedure (and against the Imitator synthesis). Report it as `≤`, never `=`.
- **Don't forget:** worst case may NOT be the first busy period (Lemma 4.1) → the bound search over
  `a` is real, not cosmetic.

---

## Reference list (from pp26–27) — so we know what the citation numbers are

[1] Audsley, Burns, Richardson, Tindell, Wellings, "Applying New Scheduling Theory to Static
    Priority Pre-emptive Scheduling," Software Engineering Journal, Sep 1993.
[2] Baker T.P., "Stack-Based Scheduling of Real-time Processes," J. Real-Time Systems 3:67–99, 1991.
[3] Baruah, Rosier, Howell, "Algorithms and Complexity Concerning the Preemptive Scheduling of
    Periodic, Real-Time Tasks on One Processor," J. Real-Time Systems 2, 1990.
[4] Chen & Lin, "Dynamic Priority Ceilings...," J. Real-Time Systems 2:325–346, 1990.
[5] Dertouzos, "Control Robotics; the Procedural Control of Physical Processes," IP 74, 1974.
[6] Ghazalie & Baker, "Aperiodic Servers in a Deadline Scheduling Environment," JRTS 9:31–67, 1995.
[7] Katcher, Lehoczky, Strosnider, "Scheduling Models of Dynamic Priority Schedulers," CMUCDS-93-4.
[8] Lehoczky, Sha, Strosnider, "Enhanced Aperiodic Responsiveness...," 8th RTSS, 1987.
[9] Lehoczky, "Fixed Priority Scheduling of Periodic Task Sets with Arbitrary Deadlines," 11th RTSS, 1990.
[10] Lehoczky & Ramos-Thuel, "An Optimal Algorithm for Scheduling Soft-Aperiodic...," 13th RTSS, 1992.
[11] Liu & Layland, "Scheduling algorithms for multiprogramming...," JACM 20(1):40–61, 1973.
[12] Locke, Vogel, Mesler, "Building a Predictable Avionics Platform in Ada," RTSS 1991.
[13] Ramamritham, "Dynamic Priority Scheduling," in Real-Time Systems: Spec/Verif/Analysis, 1995.
[14] Sha, Rajkumar, Lehoczky, "Priority Inheritance Protocols...," IEEE TC 39(9), 1990.
[15] Sprunt, Sha, Lehoczky, "Aperiodic Task Scheduling for Hard-Real-Time Systems," JRTS 1:27–60, 1989.
[16] Spuri & Buttazzo, "Efficient Aperiodic Service under EDF," 15th RTSS, 1994.
[17] Spuri M., "Earliest Deadline Scheduling in Real-Time Systems," PhD diss., Scuola S.Anna Pisa, 1995.
[18] Spuri, Buttazzo, Sensini, "Robust Aperiodic Scheduling under Dynamic Priority Systems," 16th RTSS, 1995.
[19] Spuri & Buttazzo, "Scheduling Aperiodic Tasks in Dynamic Priority Systems," JRTS (to appear).
[20] Tindell, Burns, Wellings, "An Extendible Approach for Analysing Fixed Priority Hard RT Tasks," JRTS 6(2), 1994.
[21] Tindell & Clark, "Holistic Schedulability Analysis for Distributed Hard RT Systems," Microproc. & Microprog. 40, 1994.
[22] Tindell, Burns, Wellings, "Analysis of Hard Real-Time Communications," JRTS 9, 1995.

(Not present here: George/Rivierre/Spuri RR-2966 — the exact non-preemptive source — still owed.)
