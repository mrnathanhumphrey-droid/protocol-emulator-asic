"""gate_cert_stamp -- UNCERTIFIED is a stamp, refusal is opt-in (Wilson 11-15).

Checks (static, seconds):
  S1 the ruling's must-fire entries, through pe_asm's REAL command line (a subprocess) and
     the compiler's back half (host/poset/compile.finish, the code compile_spec runs):
       a. a d = 12 program, no flag: assembles, exit 0, field = uncertified, reason present
          (in the CERT line and in the written `.cert.json`);
       b. the same program with --require-cert: nonzero exit, the reason printed, NOTHING
          written;
       c. a certified program with --require-cert: exit 0, field = certified;
       d. the compiler and the command line give identical output on all three (the same
          field; on b the same refusal reason).
     ⚠ the compiler's FRONT half (spec -> lowering) cannot produce a d = 12 program: the
       lowering spaces SPI at 20. The comparison runs the shared back half on the same
       images; run_poset_compile C1 covers the full compiler on its own slice.
  S2 the decode: the stamp of an assembled image equals compute_j on the lanes it was
     assembled from (pe_asm's assembling self-test programs, and the three above).
  S3 every `.cert.json` beside a universe image is that image's current stamp.
  S4 every IMAGE OF RECORD has a sidecar, written --require-cert, saying certified; the
     ones another agent's builder writes are LISTED as pending, not skipped silently.
  S5 the response bounds (Wilson 11-15): every image of record's unclocked SHIFT lanes have a
     certified R in model/branch_budget.json, and the stamp needs it -- with that R removed
     the stamp is uncertified, so a --require-cert build fails (must-fire M_CS_R_MISSING).
Must-fires (in-process, on scratch copies): a stale sidecar (S3), an image of record with no
sidecar (S4), and require() passing an uncertified stamp (S1b) each turn the gate red.
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(HERE, "a2"), os.path.join(ROOT, "test"),
           os.path.join(ROOT, "host", "poset")):
    if _p not in sys.path:
        sys.path.append(_p)
import cert_stamp as CS  # noqa: E402
import pe_asm  # noqa: E402

S = pe_asm

#: a certified program for S1c: clocked SHIFTs only (an unclocked SHIFT owes a certified R,
#: which a program outside the budget record does not have)
OK25 = ({0: [(S.OP_SHIFT, 8, 1, 25, 0), (S.OP_SHIFT, 8, 1, 25, 0), (S.OP_REARM, 0, 1, 25, 0)]},
        {0: (8, 9, 1, 25, 50, 75)})

D12 = ({0: [(S.OP_SHIFT, 8, 1, 12, 0), (S.OP_SHIFT, 8, 0, 12, 0), (S.OP_REARM, 0, 1, 12, 0)]},
       {0: (8, 9, 1, 12, 24, 36)})


def _prog_file(d, name, prog):
    lanes, headers = prog
    p = os.path.join(d, name + ".json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump({"lanes": {str(k): [list(a) for a in v] for k, v in lanes.items()},
                   "headers": {str(k): list(v) for k, v in headers.items()}}, fh)
    return p


def _cli(args):
    r = subprocess.run([sys.executable, os.path.join(HERE, "pe_asm.py")] + args,
                       capture_output=True, text=True, timeout=300)
    out = r.stdout
    cert = None
    for ln in out.splitlines():
        if ln.startswith("CERT "):
            cert = json.loads(ln[5:])
    refused = next((ln.split(": ", 1)[1] for ln in out.splitlines()
                    if ln.startswith("REFUSED (--require-cert): ")), None)
    return r.returncode, cert, refused, out + r.stderr


def _compiler(img, require):
    import compile as CC
    try:
        return CC.finish(img, require), None
    except CC.Refused as e:
        return None, str(e)


def s1(tmp, require_fn=None):
    probs = []
    progs = {"d12": D12, "ok": OK25}
    for name, prog in progs.items():
        img = S.assemble(*prog)
        for flag in (False, True):
            if name == "ok" and not flag:
                continue
            out = os.path.join(tmp, "%s_%d.hex" % (name, flag))
            rc, cert, refused, txt = _cli(["--program", _prog_file(tmp, name, prog), "--out", out]
                                          + (["--require-cert"] if flag else []))
            st_c, ref_c = _compiler(img, flag)
            if require_fn is not None and flag:          # must-fire: a require() that passes
                st_c, ref_c = require_fn(CS.stamp(img)), None
            tag = "%s%s" % (name, " --require-cert" if flag else "")
            if name == "d12" and not flag:               # a
                side = CS.read(out)
                if rc != 0 or not cert or cert["status"] != "uncertified" or not cert["reason"]:
                    probs.append("S1a %s: rc %d, field %s" % (tag, rc, cert))
                if side is None or side.get("status") != "uncertified" or not side.get("reason"):
                    probs.append("S1a %s: sidecar %s" % (tag, side))
            if name == "d12" and flag:                   # b
                if rc == 0 or not refused or "compute_j refuses" not in refused:
                    probs.append("S1b %s: rc %d, refusal %r" % (tag, rc, refused))
                if os.path.exists(out) or os.path.exists(CS.sidecar(out)):
                    probs.append("S1b %s: an image was written" % tag)
            if name == "ok":                              # c
                if rc != 0 or not cert or cert["status"] != "certified":
                    probs.append("S1c %s: rc %d, field %s" % (tag, rc, cert))
            # d: identical
            if (cert, refused) != (st_c, ref_c):
                probs.append("S1d %s: command line %s / %r, compiler %s / %r"
                             % (tag, cert, refused, st_c, ref_c))
    return probs


def s2():
    probs, n = [], 0
    progs = [("D12", D12), ("OK25", OK25)] + [(f, getattr(S, f)()) for f in dir(S) if f.startswith("_demo_")]
    for name, prog in progs:
        lanes, headers = prog[:2]
        try:
            img = S.assemble(lanes, headers)
        except S.Reject:
            continue                                      # a refusal demo: never an image
        n += 1
        got = CS.stamp_lanes(CS.image_lanes(img))       # the compute_j part of the stamp
        if got != CS.stamp_lanes(lanes):
            probs.append("S2 %s: image's compute_j %s, lanes %s" % (name, got,
                                                                   CS.stamp_lanes(lanes)))
    if n < 3:
        probs.append("S2 only %d programs assembled" % n)
    return probs, n


def s3(paths, read=CS.read):
    probs, n = [], 0
    for name, path in sorted(paths.items()):
        side = read(path)
        if side is None:
            continue
        n += 1
        st = CS.stamp(CS.read_hex(path))
        if {k: side.get(k) for k in st} != st:
            probs.append("S3 %s: sidecar %s, image stamp %s" % (name, side, st))
    return probs, n


def s4(read=CS.read):
    probs = []
    for rel in CS.IMAGES_OF_RECORD:
        side = read(os.path.join(ROOT, rel))
        if side is None:
            probs.append("S4 %s: image of record has no .cert.json" % rel)
        elif side.get("status") != "certified" or not side.get("require_cert"):
            probs.append("S4 %s: sidecar %s (want certified, written --require-cert)" % (rel, side))
    return probs


def s5(drop_r=False):
    """[problem]; drop_r: the must-fire -- the record's R removed must uncertify the image"""
    probs = []
    for rel in CS.IMAGES_OF_RECORD:
        img = CS.read_hex(os.path.join(ROOT, rel))
        e = CS.budget_entry(img)
        sl = CS.unclocked_shift_lanes(img)
        if e is None:
            probs.append("S5 %s: no budget record" % rel)
            continue
        if drop_r:
            e = copy.deepcopy(e)
            for ln in sl:
                e["lanes"][str(ln)]["R"] = None
        miss = [ln for ln in sl if e["lanes"].get(str(ln), {}).get("R") is None]
        st = CS.stamp(img, budget=e)
        if miss and st["status"] == "certified":
            probs.append("S5 %s: lane(s) %s have no certified R, stamp still certified" % (rel, miss))
        if miss:
            probs.append("S5 %s: unclocked SHIFT lane(s) %s owe a certified R" % (rel, miss))
    return probs


