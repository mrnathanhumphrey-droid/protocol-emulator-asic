# Two-simulator cycle-exact comparison, and the seed sweep behind the reset allowlist

Wilson's Phase 2 order, amendment 2 and "go on two-sim cycle-exact".

## The claim

Two independent simulators, given the same RTL and the same stimulus, produce
**byte-identical port traces for every cycle**. Neither is a model of the other,
so an agreement is two engines witnessing each other, and a disagreement is a
real tool-or-design problem rather than a modelling one.

**Result: CYCLE-EXACT. Identical on all 1,501 lines**, iverilog and Verilator
both `sha256 697750201a641a63`, over 1,500 run cycles of the 51-byte census
image.

| arm | result |
| --- | --- |
| Verilator, 3 seeds (`1`, `7`, `12345`) | 3/3 identical, `sha 697750201a64` |
| iverilog vs Verilator, cycle-by-cycle | identical, 1,501 of 1,501 lines |
| X driven onto a port (iverilog) | 0 cycles |
| must-fire `M_PFETCH_NOWAIT` | seeds DISAGREE, 3 distinct traces — the kill |

## Why the bench is ports-only

It has to run against the **gate-level netlist**, which has no internal signal
names: `dut.u_eng.l_armed` does not exist after synthesis. Every other bench
here reaches inside (`tb_smoke` reads `jitter_max`, `tb_edge` reads `l_armed`),
which is right for what they measure and makes them RTL-only. This one trades
that away so one artefact covers RTL, Verilator and GL.

It also needs **no golden model**. The two engines are each other's witness;
bringing `model/golden.py` in would mean growing it into a cycle-accurate second
implementation of the pipeline, which Law 1 says is worth nothing.

## The seed sweep was vacuous, and the must-fire is the only reason I know

`--x-initial unique` **alone is a no-op.** The compile flag emits the
randomisation hooks; the **runtime** reset mode still defaults to all-zeros. So
the first sweep ran three seeds against a model that was zero-initialising every
unreset flop, got three identical traces, and reported `SEEDS AGREE` having
established nothing at all.

It was caught because **the must-fire also reported `SEEDS AGREE`**. The
`M_PFETCH_NOWAIT` arm is a deliberate read-before-write; when a detector and its
own positive control both come back clean, the detector is the thing that is
broken. Measured directly on a 32-bit never-written reg:

| flags | seed 1 | seed 7 | seed 12345 |
| --- | --- | --- | --- |
| `--x-initial unique` only | `00000000` | `00000000` | `00000000` |
| `+verilator+rand+reset+2` added | `fffffffc` | `fffffff0` | `ffff9f8c` |

Both are required. `test/verilator_trace.sh` now **asserts that precondition**
on exactly such a reg before it compares anything, and exits 1 if the seeds do
not produce distinct initial state. `model/gate_reset_audit.py`'s A1 record
named only the compile flag and has been corrected.

### The mutant dies for its stated reason — by seed-dependence, not by X

`M_PFETCH_NOWAIT` deletes the `P_WAIT` state so `P_CAP` samples `s_wrdata` in
the cycle the store is still registering the read. That is verbatim the reason
allowlist entry #2 gives for leaving `s_wrdata` unreset ("captured at `P_CAP`,
which only runs after a real `P_REQ` — so it is write-before-read").

The certification is **not** X on a port: the mutant drives **0 X-bearing
cycles**, because the unknown word makes a lane permanently unready rather than
reaching an output. It is this instead:

- under zero-init the mutant is **deterministic** (one sha across seeds);
- under randomised init its trace is a **function of the seed** (3 distinct
  shas, diverging from cycle ~118, 2,766 and 2,724 lines apart).

A value whose effect depends on the seed came from uninitialised state. That is
read-before-write, which is what the mutant claimed to be.

## Two bench races that only the pair could see

Both were in the bench, and **each simulator alone produced a clean, plausible,
self-consistent trace.**

1. **Sampling race.** `emit` ran in the same timestep as `@(posedge clk)`,
   reading registered outputs mid-update. iverilog's active region runs before
   the NBA region and returned the pre-edge value; the 2-state engine returned
   the post-edge one.
2. **Stimulus race — and the first fix was the wrong half.** Seeing a one-cycle
   offset I moved only the *sampling* off the edge, and the traces stayed one
   cycle apart, because the race was upstream: stimulus was also driven in the
   posedge timestep, so the two DUTs latched different values and one program
   ran a cycle early. The signature was decisive — `vl[n] == iv[n+1]` with
   **exactly 0 residual mismatches** across all 1,500 cycles. A pure shift with
   zero residual is a whole program displaced, not a sampled value.

The bench is now **entirely negedge-driven**: the clock toggles off its own
timer, inputs change half a period before the DUT samples them, outputs are read
half a period after it drove them, and no bench event ever shares a timestep
with the active edge. Negedge rather than `#1` because the same bench must run
at gate level, where clock-to-Q is a real delay a 1 ns probe can land inside.

