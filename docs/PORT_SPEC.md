# PORT_SPEC — the fetch port and dispatch pipeline, read from the RTL

Ruling TH2. This is the input for the Lean formalisation of the `D*`
statement. It describes what `src/pe_engine.v` **does**, with a citation for
every clause. It proves nothing.

**Citations.** Line numbers are for `src/pe_engine.v` at **`3b37967`** (Ruling
TF), which changed the RTL (§0). The TF2-R commit that follows moved them
again, by a few dozen lines past the select, so for its changes (§0, last
rows) use the anchors. Line numbers drift whenever a comment
grows, so each clause also gives a **substring anchor**: text that must appear
in the RTL verbatim. `model/gate_j_proof_anchors.py` checks anchors the same
way. If the two disagree, the anchor wins. §6's measurements were taken on the
pre-TF RTL (`c8a4126` / `5cb00c1`) unless they say otherwise.

⚠ **`J_LANE_PROOF.md`'s premise table cites line numbers from before both
TH2 and TF. Use the anchors.**

## 0. Ruling TF: what changed in the RTL (for the Lean agent)

Three changes for 50 MHz timing, all in `src/pe_engine.v`:

| change | before | after | lines | anchor |
|---|---|---|---|---|
| **TF1** registered readiness and EDF key | `rel_due`, `ready` and `edf_key_off` were combinational over `now`, `l_timestamp`, `l_d` and `l_hcnt` | `due_q`, `hz_q` and `key_q` are registers that hold, **in every cycle, the value the old expressions had in that cycle**. They are computed one cycle ahead from next-state values: `now_n`, `ts_n` (the WB advance and the edge rebase), `ld_n` (the header write), and `l_hcnt`'s next value, written beside the counter | 1014–1024, 1405–1458, 2819–2827 | `due_q[ti] <= ~tf_diff(now_n, ts_n[ti]);` |
| **TF2** tree select | serial loop, four dependent compares | a tree: `(0,1)` and `(2,3)`, then their winners, then lane 4. **Proved equal** to the serial loop for every input (`formal/argmin_equiv.sby`, SymbiYosys k-induction). The must-fire is a broken tie rule, which fails | 1046–1067 | `---- BEGIN ARGMIN TREE ----` |
| **TF3** prefetch branch 1 | read the same-cycle `winner`; set `pl <= winner`, so the capture moved the round-robin position to `winner + 1` | reads the **previous cycle's** winner (`winner_q`, re-checked `l_live`). **Branch 1 no longer moves the round-robin pointer**, which is now its own register `prr`. `pl` is still the lane the in-flight refill serves | 1480–1490, 1923–1939, 1969 | `if (!pbr1) prr <= (pl == LANE_LAST) ? {LW{1'b0}} : pl + 1'b1;` |

**Ruling TF2-R (round 2), after the TF harden left the slow corner at
−3.49 ns.** Every remaining violator started at `l_live` and ended in the
dispatch registers through a 10-way, 24-bit select on the binary winner:

| change | what | anchor |
|---|---|---|
| **R1** per-lane head pre-select | `hw[i] = l_act[hix[i]]`, `hv[i] = l_actv[hix[i]]`: each lane's own head word and head-valid, a 2:1 mux on its own `l_sel`, in parallel with the tree. **Combinational, not a registered shadow** (Nathan's choice), so it is the same bit by definition and there is no copy to keep in step | `assign hv[gi] = l_actv[hix[gi]];` |
| **R2** one-hot winner | the tree also emits `winner_oh[4:0]`, the AND of node outcomes on each lane's path. Dispatch reads `w_act`, `w_hv`, `w_armed` through a flat AND-OR. `cur <= winner` keeps the binary index. Proved: `winner_oh == (winner_v ? 1 << winner : 0)` (`formal/argmin_equiv.sby`, with a must-fire that breaks lane 0's line) | `winner_oh[0] = !t4 & !t23 & !t1 & v01;` |
| **R3** release term fully registered | `rel_q` = `l_live & arrived & ~(l_armed & l_notmo)` for the current cycle, computed from **next** values. Every run-time write of `l_live` / `l_armed` / `l_notmo` goes to `live_n` / `armed_n` / `notmo_n`, and the registers and `rel_q` are written once at the end of the lane block. **A lane halted this cycle is not eligible next cycle.** Must-fire `M_TF2_LIVE_LATE` moves `census_image`'s stream in `test/run_lockstep.py` | `assign rel_due[gi] = rel_q[gi];` |

