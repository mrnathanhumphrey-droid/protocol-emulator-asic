# Ruling 0 — the SHIFT audit, and ruling 2 — `clkpin == pin`

**Ruling (Wilson), after `0deea0a`:** no bench had ever driven the host
channel, so every `OP_SHIFT` ever executed ran starved. Re-run every result
that executed a SHIFT with the queues fed, confirm or correct each, and make
"≥ 1 host push and underrun clear" a standing precondition. Reject
`clkpin == pin` on a SHIFT lane in silicon and in the toolchain.

**Result: three published claims confirmed, four defects found, two of them in
the RTL.** None of the four was reachable before the channel was fed.

---

## 1. The instrument

`test/host_feed.vh` — **one** host-channel driver, included by `tb_tx`,
`tb_smoke` and `tb_trace`; `test/test.py` carries the cocotb side of the same
contract. Two pushes per byte, high nibble first, tag on both pushes.

⛔ One copy, for the reason this project has paid for twice: four private
copies of the slot index were found one at a time, and one produced a published
column that had to be retracted. A push sequence copied into three benches is
the same shape — a copy with the nibble order wrong would split bytes across
queues in one bench and not another.

It tops up only queues **with space**: a push onto a full queue is dropped and
sets `tx_full_sticky`, so a blind feeder would drop bytes and the lane's stream
would have gaps — the feeder's bug reported as the engine's.

### The standing precondition

`hf_check` / `assert_host_fed` assert, for any run that dispatches a SHIFT:

1. at least one byte **pushed**;
2. at least one byte **consumed** (`host_pop`);
3. **no** lane's underrun flag set;
4. `tx_full_sticky` clear (the feeder did not overrun).

⛔ (2) exists because (1) and (3) pass **vacuously** together. The TX load fires
only at `l_bitp == a_cnt`, so a window can contain many shifts and no load —
and then "no underrun" means *nothing was ever requested*. It fired on its
first run; see §3.

---

## 2. What was confirmed

| claim | verdict |
|---|---|
| two-simulator cycle-exact agreement | **CONFIRMED fed** — all 5 programs × 3 phases |
| cross-seed invariance | **CONFIRMED fed** — seeds agree on every program and phase |
| `C` per opcode, 8 of 8 | **CONFIRMED fed** — census, `min == max == 2` on all eight, `fed 10 / pops 2 / underrun 0` |
| census completeness | **CONFIRMED**, and its provenance is now asserted |
| the shipped `C`/`J` figures | **unchanged** — `jobs 344`, `svc_cycles 688`, bit-identical with the feeder present |

`gate_corpus_trace`: **7 of 8, 0 failed** (1 pre-existing open arm). The
async-clear arm had gone **vacuous** on the way through — `uio_oe` constant —
and now reads 2 distinct values and is cycle-exact; that arm is the only test
of the tri-state MISO release, and it was being carried by a program whose
MISO drive was broken (§3.1).

⭐ **`five_image.hex` is unchanged.** It is the measurement base for T1's
per-lane `J` and Theorem 3's 35 port-feasible cells, and nothing in this round
moved it.

---

## 3. What was found

### 3.1 `clkpin == pin` on a shifting lane — ruling 2, now **1.6x**

`OP_SHIFT` writes the data pin and then the **clock** pin, clock second. With
the two aliased the clock write overwrites the data bit with the action's
`level` field: at `level = 0`, **every 1 bit becomes a 0**. The wire carries a
well-formed frame of the wrong data and nothing in the design can tell.

Three programs declared it, all on shifting lanes:

- `build_census` lane 0 — the image behind "C on 8 of 8 opcodes";
- `corpus.py::build_spi_target` — the **only** program exercising the
  tri-state MISO and the async-clear path;
- `build_all5` lane 1.

**Refused now, in both places.** Silicon: sticky `CONFIG_ERR` + the lane halts,
priced by `M_SHIFT_CLK_ALIAS` (with it, the illegal program runs and emits 36
bytes; without it, nothing beyond the reset byte). Toolchain:
`pe_asm.check_shift_clock_alias`, naming the lane, must-fired both ways.

⭐ **Scoped to shifting lanes, and checked at dispatch rather than header load.**
`l_clkpin` reaches the pins only inside the `OP_SHIFT` arm, so for a lane that
never shifts the alias is a don't-care — and at header-load time the chip
cannot know whether a lane's program contains a SHIFT, because actions are
fetched lazily. ⚠ This is a deliberate deviation from the ruling's "compare at
header load": `build_five` declares the alias on all five lanes while running
only `OP_LEVEL`, and a blanket refusal would make it unloadable and invalidate
T1 and Theorem 3 for a hazard those programs cannot reach. `build_five` and
`build_all5`'s lanes 3–4 are therefore **left as they are**, with the reason
recorded at each site.

