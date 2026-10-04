# The cocotb suite, rewritten — and two defects it measured

Wilson's ruling moved this up, ahead of sigrok and the timing envelope, on the
grounds that **a permanently red job trains everyone to ignore CI**. The `test`
workflow had been red for six runs on a superseded load path.

## Result

**7 of 7 pass**, `results.xml` contains **0 `failure` elements**, so CI's
`! grep failure results.xml` is satisfied. Two of the seven are `expect_fail`
arms recording measured defects.

| test | establishes |
| --- | --- |
| `test_uio_released_during_prog` | every `uio` is an input throughout load mode (kept unchanged — the one test of the five that still passed) |
| `test_protocol_outputs_idle_high_in_load` | `uo_out[3:0]` held at `1111` in load mode; readback does not go out on the protocol pins |
| `test_serial_readback_walks_the_image` | the image is observable at the pins over the 3-pin serial host view, in order, status framed in |
| `test_readback_reaches_byte_zero` | **expect_fail** — program byte 0 is unreachable through readback |
| `test_open_drain_data_pin` | F5: open-drain is expressible through `uio_oe`, on a real I²C program, with the non-vacuity arm |
| `test_open_drain_clock_pin_is_released` | **expect_fail** — an open-drain lane's clock pin is driven push-pull |
| `test_engine_runs_at_the_pins` | the five-lane program moves both banks, no pin left unknown |

## What was retired, and why it was red

Four of the five old tests asserted a load path that no longer exists:

- **`uo_out` no longer echoes the load pointer.** The pins are now 4 push-pull
  protocol outputs, a 3-pin serial host view and a spare, so the pointer tests
  read `0x6F` and asserted `111 == 3`.
- **There is no "read walk"** putting raw image bytes on `uo_out` one per 256
  clocks. Readback moved to the serial trio — the fix for the constructed-image
  FRAM write.
- **A four-raw-byte "image" is not an I²C program.** With headers, action words
  and a scheduler, `0b00, 0b01, 0b10, 0b11` cannot express open-drain, the
  enable never asserted, and the F5 must-fire fired correctly on a test that had
  become unable to measure its own subject.

The retired tests' *properties* survive: the pointer and readback properties are
ported onto the serial path, and open-drain is now shown on `corpus_i2c.hex` —
the same program the two-simulator trace corpus uses, so this suite and that
comparison speak about the same programs.

## Reading the serial host view at the pins

`uo_out[4]` = data, `[5]` = strobe, `[6]` = valid. A frame is 9 strobed bits:
8 payload bits LSB-first then a marker (1 = status, 0 = payload), and payload
frames alternate with a sticky status frame so liveness is in the stream even
when no payload moves.

Two things the decoder had to get right:

- **Framed on the `valid` edge, not a fixed stride.** Chunking strobed bits into
  groups of nine assumes the harvest began exactly at a frame boundary; it did
  not, and the whole stream decoded one bit out — image bytes appeared labelled
  as status frames. `ser_v` is high only while a frame shifts, so its rising
  edge *is* the boundary, which is also how a real host would frame a
  data/strobe/valid interface.
- **X-tolerant reads.** `int(dut.uo_out.value)` *raises* on a port carrying X and
  killed the first decoder outright. The suite reads the binstr and decides
  explicitly what an unknown means — necessary anyway at gate level.

**Readback has to be rewound to be read deterministically**, because it streams
*concurrently with loading*: by the time the last byte is written the walk is
already past it. `rb_ptr` is cleared only by `rst_n` while the program store is
deliberately unreset, so a reset rewinds the walk and keeps the image.

## Defect 1 — program byte 0 is unobservable through readback

Measured. Loading `[0xAA, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]` and
harvesting after a rewind yields payload frames `0x33(stale), 0x22, 0x33, 0x44,
0x55, 0x66, 0x77, 0x88` — **`0xAA` never appears**, and the walk runs off the end
into X one byte early.

The cause, in `src/project.v`'s load-mode readback branch: the frame is queued
from `s_rdata` while `rb_ptr` is incremented and `rb_re` asserted **in the same
cycle**, and the store's `raddr` is `rb_ptr` — so the read uses the
already-incremented pointer, address 0 is never requested, and the first frame
carries `s_rdata` from before any read.

⚠ **The reset allowlist's reason for `s_rdata` is incomplete.**
`gate_reset_audit.py` allows it unreset on the argument that "H_CAP only runs
after H_REQ". The load-mode readback path *also* consumes `s_rdata`, and there
that ordering does not hold — which is why the first frame is X on a cold part.

**Why it matters:** byte 0 is the first byte of lane 0's header — its `pin` and
`clkpin` fields — so the one byte a host cannot verify is part of the descriptor
deciding which physical pin lane 0 drives. For a feature whose stated purpose is
proving the image loaded, that is the wrong byte to lose.

**Proposed fix (offered, not applied):** latch the address to be read separately
from the walk — `rb_addr <= rb_ptr` alongside `rb_ptr <= rb_ptr + 1` — and point
the store at `rb_addr`, so the read uses the pre-increment pointer.

## Defect 2 — an open-drain lane's clock pin is driven push-pull

