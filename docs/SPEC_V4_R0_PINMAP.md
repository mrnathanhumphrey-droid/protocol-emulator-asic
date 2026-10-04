# R0 — the host data channel deviated from the ruled pin map

Wilson's R0 after `69f94ee`: state whether "payload comes from the host over the
shared `uio` bus" was loose wording or an RTL deviation, and if a deviation, fix
the pin map before building on it.

## It was a deviation, and it was the cause of the block

`PHASE1_CLOSEOUT_PART3.md:104–116` rules the F1 data channel:

| pin | ruled use | what the RTL did |
|---|---|---|
| `ui_in[6]` | prog: WR / run: **TX payload PUSH** | WR only; unused in run mode |
| `ui_in[5]` | prog: ptr reset / run: RX payload POP | ptr reset only |
| `ui_in[4:1]` | **TX payload nibble**, 2 pushes per byte | **tied off in `_unused`** |
| `ui_in[0]` | `uo_out` view select | repurposed as the push |
| `uio[7:0]` | **protocol pins only — zero spent on the data channel** | `host_data = uio_q1`, i.e. **8 bits of the protocol bus** |

Both halves of the ruled channel were unbuilt:

1. **The nibble pins.** No nibble, push or pop logic existed anywhere in `src/`,
   and `ui_in[4:1]` sat in the `_unused` concatenation.
2. **The one FIFO.** PART3 ruled that "the host pushes bytes into one FIFO and
   the engine routes them as the program consumes them". The engine's consume
   site read `if (host_valid) l_data[cur] <= host_data; else underrun`, so the
   byte had to be present in the **exact cycle** a lane wanted it. No real host
   can meet that; it would log underruns.

⛔ **This is the fourth day-one commitment found unbuilt**, after edge capture,
the no-op half-bit and ruling 1.5 — and unlike those it was *the direct cause of
a blocked work item*. Taking the payload from `uio` means a host cannot deliver a
byte without driving the very pins a live protocol is using, which is exactly
why `corpus_spim` could not address the SPI FRAM and why no I²C ACK — and
therefore no peer-driven clock stretch — was reachable.

⚠ My earlier wording was **not** loose: it described the RTL accurately. Which
means `docs/HOST_INTERFACE.md` codified the deviation **as the contract**. That
is corrected, and the correction is noted in the document itself.

### What PART4 and PART5 did supersede

The **RX** half. Three spare `uo_out` pins cannot carry a nibble plus a valid, so
RX went **bit-serial** (the 3-pin serial host view), which retires the `ui_in[5]`
pop; and PART5 framed status **into** the stream, which retires the `ui_in[0]`
view select. **Neither supersedes the TX nibble or "zero `uio` spent".**

## Built

- `ui_in[4:1]` is the TX payload nibble; `ui_in[6]` is the PUSH in run mode
  (`push_rise = run & wr_rise`, reusing the existing 3-FF async-strobe chain).
- **HIGH nibble first**, ruled here so a host and a bench cannot disagree: it
  matches the MSB-first bit order the SPI and I²C lanes use, so a byte reads the
  same way on the wire as it was pushed.
- A **2-deep byte FIFO**; the engine pops via a new `host_pop` output each time a
  lane's `SHIFT` consumes data. **One** FIFO, not one per lane, per the ruling —
  the shift action already names its lane.
- **A push on a full FIFO is reported, never stalled**: sticky **TX-full** in
  status bit 4, which F1's status list named and nothing carried. The host has no
  back-pressure pin, so a flag in the stream is the only honest answer — the same
  reasoning as RX overflow.
- `uio` is protocol-only again. `ui_in[4:1]` is no longer in `_unused`.

⭐ **One assignment per register, with the simultaneous push/pop case
enumerated.** The first version updated `tx_cnt` from three overlapping `if`s and
leaned on last-write-wins to net out a same-cycle push and pop. That is the shape
of ordering argument this project has repeatedly had to retract, so the four
combinations are a `case` instead.

### Documents corrected

