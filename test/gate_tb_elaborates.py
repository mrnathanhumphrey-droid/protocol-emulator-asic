"""`tb.v` MUST PREPROCESS THE WAY THE COCOTB MAKEFILE PREPROCESSES IT.

⛔⛔ WHY THIS GATE EXISTS: 81 of 81 sweep arms and 16 of 16 gates were GREEN
while the cocotb half would not even preprocess. `test/od_bus.vh` is the single
open-drain bus model, included by `tb.v` here and by `tb_trace`/`tb_edge` under
Verilator. Verilator runs from the REPO ROOT, so the include is written
`test/od_bus.vh`; the cocotb Makefile runs from `test/`, where that resolved to
`test/test/od_bus.vh`:

    test/tb.v:74: Include file test/od_bus.vh not found
    syntax error

Nothing in the local suite looked at `tb.v` AT ALL, so the break could only
surface in CI. That is a GATE-COVERAGE HOLE, not a path typo: the two benches
disagree about the working directory, and only one of them was ever checked.

⛔ IT DOES NOT RETYPE THE BUILD. The source list comes from
`run_local.project_sources()`, which parses `test/Makefile` -- that function
exists because this file's list was once a stale third copy that broke the
local runner outright -- and the include flags are parsed from the same
Makefile. A gate that held its own copy of the flags would pass while the real
build failed, which is the defect it is meant to catch.

⚠ WHAT THE MUST-FIRE ACTUALLY GUARDS, measured rather than assumed: the
failing combination is `test/od_bus.vh` + cwd `test/` + NO repo root on the
include path. A BARE `od_bus.vh` also works, because iverilog searches the
INCLUDING FILE's own directory -- so two spellings resolve and only one
combination breaks. The regression this gate catches is therefore the deletion
of the Makefile's `-I$(PWD)/..`, and that is the arm that was verified to fire:
with the flag removed the gate goes RED, with it restored it passes. Breaking
the spelling in `tb.v` does NOT fire it, which is a true statement about
iverilog rather than a weakness worth hiding.

⚠ PREPROCESS, NOT ELABORATE, and the limit is declared: `iverilog -E` resolves
every `include` and macro, which is exactly the class that broke. It does not
prove `tb.v` ELABORATES -- the cocotb run in CI does that, and on this box the
only iverilog is OSS CAD's 14.0-devel, which cannot elaborate this design at
all (8 errors, measured, attributed to the tool with a control arm). Claiming
more than preprocessing would be the false comfort this project keeps finding.
"""
import io
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
MAKEFILE = os.path.join(HERE, "Makefile")


def iverilog():
    return os.environ.get("PE_IVERILOG") or shutil.which("iverilog")


