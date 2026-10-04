# SPEC v4 — edge capture: the reactive direction, built

Wilson's ARMED ruling, with all three spec fixes folded in. **46 flops.**

---

## 0. The scope correction was right, and the cause is worse than the count

Wilson corrected my "3 of 5 lanes" to **2 of 5** — I²C depends on edge capture
too. Checked in the repo, all three hold:

| ruling | dependency |
|---|---|
| **N1a** | the HIGH count starts when SCL *goes* high, so a slow rise lengthens the period and `tr` leaves the controller's budget |
| **A2-P4** | clock stretch is a latency question only if the engine waits on the *observed* release; a busy-wait makes `C_i` unbounded and takes every lane with it |
| **R3** | the SDA read lands on the observed SCL rise |

> ⛔⛔ **And two of them justified themselves by asserting the capability already
> existed.**
>
> **R3:** *"The engine **already has** a reactive release on the observed SCL rise
> — that is the REACTIVE-J action gate 0.9b classified… ⭐ the correct rule **costs
> nothing**."*
>
> **N1a:** *"The same sampled-SCL-high condition is **already required** by A2
> Part 4 for clock stretching, so **no new mechanism is needed**."*
>
> "No new mechanism is needed" was true of the **model** and false of the **chip**.
> Gate 0.9b *classifies* a lane REACTIVE-J — a label, not an implementation — and
> each ruling cited the other's requirement as evidence the mechanism was there.
> **"Costs nothing" was priced against a register that was never built.**

⛔ **Second day-one commitment found unbuilt.** `ARCH_PREREG_01` commitment 1 is
*"edge timestamping on input pins — cheap (a counter and a capture register), and
it is the entire substrate for protocol discovery. **Built even though nothing
consumes it yet.**"* Commitment 3 was the golden model. Neither existed.

---

## 1. What was built — 46 flops

| piece | flops | |
|---|---|---|
| `uio_q0`, `uio_q1` | **0** | already present |
| `uio_q2` (3rd stage) | 8 | completes `L_sync = 3` |
| edge detect | **0** | combinational: `rise = q1 & ~q2` |
| `l_armed` / `l_armpin` / `l_armedge` | 30 | 1 + 4 + 1, × 5 lanes |
| `l_notmo`, `l_timeout` | 10 | "no timeout", sticky TIMEOUT |
| **timeout comparator** | **0** | see below |
| **measured** | **+46** | 2,855 → 2,901 (derived 48; Yosys folded 2) |

⭐ **The timeout costs no comparator.** `ST_WB` already does
`l_timestamp += a_dly` and `ready` already tests `now − l_timestamp`, so an ARM
with a delay **is** a deadline and the existing machinery enforces it. The edge
is an *early* release against it. Ruling 2's stored-timestamp discipline paying
for red-team 3's deadline-mode primitive.

⭐ `l_armed` **is** the edge latch, and arming is the clear — so Ruling 3's
"ignore an edge before ARM" holds **by construction**, with one bit fewer and
one fewer way to get a clear wrong.

---

## 2. The three fixes

### Fix 1 — rebase on edge (the one that would have broken UART)

On an edge release, `l_timestamp := now`. Without it, every action after an
*early* release is timed from the ARM's **timeout instant** — and 0.9b derives
UART-rx's sample grid as `edge + half + m·T`, so a deadline-anchored grid misses
every bit.

⭐ It also removes the need for a per-lane `l_edge_time` register: the rebase
happens **at capture**, not at dispatch. 16 × 5 = **80 flops not spent.**

### Fix 2 — a timeout must never look like an edge

A timeout **halts** the lane and sets a sticky `l_timeout`. Not because it is
tidier: with `release = armed & (edge | deadline)` a program cannot tell *"the
peer answered"* from *"the peer never answered"*, and would **read a frame out of
an idle line**. That is the forbidden direction one level up — not a number too
small, but a chip reporting data it never received. "No timeout" is
`delay == 0`, an encoding in an existing field.

### Fix 3 — edge-latch policy

Clear on arm, which `l_armed` gives for free. **1.6v** bounds the race: ARM must
dispatch before the peer's next legal edge.

---

## 3. The four must-fires — `test/tb_edge.v`

A **separate** bench on purpose: `tb_smoke` owns C, J, the buffer-swap invariant
and the cold/steady split, and it passes. This one drives **protocol inputs
during run** through a resolved bus (engine drives when `uio_oe`, bench otherwise)
— forcing `uio_in` would have hidden an engine-vs-peer contention bug.

| | result |
|---|---|
| **1 REBASE** — `t_out − t_edge` constant across 4 phases | **18 cycles, constant** ✅ |
| **2 NO EDGE** — no release, no invented data | 0 output edges in 600 cycles ✅ |
| **3 TIMEOUT** — halts, flag sticky, 0 further actions | ✅ |
| **4 STRETCH** — held-low SCL delays the high phase | **18 cycles** across 30/70/110 ✅ |

> ⛔⛔ **The bench was measuring the wrong window first.** It drove the peer edge
> at a fixed cycle after run entry — 40 to 109 — and the header load plus
> prime-before-release take ~100 cycles, so **every edge landed before `OP_ARM`
> had dispatched** and was correctly *ignored*. Must-fires 1 and 4 reported "no
> output edge at all".
>
> ⭐ **The pass of 2 and 3 beside the failure of 1 and 4 is what said so:** the
> *absence* tests passed because absence is exactly what an unarmed lane
> produces. `phase` now means cycles **after arming**, which is the quantity
> Ruling 1 is about.

### Mutants

