"""RULING SP1 / PN5 / CI4 -- A REAL SPI FRAM TRANSACTION (MB85RS64V), READ
BACK THROUGH THE CHIP, ADJUDICATED BY SIGROK.

`corpus_spim` is the datasheet's sequence, clocked, MSB-first, one queue:
    CS- WREN CS+  CS- WRITE 01 23 5B C4 1E CS+
    CS- READ 01 23 [in] [in] CS+
(⭐ ONE WREN since silicon fix #8. The program sent it twice while the first
SHIFT after a load sent the register's reset 0x00 -- the first loop's first
"WREN" was no opcode -- and the first frame is now checked to be 06.)

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
SPI = ("spi:clk=0:mosi=1:miso=2:cs=3:cpol=%d:cpha=%d:bitorder=msb-first:"
       "cs_polarity=active-low")
# ⭐ sigrok samples on the RISE when cpol == cpha (modes 0, 3) and on the FALL
# otherwise (modes 1, 2) -- so an inverted-clock arm is decoded as mode 1,
# which a mode-0/3 setting would read on the wrong edge
CPOL_CPHA = {False: (1, 1), True: (0, 1)}


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


def transfers(path, which, inv=False):
    """sigrok's `which`-transfer annotations -> [[words]] per CS frame.
    ⛔ ONE CHANNEL PER DECODE: the draft read both in one run and paired them
    by output order, and sigrok printed MISO first -- every pair was wrong."""
    rc, lines = R.sigrok(path, SPI % CPOL_CPHA[inv]
                         + " -A spi=%s-transfer" % which)
    out = []
    for l in lines:
        m = re.match(r"spi-1:\s*((?:[0-9A-Fa-f]{2}\s*)+)$", l)
        if m:
            out.append([int(w, 16) for w in m.group(1).split()])
    return rc, out


def cs_modes(rows, sck, cs, inv=False):
    """The SPI mode of each transaction, off the pins: CPOL is SCK's level at
    CS fall (the part reads it there); CPHA is the clock's polarity -- an
    inverted clock (CE2) samples on the fall. -> [0, 1, 2 or 3]."""
    out, pc = [], 1
    for r in rows:
        c = R.level(r, cs, True)
        if c == 0 and pc == 1:
            hi = R.level(r, sck, True)
            out.append((2 if hi else 1) if inv else (3 if hi else 0))
        pc = c
    return out


def stray_sck_edges(rows, sck, cs, bits_per_frame):
    """⛔ RULING CE2's IDLE-LEVEL CHECK, from the pins: an SCK edge while CS
    is asserted that is NOT one of the transaction's own clock phases. Each
    CS-low window carries 2 edges per bit sigrok decoded in it, give or take
    ONE: a transaction whose first LOW finds the clock already low makes no
    edge there, and a receive's trailing COLLECT adds a fall -- both are the
    transaction's own phases. A stray clock (a pair of extra edges) breaks
    the bound. Also returns whether CS was deasserted at the FIRST SCK edge
    after reset -- on an inverted clock that edge is the idle-level flip at
    header load, and a selected peer would count it.
    -> (stray windows [(index, edges, want)], first_edge_cs_high)"""
    stray, win, edges, ps, pc, first = [], -1, 0, None, 1, None
    for r in rows:
        s, c = R.level(r, sck, True), R.level(r, cs, True)
        if ps is not None and s != ps:
            if first is None:
                first = (c == 1)
            if c == 0:
                edges += 1
        if c == 0 and pc == 1:
            win += 1
            edges = 0
        if c == 1 and pc == 0 and 0 <= win < len(bits_per_frame):
            want = 2 * bits_per_frame[win]
            if abs(edges - want) > 1:
                stray.append((win, edges, want))
        ps, pc = s, c
    return stray, first


def run(defines, mode0=False, clkinv=False):
    import gate_sda_hold as g
    import pe_isa as I
    tag = ("spifram_" + ("_".join(defines) or "good")
           + ("_m0" if mode0 else "") + ("_inv" if clkinv else ""))
    vvp = g.build(list(defines), tag)
    if mode0 or clkinv:
        img, _pre = corpus.build_spi_master(mode0=mode0, clkinv=clkinv)
        os.makedirs(R.SCRATCH, exist_ok=True)
        name = "corpus_spim%s%s.hex" % ("_mode0" if mode0 else "",
                                       "_inv" if clkinv else "")
        ipath = os.path.join(R.SCRATCH, name)
        with open(ipath, "w", encoding="ascii", newline="\n") as fh:
            fh.write("\n".join("%02x" % b for b in I.full_store(bytes(img))))
            fh.write("\n")
        out, rows = R.trace(vvp, name, "spi", NCYC, img_path=ipath,
                            feed_of="corpus_spim", sck_inv=clkinv)
        prog = bytes(I.full_store(bytes(img)))
    else:
        out, rows = R.trace(vvp, IMG, "spi", NCYC)
        prog = R.read(os.path.join(HERE, IMG))
    hdr = I.lane_programs(prog)[0][0]
    pins = [hdr["clkpin"], hdr["pin"], corpus.P_M_MISO, corpus.P_M_CS]
    path = R.dump(rows, pins, tag, drive=True)
    rc1, mosi = transfers(path, "mosi", clkinv)
    rc2, miso = transfers(path, "miso", clkinv)
    modes = cs_modes(rows, hdr["clkpin"], corpus.P_M_CS, clkinv)
    stray, first = stray_sck_edges(rows, hdr["clkpin"], corpus.P_M_CS,
                                   [8 * len(m) for m in mosi])
    return {"out": out, "rows": rows, "rc": rc1 | rc2, "mosi": mosi,
            "miso": miso, "modes": modes, "chip": serial_rx(rows, 0),
            "stray": stray, "first_cs_high": first}


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
        k = i % 3
        exp = w["wren"] if k == 0 else (
            w["write"] if k == 1 else w["read"] + [None, None])
        shape.append(len(m) == len(exp) and all(
            e is None or e == b for e, b in zip(exp, m)))
    say(len(mosi) >= 6 and all(shape),
        "MOSI per frame, FROM THE FIRST: [06] [02 01 23 5B C4 1E] "
        "[03 01 23 . .]")
    reads = [i for i in range(len(mosi)) if i % 3 == 2]
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
    say(not res["stray"], "no SCK edge while CS asserted outside the "
        "transaction's own clock phases%s"
        % ("" if not res["stray"] else " -- %s" % res["stray"][:3]))
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

    # ---- RULING CE2 -- CLK_INV: SPI modes 1 and 2 -----------------------
    # ⭐ The same transaction with the SCLK pin inverted. The peer is the
    # mode-0/3 model behind an SCK inverter (same-hand, labelled); sigrok,
    # decoding the PADS with mode 1's CPOL/CPHA, is the judge of the mode.
    for label, m0_, want_mode in (("mode 1: CLK_INV, the tracked shape", False,
                                   1),
                                  ("mode 2: CLK_INV + SCK parked", True, 2)):
        print("  --- %s (scratch) ---" % label)
        r = run([], mode0=m0_, clkinv=True)
        mm = judge(r, say)
        say(mm and set(mm) == {want_mode},
            "every READ was MODE %d (CPOL from SCK at CS fall, CPHA from the "
            "inversion): %d" % (want_mode, len(mm)))
        say(r["first_cs_high"] is True,
            "the inverted clock's idle-level flip (the first SCK edge after "
            "reset) happened with CS DEASSERTED")
        if want_mode == 1:
            inv_rows = r["rows"]
            inv_bits = [8 * len(m) for m in r["mosi"]]
    # ⛔ MUST-FIRE for the idle-level check, on the PINS it reads: a stray
    # SCK pulse planted inside a CS-low window, and the idle-level flip
    # planted with CS asserted. A check never seen to fire has unknown
    # strength.
    sck, cs = corpus.P_M_SCLK, corpus.P_M_CS
    win = next(i for i, x in enumerate(inv_rows)
               if R.level(x, cs, True) == 0) + 3
    def flip(row, pin):
        uo = list(row[0])
        k = len(uo) - 1 - (pin - 8)
        uo[k] = "0" if uo[k] == "1" else "1"
        return ("".join(uo),) + tuple(row[1:])
    planted = list(inv_rows)
    planted[win] = flip(planted[win], sck)
    planted[win + 1] = flip(planted[win + 1], sck)
    say(bool(stray_sck_edges(planted, sck, cs, inv_bits)[0]),
        "must-fire: a planted stray SCK pulse inside CS-low is caught")
    first = next(i for i in range(1, len(inv_rows))
                 if R.level(inv_rows[i], sck, True)
                 != R.level(inv_rows[i - 1], sck, True))
    planted = list(inv_rows)
    for i in range(first - 2, first + 2):
        if R.level(planted[i], cs, True) == 1:
            planted[i] = flip(planted[i], cs)
    say(stray_sck_edges(planted, sck, cs, inv_bits)[1] is False,
        "must-fire: the idle-level flip planted under an asserted CS is "
        "caught")
    print("  --- MUST-FIRE: M_CLKINV_IGNORED (the XOR dropped) ---")
    # ⚠ NOT JUDGED ON MOSI, AND MEASURED WHY: the engine changes MOSI in the
    # very cycle SCK falls, so a mode-1 decode (sample on the fall) of the
    # mutant's mode-3 clock still reads the right bits -- 39 of 118 frames
    # decoded as the WRITE when this arm first judged on MOSI. What the
    # dropped XOR DOES change is the clock itself and what the mode-1 peer
    # sends back: the READs are no longer mode 1 at the pins, and the chip
    # receives 5B C4 one bit early.
    mf = run(["M_CLKINV_IGNORED"], clkinv=True)
    mreads = [i for i in range(len(mf["mosi"])) if i % 3 == 2]   # 3 frames/loop
    mm = sorted({mf["modes"][i] for i in mreads if i < len(mf["modes"])})
    say(mm and mm != [1], "the pins: the READs are no longer MODE 1 (SCK "
        "level at CS fall reads as mode %s)" % mm)
    say(mf["chip"][:2] != want()["back"],
        "the chip's received bytes are not the written %s (got %s)"
        % (" ".join("%02X" % b for b in want()["back"]),
           " ".join("%02X" % b for b in mf["chip"][:4])))

    print("  --- MUST-FIRE: M_TX_LOAD_ANYPHASE (silicon fix #2's pre-form) ---")
    mf = run(["M_TX_LOAD_ANYPHASE"])
    good = sum(1 for m in mf["mosi"] if m == want()["write"])
    say(good == 0, "no CS frame decodes as the WRITE (%d of %d did)"
        % (good, len(mf["mosi"])))
    for mut in ("M_CKRX_HEADER_PIN", "M_CKRX_PP_OBSERVED"):
        print("  --- MUST-FIRE: %s (silicon fix #3) ---" % mut)
        mf = run([mut])
        sig = [w2 for i, m in enumerate(mf["miso"]) if i % 3 == 2
               for w2 in m[3:5]]
        n = min(len(mf["chip"]), len(sig))
        print("    sigrok MISO %s / chip %s"
              % (" ".join("%02X" % b for b in sig[:4]),
                 " ".join("%02X" % b for b in mf["chip"][:4])))
        # ⛔ RULING RX1 CHANGED HOW M_CKRX_PP_OBSERVED DIES. It waits for an
        # OBSERVED rise of a `uo_out` SCK, which has no input path, so its
        # capture never fires. Before RX1 the LOW consumed the bit anyway and
        # read 0 (`00 00`); since RX1 a lane is ineligible while its capture
        # is pending, so the receive DEADLOCKS -- no READ completes and the
        # chip receives NOTHING. Either symptom is the mutant caught; a clean
        # run receives 76 bytes.
        if mut == "M_CKRX_PP_OBSERVED" and not mf["chip"]:
            say(True, "the push-pull capture never fires: the receive lane "
                      "deadlocks on RX1's capture gate (0 bytes received)")
        else:
            say(n >= 2 and sig[:2] == want()["back"]
                and mf["chip"][:n] != sig[:n],
                "the peer still answers 5B C4 and the chip disagrees")
    print()
    print("  GATE spifram: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
