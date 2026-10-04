# Pre-registration — is the real condition port *utilisation*, not uniform spacing?

Written **before** the measurement. Wilson's ruling after `1e12780`.

## The problem with the shipped rule

`D* = k · L_REFILL = 20` was derived for the **uniform** case: k lanes all at the
same spacing `d`, each needing one refill per action through one fetch port.
Real programs are not uniform. SPI may be fast while UART is slow, and the rule
as built refuses any program whose **fastest** lane is under 20 even when the
port is nearly idle.

Concretely it would refuse SPI at 2 MHz (`d = 12`) with the other lanes slow —
killing the SPI-target 2 MHz reopening for a reason that is not the real
constraint.

## Hypothesis

The binding condition is **port utilisation**, with each lane contributing in
proportion to how often it consumes:

```
U_port = Σᵢ ( L_REFILL / dᵢ )   ≤   1
```

where `dᵢ` is lane *i*'s minimum inter-action spacing and `L_REFILL = 4`.

It reduces to the shipped rule when all spacings are equal:
`k · L / d ≤ 1 ⇔ d ≥ k · L = D*`. The shipped program sits at `U_port ≈ 0.43`.

## The prediction, and what would falsify it

**Prediction:** a mixed-spacing program with `U_port ≤ 1` measures a steady-state
prefetch stall of **0**, hence `J = 1` — *even when its `d_min` is far below
`D* = 20`*.

**Falsifier:** any program with `U_port ≤ 1` that measures a non-zero steady
stall. If that happens:

- the uniform rule `d_min ≥ D*` **stays** the published claim;
- `U_port ≤ 1` is recorded as **necessary but not sufficient**, not as the
  condition;
- `pe_asm` keeps refusing on `d_min`.

⛔ The falsifier is stated before the run so the result cannot be re-read as a
confirmation afterwards. This is the same discipline the double-buffer
pre-registration used, and that falsifier did fire.

## The arms

Each measured on a 200,000-cycle run with an asserted ≥100k-cycle steady window
and the image byte count checked — the conditions the J sweep now enforces,
because four earlier probes produced confident numbers from empty windows,
unloaded images and transients.

| arm | delays | `U_port` | `d_min` | prediction |
| --- | --- | --- | --- | --- |
| A uniform at D* | 20,20,20,20,20 | 1.000 | 20 | stall 0 |
| B one fast, rest slow | 12,200,200,200,200 | 0.413 | 12 | **stall 0** (d_min ≪ D*) |
| C faster, rest slow | 8,100,100,100,100 | 0.660 | 8 | **stall 0** |
| D near the boundary | 7,40,40,40,40 | 0.971 | 7 | **stall 0** |
| E control, over the line | 6,30,30,30,30 | 1.200 | 6 | stall > 0 |
| F realistic mix | 12,50,60,70,80 | 0.587 | 12 | **stall 0** |

Arms B, C, D and F are the test: all have `d_min` below `D*` and would be
refused today. Arm E is the control — if it does **not** stall, the measurement
is not sensitive to `U_port` at all and nothing here is interpretable.

⚠ Arm A is already known to measure 0; it is included as a positive control so a
sweep that reports 0 everywhere because it is broken can be told apart from one
that reports 0 because the hypothesis holds. (A sweep reporting 0 everywhere is
exactly what one of the four broken probes did.)

## If it holds

`pe_asm` switches to `U_port ≤ 1`, which unblocks mixed programs with a fast
lane — including the SPI-target 2 MHz reopening. `D*` remains correct as the
uniform special case.

## A separate question it may also answer

`5 · 4 / 19 = 1.05 > 1`, and d = 19 measured **clean**. So either the effective
refill occupancy is slightly under `L_REFILL = 4` — some overlap between a
refill and the dispatch that freed the slot — or the boundary is not exactly at
`U_port = 1`. Arm D sits at `0.971` and arm E at `1.200`, which brackets it but
does not resolve it; resolving it needs the witness trace, still owed.

---

# RESULT — the falsifier fired. `U_port ≤ 1` is necessary, not sufficient.

Measured as pre-registered: 200,000-cycle runs, steady window 195,908 cycles,
image byte count checked on every arm.

| arm | `U_port` | `d_min` | predicted | **measured** | |
| --- | --- | --- | --- | --- | --- |
| A uniform at D* | 1.000 | 20 | 0 | **0** | control holds |
| B one fast, rest slow | 0.413 | 12 | 0 | **0** | ✓ |
| C faster, rest slow | 0.660 | 8 | 0 | **7** | ⛔ **FALSIFIED** |
| D near the boundary | 0.971 | 7 | 0 | **7** | ⛔ **FALSIFIED** |
| E control, over the line | 1.200 | 6 | >0 | **7** | control holds |
| F realistic mix | 0.587 | 12 | 0 | **0** | ✓ |

Arms C and D have port utilisation of 0.66 and 0.97 — comfortably under 1 — and
**stall 7 anyway**. Both controls behaved, so the measurement is sensitive to
the thing being tested: A (at the boundary) is clean and E (over it) stalls.

⇒ **Per the pre-registration, and without re-reading the result:**
- the uniform rule `d_min ≥ D*` **stays** the published claim;
- `U_port ≤ 1` is recorded as **necessary but not sufficient**;
- `pe_asm` keeps refusing on `d_min`.

