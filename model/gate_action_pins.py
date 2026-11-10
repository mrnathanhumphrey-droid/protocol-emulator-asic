"""GATE action-pins -- every TinyTapeout action and every flow pin is immutable
(Wilson 11-10, option (ii)).

WHY. The harden of record must run what was measured, and precheck judges on
TT's release. A branch ref resolves to whatever the branch holds on the day
(the docs and FPGA workflows followed `@ihp-cmos5l` until 11-10), and a TAG can
be moved too. So every reference that decides what the flow runs is a full
40-hex commit SHA, and every tool version is an exact release.

SCOPE (option (ii)): TinyTapeout actions and the flow pins only. GitHub's own
actions (actions/checkout@v6, ...) are out of scope by ruling.

THE RULES, over .github/workflows/*.yaml and ci/pdk.sha:
  * `uses: TinyTapeout/<anything>@<ref>`   -> ref is 40 hex
  * `tools-ref: <ref>`                     -> 40 hex
  * `TT_REF: <ref>`                        -> 40 hex
  * `librelane-version:` / `LL_VER:`       -> an exact version (3.1.0.dev4),
                                              never a range, `main` or empty
  * ci/pdk.sha                             -> one 40-hex line
MUST-FIRES: a workflow line set to `@ttihp27a` (a tag); `tools-ref: main` (a
branch); `LL_VER: 3.1` (not exact); `TT_REF` abbreviated to 7 hex.
POSITIVE TOKEN: `GATE action-pins: PASSED`.
"""

from __future__ import annotations

import glob
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WF_GLOB = os.path.join(ROOT, ".github", "workflows", "*.y*ml")
PDK_SHA = os.path.join(ROOT, "ci", "pdk.sha")

SHA40 = re.compile(r"[0-9a-f]{40}")
EXACT_VER = re.compile(r"\d+\.\d+\.\d+(?:\.(?:dev|rc|post)\d+)?")

# (name, line regex capturing the value, value rule, what the rule says)
RULES = [
    ("TinyTapeout action", re.compile(r"^\s*-?\s*uses:\s*(TinyTapeout/\S+?)@(\S+)"), SHA40,
     "a 40-hex commit SHA (a tag or branch can be moved)"),
    ("tools-ref", re.compile(r"^\s*()tools-ref:\s*['\"]?([^'\"\s#]*)"), SHA40,
     "a 40-hex commit SHA"),
    ("TT_REF", re.compile(r"^\s*()TT_REF:\s*['\"]?([^'\"\s#]*)"), SHA40,
     "a 40-hex commit SHA"),
    ("librelane-version", re.compile(r"^\s*()librelane-version:\s*['\"]?([^'\"\s#]*)"),
     EXACT_VER, "an exact release (e.g. 3.1.0.dev4)"),
    ("LL_VER", re.compile(r"^\s*()LL_VER:\s*['\"]?([^'\"\s#]*)"), EXACT_VER,
     "an exact release (e.g. 3.1.0.dev4)"),
]


def audit(files):
    """files: {relpath: text} -> ([problem], {rule name: count seen})."""
    probs, seen = [], {r[0]: 0 for r in RULES}
    for rel in sorted(files):
        if rel.replace("\\", "/").endswith("ci/pdk.sha"):
            body = files[rel].strip()
            if not SHA40.fullmatch(body):
                probs.append("%s is %r -- want one 40-hex IHP-Open-PDK commit" % (rel, body[:50]))
            continue
        for n, line in enumerate(files[rel].splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            for name, rx, rule, says in RULES:
                m = rx.match(line)
                if not m:
                    continue
                seen[name] += 1
                val = m.group(2)
                if not rule.fullmatch(val):
                    what = (m.group(1) + "@") if m.group(1) else ""
                    probs.append("%s:%d %s %s%s -- must be %s"
                                 % (rel, n, name, what, val or "<empty>", says))
    return probs, seen


def load():
    files = {}
    for p in sorted(glob.glob(WF_GLOB)):
        with open(p, encoding="utf-8") as fh:
            files[os.path.relpath(p, ROOT).replace(os.sep, "/")] = fh.read()
    with open(PDK_SHA, encoding="ascii") as fh:
        files["ci/pdk.sha"] = fh.read()
    return files


def mutate(files, rel, pat, rep):
    f = dict(files)
    new = re.sub(pat, rep, f[rel], count=1, flags=re.M)
    if new == f[rel]:
        return None
    f[rel] = new
    return f


def main():
    print("GATE action-pins: TinyTapeout actions and flow pins are SHAs / exact versions")
    try:
        files = load()
    except OSError as e:
        print("  *** COULD NOT RUN: %s" % e)
        print("  GATE action-pins: COULD NOT RUN")
        return 1
    probs, seen = audit(files)
    for name in sorted(seen):
        print("  %-20s %d pinned reference(s)" % (name, seen[name]))
    rc = 0
    # a gate that saw nothing is not a pass: the GDS flow must be found
    for need in ("TinyTapeout action", "tools-ref", "TT_REF", "LL_VER", "librelane-version"):
        if seen[need] == 0:
            probs.append("no %s found in .github/workflows -- the rule checked nothing" % need)
    for p in probs:
        print("  *** " + p)
    rc |= 1 if probs else 0

    print("  --- must-fire ---")
    muts = [
        ("a TT action set to @ttihp27a (a tag)", ".github/workflows/gds.yaml",
         r"(uses:\s*TinyTapeout/tt-gds-action)@\S+", r"\1@ttihp27a", "TinyTapeout action"),
        ("docs action set to @ttihp27a", ".github/workflows/docs.yaml",
         r"(uses:\s*TinyTapeout/\S+?)@\S+", r"\1@ttihp27a", "TinyTapeout action"),
        ("tools-ref: main (a branch)", ".github/workflows/gds.yaml",
         r"(tools-ref:\s*)\S+", r"\1main", "tools-ref"),
        ("LL_VER: 3.1 (not exact)", ".github/workflows/v2_canary.yaml",
         r"(LL_VER:\s*)\S+", r"\g<1>3.1", "LL_VER"),
        ("TT_REF abbreviated to 7 hex", ".github/workflows/v2_canary.yaml",
         r"(TT_REF:\s*)([0-9a-f]{7})[0-9a-f]+", r"\1\2", "TT_REF"),
        ("ci/pdk.sha a branch name", "ci/pdk.sha", r"^.*$", "main", "ci/pdk.sha"),
    ]
    for label, rel, pat, rep, needle in muts:
        f = mutate(files, rel, pat, rep)
        if f is None:
            print("    %-40s *** MUTATION DID NOT APPLY" % label)
            rc |= 1
            continue
        mp, _ = audit(f)
        hit = any(needle in p for p in mp)
        print("    %-40s %s" % (label, "red  ok" if hit else "*** STAYED GREEN"))
        rc |= 0 if hit else 1
    print()
    print("  GATE action-pins: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
