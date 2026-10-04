# T1–T4 — the per-lane jitter term, the `jitter_max` relabel, `NSLOT` as a
# parameter, and the stored-number audit

Wilson's T0–T4 after `3ca695e`. The pre-registration for T1 is
`docs/PREREG_J_LANE.md`, committed as **`8bc6979`, before the instrument
existed**; this document is the outcome and was written after measuring.

---

## T0 — the manifest records its toolchain

`test/artefacts.sha256` now carries four header lines (`python`, `iverilog`,
`verilator`, `yosys`). A hash that disagrees on another machine has two very
different causes — a recipe changed, or a different tool built the same recipe
— and the hashes alone could not tell them apart, which left "it must be the
tools" available as an unfalsifiable excuse for re-pinning a hash.

`test/toolchain.py` owns the probe, the line format **and** the parse, because
the writer (`make_smoke_image.py --all`) and the reader (`clean_room.py`) must
agree on all three; two copies of that is this project's most reliable bug. A
failed probe records `MISSING` rather than omitting the line, so a header
written without the full toolchain cannot read as though it had one.

The clean room prints stored-vs-live on any mismatch and names which cause it
is — including the case where the toolchain is **identical**, which is the one
that says "treat this as a recipe change". Priced by a self-test: the three
causes must print distinctly, and they do.

**Adding the header moved no hash.** All 17 artefacts unchanged, 10 of 10
reproduced in the clean room.

---

## T1 — `J_lane`: the falsifier never fired, and the aggregate does decompose

### The result

| arm | d | lanes adjudicated | `J_lane` | aggregate `jitter_max` |
|---|---|---|---|---|
| A | 12,13,14,15,16 (sub-`D*`) | 4 of 5 | **7** on every one | 11 |
| C | 8,100,100,100,100 | 5 of 5 | **7** (lane 0), 0 (lanes 1–4) | 7 |

**Pre-registered bound: `2 · L_REFILL + 1 = 9`. Falsifier: any complete release
interval with `sum > 9`. It did not fire on any cell — adjudicated or not.**

⭐ **And the prediction was at real risk.** The pre-registration staked itself
on a number already on record: the aggregate worst stall of **11**. The
hypothesis required that 11 to **decompose across lanes** — to be an
any-winner-blocked run in which the winner changed mid-stall rather than one
lane's wait. If one lane had owned the whole 11, the falsifier fired. It does
decompose: **the aggregate is 4 cycles larger than any single lane's wait.**

### What is open, and why it is open on convergence rather than on value

**Arm A lane 4 is not adjudicated.** Its measured `J_lane` is **7**, equal to
every other cell, but a strictly larger maximum appeared past the window
midpoint even at 4 M cycles, so the convergence precondition failed.

⚠ An unconverged maximum is a **floor**: more cycles can only raise it. So the
honest reading is "nothing above 7 was seen anywhere", not "7 is the bound".
Per the pre-registration this is the **third branch — neither holds nor
falsified** — because "holds" was defined over all ten runs, and rounding a
precondition failure up to a pass is exactly what the pre-registration forbids.

⛔ **OPEN RULING for Nathan:** whether a lane in this state is adjudicable at
all, or whether an arm must be added in which it keeps up. Adding one now would
be choosing an arm after seeing the result, so it is not done here.

### What the instrument measures, and what it refuses to

The predicate is `pe_engine.v`'s own stall branch with the winner pinned to one
lane, including the `!l_armed` term that `tb_witness.v` omits. Three numbers per
release interval:

- **`sum_L`** — blocked cycles per interval. The pre-registered quantity, and
  the conservative choice: a lane can be blocked, lose the winner, and be
  blocked again inside one interval, so the sum can only exceed the longest run.
- **`run_L`** — longest contiguous run. On every adjudicated cell `sum == run`,
  so the conservative choice turned out not to matter on these arms.
- **`wall_L`** — release→dispatch wall time, up to **63** cycles. ⛔ **Not
  bounded by this hypothesis and not meant to be**: it includes EDF
  interference, which the response analysis already charges through `C`.
  Recorded so a passing `J_lane ≤ 9` is never misread as "a lane dispatches
  within 9 cycles of release".

