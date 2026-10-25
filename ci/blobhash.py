"""ONE BLOB-HASH HELPER -- a file set's hash, from GIT BLOBS (Wilson R2, 10-22).

    python ci/blobhash.py [--rev REV] PATH...    # print the set hash

set_hash(paths, rev) = sha256 over sorted(paths) of  path NUL blob-bytes NUL.
That is gds.yaml's harden-record formula exactly, so a record written by the
harden and a check made here agree byte for byte.

⛔⛔ BLOBS, NEVER WORKING-TREE BYTES. This Windows checkout is CRLF on some
files and CI's Linux checkout is LF: hashing working-tree bytes gave the
harden of record's chip RTL a DIFFERENT hash here (0e4168c1... against the
record's 998ff31b..., 10-22). Blob bytes are the same on every checkout.
⛔ A blob hash at HEAD does not see an UNCOMMITTED edit, so every gate using
this also calls dirty(paths): a path that differs from HEAD, or is untracked,
is named and the gate is red.

Users: the harden record (gds.yaml writes it; model/gate_harden_record.py
checks it), the CE5 freeze (model/gate_ce5_freeze.py), LN1's input binding
(ci/ln1_replay.py writes it; model/gate_ln1_record.py checks it).
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _git(args, inp=None):
    r = subprocess.run(["git"] + args, cwd=ROOT, input=inp, capture_output=True)
    return r.returncode, r.stdout, r.stderr


def blobs(paths, rev="HEAD"):
    """{path: bytes} for each path at `rev`; a path not at rev raises."""
    req = b"".join(("%s:%s\n" % (rev, p)).encode() for p in paths)
    rc, out, err = _git(["cat-file", "--batch"], req)
    if rc != 0:
        raise RuntimeError("git cat-file failed: %s" % err.decode()[:200])
    res, i = {}, 0
    for p in paths:
        nl = out.index(b"\n", i)
        head = out[i:nl].decode()
        if head.endswith(" missing"):
            raise KeyError("%s is not in %s" % (p, rev))
        _sha, kind, size = head.split()
        if kind != "blob":
            raise KeyError("%s at %s is a %s, not a file" % (p, rev, kind))
        n = int(size)
        res[p] = out[nl + 1:nl + 1 + n]
        i = nl + 1 + n + 1                    # the batch's trailing newline
    return res


def hash_contents(contents):
    """The set hash of {path: bytes} -- what set_hash computes from blobs; a
    must-fire hands it planted bytes without touching git."""
    d = hashlib.sha256()
    for p in sorted(contents):
        d.update(p.encode() + b"\0" + contents[p] + b"\0")
    return d.hexdigest()


def set_hash(paths, rev="HEAD"):
    return hash_contents(blobs(sorted(paths), rev))


def dirty(paths):
    """[path] that differ from HEAD (staged or not) or are untracked."""
    rc1, o1, _ = _git(["diff", "--name-only", "HEAD", "--"] + list(paths))
    rc2, o2, _ = _git(["ls-files", "--others", "--exclude-standard", "--"]
                      + list(paths))
    if rc1 != 0 or rc2 != 0:
        return ["<git diff/ls-files failed>"]
    return sorted({l for l in (o1 + o2).decode().splitlines() if l.strip()})


def main(argv) -> int:
    rev = "HEAD"
    if "--rev" in argv:
        k = argv.index("--rev")
        rev = argv[k + 1]
        argv = argv[:k] + argv[k + 2:]
    paths = argv[1:]
    if not paths:
        print(__doc__.splitlines()[2].strip())
        return 2
    print(set_hash(paths, rev))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
