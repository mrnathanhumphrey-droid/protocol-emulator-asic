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
| Ruling D (D1, D3–D6) + P5 + D2's static half | *this commit* | `d <= SDA_HOLD` refused in silicon and in the assembler; +0 flops |

20 of 20 gates, **26 uncovered (all classified, and the same 26 points as at
`80ff8d7` — `gate_coverage.py`'s diff is 27 anchor moves and nothing else)**,
37 arms / 14 benches.

---

## OWED — in this order

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

### R — the port-demand invariant (⛔ before ACK)

`M_CK_HOLD_INVAL` **survives every gate**. A1 cannot see it: the PC does not
advance during a hold, so the prefetch re-reads the same address and restores
an identical word. What it breaks is **Amendment A1's port premise** — a refill
per *dispatch* instead of per *action*, measured as re-dispatch counts
1229 → 1061 on `corpus_i2c`. `D*` rests on that premise, so until R lands a
design that doubles port demand passes clean.

⇒ Need an invariant counting **refills per retired action** on a clocked lane
(expect 1, not one per dispatch), with `M_CK_HOLD_INVAL` as its must-fire.
Candidate observables: the prefetch FSM's `P_REQ`/`P_CAP` transitions per lane
against `act_retire`.

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

## Open, accepted or unexplained

* ⛔ **`test/gate_corpus_trace.py` CANNOT BUILD**, and has not been able to
  since `7a672b0`: `final procedures cannot enable/call tasks` on
  `test/progress.vh:214` and `test/clocked_conform.vh:382` under iverilog. It is
  the **two-simulator** corpus comparison and the thing that turns
  `corpus.py`'s `must move` preconditions from claims into checks. It is **not**
  in `ci/run_gates.sh`, so 20 of 20 is green without it. ⇒ The corpus at
  `d = 70` is certified by the Verilator sweep (3 rand-reset modes, no
  `*** FAIL`), the loader audit and `measure_phases` — **not** by the iverilog
  cross-check. Pre-existing, not from ruling D, and owed.
* **The unclocked `ck_hold_fits` clamp** — still live, still reachable by
  `build_i2cframe(d=12)`. Retiring it means widening D1 past `ck_act`: a scope
  decision (D3).
* ~~**`d ≤ SDA_HOLD` hazard**~~ — refused in silicon (D1) and in the assembler
  (D2 static half). The clamp is gone from the clocked path.
* **`corpus_all5` post-rise lateness 19** — ACCEPTED, legitimate for the stress
  set, unchecked by design, number kept in the sweep log; governed by S if that
  lane set is ever shipped.
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
