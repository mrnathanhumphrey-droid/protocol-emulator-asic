"""Measure I2C-relevant phase timings off a `tb_trace` trace. F4's instrument.

⛔⛔ WHAT THIS EXISTS TO MEASURE, AND WHY A PROBE WAS NOT ENOUGH. The clocked
SCL high phase was the synchroniser latency rather than the programmed delay --
MEASURED FLAT AT 6 CYCLES while `d` spanned 13x -- and nothing in the suite
could see it, because Layer B compares DISPATCH COUNTS and a park changes
timing without changing a count. So the quantity has to be measured directly
off the wire, at several delays, with a control arm.

WHAT IT REPORTS, per clocked lane:
  t_HIGH / t_LOW   run lengths of the lane's CLOCK pin, in cycles
  t_SU;DAT         SDA stable before the SCL rise
  t_HD;DAT         SDA stable after the SCL fall

⚠ WHAT IT DOES **NOT** REPORT, NAMED RATHER THAN IMPLIED: t_SU;STA, t_HD;STA
and t_SU;STO need START/STOP conditions, which the clocked scheme does not
generate -- `OP_START`/`OP_STOP` are separate opcodes and the clocked images do
not contain them. A gate reading this must say those were NOT CHECKED rather
than read their absence as compliance.

⛔ IT IS A MEASUREMENT, NOT AN ADJUDICATION. Nothing here knows what UM10204
requires; `model/a2/gate_um10204.py` holds the table and decides. Keeping them
apart is deliberate: the measurement must not be able to quietly define its own
pass condition.
"""
import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pe_isa as I

HB = I.HDR_BYTES


def load_image(path):
    by = bytearray()
    with open(path, encoding="ascii", errors="replace") as fh:
        for line in fh:
            line = line.split("//")[0].strip()
            if not line:
                continue
            for tok in line.split():
                if tok.startswith("@"):
                    continue
                by.append(int(tok, 16))
    return bytes(by)


def unpack(fields, raw, nbytes):
    w = int.from_bytes(raw, "big")
    total = sum(x for _n, x in fields)
    w >>= (nbytes * 8 - total)
    out, acc = {}, w
    for name, width in reversed(fields):
        out[name] = acc & ((1 << width) - 1)
        acc >>= width
    return out


def lanes_of(img):
    """Clocked lanes, from the image's own headers."""
    out = []
    for li in range(I.N_LANES):
        h = unpack(I.HDR_FIELDS, img[li * HB:(li + 1) * HB], HB)
        if h["clkpin"] == I.PIN_NONE or h["clkpin"] == h["pin"]:
            continue            # `clk_real` is false: nothing here is clocked
        out.append({"lane": li, "pin": h["pin"], "clkpin": h["clkpin"],
                    "mode": h["mode"], "d": h["t"]})
    return out


def bit(vec, n):
    return vec[len(vec) - 1 - n] if n < len(vec) else None


def read_trace(path, pins):
    """cycle-indexed levels for the pins named, from `uio_in` (the RESOLVED bus).

    ⭐ `uio_in` AND NOT `uio_out`, because an open-drain 1 is a RELEASE: the
    level on the wire is what the bus model resolves, which is the only thing a
    peer -- or UM10204 -- has an opinion about.
    """
    cols = {p: [] for p in pins}
    cyc = []
    with open(path, encoding="ascii", errors="replace") as fh:
        for line in fh:
            f = line.split()
            # ⛔ THE HEADER LINE IS NOT A SAMPLE, AND A FIELD-COUNT TEST DOES
            # NOT EXCLUDE IT. `tb_trace` writes a `# img=... bytes=... peer=...`
            # comment first, which has NINE fields -- so `len(f) >= 5` admitted
            # it and `f[4]` read `peer=none` as a bus vector. ⚠ The scratch
            # probe this was promoted from had exactly that bug; it was harmless
            # only because the leading run is dropped anyway, which is the kind
            # of luck that stops holding when someone re-uses the parser.
            if len(f) < 5 or not f[0].isdigit():
                continue
            cyc.append(int(f[0]))
            for p in pins:
                cols[p].append(bit(f[4], p))
    return cyc, cols


def transitions(seq):
    """indices where the level changes, and the level it changed TO."""
    out = []
    for i in range(1, len(seq)):
        if seq[i] != seq[i - 1]:
            out.append((i, seq[i]))
    return out


def runs_of(seq):
    out, cur, k, start = [], None, 0, 0
    for i, v in enumerate(seq):
        if v == cur:
            k += 1
        else:
            if cur is not None:
                out.append((cur, k, start))
            cur, k, start = v, 1, i
    if cur is not None:
        out.append((cur, k, start))
    return out


def stats(xs):
    if not xs:
        return None
    c = collections.Counter(xs)
    return {"n": len(xs), "min": min(xs), "max": max(xs),
            "modal": c.most_common(1)[0][0],
            "hist": sorted(c.items())[:24]}


def measure(trace, image):
    img = load_image(image)
    lanes = lanes_of(img)
    pins = sorted({l["pin"] for l in lanes} | {l["clkpin"] for l in lanes})
    _cyc, cols = read_trace(trace, pins)
    out = []
    for l in lanes:
        scl, sda = cols[l["clkpin"]], cols[l["pin"]]
        rr = runs_of(scl)
        # ⛔ DROP THE FIRST AND LAST RUN: the first is load-mode idle (the pins
        # are released high before the program runs) and the last is truncated
        # by the cycle limit. Neither is a phase the design produced.
        body = rr[1:-1] if len(rr) > 2 else rr
        hi = [k for v, k, _s in body if v == "1"]
        lo = [k for v, k, _s in body if v == "0"]
        # ---- data setup and hold, against the clock's own edges ----
        sda_tr = [i for i, _v in transitions(sda)]
        su, hd = [], []
        for v, _k, s in body:
            if v == "1":                       # an SCL RISE at cycle s
                prev = [t for t in sda_tr if t <= s]
                if prev:
                    su.append(s - prev[-1])
            else:                              # an SCL FALL at cycle s
                nxt = [t for t in sda_tr if t >= s]
                if nxt:
                    hd.append(nxt[0] - s)
        row = dict(l)
        row["t_HIGH"] = stats(hi)
        row["t_LOW"] = stats(lo)
        row["t_SU_DAT"] = stats(su)
        row["t_HD_DAT"] = stats(hd)
        out.append(row)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", required=True)
    ap.add_argument("--image", required=True)
    ap.add_argument("--arm", default="clean")
    ap.add_argument("--json", required=True)
    a = ap.parse_args()
    rows = measure(a.trace, a.image)
    blob = {}
    if os.path.isfile(a.json):
        try:
            with open(a.json, encoding="utf-8") as fh:
                blob = json.load(fh)
        except Exception:
            blob = {}
    blob[a.arm] = {"image": os.path.basename(a.image),
                   "trace": os.path.basename(a.trace), "lanes": rows}
    with open(a.json, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(blob, fh, indent=1, sort_keys=True)
    print("  arm %-22s %d clocked lane(s) -> %s"
          % (a.arm, len(rows), os.path.basename(a.json)))
    for r in rows:
        print("    lane %d pin=%d clk=%d %-10s d=%-5d t_HIGH %s  t_LOW %s"
              % (r["lane"], r["pin"], r["clkpin"],
                 "open-drain" if r["mode"] == 0 else "push-pull", r["d"],
                 (r["t_HIGH"] or {}).get("min"), (r["t_LOW"] or {}).get("min")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
