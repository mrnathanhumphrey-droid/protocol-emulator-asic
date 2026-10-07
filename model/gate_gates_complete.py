"""EVERY GATE FILE IS RUN SOMEWHERE, OR EXCLUDED BY NAME WITH A REASON.

⛔⛔ WHY THIS EXISTS (ruling Q2). `test/gate_corpus_trace.py` -- the
two-simulator corpus witness -- could not BUILD from `7a672b0` until ruling Q2,
and nothing noticed, because it was in NO list. It was not fail-open: it
returned 1 on a build failure. It was UNRUN. A correct gate that nobody invokes
is the fifth check-that-could-not-fire in this arc, in a new shape: not a check
that cannot see its subject, but a check nothing listens to.

⇒ Every `model/**/gate_*.py` and `test/**/gate_*.py` must be one of:

    * in `ci/run_gates.sh`'s GATES      -- run on every push;
    * in `model/a2/run_a2.py`'s GATES   -- the pyRTA / by-hand family, run at
                                           each checkpoint (pyRTA is not
                                           vendored, so these cannot be in CI);
    * in `EXCLUDED` below, BY NAME, with a reason.

⛔ NOT A PATTERN EXEMPTION. "Anything under `ta01/` is historical" is how a new
gate gets dropped in silently; each exclusion is a claim about one file. And a
STALE entry -- a listed file that no longer exists, or an excluded file that is
now also in a run list -- is red, because then the list has stopped describing
the tree.
"""

from __future__ import annotations

import glob
import io
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

#: gate files deliberately run by NEITHER list, each with its reason.
#: ⛔ Keep these few and specific; a long list here is a list nobody reads.
EXCLUDED = {
    "model/gate_flow_netlist.py":
        "reads the HARDENING FLOW's post-synthesis netlist, which costs a "
        "~3.5-hour run, so it cannot be per-push or per-checkpoint; it runs "
        "after each harden (documented in ci/run_gates.sh's header).",
    # ⛔⛔ RED, AND EXCLUDED ONLY SO THE LIST DESCRIBES THE TREE -- NOT BECAUSE
    # IT IS FINE. Found by this gate's first run: no harness had invoked it
    # since `cb7f376`. It FAILS today, for a reason it reports correctly: its
    # census-coverage claim reads `test/cj_measured_alt.txt`, an UNTRACKED
    # scratch file whatever ran last overwrote (it was last written by a
    # `five_image` run), so its own provenance check refuses the claim. Its
    # live content -- J as a derived function of the program -- is carried by
    # `gate_j_program` and `gate_dmin_clocked`. OWED: either give its input a
    # recipe and track it, or retire the gate. That is a decision, recorded.
    "model/a2/gate_cj_bounds.py":
        "RED -- owed. Reads UNTRACKED test/cj_measured_alt.txt (last written "
        "by five_image), so its own provenance check refuses its census claim. "
        "Unrun since cb7f376; live J content is in gate_j_program / "
        "gate_dmin_clocked. Fix its input recipe or retire it.",
}


def _norm(p):
    return os.path.normpath(p).replace(os.sep, "/")


def ci_gates(text=None):
    """The GATES array of `ci/run_gates.sh`, as repo-relative paths."""
    if text is None:
        with io.open(os.path.join(ROOT, "ci", "run_gates.sh"),
                     encoding="utf-8") as fh:
            text = fh.read()
    m = re.search(r"^GATES=\((.*?)^\)", text, re.S | re.M)
    if m is None:
        raise RuntimeError("ci/run_gates.sh has no GATES=( ... ) array, so "
                           "this gate cannot tell what CI runs")
    return {_norm(x) for x in
            re.findall(r"^\s+((?:model|test)/[\w/.-]+\.py)\s*$", m.group(1),
                       re.M)}


def a2_gates(text=None):
    """The GATES list of `model/a2/run_a2.py`, as repo-relative paths."""
    if text is None:
        with io.open(os.path.join(ROOT, "model", "a2", "run_a2.py"),
                     encoding="utf-8") as fh:
            text = fh.read()
    m = re.search(r"^GATES = \[(.*?)^\]", text, re.S | re.M)
    if m is None:
        raise RuntimeError("model/a2/run_a2.py has no GATES = [ ... ] list")
    return {_norm(os.path.join("model", "a2", x)) for x in
            re.findall(r'\(\s*"([\w./-]+\.py)"', m.group(1))}