def main():
    import image_universe as U
    paths = U.default().paths
    probs = []
    with tempfile.TemporaryDirectory() as tmp:
        p1 = s1(tmp)
    p2, n2 = s2()
    p3, n3 = s3(paths)
    p4 = s4()
    p5 = s5()
    probs = p1 + p2 + p3 + p4 + p5
    print("S1 must-fire entries a-d (command line vs compiler): %s" % ("ok" if not p1 else "FAIL"))
    print("S2 decode round-trip on %d assembled programs: %s" % (n2, "ok" if not p2 else "FAIL"))
    print("S3 %d sidecars current: %s" % (n3, "ok" if not p3 else "FAIL"))
    print("S4 %d image(s) of record certified: %s" % (len(CS.IMAGES_OF_RECORD),
                                                   "ok" if not p4 else "FAIL"))
    print("S5 response bounds R on the images of record's unclocked SHIFT lanes: %s"
          % ("ok" if not p5 else "FAIL"))
    for name, why in CS.IMAGES_OF_RECORD_PENDING:
        print("   pending: %s -- %s" % (name, why))
    for p in probs:
        print("  ***", p)

    # must-fires
    mf = []
    rel = CS.IMAGES_OF_RECORD[0]
    real = CS.read(os.path.join(ROOT, rel))
    if real is not None:
        bad = copy.deepcopy(real)
        bad["status"] = "uncertified" if bad["status"] == "certified" else "certified"
        stale = lambda path: bad if path.endswith(os.path.basename(rel)) else CS.read(path)
        mf.append(("M_CS_STALE_SIDECAR", bool(s3({"x": os.path.join(ROOT, rel)}, stale)[0])))
    else:
        mf.append(("M_CS_STALE_SIDECAR", False))
    mf.append(("M_CS_RECORD_NO_SIDECAR", bool(s4(lambda path: None))))
    mf.append(("M_CS_R_MISSING", bool(s5(drop_r=True))))
    # Wilson 11-15 item 8: an arm_margin below 0 uncertifies (planted on the real usbdev_fpga
    # record); the control at margin 0 -- writeback AT the deadline, legal by Armed.lean's
    # hedge -- must stay certified, or the planted red proves nothing
    uimg = CS.read_hex(os.path.join(ROOT, "fpga/images/usbdev_fpga.hex"))
    ue = CS.budget_entry(uimg)
    def arm_stamp(m):
        e2 = copy.deepcopy(ue)
        for v in e2["lanes"].values():
            if v.get("arm_margin") is not None:
                v["arm_margin"] = m
        return CS.stamp(uimg, budget=e2)["status"]
    ctl = ue is not None and arm_stamp(0) == "certified"
    if not ctl:
        print("  *** control: usbdev_fpga at arm_margin 0 is not certified")
        probs.append("M_CS_ARM_LATE control")
    mf.append(("M_CS_ARM_LATE", ctl and arm_stamp(-1) == "uncertified"))
    with tempfile.TemporaryDirectory() as tmp:
        mf.append(("M_CS_REQUIRE_PASSES", bool(s1(tmp, require_fn=lambda st: st))))
    for name, red in mf:
        print("  must-fire %-24s %s" % (name, "RED (killed)" if red else "*** SURVIVED"))
    probs += [n for n, red in mf if not red]
    print("GATE cert_stamp: %s" % ("PASSED" if not probs else "FAILED (%d)" % len(probs)))
    return 1 if probs else 0


if __name__ == "__main__":
    raise SystemExit(main())
