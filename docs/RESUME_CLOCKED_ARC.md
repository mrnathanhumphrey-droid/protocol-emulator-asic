# RESUME — the clocked-SHIFT arc

⏭ **Read this first, then `docs/SPEC_V4_CLOCKED_HIGH_PHASE.md`.** Branch `dev`.
Every item below is a Wilson ruling relayed by Nathan; relaying is approval,
including commit and push.

---

## Landed

| arc | SHA | what |
| --- | --- | --- |
| `d_min` over refill-bearing dispatches | `752fd7a` | FRAM write 81 / read 50, J=1, two-route cross-check |
| F1–F4, G1, G2, C1, C2 | `6abb6dd` | high phase counted from the observed rise; +0 flops |
| clocked I2C lane in A2 | `ea0259f` | `D_tol = d − t_LOW(min)`, fixed point 33/73/249 |
| H1–H5 + the clamp | `2120012` | SDA hold 15 cy, +30 flops, `t_HD;DAT` 0 → 15 |
| A1 / A2 | `e1fa642` | head-slot stability; gap bounded both sides |
| Ruling P | `80ff8d7` | pad-override explanation; P4 control re-established |
| Ruling D (D1, D3–D6) + P5 + D2's static half | `1f00768` | `d <= SDA_HOLD` refused in silicon and in the assembler; +0 flops |
| the CI red local could not see | `d5ae9bc` | `tb_trace`'s 64-byte filename buffer; **CI green both workflows** |
| Ruling R — the port premise | *this commit* | Layer R + `gate_port_demand`; `M_CK_HOLD_INVAL` is no longer a survivor |

**21 of 21 gates** (ruling R added `model/gate_port_demand.py`), 26 uncovered
(all classified, the same 26 points as at `80ff8d7`), 37 arms / 14 benches.

⛔ **"Green" means CI on the exact SHA, both workflows, with the run ID written
here** (ruling CI1). A local pass is reported as local.

| SHA | `test` | `docs` | note |
| --- | --- | --- | --- |
| `6abb6dd` … `80ff8d7` | ❌ **FAILURE** ×5 | ✅ | 19 of 20, `gate_um10204` CANNOT-RUN — see the CI section below |
| `1f00768` | ❌ FAILURE | ✅ | same cause; superseded |
| `d5ae9bc` | ✅ `37545309988` | ✅ `37545310031` | **first `test` green since `752fd7a`** |
| `43575eb` | ✅ `37548607991` | ✅ `37548608000` | 21 of 21; CI ran `gate_port_demand` on real data (mutant red at 17 vs bound 2) |
| `775b6bc` | ✅ `37555388505` | ✅ `37555388522` | R4 + R5 |
| `992c298` | ❌ `37558472597` | ✅ `37558472654` | ruling S, **20 of 22**: pyRTA-dependent checks put in CI, where pyRTA is absent by design. Passed locally only via a scratch pyRTA clone. Fixed in the next commit. |
| `2e6c118` | ✅ `37560421145` | ✅ `37560421167` | S fixed; 22 of 22 with pyRTA absent |
| `de38c55` | ❌ `37565855366` | ✅ `37565855370` | Q2 + CI3, **23 of 24**: the restored corpus witness's `two_sim_trace.sh` wrote its scratch to a hardcoded `/mnt/c/tmp/` -- present under WSL, absent on CI's Linux -- so both normalised traces were empty and every program "disagreed" on 0 lines. A local run cannot catch it (WSL has `/mnt/c`). Fixed with `mktemp` in the next commit. The long-path arm passed in CI. |
| `47bc387` | ❌ `37568512542` | ✅ `37568512633` | **6 of 8 on the witness**: all four corpus programs CYCLE-EXACT in CI, but the async-clear arm disagreed on 666 lines of `uio_in[6]` (CS, bench-driven) from cycle 22. |
| `f8f952c` | ❌ `37570517654` | ✅ `37570517688` | ⛔ **a wrong diagnosis, disproved by CI.** I took it for a race between the trace sampler and blocking stimulus writes on the same negedge and made the stimulus non-blocking; the identical 666 lines disagreed again. The real cause: `verilator_trace.sh` called a bare `verilator`, which in CI is apt's **5.020** -- CI keeps the pinned **5.053** off PATH and names it in `PE_VERILATOR`. CI's Icarus matched the local trace exactly; it was CI's Verilator that saw CS rise a cycle late. Fixed in the next commit; the non-blocking change is kept (the race is real) but fixed nothing observed. |
| `f0aa6db` | ✅ `37572686088` | ✅ `37572686044` | the pinned Verilator in `verilator_trace.sh`; witness 7 of 8, 0 failed, in CI; 24 of 24 |
| `b97d5bd` | ✅ `37611788009` | ✅ `37611787822` | P6 + N1; 25 of 25 |
| `29bd861` | ✅ `37619713604` | ✅ `37619713637` | E+ + Q3; 26 of 26 |
| `9ebcaeb` | ✅ `37627116027` | ✅ `37627115865` | M + README (a) + RD1; 27 of 27 |
| `231b37c` | ✅ `37636453349` | ✅ `37636453287` | M5 + M6; 27 of 27 |
| `0e29fe7` | ✅ `37644777003` | ✅ `37644776920` | V + MU + CJ + M7; 31 of 31; run_a2 41 of 41 |
| `67ea17a` | ✅ `37654159229` | ✅ `37654159170` | RA1–RA3 + MF1; 33 of 33 |
| `cd57eee` | ✅ `37661287583` / `37661284834` | ✅ `37661287669` / `37661284446` | K + U + RL1; 35 of 35 |

### Silicon fixes — RTL defects closed (ledger)

| fix | defect, as silicon would show it | closed by | commit |
| --- | --- | --- | --- |
| **power-up run** | with PROG low at reset release, the engine **ran on the power-up contents of the unreset store**: a power-up glitch on real pins, before any host load. Never on the owed list; found as a side effect of M5's first cut. | `eng_run = run & store_full` (`project.v`): the engine runs only after 2^AW consecutive writes since `rst_n` | `231b37c` |
| **partial load** | a host loading fewer than 256 bytes left the rest of the store at power-up contents, one missing REARM from running on pins | the same gate, plus a release-time CONFIG_ERR (`short_load`) | `231b37c` |
| **ACK-slot release unheld** (K) | the clocked SHIFTIN released SDA in the cycle SCL fell: `t_HD;DAT = 0` into every ACK slot | the release goes through the SDA hold pipeline | `cd57eee` |
| **setup under contention** (W1) | `d > SDA_HOLD` fixed the hold, not the setup: a lane dispatched late by contention released SCL before its held data landed, so **SDA changed while SCL was high**, a START/STOP to any receiver (11 of 562 on `ckhold_over`, 10 / 3 on the unclocked frame at d = 16 / 17) | a lane is ineligible while its own hold + `SDA_SETUP` (3 cy) is pending; contention-independent; +5 flops | `c8a4126` |
| **unclocked release unheld** (W2) | the unclocked frame's SHIFTIN release held only the inter-dispatch gap minus jitter (14 at d = 16) | the release goes through the hold pipeline when it moves SDA | `c8a4126` |
| **clocked TX bytes misaligned** (TX, "silicon fix #2") | the clocked SHIFT's host load fired on the **HIGH-phase** writeback after the 7th bit (`tx_bitp == a_cnt` tested at every writeback, `tx_bitp` advancing on LOW only), so every clocked byte's 8th bit was the NEXT byte's first and the stream drifted one bit per byte: `5B` fed went out `00 B5 6A D5`. Dispatch streams exact, every timing gate green. **Not detected because every clocked check measured edges and timing, never values**; the two-simulator witness compares the simulators with each other. Found building ACK (b)–(c), the first thing to read clocked bytes | the load is gated to the LOW phase: `(!ck_shift \|\| ck_is_low)`; `M_TX_LOAD_ANYPHASE` keeps the old form. Values now checked: Layer V (V1 golden model, V2 pushed bytes), `run_cktx`, cocotb pins-only test | TX commit |
| **clocked SHIFTIN sampled the header pin** (PN, "silicon fix #3a") | a clocked SHIFTIN sampled the lane HEADER's data pin (`l_pin`), not the ACTION's (`a_pin`): an SPI master (header MOSI, SHIFTIN on MISO) read its own MOSI line -- `corpus_spim`'s READ received `00` while the FRAM drove `5B C4`. **Hidden because every clocked receive ever tested was open-drain I2C, where action pin == header pin** and the two readings agree. ⚠ Two same-hand checks shared the blind spot: `pe_asm`'s alias check tested the header pin (the RTL and the assembler disagreed on receive-pin semantics, and neither noticed), and Layer V2 sampled the header pin | `ck_rpin` = the head slot's action pin (`l_act[hix][...]`, zero flops, sound by A1); `M_CKRX_HEADER_PIN` keeps the old form. Layer V-RX (all benches: chip RX frames == bits on the action's pin) and `run_spifram` kill it; `pe_asm` alias check + V2 on the action pin with must-fires where action pin != header pin; `gate_pin_matrix` (every pin-taking class run with action pin != header pin) | fix #3 commit |
| **push-pull clocked receive never captured** (CI, "silicon fix #3b") | a clocked SHIFTIN waited for an OBSERVED rise of its clock pin; a push-pull master's SCK sits on `uo_out`, whose `pin_in` / `pin_rise` are tied low (`project.v`), so the capture never fired and every bit read `0` -- even with (a) fixed. `ckfive` lane 4 (push-pull receive) never captured either; nothing checked its values. **Same root as (a): only open-drain clocked receives were ever value-checked** | push-pull lanes capture at the engine's OWN rise: a 6-flop slot (`ppc_v/l/n`) set at the HIGH-phase writeback fires at pad rise + 2 (DRIVE + 3 on `uio`, + 4 on `uo_out`); open-drain keeps the observed rise (`run_ckack` byte-identical). The instant is in HOST_INTERFACE in ns against the MB85RS64V table; `run_spidelay` measures the MISO-delay edge at d − 1 as predicted. `M_CKRX_PP_OBSERVED` keeps the old form, killed by V-RX, `run_spifram`, and the cocotb pins-only SPI read (gl_test) | fix #3 commit |

