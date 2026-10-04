# Pre-registration — the per-lane jitter term `J_lane`

**Written before the instrument exists and before any measurement.** Committed
in this state; the measurement lands in a later commit, against this text.

Wilson's T1. The predecessor matters: two scalars have already failed on this
question — the published universal `J = 8` (unsound at ten admissible points,
retracted) and `U_port ≤ 1` (pre-registered, falsifier fired). Both were fitted
to aggregate readings. This one is pre-registered **with its quantity defined
in RTL terms**, because the last two failures were as much about *what* was
being counted as about the number.

---

## 1. The quantity, as an RTL predicate

Lane `L` is **blocked** in a cycle when the engine's own stall branch is the one
it takes, with the winner pinned to `L`:

```
blocked_L(cyc)  ==  primed
                 && !config_err
                 && (st == ST_IDLE)
                 && winner_v
                 && (winner == L)
                 && !l_armed[L]
                 && !l_actv[L*2 + (l_sel[L] ? 1 : 0)]
```

This is `src/pe_engine.v:1076–1089` read literally — the `else` of
`if (l_actv[head])`, which is the line that increments `jitter_cnt`, with
`winner == L` added. Every term is there for a reason:

- `primed && !config_err` — the ST_IDLE arm is gated on both, so cycles before
  priming are not dispatch opportunities and must not count as waits;
- `!l_armed[L]` — an armed winner arriving ready takes the **timeout-halt**
  branch, not the stall branch. ⚠ `tb_witness.v`'s existing `waiting` wire
  omits this term, so it counts a halting lane as a stalling one. That bench
  measures the aggregate and no armed lane appears in its images, so it was
  never wrong in practice — but this instrument must not inherit the looseness.

**A release interval** for lane `L` runs from the cycle `ready[L]` rises (0→1)
to the cycle `L` dispatches (the same ST_IDLE arm, `l_actv[head]` true, which
is where `cur <= winner; st <= ST_DRIVE`). Three numbers per interval:

| name | definition | bounded by this hypothesis? |
|---|---|---|
| `sum_L` | count of `blocked_L` cycles **inside one interval** | **YES — this is the pre-registered quantity** |
| `run_L` | longest consecutive `blocked_L` run inside it | implied (`run_L ≤ sum_L`) |
| `wall_L` | interval length, release → dispatch | **NO** |

⭐ **`sum_L`, not `run_L`, is the pre-registered quantity, and that is the
conservative choice.** A lane can be blocked, lose the EDF winner to a more
urgent lane, and become blocked again inside one release interval; a
longest-run reading would report each piece separately and so can only be
smaller. Choosing the sum means the hypothesis is harder to satisfy, which is
the direction a bound must err in.

### ⛔ What `wall_L` is, and why it is not the hypothesis

`wall_L` includes **EDF interference** — cycles when `L` is ready but another
lane legitimately holds the engine. That is queueing delay, which the response
analysis already accounts for through the `C` terms; counting it as jitter would
double-charge it and would falsify any small bound trivially on a 5-lane image.
`J` is specifically the *prefetch-miss* delay, so the predicate above is the
right reading of it.

It is still **recorded and reported**, for one reason: so that nobody later
reads a passing `J_lane ≤ 9` as "a lane dispatches within 9 cycles of release".
It does not mean that, and `wall_L` is the number that answers that question.

---

## 2. The hypothesis

```
J_lane  =  max over lanes, over complete release intervals, of  sum_L
```

**Pre-registered claim:  `J_lane ≤ 2 · L_REFILL + 1 = 9`.**

The constant, derived rather than fitted:

- `L_REFILL = 4` — one refill occupies the prefetch FSM for `P_SCAN(1) +
  P_REQ/P_WAIT/P_CAP(3)` (`model/a2/gate_j_program.py:73`);
- **one refill is in flight engine-wide** and refills are non-preemptible, so a
  lane can find at most **one** other refill already in progress ahead of its
  own: `2 · L_REFILL = 8`;
- `+1` for the winner registration cycle.

## 3. The falsifier, committed now

> **Any complete release interval, on any identified lane, in any arm, with
> `sum_L > 9`.**

A single interval is enough. No averaging, no percentile, no discarding an arm
as unrepresentative.

