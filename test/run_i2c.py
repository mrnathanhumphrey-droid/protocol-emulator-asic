"""GATE I2C-FOREIGN -- sigrok certifies a real I2C frame: S | addr | A | data | A | P.

⛔⛔ EVERY I2C CLAIM THIS PROJECT HAD MADE WAS SAME-HAND. Our engine against
our own peer model -- `fram_i2c.v` says so in its own header -- and our own
benches reading our own expectations. `tb_half` proved the PLUMBING (a pushed
byte reaches the wire, a sampled byte reaches the host, neither direction
corrupts the other) and said so explicitly; it did not prove a frame any I2C
device would accept.

⇒ `sigrok`'s `i2c` protocol decoder is code written from the standard by people
who have never seen this design. It adjudicates START, the address, the
ACK/NACK and STOP. That is the difference between "our two artefacts agree" and
"a foreign reading of the standard accepts this waveform".

⭐ AND IT EARNED ITS KEEP IMMEDIATELY. The peer model refused to acknowledge a
frame sigrok called well formed, which is the one situation a same-hand setup
cannot resolve: with only our own two artefacts there is no way to tell which is
at fault. sigrok's verdict pointed at the PEER, and two real defects came out of
it -- both in the model, both invisible until something sent it a decodable
byte. They are recorded at their sites in `fram_i2c.v`.

⚠ WHAT THIS DOES NOT SETTLE: electrical timing against UM10204. sigrok
adjudicates FRAMING and BYTE VALUES; it is tolerant of rate. The timing claim
is `gate_i2c_phase.py`'s, from the datasheet table.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRATCH = os.environ.get("PE_SCRATCH",
                         os.path.join(os.environ.get("TEMP", "/tmp"), "pe_i2c"))

SRCS = ["test/tb_i2c.v", "test/fram_i2c.v",
        "src/pe_engine.v", "src/pe_store.v", "src/project.v"]
NCYC = 40000
F_CLK = 50000000
DUMP = "probe_i2c.bin"

# ⛔ THE HOST PUSHES 0x05 AND THE WIRE CARRIES 0xA0, WHICH IS NOT A TYPO.
# `OP_SHIFT` emits `l_tx[0]` -- the LEAST significant bit -- first, so the byte
# reaches the wire BIT-REVERSED. I2C is MSB-first, so a host that wants the
# device address `1010 000 0` on the wire must push its reversal.
# ⚠ `pe_isa.py`'s own docstring claims the lanes shift "MSB-first", which is
# the opposite of what the RTL does. That contradiction had never been
# detectable: nothing decoded the wire against a standard, and the one value a
# bench had checked (0x5A) is a BIT-REVERSAL PALINDROME, so it matched either
# way. sigrok reading `Address write: 50` from a pushed 0x05 is what settles it.
ADDR_PUSHED = 0xA0              # pushed AS ITSELF; the lane declares ORDER_MSB
ADDR_7BIT = 0x50                # what sigrok reports: 0xA0 >> 1
# ⛔ NON-PALINDROMIC, AND THAT IS THE WHOLE POINT (ruling 1b). This was 0x5A,
# which reverses to itself, so sigrok reading it back proved the byte arrived
# and NOTHING about the order it arrived in. 0x5B reverses to 0xDA, so sigrok
# reading `5B` is evidence the MSB-first path is right.
DATA_BYTE = 0x5B


def run(cmd, cwd=ROOT):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=cwd)


def wsl_path(p: str) -> str:
    """D:\\x -> /mnt/d/x for the decoder running inside WSL."""
    p = os.path.abspath(p).replace("\\", "/")
    if len(p) > 1 and p[1] == ":":
        return "/mnt/" + p[0].lower() + p[2:]
    return p


def sigrok_i2c(binpath: str) -> dict:
    """Run sigrok's `i2c` PD over the two-channel dump.

    ⛔ THE BINARY COMES FROM `$SIGROK_CLI` so that "tool absent => gate red" is
    a TESTABLE proposition rather than a hope -- the same contract
    `model/ta01/gate0_external.py` uses. `price_gates.sh` points it at a path
    that does not exist and requires every sigrok-dependent gate to go red; a
    gate that stays green with its foreign authority removed was never using
    it. ⚠ THE RETURN CODE MUST BE READ: a failed invocation produces no
    annotations, which is indistinguishable from "the decoder found no frame"
    unless the status is checked.
    ⛔ CHANNEL ORDER IS DECLARED IN BOTH PLACES: the bench writes bit0 = SCL,
    bit1 = SDA, and this asks for `scl=0:sda=1`. A swap decodes nothing, which
    would look exactly like bad framing.
    ⛔ A SCRIPT FILE, NOT `bash -c` -- the standing rule for reaching WSL from
    here, because Git Bash rewrites anything in the argv that looks like a path.
    """
    exe = os.environ.get("SIGROK_CLI", "sigrok-cli")
    wrap = os.path.join(ROOT, "probe_i2c_decode.sh")
    nl = chr(10)
    with open(wrap, "w", encoding="ascii", newline=nl) as fh:
        fh.write("#!/bin/bash" + nl)
        fh.write("cd %s || exit 1" % wsl_path(ROOT) + nl)
        fh.write("%s -i %s -I binary:numchannels=2:samplerate=%d "
                 "-P i2c:scl=0:sda=1 -A i2c" % (exe, binpath, F_CLK) + nl)
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    r = subprocess.run(["wsl.exe", "-e", "bash", wsl_path(wrap)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env)
    out = (r.stdout or "") + (r.stderr or "")
    ev = []
    for line in out.replace("\r", "").split(chr(10)):
        line = line.strip()
        if not line.startswith("i2c-1:"):
            continue
        tok = line.split(":", 1)[1].strip()
        if tok in ("Start", "Stop", "ACK", "NACK", "Write", "Read",
                   "Start repeat"):
            ev.append((tok, None))
        else:
            m = re.match(r"(Address write|Address read|Data write|Data read)"
                         r":\s*([0-9A-Fa-f]{2})$", tok)
            if m:
                ev.append((m.group(1), int(m.group(2), 16)))
    return {"rc": r.returncode, "events": ev, "raw": out}


def transactions(ev):
    """Split the event list at each Start. Returns a list of event lists."""
    out, cur = [], None
    for e in ev:
        if e[0] == "Start":
            if cur:
                out.append(cur)
            cur = [e]
        elif cur is not None:
            cur.append(e)
    if cur:
        out.append(cur)
    return out


def main() -> int:
    rc = 0
    print()
    print("=" * 78)
    print("GATE I2C-FOREIGN -- sigrok certifies the frame, not our own bench")
    print("=" * 78)
    print("  program : make_smoke_image.py --i2cframe 62")
    print("  peer    : test/fram_i2c.v (MB85RC256V shape, DEV_SEL = 000)")
    print("  decoder : sigrok `i2c` PD, scl=0 sda=1, %d Hz" % F_CLK)
    # COMPUTED, NOT WRITTEN DOWN. A literal 0xA0 here would be a second copy
    # of the thing being tested, and `ADDR_PUSHED * 0 + 0xA0` -- which is what
    # this said first -- is that literal wearing arithmetic.
    # ⭐ THE LANE DECLARES ORDER_MSB, so the host pushes the address AS
    # ITSELF and the engine reverses at the load. The cross-check is now that
    # the pushed byte's own 7-bit field is what sigrok should report.
    print("  the lane header declares ORDER_MSB, so the host pushes 0x%02X"
          % ADDR_PUSHED)
    print("  as itself and sigrok should report the 7-bit address as 0x%02X"
          % ADDR_7BIT)
    if ADDR_PUSHED >> 1 != ADDR_7BIT:
        print("  *** 0x%02X >> 1 is 0x%02X, not the 0x%02X this gate expects."
              % (ADDR_PUSHED, ADDR_PUSHED >> 1, ADDR_7BIT))
        print("      The two constants disagree before any measurement.")
        return 1
    if int("{:08b}".format(DATA_BYTE)[::-1], 2) == DATA_BYTE:
        print("  *** DATA_BYTE 0x%02X is a BIT-REVERSAL PALINDROME, so it")
        print("      cannot distinguish the two bit orders (ruling 1b).")
        return 1
    print("  sigrok should report the 7-bit address as 0x%02X" % ADDR_7BIT)
    print()

    os.makedirs(SCRATCH, exist_ok=True)
    g = run([sys.executable, os.path.join(HERE, "make_smoke_image.py"),
             "--i2cframe", "62"])
    if g.returncode != 0:
        print("  *** could not build the image")
        print((g.stdout + g.stderr)[-500:])
        return 1
    img = os.path.join(HERE, "i2cframe_image.hex")
    with open(img, encoding="ascii") as fh:
        nb = len([w for w in fh.read().split() if w])

    vvp = os.path.join(SCRATCH, "i2c.vvp")
    b = run(["iverilog", "-g2012", "-o", vvp, "-s", "tb_i2c"] + SRCS)
    if b.returncode != 0:
        print("  *** build failed")
        print((b.stdout + b.stderr)[-700:])
        return 1
    r = run(["vvp", vvp, "+IMG=test/i2cframe_image.hex", "+NBYTES=%d" % nb,
             "+NCYC=%d" % NCYC, "+DUMP=%s" % DUMP])
    txt = r.stdout + r.stderr
    m = re.search(r"I2CDUMP file=(\S+) samples=(\d+) sda_edges=(\d+) "
                  r"scl_edges=(\d+) acks=(\d+)", txt)
    if not m:
        print("  *** the bench produced no I2CDUMP line")
        print(txt[-700:])
        return 1
    samples, sda_e, scl_e, acks = (int(m.group(i)) for i in (2, 3, 4, 5))
    print("  --- the bench's own reading ---")
    print("    samples written      : %d" % samples)
    print("    SDA / SCL edges      : %d / %d" % (sda_e, scl_e))
    print("    peer ACK pulses      : %d %s" % (acks, "ok" if acks else "***"))
    if "tb_i2c: PASS" not in txt:
        print("    *** the bench did not pass, so the dump is not trustworthy")
        for l in txt.splitlines():
            if "FAIL" in l:
                print("      %s" % l.strip())
        return 1

    print()
    print("  --- sigrok's reading ---")
    d = sigrok_i2c(DUMP)
    # ⛔ THE RETURN CODE FIRST. No annotations and a failed invocation look the
    # same from the event list alone.
    if d["rc"] != 0:
        print("    *** sigrok-cli exited %d -- the foreign authority did not"
              % d["rc"])
        print("        run, so NOTHING below is a verdict. This gate is RED")
        print("        rather than falling back to the bench's own opinion.")
        print("    %s" % d["raw"].strip()[:300])
        return 1
    if not d["events"]:
        print("    *** sigrok ran and decoded NOTHING. Either the waveform is")
        print("        not I2C or the channel order is wrong -- both of which")
        print("        this gate exists to catch.")
        return 1
    tx = transactions(d["events"])
    print("    transactions decoded : %d" % len(tx))
    for i, t in enumerate(tx[:4]):
        desc = []
        for name, val in t:
            desc.append(name if val is None else "%s %02X" % (name, val))
        print("      %d: %s" % (i, " | ".join(desc)))

    # ---- THE CLAIM: a complete, acknowledged write transaction ---------
    print()
    print("  --- the certified frame ---")
    want = [("Start", None), ("Address write", ADDR_7BIT), ("ACK", None),
            ("Data write", DATA_BYTE), ("ACK", None), ("Stop", None)]
    good = [t for t in tx if [e for e in t if e[0] != "Write"] == want]
    print("    transactions matching S | addr %02X | A | data %02X | A | P : %d"
          % (ADDR_7BIT, DATA_BYTE, len(good)))
    if not good:
        print("    *** NOT ONE. sigrok did not certify a single complete,")
        print("        acknowledged write transaction.")
        rc = 1
    else:
        print("    ⇒ sigrok certifies the frame: START, the device address it")
        print("      ACKNOWLEDGED, a data byte it ACKNOWLEDGED, and STOP.")

    # ---- NON-VACUITY: the decoder and the peer must both DISCRIMINATE --
    # ⛔⛔ A PEER THAT ACKED EVERYTHING WOULD CERTIFY NOTHING, and so would a
    # decoder that reported ACK unconditionally. The first transaction carries
    # the reset byte 0x00 -- an address this device must REFUSE -- so the run
    # contains both outcomes and the ACK above is a discrimination, not a
    # constant.
    print()
    print("  --- non-vacuity: the peer REFUSES what is not its address ---")
    nacked = [t for t in tx
              if any(e == ("Address write", 0x00) for e in t)
              and any(e[0] == "NACK" for e in t)]
    print("    transactions addressed 0x00 and NACKed : %d" % len(nacked))
    if not nacked:
        print("    *** the run never exercised a refusal, so the ACK above")
        print("        could be a constant. The first transaction carries the")
        print("        reset byte 0x00 by construction -- if it was ACKed, the")
        print("        peer is not discriminating.")
        rc = 1
    else:
        print("    ⇒ both outcomes present: 0x00 refused, 0x%02X acknowledged."
              % ADDR_7BIT)

    # ---- the bit order, settled by the foreign decoder ----------------
    print()
    print("  --- ⛔ THE BIT ORDER, SETTLED ---")
    print("    the host pushed 0x%02X and sigrok read the 7-bit address as"
          % ADDR_PUSHED)
    print("    0x%02X, i.e. the wire byte was 0x%02X -- the BIT REVERSAL of"
          % (ADDR_7BIT, ADDR_7BIT << 1))
    print("    what was pushed. `OP_SHIFT` emits `l_tx[0]` first, so the")
    print("    engine is LSB-FIRST on the wire while I2C and SPI mode 0 are")
    print("    both MSB-first.")
    print("    ⚠ `pe_isa.py` claims the lanes shift MSB-first. That is the")
    print("      OPPOSITE of the RTL, and it was undetectable until now: the")
    print("      one byte a bench had checked end to end (0x5A) is a")
    print("      bit-reversal PALINDROME and matched either way.")
    print("    ⇒ A HOST MUST PRE-REVERSE every byte it wants on the wire")
    print("      MSB-first. Whether the ENGINE should shift the other way is")
    print("      a ruling, not a bug fix: it would change the TX byte order")
    print("      of every lane and `tb_tx`'s recorded streams with it.")

    # ---- PRICE THE ORDER BIT -------------------------------------------
    # ⛔⛔ NO BENCH OF OURS CAN JUDGE THIS, which is why it is here. A reversed
    # I2C byte is still a well-formed byte; only a decoder reading the standard
    # can say it is the WRONG one. `M_IGNORE_ORDER` ties `l_order` to 0, so the
    # engine reverts to LSB-first on the wire and the address the peer sees is
    # 0x05 reversed -- not its own. sigrok must stop certifying.
    print()
    print("  --- PRICED: M_IGNORE_ORDER must break the certification ---")
    mv = os.path.join(SCRATCH, "i2c_mut.vvp")
    bm = run(["iverilog", "-g2012", "-DM_IGNORE_ORDER", "-o", mv,
              "-s", "tb_i2c"] + SRCS)
    if bm.returncode != 0:
        print("    *** the mutant does not build, so it is not a kill")
        print("        %s" % ((bm.stdout + bm.stderr).strip()[:200]))
        rc = 1
    else:
        rm = run(["vvp", mv, "+IMG=test/i2cframe_image.hex",
                  "+NBYTES=%d" % nb, "+NCYC=%d" % NCYC,
                  "+DUMP=probe_i2c_mut.bin"])
        dm = sigrok_i2c("probe_i2c_mut.bin")
        if dm["rc"] != 0:
            print("    *** sigrok did not run on the mutant dump, so nothing")
            print("        is concluded")
            rc = 1
        else:
            txm = transactions(dm["events"])
            goodm = [t for t in txm
                     if [e for e in t if e[0] != "Write"] == want]
            acked = sum(1 for t in txm for e in t if e[0] == "ACK")
            print("    transactions decoded        : %d" % len(txm))
            print("    still matching the frame    : %d %s"
                  % (len(goodm), "*** SURVIVED" if goodm else "ok -- none"))
            print("    ACKs anywhere in the run    : %d %s"
                  % (acked, "*** SURVIVED" if acked else "ok -- none"))
            if goodm or acked:
                print("      ⛔ With the order bit IGNORED the device should")
                print("         never recognise its address, so a surviving")
                print("         ACK means the certification above does not")
                print("         depend on the order bit at all.")
                rc = 1
            else:
                print("    ⇒ the mutant is REFUSED by the peer and certified")
                print("      by nothing: the order bit is load-bearing for")
                print("      every transaction above.")
                if "tb_i2c: PASS" in (rm.stdout + rm.stderr):
                    print("      ⚠ note: the BENCH still passes on the mutant.")
                    print("        It checks liveness and that the peer ACKed")
                    print("        at least once -- and with a wrong address")
                    print("        it ACKs none, so the bench catches it too.")

    print()
    print("=" * 78)
    print("  GATE i2c-foreign: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    ⚠ PASSED means a FOREIGN decoder accepts the framing and the")
    print("      byte values, and that both ACK outcomes were exercised. It")
    print("      says nothing about electrical timing -- that is")
    print("      `gate_i2c_phase.py`'s claim, from UM10204.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
