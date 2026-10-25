"""RULING CI3 -- WHERE THE PUSH-PULL CLOCKED RECEIVE ACTUALLY SAMPLES.

Silicon fix #3 part (b) made a push-pull clocked SHIFTIN capture at the
engine's own SCK rise: `pin_in` read when it shows the MISO pad AS IT STOOD AT
THE SCK PAD's RISE (rise + the 2-sample input path; CI2, HOST_INTERFACE §SPI
receive timing). This finds that instant instead of asserting it.

The SPI peer (`fram_spi`, `MISO_DLY`) presents each read bit N system cycles
after the SCK fall that should present it. On `corpus_spim` (the real WREN /
WRITE / READ, d = 7) the chip's received bytes -- off the serial host pins --
must be the bytes the WRITE stored (5B C4) while the bit is on the pad before
the rise, and wrong once it is not:

  PREDICTED (CI2): correct while N <= d - 1 (the bit settles at least one
  cycle -- the synchroniser's +-1 -- before the rise).
  REQUIRED: every read correct at N <= d - 2, every read wrong at N >= d + 1,
  and the transition inside [d - 1, d] -- within one cycle of the prediction.
  ⚠ THE TRANSITION IS A BAND, NOT A STEP, and why is measured, not waved at:
  the SCK low phase is d cycles except when a LOW dispatch is late, which
  shortens it (t_LOW = d - (r_i - C), the quantity D2's mode floor uses);
  the bits with a short low phase fail first.

Runs in CI (iverilog only; no sigrok).
"""

from __future__ import annotations

import collections
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "model"))
from toolchain import banner, tool          # noqa: E402  ruling V
import run_recert as R                      # noqa: E402  one trace path
from run_spifram import serial_rx           # noqa: E402  one frame decoder
import corpus                               # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

IMG = "corpus_spim.hex"
NCYC = 30000
WANT = [0x5B, 0xC4]


def build(n):
    os.makedirs(R.SCRATCH, exist_ok=True)
    v = os.path.join(R.SCRATCH, "spidly_%d.vvp" % n)
    r = subprocess.run([tool("iverilog"), "-g2012",
                        "-Ptb_trace.SPI_MISO_DLY=%d" % n, "-I", "test", "-I",
                        ".", "-o", v, "-s", "tb_trace", "test/tb_trace.v",
                        "test/fram_spi.v", "test/fram_i2c.v",
                        "src/pe_engine.v", "src/pe_store.v", "src/project.v"],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit("*** build failed (N=%d)\n%s" % (n, r.stderr[-600:]))
    return v


def reads(n):
    _out, rows = R.trace(build(n), IMG, "spi", NCYC)
    rx = serial_rx(rows, 0)
    pairs = [rx[i:i + 2] for i in range(0, len(rx) - 1, 2)]
    return sum(1 for p in pairs if p == WANT), len(pairs), rows


def transition_checks(res, d):
    """[(what, good, derived)] for a sweep `res` {N: (correct reads, reads)}.
    ⛔ The third check is DERIVED (Wilson 10-25): over the swept range 0..d+2,
    checks 1 and 2 imply it -- clean N is in [d-2, d] and the first all-wrong
    N in [d-1, d+1] -- so no plant can fire it alone and it cannot be
    meta-tested. It is printed, labelled, and kept OUT of transition_problems
    and the must-fire count."""
    clean = max((n for n in res if res[n][0] == res[n][1]), default=-99)
    first_bad = min((n for n in res if res[n][0] == 0), default=-99)
    return [
        ("every read correct for N <= d - 2 = %d" % (d - 2),
         all(res[n][0] == res[n][1] and res[n][1] >= 4 for n in range(0, d - 1)),
         False),
        ("every read wrong for N >= d + 1 = %d" % (d + 1),
         all(res[n][0] == 0 for n in range(d + 1, d + 3)), False),
        ("transition within 1 cycle of the prediction (last clean N = %d, "
         "first all-wrong N = %d; predicted d - 1 = %d)"
         % (clean, first_bad, d - 1),
         abs(clean - (d - 1)) <= 1 and abs(first_bad - d) <= 1, True)]


def transition_problems(res, d):
    """[problem] -- the gate and its must-fires both call this."""
    return [what for what, good, derived in transition_checks(res, d)
            if not good and not derived]


def main() -> int:
    banner("iverilog", "vvp")
    print()
    print("=" * 78)
    print("CI3 -- the push-pull clocked receive's sample edge, found by sweep")
    print("=" * 78)
    lane = R.I.lane_programs(R.read(os.path.join(HERE, IMG)))[0][0]
    d = lane["t"]
    sclk = lane["clkpin"]
    cs = corpus.P_M_CS
    rc = 0
    res = {}
    for n in range(0, d + 3):
        ok, tot, rows = reads(n)
        res[n] = (ok, tot)
        print("    MISO delay N = %2d cycle(s): %2d of %2d reads == 5B C4"
              % (n, ok, tot))
    # the low phase, measured on the N = 0 run's pins
    _ok, _t, rows = reads(0)
    sck = [R.level(r, sclk, True) for r in rows]
    csl = [R.level(r, cs, True) for r in rows]
    lows, start = collections.Counter(), None
    for i in range(1, len(sck)):
        if sck[i - 1] == 1 and sck[i] == 0 and csl[i] == 0:
            start = i
        elif sck[i - 1] == 0 and sck[i] == 1 and start is not None:
            lows[i - start] += 1
            start = None
    print("    SCK low phase (cycles, CS low): %s  (d = %d)"
          % (dict(sorted(lows.items())), d))

    for what, good, derived in transition_checks(res, d):
        print("    %-62s %s%s" % (what, "ok" if good else "*** FAIL",
                                  "  (DERIVED from the two above)" if derived else ""))
    if transition_problems(res, d):
        rc = 1
    # ⛔ F8 (meta-test 3a, 10-24): this gate had NO must-fire -- the sweep's
    # three checks were inline and nothing planted a wrong sweep against them.
    print()
    print("  --- must-fire: the transition checks reject a wrong sweep ---")
    span = range(0, d + 3)
    for what, plant, want_bad in (
            ("every read correct (MISO delay never bites)",
             {n: (4, 4) for n in span}, True),
            ("every read wrong (nothing samples)",
             {n: (0, 4) for n in span}, True),
            ("transition 3 cycles early",
             {n: ((4, 4) if n <= d - 4 else (0, 4)) for n in span}, True),
            ("the predicted transition (control)",
             {n: ((4, 4) if n <= d - 1 else (0, 4)) for n in span}, False)):
        ok = bool(transition_problems(plant, d)) == want_bad
        print("    %-62s %s" % (what, ("red  ok" if want_bad else "ok")
                                if ok else "*** WRONG"))
        if not ok:
            rc = 1
    print()
    print("  GATE spidelay: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
