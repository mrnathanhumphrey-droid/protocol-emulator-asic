"""run_drive_sample -- DRIVE_SAMPLE (opcode 12, Wilson 11-20, option (A)) on the RTL:
one action drives `pin` and samples `pinb` at the drive instant.

  1. FULL-DUPLEX ROUND TRIP against an independent peer (tb_ds PEER=1, an SPI
     mode-0 target in the bench): lane 0 sends the host's 0xA5 on MOSI (uio[0],
     DRIVE_SAMPLE from the TX register) while sampling MISO (uio[2]); SCK (uio[1])
     is two LEVELs per bit. The target's byte must arrive in RX and 0xA5 at the
     target, both checked bit for bit.
  2. THE SAMPLE'S AGE, MEASURED (tb_ds PEER=2, a new pseudo-random bit on uio[2]
     every cycle): sixteen DRIVE_SAMPLEs of alternating level; for each, the edge
     its drive reaches the pad is read off the EV lines, and the age is the one
     offset that predicts all sixteen sampled bits. It must equal
     model/clock.py DS_SAMPLE_AGE (read from the RTL).
  3. OPEN-DRAIN: on an open-drain lane DRIVE_SAMPLE never drives a 1 (LEVEL's rule).
  4. REFUSALS: pin == pinb on the RTL (config_err, nothing driven); pe_isa refuses
     pin == pinb, a clocked lane and a pinb on an output-only uo_out pin (planted
     pinb = 8, Wilson 11-20), and accepts the clean images.
Must-fires: M_DS_SAMPLE_AFTER (the sample taken after the drive: RX gets our own
byte) and M_DS_NO_TXADV (the TX register never shifts: the target gets 0x01).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "model"))
from toolchain import banner, tool      # noqa: E402
import pe_isa as I                      # noqa: E402
import sim_run                          # noqa: E402
import clock                            # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BENCH = "test/tb_ds.v"
RTL = ["src/pe_engine.v", "src/pe_store.v", "src/project.v"]
GEN = "run_drive_sample"
MOSI, SCK, MISO = 0, 1, 2     # uio[0] driven, uio[1] the SPI clock, uio[2] the peer
D = 40                        # every word's delay: above D* = 20
TX_BYTE = 0xA5                # the host feed's first byte (tb_ds +FEED=1)
PEER_BYTE = 0x6C              # the target's byte
N_AGE = 16                    # DRIVE_SAMPLEs in the age measurement
NCYC = 1600
MUTANTS = [("M_DS_SAMPLE_AFTER", "the sample is taken after the drive"),
           ("M_DS_NO_TXADV", "the TX register never shifts")]


def _hdrs(l0, park, mode=1, clkpin=I.PIN_NONE, order=I.ORDER_LSB):
    # an unclocked open-drain lane names its own pin as the clock (the load rule
    # wants a `uio` clock pin on an open-drain lane; equal to the pin = no clock)
    if mode == 0 and clkpin == I.PIN_NONE:
        clkpin = MOSI
    hdrs = [I.hdr(MOSI, clkpin, mode, D, 0, 2 * D, 3 * D, l0, order=order)]
    for n in range(1, I.N_LANES):
        hdrs.append(I.hdr(n + 2, n + 2, 0, 500, 0, 200, 240, park))
    return hdrs


def spi_image(same_pin=False, clocked=False, uo_pinb=False, order=I.ORDER_LSB):
    """lane 0: SCK low, then per bit DRIVE_SAMPLE(MOSI <- TX, sample MISO), SCK high,
    SCK low; parked. `same_pin`: the first DRIVE_SAMPLE samples its own pin (raw word,
    pe_isa's builder is bypassed so the RTL refusal can be run). `clocked`: the lane
    names a clock pin (pe_isa only). `uo_pinb`: the first DRIVE_SAMPLE samples
    uo_out pin 8, which has no input (pe_isa only, Wilson 11-20)."""
    l0 = I.ACT_BASE
    p = [I.act(I.OP_LEVEL, SCK, 0, D)]
    for _b in range(8):
        p += [I.act_drive_sample(MOSI, MISO, D, tx=True),
              I.act(I.OP_LEVEL, SCK, 1, D), I.act(I.OP_LEVEL, SCK, 0, D)]
    p.append(I.act(I.OP_LEVEL, I.PIN_NONE, 0, 900))
    p.append(I.act(I.OP_REARM, 0, 0, 900))
    if same_pin:
        p[1] = I.act(I.OP_DRIVE_SAMPLE, MOSI, 0, D, count=7, pinb=MOSI, mod=I.MOD_DS_TX)
    if uo_pinb:
        p[1] = I.act(I.OP_DRIVE_SAMPLE, MOSI, 0, D, count=7, pinb=I.UO0, mod=I.MOD_DS_TX)
    park = l0 + (len(p) - 1) * I.ACT_BYTES
    return I.join_image(_hdrs(l0, park, clkpin=5 if clocked else I.PIN_NONE,
                              order=order), p)


def age_image(mode=1):
    """lane 0: N_AGE DRIVE_SAMPLEs on MOSI of alternating level (1, 0, 1, ...),
    sampling uio[2]; two bytes pushed."""
    l0 = I.ACT_BASE
    p = [I.act_drive_sample(MOSI, MISO, D, level=(i + 1) % 2) for i in range(N_AGE)]
    p.append(I.act(I.OP_LEVEL, I.PIN_NONE, 0, 900))
    p.append(I.act(I.OP_REARM, 0, 0, 900))
    park = l0 + (len(p) - 1) * I.ACT_BYTES
    return I.join_image(_hdrs(l0, park, mode=mode), p)


COV_DIR = "probe_cov_ds"


def coverage_arms():
    """[(label, plusargs)] for test/benchset.py's tb_ds; images under COV_DIR ("ds_"-prefixed:
    the image universe keys images by name)."""
    os.makedirs(os.path.join(ROOT, COV_DIR), exist_ok=True)
    for k, img in (("spi", spi_image()), ("age", age_image()), ("od", age_image(mode=0)),
                   ("msb", spi_image(order=I.ORDER_MSB))):
        I.write_image(os.path.join(ROOT, COV_DIR, "ds_%s.hex" % k), img)
        sim_run.cov_image("run_drive_sample", os.path.join(ROOT, COV_DIR, "ds_%s.hex" % k))
    # 11-20: check 4's two RTL refusals join the sweep (the refusal branch read
    # uncovered). The image on disk is the CLEAN SPI image; the refused byte is planted
    # as tb_ds loads it (test/imgpatch.vh), because a refused image cannot be a sweep
    # arm's +IMG (gate_admissible_images' HDR check, not declarable)
    spi_plus = ["+IMG=%s/ds_spi.hex" % COV_DIR, "+NCYC=%d" % NCYC, "+FEED=1", "+PEER=1",
                "+PTX=%d" % PEER_BYTE]
    return [("samepin", spi_plus + I.patch_plusargs(spi_image(), spi_image(same_pin=True))),
            ("clocked", spi_plus + I.patch_plusargs(spi_image(), spi_image(clocked=True))),
            ("spi", ["+IMG=%s/ds_spi.hex" % COV_DIR, "+NCYC=%d" % NCYC, "+FEED=1", "+PEER=1",
                     "+PTX=%d" % PEER_BYTE]),
            ("age", ["+IMG=%s/ds_age.hex" % COV_DIR, "+NCYC=%d" % NCYC, "+PEER=2"]),
            ("od", ["+IMG=%s/ds_od.hex" % COV_DIR, "+NCYC=%d" % NCYC, "+PEER=2"]),
            # 11-20 (gate_coverage 4303 / 4316): TX with no host byte queued (the
            # underrun arm: no +FEED), and an MSB-first lane (the received byte
            # handed over bit-reversed)
            ("nofeed", ["+IMG=%s/ds_spi.hex" % COV_DIR, "+NCYC=%d" % NCYC, "+PEER=1",
                        "+PTX=%d" % PEER_BYTE]),
            ("msb", ["+IMG=%s/ds_msb.hex" % COV_DIR, "+NCYC=%d" % NCYC, "+FEED=1", "+PEER=1",
                     "+PTX=%d" % PEER_BYTE])]


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def build(out, defines=()):
    r = run([tool("iverilog"), "-g2012", "-I", ROOT, "-o", out, "-s", "tb_ds"]
            + ["-D%s" % d for d in defines] + [BENCH] + RTL)
    if r.returncode != 0:
        raise RuntimeError("build %s failed: %s" % (out, (r.stdout + r.stderr)[-400:]))


def sim(vvp, img, *plus):
    r = run(sim_run.vvp([vvp, "+IMG=%s" % img, "+NCYC=%d" % NCYC] + list(plus), images=[img]))
    out = r.stdout + r.stderr
    ev = [(int(c), oe, o) for c, oe, o in re.findall(r"^EV (\d+) (\d\d) (\d\d)$", out, re.M)]
    rx = [(int(c), int(d), int(ln)) for c, d, ln in re.findall(r"^RX (\d+) (\d+) (\d+)$", out, re.M)]
    pr = {int(c): int(b) for c, b in re.findall(r"^PR (\d+) (\d)$", out, re.M)}
    m = re.search(r"^PEER rx=(\d+) bits=(\d+)$", out, re.M)
    peer = int(m.group(1)) if m else None
    f = re.search(r"^FLT cfg=(\d) ovr=(\d)$", out, re.M)
    return {"ev": ev, "rx": rx, "pr": pr, "peer": peer,
            "flt": f.group(0) if f else "no FLT line", "end": "END" in out}


def bits(b):
    return "".join(str((b >> i) & 1) for i in range(8))    # LSB first, wire order


def round_trip(res):
    """[problem] for the SPI round trip: RX's first byte == PEER_BYTE, the peer's == TX_BYTE"""
    p = []
    got = res["rx"][0][1] if res["rx"] else None
    if got != PEER_BYTE:
        p.append("RX %s, want the target's %s (wire order %s vs %s)"
                 % (got if got is None else "0x%02X" % got, "0x%02X" % PEER_BYTE,
                    "-" if got is None else bits(got), bits(PEER_BYTE)))
    if res["peer"] != TX_BYTE:
        p.append("the target received %s, want 0x%02X (wire order %s vs %s)"
                 % ("nothing" if res["peer"] is None else "0x%02X" % res["peer"], TX_BYTE,
                    "-" if res["peer"] is None else bits(res["peer"]), bits(TX_BYTE)))
    if res["flt"] != "FLT cfg=0 ovr=0":
        p.append("faults: " + res["flt"])
    if not res["end"]:
        p.append("the bench did not finish")
    return p


def drive_edges(ev, n):
    """the first n edges at which uio[0]'s driven level changed"""
    out, prev = [], None
    for c, oe, o in ev:
        if oe[1] != "1":
            continue
        v = int(o[1])
        if v != prev:
            out.append(c)
        prev = v
    return out[:n]


