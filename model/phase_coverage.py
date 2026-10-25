"""PHASE COVERAGE -- one row per tracked bench, and how its full phase coverage
is established (step 3a, coverage_gate_prediction.txt; Wilson 10-20 / R3).

Wilson's rule: every timing bench prints its phase coverage and a gate reds if
it drops below full. "Full" is a property of the EVIDENCE, so each bench has a
class (model/gate_phase_coverage.py checks every row):

  IN_SUITE(runner, floor)  the suite runner itself asserts >= floor of the 20
                           1 ns phases of the 50 MHz clock (its PHASE_FLOOR);
  SWEEP(record, runners)   full coverage is a committed sweep RECORD, bound by
                           blob hash to what it read (test/sweep_record.py); a
                           moved input makes the row PENDING;
  CHIP_DRIVEN(reason)      the peer only reacts to the CHIP's own edges, so
                           there is no independent peer phase to walk;
  NOT_TIMING(reason)       no peer-timing claim: a scheduler, structural or
                           functional bench (inputs placed on a clock edge by
                           design).

⛔ CLOSED WORLD (Wilson R3 point 1): the gate lists test/tb_*.v from git; a
bench with no row is RED, so a new timing bench cannot arrive unclassified.
⛔ A REASON IS REQUIRED for CHIP_DRIVEN / NOT_TIMING (point 3), and PENDING
blocks the tag (point 2: `gate_phase_coverage.py --tag`).
"""

ROWS = {
    # ---- the peer walks its own phase inside the suite ----------------------
    "test/tb_spitgt.v": ("IN_SUITE", {"runner": "test/run_spitgt.py", "floor": 20}),
    "test/tb_uartrx.v": ("IN_SUITE", {"runner": "test/run_uartrx.py", "floor": 18}),
    "test/tb_v2win.v": ("IN_SUITE", {"runner": "test/run_v2window.py", "floor": 20}),
    # ---- full coverage is a sweep --------------------------------------------
    "test/tb_i2c.v": ("SWEEP", {"record": "model/phase_sweep_i2c.json",
                                "recipe": "test/sweep_i2c_delay.py",
                                "phases_ns": 7}),
    "test/tb_ckack.v": ("SWEEP", {"record": "model/phase_sweep_i2c.json",
                                  "recipe": "test/sweep_i2c_delay.py",
                                  "phases_ns": 7}),
    "test/tb_trace.v": ("SWEEP", {"record": "model/phase_sweep_i2c.json",
                                  "recipe": "test/sweep_i2c_delay.py",
                                  "phases_ns": 7,
                                  "note": "its I2C peer (fram_i2c) is swept here; its "
                                          "SPI peer (fram_spi) is CHIP-DRIVEN -- it "
                                          "shifts on the chip's own SCK edges, and its "
                                          "MISO delay is swept in whole cycles by "
                                          "test/run_spidelay.py"}),
    "test/tb_onewire.v": ("SWEEP", {"record": "model/phase_sweep_onewire.json",
                                    "recipe": "test/sweep_onewire_phase.py"}),
    # ---- the peer reacts only to the chip's edges ----------------------------
    "test/tb_rxbw.v": ("CHIP_DRIVEN", "the serial host link's capacity: the chip "
                       "clocks every bit it sends and receives; the start alignment "
                       "is swept over 50 offsets in the runner"),
    "test/tb_uarttx.v": ("CHIP_DRIVEN", "the peer is a RECEIVER timing the chip's own "
                         "TX edges; it drives nothing back"),
    "test/tb_cktx.v": ("CHIP_DRIVEN", "clocked TRANSMIT values: the chip drives clock "
                       "and data, Layer V checks them against the golden model"),
    # ---- no peer-timing claim --------------------------------------------------
    "test/tb_csat.v": ("NOT_TIMING", "inter-dispatch spacing under saturation "
                       "(scheduler; pre-registered docs/PREREG_C_SAT.md)"),
    "test/tb_edge.v": ("NOT_TIMING", "the reactive-release must-fires: every input "
                       "written on a negedge by design (audit #3); edge placement "
                       "varied in whole cycles and checked differentially"),
    "test/tb_fifo.v": ("NOT_TIMING", "same-cycle host push + engine pop (structural)"),
    "test/tb_half.v": ("NOT_TIMING", "TX and RX on one lane: the peer is driven on "
                       "the negedge by design, so the claim cannot ride on phase"),
    "test/tb_jlane.v": ("NOT_TIMING", "per-lane dispatch jitter instrument (scheduler)"),
    "test/tb_lock.v": ("NOT_TIMING", "the schedule freeze: dispatch + pin streams vs "
                       "a golden (scheduler)"),
    "test/tb_pinrange.v": ("NOT_TIMING", "pins outside the real range (structural)"),
    "test/tb_reload.v": ("NOT_TIMING", "a reload is a clean slate (state reset); "
                         "its peers only complete transactions, no timing claim"),
    "test/tb_smoke.v": ("NOT_TIMING", "load port + pins move (smoke)"),
    "test/tb_status.v": ("NOT_TIMING", "the two host status bits (structural)"),
    "test/tb_tx.v": ("NOT_TIMING", "two TX lanes interleave their own bytes (host data path)"),
    "test/tb_verdict.v": ("NOT_TIMING", "the arm-verdict pipeline must-fire (exists to fail)"),
    "test/tb_w.v": ("NOT_TIMING", "Theorem 3 on the bench: the port ledger (scheduler)"),
    "test/tb_witness.v": ("NOT_TIMING", "the prefetch-stall witness chain (scheduler)"),
}
