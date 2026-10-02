"""THE THIRD TABLE -- an off-pattern protocol, written last, read by a third
foreign decoder.

⛔⛔ WHY IT IS WRITTEN LAST. UART and SPI are the two protocols the descriptor was
designed against, so neither can tell you whether the FORMAT generalises -- only
that it covers its own design inputs. A pulse train written AFTER the descriptor
was frozen can fail, and if the format had been shaped to fit it, "the format
generalises" would have been unfalsifiable. It is also distinct from the
input-branch table, which exists to exercise a FIELD rather than to test the shape.

⭐ AND IT IS OFF-PATTERN IN THE WAYS THAT MATTER: no framing, no data, no clock
line, no transfer, no termination -- a periodic level running forever, with the
duty cycle varying period to period. The one thing it shares with UART and SPI is
that it is a timed sequence of pin levels, which is precisely the claim.

sigrok's `pwm` PD is a THIRD foreign authority, independent of the `uart` and
`spi` decoders used in TA-01 and in this rung's Gate 0.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from interp import Interp, table_pwm

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

F_CLK = 50_000_000
PIN = 0


def wsl_path(p: str) -> str:
    p = os.path.abspath(p).replace("\\", "/")
    return ("/mnt/" + p[0].lower() + p[2:]) if len(p) > 1 and p[1] == ":" else p


def dump(levels, path: str) -> int:
    """⛔ TEMP FILE, VERIFY, REPLACE."""
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(bytes(v & 1 for v in levels))
    assert os.path.getsize(tmp) == len(levels)
    os.replace(tmp, path)
    return len(levels)


def sigrok_pwm(binpath: str, row: str) -> list:
    cmd = ("sigrok-cli -i %s -I binary:numchannels=1:samplerate=%d "
           "-P pwm:data=0:polarity=active-high -A pwm=%s"
           % (wsl_path(binpath), F_CLK, row))
    # ⛔ encoding PINNED to utf-8. `text=True` decodes with the locale codepage,
    # and cp1252 turned the decoder's `2.0 us` into `2.0 Î¼s` -- the same cp1252
    # trap that killed a TA-01b runner mid-report, now on the INPUT side.
    r = subprocess.run(["wsl.exe", "-d", "Ubuntu", "--", "bash", "-lc", cmd],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    lines = [l.strip() for l in out.replace("\r", "").split("\n") if l.strip()]
    return [l.split(":", 1)[1].strip() for l in lines if l.startswith("pwm-1:")]


def main() -> int:
    period = 100                                 # 100 cycles @ 50 MHz = 500 kHz
    print("=== TA-02 -- THE OFF-PATTERN TABLE (PWM), WRITTEN LAST ===")
    print("    machine: the SAME model/ta02/interp.py, unchanged")
    print("    foreign authority: sigrok `pwm` PD -- a THIRD decoder, independent")
    print("    period = %d cycles @ %d Hz = %.1f kHz"
          % (period, F_CLK, F_CLK / period / 1000.0))
    print()

    cases = [
        ("d25",  [25] * 12),
        ("d50",  [50] * 12),
        ("d75",  [75] * 12),
        # ⭐ the varying train: duty changes period to period, which a fixed
        # two-entry oscillator would not exercise
        ("vary", [10, 30, 50, 70, 90, 70, 50, 30, 10, 40, 60, 80]),
    ]
    print("  %-7s %-10s %-26s %-22s %s"
          % ("case", "entries", "duty wanted", "sigrok duty read", "match"))
    allok = True
    for name, duties in cases:
        tbl = table_pwm(duties, period, pin=PIN)
        # ⛔ RUN TWO EXTRA PERIODS. The PD measures a period between consecutive
        # RISING edges, and the table's first entry drives HIGH at cycle 0, so
        # there is no opening edge for period 0 and no closing edge for the last
        # one. Stopping at `period*len` therefore reports len-2 duties and reads as
        # a mismatch -- the TA-01b truncated-frame bench bug in a new costume. The
        # reported sequence is duties[1:], which is what gets compared.
        n = period * (len(duties) + 2)
        wave = Interp(tbl).run(n, pin=PIN)
        path = os.path.join(HERE, "wave_pwm_%s.bin" % name)
        dump(wave, path)

        got_d = sigrok_pwm(path, "duty-cycle")
        got_p = sigrok_pwm(path, "period")
        nums = [float(m.group(1)) for m in
                (re.search(r"([0-9]+\.?[0-9]*)\s*%", s) for s in got_d) if m]
        want = [float(d) for d in duties[1:]]              # first period has no edge
        k = min(len(nums), len(want))
        match = (k >= len(want) and
                 all(abs(nums[i] - want[i]) < 0.51 for i in range(len(want))))
        allok = allok and match
        print("  %-7s %-10d %-26s %-22s %s"
              % (name, len(tbl),
                 " ".join("%g" % d for d in want[:6]) + ("..." if len(want) > 6 else ""),
                 " ".join("%g" % v for v in nums[:6]) + ("..." if len(nums) > 6 else ""),
                 "OK (%d/%d)" % (len(want), len(want)) if match
                 else "*** MISMATCH (%d read, %d wanted) ***" % (len(nums), len(want))))
        if not match:
            print("        raw duty: %s" % got_d[:8])
            print("        raw period: %s" % got_p[:4])

    # the period row, checked once -- the decoder's own view of our timebase
    tbl = table_pwm([50] * 12, period, pin=PIN)
    wave = Interp(tbl).run(period * 14, pin=PIN)
    p = os.path.join(HERE, "wave_pwm_d50.bin")
    dump(wave, p)
    per = sigrok_pwm(p, "period")
    print()
    print("  period row (d50): %s" % (per[:4] or "-"))
    print("    expected %.1f kHz from a %d-cycle table period at %d Hz"
          % (F_CLK / period / 1000.0, period, F_CLK))
    print()

    print("  THIRD-TABLE VERDICT: %s" %
          ("PASSED -- a protocol the descriptor was never designed against, "
           "written after the freeze, comes off the unchanged machine in two "
           "entries per period and is read correctly by a third foreign decoder."
           if allok else
           "FAILED -- the format does not generalise beyond its design inputs, "
           "which is exactly what writing this table last was meant to detect."))
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
