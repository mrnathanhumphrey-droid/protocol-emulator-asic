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

WSL_ROOT = "/mnt/d/ProtocolEmulator"
TMP = os.environ.get("PE_TRACE_TMP", r"C:\tmp\corpus")
WSL_TMP = "/mnt/c/tmp/corpus"
NCYC = int(os.environ.get("PE_TRACE_NCYC", "1500"))

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
    cmd = ["iverilog", "-g2012", "-I", "test", "-o", vvp, "-s", "tb_trace"]
    for d in defines:
        cmd += ["-D", d]
    cmd += SRC
    r = run(cmd)
    return r.returncode == 0, (r.stdout + r.stderr)


def iverilog_run(vvp, img, nbytes, peer, out, phase=1, async_arm=0,
                 stayload=0, sclhold=0):
    r = run(["vvp", vvp, "+IMG=%s" % img, "+NBYTES=%d" % nbytes,
             "+PEER=%s" % peer, "+OUT=%s" % out, "+NCYC=%d" % NCYC,
             "+SEED=%d" % phase, "+ASYNC=%d" % async_arm,
             "+STAYLOAD=%d" % stayload, "+SCLHOLD=%d" % sclhold])
    return r.returncode == 0, (r.stdout + r.stderr)


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


def wsl(script, *args):
    cmd = ["wsl.exe", "-d", "Ubuntu", "--", "bash",
           "%s/test/%s" % (WSL_ROOT, script)] + [str(a) for a in args]
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def main() -> int:
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

    vvp = os.path.join(TMP, "tr.vvp")
    ok, log = iverilog_build(vvp)
    if not ok:
        print("  *** iverilog build FAILED")
        print(log[-2000:])
        return 1

    results, failures, opens = [], [], []
    for name in sorted(corpus.CORPUS):
        fn, peer = corpus.CORPUS[name]
        img_bytes, expect = fn()
        img = "test/%s.hex" % name
        nb = len(img_bytes)
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
        for port in ("uo_out", "uio_out", "uio_oe", "uio_in"):
            want = expect.get(port, False)
            if not want:
                continue
            bp = corpus.BIT_PRECONDITION.get(name)
            if bp and bp[0] == port:
                n = distinct_bit(rows, port, bp[1])
                label = "%s[%d]" % (port, bp[1])
            else:
                n = distinct(rows, port)
                label = port
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
            od = "%s/%s_p%d" % (WSL_TMP, name, ph)
            r = wsl("verilator_trace.sh", WSL_ROOT, nb, NCYC, od,
                    img, peer, 0, ph)
            if "SEEDS AGREE" not in r.stdout:
                print("      *** phase %d: seed sweep did NOT agree" % ph)
                print(chr(10).join("        " + x
                                 for x in r.stdout.splitlines()[-10:]))
                ok_all = False
                break
            ivw = "/mnt/c/tmp/corpus/%s_p%d_iv.txt" % (name, ph)
            r2 = wsl("two_sim_trace.sh", ivw, "%s/s1.txt" % od)
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
    nb = len(img_bytes)
    img = "test/corpus_sptgt.hex"
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
            od = "%s/async" % WSL_TMP
            r = wsl("verilator_trace.sh", WSL_ROOT, nb, NCYC, od, img, peer, 1)
            if "SEEDS AGREE" not in r.stdout:
                print("  *** seed sweep disagreed on the async arm")
                failures.append(("async-clear", "cross-seed disagreement"))
            else:
                r2 = wsl("two_sim_trace.sh",
                         "/mnt/c/tmp/corpus/async_iv.txt", "%s/s1.txt" % od)
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
    okb, lg = iverilog_build(mvvp, defines=("M_OD_CLK_PUSHPULL",))
    if not okb:
        print("  *** the mutant build failed")
        d2_ok = False
    else:
        img = "test/corpus_i2c.hex"
        nb = len(open(os.path.join(ROOT, img)).read().split())
        # (a) the invariant must fire on the mutant
        mi = os.path.join(TMP, "mut_i2c.txt")
        iverilog_run(mvvp, img, nb, "i2c", mi)
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
            iverilog_run(vv, img, nb, "i2c", o, sclhold=200)
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
    img = "test/corpus_i2c.hex"
    nb = len(open(os.path.join(ROOT, img)).read().split())
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
            od = "%s/readback" % WSL_TMP
            r = wsl("verilator_trace.sh", WSL_ROOT, nb, NCYC, od, img,
                    "none", 0, 1, "", 1, 0)
            if "SEEDS AGREE" not in r.stdout:
                print("  *** the readback stream DISAGREED ACROSS SEEDS -- a")
                print("      register is read before it is written on this path")
                print(chr(10).join("      " + x
                                   for x in r.stdout.splitlines()[-10:]))
                failures.append(("readback", "cross-seed disagreement"))
            else:
                r2 = wsl("two_sim_trace.sh",
                         "/mnt/c/tmp/corpus/readback_iv.txt", "%s/s1.txt" % od)
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
        n_oe = distinct(rows, "uio_oe")
        n_uo = distinct(rows, "uo_out")
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

    total = len(corpus.CORPUS) + 3
    passed = (len(results) + (1 if async_ok else 0)
              + (1 if rb_ok else 0) + (1 if d2_ok else 0))
    print()
    print("=" * 78)
    print("  CORPUS TRACE GATE: %d of %d  (%d open, %d failed)"
          % (passed, total, len(opens), len(failures)))
    for nm, why in failures:
        print("    FAILED %-15s %s" % (nm, why))
    for nm in opens:
        print("    OPEN   %-15s see test/corpus.py OPEN[%r]" % (nm, nm))
    print()
    print("  ⛔ AN OPEN ARM IS NOT A PASS. It is counted separately so the")
    print("     total cannot be read as coverage it does not have, and it")
    print("     stays red until the ruling it names lands.")
    print()
    print("  ⚠ WHAT THIS STILL DOES NOT ESTABLISH:")
    print("    * ports only -- internal state is not compared, so a divergence")
    print("      that never reaches a pin inside the window is invisible")
    print("    * RTL only -- the gate-level arm is the owed gl_test replacement")
    print("    * the peers are SAME-HAND models of the datasheets, so they")
    print("      witness the DUT's protocol timing, not the real devices'")
    print("    * %d cycles per program, one seed triple, one phase stream"
          % NCYC)
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
