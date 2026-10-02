#!/usr/bin/env bash
# Part 3 driver for the foreign checker.
# SCRIPT FILE, never `bash -lc` -- inline $VAR expansion across the
# Git-Bash/WSL boundary has eaten these arguments before.
set -uo pipefail
TK=/opt/ta/tchecker/bin
F="$1"
LBL="$2"
"$TK/tck-syntax" -c "$F" 2>&1 | grep -iE "error|OK" | head -2
timeout 1800 "$TK/tck-reach" -a reach -l "$LBL" "$F" 2>&1 \
    | grep -aE "REACHABLE|VISITED_STATES|RUNNING_TIME|ERROR|error" | head -6
