"""RULING SP1 / PN5 / CI4 -- A REAL SPI FRAM TRANSACTION (MB85RS64V), READ
BACK THROUGH THE CHIP, ADJUDICATED BY SIGROK.

`corpus_spim` is the datasheet's sequence, clocked, MSB-first, one queue:
    CS- WREN CS+  CS- WREN CS+  CS- WRITE 01 23 5B C4 1E CS+
    CS- READ 01 23 [in] [in] CS+
(the first WREN of the first loop is the shift register's reset 0x00; the
second is real on every loop -- see `corpus.build_spi_master`).

THE CHAIN -- three hands must agree on the two bytes read back:
  * WRITTEN: the bytes the program fed and the WRITE sent, 5B C4;
  * SIGROK (the foreign judge): `spi` decodes MOSI and MISO SEPARATELY, one
    transfer per CS frame (CS active low, MSB first). Every MOSI frame must be
    the sequence above, and each READ's MISO words 3..4 must be 5B C4;
  * THE CHIP: its received bytes, off the 3-pin serial host stream on
    `uo_out` (pins only: SER_DATA/STRB/VLD, 12-bit frames, `kind` = lane).
  chip RX == sigrok MISO == written, in order.

⭐ BOTH MODES (ruling CI4). The part takes its mode from SCK AT CS FALL. In the
tracked image every READ follows the WRITE, whose clocked SHIFT ends with SCK
high: every READ is MODE 3. The `mode0` arm builds the same program in scratch
with SCK parked low before each select: every transaction MODE 0. The mode of
each READ is measured off the trace, not assumed. sigrok decodes both with
cpol=1/cpha=1 -- modes 0 and 3 both sample on the rise, so the decode is the
same bit stream either way.

MUST-FIRES:
  * `M_TX_LOAD_ANYPHASE` (silicon fix #2's pre-form) -- the opcodes go out
    misaligned, so no CS frame decodes as the WRITE;
  * `M_CKRX_HEADER_PIN` / `M_CKRX_PP_OBSERVED` (silicon fix #3, both parts) --
    sigrok still sees 5B C4 on MISO (the peer is fine) but the chip receives
    something else: the chip-vs-sigrok comparison must go red.

⚠ LOCAL ONLY (sigrok-cli in WSL), under `model/a2/run_a2.py`.
"""

from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "model"))
from toolchain import banner                 # noqa: E402  ruling V
import run_recert as R                       # noqa: E402  one trace/decode path
import corpus                                # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

IMG = "corpus_spim.hex"
NCYC = 60000
SER_DATA, SER_STRB, SER_VLD = 4, 5, 6         # uo_out bits (project.v)
FRAME_BITS, MARK_PAYLOAD = 12, "0"
SPI = ("spi:clk=0:mosi=1:miso=2:cs=3:cpol=1:cpha=1:bitorder=msb-first:"
       "cs_polarity=active-low")


def want():
    """The frames the program means, from its own feed (`corpus.FEEDS`)."""
    f = corpus.FEEDS["corpus_spim"]
    return {"wren": [f[0]], "write": f[1:7], "read": f[7:10],
            "back": f[4:6]}


def serial_rx(rows, lane):
    """The chip's received bytes for `lane`, off the serial host pins --
    `test.py`'s `harvest_frames`, on the trace."""
    out, cur, pv = [], [], "0"
    for r in rows:
        uo = r[0]
        d, st, v = (R._b(uo, SER_DATA), R._b(uo, SER_STRB), R._b(uo, SER_VLD))
        if v not in "01" or st not in "01":
            continue
        if v == "1" and pv == "0":
            cur = []
        if v == "1" and st == "1":
            cur.append(d)
        if v == "0" and pv == "1" and len(cur) == FRAME_BITS:
            if cur[-1] == MARK_PAYLOAD and all(c in "01" for c in cur):
                pay = sum(int(cur[k]) << k for k in range(8))
                kind = sum(int(cur[8 + k]) << k for k in range(3))
                if kind == lane:
                    out.append(pay)
            cur = []
        pv = v
    return out


def transfers(path, which):
    """sigrok's `which`-transfer annotations -> [[words]] per CS frame.
    ⛔ ONE CHANNEL PER DECODE: the draft read both in one run and paired them
    by output order, and sigrok printed MISO first -- every pair was wrong."""
    rc, lines = R.sigrok(path, SPI + " -A spi=%s-transfer" % which)
    out = []
    for l in lines:
        m = re.match(r"spi-1:\s*((?:[0-9A-Fa-f]{2}\s*)+)$", l)
        if m:
            out.append([int(w, 16) for w in m.group(1).split()])
    return rc, out


def cs_modes(rows, sck, cs):
    """SCK's level at each CS fall, as the part reads it -> [3 or 0]."""
    out, pc = [], 1
    for r in rows:
        c = R.level(r, cs, True)
        if c == 0 and pc == 1:
            out.append(3 if R.level(r, sck, True) else 0)
        pc = c
    return out


