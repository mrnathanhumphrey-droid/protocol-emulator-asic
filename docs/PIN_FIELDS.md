# Pin fields — which pin each path reads (ruling PN2)

A lane names pins in two places: its **header** (`pin` = the data pin,
`clkpin` = the clock) and every **action** (`a_pin`). For I2C the two agree, as
do most corpus lanes. For an SPI master they do not: the header names MOSI, and
the receive action names MISO. Silicon fix #3a was a path that read the
header's pin where it meant the action's. Every clocked receive ever tested had
action pin == header pin, so the defect could not show. This table records,
for every path that takes a pin, which field it uses and why.

## RTL (`src/pe_engine.v`)

| path | pin used | correct? |
| --- | --- | --- |
| SHIFT data drive (clocked and unclocked) | `a_pin` | ✅ |
| clock drive (clocked SHIFT / SHIFTIN, LOW / HIGH / COLL) | `l_clkpin` | ✅ the clock is a lane property |
| unclocked SHIFTIN / READBIT sample | `a_pin` | ✅ |
| ARM: the pin armed on | `a_pin` → `l_armpin` | ✅ |
| clocked SHIFTIN data release | `a_pin` | ✅ |
| **clocked SHIFTIN sample** (`ck_rpin`) | was `l_pin` → now the head slot's action pin | ⛔ **silicon fix #3a**; `M_CKRX_HEADER_PIN` keeps the old form |
| clocked capture instant, push-pull | was `pin_rise[l_clkpin]` → now the engine's own rise (`ppc` slot) | ⛔ **silicon fix #3b**: `uo_out` has no input path; `M_CKRX_PP_OBSERVED` keeps the old form |
| clocked capture instant, open-drain | `pin_rise[l_clkpin]` (observed: a stretching peer decides it) | ✅ unchanged |
| SDA hold pipeline | `l_pin`, used only when `a_pin == l_pin` | ✅ guarded: the hold exists for I2C, where they agree |
| 1.6× refusal (clock pin == data pin) | `a_pin == l_clkpin` | ✅ |

`ck_rpin` reads the head slot `l_act[hix[gi]]`, so it adds no flops. It is
sound by A1: a clocked action holds its dispatch, so the head slot is the
action in progress for as long as the lane waits on its clock.

## Assembler (`model/pe_asm.py`)

| check | pin used | correct? |
| --- | --- | --- |
| `check_receive_pin` | the action's pin | ✅ |
| **`check_shift_clock_alias`** | was the header pin → now `op == OP_SHIFT and pin == clkpin` on the action's pin | ⛔ same-hand disagreement: it agreed with the RTL bug. Must-fires `_demo_action_alias` (header 8/9, SHIFT on 9: refused) and `_demo_header_alias_only` (header 9/9, SHIFT on 8: accepted) |
| `check_i2c_order` / `order_for` | lane-level (START/STOP present) | ✅ no pin |

## Golden model (`model/clocked_phase.py`)

No pin concept: it models phases, bit counts and load points. It cannot see a
pin-source defect, which is why the bench layers below exist.

## Bench layers (`test/clocked_conform.vh`)

| layer | pin used | correct? |
| --- | --- | --- |
| **V2** (wire == pushed bytes) | was the header pin → now `a_pin`, latched at the LOW phase | ⛔ same-hand disagreement, fixed; CI5 must-fire with action pin != header pin (`run_cktx` pindiv) |
| **V-RX** (new): RX frames == the bits on the action's pin | `a_pin` at the clocked HIGH writeback; unclocked receives at their writeback | ✅ must-fire `M_CKRX_HEADER_PIN` and `M_CKRX_PP_OBSERVED` on `corpus_spim` |

## Coverage of the distinction (PN4)

`model/gate_pin_matrix.py` (CI) requires every pin-taking class to run in some
bench with action pin != header pin (and != clock):

- LEVEL, START, STOP;
- SHIFT, clocked and unclocked;
- SHIFTIN: clocked open-drain, clocked push-pull, unclocked;
- READBIT, ARM.

`run_cktx.pindiv_image()` supplies the classes that no swept image covers.
