# D1, D2, and ruling 1.5 — which had never been built

Wilson's rulings after `2031cdd`. Both defects the rewritten cocotb suite
measured are fixed, and the question attached to D2 has an answer.

## The answer: 1.5's drive-mode construction was never built

Ruling 1.5 was `uio_out[i] = data[i] & pushpull[i]`, making "an open-drain pin
drives a 1" unsatisfiable **by construction**. Checked:

- **No per-pin drive-mode mask existed anywhere in `src/`** — no `pushpull`, no
  equivalent, by grep.
- `uio_out` was `e_pin_out[7:0]`, **raw**.
- `l_mode` is declared `reg l_mode [0:N_LANES-1]` — **per LANE**, where 1.5
  specified per **pin** — and was consulted only inside two opcode branches.

So the only open-drain discipline was an `if (l_mode[cur])` written out by hand
in each opcode path, and D2 is precisely the predicted consequence: a third
branch (the clock pin) was added later without it. **This is the third day-one
commitment found unbuilt**, after edge capture and the no-op half-bit.

### Built, and where it had to go

`pin_pp` is a per-pin register, set from each lane's header for both its data
pin **and** its clock pin, during the header window — so before `hdr_done`, and
therefore before any dispatch can read it. The mask is applied at the **output
flop's D input**.

Three placements were considered and two rejected for stated reasons:

| placement | why not |
| --- | --- |
| AND *after* the output flop | puts a gate on the pin; F2's structural check requires every output bit to be a register Q or a constant tie |
| a separate masked output stage | adds a cycle of latency to every protocol pin, moving measured timing and the published C/J numbers |
| **AND at the flop's D input** | **chosen** — the pin stays a flop Q, the mask costs nothing, no timing moves |

⭐ **Verified structurally, not argued**: F2 on the real netlist reports *all 24
output bits are a register Q or a constant tie*.

⛔ **Not a build-time constant, though the ruled pin map would allow one.**
`five_image` and `chain_image` legitimately drive `uio` pins **push-pull**
(`hdr(n, n, 1, …)` on pins 0..4), so a compile-time mask of the ruled map would
freeze those synthetic refill-load programs dead. ⚠ **That also means those two
images are not pin-map-legal**: they need five push-pull pins and the ruled map
provides four. Reported rather than silently changed, because their numbers feed
published refill-contention results.

## D1 — program byte 0 is readable, and the fix was two parts

**Part 1, `rb_addr`:** the readback incremented `rb_ptr` and asserted `rb_re` on
the same edge while the store was addressed from `rb_ptr`, so the read used the
already-incremented pointer and address 0 was never requested. Latching the
pre-increment address fixed that.

**Part 2, prime-before-framing — and part 1 alone was not enough.** With only
`rb_addr`, byte 0 became *reachable* but arrived **second**, behind one stale
frame: measured `0x22(stale), 0xAA, 0x22, …`. A frame was still queued from
`s_rdata` in the same breath as the read was *requested*. The readback now
primes: its first two visits issue the read and let it land without queueing a
frame. **A pipeline's first output is not data** — the same shape as the engine's
own prime-before-release.

Measured after the fix: frame 0 is `payload 0xAA`.

**The `s_rdata` allowlist reason is corrected.** It argued write-before-read
because "H_CAP only runs after H_REQ", and named only the header FSM. The
load-mode readback is a *second consumer* that inherited a reason which was
never about it, and on that path the ordering did not hold. After the fix both
consumers read it only after a real read, so the reason is now true — and the
entry says so, because **an allowlist entry is only as good as the set of
consumers it names.**

**The readback is now in the trace corpus under the seed sweep** (`+STAYLOAD=1`
keeps the part in load mode so `uo_out[6:4]` carries the framed stream):
3 seeds agree and the stream is cycle-exact across simulators. Randomised init
is what would have caught the stale first frame.

**The host contract is written down** — `docs/HOST_INTERFACE.md`, next to the
serial framing, which `PHASE1_CLOSEOUT_PART5` had flagged as owed and never
written: readback starts at address 0, the first payload frame *is* byte 0, the
rewind trigger is `rst_n` (not entering load mode, because the stream runs
concurrently with loading), and the stream is meaningful only after the load
completes.

## D2 — the open-drain clock pin is released

