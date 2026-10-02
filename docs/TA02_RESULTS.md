# TA-02 — the generic table interpreter, and two defects it found in TA-01

**8 of 8 gates report green, 2 probes measured** — but see the retractions
immediately below before relying on any of it. Re-run with
`python model/ta02/run_ta02.py` (it enumerates the gate list and executes every
entry; the summary says "N of M").

---

# ⛔⛔ RETRACTIONS — read these first

A three-way red team attacked this rung after it was written. Four claims below did
not survive, and they are corrected in place as well as listed here. **The
behavioural results held; the structural claim and three gate verdicts did not.**

**R1 — "the branch-point audit proves the machine branches only on table state"
is RETRACTED.** The audit passes **6 of 7** adversarial mutants that branch on
non-table state: a mux spelled as a subscript (`[nxt,0][self.nbits==8]` — no
`If`/`IfExp` node exists, so the checker never runs), an `AugAssign`
(`lim += self.nbits`), a branch on a **neighbouring** entry
(`self.table[pc+1].in_pin`), a local rebound after its own test (the resolver is
flow-**insensitive** and keeps the last assignment), `match`, and `assert`. It also
audits **only `step`** — `output`, `run`, `run_bus`, `initial` and `wellformed` are
never examined, and UART injected into `output` returns a byte-identical clean
verdict. And `self.table.phase == 2` is rejected but blamed on *"the bare constant
2"*: **a red mutant dying for a stale reason, the second time in this rung, and the
exact failure this audit's docstring claims to have fixed.**
⭐ What survives: the **behavioural** genericity claim, which is independent of the
audit — three protocols off one machine, three foreign decoders, `cmp`-verified
byte identity. "Proved structurally" was an overstatement of a four-AST-node,
one-function lint.

**R2 — three gate verdicts are not evidence.** `run_imi.sh` discards Imitator's
exit status and asserts against `.res` files it never proves this run produced, so
a syntactically broken model in a warm tree prints 14 `ok`s and exits 0.
`price_imi_gate.sh` — the gate whose only job is to prove another gate can fail —
reported "mutant REJECTED" when handed a model **byte-identical to the real one**
and a missing Imitator binary, because "no `.res` produced" and "conjunct absent"
are the same observation to it. **A guard passing because of the defect it screens
for.** `run_zone_edge.sh`'s `grep -q "xe<=${TE}"` freshness check bounds the
**filename**, not the freshness: stale `.tck` files satisfy it and the generator
can fail unnoticed. ⛔ This is the gate-that-cannot-fail for the **third** time in
one rung, now in a stale-artefact costume rather than a missing-assertion one.

**R3 — the tolerance band is PAYLOAD-DEPENDENT, and `[411, 459]` is the 0x55
band.** Swept per byte on the same receiver:

| byte | `0x55` / `0x00` / `0x01` / `0x0F` | `0xA5` | `0xFE` | `0xFF` |
|---|---|---|---|---|
| level band | `[411, 459]` | `[408, 462]` | `[345, 544]` | `[345, 653]`¹ |
| width | 48 | 54 | 199 | ≥308 |

¹ still conforming at the top of the swept range — effectively unbounded above.

**Why:** an all-ones payload leaves the line high from the start bit onward, so a
level-checking receiver's stop sample is **unfalsifiable** regardless of timing;
the only surviving constraint is the start sample landing in the start bit. So
finding 2 is not over-permissive by 3 cycles — **it is over-permissive by hundreds
on the right payload**, and "the Python receiver is the sole outlier *by exactly
one cycle*" was a one-byte statement.
⭐ **B5 itself survives:** the two executors agree on the band for **every** byte
tested. The claim was right; the quoted number was under-qualified.

**R4 — finding 3's diagnosis named half the cause.** `table_guard.imi:59` is
`loc eData: invariant x <= G0 + 8*G` — the executor model collapses all eight data
bits into **one location**. No monitor could check the eight middle sample phases
off that model however the property was phrased. The 5× overstatement is the
monitor's 2-of-10 predicate **and** this executor abstraction, together.

