# SPEC v4 — S3: the engine

First real RTL in this project. Continues
[`SPEC_V4_S2_SPEC_FREEZE.md`](SPEC_V4_S2_SPEC_FREEZE.md).

Reproduce:
`iverilog -g2012 -o test/smoke.vvp -s tb_smoke test/tb_smoke.v src/project.v src/pe_engine.v src/pe_store.v && vvp test/smoke.vvp`
· `python test/make_smoke_image.py` · `python model/part1_param_contract.py`
(**now green**) · `python model/a2/run_a2.py` (23 of 23).

⛔⛔ Built with **no reference to any other competition entrant's repository or
pull-request content**. The S2 quarantine covers the engine.

---

## ✅ What landed

| file | role |
|---|---|
| `src/project.v` | top: two pin banks, mode control, loader, serialiser, MISO release |
| `src/pe_engine.v` | non-preemptive EDF, fetch pipeline, pin drive |
| `src/pe_store.v` | program store, `MEM_TYPE` + a wide action-fetch port |
| `test/tb_smoke.v`, `test/make_smoke_image.py` | the bench that found everything below |

**`model/part1_param_contract.py` is GREEN** — all 8 parameters present, no
protocol constant anywhere in the RTL, no PDK cells. It went green because the
work landed, not because it was loosened.

⭐ **Every width is parameter-derived, and the contract is why.** A bare
`[15:0]` would also be the I²C `D_tol` constant and the forbidden-literal scan
rejects it. That turned a lint into a design discipline.

---

## ⭐⭐ The headline: `C` and `J` are MEASURED

354 jobs over 4,000 cycles, counted by the bench, not derived from my own design
intent:

| quantity | A2 ships | measured | verdict |
|---|---|---|---|
| **`C`** | 2 | **2.00** (708 cycles / 354 jobs) | ✅ **confirmed** |
| **`J`** | 1 | **5** | ⛔ **over budget** |

⛔ **"The FSM has two states, therefore C = 2" is a same-author re-derivation of
my own design intent**, which this project has already recorded is not an
independent witness. So the bench counts cycles. It also reports `C × 100`,
because integer division truncates — 75/38 is 1.97 and prints as `1`, which
would have read as *"C = 1"* and looked like good news.

### ⛔⛔ And the shipped table has `J = 0`, not `J = 1`

The design point has been stated throughout as *"pipelined `C = 2, J = 1`"*.
`frontier.py` says why: *"J_pipe: registering the EDF winner makes every release
uncertain by 1"*, and *"pipelined: winner registered a cycle early → C = 2,
J_pipe = 1"*. **But every lane in the shipped table carries `J = 0`**, and the
shipped `r_i = {10, 7, 3, 9, 5}` with min margin 14 is that `J = 0` analysis.

So the shipped numbers correspond to **neither** 1.3 candidate — not
`(C=3, J=0)` and not `(C=2, J=1)`. They are optimistic against both.

**Priced in the A2 model across the whole range:**

| `J` | min margin | feasible? |
|---|---|---|
| 0 (**shipped**) | **14** | yes |
| 1 (**ruled design point**) | 13 | yes |
| 5 (**measured**) | **9** | **yes** |
| 6 | 8 | yes |

At the measured `J = 5`: `r = {15, 12, 8, 14, 10}`, min margin **9**, which
clears the pre-registered **margin ≥ 4** measurement-reserve bar.

⇒ ⭐ **This is a RE-BASELINE, not a failure.** The set stays feasible and the bar
is still met. ⛔ But it is a change to published numbers and it is **reported, not
absorbed** — changing the lane table changes the digest `8ea5756203e1` that every
gate cross-checks, so that is Wilson's call, not mine.

### Why `J = 5`, and how it got there from 20

An action is **3 bytes** and the store is **byte-wide with a registered read**, so
a fetch is 3 reads — which `C = 2` cannot contain. Options were: widen the store
to 24-bit words (~25,000 cells against a ~30,500 budget — rejected on cost);
narrow the action to 2 bytes (leaves 4 bits of delay, which cannot express a UART
bit period — rejected because it puts a protocol limit back in the encoding); or
**prefetch**.

Prefetch is implemented, and the first measurement was **`J = 20`**: a 9-cycle
byte-at-a-time refill, times contention across 5 lanes. ⛔ **The prefetch that
bought `C = 2` was spending it all back as `J`.**

⭐⭐ **The fix is unlocked by S0's own finding.** `MEM_TYPE = "flops"` means the
store is a **register array**, so a 3-byte-wide read is a wider **mux**, not more
storage. One registered cycle instead of nine. **`J` 20 → 5.**

⚠ **And it breaks a rule `pe_store.v` sets for itself** — that a build parameter
must not change timing behaviour. With `flops`, `J ≈ 5`; with a byte-wide SRAM
macro, `J ≥ 3` extra. Stated in the file, not hidden. The rule is violated only
on the path S0 blocked.

