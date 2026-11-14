"""make_canary -- a canary is the work branch plus its density, ONE commit
(Wilson 11-03, B1).

⛔⛔ WHY. A canary hardens the design to read its timing; if it carries
anything the work branch does not -- a stray config key, an RTL edit made on
the canary and never ported, a stale clock -- its timing is the timing of a
different chip. The armed canaries were made by hand and carried CLOCK_PERIOD
16.667 beside a 50 MHz clock_hz and comments the work branch never had.

    python ci/make_canary.py <density> [--label NAME]
        builds branch v2-canary-<NAME>-d<density> as ONE commit on top of
        HEAD, changing ONLY src/config.json's PL_TARGET_DENSITY_PCT value and
        adding .github/workflows/test.yaml's canary ignore. HEAD must be clean
        and on origin/work/s12-c. Nothing is pushed.
    python ci/make_canary.py --check
        (v2_canary.yaml, first step) red unless HEAD~1 is reachable from
        origin/work/s12-c and `git diff HEAD~1 HEAD` is exactly that.
    python ci/make_canary.py --self-test
        the check's must-fires on planted diffs.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = "origin/work/s12-c"
CONFIG = "src/config.json"
TEST_YAML = ".github/workflows/test.yaml"
DENSITY = "PL_TARGET_DENSITY_PCT"
DENSITY_LINE = re.compile(r'^(\s*"%s":\s*)(\d+)(,?\s*)$' % DENSITY)
IGNORE = ["    # CANARY BRANCHES ONLY (Wilson 11-02): a canary differs from work/s12-c",
          "    # in config alone and its source is tested there; the harden is dispatched",
          "    branches-ignore: ['v2-canary-*']"]
PUSH = "  push:"


def git(*args, cwd=ROOT, check=True):
    r = subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise SystemExit("*** git %s: %s" % (" ".join(args), r.stderr.strip()))
    return r


def with_density(text, d):
    nl = "\r\n" if "\r\n" in text else "\n"
    lines, n = text.split(nl), 0
    for i, l in enumerate(lines):
        m = DENSITY_LINE.match(l)
        if m:
            lines[i] = "%s%d%s" % (m.group(1), d, m.group(3))
            n += 1
    if n != 1:
        raise SystemExit("*** %s has %d %s lines, not one" % (CONFIG, n, DENSITY))
    return nl.join(lines)


def with_ignore(text):
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(nl)
    i = lines.index(PUSH)
    return nl.join(lines[:i + 1] + IGNORE + lines[i + 1:])


def judge(base_cfg, head_cfg, base_yaml, head_yaml, changed):
    """-> [problem] for one canary commit's diff against its base."""
    probs = []
    extra = sorted(set(changed) - {CONFIG, TEST_YAML})
    if extra:
        probs.append("the canary changes files beyond the density and the ignore: %s"
                     % ", ".join(extra))
    try:
        bc, hc = json.loads(base_cfg), json.loads(head_cfg)
    except ValueError as e:
        return probs + ["config.json does not parse: %s" % e]
    if DENSITY not in hc:
        probs.append("the canary has no %s" % DENSITY)
    nl = "\r\n" if "\r\n" in base_cfg else "\n"
    bl = [l for l in base_cfg.split(nl) if not DENSITY_LINE.match(l)]
    hl = [l for l in head_cfg.replace("\r\n", "\n").split("\n") if not DENSITY_LINE.match(l)]
    if [l.rstrip("\r") for l in bl] != [l.rstrip("\r") for l in hl]:
        probs.append("config.json differs from the work commit beyond the %s value"
                     % DENSITY)
    want = with_ignore(base_yaml).replace("\r\n", "\n")
    if head_yaml.replace("\r\n", "\n") != want:
        probs.append("test.yaml differs from the work commit beyond the canary ignore")
    return probs


