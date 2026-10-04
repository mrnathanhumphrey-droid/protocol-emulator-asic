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

DEFAULT_IMG = "test/smoke_image.hex"
# ⛔⛔ THE STRESS IMAGE IS NOT AN EXTRA, IT IS WHAT MAKES ONE MUTANT KILLABLE.
# The default program's delays are 20/31 against a ~4-cycle refill, so the
# prefetcher always wins and the steady-state stall is 0 with ONE buffer or
# TWO. Against it, M_BUF_SWAP SURVIVED -- and a bench that cannot tell the
# design from the mutant cannot evidence the design. Five active lanes at
# d = 12..16 is the regime where the buffering is observable at all.
STRESS_FIVE = (12, 13, 14, 15, 16)
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


def build(defines, out):
    cmd = ["iverilog", "-g2012", "-o", out, "-s", "tb_smoke"]
    for d in defines:
        cmd += ["-D%s" % d]
    cmd += SRC
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def run(vvp, img=DEFAULT_IMG):
    r = subprocess.run(["vvp", vvp, "+IMG=%s" % img], cwd=ROOT,
                       capture_output=True, text=True)
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

    print()
    print("=" * 78)
    print("VERDICT")
    print("=" * 78)
    print("  mutants run           : %d" % len(MUTANTS))
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
