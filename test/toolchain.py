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

import subprocess
import sys

MISSING = "MISSING"

# ⭐ The WSL-side tools are invoked as a DIRECT argv, with no shell anywhere.
# The standing rule is "a script file, never `bash -lc` with inline $VAR" --
# that rule exists because variables expanded across the Git-Bash/WSL boundary
# have had their arguments eaten. A fixed argv has no variables to eat and no
# shell to eat them, which is the strictest form of the same rule, so it needs
# no companion .sh (one more file to keep LF-only for WSL).
PROBES = (
    ("python", None),                       # answered in-process
    ("iverilog", ["iverilog", "-V"]),
    ("verilator", ["wsl.exe", "-d", "Ubuntu", "--", "verilator", "--version"]),
    ("yosys", ["wsl.exe", "-d", "Ubuntu", "--", "yosys", "-V"]),
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
    for name, cmd in PROBES:
        if cmd is None:
            out[name] = _ascii(sys.version.split()[0])
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
