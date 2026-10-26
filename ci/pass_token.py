"""POSITIVE-TOKEN JUDGE for ci/run_gates.sh (Wilson's standing rule).

A gate passes only on an EXPLICIT POSITIVE TOKEN in its own output -- the line
`ci/gate_tokens.txt` names for it -- never on the absence of a failure. The
runner already requires exit 0; this adds the token. Exit 0 without it is red;
a gate with no entry in the table is red.

⭐ v2 (Wilson 10-25): THE THIRD VERDICT. A gate on
`model/stale_records.DECLARED` -- and ONLY such a gate -- may pass on its STALE
line instead: its own token with `PASSED` replaced by `STALE (declared: ...)`.
DECLARED is the one list; there is no second copy here. A STALE pass exits 3,
so `ci/run_gates.sh` can list it BY NAME (non-blocking on a work branch); with
PE_TAG=1 (the v2 lock) a STALE line is red, as the gates themselves are.

Usage:  python ci/pass_token.py <gate path> <its output file>
        python ci/pass_token.py --self-test      (the must-fires; run first)
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TABLE = os.path.join(ROOT, "ci", "gate_tokens.txt")
STALE_EXIT = 3


def declared_stale():
    sys.path.insert(0, os.path.join(ROOT, "model"))
    import stale_records
    return stale_records.DECLARED


def stale_rx(rx):
    """The gate's STALE line, derived from its PASS token (never typed twice)."""
    core = re.sub(r"PASSED(\\b|\\s\*\$)?$", "", rx.pattern)
    return re.compile(core + r"STALE \(declared: .+\)\s*$")


def load_table(path=TABLE):
    tab = {}
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            if not ln.strip() or ln.lstrip().startswith("#"):
                continue
            gate, rx = ln.rstrip("\n").split(None, 1)
            tab[gate] = re.compile(rx.strip())
    return tab


def judge(gate, text, tab, declared=None, tag=None):
    """(verdict, reason): verdict True (PASS), "STALE", or False (red)."""
    if gate not in tab:
        return False, "no entry in ci/gate_tokens.txt -- a gate without a " \
                      "declared pass token cannot pass"
    rx = tab[gate]
    for line in text.splitlines():
        if rx.search(line):
            return True, "pass token present: %s" % line.strip()[:80]
    srx = stale_rx(rx)
    for line in text.splitlines():
        if srx.search(line):
            declared = declared_stale() if declared is None else declared
            if tag is None:
                tag = os.environ.get("PE_TAG") == "1"
            if gate not in declared:
                return False, "a STALE line from a gate NOT on " \
                              "model/stale_records.DECLARED -- red"
            if tag:
                return False, "STALE blocks at the tag (PE_TAG=1): %s" % \
                              line.strip()[:80]
            return "STALE", "STALE, declared (non-blocking): %s" % \
                            line.strip()[:100]
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
    st = "  GATE g: STALE (declared: a reason)\n"
    stale_cases = [
        ("STALE on a declared gate",       "g.py", st, {"g.py": "r"}, False, "STALE"),
        ("STALE on an UNDECLARED gate",    "g.py", st, {},            False, False),
        ("STALE under PE_TAG=1",           "g.py", st, {"g.py": "r"}, True,  False),
    ]
    bad = 0
    for name, gate, text, dec, tag, want in stale_cases:
        got, _ = judge(gate, text, tab, declared=dec, tag=tag)
        good = got == want
        bad += not good
        print("  pass-token self-test: %-34s %s" % (
            name, ("green ok" if want else "red ok") if good else "*** WRONG"))
    for name, gate, text, want in cases:
        ok, _ = judge(gate, text, tab, declared={}, tag=False)
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
    if ok == "STALE":
        return STALE_EXIT
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
