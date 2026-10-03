#!/usr/bin/env bash
# SPEC P1 must-fire: a peer AT THE OLD BAND EDGE must be REJECTED once the
# sampler is realistic. Instantiates Te and asks whether `bad` is reachable.
set -uo pipefail
IMITATOR="${IMITATOR:-/opt/ta/bin/imitator}"
cd /mnt/d/ProtocolEmulator/model/ta01c
printf "  %-8s %-14s %s\n" "Te" "verdict" "meaning"
for TE in 412 413 414 457 458 459; do
    F="sampled_Te${TE}"
    rm -f "${F}.imi" "${F}.imiprop" "${F}.res"
    sed "s/^\t\t& Te > 0\$/\t\t\& Te = ${TE}/" uart_sampled.imi > "${F}.imi"
    grep -q "Te = ${TE}" "${F}.imi" || { echo "  ${TE}: GEN MISMATCH"; continue; }
    cp uart_sampled.imiprop "${F}.imiprop"
    "$IMITATOR" "${F}.imi" "${F}.imiprop" > "${F}.stdout" 2>&1
    RC=$?
    if [ "$RC" != 0 ] || [ ! -f "${F}.res" ]; then
        printf "  %-8s %-14s %s\n" "$TE" "TOOL-FAIL" "rc=$RC"; continue
    fi
    BODY=$(sed -n '/BEGIN CONSTRAINT/,/END CONSTRAINT/p' "${F}.res" \
           | grep -vE "BEGIN CONSTRAINT|END CONSTRAINT|^[[:space:]]*$")
    if echo "$BODY" | grep -qiE "False|^$"; then
        printf "  %-8s %-14s %s\n" "$TE" "REJECTED" "bad reachable: no valuation conforms"
    else
        printf "  %-8s %-14s %s\n" "$TE" "ADMITTED" "bad unreachable ($(echo $BODY | tr -d '\n'))"
    fi
    rm -f "${F}.imi" "${F}.imiprop" "${F}.res" "${F}.stdout"
done