**Known-weak, not retracted:** `gate_pwm.py` prints the period row without
comparing it (only the duty ratio is asserted, and it coincides with the raw duty
count only because the period is 100); `vary`'s first duty is never checked;
`field_exercised` counts an `IndexError` as coverage (dead code today — it fires 0
times — but it is a count-a-break-as-a-pass rule inside a coverage gate); and
gate 0's `warnings` column has no witness that it can ever be non-empty.

⛔ **Two of those gates could not originally fail.** `run_imi.sh` and
`run_zone_edge.sh` printed a synthesized region and a reachability table and exited
0 whatever they measured. Both now assert: the synthesis gate checks each conjunct
*inside* the `BEGIN/END CONSTRAINT` block, the **conjunct count** (so an
unpredicted conjunct cannot pass silently), and soundness / termination / nature
separately — a depth-limited run yields an under-approximation that reads like an
answer. The zone gate asserts the edge at 458/459. And the synthesis assertions are
**mutation-priced**: a monitor sampling at `18U` and a 7-bit data span are both
rejected, each for a visibly different region.

The rung's claim: **a machine containing no protocol emits UART, SPI and a pulse
train, and three independent foreign decoders read all three off it.** Genericity
is established behaviourally and structurally, not lexically.

> ⛔ **Two of the findings below are against TA-01, not TA-02**, and they are the
> red-team material. TA-01's receiver samples at the wrong period and checks the
> wrong property. Neither touches TA-01's decidability argument; both move its
> numbers. Nothing has been changed in `model/ta01/` — a fix there re-triggers
> TA-01, the TA-01b fixpoint and the TA-01c comparison as one unit, which is a
> call to make deliberately rather than inside this rung.

---

## The descriptor, frozen

Six fields. `Entry = (g, out, in_pin, in_pol, next_a, next_b)`.

| field | meaning |
|---|---|
| `g` | hold this many clocks before the transition fires |
| `out` | pin vector driven for the whole hold — output is a pure function of `pc` |
| `in_pin` | input pin sampled at the transition, or `-1` for unconditional |
| `in_pol` | take `next_a` when the sampled pin equals this, else `next_b` |
| `next_a` | successor on match / unconditional |
| `next_b` | successor on mismatch |

Machine state is **`(pc, clock)`** and nothing else. The transition relation is
nine lines with **three branch points**.

### ⛔ The freeze was incomplete, and B5 is what found it

`g = 0` is a **zero-time transition** — in RTL a combinational path from the table
memory back into the address being read, and a *cycle* of such entries is a
combinational loop. So **`g >= 1` is a well-formedness rule of the format**, now
enforced in `Interp.__init__` (the assembly point, not a checker the table
builders are asked to remember), along with successor range, pin range and
polarity. `g >= 1` also gives non-starvation by construction: every loop in the
table graph takes at least one clock.

It surfaced as a one-cycle waveform shift at `idle=0` only — a `g=0` idle entry
still emitted one cycle of output. **"No idle" is now the absence of an entry, not
an entry that lasts no time.**

---

## Gate 0 — genericity, behavioural AND structural

The two tests that *cannot fail* were demoted on purpose: an empty diff across
table loads is not-editing-a-file, and a scan for the literal `434` passes a
UART-shaped machine with the constant renamed. The scan survives only as a cheap
secondary, inside branch conditions, where a bare constant really is a protocol
commitment.

### Behavioural — SPI off the unchanged machine

SPI is structurally distant from UART on purpose: three pins not one, a
*generated* clock not a sampled bit period, MSB-first not LSB-first, framing by
chip-select level not by start/stop bits. If the interpreter had any UART in it,
SPI is what would break.

| case | want | sigrok `mosi-data` | warnings | same waveform re-read as `lsb-first` |
|---|---|---|---|---|
| 1 byte | `55` | `55` | 0 | `AA` |
| 1 byte | `0F` | `0F` | 0 | `F0` |
| 1 byte | `01` | `01` | 0 | `80` |
| 1 byte | `A5` | `A5` | 0 | *palindrome — cannot discriminate* |
| 4 bytes | `DE AD BE EF` | `DE AD BE EF` | 0 | `7B B5 7D F7` |

