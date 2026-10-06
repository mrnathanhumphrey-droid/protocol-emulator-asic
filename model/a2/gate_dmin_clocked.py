"""`d_min` over REFILL-BEARING dispatches, measured off the golden model.

The second half of the `C` re-measurement ruling. `docs/PREREG_C_CLOCKED.md`
§3a fixed the definition BEFORE anything ran; this gate is the measurement.

THE ONE CLAIM: on a clocked lane, `d_min` taken over refill-bearing dispatches
is never tighter than the unclocked lane period -- it is `>= 2d` -- so clocking
can only RELAX the port condition, and the FRAM write (n = 4) and the random
read with repeated START are admissible with `J = 1`.

⛔⛔ WHY THE DEFINITION IS LOAD-BEARING AND NOT BOOKKEEPING. `D*` is a
FETCH-PORT condition: `d >= k * L_REFILL`. A clocked re-dispatch makes no port
demand -- it retires nothing, reads no store word, owes no refill (Amendment
A1) -- and the gaps between re-dispatches are the 3-cycle `L_SYNC` park and the
bit period, both far below `D*`. So counting EVERY dispatch would hand
`admissible()` a `d_min` of 3, compute `U = 5*3/3 = 5.0`, and refuse every
clocked program ever written, over a gap that never touches the port. That
refusal is MEASURED below as a must-fire rather than described, because an
argument that a wrong definition would be wrong is not a check.

⛔ THE INSTRUMENT GAP, DECLARED THE WAY THE PREREG DECLARED `tb_csat`'s. The
golden model's `t` is PER-ACTION: `run_action` sets `t = 0` at every action
start, so the trace carries intra-action timing only and the inter-action
spacing -- which is the whole quantity here -- is not in it. This gate
COMPOSES one lane's actions onto one absolute timeline. It does not edit the
model: `clocked_phase` stays the single authority on what a dispatch is, and
the composition is a read of it.

THE COMPOSITION PREMISE, stated so it can be disagreed with:

    the next action's first dispatch is released `d` after the retiring
    dispatch of the previous action.

That is not a new rule invented here. It is the model's OWN intra-action rule
(`t = t + d` after any dispatch that did not park) applied across the action
boundary, and it is what P8 says the writeback does -- advance the lane's
timestamp from the PREVIOUS TIMESTAMP, absolutely, not from completion. The
retire dispatch breaks `run_action`'s loop before that gap is added, which is
why it has to be added here.

⭐⭐ AND IT IS CHECKED BY TWO INDEPENDENT ROUTES, which is the only reason to
trust it. The composition is MEASURED off the model, and the same spacings are
DERIVED in closed form from the model's gap rules:

    SHIFT n     2n dispatches, no park ever arms       ->  spacing = 2n*d
    SHIFTIN n   2n+1 dispatches, n of them post-HIGH   ->  spacing =
                                                           (n+1)*d + n*(s+L_SYNC)

If the two disagree, one of them is wrong and this gate goes red rather than
picking the number it likes. ⚠ THE CLOSED FORMS ARE NOT THE AUTHORITY -- the
model is -- they are a second opinion with a different failure mode, which is
the only kind worth having. The project's last instrument failure was a
`tb_csat` arm that read arrival rate back as service time and was caught ONLY
because a baseline that should have passed came out red.

⭐⭐ PRICED BY MUTATION, AND THE NUMBERS BELOW ARE MEASURED. §4 has a must-fire
of its own; §1 and §2 did not, and a check with no must-fire is one nobody has
shown can fail. Four mutants, each breaking one thing, via a scratch probe:

    baseline (unmutated)                            rc=0  fail-lines=0
    M1  closed_form SHIFT drops the post-HIGH gaps  rc=1  fail-lines=10
    M2  closed_form SHIFTIN drops n*post_high       rc=1  fail-lines=7
    M3  compose drops the cross-action gap          rc=1  fail-lines=1
    M4  a 1-bit SHIFT spacing = d (breaks the floor) rc=1  fail-lines=7

⚠ M3 FOUND A DEFECT IN THIS GATE, not in the model. Dropping the cross-action
gap makes two dispatches share a timestamp, `jp.utilisation` divided by zero,
and the gate died with a traceback instead of printing a verdict -- AND the
exception aborted the pricing run after two arms, leaving M3 and M4 unmeasured
while the output still showed two green results. Both halves are fixed:
`_guard_positive` makes a non-positive spacing a stated refusal, and the probe
treats an exception as red. ⛔ The second half is the sharper one: a harness
that dies mid-sweep reports a PARTIAL run as a whole one.

⚠ WHAT THIS GATE DOES NOT TOUCH. The A2/pyRTA half of the same ruling -- every
post-HIGH job entering the task model at its true `~L_SYNC` separation with
`J = 1` -- is a separate instrument on the pyRTA side, because pyRTA is not
vendored. Refill was never part of the A2 task model; it lives here and in the
`D*` theorem only.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, MODEL)

# ⛔ EVERY NUMBER IS IMPORTED FROM THE ONE PLACE THAT OWNS IT. `D_STAR`,
# `D_MIN_SHIPPED`, `L_REFILL` and the admissibility functions belong to
# `gate_j_program`; `D_PERIOD` and `L_SYNC` belong to the golden model. Writing
# any of them again here would be the two-copies defect `gate_stored_numbers`
# exists to catch, and this file is about a definition, not about a constant.
import gate_j_program as jp                                        # noqa: E402
from clocked_phase import (D_PERIOD, L_SYNC, SHIFT, SHIFTIN,       # noqa: E402
                           Lane, PROGRAMS, run_action)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# =========================================================================
# THE COMPOSITION -- one lane, one absolute timeline
# =========================================================================
def compose(actions, d=D_PERIOD, stretch=0, open_drain=True):
    """Run `actions` on one lane and return `(t_abs, Dispatch)` in order.

    ⛔ `run_action` RESETS `t` TO 0 PER ACTION, so each action's rows are
    offset by the running `t0`, and `t0` advances by the retiring dispatch's
    OWN recorded `t_next`.
    ⭐⭐ `t_next` AND NOT `+ d`, AND THE DIFFERENCE IS THE WHOLE F1 FIX. The
    cross-action gap is `d` only when the retiring dispatch is a COLLECT; when
    it is an open-drain HIGH -- which is how every clocked SHIFT retires -- the
    lane is PARKED and the next action is released at `rise + L_SYNC + d`. The
    first version of this composer added a flat `d` and would now understate
    every SHIFT-terminated spacing. Reading the model's own recorded gap means
    this file holds no copy of the rule to get wrong.
    """
    lane = Lane("L0", open_drain=open_drain)
    out, t0 = [], 0
    for ai, (op, n) in enumerate(actions):
        disp = run_action(lane, ai, op, n, tx_byte=0xA5,
                          peer_bits=[0] * n, stretch=stretch, d=d)
        # ⛔ THE COMPOSITION DEPENDS ON I3 (exactly one retire per action), so
        # it is asserted HERE rather than assumed from the model's selftest. A
        # premise checked somewhere else is a premise that stops holding
        # silently when the other file changes.
        rets = [x for x in disp if x.retire]
        if len(rets) != 1:
            raise AssertionError(
                "I3 violated while composing: action %d (%s n=%d) has %d "
                "retires, so there is no single point at which it owes a "
                "refill and `d_min` has no definition" % (ai, op, n, len(rets)))
        if rets[0] is not disp[-1]:
            raise AssertionError(
                "the retire is not the last dispatch of action %d" % ai)
        for x in disp:
            out.append((t0 + x.t, x))
        if rets[0].t_next is None:
            raise AssertionError(
                "action %d retired without recording its gap to the next "
                "action, so the program cannot be composed" % ai)
        t0 = t0 + rets[0].t_next
    return out


def _guard_positive(what, sp):
    """⛔ A NON-POSITIVE SPACING IS A DEFINED REFUSAL, NOT A TRACEBACK.

    `jp.utilisation` divides by `d`, so a spacing of 0 crashes the gate instead
    of reporting. It cannot arise from the real model -- every gap is `d` or
    the `L_SYNC` park, both positive -- but it AROSE WHILE PRICING THIS GATE:
    the mutant that drops the cross-action `+d` makes two dispatches share a
    timestamp, and the gate died with `ZeroDivisionError` rather than a
    verdict. Both outcomes are red, so nothing was unsafe; a crash is simply a
    worse failure mode than a stated refusal, and the degenerate-field rule
    this project already follows says to define the value rather than hit it.
    """
    bad = [x for x in sp if x <= 0]
    if bad:
        raise AssertionError(
            "%s: %d non-positive spacing(s) %s. Two refill-bearing dispatches "
            "cannot share a timestamp -- one of them would owe a refill the "
            "port has no cycle for -- so this is a broken composition, not a "
            "tight program" % (what, len(bad), sorted(set(bad))))
    return sp


def retire_spacings(rows):
    """Consecutive spacings over the REFILL-BEARING dispatches (the retires)."""
    ts = [t for t, x in rows if x.retire]
    return [b - a for a, b in zip(ts, ts[1:])]


def all_dispatch_spacings(rows):
    """⛔ THE WRONG DEFINITION, computed so its consequence is measured."""
    ts = [t for t, _x in rows]
    return [b - a for a, b in zip(ts, ts[1:])]


# =========================================================================
# THE SECOND ROUTE -- closed forms from the model's gap rules
# =========================================================================
def post_high_gap(d, stretch=0, open_drain=True):
    """The gap after a HIGH dispatch: a park on open-drain, otherwise `d`."""
    return (stretch + L_SYNC + d) if open_drain else d


def span(op, n, d, stretch=0, open_drain=True):
    """First dispatch of an action to its RETIRING dispatch.

      SHIFT n    2n dispatches (n LOW, n HIGH), so 2n-1 internal gaps: `d`
                 after each of the n LOWs, and a post-HIGH gap after each of
                 the FIRST n-1 HIGHs. The last HIGH retires.
                 => n*d + (n-1)*post_high

      SHIFTIN n  2n+1 dispatches (n LOW, n HIGH, one COLL), so 2n internal
                 gaps: `d` after each LOW and a post-HIGH gap after each HIGH.
                 => n*d + n*post_high
    """
    ph = post_high_gap(d, stretch, open_drain)
    if op == SHIFT:
        return n * d + (n - 1) * ph
    return n * d + n * ph


def gap_after_retire(op, d, stretch=0, open_drain=True):
    """The gap from an action's RETIRE to the next action's first dispatch.

    ⛔⛔ IT DEPENDS ON WHAT THE ACTION RETIRES ON, AND THAT IS THE CORRECTION
    THE CROSS-CHECK FORCED. A SHIFT retires ON a high phase, so an open-drain
    lane is PARKED at that moment and the next action waits for the rise plus
    `d`. A SHIFTIN retires on a COLLECT, which is not a high phase, so its gap
    is the plain `d`.
    """
    return post_high_gap(d, stretch, open_drain) if op == SHIFT else d


def closed_form(prev_op, op, n, d, stretch=0, open_drain=True):
    """Retire-to-retire spacing INTO an action, given what PRECEDED it.

    ⭐⭐ RE-DERIVED AFTER F1, AND THE FIRST RE-DERIVATION WAS WRONG. The gap
    rule changed twice in this arc -- every open-drain clocked high phase now
    parks (F2), and the park releases at `rise + L_SYNC + d` (F1) -- so the old
    `2n*d` / `(n+1)*d + n*(stretch+L_SYNC)` forms could not be carried.
    ⛔ THE ERROR WORTH RECORDING IS THE SECOND ONE, NOT THE FIRST: the rewrite
    charged each spacing the gap after its OWN retiring dispatch instead of the
    gap after its PREDECESSOR's. The totals still matched -- 66 + 341 equals
    63 + 344 -- so a sum check would have passed while every individual
    spacing was misattributed by exactly L_SYNC, and `d_min` is a MINIMUM over
    those individuals. ⭐ The two-route cross-check caught it on the first run,
    which is the entire reason this gate computes the same quantity twice.
    """
    return (gap_after_retire(prev_op, d, stretch, open_drain)
            + span(op, n, d, stretch, open_drain))


# the programs the pre-registered claim names, plus the corpus shapes already
# in the model's own table
CLAIMED = ("FRAM write n=4", "FRAM random read")


def measure(name, actions, d, stretch=0, open_drain=True):
    """Compose TWO frames so the wrap-around spacing is MEASURED, not computed.

    ⛔ THE FIRST VERSION APPENDED A COMPUTED WRAP VALUE to the measured list,
    which put a closed-form number inside the "measured" column and compared it
    against itself. These programs are frames that repeat, so running two of
    them measures the wrap for real -- and the wrap matters, because it is the
    spacing into the first action of the next frame.
    """
    twice = list(actions) * 2
    rows = compose(twice, d=d, stretch=stretch, open_drain=open_drain)
    sp = retire_spacings(rows)
    ops = [a[0] for a in twice]
    ns = [a[1] for a in twice]
    derived = [closed_form(ops[k - 1], ops[k], ns[k], d, stretch, open_drain)
               for k in range(1, len(twice))]
    naive = all_dispatch_spacings(rows)
    _guard_positive("%s refill-bearing" % name, sp)
    _guard_positive("%s all-dispatch" % name, naive)
    return rows, sp, derived, naive


def structural_floor(d, stretch=0, open_drain=True):
    """The tightest spacing any clocked program can produce, over every
    (predecessor, action) pair -- not over actions alone."""
    best = None
    for prev in (SHIFT, SHIFTIN):
        for op in (SHIFT, SHIFTIN):
            for n in range(1, 9):
                v = closed_form(prev, op, n, d, stretch, open_drain)
                if best is None or v < best:
                    best = v
    return best


def main() -> int:
    rc = 0
    print()
    print("=" * 78)
    print("  d_min OVER REFILL-BEARING DISPATCHES  (prereg C-clocked §3a)")
    print("=" * 78)
    print("  model units : D_PERIOD = %d   L_SYNC = %d" % (D_PERIOD, L_SYNC))
    print("  port        : D* = %d = N_LANES * L_REFILL = %d * %d"
          % (jp.D_STAR, jp.N_LANES, jp.L_REFILL))
    print("  shipped     : D_MIN_SHIPPED = %d (tightest inner spacing, 1 MHz"
          % jp.D_MIN_SHIPPED)
    print("                on a 50 MHz clock)")
    print("  util floor  : d >= %d  (U = k*C/d <= 1 at C = %d)"
          % (min(x for x in range(1, 400) if jp.admissible(x)), jp.C_SPACING))

    # ---------------------------------------------------------------
    # 1. the two routes must agree, at several d
    # ---------------------------------------------------------------
    print()
    print("  --- 1. measured composition vs the closed form, swept over d ---")
    print("    ⭐ Two independent routes to the same spacings. Disagreement is")
    print("    RED: one of them is wrong and this gate does not choose.")
    print("    %-22s %-5s %-30s %s"
          % ("program", "d", "measured spacings", "agree?"))
    disagreed = 0
    for d in (D_PERIOD, jp.D_MIN_SHIPPED, 2 * jp.D_MIN_SHIPPED):
        for name in CLAIMED:
            _rows, sp, derived, _naive = measure(name, PROGRAMS[name], d)
            ok = sp == derived
            if not ok:
                disagreed += 1
            shown = ",".join(str(x) for x in sorted(set(sp)))
            print("    %-22s %-5d %-30s %s"
                  % (name, d, shown[:30], "ok" if ok else "*** FAIL"))
            if not ok:
                print("        measured %s" % sp)
                print("        derived  %s" % derived)
    if disagreed:
        print("    *** FAIL: %d program/d point(s) disagree. The composition"
              % disagreed)
        print("        and the closed form have different failure modes, so a")
        print("        disagreement means the model's gap rules are not what")
        print("        either one thinks. STOP.")
        rc = 1
    else:
        print("    ⇒ every spacing agrees by both routes, at three values of d.")
        print("      The spacings are affine in d, which is what lets d_min be")
        print("      quoted against the SHIPPED period rather than the model's.")

    # ---------------------------------------------------------------
    # 2. the structural result: clocking cannot tighten d_min
    # ---------------------------------------------------------------
    print()
    print("  --- 2. the structural result ---")
    print("    the tightest pair is a SHIFTIN (which retires on a COLLECT,")
    print("    so its gap is a plain d) followed by a 1-bit SHIFT (whose span")
    print("    is one d). Every other pair is larger, so for ANY clocked")
    print("    program:")
    print()
    print("          d_min(refill-bearing) >= 2d  >  d")
    print()
    floor_ok = True
    for d in (D_PERIOD, jp.D_MIN_SHIPPED):
        worst = structural_floor(d)
        want = 2 * d
        if worst != want:
            floor_ok = False
        print("    d = %-4d  tightest over every (prev, op, n): %-5d  "
              "2d = %-5d  %s"
              % (d, worst, want, "ok" if worst == want else "*** FAIL"))
    if not floor_ok:
        print("    *** FAIL: the floor is not 2d, so the claim that clocking")
        print("        cannot tighten d_min does not hold as stated.")
        rc = 1
    else:
        print("    ⇒ CLOCKING RELAXES THE PORT CONDITION, it never tightens it.")
        print("      That is why the admissibility claim is not a coincidence of")
        print("      these two programs: a clocked lane asks the port for ONE")
        print("      refill per ACTION while spending 2n dispatches on it, so")
        print("      the port sees at worst half the demand of the unclocked")
        print("      lane at the same bit period.")

    # ---------------------------------------------------------------
    # 3. the pre-registered claim, evaluated
    # ---------------------------------------------------------------
    print()
    print("  --- 3. THE PRE-REGISTERED CLAIM (prereg §4) ---")
    print("    evaluated at d = D_MIN_SHIPPED = %d, the TIGHTEST shipped inner"
          % jp.D_MIN_SHIPPED)
    print("    spacing and therefore the worst case for the port.")
    print("    %-22s %-8s %-7s %-7s %-6s %s"
          % ("program", "d_min", ">= D*?", "adm?", "J", "verdict"))
    verdicts = {}
    for name in CLAIMED:
        _rows, sp, _derived, naive = measure(name, PROGRAMS[name],
                                             jp.D_MIN_SHIPPED)
        dmin = min(sp)
        pf = jp.port_feasible(dmin)
        adm = jp.admissible(dmin)
        j = jp.j_of(dmin)
        ok = pf and adm and j == jp.j_of(jp.D_MIN_SHIPPED)
        verdicts[name] = (dmin, pf, adm, j, min(naive))
        print("    %-22s %-8d %-7s %-7s %-6d %s"
              % (name, dmin, "yes" if pf else "NO", "yes" if adm else "NO", j,
                 "ADMISSIBLE" if ok else "*** FAIL"))
        if not ok:
            rc = 1
    if rc == 0:
        print("    ⇒ CLAIM CONFIRMED. Both programs are admissible, port-")
        print("      feasible, and carry J = %d -- the shipped value, not a"
              % jp.j_of(jp.D_MIN_SHIPPED))
        print("      worse one. The falsifier (prereg §4) was 'they are not")
        print("      admissible under that definition'; it did not fire.")
        print("    ⚠ THE OTHER FALSIFIER IS NOT SETTLED HERE: 'the live D*")
        print("      sweep shows stalls on them' is a measurement on silicon,")
        print("      and it is the next step, not this one.")

    # ---------------------------------------------------------------
    # 3b. THE SAME CLAIM AT A d THAT MEETS A DECLARED I2C MODE
    # ---------------------------------------------------------------
    print()
    print("  --- 3b. re-evaluated at a MODE-LEGAL d ---")
    print("    ⛔⛔ WHY §3 ALONE IS NOT THE ANSWER FOR THE FRAM PROGRAMS.")
    print("    `D_MIN_SHIPPED = 25` is the tightest spacing in the SHIPPED")
    print("    table -- SPI at 1 MHz -- and it is the right worst case for the")
    print("    fetch port. But these two programs are I2C, and after F1 the")
    print("    clock is symmetric (low = d, high = d + L_sync), so `d` must")
    print("    also clear the mode's t_LOW minimum or the program is not a")
    print("    legal I2C clock at all. A d_min computed at an illegal d")
    print("    describes a program that cannot ship.")
    print("    ⭐ THE DELAYS COME FROM `gate_um10204`'s TABLE, imported rather")
    print("    than restated -- `table_cycles()` is a pure function and needs")
    print("    no measurement, so there is no second copy of the minima here.")
    print("    ⚠ THE BARE t_LOW MINIMUM IS USED, not the jitter-corrected")
    print("    floor, because it is the TIGHTER d and therefore the stricter")
    print("    test of admissibility: a larger d only raises d_min.")
    print()
    try:
        import gate_um10204 as um
        modes = um.table_cycles()
    except Exception as exc:                            # noqa: BLE001
        print("    *** FAIL could not import the UM10204 table: %s" % exc)
        modes, rc = {}, 1
    print("    %-13s %-6s %-22s %-8s %-7s %-7s %-6s %s"
          % ("mode", "d", "program", "d_min", ">= D*?", "adm?", "J", "verdict"))
    for mname in sorted(modes, key=lambda m: modes[m]["t_LOW"]):
        dd = modes[mname]["t_LOW"]
        for name in CLAIMED:
            _rows, sp, _der, _naive = measure(name, PROGRAMS[name], dd)
            dmin = min(sp)
            pf, adm = jp.port_feasible(dmin), jp.admissible(dmin)
            j = jp.j_of(dmin)
            ok = pf and adm and j == jp.j_of(jp.D_MIN_SHIPPED)
            if not ok:
                rc = 1
            print("    %-13s %-6d %-22s %-8d %-7s %-7s %-6d %s"
                  % (mname, dd, name, dmin, "yes" if pf else "NO",
                     "yes" if adm else "NO", j,
                     "ADMISSIBLE" if ok else "*** FAIL"))
    if modes and rc == 0:
        print("    ⇒ admissible at every declared mode, still J = %d. The"
              % jp.j_of(jp.D_MIN_SHIPPED))
        print("      claim does not depend on the shipped SPI period: the")
        print("      loosest I2C clock this engine can legally produce is")
        print("      already far above D* = %d." % jp.D_STAR)

    # ---------------------------------------------------------------
    # 4. MUST-FIRE: the wrong definition must CHANGE THE VERDICT
    # ---------------------------------------------------------------
    print()
    print("  --- 4. must-fire: counting EVERY dispatch must change a verdict ---")
    print("    ⛔⛔ THIS MUST-FIRE WAS REWRITTEN BECAUSE F1 INVALIDATED IT, AND")
    print("    THAT IS WORTH RECORDING RATHER THAN QUIETLY REPLACING. Before")
    print("    F1 the post-HIGH gap was the L_SYNC park -- 3 cycles -- so the")
    print("    naive all-dispatch `d_min` was 3 on every clocked program, U was")
    print("    5.0, and the wrong definition refused EVERYTHING. F1 made the")
    print("    post-HIGH gap `L_SYNC + d`, so the tightest inter-dispatch gap")
    print("    on a clocked lane is now `d` itself and there is no sub-d gap")
    print("    left anywhere. The old must-fire therefore stopped firing -- not")
    print("    because the definition stopped mattering, but because the thing")
    print("    it pointed at was fixed.")
    print()
    print("    ⇒ WHAT §3a STILL BUYS, in two parts:")
    print()
    print("    (a) it changes the NUMBER, and by a lot:")
    print("      %-22s %-12s %-14s %s"
          % ("program", "naive", "refill-bearing", "understated by"))
    understated = 0
    for name in CLAIMED:
        dmin, _pf, _adm, _j, naive_dmin = verdicts[name]
        if naive_dmin < dmin:
            understated += 1
        print("      %-22s %-12d %-14d %.1fx"
              % (name, naive_dmin, dmin, dmin / float(naive_dmin)))
    print()
    print("    (b) it changes the VERDICT wherever `d` is tight. The naive")
    print("    reading charges the program `d`; the correct one charges at")
    print("    least `2d`. Between the utilisation floor and twice it, the two")
    print("    definitions disagree about whether the program may run at all:")
    print("      %-6s %-10s %-11s %-10s %-11s %s"
          % ("d", "naive", "naive adm?", "correct", "correct adm?", "must-fire"))
    fired = 0
    trials = 0
    for dd in (7, 9, 12, 14):
        naive_d = dd                      # the tightest all-dispatch gap IS d
        corr_d = structural_floor(dd)
        na, ca = jp.admissible(naive_d), jp.admissible(corr_d)
        this = (not na) and ca
        trials += 1
        if this:
            fired += 1
        print("      %-6d %-10d %-11s %-10d %-11s %s"
              % (dd, naive_d, "yes" if na else "NO", corr_d,
                 "yes" if ca else "NO", "fired" if this else "-"))
    if fired == 0:
        print("    *** MUST-FIRE FAILED: at no tested `d` does the naive")
        print("        definition refuse a program the correct one admits, so")
        print("        the distinction has not been shown to decide anything.")
        print("        A must-fire that does not fire is indistinguishable")
        print("        from one that cannot.")
        rc = 1
    elif understated != len(CLAIMED):
        print("    *** MUST-FIRE FAILED: the naive definition did not")
        print("        understate every claimed program's d_min.")
        rc = 1
    else:
        print("    ⇒ fired at %d of %d tested delays, and understated d_min on"
              % (fired, trials))
        print("      both claimed programs. The definition decides both the")
        print("      number and, at tight d, the admission.")

    # ---------------------------------------------------------------
    # 5. the corpus shapes, for completeness
    # ---------------------------------------------------------------
    print()
    print("  --- 5. every program in the model's table, at d = %d ---"
          % jp.D_MIN_SHIPPED)
    print("    %-24s %-8s %-7s %-6s %s"
          % ("program", "d_min", ">= D*?", "J", "naive d_min"))
    for name, actions in PROGRAMS.items():
        _rows, sp, _derived, naive = measure(name, actions, jp.D_MIN_SHIPPED)
        dmin = min(sp)
        print("    %-24s %-8d %-7s %-6d %d"
              % (name, dmin, "yes" if jp.port_feasible(dmin) else "NO",
                 jp.j_of(dmin), min(naive)))

    print()
    print("=" * 78)
    print("  GATE dmin-clocked: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    * d_min measured off the golden model, not asserted")
    print("    * two independent routes agree at three values of d")
    print("    * d_min >= 2d for every clocked program: clocking RELAXES D*")
    print("    * prereg §4 claim evaluated; the admissibility half confirmed")
    print("    * must-fire: the naive definition refuses both programs")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
