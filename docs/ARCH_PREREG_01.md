# PRE-REGISTRATION 01 — the architecture

**Written before any RTL.** Jane Street protocol-emulator ASIC competition,
IHP CMOS5L via Tiny Tapeout, deadline 18 Jan 2027.

## THE TARGET, STATED AS A TIER

⛔ **The baseline goal is an ENTRY THAT WORKS, not a novel one.** Getting eyes is
the win. Novelty is pursued only where it is free or nearly so, and the three
summits are parked until a chip exists.

## WHAT THE FIELD ALREADY HAS (6-repo sweep, 2026-10-01)

| idea | status |
|---|---|
| one shared engine, all protocols concurrently | **TAKEN** — built, 18,776 cells, +57.4 ns slack |
| per-pin routing/drive descriptor off the opcode | **TAKEN** — stated, though that RTL has never been compiled |
| deadline-scheduled **timestamped OUTPUT action queue** | ⭐ **OPEN** — nobody |

⛔ **The verification bar is already high.** Competitors are running formal
k-induction, three-corner SDF, mutation testing, and in one case hardware
confirmation with Wireshark capture. An entry whose only distinction is "we have
a good testbench" is not distinguished.

⭐ **Area is not the binding constraint.** A complete 10 Mb/s Ethernet PHY+MAC —
the *stretch* goal — fits one tile at 63% utilisation elsewhere in the field.

---

## THE ARCHITECTURE

**A single shared action engine serving all lanes, driven by a
deadline-ordered action queue.**

```
per lane (descriptor, reprogrammable):  pin, drive mode, shift reg, bit counter,
                                        divider, next-action timestamp
queue:   small, timestamp-ordered. earliest deadline served first.
engine:  pop earliest -> drive pin -> compute next timestamp -> re-queue
```

⭐ **WHY A QUEUE AND NOT "GRAB IT WHEN FREE".** Protocols have deadlines. An
engine busy with SPI when UART's bit edge comes due makes the bit jitter and the
protocol breaks — opportunistic claiming has no bound. Earliest-deadline-first
has one, and it is **provable**: with Q lanes and k cycles of service, worst-case
lateness is `(Q-1) x k` cycles. **A number you can prove is worth more here than a
number you can measure**, and the competition names formal methods explicitly.

⭐ **AND THE DUTY CYCLE MAKES IT FREE.** At 50 MHz, one event per bit:

| lane | clks/bit | engine busy at 2 clk/event |
|---|---|---|
| UART 115200 | 434 | 0.5% |
| SPI 1 MHz | 50 | 8.0% |
| I2C 400 kHz | 125 | 3.2% |
| **all three concurrently** | | **11.7%** |
| 10 Mbit Ethernet | 5 | **40%** ← the pressure point |

~9x headroom on the three required protocols. **Dedicating a state machine per
protocol — what PIO does — pays 4x for something running at a tenth duty.**

## SCOPE OF THE FIRST BUILD

- **UART (8N1), SPI (mode 0), I2C (single controller)** — the required three.
- **8 bidirectional pins** (`uio[7:0]`) as the protocol interface. UART 2 + SPI 4
  + I2C 2 = exactly 8, so all three can be live at once.
- ⛔ **`uio_oe` is load-bearing, not a convenience:** I2C needs open-drain (drive
  low, release high), SPI/UART need push-pull. **Per-pin drive mode is a hard
  requirement**, not a feature.
- 50 MHz fixed external clock (`CLOCK_PERIOD: 20`).

## ⭐ WHAT THE BASELINE BUILDS IN TO KEEP THE SUMMITS REACHABLE

Three decisions that cost little now and would cost a rewrite later:

1. **Edge timestamping on input pins** — cheap (a counter and a capture
   register), and it is the entire substrate for protocol *discovery*. Built even
   though nothing consumes it yet.
2. **The action path stays TABLE-DRIVEN**, never opcode-encoded, so a
   transition-table machine is a reinterpretation of existing storage rather than
   new silicon.
3. **The golden model is written as an executable formal semantics of the ISA**
   from day one — so a conformance proof later starts from a spec that already
   exists instead of one reconstructed afterwards.

---

## PREDICTIONS

| # | prediction | tier |
|---|---|---|
| A1 | UART+SPI+I2C concurrently fit in the tile budget | measured |
| A2 | worst-case queue lateness is exactly `(Q-1) x k` cycles and is **provable**, not just measured | analytic, then formal |
| A3 | the three required protocols are bit-exact against a golden model on both simulators | measured |
| A4 | the design closes timing at 50 MHz (20 ns) | measured |
| A5 | all three protocols run **simultaneously** on one engine without missing a deadline | measured |

## ⛔ FALSIFIERS

| # | if | then |
|---|---|---|
| F1 | any protocol's waveform diverges from the golden model on either simulator | the engine is wrong; no timing or area number counts |
| F2 | measured worst-case lateness **exceeds** `(Q-1) x k` | the scheduling argument is broken — the bound is the differentiator, so this invalidates the entry's premise, not just a number |
| F3 | 50 MHz does not close | the engine is too deep per event; reduce work per action before adding lanes |
| F4 | the design does not fit the tile budget | re-scope to fewer concurrent lanes; do **not** drop a required protocol |
| F5 | open-drain I2C cannot be expressed through `uio_oe` as modelled | the pin abstraction is wrong and must be fixed before any protocol work continues |

## ⛔ TWO SPEC DISCREPANCIES, UNRESOLVED, NOT TO BE RESOLVED BY ARITHMETIC

1. **Tile count.** Jane Street says "6x4 tiles (~0.7 mm²)". This template's
   `info.yaml` allows `1x1, 1x2, 2x2, 3x2, 4x2, 6x2, 8x2` — max 16 tiles — and
   states 167x108 µm per tile, making 6x4 = 0.43 mm², not 0.7. A competitor's
   measured 515,364 µm² fit. **The authority is a real run, not this arithmetic.**
2. **Toolchain.** The flow is **librelane** (OpenLane 2), not the OpenLane 1.1.1
   in our cached image. **The GitHub Action is the trustworthy build path**, not
   a local container.
