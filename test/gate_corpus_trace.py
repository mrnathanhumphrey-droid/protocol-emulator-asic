"""CORPUS TRACE GATE -- Wilson's BROADEN ruling, checked rather than claimed.

THE ONE CLAIM, per program: the two simulators agree cycle-for-cycle on every
port, AND the program actually moved the ports it was built to move.

⛔⛔ THE SECOND HALF IS THE WHOLE POINT. The first cycle-exact pass was true and
nearly empty: `uio_out` and `uio_oe` were CONSTANT for all 1,500 cycles, so
"the simulators agree" was carried almost entirely by `uo_out`, and the
open-drain bank, the tri-state MISO, the peer-driven inputs and the edge-capture
path contributed nothing. An agreement on a constant is not evidence about the
construct that was supposed to be varying.
⇒ Every program declares which ports it MUST make non-constant, and that
  precondition is asserted against the trace. A program whose `uio_oe` never
  moves cannot count as having exercised open-drain, however green it looks.

⛔ AND THE PRECONDITION IS PER PROGRAM, because under the ruled two-bank map
three of the five lanes CANNOT drive any `uio` pin: UART-tx and SPI-master put
every driven pin on `uo_out`, and UART-rx's only `uio` pin is an input. A
blanket "every program must move uio_oe" would be unsatisfiable for them, and
the obvious fix -- moving the master onto `uio` -- would violate the ruling that
`uio` is for pins that must be able to stop driving.

⚠ WHAT THIS STILL DOES NOT COVER is listed at the end of the run, so a green
result cannot be read as more than it is.
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
sys.path.insert(0, HERE)

import corpus  # noqa: E402
import sim_run                                       # noqa: E402
from toolchain import (banner, tool, tool_or_none,   # noqa: E402  ruling V
                       pinned_ok, PINNED_VERILATOR, PINNED_WSL_VERILATOR)

# ⛔⛔ NO PATH IN THIS FILE NAMES A MACHINE ANY MORE (ruling Q2). It used to
# hardcode `wsl.exe -d Ubuntu`, `/mnt/d/ProtocolEmulator` and `C:\tmp\corpus`,
# so the two-simulator corpus witness could only ever run on the development
# box -- which is one reason it sat outside `ci/run_gates.sh`, and outside it
# nothing noticed it had stopped BUILDING at `7a672b0`. The scratch directory
# is now inside the checkout (`probe_*` is gitignored), and the Verilator half
# runs NATIVELY where `verilator` is on PATH (CI) or through WSL where it is
# not (this box), with every path translated by one function.
TMP = os.environ.get("PE_TRACE_TMP") or os.path.join(ROOT,
                                                     "probe_corpus_trace")
# ⛔⛔ 8000 CYCLES, NOT 1500, AND THE OLD WINDOW HAD STOPPED WITNESSING ANYTHING.
# D5 raised the corpus I2C delay to d = 70, a 146-cycle bit period, so 1500
# cycles was ~10 periods -- LESS THAN ONE START + byte + ACK + STOP. The
# cross-simulator check on the corpus that had just changed saw under one
# transaction. Measured: runtime does not scale with it (66 s at 1500, 66 s at
# 8000), so the longer window costs nothing.
NCYC = int(os.environ.get("PE_TRACE_NCYC", "8000"))

SRC = ["test/tb_trace.v", "test/fram_spi.v", "test/fram_i2c.v",
       "src/pe_engine.v", "src/pe_store.v", "src/project.v"]

COLS = {"cyc": 0, "uo_out": 1, "uio_out": 2, "uio_oe": 3, "uio_in": 4}


def run(cmd, **kw):
    """⛔ EXPLICIT UTF-8. Decoding subprocess output as cp1252 once killed the
    reader thread on a star glyph and the verdicts were parsed from a
    TRUNCATED stream -- a green that was really a short read."""
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=ROOT, **kw)


def iverilog_build(vvp, defines=()):
    cmd = [tool("iverilog"), "-g2012", "-I", "test", "-o", vvp, "-s", "tb_trace"]
    for d in defines:
        cmd += ["-D", d]
    cmd += SRC
    r = run(cmd)
    return r.returncode == 0, (r.stdout + r.stderr)


def feed_args(img):
    """RULING SP1: an image's own host feed (`corpus.FEEDS`) as tb_trace
    plusargs, so a real transaction gets its opcodes. Same in both
    simulators -- a stimulus that differed would make the comparison moot."""
    seq = corpus.FEEDS.get(os.path.basename(img).replace(".hex", ""))
    if not seq:
        return []
    return ["+FEEDN=%d" % len(seq), "+FEED=%s" % "".join("%02x" % b
                                                         for b in seq)]


def iverilog_run(vvp, img, nbytes, peer, out, phase=1, async_arm=0,
                 stayload=0, sclhold=0):
    cmd = sim_run.vvp([vvp, "+IMG=%s" % img, "+NBYTES=%d" % nbytes,
                       "+PEER=%s" % peer, "+OUT=%s" % out, "+NCYC=%d" % NCYC,
                       "+SEED=%d" % phase, "+ASYNC=%d" % async_arm,
                       "+STAYLOAD=%d" % stayload, "+SCLHOLD=%d" % sclhold]
                      + feed_args(img), images=[img])
    r = run(cmd)
    log = r.stdout + r.stderr
    # ⛔ R3: rc 0 and a trace file are true of a run that stopped early; the
    # verdict lines print from `final` either way. Finished, or not ok.
    why = sim_run.trace_incomplete(log, cmd)
    if why:
        return False, log + "\n*** R3: the run did not finish: %s" % why
    return r.returncode == 0, log


# ⛔ PHASES ARE A SEPARATE AXIS FROM THE X-INITIAL SEED. Wilson's item 3 asks
# for peer edges at randomised phases; item 4 for the cross-seed sweep on every
# program. They are different claims: varying the PHASE changes the stimulus
# and must still give cross-simulator agreement, while varying the X-INITIAL
# seed must not change the trace at all. Conflating them made the sweep assert
# that different stimulus yields identical traces.
PHASES = [int(x) for x in os.environ.get("PE_TRACE_PHASES", "1,7,99").split(",")]


def read_trace(path):
    """Returns (header, rows). Strips CR: iverilog runs native on Windows and
    writes CRLF while the other side does not -- a format difference, and it is
    PROVEN one-per-end-of-line in test/two_sim_trace.sh before being removed."""
    with open(path, encoding="ascii") as fh:
        lines = [ln.rstrip("\r\n") for ln in fh]
    hdr = lines[0] if lines and lines[0].startswith("#") else ""
    rows = [ln.split() for ln in lines if ln and not ln.startswith("#")]
    return hdr, rows


def distinct(rows, col):
    return len({r[COLS[col]] for r in rows if len(r) > COLS[col]})


def distinct_bit(rows, col, bit):
    """Distinct values of ONE bit. ⛔ A whole-port check can be satisfied by the
    wrong mechanism -- the bench driving other bits of the same port -- so where
    the claim is about a specific wire the check is about that wire."""
    out = set()
    for r in rows:
        if len(r) > COLS[col]:
            v = r[COLS[col]]
            out.add(v[len(v) - 1 - bit])        # bit 0 is the rightmost
    return len(out)


def precondition(name, rows, expect):
    """[(label, n distinct, required?)] for every port the program's `expect`
    says it must move. THE precondition: the corpus arms and the census
    must-fire both call it (10-22 must-fire audit: the must-fire had its own
    inline `distinct(...) < 2` test)."""
    out = []
    for port in ("uo_out", "uio_out", "uio_oe", "uio_in"):
        if not expect.get(port, False):
            continue
        bp = corpus.BIT_PRECONDITION.get(name)
        if bp and bp[0] == port:
            n = distinct_bit(rows, port, bp[1])
            label = "%s[%d]" % (port, bp[1])
        else:
            n = distinct(rows, port)
            label = port
        out.append((label, n))
    return out


def od_violations(rows, od_pins):
    """D2's INVARIANT: no open-drain pin may ever have oe=1 AND out=1.

    Checked over EVERY cycle of EVERY corpus program, which is the form Wilson
    ruled -- because D2 escaped a suite that tested open-drain on one pin of one
    program. A lane mode honoured on the data pin and ignored on the clock pin
    is invisible to any check that does not sweep both pins across all programs.
    Returns [(cycle, pin, uio_out, uio_oe)].
    """
    bad = []
    for r in rows:
        if len(r) <= COLS["uio_oe"]:
            continue
        oe, ou = r[COLS["uio_oe"]], r[COLS["uio_out"]]
        for p in od_pins:
            if len(oe) <= p or len(ou) <= p:
                continue
            e, o = oe[len(oe) - 1 - p], ou[len(ou) - 1 - p]
            if e == "1" and o == "1":
                bad.append((r[0], p, ou, oe))
    return bad


def _verilator_native():
    """True where the Verilator scripts can run in THIS process's shell."""
    return os.name != "nt" or bool(tool_or_none("verilator"))


