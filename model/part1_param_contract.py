"""PART 1 RTL -- THE PARAMETER CONTRACT, checkable from the first line of RTL.

THE ONE CLAIM: every quantity a scaling sweep would vary is a PARAMETER, and no
protocol-specific constant appears anywhere in the engine. So scaling costs a
run, not a refactor.

⛔⛔ THIS GATE IS RED UNTIL THE ENGINE EXISTS, ON PURPOSE. `src/project.v` is the
load path; the engine is not built. A contract checker that passed on the
current source would be the exact failure this project has already recorded --
a CI job green because the artefact is too simple to reach the checked path
(gate-level sim passed for weeks on a stub with zero flip-flops). So the engine
module is REQUIRED to exist, and its absence is a failure with a named reason,
not a skip.

⭐⭐ AND THE PARAMETRIC REQUIREMENT IS NOT TIDINESS -- IT IS THE PRECONDITION FOR
ONE OF THE SCALING CLAIMS TO BE POSSIBLE AT ALL. The scaling plan wants the same
RTL pushed through Nangate45 and ASAP7 to get measured post-route Fmax at thinner
nodes. ⛔ But the memory ruling chose an IHP SRAM macro, and
`RM_IHPSG13_1P_*` DOES NOT EXIST IN EITHER OF THOSE PDKs. So if the store is
written as a hard SRAM instantiation, the predictive-node runs cannot be built --
not "would be awkward", cannot. `MEM_TYPE` is what keeps both paths alive:

    MEM_TYPE = "sram"   the IHP macro, for the real shuttle
    MEM_TYPE = "flops"  a behavioural register array, for ANY PDK

and the flop path therefore is NOT deleted when SRAM wins. It becomes the
portable fallback that the 45 nm and 7 nm numbers are measured on. ⚠ With the
obvious caveat attached: a flop-store harden at those nodes measures the ENGINE's
Fmax, not the SRAM-based design's, and the two must not be quoted as the same
configuration.

⭐ The second portability requirement is cheaper and already nearly met: the RTL
must instantiate NO PDK CELLS. Today's `src/project.v` is generic Verilog, so
this is a property to KEEP rather than to gain -- which is exactly when a check
is worth writing, because nothing will notice it being lost.
"""

from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# The engine module Part 1 must introduce. Its ABSENCE is the current failure.
ENGINE_HINTS = ("edf", "winner", "descriptor", "lane", "shift", "timestamp")

# (parameter, what it varies, why a sweep needs it)
REQUIRED_PARAMS = [
    ("N_LANES", "how many lanes the engine schedules",
     "the lane-count sweep, and the pin-budget condition 1.6o"),
    ("AW", "program store depth, 2**AW words",
     "the store-depth sweep; already a parameter in src/project.v"),
    ("N_PINS", "width of the protocol pin group",
     "Jane Street is considering 8x4 tiles -- more tiles may mean more pins"),
    ("TS_W", "timestamp / global counter width",
     "1.5 derived a FLOOR of 9 bits and ships 16; the sweep is what shows the "
     "7 bits are really spare"),
    ("DLY_W", "program delay field width",
     "F1's fit needed 10 bits; a different store size moves the trade"),
    ("D_W", "D_sched field width",
     "scales with the deadline spread, which scales with the lane set"),
    ("MEM_TYPE", "\"sram\" | \"flops\"",
     "⭐ THE PORTABILITY PARAMETER -- without it the Nangate45/ASAP7 runs "
     "cannot be built at all, AND it is the fallback if the CMOS5L macro "
     "harden fails"),
    ("RX_SERIAL", "0 = parallel RX view, 1 = 3-pin bit-serial",
     "the ruled pin map needs serial; the sweep needs to be able to turn it "
     "off to measure what it costs"),
]

# ⛔ Protocol-specific constants that must appear NOWHERE in the engine. These
# are the numbers that make a design a waveform player instead of an emulator;
# they belong in the loaded program. ORIGIN: the shipped lane table.
FORBIDDEN_LITERALS = {
    434: "UART 115200 bit period",
    414: "UART-rx admitted band floor",
    4140: "UART-rx outer period",
    216: "D_tol UART-tx",
    213: "D_tol UART-rx",
    23: "D_tol SPI-tx",
    18: "D_tol SPI-target",
    15: "D_tol I2C",
    80: "I2C N_low",
    45: "I2C N_high / event period",
    125: "I2C bit period",
}

# PDK cell prefixes that must not appear in RTL (they would pin it to one PDK)
PDK_CELL_RE = re.compile(
    r"\b(sg13[a-z0-9]*_|sky130_|RM_IHPSG13_|DFF_X|INV_X|NAND\d_X|ASAP7)",
    re.I)


def verilog_files():
    if not os.path.isdir(SRC):
        return []
    return [os.path.join(SRC, f) for f in sorted(os.listdir(SRC))
            if f.endswith((".v", ".sv"))]


def strip_comments(t: str) -> str:
    t = re.sub(r"//[^\n]*", "", t)
    return re.sub(r"/\*.*?\*/", "", t, flags=re.S)


