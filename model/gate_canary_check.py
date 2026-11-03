"""GATE canary-check -- the canary builder and its refusal, every push
(Wilson 11-03, B1).

`ci/make_canary.py` makes a canary as ONE commit on a work commit (only the
density value and the test.yaml ignore change) and its `--check` is the
canary workflow's first step. This gate keeps both honest on the work branch:

  1. A canary built IN MEMORY from this tree's own src/config.json and
     test.yaml, at densities 59/60/61, passes the check's judge -- so the
     builder and the judge agree on the real files, not only on toy ones.
  2. The judge's must-fires (`--self-test`): a config key changed, an RTL file
     changed, test.yaml changed beyond the ignore, a comment added -- red.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "ci"))

import make_canary as MC                                    # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def main():
    with open(os.path.join(ROOT, MC.CONFIG), encoding="utf-8", newline="") as fh:
        cfg = fh.read()
    with open(os.path.join(ROOT, MC.TEST_YAML), encoding="utf-8", newline="") as fh:
        yml = fh.read()
    rc = 0
    print("  --- a canary built from THIS tree passes the check ---")
    for d in (59, 60, 61):
        probs = MC.judge(cfg, MC.with_density(cfg, d), yml, MC.with_ignore(yml),
                         [MC.CONFIG, MC.TEST_YAML])
        print("    density %d: %s" % (d, "green ok" if not probs else "*** " + probs[0]))
        rc |= 1 if probs else 0
    print("  --- the judge's must-fires ---")
    rc |= MC.self_test()
    print()
    print("  GATE canary-check: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
