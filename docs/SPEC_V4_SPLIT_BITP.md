# Ruling 1 — split the bit pointer. And rulings 2 and 3.

**Ruling (Wilson), after `beb8862`:** split the shared bit pointer so each lane
has separate TX and RX pointers, each advanced and reset only by its own
opcode. State the SPI-master full-duplex shape. One entry point for local and
CI. Must-fires over enumerable spaces enumerate.

**Result: the TX load is reachable. `corpus_i2c` goes from 0 loads to 13, and
both directions now work on one lane in the same run.**

---

## 1. The split — and the register had to go with the pointer

The ruling named the pointer. **`l_data` was shared too**, and splitting only
the pointer would have been worse than the original defect.

| | shared before | now |
|---|---|---|
| pointer | `l_bitp` — RX reset at `a_cnt−1` fired before the TX load at `a_cnt` | `tx_bitp` / `rx_bitp` |
| register | `l_data` — `OP_SHIFTIN` inserted at bit 7 of the word `OP_SHIFT` was draining from bit 0 | `l_tx` / `l_rx` |

⛔ With the pointer split and the register shared, the TX load **fires** and
delivers **corrupted** bytes — plausible wrong data instead of none, which is
the more dangerous failure. The `M_SHARED_BITP` mutant demonstrates exactly
that: lane 0 emits `60 09 48 2b` where `96 69 c5 3a` was pushed.

**Cost: +55 flops** (3063 → 3118). I predicted 60 — 40 for `l_rx`, 20 for
`rx_bitp` — and synthesis folded 5. All of the new flops reset; the unreset
count is unchanged at 2153.

**The invariant is now structural:** no opcode writes the other direction's
state, by construction. That is why this shape was taken over a combined
shift-exchange action, which would also have needed an encoding bit the action
word does not have — `ACT_W` is exactly 24 of 24.

---

## 2. The result it unblocks

`corpus_i2c`, the program that measured **124 shifts, 0 loads, 0 underruns**:

```
fed 21   pops 13   underrun 0     op 1 n 124 min 2 max 2
```

Per-opcode `C` re-measured on the mixed lanes **with real loads**:
`min == max == 2` on every opcode, unchanged. Occupancy does not depend on
whether a byte loads — which is what made the starved measurement look right.

---

## 3. ⚠ The SPI-master full-duplex shape — stated, as asked

**`OP_SHIFT` couples two things:** it drives the data pin *and* the clock pin,
and it **advances the TX pointer**. So a bit period built from two SHIFTs — one
per clock edge, which is what `corpus.py` does — consumes **two payload bits per
protocol bit**, and the byte on the wire is not the byte that was pushed.

⭐ **The clock can be decoupled with the opcodes that already exist.**
`l_clkpin` reaches the pins in the `OP_SHIFT` arm and **nowhere else**, so
pointing an `OP_LEVEL` at the clock pin as its own `a_pin` moves the clock
without shifting:

```
SHIFT(data, level=0)   data bit out, clock LOW   -- advances TX
LEVEL(clkpin, 1)       clock HIGH                -- no shift
```

One shift per bit, data changing while the clock is low: correct framing for
both I2C and SPI mode 0. **Two actions per bit**, so a bit period is `2·d`.

### The answer to the ruling's question

**Two actions per bit, not one action driving both pointers** — and the
mode-0 timing check it asked for comes out as follows:

| shape | actions/bit | `d` for 1 MHz | `d ≥ D* = 20`? |
|---|---|---|---|
| TX only (write phase) | 2 | 25 | **yes** |
| TX + RX on the same bit | 3 | 17 | ⛔ **no** |

⛔ **So simultaneous full duplex at 1 MHz is not admissible.** A receive sample
needs its own action (`OP_SHIFTIN` does not drive the clock), making three
actions per bit, which needs `d = 17` — below the port-feasibility floor, where
`pe_asm` refuses the program.

⭐ **What the FRAM demo actually needs is not blocked.** An SPI FRAM
transaction is phase-separated: drive command and address bytes (MISO ignored),
then clock out don't-care bytes while reading MISO. Each *phase* is
half-duplex, two actions per bit, `d = 25` — admissible. The read phase's TX
content is don't-care, so the TX pointer advancing is harmless.

**Flagged back:** a combined shift-exchange action would make true full duplex
one action per bit, and it is the only shape that fits 1 MHz. It needs either a
wider action word or a spare encoding, and neither exists today.

---

## 4. Two more findings

### 4.1 The RX channel carries no lane identity

`rx_push`/`rx_data` are **engine-wide**, and the serial frame is
`{marker, 8 data}` with no lane field. With two receiving lanes the host cannot
tell which lane a byte came from — **the mirror image of the TX queue-tag
problem that per-lane queues solved.**

It surfaced as arithmetic: the engine delivered 50 bytes where the bench had
assembled 40, and `50 − 40 = 10` is exactly lane 0's ACK bytes arriving on the
same channel. The bench attributes by `cur`, which is available to it and
**not to the host**. Reported, not repaired: the frame format is a ruling.

