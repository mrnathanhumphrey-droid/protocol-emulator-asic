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
| Ruling P | *this commit* | pad-override explanation; P4 control re-established |

20 of 20 gates, 26 uncovered (all classified), 33 arms / 14 benches.

---

## OWED — in this order

### D — refuse `d <= SDA_HOLD` (amended)

* **D1 silicon**: clocked open-drain with `d <= SDA_HOLD` → `CONFIG_ERR`,
  engine-wide halt, **guard at the head of the chain** (same route as
  `ck_degen`; the retire-chain leak has bitten twice — see `act_retire`).
* **D2 assembler/audit**: refuse below the **per-program** floor
  `d >= t_LOW(min, mode) + (r_i − C)`, computed from that program's own A2 row
  via **S**. ⛔ The fixed 38/78/248 is **retired** — it was `ckod`'s observed
  jitter, not a law. A2 gives Fm+ **33** for the clocked lane set.
* **D3** remove the clamp (`ck_hold_fits`), now unreachable. No new uncovered
  points.
* **D4** must-fire images at `d = SDA_HOLD`, `SDA_HOLD − 1` (refuse) and
  `SDA_HOLD + 1` (runs); all other fields legal. Boundary stated **once**
  (the constant), read by gate and bench.
* **D5 corpus**: raise `corpus_i2c` / `corpus_all5` to a **mode-legal** `d`
  that passes `gate_um10204` — not merely `> 15`. Report coverage
  before/after; any point reached only at `d = 9` gets its own image or a
  classification; report sim-time growth.
  ⚠ These images are the coverage backbone and currently run at `d = 9`, so
  D1 halts them until D5 lands. Do D5 with D1.
* **D6 one image, one refusal**: `ckdegen2` (and every refusal image) gets
  legal values in every field except the one it tests; the audit records
  **which** refusal fired, and a refusal image tripping a second refusal is
  RED. At `d = 9` `ckdegen2` would trip both count-wrap and `d <= SDA_HOLD`.

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
* **E3** ledger: **third** check-that-could-not-fire this session — the
  sweep's `*** FAIL` grep, the backspace `\b` regex, and this swallowed
  `NameError`. Same class, now gated.

### P5 — `build_ckfive` pin-map legality (with D5)

Either make it pin-map-legal or add it to the audit's **named** non-legal list
with exactly which lanes collide. Measurement tools already refuse those lanes
by name. Current state:

| lane | pin/clk | status |
| --- | --- | --- |
| 0,1,2 | 0/1, 2/3, 4/5 | legal + measurable |
| 3 | 6/7 | collides with `CS_PIN`=6 and `MISO_PIN`=7 → pad-overridden |
| 4 | 8/9 | outside `uio` (`uo_out` bank) → unmeasurable from `uio_in` |

---

## THEN

**ACK (a)–(c)** → sigrok re-certification (clocked corpus, now with the hold)
→ FRAM write + random read.

* (a) SDA released on **both** phases + an overlap mutant
* (b) sample on the **observed** rise
* (c) sigrok shows ACK reads 0, NACK reads 1; a non-alternating-phase mutant
  fails decode
* ⛔ **Confirm ACK's SDA release passes the H1 hold check** — the release goes
  *through* the hold path.

Merge rule unchanged: **nothing to `cmos5l`** without `gds` + `precheck` +
`gl_test` green on the exact SHA.

---

## Open, accepted or unexplained

* **`d ≤ SDA_HOLD` hazard** — the clamp bounds it; D1 refuses it.
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
* No comment line may begin with the token `Verilator`.
* Run `bash ci/run_gates.sh` as the **last** thing before reporting; a green on
  a tree you then edit describes nothing.
