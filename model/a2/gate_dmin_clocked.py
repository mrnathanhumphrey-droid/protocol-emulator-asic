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
    M1  closed_form SHIFT = (2n-1)d                 rc=1  fail-lines=10
    M2  closed_form SHIFTIN drops n*(s+L_SYNC)      rc=1  fail-lines=7
    M3  compose drops the cross-action `+d`         rc=1  fail-lines=1
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
def compose(actions, d=D_PERIOD, stretch=0):
    """Run `actions` on one lane and return `(t_abs, Dispatch)` in order.

    ⛔ `run_action` RESETS `t` TO 0 PER ACTION, so each action's rows are
    offset by the running `t0` and `t0` advances by `retire.t + d`.
    """
    lane = Lane("L0")
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
        t0 = t0 + rets[0].t + d
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


def spacings(rows, cyclic_first=None):
    """Consecutive spacings over the REFILL-BEARING dispatches (the retires)."""
    ts = [t for t, x in rows if x.retire]
    out = [b - a for a, b in zip(ts, ts[1:])]
    # ⭐ THE WRAP-AROUND IS INCLUDED, because these programs are FRAMES that
    # repeat. The gap from the last action's retire to the next frame's first
    # retire is a real inter-refill spacing, and leaving it out would measure a
    # program that runs once.
    if cyclic_first is not None:
        out.append(cyclic_first)
    return out


def all_dispatch_spacings(rows):
    """⛔ THE WRONG DEFINITION, computed so its consequence is measured."""
    ts = [t for t, _x in rows]
    return [b - a for a, b in zip(ts, ts[1:])]


# =========================================================================
# THE SECOND ROUTE -- closed forms from the model's gap rules
# =========================================================================
def closed_form(op, n, d, stretch=0):
    """Retire-to-retire spacing INTO an action of this shape.

    SHIFT: 2n dispatches and `pending` is never armed (only SHIFTIN arms a
    capture), so every gap is `d`; first->retire is `(2n-1)*d` and the
    preceding `+d` makes `2n*d`.

    SHIFTIN: 2n+1 dispatches -- n LOW, n HIGH, one COLL. The gap after each
    HIGH is the park (`stretch + L_SYNC`); the gap after each LOW is `d`.
    first->retire is `n*d + n*(stretch + L_SYNC)`, plus the preceding `d`.
    """
    if op == SHIFT:
        return 2 * n * d
    return (n + 1) * d + n * (stretch + L_SYNC)


# the programs the pre-registered claim names, plus the corpus shapes already
# in the model's own table
CLAIMED = ("FRAM write n=4", "FRAM random read")


def measure(name, actions, d, stretch=0):
    rows = compose(actions, d=d, stretch=stretch)
    first = closed_form(actions[0][0], actions[0][1], d, stretch)
    sp = spacings(rows, cyclic_first=first)
    derived = [closed_form(op, n, d, stretch) for op, n in actions[1:]] + [first]
    naive = all_dispatch_spacings(rows)
    _guard_positive("%s refill-bearing" % name, sp)
    _guard_positive("%s all-dispatch" % name, naive)
    return rows, sp, derived, naive


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
    print("    the smallest clocked action is a 1-bit SHIFT: 2 dispatches,")
    print("    spacing 2d. Every other shape is larger (a SHIFTIN n adds")
    print("    n*L_SYNC on top of (n+1)*d). So for ANY clocked program:")
    print()
    print("          d_min(refill-bearing) >= 2d  >  d")
    print()
    floor_ok = True
    for d in (D_PERIOD, jp.D_MIN_SHIPPED):
        worst = min(closed_form(op, n, d)
                    for op in (SHIFT, SHIFTIN) for n in range(1, 9))
        if worst != 2 * d:
            floor_ok = False
        print("    d = %-4d  tightest over every legal (op, n): %-5d  2d = %d  %s"
              % (d, worst, 2 * d, "ok" if worst == 2 * d else "*** FAIL"))
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
    # 4. MUST-FIRE: the wrong definition must refuse these programs
    # ---------------------------------------------------------------
    print()
    print("  --- 4. must-fire: counting EVERY dispatch must REFUSE them ---")
    print("    ⛔ This is the whole reason §3a exists. If the naive definition")
    print("    happened to admit these programs too, the distinction would be")
    print("    cosmetic and the prereg would have fixed a definition that did")
    print("    not matter. It is not cosmetic, and here is the price:")
    print("    %-22s %-12s %-10s %-8s %s"
          % ("program", "naive d_min", "U", "adm?", "must-fire"))
    fired = 0
    for name in CLAIMED:
        dmin, _pf, _adm, _j, naive_dmin = verdicts[name]
        u = jp.utilisation(naive_dmin)
        adm = jp.admissible(naive_dmin)
        this = not adm
        if this:
            fired += 1
        print("    %-22s %-12d %-10.3f %-8s %s"
              % (name, naive_dmin, u, "yes" if adm else "NO",
                 "fired" if this else "*** DID NOT FIRE"))
    if fired != len(CLAIMED):
        print("    *** MUST-FIRE FAILED: the naive definition did not refuse")
        print("        every claimed program, so this gate is not measuring")
        print("        the thing §3a was written to prevent. A must-fire that")
        print("        does not fire is indistinguishable from one that cannot.")
        rc = 1
    else:
        print("    ⇒ the naive reading refuses BOTH, at U far above 1, over a")
        print("      gap (%d cycles, the L_SYNC park) that makes no port demand"
              % L_SYNC)
        print("      at all. The definition is load-bearing.")

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
