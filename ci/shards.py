"""THE SHARD MAP'S JUDGE -- ci/shards.txt against ci/run_gates.sh's GATES.

    python ci/shards.py check          # red unless the map covers GATES exactly
    python ci/shards.py list           # the shard names, JSON (the CI matrix)
    python ci/shards.py gates NAME     # NAME's gates, in GATES order

⛔⛔ A SHARDED SUITE MUST STILL BE THE WHOLE SUITE (Wilson 10-25). A gate in
no shard runs nowhere and reads as green; a gate in two runs twice; a row
naming no gate is a typo that hides the gate it meant. All three are red, and
`check` runs its own must-fires first (planted maps) so a judge that cannot
fail is red too. The CI matrix is read from here, never typed.
"""
from __future__ import annotations

import collections
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP = os.path.join(ROOT, "ci", "shards.txt")


def gates():
    """GATES=( ... ) of ci/run_gates.sh, in order (the one list)."""
    with open(os.path.join(ROOT, "ci", "run_gates.sh"), encoding="utf-8") as fh:
        txt = fh.read()
    body = txt[txt.index("GATES=("):]
    body = body[:body.index("\n)")]
    return re.findall(r"^\s+([a-z][\w/.-]*\.(?:py|sh))", body, re.M)


def rows(text=None):
    if text is None:
        with open(MAP, encoding="utf-8") as fh:
            text = fh.read()
    out = []
    for ln in text.splitlines():
        ln = ln.split("#", 1)[0].strip()
        if ln:
            out.append(tuple(ln.split()))
    return out


def problems(gl, rs):
    """[problem] for map rows `rs` against the gate list `gl`."""
    probs = []
    for r in rs:
        if len(r) != 2:
            probs.append("malformed row %r (want `<shard> <gate>`)" % (r,))
    rs = [r for r in rs if len(r) == 2]
    seen = collections.Counter(g for _s, g in rs)
    for g in gl:
        if seen[g] == 0:
            probs.append("%s is in GATES but in NO shard -- it would run nowhere" % g)
        elif seen[g] > 1:
            probs.append("%s is in %d shards" % (g, seen[g]))
    for g in sorted(set(seen) - set(gl)):
        probs.append("shard row names %s, which is not in GATES" % g)
    return probs


def self_test(gl):
    """The judge must reject what it claims to (planted maps)."""
    good = [("a", g) for g in gl]
    ok = not problems(gl, good)
    for what, plant in (("a gate in no shard", good[1:]),
                        ("a gate in two shards", good + [("b", gl[0])]),
                        ("a row naming no gate", good + [("b", "model/nope.py")]),
                        ("a malformed row", good + [("b",)])):
        red = bool(problems(gl, plant))
        print("    must-fire %-28s %s" % (what, "red  ok" if red else "*** MISSED"))
        ok = ok and red
    return ok


def main(argv) -> int:
    gl, rs = gates(), rows()
    cmd = argv[1] if len(argv) > 1 else "check"
    if cmd == "list":
        print(json.dumps(sorted({s for s, _g in rs})))
        return 0
    if cmd == "gates":
        name = argv[2] if len(argv) > 2 else ""
        mine = {g for s, g in rs if s == name}
        if not mine:
            print("*** no shard named %r (have: %s)"
                  % (name, " ".join(sorted({s for s, _g in rs}))), file=sys.stderr)
            return 1
        print("\n".join(g for g in gl if g in mine))
        return 0
    print("  --- the shard map covers GATES exactly (ci/shards.txt) ---")
    ok = self_test(gl)
    probs = problems(gl, rs)
    for p in probs:
        print("    *** %s" % p)
    shards = collections.Counter(s for s, _g in rs)
    print("    %d gates over %d shards: %s"
          % (len(gl), len(shards), ", ".join("%s %d" % kv for kv in sorted(shards.items()))))
    good = ok and not probs
    print("  shard map: %s" % ("ok" if good else "RED"))
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
