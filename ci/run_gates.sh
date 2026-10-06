#!/usr/bin/env bash
# THE MODEL GATES -- ONE ENTRY POINT, run by CI and by hand (Wilson's ruling 2).
#
# ⛔⛔ WHY THIS FILE EXISTS, FROM A REAL FAILURE. The ruling-0 commit was pushed
# after a local run reported "all 8 CI gates green", and CI went RED on
# `gate_stored_numbers` -- an unclassified collection (`test/test.py ::
# HOST_PAT`). Reproduced afterwards in a clean worktree at that commit: the gate
# fails there too. So it was never an environment difference. I ran the gate
# loop, then KEPT EDITING, and reported the earlier run's result for a tree that
# no longer existed.
# ⇒ Two things follow, and this script is both:
#     1. ONE list of gates, in one place, that CI executes and nothing else.
#        A loop pasted into a workflow and a loop typed at a prompt are two
#        lists, and two lists drift.
#     2. A DIRTY-TREE WARNING. A green on a tree you are not committing is not
#        a green on what you push. The script says so, by name, every run.
#
# ⚠ THE TOOLCHAIN IS SPLIT ON THE DEV BOX AND THAT IS HANDLED HERE, not by a
# second procedure. `yosys` lives only inside WSL on this machine while
# `iverilog` lives only natively, so the netlist step DELEGATES to WSL when
# yosys is not on PATH. In CI all three tools are native and no delegation
# happens. Either way the GATE LIST below is the same list, which is the part
# that drifted.
#
# Usage:
#   bash ci/run_gates.sh              # generate the netlist, run every gate
#   PE_NETLIST_JSON=/path bash ci/run_gates.sh   # reuse a netlist
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1

PY="${PE_PYTHON:-python}"
command -v "$PY" >/dev/null 2>&1 || PY=python3

