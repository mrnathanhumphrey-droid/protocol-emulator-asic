"""Write the I2C FRAM bench witness RECORD from the raw DSLogic captures.

Run by hand on the bench PC (the CSVs are hundreds of MB and stay OUT of git);
writes fpga/witness/i2c_fram_hw_witness.json, which model/gate_i2c_hw_witness.py
re-checks in CI. Two captures of two runs (Wilson 10-17):
  run A  threshold 1.0 V (~30 % of 3.3 V) -- tLOW is measured here
  run B  threshold 2.3 V (~70 %)          -- tHIGH is measured here
CH0 = SCL, CH1 = SDA, 100 MHz. Per capture: sigrok's `i2c` decoder (foreign,
sigrok-cli in WSL) -> the event list, recorded as decoded. Timing:
  fSCL   rise to rise inside bytes (intervals <= 1.5 x the median)
  tLOW   SCL fall -> rise at 30 %;  tHIGH  rise -> fall at 70 %
  rise   per SCL pulse k: (rise - preceding fall) at 70 % minus at 30 % --
         valid because the chip's release follows its own fall by a fixed
         count (deterministic build) and falls are fast; an UPPER ESTIMATE
         (the pulse-to-pulse spread exceeds the 10 ns sample step). SDA: the
         same over bits identical in both runs (the address phases).

Usage: python fpga/host/i2c_witness_record.py <capA.csv> <capB.csv> \
           <runs.log> <bitstream> <power-off-before-run-time>
"""
import bisect
import hashlib
import json
import os
import re
import statistics as st
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "fpga", "sim"))
sys.path.insert(0, os.path.join(ROOT, "model"))
import i2c_fram as IF                                    # noqa: E402
import gate_i2c_hw_witness as G                          # noqa: E402

NS = 10


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
            p = line.split(",")
            out.append((p[1].strip() == "1") | ((p[2].strip() == "1") << 1))
    if rate != 100000000:
        raise SystemExit("%s: expected 100 MHz, header says %s" % (path, rate))
    return bytes(out)


def wsl(p):
    p = os.path.abspath(p).replace("\\", "/")
    return "/mnt/%s%s" % (p[0].lower(), p[2:])


