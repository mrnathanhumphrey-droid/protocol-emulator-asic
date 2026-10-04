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
hierarchy -top tt_um_protocol_emulator -check
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
# ---- price the elaboration-time static assertion, IN YOSYS -------------
# ⛔⛔ IT WAS SILENT HERE UNTIL NOW, which is the whole reason Wilson asked.
# `hierarchy` without `-check` treats an unknown module as a BLACK BOX, so the
# undefined-module assertion elaborated cleanly at AW=4 and yosys exited 0 --
# an assertion that fires in iverilog and Verilator and says NOTHING in the
# tool that builds the chip. With `-check` it errors by name.
# ⚠ WHAT THIS DOES AND DOES NOT ESTABLISH: it proves OUR synthesis gate catches
# it. Whether LibreLane's own synth script passes `-check` is NOT verified
# here, so the guarantee is ours, not the flow's.
echo
echo "  --- static assertion, priced in yosys ---"
cat > /tmp/pe_assert_bad.ys <<'YS'
read_verilog src/pe_engine.v
chparam -set AW 4 pe_engine
hierarchy -top pe_engine -check
YS
yosys -s /tmp/pe_assert_bad.ys > /tmp/pe_assert_bad.log 2>&1
AB=$?
if [ "$AB" -ne 0 ] && grep -qi 'HEADER_REGION_DOES_NOT_FIT' /tmp/pe_assert_bad.log; then
    echo "  AW=4 fails elaboration with the diagnostic: PASS"
else
    echo "  *** AW=4 did NOT fail with the diagnostic (exit $AB). The static"
    echo "      assertion is SILENT in the synthesis path, so it guards"
    echo "      simulation only."
    exit 1
fi

echo "  PASS -- elaborates in plain Verilog, check -assert clean, no"
echo "  multiple drivers. ⚠ This is NOT a timing or area verdict: only the"
echo "  real harden in CI produces PDK cells, congestion and slack."
exit 0
