"""SHARE COUPLING -- no register's next state may depend on a register it has no
reason to read (PIT chunk 2, canary 10-30).

THE ONE CLAIM: for every entry of FORBIDDEN, the flops that feed the target
register's next state (D and enable, back through combinational logic to the
first flop) include none of the forbidden registers.

⛔⛔ WHY THIS IS A GATE AND NOT A ONE-OFF CHECK. yosys's `share` pass merges
operators that sit in MUTUALLY EXCLUSIVE branches into one shared unit with
muxed inputs. In PIT chunk 2, the budget counter's reload `(1 << bsel) - 1`
(computed only when the PIT starts) and the record builder's `<< ke` / `>> ke`
(only while it runs) became ONE shifter -- so `bud_cnt`'s next state carried
k's whole record-building path, and the canary's second-worst family
(k -> bud_cnt, +2.107 ns) was a path the RTL never wrote. Nothing in the
source shows it; only the netlist does. The fix (`bud_init`, its own register)
is held here so a later edit cannot quietly re-create the sharing.

HOW: a structural walk of the synthesised yosys JSON netlist, the same input
`gate_reset_audit` reads (PE_NETLIST_JSON, built by test/local_netlist.sh).
A TARGET that matches no flop is RED, not a pass -- an entry that describes
nothing has stopped guarding anything (the reset audit's stale-entry lesson).
                                                token: GATE share-coupling: PASSED
"""

from __future__ import annotations

import collections
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

NETLIST = os.environ.get("PE_NETLIST_JSON", r"C:\tmp\local_netlist.json")
TOP = "tt_um_protocol_emulator"

#: target register prefix -> (forbidden source prefixes, why it must not read them)
FORBIDDEN = {
    "u_pit.bud_cnt": (
        ("u_pit.k", "u_pit.ke", "u_pit.tcnt", "u_pit.v_"),
        "the capture budget counts cycles: its next state is a decrement and a "
        "reload from bud_init. A record-builder register (k, its shift amount, "
        "the interval counter, the record words) in its cone is yosys `share` "
        "merging the reload shift with the record shifts (canary 10-30)."),
}


def _names(m):
    names = collections.defaultdict(list)
    for nm, info in m["netnames"].items():
        for i, b in enumerate(info["bits"]):
            if isinstance(b, int):
                names[b].append("%s[%d]" % (nm, i))
    return names


def source_regs(m, target):
    """(flops of `target`, Counter of the register names feeding their D / enable)."""
    names = _names(m)
    drv = {}
    for cn, c in m["cells"].items():
        for p, bits in c["connections"].items():
            if c.get("port_directions", {}).get(p) == "output":
                for b in bits:
                    if isinstance(b, int):
                        drv[b] = cn

    def is_ff(cn):
        return "DFF" in m["cells"][cn]["type"]

    def qname(cn):
        return [nm for b in m["cells"][cn]["connections"].get("Q", [])
                for nm in names.get(b, []) if not nm.startswith("$")]

    flops = [cn for cn in m["cells"]
             if is_ff(cn) and any(x.startswith(target + "[") for x in qname(cn))]
    src = collections.Counter()
    for tc in flops:
        c = m["cells"][tc]
        stack = [b for p, bits in c["connections"].items() if p in ("D", "E")
                 for b in bits if isinstance(b, int)]
        seen = set()
        while stack:
            b = stack.pop()
            if b in seen or b not in drv:
                continue
            seen.add(b)
            cn = drv[b]
            if is_ff(cn):
                for nm in qname(cn):
                    src[re.sub(r"\[\d+\]$", "", nm)] += 1
                continue
            cc = m["cells"][cn]
            stack += [x for p, bits in cc["connections"].items()
                      if cc["port_directions"].get(p) == "input" for x in bits if isinstance(x, int)]
    return flops, src


def coupling_problems(table, found):
    """THE ONE JUDGEMENT (the meta seam). `found`: target -> (n flops, sources).
    -> [problem]: a target matching no flop, or a forbidden source in a cone."""
    probs = []
    for tgt, (forbid, _why) in table.items():
        n, src = found.get(tgt, (0, collections.Counter()))
        if n == 0:
            probs.append("%s matches no flop in the netlist -- the entry guards nothing" % tgt)
            continue
        bad = sorted(s for s in src if any(s.startswith(f) for f in forbid))
        if bad:
            probs.append("%s's next state reads %s" % (tgt, ", ".join(bad)))
    return probs


def _synthetic(coupled):
    """a 3-flop netlist: bud_cnt <- AND <- (bud_cnt, and k when `coupled`)."""
    cells = {
        "f_k": {"type": "$_DFF_P_", "port_directions": {"D": "input", "Q": "output"},
                "connections": {"D": [9], "Q": [2]}},
        "f_b": {"type": "$_DFF_P_", "port_directions": {"D": "input", "Q": "output"},
                "connections": {"D": [4], "Q": [3]}},
        "g": {"type": "$_AND_", "port_directions": {"A": "input", "B": "input", "Y": "output"},
              "connections": {"A": [3], "B": [2] if coupled else [3], "Y": [4]}},
    }
    nets = {"u_pit.k": {"bits": [2]}, "u_pit.bud_cnt": {"bits": [3]}}
    return {"cells": cells, "netnames": nets}


def must_fire():
    rc = 0
    print("\n  --- must-fire: the gate rejects what it claims to ---")
    for label, m, want_red in (
            ("a planted k -> bud_cnt coupling", _synthetic(True), True),
            ("the same netlist without it", _synthetic(False), False),
            ("a target that matches no flop", {"cells": {}, "netnames": {}}, True)):
        found = {t: (lambda fl, s: (len(fl), s))(*source_regs(m, t)) for t in FORBIDDEN}
        red = bool(coupling_problems(FORBIDDEN, found))
        ok = red == want_red
        print("    %-44s %s  %s" % (label, "red  " if red else "green", "ok" if ok else "*** MISSED"))
        if not ok:
            rc = 1
    return rc


def main() -> int:
    print()
    print("=" * 78)
    print("SHARE COUPLING -- no register reads what it has no reason to (canary 10-30)")
    print("=" * 78)
    if not os.path.isfile(NETLIST):
        print("  *** netlist JSON not found: %s" % NETLIST)
        print("  ⛔ RED rather than skipped: a check that cannot see the design")
        print("     has not checked it.")
        return 1
    with open(NETLIST, encoding="utf-8") as fh:
        d = json.load(fh)
    if TOP not in d.get("modules", {}):
        print("  *** %s absent from the netlist" % TOP)
        return 1
    m = d["modules"][TOP]
    print("  netlist: %s" % NETLIST)
    found = {}
    for tgt, (forbid, why) in FORBIDDEN.items():
        flops, src = source_regs(m, tgt)
        found[tgt] = (len(flops), src)
        print("  %-16s %3d flops; its next state reads: %s" % (tgt, len(flops), ", ".join(sorted(src)) or "-"))
        print("  %-16s forbidden: %s" % ("", ", ".join(forbid)))
    probs = coupling_problems(FORBIDDEN, found)
    rc = must_fire()
    print()
    for p in probs:
        print("  *** " + p)
    rc = rc or (1 if probs else 0)
    print("  GATE share-coupling: %s" % ("FAILED" if rc else "PASSED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
