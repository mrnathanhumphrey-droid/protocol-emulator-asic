# v2 status, by evidence

What the v2 chip can do today, sorted by **how far each piece has been verified**.
An item moves up a tier only when the evidence on its line exists. "CI" means
the gate runs in CI on every push to the integration branches
(`ci/run_gates.sh`), and most also run locally before every push
(`.githooks/pre-push`); every gate named here has a deliberate defect that must
turn it red.

v1 is tagged `v1-lock` and closed at 50 MHz on 6×4 tiles. It is the fallback,
and its own record is unchanged.

---

## 1. Built and verified

| | what | evidence |
|---|---|---|
| **The Protocol Inference Tile (PIT)** | Point it at an unknown bus. It records the edges, classifies every wire, measures bit period and phase, decodes the frames, and recovers the CRC polynomial with its init and xorout, **on chip**. | **CI:** `run_pit_capture` (the capture, bit for bit against a golden encoder), `run_pit_s0` (the role table), `run_pit_s3` (stage 3 on the full chip after a real capture), `run_pit_gcd` (the CRC solver: a fixed 214-set subset on every push, **3,696 / 3,696 sets bit-exact** in the full run), `run_pit_s12` (stages 1–2: period, phase and score records per wire). Twenty-three planted RTL faults across these gates, each with its named killer. |
| **The two-chip round trip** | One chip sniffs a bus and writes what it found as a spec. The spec is assembled into a program for a second chip, which emulates the bus, and that emulation is sniffed and compared with the original. | **CI:** `run_pit_rt`, **16 / 16 round trips**, with two planted emitter faults (init off by one, CPOL flipped) that must fail. **CI:** `run_pit_clk`, the clocked-bus path (SPI and I²C, including the buses it must refuse), bit-exact, with nine planted faults, and a SNIFF re-run without a reset checked against a fresh run, byte for byte. |
| **The spec emitter, v1** | The PIT's results written as text in a Rapide-style syntax, saying only what the chip determined (anything it could not determine is written `? unknown`), and read back by its own parser. | **CI:** `run_pit_emit` (spec text against the results bytes, and the parser's round trip), and end to end through `run_pit_rt`. |
| **The SRAM program store** | The program lives in the IHP `RM_IHPSG13_1P_256x32` macro. No raw input pin reaches any of its input bits. | **CI:** `gate_macro_inputs` (every macro input bit driven only through registers, with a planted raw path that must be found). Gate-level simulation of the SRAM build, 16 / 16 cocotb tests on the hardened netlist (ttihp27a flow, run locally 11-10). |
| **Clock-domain crossing** | Every host input synchronised; the data nibble sampled only on the synchronised write edge. | **CI:** `gate_cdc_qual`, a yosys induction proof (11,640 of 11,641 flop bits; the remaining one is the declared synchroniser). |
| **The scheduler proofs** | Non-preemptive EDF over five lanes; refill spacing `d_min ≥ D* = 20 → J = 1`. | **CI:** the Lean theorems `dstar`, `dstar29`, `dstar39`, checked to rest only on Lean's standard axioms, with the model tied to the RTL by trace replay. Zero refill stalls measured on v1 at d = 20–60. On v2 the sweep reads zero at every point from d = 20 to 60, but its below-D* control also reads zero (v1: 29). Until the control shows the instrument can see a stall on v2, the v2 zeros are not counted as a measurement. |
| **The v2 instruction set** | 18 opcodes in a 32-bit action word, including `BRANCH_BIT`, `CMP_BRANCH` and `LOOP`; a two-pin `ARM`; `DRIVE_SAMPLE` (drive one pin, sample another in the same action). | **CI:** `run_branch_check`, `run_arm2`, `run_drive_sample`, `gate_v2_equiv` (every v1 program runs identically on v2). |
| **The slot buffer and the FALLTHROUGH `ARM`** | Each lane holds a head, a spare and one buffered word. A FALLTHROUGH `ARM` waits for an edge within a window and otherwise continues instead of halting; it fetches its edge word first and keeps it through the edge. | **CI:** `run_slotbuf`; `run_ftflush` (the flush, keep and drop rules, and the scheduler contracts K9–K11: the edge's fetch never races its flush, an edge acts only from the cycle after arming, an armed lane is never chosen before its deadline), **13 planted faults**. The buffered engine is modelled cycle-exact in Lean (`BufEng`, `RespWinB`, `RestartB`). |
| **Inter-lane event flags** | Eight counted flags: `POST`, `WAIT` (holds the lane until a count is available, then takes it), `OBSERVE` (reads the count, takes nothing). | **CI:** `run_flags`, **4 planted faults**. The assembler proves no flag can run 8 ahead on any path of any posting lane, or refuses the program by name. |
| **The symbol generator** | One shared generator, owned by one lane: `SER` sends a byte as line-coded edges (NRZI, differential Manchester, biphase), every edge timed by a hardware counter rather than by dispatch; `SYMDEF` sets the code. | **CI:** `run_symgen`, with its refusals (wrong lane, busy generator) and the overrun case. |

## 2. Built and simulated, hardware pending

| | what | where it stands |
|---|---|---|
| **USB low-speed device reflexes** | NRZI receive, bit unstuffing and re-anchoring, CRC16 checked on chip, a response buffer in the SRAM's spare half, bus reset, device address and token check. The host microcontroller builds packets; the chip meets the turnaround. | Simulated in CI: `run_usbrx`, `run_usbcrc`, `run_usbbuf`, `run_usbaddr`, `run_usbrst`. **Never run against a real USB host.** |
| **60 MHz** | The chip's target clock. Every program is built for it, and every simulation runs at it. | **Timing is not closed, and today's RTL has not been timed at all.** History: −1.882 ns slow-corner setup (b6, 73a387a, 11-11; the PIT's GCD step) was traced to the flow estimating wires with the tech LEF's RC; with calibrated `LAYERS_RC` the s12 RTL (4404e48, 11-13) routed at **+3.1 to +4.0 ns** slow setup over three coefficients, against the +2.4 ns line, TNS 0, but fast-corner hold read +0.02 to +0.04 ns, under its +0.05 ns line. The hold / routing spread on 9c0df0c (11-15 / 16) reached GDS, precheck and gate-level on one run; its rung-2 runs ended in detailed routing (rc 1) and the spread was cancelled. **Since then the slot buffer (pieces 2–4) and its fixes went into the RTL with no synthesis, timing or route** (found 11-24). Pre-route check on today's RTL (e72e47f, 11-24, the same flow to post-CTS STA): instance area 691,737 µm² against 589,902 on 9c0df0c (+17 %), utilisation 57.3 % against 48.8 %, typical-corner setup +7.62 ns against +7.69. Slow and fast corners cannot be read before routing on this flow (9c0df0c read −38 ns slow at this step and +4.42 ns at sign-off), so they wait for the trial harden. Until it closes, v2 is a 60 MHz *design*, not a 60 MHz chip. |

## 3. In progress for v2

| | what | state |
|---|---|---|
| **The poset language and its compiler** | One spec → chip program + host encoder + checker. | Not built. The emitter (tier 1) is its first piece. |
| **On-chip poset primitives** | Order-and-bounds checking in silicon. | First piece built: the inter-lane event flags (tier 1). |
| **The RTL against the Lean engine model, cycle by cycle** | Every cycle of a simulation stepped through the Lean-mirrored model of the buffered engine and compared field by field. | Running. The FALLTHROUGH and USB benches match cycle for cycle so far; the full bench set is being replayed, and the paths the model does not yet cover are counted separately, not passed. |
| **The validator** | Checks a program against its spec before it loads. | Not built. |
| **The USB keyboard demo** | The chip enumerating as a keyboard on a laptop and typing, through the FPGA prototype. | Not yet. Needs tier 2's USB on real hardware first. |

---

Each line above links to a gate in `ci/run_gates.sh` or to a stated measurement.
When a measurement is pending, the line says so instead of rounding up.
