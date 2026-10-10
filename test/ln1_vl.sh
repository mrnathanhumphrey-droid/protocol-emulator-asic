#!/usr/bin/env bash
# LN1 Verilator arms, called by ci/ln1_replay.py: M_PFETCH_NOWAIT on m20
# (iverilog leaves its never-written capture as X; --x-initial unique makes it a
# defined value), plus the CLEAN m20 under the same simulator as the control --
# a Verilator-vs-iverilog difference on the clean build would otherwise be
# indistinguishable from the mutant's divergence.
# Usage: bash test/ln1_vl.sh <outdir> <m20.hex> <rows> <rtl label>
# Verilator is "$VL" from ci/tools.sh: $PE_VERILATOR (the pin), else PATH.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
. "$ROOT/ci/tools.sh"     # ruling V: $VL from PE_VERILATOR, made absolute
tool_banner verilator
OUT="$1"; HEX="$2"; ROWS="$3"; RTL="$4"
NB=$(tr -s ' \r\n' '\n' < "$HEX" | grep -cv '^$')
SRCS="test/tb_w.v test/tr_mon.v src/pe_engine.v src/pe_store.v src/project.v"
E='-DE=tr_top.u_tb.dut.u_eng -DCLK=tr_top.u_tb.clk -DTR1_VL_TOP'
FLAGS="--cc --exe --main --timing --public-flat-rw -Wno-fatal --x-initial unique"
rc=0

arm() {   # $1=build label $2=defines $3=arm name $4=seed
  local b="$OUT/vl_$1"
  rm -rf "$b"
  # shellcheck disable=SC2086
  "$VL" $FLAGS $E $2 +incdir+. +incdir+test -Mdir "$b" -o tr.sim \
      --top-module tr_top $SRCS > "$OUT/vl_$1.log" 2>&1
  make -C "$b" -f Vtr_top.mk -j 4 >> "$OUT/vl_$1.log" 2>&1
  [ -x "$b/tr.sim" ] || { echo "*** $1 build failed"; grep -E '^%Error' "$OUT/vl_$1.log" | head -5; rc=1; return; }
  "$b/tr.sim" +IMG="$HEX" +NBYTES="$NB" +NCYC=$((ROWS + 5000)) +WARMUP=0 \
      +TRACE="$OUT/trace_$3.csv" +MAXROWS="$ROWS" "+META=$3 rtl=$RTL" \
      +verilator+rand+reset+2 +verilator+seed+"$4" >> "$OUT/vl_$1.log" 2>&1
  echo "$3 rows $(( $(wc -l < "$OUT/trace_$3.csv") - 2 ))"
}

arm clean "" VL_m20 1
# seed 4: seeds 1-3 decode the garbage capture as armed/clocked/chaining and
# leave scope by row 3; 4-8 stay in scope to ~row 201 and show P_REQ -> P_CAP
arm nowait "-DM_PFETCH_NOWAIT" MF_nowait_m20 4
exit $rc