def main() -> int:
    print()
    print("=" * 78)
    print("PART 1 -- the RTL parameter contract")
    print("=" * 78)
    rc = 0
    files = verilog_files()
    print("  RTL files: %s" % (", ".join(os.path.basename(f) for f in files)
                               or "NONE"))
    if not files:
        print("  *** no RTL at all -- nothing to check")
        return 1
    bodies = {}
    for f in files:
        with open(f, encoding="utf-8", errors="replace") as fh:
            bodies[f] = strip_comments(fh.read())
    allsrc = "\n".join(bodies.values())

    # ---- does the engine exist yet? -------------------------------------
    print()
    print("  --- precondition: does the ENGINE exist? ---")
    hits = sorted({h for h in ENGINE_HINTS
                   if re.search(r"\b\w*%s\w*\b" % h, allsrc, re.I)})
    tied = re.search(r"assign\s+uio_out\s*=\s*8'h0*0\s*;", allsrc)
    print("    engine-shaped identifiers found: %s" % (", ".join(hits) or "none"))
    print("    uio_out tied to a constant       : %s"
          % ("YES -- no pin can drive a 1" if tied else "no"))
    if len(hits) < 3 or tied:
        print("    *** GATE IS RED, AND THIS IS THE CORRECT STATE TODAY.")
        print("        src/project.v is the LOAD PATH; the engine is rung 4 and")
        print("        is not built. A contract check that went green here would")
        print("        be a pass on an artefact too simple to reach the checked")
        print("        path -- the same failure as a gate-level sim passing on a")
        print("        stub with zero flip-flops.")
        print("        This gate turns green when Part 1 lands, which makes it")
        print("        an ACCEPTANCE TEST for the parameter contract rather than")
        print("        a lint that already passes.")
        rc = 1

    # ---- the parameters -------------------------------------------------
    print()
    print("  --- required parameters ---")
    print("    %-10s %-7s %-34s %s" % ("param", "present", "varies", "needed by"))
    for name, varies, why in REQUIRED_PARAMS:
        present = bool(re.search(r"\bparameter\b[^;]*\b%s\b" % re.escape(name),
                                 allsrc))
        print("    %-10s %-7s %-34s %s"
              % (name, "yes" if present else "NO", varies, why[:38]))
        if not present:
            rc = 1
    print("    ⛔ a literal where a parameter belongs costs a REFACTOR per")
    print("       scaling point; a parameter costs a RUN. That is the whole")
    print("       reason this is a Part-1 line and not a later clean-up.")

    # ---- protocol constants must not appear -----------------------------
    print()
    print("  --- genericity: no protocol constant anywhere in the RTL ---")
    found = []
    for lit, what in sorted(FORBIDDEN_LITERALS.items()):
        # a bare decimal, or a sized literal with that value
        pat = r"(?<![\w'])%d(?![\w'])" % lit
        for f, body in bodies.items():
            if re.search(pat, body):
                found.append((lit, what, os.path.basename(f)))
    if found:
        print("    *** FOUND protocol constants in the RTL:")
        for lit, what, f in found:
            print("      %-6d %-32s in %s" % (lit, what, f))
        print("      These belong in the LOADED PROGRAM. A protocol constant in")
        print("      the engine is the waveform-player failure in source form.")
        rc = 1
    else:
        print("    none of the %d protocol constants appears in any RTL file"
              % len(FORBIDDEN_LITERALS))
        print("    ⚠ AND THIS IS WEAK EVIDENCE TODAY, SAID PLAINLY: the engine")
        print("    does not exist, so there is almost nothing for the scan to")
        print("    find. A zero-hit search proves the string absent, not the")
        print("    property held. It becomes real evidence only once the gate's")
        print("    precondition above passes.")

    # ---- PDK portability -------------------------------------------------
    print()
    print("  --- portability: no PDK cells instantiated in RTL ---")
    pdk = []
    for f, body in bodies.items():
        for m in PDK_CELL_RE.finditer(body):
            pdk.append((m.group(0), os.path.basename(f)))
    if pdk:
        print("    *** PDK-specific names in RTL: %s"
              % ", ".join("%s (%s)" % p for p in pdk[:6]))
        print("      This pins the RTL to one PDK and makes the Nangate45 /")
        print("      ASAP7 runs impossible rather than merely awkward.")
        rc = 1
    else:
        print("    clean -- the RTL is generic Verilog, so the same source can")
        print("    be hardened at 130 nm, 45 nm and 7 nm.")
        print("    ⭐ This is a property to KEEP, not to gain. That is exactly")
        print("    when a check earns its place: nothing would notice it being")
        print("    lost, and the first PDK cell instantiated would silently end")
        print("    the predictive-node evidence.")

    # ---- the coupling the scaling plan has to know about ----------------
    print()
    print("  --- ⭐ the coupling between the SRAM ruling and the 7 nm claim ---")
    print("    The memory ruling chose RM_IHPSG13_1P_*, which does NOT EXIST in")
    print("    Nangate45 or ASAP7. If the store is a hard macro instantiation,")
    print("    the predictive-node runs CANNOT BE BUILT.")
    print("    So MEM_TYPE keeps both paths alive:")
    print("      \"sram\"  -> the IHP macro, for the real shuttle")
    print("      \"flops\" -> a behavioural array, hardenable at ANY node")
    print("    ⛔ Which means the flop store is NOT deleted when SRAM wins. It")
    print("       becomes the portable fallback the 45/7 nm numbers are")
    print("       measured on.")
    print("    ⚠ AND THE TWO MUST NOT BE QUOTED AS ONE CONFIGURATION: a flop")
    print("       store at 7 nm measures the ENGINE's Fmax, not the shipped")
    print("       SRAM design's. The ledger entry has to say which.")

    print()
    print("=" * 78)
    print("  GATE part1-params: %s"
          % ("PASSED" if rc == 0 else
             "RED -- expected until Part 1 lands; see the precondition"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
