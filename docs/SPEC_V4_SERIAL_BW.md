# The serial link, re-derived at 12 bits — and `1.6p` was wrong before that

**Ruling (Wilson):** the frame format is final, so re-derive the serial
bandwidth at 12 bits (one-deep RX pending margin, aggregate utilisation,
readback throughput) with both RX lanes active; run the liveness and RX-drop
must-fires; update `HOST_INTERFACE.md`.

**Result: `1.6p`'s published 2.2% was the raw pin rate. The real figure is
14.0%, and it was already 10.6% at 9 bits — the error predates the widening.**

---

## 1. What the link actually costs

| | derived | measured |
|---|---|---|
| bit time | 2 clocks | — |
| frame | 12 bits × 2 + **1 queue clock** = **25** | **25** (the only gap seen) |
| payload slot | 2 × 25 = **50** (status always follows a payload) | **50** at every sweep point |
| payload capacity | **8.00 Mb/s** | — |
| shipped two RX lanes | 1.12 Mb/s | — |
| **utilisation** | **14.0%** | — |
| readback, full 256-byte store | 12,800 clocks = **256 µs** | 50 clocks/byte, measured |

⛔ **`1.6p` compared against 50 Mb/s — "1 bit per cycle on the data pin".** The
stream never runs at that. Four factors were missing, every one visible in
`project.v`'s serialiser: the two-clock bit time, the 4 non-payload bits per
frame, the status frame that always follows a payload, and the queue clock
between frames.

⚠ **The error predates the 12-bit frame.** At 9 bits the slot was 38 clocks and
the true figure **10.6%**, still quoted as 2.2%. The widening moved it
10.6% → 14.0%; the mis-stated capacity accounted for the other **4.8×**.

⚠ **Readback got slower:** 194.6 µs → **256 µs** for a full walk. That is the
honest cost of the lane field — readback frames carry `kind = 7` and gain
nothing from it, but the frame could not widen for payload alone, because the
marker arrives last and both types must be the same width.

### 1.1 ⛔ My own derivation was short by two, and the measurement caught it

I first derived the slot as `2 × 12 × 2 = 48`. The bench reported the closest
two payload frames as **50**, at every one of twelve sweep points.

The missing factor is in the RTL's shape: when `ser_cnt` hits zero the
serialiser spends **one more clock** in the else-branch queueing the next frame,
so a frame occupies `bits×2 + 1`. The constant is corrected **to match the
mechanism**, not fitted to the data — the `+1` is readable off the
`if (ser_cnt != 0) ... else` structure.

⭐ And the sweep's boundary is a *different* number, which was worth getting
right rather than calling the derivation wrong. `build_rxfast` emits eight
`SHIFTIN`s then a `REARM`, so a loop is 9 actions and carries 8 completions:
the average completion period is `9d/8`, not `d`. Sustainable iff
`9d/8 ≥ 50`, i.e. **`d ≥ 45`**. Measured: clean from 45, dropping at 44.
**Both predictions now hold exactly.**

---

## 2. The liveness and RX-drop must-fires

| arm | result |
|---|---|
| within capacity (`d ≥ 45`) | **zero** bytes lost, `rx_drop_sticky` clear |
| forced over-rate (`d = 24`) | 7,404 completions, 3,998 delivered, **3,405 dropped — flag set every time** |
| survivors, after drops | **3,998 of 3,998 matched in order**, 0 unmatched |
| two RX lanes active | link reached its **ceiling** (frames exactly 50 apart) and lost nothing |

⭐ **The in-order check is what distinguishes two designs that look identical
in every other number.** A register that dropped the *new* byte and one that
silently *overwrote the pending* one would both set `rx_drop_sticky` and both
lose one byte per collision — but the second reorders the stream, and the host
cannot tell. Every delivered frame is required to match a completion by
**forward scan only**, so a reordered stream fails. The register refuses the
new byte.

### 2.1 ⚠ Two corrections to my own instrument, in opposite directions

The loss figure started as `completions − payload`, which:

1. **charged bytes still in flight** at the run's end and reported *"1 byte lost
   with the sticky flag CLEAR"* at five separate spacings — a **silent loss**,
   the most serious thing this gate can report, and entirely an artefact;
2. then, once in-flight bytes were subtracted, produced **negative** losses,
   because the subtraction counted a mid-shift *status* frame as an outstanding
   payload byte.

⇒ The drop is now counted **at the condition the RTL itself tests** —
`rx_push && rx_pend` — and the arithmetic is a **cross-check** with a stated
bound (`completions − payload − drops` must be 0..2, the two places a byte can
legitimately still be). Two corrections in opposite directions on a derived
quantity, when the event itself was observable all along.

---

## 3. ⚠ What is guaranteed, and what is not

**Average utilisation says nothing about a one-deep register.** What binds is
whether two *completions* land inside one 50-clock slot — a question about the
lanes' relative phase, not about rates. The two RX lanes' byte periods are
**400 and 3312 clocks**, unrelated, so the phase drifts and a collision is
reachable at some alignment.

⛔ **So the guarantee is that a collision is reported, not that it cannot
happen.** Both halves are measured: the flag sets every time, and survivors stay
in order. A host that must not lose a byte keeps the aggregate completion rate
below one per 50 clocks and reads **RX-drop**.

⚠ I earlier called the two-RX-lane measurement "a two-cycle margin" against a
slot of 48. The slot is 50, so that reading was not *near* the limit — it **was**
the limit. The margin that matters is on completion spacing, which that run
never pushed below the slot.

---

## 4. Where it lives

| | |
|---|---|
| `test/tb_rxbw.v` | the instrument: completions, payload frames, drops at the RTL's own condition, in-order check, min frame gap |
| `test/run_rxbw.py` | the 12-point sweep, both predictions, and `1.6p` re-quoted |
| `make_smoke_image.py --rxfast d` | one RX lane at a controlled completion rate |
| `model/a2/gate_admissibility_1_6.py` | `1.6p`'s capacity corrected, with the four missing factors named |
| `test/test.py` | the readback test now **measures** the frame gap (25) instead of trusting it |
| `docs/HOST_INTERFACE.md` | the 12-bit frame, `kind` table, marker-last, the capacity table |

Verified: `run_rxbw` PASSED (both predictions) · cocotb 8/8 with the measured
gap · mutants 8/8 · parameter sweep **7 benches × 2 points** · clean room 4/4 ·
corpus trace 7/8, 0 failed · A2 31/31 · `ci/run_gates.sh` 10/10.

## 5. Next

The sigrok-certified I²C frame — START, address, ACK, STOP — as planned.
