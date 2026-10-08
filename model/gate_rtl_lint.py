"""Ruling RL1 -- the RTL's own race classes, linted on every push.

`gate_bench_races` covers the benches. The RTL gets Verilator's checks for the
same family, with these two as ERRORS:

  BLKSEQ   a blocking `=` in a clocked process -- the RTL twin of the Layer R
           race: another process reading that variable on the same edge sees
           whichever order the simulator chose, and synthesis may disagree
           with both.
  COMBDLY  a non-blocking `<=` in a combinational process -- the converse,
           which makes simulation lag the logic it describes by a delta.

⛔ ONE DECLARED EXCEPTION CLASS: a BLOCK-LOCAL TEMPORARY -- a variable written
with `=` and read ONLY inside the same clocked block (a loop accumulator). No
other process can observe it, so there is nothing to race. `TEMPS` names each
by (file, variable) with its reason, and the gate CHECKS the claim: every use of
the variable must sit inside one `always` block. The one in the tree is
`prime_unp` in `pe_engine.v`'s priming block, whose comment already records why
it is not a separate `always @*` (a function's internal reads make `@*`
sensitivity tool-dependent).

Other `-Wall` classes are REPORTED with their counts, not judged here.
Must-fires (on planted copies under probe_rl1/): a blocking assignment in a
clocked block (`ptr = ptr + 1` in project.v) is red; a `<=` in a combinational
block (`cfg_err <= config_err` in pe_engine.v) is red.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "test"))
from toolchain import banner, tool_or_none, PINNED_WSL_VERILATOR  # noqa: E402

ERRORS = ("BLKSEQ", "COMBDLY")
TEMPS = {
    ("pe_engine.v", "prime_unp"):
        "the priming block's loop accumulator: written and read only inside "
        "that `always @(posedge clk)`; see the comment above it for why it is "
        "not an `always @*`.",
    ("pe_engine.v", "hold_ld"):
        "RULING TF1: the lane block's 'a DRIVE arm starts an SDA hold' flag. "
        "Cleared at the top of the run branch, set by the four hold arms, read "
        "at the one `l_hcnt` load and the matching `hz_q` write -- all inside "
        "that one `always @(posedge clk)`. It exists so the counter and its "
        "registered zero-flag have ONE write site and cannot disagree.",
    ("pe_engine.v", "live_n"):
        "RULING TF2-R3: the lane block's next value of `l_live`. Loaded from "
        "`l_live` at the top of the run branch, written at every run-time "
        "halt / go-live site, and read only at the end of that same block to "
        "write `l_live` and the registered release term `rel_q`.",
    ("pe_engine.v", "armed_n"):
        "RULING TF2-R3: as `live_n`, for `l_armed` (WB arm, clocked park, "
        "timeout halt, stretch fault, edge-capture disarm).",
    ("pe_engine.v", "notmo_n"):
        "RULING TF2-R3: as `live_n`, for `l_notmo` (WB arm, clocked park).",
}
SCRATCH = os.path.join(ROOT, "probe_rl1")
WARN = re.compile(r"^%(?:Warning|Error)-([A-Z0-9_]+): (\S+?):(\d+):")


def wsl_path(p):
    full = os.path.abspath(p)
    if os.name != "nt":
        return full
    drive, rest = os.path.splitdrive(full)
    return "/mnt/%s%s" % (drive[0].lower(), rest.replace("\\", "/"))


def lint(src_dir, log):
    """Run test/rtl_lint.sh natively or via WSL (with the pin); return text."""
    sc = os.path.join(ROOT, "test", "rtl_lint.sh")
    if tool_or_none("verilator") or os.name != "nt":
        cmd = ["bash", sc, src_dir, log]
    else:
        cmd = ["wsl.exe", "--", "env", "PE_VERILATOR=%s" % PINNED_WSL_VERILATOR,
               "bash", wsl_path(sc), wsl_path(src_dir), wsl_path(log)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    print("    " + "\n    ".join(l for l in r.stdout.splitlines() if l.strip()))
    if not os.path.isfile(log):
        return None
    with open(log, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def blocks_of(text):
    """[(start_line, end_line)] of every `always` block (begin/end matched)."""
    out = []
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if re.match(r"\s*always\b", ln):
            depth, j, seen = 0, i, False
            for j in range(i, len(lines)):
                code = lines[j].split("//", 1)[0]
                for t in re.findall(r"\b(begin|end)\b", code):
                    depth += 1 if t == "begin" else -1
                    seen = True
                if seen and depth == 0:
                    break
            out.append((i + 1, j + 1))
    return out


def var_at(text, line):
    """The LHS identifier of the blocking assignment on `line`."""
    m = re.search(r"([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*=(?!=)",
                  text.splitlines()[line - 1].split("//", 1)[0])
    return m.group(1) if m else None


def temp_ok(text, var):
    """True if every use of `var` (past its declaration) is in ONE block."""
    uses = [i + 1 for i, ln in enumerate(text.splitlines())
            if re.search(r"\b%s\b" % re.escape(var), ln.split("//", 1)[0])
            and not re.match(r"\s*(reg|integer|wire|logic)\b", ln)]
    for a, b in blocks_of(text):
        if uses and all(a <= u <= b for u in uses):
            return True
    return False


def judge(log_text, src_dir):
    probs, counts = [], {}
    srcs = {}
    for ln in log_text.splitlines():
        m = WARN.match(ln)
        if not m:
            continue
        rule, path, line = m.group(1), m.group(2), int(m.group(3))
        counts[rule] = counts.get(rule, 0) + 1
        if rule not in ERRORS:
            continue
        fn = os.path.basename(path)
        if fn not in srcs:
            with open(os.path.join(src_dir, fn), encoding="utf-8",
                      errors="replace") as fh:
                srcs[fn] = fh.read()
        var = var_at(srcs[fn], line) if rule == "BLKSEQ" else None
        if var and (fn, var) in TEMPS and temp_ok(srcs[fn], var):
            continue
        probs.append("%s at %s:%d%s" % (rule, fn, line,
                                        " (`%s`)" % var if var else ""))
    return probs, counts


def planted(name, fn, old, new):
    d = os.path.join(SCRATCH, name)
    if os.path.isdir(d):
        shutil.rmtree(d)
    shutil.copytree(os.path.join(ROOT, "src"), d)
    p = os.path.join(d, fn)
    with open(p, encoding="utf-8") as fh:
        s = fh.read()
    if s.count(old) != 1:
        raise SystemExit("must-fire anchor %r not unique in %s" % (old, fn))
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(s.replace(old, new))
    return d


def main() -> int:
    banner("verilator")
    print()
    print("=" * 78)
    print("  RL1 -- RTL LINT: BLKSEQ and COMBDLY are errors")
    print("=" * 78)
    os.makedirs(SCRATCH, exist_ok=True)
    rc = 0
    txt = lint(os.path.join(ROOT, "src"), os.path.join(SCRATCH, "clean.log"))
    if txt is None:
        print("  *** the lint produced no log -- RED, not skipped")
        return 1
    probs, counts = judge(txt, os.path.join(ROOT, "src"))
    print("  -Wall classes on src/: %s"
          % (", ".join("%s %d" % kv for kv in sorted(counts.items())) or "none"))
    print("  declared block-local temporaries: %s"
          % ", ".join("%s:%s" % k for k in sorted(TEMPS)))
    for p in probs:
        print("  *** %s" % p)
        rc = 1
    if not probs:
        print("  no BLKSEQ or COMBDLY outside a checked block-local temporary")

    print()
    print("  --- must-fire ---")
    d1 = planted("blkseq", "project.v",
                 "else if (wr_rise)    ptr <= ptr + 1'b1;",
                 "else if (wr_rise)    ptr = ptr + 1'b1;")
    t1 = lint(d1, os.path.join(SCRATCH, "blkseq.log"))
    p1, _ = judge(t1 or "", d1)
    hit1 = any(p.startswith("BLKSEQ") and "ptr" in p for p in p1)
    print("    a blocking `ptr = ...` in a clocked block     %s"
          % ("ok" if hit1 else "*** MISSED"))
    d2 = planted("combdly", "pe_engine.v",
                 "always @(*) cfg_err = config_err;",
                 "always @(*) cfg_err <= config_err;")
    t2 = lint(d2, os.path.join(SCRATCH, "combdly.log"))
    p2, _ = judge(t2 or "", d2)
    hit2 = any(p.startswith("COMBDLY") for p in p2)
    print("    a `<=` in a combinational block              %s"
          % ("ok" if hit2 else "*** MISSED"))
    if not (hit1 and hit2):
        rc = 1

    print()
    print("=" * 78)
    print("  GATE rtl-lint: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
