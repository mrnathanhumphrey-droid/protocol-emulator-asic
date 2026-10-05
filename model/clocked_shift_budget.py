"""CLOCKED SHIFT / SHIFTIN -- the flag-back numbers, BEFORE any RTL.

⛔ COMPUTED FROM THE LAYOUT CONSTANTS AND THE ACTUAL GENERATOR, not recalled.
`ACT_BASE`, `ACT_BYTES`, `AW` and `N_LANES` come from `model/pe_isa.py`; the
unclocked action counts are READ OFF `test/make_smoke_image.py:build_i2cframe`
opcode by opcode, and the script asserts they reproduce the two measured images
the certification pins (n=2 -> 171 bytes, n=3 -> 231) before quoting anything
about the clocked scheme. ⚠ If that assertion ever fails, every clocked number
below is void -- the accounting model no longer describes the generator.

WHAT IS RULED, and what is therefore an ASSUMPTION here:
  RULED  when `l_clkpin` is real, each dispatch of a SHIFT alternates phase
         (odd = data + clock low, even = clock high) with the bit pointer
         advancing on the low phase only, so ONE action carries a whole byte.
         Dispatch count per bit is unchanged.
  RULED  clocked SHIFTIN: yes.
  ⚠ ASSUMED, AND IT IS THE ONE NUMBER THAT MOVES THE ANSWER: that a clocked
    SHIFTIN with `count = 1` serves as the whole 1-bit ACK slot in ONE action,
    because its two phases ARE "SCL low while SDA is released" then "SCL high
    while the peer holds it". If that is wrong and the ACK still needs its
    `OP_LEVEL` scaffolding, the cost is the ACK_SCAFFOLDED column, not the
    RULED one. Both are printed for exactly that reason.
"""
import os
import sys

#: ⛔ `pe_isa` LIVES IN test/, and that is deliberate rather than untidy: it is
#: the ONE authority for the image layout, shared by the generators and the
#: benches. Importing a second copy into model/ is how the layout would come to
#: exist twice.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, os.pardir, "test"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pe_isa as I

STORE = 1 << I.AW
HDR = I.ACT_BASE
AB = I.ACT_BYTES
MAX_ACTIONS = (STORE - HDR) // AB


def img_bytes(actions):
    return HDR + AB * actions


# --------------------------------------------------------------------------
# THE UNCLOCKED COST, read off build_i2cframe opcode by opcode.
# --------------------------------------------------------------------------
# per wire byte:  8 x (OP_SHIFT + OP_LEVEL scl high)       = 16
#                 OP_LEVEL scl low                         +1
#                 OP_SHIFTIN (release + sample the ACK)    +1
#                 OP_LEVEL scl high (ACK on air)           +1
#                 OP_LEVEL scl low                         +1
UNCLOCKED_PER_BYTE = 8 * 2 + 4
# fixed:          OP_START, OP_LEVEL scl low,
#                 OP_LEVEL sda low, OP_LEVEL scl high, OP_STOP,
#                 OP_REARM, and the parked OP_REARM
FIXED = 7

# ⭐ THE RULED SCHEME: one action per byte, one action for the ACK.
RULED_PER_BYTE = 1 + 1
# ⚠ THE FALLBACK if a 1-bit clocked SHIFTIN cannot stand alone as the ACK:
# the byte collapses to one action but the ACK keeps its scaffolding.
SCAFFOLDED_PER_BYTE = 1 + 4


def write_actions(n, per_byte):
    return per_byte * n + FIXED


#: ⛔ THE PREMISE, CHECKED AGAINST THE PROOF TEXT RATHER THAN REMEMBERED. The
#: ruling says the premise must read "AT MOST one refill per dispatch"; this
#: greps for the phrasing that is actually there, because "I recall the proof
#: says X" is not a reading of the proof.
PROOF = "docs/J_LANE_PROOF.md"
BAD_PHRASE = "leaves exactly one slot"
GOOD_PHRASE = "at most one slot"


