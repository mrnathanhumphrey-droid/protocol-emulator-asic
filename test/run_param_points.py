"""PARAMETER-POINT SWEEP -- every bench at every supported parameter value.

THE RULE (Wilson, ruling 4): the suite runs `tb_smoke`, `tb_edge`, `tb_jlane`,
`tb_witness` and the cocotb benches at **both** `SPL` values, and at any other
contract-variable parameter a bench can elaborate.

⛔⛔ WHY, AND WHY IT IS THE GENERIC DETECTOR. Four benches kept a private copy
of the engine's head-slot index (`ln*2 + (l_sel[ln] ? 1 : 0)`). Every copy
silently assumed `SPL = 2`, and **every one of them broke the moment `SPL = 1`
existed** -- including one that had already measured and published a column
that then had to be retracted. The copies were found one at a time, by
inspection, over several hours.

⇒ A hidden constant in a bench fails as soon as the parameter it silently
  assumes becomes variable. So the parameter is MADE to vary, and the failure
  is structural rather than something to be noticed.

⚠ WHAT A PASS HERE MEANS. It means no bench's behaviour depends on a parameter
value it was not told about. It does NOT mean both configurations are equally
good: `test/run_spl_compare.py` is the measurement, and the answer there is
that the double buffer is what makes the published claim true. A bench passing
at SPL = 1 says the bench is honest, not that SPL = 1 is shippable.

⚠ AND IT IS NOT A SUBSTITUTE FOR `model/gate_bench_indices.py`, which forbids
the pattern structurally. This sweep catches a hidden assumption only if some
assertion actually depends on it; the guard catches the expression whether or
not anything looks.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRATCH = os.environ.get("PE_SCRATCH",
                         os.path.join(os.environ.get("TEMP", "/tmp"), "pe_pp"))

SRCS = ["src/pe_engine.v", "src/pe_store.v", "src/project.v"]

# ⭐ THE SUPPORTED POINTS OF EVERY CONTRACT-VARIABLE PARAMETER A BENCH CAN
# ELABORATE. Today that is `SPL`. ⛔ Other parameters in the contract (`AW`,
# `N_LANES`, `N_PINS`, `MEM_TYPE`) are NOT swept here, and the reason is
# recorded rather than left as an omission: the benches hard-code lane counts,
# pin assignments and image layouts, so a second value would fail for reasons
# that are about the bench's fixtures and not about a hidden assumption. `AW`
# already has its own static-assertion check in `yosys_check.sh` (AW = 4 must
# fail elaboration with a diagnostic). Adding a point here requires the
# fixtures to be parametric first.
POINTS = {"SPL": [2, 1]}

# ⛔⛔ EXPECTATIONS ARE DECLARED PER POINT, WITH A REASON -- NOT ALLOWLISTED.
# A bench can legitimately fail at a non-shipped parameter point because the
# DESIGN differs there, and that is a different thing from a bench carrying a
# hidden assumption. Both show up red, so the difference has to be written
# down. ⭐ AND A DECLARATION IS CHECKED IN BOTH DIRECTIONS: if a declared
# failure starts PASSING, this gate goes red too, because the reason has gone
# stale. An allowlist that only suppresses is how a real finding gets absorbed.
#
# (top, bench file, plusargs, pass-line, {SPL: "ok" | (why it fails)})
BENCHES = [
    ("tb_smoke", "test/tb_smoke.v", [], "SMOKE: PASS",
     {2: "ok", 1: "ok"}),

    ("tb_edge", "test/tb_edge.v", [], "tb_edge: PASS",
     {2: "ok",
      # ⭐⭐ A REAL DESIGN CONSEQUENCE OF SPL = 1, FOUND BY THIS SWEEP ON ITS
      # FIRST RUN -- not a bench assumption. Must-fire 5b is the no-op
      # half-bit differential: two programs whose no-op delays differ by 12
      # must land 12 cycles apart.
      #   SPL = 2 : half=7 -> 13 cycles, half=19 -> 25, difference 12 = 12 ok
      #   SPL = 1 : half=7 -> 16 cycles, half=19 -> 25, difference 9  != 12
      # The SHORT delay lands 3 cycles late and the long one is unaffected:
      # the half=7 action is dispatched while its own refill is still in
      # flight and pays the stall, while half=19 has time for the refill to
      # land. ⇒ AT SINGLE-BUFFER DEPTH A PROGRAMMED DELAY SHORTER THAN THE
      # REFILL LATENCY DOES NOT REACH THE PIN FAITHFULLY, and the no-op is
      # precisely the sub-bit timing idiom. So SPL = 1 breaks a RULED
      # mechanism, not merely a jitter figure -- independent evidence for
      # keeping the double buffer, beyond the stall cliff.
      1: "must-fire 5b: the no-op half-bit differential reads 9 against a "
         "programmed 12, because the short delay pays a refill stall the long "
         "one does not. A ruled mechanism, broken at this depth."}),

    # ⚠ tb_witness and tb_jlane are INSTRUMENTS, not pass/fail benches: they
    # print measurements. What is checked here is that they elaborate and
    # satisfy THEIR OWN preconditions at both points -- an instrument that
    # silently reads the wrong slot is exactly defects 1 and 3, and at SPL = 1
    # the private index made tb_jlane report 1870 against a bound of 9.
    ("tb_witness", "test/tb_witness.v",
     ["+IMG=test/probe_pp.hex", "+NBYTES=75", "+NCYC=30000"],
     "witness done", {2: "ok", 1: "ok"}),

    # ⛔ ARM C AND A LONG ENOUGH RUN, because tb_jlane's preconditions are part
    # of what is being checked. My first attempt pointed it at the sub-D*
    # arm A image for 60k cycles, so the window and stationarity
    # preconditions failed BY CONSTRUCTION and both points read red -- the
    # instrument refusing an unvalidatable number, reported as a defect. Arm C
    # is the stationary arm and 200k clears the 100k window floor.
    ("tb_jlane", "test/tb_jlane.v",
     ["+IMG=test/probe_pp_c.hex", "+NBYTES=75", "+LANE=0", "+NCYC=200000",
      "+WARMUP=20000"],
     "consistency:", {2: "ok", 1: "ok"}),

    # ⭐ T5.1 -- THE ONLY BENCH THAT CARRIES HOST PAYLOAD, so it is the only
    # one in which the TX queue tag can be wrong. It is here because the four
    # private slot-index copies were all found ONE AT A TIME, and the lesson
    # recorded then was that a new bench joins the sweep when it is written,
    # not after it has produced a wrong number at the other depth.
    # ⚠ AND IT EARNED ITS PLACE IMMEDIATELY, though not against the design:
    # run at SPL = 1 it reported ONE unexplained pin event out of 847 while
    # SPL = 2 reported none. The ownership result was identical at both
    # depths, so a denominator that moved with a parameter that cannot affect
    # it was the tell -- a drive in the final cycles was counted as scored
    # before its lag window could resolve. The bench now counts an event only
    # when it resolves. A bench defect, found by varying a parameter.
    ("tb_tx", "test/tb_tx.v",
     ["+IMG=test/probe_pp_tx.hex", "+NCYC=6000"],
     "tb_tx: PASS", {2: "ok", 1: "ok"}),

    # ⭐ THE HALF-DUPLEX BENCH, in the sweep from the day it was written. It is
    # the only bench where TX and RX live on ONE lane, so it is the only one
    # that can see a direction corrupting the other -- and a depth-dependent
    # version of that would be invisible everywhere else.
    ("tb_half", "test/tb_half.v",
     ["+IMG=test/probe_pp_half.hex", "+NCYC=40000"],
     "tb_half: PASS", {2: "ok", 1: "ok"}),

    # ⭐ THE SERIAL-LINK BENCH, in the sweep from the day it was written. The
    # link is downstream of the engine, so SPL should not reach it at all --
    # which is exactly why it belongs here: "should not" is a prediction.
    # ⚠ A SHORTER RUN THAN `run_rxbw.py` uses. The sweep is checking that the
    # bench is honest at both depths, not re-measuring the capacity, and the
    # 50-clock slot is visible within a few thousand cycles.
    ("tb_rxbw", "test/tb_rxbw.v",
     ["+IMG=test/probe_pp_rx.hex", "+NCYC=20000"],
     "tb_rxbw: PASS", {2: "ok", 1: "ok"}),

    # ⭐⭐ THE STATUS-BIT BENCH, in the sweep from the day it was written --
    # this file's own rule, two entries above: "a new bench joins the sweep
    # when it is written, not after it has produced a wrong number at the
    # other depth." It was added to `benchset.py` first, and adding it to only
    # one of two bench lists is precisely the drift both lists exist to avoid.
    # ⚠ `MODE=0` (STARVE) is the arm swept. It is the one that depends on the
    # engine reaching a SHIFT's byte-load point, which is where the action
    # slots live, so it is the arm a depth change could plausibly reach; the
    # OVERRUN arm never dispatches at all.
    ("tb_status", "test/tb_status.v",
     ["+IMG=test/tx_image.hex", "+NBYTES=87", "+NCYC=20000", "+MODE=0"],
     "tb_status: PASS", {2: "ok", 1: "ok"}),

    # ⭐ THE OUT-OF-RANGE PIN BENCH, swept on the RESERVED-INDEX arm. That is
    # the arm that DISPATCHES -- the refusal arm never gets past the loader --
    # so it is the one where an action-slot depth could reach the pin-write
    # guards it is checking.
    ("tb_pinrange", "test/tb_pinrange.v",
     ["+IMG=test/pinnone_image.hex", "+NBYTES=54", "+NCYC=8000", "+MODE=1"],
     "tb_pinrange: PASS", {2: "ok", 1: "ok"}),
]


def run(cmd, cwd=ROOT, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=cwd, env=e)


def verdict(passed, want_ok, note=""):
    """(cell text, is_an_error) for one (bench, point).

    ⛔ FOUR COMBINATIONS, AND TWO OF THEM ARE ERRORS -- including the one an
    allowlist would silently swallow: a DECLARED FAILURE THAT STARTS PASSING.
    A reason that has gone stale is how a real change gets absorbed into a
    suppression list, so it is red in both directions.
    """
    if passed and want_ok:
        return "ok", False
    if not passed and not want_ok:
        return "fails AS DECLARED", False
    if passed and not want_ok:
        return "*** PASSES, declared FAIL", True
    return "*** %s (undeclared)" % (note or "failed"), True


def selftest() -> int:
    """⛔ PRICE THE DECLARATION LOGIC (standing rule 3) without re-running any
    bench -- the expensive part is the simulation, and the thing that can be
    wrong is this four-way decision."""
    rc = 0
    cases = (
        (True,  True,  False, "a bench that passes where ok is declared"),
        (False, False, False, "a bench that fails where a reason is declared"),
        (True,  False, True,  "a DECLARED FAILURE THAT STARTED PASSING"),
        (False, True,  True,  "an undeclared failure"),
    )
    print("  --- must-fire: the declaration is checked in both directions ---")
    for passed, want_ok, want_err, name in cases:
        cell, err = verdict(passed, want_ok, "assertion failed")
        ok = (err == want_err)
        print("    %-46s %s" % (name, "%s%s" % (
            "red" if err else "green",
            "" if ok else "  *** WRONG, wanted %s" % (
                "red" if want_err else "green"))))
        if not ok:
            rc = 1
    return rc


def main() -> int:
    rc = 0
    if "--selftest" in sys.argv:
        return selftest()
    print()
    print("=" * 78)
    print("PARAMETER-POINT SWEEP -- every bench at every supported value")
    print("=" * 78)
    for p, vals in POINTS.items():
        print("  %s : %s" % (p, vals))
    print()
    os.makedirs(SCRATCH, exist_ok=True)

    # the instruments need images; probe-named, per standing rule 6
    for delays, base in (([12, 13, 14, 15, 16], "probe_pp"),
                         ([8, 100, 100, 100, 100], "probe_pp_c")):
        g = run([sys.executable, os.path.join(HERE, "make_smoke_image.py"),
                 "--five"] + [str(x) for x in delays] + [base])
        if g.returncode != 0:
            print("  *** could not build test/%s.hex" % base)
            return 1
    # ⛔ tb_tx NEEDS THE TWO-TX-LANE PROGRAM, and it gets a PROBE COPY rather
    # than the committed `tx_image.hex`: standing rule 6, and also so this
    # sweep cannot pass or fail on how stale a tracked artefact happens to be.
    # `--tx` writes one fixed name, so the copy is made here.
    g = run([sys.executable, os.path.join(HERE, "make_smoke_image.py"),
             "--tx", "12", "13"])
    if g.returncode != 0:
        print("  *** could not build the tb_tx image")
        return 1
    shutil.copyfile(os.path.join(HERE, "tx_image.hex"),
                    os.path.join(HERE, "probe_pp_tx.hex"))
    with open(os.path.join(HERE, "probe_pp_tx.hex"), encoding="ascii") as fh:
        nb_tx = len([w for w in fh.read().split() if w])
    # ⛔ NBYTES COUNTED FROM THE FILE. tb_tx REFUSES to run without it, and a
    # literal would go stale the moment the program grew an action.
    for i, (top, _src, args, _needle, _exp) in enumerate(BENCHES):
        if top == "tb_tx":
            args.append("+NBYTES=%d" % nb_tx)
    g = run([sys.executable, os.path.join(HERE, "make_smoke_image.py"),
             "--half", "24"])
    if g.returncode != 0:
        print("  *** could not build the tb_half image")
        return 1
    shutil.copyfile(os.path.join(HERE, "half_image.hex"),
                    os.path.join(HERE, "probe_pp_half.hex"))
    with open(os.path.join(HERE, "probe_pp_half.hex"), encoding="ascii") as fh:
        nb_half = len([w for w in fh.read().split() if w])
    for i, (top, _src, args, _needle, _exp) in enumerate(BENCHES):
        if top == "tb_half":
            args.append("+NBYTES=%d" % nb_half)
    g = run([sys.executable, os.path.join(HERE, "make_smoke_image.py"),
             "--rxfast", "24"])
    if g.returncode != 0:
        print("  *** could not build the tb_rxbw image")
        return 1
    shutil.copyfile(os.path.join(HERE, "rxfast_image.hex"),
                    os.path.join(HERE, "probe_pp_rx.hex"))
    with open(os.path.join(HERE, "probe_pp_rx.hex"), encoding="ascii") as fh:
        nb_rx = len([w for w in fh.read().split() if w])
    for i, (top, _src, args, _needle, _exp) in enumerate(BENCHES):
        if top == "tb_rxbw":
            args.append("+NBYTES=%d" % nb_rx)

    declared = []
    print("  %-12s %-24s %-24s" % ("bench", "SPL=2", "SPL=1"))
    for top, src, args, needle, expect in BENCHES:
        cells = {}
        for spl in POINTS["SPL"]:
            vvp = os.path.join(SCRATCH, "%s_spl%d.vvp" % (top, spl))
            b = run(["iverilog", "-g2012", "-o", vvp, "-s", top,
                     "-P%s.SPL_CFG=%d" % (top, spl), src] + SRCS)
            if b.returncode != 0:
                passed, note = False, "BUILD FAILED"
            else:
                r = run(["vvp", vvp] + args)
                txt = r.stdout + r.stderr
                # ⛔ A FAILURE LINE COUNTS EVEN IF THE PASS LINE IS PRESENT:
                # some benches print both when one arm of several fails.
                bad = ("FAILURE" in txt or "*** FAIL" in txt
                       or "*** VOID" in txt)
                passed = (needle in txt) and not bad
                note = ("assertion failed" if bad
                        else "no '%s'" % needle) if not passed else ""
                if not passed:
                    with open(os.path.join(SCRATCH, "%s_spl%d.log"
                                           % (top, spl)),
                              "w", encoding="utf-8") as fh:
                        fh.write(txt)
            want_ok = (expect.get(spl) == "ok")
            cells[spl], err = verdict(passed, want_ok, note)
            if err:
                rc = 1
            elif not want_ok:
                declared.append((top, spl, expect[spl]))
        print("  %-12s %-24s %-24s" % (top, cells[2], cells[1]))

    if declared:
        print()
        print("  --- declared parameter-point differences ---")
        for top, spl, why in declared:
            print("    %s at SPL=%d:" % (top, spl))
            for i in range(0, len(why), 66):
                print("      %s" % why[i:i + 66])

    # ---- cocotb, through the same toplevel CI uses ----------------------
    print()
    print("  --- cocotb (8 tests), through tb.v at both points ---")
    for spl in POINTS["SPL"]:
        r = run([sys.executable, os.path.join(HERE, "run_local.py")],
                env={"PE_SPL": str(spl)})
        txt = r.stdout + r.stderr
        m = re.search(r"TESTS=(\d+) PASS=(\d+) FAIL=(\d+)", txt)
        if m and m.group(3) == "0" and m.group(1) == m.group(2):
            print("    SPL=%d  %s of %s passed" % (spl, m.group(2), m.group(1)))
        else:
            print("    SPL=%d  *** %s" % (spl, m.group(0) if m
                                          else "no cocotb summary"))
            rc = 1
            with open(os.path.join(SCRATCH, "cocotb_spl%d.log" % spl), "w",
                      encoding="utf-8") as fh:
                fh.write(txt)

    print()
    print("=" * 78)
    print("  PARAMETER-POINT SWEEP: %s" % ("PASSED" if rc == 0 else "FAILED"))
    if rc:
        print("    ⚠ A BENCH THAT PASSES AT ONE POINT AND FAILS AT THE OTHER")
        print("      is a bench carrying a hidden assumption about that")
        print("      parameter -- not necessarily an RTL bug. Four such were")
        print("      found by hand before this sweep existed; logs are in")
        print("      %s" % SCRATCH)
    else:
        print("    no bench's behaviour depends on a parameter value it was")
        print("    not told about, at the points swept.")
        print("    ⚠ THIS IS NOT A VERDICT ON SPL = 1 AS A CONFIGURATION.")
        print("      `test/run_spl_compare.py` is the measurement, and it")
        print("      finds the double buffer is what makes the published")
        print("      claim true. A bench passing at SPL = 1 says the BENCH is")
        print("      honest, not that SPL = 1 is shippable.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
