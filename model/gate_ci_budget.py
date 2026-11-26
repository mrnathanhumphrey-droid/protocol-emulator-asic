"""THE CI BUDGET -- no push may fan out on GitHub again (Nathan + Wilson 11-25).

⛔⛔ WHY. The account was suspended 11-15 to 11-23. The Actions history (agent 1, 11-25) shows what changed:
the push-fired `test` workflow had grown, one edit at a time, from 1 job per push to 63-64 (11 shards + 47
meta-seams as matrix jobs, ~12 runner-hours per push); on 11-14 alone 127 runs, 4,114 jobs, 537 runner-hours,
at the 40-concurrent account limit for hours. The normal month before it: 1 test job per push, ~6 runner-
hours a day, at most 11 jobs at once -- and that is the activity GitHub said is fine. Each step of the drift
looked reasonable; nothing totalled it. This gate totals it, before every push.

⇒ B1  A harden never runs on a push: harden.yml has no push / pull_request / schedule trigger.
⇒ B2  In a workflow a push or pull request can start, every matrix job runs ONE leg at a time
      (strategy.max-parallel: 1) unless the job itself runs only on a manual dispatch.
⇒ B3  A push or pull request starts at most MAX_PUSH_JOBS jobs per workflow (jobs restricted to a manual
      dispatch do not count). A matrix job counts once here; B2 already holds it to one leg at a time.
⇒ B4  test.yaml plans its push through ci/push_plan.py (the shards a change calls for, run in sequence), and
      the plan itself behaves: a docs-only change runs nothing, an RTL change runs every shard, and every
      planned chunk fits one job's budget -- and so does every fixed DISPATCH chunk (ci_chunks.json).
⇒ B5  Every leg of test.yaml's `test` job may run as long as a planned chunk needs: its timeout-minutes (the
      smallest number in it, when it is an expression) is at least job_budget_min + SETUP_MARGIN_MIN. 3f18e0e
      planned push chunks up to 300 min under a 120-min push timeout; run 45715643365's push-1 (~270 min
      planned) was cancelled at 2h00m, mid Model gates -- no test went red, the verdict was just lost.
"""
from __future__ import annotations

import glob
import importlib.util
import os
import re
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_PUSH_JOBS = 6
PUSHY = ("push", "pull_request", "pull_request_target")
SETUP_MARGIN_MIN = 15


def triggers(doc):
    on = doc.get("on", doc.get(True, {}))
    if isinstance(on, str):
        return {on: None}
    if isinstance(on, list):
        return {k: None for k in on}
    return on or {}


def dispatch_only(job):
    cond = str(job.get("if", ""))
    return "workflow_dispatch" in cond and "!=" not in cond


def audit(name, text):
    """Return the problems with one workflow file (name, its YAML text)."""
    out = []
    doc = yaml.safe_load(text) or {}
    trig = triggers(doc)
    pushy = [t for t in trig if t in PUSHY]
    jobs = doc.get("jobs", {}) or {}
    base = os.path.basename(name)
    if base.startswith("harden") and (pushy or "schedule" in trig):
        out.append("B1 %s: a harden workflow is started by %s" % (base, ", ".join(pushy + (["schedule"] if "schedule" in trig else []))))
    if pushy:
        counted = 0
        for jn, j in jobs.items():
            if dispatch_only(j):
                continue
            counted += 1
            st = j.get("strategy") or {}
            if "matrix" in st and str(st.get("max-parallel", "")) != "1":
                out.append("B2 %s: job `%s` is a matrix a push can start with max-parallel %s (must be 1)"
                           % (base, jn, st.get("max-parallel", "unset")))
        if counted > MAX_PUSH_JOBS:
            out.append("B3 %s: a push can start %d jobs (> %d)" % (base, counted, MAX_PUSH_JOBS))
    return out


def plan_checks(root):
    out = []
    t = os.path.join(root, ".github", "workflows", "test.yaml")
    if os.path.exists(t) and "ci/push_plan.py" not in open(t, encoding="utf-8").read():
        out.append("B4 test.yaml: the push path does not go through ci/push_plan.py")
    pp = os.path.join(root, "ci", "push_plan.py")
    if not os.path.exists(pp):
        return out + ["B4 ci/push_plan.py is missing"]
    spec = importlib.util.spec_from_file_location("push_plan", pp)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    _, order = m.shard_map()
    if m.plan(["docs/V2_STATUS.md", "README.md"]):
        out.append("B4 push_plan: a docs-only change plans shards %s" % m.plan(["docs/V2_STATUS.md"]))
    if set(m.plan(["src/pe_engine.v"])) != set(order):
        out.append("B4 push_plan: an RTL change does not plan every shard")
    import json
    c = json.load(open(os.path.join(root, "ci", "ci_chunks.json"), encoding="utf-8"))
    for ch in m.chunks(order):
        tot = sum(c["minutes"].get(s, 60) for s in ch["shards"].split())
        if tot > c["job_budget_min"] and len(ch["shards"].split()) > 1:
            out.append("B4 push_plan: chunk %s is %d min (> %d)" % (ch["name"], tot, c["job_budget_min"]))
    out += dispatch_problems(c)
    if os.path.exists(t):
        out += timeout_check(open(t, encoding="utf-8").read(), c["job_budget_min"])
    return out


