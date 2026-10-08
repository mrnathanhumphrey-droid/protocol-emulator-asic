"""Ruling V -- every simulation/synthesis tool is reached through ONE resolver,
and every tool-driven script says which binary it ran.

⛔⛔ WHY. CI keeps the pinned Verilator off PATH and names it in `PE_VERILATOR`;
apt's 5.020 is on PATH. `test/verilator_trace.sh` called a bare `verilator`, so
the two-simulator witness ran 5.020 in CI and disagreed with the local 5.053 on
666 lines -- and two commits went to a wrong diagnosis (a stimulus race) before
anyone looked at the version. Answering V found the same class twice more: the
artefact manifest probed a bare WSL `verilator` (apt's 5.032, which built
nothing), and the local witness and parameter dump reached WSL without the pin.

⇒ V1  In `ci/`, `test/` and `model/` no verilator / iverilog / vvp / yosys is
      invoked by its bare name. Shell sources `ci/tools.sh` and runs "$VL" /
      "$IV" / "$VVP" / "$YS"; Python calls `toolchain.tool()`. Both read the
      `PE_*` variable first, then PATH, and make the path absolute.
      Also refused: a PRIVATE resolver that defaults to the bare name
      (`${PE_VERILATOR:-verilator}`, `environ.get("PE_IVERILOG", "iverilog")`),
      which is a PATH lookup that reads as if it were not one.
⇒ V2  Every file that runs a resolved tool prints it: shell that sources the
      resolver calls `tool_banner`; Python that calls `tool(` calls `banner(`.
      (The witness additionally REQUIRES the pinned release in its banner --
      `test/gate_corpus_trace.py`'s ruling-V check.)

The two resolvers themselves, and this file, are exempt by name.
"""

from __future__ import annotations

import glob
import io
import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import gate_shell_rc as shrc                                      # noqa: E402

TOOLS = r"(?:verilator|iverilog|vvp|yosys)"
EXEMPT = {"ci/tools.sh", "test/toolchain.py", "model/gate_tool_pinning.py"}

SH_CMD = re.compile(
    r"(?:^|[;&|(`]|\bthen\b|\bdo\b|\belse\b|\bcommand\s+-v\b|\bwhich\b|"
    r"\bexec\b|\btimeout\s+\d+)\s*(%s)\b(?![\w./-])" % TOOLS)
SH_PRIVATE = re.compile(r"\$\{PE_(?:VERILATOR|IVERILOG|VVP|YOSYS):-%s\}" % TOOLS)
SH_RESOLVED_RUN = re.compile(
    r"(?:^|[;&|(`]|\bthen\b|\bdo\b|\belse\b)\s*\"\$(?:VL|IV|VVP|YS)\"")
SH_SOURCES = re.compile(r"(?:^|\s)(?:\.|source)\s+\S*ci/tools\.sh")

PY_ARGV = re.compile(r"""\[\s*(['"])%s\1\s*[,\]]""" % TOOLS)
PY_WHICH = re.compile(r"""which\(\s*(['"])%s\1""" % TOOLS)
PY_WSL_ARG = re.compile(r"""(['"])--\1\s*,\s*(['"])%s\2""" % TOOLS)
PY_PRIVATE = re.compile(
    r"""environ\.get\(\s*['"]PE_(?:VERILATOR|IVERILOG|VVP|YOSYS)['"]\s*,"""
    r"""\s*(['"])%s\1""" % TOOLS)


def py_code_lines(text):
    """Lines with their comments removed (strings kept: they ARE the argv)."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        s = line.split("#", 1)[0] if "#" in line and not re.search(
            r"""['"][^'"]*#""", line) else line
        if s.strip():
            out.append((n, s))
    return out


def audit_sh(path, text):
    probs = []
    used = False
    for n, t in shrc.logical_lines(text):
        v = shrc.shell_view(t)
        m = SH_CMD.search(v)
        if m:
            probs.append("%s:%d: bare `%s` in command position (V1) -- source "
                         "ci/tools.sh and use its variable" % (path, n, m.group(1)))
        if SH_PRIVATE.search(v):
            probs.append("%s:%d: a private resolver defaulting to the bare name "
                         "(V1) -- source ci/tools.sh" % (path, n))
        if SH_RESOLVED_RUN.search(v):
            used = True
    sources = bool(SH_SOURCES.search(text))
    if (sources or used) and "tool_banner" not in text:
        probs.append("%s: runs a resolved tool but never calls `tool_banner` "
                     "(V2) -- the log would not say which binary ran" % path)
    if used and not sources:
        probs.append("%s: runs \"$VL\"/\"$IV\"/\"$VVP\"/\"$YS\" without sourcing "
                     "ci/tools.sh (V1) -- a private resolver" % path)
    return probs


