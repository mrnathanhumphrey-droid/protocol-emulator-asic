"""J = 9 MARGINS -- compute, do not implement (Wilson, ruling 5).

THE QUESTION, and only the question: if `pe_asm` were extended to admit
programs with `d_min < D*` by charging them `J = 9` -- the structurally derived
per-lane bound (`2 * L_REFILL + 1`), now with a measured check at 7 -- would
every lane still keep a positive margin?

⛔⛔ WHAT THIS DELIBERATELY DOES NOT DO. It does not change `pe_asm`, does not
publish `J = 9`, and does not reopen SPI-target 2 MHz. The ruling is "compute
the margins now, decide later", and a gate that implemented the extension while
reporting the numbers would have made the decision by writing the code.

TWO LANE SETS, as ruled:
  * the SHIPPED five, with every lane charged J = 9 (I2C also pays L_JIT);
  * a d = 12 program with SPI-target at 2 MHz -- the case the D* refusal
    currently closes, and the reason anyone would want this.

TWO BOUNDS, in the ruled order:
  * pyRTA is PRIMARY (correctly framed, jitter-aware);
  * ours is the safe-direction cross-check, and must come out >= pyRTA. If
    ours is ever BELOW pyRTA, that is a STOP, not a better number.

⚠ `MARGIN_BAR = 4` is pre-registered in `ARCH_PREREG_01.md`. A margin that is
merely positive is not the bar.
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

import pyrta_bound                                     # noqa: E402
import pyrta_src                                       # noqa: E402
from bursty import BLane, L_JIT, response_time_b       # noqa: E402
from gate_j_sound import MARGIN_BAR, lanes_at          # noqa: E402

J_UNDER_TEST = 9
L_REFILL, N_LANES = 4, 5
D_STAR = N_LANES * L_REFILL


# ---------------------------------------------------------------------------
# the d = 12 program: SPI-target at 2 MHz, the case D* currently refuses
# ---------------------------------------------------------------------------
# ⛔ WHY THIS SET AND NOT A TIGHTER ONE. `d = 12` is the action spacing, so the
# bit period is 2 x d = 24 cycles at 50 MHz -- about 2 MHz, which is the
# SPI-target rate the D* refusal closes. The other four lanes keep their
# shipped rates: the question is whether ONE fast lane can be admitted, not
# whether five can.
# ⚠ D_tol VALUES ARE THE SHIPPED ONES except for the fast lane, whose D is
# half its period in the same style as the modelled stand-ins. It is a
# PLAUSIBLE requirement, not a derived one from a datasheet, and the verdict
# below is therefore about feasibility of the shape rather than about a
# specific part.
def lanes_d12(j_pipe: int) -> list:
    return [
        BLane("UART-tx 115200", 434, 2, D_tol=216, J=j_pipe),
        BLane("SPI-tx 1 MHz", 25, 2, D_tol=23, J=j_pipe),
        BLane("I2C 400 kHz", 45, 2, D_tol=15, J=j_pipe + L_JIT),
        BLane("UART-rx 115200", 434, 2, D_tol=216, J=j_pipe),
        BLane("SPI-target 2 MHz", 24, 2, D_tol=12, J=j_pipe),
    ]


def ours_rows(lanes):
    """(margin, name, r) per lane, our bound. ⭐ ONE list, selected by
    identity -- `response_time_b` filters interference with `is not`, so an
    equal-but-distinct copy would let a lane interfere with itself."""
    out = []
    for l in lanes:
        r = response_time_b(l, lanes, jitter_in_interference=True)["r"]
        out.append((l.margin(r), l.name, r))
    return out


def pyrta_rows(src, lanes):
    """(margin, name, r) per lane from pyRTA, the PRIMARY bound.

    ⛔ THE LANE OBJECTS GO IN UNCHANGED, and the first version of this
    converted them to 7-tuples first -- `pyrta_bound.bound` reads `.T`/`.t`
    off them and died on the tuples. ⭐ Passing the same objects our bound
    analysed is also the only way the two bounds are known to be about the
    same task set: `bound` builds an arrival curve from each lane and verifies
    it pointwise, so a re-expressed lane set would be a second task model.
    """
    out = []
    for k, l in enumerate(lanes):
        r, err = pyrta_bound.bound(src, lanes, k)
        if r is None:
            print("      ⚠ %s: pyRTA returned no bound -- %s" % (l.name, err))
        out.append((None if r is None else l.margin(r), l.name, r))
    return out


def show(title, rows):
    print("    %s" % title)
    print("      %-20s %-6s %s" % ("lane", "r", "margin"))
    for m, name, r in sorted(rows, key=lambda x: (99 if x[0] is None else x[0])):
        print("      %-20s %-6s %s" % (name, r, "n/a" if m is None else m))
    got = [m for m, _n, _r in rows if m is not None]
    return min(got) if got else None


def main() -> int:
    rc = 0
    print()
    print("=" * 78)
    print("J = %d MARGINS -- COMPUTE ONLY (ruling 5)" % J_UNDER_TEST)
    print("=" * 78)
    print("  question : could pe_asm admit d_min < D* = %d by charging J = %d?"
          % (D_STAR, J_UNDER_TEST))
    print("  bar      : margin >= %d (pre-registered, ARCH_PREREG_01.md)"
          % MARGIN_BAR)
    print("  ⛔ THIS GATE CHANGES NOTHING. It does not touch pe_asm, does not")
    print("     publish J = %d, and does not reopen SPI-target 2 MHz."
          % J_UNDER_TEST)
    print()

    src = pyrta_src.require_pyrta("gate_j9_margins")
    if not src:
        print("  *** pyRTA is the PRIMARY bound and it is absent, so this gate")
        print("      is RED rather than falling back to ours alone. Point")
        print("      PYRTA_SRC at a clone's src/.")
        return 1

    verdicts = {}
    for label, builder in (("the SHIPPED five", lanes_at),
                           ("a d = 12 program (SPI-target 2 MHz)", lanes_d12)):
        print("  --- %s, every lane at J = %d ---" % (label, J_UNDER_TEST))
        lanes = builder(J_UNDER_TEST)
        o = ours_rows(lanes)
        p = pyrta_rows(src, lanes)
        m_ours = show("ours (safe-direction cross-check)", o)
        print()
        m_pyr = show("pyRTA (PRIMARY)", p)
        print()
        # ⛔⛔ THE DIRECTION CHECK IS A STOP, NOT A COMPARISON. Ours must be at
        # or above pyRTA on every lane; ours being LOWER would mean our bound
        # is optimistic, and then neither number may be used.
        by_name_o = {n: r for _m, n, r in o}
        unsafe = [(n, by_name_o[n], r) for _m, n, r in p
                  if r is not None and by_name_o.get(n) is not None
                  and by_name_o[n] < r]
        if unsafe:
            print("    ⛔⛔ STOP: ours is BELOW pyRTA on %s" % (unsafe,))
            print("       Our bound would be optimistic, so NEITHER number may")
            print("       be used until the recurrence is re-derived.")
            rc = 1
        else:
            print("    direction ok: ours >= pyRTA on every lane")
        print("    min margin: ours %s   pyRTA %s   bar %s"
              % (m_ours, m_pyr, MARGIN_BAR))
        verdicts[label] = (m_ours, m_pyr)
        print()

    # ---- the answer to the ruled question, and nothing more -------------
    print("-" * 78)
    print("  THE ANSWER")
    open_option = True
    for label, (m_ours, m_pyr) in verdicts.items():
        use = m_pyr if m_pyr is not None else m_ours
        if use is None:
            print("    %s: NO READING" % label)
            open_option = False
            rc = 1
        elif use < 0:
            print("    %-36s MISSES ITS DEADLINES (margin %d)" % (label, use))
            open_option = False
        elif use < MARGIN_BAR:
            print("    %-36s margin %d -- POSITIVE BUT UNDER THE BAR of %d"
                  % (label, use, MARGIN_BAR))
            open_option = False
        else:
            print("    %-36s margin %d -- at or above the bar" % (label, use))
    print()
    if open_option:
        print("    ⇒ every lane keeps margin >= %d at J = %d on both sets, so"
              % (MARGIN_BAR, J_UNDER_TEST))
        print("      extending pe_asm to admit d_min < D* at J = %d (SPL = 2"
              % J_UNDER_TEST)
        print("      ONLY) is a REAL OPTION. ⚠ Nathan's product call, and not")
        print("      implemented here.")
    else:
        print("    ⇒ THE OPTION IS CLOSED ON THESE NUMBERS. At J = %d the"
              % J_UNDER_TEST)
        print("      margin does not clear the pre-registered bar, so")
        print("      admitting d_min < D* at J = %d would ship a set whose"
              % J_UNDER_TEST)
        print("      slack is smaller than the bar the architecture was")
        print("      accepted against. ⭐ That is a RESULT, not a failure of")
        print("      this gate: the D* refusal in pe_asm stays, and")
        print("      SPI-target 2 MHz stays closed by it.")
        print("    ⚠ WHAT WOULD REOPEN IT: a smaller J (the measured per-lane")
        print("      value is 7, not 9 -- but 7 is a measured floor on these")
        print("      arms, not a derived bound, so it cannot be charged), or a")
        print("      looser D_tol on the tightest lane, or more fetch")
        print("      bandwidth (which is what lowers D* itself).")
    print()
    print("=" * 78)
    print("  GATE j9-margins: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    ⚠ PASSED means the numbers were computed and the direction")
    print("      check held -- NOT that the extension is approved.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
