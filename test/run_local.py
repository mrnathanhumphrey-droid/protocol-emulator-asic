"""Local test runner -- FAST ITERATION ONLY. CI's Makefile is authoritative.

⛔ This exists because this Windows box has iverilog + cocotb but no `make`, while
WSL has `make` and neither of the other two. cocotb 2.x's Python runner sidesteps
the Makefile so RTL can be iterated locally instead of via a push-and-wait.

⛔⛔ IT IS NOT THE GATE. `test.yaml` in CI runs the Makefile on ubuntu, and
`gl_test` runs the SAME test.py against the synthesized netlist -- which is the
run that can actually disagree with the model. A green here means "the RTL behaves";
only CI's gate-level run means "the silicon behaves". Never report this as the
suite having passed.
"""

from __future__ import annotations

import os
import sys

from cocotb_tools.runner import get_runner

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), "src")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def project_sources():
    """PARSE the source list out of test/Makefile instead of holding a copy.

    ⛔⛔ THIS FILE HELD A STALE THIRD COPY AND IT BROKE THE LOCAL RUNNER
    OUTRIGHT. `PROJECT_SOURCES` lives in test/Makefile and is mirrored in
    info.yaml; this runner listed only `project.v`, so after the engine/store
    split it could not even elaborate -- "3 error(s) during elaboration: pe_engine
    referenced 1 times, pe_store referenced 1 times" -- while its own comment
    claimed "SAME SOURCES AND SAME TOPLEVEL AS CI'S MAKEFILE". A constant kept in
    three files is a constant updated in one.
    ⭐ Parsing the Makefile makes that comment true by construction rather than
    by vigilance.
    """
    mk = os.path.join(HERE, "Makefile")
    with open(mk, encoding="utf-8") as fh:
        for line in fh:
            if line.strip().startswith("PROJECT_SOURCES"):
                return line.split("=", 1)[1].split()
    raise AssertionError("PROJECT_SOURCES not found in %s" % mk)


def assert_info_yaml_agrees(srcs):
    """⛔⛔ info.yaml AND test/Makefile MUST NAME THE SAME FILES, because they
    feed different tools: the Makefile builds what CI TESTS, info.yaml lists what
    the flow HARDENS. A divergence means the tests pass on one design and the
    chip is built from another, and nothing in either tool would say so.
    """
    yml = os.path.join(os.path.dirname(HERE), "info.yaml")
    with open(yml, encoding="utf-8") as fh:
        text = fh.read()
    body = text.split("source_files:", 1)[1]
    listed = []
    for line in body.splitlines()[1:]:
        st = line.strip()
        if st.startswith("- "):
            listed.append(st[2:].strip().strip('"').strip("'"))
        elif st and not st.startswith("#"):
            break
    if sorted(listed) != sorted(srcs):
        raise AssertionError(
            "info.yaml source_files %s != Makefile PROJECT_SOURCES %s -- CI would "
            "test one design and the flow harden another" % (listed, srcs))
    return listed


def main() -> int:
    srcs = project_sources()
    assert_info_yaml_agrees(srcs)
    print("  sources (from test/Makefile, info.yaml agrees): %s"
          % " ".join(srcs))
    build_dir = os.path.join(HERE, "sim_build", "rtl")
    runner = get_runner("icarus")
    runner.build(
        # ⛔ SAME SOURCES AND SAME TOPLEVEL AS CI'S MAKEFILE (`TOPLEVEL = tb`).
        # Elaborating the module directly instead bypassed tb.v -- which carries
        # `timescale 1ns/1ps` -- and every test died on "unable to represent 20ns
        # with a precision of 1e0". A local runner that elaborates something
        # DIFFERENT from CI is not a faster version of CI, it is another thing.
        sources=[os.path.join(SRC, f) for f in project_sources()]
                + [os.path.join(HERE, "tb.v")],
        build_dir=build_dir,
        hdl_toplevel="tb",
        # ⛔ NO WIDTH WARNINGS SUPPRESSED. The width classes are the ones most
        # likely to expose a real bug in arithmetic RTL, and suppressing them is
        # how "clean under -Wall" became a false statement once already.
        # ⭐ PE_SPL selects the action-buffer depth, so the cocotb suite can
        # run at BOTH parameter points (ruling: every bench at every supported
        # parameter value). A hidden constant in a bench fails the moment the
        # parameter it silently assumed becomes variable -- which is how four
        # private copies of the engine's slot index were found.
        build_args=["-g2012", "-Wall",
                    "-Ptb.SPL_CFG=%s" % os.environ.get("PE_SPL", "2")],
        always=True,
    )
    # ⭐ PE_TEST_MODULE lets a throwaway diagnostic module run through the
    # SAME build and toplevel as the real suite. A diagnostic elaborated
    # differently from the suite measures a different thing.
    runner.test(
        hdl_toplevel="tb",
        test_module=os.environ.get("PE_TEST_MODULE", "test"),
        build_dir=build_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
