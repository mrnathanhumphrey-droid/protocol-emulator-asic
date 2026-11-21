"""cert_stamp -- an image's certification STAMP: certified, or uncertified with the reason
(Wilson 11-15: "UNCERTIFIED is a stamp, refusal is opt-in").

  1. Default, every path: an image whose program pe_asm.compute_j refuses (d_min below
     D* = 20, an inadmissible set, a zero spacing) is still BUILT, and stamped
         UNCERTIFIED: compute_j refuses: <compute_j's reason>
     -- the d = 12 test images assemble and run as uncertified stress tests.
  2. Opt-in refusal: `--require-cert` (here `require()`) turns an uncertified stamp into a
     failure with the same reason and a nonzero exit. Every image that ships or goes on
     the board is built with it (IMAGES_OF_RECORD).
  3. Machine-readable: the stamp is a FIELD -- `stamp(img)` returns it, `write()` puts it
     beside the image as `<image>.cert.json` -- not a printed line. Without
     --require-cert the exit code stays 0, so the field is the only signal and gates
     read it (`read()`; `gate_cert_stamp.py` checks every sidecar is current).

ONE FUNCTION OF THE IMAGE. The stamp is computed from the image's bytes, never from a
builder's private lanes, so the compiler, pe_asm's command line and every gate get the same
field for the same image. `image_lanes` decodes each lane's words back into the
`(op, pin, level, delay, q)` tuples compute_j reads (the inverse of pe_asm.assemble: a
LOOP's spacing is its wait W = count:pinb, every other word's is its delay field), from
the lane's base to its first REARM / LOOP or the next lane's base. Lanes parked on the
shared REARM are left out, as pe_asm.assemble leaves them out of `lanes`. The compiler
cross-checks the decode against the lanes the lowering actually handed pe_asm.assemble
(run_poset_compile C1), and the gate round-trips every pe_asm self-test program.

The image bytes are never changed: the chip loads all of them, and every image's sha is a
tracked artefact.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(HERE, "a2"), os.path.join(ROOT, "test")):
    if _p not in sys.path:
        sys.path.append(_p)
import pe_isa as I  # noqa: E402

SUFFIX = ".cert.json"

#: Images that ship or go on the board: built with --require-cert (ruling 2). Paths are
#: repo-relative; each has a sidecar that must say "certified".
IMAGES_OF_RECORD = (
    "fpga/images/usbdev_fpga.hex",
    # Wilson 11-15 item 7 (agent 1): `uart_rx.py <out> board` writes it --require-cert
    "fpga/images/uart_rx_board.hex",
)
#: Images of record built by another agent's builder; their builders take --require-cert
#: when that agent wires it (listed so the gate names them, not silently skipped).
IMAGES_OF_RECORD_PENDING = (
    ("usbdev_dev.hex", "test/run_usbaddr.py (agent 1): pass --require-cert to its writer"),
)


#: must-fire switch (gate_cert_stamp M_CS_A2_IGNORED): the stamp ignores A2's verdict
A2_MUT = False
#: must-fire switch (gate_cert_stamp M_CS_SYMDEF_PAYLOAD): SYMDEF's payload read as its delay
SYMDEF_MUT = False


class Uncertified(Exception):
    """--require-cert on an uncertified image; str() is the stamp's reason."""


def _words(img, base):
    a = base
    while a + I.ACT_BYTES <= min(len(img), I.STORE_BYTES):
        yield a, I._unpack(I.ACT_FIELDS, img[a:a + I.ACT_BYTES], I.ACT_BYTES)
        a += I.ACT_BYTES


def _tuple(x, t=None):
    if x["op"] == I.OP_SYMDEF and t is not None and not SYMDEF_MUT:
        # ⛔ SYMDEF's delay field is CONFIG PAYLOAD; the RTL advances the lane by the header
        # period `t` (`a_dly_sg`), and A2 prices it so (program_a2.lanes_of, 08fdf55) -- found
        # 11-20: the coverage sweep's symbol-generator images read "delay 0, a zero release
        # spacing" here and were stamped uncertified while A2 certified them (B 0)
        return (x["op"], x["pin"], x["level"], t, x["q"])
    if x["op"] == I.OP_LOOP:
        return (x["op"], 0, 0, (x["count"] << I.PINB_W) | x["pinb"], x["q"])
    if x["op"] in I.BRANCH_OPS:
        # ⛔ a BRANCH's delay field is its TARGET (delay[6:0]); its spacing is the wait W
        # (count:pinb, pe_isa.branch_wait) -- found 11-15: run_branch_check's braw images read
        # "d_min = 6" (a target) and were stamped uncertified while A2 certified them
        return (x["op"], x["pin"], x["level"], I.branch_wait(x), x["q"])
    return (x["op"], x["pin"], x["level"], x["delay"], x["q"])


