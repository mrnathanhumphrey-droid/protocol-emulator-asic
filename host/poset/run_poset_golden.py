#!/usr/bin/env python3
"""run_poset_golden -- the gate for the order-and-bounds golden model (host/poset/golden.py).

THE PEERS ARE INDEPENDENT (guiding doc Â§5): the buses below are generated here from the
protocol definitions, and each generator RECORDS the truth as it draws it (the order, the
instance count, every drawn lead / hold / span). The golden only ever sees the wire
transitions. The answer key is the generator's own record, never the golden's output.

Arms
  P1 SPI mode 0   : CS falls before the first SCLK rise      Fall(cs) |> Rise(sclk)
  P2 I2C          : START before SCL's first fall            Start |> Fall(scl)
                    START before the first byte              Start |> Byte(sda)
                    each START before its STOP                Start -> Stop
  P3 UART         : start bit before the byte                Frame(rx) |> Byte(rx)
                    (and a raw Fall(rx) |> Byte(rx) must NOT come out as an order)
  N1 SPI, one frame aborted (CS asserted with no clock)       -> VIOLATION, never an order
  N2 two free-running wires, both orders seen                  -> BOTH (`||`), never `->`
  N3 a wire with no events                                     -> ABSTAIN, never an order
Every ORDER statement must carry `observed n`, n = the generator's own count, and its
`during` bounds must equal the generator's drawn min / max, converted at clock.hz().

Must-fires: every golden.MUTANTS entry, run IN-PROCESS through the same judge, must turn this gate red.

POSITIVE TOKEN: `GATE poset_golden: PASSED`.
"""
from __future__ import annotations

import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import golden as G  # noqa: E402
from golden import key  # noqa: E402

#: gate_mutant_kills' scratch-mutant registry (ruling AC2): this gate is the killer
SCRATCH_MUTANTS = {
    "M_PG_SWAP": "killed in-process by this gate",
    "M_PG_IMM_LOOSE": "killed in-process by this gate",
    "M_PG_DUR_OFF1": "killed in-process by this gate",
    "M_PG_NO_LABEL": "killed in-process by this gate",
    "M_PG_ABSTAIN": "killed in-process by this gate",
}
#: the literal above must name exactly the module's MUTANTS (checked at start-up)
if set(SCRATCH_MUTANTS) != set(G.MUTANTS):
    raise SystemExit("GATE poset_golden: FAILED -- SCRATCH_MUTANTS differs from G.MUTANTS")

HZ = G.clock.hz()


def ns(c):
    return "%.4f" % (c * 1e9 / HZ)


# ---------------------------------------------------------------------------
# the peers: generators that record their own truth
# ---------------------------------------------------------------------------

class Bus:
    def __init__(self, init):
        self.init, self.lv, self.tr = dict(init), dict(init), []

    def set(self, t, w, v):
        if self.lv[w] != v:
            self.tr.append((t, w, v))
            self.lv[w] = v

    def trace(self):
        return self.init, sorted(self.tr, key=lambda x: x[0])


def spi(seed, frames=40, H=6, CS=3, CK=1, DO=2, abort_at=None):
    """mode 0. Truth: leads (CS fall -> first SCLK rise), one per clocked frame."""
    rnd = random.Random(seed)
    b = Bus({CS: 1, CK: 0, DO: 0})
    t, leads = 100, []
    for k in range(frames):
        b.set(t, CS, 0)
        if k == abort_at:                      # N1: asserted, then released, no clock
            t += 3 * H
            b.set(t, CS, 1)
            t += 10 * H
            continue
        L = rnd.randint(2, 120)
        leads.append(L)
        tc = t + L
        byte = rnd.randrange(256)
        for i in range(8):
            b.set(tc - 1, DO, (byte >> (7 - i)) & 1)
            b.set(tc, CK, 1)
            b.set(tc + H, CK, 0)
            tc += 2 * H
        b.set(tc + H, CS, 1)
        t = tc + H + rnd.randint(5, 200)
    return b, leads