19 table entries for one byte, 67 for four. **4 of 5 cases bit-order sensitive.**

⭐ **The wire order is certified by the foreign decoder, not by us.** Re-reading
the *same* waveform with `bitorder=lsb-first` must yield the reversed byte. That
matters because the decoder's `mosi-bits` row is **not** wire order — for
`msb-first` the PD inserts each arriving bit at the front of its list, so
iterating it returns arrival order *reversed* (`0x0F` goes out `0,0,0,0,1,1,1,1`
and prints `1,1,1,1,0,0,0,0`). Reading that row as the wire order would have
manufactured an MSB/LSB finding that is purely a display artefact.

### Structural — the branch-point audit ⛔ **RETRACTED, see R1**

> ⛔⛔ **Everything in this subsection is reported as measured, and it is all true
> as far as it goes — it just does not support the conclusion it was written to
> support.** The audit passes 6 of 7 adversarial mutants (R1), examines only
> `step` of six callables, and kills its 7th for the wrong reason. Read it as **a
> lint with four known blind spots**, not as a proof. The genericity claim rests on
> the behavioural gate above, which is independent of this.

Every branch in `Interp.step` must depend only on the current entry `e`, the
generic state `(pc, x)`, and the sampled inputs.

- **3 branch points, zero findings** — and that count is itself the hole: `step`
  has exactly three *`If`/`IfExp`* nodes, and the audit equates "branch point" with
  that node set. A subscript mux, `match`, `assert` and exception dispatch are
  branches in silicon and invisible here.
- Descriptor fields read by branches: `g`, `in_pin`, `in_pol` — all declared, **no
  stray fields**. A branch on an undeclared field would be state silicon must
  carry that no table ever specified.
- **4 of 4 mutants rejected, each naming its own offender**: a bit counter
  (`self.nbits`), a hard-coded baud (`434`), a frame-phase register (`phase`), and
  a hoisted global (`UART_STOP_BITS`).

⛔ **The audit's first version flagged the real machine** — it saw the bare name
`matched` in a ternary and called it foreign. Worse, mutant M4 then died naming
`matched` instead of `UART_STOP_BITS`: **a red mutant dying for a stale reason**,
which would have certified an audit that was not in fact reading hoisted
expressions at all. The fix resolves a local back to its defining expression, so
hoisting neither triggers nor hides a finding.

---

## The input guard — kept, and exercised before the freeze

A machine that can only drive and never sample is a waveform player. The guard
survived the minimal descriptor, so it had to be exercised: **an unexercised field
is silicon nobody has ever run.**

The exerciser is a genuine control divergence, not a stall:

- pin held 1 → path states `[0,1,2]`, drove high
- pin held 0 → path states `[0,1,3]`, stayed low
- **alternating input visits `[0,1,2,3]` — both arms inside one run**, so the guard
  is evaluated at every visit rather than latched once
- flipping **`in_pol` alone** swaps the arm: `[0,1,2]` → `[0,1,3]`
- **must-fire**: a guard-blind machine makes the two input traces *identical*

### Coverage, by perturbation — not by presence

A field counts as exercised only if **some single-entry mutation of it changes the
run**. Presence in a table is not use.

| table | `g` | `out` | `in_pin` | `in_pol` | `next_a` | `next_b` | entries |
|---|---|---|---|---|---|---|---|
| `uart_tx` | yes | yes | — | — | yes | — | 31 |
| `spi_write` | yes | yes | — | — | yes | — | 35 |
| `input_branch` | yes | yes | **yes** | **yes** | yes | **yes** | 4 |

**6 of 6 fields exercised; none unexercised.**

⭐⭐ **This table is the argument for having built the input-branch table at all.**
`in_pin`, `in_pol` and `next_b` are exercised by *nothing else*. Without it, **three
of six frozen descriptor fields would have gone to silicon unexercised.**

### Table-size budget, pre-registered

**64 entries for UART.** A 3-byte periodic stream costs **31** (1 idle + 3 × (start
+ 8 data + stop)). Within budget; over it would have fired the
format-too-verbose falsifier.

