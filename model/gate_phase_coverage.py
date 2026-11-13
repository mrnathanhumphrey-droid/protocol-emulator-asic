"""GATE PHASE COVERAGE -- every bench's full phase coverage is established
(step 3a; Wilson 10-20 standing rule + R3's three hardening points).

    python model/gate_phase_coverage.py          # the suite: PENDING printed
    python model/gate_phase_coverage.py --tag    # the lock step: PENDING = RED

model/phase_coverage.py holds one row per tracked bench. This gate checks:
  G1  CLOSED WORLD: the rows cover `git ls-files test/tb_*.v` EXACTLY; every
      named runner / recipe is tracked and names its bench.
  G2  IN_SUITE: the runner's own module-level PHASE_FLOOR equals the row's
      floor and is USED in its source beyond the assignment (an assert that
      no longer reads the constant would hide a weaker floor).
  G3  SWEEP: the record exists, every run in it passed, its union meets the
      row's claim -- red otherwise. Then FRESHNESS: set_hash(its inputs) at
      HEAD == the record and they are committed + clean; if not, the row is
      PENDING (the sweep must be re-run: its recipe is named).
  CHIP_DRIVEN / NOT_TIMING: a non-empty reason (red otherwise).
PENDING keeps the suite green and is printed by name; `--tag` is RED on any.
MUST-FIRES (planted, through the same functions): a bench with no row; a row
for no bench; a floor above the runner's; a floor constant never used; a
sweep record with a failed run; a moved input -> PENDING and --tag red; an
empty reason.
"""
from __future__ import annotations

import ast
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "ci"))
sys.path.insert(0, HERE)
import blobhash                                    # noqa: E402
import phase_coverage                              # noqa: E402
import clock                                       # noqa: E402  Wilson 11-03

CLASSES = ("IN_SUITE", "SWEEP", "CHIP_DRIVEN", "NOT_TIMING")


def tracked():
    return set(blobhash._git(["ls-files"])[1].decode().splitlines())


def world_problems(rows, benches, files):
    """G1. `benches` = tracked tb_*.v; `files` = every tracked path."""
    probs = []
    for b in sorted(benches - set(rows)):
        probs.append("%s has NO row -- an unclassified bench" % b)
    for b in sorted(set(rows) - benches):
        probs.append("row %s names no tracked bench" % b)
    for b, (cls, spec) in sorted(rows.items()):
        if cls not in CLASSES:
            probs.append("%s: unknown class %r" % (b, cls))
        if cls in ("IN_SUITE", "SWEEP"):
            for k in ("runner", "recipe"):
                p = spec.get(k)
                if p and p not in files:
                    probs.append("%s: its %s %s is not tracked" % (b, k, p))
        if cls in ("CHIP_DRIVEN", "NOT_TIMING") and not str(spec).strip():
            probs.append("%s: %s with no reason" % (b, cls))
    return probs


def floor_problems(bench, short, src):
    """G2 on one runner's source text. ⭐ The floor is the target clock's own
    phase count less PHASE_SHORT (Wilson 11-03): the row holds `short`, the
    runner states PHASE_SHORT as a literal and READS PHASE_FLOOR."""
    tree = ast.parse(src)
    val = None
    for n in tree.body:
        if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "PHASE_SHORT"
                                             for t in n.targets):
            val = getattr(n.value, "value", None)
    uses = sum(1 for n in ast.walk(tree)
               if isinstance(n, ast.Name) and n.id == "PHASE_FLOOR"
               and isinstance(n.ctx, ast.Load))
    if val is None:
        return ["%s: its runner has no module-level PHASE_SHORT" % bench]
    probs = []
    if val != short:
        probs.append("%s: runner PHASE_SHORT = %s, the row says %s" % (bench, val, short))
    if uses == 0:
        probs.append("%s: PHASE_FLOOR is assigned but never READ -- the check "
                     "does not use it" % bench)
    return probs


