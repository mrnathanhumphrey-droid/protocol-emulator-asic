#!/usr/bin/env bash
# LOCAL structural check input for F2 face 3, in SECONDS instead of a 2-hour
# CI harden.
# ⛔ `write_verilog` CANNOT BE USED FOR THIS: yosys renders its own internal
# cells ($_DFF_*, $_AND_*) as behavioural `always`/`assign` blocks, so the
# emitted file has ZERO instances and F2's anti-vacuity guard correctly refuses
# it ("a check that found nothing to check has not run"). `write_json` keeps the
# cell graph, which is what a structural question needs.
set -uo pipefail
cd "${1:-/mnt/d/ProtocolEmulator}" || exit 1
DEFS="${2:-}"      # e.g. M_COMB_OUT, to price the check
cat > /tmp/nl.ys <<'YS'
read_verilog DEFARGS src/pe_store.v
read_verilog DEFARGS src/pe_engine.v
read_verilog DEFARGS src/project.v
hierarchy -top tt_um_protocol_emulator
synth -top tt_um_protocol_emulator -flatten
write_json /tmp/local_netlist.json
YS
if [ -n "$DEFS" ]; then sed -i "s|DEFARGS|-D $DEFS|g" /tmp/nl.ys; else sed -i "s|DEFARGS ||g" /tmp/nl.ys; fi
yosys -s /tmp/nl.ys > /tmp/nl.log 2>&1
RC=$?
if [ "$RC" -ne 0 ]; then echo "yosys failed ($RC); see /tmp/nl.log"; exit 1; fi
OUT="${3:-local_netlist}"
# ⭐ THE DESTINATION IS AN ARGUMENT, so a Linux CI runner uses THIS script
# rather than a second copy of the yosys recipe pasted into the workflow. A
# recipe that exists twice is this project's most reliable bug, and the copy in
# a CI file is the one nobody runs locally. Default stays the Windows-side
# /mnt/c/tmp that the local flow reads.
OUTDIR="${4:-/mnt/c/tmp}"
mkdir -p "$OUTDIR"
cp /tmp/local_netlist.json "$OUTDIR/$OUT.json"
echo "json -> $OUTDIR/$OUT.json ($(wc -c < /tmp/local_netlist.json) bytes) defs=[$DEFS]"
