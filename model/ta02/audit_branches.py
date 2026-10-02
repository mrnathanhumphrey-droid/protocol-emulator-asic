"""THE BRANCH-POINT AUDIT -- the structural half of Gate 0.

⛔⛔ WHAT IT IS FOR. The behavioural gate (SPI off the unchanged machine) is the
falsifier that can fail, but it is a test of OUTPUT. A machine could emit correct
SPI and still be protocol-shaped inside -- a bit counter, a frame-phase register,
a notion of "data phase" -- and that shape is what gets paid for in silicon when
TA-02's semantics freeze. This audit reads the transition relation and asks the
one structural question: DOES ANY BRANCH DEPEND ON ANYTHING BUT THE CURRENT TABLE
ENTRY AND THE GENERIC STATE?

⛔ IT REPLACES THE TWO TESTS THAT CANNOT FAIL. "The diff across table loads is
empty" is not-editing-a-file. "No protocol literals appear in the file" passes a
UART machine with `434` renamed `BIT_PERIOD` -- which is why the literal scan is
kept here only as a cheap SECONDARY, inside the branch tests where a bare constant
really is a protocol commitment, and never as the primary evidence.

⭐⭐ AND IT IS PRICED BY MUTATION. An audit nobody has seen reject anything is an
audit of unknown strength, so four mutants of `step` are fed through it below --
each must be REJECTED, and each must be rejected FOR ITS STATED REASON. A colour
cannot certify a reason: the finding must name the offending branch.
"""

from __future__ import annotations

import ast
import os
import sys
import textwrap

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))

# The machine's whole permitted vocabulary inside a branch condition.
#   st, pc, x   -- the generic state: a table index and ONE clock
#   e           -- the current table entry (and its fields, via attributes)
#   in_bits     -- the sampled input pins
# ⛔ Anything else is, by definition, state the table did not put there.
ALLOWED_NAMES = {"st", "pc", "x", "e", "in_bits", "self"}
ALLOWED_SELF_ATTRS = {"table"}
# 0 is the `in_pin < 0` sentinel; 1 is the bit mask. A branch constant that is
# neither is a magic number, and a magic number in a branch is a protocol.
ALLOWED_CONSTS = {0, 1, True, False, None}


def _tests_of(fn: ast.AST):
    """Every branch condition in the function, with its line."""
    out = []
    for node in ast.walk(fn):
        if isinstance(node, ast.If):
            out.append(("if", node.test, node.test.lineno))
        elif isinstance(node, ast.IfExp):
            out.append(("ifexp", node.test, node.test.lineno))
        elif isinstance(node, ast.While):
            out.append(("while", node.test, node.test.lineno))
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp,
                               ast.DictComp)):
            for g in node.generators:
                for c in g.ifs:
                    out.append(("comp-if", c, c.lineno))
        elif isinstance(node, ast.BoolOp):
            # a BoolOp inside a test is already covered; a BoolOp assigned to a
            # name that is LATER used as a test is not -- `matched = a and b` is a
            # branch point whose condition lives on another line.
            pass
    return out


def _local_defs(fn: ast.AST) -> dict:
    """`matched = <expr>` -- a branch condition HOISTED onto its own line.

    ⛔⛔ THE AUDIT'S FIRST VERSION FLAGGED THE REAL MACHINE because it saw the bare
    name `matched` in the ternary and called it foreign. Worse, mutant M4 then died
    naming `matched` instead of its own `UART_STOP_BITS` -- A RED MUTANT DYING FOR A
    STALE REASON, which would have certified an audit that was not actually looking
    at the hoisted expression. The fix is to RESOLVE a local back to its defining
    expression and audit that, so hoisting neither triggers nor hides a finding.
    """
    defs = {}
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            defs[node.targets[0].id] = node.value
    return defs


def audit_function(src: str, fname: str = "step") -> dict:
    """Audit one function's branch points. Returns findings; empty == clean."""
    tree = ast.parse(textwrap.dedent(src))
    fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == fname:
            fn = node
            break
    if fn is None:
        return {"ok": False, "findings": [("missing", 0, "no `%s`" % fname)],
                "branches": 0, "fields": set()}

    defs = _local_defs(fn)
    findings, fields = [], set()

    def check(expr, kind, ln, resolving=frozenset()):
        for sub in ast.walk(expr):
            if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name):
                if sub.value.id == "self" and sub.attr not in ALLOWED_SELF_ATTRS:
                    findings.append((kind, ln,
                                     "branch depends on NON-TABLE instance state "
                                     "`self.%s`" % sub.attr))
                elif sub.value.id == "e":
                    fields.add(sub.attr)        # which descriptor fields branch
            elif isinstance(sub, ast.Name):
                if sub.id in ALLOWED_NAMES:
                    continue
                if sub.id in defs and sub.id not in resolving:
                    # a hoisted condition: audit WHAT IT IS, not its label
                    check(defs[sub.id], kind, ln, resolving | {sub.id})
                else:
                    findings.append((kind, ln,
                                     "branch depends on name `%s`, which is outside "
                                     "the machine's vocabulary %s"
                                     % (sub.id, sorted(ALLOWED_NAMES))))
            elif isinstance(sub, ast.Constant) and sub.value not in ALLOWED_CONSTS:
                findings.append((kind, ln,
                                 "branch compares against the bare constant %r -- a "
                                 "magic number in a branch IS a protocol commitment"
                                 % (sub.value,)))

    tests = _tests_of(fn)
    for kind, test, ln in tests:
        check(test, kind, ln)

    seen, uniq = set(), []
    for f in findings:
        if f not in seen:
            seen.add(f)
            uniq.append(f)
    return {"ok": not uniq, "findings": uniq, "branches": len(tests),
            "fields": fields}


