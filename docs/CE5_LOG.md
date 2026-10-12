# CE5 — 1-Wire (DS18B20) on the frozen RTL: expressiveness log

CE5 asks whether the **frozen** chip (`src/` unchanged since the freeze SHA,
`model/gate_ce5_freeze.py`) can run a protocol it was never designed for with
a pe_asm program alone. The answer is yes, with the workarounds below. Each
entry is a place the ISA or pe_asm could **not** say what the protocol
needed: the workaround used, and the RTL change that would remove it.
**No RTL change was made.** This is flexibility evidence, stated with its
costs.

**Write-up framing (Wilson).** 1-Wire **slot timing is generated on-chip**:
every falling edge, release and sample instant is placed by the engine to the
cycle. The **bit stream is host-supplied**, because the ISA has no loop count
or branch (OW1): the host chooses which slot shape runs next, the split real
1-Wire bus masters (DS2480B / DS2482) make. Say both halves together; neither
is the whole claim.

* Program: `model/pe_proto.py` (`OneWire`), images by `test/onewire.py`
  (`test/onewire_image.hex`, `test/onewire_fpga_image.hex`).
* Gate: `test/run_onewire.py` (bench `test/tb_onewire.v`, peer
  `test/ds18b20_model.v`).
* Timing source: Analog Devices (Maxim) **DS18B20 datasheet 19-7487; Rev 6;
  7/19** — "AC Electrical Characteristics" (p. 3), "1-Wire Signaling"
  (pp. 15–16). Read from analog.com, **not vendored** (`refs/` is
  gitignored).
* The peer model is **same-hand** (written alongside the program). The real
  DS18B20 (on order) is the foreign witness.
