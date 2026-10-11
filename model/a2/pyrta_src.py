"""SPEC H1 -- ONE pyRTA discovery function, shared by every gate that needs it.

THE ONE CLAIM: a gate that names pyRTA as its authority is RED when pyRTA is
absent, and GREEN only when the clone it actually imported is named in its own
output.

⛔⛔ WHY THIS IS A FILE AND NOT A COPY-PASTE. `gate_pyrta.py` had a discovery
function with a convenience fallback (walk TEMP and ~ for a clone); `gate_twin_pair.py`
had `os.environ.get("PYRTA_SRC")` and nothing else. The two disagreed, so the
twin-pair gate went RED -- "this path is UNPINNED" -- with the tool sitting on
disk and importable. A false red is not harmless: that gate exists to pin the
BY-VALUE direction of the self-exclusion bug, so for as long as it reds for the
wrong reason the direction is unpinned AND the reason is hidden behind an
expected-looking failure.

⛔⛔ AND THE FALLBACK MADE THE GATE UNPRICEABLE, WHICH IS THE WORSE HALF. The
acceptance test for a foreign-authority gate is `price_gates.sh`: remove the
tool, require red. With an unconditional disk walk there is no way to remove it
-- `PYRTA_SRC=/nonexistent` would be ignored and the walk would find the clone
anyway, so the pricing arm would report GREEN-without-authority and we would
have "fixed" it by weakening the only check that can detect the problem.

So the contract here is explicit, and it is the whole point of the module:

    PYRTA_SRC unset            -> search (TEMP, ~) for a clone; convenience
    PYRTA_SRC set to a dir     -> use exactly that; no search
    PYRTA_SRC set to a NON-dir -> return None. DO NOT SEARCH.

The third line is what makes the gate priceable: an explicitly-set-but-invalid
path means "use this and nothing else", so the pricing arm can actually take the
authority away. ⭐ Both faces are exercised by `selftest()` below and by
`price_gates.sh`, because a discovery function that has only ever been seen
succeed is the same unknown-strength artefact as an audit that has never
rejected anything.

⛔ pyRTA is NOT vendored. It is third-party source and this repository is
published. Point PYRTA_SRC at a clone's `src/`:

    git clone https://github.com/PROSA-Project/pyRTA
    PYRTA_SRC=<clone>/src python model/a2/gate_pyrta.py
"""

from __future__ import annotations

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ENV = "PYRTA_SRC"
CLONE_URL = "https://github.com/PROSA-Project/pyRTA"

# The marker that makes a directory a pyRTA `src/` and not a directory named src.
_MARKER = "response_time_analysis"


def _is_pyrta_src(path: str) -> bool:
    return bool(path) and os.path.isdir(os.path.join(path, _MARKER))


def find_pyrta() -> str | None:
    """The clone's `src/`, or None. See the module docstring for the contract."""
    raw = os.environ.get(ENV)
    if raw is not None:
        # EXPLICIT: honour it exactly, including the refusal. No fallback --
        # that is what makes `price_gates.sh` able to remove the authority.
        return raw if _is_pyrta_src(raw) else None
    for base in (os.environ.get("TEMP", ""), os.path.expanduser("~")):
        if not base or not os.path.isdir(base):
            continue
        for root, dirs, _ in os.walk(base):
            if os.path.basename(root).lower() == "pyrta" and "src" in dirs:
                cand = os.path.join(root, "src")
                if _is_pyrta_src(cand):
                    return cand
            if root.count(os.sep) - base.count(os.sep) > 6:
                dirs[:] = []
    return None


# ===========================================================================
# P6 -- PROVENANCE: WHICH pyRTA, NOT JUST WHERE
# ===========================================================================
# ⛔⛔ THE PRIMARY FOREIGN AUTHORITY FOR EVERY TIMING CLAIM WAS PICKED UP FROM
# A SCRATCH DIRECTORY WITH NO RECORDED COMMIT. `find_pyrta()` answers "is there
# a pyRTA src/ here"; nothing answered "which pyRTA". A witness whose version is
# unknown is an unverified witness: a pyRTA change between two runs would move
# every bound it certifies, and the record could not say whether it had.
# ⇒ The commit is PINNED here, and `pinned_pyrta()` returns a clone only if it
#   is a clean git checkout of exactly this commit -- or the run DECLARES the
#   difference by name in `PYRTA_DECLARED`, which every gate then prints.
# ⭐ WHY THIS COMMIT: it is the clone the ruling-S budgets and the C = 3
#   re-quote were re-derived against in this arc, and re-running `gate_pyrta`
#   at it reproduces ledger entry `65bc3c8114e5`'s numbers exactly
#   (r = {16, 12, 7, 15, 9}) -- see `lane_digest.PYRTA_PIN`. ⚠ That is a
#   REPRODUCTION, not a claim about which clone produced the entry first: the
#   earlier clone's commit was never recorded, which is the defect this fixes.
PINNED_COMMIT = "1f3a649ced61709620857ec28653b51a0c6ce28d"
PINNED_DATE = "2026-06-16"           # its commit date, for the reader
DECLARE_ENV = "PYRTA_DECLARED"        # "<commit|UNKNOWN>: <reason>"


