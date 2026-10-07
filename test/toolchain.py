"""toolchain -- THE ONE PROBE for which tools built an artefact.

`test/artefacts.sha256` pins each generated artefact by hash. A hash that
disagrees on another machine has two very different causes, and the manifest
could not tell them apart:

  * **a recipe changed** -- a real finding, and the thing the manifest exists
    to catch;
  * **a tool version changed** -- the same recipe, a different `iverilog` or
    `verilator`, so the bytes moved underneath an unchanged command.

Without the versions recorded next to the hashes, the second reads exactly like
the first, and the cheap way out of a red gate is to re-pin the hash -- which
is how a recipe change gets laundered through a toolchain excuse.

⇒ The manifest header records the versions. On a mismatch the clean room prints
stored vs live, so the two causes separate before anyone edits a hash.

⛔⛔ WHY THIS IS A MODULE AND NOT TWO COPIES. The writer (`make_smoke_image.py
--all`) and the reader (`clean_room.py`) must agree on the probe AND on the line
format. Written separately they are this project's most reliable bug -- the same
shape as `tb_smoke`'s private `exp_act` slice and `run_local.py`'s third source
list, where two copies of one fact drifted and both sides stayed green. One
module owns the probe, the format, and the parse.

⛔ A FAILED PROBE RECORDS `MISSING`, NEVER A GUESS AND NEVER AN OMISSION. An
omitted line would make a header written on a machine without Verilator look
complete; `MISSING` is a reading, and it is visibly not a version.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

MISSING = "MISSING"

# ============================================================================
# RULING V -- THE ONE RESOLVER FOR EVERY SIMULATION AND SYNTHESIS TOOL
# ============================================================================
# ⛔⛔ WHY. CI keeps the pinned Verilator OFF `PATH` and names it in
# `PE_VERILATOR`; apt's 5.020 is what a bare `verilator` finds there.
# `verilator_trace.sh` called the bare name, so the corpus witness ran 5.020 in
# CI and disagreed with the local 5.053 on 666 lines -- and two commits went to
# a wrong diagnosis before the version was looked at. A tool found by PATH is a
# tool nobody chose.
# ⇒ Every invocation in `ci/`, `test/` and `model/` goes through `tool()` here
#   (or `ci/tools.sh` for shell), which reads the `PE_*` variable first and
#   only then PATH, and returns an ABSOLUTE path. `banner()` prints that path
#   and the version, so every log says what actually ran.
#   `model/gate_tool_pinning.py` refuses a bare invocation anywhere else.
# ⚠ ONLY VERILATOR IS PINNED TO A VERSION. iverilog and yosys come from the
#   distribution in CI on purpose (test.yaml); for them the guarantee is that
#   the path and version are named in the log, not that they are fixed.
TOOL_ENV = {"verilator": "PE_VERILATOR", "iverilog": "PE_IVERILOG",
            "vvp": "PE_VVP", "yosys": "PE_YOSYS"}
VERSION_FLAG = {"verilator": "--version", "iverilog": "-V", "vvp": "-V",
                "yosys": "-V"}
#: The pinned release, by MAJOR.MINOR token (see gate_coverage.PINNED_TOOL's
#: history for why a prefix match is not enough).
PINNED_VERILATOR = "Verilator 5.053"
#: The pinned binary on the WSL side, used when this machine has no Verilator
#: of its own (the Windows-local flow delegates to WSL).
PINNED_WSL_VERILATOR = os.environ.get(
    "PE_VERILATOR_WSL", "/opt/oss-cad-suite-2026-09-30/bin/verilator")


class ToolMissing(RuntimeError):
    pass


def tool(name):
    """Absolute path of `name`, from its `PE_*` variable, else PATH.

    `vvp` without `PE_VVP` is taken from the SAME directory as the resolved
    iverilog, so the compiler and its runtime cannot come from two installs.
    """
    env = os.environ.get(TOOL_ENV[name])
    if env:
        p = shutil.which(env) or (env if os.path.isfile(env) else None)
        if not p:
            raise ToolMissing("%s=%s does not exist" % (TOOL_ENV[name], env))
        return os.path.abspath(p)
    if name == "vvp":
        try:
            d = os.path.dirname(tool("iverilog"))
        except ToolMissing:
            d = None
        if d:
            for cand in ("vvp", "vvp.exe"):
                if os.path.isfile(os.path.join(d, cand)):
                    return os.path.join(d, cand)
    p = shutil.which(name)
    if not p:
        raise ToolMissing("%s is not set and %s is not on PATH"
                          % (TOOL_ENV[name], name))
    return os.path.abspath(p)


def tool_or_none(name):
    try:
        return tool(name)
    except ToolMissing:
        return None


def version_of(argv):
    try:
        r = subprocess.run(argv, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        v = _first_line(r.stdout) or _first_line(r.stderr)
        return v if v else MISSING
    except Exception:
        return MISSING


def banner(*names, indent="  "):
    """Print `tool <name>: <path>  <version>` for each; return {name: path}.

    ⭐ RULING V2: every tool-driven gate calls this before using a tool, so the
    log names the binary that produced its verdict.
    """
    out = {}
    for n in names:
        p = tool_or_none(n)
        v = version_of([p, VERSION_FLAG[n]]) if p else MISSING
        print("%stool %-9s: %s  %s" % (indent, n, p or "NOT FOUND", v))
        out[n] = p
    return out


def pinned_ok(label):
    """True if a version banner names the pinned Verilator (token equality)."""
    want, got = PINNED_VERILATOR.split(), (label or "").split()
    return len(got) >= 2 and got[0] == want[0] and got[1] == want[1]


def _probe_argv(name):
    """The argv that reports `name`'s version for the manifest header."""
    if isinstance(name, (list, tuple)):          # an explicit argv (selftest)
        return list(name)
    p = tool_or_none(name)
    if p:
        return [p, VERSION_FLAG[name]]
    # ⭐ The WSL-side tools are invoked as a DIRECT argv, with no shell. The
    # standing rule is "a script file, never `bash -lc` with inline $VAR"; a
    # fixed argv has no variables to eat. ⛔ AND IT NAMES THE PINNED BINARY:
    # this probe used to ask WSL for a bare `verilator`, which there is apt's
    # 5.032 -- so the manifest header recorded a Verilator that built nothing.
    if name == "verilator" and shutil.which("wsl.exe"):
        return ["wsl.exe", "-d", "Ubuntu", "--", PINNED_WSL_VERILATOR,
                "--version"]
    if name == "yosys" and shutil.which("wsl.exe"):
        return ["wsl.exe", "-d", "Ubuntu", "--",
                os.environ.get("PE_YOSYS_WSL", "/usr/bin/yosys"), "-V"]
    return None


