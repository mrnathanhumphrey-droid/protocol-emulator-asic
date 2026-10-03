#!/usr/bin/env bash
# LOCAL SYNTHESIS CHECK -- elaboration, multi-driver, and flop count.
#
# ⛔⛔ WHY THIS EXISTS. The engine shipped once with 9 nets driven from two
# always blocks. iverilog ACCEPTED IT SILENTLY -- multiple procedural drivers
# are last-write-wins in simulation and a hard error in synthesis -- so the
# smoke bench passed, with correct edge counts and a correct measured C, on a
# design that could not be built. CI caught it 36 minutes later, by dying in 3.
# ⇒ A SIMULATION BENCH CANNOT SEE MULTI-DRIVER. Only a synthesiser can, so one
# runs locally before pushing.
#
# ⭐ IT ALSO READS WITHOUT `-sv`. The double buffer introduced Verilog
# FUNCTIONS and flat arrays with index arithmetic; a 2-D unpacked array would
# have been legal Verilog-2001 and accepted by iverilog while risking the
# non-SystemVerilog reader. Reading in plain mode here is what makes that a
# checked property rather than a hope.
#
# Usage, from the repo root:
#   MSYS_NO_PATHCONV=1 wsl.exe -d Ubuntu -- bash /mnt/d/ProtocolEmulator/test/yosys_check.sh
# ⛔ A SCRIPT FILE, never `bash -lc` with inline $VAR across the Git-Bash/WSL
# boundary -- that has eaten arguments in this project before.
set -uo pipefail

ROOT="${1:-/mnt/d/ProtocolEmulator}"
cd "$ROOT" || exit 1

cat > /tmp/pe_check.ys <<'YS'
read_verilog src/pe_store.v
read_verilog src/pe_engine.v
read_verilog src/project.v
hierarchy -top tt_um_protocol_emulator
proc
opt
check -assert
synth -top tt_um_protocol_emulator -flatten
tee -o /tmp/pe_stat.txt stat
YS

yosys -s /tmp/pe_check.ys > /tmp/pe_full.log 2>&1
RC=$?

echo "=============================================================="
echo "LOCAL SYNTHESIS CHECK"
echo "=============================================================="
echo "  yosys exit                 : $RC"
MD=$(grep -ciE 'multiple.*driver|conflicting driver' /tmp/pe_full.log)
ER=$(grep -cE '^ERROR' /tmp/pe_full.log)
echo "  multi-driver mentions      : $MD  (must be 0)"
echo "  ERROR lines                : $ER  (must be 0)"
echo
echo "  flop cells (1 bit each):"
grep -E '\$_[AS]?DFFE?_' /tmp/pe_stat.txt | sed 's/^/   /'
TOT=$(grep -E '\$_[AS]?DFFE?_' /tmp/pe_stat.txt | awk '{s+=$2} END {print s+0}')
echo "  TOTAL FLOPS                : $TOT"
grep -E 'Number of cells' /tmp/pe_stat.txt | sed 's/^/  /'
echo
if [ "$RC" -ne 0 ] || [ "$MD" -ne 0 ] || [ "$ER" -ne 0 ]; then
    echo "  *** NOT SYNTHESISABLE -- do not push. Full log /tmp/pe_full.log"
    exit 1
fi
echo "  PASS -- elaborates in plain Verilog, check -assert clean, no"
echo "  multiple drivers. ⚠ This is NOT a timing or area verdict: only the"
echo "  real harden in CI produces PDK cells, congestion and slack."
exit 0
