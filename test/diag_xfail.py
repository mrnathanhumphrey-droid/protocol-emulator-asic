"""THROWAWAY: price the expect_fail mechanism. Safe to delete.

The suite claims its two recorded defects ANNOUNCE THEIR OWN OBSOLESCENCE: when
fixed, the expect_fail test passes unexpectedly and CI goes red. A mechanism
only ever seen to pass has unknown strength, so here is an expect_fail test
that SUCCEEDS. results.xml must then contain a failure.
"""

import cocotb
from cocotb.triggers import Timer


@cocotb.test(expect_fail=True)
async def xfail_that_actually_passes(dut):
    await Timer(1, unit="ns")
    assert True, "this test does not fail, so the expect_fail must be violated"
