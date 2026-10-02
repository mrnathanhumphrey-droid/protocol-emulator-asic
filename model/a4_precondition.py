"""A4 PRECONDITION GATE -- what must be true before "closes at 50 MHz" means anything.

THE ONE CLAIM: the timing numbers were extracted from real paths through real
sequential logic, not from an empty path set.

⛔⛔ WHY THIS EXISTS, AND IT IS NOT HYPOTHETICAL. For weeks this project's
gate-level job was green and its post-PnR report read `WNS 0.0` at all three
corners -- on the Tiny Tapeout template stub: 53 cells, entirely combinational,
ZERO FLIP-FLOPS. `0.0` there does not mean "met with zero margin", it means
**NO PATH**. An empty path set has no worst slack, and the tool prints a zero.
Every downstream reading of that number was vacuous.

The assertion was never wrong. The SUBJECT was too simple to reach the tool
path. No amount of staring at the gate catches that, so the gate has to check
the subject:

  P1  the netlist contains flip-flops                      (>0, and how many)
  P2  the worst-slack report carries a NUMERIC slack        (not an empty set)
  P3  at least one reported path ENDS AT A FLIP-FLOP        (not all pad-to-pad)
  P4  `report_checks --slack_max -0.01` found NO paths      (zero violations)
  P5  `check_setup` is silent -- no unconstrained endpoints, no missing
      input delay, no loops, no generated-clock problems

⛔ P3 is the one that would have caught the stub, and it is the one a human
reviewer would skip: a design can have flops and still report only
combinational feedthrough paths if the clock is not constrained.

⚠ NOT IN CI, SAID PLAINLY. The netlist and the STA reports are produced by a
third-party GitHub Action (`TinyTapeout/tt-gds-action`) whose steps this repo
does not control, and they exist only inside its uploaded artifact. This gate
therefore runs against a downloaded artifact, by hand, and its output is what
`docs/SILICON_EVIDENCE.md` records. Claiming it as a CI gate would be a nicer
sentence and a false one.

Usage:
    python model/a4_precondition.py <netlist.v> <stapostpnr_dir>
"""

from __future__ import annotations

import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

FLOP_RE = re.compile(r"^\s*(sg13cmos5l_(?:dfrbpq|dfrbp|sdfrbp|dlrbp)\w*)\s", re.M)
CELL_RE = re.compile(r"^ *(sg13cmos5l_\w+)", re.M)


def read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def check_netlist(path: str) -> dict:
    txt = read(path)
    flops = FLOP_RE.findall(txt)
    cells = CELL_RE.findall(txt)
    filler = [c for c in cells if re.match(r"sg13cmos5l_(decap|fill|tap)", c)]
    return {"flops": len(flops), "total": len(cells),
            "filler": len(filler), "logic": len(cells) - len(filler)}


def check_corner(d: str) -> dict:
    out = {"corner": os.path.basename(d)}
    for key, fn in (("setup_ws", "ws.max.rpt"), ("hold_ws", "ws.min.rpt")):
        p = os.path.join(d, fn)
        if not os.path.isfile(p):
            out[key] = None
            continue
        m = re.search(r":\s*(-?[\d.]+)\s*$", read(p).replace("\r", ""), re.M)
        out[key] = float(m.group(1)) if m else None
    maxrpt = os.path.join(d, "max.rpt")
    if os.path.isfile(maxrpt):
        txt = read(maxrpt)
        eps = re.findall(r"Endpoint: \S+ \(([^)]*)\)", txt)
        out["paths"] = len(eps)
        out["ff_endpoints"] = sum(1 for e in eps if "flip-flop" in e)
        out["no_paths"] = "No paths found" in txt
    else:
        out["paths"] = out["ff_endpoints"] = 0
        out["no_paths"] = True
    checks = os.path.join(d, "checks.rpt")
    if os.path.isfile(checks):
        txt = read(checks).replace("\r", "")
        # ⛔⛔ PARSE BY SECTION, NOT BY SEARCHING THE WHOLE FILE. An earlier read
        # of this report used `grep` for matching LINES and took "No paths
        # found." to be the answer to `report_checks -unconstrained`, because the
        # two lines appeared adjacent in the grep OUTPUT. They are 136 lines
        # apart in the file. "No paths found." belongs to
        # `report_checks --slack_max -0.01`, which is a much STRONGER statement:
        # no path has slack worse than -0.01 ns, i.e. zero timing violations.
        # Section boundaries are the only safe way to attribute a verdict in a
        # multi-report file.
        secs, cur = {}, None
        for line in txt.split("\n"):
            if line.startswith(("report_", "check_")):
                cur = line.strip()
                secs[cur] = []
            elif cur:
                secs[cur].append(line)

        def body(prefix):
            for k, v in secs.items():
                if k.startswith(prefix):
                    return "\n".join(v)
            return None

        viol = body("report_checks --slack_max")
        out["no_violations"] = ("No paths found" in viol) if viol is not None else None
        setup = body("check_setup")
        out["setup_clean"] = (
            not [l for l in setup.split("\n")
                 if l.strip() and not l.startswith("=")]) if setup is not None else None
        out["violators"] = txt.count("(VIOLATED)")
    else:
        out["no_violations"] = out["setup_clean"] = None
        out["violators"] = None
    return out


