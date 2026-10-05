# A sigrok-certified I²C frame — and two defects in our own peer

**Ruling (Wilson):** after RX lane identity, a sigrok-certified decode of a
real I²C frame with START, address, ACK and STOP. Today's must-fires prove the
plumbing, not a certified protocol.

**Result: certified.** sigrok decodes **13** complete acknowledged write
transactions, plus one correctly refused. And it immediately earned its keep —
it pointed at **two real defects in our own peer model**, neither of which any
same-hand setup could have resolved.

```
0: Start | Write | Address write 00 | NACK | Data write 5A | NACK | Stop
1: Start | Write | Address write 50 | ACK  | Data write 5A | ACK  | Stop
2: Start | Write | Address write 50 | ACK  | Data write 5A | ACK  | Stop
...
```

`0x50` is the MB85RC256V device address (`1010 000`), and the peer
**acknowledged** it.

---

## 1. Why a foreign decoder, and what it changed

Every I²C claim this project had made was **same-hand**: our engine against our
own peer model — `fram_i2c.v` says so in its own header — and our own benches
reading our own expectations. `tb_half` proved the *plumbing* and said so
explicitly.

⭐ **The peer refused to acknowledge a frame sigrok called well formed.** That
is the one situation a same-hand setup cannot resolve: with only two of our own
artefacts disagreeing there is no way to tell which is at fault. sigrok's
verdict pointed at the **peer**, and two defects came out of it.

### 1.1 The peer assembled 9 bits and decoded the last 8

On a fresh START the first SCL rise already carries bit 7, and the model then
set `bitn <= 7` — so `byte_done` fired on the **ninth** rise and `shin` held
samples 2..9: the byte shifted left by one with the released ACK bit appended.
A correct device address of `0xA0` decoded as `0x41` and never matched.

### 1.2 The phase machine could not see a restart

The sharper one. Both state blocks latch `bus_active` on an SCL edge and detect
a fresh START as "it was 0, now it is 1". But a STOP **and** the next START both
happen while SCL is **high** — that is what those conditions *are* — so between
two SCL edges the flag goes `1 → 0 → 1` and each block samples `1` then `1`.
**The restart is invisible**, and a device that had gone to `P_IDLE` on an
address that was not its own stayed there for ever.

Our program's *first* transaction carries the reset byte `0x00` by construction
(`l_tx` resets to 0 and the host byte loads only after eight shifts), which this
device must refuse — so the peer went idle on transaction 1 and never
acknowledged any of the hundreds that followed.

⇒ Fixed with a monotonic **start counter** owned by the asynchronous SDA block,
which each edge-sampled block compares against its own latched copy. Same
information, no second driver on any signal — which the model's own
one-driver-per-signal rule requires (learned when Verilator rejected six
multidriven signals in `fram_spi.v` that iverilog had accepted in silence).

⚠ **Why neither was caught before.** The peer's address-match branch had
**never once fired**. `corpus.py`'s I²C program used two SHIFTs per bit, so it
consumed two payload bits per protocol bit and never put a coherent byte on the
wire; and the trace gate compares the two *simulators* against each other, not
the bus against a standard. An unexercised branch is not a correct one.

---

## 2. ⛔ The bit order, settled — and a doc that said the opposite

The host pushes **`0x05`** and sigrok reads the 7-bit address as **`0x50`**,
i.e. the wire byte was **`0xA0`** — the **bit reversal** of what was pushed.

`OP_SHIFT` emits `l_tx[0]` first, so **the engine is LSB-first on the wire**,
while I²C and SPI mode 0 are both MSB-first.

⚠ **`pe_isa.py`'s own docstring claims the lanes shift MSB-first.** That is the
opposite of what the RTL does, and it was undetectable until now: nothing
decoded the wire against a standard, and the one byte a bench had checked end to
end — `0x5A` — is a **bit-reversal palindrome** and matched either way.

⇒ **A host must pre-reverse** every byte it wants on the wire MSB-first.