## But the ruling's motivation was right, and that is a separate finding

**Arms B and F measure 0 with `d_min = 12`, far below `D* = 20`.** So the
uniform rule really is *conservative for mixed programs*: it refuses programs
that demonstrably do not stall. The SPI-at-2-MHz case the ruling was trying to
unblock **is** reachable — `U_port` is just not the predicate that reaches it.

What the arms rule out and what they leave open:

- `U_port` alone: **ruled out** (C, D).
- `d_min` alone: **ruled out** — uniform `12,13,14,15,16` has `d_min = 12` and
  stalls 11, while B has `d_min = 12` and stalls 0.
- A **conjunction** of a per-lane spacing floor with an aggregate port term fits
  every point I have, including both of those. ⚠ It is a *hypothesis fitted to
  this data*, not a derivation, and it does not get published on that basis.

Two numbers point at where the floor comes from. The stall in C, D and E is
exactly **7**, which equals `L_CAP` — "in-flight(3) + scan(1) + own(3), via
winner-first", i.e. a lane's own refill round-trip rather than the aggregate
contention. The uniform sub-`D*` cases stalled **11**, above `L_CAP`, which is
what aggregate contention would add. That is consistent with two distinct
mechanisms, which is why one scalar cannot express the condition.

And `U_port` cannot be exactly the aggregate term either: uniform `d = 19` has
`U_port = 5·4/19 = 1.053 > 1` and measures **0**. So the effective refill
occupancy is slightly under `L_REFILL = 4`, which is the same off-by-one that
made `D* = 20` conservative against a measured cliff at 19.

⇒ **Owed before any generalisation is published:** the witness trace of the
worst stall event — which lanes' refills were queued ahead, in what order — for
one sub-`D*` uniform case *and* one falsifying mixed case (arm C). Two
mechanisms need two chains, and a scalar fitted to six points is not either of
them.

---

# WITNESS TRACES — the mechanism, and why both scalars failed

`test/tb_witness.v` keeps a 48-cycle ring of what the single fetch port was
doing and dumps it at each new steady-state maximum. Two chains, as ruled.

## Chain 1 — sub-`D*` uniform (`12,13,14,15,16`), stall 8 at cycle 4870

```
cycle  pst  pl  winner  head?  stall
4863    0    0    0       0      0     port serving lane 0: SCAN
4864    1    0    0       0      1                          REQ
4865    2    0    1       0      2                          WAIT
4866    3    0    1       0      3                          CAP   -> lane 0 done
4867    0    1    1       0      4     port starts the WINNER's own refill
4870    3    1    1       0      7                          CAP
```

The winner (lane 1) waited for **one other lane's complete refill, then its
own**: 2 × `L_REFILL` = 8 cycles.

## Chain 2 — arm C (`8,100,100,100,100`), stall 7 at cycle 4107

```
4100    0    4    0       0      0     port serving LANE 4 -- which is at d=100
4103    3    4    0       0      2       its refill completes
4104    0    0    0       0      3     only now does the winner's own refill start
4107    3    0    0       0      6
```

**Lane 4 runs every 100 cycles and its refill was still in the way.** That is
the *speculative spare fill*: the prefetch scan fills a lane's empty SPARE slot
when nothing more urgent is pending — "filling a SPARE is speculative work that
can wait" — so a nearly-idle lane is still a port consumer.

## Why `U_port` failed, structurally

`U_port = Σ L_REFILL/dᵢ` counts **one refill per action per lane**. The port also
issues **speculative spare refills for any live lane whose spare is empty**,
which are not tied to that lane's action rate at all. So a program can have
`U_port = 0.66` and still find the port busy when its fast lane needs a head
refill. The predicate was missing a whole class of port work, which is why it
failed at arms C and D while the controls behaved.

## The shape of the real bound, and where the old one went wrong

Both chains are the same mechanism:

```
stall  =  (refills queued ahead  +  1) × L_REFILL
```

with at most one refill in flight per lane, so at most `k − 1` ahead:

```
worst-case stall  ≤  k · L_REFILL  =  20
```

⛔ **The published derivation capped the stall at `L_CAP = 7`.** The structure
permits up to **20**. That cap is the unsoundness: it is below the worst case
the chain can produce, which is why ten admissible points measured above it.
The largest value actually observed is 12, comfortably inside 20.

⭐ **And it re-derives `D*` from the same place.** `d ≥ k · L_REFILL` is exactly
the condition that the port can serve every live lane's refill within the
shortest action period — so at or above `D*` nothing is ever found missing, and
the stall is 0. The scoped claim and the worst case now come from one argument
rather than two.

⚠ **What is still not established.** `k · L_REFILL = 20` is an upper bound from
the chain's structure, not a tight one, and the mixed arms show the threshold
for *their* shape is lower (arm B passes at `d_min = 12`, arm C fails at 8 —
consistent with needing more than `2 · L_REFILL` when only one competitor is
typically queued). A per-program bound would need the number of concurrently
pending refills, which depends on the spare-fill policy. ⛔ No universal number
is published on the strength of two traces: if a universal `J` is wanted, the
sound-but-loose value implied here is `k · L_REFILL + J_WINNER_REG = 21`, far
above the retracted 8, and that is Wilson's call rather than a number I should
quote into the lane table.
