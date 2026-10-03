# Phase 1 close-out, part 2 — Rulings 1 & 2, A1, and 1.5 / 1.6

Answers the rulings issued after `4c22dca`. Continues
[`PHASE1_CLOSEOUT.md`](PHASE1_CLOSEOUT.md), which covers H1–H4, R1–R3 and 1.2.

**Reproduce:**
```
python model/a2/run_a2.py            # the whole suite + the digest meta-check
python model/a2/run_a2.py --price    # inject a stale lane table; RED is the PASS
bash  model/price_gates.sh           # every foreign gate, authority removed
```
**Suite: 17 of 17 gates green, one lane table, no gate opted out.**
**Pricing: 9 of 9 red.**

---

## A1 — the lane-table digest, and why the obvious version would not have worked

Every gate prints `LANE-DIGEST base=… used=…`; `run_a2.py` fails the run if any
two disagree. **Base digest `8ea5756203e1`, reported by 10 of 10 gates that
consume the table.**

> **The obvious form of this check would have passed on both of the stale copies
> that prompted it.** If each gate digested the table it *imported*, then a gate
> that imports the table and hands the analyser a hand-typed copy prints a
> matching digest while using the copy — the guard passing *because* of the
> defect it screens for. So there are two digests: `base` (the shipped table)
> and `used` (what the analyser actually received). A hand-typed copy moves
> `used` and leaves `base` alone. That asymmetry is the whole mechanism.

Three ways the run fails: a gate exits non-zero; two gates report different
`base`; or a gate that consumes the table prints **no** digest — which is why
`EXPECT_DIGEST` is an explicit list rather than "whatever showed up". A gate that
stops printing its digest would otherwise leave the cross-check silently and the
run would go green with fewer participants than it declared.

