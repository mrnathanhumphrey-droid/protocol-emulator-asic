# v2 status, by evidence

What the v2 chip can do today, sorted by **how far each piece has been verified**.
An item moves up a tier only when the evidence on its line exists. "CI" means
the gate runs on every push (`ci/run_gates.sh`); every gate named here has a
deliberate defect that must turn it red.

v1 is tagged `v1-lock` and closed at 50 MHz on 6×4 tiles. It is the fallback,
and its own record is unchanged.

---

## 1. Built and verified

| | what | evidence |
|---|---|---|
| **The Protocol Inference Tile (PIT)** | Point it at an unknown bus. It records the edges, classifies every wire, measures bit period and phase, decodes the frames, and recovers the CRC polynomial with its init and xorout, **on chip**. | **CI:** `run_pit_capture` (the capture, bit for bit against a golden encoder), `run_pit_s0` (the role table), `run_pit_s3` (stage 3 on the full chip after a real capture), `run_pit_gcd` (the CRC solver: a fixed 214-set subset on every push, **3,696 / 3,696 sets bit-exact** in the full run), `run_pit_s12` (stages 1–2: period, phase and score records per wire). Twenty-three planted RTL faults across these gates, each with its named killer. |
| **The two-chip round trip** | One chip sniffs a bus and writes what it found as a spec. The spec is assembled into a program for a second chip, which emulates the bus, and that emulation is sniffed and compared with the original. | **CI:** `run_pit_rt`, **16 / 16 round trips**, with two planted emitter faults (init off by one, CPOL flipped) that must fail. **CI:** `run_pit_clk`, the clocked-bus path (SPI and I²C, including the buses it must refuse), bit-exact, with eight planted faults. |
| **The spec emitter, v1** | The PIT's results written as text in a Rapide-style syntax, saying only what the chip determined (anything it could not determine is written `? unknown`), and read back by its own parser. | **CI:** `run_pit_emit` (spec text against the results bytes, and the parser's round trip), and end to end through `run_pit_rt`. |
| **The SRAM program store** | The program lives in the IHP `RM_IHPSG13_1P_256x32` macro. No raw input pin reaches any of its input bits. | **CI:** `gate_macro_inputs` (every macro input bit driven only through registers, with a planted raw path that must be found). Gate-level simulation of the SRAM build, 16 / 16 cocotb tests on the hardened netlist (ttihp27a flow, run locally 11-10). |
| **Clock-domain crossing** | Every host input synchronised; the data nibble sampled only on the synchronised write edge. | **CI:** `gate_cdc_qual`, a yosys induction proof (11,640 of 11,641 flop bits; the remaining one is the declared synchroniser). |
| **The scheduler proofs** | Non-preemptive EDF over five lanes; refill spacing `d_min ≥ D* = 20 → J = 1`. | **CI:** the Lean theorems `dstar`, `dstar29`, `dstar39`, checked to rest only on Lean's standard axioms, with the model tied to the RTL by trace replay. Zero refill stalls measured on v1 at d = 20–60. On v2 the sweep reads zero at every point from d = 20 to 60, but its below-D* control also reads zero (v1: 29). Until the control shows the instrument can see a stall on v2, the v2 zeros are not counted as a measurement. |
| **The v2 instruction set** | 12 opcodes in a 32-bit action word, including `BRANCH_BIT`, `CMP_BRANCH` and `LOOP`; a two-pin `ARM`. | **CI:** `run_branch_check`, `run_arm2`, `gate_v2_equiv` (every v1 program runs identically on v2). |

## 2. Built and simulated, hardware pending

| | what | where it stands |
|---|---|---|
| **USB low-speed device reflexes** | NRZI receive, bit unstuffing and re-anchoring, CRC16 checked on chip, a response buffer in the SRAM's spare half, bus reset, device address and token check. The host microcontroller builds packets; the chip meets the turnaround. | Simulated in CI: `run_usbrx`, `run_usbcrc`, `run_usbbuf`, `run_usbaddr`, `run_usbrst`. **Never run against a real USB host.** |
| **60 MHz** | The chip's target clock. Every program is built for it, and every simulation runs at it. | **Timing is not closed.** Last signed-off reading: **−1.882 ns** slow-corner setup, against a bar of +2.4 ns, the worst path in the PIT's GCD step. The fixes are in the RTL (registered step decode, registered divisor mask, per-group select copies, a log-depth compare), all bit-exact with zero added cycles. The routed result on the shipping flow is being measured. Until it closes, v2 is a 60 MHz *design*, not a 60 MHz chip. |

## 3. In progress for v2

| | what | state |
|---|---|---|
| **The poset language and its compiler** | One spec → chip program + host encoder + checker. | Not built. The emitter (tier 1) is its first piece. |
| **On-chip poset primitives** | Order-and-bounds checking in silicon. | Not built. |
| **The validator** | Checks a program against its spec before it loads. | Not built. |
| **The USB keyboard demo** | The chip enumerating as a keyboard on a laptop and typing, through the FPGA prototype. | Not yet. Needs tier 2's USB on real hardware first. |

---

Each line above links to a gate in `ci/run_gates.sh` or to a stated measurement.
When a measurement is pending, the line says so instead of rounding up.
