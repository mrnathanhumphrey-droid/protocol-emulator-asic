#!/usr/bin/env python3
"""drain_table -- Wilson 11-15 call 1: J per lane shape under the three levels of fix.

The root (Wilson): a lane spaced at exactly D* has no slack, so lateness never drains. Three
levels: the LOWERING adds spacing (a), the CERTIFICATE uses the peer's premise, the RTL
PREFETCHES the successor. For every shape with a peer wire this reports the lane's J
(1 + its largest certified lateness; "-" = no lateness certificate) and the image's B for:

  built     the image as it is (the compiler's c23c6de lowering for `within` lanes)
  (a)       spacing after the reactive release: the first word on the ARM's edge path gets
            `drain` more cycles (the smallest of DRAINS giving the least J; the compiler's
            `drain` option for `within` lanes, the image's word patched for universe shapes)
  premise   the peer premise in the certificate: the ARM's successor released no earlier
            than the peer allows (model/premises.py; each row names it and its label)
  (a)+prem  both
  prefetch  agent 1's note: the ARM's successors READY at release (lateness stops at the
            ARM) -- a counterfactual of RTL that prefetches them, with the image as built
  prefetch+(a)  both: what the prefetch leaves for the lowering's spacing
`within` lanes are built for both arming placements (late = c23c6de; early = at A + D*,
which is what gives a premise its room). Static; the certificate only, no simulation.
Writes comms/drain_table.md (gitignored) and prints the table.
"""
from __future__ import annotations

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for _p in (HERE, os.path.join(ROOT, "model"), os.path.join(ROOT, "model", "a2"),
           os.path.join(ROOT, "test")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

def _drains():
    import compile as C
    return tuple(range(0, C.drain_max() + 1))     # EVERY value up to the generated limit (a sparse
    # grid reported 17 as 20, then m1 33 as 40 and b3b 34 as none)


DRAINS = _drains()


def _j(bb, lane):
    if bb["B"] is None:
        return None, None
    ln = bb["lanes"].get(lane) or bb["lanes"].get(str(lane))
    return (None if ln is None else 1 + ln["max_late"]), bb["B"]


def _cell(results):
    """least J over the drain search -> 'J (B, drain)'"""
    ok = [(j, d, b) for d, (j, b) in results if j is not None]
    if not ok:
        return "-"
    j, d, b = min(ok, key=lambda t: (t[0], t[1]))
    return "%d (B %d%s)" % (j, b, ", +%d" % d if d else "")


# ---------------------------------------------------------------------------
# `within` lanes: the compiler, for real
# ---------------------------------------------------------------------------

def within_rows():
    import compile as C
    import run_poset_compile as RPC
    import pit_emit
    import run_pit_emit as V1T
    hz = C.clock.hz()
    rows = []
    cases = [("SPI master, CS fall -> peer B", RPC.WIN, "spi", "Fall(uio3)")]
    for v1 in ("uart_crc", "i2c"):
        cases.append(("%s lowering, first A -> peer B" % v1, None, v1, None))
    for name, tmpl, v1, a_ev in cases:
        base = pit_emit.emit(bytes(V1T.IMAGES[v1]()), hz).rstrip("\n").splitlines()
        if tmpl is None:
            # the lowering's own driven wires: A = the first Fall on a wire it drives
            parsed = C.S.parse("\n".join(base) + "\n")
            try:
                _img, low, route = C.lower(parsed["v1"], 7)
            except C.Refused as e:
                rows.append((name, "-", "lowering refused: %s" % str(e)[:60]))
                continue
            touched = C._touched(low[0], low[1])
            wires = [w for w in range(8) if C._route_pin(route, w) in touched]
            free = [w for w in range(8) if C._route_pin(route, w) is None]
            if not wires or not free:
                rows.append((name, "-", "no driven wire / no free wire"))
                continue
            stmt_ = ("pattern Fall(uio%d) -> Fall(uio%d) within (2000 ns, 10000 ns) else %%s "
                     "source datasheet \"X\";" % (wires[0], free[0]))
        else:
            stmt_ = tmpl
        for kind in ("abort", "continue"):
            text = "\n".join(base[:-1] + ["  " + (stmt_ % kind)] + [base[-1]]) + "\n"
            parsed = C.S.parse(text)
            try:
                _img, low, route = C.lower(parsed["v1"], 7)
            except C.Refused as e:
                rows.append(("%s, else %s" % (name, kind), "-", "refused: %s" % str(e)[:60]))
                continue
            cells = {}
            lane = None
            for arm in ("late", "early"):
                for col, prem, drains, ready in (("built", None, (0,), False),
                                                 ("(a)", None, DRAINS, False),
                                                 ("premise", "spec", (0,), False),
                                                 ("(a)+prem", "spec", DRAINS, False),
                                                 ("prefetch", None, (0,), True),
                                                 ("prefetch+(a)", None, DRAINS, True)):
                    res = []
                    for d in drains:
                        try:
                            _l, _r, w = C.windows(parsed["poset"], low, route, hz, arm=arm, counterfactual=True,
                                                  drain=d, premise=prem, ready=ready)
                        except C.Refused as e:
                            res.append((d, (None, None)))
                            cells[(arm, col, "why")] = str(e)[:60]
                            continue
                        lane = w["windows"][0]["lane"] if w and w["windows"] else lane
                        res.append((d, _j(w["budget"], lane)))
                    cells[(arm, col)] = _cell(res)
            for arm in ("late", "early"):
                rows.append(("%s, else %s, arm %s" % (name, kind, arm), lane,
                             " | ".join(cells.get((arm, c), "-") for c in
                                        ("built", "(a)", "premise", "(a)+prem", "prefetch",
                                         "prefetch+(a)"))
                             + ("   [%s]" % cells[(arm, "built", "why")]
                                if (arm, "built", "why") in cells else "")))
    return rows


# ---------------------------------------------------------------------------
# the universe's peer shapes: premises per shape
# ---------------------------------------------------------------------------

def _patch(img, word, extra, I):
    a = I.ACT_BASE + word * I.ACT_BYTES
    x = I._unpack(I.ACT_FIELDS, img[a:a + I.ACT_BYTES], I.ACT_BYTES)
    if x["op"] == I.OP_ARM:
        # ⛔ an ARM's delay field is its TIMEOUT, not a spacing: a word after an ARM that is
        # itself an ARM (SPI modes 1 / 3: the CS ARM then the first SCK ARM) is left alone
        # (found 11-15: m1 / m3's "+40" came from timing an untimed ARM)
        return img
    if x["delay"] + extra > (1 << I.DLY_W) - 1:
        return None
    new = I.act(x["op"], x["pin"], x["level"], x["delay"] + extra, count=x["count"], q=x["q"],
                pinb=x["pinb"], mod=x["mod"])
    return img[:a] + bytes(new) + img[a + I.ACT_BYTES:]


def shape_premise(img, lane, I, g, gaps):
    """({ARM word: premise release gap}, premise ID, label) for the shapes with a peer premise:
    the UART receive loop (arm_gate's frame), the SPI target (the master's SCK period)."""
    import branch_budget as BB
    import lane_cert as LC
    import premises as PM
    import program_a2 as P
    from fractions import Fraction
    bit = I.read_header(img, lane)["t"]
    ag = BB.arm_gate(img, lane, (g, None, gaps), {w: 0 for w in g}, I)
    if ag:
        # UART: the next start edge seen >= E + edge_min; the ARM released <= E + hi
        out = {}
        for a in ag:
            path, w = [], g[a][1][0]
            while w != a:
                path.append(w)
                w = g[w][1][0]
            hi = 1 + sum(LC.upper_gaps(g[p][0], I) for p in path)
            data = [p for p in path if g[p][0]["op"] == I.OP_SHIFTIN and g[p][0]["delay"] == bit]
            err = Fraction(BB.uart_peer_err(), 1000)
            edge_min = math.floor((len(data) + 2) * bit * (1 - err)) - (LC.SYNC_MAX - LC.SYNC_MIN)
            out[a] = edge_min + 1 - hi
        return out, "UART_PEER_BAND", PM.REGISTRY["UART_PEER_BAND"]["label"]
    t_ext = P.T_EXT.get(P.image_sha(I.full_store(bytes(img))), {}).get(lane)
    if t_ext:
        # SPI target: consecutive same-polarity SCK edges >= one period apart; an ARM's
        # previous ARM on the chain saw E_prev, this ARM is released <= E_prev + 1 + ups
        out = {}
        arms = [w for w in g if g[w][0]["op"] == I.OP_ARM]
        for a in arms:
            for p0 in arms:
                path, w, ok = [], g[p0][1][0] if len(g[p0][1]) == 1 else None, True
                while w is not None and w != a and len(path) <= len(g):
                    if g[w][0]["op"] == I.OP_ARM:
                        ok = False
                        break
                    path.append(w)
                    w = g[w][1][0] if len(g[w][1]) == 1 else None
                ups = [LC.upper_gaps(g[q][0], I) for q in path]
                if not ok or w != a or any(u is None for u in ups):
                    continue
                same = (g[p0][0]["pin"], g[p0][0]["level"]) == (g[a][0]["pin"], g[a][0]["level"])
                if g[p0][0]["pin"] != g[a][0]["pin"]:
                    continue
                spacing = t_ext if same else t_ext // 2
                out[a] = min(out.get(a, 10 ** 9),
                             spacing - (LC.SYNC_MAX - LC.SYNC_MIN) + 1 - (1 + sum(ups)))
        return out, "PICO_SPI_SCK", PM.REGISTRY["PICO_SPI_SCK"]["label"]
    return {}, None, "no premise registered for this shape"


def universe_rows():
    import image_universe as U
    import lane_cert as LC
    import proof_constants as PC
    import branch_budget as BB
    I = LC._isa()
    prem = LC.premises(PC.load())
    rows, seen = [], set()
    for name, img in U.images():
        progs = I.lane_programs(img)
        usb = PC.usb_receive_live(progs, I)
        for lane in sorted(progs):
            if usb and lane == I.USB_LANE:
                continue
            g, _p, gaps = LC.build(img, lane, prem, I)
            arms = [w for w in g if g[w][0]["op"] == I.OP_ARM]
            if not arms:
                continue
            key = (bytes(I.full_store(bytes(img))), lane)       # per image: J is the image's
            if key in seen:
                continue
            seen.add(key)
            pg, pid, label = shape_premise(img, lane, I, g, gaps)
            succ = {s for a in arms for s in g[a][1]}
            cells = []
            for col, use_p, drains, ready in (("built", False, (0,), False),
                                              ("(a)", False, DRAINS, False),
                                              ("premise", True, (0,), False),
                                              ("(a)+prem", True, DRAINS, False),
                                              ("prefetch", False, (0,), True),
                                              ("prefetch+(a)", False, DRAINS, True)):
                if use_p and not pg:
                    cells.append("n/a")
                    continue
                res = []
                for d in drains:
                    im = img
                    for a in arms:
                        if d and im is not None:
                            for s in g[a][1]:
                                im = _patch(im, s, d, I) if im is not None else None
                    if im is None:
                        res.append((d, (None, None)))
                        continue
                    bb = BB.image_budget(im, premise_gaps={lane: pg} if use_p else None,
                                         ready={lane: succ} if ready else None)
                    res.append((d, _j(bb, lane)))
                cells.append(_cell(res))
            rows.append(("%s lane %d (%d ARMs, spacings %s)%s" % (
                name, lane, len(arms), sorted({g[w][0]["delay"] for w in g
                                               if g[w][0]["op"] != I.OP_ARM})[:4],
                " + USB" if usb else ""), lane,
                " | ".join(cells) + "   [premise: %s; %s]" % (pid or "none", label)))
    return rows


def main():
    rows = within_rows() + universe_rows()
    hdr = "shape | lane | built | (a) | premise | (a)+prem | prefetch | prefetch+(a)"
    out = ["# J per lane shape (Wilson 11-15, call 1) -- generated by host/poset/drain_table.py",
           "", "Each cell: J (B, +drain cycles when (a) used one); '-' = no lateness certificate.",
           "", hdr]
    for name, lane, cells in rows:
        out.append("%s | %s | %s" % (name, lane, cells))
    text = "\n".join(out) + "\n"
    print(text)
    os.makedirs(os.path.join(ROOT, "comms"), exist_ok=True)
    with open(os.path.join(ROOT, "comms", "drain_table.md"), "w", encoding="utf-8") as fh:
        fh.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
