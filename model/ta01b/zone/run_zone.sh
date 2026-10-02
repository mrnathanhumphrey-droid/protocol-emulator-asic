#!/usr/bin/env bash
# Zone cross-check for TA-01b. SCRIPT FILE, never `bash -lc` -- inline $VAR
# expansion across the Git-Bash/WSL boundary has eaten these variables before.
set -uo pipefail
TK=/opt/ta/tchecker/bin
cd /mnt/d/ProtocolEmulator/model/ta01b/zone

for f in "$@"; do
    echo "=== ${f} ==="
    "$TK/tck-syntax" -c "${f}.tck" 2>&1 | head -3
    timeout 600 "$TK/tck-reach" -a reach -l bad "${f}.tck" 2>&1 \
        | grep -E "REACHABLE|VISITED_STATES|VISITED_TRANSITIONS|RUNNING_TIME|MEMORY"
    echo
done
