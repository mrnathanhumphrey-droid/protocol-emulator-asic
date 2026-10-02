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


def main() -> int:
    build_dir = os.path.join(HERE, "sim_build", "rtl")
    runner = get_runner("icarus")
    runner.build(
        # ⛔ SAME SOURCES AND SAME TOPLEVEL AS CI'S MAKEFILE (`TOPLEVEL = tb`).
        # Elaborating the module directly instead bypassed tb.v -- which carries
        # `timescale 1ns/1ps` -- and every test died on "unable to represent 20ns
        # with a precision of 1e0". A local runner that elaborates something
        # DIFFERENT from CI is not a faster version of CI, it is another thing.
        sources=[os.path.join(SRC, "project.v"), os.path.join(HERE, "tb.v")],
        build_dir=build_dir,
        hdl_toplevel="tb",
        # ⛔ NO WIDTH WARNINGS SUPPRESSED. The width classes are the ones most
        # likely to expose a real bug in arithmetic RTL, and suppressing them is
        # how "clean under -Wall" became a false statement once already.
        build_args=["-g2012", "-Wall"],
        always=True,
    )
    runner.test(
        hdl_toplevel="tb",
        test_module="test",
        build_dir=build_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
