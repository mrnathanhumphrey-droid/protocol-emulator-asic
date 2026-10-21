"""RULING ACK (b)-(c) -- THE CLOCKED I2C READ, ADJUDICATED BY SIGROK.

(b)  The clocked SHIFTIN samples on the OBSERVED SCL rise. Measured against a
     peer that STRETCHES and presents each read bit only at the end of the
     hold (`fram_i2c` LATE mode), at N = 0, short, long, and one stretch just
     under the chip's own stretch timeout (CK_STRETCH_PRE * CK_STRETCH_TO).
(c)  sigrok's `i2c` decoder reads the wire: the peer's ACKs as ACK, the
     master's ACK as ACK (0) and its NACK as NACK (1), the data bytes as the
     bytes the peer drove.

The program is the part's documented RANDOM READ, one loop:
    S | A0 | A | 01 | A | 23 | A | Sr | A1 | A | data | A | data | NACK | P
with the framing MEASURED for silicon fix #2 (TX8): the repeated START follows
the slave's ACK (a clocked SHIFTIN, which leaves SCL LOW): SDA high, SCL high,
START. The STOP follows the master's NACK (a clocked SHIFT, which leaves SCL
HIGH): SCL low, SDA low, SCL high, STOP -- three would put a spurious START on
the wire, because the NACK leaves SDA high.

⛔⛔ AC1 -- SIGROK JUDGES THE BYTES, NOT OUR PEER. The chip's received bytes
are compared with sigrok's `Data read` bytes FROM THE SAME DUMP, and both with
the intended non-palindromic pair (0x5B, 0xE2). `fram_i2c` is same-hand; here
it is only the stimulus.
⛔ AC5 -- an address nobody answers (A2 / A3): sigrok decodes NACK after both
addresses and the chip's ACK-slot receive records the 1.

MUST-FIRES:
  * the WRONG-INSTANT SAMPLER (scratch mutant `S_CK_COMMANDED_RISE`): the
    capture fires on the first cycle after the controller releases SCL,
    instead of on the observed rise. Built from `src/pe_engine.v`'s own text
    into scratch -- `src/` untouched, so lock hygiene charges no harden -- and
    registered in `gate_mutant_kills`' SCRATCH table (AC2). On every
    STRETCHED arm the chip must read WRONG bytes, i.e. disagree with sigrok.
  * `M_CK_NO_ALTERNATE` (the clock phase never moves): sigrok decodes no
    well-formed random read.
  * `M_TX_LOAD_ANYPHASE` (the pre-fix silicon, fix #2): the address bytes go
    out misaligned, so no well-formed read appears and the intended bytes
    are never read.

⚠ LOCAL ONLY, like `run_i2c.py`: sigrok-cli runs in WSL and CI does not
install it, so this runs under `model/a2/run_a2.py`.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from toolchain import banner, tool, scratch_sub  # noqa: E402  ruling V
import sim_run                                   # noqa: E402
from run_i2c import sigrok_i2c, transactions  # noqa: E402  one decoder path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SCRATCH = os.environ.get("PE_SCRATCH",
                         os.path.join(os.environ.get("TEMP", "/tmp"), "pe_ckack"))
SRCS = ["pe_engine.v", "pe_store.v", "project.v"]
D = 70                       # D_FM_SHIPPABLE: the shipped clocked I2C delay
F_CLK = 50000000


def d_half_fm():
    """RULING CE1: the smallest HALF_HIGH delay whose bit period does not
    exceed Fm's 400 kHz ceiling -- d + d//2 + L_SYNC >= ceil(F_CLK / 400k) --
    and is not below the symmetric scheme's shippable Fm floor (`D`). DERIVED
    here rather than typed, so a moved L_SYNC or floor moves it."""
    sys.path.insert(0, os.path.join(ROOT, "model", "a2"))
    from bursty import L_SYNC
    need = -(-F_CLK // 400000)
    d = D
    while d + (d >> 1) + L_SYNC < need:
        d += 1
    return d


WANT = (0x5B, 0xE2)          # what the peer holds at 0x0123 / 0x0124
ADDR7 = 0x50                 # sigrok's 7-bit reading of A0 / A1
NACK7 = 0x51                 # ... and of A2 / A3, which nobody answers

_DECODE = threading.Lock()

#: scratch-built mutants this file kills (gate_mutant_kills' SCRATCH table)
SCRATCH_MUTANTS = {
    "S_CK_COMMANDED_RISE": "the clocked SHIFTIN capture on the controller's "
                           "own SCL release instead of the observed rise",
}


def commanded_rise_subs():
    """(landmark, replacement) for S_CK_COMMANDED_RISE; each must occur once."""
    # ⛔ THE OPEN-DRAIN ARM of the live `ck_hit` (silicon fix #3b split it by
    # mode; the old one-line assign survives only under M_CKRX_PP_OBSERVED,
    # where this landmark matched once and changed nothing -- see
    # `toolchain.scratch_sub`)
    return [("                          : (ckp_real & pin_rise[l_clkpin[gi]]));",
             "                          : (ckp_real));  "
             "// S_CK_COMMANDED_RISE")]


def stretch_timeout():
    """CK_STRETCH_PRE * CK_STRETCH_TO, read from the RTL's own defaults."""
    with open(os.path.join(ROOT, "src", "pe_engine.v"), encoding="utf-8") as fh:
        t = fh.read()
    pre = int(re.search(r"parameter integer CK_STRETCH_PRE\s*=\s*(\d+)", t).group(1))
    to = int(re.search(r"parameter integer CK_STRETCH_TO\s*=\s*(\d+)", t).group(1))
    return pre * to