def image_lanes(img):
    """{lane: [(op, pin, level, delay, q)]} decoded from the image, as compute_j reads them:
    EVERY word reachable from the lane's base (proof_constants.lane_words: the next word, a
    branch's target, a FALLTHROUGH ARM's PC+2, sections after a mid-program REARM), in word
    order. ⛔ 57e96cf walked base -> first REARM and saw 13 of usbdev lane 0's 106 words; a
    straight-line pe_asm lane is the same walk either way (gate S2 round-trips them)."""
    import proof_constants as PC
    img = bytes(img)
    heads = {ln: I.read_header(img, ln)["base"] for ln in range(I.N_LANES)}
    # the shared park word: a base several lanes share whose word is a lone REARM
    parked = set()
    for b in set(heads.values()):
        sharers = [ln for ln, v in heads.items() if v == b]
        first = next(_words(img, b), (None, None))[1]
        if len(sharers) > 1 and first is not None and first["op"] == I.OP_REARM:
            parked.add(b)
    return {ln: [_tuple(x, I.read_header(img, ln)["t"]) for _w, x in PC.lane_words(img, ln, I)]
            for ln in range(I.N_LANES) if heads[ln] not in parked}


def stamp_lanes(lanes):
    """the stamp of a program given as pe_asm lanes (5- or 6-tuples)"""
    import pe_asm
    ln, _c = pe_asm.split_counts(lanes)
    try:
        d_min, j = pe_asm.compute_j(ln)
    except pe_asm.Reject as e:
        return {"status": "uncertified", "reason": "compute_j refuses: %s" % e,
                "d_min": None, "J": None}
    return {"status": "certified", "reason": "pe_asm.compute_j", "d_min": d_min, "J": j}


def unclocked_shift_lanes(img):
    """lanes with an UNCLOCKED SHIFT among their reachable words (program_a2.is_clocked's
    complement: a SHIFT that is not level-1 on a lane with a real clock pin)"""
    import proof_constants as PC
    out = []
    for ln, acts in image_lanes(img).items():
        h = I.read_header(bytes(img), ln)
        if any(a[0] == I.OP_SHIFT and not (h["clkpin"] < I.N_PINS and a[2] == 1) for a in acts):
            out.append(ln)
    return out


BUDGET = os.path.join(HERE, "branch_budget.json")


def budget_entry(img):
    """the image's entry in model/branch_budget.json (by sha), or None"""
    import program_a2 as P
    try:
        with open(BUDGET, encoding="utf-8") as fh:
            rec = json.load(fh).get("images", {})
    except OSError:
        return None
    sha = P.image_sha(I.full_store(bytes(img)))       # the record keys the full store
    return next((v for v in rec.values() if v.get("sha") == sha), None)


