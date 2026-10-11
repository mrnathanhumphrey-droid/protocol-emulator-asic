"""POSITIVE-TOKEN JUDGE for ci/run_gates.sh (Wilson's standing rule).

A gate passes only on an EXPLICIT POSITIVE TOKEN in its own output -- the line
`ci/gate_tokens.txt` names for it -- never on the absence of a failure. The
runner already requires exit 0; this adds the token. Exit 0 without it is red;
a gate with no entry in the table is red.

Usage:  python ci/pass_token.py <gate path> <its output file>
        python ci/pass_token.py --self-test      (the must-fires; run first)
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TABLE = os.path.join(ROOT, "ci", "gate_tokens.txt")


def load_table(path=TABLE):
    tab = {}
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            if not ln.strip() or ln.lstrip().startswith("#"):
                continue
            gate, rx = ln.rstrip("\n").split(None, 1)
            tab[gate] = re.compile(rx.strip())
    return tab


def judge(gate, text, tab):
    """(ok, reason)."""
    if gate not in tab:
        return False, "no entry in ci/gate_tokens.txt -- a gate without a " \
                      "declared pass token cannot pass"
    rx = tab[gate]
    for line in text.splitlines():
        if rx.search(line):
            return True, "pass token present: %s" % line.strip()[:80]
    return False, "exit 0 but NO PASS TOKEN (%s) in its output -- the " \
                  "absence of a failure is not a pass" % rx.pattern


def self_test():
    """The must-fires. Every red case must be red, the green case green."""
    tab = {"g.py": re.compile(r"^\s*GATE g: PASSED\s*$")}
    cases = [
        ("token present",                  "g.py", "x\n  GATE g: PASSED\n", True),
        ("empty output (tool never ran)",  "g.py", "",                        False),
        ("no token, no failure seen",      "g.py", "all checks ok\n",         False),
        ("token only as a FAILED verdict", "g.py", "  GATE g: *** FAILED\n",  False),
        ("token text inside another line", "g.py", "said GATE g: PASSED?\n",  False),
        ("gate absent from the table",     "h.py", "  GATE g: PASSED\n",      False),
    ]
    bad = 0
    for name, gate, text, want in cases:
        ok, _ = judge(gate, text, tab)
        good = ok == want
        bad += not good
        print("  pass-token self-test: %-34s %s" % (
            name, ("green ok" if want else "red ok") if good else "*** WRONG"))
    tab_real = load_table()
    print("  pass-token table: %d gates declared" % len(tab_real))
    if bad:
        print("PASS-TOKEN SELF-TEST: *** FAILED (%d)" % bad)
        return 1
    print("PASS-TOKEN SELF-TEST: PASSED")
    return 0


def main():
    if sys.argv[1:] == ["--self-test"]:
        return self_test()
    gate, out = sys.argv[1], sys.argv[2]
    with open(out, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    ok, why = judge(gate, text, load_table())
    print("  [pass-token] %s: %s" % (gate, why))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
