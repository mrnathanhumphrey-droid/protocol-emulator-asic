"""HALT RESET GATE -- the halt state equals the reset state (WF2 #9-#11).

⛔⛔ WHY. The power-on reset and the halt clear were two hand-written lists,
and they drifted: the halt cleared PCs, arms and `pin_oe` and nothing else, so
the bit pointers (#9), the pads' levels (#10) and the clocked-lane phase state
(#11 -- `l_ckbit` left at 7 made the first clocked SHIFT after a reload 16
bits long) all survived a reload into the next program.
⭐ THE FIX HOLDS BY CONSTRUCTION (Wilson): the register list lives ONCE, at
the top of `src/pe_engine.v` (in the file, not an include -- most tools and
the gates' scratch copies were not given an include path), as one macro per
always block, and each block expands
the same macro in its async power-on branch and its synchronous `!run` halt
branch. This gate is the SECOND check, for what construction cannot see:

  1. every `always @(posedge clk or negedge rst_n)` block in `src/pe_engine.v`
     resets ONLY through `PE_RST_*` macros -- a raw assignment in a power-on
     branch is a register declared outside the list (RED);
  2. each such block has a `!run` halt branch expanding the SAME macros, minus
     `PE_RST_KEEP` (RED if missing or different);
  3. `PE_RST_KEEP` (power-on only: status the host reads AFTER halting) names
     EXACTLY the ruled status flags -- anything more on it is a register that
     would quietly survive a reload (RED);
  4. no macro name is expanded in a power-on branch that the list file does
     not define, and every `PE_RST_*` the list defines is used.

MUST-FIRES (on mutated copies of the real text, never on the tree): a raw
assignment added to a power-on branch; a block's halt branch removed; an extra
name on the keep-list. Each must turn the gate red.

Usage: python model/gate_halt_reset.py [--root DIR]   (DIR holds pe_engine.v;
default src/)
Verdict: `HALT-RESET GATE: PASSED` or `*** FAIL ...`.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEEP_RULED = {"l_timeout", "sticky_ovr", "config_err", "clk_stretch_err",
              "lane_underrun", "lane_overflow"}
BLOCK_HEAD = "always @(posedge clk or negedge rst_n)"


def strip_comments(txt):
    txt = re.sub(r"/\*.*?\*/", " ", txt, flags=re.S)
    return re.sub(r"//[^\n]*", "", txt)


def macros(list_txt):
    """name -> body, for every `define in the list file (continuations
    joined)."""
    out = {}
    lines = strip_comments(list_txt).replace("\\\n", " ").split("\n")
    for ln in lines:
        m = re.match(r"\s*`define\s+(\w+)\s*(.*)$", ln)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def assigned(body):
    """register names assigned (`name <=` or `name[...] <=`) in a body."""
    return set(re.findall(r"(\w+)\s*(?:\[[^\]]*\])?\s*<=", body))


def branch(txt, i):
    """the statement starting at txt[i]: a `begin ... end` (balanced) or a
    single statement up to its `;` / its macro token. -> (text, end index)."""
    j = i
    while txt[j].isspace():
        j += 1
    if txt.startswith("begin", j):
        depth, k = 0, j
        for m in re.finditer(r"\b(begin|end)\b", txt[j:]):
            depth += 1 if m.group(1) == "begin" else -1
            if depth == 0:
                k = j + m.end()
                return txt[j:k], k
        raise ValueError("unbalanced begin/end")
    if txt[j] == "`":
        m = re.match(r"`\w+", txt[j:])
        return m.group(0), j + m.end()
    k = txt.index(";", j)
    return txt[j:k + 1], k + 1