# ---------------------------------------------------------------------------
# THE GATE LIST. One place. Add a gate here and CI runs it.
# ---------------------------------------------------------------------------
# ⛔ NOT INCLUDED, and each exclusion is declared rather than implied:
#   * the clean room, the parameter-point sweep and run_spl_compare -- minutes
#     of simulation each, and the clean room moves files about. By-hand at each
#     `cmos5l` checkpoint.
#   * every pyRTA-PRIMARY gate (gate_pyrta, gate_j_sound, gate_c3_requote,
#     gate_j9_margins, ...). pyRTA is NOT VENDORED -- it is reached through
#     PYRTA_SRC -- and those gates are RED by design without it rather than
#     falling back to our own recurrence. `model/a2/run_a2.py` is their
#     harness, by hand at each checkpoint.
#   * `model/gate_flow_netlist.py` -- the R2 FLOW CROSS-CHECK. It reads the
#     HARDENING FLOW's post-synthesis netlist, which costs a ~3.5-hour run, so
#     it cannot be a per-push gate. It runs after each harden, on the
#     downloaded artefact, and its result is recorded with that harden's
#     per-job report:
#       $env:PE_FLOW_NETLIST = '<run>\logs\runs\wokwi\06-yosys-synthesis\tt_um_protocol_emulator.nl.v.json'
#       $env:PE_NETLIST_JSON = 'D:\ProtocolEmulator\probe_nl\ci_netlist.json'
#       python model/gate_flow_netlist.py
#     ⛔ IT IS A SECOND AUTHORITY, NOT A REPLACEMENT: `gate_reset_audit` above
#     still gates every push on the netlist built in seconds. ⛔ AND IT IS NOT
#     CONDITIONALLY WIRED INTO THIS LIST -- a gate that skips itself when an
#     env var is unset is the exact shape this project keeps finding bugs in,
#     so the exclusion is declared here and the invocation is explicit.
GATES=(
  # ⛔ THE BENCH LINT, and it earned its place twice over in one file. The
  # watchdog `test/progress.vh` was VACUOUS on all twelve benches on its first
  # run -- a hierarchical reference to a `localparam` compiled and never
  # matched -- and then its failure messages printed NOTHING because their
  # format strings were brace-concatenated, while the counter beside them
  # reached 144. Both shapes are "a check that cannot speak", which reads
  # exactly like a check that passed.
  model/gate_bench_lint.py
  model/gate_ruling_audit.py
  model/gate_one_encoder.py
  model/gate_mutant_arms.py
  model/gate_reset_audit.py
  model/gate_stored_numbers.py
  model/gate_bench_indices.py
  model/gate_j_proof_anchors.py
  model/a2/gate_j_program.py
  # ⭐ JOINED THE LIST when it took the RX lane-field width check. That check
  # guards against a received byte being attributed to the WRONG LANE if
  # `N_LANES` ever outgrows the explicit [2:0] on `e_rx_lane` -- and it lives
  # here rather than in the RTL because a generate-guarded zero-width net was
  # tried as a compile-time assertion and iverilog accepted it SILENTLY.
  # ⛔⛔ THE SAME DEFECT THREE TIMES is why this gate exists: an array
  # indexed by a PROGRAM-CONTROLLED pin field can be driven out of range,
  # and it shipped as the `pin_out[12]` WRITE, then as the `pin_in[a_pin]`
  # RX SAMPLE, then as the `pin_rise[l_armpin]` EDGE SELECT -- each found
  # and fixed separately. It enumerates the family and holds every member
  # to a declared guard, keyed on (file, array, index) so nothing has to be
  # re-anchored when lines move.
  model/gate_program_index.py
  model/part1_param_contract.py
  # ⛔⛔ THE HARNESS MUST BUILD AT GATE LEVEL, and this is in the list because
  # a checkpoint harden died proving otherwise: `gl_test` failed in 55 seconds
  # on a parameter override in `tb.v` after `gds` had spent 3h50m and
  # `precheck` 2h11m succeeding. Gate-level elaboration happens ONLY inside
  # the harden, so the RTL `test` job and the parameter sweep could both be
  # green while the gate-level harness was unbuildable. This answers the same
  # question in under a second.
  test/gl_harness_check.py
  # ⛔ RULING 1b. Every end-to-end payload pattern must contain a byte whose
  # bit reversal differs from itself. Three benches fed {5A, C3, 3C, A5} --
  # FOUR PALINDROMES OUT OF FOUR -- so every "the byte reached the wire"
  # result was true and said nothing about bit ORDER, which is how the
  # engine's LSB-first wire order survived an entire host-channel audit while
  # `pe_isa.py` documented the opposite.
  test/check_vectors.py
  # ⛔⛔ WILSON'S COVERAGE RULING, GATED. "Every uncovered branch, FSM state,
  # opcode arm and peer branch gets either a test that reaches it, or a
  # written reason why it's unreachable, checked like the reset allowlist. It
  # becomes a gate: new uncovered RTL fails CI unless justified."
  # ⭐ WHAT IT FOUND ON ITS FIRST RUN: `fram_spi.v`'s ENTIRE command decoder
  # had never executed (18 points), no byte had ever been written into the I2C
  # peer's memory, and `lane_underrun` and `tx_full_sticky` -- two status bits
  # the host reads -- had never been SET by any test, only asserted clear.
  # ⚠ The bench set it measures is `test/benchset.py`, which enumerates
  # `test/tb*.v` from disk and fails on a bench nobody classified.
  test/benchset.py
  test/gate_coverage.py
  model/pe_asm.py
)

