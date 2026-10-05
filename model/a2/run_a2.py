"""THE A2 SUITE -- print the list, run the list, and cross-check the digests.

⛔⛔ PRINT THE LIST AND RUN THE LIST. The standing failure this guards against is
running 3 of 26 suites and reporting "full gate green" -- which has happened
twice on this project. The gates are enumerated here, every one is executed, and
the summary says "N of M" or it says nothing.

⭐⭐ AND THE META-CHECK IS THE REASON THIS FILE EXISTS RATHER THAN A SHELL LOOP
(spec A1). Each gate prints `LANE-DIGEST base=... used=...`. This runner collects
them and FAILS THE RUN if any two gates disagree about `base` -- i.e. if two
gates in the same run analysed different shipped lane tables. Two stale copies
of that table turned up in a single batch, so the question "did everything here
see the same five lanes?" is not rhetorical and is not answerable by reading.

THE THREE WAYS THIS RUN FAILS:
  1. a gate exits non-zero                      -- the ordinary way
  2. two gates report different `base` digests   -- a copy exists somewhere
  3. a gate that consumes the lane table prints NO digest line -- it opted out
     of the check, which is the one thing a gate must not be able to do

⛔ (3) IS THE ONE THAT MATTERS AND IT IS WHY `EXPECT_DIGEST` IS AN EXPLICIT LIST.
If the runner simply collected whatever digests appeared, a gate that stopped
printing one would silently leave the cross-check -- and the run would go green
with fewer participants than it started with. The expectation is declared here,
per gate, so dropping out is a failure rather than an absence.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# (file, label, consumes the shipped lane table?)
GATES = [
    ("lane_digest.py", "A1   lane-table digest, both faces + per-field must-fire", False),
    ("pyrta_src.py", "H1   pyRTA discovery, both faces", False),
    ("jitter_dmax.py", "A    D_i closed form, adversarial search", False),
    ("a2_close.py", "A2   feasibility + the loose bound (historical baseline)", False),
    ("rta_spuri.py", "O9   deadline-limited interference, `+1` settled", False),
    ("bursty.py", "P4   the reactive direction + R1/R2/H3 lane table", True),
    ("gate_i2c_phase.py", "N1   the I2C SCL phase split, from UM10204 T11", True),
    ("gate_i2c_sda_read.py", "R3   SDA read on the observed SCL rise", True),
    ("gate_lane_class.py", "0.9b SOURCE vs REACTIVE + H3/R1 assertions", True),
    ("frontier.py", "1.2  the (C, J) frontier", True),
    ("gate_microarch_1_3.py", "1.3  microarchitecture sketch vs the frontier", True),
    ("grid_quantization.py", "C3   clock-grid quantization (Ethernet)", False),
    ("gate_twin_pair.py", "P3   twin-pair self-exclusion, both directions", False),
    ("gate_rearm.py", "R2   chained waits: the re-arm task in A2", True),
    ("gate_encoding_f1.py", "F1   program vs payload; store sized after", True),
    ("gate_descriptor_1_5.py", "1.5  descriptor freeze, encoding derived", True),
    ("gate_pin_subsets.py", "PIN  12 pins vs 8 uio; envelope checked on every subset", True),
    ("gate_program_census.py", "S1   program-size census -> AW, from enumerated actions", True),
    ("gate_spec_freeze_s2.py", "S2   spec freeze: every field traces to a ruling", True),
    ("gate_load_pin_safety.py", "PIN  load-mode readback must not drive peripherals", True),
    ("gate_miso_tristate.py", "PIN  target MISO must release; uo_out cannot", True),
    ("gate_admissibility_1_6.py", "1.6  admissibility conditions, each priced", True),
    ("gate_pyrta.py", "1.4b third-party check of the shipped r_i", True),
    # ---- the jitter-sound pipeline (Wilson's ruling, steps 1-4) ----------
    # ⛔ `zone/run_jitter.py` is NOT here, for the same reason run_edf.py and
    # run_bursty.py are not: it shells into WSL for TChecker and takes minutes.
    # Its verdicts are RECORDED in jitter_instances.py, and that file's selftest
    # plus run_jitter's own stale-record check are what keep the record honest.
    ("jitter_instances.py", "J0   one jitter instance list + recorded verdicts", False),
    ("gate_edge_capture.py",
     "EC   L_sync derived from the sync chain; <= A2's 3, jitter <= 1", False),
    ("gate_noop_job.py",
     "NOP  the half-bit no-op as a real job; A2 + pyRTA re-quoted", True),
    ("gate_j_program.py", "J1b  J(d_min) derived; shipped J=1, universal J=8", False),
    # ⛔ `../` because this one lives in model/ with the other RTL-FACING gates
    # (part1_param_contract, f2_flop_driven_outputs), not in model/a2/ with the
    # analysis. It is in THIS list anyway: an out-of-suite gate is a gate nobody
    # runs, and `golden.py` carries prediction A3 and falsifier F1.
    ("../gate_reverse_trace.py",
     "RT   reverse traceability: the census on the golden model", False),
    ("gate_j_sound.py", "J4   the J sweep; the bar verdict is bound-dependent", True),
    # ⛔ THE C CORRECTION. `docs/PREREG_C_SAT.md` pre-registered the minimum
    # inter-dispatch spacing at 2 and it MEASURED 3, so every published r_i and
    # margin was optimistic. This gate is the re-quote, and it is in the suite
    # because a correction that runs only when someone remembers it has the
    # same standing as the number it replaced.
    ("gate_c3_requote.py", "C3   C = 3 re-quote: r_i and margins corrected", True),
    ("gate_pyrta_jitter.py", "J3   pyRTA witness at J>0; the naive arm is a trap", True),
]
EXPECT_DIGEST = {f for f, _l, needs in GATES if needs}

# ⛔⛔ PRICING THE META-CHECK. `--price` appends a probe that reproduces the
# defect A1 screens for -- a gate analysing a stale hand-typed copy of the lane
# table -- and the run is then REQUIRED to fail. A meta-check that has never
# been seen red is an unmeasured artefact, and this one guards against a class
# that has already occurred twice, so it does not get to be untested.
#
# ⭐ The probe exits 0 deliberately. If it failed on its exit status the harness
# would be crediting the digest check for something the ordinary "N of M" count
# already catches; the run has to go red on the DIGEST MISMATCH specifically.
PRICE_PROBE = ("_price_stale_lane_table.py",
               "PRICE a gate analysing a STALE copy -- the run MUST fail", True)

DIGEST_RE = re.compile(r"LANE-DIGEST base=(\w+) used=(\w+)\s+(\w+)")


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    pricing = "--price" in argv
    gates = list(GATES) + ([PRICE_PROBE] if pricing else [])
    expect = set(EXPECT_DIGEST) | ({PRICE_PROBE[0]} if pricing else set())
    print()
    print("=" * 78)
    print("A2 SUITE -- %d entries%s"
          % (len(gates), "   *** PRICING RUN: a RED result is the PASS ***"
             if pricing else ""))
    print("=" * 78)
    for i, (f, label, needs) in enumerate(gates, 1):
        print("  %2d. [%s] %-24s %s"
              % (i, "digest" if needs else "      ", f, label))
    print()

    results, digests = [], {}
    for f, label, needs in gates:
        t0 = time.time()
        r = subprocess.run([sys.executable, "-u", os.path.join(HERE, f)],
                           capture_output=True, text=True, cwd=ROOT,
                           encoding="utf-8", errors="replace")
        dt = time.time() - t0
        out = (r.stdout or "") + (r.returncode and (r.stderr or "") or "")
        m = DIGEST_RE.search(out)
        if m:
            digests[f] = (m.group(1), m.group(2), m.group(3))
        results.append((f, label, needs, r.returncode, dt, out))
        print("  [%s] %-24s %5.1fs  %s"
              % ("PASS" if r.returncode == 0 else "FAIL", f, dt,
                 ("base=%s used=%s %s" % digests[f]) if f in digests
                 else ("-- no digest" if needs else "")))

    rc = 0
    passed = [x for x in results if x[3] == 0]
    print()
    print("  GATES: %d of %d passed" % (len(passed), len(results)))
    if len(passed) != len(results):
        rc = 1

    # ---- meta-check (2): one shipped lane table across the whole run -----
    print()
    print("  --- META-CHECK: did every gate see the SAME shipped lane table? ---")
    bases = {f: d[0] for f, d in digests.items()}
    distinct = sorted(set(bases.values()))
    if not bases:
        print("    *** no gate reported a digest at all -- the check did not run")
        rc = 1
    elif len(distinct) == 1:
        print("    base digest %s, reported by %d of %d gates that consume the"
              % (distinct[0], len(bases), len(expect)))
        print("    table => ONE shipped lane table across the run")
    else:
        print("    *** FAIL: %d DIFFERENT shipped tables in one run ***"
              % len(distinct))
        for d in distinct:
            print("      %s : %s" % (d, ", ".join(sorted(f for f, b in bases.items()
                                                         if b == d))))
        print("      A copy of the lane table exists. Find it before reading any")
        print("      number above -- the gates are not describing one design.")
        rc = 1

    # ---- meta-check (2b): no UNDECLARED variant -------------------------
    # ⛔⛔ THIS IS THE ARM THAT CATCHES THE DEFECT WE ACTUALLY HAD, and I did not
    # have it until the pricing probe exposed the gap. A hand-typed copy moves
    # `used` and leaves `base` ALONE -- the gate still imports the real module,
    # it just hands the analyser something else. So base-agreement across gates,
    # which is the obvious form of this check, would have passed on both of the
    # stale copies that prompted A1. The mismatch has to be read against whether
    # the gate DECLARED it.
    print()
    print("  --- META-CHECK: any UNDECLARED lane-table variant? ---")
    undecl = sorted(f for f, _l, _n, _c, _d, out in results
                    if "UNDECLARED" in out)
    if undecl:
        print("    *** FAIL: these analysed a lane set that is NOT the shipped")
        print("        table, without declaring why:")
        for f in undecl:
            print("      %s" % f)
        print("      That is the signature of a hand-typed copy: `base` matches")
        print("      because the module is still imported, `used` does not")
        print("      because the analyser was handed something else.")
        rc = 1
    else:
        print("    none -- every used != base carries a declared reason")

    # ---- meta-check (3): nobody opted out --------------------------------
    missing = sorted(expect - set(digests))
    print()
    print("  --- META-CHECK: did any gate opt OUT of the digest? ---")
    if missing:
        print("    *** FAIL: these consume the lane table and printed no digest:")
        for f in missing:
            print("      %s" % f)
        print("      A gate that stops printing its digest leaves the")
        print("      cross-check silently, and the run goes green with fewer")
        print("      participants than it declared. That is the failure this")
        print("      explicit list exists to make impossible.")
        rc = 1
    else:
        print("    all %d gates that consume the table reported one"
              % len(expect))

    # ---- declared variants, listed rather than hidden --------------------
    var = {f: d for f, d in digests.items() if d[2] == "VARIANT"}
    if var:
        print()
        print("  declared VARIANTS (used != base, by design):")
        for f, d in sorted(var.items()):
            print("    %-24s used=%s" % (f, d[1]))
        print("    each declares its reason in its own output; an UNDECLARED")
        print("    variant prints '*** UNDECLARED VARIANT ***' and is a finding.")

    for f, label, needs, code, dt, out in results:
        if code != 0:
            print()
            print("  --- FAILED: %s  %s" % (f, label))
            print("\n".join("      " + l for l in out.splitlines()[-25:]))

    print()
    if pricing:
        # ⛔ THE VERDICT IS INVERTED HERE AND ONLY HERE. The probe reproduces the
        # defect, so the suite going RED is the pass; the suite going GREEN means
        # the meta-check cannot see a stale copy and is not evidence of anything.
        print("  A2 SUITE (PRICING RUN): %s"
              % ("PASSED -- the stale-copy probe took the run down, so the "
                 "digest meta-check depends on what it claims to check"
                 if rc != 0 else
                 "*** FAILED -- the suite went GREEN with a gate analysing a "
                 "STALE lane table. The meta-check does not detect the defect "
                 "it exists for. ***"))
        return 0 if rc != 0 else 1
    print("  A2 SUITE: %s"
          % ("%d of %d gates green, one lane table, no gate opted out"
             % (len(passed), len(results)) if rc == 0
             else "*** NOT GREEN -- see above ***"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
