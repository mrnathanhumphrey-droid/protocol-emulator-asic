"""poset golden -- the ORDER-AND-BOUNDS golden model (Agent 2, 11-12; brief item 2).

Wire transitions in, poset-spec statements out (host/poset/POSET_SPEC.md).
Written from the protocol definitions and the spec's own semantics, never from the RTL.

  trace   : (init, trans). init = {wire: level}; trans = [(cycle, wire, level)], time-ordered
  extract : trace -> {(kind, wires): [cycle, ...]}, the spec's closed event vocabulary
  pairs   : the instance pairs one pattern relates (nth-to-nth for `->`, next-in-alphabet for `|>`)
  infer   : candidates -> statements, every bound `observed n` (the PIT never writes a datasheet bound)

Verdict discipline (guiding doc §5): a pattern with no instance pairs is ABSTAIN, never "holds".
A pattern with a violating pair is not emitted as an order. If both orders were seen it becomes `||`.

Mutants for the gate's must-fires: env POSET_GOLDEN_MUTANT (one name; see MUTANTS).
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "model"))
import clock  # noqa: E402

#: each must turn run_poset_golden red; the gate reads this list (no second copy)
MUTANTS = ("M_PG_SWAP",       # `->` compares the wrong way round
           "M_PG_IMM_LOOSE",  # `|>` skips intervening events of the pattern's own alphabet
           "M_PG_DUR_OFF1",   # every duration one cycle long
           "M_PG_NO_LABEL",   # bounds printed without `observed n`
           "M_PG_ABSTAIN")    # no evidence reported as an order that holds
MUT = os.environ.get("POSET_GOLDEN_MUTANT", "")
if MUT and MUT not in MUTANTS:
    raise SystemExit("poset golden: unknown mutant %r" % MUT)

RAW = ("Rise", "Fall", "Edge")


def key(kind, *wires):
    return (kind, tuple(wires))


def name(k):
    return "%s(%s)" % (k[0], ", ".join("uio%d" % w for w in k[1]))


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------

def extract(init, trans, i2c=(), uart=None):
    """-> {(kind, wires): [cycles]}. `i2c`: [(sda, scl)]; `uart`: {wire: bit_cycles}.
    Raw events on every wire; Start / Stop / Byte for the declared I2C pairs; Frame (the start
    bit's falling edge) and Byte (the sample instant of the last data bit, 8.5 bit times after
    it) for the declared UART wires."""
    uart = uart or {}
    lv = dict(init)
    ev: dict = {}

    def add(k, t):
        ev.setdefault(k, []).append(t)

    # per-I2C-pair state: inside a transfer, SCL rises counted since START (9 per byte)
    i2s = {p: None for p in i2c}
    # per-UART-wire state: cycle the current frame ends (falls before it are data)
    ubusy = {w: -1 for w in uart}
    for t, w, v in trans:
        if lv.get(w) == v:
            continue
        old = lv.get(w)
        lv[w] = v
        add(key("Rise" if v else "Fall", w), t)
        add(key("Edge", w), t)
        for p in i2c:
            sda, scl = p
            if w == sda and lv.get(scl) == 1:
                if v == 0:
                    add(key("Start", sda, scl), t)
                    i2s[p] = 0
                else:
                    add(key("Stop", sda, scl), t)
                    i2s[p] = None
            elif w == scl and v == 1 and i2s[p] is not None:
                i2s[p] += 1
                if i2s[p] % 9 == 8:                     # the 8th data bit's sample edge
                    add(key("Byte", sda), t)
        if w in uart and v == 0 and old == 1 and t > ubusy[w]:
            T = uart[w]
            add(key("Frame", w), t)                     # the start bit's edge (a raw Fall also
            #                                             matches data-bit falls inside the frame)
            add(key("Byte", w), t + (17 * T) // 2)      # mid of bit 7 = 8.5 T after the start edge
            ubusy[w] = t + 10 * T - T // 2              # through the stop bit's sample
    return ev


# ---------------------------------------------------------------------------
# pairs
# ---------------------------------------------------------------------------

def pairs(ev, a, op, b):
    """-> (pairs [(ta, tb)], violations [(ta, tb or None)], abstain count).
    `->`: nth A with nth B over the common count; a violation is tb <= ta.
    `|>`: each A with the next event in the alphabet {A, B} (ties: B first only if strictly
    later); a violation is the next event being another A, or a B at the same cycle;
    an A with nothing after it is an abstain, not a violation (presence, never absence)."""
    A, B = ev.get(a, []), ev.get(b, [])
    ok, bad, abst = [], [], 0
    if op == "->":
        for ta, tb in zip(A, B):
            later = (tb < ta) if MUT == "M_PG_SWAP" else (tb > ta)
            (ok if later else bad).append((ta, tb))
        abst = abs(len(A) - len(B))
        return ok, bad, abst
    if op == "|>":
        merged = sorted([(t, 0, "A") for t in A] + [(t, 1, "B") for t in B])
        for i, (t, _o, s) in enumerate(merged):
            if s != "A":
                continue
            nxt = merged[i + 1:]
            if MUT == "M_PG_IMM_LOOSE":
                nxt = [x for x in nxt if x[2] == "B"]
            if not nxt:
                abst += 1
            elif nxt[0][2] == "B" and nxt[0][0] > t:
                ok.append((t, nxt[0][0]))
            else:
                bad.append((t, nxt[0][0] if nxt[0][2] == "B" else None))
        return ok, bad, abst
    raise ValueError("operator %r: the golden checks -> and |> (|| is inferred, not checked)" % op)


# ---------------------------------------------------------------------------
# inference
# ---------------------------------------------------------------------------

def _ns(cycles, hz):
    return "%.4f" % (cycles * 1e9 / hz)


def infer(ev, cands, hz=None):
    """cands: [(A, op, B)] -> [record]. A record is a dict with the verdict
    (ORDER / BOTH / VIOLATION / ABSTAIN), the counts, the bounds in cycles and the
    statement text (None unless ORDER or BOTH)."""
    hz = hz or clock.hz()
    out = []
    for a, op, b in cands:
        ok, bad, abst = pairs(ev, a, op, b)
        r = {"a": a, "op": op, "b": b, "n": len(ok), "violations": len(bad),
             "abstain": abst, "min": None, "max": None, "text": None}
        if not ok and not bad:
            r["verdict"] = "ABSTAIN"
            if MUT == "M_PG_ABSTAIN":
                r["verdict"], r["text"] = "ORDER", "pattern %s %s %s;" % (name(a), op, name(b))
        elif bad:
            rev = [p for p in bad if p[1] is not None and p[1] < p[0]]
            if ok and rev:
                r["verdict"] = "BOTH"
                r["text"] = "pattern %s || %s observed %d;" % (name(a), name(b), len(ok) + len(bad))
            else:
                r["verdict"] = "VIOLATION"
        else:
            d = [tb - ta + (1 if MUT == "M_PG_DUR_OFF1" else 0) for ta, tb in ok]
            r["verdict"], r["min"], r["max"] = "ORDER", min(d), max(d)
            lab = "" if MUT == "M_PG_NO_LABEL" else " observed %d" % len(ok)
            r["text"] = "pattern %s %s %s during (%s ns, %s ns)%s;" % (
                name(a), op, name(b), _ns(min(d), hz), _ns(max(d), hz), lab)
        out.append(r)
    return out
