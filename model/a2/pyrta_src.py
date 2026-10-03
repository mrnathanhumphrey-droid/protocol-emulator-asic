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


def require_pyrta(gate: str) -> str | None:
    """find_pyrta(), but it prints the RED paragraph the gates all printed.

    Returns the src path, or None after explaining why the gate is red. The
    caller returns non-zero; this function never exits, so a caller can still
    run its tool-independent arms before failing.
    """
    src = find_pyrta()
    if src:
        print("  pyRTA source: %s" % src)
        return src
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
