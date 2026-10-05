# The coverage sweep — what has never run

**Ruling (Wilson):** *"The bigger move code is pointing at: a coverage sweep,
not more one-at-a-time finds … Verilator line, branch and toggle coverage
across every bench (`--coverage`, free), merged into one report. Include the
peer models … Every uncovered branch, FSM state, opcode arm and peer branch
gets either a test that reaches it, or a written reason why it's unreachable,
checked like the reset allowlist … It becomes a gate: new uncovered RTL fails
CI unless justified. That's the systematic version of 'what else has never
run,' and it should come before new features."*

**Built, and it earned its keep immediately.** 19 arms over 10 benches, merged
into one report, gated. The design is **95–100% line** and **90–93% branch**
covered. The findings are not in those percentages — they are in the 37 points
that are named below.

---

## 1. The headline findings

| | finding |
|---|---|
| ⛔⛔ | **`fram_spi.v`'s entire command decoder has never executed.** 18 of its points are dark — `WREN`, `WRDI`, `RDSR`, `RDID`, `READ`, `WRITE` and the `P_AHI`/`P_ALO`/`P_DATA` phases alike. Bits *are* shifted in (the assembly block is covered), so the peer is wired and clocked; `byte_done` simply never fires at a `negedge sck` with the part selected. **This is the same shape as the I²C peer defect sigrok found** — a corpus program that drives the bus without ever assembling a byte the peer accepts. |
| ⛔⛔ | **No byte has ever been written into the I²C peer's memory.** `P_WDATA`, which holds `mem[addr] <= shin`, has count 0. |
| ⛔⛔ | **`lane_underrun` and `tx_full_sticky` have never been SET by any test.** Both are status bits the host reads, and both are asserted *clear* as a precondition by `tb_tx` and by `host_feed.vh`'s `hf_check`. Every run to date proves only that they do not fire spuriously; their set paths are unverified. |
| ⛔ | **Half of the 1.6s load-time refusal has never fired.** The `clkpin == pin` guard is exercised by `tb_tx +BADCLK=1`; the `pin >= N_UIO` guard on an open-drain lane, on *either* pin, is not. |
| ⚠ | **`RX_SERIAL` is a parameter no configuration ever sets.** Its `!= 0` arm's `else` is shipped source that nothing executes. **This needs a ruling** — sweep it as a build arm, or delete it. |

### 1.1 A correction to a published claim

`docs/SPEC_V4_I2C_CERTIFIED.md` §6 says *"the peer's `P_AHI`/`P_ALO` phases are
still unexercised."* Coverage says **`P_AHI` executes 13 times**; `P_ALO` is the
unexercised one.

⭐ And the sharper consequence, which the certification did not state: the
certified frame is `S | dev | A | one byte | A | P`, and the peer consumes that
second byte as `addr[AW-1:8]` at `P_AHI` — **not as data**. sigrok's
`Data write 5B` is correct at the I²C level (it is simply the second byte), and
the certification stands for exactly what it claimed — framing and byte values
on the wire, adjudicated by a foreign decoder. But **the FRAM write itself has
never completed**, and the two are easy to conflate.

---

## 1a. Ruling (a) item 1, closed — and one correction, one new defect

**Closed:** 7 points, uncovered 37 → **30**, OWED 32 → **25**.

| point | how |
|---|---|
| `pe_engine.v:1627` `lane_underrun` SET | `tb_status +MODE=0` starves the TX lanes; the flag sets on lanes 0 and 1 **and no other**, lane still **live** |
| `project.v:412` `tx_full_sticky` SET | `tb_status +MODE=1` overruns queue 2; `tx_cnt[2]` shown full first, **both stored bytes survive** |
| `pe_engine.v:1158, 1352, 1446` the reserved index | `pinnone_image.hex` + `tb_pinrange +MODE=1` — header, `OP_SHIFT` and `OP_SHIFTIN` all on `PIN_NONE` |
| `pe_engine.v:1143, 1145` the OD refusal | `tb_pinrange +MODE=0` — **see the correction below** |

### ⛔ CORRECTION: the open-drain refusal was never untested

