"""park_class -- what a PARKED lane does to the pin its header names, from the RTL.

⛔⛔ WILSON'S P3 RULING (one rule, explicit and implicit parks alike): a parked
lane may name a pin an active lane uses iff the parked lane is RELEASE-ONLY on
that pin for the whole program -- it never drives it and cannot change how the
active lane drives it -- PROVEN FROM AN RTL ANCHOR. This module is the proof;
a missing anchor RAISES (and pe_asm refuses), it never falls back to "probably
fine". The same shape as `count_ranges` and `hold_bound`.

⭐ WHAT A PARKED LANE IS. `pe_asm.assemble` gives it the header
`hdr(p, p, mode 0, ...)` (data pin = clock pin = p, OPEN-DRAIN) and points it at
the image's park word, a chaining `OP_REARM`. Its only effects on pin p are
therefore what HEADER LOAD writes for p, and what its one action drives:

  K1  `pin_pp[hsh_n[HDR_BYTES*8-1 -: PINW]]` / `<= hsh_n[HDR_BYTES*8-1-2*PINW];`
        header load writes the DATA pin's drive class from the header's mode bit
  K2  `pin_pp[hsh_n[HDR_BYTES*8-1-PINW -: PINW]]` (same right-hand side)
        ... and the CLOCK pin's, from the same bit
  K3  `l_mode[hl]   <= hsh_n[HDR_BYTES*8-1-2*PINW];`
        that bit IS the lane's mode (0 = open-drain): a parked header writes
        `pin_pp[p] <= 0`, nothing else into the class
  K4  `&& hsh_n[HDR_BYTES*8-1-PINW -: PINW] >= 4'd8)` (the `pin_inv` write)
        the only other per-pin header write is the clock inversion, and only
        for a `uo_out` clock (8..11); a park pin is a `uio` pin (0..7, 1.6s,
        `check_open_drain_bank`), so it never reaches `pin_inv`
  K5  `OP_ARM, OP_REARM: ;                 // no pin movement`
        the park word (OP_REARM) drives nothing, so the parked lane never pulls
        the pin low or drives it high: release-only

  =>  parking on p is a no-op on p iff `pin_pp[p]` is 0 whatever the load
      order -- i.e. iff EVERY active lane naming p is open-drain. A push-pull
      user means the park can turn its 1s into releases (lanes load in order):
      refused, explicit or implicit.
"""

from __future__ import annotations

import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENGINE = os.path.join(ROOT, "src", "pe_engine.v")

#: (id, what it establishes, the statement that must be present). Matched with
#: every run of whitespace collapsed to one space, so a statement split over
#: lines is bound WHOLE -- a left-hand side alone would also match a different
#: right-hand side.
ANCHORS = (
    ("K1", "header load writes the data pin's drive class from the mode bit",
     "pin_pp[hsh_n[HDR_BYTES*8-1 -: PINW]] <= hsh_n[HDR_BYTES*8-1-2*PINW];"),
    ("K2", "header load writes the clock pin's drive class from the same bit",
     "pin_pp[hsh_n[HDR_BYTES*8-1-PINW -: PINW]] <= hsh_n[HDR_BYTES*8-1-2*PINW];"),
    ("K3", "that bit is the lane's mode (0 = open-drain)",
     "l_mode[hl] <= hsh_n[HDR_BYTES*8-1-2*PINW];"),
    ("K4", "pin_inv is written only for a uo_out clock (>= 8)",
     "&& hsh_n[HDR_BYTES*8-1-PINW -: PINW] >= 4'd8) "
     "pin_inv[hsh_n[HDR_BYTES*8-1-PINW -: PINW]]"),
    ("K5", "OP_REARM (the park word) moves no pin",
     "OP_ARM, OP_REARM: ; // no pin movement"),
)


class ParkClassError(RuntimeError):
    """An anchor is missing: what a parked header does to its pin is unproven."""


def anchors(text=None):
    """[(id, what, line number)] for every anchor; raises on the first missing."""
    if text is None:
        with open(ENGINE, encoding="utf-8") as fh:
            text = fh.read()
    # collapse whitespace, keeping each collapsed character's source line
    flat, line_of, ln, prev_ws = [], [], 1, False
    for ch in text:
        if ch.isspace():
            if not prev_ws:
                flat.append(" ")
                line_of.append(ln)
            prev_ws = True
        else:
            flat.append(ch)
            line_of.append(ln)
            prev_ws = False
        if ch == "\n":
            ln += 1
    flat = "".join(flat)
    out = []
    for aid, what, needle in ANCHORS:
        at = flat.find(needle)
        hit = line_of[at] if at >= 0 else None
        if hit is None:
            raise ParkClassError(
                "anchor %s (%s) is not in src/pe_engine.v: %r. What a parked "
                "header does to its pin can no longer be read from the RTL, so "
                "no overlap can be proven release-only." % (aid, what, needle))
        out.append((aid, what, hit))
    return out


def release_only(users, text=None):
    """True iff parking on a pin whose ACTIVE users have these modes leaves it
    untouched: the anchors hold and every user is open-drain (mode 0)."""
    anchors(text)
    return all(int(m) == 0 for m in users)