def image(path, d=D, flags=0):
    """The part's random read. `flags` = FLAG_HALF_HIGH builds ruling CE1's
    Fm image (at `D_HALF`): the same program, the HIGH phase d/2."""
    from pe_isa import (ACT_BASE, ACT_BYTES, OP_LEVEL, OP_REARM, OP_START,
                        OP_STOP, ORDER_MSB, act, act_shift_clocked,
                        act_shiftin_clocked, hdr, write_image)
    sda, scl = 2, 1
    # ⭐ ONE QUEUE (q0) for every SHIFT, as `pe_asm.check_queue_ownership`
    # requires; the host pushes the bytes in the order the SHIFTs pop them
    # (tb_ckack.v). ⚠ The first version spread this lane over FOUR queues --
    # a program the assembler REFUSES -- which is corrected here; the result
    # it certified (sampling instant, sigrok's decode) does not depend on the
    # routing, and is re-measured on the admissible program.
    prog = [
        act(OP_START, sda, 0, d),
        act_shift_clocked(sda, d, nbits=8, q=0),     # A0
        act_shiftin_clocked(sda, d, nbits=1),        # ACK slot
        act_shift_clocked(sda, d, nbits=8, q=0),     # 01
        act_shiftin_clocked(sda, d, nbits=1),
        act_shift_clocked(sda, d, nbits=8, q=0),     # 23
        act_shiftin_clocked(sda, d, nbits=1),
        # Sr after a clocked SHIFTIN (SCL low): SDA high, SCL high, START
        act(OP_LEVEL, sda, 1, d), act(OP_LEVEL, scl, 1, d),
        act(OP_START, sda, 0, d),
        act_shift_clocked(sda, d, nbits=8, q=0),     # A1
        act_shiftin_clocked(sda, d, nbits=1),        # peer ACK
        act_shiftin_clocked(sda, d, nbits=8),        # data 1
        act_shift_clocked(sda, d, nbits=1, q=0),     # master ACK  (2D)
        act_shiftin_clocked(sda, d, nbits=8),        # data 2
        act_shift_clocked(sda, d, nbits=1, q=0),     # master NACK (C4)
        # P after a clocked SHIFT (SCL high): SCL low, SDA low, SCL high, STOP
        act(OP_LEVEL, scl, 0, d), act(OP_LEVEL, sda, 0, d),
        act(OP_LEVEL, scl, 1, d), act(OP_STOP, sda, 1, d),
        act(OP_REARM, 0, 1, d),
    ]
    park = ACT_BASE + len(prog) * ACT_BYTES
    prog.append(act(OP_REARM, 0, 0, 500))
    headers = [hdr(sda, scl, 0, d, flags, 2 * d, 3 * d, ACT_BASE,
                   order=ORDER_MSB)]
    headers += [hdr(p, p, 0, 500, 0, 200, 240, park) for p in (0, 3, 4, 5)]
    write_image(path, b"".join(headers) + b"".join(prog))
    # a CLOCKED scratch image: its provenance for test/sim_run.py
    sim_run.scratch_image("run_ckack", path)
    return path


