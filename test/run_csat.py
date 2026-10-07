"""THE C SATURATION SWEEP -- is the dispatch FSM's floor 2 cycles or 3?

⛔⛔ PRE-REGISTERED IN `docs/PREREG_C_SAT.md` AT 2bdc109, BEFORE `tb_csat.v`
EXISTED. Hypothesis: `btbmin = 2`. Falsifier: `3`. Read that document before
reading a number out of here; the disposition for every branch is written there
and is not re-decided from the result.

WHAT IS AT STAKE. Every published `r_i`, every margin in the shipped lane
table, and `B = max(C_j - 1)` are computed with `C = 2`, taken from
`svc_cycles / svc_jobs` -- which counts cycles where `st != ST_IDLE` and is
therefore the engine's OCCUPANCY per job, not the SPACING between the jobs it
can deliver. `ST_WB` assigns `st <= ST_IDLE` unconditionally, so the FSM is a
three-state cycle. If its floor is 3, `C` is one too small everywhere and every
margin is optimistic -- the forbidden direction, in the numbers we publish.

⭐ THE ARMS ARE A CONTRAST, NOT A SURVEY. Arm S is the measurement; arm T is
the SAME structure with more slack, and §4.2 precondition 8 requires S and T to
agree -- if they do not, something other than the FSM sets the floor and
neither number is the one the document is about. Arm U is oversubscribed and
may only be LARGER (no program can beat the FSM). Arm V is the shipped program,
reported so nobody later quotes its arrival-limited mean as `C`.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from toolchain import banner, tool          # noqa: E402  ruling V

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRATCH = os.environ.get("PE_SCRATCH",
                         os.path.join(os.environ.get("TEMP", "/tmp"), "pe_cs"))

DELTA_PREREG = 2
NCYC, WARMUP = 200000, 20000
MIN_WINDOW, MIN_DISP, MIN_BTB = 100000, 1000, 100

SRCS = ["src/pe_engine.v", "src/pe_store.v", "src/project.v"]

# (tag, delays or None for the shipped image, what the arm is for, is it the
#  primary measurement?)
# ⛔ ARM S's d = 40 IS CHOSEN, NOT CONVENIENT. P8 makes the timestamp advance
# absolute, so five lanes sharing one delay stay phase-aligned forever and
# release in the SAME cycle -- a burst of five back-to-back dispatches every
# 40 cycles. And 40 >= 2*D* = 40 means the port has twice the time it needs,
# so refill cannot be the limit, which is the condition the ruling names.
ARMS = [
    ("S", [40] * 5, "simultaneous release, port-feasible: THE measurement",
     True),
    ("T", [60] * 5, "the same structure with more slack -- must agree with S",
     True),
    ("U", [2] * 5, "oversubscribed: may only be LARGER than the floor",
     False),
    ("V", None, "the shipped program: arrival-limited, NOT a floor", False),
]


def run(cmd, cwd=ROOT):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=cwd)


def build():
    os.makedirs(SCRATCH, exist_ok=True)
    out = os.path.join(SCRATCH, "csat.vvp")
    r = run([tool("iverilog"), "-g2012", "-o", out, "-s", "tb_csat",
             "-Ptb_csat.SPL_CFG=2", "test/tb_csat.v"] + SRCS)
    if r.returncode != 0:
        print("*** build failed")
        print((r.stdout + r.stderr)[-900:])
        return None
    return out


KEYS = ("btbmin", "dmin", "dmax", "btb", "nsp", "ndisp", "ntrans", "win",
        "halt", "cfgerr", "ovr", "h1", "h2", "at", "mid")


def one(vvp, img, nbytes):
    r = run([tool("vvp"), vvp, "+IMG=%s" % img, "+NBYTES=%d" % nbytes,
             "+NCYC=%d" % NCYC, "+WARMUP=%d" % WARMUP])
    txt = r.stdout + r.stderr
    m = re.search(r"CSAT img=\S+ " + " ".join(
        r"%s=(-?\d+)" % k for k in KEYS), txt)
    if not m:
        return None, ["no CSAT line"], txt
    d = {k: int(m.group(i + 1)) for i, k in enumerate(KEYS)}
    bad = [l.strip() for l in txt.splitlines()
           if "*** FAIL" in l or "*** VOID" in l]
    return d, bad, txt


def validate(d, bad, primary):
    """⛔ THE PRECONDITIONS OF §4.2, CHECKED HERE AND NOT ONLY IN THE BENCH, so
    a reading cannot be lifted out of the bench's output past its own FAILs.

    ⛔⛔ AND ONE PRECONDITION IS RE-SCOPED HERE, VISIBLY. `tb_csat` applies
    `btb >= 100` unconditionally, because the bench cannot know an arm's role;
    every arm it runs is, as far as it knows, a floor measurement. The ARM
    ROLES live here. For a non-primary arm the btb count is the FINDING rather
    than a precondition -- arm U is oversubscribed, so its heads are usually
    invalid and the engine is rarely able to go back to back, which is the
    thing the arm shows. ⚠ A re-scope done silently is how a wrong scope hides
    in a constant, so the dropped FAIL is PRINTED, not just dropped.
    """
    why = []
    for line in bad:
        if not primary and "back-to-back opportunities" in line:
            print("       ⚠ arm is not a floor claim: the bench's btb"
                  " precondition is NOT applied (%d seen)" % d["btb"])
            continue
        why.append(line)
    if d["win"] < MIN_WINDOW:
        why.append("window %d < %d" % (d["win"], MIN_WINDOW))
    if d["ndisp"] < MIN_DISP:
        why.append("only %d dispatch decisions" % d["ndisp"])
    if abs(d["ndisp"] - d["ntrans"]) > 1:
        why.append("cross-check %d vs %d" % (d["ndisp"], d["ntrans"]))
    if d["halt"] or d["cfgerr"]:
        why.append("halt=%d cfgerr=%d" % (d["halt"], d["cfgerr"]))
    # ⛔⛔ `btb` IS A PRECONDITION ONLY WHERE THE FLOOR IS BEING CLAIMED. Arm V
    # is the shipped program and is EXPECTED to have few back-to-back
    # opportunities -- that is the finding about it, not a failure of it. A
    # precondition applied where the document does not apply it would force a
    # NO READING on the one arm whose purpose is to show the engine idle.
    if primary and d["btb"] < MIN_BTB:
        why.append("btb %d < %d -- the floor was not exercised"
                   % (d["btb"], MIN_BTB))
    # ⛔ IMPOSSIBLE BY CONSTRUCTION: the btb pairs are a SUBSET.
    if d["btbmin"] > 0 and d["dmin"] > d["btbmin"]:
        why.append("dmin %d > btbmin %d, impossible" % (d["dmin"],
                                                        d["btbmin"]))
    return why


def main() -> int:
    banner("iverilog", "vvp")   # ruling V2: the log names the binary that ran
    rc = 0
    print()
    print("=" * 78)
    print("C UNDER SATURATION -- inter-dispatch spacing, not occupancy")
    print("=" * 78)
    print("  pre-reg  : docs/PREREG_C_SAT.md (2bdc109, before the instrument)")
    print("  hypothesis: btbmin = %d   falsifier: %d"
          % (DELTA_PREREG, DELTA_PREREG + 1))
    print("  quantity : btbmin -- the minimum spacing between dispatch")
    print("             decisions over pairs whose predecessor had a")
    print("             SUCCESSOR ALREADY ELIGIBLE during its ST_WB cycle.")
    print("             ⛔ NOT `svc_cycles/svc_jobs`, which is occupancy and")
    print("             reads 2.00 whatever the spacing is.")
    print("  run      : %d cycles, %d warm-up" % (NCYC, WARMUP))
    print()
    vvp = build()
    if vvp is None:
        return 1

    print("  %-4s %-14s %-8s %-7s %-7s %-8s %-7s %s"
          % ("arm", "lanes", "btbmin", "dmin", "dmax", "btb", "ndisp",
             "verdict"))
    res = {}
    for tag, delays, _why, primary in ARMS:
        if delays is None:
            img, base = "test/smoke_image.hex", None
        else:
            base = "probe_csat_%s" % tag.lower()
            g = run([sys.executable, os.path.join(HERE, "make_smoke_image.py"),
                     "--five"] + [str(x) for x in delays] + [base])
            if g.returncode != 0:
                print("  %-4s *** could not build the image" % tag)
                rc = 1
                continue
            img = "test/%s.hex" % base
        path = os.path.join(ROOT, img)
        if not os.path.isfile(path):
            print("  %-4s *** %s is missing" % (tag, img))
            rc = 1
            continue
        with open(path, encoding="ascii") as fh:
            nbytes = len([w for w in fh.read().split() if w])
        d, bad, txt = one(vvp, img, nbytes)
        if d is None:
            print("  %-4s *** NO CSAT LINE: %s" % (tag, bad))
            print(txt[-500:])
            rc = 1
            continue
        why = validate(d, bad, primary)
        lanes = "shipped" if delays is None else " ".join(str(x)
                                                          for x in delays[:1])
        if delays is not None:
            lanes = "%s x5" % delays[0]
        if why:
            print("  %-4s %-14s %-8s %-7s %-7s %-8s %-7s *** NO READING: %s"
                  % (tag, lanes, "-", "-", "-", d["btb"], d["ndisp"],
                     "; ".join(why)[:34]))
            if primary:
                rc = 1
            res[tag] = None
            continue
        print("  %-4s %-14s %-8d %-7d %-7d %-8d %-7d %s"
              % (tag, lanes, d["btbmin"], d["dmin"], d["dmax"], d["btb"],
                 d["ndisp"],
                 "floor" if primary else "not a floor"))
        res[tag] = d

    print()
    print("  --- the arms' purposes, checked ---")
    s, t, u = res.get("S"), res.get("T"), res.get("U")
    if s and t:
        same = s["btbmin"] == t["btbmin"]
        print("    S and T agree (prereg 4.2.8) : %s  (%d vs %d) %s"
              % ("yes" if same else "NO", s["btbmin"], t["btbmin"],
                 "ok" if same else "*** something other than the FSM sets it"))
        if not same:
            rc = 1
    if s and u:
        ok = u["dmin"] >= s["btbmin"]
        print("    U cannot beat the floor      : dmin %d >= %d %s"
              % (u["dmin"], s["btbmin"],
                 "ok" if ok else "*** VOID -- a program beat the FSM, so the"
                 " instrument is miscounting"))
        if not ok:
            rc = 1
    if s and u:
        print("    U btb                        : %d -- the arm's FINDING, not"
              % u["btb"])
        print("      a shortfall: oversubscribed at d = 2, the one fetch port")
        print("      is the binding constraint and heads are usually INVALID,")
        print("      so the engine is rarely able to go back to back at all.")
    v = res.get("V")
    if v:
        print("    V (shipped) btb              : %d back-to-back, btbmin %d"
              % (v["btb"], v["btbmin"]))
        print("      ^ ⭐ STRONGER THAN THIS ARM WAS SCOPED FOR. Its MEAN")
        print("        spacing is arrival-limited and is not a `C` -- that is")
        print("        why it is declared not-a-floor. But %d of its spacings"
              % v["btb"])
        print("        had a successor already eligible, and the minimum over")
        print("        those is %d as well. So the floor is exercised BY THE"
              % v["btbmin"])
        print("        SHIPPED PROGRAM, not only by a synthetic burst.")

    print()
    print("-" * 78)
    if s is None:
        print("  *** NO READING ON THE PRIMARY ARM. Nothing is concluded about")
        print("      C, and the published numbers are neither confirmed nor")
        print("      corrected -- record the instrument's state (prereg 5.3).")
        rc = 1
    elif s["btbmin"] == DELTA_PREREG:
        print("  THE FALSIFIER DID NOT FIRE. btbmin = %d on %d back-to-back"
              % (s["btbmin"], s["btb"]))
        print("  opportunities, so C = 2 stands and the published r_i and")
        print("  margins are computed with the right service time.")
        print("  ⛔ The occupancy figure is relabelled anyway (prereg 5.1): it")
        print("     does not measure spacing whatever the spacing turns out")
        print("     to be.")
    else:
        print("  ⛔⛔ THE FALSIFIER FIRED. btbmin = %d, not %d."
              % (s["btbmin"], DELTA_PREREG))
        print("  On %d spacings where a successor was ALREADY ELIGIBLE during"
              % s["btb"])
        print("  the predecessor's writeback, the engine never dispatched in")
        print("  fewer than %d cycles. The dispatch FSM is a three-state cycle"
              % s["btbmin"])
        print("  and `svc_cycles/svc_jobs = 2.00` measured the two states that")
        print("  are labelled service, not the third that is not.")
        print()
        print("  ⇒ C = %d FOR THE ANALYSIS, per prereg 5.2:" % s["btbmin"])
        print("    1. re-quote every r_i and margin with C = %d, pyRTA PRIMARY"
              % s["btbmin"])
        print("       and ours as the safe-direction cross-check")
        print("    2. B = max(C_j - 1) = %d, not 1" % (s["btbmin"] - 1))
        print("    3. per-lane margins reported, not just the minimum")
        print("    4. a ledger entry, as an error and not a footnote")
        print("    5. ⛔ D* IS UNAFFECTED and must not be re-derived to")
        print("       compensate: D* = k*L_REFILL contains no C.")
        print("    6. ⛔ `d_min >= D* -> J = 1` is a JITTER claim. If C = %d"
              % s["btbmin"])
        print("       makes a lane infeasible that is a MARGIN finding.")
    print()
    print("=" * 78)
    print("  GATE c-sat: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    ⚠ PASSED means the instrument's preconditions held and the arms")
    print("      behaved as the document requires -- NOT that the hypothesis")
    print("      survived. The falsifier firing is a RESULT, not a gate")
    print("      failure, and the disposition above is what it triggers.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
