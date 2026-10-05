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
GATES=(
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
    WSLROOT="${ROOT//\\//}"
    case "$WSLROOT" in
      [A-Za-z]:*) _d="${WSLROOT%%:*}"; _rest="${WSLROOT#*:}" ;;
      /?/*)       _d="${WSLROOT:1:1}"; _rest="${WSLROOT:2}"  ;;
      *)          _d="";               _rest="$WSLROOT"      ;;
    esac
    if [ -n "$_d" ]; then
      _d="$(printf '%s' "$_d" | tr 'A-Z' 'a-z')"
      WSLROOT="/mnt/${_d}${_rest}"
    fi
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