TF2-R changes **no behaviour anywhere**, including below `D*` and at cold
start. Measured against `3b37967`: see RESUME's TF2-R row.

**What this means for the proof:**
- **TF1 changes nothing observable.** The streams are byte-identical on every
  shipped admissible image (`test/run_lockstep.py`, in CI). The must-fire
  `M_TF1_LATE`, the naive retiming, moves all 12 streams.
- **TF2 changes nothing.** It is proved, not measured.
- **TF3 removes the starvation mechanism.** §1's "branch 1 relocates the
  pointer" is gone. On the arm that starved a lane for 16,468 cycles, the
  worst owed-fill wait is now 50 cycles to issue and 53 to capture over 4M
  cycles, with at most 12 refills ahead, and it does not grow with run
  length.
  - Above `D*` branch 1 fires only during priming, as before. Priming now
    finishes **one cycle later** on 7 of the 12 lockstep images. That is a
    cold-start difference TF4 allows, and it is listed by `run_lockstep.py`.
  - Branch 1 now starts a winner's head refill **one cycle later** than
    before, because it reads `winner_q`. That bears on Theorem 1's
    winner-blocked bound (§6).

Constants: `N_LANES = k = 5`, `SPL = 2` slots per lane, `L_REFILL = 4`.

---

## 1. TH2a: how the port chooses which owed refill to serve

There is one prefetch FSM. Its state is `pst ∈ {P_SCAN, P_REQ, P_WAIT, P_CAP}`
(`:1472`). It has two lane registers (`:1473–1490`):
- `pl`, the lane the in-flight refill serves;
- `prr`, the round-robin pointer (TF3).

The FSM runs only after the header load completes (`if (hdr_done)`, `:1910`).
In a `P_SCAN` cycle it evaluates exactly one of three branches, in this order
(`:1912–1940`):

| order | condition | action | lines | anchor |
|---|---|---|---|---|
| 1 | `winner_v_q && l_live[winner_q] && !l_actv[hix[winner_q]]`: the **previous cycle's** EDF winner is still live and its **head** is invalid | serve that **winner's head**: `pl <= winner_q`, `pbr1 <= 1`, `pslot <= l_sel[winner_q]` (the head), `paddr <= l_pc[winner_q]`, go to `P_REQ`. **`prr` is not touched.** | 1923–1928 | `if (winner_v_q && l_live[winner_q] && !l_actv[hix[winner_q]]) begin` |
| 2 | `l_live[prr] && want_fetch(prr)`: the lane **at the pointer** wants a fetch | serve lane `prr`: `pl <= prr`, `pbr1 <= 0`, its **head if the head is empty, else its spare**, `paddr <= fetch_addr(prr)`, go to `P_REQ` | 1929–1936 | `end else if (l_live[prr] && want_fetch(prr)) begin` |
| 3 | otherwise | advance the pointer: `prr <= (prr == LANE_LAST) ? 0 : prr + 1`. **This costs one cycle** per lane passed over. | 1937–1939 | `prr <= (prr == LANE_LAST) ? {LW{1'b0}} : prr + 1'b1;` |

After a **branch-2** capture the pointer moves to the lane after the one
served: `if (!pbr1) prr <= pl + 1 mod k` (`:1969`). After a **branch-1**
capture it does not move.

**So the answers to TH2a, exactly:**

- **Winner first.** Only the registered winner's head jumps the queue
  (branch 1). A non-winner whose head is invalid gets no priority. It is
  served by branch 2 when the pointer reaches it.
- **Owed refills are served in round-robin order, by the position of the scan
  pointer.** Branch 2 ranks owed refills by nothing else: **not** by lane
  index, **not** by EDF key, **not** by age. Within one lane, branch 2 fills
  the head before the spare.
