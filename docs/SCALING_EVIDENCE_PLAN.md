# The scaling-evidence plan — and the two couplings it has to respect

Wilson's plan, recorded with the engineering constraints I found on it. The plan
itself is his; what follows is what the RTL has to do to make it buildable, plus
two places where it collides with decisions already taken.

**Three tiers, strongest first:**

1. **Measured on the real process at bigger sizes.** Sweep the RTL's own
   parameters (lane count, store depth, pins) through the same IHP flow and
   report routed area and Fmax at each point. Also answers Jane Street's own
   open question — they are considering 8×4 tiles, and this hands them the curve.
2. **Measured on real hardware at higher clocks: the Artix.** Run the engine at
   ~2× clock and decode real FRAM traffic faster. Turns "margins grow with
   frequency" from a calculation into a measurement. At ≥ 60 MHz on the bench,
   **Ethernet comes back** — the clock-grid exclusion reinstates at any multiple
   of 20 MHz.
3. **Routed at thinner nodes, predictive.** The same RTL through OpenROAD at
   Nangate45/FreePDK45 and ASAP7, then each node's **measured** Fmax fed back
   into the pyRTA gate at that clock.

⛔ **Both standing caveats hold.** Predictive is not fabricable and gets labelled
predictive like everything else in the ledger. And **none of it means anything
until the engine exists** — scaling a load path proves nothing.

---

## The one thing to do now: the Part 1 parameter contract

Checked by `model/part1_param_contract.py`, which is **red today and expected to
be**. Every quantity a sweep would vary is a parameter:

| parameter | varies | the sweep that needs it |
|---|---|---|
| `N_LANES` | lanes scheduled | the lane-count curve; condition 1.6o |
| `AW` | store depth, `2**AW` words | store-depth curve (already a parameter) |
| `N_PINS` | protocol pin-group width | 8×4 tiles may mean more pins |
| `TS_W` | timestamp / global counter | 1.5 derived a floor of 9 and ships 16 — the sweep is what shows the 7 bits are spare |
| `DLY_W` | program delay field | F1's fit needed 10; a different store moves the trade |
| `D_W` | `D_sched` field | scales with the deadline spread, which scales with the lane set |
| `MEM_TYPE` | `"sram"` \| `"flops"` | ⭐ **the portability parameter** |

A literal where a parameter belongs costs a **refactor per scaling point**; a
parameter costs a **run**. That is why it is a Part-1 line and not a later
clean-up.

The gate also enforces two properties beyond the parameter list:

- **No protocol constant anywhere in the engine** — the 11 numbers from the lane
  table (434, 414, 216, 213, 23, 18, 15, 80, 45, 125, 4140) belong in the loaded
  program. A protocol constant in the engine is the waveform-player failure in
  source form. ⚠ Weak evidence today, said plainly: the engine does not exist, so
  the scan has almost nothing to find. A zero-hit search proves the string
  absent, not the property held.
- **No PDK cells in RTL.** Today's source is generic Verilog, so this is a
  property to **keep**, not to gain — which is exactly when a check earns its
  place, because nothing would notice it being lost.

⛔ This gate is **not** in `run_a2.py`'s list. Like F2's netlist check and
`a4_precondition.py`, it is a standalone acceptance test that is *supposed* to be
red until Part 1 lands. Putting it in the suite would red the suite; leaving it
out of the record would hide it.

---

## Coupling 1 — the SRAM ruling and the 7 nm claim collide

**`RM_IHPSG13_1P_*` does not exist in Nangate45 or ASAP7.** If the program store
is written as a hard macro instantiation, **tier 3 cannot be built** — not
"would be awkward", cannot.

`MEM_TYPE` is what keeps both alive:

| value | for |
|---|---|
| `"sram"` | the IHP macro, for the real shuttle |
| `"flops"` | a behavioural array, hardenable at **any** node |

⛔ **So the flop store is not deleted when SRAM wins.** It becomes the portable
fallback the 45 nm and 7 nm numbers are measured on.

