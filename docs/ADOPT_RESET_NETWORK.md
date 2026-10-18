# Adopting the reset-network halt — notes and evidence

The engine's halt moved from a synchronous `else if (!run)` branch in every
register to **one reset flop in the top**: `eng_rst_n`, async-cleared by the
synchronized power-on reset, otherwise `<= eng_run`. The keep-list flags
(`l_timeout`, underrun, overflow) became `*_m` flops with power-on-only twins
`*_k`, read back as `twin | flag` under the old names. This file records what
the adoption was measured against and what changed.

## Why (Wilson's attribution)

#11's halt-clear fan-in into every register spread the placement; the loss is
wire load, not cells. Canary (a): slow setup +0.6085 ns; control with #11
reverted: +3.36 ns.

## Timing ledger (ship setting: density 60 %, `RUN_POST_GRT_RESIZER_TIMING: 1`, `GRT_RESIZER_HOLD_SLACK_MARGIN` 0.10)

Measured with the flow config whose hardening keys hash to
`dada746cd015f3ce…` (`model/timing_of_record.json`). `model/gate_flow_config.py`
fails if the tree's `src/config.json` drifts from it. That is how the
hold-fix gap was found: the two settings above were missing from the lock
branch until 10-17.

| layout | slow setup (ns) | worst hold (ns) | hold endpoints < +0.10 | hold buffers added by the post-GRT step |
| --- | --- | --- | --- | --- |
| reset network, 57 % | +1.87 | +0.106 | 0 | 22 (~359 µm²) |
| reset network, **60 %** | **+2.68** | +0.105 | 0 | 35 (~572 µm²) |
| reset network, 63 % | +1.78 | +0.101 | 0 | 29 (~474 µm²) |
| (b4) + reset network, 60 % | +2.33 | +0.103 | 0 | 13 (~212 µm²) |
| (a) old halt, 60 % | +0.447 | +0.107 | 0 | 18 (~392 µm²) |

- Must-fire for the endpoint check: the same probe on the setting-off canary
  finds 32 endpoints under +0.10, 3 failing (worst −0.020 ns, fast corner).
- **Planning number: +1.78 ns (worst density), placement noise ≈ ±0.7 ns.**
  57 % moved +0.66 ns from a change that cannot improve setup.
- **(a) vs (b4):** (b4) lost on timing (+2.33 against (a) +2.68; its bar was
  +3.38, i.e. (a) plus the noise band); gates not run on (b4).
- **(a) with the old halt does not meet the bar at margin 0.10 (+0.447).** The
  mux halt is therefore **no longer a fallback**: the reset network is required.
- Probe: `probe_c1/probe_h10r_report.sh` (+ `probe_h10r_paths.tcl`).

## The +1-cycle start and the re-records

The engine leaves reset one flop after `eng_run`, so it starts one cycle later
than the mux halt did. `test/check_reset_shift.py` (`1a30f2f`) proved, on full
traces at `afaf8b5` and `2bf4d23`, that nothing else moved:
`RESET-SHIFT: 12 identical, 15 shifted +1, 0 other` — six must-fires red
(`probe_reports/probe_reset_shift_2bf4d23.log`). `model/a2/sweep_w.json` was
first misclassified as identical; the checker caught it and it was reclassified
with a prediction stamped before the run (`probe_reports/probe_sweep_prediction.txt`).

- `test/cj_measured.txt` re-recorded (`bd04d1a`): hdr_cyc 94 → 95, jobs
  344 → 343, svc_cycles 687 → 686; the run at NCYC + 1 reproduces the old counts.
- `model/a2/sweep_w.json` re-recorded (`c2bbf6e`): byte-identical to an
  independent run at the same RTL; `warm_from` +1 on all 80 arms, verdict
  fields unchanged.

## Start-up latency — the evidence for HOST_INTERFACE's formula

`docs/HOST_INTERFACE.md` states the start-up as
**96 + 4R + S cycles** from PROG sampled low to the first dispatch. Each term
was measured on the 12 shipped admissible images (RTL `2bf4d23`, iverilog,
`tb_lock`, first load after power-on):

| step | measured | on |
| --- | --- | --- |
| `prog_s` low → `eng_rst_n` | 1 | 12 of 12 |
| `eng_rst_n` → `hdr_done` | 91 = 1 + 3 × 5 × 6 | 12 of 12 |
| `primed` → first dispatch | 1 | 12 of 12 |

