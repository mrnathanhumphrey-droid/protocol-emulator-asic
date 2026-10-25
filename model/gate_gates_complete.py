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
    "model/gate_ln1_record.py":
        "OWED, NOT RETIRED (10-25): it checks model/ln1_of_record.json, which "
        "exists only after the next 200k LN1 dispatch with --record. It joins "
        "GATES in the commit that adds that record -- this entry then goes "
        "STALE (red) and is removed in the same commit.",
}

#: ⛔⛔ RULING CJ -- gate files RETIRED because every claim they made now lives
#: in a gate that RUNS. Kept on disk for their history (nothing is deleted);
#: each must carry a `RETIRED` banner in its header so nobody reads a stale
#: verdict as live, must not be in a run list, and every successor named here
#: must itself be run -- a pointer to a gate nothing runs is no pointer.
#: file -> ([successor gate files], the per-claim pointer)
RETIRED = {
    "model/a2/gate_cj_bounds.py": (
        ["model/a2/gate_c3_requote.py", "model/a2/gate_j_program.py",
         "model/a2/gate_dmin_clocked.py", "test/gate_coverage.py"],
        "C_max = 2 is OCCUPANCY; RTA charges the SPACING C = 3 -> "
        "gate_c3_requote + run_csat (ledger 65bc3c8114e5). Universal J_max = 8 "
        "is WITHDRAWN -> the scoped d_min >= D* = 20 -> J = 1 in "
        "gate_j_program / gate_dmin_clocked (ledger b4e51034e283). Opcode "
        "coverage 8/8 (its census input was written by five_image, so it was "
        "red) -> the coverage sweep, gate_coverage. The double-buffer "
        "pre-registration (2, measured 7) -> bursty.DOUBLE_BUFFER_PREREG, a "
        "LEDGER site in gate_stored_numbers. Its J = 0..10 margin table is "
        "pre-C = 3 -> gate_c3_requote."),
}
RETIRED_BANNER = "RETIRED (ruling CJ)"


def _norm(p):
    return os.path.normpath(p).replace(os.sep, "/")


def _head(rel, n=12):
    """The first `n` lines of a file -- where a RETIRED banner must sit."""
    try:
        with io.open(os.path.join(ROOT, rel), encoding="utf-8",
                     errors="replace") as fh:
            return "".join(fh.readline() for _ in range(n))
    except OSError:
        return ""


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


def audit(files, ci, a2, excluded, retired=None, read=None):
    """(unlisted, stale) -- both must be empty."""
    retired = RETIRED if retired is None else retired
    unlisted = sorted(f for f in files
                      if f not in ci and f not in a2 and f not in excluded
                      and f not in retired)
    stale = []
    for f, (succ, _why) in sorted(retired.items()):
        if f not in files:
            stale.append("%s is RETIRED but does not exist" % f)
            continue
        if f in ci or f in a2:
            stale.append("%s is RETIRED and ALSO run -- a retired verdict is "
                         "not evidence" % f)
        head = (read or _head)(f)
        if RETIRED_BANNER not in head:
            stale.append("%s is RETIRED but its header lacks %r -- a reader "
                         "would take its verdict as live" % (f, RETIRED_BANNER))
        for s in succ:
            if s not in ci and s not in a2:
                stale.append("%s points at successor %s, which nothing runs"
                             % (f, s))
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
    for f, (succ, why) in sorted(RETIRED.items()):
        print("  RETIRED   %s" % f)
        print("            successors (all run): %s" % ", ".join(succ))
        print("            %s" % why)

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
    # ⛔ RULING CJ's retirement, priced three ways
    f0 = next(iter(RETIRED))
    _u, s4 = audit(files, ci, a2, EXCLUDED, read=lambda r: "no banner here")
    hit3 = any("lacks" in x for x in s4)
    print("    a retired gate without its banner            %s"
          % ("ok" if hit3 else "*** MISSED"))
    _u, s5 = audit(files, ci | {f0}, a2, EXCLUDED)
    hit4 = any("ALSO run" in x for x in s5)
    print("    a retired gate still in a run list           %s"
          % ("ok" if hit4 else "*** MISSED"))
    r6 = {f0: (["test/gate_nobody_runs.py"], "fixture")}
    _u, s6 = audit(files, ci, a2, EXCLUDED, retired=r6)
    hit5 = any("which nothing runs" in x for x in s6)
    print("    a successor nothing runs                     %s"
          % ("ok" if hit5 else "*** MISSED"))
    if not (hit and hit2 and hit3 and hit4 and hit5):
        rc = 1

    print()
    print("=" * 78)
    print("  GATE gates-complete: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
