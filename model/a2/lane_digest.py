"""SPEC A1 -- every gate prints a DIGEST of the lane table it consumed.

THE ONE CLAIM: if two gates in one run analysed different lane tables, the run
fails -- without anyone having to go looking for the copy.

⛔⛔ WHY A DIGEST AND NOT A CODE REVIEW. Two stale copies of the lane table
turned up in a single batch:
  * `gate_pyrta.py` carried a hand-typed second table, edited from memory
    whenever a deadline moved;
  * `periodic_equivalence()` hard-coded UART-rx as (n=10, t=434, T=4340) long
    after P1 re-synthesized the lane to (t=414, T=4140) -- and it PASSED, because
    `n*t == T` holds for both. A green check was certifying the gaplessness of a
    lane the project no longer ships, and that substitution is the thing the
    whole pyRTA comparison rests on.
Two in one batch is a class, not luck. Grepping for copies finds the ones that
exist; a digest catches the one that has not been written yet.

⭐⭐ AND THE OBVIOUS VERSION OF THIS CHECK WOULD NOT WORK. If each gate printed
the digest of the table it IMPORTED, then a gate that imports the table and then
analyses a hand-typed copy prints a matching digest while using the copy -- the
guard would pass BECAUSE of the defect it screens for. So there are two digests
per gate and the distinction is the whole mechanism:

    BASE  the shipped table as this module computes it, from `bursty`. Every
          gate in a run must report the same BASE, or the run failed.
    USED  the lane objects the gate actually handed to the analyser. A gate that
          claims to analyse the shipped table must report USED == BASE.

A hand-typed copy changes USED and leaves BASE alone, which is exactly the
signature the second field exists to expose. A gate that deliberately analyses a
VARIANT (a C sweep, a different SCL split, a constructed instance) declares that,
and then USED != BASE is the expected reading rather than a failure.

⛔ THE DIGEST COVERS EVERY FIELD THAT CHANGES A RESULT, including the two R2
added. Leaving `D_sched` out would let a gate schedule on a different key and
still match -- which is the same error in a new place.
"""

from __future__ import annotations

import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

MARKER = "LANE-DIGEST"          # what `run_a2.py` greps for


def _fields(lane) -> tuple:
    """Every field that can change a response time. Order is part of the hash.

    ⛔ `D_sched` and `D_tol` are BOTH here. They are different objects (spec R2)
    and a gate that confused them would otherwise digest identically.
    """
    return (lane.name,
            int(lane.T), int(lane.C),
            int(getattr(lane, "n", 1)),
            int(getattr(lane, "t", lane.T)),
            int(getattr(lane, "J", 0)),
            int(lane.D_tol), int(lane.D_sched), int(lane.D))


def digest(lanes) -> str:
    """A short, stable hash of a lane set. Order-insensitive by construction."""
    h = hashlib.sha256()
    for f in sorted(_fields(l) for l in lanes):
        h.update(repr(f).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:12]


def shipped():
    """THE shipped five-lane table, from the one place it is defined."""
    from bursty import TX, SPI_RX, UART_RX
    return list(TX) + [UART_RX, SPI_RX]


def base_digest() -> str:
    return digest(shipped())


def announce(gate: str, used=None, variant: str | None = None) -> str:
    """Print this gate's BASE and USED digests. Returns the USED digest.

    `used`    the lane objects actually analysed. None means "this gate does not
              analyse the shipped table at all" (e.g. constructed instances), and
              that is recorded rather than silently skipped.
    `variant` a one-line reason USED is expected to differ from BASE. A gate that
              analyses a variant without declaring one is a finding.
    """
    b = base_digest()
    if used is None:
        print("  %s base=%s used=NONE  (%s analyses no shipped lane: %s)"
              % (MARKER, b, gate, variant or "*** UNDECLARED ***"))
        return "NONE"
    u = digest(used)
    if u == b:
        print("  %s base=%s used=%s  MATCH  (%s)" % (MARKER, b, u, gate))
    else:
        print("  %s base=%s used=%s  VARIANT  (%s: %s)"
              % (MARKER, b, u, gate, variant or "*** UNDECLARED VARIANT ***"))
    return u


# ============================================================================
def selftest() -> int:
    """⛔ A digest that has never been seen to DIFFER is not a check.

    Both faces, plus the one that matters most: a single-field change in the
    field most recently added to the model must move the hash. R2's `D_sched`
    went in last and is the one a future edit is most likely to forget.
    """
    from bursty import BLane
    print()
    print("=" * 78)
    print("SPEC A1 -- the lane-table digest, both faces")
    print("=" * 78)
    rc = 0
    ship = shipped()
    b = digest(ship)
    print("  shipped base digest: %s  (%d lanes)" % (b, len(ship)))

    # face 1: the same table, rebuilt independently, must digest the same
    same = [BLane(l.name, l.T, l.C, n=l.n, t=l.t, J=l.J,
                  D_tol=l.D_tol, D_sched=l.D_sched) for l in ship]
    print("  face 1  an independent rebuild of the same values -> %s  %s"
          % (digest(same), "MATCH" if digest(same) == b else "*** DIFFERS ***"))
    if digest(same) != b:
        rc = 1

    # face 2: order must not matter -- gates assemble the set in their own order
    print("  face 2  the same set, reversed -> %s  %s"
          % (digest(list(reversed(ship))),
             "MATCH" if digest(list(reversed(ship))) == b else "*** DIFFERS ***"))
    if digest(list(reversed(ship))) != b:
        rc = 1

    # face 3: THE MUST-FIRE -- one field at a time, each must move the hash
    print("  face 3  must-fire: a single-field change must CHANGE the digest")
    moves = []
    for field, kw in (("T", {"T": ship[1].T + 1}),
                      ("C", {"C": ship[1].C + 1}),
                      ("n/t", {"n": 2, "t": ship[1].T // 2}),
                      ("J", {"J": ship[1].J + 1}),
                      ("D_tol", {"D_tol": ship[1].D_tol + 1}),
                      ("D_sched", {"D_sched": ship[1].D_sched - 1})):
        args = dict(name=ship[1].name, T=ship[1].T, C=ship[1].C,
                    n=ship[1].n, t=ship[1].t, J=ship[1].J,
                    D_tol=ship[1].D_tol, D_sched=ship[1].D_sched)
        args.update(kw)
        mut = [BLane(args["name"], args["T"], args["C"], n=args["n"],
                     t=args["t"], J=args["J"], D_tol=args["D_tol"],
                     D_sched=args["D_sched"])] + ship[2:] + [ship[0]]
        d = digest(mut)
        ok = d != b
        moves.append((field, ok))
        print("      %-8s -> %s  %s" % (field, d, "moved" if ok else "*** UNCHANGED ***"))
        if not ok:
            rc = 1
    dead = [f for f, ok in moves if not ok]
    if dead:
        # ⛔ this branch had a %s with no argument: it would have raised
        # TypeError at the exact moment it was trying to report a failure.
        # A reporting path that only runs on failure is a path nothing exercises.
        print("      *** FAIL: %s do not enter the digest, so a gate could"
              % ", ".join(dead))
        print("          analyse a different value and still match. ***")
    else:
        print("      => every result-changing field is inside the hash")

    print()
    print("  GATE A1-selftest: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(selftest())