# ===========================================================================
# THE MUTANTS. Each must be REJECTED, and the rejection must NAME the offender.
# ===========================================================================
MUTANTS = [
    ("M1 bit counter",
     "self.nbits",
     """
     def step(self, st, in_bits=0):
         pc, x = st
         e = self.table[pc]
         if x + 1 < e.g:
             return (pc, x + 1)
         if self.nbits == 8:            # <-- protocol-shaped: a BIT COUNTER
             return (0, 0)
         if e.in_pin < 0:
             return (e.next_a, 0)
         matched = ((in_bits >> e.in_pin) & 1) == e.in_pol
         return ((e.next_a if matched else e.next_b), 0)
     """),
    ("M2 baud constant",
     "434",
     """
     def step(self, st, in_bits=0):
         pc, x = st
         e = self.table[pc]
         if x + 1 < 434:                # <-- the bit period, hard-coded
             return (pc, x + 1)
         if e.in_pin < 0:
             return (e.next_a, 0)
         matched = ((in_bits >> e.in_pin) & 1) == e.in_pol
         return ((e.next_a if matched else e.next_b), 0)
     """),
    ("M3 frame phase",
     "phase",
     """
     def step(self, st, in_bits=0):
         pc, x, phase = st
         e = self.table[pc]
         if x + 1 < e.g:
             return (pc, x + 1, phase)
         if phase == 1:                 # <-- a notion of "data phase"
             return (e.next_a, 0, 1)
         if e.in_pin < 0:
             return (e.next_a, 0, phase)
         matched = ((in_bits >> e.in_pin) & 1) == e.in_pol
         return ((e.next_a if matched else e.next_b), 0, phase)
     """),
    ("M4 hoisted global",
     "UART_STOP_BITS",
     """
     def step(self, st, in_bits=0):
         pc, x = st
         e = self.table[pc]
         if x + 1 < e.g:
             return (pc, x + 1)
         done = x >= e.g * UART_STOP_BITS   # <-- hoisted onto its own line
         if e.in_pin < 0:
             return (e.next_a if done else pc, 0)
         matched = ((in_bits >> e.in_pin) & 1) == e.in_pol
         return ((e.next_a if matched else e.next_b), 0)
     """),
]


def main() -> int:
    print("=== TA-02 GATE 0 -- BRANCH-POINT AUDIT (structural genericity) ===")
    print("    target: model/ta02/interp.py :: Interp.step")
    print("    rule:   every branch depends ONLY on the current table entry `e`,")
    print("            the generic state (pc, x) and the sampled inputs.")
    print()
    src = open(os.path.join(HERE, "interp.py"), encoding="utf-8").read()
    real = audit_function(src, "step")
    print("  branch points found in `step`: %d" % real["branches"])
    for kind, ln, msg in real["findings"]:
        print("    *** %s @line %d: %s" % (kind, ln, msg))
    print("  verdict: %s" % ("CLEAN -- zero branches on non-table state"
                             if real["ok"] else "FINDINGS -- see above"))

    # ⭐ THE DESCRIPTOR FREEZE, CHECKED RATHER THAN ASSERTED. Every field the
    # branches read must be a field of the descriptor TA-02 is freezing -- a branch
    # on anything else is state that silicon would have to carry without the table
    # ever having specified it.
    sys.path.insert(0, HERE)
    from interp import Entry
    declared = set(Entry._fields)
    stray = real["fields"] - declared
    print("  descriptor fields read by branches: %s" % sorted(real["fields"]))
    print("  declared descriptor fields:         %s" % sorted(declared))
    print("  branch-read fields outside the descriptor: %s"
          % (sorted(stray) if stray else "none"))
    print()

    print("  -- mutation pricing: each mutant must be REJECTED, and the finding")
    print("     must NAME the offending term. A colour cannot certify a reason.")
    print()
    print("    %-20s %-10s %-9s %s" % ("mutant", "rejected", "names it", "finding"))
    killed = 0
    for label, offender, msrc in MUTANTS:
        res = audit_function(msrc, "step")
        rejected = not res["ok"]
        named = any(offender in msg for _, _, msg in res["findings"])
        if rejected and named:
            killed += 1
        first = res["findings"][0][2][:58] if res["findings"] else "-"
        print("    %-20s %-10s %-9s %s"
              % (label, "yes" if rejected else "*** NO ***",
                 "yes" if named else "*** NO ***", first))
    print()
    print("  mutants killed FOR THEIR STATED REASON: %d of %d"
          % (killed, len(MUTANTS)))
    ok = (real["ok"] and killed == len(MUTANTS) and real["branches"] >= 3
          and not stray)
    print()
    print("  BRANCH-POINT AUDIT: %s" %
          ("PASSED -- the transition relation reads the table and nothing else, "
           "and the audit has been shown to reject four ways of breaking that."
           if ok else
           "FAILED -- either the machine branches on non-table state, or the "
           "audit cannot be shown to catch it (which is worse)."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