- **Branch 1 borrows the port without moving the pointer** (TF3). So every
  owed refill is reached by the pointer within one rotation of branch-2 and
  branch-3 steps. Branch-1 refills can be interleaved, and each costs
  `L_REFILL`.
  - Before TF3, branch 1 set `pl <= winner`, and the capture moved the scan to
    `winner + 1`. That relocation is what starved a lane for 16,468 cycles
    below `D*` (§6).
- `want_fetch(ln)` (`:1549`) returns true in exactly two cases:
  - the lane's head is invalid; or
  - with `SPL > 1`, the spare is invalid and the head is **not** a chaining
    re-arm (`OP_REARM` with `level = 0`).

  A chaining re-arm's spare is deliberately left unfilled.
- `fetch_addr(ln)` (`:1520`) picks the address:
  - `l_pc` if the head is invalid (filling the head itself);
  - `l_base` if the head is a looping re-arm;
  - `l_fpc` otherwise (the successor pointer, advanced at every capture,
    `:1965`).
- **The store read port has one other client**, the header load. It has
  priority (`:1645`), but it finishes (`hdr_done`) before the prefetch FSM is
  enabled. During a run the prefetch is the only reader of the store.

## 2. TH2d: refill service time and the one-in-flight rule

| fact | lines | anchor |
|---|---|---|
| The four states form a fixed walk: `P_SCAN → P_REQ → P_WAIT → P_CAP → P_SCAN`. Every transition after `P_SCAN` is unconditional. | 1954, 1956, 1966 | `P_REQ:  pst <= P_WAIT;` / `P_WAIT: pst <= P_CAP;` |
| `P_CAP` writes the word and sets `l_actv[fix] <= 1`. `fix` is the slot **latched at the scan** (`pl`, `pslot`), not the lane's current head. | 1494, 1957–1960 | `wire [SIW-1:0]        fix = pl * SPL + (((SPL > 1) && pslot) ? 1 : 0);` |
| The address is latched at the scan (`paddr`) and is not recomputed at `P_REQ`. A writeback while the refill is in flight cannot redirect it. | 1683 | `s_wraddr <= paddr;` |
| **One in flight.** `pst` is a single register. No new scan happens until `P_CAP` returns to `P_SCAN`, and nothing preempts a started refill. | 1472, 1911–1972 | `reg [2:0]             pst;` |

**`L_REFILL = 4`** is counted from the `P_SCAN` cycle that issues the refill
to the cycle after `P_CAP`, when the valid bit is visible. In TH3 the probe
sees the issue at the `P_REQ` sample and the valid bit three samples later.
`wc − wi = 3` holds in every arm. A scan that serves nobody (branch 3) costs
1 cycle. With all five lanes wanting, the port completes one refill every 4
cycles.

`M_PFETCH_NOWAIT` (`:1951–1955`) removes `P_WAIT`. It is a mutant, not a
configuration.

## 3. TH2b: per-dispatch pipeline latencies

Unless stated, every term below is a combinational read of registered state.
Since TF1, the time compare, the key and the hold test are themselves
registers, holding the value the old expressions had in the same cycle.

