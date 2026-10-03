# Phase 1 close-out — H1–H4, R1–R3, 1.2

> **Continued in [`PHASE1_CLOSEOUT_PART2.md`](PHASE1_CLOSEOUT_PART2.md)** —
> Rulings 1 and 2, the A1 lane-table digest, and the 1.5 / 1.6 freeze. The
> shipped lane table below is unchanged by that work; the suite entry point is
> now `python model/a2/run_a2.py`.

Answers spec v3.1 (housekeeping → the three pre-1.2 corrections → the `(C, J)`
frontier). **Supersedes the `r_i` and margin tables in `A2_GREEN_RESULTS.md`**
and in `A2_CLOSE_RESULTS.md`. The methods in both stand; the numbers do not.

**Reproduce — the whole block, in order:**
```
python model/a2/pyrta_src.py            # H1   discovery, both faces
python model/a2/bursty.py               # R1+R2+H3  the lane table + inertness gate
python model/a2/gate_lane_class.py      # 0.9b re-run: H3 + R1 assertions, R1's cost
python model/a2/gate_i2c_sda_read.py    # R3   SDA on the observed rise
python model/a2/frontier.py             # 1.2  the (C, J) frontier
python model/a2/gate_pyrta.py           # 1.4b foreign re-check of the new table
python model/a2/gate_twin_pair.py       # P3   now actually runs (was a false red)
bash  model/price_gates.sh              # every foreign gate priced
```

---

## The shipped lane table

`D_sched = D_tol` throughout — spec R2 separates them but Part 1 does not
optimise the assignment. The EDF key the recurrence schedules on is
`D_sched + C_i`. `C = 2` on every lane and **is still unmeasured**.

| lane | class | `T` | `n`/`t` | `D_tol` | authority for `D_tol` | key | `r` | `r−C` | margin |
|---|---|---|---|---|---|---|---|---|---|
| UART-tx 115200 | SOURCE | 434 | 1/434 | 216 | sigrok ladder | 218 | 10 | 8 | 208 |
| SPI-tx 1 MHz | SOURCE | 25 | 1/25 | 23 | derived — MB85RS64V `DS501-00015-6v1-E` | 25 | 7 | 5 | 18 |
| I²C 400 kHz | SOURCE + REACTIVE-J | 45 | 1/45 | 15 | derived — UM10204 Rev 7 T11 | 17 | 3 | 1 | **14** |
| UART-rx 115200 | REACTIVE-anchor | 4140 | 10/414 | 213 | derived — `216 − L_sync` | 215 | 9 | 7 | 206 |
| SPI-target 1 MHz | REACTIVE-abs | 400 | 16/25 | 18 | **derived — absolute budget (R1)** | 20 | 5 | 3 | 15 |

`U = 0.21388`, busy period `L = 10`, every `m_i = 1`.
**Minimum admissibility margin 14**, against a bar of 4.
**pyRTA agrees 5/5** on this set, at the real periods, with no replica and no
scaling (`gate_pyrta.py`).

> **margin = `D_tol − (r − C_i)`, not `D − r`.** The two differ by exactly `C_i`
> while `D_sched = D_tol`, and both were quoted as "the minimum margin" in the
> same arc off the same run (9 from the table column, 11 from prose). There is
> now one function, `BLane.margin()`, and the column and the prose both call it.

---

## R1 — SPI-target's deadline derived, O4 closed

**The reading that had to be corrected was mine.** I reported SPI-target's
stand-in `D = 12` as "non-load-bearing, because its binding test is 0.9b's
absolute budget rather than `D`". That is wrong in the way that matters: under
EDF a deadline **is a priority**, 12 was the tightest number in the table, and
so the stand-in was making SPI-target the highest-priority lane and therefore
setting every other lane's `r_i`. A modelled number was the scheduling key for
the whole set.

Derived from the same absolute budget that already governs the lane, expressed
in the start-delay terms every other tolerance uses:

