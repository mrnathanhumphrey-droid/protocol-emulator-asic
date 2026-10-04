# SPEC v4 — reverse traceability, and the golden model it needed

Wilson's next sequenced item after the re-baseline. It could not be done as
asked, because the artefact it runs on did not exist.

---

## 0. The golden model did not exist

`docs/ARCH_PREREG_01.md`, commitment 3:

> **The golden model is written as an executable formal semantics of the ISA**
> from day one — so a conformance proof later starts from a spec that already
> exists instead of one reconstructed afterwards.

Prediction **A3** ("bit-exact against a golden model on both simulators") and
falsifier **F1** ("any protocol's waveform diverges from the golden model → the
engine is wrong; no timing or area number counts") both rest on it.

> ⛔ It was never built. The engine, the double buffer, the jitter-sound
> pipeline, prime-before-release and two digest bumps all landed first. Nothing
> in the repository executed an action word — `test/make_smoke_image.py` only
> **encodes** them. So every claim about what the engine *does* has been a claim
> about what the RTL does, checked against a testbench written beside it.

It is now `model/golden.py`.

### Written from the spec, not from the RTL

| what | source |
|---|---|
| opcode semantics | `gate_program_census`'s action vocabulary + its enumerated programs |
| action-word layout | `gate_encoding_f1.action_word` |
| state | `gate_spec_freeze_s2.frozen_fields` |

> ⛔⛔ A golden model transcribed from `pe_engine.v` is a **same-author
> re-derivation**: it agrees with the engine on every bug they share, and the
> agreement means nothing. Same error as a measurement "confirming" the bound it
> was derived from.

### The mechanism that makes this a check and not an opinion

State is a `FieldSet` whose keys **must** appear in the frozen field table. An
access to an unfrozen name is **recorded**, not silently serviced.

```
S2 traceability   detects a FIELD WITH NO RULING      (forward)
this              detects a BEHAVIOUR WITH NO FIELD   (reverse)
```

S3 found five such fields by writing RTL and watching it fail — three
registered-read off-by-ones and a drive-mode bug later. This is the cheaper
direction.

**Must-fire:** the two fields S3 named independently (`program counter`,
`program base`) must both be reported, or the recording is not working and a
"none" result would be meaningless. Both reported.

---

## 1. ⛔⛔ FINDING: `armed` — reactive lanes cannot be released by their peer

Not on S3's list of five. The semantics needed somewhere to record "this lane is
waiting on an external edge", which is **not** the same state as "next action at
time T". Chased into the RTL and **scanned, not argued**:

| check | result |
|---|---|
| `OP_ARM`'s case body is empty (a no-op) | **True** — `OP_ARM, OP_REARM: ;` |
| any edge capture on a **protocol** input pin | **none found** |
| only edge detect is the loader's `wr_rise` | **True** — that's the *host* interface |

⇒ **UART-rx and SPI-target are both REACTIVE lanes** — their releases come from a
peer edge (a start bit, a CS fall) — and the engine has no edge capture, no armed
state, and an `ARM` that does nothing. Those two lanes would run **open-loop** on
their programmed delays and drift against the peer.

> ⚠ **The scheduling analysis is not invalidated.** It bounds
> release-to-completion *given* a release, and models reactive releases as an
> arrival curve, which is sound. What is absent is the mechanism that makes a
> release **happen**.

> ⛔ **And this is the second day-one commitment found unbuilt.** Commitment 1 is
> *"edge timestamping on input pins — cheap (a counter and a capture register),
> and it is the entire substrate for protocol discovery. Built even though
> nothing consumes it yet."* Neither it nor the golden model existed.

**Owed: a ruling.** Build edge capture now, or scope it to Phase 2 and say
plainly that the reactive direction is unimplemented? The honest framing is that
*three of five lanes work and two are open-loop*, and that is a product
statement, not a timing one.

---

## 2. All 8 opcodes now measured **on the RTL**, not 2 of 8

`gate_cj_bounds` had been reporting `C_max` derived for all 8 action types and
measured on **two**, because the default smoke program only uses LEVEL and
re-arm.

> ⛔ The golden model exercising an opcode settles *"is any opcode unneeded by
> the required protocols"*. It settles **nothing** about the silicon. Conflating
> the two is an exact answer to the wrong question.

So `test/make_smoke_image.py --census` builds a program that makes the **RTL**
execute every opcode:

| opcode | n | min | max | derived |
|---|---|---|---|---|
| LEVEL | 52 | 2 | 2 | 2 |
| SHIFT | 26 | 2 | 2 | 2 |
| SHIFTIN | 39 | 2 | 2 | 2 |
| READBIT | 39 | 2 | 2 | 2 |
| START | 26 | 2 | 2 | 2 |
| STOP | 26 | 2 | 2 | 2 |
| ARM | 39 | 2 | 2 | 2 |
| REARM/loop | 88 | 2 | 2 | 2 |

**`C_max = 2` is now derived AND measured on 8 of 8.** Measurements land in
`cj_measured_alt.txt` via the input-dependent path, so they cannot clobber the
shipped figures.

> ⚠ The census image is a **coverage program, not a protocol**: its opcodes run
> in an order chosen to reach them all, so its pin waveform means nothing and it
> legitimately fails the bench's *"lane 1 moved its pin"* assertion — lane 1 runs
> SHIFTIN/READBIT/ARM, none of which drive a pin. **The bench was not weakened to
> make it pass.**

---

## 3. ⛔⛔ FINDING: the bench silently truncated every image to 51 bytes

`localparam integer IMG_BYTES = 51` — the loader shifted in exactly 51 bytes
regardless of the image's real size.

The census image is 63 bytes. Bytes 51–62 were never written to the store, so:

1. the engine fetched an **X** action word;
2. `ST_WB` does `l_timestamp <= l_timestamp + a_dly` **unconditionally**, so the
   timestamp became X;
3. `ready` tests `now - l_timestamp`, so the lane went **permanently unready**.

One lane died, the other kept running, and the bench reported its results as
though the program were complete.

> ⭐⭐ **It had never fired because every image so far was exactly 51 bytes.** The
> default, stress, five-lane and chain programs all have 5 headers + 7 actions =
> 30 + 21 = 51 — matching **by coincidence of construction**. The census image was
> the first with a different action count and it broke on its first run.
>
> ⇒ **A constant that encodes the shape of one artefact is a trap waiting for the
> second artefact.** Same class as the must-fire whose witness was a hard-coded
> 3 MHz, which went vacuous when `r − C` moved by one.

**Fixed by derivation:** `$readmemh` leaves unwritten entries X, so the highest
initialised index + 1 is the image size. The array is sized to the **store**
(2^AW = 256) so no image can overflow it, and a too-short read is **asserted** —
`$readmemh` warns on a missing file but does not stop the run.

---

## 4. State

- **A2 suite 28 of 28**, digest `b4e51034e283`, ledger entry 2 of 2.
- `price_gates.sh` **13 of 13**; `run_mutants.py` **4 of 4**.
- Default smoke image **bit-identical** after all of the above: 130/84 edges,
  C = 2.00, cold 0 == steady 0, invariant 0 violations.
- `gate_reverse_trace.py` is in `run_a2.py`'s list via `../`, deliberately: it
  lives in `model/` with the other RTL-facing gates, and **an out-of-suite gate
  is a gate nobody runs**.

### Still owed

1. **A ruling on `armed` / edge timestamping** (§1) — the reactive direction is
   unimplemented and that is a product statement.
2. **CI `gds` + F2 faces 3–4.** Watch pinned to run `37164499313` (`2e40bef`).
   ⭐ `0dd6bee` changed only `model/` and `test/` files —
   `git diff --name-only 2e40bef 0dd6bee -- src/ info.yaml .github/` is **empty** —
   so the RTL and flow are identical and the older run's netlist is equally valid
   evidence. The duplicate run was cancelled rather than hardening the same RTL
   from scratch.
3. **TChecker for bursty-with-jitter** — the two `m_i > 1` lanes still carry one
   foreign witness at `J > 0` where everything else carries two.
4. `test/test.py` — all 5 cocotb tests still assert the superseded load path.