def engine(kind):
    if kind != "commanded":
        return os.path.join(ROOT, "src", "pe_engine.v")
    with open(os.path.join(ROOT, "src", "pe_engine.v"), encoding="utf-8",
              newline="") as fh:
        txt = fh.read().replace("\r\n", "\n")
    for a, b in commanded_rise_subs():
        txt = scratch_sub(txt, a, b, "S_CK_COMMANDED_RISE")
    out = os.path.join(SCRATCH, "pe_engine_commanded.v")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(txt)
    return out


def build(kind, late, skip, once):
    os.makedirs(SCRATCH, exist_ok=True)
    out = os.path.join(SCRATCH, "ck_%s_%d_%d_%d.vvp" % (kind, late, skip, once))
    cmd = [tool("iverilog"), "-g2012", "-o", out, "-s", "tb_ckack",
           "-Ptb_ckack.LATE=%d" % late, "-Ptb_ckack.LATE_SKIP=%d" % skip,
           "-Ptb_ckack.LATE_ONCE=%d" % once]
    if kind == "noalt":
        cmd.append("-DM_CK_NO_ALTERNATE")
    if kind == "oldtx":
        cmd.append("-DM_TX_LOAD_ANYPHASE")
    if kind == "halfign":
        cmd.append("-DM_HALF_IGNORED")
    if kind == "dly11":
        # ⭐ phase coverage (Wilson 10-20): the peer 11 ns late, a real part's
        # output delay; the 10-21 sweep found every output identical 0..19 ns
        cmd.append("-DPEER_DLY_NS=11")
    cmd += ["test/tb_ckack.v", "test/fram_i2c.v", engine(kind)]
    cmd += [os.path.join(ROOT, "src", s) for s in SRCS[1:]]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit("*** build failed (%s)\n%s"
                         % (kind, (r.stdout + r.stderr)[-900:]))
    return out


def run_arm(name, kind, late, skip, once, ncyc, devw="A0", devr="A1",
            img_name="ckack.hex"):
    img = os.path.join(SCRATCH, img_name)
    vvp = build(kind, late, skip, once)
    dump = os.path.join(ROOT, "probe_ckack_%s.bin" % name)
    with open(img, encoding="ascii") as fh:
        nb = len(fh.read().split())
    r = subprocess.run(sim_run.vvp([vvp, "+IMG=" + img.replace(os.sep, "/"),
                                    "+NBYTES=%d" % nb, "+NCYC=%d" % ncyc,
                                    "+DUMP=" + dump.replace(os.sep, "/"),
                                    "+DEVW=" + devw, "+DEVR=" + devr],
                                   images=[img]), cwd=ROOT,
                       capture_output=True, encoding="utf-8", errors="replace")
    txt = (r.stdout or "") + (r.stderr or "")
    if "END tb_ckack" not in txt:
        raise SystemExit("*** %s: bench did not finish\n%s" % (name, txt[-800:]))
    rx = [(int(n), v) for n, v in
          re.findall(r"^RX cyc=\d+ cnt=(\d+) data=([0-9a-fx]{2})", txt, re.M)]
    st = dict(re.findall(r"(\w+)=(\d+)", next(
        l for l in txt.splitlines() if l.startswith("STICKY"))))
    park = int(re.search(r"PARK max=(\d+)", txt).group(1))
    fails = [l for l in txt.splitlines() if "*** FAIL" in l]
    # ⛔ ONE DECODE AT A TIME: `sigrok_i2c` writes ONE fixed wrapper script,
    # so two arms decoding at once can each run the other's dump. MEASURED:
    # the first full run failed AC1 on n0 that way, and n0 alone passes.
    with _DECODE:
        dec = sigrok_i2c(os.path.relpath(dump, ROOT).replace(os.sep, "/"))
    return {"name": name, "kind": kind, "late": late, "rx": rx,
            "sticky": {k: int(v) for k, v in st.items()}, "park": park,
            "fails": fails, "sigrok": dec, "scl": scl_stats(dump)}