def sweep_state(bench, spec, rec, head_hash, dirty):
    """G3 -> (problems, pending): red for a bad record, PENDING for a stale one."""
    if rec is None:
        return [], ["%s: no record %s -- run %s --record %s"
                    % (bench, spec["record"], spec["recipe"], spec["record"])]
    res = rec.get("result") or {}
    probs = []
    if res.get("passed") != res.get("total") or not res.get("total"):
        probs.append("%s: the sweep record has %s of %s runs passing"
                     % (bench, res.get("passed"), res.get("total")))
    if "phases_ns" in spec and len(res.get("phases_ns") or []) < spec["phases_ns"]:
        probs.append("%s: the sweep covered %s phases, the row claims %d"
                     % (bench, res.get("phases_ns"), spec["phases_ns"]))
    claim = res.get("claim")
    # ⭐ THE CLAIM IS PER ARM since 31954d1 (11-03, the chip to 60 MHz): the
    # chip arm covers clock.phases() = 17, the FPGA arm stays at 50 MHz's 20,
    # so the sweep writes {arm: claim}. A flat claim (one for every arm, the
    # pre-11-03 shape) is still read; an arm with no claim of its own is red.
    per_arm = bool(claim) and "S1" not in claim
    for arm, u in (res.get("union") or {}).items():
        c = (claim.get(arm) if per_arm else claim) if claim else None
        if claim and c is None:
            probs.append("%s: arm %s has no claim in the record" % (bench, arm))
            continue
        if c and not (tuple(u["S1"]) >= tuple(c["S1"])
                      and tuple(u["S2"]) >= tuple(c["S2"])
                      and u["S3_relative"] >= c["S3_relative"]):
            probs.append("%s: arm %s's union %s is below the claim %s"
                         % (bench, arm, u, c))
    pending = []
    if dirty:
        pending.append("%s: sweep inputs uncommitted: %s" % (bench, dirty[:3]))
    elif (rec.get("inputs") or {}).get("sha256") != head_hash:
        pending.append("%s: the sweep's inputs MOVED since its record (%s... -> "
                       "%s...) -- re-run %s --record %s"
                       % (bench, str((rec.get("inputs") or {}).get("sha256"))[:12],
                          str(head_hash)[:12], spec["recipe"], spec["record"]))
    return probs, pending


def arms_rec(ok_s1):
    """a per-arm sweep result (the 11-03 shape): the chip arm `ok` claims
    17 / 17 / 12, the FPGA arm 20 / 20 / 15; `ok` covers `ok_s1` on S1."""
    return {"union": {"ok": {"S1": [ok_s1, ok_s1], "S2": [17, 17], "S3_relative": 12},
                      "fpga": {"S1": [20, 20], "S2": [20, 20], "S3_relative": 15}},
            "claim": {"ok": {"S1": [17, 17], "S2": [17, 17], "S3_relative": 12},
                      "fpga": {"S1": [20, 20], "S2": [20, 20], "S3_relative": 15}}}


