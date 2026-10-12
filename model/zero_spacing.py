"""zero_spacing -- a delay-0 action is a ZERO release spacing (except an ARM's).

⛔⛔ WILSON'S DELAY-0 REARM RULING (must fix before lock). pe_asm ACCEPTED a
program whose wire stream did not match its feed: a WS2812 3-sub-bit lane at
d = 21 whose loop ended in a delay-0 REARM, beside four d = 20 lanes ("J 1").
The shipped UART-rx program had the same chain (stop SHIFTIN -> REARM -> ARM,
all delay 0), and beside the same four lanes it was ACCEPTED and mis-received
at -3 % baud. Every timing screen took its minimum over POSITIVE delays only
(`pe_asm.compute_j`, N1's `refill_dmin`, `program_a2.lane_set`), so a zero
spacing was invisible to all three.

⭐ WHY DELAY 0 IS A ZERO SPACING (PORT_SPEC §7, "one rule for every action"):
at writeback the lane's timestamp advances by `wb_dly` (= `a_dly`), so the
next action is released `a_dly` later -- at 0, immediately, and it owes a
refill like any retire. That is a lane dispatching twice within the 3-cycle
dispatch, which breaks P8/P9 ("a lane dispatches at most once per d cycles"):
no J can be computed for it, so the program is REFUSED (a missing bound is
red), never quoted.

⭐ WHY AN ARM'S DELAY 0 IS NOT (anchored, each line re-found in the RTL every
run; a missing anchor withdraws the exemption, so the ARM counts too):

  E1  `notmo_n[cur]   = (a_dly == {DLY_W{1'b0}});`
        an ARM's delay field is its TIMEOUT, and 0 means "no timeout"
  E2  `& ~(armed_n[i] & notmo_n[i]);` (the registered release term `rel_q`)
        an armed no-timeout lane is NOT released by its timestamp: it does not
        dispatch at all while it waits
  E3  `: arm_hit[gi] ? ck_rebase[gi]`
        only the observed EDGE releases it (timestamp rebased to the edge)

  => a delay-0 ARM puts no timestamp-driven dispatch on the lane; its
     successor's spacing is set by the PEER's edge. ⚠ That edge spacing is
     outside every program-derived d_min -- for an ARM with a timeout too --
     which is the reactive-lane scope already stated, not something this
     exemption creates.
"""

from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENGINE = os.path.join(ROOT, "src", "pe_engine.v")
sys.path.insert(0, os.path.join(ROOT, "test"))
from pe_isa import OP_ARM, OPCODES  # noqa: E402  (= the RTL's, gate_one_encoder)

NAMES = {v: "OP_" + k for k, v in OPCODES.items()}

#: (id, what it establishes, the statement that must be present, matched with
#: whitespace collapsed)
ANCHORS = (
    ("E1", "an ARM's delay 0 means no timeout",
     "notmo_n[cur] = (a_dly == {DLY_W{1'b0}});"),
    ("E2", "an armed no-timeout lane is not released by its timestamp",
     "& ~(armed_n[i] & notmo_n[i]);"),
    ("E3", "only the observed edge releases it",
     ": arm_hit[gi] ? ck_rebase[gi]"),
)


class ZeroSpacingError(RuntimeError):
    """The program has a zero release spacing: no J can be computed."""


def anchors(text=None):
    """[(id, what, line)] for every anchor; raises ZeroSpacingError on the
    first missing (the ARM exemption is then unproven)."""
    if text is None:
        with open(ENGINE, encoding="utf-8") as fh:
            text = fh.read()
    out = []
    for aid, what, needle in ANCHORS:
        pat = r"\s+".join(re.escape(t) for t in needle.split())
        m = re.search(pat, text)
        if m is None:
            raise ZeroSpacingError(
                "anchor %s (%s) is not in src/pe_engine.v: %r -- a delay-0 "
                "ARM can no longer be shown to wait on its edge, so it counts "
                "as a zero spacing too" % (aid, what, needle))
        out.append((aid, what, text.count("\n", 0, m.start()) + 1))
    return out


def arm_exempt(text=None):
    """True iff the ARM exemption is anchored in the RTL."""
    try:
        anchors(text)
        return True
    except ZeroSpacingError:
        return False


def check(actions, text=None):
    """Raise ZeroSpacingError naming the first zero spacing, if any."""
    hits = find(actions, text)
    if hits:
        raise ZeroSpacingError(message(hits))


def find(actions, text=None):
    """Zero release spacings in [(lane, index, op, delay)]: every delay-0
    action, minus ARMs while the exemption is anchored."""
    exempt = arm_exempt(text)
    return [(ln, i, op) for (ln, i, op, d) in actions
            if int(d) == 0 and not (exempt and int(op) == OP_ARM)]


def message(hits):
    names = NAMES
    ln, i, op = hits[0]
    return ("lane %d action %d (%s) has delay 0, a ZERO release spacing: the "
            "next action dispatches back to back and owes a refill, so the "
            "lane breaks 'one dispatch per >= d cycles' and no J can be "
            "computed (%d zero spacing(s) in the program). Give it a delay "
            ">= D*. Only an ARM's delay 0 is exempt -- it means 'no timeout' "
            "and the lane waits on its edge (model/zero_spacing.py E1-E3)."
            % (ln, i, names.get(op, "op %d" % op), len(hits)))