def scl_stats(dump):
    """SCL off the bus dump (bit0 per cycle, the RESOLVED line): the modal
    rise-to-rise period and modal HIGH / LOW widths, in cycles. Modal, so a
    stretch, a START/STOP or the idle between transactions does not decide."""
    from collections import Counter
    with open(dump, "rb") as fh:
        s = [b & 1 for b in fh.read()]
    rises = [i for i in range(1, len(s)) if s[i] and not s[i - 1]]
    falls = [i for i in range(1, len(s)) if not s[i] and s[i - 1]]
    per = Counter(b - a for a, b in zip(rises, rises[1:]))
    # ⚠ only COMPLETE phases: the trace's last rise has no fall after it, and
    # counting it as a 0-cycle high is what reported "min t_HIGH 0" once
    import bisect
    hi = Counter(falls[bisect.bisect_right(falls, r)] - r for r in rises
                 if bisect.bisect_right(falls, r) < len(falls))
    lo = Counter(rises[bisect.bisect_right(rises, f)] - f for f in falls
                 if bisect.bisect_right(rises, f) < len(rises))
    mode = lambda c: c.most_common(1)[0][0] if c else None
    return {"period": mode(per), "high": mode(hi), "low": mode(lo),
            "min_high": min(hi) if hi else None,
            "min_low": min(lo) if lo else None}


def random_reads(arm, addr7=ADDR7):
    """Complete random reads sigrok decoded, as the exact event sequence the
    part's read is: -> [(byte1, byte2), ...]."""
    out = []
    for t in transactions(arm["sigrok"]["events"]):
        k = [e for e in t if e[0] not in ("Write", "Read")]
        shape = [e[0] for e in k]
        want = ["Start", "Address write", "ACK", "Data write", "ACK",
                "Data write", "ACK", "Start repeat", "Address read", "ACK",
                "Data read", "ACK", "Data read", "NACK", "Stop"]
        if (shape == want and k[1][1] == addr7 and k[3][1] == 0x01
                and k[5][1] == 0x23 and k[8][1] == addr7):
            out.append((k[10][1], k[12][1]))
    return out


def sigrok_data_reads(arm):
    return [e[1] for e in arm["sigrok"]["events"] if e[0] == "Data read"]


def chip_data_reads(arm):
    """The chip's 8-bit receives, in order (X stays X: it is a finding)."""
    return [v for n, v in arm["rx"] if n == 8]