def check():
    print("  --- B1: the canary is the work branch plus its density ---")
    git("fetch", "-q", "origin", "work/s12-c:refs/remotes/" + WORK, check=False)
    base = git("rev-parse", "HEAD~1").stdout.strip()
    anc = git("merge-base", "--is-ancestor", base, WORK, check=False).returncode == 0
    print("    HEAD~1 %s on %s: %s" % (base[:12], WORK, "yes" if anc else "*** NO"))
    changed = git("diff", "--name-only", "HEAD~1", "HEAD").stdout.split()
    show = lambda rev, p: git("show", "%s:%s" % (rev, p)).stdout
    probs = judge(show("HEAD~1", CONFIG), show("HEAD", CONFIG),
                  show("HEAD~1", TEST_YAML), show("HEAD", TEST_YAML), changed)
    if not anc:
        probs.insert(0, "HEAD~1 is not a work/s12-c commit")
    d = json.loads(show("HEAD", CONFIG)).get(DENSITY)
    for p in probs:
        print("    *** " + p)
    print("  CANARY CHECK: %s (density %s)" % ("FAILED" if probs else "PASSED", d))
    return 1 if probs else 0


def self_test():
    cfg = '{\n  "A": 1,\n  "%s": 60,\n  "CLOCK_PERIOD": 16.667\n}\n' % DENSITY
    yml = "name: test\non:\n%s\n  workflow_dispatch:\n" % PUSH
    good = (cfg, with_density(cfg, 61), yml, with_ignore(yml), [CONFIG, TEST_YAML])
    rc = 0
    cases = [
        ("the made canary itself", good, False),
        ("a config key changed", (cfg, with_density(cfg, 61).replace("16.667", "20"),
                                  yml, with_ignore(yml), [CONFIG, TEST_YAML]), True),
        ("an RTL file changed", good[:4] + ([CONFIG, TEST_YAML, "src/pe_store.v"],), True),
        ("test.yaml changed beyond the ignore", (cfg, with_density(cfg, 61), yml,
                                                 with_ignore(yml) + "  # x\n",
                                                 [CONFIG, TEST_YAML]), True),
        ("a comment added to config", (cfg, with_density(cfg, 61).replace(
            '"A": 1,', '"A": 1,\n  "//": "canary note",'), yml, with_ignore(yml),
            [CONFIG, TEST_YAML]), True),
    ]
    for what, args, want_red in cases:
        red = bool(judge(*args))
        ok = red == want_red
        print("    %-38s %s" % (what, ("red  ok" if want_red else "green ok") if ok
                                else "*** WRONG"))
        rc |= 0 if ok else 1
    print("  CANARY SELF-TEST: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


def make(density, label):
    if git("status", "--porcelain", "--untracked-files=no").stdout.strip():
        raise SystemExit("*** the tree is not clean -- a canary is built from a commit")
    head = git("rev-parse", "HEAD").stdout.strip()
    if git("merge-base", "--is-ancestor", head, WORK, check=False).returncode != 0:
        raise SystemExit("*** HEAD %s is not on %s -- push the work commit first, or "
                         "the canary check will refuse it" % (head[:12], WORK))
    name = "v2-canary-%s-d%d" % (label, density)
    tmp = tempfile.mkdtemp(prefix="pe_canary_", dir=os.environ.get("PE_SCRATCH_ROOT"))
    wt = os.path.join(tmp, "wt")
    git("worktree", "add", "-q", "--detach", wt, head)
    try:
        for rel, fn in ((CONFIG, lambda t: with_density(t, density)), (TEST_YAML, with_ignore)):
            p = os.path.join(wt, rel)
            with open(p, encoding="utf-8", newline="") as fh:
                t = fh.read()
            with open(p, "w", encoding="utf-8", newline="") as fh:
                fh.write(fn(t))
        git("add", CONFIG, TEST_YAML, cwd=wt)
        git("commit", "-q", "-m", "canary %s: %s = %d on %s\n\nBuilt by ci/make_canary.py "
            "(Wilson 11-03, B1): the work commit plus its density, nothing else."
            % (name, DENSITY, density, head[:12]), cwd=wt)
        sha = git("rev-parse", "HEAD", cwd=wt).stdout.strip()
        git("branch", "-f", name, sha)
    finally:
        git("worktree", "remove", "--force", wt, check=False)
    print("  %s -> %s (one commit on %s)" % (name, sha[:12], head[:12]))
    return 0


def main(argv):
    if "--check" in argv:
        return check()
    if "--self-test" in argv:
        return self_test()
    if not argv or not argv[0].isdigit():
        print(__doc__)
        return 2
    label = argv[argv.index("--label") + 1] if "--label" in argv else "w"
    return make(int(argv[0]), label)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
