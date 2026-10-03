# SPEC v4 — the double buffer, and what measuring it actually found

Nathan's call: **yes**. Sequenced after the jitter-sound pipeline, per Wilson.
It is built, synthesised, mutation-tested — and **the pre-registered falsifier
fired**, twice over, in ways that matter more than the feature.

---

## The headline, before the detail

| claim | status |
|---|---|
| double buffer built, synthesises, behaviour bit-identical | ✅ 134/86 edges, C = 2.00, `check -assert` clean |
| predicted `J_pipe = 2` | ⛔ **FALSIFIED — measured 7** |
| predicted cost ~110 flops | ⛔ **measured 169** (+54 %) |
| it reduces worst-case `J` | ✅ **11 → 7** |
| it helps the **shipped** lane set | ⛔ **no — both buffers give steady-state stall 0** |
| the `J = 5` quoted since S3 | ⛔ **was a cold-start transient all along** |

---

## 1. What was built

Two action slots per lane, a select bit, and a fetch pointer that runs ahead of
the PC:

```
l_act[lane*2 + slot]   two action words
l_actv[lane*2 + slot]  per-slot valid
l_sel[lane]            which slot is the HEAD; flips at writeback
l_fpc[lane]            the fetch pointer, ahead of l_pc
```

At writeback the head is invalidated **and** `l_sel` flips, so the spare —
already holding the successor — becomes the head and the next dispatch finds a
valid head with no refill on its path.

> ⛔ **Flat arrays indexed `lane*2 + slot`, not `[0:N_LANES-1][0:1]`.** A 2-D
> unpacked array is legal Verilog-2001 and iverilog takes it happily — which is
> exactly the trap this project already fell into once, when the multi-driver bug
> passed the local bench and died in Yosys. `test/yosys_check.sh` now reads the
> design **without `-sv`** so that acceptance is a checked property.

### The term the pre-registration missed

`OP_REARM` with `level = 1` jumps `l_pc` to `l_base`. A plain double buffer has
already prefetched `l_pc + ACT_BYTES`, which after a loop is the **wrong**
action — so both slots would flush and the next dispatch would pay a full
refill, **once per program iteration**. For a 10-action UART byte that is 1
dispatch in 10, and `J` would have landed near 7 on an incomplete decomposition
rather than on the double buffer.

The remedy is free because the loop target is already a register: the prefetcher
decodes the head slot and fetches `l_base` when the head is a looping re-arm
(`fetch_addr`). So the loop is prefetched like any other control flow.

---

## 2. ⛔ The falsifier fired: predicted 2, measured 7

| | worst-case steady-state stall | `J` (+1 winner registration) |
|---|---|---|
| single buffer (`M_BUF_SWAP`) | 10 | **11** |
| double buffer | 6 | **7** |
| pre-registered prediction | — | **2** |

Swept over inter-action delay `d ∈ [2,30]` with five active lanes.

**Why the decomposition was wrong, which is the useful part:** the two refill
terms do *not* go to zero, because **one shared fetch port still serves every
lane**. Double buffering converts a per-dispatch *latency* into a *queueing*
delay — each lane gains a whole extra action period of slack, but when several
lanes demand refills inside one window the queue delay survives.

> ⭐ **This is the same structural fact that killed the earlier "cheap win."**
> Refilling at writeback took `J` from 5 to 7 because a busy port makes a
> *different* lane wait. With one port, `J` is bounded by port **throughput**, and
> neither buffering nor a smarter refill policy changes throughput. The
> pre-registration assumed latency was the whole story; it wasn't.

Reported, **not re-argued** — the pre-registration says so in as many words.

---

## 3. ⛔⛔ The negative result, which outranks the feature

At the **shipped** inner action spacings — 25, 45, 434, 414, 25 cycles — with
all five lanes active:

| | cold start | steady state | stall events |
|---|---|---|---|
| double buffer | 7 | **0** | 0 |
| single buffer | 7 | **0** | 0 |

**Identical.** The shipped program never enters the regime where buffering
matters. The double buffer is distinguishable from its own mutant only for
`L/2 ≤ d < L`, i.e. `d ≈ 10–16`, and the tightest shipped lane sits at `d ≈ 25`.

### Which means the `J = 5` driving the whole crisis was a cold start

The bench had been reporting `J = 5` since S3 as if it were a steady-state
property. It is each lane's **first** action after `hdr_done`, once per run:

| default program | cold | steady |
|---|---|---|
| single buffer | 9 | 0 |
| double buffer | 5 | 0 |

> ⛔ **And the bench could not have told us.** `dut.u_eng.jitter_max` is a max
> over the whole run, so a single startup transient pins it forever. After
> double-buffering it still read 5 while the steady-state stall was **zero** —
> which is why `M_BUF_SWAP` *survived* the first mutation run. A max over a run
> containing a transient is not a measurement of the steady state, and reading it
> as one would have made the double buffer look like it had done nothing.
> The bench now reports cold and steady separately, and cross-checks its cold
> figure against the engine's own counter.

