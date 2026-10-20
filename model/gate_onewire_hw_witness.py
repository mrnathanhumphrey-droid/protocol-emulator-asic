"""A RECORDED BENCH WITNESS, RE-CHECKED IN CI -- the 1-Wire lane on hardware.

⛔ WHAT THIS IS, AND IS NOT (Wilson 10-17, the I2C pattern). It is NOT a
hardware run in CI. The board ran on the bench (Puzhi PA100T-EDU, the OW = 1
build on J11, a DS18B20 probe with 4.7 kOhm to 3V3, breadboard), a DSLogic
U3Pro16 captured DQ (capture 182359), and `fpga/host/ow_witness_record.py`
wrote what the capture says -- sigrok's decoded 1-Wire events and the slot
timing -- into `fpga/witness/onewire_hw_witness.json`, with provenance (the
capture's name and SHA-256; the CSV stays out of git; the bitstream's SHA-256,
its build log's generics and its programming log line; the PC's run logs).
This gate re-checks that RECORD against the repository today, in seconds, with
no simulator:

  1. THE PROGRAM IS THE ONE THAT RAN: the SHA-256 of test/onewire_fpga_image.hex,
     fpga/feeds/onewire_fpga_feed.hex and .params equal the recorded ones, and
     the build log's generics equal the .params values. The tracked feed is
     the one `test/onewire.py` builds from `pe_proto.DS18B20_TXN`.
  2. WIRE == FEED, EXACTLY: the decoded events are DS18B20_TXN -- 3 resets,
     each with presence; every command byte exact (33; CC 44; CC BE); 8 ROM
     bytes, a Convert T poll (busy 00 first, done last), 9 scratchpad bytes
     -- and nothing else.
  3. THE PART'S ANSWERS: the ROM's CRC-8 holds and it is the probe's ROM
     (28 8A 7A A9 11 00 00 30, Wilson 10-17); the scratchpad's CRC-8 holds.
  4. WIRE == PC: the captured run passed on the PC, and its printed ROM, poll
     count, scratchpad and temperature are the wire's. Every other recorded
     run on this bitstream either passed with the probe's ROM or carries the
     note that explains it.
  5. SLOT ACCOUNTING: the per-class slot counts equal the decoded bits (W0 /
     W1 from the commands, R0 / R1 from the read bytes), and every DQ low is a
     reset, a presence or a slot.
  6. DS18B20 TIMING (datasheet 19-7487 Rev 6, the windows test/ds18b20_model.v
     quotes): tRSTL >= 480 us; tPDHIGH 15..60; tPDLOW 60..240; tRSTH >= 480;
     tLOW0 60..120; tLOW1 1..15; tREC >= 1; fall to fall >= 61; and against
     the build's 13 us master sample: every read-0 held past it, every read-1
     init low (with its rise) back above threshold before it.
MUST-FIRES: (i) one recorded byte flipped -> red; (ii) the feed / image /
params changed -> red; (iii) one timing pushed out of its window -> red.

⛔ SCOPE: the bitstream is the 2abcdab glue. The status trailer to the PC
(eafe67b) is not in this witness (the record says so in `scope`).
POSITIVE TOKEN: `GATE onewire-hw-witness: PASSED`.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "test"))

IMAGE = "onewire_fpga_image.hex"
EVIDENCE = os.path.join(ROOT, "fpga", "witness", "onewire_hw_witness.json")
FILES = {"image": os.path.join(ROOT, "test", IMAGE),
         "feed": os.path.join(ROOT, "fpga", "feeds", "onewire_fpga_feed.hex"),
         "params": os.path.join(ROOT, "fpga", "feeds", "onewire_fpga_feed.params")}
PROBE_ROM = [0x28, 0x8A, 0x7A, 0xA9, 0x11, 0x00, 0x00, 0x30]
#: master writes after each reset (DS18B20_TXN: 33 | CC 44 | CC BE)
WRITES_PER_RESET = (1, 2, 2)
SAMPLE_US = 13.0               # the build's master sample point (2 us init)
#: DS18B20 datasheet 19-7487 Rev 6 (us); None = no upper bound
WINDOWS = {"tRSTL_us": (480, None), "tPDHIGH_us": (15, 60),
           "tPDLOW_us": (60, 240), "tRSTH_us": (480, None),
           "tLOW0_us": (60, 120), "tLOW1_us": (1, 15), "tREC_us": (1, None),
           "fall_to_fall_us": (61, None)}


def sha_text(path):
    """SHA-256 with line endings normalised (a CRLF checkout is the same file)."""
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read().replace(b"\r\n", b"\n")).hexdigest()


def crc8(bs):
    """Dallas/Maxim CRC-8 (x^8 + x^5 + x^4 + 1, reflected)."""
    c = 0
    for b in bs:
        for _ in range(8):
            mix = (c ^ b) & 1
            c >>= 1
            if mix:
                c ^= 0x8C
            b >>= 1
    return c


def params(path):
    out = {}
    for ln in open(path, encoding="ascii"):
        if ln.strip():
            k, v = ln.split()
            out[k] = int(v)
    return out


def txn():
    import pe_proto as P
    return P.DS18B20_TXN


def walk(events, t):
    """Match the decoded events to the transaction. -> (fields, problem|None)."""
    got = {"rom": [], "polls": [], "sp": [], "writes": []}
    i = 0
    for step in t:
        if step[0] == "reset":
            if i >= len(events) or events[i] != ["reset", True]:
                return got, "event %d: expected reset with presence, got %s" % (
                    i, events[i] if i < len(events) else None)
            i += 1
            continue
        if step[0] == "write":
            if i >= len(events) or events[i] != ["byte", step[1]]:
                return got, "event %d: expected command %02X, got %s" % (
                    i, step[1], events[i] if i < len(events) else None)
            got["writes"].append(step[1])
            i += 1
            continue
        if step[0] == "read":
            n, tag = step[1], step[2]
            bs = events[i:i + n]
            if len(bs) != n or any(e[0] != "byte" for e in bs):
                return got, "event %d: expected %d %s bytes" % (i, n, tag)
            got[tag] = [e[1] for e in bs]
            i += n
            continue
        if step[0] == "poll":
            while True:
                if i >= len(events) or events[i][0] != "byte":
                    return got, "event %d: the poll never read done" % i
                got["polls"].append(events[i][1])
                i += 1
                if got["polls"][-1] != 0:
                    break
            continue
        return got, "unknown transaction step %r" % (step,)
    if i != len(events):
        return got, "%d decoded events after the transaction's end" % (len(events) - i)
    return got, None


def hexs(bs):
    return " ".join("%02X" % b for b in bs)


def audit(ev, files_sha=None, prm=None, feed_ok=None):
    """-> [problem] for evidence `ev` against the repository (pure, so the
    must-fires can price it)."""
    probs = []
    have = files_sha if files_sha is not None else \
        {k: sha_text(p) for k, p in FILES.items()}
    for k in sorted(FILES):
        if ev["program_sha256"].get(k) != have[k]:
            probs.append("the recorded %s is not the repository's (%s vs %s): "
                         "the bench ran a different program -- re-run and "
                         "re-record" % (k, ev["program_sha256"].get(k, "-")[:12],
                                        have[k][:12]))
    prm = prm if prm is not None else params(FILES["params"])
    gen = dict((k, int(v)) for k, v in
               re.findall(r"\b(NFEED|POLLIDX|PER2|MARGIN)=(\d+)", ev["build_log"]["line"]))
    if gen != prm:
        probs.append("the build's generics %s are not the tracked params %s" % (gen, prm))
    if feed_ok is False:
        probs.append("the tracked feed is not the one test/onewire.py builds "
                     "from DS18B20_TXN")

    got, why = walk(ev["capture"]["events"], txn())
    if why:
        probs.append("decoded wire != the feed's transaction: %s" % why)
    rom, sp, pol = got["rom"], got["sp"], got["polls"]
    if len(rom) == 8 and crc8(rom[:7]) != rom[7]:
        probs.append("ROM CRC-8 fails on the wire: %s" % hexs(rom))
    if rom != PROBE_ROM:
        probs.append("the wire's ROM %s is not the probe's %s" % (hexs(rom), hexs(PROBE_ROM)))
    if len(sp) == 9 and crc8(sp[:8]) != sp[8]:
        probs.append("scratchpad CRC-8 fails on the wire: %s" % hexs(sp))
    if len(pol) < 2 or pol[0] != 0:
        probs.append("the poll does not read busy (00) first: %s" % hexs(pol[:4]))

    caps = [r for r in ev["runs"] if r["captured"]]
    if len(caps) != 1:
        probs.append("%d runs marked captured; exactly one must be" % len(caps))
    for r in caps:
        if not r["pass"]:
            probs.append("the captured run %s did not pass on the PC" % r["log"])
        if (r["rom"] or "") != hexs(rom):
            probs.append("wire ROM %s != the PC's %s" % (hexs(rom), r["rom"]))
        if r["polls"] != len(pol):
            probs.append("wire polls %d != the PC's %s" % (len(pol), r["polls"]))
        if (r["scratchpad"] or "") != hexs(sp):
            probs.append("wire scratchpad %s != the PC's %s" % (hexs(sp), r["scratchpad"]))
        if len(sp) == 9:
            raw = sp[0] | sp[1] << 8
            raw = raw - 0x10000 if raw & 0x8000 else raw
            if r["temperature_c"] != raw / 16.0:
                probs.append("wire temperature %.4f C != the PC's %s"
                             % (raw / 16.0, r["temperature_c"]))
    for r in ev["runs"]:
        if r["captured"]:
            continue
        if r["pass"] and r["rom"] != hexs(PROBE_ROM):
            probs.append("run %s passed on another ROM %s" % (r["log"], r["rom"]))
        if not r["pass"] and not r.get("note"):
            probs.append("run %s failed and the record does not say why" % r["log"])

    t = ev["timing"]
    bits = lambda bs, v: sum(((b >> k) & 1) == v for b in bs for k in range(8))
    reads = rom + pol + sp
    want = {"W0": bits(got["writes"], 0), "W1": bits(got["writes"], 1),
            "R0": bits(reads, 0), "R1": bits(reads, 1)}
    if t["slots"] != want:
        probs.append("slot counts %s != the decoded bits %s" % (t["slots"], want))
    la = t["lows_accounted"]
    if la["total"] != la["resets"] + la["presence"] + la["slots"] or \
            la["slots"] != sum(want.values()):
        probs.append("DQ lows not all accounted for: %s" % la)
    for k, (lo, hi) in sorted(WINDOWS.items()):
        if t[k]["min"] < lo or (hi is not None and t[k]["max"] > hi):
            probs.append("%s %.1f..%.1f us outside [%s, %s]" % (
                k[:-3], t[k]["min"], t[k]["max"], lo, "inf" if hi is None else hi))
    if t["read0_held_us"]["min"] <= SAMPLE_US:
        probs.append("a read-0 released at %.1f us, before the %.0f us sample"
                     % (t["read0_held_us"]["min"], SAMPLE_US))
    if t["read_init_low_us"]["max"] >= SAMPLE_US:
        probs.append("a read-1 still low at %.1f us, past the %.0f us sample"
                     % (t["read_init_low_us"]["max"], SAMPLE_US))
    return probs


def feed_matches():
    import onewire
    lines, _rx, _p = onewire.feed("fpga")
    trk = open(FILES["feed"], encoding="ascii").read().replace("\r\n", "\n")
    return trk == "\n".join(lines) + "\n"


def main() -> int:
    print("=" * 78)
    print("1-WIRE HW WITNESS -- a recorded bench witness of %s, re-checked in CI" % IMAGE)
    print("  (NOT a hardware run in CI: the record is the bench's, checked here)")
    print("=" * 78)
    with open(EVIDENCE, encoding="utf-8") as fh:
        ev = json.load(fh)
    c, t = ev["capture"], ev["timing"]
    print("  bench: %s" % ev["bench"])
    print("  scope: %s" % ev["scope"])
    print("  bitstream sha256 %s" % ev["bitstream_sha256"])
    print("  %s" % ev["build_log"]["line"][:110])
    print("  %s" % ev["program_log"]["line"][:110])
    print("  capture %s (sha256 %s...): %d events at %d Hz"
          % (c["file"], c["csv_sha256"][:16], len(c["events"]), c["rate_hz"]))
    for r in ev["runs"]:
        print("  run %-18s %s%s%s" % (
            r["log"], "PASS" if r["pass"] else "FAIL",
            "  %.4f C" % r["temperature_c"] if r["temperature_c"] is not None else "",
            "   <- CAPTURED" if r["captured"] else
            ("   (%s)" % r["note"] if r.get("note") else "")))
    print("  slots %s; lows %s" % (t["slots"], t["lows_accounted"]))
    for k in ("tRSTL_us", "tPDHIGH_us", "tPDLOW_us", "tRSTH_us", "tLOW0_us",
              "tLOW1_us", "read_init_low_us", "read0_held_us", "tREC_us",
              "fall_to_fall_us"):
        print("    %-18s %7.1f .. %7.1f us  (n=%d)" % (k[:-3], t[k]["min"],
                                                     t[k]["max"], t[k]["n"]))
    print("    read-1 rise (upper) %.1f us vs the %.0f us sample"
          % (t["read1_rise_upper_us"], SAMPLE_US))
    fm = feed_matches()
    probs = audit(ev, feed_ok=fm)
    for p in probs:
        print("  *** %s" % p)
    if not probs:
        print("  the record matches the repository's program, feed and build "
              "generics; wire == feed exactly; wire == the PC's run; every "
              "DS18B20 window met")

    print("  --- must-fire ---")
    rc = 1 if probs else 0
    have = {k: sha_text(p) for k, p in FILES.items()}
    mf = []
    e1 = copy.deepcopy(ev)
    k = next(i for i, x in enumerate(e1["capture"]["events"])
             if x[0] == "byte" and i > 1 and x[1] not in (0x33, 0xCC, 0x44, 0xBE))
    e1["capture"]["events"][k][1] ^= 0x01
    mf.append(("(i) one recorded ROM byte flipped", audit(e1), "the probe's"))
    e1b = copy.deepcopy(ev)
    sp0 = len(e1b["capture"]["events"]) - 9
    e1b["capture"]["events"][sp0][1] ^= 0x10
    mf.append(("(i) one scratchpad byte flipped", audit(e1b), "scratchpad CRC-8"))
    for key in ("feed", "image", "params"):
        mf.append(("(ii) the %s changed" % key,
                   audit(ev, dict(have, **{key: "0" * 64})),
                   "the recorded %s is not" % key))
    mf.append(("(ii) a generic != the params",
               audit(ev, prm=dict(params(FILES["params"]), POLLIDX=16)),
               "generics"))
    mf.append(("(ii) feed not DS18B20_TXN's", audit(ev, feed_ok=False),
               "the tracked feed is not"))
    for key, val, needle in (("tLOW0_us", ("max", 120.1), "tLOW0"),
                             ("tPDHIGH_us", ("max", 60.1), "tPDHIGH"),
                             ("tREC_us", ("min", 0.9), "tREC"),
                             ("read0_held_us", ("min", SAMPLE_US), "read-0")):
        e = copy.deepcopy(ev)
        e["timing"][key][val[0]] = val[1]
        mf.append(("(iii) %s pushed out of window" % key[:-3], audit(e), needle))
    for label, ps, needle in mf:
        hit = any(needle in p for p in ps)
        print("    %-38s %s" % (label, "red  ok" if hit else "*** NOT RED"))
        rc |= 0 if hit else 1
    print()
    print("  GATE onewire-hw-witness: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