### 4.2 `tb_half`'s own two corrections

- **The engine samples `pin_in`, not the pin.** `pin_in = uio_q1`, a two-stage
  synchroniser, so the first version compared the assembled byte against the
  *live* peer level: three bytes matched and the fourth did not, because the
  pattern transitioned inside that window. A two-cycle skew showing up as a
  data error on one byte in four is the kind of mismatch that gets "fixed" by
  loosening the comparison. ⇒ Two claims, two checks: the RX expectation is
  built from `pin_in`, and the offset is asserted separately.
- **And the offset label was wrong.** The bench printed *"pin_in = uio_q1, a
  0-stage synchroniser, MEASURED"* — false, and false in the direction of
  claiming more than was measured. `d` is an offset in the bench's own delay
  line, not a flop count. What the check establishes is that **one fixed
  offset explains every sample**; the depth is structural, read off
  `project.v`.

---

## 5. Ruling 2 — one entry point

`ci/run_gates.sh` is what CI runs and what I run before reporting green. The
workflow calls **only** it for the model gates.

**The diagnosis first.** I reported "all 8 CI gates green" and CI went red on
`gate_stored_numbers`. Reproduced in a clean worktree at that commit: **it
fails there too.** So it was never an environment difference — I ran the gates,
then kept editing, and reported the earlier run's result for a tree that no
longer existed.

So the script carries three things:

1. **The gate list, once.** A loop in a workflow and a loop typed at a prompt
   are two lists.
2. **A dirty-tree warning, every run,** naming the modified files — because a
   green on a tree you are not committing is not a green on what you push.
3. **Per-gate preconditions, as failures rather than skips.** ⚠ The first
   version said `gate_reset_audit` needs `yosys`; it needs the **netlist**. On
   this box yosys lives only in WSL, so the netlist is built by delegation and
   the gate — pure Python once it has the JSON — was declared unrunnable while
   its input sat on disk. A precondition stated as the wrong thing failed safe
   here, but it would have made the audit permanently unrunnable locally,
   which is how a gate quietly stops being run at all.

⭐ **It earned its place immediately:** on its first full run after this round's
edits it went red on `HALF_MUTANTS` being unclassified — caught *before* I
reported, which is the whole point.

The split toolchain is handled in the script, not by a second procedure: yosys
is WSL-only here and iverilog is native-only, so the netlist step delegates to
WSL when yosys is absent. In CI all three tools are native and nothing
delegates. Either way the gate list is the same list.

---

## 6. Ruling 3 — enumerate

Three times a must-fire's witness slid between hand-chosen constants: two
constants, then a list of constants, then `T = 13` between 2.0 and 1.5 MHz.

| must-fire | was | now |
|---|---|---|
| `gate_lane_class` 0.9b separation | list of 9 round MHz | **every integer period 2..120** — 15 separating cases where the list found 0 |
| `bursty` blocking filter vs jitter model | hand grid, 432 points | **exhaustive, 117,128 instances** — 270× |
| `bursty` n=1 arrival-curve reduction | `T ∈ {3,5,7,25,62,434}`, `J ∈ {0,1,2,3,7,11}` | `T` exhaustive 2..16 plus the shipped 25/62/434, `J` exhaustive 0..12 — **24,696 cells at J > 0** |
| `tb_half` sync offset | — | scored at every candidate; one must explain all |

**Where enumeration stops, the rationale is stated.** The arrival-curve sweep's
inner loop is `O(T)`, so periods above 16 are not enumerated — and the three
kept are the **shipped** periods (SPI 25, I2C 62, UART 434), so the
unenumerated part of the space is covered by the exact values the design uses
rather than by arbitrary large numbers. The blocking sweep's range (2..12) is
bounded because a disagreement needing a period above 12 would be about
overflow, not about the algebra — a different claim.

---

## 7. Verified

`tb_half` 4/4 at both SPL points · mutants **7/7**, 0 survivors, 0 wrong
reasons · cocotb 8/8 with the two declared-zero assertions **flipped** to real
readings (8 bytes consumed each) · corpus trace 7/8, 0 failed, fed · parameter
sweep 6 benches × 2 points · clean room 4/4 on freshly generated images · A2
31/31 · `ci/run_gates.sh` 9/9 · reset audit green on a fresh netlist ·
manifest moved on exactly the one new image.

## 8. What this does not establish

- **A certified protocol.** `half_image` is protocol-*shaped*: no START/STOP,
  no addressing. The claims are about the plumbing — a pushed byte reaches the
  wire, a sampled byte reaches the host, neither direction corrupts the other.
  The sigrok-adjudicated decode of a real I2C frame is **not done**, and it is
  the next thing: `model/ta01/gate0_external.py` has the invocation pattern
  (single-channel `binary` input, `uart` PD), so an `i2c` PD over a two-channel
  SCL/SDA dump is a known shape of work, not a new one.
- **Gate level.** All RTL simulation.
- **The real FRAM transaction**, which needs §3's phase-separated program and
  the peer models in `gate_corpus_trace`.