def run(defines, mode0=False):
    import gate_sda_hold as g
    import pe_isa as I
    tag = "spifram_" + ("_".join(defines) or "good") + ("_m0" if mode0 else "")
    vvp = g.build(list(defines), tag)
    if mode0:
        img, _pre = corpus.build_spi_master(mode0=True)
        os.makedirs(R.SCRATCH, exist_ok=True)
        ipath = os.path.join(R.SCRATCH, "corpus_spim_mode0.hex")
        with open(ipath, "w", encoding="ascii", newline="\n") as fh:
            fh.write("\n".join("%02x" % b for b in I.full_store(bytes(img))))
            fh.write("\n")
        out, rows = R.trace(vvp, "corpus_spim_mode0.hex", "spi", NCYC,
                            img_path=ipath, feed_of="corpus_spim")
        prog = bytes(I.full_store(bytes(img)))
    else:
        out, rows = R.trace(vvp, IMG, "spi", NCYC)
        prog = R.read(os.path.join(HERE, IMG))
    hdr = I.lane_programs(prog)[0][0]
    pins = [hdr["clkpin"], hdr["pin"], corpus.P_M_MISO, corpus.P_M_CS]
    path = R.dump(rows, pins, tag, drive=True)
    rc1, mosi = transfers(path, "mosi")
    rc2, miso = transfers(path, "miso")
    modes = cs_modes(rows, hdr["clkpin"], corpus.P_M_CS)
    return {"out": out, "rows": rows, "rc": rc1 | rc2, "mosi": mosi,
            "miso": miso, "modes": modes, "chip": serial_rx(rows, 0)}


def judge(res, say):
    """The good-build verdicts on one arm -> the READs' modes."""
    w = want()
    mosi, miso, modes = res["mosi"], res["miso"], res["modes"]
    print("    sigrok: %d MOSI / %d MISO transfer(s), %d CS fall(s); first "
          "MOSI %s" % (len(mosi), len(miso), len(modes),
                       [" ".join("%02X" % b for b in m) for m in mosi[:4]]))
    say(res["rc"] == 0 and mosi and len(mosi) == len(miso),
        "sigrok ran; one MOSI and one MISO transfer per CS frame")
    # sigrok emits a transfer per COMPLETED frame; a frame the window cut
    # off is a CS fall with no transfer, and only at the end
    say(0 <= len(modes) - len(mosi) <= 1,
        "every CS frame decoded (%d falls, %d transfers)"
        % (len(modes), len(mosi)))
    shape = []
    for i, m in enumerate(mosi):
        k = i % 4
        exp = ([0x00] if i == 0 else w["wren"]) if k < 2 else (
            w["write"] if k == 2 else w["read"] + [None, None])
        shape.append(len(m) == len(exp) and all(
            e is None or e == b for e, b in zip(exp, m)))
    say(len(mosi) >= 8 and all(shape),
        "MOSI per frame: [06] [06] [02 01 23 5B C4 1E] [03 01 23 . .]")
    reads = [i for i in range(len(mosi)) if i % 4 == 3]
    sig = [w2 for i in reads for w2 in miso[i][3:5]]
    say(len(reads) >= 2 and all(miso[i][3:5] == w["back"] for i in reads),
        "sigrok MISO words of all %d READs == the written %s"
        % (len(reads), " ".join("%02X" % b for b in w["back"])))
    chip = res["chip"]
    n = min(len(chip), len(sig))
    print("    chip received (serial frames, lane 0): %s"
          % " ".join("%02X" % b for b in chip[:8]))
    say(n >= 4 and chip[:n] == sig[:n],
        "the chip's received bytes == sigrok's MISO words (%d bytes)" % n)
    say("[V2]: ok" in res["out"],
        "Layer V2: MOSI on the wire == the host-pushed bytes")
    say("[V-RX]: ok" in res["out"],
        "Layer V-RX: the chip's RX frames == the bits on the action's pin")
    return [res["modes"][i] for i in reads if i < len(res["modes"])]


def main() -> int:
    banner("iverilog", "vvp")
    print()
    print("=" * 78)
    print("SP1 -- a real MB85RS64V transaction (WREN, WRITE, READ), sigrok-judged")
    print("=" * 78)
    rc = 0

    def say(ok, what):
        nonlocal rc
        print("    %-66s %s" % (what, "ok" if ok else "*** FAIL"))
        if not ok:
            rc = 1

    print("  --- mode 3: the tracked image ---")
    m3 = judge(run([]), say)
    say(m3 and set(m3) == {3}, "every READ was MODE 3 (SCK high at CS fall): "
        "%d" % len(m3))
    print("  --- mode 0: SCK parked low before each select (scratch) ---")
    m0 = judge(run([], mode0=True), say)
    say(m0 and set(m0) == {0}, "every READ was MODE 0 (SCK low at CS fall): "
        "%d" % len(m0))

    print("  --- MUST-FIRE: M_TX_LOAD_ANYPHASE (silicon fix #2's pre-form) ---")
    mf = run(["M_TX_LOAD_ANYPHASE"])
    good = sum(1 for m in mf["mosi"] if m == want()["write"])
    say(good == 0, "no CS frame decodes as the WRITE (%d of %d did)"
        % (good, len(mf["mosi"])))
    for mut in ("M_CKRX_HEADER_PIN", "M_CKRX_PP_OBSERVED"):
        print("  --- MUST-FIRE: %s (silicon fix #3) ---" % mut)
        mf = run([mut])
        sig = [w2 for i, m in enumerate(mf["miso"]) if i % 4 == 3
               for w2 in m[3:5]]
        n = min(len(mf["chip"]), len(sig))
        print("    sigrok MISO %s / chip %s"
              % (" ".join("%02X" % b for b in sig[:4]),
                 " ".join("%02X" % b for b in mf["chip"][:4])))
        say(n >= 2 and sig[:2] == want()["back"]
            and mf["chip"][:n] != sig[:n],
            "the peer still answers 5B C4 and the chip disagrees")
    print()
    print("  GATE spifram: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
