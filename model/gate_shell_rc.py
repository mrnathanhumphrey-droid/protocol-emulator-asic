"""E+ -- a shell exit code is read only where it can belong to its command.

⛔⛔ WHY (ruling E+). Four times in one arc a checking loop printed an exit code
that belonged to something else, and once it hid a gate that was really
exiting 1:

    cmd | tail; echo $?                        $? is tail's
    cmd | head; echo "rc=$?"                   $? is head's
    printf "%s %s" "$(basename $g)" "$?"       the substitution ran FIRST and
                                               reset $? to basename's 0

The third has no pipe in it, so `set -o pipefail` alone could not have caught
it. All four were in throwaway loops rather than committed scripts -- every
committed `$?` read is clean today -- so this gate GUARDS the committed
scripts going forward, and `ci/rc.sh`'s `run_rc` is the one way loops capture
a code.

RULES, over every `.sh` under ci/, test/ and model/:

  E1  the script sets `-o pipefail`.
  E3a no command substitution (`$(` or a backtick) BEFORE `$?` on its line.
  E3b `$?` does not read the status of a PIPELINE.
  E3c `$?` is read immediately: on the same line after `;`, or on the very
      next line -- no blank line, comment or block keyword in between.

Backslash-continued lines are joined first, so a multi-line command followed
by `rc=$?` is one command and one read. Text inside single quotes is not
shell and is not scanned. Named exceptions only, each with a reason.
"""

from __future__ import annotations

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

#: (path, logical line number) -> reason. ⛔ Keep this empty unless a read is
#: genuinely correct in a shape the rules cannot see.
EXCEPTIONS = {}

#: scripts exempt from E1 by name. ⛔ Only a SOURCED library belongs here: a
#: file that is `.`-sourced and runs `set -o pipefail` changes its CALLER's
#: shell options behind its back, which is a worse defect than the one E1
#: guards. Its own functions must still pass E3, and do.
PIPEFAIL_EXEMPT = {
    "ci/rc.sh": "a SOURCED helper (`. ci/rc.sh`); setting shell options in it "
                "would silently change the caller's shell. Contains no pipes.",
}

PIPEFAIL = re.compile(r"^\s*set\s+-[A-Za-z]*o\s+pipefail\b|^\s*set\s+-o\s+pipefail\b",
                      re.M)
BLOCK_KW = {"fi", "done", "esac", "then", "else", "do", "}", ")", ";;"}


def scripts():
    out = []
    for top in ("ci", "test", "model"):
        for d, _dirs, files in os.walk(os.path.join(ROOT, top)):
            for f in files:
                if f.endswith(".sh") and not f.startswith("probe_"):
                    out.append(os.path.relpath(os.path.join(d, f), ROOT)
                               .replace(os.sep, "/"))
    return sorted(out)


def logical_lines(text):
    """[(first_line_no, joined_text)] with backslash continuations joined."""
    out, buf, start = [], "", None
    for n, raw in enumerate(text.splitlines(), 1):
        if start is None:
            start = n
        if raw.rstrip().endswith("\\"):
            buf += raw.rstrip()[:-1] + " "
            continue
        out.append((start, buf + raw))
        buf, start = "", None
    if buf:
        out.append((start, buf))
    return out


def shell_view(line):
    """The line with single-quoted text and comments blanked out."""
    res, sq, dq, i = [], False, False, 0
    while i < len(line):
        c = line[i]
        if sq:
            res.append(" " if c != "'" else "'")
            sq = c != "'"
        elif c == "'" and not dq:
            sq = True
            res.append("'")
        elif c == '"':
            dq = not dq
            res.append(c)
        elif c == "\\" and i + 1 < len(line):
            res.append(c + line[i + 1])
            i += 1
        elif c == "#" and not dq and (i == 0 or line[i - 1] in " \t;"):
            break
        else:
            res.append(c)
        i += 1
    return "".join(res)


def has_pipe(seg):
    """An unquoted single `|` (not `||`)."""
    s = re.sub(r'"[^"]*"', '""', seg)
    return re.search(r"(?<!\|)\|(?!\|)", s) is not None


