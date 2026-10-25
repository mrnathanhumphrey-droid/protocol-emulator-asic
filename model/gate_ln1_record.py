"""LN1 OF RECORD STILL DESCRIBES THIS TREE (Wilson R4, 10-22).

The full LN1 run (200,000 rows per arm, `workflow_dispatch` of test.yaml) is
too long for every push, so it is BOUND to its inputs like the harden: the run
writes what it read (ci/ln1_replay.py --record: the trace benches, the Lean
sources, the lockstep images, and every repo module it imported) and their
set hash from GIT BLOBS (ci/blobhash.py). That record is committed as
model/ln1_of_record.json. This gate requires:

  * the record says GREEN at >= 200,000 rows;
  * set_hash(the recorded files) at HEAD == the recorded hash, and every one
    of them committed and clean -- any change is RED: re-dispatch the 200k run.

⭐ The list is the RUN's, not re-derived here: ln1_replay imports some modules
only mid-run, so an import-time list would be short. A new import still trips
the gate -- adding it edits a file already on the list.

MUST-FIRES (planted, through ln1_problems()): a 20k-row record, a RED record,
a hash that does not match, an uncommitted edit.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "ci"))
import blobhash                                    # noqa: E402

RECORD = os.path.join(HERE, "ln1_of_record.json")
FULL_ROWS = 200000


def ln1_problems(rec, head_hash, dirty):
    """[problem]: the gate and its must-fires both call this."""
    probs = ["%s is uncommitted or untracked" % p for p in dirty]
    if rec.get("verdict") != "GREEN":
        probs.append("the record's verdict is %r, not GREEN" % rec.get("verdict"))
    if int(rec.get("rows") or 0) < FULL_ROWS:
        probs.append("the record ran %s rows per arm, not the full %d"
                     % (rec.get("rows"), FULL_ROWS))
    if (rec.get("inputs") or {}).get("sha256") != head_hash:
        probs.append("its inputs hashed %s..., HEAD hashes %s... -- RE-DISPATCH "
                     "THE 200k RUN" % (str((rec.get("inputs") or {}).get("sha256"))[:12],
                                      str(head_hash)[:12]))
    return probs


def main() -> int:
    print("=" * 78)
    print("LN1 RECORD -- the full Lean replay still describes this tree")
    print("=" * 78)
    if not os.path.isfile(RECORD):
        print("  *** no %s -- dispatch the 200k run with --record and commit "
              "its record" % os.path.relpath(RECORD, ROOT))
        print("  GATE ln1_record: FAILED")
        return 1
    with open(RECORD, encoding="utf-8") as fh:
        rec = json.load(fh)
    files = (rec.get("inputs") or {}).get("files") or []
    print("  record: run %s on %s, %s rows, %s arms, %d input files"
          % (rec.get("run"), str(rec.get("sha"))[:12], rec.get("rows"),
             rec.get("arms"), len(files)))
    try:
        head = blobhash.set_hash(files)
    except KeyError as e:                 # a recorded file no longer at HEAD
        head = "<%s>" % e
    probs = ln1_problems(rec, head, blobhash.dirty(files))
    if not files:
        probs.append("the record names no input files")
    for p in probs:
        print("  *** %s" % p)
    ok = not probs
    if ok:
        print("  inputs at HEAD hash %s... == the record" % head[:12])

    print("  --- must-fire: the check rejects what it claims to ---")
    good = dict(rec, verdict="GREEN", rows=FULL_ROWS)
    for what, prec, ph, pdirty in (
            ("a 20k-row record", dict(good, rows=20000), good["inputs"]["sha256"], []),
            ("a RED record", dict(good, verdict="RED"), good["inputs"]["sha256"], []),
            ("inputs that moved", good, "0" * 64, []),
            ("an uncommitted edit to an input", good, good["inputs"]["sha256"],
             ["src/pe_engine.v"])):
        red = bool(ln1_problems(prec, ph, pdirty))
        print("    %-46s %s" % (what, "red  ok" if red else "*** MISSED"))
        ok = ok and red
    print()
    print("  GATE ln1_record: %s" % ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
