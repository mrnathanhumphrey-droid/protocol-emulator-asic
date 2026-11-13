"""poset spec -- the v2 PARSER and canonical RENDERER (host/poset/POSET_SPEC.md).

parse(text) -> {"v1": <pit_emit.parse claims>, "poset": [statement, ...]}

ONE SOURCE FOR v1: every line that is not a `pattern` / `never` statement goes to
emitter v1's own parser (model/pit_emit.parse), unchanged. So v1's rules are not
re-implemented here, and every v1 spec stays a v2 spec by construction. The v2
grammar (vol5 operators, bounded repeat, `during`, clauses) applies to `pattern` /
`never` lines only.

A statement is a dict: {"kind": "pattern"|"never", "ast", "during": (lo_str, hi_str) | None,
"observed": int | None, "given": str | None, "source": None | "data" | ("datasheet", str)}.
An AST node is ("ev", KIND, (wire, ...)) | ("bin", op, left, right) | ("rep", n, node).
`during` keeps the numbers as written, so render(parse(t)) reproduces them exactly.

Mutants for the gate's must-fires: env POSET_SPEC_MUTANT (see MUTANTS).
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "model"))
import pit_emit  # noqa: E402

MUTANTS = ("M_PS_ACCEPT_LT",    # v1's stray `<` accepted as an operator
           "M_PS_RIGHT_ASSOC",  # operators group to the right (vol5 §2.1: left)
           "M_PS_DROP_OBS",     # the `observed n` clause parsed and dropped
           "M_PS_OPEN_KINDS",   # any event name accepted (the vocabulary is closed)
           "M_PS_V1_BYPASS")    # non-pattern lines not handed to v1's parser
MUT = os.environ.get("POSET_SPEC_MUTANT", "")
if MUT and MUT not in MUTANTS:
    raise SystemExit("poset spec: unknown mutant %r" % MUT)


class SpecError(ValueError):
    pass


KINDS = {"Rise": (1, 1), "Fall": (1, 1), "Edge": (1, 1),
         "Start": (1, 2), "Stop": (1, 2),           # (sda) as v1 writes it, or (sda, scl)
         "Frame": (1, 1), "Byte": (1, 1)}
BINOPS = ("->", "|>", "||", "~", "or", "and")
#: names may carry inner hyphens (v1's condition `all-wires-sniffed`); a hyphen must be
#: followed by a letter, so `x->y` still tokenizes as x, ->, y
_TOK = re.compile(r'\s*(->|\|>|\|\||~|<|\(|\)|\[|\]|,|"[^"]*"|\d+(?:\.\d+)?'
                  r'|[A-Za-z_]\w*(?:-[A-Za-z_]\w*)*|\S)')


def _tokens(s):
    out, i = [], 0
    while i < len(s):
        m = _TOK.match(s, i)
        if not m:
            break
        if m.group(1):
            out.append(m.group(1))
        i = m.end()
    return out


class _P:
    def __init__(self, toks):
        self.t, self.i = toks, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self, want=None):
        tok = self.peek()
        if tok is None or (want is not None and tok != want):
            raise SpecError("expected %r, got %r" % (want or "a token", tok))
        self.i += 1
        return tok

    def binop(self):
        tok = self.peek()
        if tok in BINOPS or (tok == "<" and MUT == "M_PS_ACCEPT_LT"):
            return tok
        return None

    def pattern(self):
        if MUT == "M_PS_RIGHT_ASSOC":
            left = self.term()
            op = self.binop()
            if op is None:
                return left
            self.take()
            return ("bin", op, left, self.pattern())
        node = self.term()
        while True:
            op = self.binop()
            if op is None:
                return node
            self.take()
            node = ("bin", op, node, self.term())

    def term(self):
        tok = self.peek()
        if tok == "(":
            self.take()
            node = self.pattern()
            self.take(")")
            return node
        if tok == "[":
            self.take()
            n = self.take()
            if not n.isdigit() or int(n) < 1:
                raise SpecError("repeat count must be an integer >= 1, got %r "
                                "(unbounded iteration is not in v2)" % n)
            self.take("->")
            self.take("]")
            return ("rep", int(n), self.term())
        return self.event()

    def event(self):
        kind = self.take()
        if not re.fullmatch(r"[A-Za-z_]\w*", kind):
            raise SpecError("expected an event, got %r" % kind)
        if kind not in KINDS and MUT != "M_PS_OPEN_KINDS":
            raise SpecError("event kind %r is not in the vocabulary %s" % (kind, sorted(KINDS)))
        self.take("(")
        ws = [self.wire()]
        while self.peek() == ",":
            self.take()
            ws.append(self.wire())
        self.take(")")
        lo, hi = KINDS.get(kind, (1, 8))
        if not lo <= len(ws) <= hi:
            raise SpecError("%s takes %d..%d wires, got %d" % (kind, lo, hi, len(ws)))
        return ("ev", kind, tuple(ws))

    def wire(self):
        tok = self.take()
        m = re.fullmatch(r"uio([0-7])", tok)
        if not m:
            raise SpecError("not a wire: %r" % tok)
        return int(m.group(1))


def parse_statement(s):
    """`pattern ...` / `never ...` without the `;` -> statement dict."""
    kind, _, rest = s.partition(" ")
    p = _P(_tokens(rest))
    st = {"kind": kind, "ast": p.pattern(), "during": None, "observed": None,
          "given": None, "source": None}
    if p.peek() == "during":
        p.take()
        p.take("(")
        lo = p.take(); p.take("ns"); p.take(",")
        hi = p.take(); p.take("ns"); p.take(")")
        for v in (lo, hi):
            if not re.fullmatch(r"\d+(?:\.\d+)?", v):
                raise SpecError("not a time: %r" % v)
        if float(lo) > float(hi):
            raise SpecError("during (%s ns, %s ns): lower bound above upper" % (lo, hi))
        st["during"] = (lo, hi)
    while p.peek() is not None:
        c = p.take()
        if c == "observed":
            n = p.take()
            if not n.isdigit():
                raise SpecError("observed takes an instance count, got %r" % n)
            if MUT != "M_PS_DROP_OBS":
                st["observed"] = int(n)
        elif c == "given":
            st["given"] = p.take()
        elif c == "source":
            src = p.take()
            if src == "data":
                st["source"] = "data"
            elif src == "datasheet":
                q = p.take()
                if not (q.startswith('"') and q.endswith('"')):
                    raise SpecError("source datasheet takes a quoted part name")
                st["source"] = ("datasheet", q[1:-1])
            else:
                raise SpecError("source is data or datasheet, got %r" % src)
        else:
            raise SpecError("unexpected %r after the pattern" % c)
    return st


def parse(text):
    """-> {"v1": claims, "poset": [statements]}."""
    keep, stmts = [], []
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("pattern ") or s.startswith("never "):
            if "--" in s:
                s = s[:s.index("--")].rstrip()
            if not s.endswith(";"):
                raise SpecError("no `;`: %r" % s)
            stmts.append(parse_statement(s[:-1].strip()))
        else:
            keep.append(ln)
    if MUT == "M_PS_V1_BYPASS":
        v1 = None
    else:
        try:
            v1 = pit_emit.parse("\n".join(keep))
        except pit_emit.SpecError as e:
            raise SpecError("v1: %s" % e)
    return {"v1": v1, "poset": stmts}


# ---------------------------------------------------------------------------
# canonical rendering
# ---------------------------------------------------------------------------

def render_ast(n):
    if n[0] == "ev":
        return "%s(%s)" % (n[1], ", ".join("uio%d" % w for w in n[2]))
    if n[0] == "rep":
        inner = render_ast(n[2])
        return "[%d ->] %s" % (n[1], inner if n[2][0] == "ev" else "(%s)" % inner)
    _b, op, l, r = n
    rs = render_ast(r)
    if r[0] == "bin":                       # left-associative: a right operand group needs parens
        rs = "(%s)" % rs
    return "%s %s %s" % (render_ast(l), op, rs)


def render_statement(st):
    s = "%s %s" % (st["kind"], render_ast(st["ast"]))
    if st["during"]:
        s += " during (%s ns, %s ns)" % st["during"]
    if st["observed"] is not None:
        s += " observed %d" % st["observed"]
    if st["given"]:
        s += " given %s" % st["given"]
    if st["source"] == "data":
        s += " source data"
    elif st["source"]:
        s += ' source datasheet "%s"' % st["source"][1]
    return s + ";"