`info.yaml`'s pinout was the **pre-ruling datasheet throughout** — `uo[0..7]`
described as "pointer echo / program readback" (a model that no longer exists),
I²C SCL/SDA on the wrong pins, and `uio[2..7]` "reserved for protocol pins".
It now matches the derived map. This matters beyond tidiness: `info.yaml` is what
the Tiny Tapeout datasheet is generated from.

## #3 — the 10 unattributed flops

Measured, not guessed: both commits were synthesised and flop counts diffed
**per signal**.

| signal | Δ |
|---|---|
| `u_eng.pin_pp` | +12 |
| **`u_eng.hsh`** | **+10** |
| `rb_addr` | +8 |
| `rb_prime` | +1 |
| `$alumacc` re-mapping (net of −15/+15/−7/+7/+1) | +1 |
| **total** | **+32** — fully accounted |

`hsh` is the header shift register. `pin_pp`'s load reads **two more slices of
it** (the lane's `pin` and `clkpin`) plus their range comparators, so bits that
previously optimised away are now live. It is synthesis retention caused by a
new reader, which is what "most likely synthesis re-mapping" guessed — but the
reader is identifiable, so it is recorded as a cause rather than a shrug.

## #4 — the limit of 1.5, and the loader check

**Recorded: "an open-drain pin never drives a 1" holds BY DECLARATION.** The
mask is per-pin and runtime, set from each lane's header, so it enforces the mode
the program *declared*. A program that declares its I²C lane push-pull will
drive SCL high, and the construction cannot stop it — that is a program error of
the same kind as a wrong pin number.

**On the proposed heuristic — flag push-pull on a pin the program also arms for
input — my call is: not worth a 1.6 entry.** Reasons:

- Its **false-negative rate is the problem, not false positives.** Arming a pin
  you also drive push-pull is nearly always an error (you would be watching
  edges you created), so it would rarely misfire. But the headline failure —
  declaring an I²C lane push-pull — is only caught *if that program also arms
  SCL*. A program that gets the mode wrong may well omit the arm too, so the
  check misses the simplest version of the error it exists for.
- It is a heuristic sitting next to an **exact** check that is available.

⭐ **The exact check is worth an entry instead.** Under the two-bank ruling each
pin's electrical class is fixed at build time — `uio[1:2]` open-drain, `uio[7]`
tri-state, `uio[0,3,4,5,6]` inputs, the four `uo_out` protocol pins push-pull.
So the loader can **reject a header whose declared mode disagrees with the pin's
ruled class**, which is not a guess and makes the error impossible rather than
flagged.

⚠ **It would reject `five_image` and `chain_image`**, which declare push-pull on
`uio` pins 0..4. That is the correct verdict — they are not pin-map-legal
programs — and it is exactly what ruling #2 is about. So the loader check and the
stress-image relabelling are the same decision, and the check should land with
or after it, never before.

## Suite state

`yosys_check` clean, 0 multi-driver, static assertion fires, **2961 flops** ·
F2 on the real netlist **24 of 24** flop-or-constant · `gate_reset_audit`
**PASSED**, 2964 flops, 2103 unreset across 6 groups, **6 of 6 allowlisted** ·
`run_a2` **30 of 30** · `price_gates` **13 of 13 red** · `run_mutants` **4 of 4**
· `tb_smoke` PASS · `tb_edge` **5 of 5** · `gate_corpus_trace` **7 of 8, 1 open,
0 failed** · cocotb **7 of 7**.

⚠ The reset audit **correctly failed first**: `tx_fifo` was a new unreset group
and the gate refused to absorb it into a total that still looked about right. It
is now allowlisted with a write-before-read reason that **names its one
consumer** — the `s_rdata` lesson, where a second consumer inherited a reason
never written for it.

## Still open

- **R1/R2** — the ruled SHIFT semantics and a bench host model driving the
  nibble channel. The channel now exists for them to drive; `corpus_spim` and the
  real peer-driven stretch stay open until they land.
- **#2** — legalise copies of `five_image`/`chain_image` and assert the `J`/stall
  measurements are identical.
- Gate level for the current suite.
