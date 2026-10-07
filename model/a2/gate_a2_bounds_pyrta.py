"""RULING S -- the pyRTA column of `test/clocked_a2_bounds.json`, re-derived.

⛔⛔ WHY THIS IS A SEPARATE GATE. The per-program A2 budgets the bench enforces
are pyRTA-PRIMARY, and pyRTA is NOT vendored, so -- like every other
pyRTA-primary gate here -- this one lives OUTSIDE `ci/run_gates.sh` and runs
under `model/a2/run_a2.py` by hand at each checkpoint. It is RED without
pyRTA rather than falling back to our own recurrence.

`gate_a2_program.py` (in CI) re-derives everything EXCEPT this column -- the
lane set, U, J and our own recurrence -- so an image that changed without the
JSON being regenerated is caught on every push. What only this gate catches is
the pyRTA column itself drifting: a pyRTA version change, or a change to how
`pyrta_bound` frames the question.

⚠ THE FIRST VERSION OF RULING S PUT THIS CHECK IN CI, where it went red at
20 of 22 while passing locally -- a pyRTA clone sits in a scratch directory on
the development box. Checking CI on the exact SHA is what caught it.
"""

from __future__ import annotations

import io
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import program_a2                                                 # noqa: E402
from pyrta_src import require_pyrta                               # noqa: E402


def main() -> int:
    print()
    print("=" * 78)
    print("  RULING S -- the pyRTA column of the per-program A2 budgets")
    print("=" * 78)
    src = require_pyrta("gate_a2_bounds_pyrta.py")
    if not src:
        return 1
    if not os.path.isfile(program_a2.OUT_JSON):
        print("  *** FAIL test/clocked_a2_bounds.json is absent")
        return 1
    with io.open(program_a2.OUT_JSON, encoding="utf-8") as fh:
        on_disk = json.load(fh)
    rc = 0
    n = 0
    for name, img in program_a2.clocked_images():
        fresh = program_a2.derive(img, src)
        old = on_disk.get(name)
        if old != fresh:
            print("  *** FAIL %s differs from the committed row" % name)
            rc = 1
        n += 1
        for ln, e in sorted(fresh["lanes"].items(), key=lambda kv: int(kv[0])):
            print("    %-24s lane %s  r(pyRTA) %-5s r(ours) %-5s budget %s"
                  % (name, ln, e["r_pyrta"], e["r_ours"], e["slack"]))
    print()
    print("  %d image(s) re-derived with pyRTA" % n)
    print("=" * 78)
    print("  GATE a2-bounds-pyrta: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
