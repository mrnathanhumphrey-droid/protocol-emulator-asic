# T5.1 — TX interleave, and a channel nothing had ever driven

**Ruling (Wilson):** close the one PARTIAL — two TX lanes interleaving under
host-ordered pushes, each emitting only its own bytes. `tb_tx.v` plus a
one-line `M_TX_IGNORE_TAG`, mutants 4/4 → 5/5.

**Result: the claim holds, and the headline is what building it uncovered.**

---

## 1. ⛔⛔ The host data channel had never been driven by any bench

`test/pe_isa.py` has carried `host_pushes()` since F1 was built. **Nothing in
`test/` called it.** No bench ever raised `ui_in[6]` in run mode, so every
`OP_SHIFT` the suite has ever executed found `host_valid = 0` and took the
underrun branch.

That includes the census image, which is how `gate_cj_bounds` reports `C_max`
measured on **8 of 8** opcodes. SHIFT has been executed many thousands of times;
it had never been executed **with a byte in the queue**. The path from a queue
to a wire was built, encoded in the ISA, allowed for in the pin map, priced in
the channel-utilisation figure — and unexercised.

⭐ A mutant on that path could not have died, which is why `M_TX_IGNORE_TAG`
did not exist before now: there was nothing for it to break.

---

## 2. The result

`test/tb_tx.v`, on `make_smoke_image.py --tx 12 13` — two lanes, eight SHIFTs
and a re-arm each, lane 0 naming queue 0 and lane 1 naming queue 1:

```
host order was q0=b1, q1=2d, q0=4e, q1=d2
  lane 0 byte 0: got b1 want b1 ok     lane 1 byte 0: got 2d want 2d ok
  lane 0 byte 1: got 4e want 4e ok     lane 1 byte 1: got d2 want d2 ok
tb_tx: PASS (4 of 4 must-fires)
```

| # | must-fire | why it is there |
|---|---|---|
| 1 | the first byte out of each lane is `00` | proves the reconstruction is **byte-aligned**. By construction: `l_data` resets to 0 and the first load lands at the *end* of the first eight drives. Without it, every later comparison could fail for a framing reason that has nothing to do with queues. |
| 2 | **each lane emits only its own queue, in order** | the ruled claim. The host pushes `q0, q1, q0, q1` and never learns which lane dispatched first. |
| 3 | the pin carries the bit that was driven | the drive decision and the pin are two separate readings, not one. 846 of 846 events. |
| 4 | the tag is latched with the high nibble | a byte pushed with tag 0 then tag 1 lands wholly in queue 0 — queue 1 is untouched. |

**The mutant dies naming its reason:**

```
M_TX_IGNORE_TAG   host_q becomes a constant: every lane pops queue 0   RED
  *** FAIL: lane 1 emitted a QUEUE 0 byte -- the queue tag was ignored
mutants run: 5   survived: 0   died of a WRONG reason: 0
```

⛔ The *first* version of the cross-lane check compared only byte 0 against
byte 0, and it **did not fire**: under the mutant lane 1 gets queue 0's
*second* byte, because lane 0 took the first. The mutant died of
`got 4e want 2d` — a value mismatch, which is not its stated reason, and this
project does not accept that as a kill. The check now scans every byte a lane
emitted against every byte of the other queue.

---

## 3. ⚠ A real finding, reported and not fixed: `pin == clkpin` on a SHIFT lane

Building this cost one debugging cycle, and the cause is worth a ruling.

`OP_SHIFT` drives **two** pins in one `ST_DRIVE`:

```verilog
pin_out[a_pin]          <= l_data[cur][0] & pin_pp[a_pin];   // the data bit
...
pin_out[l_clkpin[cur]]  <= a_lvl & pin_pp[l_clkpin[cur]];    // the clock edge
```

The clock write comes **second**. With a header naming the same pin for data and
clock, it overwrites the data bit with `a_lvl` — at `a_lvl = 0`, **every 1 bit
becomes a 0.**

The bench reported 8 unexplained pin events per lane out of ~440, which looked
like a flaky pin. The diagnostic print is what turned it into a diagnosis: every
unexplained event read `drove=1 uo=0`, and **exactly 8 per lane is exactly the
number of 1 bits in each queue's payload** — so *every* 1 was being lost.

- **It was my program's bug**, fixed by giving each lane its own clock pin
  (`UO2`, `UO3`), which is also how a real SPI lane is configured.
- **`build_census` and `build_five` both declare `clkpin == pin`** and are
  unaffected, because they only use `OP_LEVEL`, which does not touch the clock
  pin. The hazard has been latent in two images the suite runs daily.
- ⛔ **Nothing refuses such a program.** The wire carries a well-formed frame of
  the wrong data: the silent-corruption class, one level above a wrong number.
  It was unreachable until T5.1 because nothing had ever shifted a real byte.

**Owed to Wilson:** a load-time condition rejecting `clkpin == pin` on a lane
that executes `OP_SHIFT`. Adding an admissibility rule is a ruling, so it is
reported, not written.

---

## 4. The bench defect the parameter sweep caught

`tb_tx` joined `run_param_points.py` when it was written rather than after it
produced a wrong number — the lesson from finding four private slot-index copies
one at a time. **It earned its place immediately**, though not against the
design: at `SPL = 1` it reported *one* unexplained pin event out of 847 while
`SPL = 2` reported none.

The ownership result was identical at both depths, so a **denominator that moved
with a parameter that cannot affect it** was the tell. A drive in the final
cycles of the run was counted as scored before its lag window could resolve. The
bench now counts an event only when it resolves, and both depths read 846 of 846.

Also corrected while building: `PIN_LAG` was *assumed* to be 2 (`pin_out` then
`uo_q`, two register stages) and compared only at that lag. The bench now scores
**every** lag in 1..5, reports the whole profile, requires some lag to explain
every event, and checks the derived value against the one that did. An assumed
pipeline depth that is wrong on a *fraction* of events is worse than one wrong
on all of them: it looks like a flaky pin instead of a bookkeeping error.

---

## 5. Where it runs

| harness | status |
|---|---|
| `test/run_mutants.py` | 5 mutants, 0 survivors, 0 wrong reasons |
| `test/run_param_points.py` | 5 benches × 2 SPL points, all declared |
| `test/clean_room.py` | third bench; loads the pinned `tx_image.hex` |
| `test/artefacts.sha256` | 18 artefacts; **no existing hash moved** |
| `model/gate_mutant_arms.py` | `M_TX_IGNORE_TAG` = 2 diff lines, minimal |
| `model/gate_stored_numbers.py` | `TX_MUTANTS` classified as a declaration |

`build()` in `run_mutants` now derives the Verilog top from the bench filename
instead of comparing source-list identity — with three benches, a forgotten
`is SRC_X` comparison would have silently built `tb_smoke`, passed, and recorded
a survivor for a reason that was not the mutation.

### Scope

Ownership and **order**, on a two-lane program at `d = 12/13`. Not protocol
framing (eight SHIFTs and a re-arm is not UART), not channel timing, and not the
tag's 2-bit width limit — four queues, with the escape hatch for a fifth
(carrying the tag in the data stream) recorded in `project.v`.
