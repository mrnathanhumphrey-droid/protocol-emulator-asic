#!/usr/bin/env python3
"""run_poset_spec -- the gate for the v2 spec parser (host/poset/spec.py) and emitter v2
(host/poset/emit2.py).

  S1 v1 COMPATIBILITY, from v1's own gate data (test/run_pit_emit.py, read, not copied):
     every v1 image's emitted text parses under v2 with v1 claims == pit_emit.parse's;
     v1's GOOD_PATTERN parses; every v1 BAD text is still refused.
  S2 THE GOLDEN'S STATEMENTS round-trip exactly: render(parse(t)) == t, for every statement
     run_poset_golden's arms produce.
  S3 EMITTER v2 end to end: v1 claims intact; ORDER records come back as the same
     statements; VIOLATION / ABSTAIN records come back as `? unknown order.*` lines, never
     as patterns.
  S4 GRAMMAR: the accept list round-trips to the same AST; vol5's left associativity; the
     reject list (each with the reason it must fail) is refused.
Must-fires: every spec.MUTANTS entry, in a subprocess, turns this gate red.

POSITIVE TOKEN: `GATE poset_spec: PASSED`.
"""
from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.join(ROOT, "test"))
import spec as S  # noqa: E402
import emit2 as E2  # noqa: E402
import golden as G  # noqa: E402
import run_poset_golden as RG  # noqa: E402
import run_pit_emit as V1T  # noqa: E402
from golden import key  # noqa: E402

pit_emit = S.pit_emit
HZ = G.clock.hz()

ACCEPT = [
    "pattern (Rise(uio1) || Rise(uio2)) -> Byte(uio0);",
    "never Fall(uio3) |> Fall(uio3);",
    'pattern [8 ->] Rise(uio1) during (100 ns, 2000.5 ns) observed 3 given all-wires-sniffed '
    'source datasheet "MB85RC256V";',
    "pattern Start(uio1) || Start(uio2);",
    "pattern Rise(uio1) ~ Rise(uio2) and Fall(uio1) or Fall(uio2) source data;",
    "pattern Start(uio2, uio1) -> (Byte(uio2) -> Stop(uio2, uio1));",
]
REJECT = {
    "v1's stray `<`": "pattern Frame(uio0) < Frame(uio0);",
    "event kind outside the vocabulary": "pattern Glitch(uio0);",
    "wire uio8": "pattern Rise(uio8);",
    "Rise on two wires": "pattern Rise(uio1, uio2);",
    "Start on three wires": "pattern Start(uio1, uio2, uio3);",
    "bounds reversed": "pattern Rise(uio1) during (5 ns, 2 ns);",
    "repeat 0": "pattern [0 ->] Rise(uio1);",
    "unbounded iteration": "pattern [* ->] Rise(uio1);",
    "a placeholder": "pattern (?x : Integer) Rise(uio1);",
    "a guard": "pattern Rise(uio1) where x;",
    "union": "pattern Rise(uio1) union Rise(uio2);",
    "no `;`": "pattern Rise(uio1) -> Rise(uio2)",
    "observed without a count": "pattern Rise(uio1) observed many;",
    "time without ns": "pattern Rise(uio1) during (5, 9);",
}


def wrap(*lines):
    return "spec sniff is\n  captured at %d Hz;\n%s\nend sniff;\n" % (HZ, "\n".join("  " + l for l in lines))


def refused(text):
    try:
        S.parse(text)
    except S.SpecError:
        return True
    return False


