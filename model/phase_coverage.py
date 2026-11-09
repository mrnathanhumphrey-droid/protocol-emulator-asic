"""PHASE COVERAGE -- one row per tracked bench, and how its full phase coverage
is established (step 3a, coverage_gate_prediction.txt; Wilson 10-20 / R3).

Wilson's rule: every timing bench prints its phase coverage and a gate reds if
it drops below full. "Full" is a property of the EVIDENCE, so each bench has a
class (model/gate_phase_coverage.py checks every row):

  IN_SUITE(runner, short)  the suite runner itself asserts it covers all but
                           `short` of the target clock's 1 ns phases (its
                           PHASE_FLOOR = clock.phases() - PHASE_SHORT: 20
                           phases at 50 MHz, 17 at 60 -- Wilson 11-03);
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
    "test/tb_spitgt.v": ("IN_SUITE", {"runner": "test/run_spitgt.py", "short": 0}),
    "test/tb_uartrx.v": ("IN_SUITE", {"runner": "test/run_uartrx.py", "short": 2}),
    # v2 primitive 3 bundle 3: the USB receive. Its U6 arm drives every host
    # edge at a fractional time and MEASURES the 1 ns bins (17/17 at 60 MHz)
    "test/tb_usbrx.v": ("IN_SUITE", {"runner": "test/run_usbrx.py", "short": 0}),
    "test/tb_v2win.v": ("IN_SUITE", {"runner": "test/run_v2window.py", "short": 0}),
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
    "test/tb_rxbw.v": ("CHIP_DRIVEN", "the host link it measures is the chip's OUTPUT "
                       "stream (data / strobe / valid on uo_out, clocked by the "
                       "chip); the host drives nothing on it (Wilson 10-25: stated). "
                       "Its RX peers enter through the uio 2-flop synchroniser, "
                       "whose sub-cycle phase tb_uartrx walks (IN_SUITE)"),
    "test/tb_uarttx.v": ("CHIP_DRIVEN", "the peer is a RECEIVER timing the chip's own "
                         "TX edges; it drives nothing back"),
    "test/tb_usbbuf.v": ("CHIP_DRIVEN", "v2 primitive 3 bundle 5: the claims are the chip's OWN "
                         "packets (bit for bit) and its turnaround after the host's EOP; "
                         "the host's receive-side sub-cycle phase is walked by tb_usbrx "
                         "(IN_SUITE), whose receive path this bench reuses unchanged"),
    "test/tb_pair.v": ("CHIP_DRIVEN", "v2 primitive 3 bundle 2: the claim is the chip's OWN "
                       "pair waveform (D+/D-, SHIFTI, self-timed bytes) cycle for cycle; its "
                       "one receive case is functional, and the unclocked sample's sub-cycle "
                       "phase is walked by tb_uartrx and tb_usbrx (IN_SUITE)"),
    "test/tb_arm2.v": ("NOT_TIMING", "v2 primitive 3 bundle 1: the claim is the two-pin "
                       "ARM's CYCLE latency from a synchronised input (fire 2 cycles after "
                       "the later pin); the pins are placed on clock edges by design, and "
                       "an edge's sub-cycle phase only moves which cycle the synchroniser "
                       "takes it -- the quantisation the USB budget carries and tb_usbrx walks"),
    "test/tb_xclock.v": ("CHIP_DRIVEN", "the cross-clock bench (gate_clock_cross, "
                         "Wilson 11-03): no peer -- every uio pin is pulled up -- "
                         "and it only records the chip's own edges, judged in ns "
                         "across two clocks; no independent peer phase to walk"),
    "test/tb_cktx.v": ("CHIP_DRIVEN", "clocked TRANSMIT values: the chip drives clock "
                       "and data, Layer V checks them against the golden model"),
    # ---- no peer-timing claim --------------------------------------------------
    "test/tb_pit.v": ("NOT_TIMING", "the PIT SNIFF capture bench "
                     "(test/run_pit_capture.py): it plays a recorded uio "
                     "stimulus on negedges and checks the stored bytes bit "
                     "for bit against the golden encoder; no peer-timing claim"),
    "test/tb_equiv.v": ("NOT_TIMING", "the v1 == v2 equivalence bench "
                        "(model/gate_v2_equiv.py): it compares two builds' "
                        "dispatch + pin streams; its host pushes sit on clock "
                        "edges by design and it makes no peer-timing claim"),
    "test/tb_csat.v": ("NOT_TIMING", "inter-dispatch spacing under saturation "
                       "(scheduler; pre-registered docs/PREREG_C_SAT.md)"),
    "test/tb_edge.v": ("NOT_TIMING", "the reactive-release must-fires: every input "
                       "written on a negedge by design (audit #3); edge placement "
                       "varied in whole cycles and checked differentially. The "
                       "timing side of edge capture is phase-walked by tb_spitgt "
                       "(CS/SCK releases, 20/20) and tb_uartrx (start edge, 18/20)"),
    "test/tb_fifo.v": ("NOT_TIMING", "same-cycle host push + engine pop (structural)"),
    "test/tb_half.v": ("NOT_TIMING", "TX and RX on one lane: the peer is driven on "
                       "the negedge by design, so the claim cannot ride on phase. "
                       "The timing side of one-lane TX + RX is phase-walked by "
                       "tb_spitgt (MOSI capture + MISO drive, 20/20)"),
    "test/tb_jlane.v": ("NOT_TIMING", "per-lane dispatch jitter instrument (scheduler)"),
    "test/tb_lock.v": ("NOT_TIMING", "the schedule freeze: dispatch + pin streams vs "
                       "a golden (scheduler)"),
    "test/tb_pinrange.v": ("NOT_TIMING", "pins outside the real range (structural)"),
    "test/tb_rowmux.v": ("NOT_TIMING", "the store's row-read tree alone: combinational, "
                         "no clock and no peer (structural)"),
    "test/tb_reload.v": ("NOT_TIMING", "a reload is a clean slate (state reset); "
                         "its peers only complete transactions, no timing claim"),
    "test/tb_smoke.v": ("NOT_TIMING", "load port + pins move (smoke)"),
    "test/tb_status.v": ("NOT_TIMING", "the two host status bits (structural)"),
    "test/tb_store_latch.v": ("NOT_TIMING", "the latch store alone: power-up fill, both "
                              "read ports and the read-after-write / shared-read checks, "
                              "inputs on negedges by design; no peer, no phase claim"),
    "test/tb_tx.v": ("NOT_TIMING", "two TX lanes interleave their own bytes (host data path)"),
    "test/tb_verdict.v": ("NOT_TIMING", "the arm-verdict pipeline must-fire (exists to fail)"),
    "test/tb_w.v": ("NOT_TIMING", "Theorem 3 on the bench: the port ledger (scheduler)"),
    "test/tb_witness.v": ("NOT_TIMING", "the prefetch-stall witness chain (scheduler)"),
}