```
D_tol = half_period − tSU(peer) − L_sync − out_reg − [C_i if C9 = COMPLETION]
      = 25 − 1 − 3 − 1 − [2]
      = 20  (C9 = START)      18  (C9 = COMPLETION)
```

**The table ships 18**, the smaller, so it is correct under either C9 outcome
and cannot be made worse by 1.3's decision.

**The falsifier did not fire.** It reorders — 18 > 15 puts I²C at the top and
drops SPI-target to second — and no margin falls below the bar. I²C `r` goes
5 → 3, SPI-target 3 → 5, minimum margin **11 → 14**.

### But R1 costs this lane frequency headroom, and that is a loss

The reorder raises SPI-target's start delay from 1 to 3 cycles, which comes
straight off its absolute budget:

| `f_SCLK` | margin at `r−C = 1` | margin at `r−C = 3` | |
|---|---|---|---|
| 1 MHz | 17 | **15** | both clear the bar |
| 2 MHz | 4 | **2** | ⛔ **was exactly at the bar, now below it** |
| 2.5 MHz | 2 | 0 | below either way |

1 MHz is what is declared, so nothing shipped moves. **The 2 MHz option is now
out of reach** without a C9 decision or a measured `C`. Recorded because R1
improved the *minimum* margin while making this one worse, and only one of those
two facts is flattering.

---

## R2 — `D_sched` and `D_tol` separated

`D_tol` is the requirement (an input, from a datasheet or a protocol table).
`D_sched` is the EDF key and a **design choice**: any `D_sched ≤ D_tol` is
sound, because the schedule then enforces something at least as strong as the
requirement. `assert D_sched ≤ D_tol` is in the constructor, not at a call site.

**Why it was needed:** deriving `D_SPI-tx = 23` in 1.1 was a change to a
*tolerance*, but because one field was both things it silently re-ordered all
five priorities and moved every `r_i`. That result happened to improve. The next
one has no such guarantee.

**The restructure is required to be inert, and that is gated** —
`assert_r2_order_neutral()`:

* **the reason** — the recurrence touches deadlines only through *differences*
  (`floor((a + J + D_i − D_j)/T_j) + 1`, and the filter `D_j > a + D_i`), so a
  uniform shift cannot move any `r_i`; with `C` uniform, `key = D_tol + C` **is**
  a uniform shift. Checked at k ∈ {1, 2, 5, 97} on three lane sets.
* **the fact** — the real five-lane table at its pre-R1 deadlines gives
  `r = [10, 7, 5, 10, 3]` under *both* conventions, lane for lane.
* **must-fire** — `D_sched > D_tol` raises.

R1 and R2 landed in one edit, which is the shape where a structural change hides
a numerical one. The inertness gate is what makes R1's reorder attributable to
R1.

---

## R3 — the I²C SDA read goes on the observed SCL rise

**Mechanism: folded into the existing REACTIVE-J high-phase release.** Same
release, same 3-FF sync, no new event, no programmed offset. The "small fixed
offset" is the service latency the release already has:

```
delta = L_sync + (r_I2C − C_I2C) + in_reg = 3 + 1 + 1 = 5 cycles
```
The sample lands `N_low + delta = 85` cycles after the SCL fall.

`T_AA` becomes a **check**, never a placement: `T_AA ≤ N_low − delta_max`, i.e.
`45 ≤ 80 − 5 = 75`. Holds with 30 cycles spare. It holds *more easily* under
clock stretching, because a stretched low phase moves the rise later and only
increases `N_low`.

### What this gate does **not** show

The must-fire rejects the whole region before `T_AA` (offsets 0–44), which is
the error a counted-offset scheme makes when someone later optimises the offset
down. **It does not refute the placement I had proposed.** "Centre the read in
the valid window `[T_AA, N_low]`" gives offset 62 with half-width 17 — that is a
coherent derivation and the data *is* valid there. My stated reason for killing
it ("standard-mode `T_AA` = 150 cycles exceeds the 80-cycle low phase") was
**wrong**: it compares a standard-mode `T_AA` against a *fast-mode* low phase.
At 100 kHz the period is 500 cycles and the low phase ~267, so the window is
wide open.

