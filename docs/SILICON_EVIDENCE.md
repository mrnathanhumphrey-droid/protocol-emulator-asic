# Silicon evidence — the post-PnR numbers, copied out of their artefact

Every figure below is copied from the CI artefact named beside it, not recalled.
Produced by `model/a4_precondition.py` run against the downloaded artefact.

**Source:** commit `bba3bae`, CI run **`37058686306`**, artefacts `tt_submission`
and `GDS_logs`. Re-verified unchanged on commit `46f3468`, run `37074059304`.

**Reproduce:**
```
gh run download 37058686306 -n tt_submission -D <dir>
gh run download 37058686306 -n GDS_logs      -D <dir>/logs
python model/a4_precondition.py \
    <dir>/tt_submission/tt_um_protocol_emulator.v \
    <dir>/logs/runs/wokwi/55-openroad-stapostpnr
```

---

## ⛔⛔ Read this before quoting any timing number

**`timing__setup__wns = 0` is the same value on this design and on a 53-cell
combinational stub.** OpenLane's WNS metric is `min(0, worst_slack)`, so `0`
means "no violation" — and an *empty path set* also has no violation. For weeks
this project read `WNS 0.0` at three corners as "closes at 50 MHz" when the
design under test had **zero flip-flops** and the number meant **no path**.

The figures that distinguish the two cases are the **worst slack** in
`ws.max.rpt` and the **path count** in `max.rpt`. Those are what this file
records, and what `model/a4_precondition.py` asserts.

## A4 precondition gate — PASSED

| # | precondition | result |
|---|---|---|
| P1 | netlist contains flip-flops | **535** |
| P2 | numeric worst slack present (not an empty set) | all 3 corners |
| P3 | ≥1 reported path **ends at a flip-flop** | **535 of 568** |
| P4 | no path with slack < −0.01 ns (zero violations) | all 3 corners |
| P5 | `check_setup` silent — no unconstrained endpoint, no missing input delay, no loops, no generated-clock problems | all 3 corners |

P3 is the one that would have caught the stub: a design can contain flops and
still report only pad-to-pad combinational paths if the clock is not constrained.

## Timing, `CLOCK_PERIOD: 20` (50 MHz)

| corner | worst setup slack | worst hold slack | paths | → flop |
|---|---|---|---|---|
| `nom_slow_1p08V_125C` | **+1.5612 ns** | **+0.6154 ns** | 568 | 535 |
| `nom_typ_1p20V_25C` | +5.4410 ns | +0.2931 ns | 568 | 535 |
| `nom_fast_1p32V_m40C` | +7.6599 ns | +0.1120 ns | 568 | 535 |

Setup/hold TNS 0.0 at every corner. The slow-corner critical path is a
**combinational feedthrough** `ui_in[7] → uo_out[7]` through the `mem[rd_ptr]`
readback mux — *not* a register path. Worst flop endpoint is **+9.18 ns**.

## ⚠ Scope of the A4 claim — three caveats that travel with it

1. **`PNR_SDC_FILE: null`.** PnR used the **generic fallback SDC**, not a
   design-specific one. The clock constraint was applied (paths are reported
   "clocked by clk" against a 20 ns period), but there are no design input/output
   delays and no declared false paths. **The defensible claim is "closes at
   50 MHz under the fallback SDC."** A design SDC is rung 4 Part 5's job and
   retires this caveat.
2. **Lint violations remain**, and they are not timing: at the slow corner **20
   `max_slew`** violators (worst −0.233 ns on a 2.507 ns limit, ~9% over) and
   **30 `max_fanout`** violators, *all* on clock-tree leaf buffers
   (`clkbuf_leaf_*_clk/X`, 22 loads against a limit of 10 → slack −12). The
   fanout one is a CTS `MAX_FANOUT_CONSTRAINT` setting. 30 violators at the fast
   and typ corners.
3. **This is not "timing closes with real logic" in the sense a reader will
   assume.** See the area section: 512 of the 535 flops are the program store.

## Area and composition

| metric | value |
|---|---|
| die area | 916,214 µm² |
| core area | 902,417 µm² |
| **instance utilisation** | **6.28%** |
| total instances | 71,107 |
| logic cells | **2,946** |
| filler / decap / tap | 68,161 |
| total power | 2.09 mW |

**Cell inventory (top of the list):**

| count | cell | note |
|---|---|---|
| 65,875 | `decap_8` | filler |
| 875 / 764 | `fill_1` / `fill_2` | filler |
| 647 | `decap_4` | filler |
| **555** | `dlygate4sd3_1` | **hold-fix delay buffers — more than there are flops** |
| **535** | `dfrbpq_1` | **flip-flops** |
| 515 | `mux2_1` | the 64-entry readback mux tree |
| 512 | `tiehi` | |
| 250 | `a22oi_1` | |

⛔ **Flop breakdown, because "535 flops" overstates the logic:** `mem` 512 +
`ptr` 6 + `rd_ptr` 6 + `div` 8 + `wr_sync` 3 = 535. **512 of them are the 64-byte
program store** — a register file, not datapath. And the 555 delay cells are what
bought the +0.6154 ns of hold margin.

## Functional evidence

**Gate-level simulation, run `37058686306`, job `111024958483`, 1m02s:**

```
test.test_pointer_echo_and_autoincrement   PASS
test.test_ptr_rst                          PASS
test.test_load_then_readback               PASS
test.test_uio_released_during_prog         PASS
test.test_f5_open_drain                    PASS
** TESTS=5 PASS=5 FAIL=0 SKIP=0 **
```

Elaborated against `gate_level_netlist.v` with `-DGL_TEST -DFUNCTIONAL`, and
**`src/project.v` is absent from the source list** — the subject is the netlist.

**Job status, both runs:** `gds` ✅ `gl_test` ✅ `precheck` ✅ `docs` ✅ `test` ✅.
`viewer` ❌ — it deploys the GDS preview to GitHub Pages, deliberately disabled
while the repo is private. **Expected red, not a defect.**

## What this evidence does *not* support

- It does not show a protocol being emulated. `src/project.v` is the program-load
  path and the pin abstraction; the engine is rung 4. Its own header says so.
- `uio_out` is tied to `8'h00`, so the design **cannot drive a logic 1 on a
  bidirectional pin** — UART TX, SPI SCLK and MOSI are push-pull and unsupported
  until the per-pin drive-mode bit lands.
- It says nothing about whether the RTL implements the A2-analysed scheduler;
  that is the refinement obligation in `docs/RUNG4_CONVENTION.md`.
