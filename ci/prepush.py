"""THE PRE-PUSH SET -- ci/prepush.txt against ci/run_gates.sh's GATES (Wilson 11-15, item 5).

    python ci/prepush.py check   # red unless the list covers GATES exactly (see below)
    python ci/prepush.py run     # check, then run every `prepush` gate; any red -> exit 1
    python ci/prepush.py list    # the prepush gates, in GATES order

Run by the pre-push hook (.githooks/pre-push), so a red pre-push gate BLOCKS THE PUSH.

⛔⛔ WHY (11-15): 1eee995 went to origin red on gate_wire_feed (and v3_table.vh), and
a572c42 registered four gates in GATES but in no CI shard -- both because the gates run
before a push were a hand-picked set. Every registered gate is now named here, as one of

    prepush <gate>                 -- run by the hook before every push from this checkout;
    ci-only <gate> <reason ...>    -- run by CI's shards only; the reason is REQUIRED.

and `check` is red on: a GATES entry not listed (it would be silently dropped from the
hook), a gate listed twice, a row naming no GATES entry, a listed file that does not
exist, a ci-only row with no reason, a malformed row. `check` runs its own must-fires
first (planted lists), and `run` prices "a failing pre-push gate blocks the push" on a
planted red gate before it runs the real ones -- a judge that cannot fail is red too.
"""
from __future__ import annotations

import collections
import os
import subprocess
import sys
import tempfile
import time

try:        # under git's hook runner stdout is the console code page (cp1252 here); gate
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # lines carry non-ASCII
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ci"))
import shards  # noqa: E402  -- the one GATES parser

LIST = os.path.join(ROOT, "ci", "prepush.txt")
KINDS = ("prepush", "ci-only")


def rows(text=None):
    if text is None:
        with open(LIST, encoding="utf-8") as fh:
            text = fh.read()
    out = []
    for ln in text.splitlines():
        ln = ln.split("#", 1)[0].strip()
        if ln:
            out.append(tuple(ln.split(None, 2)))
    return out


def problems(gl, rs, exists=lambda g: os.path.isfile(os.path.join(ROOT, g))):
    """[problem] for list rows `rs` against the gate list `gl`."""
    probs, good = [], []
    for r in rs:
        if len(r) < 2 or r[0] not in KINDS:
            probs.append("malformed row %r (want `prepush <gate>` or "
                         "`ci-only <gate> <reason>`)" % (r,))
        elif r[0] == "ci-only" and (len(r) < 3 or not r[2].strip()):
            probs.append("%s is ci-only with NO reason" % r[1])
        elif r[0] == "prepush" and len(r) > 2:
            probs.append("malformed row %r (a prepush row takes no reason)" % (r,))
        else:
            good.append(r)
    seen = collections.Counter(r[1] for r in rs if len(r) >= 2)
    for g in gl:
        if seen[g] == 0:
            probs.append("%s is in GATES but NOT LISTED -- neither pre-push nor CI-only" % g)
        elif seen[g] > 1:
            probs.append("%s is listed %d times" % (g, seen[g]))
    for g in sorted(set(seen) - set(gl)):
        probs.append("row names %s, which is not in GATES" % g)
    for r in good:
        if not exists(r[1]):
            probs.append("row names %s, which does not exist" % r[1])
    return probs


def prepush_gates(gl, rs):
    want = {r[1] for r in rs if len(r) >= 2 and r[0] == "prepush"}
    return [g for g in gl if g in want]


def self_test(gl):
    """check must reject what it claims to (planted lists)."""
    good = [("prepush", g) for g in gl]
    ok = not problems(gl, good)
    if not ok:
        print("    *** the all-prepush control list is red: %s" % problems(gl, good)[:2])
    for what, plant, ex in (
            ("an unlisted gate", good[1:], None),
            ("a gate listed twice", good + [("ci-only", gl[0], "x")], None),
            ("a row naming no GATES entry", good + [("prepush", "model/nope.py")], None),
            ("a listed gate that does not exist", good, lambda g: g != gl[0]),
            ("a ci-only row with no reason", [("ci-only", gl[0])] + good[1:], None),
            ("a malformed row", good + [("maybe", gl[0])], None)):
        red = bool(problems(gl, plant, ex) if ex else problems(gl, plant))
        print("    must-fire %-34s %s" % (what, "red  ok" if red else "*** MISSED"))
        ok = ok and red
    return ok


def run_gate(g):
    """(rc, seconds, last line) for one gate, from the repo root."""
    cmd = (["bash", g] if g.endswith(".sh") else [sys.executable, g])
    t0 = time.time()
    p = subprocess.run(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = p.stdout.decode("utf-8", "replace").strip().splitlines()
    return p.returncode, time.time() - t0, (out[-1] if out else "")


def run_all(gates, runner=run_gate):
    """-> (rc, [(gate, rc, s, last)]); rc 1 if ANY gate is red."""
    res = []
    for g in gates:
        rc, s, last = runner(g)
        res.append((g, rc, s, last))
        print("  %-40s rc=%d %5.0fs  %s" % (g, rc, s, last[:90]))
    return (1 if any(r[1] != 0 for r in res) else 0), res


def block_must_fire():
    """a failing pre-push gate blocks the push: run_all on a planted red gate -> rc 1"""
    with tempfile.TemporaryDirectory() as d:
        red = os.path.join(d, "planted_red_gate.py")
        with open(red, "w") as fh:
            fh.write("import sys; print('planted red'); sys.exit(1)\n")
        rc, _ = run_all([red], lambda g: (subprocess.run([sys.executable, g],
                                                         stdout=subprocess.DEVNULL).returncode,
                                          0.0, "planted"))
    ok = rc != 0
    print("    must-fire %-34s %s" % ("a failing pre-push gate blocks",
                                      "red  ok" if ok else "*** MISSED"))
    return ok


def main(argv) -> int:
    cmd = argv[1] if len(argv) > 1 else "check"
    gl, rs = shards.gates(), rows()
    if cmd == "list":
        print("\n".join(prepush_gates(gl, rs)))
        return 0
    print("  --- PRE-PUSH SET (ci/prepush.txt) against GATES ---")
    ok = self_test(gl)
    probs = problems(gl, rs)
    for p in probs:
        print("    *** %s" % p)
    pp = prepush_gates(gl, rs)
    print("    %d gates: %d prepush, %d ci-only" % (len(gl), len(pp), len(gl) - len(pp)))
    if not ok or probs:
        print("  pre-push list: RED")
        return 1
    print("  pre-push list: ok")
    if cmd == "check":
        return 0
    if cmd != "run":
        print("  *** unknown command %r" % cmd)
        return 1
    if not block_must_fire():
        return 1
    print("  --- running %d pre-push gate(s) ---" % len(pp))
    rc, res = run_all(pp)
    bad = [r[0] for r in res if r[1] != 0]
    print("  PRE-PUSH: %s" % ("PASSED" if rc == 0 else
                              "*** RED -- push blocked: " + ", ".join(bad)))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