⛔⛔ **T4 — WHAT `d2b7d34`'s "GATE-LEVEL-VERIFIED" COVERED.** It covered
**function**: gl_test 8 of 8 and precheck passing (gds 37287797590). It did
**not** cover timing. At the slow corner (1.08 V, 125 °C) and 50 MHz, setup WNS
was −5.44 ns over 53 paths (TNS −228.9). Every path ran from `u_eng.now[0]`
through the serial EDF argmin into the dispatch registers, about 26 ns against
20. Typ and fast were clean. Utilisation was 49.3%, not "~10%". Ruling T makes
closing every signoff corner at 50 MHz, or an explicit measured
operating-condition scope, a **lock criterion**.

---

## OWED — Wilson's order

harden (gds 37678507030 on `c8a4126`) → **T1 + T2** report → commit
**Y-R / Z / DT / A** → T fix plan (Nathan's call) → `E` → D* sweep + live
window check (P9w under contention) → ACK (b)–(c) → sigrok re-certification →
FRAM write + random read → pe_asm protocol front-end → lock.
**Lock criteria now include T3:** setup and hold met at every signoff corner at
50 MHz, or an explicit, measured operating-condition scope carried into every
timing claim.

| item | what | state |
| --- | --- | --- |
| **R** | port-demand invariant (a RATE) | ✅ landed |
| **R4** | Theorem 3's P10 + P1 checked VERBATIM; own mutant | ✅ landed |
| **R5** | refill-bearing dispatch attribution; §1 stands (case a) | ✅ landed |
| **S** | the A2 bound, per program; D2's mode floor on the same machinery | ✅ landed — SPEC §16 |
| **D\*-window** | Theorem 3's CONCLUSION live: sliding window of `d` cycles counting refill requests at the port, asserted `<= k` on every feasible-at-J=1 arm; must-fire on an infeasible arm (`corpus_all5`). Premise (R4) + conclusion (window) = the whole theorem on the bench. **Goes in the existing `D*` sweep step — not new work now.** | owed (Wilson, after R5) |
| **Q2** | `gate_corpus_trace` built, portable, in CI; GATES completeness | ✅ landed — SPEC §17 |
| **CI3** | every bench's name buffer 256, loud load check, >128-byte arm, lint rule | ✅ landed — SPEC §17 |
| **P6** | pyRTA pinned at `1f3a649`, enforced, printed everywhere; reproduces `65bc3c8114e5` exactly | ✅ landed — SPEC §18 |
| **N1** | non-admissible images declared (OVERLOAD / PORT / PINMAP), derived from each image; found `five_image` overloaded + 9 more below D* | ✅ landed — SPEC §18 |
| **E+** | exit codes mechanical: pipefail enforced, `ci/rc.sh` run_rc, `gate_shell_rc` lint, must-fires | ✅ landed — SPEC §19 |
| **Q3** | `five_image` as evidence: **mechanism only**; every claim-bearing run point admissible | ✅ landed — SPEC §19 |
| **M** | unreset store: full-store images, defined filler, audit, PC-reach report, load-time report | ✅ landed — SPEC §20 |
| **README (option a) + RD1** | ledger numbers only (lane table C 2→3, SPI-target D_tol 18→17, r row, margin 12→11), universal `J = 8` row + its sentence removed, scoped `d_min ≥ D* = 20 → J = 1` stated; `gate_stored_numbers` now audits the README | ✅ landed — SPEC §20; ⚠ framing/prose untouched, still Nathan's (F7b) |
| **M5** | silicon refuses a partial load: consecutive-write counter, engine gated on `store_full`, release-time CONFIG_ERR; `M_NO_STORE_FULL` must-fire | ✅ landed — SPEC §21 |
| **M6** | loud filler: no lane-independent dispatch refusal exists → `feffc0` kept, "escape parks silently" recorded | ✅ landed — SPEC §21 |
| **V** | one resolver per language (`ci/tools.sh`, `toolchain.tool()`), banners everywhere, `gate_tool_pinning` (must-fire: `verilator_trace.sh` @ `f8f952c`); witness REQUIRES the 5.053 banner; manifest + local WSL calls now carry the pin | ✅ landed — SPEC §22 |
| **MU** | `gate_mutant_kills`: 29 defines, 25 killed in CI, 1 in run_a2, 3 declared survivors; `run_mutants` into CI with a clocked family; `gate_f2_local` (M_COMB_OUT on the real netlist); Layer R cross-block race fixed | ✅ landed — SPEC §22 |
| **CJ** (`gate_cj_bounds`) | RETIRED with a per-claim pointer; `gate_gates_complete` RETIRED class; `gate_c3_requote` J = 8 relabelled as the retracted stress point | ✅ landed — SPEC §22 |
| **RA1/RA2** | racy-R numbers re-measured, iverilog + Verilator, 5 images × 3 builds: **identical**; clean 1/1/2/1/1, kills 16/16/17, orthogonality stands; SPL confirmation stands | ✅ landed — SPEC §23 |
| **RA3** | `gate_bench_races`: same-edge cross-block blocking reads red unless declared; must-fire = Layer R @ `231b37c` | ✅ landed — SPEC §23 |
| **MF1** | `gate_manifest`: committed manifest vs files in CI; must-fires: flipped byte, empty, the stale `231b37c` manifest | ✅ landed — SPEC §23 |
| **RL1** | Verilator lint on src/ in CI, BLKSEQ/COMBDLY errors except a checked block-local temporary (`prime_unp`); must-fires planted | ✅ landed — SPEC §24 |
| **K** | clocked SHIFTIN release held (hold pipeline); Layer H attributes every chip SDA move; K2 table with required cells (new `ckread_image` for ACK/NACK); K3 `M_SHIFTIN_UNHELD`; K4 corpus_i2c arm in phases_run, min 15 over 217 | ✅ landed — SPEC §24 |
| **U** | refusal widened to the unclocked clock-low SHIFT; clamp retired; pe_asm + dgf mirrors; i2cframe d=15 refused, d=16 runs; `M_HOLD_CLOCKED_ONLY` | ✅ landed — SPEC §24 |
| **W1** | (b) chosen: a lane is ineligible while its own hold + `SDA_SETUP` (Fm+ 50 ns → 3 cy) is pending; one counter (load 18, pin at 4); `ready = rel_due & hcnt == 0`; only releases that move SDA load; Layer H reds data moves with SCL released | ✅ landed — SPEC §25 |
| **W2** | unclocked SHIFTIN/READBIT release through the hold pipeline (14 → 29 at d = 16) | ✅ landed — SPEC §25 |
| **W3** | (c) rejected | — |
| **W4** | ckhold_over + i2cframe d = 16/17/18: 0 data moves with SCL released, holds ≥ 15, setup ≥ 5; W1 binds **0** on every mode-legal image | ✅ landed — SPEC §25 |
| **W5** | `M_NO_HOLD_GATE` reproduces 11/562 and 10/3; `M_SHIFTIN_UC_UNHELD` reproduces 14 | ✅ landed — SPEC §25 |
| **W6** | W1 binds on ckdense (A2-admissible): carried as release jitter `J_w1 = max(0, HS + 1 + r_i − C − T_i)` by fixed point; measured ≤ derived; pyRTA now exceeds ours on every ckdense lane (its D−J framing double-counts J). W1 also stopped ruling S's must-fire firing (widest 8 = the light budget) → **ckdense re-spanned 22..25 → 20..23** (widest 10 again). P9 re-anchored to `rel_due`, W1 gate added as P9w; Theorem 3 scope on unclocked frames recorded for the D* sweep | ✅ landed — SPEC §25 |
| **W7** | mode floor covers unclocked OD frames (t_LOW, t_HIGH, t_SU;DAT); i2cframe d = 16 refused, d = 62 Fm+ | ✅ landed — SPEC §25 |
| (opt) | `ckdense` margin: a heavier feasible variant firing on several releases | non-blocking |
| **M7** | HOST_INTERFACE: the full-store rule binds the FIRST load after `rst_n`; partial reloads after it run | ✅ landed |
| **Y-R** | "pyRTA double-counts jitter" WITHDRAWN (TChecker: D − J exact 8/8, charge-once below truth 5/8); wrapper unchanged | ✅ landed `372ca6e` — SPEC §26 |
| **Z** | our recurrence gets Spuri's full candidate set (old search below TChecker on 7/8; 184/6,601 at J = 0); `gate_spuri_candidates` (CI), `zone/run_z.py` (24/24) | ✅ landed `372ca6e` — SPEC §26 |
| **DT** | 1.6a per program (r_i ≤ t_i, measured vs TChecker); QUEUE condition; ckdense + ckhold_over non-admissible; ckheavy is Ruling S's subject; D_sched ≤ D_tol asserted | ✅ landed `372ca6e` — SPEC §26 |
| **A** | pyRTA primary wherever published/judged; ours an asserted ≥ cross-check; README `J = 1` row 9 / 11 (ours column KEPT until the presentation rewrite — Nathan); 1.6m re-priced (pyRTA C = 3 margin 1); W1 jitter on pyRTA's side; `ANALYSIS_LEDGER`. ⚠ The universal `J = 8` withdrawal reason is MEASUREMENT, not margin: `SWEEP_LIVE` reaches **11** at d = 8..18 against a derivation capped at 7. 20 = k·L_REFILL is the chain's structural ceiling, not a measured value | ✅ landed `372ca6e` — SPEC §26 |
| **T** | 50 MHz timing closure, LOCK BLOCKER. T1 (harden 37678507030 on `c8a4126` vs `d2b7d34`): slow-corner setup WNS −5.44 → **−6.53** ns, TNS −228.9 → −293.5, violations 53 → 56; typ +3.35, fast +9.11, hold met at every corner; flops 3,127 → 3,298, utilisation 49.3% → 53.5%. T2: all 56 violating paths start at `now`, end at the dispatch (`a_*`) / prefetch (`paddr`, `fix`) registers, 67–71 cells, via ready (+W1 gate) → EDF key → serial argmin. Fix plan is Nathan's call; any argmin restructure must preserve the lowest-index tie rule, proven equal to the serial one | T1/T2 reported; fix plan owed |
| **CHECKPOINT (H-CK1–3)** | full harden (gds + precheck + gl_test) on the W dev SHA without merging; report vs `d2b7d34` | ✅ run 37678507030: gds ✅ (3 h 31), gl_test ✅ **12/12** incl. hold/setup, hold refusal, clocked park; precheck pending at time of writing; `viewer` failed as on the baseline (not sign-off). Not merged (timing fails T3) |
| **TH1** | **Theorem 3: proof gap identified (utilisation argument insufficient; slot/release mis-assignment); statement supported by measurement; formal proof in progress (Lean).** README carries `d_min ≥ D* = 20 → J = 1` as MEASURED (d = 20..60 runs) with "written proof under revision"; the window-check citation is added when TH4 runs. `gate_j_proof_anchors` keeps P1–P10 | ✅ — `J_LANE_PROOF.md` Amendment A2 |
| **TH2** | `docs/PORT_SPEC.md`: port arbitration (winner head first, then round-robin by scan pointer; branch 1 relocates the pointer), pipeline latencies (measured), slot lifecycle (refill owed at WB(j) is needed at decision(j + 2); slack ≥ 2d − R_i − 2), L_REFILL / one-in-flight, cold start | ✅ |
| **TH3** | probe `probe_tb_port.v`. Above D*: 0 stalls on 7 sweep points, 16 admissible images, adversarial and drifting arms; worst owed fill 19 issue / 23 capture, ≤ 5 served ahead, NO growth 200k → 4M. d = 18 and arm C: every stall cycle arbitration (0 pipeline, 0 cold). ⛔ Below D* (12×4 + 100) the port STARVES: 16,468-cycle wait, 2,473 refills ahead — round-robin holds only while branch 1 is silent | ✅ |
| **TH4** | the live window check (D* sweep, P9w under contention) also logs TH3a's quantities (owed-fill wait, refills served ahead), so bench and Lean check the same invariant | owed (with the D* sweep) |
| **PS1–PS3** | candidate bound `2d ≥ 37` (d ≥ 19) FALSIFIED: five lanes at d = 19 stall (the recorded "d = 19 clean" was the 19..23 recipe, one lane at 19). D* = k·L_REFILL is a THROUGHPUT floor, tight on the uniform family; latency is necessary, not sufficient. Lemma B 23 measured 24 above D*; Lemma A premise (same-lane gap > 12) false on ckheavy (gap 12); pe_asm refuses d_min < D* | ✅ landed `5cb00c1` — PORT_SPEC §6, A2 |
| **TF** (GO, Nathan) | 50 MHz fix: **TF1** registered readiness + EDF key from next-state values; **TF2** tree select; **TF3** prefetch branch 1 on `winner_q`, and it no longer moves the round-robin pointer (`prr`). **TF4:** SymbiYosys proves tree == serial (`formal/argmin_equiv.sby`; broken-tie must-fire FAILS); lockstep **1,030 / 1,035** images byte-identical incl. **1,000 random admissible**, the 5 that move are all declared non-admissible (PORT); priming +1 cycle on 995 (allowed, listed); new CI gate `test/run_lockstep.py` (12 shipped images identical, must-fire `M_TF1_LATE` moves 12/12); sub-D* starvation arm 16,468 → **53** cycles (4M, no growth); cocotb 12/12 local. Side effects, recorded: Theorem 1's `sum_L` 7 → **9** (= the bound, falsifier not fired; derivation needs re-doing with `winner_q`); overload worst stall on five_image 7 → 13 while total stall events FELL 287 → 246; M_BUF_SWAP re-witnessed on stall events, M_PFETCH_NOWAIT on liveness (X now propagates through the tree; Verilator seeds still disagree); `tb_fifo`'s phase walk was NOT exhaustive (absolute-time `phase % 23`) and missed every pop once priming moved one cycle -- now anchored to observed pops, corner hit at phase 99 on both RTLs. **TF6:** PORT_SPEC §0 + A3; Lean agent: branch 1 no longer relocates the pointer | ✅ landed `3b37967`, CI green (test 37716428870, docs 37716428802) |
| **TF5** | harden 37716433124 on `3b37967`: slow WNS −6.53 → **−3.49** ns, TNS −293.5 → −78.4, violations 56 → 28; typ +5.31, fast +10.05; hold met; 3,396 flops / 54.1%; gl_test 12/12. `now` and the prefetch regs gone from the violators; logic depth 42–44 → 23. Remaining: `l_live` → ready → tree → 10-way 24-bit action select → dispatch regs (27–28 of 50–51 cells are buffers). Implied fmax slow ~42.6 MHz, typ ~68 MHz. ⛔ My dispatch of this run CANCELLED the previous run's precheck (concurrency group, cancel-in-progress) at 2 h 39 m | ✅ reported; precheck pending |
| **TF2-R** (GO) | **R1** per-lane head pre-select `hw/hv[i] = slot[hix[i]]` — combinational, not a registered shadow (Nathan's choice: same fan-out cut, no state to drift, so R4's invariant holds by definition); **R2** one-hot winner from the tree, dispatch reads `w_act`/`w_hv`/`w_armed` through an AND-OR; **R3** `l_live`/`l_armed`/`l_notmo` writes go through next-value temporaries and the whole release term is the register `rel_q` (must-fire `M_TF2_LIVE_LATE`, killed by run_lockstep on census_image). **R5:** lockstep vs `3b37967` **1,035 / 1,035 byte-identical, priming included**; SymbiYosys one-hot == binary winner (must-fire: lane 0's line without `v01` FAILS) | ✅ landed `18f2c0e`, CI green (test 37744353295, docs 37744353096) |
| **TF2-R6** | harden **37744351928** on `18f2c0e` — gds ✅ (4 h 21), gl_test ✅ **12/12**, precheck ✅. **50 MHz CLOSES at every signoff corner:** slow WNS **+0.108 ns**, TNS 0, **0 violations** (was −3.49 / −78.4 / 28 at `3b37967`, −6.53 / −293.5 / 56 at `c8a4126`, −5.44 / −228.9 / 53 at `d2b7d34`); typ +6.61, fast +9.82; hold met all corners (worst 0.094 ns fast); 3,396 flops (+0), 31,423 cells, 54.0%. **New critical path:** the program store read port, `e_wraddr` → store read mux → `s_wrdata` (31 cells, 20 buf/inv; top seven paths); next `e_host_lane` → `l_hcnt` (+1.087). Implied fmax (setup only): slow ~50.3, typ ~74.7, fast ~98 MHz. ⇒ **T3 met at 50 MHz, thin (0.1 ns) at slow.** 60 MHz at slow is ~3.2 ns short and its limiter is the STORE READ, not dispatch: option 3 alone would not close it; a store-read pipeline stage (L_REFILL 4 → 5, D* 20 → 25) is a published-claim change for the 60 MHz branch | ✅ — T closed at 50 MHz; ACCEPTED (Wilson) |
| **LOCK HYGIENE** (ruled) | slow-corner margin is ~0.1 ns: **ANY RTL change before the lock needs a full harden (gds + precheck + gl_test) before it counts toward the lock** | standing |
| **60 MHz branch** (record, not now) | store-read pipeline stage + option 3 (dispatch a cycle later). With `L_REFILL = 5` the PORT_SPEC skeleton predicts `2d ≥ (k−1)C + (k+1)L + 1 = 43`, i.e. **D* ≈ 22, not 25 by assumption** -- a prediction to TEST on the branch (PS1 showed the throughput floor `k·L` also binds: 25 at L = 5) | branch only |
| **C1–C3** | confirm before R closes: C1 lockstep numbers, C2 SymbiYosys results + must-fires, C3 PS1–PS3 re-run on `51a7214` (PS3's starvation arm vs `3b37967` as the must-fire comparison) | ✅ ACCEPTED (Wilson) |
| **C1** | lockstep current RTL vs `3b37967`: **1,120 / 1,120 byte-identical incl. priming** = 35 shipped + 1,000 random admissible + 85 probe images (incl. d = 18/19 stall arms and the 12×4 starvation arm) | ✅ |
| **C2** | `argmin_equiv`: tree == serial AND one-hot == serial, PASS; both must-fires FAIL at their own assertions. Shadow invariant VACUOUS (no shadow: combinational pre-select). **ADDED:** `formal/preselect_equiv.sby` — the AND-OR pick (`w_act`, `w_hv`, `w_armed`) == the indexed mux, lifted from `src/` by landmark (no RTL edit), premise = the one-hot fact; PASS; must-fire (`w_act` ungated) FAILS at the `w_act` assertion. ⚠ Neither proof runs in CI (no `sby` there) — run by hand | ✅ |
| **C3** | PS2: `ckheavy` lane 4 min gap 12 (10 ≤ 13), others ≥ 18. PS3: `pe_asm` refuses d_min < D*; 12×4 arm 4M: 50 issue / 53 capture, ≤ 12 ahead. ⚠ LABEL: the 16,468 / 2,473 baseline is **`c8a4126`** (measured 10-07 18:30, last pre-TF `pe_engine.v`); `3b37967` already carries TF3 and measures 50/53. Pinned in PORT_SPEC §6 | ✅ |
| **B1** | branch-1 census, TF RTL, 29 arms with every d ≥ 20: `ISSUE head = 1` (cold start), 0 stalls. d = 19 clean arms: 92 / 2,291 with no stall. PORT_SPEC addenda `fed6e62` | ✅ ACCEPTED |
| **ACK (b)–(c)** (GO, AC1–AC5) | `test/run_ckack.py` (local, sigrok; in `run_a2`): the part's RANDOM READ `S A0 A 01 A 23 A Sr A1 A data A data NACK P`, clocked throughout, against `fram_i2c` in LATE mode. **(c)** sigrok decodes exactly that shape, `5B E2`, every loop. **AC1** chip bytes == sigrok `Data read` bytes == `5B E2` at stretch 0 / 280 / 5,000 / **1,703,088** (lane parked 1,702,951 < timeout 1,753,088), no fault. **(b)/AC3** scratch mutant `S_CK_COMMANDED_RISE` (capture on the controller's release) disagrees with sigrok on every stretched arm (`ff ff…`; `db` for the one stretched byte near the timeout). `M_CK_NO_ALTERNATE` and `M_TX_LOAD_ANYPHASE` (fix #2's old form): no well-formed read. **AC5** A2/A3: sigrok NACK after each address; the chip's 1-bit receive lands in bit 0 of the RX byte, 1 on every slot (0 where answered). **AC2** `gate_mutant_kills` SCRATCH table: `S_W4_SLOW_REFILL` (run_w_sweep, CI), `S_CK_COMMANDED_RISE` (run_ckack, run_a2); unlisted / stale / unrun scratch mutants are red. ⚠ First full run failed AC1 on a RACE IN MY RUNNER (`sigrok_i2c` writes one fixed wrapper script; parallel decodes ran each other's dumps) — decodes now serialised | ✅ |
| **RC1–RC7** (sigrok re-cert, option 1) | **RC7 LEDGER: the clocked I2C corpus images were never valid I2C** — `corpus_i2c`, `ckread`, `corpus_all5` lane 0 framed START/STOP on LSB-first lanes (`hdr()`'s default) with a STOP issued while SCL was low (no STOP on the wire: sigrok saw one START and an endless byte stream). Detected on the first foreign decode; **chip behaviour correct throughout** (Layer V2: wire == pushed, in the order the header asked). **RC1** rebuilt MSB-first with the measured STOP (3 after a SHIFTIN; `ckread` 4 after its NACK SHIFT); `test/run_recert.py` (run_a2, sigrok): 34/34/14 frames, every one closed by STOP, sigrok bytes == wire bytes == pushed bytes. **RC2** SPI transmit lanes (`ckfive` 0–2, `corpus_all5` 2, `corpus_spim` 0): sigrok mode 3 == the chip's drive; the falling-edge control disagrees on 2 of 5 (data holds across both edges on ckfive). `ckfive` lane 3 declared: it sits on the SPI-target CS/MISO pad pair, so its own 1 bits clear its clock's enable (pad override as designed); lane 4 is receive-only. **RC3** 8 images declared not certifiable by name (timing subjects, refusal images); an unclassed clocked image is red. **RC4** `pe_isa.order_for` derives the order from the program (START/STOP → MSB) in `corpus._assemble`, `build_ckread`, `pe_asm.assemble`; `gate_i2c_order` (CI) + `pe_asm.check_i2c_order` refuse an LSB I2C lane, census lane 0 exempt by name. FRAM write / random-read "builders" are model action lists with no header — none exists yet; the FRAM item will take its order from `order_for`. **RC5** lockstep: corpus_i2c `f8b7f6ab→c6e6d013` (dispatches 1319→1320, stream MOVED), ckread `faa8f4c6→94f7ddb5` (1316→1317, MOVED), other 10 unchanged; manifest: 3 image hashes; gate_sda_hold & K2: no stored value moved (re-run green); coverage green after the swept `tb_ckack` arm went back to `+DEVW=A1` (its LSB workaround `85` had silently dropped 9 read-path points); A2 bounds: no delay changed. **RC6** `sweep_w.json` pins image hashes; `run_w_sweep --images` re-ran the 12 image rows (refused if the RTL hash is stale); stale image hash is a must-fire in gate_j_program | ✅ |
| **PN8 + SP1 program** | (1) `host_feed.vh`: per-queue sequences up to 16 bytes (`hf_n`/`hf_put`) so a real transaction fits ONE queue; `tb_tx`/`tb_half` take `hf_len`. (2) **my `run_ckack` image used 4 TX queues on one lane, which `pe_asm` REFUSES** — now one queue; it checks its own image against `check_queue_ownership`; ACK re-certified (PASSED). (3) `fram_spi.v` to the datasheet (modes 0 AND 3): deselect resets asynchronously, a byte completed before CS rises acts at CS rise, WEL clears at CS rise after a WRITE — it was mode-0-only (phase never reset; the last byte never acted). (4) `corpus_spim` = the real MB85RS64V `WREN WREN WRITE 01 23 5B C4 1E READ 01 23 in in`, MSB-first, fed in order (`corpus.FEEDS`, `tb_trace +FEED/+FEEDN`, `verilator_trace.sh` arg 12); MISO now moves → **`corpus_spim` OPEN retired, corpus trace 8 of 8**. Coverage `fram_spi` 11/17 lines + 7/12 branches uncovered → 4/18 + 2/18 (WRDI/RDSR/RDID + refused write OWED, `default` UNREACHABLE); toggle ceiling 54 → 18. ⚠ The chip's RX on this program reads 00 — silicon fix #3 below (PN1–PN7) | ✅ |
| **PN1–PN6 + CI1–CI5** (silicon fix #3, both parts; ledger rows above) | **PN1** `ck_rpin` = the head slot's action pin; `M_CKRX_HEADER_PIN`. **CI1** push-pull clocked capture from a 6-flop slot (`ppc_v/l/n`) at the engine's own rise; open-drain keeps the observed rise; `M_CKRX_PP_OBSERVED`. `run_mutants` 25 mutants, 0 survivors (both new ones die of `clocked_conform[V-RX]` on `corpus_spim`). **PN2** `docs/PIN_FIELDS.md`: every pin-taking path, RTL + `pe_asm` + model + bench layers. **PN3** Layer V-RX in every `clocked_conform` bench: RX frames == the pad bits on the action's pin. Two of my own errors found by it on its first full sweep: (i) it queued RX pushes the chip DROPS on overrun (`project.v` `rx_pend`; reported as status bit 6) — now modelled, and a drop without the sticky bit is red; (ii) `tb_rxbw` drove its peer with blocking writes after `@(posedge clk)`, racing every posedge sampler — 616 of 3948 frames off by one walking bit at d = 45; now non-blocking, rx-bandwidth gate unchanged (loss stops at d = 45 = prediction). **PN4** `model/gate_pin_matrix.py` (CI): all 10 classes run with action pin != header pin; pindiv is now SWEPT (`benchset` tb_cktx `gen`). **PN5 / SP1** `test/run_spifram.py` (run_a2, sigrok, MOSI and MISO decoded SEPARATELY): mode 3 (tracked image) 39 READs, mode 0 (scratch, SCK parked low) 38 READs — chip RX == sigrok MISO == written `5B C4` (78 / 76 bytes); MOSI frames exact; V2 + V-RX ok; must-fires `M_TX_LOAD_ANYPHASE` (0 of 156 frames decode as the WRITE), both fix #3 mutants (peer answers `5B C4`, chip `00`). `fram_spi` 4/18 lines + 2/18 branches uncovered (WRDI/RDSR/RDID + refused write OWED, `default` UNREACHABLE), toggles 18 ≤ ceiling 18 — the seven TX5 points stay paid by the bytes the program means. **PN6 / CI4** cocotb `test_clocked_spi_read_at_the_pins` (pins only → gl_test): `5B` ×15 (1 mode-3 read, 14 mode-0); `M_CKRX_HEADER_PIN` and `M_CKRX_PP_OBSERVED` each `00` ×15, FAIL; cocotb 14/14 local. `ckfive` lane 4 now captures; lockstep re-recorded (only ckfive moved, dispatch stream identical). **CI2** HOST_INTERFACE "SPI master receive timing": instant in ns vs the MB85RS64V table. **CI3** `test/run_spidelay.py` (CI): MISO delay N ≤ 5 → 19/19, 6 → 18/19, 7 → 15/19, ≥ 8 → 0/19; predicted edge d − 1 = 6, agrees within 1 cycle. **CI5** `pe_asm` alias check on the action pin (must-fires both ways); V2 samples the action pin; scratch `S_TX_HEADER_PIN` (run_cktx) red on V2. **Knock-ons:** `gate_program_index` had stopped SEEING the sample read (renamed into the `ck_rpin` wire) — registered; coverage re-anchored (+48 / +14), the stretch-error branch 2678 went dark (it was paid ONLY by fix #3b's defect) → OWED with the analysis, the K = 1 arm covered by swept pindiv; `sweep_w.json` re-run, 80 arms, 0 violations, only the RTL hash moved. ⛔ **`S_CK_COMMANDED_RISE` WENT VACUOUS**: its text landmark still matched once, inside the new `ifdef M_CKRX_PP_OBSERVED`, so the "mutant" was the clean RTL and `run_ckack`'s must-fire failed only because it could not die. All 3 scratch builders now go through `toolchain.scratch_sub` (refuses a landmark in mutant-`ifdef` code; must-fire in `gate_mutant_kills`); re-run: `ff ff …`, `db` near the timeout, as recorded. ⚠ **Finding, not changed:** a clocked receive ENDS WITH SCK LOW (I6), so after a READ the next transaction is mode 0, while a SHIFT leaves SCK high (mode 3). The part accepts both; a program wanting one mode throughout parks SCK with an `OP_LEVEL` | ✅ `117e55c`: CI test 37884255883 + docs 37884255888; harden 37885702201 gds + precheck + gl_test 14/14 ✅; slow WNS −0.074 ns (1 viol, `e_host_lane → l_hcnt[2][3]`), typ +7.33, fast +10.29, hold clean → TM |
| **TM1–TM3** (timing, option 2; bar = slow-corner WNS ≥ +0.5 ns) | 117e55c slow corner, 2000 paths: **10 below +0.5 ns**, three families — `cur` → `hold_ld` → `l_hcnt` (7 paths, −0.074…+0.493), `e_wraddr → s_wrdata` store read (+0.140), `edf_key_off` → argmin → `cur_act`/`a_cnt` (+0.197); next tier +0.70 (`e_host_q`, `e_pin_oe`, `a_op`, `a_pin`, `a_dly`). **TM1** the DRIVE arm records the hold load (`hl_v`/`hl_l`, 1 + LW flops) and the countdown writes `SDA_HS − 1` a cycle later; `l_hcnt` is now the EFFECTIVE count (a wire, the pending load reads `SDA_HS`), so every reader — `hz_q`, the pin landing, Layer H — sees the same value every cycle; "load only on an idle counter" kept via `hz_q[cur]`; `M_TM1_UNREG` = old form. **TM2 store** the engine registers `paddr + 0/1/2` beside `s_wraddr` (`s_wraddrk`), so no adder precedes the 256-way mux and each byte has its own address flops; `M_TM2_STORE_ADD` = old form; `paddr` is now RESET (the sums let synthesis rename 7 of its 8 unreset flops, breaking the reset audit's by-name allowlist — the `pslot`/`fix` lesson; write-before-read makes it invisible; entry retired). **TM2 argmin** all 10 lane-pair compares run in parallel off the registered keys and each node selects its pair's bit — no 16-bit key mux in series; SymbiYosys miter PASS, both must-fires FAIL (⚠ the miter is run by NO gate — local only, since TF4). **Proof:** lockstep vs `117e55c` **1,035 / 1,035 byte-identical** (35 tracked + 1,000 random admissible; 33.2 M pin lines, 6.1 M dispatch lines), priming identical; `sweep_w.json` re-run — only the 3 RTL hashes moved, 80 arms unchanged; `gate_sda_hold`, `run_ckack`, `run_cktx`, W live subset green; coverage re-anchored (+63), no new uncovered point. Both old forms are DECLARED SURVIVORS (equivalent by requirement). **TM3 (read-only, from the run's `resolved.json`):** the flow can target margin without moving signoff — `PL_RESIZER_SETUP_SLACK_MARGIN` 0.05 / `GRT_RESIZER_SETUP_SLACK_MARGIN` 0.025 ns (repair targets), `RUN_POST_GRT_RESIZER_TIMING` off, `PL_TIMING_DRIVEN` off, `SYNTH_STRATEGY` `AREA 0`; `CLOCK_UNCERTAINTY_CONSTRAINT` 0.25 ns already in signoff. ⛔ `TIMING_VIOLATION_CORNERS = ['*typ*']`: the flow fails only on TYP violations — both slow-corner misses reported gds SUCCESS, so the +0.5 ns bar is ours to check | local ✅; harden (TM4) owed |
| **TX1** | RTL: host load gated to the LOW phase; `M_TX_LOAD_ANYPHASE` (ifdef) = the old form, registered (`gate_mutant_arms` 2 lines; killer `run_mutants` CLOCKED on corpus_i2c, dies of `clocked_conform[V1]`) | ✅ |
| **TX2** | Layer V2 in `clocked_conform.vh` (all 16 benches that include it): host PUSHES decoded off `ui_in`, wire bits off the data pin at every clocked HIGH (uio released = 1), per lane in lane order; a lane's j-th clocked SHIFT sends its (j−1)-th popped byte whole; underrun residue modelled and counted; bytes consumed == bytes on the wire | ✅ |
| **TX3** | golden model: TX register + load point; I11 (load once, on the LAST LOW) and I12 (bits = register, in order), must-fires (pre-fix load → I11; its wrong 8th bit → I12, with a byte pair where the bit really differs — the first choice passed vacuously). Generates `ck_load_at` / `ck_tx_bit` into `clocked_bounds.vh`; Layer V1 checks them | ✅ |
| **TX4** | `test/run_cktx.py` (CI) + `tb_cktx.v`: OD MSB lane widths 1..8 back to back + bytes with ACK; PP LSB lane widths 8 3 8 5 1 7 2 4 6; non-palindromic queues; starve window (underrun 11 / 39 actions, V2 holds); mutant red on V1 and V2 | ✅ |
| **TX5** | lockstep golden re-recorded: pre-form reproduced all 12 old digests; **dispatch streams identical old→new on all 12**; full digests moved on exactly corpus_i2c `aa745219→f8b7f6ab`, ckheavy `b4292ea8→5990cc50`, ckfive `4b4df9cd→bbba6698`, ckod `f6bf04fa→a1af4720`, ckread `ea1e42fb→faa8f4c6`. `dispatch_sha256` now recorded per image. **Other knock-ons, each re-recorded deliberately:** `gate_sda_hold` W5 (`M_NO_HOLD_GATE` on ckhold_over) 11/562 → 14/688 (the pre-fix RTL with the same mutant still gives exactly 11/562); `sweep_w.json` re-run (STALE by design on any RTL change); **coverage, a retraction:** 7 `fram_spi` decoder points and 24 of its toggles that the self-clocked corpus had "paid" were paid by the **misaligned** bytes (the feed 5B 01 7A C7 holds no READ/WRITE opcode; the drift formed one) — back to OWED (`_SPI_DRIFT`), ceiling 30 → 54. The `fram_i2c` READ path (old 207/208/239) is now PAID by `tb_ckack`'s swept arm (`+DEVW=85`, LATE 300, LATE_SKIP 4 — the first program ever to read the peer); its ceiling 93 → 98 for the LATE registers | ✅ |
| **TX6** | cocotb `test_clocked_tx_bytes_at_the_pins` (pins only, gl_test): fixed `00 5B 5B 5B 5B 5B 5B`; built with `M_TX_LOAD_ANYPHASE` FAILS `00 B5 6A D5 AB 56 AD` (run via cocotb's runner on Windows iverilog 12; OSS CAD's iverilog 14-devel rejects pre-existing declaration order). Harden on the fix SHA: pending | harden owed |
| **TX8** | ⚠ **CORRECTION to the ruling's premise (mine):** STOP cost depends on what it follows — after a clocked SHIFTIN the COLLECT leaves SCL LOW (STOP = 3); after a clocked SHIFT SCL is HIGH (STOP = 4; with 3 a final 1 bit — every NACK — makes a spurious START, measured). Repeated START after a slave ACK = 3 (was costed 4). `clocked_shift_budget.py` corrected: write 15 actions / 75 B, random read 20 / 90 B (net unchanged); both fit AW = 8 | ✅ |
| **TX9** | `fram_i2c.v`: P_RDATA reload of the second byte, SDA released through the master's ACK/NACK slot, stop on NACK, LATE / LATE_SKIP / LATE_ONCE stretch. **No earlier result used a read with this peer** (tb_i2c, tb_trace only write) | ✅ |
| **W** | Theorem 3 on the bench: `test/tb_w.v` + `test/run_w_sweep.py` (live subset u20, m20, u18, slow-u20 in CI; `--full` → `model/a2/sweep_w.json`, checked by `gate_j_program`, STALE on any RTL change). 0 violations on 56 arms at d ≥ 20 + 12 images; must-fires red; d = 19: m/drift clean, u/mb stall. **F1** two owed slots per lane at d = 20/21; **F2** R_i = 12 tight; **F3** Lemma A's gap premise fails on `ckheavy` → generalise (Lean), ckheavy measurement-only meanwhile. J_LANE_PROOF A4 | ✅ |
| **CI2** | retro: confirm the `tb_trace` path gate was the ONLY failure on `6abb6dd..e1fa642` | owed |
| **E** | Python swallowed-exception audit (E+ shell half landed earlier). `model/gate_except.py` in CI: no bare `except:`; no `except Exception` that neither re-raises nor is allowlisted BY NAME (file, function, first statement) with where its verdict goes; 117 console-encoding handlers excused structurally; stale keys fail. Must-fires: pre-fix measure_phases `NameError -> None` shape RED, bare except RED, stale key RED, re-raise GREEN. **E3 ledger, four live swallows found and FIXED:** measure_phases rewrote a corrupt phases file with one record (deleting the rest); gate_stored_numbers skipped unparsable files and unparse failures; gate_one_encoder caught everything (measured: only NameError/SyntaxError, now exactly those); gate_a2_program §1b skipped an admissible lane whose own recurrence raised | ✅ `cc1bc12`, CI test 37797469012 / docs 37797468905, ACCEPTED |


### ~~D — refuse `d <= SDA_HOLD`~~ → LANDED, except D2's mode floor

See `docs/SPEC_V4_CLOCKED_HIGH_PHASE.md` §13 for the full trace. Summary:

* **D1 silicon** — `ck_holdviol` joined with `ck_degen` into one `ck_refuse`
  wire at the **head** of every clocked chain. `config_err`, lane halt,
  engine-wide stop through `ST_IDLE`. **+0 flops.** `<=` not `<` (at equality
  `t_SU;DAT` is zero). Open-drain only. `SDA_HOLD == 0` refuses nothing, so the
  `hold0` measurement arm still has traffic.
* **D2 — STATIC HALF ONLY.** `pe_asm.check_clocked_hold_delay` refuses on the
  `SDA_HOLD` floor, boundary read from the RTL via `model/hold_bound.py`.
  ⛔ **STILL OWED, WITH S:** the per-program floor
  `d >= t_LOW(min, mode) + (r_i − C)`. A program the assembler accepts today is
  **hold-legal, not certified mode-legal**, and the report says so.
* **D3** — clamp removed from the **clocked** site; **kept at the unclocked
  site**, where `build_i2cframe(d=12)` still reaches it and D1's `ck_act` scope
  does not. ⇒ Extending the refusal to the unclocked idiom would retire it
  entirely: a **scope decision**, recorded not taken.
* **D4** — three images (`ckhold_under/at/over`), boundary from
  `hold_bound.bound()` + offset. Refusals in `tb_pinrange +MODE=4`; the **runs**
  arm in `tb_trace +CKRUNS=1`, because `tb_pinrange` holds `uio_in` constant and
  a parked open-drain lane would measure a hang. 131 clocked actions retired.
* **D5** — `d = 70` (Fm, matching the lane's own "I2C 400 kHz" label). 65 is the
  arithmetic floor and **measured 63/64**, so 70. `corpus_all5` raises **lane 0
  only** — the other four stay at 9..13 to keep the contention the image exists
  for. Bit period 24 → 146 cycles; `+NCYC` fixed, so ~6× fewer transactions per
  arm. Coverage **26 → 26, same points**; the one branch D3 left reachable only
  at `SDA_HOLD == 0` is **covered by a new sweep arm** (`ckod_hold0`,
  `-GSDA_HOLD_NS=0`) rather than waived.
* **D6** — `DELIBERATE` names one refusal class per image and reds on a second.
  32 images, 8 declared, 0 undeclared, 0 multi. Found `cfgerr_image.hex`
  undeclared (the 1.6s predicate did not exist, so the audit could not decode
  the refusal the image exists for) and the gate's own selftest probing at
  `d = 9`, where two arms would have passed for the wrong reason.
* **P5** — `corpus.PAD_COLLISION`: `ckfive` lane 3 and `ckod` lane 3, the only
  two, each with the colliding pin named. Scoped to lanes that can **drive**.

### ~~R — the port-demand invariant~~ → LANDED

`clocked_conform.vh` **Layer R** counts prefetch refills (`pst == P_CAP` with
`pl` naming the lane) per **retired clocked action**, over the window Layer B
already delimits, attributed to the action that **ended** via `cb_ck`.
`test/refill_run.sh` + `model/gate_port_demand.py` adjudicate it; the gate is in
`ci/run_gates.sh` and is **RED without the measurement**. See SPEC §14.

* **Bound = `dut.u_eng.SPL`**, derived: at most one fill per slot (the previous
  retire's head refill landing just inside the window, plus one speculative
  spare fill). **Enforced by default** — unlike A2's, because it is a
  structural property of the buffer depth rather than a lane-set bound.
* **Measured:** clean 1 / 1 / **2** on `ckod` / `corpus_i2c` / `corpus_all5`
  (632 retired actions); `M_CK_HOLD_INVAL` **16 / 16 / 17**. Also 1 on `ckfive`
  (310 actions) and `ckhold_over` (196), in all three rand-reset modes.
* ⚠ **`corpus_all5` touches the bound exactly** — no slack. A red here is a
  request to re-derive `D*`, never a licence to raise the constant.
* ⛔ **The first bound was 1 and was wrong**: measured on the two single-clocked-
  lane images and applied to the 5-lane stress image, where the spare fill
  lands inside the window. Same category error as three others in this ledger;
  fixed by deriving from the depth, which explains both numbers.
* `M_CK_HOLD_INVAL` is **no longer a characterised survivor** — its entry in
  `gate_mutant_arms.py` says so.

### ~~R4 / R5~~ → LANDED. See SPEC §15.

**R4** checks Theorem 3's **P10** and **P1** in the words the proof uses, and
`gate_port_demand.check_premise_text()` fails if either sentence stops appearing
verbatim in `J_LANE_PROOF.md` — so the bench and the proof cannot drift. The
Lean formalisation has not started; when it does its premise is copied from the
same sentence.

⇒ **The three layers are orthogonal, and that is measured, not argued:**

| arm | R4 (premise) | R5 non-retiring | R (rate) |
| --- | --- | --- | --- |
| clean | ok | 0 | ok |
| `M_CK_HOLD_INVAL` | **ok** | 2820 / 586 / 5260 | **red** |
| `M_PFETCH_BOTH_INVAL` (new) | **red** | 0 | **ok** |

`M_CK_HOLD_INVAL` raises the *rate* while still leaving one slot per dispatch,
so **P10 holds under it**; `M_PFETCH_BOTH_INVAL` keeps the rate and breaks the
premise. Each mutant dies to exactly the layer whose sentence it violates.

**R5's answer is case (a):** **zero** non-retiring refill-bearing dispatches on
every clean arm (7 images). Every refill is owed by a **retiring** dispatch —
exactly the set §1's closed form covers, so **`d_min` needs no re-derivation**.
`corpus_all5`'s second refill is the speculative spare fill Theorem 3's own note
already counts.

⛔ **`D*` is a RATE bound, not a minimum separation.** The port-wide min gap is
3 cycles on multi-lane programs and that is the demand `D*` is sized *for*;
comparing it to 20 would have manufactured a failure on every such program. The
**per-lane** min is `d_min`'s subject, and it tracks admissibility exactly:
`corpus_i2c` 69, `ckod` 37, `ckfive` 23, `ckhold_over` 20 — all port-feasible,
`J = 1`. The three below `D*` (`corpus_spim` 5, `corpus_sptgt` 3, `corpus_all5`
3) are coverage/stress images, infeasible **on purpose**, `J = 8`.

**FRAM programs, explicitly:** §1's write and random read have `d_min` **81**
and **50**, far above `D* = 20`, one clocked lane each. Unaffected either way.
`corpus_spim` at `d = 7` is a trace image, not the shipped 1 MHz SPI lane.

### ⛔ NEW, AND IT CHANGES ACK — the clocked SHIFTIN's SDA release is not held

ACK item (a) asked that the release be **confirmed** to pass the H1 hold check.
Measured during D5: **it does not.** `t_HD;DAT` on `corpus_i2c` is
`{0: 20, 15: 93, 280: 35, 282: 1}` — 93 held data bits and **20 with zero
hold**. A falsifier set attributes every zero to the clocked `OP_SHIFTIN`:
dropping `OP_READBIT` leaves 21, dropping `OP_START`/`OP_STOP` leaves 23,
dropping the SHIFTIN leaves **0** (all 140 at 15).

The clocked SHIFTIN releases SDA unconditionally on its first LOW dispatch, so
the transition **from the last transmitted bit into the ACK slot** carries no
hold — a real `t_HD;DAT` violation, the same class ruling H fixed, in a place
ruling H did not reach.

⇒ **The ruling-H measurement set cannot see it**: `build_ckod` is SHIFT-only,
and `i2cframe` escapes because its SCL fall and SDA release are different
dispatches, `d` apart. §4b(a)'s green is sound for the **transmit** path and
silent about the receive handover. ACK (a) becomes a **fix**, not a
confirmation.

### S — the A2 bound, per program

`CK_GAP_SLACK = 8` in `test/clocked_conform.vh` is the **shipped** lane set's
`L_SYNC + 1 + (r_i − C)`. It is currently enforced on one arm only
(`+A2BOUND=1` on `ckod`) because other programs have different lane sets —
`corpus_all5` measures a post-rise lateness of **19**.

⇒ Compute the bound **per program** from that program's own A2 row and feed it
to the bench (generated `.vh`, like `clocked_bounds.vh`), so every clocked arm
is bounded rather than one. Must-fire: a lighter lane set's bound applied to a
heavier program must go red. This also supplies **D2**'s floor.

### E — swallowed-exception audit (alongside)

* **E1** a gate over `test/` and `model/`: no bare `except:`, and no
  `except Exception` that returns a value or passes without re-raising or
  recording a verdict. Allowlist **by name with a reason**.
* **E2** must-fire: the pre-fix `measure_phases.py` shape
  (`NameError` → `None`) must trip it.
* **E3** ledger: now **four** checks-that-could-not-fire in this arc — the
  sweep's `*** FAIL` grep, the backspace `\b` regex, the swallowed `NameError`,
  and (found by ruling D) **`benchset.plusargs_read`'s `[A-Z_]+` pattern, which
  could not see `+A2BOUND` because of the digit** — thirteen benches reading it,
  one arm supplying it, the check silent for a whole arc. Pattern widened,
  `SHARED_INCLUDE_DEFAULTS` declares the default once, and both the digit case
  and the scoping are priced in the gate's own must-fires.

---

## THEN

**ACK (a)–(c)** → sigrok re-certification (clocked corpus, now with the hold)
→ FRAM write + random read.

* (a) SDA released on **both** phases + an overlap mutant
* (b) sample on the **observed** rise
* (c) sigrok shows ACK reads 0, NACK reads 1; a non-alternating-phase mutant
  fails decode
* ⛔⛔ **ACK's SDA release does NOT pass the H1 hold check — measured.** See
  the finding above: the clocked `OP_SHIFTIN` releases SDA on its first LOW
  dispatch with no hold, so the last transmitted bit gets `t_HD;DAT = 0`. (a)
  is a **fix**, not a confirmation, and the ruling-H measurement set is blind to
  it (`ckod` is SHIFT-only).

Merge rule unchanged: **nothing to `cmos5l`** without `gds` + `precheck` +
`gl_test` green on the exact SHA.

---

## ⛔⛔ CI WAS RED FOR FIVE COMMITS WHILE LOCAL WAS GREEN — fixed, read this

`6abb6dd`, `ea0259f`, `2120012`, `e1fa642` and `80ff8d7` all show **`test`
workflow FAILURE** on GitHub at **19 of 20**, with
`model/a2/gate_um10204.py (no phase measurement at PE_PHASES_JSON)`. The
earlier handoff recorded them as "CI-green". **That was wrong**, and the local
20 of 20 was not: the two disagreed for a reason that is invisible on this box.

**Cause.** `tb_trace.v` declared `reg [8*64-1:0] imgfile, outfile, peersel`,
and `test/phases_run.sh` passes **absolute** paths. Here
`/mnt/d/ProtocolEmulator/probe_phases/trace_clean.txt` is 59 bytes and fits; in
CI the checkout is `/home/runner/work/protocol-emulator-asic/...`, so `+OUT` is
**99** bytes and `+IMG` **83**. Verilog **silently truncates** a longer
`$value$plusargs("%s")`, `$fopen` returned 0, `$fwrite` to fd 0 wrote nothing,
and the simulation printed a clean `$finish` and **exit 0**. Every arm reported
`*** no trace` with no reason.

**Priced, not argued:** the same binary writes 2,001 lines to a 39-byte path and
nothing to a 107-byte one. After the fix, 107 bytes writes 2,001 lines.

**Fixed three ways**, because one would have left it undiagnosable again:

1. `tb_trace.v`'s filename buffers → **256 bytes**.
2. `$fopen` failure is now **fatal and named**, printing the path and the
   buffer size. A bench that cannot record its measurement must say so itself.
3. `phases_run.sh`'s `no trace` branch prints the **path length** and the head
   of the run log. Five CI runs said `no trace` and nothing else.

⚠ **LATENT, NOT FIXED:** **every other bench still declares `8*64-1`**
(`tb_csat`, `tb_edge`, `tb_fifo`, `tb_half`, `tb_i2c`, `tb_jlane`, `tb_rxbw`,
`tb_smoke`, `tb_tx`). They are safe **only** because `benchset` hands them
RELATIVE `+IMG=test/...`. Anything that ever passes one an absolute path hits
the identical silent truncation. Deliberately left rather than changed blind.

⇒ **STANDING RULE FROM THIS:** a local `20 of 20` is **not** a CI green. Check
`gh run list --branch dev` after every push. `ci/run_gates.sh`'s own banner
says a green here is a green there — that claim held only because nobody looked.

---

## Open, accepted or unexplained

* ~~`gate_corpus_trace`~~ — **restored and in CI** (SPEC §17). 7 of 8, 0 failed, 1 open (`corpus_spim`, stated); `corpus_i2c` / `corpus_all5` at d = 70 CYCLE-EXACT across both simulators.
* **The unclocked `ck_hold_fits` clamp** — still live, still reachable by
  `build_i2cframe(d=12)`. Retiring it means widening D1 past `ck_act`: a scope
  decision (D3).
* ~~**`d ≤ SDA_HOLD` hazard**~~ — refused in silicon (D1) and in the assembler
  (D2 static half). The clamp is gone from the clocked path.
* ⛔ **`corpus_all5` post-rise lateness is 131, not 19** — the 19 went stale when
  D5 moved lane 0 to d = 70 beside four lanes at 9–13. Its lane set has
  U = 1.096, so ruling S reports it **unbounded** (no finite worst case) and the
  bench measures it without a verdict.
* **`ckfive` lane 2: modal t_HIGH 123 vs d = 120** (+≈`L_SYNC`) on a push-pull
  lane that does not park, while lanes 0 and 1 are exact. **Unexplained.**
* **`t_SU;STA` / `t_HD;STA` / `t_SU;STO`** — need START/STOP, which the clocked
  images do not contain. Owed against the certified two-action frame.
* **`t_r` / `t_f`** — edge rates are a board/pull-up property; a
  cycle-resolution trace cannot see them.
* **Trace-level START/STOP separation** — a pin trace cannot tell a legitimate
  START from an SDA-during-high violation; needs opcode visibility.
* **`hdr_cyc` 92 vs 91** — open, bounded, gates nothing.
* **Ruling T `d/2` high phase** — named reach item, needs a selector bit, so it
  waits on an encoding decision.
* **Harness friction** — every RTL edit shifts `gate_coverage`'s line anchors;
  `reanchor.py` ran five times this arc. Keying the table on anchor **text**
  with the line as a hint would absorb it. Observed, not changed.

## Standing constraints

* `refs/` is gitignored with the guard committed — the submission is **open
  source**; third-party PDFs must never enter it. UM10204 is **transcribed**,
  never vendored.
* Verilator pinned at `/opt/oss-cad-suite-2026-09-30/bin/verilator`; runs need
  `--x-initial unique` **and** `+verilator+rand+reset+2`.
* `wsl.exe` always with `MSYS_NO_PATHCONV=1` and always a **script file**.
* Author sources with Write/Edit, **never** shell heredocs into tracked files.
* Never `git add -A`; explicit paths only. Probes write only to `probe_*`.
* **`SDA_HOLD` is stated once, in `src/pe_engine.v`**, and read everywhere else
  through `model/hold_bound.py` — which refuses rather than guesses if the RTL's
  ceiling expression changes. `test/param_dump.sh` prints the **elaborator's**
  value as a second authority (both read 15). Never type the number.
* No comment line may begin with the token `Verilator`.
* Run `bash ci/run_gates.sh` as the **last** thing before reporting; a green on
  a tree you then edit describes nothing.
* ⛔ **Run it as `PYRTA_SRC=/nonexistent bash ci/run_gates.sh`.** pyRTA is absent
  from CI by design, and a pyRTA clone sits in this box's scratch directory, so
  a plain local run can pass checks CI cannot run (`992c298`, red at 20 of 22).
  The pyRTA-primary gates run separately: `python model/a2/run_a2.py`.

* ⛔ **Capture exit codes with `. ci/rc.sh; run_rc <cmd>`**, never a hand-written `$?` after a pipe or a `$(...)`. Four vacuous readings in one arc; `gate_shell_rc` enforces it in committed scripts.