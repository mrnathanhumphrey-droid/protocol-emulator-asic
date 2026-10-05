"""R2 FLOW CROSS-CHECK -- the hardening flow's own netlist as a SECOND authority
on the reset audit.

⛔ THIS DOES NOT REPLACE `gate_reset_audit`. That gate reads a netlist this repo
builds in seconds from `test/local_netlist.sh` and runs on every push. This one
reads the netlist the HARDENING FLOW produced, which costs a 3.5-hour run, and
so runs after a harden on the downloaded artefact. Two authorities, and the
cheap one keeps gating.

⭐ WHY A SECOND AUTHORITY IS WORTH ANYTHING HERE: the local netlist is generic
(`$_DFFE_*` cells, a reset shows as an `R`/`S` PORT). The flow's is PDK-mapped:
every flop is an `sg13cmos5l_dfrbpq_1` with a `RESET_B` PIN, and "no reset"
means that pin is tied to `tiehi`. Nothing about the local reading carries over
-- different cell library, different stage, different test -- so the two counts
agreeing is a real coincidence to demand, not the same measurement twice.

⛔⛔ WHAT THIS GATE MAY NOT DO: attribute the flop-count difference between the
two netlists to the yosys VERSION. It is confounded and the confound was
measured, not argued:

    local  `synth -top -flatten`            yosys 0.52 -> 3132 flops, 979 reset
    local  + `opt -full; opt_dff -sat`      yosys 0.52 -> 3131 flops, 978 reset
    flow   OpenLane AREA_0 + ABC + techmap  yosys 0.66 -> 3127 flops, 974 reset

Adding only the extra optimisation, at the SAME yosys, moves 1 of the 5. The
other 4 appear during ABC area mapping and PDK techmap -- stages the local
generic script never runs at all. So "0.66 removed five flops" is not a claim
this evidence supports; "a longer script removes five, at least one of which
0.52 also removes" is. ⚠ The reset-bearing count is the only one that moves.
THE UNRESET COUNT IS 2153 ON BOTH SIDES, and that is the number the allowlist
depends on.

⛔ AND WHY THE FIVE ARE NOT LISTED BY NAME: five instruments were spent trying
and the name axis does not survive the stage difference. Recorded so nobody
spends a sixth:
  1. bit -> name via `setdefault` picks an ARBITRARY alias of the many each bit
     carries, and the two releases order `netnames` differently. It invents
     swaps -- `l_order` 5->0 beside `l_sel` 0->5 -- and summed to -8, not -5.
  2. a plain name diff returns 102 local-only against 97 flow-only names,
     almost all `$abc$`/`$auto$` temporaries. Naming churn, not registers.
  3. the flow netlist is post-`splitnets`: a bus is per-bit netname KEYS.
  4. and a memory word is `tx_mem[0][0]` there against `tx_mem[0]` (8 bits)
     locally -- two trailing bracket groups against one, so stripping a single
     group leaves `tx_mem[0]` against `tx_mem` and every memory reads changed.
  5. with all of that fixed, declared-name totals still do not reconcile (1202
     local against 944 flow) because one bit belongs to several declared
     groups after flattening.
What the SYNTHESIS LOG says instead is dispositive about their NATURE, which is
what was actually asked. Every flop yosys drops it names a mechanism for, and
each one is a constant or a never-changing bit:
    Setting constant 0-bit at position 7 on $procdff$18731 ($adff)
    Setting constant 0-bit at position 7 on $procdff$18796 ($adff)
    Setting constant 0-bit at position 2 on $auto$ff.cc:266:slice$21273 ($adff)
    Setting constant 0-bit at position 7 on $auto$ff.cc:266:slice$21526 ($adffe)
    Removed top 8 bits (of 48) from FF cell ...slice$21958 ($adffe)
    Handling D = Q on ...$procdff$19138 ($adff) (removing D path)
    Handling D = Q on ...slice$21457 ($adffe) (removing D path)
A `D = Q` flop can never leave its reset value, so dropping it is exactly a
constant fold. ⭐ All of them are reset-BEARING; none is unreset. A redundant
reset-bearing flop removed is a flop that was already pinned to its reset
value, which cannot put a register into the unreset class.

HOW THE CHECK IS BUILT, and why each part is the part it is:

  * THE COUNT. Flops whose `RESET_B` is tied to `tiehi`, against the local
    audit's unreset count. Both read from their netlists -- neither is a
    number typed into this file, because a recorded expectation would pass
    while both sides drifted together.
  * THE PARTITION, not four numbers. Per-group counts are checked AND the
    groups are required to account for every tied bit (sum == total, no
    residue). Checking only the four named groups would let one extra tied
    flop land anywhere else and still pass -- which is precisely the mutant.
  * THE ALIAS, structurally. `fix = {pl, pslot}`, so `fix[0]` IS `pslot` by the
    concatenation identity. ⭐ MEASURED: `pslot` does NOT survive into the flow
    netlist as a name at all, so a check that looked for it would pass
    vacuously forever. Require instead exactly one tied bit under `u_eng.fix`,
    require it to be `fix[0]`, and require `fix[1..3]` driven.
"""
import collections
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TOP = "tt_um_protocol_emulator"
FLOP = "sg13cmos5l_dfrbpq_1"
TIE = "tiehi"