def stamp(img, budget=None):
    """THE FIELD: {'status': 'certified' | 'uncertified', 'reason', 'd_min', 'J'}.
    Certified needs BOTH:
      * pe_asm.compute_j accepts the image's lanes (the J floor);
      * A2's certificate exists (a finite B; Wilson 11-15: the stamp and A2 read ONE verdict) --
        the record's entry, or the same certificate live when the image has none;
      * every lane with an unclocked SHIFT has a CERTIFIED response bound R (Wilson 11-15:
        j1_ok needs R, so the bounds are owed before an image of record) -- read from the
        generated record model/branch_budget.json (`budget`: that entry, as the generator
        passes it while writing). An image with no record has no certified R."""
    st = stamp_lanes(image_lanes(img))
    if st["status"] != "certified":
        return st
    e = budget if budget is not None else budget_entry(img)
    if e is None:
        # no record entry: A2's certificate, live -- the record's own function (live_price)
        import branch_budget as BB
        e = BB.image_budget(bytes(img))
    # Wilson 11-15: ONE certificate, one verdict -- the stamp reads A2's (no finite B: uncertified)
    if e.get("B") is None and not A2_MUT:
        return dict(st, status="uncertified", reason="A2: %s" % e.get("reason"))
    # (kept on merge of ac9547d: A2's verdict above refuses a negative UART arming margin
    # since 7b4a6f1; this stays as the stamp's own check, as gate_cert_stamp M_CS_ARM_LATE
    # plants it on a record entry, not on A2)
    # ⛔ WILSON 11-15 (combined ruling, item 8): a lane that ARMS LATE -- the record's
    # arming premise margin (branch_budget arm_margin, deadline minus armed-by) below 0 --
    # cannot be certified: the edge can arrive before the ARM. An image of record that arms
    # late is fixed, not stamped (its builder writes --require-cert and is refused here).
    late_arm = sorted(((ln, (v or {}).get("arm_margin")) for ln, v in
                       ((e or {}).get("lanes") or {}).items()
                       if isinstance((v or {}).get("arm_margin"), int)
                       and v["arm_margin"] < 0), key=lambda kv: int(kv[0]))
    if late_arm:
        return dict(st, status="uncertified", reason=(
            "arms late: %s (the arming premise: armed by EOP + k must not pass the "
            "deadline; branch_budget arm_margin < 0 -- Wilson 11-15 item 8)"
            % "; ".join("lane %s arm_margin %d" % (ln, m) for ln, m in late_arm)))
    # ⛔ WILSON 11-15 (UART blocker ruling, item 1): 1.6a with the record's certified
    # lane lateness in J. pe_asm assembles at the proved J; a lane that fails only
    # with its lateness in is UNCERTIFIED here (a split theorem may take it off).
    late = [ln for ln, v in ((e or {}).get("lanes") or {}).items()
            if (v or {}).get("max_late")]
    if late:
        import program_a2 as P
        bad = sorted(((ln, v) for ln, v in P.queue_slot(img).items()
                      if not v["ok"]), key=lambda kv: int(kv[0]))
        if bad:
            return dict(st, status="uncertified", reason=(
                "1.6a queue check fails with the record's certified lane lateness in J: %s "
                "(J from the lane's certificate, program_a2.lane_j_obs; a split theorem for "
                "the late word would drop it -- Wilson 11-15)" % "; ".join(
                    "lane %s r %s > T %s" % (ln, v["r"], v["T"]) for ln, v in bad)))
    sl = unclocked_shift_lanes(img)
    if not sl:
        return st
    lanes = (e or {}).get("lanes") or {}
    miss = [ln for ln in sl
            if (lanes.get(str(ln)) or lanes.get(ln) or {}).get("R") is None]
    if miss:
        why = "the certificate has no R for it (%s)" % e.get("reason", "?")
        return dict(st, status="uncertified",
                    reason="unclocked SHIFT lane(s) %s: no certified response bound R -- %s"
                    % (",".join(map(str, miss)), why))
    return st


def line(st):
    """the field as one line (the compiler's cert J_floor, pe_asm's report)"""
    if st["status"] == "certified":
        return "certified: J %d at d_min %d (pe_asm.compute_j; R certified where owed)" % (
            st["J"], st["d_min"])
    return "UNCERTIFIED: %s" % st["reason"]


def require(st, what="image"):
    """--require-cert: raise Uncertified (same reason) unless the stamp is certified"""
    if st["status"] != "certified":
        raise Uncertified("%s: UNCERTIFIED: %s" % (what, st["reason"]))
    return st


def sidecar(path):
    return path + SUFFIX


def write(path, img, require_cert=False):
    """write `path` (the full store, pe_isa.write_image) and its stamp sidecar; with
    require_cert, an uncertified image raises Uncertified and NOTHING is written"""
    st = stamp(img)
    if require_cert:
        require(st, os.path.basename(path))
    full = I.write_image(path, img)
    rec = dict(st, image=os.path.basename(path), require_cert=bool(require_cert))
    with open(sidecar(path), "w", encoding="ascii", newline="\n") as fh:
        json.dump(rec, fh, indent=1, sort_keys=True)
        fh.write("\n")
    return full, st


def read(path):
    """the sidecar's field, or None if the image has none"""
    p = sidecar(path)
    if not os.path.exists(p):
        return None
    with open(p, encoding="ascii") as fh:
        return json.load(fh)


def read_hex(path):
    with open(path, encoding="ascii") as fh:
        return bytes(int(t, 16) for t in fh.read().split())
