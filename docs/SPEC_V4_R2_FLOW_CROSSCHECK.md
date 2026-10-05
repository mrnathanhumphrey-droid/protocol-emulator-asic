# R2 — the flow netlist as a second authority on the reset audit

Ruling: *"Spend a little, not a lot. Keep the local audit as it is, and add a
flow-netlist cross-check. It's a second authority, not a replacement."*

Gate: `model/gate_flow_netlist.py`. Run after each harden on the downloaded
artefact, **not** per push — it depends on a ~3.5-hour run. The exclusion is
declared in `ci/run_gates.sh` beside the pyRTA and clean-room exclusions, and
the gate is deliberately **not** conditionally wired into the gate list: a gate
that skips itself when an env var is unset is the shape this project keeps
finding bugs in.

```
$env:PE_FLOW_NETLIST = '<run>\logs\runs\wokwi\06-yosys-synthesis\tt_um_protocol_emulator.nl.v.json'
$env:PE_NETLIST_JSON = 'D:\ProtocolEmulator\probe_nl\ci_netlist.json'
python model/gate_flow_netlist.py
```

## Why the two readings are independent

| | local, per push | flow, per harden |
|---|---|---|
| builder | `test/local_netlist.sh`, `synth -top -flatten` | OpenLane AREA_0 + ABC + PDK techmap |
| yosys | 0.52 (`fee39a32`) | 0.66 (`86f2ddeb`), from the netlist's own `creator` field |
| cells | generic `$_DFFE_*` | `sg13cmos5l_dfrbpq_1` |
| "no reset" is | no `R`/`S` **port** | `RESET_B` **pin** tied to `tiehi` |

Different library, different stage, different test. The two counts agreeing is a
coincidence worth demanding, not one measurement taken twice.

## Result on the `cmos5l` artefact

```
flow netlist: 3127 mapped flops, 2153 tied (unreset), 974 driven
  u_store.mem   2048      tx_mem          64      s_wrdata   24
  s_rdata          8      u_eng.paddr      8      u_eng.fix   1
```

**2153 tied == 2153 unreset locally**, exactly. Every group count matches, and
the groups **partition** the tied set with no residue.

The partition is the load-bearing part. Checking only the four named groups
would let one extra tied flop land anywhere else and still pass — which is
exactly the must-fire. Nine mutants, each required to fail *for its own stated
reason*: an extra tied flop in a new group, inside `tx_mem`, and on no declared
name; a disagreeing local count; `fix[1]` tied as well; the tied bit moved to
`fix[1]`; `u_eng.fix` absent entirely; and no mapped flops at all.

## The alias check, structurally

`fix = {pl, pslot}`, so `fix[0]` **is** `pslot` by the concatenation identity.
Measured: **`pslot` does not survive into the flow netlist as a name at all**, so
a check looking for it would have passed vacuously forever. The gate instead
requires exactly one tied bit under `u_eng.fix`, requires it to be `fix[0]`, and
requires `fix[1..3]` driven.

```
u_eng.fix[0] -> net 2410   TIED (unreset)
u_eng.fix[1] -> net 2074   driven reset
u_eng.fix[2] -> net  237   driven reset
u_eng.fix[3] -> net  239   driven reset
```

## The 979-vs-974 reset-bearing difference

**The "0.66 removed five flops" framing does not survive measurement.** The axis
is confounded — the two netlists differ in *script* as well as version — and
decomposing it at one fixed yosys shows the script carrying the effect:

| | flops | reset-bearing |
|---|---|---|
| local `synth -top -flatten`, yosys **0.52** | 3132 | 979 |
| local + `opt -full; opt_dff -sat`, yosys **0.52** | 3131 | **978** |
| flow OpenLane AREA_0 + ABC + techmap, yosys **0.66** | 3127 | 974 |

Adding only the extra optimisation, at the **same** yosys, moves 1 of the 5. The
other 4 appear during ABC area mapping and PDK techmap — stages the local
generic script never runs. So the supported claim is "a longer script removes
five, at least one of which 0.52 also removes", not "0.66 removed five".

**They are redundant, which is what was actually asked.** Yosys names a
mechanism for every flop it drops, and each is a constant or a never-changing
bit:

```
Setting constant 0-bit at position 7 on $procdff$18731 ($adff)
Setting constant 0-bit at position 7 on $procdff$18796 ($adff)
Setting constant 0-bit at position 2 on $auto$ff.cc:266:slice$21273 ($adff)
Setting constant 0-bit at position 7 on $auto$ff.cc:266:slice$21526 ($adffe)
Removed top 8 bits (of 48) from FF cell ...slice$21958 ($adffe)
Handling D = Q on ...$procdff$19138 ($adff) (removing D path)
Handling D = Q on ...slice$21457 ($adffe) (removing D path)
```

A `D = Q` flop can never leave its reset value, so dropping it *is* a constant
fold. All of them are reset-**bearing**; none is unreset — and a redundant
reset-bearing flop removed was already pinned to its reset value, so it cannot
move a register into the unreset class. **The unreset count, the only number the
allowlist depends on, is 2153 on both sides.**

### Why they are not listed by name

Five instruments were spent on the name axis and it does not survive the stage
difference. Recorded so nobody spends a sixth:

1. `bit -> name` via `setdefault` picks an **arbitrary** alias of the many each
   bit carries, and the two releases order `netnames` differently. It invents
   swaps — `l_order` 5→0 beside `l_sel` 0→5 — and summed to **−8**, not −5.
2. A plain name diff returns 102 local-only against 97 flow-only names, almost
   all `$abc$`/`$auto$` temporaries. Naming churn, not registers.
3. The flow netlist is post-`splitnets`: a bus is per-bit netname **keys**.
4. A memory word is `tx_mem[0][0]` there against `tx_mem[0]` (8 bits) locally —
   two trailing bracket groups against one. Stripping a single group leaves
   `tx_mem[0]` against `tx_mem`, so **every** memory reads as changed.
5. With all of that fixed, declared-name totals still do not reconcile (1202
   local against 944 flow), because after flattening one bit belongs to several
   declared groups.

The gate's normaliser strips **all** trailing bracket groups, which is what
makes the per-group partition above trustworthy.

Local yosys stays at **0.52** per the ruling; the flow's 0.66 is read, never
installed.