**Priming, predicted from the image bytes alone, then compared.** The predictor
reads each header's `D_sched` and `base` and the first action at `base`, takes
the winner as the smallest `D_sched` (ties to the lowest index: at `hdr_done`
every key is `D_sched` because `now` and every timestamp are 0), and replays the
prefetch scan. The traces were logged separately and compared only at the end:

| image | D_sched per lane | winner (pred / RTL) | R | S | 4R + S + 1 | measured |
| --- | --- | --- | --- | --- | --- | --- |
| smoke_image | 40,60,200,200,200 | 0 / 0 | 7 | 1 | 30 | 30 |
| stress_image | 50,62,200,200,200 | 0 / 0 | 7 | 1 | 30 | 30 |
| half_image | 48,48,200,200,200 | 0 / 0 | 7 | 1 | 30 | 30 |
| census_image | 50,50,200,200,200 | 0 / 0 | 7 | 1 | 30 | 30 |
| corpus_i2c | 140,200,200,200,200 | 0 / 0 | 6 | 0 | 25 | 25 |
| i2caddr_image | 124,200,200,200,200 | 0 / 0 | 6 | 0 | 25 | 25 |
| i2cframe_image | 124,200,200,200,200 | 0 / 0 | 6 | 0 | 25 | 25 |
| rxfast_image | 48,200,200,200,200 | 0 / 0 | 6 | 0 | 25 | 25 |
| ckheavy_image | 60,62,64,4,4 | **3 / 3** | 10 | 1 | 42 | 42 |
| ckfive_image | 50,90,240,255,120 | 0 / 0 | 10 | 1 | 42 | 42 |
| ckod_image | 66,120,240,255,200 | 0 / 0 | 9 | 1 | 38 | 38 |
| ckread_image | 140,200,200,200,200 | 0 / 0 | 6 | 0 | 25 | 25 |

12 of 12 match on the winner, the full refill order and the total.
`ckheavy_image` is the discriminating case: lanes 3 and 4 tie on the smallest
`D_sched` and the tie rule picks lane 3, as the RTL did.

⚠ An earlier version of this check counted R and S from the same trace whose
length it compared; that cannot fail and was withdrawn. ⚠ The predictor and the
trace probes are scratch scripts, not yet tracked.

**The worst case for any legal program: 4R + S ≤ 41, so start-up ≤ 137
cycles.** Every lane is live after the header load (`pe_engine.v` sets `live`
unconditionally), and `now` does not advance until `primed`, so the winner is
fixed for the whole of priming. The only free inputs are the winner (5) and
which lanes start on a chaining REARM (2^5): all 160 cases replayed with the
predictor above. Maximum 41 (R = 10, S = 1, no chaining heads, winner 0–3); S
reaches 5 only where chaining heads cut R by more. `ckheavy_image` sits exactly
at the bound.

**Reload, measured.** `tb_reload` (the `run_reload.py` arms) loads twice; every
release was timed from the synchronised `prog_s` falling to the first dispatch
and compared with the formula for the image being loaded (94 + 4R + S from
`prog_s`; the pad adds the 2 synchronizer cycles):

| arm | first load | reload | predicted |
| --- | --- | --- | --- |
| tx5, tx1, tx8 (uart_tx → uart_tx) | 119 | 119 | 119 (R 6, S 1) |
| rx (uart_rx → uart_rx) | 119 | 119 | 119 (R 6, S 1) |
| rx2tx (uart_rx → uart_tx, a different program) | 119 | 119 | 119 (R 6, S 1) |

Both UART images have the same R and S, so these arms show the reload path
equals the first load; they add no new discriminating image (`ckheavy_image`
is that case).

## Found while measuring the SPI receive window

- **The synchronous release is not the worst case for this scheduler.** On the
  five-lane admissible image, the maximum lateness (9, equal to the bound) came
  with the SPI subject 3 cycles behind the locked 25-cycle neighbour; all lanes
  aligned gave 7. Critical-instant reasoning doesn't carry over: future timing
  sweeps must cover release offsets.