I reported *"half the 1.6s load-time refusal has never fired."* **Wrong.**
`cfgerr_image.hex` is `hdr(UO0, UO0, 0, ...)` — open-drain with **both** pins at
`UO0 = 8 ≥ N_UIO = 8` — and `test/test.py` has run it as
`test_config_error_refuses_to_run` all along. Measured directly: under that
image, 1143's and 1145's taken arms each fire once.

They read as uncovered because **the cocotb toplevel `tb.v` is the one bench
`benchset.py` excludes** (no self-checking PASS line for a `--binary` run).
⇒ This is the **second** false gap from that blind spot — §5 item 1 of this
very document warns about it. A sweep with a declared exclusion keeps
manufacturing false gaps unless the excluded bench's *stimulus* is brought
somewhere measurable, which `tb_pinrange +MODE=0` now does (with a Verilog-side
assertion, so the refusal no longer rests on cocotb alone).

### ⛔⛔ NEW DEFECT: `pin_in[a_pin]` is read out of range, and the X leaves the chip

The reserved-index arm puts **X on `ser_d` (`uo_out[4]`) for 112 cycles** —
exactly its number of `OP_SHIFT` dispatches.

`pin_in[a_pin]` is read with **no `pin_real` guard** at `pe_engine.v:745`,
`:1502` and `:1524`. With `a_pin = PIN_NONE = 15` against a `[11:0]` vector,
`OP_SHIFTIN`/`OP_READBIT` samples out of range; the X lands in `l_rx`, then
`rx_data`, then the serial readback, and leaves the chip while `ser_v` is high —
so a host would sample it.

⭐ **It is the mirror of a defect already fixed.** The WRITE side was guarded
after the `pin_out[12]` incident — `pin_real` at 1352, `clk_real` at 1428, the
`pin_pp` guard at 1158 — and the SAMPLE side was not. *A fix on one axis
repeats the error on a parallel one.*

⚠ **Controlled, so it is not a property of the check:** `smoke_image`,
`five_image` and `cfgerr_image` all give **zero** serial X; only the
reserved-index program produces it. And the X check is two-state-vacuous under
Verilator, so it is evidence only in an iverilog run.

⇒ **OWED RULING.** Sample a defined 0 on a non-real pin, or refuse a SHIFTIN
that names the reserved index? The second would be wrong for an SPI target,
which names `PIN_NONE` as its *clock* deliberately — but the data pin is a
different question. Not fixed unilaterally.

## 2. What the sweep is

| | |
|---|---|
| `test/benchset.py` | **one declaration** of how every bench is built and run. It **enumerates `test/tb*.v` from disk** and fails on a bench with neither a config nor a written exclusion — ruling 3 applied to the bench set itself. The invocations had been scattered across eight scripts; a ninth copy would have drifted. |
| `test/coverage_sweep.sh` | builds each arm with `--coverage`, runs it, merges with `verilator_coverage`, writes `merged.dat` / `merged.info` / annotated sources. |
| `test/gate_coverage.py` | adjudicates the measurement against a classification table, and is wired into `ci/run_gates.sh` (now **14 gates**). |

### 2.1 The three metrics, as the tool actually provides them

Verilator emits `v_line`, **`v_branch`** and `v_toggle` points natively — all
three of the ruling's metrics exist. ⚠ `--coverage` turns on line and toggle;
there is no `--coverage-branch` switch, but branch points are emitted anyway as
part of line coverage, one per basic block, so each arm of an `if`/`case`
carries its own point.

⛔ **"Uncovered" is per ARM, not per line**, and reading it as "never ran" would
be flatly wrong for several entries: `fram_i2c.v:235` executes 28 times and
`:251` executes 2,845,919 times, and both are listed because their *true* arm
is never taken.

### 2.2 The numbers

| file | line | | branch | | toggle | |
|---|---|---|---|---|---|---|
| `src/pe_engine.v` | 60 | **95.0%** | 72 | **90.3%** | 1336 | 82.2% |
| `src/pe_store.v` | 3 | **100%** | 6 | **100%** | 69 | 95.7% |
| `src/project.v` | 15 | **100%** | 44 | **93.2%** | 446 | 83.4% |
| `test/fram_i2c.v` | 18 | 88.9% | 14 | 71.4% | 91 | 50.5% |
| `test/fram_spi.v` | 17 | **35.3%** | 10 | **30.0%** | 50 | 46.0% |