**What actually retires the counted offset is cost, measured:**

| mode | period | slack | `N_low`/`N_high` | counted window | ±tol | rise-release slack |
|---|---|---|---|---|---|---|
| standard 100 kHz | 500 | 65 | 267/233 | [150, 267] | **±58** | 228 |
| fast 400 kHz | 125 | 30 | 80/45 | [45, 80] | **±17** | 40 |
| fast-mode+ 1 MHz | 50 | 0 | 30/20 | [28, 30] | **±1** | 15 |

The counted offset is **sound in every mode** and merely worse: a per-mode
constant that has to be re-derived, whose tolerance collapses exactly where
everything else is tight, bought against a lane whose binding tolerance is 15.
The observed rise needs no table at any rate, for any peer.

### Two things that table settles as a side effect

* **The Fast-mode-Plus exclusion is reproduced independently** — the slack row
  is 0 because this part's own `THIGH`+`TLOW` minima are 400 + 600 = 1000 ns,
  exactly the 1 MHz period.
* **And it is a DEVICE constraint, not an I²C one.** UM10204 Table 11 allows
  260 + 500 = 760 ns at Fm+. The MB85RC256V is stricter than the bus spec here,
  so "no Fast-mode Plus" is scoped to **this part** and must not be recorded as
  a protocol fact.

### The folded-vs-separate fork, priced rather than assumed

"It costs nothing" is true of the folded mechanism and false of a separate
release at `rise + delta`, which makes the lane's minimum inter-event spacing 5
instead of 45:

| lane | `r` folded | `r` separate | Δ |
|---|---|---|---|
| UART-tx | 10 | 14 | **+4** |
| SPI-tx | 7 | 9 | **+2** |
| UART-rx | 9 | 11 | **+2** |
| SPI-target | 5 | 5 | 0 |
| I²C | 3 | 3 | 0 |

**The minimum margin is 14 either way** — which is exactly why the minimum is
the wrong thing to quote here. The lane that sets the minimum is the one that
does not move, so "it costs 0 cycles of minimum margin" would be arithmetically
true and would hide three lanes losing 2–4 cycles each. Separate is *feasible*;
it buys nothing folded does not already give. **Folded is the design.**

⚠ **What folding owes:** the high-phase service now samples a pin as well as
releasing SCL, so its `C` may not be 2. One more place for Phase 2 to measure.

---

## 1.2 — the `(C, J)` frontier

All earlier frontiers are superseded: four deadlines moved, and a frontier is
made of deadlines.

**`C` enters the two tests differently, and that is the point of printing two.**
Source lanes take `C` once, through `r`. SPI-target takes it **twice and in the
same direction** — through `r`, and through `D_tol` itself, which *is* a function
of `C` at C9 = COMPLETION. That second path is what a frontier sweep normally
misses, because it looks like a per-lane constant and is not.

`J` is likewise two independent terms that **add** on the I²C lane: `J_pipe`
(registering the EDF winner — a property of the engine, applies to every lane)
and `L_jit = 1` (the synchroniser's async-capture ambiguity, on the REACTIVE-J
action only).

### Minimum admissibility margin over `(C, J_pipe)`

**C9 = pin at START**

| C \ J | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| 1 | 14 | 13 | 12 | 11 |
| 2 | 13 | **12** | 11 | 10 |
| 3 | **12** | 11 | 10 | 9 |
| 4 | 11 | 10 | 9 | 8 |
| 5 | 9 | 8 | 7 | 6 |
| 6 | 6 | 5 | 4 | 3 |
| 7 | 3 | 2 | 1 | 0 |

**C9 = pin at COMPLETION**

| C \ J | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| 1 | 14 | 13 | 12 | 11 |
| 2 | 13 | **12** | 11 | 10 |
| 3 | **12** | 11 | 10 | 9 |
| 4 | 9 | 8 | 7 | 6 |
| 5 | 5 | 4 | 3 | 2 |
| 6 | 3 | 2 | 1 | 0 |
| 7 | 1 | 0 | −1 | −2 |