PROBES = (
    ("python", None),                       # answered in-process
    ("iverilog", "iverilog"),
    ("verilator", "verilator"),
    ("yosys", "yosys"),
)

PREFIX = "# tool "
SEP = " = "


def _ascii(s):
    """The manifest is written as ASCII; an exotic version string must not be
    able to crash the write that records it."""
    return s.encode("ascii", "replace").decode("ascii")


def _first_line(txt):
    for ln in txt.splitlines():
        if ln.strip():
            return _ascii(ln.strip())
    return ""


def probe():
    """{tool: version-or-MISSING}, in a fixed order."""
    out = {}
    for name, which in PROBES:
        if which is None:
            out[name] = _ascii(sys.version.split()[0])
            continue
        cmd = _probe_argv(which)
        if cmd is None:
            out[name] = MISSING
            continue
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=120)
            # ⚠ `iverilog -V` and `yosys -V` print to stdout, Verilator too,
            # but a build that writes its banner to stderr must not read as
            # MISSING -- so both streams are considered, stdout first.
            v = _first_line(r.stdout) or _first_line(r.stderr)
            out[name] = v if (r.returncode == 0 and v) else MISSING
        except Exception:
            out[name] = MISSING
    return out


def header_lines(vers=None):
    """The `# tool <name> = <version>` lines for the manifest header."""
    v = probe() if vers is None else vers
    return [PREFIX + name + SEP + v.get(name, MISSING) for name, _c in PROBES]


def parse(path):
    """Read the versions back out of a manifest. {} if the header has none."""
    out = {}
    try:
        with open(path, encoding="ascii", errors="replace") as fh:
            for ln in fh:
                if not ln.startswith(PREFIX):
                    continue
                name, _sep, ver = ln[len(PREFIX):].strip().partition(SEP)
                if name:
                    out[name.strip()] = ver.strip()
    except OSError:
        return {}
    return out


def compare(stored, live):
    """[(tool, stored, live)] for every tool that reads differently.

    A tool absent from the stored header counts as a difference: a manifest
    written before this header existed cannot vouch for the toolchain, and
    saying so is the point.
    """
    diff = []
    for name, _c in PROBES:
        s = stored.get(name, "(not recorded)")
        l = live.get(name, MISSING)
        if s != l:
            diff.append((name, s, l))
    return diff


def selftest():
    """⛔ THE MECHANISM IS PRICED, NOT TRUSTED (standing rule 3).

    Four ways this could be decoration instead of a check, each made to fire:
    a header that is not read back, a missing header that reads as agreement, a
    changed version that is not noticed, and a failed probe that reports a
    version anyway.
    """
    global PROBES
    import os
    import tempfile

    rc = 0

    def say(ok, what):
        nonlocal rc
        print("    %-58s %s" % (what, "fires" if ok else "*** DID NOT FIRE"))
        if not ok:
            rc = 1

    d = tempfile.mkdtemp(prefix="pe_tc_")
    fake = {"python": "9.9.9", "iverilog": "Icarus Verilog version 0.0",
            "verilator": "Verilator 0.000", "yosys": "Yosys 0.0"}
    good = os.path.join(d, "with.sha256")
    with open(good, "w", encoding="ascii", newline=chr(10)) as fh:
        fh.write("# header" + chr(10))
        for ln in header_lines(fake):
            fh.write(ln + chr(10))
        fh.write("deadbeef  x.hex  # recipe" + chr(10))
    say(parse(good) == fake, "a written header parses back to what was written")

    bare = os.path.join(d, "without.sha256")
    with open(bare, "w", encoding="ascii", newline=chr(10)) as fh:
        fh.write("# header" + chr(10) + "deadbeef  x.hex  # recipe" + chr(10))
    say(parse(bare) == {}, "a manifest with no header parses as no reading")
    say(len(compare(parse(bare), fake)) == len(PROBES),
        "no header counts as a difference on every tool")

    moved = dict(fake, verilator="Verilator 5.999")
    dd = compare(fake, moved)
    say([t for t, _s, _l in dd] == ["verilator"],
        "one changed version is reported, and only that one")
    say(not compare(fake, fake), "an identical toolchain reports no difference")

    # a probe that cannot run must record MISSING, not a plausible version
    keep = PROBES
    try:
        PROBES = (("nosuchtool", ["pe_no_such_tool_xyz", "--version"]),)
        say(probe() == {"nosuchtool": MISSING},
            "a tool that will not run records MISSING")
    finally:
        PROBES = keep

    print("  toolchain self-test: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        print("  --- toolchain probe self-test ---")
        raise SystemExit(selftest())
    for ln in header_lines():
        print(ln)
