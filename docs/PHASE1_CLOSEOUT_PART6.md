# Phase 1 close-out, part 6 — the MISO catch, and the harden gate

Answers the rulings issued after `a05d048`. Continues
[`PHASE1_CLOSEOUT_PART5.md`](PHASE1_CLOSEOUT_PART5.md).

Reproduce: `python model/a2/run_a2.py` (21 of 21) ·
`python model/a2/gate_miso_tristate.py` · `python model/macro_harden_gate.py`
(red on purpose) · `python model/f2_flop_driven_outputs.py` ·
`bash model/price_gates.sh` (9 of 9).

---

## ⛔⛔ MISO — the error was in a category, not in arithmetic

**An SPI target's MISO must be able to stop driving.** That is how several
targets share one MISO line, and `uo_out` is output-only and *always driven*. A
target MISO there is a permanent second driver: it contends with every other
device on every transfer not addressed to it.

⭐ **And the root cause was in my own model, one axis up from the numbers.**
`PINS_DIR` split the protocol pins by **direction** — (push-pull, inputs,
open-drain). On that axis a target's MISO is simply *"an output"*, so it landed
on `uo_out` with the other outputs and **every count balanced**. The arithmetic
was right. The axis was wrong: what `uo_out` cannot do is not "carry an input",
it is **relinquish**.

| electrical class | must be able to | bank |
|---|---|---|
| push-pull output | drive 0 and 1 | `uo_out` or `uio` |
| input | not drive at all | `uio` |
| open-drain (I²C SCL/SDA) | release → pull-up wins | **`uio` only** |
| tri-state (SPI-target MISO) | release → another target drives | **`uio` only** |

⛔ On a direction axis the last row **does not exist**. An open-drain I²C line
and a tri-stated target MISO are different protocols making the same demand, and
only one of them was in the table.

### Primary evidence, from the part that is our own rung-5 oracle

**MB85RS64V** — the FRAM the demo writes — documents the convention in its own
pin table:

> pin 1 `CS`: *"When CS is the 'H' level, device is in deselect (standby) status
> and **SO becomes High-Z**. Inputs from other pins are ignored at this time."*
>
> pin 2 `SO`: *"This is **High-Z during standby**."*

⭐ So the rule is not a convention we adopted — it is the observable behaviour of
the device our target shares a bus with. ORIGIN: `refs/mb85rs64v_ramxeed.txt`,
the RAMXEED datasheet's own PIN FUNCTIONAL DESCRIPTIONS section.

### The fix, and where the constraint went

| map | `uio` | `uo_out` (incl. 3 serial) |
|---|---|---|
| MISO as push-pull (**superseded**) | 7 of 8 | 8 of 8 |
| **RULED: MISO tri-state on `uio`** | **8 of 8** | **7 of 8** |

⭐ One pin changed banks and both banks still fit. **31 of 31 subsets remain
feasible** — and that was *counted*, not assumed: `gate_pin_subsets.py` now
enumerates all three maps side by side.

⛔ **But the restored spare is on the wrong bank to be useful.** 1.6o used to say
the lost `uo_out` spare was the constraint. The true statement is that the
constraint **moved**: `uio` is now exactly full, and `uo_out`'s one spare can
absorb another **push-pull output and nothing else**. A further input,
open-drain or tri-state line has nowhere to go.

### The foreign sweep got wider, and that was the actual gap

`gate_pin_subsets.py` used to run pyRTA over the **24** all-on-`uio` subsets.
The ruled map admits **31**, so the 7 subsets the placement ruling created had
never been checked by the foreign tool. The sweep now runs on the ruled set:
**31 subsets, 80 (lane, subset) pairs**, up from 54. Zero violations.

⭐ **The lane-table digest is unchanged at `8ea5756203e1`**, which is the precise
statement that this was a correctness fix with no schedulability consequence —
and ⛔ **exactly why the error survived a whole batch.** Nothing downstream
complained, because nothing downstream was wrong.

---

## ⛔ The MISO fix is **not complete** at `uio_oe = CS` — release takes time

New finding, and it became **1.6r**.

`CS` is an asynchronous input on `uio`, so it is synchronised (`L_sync = 3`) and
the enable is registered per F2 (`out_reg = 1`). The enable therefore follows
`CS` by **4 cycles in both directions** — and the **deassert** direction is the
one that bites: *for 4 cycles = 80 ns after the master deselects us, we are
still driving the shared line.*

