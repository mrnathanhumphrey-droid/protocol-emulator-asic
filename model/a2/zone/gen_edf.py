"""A2-GREEN Part 3 -- emit a non-preemptive EDF scheduler as a TChecker model.

THE ONE CLAIM: `r_i` from the recurrence can be checked by a FOREIGN engine
exploring actual schedules, rather than by my algebra agreeing with my Python.

⛔⛔ WHY DISCRETE TIME AND NOT ZONES. The first attempt encoded EDF the natural
timed-automaton way: one clock per lane measuring time since release, and the
EDF choice as a DIAGONAL guard `x_j - x_i <= D_j - D_i`. `tck-syntax` accepts it
and `tck-reach` then refuses:

    ERROR: unsupported diagonal constraints

That is a hard limit of the zone algorithm, not a modelling mistake. The fix is
better than a workaround: the recurrence under test is a DISCRETE-TIME
formulation -- its blocking term is `C_k - 1`, one tick -- so a dense-time zone
model would be cross-checking a different semantics and any disagreement would be
uninterpretable. This model makes time explicit: one clock drives a tick, every
scheduling variable is a bounded int, and the state space is finite, so
reachability is decidable and COMPLETE.

THE MODEL, per time step:
    R1..RN  releases      each lane releases at its period; a release while
                          already pending sets `ovr` (the model's own
                          single-pending assumption, checked not assumed)
    SC      schedule      if the engine is free it MUST take a pending job
                          (work-conserving by construction: no skip edge is
                          emitted when something is pending) and takes the
                          EARLIEST-DEADLINE one
    EX      execute       one cycle of service; on the last cycle the job
                          completes and the response time is tested
    TK      time passes   exactly one tick -- the only location with a clock
                          invariant above zero
    A1..AN  age           every age advances

⭐ NON-PREEMPTION AND BLOCKING ARE EMERGENT, NOT ENCODED. `SC` only fires when
`cur == 0`, so a running job is never displaced; a less urgent job that started
before a more urgent release therefore runs to completion and delays it. That is
the `(C_k - 1)` blocking term arising from the schedule instead of being asserted
into it -- which is the whole point of cross-checking.

⭐ RELEASE PHASES ARE NONDETERMINISTIC. Each lane's first release may happen at
any step, so the checker explores every phase alignment. Pinning all lanes to a
synchronous release at t=0 would assume the critical instant -- exactly what
Spuri's Lemma 4.1 says you may not assume.

⭐ DEADLINE TIES ARE NONDETERMINISTIC TOO. The EDF guard uses `<=`, so on a tie
every candidate is enabled and the checker explores all tie-breaks. Picking one
would be assuming a tie-break rule the hardware does not promise.

RESPONSE TIME: a job released at step t and starting at t occupies cycles
t..t+C-1, so it completes at t+C and its response is C. With ages advanced once
per step, at the completing step `a_i` equals `response - 1`. Hence the test
`a_i >= R` means `response > R`, and

    r_i = min{ R : BAD unreachable }      (binary search by the caller)
"""

from __future__ import annotations

import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def subsets(xs):
    out = [[]]
    for x in xs:
        out += [s + [x] for s in out]
    return out