def include_flags():
    """The `-I` flags the cocotb Makefile actually passes, parsed from it.

    ⛔ PARSED, NOT LISTED. `COMPILE_ARGS += -I$(SRC_DIR)` and
    `-I$(PWD)/..` are the real flags; a copy here would drift from them and
    this gate would then certify a build nobody runs.
    """
    with io.open(MAKEFILE, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    src_dir = None
    m = re.search(r"^SRC_DIR\s*[:?]?=\s*(.+)$", text, re.M)
    if m:
        src_dir = m.group(1).strip()
    out = []
    for m in re.finditer(r"^COMPILE_ARGS\s*\+?=\s*(.+)$", text, re.M):
        for tok in m.group(1).split():
            if not tok.startswith("-I"):
                continue
            p = tok[2:]
            if src_dir:
                p = p.replace("$(SRC_DIR)", src_dir)
            p = p.replace("$(PWD)", HERE).replace("$(CURDIR)", HERE)
            if "$(" in p:                     # an expansion we cannot resolve
                continue
            out.append(os.path.normpath(os.path.join(HERE, p)))
    return out, src_dir


def makefile_sources():
    """`PROJECT_SOURCES` out of test/Makefile."""
    with io.open(MAKEFILE, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    m = re.search(r"^PROJECT_SOURCES\s*[:?]?=\s*(.+)$", text, re.M)
    return m.group(1).split() if m else []


def preprocess(iv, flags, sources, label):
    """`iverilog -E` from the TEST directory, as the Makefile does."""
    cmd = [iv, "-E", "-o", os.devnull, "-g2012"]
    for f in flags:
        cmd += ["-I", f]
    cmd += sources
    r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    ok = (r.returncode == 0)
    msg = (r.stderr or r.stdout or "").strip().splitlines()
    return ok, (msg[0] if msg else ""), label


def main():
    print()
    print("=" * 78)
    print("TB ELABORATION -- `tb.v` preprocesses as the cocotb Makefile does")
    print("=" * 78)
    iv = iverilog()
    if not iv:
        print("  *** iverilog not found (PATH or PE_IVERILOG).")
        print("  ⛔ RED rather than skipped: the whole content of this gate is")
        print("     that the cocotb build's own include resolution works, and a")
        print("     skipped check of it is what let the last break reach CI.")
        return 1

    # ⛔ THE MAKEFILE IS THE SINGLE AUTHORITY, and this is a second READER of
    # it rather than a second copy of the data -- the duplication rule is about
    # copies, not about two programs reading one file. `run_local` parses the
    # same `PROJECT_SOURCES`, so where cocotb is importable the two readings
    # are CROSS-CHECKED below; where it is not (plain python3, no cocotb) this
    # gate still runs, because a gate that needs cocotb to check the cocotb
    # build's include path would be unrunnable exactly where it matters.
    srcs = makefile_sources()
    flags, src_dir = include_flags()
    try:
        sys.path.insert(0, HERE)
        import run_local
        other = run_local.project_sources()
        agree = (list(other) == list(srcs))
        print("  cross-check: run_local reads %s -- %s"
              % (" ".join(other), "agrees" if agree else "*** DISAGREES"))
        if not agree:
            print("  *** two readings of test/Makefile disagree, so one of the")
            print("      parsers is wrong and the build list is unknown.")
            return 1
    except ImportError:
        print("  cross-check: run_local needs cocotb, which is absent here --")
        print("               the Makefile parse stands alone this run")
    print("  iverilog : %s" % iv)
    print("  SRC_DIR  : %s" % (src_dir or "(not found in the Makefile)"))
    print("  -I flags : %s" % (", ".join(flags) or "(none)"))
    print("  sources  : %s + tb.v" % " ".join(srcs))
    if not flags:
        print("  *** no include flags parsed out of test/Makefile, so this gate")
        print("      would pass by testing nothing.")
        return 1

    rc = 0
    # the real thing: the Makefile's own sources and flags
    abs_srcs = [os.path.join(ROOT, "src", s) for s in srcs]
    ok, msg, _ = preprocess(iv, flags, abs_srcs + [os.path.join(HERE, "tb.v")],
                            "tb.v")
    print()
    print("  --- the real build's preprocessing ---")
    print("    %-54s %s" % ("tb.v with the Makefile's flags, from test/",
                            "ok" if ok else "*** FAILED"))
    if not ok:
        print("        %s" % msg)
        rc = 1

    # ---- must-fires ----------------------------------------------------
    # ⛔ PRICE THE THING THAT BROKE: the include PATH, not just the file.
    print()
    print("  --- must-fire: the include path is what is being checked ---")
    probe = os.path.join(HERE, "probe_inc_mustfire.v")
    cases = [
        ("the shared model resolves WITH the repo root",
         '`include "test/od_bus.vh"' + "\n", flags, True),
        ("... and FAILS without it",
         '`include "test/od_bus.vh"' + "\n",
         [f for f in flags if os.path.normpath(f) != os.path.normpath(ROOT)],
         False),
        ("a misspelled include fails",
         '`include "test/od_bus_typo.vh"' + "\n", flags, False),
    ]
    for label, body, fl, want in cases:
        with io.open(probe, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("module probe_inc;\n  wire [7:0] uio_in, uio_oe, "
                     "uio_out, ob_oe, ob_val;\n")
            fh.write(body)
            fh.write("endmodule\n")
        ok2, msg2, _ = preprocess(iv, fl, [probe], label)
        good = (ok2 == want)
        print("    %-54s %s" % (label, "ok" if good else
                                "*** wanted %s" % ("a pass" if want
                                                   else "a failure")))
        if not good:
            rc = 1
    try:
        os.remove(probe)
    except OSError:
        pass

    print()
    print("=" * 78)
    print("  GATE tb-elaborates: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    ⚠ PREPROCESSING ONLY -- it resolves every `include` and macro,")
    print("      which is the class that broke. CI's cocotb run is what proves")
    print("      `tb.v` elaborates and passes.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