# What each gate actually needs, so a missing prerequisite is NAMED rather than
# showing up as that gate's own failure.
# ⛔ `gate_reset_audit` NEEDS THE NETLIST, NOT `yosys` ON PATH, and the first
# version of this said yosys. On this box yosys lives only inside WSL, so the
# netlist is built by delegation and the gate -- which is pure Python once it
# has the JSON -- was declared unrunnable while its input sat ready on disk.
# A precondition stated as the wrong thing fails in the safe direction here
# (it refused to claim green) but it would have made the audit permanently
# unrunnable locally, which is how a gate quietly stops being run at all.
can_run() {
  case "$1" in
    model/gate_one_encoder.py|test/gl_harness_check.py)
      command -v iverilog >/dev/null 2>&1 || { echo "iverilog is not on PATH"; return 1; } ;;
    model/gate_reset_audit.py)
      [ -n "${PE_NETLIST_JSON:-}" ] && [ -f "${PE_NETLIST_JSON:-}" ] \
        || { echo "no netlist at PE_NETLIST_JSON"; return 1; } ;;
    # ⛔ THE COVERAGE GATE NEEDS THE MEASUREMENT, and a missing measurement is
    # a FAILURE here rather than a skip -- the same rule the reset audit's
    # netlist precondition follows, and for the same reason: a gate that
    # quietly stops running is a gate that stops covering anything.
    test/gate_coverage.py)
      [ -n "${PE_COVERAGE_DAT:-}" ] && [ -f "${PE_COVERAGE_DAT:-}" ] \
        || { echo "no coverage data at PE_COVERAGE_DAT"; return 1; } ;;
  esac
  return 0
}

echo "=============================================================================="
echo "  MODEL GATES -- ci/run_gates.sh  (the one entry point)"
echo "=============================================================================="
echo "  root   : $ROOT"
echo "  python : $("$PY" -c 'import sys;print(sys.version.split()[0])' 2>/dev/null)"
for t in iverilog verilator yosys; do
  printf "  %-7s: %s\n" "$t" "$(command -v "$t" 2>/dev/null || echo 'not on PATH')"
done

# ---------------------------------------------------------------------------
# ⛔⛔ THE DIRTY-TREE WARNING -- the specific lesson of the red commit.
# ---------------------------------------------------------------------------
echo
if command -v git >/dev/null 2>&1 && git rev-parse --git-dir >/dev/null 2>&1; then
  DIRTY="$(git status --porcelain --untracked-files=no 2>/dev/null)"
  if [ -n "$DIRTY" ]; then
    echo "  ⚠⚠ THE WORKING TREE HAS UNCOMMITTED CHANGES TO TRACKED FILES:"
    echo "$DIRTY" | sed 's/^/       /'
    echo "     A green below is a green on THIS tree. If you edit anything"
    echo "     after this run, the result no longer describes what you push --"
    echo "     which is exactly how a 'all gates green' report preceded a red"
    echo "     CI run once already. Re-run this script as the LAST thing before"
    echo "     reporting."
  else
    echo "  tree: clean -- a green below describes HEAD as it will be pushed"
  fi
else
  echo "  tree: not a git checkout, so no dirty-tree check"
fi

