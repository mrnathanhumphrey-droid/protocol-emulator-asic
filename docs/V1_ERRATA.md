# v1 errata

Known defects in v1 (tag `v1-lock` = 04a4fe3), the fallback if v2 does not ship.
Each entry names where it was found, the fix on v2, and how to see it.

## E1 — a refusal's sticky fault bit is swallowed (found 2026-11-19)

**What.** `src/pe_engine.v` carries, late in the one sequential block:

```verilog
for (i = 0; i < N_LANES; i = i + 1)
  if (l_live[i] && ready[i] && busy && (i[LW-1:0] != cur))
    sticky_ovr_m <= sticky_ovr_m;         // observed, not an error here
```

It was meant as "observed, nothing to do". As the LAST nonblocking write of
`sticky_ovr_m` in the block, it overrides every earlier set in the same cycle
whenever another lane is ready while the engine is busy. A refusal (`ck_refuse`:
a degenerate clocked bit count or a hold violation; the clock-alias refusal)
then raises `config_err` but leaves the host's sticky fault bit (uo_out[4]) at 0.

**Effect on v1.** The engine still halts (config_err gates dispatch), so no wrong
waveform is driven; the host sees CONFIG_ERR but not the sticky fault. A host
that keys on the sticky bit alone misses the refusal.

**Seen on.** The five refusal images `ckdegen_image.hex`, `ckdegen2_image.hex`,
`ckhold_at_image.hex`, `ckhold_under_image.hex`, `tx_badclk_image.hex`: v1's
status byte reads 0x6f where v2 (fixed) reads 0x7f.

**v2.** Fixed in 6206743 (the hold removed). `model/gate_v2_equiv.py` declares
exactly this difference on exactly those five images (`STICKY_ERRATUM`), requires
v2 to show the bit set on each, and stays red for any other difference.

**If v1 ships.** Delete the hold (one line); the same five images then report the
sticky bit, matching v2.

## E2 — a clocked write leaves its park set; a false clock-stretch fault ~35 ms later (found 2026-11-23)

**What.** On an open-drain lane with a clock pin, every clocked action parks at
its high phase (`l_ckpark <= 1`) and waits for the peer to release the clock.
`l_ckpark` is cleared in only two places: `ck_hit`, which needs `l_ckwait` — set
only by a clocked `SHIFTIN` — and the stretch watchdog's halt. After a clocked
`SHIFT`, the rise is seen (the lane disarms and runs on), but `l_ckpark` stays 1
until the lane's next clocked `SHIFTIN`. While it is set, the stretch watchdog
keeps counting (one tick per `CK_STRETCH_PRE` = 16,384 cycles).

**Effect on v1.** A lane whose last clocked action is a write, and which runs no
clocked read for `CK_STRETCH_TO` ticks (35 ms), is **halted with the sticky
clock-stretch fault** (status bit 7, `clk_stretch_err`) although every clock rise
came. Data already sent is correct; the lane stops, and the host sees a bus fault
that did not happen. A plain `ARM` on such a lane also rebases to `now + hdly`
instead of `now`.

**Seen on** (simulation of `v1-lock`, scratch bench):

| image | lane | false halt |
|---|---|---|
| `fpga/images/i2c_fram_fpga.hex` (the board image) | 0 — its last write is followed by the final `REARM`, with no clocked read | cycle 1,784,212 = **35.7 ms** after reset, ~35 ms after the transfer completed |
| a write-only I²C controller (START, three clocked writes, STOP, repeating) | 0 | cycle 1,754,901 = **35.1 ms**, while still writing |

By static analysis the same holds for every lane that writes and never reads on
a clock: 12 lanes in `ckdense_image.hex`, `ckod_image.hex`, `ckheavy_image.hex`
and `ckhold_over_image.hex`. Their benches stop well before 35 ms, which is why no
gate saw it. Every other clocked lane of record reads within ~2,200 cycles of
each write and never reaches the limit.

**v2.** The same mechanism (measured on 074e477: the board image at 35.9 ms, the
write-only lane at 35.3 ms). Fixed in 8dbad16 (Wilson 11-23): the park's own
rise clears `l_ckpark`. `test/run_ftflush.py` judges it on every run (PARKEND,
STRETCHFALSE, PARKARM), plants `M_PARK_STUCK`, and runs the witness: a clocked
write, 900 idle cycles past the stretch bound at a shortened prescaler, then a
plain `ARM` — no fault on the fix, the false halt under the mutant.

**If v1 ships.** The same fix is one line at the edge capture. Without it, a
program avoids the fault by ending every clocked-write burst with a clocked read
(an I²C write's ACK slot is one), or the host ignores status bit 7 after a
write-only burst.