| stage | definition | lines | anchor |
|---|---|---|---|
| **release** | `rel_due[i] = l_live & due_q[i] & ~(armed & no-timeout)`, where `due_q[i]` = `(now − l_timestamp[i] ≥ 0)` in this cycle (TF1, from `now_n`, `ts_n`). The job is released in the cycle where `now == l_timestamp`. | 1014–1015, 1451 | `assign rel_due[gi] = l_live[gi] & due_q[gi]` |
| **eligible** | `ready[i] = rel_due[i] & hz_q[i]`, where `hz_q[i]` = `(l_hcnt[i] == 0)` in this cycle (TF1, written beside the counter). **W1:** a lane is ineligible while its own SDA hold + setup counter runs. | 1016–1020, 2822–2827 | `assign ready[gi] = rel_due[gi] & hz_q[gi];` |
| **winner** | Minimum `edf_key_off` (= `key_q`, TF1) over the `ready` lanes. On a tie the lowest index wins. It is a tree since TF2, proved equal to the strict-`<` ascending loop. It is combinational over registers, so it is valid **in the same cycle** as `ready`. | 1024, 1046–1067 | `---- BEGIN ARGMIN TREE ----` |
| **decision** | In `ST_IDLE`, dispatch requires `primed && !config_err && winner_v`. An armed winner takes the timeout-halt branch instead. Otherwise: head valid → `st <= ST_DRIVE`, `cur <= winner`; head invalid → stall and count `jitter_cnt`. | 1989–2039 | `if (l_actv[hix[winner]]) begin` |
| **DRIVE** | One cycle. The pin registers are written here (C9 = START). Always `st <= ST_WB`. | 2041–2412 | `st <= ST_WB;` |
| **WB** | One cycle: `l_timestamp += a_dly` (absolute, P8); the slot lifecycle (§4); `st <= ST_IDLE` unconditionally. | 2415–2790 | `l_timestamp[cur] <= l_timestamp[cur] + {{(TS_W-DLY_W){1'b0}}, a_dly};` |
| **next decision** | The cycle after WB. The FSM is a three-state cycle, so dispatches are **≥ 3 cycles apart** (`C = 3` spacing, `:2922`). | — | `st <= ST_IDLE;` |

**Measured** with the TH2b probe (`probe_tb_lat.v`). Over every decision after
warm-up, for each listed image:

| image | release → eligible | eligible → decision | decision → DRIVE → WB → IDLE |
|---|---|---|---|
| five-lane d = 20..24 | 0 on all 41,048 decisions | 0..4 (lane 0) up to 0..12 (lane 4) | exactly 1, 1, 1 on all 45,615 |
| five-lane d = 60..64 | 0 | 0..2 up to 0..12 | 1, 1, 1 on all 16,129 |
| `ckheavy_image` (A2 subject) | 0 on all 33,678 | 0..4 up to 0..12 | 1, 1, 1 on all 37,427 |
| `corpus_i2c` | 0 | 0..2 up to 9..12 | 1, 1, 1 on all 4,393 |
| **`ckdense_image`** (non-admissible, W1 binds) | **0..5 / 0..6 / 0..7 / 0..8** on lanes 0–3 (≥ 1 on 3,047 decisions) | 0..5 up to 0..12 | 1, 1, 1 on all 33,719 |

- **The minimum release → decision is 0.** A lane that is the winner with a
  valid head is decided **in its release cycle**, DRIVEs the next cycle and
  writes back the cycle after. P7's "1 cycle of winner registration" is this
  decision cycle. No separate registration cycle exists.
- **eligible → decision** is EDF ordering plus any stall. On these arms it
  rises with lane index, as EDF predicts.
- **W1's hold wait (P9w)** is 0 on every admissible arm. On `ckdense` it
  reaches 8, which shows the probe can see it. Bound: a hold is loaded with
  `SDA_HS = SDA_HOLD + SDA_SETUP = 18` at a DRIVE, and only on the K and W2
  arms. Since TF1 those arms raise `hold_ld` (`:2161`, `:2274`, `:2359`,
  `:2377`) and the single load is at `:2819`. The counter counts down every
  cycle, at block level, whatever `st` is (`:2820–2845`). The pin lands at
  `l_hcnt == SDA_SETUP1` (`:2831`).

  ⇒ The lane is eligible again no earlier than 19 cycles after that DRIVE.
  Its next release waits `max(0, DRIVE + 19 − release)`. This is the
  `J_w1` term of `model/a2/program_a2.py` (W6).

## 4. TH2c: the slot lifecycle at writeback (P10)

Each lane has two slots, `hix[ln]` (the head) and `six[ln]` (the spare),
selected by `l_sel[ln]` (`:738–739`). In `ST_WB`, exactly one of these arms
runs (`:2663–2742`):

