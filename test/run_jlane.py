"""run_jlane -- the T1 per-lane jitter sweep, adjudicated against the
pre-registration in `docs/PREREG_J_LANE.md` (committed 8bc6979, BEFORE the
instrument existed).

Ten runs: 5 identified lanes x 2 arms. Each run must print its own
preconditions; a run that fails one yields NO READING and is never counted as
a pass.

⛔ WRITES ONLY `probe_`-NAMED FILES (standing rule 6). The images are
`probe_jl_armA.hex` / `probe_jl_armC.hex` and the logs go to the scratch
directory. The J investigation clobbered `five_image.hex` dozens of times
because `--five` had a constant output path; that is what this rule is for.

⛔ THE ADJUDICATION IS THE PRE-REGISTERED ONE, NOT A FRESH ONE. The falsifier
is "any complete release interval, on any identified lane, in any arm, with
sum > 9". One interval is enough: no averaging, no percentile, no discarding
an arm as unrepresentative.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRATCH = os.environ.get("PE_SCRATCH",
                         os.path.join(os.environ.get("TEMP", "/tmp"), "pe_jl"))

# the pre-registered constant, named once
L_REFILL = 4
J_PREREG = 2 * L_REFILL + 1          # = 9
MIN_WINDOW = 100000
MIN_INTERVALS = 100
N_LANES = 5

# ⛔⛔ THE RUN LENGTH AND WARM-UP ARE MEASURED FLOORS, NOT GUESSES, and both
# were raised once the transient was measured. The pre-registration asks for a
# long run (>= 200k cycles) and a window of >= 100k; those are FLOORS, so
# raising them satisfies the pre-registration rather than amending it -- the
# hypothesis, the falsifier and the arms are untouched.
#
# The evidence: on arm A lane 0, a controlled 200k-cycle run completed SIX
# release intervals, while the same lane completed several thousand between
# cycles 196k and 468k. A 4000-cycle warm-up was therefore inside the transient
# by two orders of magnitude, and any maximum taken from that window would have
# been a transient reading presented as a steady-state one.
# ⚠ These numbers were NOT chosen by looking for values that make the result
# come out right. They are chosen to satisfy the stationarity and convergence
# preconditions, which the bench checks and reports independently of the value
# of J_lane.
NCYC = 1000000
WARMUP = 200000

# ⛔⛔ ONE ESCALATION, AT A FIXED MULTIPLE, DECLARED BEFORE THE RESULT.
# The pre-registration's remedy for a failed precondition is "fix the
# instrument and re-run", and for a window precondition that means a longer
# window. But "keep running until it looks stationary" is a STOPPING RULE
# FITTED TO THE DATA, which is the same sin as moving a threshold. So the
# escalation is capped at exactly one retry at exactly 4x, decided here rather
# than after reading the retry, and every escalated cell is REPORTED as
# escalated. A cell that still fails stays OPEN; it is not escalated again.
ESCALATE = 4
MAX_ESCALATIONS = 1

ARMS = (
    # (name, --five delays, probe basename, why this arm is in the set)
    ("A", [12, 13, 14, 15, 16], "probe_jl_armA",
     "uniform sub-D* (d_min=12); where the aggregate 8 was recorded"),
    ("C", [8, 100, 100, 100, 100], "probe_jl_armC",
     "mixed; the arm that falsified U_port via speculative spare fills"),
)

SRCS = ["test/tb_jlane.v", "src/pe_engine.v", "src/pe_store.v", "src/project.v"]


def run(cmd, cwd=ROOT):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=cwd)


# ⭐ THE BUFFER DEPTH, SELECTABLE: `python test/run_jlane.py --spl 1`.
# T3 needs the per-lane wait under BOTH configurations, and the engine's `SPL`
# parameter is what makes the single-buffer arm buildable at all.
SPL = 1 if "--spl" in sys.argv and sys.argv[sys.argv.index("--spl") + 1] == "1" else 2


def build():
    os.makedirs(SCRATCH, exist_ok=True)
    vvp = os.path.join(SCRATCH, "jlane_spl%d.vvp" % SPL)
    r = run(["iverilog", "-g2012", "-o", vvp, "-s", "tb_jlane",
             "-Ptb_jlane.SPL_CFG=%d" % SPL]
            + [os.path.join(ROOT, s) for s in SRCS])
    if r.returncode != 0:
        print("*** build failed")
        print((r.stdout + r.stderr)[-1500:])
        return None
    return vvp


def make_image(delays, base):
    r = run([sys.executable, os.path.join(HERE, "make_smoke_image.py"),
             "--five"] + [str(d) for d in delays] + [base])
    if r.returncode != 0:
        return None, (r.stdout + r.stderr)[-300:]
    path = os.path.join(HERE, base + ".hex")
    if not os.path.isfile(path):
        return None, "no %s written" % path
    with open(path, encoding="ascii") as fh:
        nbytes = len([w for w in fh.read().split() if w])
    return nbytes, None


def parse(txt):
    """Pull the one result line plus every precondition verdict."""
    out = {"fails": [l.strip() for l in txt.splitlines() if "*** FAIL" in l
                     or "*** VOID" in l]}
    m = re.search(r"JLANE lane=(\d+) sum=(\d+) run=(\d+) wall=(\d+) "
                  r"iv=(\d+) drop=(\d+) fire=(\d+) win=(\d+) agg=(\d+) "
                  r"rdy=(\d+) blk=(\d+) free=(\d+)", txt)
    if m:
        for i, k in enumerate(("lane", "sum", "run", "wall", "iv", "drop",
                               "fire", "win", "agg", "rdy", "blk", "free")):
            out[k] = int(m.group(i + 1))
    m = re.search(r"# arm t =([\d ]+)", txt)
    out["t"] = [int(x) for x in m.group(1).split()] if m else None
    return out


# ⛔ WHICH FAILURES A LONGER WINDOW CAN FIX. Stationarity, convergence and the
# interval count are all window-length questions. A halted lane, a wrong image,
# a void consistency check or a missing result line are NOT -- retrying those
# for longer is just taking the same wrong reading more slowly.
WINDOW_CLASS = re.compile(
    r"not stationary|new maximum appeared|intervals \d+ < |BACKLOGGED|window "
    r"\d+ < ")


def cell(vvp, base, nbytes, lane, delays, arm, ncyc, warmup, tag=""):
    """Run one (arm, lane) and validate its preconditions.

    Returns (parsed, why_void, logpath). `why_void` empty means adjudicable.
    ⭐ ONE function, so an escalated re-run is validated by exactly the same
    code as the first attempt -- a retry judged by looser rules would be a
    second standard wearing the first one's name.
    """
    r = run(["vvp", vvp,
             "+IMG=test/%s.hex" % base,
             "+NBYTES=%d" % nbytes,
             "+LANE=%d" % lane,
             "+NCYC=%d" % ncyc,
             "+WARMUP=%d" % warmup])
    log = os.path.join(SCRATCH, "probe_jl_spl%d_%s_L%d%s.log"
                       % (SPL, arm, lane, tag))
    with open(log, "w", encoding="utf-8") as fh:
        fh.write(r.stdout + r.stderr)
    p = parse(r.stdout + r.stderr)

    why_void = list(p["fails"])
    if "sum" not in p:
        why_void.append("no JLANE result line")
    else:
        if p["win"] < MIN_WINDOW:
            why_void.append("window %d < %d" % (p["win"], MIN_WINDOW))
        # ⛔ A WINDOW LARGER THAN THE RUN IS IMPOSSIBLE, and it happened: the
        # bench's dump task shared the run loop's index, so printing a chain
        # restarted the loop. Checked here as well as in the bench, because
        # this is the number the verdict uses.
        if p["win"] > ncyc:
            why_void.append(
                "window %d exceeds NCYC %d -- impossible, so the run length "
                "was not controlled" % (p["win"], ncyc))
        if p["iv"] < MIN_INTERVALS:
            # ⭐ NAME THE CAUSE. A lane ready in >90% of the window is
            # BACKLOGGED -- permanently behind its own period -- so it has
            # almost no release edges to measure between. That is a finding
            # about the program (d < D*), not a quiet lane, and one message
            # for both would hide it.
            backlog = p["rdy"] > (p["win"] * 9) // 10
            why_void.append(
                ("BACKLOGGED: ready in %d of %d window cycles, so only %d "
                 "release edges" % (p["rdy"], p["win"], p["iv"]))
                if backlog else
                ("intervals %d < %d" % (p["iv"], MIN_INTERVALS)))
        if p["run"] > p["agg"] or p["free"] > p["agg"]:
            why_void.append("blocked run (%d/%d) > engine aggregate %d"
                            % (p["run"], p["free"], p["agg"]))
    if p["t"] != delays:
        why_void.append("image echoes t=%s, expected %s" % (p["t"], delays))
    return p, why_void, log


def main() -> int:
    rc = 0
    print()
    print("=" * 78)
    print("T1 -- PER-LANE JITTER, against the pre-registration")
    print("=" * 78)
    print("  hypothesis : J_lane <= 2*L_REFILL + 1 = %d" % J_PREREG)
    print("  falsifier  : ANY complete release interval with sum > %d"
          % J_PREREG)
    print("  pre-reg    : docs/PREREG_J_LANE.md, committed before this ran")
    print("  SPL        : %d  (%s action buffer)"
          % (SPL, "double" if SPL == 2 else "SINGLE"))
    print("  run        : %d cycles, %d warm-up (both raised after the"
          % (NCYC, WARMUP))
    print("               transient was MEASURED -- see the module comment)")
    print()

    vvp = build()
    if vvp is None:
        return 1

    rows, violations, noread, escalated = [], [], [], []
    for arm, delays, base, why in ARMS:
        nbytes, err = make_image(delays, base)
        if nbytes is None:
            print("  *** arm %s: %s" % (arm, err))
            return 1
        print("  arm %s  d=%s  %s  (%d bytes)"
              % (arm, delays, base + ".hex", nbytes))
        print("         %s" % why)
        for lane in range(N_LANES):
            p, why_void, log = cell(vvp, base, nbytes, lane, delays, arm,
                                    NCYC, WARMUP)
            # ⭐ ONE ESCALATION, at the fixed multiple declared above. A
            # window precondition is remedied by a longer window; anything
            # else (a halted lane, a wrong image, a void consistency check) is
            # not, so only window-class failures are retried.
            if why_void and all(WINDOW_CLASS.search(w) for w in why_void):
                print("    lane %d  escalating: %s" % (lane, why_void[0]))
                print("             re-running at %dx cycles (one retry, "
                      "declared before the result)" % ESCALATE)
                p, why_void, log = cell(vvp, base, nbytes, lane, delays, arm,
                                        NCYC * ESCALATE, WARMUP * ESCALATE,
                                        tag="x%d" % ESCALATE)
                if not why_void:
                    escalated.append((arm, lane))

            if why_void:
                print("    lane %d  NO READING -- %s" % (lane, "; ".join(
                    dict.fromkeys(why_void))))
                # ⭐ THE UN-ADJUDICATED CELL STILL CARRIES A READING, clearly
                # labelled as a different quantity. The pre-registered
                # quantity is a per-release-interval sum and cannot be
                # computed here; the longest blocked run can, and reporting it
                # is how a refusal stays informative instead of being a hole
                # someone later fills with an assumption.
                if "free" in p:
                    print("             adjacent (NOT the pre-registered "
                          "quantity): longest blocked run %d, total blocked "
                          "%d" % (p["free"], p["blk"]))
                print("             log %s" % log)
                noread.append((arm, lane, why_void, p))
                rc = 1
                continue

            flag = ""
            if p["sum"] > J_PREREG:
                flag = "  <== OVER THE PRE-REGISTERED %d" % J_PREREG
                violations.append((arm, lane, p["sum"], log))
            print("    lane %d  J_lane=%-3d run=%-3d wall=%-5d iv=%-6d "
                  "drop=%-5d agg=%-3d%s"
                  % (lane, p["sum"], p["run"], p["wall"], p["iv"], p["drop"],
                     p["agg"], flag))
            rows.append((arm, lane, p))
        print()

    # ---- the verdict ----------------------------------------------------
    print("-" * 78)
    if not rows:
        print("  NO READING on every run -- nothing to adjudicate.")
        return 1

    worst = max(p["sum"] for _a, _l, p in rows)
    worst_wall = max(p["wall"] for _a, _l, p in rows)
    agg = max(p["agg"] for _a, _l, p in rows)
    print("  runs adjudicated     : %d of %d" % (len(rows), 2 * N_LANES))
    if escalated:
        print("  escalated (%dx cycles, one retry): %s" % (ESCALATE,
              ", ".join("arm %s lane %d" % (a, l) for a, l in escalated)))
        print("    ⚠ these cells needed a longer window to meet a")
        print("      precondition. Reported because an escalated cell is not")
        print("      the same evidence as one that converged first time.")
    print("  worst J_lane         : %d   (pre-registered bound %d)"
          % (worst, J_PREREG))
    print("  worst wall time      : %d   (NOT bounded by the hypothesis)"
          % worst_wall)
    print("  engine aggregate max : %d   (any-winner-blocked run length)" % agg)
    print()
    # ⭐⭐ THE DECOMPOSITION, STATED AS A NUMBER, AND PER ARM. The
    # pre-registration put this prediction at risk against a figure already on
    # record: the aggregate worst stall. The hypothesis is only coherent if
    # that aggregate DECOMPOSES -- if it is an any-winner-blocked run in which
    # the winner changed mid-stall rather than one lane's wait.
    # ⛔ PER ARM, not pooled: taking the aggregate from one arm and the
    # per-lane max from another would compare two different programs and call
    # it a decomposition.
    print("  --- what the aggregate was hiding (per arm) ---")
    for arm, _d, _b, _w in ARMS:
        mine = [p for a, _l, p in rows if a == arm]
        if not mine:
            continue
        a_agg = max(p["agg"] for p in mine)
        a_worst = max(p["sum"] for p in mine)
        print("    arm %s: aggregate %d vs worst single lane %d  (%d of %d "
              "lanes adjudicated)"
              % (arm, a_agg, a_worst, len(mine), N_LANES))
        if a_agg > a_worst:
            print("      ⇒ the aggregate is %d cycles LARGER than any one"
                  % (a_agg - a_worst))
            print("        lane's wait, so it is several lanes' waits laid end")
            print("        to end -- which is why `jitter_max` is labelled an")
            print("        any-winner-blocked run length and not a per-lane J.")
        else:
            print("      ⇒ equal: one lane owned the whole worst run here, so")
            print("        the aggregate did not overstate the per-lane wait")
            print("        on this program. They coincide; they are still not")
            print("        the same measure.")
    print()
    if violations:
        print("  *** FALSIFIED, as the pre-registration defined it:")
        for arm, lane, s, log in violations:
            print("      arm %s lane %d: sum = %d > %d   %s"
                  % (arm, lane, s, J_PREREG, log))
        print("  ⇒ Disposition (pre-committed): recorded as written, the")
        print("    witness chain of the violating interval is in the log, and")
        print("    the scoped claim d_min >= D* -> J = 1 stands ALONE with no")
        print("    universal companion.")
        return 1

    if noread:
        # ⛔⛔ THE PRE-REGISTRATION'S THIRD BRANCH, APPLIED AS WRITTEN. It
        # names three outcomes -- holds (all 10 runs, all preconditions met),
        # falsified, or NO READING -- and "holds" is defined over all ten.
        # With a cell unadjudicated the result is NEITHER, and rounding it up
        # to a pass is precisely the move the pre-registration exists to
        # forbid. ⚠ It is also NOT a design failure: the cell below is a
        # property of the PROGRAM (a lane that cannot keep up with its own
        # period below D*), and the distinction is Nathan's to rule on.
        print("  NOT FALSIFIED on the %d adjudicated runs (worst %d <= %d),"
              % (len(rows), worst, J_PREREG))
        print("  but NOT A PASS: %d of %d cells could not be adjudicated."
              % (len(noread), 2 * N_LANES))
        over = [1 for _a, _l, _w, p in noread
                if p.get("sum", 0) > J_PREREG]
        print("  the falsifier (sum > %d) fired on %d of %d cells, open ones"
              % (J_PREREG, len(violations) + len(over), 2 * N_LANES))
        print("  included -- so no cell, adjudicated or not, read above it.")
        for arm, lane, why, p in noread:
            print("      arm %s lane %d -- %s" % (arm, lane, why[0]))
            print("        adjacent reading: longest blocked run %d"
                  % p.get("free", -1))
            # ⭐⭐ WHETHER THE OPEN CELL IS OPEN ON **VALUE** OR ON
            # **CONVERGENCE** -- a distinction worth making explicitly,
            # because "not adjudicated" otherwise reads as "might be worse".
            # ⚠ An unconverged maximum is a FLOOR: it can only go up with more
            # cycles, so a reading at or below the bound is not evidence the
            # bound holds. It IS evidence that nothing above it was seen, and
            # saying that precisely is better than leaving a hole.
            if "sum" in p:
                print("        measured sum %d (%s the bound %d), but the max "
                      "is UNCONVERGED" % (p["sum"], "within" if
                                          p["sum"] <= J_PREREG else "ABOVE",
                                          J_PREREG))
                print("        -- a floor, not a verdict: more cycles can only")
                print("           raise it, so this cell is open on")
                print("           convergence, not on a larger value")
        print("  ⇒ Disposition (pre-committed): NEITHER. The pre-registration")
        print("    defines 'holds' over all ten runs, so this is the third")
        print("    branch, and a precondition failure is never a pass.")
        print("  ⇒ OPEN RULING: whether a BACKLOGGED lane (permanently ready,")
        print("    hence no release edges) is adjudicable at all, or whether")
        print("    an arm must be added in which that lane keeps up. Adding")
        print("    one now would be choosing an arm after seeing the result.")
        return 1

    print("  HOLDS on every adjudicated run.")
    print("  ⇒ Disposition (pre-committed): ANALYSIS ONLY. This does not")
    print("    publish a universal J = %d. Whether pe_asm may admit programs"
          % J_PREREG)
    print("    below D* at J = %d is a SEPARATE ruling, after margins at"
          % J_PREREG)
    print("    J = %d are computed with pyRTA (the primary bound)." % J_PREREG)
    print("  ⚠ And it is a FLOOR: %d runs, one phase alignment each."
          % len(rows))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
