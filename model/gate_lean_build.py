#!/usr/bin/env python3
"""gate_lean_build -- the Lean proofs, built and audited in CI (Wilson 11-12, approved).

  1. `lake build` in lean/JLane exits 0
  2. no `sorry` token in lean/JLane/JLane/*.lean outside comments
  3. no `axiom` declaration in those sources
  4. `#print axioms` for every theorem in KEY (the published results) -- run through
     `lake env lean` on a generated file, because a CACHED `lake build` prints no axiom lines
     and their absence would read as a pass. Every KEY theorem must REPORT (presence, not
     absence), and its axioms must be a subset of ALLOWED.
ALLOWED = {propext, Quot.sound}. Classical.choice is NOT allowed: the build does not depend on
it today (11-12, measured), and admitting it needs a ruling with its reason.

MUST-FIRES, on a temporary copy of the tree:
  M_LEAN_SORRY   a theorem proved by `sorry` appended to SelfTimed.lean   -> check 2 red
  M_LEAN_AXIOM   an axiom, and a KEY-listed theorem that uses it           -> checks 3 and 4 red
Both are judged by the same `judge` as the clean arm (gate_meta's stub on it turns the gate red).

POSITIVE TOKEN: `GATE lean-build: PASSED`.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LEAN = os.path.join(ROOT, "lean", "JLane")
ALLOWED = {"propext", "Quot.sound"}
#: the published results: what the README / notes claim was proved (SPEC, not a measurement)
KEY = ("dstar", "dstar29", "dstar39", "dstar39_v2", "dstar39_st", "dstar39_hold",
       "hold_window", "runH_nohold", "runH_coinc", "step2_proj", "step2_proj_st",
       "run2_proj_st", "holdCycles_meets")
PLANT_THM = "planted_by_gate"
#: gate_mutant_kills' scratch-mutant registry (ruling AC2): this gate is the killer
SCRATCH_MUTANTS = {
    "M_LEAN_SORRY": "a theorem proved by `sorry`, planted in a temp copy of the tree",
    "M_LEAN_AXIOM": "an axiom and a theorem using it, planted in a temp copy of the tree",
}


def _strip_comments(src):
    src = re.sub(r"/-.*?-/", " ", src, flags=re.S)
    return re.sub(r"--[^\n]*", " ", src)


def scan(tree):
    """-> (sorry hits, axiom declarations), outside comments."""
    s, a = [], []
    d = os.path.join(tree, "JLane")
    for f in sorted(os.listdir(d)):
        if not f.endswith(".lean"):
            continue
        body = _strip_comments(open(os.path.join(d, f), encoding="utf-8").read())
        if re.search(r"\bsorry\b", body):
            s.append(f)
        if re.search(r"(?m)^\s*axiom\s", body):
            a.append(f)
    return s, a


def axioms(tree, names):
    """-> ({name: [axioms]}, missing names, raw output)."""
    fd, path = tempfile.mkstemp(suffix=".lean", prefix="gate_lean_axioms_")
    with os.fdopen(fd, "w") as fh:
        fh.write("import JLane\n" + "".join("#print axioms JLane.%s\n" % n for n in names))
    try:
        r = subprocess.run(["lake", "env", "lean", path], cwd=tree, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    finally:
        os.remove(path)
    out = r.stdout + r.stderr
    got = {}
    for m in re.finditer(r"'JLane\.(\w+)' depends on axioms: \[([^\]]*)\]", out):
        got[m.group(1)] = [x.strip() for x in m.group(2).split(",") if x.strip()]
    for m in re.finditer(r"'JLane\.(\w+)' does not depend on any axioms", out):
        got[m.group(1)] = []
    return got, [n for n in names if n not in got], out


def judge(tree, names=KEY):
    probs = []
    r = subprocess.run(["lake", "build"], cwd=tree, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return ["lake build failed: %s" % (r.stdout + r.stderr)[-300:]], {}
    s, a = scan(tree)
    if s:
        probs.append("`sorry` in %s" % ", ".join(s))
    if a:
        probs.append("an `axiom` declaration in %s" % ", ".join(a))
    got, missing, raw = axioms(tree, names)
    if missing:
        probs.append("no axiom report for %s (%s)" % (", ".join(missing), raw.strip()[-200:]))
    for n, ax in sorted(got.items()):
        extra = set(ax) - ALLOWED
        if extra:
            probs.append("%s depends on %s, outside {%s}" % (n, sorted(extra), ", ".join(sorted(ALLOWED))))
    return probs, got


def _mutant_tree(kind):
    tmp = tempfile.mkdtemp(prefix="gate_lean_%s_" % kind)
    dst = os.path.join(tmp, "JLane")
    shutil.copytree(LEAN, dst)                    # .lake included: an incremental rebuild
    p = os.path.join(dst, "JLane", "SelfTimed.lean")
    src = open(p, encoding="utf-8").read().rstrip()
    assert src.endswith("end JLane")
    if kind == "sorry":
        plant = "theorem %s : (1 : Nat) = 2 := sorry\n" % PLANT_THM
    else:
        plant = "axiom planted_axiom : (1 : Nat) = 2\ntheorem %s : (1 : Nat) = 2 := planted_axiom\n" % PLANT_THM
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(src[:-len("end JLane")] + plant + "\nend JLane\n")
    return tmp, dst


def main() -> int:
    print("Lean build audit: lean/JLane, %d published theorems, axioms within {%s}"
          % (len(KEY), ", ".join(sorted(ALLOWED))))
    probs, got = judge(LEAN)
    for n in KEY:
        print("    %-18s %s" % (n, got.get(n, "*** NO REPORT")))
    for p in probs:
        print("  ***", p)
    for kind in ("sorry", "axiom"):
        tmp, tree = _mutant_tree(kind)
        try:
            mp, _ = judge(tree, KEY + (PLANT_THM,))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        # each arm must be killed by ITS check: the sorry scan, and the #print axioms limit
        # (not merely by the source grep for `axiom`)
        want = "`sorry` in" if kind == "sorry" else "outside {"
        hit = [p for p in mp if want in p]
        red = bool(hit)
        print("  must-fire M_LEAN_%-6s %s  %s" % (kind.upper(), "RED (killed)" if red else "*** SURVIVED",
                                                  (hit[0] if hit else (mp[0] if mp else ""))[:100]))
        if not red:
            probs.append("must-fire M_LEAN_%s survived" % kind.upper())
    if probs:
        print("GATE lean-build: FAILED (%d)" % len(probs))
        return 1
    print("GATE lean-build: PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