def check(engine_txt, list_txt):
    """-> list of problems (empty = green)."""
    p = []
    defs = macros(list_txt)
    rst_defs = {n for n in defs if n.startswith("PE_RST_")}
    keep = assigned(defs.get("PE_RST_KEEP", ""))
    if "PE_RST_KEEP" not in defs:
        p.append("the list defines no PE_RST_KEEP")
    elif keep != KEEP_RULED:
        p.append("PE_RST_KEEP names %s; the ruled keep-list is exactly %s"
                 % (sorted(keep), sorted(KEEP_RULED)))
    used = set()
    txt = strip_comments(engine_txt)
    starts = [m.start() for m in re.finditer(re.escape(BLOCK_HEAD), txt)]
    if not starts:
        p.append("no `%s` block found in the engine" % BLOCK_HEAD)
    for s in starts:
        line = txt.count("\n", 0, s) + 1
        m = re.compile(r"if\s*\(\s*!\s*rst_n\s*\)").search(txt, s)
        if not m:
            p.append("block at line %d: no `if (!rst_n)` branch" % line)
            continue
        por, k = branch(txt, m.end())
        por_mac = set(re.findall(r"`(PE_RST_\w+)", por))
        raw = assigned(re.sub(r"`\w+", " ", por))
        if raw:
            p.append("block at line %d: power-on branch assigns %s directly, "
                     "outside the shared list" % (line, sorted(raw)))
        if not por_mac:
            p.append("block at line %d: power-on branch expands no PE_RST_* "
                     "macro" % line)
        for n in por_mac - rst_defs:
            p.append("block at line %d: `%s is not defined in the list"
                     % (line, n))
        used |= por_mac
        h = re.compile(r"\s*else\s+if\s*\(\s*!\s*run\s*\)").match(txt, k)
        if not h:
            p.append("block at line %d: no `else if (!run)` HALT branch right "
                     "after the power-on branch -- the halt does not clear "
                     "this block" % line)
            continue
        halt, _ = branch(txt, h.end())
        halt_mac = set(re.findall(r"`(PE_RST_\w+)", halt))
        want = por_mac - {"PE_RST_KEEP"}
        if halt_mac != want:
            p.append("block at line %d: halt branch expands %s, power-on "
                     "expands %s (minus the keep-list) -- they must be the "
                     "same list" % (line, sorted(halt_mac), sorted(want)))
        if "PE_RST_KEEP" in halt_mac:
            p.append("block at line %d: the halt clears the KEEP-list (status "
                     "the host reads after halting)" % line)
    for n in sorted(rst_defs - used - {"PE_RST_SHBITP"}):
        p.append("the list defines `%s but no block expands it" % n)
    return p


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read().replace("\r\n", "\n")


def main():
    root = os.path.join(ROOT, "src")
    if "--root" in sys.argv:
        root = os.path.abspath(sys.argv[sys.argv.index("--root") + 1])
    try:
        eng = read(os.path.join(root, "pe_engine.v"))
    except OSError as e:
        print("*** FAIL halt_reset: cannot read the engine (%s)" % e)
        return 1
    lst = eng                       # the list is defined in the engine itself
    print("HALT RESET -- one list for power-on and halt (%s)"
          % os.path.relpath(root, ROOT))
    probs = check(eng, lst)
    n_blk = len(re.findall(re.escape(BLOCK_HEAD), strip_comments(eng)))
    print("  %d reset block(s); keep-list %s"
          % (n_blk, sorted(assigned(macros(lst).get("PE_RST_KEEP", "")))))
    for q in probs:
        print("  *** " + q)

    # ---- must-fires, on mutated copies of the real text ------------------
    mf_ok = True
    m1 = eng.replace("      `PE_RST_MAIN\n      `PE_RST_KEEP\n",
                     "      `PE_RST_MAIN\n      `PE_RST_KEEP\n"
                     "      stray_reg <= 1'b0;\n", 1)
    m2 = re.sub(r"else if \(!run\)\s+`PE_RST_NOW[^\n]*\n", "", eng, count=1)
    m3 = eng.replace("lane_overflow   <= {N_LANES{1'b0}}; \\",
                     "lane_overflow   <= {N_LANES{1'b0}}; \\\n"
                     "      l_ckbit[0] <= {BPW{1'b0}}; \\", 1)
    for name, e in (("raw assignment in a power-on branch", m1),
                    ("a block's halt branch removed", m2),
                    ("an extra name on the keep-list", m3)):
        changed = e != eng
        red = changed and bool(check(e, e))
        print("  must-fire  %-40s %s" % (name, "red" if red else
                                         "*** NOT RED%s" % (
                                             "" if changed else
                                             " (the mutation did not apply)")))
        mf_ok = mf_ok and red

    if not probs and mf_ok:
        print("HALT-RESET GATE: PASSED")
        return 0
    print("*** FAIL halt_reset: %d problem(s)%s" % (
        len(probs), "" if mf_ok else "; a must-fire did not fire"))
    return 1


if __name__ == "__main__":
    sys.exit(main())
