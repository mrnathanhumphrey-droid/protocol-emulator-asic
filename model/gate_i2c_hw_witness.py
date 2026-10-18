"""A RECORDED BENCH WITNESS, RE-CHECKED IN CI -- the I2C FRAM lane on hardware.

⛔ WHAT THIS IS, AND IS NOT (Wilson 10-17). It is NOT a hardware run in CI.
The board ran on the bench (Puzhi PA100T-EDU, the I2C build, an Adafruit
#1895 MB85RC256V, ~3.2 kOhm pull-ups on a breadboard), a DSLogic U3Pro16
captured the wire, and `fpga/host/i2c_witness_record.py` wrote what the
captures say -- sigrok's decoded events and the Fast-mode timings -- into
`fpga/witness/i2c_fram_hw_witness.json`, with provenance (capture names and
SHA-256s; the CSVs stay out of git; the bitstream SHA-256; the PC's run-log
lines). This gate re-checks that RECORD against what the repository says
today, in seconds, with no simulator:

  1. THE PROGRAM IS THE ONE THAT RAN: the SHA-256 of fpga/images/
     i2c_fram_fpga.hex, fpga/feeds/i2c_fram_feed.hex and
     i2c_fram_falls.hex equal the recorded ones. Change the image or the
     feed and this is red until the bench is re-run and re-recorded.
  2. WIRE == FEED, EXACTLY, per captured run: the decoded events equal the
     transaction the feed commands (`expected_events`, built from
     fpga/sim/i2c_fram.py: device address, memory address, master ACK / NACK)
     with that run's data, and the FRAM's bytes equal the run's old / new.
  3. PERSISTENCE: each logged run's old bytes are the previous run's data;
     the record names which run spans a POWER-OFF (the retention check).
  4. FAST-MODE TIMING (UM10204 Fm): fSCL max <= 400 kHz; tLOW min >= 1.3 us
     (measured at the 30 % capture); tHIGH min >= 0.6 us (at 70 %); rise
     (30 -> 70 %) <= 300 ns on SCL and on SDA.
MUST-FIRES: (i) one recorded byte flipped -> red; (ii) the feed / image
changed -> red; (iii) one timing pushed past its Fm limit -> red.

The measured rate is recorded as measured (370.4 kHz typical, PA100T,
breadboard) -- the 397 kHz figure is the simulation's, with ideal edges.
POSITIVE TOKEN: `GATE i2c-hw-witness: PASSED`.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "fpga", "sim"))

IMAGE = "i2c_fram_fpga.hex"
EVIDENCE = os.path.join(ROOT, "fpga", "witness", "i2c_fram_hw_witness.json")
FILES = {"image": os.path.join(ROOT, "fpga", "images", IMAGE),
         "feed": os.path.join(ROOT, "fpga", "feeds", "i2c_fram_feed.hex"),
         "falls": os.path.join(ROOT, "fpga", "feeds", "i2c_fram_falls.hex")}
#: UM10204 Fast-mode limits
FM = {"fscl_max_khz": 400.0, "tlow_min_us": 1.3, "thigh_min_us": 0.6,
      "rise_max_ns": 300.0}


def sha_text(path):
    """SHA-256 of a text file with line endings normalised (a CRLF checkout
    is the same file)."""
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read().replace(b"\r\n", b"\n")).hexdigest()


def expected_events(data_hex, old_hex):
    """The transaction the feed commands, as sigrok `i2c` events, for one run:
    T1 random read of the old bytes, T2 write of the data, T3 random read."""
    import i2c_fram as IF
    d = list(bytes.fromhex(data_hex))
    o = list(bytes.fromhex(old_hex))
    a7, hi, lo = IF.DEV_W >> 1, IF.ADDR >> 8, IF.ADDR & 0xFF

    def rd(vals):
        e = [["Start", None], ["Address write", a7], ["ACK", None],
             ["Data write", hi], ["ACK", None], ["Data write", lo], ["ACK", None],
             ["Start repeat", None], ["Address read", a7], ["ACK", None]]
        for i, v in enumerate(vals):
            e += [["Data read", v], ["NACK" if i == len(vals) - 1 else "ACK", None]]
        return e + [["Stop", None]]
    wr = [["Start", None], ["Address write", a7], ["ACK", None],
          ["Data write", hi], ["ACK", None], ["Data write", lo], ["ACK", None]]
    for v in d:
        wr += [["Data write", v], ["ACK", None]]
    return rd(o) + wr + [["Stop", None]] + rd(d)


def audit(ev, files_sha=None):
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
    caps = ev["captures"]
    if len(caps) < 1:
        probs.append("no capture recorded")
    for c in caps:
        want = expected_events(c["data"], c["old"])
        if c["events"] != want:
            k = next((i for i, (a, b) in enumerate(zip(c["events"], want))
                      if a != b), min(len(c["events"]), len(want)))
            probs.append("capture %s: decoded wire != the feed's transaction "
                         "at event %d (%s vs %s)" % (
                             c["file"], k,
                             c["events"][k] if k < len(c["events"]) else None,
                             want[k] if k < len(want) else None))
    runs = ev["runs"]
    for prev, cur in zip(runs, runs[1:]):
        if cur["old_read"].replace(" ", "") != prev["data"]:
            probs.append("run at %s read old %s, the previous run wrote %s"
                         % (cur["time"], cur["old_read"], prev["data"]))
    if not any(r.get("after_power_off") for r in runs[1:]):
        probs.append("no logged run spans a power-off: retention unwitnessed")
    for r in runs:
        if not r.get("pass"):
            probs.append("run at %s did not pass on the PC" % r["time"])
    t = ev["timing"]
    if t["fscl_khz"]["max"] > FM["fscl_max_khz"]:
        probs.append("fSCL max %.1f kHz > %.0f" % (t["fscl_khz"]["max"], FM["fscl_max_khz"]))
    if t["tlow_us"]["min"] < FM["tlow_min_us"]:
        probs.append("tLOW min %.3f us < %.1f" % (t["tlow_us"]["min"], FM["tlow_min_us"]))
    if t["thigh_us"]["min"] < FM["thigh_min_us"]:
        probs.append("tHIGH min %.3f us < %.1f" % (t["thigh_us"]["min"], FM["thigh_min_us"]))
    for line in ("scl", "sda"):
        if t["rise_ns"][line]["max"] > FM["rise_max_ns"]:
            probs.append("%s rise max %d ns > %d" % (
                line.upper(), t["rise_ns"][line]["max"], FM["rise_max_ns"]))
    return probs


def main() -> int:
    print("=" * 78)
    print("I2C HW WITNESS -- a recorded bench witness of %s, re-checked in CI" % IMAGE)
    print("  (NOT a hardware run in CI: the record is the bench's, checked here)")
    print("=" * 78)
    with open(EVIDENCE, encoding="utf-8") as fh:
        ev = json.load(fh)
    t = ev["timing"]
    print("  bench: %s" % ev["bench"])
    print("  bitstream sha256 %s" % ev["bitstream_sha256"])
    for c in ev["captures"]:
        print("  capture %s (threshold %s, sha256 %s...): %d events, data %s old %s"
              % (c["file"], c["threshold"], c["csv_sha256"][:16], len(c["events"]),
                 c["data"], c["old"]))
    for r in ev["runs"]:
        print("  run %s: old %s -> data %s%s" % (
            r["time"], r["old_read"], r["data"],
            "   <- after a POWER-OFF (retention)" if r.get("after_power_off") else ""))
    print("  fSCL MEASURED: typical %.1f kHz, range %.1f-%.1f kHz (nominal 397 kHz "
          "is the simulation's, ideal edges)"
          % (t["fscl_khz"]["typical"], t["fscl_khz"]["min"], t["fscl_khz"]["max"]))
    print("  tLOW min %.3f us, tHIGH min %.3f us, rise max SCL %d / SDA %d ns"
          % (t["tlow_us"]["min"], t["thigh_us"]["min"], t["rise_ns"]["scl"]["max"],
             t["rise_ns"]["sda"]["max"]))
    probs = audit(ev)
    for p in probs:
        print("  *** %s" % p)
    if not probs:
        print("  the record matches the repository's program and feed, wire == "
              "feed exactly, persistence chained, every Fm timing in spec")

    print("  --- must-fire ---")
    rc = 1 if probs else 0
    mf = []
    e1 = copy.deepcopy(ev)
    k = next(i for i, x in enumerate(e1["captures"][0]["events"]) if x[1] is not None)
    e1["captures"][0]["events"][k][1] ^= 0x01
    mf.append(("(i) one recorded byte flipped", audit(e1), "decoded wire != the feed"))
    have = {k2: sha_text(p) for k2, p in FILES.items()}
    have2 = dict(have, feed="0" * 64)
    mf.append(("(ii) the feed changed", audit(ev, have2), "the recorded feed is not"))
    have3 = dict(have, image="0" * 64)
    mf.append(("(ii) the image changed", audit(ev, have3), "the recorded image is not"))
    e4 = copy.deepcopy(ev)
    e4["timing"]["tlow_us"]["min"] = FM["tlow_min_us"] - 0.01
    mf.append(("(iii) tLOW pushed below 1.3 us", audit(e4), "tLOW min"))
    e5 = copy.deepcopy(ev)
    e5["timing"]["rise_ns"]["sda"]["max"] = FM["rise_max_ns"] + 1
    mf.append(("(iii) SDA rise pushed past 300 ns", audit(e5), "SDA rise max"))
    e6 = copy.deepcopy(ev)
    e6["timing"]["fscl_khz"]["max"] = FM["fscl_max_khz"] + 0.1
    mf.append(("(iii) fSCL pushed past 400 kHz", audit(e6), "fSCL max"))
    for label, ps, needle in mf:
        hit = any(needle in p for p in ps)
        print("    %-38s %s" % (label, "red  ok" if hit else "*** NOT RED"))
        rc |= 0 if hit else 1
    print()
    print("  GATE i2c-hw-witness: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