⚠ **The residual 5 is the shared fetch port** (scan + request + read + capture,
plus waiting behind another lane's refill). Getting to `J ≤ 1` needs per-lane
fetch engines (area) or a load-time condition that a lane's inter-action delay
exceeds the refill latency. **Not done; named.**

---

## ⛔⛔ Five fields the S2 freeze did not have

The engine could not work without any of them. **All five have the same root
cause:** the freeze's table came from the *descriptor* documents, which describe
lane **state**, and said nothing about the **fetch machinery** Ruling 1's
pipeline implies or about the **image's structure**.

| # | field | why it is required |
|---|---|---|
| 1 | per-lane **program counter** | lanes execute independently; there is no one stream |
| 2 | per-lane **prefetch word + valid** | what makes `C = 2` possible at all |
| 3 | per-lane **program base** (image) | without it every lane's PC starts at `ACT_BASE` and **all five run the same stream** |
| 4 | a **loop** | a lane's PC advanced linearly and **fell off the end of its program**; a periodic protocol cannot repeat |
| 5 | **drive mode in the image** | the freeze lists it as a register and **nothing set it** |

⭐⭐ **And the S2 gate could not have caught any of them.** Traceability detects
**a field with no ruling**. It cannot detect **a ruling with no field.** That
asymmetry is the real lesson of S3, and it is recorded rather than absorbed.

⭐ Item 4 was fixed without new state or a new opcode: `OP_REARM`'s existing
level bit now selects *extend the delay* (Ruling 2's chaining) versus *extend and
jump to base* (loop).

---

## ⛔ A new admissibility condition, found by simulation

Item 5's symptom was worth more than the fix. With `l_mode` stuck at 0 =
open-drain, a lane on a **`uo_out`** pin drove **low once and stuck there
forever** — while the scheduler ran perfectly and the bench's edge counter read
`1`.

**Open-drain is meaningless on `uo_out`:** open-drain holds `pin_out` at 0 and
modulates the **enable**, and `uo_out` **has no enable**.

⇒ **A lane in open-drain mode must be assigned a `uio` pin.** This is the
electrical-class rule from the pin map, but as a **load-time check on the
assignment** rather than a design-time check on the budget. 1.6o covers the
budget; nothing yet covers this. **Owed as a new 1.6 condition.**

---

## What the smoke bench found that elaboration did not

`iverilog` elaborated the engine **cleanly, with zero warnings, while it did
nothing at all.** That is the recorded failure mode — a gate-level sim passing
for weeks on a stub with zero flip-flops — so the bench drives the real pin-level
load protocol and **counts edges**.

| bug | symptom |
|---|---|
| registered-read **off-by-one**, in **three** places (header FSM, prefetch FSM, wide-fetch FSM) | fields unpack from the previous byte; `ready` = X; engine idle forever |
| **non-blocking unpack ordering** — unpacking `hsh` in the same cycle the last byte shifts in | every field 8 bits adrift; `l_pc` = 63 instead of 30 |
| header **field misalignment** — 38 bits sliced inside a 40-bit register | all fields 2 bits low |
| drive mode never loaded | see above |

⭐ **The correctness signal is not "pins moved".** Lane 0 and lane 1 produced
**134 and 86 edges**, a ratio of **1.56**, against programmed half-periods of 20
and 31 — ratio **1.55**. The *rate relationship* matches the program, which a
stuck or round-robin engine would not produce.

⛔ **One earlier green was also wrong for an interesting reason.** Before the fix,
`ready` was `l_live & l_actv & ~diff`, which conflated *"I have this lane's next
action in a register"* with *"this lane's job has been released"*. At most **one**
lane was ever ready, so **EDF never had two candidates** and the schedule
degenerated to round-robin-by-prefetch-availability — **and every lane still moved
its pins, so the bench passed.** A2 assumes every released lane competes.

---

## CI, and why the standing red mattered

`gds`, `gl_test` and `precheck` have all been **passing**. The only failing job is
**`viewer`**, which deploys to GitHub Pages and 404s because Pages is not enabled
— and cannot be, while the repo is private until submission.

⇒ `viewer` is now `continue-on-error: true`. ⛔ **A permanently red job trains you
to ignore CI**, and the `gds` result now matters for the first time, because real
RTL has landed. A standing red X is exactly where a genuine failure hides.

⚠ **And `gl_test` passing is still weak evidence.** It completed in 48 s against
the old load-path stub. The cocotb test in `test/test.py` was written for that
stub; until it exercises the engine, `gl_test` green means *"not yet exercised"*,
never *"correct"*. **Phase 2 owes that test.**

---

## Status and what S3 still owes

**`model/part1_param_contract.py` GREEN** · 23 of 23 model gates green · digest
`8ea5756203e1` unchanged · `price_gates.sh` 9 of 9 ·
`model/macro_harden_gate.py` still red on purpose.

⚠ **F2 faces 3 and 4 are NOT yet verified against the real design.** F2's
self-test passes, but face 3 is a check on a **synthesized gate-level netlist**,
which only CI produces. The RTL registers every output (`uo_q`, `pin_out`,
`pin_oe`, the async-clear MISO enable) so it *should* pass — **that is a
prediction, not a result**, until the netlist is checked.

**Owed:** F2 against the synthesized netlist · Wilson's ruling on the `J`
re-baseline · a 1.6 condition for open-drain-on-`uio` · per-lane fetch or a
delay condition if `J ≤ 1` is required · the protocol opcode *semantics*
verified per protocol (Phase 2 cocotb) · the area/timing numbers from the first
real `gds` run · re-read the TopMetal1 pitch · H4.
