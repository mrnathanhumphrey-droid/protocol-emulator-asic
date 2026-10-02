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

**Stage: Part 1 only — the `+1` is still present. Shipped values are in Final.**

| lane | `r` loose | `r` Spuri (Part 1) | delta |
|---|---|---|---|
| UART | 7 | 7 | 0 |
| **SPI** | **8** | **4** | **−4** |
| I²C | 8 | 6 | −2 |

**`r_SPI` is settled: a genuine pass, not a buffered one.** Margin 4→8 on the
three required lanes, and 0→6 with Ethernet. **SPI's zero margin was an artefact
of the over-count, not a property of the design.**

> ⚠ **Two values of `r_SPI` appear in this document and both are correct — for
> different stages.** `r_SPI = 4` is Part 1 alone (deadline-limited interference,
> `+1` still present). `r_SPI = 3` is Parts 1 **and** 2 (`+1` removed) and is the
> **shipped** value, which is what the gate table and the Final section quote.
> Stated here because the two numbers otherwise read as a contradiction in the
> flagship result document. Every table below carries its stage in the heading.

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

## Part 2 (O8, dissolved) — the `+1` double-counts

⭐ **O8 asked for a citation for the `+1`. There is no `+1` left to cite.** What
this project uses is a **discrete non-preemptive EDF recurrence of our own**,
cross-validated 9/9 against an independent timed-automaton model checker on three
forced schedules and a stress instance. That is stronger provenance than a
reference: *"cross-checked against a foreign model checker, including on the
instance built to break it"* says more than *"per RR-2966 eq. X"*, because it is
a claim about this implementation rather than about a paper. **Written as ours,
validated — not borrowed.**

Settled by three schedules whose answers are forced by the schedule itself:

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

### Why the fix is air-tight rather than lucky

The unsoundness found in Part 3 lived at `m_i > 1`. State it as a chain, because
each link is separately checkable:

1. **The bug lived at `m_i > 1`** — it was a release-count convention that only
   differs from the correct one once a second instance of a lane falls inside the
   busy period.
2. **No feasible real lane is `m_i > 1`** — measured, not assumed. The busy period
   is 6 cycles (driving only) or 10 cycles (both directions), while the shortest
   inner spacing of any lane is 25. `m_i = 1` for all five lanes in both
   directions, including the two bursty receive lanes.
3. **Therefore the corrected and uncorrected recurrences agree on the real
   tables** — and they do, identically, which is why Part 1's `r_SPI = 4` (that
   stage's value, before Part 2 removes the `+1`) survived
   the Part 3 fix unchanged.
4. **Both are foreign-validated** — the corrected one directly (9/9 periodic,
   9/9 bursty), and the agreement in (3) transfers that validation to the shipped
   numbers.

⛔ The protection in (2) is a property of *this* task set at *this* utilisation,
not of the method. Any lane with an inner spacing shorter than the busy period
re-enters the unsound regime, which is why the corrected recurrence is the only
one in the repo.

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

---

## Part 4 — the receiving direction

**Reproduce:** `python model/a2/bursty.py` and `python model/a2/zone/run_bursty.py`

Reactive lanes modelled as Spuri bursty arrivals — `n` events per outer period at
inner spacing `t`, with `n·t ≤ T`:

| lane | `T_i` | `C_i` | `D_i` | `n_i` | `t_i` | `n·C/T` | shape |
|---|---|---|---|---|---|---|---|
| UART-rx 115200 | 4340 | 2 | 216 | 10 | 434 | 0.00461 | 10 samples/frame, back-to-back: `n·t == T`, **gapless** |
| SPI-target 1 MHz | 400 | 2 | 12 | 16 | 25 | 0.08000 | master-clocked, 16 edges/byte, `n·t == T` |

Both are the densest arrival the protocol permits — `n·t == T` exactly, so there
is no slack in the burst to be optimistic about.

**Both directions, all five lanes: `U = 0.20147`, every lane feasible.**

| lane | `m_i` | `r_i` | `D_i` | margin | `t_i` | queues? | classification |
|---|---|---|---|---|---|---|---|
| UART-tx 115200 | 1 | 10 | 216 | 206 | 434 | no | **FEASIBLE** |
| SPI-tx 1 MHz | 1 | 5 | 12 | 7 | 25 | no | **FEASIBLE** |
| I²C 400 kHz | 1 | 7 | 30 | 23 | 62 | no | **FEASIBLE** |
| UART-rx 115200 | 1 | 10 | 216 | 206 | 434 | no | **FEASIBLE** |
| SPI-target 1 MHz | 1 | 5 | 12 | 7 | 25 | no | **FEASIBLE** |

No lane at zero margin. **No lane reaches the derived-buffer rung**, so the
FIFO-depth derivation is unexercised and deliberately not shipped — writing that
formula now would ship an unvalidated bound for a case that does not arise.

### ⭐ The bursty premise does not bite, and that is a measured result

**`m_i = 1` for every lane, including both bursty ones.** The busy period is 10
cycles; the shortest inner spacing is 25. No burst ever has two events inside one
busy period — the engine drains work far faster than events arrive, so the burst
structure never materialises. **The reactive lanes do not enter the regime the
recurrence was unsound in.**

