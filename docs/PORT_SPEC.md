# PORT_SPEC — the fetch port and dispatch pipeline, read from the RTL

Ruling TH2. This is the input for the Lean formalisation of the `D*`
statement. It describes what `src/pe_engine.v` **does**, with a citation for
every clause. It proves nothing.

**Citations.** Line numbers are for `src/pe_engine.v` at `c8a4126`, the last
commit that changed the RTL. Line numbers drift whenever a comment grows, so
each clause also gives a **substring anchor**: text that must appear in the
RTL verbatim. `model/gate_j_proof_anchors.py` checks anchors the same way. If
the two disagree, the anchor wins.

⚠ **`J_LANE_PROOF.md` cites P4 as lines 1075–1082. Those lines are stale.**
The branch now sits at 1772–1777 (§1 below). The premise's anchor is
unchanged and still present.

Constants: `N_LANES = k = 5`, `SPL = 2` slots per lane, `L_REFILL = 4`.

---

## 1. TH2a: how the port chooses which owed refill to serve

There is one prefetch FSM. Its state is `pst ∈ {P_SCAN, P_REQ, P_WAIT, P_CAP}`
and its lane pointer is `pl` (`:1339–1342`). The FSM runs only after the
header load completes (`if (hdr_done)`, `:1757`). In a `P_SCAN` cycle it
evaluates exactly one of three branches, in this order (`:1759–1781`):

| order | condition | action | lines | anchor |
|---|---|---|---|---|
| 1 | `winner_v && !l_actv[hix[winner]]`: the current EDF winner's **head** is invalid | serve the **winner's head**: `pl <= winner`, `pslot <= l_sel[winner]` (the head), `paddr <= l_pc[winner]`, go to `P_REQ` | 1767–1771 | `if (winner_v && !l_actv[hix[winner]]) begin` |
| 2 | `l_live[pl] && want_fetch(pl)`: the lane **at the pointer** wants a fetch | serve lane `pl`: its **head if the head is empty, else its spare** (`pslot <= l_actv[hix[pl]] ? !l_sel[pl] : l_sel[pl]`), `paddr <= fetch_addr(pl)`, go to `P_REQ` | 1772–1777 | `end else if (l_live[pl] && want_fetch(pl)) begin` |
| 3 | otherwise | advance the pointer: `pl <= (pl == LANE_LAST) ? 0 : pl + 1`. **This costs one cycle** per lane passed over. | 1778–1780 | `pl <= (pl == LANE_LAST) ? {LW{1'b0}} : pl + 1'b1;` |

After every capture the pointer moves to the lane **after** the one just
served: `pl <= pl + 1 mod k` (`:1808`). This includes a capture issued
through branch 1, where `pl` had been set to `winner`.

**So the answers to TH2a, exactly:**

- **Winner first.** Only the EDF winner's head jumps the queue (branch 1). A
  non-winner whose head is invalid gets no priority. It is served by branch 2
  when the pointer reaches it.
- **Owed refills are served in round-robin order, by the position of the scan
  pointer.** Branch 2 ranks owed refills by nothing else: **not** by lane
  index, **not** by EDF key, **not** by age. Within one lane, branch 2 fills
  the head before the spare.
- **Branch 1 relocates the pointer.** A winner-head refill sets `pl` to the
  winner, and the capture then sets it to `winner + 1`. The round-robin
  position is therefore reset by every branch-1 refill. Branch 1 is the only
  way a lane can be passed over more than once per rotation (§6).
- `want_fetch(ln)` (`:1404–1427`) returns true in exactly two cases:
  - the lane's head is invalid; or
  - with `SPL > 1`, the spare is invalid and the head is **not** a chaining
    re-arm (`OP_REARM` with `level = 0`).

  A chaining re-arm's spare is deliberately left unfilled (`:1421–1423`).
- `fetch_addr(ln)` (`:1375–1388`) picks the address:
  - `l_pc` if the head is invalid (filling the head itself);
  - `l_base` if the head is a looping re-arm;
  - `l_fpc` otherwise (the successor pointer, advanced at every capture,
    `:1806`).
- **The store read port has one other client**, the header load. It has
  priority (`:1499–1541`), but it finishes (`hdr_done`) before the prefetch
  FSM is enabled. During a run the prefetch is the only reader of the store
  (`:1500–1502`).

## 2. TH2d: refill service time and the one-in-flight rule

| fact | lines | anchor |
|---|---|---|
| The four states form a fixed walk: `P_SCAN → P_REQ → P_WAIT → P_CAP → P_SCAN`. Every transition after `P_SCAN` is unconditional. | 1795, 1797, 1807 | `P_REQ:  pst <= P_WAIT;` / `P_WAIT: pst <= P_CAP;` |
| `P_CAP` writes the word and sets `l_actv[fix] <= 1`. `fix` is the slot **latched at the scan** (`pl`, `pslot`), not the lane's current head. | 1349, 1800–1801 | `wire [SIW-1:0]        fix = pl * SPL + (((SPL > 1) && pslot) ? 1 : 0);` |
| The address is latched at the scan (`paddr`) and is not recomputed at `P_REQ`. A writeback while the refill is in flight cannot redirect it. | 1532–1538 | `s_wraddr <= paddr;` |
| **One in flight.** `pst` is a single register. No new scan happens until `P_CAP` returns to `P_SCAN`, and nothing preempts a started refill. | 1340, 1758–1811 | `reg [2:0]             pst;` |

**`L_REFILL = 4`** is counted from the `P_SCAN` cycle that issues the refill
to the cycle after `P_CAP`, when the valid bit is visible. In TH3 the probe
sees the issue at the `P_REQ` sample and the valid bit three samples later.
`wc − wi = 3` holds in every arm. A scan that serves nobody (branch 3) costs
1 cycle. With all five lanes wanting, the port completes one refill every 4
cycles.

