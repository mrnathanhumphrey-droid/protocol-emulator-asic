# SPEC v4 — Rulings 1 and 2: `J` becomes a function, pyRTA becomes primary

Wilson's rulings after `78d8f40`, both executed. The combined effect is that the
bar question dissolves: at the shipped program's derived `J = 1` the two bounds
**agree exactly** and the minimum margin is **12**.

---

## Ruling 1(a) — prime before release

The cold start is **removed structurally**, not excluded by definition.

> ⛔ Why not just exclude it: on a source lane a late *first* edge followed by an
> on-time second edge **is** differential jitter against `D_tol` — the peer sees a
> short first bit. Declaring the first job out of scope would exclude a real
> timing error for the sole reason that it happens first.

**Implementation.** No lane is released until every live lane's buffers are
primed, and **`now` does not advance until then**.

> ⛔ Gating only *dispatch* would relocate the problem, not remove it: `now` would
> run on through the priming refills, every absolute timestamp would fall behind,
> and the first job would be released **already late** — the same delay, charged to
> the schedule instead of to start-up. Freezing the clock makes the refill latency
> elapse before `t = 0` of the schedule exists.

`!want_fetch(i)` *is* the priming condition, reused rather than rewritten:
that function already encodes "this lane needs nothing more fetched", including
the chaining-re-arm case where the spare is deliberately left unfilled. A
hand-written "both slots valid" would **deadlock** on exactly that case.

### Two bugs on the way in, both recorded

1. **A continuous `primed` gate deadlocked the engine — zero edges.** "Every lane
   wants nothing fetched" is true at start-up and false again one cycle after
   *every* writeback, because the swap leaves the freed slot empty. Priming is a
   **start-up milestone, not an invariant**: it latches.
2. **A function in a continuous assign is sensitive only to its arguments.** The
   first version computed `assign lane_unprimed[gi] = l_live[gi] & want_fetch(gi)`
   inside a generate. `gi` is a genvar constant, so `want_fetch` was evaluated
   **once at time 0** — when every array was still X — and never re-evaluated.
   `lane_unprimed` sat at `xxxxx` all run and the engine produced zero edges
   again, for an entirely different reason. ⭐ Evaluating it in the **clocked**
   block fixes it properly and is better than `always @(*)`, whose sensitivity to
   signals read *inside* a called function is tool-dependent — that would have
   been the same latent bug with a different trigger.

### Must-fire: first-edge jitter == steady-state jitter

| | cold | steady |
|---|---|---|
| **design** | **0** | **0** ✅ |
| `M_NO_PRIME` | **76** | 0 → must-fire **fails** ✅ |

> ⛔⛔ **And 76 is itself a finding.** The un-primed design's real
> release-to-dispatch delay was **76 cycles**, dominated by the header load — not
> the 5 this project had been quoting. The old engine counter *and* the old bench
> **both** gated on `hdr_done`, so both were blind to the window in which `now`
> ran, lanes were released, and nothing could dispatch. **Two independent
> reconstructions sharing one blind spot read as agreement.**

The bench's stall gate is now "schedule time is running" (`now` advancing), not
`primed` — keying it off `primed` would make it a copy of the engine's control
signal *and* make `M_NO_PRIME` invisible, since the bench would simply not look
during the window where the mutant does its damage.

**Cost: 1 flop** (`primed_q`). 2,854 → 2,855.

---

## Ruling 1(b) — `J` is a derived function of the program

`gate_j_program.py`. Derived from the prefetch FSM, **not fitted to the sweep**:

```
L_REFILL  = 4   P_SCAN notices (1) + P_REQ->P_WAIT->P_CAP (3)
WINDOW    = d + C                     the spare's refill window
shortfall = max(0, k*L_REFILL - (d_min + C))
L_CAP     = 7   in-flight (<=3) + scan (1) + own (3)
J(d_min,k) = min(shortfall, L_CAP) + J_WINNER_REG
```

> ⭐ **The cap exists because of `P_SCAN`'s winner-first policy** — at most one
> other refill can be ahead of a stalling lane's. Without winner-first the queue
> would be `k` deep and there would be no cap. **The policy is load-bearing for
> the *bound*, not just the average.**

### The two published numbers

| | `d_min` | `J` |
|---|---|---|
| **shipped program** | 25 | **1** — shortfall `max(0, 20−27) = 0`, winner registration only |
| **universal worst case** over admissible programs | 8 | **8** |

Measured floor over the same admissible range: **6**. ⚠ The **derived** number
publishes. A measurement is a floor on the true maximum, and this project has
already shipped `C = 2.00` as a mean and `J = 5` as a bound once.

> ⛔ **Admissibility bounds the sweep.** At `d < 8` the five-lane set has
> `U = N·C/(d+C) > 1` — overloaded, infeasible by condition (1) — and the stalls
> there are the engine being saturated, not refill latency. Including them would
> manufacture a worse `J` than any admissible program can produce.

`sim ≤ derived` at every admissible swept point; a sim value **above** the
derivation stops everything.

**1.6t added** (1.6 now at **20 conditions**): `d_min` is an admissibility
input and the loader **computes** the program's `J` from it — a property the
loader checks, never a promise the programmer makes. Its firing witness is a
program that is feasible by condition (1) and still carries `J = 8` instead of 1.

**Double buffer: kept.** 169 flops for a universal worst case of 8 rather than
~11. At the shipped program both are 0, so it is insurance for programs we have
not written — which is what a bound over admissible programs is for.

---

## Ruling 2 — pyRTA is the primary bound

