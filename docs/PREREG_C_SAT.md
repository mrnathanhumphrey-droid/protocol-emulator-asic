# PRE-REGISTRATION — is `C` 2 or 3 under saturation?

**Written before the instrument exists.** `test/tb_csat.v` and
`test/run_csat.py` do not exist at the commit that adds this file, for the same
reason `docs/PREREG_J_LANE.md` was committed alone at `8bc6979`: a hypothesis
written after the number is known is not a hypothesis.

---

## 1. Why this is being measured at all

Every published response time `r_i`, every margin in the shipped lane table,
and the blocking term `B = max(C_j − 1)` are computed with **`C = 2`**. The
value comes from `model/a2/gate_cj_bounds.py`, which derives it from the
dispatch FSM:

```
ST_IDLE  --(primed & !config_err & winner_v & l_actv[hix[winner]])--> ST_DRIVE
ST_DRIVE --(unconditional)-------------------------------------------> ST_WB
ST_WB    --(unconditional)-------------------------------------------> ST_IDLE
```

`ST_DRIVE` and `ST_WB` are two states, so the derivation says `C = 2`, and the
smoke bench agrees: `svc_cycles / svc_jobs = 688 / 344 = 2.00` in the live
`test/cj_measured.txt` (the figure quoted since S3 is `708 / 354`, the same
ratio on an earlier program), with `min == max == 2` on every opcode the census
image exercises.

**⛔ But `svc_cycles` counts cycles where `st != ST_IDLE`.** That is the
engine's *occupancy* per job, not the *spacing* between the jobs it can
deliver. `ST_WB` assigns `st <= ST_IDLE` unconditionally, so the next job's
dispatch decision cannot be taken until the cycle *after* writeback. The FSM is
a **three-state cycle**, and a three-state cycle delivers one job every three
cycles however many of those cycles are labelled "service".

If the resource is unavailable to any other lane for three cycles per job while
the analysis charges two, then every `r_i` is computed with `C` one too small,
every margin is optimistic, and `B` is optimistic — **in the forbidden
direction, in the numbers we publish.**

⚠ This is not a claim that `C = 3`. It is the statement that the measurement on
record (`688 / 344`, and `708 / 354` before it) cannot answer the question, because it measures a
different quantity. The relabelling is owed regardless of how this comes out.

---

## 2. The quantity

**Δ — inter-dispatch spacing.** Let a *dispatch decision* be a cycle in which
the `ST_IDLE` arm's condition holds and the head slot is valid, i.e. the cycle
in which `st <= ST_DRIVE` is assigned. For consecutive dispatch decisions at
cycles `n_j` and `n_{j+1}`, `Δ_j = n_{j+1} − n_j`.

The quantity of interest is **`min Δ` over a saturated steady window** — the
floor the FSM can achieve, which is what bounds throughput and therefore what
RTA must charge.

⭐ **The minimum, not the mean.** A mean Δ reflects how often lanes happen to be
ready; it tells us nothing about the floor. And the minimum is the *cheap*
statistic to falsify: a single observed `Δ = 2` anywhere in the run refutes
`C = 3`. Refill queueing and EDF idleness can only make Δ **larger**, so an
inflated mean cannot hide a floor of 2 — but a floor that is never *exercised*
can, which §4 is about.

### 2.1 Not these

- **`svc_cycles / svc_jobs`** — occupancy, the quantity already on record.
- **Release-to-dispatch wall time** — includes EDF interference, which the
  recurrence already charges.
- **`Δ` averaged over the whole run** — arrival-limited at the shipped
  spacings (25, 45, 434, 414, 25 cycles), where the engine is idle almost
  always and Δ measures the *program*, not the engine.

---

## 3. The arms

Built with `test/make_smoke_image.py --five d0 d1 d2 d3 d4`, the recipe
`price_j_sweep.sh` and `run_dstar_check.py` already use.