### Four instrument defects, each caught by a printed precondition

0. **The bench kept its own copy of the head index** — `lane*2 + l_sel` — and
   that copy failed **twice**. First as a 3-bit declaration, aliasing lane 4's
   slots (8, 9) onto lane 0's, found before any measurement. Then, at SPL = 1,
   where lane 1's head is slot 1 while `1*2` reads **lane 2's** slot: the
   instrument reported a per-interval sum of **1870** against a bound of 9.
   ⛔ A five-alarm result that was entirely the probe's own bug, and it was
   caught by the impossibility of the shape — `sum = 1870` with
   `longest run = 6` requires a lane to be winner-blocked ~300 times inside one
   release interval without ever dispatching, which the winner-first refill
   policy does not permit.
   ⚠ **And it is a fix reproduced on the unexamined axis.** `tb_smoke` had the
   identical copy, was found and fixed in this same session — and `tb_jlane`,
   the file carrying the warning comment about exactly this, was not. Both now
   read `dut.u_eng.hix[...]`. At SPL = 2 the copy was arithmetically identical,
   so the SPL = 2 results stand and were re-confirmed after the fix.

1. **The dump task shared the run loop's index.** Every chain dump reset `i` to
   `RING`, so the bench ran **2.3× longer than `NCYC`** — a reported window of
   468 099 cycles on a 200 000-cycle run. Only the lanes that printed were
   affected, so four cells were wrong and six were right. Caught because the
   window is a printed precondition with a known ceiling; the guard
   `cycles run vs requested` now exists.
   ⚠ **`tb_witness.v` has the same defect** — `tb_jlane` was written from its
   structure and inherited it. Fixed there too. The run was *longer* than asked
   (the safe direction for a worst-case search) and `cyc` counts real
   iterations, so the published chains stand: after the fix, chain 1 reproduces
   **stall 8 at cycle 4870**, the exact value and cycle `PREREG_U_PORT.md`
   records. What was wrong was the run-length *control*.
2. **The arm echo decoded the header from the prose.** `make_smoke_image.py`'s
   docstring omitted the `mode` bit, so every field below it was one bit adrift
   and the d = 12 arm echoed **"518"**. Caught because the echo is a
   precondition with a known answer. The docstring is corrected against
   `pe_isa.HDR_FIELDS`, which is the authority.
3. **A 3-bit head index.** `NSLOT = 10` needs four bits, so lane 4's slots
   aliased onto lane 0's. Found before any measurement, and it is why the RTL
   now derives `SIW` and dumps it through both elaborators.

### The transient was far longer than assumed, and the window had to be measured

The first controlled run found arm A lane 0 completing **6** release intervals
in 196 k cycles and **several thousand** between 196 k and 468 k. A 4000-cycle
warm-up was inside the transient by two orders of magnitude.

So the run is 1 M cycles with a 200 k warm-up — **raised after measuring the
transient, not guessed** — and two preconditions were added: **stationarity**
(the window's two halves must behave alike) and **convergence** (no strictly
larger maximum in the second half). Both are post-hoc, both make *more* cells
fail, and that is recorded as what they are.

⚠ **One escalation, at a fixed 4×, declared before the result.** A window
precondition is remedied by a longer window, but "keep running until it looks
stationary" is a stopping rule fitted to the data. So: exactly one retry, at
exactly 4×, validated by the same code as the first attempt, and every escalated
cell is reported as escalated. Arm A lanes 0 and 3 escalated and converged; lane
4 escalated and did not.

### Non-outcomes, as pre-committed

This publishes **no universal `J = 9`**. The holding cells are *analysis*.
Whether `pe_asm` may admit programs below `D*` at `J = 9` is a **separate
ruling**, after margins at `J = 9` are computed with **pyRTA**. The scoped claim
`d_min ≥ D* = 20 → J = 1` remains the only published timing claim.

---

## T2 — `jitter_max` relabelled as the aggregate it is