def sigrok(samples, tag, scratch):
    binp = os.path.join(scratch, "probe_witness_%s.bin" % tag)
    with open(binp, "wb") as fh:
        fh.write(samples)
    sh = os.path.join(scratch, "probe_witness_%s.sh" % tag)
    with open(sh, "w", encoding="ascii", newline="\n") as fh:
        fh.write("#!/bin/bash\nsigrok-cli -i %s -I binary:numchannels=2:samplerate="
                 "100000000 -P i2c:scl=0:sda=1 -A i2c\n" % wsl(binp))
    r = subprocess.run(["wsl.exe", "-e", "bash", wsl(sh)], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:                        # a failed decode is no decode
        raise SystemExit("sigrok failed: %s" % (r.stdout + r.stderr)[-400:])
    ev = []
    for line in r.stdout.replace("\r", "").splitlines():
        if not line.startswith("i2c-1:"):
            continue
        tok = line.split(":", 1)[1].strip()
        m = re.match(r"(Address write|Address read|Data write|Data read): (\w\w)", tok)
        if m:
            ev.append([m.group(1), int(m.group(2), 16)])
        elif tok in ("Start", "Stop", "ACK", "NACK", "Start repeat"):
            ev.append([tok, None])
    return ev


def edges(s, bit):
    e, prev = [], (s[0] >> bit) & 1
    for i in range(1, len(s)):
        v = (s[i] >> bit) & 1
        if v != prev:
            e.append((i, v))
            prev = v
    return e


def pulses(e):
    return [(e[i][0], e[i + 1][0], e[i + 2][0]) for i in range(len(e) - 2)
            if e[i][1] == 0 and e[i + 1][1] == 1 and e[i + 2][1] == 0]


def sda_rises(scl, sda, keep):
    falls = [i for i, v in scl if v == 0]
    out = {}
    for i, v in sda:
        if v == 1:
            k = bisect.bisect_right(falls, i) - 1
            if k >= 0 and keep(k + 1):
                out[k] = i - falls[k]
    return out


def main():
    cap_a, cap_b, log, bit, poweroff = sys.argv[1:6]
    runs = [json.loads(l) for l in open(log, encoding="utf-8") if l.strip()]
    scratch = os.path.dirname(os.path.abspath(cap_a))
    # the two captured runs are the log's runs whose time the capture brackets;
    # by construction here: capture A = the first logged run, B = the second
    caps, S = [], {}
    for path, thr, run in ((cap_a, "1.0 V", runs[0]), (cap_b, "2.3 V", runs[1])):
        s = load(path)
        ev = sigrok(s, thr[0], scratch)
        caps.append({"file": os.path.basename(path), "threshold": thr,
                     "csv_sha256": sha_file(path), "run_time": run["time"],
                     "data": run["data"], "old": run["old_read"].replace(" ", ""),
                     "events": ev})
        S[thr] = (edges(s, 0), edges(s, 1))
    pa, pb = pulses(S["1.0 V"][0]), pulses(S["2.3 V"][0])
    per = [b[1] - a[1] for a, b in zip(pa, pa[1:])]
    med = st.median(per)
    inb = [x for x in per if x <= 1.5 * med]
    tlow = [r - f for f, r, _n in pa]
    thigh = [n - r for _f, r, n in pb]
    thigh = [x for x in thigh if x <= 1.5 * st.median(thigh)]
    if len(pa) != len(pb):
        raise SystemExit("SCL pulse counts differ (%d vs %d)" % (len(pa), len(pb)))
    rs = [(b[1] - b[0]) - (a[1] - a[0]) for a, b in zip(pa, pb)]
    model, _total = IF.falls()
    keep = lambda f: f <= model[3] + 9 or model[8] <= f <= model[11]
    r1 = sda_rises(S["1.0 V"][0], S["1.0 V"][1], keep)
    r2 = sda_rises(S["2.3 V"][0], S["2.3 V"][1], keep)
    rr = [r2[k] - r1[k] for k in sorted(set(r1) & set(r2))]
    khz = lambda n: round(1e6 / (n * NS), 1)
    timing = {
        "fscl_khz": {"typical": khz(med), "min": khz(max(inb)), "max": khz(min(inb))},
        "tlow_us": {"min": round(min(tlow) * NS / 1000.0, 3),
                    "typical": round(st.median(tlow) * NS / 1000.0, 3)},
        "thigh_us": {"min": round(min(thigh) * NS / 1000.0, 3),
                     "typical": round(st.median(thigh) * NS / 1000.0, 3)},
        "rise_ns": {"scl": {"max": max(rs) * NS, "typical": int(st.median(rs) * NS),
                            "min": min(rs) * NS, "n": len(rs)},
                    "sda": {"max": max(rr) * NS, "typical": int(st.median(rr) * NS),
                            "n": len(rr)}}}
    for r in runs:
        r["after_power_off"] = r["time"] == poweroff
    ev = {
        "what": "a RECORDED BENCH WITNESS of %s, re-checked in CI by "
                "model/gate_i2c_hw_witness.py -- not a hardware run in CI" % G.IMAGE,
        "bench": "Puzhi PA100T-EDU (XC7A100T), I2C build on J11 (SCL B20, SDA A20, "
                 "open drain); Adafruit #1895 MB85RC256V at 0x50; 4.7 kOhm to 3V3 "
                 "on each line in parallel with the breakout's (~3.2 kOhm); "
                 "breadboard; DSLogic U3Pro16 at 100 MHz, CH0 SCL, CH1 SDA",
        "bitstream": os.path.basename(bit),
        "bitstream_sha256": sha_file(bit),
        "program_sha256": {k: G.sha_text(p) for k, p in G.FILES.items()},
        "captures": caps,
        "runs": runs,
        "timing": timing,
        "methods": __doc__.split("Usage:")[0].strip(),
    }
    out = G.EVIDENCE
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(ev, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print("wrote %s: %d captures, %d runs; fSCL typical %.1f kHz (%.1f-%.1f)"
          % (os.path.relpath(out, ROOT), len(caps), len(runs),
             timing["fscl_khz"]["typical"], timing["fscl_khz"]["min"],
             timing["fscl_khz"]["max"]))


if __name__ == "__main__":
    main()