### ⭐ This prediction is at real risk, and here is the number that could kill it

The **aggregate** worst stall already recorded is **12** (sub-`D*`, logged in
`PREREG_U_PORT.md`), and chain 1 there shows a run of **8** that the trace
attributes to "one other lane's complete refill, then its own" — i.e. exactly
`2 · L_REFILL`.

The hypothesis asserts that the recorded 12 **decomposes across lanes**: that it
is an any-winner-blocked run in which the winner changed mid-stall, and that no
single lane owns more than 9 of it. If instead one lane owns the whole 12, the
falsifier fires immediately.

⇒ So the structural claim being tested is precisely **"at most one refill can be
queued ahead of a given lane's own"**. If more than one can be, 12 belongs to
one lane and `2 · L_REFILL + 1` is the wrong shape — the same way `L_CAP = 7`
was the wrong shape for the aggregate.

## 4. Non-outcomes — what a pass does not license

- It does **not** publish a universal `J = 9`. A holding result is recorded as
  **analysis**. Whether `pe_asm` may admit programs below `D*` at `J = 9` is a
  **separate ruling**, taken only after margins at `J = 9` are computed with
  **pyRTA** (the primary bound).
- It does **not** supersede the scoped claim. `d_min ≥ D* = 20 → J = 1` remains
  the only published timing claim either way.
- It is a **floor on the bound, not a bound**: a finite set of arms and phase
  alignments. A derivation must land at or above what is seen here.

## 5. Arms, fixed before measuring

Each of the 5 lanes identified in turn, in both arms. 10 runs.

| arm | program | why |
|---|---|---|
| **A** — d=12 stress | `--five 12 13 14 15 16`, `d_min = 12 < D*` | the uniform sub-`D*` case; where the aggregate 8 was seen |
| **C** | `--five 8 100 100 100 100`, `d_min = 8` | the mixed case that falsified `U_port`; speculative spare fills from near-idle lanes are the port work a per-lane count misses |

⛔ Both are written to **`probe_`-named images** (standing rule 6). Reserved
artefact names belong to their generators and to `test/artefacts.sha256`; the
J investigation already clobbered `five_image.hex` dozens of times because
`--five` had a constant output path.

## 6. Preconditions the output must print, or there is no reading

Standing rule 4. Each run prints, and the gate refuses the number if any fails:

1. **image loaded** — `+NBYTES` supplied and the byte count echoed; a program
   that never loaded reads as "no stalls", which is how a probe once produced
   the opposite of the right answer;
2. **window length** — cycles after warm-up, **≥ 100 000**;
3. **convergence outside the transient** — the maximum must be reached inside
   the asserted window, not during warm-up; warm-up is counted from
   `hdr_done`, and a warm-up that runs past the end of the run yields an empty
   window, which must print as *no reading* and never as zero;
4. **liveness of the identified lane** — `l_live[L]` observed true, and
   **≥ 100 complete release intervals** recorded for `L`. Zero intervals is
   **not a pass**: it is a dead instrument, and it must say so;
5. **engine health** — `config_err` low throughout, `primed` observed high;
6. **arm identity** — the image's `d` set echoed from the file actually loaded,
   so a run cannot be attributed to the wrong arm.

## 7. Disposition, both branches, decided now

- **Holds (`J_lane ≤ 9` in all 10 runs, all preconditions met)** → recorded as
  *analysis only*, with the arms and window lengths. The per-lane instrument
  then becomes the measurement tool for T3 (`NSLOT` single- vs double-buffer).
- **Falsified (any `sum_L > 9`)** → recorded **as written, with the
  measurement that fired it**. The witness trace of the violating interval is
  pulled (which lanes' refills were queued ahead, in order), and the scoped
  claim `d_min ≥ D* → J = 1` stands alone with no universal companion.
- **No reading (any precondition fails)** → neither. Fix the instrument and
  re-run; a precondition failure is never reported as a pass.

## 8. Instrument must-fire

The instrument is itself gated (standing rule 3): a deliberately mis-set arm
must make it report a **failure**, not a quiet zero. Specifically — point the
instrument at a lane index that is not live, and the "≥ 100 intervals"
precondition must fire and refuse the run. Four of the probes in the J
investigation were broken and each one was confident; a measurement that cannot
be shown to fail is not a measurement.