| dispatch kind | condition | head invalidated? | `l_sel` flips? | refill owed? | lines |
|---|---|---|---|---|---|
| **held clocked re-dispatch** (mid-byte SHIFT/SHIFTIN phase) | `ck_hold_eff` | no | no | **none** (Amendment A1) | 2663–2701 |
| **ordinary retire** | `a_op != OP_REARM` | **yes** | **yes** | **one**: the freed slot, now the spare | 2702–2723 |
| **looping re-arm** | `OP_REARM`, `level = 1` | **yes** | **yes** | **one**, fetched from `l_base` | 2724–2732 |
| **chaining re-arm** | `OP_REARM`, `level = 0` | no | no | **none**, and `want_fetch` leaves the spare unfilled | no arm: it matches none of 2663–2732 (`M_BUF_CHAINFLIP`, 2738–2742, is the mutant that adds one) |

**Which slot is the head, which is freed.** After a retiring WB of job `j`:

- The slot that held `j` is invalidated, and the select flips. **The new head
  is the old spare**, which holds the action for job `j + 1` if its refill has
  already landed.
- **The freed slot becomes the new spare.** The refill owed for it fetches the
  action for job **`j + 2`**.

**When it must be valid.** The freed slot is consumed when it is the head
again, which happens after WB of job `j + 1`, at the decision for job
**`j + 2`**. So:

- a refill owed at `WB(j)` has until **`decision(j + 2)`**;
- `decision(j + 2) ≥ release(j + 2) = release(j) + 2d`, by P8's absolute
  timestamp advance;
- `WB(j) = decision(j) + 2 ≤ release(j) + R_i + 2`, where `R_i` is the lane's
  maximum release → decision time.

⇒ **slack ≥ 2d − R_i − 2.** The deadline is release `j + 2`, not release
`j + 1`. A head is found invalid at decision `j + 1` only if the refill owed
at `WB(j − 1)` is still outstanding at `WB(j)`. In that case both slots are
owed at once and branch 2 fills the head first. TH3 observed both-slots-owed
directly at d = 20..24 (lane 4, slots 8 and 9 owed 12 cycles apart), with no
stall.

`ST_WB` is unconditional, so the cycle after it is a decision cycle (§3).

## 5. TH2e: cold start

