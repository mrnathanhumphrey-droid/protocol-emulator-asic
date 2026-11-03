"""GATE clock-literals -- no typed clock outside the clock source (Wilson 11-03).

⛔⛔ WHY. The 50 -> 60 MHz move found 50 MHz typed into the RTL, five
benches, the assembler's I2C floors, about fifteen golden models and every
shipped program -- each copy correct where it was written and wrong the day
the clock moved. `model/clock.py` is now the one reader and the board configs
(info.yaml, fpga/board.yaml) the only places a frequency is written. This gate
is what stops a new copy coming back: it scans every tracked code file for the
shapes those copies took.

⭐ A DELIBERATE NUMBER SAYS SO ON ITS LINE: `clock-ok: <reason>` (a record of
a past run at 50 MHz, a must-fire's mismatched clock, a cycle count that is a
cycle count). An empty reason is red.

⚠ NOT A PARSER, a textual scan for the shapes that occurred. It cannot see a
clock spelled some new way; it can stop the old ways returning.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

#: the clock source and the board configs: the only files allowed a frequency
#: ... and the two GENERATED bench headers, whose one number
#: `gate_clock_consistency` holds to the board config (as it does the RTL
#: `CLK_PERIOD_PS` defaults, which none of the shapes below match).
EXEMPT = {"model/clock.py", "info.yaml", "src/config.json", "fpga/board.yaml",
          "model/gate_clock_literals.py", "test/pe_clock.vh",
          "fpga/sim/fpga_clock.vh"}

CODE = re.compile(r"\.(py|v|vh|sv|sh|tcl)$")

#: (name, regex) -- the shapes the copies took
SHAPES = [
    ("a typed 50 MHz", re.compile(r"(?<![\w.])(50_000_000|50000000|50e6|5e7)(?![\w.])")),
    ("a typed clock constant", re.compile(
        r"\b(F_CLK|FCLK|CLK_HZ|HZ|f_clk|f_mhz|NS_PER_CYCLE|CY_PER_US|CLK_NS|"
        r"CLK_PERIOD_NS|PERIOD_NS|SLOW_PERIOD_NS)\s*=\s*[1-9]")),
    ("a typed bench clock", re.compile(r"always\s*#\s*\d+(\.\d+)?\s*clk\b")),
    ("cycles -> us at 50 MHz", re.compile(r"/\s*50\.0(?![\d])")),
    ("a typed 20 ns period in a bench", re.compile(r"(?<![\w.])20\.0\s*\*|/\s*20\.0(?![\d])")),
]
OK_MARK = re.compile(r"clock-ok:\s*(\S.*)?$")


def tracked():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout.split()
    return [p for p in out if CODE.search(p) and p not in EXEMPT]


def scan(files):
    """{path: text} -> [(path, line_no, shape, line)] of unexcused hits."""
    hits = []
    for p, text in files.items():
        for i, line in enumerate(text.split("\n"), 1):
            for name, rx in SHAPES:
                if not rx.search(line):
                    continue
                m = OK_MARK.search(line)
                if m and m.group(1):
                    continue
                hits.append((p, i, name if not m else name + " (clock-ok with NO reason)",
                             line.strip()))
                break
    return hits


def main():
    files = {}
    for p in tracked():
        try:
            with open(os.path.join(ROOT, p), encoding="utf-8", errors="replace") as fh:
                files[p] = fh.read()
        except OSError:
            continue
    hits = scan(files)
    print("  scanned %d tracked code files (exempt: %s)" % (len(files), ", ".join(sorted(EXEMPT))))
    for p, i, name, line in hits:
        print("    *** %s:%d  %s  | %s" % (p, i, name, line[:110]))
    rc = 1 if hits else 0
    print("  --- must-fires: a planted literal goes red ---")
    for what, text in (("F_CLK = 50_000_000", "F_CLK = 50_000_000\n"),
                       ("always #10 clk = ~clk;", "  always #10 clk = ~clk;\n"),
                       ("cycles / 50.0 as us", "print(n / 50.0)\n"),
                       ("clock-ok with no reason", "HZ = 50e6   # clock-ok:\n")):
        red = bool(scan({"planted.py": text}))
        print("    must-fire: %-28s %s" % (what, "red  ok" if red else "*** MISSED"))
        rc |= 0 if red else 1
    ok = not scan({"ok.py": "F_CLK = 50_000_000   # clock-ok: a record of the v1 run\n"})
    print("    accepted : %-28s %s" % ("clock-ok with a reason", "ok" if ok else "*** WRONGLY RED"))
    rc |= 0 if ok else 1
    print()
    print("  GATE clock-literals: %s" % ("PASSED" if rc == 0 else "FAILED (%d unexcused)" % len(hits)))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
