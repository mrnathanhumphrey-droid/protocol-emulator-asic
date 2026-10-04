# Phase 2 — derived, and flagged back before building

Per the kickoff: *"code derives the details and flags back."* Nothing below is
built. Five findings change the plan, two of them substantively.

---

## Tooling: better than expected, with one gap

| tool | where | note |
|---|---|---|
| iverilog | **Windows** | the existing benches |
| **Verilator 5.032** | **WSL** | available ✅ |
| **sigrok-cli** | **WSL** | `uart`, `spi`, `i2c` decoders all present ✅ |
| yosys | WSL | already used by `yosys_check.sh` |
| cocotb | Windows | 2.0.1 |
| **IHP cell models** | **absent locally** | ⛔ gate-level sim can only run in CI |

⭐ **Verilator accepts the design's multi-edge async block** —
`always @(posedge clk or posedge cs_deasserted or negedge rst_n)`, the 1.6r
async-clear — so the MISO release does not have to be restructured for a second
simulator. That was the thing most likely to block arm (a) and it does not.

⛔ **The two simulators live in different environments** (iverilog on Windows,
Verilator in WSL). A single harness process cannot invoke both directly; it has
to drive each and compare artefacts across the boundary, with the WSL calls made
through **script files**, never inline `bash -c` with expanded vars.

---

## ⛔ Finding 1 — Verilator rejects the design today, on 6 warnings at 5 sites

`verilator --lint-only` exits **1**. All six are width mismatches, and **none is
a bug** — each was checked:

| site | expression | why it is benign |
|---|---|---|
| `pe_engine.v:793` | `hl == N_LANES-1` | `hl` 3 bits vs 4; zero-extends |
| `pe_engine.v:767` | `hb == HDR_BYTES-1` | `hb` 4 bits vs 5; zero-extends |
| `pe_engine.v:832,847` | `pl == N_LANES-1` | same |
| `pe_engine.v:641` | `s_raddr <= hl*HDR_BYTES + hb` | max `4*6+5 = 29` into AW=8 |

> ⛔ **The fix must not be a lint suppression.** `/* verilator lint_off WIDTH */`
> would hide a genuine overflow if one ever appeared, and the truncation at
> `s_raddr` is exactly where one could: `N_LANES * HDR_BYTES + HDR_BYTES` must
> fit in `2^AW`, which holds at the shipped config (29 < 256) and is **not
> checked anywhere**.
>
> ⇒ Proposed: derived-width intermediate wires at the five sites, **plus an
> elaboration-time assertion** on that inequality. ⚠ The widths must stay
> parameter-derived — `part1_param_contract.py` rejects a literal width, because
> a bare `[15:0]` is also the I²C `D_tol` constant.

**Cost:** ~5 small edits plus one assertion. It is a prerequisite for *all* of
arm (a), so it comes first.

---

## ⛔⛔ Finding 2 — the resolved-bus plan needs changing, twice

Arm (c) says *"contention → X; bench asserts no-X."* Two independent reasons that
is not sufficient.

**(i) X requires the two drivers to DISAGREE.** Measured this batch: the bad
no-op program drove the arm pin LOW while the peer was driving it LOW (that
*is* the edge), so two drivers fought and the bus **resolved cleanly to 0 with
X = 0**. The contention was real and invisible. It was caught by **135 cycles of
enable overlap**, not by X.

**(ii) Verilator is 2-state — it has no X at all.** So an X-based check cannot
run in the second simulator even in the disagreeing case.

> ⇒ **The portable detector is ENABLE OVERLAP**: assert that the engine never
> asserts `uio_oe[p]` while the peer model drives `p`. X stays as a second,
> weaker signal — it catches disagreement and says nothing about agreement.
> A bench that keys only on X would pass a design that drives against its peer
> in agreement, which is electrically a fight and protocol-wise a corrupted bit.

This also means arm (c)'s FRAM models must **export their drive-enable**, not
just their pin value, so the harness can see overlap.

---

## Finding 3 — gate-level belongs in CI, and that reshapes (a) and (e)

No IHP cell models locally, so a gate-level netlist cannot be simulated on this
machine. But CI's `gl_test` job already does exactly that, inside the `gds`
workflow.

⇒ The split is:

| | local | CI |
|---|---|---|
| RTL vs golden, iverilog | ✅ | ✅ |
| RTL vs golden, **Verilator** | ✅ (after Finding 1) | ✅ |
| **gate-level** vs golden | ✖ no cell models | ✅ `gl_test` |

⭐ And that makes arm (e) the natural vehicle: `gl_test` currently runs
`test/test.py`, whose 5 cocotb tests all assert the **superseded load path**
(`test_pointer_echo_and_autoincrement` expects the pointer echo 1.6q removed).
Replacing that file *is* arm (e), and it is what makes gate-level coverage real
rather than a job that has been red so long it is read as furniture.

⚠ **The harden is ~3½ hours**, so every CI-side arm has that feedback loop. The
local JSON-netlist trick that cut F2 from 3½ hours to seconds has no equivalent
for behavioural gate-level sim — it needs the real cells.

---

## A2 RESEARCH RESULT — no vendor HDL model found

Wilson's amendment A2 asked whether a vendor ships one. Searched:

