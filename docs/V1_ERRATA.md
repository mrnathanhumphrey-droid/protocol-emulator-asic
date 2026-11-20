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
