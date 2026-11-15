"""gate_live_price -- programs assembled at run time are priced live (Wilson 11-15, item 5).

  L1 THE SAME FUNCTION: for every image in the record (model/branch_budget.json), the live price
     (live_price.price) equals the record's entry -- stamp, B and reason -- so the live path is
     the record's own certificate, not a second one
  L2 RUN-TIME PROGRAMS: programs built now, outside the record (pe_asm's assembling self-test
     programs; the UART receive and transmit builders at bit periods the record does not hold),
     are each priced: the stamp is present, never "no budget record", and pricing twice gives
     the same result. Each prints its report line.
Must-fires (in-process): M_LP_RECORD_ONLY (price from the record lookup only: a run-time
program with an unclocked SHIFT lane reads "no budget record" -> L2 red) and M_LP_STALE (one
record entry's B moved by 4 -> L1 red).
Static; about a second per hundred images. POSITIVE TOKEN: `GATE live_price: PASSED`.
"""
from __future__ import annotations

import copy
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(HERE, "a2"), os.path.join(ROOT, "test")):
    if _p not in sys.path:
        sys.path.append(_p)
import live_price as LP  # noqa: E402

#: the run-time builders' parameters: bit periods the record does not hold (L2 checks that)
UART_RX_T = (300, 400)
UART_TX_T = (300,)


def runtime_programs():
    """[(name, image)] assembled now"""
    import pe_asm as S
    import uart_rx
    import uart_tx
    out = []
    for f in sorted(n for n in dir(S) if n.startswith("_demo_")):
        prog = getattr(S, f)()
        try:
            out.append(("pe_asm.%s" % f, bytes(S.assemble(*prog[:2]))))
        except S.Reject:
            continue
    for t in UART_RX_T:
        out.append(("uart_rx.build(T=%d)" % t, bytes(uart_rx.build(t))))
    for t in UART_TX_T:
        out.append(("uart_tx.build(T=%d)" % t, bytes(uart_tx.build(t))))
        out.append(("uart_tx.build(T=%d, busy)" % t, bytes(uart_tx.build(t, busy=True))))
    return out


def l1(rec=None):
    import gen_branch_budget as GB
    rec = rec if rec is not None else GB.load()["images"]
    probs, n = [], 0
    for name, img in GB.corpus():
        e = rec.get(name)
        if e is None:
            continue
        n += 1
        p = LP.price(img)
        got = (p["stamp"], p["B"], p["reason"])
        want = (e.get("cert"), e.get("B"), e.get("reason"))
        if got != want:
            probs.append("L1 %s: live %s, record %s" % (name, got, want))
    return probs, n


def l2(verbose=False):
    import cert_stamp as CS
    probs, rows = [], []
    for name, img in runtime_programs():
        if CS.budget_entry(img) is not None:
            probs.append("L2 %s is in the record: not a run-time program" % name)
            continue
        p1, p2 = LP.price(img), LP.price(img)
        if p1 != p2:
            probs.append("L2 %s: two prices differ" % name)
        if "no budget record" in (p1["stamp"].get("reason") or ""):
            probs.append("L2 %s: priced from the record lookup (%s)" % (name, p1["stamp"]["reason"]))
        rows.append("  %-36s %s" % (name, LP.line(p1)))
    return probs, rows


def main():
    p1, n1 = l1()
    p2, rows = l2()
    print("L1 live price == record entry on %d record images: %s" % (n1, "ok" if not p1 else "FAIL"))
    print("L2 %d run-time programs priced live: %s" % (len(rows), "ok" if not p2 else "FAIL"))
    for r in rows:
        print(r)
    probs = p1 + p2
    for p in probs[:20]:
        print("  ***", p)
    # must-fires
    mf = []
    LP.RECORD_ONLY_MUT = True
    try:
        mf.append(("M_LP_RECORD_ONLY", bool(l2()[0])))
    finally:
        LP.RECORD_ONLY_MUT = False
    import gen_branch_budget as GB
    rec = copy.deepcopy(GB.load()["images"])
    victim = next((k for k, v in sorted(rec.items()) if v.get("B") is not None), None)
    if victim:
        rec[victim]["B"] += 4
    mf.append(("M_LP_STALE", bool(victim) and bool(l1(rec)[0])))
    for name, red in mf:
        print("  must-fire %-18s %s" % (name, "RED (killed)" if red else "*** SURVIVED"))
    probs += [n for n, red in mf if not red]
    print("GATE live_price: %s" % ("PASSED" if not probs else "FAILED (%d)" % len(probs)))
    return 1 if probs else 0


if __name__ == "__main__":
    raise SystemExit(main())
