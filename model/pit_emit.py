"""pit_emit -- the RPL EMITTER v1 (Wilson 11-06, item 2): the PIT's results
bytes in, the spec text out, and the parser that reads the spec back.

THE ONE RULE: the spec says only what the chip found. Every field comes from
the results bytes -- the status (2, 28, 29), the role table (32..38), the
per-wire records (40..119) and the stage 3 record (120..135) -- and a field the
chip did not determine is a `? unknown <field> -- <reason>;` line, never a
value. Nothing is inferred on the host.

THE SYNTAX (Wilson 11-06, D1). One statement per line, each ending in `;`:

    spec sniff is
      captured at 60000000 Hz;
      partial full after 312 records;
      wire uio0 : NRZ_ASYNC idle 1 rate 2500000.000 Bd frame 10 bits given all-wires-sniffed;
      wire uio1 : role CLOCK;
      wire uio2 : role SYNC_DATA of uio1 change 0;
      wire uio3 : role FRAME of uio1;
      wire uio4 : bit 400.0000 ns;
      ? unknown uio4.encoding -- non-harmonic rival;
      crc on uio0 : width 16 refin refout poly 0x1021 frame 3 bytes init 0xFFFF xorout 0x0000 source catalogue "CRC-16/MODBUS" class 1;
    end sniff;

  * RATES ARE REAL TIME (D1 change 1): the bit period in ns (`bit`, Manchester's
    `half-bit`) or, for UART, `rate ... Bd`; the capture clock once in the
    header. pe_asm converts at whatever target clock it is given. Printed to a
    precision that recovers the record's 16.4 fixed-point period exactly.
  * PROVENANCE IS A CLAUSE (D1 change 2): `source catalogue "<name>"` when the
    canonical member IS a catalogue entry, else `source data`; `class 1` or
    `class multi` (the record's class flag: the data cannot tell the members
    of a multi class apart). A validator reads clauses; `--` comments are for
    people and the parser drops them.
  * CRC PARAMETERS ARE ROCKSOFT'S (the reveng catalogue's convention): the
    record holds xorout in TRANSMISSION order, so a reflected CRC's xorout is
    bit-reversed on the way out (measured on the frozen solver: Rocksoft
    xorout 0x0F0F, refin / refout, is stored 0xF0F0; init is stored as
    Rocksoft's). The catalogue match is made on the record's own values.
  * `given all-wires-sniffed`: the record's condition bit (Wilson 10-28 (b)) --
    a one-wire data class holds only if no clock hides off the sniffed pins.
  * v2's order-and-bounds edges parse today with no new syntax (vol5's
    operators, `during` from its Timing macro):
        pattern Frame(uio0) -> Frame(uio0) during (100 ns, 2000 ns);

⚠ WHAT THE BYTES CANNOT SAY. The clocked bus's refusals (no CS level, no
clean sample edge, data in both levels) and stage 3's own UNKNOWN reasons
leave the stage 3 record all zero, and byte 2's flag bits are never written:
the reason is in the golden, not on the chip. v1 says what the bytes do
show (the role table: e.g. a clock and data with no frame wire) and otherwise
"no stage 3 record". A reason code would be an RTL change: a ruling.
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import clock                                                      # noqa: E402

TABLE_AT, TABLE_BYTES = 32, 7
REC_AT, REC_BYTES = 40, 10
S3_AT, S3_BYTES = 120, 16
RESULTS_BYTES = S3_AT + S3_BYTES

# the role table's codes (pit_s0_golden.R_*)
R_NONE, R_CLOCK, R_SYNC, R_FRAME, R_AMBIG, R_CLOCK_I2C, R_SYNC_I2C, R_REFUSED = range(8)
# the per-wire record's class codes (run_pit_s12.C_*)
C_NONE, C_CLOCK, C_MANCH, C_ASYNC, C_NRZI, C_LEVEL, C_UNK, C_ROLE = range(8)
CLS_NAME = {C_CLOCK: "CLOCK", C_MANCH: "MANCHESTER", C_ASYNC: "NRZ_ASYNC",
            C_NRZI: "NRZI_STUFFED", C_LEVEL: "LEVEL_CODE"}
#: the record's `why` code -> its reason; codes 1-3 are stage 1's (no timing)
WHY = {1: "fewer than 16 intervals", 2: "no candidate period reaches the hit rate",
       3: "non-harmonic rival period", 4: "no non-idle runs",
       5: "clock-shaped but irregular", 6: "stage 0 refused the capture",
       7: "sync-possible: another wire is as active"}
WHY_TIMING = (1, 2, 3)
WCODE = {1: 8, 2: 16, 3: 32}
#: the R3 canonical-member catalogue (pit_golden.CATALOGUE, frozen): name ->
#: (width, poly, init, xorout, reflected), in the model's transmission domain
CATALOGUE = {
    "CRC-8":              (8, 0x07, 0x00, 0x00, False),
    "CRC-8/MAXIM":        (8, 0x31, 0x00, 0x00, True),
    "CRC-16/CCITT-FALSE": (16, 0x1021, 0xFFFF, 0x0000, False),
    "CRC-16/XMODEM":      (16, 0x1021, 0x0000, 0x0000, False),
    "CRC-16/ARC":         (16, 0x8005, 0x0000, 0x0000, True),
    "CRC-16/MODBUS":      (16, 0x8005, 0xFFFF, 0x0000, True),
    "CRC-32":             (32, 0x04C11DB7, 0xFFFFFFFF, 0xFFFFFFFF, True),
}
CONDITION = "all-wires-sniffed"


class SpecError(Exception):
    pass


# ---------------------------------------------------------------------------
# results bytes -> claims (a plain dict: the thing the emitter prints and the
# parser returns, so parse(emit(r)) == claims(r) is checkable)
# ---------------------------------------------------------------------------
def _p16(rec):
    return ((rec[1] >> 4) & 7) << 16 | rec[2] << 8 | rec[3]


def _fb(rec):
    return (rec[1] & 0xF) << 9 | (rec[4] >> 7) << 8 | rec[9]


def claims(results, clock_hz=None):
    """-> {"clock_hz", "partial", "roles", "wires", "crc", "unknown", "patterns"}.
    roles: {w: (role, partner, change)}; wires: {w: {"cls", "p16", "idle", "fb",
    "given"}}; crc: None or {"wire", "width", "reflected", "poly", "frame",
    "init", "xorout", "source", "multi"}; unknown: [(field, reason)] in order."""
    r = bytes(results)
    if len(r) < RESULTS_BYTES:
        raise SpecError("results: %d bytes, need %d" % (len(r), RESULTS_BYTES))
    out = {"clock_hz": int(clock_hz or clock.hz()), "partial": None, "roles": {},
           "wires": {}, "crc": None, "unknown": [], "patterns": []}
    unk = out["unknown"]
    if r[2] & 0x80:
        n = (r[28] & 0x3F) << 8 | r[29]
        out["partial"] = ("overrun" if r[28] & 0x80 else "full", n)
    # the role table: 8 x 7 bits, little-endian
    word = int.from_bytes(r[TABLE_AT:TABLE_AT + TABLE_BYTES], "little")
    ent = [(word >> (7 * w)) & 0x7F for w in range(8)]
    if ent[0] & 7 == R_REFUSED:
        unk.append(("roles", "stage 0 refused the capture at uio%d" % ((ent[0] >> 3) & 7)))
    else:
        for w, e in enumerate(ent):
            code, part, lvl = e & 7, (e >> 3) & 7, e >> 6
            if code == R_NONE:
                continue
            if code == R_AMBIG:
                unk.append(("uio%d.role" % w, "ambiguous with uio%d" % part))
                continue
            role = {R_CLOCK: "CLOCK", R_CLOCK_I2C: "CLOCK", R_SYNC: "SYNC_DATA",
                    R_SYNC_I2C: "SYNC_DATA", R_FRAME: "FRAME"}[code]
            i2c = code in (R_CLOCK_I2C, R_SYNC_I2C)
            out["roles"][w] = {"role": role, "i2c": i2c,
                               "of": part if code in (R_SYNC, R_SYNC_I2C, R_FRAME) else None,
                               "change": lvl if code in (R_SYNC, R_SYNC_I2C) else None}
    # the per-wire records
    for w in range(8):
        rec = r[REC_AT + REC_BYTES * w:REC_AT + REC_BYTES * (w + 1)]
        cls, why, cond = rec[0] >> 5, (rec[0] >> 2) & 7, (rec[0] >> 1) & 1
        if cls in (C_NONE, C_ROLE):
            continue
        p16 = _p16(rec)
        if cls == C_UNK:
            if why in WHY_TIMING or why == 6 or p16 == 0:
                unk.append(("uio%d.rate" % w, WHY.get(why, "no timing")))
            else:
                out["wires"][w] = {"cls": None, "p16": p16, "idle": None, "fb": None, "given": False}
            unk.append(("uio%d.encoding" % w, WHY.get(why, "unclassified")))
            continue
        out["wires"][w] = {"cls": CLS_NAME[cls], "p16": p16,
                           "idle": rec[1] >> 7 if cls == C_ASYNC else None,
                           "fb": _fb(rec) if cls == C_ASYNC else None,
                           "given": bool(cond)}
    # the stage 3 record
    s = r[S3_AT:S3_AT + S3_BYTES]
    if not s[0] & 0x08:
        if any(v["role"] == "SYNC_DATA" for v in out["roles"].values()) and not \
                any(v["role"] == "FRAME" or v["i2c"] for v in out["roles"].values()):
            why = "no stage 3 record: a clocked bus with no frame wire"
        else:
            why = "no stage 3 record: no UART wire and no clocked bus it could sample"
        unk.append(("crc", why))
        return out
    w = s[0] & 7
    if not s[0] & 0x10:
        unk.append(("uio%d.crc" % w, "no polynomial from %d frames" % s[3]))
        return out
    c = {"wire": w, "width": WCODE[s[1] & 3], "reflected": bool(s[0] & 0x40),
         "poly": int.from_bytes(s[4:8], "little"), "frame": s[1] >> 2,
         "init": None, "xorout": None, "source": None, "multi": None}
    out["crc"] = c
    if s[0] & 0x20:
        c["init"] = int.from_bytes(s[8:12], "little")
        c["xorout"] = int.from_bytes(s[12:16], "little")
        c["multi"] = bool(s[0] & 0x80)
        key = (c["width"], c["poly"], c["init"], c["xorout"], c["reflected"])
        c["source"] = next((n for n, v in CATALOGUE.items() if v == key), "data")
        if c["reflected"]:                  # the record's transmission order -> Rocksoft
            c["xorout"] = _rev(c["xorout"], c["width"])
    else:
        unk.append(("uio%d.crc.init" % w, "not solved from the frames"))
        unk.append(("uio%d.crc.xorout" % w, "not solved from the frames"))
    return out


def _rev(v, n):
    return int(bin(v)[2:].zfill(n)[::-1], 2)


# ---------------------------------------------------------------------------
# claims -> text
# ---------------------------------------------------------------------------
def _ns(p16, hz):
    return "%.4f" % (p16 / 16.0 / hz * 1e9)


def _bd(p16, hz):
    return "%.3f" % (hz * 16.0 / p16)


def _hex(v, width):
    return "0x%0*X" % (width // 4, v)


def render(cl):
    hz = cl["clock_hz"]
    L = ["-- PE PIT spec v1: the chip's claims only (results bytes 0..135)",
         "spec sniff is", "  captured at %d Hz;" % hz]
    if cl["partial"]:
        L.append("  partial %s after %d records;" % cl["partial"])
    for w in sorted(cl["roles"]):
        v = cl["roles"][w]
        t = "  wire uio%d : role %s" % (w, v["role"])
        if v["i2c"]:
            t += " i2c"
        if v["of"] is not None:
            t += " of uio%d" % v["of"]
        if v["change"] is not None:
            t += " change %d" % v["change"]
        L.append(t + ";")
    for w in sorted(cl["wires"]):
        v = cl["wires"][w]
        t = "  wire uio%d :" % w
        if v["cls"]:
            t += " " + v["cls"]
        if v["idle"] is not None:
            t += " idle %d" % v["idle"]
        if v["cls"] == "NRZ_ASYNC":
            t += " rate %s Bd" % _bd(v["p16"], hz)
        elif v["cls"] == "MANCHESTER":
            t += " half-bit %s ns" % _ns(v["p16"], hz)
        else:
            t += " bit %s ns" % _ns(v["p16"], hz)
        if v["fb"] is not None:
            t += " frame %d bits" % v["fb"]
        if v["given"]:
            t += " given " + CONDITION
        L.append(t + ";")
    c = cl["crc"]
    if c:
        t = "  crc on uio%d : width %d" % (c["wire"], c["width"])
        if c["reflected"]:
            t += " refin refout"
        t += " poly %s frame %d bytes" % (_hex(c["poly"], c["width"]), c["frame"])
        if c["init"] is not None:
            t += " init %s xorout %s" % (_hex(c["init"], c["width"]), _hex(c["xorout"], c["width"]))
            t += ' source catalogue "%s"' % c["source"] if c["source"] != "data" else " source data"
            t += " class %s" % ("multi" if c["multi"] else "1")
        L.append(t + ";")
    for f, why in cl["unknown"]:
        L.append("  ? unknown %s -- %s;" % (f, why))
    for p in cl["patterns"]:
        L.append("  pattern %s;" % p)
    L.append("end sniff;")
    return "\n".join(L) + "\n"


def emit(results, clock_hz=None):
    return render(claims(results, clock_hz))


# ---------------------------------------------------------------------------
# text -> claims (the round trip's and the validator's reader: clauses only)
# ---------------------------------------------------------------------------
_EV = r"[A-Za-z_]\w*\(\s*\w+(?:\s*,\s*\w+)*\s*\)"
_PAT = re.compile(r"^%s(?:\s*(?:->|\|\||~|<|and|or)\s*%s)*"
                  r"(?:\s+during\s*\(\s*[\d.]+\s*ns\s*,\s*[\d.]+\s*ns\s*\))?$" % (_EV, _EV))


def _wire(tok):
    m = re.fullmatch(r"uio([0-7])", tok)
    if not m:
        raise SpecError("not a wire: %r" % tok)
    return int(m.group(1))


def parse(text):
    cl = {"clock_hz": None, "partial": None, "roles": {}, "wires": {}, "crc": None,
          "unknown": [], "patterns": []}
    body = [ln.strip() for ln in text.splitlines()]
    body = [ln for ln in body if ln and not ln.startswith("--")]
    if not body or body[0] != "spec sniff is" or body[-1] != "end sniff;":
        raise SpecError("not a `spec sniff is ... end sniff;` block")
    for ln in body[1:-1]:
        if ln.startswith("?"):
            m = re.fullmatch(r"\? unknown (\S+) -- ([^;]+);", ln)
            if not m:
                raise SpecError("bad unknown line: %r" % ln)
            cl["unknown"].append((m.group(1), m.group(2)))
            continue
        if "--" in ln:
            ln = ln[:ln.index("--")].rstrip()
        if not ln.endswith(";"):
            raise SpecError("no `;`: %r" % ln)
        s = ln[:-1].strip()
        if s.startswith("pattern "):
            p = s[len("pattern "):].strip()
            if not _PAT.match(p):
                raise SpecError("bad pattern: %r" % p)
            cl["patterns"].append(p)
            continue
        tk = s.split()
        if tk[:2] == ["captured", "at"] and tk[3:] == ["Hz"]:
            cl["clock_hz"] = int(tk[2])
        elif tk[0] == "partial" and tk[2] == "after" and tk[4] == "records":
            cl["partial"] = (tk[1], int(tk[3]))
        elif tk[0] == "wire" and tk[2] == ":":
            _parse_wire(cl, _wire(tk[1]), tk[3:])
        elif tk[:2] == ["crc", "on"] and tk[3] == ":":
            cl["crc"] = _parse_crc(_wire(tk[2]), tk[4:], s)
        else:
            raise SpecError("unknown statement: %r" % ln)
    if cl["clock_hz"] is None:
        raise SpecError("no `captured at` line")
    hz = cl["clock_hz"]
    for v in cl["wires"].values():          # real time -> the record's 16.4 period
        kind, x = v.pop("_t")
        v["p16"] = round(hz * 16.0 / x) if kind == "Bd" else round(x * 1e-9 * hz * 16.0)
    return cl


def _parse_wire(cl, w, tk):
    if tk and tk[0] == "role":
        v = {"role": tk[1], "i2c": False, "of": None, "change": None}
        i = 2
        while i < len(tk):
            if tk[i] == "i2c":
                v["i2c"], i = True, i + 1
            elif tk[i] == "of":
                v["of"], i = _wire(tk[i + 1]), i + 2
            elif tk[i] == "change":
                v["change"], i = int(tk[i + 1]), i + 2
            else:
                raise SpecError("wire uio%d: %r" % (w, tk[i]))
        cl["roles"][w] = v
        return
    v = {"cls": None, "p16": None, "idle": None, "fb": None, "given": False}
    i = 0
    if tk and tk[0] in CLS_NAME.values():
        v["cls"], i = tk[0], 1
    while i < len(tk):
        k = tk[i]
        if k == "idle":
            v["idle"], i = int(tk[i + 1]), i + 2
        elif k == "rate" and tk[i + 2] == "Bd":
            v["_t"], i = ("Bd", float(tk[i + 1])), i + 3
        elif k in ("bit", "half-bit") and tk[i + 2] == "ns":
            v["_t"], i = ("ns", float(tk[i + 1])), i + 3
        elif k == "frame" and tk[i + 2] == "bits":
            v["fb"], i = int(tk[i + 1]), i + 3
        elif k == "given" and tk[i + 1] == CONDITION:
            v["given"], i = True, i + 2
        else:
            raise SpecError("wire uio%d: %r" % (w, k))
    if "_t" not in v:
        raise SpecError("wire uio%d: no rate" % w)
    cl["wires"][w] = v


def _parse_crc(w, tk, s):
    c = {"wire": w, "width": None, "reflected": False, "poly": None, "frame": None,
         "init": None, "xorout": None, "source": None, "multi": None}
    refl = set()
    i = 0
    while i < len(tk):
        k = tk[i]
        if k == "width":
            c["width"], i = int(tk[i + 1]), i + 2
        elif k in ("refin", "refout"):
            refl.add(k)
            i += 1
        elif k in ("poly", "init", "xorout"):
            c[k], i = int(tk[i + 1], 16), i + 2
        elif k == "frame" and tk[i + 2] == "bytes":
            c["frame"], i = int(tk[i + 1]), i + 3
        elif k == "source" and tk[i + 1] == "data":
            c["source"], i = "data", i + 2
        elif k == "source" and tk[i + 1] == "catalogue":
            m = re.search(r'source catalogue "([^"]+)"', s)
            if not m:
                raise SpecError("crc: bad catalogue name")
            c["source"] = m.group(1)
            i += 2 + len(m.group(1).split())
        elif k == "class":
            c["multi"], i = {"1": False, "multi": True}[tk[i + 1]], i + 2
        else:
            raise SpecError("crc on uio%d: %r" % (w, k))
    if refl not in (set(), {"refin", "refout"}):
        raise SpecError("crc on uio%d: refin and refout come together (one record flag)" % w)
    c["reflected"] = bool(refl)
    if None in (c["width"], c["poly"], c["frame"]):
        raise SpecError("crc on uio%d: width, poly and frame are required" % w)
    if (c["init"] is None) != (c["xorout"] is None) or \
            (c["init"] is not None and None in (c["source"], c["multi"])):
        raise SpecError("crc on uio%d: init, xorout, source and class come together" % w)
    return c