def ta02_gates(a2):
    """The gates `model/ta02/run_ta02.py` runs -- ONLY if that harness is run.

    ⛔ A HARNESS NOTHING INVOKES DOES NOT MAKE ITS GATES "RUN". `run_ta02.py`
    was reachable from nowhere until ruling Q2 added it to `run_a2.py`, so its
    list counts only while `run_a2.py` lists it -- otherwise its three gates
    would have read as covered one level up from the defect.
    """
    if "model/ta02/run_ta02.py" not in a2:
        return set()
    with io.open(os.path.join(ROOT, "model", "ta02", "run_ta02.py"),
                 encoding="utf-8") as fh:
        text = fh.read()
    return {_norm(os.path.join("model", "ta02", x)) for x in
            re.findall(r'os\.path\.join\(HERE,\s*"([\w.-]+\.py)"\)', text)}


def gate_files(root=ROOT):
    out = set()
    for pat in ("model/**/gate_*.py", "test/**/gate_*.py"):
        for p in glob.glob(os.path.join(root, pat), recursive=True):
            out.add(_norm(os.path.relpath(p, root)))
    return out


def audit(files, ci, a2, excluded):
    """(unlisted, stale) -- both must be empty."""
    unlisted = sorted(f for f in files
                      if f not in ci and f not in a2 and f not in excluded)
    stale = []
    for f in sorted(excluded):
        if f not in files:
            stale.append("%s is EXCLUDED but does not exist" % f)
        elif f in ci or f in a2:
            stale.append("%s is EXCLUDED and ALSO run -- drop the exclusion" % f)
    for f in sorted(ci):
        if not os.path.isfile(os.path.join(ROOT, f)):
            stale.append("ci/run_gates.sh lists %s, which does not exist" % f)
    return unlisted, stale


def main() -> int:
    print()
    print("=" * 78)
    print("  GATES COMPLETENESS -- every gate file is run, or excluded by name")
    print("=" * 78)
    files, ci, a2 = gate_files(), ci_gates(), a2_gates()
    a2 = a2 | ta02_gates(a2)
    print("  gate_*.py files on disk : %d" % len(files))
    print("  run on every push (CI)  : %d" % len(files & ci))
    print("  run by run_a2.py        : %d" % len(files & a2))
    print("  excluded by name        : %d" % len(set(EXCLUDED) & files))
    rc = 0
    unlisted, stale = audit(files, ci, a2, EXCLUDED)
    for f in unlisted:
        print("  *** %s is in NO run list and is not excluded." % f)
        print("      A gate nothing runs reports nothing -- add it to")
        print("      ci/run_gates.sh, to model/a2/run_a2.py, or to EXCLUDED")
        print("      here with the reason it should not run.")
        rc = 1
    for s in stale:
        print("  *** STALE: %s" % s)
        rc = 1
    for f, why in sorted(EXCLUDED.items()):
        if f in files:
            print("  excluded  %-40s %s" % (f, why[:60]))

    # ---- must-fire: an unlisted gate file is reported ------------------
    # ⛔ PRICED ON THE REAL LISTS, with one invented file added. A completeness
    # check that cannot see a new file is the defect it exists to catch.
    print()
    print("  --- must-fire ---")
    fake = "test/gate_never_listed_dummy.py"
    u2, _s2 = audit(files | {fake}, ci, a2, EXCLUDED)
    hit = fake in u2
    print("    an unlisted dummy gate file is reported      %s"
          % ("ok" if hit else "*** MISSED"))
    _u3, s3 = audit(files, ci, a2, dict(EXCLUDED, **{
        "test/gate_no_such_file.py": "a stale exclusion, for the must-fire"}))
    hit2 = any("gate_no_such_file" in x for x in s3)
    print("    a stale exclusion is reported                %s"
          % ("ok" if hit2 else "*** MISSED"))
    if not (hit and hit2):
        rc = 1

    print()
    print("=" * 78)
    print("  GATE gates-complete: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
