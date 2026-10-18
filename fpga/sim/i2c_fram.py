"""The I2C FRAM build (OW = 2): its program, its feed, its SCL-fall model.

THE PROGRAM -- the shipped Fast-mode I2C lane (ruling CE1: HALF_HIGH at
`run_ckack.d_half_fm()`), on SDA = uio[2] / SCL = uio[1], ONE PASS:
  T1  random read  S A0 a 00 a 10 a Sr A1 a [d0] A [d1] A [d2] A [d3] N P
      -- the OLD contents of FRAM 0x0010..0x0013
  T2  write        S A0 a 00 a 10 a D0 a D1 a D2 a D3 a P
      -- D0..D3 are the PC's fresh random bytes (sent after 'G')
  T3  random read  as T1 -- must return D0..D3
then a level-0 REARM, which does not retire: the lane PARKS (pe_isa:
"a lane that falls off its program PARKS"). No second pass, so the feed
just ends -- no idle bytes, no underrun after it.

THE FEED (12-bit words, fpga/feeds/i2c_fram_feed.hex): `0xx` = byte xx;
`20s` = the PC's data byte number s. One word per SHIFT, in pop order.
Master ACK = 2D, NACK = C4: only the MSB of a 1-bit SHIFT reaches the wire
(as test/tb_ckack.v), and distinct bytes keep the two identifiable.

THE SCL-FALL COUNT MODEL (Wilson 1a), MEASURED, then checked every run:
  * every START and repeated START: ONE fall (counted explicitly);
  * every clocked bit (data, ACK slot, master ACK/NACK): one fall;
  * LEVEL / STOP / REARM: none;
  * a SHIFT's queue pop comes BEFORE its own bits' falls.
FALLS[k] = falls before byte k's pop. The discovery bench (probe, chip fed
by queue count) matched all 23 pops and the total, 212 = 5 STARTs + 207
bits; run_fpga_i2c.py re-checks FALLS against every simulated pop.

THE RECEIVES: one per SHIFTIN -- the ACK slots (ACK bit = rx & 1, 0 = ACK)
and the 8 data bytes.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for _d in ("test", "model"):
    if os.path.join(ROOT, _d) not in sys.path:
        sys.path.insert(0, os.path.join(ROOT, _d))
import pe_proto as P                                       # noqa: E402
from pe_isa import (FLAG_HALF_HIGH, OP_REARM, OP_SHIFT,     # noqa: E402
                    OP_SHIFTIN, OP_START)

SDA, SCL = 2, 1
DEV_W, DEV_R = 0xA0, 0xA1           # MB85RC256V, A2..A0 = 000 -> 0x50
ADDR = 0x0010
ACK, NACK = 0x2D, 0xC4
NDATA = 4


def delay():
    import run_ckack
    return run_ckack.d_half_fm()


def actions():
    d = delay()
    m = P.I2C(SDA, SCL, d, nc_count=0)
    T = lambda segs: m.transaction(segs, loop=False)
    acts = (T([("write", 3), ("read", NDATA)]) + T([("write", 3 + NDATA)])
            + T([("write", 3), ("read", NDATA)]))
    acts.append((OP_REARM, 0, 0, d, 0, 0))        # park: does not retire
    return acts, m


def image():
    acts, m = actions()
    return P.image({0: acts}, {0: m.header(FLAG_HALF_HIGH)})


def feed():
    """-> [word]: one per SHIFT, in pop order ('pc', s) or ('b', byte)."""
    rd = [("b", DEV_W), ("b", ADDR >> 8), ("b", ADDR & 0xFF), ("b", DEV_R)] \
        + [("b", ACK)] * (NDATA - 1) + [("b", NACK)]
    wr = [("b", DEV_W), ("b", ADDR >> 8), ("b", ADDR & 0xFF)] \
        + [("pc", s) for s in range(NDATA)]
    return rd + wr + rd


def feed_lines():
    return ["%03x" % (0x200 | v if k == "pc" else v) for k, v in feed()]


def falls():
    """The count model, walked over the program's actions."""
    acts, _m = actions()
    f, out = 0, []
    for a in acts:
        op, n = a[0], a[5]
        if op == OP_START:
            f += 1
        elif op == OP_SHIFT:
            out.append(f)                  # pops BEFORE its own falls
            f += n + 1                     # count field = bits - 1
        elif op == OP_SHIFTIN:
            f += n                         # count field = bits
    return out, f


def rxmap():
    """-> [(kind, info)] per receive, in order."""
    rd = [("ack", "T1 A0"), ("ack", "T1 addr hi"), ("ack", "T1 addr lo"),
          ("ack", "T1 A1")] + [("old", i) for i in range(NDATA)]
    wr = [("ack", "T2 A0"), ("ack", "T2 addr hi"), ("ack", "T2 addr lo")] \
        + [("ack", "T2 data %d" % i) for i in range(NDATA)]
    rd3 = [(k, v if k == "old" else v.replace("T1", "T3")) for k, v in rd]
    rd3 = [("new", v) if k == "old" else (k, v) for k, v in rd3]
    return rd + wr + rd3


def params():
    f, total = falls()
    return {"NFEED": len(feed()), "NRX": len(rxmap()), "FALLS_TOTAL": total}


if __name__ == "__main__":
    f, total = falls()
    print("d = %d, %d feed words, %d receives, falls model %s (total %d)"
          % (delay(), len(feed()), len(rxmap()), f, total))