def audit_py(path, text):
    probs = []
    for n, s in py_code_lines(text):
        for rx, why in ((PY_ARGV, "a bare tool name heading an argv"),
                        (PY_WHICH, "a PATH lookup by bare name"),
                        (PY_WSL_ARG, "a bare tool name handed to WSL"),
                        (PY_PRIVATE, "a private resolver defaulting to the "
                                     "bare name")):
            if rx.search(s):
                probs.append("%s:%d: %s (V1) -- use toolchain.tool()"
                             % (path, n, why))
    if re.search(r"(?<![\w.])tool\(", text) and "banner(" not in text:
        probs.append("%s: calls tool() but never banner() (V2)" % path)
    return probs


def files():
    out = []
    for top in ("ci", "test", "model"):
        for p in glob.glob(os.path.join(ROOT, top, "**", "*"), recursive=True):
            rel = os.path.relpath(p, ROOT).replace("\\", "/")
            if (not os.path.isfile(p) or "__pycache__" in rel
                    or os.path.basename(p).startswith("probe_")
                    or rel in EXEMPT):
                continue
            if rel.endswith((".sh", ".py")):
                out.append(rel)
    return sorted(out)


def audit(rel, text):
    return audit_sh(rel, text) if rel.endswith(".sh") else audit_py(rel, text)


def main() -> int:
    print()
    print("=" * 78)
    print("  V -- TOOLS THROUGH ONE RESOLVER, AND THE LOG NAMES WHAT RAN")
    print("=" * 78)
    fs = files()
    probs = []
    for rel in fs:
        with io.open(os.path.join(ROOT, rel), encoding="utf-8",
                     errors="replace") as fh:
            probs += audit(rel, fh.read())
    print("  scanned %d script(s) under ci/ test/ model/; resolvers exempt: %s"
          % (len(fs), ", ".join(sorted(EXEMPT - {"model/gate_tool_pinning.py"}))))
    rc = 0
    for p in probs:
        print("  *** %s" % p)
        rc = 1
    if not probs:
        print("  no bare invocation, no private resolver; every tool-driven "
              "script prints its banner")

    # ---- must-fire ----------------------------------------------------------
    print()
    print("  --- must-fire ---")
    cases = []
    # ⛔ THE REAL DEFECT, from history: verilator_trace.sh as it stood at
    # f8f952c, the commit whose CI witness ran apt's 5.020. ⚠ KEPT AS A
    # FIXTURE because CI checks out at depth 1 and `git show` finds nothing
    # there; where history IS present the fixture is checked byte-for-byte
    # against it, so it cannot drift into a file that merely looks old.
    fx = os.path.join(HERE, "fixtures", "verilator_trace_f8f952c.sh.txt")
    with io.open(fx, encoding="utf-8", newline="") as fh:
        old = fh.read()
    try:
        hist = subprocess.run(["git", "show", "f8f952c:test/verilator_trace.sh"],
                              cwd=ROOT, capture_output=True).stdout
    # ⛔ RULING E: only "git is not runnable here" is expected, and that is
    # OSError; a git that runs and fails returns empty stdout without raising.
    except OSError:
        hist = b""
    if hist:
        # line endings normalised: a Windows checkout may CRLF the fixture
        same = (hist.decode("utf-8", "replace").replace("\r\n", "\n")
                == old.replace("\r\n", "\n"))
        print("    fixture vs git f8f952c                          %s"
              % ("identical" if same else "*** DIFFERS"))
        rc |= 0 if same else 1
    else:
        print("    fixture vs git f8f952c                          (no history "
              "here -- shallow checkout; fixture used as committed)")
    cases.append(("verilator_trace.sh at f8f952c (CI ran 5.020)",
                  any("V1" in x for x in
                      audit_sh("old/verilator_trace.sh", old))))
    cases.append(("a Python argv headed by bare \"iverilog\"",
                  bool(audit_py("x.py", 'r = run(["iverilog", "-g2012"])\n'))))
    cases.append(("a shell `VL=\"${PE_VERILATOR:-verilator}\"`",
                  bool(audit_sh("x.sh", 'set -o pipefail\nVL="${PE_VERILATOR:-verilator}"\n'))))
    cases.append(("sourcing ci/tools.sh with no tool_banner",
                  any("V2" in x for x in audit_sh(
                      "x.sh", 'set -o pipefail\n. ci/tools.sh\n"$VL" --cc x.v\n'))))
    cases.append(("tool() without banner()",
                  any("V2" in x for x in audit_py(
                      "x.py", 'cmd = [tool("vvp"), out]\n'))))
    cases.append(("a clean resolved script is accepted",
                  not audit_sh("x.sh", 'set -o pipefail\n. ci/tools.sh\n'
                                       'tool_banner verilator\n"$VL" --cc x.v\n')))
    for label, hit in cases:
        print("    %-48s %s" % (label, "ok" if hit else "*** MISSED"))
        if not hit:
            rc = 1

    print()
    print("=" * 78)
    print("  GATE tool-pinning: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
