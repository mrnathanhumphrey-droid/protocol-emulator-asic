"""MUTANT ARM DRIFT GUARD -- the ifdef must wrap the minimal delta, nothing else.

THE ONE CLAIM: for every mutant define, preprocessing the sources with and
without it differs by EXACTLY the intended mutation. Any other difference means
the two arms have drifted apart.

⛔⛔⛔ WHY THIS EXISTS, AND IT IS NOT HYPOTHETICAL. 1.6s's refusal-to-dispatch
went in as `ST_IDLE: if (hdr_done && !config_err && winner_v)` -- and landed in
the `M_NO_PRIME` MUTANT ARM. The guard line was DUPLICATED either side of an
`ifdef`, a text edit hit one copy, and the default path (which gates on
`primed`, not `hdr_done`) never got it. The violating program ran, every other
gate stayed green, and only the new must-fire caught it.
⇒ A FIX THAT LANDS IN A MUTANT ARM IS NOT IN THE DESIGN. The failure mode is
  duplicated ACTIVE LOGIC inside an `ifdef`, so the structural answer is to
  forbid the duplication and check it mechanically.

## The rules, each checked

  1. SIZE IS THE SIGNAL FOR DUPLICATION, NOT COUNT EQUALITY. An early version
     required the diff to remove as many lines as it adds, on the theory that a
     mutation is a substitution. ⛔ That is wrong: an `ifndef` mutant legitimately
     DELETES one line (M_NO_REBASE drops the rebase), and a duplicated block
     shows up as a LARGE diff with EQUAL counts -- the opposite of what the rule
     would have caught. So the budget below is the duplication check.
  2. NO COMMENTS IN THE DIFF. A comment that appears in only one arm proves the
     `ifdef` wraps more than the delta -- the comment is not the mutation. This
     found a real instance on the first run.
  3. NON-EMPTY. A mutant whose diff is empty changes nothing and is dead
     weight that reads as coverage.
  4. SIZE BUDGET, with declared exceptions. Anything above `MINIMAL` lines must
     carry a stated reason, so a block swap is a decision on the record rather
     than a habit.
  5. NO DRIFT. The diff must equal the recorded expectation line for line.

⚠ RULE 5 IS RECORDED FROM INSPECTION, NOT AUTO-ACCEPTED. A table generated from
whatever the source happens to say would certify the current state as intended,
which is the fitted-to-observation failure. The counts and reasons below were
read one at a time; rules 1-4 hold independently of them, so even a wrong
expectation cannot make a duplicated block pass.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")
SOURCES = ["pe_engine.v", "project.v", "pe_store.v"]

MINIMAL = 4          # lines of preprocessed diff that need no excuse

# mutant -> (expected total diff lines, reason if above MINIMAL)
EXPECT = {
    "M_NOOP_DRIVES":     (2, None),
    "M_NO_REBASE":       (1, None),
    "M_PFETCH_NOWAIT":   (2, None),
    "M_BUF_NOINVAL":     (2, None),
    "M_BUF_SWAP":        (2, None),
    "M_COMB_OUT":        (4, None),
    "M_NO_PRIME":        (4, None),
    "M_BUF_CHAINFLIP":   (3, None),
    # ⭐ TWO LINES, WHICH IS ONE SUBSTITUTION: `assign host_q = a_q;` becomes
    # `assign host_q = 2'd0;`, so the diff is one line removed and one added --
    # the same shape as M_BUF_SWAP and M_PFETCH_NOWAIT. The queue tag is a
    # single expression, so nothing else moves with it, which is what makes
    # this a clean price on the field rather than on a block.
    "M_TX_IGNORE_TAG":   (2, None),
    "M_SHIFT_CLK_ALIAS": (6,
        "a BLOCK substitution, declared: the refusal has to suppress BOTH the "
        "data write and the clock write, so removing it removes an if/else "
        "whose begin and end bracket two separate assignment groups -- the "
        "`else begin` and its closing `end` are in different `ifndef` arms. "
        "⚠ The first version of the guard put only the data write inside the "
        "else, and the clock write then drove the aliased pin anyway: a "
        "refusal that still drives the pin it refuses is the defect with a "
        "flag set beside it."),
    "M_TIMEOUT_PROCEED": (6,
        "a BLOCK substitution, declared: the mutation removes the halt -- "
        "clearing l_live, l_armed and the sticky flag -- and there is no single "
        "expression whose value expresses 'do not halt'. The arms share no "
        "duplicated logic; the whole block is the delta."),
    "M_OD_CLK_PUSHPULL": (9,
        "a BLOCK substitution, declared: restoring D2 means removing BOTH the "
        "l_mode branch on the clock pin AND the 1.5 pin_pp mask, because with "
        "1.5 built the mask alone would suppress the hard 1 and the mutant "
        "would no longer reproduce the defect it prices. Two coupled changes, "
        "so no single expression carries it."),
}


def discover():
    """⛔ MATCH `ifdef`/`ifndef`, NOT A BARE `M_` PATTERN. A loose scan for
    `M_[A-Z_]+` reports `M_TYPE`, which does not exist -- it is the tail of
    `MEM_TYPE`. That is the same false-positive class as `F7` in the ruling
    audit, and a phantom mutant with an empty diff would trip rule 3 forever."""
    found = set()
    for fn in SOURCES:
        with open(os.path.join(SRC, fn), encoding="utf-8") as fh:
            for m in re.finditer(r"`(?:ifdef|ifndef)\s+(M_[A-Z0-9_]+)", fh.read()):
                found.add(m.group(1))
    return sorted(found)


def preprocess(fn, define=None):
    out = os.path.join(tempfile.gettempdir(), "pe_pp_%s.v" % (define or "off"))
    cmd = ["iverilog", "-E", "-o", out]
    if define:
        cmd.append("-D" + define)
    cmd.append(os.path.join(SRC, fn))
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if r.returncode != 0 or not os.path.isfile(out):
        return None
    with open(out, encoding="utf-8", errors="replace") as fh:
        # ⛔ BLANK LINES ARE DROPPED. The preprocessor emits an empty line
        # where each `ifdef`/`else`/`endif` stood, so when the two arms differ in
        # length those blanks SHIFT and a line differ reports them as changes --
        # it made every delta read 3x its real size. Whitespace is not a mutation
        # class, so removing it is safe and makes the count mean what it says.
        return [ln.rstrip() for ln in fh if ln.strip()]


def diff_lines(a, b):
    """The changed lines, as (sign, text). A plain set difference is enough:
    we only need WHAT changed, not where."""
    import difflib
    out = []
    for ln in difflib.unified_diff(a, b, lineterm="", n=0):
        if ln.startswith("+++") or ln.startswith("---") or ln.startswith("@@"):
            continue
        if ln.startswith("+"):
            out.append(("+", ln[1:].strip()))
        elif ln.startswith("-"):
            out.append(("-", ln[1:].strip()))
    return out


def is_comment(t):
    return t.startswith("//") or t.startswith("/*") or t.startswith("*")


def audit(src_dir=None):
    """Returns (rc, rows). `src_dir` lets the must-fire point at a mutated copy."""
    global SRC
    saved, rc, rows = SRC, 0, []
    if src_dir:
        SRC = src_dir
    try:
        for mut in discover():
            changed = []
            for fn in SOURCES:
                off = preprocess(fn)
                on = preprocess(fn, mut)
                if off is None or on is None:
                    rows.append((mut, 0, 0, 0, "*** preprocess FAILED"))
                    rc = 1
                    break
                changed += diff_lines(off, on)
            else:
                nadd = sum(1 for s, _ in changed if s == "+")
                ndel = sum(1 for s, _ in changed if s == "-")
                ncmt = sum(1 for _, t in changed if is_comment(t))
                flags = []
                exp, reason = EXPECT.get(mut, (None, None))
                if ncmt:
                    flags.append("%d COMMENT line(s) inside an arm: the ifdef "
                                 "wraps more than the delta" % ncmt)
                if nadd + ndel == 0:
                    flags.append("EMPTY: this mutant changes nothing")
                if nadd + ndel > MINIMAL and not reason:
                    flags.append("%d lines with no declared reason (budget %d)"
                                 % (nadd + ndel, MINIMAL))
                if exp is None:
                    flags.append("NOT IN THE EXPECT TABLE -- unreviewed")
                elif nadd + ndel != exp:
                    flags.append("DRIFT: %d diff lines, expected %d"
                                 % (nadd + ndel, exp))
                if flags:
                    rc = 1
                rows.append((mut, nadd, ndel, ncmt, "; ".join(flags)))
    finally:
        SRC = saved
    return rc, rows


def main() -> int:
    print()
    print("=" * 78)
    print("MUTANT ARM DRIFT GUARD -- the ifdef wraps the minimal delta")
    print("=" * 78)
    muts = discover()
    print("  mutants discovered (from `ifdef`/`ifndef`): %d" % len(muts))
    print()
    rc, rows = audit()
    print("  %-22s %5s %5s %5s  %s" % ("mutant", "+", "-", "cmt", "verdict"))
    print("  " + "-" * 74)
    for mut, nadd, ndel, ncmt, flags in rows:
        print("  %-22s %5d %5d %5d  %s"
              % (mut, nadd, ndel, ncmt, flags or "minimal, as recorded"))

    print()
    print("  --- declared block substitutions ---")
    for mut, (n, reason) in sorted(EXPECT.items()):
        if reason:
            print("    %s (%d lines)" % (mut, n))
            for line in _wrap(reason, 66):
                print("        %s" % line)

    # ---- MUST-FIRE: a drifted arm has to FAIL -------------------------
    # ⛔ The guard exists because a real edit landed in the wrong arm, so it is
    # priced by doing that on purpose: an extra line inside one branch of an
    # `ifdef` must make this red.
    print()
    print("  --- must-fire: a deliberately drifted arm ---")
    mf = "did not run"
    with tempfile.TemporaryDirectory() as td:
        for fn in SOURCES:
            with open(os.path.join(SRC, fn), encoding="utf-8") as fh:
                txt = fh.read()
            if fn == "pe_engine.v":
                # inject a line into ONE arm of M_NO_PRIME, as happened for real
                txt = txt.replace("`ifdef M_NO_PRIME\n",
                                  "`ifdef M_NO_PRIME\n// drifted arm\n", 1)
            with open(os.path.join(td, fn), "w", encoding="utf-8") as fh:
                fh.write(txt)
        drc, drows = audit(td)
        bad = [r for r in drows if r[0] == "M_NO_PRIME" and r[4]]
        if drc != 0 and bad:
            mf = "FIRED: %s" % bad[0][4][:120]
        else:
            mf = "*** DID NOT FIRE -- the guard would miss a drifted arm"
            rc = 1
    print("    %s" % mf)

    print()
    print("=" * 78)
    print("  GATE mutant-arms: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    * %d mutants, each checked for comment-free arms, a non-empty"
          % len(muts))
    print("      delta, a size budget with declared reasons (the duplication")
    print("      check), and no drift from the recorded diff.")
    print("    * the must-fire injects a line into ONE arm of M_NO_PRIME --")
    print("      the real failure -- and requires this gate to go red.")
    return rc


def _wrap(t, w):
    out, cur = [], ""
    for x in str(t).split():
        if cur and len(cur) + 1 + len(x) > w:
            out.append(cur)
            cur = x
        else:
            cur = (cur + " " + x) if cur else x
    if cur:
        out.append(cur)
    return out


if __name__ == "__main__":
    raise SystemExit(main())