`M_PFETCH_NOWAIT` (`:1792–1796`) removes `P_WAIT`. It is a mutant, not a
configuration.

## 3. TH2b: per-dispatch pipeline latencies

Every term below is a combinational read of registered state unless stated.

| stage | definition | lines | anchor |
|---|---|---|---|
| **release** | `rel_due[i] = l_live & (now − l_timestamp[i] ≥ 0) & ~(armed & no-timeout)`. The job is released in the cycle where `now == l_timestamp`. | 995–996 | `assign rel_due[gi] = l_live[gi] & ~diff[TS_W-1]` |
| **eligible** | `ready[i] = rel_due[i] & (l_hcnt[i] == 0)`. **W1:** a lane is ineligible while its own SDA hold + setup counter runs. | 997–1001 | `assign ready[gi] = rel_due[gi] & (l_hcnt[gi] == {HOLDW{1'b0}});` |
| **winner** | Minimum `edf_key_off` over the `ready` lanes. On a tie the lowest index wins (strict `<` in an ascending loop). It is combinational, so it is valid **in the same cycle** as `ready`. | 1004, 1016–1027 | `if (ready[k] && (!winner_v \|\| edf_key_off[k] < best)) begin` |
| **decision** | In `ST_IDLE`, dispatch requires `primed && !config_err && winner_v`. An armed winner takes the timeout-halt branch instead. Otherwise: head valid → `st <= ST_DRIVE`, `cur <= winner`; head invalid → stall and count `jitter_cnt`. | 1828–1878 | `if (l_actv[hix[winner]]) begin` |
| **DRIVE** | One cycle. The pin registers are written here (C9 = START). Always `st <= ST_WB`. | 1880–2252 | `st <= ST_WB;` |
| **WB** | One cycle: `l_timestamp += a_dly` (absolute, P8); the slot lifecycle (§4); `st <= ST_IDLE` unconditionally. | 2254–2630 | `l_timestamp[cur] <= l_timestamp[cur] + {{(TS_W-DLY_W){1'b0}}, a_dly};` |
| **next decision** | The cycle after WB. The FSM is a three-state cycle, so dispatches are **≥ 3 cycles apart** (`C = 3` spacing, `:2750–2768`). | 2628 | `st <= ST_IDLE;` |

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
  arms (`:2000`, `:2113`, `:2198`, `:2216`). It counts down every cycle, at
  block level, whatever `st` is (`:2654–2667`). The pin lands at
  `l_hcnt == SDA_SETUP1` (`:2659`).

  ⇒ The lane is eligible again no earlier than 19 cycles after that DRIVE.
  Its next release waits `max(0, DRIVE + 19 − release)`. This is the
  `J_w1` term of `model/a2/program_a2.py` (W6).

## 4. TH2c: the slot lifecycle at writeback (P10)

Each lane has two slots, `hix[ln]` (the head) and `six[ln]` (the spare),
selected by `l_sel[ln]` (`:738–739`). In `ST_WB`, exactly one of these arms
runs (`:2502–2581`):

| dispatch kind | condition | head invalidated? | `l_sel` flips? | refill owed? | lines |
|---|---|---|---|---|---|
| **held clocked re-dispatch** (mid-byte SHIFT/SHIFTIN phase) | `ck_hold_eff` | no | no | **none** (Amendment A1) | 2502–2540 |
| **ordinary retire** | `a_op != OP_REARM` | **yes** | **yes** | **one**: the freed slot, now the spare | 2541–2562 |
| **looping re-arm** | `OP_REARM`, `level = 1` | **yes** | **yes** | **one**, fetched from `l_base` | 2563–2571 |
| **chaining re-arm** | `OP_REARM`, `level = 0` | no | no | **none**, and `want_fetch` leaves the spare unfilled | no arm: it matches none of 2502–2571 (`M_BUF_CHAINFLIP`, 2577–2581, is the mutant that adds one) |

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
| Reset clears every `l_actv` and `l_sel`. At `hdr_done` both slots of every lane are empty. | 1611, 1628, 1659, 1667 | `for (i = 0; i < NSLOT; i = i + 1) l_actv[i] <= 1'b0;` |
| **Dispatch is gated on `primed`**, not on `hdr_done`. | 1828–1834 | `primed` (the `ifndef M_NO_PRIME` arm) |
| **`now` does not advance until `primed`.** The schedule's `t = 0` begins after priming, so no job's response time contains a priming refill. | 771–786 | `else if (run && primed) now <= now + 1'b1;` |
| `primed_q` latches **once**, when `hdr_done` holds and no live lane `want_fetch`es: both slots are full, except a chaining head's spare. Ordinary refill churn never revokes it. Only `!run` (HALT) clears it. | 1484–1497 | `if (hdr_done && !prime_unp) primed_q <= 1'b1;` |
| Priming refills go through the same FSM (§1). With `now` frozen, a lane whose timestamp is already due is a `ready` winner with an invalid head, so branch 1 can fire during priming. TH3 counted exactly **one** branch-1 issue per run on every port-feasible arm, at cold start. | — | — |

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
- **The arbitration is not starvation-free in general.** Below `D*`, on arm
  `12, 12, 12, 12, 100`, one owed spare waited 16,468 cycles, with 2,473
  refills served ahead of it. The cause is branch 1 relocating the pointer
  (§1). Round-robin fairness therefore holds only while branch 1 is silent.
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

`R_i` is a response-time quantity, so the port invariant and the EDF analysis
are coupled through it. The Lean statement needs that coupling stated
explicitly, or an independent bound on `R_i` such as pyRTA's.