def provenance(src: str):
    """(commit, dirty) for the clone owning `src`, or (None, None) if not git.

    ⚠ `dirty` covers TRACKED changes only: a modified pyRTA file means the code
    that ran is not the commit's, so the commit alone no longer identifies it.
    """
    import subprocess
    root = os.path.dirname(os.path.abspath(src))
    try:
        head = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=20)
        if head.returncode != 0:
            return None, None
        st = subprocess.run(["git", "-C", root, "status", "--porcelain",
                             "--untracked-files=no"],
                            capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None, None
    return head.stdout.strip(), bool(st.stdout.strip())


def dirty_files(src: str):
    """The clone's modified / deleted TRACKED files, as `git status` names them."""
    import subprocess
    root = os.path.dirname(os.path.abspath(src))
    try:
        st = subprocess.run(["git", "-C", root, "status", "--porcelain",
                             "--untracked-files=no"],
                            capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return []
    return [ln.strip() for ln in st.stdout.splitlines() if ln.strip()]


def judge(src: str, declared: str | None):
    """(ok, label) for one clone. Pure, so the must-fire can price it."""
    commit, dirty = provenance(src)
    ident = commit or "UNKNOWN"
    if commit == PINNED_COMMIT and not dirty:
        return True, "PINNED %s (%s)" % (commit[:12], PINNED_DATE)
    if dirty:
        ident = "%s+LOCAL-CHANGES" % (commit or "UNKNOWN")
    if declared:
        want = declared.split(":", 1)[0].strip()
        why = declared.split(":", 1)[1].strip() if ":" in declared else ""
        if want and (want == ident or (commit and want == commit and not dirty)):
            if not why:
                return False, ("%s is DECLARED without a reason -- a declaration "
                               "is only worth printing if it says why" % ident)
            return True, "DECLARED %s -- %s" % (ident[:20], why)
    # ⛔ DIRTY IS NOT A COMMIT MISMATCH, and the message used to say it was:
    # "UNPINNED 1f3a649ced6170962085, pin is 1f3a649ced61" when the commit WAS
    # the pin and one tracked file (py.typed) had been deleted from the clone.
    # A reader chases the wrong cause. Named separately, with the files.
    if commit == PINNED_COMMIT and dirty:
        files = dirty_files(src)
        return False, ("DIRTY: the clone IS the pinned commit %s, but %d tracked "
                       "file(s) differ from it: %s. Restore them (git -C <clone> "
                       "checkout -- <file>) -- and find what changed them." % (
                           PINNED_COMMIT[:12], len(files), "; ".join(files[:6])))
    return False, ("UNPINNED %s, pin is %s. Check out the pin, or set %s="
                   "\"%s: <reason>\" to run this copy on purpose."
                   % (ident[:20], PINNED_COMMIT[:12], DECLARE_ENV, ident))


def pinned_pyrta(quiet: bool = False):
    """`find_pyrta()`, but only a PINNED (or declared) clone counts.

    ⛔ An unpinned copy is returned as None -- the same as no pyRTA at all --
    so every caller's existing "pyRTA absent" path takes over: the
    pyRTA-primary gates go RED, and the CI-side derivations fall back to their
    own recurrence and say so. Nothing downstream needs to know about pins.
    """
    src = find_pyrta()
    if not src:
        return None
    ok, label = judge(src, os.environ.get(DECLARE_ENV))
    if not quiet:
        print("  pyRTA: %s" % src)
        print("  pyRTA commit: %s" % label)
    if not ok:
        if quiet:
            print("  pyRTA REFUSED: %s" % label)
        return None
    return src


def require_pyrta(gate: str) -> str | None:
    """find_pyrta(), but it prints the RED paragraph the gates all printed.

    Returns the src path, or None after explaining why the gate is red. The
    caller returns non-zero; this function never exits, so a caller can still
    run its tool-independent arms before failing.
    ⭐ P6: it now also prints the clone's COMMIT, and refuses an unpinned one.
    """
    src = find_pyrta()
    if src:
        ok, label = judge(src, os.environ.get(DECLARE_ENV))
        print("  pyRTA source: %s" % src)
        print("  pyRTA commit: %s" % label)
        if ok:
            return src
        print("  *** pyRTA REFUSED -- %s is RED. An unpinned witness is an" % gate)
        print("      unverified one: the bounds it certifies would move with")
        print("      a pyRTA change and the record could not say whether.")
        return None
    raw = os.environ.get(ENV)
    print("  *** pyRTA NOT FOUND -- %s is RED." % gate)
    if raw is None:
        print("      %s is unset and no clone was found under TEMP or ~." % ENV)
    else:
        print("      %s is set to %r, which is not a pyRTA src/ directory" % (ENV, raw))
        print("      (no %s/ inside it). An explicit setting is honoured" % _MARKER)
        print("      exactly, so no fallback search was attempted.")
    print("      git clone %s" % CLONE_URL)
    print("      %s=<clone>/src python model/a2/%s" % (ENV, gate))
    print("  A foreign check that cannot run has not run.")
    return None


# ============================================================================
def selftest() -> int:
    """BOTH FACES. A discovery function seen only to succeed is unmeasured.

    ⛔ The must-fire face is the one that matters: with PYRTA_SRC set to a path
    that is not a pyRTA src/, discovery MUST return None even though a real
    clone may be sitting in TEMP. If it does not, `price_gates.sh` cannot take
    the authority away from any gate that uses this module, and every pyRTA
    gate silently becomes unpriceable.
    """
    print()
    print("=" * 78)
    print("SPEC H1 -- pyRTA discovery, both faces")
    print("=" * 78)
    saved = os.environ.get(ENV)
    rc = 0
    try:
        # --- face 1: tool present ---------------------------------------
        # ⛔ Honour a VALID explicit setting; only clear an unset or invalid one
        # so the search path gets its chance. Unconditionally popping it would
        # red this gate on any machine whose clone lives outside TEMP and ~ --
        # i.e. it would fail for the one deployment the env var exists to serve.
        how = "explicit"
        if not _is_pyrta_src(saved or ""):
            os.environ.pop(ENV, None)
            how = "unset, search allowed"
        found = find_pyrta()
        print("  face 1  PYRTA_SRC %s -> %s" % (how, found or "NOT FOUND"))
        if not found:
            print("    *** FACE 1 UNEXERCISED: no clone found, so the SUCCESS")
            print("        path of this function has not run. That is a red, not")
            print("        a caveat -- a discovery function only ever seen to")
            print("        refuse is exactly as unmeasured as one only ever seen")
            print("        to succeed, and it is the half that `price_gates.sh`")
            print("        cannot supply. Clone pyRTA and re-run.")
            rc = 1
        else:
            print("    marker present (%s/): yes" % _MARKER)

        # --- face 2: the must-fire -- explicit bad path refuses ----------
        os.environ[ENV] = os.path.join(os.sep, "nonexistent", "not-a-tool")
        blocked = find_pyrta()
        print("  face 2  PYRTA_SRC=/nonexistent/not-a-tool -> %s"
              % (blocked or "None (refused)"))
        if blocked is not None:
            print("    *** FAIL: an explicit non-directory did NOT refuse. The")
            print("        fallback search ran anyway, so no pyRTA gate can be")
            print("        priced and every one of them is unmeasured. ***")
            rc = 1
        else:
            print("    MUST-FIRE PASSED -- the authority can be removed, so every")
            print("    gate built on this module is priceable.")

        # --- face 3: a directory that exists but is not pyRTA ------------
        os.environ[ENV] = os.path.dirname(os.path.abspath(__file__))
        wrong = find_pyrta()
        print("  face 3  PYRTA_SRC=<this repo's model/a2> -> %s"
              % (wrong or "None (refused)"))
        if wrong is not None:
            print("    *** FAIL: a directory with no %s/ was accepted; the")
            print("        marker check is not doing anything. ***" % _MARKER)
            rc = 1
        else:
            print("    refused on the marker, not on existence -- a real directory")
            print("    that is not pyRTA is still not pyRTA.")

        # --- face 4 (P6): WHICH pyRTA -- the pin, priced ---------------------
        # ⛔ A COPY WITH NO RECORDED COMMIT must be refused, which is exactly the
        # state the timing witness was in before P6. Built as a real pyRTA-shaped
        # directory OUTSIDE any git repo, so `find_pyrta` would accept it and
        # only the provenance check can turn it away.
        import shutil
        import tempfile
        print("  face 4  the pin (P6)")
        if found:
            ok, label = judge(found, None)
            print("    the real clone                      -> %s" % label)
            if not ok:
                print("    *** the clone in use is NOT the pin -- every")
                print("        pyRTA-primary gate will refuse it")
                rc = 1
        fake = tempfile.mkdtemp(prefix="pyrta_unpinned_")
        try:
            fsrc = os.path.join(fake, "src")
            os.makedirs(os.path.join(fsrc, _MARKER))
            for label_, decl, want in (
                    ("a copy with NO commit, undeclared", None, False),
                    ("... declared by name with a reason",
                     "UNKNOWN: selftest fixture", True),
                    ("... declared with NO reason", "UNKNOWN", False)):
                ok, why = judge(fsrc, decl)
                good = ok == want
                print("    %-38s -> %s" % (label_, "accepted" if ok else "refused"))
                if not good:
                    print("      *** wanted %s: %s"
                          % ("acceptance" if want else "refusal", why))
                    rc = 1
        finally:
            shutil.rmtree(fake, ignore_errors=True)
    finally:
        if saved is None:
            os.environ.pop(ENV, None)
        else:
            os.environ[ENV] = saved
    print()
    print("  GATE H1: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(selftest())