def gen(lanes, target: int, R: int, tag: str = "edf") -> str:
    """lanes = [(name, T, C, D)] or [(name, T, C, D, n, t)]; target = analysed
    lane index; R = bound.

    BAD is reachable iff some schedule gives the target lane a response > R.

    ⭐ THE n == 1 PATH IS EMITTED BYTE-IDENTICALLY to the version validated in
    Part 3. A bursty lane needs two timers (age since its last event, and time
    since its burst began) where a periodic lane needs one, so the bursty edges
    are a SEPARATE branch rather than a generalisation of the periodic ones.
    Rewriting the periodic path to share code would have put the one artefact
    that is already foreign-validated back into doubt for no gain.
    """
    N = len(lanes)
    T = [l[1] for l in lanes]
    C = [l[2] for l in lanes]
    D = [l[3] for l in lanes]
    nb = [(l[4] if len(l) > 4 else 1) for l in lanes]
    tb = [(l[5] if len(l) > 5 else l[1]) for l in lanes]
    for i in range(N):
        if nb[i] * tb[i] > T[i]:
            raise ValueError("lane %d: burst n*t=%d exceeds T=%d"
                             % (i, nb[i] * tb[i], T[i]))
    cmax = max(C)
    L = []
    w = L.append

    w("system:%s" % tag)
    w("")
    w("event:tau")
    w("")
    for i in range(N):
        w("int:1:0:1:0:p%d" % i)          # pending
        w("int:1:0:%d:0:a%d" % (max(1, T[i]), i))   # age since this lane's last event
        if nb[i] == 1:
            w("int:1:0:1:0:st%d" % i)     # periodic: has it started releasing yet
        else:
            w("int:1:0:%d:0:b%d" % (max(1, T[i]), i))   # time since burst start
            w("int:1:0:%d:0:k%d" % (nb[i], i))          # events so far this burst
    w("int:1:0:%d:0:rem" % cmax)          # remaining service of running job
    w("int:1:0:%d:0:cur" % N)             # 1..N = running lane, 0 = idle
    w("int:1:0:1:0:ovr")                  # a release arrived while pending
    w("")
    w("process:P")
    w("clock:1:c")
    # every location is urgent (c<=0) except TK, where exactly one tick passes
    w("location:P:R0{initial: : invariant: c<=0}")
    for i in range(1, N):
        w("location:P:R%d{invariant: c<=0}" % i)
    w("location:P:SC{invariant: c<=0}")
    w("location:P:EX{invariant: c<=0}")
    w("location:P:TK{invariant: c<=1}")
    for i in range(N):
        w("location:P:A%d{invariant: c<=0}" % i)
    w("location:P:BAD{labels: bad : invariant: c<=0}")
    w("location:P:OVR{labels: ovr : invariant: c<=0}")
    w("")

    # ---------------- release phase ----------------
    w("# --- releases: nondeterministic first release, then periodic ---")
    for i in range(N):
        nxt = ("R%d" % (i + 1)) if i + 1 < N else "SC"
        if nb[i] > 1:
            # ---- bursty lane: n events at inner spacing t, outer period T ----
            n, t = nb[i], tb[i]
            # burst not begun: start it at any step (all phases explored)
            w("edge:P:R%d:%s:tau{provided: k%d==0 : do: k%d=1; p%d=1; a%d=0; b%d=0}"
              % (i, nxt, i, i, i, i, i))
            w("edge:P:R%d:%s:tau{provided: k%d==0}" % (i, nxt, i))
            # mid-burst: next event one inner spacing after the previous
            w("edge:P:R%d:%s:tau{provided: k%d>=1 && k%d<%d && a%d<%d}"
              % (i, nxt, i, i, n, i, t))
            w("edge:P:R%d:%s:tau{provided: k%d>=1 && k%d<%d && a%d==%d && p%d==0 : "
              "do: k%d=k%d+1; p%d=1; a%d=0}" % (i, nxt, i, i, n, i, t, i, i, i, i, i))
            w("edge:P:R%d:OVR:tau{provided: k%d>=1 && k%d<%d && a%d==%d && p%d==1 : "
              "do: ovr=1}" % (i, i, i, n, i, t, i))
            # burst exhausted: wait out the outer period, then start the next
            w("edge:P:R%d:%s:tau{provided: k%d==%d && b%d<%d}"
              % (i, nxt, i, n, i, T[i]))
            w("edge:P:R%d:%s:tau{provided: k%d==%d && b%d==%d && p%d==0 : "
              "do: k%d=1; p%d=1; a%d=0; b%d=0}"
              % (i, nxt, i, n, i, T[i], i, i, i, i, i))
            w("edge:P:R%d:OVR:tau{provided: k%d==%d && b%d==%d && p%d==1 : do: ovr=1}"
              % (i, i, n, i, T[i], i))
            continue
        # ---- periodic lane: unchanged from the Part 3 validated model ----
        # not started yet: either release now, or keep waiting
        w("edge:P:R%d:%s:tau{provided: st%d==0 : do: st%d=1; p%d=1; a%d=0}"
          % (i, nxt, i, i, i, i))
        w("edge:P:R%d:%s:tau{provided: st%d==0}" % (i, nxt, i))
        # started: release exactly when the age reaches the period.
        # ⛔⛔ THIS GUARD WAS `a == T-1` AND THAT WAS AN OFF-BY-ONE IN THE
        # PERIOD ITSELF. A release at step t sets a=0 during step t, and the age
        # advances once per step, so a == T is the step exactly T later. Firing
        # at T-1 made every period one tick SHORT, which for I3 lifted the real
        # utilisation from 0.95 to 1.137 -- an overloaded system. It then
        # disagreed with the recurrence on three lanes and looked exactly like
        # "the recurrence is unsound". It was the model. The `ovr` check is what
        # said so, and the m_i>1 instance is what triggered it: with m_i == 1
        # the period never enters the first-instance worst case, so I1 and I2
        # agreed with a broken model.
        w("edge:P:R%d:%s:tau{provided: st%d==1 && a%d<%d}"
          % (i, nxt, i, i, T[i]))
        w("edge:P:R%d:%s:tau{provided: st%d==1 && a%d==%d && p%d==0 : "
          "do: p%d=1; a%d=0}" % (i, nxt, i, i, T[i], i, i, i))
        # ⛔ a release while still pending: the model's single-job assumption
        # breaking. Flagged, never silently absorbed.
        w("edge:P:R%d:OVR:tau{provided: st%d==1 && a%d==%d && p%d==1 : do: ovr=1}"
          % (i, i, i, T[i], i))
    w("")

    # ---------------- schedule phase ----------------
    w("# --- schedule: work-conserving, earliest deadline, ties nondeterministic ---")
    w("edge:P:SC:EX:tau{provided: cur>0}")       # busy: no decision to make
    allp = " && ".join("p%d==0" % j for j in range(N))
    w("edge:P:SC:EX:tau{provided: cur==0 && %s}" % allp)   # nothing pending
    for k in range(N):
        others = [j for j in range(N) if j != k]
        for S in subsets(others):
            notS = [j for j in others if j not in S]
            g = ["cur==0", "p%d==1" % k]
            g += ["p%d==1" % j for j in S]
            g += ["p%d==0" % j for j in notS]
            # EDF: D_k - a_k <= D_j - a_j  <=>  a_j - a_k <= D_j - D_k
            g += ["a%d-a%d<=%d" % (j, k, D[j] - D[k]) for j in S]
            w("edge:P:SC:EX:tau{provided: %s : do: cur=%d; rem=%d}"
              % (" && ".join(g), k + 1, C[k]))
    w("")

    # ---------------- execute phase ----------------
    w("# --- execute one cycle; test the response on the completing cycle ---")
    w("edge:P:EX:TK:tau{provided: cur==0}")
    for k in range(N):
        w("edge:P:EX:TK:tau{provided: cur==%d && rem>1 : do: rem=rem-1}" % (k + 1))
        if k == target:
            # response = a_k + 1. BAD iff response > R, i.e. a_k >= R.
            w("edge:P:EX:TK:tau{provided: cur==%d && rem==1 && a%d<=%d : "
              "do: rem=0; p%d=0; cur=0}" % (k + 1, k, R - 1, k))
            w("edge:P:EX:BAD:tau{provided: cur==%d && rem==1 && a%d>=%d : "
              "do: rem=0; p%d=0; cur=0}" % (k + 1, k, R, k))
        else:
            w("edge:P:EX:TK:tau{provided: cur==%d && rem==1 : "
              "do: rem=0; p%d=0; cur=0}" % (k + 1, k))
    w("")

    # ---------------- tick, then age ----------------
    w("# --- the only place time passes ---")
    w("edge:P:TK:A0:tau{provided: c==1 : do: c=0}")
    for i in range(N):
        nxt = ("A%d" % (i + 1)) if i + 1 < N else "R0"
        if nb[i] > 1:
            # a bursty lane carries two timers; each saturates independently, so
            # all four cap combinations get an edge (a missing one would silently
            # stall the cycle and drop behaviours -- empty-reads-as-pass again)
            w("edge:P:A%d:%s:tau{provided: a%d<%d && b%d<%d : "
              "do: a%d=a%d+1; b%d=b%d+1}"
              % (i, nxt, i, T[i], i, T[i], i, i, i, i))
            w("edge:P:A%d:%s:tau{provided: a%d<%d && b%d==%d : do: a%d=a%d+1}"
              % (i, nxt, i, T[i], i, T[i], i, i))
            w("edge:P:A%d:%s:tau{provided: a%d==%d && b%d<%d : do: b%d=b%d+1}"
              % (i, nxt, i, T[i], i, T[i], i, i))
            w("edge:P:A%d:%s:tau{provided: a%d==%d && b%d==%d}"
              % (i, nxt, i, T[i], i, T[i]))
            continue
        w("edge:P:A%d:%s:tau{provided: a%d<%d : do: a%d=a%d+1}"
          % (i, nxt, i, T[i], i, i))
        w("edge:P:A%d:%s:tau{provided: a%d==%d}" % (i, nxt, i, T[i]))
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    # tiny smoke: one lane, C=2 -> response must be exactly 2
    print(gen([("solo", 100, 2, 50)], target=0, R=1, tag="smoke"))
