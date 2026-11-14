"""gen_cert_constants -- the CERTIFIED entries of lean/JLane/proof_constants.json, generated.

Wilson 11-14 (ruling 2): the co-resident spacing is what the certificate requires, never typed.
This runs model/lane_cert.py on the USB program (test/usbdev.py, scheduler (b')) and writes
`usb_other_R` -- the response bound the other lanes get with that program co-resident
(RespSpan.wb_close_span) -- into proof_constants.json. proof_constants.py derives
coresident_usb = usb_other_R + pending_slack + br1_budget from it; Lean pins both (Params.lean)
and gate_lean_build compares; gate_lane_cert checks the stored value is the current one.

Usage: python model/gen_cert_constants.py            (writes)
       python model/gen_cert_constants.py --check    (exit 1 if stale)
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "test")]
import lane_cert as LC  # noqa: E402
import proof_constants as PC  # noqa: E402

CERTIFIED = ("usb_other_R",)


def certified(img=None):
    """{key: value} from lane_cert's certificate on the USB program."""
    if img is None:
        import usbdev as V
        img = V.image()
    with contextlib.redirect_stdout(io.StringIO()):
        LC.full_report(img, "usbdev")
    got = dict(LC.full_report.last)
    missing = [c for c in CERTIFIED if c not in got]
    if missing:
        raise RuntimeError("lane_cert did not certify %s (no m <= 8 met the span rule?)" % missing)
    return {c: got[c] for c in CERTIFIED}


def main():
    with open(PC.PATH, encoding="utf-8") as fh:
        data = json.load(fh)
    if "--check" not in sys.argv and any(c not in data for c in CERTIFIED):
        # bootstrap: proof_constants.load needs the key to exist; the certified value does not
        # depend on it (lane_cert reads it only to compare), and it is overwritten below
        data.update({c: 0 for c in CERTIFIED if c not in data})
        with open(PC.PATH, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    want = certified()
    stale = {c: (data.get(c), v) for c, v in want.items() if data.get(c) != v}
    if "--check" in sys.argv:
        for c, (old, new) in stale.items():
            print("STALE %s: stored %s, certificate %s (run model/gen_cert_constants.py)"
                  % (c, old, new))
        print("certified constants %s" % ("current" if not stale else "STALE"))
        return 1 if stale else 0
    data.update(want)
    data["_certified"] = ("usb_other_R is CERTIFIED, not a primitive: written by "
                          "model/gen_cert_constants.py from lane_cert's certificate on "
                          "test/usbdev.py (RespSpan.wb_close_span, b'); gate_lane_cert checks it "
                          "is current. Wilson 11-14.")
    with open(PC.PATH, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print("wrote %s" % ", ".join("%s = %s" % kv for kv in want.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
