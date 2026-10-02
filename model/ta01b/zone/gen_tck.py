"""Emit the looping UART model as a TChecker timed automaton.

⛔⛔ WHAT THIS MODEL CHECKS, AND WHAT IT DELIBERATELY DOES NOT. The zone tool is
the INDEPENDENT witness for the TIMED property -- the framing conjunct: the start
bit is sampled low, the stop bit is sampled high, and every sample lands inside
its own bit window. That is what a timed automaton is FOR.

It does NOT carry the DATA conjunct. The byte comparison is integer bookkeeping,
not a timing property, and zones contribute nothing to it. The fixpoint carries
both; this carries the timed half. Saying so is the point -- claiming the zone
model covers the data conjunct would be claiming independence we do not have.

⭐ AND THE DATA BITS ARE NONDETERMINISTIC HERE, WHICH MAKES THIS STRONGER THAN
THE FIXPOINT ON ITS OWN AXIS. The executor may emit EITHER level for every data
bit, so `A[] not bad` proves framing conformance for ALL 2^8 payloads and every
infinite sequence of them -- not just the periodic stream [0x55,0x0F,0x01]. That
is exactly the "framing conjunct is value-independent" requirement, discharged by
construction rather than by assertion.

⭐ UNBOUNDED INTER-FRAME IDLE IS FREE IN A TA: the idle location simply carries no
invariant, so time may pass there without bound. In the fixpoint this needed an
explicit nondeterministic branch; here it is the absence of a constraint.

⛔ THE FALLING EDGE IS A SYNCHRONISED EVENT, not a guard on a shared variable.
A guard `line==0` would be enabled for the whole start bit, letting the monitor
latch LATE and manufacturing misalignment that the real receiver never has -- a
spurious counterexample, which is worse than a missed one because it looks like a
finding.
"""

import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def gen(t_mon: int, t_exec: int | None = None, n: int = 8) -> str:
    """t_mon = monitor's nominal bit period; t_exec = executor's actual one."""
    te = t_exec if t_exec is not None else t_mon
    half = t_mon // 2
    L = []
    w = L.append
    w("system:uart_loop")
    w("")
    w("event:fall")      # start-bit edge, synchronised
    w("event:tau")
    w("")
    w("# shared line level, written by the executor, sampled by the monitor")
    w("int:1:0:1:1:line")
    w("")
    # ---------------- executor ----------------
    w("process:E")
    w("clock:1:xe")
    w("location:E:eIdle{initial:}")          # no invariant => unbounded idle
    w("location:E:eStart{invariant: xe<=%d}" % te)
    for k in range(n):
        w("location:E:eD%d{invariant: xe<=%d}" % (k, te))
    w("location:E:eStop{invariant: xe<=%d}" % te)
    # idle -> start : the synchronised falling edge, enabled at ANY time
    w("edge:E:eIdle:eStart:fall{do: line=0; xe=0}")
    # start -> D0 : nondeterministic data bit
    w("edge:E:eStart:eD0:tau{provided: xe==%d : do: line=0; xe=0}" % te)
    w("edge:E:eStart:eD0:tau{provided: xe==%d : do: line=1; xe=0}" % te)
    for k in range(n):
        nxt = ("eD%d" % (k + 1)) if k + 1 < n else "eStop"
        if k + 1 < n:
            w("edge:E:eD%d:%s:tau{provided: xe==%d : do: line=0; xe=0}" % (k, nxt, te))
            w("edge:E:eD%d:%s:tau{provided: xe==%d : do: line=1; xe=0}" % (k, nxt, te))
        else:
            # entering STOP the line must go high -- that IS the stop bit
            w("edge:E:eD%d:eStop:tau{provided: xe==%d : do: line=1; xe=0}" % (k, te))
    # stop -> idle, re-arm
    w("edge:E:eStop:eIdle:tau{provided: xe==%d : do: line=1; xe=0}" % te)
    w("")
    # ---------------- monitor ----------------
    w("process:M")
    w("clock:1:xm")
    w("location:M:mIdle{initial:}")
    w("location:M:mStart{invariant: xm<=%d}" % half)
    for k in range(n):
        w("location:M:mD%d{invariant: xm<=%d}" % (k, t_mon))
    w("location:M:mStop{invariant: xm<=%d}" % t_mon)
    w("location:M:bad{labels: bad}")
    # idle -> start on the SYNCHRONISED falling edge
    w("edge:M:mIdle:mStart:fall{do: xm=0}")
    # start sample at the bit centre -- FRAMING conjunct, value independent
    w("edge:M:mStart:mD0:tau{provided: xm==%d && line==0 : do: xm=0}" % half)
    w("edge:M:mStart:bad:tau{provided: xm==%d && line==1}" % half)
    for k in range(n):
        nxt = ("mD%d" % (k + 1)) if k + 1 < n else "mStop"
        # data bits are RECORDED, never judged -- framing is value-independent
        w("edge:M:mD%d:%s:tau{provided: xm==%d : do: xm=0}" % (k, nxt, t_mon))
    # stop sample must be high
    w("edge:M:mStop:mIdle:tau{provided: xm==%d && line==1 : do: xm=0}" % t_mon)
    w("edge:M:mStop:bad:tau{provided: xm==%d && line==0}" % t_mon)
    w("")
    w("sync:E@fall:M@fall")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--t", type=int, default=434)
    ap.add_argument("--te", type=int, default=None)
    ap.add_argument("-o", default=None)
    a = ap.parse_args()
    txt = gen(a.t, a.te)
    if a.o:
        open(a.o, "w", newline="\n").write(txt)
        print("wrote %s  (T_mon=%d T_exec=%d)" % (a.o, a.t, a.te or a.t))
    else:
        print(txt)
