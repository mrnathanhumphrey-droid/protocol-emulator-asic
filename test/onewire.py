"""CE5 -- the 1-Wire (DS18B20) slot-engine images, assembled with pe_asm.

The program is `model/pe_proto.OneWire` (read its docstring for the slot
shapes and why the transaction is host-fed); this file only builds images and
the host feed.

Variants:
  tt          the TT image: DQ = uio[2] open-drain, sense = uio[3]
  fpga        the Puzhi PA100T-EDU image: same pins, master low 2 us, sample
              at 13 us (Figure 18: short T_INIT, late sample) for a real
              4.7 kOhm pull-up
  w0short     MUST-FIRE: write-0 low cut to 50 us (< tLOW0 min 60 us)
  latesample  MUST-FIRE: the read sample moved to 20 us (> tRDV 15 us)

Usage:  python test/onewire.py <variant> <out.hex> [<feed.hex>]
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "model"))
import pe_proto as P                                            # noqa: E402

TRACKED = {"tt": "onewire_image.hex", "fpga": "onewire_fpga_image.hex"}


def engine(variant):
    if variant == "tt":
        return P.onewire_tt()
    if variant == "fpga":
        return P.onewire_fpga()
    if variant == "w0short":
        return P.OneWire(TW0_us=50.0)
    if variant == "latesample":
        return P.OneWire(B_us=17.0)
    raise SystemExit("unknown variant %r" % variant)


def build(variant):
    lanes, headers = engine(variant).lanes_headers()
    return P.image(lanes, headers)


def feed(variant, txn=None):
    """-> (feed lines, rx map, index of the first poll byte)."""
    lines, rxmap = engine(variant).feed_file(txn or P.DS18B20_TXN)
    pollidx = next(i for i, r in enumerate(rxmap) if r[0] == "poll")
    return lines, rxmap, pollidx


def write_hex(path, img):
    with open(path, "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join("%02x" % b for b in img) + "\n")


def main():
    var, out = sys.argv[1], sys.argv[2]
    img = build(var)
    write_hex(out, img)
    e = engine(var)
    print("onewire %s: P = %d cycles, A = %d, B = %d, TW0 = %d, T3 = %d -> %s"
          % (var, e.P, e.A, e.B, e.TW0, e.T3, out))
    if len(sys.argv) > 3:
        lines, _m, pidx = feed(var)
        with open(sys.argv[3], "w", encoding="ascii", newline="\n") as fh:
            fh.write("\n".join(lines) + "\n")
        print("  feed: %d words, poll at rx byte %d -> %s"
              % (len(lines), pidx, sys.argv[3]))


if __name__ == "__main__":
    main()
