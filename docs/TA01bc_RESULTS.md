# TA-01b / TA-01c — the infinite run, and the band that was computed rather than tested

**Both GREEN, and both RE-DERIVED after a receiver fix.** Re-run:
`python model/ta01b/run_ta01b.py` (fixpoint),
`bash model/ta01b/zone/run_zone.sh uart_nominal uart_drift10` (zones),
`bash model/ta01c/run_imi.sh uart_param.imi uart_param.imiprop` (synthesis).

---

## ⛔⛔ CORRECTIONS — a receiver defect, and a runner that never existed

**C1 — `run_ta01b.py` did not exist when this document said to run it.** The line
above has pointed at that file since TA-01b was written; `git log --all` has no
record of it ever being committed. Every number below was produced by ad-hoc
invocation and was **not re-runnable as documented**. The runner now exists and
re-derives all of them mechanically.

**C2 — `StreamReceiver` sampled one cycle late per bit, and so did TA-01's
`UartReceiver`.** `if x < t` then sampling at `x == t` counts `0..t` **inclusive** —
`t+1` cycles per bit, an effective 435-cycle bit period at `T = 434`
(114,943 baud against a nominal 115,200) and **+10 cycles of accumulated offset by
the stop sample**. Fixed: the thresholds are now named **once** per receiver
(`s_start`, `s_bit`) and shared by every call site.

⛔⛔ **This document announced the defect and explained it away.** The reset
diagnostic below read: *"max clock `== T`, not `< T`; the clock reaches `T` at the
sample then resets. Off-by-one in the spec's phrasing, not a failure."* **It was the
defect.** It is also load-bearing for the BFS-termination argument, so it was a
guard that passed *because of* the thing it screened for.

⛔ **It was in three receivers at once** — `UartReceiver.step`, `_enabled` (the
*deliberately independent* re-derivation, so TA-01's determinism/totality gate
passed because both copies shared the defect), and `StreamReceiver.step`. Agreement
is not corroboration unless the copies can fail independently.

### What the re-derivation changed, and what it did not

| diagnostic | published | re-derived | |
|---|---|---|---|
| max reachable clock | `434` (`== T`) | **`433` (`== T-1`)** | ⭐ the receipt for the fix |
| fixpoint states @ T=434 | 13,023 | **13,023** | unchanged |
| determinism × totality combinations | 34,086 | **34,086** | unchanged |
| state-count law | "30 per clock tick" | **slope exactly 30.0000**, `30T + 3` | sharpened |
| zone verdicts | `false` / `true`, 37 / 36 states | **identical** | unchanged |
| TA-01c constraint | `9Te < 19U < 10Te`, exact | **identical** | unchanged |

⛔ **A claim made while diagnosing this, now REFUTED by the re-derivation:** that
the 13,023-state count and the 30-per-tick law were "defect-derived". They are
**defect-invariant** — identical before and after. The reachable set counts
`(executor, monitor)` pairs along a phase-locked trajectory plus idle branching, and
moving *where within a bit* the sample fires does not change how many distinct pairs
occur. Only `max_clock` ever depended on the threshold. ⭐ The honest version of
"re-derive, don't re-word" includes re-deriving the things you predicted would move
and reporting that they did not.

### ⭐ And the level/phase question was half a category error

The companion claim — "the receiver checks the level where the formal models check
the phase" — conflated two objects. A **receiver model** samples levels because
real silicon has no access to the transmitter's phase; a **conformance oracle**
checks that every sample landed in its own bit window. TA-01 built the first and
claimed the second. `model/ta01/phase_oracle.py` adds the missing object rather than
bending the receiver into it, and **the oracle's band is `[413, 458]` — exactly
Imitator's synthesized band.** So the three routes now agree **at the edge**, which
is what the "triple cross-check" below claimed and did not have.

⭐ The receiver's own band is **payload-dependent, and correctly so**: `0xFF` leaves
the line high from the start bit onward, so a level-checked stop sample cannot fail
however far it drifts — band `[344, 651]` against `0x55`'s `[410, 458]`, **6.4×
too permissive**. **Timing conformance must be tested on `0x55`-class payloads;
"not its own bit-reversal" is necessary but not sufficient.**

---

# TA-01b — conformance over an unbounded run

## The infinite-run proof

