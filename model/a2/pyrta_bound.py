"""THE pyRTA BOUND -- one implementation, because it is now the PRIMARY number.

Ruling 2: pyRTA's bound is published; our recurrence becomes the independent
cross-check in the safe direction.

⛔⛔ WHY THIS FILE HAD TO EXIST THE MOMENT pyRTA BECAME PRIMARY. Four gates were
each building pyRTA task sets themselves -- `gate_pyrta`, `gate_rearm`,
`gate_pin_subsets`, `gate_pyrta_jitter` -- and when the shipped table was
re-baselined to its derived `J = 1`, THREE OF THEM FAILED AT ONCE, all for the
same reason: every one used plain `Periodic`, i.e. the NAIVE framing, and so
reported the J = 0 answers against our J = 1 ones.

⭐ That was the stale-literal guards and the agreement checks doing exactly
their job -- but it also showed the structural problem. A bound that is quoted
as THE published number cannot have four private implementations, three of them
wrong. `gate_pyrta_jitter` already demonstrated that the naive framing
reproduces our old *bug's* numbers on the two lanes where the bug was visible;
leaving that framing in three gates means three gates silently measuring a
different question.

THE FRAMING, and why each piece is needed:

  1. ARRIVALS CARRY JITTER. `PeriodicWithJitter(T, J)` has upper arrival curve
     `ceil((delta + J)/T)` -- Spuri's inflated release count exactly, and
     pointwise equal to our `BLane.N_J`. A bursty lane (n > 1) has no pyRTA
     arrival class, so its curve is handed over as an `ArrivalCurvePrefix` built
     from `N_J` and VERIFIED pointwise against it.

  2. DEADLINES ARE CONVERTED, BECAUSE THE CONVENTIONS DIFFER. pyRTA's
     `Deadline(D)` is relative to the job's ARRIVAL; ours is relative to its
     NOMINAL release. Without jitter those coincide. With jitter they give
     DIFFERENT EDF PRIORITY ORDERS -- a job nominally early but actually delayed
     still carries its early deadline in our semantics, so it can outrank a job
     released after it. Interferers therefore get `D_j - J_j`, the most urgent
     their nominal-release deadline can appear from their own arrival.

  3. THE SUBJECT'S OWN DELAY IS SWEPT, NOT CHOSEN. A subject job delayed by
     `delta` has relative deadline `D_k - delta` from its own arrival, and its
     response from the NOMINAL release is pyRTA's answer plus `delta`. ⛔ GIVING
     IT `D_k` AND THEN ADDING `J_k` DOUBLE-COUNTS -- deadline `D_k` says the job
     was NOT delayed, `+J_k` says it was delayed fully, and asserting both about
     one job inflated the bound above our own number and printed a FALSE
     unsoundness alarm on I2C. So the bound is the max over every `delta` the
     job can actually take.

  4. THE INTERFERER COUNT IS ASSERTED. pyRTA filters interferers BY VALUE on a
     frozen dataclass, so two parameter-identical lanes are both excluded and
     the bound comes out optimistic. `Priority(i)` is an identity tag for that
     reason only -- `edf.rta` reads deadlines.

⚠ WHAT IS OURS AND WHAT IS pyRTA'S. The SOLVER is pyRTA's: its busy-window
search, its interference algebra, its machine-verified lineage. The FRAMING
above is mine. That is stated wherever the number is published, and the naive
framing is kept red in `gate_pyrta_jitter` arm 1 as the honest measure of how
much the framing is doing.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_CACHE = {}


def _mod(src):
    """Import pyRTA once per src. ⛔ The caller resolves `src` via
    `pyrta_src.require_pyrta`, so this module never searches and never silently
    succeeds on a machine where the authority was deliberately removed."""
    if src not in _CACHE:
        if src not in sys.path:
            sys.path.insert(0, src)
        from response_time_analysis import edf
        from response_time_analysis.model import (WCET, ArrivalCurvePrefix,
                                                  Deadline, FullyNonPreemptive,
                                                  IdealProcessor, Periodic,
                                                  PeriodicWithJitter, Priority,
                                                  Task, taskset)
        _CACHE[src] = dict(
            edf=edf, WCET=WCET, ArrivalCurvePrefix=ArrivalCurvePrefix,
            Deadline=Deadline, FullyNonPreemptive=FullyNonPreemptive,
            IdealProcessor=IdealProcessor, Periodic=Periodic,
            PeriodicWithJitter=PeriodicWithJitter, Priority=Priority,
            Task=Task, taskset=taskset)
    return _CACHE[src]


def _curve(m, lane, horizon):
    """The lane's jitter-inflated arrival curve, in pyRTA's terms.

    ⛔ A BURSTY LANE GETS AN EXPLICIT PREFIX AND IT IS VERIFIED. pyRTA has no
    bursty arrival class, so the steps come from our own `N_J` -- which would be
    a silent opportunity to hand pyRTA a different task set from the one we
    analysed. The prefix is therefore checked pointwise against `N_J` over the
    whole horizon before it is used.
    """
    n = getattr(lane, "n", 1)
    if n == 1:
        if lane.J:
            return m["PeriodicWithJitter"](period=lane.t, jitter=lane.J)
        return m["Periodic"](period=lane.t)
    steps, prev = [], 0
    for d in range(1, horizon):
        v = lane.N_J(d - 1)          # closed-interval ours -> half-open pyRTA
        if v != prev:
            steps.append((d, v))
            prev = v
    acp = m["ArrivalCurvePrefix"](horizon=horizon, ac_steps=steps)
    bad = [d for d in range(1, horizon) if acp.max_arrivals(d) != lane.N_J(d - 1)]
    if bad:
        raise AssertionError(
            "%s: the arrival-curve prefix disagrees with N_J at %d of %d points "
            "(first delta=%d). pyRTA would be analysing a different task set."
            % (lane.name, len(bad), horizon - 1, bad[0]))
    return acp


def bound(src, lanes, k, horizon=None):
    """pyRTA's bound on lane `k`'s response, measured from the NOMINAL release.

    Returns (r, None) or (None, reason).
    """
    m = _mod(src)
    if horizon is None:
        horizon = 2 * max(getattr(l, "T", l.t) for l in lanes)
    curves = [_curve(m, l, horizon) for l in lanes]
    subject = lanes[k]
    best, err = None, None
    for delta in range(0, subject.J + 1):
        tasks = []
        ok = True
        for i, l in enumerate(lanes):
            d_eff = (l.D - delta) if i == k else (l.D - l.J)
            if d_eff <= 0:
                err = ("%s: effective deadline %d <= 0 -- the lane's whole "
                       "tolerance is release jitter, so this construction "
                       "cannot express it" % (l.name, d_eff))
                ok = False
                break
            tasks.append(m["Task"](curves[i],
                                   m["FullyNonPreemptive"](m["WCET"](l.C)),
                                   m["Deadline"](d_eff), m["Priority"](i)))
        if not ok:
            continue
        ts = m["taskset"](*tasks)
        # the identity footgun, asserted rather than trusted
        if len(list(ts.excluding_iter(tasks[k]))) != len(tasks) - 1:
            return None, ("parameter-identical lanes were MERGED by pyRTA: "
                          "the bound would be optimistic")
        sol = m["edf"].rta(ts, tasks[k], m["IdealProcessor"]())
        R = getattr(sol.response_time_bound, "value", sol.response_time_bound)
        if R is None:
            err = "pyRTA returned no bound at delta=%d" % delta
            continue
        v = R + delta
        if best is None or v > best:
            best = v
    return best, (None if best is not None else (err or "no feasible delta"))


def bound_charge_once(src, lanes, k, horizon=None):
    """⛔ THE "CHARGE JITTER ONCE" FRAMING -- RETRACTED, KEPT TO BE SHOWN FAILING.

    Interferers keep their jittered arrival curve but get `Deadline(D_j)`
    instead of `D_j - J_j`; the subject's own delay is swept as in `bound`.
    Ruling Y ordered the wrapper changed to this on the claim that `bound`
    charges jitter twice. The claim had no witness and it is FALSE: on the
    LJ instances (`jitter_instances.LJ_INSTANCES`, J about half the period)
    TChecker says `bound` is EXACT on all 8 lanes and THIS framing is BELOW the
    truth on 5 of 8 -- it hands a late interferer a deadline its nominal
    release never had, so it is outranked when it should not be.
    `gate_pyrta_jitter` arm 4 requires exactly that.
    """
    m = _mod(src)
    if horizon is None:
        horizon = 2 * max(getattr(l, "T", l.t) for l in lanes)
    curves = [_curve(m, l, horizon) for l in lanes]
    best = None
    for delta in range(0, lanes[k].J + 1):
        tasks = [m["Task"](curves[i], m["FullyNonPreemptive"](m["WCET"](l.C)),
                           m["Deadline"]((l.D - delta) if i == k else l.D),
                           m["Priority"](i))
                 for i, l in enumerate(lanes)]
        ts = m["taskset"](*tasks)
        sol = m["edf"].rta(ts, tasks[k], m["IdealProcessor"]())
        R = getattr(sol.response_time_bound, "value", sol.response_time_bound)
        if R is not None and (best is None or R + delta > best):
            best = R + delta
    return best


def bound_naive(src, lanes, k, horizon=None):
    """⛔ THE NAIVE FRAMING, KEPT ONLY TO BE SHOWN FAILING.

    Deadlines unconverted and `+J_k` added to the subject. It is NOT a worse
    approximation of the same question -- it answers a DIFFERENT one, and on the
    two lanes where our old interference bug was visible it returns EXACTLY the
    buggy numbers. `gate_pyrta_jitter` arm 1 runs it and requires it to be
    optimistic, because "two engines agree" is worth nothing when they share the
    assumption that is wrong.
    """
    m = _mod(src)
    if horizon is None:
        horizon = 2 * max(getattr(l, "T", l.t) for l in lanes)
    curves = [_curve(m, l, horizon) for l in lanes]
    tasks = [m["Task"](curves[i], m["FullyNonPreemptive"](m["WCET"](l.C)),
                       m["Deadline"](l.D), m["Priority"](i))
             for i, l in enumerate(lanes)]
    ts = m["taskset"](*tasks)
    if len(list(ts.excluding_iter(tasks[k]))) != len(tasks) - 1:
        return None, "lanes MERGED"
    sol = m["edf"].rta(ts, tasks[k], m["IdealProcessor"]())
    R = getattr(sol.response_time_bound, "value", sol.response_time_bound)
    if R is None:
        return None, "no bound"
    return R + lanes[k].J, None


def check_direction(rows, label="", verbose=True):
    """Ruling 2's gate: OURS >= pyRTA on every lane.

    `rows` = [(name, r_pyrta, r_ours)].

    ⛔⛔ NAMED FOR WHAT IT MEANS, BECAUSE THIS CHECK WAS ONCE INVERTED. In
    `gate_pyrta.py` the variable holding the SAFE cases was called `tighter` and
    the unsoundness alarm fired on them; it only looked correct because an
    exact-equality guard was failing either way, i.e. the gate worked for a
    reason other than the one it stated. Ours SMALLER than a sufficient bound is
    the forbidden direction, and that is the name it gets.

    ⭐ AND UNDER RULING 2 THE FAILURE HAS TWO CAUSES, NOT ONE. pyRTA is now the
    published number, so `ours < pyRTA` means EITHER our recurrence is unsound
    OR pyRTA has been misframed -- and `bound_naive` is standing proof that
    misframing is a live risk, not a theoretical one. The message says both.
    """
    smaller = [r for r in rows if r[2] < r[1]]
    larger = [r for r in rows if r[2] > r[1]]
    exact = [r for r in rows if r[2] == r[1]]
    if verbose:
        print("    %-34s %d exact, %d ours-larger (safe), %d ours-smaller"
              % (label or "direction:", len(exact), len(larger), len(smaller)))
        if smaller:
            print("    ⛔⛔ OURS SMALLER THAN pyRTA on: %s"
                  % ", ".join("%s (%d < %d)" % (r[0], r[2], r[1])
                              for r in smaller))
            print("        STOP. Either our recurrence is UNSOUND, or pyRTA is")
            print("        MISFRAMED -- and `bound_naive` shows misframing is a")
            print("        real risk. Resolve which before quoting any r_i.")
    return not smaller