⚠ Verilator's own global "26%" is toggle-dominated and says nothing useful; the
per-file, per-kind split is the measurement.

---

## 3. What the gate claims

**No uncovered line-or-branch point in the design or the peer models outside
the classification table.** 37 points, as:

- **4 `UNREACHABLE`** — with the mechanism *checked structurally*, not asserted
- **32 `OWED`** — debt, each naming the test that would reach it
- **1 `DEAD_CONFIG`** — `RX_SERIAL`, awaiting a ruling

⛔ **A green means "nothing NEW went uncovered"** — which is precisely the
gating property the ruling asks for. It does **not** mean the design is
covered. The 32 owed points are debt, and listing them per point is how the
debt stays visible instead of dissolving into a percentage.

The gate also fails on a **stale** entry, in both directions: an `UNREACHABLE`
point that got covered means **the written reason was false** (the most
important thing it can say), and an `OWED` point that got covered means the
debt was paid and the entry now claims something untested is untested. Without
that the table could only grow, and a list that cannot shrink is a list nobody
prunes.

### 3.1 The `UNREACHABLE` reasons are machine-checked

A reason like *"all eight opcodes are handled"* is a **count**, and this project
has a rule about counts. So:

- **`a_op`'s `default`** — the arms are resolved to their numeric encodings and
  compared against the selector's whole space: 3 bits, 8 values, all named.
- **`st`'s and `pst`'s `default`** — these do **not** fill their space (3 of 4,
  4 of 8). What makes them unreachable is that *nothing ever assigns an unnamed
  encoding*, so **that** is what is checked: every `<=` to the selector must
  write a named arm. ⚠ This is reachability *from reset* only — a corrupted
  flop still lands in the default, which is why the arm stays in the RTL and
  why `gate_reset_audit` underwriting the selector's reset matters.
- **`H_IDLE`'s `else`** — every `hst <= H_IDLE` must clear `hdr_done` within
  six lines, checked at both sites.

⭐ **Both of these checks failed on their first run against reasons that were
correct**, and each failure was mine: the opcode scan captured only the first
name of a multi-label arm (`OP_LEVEL, OP_START, OP_STOP:` read as one opcode),
and the assignment scan ran past a trailing `//` comment to the next semicolon
and read the comment prose as an encoding. A structural check that is wrong in
the *alarming* direction is still wrong, and it nearly bought a rewrite of a
sound waiver.

---

## 4. ⛔⛔ RETRACTED: the reset-mode divergence was the BENCH, not the DUT

**Ruling (c) (Wilson) made this top priority ahead of the 32 owed points, on
the grounds that it was silicon correctness.** It is not. The cause is the host
feeder's own uninitialised state, and **my claim that "it is the DUT, not bench
bookkeeping" was wrong.**

### 4.1 What it actually was

`test/host_feed.vh` declared `hf_en`, `hf_mask` and `hf_q` with **no
declaration initialisers**. `hf_init` is a *task* called from each bench's main
`initial`, while the feeder is its **own** `initial` block — both start at time
0 and their order is not guaranteed. With `hf_en` holding an arbitrary power-on
value the feeder could push host bytes **before `hf_init` cleared it**, and
`hf_q` was never covered by `hf_init` at all.

⇒ Fixed by initialising at the declaration, which is applied before any process
runs — the only ordering that holds. **Every bench then passes at `+0`, `+1`
and `+2`: 57 of 57 arms.**

### 4.2 Why my evidence was misleading, and the lesson

I argued: *"It is the DUT, not bench bookkeeping — `tb_i2c`'s raw bus dump
diverges from cycle 119."* The dump being a raw wire proves **the wire
differed**. It says nothing about where the cause is, because the DUT drives
that wire *in response to host pushes*, and the pushes are the bench's. A
spurious early push makes the DUT transmit something different, entirely
correctly.

⛔ **"The probe output is low-level" is not an argument about causation.**

### 4.3 Wilson's elimination method, run and negative