⛔ **An honest limit of this descriptor:** one entry per bit means the *payload* is
baked into the table, so changing the data means reloading the table. A real
emulator wants a data source (FIFO / shift register). That is a descriptor
**extension deliberately not added** — it is generality the genericity proof does
not need, and it would be silicon paid for before anything exercised it. It is the
first thing TA-03 should price.

---

## B5 — the generic machine reproduces TA-01 exactly

Byte identity, not bisimulation. A bisimulation claim between a table interpreter
and a bespoke FSM is either trivial or unprovable at this layer — their state
spaces are different shapes *by construction*, which is the point of the
interpreter. Byte identity is checkable, and it is checked with **`cmp`**, a
foreign byte comparator, not our own `==`.

| check | result |
|---|---|
| waveform byte-identical, all **24** (byte, idle) pairs | **yes**, 5208/5208 bytes |
| identical verdict, from the **unchanged** TA-01 monitor and driver | **yes**, 6 of 6 bytes |
| identical tolerance band, swept on both columns | **yes**, both `Te ∈ [411, 459]` |

So TA-01's conformance results transfer to the generic machine. **And then the
band turned out to be wrong on both columns, for reasons that are TA-01's.**

---

## ⛔⛔ FINDING 1 — TA-01's receiver is not a 115200-baud receiver

> ✅ **FIXED.** The thresholds are now named once per receiver (`s_start`, `s_bit`)
> and shared by every call site, in all three receivers that carried the defect:
> `UartReceiver.step`, `_enabled`, and TA-01b's `StreamReceiver.step`. Re-derived:
> sample cycles **217 … 4123**, gaps **{434}**, offset **+0**, max reachable clock
> **433 = T-1**, and the level check's high edge now **458** — agreeing with both
> Imitator and TChecker. Full certificate re-run green: TA-01, TA-01b (13,023
> states, slope exactly 30.0000), zones (37/36), TA-01c (`9Te < 19U < 10Te`, exact),
> and all 8 TA-02 gates. Details in `docs/TA01bc_RESULTS.md` §C1–C2.

B5's bands agreed with each other and **disagreed with TA-01c's synthesized band**.
Three different answers:

| route | band (integer `Te` at `T = 434`) |
|---|---|
| level predicate, at the receiver's own schedule (`UartReceiver`) | `[411, 459]` |
| phase predicate, **also at the receiver's defective schedule** | `[414, 459]` |
| **synthesized** — TA-01c, `9Te < 19U < 10Te`, = the `.imi` monitor | **`[413, 458]`** |

⛔ **Row 2 was originally labelled "what the `.imi` monitor does" — wrong, and
corrected above (R2-adjacent).** The `.imi` monitor's own guards (`x = U`,
`x = 19U`, `U = 217`) give row **3**, not row 2. Row 2 is the *phase* predicate
evaluated at the *Python receiver's* schedule (218 / 4133). So this is **two models
carrying three predicates, not three independent routes** — the independence on
display here is smaller than the table first suggests. Row 1 is also the 0x55 band
only; see **R3**.

The measured sample schedule settles it:

```
sample cycles:      218, 653, 1088, 1523, 1958, 2393, 2828, 3263, 3698, 4133
inter-sample gaps:  {435}            <- every gap, not an average
start sample:       cycle 218        (the .imi monitor samples at U    = 217)
stop  sample:       cycle 4133       (the .imi monitor samples at 19U  = 4123)
accumulated offset: +10 cycles
```

**`UartReceiver`'s effective bit period is T+1 = 435 cycles — 114,943 baud against
a nominal 115,200 (−0.22%).** `if x < t: x+1` then `if x == t: sample` counts
`0..t` *inclusive*, which is `t+1` cycles per bit, compounding to +10 cycles over a
10-bit frame. Imitator never had it: its guards (`x = U`, `x = 19U`) are exact.

Predicting the phase band from the **measured** stop cycle instead of the nominal
one gives `[414, 459]` — **exactly the measured phase band.** Fully accounted for.

