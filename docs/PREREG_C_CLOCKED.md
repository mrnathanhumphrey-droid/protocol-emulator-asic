# Pre-registration — `C` under the self-clocked SHIFT

**Written before the measurement runs.** Nothing below is a result. Every
number is either a prior value being carried in, or a threshold fixed in
advance. The one thing this document exists to prevent is choosing the decision
rule after seeing the data.

Ruled gate: the clocked SHIFT/SHIFTIN build may not be certified until `C` is
re-measured, because a **re-dispatched action needs no store read**, and a
shortened writeback would move the inter-dispatch spacing that every published
margin rests on.

---

## 1. What is being measured, and the instrument gap

`C` is the engine's per-job service cost as a response-time analysis charges
it. The shipped value is **3**, and the authority for it is
`docs/PREREG_C_SAT.md`: the dispatch FSM is a three-state cycle
(`ST_IDLE → ST_DRIVE → ST_WB → ST_IDLE`, the exit from `ST_WB`
unconditional), so the engine delivers one action every three cycles.
`svc_cycles / svc_jobs = 2.00` measures **occupancy** and is right about it —
it is not `C`.

`test/tb_csat.v` reports **`btbmin`**: the minimum spacing over back-to-back
dispatch pairs under saturation. That is the right quantity for "can the engine
go faster than 3", and it is **not** the quantity this ruling asks for.

> ⛔ **The instrument does not yet answer the question.** `tb_csat` has no
> per-opcode breakdown — `a_op` appears nowhere in it — and it reports the
> **minimum**. The ruling asks for the **maximum spacing per opcode**, because
> the risk from the clocked scheme is an opcode that takes *longer* than 3,
> not one that takes less. Extending it is part of this work and is declared
> here so the measurement cannot be quietly reinterpreted to fit what the
> existing instrument happens to print.

**The quantity:** for each opcode, the **maximum** back-to-back inter-dispatch
spacing observed under saturation, on programs containing self-clocked actions.

---

## 2. The decision rule, fixed now

| measured max spacing, any opcode | verdict |
| --- | --- |
| **< 3** | the engine is *faster* than charged. **Keep charging 3.** Do not re-quote downward. |
| **= 3** | unchanged. Proceed. |
| **> 3** | **FORBIDDEN.** Stop. Re-quote every published margin that rests on `C = 3`, before anything else proceeds. |

The asymmetry is deliberate and is not a hedge: a bound measured to check a
bound must not then be *lowered* by that same measurement. A smaller spacing
makes `C = 3` conservative, which costs margin we already have; a larger one
invalidates published numbers, which costs the entry its claim.

---

## 3. Two spacing definitions, made explicit

These are different quantities and conflating them is the failure this section
exists to prevent.

### 3a. `d_min` — **refill-bearing dispatches only**

`D*` is a **fetch-port** condition: it asks whether the port can serve every
lane's refill within the shortest action period. A clocked re-dispatch makes
**no port demand** — it retires nothing, reads no store word, and owes no
refill (Amendment A1). COLLECT likewise.

> ⇒ `d_min` is therefore defined over **refill-bearing dispatches**: those that
> retire an action and so owe a refill. Counting *all* dispatches would make
> `d_min` the 3-cycle phase gap and refuse every clocked program over a gap
> that never touches the port.

### 3b. A2/pyRTA — **every post-HIGH job at its true separation**

On a clocked lane every post-HIGH dispatch is released by the **observed clock
rise**, not by its timestamp — not only COLLECT. The golden model carries a
`reactive` flag per dispatch and reports **8 of 17** for an 8-bit receive.

Each such job therefore enters the task model with:

* `C` as measured in §2;
* a **reactive release**, so it carries the sync jitter `J = 1`;
* a minimum separation from the HIGH job of about `L_sync`, **not** the lane's
  nominal bit period;
* **no port demand** — refill was never part of the A2 task model; it lives
  only in `D*` and per-lane `J`.

No new arm is needed for this (ruled): it is an ordinary job in the lane's job
stream.

---

## 4. The admissibility claim — **pre-registered**

> **Claim.** With `d_min` defined over refill-bearing dispatches (§3a), and
> every post-HIGH job modelled at its true `~L_sync` separation (§3b), the
> **full FRAM write (n = 4)** and the **random read with repeated START** are
> **admissible**.

**Falsifier, either of:**

1. they are **not** admissible under that definition; or
2. the live `D*` sweep shows **stalls** on them.

Program sizes carried in from `model/clocked_shift_budget.py` (measured there,
not re-derived here): the write is **15 actions / 75 bytes**, the random read
**20 actions / 90 bytes**, against a 256-byte store with a 75-action budget.

---

## 5. What is *not* claimed

* Nothing here re-opens `J = 1` or `D* = 20`. Those rest on Theorem 3, whose
  premise was amended (A1) from "exactly one refill per dispatch" to "at most
  one" — a change that **preserves** the bound, because the proof needs an
  upper bound and a re-dispatch owes fewer.
* `C` is a property of the **engine**, not of a program. A program-specific
  spacing that is arrival-limited rather than service-limited is not a `C`, and
  `tb_csat` already refuses to read one as such.
* This does not certify the clocked ACK. Conditions (a)–(c) — SDA released on
  both phases, the sample on the observed rise, ACK reads 0 and NACK reads 1 —
  are separate and come after.
