# The ruling implementation audit

Wilson's ruling after `534fbb9`: five day-one commitments had been found unbuilt
**one at a time, each by accident**. That is a property of how we look, not of
how many are left, so the answer is a single sweep plus a standing check.

`model/gate_ruling_audit.py`.

## Result

**44 rulings tabled — 17 built, 1 partial, 3 unbuilt, 3 superseded, 20 analysis.
Coverage 32 of 32 ruling identifiers, 0 unreviewed.** Every `built` claim is
backed by an anchor that resolves; the gate is red if one stops resolving.

### Why reverse traceability did not already cover this

`gate_reverse_trace.py` checks **behaviours → fields**: every ruled behaviour has
an encoding field to carry it. That is a different question from **rulings →
implementation**, and a ruling can have a perfectly good field with no logic
reading it. 1.5 had a `mode` bit in every header and nothing at the output stage.

### What gives it teeth

Each `rtl`/`model` item carries a **file plus a substring that must be present**.
A ruling marked `built` whose anchor stops resolving fails the gate — so deleting
`pin_pp` goes red instead of being rediscovered in a year. A ruling marked
`unbuilt` fails if its anchor *does* resolve, which catches a status that has
gone stale in the other direction.

**The mechanism is priced, not trusted.** A self-test confirms a bogus needle is
rejected, a missing file is rejected, and a real anchor is accepted — so the gate
is known to be *able* to fail.

### Coverage is measured, not asserted

An audit that quietly covers 60% while looking complete is the exact failure it
exists to prevent. Ruling identifiers are **scraped from `docs/`** and compared
against the table; anything with no entry prints as UNREVIEWED with a count.
The scraper is deliberately loose — over-reporting is the safe direction for a
coverage measure — so its exclusions are named rather than silently filtered
(`F7` is a CRC byte in `TA02_RESULTS.md`, not a ruling).

## Two more unbuilt rulings, found by the sweep

Both are stated as **loader behaviour** and the chip has none.

- **1.6s** — "an open-drain lane must be assigned a `uio` pin … so the loader
  **REJECTS** it". There is no load-time rejection in the RTL, and the image
  toolchain only states the rule in prose: `make_smoke_image.hdr()`'s docstring
  says open-drain "is only MEANINGFUL on a `uio` pin" and asserts nothing.
- **1.6t** — "the loader **COMPUTES** the program's J from `d_min`". No RTL
  site; the derivation lives in `gate_j_program.py`.

⛔ And two RTL comments defer to a screen that does not exist — `project.v`'s
"which is what 1.6 rejects at load time" and `pe_store.v`'s "1.6's load-time
screen is what guarantees the image is admissible".

⚠ **Being inside a passing model gate is what let them read as built.**
`gate_admissibility_1_6.py` carries 23 conditions, each with a check and a firing
witness, and it is green — but it checks **programs we author**, not a chip-side
rejection. For most of the family that is the right home: 1.6a's queue-slot
bound and 1.6i's minimum pulse width are obligations on whoever writes the
program. For 1.6s and 1.6t it is not, because they name hardware.

The 1.6 family is therefore tabled **by reference** to that gate, with the
caveat recorded on every entry, and s/t broken out as `unbuilt`.

## The 1.5 limit — scope corrected

My earlier claim that "the ruled map fixes each pin's class at build time, so the
loader can reject a mode mismatch" was **too broad, and Wilson is right**:

- It holds for **`uo_out`** — output-only, therefore push-pull only — and that
  rejection already exists as **1.6s**.
- It does **not** hold for `uio`: those pins are physically capable of either
  drive class and roles are assigned per program, so there is no build-time class
  to check a header against.

⇒ The exact check reduces to one that exists. An I²C lane misdeclared push-pull
on `uio` stays undetectable by the loader, and "open-drain never drives a 1
**holds by declaration**" is the honest record.

### `five_image` / `chain_image` relabelled

Not **illegal** — push-pull on a `uio` pin is physically fine. They just do not
follow the ruled **placement** (push-pull on `uo_out`). Both are relabelled
*scheduler stress images, not pin-map-legal programs*, and the reason the 1.5
mask is runtime rather than build-time is recorded next to them. Ruling #2's
legal-copy `J`/stall re-run still applies.

## Open, and awaiting a decision

- **TX routing** (`partial`). One shared FIFO with no lane tag is only correct
  with **one** TX-consuming lane. With more than one, consumption order is the
  EDF interleave — timing-dependent — so a host cannot order its pushes and the
  wrong lane transmits the wrong byte **silently**. Awaiting a choice between a
  2-bit lane tag (the retired pop and view-select freed `ui_in[0]` and
  `ui_in[5]`) and an admissibility limit of one TX-consuming lane.
- **RX attribution** (`unbuilt`). The mirror: serial frames carry payload or
  status but no lane identity, so with UART-rx and SPI-target both receiving the
  host cannot attribute a byte.

Must-fires owed for both: two TX lanes interleaving with host-ordered pushes,
each lane emitting only its own bytes; two RX lanes receiving at once, every byte
attributed correctly.

## Suite

`gate_ruling_audit` **PASSED** (0 unreviewed, self-test green) · `run_a2`
**30 of 30** · `price_gates` **13 of 13 red** · `gate_reset_audit` PASSED ·
`run_mutants` **4 of 4** · `tb_smoke` PASS · `tb_edge` **5 of 5** · cocotb
**7 of 7**.