**The firing witness is the ruled design, not a mutant.** A master that
deselects SPI-target and selects another target in the *same* cycle produces
**4 cycles of contention** — exactly the release latency. That is what makes
1.6r a condition on the **master**, and therefore host-facing spec rather than a
design bound.

| quantity | value |
|---|---|
| our release latency | 4 cyc = **80 ns** |
| SPI-target SCK half-period | 25 cyc = 500 ns |
| release as a fraction of a half-period | **16 %** |

⇒ Release completes inside one SCK half-period. A master that deselects us and
selects another target has to move two of its own GPIOs; it cannot plausibly do
so faster than it clocks SCK. ⚠ **Implied, not guaranteed** — so it is written
down, next to the serial format.

⛔ **And one number is deliberately not quoted.** The MB85RS64V AC table *has* a
named **"Output disable time"** and a **"Deselect time"**, so release latency is
a budgeted quantity on real parts rather than something this gate invented. But
that table's text layer is **scrambled** — it reads "Clock low time tCSH 25" and
"Chip select hold time tODV", with the parameter and symbol columns misaligned.
That is the same evidence boundary already recorded for this part in 1.1.
**The parameter names are evidence; the values from that table are not**, and
none is quoted. The threshold comes from our own lane table instead.

---

## F2 gains the face that matters most, and it was never exercised

`uio_oe` has been in F2's `OUT_PORTS` from the start — correct scope. ⛔ **But no
mutant face ever exercised it**, so the coverage was untested: scope without
evidence. The MISO ruling put the first *real* enable in the design, so the face
now exists.

**Face 4** — every data output correctly flopped, **only the enable
combinational**. A checker that looked at `uo_out`/`uio_out` and stopped would
call it compliant. It dies naming `uio_oe[0] COMBINATIONAL
sg13cmos5l_inv_1 <- sg13cmos5l_nand2_1`.

⭐ **The escalation that makes it F2's business:** a glitch on a **data** output
is a wrong level for a few hundred ps. A glitch on an **enable** switches a
second **driver** on — so a shared MISO gets two output stages at opposing
levels. **Contention, not a wrong value.** The enable earns the flop at least as
much as the data does.

F2 is now **four mutants + fail-closed on unknown cells**, and face 3 (today's
combinational readback) is still red on purpose.

---

## The harden gate — `model/macro_harden_gate.py`, red on purpose

### ⭐⭐ Primary evidence from our own repo: `src/config.json`

The settings the shipped flow actually runs with. The gate **reads** them rather
than restating them, because a config value quoted into a comment is one that
can drift without anything noticing.

| setting | value | consequence |
|---|---|---|
| `FP_PDN_MULTILAYER` | 0 | no horizontal straps — the PDN is a **single-layer vertical comb** |
| `FP_PDN_VPITCH` | 50.0 µm | a 236.8 µm macro intercepts **≥4 straps wherever it sits** |
| `FP_PDN_VWIDTH` | 2.1 µm | ~5 of the 72 TopMetal1 crossing tracks, if that is the layer |
| `GRT_ALLOW_CONGESTION` | **1** | ⭐⭐ the router is **told** to tolerate congestion |

⭐⭐ **`GRT_ALLOW_CONGESTION = 1` is the line that justifies the gate's shape.**
"The design routed" is a **weaker claim on this flow than it sounds** — it can
route by overflowing and pay in detour, coupling and delay. So requiring
**timing** rather than route completion is a *first-party* reason, not a cautious
preference. The ruling demanded exactly that; this is the evidence for why it
was necessary.

### ⛔ The two crossing problems are not the same problem

Edge placement was ruled to keep IO-to-engine routes off the macro. That is
correct, and it addresses **signal** crossing — the 72-track ceiling. It does
**nothing** for **PDN** crossing, and the reason is geometric: the straps are
**vertical at a fixed 50 µm pitch spanning the die**, so a 236.8 µm macro
intercepts ~5 of them **under every placement**. A window of width `W` on a
lattice of pitch `P` contains `floor(W/P)` or one more, by phase alone.

**Two problems, one lever each, and the ruling's rationale names only the first.**

⭐ **And for power that inverts the risk.** You *want* straps over a macro —
that is how its VDD/VSS pins get tapped. ≥4 guaranteed means the macro **cannot
be missed** by the PDN. So the failure mode was never "no strap reaches it". It
is narrower and sharper:

