"""A SWEEP'S RECORD -- what it read, bound by blob hash (phase coverage, 10-25).

A timing bench whose full phase coverage is a SWEEP (model/phase_coverage.py,
class SWEEP) is covered only while the sweep's evidence still describes the
tree. The sweep writes a record: its result plus `inputs` = the files it read
and their set hash from GIT BLOBS (ci/blobhash.py). The phase-coverage gate
recomputes the hash at HEAD; a moved input makes the row PENDING.

⭐ THE INPUT SET, STATED AS A CONSERVATIVE SUPERSET (a sweep runs runners as
subprocesses, so their imports cannot be read off sys.modules):
  * the runners' STATIC import closure inside the repo (an AST walk -- it
    sees imports inside function bodies too), plus the sweep script itself;
  * every tracked src/*.v, test/*.v and test/*.vh (any bench or RTL file);
  * every tracked test/*.hex whose NAME appears in that closure's source.
Too wide only costs a re-run; too narrow would let a moved input pass.
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "ci"))
import blobhash                                    # noqa: E402

PATHS = [os.path.join(ROOT, d) for d in ("test", "model", os.path.join("model", "a2"), "ci")]


def _rel(p):
    return os.path.relpath(os.path.abspath(p), ROOT).replace(os.sep, "/")


def _resolve(name):
    """A top-level module name -> its repo file, or None (stdlib/site)."""
    for d in PATHS:
        p = os.path.join(d, name + ".py")
        if os.path.isfile(p):
            return p
    return None


def closure(scripts):
    """Repo files in the static import closure of `scripts` (repo-relative):
    every `import x` / `from x import y`, anywhere in the file (function
    bodies included), that resolves to a repo module on the runners' paths."""
    tracked = set(blobhash._git(["ls-files"])[1].decode().splitlines())
    todo = [os.path.join(ROOT, s) for s in scripts]
    seen = set()
    while todo:
        f = os.path.abspath(todo.pop())
        if f in seen:
            continue
        seen.add(f)
        with open(f, encoding="utf-8", errors="replace") as fh:
            tree = ast.parse(fh.read(), f)
        for n in ast.walk(tree):
            names = ([a.name for a in n.names] if isinstance(n, ast.Import) else
                     [n.module] if isinstance(n, ast.ImportFrom) and n.module
                     and not n.level else [])
            for nm in names:
                p = _resolve(nm.split(".")[0])
                if p:
                    todo.append(p)
    return sorted(p for p in (_rel(x) for x in seen) if p in tracked)


def inputs(scripts):
    tracked = set(blobhash._git(["ls-files"])[1].decode().splitlines())
    py = closure(scripts)
    text = ""
    for p in py:
        with open(os.path.join(ROOT, p), encoding="utf-8", errors="replace") as fh:
            text += fh.read()
    hexes = {"test/" + n for n in re.findall(r"\b([\w.-]+\.hex)\b", text)}
    hdl = {p for p in tracked if re.match(r"^(src/[^/]+\.v|test/[^/]+\.vh?)$", p)}
    return sorted(set(py) | hdl | (hexes & tracked))


def write(path, kind, result, scripts):
    files = inputs(scripts)
    dirty = blobhash.dirty(files)
    if dirty:
        raise SystemExit("*** sweep_record: inputs are uncommitted -- the record "
                         "would describe no commit: %s" % dirty[:5])
    rec = {"kind": kind,
           "sha": blobhash._git(["rev-parse", "HEAD"])[1].decode().strip(),
           "result": result,
           "inputs": {"files": files, "sha256": blobhash.set_hash(files)}}
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(rec, fh, indent=1)
        fh.write("\n")
    return rec
