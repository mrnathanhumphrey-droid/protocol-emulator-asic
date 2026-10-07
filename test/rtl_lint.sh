#!/usr/bin/env bash
# RULING RL1 -- Verilator lint on the RTL, for the gate that reads it.
#
# Usage:  bash test/rtl_lint.sh <src-dir> <log>
#   Lints <src-dir>/pe_store.v pe_engine.v project.v with -Wall and writes the
#   full output to <log>. The VERDICT is model/gate_rtl_lint.py's; this script
#   only runs the tool (through the one resolver) and records what it said.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
. "$ROOT/ci/tools.sh"
tool_banner verilator
SRC="${1:?src dir}"
LOG="${2:?log path}"
"$VL" --lint-only -Wall --top-module tt_um_protocol_emulator \
      "$SRC/pe_store.v" "$SRC/pe_engine.v" "$SRC/project.v" > "$LOG" 2>&1
rc=$?
echo "  lint exit $rc -> $LOG"
exit 0
