#!/usr/bin/env bash
# Elaborate test/param_dump.v with Verilator and print the resolved parameters.
# ⭐ A SCRIPT FILE, never `bash -lc` with inline $VAR across the Git-Bash/WSL
# boundary -- that has eaten arguments in this project before.
set -uo pipefail
cd "${1:-/mnt/d/ProtocolEmulator}" || exit 1
rm -rf /tmp/pdobj
# ⛔ THE PINNED VERILATOR via PE_VERILATOR, never a bare `verilator` from PATH:
# CI keeps the pin off PATH and apt's 5.020 on it. `verilator_trace.sh` made
# that mistake and its witness ran against the wrong Verilator in CI.
"${PE_VERILATOR:-verilator}" --binary --timing -Wno-fatal --top-module param_dump -o pd \
    --Mdir /tmp/pdobj +incdir+test \
    test/param_dump.v src/pe_engine.v src/pe_store.v src/project.v \
    > /tmp/pd_build.log 2>&1
RC=$?
if [ "$RC" -ne 0 ] || [ ! -x /tmp/pdobj/pd ]; then
    echo "VERILATOR BUILD FAILED (exit $RC)"
    tail -20 /tmp/pd_build.log
    exit 1
fi
/tmp/pdobj/pd 2>&1 | grep PARAM