- **Feed limit, found by a probe.** `tb_trace`'s `+FEEDN` is documented as ≤ 16
  (host_feed's `HF_PAT`) but not enforced. A 30-byte feed ran silently with 14
  bytes sent as 00. The probe's own fix stayed in the scratch probe; the bench
  now refuses it: `tb_trace.v` FATALs on `+FEEDN` above `feedv`'s 16 bytes, and
  `run_mutants.py` holds the must-fire (+FEEDN=17 red, +FEEDN=16 clean).

## Bench races (audit #3)

- **The +1-cycle start is confirmed independently of the simulator.** Under
  Verilator the original `tb_smoke` read `hdr_done` 94 / `jobs` 344, the
  pre-reset-network values: a bench race was swallowing the change's +1 cycle.
  With the race-free bench both simulators read 95 / 343, the committed
  `cj_measured` values. The checker's evidence had been iverilog-only.
- **What was fixed.** Blocking writes to chip inputs right after a rising edge,
  in `tb_edge`, `tb_smoke`, `tb_pinrange`, `tb_status` and `tb_reload`, now land
  on the falling edge. Two were hidden behind task calls: `tb_edge`'s peer-edge
  writes after `run_cycles`, and `tb_reload`'s PROG raise inside
  `write_image`, which made Verilator report a false host-channel push in load
  mode. Every iverilog output is byte-identical before and after (17 arms), and
  Verilator now matches iverilog on every arm of these benches and on `tb_lock`
  and `tb_w`. Remaining flagged sites are benign by construction (data nibbles
  read only at the synchronised WR edge: `tb_fifo`, `tb_v2win`) or deliberate
  (`tb_half`'s `+PLANT_EDGE_RACE`).

## HOST_INTERFACE, audited against the readout path

"HOST_INTERFACE complete" means **audited against the readout path**: every
claim of the form "the host can see / read / learn X" traced to a status-byte
bit or a pin. This table is the record.

| claim | readout |
| --- | --- |
| why the part is silent after a short load | status bit 5; `cfg_err_any` includes `short_load` (`project.v`) |
| a CONFIG_ERR is seen | bit 5 |
| overflow is reported in the stream | bit 2 (RX overflow), bit 6 (RX-drop) |
| a collision is reported, never silent | bit 6 RX-drop; measured by `run_rxbw.py` |
| the host can verify what it loaded | load-mode frames, kind 7 |
| a full queue is reported | bit 4 TX-full |
| which lane a received byte came from | `kind` = the receiving lane |
| clock-stretch fault | bit 7 |

Four claims did not trace, and each was corrected in the doc (behaviour is as
designed):
- **What is kept on a reload:** it listed `l_timeout` and "per-lane"
  underrun/overflow as the host's to read. A timeout reaches the host only as
  bit 3 (`ovr`), which every engine fault sets; underrun and overflow are
  OR-ed across lanes. Now stated as a limitation: the host cannot identify
  which lane timed out, underran or overflowed.
- **Liveness:** "frames alternate, so liveness is in the stream" is false in
  run mode; an idle chip is silent. Now stated as a limitation: a host cannot
  tell an idle chip from a dead one through the stream. A self-made heartbeat
  recipe is not documented, because no bench demonstrates one.
- **Reading past the loaded region returns X:** a simulator value, and under
  the full-store rule there is no unloaded region in a run the chip accepts.
- **Underrun "per lane":** recorded per lane, reported OR-ed.

`l_timeout_k` (and the per-lane `l_timeout` register) have no logic reader;
host timeout visibility is via `sticky_ovr`; both are expected to be pruned in
synthesis; removal deferred to after the lock. `gate_halt_reset`'s keep-list
says the same. Nothing at gate level names `l_timeout` (the only references
are an RTL bench and an RTL source-text check), so pruning breaks nothing.

Per-lane status, an idle-slot heartbeat and the `l_timeout` removal are on the
post-lock reach list, `docs/REACH.md`, with the rest of the branch.

## Still owed for the lock

- the `model/a2/sweep_w.json` re-record once `src/` is final: the
  `src/pe_engine.v` comment edit (HDR_BITS 48, rtl_equiv proven) moved only its
  source hash; predicted data byte-identical, checked by diff
- `test/gate_coverage.py` running and green (re-anchor via `model/reanchor.py`)
- the full gate run, then the commits (docs / tests / `src/`)
- CE5 full re-certification, then the harden of record

Done since this list was first written: the adoption edits (the PORT_SPEC §7
anchor, `tb_edge.v`'s timeout check, the benchset `+IMG0` declaration, the
`src/pe_engine.v` comment with its equivalence proof), the HOST_INTERFACE
audit and corrections, `docs/REACH.md`, the bench-race fixes with
`gate_bench_race` and `gate_xsim`, and the `tb_trace` feed guard.
