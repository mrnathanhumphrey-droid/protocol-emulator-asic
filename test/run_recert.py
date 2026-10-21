"""RULING RC1-RC3 -- SIGROK RE-CERTIFIES EVERY CLOCKED IMAGE, BY BUS TYPE.

The clocked corpus had never been put in front of a foreign decoder. The first
look found the I2C images framed on LSB-first lanes with a STOP that was no
STOP (the chip correct throughout -- Layer V2). This is the standing check:

  I2C   (`corpus_i2c`, `ckread`, `corpus_all5` lane 0): `tb_trace` runs the
        image with the I2C peer; Layer V2 must report the wire == the host-
        pushed bytes; sigrok's `i2c` decoder must find WELL-FORMED frames
        (every Start closed by a Stop, nothing undecoded), and its bytes must
        equal this file's own decode of the same dump. So: sigrok == wire ==
        intended, the chain the ruling asks for.
  SPI   (push-pull clocked TRANSMIT lanes: `ckfive` lanes 0-3, `corpus_all5`
        lane 2, `corpus_spim` lane 0): sigrok's `spi` decoder, MODE 3 (the
        clocked SHIFT drives data on its LOW phase, raises the clock on HIGH,
        and leaves it HIGH -- the sampling edge MEASURED here: a falling-edge
        decode is shown to disagree), bit order from the lane header;
        sigrok's MOSI words == this file's decode of the same dump (the
        CHIP's drive, not the bench-resolved bus); Layer V2 ok. `ckfive` lane
        4 is a clocked RECEIVE lane, declared by name.
  NOT CERTIFIABLE, BY NAME (RC3): every other clocked image is declared below
        with its reason -- a timing subject with no START/STOP framing, or a
        refusal image that puts nothing on the wire. A clocked image in no
        class is RED, so a new one cannot slip past by being unnamed.

⚠ LOCAL ONLY (sigrok-cli in WSL), under `model/a2/run_a2.py`.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "model"))
from toolchain import banner, tool          # noqa: E402  ruling V
import sim_run                              # noqa: E402
import pe_isa as I                          # noqa: E402
from run_i2c import wsl_path                # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SCRATCH = os.environ.get("PE_SCRATCH",
                         os.path.join(os.environ.get("TEMP", "/tmp"),
                                      "pe_recert"))
F_CLK = 50000000
NCYC = 60000

#: image -> (peer, [lane, ...]) certified as I2C
I2C = {"corpus_i2c.hex": ("i2c", [0]),
       "ckread_image.hex": ("i2c", [0]),
       "corpus_all5.hex": ("i2c", [0])}
#: image -> (peer, [lane, ...]) certified as SPI (push-pull clocked)
SPI = {"ckfive_image.hex": ("none", [0, 1, 2]),
       "corpus_all5.hex": ("spi", [2]),
       "corpus_spim.hex": ("spi", [0]),
       # the same 1 MHz SPI-master transaction at d = 25 (admissible; WF1's
       # SPI-master witness, 6c919bc) -- unclassed from 6c919bc until the
       # class guard (gate_image_bounds G5, Wilson 10-19) found it
       "corpus_spim25.hex": ("spi", [0])}
#: clocked lanes of a certified image that are NOT certified, by name
RX_ONLY = {
    ("ckfive_image.hex", 3):
        "on the SPI-target pad pair (data = CS_PIN 6, clock = MISO_PIN 7): "
        "MISO's enable is async-cleared whenever pin 6 reads high, so this "
        "lane's own 1 bits switch its clock off -- MEASURED, the clock "
        "toggles only on 0 bits and the wire decodes 00. The pad override "
        "is the chip working as designed (N1's PINMAP hazard); `ckfive` is "
        "the C saturation base, not a protocol, so the lane is not an SPI "
        "transfer. Its data bits are still checked by Layer V2.",
    ("ckfive_image.hex", 4):
        "a clocked SHIFTIN lane (receive only): its data pin is read, never "
        "driven, so there is no transmitted byte to certify",
}
#: RC3: clocked images that are NOT protocol transactions, by name
NOT_CERTIFIABLE = {
    "ckod_image.hex": "timing subject: open-drain clocked lanes at a delay "
                      "span, no START/STOP framing; values covered by V2",
    "ckheavy_image.hex": "timing subject (the A2 subject): clocked lanes with "
                         "no START/STOP framing; values covered by V2",
    "ckdense_image.hex": "timing subject: four open-drain clocked lanes, no "
                         "START/STOP framing; values covered by V2",
    "ckhold_at_image.hex": "refusal image: d = SDA_HOLD is refused (D1), "
                           "nothing reaches the wire",
    "ckhold_under_image.hex": "refusal image: d < SDA_HOLD is refused (D1)",
    "ckhold_over_image.hex": "timing subject: the W1 setup measurement at "
                             "d = 16, no START/STOP framing; values covered "
                             "by V2",
    "ckdegen_image.hex": "refusal image: a zero-bit clocked action is "
                         "refused, nothing reaches the wire",
    "ckdegen2_image.hex": "refusal image: the wrapping-count route to the "
                          "same refusal",
    # B3b contention subjects: five protocols on one image, and this runner's
    # foreign decode reads ONE protocol per image. Every lane's bytes are
    # checked on its own wire by test/run_spitgt.py (tb_spitgt +FIVE).
    "b3b_a_image.hex": "contention subject (B3b): five lanes on one image; "
                       "each lane's wire checked by run_spitgt",
    "b3b_a3_image.hex": "contention subject (B3b), as b3b_a in mode 3",
    "b3b_b_image.hex": "contention subject (B3b), I2C at the A2 envelope "
                       "deadline; each lane's wire checked by run_spitgt",
    "b3b_bnoi2c_image.hex": "contention subject (B3b), b3b_b without I2C; "
                            "each lane's wire checked by run_spitgt",
}


#: the wire-feed check that marks an image as a COVERAGE image
COVERAGE_CHECK = "test/gate_coverage.py"


def derived_not_certifiable():
    """{image: reason} for clocked images whose class FOLLOWS from what
    `gate_wire_feed.REGISTRY` already declares about them -- derived, never
    typed (Wilson 10-19: the three images the shared universe brought in on
    23daef3 had been hand-declared here):
      * WITNESS by a recorded HARDWARE-witness gate (model/gate_*_hw_witness.py)
        -> certified on hardware by that gate, not by this simulation;
      * INTERNAL, checked by the coverage sweep -> a coverage image, not a
        protocol transaction.
    """
    sys.path.insert(0, os.path.join(ROOT, "model", "a2"))
    import gate_wire_feed as W
    ck = clocked_images()        # only a CLOCKED image has a class here
    out = {}
    for name, (kind, d) in W.REGISTRY.items():
        if name not in ck:
            continue
        r = d.get("runner", "")
        if kind == W.WITNESS and re.fullmatch(r"model/gate_\w+_hw_witness\.py", r):
            out[name] = ("certified ON HARDWARE by %s (derived from its "
                         "wire-feed WITNESS entry), not by this simulation" % r)
        elif kind == W.INTERNAL and d.get("checked_by") == COVERAGE_CHECK:
            out[name] = ("coverage image, checked by %s (derived from its "
                         "wire-feed INTERNAL entry), not a protocol "
                         "transaction" % COVERAGE_CHECK)
    return out


def clocked_images():
    """Clocked images of the SHARED universe (`model/image_universe.py`,
    Wilson 10-18); this listed test/ only."""
    import image_universe
    out = {}
    for p, path in image_universe.items():
        img = read(path)
        lanes = [ln for ln, (h, _a) in I.lane_programs(img).items()
                 if h["clkpin"] not in (I.PIN_NONE, h["pin"])
                 and any(a["op"] in (I.OP_SHIFT, I.OP_SHIFTIN) and a["level"]
                         for a in _a)]
        if lanes:
            out[p] = lanes
    return out


def read(p):
    with open(p, encoding="ascii") as fh:
        return bytes(int(t, 16) for t in fh.read().split())


NOT_CERTIFIABLE.update(derived_not_certifiable())


def classes():
    """{image: class name} -- every image run_recert classes."""
    out = {}
    for n in I2C:
        out[n] = "I2C"
    for n in SPI:
        out.setdefault(n, "SPI")
    for n in NOT_CERTIFIABLE:
        out.setdefault(n, "NOT_CERTIFIABLE")
    return out


def build():
    import gate_sda_hold as g
    return g.build([], "recert")


def trace(vvp, img, peer, ncyc=NCYC, img_path=None, feed_of=None,
          sck_inv=0):
    """Run `tb_trace` on `img` with its own host feed (`corpus.FEEDS`, ruling
    SP1) -> (stdout, rows of (uo_out, uio_out, uio_oe, uio_in)).

    `img_path`: a SCRATCH image (not under `test/`) run under the name `img`;
    `feed_of`: the `corpus.FEEDS` key whose queue it takes (a variant of a
    tracked program pops the same bytes in the same order);
    `sck_inv`: the SPI peer as a mode 1/2 device (ruling CE2)."""
    os.makedirs(SCRATCH, exist_ok=True)
    out = os.path.join(SCRATCH, "t_%s_%s%s.txt" % (img.replace(".hex", ""),
                                                   peer, "_inv" if sck_inv
                                                   else ""))
    import benchset
    import corpus
    ipath = (img_path.replace("\\", "/") if img_path else "test/%s" % img)
    # ⛔ the bound of the image ACTUALLY RUN: this looked up "test/" + img,
    # and since 23daef3 a missing record classifies the image -- so a scratch
    # variant (run_spifram's corpus_spim_mode0.hex, not under test/) crashed
    # the lookup. Found by the launch-helper record pass (Wilson 10-19).
    a2 = benchset.a2_slack_arg(ipath)
    seq = corpus.FEEDS.get(feed_of or img.replace(".hex", ""), [])
    feed = (["+FEEDN=%d" % len(seq),
             "+FEED=%s" % "".join("%02x" % b for b in seq)] if seq else [])
    r = subprocess.run(sim_run.vvp([vvp, "+IMG=%s" % ipath, "+NBYTES=256",
                                    "+PEER=%s" % peer, "+NCYC=%d" % ncyc, "+OUT=%s" % out,
                                    "+SEED=1", "+ASYNC=0", "+STAYLOAD=0", "+SCLHOLD=0",
                                    "+SPI_SCK_INV=%d" % (1 if sck_inv else 0)]
                                   + ([a2] if a2 else []) + feed, images=[ipath]),
                       cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    rows = []
    with open(out, encoding="ascii", errors="replace") as fh:
        for line in fh:
            f = line.split()
            if len(f) >= 5 and f[0].isdigit():
                rows.append((f[1], f[2], f[3], f[4]))
    return r.stdout or "", rows


def _b(v, n):
    return v[len(v) - 1 - n]


def level(row, pin, drive=False):
    """The pin's level. `drive=False`: the RESOLVED bus (`uio_in`), which is
    what an open-drain receiver sees. `drive=True`: what the CHIP drives where
    it drives (`uio_out` under `uio_oe`, or `uo_out`) -- needed for push-pull
    lanes, because `tb_trace` itself drives several uio pins as peer-side
    inputs, so the resolved value there is the BENCH's (measured: ckfive lane
    3 read `00 00 00 00` off `uio_in` while Layer V2 had its 8 bytes right)."""
    uo, uout, uoe, uin = row
    if pin >= 8:
        b = _b(uo, pin - 8)
    elif drive and _b(uoe, pin) == "1":
        b = _b(uout, pin)
    else:
        b = _b(uin, pin)
    return 1 if b == "1" else 0          # X / Z read as released


def dump(rows, pins, name, drive=False):
    path = os.path.join(SCRATCH, name + ".bin")
    with open(path, "wb") as fh:
        fh.write(bytes(sum(level(r, p, drive) << i for i, p in enumerate(pins))
                       for r in rows))
    return path


def sigrok(path, decoder):
    """`decoder` is the -P argument; returns (rc, [annotation lines])."""
    wrap = os.path.join(ROOT, "probe_recert_decode.sh")
    nl = chr(10)
    with open(wrap, "w", encoding="ascii", newline=nl) as fh:
        fh.write("#!/bin/bash" + nl)
        fh.write("%s -i %s -I binary:numchannels=4:samplerate=%d -P %s"
                 % (os.environ.get("SIGROK_CLI", "sigrok-cli"), wsl_path(path),
                    F_CLK, decoder) + nl)
    r = subprocess.run(["wsl.exe", "-e", "bash", wsl_path(wrap)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace",
                       env=dict(os.environ, MSYS_NO_PATHCONV="1"))
    lines = [l.strip() for l in ((r.stdout or "") + (r.stderr or "")).replace(
        "\r", "").split(chr(10)) if l.strip()]
    return r.returncode, lines


def own_i2c(rows, scl, sda):
    """(frames, bytes): frames = [(closed_by_stop, n_bytes)], our own decode."""
    frames, data, bits, ps, pd, cur = [], [], [], 1, 1, None
    for r in rows:
        s, d = level(r, scl), level(r, sda)
        if s and ps and d != pd:
            if d == 0:                               # START (or repeated)
                if cur is not None and cur[1] == 0:
                    pass
                cur = cur if cur is not None else [False, 0]
            else:                                    # STOP
                if cur is not None:
                    cur[0] = True
                    frames.append(tuple(cur))
                cur = None
            bits = []
        elif s and not ps:
            bits.append(d)
            if len(bits) == 9:
                data.append(int("".join(map(str, bits[:8])), 2))
                if cur is not None:
                    cur[1] += 1
                bits = []
        ps, pd = s, d
    if cur is not None:
        frames.append((False, cur[1]))
    return frames, data


def own_spi(rows, clk, mosi, lsb):
    """MOSI words, 8 rising clock edges each (sample on the rise), counted
    from the first edge -- the same framing sigrok uses without a CS."""
    words, bits, pc = [], [], level(rows[0], clk, True)
    for r in rows:
        c = level(r, clk, True)
        if c and not pc:
            bits.append(level(r, mosi, True))
            if len(bits) == 8:
                b = bits[::-1] if lsb else bits
                words.append(int("".join(map(str, b)), 2))
                bits = []
        pc = c
    return words


def main() -> int:
    banner("iverilog", "vvp")
    print()
    print("=" * 78)
    print("RC1-RC3 -- sigrok re-certifies every clocked image, by bus type")
    print("=" * 78)
    rc = 0

    def say(ok, what):
        nonlocal rc
        print("    %-66s %s" % (what, "ok" if ok else "*** FAIL"))
        if not ok:
            rc = 1

    # ---- every clocked image is in exactly one class ----------------------
    ck = clocked_images()
    classed = set(I2C) | set(SPI) | set(NOT_CERTIFIABLE)
    print("  %d clocked images: %s" % (len(ck), " ".join(sorted(ck))))
    say(set(ck) <= classed, "every clocked image is classed (unclassed: %s)"
        % sorted(set(ck) - classed))
    say(classed <= set(ck), "no class names a non-clocked image (stale: %s)"
        % sorted(classed - set(ck)))
    for n, why in sorted(NOT_CERTIFIABLE.items()):
        print("    not certifiable, by name: %-24s %s" % (n, why[:44]))

    vvp = build()
    fall_differs = []
    for img, (peer, lanes) in sorted(I2C.items()):
        hdrs = I.lane_programs(read(os.path.join(HERE, img)))
        for ln in lanes:
            h = hdrs[ln][0]
            out, rows = trace(vvp, img, peer)
            scl, sda = h["clkpin"], h["pin"]
            path = dump(rows, [scl, sda], "%s_l%d" % (img, ln))
            rc_s, lines = sigrok(path, "i2c:scl=0:sda=1 -A i2c")
            ev = [l.split(":", 1)[1].strip() for l in lines
                  if l.startswith("i2c-1:")]
            sd = [int(m.group(1), 16) for e in ev for m in
                  [re.match(r"(?:Address (?:write|read)|Data (?:write|read)):"
                            r"\s*([0-9A-Fa-f]{2})$", e)] if m]
            starts = sum(1 for e in ev if e in ("Start", "Start repeat"))
            stops = sum(1 for e in ev if e == "Stop")
            frames, own = own_i2c(rows, scl, sda)
            print("  --- I2C %s lane %d (peer %s, MSB=%d): %d frame(s) ---"
                  % (img, ln, peer, h["order"], len(frames)))
            print("      sigrok %d Start / %d Stop; bytes %s"
                  % (starts, stops, " ".join("%02X" % b for b in sd[:10])))
            say(rc_s == 0 and ev, "sigrok ran and decoded")
            say(h["order"] == I.ORDER_MSB, "the lane is MSB-first (RC4)")
            say(len(frames) >= 2 and all(f[0] for f in frames[:-1]),
                "every frame but the run-cut last one is closed by a STOP")
            say(stops >= 2, "sigrok sees the STOPs (%d)" % stops)
            # an address byte is reported as 7 bits + R/W by sigrok
            own_cmp = [(b >> 1) if i in addr_idx(ev) else b
                       for i, b in enumerate(own[:len(sd)])]
            say(sd == own_cmp, "sigrok's bytes == this file's decode of the "
                "same dump (%d bytes)" % len(sd))
            say("[V2]: ok" in out, "Layer V2: the wire == the host-pushed "
                "bytes (the intended ones)")
    for img, (peer, lanes) in sorted(SPI.items()):
        hdrs = I.lane_programs(read(os.path.join(HERE, img)))
        out, rows = trace(vvp, img, peer)
        for ln in lanes:
            h = hdrs[ln][0]
            lsb = h["order"] == I.ORDER_LSB
            path = dump(rows, [h["clkpin"], h["pin"]], "%s_l%d" % (img, ln),
                        drive=True)
            got = {}
            for mode in (3, 1):
                cpol, cpha = mode >> 1, mode & 1
                rc_s, lines = sigrok(path, "spi:clk=0:mosi=1:cpol=%d:cpha=%d:"
                                     "bitorder=%s -A spi=mosi-data"
                                     % (cpol, cpha, "lsb-first" if lsb
                                        else "msb-first"))
                got[mode] = [int(l.split(":", 1)[1].strip(), 16) for l in lines
                             if l.startswith("spi-1:")
                             and re.match(r"^[0-9A-Fa-f]{2}$",
                                          l.split(":", 1)[1].strip())]
            own = own_spi(rows, h["clkpin"], h["pin"], lsb)
            n = min(len(own), len(got[3]))
            print("  --- SPI %s lane %d (clk %d, mosi %d, %s): %d word(s) ---"
                  % (img, ln, h["clkpin"], h["pin"],
                     "LSB" if lsb else "MSB", len(own)))
            print("      sigrok mode 3 %s"
                  % " ".join("%02X" % b for b in got[3][:10]))
            say(n >= 4 and got[3][:n] == own[:n],
                "sigrok mode 3 == this file's decode of the same dump")
            # ⭐ the NEGATIVE CONTROL samples on the FALLING edge (mode 1).
            # Modes 0 and 3 both sample on the rise and differ only in idle
            # polarity, so mode 0 agreeing is not a contradiction -- the first
            # version of this check asserted it would not, and was wrong.
            # ⚠ Where data holds across BOTH edges (measured on ckfive) a
            # falling-edge decode agrees too, so the control must disagree on
            # AT LEAST ONE lane -- that alone shows sigrok honours the edge.
            fall_differs.append(got[1][:n] != own[:n])
            print("      falling-edge decode (mode 1) %s"
                  % ("DIFFERS" if fall_differs[-1] else "agrees (data holds "
                     "across both edges here)"))
            say("[V2]: ok" in out, "Layer V2: the wire == the host-pushed bytes")
    say(any(fall_differs), "the falling-edge control disagrees on at least "
        "one lane (%d of %d): the sampling edge is measured, not assumed"
        % (sum(fall_differs), len(fall_differs)))
    for (img, ln), why in sorted(RX_ONLY.items()):
        print("  --- %s lane %d: not certified, by name -- %s" % (img, ln, why))
    print()
    print("  GATE recert: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


def addr_idx(ev):
    """Indices, in sigrok's byte list, of the address bytes."""
    out, i = set(), 0
    for e in ev:
        if e.startswith("Address"):
            out.add(i)
            i += 1
        elif e.startswith("Data"):
            i += 1
    return out


if __name__ == "__main__":
    sys.exit(main())
