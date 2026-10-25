# Scope of v1 — what this chip claims, and what it does not

v1 is the design as tagged `sub-v1`: IHP `sg13cmos5l`, 6×4 tiles, 50 MHz, for
the Tiny Tapeout shuttle. Every claim below points at the evidence that
carries it; anything not listed here is not claimed.

## Claimed

| claim | evidence |
|---|---|
| Five protocol lanes on one engine, at the rates in the README's lane table: UART-tx 115,200, SPI master 1 MHz, I²C Fast-mode (397 kHz formula / 393.7 kHz sim / 370.4 kHz board), UART-rx 115,200, SPI target (MISO 1 MHz, MOSI capture 500 kHz) | the two-simulator trace corpus (10 of 10) and each lane's runner, in `ci/run_gates.sh` |
| Their worst-case response times are bounded: published bound min margin 11 cycles (pyRTA), our analysis may only be more pessimistic | `model/a2/run_a2.py` (pyRTA cross-check, subsets 0 disagreements) |
| The design closes timing at 50 MHz | the CI harden of record: slow-corner setup +2.676 ns, hold +0.105 ns, 0 violations; `model/gate_harden_record.py` holds the tree to what it hardened |
| Every timing bench's peer phase is covered | `model/gate_phase_coverage.py`: a row per bench; in-suite walks, or sweeps bound by blob hash to the tree |
| Refill spacing `d ≥ D* = 20` gives `J = 1` | measured (`test/run_dstar_check.py`) and proved in Lean (`dstar`, `dstar29`, `dstar39`), under the hypotheses those theorems state |
| The restructured lane select and dispatch pick equal what they replaced | SymbiYosys proofs with refuted mutants (`formal/`) |
| Every check can fail | each gate's must-fires, and `model/gate_meta.py` (each check stubbed to always pass must turn its gate red) |
| UART-rx, I²C and 1-Wire on real parts | Artix-7 prototype; I²C and 1-Wire as recorded bench witnesses re-checked in CI (`fpga/witness/`) |

## Not claimed

- **60 MHz, or the 8×4 tile.** Those are v2 configuration results, not v1.
- **The SPI target on hardware.** It is witnessed in simulation only.
- **The trace corpus at gate level.** The cocotb suite has run on the hardened
  netlist; the corpus has not.
- **The UART hardware run as evidence.** It is a dated account; the raw output
  was not kept (README, "On real hardware").
- **Any protocol beyond the five lanes as certified.** Another protocol is
  supported if `model/pe_asm.py` accepts its program against the instruction
  set and the timing envelope; that verdict is the claim, not a certification.
- **Behaviour the host must provide.** The host-side requirements in
  `docs/HOST_INTERFACE.md` (for example the SPI target's 6-cycle CS lead) are
  the host's obligation; the chip's claims hold only when they are met.