# ⛔ STRIP *ALL* TRAILING BRACKET GROUPS, not one. See note 4 in the docstring:
# the flow netlist is post-splitnets and a memory word reads `tx_mem[0][0]`
# while the local one reads `tx_mem[0]` with 8 bits.
BASE = re.compile(r"(\[\d+\])+$")

# The tied-reset groups, which must PARTITION the tied set exactly. The four
# Wilson named, plus the two the partition forces into the open: a check that
# listed only the named four would not notice a flop added elsewhere.
EXPECT_TIED = {
    "u_store.mem": 2048,   # the 256x8 store
    "tx_mem": 64,          # the 8x8 TX mirror
    "s_wrdata": 24,        # store write-data pipe
    "s_rdata": 8,          # store read-data
    "u_eng.paddr": 8,      # program address
    "u_eng.fix": 1,        # `fix[0]`, which IS `pslot`
}

ALIAS_GROUP = "u_eng.fix"
ALIAS_TIED_BIT = 0         # fix[0] == pslot
ALIAS_WIDTH = 4


def base_name(nn):
    return BASE.sub("", nn)


def read_top(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        d = json.load(fh)
    if TOP not in d.get("modules", {}):
        return None
    return d["modules"][TOP]


def tie_bits(mod):
    """Nets driven by a tie-high cell."""
    out = set()
    for cd in mod["cells"].values():
        if TIE in cd["type"]:
            for bits in cd["connections"].values():
                out.update(b for b in bits if isinstance(b, int))
    return out


def classify_flow(mod):
    """(tied, driven) Q-bit sets, by the RESET_B pin -- the mapped-netlist test."""
    tie = tie_bits(mod)
    tied, driven = set(), set()
    for cd in mod["cells"].values():
        if cd["type"] != FLOP:
            continue
        rb = cd["connections"].get("RESET_B", [])
        is_tied = any((isinstance(b, int) and b in tie) for b in rb)
        for b in cd["connections"].get("Q", []):
            if isinstance(b, int):
                (tied if is_tied else driven).add(b)
    return tied, driven


def groups_for(mod, bits):
    """Declared (non-`$`) register groups covering `bits`, base-name normalised."""
    g = collections.defaultdict(set)
    for nn, nd in mod["netnames"].items():
        if nn.startswith("$"):
            continue
        b0 = base_name(nn)
        for b in (nd.get("bits") or []):
            if isinstance(b, int) and b in bits:
                g[b0].add(b)
    return g


def local_unreset(mod):
    """The local audit's own test: a generic flop with no `R`/`S` PORT."""
    n = 0
    for cd in mod["cells"].values():
        if "DFF" not in cd["type"].upper():
            continue
        c = cd.get("connections", {})
        if not (("R" in c) or ("S" in c)):
            n += len([b for b in c.get("Q", []) if isinstance(b, int)])
    return n


def check(mod, expect_unreset):
    """The cross-check. Returns a list of failure strings; empty means passed."""
    bad = []
    tied, driven = classify_flow(mod)
    nflop = sum(1 for cd in mod["cells"].values() if cd["type"] == FLOP)

    # ⛔ ANTI-VACUITY FIRST. A netlist with no mapped flops would satisfy every
    # per-group count below by having nothing to count.
    if not tied:
        bad.append("no tied-reset flop found at all -- the check found nothing "
                   "to check, so it has not run")
        return bad, tied, driven, nflop

    # 1. THE COUNT, against the local audit rather than a stored number.
    if expect_unreset is not None and len(tied) != expect_unreset:
        bad.append("tied-reset count %d != local audit's unreset count %d"
                   % (len(tied), expect_unreset))

    # 2. THE PARTITION: declared groups, exact counts, and no residue.
    g = groups_for(mod, tied)
    for name, want in sorted(EXPECT_TIED.items()):
        got = len(g.get(name, ()))
        if got != want:
            bad.append("group `%s` has %d tied bit(s), expected %d"
                       % (name, got, want))
    extra = sorted(set(g) - set(EXPECT_TIED))
    if extra:
        bad.append("undeclared tied group(s): %s"
                   % ", ".join("%s(%d)" % (k, len(g[k])) for k in extra))
    covered = set()
    for v in g.values():
        covered |= v
    if covered != tied:
        bad.append("%d tied bit(s) sit on no declared register name, so the "
                   "groups do not account for the tied set"
                   % len(tied - covered))

    # 3. THE ALIAS, by the concatenation identity. `pslot` is gone as a name.
    fix = {}
    for nn, nd in mod["netnames"].items():
        if base_name(nn) != ALIAS_GROUP:
            continue
        mm = re.search(r"\[(\d+)\]$", nn)
        bits = [b for b in (nd.get("bits") or []) if isinstance(b, int)]
        if mm and len(bits) == 1:
            fix[int(mm.group(1))] = bits[0]
        else:
            for i, b in enumerate(bits):
                fix[i] = b
    if not fix:
        bad.append("`%s` is absent from the netlist, so the alias check would "
                   "pass vacuously" % ALIAS_GROUP)
    else:
        t = sorted(i for i, b in fix.items() if b in tied)
        if t != [ALIAS_TIED_BIT]:
            bad.append("`%s` has tied bit(s) %s, expected exactly [%d]"
                       % (ALIAS_GROUP, t, ALIAS_TIED_BIT))
        for i in range(ALIAS_WIDTH):
            if i == ALIAS_TIED_BIT:
                continue
            if i not in fix:
                bad.append("`%s[%d]` absent" % (ALIAS_GROUP, i))
            elif fix[i] not in driven:
                bad.append("`%s[%d]` is not a driven-reset flop" % (ALIAS_GROUP, i))
    return bad, tied, driven, nflop


# --------------------------------------------------------------------------
# MUST-FIRE. ⛔ A synthetic flow-STYLE netlist, mutated one way at a time, and
# each mutant must fail FOR ITS OWN STATED REASON -- a mutant that dies because
# some other assertion tripped certifies nothing.
# --------------------------------------------------------------------------
def synth_netlist():
    """A miniature flow-style netlist that PASSES, to mutate from."""
    nets = {}
    nxt = [2]
    def alloc(n):
        out = list(range(nxt[0], nxt[0] + n))
        nxt[0] += n
        return out
    cells, netnames = {}, {}
    cells["tie"] = {"type": "sg13cmos5l_tiehi_1", "connections": {"Y": [1]}}

    def add_group(name, n, tied, two_d=False, width=8):
        bits = alloc(n)
        for i, b in enumerate(bits):
            cells["ff_%s_%d" % (name, i)] = {
                "type": FLOP,
                "connections": {"Q": [b], "RESET_B": [1 if tied else 0]},
            }
            if two_d:
                netnames["%s[%d][%d]" % (name, i // width, i % width)] = {"bits": [b]}
            else:
                netnames["%s[%d]" % (name, i)] = {"bits": [b]}
        return bits

    for name, n in EXPECT_TIED.items():
        if name == ALIAS_GROUP:
            continue
        add_group(name, n, True, two_d=(name in ("u_store.mem", "tx_mem")))
    # fix[0] tied, fix[1..3] driven
    fb = alloc(ALIAS_WIDTH)
    for i, b in enumerate(fb):
        cells["ff_fix_%d" % i] = {
            "type": FLOP,
            "connections": {"Q": [b], "RESET_B": [1 if i == 0 else 0]},
        }
        netnames["%s[%d]" % (ALIAS_GROUP, i)] = {"bits": [b]}
    return {"cells": cells, "netnames": netnames}


def selftest():
    import copy
    rc = 0
    base = synth_netlist()
    n_tied = sum(EXPECT_TIED.values())

    def extra_tied_new_group(m):
        m["cells"]["ff_extra"] = {"type": FLOP,
                                  "connections": {"Q": [9001], "RESET_B": [1]}}
        m["netnames"]["u_eng.sneaky"] = {"bits": [9001]}

    def extra_tied_existing(m):
        m["cells"]["ff_extra"] = {"type": FLOP,
                                  "connections": {"Q": [9002], "RESET_B": [1]}}
        m["netnames"]["tx_mem[8][0]"] = {"bits": [9002]}

    def extra_tied_unnamed(m):
        m["cells"]["ff_extra"] = {"type": FLOP,
                                  "connections": {"Q": [9003], "RESET_B": [1]}}
        m["netnames"]["$auto$nameless"] = {"bits": [9003]}

    def fix1_also_tied(m):
        m["cells"]["ff_fix_1"]["connections"]["RESET_B"] = [1]

    def fix_tied_bit_moved(m):
        m["cells"]["ff_fix_0"]["connections"]["RESET_B"] = [0]
        m["cells"]["ff_fix_1"]["connections"]["RESET_B"] = [1]

    def fix_gone(m):
        for i in range(ALIAS_WIDTH):
            m["netnames"].pop("%s[%d]" % (ALIAS_GROUP, i), None)

    def no_flops(m):
        for k in [k for k in m["cells"] if m["cells"][k]["type"] == FLOP]:
            del m["cells"][k]

    # (label, mutate, expected-unreset, substring the failure must contain)
    cases = [
        ("baseline, unmutated", None, n_tied, None),
        ("one extra tied flop, new group",
         extra_tied_new_group, n_tied, "undeclared tied group"),
        ("one extra tied flop, inside tx_mem",
         extra_tied_existing, n_tied, "group `tx_mem` has 65"),
        ("one extra tied flop on no declared name",
         extra_tied_unnamed, n_tied, "sit on no declared register name"),
        ("local unreset count disagrees",
         None, n_tied + 1, "!= local audit's unreset count"),
        ("fix[1] tied as well",
         fix1_also_tied, n_tied, "expected exactly [0]"),
        ("the tied fix bit is fix[1], not fix[0]",
         fix_tied_bit_moved, n_tied, "expected exactly [0]"),
        ("`u_eng.fix` absent entirely",
         fix_gone, n_tied, "pass vacuously"),
        ("no mapped flops at all",
         no_flops, n_tied, "found nothing to check"),
    ]
    print("  MUST-FIRE, on a synthetic flow-style netlist:")
    for label, mut, exp, want in cases:
        m = copy.deepcopy(base)
        if mut:
            mut(m)
        bad, _t, _d, _n = check(m, exp)
        if want is None:
            ok = not bad
            detail = "" if ok else "  <- %s" % (bad[0] if bad else "")
        else:
            # ⛔ BY ITS STATED REASON, not merely red.
            ok = any(want in b for b in bad)
            detail = "" if ok else "  <- got %s" % (bad or "a PASS")
        print("    %-46s %s%s" % (label, "ok" if ok else "*** FAILED", detail))
        if not ok:
            rc = 1
    return rc


def provenance(path):
    """⭐ WHICH HARDEN THIS NETLIST CAME FROM. A cross-check against an
    unlabelled artefact cannot be reproduced, and a stale download would read
    exactly like a fresh pass.

    ⛔ THE VERSION IS TAKEN FROM THE NETLIST'S OWN `creator` FIELD, not from the
    log beside it. A netlist copied into a directory holding somebody else's
    log would otherwise be labelled with that log's version -- the provenance
    has to travel inside the artefact being checked.
    """
    out = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        head = fh.read(4096)
    m = re.search(r'"creator"\s*:\s*"([^"]+)"', head)
    if m:
        out.append("flow yosys: %s   (from the netlist's own creator field)"
                   % m.group(1))
    else:
        # The log is a fallback only, and says so. Its version line is indented.
        d = os.path.dirname(os.path.abspath(path))
        log = os.path.join(d, "yosys-synthesis.log")
        if os.path.isfile(log):
            with open(log, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if line.strip().startswith("Yosys 0."):
                        out.append("flow yosys: %s   (⚠ from the adjacent log, "
                                   "NOT the netlist)" % line.strip())
                        break
    out.append("netlist:    %s (%d bytes)" % (path, os.path.getsize(path)))
    return out


def main():
    flow = os.environ.get("PE_FLOW_NETLIST")
    if not flow:
        print("  *** PE_FLOW_NETLIST is not set.")
        print("  Point it at the harden's post-synthesis netlist JSON:")
        print("    $env:PE_FLOW_NETLIST = "
              "'<run>\\logs\\runs\\wokwi\\06-yosys-synthesis\\"
              "%s.nl.v.json'" % TOP)
        print("  ⛔ RED rather than skipped: this gate's whole content is the")
        print("     comparison, and a skipped comparison is not a weaker pass.")
        print()
        return 1 if selftest() is not None else 1
    if not os.path.isfile(flow):
        print("  *** flow netlist not found: %s" % flow)
        return 1

    mod = read_top(flow)
    if mod is None:
        print("  *** %s absent from %s" % (TOP, flow))
        return 1

    # The local side, by the local audit's own test. ⛔ Not a number stored
    # here: a stored expectation passes while both sides drift together.
    lp = os.environ.get("PE_NETLIST_JSON")
    expect = None
    if lp and os.path.isfile(lp):
        lmod = read_top(lp)
        if lmod is not None:
            expect = local_unreset(lmod)
    if expect is None:
        print("  *** the local netlist (PE_NETLIST_JSON) is not readable, so")
        print("      there is nothing to cross-check AGAINST. Build it with")
        print("      test/local_netlist.sh first.")
        return 1

    for line in provenance(flow):
        print("  %s" % line)
    print("  local:      %s (unreset %d)" % (lp, expect))
    print()

    bad, tied, driven, nflop = check(mod, expect)
    print("  flow netlist: %d mapped flops, %d tied (unreset), %d driven"
          % (nflop, len(tied), len(driven)))
    g = groups_for(mod, tied)
    for name in sorted(EXPECT_TIED):
        print("    %-16s %5d tied   (expected %d)"
              % (name, len(g.get(name, ())), EXPECT_TIED[name]))
    print()
    for b in bad:
        print("  *** %s" % b)
    rc = 1 if bad else 0

    print()
    rc_self = selftest()
    print()
    print("=" * 78)
    print("  GATE flow-netlist: %s" % ("PASSED" if (rc or rc_self) == 0
                                       else "FAILED"))
    print("    * the flow's PDK-mapped netlist agrees with the local generic")
    print("      one on %d unreset flops, by two unrelated tests: an absent"
          % expect)
    print("      `R`/`S` port locally, a `RESET_B` pin tied to `tiehi` there")
    print("    * ⛔ a SECOND authority, not a replacement: `gate_reset_audit`")
    print("      still gates every push on the netlist built in seconds")
    print("    * ⛔ the 979-vs-974 reset-bearing difference is NOT a version")
    print("      effect -- it is confounded with the script, and measuring at")
    print("      one yosys moves 1 of the 5. See this file's header.")
    return 1 if (rc or rc_self) else 0


if __name__ == "__main__":
    sys.exit(main())
