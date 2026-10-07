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

---

## OWED — Wilson's order

`R` ✅ → **`S`** → `Q2 + CI3` → `K (+U)` → `E` → sigrok re-certification →
FRAM write + random read.

| item | what | state |
| --- | --- | --- |
| **R** | port-demand invariant (a RATE) | ✅ landed |
| **R4** | Theorem 3's P10 + P1 checked VERBATIM; own mutant | ✅ landed |
| **R5** | refill-bearing dispatch attribution; §1 stands (case a) | ✅ landed |
| **S** | the A2 bound, per program; D2's mode floor on the same machinery | ✅ landed — SPEC §16 |
| **D\*-window** | Theorem 3's CONCLUSION live: sliding window of `d` cycles counting refill requests at the port, asserted `<= k` on every feasible-at-J=1 arm; must-fire on an infeasible arm (`corpus_all5`). Premise (R4) + conclusion (window) = the whole theorem on the bench. **Goes in the existing `D*` sweep step — not new work now.** | owed (Wilson, after R5) |
| **Q2** | `gate_corpus_trace`: answered; fix = run it + repair the build, + a GATES-completeness check (every `gate_*.py` listed or excluded by name) | **NEXT** |
| **CI3** | every bench's `8*64-1` filename buffer + a >128-byte long-path arm | owed |
| **K** | ACK hold: every driven SDA transition through `SDA_HOLD`, + a transition-class coverage table | owed |
| **U** | widen the refusal to the unclocked open-drain data drive; retire the clamp | owed, with K |
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

* ⛔⛔ **`gate_corpus_trace` — Q2 ANSWERED, FIX ORDERED AFTER S.** It is **not
  in the gate list and nothing runs it**: `GATES` does not contain it and no
  `.sh`/`.yml` invokes it. So 20 of 20 never included it — the suite was not
  passing *over* a broken gate, it was never asking. **It is also not
  fail-open:** on a build failure it prints `*** iverilog build FAILED` and
  `return 1`, real exit code **1**. ⛔ My earlier `RC=0` was my own error — `$?`
  read after a pipe into `tail`, the **vacuous `$?`** mistake from earlier in
  this same session, repeated. ⇒ The real defect is **a gate that correctly
  reports RED and that nobody runs** — a fifth instance of the class, in a new
  shape. Fix = add it to the list (goes red at once) **and** repair the build
  (`final procedures cannot enable/call tasks`, `progress.vh:214`,
  `clocked_conform.vh:382`). Until then the corpus at `d = 70` is certified by
  the Verilator sweep, the loader audit and `measure_phases` — **not** by the
  iverilog cross-check.
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
