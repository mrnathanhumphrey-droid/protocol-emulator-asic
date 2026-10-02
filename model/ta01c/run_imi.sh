#!/usr/bin/env bash
# script file, never `bash -lc` -- inline $VAR expansion across the Git-Bash/WSL
# boundary has eaten these before.
set -uo pipefail
cd /mnt/d/ProtocolEmulator/model/ta01c
/opt/ta/bin/imitator "$@" 2>&1