**Owed to Wilson:** whether the *engine* should shift the other way is a
**ruling**, not a bug fix. Reversing it would change the TX byte order of every
lane and `tb_tx`'s recorded streams with it. The three shapes:

1. **leave it, document it** — the host reverses; cheapest, and the ISA
   docstring is simply wrong and gets corrected;
2. **shift MSB-first in the engine** — `l_tx[7]` out, shift left; changes every
   recorded TX stream and the `tb_tx`/`tb_half` expectations;
3. **a per-lane order bit in the header** — costs an encoding bit, and there
   isn't one spare (`ACT_W` is 24 of 24; a *header* field might fit).

---

## 3. The framing, built from the opcodes that exist

| | |
|---|---|
| START | `OP_START(SDA, 0)` pulls SDA low while SCL is still released high, then SCL goes low |
| a bit | `OP_SHIFT(SDA, lvl=0, clk=SCL)` puts the bit on SDA **and** takes SCL low in one dispatch; `OP_LEVEL(SCL, 1)` releases SCL high |
| ACK | SCL low, `OP_SHIFTIN(SDA)` **releases** SDA so the peer can pull it, SCL high (the acknowledge is on the wire), SCL low |
| STOP | SDA low, SCL high, `OP_STOP(SDA, 1)` releases SDA so it **rises** while SCL is high |

⭐ **Two actions per bit, one shift per bit.** The clock is decoupled from the
shift because `l_clkpin` is written in the `OP_SHIFT` arm and nowhere else, so
an `OP_LEVEL` aimed at SCL moves the clock without consuming a payload bit —
the mechanism established in the split-pointer round.

⚠ Open-drain is what makes it legal: both pins are `uio`, `MODE_OD`, so a 1 is
a *release* and the peer may pull low simultaneously. That is what an ACK is.

---

## 4. The gate's own guards

| guard | what it stops |
|---|---|
| `sigrok-cli` from **`$SIGROK_CLI`** | **priced**: pointed at a missing path the gate goes RED, so it genuinely depends on the foreign authority rather than falling back to the bench's opinion |
| return code read | a failed invocation produces no annotations, which is indistinguishable from "no frame found" unless the status is checked |
| liveness before decoding | both bus lines must have moved and the peer must have ACKed at least once — "the decoder found no frame" reads the same whether the bus was silent or the framing was wrong |
| **non-vacuity** | the run must contain a transaction addressed `0x00` and **NACKed**. A peer that ACKed everything would certify nothing, and so would a decoder that reported ACK unconditionally |
| channel order declared twice | the bench writes bit0 = SCL, bit1 = SDA and the invocation asks `scl=0:sda=1`; a swap decodes nothing, which looks exactly like bad framing |
| the reversal **computed** | `0xA0` is derived from `ADDR_PUSHED`, and the two constants are cross-checked before any measurement — a literal would be a second copy of the thing under test |

---

## 5. Verified

`run_i2c` **PASSED** and priced · corpus trace **7/8, 0 failed** with the
corrected peer (the D2 open-drain invariant and the stretch must-fires both
still hold) · cocotb 8/8 · mutants 8/8 · clean room **5/5** on freshly
generated images · A2 31/31 · `ci/run_gates.sh` 10/10.

⚠ `run_i2c.py` is a **by-hand checkpoint gate**, not CI: it needs WSL and
`sigrok-cli`, neither of which the CI runner has. That is the same declared
boundary every pyRTA-primary gate sits behind.

## 6. What this does not settle

- **Electrical timing against UM10204.** sigrok adjudicates framing and byte
  values; it is tolerant of rate. The timing claim is `gate_i2c_phase.py`'s,
  from the datasheet table.
- **A read transaction.** This certifies a *write*: `S | addr | A | data | A | P`.
  The part's read sequence needs a repeated START and `R/W = 1`, which the peer
  models and nothing yet exercises.
- **Two address bytes.** The MB85RC256V takes `S | dev | A | addrhi | A |
  addrlo | A | data | A | P`; this frame sends one address byte, so the peer's
  `P_AHI`/`P_ALO` phases are still unexercised.