The ruling specified: under `rand+reset+2`, zero one allowlisted group at a
time; the group whose zeroing restores the pass has the false reason. Run over
all five zeroable groups plus a `PE_ZERO_ALL` control:

| arm | tb_smoke | tb_tx | tb_i2c |
|---|---|---|---|
| baseline +0 | 0 | 0 | 0 |
| baseline +2 | 1 | 12 | 4 |
| **ALL** (5 groups zeroed) +2 | 1 | 12 | 4 |
| each group individually +2 | 1 | 12 | 4 |

**Zeroing every group changed nothing** — and `PE_ZERO_ALL`'s bus dump was
*byte-identical* to the unzeroed `+2` run. So the elimination returned nothing,
which is what sent the investigation to a DUT-only VCD and from there to the
bench. ⭐ The control arm was what made the negative result readable: without
it, five negative individual arms could have meant anything.

⚠ And the first run of that sweep was **unsound**: every mode-2 arm wrote
`run_<top>_<mode>.log`, so each arm clobbered the previous arm's evidence — a
constant output path, the same class as the `cj_measured.txt` clobber in §5.
The counts happened to be grepped before each overwrite, but nothing could be
verified afterwards. Re-run with the arm in the filename and a **vacuity
check**: an arm whose zeroing never printed is reported `*** VACUOUS` rather
than counted as a result.

### 4.4 What this does and does not say about the allowlist

It removes the evidence that one of the six "write-before-read" reasons is
false. It does **not** prove they are all true — only that these benches at
these modes do not expose a violation. ⚠ One reason is independently suspect on
inspection: `u_eng.fix` is `wire [SIW-1:0] fix = pl * SPL + ...` at
`pe_engine.v:797`, a **combinational expression with no flop**, so the
netlist-derived entry attributes some other 1-bit unreset flop to that name.

### 4.5 ⛔ Running all three modes adds NO line or branch coverage

Measured: the union over `+0/+1/+2` reaches 876 of 2727 points against 716 for
`+0` alone — and **every one of those 160 points is a toggle point.** Line and
branch are identical at 37 uncovered either way. Uncovered toggle goes 238 → 0
in `pe_engine.v`, 74 → 0 in `project.v`, 45 → 1 in the I²C peer.

The reason is immediate once seen: `rand+reset` sets every register bit to an
arbitrary value, so nearly every bit *toggles* without the design doing
anything. ⇒ **Toggle coverage at a randomised power-on measures the reset mode,
not the stimulus.** Crediting it would raise the ratchet to a number no test
earns, so the **adjudicated measurement is `+0` only**; the union is kept as
`merged_allmodes.dat` for information. The three-mode run keeps its full value
as the robustness gate ruling (c) asked for.

### 4.6 `hdr_cyc` 92 vs 91: not the same root

Ruling (c) asked whether the one-cycle cross-simulator disagreement shared the
power-on cause. **It does not.** At the canonical point (SPL 2, default image,
`NCYC=4000`, `WARMUP=200`):

| | `hdr_cyc` |
|---|---|
| Verilator, rand-reset **+0 / +1 / +2** | **91**, identical at all three |
| iverilog | **92** |

`jobs 344`, `svc_cycles 688`, `cycles 4000` and both opcode rows agree exactly.
So it is stable and reset-independent — a separate race, as the ruling
anticipated.

⚠ **My first re-measurement of this today was confounded** and I nearly
reported it: `test/probe_cj_measured.txt` is a constant path written by *every*
Verilator `tb_smoke` arm, so the SPL=1 arm had overwritten the default arm's
numbers and the file read `spl 1 / jobs 345`. Comparing that against the SPL=2
iverilog record compares two configurations. The same clobber class, a third
time.

**A hypothesis tested and falsified.** The loop does `@(posedge clk)` and then
reads `dut.u_eng.hdr_done`, which the DUT assigns non-blockingly on that same
edge — a classic nonblocking-visibility race. Adding a `#0.1` settling delay
gives iverilog **91** and Verilator **90**: both shifted by one, **the gap
preserved**. So that is not the cause, and adopting the delay would move pinned
numbers (`jobs` 344 → 345 under Verilator) without fixing anything. Not
adopted. **Root not isolated; it remains open.**

