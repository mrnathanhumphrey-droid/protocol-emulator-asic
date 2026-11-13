"""GATE tracked-images -- every tracked image is pinned or exempt (Wilson 11-03).

⛔⛔ WHY. The 60 MHz move converted the program sources to real time and left
four TRACKED images stale (onewire_image, uart_rx_image, uart_tx_image,
uart_tx_busy_image): they sat outside `test/artefacts.sha256`, so
`gate_manifest` never compared them with their recipes, and only each sim
runner's own "tracked == pe_asm output" line -- a sim-shard check, hours in --
saw it. A manifest closes the class only if nothing can be tracked OUTSIDE it.

THE RULE. Every git-tracked image file (`*.hex`, `*.mem`) is either
  * a line in `test/artefacts.sha256` (so `gate_manifest` checks its hash and
    `make_smoke_image.py --all` names its recipe), or
  * in EXEMPT below, with the reason it is not regenerated and what pins it.
An exempt entry that matches no tracked file is red too (a reason left behind
for a file that is gone is inherited by the next file of that name).
MUST-FIRE: a planted unlisted image is red.
POSITIVE TOKEN: `GATE tracked-images: PASSED`.
"""

from __future__ import annotations

import os
import posixpath
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MANIFEST = os.path.join(HERE, "artefacts.sha256")
LINE = re.compile(r"^([0-9a-f]{64})\s+(\S+)\s+#")
PATTERNS = ("*.hex", "*.mem")

_HW = ("the bytes the PA100T ran on the bench; pinned by SHA-256 in %s, red "
       "until the bench is re-run and re-recorded")
#: repo path -> why it is not in the manifest, and what pins it instead
EXEMPT = {
    # F1.5 (11-09): regenerated as v2 (fpga/sim/i2c_fram.py image()); the
    # tracked file == the generator is checked by fpga/sim/run_fpga_i2c.py,
    # and its hardware witness reads STALE until the bench re-witness
    "fpga/images/i2c_fram_fpga.hex":
        "the v2 I2C FRAM board image; tracked == fpga/sim/i2c_fram.py's image() "
        "checked by fpga/sim/run_fpga_i2c.py (CI, shard fpga); the PA100T ran "
        "its v1 predecessor -- model/gate_i2c_hw_witness.py is STALE until the "
        "bench re-witness on the v2 bitstream",
    "fpga/feeds/i2c_fram_feed.hex": _HW % "model/gate_i2c_hw_witness.py",
    "fpga/feeds/i2c_fram_falls.hex": _HW % "model/gate_i2c_hw_witness.py",
    "fpga/feeds/onewire_fpga_feed.hex": _HW % "model/gate_onewire_hw_witness.py",
}


def tracked():
    r = subprocess.run(["git", "ls-files", "--"] + list(PATTERNS), cwd=ROOT,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("git ls-files failed: %s" % r.stderr[:200])
    return sorted(p for p in r.stdout.splitlines() if p)


def pinned():
    with open(MANIFEST, encoding="ascii", errors="replace") as fh:
        names = [m.group(2) for m in map(LINE.match, fh.read().splitlines()) if m]
    # the manifest names files relative to test/ (F1.5: the FPGA board's UART
    # images are pinned as ../fpga/images/..., so the path is normalised)
    return {posixpath.normpath("test/" + n) for n in names}


def judge(files, pins, exempt):
    """-> [problem] for the tracked `files`."""
    probs = []
    for f in files:
        if f not in pins and f not in exempt:
            probs.append("%s is tracked but neither in test/artefacts.sha256 nor "
                         "exempt -- pin it (make_smoke_image.py --all) or exempt it "
                         "with a reason" % f)
    for f in sorted(set(exempt) - set(files)):
        probs.append("EXEMPT entry %s matches no tracked file" % f)
    for f in sorted(set(exempt) & pins):
        probs.append("%s is both pinned and exempt" % f)
    return probs


def main():
    print("GATE tracked-images: every tracked image is in the manifest or exempt")
    try:
        files, pins = tracked(), pinned()
    except (RuntimeError, OSError) as e:
        print("  *** COULD NOT RUN: %s" % e)
        print("  GATE tracked-images: COULD NOT RUN")
        return 1
    probs = judge(files, pins, EXEMPT)
    n_pin = sum(1 for f in files if f in pins)
    print("  %d tracked image(s): %d pinned, %d exempt" % (len(files), n_pin,
                                                          len(files) - n_pin))
    for f in sorted(EXEMPT):
        print("    exempt %-38s %s" % (f, EXEMPT[f][:70]))
    for p in probs:
        print("  *** " + p)
    rc = 1 if probs else 0
    plant = "test/planted_unlisted_image.hex"
    mp = judge(files + [plant], pins, EXEMPT)
    hit = any(plant in p for p in mp)
    print("  must-fire: a planted unlisted image          %s"
          % ("red  ok" if hit else "*** STAYED GREEN"))
    rc |= 0 if hit else 1
    print()
    print("  GATE tracked-images: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
