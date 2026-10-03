#!/usr/bin/env bash
# SPEC P1 band re-synthesis. SCRIPT FILE, never `bash -lc`.
set -uo pipefail
IMITATOR="${IMITATOR:-/opt/ta/bin/imitator}"
cd /mnt/d/ProtocolEmulator/model/ta01c
rm -f uart_sampled.res
"$IMITATOR" uart_sampled.imi uart_sampled.imiprop > uart_sampled.stdout 2>&1
RC=$?
if [ "$RC" != 0 ] || [ ! -f uart_sampled.res ]; then
    echo "*** imitator rc=$RC, .res present: $([ -f uart_sampled.res ] && echo yes || echo no)"
    sed -n '1,40p' uart_sampled.stdout
    exit 1
fi
echo "=== synthesized constraint ==="
sed -n '/BEGIN CONSTRAINT/,/END CONSTRAINT/p' uart_sampled.res
echo "=== soundness / termination / nature ==="
grep -E "Constraint soundness|Termination|Constraint nature" uart_sampled.res