def check_premise(root):
    path = os.path.join(root, PROOF)
    print("  --- the premise, read out of %s ---" % PROOF)
    if not os.path.isfile(path):
        print("    *** %s not found -- the premise cannot be checked" % PROOF)
        return 1
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()
    hits = [(i + 1, ln.strip()) for i, ln in enumerate(lines)
            if BAD_PHRASE in ln]
    good = [(i + 1, ln.strip()) for i, ln in enumerate(lines)
            if GOOD_PHRASE in ln]
    if hits:
        print("    ⛔ FOUND THE PHRASING THE CLOCKED SHIFT FALSIFIES:")
        for n, ln in hits:
            print("       %s:%d" % (PROOF, n))
            print("         %s" % ln[:72])
        print("    ⇒ Theorem 3's proof currently argues from EXACTLY one slot")
        print("       owed per dispatch. A clocked SHIFT RE-dispatches the same")
        print("       action: no writeback, no store read, so it leaves ZERO")
        print("       slots to refill. 'Exactly one' becomes FALSE.")
        print("    ⭐ THE CONCLUSION SURVIVES, and the direction is why: the")
        print("       proof uses the premise only to bound demand at 'at most k")
        print("       refills per d-cycle window'. A re-dispatch demands FEWER,")
        print("       never more, so weakening 'exactly' to 'at most' preserves")
        print("       the bound. The amendment is bookkeeping, not a re-proof.")
        print("    ⚠ P10's own wording needs the same treatment: 'the refill")
        print("       owed is for the SPARE' -- under a re-dispatch no refill is")
        print("       owed at all.")
        print("    ⛔ NOT EDITED HERE: amending a published proof is a ruling,")
        print("       not a clean-up. Flagged with the line number instead.")
        return 0
    if good:
        print("    ok -- already reads 'at most':")
        for n, ln in good[:3]:
            print("       %s:%d  %s" % (PROOF, n, ln[:60]))
        return 0
    print("    ⚠ NEITHER phrasing found. A zero-hit search proves the STRING")
    print("      absent, not the premise -- read the proof by hand before")
    print("      concluding anything about it.")
    return 1