The fixpoint **closes**: 13,023 reachable states, `BAD` outside the set, BFS
terminates, max reachable clock bounded by `T`. A **closed** reachable set with
BAD outside it is a sound safety proof over **every** run, including the infinite
one. Unrolling can only ever certify `N` frames at cost ∝ `N`.

⭐ **Inter-frame idle is NONDETERMINISTIC, not sampled.** The executor may idle
any number of cycles before the next frame, so "arbitrary-length idle" is covered
**by construction**. TA-01 sampled idle ∈ {0,1,2,3}, which tests phase
independence but cannot speak for *arbitrary*.

⛔ **Reset diagnostics (these replaced the bogus "flat in frame count", which is
trivially true of a fixpoint and tests nothing):** BFS **terminates** — a
non-resetting clock makes the state space unbounded and it simply would not — and
**max reachable clock is bounded by T**.

> ⛔⛔ **RETRACTED — the original text here read:** *"Precisely: max clock `== T`,
> not `< T`; the clock reaches `T` at the sample then resets. Off-by-one in the
> spec's phrasing, not a failure."* **That was the defect, not a phrasing problem**
> (see C2 at the top). Under the fixed thresholds the counter runs `0..T-1` and the
> measured max reachable clock is **433 = T-1**, as it should always have been.
> This sentence is the clearest instance in the project of a diagnostic firing
> correctly and being argued away.

## Both conjuncts load-bearing over the loop

⛔ **`BAD` is split by conjunct, because "reaches BAD" is a colour, not a
reason.** In the first pass the rejection arms were only checked for reaching
BAD — R3 was *supposed* to die by the data conjunct, and nothing verified it had.

| arm | dies by | |
|---|---|---|
| R1 stop dropped @pos1 | **`BAD_FRAME` only** | framing conjunct |
| R3 data bit flipped @pos1 | **`BAD_DATA` only** | framing perfect — can only die by comparison |

⭐ The data conjunct needs a **periodic** expected stream (`[0x55,0x0F,0x01]`,
position mod P=3). Over an unbounded run an arbitrary expected sequence needs
unbounded position memory and finiteness dies. ⛔ The lazy escape — drop the byte
comparison for the loop and check framing only — silently un-load-bears the data
conjunct, which is exactly the regression M5 existed to stop. **The zone model
structurally cannot see the data conjunct, so this is its blind spot and has to be
green here.**

Determinism + totality: **34,086 combinations**, including the **mod-P axis** —
forgetting the new counter reopens the totality hole on a fresh axis.

## The zone cross-check — independent theory, same verdict

| model | verdict | states | time |
|---|---|---|---|
| `uart_nominal` (Te = T = 434) | `REACHABLE false` | 37 | 0.20 ms |
| `uart_drift10` (Te = 478, +10%) | `REACHABLE true` | 36 | 0.14 ms |

⭐ **The zone model proves something strictly stronger on its own axis:** data
bits are **nondeterministic**, so `A[] not bad` covers **all 2⁸ payloads in every
infinite sequence**, not merely the periodic stream. That discharges "the framing
conjunct is value-independent" **by construction** rather than by assertion.

⛔ **It deliberately does not carry the data conjunct.** Byte comparison is
integer bookkeeping; zones contribute nothing. The honest statement is **two
routes to the timed property, one route to the data property.**

⛔ **A modelling choice that would have manufactured a false finding:** the
falling edge is a **synchronised event**, not a guard on shared `line`. As a guard
it stays enabled for the whole start bit, letting the monitor latch *late* and
producing misalignment a real receiver never has — a spurious counterexample,
which is worse than a missed one because it looks like a result.

**Re-arm gating, verified two ways.** `fall` appears on exactly two edges, both
from IDLE. ⭐ And empirically: data bits are nondeterministic so mid-frame lows
occur on every path — if one could re-latch `fall`, the monitor would misalign and
`bad` would be reachable. It is not. **Time-deadlock audit:** all 23 locations,
zero at risk; every bounded location's guard fires exactly when its invariant
expires.

## The T-axis — measured on both columns

| baud | T | fixpoint states | zone states | ratio |
|---|---|---|---|---|
| 115200 | 434 | 13,023 | **37** | 352× |
| 9600 | 5,208 | 156,243 | **37** | 4,223× |
| 2400 | 20,833 | 624,993 | **37** | 16,892× |
| 1200 | 41,667 | 1,250,013 | **37** | **33,784×** |