### ⭐⭐ Confirmed by a third tool, with the checked property held fixed

Arithmetic that accounts for a defect is still my arithmetic. The zone model
isolates it, because TChecker's monitor checks the **line level** exactly as the
Python receiver does — but its guards (`xm==half`, `xm==t_mon`) are exact
equalities, so it has no +1-per-bit error. **Vary only the timing; hold the checked
property constant** (`model/ta02/run_zone_edge.sh`, `T_mon = 434`):

| `Te` | 455 | 456 | 457 | **458** | **459** | 460 | 461 |
|---|---|---|---|---|---|---|---|
| `bad` reachable | false | false | false | **false** | **true** | true | true |
| states | 37 | 37 | 37 | 37 | 36 | 36 | 36 |

| route | timing | property | high edge |
|---|---|---|---|
| Imitator (synthesis) | exact | phase | **458** |
| TChecker (zones) | exact | **level** | **458** |
| Python fixpoint | **435-cycle** | level | **459** |

**The two routes with exact timing agree on 458. The Python receiver is the sole
outlier, by exactly one cycle.** A level-vs-phase difference cannot produce that —
TChecker shares the level check and still lands on 458. This is the +1-per-bit
defect, measured by a tool that is not mine.

⛔⛔ **The diagnostic fired in TA-01b and was explained away.** `TA01bc_RESULTS.md`
records *"max clock `== T`, not `< T`; the clock reaches `T` at the sample then
resets. Off-by-one in the spec's phrasing, not a failure."* That was **the defect
announcing itself**, read as a phrasing problem. The `0..T` inclusive count is the
same off-by-one.

⛔ Gate 0 could not catch it: sigrok resamples at the true baud, and 0.22% on a
single frame is far inside UART's own tolerance. **A foreign authority bounds what
it can resolve.**

## ⛔ FINDING 2 — the receiver checks the level, the model checks the phase

> ⚠️ **HALF-RETRACTED — this was partly a CATEGORY ERROR, not a defect.** A
> **receiver model** samples levels because real silicon has no access to the
> transmitter's phase; a **conformance oracle** checks that every sample landed in
> its own bit window. TA-01 built the first and claimed the second.
> `model/ta01/phase_oracle.py` adds the missing object instead of bending the
> receiver into it — bending it would have retired the level check exactly when
> RTL, which reads levels and not phases, is about to need it.
> ⭐ **The oracle's band is `[413, 458]`, exactly Imitator's synthesized band**, so
> the three routes now agree AT THE EDGE. The residual level/phase gap (level low
> edge 410 vs oracle 413) is real receiver behaviour, not an artefact.
> ⭐ **And the payload dependence of R3 is a property of UART:** `0xFF` leaves the
> line high from the start bit onward, so a level-checked stop sample cannot fail
> however far it drifts — `[344, 651]` against `0x55`'s `[410, 458]`, **6.4× too
> permissive**. **Test timing conformance on `0x55`-class payloads; "not its own
> bit-reversal" is necessary but NOT sufficient — the byte must also be able to
> make a mis-timed sample read the wrong value.**

The three `Te` values where the two checks disagree are `411, 412, 413`, and the
reason is identical in all three:

```
sample 9 (wants stop) fired at cycle 4133, which is in AFTER-FRAME(idle), level = 1
```

A stop sample that has drifted **past the end of the frame** reads idle-high and is
accepted. TA-01c's `.imi` header names this hazard exactly and says it was
avoided — **it was avoided in the Imitator model, and never in the Python
receiver**, which is the model that produced TA-01's verdicts, the TA-01b fixpoint
and these sweeps.

### What this does and does not touch

- ⛔ **Not supported at the edge:** TA-01bc's *"triple cross-check … three routes to
  the same boundary."* The three routes sampled **three points** (nominal, +2%,
  +10%), all far from the edge. Agreement at sampled points is not agreement at the
  boundary, and the boundary is the only place the models can differ.
- ✅ **Untouched:** the decidability argument (reachability vs language inclusion),
  determinism, totality, fixpoint closure, BFS termination, the zone model's
  `REACHABLE` verdicts at nominal and +10%, and Gate 0. These are structural or far
  from the edge.
