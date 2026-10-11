# CE5 — 1-Wire (DS18B20) on the frozen RTL: expressiveness log

CE5 asks whether the **frozen** chip (`src/` unchanged since the freeze SHA,
`model/gate_ce5_freeze.py`) can run a protocol it was never designed for with
a pe_asm program alone. The answer is yes, with the workarounds below. Each
entry is a place the ISA or pe_asm could **not** say what the protocol
needed: the workaround used, and the RTL change that would remove it.
**No RTL change was made.** This is flexibility evidence, stated with its
costs.

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

## Part D — WS2812 (measure, don't build): verdict CE5b, with one gap

**Spec used** (WS2812 family, as commonly published; no datasheet was
fetched for this, so treat the bounds as nominal): T0H 0.40 µs, T1H 0.80 µs,
T0L 0.85 µs, T1L 0.45 µs, each ±150 ns; bit period 1.25 µs ± 600 ns; latch
(reset) low > 50 µs. At 50 MHz: 20 / 40 / 42.5 / 22.5 cycles, ±7.5.

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

**Verdict: the bit timing is FEASIBLE on the frozen engine (CE5b).** The gap:
the loop's `LEVEL hi` is unconditional, so the lane **cannot emit the
> 50 µs latch low** by itself (on TX underrun it sends 0-bits, not a latch);
the host must stop the engine (PROG) to latch. A sub-bit encoding (three
host bits per WS2812 bit, `1 b 0`, SHIFT-only at d ≈ 21) would make the
latch a run of 0s, at 3× the host bandwidth — **not measured**. Margin at
`d = D*` with five busy lanes is not measured either; the per-lane serializer
of the reach branch removes both (a byte → 24 timed edges with no dispatch
per edge).