| part | result |
|---|---|
| MB85RS64V / MB85RC256V (RAMXEED, ex-Fujitsu) | datasheets only, **no HDL model** |
| Infineon F-RAM FM25V02 / FM24V10 | **no HDL model found** |
| Infineon **NOR flash** S25FL… | Verilog/VHDL models **are** published — a *different device class* |

> ⚠ The search was not exhaustive — a vendor may supply one on request to a
> registered account — so this records **"not found"**, never "does not exist".

⇒ Per A2, the foreign peer arrives at **rung 5: the real part on the Artix**.

> ⛔⛔ **And a vendor model could not be committed even if found.** The
> submission is open source and a vendor model is third-party code under its own
> licence — like the datasheets already quarantined in the gitignored `refs/`.
> It would have to follow **pyRTA's pattern exactly**: not vendored, located
> through an env var, and the gate RED without it so the dependency stays
> priceable. That is worth knowing *before* anyone goes looking, because
> "we found a foreign model" would not by itself mean we could ship with it.

---

## ⛔⛔ Finding 6 (new) — Verilator caught the multi-driver class in the peer model

The first `fram_spi.v` drove six signals from four blocks (`negedge cs_n`,
`posedge cs_n`, `posedge sck`, `negedge sck`) — the natural way to write a peer
model. **iverilog accepted it silently. Verilator rejected all six as
MULTIDRIVEN.**

⭐ That is the *same defect class* that made the engine unsynthesizable and
killed a harden after three minutes: multiple procedural drivers are
last-write-wins in simulation and an error in synthesis.

⇒ **The engine's "one sequential block" discipline applies to the peers too**,
and a second simulator is what enforced it. CS is now a *synchronous* reset
inside each block, and the one genuinely asynchronous requirement — release on
deselect — is a combinational gate on `so_oe` rather than a second always block.

⭐ `fram_spi.v` is now clean in **both** simulators. Note the engine is **not**
yet (Finding 1's six width warnings), so the peer model reached two-simulator
cleanliness first.

---

## Finding 4 — the FRAM models are mine to write, and the datasheets must not travel

Arm (c) needs behavioural models for **MB85RS64V** (SPI) and **MB85RC256V**
(I²C). Neither exists. The protocol facts are already extracted into the repo
(the census quotes the opcode/address/ACK sequences, and F1's correction records
that our parts take **two** address bytes).

> ⛔ The PDFs live in `refs/`, which is gitignored with the guard committed
> (`refs/.gitignore` = `*`) because the submission is **open source** and the
> datasheets are third-party. A model I write describing a protocol is my own
> code and publishes fine; the PDFs must never enter the tree, and the models
> must be built from the facts already extracted rather than by copying text in.

**Cost:** the two models are the largest single piece of Phase 2 — a correct
FRAM responder with address auto-increment, WREN/WRDI state and ACK generation.

---

## Finding 5 — "two-sim byte-exact" needs its merge semantics stated, and the golden model is not yet cycle-accurate

`model/golden.py` is an **ISA semantics**: it produces pin events with offsets
relative to each action's start, and the scheduler owns absolute time. It does
**not** currently model `L_sync`, the dispatch pipeline, the double buffer or
prime-before-release — so it cannot be compared byte-exact against the RTL's
waveform cycle by cycle without first deciding what "byte-exact" compares.

Proposed, for ruling:

- compare the **decoded byte stream** (via sigrok) rather than the cycle-by-cycle
  pin vector. That is what arm (b) already implies, it is what the protocol
  actually promises, and it does not require the golden model to grow a pipeline
  it does not have.
- keep the **cycle-accurate** comparison between the two *simulators* (iverilog
  vs Verilator vs gate-level), where both sides are the same RTL and a
  disagreement is a real tool or netlist problem.

⇒ **Two different comparisons, stated separately:**

```
golden  <-> decoded byte stream        (semantic: does it speak the protocol)
sim A   <-> sim B  <-> gate-level      (cycle-exact: do the three agree)
```

Conflating them would mean growing the golden model into a second
implementation of the pipeline — which is precisely the same-author
re-derivation the model was written to avoid.

---

## Proposed order

1. **Finding 1** — width tightening + the `N_LANES*HDR_BYTES` assertion.
   Unblocks everything in (a). Smallest piece, hardest dependency.
2. **Arm (c) first, not last** — FRAM models with exported enables, and the
   **enable-overlap** detector. It is the biggest piece and (d)'s must-fires all
   need a peer.
3. **Arm (a)** — two-sim cycle-exact on RTL, local; gate-level in CI.
4. **Arm (b)** — sigrok decode vs golden, with each comparison shown RED against
   a corrupted golden first.
5. **Arm (d)+(e)** — the owed cocotb must-fires, replacing `test/test.py`, so CI
   green means exercised.

## Questions I need answered before building

1. **The two comparisons in Finding 5** — split as proposed, or do you want the
   golden model grown into a cycle-accurate model of the pipeline?
2. **Finding 2** — confirm enable-overlap becomes the primary contention
   assertion, with X demoted to a secondary signal.
3. **Finding 1** — derived-width intermediates plus the elaboration assertion, or
   would you rather see the five expressions restructured some other way?