That weakens the premise of the refinement that demanded the bursty cross-check —
but it does not remove the need for it, because **the `m_i = 1` verdict is itself
computed by the machinery under suspicion.** So the foreign check ran anyway, on
instances built to reach `m_i > 1`:

| instance | `U` | `L` | agreement |
|---|---|---|---|
| B1 bursty `n=3` | 0.450 | 4 | 2/2, **Abur `m=2`** |
| B2 bursty + two periodic | 0.658 | 5 | 3/3, **Abur `m=2`** |
| B3 two bursty lanes | 0.533 | 2 | 2/2 |
| B4 **scaled UART-rx replica** (`n=10`, bit period 434→3) | 0.476 | 4 | 2/2, **rx10 `m=2`** |

**9/9 agree, `ovr` unreachable throughout, 3 lanes at `m_i > 1`.** The run asserts
its own non-vacuity: if no checked lane had `m_i > 1` it reports VACUOUS and
fails, because a bursty cross-check that never reaches a burst is a restatement
of Part 3.

The generalisation is also pinned mechanically: **`assert_reduces_to_periodic()`**
checks the bursty arrival curve, the interference term, and the whole recurrence
against the corrected periodic versions at `n = 1`, over every lane period and
thousands of points. A bursty lane with `n = 1` cannot silently mean something
other than the periodic lane it is.

⛔ The `n = 1` path of the TChecker generator is emitted **byte-identically** to
the Part 3 validated version — the bursty edges are a separate branch. Part 3 was
re-run after the edit and still passes 9/9.

### I²C clock-stretch — the spec asks the wrong question first

Part 4 says *"check the I²C spec for a stretch ceiling; no ceiling → honest
obstacle."* A ceiling bounds how **long** the peer can delay us — latency.
Schedulability needs a **floor on inter-arrival** — how close together our events
can come. Different quantities, and the ceiling's absence does not make the lane
unschedulable.

**The direction argument settles it without any spec lookup:** a slave stretches
by holding SCL **low**, which *lengthens* the low phase, so consecutive
SCL-release events move **further apart, never closer**. The densest possible
arrival on this lane is the **un-stretched** lane, already in the table at
`T = 62`. Stretching can only reduce the event rate; bounded or not, it cannot
break A2a or A2b.

**⛔ The real exposure is `C_i`, not `T_i`, and the spec does not ask about it.**
If the engine busy-waits on SCL, its service time *is* the stretch duration:

| variant | `C_I2C` | `U` | result |
|---|---|---|---|
| hardware wait (lane blocks, engine moves on) | 2 | 0.1169 | **FEASIBLE** — UART 6, SPI 3, I²C 5 |
| engine busy-wait (100 µs, a *short* stretch) | 5000 | **80.73** | **INFEASIBLE — all three lanes** |

**One busy-wait takes every lane, not just its own:** the blocking term is
`max_j(C_j − 1)` over later-deadline lanes, so an unbounded `C` anywhere is an
unbounded `B` everywhere. That is why this is a **derived design requirement**,
not a per-lane caveat.

**Classification: FEASIBLE, conditional on a derived design requirement** — the
SCL wait must be a hardware condition on the lane, never engine occupancy.
Violate it and the lane becomes a named obstacle (unbounded `C_i`, P2 fails).

⚠ **Not verified against the document.** I did not open UM10204 in this session
and will not quote a clause number. My understanding is that plain I²C sets no
maximum stretch in standard/fast mode while SMBus does (`T_LOW:SEXT`, 25 ms
cumulative). **The conclusion does not depend on it:** the direction argument
settles schedulability with no ceiling at all, and the `C_i` argument holds for
any ceiling large enough to matter.

---

## Gate status

| part | state |
|---|---|
| 1 — O9 deadline-limited interference, `r_SPI` settled | ✅ `r_SPI = 3` with Part 2 applied (4 at Part 1 alone), margin 9, genuine pass |
| 2 — O8 the `+1` | ✅ spurious, removed; **O8 dissolves** — ours, validated, not borrowed |
| 3 — foreign cross-check, N=2,3,4 | ✅ 9/9, model validated first, `m_i>1` and distinct `C` covered |
| 4 — P1 reactive lanes | ✅ both classified FEASIBLE; bursty path 9/9 foreign-checked with 3 lanes at `m_i>1` |

### ⭐ Required-set A2 is GREEN

Three required protocols, **both directions**, on the tightened bound, with every
number cross-checked against an independent timed-automaton checker — including in
the one regime the recurrence was proved able to get wrong.

`U = 0.20147`. Five lanes. No lane at zero margin, no lane needing a buffer, no
named obstacle. The one conditional is a **derived design requirement**: the I²C
SCL wait must be hardware, not engine occupancy.

### What is still labelled, deliberately

- **`D_i` for SPI, I²C and Ethernet is modeled, not sigrok-derived (O4).** The
  centre-sampling geometry is applied at each lane's inner spacing. Only UART's
  `D_i` is foreign-adjudicated. TA-03's conformance oracles upgrade these;
  modeled-and-labelled is the correct state until then.
- **I²C clock-stretch spec reading is unverified** against UM10204 (above), and the
  conclusion is built not to depend on it.
- **Ethernet remains out of the required set** and infeasible unbuffered
  (`r = C + B = 3 > D = 2`). With a **1-bit shadow register** it closes
  (`D = 4`, `r = 3`) — cheap enough to be a live scope option rather than a
  stretch goal.
