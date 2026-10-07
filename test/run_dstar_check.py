"""THE D* THEOREM'S CHECK -- per-lane refill queueing must be ZERO at d >= D*.

⛔⛔ WHY THIS IS NOW THE LOAD-BEARING GATE. The one published timing claim is
`d_min >= D* = k*L_REFILL = 20  ->  J = 1`, and R1 showed what it actually
rests on: a term nobody was counting. A lane waiting for its action word can be
made to wait while the single fetch port refills for a lane that OUTRANKS it --
the engine idle, nothing executing, so pyRTA's recurrence charges nothing and
the winner-blocked stall counter skips it because the winner is not the
subject. Below D* that term measures 29 cycles.

THE THEOREM (docs/J_LANE_PROOF.md, Theorem 3): in steady state, for
`d_min >= D*`, that term is ZERO -- not bounded, zero.

THE FALSIFIER, pre-stated: any program with `d_min >= D*` and a nonzero
per-lane refill wait.

⭐ RQ, NOT `gap`. `tb_jlane` splits an idle cycle in which the subject is not
the winner into two classes, and only one of them is this term:
    RQ  the winner's head is INVALID -- the port is refilling for a lane that
        outranks me. THIS is the term, and the theorem says 0.
    DD  the winner's head is VALID -- its dispatch-decision cycle. Ordinary
        EDF ordering, and it is NOT zero above D*: it rises 1,1,2,3,3 across
        the lanes in deadline order, exactly as EDF predicts.
⛔ Conflating them would have falsified the published claim on the first spot
check, which read `gap` = 1..3 at d = 20 with the stall at zero. The gate must
assert the right quantity or it refutes a true claim.

⚠ STEADY STATE ONLY, declared. The cold start is a separate regime -- a head
IS invalid on a lane's first action, by construction -- and `tb_smoke` reports
cold and steady separately for that reason. The warm-up here is what makes this
a steady-state reading, and it is printed.
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
                         os.path.join(os.environ.get("TEMP", "/tmp"), "pe_ds"))

L_REFILL, N_LANES = 4, 5
D_STAR = N_LANES * L_REFILL          # 20
NCYC, WARMUP, MIN_WINDOW, MIN_IV = 200000, 20000, 100000, 100

# ⭐ THE SAME SEVEN PORT-FEASIBLE POINTS `price_j_sweep.sh` MEASURES, so the
# two checks are about the same programs. Each is built as
# `--five d d+1 d+2 d+3 d+4`, that sweep's recipe, so d is the MINIMUM delay
# and the arm is port-feasible iff d >= D*.
D_POINTS = [20, 21, 22, 25, 30, 40, 60]
# ⛔ AND A CONTROL BELOW D*, because a gate that only ever looks above the
# threshold cannot show the threshold is where anything happens. It MUST come
# out non-zero; a zero here means the instrument is not measuring.
#
# ⚠ THE CONTROL IS ARM C, NOT A UNIFORM SUB-D* SWEEP, and the reason is a
# measured one. Uniform sub-D* programs (d = 12..18) are NON-STATIONARY: T1
# found lanes starving and trading places on a beat longer than a million
# cycles, so those cells fail the stationarity precondition and read NO
# READING -- which is the precondition working, not a result. Arm C
# (8, 100, 100, 100, 100) is sub-D* AND stationary: T1 adjudicated all five of
# its lanes, and its lane 4 is where RQ = 29 was measured.
# ⭐ Using the arm that already produced the number keeps this gate's control
# and R1's headline measurement on the SAME program, rather than on two
# different sub-D* shapes that happen to share a label.
CONTROL = ("arm C", [8, 100, 100, 100, 100])

SRCS = ["src/pe_engine.v", "src/pe_store.v", "src/project.v"]


def run(cmd, cwd=ROOT):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=cwd)


def build():
    os.makedirs(SCRATCH, exist_ok=True)
    out = os.path.join(SCRATCH, "jlane.vvp")
    r = run([tool("iverilog"), "-g2012", "-o", out, "-s", "tb_jlane",
             "-Ptb_jlane.SPL_CFG=2", "test/tb_jlane.v"] + SRCS)
    if r.returncode != 0:
        print("*** build failed")
        print((r.stdout + r.stderr)[-700:])
        return None
    return out


def one(vvp, base, nbytes, lane, ncyc=NCYC, warmup=WARMUP):
    r = run([tool("vvp"), vvp, "+IMG=test/%s.hex" % base, "+NBYTES=%d" % nbytes,
             "+LANE=%d" % lane, "+NCYC=%d" % ncyc, "+WARMUP=%d" % warmup])
    txt = r.stdout + r.stderr
    m = re.search(r"JLANE lane=(\d+) sum=(\d+) run=(\d+) wall=(\d+) iv=(\d+) "
                  r"drop=(\d+) fire=(\d+) win=(\d+) agg=(\d+) rdy=(\d+) "
                  r"blk=(\d+) free=(\d+) gap=(\d+) full=(\d+) rq=(\d+) "
                  r"dd=(\d+)", txt)
    if not m:
        return None, "no JLANE line"
    k = ("lane", "sum", "run", "wall", "iv", "drop", "fire", "win", "agg",
         "rdy", "blk", "free", "gap", "full", "rq", "dd")
    d = {n: int(m.group(i + 1)) for i, n in enumerate(k)}
    fails = [l.strip() for l in txt.splitlines()
             if "*** FAIL" in l or "*** VOID" in l]
    return d, fails


# ⛔⛔ THE CONTROLS NEED A LONGER RUN, AND THAT IS A MEASURED FACT, NOT A
# CONVENIENCE. Sub-D* programs have a transient two orders of magnitude longer
# than port-feasible ones -- T1 measured arm A lane 0 completing SIX release
# intervals in the first 196k cycles and thousands in the next 272k, because
# below D* lanes starve and trade places on a long beat. At 200k the controls
# produced NO READING (too few intervals), which is the precondition working:
# it refused to report a zero from a dead instrument. ⚠ A zero there would have
# been read as "the instrument sees nothing below D* either", i.e. as evidence
# AGAINST the very contrast the controls exist to show.
# ⭐ Above D* nothing starves, so 200k converges; the asymmetry in run length
# mirrors an asymmetry in the behaviour being measured.
CTRL_NCYC, CTRL_WARMUP = 1000000, 200000


def sweep(vvp, sets, label, expect_zero, ncyc=NCYC, warmup=WARMUP):
    """`sets` is [(name, [5 delays])]. `expect_zero` is the prediction."""
    rc = 0
    rows = []
    print("  --- %s ---" % label)
    print("    %-7s %-8s %-28s %s"
          % ("program", "lanes", "RQ per lane", "verdict"))
    for d, delays in sets:
        base = "probe_ds%s" % str(d).replace(" ", "")
        g = run([sys.executable, os.path.join(HERE, "make_smoke_image.py"),
                 "--five"] + [str(x) for x in delays] + [base])
        if g.returncode != 0:
            print("    %-7s *** could not build the image" % d)
            rc = 1
            continue
        with open(os.path.join(HERE, base + ".hex"), encoding="ascii") as fh:
            nbytes = len([w for w in fh.read().split() if w])
        rqs, void = [], []
        for lane in range(N_LANES):
            p, fails = one(vvp, base, nbytes, lane, ncyc, warmup)
            if p is None:
                void.append("lane %d: %s" % (lane, fails))
                continue
            # ⛔ PRECONDITIONS, same as the per-lane sweep's: a reading from an
            # empty window or a dead instrument is not a zero.
            if p["win"] < MIN_WINDOW:
                void.append("lane %d window %d" % (lane, p["win"]))
            elif p["iv"] < MIN_IV:
                void.append("lane %d only %d intervals" % (lane, p["iv"]))
            elif fails:
                void.append("lane %d: %s" % (lane, fails[0][:40]))
            else:
                rqs.append(p["rq"])
        if void:
            print("    %-7s %-8s %-28s *** NO READING: %s"
                  % (d, "-", "-", "; ".join(void)[:40]))
            rc = 1
            continue
        worst = max(rqs)
        ok = (worst == 0) if expect_zero else (worst > 0)
        print("    %-7s %-8d %-28s %s"
              % (d, len(rqs), " ".join(str(x) for x in rqs),
                 ("RQ = 0  ok" if expect_zero else "RQ > 0  ok") if ok
                 else ("*** FALSIFIER FIRED: RQ = %d" % worst if expect_zero
                       else "*** RQ = 0 -- the instrument sees nothing here")))
        if not ok:
            rc = 1
        rows.append((d, rqs))
    return rows, rc


def main() -> int:
    banner("iverilog", "vvp")   # ruling V2: the log names the binary that ran
    print()
    print("=" * 78)
    print("THE D* THEOREM -- per-lane refill queueing is ZERO at d >= D* = %d"
          % D_STAR)
    print("=" * 78)
    print("  theorem  : docs/J_LANE_PROOF.md, Theorem 3")
    print("  falsifier: ANY program with d_min >= D* and a nonzero per-lane")
    print("             refill wait (RQ)")
    print("  quantity : RQ -- idle cycles while the port refills for a lane")
    print("             that outranks me. NOT `gap`, which also contains DD")
    print("             (others' dispatch-decision cycles) and is nonzero")
    print("             above D* by EDF ordering alone.")
    print("  run      : %d cycles, %d warm-up above D*; %d / %d for the"
          % (NCYC, WARMUP, CTRL_NCYC, CTRL_WARMUP))
    print("             controls, whose transient is ~2 orders longer")
    print("             (measured in T1) -> STEADY STATE only; the cold")
    print("             start is a separate regime by construction.")
    print()
    vvp = build()
    if vvp is None:
        return 1

    above, rc1 = sweep(vvp, [(d, [d + i for i in range(5)])
                                 for d in D_POINTS],
                       "PORT-FEASIBLE: the theorem predicts 0", True)
    print()
    below, rc2 = sweep(vvp, [CONTROL],
                       "CONTROL below D*: this MUST be non-zero", False,
                       CTRL_NCYC, CTRL_WARMUP)

    rc = rc1 | rc2
    print()
    print("-" * 78)
    if rc == 0:
        n = sum(len(r) for _d, r in above)
        print("  THEOREM 3 HOLDS on every point measured:")
        print("    %d port-feasible cells (%d points x %d lanes): RQ = 0"
              % (n, len(above), N_LANES))
        print("    %d control cells below D* (arm C): RQ > 0, so the instrument"
              % sum(len(r) for _d, r in below))
        print("    demonstrably able to see the term it reports as zero.")
        print("  ⇒ The published claim `d_min >= D* -> J = 1` rests on this,")
        print("    and the term it needed to be zero IS zero -- measured per")
        print("    lane, not inferred from an aggregate.")
        print("  ⚠ A MEASUREMENT, NOT THE PROOF. The theorem is in")
        print("    docs/J_LANE_PROOF.md with its premises anchored to the RTL")
        print("    by `model/gate_j_proof_anchors.py`. This gate is its CHECK:")
        print("    it can falsify the theorem and cannot establish it.")
    else:
        print("  *** THE CHECK DID NOT PASS. If the falsifier fired above D*,")
        print("      the published claim is in question and that is the")
        print("      finding -- record it, do not re-scope the threshold.")
    print()
    print("=" * 78)
    print("  GATE d-star: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
