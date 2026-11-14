"""Ruling RA3 -- no bench layer reads, on the same clock edge, a variable that
another `always` block writes with a BLOCKING assignment.

⛔⛔ WHY. Layer R (refills per retired clocked action) closed its window by
reading Layer B's `cb_pc` / `cb_ck` / `cb_op` / `cb_cnt` / `cb_n`, which Layer
B writes with blocking assignments in its own `always @(posedge dut.clk)`.
Which of two same-edge blocks runs first is the SIMULATOR's choice. Verilator
ran R first and saw the PC change; iverilog ran B first, so R never closed a
window, and the CLEAN design failed R under iverilog (13 of 64 actions "over
the bound", worst 9). The verdict was a property of scheduling, not of the
design -- and every R number accepted before the fix had been measured with
it (re-measured under ruling RA1: unchanged, identical on both simulators).

⇒ For each bench, with its `include`s EXPANDED (a bench and its layers share
  one module scope), every variable written by a blocking `=` in one
  `always @(<edge>)` block and read in ANOTHER block on the SAME sensitivity is
  RED -- unless declared in `SAFE` with the reason it cannot race.
⇒ Non-blocking (`<=`) writes are not counted: a same-edge reader sees the old
  value by the language's own rule, whatever the order.

⭐ THE MODEL FOR A SAFE READ is R5's: it reads `cb_ck` / `cb_n` for a dispatch
it latched one edge EARLIER, and Layer B cannot write the same lane again on
the very next edge (the dispatch FSM is a three-state cycle), so the value is
settled whichever block runs first. A declaration names the READING block by
an anchor token that block must contain, so the same variable read from a
different block is not covered by it.
"""

from __future__ import annotations

import glob
import io
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

KW = set("begin end if else for while repeat forever case casez casex endcase "
         "default integer reg wire posedge negedge or always initial final "
         "assign".split())

#: (variable, anchor token in the READING block) -> why it cannot race.
SAFE = {
    ("cb_ck", "p5_mid"): "R5 reads it for the dispatch it latched ONE EDGE "
                         "EARLIER (`p4_wb`); Layer B cannot write the same "
                         "lane on the next edge (three-state dispatch cycle).",
    ("cb_n", "p5_mid"): "same read, same reason: the dispatch count R5 prints "
                        "for a dispatch latched one edge earlier.",
}

FIXTURE = os.path.join(HERE, "fixtures", "clocked_conform_231b37c.vh.txt")


def strip(src):
    """Comments and string literals blanked, line numbers kept."""
    src = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), src,
                 flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    return re.sub(r'"(?:\\.|[^"\\\n])*"', '""', src)


def expand(path, seen=None, override=None):
    """The bench with every `include "..."` that resolves inside the repo
    spliced in. `override` maps an include path to replacement text (used
    by the must-fire)."""
    seen = set() if seen is None else seen
    with io.open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()

    def rep(m):
        inc = m.group(1)
        for cand in (inc, os.path.join("test", inc)):
            key = cand.replace("\\", "/")
            if override and key in override:
                return override[key]
            full = os.path.join(ROOT, cand)
            if os.path.isfile(full) and full not in seen:
                seen.add(full)
                return expand(full, seen, override)
        return ""
    return re.sub(r'`include\s+"([^"]+)"', rep, text)


_COND = re.compile(r"`(ifdef|ifndef|elsif|else|endif)\b[ \t]*(\w*)")


def _cond_tree(src):
    """[str | [branch, ...]]: the text split at `ifdef/`ifndef/`elsif/`else/
    `endif, each conditional a list of its branches (each branch itself a
    tree). Line numbers kept: directive lines are blanked, not removed."""
    stack = [[]]                 # the current branch's item list
    conds = []                   # open conditionals: [branch, ...]
    pos = 0
    for m in _COND.finditer(src):
        stack[-1].append(src[pos:m.start()])
        kw = m.group(1)
        if kw in ("ifdef", "ifndef"):
            c = [[]]
            stack[-1].append(c)
            conds.append(c)
            stack.append(c[0])
        elif kw in ("elsif", "else"):
            if not conds:
                raise ValueError("`%s with no open conditional" % kw)
            stack.pop()
            conds[-1].append([])
            stack.append(conds[-1][-1])
        else:                    # endif
            if not conds:
                raise ValueError("`endif with no open conditional")
            stack.pop()
            conds.pop()
        pos = m.end()
    stack[-1].append(src[pos:])
    if conds:
        raise ValueError("%d unterminated conditional(s)" % len(conds))
    return stack[0]


def _width(tree):
    return max([1] + [max(len(it), max(_width(b) for b in it))
                      for it in tree if isinstance(it, list)])