> ⚠ **Whether the cold start belongs in the published `J` is Wilson's to rule.**
> Spuri's RTA bounds **every** job including the first, so on the letter of the
> analysis it does. The counter-argument: a uniform offset on each lane's *first*
> action, before the protocol has begun, is start-up latency rather than
> inter-action jitter, and the host controls when the program starts. **That is a
> modelling claim, so it is stated and not assumed.**

---

## 4. Cost: 169 flops, not ~110

`test/yosys_check.sh`, same script on both trees:

| | flops | generic cells |
|---|---|---|
| HEAD (single buffer) | 2,685 | 14,370 |
| double buffer | 2,854 | 15,611 |
| **delta** | **+169** | **+1,241** |

> ⛔ **The estimate was low by 54 %.** It counted the second action word
> (`N_LANES × ACT_W = 110`) and forgot every pointer the second slot needs:
> `l_fpc` (5 × AW = 40), `l_sel` (5), and the refill's latched slot and address
> (1 + 8). **A flop estimate that counts the DATA and forgets the POINTERS is the
> same error as sizing a store by its payload and forgetting the program** — which
> this project already made once, in F1.

---

## 5. Mutation testing — the owed deliverable

`test/run_mutants.py`. Arm 0 requires the **unmutated** build to pass first,
and requires the invariant to have actually run (6,321 checks), because every
"the mutant died" is meaningless against an already-red baseline.

| mutant | mode | verdict | evidence |
|---|---|---|---|
| `M_BUF_NOINVAL` | assert | **RED** | buffer-swap invariant |
| `M_BUF_SWAP` | **differential** | **RED** | steady 9 vs baseline 5 |
| `M_BUF_CHAINFLIP` | effect | **RED** | sel flips 353 vs 329 |

**The buffer-swap invariant** is checked against the loaded **image**, not
against another engine register: the head slot must hold the action at `l_pc`.
Comparing two engine registers would be satisfied by any self-consistent wrong
state — which is what a stale buffer *is*. The check's **count** is asserted too,
because a zero-violation result is worthless if the check never ran.

> ⭐ `M_BUF_SWAP` is the informative one, and it needed **differential** mode. The
> bench's absolute steady-J check is `> 2`, and both the design (5) and the
> mutant (9) exceed it — so an absolute check would have "killed" the mutant
> while being equally satisfied by the correct design. A guard passing for the
> wrong reason, again. The kill criterion is now *strictly worse than the
> baseline on the same image*.

> ⛔ **`M_BUF_CHAINFLIP` corrected the RTL.** The comment claimed the chaining
> asymmetry was a *correctness* requirement — that flipping would dispatch the
> wrong action. **It would not:** the refill reloads `l_pc`, which a chaining
> re-arm has not advanced, so the same action comes back. The asymmetry is a
> performance choice worth one refill per park dispatch. It is declared a
> **characterised survivor** — its effect is asserted (the flip count must change)
> but no program the bench can build makes its cost visible, so the asymmetry is
> correct by derivation and **unevidenced by test**. Recorded rather than killed
> by a program contrived for it.

---

## 6. A clobber that bit immediately

The bench now takes an image argument (`+IMG=`) and still wrote **one** constant
path, `test/cj_measured.txt`. A refill-stress run overwrote the default
program's measurements and `gate_cj_bounds.py` reported **`sim 7`** for a program
it was not measuring — while looking perfectly green.

Fixed the way the standing rule says: the provenance travels **with** the
numbers. The bench writes `image <path>` into the file and the gate asserts it is
the default program. Priced: after a stress run the gate now exits **1** with
*"was written by test/five_image.hex, not the default program"*.

---

## 7. State

- `src/pe_engine.v` double-buffered; **behaviour bit-identical** on the default
  program (134/86 edges, C = 2.00, same per-opcode min==max==2).
- **Smoke bench PASSES** — first time, including the new invariant and J split.
- **A2 suite 26 of 26**, base digest unchanged `8ea5756203e1`.
- `part1_param_contract`, `f2_flop_driven_outputs`, `gate_cj_bounds` green;
  `run_mutants` 3 of 3 accounted for.
- `test/yosys_check.sh`: plain-Verilog elaboration, `check -assert` clean,
  **0 multi-driver**.

### Owed

- **Wilson: does the published `J` include the cold start?** Everything else
  about `J` now hangs on this. If it does, `J = 7` (double) or `11` (single). If
  it does not, the steady-state `J` at the shipped delays is **1** — winner
  registration alone — and the margin question largely dissolves.
- **Wilson: keep the double buffer?** 169 flops for `J` 11 → 7, which matters
  only if the cold start is excluded *and* a host may load a tight program. At
  the shipped delays it buys nothing. ⭐ It is still the only thing that moved
  `J` at all after the refill-policy attempt made it worse.
- **Wilson: Spuri's full jitter form** (`docs/SPEC_V4_J_SOUND.md` §4) — our bound
  is loose by up to 4 cycles on I²C and that is what makes the bar verdict
  bound-dependent.
- `test/test.py` — all 5 cocotb tests still assert the superseded load path.
- Reverse traceability: census programs on the golden model, which also clears
  the 6 unmeasured opcodes.
