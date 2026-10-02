# A2-CLOSE — `D_i` derived, A2a/A2b closed against it

Answers A2-CLOSE (rung 3). Run order was the one specified: Part A on UART first
as the method's validation, then straight to Ethernet as the lane that decides
the gate.

**Reproduce:**
```
python model/a2/jitter_dmax.py          # Part A: derive D_i, all lanes
python model/a2/gate_jitter_sigrok.py   # Gate A-FOREIGN: sigrok at the boundary
python model/a2/a2_close.py             # Parts B and C against the derived D_i
```

---

## Part A — `D_i` is now a formula, not an open question

```
D_i = min( floor(T_i/2),  T_i - floor(T_i/2) - 1 )
```

Derived before the search ran, so the measurement had something to contradict.
The receiver locks on the first low cycle, so the start edge's own delay `d_0`
shifts the whole sample grid *with* it — a uniform delay is invisible. Sample `m`
lands at `d_0 + half + m*T` and must sit inside segment `m`'s actual interval
`[m*T + d_m, (m+1)*T + d_{m+1})`:

| side | constraint | bound |
|---|---|---|
| late edge | `d_m − d_0 ≤ half` | `J ≤ half` |
| **early edge** | `d_0 − d_{m+1} < T − half` | **`J ≤ T − half − 1`** ← binds |

| lane | `T_i` | predicted | **searched** | witness |
|---|---|---|---|---|
| UART 115200 | 434 | 216 | **216** | `early_1` |
| SPI 1 MHz | 25 | 12 | **12** | `early_1` |
| I²C 400 kHz | 62 | 30 | **30** | `early_1` |
| 10 Mbit Ethernet | 5 | 2 | **2** | `early_1` |

The witness is `d_0 = 217, all later edges on time` at every lane — the **early**
side, one cycle tighter than the `T/2` the spec pre-registered. `D_UART = 216,
not 217.`

### Gate A-FOREIGN — sigrok flips at the same cycle

Not "sigrok agrees at the boundary" (a decoder that failed everything would
satisfy that on one side by luck). A ladder across the boundary, with three
conditions checked separately and a non-vacuity check:

| v | ours | sigrok | decoded |
|---|---|---|---|
| 0, 1, 108, 214, 215, **216** | CONF | CONF | `0x55` |
| **217**, 218, 250, 300, 433 | VIOL | VIOL | `0xD5` |

(a) both conform for every `v ≤ 216` ✅ (b) both refuse for every `v > 216` ✅
(c) verdicts agree on all 11 rungs ✅ (d) non-vacuity: both authorities produced
both verdicts ✅

⭐ The decoded byte above the band is **`0xD5`, not `0x55`** — the bits shifted
by exactly one position. That is the whole-grid misalignment the derivation
predicts, caught independently by foreign code.

### ⛔ One of my own predictions was refuted

I predicted the worst-case byte would be the maximum-edge-density one (`0x55`).
**Measured over all 256 bytes: `D` is data-INDEPENDENT** — every byte conforms at
216 and breaks at 217, across edge counts `{1,3,5,7,9}`. The mechanism is not
per-edge margin erosion but misalignment of the entire sample grid, which bites
regardless of how many boundaries carry a real edge. The *value* was predicted
correctly; the *reason I gave for it* was wrong.

---

## Part B — A2a feasibility

`B_i` derived from the deadline ordering, not inherited as `(k−1)`. Because
`D_i` spans 2..216 the ordering is strongly shaped and **`B_i` is not uniform** —
the latest-deadline lane is blocked by nothing:

| lane | `T_i` | `C_i` | `D_i` | `B_i` | blocked by (later deadline) |
|---|---|---|---|---|---|
| UART 115200 | 434 | 2 | 216 | **0** | — nothing |
| SPI 1 MHz | 25 | 2 | 12 | 1 | UART, I²C |
| I²C 400 kHz | 62 | 2 | 30 | 1 | UART |
| 10 Mbit Ethernet | 5 | 2 | 2 | 1 | UART, SPI, I²C |