> ⛔ **Which layer do the vertical straps land on?**
> **TopMetal1** → they pass over the macro's M1–M4 `OBS` and tap down. Fine.
> **Metal4** → the macro's own `OBS` **blocks** them. `GeneratePDN` cannot cross
> the footprint. That is the observed public failure.

⛔ **My earlier framing was too loose.** *"CMOS5L has no Metal5, so the PDN is
already adjacent"* — "adjacent" does not say whether the straps sit **on** the
blocked layer, and that is the entire question. ⚠ The artefact that settles it is
the PDN configuration inside `tt-gds-action@ihp-cmos5l`, or the first run's own
`GeneratePDN` log. **Named, not guessed.**

### ⛔ A refinement to the placement ruling

*"The edge opposite the IO side"* presumes **one** IO side.
`LEFT/RIGHT_MARGIN_MULT = 6` against `TOP/BOTTOM = 1` is **consistent with the IO
channel being on the left and right edges** — ⚠ **secondary**, an inference from
a margin setting, not a pin placement. The primary artefact is the generated
DEF's `PINS` section, which does not exist yet.

⭐ **So the decision is made invariant to it.** The gate scores every placement
under every IO-edge assumption. If IO arrives on **both** left and right there is
**no opposite edge**, and a left or right corner sits *in* the fan-out channel.
The placement **perpendicular to the flow** keeps horizontal IO-to-engine routes
clear.

⇒ **Place at the top or bottom edge**, and pick between them from the DEF once
the first run produces one. `top edge` is clear under the most assumptions.

⚠ **One lever is deliberately not recommended.** Rotating to R90 cuts
intercepted straps from 5 to 3. Whether that is good or bad **depends on the
unknown layer** — fewer straps means fewer blocked crossings if they are on
Metal4, and fewer power taps if they are on TopMetal1. The **sign of the effect
is unknown**, so no recommendation is made. (Many SRAM macros also cannot
legally rotate, which is a second reason to settle the layer first.)

### What the gate requires

Four artefacts, all absent today: the placed+routed DEF, the GDS, the **timing
signoff summary**, and the `GeneratePDN` log. ⛔ **It will not accept a
successful `GeneratePDN` as a pass** — a PDN that completes, a design that
routes, and a design that *meets timing* are three different claims.

**Fallback order, unchanged:** macro to the top/bottom edge → **the flop store**,
which is the *shipped* design and not a degradation, since F1's encoding already
fits one transaction per protocol into 62 of 64 bytes at the existing `AW = 6`.

---

## 1.6 — now 18 conditions

| id | change |
|---|---|
| **1.6o** | restated **by electrical class**: `uio ≥ inputs + open-drain + tri-state`, `uo_out ≥ push-pull + 3 serial`. Now **two** must-fire faces |
| **1.6r** | **new** — shared MISO: the master leaves ≥ `L_sync + out_reg` cycles between deasserting our CS and selecting another target |

⭐ **1.6o's second face is the one worth keeping.** The superseded map was
**wireable** — it admitted all 31 subsets and every count balanced — **and it was
still wrong**. ⛔ *No pin count rejects it.* So the arm rejects it on
**electrical class** instead. A budget condition that only counts pins cannot
catch a pin in the wrong bank.

---

## Status

**21 of 21 model gates green**, one lane table (**`8ea5756203e1`**, unchanged).
`price_gates.sh` **9 of 9**. 1.6 at **18 conditions**, each with a firing
witness.

**Four gates are red on purpose** and must not be "fixed" — each is an
acceptance test for work not yet done, all deliberately **outside**
`run_a2.py`: `model/part1_param_contract.py`,
`model/f2_flop_driven_outputs.py` face 3 (against the real netlist),
`model/macro_harden_gate.py`, and the push-pull face (b) of the drive-mode
must-fire.

**Next:** the CMOS5L harden — **settle the strap layer first**, then placement
per section 3, full route, timing → re-close 1.5 → Part 1 RTL.

**Still owed:** `C` unmeasured; the engine is not built; `nptest` exactness;
H4 (`refs/ieee_try.bin`, `refs/t2.bin` — safe to delete, Nate's hand); the
memory-index compaction (Nate's go).

**Phase 2 cocotb must-fire added:** with our CS deasserted, MISO reads high-Z,
and a mutant driving MISO while deselected **fails for contention** with a second
modelled target. ⛔ **A single-target bench cannot kill that mutant** — with
nothing else on the line, an always-driven MISO reads correct. The bench needs
the FRAM model on the bus.
