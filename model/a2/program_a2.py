"""program_a2 -- A2's post-HIGH gap bound, derived PER PROGRAM (ruling S).

⛔⛔ WHAT WAS WRONG, AND IT IS THE SAME CATEGORY ERROR THIS SESSION HAS MADE
FOUR TIMES. `test/clocked_conform.vh` bounded every clocked lane's post-HIGH
release at `d + CK_GAP_SLACK` with `CK_GAP_SLACK = 8 = L_SYNC + 1 + (r_i - C)`,
and that `r_i` came from `gate_clocked_lane_a2.build()` -- the A2 MODEL's
shipped lane set (UART-tx, SPI-tx, UART-rx, SPI-rx, one clocked I2C lane). The
bound was then enforced on `ckod`, whose lane set is FOUR clocked open-drain
lanes at 33/60/120/240 and nothing else. A number derived for one lane set,
enforced on another. It happened to hold (measured 7 against 8), which is
exactly why it went unnoticed -- and every other clocked arm ran with the bound
switched OFF because nobody had a number for its lane set.

⇒ `r_i` belongs to the pair (PROGRAM, LANE). This module derives it from the
  program's OWN image: its own headers, its own delays, its own `J`.

THE LANE SET, READ FROM THE IMAGE AND NOT ASSUMED:

    T        the lane's MINIMUM action delay over every action it can reach.
             By P8 the timestamp advances absolutely by `a_dly`, so the tightest
             delay is the tightest inter-release.
    C        `C_SHIPPED` -- the measured dispatch service time.
    D_sched  the header's `dsched`, because that IS the engine's EDF key.
             ⛔ Not a protocol tolerance. `r_i` depends on priority, and the
             silicon's priority is this field; using anything else would derive
             the response of a differently-scheduled machine.
    D_tol    the header's `dtol`. Admissibility only -- it does not move `r_i`.
    J        `j_of(d_min_program, k)` for every lane, plus `L_JIT` on a lane
             released by an OBSERVED EDGE (a clocked open-drain lane parks on
             SCL's rise). J is a function of the program, not one number
             (ruling 1(b)), so the program's own `d_min` sets it.

⚠ AN OVERLOADED PROGRAM HAS NO BOUND, AND THAT IS A RESULT, NOT A GAP. A lane
set whose utilisation exceeds 1 has no finite worst-case response; the RTA does
not converge and pyRTA returns no bound. `corpus_all5` runs four lanes at
d = 9..13 beside a clocked lane at 70, ON PURPOSE (it is the scheduler stress
image), and its clocked lane MEASURED 131 cycles late. Quoting a bound for it
would be inventing one. It is reported UNBOUNDED with the utilisation that
makes it so, and the bench reports its lateness without a verdict -- which is
the status Wilson's earlier ruling already gave it.
"""

from __future__ import annotations

import glob
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "model"))
sys.path.insert(0, os.path.join(ROOT, "test"))

import gate_degenerate_fields as dgf                              # noqa: E402
import gate_j_program as jp                                       # noqa: E402
import pe_isa as I                                                # noqa: E402
import pyrta_bound                                                # noqa: E402
from bursty import C_SHIPPED, L_JIT, L_SYNC, BLane, response_time_b  # noqa
from pyrta_src import pinned_pyrta                                # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

N_PINS = I.UO3 + 1
OUT_JSON = os.path.join(ROOT, "test", "clocked_a2_bounds.json")


def lanes_of(img):
    """Every lane the image runs, as (lane, header, actions)."""
    by = {}
    for ln, h, a in dgf.walk(img):
        by.setdefault(ln, (h, []))[1].append(a)
    return [(ln, h, acts) for ln, (h, acts) in sorted(by.items())]


def is_clocked(h, a):
    return (h["clkpin"] < N_PINS and a["level"] == 1
            and a["op"] in (I.OP_SHIFT, I.OP_SHIFTIN))


def lane_set(img):
    """The program's own A2 lane set, plus which entries are clocked OD."""
    rows = lanes_of(img)
    delays = [a["delay"] for _ln, _h, acts in rows for a in acts
              if a["delay"] > 0]
    d_min = min(delays) if delays else None
    k = len(rows)
    j_prog = jp.j_of(d_min, k) if d_min else 0
    out = []
    for ln, h, acts in rows:
        T = min((a["delay"] for a in acts if a["delay"] > 0), default=500)
        ck_od = any(is_clocked(h, a) for a in acts) and h["mode"] == 0
        # ⛔ BLane asserts D_sched <= D_tol; a header that violates it is a
        # program whose EDF key is looser than its own tolerance, which the
        # model refuses rather than silently swapping.
        ds, dt = h["dsched"], h["dtol"]
        if ds > dt:
            dt = ds
        J = j_prog + (L_JIT if ck_od else 0)
        bl = BLane("lane%d%s" % (ln, " ckOD" if ck_od else ""), T=T,
                   C=C_SHIPPED, D_tol=dt, D_sched=ds, J=J)
        out.append({"lane": ln, "blane": bl, "clocked_od": ck_od, "T": T})
    return out, d_min, k, j_prog


def utilisation(ls):
    return sum(r["blane"].C / float(r["T"]) for r in ls)