* **Dallas CRC-8 is checked host-side** in sub-v1 (`run_onewire.crc8`, itself
  checked against Maxim AN27's worked example `02 1C B8 01 00 00 00 → A2`).
  On-chip CRC belongs to the reach branch.

## Datasheet numbers used (quoted)

| symbol | datasheet (Table: AC Electrical Characteristics) | where it binds |
| --- | --- | --- |
| tSLOT | Time Slot 60 min, 120 max µs | fall → next fall ≥ tSLOT + tREC = 61 µs |
| tREC | Recovery Time 1 µs min | release → next fall |
| tLOW0 | Write 0 Low Time 60 min, 120 max µs | write-0 low (program: 70 µs) |
| tLOW1 | Write 1 Low Time 1 min, 15 max µs | write-1 low (program: 3 µs) |
| tRDV | Read Data Valid 15 µs | master sample ≤ 15 µs after the fall (program: 12 µs) |
| tRSTH | Reset Time High 480 µs min | reset release → next fall |
| tRSTL | Reset Time Low 480 µs min | reset low (program: ≥ 584 µs) |
| tPDHIGH | Presence-Detect High 15 min, 60 max µs | presence guaranteed low from 60 µs … |
| tPDLOW | Presence-Detect Low 60 min, 240 max µs | … to 15 + 60 = 75 µs after release (program samples at ~67 µs) |
| tCONV | 750 ms max at 12 bits (Table 2) | not waited: polled (VDD mode) |

Quoted text relied on: *"The DS18B20 samples the 1-Wire bus during a window
that lasts from 15µs to 60µs after the master initiates the write time
slot."* *"Output data from the DS18B20 is valid for 15µs after the falling
edge that initiated the read time slot. Therefore, the master must release
the bus and then sample the bus state within 15µs from the start of the
slot."* *"If the DS18B20 is powered by an external supply, the master can
issue read time slots after the Convert T command and the DS18B20 will
respond by transmitting a 0 while the temperature conversion is in progress
and a 1 when the conversion is done."* *"Infinite recovery time can occur
between bits so long as the 1-Wire bus is in the inactive (high) state during
the recovery period"* — so tSLOT's **maximum** is not a wire-checkable bound
on its own; tLOW0 ≤ 120 µs is checked.

## The program (one paragraph)

The ISA cannot hold the transaction (OW1), so the program is a **slot
engine**: one loop iteration (128 µs) is one 1-Wire symbol, chosen by four
TX-queue bits — `W1/READ` (low 3 µs, sample at 12 µs), `W0` (low 70 µs),
`RST` (low the whole iteration; chained ≥ 480 µs), `RSTEND` (low until 72 µs,
then released), `IDLE` (released; its sample after `RSTEND` is the presence
sample, 68 µs after release). The host turns the transaction (reset, 33h,
read 8; reset, CCh 44h, poll; reset, CCh BEh, read 9) into symbols
(`OneWire.feed`), the split real 1-Wire masters make (DS2480B/DS2482: the
host issues reset / write-bit / read-bit, the line driver owns the timing).
Every timing-critical edge and sample is on-chip and exact.

**Certification status (WF2 round 2, 2026-10-12).** Until today pe_asm's 1.6a
had **no response bound** for this program and accepted it through a skip
path. Lane 0 chains hold-loading SHIFTs, which W1's model refused outright.
That skip is closed, and a lane with no bound is now refused. W1's model is
extended to chained hold loads by induction. A chained loading job is never
W1-delayed iff `HS + 2 + (r − C)` is at most the spacing after it, and that
is checked, never assumed. Lane 0 is now bounded at **r = 16** (pyRTA =
ours). The measured worst response is **15** on all seven 1-Wire arms, and
no job was ever released into an earlier job's hold.
⭐ **Certified by pe_asm under the back-to-back hold extension (accepted 12
Oct).** The proof, its constants, its edge must-fire (gap 33 = window +
lateness exactly accepted, 32 refused) and these measurements are in
`docs/SPEC_V4_CLOCKED_HIGH_PHASE.md`, §W8.

## Wiring (TT and the Puzhi PA100T-EDU image)

* `test/onewire_image.hex` (TT) and `test/onewire_fpga_image.hex` (PA100T,
  the same engine with a 2 µs read-slot low and the sample at 13 µs — Figure
  18's advice for a real pull-up's rise time) use the same pins:
  * `uio[2]` — **DQ**, open-drain (the lane's data pin);
  * `uio[3]` — **sense**, an input, wired to the **same DQ net** (OW2);
  * `uio[4]` — the lane's clock pin, **left unconnected** (OW3; the engine
    pulls it low).
* **4.7 kΩ pull-up from DQ to the DS18B20's VDD (3.3 V)**; the part
  VDD-powered (not parasite), GND common. Bench: `run_onewire`'s `fpga` arm
  runs that image with a 2 µs rise.
* The chip runs unchanged inside the main branch's `fpga/rtl/pe_fpga_core.v`
  wrapper (not on this branch); map those three `uio` bits to header pins.
* The host must stream the symbols (`OneWire.feed`) and read the pushed
  bytes from the serial view; Dallas CRC-8 is the host's.

## Log

### OW1 — no counter, compare or branch: the transaction cannot be stored

* **Need.** READ ROM reads 64 slots, READ SCRATCHPAD 72; Convert T needs
  "repeat read slots until a 1".
* **Could not.** A lane's only control flow is REARM to its base (forever)
  or a chaining REARM (park forever). Unrolled, 64 read slots are 64 × 3 =
  **192 actions**; the store holds (256 − 30) / 3 = **75**.
* **Workaround.** The slot engine above (9 actions, 27 bytes); the host
  sequences symbols and decides the poll's end from the pushed bytes.
  Measured: Convert T polled in 4 groups of 8 slots (`00 00 F0 FF`), one group
  past completion because the host decides with queue latency (OW7).
* **RTL change that removes it.** A loop count on REARM (loop N times, then
  fall through), or a branch-on-last-RX-bit. Either lets the ROM read be
  `8 × (read slot)` in place, and the poll be on-chip.

### OW2 — an unclocked SHIFTIN releases the pin it samples

* **Need.** The sample point is fixed by the program (12 µs) but, with the
  symbol chosen by data, the program does not know whether the current slot
  is a read or a write-0 — and a write-0 must stay low for 60 µs.
* **Could not.** `OP_SHIFTIN`/`OP_READBIT` write `pin_oe[a_pin] <= 0` on
  every dispatch (`pe_engine.v`, the `OP_SHIFTIN, OP_READBIT` drive arm). On
  DQ itself, the 12 µs sample would end every write-0 at 12 µs.
* **Workaround.** Sample a **second pin** wired to the same DQ net: DQ on
  `uio[2]` (open-drain), sense on `uio[3]` (input). One extra pad.
* **RTL change.** A sample-only receive (no `pin_oe` write) — e.g. SHIFTIN
  with `level = 1` on a lane without a real clock, which today means nothing.

### OW3 — an open-drain lane must name a real `uio` clock pin (1.6s)

* **Need.** 1-Wire has no clock.
* **Could not.** Silicon refuses an open-drain header whose clock pin is not
  `uio` (`pe_engine.v`, the 1.6s block at header load: CONFIG_ERR, engine-wide
  halt). `PIN_NONE` is a "no clock" only on a push-pull lane.
  ⛔ **Found the hard way, and it was a toolchain defect:** pe_asm accepted the
  `PIN_NONE`-clock image and the chip ran **nothing** (CONFIG_ERR, 0
  writebacks). pe_asm now refuses it (`check_open_drain_bank`, with
  must-fires in `pe_asm.main`).
* **Workaround.** A third, **unconnected** `uio` pin as the lane's clock
  (`uio[4]`). Every unclocked SHIFT (level 0, real clock) pulls it low, and
  routes the DQ move through the SDA hold pipeline: every DQ edge lands
  `SDA_HOLD` (15) cycles after its dispatch, and the lane is ineligible for
  19 cycles after it (W1). Both are constant and far inside the slot margins
  (measured write-1 low 3.26–3.50 µs for a programmed 3.0).
* **RTL change.** Let 1.6s check the clock pin only when it is a real pin
  (`clk_real` already guards every clock write).
* **Sweep (Wilson's follow-up): the 1.6s check over EVERY tracked image.**
  All 29 tracked `.hex` (`git ls-files '*.hex'` at 55b0600: 28 under
  `test/`, plus `fpga/images/uart_rx_434.hex`), every one of the 5 headers
  the chip loads (active and parked), through `pe_asm.check_open_drain_bank`
  and, independently, the RTL rule restated (mode 0 with `pin >= 8` or
  `clkpin >= 8`). The SP2/P1 count range was swept in the same pass.

  | result | images |
  | --- | --- |
  | 1.6s **fails** | `test/cfgerr_image.hex` (lane 0: open-drain on pin 8) — **declared**: it is the 1.6s refusal image (`gate_degenerate_fields.DELIBERATE`, R_OD_ON_UO) |
  | count range fails | `test/ckdegen_image.hex` (lane 0 SHIFTIN count 0), `test/ckdegen2_image.hex` (lane 0 SHIFT count 15) — **declared**: the R_CKDEGEN refusal images |
  | both pass | the other 26: `uart_rx_434` (fpga), `armnone`, `ckdense`, `ckfive`, `ckheavy`, `ckhold_at`, `ckhold_over`, `ckhold_under`, `ckod`, `ckread`, `corpus_all5`, `corpus_i2c`, `corpus_spim`, `corpus_sptgt`, `corpus_uartrx`, `half`, `i2caddr`, `i2cframe`, `onewire_fpga`, `onewire`, `pinnone`, `rxfast`, `smoke`, `tx_badclk`, `tx`, `uart_rx` |

  **Finding: none.** No tracked image other than the declared refusal
  images would be refused at header load, so no other shipped image was in
  the OW3 class (accepted by the toolchain, refused by the chip). The sweep
  is a one-off report (scratch probe), not a standing gate.

### OW4 — the delay field ends at 1023 cycles (20.46 µs)

* **Need.** tLOW0 70 µs, the 56 µs tail before the next slot, tRSTL ≥ 480 µs,
  tRSTH ≥ 480 µs.
* **Could not** in one action (`DLY_W = 10`). A chaining REARM extends a
  delay only by parking forever.
* **Workaround.** No-op fillers (`OP_LEVEL` on PIN_NONE) inside the symbol
  (4 of the 9 actions are fillers or carry split delays); resets are built
  from consecutive `RST` symbols (≥ 584 µs low, ≥ 1463 µs high after).
* **RTL change.** A per-lane prescaler bit, or a wider delay field.

### OW5 — no on-chip CRC

* **Workaround.** Host-side Dallas CRC-8 (sub-v1 scope).
* **RTL change.** A CRC-8 accumulator on the RX path — reach branch.

### OW6 — the underrun level is a bus RESET

* **Fact.** On TX underrun the shift register shifts in zeros, so DQ is held
  **low** — a 1-Wire reset. The reset value of the shift register (00h) also
  makes the first two symbols of every run `RST` (counted into the first
  reset block, `OneWire.feed`). Harmless on 1-Wire, but it means the lane's
  "starved" state actively drives the bus.
* **Workaround.** The host keeps the queue fed (trailing `IDLE` bytes); the
  bench requires `underrun = 0`.
* **RTL change.** A per-lane underrun fill (e.g. 1s = release for an
  open-drain lane).
* **⭐ RTL FIX CANDIDATE (logged, NOT implemented — src/ is frozen):
  a configurable idle level on underrun.** A per-lane header bit choosing
  what an underrunning SHIFT shifts in (0 as today, or 1 = release / idle
  high). For 1-Wire the idle level is released-high, so a starved lane would
  stop driving the bus instead of resetting the part.
* **The hazard, stated (Wilson).** A TX underrun pulls DQ low, which a
  DS18B20 reads as a **reset** (≥ 480 µs low) or, shorter, as a **write-0 /
  a read slot it answers into**. The host must therefore DETECT an underrun
  before the real part goes on — and it does, as a **standing must-fire** in
  `test/run_onewire.py` (bench `+STALL_AT` / `+STALL_CYC`: the host stops
  pushing mid-READ ROM, at feed word 19):

  | arm | stall | DQ low | pushed ROM bytes | peer violations | host verdict |
  | --- | --- | --- | --- | --- | --- |
  | `underrun_reset` | 100,000 cycles | ~1.2 ms → the part **resets**, its presence pulse lands in the data | `28 A2 00 F4 FF FF FF FF` | 1 (tRSTH) | CRC-8 **red** (crc8 35) |
  | `underrun_slot` | 45,000 cycles | one 128 µs slot | `28 A2 0C 37 15 00 00 20` | **0** | CRC-8 **red** (crc8 BC) |

  Red requires BOTH the chip's underrun sticky = 1 (the stall really starved
  the lane) AND a host-side check red. ⚠ The short stall is the instructive
  one: the peer model sees **nothing wrong** — only the host's CRC catches
  it. ⛔ CRC-8 alone is not enough in general: eight `00` bytes have a valid
  Dallas CRC, and `00` is exactly what a host reads from a bus held low, so
  the host also checks the ROM family code (28h, not all-zero).
* **Which board feed can underrun (Wilson's question).** At 55b0600 the FPGA
  wrapper `fpga/rtl/pe_fpga_core.v` loads the program from a **BRAM ROM**
  through the real host interface, then holds `ui_in = {PROG 0, WR 0, PTR 0,
  00000}` for good: the TX host channel (WR edge on `ui_in[6]`, nibble on
  `ui_in[4:1]`, tag on `{ui_in[5], ui_in[0]}`) is **never driven after the
  load**. The PC's USB-UART reaches the chip only as a *protocol* pin
  (`uio[3]`, the UART-rx demo's input) and through a 1 KiB FIFO on the
  *receive* side. **So today the board has no feed path for the 1-Wire
  symbol stream at all.** The two ways to add one differ exactly on this
  hazard:
  * **BRAM feed** (a second ROM played into the host channel by the glue):
    a push costs ~12 cycles against one byte per 256 µs consumed, so it
    **cannot underrun**. But the Convert-T poll is reactive (OW7): a pure
    ROM feed needs either a fixed worst-case poll count (tCONV 750 ms / 1.024
    ms per 8-slot group ≈ 733 groups) or glue that watches the pushed byte.
  * **PC feed** (USB-UART → glue → host channel): 115200 baud ≈ 11.5 kB/s
    against 3.9 kB/s needed, so bandwidth is fine — but the chip holds only
    2 queued bytes + the shift register = **768 µs** of slack, below a
    typical USB-UART latency (milliseconds; FTDI's default latency timer is
    16 ms). **It can underrun** unless the glue adds a TX FIFO (1 KiB =
    262 ms of slack) — and then the must-fire above is the detector.
  * **⭐ RULED (Wilson): the PC feed, through a glue TX FIFO.** When the board
    needs a 1-Wire feed, the glue in the FPGA wrapper gets a TX FIFO (test
    infrastructure, not chip RTL) sized for several ms of USB latency at the
    slot rate, and the chip's underrun sticky is reported to the host on
    **every** run. Not built yet: the board has no 1-Wire peer today.

### OW7 — the poll's end is decided by the host

* **Fact.** With no branch, "repeat read slots until 1" is the host's
  decision, made from pushed bytes with queue latency (2 queued bytes +
  the shift register = 3 bytes = 6 symbols in flight). The extra slots are
  harmless (the part answers 1 when done).

### OW8 — a pushed byte is fixed at 8 samples

* **Fact.** `count = 8` on the SHIFTIN pushes one byte per 8 symbols, so
  every block of the transaction must be a multiple of 8 symbols: the reset
  block is padded to 16 symbols (2.05 ms, against ~1.1 ms needed).
* **RTL change.** A per-action "push now" (or count from the host).

## SP2 findings (the protocol front-end, `model/gate_sp2_frontend.py`)

Re-expressing the shipped FRAM programs in front-end form, byte for byte,
found four pe_asm gaps (fixed in pe_asm, references unchanged):

* **P1** pe_asm refused every count outside 1..15, so a **1-bit clocked
  SHIFT** (`count = 0`: the I²C master's ACK/NACK) — and therefore the FRAM
  random read — was not expressible at all. The range is now per opcode
  (SHIFT 0..14, SHIFTIN 1..15, others 0..15), matching the chip's own
  CONFIG_ERR cases.
* **P2** an SPI FRAM lane is MSB-first with no START/STOP for `order_for` to
  see; pe_asm had no way to state the order. Header element 8 = order.
* **P3** the shipped images park idle lanes differently (pin 1 in the corpus;
  0/3/4/5 in `run_ckack`/`build_ckread`). `assemble(park_pins=...)`.
* **P4** `corpus_spim` (d = 7) is refused by pe_asm's per-program 1.6a check
  — it is an N1-declared non-admissible trace image. Emitted for identity
  with `timing_checks=False`; the refusal is expected by name, and the same
  transaction at d = 25 passes the full verdict.
* The count field of opcodes that ignore it is 8 in the corpus and 0 in
  `run_ckack`: a silicon don't-care, an image byte difference. The front-end
  takes it as a parameter.

**Wilson's rulings on P1–P4 (implemented):**

* **P1 — accepted, anchored to the RTL.** The range is no longer typed in
  pe_asm: `model/count_ranges.py` derives it from text anchors in
  `src/pe_engine.v` (at 55b0600: `BPW = 4` l.281, `a_cnt` l.1360,
  `ck_shift`/`ck_shiftin` l.1421–1422, `ck_nbits = ck_shift ? (a_cnt + 1) :
  a_cnt` l.1442–1443, `ck_degen = ck_act & (ck_nbits == 0)` l.1458,
  `ck_refuse` l.1507; the unclocked TX-load / RX-push compares l.3103 /
  l.2912). SHIFT moves `(count + 1) mod 16` bits, SHIFTIN `count`; zero bits
  is CONFIG_ERR ⇒ SHIFT 0..14, SHIFTIN 1..15, others 0..15. A missing anchor
  is a refusal. ⚠ Scope: `ck_degen` refuses *clocked* actions only; the
  unclocked forms count the same way and at 15 / 0 run a 16-bit cycle over an
  8-bit register (defined, not refused) — pe_asm refuses them too, the safe
  direction. Gate `model/gate_count_ranges.py` (must-fires: SHIFT 15 and
  SHIFTIN 0 refused; a mutated `ck_nbits` or `ck_degen` makes the derivation
  raise).
* **P2 — accepted.** Raw pe_asm keeps the documented default (`order_for`:
  LSB unless START/STOP); the SP2 byte identity shows the default reproduces
  every old image. In the **front-end** an SPI master lane must state its
  order: `pe_proto.SPI(..., order)` has no default and `pe_proto.image`
  refuses a 7-element SPI header (must-fire M3 in `gate_sp2_frontend`).
* **P3 — one rule (Wilson's follow-up).** A parked header still loads and
  sets its pin's drive class (ruling 1.5). An overlap with any active lane's
  pin (header data/clock or any action pin — the 1-Wire sense pin is an
  action pin) is allowed **iff it is release-only**, explicit or implicit
  alike, proven from RTL anchors (`model/park_class.py`, K1–K5: the class
  write takes the mode bit; no `pin_inv` write on a `uio` park pin; the park
  word, `OP_REARM`, moves no pin). So it is allowed exactly when every active
  user of the pin is open-drain; a push-pull user is refused. `corpus_i2c`'s
  implicit park on its own open-drain SCL passes under this rule.
  Must-fires (pe_asm): an explicit park on a push-pull pin and the implicit
  default under a push-pull lane are refused; explicit parks on the
  open-drain 1-Wire DQ and sense pins are accepted; with anchor K5 removed
  even the open-drain overlap is refused (unproven is red).
* **P4 — accepted only through a registry.** `model/nonadmissible.py` is the
  one file: N1's `NON_ADMISSIBLE` moved there (unchanged; `gate_admissible_
  images` reads it), plus `TIMING_EXEMPT`: `corpus_spim.hex` (and its three
  untracked `run_spifram` variants, each naming it as parent) may take
  `timing_checks=False`; `ckdense_image.hex` may take `no_rta_budget`. pe_asm
  refuses `timing_checks=False` without a registered `exempt_as`;
  `program_a2` refuses at import a `NO_RTA_BUDGET` whose membership differs
  (the measured widest gap and margin stay there) and re-checks per use;
  `gate_sp2_frontend`'s expected-refused list is derived from it.

## Part D — WS2812B (CE5b feasibility): ⛔ NOT CLAIMABLE against the official datasheet

**⛔ THE EARLIER VERDICT BELOW ("FEASIBLE") IS WITHDRAWN.** It was judged
against "commonly published" nominals, not a datasheet. Against the
manufacturer's numbers no admissible program meets the bit timing; the
measurement and the reasoning follow. No gate claims WS2812 support.

**A measured limit, recorded as a negative result (Wilson).** WS2812 is
**not claimable on sub-v1**. T0H max is 380 ns; one action delay is at least
D* = 20 cycles = 400 ns at 50 MHz. So the scheduler's own minimum delay rules
it out, and no admissible tuning fixes it. This is the concrete motivation
for the reach branch's per-lane serializers (a byte → 24 timed edges with no
dispatch per edge).

* **Why the earlier verdict said "feasible":** that measurement's loop ended
  in a **delay-0 REARM**, which pe_asm's admissibility screen could not see
  (`compute_j` and N1's `refill_dmin` took the minimum over positive delays
  only). That is the delay-0 REARM finding below, ruled must-fix-before-lock
  and now FIXED: pe_asm refuses any delay-0 action but an ARM's
  (`model/zero_spacing.py`; docs/RESUME_CLOCKED_ARC.md). A program written
  that way was outside the guarantee while being certified inside it.
* **When the NeoPixel Stick arrives,** identify the actual LED part on it
  (WS2812B, SK6812, …) and record it here. Different parts have different T0H
  windows; no claim is made from a different part's datasheet.

### The datasheet (fetched from the manufacturer, quoted; not vendored)

Worldsemi, **"WS2812B-V5/W Intelligent control LED integrated light
source", datasheet V6.1 (2022-09-08)**, www.world-semi.com
(`/web/userfiles/productfile/WS2812B_V5WDatasheet_V6.1_EN.pdf`), p. 3,
table **"Data Transfer Time"**; the same numbers in **WS2812B-V6 规格书
V1.1** (Chinese), p. 4, "数据传输时间", which adds TDATA:

| symbol | quoted | cycles @ 50 MHz |
| --- | --- | --- |
| T0H | "0 code, high voltage time 220ns~380ns" | 11 – 19 |
| T1H | "1 code, high voltage time 580ns~1µs" | 29 – 50 |
| T0L | "0 code, low voltage time 580ns~1µs" | 29 – 50 |
| T1L | "1 code, low voltage time 580ns~1µs" | 29 – 50 |
| RES | "Frame unit, low voltage time >280µs" | > 14,000 |
| TDATA (V6 CN) | "数据周期 ≥1.25us" (data period) | ≥ 62.5 |

p. 1: *"RESET time>280μs, it won't cause wrong reset while interruption"*;
p. 4: *"Data transmit in order of GRB, high bit data at first."* The "50 µs"
latch and the ±150 ns nominals used before are older-part numbers; the
current part needs > 280 µs.

### Five lanes busy (scratch probe `probe_ws2812/`, iverilog, not committed)

Program: lane 0 on `uo_out[0]`, push-pull, MSB-first; per bit `LEVEL hi
(d1) → SHIFT bit (d2: 0 falls, 1 stays) → LEVEL lo (d3)`, 8 bits unrolled +
`REARM`; nominal T0H = d1, T1H = d1+d2, T0L = d2+d3, T1L = d3. The tightest
admissible choice for these bounds is **d1 = 20 (= D*), d2 = 20, d3 = 30**.
**All four other lanes busy**: push-pull `OP_LEVEL` toggles on `uo_out[1..3]`
and `uio[0]` at d = 20. pe_asm: ACCEPTED, d_min 20, J = 1. Host feed `A5 3C
F0 0F` on queue 0; 60,000 cycles; **864 consecutive decoded bits equal the
fed stream exactly**; underrun 0, config_err 0, tx_full 0.

| | measured cycles | measured ns | datasheet ns | |
| --- | --- | --- | --- | --- |
| T0H | 17 – 20 (n 429) | 340 – 400 | 220 – 380 | ⛔ **FAIL** (max) |
| T1H | 37 – 40 (n 424) | 740 – 800 | 580 – 1000 | ok |
| T0L | 48 – 52 (n 429) | 960 – 1040 | 580 – 1000 | ⛔ **FAIL** (max) |
| T1L | 28 – 32 (n 424) | 560 – 640 | 580 – 1000 | ⛔ **FAIL** (min) |
| period | 68 – 72 (n 853) | 1360 – 1440 | ≥ 1250 (V6) | ok |

**Why no admissible tuning fixes it.** T0H is one action delay: T0H ≥ d1 ≥
D* = 20 cycles = 400 ns > 380 ns, and `d1 = 19` is refused by pe_asm
("d_min = 19 is below D* = 20 ... LANE 0 carries the tightest spacing").
Independently, with the measured ±2-cycle jitter, T1L ≥ 29 needs d3 ≥ 31 and
T0L ≤ 50 needs d2 + d3 ≤ 48, so d2 ≤ 17 < D*. Both are consequences of
D* = 20 at 50 MHz, not of this program. (The open-drain held/direct
pipeline offset — a held SHIFT lands SDA_HOLD = 15 cycles after dispatch —
was analysed, not simulated: it reaches T0H = 15 but forces one low ≥ 55
cycles = 1.1 µs > 1 µs, and needs a pull-up fast enough for 800 kHz.)

### The latch (Wilson's cheap option first)

Measured with the same build, after the timing window (each pause 20,000
cycles = 400 µs):

* **Host stops feeding (TX underrun):** the pin is **not** held low. The
  loop's `LEVEL hi` is unconditional and an underrunning SHIFT shifts in 0s,
  so the lane keeps emitting **0-codes**: 286 rises in the 400 µs, longest
  low 52 cycles (1.04 µs). No reset is ever seen by the part.
* **Host raises PROG:** in load mode `project.v` forces the four `uo_out`
  protocol pins **HIGH** (`proto_out = prog_mode ? 4'b1111 : ...`): the pin
  was high for 19,997 of 20,000 cycles. A long HIGH, not a latch.

So the cheap option fails (the pin pulses, or goes high), and the fallback
applies:

* **3-sub-bit encoding** (each WS bit = host bits `1 b 0`, the lane SHIFT-only
  at sub-bit period p). **Latch: works** — an underrunning lane shifts 0s, so
  pausing the host IS the latch: the pin was low for the whole 400 µs pause
  (> 280 µs RES). **Host bandwidth, measured** (p = 21, lane alone): 118 TX
  bytes per 20,000 cycles = one byte per ~169.5 cycles (3.4 µs) ≈ **295
  kB/s**, against one byte per 560 cycles (≈ 89 kB/s) for the 3-action scheme
  — 3.3×. **Timing: infeasible by construction** — T0H = p ≥ D* = 20 cycles
  (400 ns > 380), and T1L = p must be ≥ 29 cycles (580 ns), contradicting T0H
  ≤ 19.
* ⛔ **A FINDING ON THE WAY, for Wilson (toolchain, not WS2812).** The 3-sub-bit
  lane at p = 21 **beside the four d = 20 neighbours** emitted a stream that
  does **not** equal the fed one (longest match 5 sub-bits; alone, and at
  p = 30 with the same neighbours, it matches exactly — 930 / 642 bits). Its
  SHIFT writebacks were spaced **3 to 139 cycles** apart for a programmed 21.
  The lane's loop ends in `REARM` with **delay 0**; with that REARM at delay
  21 the spacing is 20–54. pe_asm ACCEPTED the delay-0 build with
  "d_min 20, J 1": `compute_j` (and N1's `refill_dmin`) take the minimum over
  **positive** delays only, so a delay-0 REARM's zero spacing is invisible to
  the admissibility screen. Not fixed here (it touches what "admissible"
  means); reported.

**Hardware note.** The WS2812B's data input is a 5 V-logic input (VIH =
0.63·VDD ≈ 3.15 V at 5 V, above the chip's 3.3 V output at margin ~0.15 V),
so the data line goes through the **74AHCT125** already on order (TTL-level
input, 5 V output) on the board — whatever encoding is used.

**What would make it claimable.** The reach branch's per-lane serializer (a
byte → 24 timed edges with no dispatch per edge) removes the D* floor from
the edge spacing; or a clock faster than 50 MHz such that D* × period ≤
380 ns. Neither exists on the frozen chip.

### History — the first measurement (judged against nominals; superseded)

**Program (scratch probe, not committed):** one push-pull lane on
`uo_out[0]`, MSB-first; per bit `LEVEL hi (d 20) → SHIFT bit (d 20: 0 falls,
1 stays) → LEVEL lo (d 22/23)`, 8 bits unrolled + `REARM` (delay 0) = 25
actions. `d_min = 20 = D*`; **pe_asm accepts it** (J = 1). Host bandwidth: one
TX byte per 8 bits (10 µs).

**Measured** (iverilog, 30,000 cycles, ~480 bits, host feed `A5 3C F0 0F`;
the decoded bit stream equals the fed stream exactly, at a phase offset):

| | alone | beside a lane toggling at d = 25 | spec (cycles) |
| --- | --- | --- | --- |
| T0H | 16–20 | 18–20 | 12.5–27.5 |
| T1H | 36–40 | 38–40 | 32.5–47.5 |
| T0L | 42–46 | 42–46 | 35–50 |
| T1L | 22–26 | 22–24 | 15–30 |
| period | 58–66 | 60–66 | 32.5–92.5 |

(The first high pulse after start-up, the idle-high line, is excluded.)
Inter-edge jitter: **≤ 4 cycles (80 ns)** against the ±150 ns tolerance —
the 3-cycle late dispatch after the delay-0 REARM, plus EDF contention.
Margin ≈ 70 ns at `d = D*`.

**Verdict at the time (WITHDRAWN above): "the bit timing is FEASIBLE on the
frozen engine (CE5b)".** The gap:
the loop's `LEVEL hi` is unconditional, so the lane **cannot emit the
> 50 µs latch low** by itself (on TX underrun it sends 0-bits, not a latch);
the host must stop the engine (PROG) to latch. A sub-bit encoding (three
host bits per WS2812 bit, `1 b 0`, SHIFT-only at d ≈ 21) would make the
latch a run of 0s, at 3× the host bandwidth — **not measured**. Margin at
`d = D*` with five busy lanes is not measured either; the per-lane serializer
of the reach branch removes both (a byte → 24 timed edges with no dispatch
per edge).