Read off the RTL, not off a label: `jitter_cnt` is **one counter shared by all
lanes**, incremented whenever the *current* winner is blocked and cleared only
on no-winner or at writeback. If the winner changes mid-stall the count carries
straight on across two lanes' waits and reports their sum as one run.

⇒ It is the longest **any-winner-blocked run length**, engine-wide. An upper
bound on any single lane's prefetch-miss wait — the safe direction — but not
that quantity. T1 measured the gap: **11 aggregate, 7 per lane.**

Relabelled in `src/pe_engine.v` (both the declaration and the increment site),
`test/tb_smoke.v` (the printed label was "measured J (max prefetch stall)",
which reads as per-lane), `model/a2/gate_cj_bounds.py`,
`model/a2/gate_j_program.py` and `docs/SPEC_V4_DOUBLE_BUFFER.md`.
`docs/PREREG_U_PORT.md` already stated it correctly — it is where the ruling
came from.

---

## T3 — `NSLOT` is a parameter, and the answer is the opposite of the expected one

### Built

`SPL` (slots per lane) is a parameter on `pe_engine` and
`tt_um_protocol_emulator`, defaulting to 2. `iverilog -Ptb_smoke.SPL_CFG=1`
builds the single-buffer engine. **A parameter, not a mutant `ifdef`**: the
single-buffer engine is a design alternative worth 169 flops, not a defect to be
killed.

The `ln*2 + (l_sel[ln] ? 1 : 0)` index was written out at **ten sites**; it is
now one combinational wire per lane (`hix`, `six`, plus `fix` for the refill in
flight). Ten copies of an index cannot be made depth-independent one at a time.

Two things forced the shape, both found by tools rather than by review:

