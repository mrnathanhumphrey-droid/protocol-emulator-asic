"""Write the 1-Wire (DS18B20) bench witness RECORD from the raw DSLogic capture.

Run by hand on the bench PC (the CSV is ~860 MB and stays OUT of git); writes
fpga/witness/onewire_hw_witness.json, which model/gate_onewire_hw_witness.py
re-checks in CI. The capture (Wilson lock order 10-17): DSLogic U3Pro16,
10 MHz, CH0 = DQ, of one PC run of the OW = 1 build on J11.
  decode  sigrok's `onewire_link` + `onewire_network` (foreign, sigrok-cli in
          WSL) -> resets / presence and the byte stream, recorded as decoded;
          a `ROM:` value (64-bit, sent LSB first) is recorded as its 8 bytes
  slots   every DQ low, classified against the decoded bytes in wire order
          (LSB first; the first 1 / 2 / 2 bytes after each reset are the
          master's commands, the rest are reads): W0 / W1 / R0 / R1. A slot
          whose low width disagrees with its decoded bit is a refusal
  timing  per class, low width min / max; tREC = the high before each slot's
          fall; fall to fall; reset low, presence wait (release -> fall) and
          pulse; tRSTH = reset release -> the first slot's fall. The capture
          file does not record the threshold voltage, so none is claimed.
  read-1  the line's return above threshold after the master's 2.000 us init
          low (100 cycles at 50 MHz, the build's) = low width - 2.000 us, an
          UPPER estimate at 0.1 us steps; the master samples at 13 us.
PC runs: each `fpga/host/ow_run.py` log is recorded verbatim with its parse;
the capture is paired to ONE run by content (its decoded bytes == that run's
printed ROM, poll count and scratchpad), never by time alone.

Usage: python fpga/host/ow_witness_record.py <capture.csv> <bitstream> \
           <vivado.log> <program.log> <captured-run.log> \
           [<other-run.log>[::<note>] ...]
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "model"))
import gate_onewire_hw_witness as G                      # noqa: E402

NS = 100                       # 10 MHz
INIT_US = 2.0                  # the build's master init low (100 cycles)


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def load(path):
    rate, out = None, bytearray()
    with open(path, encoding="ascii", errors="replace") as fh:
        for line in fh:
            if line.startswith(";"):
                m = re.search(r"Sample rate: (\d+) MHz", line)
                if m:
                    rate = int(m.group(1)) * 1000000
                continue
            if line.startswith("T"):
                continue
            out.append(1 if line.split(",", 2)[1].strip() == "1" else 0)
    if rate != 10000000:
        raise SystemExit("%s: expected 10 MHz, header says %s" % (path, rate))
    return bytes(out)


def wsl(p):
    p = os.path.abspath(p).replace("\\", "/")
    return "/mnt/%s%s" % (p[0].lower(), p[2:])


def sigrok(samples, scratch):
    binp = os.path.join(scratch, "probe_ow_witness.bin")
    with open(binp, "wb") as fh:
        fh.write(samples)
    sh = os.path.join(scratch, "probe_ow_witness.sh")
    with open(sh, "w", encoding="ascii", newline="\n") as fh:
        fh.write("#!/bin/bash\nsigrok-cli -i %s -I binary:numchannels=1:samplerate="
                 "10000000 -P onewire_link:owr=0,onewire_network -A onewire_network\n"
                 % wsl(binp))
    r = subprocess.run(["wsl.exe", "-e", "bash", wsl(sh)], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:                        # a failed decode is no decode
        raise SystemExit("sigrok failed: %s" % (r.stdout + r.stderr)[-400:])
    ev = []
    for line in r.stdout.replace("\r", "").splitlines():
        if not line.startswith("onewire_network-1:"):
            continue
        tok = line.split(":", 1)[1].strip()
        if tok.startswith("Reset/presence:"):
            ev.append(["reset", tok.endswith("true")])
        elif tok.startswith("ROM command:") or tok.startswith("Data:"):
            ev.append(["byte", int(re.search(r"0x([0-9a-f]+)", tok).group(1), 16)])
        elif tok.startswith("ROM:"):
            rom = int(tok.split("0x", 1)[1], 16)
            ev += [["byte", (rom >> (8 * k)) & 0xFF] for k in range(8)]
        else:
            raise SystemExit("sigrok: an event this record does not know: %r" % tok)
    return ev


def lows(s):
    """[(fall index, rise index)] for every low on DQ."""
    out, fall = [], None
    for i in range(1, len(s)):
        if s[i - 1] == 1 and s[i] == 0:
            fall = i
        elif s[i - 1] == 0 and s[i] == 1 and fall is not None:
            out.append((fall, i))
            fall = None
    return out


def us(n):
    return round(n * NS / 1000.0, 1)


def span(xs):
    return {"min": us(min(xs)), "max": us(max(xs)), "n": len(xs)}


def timing(s, ev):
    """The wire's timing table, every DQ low classified against `ev`."""
    lo = lows(s)
    k, resets, slots = 0, [], []   # slots: (class, fall, rise)
    bi = 0                         # byte index since the last reset
    for e in ev:                   # ONE pass, in wire order
        if e[0] == "reset":
            # reset low, then the device's presence low
            resets.append({"rstl": lo[k], "pres": lo[k + 1], "first_slot": None})
            k += 2
            bi = 0
            continue
        nwr = G.WRITES_PER_RESET[len(resets) - 1]
        for bit in range(8):
            f, r = lo[k]
            v = (e[1] >> bit) & 1
            cls = ("W" if bi < nwr else "R") + str(v)
            long_ = (r - f) * NS > 15000
            if long_ != (v == 0):
                raise SystemExit("low %d (%s): %.1f us disagrees with its "
                                 "decoded bit" % (k, cls, us(r - f)))
            if resets[-1]["first_slot"] is None:
                resets[-1]["first_slot"] = f
            slots.append((cls, f, r))
            k += 1
        bi += 1
    if k != len(lo):
        raise SystemExit("%d DQ lows, %d accounted for" % (len(lo), k))
    by = {c: [r - f for cc, f, r in slots if cc == c] for c in ("W0", "W1", "R0", "R1")}
    falls = [f for _c, f, _r in slots]
    rises = [r for _c, _f, r in slots]
    rec = [falls[i + 1] - rises[i] for i in range(len(slots) - 1)
           if falls[i + 1] - falls[i] < 2000]          # inside a reset segment
    f2f = [falls[i + 1] - falls[i] for i in range(len(slots) - 1)
           if falls[i + 1] - falls[i] < 2000]
    return {
        "lows_accounted": {"total": len(lo), "resets": len(resets),
                           "presence": len(resets), "slots": len(slots)},
        "slots": {c: len(v) for c, v in by.items()},
        "tRSTL_us": span([x["rstl"][1] - x["rstl"][0] for x in resets]),
        "tPDHIGH_us": span([x["pres"][0] - x["rstl"][1] for x in resets]),
        "tPDLOW_us": span([x["pres"][1] - x["pres"][0] for x in resets]),
        "tRSTH_us": span([x["first_slot"] - x["rstl"][1] for x in resets]),
        "tLOW0_us": span(by["W0"]),
        "tLOW1_us": span(by["W1"]),
        "read_init_low_us": span(by["R1"]),
        "read0_held_us": span(by["R0"]),
        "tREC_us": span(rec),
        "fall_to_fall_us": span(f2f),
        "read1_rise_upper_us": round(max(by["R1"]) * NS / 1000.0 - INIT_US, 1),
    }