Frontier at `J_pipe ≤ 1`: **`C ≤ 6` at START, `C ≤ 5` at COMPLETION.**

### The binding lane changes hands along the sweep

At `J_pipe = 1`:

| C | binding @ START | min | binding @ COMPLETION | min |
|---|---|---|---|---|
| 1–3 | I²C | 13→11 | I²C | 13→11 |
| 4 | I²C | 10 | **SPI-target** | 8 |
| 5–7 | **SPI-tx** | 8→2 | I²C | 4→0 |

So **a frontier is not a ceiling on `C` alone** — the admissible region is not a
rectangle and `C ≤ k` is not a safe summary of it.

### The target 1.2 hands to 1.3

`(C_i, J_pipe) = (2, 1)` on every lane, priced at **C9 = COMPLETION** (the worse
variant), so the target holds whichever way 1.3 decides.

| lane | `C_i` | `J_i` | margin | headroom before the bar |
|---|---|---|---|---|
| UART-tx | 2 | 1 | 207 | 203 |
| SPI-tx | 2 | 1 | 17 | 13 |
| I²C | 2 | **2** | **12** | 8 |
| UART-rx | 2 | 1 | 205 | 201 |
| SPI-target | 2 | 1 | 14 | 10 |

### ⭐⭐ The 1 MHz feasibility does not decide the pipeline

| candidate | C9 = START | C9 = COMPLETION | |
|---|---|---|---|
| unpipelined `C=3, J=0` | min margin **12** | min margin **12** | clears under both |
| pipelined `C=2, J=1` | min margin **12** | min margin **12** | clears under both |

Both candidates come out at 12, under both C9 variants, and in both the binding
lane is I²C — whose margin is *identical* at `(3,0)` and `(2,1)` because the
extra service cycle and the extra jitter cycle cost it the same.

**1.3 must therefore choose on area and critical path, not on schedulability.**
Saying so is this file's job; pretending a preference fell out of the numbers
would not be.

**What C9 is worth, in the unit 1.3 actually spends:** one cycle of service
budget (`C ≤ 6` at START vs `C ≤ 5` at COMPLETION). Same decision 0.9b priced at
~0.5 MHz of SPI-target headroom.

---

## H — housekeeping

### H1 — one pyRTA discovery function, and the gates are priceable now

`gate_pyrta.py` had a discovery function with a disk-walk fallback;
`gate_twin_pair.py` had `os.environ.get("PYRTA_SRC")` and nothing else. So with
a clone on disk and importable, **the twin-pair gate reported "pyRTA not found …
the by-VALUE direction is UNPINNED" while the pyRTA gate reported PASSED, off
the same library, in the same run.** A red whose message is a plausible
description of a real gap is the worst kind: it reads as a known limitation, so
nobody looks.

**And the fallback made both gates unpriceable, which is the worse half.**
`price_gates.sh` works by removing the tool and requiring red — with an
unconditional disk walk there was no way to remove it. The contract is now
explicit:

| `PYRTA_SRC` | behaviour |
|---|---|
| unset | search TEMP and `~` for a clone (convenience) |
| set to a pyRTA `src/` | use exactly that, no search |
| **set to anything else** | **return None. Do not search.** |

The third line is what makes the gates priceable. Both faces are exercised by
`pyrta_src.py`'s self-test, which is **red unless both the success and the
refusal path have run** — a discovery function seen only to succeed is as
unmeasured as an audit that has never rejected anything. Both gates are now in
`price_gates.sh` and both go red with the authority removed.

`pyrta_src.py` is deliberately *not* priced there: it manages `PYRTA_SRC`
internally to reach both faces, so an outer setting cannot take the authority
away from it, and the attempt would be scored as a failure of the wrong thing.

