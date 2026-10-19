#!/usr/bin/env bash
# tools.sh -- THE ONE RESOLVER for verilator / iverilog / vvp / yosys in shell.
#
# ⛔⛔ WHY (ruling V). CI keeps the pinned Verilator OFF `PATH` and names it in
# `PE_VERILATOR`; apt's 5.020 is what a bare `verilator` finds there.
# `verilator_trace.sh` called the bare name, the corpus witness ran 5.020 in
# CI, disagreed with the local 5.053 on 666 lines, and two commits went to a
# wrong diagnosis before anyone looked at the version.
# ⇒ Source this and invoke "$VL" / "$IV" / "$VVP" / "$YS", never the bare
#   names. Each reads its `PE_*` variable first and only then PATH, and is
#   made ABSOLUTE, so `tool_banner` can print exactly what ran.
#   `model/gate_tool_pinning.py` refuses a bare invocation anywhere else in
#   `ci/`, `test/` and `model/`. The Python twin is `test/toolchain.py tool()`.
# ⚠ ONLY VERILATOR IS VERSION-PINNED; iverilog and yosys come from the
#   distribution in CI on purpose. For them the guarantee is that the log
#   names the path and version.
#
# ⛔ A SOURCED HELPER, like `ci/rc.sh`: it sets no shell options (that would
# change the caller's shell) and so must contain NO PIPES -- `gate_shell_rc`
# holds both. The version line is read with process substitution instead.
#
# USAGE:  . ci/tools.sh
#         tool_banner verilator            # prints `tool verilator: <path>  <version>`
#         "$VL" --cc ...

_pe_resolve() {   # $1 = value of the PE_* variable (may be empty), $2 = name
  local v="$1" p
  if [ -n "$v" ]; then
    p="$(command -v "$v" 2>/dev/null)"
    [ -n "$p" ] || p="$v"
  else
    p="$(command -v "$2" 2>/dev/null)"
    [ -n "$p" ] || p="$2"
  fi
  printf '%s' "$p"
}

VL="$(_pe_resolve "${PE_VERILATOR:-}" verilator)"
IV="$(_pe_resolve "${PE_IVERILOG:-}" iverilog)"
YS="$(_pe_resolve "${PE_YOSYS:-}" yosys)"
# ⭐ vvp from the SAME install as iverilog unless named, so the compiler and
# its runtime cannot come from two different releases.
if [ -n "${PE_VVP:-}" ]; then
  VVP="$(_pe_resolve "$PE_VVP" vvp)"
elif [ -x "$(dirname "$IV")/vvp" ]; then
  VVP="$(dirname "$IV")/vvp"
else
  VVP="$(_pe_resolve "" vvp)"
fi

# ⛔⛔ sim_exec -- THE SHELL SIDE OF test/sim_run.py (Wilson 10-19). Every
# simulation RUN in shell (vvp, a Verilator-built binary) is written as
#     sim_exec "<image> <image> ..." <run command...>
# The image list is REQUIRED ("" = loads no program image). It runs the ONE
# lookup (`python test/sim_run.py check ...`), which refuses a clocked image
# with no A2 bound, naming it, and only then runs the command -- with the
# image's +A2SLACK appended when it has a bound and the command carries none.
# `model/gate_sim_runs.py` is red on a run not written this way.
_PE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# this run's provenance token (test/sim_run.py run_token): set once, exported,
# so a generator this script starts and the check before its run agree
export SIM_RUN_TOKEN="${SIM_RUN_TOKEN:-sh$$-$RANDOM$RANDOM}"
sim_exec() {
  local imgs="$1" py="${PE_PYTHON:-python3}" a2 x has=0
  shift
  command -v "$py" >/dev/null 2>&1 || py=python
  # shellcheck disable=SC2086
  a2="$("$py" "$_PE_ROOT/test/sim_run.py" check $imgs)" || return 97
  # queue 3b: a bound that exists is ENFORCED -- append the run's +A2SLACK
  # unless the command already carries one (a2_run.sh's light arm, the sweep)
  for x in "$@"; do
    case "$x" in +A2SLACK=*) has=1 ;; esac
  done
  if [ -n "$a2" ] && [ "$has" = 0 ]; then
    "$@" "$a2"
  else
    "$@"
  fi
}

tool_banner() {   # tool_banner verilator iverilog vvp yosys ...
  local t p f v
  for t in "$@"; do
    case "$t" in
      verilator) p="$VL";  f="--version" ;;
      iverilog)  p="$IV";  f="-V" ;;
      vvp)       p="$VVP"; f="-V" ;;
      yosys)     p="$YS";  f="-V" ;;
      *)         printf '  tool %-9s: UNKNOWN TOOL NAME\n' "$t"; continue ;;
    esac
    v="MISSING"
    if command -v "$p" >/dev/null 2>&1; then
      IFS= read -r v < <("$p" "$f" 2>&1)
    fi
    printf '  tool %-9s: %s  %s\n' "$t" "$p" "$v"
  done
}