def parse_run(path, captured):
    txt = open(path, encoding="utf-8-sig").read().replace("\r\n", "\n")
    g = lambda rx: (re.search(rx, txt, re.M) or [None, None])[1]
    run = {"log": os.path.basename(path),
           "pass": "FPGA-ONEWIRE-HW: PASSED" in txt,
           "received": int(g(r"^received (\d+) byte")),
           "rom": g(r"ROM == the probe's ROM\s+\S+\s+([0-9A-F ]+?)\s*$"),
           "polls": g(r"Convert T polled.*?\s(\d+) poll byte"),
           "scratchpad": g(r"scratchpad CRC-8 valid\s+ok\s+([0-9A-F ]+?)\s*$"),
           "temperature_c": g(r"TEMPERATURE: ([\d.+-]+) C"),
           "captured": captured,
           "lines": txt.strip().splitlines()}
    run["polls"] = int(run["polls"]) if run["polls"] else None
    run["temperature_c"] = float(run["temperature_c"]) if run["temperature_c"] else None
    return run


def main():
    cap, bit, viv, prog, run_cap = sys.argv[1:6]
    others = sys.argv[6:]
    build_line = next(l for l in open(viv, encoding="utf-8", errors="replace")
                      if l.startswith("PE_FPGA: 1-Wire build, generics"))
    s = load(cap)
    with tempfile.TemporaryDirectory() as scratch:
        ev = sigrok(s, scratch)
    t = timing(s, ev)
    prog_line = next(l for l in open(prog, encoding="utf-8", errors="replace")
                     if l.startswith("PE_PROGRAM: bitstream"))
    runs = [parse_run(run_cap, True)]
    for arg in others:                 # `<log>` or `<log>::<why it is as it is>`
        path, _sep, note = arg.partition("::")
        runs.append(parse_run(path, False))
        if note:
            runs[-1]["note"] = note
    rec = {
        "what": "a RECORDED BENCH WITNESS of %s, re-checked in CI by "
                "model/gate_onewire_hw_witness.py -- not a hardware run in CI"
                % G.IMAGE,
        "bench": "Puzhi PA100T-EDU (XC7A100T), OW = 1 build on J11 (DQ A20, open "
                 "drain); DS18B20 waterproof probe, VDD-powered, 4.7 kOhm DQ to "
                 "3V3; breadboard; DSLogic U3Pro16 at 10 MHz, CH0 = DQ",
        "scope": "The bitstream is the 2abcdab glue. The STATUS TRAILER to the "
                 "PC (eafe67b, later) is NOT in this witness and has not run on "
                 "1-Wire hardware; the runs' PC logs are pre-trailer. The wire "
                 "carries the chip's program and the tracked feed, both "
                 "unchanged since (program_sha256).",
        "bitstream": os.path.basename(bit),
        "bitstream_sha256": sha_file(bit),
        "build_log": {"file": os.path.basename(viv), "line": build_line.strip()},
        "program_log": {"file": os.path.basename(prog), "line": prog_line.strip()},
        "program_sha256": {k: G.sha_text(p) for k, p in G.FILES.items()},
        "capture": {"file": os.path.basename(cap), "csv_sha256": sha_file(cap),
                    "rate_hz": 10000000, "samples": len(s),
                    "threshold": "not recorded in the capture file",
                    "events": ev},
        "runs": runs,
        "timing": t,
        "methods": __doc__.split("Usage:")[0].strip(),
    }
    out = G.EVIDENCE
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(rec, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print("wrote %s: %d events, %d runs; slots %s"
          % (os.path.relpath(out, ROOT), len(ev), len(runs), t["slots"]))


if __name__ == "__main__":
    main()
