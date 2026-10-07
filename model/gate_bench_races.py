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


def blocks(src):
    out = []
    for m in re.finditer(r"\balways\s*@\s*\(([^)]*)\)\s*", src):
        sens = re.sub(r"\s+", " ", m.group(1).strip())
        i, j = m.end(), None
        if src.startswith("begin", i):
            depth = 0
            for t in re.finditer(r"\b(begin|end)\b", src[i:]):
                depth += 1 if t.group(1) == "begin" else -1
                if depth == 0:
                    j = i + t.end()
                    break
        else:
            j = src.index(";", i) + 1
        out.append((sens, src[i:j]))
    return out


def races(text):
    """[(variable, reader-block excerpt)] for undeclared same-edge reads."""
    bl = blocks(strip(text))
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
        found = races(expand(p))
        n += 1
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
    if not (hit and hit2 and hit3):
        rc = 1

    print()
    print("=" * 78)
    print("  GATE bench-races: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