def vpath(path):
    """A native path as the Verilator side sees it.

    ⭐ ONE TRANSLATION, used for every path handed to a Verilator script. The
    old file spelled the WSL scratch path out by hand at four call sites and
    the Windows drive path at the others -- two spellings of one directory that
    only agreed on one machine.
    """
    full = os.path.abspath(path)
    if _verilator_native():
        return full.replace("\\", "/")
    drive, rest = os.path.splitdrive(full)
    return "/mnt/%s%s" % (drive[0].lower(), rest.replace("\\", "/"))


class _NoVerilator:
    returncode = 127
    stdout = ("*** NO VERILATOR: not on PATH and no wsl.exe to delegate to, "
              "so the second simulator cannot run -- the comparison is RED, "
              "not skipped.")
    stderr = ""


def vrun(script, *args):
    """Run a Verilator-side script: natively (CI) or through WSL (this box)."""
    sc = os.path.join(ROOT, "test", script)
    if _verilator_native():
        cmd = ["bash", sc]
    elif shutil.which("wsl.exe"):
        # ⛔ RULING V: THE PIN TRAVELS WITH THE CALL. Without it the WSL side
        # resolved a bare `verilator` from its own PATH -- apt's 5.032 on this
        # box -- the same class of defect that ran CI's witness on 5.020. A
        # fixed argv (`env NAME=value`) carries it with no shell to expand.
        cmd = ["wsl.exe", "--", "env",
               "PE_VERILATOR=%s" % PINNED_WSL_VERILATOR, "bash", vpath(sc)]
    else:
        return _NoVerilator()
    r = subprocess.run(cmd + [str(a) for a in args], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    # ⚠ ONLY THE SCRIPT THAT RUNS VERILATOR is held to the banner:
    # `two_sim_trace.sh` compares two trace FILES and runs no simulator.
    if script in VERILATOR_SCRIPTS:
        _pin_check(r.stdout, script)
    return r


VERILATOR_SCRIPTS = {"verilator_trace.sh"}


#: ⛔ RULING V: every Verilator-side run must NAME the pinned release in its
#: banner (`tool_banner verilator`). "The witness CI log must show 5.053" is
#: enforced here, not left to someone reading the log.
PIN_PROBLEMS = []


def pin_problem(out, script):
    """None if `out` carries the pinned Verilator's banner, else why not.
    _pin_check and its must-fire both call this (F8, meta-test 10-24: no
    must-fire planted a bad banner)."""
    lines = [l for l in (out or "").splitlines()
             if l.strip().startswith("tool verilator")]
    if not lines:
        return "%s printed no `tool verilator` banner" % script
    ver = lines[0].split(":", 1)[1].strip().split("  ", 1)
    label = ver[1] if len(ver) > 1 else ""
    if not pinned_ok(label):
        return ("%s ran %r, not the pinned %s"
                % (script, lines[0].strip(), PINNED_VERILATOR))
    return None


def _pin_check(out, script):
    why = pin_problem(out, script)
    if why:
        PIN_PROBLEMS.append(why)


def main() -> int:
    banner("iverilog", "vvp")   # ruling V2: the log names the binary that ran
    os.makedirs(TMP, exist_ok=True)
    print()
    print("=" * 78)
    print("CORPUS TRACE GATE -- broaden the two-sim comparison (Wilson)")
    print("=" * 78)
    print("  programs : %d" % len(corpus.CORPUS))
    print("  cycles   : %d each" % NCYC)
    print("  pin map  : generated, RTL-checked (MISO=%d CS=%d)"
          % (corpus.P_T_MISO, corpus.P_T_CS))
    print()

    # ⛔ F8 (meta-test, 10-24): RULING V's banner check, priced -- no
    # must-fire had ever planted a bad banner.
    print("  --- must-fire: the pinned-Verilator banner (ruling V) ---")
    pin_ok = True
    for what, out, want_bad in (
            ("no banner at all", "built ok\n", True),
            ("an unpinned Verilator (apt's 5.020)",
             "  tool verilator: /usr/bin/verilator  Verilator 5.020 2024-01-01\n",
             True),
            ("the pinned banner (control)",
             "  tool verilator: /opt/v  %s devel rev x\n" % PINNED_VERILATOR,
             False)):
        ok = bool(pin_problem(out, "mf.sh")) == want_bad
        print("    %-44s %s" % (what, ("red  ok" if want_bad else "ok")
                                if ok else "*** WRONG"))
        if not ok:
            pin_ok = False
    vvp = os.path.join(TMP, "tr.vvp")
    ok, log = iverilog_build(vvp)
    if not ok:
        print("  *** iverilog build FAILED")
        print(log[-2000:])
        return 1

    results, failures, opens = [], [], []
    if not pin_ok:
        failures.append(("ruling V must-fire", "the banner check mis-judged a plant"))
    for name in sorted(corpus.CORPUS):
        fn, peer = corpus.CORPUS[name]
        img_bytes, expect = fn()
        img = "test/%s.hex" % name
        # ⛔ RULING M5: load the FILE, all of it. `len(img_bytes)` was the
        # program length (51 for corpus_i2c), which left the rest of the store
        # unwritten -- and the chip now refuses exactly that load.
        nb = len(open(os.path.join(ROOT, img)).read().split())
        iv = os.path.join(TMP, "%s_iv.txt" % name)

        ok, log = iverilog_run(vvp, img, nb, peer, iv)
        if not ok or not os.path.isfile(iv):
            print("  %-15s *** iverilog run FAILED" % name)
            print(log[-800:])
            failures.append((name, "iverilog run"))
            continue

        hdr, rows = read_trace(iv)
        print("  %-15s peer=%-4s %d rows" % (name, peer, len(rows)))

        # ---- THE PRECONDITION -----------------------------------------
        pre_ok = True
        for label, n in precondition(name, rows, expect):
            if n < 2:
                print("      *** %s is CONSTANT (%d value) but this program "
                      "must move it" % (label, n))
                pre_ok = False
            else:
                print("      %-11s %d distinct values  (required)" % (label, n))
        if not pre_ok:
            if name in corpus.OPEN:
                print("      OPEN, with a stated cause:")
                for line in _wrap(corpus.OPEN[name], 62):
                    print("        %s" % line)
                opens.append(name)
            else:
                failures.append((name, "precondition: a required port is "
                                       "constant"))
            continue
        if name in corpus.OPEN:
            print("      ⭐ THIS ARM WAS RECORDED AS OPEN AND ITS PRECONDITION")
            print("         NOW PASSES -- the recorded cause no longer holds.")
            print("         Re-read test/corpus.py OPEN and retire the entry.")
            # ⛔ A STALE EXEMPTION IS A FAILURE, NOT A NOTE. This only printed,
            # so a program could start passing while still listed OPEN and the
            # exemption would sit there excusing nothing, unnoticed -- the hole
            # `DELIBERATE` and `PAD_COLLISION` already close by going red.
            # Found when ruling Q2 brought this gate back from `7a672b0`.
            failures.append((name, "listed OPEN but its precondition now "
                                   "passes -- retire the entry"))

        # ---- D2's INVARIANT: no open-drain pin ever drives a 1 ---------
        odp = expect.get("od_pins", ())
        bad = od_violations(rows, odp)
        if bad:
            print("      *** %d cycle(s) drove a HARD 1 on an open-drain pin %s"
                  % (len(bad), sorted(set(b[1] for b in bad))))
            for c, pn, ou, oe in bad[:3]:
                print("          cyc %s pin %d  uio_out=%s uio_oe=%s"
                      % (c, pn, ou, oe))
            failures.append((name, "open-drain hard 1 on pin(s) %s"
                             % sorted(set(b[1] for b in bad))))
            continue
        print("      od invariant holds on pins %s over %d cycles"
              % (list(odp), len(rows)))

        # ---- X CENSUS --------------------------------------------------
        nx = sum(1 for r in rows if any("x" in f for f in r[1:]))
        if nx:
            print("      ⚠ %d cycle(s) carry X -- the 2-state engine cannot "
                  "reproduce X, so the compare below is not meaningful" % nx)
            failures.append((name, "X on a port (%d cycles)" % nx))
            continue

        # ---- PER PHASE: the 3-seed sweep, then the CROSS-SIM COMPARE ---
        ok_all = True
        for ph in PHASES:
            ivp = os.path.join(TMP, "%s_p%d_iv.txt" % (name, ph))
            o2, lg = iverilog_run(vvp, img, nb, peer, ivp, phase=ph)
            if not o2 or not os.path.isfile(ivp):
                print("      *** phase %d: iverilog run failed" % ph)
                ok_all = False
                break
            od = vpath(os.path.join(TMP, "%s_p%d" % (name, ph)))
            r = vrun("verilator_trace.sh", vpath(ROOT), nb, NCYC, od,
                    img, peer, 0, ph, "", 0, 0, " ".join(feed_args(img)))
            if "SEEDS AGREE" not in r.stdout:
                print("      *** phase %d: seed sweep did NOT agree" % ph)
                print(chr(10).join("        " + x
                                 for x in r.stdout.splitlines()[-10:]))
                ok_all = False
                break
            ivw = vpath(ivp)
            r2 = vrun("two_sim_trace.sh", ivw, "%s/s1.txt" % od)
            if "CYCLE-EXACT" not in r2.stdout:
                print("      *** phase %d: CROSS-SIM DISAGREEMENT" % ph)
                print(chr(10).join("        " + x
                                 for x in r2.stdout.splitlines()[-14:]))
                ok_all = False
                break
            print("      phase %-3d seeds agree + CYCLE-EXACT" % ph)
        if ok_all:
            results.append(name)
        else:
            failures.append((name, "phase sweep"))

    # ---- THE ASYNC-CLEAR ARM -------------------------------------------
    print()
    print("  --- the async-clear arm (Wilson's item 2) ---")
    print("  CS deasserts MID-CYCLE, off both clock edges, at a seeded offset")
    print("  in 1..9 ns. `uio_oe[MISO]` comes from a flop on")
    print("  `always @(posedge clk or posedge cs_deasserted or negedge rst_n)`,")
    print("  a triple-edge async clear -- the construct where the two")
    print("  simulators most plausibly diverge. Clocking CS on an edge would")
    print("  hide it behind the synchronous path.")
    fn, peer = corpus.CORPUS["corpus_sptgt"]
    img_bytes, _ = fn()
    img = "test/corpus_sptgt.hex"
    nb = len(open(os.path.join(ROOT, img)).read().split())   # M5: the whole file
    iv = os.path.join(TMP, "async_iv.txt")
    ok, log = iverilog_run(vvp, img, nb, peer, iv, async_arm=1)
    async_ok = False
    if ok and os.path.isfile(iv):
        _, rows = read_trace(iv)
        moved = distinct(rows, "uio_oe")
        print("  iverilog: %d rows, uio_oe %d distinct values" % (len(rows), moved))
        if moved < 2:
            print("  *** uio_oe CONSTANT -- the arm is VACUOUS: if the lane")
            print("      never asserts the enable, the async clear has nothing")
            print("      to clear and agreement proves nothing.")
            failures.append(("async-clear", "vacuous: uio_oe constant"))
        else:
            od = vpath(os.path.join(TMP, "async"))
            r = vrun("verilator_trace.sh", vpath(ROOT), nb, NCYC, od, img,
                     peer, 1, 1, "", 0, 0, " ".join(feed_args(img)))
            if "SEEDS AGREE" not in r.stdout:
                print("  *** seed sweep disagreed on the async arm")
                failures.append(("async-clear", "cross-seed disagreement"))
            else:
                r2 = vrun("two_sim_trace.sh", vpath(iv), "%s/s1.txt" % od)
                if "CYCLE-EXACT" in r2.stdout:
                    print("  CYCLE-EXACT with CS off-edge: the two simulators")
                    print("  agree on the asynchronous release.")
                    async_ok = True
                else:
                    print("  *** THE TWO SIMULATORS DISAGREE ON THE ASYNC CLEAR.")
                    print("      Per the ruling this is a FINDING to understand")
                    print("      before gate level, not a race to sample around.")
                    print("\n".join("      " + x
                                    for x in r2.stdout.splitlines()[-14:]))
                    failures.append(("async-clear", "cross-sim disagreement"))
    else:
        print("  *** the async arm did not run")
        print(log[-600:])
        failures.append(("async-clear", "run failed"))

    # ---- D2's MUST-FIRES: price the open-drain invariant and the stretch --
    # ⛔⛔ A GUARD NEVER SEEN TO FAIL HAS UNKNOWN STRENGTH, and both of these are
    # new. `M_OD_CLK_PUSHPULL` restores the defect exactly -- the clock pin
    # driven push-pull regardless of the lane's mode -- so:
    #   (a) the cross-program invariant must REPORT violations under it;
    #   (b) a peer holding SCL LOW must come out CLEAN against a released SCL
    #       and CONTENDED (X on the line) against a driven one. That is Wilson's
    #       point made measurable: a stretch against a push-pull high is a SHORT.
    # ⚠ THE PEER-DRIVEN STRETCH ARM CAME OUT VACUOUS and is NOT what runs here.
    # `fram_i2c` stretches per ACK and never ACKs: it needs a START plus a
    # matching device address, which no program can send for the same reason
    # `corpus_spim` is OPEN. All four measurements were identical -- a must-fire
    # that fired on nothing. The bench holds SCL low directly instead, which
    # tests the electrical claim and needs no transaction.
    print()
    print("  --- D2 must-fires: the invariant and the stretch, both priced ---")
    d2_ok = True
    mvvp = os.path.join(TMP, "mut.vvp")
    okb, lg = iverilog_build(mvvp, defines=("M_CK_OD_CLK_DRIVE",))
    if not okb:
        print("  *** the mutant build failed")
        d2_ok = False
    else:
        img = "test/corpus_i2c.hex"
        nb = len(open(os.path.join(ROOT, img)).read().split())
        # (a) the invariant must fire on the mutant
        mi = os.path.join(TMP, "mut_i2c.txt")
        # ⛔ F11 (meta-test, 10-23): the run's ok flag is READ -- both D2 arms
        # threw it away and judged whatever trace was there; a clean arm cut
        # short counts 0 contended cycles and reads as "released"
        okm, logm = iverilog_run(mvvp, img, nb, "i2c", mi)
        if not okm:
            print("  *** D2 (a): the mutant run did not finish: %s" % logm[-200:])
            d2_ok = False
        _, mrows = read_trace(mi)
        mbad = od_violations(mrows, (corpus.P_SCL, corpus.P_SDA))
        print("  (a) invariant on the mutant: %d hard-1 cycle(s)" % len(mbad))
        if not mbad:
            print("      *** DID NOT FIRE -- the invariant would miss the very")
            print("          defect it was written for.")
            d2_ok = False
        else:
            print("      fires, e.g. cyc %s pin %d uio_out=%s uio_oe=%s"
                  % mbad[0])
        # (b) the stretch: clean must be clean, the mutant must contend
        res = {}
        for tag, vv in (("clean", vvp), ("mutant", mvvp)):
            o = os.path.join(TMP, "hold_%s.txt" % tag)
            okh, logh = iverilog_run(vv, img, nb, "i2c", o, sclhold=200)
            if not okh:
                print("  *** D2 (b) %s: the run did not finish: %s"
                      % (tag, logh[-200:]))
                d2_ok = False
            _, rws = read_trace(o)
            win = [r for r in rws if 100 < int(r[0]) <= 300]
            nx = 0
            for r in win:
                v = r[COLS["uio_in"]]
                if v[len(v) - 1 - corpus.P_SCL] not in "01":
                    nx += 1
            res[tag] = nx
            print("  (b) %-6s SCL held low 200 cyc: %d contended (X) cycle(s)"
                  % (tag, nx))
        if res.get("clean") != 0:
            print("      *** the CLEAN arm contends -- SCL is not released")
            d2_ok = False
        if not res.get("mutant"):
            print("      *** the MUTANT does not contend, so this arm does not")
            print("          price the release: a stretch against a driven high")
            print("          must show as a short.")
            d2_ok = False
        if d2_ok:
            print("      ⇒ released SCL takes the hold cleanly; driven SCL")
            print("        shorts against it. The release is priced.")
    if not d2_ok:
        failures.append(("D2 must-fires", "not priced"))

    # ---- D1: THE READBACK STREAM, UNDER THE SEED SWEEP -----------------
    # Wilson's D1 ruling: put the readback into the trace corpus under the seed
    # sweep, because RANDOMISED INIT IS WHAT WOULD HAVE CAUGHT the stale first
    # frame. With `+STAYLOAD=1` the part stays in load mode for the window, so
    # `uo_out[6:4]` carries the framed readback and the compared trace IS the
    # host-visible stream.
    print()
    print("  --- D1: the serial readback stream, 3 seeds + cross-sim ---")
    rb_ok = False
    # ⛔⛔ THE READBACK IMAGE FILLS THE WHOLE STORE, AND THE MEASUREMENT SAYS WHY.
    # The readback pointer increments freely and wraps at 2^AW, so it walks
    # EVERY store address -- and a 51-byte image leaves 205 of them never
    # written. The store is allowlisted UNRESET, so past the image the stream
    # reads uninitialised SRAM and the three init seeds legitimately disagree:
    # MEASURED, 920 to 1380 differing lines from cycle ~2247, exactly where the
    # serial walk passes byte 51. The old 1500-cycle window ended just before
    # that point, so it never saw it.
    # ⇒ Falsified rather than argued: the SAME program padded with zeros to the
    #   full store gives SEEDS AGREE. So this is NOT an unreset engine flop; it
    #   is the store doing what its allowlist entry says.
    # ⭐ PADDING ALSO MAKES THE ARM STRONGER, not merely green: the walk now
    # crosses the pointer's WRAP at 2^AW, a framing edge the short window never
    # reached. The arm's claim is that the readback FRAMING is init-independent
    # -- what the stale first frame would have broken -- and it now holds over
    # the whole store and across the wrap.
    # ⚠ WHAT IT DOES NOT SAY: a host reading back past the bytes it loaded
    # gets uninitialised store contents. That is the store's declared
    # behaviour, not a defect, and it is now written down here.
    # ⭐⭐ RULING M MADE THE PADDING THE IMAGE. Every image is now written
    # whole (`pe_isa.full_store`, the filler word rather than zeros), so this
    # arm runs the TRACKED `corpus_i2c.hex` as it ships; the zero-padding copy
    # it used to build is gone. It REFUSES a short image rather than pad one,
    # so it can never again run something other than what is loaded on a chip.
    src_img = "test/corpus_i2c.hex"
    full = open(os.path.join(ROOT, src_img)).read().split()
    img = src_img
    nb = len(full)
    if nb != (1 << corpus.AW):
        print("  *** %s is %d bytes, not the whole store (%d) -- ruling M"
              % (src_img, nb, 1 << corpus.AW))
        failures.append(("readback", "short image"))
    print("  image: %s, %d bytes (the whole store)" % (src_img, nb))
    ivr = os.path.join(TMP, "readback_iv.txt")
    ok, log = iverilog_run(vvp, img, nb, "none", ivr, stayload=1)
    if ok and os.path.isfile(ivr):
        _, rows = read_trace(ivr)
        npat = len({r[COLS["uo_out"]] for r in rows})
        print("  iverilog: %d rows, %d distinct uo_out patterns" % (len(rows), npat))
        if npat < 2:
            print("  *** the readback stream is CONSTANT -- nothing to compare")
            failures.append(("readback", "stream constant"))
        else:
            od = vpath(os.path.join(TMP, "readback"))
            r = vrun("verilator_trace.sh", vpath(ROOT), nb, NCYC, od, img,
                    "none", 0, 1, "", 1, 0)
            if "SEEDS AGREE" not in r.stdout:
                print("  *** the readback stream DISAGREED ACROSS SEEDS -- a")
                print("      register is read before it is written on this path")
                print(chr(10).join("      " + x
                                   for x in r.stdout.splitlines()[-10:]))
                failures.append(("readback", "cross-seed disagreement"))
            else:
                r2 = vrun("two_sim_trace.sh", vpath(ivr), "%s/s1.txt" % od)
                if "CYCLE-EXACT" in r2.stdout:
                    print("  seeds agree + CYCLE-EXACT: the readback stream is")
                    print("  init-independent, which is what the stale first")
                    print("  frame would have broken.")
                    rb_ok = True
                else:
                    print("  *** cross-sim disagreement on the readback stream")
                    failures.append(("readback", "cross-sim disagreement"))
    else:
        print("  *** the readback arm did not run")
        failures.append(("readback", "run failed"))

    # ---- MUST-FIRE: the precondition has to REJECT the narrow trace ----
    # ⛔⛔ A PRECONDITION NOBODY HAS SEEN FAIL HAS UNKNOWN STRENGTH, and this
    # one exists because of a specific program: the opcode-coverage census,
    # which drives only `UO0..UO3` on the `uo_out` bank. It is the program the
    # first cycle-exact result was measured on, and the whole BROADEN ruling
    # says that result was nearly empty. So the census image is fed to the
    # all-lane expectations: the precondition MUST reject it on `uio_oe`.
    print()
    print("  --- must-fire: the precondition rejects the OLD census image ---")
    mf_ok = False
    cen = "test/census_image.hex"
    cen_bytes = len(open(os.path.join(ROOT, cen)).read().split())
    ivc = os.path.join(TMP, "census_iv.txt")
    ok, log = iverilog_run(vvp, cen, cen_bytes, "all", ivc)
    if ok and os.path.isfile(ivc):
        _, rows = read_trace(ivc)
        # the ALL-LANE expectation: every bank must move
        pre = dict(precondition("census_image", rows,
                                {"uo_out": True, "uio_oe": True}))
        n_oe, n_uo = pre.get("uio_oe", 0), pre.get("uo_out", 0)
        print("  census image: uo_out %d distinct, uio_oe %d distinct"
              % (n_uo, n_oe))
        if n_oe < 2 and n_uo >= 2:
            print("  REJECTED on uio_oe, as it must be: the program moves the")
            print("  uo_out bank and NOTHING on uio. ⇒ the precondition has")
            print("  been seen to fail, on the very trace that motivated it.")
            mf_ok = True
        else:
            print("  *** THE MUST-FIRE DID NOT FIRE. The census image now")
            print("      moves uio_oe (%d values), so this arm no longer" % n_oe)
            print("      prices the precondition and a new witness is needed.")
    else:
        print("  *** the must-fire arm did not run")
    if not mf_ok:
        failures.append(("must-fire", "the precondition was not seen to fail"))

    # ---- RULINGS RX2 / RX5: corpus_all5, LONG and MULTI-SEED ---------------
    # ⛔⛔ SILICON FIX #7 HID FOR TWO REASONS AND THIS ARM ANSWERS BOTH. The
    # push-pull SPI receive consumed bits before their capture whenever a late
    # HIGH shrank the HIGH phase under five-lane contention; that needs a
    # particular INTERLEAVING, so it showed on 3 of 6 seeds at 200k cycles and
    # never at this gate's 8,000 cycles on seed 1. And Layer V-RX's model
    # predicted the losses. So: 200k cycles, seeds 1-6, and the verdict that
    # counts is `rx_e2e` -- the chip's bytes against the WIRE at the clock
    # edges, with no model of capture timing. Must-fire: M_RX_NO_CAPGATE (the
    # capture-pending eligibility gate removed) on seed 1.
    print()
    print("  --- RX2/RX5: corpus_all5, 200k cycles, seeds 1-6 (rx_e2e) ---")
    rx_ok = True
    a5 = os.path.join(ROOT, "test", "corpus_all5.hex")
    nb5 = len(open(a5).read().split())

    def all5(v, seed):
        cmd = sim_run.vvp([v, "+IMG=%s" % a5, "+NBYTES=%d" % nb5,
                           "+PEER=all", "+OUT=%s" % os.path.join(TMP, "rx_all5.txt"),
                           "+NCYC=200000", "+SEED=%d" % seed, "+ASYNC=0",
                           "+STAYLOAD=0", "+SCLHOLD=0", "+SPI_SCK_INV=0"],
                          images=[a5])
        r = run(cmd)
        o = r.stdout + r.stderr
        # ⛔ R4 #11: rx_e2e's verdict prints from `final` after any stop
        why = sim_run.trace_incomplete(o, cmd)
        if why:
            raise SystemExit("*** corpus_all5 seed %d: %s" % (seed, why))
        return o

    for seed in range(1, 7):
        o = all5(vvp, seed)
        line = next((l.strip() for l in o.splitlines() if "rx_e2e" in l
                     and ("ok --" in l or "of" in l)), "rx_e2e: no verdict")
        nf = o.count("*** FAIL")
        good = nf == 0 and "rx_e2e: ok" in o
        print("  seed %d  %-62s %s" % (seed, line[:62], "ok" if good
                                         else "*** %d FAIL line(s)" % nf))
        rx_ok = rx_ok and good
    mvvp = os.path.join(TMP, "tr_rxnocap.vvp")
    bok, blog = iverilog_build(mvvp, ["M_RX_NO_CAPGATE"])
    if not bok:
        print("  *** M_RX_NO_CAPGATE build FAILED: %s" % blog[-300:])
        rx_ok = False
    else:
        o = all5(mvvp, 1)
        bad = [l.strip() for l in o.splitlines()
               if l.startswith("*** FAIL rx_e2e") and " of " in l]
        print("  must-fire M_RX_NO_CAPGATE seed 1: %s" % (
            ("red  ok -- " + bad[0][len("*** FAIL "):]) if bad
            else "*** MUST-FIRE FAILED (rx_e2e silent)"))
        rx_ok = rx_ok and bool(bad)
    # ---- RULING EX1: the capture gate is EXACT, checked at its boundary ----
    # corpus_all5 never asks the gate to decide AT its edge (0 boundary
    # consumes on seeds 1-6), so a gate one cycle late would pass there. An
    # SPI read at d = 4 does: its HIGH lasts 4 cycles, so the LOW is released
    # 2 cycles after the HIGH writeback, exactly when `ppc_n` = 1. Clean: the
    # boundary is used (EX1 prints `boundary consumes (= 1): N`, N > 0);
    # M_RX_CAPGATE_LATE: never (N = 0, no functional failure -- the only
    # trace it leaves); M_RX_CAPGATE_EARLY: EX1 and rx_e2e both fail.
    # ⛔ WILSON (EX1 ruling): the count is PINNED EXACTLY, per image digest --
    # "> 0" would let a drift from 1016 to 900 pass -- and every consume is
    # CLASSIFIED (rx_e2e.vh `EX1 classes`): boundary = dispatched at its first
    # ready cycle (ready -> ST_DRIVE = 3, measured) with the capture still
    # pending; the off-boundary 72 are CONTENTION -- ready before the capture
    # landed, dispatched 2 cycles late because another lane's dispatch went
    # first. Nothing unexplained. An unknown digest is red: re-derive, re-pin.
    import hashlib
    import pe_isa as I
    # ⛔ RE-PINNED (WF2, silicon fix #8): the program sends ONE WREN, not two
    # (the second was a workaround for the reset 0x00), so the image -- and
    # its digest -- changed. Was 43c6dfdeda8f931c: 1088 = 1016 boundary + 72
    # contention, 0 unexplained. Now 1184 = 1111 + 73, 0 unexplained: a
    # shorter loop fits more READs in the same 60k cycles; the classification
    # is unchanged and every must-fire below still fires.
    EX1_PIN = {"726383c7533dfe41": dict(n=1184, boundary=1111, b_unexp=0,
                                        contention=73, late=0, o_unexp=0)}
    d4 = os.path.join(TMP, "spim_d4.hex")
    img4, _ = corpus.build_spi_master(d=4)
    store4 = bytes(I.full_store(bytes(img4)))
    dig4 = hashlib.sha256(store4).hexdigest()[:16]
    with open(d4, "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join("%02x" % b for b in store4) + "\n")

    def spim4(v, extra=()):
        cmd = sim_run.vvp([v, "+IMG=%s" % d4, "+NBYTES=256", "+PEER=spi",
                           "+OUT=%s" % os.path.join(TMP, "rx_d4.txt"), "+NCYC=60000",
                           "+SEED=1", "+ASYNC=0", "+STAYLOAD=0", "+SCLHOLD=0",
                           "+SPI_SCK_INV=0"] + feed_args(os.path.join(ROOT, "test",
                                                                      "corpus_spim.hex"))
                          + list(extra), images=[d4])
        r = run(cmd)
        o = r.stdout + r.stderr
        # ⛔ R4 #11: EX1 / rx_e2e print from `final` after any stop
        why = sim_run.trace_incomplete(o, cmd)
        if why:
            raise SystemExit("*** spim_d4 %s: %s" % (" ".join(extra) or "clean", why))
        m = re.search(r"boundary consumes \(= 1\): (\d+)", o)
        return o, (int(m.group(1)) if m else None)

    o, nb = spim4(vvp)
    mn = re.search(r"EX1: ok -- (\d+) push-pull", o)
    mc = re.search(r"EX1 classes: boundary (\d+) \(\+ (\d+) unexplained\); "
                   r"off-boundary: contention (\d+), late release (\d+) "
                   r"\(\+ (\d+) unexplained\)", o)
    got = None
    if mn and mc:
        got = dict(n=int(mn.group(1)), boundary=int(mc.group(1)),
                   b_unexp=int(mc.group(2)), contention=int(mc.group(3)),
                   late=int(mc.group(4)), o_unexp=int(mc.group(5)))
    want_pin = EX1_PIN.get(dig4)
    ex_ok = (got is not None and got == want_pin and nb == got["boundary"]
             and o.count("*** FAIL") == 0)
    print("  EX1 d=4 clean : image %s  %s" % (dig4, got))
    if want_pin is None:
        print("  *** EX1: image digest %s is not pinned -- the d = 4 image "
              "changed; re-derive and re-pin its counts" % dig4)
    elif not ex_ok:
        print("  *** EX1: expected exactly %s" % want_pin)
    else:
        print("  EX1 d=4 clean : ok -- exact pin; %d boundary, %d contention, "
              "0 unexplained" % (got["boundary"], got["contention"]))
    # ⛔ DL1 (Wilson): a receive that stops PART-WAY must be red, not only one
    # that never completes a byte. Planted: the capture slot is forced off at
    # cycle 20000, after dozens of bytes (rx_e2e.vh `+RX_PLANT_HANG`).
    o, _ = spim4(vvp, ["+RX_PLANT_HANG=20000"])
    mh = re.search(r"EX1: ok -- (\d+) push-pull", o)
    hit = ("PLANTED HANG" in o and "STOPPED with receive work owed" in o
           and mh is not None and int(mh.group(1)) >= 64)
    print("  must-fire %-20s %s" % ("hang @20000 (DL1)", (
        "red  ok -- stopped after %s consumes (%d+ bytes)" % (
            mh.group(1), int(mh.group(1)) // 8)) if hit
        else "*** MUST-FIRE FAILED (a part-way hang passed)"))
    ex_ok = ex_ok and hit
    for mut, want in (("M_RX_CAPGATE_LATE", "late"), ("M_RX_CAPGATE_EARLY", "early")):
        mv = os.path.join(TMP, "tr_%s.vvp" % mut.lower())
        bok, blog = iverilog_build(mv, [mut])
        if not bok:
            print("  *** %s build FAILED" % mut)
            ex_ok = False
            continue
        o, nb = spim4(mv)
        if want == "late":
            hit = nb == 0 and o.count("*** FAIL") == 0
            why = "boundary consumes %s (the edge is never used)" % nb
        else:
            hit = "*** FAIL EX1" in o and "*** FAIL rx_e2e" in o
            why = "EX1 and rx_e2e both fail"
        print("  must-fire %-20s %s" % (mut, ("red  ok -- " + why) if hit
                                         else "*** MUST-FIRE FAILED (%s)" % why))
        ex_ok = ex_ok and hit
    rx_ok = rx_ok and ex_ok
    if not rx_ok:
        failures.append(("rx-e2e", "corpus_all5 multi-seed, EX1, or a must-fire"))

    # ---- RULING V: the Verilator side was the PINNED release, every time ----
    print()
    print("  --- ruling V: every Verilator-side run named the pin ---")
    if PIN_PROBLEMS:
        for p in sorted(set(PIN_PROBLEMS)):
            print("  *** %s" % p)
        failures.append(("verilator pin", "%d run(s) not on %s"
                         % (len(PIN_PROBLEMS), PINNED_VERILATOR)))
    else:
        print("  every run printed `tool verilator` on %s" % PINNED_VERILATOR)

    total = len(corpus.CORPUS) + 4
    passed = (len(results) + (1 if async_ok else 0)
              + (1 if rb_ok else 0) + (1 if d2_ok else 0)
              + (1 if rx_ok else 0))
    print()
    print("=" * 78)
    print("  CORPUS TRACE GATE: %d of %d  (%d open, %d failed)"
          % (passed, total, len(opens), len(failures)))
    for nm, why in failures:
        print("    FAILED %-15s %s" % (nm, why))
    for nm in opens:
        print("    OPEN   %-15s see test/corpus.py OPEN[%r]" % (nm, nm))
    print()
    # ⛔⛔ THIS TEXT USED TO SAY AN OPEN ARM "STAYS RED", and the exit code below
    # has always been `0 if not failures` -- so the prose claimed a strictness
    # the gate never had. Found by reading the exit code against the words when
    # ruling Q2 put this gate in CI. An OPEN arm is a NAMED, REASONED exception
    # in `test/corpus.py OPEN`, the same pattern as `DELIBERATE` and
    # `PAD_COLLISION`; what keeps it honest is that it is counted apart from
    # the passes and that a STALE entry (the program now passes) is a failure.
    print("  ⛔ AN OPEN ARM IS NOT A PASS. It is a NAMED exception with a")
    print("     stated cause in test/corpus.py OPEN, counted apart from the")
    print("     passes so the total cannot be read as coverage it does not")
    print("     have. It does not fail the gate; a STALE entry -- the program")
    print("     now passes while still listed -- does.")
    print()
    print("  ⚠ WHAT THIS STILL DOES NOT ESTABLISH:")
    print("    * ports only -- internal state is not compared, so a divergence")
    print("      that never reaches a pin inside the window is invisible")
    print("    * RTL only -- the gate-level arm is the owed gl_test replacement")
    print("    * the peers are SAME-HAND models of the datasheets, so they")
    print("      witness the DUT's protocol timing, not the real devices'")
    print("    * %d cycles per program, one seed triple, one phase stream"
          % NCYC)
    # ⛔ POSITIVE TOKEN (Wilson): printed ONLY on the success path; the runner
    # (ci/pass_token.py) requires it, so exit 0 without it is red
    print()
    print("  GATE corpus-trace: %s" % ("PASSED" if not failures
                                       else "*** FAILED (%d)" % len(failures)))
    return 0 if not failures else 1


def _wrap(t, w):
    out, cur = [], ""
    for x in str(t).split():
        if cur and len(cur) + 1 + len(x) > w:
            out.append(cur)
            cur = x
        else:
            cur = (cur + " " + x) if cur else x
    if cur:
        out.append(cur)
    return out


if __name__ == "__main__":
    raise SystemExit(main())