def main() -> int:
    tag = "--tag" in sys.argv
    print("=" * 78)
    print("PHASE COVERAGE -- every bench's full phase coverage, by its evidence%s"
          % (" (--tag: PENDING is RED)" if tag else ""))
    print("=" * 78)
    rows = phase_coverage.ROWS
    files = tracked()
    benches = {p for p in files if p.startswith("test/tb_") and p.endswith(".v")}
    probs = world_problems(rows, benches, files)
    pending = []
    recs = {}
    for b, (cls, spec) in sorted(rows.items()):
        line = cls
        if cls == "IN_SUITE":
            with open(os.path.join(ROOT, spec["runner"]), encoding="utf-8") as fh:
                p = floor_problems(b, spec["short"], fh.read())
            probs += p
            line += " %s >= %d/%d" % (os.path.basename(spec["runner"]),
                                      clock.phases() - spec["short"], clock.phases())
        elif cls == "SWEEP":
            path = os.path.join(ROOT, spec["record"])
            if spec["record"] not in recs:
                recs[spec["record"]] = None
                if os.path.isfile(path):
                    with open(path, encoding="utf-8") as fh:
                        recs[spec["record"]] = json.load(fh)
            rec = recs[spec["record"]]
            files_in = ((rec or {}).get("inputs") or {}).get("files") or []
            try:
                hh = blobhash.set_hash(files_in) if files_in else None
            except KeyError as e:
                hh = "<%s>" % e
            p, pend = sweep_state(b, spec, rec, hh, blobhash.dirty(files_in) if files_in else [])
            probs += p
            pending += pend
            line += " %s%s" % (spec["record"], "  PENDING" if pend else "  fresh")
        print("  %-22s %s" % (os.path.basename(b), line))
    # ⭐ v2 (Wilson 10-25): a pending sweep whose inputs moved ONLY inside step
    # 2's declared change set is STALE (model/stale_records.py); any input
    # outside it is a FAIL, not a quiet PENDING
    stale_why = None
    if pending:
        import stale_records as SR
        ins = sorted({f for r in recs.values() if r
                      for f in (r.get("inputs") or {}).get("files") or []})
        v, why = SR.stale_verdict("model/gate_phase_coverage.py", SR.moved(ins))
        print("  stale_records: %s -- %s" % (v, why))
        if v == "STALE":
            stale_why = why
        elif v == "FAIL" and not tag:
            probs.append("pending sweep(s) are not the declared staleness: %s" % why)
    for p in probs:
        print("  *** %s" % p)
    for p in pending:
        print("  PENDING %s" % p)
    ok = not probs and not (tag and pending)
    if tag and pending:
        print("  *** --tag: %d PENDING row(s) -- the tag waits for the sweep(s)" % len(pending))

    print("  --- must-fire: the checks reject what they claim to ---")
    one = {"test/tb_x.v": ("NOT_TIMING", "r")}
    good_rec = {"result": {"passed": 2, "total": 2, "phases_ns": [0, 1]},
                "inputs": {"sha256": "h"}}
    sp = {"record": "r.json", "recipe": "s.py", "phases_ns": 2}
    for what, red in (
            ("a bench with no row",
             world_problems({}, {"test/tb_x.v"}, set())),
            ("a row for no bench", world_problems(one, set(), set())),
            ("an empty NOT_TIMING reason",
             world_problems({"test/tb_x.v": ("NOT_TIMING", " ")}, {"test/tb_x.v"}, set())),
            ("a floor below the row's (more phases short)",
             floor_problems("b", 0, "PHASE_SHORT = 2\nPHASE_FLOOR = P - PHASE_SHORT\n"
                                     "ok = x >= PHASE_FLOOR\n")),
            ("a floor constant never read",
             floor_problems("b", 0, "PHASE_SHORT = 0\nPHASE_FLOOR = P - PHASE_SHORT\n"
                                     "ok = x >= 20\n")),
            ("a sweep record with a failed run",
             sweep_state("b", sp, dict(good_rec, result=dict(good_rec["result"], passed=1)),
                         "h", [])[0]),
            ("a sweep below its claimed phases",
             sweep_state("b", dict(sp, phases_ns=7), good_rec, "h", [])[0]),
            # per-arm claims (11-12): each arm against its OWN claim
            ("an arm below its own per-arm claim",
             sweep_state("b", sp, dict(good_rec, result=dict(good_rec["result"], **arms_rec(16))),
                         "h", [])[0]),
            ("an arm with no claim of its own",
             sweep_state("b", sp, dict(good_rec, result=dict(
                 good_rec["result"], union=arms_rec(17)["union"],
                 claim={"ok": arms_rec(17)["claim"]["ok"]})), "h", [])[0]),
            ("a flat claim the union misses (pre-11-03 shape)",
             sweep_state("b", sp, dict(good_rec, result=dict(
                 good_rec["result"], union=arms_rec(17)["union"],
                 claim={"S1": [20, 20], "S2": [20, 20], "S3_relative": 15})), "h", [])[0])):
        print("    %-46s %s" % (what, "red  ok" if red else "*** MISSED"))
        ok = ok and bool(red)
    pend = sweep_state("b", sp, good_rec, "MOVED", [])[1]
    ctl = sweep_state("b", sp, good_rec, "h", [])
    print("    %-46s %s" % ("a moved sweep input -> PENDING (and --tag red)",
                            "red  ok" if pend else "*** MISSED"))
    print("    %-46s %s" % ("the fresh record (control)",
                            "ok" if not ctl[0] and not ctl[1] else "*** WRONG"))
    ok = ok and bool(pend) and not ctl[0] and not ctl[1]
    ctl2 = sweep_state("b", sp, dict(good_rec, result=dict(good_rec["result"], **arms_rec(17))),
                       "h", [])[0]
    print("    %-46s %s" % ("each arm at its own claim (control)",
                            "ok" if not ctl2 else "*** WRONG %s" % ctl2))
    ok = ok and not ctl2
    print()
    print("  %d rows: %d PENDING" % (len(rows), len(pending)))
    ok = ok and not probs
    if ok and stale_why:
        print("  GATE phase_coverage: STALE (declared: %s)" % stale_why)
        return 0
    print("  GATE phase_coverage: %s" % ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