def main(argv) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    netlist, stadir = argv[1], argv[2]
    print("=" * 76)
    print("A4 PRECONDITION GATE")
    print("=" * 76)
    n = check_netlist(netlist)
    print("  netlist: %s" % netlist)
    print("    total instances %d   logic %d   filler/decap/tap %d"
          % (n["total"], n["logic"], n["filler"]))
    print("    FLIP-FLOPS: %d" % n["flops"])
    rc = 0
    p1 = n["flops"] > 0
    print("    P1  netlist contains flip-flops: %s"
          % ("PASS (%d)" % n["flops"] if p1
             else "*** FAIL -- zero flops: every timing number here is vacuous"))
    rc |= 0 if p1 else 1

    corners = sorted(os.path.join(stadir, d) for d in os.listdir(stadir)
                     if os.path.isdir(os.path.join(stadir, d)))
    if not corners:
        print("  *** FAIL -- no corner directories under %s" % stadir)
        return 1
    print()
    print("  %-24s %-10s %-10s %-8s %-8s %-8s %s"
          % ("corner", "setup WS", "hold WS", "paths", "->flop", "slew", "P2 P3 P4 P5"))
    for d in corners:
        c = check_corner(d)
        p2 = c["setup_ws"] is not None and c["hold_ws"] is not None and not c["no_paths"]
        p3 = c["ff_endpoints"] > 0
        p4 = c["no_violations"] is True
        p5 = c["setup_clean"] is True
        rc |= 0 if (p2 and p3 and p4 and p5) else 1
        print("  %-24s %-10s %-10s %-8d %-8d %-8s %s %s %s %s"
              % (c["corner"],
                 "%.4f" % c["setup_ws"] if c["setup_ws"] is not None else "NONE",
                 "%.4f" % c["hold_ws"] if c["hold_ws"] is not None else "NONE",
                 c["paths"], c["ff_endpoints"],
                 c["violators"] if c["violators"] is not None else "?",
                 "ok" if p2 else "**", "ok" if p3 else "**",
                 "ok" if p4 else "**", "ok" if p5 else "**"))
    print()
    print("  P2 numeric worst-slack present   P3 >=1 path ends at a flop")
    print("  P4 no path with slack < -0.01 (zero violations)")
    print("  P5 check_setup silent (no unconstrained endpoint / missing delay / loop)")
    print("  `slew` column = max_slew + max_fanout lint violators, NOT timing")
    print()
    if rc == 0:
        print("  A4 PRECONDITION: PASSED -- the timing numbers describe real")
        print("  sequential paths. ⚠ The claim they support is scoped to the SDC")
        print("  that PnR actually used; see docs/SILICON_EVIDENCE.md.")
    else:
        print("  *** A4 PRECONDITION FAILED -- do not quote any timing number")
        print("      from this run. A zero slack on an empty path set is 'no path'.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