- **Yosys rejects a function call inside a function body** ("Non-constant
  function call in constant expression"), twice — once per calling function.
  iverilog and `tb_smoke` accepted it both times. Exactly what
  `test/yosys_check.sh` exists for: a simulator cannot see unsynthesisable.
- **`tb_smoke` kept its own copy of the index**, and at SPL = 1 `lk*2` is the
  wrong slot — lane 1's head is slot 1, the formula gives 2. The invariant
  compared lane 1's PC against lane 2's action word and **failed 3207 times on
  a design that was behaving correctly**. It now reads `dut.u_eng.hix[lk]`.
  Same file that once kept a private `exp_act[23:2]` slice.

**Flop count is unchanged** — 6126 under one script on both trees, measured by
synthesising `3ca695e` and the working tree side by side rather than comparing
against a figure in a document. (My first reading of "+99 flops" was exactly
that recall error.) Cells +33, no flops.

### Correctness first

| | tb_smoke | edges (lane 0 / 1) | measured C | select-bit flips |
|---|---|---|---|---|
| SPL = 2 | PASS | 130 / 84 | 2.00 | 320 |
| SPL = 1 | PASS | 130 / 84 | 2.00 | **0** |

Identical pin behaviour and `C`; SPL = 1 correctly never swaps. A performance
number from an unverified configuration is a measurement of nothing — and that
is precisely what the retracted benefit claim was.

### Measured, on the J sweep's own recipe

| d | double (SPL = 2) | single (SPL = 1) |
|---|---|---|
| 8 | 10 | 8 |
| 12 | 11 | 11 |
| 16 | 11 | 9 |
| 18 | 11 | 8 |
| **19** | **0** | 8 |
| **20** | **0** | 6 |
| **21** | **0** | 4 |
| **25** | **0** | 1 |
| **30** | **0** | 1 |

- **double**: the cliff lies in (18, 19]; stall 0 at and above it.
- **single**: the stall **never reaches 0** anywhere in the swept range. Its
  cliff is **above 30** — not located, and not absent.

### ⇒ The double buffer is what makes the published claim true

In the scoped region (`d ≥ D* = 20`) the double buffer stalls **0** and the
single buffer stalls up to **6**. So `d_min ≥ D* → J = 1` **holds only at
SPL = 2**; at SPL = 1 the same programs stall and `J` would be at least 7.

**RECOMMENDATION: KEEP IT** — the opposite of what T3 anticipated, and larger
and in a different place than the retracted "11 → 7" claimed. ⚠ Nathan rules.

⛔ **And my own gate got this backwards first.** Its verdict took the worst
stall over the *whole* swept range, which includes `d < D*` where neither depth
is port-feasible and both read 11 — so the columns tied and it printed
"LOWERS NEITHER, remove 169 flops", directly under a table saying the opposite.
An exact maximum over the wrong range, and it also treated "no cliff found" as
"no difference" rather than "worse than everything swept". The published claim
is scoped to `d ≥ D*`, so that is where the comparison is made.

### The old benefit claim, and the old record

The "11 → 7" headline is **retracted** in `docs/SPEC_V4_DOUBLE_BUFFER.md`, and
`gate_j_program.py` no longer *computes* it — a retraction in the docs while
the gate still prints the number is the two-copies defect.

`SWEEP_SINGLE` is now buildable and **its stored values are contradicted** at 5
of 6 shared points (d = 16: stored 0, measured 9; d = 25: stored 0, measured 1).
Withdrawn, not re-fitted, and retained only as a labelled record.

---

## T4 — the stored-number audit

`model/gate_stored_numbers.py`. **51 constant collections scraped, 11 tabled as
stored numbers, 40 excluded by name as specifications, 0 unreviewed.** Every
site is exactly one of:

- **LIVE** (4) — recomputed in the same run; the stored value is a regression
  pin. `gate_pyrta.EXPECTED_R`, `gate_j_sound.EXPECTED`,
  `gate_reset_audit.ALLOWED`, `gate_mutant_arms.EXPECT`.
- **RECORD** (5) — stored from a run not repeated in-gate; **must carry a
  recipe file that exists**. `SWEEP`, `SWEEP_SINGLE`, `TCHECKER_RECORDED`,
  `PYRTA_SHIPPED`, `DOUBLE_BUFFER_COST`.
- **LEDGER** (2) — immutable by design, and a ledger with a recipe is a
  finding. `DOUBLE_BUFFER_PREREG`, `DIGEST_LEDGER`.

A stored number is not forbidden — foreign-tool results and pre-registrations
*should* be stored. What is forbidden is a stored number with no way back to its
source, which is what `SWEEP_SINGLE` was.

**Still carrying a caveat:** `DOUBLE_BUFFER_COST.flops_before` was measured on
the pre-double-buffer tree with **no commit ref recorded**, so its recipe
reproduces `flops_after` only and the delta is not re-derivable from HEAD alone.
Tabled with that stated rather than quietly accepted.

Priced by six must-fires: a bogus anchor, a missing file, a recipe-less RECORD,
a RECORD whose recipe file is missing, a re-runnable LEDGER — all rejected — and
a sound RECORD accepted, so the checks do not simply reject everything.
⭐ The coverage check caught **this gate's own new sweep constant** on the
commit that added it, and the exclusion list's first version had **10 of 32
names that were never scraped at all** — assembled from a grep instead of from
the scraper, which is why the stale-exclusion check exists.

---

## Suite at this commit

`run_a2` **30 of 30** · `price_gates` **13 of 13 red** · `run_mutants`
**4 of 4** · `tb_smoke` PASS **at both depths** · `tb_edge` **5 of 5** · cocotb
**8 of 8** · `price_j_sweep` PASS on the scoped claim · `gate_corpus_trace`
**7 of 8, 1 open** (`corpus_spim`, pre-existing) · ruling-audit, one-encoder
(**15 values, both elaborators agree**), mutant-arms, reset-audit, `pe_asm`,
clean room (**10 of 10, hashes matched, must-fire firing**), **stored-numbers
PASSED** · `yosys_check` clean, 0 multi-driver, static assertion fires.

⚠ `gate_mutant_arms` **correctly failed first**: the depth guard's explanatory
comment landed *inside* the `ifndef M_BUF_SWAP` arm ("5 COMMENT lines inside an
arm … DRIFT: 7 diff lines, expected 2"). A mutant arm wraps the minimal delta
and nothing else — the same rule that caught the 1.6s config guard landing in an
`M_NO_PRIME` arm.