def i2c(seed, msgs=24, H=40, SDA=2, SCL=1):
    """Truth per message: hd (START -> SCL fall), first-byte span (START -> 8th SCL rise),
    whole span (START -> STOP)."""
    rnd = random.Random(seed)
    b = Bus({SDA: 1, SCL: 1})
    t, hds, firsts, spans = 100, [], [], []
    for _ in range(msgs):
        t0 = t
        b.set(t, SDA, 0)                        # START: SDA falls, SCL high
        hd = rnd.randint(36, 54)
        hds.append(hd)
        t += hd
        b.set(t, SCL, 0)
        first = None
        for k in range(rnd.randint(1, 3)):
            byte = rnd.randrange(256)
            for i, bit in enumerate([(byte >> (7 - j)) & 1 for j in range(8)] + [0]):
                b.set(t + H // 2, SDA, bit)     # data moves while SCL is low
                b.set(t + H, SCL, 1)
                if k == 0 and i == 7:
                    first = t + H - t0
                b.set(t + 2 * H, SCL, 0)
                t += 2 * H
        b.set(t + H // 2, SDA, 0)               # STOP: SDA rises while SCL high
        b.set(t + H, SCL, 1)
        b.set(t + 2 * H, SDA, 1)
        spans.append(t + 2 * H - t0)
        firsts.append(first)
        t += 2 * H + rnd.randint(50, 400)
    return b, hds, firsts, spans


def uart(seed, frames=48, RX=0):
    """8N1, LSB first. Truth: the byte's last-data-bit sample instant, 8.5 bit times after
    the start edge (the spec's Byte instant, by definition), one per frame."""
    rnd = random.Random(seed)
    T = int(round(G.clock.per_rate(115200)))
    b = Bus({RX: 1})
    t, spans = 100, []
    for _ in range(frames):
        byte = rnd.randrange(256)
        b.set(t, RX, 0)
        for i in range(8):
            b.set(t + (i + 1) * T, RX, (byte >> i) & 1)
        b.set(t + 9 * T, RX, 1)
        spans.append((17 * T) // 2)
        t += 10 * T + rnd.randint(0, 5 * T)
    return b, T, spans


def free(seed, n=30, A=4, B=5):
    """two wires, one rise each per period, relative order drawn; both orders forced."""
    rnd = random.Random(seed)
    b = Bus({A: 0, B: 0})
    t = 100
    for k in range(n):
        da, db = rnd.randint(0, 30), rnd.randint(0, 30)
        if k == 0:
            da, db = 0, 10
        if k == 1:
            da, db = 10, 0
        if da == db:
            db += 1
        b.set(t + da, A, 1); b.set(t + db, B, 1)
        b.set(t + 50, A, 0); b.set(t + 50, B, 0)
        t += 100
    return b


# ---------------------------------------------------------------------------
# the judge
# ---------------------------------------------------------------------------

def expect_order(probs, rec, n, lo, hi, tag):
    if rec["verdict"] != "ORDER":
        probs.append("%s: verdict %s, expected ORDER" % (tag, rec["verdict"]))
        return
    if rec["n"] != n:
        probs.append("%s: %d instance pairs, the generator made %d" % (tag, rec["n"], n))
    if (rec["min"], rec["max"]) != (lo, hi):
        probs.append("%s: bounds %s..%s cycles, the generator drew %d..%d"
                     % (tag, rec["min"], rec["max"], lo, hi))
    want = "during (%s ns, %s ns) observed %d;" % (ns(lo), ns(hi), n)
    if not (rec["text"] or "").endswith(want):
        probs.append("%s: statement %r does not end %r" % (tag, rec["text"], want))


def judge():
    probs, lines = [], []

    b, leads = spi(1)
    ev = G.extract(*b.trace())
    r = G.infer(ev, [(key("Fall", 3), "|>", key("Rise", 1))], HZ)[0]
    expect_order(probs, r, len(leads), min(leads), max(leads), "P1 SPI CS before SCLK")
    lines.append(r["text"])

    b, hds, firsts, spans = i2c(2)
    ev = G.extract(*b.trace(), i2c=[(2, 1)])
    st = key("Start", 2, 1)
    rs = G.infer(ev, [(st, "|>", key("Fall", 1)), (st, "|>", key("Byte", 2)),
                      (st, "->", key("Stop", 2, 1))], HZ)
    expect_order(probs, rs[0], len(hds), min(hds), max(hds), "P2 I2C START before SCL fall")
    expect_order(probs, rs[1], len(firsts), min(firsts), max(firsts), "P2 I2C START before byte")
    expect_order(probs, rs[2], len(spans), min(spans), max(spans), "P2 I2C START before STOP")
    lines += [x["text"] for x in rs]

    b, T, spans = uart(3)
    ev = G.extract(*b.trace(), uart={0: T})
    r = G.infer(ev, [(key("Frame", 0), "|>", key("Byte", 0))], HZ)[0]
    expect_order(probs, r, len(spans), min(spans), max(spans), "P3 UART start before byte")
    lines.append(r["text"])
    # the raw Fall is NOT the start bit: data-bit falls sit inside the frame, so `|>` from a
    # Fall must be refused (finding 11-12; the spec's first UART example was wrong)
    r = G.infer(ev, [(key("Fall", 0), "|>", key("Byte", 0))], HZ)[0]
    if r["verdict"] == "ORDER":
        probs.append("P3b UART raw Fall |> Byte: ORDER, but data-bit falls intervene")

    b, _ = spi(4, abort_at=17)
    ev = G.extract(*b.trace())
    r = G.infer(ev, [(key("Fall", 3), "|>", key("Rise", 1))], HZ)[0]
    if r["verdict"] != "VIOLATION" or r["violations"] != 1:
        probs.append("N1 aborted SPI frame: verdict %s with %d violations, expected VIOLATION x1"
                     % (r["verdict"], r["violations"]))

    b = free(5)
    ev = G.extract(*b.trace())
    r = G.infer(ev, [(key("Rise", 4), "->", key("Rise", 5))], HZ)[0]
    if r["verdict"] != "BOTH" or "||" not in (r["text"] or ""):
        probs.append("N2 both orders seen: verdict %s, expected BOTH (`||`)" % r["verdict"])

    r = G.infer({}, [(key("Rise", 6), "->", key("Rise", 7))], HZ)[0]
    if r["verdict"] != "ABSTAIN" or r["text"] is not None:
        probs.append("N3 no evidence: verdict %s, expected ABSTAIN with no statement" % r["verdict"])

    for x in lines:
        if x and " during " in x and " observed " not in x:
            probs.append("unlabelled bound: %r" % x)
    return probs, lines


def main() -> int:
    if os.environ.get("POSET_GOLDEN_MUTANT"):
        probs, _ = judge()
        print("MUTANT %s: %s" % (os.environ["POSET_GOLDEN_MUTANT"], "RED" if probs else "green"))
        for p in probs[:3]:
            print("   ", p)
        return 1 if probs else 0
    print("poset golden: order-and-bounds on known buses (clock %d Hz)" % HZ)
    probs, lines = judge()
    for x in lines:
        print("   ", x)
    for p in probs:
        print("  ***", p)
    killed = []
    for m in G.MUTANTS:
        # IN-PROCESS, through the same `judge`: gate_meta's always-pass stub on `judge` then
        # hides the mutants too, so the stubbed gate goes red (a subprocess would not see it)
        G.MUT = m
        try:
            mp, _ = judge()
        except Exception as e:                      # a mutant that crashes the judge is red
            mp = ["crash: %r" % e]
        finally:
            G.MUT = ""
        red = bool(mp)
        print("  must-fire %-15s %s  %s" % (m, "RED (killed)" if red else "*** SURVIVED",
                                            (mp[0] if mp else "")[:80]))
        if not red:
            probs.append("mutant %s survived" % m)
        else:
            killed.append(m)
    if probs:
        print("GATE poset_golden: FAILED (%d)" % len(probs))
        return 1
    print("GATE poset_golden: PASSED (clean exact; %d / %d mutants killed)"
          % (len(killed), len(G.MUTANTS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