**Three required protocols — condition (1)** `U = 0.11687 ≤ 1` ✅ (reproduces the
pre-reg's 11.7%). **Condition (2)** passes at all 37 scheduling points; tightest
is `d = 12`, demand `2 + B 1 = 3`, slack 9. `H = 10850` cycles.

**With Ethernet — condition (2) FAILS at exactly one point:**
```
d = 2    demand 2 + B 1 = 3  >  2
```

---

## Part C — A2b the bound

**Three required protocols — A2 GREEN:**

| lane | `m_i` | `r_i` | `D_i` | margin |
|---|---|---|---|---|
| UART 115200 | 1 | 7 | 216 | 209 |
| SPI 1 MHz | 1 | 8 | 12 | 4 |
| I²C 400 kHz | 1 | 8 | 30 | 22 |

**With Ethernet — A2 RED:**

| lane | `m_i` | `r_i` | `D_i` | margin | |
|---|---|---|---|---|---|
| UART 115200 | 1 | 11 | 216 | 205 | OK |
| SPI 1 MHz | 1 | 12 | 12 | **0** | ⚠ zero margin |
| I²C 400 kHz | 1 | 12 | 30 | 18 | OK |
| 10 Mbit Ethernet | 2 | 10 | 2 | −8 | **INFEASIBLE** |

### The Ethernet verdict is structural, not numerical

```
D_Ethernet = 2        one service action C = 2        blocking B = 1
C + B = 3  >  D = 2
```

`C + B` is a floor on the response time that no scheduling policy can go under:
one indivisible service action plus one non-preemptive blocking action. **Ethernet
is infeasible for any `D < 3`.** Tightening `D_Ethernet`, changing the sampling
geometry, or re-deriving against a real Manchester monitor cannot rescue it —
they can only make it worse. Interference from the other three lanes never even
gets consulted. This is **A2-F4**: non-preemption binding, a design result.

### The escape, computed — `w = 4`

A `w`-bit shift register clocked at the bit rate makes the engine's event "refill
`w` bits": `T = 5w`, and with ping-pong buffering `D = 5w − 1`. Every lane
re-checked at each `w`, not just Ethernet:

| `w` | `T` | `D` | `U` | cond(2) | verdict |
|---|---|---|---|---|---|
| 1 | 5 | 4 | 0.5169 | pass | infeasible: Ethernet (10/4) |
| 2 | 10 | 9 | 0.3169 | pass | infeasible: Ethernet (10/9) |
| **4** | **20** | **19** | **0.2169** | **pass** | **FEASIBLE** |
| 8 | 40 | 39 | 0.1669 | pass | FEASIBLE |
| 16 | 80 | 79 | 0.1419 | pass | FEASIBLE |

**`w = 4` is the derived minimum shift-register width** — the smallest `w` at
which every lane satisfies `r_i ≤ D_i` and condition (2) holds. A number the
architecture has to honour, not a tuning knob.

---

## Overrides to the spec

**O1 — A2-F5's threshold is 2× too loose to catch the bug it names.** The spec
caps `D_i < T_i` and identifies the failure as "letting edges cross their own
sample". But an edge crossing its own sample *is* the `D > T/2` case. A search
returning `D_UART = 300` would be badly broken and would still pass a `D < 434`
cap. **The cap that can catch the named bug is `D_i ≤ floor(T_i/2)`.** Same
family as "a wrong scope lives in the predicate *and* its constant".

**O2 — the closed form bounds `L_i`, and Part C's layout invites comparing it to
`D_i`.** `sum_{j≠i} C_j + max_lp(C_j−1)` omits `C_i` and the `+1` entirely, so it
is a busy-period bound, not a response time. It sits immediately below
`r_i ≤ D_i` in the spec, and **I made exactly that mistake in my first results
table** — printed it beside `r_i` and `D_i` as if comparable. It should be
labelled as an `L_i` bound and never appear in a table with a `D_i` comparison.

**O3 — A2-F1 is right about Ethernet but will mis-fire first.** "Closed form ≠
recurrence, expected at Ethernet (`m_i>1`)" — but the two already disagree at
`m_i = 1` (UART: 4 vs 7), for the O2 reason, not a bug. As written F1 fires at
UART and gets diagnosed as the Ethernet break.

**O4 — Part A can only be *executed* for UART.** It says "take the conformance
product already proved in TA-01/b/c, per protocol" — TA-01/01b/01c are UART-only.
SPI, I²C and Ethernet get the *same centre-sampling geometry* applied at their
`T`, which is a model assumption, not a derivation from a proved monitor.
Ethernet is weakest: 10BASE-T is Manchester-coded into a PLL receiver. The
Ethernet **verdict** survives this (it fails for any `D < 3`); the **number**
is a stand-in and is labelled as one in the code.

**O5 — P1's buffer rung is scoped too narrowly.** The spec gives "derive the FIFO
depth" as an escape for *reactive input* lanes (UART-rx, I²C clock-stretch). It is
also the only escape for a *high-rate output* lane. Proposed general trigger:
**`D_i < C_i + B_i` ⇒ a buffer is mandatory, and its width is derived, not
chosen.** Ethernet is the instance; `w = 4`.

**O6 — nothing in the falsifier list catches a zero-margin pass.** SPI at
`r = 12, D = 12` satisfies condition (1), condition (2), and `r_i ≤ D_i`, and is
one cycle from infeasible. Proposed **A2-F6: any lane with `r_i == D_i` is
reported as a named obstacle, not a pass** — it means the next `C_i` revision,
the next lane, or any `B_i` increase breaks the gate with no warning.

**O7 — add the injection sanity check the spec doesn't ask for.** The jitter model
is only right if a *uniform* delay on every edge is invisible (the receiver
re-syncs). If a search returns the same `D` whether the start edge or a data edge
is delayed, the injection is not modelling re-synchronisation and every number is
generous. The `early_j` / `late_j` shape split tests this directly, and it is what
located the binding side.

**O8 — the `+1` in `w_i(q)` is load-bearing and uncited.** It is 1 of UART's 7
cycles. Implemented as written; needs a source before the bound is called proved.

**O9 — the interference sum is not deadline-limited, and the one place that could
matter is SPI.** Proper EDF caps lane `j`'s contribution by how many instances can
carry a deadline ≤ the analysed one. Omitting the cap over-counts, so the numbers
above are an upper bound on an upper bound — safe, but **SPI is at exactly zero
margin**, so if the tightening rescues anything it rescues SPI. Worth doing before
`r_SPI = 12` is treated as final.

---

## Status against the spec's own gate

| deliverable | state |
|---|---|
| `D_i` per lane, sigrok-confirmed, in `(0, T_i)` | ✅ UART derived+searched+foreign; ⚠ other three by geometry (O4) |
| A2a (1) & (2) on the real tables | ✅ 3 lanes green; ❌ Ethernet fails cond(2) at `d=2` |
| A2b recurrence with `B_i` derived | ✅ `B_i` from deadline ordering, not uniform |
| `r_i ≤ D_i` per lane | ✅ 3 lanes; ❌ Ethernet (−8); ⚠ SPI zero margin |
| P1 checked per protocol | ❌ **not done** — reactive lanes untouched |
| Imitator cross-check at `N = 2,3,4` | ❌ **not done** — standing law 1 unsatisfied for Parts B/C |

**Gate: not yet green.** Part A is closed for UART to the spec's own standard.
Parts B and C are computed and the three required protocols pass, but two
deliverables are outstanding (P1, and the Imitator cross-check that makes the
recurrence independent of the hand that coded it). Ethernet is a **named
obstacle with a derived escape**, which is A2-F4 behaving as designed.
