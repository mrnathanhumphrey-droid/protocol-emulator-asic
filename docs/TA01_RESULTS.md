# TA-01 RESULTS — UART conformance is a decidable, non-vacuous query

**Status: GREEN.** Re-runnable by anyone: `sigrok-cli` + Python, no timed-automaton
tool build required for this stone.

```
cd model/ta01 && python run_ta01.py
```

## The one claim this probe tested

That *"does this UART-TX program conform to UART?"* can be **answered** — as
reachability of a BAD state in `(executor ‖ deterministic monitor)` — rather than
argued. Safety-reachability, not language inclusion: `L(E) ⊆ L(S)` is
**undecidable** for timed automata (the Alur–Dill universality trap), while
reachability is decidable, and the two coincide **exactly** when the monitor is
deterministic **and total**.

## Gate 0 — the external decoder, run FIRST

**sigrok-cli 0.7.2's `uart` protocol decoder** — foreign code, written by other
people from the standard — decodes our waveform and **agrees with `S_UART` on
every waveform, good and mutant. Zero disagreements.**

⛔ **This gate is the whole method's smoke test, and it exists because the rest of
the stack cannot catch its own blind spot.** `uart_ta.py` holds two models written
by one hand from one understanding of UART; a shared misconception — stop bit two
bits wide, data sent MSB-first — passes determinism, totality, conformance and
every mutant, and TA-01 goes green on a protocol that is not UART. The must-fire
arm proves the monitor is not **vacuous**; it cannot prove the monitor is
**correct**. sigrok is the only genuinely independent authority in the stack.

⭐ It also confirmed something nobody asked it to: the decoder prints the
individual bits `1 0 1 0 1 0 1 0` before the byte, which validates **LSB-first
ordering** and not merely the final value.

## Gate 1 — determinism AND totality, as two separate checks

**11,362 combinations** (13 states × 437 clock values × 2 levels). Zero states
with ≥2 enabled transitions; zero states with 0 enabled.

⛔ **Totality is the dangerous half and it is not symmetric with determinism.**
Two enabled transitions breaks the safety↔conformance equivalence. **Zero** enabled
transitions silently **drops** the behaviour, so it can never reach BAD, and reads
as **CONFORMING**. The first draft of `UartReceiver.step` had no catch-all for
clock regions unreachable in correct operation — that is the hole, and it only
closed because the gate checks the two properties separately.

## Gate 2 — good programs conform

| byte | bit-order | ours | sigrok | decoded | agree |
|---|---|---|---|---|---|
| 0x55 | sensitive | CONF | CONF | 0x55 | OK |
| 0x0F | sensitive | CONF | CONF | 0x0F | OK |
| 0x01 | sensitive | CONF | CONF | 0x01 | OK |
| 0x00 | **palindrome** | CONF | CONF | 0x00 | OK |
| 0xFF | **palindrome** | CONF | CONF | 0xFF | OK |
| 0xA5 | **palindrome** | CONF | CONF | 0xA5 | OK |

⛔⛔ **THE TEST-BYTE FINDING.** A byte equal to its own bit-reversal **cannot catch
an LSB/MSB swap**. Of the originally-specified four — `0x00`, `0xFF`, `0x55`,
`0xA5` — **three are palindromes**; only `0x55` (which reverses to `0xAA`)
discriminates, and it was the one run first *by luck, not design*. `0x0F` and
`0x01` were added so **3 of 6 are bit-order sensitive deliberately.**

## The arm set — must-fire and must-NOT-fire

| mutant | expected | ours | sigrok | died by |
|---|---|---|---|---|
| M0 +2% baud | **CONFORM** | CONF | CONF | — |
| M1 +10% baud | VIOLATE | VIOL | VIOL | framing |
| M2 stop low | VIOLATE | VIOL | VIOL | framing |
| M3 inverted | VIOLATE | VIOL | VIOL | framing |
| M4 7 data bits | VIOLATE | VIOL | VIOL | byte mismatch |
| **M5 bit3 flipped** | VIOLATE | VIOL | VIOL | **byte mismatch** |

⭐ **M0 is the false-fail guard.** `9.5 × 0.02 = 0.19` bit of displacement, inside
the ±0.5 bit budget, so a real receiver tolerates it and so must ours. A monitor
that over-rejects is one nobody else's UART passes — worse than useless.

## M1's mechanism — and the gap it exposed

The monitor samples `Dk` at `217 + 434(k+1)`; the drifted executor holds `Dk` over
`[478(k+1), 478(k+2))`. **First data bit sampled from the wrong executor bit: D4**,
matching `44(k+1) > 217 ⇒ k+1 > 4.93` exactly. A mutant must die for its **stated
reason**, and this one does.

⛔⛔ **BUT IT IS DETECTED AT THE STOP SAMPLE, NOT AT D4** — a wrong data bit is
silently *recorded*, nothing checks it until the byte comparison, so the framing
error reaches BAD first. **M1 therefore exercises the FRAMING conjunct, not the
DATA conjunct.** Before `M5` existed, **every mutant in the set died on framing**
and the byte-comparison half of BAD was never load-bearing. M5 — one data bit
flipped, framing perfect — can only die by comparison, and does.

That is the same shape as splitting determinism from totality: two conjuncts in
the condition, only one of them actually tested.

## Gate 4 — scaling, not termination

| baud | T (cycles) | product steps | wall |
|---|---|---|---|
| 9,600 | 5,208 | 249,990 | 83.7 ms |
| 115,200 | 434 | 20,838 | 6.9 ms |
| 1,000,000 | 50 | 2,406 | 0.8 ms |

Linear in `T` — finite-state enumeration of a single frame.

⛔ **The frame-count axis is deliberately NOT run here.** A second frame requires
the monitor to return `DONE → IDLE`, i.e. **to loop** — and looping is exactly what
forces the clock to reset and makes finite-state enumeration blow up. That belongs
to **TA-01b**, where the zone-based formulation earns its keep instead of
decorating. **This scaling table is the empirical argument for why TA-01b is
needed**, not merely tractability hygiene.

## ⛔ What TA-01 does NOT establish

- **Not** that any RTL implements this model — that is a later refinement probe.
- **Not** the general case — SPI/I²C and the generic table-interpreter executor
  are later probes.
- **Not** a Lean proof — the soundness metatheory is a companion track.
- **Not** receive/sniff — this is transmit only.
- ⛔ **And gate 1's checker was written by the same hand as the monitor**, so it is
  a consistency check, not an independent one. `_enabled()` re-derives enablement
  from the guard structure rather than calling `step()`, which helps, but **sigrok
  remains the only foreign authority in the stack.** TA-01b should keep it.