# ---------------------------------------------------------------------------
# ⛔⛔ THE GIT-BASH -> WSL PATH CONVERSION, IN ONE PLACE. Two steps delegate to
# WSL now (the netlist and the coverage sweep), and this conversion has already
# cost two failures: a rule that only matched `X:` converted nothing, because
# Git Bash reports this repo as `/d/ProtocolEmulator`; and a `sed 's|\\|/|g'`
# fix had its backslashes eaten before sed saw them. Parameter expansion has no
# such layer, and ONE copy cannot drift from the other.
# ---------------------------------------------------------------------------
wsl_root() {
  local p="${1//\\//}" d rest
  case "$p" in
    [A-Za-z]:*) d="${p%%:*}"; rest="${p#*:}" ;;
    /?/*)       d="${p:1:1}"; rest="${p:2}"  ;;
    *)          d="";         rest="$p"      ;;
  esac
  if [ -n "$d" ]; then
    d="$(printf '%s' "$d" | tr 'A-Z' 'a-z')"
    printf '/mnt/%s%s' "$d" "$rest"
  else
    printf '%s' "$rest"
  fi
}

# ---------------------------------------------------------------------------
# the netlist the reset audit classifies flops from
# ---------------------------------------------------------------------------
# ⭐ VIA THE SAME SCRIPT THE LOCAL FLOW USES (`test/local_netlist.sh`), whose
# output directory is an argument for exactly this reason.
NL_DIR="${PE_NETLIST_DIR:-/tmp}"
if [ -z "${PE_NETLIST_JSON:-}" ]; then
  echo
  echo "  --- netlist for the reset audit ---"
  if command -v yosys >/dev/null 2>&1; then
    bash test/local_netlist.sh "$ROOT" "" ci_netlist "$NL_DIR" || {
      echo "  *** yosys could not build the netlist"; exit 1; }
    export PE_NETLIST_JSON="$NL_DIR/ci_netlist.json"
  elif command -v wsl.exe >/dev/null 2>&1; then
    # ⛔ DELEGATED, AND THE RULES FOR IT ARE THE PROJECT'S: always a SCRIPT
    # FILE (never inline `bash -c`) and always MSYS_NO_PATHCONV=1, because
    # Git Bash rewrites anything that looks like a path in the argv.
    # ⚠ WSL CANNOT SEE GIT BASH'S /tmp, so the wrapper and the output both
    # live where both sides can reach them.
    echo "  yosys is not on PATH; delegating the netlist step to WSL"
    WRAP="$ROOT/probe_ci_netlist.sh"
    {
      echo '#!/bin/bash'
      echo 'cd "$(dirname "$0")" || exit 1'
      echo 'bash test/local_netlist.sh "$PWD" "" ci_netlist "$PWD/probe_nl"'
    } > "$WRAP"
    mkdir -p "$ROOT/probe_nl"
    # ⛔ TWO SPELLINGS TO HANDLE, AND BASH EXPANSION RATHER THAN `sed`.
    # Git Bash reports this repo as `/d/ProtocolEmulator`, not `D:\...`, so a
    # rule that only matched `X:` converted nothing and WSL was handed a path
    # that does not exist there. The second attempt used `sed 's|\\|/|g'`,
    # whose backslashes are eaten before sed sees them -- the same quoting
    # hazard this project has a standing rule about. Parameter expansion has
    # no such layer.
    WSLROOT="$(wsl_root "$ROOT")"
    # ⭐ AND IT IS CHECKED FROM WSL'S OWN VIEW before being used. The first
    # failure was "No such file or directory" from inside WSL, which is a
    # clearer message than anything downstream would have produced -- but only
    # because the wrapper happened to be the first thing touched.
    if ! MSYS_NO_PATHCONV=1 wsl.exe -e test -f "$WSLROOT/probe_ci_netlist.sh"
    then
      echo "  *** WSL cannot see $WSLROOT/probe_ci_netlist.sh"
      echo "      (converted from $ROOT). Fix the path mapping rather than"
      echo "      skipping the reset audit."
      exit 1
    fi
    MSYS_NO_PATHCONV=1 wsl.exe -e bash "$WSLROOT/probe_ci_netlist.sh" || {
      echo "  *** the WSL netlist step failed"; exit 1; }
    export PE_NETLIST_JSON="$ROOT/probe_nl/ci_netlist.json"
  else
    echo "  *** neither yosys nor wsl.exe is available, so the reset audit"
    echo "      cannot see the design. It is RED rather than skipped."
  fi
fi
[ -n "${PE_NETLIST_JSON:-}" ] && echo "  PE_NETLIST_JSON=$PE_NETLIST_JSON"

# ---------------------------------------------------------------------------
# THE COVERAGE SWEEP, whose data `test/gate_coverage.py` adjudicates.
# ---------------------------------------------------------------------------
# ⛔⛔ WILSON'S RULING PUT THIS IN CI: "It becomes a gate: new uncovered RTL
# fails CI unless justified." So the measurement is produced here rather than
# by hand, and the gate is RED without it -- a coverage gate that passes when
# the measurement is missing is a guard that passes because of what it guards.
#
# ⚠ IT COSTS MINUTES, AND THAT IS DECLARED. Eleven Verilator builds at ~19s
# plus nineteen simulated arms is roughly five minutes, against seconds for
# every other gate here. `PE_COVERAGE_DAT=<path>` reuses an existing
# measurement, and `PE_SKIP_COVERAGE=1` leaves the gate RED rather than
# pretending. ⛔ The reuse path is for iterating on the WAIVER TABLE, not for
# reporting a green: data from an older tree describes that tree, which is the
# dirty-tree lesson above in another form.
if [ -z "${PE_COVERAGE_DAT:-}" ] && [ "${PE_SKIP_COVERAGE:-0}" != "1" ]; then
  echo
  echo "  --- coverage sweep for the coverage gate ---"
  # ⛔⛔ THE EXPORT IS GUARDED ON THE SWEEP'S EXIT CODE, NOT ON THE FILE
  # EXISTING, and this cost a false green. The first delegated run failed all
  # nineteen arms; `merged.dat` from an EARLIER successful run was still on
  # disk; this block exported it and `gate_coverage` passed on data describing
  # a tree that no longer existed. Nothing in the output said the data was
  # stale. ⇒ The sweep now destroys the old measurement before starting, AND
  # the path is only exported when the sweep actually succeeded. Either guard
  # alone leaves the hole open.
  SWEEP_OK=0
  if command -v verilator >/dev/null 2>&1; then
    if bash test/coverage_sweep.sh "$ROOT/probe_cov"; then
      SWEEP_OK=1
    else
      echo "  *** the coverage sweep failed -- the gate will be RED"
    fi
    [ "$SWEEP_OK" = "1" ] && [ -f "$ROOT/probe_cov/merged.dat" ] \
      && export PE_COVERAGE_DAT="$ROOT/probe_cov/merged.dat"
  elif command -v wsl.exe >/dev/null 2>&1; then
    echo "  verilator is not on PATH; delegating the sweep to WSL"
    CWRAP="$ROOT/probe_ci_coverage.sh"
    {
      echo '#!/bin/bash'
      echo 'cd "$(dirname "$0")" || exit 1'
      # ⛔⛔ THE SWEEP GETS THE SAME PINNED VERILATOR AS THE COCOTB ARM. Without
      # this they split inside ONE gate run -- the sweep on the distro's 5.032
      # and the arm on the pinned 5.053 -- and the coverage gate then failed on
      # a classified point that only the newer release emits. One toolchain, or
      # the two halves of the same gate disagree about what exists.
      echo "export PE_VERILATOR=\"${PE_VERILATOR_WSL:-/opt/oss-cad-suite-2026-09-30/bin/verilator}\""
      echo 'bash test/coverage_sweep.sh "$PWD/probe_cov"'
    } > "$CWRAP"
    CWSLROOT="$(wsl_root "$ROOT")"
    if ! MSYS_NO_PATHCONV=1 wsl.exe -e test -f "$CWSLROOT/probe_ci_coverage.sh"
    then
      echo "  *** WSL cannot see $CWSLROOT/probe_ci_coverage.sh"
      echo "      (converted from $ROOT). Fix the path mapping rather than"
      echo "      skipping the coverage gate."
    else
      if MSYS_NO_PATHCONV=1 wsl.exe -e bash "$CWSLROOT/probe_ci_coverage.sh"
      then
        SWEEP_OK=1
      else
        echo "  *** the WSL coverage sweep failed -- the gate will be RED"
      fi
      [ "$SWEEP_OK" = "1" ] && [ -f "$ROOT/probe_cov/merged.dat" ] \
        && export PE_COVERAGE_DAT="$ROOT/probe_cov/merged.dat"
    fi
  else
    echo "  *** neither verilator nor wsl.exe is available, so no coverage"
    echo "      can be measured. The gate is RED rather than skipped."
  fi
fi
[ -n "${PE_COVERAGE_DAT:-}" ] && echo "  PE_COVERAGE_DAT=$PE_COVERAGE_DAT"

# ---------------------------------------------------------------------------
# THE COCOTB COVERAGE ARM (ruling 2) -- the one bench the sweep excludes.
# ---------------------------------------------------------------------------
# ⛔⛔ IT RUNS AFTER THE SWEEP, NOT BEFORE. The sweep clears `cov_*.dat` at
# startup, which deleted this arm's output once and made the gate report "no
# cocotb coverage" after a run that had produced it.
# ⚠ A MISSING ARM IS REPORTED, NOT FAILED. It needs Verilator >= 5.036 (cocotb
# 2.0.1's floor) and Python <= 3.13; `gate_coverage` then names what it did NOT
# check rather than reading as "no false gaps".
if [ -z "${PE_COCOTB_DAT:-}" ] && [ "${PE_SKIP_COVERAGE:-0}" != "1" ]; then
  echo
  echo "  --- cocotb coverage arm (ruling 2) ---"
  CC_OK=0
  if command -v verilator >/dev/null 2>&1 || [ -n "${PE_VERILATOR:-}" ]; then
    if bash test/coverage_cocotb.sh "$ROOT/probe_cov"; then CC_OK=1; fi
  elif command -v wsl.exe >/dev/null 2>&1; then
    CCWRAP="$ROOT/probe_ci_cocotb.sh"
    {
      echo '#!/bin/bash'
      echo 'cd "$(dirname "$0")" || exit 1'
      echo "export PE_VERILATOR=\"${PE_VERILATOR_WSL:-/opt/oss-cad-suite-2026-09-30/bin/verilator}\""
      echo 'bash test/coverage_cocotb.sh "$PWD/probe_cov"'
    } > "$CCWRAP"
    CCROOT="$(wsl_root "$ROOT")"
    if MSYS_NO_PATHCONV=1 wsl.exe -e bash "$CCROOT/probe_ci_cocotb.sh"; then
      CC_OK=1
    fi
  fi
  if [ "$CC_OK" = "1" ] && [ -f "$ROOT/probe_cov/cocotb_coverage.dat" ]; then
    export PE_COCOTB_DAT="$ROOT/probe_cov/cocotb_coverage.dat"
  else
    echo "  ⚠ the cocotb arm did not produce data; the false-gap check will"
    echo "    report itself as NOT PERFORMED."
  fi
fi
[ -n "${PE_COCOTB_DAT:-}" ] && echo "  PE_COCOTB_DAT=$PE_COCOTB_DAT"

# ---------------------------------------------------------------------------
# run them
# ---------------------------------------------------------------------------
echo
FAILED=()
MISSING=()
for g in "${GATES[@]}"; do
  # ⛔ A MISSING PREREQUISITE IS A FAILURE, NOT A SKIP, and it is named as
  # itself. "An audit that cannot see the design has not audited it" -- and a
  # run that quietly covered 8 of 9 gates is how a partial result gets
  # reported as a whole one.
  if ! why="$(can_run "$g")"; then
    echo "=== $g : *** CANNOT RUN -- $why ==="
    MISSING+=("$g ($why)")
    continue
  fi
  echo "=== $g ==="
  "$PY" "$g"
  rc=$?
  if [ $rc -ne 0 ]; then
    FAILED+=("$g (exit $rc)")
  fi
done

echo
echo "=============================================================================="
echo "  GATES: $(( ${#GATES[@]} - ${#FAILED[@]} - ${#MISSING[@]} )) of ${#GATES[@]} passed"
if [ ${#FAILED[@]} -gt 0 ]; then
  echo "  FAILED:"
  for f in "${FAILED[@]}"; do echo "    $f"; done
fi
if [ ${#MISSING[@]} -gt 0 ]; then
  echo "  COULD NOT RUN (a missing tool is NOT a pass):"
  for m in "${MISSING[@]}"; do echo "    $m"; done
fi
if [ ${#FAILED[@]} -eq 0 ] && [ ${#MISSING[@]} -eq 0 ]; then
  echo "  ⇒ every gate in the list ran and passed. This is the SAME list CI"
  echo "    runs, so a green here is a green there -- provided the tree was"
  echo "    clean above."
  exit 0
fi
exit 1
