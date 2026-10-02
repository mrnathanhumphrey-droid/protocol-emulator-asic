"""RUNG 4 Part 0 -- does the proved bound CONSTRAIN the hardware's tie-break,
or COVER every tie-break?

Rung 4's Part 0 and falsifier R4-F2 both assume the first: "if the hardware
breaks deadline ties the other way, the foreign-validated bound is about a
different machine." If that is right it is a serious constraint on the RTL
scheduler -- it would have to reproduce a specific tie-break rule exactly, and
getting it wrong would silently void A2.

⭐ THE ARGUMENT THAT IT IS NOT RIGHT. The A2 model's EDF guard uses `<=` against
every rival, so on an equal deadline EVERY candidate transition is enabled and
the checker explores all orderings. The reported r_i is therefore the MAXIMUM
over all tie-breaks. Any deterministic rule the hardware might use is a SUBSET of
those runs, so its worst case cannot exceed the reported bound. The recurrence
agrees by construction: its eligibility test is non-strict (`D_j <= a + D_i`), so
an equal-deadline rival is counted as interference -- the pessimistic choice.

That is a soundness argument, not evidence. This measures it: the same instances
re-checked under a deterministic lowest-index-wins tie-break, which must come out
<= the nondeterministic answer on every lane.

⛔ WHAT A VIOLATION WOULD MEAN. `det > nondet` on any lane would mean the
nondeterministic model does NOT subsume the deterministic one -- i.e. the `<=`
guard fails to enable some ordering the deterministic rule can produce. That
would be a bug in the model, and it would retroactively put every Part 3 and
Part 4 number in doubt, because all of them came from the `<=` version.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))

from run_edf import INSTANCES, foreign_r                      # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def main() -> int:
    print()
    print("=" * 78)
    print("RUNG 4 PART 0 -- is the bound tie-break-SPECIFIC or tie-break-FREE?")
    print("=" * 78)
    rows = []
    for inst_label, lanes in INSTANCES:
        print()
        print("  %s" % inst_label)
        print("    %-8s %-14s %-14s %-8s %s"
              % ("lane", "nondet (all)", "index (det)", "det<=all", "note"))
        for k, l in enumerate(lanes):
            tag = "tb_%s_%d" % (inst_label.split()[0].lower(), k)
            nd = foreign_r(lanes, k, tag + "_n", tie_mode="nondet")
            dt = foreign_r(lanes, k, tag + "_d", tie_mode="index")
            a, b = nd.get("r"), dt.get("r")
            ok = (a is not None and b is not None and b <= a)
            rows.append({"inst": inst_label, "lane": l[0], "nondet": a,
                         "det": b, "ok": ok, "tight": a == b})
            print("    %-8s %-14s %-14s %-8s %s"
                  % (l[0], a, b, "yes" if ok else "*** NO ***",
                     "equal" if a == b else "det is %s cycles lower"
                     % (a - b if a is not None and b is not None else "?")))
    print()
    print("=" * 78)
    print("VERDICT")
    print("=" * 78)
    bad = [r for r in rows if not r["ok"]]
    equal = [r for r in rows if r["tight"]]
    print("  lanes checked:                 %d" % len(rows))
    print("  det <= nondet on every lane:   %s"
          % ("YES" if not bad else "*** NO: %s ***"
             % ", ".join("%s/%s" % (r["inst"], r["lane"]) for r in bad)))
    print("  lanes where the two are EQUAL: %d of %d" % (len(equal), len(rows)))
    print()
    if bad:
        print("  *** The nondeterministic model does NOT subsume the deterministic")
        print("      one. That is a model bug, and it puts every Part 3 and Part 4")
        print("      number in doubt -- all of them came from the <= version. ***")
        return 1
    print("  ⭐ CONCLUSION: the proved bound is TIE-BREAK-FREE. It was computed as")
    print("     the max over all tie-breaks, so any deterministic rule the RTL")
    print("     implements -- lowest lane index, round-robin, a priority encoder,")
    print("     whatever is cheapest in cells -- is covered by it.")
    print()
    print("  ⛔ SO RUNG 4's R4-F2 IS TIGHTER THAN IT NEEDS TO BE. The RTL does NOT")
    print("     have to reproduce a specific tie-break. What it DOES have to")
    print("     reproduce exactly is the RELEASE convention (an action whose")
    print("     timestamp equals the current cycle is ready THAT cycle) and")
    print("     non-preemption -- those are not max-ed over, they are assumed.")
    print()
    print("  ⚠ ONE CAVEAT THAT SURVIVES: tie-break freedom holds for the BOUND")
    print("     (r_i <= D_i), not for BYTE-EXACT waveform equality. Part 2 demands")
    print("     the RTL match the golden model byte-for-byte, and two different")
    print("     tie-breaks emit different byte orders when deadlines collide. So")
    print("     the golden model must be pinned to WHATEVER rule the RTL picks --")
    print("     it just does not have to be any particular one.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