The clock pin now takes the same `l_mode` branch as the data pin: open-drain
pulls low with `oe=1, out=0` and **releases** with `oe=0`, leaving the high phase
to the observed rise through edge capture, which is what N1a requires. The
comment that justified driving the clock there — "so data and clock never need
P-ORDER per bit" — is about *ordering* and holds under either drive style.

### Both must-fires, priced as permanent arms

**(a) The cross-program invariant.** No pin of an open-drain lane may ever have
`oe=1` with `out=1`, checked over **every cycle of every corpus program**. Each
builder names its own `od_pins`, so the invariant's subject comes from what the
program declared rather than from a separately-maintained list. ⛔ Note `P_SCL`
appears in every program — the parked lanes are open-drain on it — which is the
case D2 escaped through.

`M_OD_CLK_PUSHPULL` restores the defect exactly. Priced: **clean 0 violations,
mutant 196**, e.g. `cyc 127 pin 1 uio_out=11111011 uio_oe=00000110` — the same
signature originally measured, so the mutant dies for its stated reason.

**(b) A real stretch.** A peer holds SCL **low** for 200 cycles:

| arm | contended (X) cycles on the line |
| --- | --- |
| clean | **0** — the hold wins; the stretch works |
| `M_OD_CLK_PUSHPULL` | **27** — the engine fights it: a short, not a stretch |

⚠ **The peer-driven version of this arm came out vacuous and is not what runs.**
`fram_i2c` stretches per ACK and never ACKs: it needs a START plus a matching
device address, which no program can send — the same cause as `corpus_spim`'s
OPEN entry. All four measurements (clean/mutant × stretching/not) were
identical: a must-fire firing on nothing. The bench holds SCL low directly
instead, which tests the electrical claim and needs no transaction.

⇒ **Consolidation worth recording: neither peer can be addressed by a program
yet**, so *every* must-fire that needs a peer **response** — SPI read data, an
I²C ACK, a peer-driven stretch — is blocked on the one ruling named in
`corpus.py`'s `OPEN` entry.

## The cocotb suite: both markers removed, assertions strengthened

The self-announcing mechanism worked as designed. On fixing D2 the arm reported
*"passed but we expected a failure"* and told me to delete the marker. Both
`expect_fail` markers are gone, and the tests now assert **more** than before:

- `test_serial_readback_walks_the_image` asserts the **whole image including
  byte 0**, with no frame discarded (it used to assert `image[1:]` and drop the
  first frame);
- `test_readback_reaches_byte_zero` is D1's must-fire: a distinctive byte 0 is
  the **first** payload;
- `test_open_drain_clock_pin_is_released` is a normal passing test.

7 of 7 pass.

## CI — the branch split

`gds` now has `branches: [cmos5l]` alongside its path filter. The harden takes
~3.5 h and the concurrency group cancels it on the next push, so **gate-level
results only landed if nobody pushed for three and a half hours** — three
hardens in a row were cancelled that way, each after real progress. That made
gate-level coverage a function of typing discipline rather than of policy.

Develop on `dev`, where `test` and the fast gates still run on every push; merge
to `cmos5l` at a checkpoint when a harden is wanted. The cancel behaviour then
becomes a feature: it only ever cancels a harden a newer checkpoint has
superseded. `workflow_dispatch` is unchanged, and the submission checklist still
depends on it.

## Suite state

`yosys_check` clean, 0 multi-driver, static assertion fires, **2933 flops** ·
F2 on the real netlist: **24 of 24 output bits flop-or-constant** ·
`gate_reset_audit` PASSED, 2936 flops with **2087 unreset — unchanged**, so all
the new state is reset-bearing · `run_a2` **30 of 30** (digest `b4e51034e283`) ·
`price_gates` **13 of 13 red** · `run_mutants` **4 of 4** · `tb_smoke` PASS ·
`tb_edge` **5 of 5** · `gate_reverse_trace` 8 of 8 ·
`gate_corpus_trace` **7 of 8, 1 open, 0 failed** · cocotb **7 of 7**.

⚠ The flop count rose 2901 → 2933. `pin_pp` (12), `rb_addr` (8) and `rb_prime`
(2) are 22 of those 32; the remaining 10 I have not attributed, and it is a
mapping difference rather than declared state.

⚠ **Gate level is still unverified.** This is the first checkpoint whose harden
is meant to land, and `gl_test` will give the first gate-level result for the
new suite.