## Line endings are normalised, and the normalisation is proven

iverilog runs natively on Windows and `$fopen` in write mode translates newlines
to CRLF; Verilator runs under WSL and does not. Stripping CR silently would also
hide a real difference that happened to involve CR, so the claim "the raw files
differ **only** by trailing CR" is checked: every CR must be at end-of-line and
there must be exactly one per line (1,501 CR, 1,501 at EOL, 1,501 lines).

The provenance-header compare originally ran on the **raw** first lines and
failed on two headers that were character-for-character identical — defeated by
the very CR it sits downstream of. It now reads the normalised copies.

## Smaller things that cost real time

- **A comment is not inert.** A comment line whose first word is the tool's name
  is parsed as a lint pragma, case- and whitespace-insensitively, and rejected as
  an unknown one. This explanation broke the build three times as each rewrite
  rewrapped the name onto the start of a line. The build failure is the standing
  guard; no gate is owed.
- **The image length is passed in, not derived.** `tb_smoke` finds it by
  scanning for the first X, since `$readmemh` leaves unwritten entries X. That
  is correct in iverilog and **silently wrong** in Verilator, which initialises
  the array to 0: the derivation returned 256 against iverilog's 51. `+NBYTES`
  is now required and the bench refuses without it. The **provenance header
  caught this** — added against the clobber hazard, it reported `bytes=256` vs
  `bytes=51` before a single trace line was compared.
- **WSL `/tmp` is wiped between `wsl.exe` invocations here.** Any artefact a
  later command must read lives on `/mnt/c`; only the Verilator build tree stays
  in `/tmp`, because its C++ build across the 9p mount is slow.
- **A whole-file grep for `x` counts the header**, which contains
  `smoke_image.hex`. The X census is taken on the body.

## What this does NOT establish

- **Ports only.** Internal state is not compared. A divergence that never
  reaches `uo_out`/`uio_out`/`uio_oe` within the traced window is invisible here.
- **RTL only, so far.** The gate-level arm is the CI `gl_test` replacement and
  is still owed; this bench is built to run there unchanged, but has not.
- **One program, 1,500 cycles.** The census image, not a sweep of programs.
- **`uio_out`/`uio_oe` are constant across this trace**, so the comparison's
  discriminating power came almost entirely from `uo_out` (112 of 1,500 cycles
  changed). A program that exercises the pin drivers harder would test more.
- **2-state vs 4-state.** Verilator cannot represent X, so if iverilog ever
  drives X onto a port the two differ by construction. The X census is reported
  with the comparison for exactly that reason, and is currently 0.

## Reproduce

```bash
# iverilog (native Windows), from the repo root
iverilog -g2012 -o tr.vvp -s tb_trace \
    test/tb_trace.v src/pe_engine.v src/pe_store.v src/project.v
vvp tr.vvp +IMG=test/smoke_image.hex +NBYTES=51 +OUT=/c/tmp/tr_iv.txt +NCYC=1500

# Verilator, 3 seeds, with the randomisation precheck
MSYS_NO_PATHCONV=1 wsl.exe -d Ubuntu -- bash \
  /mnt/d/ProtocolEmulator/test/verilator_trace.sh \
  /mnt/d/ProtocolEmulator 51 1500 /mnt/c/tmp/vtrace_clean

# the must-fire: this one must exit 2 (seeds disagree)
MSYS_NO_PATHCONV=1 wsl.exe -d Ubuntu -- bash \
  /mnt/d/ProtocolEmulator/test/verilator_trace.sh \
  /mnt/d/ProtocolEmulator 51 1500 /mnt/c/tmp/vtrace_mut "+define+M_PFETCH_NOWAIT"

# the cycle-exact compare
MSYS_NO_PATHCONV=1 wsl.exe -d Ubuntu -- bash \
  /mnt/d/ProtocolEmulator/test/two_sim_trace.sh \
  /mnt/c/tmp/tr_iv.txt /mnt/c/tmp/vtrace_clean/s1.txt
```

## Suite state at this commit

`python model/a2/run_a2.py` → **30 of 30**, digest `b4e51034e283`, one lane table.
`bash model/price_gates.sh` → **13 of 13 red**.
`python test/run_mutants.py` → **4 of 4**, 0 survived, 0 died of a wrong reason.
`bash test/yosys_check.sh` → clean, 0 multi-driver, AW=4 static assertion fires.
`python model/gate_reset_audit.py` → PASSED, 2,087 unreset flops, 5 of 5 groups
allowlisted, no width drift.
`tb_smoke` PASS · `tb_edge` PASS (5 of 5 must-fires) · `gate_reverse_trace` 8 of
8 opcodes, 0 behaviours with no field.

The two netlists report **2,901** (`yosys_check.sh`, `synth -flatten`) and
**2,904** (`local_netlist.sh`) flops. The difference is entirely in
**reset-bearing** cell mapping between two different synthesis scripts; the
**unreset** count is **2,087 in both**, which is the number the audit's claim
rests on.