⭐ The consequence is bounded, which is the part that matters for published
work: `C_OCCUPANCY` is `svc_cycles/jobs` = 688/344 = 2.0000 under iverilog and
689/345 = 1.9971 under Verilator — **2.00 at the published precision either
way**, so the disagreement does not reach the derivation.

## 4a. (superseded) The reset-mode divergence as first reported

**The sweep runs at `+verilator+rand+reset+0`, and that is declared rather than
assumed.** At `+1` (all ones) and `+2` (randomised) — **the setting this
project's own convention names** — three benches fail:

| arm | at `reset+0` | at `reset+1` / `+2` |
|---|---|---|
| `tb_smoke` | pass | 3 failures, incl. a one-byte prefetch offset |
| `tb_tx` | pass | 12 failures, `config_err` set at load |
| `tb_i2c` | pass | 4 failures, the peer never ACKs |

**It is the DUT, not bench bookkeeping.** `tb_i2c`'s raw bus dump diverges from
**cycle 119**, and `+1` and `+2` produce byte-identical dumps. ⚠ The dump is
the resolved bus and the open-drain resolution happens in the bench, so this
localises the divergence to the DUT-plus-resolution path without fully
excluding bench state.

**Falsified along the way:** the obvious hypothesis — that the design reads
store bytes the image never wrote — is **wrong**. Zero-filling all 256 bytes of
the store changes nothing (12 / 4 / 3 failures before and after). The cause is
a flop, and since `gate_reset_audit` regenerates its netlist each run and
passes, every flop is either reset-bearing or one of its six allowlisted
entries — so **at least one of those six "write-before-read" reasons is wrong,
or the divergence enters through bench state**. Not yet isolated.

⇒ **Consequence, stated: paths reachable only from a nonzero power-on state are
not measured by this sweep.** And the question of whether the RTL must be robust
to arbitrary power-on state — real silicon's is — is a **ruling**, not a bug
fix, since it would mean adding reset to flops the allowlist deliberately
leaves unreset.

---

## 5. Three corrections the sweep forced on itself

⭐ Recorded because each is a way a coverage number can lie.

1. **An uncovered point can mean the SWEEP is incomplete, not that nothing
   tests it.** `pe_engine.v:867 else if (SPL == 1)` and the two `if (SPL > 1)`
   slot-flips read as dark — yet `run_param_points.py` has been running both
   depths all along. The sweep only ever *built* `SPL = 2`. One `-GSPL_CFG=1`
   arm covered all three. ⛔ Build-time parameters therefore key the build, or
   an arm runs against a binary it never built.
2. **An arm added in the expectation of covering something must be checked
   against whether it did.** Two clock-stretch arms were added for
   `fram_i2c.v:235`; the count did not move — 37 points before, 37 after. The
   reason was worth more than the arms: the stretching peer has never had a
   coherent byte clocked into it at all.
3. **`$finish` does not stop a Verilator run the way it stops iverilog.**
   Verilator exits at the end of the enclosing *time step*, so a verdict
   section following with no delay runs anyway. `tb_tx +BADCLK=1` printed
   `PASS (1.6x refusal)`, hit `$finish`, then ran the ordinary queue-ownership
   verdict — which failed, because the program it was judging had been refused
   on purpose. Judging that run by its log reported a pass as **eleven
   failures**. Logs are now cut at the first `$finish`. ⚠ The same caveat
   applies to the coverage: bench lines after a `$finish` can be credited
   though iverilog never reaches them, which is why the gate's subject is
   `src/` and the peer models, not bench bodies.

And one detector bug worth naming: a case-insensitive `FAIL` match flagged
`tb_csat`'s own line *"sticky_ovr observed : 0 (recorded, not a failure)"* and
failed an arm that had passed.

### 5.0 Two points whose coverage depends on the Verilator release

⭐ **Measured, across two releases on byte-identical stimulus.** The same 19
arms on **5.020** and **5.032** produce **identical point totals for every
file** (72/60, 6/3, 44/15, 14/18, 10/17) and **identical uncovered toggle
counts for every file**. The entire difference is two branch arms in
`pe_engine.v`, both `if` arms inside unrolled `for` loops over lanes:

