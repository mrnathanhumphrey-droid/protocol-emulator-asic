"""A2-CLOSE Part A, GATE A-FOREIGN -- sigrok adjudicates the D_i boundary.

THE ONE CLAIM: the jitter tolerance we computed is UART's tolerance, not our
monitor's. `jitter_dmax.py` searched a band using the TA-01 receiver -- our own
code. This runs an INDEPENDENT decoder (sigrok's `uart` PD, foreign code written
from the standard) over the same jittered waveforms and requires it to switch
verdict AT THE SAME v.

⛔ "SIGROK AGREES AT THE BOUNDARY" IS THE WEAK VERSION AND IS NOT WHAT THIS
CHECKS. A decoder that failed everything, or passed everything, would "agree at
the boundary" on one side by luck. This runs a LADDER across the boundary and
requires:
    (a) both authorities CONFORM for every v <= D,
    (b) both authorities REFUSE for every v > D,
    (c) the switch is at the same v -- D_ours == D_sigrok.
Any of the three failing is a finding. (a) alone is also what proves the gate is
not vacuous: if sigrok refused at v = 0 the whole ladder would be meaningless.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "ta01"))
sys.path.insert(0, HERE)

from gate0_external import sigrok_decode                      # noqa: E402
from uart_ta import UartReceiver, bit_period                   # noqa: E402
from jitter_dmax import conforms_under, levels_jittered        # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def dump_jittered(byte: int, T: int, deltas: list, path: str) -> int:
    """One byte per cycle, bit0 = the TX line -- sigrok's `binary` input format."""
    wave = levels_jittered(byte, T, deltas)
    if wave is None:
        raise ValueError("deltas reorder the waveform; outside the jitter model")
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:                 # temp-then-replace: a truncating
        fh.write(bytes(lv & 1 for lv in wave))  # open() can lose the old file on
    os.replace(tmp, path)                       # a failed write
    return len(wave)