Measured on `corpus_i2c.hex`, whose lane declares open-drain with SDA as data
and SCL as clock: **`uio_oe=00000110 uio_out=11111011`** — SCL has its enable
asserted *and* its output high, a hard 1 on a line that must only ever be pulled
low. SDA is correct.

The cause, in `src/pe_engine.v`'s `OP_SHIFT`: the data pin gets an
open-drain-aware `if (l_mode[cur]) … else …`, and then the clock pin is driven
with no such branch — `pin_out[l_clkpin[cur]] <= a_lvl` and
`pin_oe[l_clkpin[cur]] <= 1` unconditionally. `OP_LEVEL`, `OP_START` and
`OP_STOP` all honour `l_mode` for the pin they name; the clock pin never does.

**Why it matters, and it is not tidiness:**

- **Clock stretching becomes impossible.** A peer stretches by holding SCL *low*;
  against a push-pull driver that is a short, not a stretch. `test/fram_i2c.v`
  exports `scl_oe` as a pull-low stretch enable for exactly that purpose, and
  `docs/A2_GREEN_RESULTS.md` reasons about the stretch duration — so the peer
  model and the schedulability argument both assume a releasable SCL the engine
  cannot provide.
- **Multi-master arbitration and bus recovery** need every I²C line releasable.

**Proposed fix (offered, not applied — a protocol ruling):** give the clock pin
the same `l_mode` branch the data pin has. The comment's stated reason for
driving the clock there — "so data and clock never need P-ORDER per bit" — is
about *ordering*, and holds under either drive style.

## Why `expect_fail`, and the mechanism is priced

A defect recorded only in prose does not tell you when it is fixed. These two
arms are `expect_fail`, so CI is honest rather than permanently red, and each
**announces its own obsolescence**: when the defect is fixed the test passes
unexpectedly, CI goes red, and whoever fixed it is told to delete the marker.

⭐ **That claim is measured, not asserted.** A mechanism only ever seen to pass
has unknown strength, so an `expect_fail` test that trivially succeeds was run:
cocotb reported "passed but we expected a failure" and `results.xml` gained a
`<failure>` element. The self-announcing property holds.

## The local runner was broken, and held a stale third copy

`run_local.py` passed only `project.v` and `tb.v` to iverilog, so after the
engine/store split it could not even elaborate — "3 error(s) during elaboration:
pe_engine referenced 1 times, pe_store referenced 1 times" — while its own
comment claimed "SAME SOURCES AND SAME TOPLEVEL AS CI'S MAKEFILE". It now
**parses `PROJECT_SOURCES` out of `test/Makefile`**, which makes that comment
true by construction rather than by vigilance.

`PE_TEST_MODULE` was added so a throwaway diagnostic can run through the same
build and toplevel as the suite; a diagnostic elaborated differently from the
suite measures a different thing.

**And a new CI step asserts `info.yaml` and `test/Makefile` name the same
files.** The Makefile builds what CI *tests*; `info.yaml` lists what the flow
*hardens*. A divergence means the tests pass on one design and the chip is built
from another, and neither tool would say so. The check's must-fire was run: given
a list with one file missing it reports "CI would test one design and the flow
harden another".

## Gate level

`gl_test` runs the TinyTapeout `gl_test@ihp-cmos5l` action, which runs this same
`test.py` with `GATES=yes`, so the suite runs at gate level with no further
wiring. Every check is at the pins — nothing reads `dut.mem` or any internal
signal — which is what makes that possible.

⚠ **Not verified locally.** There is no netlist or PDK on this machine, so the
gate-level outcome is unconfirmed until the next harden completes. The arm most
likely to behave differently there is `test_engine_runs_at_the_pins`, which
requires **no X on `uo_out`/`uio_oe`** across its window; that is a property
worth asserting strictly, and if gate level violates it that is information
rather than a test to loosen.

## What this does NOT establish

- **Liveness and non-vacuity, not protocol correctness.** What the waveforms
  *mean* is settled by the two-simulator corpus comparison and the A2 margin
  gates. `test_engine_runs_at_the_pins` says the engine still does something at
  the pins, in the one place that also runs at gate level.
- **No timing claim.** Only the real harden produces slack.
- **The two defects are recorded, not fixed.** Both need a ruling, and both
  proposed fixes are one register / one branch.

## Reproduce

```bash
python test/run_local.py                      # the suite, RTL
PE_TEST_MODULE=<mod> python test/run_local.py # a diagnostic through the same build
python -c "import sys; sys.path.insert(0,'test'); import run_local; \
  run_local.assert_info_yaml_agrees(run_local.project_sources())"
```

## Suite state at this commit

`run_a2` **30 of 30** (digest `b4e51034e283`) · `price_gates` **13 of 13 red** ·
`run_mutants` **4 of 4** · `tb_smoke` PASS · `tb_edge` **5 of 5** ·
`gate_reverse_trace` 8 of 8 · `gate_reset_audit` PASSED ·
`gate_corpus_trace` **5 of 6, 1 open, 0 failed** · cocotb **7 of 7**.

`yosys_check.sh` not re-run: nothing under `src/` changed in this round.