**Two stale copies found while wiring it:**
* `gate_pyrta.py` carried a hand-copied second lane table. It now imports the
  parameters from `bursty.py` and keeps only the expected `r_i` hand-typed —
  that split is the pin. A gate that imported the answers too would compare the
  recurrence against itself and agree by construction.
* `periodic_equivalence()` hard-coded UART-rx as `n=10, t=434, T=4340`, long
  after P1 re-synthesized the lane to `t=414, T=4140`. It passed, because
  `n·t == T` holds for both — so a green check was certifying the gaplessness of
  a lane the project no longer ships, and that substitution is what the whole
  pyRTA comparison rests on. Now read off the objects.

### H2 — the branch-point audit is scoped, not retired

It reads `model/ta02/interp.py`, and TA-02's architecture claim is **retracted**
(the queue architecture stands). So a green there says something about a machine
that is not the design. Within its own subject it is a lint with four confirmed,
unfixed blind spots (`RT1_BUILT.md` 1–3): it passes **9 of 11** adversarial
mutants that branch on non-table state, equates "branch point" with `If`/`IfExp`
nodes, kills one mutant for the wrong stated reason, and reads 1 of 6 callables.

Actions taken: a scope banner at the top of the file naming what it is not
evidence of; reclassified in `run_ta02.py` from `gate` to **`lint`**, so its
colour no longer enters the gate count. The runner now prints a `LINTS:` line —
the gate count moved 8 → 7 and a headline number that changes silently is how a
scoping decision becomes a quiet subtraction.

**The genericity claim rests on the behavioural gate** (`gate0_spi.py`), which
is independent of this file. "The branch-point audit is green" is not citable.

### H3 — UART per direction, and the two numbers now get compared

UART-tx `D_tol = 216` (SOURCE, sigrok-adjudicated). UART-rx `D_tol = 213`
(REACTIVE-anchor: the sample grid hangs off a *detected* start edge, which lags
by `L_sync`, so the early-side constraint tightens to `T − half − L_sync`).

Gate 0.9b had been **deriving and printing 213 while the lane table carried
216**, and nothing compared them. A number that is only ever printed is not in
the model. Both the H3 and the R1 derivations are now asserted against the table
inside 0.9b, and disagreement reds the gate.

`T_min = 414` confirmed in both paths — `bursty.UART_RX.t = 414` and the period
pyRTA is given — from the re-synthesis at **`2595357`** ("P1+P2+P3: UART band
re-synthesized at T_min=414"). Adopting 213 drops UART-rx `r` from 10 to 9: with
an earlier deadline than UART-tx it is no longer tied with it in the EDF order.

### H4 — not done; deletion is not mine

`refs/ieee_try.bin` and `refs/t2.bin` are **safe to delete** (bot-block HTML
saved with a `.bin` extension, zero references in the tree). `refs/` is
gitignored with the guard committed, so neither is in the repository and
deleting them changes nothing that ships.

---

## What is still owed

* **`C` is unmeasured on every lane.** Every margin above traces to one
  `ARCH_PREREG_01` sentence. The ≥ 4 bar is the reserve against that and
  **retires after Phase 2**, at which point `frontier.py` is re-run and margins
  are quoted on the measured value.
* **The engine is not built.** `uio_out` is tied low, so no pin can drive a 1.
* **Exactness.** pyRTA's bound is *sufficient*, not exact. `nptest` (Nasri &
  Brandenburg, RTSS 2017) is exact on a uniprocessor and is the next escalation;
  it needs a C++14/TBB build under WSL and has not been run.
* **`tSU(master)` is parametric** at 1 cycle — no SPI master device is picked.
  It is an input to R1's derived deadline, so picking one is a real decision.
  With 20 cycles of margin on SPI-tx a 10× larger value would still pass.
* **The SPI AC table is a single-source visual read.** Its text layer is
  scrambled (values interleaved with the next row's label) and Mouser served a
  bot page instead of a mirror. The I²C table *was* verified out of the text
  layer, and every I²C number in this document is quoted from it.
