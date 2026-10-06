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
import io
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

#: ⛔⛔ PINS WHOSE PAD VALUE IS NOT THE ENGINE'S. `project.v` OVERRIDES
#: `uio_oe[MISO_PIN]` with the SPI target's `miso_oe_q`, so the engine's write to
#: that pin never reaches the pad, and `CS_PIN` is that target's chip-select
#: INPUT. A phase measured on either is a measurement of the SPI target, not of
#: the lane that declared the pin.
#: ⚠ THIS WAS NOT HYPOTHETICAL: `build_ckfive` puts lane 3 on pin 6 / clkpin 7 --
#: both of them -- and the control arm duly reported a "clock" there. Chasing a
#: 15-cycle shift on that pin cost a whole investigation before the override was
#: found. `build_ckfive` is allowed the collision because it declares itself not
#: pin-map-legal; the MEASUREMENT is not allowed to believe it.
#: ⭐ The values are carried here rather than imported because `project.v` holds
#: them as module parameters, not in any Python module -- and they are asserted
#: against that file at run time below, so a drift is a failure and not a
#: silent disagreement.
MISO_PIN = 7
CS_PIN = 6


def _check_pin_constants(root):
    """Assert the carried pin numbers still match `src/project.v`."""
    # ⛔⛔ NO BARE `except` HERE, AND THE FIRST VERSION HAD ONE -- WHICH MADE
    # THIS GUARD UNABLE TO FIRE AT ALL. `io` was not imported, so `io.open`
    # raised NameError, the bare handler swallowed it and the function returned
    # `None` on every call. A deliberately wrong MISO_PIN was NOT reported.
    # ⚠ That is the exact shape this function exists to prevent, in the
    # function itself: a check whose failure path is the silent one.
    import re
    path = os.path.join(root, "src", "project.v")
    txt = io.open(path, encoding="utf-8").read()
    out = {}
    for name in ("MISO_PIN", "CS_PIN"):
        m = re.search(r"parameter\s+integer\s+%s\s*=\s*(\d+)" % name, txt)
        if m:
            out[name] = int(m.group(1))
    if not out:
        raise AssertionError(
            "no MISO_PIN/CS_PIN parameters found in %s -- the pins this "
            "measurement excludes could not be confirmed" % path)
    return [k for k, v in out.items() if v != globals()[k]]


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
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bad = _check_pin_constants(root)
    if bad:
        raise AssertionError(
            "MISO_PIN/CS_PIN here disagree with src/project.v: %s. A phase "
            "measurement that excludes the wrong pins is worse than one that "
            "excludes none, because the exclusion looks deliberate" % bad)
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
        # ⛔⛔ MEASURE ONLY COMPLETE CLOCK PERIODS, by a structural rule rather
        # than a tuned window. A LOW run counts as a t_LOW only when a HIGH
        # follows it AND another LOW follows that -- which is what proves the
        # high phase ended in a FALL rather than in the lane going quiescent.
        # ⚠ WHY: the phases at the EDGES of a program are not clock periods at
        # all. The first low run after the bus leaves load mode is the tail of
        # the release, and the last one ends because the lane stopped clocking.
        # Measured, the tail showed up as a lone short outlier -- lane 3's
        # t_LOW histogram was [[14,1],[92,1],[120,6]] with t_HIGH a clean 125
        # on all seven, and the 14 was the final low run before a
        # 38,139-cycle idle high.
        # ⛔ IT EXCLUDES NON-PERIODS, NOT SHORT VALUES. A genuinely short low
        # phase in the middle of a program sits inside a complete period and is
        # still measured. The first attempt at this fix dropped a LEADING low
        # run, which was the wrong end and changed nothing -- recorded because
        # a rule that does not bite looks exactly like one that did.
        periods = []
        for j in range(len(body) - 2):
            if (body[j][0] == "0" and body[j + 1][0] == "1"
                    and body[j + 2][0] == "0"):
                periods.append((body[j], body[j + 1]))
        lo = [p[0][1] for p in periods]
        hi = [p[1][1] for p in periods]
        # ---- data setup and hold, against the clock's own edges ----
        sda_tr = [i for i, _v in transitions(sda)]
        su, hd = [], []
        n_high_moves = [0]      # SDA transitions during a clock HIGH phase
        for low, high in periods:
            s_fall = low[2]                    # the LOW run begins at the fall
            s_rise = high[2]                   # the HIGH run begins at the rise
            prev = [t for t in sda_tr if t <= s_rise]
            if prev:
                su.append(s_rise - prev[-1])
            # ⛔⛔ t_HD;DAT IS ONLY DEFINED WHERE SDA ACTUALLY MOVES, and the
            # first version of this got it wrong in the flattering direction.
            # It took the next SDA transition after the fall WHEREVER it was,
            # so on a lane whose consecutive bits happen to be equal the answer
            # was the distance to some later bit -- lane 3 reported 489 cycles
            # of "hold" on the ZERO-HOLD build, which would have read as the
            # requirement being met by a design that does not meet it.
            # ⇒ The transition must fall inside THIS bit period (after the
            #   fall, before the rise). If SDA does not move, there is no hold
            #   to measure -- the data was already stable, which is not a
            #   violation and must not be recorded as a passing measurement
            #   either.
            inside = [t for t in sda_tr if s_fall <= t < s_rise]
            if inside:
                hd.append(inside[0] - s_fall)
            # ⛔⛔ SDA MOVING WHILE SCL IS HIGH IS A HARD PROTOCOL VIOLATION,
            # and it is counted separately because its ABSENCE from `hd` reads
            # like no data rather than like bad data. UM10204: data may change
            # only while SCL is low; a change during the high phase is a START
            # or a STOP to any receiver.
            # ⚠ IT IS REACHABLE FROM THE HOLD ITSELF. If `SDA_HOLD` exceeds the
            # lane's low phase, the held value lands AFTER the next rise -- so
            # a fix for the hold requirement can create this violation, which is
            # exactly why it is measured and not reasoned about. MEASURED: at
            # d = 9 with SDA_HOLD = 15 the clocked lane reports NO in-period
            # transition at all, because every one of them moved late.
            nxt_fall = s_rise + high[1]
            moved_high = [t for t in sda_tr if s_rise <= t < nxt_fall]
            n_high_moves[0] += len(moved_high)
        row = dict(l)
        row["pad_overridden"] = (l["pin"] in (MISO_PIN, CS_PIN)
                                 or l["clkpin"] in (MISO_PIN, CS_PIN))
        row["t_HIGH"] = stats(hi)
        row["t_LOW"] = stats(lo)
        row["t_SU_DAT"] = stats(su)
        row["t_HD_DAT"] = stats(hd)
        row["sda_moves_in_high"] = n_high_moves[0]
        row["periods"] = len(periods)
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
