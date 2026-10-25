"""A2 OF RECORD STILL DESCRIBES THIS TREE (Wilson 10-25).

The A2 suite (model/a2/run_a2.py: pyRTA bounds, sigrok certifications, the
FRAM demos) is run by hand -- pyRTA is not vendored and sigrok is local -- so
the v1 baseline's A2 claims are BOUND to the tree like the harden and LN1:
`run_a2.py --record` writes what it read (test/sweep_record.py: the gates'
import closure, every HDL file, the images they name; blob-hashed) and the
pinned pyRTA commit, committed as model/a2_of_record.json. This gate requires:

  * every gate in the record passed, and the record lists exactly run_a2's
    current GATES (a gate added or dropped since is RED: re-run);
  * the pyRTA commit is the pinned one (model/a2/pyrta_src.PINNED_COMMIT);
  * set_hash(the recorded inputs) at HEAD == the record, all committed and
    clean -- any change is RED: re-run the A2 suite with --record.

MUST-FIRES (planted, through a2_problems()): a failed gate, a gate list that
moved, an unpinned pyRTA, inputs that moved, an uncommitted edit.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "ci"))
sys.path.insert(0, os.path.join(HERE, "a2"))
import blobhash                                    # noqa: E402

RECORD = os.path.join(HERE, "a2_of_record.json")


def a2_problems(rec, gates_now, pinned, head_hash, dirty):
    """[problem]: the gate and its must-fires both call this."""
    res = rec.get("result") or {}
    probs = ["%s is uncommitted or untracked" % p for p in dirty]
    if not res.get("total") or res.get("passed") != res.get("total"):
        probs.append("the record has %s of %s A2 gates passing"
                     % (res.get("passed"), res.get("total")))
    if list(res.get("gates") or []) != list(gates_now):
        probs.append("run_a2's GATES moved since the record (%d recorded, %d now) "
                     "-- re-run" % (len(res.get("gates") or []), len(gates_now)))
    if res.get("pyrta_commit") != pinned:
        probs.append("the record ran pyRTA %s, the pin is %s"
                     % (str(res.get("pyrta_commit"))[:12], pinned[:12]))
    if (rec.get("inputs") or {}).get("sha256") != head_hash:
        probs.append("its inputs hashed %s..., HEAD hashes %s... -- RE-RUN "
                     "model/a2/run_a2.py --record"
                     % (str((rec.get("inputs") or {}).get("sha256"))[:12],
                        str(head_hash)[:12]))
    return probs


def main() -> int:
    print("=" * 78)
    print("A2 RECORD -- the by-hand A2 suite still describes this tree")
    print("=" * 78)
    import run_a2
    from pyrta_src import PINNED_COMMIT
    gates_now = [f for f, _l, _n in run_a2.GATES]
    if not os.path.isfile(RECORD):
        print("  *** no %s -- run model/a2/run_a2.py --record %s"
              % (os.path.relpath(RECORD, ROOT), os.path.relpath(RECORD, ROOT)))
        print("  GATE a2_record: FAILED")
        return 1
    with open(RECORD, encoding="utf-8") as fh:
        rec = json.load(fh)
    files = (rec.get("inputs") or {}).get("files") or []
    res = rec.get("result") or {}
    print("  record: %s on %s -- %s of %s gates, pyRTA %s, %d input files"
          % (rec.get("kind"), str(rec.get("sha"))[:12], res.get("passed"),
             res.get("total"), str(res.get("pyrta_commit"))[:12], len(files)))
    try:
        head = blobhash.set_hash(files)
    except KeyError as e:
        head = "<%s>" % e
    probs = a2_problems(rec, gates_now, PINNED_COMMIT, head, blobhash.dirty(files))
    if not files:
        probs.append("the record names no input files")
    for p in probs:
        print("  *** %s" % p)
    ok = not probs
    if ok:
        print("  inputs at HEAD hash %s... == the record" % head[:12])

    print("  --- must-fire: the check rejects what it claims to ---")
    h = (rec.get("inputs") or {}).get("sha256")
    good = dict(rec, result=dict(res, passed=res.get("total")))
    for what, prec, gl, pin, ph, pd in (
            ("a failed A2 gate", dict(good, result=dict(good["result"], passed=0)),
             gates_now, PINNED_COMMIT, h, []),
            ("a gate list that moved", good, gates_now + ["new_gate.py"],
             PINNED_COMMIT, h, []),
            ("an unpinned pyRTA", good, gates_now, "0" * 40, h, []),
            ("inputs that moved", good, gates_now, PINNED_COMMIT, "0" * 64, []),
            ("an uncommitted edit to an input", good, gates_now, PINNED_COMMIT, h,
             ["src/pe_engine.v"])):
        red = bool(a2_problems(prec, gl, pin, ph, pd))
        print("    %-46s %s" % (what, "red  ok" if red else "*** MISSED"))
        ok = ok and red
    print()
    print("  GATE a2_record: %s" % ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
