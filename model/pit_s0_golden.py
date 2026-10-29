"""PIT chunk 2 golden: the ROLE TABLE stage 0 must write (bytes 32..38).

THE INPUT IS THE CAPTURE AS STORED (Wilson 10-29): pit_capture_golden.decode of
the capture's bytes -- whole records, saturating intervals -- with every wire's
level rebuilt from the starting levels (byte 39). The RULES are the frozen
model's: model/pit_golden.py, which must hash to FROZEN (refused otherwise).

THE TABLE: wire w's 7 bits {change level, partner (3), role (3)} at bit 7w of a
56-bit word; byte 32 + i = its bits 8i+7 .. 8i. Roles: 0 none, 1 CLOCK,
2 SYNC_DATA, 3 FRAME, 4 AMBIGUOUS, 5 CLOCK of an I2C bus, 6 SYNC_DATA of an I2C
bus, 7 REFUSED (the rate floor: every wire, partner = the wire that tripped it).
Partner: SYNC_DATA / FRAME -> the clock; AMBIGUOUS -> the other wire of the pair.
"""
import hashlib
import os
import re

import pit_capture_golden as PG

HERE = os.path.dirname(os.path.abspath(__file__))
FROZEN = "e55d0b631037afade63ae98193a7f4f35520998a667d123b4b3f3a61d6b304b9"
TABLE_AT, TABLE_BYTES = 32, 7
R_NONE, R_CLOCK, R_SYNC, R_FRAME, R_AMBIG, R_CLOCK_I2C, R_SYNC_I2C, R_REFUSED = range(8)


def frozen_model():
    path = os.path.join(HERE, "pit_golden.py")
    with open(path, "rb") as fh:
        got = hashlib.sha256(fh.read()).hexdigest()
    if got != FROZEN:
        raise RuntimeError("model/pit_golden.py is NOT the frozen stage-0 rule set (%s, want %s)"
                           % (got[:8], FROZEN[:8]))
    import pit_golden
    return pit_golden


def stored_capture(log, lv0, budget=None, ncyc=None):
    """the capture stage 0 reads: [(t, mask, levels after)] decoded from the
    stored bytes, or None if the capture never stopped (stage 0 never runs)."""
    cap_bytes, n, _ovf, why = PG.encode(log, budget, ncyc)
    if why is None:
        return None
    recs, _k = PG.decode(cap_bytes, n)
    out, lv = [], lv0
    for t, mask in recs:
        lv ^= mask
        out.append((t, mask, lv))
    return out


def roles_of(cap):
    return frozen_model().stage0(cap)


def table(roles):
    """the 7 bytes of the role table for stage0's result."""
    ent = [0] * 8
    if "refused" in roles:
        w = int(re.match(r"wire (\d+):", roles["refused"]).group(1))
        ent = [R_REFUSED | (w << 3)] * 8
    else:
        for w, r in roles.items():
            role, part, lvl = r["role"], 0, 0
            if role == "CLOCK":
                code = R_CLOCK_I2C if r.get("bus") == "I2C" else R_CLOCK
            elif role == "SYNC_DATA":
                code = R_SYNC_I2C if r.get("bus") == "I2C" else R_SYNC
                part, lvl = r["clock"], r["change_level"]
            elif role == "FRAME":
                code, part = R_FRAME, r["clock"]
            elif role == "AMBIGUOUS":
                code, part = R_AMBIG, r["with"] if "with" in r else r["clock"]
            else:
                raise ValueError("unknown role %r" % role)
            ent[w] = code | (part << 3) | (lvl << 6)
    word = 0
    for w in range(8):
        word |= ent[w] << (7 * w)
    return bytes((word >> (8 * i)) & 0xFF for i in range(TABLE_BYTES))


def expect(log, lv0, budget=None, ncyc=None):
    """-> (table bytes or None if stage 0 never runs, roles)."""
    cap = stored_capture(log, lv0, budget, ncyc)
    if cap is None:
        return None, None
    roles = roles_of(cap)
    return table(roles), roles
