# Phase 1 close-out, part 7 — release fixed in hardware, and three primary reads

Answers the rulings issued after `08cf927`. Continues
[`PHASE1_CLOSEOUT_PART6.md`](PHASE1_CLOSEOUT_PART6.md).

Reproduce: `python model/a2/run_a2.py` (21 of 21) ·
`python model/a2/gate_miso_tristate.py` · `python model/macro_harden_gate.py`
(red on purpose) · `python model/f2_flop_driven_outputs.py` ·
`python model/sram_spike.py` · `bash model/price_gates.sh` (9 of 9).

---

## ✅ 1.6r — release is fixed in hardware, not pushed onto the master

**The previous shape of this condition was the fallback dressed as the fix.** A
fully synchronous enable follows CS by `L_sync + out_reg = 4` cycles in *both*
directions, so for 80 ns after the master deselects us we are still driving the
shared line. The first version wrote *"the master must leave ≥ 5 cycles"* into
the host spec. ⛔ That is not a fix — the contention window is real and a host
cannot be relied on to avoid it.

**The fix is the reset-synchroniser pattern applied to the enable:**

| direction | mechanism | latency |
|---|---|---|
| **release** (`oe → 0`) | CS rising **asynchronously clears** the `uio_oe` flop | pad + clear delay, **sub-cycle** |
| **assert** (`oe → 1`) | through the synchroniser, as before | 4 cycles |

⭐⭐ **And F2 still holds.** The pin is still driven by a flop's Q — an
async-clear flop *is* a flop. So this does not trade a correctness property for
a timing one; F2's checker only has to **recognise** the cell, which is
classification, not a waiver.

### The must-fire is two-sided, which is what makes it evidence

| enable design | contention under a zero-gap master |
|---|---|
| ✅ async-clear (ruled) | **0 cycles** |
| ⛔ fully synchronous (superseded) | **4 cycles** |

⭐ A one-sided arm would only show the new design passing — which a design that
*never drives at all* would also do. The arm is evidence because the design it
replaces is run through it and **dies**.

### The residual risk, priced, and it points the safe way

A glitch on CS now **releases** MISO mid-transfer.

| | no glitch | with glitch | **glitch alone** |
|---|---|---|---|
| contention cycles | 0 | 0 | **0** |
| floating-while-selected | 4 | 5 | **1** |

⛔ **The arm had to isolate its own term.** The same trace *without* a glitch
already floats for the first 4 steps, because the **assert** path is
synchronised. Reporting the raw count would charge the glitch for the assert
warm-up and overstate the risk by 5×, so the cost is the **difference**.

⭐ **The direction is the safe one, and that is the whole justification for the
asymmetry.** A glitch can only turn a driver **off**, so it costs a corrupted
bit (the master samples a float) and can **never** cause contention. The
superseded design failed the other way — it could only turn a driver **on**
late, which *is* contention. A corrupted bit is a detected, retryable protocol
error; contention is two output stages fighting.

⇒ **Part 1 must explicitly pick one:** filter CS before the async clear (a 2–3
cycle digital filter, which re-introduces part of the lag it removed), or record
the glitch sensitivity as a limitation. ⛔ Silently doing neither is how this
becomes a field failure nobody predicted.

⇒ **Phase 4 SDC owes recovery/removal** on the async clear's **deassert** edge —
a clear releasing near a clock edge is its own metastability hazard, *moved*
rather than removed.

### What remains on the host: the assert side only

MISO becomes valid ~4 cycles (80 ns) after CS falls, so the requirement is a
**CS setup ≥ 4 cycles before the first SCLK edge** — 16 % of the 25-cycle SCK
half-period. ⭐ **A CS setup is routine for an SPI target**; every target has
one. An inter-select *gap* is an unusual demand on a master. The requirement got
smaller **and** more ordinary.

⛔ **One number is still deliberately not quoted.** The MB85RS64V AC table
*names* an "Output disable time" and a "Deselect time" — so release latency is a
budgeted quantity on real parts — but that table's text layer is **scrambled**
(the 1.1 boundary for this part). **Parameter names are evidence; its values are
not**, and none is used.

---

## F2 face 4 — the async-clear acceptance was only *incidental*

