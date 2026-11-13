#!/usr/bin/env python3
"""run_rean_floor -- the RE-ANCHOR FLOOR, confirmed on the RTL (Wilson 11-12, the floor ruling).

THE CLAIM (lean: the named hardware hypothesis of the USB-lane brick): a re-anchored release
lands at least REAN_PIPE + floor(d / REAN_HALVING) cycles after the release of the sample before
it, whatever the host does. Reason (pe_engine.v): `rean_cap` needs the lane's NEXT release still
in the future (`tf_diff(now_n, l_timestamp)`), and a bit's writeback at r + 2 makes r + d
visible only at r + 3; the target is `now + d/2`.

THE TEST, on the existing bench (test/tb_usbrx.v, unchanged), at d = 40 and one other d:
  1. a clean packet; the bench's `SA <wb> <ts>` line gives each sample's writeback and release
  2. pick a sample k whose next host edge falls before sample k+1; move THAT edge to
     wb_k + o, for o = O_MIN .. O_MAX (one sim each, bracketing the guard: see O_MIN);
     everything else unchanged
  3. read the next release ts_{k+1} - ts_k per o
  PASS iff: some early o is DROPPED (spacing = d: the guard is seen working, presence not
  absence), the minimum over accepted o equals the floor EXACTLY, and nothing lands below it.
Constants: lean/JLane/proof_constants.json (the one source the Lean build and the clock gate
also read). Never typed here.

MUST-FIRE: the same sweep built with -DM_REAN_FLOOR_EARLY (src/pe_engine.v: `rean_cap` reads
`ts_n[USB_LANE]`, not `l_timestamp[USB_LANE]` -- the writeback visible a cycle early).
⛔ EXACTLY ONE CYCLE (Wilson 11-12): the mutant's minimum accepted spacing must equal the floor
MINUS ONE at every d (22 at d = 40, 26 at d = 48). Lower than that, the mutant is doing more
than it claims: red. Every offset where it differs from the clean arm is printed, so anything
else it changes about re-anchoring is on the record. Identical to the clean arm: red.

POSITIVE TOKEN: `GATE rean_floor: PASSED`.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import run_usbrx as U  # noqa: E402
import pe_isa as I  # noqa: E402
import sim_run  # noqa: E402

with open(os.path.join(ROOT, "lean", "JLane", "proof_constants.json")) as _fh:
    K = json.load(_fh)
PIPE, HALV = K["rean_pipe"], K["rean_halving"]
#: the sweep brackets the guard: an edge reaches `rean_cap` only after the input synchronizer
#: (measured 11-12: an edge 1 cycle after the writeback lands 3 cycles above the floor), so the
#: worst case is an edge at the PIN slightly BEFORE the writeback, captured just after it.
#: Offsets whose run moves sample k itself (re-anchored before its own release) are excluded.
O_MIN, O_MAX = -8, 6
D_OTHER = 48                    # the second d the ruling asks for (stimulus choice, even, > 40)


def floor_of(d):
    return PIPE + d // HALV


def sweep(vvp, tmp, d, tag):
    U.D = d                                    # run_usbrx's image() and line() read the module's D
    img = os.path.join(tmp, "usbrx_main.hex")  # the name run_usbrx's registered pattern expects
    img = os.path.join(tmp, "usbrx_%s_%d.hex" % (tag, d)) if False else img
    sub = os.path.join(tmp, "%s_d%d" % (tag, d))
    os.makedirs(sub, exist_ok=True)
    img = os.path.join(sub, "usbrx_main.hex")
    I.write_image(img, U.image())
    sim_run.scratch_image(U.GEN, img)
    pk = [U.packet(*U.PAYLOADS[3])]            # the seeded random payload: edges throughout
    tr, t_end = U.line(pk, 0.0, 0, 11)

    def run(trace, name):
        wv = os.path.join(sub, "wave_%s.txt" % name)
        U.write_wave(wv, trace)
        rx, se, ce, sa, end, tail = U.sim(vvp, img, wv, t_end + 400)
        return sa, end

    sa, end = run(tr, "clean")
    if not end or len(sa) < 10:
        return None, "clean run: %d samples, end %s" % (len(sa), end)
    # sample k: a mid-packet sample with exactly one host edge before sample k+1
    edges = [c for c, _l in tr]
    pick = None
    for k in range(4, len(sa) - 2):
        between = [i for i, c in enumerate(edges) if sa[k][0] < c < sa[k + 1][0]]
        if len(between) == 1:
            pick = (k, between[0])
            break
    if pick is None:
        return None, "no sample with exactly one following edge"
    k, ei = pick
    jobs = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for o in range(O_MIN, O_MAX + 1):
            t2 = list(tr)
            t2[ei] = (sa[k][0] + o, tr[ei][1])
            if ei > 0 and t2[ei][0] <= t2[ei - 1][0]:
                continue
            jobs[o] = pool.submit(run, t2, "o%d" % o)
        out = {}
        for o, f in jobs.items():
            s2, e2 = f.result()
            if not e2 or len(s2) <= k + 1 or s2[k] != sa[k]:
                out[o] = None
            else:
                out[o] = s2[k + 1][1] - s2[k][1]
    return out, None


def judge(vvp, tmp, tag):
    probs, rows = [], {}
    for d in (40, D_OTHER):
        sp, err = sweep(vvp, tmp, d, tag)
        if err:
            probs.append("d=%d: %s" % (d, err))
            continue
        rows[d] = sp
        vals = [v for v in sp.values() if v is not None]
        if not vals:
            probs.append("d=%d: no usable run" % d)
            continue
        acc = [v for v in vals if v != d]
        if d not in vals:
            probs.append("d=%d: no early edge was dropped -- the guard was never seen working" % d)
        if not acc:
            probs.append("d=%d: no edge re-anchored in the sweep" % d)
        elif min(acc) != floor_of(d):
            probs.append("d=%d: minimum re-anchored spacing %d, the floor is %d"
                         % (d, min(acc), floor_of(d)))
        if any(v < floor_of(d) for v in vals):
            probs.append("d=%d: a spacing below the floor: %s" % (d, sorted(vals)[:3]))
    return probs, rows


def main() -> int:
    print("re-anchor floor: next release >= last release + %d + floor(d / %d) "
          "(proof_constants.json)" % (PIPE, HALV))
    tmp = tempfile.mkdtemp(prefix="pe_reanfloor_")
    vvp = os.path.join(tmp, "usbrx.vvp")
    U.build(vvp)
    probs, rows = judge(vvp, tmp, "clean")
    for d, sp in rows.items():
        print("  d=%d floor %d:  o -> spacing  %s" % (d, floor_of(d),
              "  ".join("%d:%s" % (o, v) for o, v in sorted(sp.items()))))
    for p in probs:
        print("  ***", p)
    # the must-fire
    vm = os.path.join(tmp, "usbrx_mut.vvp")
    U.build(vm, defines=("M_REAN_FLOOR_EARLY",))
    mp, mrows = judge(vm, tmp, "mut")
    if mrows == rows:
        print("  must-fire M_REAN_FLOOR_EARLY: *** NOT EFFECTIVE (identical to the clean arm)")
        probs.append("must-fire M_REAN_FLOOR_EARLY changed nothing")
    for d in (40, D_OTHER):
        sp, cl = mrows.get(d) or {}, rows.get(d) or {}
        acc = [v for v in sp.values() if v is not None and v != d]
        want = floor_of(d) - 1
        got = min(acc) if acc else None
        diff = ["o=%d %s->%s" % (o, cl.get(o), v) for o, v in sorted(sp.items()) if cl.get(o) != v]
        print("  must-fire M_REAN_FLOOR_EARLY d=%d: minimum %s, want exactly %d (floor %d - 1)  %s"
              % (d, got, want, floor_of(d), "RED ok" if got == want else "***"))
        print("      differs from the clean arm at: %s" % ("; ".join(diff) or "nowhere"))
        if got != want:
            probs.append("must-fire d=%d: minimum %s, not exactly floor - 1 = %d%s"
                         % (d, got, want, " -- the mutant does MORE than one cycle"
                            if got is not None and got < want else ""))
        # ⛔ THE CHECK ITSELF MUST CONVICT THE MUTANT (gate_meta seam, 11-13 CI):
        # the lines above read the sweep data, so with `judge` stubbed to clean
        # they stayed green. `judge`'s own problem list must name d's floor.
        conv = [p for p in mp if p.startswith("d=%d:" % d) and "floor" in p]
        print("      judge on the mutant: %s" % (conv[0] if conv else "*** NO PROBLEM -- the check does not see it"))
        if not conv:
            probs.append("must-fire d=%d: judge() reported nothing on M_REAN_FLOOR_EARLY" % d)
    if probs:
        print("GATE rean_floor: FAILED (%d)" % len(probs))
        return 1
    print("GATE rean_floor: PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
