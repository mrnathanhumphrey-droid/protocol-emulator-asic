"""CE5 FREEZE -- the RTL under `src/` is byte-for-byte the frozen RTL.

CE5 (the 1-Wire DS18B20 demo, `test/run_onewire.py`) is a claim about what
the FROZEN chip can do with a program alone. If anything under `src/` moved,
CE5 is VOID -- the program might be leaning on an RTL change. So:

    git diff --name-only FREEZE_SHA -- src/      must print nothing
    git ls-files --others --exclude-standard -- src/   (no new, untracked RTL)

⭐ FREEZE_SHA IS ONE NAMED CONSTANT so it can be re-pinned when this branch is
rebased onto the formally-equivalent "commit 1": change it here and nowhere
else.

⛔ POSITIVE TOKEN ONLY (Wilson's standing rule). The pass needs: git's
version banner printed, FREEZE_SHA resolved to a commit object, both git
commands exiting 0 with EMPTY output, and the planted must-fire seen RED by
NAME. Only then is `CE5-FREEZE: PASSED` printed. A missing freeze commit (a
shallow CI checkout) is fetched once by SHA; if it still cannot be resolved
the gate is RED, never a skip.

MUST-FIRE: a COPY of `src/` in a temp directory, one character changed in its
`pe_engine.v`, checked against FREEZE_SHA through a TEMPORARY index (read from
FREEZE_SHA) and `--work-tree` pointed at the copy. The real tree and the real
index are never touched. It must list `src/pe_engine.v`; an unmodified copy
checked the same way must list nothing (the control, so the mechanism is not
red for some other reason).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

#: the frozen RTL. Re-pinned from ae15d2c to commit 1 (62390e9) on the rebase
#: (Wilson): valid because commit 1's src/ change is declaration-only and
#: formally equivalent to ae15d2c (model/rtl_equiv.py: 4,102/4,102 proven).
#: ⛔ RE-PINNED AGAIN, to b3cf898 (WF2, silicon fixes #8-#11) -- NOT a
#: bookkeeping move: the RTL changed behaviour (the first TX byte, reloads),
#: and CE5's own feed changed with it (the first reset block lost its 2-RST
#: workaround). CE5 was therefore RE-CERTIFIED on this SHA -- the full set,
#: presence, ROM + scratchpad with CRC, per-slot timing windows and every
#: must-fire -- and docs/CE5_LOG.md records the move and why (Wilson).
FREEZE_SHA = "b3cf89811f30132e99b790afb60a447d131536ef"


def git(args, env=None):
    r = subprocess.run(["git"] + args, cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env)
    return r.returncode, r.stdout, r.stderr


def resolve():
    rc, out, _ = git(["cat-file", "-t", FREEZE_SHA])
    if rc == 0 and out.strip() == "commit":
        return True
    # a shallow checkout (CI) may not hold it: fetch that one commit by SHA
    git(["fetch", "--no-tags", "--depth=1", "origin", FREEZE_SHA])
    rc, out, _ = git(["cat-file", "-t", FREEZE_SHA])
    return rc == 0 and out.strip() == "commit"


def changed(work_tree=None):
    """-> (ok_ran, [changed paths]) for src/ against FREEZE_SHA."""
    env, pre = None, []
    tmp_index = None
    if work_tree is not None:
        fd, tmp_index = tempfile.mkstemp(prefix="ce5_index_")
        os.close(fd)
        os.remove(tmp_index)
        env = dict(os.environ, GIT_INDEX_FILE=tmp_index)
        rc, _o, e = git(["read-tree", FREEZE_SHA], env=env)
        if rc != 0:
            return False, ["<read-tree failed: %s>" % e.strip()[:80]]
        pre = ["--work-tree=" + work_tree]
    try:
        rc1, out1, e1 = git(pre + ["diff", "--name-only", FREEZE_SHA, "--",
                                   "src/"], env=env)
        rc2, out2, e2 = git(pre + ["ls-files", "--others",
                                   "--exclude-standard", "--", "src/"], env=env)
    finally:
        if tmp_index and os.path.exists(tmp_index):
            os.remove(tmp_index)
    if rc1 != 0 or rc2 != 0:
        return False, ["<git failed: %s %s>" % (e1.strip()[:60], e2.strip()[:60])]
    names = [l for l in (out1 + out2).splitlines() if l.strip()]
    return True, names


def main() -> int:
    print("=" * 78)
    print("CE5 FREEZE -- src/ against FREEZE_SHA %s" % FREEZE_SHA)
    print("=" * 78)
    rc, ver, _ = git(["--version"])
    print("  %s" % (ver.strip() if rc == 0 else "*** git did not run"))
    if rc != 0:
        print("  *** CE5-FREEZE: FAILED (no git)")
        return 1
    if not resolve():
        print("  *** FREEZE_SHA does not resolve to a commit here (shallow "
              "clone and the fetch failed?) -- RED, not a skip")
        print("  *** CE5-FREEZE: FAILED")
        return 1
    print("  FREEZE_SHA resolves to a commit")
    ok = True
    ran, names = changed()
    if ran and not names:
        print("  real tree: git diff --name-only FREEZE_SHA -- src/ is EMPTY, "
              "no untracked RTL")
    else:
        ok = False
        print("  *** real tree: src/ differs from the freeze: %s -- CE5 VOID"
              % names)

    print("  --- must-fire: a planted 1-char change in a COPY of src/ ---")
    tmp = tempfile.mkdtemp(prefix="ce5_freeze_")
    try:
        shutil.copytree(os.path.join(ROOT, "src"), os.path.join(tmp, "src"))
        ran_c, names_c = changed(tmp)
        if ran_c and not names_c:
            print("    control: the unmodified copy reads clean")
        else:
            ok = False
            print("    *** control: the unmodified copy reads %s" % names_c)
        tgt = os.path.join(tmp, "src", "pe_engine.v")
        with open(tgt, "rb") as fh:
            data = bytearray(fh.read())
        k = data.index(b"localparam")             # a real token, mid-file
        data[k] = ord("L")
        with open(tgt, "wb") as fh:
            fh.write(bytes(data))
        ran_m, names_m = changed(tmp)
        if ran_m and "src/pe_engine.v" in names_m:
            print("    red: the planted copy lists %s" % names_m)
        else:
            ok = False
            print("    *** MUST-FIRE FAILED: planted copy reads %s (ran=%s)"
                  % (names_m, ran_m))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    # the real file was never opened for writing; prove it is still clean
    ran2, names2 = changed()
    if not (ran2 and not names2):
        ok = False
        print("  *** after the must-fire the real tree reads %s" % names2)
    print()
    if ok:
        print("  CE5-FREEZE: PASSED")
        return 0
    print("  *** CE5-FREEZE: FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