| arm | delays | why |
|---|---|---|
| **S** (primary) | `40 40 40 40 40` | **Simultaneous release, port-feasible.** All five lanes share one delay, and `P8` makes the timestamp advance absolute, so once aligned they stay aligned forever: five lanes become ready in the *same* cycle, every 40 cycles. `d = 40 ≥ D* = 20` means the port has twice the time it needs, so every head is valid — **refill cannot be the limit**, which is the condition Wilson's ruling names. Each release instant yields a burst of 5 back-to-back dispatches and therefore 4 spacings of pure FSM throughput. |
| **T** | `60 60 60 60 60` | **The same structure with more slack.** If arm S's Δ floor is set by anything port-related, T must differ. If the floor is the FSM, T must read identically. A second arm whose only difference is slack is the cheapest available control on "did refill still bind?". |
| **U** (contrast) | `2 2 2 2 2` | **Oversubscribed.** `d = 2 ≪ D*`, so the port is the binding constraint (one refill per 4 cycles, engine-wide) and Δ should be *larger* than the FSM floor, not smaller. ⛔ Included as a **direction check only**: a reading here that is *below* arm S's floor would mean the instrument is miscounting dispatches, because no program can beat the FSM. |
| **V** (shipped) | the default `smoke_image` | Reported for the record, **not for the floor.** At the shipped spacings the engine is idle almost always; its Δ is arrival-limited and must not be read as a throughput measurement. Printed so that nobody later quotes the shipped program's mean Δ as `C`. |

---

## 4. Hypothesis and falsifier

> **Hypothesis (the value the published numbers assume): `min Δ = 2`.**
>
> **Falsifier: `min Δ = 3`** on arm S — that is, *no* pair of dispatch
> decisions anywhere in a saturated steady window is spaced fewer than three
> cycles.

### 4.1 The reading that is not a result

⛔⛔ `min Δ = 3` is only evidence about the FSM **if the floor was exercised**.
If arm S never puts a second eligible lane behind a dispatching one, then Δ ≥ 3
says the lanes arrived 3 apart, not that the engine cannot do better. So the
run must demonstrate the opportunity existed:

**`btb` — back-to-back opportunities.** Counted in each dispatch's `ST_WB`
cycle: is there a lane `L ≠ cur` with `l_live[L] && ready[L] &&
l_actv[hix[L]] && !l_armed[L]`? If so, a dispatch was *already eligible* before
the current one finished, and the following Δ is FSM-limited rather than
arrival-limited.

**`btb_min` is the deciding number** — the minimum Δ taken only over spacings
whose predecessor had a back-to-back opportunity. `min Δ` over all spacings is
reported beside it and must agree.

### 4.2 Preconditions — a run that fails any of these yields NO READING

1. `cycles run == NCYC` (the dump-task-shared-index defect: a run length that
   depends on how often the bench printed is not a controlled measurement).
2. Steady window ≥ 100,000 cycles, measured from `hdr_done + WARMUP`.
3. `primed` observed, `config_err` never observed, no lane halted mid-run
   (a timeout halt is not a timing reading).
4. **≥ 1,000 dispatch decisions** inside the window.
5. **`btb` ≥ 100** on arms S and T. Fewer means the burst did not form and the
   floor was not exercised — §4.1.
6. **Instrument cross-check:** the count of dispatch decisions (the `ST_IDLE`
   arm read literally) must **equal** the count of `st` 0→1 transitions. Two
   independent detections of the same event; a mismatch voids the run.
7. **Convergence:** no new minimum Δ in the second half of the window.
8. Arms S and T must report the **same** `btb_min`. They differ only in slack,
   so a disagreement means something other than the FSM is setting the floor
   and neither number is the one this document is about.

---

## 5. Disposition — decided here, before the number is known

### 5.1 If `btb_min = 2` (hypothesis holds)

`C = 2` stands. The occupancy figure is still **relabelled** as occupancy in
`gate_cj_bounds.py`, because it does not measure spacing whatever the spacing
turns out to be. §6 is done anyway.

### 5.2 If `btb_min = 3` (falsifier fires)

1. **`C = 3` for the analysis.** Re-quote every published `r_i` and margin with
   `C = 3`, **pyRTA primary** and ours as the safe-direction cross-check
   (ours ≥ pyRTA, else STOP).
