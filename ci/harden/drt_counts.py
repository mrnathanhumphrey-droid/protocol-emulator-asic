"""Detailed-routing violation count per pass, read so it is CURRENT (Wilson 11-25, J3 fix).

OpenROAD's stdout reaches the step log block-buffered: on box 2 (11-25) the log stood at "pass 0, 50 %" while the
router had finished four passes (49,626 / 32,870 / 30,903 / 11,613), so a gate reading the log saw nothing for ~1 h.
harden.yml therefore runs J3 with DRT_SAVE_DRC_REPORT_ITERS=1: the router writes its own violation report after every
pass (drt.tcl: -drc_report_iter_step 1, next to -output_drc <step>/<design>.drc). Those files are flushed when the pass
ends. This reads them; if there are none it falls back to the log's "Number of violations" lines, and it returns
whichever source has seen more passes.

  python drt_counts.py <run_dir>          -> prints the counts, one per pass, space-separated
"""
import glob
import os
import re
import sys


def from_reports(run_dir):
    per = {}
    for f in glob.glob(os.path.join(run_dir, "*-openroad-detailedrouting", "**", "*.drc*"), recursive=True):
        m = re.search(r"(\d+)\D*$", os.path.basename(f))   # the pass number OpenROAD appends to the report name
        if not m:
            continue
        txt = open(f, errors="replace").read()
        per[int(m.group(1))] = len(re.findall(r"violation type", txt))
    if not per:
        return []
    base = min(per)                                        # OpenROAD may number passes from 0 or from 1
    return [per[k] for k in sorted(per) if k - base < len(per)]


def from_log(run_dir):
    v = []
    for f in glob.glob(os.path.join(run_dir, "*-openroad-detailedrouting", "*.log")):
        v += [int(x) for x in re.findall(r"Number of violations = (\d+)", open(f, errors="replace").read())]
    return v


def counts(run_dir):
    a, b = from_reports(run_dir), from_log(run_dir)
    return a if len(a) >= len(b) else b


if __name__ == "__main__":
    print(" ".join(str(x) for x in counts(sys.argv[1])))