def judge():
    probs = []
    # S1
    for nm, mk in V1T.IMAGES.items():
        t = pit_emit.emit(bytes(mk()), HZ)
        got = S.parse(t)["v1"]
        if got != pit_emit.parse(t):
            probs.append("S1 v1 image %s: v2's v1 claims differ from pit_emit.parse" % nm)
    if refused(V1T.GOOD_PATTERN):
        probs.append("S1 v1 GOOD_PATTERN refused by v2")
    for nm, t in V1T.BAD.items():
        if not refused(t):
            probs.append("S1 v1 BAD %r accepted by v2" % nm)
    # S2
    _p, lines = RG.judge()
    for t in lines:
        st = S.parse_statement(t[:-1])
        if S.render_statement(st) != t:
            probs.append("S2 round trip: %r -> %r" % (t, S.render_statement(st)))
    # S3
    b, _leads = RG.spi(1)
    ev = G.extract(*b.trace())
    recs = G.infer(ev, [(key("Fall", 3), "|>", key("Rise", 1)),
                        (key("Fall", 3), "|>", key("Fall", 3)),   # VIOLATION: CS falls are not adjacent
                        (key("Rise", 6), "->", key("Rise", 7))], HZ)   # ABSTAIN
    res = bytes(V1T.IMAGES["spi"]())
    text = E2.emit2(res, recs, HZ)
    try:
        back = S.parse(text)
    except S.SpecError as e:
        probs.append("S3 emitter v2 text refused: %s" % e)
        back = None
    if back is not None:
        base = pit_emit.parse(pit_emit.emit(res, HZ))
        v1 = dict(back["v1"]) if back["v1"] else {}
        extra = [u for u in v1.get("unknown", []) if u[0].startswith("order.")]
        v1["unknown"] = [u for u in v1.get("unknown", []) if not u[0].startswith("order.")]
        if v1 != base:
            probs.append("S3 emitter v2 changed the v1 claims")
        want = [r["text"] for r in recs if r["verdict"] in ("ORDER", "BOTH")]
        if [S.render_statement(s) for s in back["poset"]] != want:
            probs.append("S3 poset statements %r, expected %r"
                         % ([S.render_statement(s) for s in back["poset"]], want))
        verdicts = [r["verdict"] for r in recs]
        if verdicts != ["ORDER", "VIOLATION", "ABSTAIN"] or len(extra) != 2:
            probs.append("S3 verdicts %s, order unknowns %d (expected ORDER / VIOLATION / ABSTAIN, 2)"
                         % (verdicts, len(extra)))
    # S4
    for t in ACCEPT:
        try:
            a = S.parse(wrap(t))["poset"][0]
            r = S.render_statement(a)
            if S.parse_statement(r[:-1])["ast"] != a["ast"] or S.parse_statement(r[:-1]) != a:
                probs.append("S4 accept %r: render %r parses differently" % (t, r))
        except S.SpecError as e:
            probs.append("S4 accept %r refused: %s" % (t, e))
    ast = S.parse_statement("pattern Rise(uio1) -> Rise(uio2) || Rise(uio3)")["ast"]
    if not (ast[0] == "bin" and ast[1] == "||" and ast[2][0] == "bin" and ast[2][1] == "->"):
        probs.append("S4 associativity: A -> B || C parsed as %r, vol5 groups left" % (ast,))
    for why, t in REJECT.items():
        if not refused(wrap(t)):
            probs.append("S4 reject (%s) accepted: %r" % (why, t))
    return probs, text


def main() -> int:
    if os.environ.get("POSET_SPEC_MUTANT"):
        try:
            probs, _ = judge()
        except Exception as e:                       # a mutant that crashes the gate is red
            probs = ["crash: %r" % e]
        print("MUTANT %s: %s" % (os.environ["POSET_SPEC_MUTANT"], "RED" if probs else "green"))
        for p in probs[:3]:
            print("   ", p)
        return 1 if probs else 0
    print("poset spec: the v2 parser and emitter v2 (clock %d Hz)" % HZ)
    probs, text = judge()
    print("  emitter v2 sample (SPI image + golden records):")
    for ln in text.splitlines():
        print("    |", ln)
    for p in probs:
        print("  ***", p)
    for m in S.MUTANTS:
        env = dict(os.environ, POSET_SPEC_MUTANT=m)
        r = subprocess.run([sys.executable, os.path.abspath(__file__)], env=env,
                           capture_output=True, text=True)
        red = r.returncode != 0 and ("MUTANT %s: RED" % m) in r.stdout
        why = next((ln.strip() for ln in r.stdout.splitlines()[1:2]), "")
        print("  must-fire %-17s %s  %s" % (m, "RED (killed)" if red else "*** SURVIVED", why[:90]))
        if not red:
            probs.append("mutant %s survived" % m)
    if probs:
        print("GATE poset_spec: FAILED (%d)" % len(probs))
        return 1
    print("GATE poset_spec: PASSED (S1-S4 exact; %d / %d mutants killed)" % (len(S.MUTANTS), len(S.MUTANTS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