def _pick(tree, k):
    """The text with branch min(k, last) taken at every conditional (an
    `ifdef with no `else has an empty last branch)."""
    out = []
    for it in tree:
        if isinstance(it, str):
            out.append(it)
        else:
            br = list(it) + ([[]] if len(it) == 1 else [])
            out.append(_pick(br[min(k, len(br) - 1)], k))
    return "".join(out)


def variants(src):
    """⭐ Wilson 11-14: the bench as the COMPILER sees it, one variant per
    branch index -- variant k takes branch k (or the last) of every
    conditional, so every branch of every `ifdef is scanned in at least one
    variant, never both branches of one conditional in the same text (the
    raw text, with both, unbalanced begin/end and swallowed later blocks)."""
    tree = _cond_tree(src)
    w = _width(tree)
    return [_pick(tree, k) for k in range(max(w, 2))]


def cond_problems(src):
    """[problem]: a conditional whose branches leave different begin/end
    depth -- each branch must balance the same way, or no reading of the text
    (ours or a reader's) agrees on where blocks end."""
    out = []

    def net(tree):
        n = 0
        for it in tree:
            if isinstance(it, str):
                n += len(re.findall(r"\b(?:begin|case|casez|casex|fork)\b", it))
                n -= len(re.findall(r"\b(?:end|endcase|join)\b", it))
            else:
                ns = [net(b) for b in it] + ([0] if len(it) == 1 else [])
                if len(set(ns)) > 1:
                    out.append("an `ifdef whose branches open/close begin-end "
                               "differently (net %s)" % ns)
                n += ns[0]
        return n
    try:
        net(_cond_tree(src))
    except ValueError as e:
        out.append(str(e))
    return out


_TOK = re.compile(r"\b(begin|end|fork|join|join_any|join_none|case|casez|casex|"
                  r"endcase|if|else|for|while|repeat|forever)\b|[;()@#]")


def _skip_ws(src, i):
    while i < len(src) and src[i].isspace():
        i += 1
    return i


def _paren(src, i):
    """i at '(' -> index after its matching ')'."""
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "(":
            depth += 1
        elif src[j] == ")":
            depth -= 1
            if depth == 0:
                return j + 1
    raise ValueError("unbalanced parenthesis")


def _stmt(src, i):
    """One Verilog statement starting at i -> the index just after it. Handles
    begin/end, fork/join, case/endcase, if/else chains, loops, event and delay
    controls; anything else runs to its `;`."""
    i = _skip_ws(src, i)
    m = re.compile(r"\w+|.").match(src, i)
    w = m.group(0) if m else ""
    if w in ("begin", "fork"):
        close = ("end",) if w == "begin" else ("join", "join_any", "join_none")
        depth = 0
        for t in re.finditer(r"\b(begin|end|fork|join|join_any|join_none)\b", src[i:]):
            g = t.group(1)
            depth += 1 if g in ("begin", "fork") else -1
            if depth == 0:
                return i + t.end()
        raise ValueError("unterminated %s" % w)
    if w in ("case", "casez", "casex"):
        depth = 0
        for t in re.finditer(r"\b(case|casez|casex|endcase)\b", src[i:]):
            depth += -1 if t.group(1) == "endcase" else 1
            if depth == 0:
                return i + t.end()
        raise ValueError("unterminated case")
    if w == "if":
        j = _paren(src, _skip_ws(src, i + 2))
        j = _stmt(src, j)
        k = _skip_ws(src, j)
        if re.match(r"else\b", src[k:]):
            return _stmt(src, k + 4)
        return j
    if w in ("for", "while", "repeat"):
        return _stmt(src, _paren(src, _skip_ws(src, i + len(w))))
    if w == "forever":
        return _stmt(src, i + 7)
    if w == "@":
        k = _skip_ws(src, i + 1)
        k = _paren(src, k) if src.startswith("(", k) else k + 1
        return _stmt(src, k)
    if w == "#":
        k = re.compile(r"#\s*(\([^)]*\)|[\w.]+)").match(src, i).end()
        return _stmt(src, k)
    return src.index(";", i) + 1


def blocks(src):
    """[(sensitivity, body)] for every `always @(...)` -- each body read to its
    TRUE end by a statement parser (Wilson 11-14: `always @(...) if (...)
    begin ... end` was cut at its first `;`, under-reading the block)."""
    out = []
    for m in re.finditer(r"\balways\s*@\s*\(([^)]*)\)\s*", src):
        sens = re.sub(r"\s+", " ", m.group(1).strip())
        i = m.end()
        out.append((sens, src[i:_stmt(src, i)]))
    return out


def races(text):
    """[(variable, sensitivity)] for undeclared same-edge reads, over every
    conditional-compilation variant of the text (union, de-duplicated)."""
    seen, out = set(), []
    for v in variants(strip(text)):
        for r in _races(v):
            if r not in seen:
                seen.add(r)
                out.append(r)
    return out


