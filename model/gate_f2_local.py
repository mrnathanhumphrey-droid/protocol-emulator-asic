"""F2 face 3 on every push: every output bit is a flop Q, priced by M_COMB_OUT.

⛔⛔ WHY (ruling MU). `M_COMB_OUT` -- the combinational `prog_mode` mux on the
`uio` outputs that ruling F2 forbids, because a glitch on SCL or SCLK is an
extra clock edge -- was killed only by hand: `test/local_netlist.sh M_COMB_OUT`
then `f2_flop_driven_outputs.py` on the JSON. Nothing in CI or `run_a2` ever
built the mutant, so the claim "F2 catches it" was as old as the day it was
last typed. The F2 selftest prices the CHECK on synthetic netlists; this gate
prices it on the REAL design, both ways:

    PE_NETLIST_JSON       the clean yosys graph       -> F2 must PASS
    PE_NETLIST_COMB_JSON  the same recipe, -D M_COMB_OUT -> F2 must FAIL

Both are built by `ci/run_gates.sh`'s netlist step (~5 s each). RED without
either: a structural check that has not seen the design has not checked it.
⚠ Yosys pre-mapping cells, not the PDK netlist -- structural only. The
authoritative F2 run is on the hardened netlist (`f2_flop_driven_outputs.py
<gate_level_netlist.v>`); this one is the one that runs on every push.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import f2_flop_driven_outputs as f2                               # noqa: E402


def run(path):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = f2.check_json(path)
    return rc, buf.getvalue()


def main() -> int:
    print()
    print("=" * 78)
    print("  F2 FACE 3, LOCAL NETLIST -- every output a flop Q (priced by M_COMB_OUT)")
    print("=" * 78)
    rc = 0
    for env, want, label in (
            ("PE_NETLIST_JSON", 0, "clean design       must PASS"),
            ("PE_NETLIST_COMB_JSON", 1, "M_COMB_OUT mutant  must FAIL")):
        p = os.environ.get(env)
        if not p or not os.path.isfile(p):
            print("  *** no netlist at %s -- RED rather than skipped" % env)
            rc = 1
            continue
        got, out = run(p)
        summary = [l.strip() for l in out.splitlines()
                   if "output bits examined" in l or "$_" in l][:3]
        ok = (got == want)
        print("  %-30s %s   (%s)" % (label, "ok" if ok else "*** WRONG",
                                     os.path.basename(p)))
        for s in summary:
            print("      | %s" % s)
        if not ok:
            rc = 1
    print()
    print("=" * 78)
    print("  GATE f2-local: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
