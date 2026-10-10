"""CDC5: no top-level input reaches core logic except through its synchronizer.

⛔⛔ WHY (rulings CDC1-CDC5, silicon fixes #4 and #5). `ui_in[7]` (PROG) fed
`run` straight into the engine's time counter and key adders, `ui_in[5]`
(PTR_RST) fed the load pointer, and `rst_n` released every flop directly.
The host runs on its own clock, so each was a metastability hazard that
neither simulation nor STA can see: the SDC's input delay assumes a
synchronous host, and a simulator never resolves a flop late. It was found
only because the worst timing path of the 29aaeb3 canary started at a port.

THE RULE, per input bit of the yosys graph (`PE_NETLIST_JSON`, the same
pre-mapping netlist the reset audit and F2 use):

  SYNC        the pin may reach ONLY the D pin of its declared synchronizer's
              first flop (a flop whose Q net carries the declared name).
  RESET       `rst_n` may reach ONLY the async reset pins of the declared
              synchronizer flops; every core flop resets on `rst_n_s`.
  QUALIFIED   (D4) the TX nibble / tag pins are sampled on the synchronised
              WR edge, so their combinational cone may end ONLY at the D pins
              of the declared capture flops (`tx_asm`, `tx_tag`, `tx_mem`).
  ASYNC CLEAR (D5) SPI-target CS may also reach the async pins of
              `miso_oe_q`, its declared asynchronous release.

PRICED both ways, like F2-local:
  PE_NETLIST_JSON         the clean graph            -> must PASS
  PE_NETLIST_CDCRAW_JSON  the same recipe, M_CDC_RAW -> must FAIL, naming the
                          ui_in[7] -> run path (today's silicon defect)
RED without either netlist. ⚠ Structural, on yosys pre-mapping cells.
"""

from __future__ import annotations

import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOP = "tt_um_protocol_emulator"


def cs_pin():
    """`CS_PIN` from src/project.v (a spec, read where it is defined)."""
    txt = open(os.path.join(ROOT, "src", "project.v"), encoding="utf-8").read()
    m = re.search(r"(?:local)?param(?:eter)?\s+integer\s+CS_PIN\s*=\s*(\d+)", txt)
    if not m:
        raise SystemExit("*** CS_PIN not found in src/project.v")
    return int(m.group(1))


#: synchronizer first-flop Q names, per input. `uio_in[i]` -> `uio_q0[i]`.
SYNC = {
    ("ui_in", 7): "prog_sync",
    ("ui_in", 5): "ptr_sync",
    ("ui_in", 6): "wr_sync",
    ("ena", 0): "ena_sync",
}
#: every flop allowed to see the RAW `rst_n` on its async pin
RESET_OK = ("rst_sync", "prog_sync", "ptr_sync", "ena_sync", "wr_sync",
            "uio_q0", "uio_q1", "uio_q2")
#: qualifier-sampled data pins (D4) and the flops their cones may end in.
#: The qualifier is the synchronised WR edge (`push_rise` = run & wr_rise).
QUALIFIED = {("ui_in", 0), ("ui_in", 1), ("ui_in", 2), ("ui_in", 3),
             ("ui_in", 4), ("ui_in", 5)}
CAPTURE_OK = ("tx_asm", "tx_tag", "tx_mem")
ASYNC_PINS = ("R", "S", "AD", "L")


def load(path):
    m = json.load(open(path, encoding="utf-8"))["modules"][TOP]
    names = {}
    for n, v in m["netnames"].items():
        if v.get("hide_name"):
            continue
        for b in v["bits"]:
            if isinstance(b, int):
                names.setdefault(b, []).append(n)
    readers = {}
    flops = {}
    for cn, c in m["cells"].items():
        t, con, pd = c["type"], c["connections"], c.get("port_directions", {})
        isff = "DFF" in t or "DLATCH" in t
        if isff:
            flops[cn] = c
        for p, bits in con.items():
            if pd.get(p) != "input":
                continue
            for b in bits:
                if isinstance(b, int):
                    readers.setdefault(b, []).append((cn, p, isff))
    return m, names, readers, flops


def qname(cell, names):
    q = cell["connections"].get("Q", [None])[0]
    return [n for n in names.get(q, [])]


