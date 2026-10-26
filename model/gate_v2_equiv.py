"""THE v1 == v2 EQUIVALENCE GATE (Wilson, v2 step 2 item 5).

WHAT IT CLAIMS. Every v1 image runs the SAME on v2 as on v1 -- the same
dispatches (lane and DECODED fields) and the same output pins, cycle for cycle
from the engine's start -- and v2's own load is what its spec says.

HOW. One bench, `test/tb_equiv.v`, compiled against the v1-lock RTL (read from
git, never checked out) and against this tree's. Each of the 41 v1-lock images
runs on v1 as its v1-lock bytes and on v2 as the tracked v2 image, which must
equal `test/v1_translate.translate(v1)` byte for byte. Cycles are counted from
reset, so free-running counters (the status serialiser) are compared too.

⛔⛔ THE OFFSET IS DERIVED, NEVER SEARCHED. v2's store is bigger, so its load
is longer by (pe_isa.STORE_BYTES - v1 STORE_BYTES) writes; the v1 run holds
PROG that much longer:  D = (512 - 256) x LOAD_CYC_PER_BYTE, the bench's own
loader constant, read from `test/tb_equiv.v` (one place). A fitted offset
could hide drift. MUST-FIRE: D - 1 and D + 1 are RED on every image.

THE LOAD SECTION is a spec of v2, not "v1 differs plausibly": STORE_BYTES
loaded; the magic at HDR_REGION; a cleared magic REFUSED (cfg_err, the engine
never starts) -- and under `M_NO_MAGIC` (the build that ignores the magic) that
refusal check goes RED, so this gate is M_NO_MAGIC's killer; a 256-byte load
never starts the engine (R3); v2's start cycle == v1's + D.

MUST-FIRES on the encoding (each must make EVERY image whose bytes it changes
differ): a field shifted one bit (delay << 1), two opcodes swapped (LEVEL and
SHIFT), every header base one word off. And `falloff.hex` (store_probe: a lane
with no terminating REARM, which reaches the filler) is in the set.

POSITIVE TOKEN: `GATE v2-equiv: PASSED`.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "test")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from toolchain import banner, tool      # noqa: E402
import pe_isa as I                      # noqa: E402
import sim_run                          # noqa: E402
import v1_translate as T                # noqa: E402

V1REV = "v1-lock"
BENCH = "test/tb_equiv.v"
RTL = ["src/pe_engine.v", "src/pe_store.v", "src/project.v"]
NCYC = 12000          # cycles compared after the start, per image
NCYC_MF = 6000        # ... per must-fire run
GEN = "gate_v2_equiv"  # its scratch images' registered generator (sim_run)


def git(*args):
    r = subprocess.run(["git"] + list(args), cwd=ROOT, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args), r.stderr.decode()[:200]))
    return r.stdout


def load_cyc_per_byte():
    with open(os.path.join(ROOT, BENCH), encoding="utf-8") as fh:
        m = re.search(r"localparam integer LOAD_CYC_PER_BYTE = (\d+);", fh.read())
    if not m:
        raise RuntimeError("%s declares no LOAD_CYC_PER_BYTE" % BENCH)
    return int(m.group(1))


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def build(out, srcs, defines=()):
    r = run([tool("iverilog"), "-g2012", "-I", ROOT, "-o", out, "-s", "tb_equiv"]
            + ["-D%s" % d for d in defines] + [BENCH] + srcs)
    if r.returncode != 0:
        raise RuntimeError("build %s failed: %s" % (out, (r.stdout + r.stderr)[-400:]))


def write_hex(path, img, register=False):
    with open(path, "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join("%02x" % b for b in img) + "\n")
    if register:
        sim_run.scratch_image(GEN, path)
    return path


def sim(vvp, img, nbytes, progdly=0, ncyc=NCYC, lookup=None):
    """-> {start, cfg_err, started, recs [(kind, cyc, rest)], fails, cpb}.
    `lookup`: the images the A2 lookup is asked about (a v1 run names its v2
    twin: the same program, so the same bound)."""
    args = [vvp, "+IMG=%s" % img, "+NBYTES=%d" % nbytes, "+PROGDLY=%d" % progdly,
            "+NCYC=%d" % ncyc]
    r = run(sim_run.vvp(args, images=lookup if lookup is not None else [img]))
    out = r.stdout + r.stderr
    d = {"start": None, "cfg_err": None, "started": None, "recs": [],
         "fails": [], "cpb": None, "raw": out}
    for ln in out.splitlines():
        t = ln.split()
        if not t:
            continue
        if t[0] in ("D", "P") and len(t) > 2:
            d["recs"].append((t[0], int(t[1]), " ".join(t[2:])))
        elif t[0] == "S" and len(t) == 2:
            d["start"] = int(t[1])
        elif t[0] == "END":
            m = re.search(r"cfg_err=(\d) started=(\d)", ln)
            if m:
                d["cfg_err"], d["started"] = int(m.group(1)), int(m.group(2))
        elif t[0] == "LOAD_CYC_PER_BYTE":
            d["cpb"] = int(t[1])
        if "*** FAIL" in ln and "runstart.vh" not in ln:
            d["fails"].append(ln.strip())
    return d


def after(d, s):
    return [x for x in d["recs"] if x[1] >= s]


def same(a, b):
    """v1 run `a`, v2 run `b`: equal start, equal records from it on."""
    if a["start"] is None or b["start"] is None:
        return a["started"] == b["started"] and a["cfg_err"] == b["cfg_err"]
    return a["start"] == b["start"] and after(a, b["start"]) == after(b, b["start"])


def v1_falloff(tmp):
    """falloff.hex as v1-lock's own store_probe builds it (v1's encoder)."""
    d = os.path.join(tmp, "v1py")
    os.makedirs(d)
    # its scripts AND the shipped images it pads, all as v1-lock has them
    files = ["store_probe.py", "pe_isa.py"] + [
        os.path.basename(p) for p in
        git("ls-tree", "-r", "--name-only", V1REV, "test").decode().split()
        if p.endswith(".hex")]
    for f in files:
        with open(os.path.join(d, f), "wb") as fh:
            fh.write(git("show", "%s:test/%s" % (V1REV, f)))
    out = os.path.join(tmp, "v1probe")
    r = run([sys.executable, os.path.join(d, "store_probe.py"), out])
    if r.returncode != 0:
        raise RuntimeError("v1 store_probe failed: %s" % (r.stdout + r.stderr)[-300:])
    with open(os.path.join(out, "falloff.hex"), encoding="ascii") as fh:
        return bytes(int(w, 16) for w in fh.read().split())


def main() -> int:
    print()
    print("=" * 78)
    print("  v2-EQUIV -- every v1 image runs the same on v2, from run start")
    print("=" * 78)
    banner("iverilog", "vvp")
    V1 = T.v1()
    cpb = load_cyc_per_byte()
    D = (I.STORE_BYTES - V1.STORE_BYTES) * cpb
    print("  offset D = (%d - %d) x %d (tb_equiv's LOAD_CYC_PER_BYTE) = %d -- DERIVED"
          % (I.STORE_BYTES, V1.STORE_BYTES, cpb, D))
    probs = []
    tmp = tempfile.mkdtemp(prefix="pe_v2equiv_")
    try:
        v1src = []
        for f in RTL:
            p = os.path.join(tmp, "v1_" + os.path.basename(f))
            with open(p, "wb") as fh:
                fh.write(git("show", "%s:%s" % (V1REV, f)))
            v1src.append(p)
        vv1, vv2, vvm = (os.path.join(tmp, n) for n in ("v1.vvp", "v2.vvp", "nomagic.vvp"))
        build(vv1, v1src)
        build(vv2, RTL)
        build(vvm, RTL, defines=["M_NO_MAGIC"])

        # ---- the image set: 41 v1-lock images + falloff ------------------
        names = sorted(os.path.basename(p) for p in
                       git("ls-tree", "-r", "--name-only", V1REV, "test")
                       .decode().split() if p.endswith(".hex"))
        cases = []      # (name, v1 bytes, v1 path, v2 path, v2 lookup path)
        for n in names:
            b1 = git("show", "%s:test/%s" % (V1REV, n))
            img1 = bytes(int(w, 16) for w in b1.decode("ascii").split())
            p2 = os.path.join(ROOT, "test", n)
            if not os.path.isfile(p2):
                probs.append("%s: no v2 image in test/" % n)
                continue
            with open(p2, encoding="ascii") as fh:
                img2 = bytes(int(w, 16) for w in fh.read().split())
            if img2 != T.translate(img1):
                probs.append("%s: the tracked v2 image is NOT translate(v1)" % n)
                continue
            cases.append((n, img1, write_hex(os.path.join(tmp, "v1_" + n), img1),
                          p2, p2))
        f1 = v1_falloff(tmp)
        f2 = write_hex(os.path.join(tmp, "v2eq_falloff.hex"), T.translate(f1),
                       register=True)
        cases.append(("falloff.hex (store_probe)", f1,
                      write_hex(os.path.join(tmp, "v1_falloff.hex"), f1), f2, f2))

        # ---- 1. EQUIVALENCE at the derived offset --------------------------
        print()
        print("  --- 1. v1 (PROG + %d) vs v2, from the engine start ---" % D)
        runs = {}
        for n, img1, p1, p2, lk in cases:
            a = sim(vv1, p1, V1.STORE_BYTES, D, lookup=[p1, lk])
            b = sim(vv2, p2, I.STORE_BYTES)
            runs[n] = (a, b)
            ok = same(a, b) and a["fails"] == b["fails"]
            nrec = len(after(b, b["start"])) if b["start"] is not None else 0
            print("    %-28s start v1 %-5s v2 %-5s  %5d records  %s"
                  % (n, a["start"], b["start"], nrec,
                     "IDENTICAL" if ok else "*** DIFFER"))
            if not ok:
                probs.append("%s: v1 and v2 differ at the derived offset" % n)
            if b["cpb"] != cpb:
                probs.append("%s: the bench ran LOAD_CYC_PER_BYTE %s, the gate "
                             "derived with %d" % (n, b["cpb"], cpb))
        live = [n for n, (a, b) in runs.items()
                if b["start"] is not None and after(b, b["start"])]
        print("    %d of %d images identical; %d started and recorded"
              % (sum(1 for n in runs if same(*runs[n]) and runs[n][0]["fails"]
                     == runs[n][1]["fails"]), len(runs), len(live)))

        # ---- 2. the offset must-fire: D - 1 and D + 1 ----------------------
        print()
        print("  --- 2. must-fire: the offset one cycle off ---")
        for dd in (D - 1, D + 1):
            red = 0
            for n, img1, p1, p2, lk in cases:
                if n not in live:
                    continue
                a = sim(vv1, p1, V1.STORE_BYTES, dd, ncyc=NCYC_MF, lookup=[p1, lk])
                red += not same(a, runs[n][1])
            ok = red == len(live)
            print("    offset %d: %d of %d images RED  %s"
                  % (dd, red, len(live), "ok" if ok else "*** MISSED"))
            if not ok:
                probs.append("offset %d left %d image(s) equal" % (dd, len(live) - red))

        # ---- 3. the encoding must-fires ------------------------------------
        print()
        print("  --- 3. must-fire: a wrong translation is RED ---")
        mask = (1 << dict(V1.ACT_FIELDS)["delay"]) - 1

        def shift(f):
            f["delay"] = (f["delay"] << 1) & mask
            return f

        def swap(f):
            f["op"] = {I.OP_LEVEL: I.OP_SHIFT, I.OP_SHIFT: I.OP_LEVEL}.get(f["op"], f["op"])
            return f

        for what, mk in (("a field shifted one bit (delay << 1)",
                          lambda b: T.translate(b, field_map=shift)),
                         ("two opcodes swapped (LEVEL <-> SHIFT)",
                          lambda b: T.translate(b, field_map=swap)),
                         ("every header base one word off",
                          lambda b: T.translate(b, base_off=1))):
            red = tried = 0
            for i, (n, img1, p1, p2, lk) in enumerate(cases):
                if n not in live:
                    continue
                try:
                    bad = mk(img1)
                except ValueError:
                    tried += 1          # the encoder refuses it: red by refusal
                    red += 1
                    continue
                if bad == T.translate(img1):
                    continue            # this image has nothing to mutate
                pm = write_hex(os.path.join(tmp, "v2eq_mf%d.hex" % i), bad,
                               register=True)
                b = sim(vv2, pm, I.STORE_BYTES, ncyc=NCYC_MF)
                tried += 1
                red += not same(runs[n][0], b)
            ok = tried > 0 and red == tried
            print("    %-40s %d of %d images RED  %s"
                  % (what, red, tried, "ok" if ok else "*** MISSED"))
            if not ok:
                probs.append("must-fire %r: %d of %d red" % (what, red, tried))

        # ---- 4. THE LOAD SECTION: a spec of v2 -----------------------------
        print()
        print("  --- 4. the load section (v2's own spec) ---")
        sm = next(c for c in cases if c[0] == "smoke_image.hex")
        a0 = sim(vv1, sm[2], V1.STORE_BYTES, 0, ncyc=NCYC_MF, lookup=[sm[2], sm[4]])
        b0 = runs["smoke_image.hex"][1]

        def say(ok, what):
            print("    %-62s %s" % (what, "ok" if ok else "*** FAIL"))
            if not ok:
                probs.append("load section: " + what)

        say(b0["started"] == 1, "a %d-byte load starts the engine" % I.STORE_BYTES)
        with open(sm[3], encoding="ascii") as fh:
            img2 = bytearray(int(w, 16) for w in fh.read().split())
        say(bytes(img2[I.HDR_REGION:I.HDR_REGION + len(I.MAGIC)]) == I.MAGIC,
            "the magic %r sits at bytes %d..%d" % (I.MAGIC, I.HDR_REGION,
                                                  I.HDR_REGION + len(I.MAGIC) - 1))
        say(a0["start"] is not None and b0["start"] == a0["start"] + D,
            "v2's start cycle (%s) == v1's (%s) + D" % (b0["start"], a0["start"]))
        nm = bytearray(img2)
        nm[I.HDR_REGION:I.HDR_REGION + len(I.MAGIC)] = bytes(len(I.MAGIC))
        pnm = write_hex(os.path.join(tmp, "v2eq_nomagic.hex"), bytes(nm), register=True)
        r = sim(vv2, pnm, I.STORE_BYTES, ncyc=NCYC_MF)
        refused = r["started"] == 0 and r["cfg_err"] == 1
        say(refused, "a cleared magic is REFUSED: cfg_err=%s, started=%s"
            % (r["cfg_err"], r["started"]))
        r = sim(vv2, sm[3], len(img2) // 2, ncyc=NCYC_MF)
        say(r["started"] == 0, "a %d-byte load never starts the engine (R3): started=%s"
            % (len(img2) // 2, r["started"]))
        # M_NO_MAGIC: the build that ignores the magic must turn the refusal red
        r = sim(vvm, pnm, I.STORE_BYTES, ncyc=NCYC_MF)
        killed = not (r["started"] == 0 and r["cfg_err"] == 1)
        print("    must-fire M_NO_MAGIC: the cleared-magic refusal goes RED %s"
              % ("ok -- killed (started=%s, cfg_err=%s)" % (r["started"], r["cfg_err"])
                 if killed else "*** MISSED -- the mutant survives"))
        if not killed:
            probs.append("M_NO_MAGIC survives the refusal check")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    for p in probs:
        print("  *** %s" % p)
    print("  GATE v2-equiv: %s" % ("FAILED" if probs else "PASSED"))
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())
