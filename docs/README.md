# Documentation

The specifications, the timing analysis and its proofs, and the record of how the
design got here. If you read only three, read the first three.

- [Start here](#start-here)
- [Timing analysis and proofs](#timing-analysis-and-proofs)
- [Pre-registrations](#pre-registrations)
- [Design record](#design-record)
- [Verification method](#verification-method)
- [Working logs](#working-logs)

Documents in the last three groups are dated records: they say what was true and
decided at the time, and a later document may supersede a number in an earlier
one. The CI gates (`ci/run_gates.sh`) are the current truth.

## Start here

| document | what it is |
|---|---|
| [HOST_INTERFACE.md](HOST_INTERFACE.md) | pins, the program-load protocol, serial framing, the readback contract |
| [PORT_SPEC.md](PORT_SPEC.md) | the fetch port and dispatch pipeline, read from the RTL |
| [J_LANE_PROOF.md](J_LANE_PROOF.md) | the per-lane jitter bound, argued from the RTL, and where the argument stops |
| [info.md](info.md) | the Tiny Tapeout datasheet page |
| [PIN_FIELDS.md](PIN_FIELDS.md) | which pin field each datapath reads |
| [RUNG4_CONVENTION.md](RUNG4_CONVENTION.md) | the scheduler convention the RTL implements |
| [SILICON_EVIDENCE.md](SILICON_EVIDENCE.md) | post-place-and-route numbers from an earlier, smaller build, and how to read them; superseded by the timing of record |
| [ADOPT_RESET_NETWORK.md](ADOPT_RESET_NETWORK.md) | the reset-network halt and its timing evidence (the timing of record) |
| [REACH.md](REACH.md) | what the design could do next, beyond what it claims |

## Timing analysis and proofs

| document | what it is |
|---|---|
| [A2_FRAMEWORK.md](A2_FRAMEWORK.md) | the non-preemptive EDF framework, from the literature |
| [A2_BRIEF_FOR_WILSON.md](A2_BRIEF_FOR_WILSON.md) | everything extracted from the scheduling papers, in one place |
| [SPURI_RR2772_EXTRACT.md](SPURI_RR2772_EXTRACT.md) | extract of Spuri (1996), *Analysis of Deadline Scheduled Real-Time Systems* |
| [A2_GREEN_RESULTS.md](A2_GREEN_RESULTS.md) | the response-time analysis, parts 1–3 |
| [A2_CLOSE_RESULTS.md](A2_CLOSE_RESULTS.md) | the tolerated response `D_i` derived, and the analysis closed against it |
| [SPEC_V4_RULINGS_J_AND_BOUND.md](SPEC_V4_RULINGS_J_AND_BOUND.md) | jitter becomes a function of the program; pyRTA becomes the primary bound |
| [SPEC_V4_J_SOUND.md](SPEC_V4_J_SOUND.md) | the jitter-sound analysis pipeline |
| [SPEC_V4_J_LANE_AND_SPL.md](SPEC_V4_J_LANE_AND_SPL.md) | the per-lane jitter term and the slot count |
| [SPEC_V4_C_SATURATION.md](SPEC_V4_C_SATURATION.md) | the service time `C` under saturation |
| [TA01_RESULTS.md](TA01_RESULTS.md) | UART conformance as a decidable timed-automata query |
| [TA01bc_RESULTS.md](TA01bc_RESULTS.md) | the infinite run, and a timing band computed rather than tested |
| [TA02_RESULTS.md](TA02_RESULTS.md) | a generic table interpreter as timed automata, and two defects it found |
| [TA02_FORWARD_PLAN.md](TA02_FORWARD_PLAN.md) | the timed-automata plan at the time |

## Pre-registrations

Each question was written down, with what would count as an answer, before it
was measured.

| document | the question |
|---|---|
| [ARCH_PREREG_01.md](ARCH_PREREG_01.md) | the architecture |
| [PREREG_C_SAT.md](PREREG_C_SAT.md) | is the service time `C` 2 or 3 under saturation? |
| [PREREG_C_CLOCKED.md](PREREG_C_CLOCKED.md) | `C` under the self-clocked `SHIFT` |
| [PREREG_J_LANE.md](PREREG_J_LANE.md) | the per-lane jitter term |
| [PREREG_U_PORT.md](PREREG_U_PORT.md) | is the real condition fetch-port utilisation rather than uniform spacing? |
| [SCALING_EVIDENCE_PLAN.md](SCALING_EVIDENCE_PLAN.md) | the scaling-evidence plan, and the couplings it has to respect |

## Design record

How each part of the design was specified, built and corrected.

| document | what it is |
|---|---|
| [SPEC_V4_S0_S1_RESULTS.md](SPEC_V4_S0_S1_RESULTS.md) | spec v4, stages S0 and S1 |
| [SPEC_V4_S2_SPEC_FREEZE.md](SPEC_V4_S2_SPEC_FREEZE.md) | spec v4, S2: the spec freeze |
| [SPEC_V4_S3_ENGINE.md](SPEC_V4_S3_ENGINE.md) | spec v4, S3: the engine |
| [SPEC_V4_PHASE2_FLAGBACK.md](SPEC_V4_PHASE2_FLAGBACK.md) | phase 2, derived and checked before building |
| [SPEC_V4_DOUBLE_BUFFER.md](SPEC_V4_DOUBLE_BUFFER.md) | the double-buffered prefetch, and what measuring it found |
| [SPEC_V4_EDGE_CAPTURE.md](SPEC_V4_EDGE_CAPTURE.md) | edge capture: the reactive direction |
| [SPEC_V4_CLOCKED_HIGH_PHASE.md](SPEC_V4_CLOCKED_HIGH_PHASE.md) | the clocked SCL high phase, and a checker that was blind to timing |
| [SPEC_V4_SHIFT_AUDIT.md](SPEC_V4_SHIFT_AUDIT.md) | the `SHIFT` audit, and a clock pin equal to its data pin |
| [SPEC_V4_SPLIT_BITP.md](SPEC_V4_SPLIT_BITP.md) | splitting the bit pointer |
| [SPEC_V4_T51_TX_INTERLEAVE.md](SPEC_V4_T51_TX_INTERLEAVE.md) | TX interleave, and a channel nothing had ever driven |
| [SPEC_V4_RX_LANE_ID.md](SPEC_V4_RX_LANE_ID.md) | RX lane identity, the mirror of the TX tag |
| [SPEC_V4_SERIAL_BW.md](SPEC_V4_SERIAL_BW.md) | the serial link's bandwidth, re-derived at 12 bits |
| [SPEC_V4_R0_PINMAP.md](SPEC_V4_R0_PINMAP.md) | the host data channel against the pin map |
| [SPEC_V4_D1_D2.md](SPEC_V4_D1_D2.md) | the per-pin drive-class rule, which had never been built |
| [SPEC_V4_RULING_AUDIT.md](SPEC_V4_RULING_AUDIT.md) | an audit of every design decision against the RTL |

## Verification method

| document | what it is |
|---|---|
| [SPEC_V4_TWO_SIM.md](SPEC_V4_TWO_SIM.md) | the two-simulator cycle-exact comparison, and the seed sweep behind the reset allowlist |
| [SPEC_V4_CORPUS.md](SPEC_V4_CORPUS.md) | widening that comparison to a protocol corpus |
| [SPEC_V4_COVERAGE_SWEEP.md](SPEC_V4_COVERAGE_SWEEP.md) | the coverage sweep: what has never run |
| [SPEC_V4_COCOTB_REWRITE.md](SPEC_V4_COCOTB_REWRITE.md) | the cocotb suite, rewritten, and two defects it measured |
| [SPEC_V4_I2C_CERTIFIED.md](SPEC_V4_I2C_CERTIFIED.md) | an I²C frame certified by sigrok, and two defects in our own peer model |
| [SPEC_V4_REVERSE_TRACE.md](SPEC_V4_REVERSE_TRACE.md) | reverse traceability, and the golden model it needed |
| [SPEC_V4_R2_FLOW_CROSSCHECK.md](SPEC_V4_R2_FLOW_CROSSCHECK.md) | the hardening flow's netlist as a second authority on the reset audit |

## Working logs

Chronological, kept as written.

| document | what it covers |
|---|---|
| [PHASE1_CLOSEOUT.md](PHASE1_CLOSEOUT.md) | phase 1 close-out, part 1 |
| [PHASE1_CLOSEOUT_PART2.md](PHASE1_CLOSEOUT_PART2.md) | part 2: the first rulings and the drive-class rule |
| [PHASE1_CLOSEOUT_PART3.md](PHASE1_CLOSEOUT_PART3.md) | part 3 |
| [PHASE1_CLOSEOUT_PART4.md](PHASE1_CLOSEOUT_PART4.md) | part 4: the pin conflict, and the memory decision |
| [PHASE1_CLOSEOUT_PART5.md](PHASE1_CLOSEOUT_PART5.md) | part 5: SRAM provenance, and the product call |
| [PHASE1_CLOSEOUT_PART6.md](PHASE1_CLOSEOUT_PART6.md) | part 6: the MISO catch, and the harden gate |
| [PHASE1_CLOSEOUT_PART7.md](PHASE1_CLOSEOUT_PART7.md) | part 7: release fixed in hardware |
| [RESUME_CLOCKED_ARC.md](RESUME_CLOCKED_ARC.md) | the clocked-`SHIFT` arc, with every ruling in order |
| [CE5_LOG.md](CE5_LOG.md) | 1-Wire (DS18B20) on the frozen RTL: an expressiveness log |