The flop pattern already contains `dfr`, so `dfrbpq`-style async-reset cells
*happened* to classify correctly — and **nothing tested it.** That is the same
defect as `uio_oe` being in `OUT_PORTS` with no face exercising it: a property
that holds by accident can be lost by a pattern edit nobody connects to MISO.

F2 is now **2 passing faces + 4 mutants + fail-closed on unknown cells**, and
face 3 (today's combinational readback) stays red on purpose.

---

## ⛔⛔ Three primary reads, and two of them falsified my own claims

### 1. Placement — the DEF overturned my inference *and* my instrument

ORIGIN: `tech/ihp-sg13cmos5l/def/tt_block_6x4_pgvdd.def`,
**TinyTapeout/tt-support-tools @ `ihp-sg13cmos5l`** — our exact tile size,
first-party to the competition's own flow.

```
DIEAREA ( 0 0 ) ( 1289280 710640 ) ;      UNITS DISTANCE MICRONS 1000
PINS 43 ;   all at y = 710140, all on LAYER Metal4
pin x range 29760 .. 191040
TRACKS ... STEP  480 LAYER Metal4         -> 0.48 um
TRACKS ... STEP 2280 LAYER TopMetal1      -> 2.28 um
```

**All 43 pins sit in the leftmost 161 µm (13 %) of a 1289 µm die, on the max-Y
edge.** The IO is a **corner cluster**, not an edge.

⛔ **I had inferred the IO side from `LEFT/RIGHT_MARGIN_MULT = 6` against
`TOP/BOTTOM = 1`**, concluded left+right, and my scoring matrix therefore
preferred the **TOP edge** — which is the **IO edge**. The recommendation
pointed at the single worst placement.

⭐ **The lesson is about the instrument, not the answer.** A matrix that scores
every assumption looks rigorous and cannot tell you which assumption is *true*
— it launders a guess as coverage. One primary read collapsed it and **reversed
it**. The matrix is kept as a backstop and explicitly scored against the known
answer so its earlier preference stays visible.

⇒ ✅ **Place the macro at the MIN-Y / MAX-X corner**, diagonally opposite the pin
cluster. Which is the **original** ruling — "the edge or corner away from the pin
side" — not my refinement.

⛔ **And the pins are on `Metal4`, the layer the macro's `OBS` blocks.** Routes
leaving those pins *start* on the one layer the macro is opaque to. That is an
independent reason to keep it far away, and it needs no crossing count.

### 2. A pitch correction: TopMetal1 is 2.28 µm, not 3.28

| source | pitch | crossing tracks over the macro |
|---|---|---|
| **DEF `TRACKS STEP 2280`** (this flow's grid) | **2.28 µm** | **103** |
| my earlier read of the PDK tech LEF | 3.28 µm | 72 |

⭐ The DEF wins **for this purpose** because it *is* the grid the router uses for
our tile. ⚠ But a one-digit disagreement is what a transposition looks like, so
re-reading the tech LEF is **owed**, and the conflict is recorded rather than
quietly resolved. ⛔ Either way the conclusion is unchanged: TopMetal1 is the
only layer crossing the macro and is **~14× scarcer** than the layers below, so
placement is the mitigation.

### 3. The 6×4 die area was wrong by 2.1×, and the DEF reconciles a flagged conflict

| | area |
|---|---|
| `167 × 108 × 24` tiles (ARCH_PREREG_01 s110) | 432,864 µm² |
| **DEF `DIEAREA`** | **916,214 µm²** |

⭐ **This settles the conflict `info.yaml` itself flagged.** Our own shipped run
reports a **902,417 µm² core** — impossible inside a 432,864 µm² die, and
consistent with a 916,214 µm² one (the difference is the core-to-die margin).
The tile-multiple arithmetic is superseded. Today's 64 B flop store is **4.3 %**
of the real 6×4 die.

### 4. ⛔⛔ `MEM_TYPE = "sram"` is a **cross-PDK** instantiation

The `ihp-sg13cmos5l` PDK tree at the pinned commit contains **no SRAM macro
library** — `libs.ref` has only `sg13cmos5l_stdcell` and `sg13cmos5l_io`;
`libs.tech` has only `klayout` and `gnucap`. The `RM_IHPSG13_1P_*` family lives
in the `ihp-sg13g2` tree.

⇒ **Using the macro here means dropping SG13G2 LEF/GDS/LIB artefacts into a
CMOS5L design.** ⭐ Geometrically defensible — CMOS5L is the same process minus
HBTs and minus Metal5/TopMetal2, and the macro tops out at **Metal4, below both
removed layers** — and TT's own allowlist change (PR #187) is layer-based and was
tested with an `RM_IHPSG13_1P_*` part, consistent with exactly this workflow.
⛔ **But it must be said as what it is, not as "the PDK's SRAM."**

⛔⛔ **And this corrects PART5's finding #1, which I recorded as *primary*:**
*"IHP-Open-PDK has exactly one PDK directory, `ihp-sg13g2`. No sg13cmos5l tree."*
At the commit this flow **pins** (`2bbec75`) there **is** an `ihp-sg13cmos5l`
tree, plus `ihp-common`.

⭐ **The defect was in the origin field, not the reading.** I wrote the origin as
*"the repo's own top-level listing"* **without a ref**. A listing is a snapshot
of a commit, and omitting which one is what let a primary fact go stale and then
false. ⇒ **An origin must name the ref, not just the repo.**

---

## `ROUTED` is now defined, because `GRT_ALLOW_CONGESTION = 1`

The router is **told** not to fail on congestion, so it can succeed by
**overflowing** and pay in detour, coupling and delay. A flow that prints
success is not evidence. The gate asserts three things, all required:

1. **global-route overflow = 0, parsed** from the GRT report — *not* inferred
   from the absence of an error, because the flow is configured not to error;
2. **detailed-route DRC clean**;
3. **timing met** at the corner that matters.

⛔ **A route that succeeds by overflowing is a fail under this gate, whatever
the flow prints.**

---

## ⛔⛔ QUARANTINED: the PDN strap layer

The remaining question — whether the vertical straps land on **TopMetal1**
(passing over the macro's `OBS`) or **Metal4** (blocked by it) — is **not
resolved, and not for lack of trying.** Ruled out by primary full-tree reads:

| location | result |
|---|---|
| IHP-Open-PDK @ `2bbec75`, `ihp-sg13cmos5l` | no openlane/librelane config, no tech LEF |
| TinyTapeout/tt-support-tools @ `ihp-sg13cmos5l` | no PDN config |
| TinyTapeout/tt-gds-action @ `ihp-cmos5l` | only `install_sg13cmos5l.sh` (PDK = IHP-Open-PDK @ `2bbec75`) + `action.yml` (librelane `3.1.0.dev3`) |

⇒ It therefore lives in **LibreLane's own built-in PDK config**.

⛔ **Why the work stopped there.** The one search that reached it returned a
paraphrase of **another competition entry's issue and pull request** — their
diagnosis *and* their fix. That must not enter an open-source submission, so it
was not read, not used, and is **not recorded here or anywhere in this repo**.
**Nate rules on how to proceed.** The legitimate routes are LibreLane's own
config, or our own run's `GeneratePDN` log.

⚠ **The same applies to the "observed public GeneratePDN failure" this project
has cited since PART5.** It traces to that entry's issue tracker — **singular**,
not "public issue titles" plural. It needs **re-labelling, not repeating.**

---

## Status

**21 of 21 model gates green**, one lane table (**`8ea5756203e1`**, unchanged
again). `price_gates.sh` **9 of 9**. 1.6 at **18 conditions**, each with a firing
witness.

**Three gates red on purpose**, all outside `run_a2.py`:
`model/part1_param_contract.py`, `model/f2_flop_driven_outputs.py` face 3
against the real netlist, `model/macro_harden_gate.py`. Plus the push-pull face
(b) of the drive-mode must-fire.

**Next:** Nate's ruling on the quarantine → the strap layer from a legitimate
source → the harden run (placed + **ROUTED as defined** + timing) → re-close 1.5
→ Part 1 RTL.

**Still owed:** `C` unmeasured; the engine is not built; `nptest` exactness;
re-read the PDK tech LEF for TopMetal1's pitch; H4 (`refs/ieee_try.bin`,
`refs/t2.bin` — safe to delete, Nate's hand).