def main():
    root = os.path.join(_HERE, os.pardir)
    print("  layout, from model/pe_isa.py")
    print("    store            %d bytes (AW = %d)" % (STORE, I.AW))
    print("    header region    %d bytes (%d lanes x %d)"
          % (HDR, I.N_LANES, I.HDR_BYTES))
    print("    action           %d bytes" % AB)
    print("    ⇒ ACTION BUDGET  %d actions  ((%d - %d) / %d)"
          % (MAX_ACTIONS, STORE, HDR, AB))
    print()

    # ---- the accounting model must reproduce the pinned images ------------
    print("  --- the unclocked model, against the images the certification pins ---")
    rc = 0
    for n, want in ((2, 171), (3, 231), (4, 291)):
        got = img_bytes(write_actions(n, UNCLOCKED_PER_BYTE))
        ok = (got == want)
        print("    n=%d  %4d bytes   pinned %4d   %s"
              % (n, got, want, "ok" if ok else "*** MISMATCH"))
        if not ok:
            rc = 1
    if rc:
        print("    ⛔ THE MODEL NO LONGER DESCRIBES THE GENERATOR. Every number")
        print("       below is void until this agrees again.")
        return 1
    print("    ⇒ %d actions per wire byte + %d fixed, confirmed"
          % (UNCLOCKED_PER_BYTE, FIXED))
    print()

    # ---- actions per byte -------------------------------------------------
    print("  --- actions per wire byte ---")
    print("    unclocked (today)                      %2d" % UNCLOCKED_PER_BYTE)
    print("    RULED: clocked SHIFT + clocked SHIFTIN %2d   (%.1fx cheaper)"
          % (RULED_PER_BYTE, UNCLOCKED_PER_BYTE / RULED_PER_BYTE))
    print("    if the ACK keeps its scaffolding       %2d   (%.1fx cheaper)"
          % (SCAFFOLDED_PER_BYTE,
             UNCLOCKED_PER_BYTE / SCAFFOLDED_PER_BYTE))
    print("    ⭐ DISPATCHES per byte are UNCHANGED at %d (8 bits x 2 phases)"
          % (8 * 2))
    print("       -- which is the ruling's point: the timing model is untouched,")
    print("       and it is also exactly why C must be re-measured, because a")
    print("       RE-DISPATCHED action needs no store read.")
    print()

    # ---- the FRAM write ---------------------------------------------------
    print("  --- a full FRAM write:  S | dev | A | addrhi | A | addrlo | A | data | A | P ---")
    print("    (4 wire bytes)")
    print("    %-34s %8s %8s %s" % ("scheme", "actions", "bytes", "fits 256?"))
    for label, pb in (("unclocked (today)", UNCLOCKED_PER_BYTE),
                      ("RULED clocked", RULED_PER_BYTE),
                      ("clocked, ACK scaffolded", SCAFFOLDED_PER_BYTE)):
        a = write_actions(4, pb)
        b = img_bytes(a)
        print("    %-34s %8d %8d %s"
              % (label, a, b, "yes" if b <= STORE else "NO -- over by %d" % (b - STORE)))
    print()
    print("    the longest write that fits, per scheme:")
    for label, pb in (("unclocked (today)", UNCLOCKED_PER_BYTE),
                      ("RULED clocked", RULED_PER_BYTE),
                      ("clocked, ACK scaffolded", SCAFFOLDED_PER_BYTE)):
        n = 0
        while img_bytes(write_actions(n + 1, pb)) <= STORE:
            n += 1
        print("      %-32s n = %d wire bytes" % (label, n))
    print()

    # ---- the random read --------------------------------------------------
    # S | dev+W | A | addrhi | A | addrlo | A | Sr | dev+R | A | data | NACK | P
    print("  --- a random read with repeated START ---")
    print("    S | dev+W | A | addrhi | A | addrlo | A | Sr | dev+R | A | data | A- | P")
    print()
    # ⚠ THE REPEATED START IS COSTED AT 4 ACTIONS, NOT 1: SDA must be released
    # high and SCL taken high again before SDA may fall, and after a clocked
    # ACK the clock is left HIGH, so the sequence is SCL low, SDA high, SCL
    # high, then OP_START. Costing it at 1 would be the optimistic error.
    REPEATED_START = 4
    STOP_SEQ = 3            # SDA low, SCL high, OP_STOP
    rows = []
    # RULED: every master byte is 1 action + 1 ACK action; the byte read IN is
    # one clocked SHIFTIN(count=8); the master NACK is one clocked SHIFT(1).
    ruled = (1                      # OP_START
             + 3 * RULED_PER_BYTE   # dev+W, addrhi, addrlo
             + REPEATED_START
             + RULED_PER_BYTE       # dev+R
             + 1                    # clocked SHIFTIN(8): the data byte
             + 1                    # clocked SHIFT(1): the master NACK
             + STOP_SEQ
             + 2)                   # OP_REARM + the parked OP_REARM
    rows.append(("RULED clocked", ruled))
    # Scaffolded: the master bytes keep their ACK scaffolding, and reading a
    # byte IN costs 8 x (SHIFTIN + SCL high) + a trailing SCL low.
    scaf = (1
            + 3 * SCAFFOLDED_PER_BYTE
            + REPEATED_START
            + SCAFFOLDED_PER_BYTE
            + (8 * 2 + 1)
            + 3
            + STOP_SEQ
            + 2)
    rows.append(("clocked, ACK scaffolded", scaf))
    # Today: nothing is clocked.
    today = (1
             + 3 * UNCLOCKED_PER_BYTE
             + REPEATED_START
             + UNCLOCKED_PER_BYTE
             + (8 * 2 + 1)
             + 3
             + STOP_SEQ
             + 2)
    rows.insert(0, ("unclocked (today)", today))
    print("    %-34s %8s %8s %s" % ("scheme", "actions", "bytes", "fits 256?"))
    for label, a in rows:
        b = img_bytes(a)
        print("    %-34s %8d %8d %s"
              % (label, a, b,
                 "yes" if b <= STORE else "NO -- over by %d" % (b - STORE)))
    print()
    print("  " + "=" * 74)
    print("  THE FLAG-BACK")
    print("    * actions per byte: 20 today -> 2 under the ruled scheme.")
    print("    * a full 4-byte FRAM write: %d bytes today (over the store by %d)"
          % (img_bytes(write_actions(4, UNCLOCKED_PER_BYTE)),
             img_bytes(write_actions(4, UNCLOCKED_PER_BYTE)) - STORE))
    print("      -> %d bytes ruled, %d if the ACK keeps its scaffolding."
          % (img_bytes(write_actions(4, RULED_PER_BYTE)),
             img_bytes(write_actions(4, SCAFFOLDED_PER_BYTE))))
    print("    * a random read with repeated START: %d bytes ruled -- it FITS,"
          % img_bytes(ruled))
    print("      and it does NOT fit today (%d)." % img_bytes(today))
    print("    * ⚠ CORRECTION TO A PUBLISHED ESTIMATE: SPEC_V4_I2C_CERTIFIED")
    print("      §6.2 says the clocked SHIFT 'brings a full write to ~111")
    print("      bytes'. That is the ACK-SCAFFOLDED column, which assumed only")
    print("      SHIFT was clocked. SHIFTIN was ruled clocked too, so the")
    print("      ruled figure is %d." % img_bytes(write_actions(4, RULED_PER_BYTE)))
    print("    * ⛔ NO RTL UNTIL C IS RE-MEASURED. See the plan printed below.")
    print()
    rc_p = check_premise(root)
    print()
    print("  THE C RE-MEASUREMENT PLAN (gates the build, per the ruling)")
    print("    1. Build the clocked SHIFT/SHIFTIN behind the existing")
    print("       `l_clkpin`-real condition, change no header field.")
    print("    2. `test/run_csat.py` on CLOCKED programs -- the arm that")
    print("       matters is a lane whose actions are re-dispatched, because a")
    print("       re-dispatched action needs no store read and a shortened")
    print("       writeback is what would move the spacing.")
    print("    3. ⛔ MAX inter-dispatch spacing per OPCODE, not the mean. A mean")
    print("       hides the one opcode that got faster, and the margin rests on")
    print("       the worst case, not the average one.")
    print("    4. Verdict, fixed in advance:")
    print("         spacing  < 3  -> safe; KEEP CHARGING 3 (do not re-quote")
    print("                          downward off a measurement taken to")
    print("                          check a bound)")
    print("         spacing == 3  -> unchanged, proceed")
    print("         spacing  > 3  -> FORBIDDEN. Stop and re-quote every")
    print("                          published margin that rests on C = 3.")
    print("    5. ⛔ THE PREMISE BEFORE THE CONSEQUENT: confirm Theorem 3 and")
    print("       `J_LANE_PROOF` read 'AT MOST one refill per dispatch', not")
    print("       'exactly one'. A clocked SHIFT re-dispatches WITHOUT a refill,")
    print("       so 'exactly one' is false under the new scheme and every")
    print("       bound derived from it would be measuring a premise that no")
    print("       longer holds.")
    print("    6. Then re-run `gate_j_proof_anchors`, the D* sweep and per-lane")
    print("       J; re-certify with sigrok (mutant: phase not alternating =>")
    print("       the foreign decoder must FAIL).")
    print("    7. No Lean lane exists yet. When one starts, the 'at most one")
    print("       refill per dispatch' phrasing is the note it inherits.")
    return rc_p


if __name__ == "__main__":
    sys.exit(main())
