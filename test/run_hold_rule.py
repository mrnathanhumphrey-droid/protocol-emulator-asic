"""GATE hold-rule: the host hold of docs/HOST_FIRMWARE.md FW-1 is the right number (Wilson 11-11).

    python test/run_hold_rule.py

⛔⛔ WHY. The hold was "4 cycles" until 11-10: the bare worst case, with no
margin, and every bench driver held exactly 4 -- and every bench passed, because
a driver that changes pins on the FALLING edge keeps half a cycle of margin at
every capture edge. Measured 11-11: with the normal driver, even a 4-cycle hold
with the late-resolving synchroniser passes. So the number was never tested.

THE ARMS run the UART-TX witness (tb_uarttx: every byte the host fed, judged at
the bus by a peer) with the WORST-PHASE host of test/host_feed.vh
(HF_WORST_PHASE: `wr` lands 1 ps after a rising edge, the nibble skewed
HF_SKEW_NS = 10 ns ahead of it -- an ASSUMPTION, the TT FAQ's round-trip
estimate, FW-1), at a hold of HF_HOLD cycles, with and without PE_SIM_LATE_WR
(the first synchroniser flop resolving late, the 4th-edge capture):

    4-cycle, normal capture    PASS     (why the old benches never noticed)
    4-cycle, late capture      FAIL     (the rule's number: 4 is too short)
    5-cycle, normal capture    PASS
    5-cycle, late capture      PASS     (FW-1: 5 holds in the worst case)
    3-cycle, late capture      FAIL     (the define is live)

A FAIL arm must fail ON THE BUS (a wrong or missing byte at the peer), not by a
build error or a timeout: a corruption must be seen to corrupt. Every other
bench keeps the normal-phase driver at 5 cycles.
POSITIVE TOKEN: `GATE hold-rule: PASSED`.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import sim_run                                    # noqa: E402
import uart_tx                                    # noqa: E402
from toolchain import banner, tool                # noqa: E402
from run_uarttx import NCYC, _STORE_BYTES         # noqa: E402

IMG = "test/uart_tx_image.hex"
#: (hold, late, expect)
ARMS = ((4, False, "PASS"), (4, True, "FAIL"), (5, False, "PASS"),
        (5, True, "PASS"), (3, True, "FAIL"))
#: the bus-level failure lines a FAIL arm must show (tb_uarttx / clocked_conform)
BUS_FAIL = ("clocked_conform[V3]", "not the bytes the host fed", "frame")


def judge(out, expect):
    """[problem] for one arm's simulator output."""
    ok = "UART-TX: ok" in out and "*** FAIL" not in out
    if expect == "PASS":
        return [] if ok else ["expected PASS, got: %s" % first_fail(out)]
    if ok:
        return ["expected FAIL, the bus was clean -- the hold this arm breaks went unseen"]
    if "*** FAIL" not in out or not any(k in out for k in BUS_FAIL):
        return ["failed, but not on the bus: %s" % first_fail(out)]
    return []


def first_fail(out):
    return next((l.strip()[:110] for l in out.splitlines() if "*** FAIL" in l or "UART-TX" in l),
                "(no verdict line)")


def run_arm(work, hold, late):
    vvp = os.path.join(work, "tb_hold_%d_%d.vvp" % (hold, late))
    defs = ["-DHF_WORST_PHASE", "-DHF_HOLD=%d" % hold] + (["-DPE_SIM_LATE_WR"] if late else [])
    r = subprocess.run([tool("iverilog"), "-g2012", "-I", "test"] + defs +
                       ["-o", vvp, "-s", "tb_uarttx", "test/tb_uarttx.v", "src/pe_engine.v",
                        "src/pe_store.v", "src/project.v"],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        return None, "build failed: " + (r.stdout + r.stderr).strip()[-200:]
    o = subprocess.run(sim_run.vvp([vvp, "+IMG=" + IMG, "+NBYTES=%d" % _STORE_BYTES,
                                    "+NCYC=%d" % NCYC, "+BITP=%d" % uart_tx.T_NOMINAL,
                                    "+ERR=0"], images=[IMG]),
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return o.stdout + o.stderr, None


def must_fires():
    """the judge itself: [(label, red?)]"""
    clean = "UART-TX: ok -- 38 frame(s)\n"
    bus = "*** FAIL clocked_conform[V3]: lane 0 unclocked bit\n"
    return [("a PASS arm that failed", bool(judge(bus, "PASS"))),
            ("a FAIL arm that stayed clean", bool(judge(clean, "FAIL"))),
            ("a FAIL arm that failed off the bus", bool(judge("*** FAIL build\n", "FAIL")))], \
        not judge(clean, "PASS") and not judge(bus, "FAIL")


def main():
    print("GATE hold-rule: the host hold (HOST_FIRMWARE.md FW-1) -- 4 cycles fails, 5 holds, worst phase")
    banner("iverilog", "vvp")
    rc = 0
    mf, control = must_fires()
    for label, red in mf:
        print("  must-fire: %-40s %s" % (label, "red  ok" if red else "*** STAYED GREEN"))
        rc |= 0 if red else 1
    print("  control:   %-40s %s" % ("clean PASS / bus FAIL", "ok" if control else "*** RED"))
    rc |= 0 if control else 1
    work = tempfile.mkdtemp(prefix="holdrule_")
    print("  --- arms (worst-phase host, skew assumption 10 ns) ---")
    for hold, late, expect in ARMS:
        out, err = run_arm(work, hold, late)
        probs = [err] if err else judge(out, expect)
        print("  hold %d  late capture %-3s  expect %-4s  %s  %s"
              % (hold, "on" if late else "off", expect, "ok " if not probs else "***",
                 first_fail(out) if out and expect == "FAIL" else ""))
        for p in probs:
            print("      *** " + p)
        rc |= 1 if probs else 0
    shutil.rmtree(work, ignore_errors=True)
    print("\n  GATE hold-rule: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