def _races(src):
    bl = blocks(src)
    writes = {}
    for n, (_s, b) in enumerate(bl):
        for m in re.finditer(r"(?<![\w.])([A-Za-z_]\w*)\s*(\[[^\]]*\])?\s*"
                             r"(<?)=(?!=)", b):
            if m.group(3) == "" and m.group(1) not in KW:
                writes.setdefault(m.group(1), set()).add(n)
    out = []
    for n, (sens, b) in enumerate(bl):
        toks = set(re.findall(r"(?<![\w.$`])([A-Za-z_]\w*)", b)) - KW
        for v in sorted(toks):
            if v not in writes or n in writes[v]:
                continue
            if not any(bl[k][0] == sens for k in writes[v]):
                continue
            if any(var == v and re.search(r"\b%s\b" % anchor, b)
                   for (var, anchor) in SAFE):
                continue
            out.append((v, sens))
    return out


def benches():
    return sorted(p for p in glob.glob(os.path.join(ROOT, "test", "*.v"))
                  if not os.path.basename(p).startswith("probe_"))


def main() -> int:
    print()
    print("=" * 78)
    print("  RA3 -- NO SAME-EDGE READ OF ANOTHER BLOCK'S BLOCKING WRITE")
    print("=" * 78)
    rc = 0
    n = 0
    for p in benches():
        text = expand(p)
        found = races(text)
        n += 1
        for c in cond_problems(strip(text)):
            print("  *** %s: %s" % (os.path.relpath(p, ROOT), c))
            rc = 1
        for v, sens in found:
            print("  *** %s: `%s` is read in one `always @(%s)` block and "
                  "written with `=` in another -- the result depends on which "
                  "the simulator runs first" % (os.path.relpath(p, ROOT), v, sens))
            rc = 1
    print("  %d bench/model file(s) scanned with includes expanded; %d declared "
          "safe read(s)" % (n, len(SAFE)))
    if rc == 0:
        print("  no undeclared same-edge cross-block read")

    print()
    print("  --- must-fire ---")
    with io.open(FIXTURE, encoding="utf-8") as fh:
        old = fh.read()
    tb = os.path.join(ROOT, "test", "tb_trace.v")
    pre = races(expand(tb, override={"test/clocked_conform.vh": old}))
    hit = {v for v, _s in pre} >= {"cb_pc", "cb_op", "cb_cnt"}
    print("    Layer R as it stood at 231b37c (pre-fix)       %s  %s"
          % ("ok" if hit else "*** MISSED", sorted({v for v, _ in pre})))
    syn = ("module m; reg clk; integer a, b;\n"
           "always @(posedge clk) begin a = a + 1; end\n"
           "always @(posedge clk) begin b = a; end\nendmodule\n")
    hit2 = [v for v, _ in races(syn)] == ["a"]
    print("    a synthetic same-edge read of a blocking write %s"
          % ("ok" if hit2 else "*** MISSED"))
    syn_nb = syn.replace("a = a + 1", "a <= a + 1")
    hit3 = not races(syn_nb)
    print("    the same read of a NON-blocking write passes   %s"
          % ("ok" if hit3 else "*** WRONGLY RED"))
    # ⭐ Wilson 11-14: the two places the parser could not see
    syn_if = ("module m; reg clk; integer a, b;\n"
              "always @(posedge clk) if (1) begin b <= 0; a = a + 1; end\n"
              "always @(posedge clk) begin b <= a; end\nendmodule\n")
    hit4 = [v for v, _ in races(syn_if)] == ["a"]
    print("    a race after the first `;` of `if (...) begin` %s"
          % ("ok" if hit4 else "*** MISSED"))
    # the reader's two `ifdef branches each open a `begin`: read raw, the
    # block runs past its end and swallows the writer below, so the write
    # looked like the reader's own (the 11-14 progress.vh shape)
    syn_def = ("module m; reg clk; integer a, b;\n"
               "always @(posedge clk) begin\n"
               "`ifdef X\n  if (1'b0) begin\n`else\n  if (1) begin\n`endif\n"
               "    b <= a;\n  end\nend\n"
               "always @(posedge clk) begin a = a + 1; end\n"
               "endmodule\n")
    hit5 = [v for v, _ in races(syn_def)] == ["a"] and not cond_problems(syn_def)
    print("    a race inside an `ifdef branch                %s"
          % ("ok" if hit5 else "*** MISSED"))
    unbal = syn_def.replace("  if (1) begin\n", "  if (1)\n")
    hit6 = bool(cond_problems(unbal))
    print("    an `ifdef whose branches unbalance begin/end   %s"
          % ("red  ok" if hit6 else "*** MISSED"))
    if not (hit and hit2 and hit3 and hit4 and hit5 and hit6):
        rc = 1

    print()
    print("=" * 78)
    print("  GATE bench-races: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