- ✅ **Measured, not owed:** the zone model's band edge is **458**, matching the
  synthesis and isolating the defect to the Python receiver — see the table above.
- ⚠️ **Not comparable, and not claimed:** the zone model's *low* edge answers a
  different question. Its data bits are nondeterministic and it carries **no data
  conjunct**, so a far-too-slow executor is caught by the start sample rather than
  by a wrong byte. Only the high edge is a like-for-like comparison.

---

## The parametric re-synthesis — the proof knob IS the reprogram knob

TA-01c synthesized over `Te`, "the executor's actual bit period" — a parameter of
the *model*, not a field of anything. TA-02 synthesizes over **`G`, the table's own
guard field**, so reloading the table moves inside a region already proved instead
of needing a new proof per baud rate.

A single non-resetting clock remains faithful to an interpreter that resets its
clock every entry, because the UART table is traversed in sequence with no
branching — and that is **licensed by B5's measurement**, not assumed. Giving the
executor its own resetting clock *and* parametrizing both is the undecidable
region.

Both results **exact (sound and complete)**, fixpoint at depth 7, 16 states, <0.01 s.

**Close-out** (`G0 = G`, the table convention — a model derived from the general one
by `sed` adding exactly one constraint, so the two provably differ by that line):

```
19*U > 9*G0  &  10*G0 > 19*U  &  G0 = G        i.e.  9G < 19U < 10G
```

✅ Reproduces TA-01c's band as a constraint on a table field. The
re-parametrization did not change the model.

**General** (`G0` free — the start-bit entry carries its own guard, which a
reprogrammable table can obviously do):

```
19*U > G0 + 8*G  &  G0 + 9*G > 19*U  &  G0 > U
```

The third conjunct `G0 > U` is **new**; the single-`G` convention hides it (there it
follows from the other two).

## ⭐⭐ FINDING 3 — an exact, complete answer to the wrong question

The general region is 2-dimensional, so for almost any data period `G` there is
*some* `G0` satisfying it: admissible `G ∈ [2, 488]`, a **112%-of-T** envelope
against TA-01c's ±5%. One extra table field appearing to buy an 11× wider band is
a result to attack, not to publish.

**The step that makes it impossible: the synthesized monitor checks 2 of the 10
samples — and the executor model could not have offered the other 8.**
⛔ **R4:** `table_guard.imi:59` is `loc eData: invariant x <= G0 + 8*G`, collapsing
all eight data bits into **one location**. So the 5× overstatement has *two*
causes, and naming only the monitor's predicate (as this section originally did)
lets the modelling half off. Re-synthesizing over a 10-sample monitor therefore
also requires **splitting `eData` into eight locations** — otherwise the richer
property has nothing to bind to. TA-01c's model records the data bits without
judging their phase —
correct for *framing*, silently wrong for the *byte*. Satisfying start-and-stop
while the eight middle samples slip into neighbouring bits decodes a **different
byte**, and the region cannot see that.

Measured over `G ∈ [2,600)`, trying every admitted `G0`, across **8 payload bytes**
(3 bit-order sensitive, 3 palindromes):

| requirement | admissible `G` | as ε around `T` |
|---|---|---|
| framing only — *what Imitator was asked* | `[2, 488]` | −99.54% … +12.44%, width **111.98%** |
| + all 10 phases + correct byte, `G0` per byte | `[386, 488]` | −11.06% … +12.44%, width 23.50% |
| + all 10 phases + correct byte, **one shared `G0`** | `[386, 488]` | −11.06% … +12.44%, width **23.50%** |
| single-`G` band (TA-01c integer shadow) | `[413, 458]` | −4.84% … +5.53%, width **10.37%** |

**The start-bit field does buy tolerance — 2.27×, not 11×.** 45 → 102 cycles wide.
Per-byte and shared-`G0` bands coincide, so **one `G0` serves every payload**; it is
a table convention, not a per-payload retune.

