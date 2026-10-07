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
| **Y-R** | "pyRTA double-counts jitter" WITHDRAWN (TChecker: D − J exact 8/8, charge-once below truth 5/8); wrapper unchanged | ✅ local — SPEC §26 |
| **Z** | our recurrence gets Spuri's full candidate set (old search below TChecker on 7/8; 184/6,601 at J = 0); `gate_spuri_candidates` (CI), `zone/run_z.py` (24/24) | ✅ local — SPEC §26 |
| **DT** | 1.6a per program (r_i ≤ t_i, measured vs TChecker); QUEUE condition; ckdense + ckhold_over non-admissible; ckheavy is Ruling S's subject; D_sched ≤ D_tol asserted | ✅ local — SPEC §26 |
| **A** | pyRTA primary wherever published/judged; ours an asserted ≥ cross-check; README `J = 1` row 9 / 11 (ours column keep/drop = Nathan's prose call); 1.6m re-priced (pyRTA C = 3 margin 1); W1 jitter on pyRTA's side; `ANALYSIS_LEDGER` | ✅ local — SPEC §26 |
| **T** | 50 MHz timing closure, LOCK BLOCKER. T1/T2 from the harden; fix plan named only after the paths are; any argmin restructure must preserve the lowest-index tie rule, proven equal to the serial one | T1/T2 owed (harden running) |
| **CHECKPOINT (H-CK1–3)** | full harden (gds + precheck + gl_test) on the W dev SHA without merging; report flops / utilisation / slack / gl_test / precheck / wall time vs `d2b7d34` (3127 flops, ~10%, 8/8); gl_test must exercise M5 short-load, D1/U refusal, clocked OD park/rebase, the hold pipeline, W1 — add arms or say which it can't reach. ⚠ Scope is every `src/` commit since `d2b7d34`, now also K, U and W | **NEXT — GO** |
| **CI2** | retro: confirm the `tb_trace` path gate was the ONLY failure on `6abb6dd..e1fa642` | owed |
| **E** | swallowed-exception audit, **+E+**: `set -o pipefail` in every `.sh` under `ci/` and `test/` with a lint gate (must-fire: a failing command piped into `tail`) | owed |


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