### 3.2 The clock pin had no reality guard — an RTL gap

Every **data** write is guarded by `pin_real = (a_pin < N_PINS)`. The clock
write was **not**, so `pin_out[l_clkpin[cur]]` could index out of range with no
guard — the identical hazard `pin_real`'s own comment calls "the class of thing
that passed iverilog and died in Yosys once already", on the parallel axis. A
fix applied to one axis and not to the symmetric one.

`clk_real` closes it, and it is what makes **"this lane has no clock"**
expressible: an SPI *target* does not drive a clock — the master supplies SCK —
so its `clkpin` has nothing legitimate to point at. The corpus target lane now
declares `PIN_NONE`. Cost: **0 flops** (3063 before and after).

### 3.3 Three shifting lanes shared one TX queue

`build_all5`'s I2C, SPI-target and SPI-master lanes all drew from TX queue 0 —
the head-of-line collision per-lane queues exist to prevent, and exactly what
`pe_asm.check_queue_ownership` refuses. Unfed, all three drew nothing, so the
collision could not produce a wrong byte. `_assemble` now takes per-lane
queues; the three lanes get 0, 1, 2.

### 3.4 ⛔⛔ The TX byte load is **unreachable** on a half-duplex lane

The finding the vacuity check surfaced, and the one still owed a ruling.

`OP_SHIFT` and `OP_SHIFTIN` **share one bit pointer**, and they disagree about
where a byte ends:

```verilog
OP_SHIFT:   l_bitp <= l_bitp + 1;                      // TX load at l_bitp == a_cnt
OP_SHIFTIN: l_bitp <= l_bitp + 1;
            if (l_bitp == a_cnt - 1) l_bitp <= 0;       // RX completes one EARLIER
```

So on a lane that mixes the two, the RX reset at `a_cnt − 1` always fires
before the TX load at `a_cnt` can be reached. **Measured on `corpus_i2c`: 124
`OP_SHIFT` dispatches, 0 loads, 0 underruns** — no byte is ever even
*requested*.

⚠ That is every half-duplex protocol we ship: I2C drives a bit and reads the
ACK; SPI-master drives MOSI and samples MISO. **The host → TX path is
unreachable on those lanes.**

It is asserted as **exactly zero** in the two affected cocotb tests, with the
reason on record, so a design change that makes the load reachable turns them
red and forces the declaration to be revisited.

**Owed to Wilson** — three candidate shapes, not chosen here:
1. separate TX and RX bit pointers (flops);
2. make the TX load symmetric at `a_cnt − 1` (free, but changes TX framing —
   `tb_tx` currently gets 8 drives per byte at `count = 7`);
3. declare that a lane may not mix SHIFT and SHIFTIN (would break I2C and
   SPI-master as designed, so almost certainly wrong).

⚠ Note the asymmetry is *already* observable in the field semantics: at
`a_cnt = 8` RX completes after 8 samples while TX would load after 9 shifts.
Whichever way (1)–(3) goes, that off-by-one between the two directions is the
thing being fixed.

---

## 4. The structural guards

| guard | what it stops coming back |
|---|---|
| `corpus.py::audit_programs` | every corpus program run against the loader's own rules — queue ownership and 1.6x. Priced with both defects reconstructed. |
| `host_feed.vh` precondition | a starved run cannot be reported as a fed one |
| `cj_measured*.txt` `fed`/`pops`/`underrun` | the fed state travels **with** the numbers; `gate_cj_bounds` refuses a file whose SHIFT count is non-zero while `fed` is 0 |
| `gate_cj_bounds` alt-file image assertion | the shipped file has had an `image` assertion since a stress run clobbered it — the alt file, reached by the **same** constant-path mechanism, had only a printed label, and was found holding a `five_image` run while the section above it was headed "census image" |
| `M_SHIFT_CLK_ALIAS` | the 1.6x refusal is priced, not merely present |
| `gate_ruling_audit` 1.6x entry | the ruling is anchored to `clk_real` in the RTL |

⭐ The alt-file finding is the same shape as the defect it sits beside: a fix
applied to one axis and not to the parallel one. That makes three in this round
(the alt file, the clock-pin guard, and `px_n`'s run-boundary accounting in
`tb_tx`).

---

## 5. What this does not establish

- **Payload correctness on a real protocol.** `tb_tx` proves ownership and
  order on a synthetic two-lane program; the corpus programs that *do* carry
  protocol shape cannot load a byte at all (§3.4) or load only on their
  SHIFT-only lanes.
- **Gate level.** All of it is RTL simulation.
- **The channel's timing margin.** `1.6n` measures 10.7 % utilisation; nothing
  here stresses it.