def main() -> int:
    T = bit_period()
    rx = UartReceiver(T)
    BYTE = 0x55                  # bit-order sensitive: not its own bit-reversal
    D = 216                      # from jitter_dmax.py; the ladder must rediscover it

    print("=" * 78)
    print("GATE A-FOREIGN -- sigrok vs our monitor across the D_i boundary")
    print("=" * 78)
    print("  byte 0x%02X, T = %d, shape `early_1` (delta_0 = v, all later edges on time)"
          % (BYTE, T))
    print("  our computed D = %d, so sigrok must flip between v=%d and v=%d"
          % (D, D, D + 1))
    print()
    print("  %-6s %-10s %-10s %-9s %s" % ("v", "ours", "sigrok", "decoded", "agree"))

    ladder = [0, 1, 108, 214, 215, 216, 217, 218, 250, 300, 433]
    rows = []
    tool_failures = []
    SHIFTED = 0xD5          # 0x55 with the sample grid one bit position late
    for v in ladder:
        deltas = [v] + [0] * 9
        ours = conforms_under(BYTE, T, deltas, rx)
        if ours is None:
            print("  %-6d %s" % (v, "OUT OF MODEL (boundaries reorder) -- skipped"))
            continue
        path = os.path.join(HERE, "wave_jit_%03d.bin" % v)
        dump_jittered(BYTE, T, deltas, path)
        theirs_raw = sigrok_decode(path)
        # ⛔⛔ THE EXIT STATUS IS CHECKED, AND THIS GATE PASSED WITHOUT IT.
        # `sigrok_decode` has always returned `rc`, and nothing in the repo ever
        # read it. A sigrok that failed to run on ONLY the above-band rungs
        # yields no annotations there, so `theirs` is False == VIOL -- exactly
        # what condition (b) expects -- while the below-band rungs satisfy
        # non-vacuity. All four conditions passed with the foreign authority
        # broken on the half of the ladder that carries the finding. A tool
        # failure is NOT a verdict and is now a hard gate failure.
        if theirs_raw["rc"] != 0:
            tool_failures.append((v, theirs_raw["rc"]))
            print("  %-6d %-10s %s" % (v, "CONF" if ours else "VIOL",
                  "*** SIGROK FAILED TO RUN (rc=%s) -- not a verdict ***"
                  % theirs_raw["rc"]))
            try:
                os.remove(path)
            except OSError:
                pass
            continue
        decoded = int(theirs_raw["bytes"][0], 16) if theirs_raw["bytes"] else None
        theirs = bool(theirs_raw["start"] and theirs_raw["stop"]
                      and decoded == BYTE and not theirs_raw["frame_error"])
        agree = (ours == theirs)
        rows.append((v, ours, theirs, decoded, agree))
        print("  %-6d %-10s %-10s %-9s %s"
              % (v, "CONF" if ours else "VIOL", "CONF" if theirs else "VIOL",
                 "0x%02X" % decoded if decoded is not None else "-",
                 "OK" if agree else "*** DISAGREE ***"))
        try:
            os.remove(path)
        except OSError:
            pass

    print()
    # ---- the three conditions, each checked separately --------------------
    inside = [r for r in rows if r[0] <= D]
    outside = [r for r in rows if r[0] > D]
    a = all(r[1] and r[2] for r in inside)
    b = all((not r[1]) and (not r[2]) for r in outside)
    c = all(r[4] for r in rows)
    print("  (a) both CONFORM for every v <= %d (%d rungs): %s"
          % (D, len(inside), "PASS" if a else "FAIL"))
    print("  (b) both REFUSE  for every v >  %d (%d rungs): %s"
          % (D, len(outside), "PASS" if b else "FAIL"))
    print("  (c) verdicts agree on every rung:               %s"
          % ("PASS" if c else "FAIL"))
    print()
    # ⛔ non-vacuity: the ladder must contain BOTH verdicts from BOTH authorities
    nv = (any(r[1] for r in rows) and any(not r[1] for r in rows)
          and any(r[2] for r in rows) and any(not r[2] for r in rows))
    print("  non-vacuity -- both authorities produced BOTH verdicts somewhere: %s"
          % ("PASS" if nv else "*** FAIL: a one-sided ladder proves nothing ***"))

    # ---- (d) sigrok must refuse FOR THE STATED REASON -------------------
    # ⛔⛔ THIS WAS PRINTED AND NEVER ASSERTED. "Above the band sigrok decodes
    # 0xD5 not 0x55" is the gate's advertised finding -- the one-bit sample-grid
    # shift the derivation predicts -- and the gate was scored purely on
    # CONF/VIOL, so sigrok could have refused above the band for ANY reason
    # (truncated file, wrong baud, no annotations at all) and passed. The
    # project's own rule is that a mutant must die for its stated reason; it had
    # never been applied to our own flagship foreign gate.
    above = [r for r in rows if r[0] > D]
    shifted = [r for r in above if r[3] == SHIFTED]
    wrong_reason = [r for r in above if r[3] != SHIFTED]
    print("  (d) above the band sigrok decodes 0x%02X (the predicted one-bit"
          % SHIFTED)
    print("      grid shift) on every rung: %s"
          % ("PASS -- %d of %d" % (len(shifted), len(above)) if not wrong_reason
             else "*** FAIL: %s refused for an UNNAMED reason (decoded %s) ***"
             % ([r[0] for r in wrong_reason],
                ["0x%02X" % r[3] if r[3] is not None else None
                 for r in wrong_reason])))
    d_ok = bool(above) and not wrong_reason

    tf_ok = not tool_failures
    if tool_failures:
        print()
        print("  *** SIGROK FAILED TO RUN on %d rung(s): %s"
              % (len(tool_failures), tool_failures))
        print("      A tool failure is not a verdict. Without this check those")
        print("      rungs would have read as VIOL and the gate would be GREEN.")

    ok = a and b and c and nv and d_ok and tf_ok
    print()
    print("  GATE A-FOREIGN: %s" % (
        "PASSED -- D_UART = %d is UART's jitter tolerance, not our monitor's,"
        " and sigrok refuses above it for the predicted reason" % D
        if ok else "FAILED -- the computed band is not corroborated; do not use it"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