2. `B = max(C_j − 1) = 2`.
3. Per-lane margins reported, not just the minimum.
4. A ledger entry, as an error and not a footnote: the published margins were
   computed with a `C` that measured occupancy rather than throughput.
5. ⛔ **`D*` is unaffected and must not be re-derived to compensate.**
   `D* = k · L_REFILL = 20` is a port-throughput threshold; it contains no `C`.
   Theorem 3's premises (`model/gate_j_proof_anchors.py` P8/P9) are untouched.
6. ⛔ The shipped claim `d_min ≥ D* → J = 1` is about *jitter*, not service
   time. If `C = 3` makes a shipped lane infeasible, that is a **margin**
   finding, not a reason to restate `J`.

### 5.3 If `btb_min > 3`, or arms S and T disagree, or `btb < 100`

**NO READING**, and that is the result. Record what the instrument did and do
not quote a `C` from it. ⛔ In particular, `btb_min = 4` must **not** be read as
"`C = 4`": at `d = 40` the port serves five refills per 40 cycles and a fourth
cycle could be port-related, which arm T is there to distinguish.

---

## 6. Owed regardless of the outcome — the 1.6t table

`model/a2/gate_j_program.py` prints `adm (U ≤ 1) = yes` at
`d_min = 8, 10, 12, 18` from

```python
def utilisation(d, k):  return k * C_SVC / float(d + C_SVC)
```

**`d + C` is wrong as a period.** `P8` makes a lane's timestamp advance
`+= d` from the *previous timestamp*, absolutely — so a lane's period is
exactly `d`, not `d + C`. (This is the same premise Theorem 3 needs, anchored
in `gate_j_proof_anchors.py`; the RTL comment at that line records that the
relative form drifts `k·(r − C)`.) The correct condition is

```
U = k · C / d  ≤  1
```

which admits `d ≥ k·C` — **10** at `C = 2`, **15** at `C = 3`, against the
`d ≥ 8` currently printed. Those rows are a false label on a green gate and are
being fixed in this round either way.

### 6.1 ⛔⛔ And the correction must not be allowed to excuse the known unsoundness

Tightening `admissible` has a consequence that would be convenient and must be
declared *before* the number is known, not discovered afterwards:

`gate_j_program.py` **EXCLUDES** inadmissible points from its
`sim ≤ derived` check. The recorded sweep has **ten admissible points
(`d = 8..18`) measuring above the derivation** — the unsoundness that retracted
the universal `J = 8`. Under `U = k·C/d`:

- at `C = 2`, admissible is `d ≥ 10`, so `d = 8, 9` leave the check — **8 of 10
  violations remain**;
- at `C = 3`, admissible is `d ≥ 15`, so `d = 8..14` leave the check — **only
  `d = 15, 16, 18` remain**.

⛔ **A correction that makes seven known violations disappear by re-scoping is
not a correction.** So, pre-registered: the ten points stay listed as
violations in the gate's output under their own heading, with both scopes
printed, whatever `admissible` comes to say about them. The retraction of the
universal `J = 8` is **not** reopened by this, and the gate must not become
able to report "sim ≤ derived at every admissible point" while the measurements
that killed that bound sit silently outside the scope.

---

## 7. What this cannot settle

- **Silicon.** Δ is measured in RTL simulation. The post-synthesis path report
  is a separate claim and remains owed, as `pe_engine.v`'s closing comment
  already records.
- **Whether `C` is opcode-dependent.** It is not, structurally — neither
  transition out of `ST_DRIVE` or `ST_WB` is conditional on the opcode — and
  the census image has checked `min == max == 2` occupancy on 8 of 8 opcodes.
  This document is about the *spacing*, which is opcode-independent by the same
  argument. It is stated, not re-measured.
- **The host channel.** `OP_SHIFT`'s byte load at `l_bitp[cur] == a_cnt` is a
  sticky-flag underrun, never a stall, by design (a stall would make `C`
  unbounded — the clock-stretch conclusion a third time). Arms S–V do not
  exercise it.