def measure_age(res):
    """(age or None, [problem]): the offsets a (0..8) for which the bit latched at
    edge E_i - a predicts every sampled bit. A PR bit printed at c is latched at c + 1."""
    sampled = []
    for _c, d, ln in res["rx"][:2]:
        if ln == 0:
            sampled += [(d >> i) & 1 for i in range(8)]
    edges = drive_edges(res["ev"], N_AGE)
    if len(sampled) != N_AGE or len(edges) != N_AGE:
        return None, ["the age run gave %d sampled bits and %d drive edges, want %d"
                      % (len(sampled), len(edges), N_AGE)]
    fits = []
    for a in range(9):
        pred = [res["pr"].get(e - a - 1) for e in edges]
        if pred == sampled:
            fits.append(a)
    if len(fits) != 1:
        return None, ["the age is not determined: offsets %s fit" % fits]
    return fits[0], []


def main() -> int:
    banner("iverilog", "vvp")
    print()
    print("=" * 78)
    print("DRIVE_SAMPLE -- drive pin, sample pinb at the drive instant (Wilson 11-20)")
    print("=" * 78)
    probs = []
    tmp = tempfile.mkdtemp(prefix="pe_ds_")
    vvp = os.path.join(tmp, "ds.vvp")
    build(vvp)

    print("\n  1. full-duplex round trip vs an SPI mode-0 target (independent, in tb_ds)")
    ps = os.path.join(tmp, "ds_spi.hex")
    simg = spi_image()
    I.write_image(ps, simg)
    sim_run.scratch_image(GEN, ps)
    plus = ("+FEED=1", "+PEER=1", "+PTX=%d" % PEER_BYTE)
    res = sim(vvp, ps, *plus)
    pr = round_trip(res)
    print("    out 0x%02X -> target %s ; target 0x%02X -> RX %s   %s"
          % (TX_BYTE, "-" if res["peer"] is None else "0x%02X" % res["peer"], PEER_BYTE,
             "0x%02X" % res["rx"][0][1] if res["rx"] else "-", res["flt"]))
    print("    %s" % ("both bytes bit for bit" if not pr else "*** " + "; ".join(pr)))
    probs += pr

    print("\n  2. the sample's age (a new pseudo-random bit on pinb every cycle)")
    pa = os.path.join(tmp, "ds_age.hex")
    I.write_image(pa, age_image())
    sim_run.scratch_image(GEN, pa)
    ares = sim(vvp, pa, "+PEER=2")
    age, ap = measure_age(ares)
    if age is not None and age != clock.DS_SAMPLE_AGE:
        ap.append("measured age %d != model/clock.py DS_SAMPLE_AGE %d" % (age, clock.DS_SAMPLE_AGE))
    print("    measured %s; clock.DS_SAMPLE_AGE = %d (the pad as latched %d edge(s) before "
          "the edge this drive reaches it)" % (age, clock.DS_SAMPLE_AGE, clock.DS_SAMPLE_AGE))
    print("    %s" % ("equal, and determined by all %d samples" % N_AGE if not ap
                      else "*** " + "; ".join(ap)))
    probs += ap

    print("\n  3. open-drain: never drives a 1")
    po = os.path.join(tmp, "ds_od.hex")
    I.write_image(po, age_image(mode=0))
    sim_run.scratch_image(GEN, po)
    ores = sim(vvp, po, "+PEER=2")
    hi = [c for c, oe, o in ores["ev"] if oe[1] == "1" and o[1] == "1"]
    lows = [c for c, oe, o in ores["ev"] if oe[1] == "1" and o[1] == "0"]
    ok = not hi and len(lows) >= N_AGE // 2 - 1
    print("    %s (driven-low edges %d, driven-high %d)"
          % ("released for 1, driven for 0" if ok else "*** WRONG", len(lows), len(hi)))
    if not ok:
        probs.append("open-drain DRIVE_SAMPLE: driven high %s, driven low %d times" % (hi, len(lows)))

    print("\n  4. refusals")
    for what, name, img in (("pin == pinb", "ds_samepin.hex", spi_image(same_pin=True)),
                            ("a clocked lane", "ds_clocked.hex", spi_image(clocked=True))):
        pp = os.path.join(tmp, name)
        I.write_image(pp, img)
        sim_run.scratch_image(GEN, pp)
        rres = sim(vvp, pp, *plus)
        drove = [c for c, oe, o in rres["ev"] if oe[1] == "1" and o[1] == "1"]
        rok = rres["flt"] == "FLT cfg=1 ovr=1" and not drove
        print("    RTL, %s: %s (%s, MOSI driven high %d times)"
              % (what, "refused" if rok else "*** NOT REFUSED", rres["flt"], len(drove)))
        if not rok:
            probs.append("the RTL did not refuse %s (%s)" % (what, rres["flt"]))
    for what, img in (("pin == pinb", spi_image(same_pin=True)),
                      ("a clocked lane", spi_image(clocked=True)),
                      ("pinb on uo_out (planted pinb = 8)", spi_image(uo_pinb=True))):
        q = I.drive_sample_problems(img)
        print("    pe_isa, %s: %s" % (what, ("refused (%s)" % q[0]) if q else "*** ACCEPTED"))
        if not q:
            probs.append("pe_isa accepted DRIVE_SAMPLE with %s" % what)
    for what, img in (("SPI", simg), ("age", age_image())):
        q = I.drive_sample_problems(img) + I.unread_problems(img)
        print("    pe_isa, the clean %s image: %s" % (what, "accepted" if not q else "*** REFUSED: %s" % q))
        if q:
            probs.append("pe_isa refused the clean %s image" % what)

    print("\n  must-fires (the round trip)")
    for d, what in MUTANTS:
        mv = os.path.join(tmp, "ds_%s.vvp" % d)
        build(mv, [d])
        mres = sim(mv, ps, *plus)
        red = bool(round_trip(mres))
        print("    %-18s %-38s %s" % (d, what, ("RED: " + round_trip(mres)[0]) if red else "*** SURVIVED"))
        if not red:
            probs.append("%s survived" % d)
    print()
    for x in probs:
        print("  *** %s" % x)
    print("=" * 78)
    print("  GATE drive-sample: %s" % ("PASSED" if not probs else "FAILED"))
    return 0 if not probs else 1


if __name__ == "__main__":
    sys.exit(main())