def named(cell, names, prefixes):
    return any(n == p or n.startswith(p + "[") or n.startswith("\\" + p)
               or n == p.split("[")[0] for n in qname(cell, names)
               for p in prefixes)


def cone(start, m, readers, flops):
    """(flop, pin) pairs reached combinationally from net bit `start`."""
    out, seen, todo = [], {start}, [start]
    while todo:
        b = todo.pop()
        for cn, p, isff in readers.get(b, []):
            if isff:
                out.append((cn, p))
                continue
            c = m["cells"][cn]
            for op, d in c.get("port_directions", {}).items():
                if d == "output":
                    for ob in c["connections"][op]:
                        if isinstance(ob, int) and ob not in seen:
                            seen.add(ob)
                            todo.append(ob)
    return out, len(seen)


def check(path, verbose=True):
    m, names, readers, flops = load(path)
    cs = cs_pin()
    bad = []
    table = []
    for port in ("ui_in", "uio_in", "ena", "rst_n"):
        for i, b in enumerate(m["ports"][port]["bits"]):
            if not isinstance(b, int):
                continue
            label = "%s[%d]" % (port, i) if len(m["ports"][port]["bits"]) > 1 else port
            ends, nets = cone(b, m, readers, flops)
            kind = []
            for cn, p in ends:
                c = flops[cn]
                q = ",".join(qname(c, names)[:1]) or cn
                # DIRECT: the pin bit itself sits on this flop pin, no logic
                direct = b in c["connections"].get(p, [])
                if port == "rst_n":
                    ok = p in ASYNC_PINS and named(c, names, RESET_OK) and direct
                    why = "async pin of a synchronizer"
                elif port == "uio_in" and i == cs and p in ASYNC_PINS and named(c, names, ("miso_oe_q",)):
                    ok, why = True, "declared async clear (D5)"
                elif (port, i) in SYNC and p == "D" and direct and named(c, names, (SYNC[(port, i)],)):
                    ok, why = True, "synchronizer first flop"
                elif port == "uio_in" and p == "D" and direct and named(c, names, ("uio_q0",)):
                    ok, why = True, "synchronizer first flop"
                elif (port, i) in QUALIFIED and p == "D" and named(c, names, CAPTURE_OK):
                    ok, why = True, "qualifier-sampled capture (WR edge)"
                else:
                    ok, why = False, "UNSYNCHRONIZED"
                kind.append(why)
                if not ok:
                    bad.append("%s -> %s.%s (%s) through %d net bit(s)"
                               % (label, q, p, flops[cn]["type"], nets))
            table.append((label, len(ends), sorted(set(kind))))
    if verbose:
        for label, n, kinds in table:
            print("    %-10s %4d flop pin(s)  %s" % (label, n, "; ".join(kinds) or "-"))
    return bad


def main() -> int:
    print()
    print("=" * 78)
    print("  CDC5 -- no top-level input reaches core logic unsynchronized")
    print("=" * 78)
    rc = 0
    for env, want_clean, label in (
            ("PE_NETLIST_JSON", True, "clean design    must PASS"),
            ("PE_NETLIST_CDCRAW_JSON", False, "M_CDC_RAW       must FAIL")):
        p = os.environ.get(env)
        if not p or not os.path.isfile(p):
            print("  *** no netlist at %s -- RED rather than skipped" % env)
            rc = 1
            continue
        print("  --- %s (%s) ---" % (label, os.path.basename(p)))
        bad = check(p, verbose=want_clean)
        if want_clean:
            ok = not bad
            for b in bad[:12]:
                print("    *** %s" % b)
        else:
            prog = [b for b in bad if b.startswith("ui_in[7] ->")]
            ok = bool(prog)
            print("    %d violation(s); ui_in[7] -> core: %d  %s"
                  % (len(bad), len(prog), "red  ok (must-fire)" if ok
                     else "*** MUST-FIRE FAILED"))
            for b in prog[:2]:
                print("      | %s" % b)
        if not ok:
            rc = 1
    print()
    print("=" * 78)
    print("  GATE cdc: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    ⚠ PASSED means every input bit's combinational cone ends only at")
    print("    its declared synchronizer / capture / async-clear flops in the yosys")
    print("    graph. It is structural: it does not prove the host honours the")
    print("    hold and ordering rules in docs/HOST_INTERFACE.md.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