def dispatch_problems(c):
    """B4 for the DISPATCH chunks (11-26): ci_chunks.json's fixed full-suite chunks are summed with the
    same measured minutes as a push's -- at the re-measured minutes the old two chunks were ~374 and
    ~381 min, past the 330-min job timeout, and nothing summed them."""
    out = []
    for ch in c.get("dispatch", []):
        sh = ch["shards"].split()
        tot = sum(c["minutes"].get(s, 60) for s in sh)
        if tot > c["job_budget_min"] and len(sh) > 1:
            out.append("B4 dispatch: chunk %s is %d min (> %d)" % (ch["name"], tot, c["job_budget_min"]))
    return out


def timeout_check(text, budget):
    """B5: the `test` job's timeout covers a full planned chunk (budget min) plus setup."""
    doc = yaml.safe_load(text) or {}
    job = (doc.get("jobs", {}) or {}).get("test")
    if not job:
        return ["B5 test.yaml: no `test` job"]
    tm = job.get("timeout-minutes")
    nums = [int(n) for n in re.findall(r"\d+", str(tm))] if tm is not None else []
    if not nums:
        return ["B5 test.yaml: job `test` has no timeout-minutes (GitHub's default is 360; set it)"]
    need = budget + SETUP_MARGIN_MIN
    if min(nums) < need:
        return ["B5 test.yaml: job `test` can time out at %d min, under a planned chunk's %d + %d setup"
                % (min(nums), budget, SETUP_MARGIN_MIN)]
    return []


PLANT_FANOUT = """on:
  push:
    branches: [main]
jobs:
  list: {runs-on: ubuntu-24.04, steps: [{run: echo}]}
  test:
    needs: list
    strategy:
      fail-fast: false
      max-parallel: 8
      matrix: {shard: [a, b, c, d, e, f, g, h, i, j, k]}
    runs-on: ubuntu-24.04
    steps: [{run: echo}]
"""
PLANT_MANY = "on: [push]\njobs:\n" + "".join("  j%d: {runs-on: ubuntu-24.04, steps: [{run: echo}]}\n" % i for i in range(8))
PLANT_DISPATCH = {"job_budget_min": 300, "minutes": {"cov": 200, "sim1": 88, "trace": 28, "gcd": 20},
                  "dispatch": [{"name": "full-1", "shards": "cov sim1 trace gcd"}]}
PLANT_TMO = """on: [push]
jobs:
  test:
    runs-on: ubuntu-24.04
    timeout-minutes: ${{ github.event_name == 'push' && 120 || 330 }}
    steps: [{run: echo}]
"""
PLANT_HARDEN = "on:\n  push: {branches: [x]}\n  workflow_dispatch: {}\njobs:\n  j1: {runs-on: ubuntu-24.04, steps: [{run: echo}]}\n"
PLANT_OK = """on:
  push: {branches: [x]}
  workflow_dispatch: {}
jobs:
  list: {runs-on: ubuntu-24.04, steps: [{run: echo}]}
  test:
    needs: list
    strategy: {max-parallel: 1, matrix: {chunk: [a, b]}}
    runs-on: ubuntu-24.04
    steps: [{run: echo}]
  seams:
    if: github.event_name == 'workflow_dispatch'
    strategy: {matrix: {s: [a, b, c, d, e, f, g, h]}}
    runs-on: ubuntu-24.04
    steps: [{run: echo}]
"""


def main() -> int:
    print("=" * 78)
    print("  B -- THE CI BUDGET: no push fans out on GitHub (11-25)")
    print("=" * 78)
    rc = 0
    files = sorted(glob.glob(os.path.join(ROOT, ".github", "workflows", "*.y*ml")))
    for f in files:
        probs = audit(f, open(f, encoding="utf-8").read())
        for p in probs:
            print("  *** " + p)
        rc |= bool(probs)
    probs = plan_checks(ROOT)
    for p in probs:
        print("  *** " + p)
    rc |= bool(probs)
    print("  %d workflow(s) audited; MAX_PUSH_JOBS = %d" % (len(files), MAX_PUSH_JOBS))
    print("  --- must-fire ---")
    cases = [
        ("the 11-15 shape: a push-fired 11-way matrix", any(p.startswith("B2") for p in audit("test.yaml", PLANT_FANOUT))),
        ("8 jobs started by one push", any(p.startswith("B3") for p in audit("x.yaml", PLANT_MANY))),
        ("the 3f18e0e shape: a 120-min push timeout under 300-min chunks", any(p.startswith("B5") for p in timeout_check(PLANT_TMO, 300))),
        ("the 11-26 shape: dispatch chunks summing past the budget", any(p.startswith("B4 dispatch") for p in dispatch_problems(PLANT_DISPATCH))),
        ("a harden started by a push", any(p.startswith("B1") for p in audit("harden.yml", PLANT_HARDEN))),
        ("a 1-at-a-time push matrix + dispatch-only fan-out is accepted", not audit("x.yaml", PLANT_OK)),
    ]
    for label, hit in cases:
        print("    %-62s %s" % (label, "red" if hit and "accepted" not in label else ("accepted" if hit else "*** MISSED")))
        if not hit:
            rc = 1
    print()
    print("=" * 78)
    print("  GATE ci-budget: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return 1 if rc else 0


if __name__ == "__main__":
    raise SystemExit(main())