Fixpoint grows linearly at a constant **30 states per clock tick**; the zone
column is **exactly flat at 37** across a 96× range of T.

⛔ **But enumeration still WORKS at every fixed T.** This makes zones a large
**optimization**, not a necessity. Only TA-01c is a necessity.

## Gate 0 caught a bench bug on its first stream run

sigrok decoded `55 0F 01 55 0F` then **`Frame error`**. Cause: the waveform dumper
counted frames on *start*, truncating the last one mid-flight. **A bench bug that
would have read as a model failure**, found by the foreign authority. After the
fix: `55 0F 01 55 0F 01`, two full periods, clean.

---

# TA-01c — the band, synthesized

## The result

```
Imitator:   9*Te < 19*U < 10*Te          exact (sound and complete)
design rule T = 2U,  Te = 2U(1+eps):

        -1/20  <  eps  <  1/18
      -5.0000%  ..  +5.5556%
```

Fixpoint reached at depth 7, 16 states, 0.006 s. **Fully symbolic — the
bounded-region fallback was not needed.**

## ⭐⭐ The asymmetry — predicted as P4, and it fired

The hand calculation gives `|eps| < 1/19 = ±5.2632%` — **symmetric, and wrong on
both ends**:

```
1/20 = 5.0000%   <   1/19 = 5.2632%   <   1/18 = 5.5556%
```

The `9.5*eps` arithmetic linearises and therefore **symmetrises**. The true
tolerance is **11% wider on the fast side than the slow side**, and point-testing
could not have revealed that — you would have to already know where to look.
**That asymmetry is the formalism giving something arithmetic could not.**

## Triple cross-check

| route | nominal | M0 (+2%) | M1 (+10%) |
|---|---|---|---|
| parametric synthesis (symbolic) | conform | conform | violate |
| zone model-checking (TChecker) | `REACHABLE false` | — | `REACHABLE true` |
| finite-state fixpoint | conform | conform | violate |

Exact window at `U=217`: **412.30 < Te < 458.11**.

## Decidability, as pre-registered

**One clock**, reset only at the frame's falling edge and never within the frame,
so the executor's boundaries and the monitor's samples are both **absolute
constraints on that single clock**. Single-clock PTA reachability is decidable.
Giving executor and monitor independent clocks *and* parametrizing both is the
undecidable region — deliberately avoided.

⭐ **The `floor(T/2)` non-linearity never appeared**, because `T = 2U` makes every
guard `U, 3U, … 19U` **linear in the parameter**. Even bit periods are a **DESIGN
RULE** for the emulator (costs < 0.2% baud accuracy at 115200, far inside the
tolerance band), which makes the theorem **total over the design space** rather
than restricted within it.

⛔ **A modelling decision that would have widened the band falsely:** the monitor
checks the executor's **phase**, not the line **level**. A stop sample landing
*after* the frame reads idle-high and would "pass" a level-only check — handing
back a more permissive band for a reason that is a modelling artefact, not real
tolerance. A flattering error, and the kind that looks like a result.

## The necessity sentence

> **Conformance holds over a continuous tolerance band that was *computed, not
> tested* — `−1/20 < ε < 1/18`, exact. Enumeration cannot phrase "all ε in a
> continuous band," which is why the timed automaton is necessary here and not
> merely a 33,784× optimization.**

---

## Independence budget, as it now stands

1. **sigrok** — foreign, semantic, at the model layer (TA-01, TA-01b)
2. **zone vs fixpoint** — independent theories on the timed property (TA-01b)
3. **parametric synthesis vs analytic vs point tests** — three routes to the same
   boundary (TA-01c)

⛔ Still owed: a real receiver at the FPGA stage, and Lean for soundness.

## Scope fence — unchanged

Still UART, still transmit, still the model. **No RTL implements any of this yet**
— that is the refinement probe. Generic table-interpreter executor, SPI/I²C, and
fab are later rungs.

## Instrument slips logged this rung

- **`$TK` / `$f` eaten** crossing the Git-Bash/WSL boundary → script files, never
  inline `bash -lc`. This is the trap `run_pnr.sh`'s own header records as having
  "corrupted this exact kind of command five separate times."
- **cp1252 console** killed a runner mid-report → `sys.stdout.reconfigure("utf-8")`
  belongs in the file, not only in ad-hoc snippets.
- **`EXIT=0` from a pipe** was `tail`'s status, not Python's — a pipe hid a real
  failure.
