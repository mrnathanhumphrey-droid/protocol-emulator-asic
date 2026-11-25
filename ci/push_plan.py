"""THE PUSH PLAN -- which test shards a push needs, from what it changed (Nathan + Wilson 11-25).

The 11-15 account suspension coincided with 63-64 test jobs per push (11 shards + 47 meta-seams, all at
once). A push now runs ONE runner at a time, and only the shards its changes call for:

    docs/** or *.md only            -> no shard (docs.yaml builds the datasheet)
    src/** or info.yaml (the RTL)   -> every shard (the full simulation set) + fast
    lean/**                         -> lean + fast
    model/** test/** fpga/** host/** a gate or bench file
                                    -> the shard that owns that file in ci/shards.txt + fast
                                       (a file no shard owns -> fast)
    anything else (ci/, .github/, scripts)
                                    -> fast
The chosen shards run IN SEQUENCE. If their measured minutes (ci/ci_chunks.json "minutes") exceed one job's
budget they are split into consecutive chunks, still one runner at a time (test.yaml: max-parallel 1).
The 47 slow meta-seams never run on a push; they are the dispatched full suite's.

    python ci/push_plan.py <base_sha> <head_sha>     -> prints  shards=[...]  and  chunks=[...]  (GitHub output)
    python ci/push_plan.py --files f1 f2 ...         -> the same, for a given file list (tests / gate)
A base of all zeros (a new branch) or an unknown base plans the full set: no change list, no shortcut.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def shard_map():
    owner, order = {}, []
    for line in open(os.path.join(HERE, "shards.txt"), encoding="utf-8"):
        p = line.split("#")[0].split()
        if len(p) >= 2:
            owner[p[1]] = p[0]
            if p[0] not in order:
                order.append(p[0])
    return owner, order


def plan(files):
    owner, order = shard_map()
    need = set()
    for f in files:
        f = f.replace("\\", "/")
        if f.startswith("docs/") or f.endswith(".md"):
            continue
        elif f.startswith("src/") or f == "info.yaml":
            need |= set(order)
        elif f.startswith("lean/"):
            need.add("lean")
        elif f.startswith(("model/", "test/", "fpga/", "host/")):
            need.add(owner.get(f, "fast"))
        else:
            need.add("fast")
    if need:
        need.add("fast")
    return [s for s in order if s in need]


def chunks(shards):
    c = json.load(open(os.path.join(HERE, "ci_chunks.json"), encoding="utf-8"))
    mins, budget = c["minutes"], c["job_budget_min"]
    out, cur, t = [], [], 0
    for s in sorted(shards, key=lambda s: -mins.get(s, 60)):
        m = mins.get(s, 60)
        if cur and t + m > budget:
            out.append(cur); cur, t = [], 0
        cur.append(s); t += m
    if cur:
        out.append(cur)
    return [{"name": "push-%d" % (i + 1), "shards": " ".join(ch)} for i, ch in enumerate(out)]


def changed(base, head):
    if not base or set(base) == {"0"}:
        return None
    r = subprocess.run(["git", "-C", ROOT, "diff", "--name-only", base, head], capture_output=True, text=True)
    return r.stdout.split() if r.returncode == 0 else None


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "--files":
        files = a[1:]
    else:
        files = changed(a[0] if a else "", a[1] if len(a) > 1 else "HEAD")
        if files is None:                      # new branch / unknown base: the full set
            files = ["src/"]
            print("no usable base: planning the full shard set", file=sys.stderr)
    sh = plan(files)
    print("shards=" + json.dumps(sh))
    print("chunks=" + json.dumps(chunks(sh)))