def audit_text(path, text):
    """Problems in one script's text. Pure, so the must-fires can price it."""
    probs = []
    if not PIPEFAIL.search(text) and path not in PIPEFAIL_EXEMPT:
        probs.append("%s: no `set -o pipefail` (E1)" % path)
    # ⛔ PER LOGICAL LINE. The first version ran `shell_view` over the WHOLE
    # file, and `shell_view` stops at the first comment -- the shebang on line
    # 1 -- so it saw nothing and this check could never fire. Caught by reading
    # it before it shipped, and now priced in the must-fires.
    if path in PIPEFAIL_EXEMPT and any(has_pipe(shell_view(t))
                                       for _n, t in logical_lines(text)):
        probs.append("%s: exempt from E1 as a pipe-free sourced helper, but it "
                     "now contains a pipe" % path)
    lines = logical_lines(text)
    views = [(n, shell_view(t)) for n, t in lines]
    for idx, (n, v) in enumerate(views):
        pos = v.find("$?")
        while pos >= 0:
            key = (path, n)
            if key not in EXCEPTIONS:
                before = v[:pos]
                if "$(" in before or "`" in before:
                    probs.append("%s:%d: a command substitution runs before "
                                 "`$?` on this line, so `$?` is ITS status "
                                 "(E3a)" % (path, n))
                segs = re.split(r";|&&|\|\|", before)
                prior = [s for s in segs[:-1] if s.strip()]
                if prior:
                    if has_pipe(prior[-1]):
                        probs.append("%s:%d: `$?` reads the status of a "
                                     "pipeline (E3b)" % (path, n))
                else:
                    if idx == 0:
                        probs.append("%s:%d: `$?` with no command before it "
                                     "(E3c)" % (path, n))
                    else:
                        pn, pv = views[idx - 1]
                        pstrip = pv.strip()
                        if (not pstrip or pstrip in BLOCK_KW
                                or pn != n - 1 - _extra(lines, idx - 1)):
                            probs.append("%s:%d: `$?` is not read on the line "
                                         "immediately after its command "
                                         "(E3c)" % (path, n))
                        elif has_pipe(pstrip):
                            probs.append("%s:%d: `$?` reads the status of a "
                                         "pipeline on the previous line (E3b)"
                                         % (path, n))
            pos = v.find("$?", pos + 2)
    return probs


def _extra(lines, i):
    """How many PHYSICAL lines logical line i spans, minus one."""
    n, t = lines[i]
    nxt = lines[i + 1][0] if i + 1 < len(lines) else n + 1
    return nxt - n - 1


def main() -> int:
    print()
    print("=" * 78)
    print("  E+ -- SHELL EXIT CODES: read only where they can belong")
    print("=" * 78)
    rc = 0
    files = scripts()
    reads = 0
    for f in files:
        with io.open(os.path.join(ROOT, f), encoding="utf-8",
                     errors="replace") as fh:
            text = fh.read()
        reads += sum(v.count("$?") for _n, v in
                     ((n, shell_view(t)) for n, t in logical_lines(text)))
        for p in audit_text(f, text):
            print("  *** %s" % p)
            rc = 1
    print("  %d script(s), %d `$?` read(s)%s"
          % (len(files), reads, "" if rc else " -- every one well-placed, "
                                                "every script pipefail"))

    # ---- must-fires (E4) -----------------------------------------------------
    print()
    print("  --- must-fire ---")
    cases = [
        ("a failing command piped into tail, then $?",
         "set -uo pipefail\nfalse | tail -1\nrc=$?\n", "E3b"),
        ("the same on one line",
         "set -uo pipefail\nfalse | tail -1; echo $?\n", "E3b"),
        ("$? after $(basename ...) in a loop",
         'set -uo pipefail\nfor g in a b; do\n  false\n'
         '  printf "%s %s\\n" "$(basename $g)" "$?"\ndone\n', "E3a"),
        ("a blank line between the command and $?",
         "set -uo pipefail\nfalse\n\nrc=$?\n", "E3c"),
        ("a script with no pipefail",
         "set -u\nfalse\nrc=$?\n", "E1"),
    ]
    # the exempt helper must stay pipe-free -- priced on its real path, with a
    # shebang first, which is exactly what defeated the first version
    got = audit_text("ci/rc.sh", "#!/usr/bin/env bash\nrun() { a | b; }\n")
    hit = any("now contains a pipe" in g for g in got)
    print("    %-46s %s" % ("the E1-exempt helper gaining a pipe",
                            "red" if hit else "*** MISSED"))
    if not hit:
        rc = 1
    for label, text, want in cases:
        got = audit_text("fixture.sh", text)
        hit = any(want in g for g in got)
        print("    %-46s %s" % (label, "red (%s)" % want if hit
                                else "*** MISSED"))
        if not hit:
            rc = 1
    good = [
        ("a redirected command then rc=$?",
         "set -uo pipefail\ncmd > log 2>&1\nrc=$?\n"),
        ("a backslash-continued command then rc=$?",
         "set -uo pipefail\ncmd a \\\n    b > log 2>&1\nrc=$?\n"),
        ("cmd; rc=$? on one line",
         "set -uo pipefail\ncmd; rc=$?\n"),
        ("'$?' inside single quotes is not shell",
         "set -uo pipefail\necho 'the code is $?'\n"),
    ]
    for label, text in good:
        got = audit_text("fixture.sh", text)
        print("    %-46s %s" % (label, "accepted" if not got
                                else "*** WRONGLY REFUSED: %s" % got[0]))
        if got:
            rc = 1

    print()
    print("=" * 78)
    print("  GATE shell-rc: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