| fact | lines | anchor |
|---|---|---|
| Reset clears every `l_actv` and `l_sel`. At `hdr_done` both slots of every lane are empty. | 1759, 1776, 1807, 1815 | `for (i = 0; i < NSLOT; i = i + 1) l_actv[i] <= 1'b0;` |
| **Dispatch is gated on `primed`**, not on `hdr_done`. | 1989–1995 | `primed` (the `ifndef M_NO_PRIME` arm) |
| **`now` does not advance until `primed`.** The schedule's `t = 0` begins after priming, so no job's response time contains a priming refill. Since TF1 the condition is the wire `now_inc`, which the registered readiness also reads. | 771–786, 1405–1409 | `wire now_inc = run && primed;` |
| `primed_q` latches **once**, when `hdr_done` holds and no live lane `want_fetch`es: both slots are full, except a chaining head's spare. Ordinary refill churn never revokes it. Only `!run` (HALT) clears it. | 1629–1642 | `if (hdr_done && !prime_unp) primed_q <= 1'b1;` |
| Priming refills go through the same FSM (§1). With `now` frozen, a lane whose timestamp is already due is a `ready` winner with an invalid head, so branch 1 can fire during priming. TH3 counted exactly **one** branch-1 issue per run on every port-feasible arm, at cold start (pre-TF). With TF3 branch 1 reads `winner_q`, and priming ends one cycle later on 7 of 12 lockstep images. | — | — |

**What holds before the first refill completes:**

- no lane can dispatch (`primed = 0`);
- `now` is frozen, so no release time passes;
- the port fills heads and spares through branches 1 and 2.

**At the first release:** every live lane's head is valid, and its spare is
valid unless the head is a chaining re-arm. This is the same invariant
steady state needs at every decision. TH3 measured **0 cold-start stalls**
on every arm. The only fills of never-filled slots were the priming fills:
6 to 10 per image, at most two per live lane.

⚠ A HALT (`run` low) clears `primed_q`, and the next run re-primes. A lane
halted by a timeout or a clock-stretch fault stops consuming. It owes no
refills and holds no deadlines.

## 6. What the Lean statement can and cannot lean on (RTL facts only)

- **Above `D*`, branch 1 never fires after priming. The port is then pure
  round-robin.** Measured on every port-feasible arm: `ISSUE head = 1`, the
  cold-start fill. On the d = 18 control branch 1 fires 49,919 times in 1M
  cycles, and arm C fires it 124,982 times.
  - **Re-measured on the TF RTL (`18f2c0e`), 2026-10-08: still holds.**
    `ISSUE head = 1` and 0 stalls on all 29 arms with every `d ≥ 20`: 17
    synthetic arms at 1M cycles (uniform 20..60, `20..24`, the drift and
    adversarial TH3 arms, `20 20 20 20 24`, `20 21 22 23 100`) and the 12
    admissible images at 200k. Probe `probe_tb_port_tf.v`, logs
    `probe_b1/`.
  - ⚠ **Below `D*` this no longer tracks stalls.** With TF3 branch 1 reads
    `winner_q`, so it can start a speculative head fill for the lane that
    just wrote back. On the two stall-free `d = 19` arms it fires 92 times
    (`19 20 21 22 23`) and 2,291 times (`19 23 19 23 19`) in 1M cycles,
    where the pre-TF PS table records 0. The dispatch stream is unchanged
    (C1: byte-identical to `3b37967`). So "branch 1 fired" is not evidence of
    a stall on the TF RTL, and the induction below must not use it as one.
- **Pre-TF, the arbitration was not starvation-free.** Below `D*`, on arm
  `12, 12, 12, 12, 100`, one owed spare waited 16,468 cycles, with 2,473
  refills served ahead of it. The cause was branch 1 relocating the pointer.
  **TF3 removed it:** on the same arm the worst wait is 48 / 50 cycles to
  issue at 1M / 4M cycles (51 / 53 to capture), with at most 12 refills
  ahead, and it does not grow. Branch 1 still borrows the port, so the bound
  on an owed fill's wait must charge the branch-1 refills interleaved with
  one rotation. It no longer has to charge a pointer reset.
- **This is circular as a premise and must be proved, not assumed.** Branch 1
  fires only when a winner's head is invalid, which is the very event the
  theorem excludes. The natural shape is an **induction over owed refills**:
  1. If every owed refill so far was captured before it was needed, no head
     was invalid, branch 1 never fired, and the scan is round-robin.
  2. Under round-robin, an owed fill waits behind at most:
     - the remainder of the one in-flight refill (≤ `L_REFILL − 1`);
     - one refill per other lane (`(k − 1) · L_REFILL`);
     - one scan cycle per lane passed over that wants nothing.
  3. That wait must fit inside the slack of §4: `2d − R_i − 2`.
- **Measured against that shape** (TH3a, five-lane d = 20..24): the worst
  free → capture wait was 22 cycles, and at most 5 refills were captured
  ahead of an owed one (the in-flight one plus four others). Lane 4's measured
  `R_i` is 12, so the slack is `2·24 − 12 − 2 = 34`. ⚠ This is measurement.
  The bound, its constant and `R_i` are for the Lean statement to fix.

### PS1–PS3: the candidate bound, measured against today's RTL (2026-10-07)

The candidate was: Lemma A `R_i ≤ (k−1)C = 12`; Lemma B "valid within
`(k+1)L − 1 = 23` of the WB"; Lemma C slack `≥ 2d − R_i − 2`. Together they
give `2d ≥ 37`, i.e. `d ≥ 19`. Runs were 1M cycles with probes
`probe_tb_port.v` and `probe_tb_lat.v`.

**Conventions.**
- *Valid from WB* is the first cycle a decision can read the slot as valid,
  minus the cycle of the WB that freed it.
- *Slack* is the consuming decision's cycle minus that first-valid cycle.
- `R_i` is release → decision.

| arm | stalls (window) | winner-head refills after priming | worst valid from WB | worst slack | worst `R_i` |
|---|---|---|---|---|---|
| 20 20 20 20 20 | 0 | 0 | 10 | ≥ 28 | — |
| 20 21 22 23 24 | 0 | 0 | **24** | ≥ 15 | 12 |
| 20 21 22 23 100 | 0 | 0 | 21 | ≥ 15 | — |
| 20 20 20 20 24 | 0 | 0 | 13 | ≥ 25 | — |
| 19 20 21 22 23 | 0 | 0 | **27** | ≥ 9 | 12 |
| 19 23 19 23 19 | 0 | 0 | 24 | ≥ 12 | 12 |
| **19 19 19 19 23** | **184,612** | 25,919 | — | — | 275 |
| **19 19 19 19 19** | **195,571** | 35,754 | — | — | 157 |
| 18 18 18 18 18 (control) | 177,287 | 22,431 | — | — | 154 |
| 18 19 20 21 22 (control) | 204,371 | 49,918 | — | — | 97 |

- **PS1: the boundary prediction `d ≥ 19` is FALSIFIED.** Five lanes at
  `d = 19` stall. The port is asked for `5 · 4 = 20` cycles of refill per 19.
  The cliff the sweep recorded at "d = 19" came from the recipe
  `19 20 21 22 23`, which has only **one** lane at 19, so port demand is
  below 1.
  - ⇒ `D* = k · L_REFILL = 20` is a **throughput** floor, and on the uniform
    family it is tight.
  - The latency condition `2d ≥ 37` is necessary, not sufficient. A sound
    statement needs **both** conditions.
  - The owed item in `gate_j_program.py` is closed with this record.
- **Lemma B's constant is one cycle short even above `D*`.** The worst valid
  from WB is 24, not 23, on `20..24`. On `19..23` it is 27, with branch 1
  silent and no stall: a lane can owe both slots at once (§4), so its second
  refill waits a second round-robin pass. The latency slack still held, at
  ≥ 9.
  - ⚠ This table is **pre-TF**. On the TF RTL (C3, 2026-10-08), `19..23`
    has worst valid from WB 28 and slack ≥ 8, and branch 1 is **not**
    silent (92 head fills, 0 stalls). `19 23 19 23 19` has 24 and ≥ 12,
    with 2,291 head fills and 0 stalls. Above `D*`, see §6.
- **Lemma A's bound (`R_i ≤ 12`) held on every stall-free arm.** It fails
  only where the port is saturated.
- **PS2: Lemma A's premise ("every same-lane dispatch gap > 12") is false
  on an admissible image.**
  - `ckheavy_image` (the A2 subject), lane 4, `d = 21`: the minimum gap is
    **12**, and 10 gaps are ≤ 13. A lane released at `d` and decided up to
    `R_i` late can be decided again `d − R_i` cycles later. The measured
    `R_4` is 11.
  - The same holds for held clocked re-dispatches. `ckheavy`'s clocked lanes
    (`d = 30..32`) bottom out at **22**, not `≥ d`.
  - Every other admissible image has a minimum gap ≥ 16. So no zero-delay
    back-to-back dispatch occurs on any of them, even though `pe_asm`'s
    `d_min` ignores zero-delay actions (`pe_asm.py:550`).
  - Gaps are bounded below by `d − R_i`, not by `d`.
- **PS3: `pe_asm` refuses `d_min < D*`** (`pe_asm.py:576–586`). The
  `_demo_tight` must-fire covers it. The chip itself refuses nothing: a raw
  image bypasses `pe_asm`, which is how every sub-`D*` arm above runs.
  - Aside, sub-`D*` only: on the saturated arms some lanes fall behind by
    about 2^15 cycles. Release → decision then reads ~32,800, which is the
    16-bit timestamp's signed window. 1.6b's spread assumption fails in
    overload, in a region nothing is claimed for.

`R_i` is a response-time quantity, so the port invariant and the EDF analysis
are coupled through it. The Lean statement needs that coupling stated
explicitly, or an independent bound on `R_i` such as pyRTA's.