| line | what | 5.020 | 5.032 |
|---|---|---|---|
| 651 | the EDF arbiter's selection condition | uncovered | taken **5,231,510** times |
| 942 | the prime scan's `l_live[pi] && want_fetch(pi)` | uncovered | taken **30** times |

⇒ The arms are plainly exercised, so 5.020's zero is an **attribution
artefact** across loop iterations rather than a test gap. They carry the status
`TOOL_DIVERGENT`: **counted as uncovered**, because the gate must not pick the
lenient reading of a disagreement it cannot adjudicate, and exempt from the
stale check, because "covered" is the expected reading on half the releases.
⛔ That exemption is deliberately narrow — an `UNREACHABLE` point that got
covered stays fatal, since it means the written reason is false.

### 5.1 The parser's one real hazard

`verilator_coverage --write` does **not** sum a point across benches: the merged
file carries one record per (point, hierarchy), and the hierarchy is
`tb_csat.dut.u_eng`, `tb_edge.dut.u_eng`, … one per bench. A point reached only
by `tb_edge` appears with count 0 under nine other benches. **Reading those as
uncovered would report nearly every point as dark** — so the gate aggregates
across hierarchy, and prices that by asserting most subject points read as
covered (222 of 259).

---

## 6. Verified

`ci/run_gates.sh` **14 of 14**, with the sweep's own 19 arms green and the
coverage gate passing. The sweep costs roughly five minutes — eleven Verilator
builds plus nineteen simulated arms — against seconds for every other gate;
`PE_COVERAGE_DAT` reuses a measurement for waiver-table work, and
`PE_SKIP_COVERAGE=1` leaves the gate **red** rather than pretending.

⚠ `verilator` lives only inside WSL on this box, so `ci/run_gates.sh` delegates
the sweep the same way it delegates the yosys netlist step — one shared
path-conversion helper now, because that conversion had already cost two
failures.

### 6.1 ⛔⛔ The tool is older in CI, and `--binary` cannot do coverage there

The sweep is built as **generate, patch, build** rather than `--binary`, and
that is a portability fix established from Verilator's own source rather than
guessed at. On **5.020** — what the runner installs, against **5.032** here —
the arms ran, **passed**, and produced no coverage file at all:

- `src/V3EmitCMain.cpp` at tag `v5.020` emits `topp->final(); return 0;` with
  **no coverage write anywhere**. 5.032 emits `contextp->coveragep()->write();`.
- `+verilator+coverage+file+` **does not exist** in 5.020 — passing it is
  `Unknown runtime argument` and SIGABRT.

So neither naming the output file nor searching for it could ever have worked:
the simulator never wrote one. ⇒ The generated `V<top>__main.cpp` now gets the
coverage write inserted after `topp->final()` when it lacks one;
`VerilatedCovContext::write()` and `VerilatedContext::coveragep()` are both
present in 5.020's `verilated_cov.h`, so one line serves both.

⭐ **Priced, because on this box the patch never fires.** 5.032 already emits
the call, so the patch would have shipped unexercised — the exact shape of a
guard that is never run. `probe_covpatch.sh` strips the line to the 5.020
shape, applies the sweep's patch verbatim, rebuilds and runs: **1 write call →
0 stripped → 1 patched**, sim `rc=0` with 7 PASS, **2192 lines of coverage
written**.

## 7. What this does not settle

- **The 32 owed points.** Priority is Wilson's call. The largest single item is
  the SPI peer's command set; the sharpest for the *design* are the two status
  bits (`lane_underrun`, `tx_full_sticky`) whose set paths no test has entered.
- **The reset-mode divergence** (§4), unisolated.
- **`RX_SERIAL`** (§1), awaiting a sweep-or-delete ruling.
- **Toggle coverage** is ratcheted per file, not adjudicated per point — ~390
  uncovered toggle points against 37 line/branch ones, mostly top bits of wide
  buses the parameter set cannot reach.
- **Gate-level coverage.** This is RTL coverage; the netlist is a different
  artefact and `gl_test` remains its only behavioural check.
