"""spi_premise -- the SPI target's arming check against its master's SCK premise (Wilson 11-15,
call 4).

An SPI-target lane waits on SCK with ARMs; the word after each (the MISO SHIFT) drives one cycle
after the edge, and its delay -- plus any drain -- sets when the NEXT SCK ARM is released. That
ARM must be armed before the next SCK edge of its polarity can be seen. The premise is the
master's fastest SCK: on the bench, the Pico's firmware setting (premises.PICO_SPI_SCK, today
`assumed`, its hardware witness OWED). So:

  margins(img, lane, t_ext, ready=None)  per SCK ARM: next same-polarity edge (t_ext cycles; half
                     for opposite polarity) - sync skew - 1 - (its release after the previous
                     edge + its certified lateness + 4). None per ARM when the image has no
                     certificate to read lateness from.
  check(img, pid="PICO_SPI_SCK", ready=None, t_ext=None, declared=None)
                     -> (problems, info). A negative margin is a problem ONLY when the premise is
                     stamp-usable (premises.stamp_usable: `read` or `measured`); until then the
                     margins are reported and the check stays out of every certificate.
The compiler has no SPI-target lowering today; the images come from test/make_smoke_image.py
(agent 1), whose builder calls check() -- a program with an SPI-target lane declares its
master's premise ID, as `within` declares `source datasheet`.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(HERE, "a2"), os.path.join(ROOT, "test")):
    if _p not in sys.path:
        sys.path.append(_p)

#: must-fire switch (gate_spi_premise M_SP_NOT_APPLIED): the check never refuses
NOT_APPLIED_MUT = False


def declared_t_ext(img):
    """{lane: SCK period in cycles} the image declares (program_a2.T_EXT_HZ, by sha)"""
    import program_a2 as P
    import pe_isa as I
    return dict(P.T_EXT.get(P.image_sha(I.full_store(bytes(img))), {}))


def margins(img, lane, t_ext, ready=None):
    import branch_budget as BB
    import lane_cert as LC
    import proof_constants as PC
    I = LC._isa()
    g, _p, _gp = LC.build(img, lane, LC.premises(PC.load()), I)
    bb = BB.image_budget(bytes(img), ready={lane: ready} if ready else None)
    lat = bb["lanes"][lane]["lat"] if bb["B"] is not None else None
    skew = LC.SYNC_MAX - LC.SYNC_MIN
    arms = [w for w in g if g[w][0]["op"] == I.OP_ARM]
    out = {}
    for a in arms:
        for p0 in arms:
            path, w = [], (g[p0][1][0] if len(g[p0][1]) == 1 else None)
            while w is not None and w != a and g[w][0]["op"] != I.OP_ARM and len(path) <= len(g):
                path.append(w)
                w = g[w][1][0] if len(g[w][1]) == 1 else None
            if w != a or g[p0][0]["pin"] != g[a][0]["pin"]:
                continue
            ups = [LC.upper_gaps(g[q][0], I) for q in path]
            if any(u is None for u in ups):
                continue
            spacing = t_ext if g[p0][0]["level"] == g[a][0]["level"] else t_ext // 2
            rel = 1 + sum(ups)
            m = None if lat is None else spacing - skew - 1 - (rel + lat.get(a, 0) + 4)
            if a not in out or (m is not None and (out[a] is None or m < out[a])):
                out[a] = m
    return out


def check(img, pid="PICO_SPI_SCK", ready=None, t_ext=None, declared=None):
    import premises as PM
    usable, cite = PM.stamp_usable(pid)
    te = declared if declared is not None else declared_t_ext(img)
    info = {"premise": pid, "usable": usable, "label": PM.REGISTRY[pid]["label"], "lanes": {}}
    probs = []
    for ln, t in sorted(te.items()):
        t = t_ext or t
        ms = margins(img, ln, t, ready)
        known = [m for m in ms.values() if m is not None]
        info["lanes"][ln] = {"t_ext": t, "min_margin": min(known) if known else None,
                             "unknown": sum(1 for m in ms.values() if m is None)}
        if usable and known and min(known) < 0 and not NOT_APPLIED_MUT:
            probs.append("lane %d: SPI-target SCK ARM margin %d < 0 at SCK period %d (premise %s): "
                         "an ARM may be armed after the next SCK edge" % (ln, min(known), t, pid))
    return probs, info
