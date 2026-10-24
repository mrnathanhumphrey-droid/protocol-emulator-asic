"""Ruling MF1 -- every hash `test/artefacts.sha256` pins matches the file.

⛔⛔ WHY. From `9ebcaeb` to `0e29fe7` the committed manifest pinned the WRONG
bytes for all five `corpus_*.hex`: `make_smoke_image.py --all` wrote it before
`corpus.py` rewrote the corpus. Nothing in CI compared the manifest with the
images, so a manifest whose whole purpose is "a changed artefact shows as a
diff" carried five stale lines through two green commits.

⛔ WHICH MANIFEST, AND WHY IT DIFFERS BY PLACE. A fresh CI clone lacks the
generated (gitignored) images, so `benchset.base_images()` runs `--all` --
which REWRITES the working-copy manifest from whatever it just built. Checking
that copy in CI would compare the files with hashes taken FROM those files and
could never fail; it is exactly how the stale lines would have survived CI.
  * in CI (`GITHUB_ACTIONS`) the COMMITTED manifest (`git show HEAD:`) is
    checked against the files: tracked images as committed, generated images
    as regenerated -- which is also the reproducibility claim the manifest
    makes.
  * locally the WORKING manifest is checked, because a commit in progress
    legitimately changes it; that would have caught `9ebcaeb` before commit.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MANIFEST = os.path.join(HERE, "artefacts.sha256")
LINE = re.compile(r"^([0-9a-f]{64})\s+(\S+)\s+#")


def manifest_text(committed):
    if committed:
        r = subprocess.run(["git", "show", "HEAD:test/artefacts.sha256"],
                           cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            return None, "git show HEAD:test/artefacts.sha256 failed"
        return r.stdout, "committed (HEAD)"
    with open(MANIFEST, encoding="ascii", errors="replace") as fh:
        return fh.read(), "working copy"


def check(text, read):
    """[problems] for manifest `text`; `read(name)` returns bytes or None."""
    probs, n = [], 0
    for ln in text.splitlines():
        m = LINE.match(ln)
        if not m:
            continue
        n += 1
        want, name = m.group(1), m.group(2)
        data = read(name)
        if data is None:
            probs.append("%s is pinned but not on disk" % name)
            continue
        # line endings normalised: the generators write LF; a Windows
        # checkout may hand back CRLF for the same committed bytes
        got = hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()
        if got != want:
            probs.append("%s: pinned %s..., file hashes %s..."
                         % (name, want[:12], got[:12]))
    if n == 0:
        probs.append("the manifest pins NOTHING -- a check with no subject")
    return probs, n


def read_file(name):
    p = os.path.join(HERE, name)
    if not os.path.isfile(p):
        return None
    with open(p, "rb") as fh:
        return fh.read()


def main() -> int:
    print()
    print("=" * 78)
    print("  MF1 -- EVERY PINNED ARTEFACT HASH MATCHES ITS FILE")
    print("=" * 78)
    ci = os.environ.get("GITHUB_ACTIONS") == "true"
    text, which = manifest_text(committed=ci)
    rc = 0
    if text is None:
        print("  *** %s" % which)
        return 1
    probs, n = check(text, read_file)
    print("  manifest : %s, %d artefact(s) pinned" % (which, n))
    for p in probs:
        print("  *** %s" % p)
        rc = 1
    if not probs:
        print("  every pinned hash matches the file on disk")

    # ---- must-fire: ONE FLIPPED BYTE ----------------------------------------
    print()
    print("  --- must-fire ---")
    first = next((LINE.match(l).group(2) for l in text.splitlines()
                  if LINE.match(l)), None)

    def flipped(name):
        d = read_file(name)
        if d is not None and name == first and d:
            d = bytes([d[0] ^ 0x01]) + d[1:]
        return d
    p2, _ = check(text, flipped)
    hit = any(x.startswith(first + ":") for x in p2) if first else False
    print("    one flipped byte in %-24s %s" % (first, "ok" if hit
                                                 else "*** MISSED"))
    p3, _ = check("", read_file)
    hit2 = any("pins NOTHING" in x for x in p3)
    print("    an empty manifest is refused                 %s"
          % ("ok" if hit2 else "*** MISSED"))
    # ⛔ THE REAL DEFECT: the manifest as committed at 231b37c (kept as a
    # fixture -- CI checks out at depth 1), with five stale corpus hashes.
    fx = os.path.join(ROOT, "model", "fixtures", "artefacts_231b37c.sha256.txt")
    with open(fx, encoding="ascii", errors="replace") as fh:
        p4, _ = check(fh.read(), read_file)
    # ⛔ F5 (meta-test, 10-23): the STALE-HASH message only. "corpus_" alone
    # also matched "is pinned but not on disk", so with the images missing
    # this read 5 for the wrong reason.
    stale = sorted(x.split(":")[0] for x in p4
                   if x.startswith("corpus_") and "file hashes" in x)
    hit3 = len(stale) == 5
    print("    the 231b37c manifest (5 stale corpus hashes) %s  %s"
          % ("ok" if hit3 else "*** MISSED", stale))
    if not (hit and hit2 and hit3):
        rc = 1

    print()
    print("=" * 78)
    print("  GATE manifest: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