⛔ **`#synth` returned a constraint that is exact and complete *for the question
asked*. The question omitted 8 of 10 samples, so an exact answer overstated the
envelope by 5×.** Exactness is a property of the answer, never of the question —
and the flattering direction is the dangerous one, because it looks like a result.

---

## The third table — off-pattern, written last

A pulse train shares exactly one thing with UART and SPI: it is a timed sequence of
pin levels. No framing, no data, no clock line, no transfer, no termination. It was
written **after** the descriptor froze — written first, the format would have been
shaped to fit it and "the format generalises" would be unfalsifiable. It is also
distinct from the input-branch table, which exists to exercise a field.

sigrok's `pwm` PD is a **third** foreign authority, independent of the `uart` and
`spi` decoders.

| case | duty wanted | sigrok read | match |
|---|---|---|---|
| `d25` | 25 × 12 | 25 … | **11/11** |
| `d50` | 50 × 12 | 50 … | **11/11** |
| `d75` | 75 × 12 | 75 … | **11/11** |
| `vary` | 10,30,50,70,90,70,50,30,10,40,60,80 | same | **11/11** |

Two entries per period, 24 entries. Period row reads **2.0 μs** = 100 cycles at
50 MHz = 500 kHz, as the table specifies. `vary` changes duty period-to-period,
which a fixed two-entry oscillator would not exercise.

⛔ A duty of 0 or `period` would need a zero-length entry, which `wellformed`
forbids. The honest encoding of "always low" is **one** entry, not two with one
lasting no time.

---

## Independence budget, as it now stands

1. **sigrok `uart`** — foreign, semantic (TA-01, TA-01b)
2. **sigrok `spi`** — foreign, *different standard*, on a 3-pin generated-clock
   protocol (TA-02 gate 0), plus the `lsb-first` re-read certifying wire order
3. **sigrok `pwm`** — foreign, third decoder, off-pattern (TA-02 third table)
4. **`cmp`** — foreign byte comparator for B5's identity claim
5. **zone vs fixpoint** — independent theories on the timed property (TA-01b)
6. **parametric synthesis vs zones vs fixpoint** — ⛔ **three routes, and they do NOT
   agree at the edge.** Synthesis and zones agree on 458; the Python fixpoint says
   459. See findings 1 and 2. ⛔ And discount the *structural* audit entirely (R1):
   it is a lint with four blind spots, not an independent witness.

⭐ **The strongest item on this list is one the red team added, not me.** An
exact-timed twin of `UartReceiver` carrying the **identical level check**
(`x < t-1` / `x == t-1`) lands on high edge **458**, matching Imitator and
TChecker. That isolates finding 1 by a fourth route and by a method that is not
mine — the `T+1` period, not the level predicate, is what moved the edge.

⛔ Still owed: a real receiver at the FPGA stage, and Lean for soundness.

---

## Scope fence

Still the **model**. **No RTL implements any of this.** The interpreter is a model of
the semantics RTL must implement, which is why every descriptor field is treated as
a silicon commitment. Full SPI conformance (TA-03), I²C, the refinement probe, and
fab are later rungs. `model/ta01/` is **unmodified**.

## Instrument slips logged this rung

- **`-A spi` regex-scraped**, so every case read as a mismatch on the first run: the
  `mosi-transfer` row repeats a single word, and `DE AD BE EF` contains spaces and
  was silently dropped. The decoder had been right all along. → **select the
  annotation row, never scrape.** Same shape as TA-01b's frame error.
- **The PWM PD measures period between rising edges**, and the table drives high at
  cycle 0 — no opening edge, no closing edge, 12 duties reported as 10. → run two
  extra periods and compare `duties[1:]`. **TA-01b's truncated-frame bug in a new
  costume.**
- **cp1252 on the decoder's output**: `text=True` turned `2.0 μs` into `2.0 Î¼s`. The
  TA-01b encoding trap, now on the *input* side. → pin `encoding="utf-8"`.
- **MSYS rewrote `/mnt/d/...`** into `C:/Program Files/Git/mnt/d/...` → `MSYS_NO_PATHCONV=1`.
- **The audit flagged the real machine** and killed a mutant for a stale reason — see
  Gate 0, structural.
