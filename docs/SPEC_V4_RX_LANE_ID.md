# RX lane identity — the mirror of the TX tag, closed

**Ruling (Wilson):** already ruled, and the next item. True full duplex is
deferred (no encoding bit free, and the serialiser reach gives it for free
anyway). After this: sigrok-certified decode of a real I²C frame with START,
address, ACK and STOP.

**Result: the host can attribute every received byte.** The bench decodes the
real serial stream and sees `L0=10, L1=40` payload frames, correctly separated,
with lane 1's bytes matching exactly what was presented on the pin.

---

## 1. The frame went 9 bits → 12

```
         was:  { marker, data[7:0] }                     9 bits
         now:  { marker, kind[2:0], data[7:0] }         12 bits

  marker 1            -> STATUS           (kind = KIND_NONE = 7)
  marker 0, kind 0..4 -> RX PAYLOAD from THAT LANE
  marker 0, kind 7    -> READBACK byte, not a lane
```

⛔ **Both frame types had to widen together.** The marker shifts out **last**,
so the host cannot know a frame's width until it has already read most of it —
variable-length frames would be undecodable.

⭐ **It resolved a second, pre-existing ambiguity.** A readback byte and an RX
payload byte **both** carried `marker = 0`, so the two were already
indistinguishable on the wire and were being told apart by which mode the host
believed it was in. `kind = 7` now says "not a lane" explicitly.

**The lane travels with the byte.** `rx_lane` is registered in the engine
alongside `rx_data`, and `project.v` captures it into `rx_pend_lane` at the
push. ⛔ It is **not** derived from `cur` downstream: `rx_push` is a pulse that
goes high the cycle *after* the writeback that completes the byte, and `cur` is
free to change before anyone reads it. A consumer sampling `cur` at the pulse
would be right most of the time — the worst kind of wrong.

**Cost: +9 flops** (3118 → 3127): 3 for `rx_lane`, 3 for `rx_pend_lane`, 3 for
the wider `ser_sh`. All reset; the unreset count is unchanged at 2153.

---

## 2. The must-fire reads the wire, not the internals

`tb_half` now decodes the 3-pin serial stream exactly as a host would — framed
on the `valid` edge, not a fixed stride — and asserts:

| | |
|---|---|
| frames decoded | 100 (50 status) |
| payload frames per lane | **L0=10, L1=40**, L2–L4 = 0 |
| frames with an unknown `kind` | 0 |
| lane 1's bytes, as the host sees them | `3c 87 f0 1e` |
| lane 1's bytes the bench presented | `3c 87 f0 1e` |

⛔ **The claim is about the host**, so it is read off the wire. `rx_push` and
`cur` are internal; the question the field exists to answer is "can the *host*
attribute a received byte", and the only honest place to ask it is the stream.

**`M_RX_NO_LANE`** pins the field to 0 — what shipped in effect. The host then
sees `L0=50, L1=0` where the truth is `L0=10, L1=40`, and the bench fails on
"no frame was attributed to lane 1".

⭐ The mutant **keeps the frame width** and only pins the field, so the bench
still decodes and the kill is an *attribution* failure rather than a framing
one. A mutant that broke the framing would have died of the wrong assertion.

---

## 3. ⛔ A compile-time assertion that could not fail

The lane field is 3 bits in two places that cannot see `LW`: `e_rx_lane` is
declared `[2:0]` because `LW` is a localparam defined further down
`project.v`, and `kind` is 3 bits in the frame. If `N_LANES` outgrew 8, `LW`
would become 4 and that explicit 3 would **silently truncate** the lane id — a
byte attributed to the wrong lane, which is the exact failure the field exists
to prevent.

I first wrote that as a generate-guarded zero-width net:

```verilog
generate if (LW != 3) begin : g_rx_lane_width
  wire _rx_lane_width_must_be_3[-1:0];
end endgenerate
```

**iverilog accepted `wire x[-1:0]` silently.** It was decoration — which is
worse than nothing, because it reads as a guard.

⭐ **Caught by pricing it:** inverting the condition to `LW == 3` left the build
green, so the "assertion" had never been able to fail. The real check now lives
in `model/part1_param_contract.py` (and in CI), with four must-fire cases — the
shipped shape, a lane count that overflows the declared width, one that
overflows the frame's `kind` field but *not* the width, and one that overflows
neither after widening. ⚠ Those last two matter because the two limits are
different numbers that merely coincide today.

⚠ One intermediate slip worth recording: the check's first regex looked for
`localparam integer N_LANES` and `N_LANES` is a module **parameter**, so it
read `None`. It failed in the safe direction — it refuses to pass on a value it
could not find — but a regex that cannot find its target is indistinguishable
from a violation unless it says which, so it now says which.

---

## 4. Verified

`tb_half` **5/5** at both SPL points · mutants **8/8**, 0 survivors, 0 wrong
reasons · cocotb 8/8 through the widened decoder · corpus trace 7/8, 0 failed —
the readback stream still agrees cycle-exactly across three seeds and two
simulators at 12 bits · parameter sweep 6 benches × 2 points · clean room 4/4 ·
A2 31/31 · `ci/run_gates.sh` **10/10** · reset audit green on a fresh netlist.

---

## 5. Next, and what is deferred

**Next: a sigrok-certified I²C frame** — START, address, ACK, STOP. Today's
must-fires prove the *plumbing*: a pushed byte reaches the wire, a sampled byte
reaches the host attributed to its lane, and neither direction corrupts the
other. They do not prove a frame a foreign decoder would accept.
`model/ta01/gate0_external.py` holds the invocation pattern (`binary` input,
`uart` PD, `SIGROK_CLI` so "tool absent ⇒ gate red" is testable), so an `i2c`
PD over a two-channel SCL/SDA dump is a known shape of work. The program needs
real framing, which §3 of the previous round showed is expressible — SHIFT for
data + clock-low, `OP_LEVEL` on the clock pin for clock-high, two actions per
bit.

**Deferred, per ruling:** a combined shift-exchange action for true
simultaneous full duplex. There is no encoding bit free — `ACT_W` is exactly 24
of 24 — and the per-lane serialiser reach would provide it without one.