⚠ **And the two must not be quoted as one configuration.** A flop store at 7 nm
measures the *engine's* Fmax, not the shipped SRAM design's. The ledger entry has
to say which — otherwise the strongest-looking number in the pitch is the one an
expert dismantles first.

### Reference for `"sram"` in v2 and later: the IHP SRAM macro walkthrough

<https://kdp1965.github.io/ihp-um-janestreet-prism/ihp_sram_macro.html>
(source repo `kdp1965/ihp-um-janestreet-prism`, dated 2026-09-29).

This is a **public integration walkthrough** that anyone may follow. It is not a
competing entry that we would be borrowing from. Nate noted it on 2026-10-10 for
v2 and later. v1 (`sub-v1`) ships the flop store, and nothing in this section
changes v1.

What the walkthrough covers, as summarised from the page (not yet reproduced here):

- **PDK:** `ihp-sg13cmos5l`, IHP-Open-PDK commit `2bbec755`. This is the same
  commit our C1 canary uses, so there is no PDK bump.
- **Macro:** `RM_IHPSG13_1P_512x32_c2_bm_bist`, single port, 512 × 32, with
  bit/byte mask and BIST. The PDK also has single-port macros from 64×16 to
  8192×32 and dual-port up to 1024×32.
- **Read latency:** one cycle. The store-read path would have to absorb this, and
  A2/W would have to be re-derived.
- **RTL:** tie `A_DLY` to 1 and disable BIST. Synthesis gets a
  `(* blackbox *)` stub. Simulation uses the PDK behavioural model with
  `-DFUNCTIONAL`.
- **LibreLane `MACROS` block:** GDS, LEF, CDL, and three lib corners, plus
  placement and orientation. `PDN_MACRO_CONNECTIONS` entries are needed for
  `VDD!` and `VDDARRAY!`.
- **PDN:** Metal4 stripes, pitch 44.96 µm, spacing 3.52 µm, width 2.1 µm,
  offset 6.15 µm, aligned to the macro columns.
- **Signoff:** Magic DRC is off and KLayout runs with the CMOS5L deck. Precheck
  whitelists GDS layers 25/0 and 16/0.
- **Area:** the walkthrough's tile is 8×4 (1.22 mm²), and one 512×32 macro takes
  about 6.5% of it.
- **Licence:** the page says IHP's behavioural models are Apache-2.0. The
  walkthrough repo's own licence is **not yet checked**; check it before copying
  any of its files.

⛔ This reference does not dissolve Coupling 1. The `"sram"` build is still
IHP-only, and the flop store is still what tiers 2 and 3 measure.

---

## Coupling 2 — tier 3 feeds the proof, so the proof's inputs move with it

Tier 3's output is "at 7 nm these protocols become feasible with this margin",
produced by feeding a measured Fmax into the pyRTA gate. That is the right shape,
and it moves **more than the clock**:

- every lane's `T_i` is *cycles per bit*, so it scales with Fmax;
- `D_tol` for the **source** lanes scales the same way (they are protocol
  tolerances in time, converted to cycles);
- but the **reactive** budgets do **not** scale cleanly: `L_sync` is 3 *cycles*
  and stays 3 cycles, so in *time* it shrinks — which makes reactive lanes get
  **better** faster than source lanes;
- and `C_i` stays in cycles, which is why a higher clock buys margin at all.

⭐ So the re-derivation is a genuine recomputation per node, not a multiply. The
lane table has to be rebuilt at each Fmax and re-checked by pyRTA — which the
A1 digest will catch if anyone quotes a margin from the wrong one.

⛔ **And the Ethernet reinstatement is a clock-grid fact, not an Fmax fact.** It
returns at multiples of **20 MHz** (so the Manchester mid-bit lands on a grid
edge), not at "fast enough". A 7 nm run at 900 MHz does not reinstate Ethernet
unless 900 is a multiple of 20 — it is, but the *reason* is divisibility, and
quoting speed as the cause would be wrong in a way an expert would catch
immediately.

---

## Order

Part 1 RTL (parametric from the first line, passing F2 face 3 and this contract)
→ Phase 2 measure `C`/`J` → **then** tiers 1–3, in that order of strength.