def derive(img, src=None):
    """Per clocked open-drain lane: r_i (pyRTA primary), and the bench slack.

    ⛔⛔ `src=None` IS A SUPPORTED MODE, AND THE FIRST VERSION DID NOT HAVE IT.
    pyRTA is NOT vendored, and every pyRTA-primary gate in this project lives
    OUTSIDE `ci/run_gates.sh` for exactly that reason (`run_a2.py` runs them by
    hand at each checkpoint). Ruling S first wired two pyRTA-dependent checks
    into CI; both passed here only because a pyRTA clone sits in a scratch
    directory, and CI went red at 20 of 22 -- caught by checking CI on the
    exact SHA, which is what ruling CI1 is for.
    ⇒ Without pyRTA this computes EVERYTHING EXCEPT the pyRTA column: the lane
      set, U, J and our own recurrence's `r_ours`. That is what CI re-derives
      to hold the committed JSON current. The pyRTA column -- and therefore the
      bench budgets, which are pyRTA-primary -- is re-derived by
      `gate_a2_bounds_pyrta.py` under `run_a2.py`, RED without pyRTA.
    ⭐ `r_floor` IS THE LARGER OF THE TWO WHEN BOTH EXIST. Measured over every
    clocked lane in the repo, `r_ours >= r_pyrta` (equal on most, larger on two
    `ckdense` lanes), so a floor taken from `r_ours` alone is never LESS strict
    than the pyRTA one on any program we have -- but that is an observation,
    not a theorem, so when pyRTA is present the max is used rather than trusted.
    """
    ls, d_min, k, j_prog = lane_set(img)
    blanes = [r["blane"] for r in ls]
    u = utilisation(ls)
    res = {"d_min": d_min, "k": k, "J": j_prog, "U": round(u, 4),
           "lanes": {}}
    for i, r in enumerate(ls):
        if not r["clocked_od"]:
            continue
        entry = {"T": r["T"], "r_pyrta": None, "r_ours": None, "slack": None,
                 "r_floor": None, "why": None}
        # ⛔ OVERLOAD FIRST: an RTA over a set with U > 1 has no fixed point,
        # and a number returned anyway would be the horizon, not a bound.
        if u > 1.0:
            entry["why"] = ("lane set overloaded (U = %.3f > 1): no finite "
                            "worst-case response exists" % u)
            res["lanes"][str(r["lane"])] = entry
            continue
        try:
            ours = response_time_b(r["blane"], blanes)["r"]
        except Exception as exc:                          # noqa: BLE001
            ours = None
            entry["why"] = "own recurrence raised %s" % type(exc).__name__
        entry["r_ours"] = ours
        if not src:
            # ⭐ NO pyRTA: our recurrence only, and the entry SAYS so. The
            # pyRTA column stays None rather than being filled with `r_ours`,
            # so nothing downstream can mistake one for the other.
            entry["r_floor"] = ours
            res["lanes"][str(r["lane"])] = entry
            continue
        p, err = pyrta_bound.bound(src, blanes, i)
        entry["r_pyrta"] = p
        cands = [x for x in (ours, p) if x is not None]
        entry["r_floor"] = max(cands) if cands else None
        if p is None:
            entry["why"] = entry["why"] or ("pyRTA gave no bound: %s" % err)
        else:
            # ⭐ pyRTA IS PRIMARY. The bench budget is the same expression the
            # shipped constant came from -- only the lane set it is evaluated
            # over has changed, which is the entire point of ruling S.
            entry["slack"] = L_SYNC + 1 + (p - C_SHIPPED)
        res["lanes"][str(r["lane"])] = entry
    return res


def clocked_images():
    """Every tracked image that has at least one clocked open-drain lane."""
    out = []
    for p in sorted(glob.glob(os.path.join(ROOT, "test", "*.hex"))):
        name = os.path.basename(p)
        if name.startswith("probe_"):
            continue
        img = dgf.load(p)
        ls, _d, _k, _j = lane_set(img)
        if any(r["clocked_od"] for r in ls):
            out.append((name, img))
    return out


def main() -> int:
    print()
    print("=" * 78)
    print("  RULING S -- A2's POST-HIGH GAP BOUND, PER PROGRAM")
    print("=" * 78)
    # ⛔ P6: only a PINNED (or declared) pyRTA writes the budgets the bench
    # enforces -- an unpinned witness cannot certify a committed artefact.
    src = pinned_pyrta()
    if not src:
        print("  *** pyRTA NOT FOUND -- the per-program bound is pyRTA-primary,")
        print("      so nothing is written rather than a fallback number.")
        return 1
    print("  pyRTA source: %s" % src)
    print("  slack = L_SYNC (%d) + 1 + (r_i - C), r_i from pyRTA over the"
          % L_SYNC)
    print("  program's OWN lane set")
    print()
    blob = {}
    print("  %-26s %-5s %-3s %-3s %-7s %-5s %-6s %-7s %-6s %s"
          % ("image", "dmin", "k", "J", "U", "lane", "T", "r(pyRTA)",
             "slack", "note"))
    for name, img in clocked_images():
        res = derive(img, src)
        blob[name] = res
        for ln, e in sorted(res["lanes"].items(), key=lambda kv: int(kv[0])):
            print("  %-26s %-5s %-3s %-3s %-7s %-5s %-6s %-7s %-6s %s"
                  % (name, res["d_min"], res["k"], res["J"], res["U"], ln,
                     e["T"], e["r_pyrta"], e["slack"], e["why"] or ""))
    with io.open(OUT_JSON, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(blob, fh, indent=1, sort_keys=True)
    print()
    print("  -> %s (%d image(s))" % (os.path.relpath(OUT_JSON, ROOT),
                                     len(blob)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