### The re-baseline

Digest **`8ea5756203e1` → `b4e51034e283`**. Every lane now carries its derived
`J` (1, and 2 on I²C for asynchronous capture).

```
r = {11, 8, 5, 10, 6}      min margin 12      bar >= 4
```

⭐ `b4e51034e283` is the digest `frontier.py` had been declaring as its
**(C=2, J=1) variant** — so that gate now **MATCHES**. The stated design point
and the shipped table finally agree.

| | ours | pyRTA | bar |
|---|---|---|---|
| **shipped `J=1`** | 12 | **12** — exact on all five lanes | PASS both |
| universal `J=8` | 1 FAIL | **5** | **PASS** under the primary bound |

### What the re-baseline broke, and why that was the system working

**Three gates failed at once**, all the same root cause: `gate_pyrta`,
`gate_rearm` and `gate_pin_subsets` each built their own pyRTA task set with
plain `Periodic` — the **naive** framing — and so reported the J = 0 answers
against our J = 1 ones. A fourth, `gate_pyrta_jitter`, had the correct
construction privately.

> ⛔⛔ **A bound that is quoted as the published number cannot have four private
> implementations, three of them wrong.** The framing now lives once, in
> `pyrta_bound.py`: jitter in the arrivals, deadlines converted from
> nominal-release to arrival semantics, and the subject's own delay **swept**.
> After conversion: `gate_pin_subsets` 80 of 80 subset results agree, `gate_rearm`
> 6 of 6 exact, `gate_pyrta` 5 of 5 exact.

Two more caught by the guards rather than by me:

- **`gate_lane_class.five_lanes` dropped `J`.** A second builder copying
  name/T/C/D/n/t and silently not carrying `J`. Invisible while the table was
  J = 0 everywhere; the moment it moved, the gate reported the **old** digest
  under the current table's name. The A1 digest meta-check caught it — the second
  time a second builder has caused a finding here.
- **`gate_lane_class`'s must-fire went vacuous.** It checked two hard-coded rates
  (3 and 4 MHz) that separated the differential and absolute tests *at J = 0*.
  With `r − C` one cycle larger the differential test fails there too, and the arm
  reported "no case separates the two tests" about a separation that had simply
  moved to 2.5 MHz. ⭐ **A must-fire whose witness is a hard-coded constant has a
  shelf life** — it now searches and names the rate it finds.

### Direction, not agreement

`pyrta_bound.check_direction`: **ours ≥ pyRTA on every lane.** Ours smaller →
STOP, and under Ruling 2 that has **two** causes, not one: either our recurrence
is unsound *or* pyRTA has been misframed. `bound_naive` is standing proof that
misframing is live — kept red in `gate_pyrta_jitter` arm 1, where it returns
**exactly our old bug's numbers** on the two lanes where the bug was visible.

### Spuri's full jitter form: not adopted, and now unnecessary

Our recurrence sets **no published number**, so there is nothing to tighten. The
three structural gaps (`docs/SPEC_V4_J_SOUND.md` §4) stay recorded as the
*reason* our form is loose, not as work owed.

> ⛔ If it is ever adopted it needs a **pre-registered rationale decided before
> margins are computed** — otherwise the adoption cannot be told apart from
> choosing the recurrence that gives the answer we wanted.

---

## The digest ledger

A digest bump is the one change that invalidates every published number at once,
and until now it was recorded only in prose across seven closeout documents.

> ⛔ The suite's cross-check only compares gates **to each other within one run**,
> so a whole run can agree on a table nobody authorised.

`lane_digest.DIGEST_LEDGER` now records every digest with its reason, and
`assert_current()` requires the live table to hash to the newest entry. An
unauthorised bump goes **red** naming the problem; an older entry is reported as
"reverted, or a second builder is dropping a field" — which is exactly what had
just happened.

**Priced** (`_price_digest_ledger.py`): a one-cycle change to one lane's `J`
moves the digest and the ledger rejects it. `price_gates.sh` now **13 of 13**.

---

## The clobber, fixed twice

The bench takes an image argument and wrote **one** constant path. Detection
(an `image` provenance line, asserted by the gate) worked — it caught `sim 7`
from a program the gate was not measuring. But detection left the hazard: running
`test/run_mutants.py` legitimately exercises the stress images and then left the
C/J gate red.

⭐ The output path now **depends on the input** — a non-default image writes
`cj_measured_alt.txt`. **N+1 made impossible, not merely visible.** The asserted
provenance line is kept as a second, independent guard.

---

## State

- **A2 suite 27 of 27**, digest `b4e51034e283`, ledger entry 2 of 2.
- **`price_gates.sh` 13 of 13** red.
- **1.6 at 20 conditions**, every one with a firing witness.
- `test/run_mutants.py` **4 of 4** (`M_NO_PRIME` added).
- Smoke bench **PASS**: cold 0 == steady 0, C = 2.00, invariant 0 violations.
- `test/yosys_check.sh`: plain Verilog, `check -assert` clean, **0 multi-driver**,
  2,855 flops.

### Still owed

- **CI `gds` + F2 face 3.** The `78d8f40` run reached 33 min (a success is ~36);
  F2 faces 3–4 remain a prediction until the synthesized netlist is checked.
- **Reverse traceability**: census programs on the golden model, which also
  clears the 6 unexercised opcodes.
- **TChecker for bursty-with-jitter** — the two `m_i > 1` lanes still carry one
  foreign witness at `J > 0` where everything else carries two.
- `test/test.py` — all 5 cocotb tests still assert the superseded load path.