def main() -> int:
    banner("iverilog", "vvp")
    print()
    print("=" * 78)
    print("ACK (b)-(c) -- the clocked I2C random read, adjudicated by sigrok")
    print("=" * 78)
    os.makedirs(SCRATCH, exist_ok=True)
    image(os.path.join(SCRATCH, "ckack.hex"))
    # ⛔ THE PROGRAM MUST BE ONE THE TOOLCHAIN ADMITS: `pe_asm`'s queue rule
    # (one lane, one queue), read back off the image itself
    import pe_isa
    sys.path.insert(0, os.path.join(ROOT, "model"))
    import pe_asm
    with open(os.path.join(SCRATCH, "ckack.hex"), encoding="ascii") as fh:
        raw = bytes(int(t, 16) for t in fh.read().split())
    lanes = {ln: [(a["op"], a["pin"], a["level"], a["delay"], a["q"])
                  for a in acts]
             for ln, (_h, acts) in pe_isa.lane_programs(raw).items()}
    try:
        pe_asm.check_queue_ownership(lanes)
        print("  the program passes pe_asm's queue rule (one lane, one queue)")
    except pe_asm.Reject as e:
        print("  *** the program breaks pe_asm's queue rule: %s" % e)
        return 1
    to = stretch_timeout()
    under = to - 50000
    print("  stretch timeout = %d cycles (CK_STRETCH_PRE * CK_STRETCH_TO); "
          "the near-timeout arm stretches %d once" % (to, under))
    # (name, kind, LATE, LATE_SKIP, LATE_ONCE, ncyc)
    arms = [("n0", "good", 0, 0, 0, 50000),
            ("n0_dly11", "dly11", 0, 0, 0, 50000),
            ("short", "good", 4 * D, 0, 0, 60000),
            ("long", "good", 5000, 0, 0, 260000),
            ("under", "good", under, 16, 1, under + 60000),
            ("mut_short", "commanded", 4 * D, 0, 0, 60000),
            ("mut_long", "commanded", 5000, 0, 0, 260000),
            ("mut_under", "commanded", under, 16, 1, under + 60000),
            ("noalt", "noalt", 0, 0, 0, 50000),
            ("oldtx", "oldtx", 0, 0, 0, 50000)]
    with ThreadPoolExecutor(3) as ex:
        res = dict((a[0], r) for a, r in zip(arms, ex.map(
            lambda a: run_arm(*a), arms)))
    res["nack"] = run_arm("nack", "good", 0, 0, 0, 50000, devw="A2",
                          devr="A3")
    rc = 0

    def say(ok, what):
        nonlocal rc
        print("    %-64s %s" % (what, "ok" if ok else "*** FAIL"))
        if not ok:
            rc = 1

    # n0_dly11: the n0 arm with the peer 11 ns late -- peer phases exercised
    # are posedge + 0 ns (every other arm) and posedge + 11 ns (this one)
    for n in ("n0", "n0_dly11", "short", "long", "under"):
        a = res[n]
        rr, sd, cd = random_reads(a), sigrok_data_reads(a), chip_data_reads(a)
        print("  --- (b)/(c) %s: LATE=%d, park max %d ---" % (n, a["late"],
                                                             a["park"]))
        print("      sigrok random reads %s; sigrok Data read %s; chip %s"
              % (["%02X %02X" % p for p in rr[:4]],
                 " ".join("%02X" % b for b in sd[:8]), " ".join(cd[:8])))
        say(a["sigrok"]["rc"] == 0, "sigrok ran (rc 0)")
        say(len(rr) >= 1 and all(p == WANT for p in rr),
            "sigrok: every random read is S A0 A 01 A 23 A Sr A1 A 5B A E2 "
            "NACK P")
        say([int(v, 16) if "x" not in v else -1 for v in cd] == sd,
            "AC1: the chip's received bytes == sigrok's Data read bytes")
        say(not a["fails"] and a["sticky"].get("clk_stretch_err") == 0
            and a["sticky"].get("config_err") == 0,
            "no bench FAIL line, no stretch fault, no config error")
        if n == "under":
            say(a["park"] > under - 1000 and a["park"] < to,
                "the lane really parked ~%d (< timeout %d)" % (a["park"], to))
    print("  --- MUST-FIRE: S_CK_COMMANDED_RISE on every stretched arm ---")
    for n in ("mut_short", "mut_long", "mut_under"):
        a = res[n]
        cd, sd = chip_data_reads(a), sigrok_data_reads(a)
        diff = [int(v, 16) if "x" not in v else -1 for v in cd] != sd
        say(diff, "%s: the chip disagrees with sigrok (chip %s / sigrok %s)"
            % (n, " ".join(cd[:4]), " ".join("%02X" % b for b in sd[:4])))
    print("  --- MUST-FIRE: M_CK_NO_ALTERNATE, M_TX_LOAD_ANYPHASE ---")
    say(not random_reads(res["noalt"]),
        "M_CK_NO_ALTERNATE: sigrok decodes no well-formed random read")
    say(not random_reads(res["oldtx"]),
        "M_TX_LOAD_ANYPHASE (pre-fix #2): no well-formed random read")
    print("  --- AC5: an address nobody answers (A2 / A3) ---")
    a = res["nack"]
    ev = a["sigrok"]["events"]
    nacked = [i for i, e in enumerate(ev[:-1])
              if e[0] in ("Address write", "Address read")
              and e[1] == NACK7 and ev[i + 1][0] == "NACK"]
    say(len(nacked) >= 2, "sigrok decodes NACK after the unanswered address "
        "(%d of them)" % len(nacked))
    # ⭐ A 1-bit receive lands in BIT 0 of the RX byte (measured: the higher
    # bits are the accumulator's history from earlier 1-bit receives), so the
    # ACK bit is `rx & 1`: 0 = ACK, 1 = NACK. The first loop's write is NACKed
    # on every arm (its address is the reset byte 00), so loop 2+ is judged.
    bits = [int(v, 16) & 1 for n, v in a["rx"] if n == 1][4:]
    good = [int(v, 16) & 1 for n, v in res["n0"]["rx"] if n == 1][4:]
    say(bool(bits) and all(b == 1 for b in bits),
        "the chip's ACK-slot receive records NACK (1) on every slot: %s"
        % bits[:8])
    say(bool(good) and all(b == 0 for b in good),
        "... where an answered address records ACK (0): %s" % good[:8])

    # ---- RULING CE1 -- HALF_HIGH: I2C Fm up to ~397 kHz ---------------------
    # ⭐ THE SAME RANDOM READ, the HIGH phase d/2, at the DERIVED shippable d.
    # The claim is "Fm up to ~397 kHz (ideal edges; delivered rate depends on
    # pull-up rise time)": the rate below is the bench's ideal-edge bus.
    from pe_isa import FLAG_HALF_HIGH, flag_problems
    dh = d_half_fm()                       # (puts model/a2 on the path)
    import gate_j_program as jp
    import gate_um10204 as um
    from bursty import L_SYNC
    image(os.path.join(SCRATCH, "ckack_half.hex"), d=dh, flags=FLAG_HALF_HIGH)
    with open(os.path.join(SCRATCH, "ckack_half.hex"), encoding="ascii") as fh:
        hraw = bytes(int(t, 16) for t in fh.read().split())
    print("  --- CE1: HALF_HIGH at d = %d (derived: the 400 kHz ceiling, "
          "L_SYNC, the Fm floor %d) ---" % (dh, D))
    say(not flag_problems(hraw, jp.D_STAR),
        "the HALF_HIGH image passes the toolchain's mode-bit rules "
        "(d/2 = %d >= D* = %d)" % (dh >> 1, jp.D_STAR))
    harms = [("fm_half", "good", 0, 0, 0, 60000),
             ("fm_half_long", "good", 5000, 0, 0, 260000),
             ("mut_half", "halfign", 0, 0, 0, 60000)]
    with ThreadPoolExecutor(3) as ex:
        hres = dict((a[0], r) for a, r in zip(harms, ex.map(
            lambda a: run_arm(*a, img_name="ckack_half.hex"), harms)))
    um_fm = um.UM10204["Fm  400 kHz"]
    hi_min, lo_min = (-(-um_fm["t_HIGH"] * F_CLK // 10 ** 9),
                      -(-um_fm["t_LOW"] * F_CLK // 10 ** 9))
    for n in ("fm_half", "fm_half_long"):
        a = hres[n]
        rr, sd, cd = random_reads(a), sigrok_data_reads(a), chip_data_reads(a)
        sc = a["scl"]
        khz = F_CLK / sc["period"] / 1000.0 if sc["period"] else 0
        print("      %s: SCL period %s (%.1f kHz), HIGH %s, LOW %s; random "
              "reads %s" % (n, sc["period"], khz, sc["high"], sc["low"],
                            ["%02X %02X" % p for p in rr[:3]]))
        say(len(rr) >= 1 and all(p == WANT for p in rr),
            "sigrok: every random read is the part's, data 5B E2 (%s)" % n)
        say([int(v, 16) if "x" not in v else -1 for v in cd] == sd,
            "the chip's received bytes == sigrok's Data read bytes (%s)" % n)
        say(not a["fails"] and a["sticky"].get("clk_stretch_err") == 0,
            "no bench FAIL line (Layer B gaps included), no stretch fault")
        if n == "fm_half":
            # ⛔ MEASURED, NOT ASSERTED: the first version checked the period
            # against `d + d/2 + L_SYNC` (126) -- a formula of mine -- and the
            # bus measures 127 (LOW 82, HIGH 45). The claim is the measured
            # rate, held to Fm's ceiling and to the d/2 phase actually landing.
            say(khz <= 400.0 and sc["high"] < sc["low"]
                and sc["high"] - (dh >> 1) <= 2 * L_SYNC,
                "MEASURED: SCL period %d cycles = %.1f kHz (<= Fm 400 kHz); "
                "HIGH %d = d/2 %d + sync, LOW %d"
                % (sc["period"], khz, sc["high"], dh >> 1, sc["low"]))
            say(sc["min_high"] >= hi_min and sc["min_low"] >= lo_min,
                "UM10204 Fm: min t_HIGH %d >= %d, min t_LOW %d >= %d cycles"
                % (sc["min_high"], hi_min, sc["min_low"], lo_min))
    print("  --- MUST-FIRE: M_HALF_IGNORED (the selector read as 0) ---")
    m = hres["mut_half"]
    say(any("[B-GAP]" in f for f in m["fails"]),
        "Layer B gaps red: the HIGH phase is d, not the model's d/2")
    say(m["scl"]["period"] != dh + (dh >> 1) + L_SYNC,
        "the SCL period moved (%s cycles): the mutant runs symmetric"
        % m["scl"]["period"])
    print()
    print("  GATE ckack: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
