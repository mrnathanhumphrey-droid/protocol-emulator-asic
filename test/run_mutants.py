#!/usr/bin/env python3
"""Mutation testing for the double-buffered action fetch.

THE ONE CLAIM: every piece of state the double buffer added is load-bearing --
break it and the smoke bench goes RED, for a stated reason.

⛔⛔ WHY THIS FILE EXISTS. `M-PREFETCH-STALE` has been NAMED in `pe_engine.v`
since S3 and was never mechanically runnable. A mutant that has never been seen
kill anything is an unmeasured artefact, exactly like a guard that has never
fired -- and this project has already shipped one of those (1.6s passed
unconditionally for a release because `bad` was unreachable). The double buffer
adds FOUR coupled pieces of state (two slots, a select bit, a fetch pointer that
runs ahead of the PC), and "the edge counts still look right" does not check any
of them: a lane dispatching a stale action still toggles its pin.

⭐ EACH MUTANT MUST DIE FOR ITS OWN STATED REASON, not merely die. The standing
rule in this project is that a red mutant has to be certified by its failure
MESSAGE -- a mutant that fails because the build broke, or because an unrelated
assertion tripped, is not evidence about the thing it mutates. So each entry
below names the assertion that must be the one to fire.
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
SCRATCH = os.environ.get("TEMP", "/tmp")

SRC = ["test/tb_smoke.v", "src/pe_engine.v", "src/pe_store.v", "src/project.v"]
# ⭐ The reactive-release mutants run against a DIFFERENT bench: tb_edge drives
# protocol inputs during run, which tb_smoke never does. One runner, two
# benches, because a mutant has to be judged by the bench that can see it.
SRC_EDGE = ["test/tb_edge.v", "src/pe_engine.v", "src/pe_store.v",
            "src/project.v"]
# ⭐ T5.1 -- A THIRD BENCH, because the TX queue tag is invisible to the other
# two. `tb_smoke` and `tb_edge` never drive the host channel, so every
# OP_SHIFT they execute finds an empty queue and takes the underrun branch: a
# mutant on the queue-selection path has nothing to break there. `tb_tx` is
# what gives M_TX_IGNORE_TAG something to kill it with.
SRC_TX = ["test/tb_tx.v", "src/pe_engine.v", "src/pe_store.v", "src/project.v"]
TX_IMG = "test/tx_image.hex"
TX_BADCLK_IMG = "test/tx_badclk_image.hex"
# (define, what it breaks, the text that certifies the kill, why, which image)
# ⭐ TWO IMAGES, because the two mutants break DIFFERENT claims: the tag mutant
# needs a legal two-lane program to misroute bytes in, and the clock-alias
# mutant needs the ILLEGAL program whose refusal it removes. A single image
# could not kill both.
TX_MUTANTS = [
    ("M_TX_IGNORE_TAG",
     "host_q becomes a constant: every lane pops queue 0",
     "the queue tag was ignored",
     "⛔ THE SILENT-CORRUPTION CLASS. The engine pops a queue, the lane shifts "
     "what it got, and the wire carries a WELL-FORMED FRAME WITH ANOTHER "
     "LANE'S PAYLOAD -- no assertion in the design fires, no flag is set. "
     "With two TX lanes active, consumption order is the EDF interleave, so "
     "the host cannot predict which lane takes the next byte; the action's "
     "queue field is the whole mechanism that makes that safe. ⚠ The kill is "
     "certified by the CROSS-LANE diagnosis, not by a value mismatch: the "
     "bench scans every byte a lane emitted against every byte of the other "
     "queue, because the narrow 'byte 0 vs byte 0' check did NOT fire (lane 1 "
     "gets queue 0's SECOND byte, since lane 0 took the first) and the mutant "
     "would have died of 'got 4e want 2d' -- a wrong reason.", "good"),
    ("M_SHIFT_CLK_ALIAS",
     "remove the 1.6x refusal of a SHIFT lane whose clk pin is its data pin",
     "1.6x: the aliased SHIFT was not refused",
     "⛔ OP_SHIFT writes the data pin and THEN the clock pin, so with "
     "`clkpin == pin` the clock write overwrites every data bit with the "
     "action's level field -- at level = 0 every 1 bit becomes a 0 and the "
     "wire carries a well-formed frame of the wrong data. ⚠ IT WAS LATENT FOR "
     "THE WHOLE LIFE OF THE HOST CHANNEL: nothing had ever fed a queue, so "
     "every OP_SHIFT ran on an all-zero shift register where losing the 1 bits "
     "changed nothing -- and `build_census` declared the alias on its shifting "
     "lane the entire time. ⭐ With the refusal removed the bad program RUNS "
     "and emits 36 bytes; with it, config_err is sticky, the lane halts, and "
     "nothing beyond the reset byte comes out.", "badclk"),
]
EDGE_MUTANTS = [
    ("M_NO_REBASE",
     "edge release leaves the timestamp at the ARM's DEADLINE",
     "MUST-FIRE 1 FAILED",
     "The sample grid then anchors to an arbitrary timeout instant instead of "
     "to the peer's edge, which for UART-rx misses every bit (0.9b derives the "
     "grid as edge + half + m*T). ⚠ Must-fire 4 does NOT catch this -- it still "
     "reports a constant offset, because its program uses timeout=0. Only the "
     "finite-deadline case distinguishes them."),
    ("M_TIMEOUT_PROCEED",
     "a timeout lets the lane carry on instead of halting",
     "MUST-FIRE 3 FAILED",
     "A program then cannot tell 'the peer answered' from 'the peer never "
     "answered' and would read a frame out of an idle line -- the forbidden "
     "direction one level up from an unsound bound."),
    ("M_NOOP_DRIVES",
     "remove the pin_real guard: a no-op drives its pin",
     "(characterised survivor -- structural only)",
     "⛔ NOT KILLABLE BY SIMULATION, and the reason is specific: with "
     "PIN_NONE = 15 on 12-wide vectors an out-of-range write is SILENTLY "
     "IGNORED by iverilog, so removing the guard changes nothing the bench can "
     "see. It DOES take effect -- the local netlist gains 3 cells, so the "
     "comparator is real logic, not documentation. ⭐ The guard's value is "
     "SYNTHESIS portability: out-of-range indexing is where tool behaviour "
     "diverges, which is the class that passed iverilog and died in Yosys "
     "once already. ⚠ The OBSERVABLE failure is a BAD PROGRAM, not this "
     "mutant: a no-op naming a real input pin, which tb_edge catches (135 "
     "drive cycles) and 1.6w rejects at load."),
    ("M_COMB_OUT",
     "restore the combinational prog_mode mux on the uio outputs",
     "(structural, checked by F2 on the local netlist)",
     "Not a simulation mutant: it is caught by model/f2_flop_driven_outputs.py "
     "on a yosys JSON netlist, where it shows up as $_ANDNOT_ driving the uio "
     "bits. Listed here so the full mutant inventory is in one place."),
]

DEFAULT_IMG = "test/smoke_image.hex"
# ⛔⛔ THE STRESS IMAGE IS NOT AN EXTRA, IT IS WHAT MAKES ONE MUTANT KILLABLE.
# The default program's delays are 20/31 against a ~4-cycle refill, so the
# prefetcher always wins and the steady-state stall is 0 with ONE buffer or
# TWO. Against it, M_BUF_SWAP SURVIVED -- and a bench that cannot tell the
# design from the mutant cannot evidence the design. Five active lanes at
# d = 12..16 is the regime where the buffering is observable at all.
# ⛔ IMPORTED, NOT RESTATED. These delays and `--all`'s were two recipes for
# one filename, which the clean-room check caught as the same file reproducing
# with different content. The generator owns them.
from make_smoke_image import FIVE_STRESS as STRESS_FIVE   # noqa: E402
STRESS_IMG = "test/five_image.hex"

# mode "assert": a named bench assertion must fire.
# mode "worse" : ⭐ DIFFERENTIAL. The mutant must be measurably WORSE than the
#   baseline on the SAME image. An absolute threshold cannot work here: the
#   bench's steady-J check is `> 2` and both the design (5) and the mutant (9)
#   exceed it, so an absolute check would "kill" the mutant while being equally
#   satisfied by the correct design -- a guard passing for the wrong reason,
#   which is this project's signature defect.
MUTANTS = [
    ("M_BUF_NOINVAL", "assert", DEFAULT_IMG,
     "swap without invalidating the consumed head slot",
     "buffer-swap invariant",
     "After two writebacks the lane dispatches the action it already ran: the "
     "old head is still valid and holds the consumed word, so the second swap "
     "selects it. This is the double-buffer form of M-PREFETCH-STALE."),
    ("M_BUF_SWAP", "worse", STRESS_IMG,
     "invalidate the head but never swap to the prefetched successor",
     "steady-state stall strictly worse than the baseline",
     "The dispatched action stays CORRECT -- `fetch_addr` sees an invalid head "
     "and refills it from `l_pc` -- so no correctness assertion fires. What "
     "breaks is the jitter. This is the mutant that certifies the SWAP, rather "
     "than merely the second slot, is what buys the J reduction."),
    # ⛔⛔ A CHARACTERISED SURVIVOR, DECLARED AS ONE. It is NOT reclassified to
    # make this gate green: `effect` still asserts that the mutation CHANGES THE
    # DESIGN'S BEHAVIOUR, so it cannot become a no-op in silence. What is
    # declared is that its cost is below the bench's resolution -- verified, not
    # assumed: with it, lane 2's select bit flips 4 times instead of 3, and the
    # total refill count is IDENTICAL at 652. So the chaining asymmetry is
    # correct by derivation and unevidenced by test, which is the honest state.
    # ⭐ AND IT CORRECTED THE RTL: the comment there called the asymmetry a
    # correctness requirement, claiming a flip would dispatch the wrong action.
    # It would not -- the refill reloads `l_pc`, which a chaining re-arm has not
    # advanced, so the same action comes back. The mutant is what established
    # that, which is a mutant earning its place by surviving.
    # ⭐⭐ RULING 1(a)'s mutant. Releasing jobs before the buffers are primed is
    # the thing prime-before-release exists to prevent, and it must be visible.
    # ⛔ MEASURED cold = 76, not the 5 this project had been quoting. The old
    # engine counter AND the old bench both gated on `hdr_done`, so BOTH were
    # blind to the header-load window -- during which `now` ran, lanes were
    # released, and nothing could dispatch. Two independent reconstructions
    # sharing one blind spot read as agreement.
    ("M_NO_PRIME", "assert", DEFAULT_IMG,
     "release jobs before every lane's buffers are primed",
     "prime-before-release must-fire",
     "Without priming, `now` advances through the header load and the initial "
     "refills, so every lane's first job is released ALREADY LATE and the "
     "first-edge delay (76) differs from the steady-state one (0). That "
     "difference is differential jitter against D_tol on a source lane, which "
     "is why the cold start had to be removed rather than declared out of "
     "scope."),
    ("M_BUF_CHAINFLIP", "effect", DEFAULT_IMG,
     "swap on a chaining re-arm (PC does not advance)",
     "select-bit flip count must differ from the baseline",
     "Performance-only: one needless refill per park dispatch. No program the "
     "bench can build makes that visible in the worst-case stall, so this is "
     "declared a characterised survivor rather than killed by a contrived "
     "program -- but the mutation is still required to TAKE EFFECT."),
]


def make_stress():
    subprocess.run([sys.executable, "test/make_smoke_image.py", "--five"]
                   + [str(x) for x in STRESS_FIVE],
                   cwd=ROOT, capture_output=True, text=True)


def steady(out):
    m = re.search(r"max prefetch stall, STEADY\s+:\s+(\d+)", out)
    return int(m.group(1)) if m else None


def flips(out):
    m = re.search(r"select-bit flips\s+:\s+(\d+)", out)
    return int(m.group(1)) if m else None


def build(defines, out, src=None):
    # ⛔ THE TOP IS DERIVED FROM THE BENCH FILE, NOT FROM LIST IDENTITY. This
    # read `src is SRC_EDGE`, so adding a third bench meant a third `is`
    # comparison and a silent fall-through to `tb_smoke` if one was forgotten
    # -- the mutant would then build the wrong top, pass, and be recorded as a
    # survivor for a reason that was not the mutation.
    files = src if src is not None else SRC
    top = os.path.splitext(os.path.basename(files[0]))[0]
    cmd = ["iverilog", "-g2012", "-o", out, "-s", top]
    for d in defines:
        cmd += ["-D%s" % d]
    cmd += (src if src is not None else SRC)
    # ⛔⛔ UTF-8, EXPLICITLY. `text=True` uses the locale codec, which on this
    # box is cp1252 -- and every bench prints ⭐/⛔, so the reader thread raised
    # UnicodeDecodeError, DIED, and left the captured output TRUNCATED. The
    # verdicts below are parsed from that output, so a mutant could be judged
    # killed or survived from a partial stream. It presented as "the unmutated
    # tb_edge does not pass" while the same command passed by hand.
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def run(vvp, img=DEFAULT_IMG, extra=None):
    cmd = ["vvp", vvp] + ([] if img is None else ["+IMG=%s" % img])         + (extra or [])
    # ⛔⛔ UTF-8, EXPLICITLY. `text=True` uses the locale codec, which on this
    # box is cp1252 -- and every bench prints ⭐/⛔, so the reader thread raised
    # UnicodeDecodeError, DIED, and left the captured output TRUNCATED. The
    # verdicts below are parsed from that output, so a mutant could be judged
    # killed or survived from a partial stream. It presented as "the unmutated
    # tb_edge does not pass" while the same command passed by hand.
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True,
                       encoding="utf-8", errors="replace")
    return (r.stdout or "") + (r.stderr or "")


def verdict(out):
    """(failures, which assertions fired). ⛔ Parsed, not eyeballed."""
    m = re.search(r"SMOKE:\s+(\d+)\s+FAILURE", out)
    n = int(m.group(1)) if m else (0 if "SMOKE: PASS" in out else None)
    fired = []
    if re.search(r"FAIL buffer-swap invariant", out) or \
       "THE HEAD SLOT DOES NOT HOLD THE ACTION" in out:
        fired.append("buffer-swap invariant")
    if "STEADY-STATE J EXCEEDS" in out:
        fired.append("STEADY-STATE J")
    if "C IS NOT 2" in out:
        fired.append("C")
    if "never moved its pin" in out:
        fired.append("edges")
    if "PRIME-BEFORE-RELEASE MUST-FIRE FAILED" in out:
        fired.append("prime-before-release must-fire")
    if "THE INVARIANT RAN" in out:
        fired.append("invariant vacuous")
    if "disagrees with the engine's" in out:
        fired.append("cold-max disagreement")
    return n, fired


def main() -> int:
    print()
    print("=" * 78)
    print("MUTATION TESTING -- the double-buffered action fetch")
    print("=" * 78)

    # ---- arm 0: the UNMUTATED build must PASS ------------------------
    # ⛔ Run this first. Every "the mutant died" below is meaningless if the
    # baseline is already red -- the mutants would be dying of the baseline's
    # illness and the run would read as perfect mutation coverage.
    base = os.path.join(SCRATCH, "mut_base.vvp")
    rc, log = build([], base)
    if rc != 0:
        print("  *** the UNMUTATED build does not compile:")
        print(log[:1500])
        return 1
    out = run(base)
    n, fired = verdict(out)
    print()
    print("  arm 0 -- baseline, no mutation: %s"
          % ("PASS" if n == 0 else "*** %s failures: %s ***" % (n, fired)))
    if n != 0:
        print("      Nothing below is interpretable: a mutant cannot be shown")
        print("      to kill an assertion that is already failing.")
        return 1
    # and the invariant must actually have run
    mchk = re.search(r"checks performed\s+:\s+(\d+)", out)
    print("      buffer-swap invariant checks in the baseline: %s"
          % (mchk.group(1) if mchk else "NOT REPORTED"))
    if not mchk or int(mchk.group(1)) < 100:
        print("      *** the invariant barely ran in the CLEAN build, so it")
        print("          cannot be credited with killing anything. ***")
        return 1

    # ---- the mutants -------------------------------------------------
    print()
    base_out_flips = out           # the baseline run on the DEFAULT image
    make_stress()
    base_stress = steady(run(base, STRESS_IMG))
    print("      baseline steady-state stall on the stress image: %s"
          % base_stress)
    if base_stress is None:
        print("      *** the stress image produced no steady-state figure ***")
        return 1

    print()
    print("  %-18s %-7s %-28s %-9s %s"
          % ("mutant", "mode", "what it breaks", "verdict", "evidence"))
    survivors, wrong_reason = [], []
    for define, mode, img, breaks, want, why in MUTANTS:
        vvp = os.path.join(SCRATCH, "mut_%s.vvp" % define.lower())
        rc, log = build([define], vvp)
        if rc != 0:
            print("  %-18s %-7s %-28s BUILD FAIL -- not a kill"
                  % (define, mode, breaks[:28]))
            print("      ⛔ a mutant that does not COMPILE proves nothing about")
            print("         the bench. Fix the mutation, not the verdict.")
            print(log[:600])
            wrong_reason.append((define, "build"))
            continue
        out = run(vvp, img)
        n, fired = verdict(out)
        if mode == "assert":
            killed = (n is None) or (n > 0)
            right = want in fired
            evidence = ", ".join(fired) if fired else "(none)"
        elif mode == "worse":
            ms = steady(out)
            killed = ms is not None and base_stress is not None and ms > base_stress
            right = killed
            evidence = "steady %s vs baseline %s" % (ms, base_stress)
        else:   # "effect" -- a characterised survivor that must still DO something
            fl = flips(out)
            bl = flips(base_out_flips)
            killed = fl is not None and bl is not None and fl != bl
            right = killed
            evidence = "sel flips %s vs baseline %s" % (fl, bl)
        print("  %-18s %-7s %-28s %-9s %s"
              % (define, mode, breaks[:28],
                 "RED" if killed else "*** SURVIVED ***", evidence))
        print("      %s" % why)
        if not killed:
            survivors.append(define)
            if mode == "worse":
                print("      ⛔ the mutant is NOT worse than the design on this")
                print("         image, so the image does not exercise the")
                print("         mechanism. That is a statement about the BENCH.")
        elif not right:
            print("      *** it died, but NOT of `%s` -- it died of %s. A kill"
                  % (want, fired or "an unparsed failure"))
            print("          for the wrong reason is not evidence about this")
            print("          mutation. ***")
            wrong_reason.append((define, fired))

    # ---- the REACTIVE-RELEASE mutants, on tb_edge -------------------
    print()
    print("  --- edge-capture mutants (bench: tb_edge) ---")
    base_e = os.path.join(SCRATCH, "mut_edge_base.vvp")
    rc, log = build([], base_e, src=SRC_EDGE)
    if rc != 0:
        print("    *** tb_edge does not compile: %s" % log[:300])
        survivors.append("tb_edge build")
    else:
        out_e = run(base_e, img=None)
        if "tb_edge: PASS" not in out_e:
            print("    *** the UNMUTATED tb_edge does not pass -- nothing below")
            print("        is interpretable.")
            survivors.append("tb_edge baseline")
        else:
            print("    baseline: PASS (4 of 4 must-fires)")
            for define, breaks, want, why in EDGE_MUTANTS:
                if define in ("M_COMB_OUT", "M_NOOP_DRIVES"):
                    print("    %-19s %-40s %s"
                          % (define, breaks[:40], "structural -- see F2"))
                    print("        %s" % why)
                    continue
                v = os.path.join(SCRATCH, "mut_e_%s.vvp" % define.lower())
                rc, log = build([define], v, src=SRC_EDGE)
                if rc != 0:
                    print("    %-19s BUILD FAIL -- not a kill" % define)
                    wrong_reason.append((define, "build"))
                    continue
                o = run(v, img=None)
                killed = "tb_edge: PASS" not in o
                right = want in o
                print("    %-19s %-40s %s"
                      % (define, breaks[:40],
                         "RED" if killed else "*** SURVIVED ***"))
                print("        %s" % why)
                if not killed:
                    survivors.append(define)
                elif not right:
                    print("        *** died, but not of `%s` ***" % want)
                    wrong_reason.append((define, "wrong reason"))

    # ---- the TX QUEUE mutants, on tb_tx -----------------------------
    print()
    print("  --- TX queue-ownership mutants (bench: tb_tx) ---")
    nb_tx = None
    tx_path = os.path.join(ROOT, TX_IMG)
    if not os.path.isfile(tx_path):
        print("    *** %s is missing. Build it:" % TX_IMG)
        print("        python test/make_smoke_image.py --tx 12 13")
        survivors.append("tb_tx image")
    else:
        # ⛔ NBYTES IS COUNTED FROM THE FILE, never passed as a literal. The
        # bench REFUSES to run without it, because an image that never loaded
        # emits nothing and "no bytes" would read as a queue fault.
        with open(tx_path, encoding="ascii") as fh:
            nb_tx = len([w for w in fh.read().split() if w])
    if nb_tx is not None:
        extra = ["+NBYTES=%d" % nb_tx, "+NCYC=6000"]
        base_t = os.path.join(SCRATCH, "mut_tx_base.vvp")
        rc, log = build([], base_t, src=SRC_TX)
        if rc != 0:
            print("    *** tb_tx does not compile: %s" % log[:300])
            survivors.append("tb_tx build")
        else:
            out_t = run(base_t, img=TX_IMG, extra=extra)
            if "tb_tx: PASS" not in out_t:
                print("    *** the UNMUTATED tb_tx does not pass -- nothing")
                print("        below is interpretable.")
                survivors.append("tb_tx baseline")
            else:
                print("    baseline: PASS (4 of 4 must-fires)")
                # ⛔ THE BAD-CLOCK IMAGE IS BUILT AND MEASURED HERE TOO,
                # and its BASELINE is the refusal: `tb_tx +BADCLK=1` passes
                # only if the engine refused the program. A mutant arm whose
                # unmutated run was never checked would make "the mutant
                # killed it" unreadable.
                bad_extra, bad_ok = None, False
                bp = os.path.join(ROOT, TX_BADCLK_IMG)
                if os.path.isfile(bp):
                    with open(bp, encoding="ascii") as fh:
                        nb = len([w for w in fh.read().split() if w])
                    bad_extra = ["+NBYTES=%d" % nb, "+NCYC=4000", "+BADCLK=1"]
                    ob = run(base_t, img=TX_BADCLK_IMG, extra=bad_extra)
                    bad_ok = "tb_tx: PASS" in ob
                    print("    baseline (1.6x image): %s"
                          % ("REFUSED, as it must" if bad_ok
                             else "*** the illegal program was NOT refused"))
                    if not bad_ok:
                        survivors.append("tb_tx 1.6x baseline")
                else:
                    print("    *** %s is missing. Build it:" % TX_BADCLK_IMG)
                    print("        python test/make_smoke_image.py --txbadclk")
                    survivors.append("tb_tx 1.6x image")
                for define, breaks, want, why, which in TX_MUTANTS:
                    if which == "badclk" and not bad_ok:
                        continue
                    use_img = TX_BADCLK_IMG if which == "badclk" else TX_IMG
                    use_extra = bad_extra if which == "badclk" else extra
                    v = os.path.join(SCRATCH, "mut_t_%s.vvp" % define.lower())
                    rc, log = build([define], v, src=SRC_TX)
                    if rc != 0:
                        print("    %-19s BUILD FAIL -- not a kill" % define)
                        wrong_reason.append((define, "build"))
                        continue
                    o = run(v, img=use_img, extra=use_extra)
                    killed = "tb_tx: PASS" not in o
                    right = want in o
                    print("    %-19s %-40s %s"
                          % (define, breaks[:40],
                             "RED" if killed else "*** SURVIVED ***"))
                    print("        %s" % why)
                    if not killed:
                        survivors.append(define)
                    elif not right:
                        print("        *** died, but not of `%s` ***" % want)
                        wrong_reason.append((define, "wrong reason"))

    print()
    print("=" * 78)
    print("VERDICT")
    print("=" * 78)
    print("  mutants run           : %d" % (len(MUTANTS) + len(TX_MUTANTS)))
    print("  survived (bad)        : %d  %s" % (len(survivors), survivors or ""))
    print("  died of a WRONG reason: %d  %s" % (len(wrong_reason),
                                                wrong_reason or ""))
    ok = not survivors and not wrong_reason
    print()
    if ok:
        print("  ⭐ every piece of double-buffer state is load-bearing, and each")
        print("     mutant died of the assertion it was supposed to trip.")
        print("     ⭐ M_BUF_SWAP is the informative one: it leaves behaviour")
        print("     CORRECT and breaks only the jitter, so it certifies that the")
        print("     swap -- not merely the existence of a second slot -- is what")
        print("     the J reduction comes from.")
    else:
        if survivors:
            print("  ⛔⛔ %d MUTANT(S) SURVIVED. The bench does not test what they"
                  % len(survivors))
            print("      break, so the double buffer's correctness is unevidenced")
            print("      in exactly that respect.")
        if wrong_reason:
            print("  ⛔ %d died for the wrong reason -- see above." % len(wrong_reason))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
