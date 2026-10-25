"""THE HARDEN OF RECORD STILL DESCRIBES THIS TREE (Wilson 10-21; R2 10-22).

The harden of record (gds 39719085897 on a48af2e) wrote what it ran ON --
chip RTL, flow config, gl_test image set -- each as a set hash
(.github/workflows/gds.yaml -> harden_record.json, kept verbatim in
model/harden_of_record.json). This gate recomputes each set's hash from GIT
BLOBS at HEAD (ci/blobhash.py, the same formula) and requires all three equal,
and every file committed and clean. A mismatch is RED: re-run the harden;
nothing is assumed from "only bench work landed".

⛔ BLOBS, NOT WORKING-TREE BYTES: this checkout's CRLF gave the chip RTL a
different hash (0e4168c1... vs 998ff31b..., 10-22). The helper reads blobs.
⛔ THE FILE LISTS ARE RE-DERIVED, NOT ONLY READ FROM THE RECORD: a new .v under
src/ or a new image read by test/test.py would otherwise pass unhashed, since
the record names only what existed then. The derivation is gds.yaml's own.

MUST-FIRES (planted, through record_problems()): a changed record hash, a
record file list that misses a file the tree has, an uncommitted edit.
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "ci"))
import blobhash                                    # noqa: E402

RECORD = os.path.join(HERE, "harden_of_record.json")
SETS = ("chip_rtl", "flow_config", "gl_test_images")


def tree_sets():
    """{set: [files]} derived from HEAD exactly as gds.yaml derives them."""
    src = blobhash._git(["ls-tree", "--name-only", "HEAD", "src/"])[1].decode()
    rtl = sorted(p for p in src.split() if p.endswith(".v"))
    test_py = blobhash.blobs(["test/test.py"])["test/test.py"].decode("utf-8")
    imgs = sorted({"test/" + m for m in re.findall(r'read_hex\("([^"]+)"\)', test_py)})
    return {"chip_rtl": rtl, "flow_config": ["src/config.json", "info.yaml"],
            "gl_test_images": imgs}


def record_problems(rec, sets, hashes, dirty):
    """[problem]: the gate and its must-fires both call this. `sets` are the
    tree's derived file lists, `hashes` their blob hashes at HEAD."""
    probs = ["%s is uncommitted or untracked" % p for p in dirty]
    for k in SETS:
        r = rec.get(k) or {}
        if sorted(r.get("files", [])) != sorted(sets[k]):
            probs.append("%s: the record hardened %s, the tree has %s"
                         % (k, r.get("files"), sets[k]))
        if r.get("sha256") != hashes[k]:
            probs.append("%s: the record hashed %s..., HEAD hashes %s... -- "
                         "RE-RUN THE HARDEN" % (k, str(r.get("sha256"))[:12],
                                                hashes[k][:12]))
    return probs


def main() -> int:
    print("=" * 78)
    print("HARDEN RECORD -- the harden of record still describes this tree")
    print("=" * 78)
    with open(RECORD, encoding="utf-8") as fh:
        rec = json.load(fh)
    print("  record: run %s on %s" % (rec.get("run"), str(rec.get("sha"))[:12]))
    sets = tree_sets()
    hashes = {k: blobhash.set_hash(v) for k, v in sets.items()}
    dirty = blobhash.dirty(sorted({p for v in sets.values() for p in v}))
    for k in SETS:
        same = (rec.get(k) or {}).get("sha256") == hashes[k]
        print("  %-15s %d files  HEAD %s...  %s" % (k, len(sets[k]), hashes[k][:12],
                                                    "== record" if same else "*** DIFFERS"))
    probs = record_problems(rec, sets, hashes, dirty)
    for p in probs:
        print("  *** %s" % p)
    ok = not probs

    print("  --- must-fire: the check rejects what it claims to ---")
    for what, prec, psets, pdirty in (
            ("a record hash that does not match",
             dict(rec, chip_rtl=dict(rec["chip_rtl"], sha256="0" * 64)), sets, []),
            ("a tree file the record never hardened",
             rec, dict(sets, chip_rtl=sets["chip_rtl"] + ["src/new.v"]), []),
            ("an uncommitted edit to a hardened file",
             rec, sets, ["src/pe_engine.v"])):
        red = bool(record_problems(prec, psets, hashes, pdirty))
        print("    %-46s %s" % (what, "red  ok" if red else "*** MISSED"))
        ok = ok and red
    print()
    print("  GATE harden_record: %s" % ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