**Priced by mutating the artefact, not by removing a tool.**
`model/a2/_price_stale_lane_table.py` is a deliberate mutant: it analyses the
table as it stood at `e586ad4` (SPI-target `D_tol=12`, UART-rx `216` — the real
previous values, because the defect being priced is "a copy that was right when
it was written") and declares no variant. `run_a2.py --price` adds it and
**inverts its own verdict**, so a *green* pricing run would mean the meta-check
is blind. Result: **15 of 15 gates exit 0 and the run still goes red**, on the
undeclared-variant arm specifically — not on an exit status, which the ordinary
"N of M" count already catches.

Found while wiring it: `gate_i2c_phase.py` rebuilt its lane set with the legacy
positional shape, which round-trips `D_tol` only by arithmetic accident and
**silently drops `J`**. Harmless today because those four lanes have `J = 0`;
the first lane to carry release jitter would have had it quietly removed.

---

## Ruling 1 — pipelined `C=2, J=1`, C9 = START. Adopted, with its conditions.

**(i) EDF keys in per-lane registers** — ~5 × 16 = 80 flops, off the critical
path. Recorded with the reason, because it is not a detail: if winner selection
read memory, the pipeline register would sit *after* the mux access it was added
to avoid, and the fetch problem would move rather than go away. For scale, the
design is 2,946 cells at 6.28 % utilisation with 535 flops, **512 of them the
program store** — so 80 more is ~15 % of the non-store flops and invisible in
area.

**(ii) `M-PREFETCH-STALE`, named now** — stage 1 drives the pin from the
descriptor prefetched for the *previous* winner (`desc_q` loaded from
`winner_d1` rather than `winner`). Survives any check that only asks *whether* a
pin moved; killed by byte-exactness, because the wrong lane's bit pattern lands
on the wrong pin at the right time.

⛔ **The arm must run a multi-lane program or it is vacuous.** With one live lane
the previous winner *is* the current winner, so a single-lane test cannot
distinguish the two; the mutant is only reachable with ≥ 2 lanes live
simultaneously.

**(iii) `D_tol`(SPI-target) stays 18**, labelled *conservative, C9-independent*,
lifting to 20 only when Phase 2 **measures** the pin moving at service start.
Asserted in 0.9b against the **derivation** rather than against the literal 18,
so it tracks `tSU` / `L_sync` / `out_reg` if any of them move.

### 2 MHz is pre-registered rather than given up

> SPI-target 2 MHz is admissible **iff** (a) Phase 2 measures `C = 2` exactly,
> **and** (b) the recomputed absolute margin at 2 MHz is > 0, **and** (c) C9 =
> START is *measured* in the built RTL — the same evidence that lifts `D_tol`
> 18 → 20.

⭐ **(a) is load-bearing and not redundant with (b).** Measured, the 2 MHz margin
is **3 / 1 / 0 at `C` = 2 / 3 / 4**. At `C = 3` condition (b) *still holds*, so
2 MHz is kept closed by (a) alone.

⛔ I first wrote this must-fire as "at `C = 3` the margin falls below 0". It does
not — it is 1. Computing it made the arm **sharper**, not weaker: the interesting
fact is precisely that (b) would pass there.

---

## Ruling 2 — absolute counter, long waits as chained re-arms. Adopted.

The ruling removed my premise rather than accepting it. I had framed the wrap
bound as an obligation on the programmer, which made it a spec decision. As a
chain of loader-split no-op re-arms it becomes a **per-action property checked at
load**, and the programmer never sees 32,768 cycles as a limit — the same move as
the rest of the admissibility work, for one opcode.

**Cost in A2, computed at three rates:** 0 cycles of minimum margin at the legal
rate (`T` = 32767), at the ruled rate (`T` = 16384), and with **five
simultaneous chains**.

⛔ **But the minimum is not the whole story — the same statistic trap flagged in
R3.** UART-tx pays **+1** (`r` 10 → 11, margin 208 → 207). It pays because the
re-arm's enormous `D_tol` takes the latest deadline from it, so UART-tx stops
being the lane nothing can block and starts charging `B = 1` like the others.
206 cycles of margin absorbs it; a cost the minimum hides is still a cost.

⛔ **The re-arm must stay a no-op, and that is schedulability, not tidiness.** Its
only route to harm is the non-preemptive blocking term `max{C_j − 1 : D_j > a +
D_i}`. At `C = 2` it contributes `B = 1`, which every lane was already charging
for some other lane. At `C = 4` and `C = 6` the minimum margin falls to **12 and
10** — it is the cheapest action in the instruction set or the most expensive
lane in the set.

### ⭐ A requirement nobody asked for: add to the *stored* timestamp

Both forms are one adder and look equally reasonable at the RTL:

| form | drift over `k` chunks |
|---|---|
| `next = stored_timestamp + chunk` | **exactly 0 at every k** |
| `next = now + chunk` | `k × (r − C)` — **grows with the delay** |

| programmed delay | chunks | `stored+chunk` | `now+chunk` |
|---|---|---|---|
| 655 µs | 1 | 0 | 10 |
| 10 ms (a sensor poll) | 16 | 0 | 160 |
| 1 s | 1,526 | 0 | **15,260** |

The error is ~0.03 % and reading it as a percentage is the mistake: it is
unbounded-in-`k` drift on a timing engine whose entire claim is that it does not
drift. **It is invisible at `k = 1`.**

**Must-fire named:** program a 2-chunk wait and require the final action
byte-exact at the un-chained timestamp. A relative re-arm fails it by 20 cycles.

**Foreign-checked:** pyRTA agrees **6/6** on the augmented set.

---

## 1.5 — descriptor freeze. Two findings that change the design.

Every field traces to a spec item or the pre-reg; none was cut. Derived encoding:
**per-lane register state 52 bits × 5 lanes = 260 flops**, global 17 → **277 new
engine flops**, against 23 non-store flops today.

### The timestamp width, derived

Floor is **9 bits**, from `spread + max r = 211 < 2^(N−1)`; the live EDF keys are
`[17, 20, 25, 215, 218]`.

⛔ The `+ max r_i` term is not decoration: a deadline stays live until its job
*completes*, so the oldest live deadline can be up to `r_i` in the past relative
to its own release. Omitting it would make the condition a statement about
releases rather than about what is in the comparator.

⭐ **Delay length does not enter the floor at all**, because Ruling 2's chains
decouple the two — and the re-arm rate **never binds the schedule at any N down
to the floor** (minimum margin 14 at N = 9 … 20). So **N = 16 is headroom, with
7 bits available to give back** if area or timing ever asks. That is a better
thing to know than "16 because 16 is a nice number".

### ⛔⛔ F1 — the program store is an order of magnitude too small

| | |
|---|---|
| program action word | 23 bits → **3 bytes** |
| store at `AW = 6` | 64 bytes → **21 actions** |
| one UART frame (10 edges) | 10 actions |
| one SPI byte (16 edges) | 16 actions |
| one frame on each required protocol | **~44 actions = 132 bytes** |

**It does not fit.** `AW ≥ 8` (256 B) for one frame each; `AW = 9` (512 B) for a
program with room to be interesting — store flops 512 → 4,096. This is not a
tuning question; it is the difference between a demo and the object.

### ⛔⛔ F2 — widening it walks into the critical path, and both have one fix

The store is read through `mem[…]` into a **combinational pad feedthrough**,
already the worst path in the design at 18.4388 of 20 ns. Deepening the store
deepens that mux, so **store depth and the critical path are one decision**.

⭐ Both are fixed by the same change: **register the readback.** The feedthrough
exists only because `uo_out` presents `mem[rd_ptr]` combinationally. A register
there costs 8 flops, retires the only nearly-full path on the chip, and makes
store depth a question about area alone. ⚠ It moves the existing cocotb readback
test by one cycle, which is why it is a ruling and not a tidy-up.

### F3 — is `D_tol` a flop or loader metadata?

The engine datapath never reads it; only an admissibility checker would. In
silicon it costs 40 flops; as loader metadata it costs nothing and the check runs
at load. The ruling said "separate fields" — this asks whether *field* means
silicon. It turns on whether the admissibility hook is ever to run on-chip.

### One figure I was given and am not repeating

P-ATOMIC arrives with "about 350 cells" attached. **I can find no basis for that
number anywhere in this repository** — not `ARCH_PREREG_01.md`, not
`SILICON_EVIDENCE.md`, not any results doc. Derived from scratch: 16 flops
(mask + data) plus a ~30-cell apply network → **~46 cells, about 8× smaller**.
Either 350 scopes something larger than the field (a whole atomic-group action
path, perhaps) or it is stale. Recorded as a **discrepancy**, not reconciled by
guesswork.

### Drive mode — structural rather than tested

`uio_out[i] = data[i] & pushpull[i]`. With `pushpull[i] = 0`, `uio_out[i]` is
constant 0, so `uio_oe[i] && uio_out[i]` is **unsatisfiable** — the strongest
form of "open-drain never drives high": not untested, impossible.

Must-fire, both faces: (a) `pushpull=0` → the enable asserts and the output stays
0; (b) `pushpull=1` → **both levels appear at the pin**. ⛔ **Face (b) cannot
pass today**, and a suite carrying only face (a) is green on the shipped RTL —
the "too simple to reach the broken path" shape exactly.

### P-ORDER — no new fields, and that is the point

Ordering between lanes is expressed as timestamp **offsets** in the program, not
as a priority field. The EDF key already orders everything; a second ordering
mechanism would be a second scheduler, and the two would disagree somewhere.

---

## 1.6 — thirteen admissibility conditions, every one with a firing witness

**All load-time. None runs in the engine datapath** — the hardware assumes
admissibility and the loader guarantees it. That is what keeps the engine small.

| id | condition | shipped set | must-fire |
|---|---|---|---|
| 1.6a | `r_i ≤ t_i` (one queue slot) | tightest `r−t = −18` | dense lane `r=14 > t=2` |
| 1.6b | spread + max r < `2^(N−1)` | `211 < 32768` | deadlines 32768 apart |
| 1.6c | per-action delay < `2^(N−1)`, at load | 32767 cyc = 655 µs | 32768 → split into chunks |
| 1.6d | `D_sched ≤ D_tol` | equal on every lane | constructor raises |
| 1.6e | `C_i + B_i ≤ D_tol` **[necessary-only]** | slack 12 on I²C | `2 + 8 > 1` |
| 1.6f | SOURCE: `r − C ≤ D_tol` | tightest 14 on I²C | `r−C = 1 > D_tol = 0` |
| 1.6g | REACTIVE: absolute budget + C9 | `7 ≤ 24`, `9 ≤ 24` | 3 MHz: `9 > 7.3` |
| 1.6h | P-ORDER: `N_sep − (r−C) ≥ t_min` | `N_sep ≥ 6` | `N_sep = 1` vs `r−C = 5` |
| 1.6i | min pulse ≥ `T_SP` = 3 cyc | `45 ≥ 3` | a 2-cycle SCL pulse |
| 1.6j | no MISO sample the cycle after SCK↓ | `t_ODV` = 1 | sample at offset 1 |
| 1.6k | peer bounds | `t = 414 ∈ [414, 458]` | `Te = 413` |
| 1.6l | no I²C Fm+ **on this part** | 400 + 600 = whole period | Fm+ program rejected |
| 1.6m | **pre-reg:** 2 MHz reopening | margin 3 at the ruled point | `C=3` → (a) alone closes it |

⛔ **1.6e is necessary-only** and is labelled so: passing it does not imply
feasibility, it is a cheap screen that rejects hopeless programs before the
response-time fixpoint runs. 1.6f and 1.6g are the sufficient ones.

⛔ **Two of these must-fires were vacuous when first written.** 1.6a compared
`r = 6 > t = 6` and 1.6f `r − C = 1 > D_tol = 1` — both non-strict against the
very threshold they test, which is the "falsifier whose threshold sits where its
named bug cannot reach it" shape. Caught only because every condition is required
to produce a firing witness.

⚠ **1.6m quotes the margin at the *ruled design point*, not the shipped table,
and the two differ.** The table carries `J = 0` → `r − C = 3` → 2 MHz margin
**4**. The design that will be built is pipelined at `J_pipe = 1` → `r − C = 4` →
margin **3**, which is why 2 MHz is closed. Printing the table's 4 here would
have read as "2 MHz already clears the bar", off the same run that says it does
not.

---

## Still owed

* **`C` is unmeasured on every lane.** Every margin traces to one
  `ARCH_PREREG_01` sentence. The ≥ 4 bar is the reserve against that and
  **retires after Phase 2**.
* **The engine is not built.** `uio_out` is tied low, so no pin can drive a 1.
* **Three 1.5 flag-backs are open:** store depth (F1), register the readback
  (F2), `D_tol` in silicon or at load (F3).
* **Exactness.** pyRTA's bound is sufficient, not exact. `nptest` (Nasri &
  Brandenburg, RTSS 2017) is exact on a uniprocessor, needs a C++14/TBB build
  under WSL, and has not been run.
* **H4 is still not done** — `refs/ieee_try.bin` and `refs/t2.bin` are safe to
  delete; deletion is Nate's hand, not mine.