| mutant | verdict |
|---|---|
| `M_NO_REBASE` | **RED** — must-fire 1 fails (`t_out − t_edge` becomes −1,−1,−1,102) |
| `M_TIMEOUT_PROCEED` | **RED** — must-fire 3 fails, 1/2/4 still pass |

> ⚠ **Coverage, measured not assumed: must-fire 4 does NOT catch `M_NO_REBASE`.**
> It still reports a constant offset, because its program uses `timeout = 0` and
> an un-rebased timestamp reaches readiness another way. **Only must-fire 1, with
> a finite deadline, distinguishes it.** Two must-fires that look alike are not
> two must-fires.

> ⛔ **And `run_mutants.py` was decoding subprocess output as cp1252**, so the
> reader thread died on the ⭐/⛔ bytes the benches print and the captured stream
> was **truncated** — verdicts were being parsed from a partial read. It presented
> as "the unmutated tb_edge does not pass" while the same command passed by hand.
> Now explicit UTF-8.

---

## 4. `L_sync` derived — `gate_edge_capture.py`

`L_SYNC = 3` and `L_JIT = 1` have been in `bursty.py` since 0.9b, used to derive
every reactive lane's `D_tol`. The chip had two stages and no edge detect, so
both constants described a mechanism that did not exist.

Derived from `q0 → q1 → q2` with `rise = q1 & ~q2` and a registered capture:

```
latency  2.000 .. 2.999 cycles   ->  L_sync = 3   (ceil: the budget holds for every phase)
uncertainty                 1    ->  == L_JIT
```

Both match A2 exactly. The derivation **moves with the structure** — 2 stages
gives 1..1.999, 4 stages gives 3..3.999 and would be red — so it is not a
constant in disguise.

> ⛔ **The first version floored the latency to whole cycles and reported an
> uncertainty of ZERO**, destroying the one quantity the gate exists to measure.
> The latency is *continuous* in the arrival phase; the spread **is** the jitter.
> Rounding it away produces a number that looks better and means nothing.

⭐ **Cross-check:** `L_sync 3 + C 2 + d1 12 + 1 drive cycle = 18`, which is
exactly the constant `tb_edge` measures. The derived chain model and the chain
agree.

---

## 5. The freeze was stale since S3 — now 36 fields

S2 carried **24** fields. S3 found five it lacked by writing RTL and watching it
fail; reverse traceability found them again from the spec side, **plus `armed`,
which S3's list did not have.** Folded in with their rulings:

`program counter`, `program base`, `action buffer + valid (×2)`,
`fetch pointer`, `buffer select`, `armed`, `armed pin`, `armed edge polarity`,
`no-timeout`, `TIMEOUT (sticky)`, `primed (one-shot)`,
`input sync chain + edge detect`.

**36 fields, all traced, no duplicates.** Reverse traceability now reports
**0 behaviours with no field.**

> ⭐⭐ **And the must-fire became synthetic, which is the structural point.** It
> used to assert that `program counter` and `program base` were reported missing
> — which would have gone **vacuous** the moment the gap was closed: the guard
> would have depended, for its own strength, on the defect never being fixed. It
> now injects a deliberately-absent field name and checks a frozen one as a
> control. **A guard priced by an injected defect keeps working after the real one
> is repaired.**

> ⛔ **The RTL scan in that gate also went stale and reported a false finding.**
> It grepped for `pin_sync`/`pin_in_q` and went on saying "no edge capture"
> *after* edge capture was built under different names. **A grep for a mechanism is
> a grep for the names you expected it to have**, and it failed in both
> directions. It now lists all 12 markers and reports partial matches rather than
> rounding to present or absent.

### New admissibility conditions — 1.6 at 22

- **1.6u** — a reactive lane's **first action must be ARM**. Prime-before-release
  frees `now`, so a lane with `l_timestamp = 0` is immediately ready; a receiver
  that starts on an idle line invents a frame. The census already writes them
  that way, so this rejects the program we'd write **by accident**.
- **1.6v** — ARM must dispatch before the peer's next legal edge. Reactive lanes
  only: `SPI-target gap 25 vs D 20` (slack 5), `I²C 45 vs 17`, `UART-rx 414 vs 215`.

> ⛔ 1.6v failed first on **SPI-tx** — a *source* lane that never arms. A condition
> applied to lanes it does not govern produces a red that says nothing, which is
> a guard firing for the wrong reason with the sign flipped.

---

## 6. State

- **A2 suite 29 of 29**, digest `b4e51034e283`, ledger entry 2 of 2.
- `price_gates.sh` **13 of 13**; `run_mutants.py` **4 of 4**; `tb_edge` **4 of 4**.
- `yosys_check.sh`: plain Verilog, `check -assert` clean, **0 multi-driver**,
  **2,901 flops**. Local F2: **24 of 24** output bits flop-or-const.
- `tb_smoke` unchanged: 130/84 edges, C = 2.00, cold 0 == steady 0.

### Still owed

1. **The half-bit offset has nowhere to live.** The rebase lands the first
   post-ARM action *at* the edge, but UART-rx needs its first sample at
   `edge + half`. ARM's delay field is the timeout, and a delay only takes effect
   at an action's *writeback* — so it delays the next action, not its own. **The
   ISA has no pure-delay opcode**, and the census's `p_uart_rx` assumed "centred
   by the lane's phase" was free. Needs a ruling: a pure-delay opcode, a no-op
   `LEVEL` as the idiom, or a rebase of `now + offset`.
2. **CI `gds` on the edge-capture RTL** — and with it, F2 face 3 on a real
   netlist *after* the uio fix.
3. **TChecker for bursty-with-jitter** — the two `m_i > 1` lanes still carry one
   foreign witness at `J > 0`.
4. `test/test.py` — all 5 cocotb tests still assert the superseded load path.
