"""SPEC A1 pricing probe -- A GATE THAT ANALYSES A STALE COPY OF THE LANE TABLE.

⛔⛔ THIS FILE IS A MUTANT, ON PURPOSE, AND IT IS NOT A GATE. It exists only so
`run_a2.py --price` can be shown RED. It reproduces the exact defect A1 screens
for: a gate that imports the shipped table, then hands the analyser a hand-typed
copy whose numbers have gone stale.

The copy below is the table as it stood at `e586ad4` -- before R1 derived
SPI-target's deadline and H3 corrected UART-rx's. Those are the real previous
values, not invented ones, because the defect being priced is specifically "a
copy that was right when it was written".

⭐ AND IT DECLARES NO VARIANT. That is the point. A gate analysing a variant on
purpose says so and the digest line reads VARIANT; this one claims to be
analysing the shipped table, so it must read as a bare mismatch and take the run
down with it.

⛔ `run_a2.py` must NOT list this file in its normal GATES. If this probe ever
appears in a green run, the pricing harness has leaked into the suite.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import lane_digest                                              # noqa: E402
from bursty import BLane                                        # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# The table as hand-typed at e586ad4: SPI-target D_tol=12 (the stand-in R1
# replaced with 18) and UART-rx D_tol=216 (H3 corrected it to 213).
STALE = [("UART-tx 115200", 434, 2, 216, 1, 434),
         ("SPI-tx 1 MHz", 25, 2, 23, 1, 25),
         ("I2C 400 kHz", 45, 2, 15, 1, 45),
         ("UART-rx 115200", 4140, 2, 216, 10, 414),
         ("SPI-target 1 MHz", 400, 2, 12, 16, 25)]


def main() -> int:
    print()
    print("=" * 78)
    print("A1 PRICING PROBE -- a gate analysing a STALE hand-typed lane table")
    print("=" * 78)
    lanes = [BLane(n, T, C, n=nn, t=t, D_tol=d) for n, T, C, d, nn, t in STALE]
    # claims to analyse the shipped table; declares no variant
    lane_digest.announce("_price_stale_lane_table.py (PROBE)", lanes)
    print("  This probe exits 0 ON PURPOSE. The run must fail on the DIGEST")
    print("  MISMATCH, not on this exit status -- otherwise the meta-check is")
    print("  being credited for something an ordinary gate failure would catch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
