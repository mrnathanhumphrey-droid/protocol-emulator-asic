"""THE v1 == v2 AT 50 MHz EQUIVALENCE GATE (Wilson, v2 step 2 item 5; 11-03).

SCOPE, AS IT PRINTS: translator + engine == v1 at 50 MHz, guard band aside.

WHAT IT CLAIMS: v1 == v2 AT 50 MHz. Every v1 image runs the SAME on v2 as on
v1 -- the same dispatches (lane and DECODED fields) and the same output pins,
cycle for cycle from the engine's start -- AT v1's CLOCK, and v2's own load is
what its spec says.

⛔⛔ AT 50 MHz, AND ONLY THERE (Wilson 11-03, option A). The claim is that the
translator plus the v2 engine reproduce v1 cycle for cycle, and that means
something only at v1's clock: v2's hold and stretch counts are DERIVED from
the clock (60 MHz on the chip), and its shipped images are assembled in real
time per target, so at 60 MHz neither the counts nor the bytes are v1's on
purpose. Both builds run at v1's clock -- read from v1-lock's own info.yaml,
never typed -- with the v2 dut given that period (the bench define
PE_EQUIV_V2_PERIOD, which never reaches synthesis: gate_clock_consistency).
⛔⛔ GUARD BAND ASIDE (Wilson 11-04). v1 ran UNBANDED counts and v2 adds a
21/20 guard band on purpose, so the v2 build here has the band OFF (tb_equiv's
`defparam dut.u_eng.BAND_NUM/BAND_DEN = 1`, under the same bench define).
MEASURED 11-04: band on, 27 of 42 identical, the 15 others moved by the band
alone; band off, 42 of 42. The band itself is checked where it lives --
gate_clock_consistency (engine == model/clock.py, and check 6: every synthesis
and canary config keeps it) and Hold.lean -- never by this gate.
The 60 MHz side is NOT this gate's: it is covered by model/gate_clock_cross.py
(the same programs at both targets, matched in real time) and by the
per-target assembler checks (pe_asm's refusals at each target's clock).

HOW. One bench, `test/tb_equiv.v`, compiled against the v1-lock RTL (read from
git, never checked out) and against this tree's. Each of the 41 v1-lock images
runs on v1 as its v1-lock bytes and on v2 as `test/v1_translate.translate(v1)`,
BUILT IN SCRATCH. (The tracked v2 images were translate(v1) once; those the
60 MHz move re-derived are pinned by test/artefacts.sha256 and their own
runners, so whether each still equals translate(v1) is REPORTED, not judged.)
Cycles are counted from reset, so free-running counters (the status
serialiser) are compared too.

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

⛔⛔ THE SCOPE IS THE ADMISSIBLE SET (Wilson 11-14). An ADMISSIBLE image (every
image not in model/nonadmissible.NON_ADMISSIBLE) is JUDGED and must be
bit-exact. A NON-ADMISSIBLE image is still RUN, and reported with its first
differing record, labelled "outside the admissible set; v2's guarantees don't
apply" -- never judged. MUST-FIRE: smoke_image (PINNED, Wilson 11-14) with a
planted difference -- the level of lane 0's first-writeback LEVEL word flipped
in its v2 translation -- turns the gate red; a reach check proves the clean run
dispatches that word and writes back after it, and that the judged difference
lands at or before that writeback, else "difference outside the run" is red.

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
import nonadmissible as NA              # noqa: E402
import pe_isa as I                      # noqa: E402
import sim_run                          # noqa: E402
import v1_translate as T                # noqa: E402

V1REV = "v1-lock"
V2_PERIOD_DEFINE = "PE_EQUIV_V2_PERIOD"     # tb_equiv.v's bench-only define
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


def v1_clock_hz():
    """v1's clock, from v1-lock's own info.yaml -- never typed."""
    m = re.search(r"^\s*clock_hz:\s*(\d+)", git("show", "%s:info.yaml" % V1REV)
                  .decode("utf-8"), re.M)
    if not m:
        raise RuntimeError("%s:info.yaml declares no clock_hz" % V1REV)
    return int(m.group(1))


def build(out, srcs, defines=(), ps=None):
    clk = ["-DPE_CLK_PS=%d" % ps] if ps else []
    r = run([tool("iverilog"), "-g2012", "-I", ROOT, "-o", out, "-s", "tb_equiv"]
            + clk + ["-D%s" % d for d in defines] + [BENCH] + srcs)
    if r.returncode != 0:
        raise RuntimeError("build %s failed: %s" % (out, (r.stdout + r.stderr)[-400:]))


def write_hex(path, img, register=False):
    with open(path, "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join("%02x" % b for b in img) + "\n")
    if register:
        sim_run.scratch_image(GEN, path)
    return path


GEN_V1 = "gate_v2_equiv_v1"   # the v1 side's registered generator (sim_run; Wilson 11-21)


def write_v1(path, img, source):
    """A v1-lock image for the v1 engine, written WITH provenance (Wilson 11-21: every image
    outside the universe, clocked or not): the commit V1REV resolves to now and `source`."""
    write_hex(path, img)
    c = sim_run.pin_commit(V1REV)
    if c is None:
        raise RuntimeError("cannot resolve %s to a commit" % V1REV)
    sim_run.scratch_image(GEN_V1, path, meta={"commit": c, "source": source})
    return path


def sim(vvp, img, nbytes, progdly=0, ncyc=NCYC, lookup=None, quiescent=False):
    """-> {start, cfg_err, started, recs [(kind, cyc, rest)], fails, cpb}.
    `lookup`: the images the A2 lookup is asked about (a v1 run names its v2
    twin: the same program, so the same bound). `quiescent`: the image is on
    QUIESCENT (declared by name) -- the bench gets +QUIESCENT."""
    args = [vvp, "+IMG=%s" % img, "+NBYTES=%d" % nbytes, "+PROGDLY=%d" % progdly,
            "+NCYC=%d" % ncyc] + (["+QUIESCENT"] if quiescent else [])
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


#: the label a non-admissible image's report carries (Wilson 11-14, verbatim)
OUTSIDE = "outside the admissible set; v2's guarantees don't apply"


def first_diff(a, b):
    """the first point where v1 run `a` and v2 run `b` part, as text"""
    if a["start"] != b["start"]:
        return "start cycle v1 %s, v2 %s" % (a["start"], b["start"])
    if a["start"] is None:
        return "cfg_err/started v1 %s/%s, v2 %s/%s" % (a["cfg_err"], a["started"],
                                                       b["cfg_err"], b["started"])
    ra, rb = after(a, b["start"]), after(b, b["start"])
    for k in range(max(len(ra), len(rb))):
        x = ra[k] if k < len(ra) else None
        y = rb[k] if k < len(rb) else None
        if x != y:
            return "record %d: v1 %s | v2 %s" % (k, " ".join(map(str, x)) if x else "(none)",
                                                 " ".join(map(str, y)) if y else "(none)")
    if a["fails"] != b["fails"]:
        fa = next((f for f in a["fails"] if f not in b["fails"]), None)
        fb = next((f for f in b["fails"] if f not in a["fails"]), None)
        return "monitor lines: v1 %s | v2 %s" % (fa or "(none)", fb or "(none)")
    return ""


#: ⛔ THE ONE DECLARED DIFFERENCE (Wilson 11-19, 6206743): v1 -- and v2 before that
#: commit -- carried `sticky_ovr_m <= sticky_ovr_m` as the LAST write of the engine's
#: block, which discarded the sticky set by a refusal in the same cycle. v2 now
#: reports it. These five refusal images, BY NAME, may differ from v1 in the sticky
#: bit of the status byte ONLY (uo_out bit 4: 6f -> 7f), and each MUST show it set
#: (the fix has to hold, not just be tolerated). Any other bit or byte differing on
#: them, or any other image differing, stays red. v1's erratum: V1_ERRATA.
STICKY_ERRATUM = ("ckdegen_image.hex", "ckdegen2_image.hex", "ckhold_at_image.hex",
                  "ckhold_under_image.hex", "tx_badclk_image.hex")
STICKY_BIT = 0x10                      # uo_out[4], the host status' sticky fault


def sticky_only(a, b):
    """(True, n) when v2 run `b` equals v1 run `a` except that P records' uo_out
    byte has STICKY_BIT set in v2 and clear in v1 (n such records, n >= 1);
    (False, why) otherwise."""
    if a["start"] is None or a["start"] != b["start"] or a["fails"] != b["fails"]:
        return False, "start / monitor lines differ: %s" % first_diff(a, b)
    ra, rb = after(a, b["start"]), after(b, b["start"])
    if len(ra) != len(rb):
        return False, "record counts differ (%d / %d)" % (len(ra), len(rb))
    n = 0
    for x, y in zip(ra, rb):
        if x == y:
            continue
        if x[0] != "P" or y[0] != "P" or x[1] != y[1]:
            return False, "a non-status record differs: v1 %s | v2 %s" % (x, y)
        tx, ty = x[2].split(), y[2].split()
        if tx[1:] != ty[1:]:
            return False, "a pin byte differs: v1 %s | v2 %s" % (x, y)
        u1, u2 = int(tx[0], 16), int(ty[0], 16)
        if u1 ^ u2 != STICKY_BIT or not u2 & STICKY_BIT:
            return False, "uo_out differs beyond the sticky bit: v1 %s | v2 %s" % (x, y)
        n += 1
    if n == 0:
        return False, "the sticky bit is NOT set in v2 -- 6206743's fix does not hold"
    return True, n


def judge(n, a, b):
    """(verdict, detail, problem or None) for one image's pair of runs. THE ONE
    JUDGE: section 1 and its must-fire both call it."""
    ok = same(a, b) and a["fails"] == b["fails"]
    base = n.split()[0]
    if base in NA.NON_ADMISSIBLE:
        return (("IDENTICAL (non-admissible, not judged)" if ok else
                 "DIFFER -- " + OUTSIDE), "" if ok else first_diff(a, b), None)
    if base in STICKY_ERRATUM:
        good, why = sticky_only(a, b)
        if good:
            return ("IDENTICAL but the sticky bit (6206743, declared; %d status "
                    "record(s) with it set)" % why), "", None
        return ("*** DIFFER", why, "%s: the declared sticky-bit difference does not "
                "hold -- %s" % (n, why))
    if ok:
        return "IDENTICAL", "", None
    return ("*** DIFFER", first_diff(a, b),
            "%s: v1 and v2 differ at the derived offset (ADMISSIBLE: must be "
            "bit-exact) -- %s" % (n, first_diff(a, b)))


#: the planted-difference must-fire's image (Wilson 11-14: pinned)
PLANT_IMAGE = "smoke_image.hex"

#: ⛔ QUIESCENT BY DECLARATION (Wilson 11-14), each by EXACT name: an
#: edge-paced image whose lanes wait on a peer edge -- this bench has no peer,
#: so it retires nothing by design. Run with +QUIESCENT (the run_arm2 /
#: tb_reload pattern), never a monitor exception. Each must run WITH A PEER in
#: another registered gate (`peer_coverage`), so declaring it quiescent here
#: never leaves it untested everywhere.
QUIESCENT = {
    "corpus_uartrx.hex": "edge-paced, no peer in this bench",
    "sptgt_m0_image.hex": "edge-paced, no peer in this bench",
    "sptgt_m1_image.hex": "edge-paced, no peer in this bench",
    "sptgt_m2_image.hex": "edge-paced, no peer in this bench",
    "sptgt_m3_image.hex": "edge-paced, no peer in this bench",
    "sptgt_mosi_image.hex": "edge-paced, no peer in this bench",
    "uart_rx_image.hex": "edge-paced, no peer in this bench",
}


def _shards():
    with open(os.path.join(ROOT, "ci", "shards.txt"), encoding="utf-8") as fh:
        return {ln.split()[1] for ln in fh if len(ln.split()) >= 2
                and not ln.lstrip().startswith("#")}


def _text(rel):
    try:
        with open(os.path.join(ROOT, rel), encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def peer_coverage(name, registry=None, corpus_map=None, shards=None, read=None):
    """[(gate, how)]: the registered gates that run image `name` WITH A PEER,
    read from the repo's own declarations, never a typed map:
      * its gate_wire_feed row is WITNESS (sim) -- the row's runner compares
        the wire against a peer -- and that runner is in ci/shards.txt and
        names the image file;
      * it is a corpus program (test/corpus.py CORPUS) with its PEER wiring,
        run by test/gate_corpus_trace.py (in ci/shards.txt), which passes
        +PEER to its bench."""
    import gate_wire_feed as WF
    import corpus
    registry = WF.REGISTRY if registry is None else registry
    corpus_map = corpus.CORPUS if corpus_map is None else corpus_map
    shards = _shards() if shards is None else shards
    read = _text if read is None else read
    out = []
    ent = registry.get(name)
    if ent and WF.label_of(*ent).startswith(WF.WITNESS_SIM):
        r = ent[1].get("runner")
        if r and r in shards and name in read(r):
            out.append((r, "wire-feed %s" % WF.label_of(*ent)))
    stem = name[:-4] if name.endswith(".hex") else name
    ct = "test/gate_corpus_trace.py"
    if (stem in corpus_map and corpus_map[stem][1] and ct in shards
            and "+PEER=" in read(ct)):
        out.append((ct, "corpus peer %r" % corpus_map[stem][1]))
    return out


def plant_first_writeback(img):
    """(planted bytes, byte address, original word fields): lane 0's first
    LEVEL word with level 1 -- the dispatch that makes the first writeback --
    with its level flipped to 0."""
    pc = I.read_header(img, 0)["base"]
    while pc + I.ACT_BYTES <= len(img):
        a = I._unpack(I.ACT_FIELDS, img[pc:pc + I.ACT_BYTES], I.ACT_BYTES)
        if a["op"] == I.OP_LEVEL and a["level"] == 1:
            out = bytearray(img)
            out[pc:pc + I.ACT_BYTES] = I.act(a["op"], a["pin"], 0, a["delay"],
                                             a["count"], a["q"], a["pinb"], a["mod"])
            return bytes(out), pc, a
        if a["op"] == I.OP_REARM:
            break
        pc += I.ACT_BYTES
    raise RuntimeError("plant: lane 0 has no level-1 LEVEL word before its REARM")


def reached(run, word):
    """(dispatch cycle, its record index, writeback cycle, its record index)
    if the clean run, after its start, dispatches `word` on lane 0 and then
    writes back; else None. Indices count from the start, as first_diff's."""
    if run["start"] is None:
        return None
    recs = after(run, run["start"])
    key = "0 %d %d %d %d " % (word["op"], word["pin"], word["level"], word["delay"])
    for k, (kind, cyc, rest) in enumerate(recs):
        if kind == "D" and (rest + " ").startswith(key):
            for j in range(k + 1, len(recs)):
                if recs[j][0] == "P":
                    return cyc, k, recs[j][1], j
            return None
    return None


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
    print("  v2-EQUIV -- translator + engine == v1 at 50 MHz, guard band aside")
    print("=" * 78)
    banner("iverilog", "vvp")
    import clock
    v1_hz = v1_clock_hz()
    ps = clock.period_ps(v1_hz)
    print("  v1's clock (v1-lock info.yaml): %.1f MHz -> both builds at %d ps; the "
          "60 MHz side is gate_clock_cross's" % (v1_hz / 1e6, ps))
    V1 = T.v1()
    cpb = load_cyc_per_byte()
    D = (I.STORE_BYTES - V1.STORE_BYTES) * cpb
    print("  offset D = (%d - %d) x %d (tb_equiv's LOAD_CYC_PER_BYTE) = %d -- DERIVED"
          % (I.STORE_BYTES, V1.STORE_BYTES, cpb, D))
    probs = []
    # ⛔ ONE JUDGE, ONE LIST (Wilson 11-14): this bench runs every image with NO
    # PEER, so refusal images print progress.vh's vacuity line on v1 AND v2
    # alike, and the encoding must-fires (v2eq_mf*) are broken on purpose.
    # Every such arm is declared by exact identity in test/monitor_mustfire.py
    # (the `gate_v2_equiv:*` entries + their CLEAN_BUILD_EXCEPTIONS); the
    # central judge (sim_run) rules on them like every other run. Section 1
    # still requires v1's and v2's FAIL lines to be EQUAL on top of that.
    tmp = tempfile.mkdtemp(prefix="pe_v2equiv_")
    try:
        v1src = []
        for f in RTL:
            p = os.path.join(tmp, "v1_" + os.path.basename(f))
            with open(p, "wb") as fh:
                fh.write(git("show", "%s:%s" % (V1REV, f)))
            v1src.append(p)
        vv1, vv2, vvm = (os.path.join(tmp, n) for n in ("v1.vvp", "v2.vvp", "nomagic.vvp"))
        # the v1-lock engine predates rdy_rel / layer S (PE_EQUIV_PRE) and the
        # self-timed / USB decode the per-action progress bound reads (PE_V1_RTL)
        build(vv1, v1src, defines=["PE_EQUIV_PRE", "PE_V1_RTL"], ps=ps)
        build(vv2, RTL, defines=[V2_PERIOD_DEFINE], ps=ps)
        build(vvm, RTL, defines=[V2_PERIOD_DEFINE, "M_NO_MAGIC"], ps=ps)

        # ---- the image set: 41 v1-lock images + falloff ------------------
        names = sorted(os.path.basename(p) for p in
                       git("ls-tree", "-r", "--name-only", V1REV, "test")
                       .decode().split() if p.endswith(".hex"))
        cases = []      # (name, v1 bytes, v1 path, v2 path, v2 lookup path)
        rederived = []  # tracked v2 images that are no longer translate(v1)
        for n in names:
            b1 = git("show", "%s:test/%s" % (V1REV, n))
            img1 = bytes(int(w, 16) for w in b1.decode("ascii").split())
            # ⭐ v2 runs translate(v1) BUILT HERE, never the tracked file
            p2 = write_hex(os.path.join(tmp, "v2eq_t_" + n), T.translate(img1),
                           register=True)
            pt = os.path.join(ROOT, "test", n)
            if os.path.isfile(pt):
                with open(pt, encoding="ascii") as fh:
                    if bytes(int(w, 16) for w in fh.read().split()) != T.translate(img1):
                        rederived.append(n)
            cases.append((n, img1, write_v1(os.path.join(tmp, "v1_" + n), img1,
                                            "git show %s:test/%s" % (V1REV, n)),
                          p2, p2))
        print("  %d of %d tracked v2 images still equal translate(v1); %d re-derived "
              "for 60 MHz (reported, not judged -- the manifest pins them): %s"
              % (len(names) - len(rederived), len(names), len(rederived),
                 ", ".join(rederived) or "none"))
        f1 = v1_falloff(tmp)
        f2 = write_hex(os.path.join(tmp, "v2eq_falloff.hex"), T.translate(f1),
                       register=True)
        cases.append(("falloff.hex (store_probe)", f1,
                      write_v1(os.path.join(tmp, "v1_falloff.hex"), f1,
                               "store_probe.py + pe_isa.py at %s (v1's own encoder)" % V1REV),
                      f2, f2))

        # ---- 1. EQUIVALENCE at the derived offset --------------------------
        print()
        print("  --- 1. v1 (PROG + %d) vs v2, from the engine start ---" % D)
        runs = {}
        for n, img1, p1, p2, lk in cases:
            q = n in QUIESCENT
            a = sim(vv1, p1, V1.STORE_BYTES, D, lookup=[p1, lk], quiescent=q)
            b = sim(vv2, p2, I.STORE_BYTES, quiescent=q)
            runs[n] = (a, b)
            verdict, detail, prob = judge(n, a, b)
            nrec = len(after(b, b["start"])) if b["start"] is not None else 0
            print("    %-28s start v1 %-5s v2 %-5s  %5d records  %s"
                  % (n, a["start"], b["start"], nrec, verdict))
            if detail:
                print("        first difference: %s" % detail[:150])
            if prob:
                probs.append(prob)
            if b["cpb"] != cpb:
                probs.append("%s: the bench ran LOAD_CYC_PER_BYTE %s, the gate "
                             "derived with %d" % (n, b["cpb"], cpb))
        live = [n for n, (a, b) in runs.items()
                if b["start"] is not None and after(b, b["start"])]
        adm = [n for n in runs if n.split()[0] not in NA.NON_ADMISSIBLE]
        print("    %d of %d ADMISSIBLE images identical (judged); %d non-admissible "
              "run and reported, %d of them differing (%s); %d started and recorded"
              % (sum(1 for n in adm if judge(n, *runs[n])[0].startswith("IDENTICAL")), len(adm),
                 len(runs) - len(adm),
                 sum(1 for n in runs if n not in adm and judge(n, *runs[n])[0] !=
                     "IDENTICAL (non-admissible, not judged)"), OUTSIDE, len(live)))

        # ---- 1a. must-fires: the declared sticky-bit difference is SCOPED ----
        # (Wilson 11-19) on the recorded runs: (i) another uo_out bit also moved on
        # an erratum image, (ii) the sticky bit NOT set in v2 (the fix not holding),
        # (iii) the same sticky-only difference on an image NOT on the list.
        import copy
        e0 = next((n for n in STICKY_ERRATUM if n in runs), None)
        if e0 is None:
            probs.append("must-fire: no sticky-erratum image ran")
        else:
            a0, b0 = runs[e0]
            # the plant goes on the FIRST differing record AFTER the start (the judge
            # compares from the start; a pre-start record proves nothing)
            ra0, rb0 = after(a0, b0["start"]), after(b0, b0["start"])
            d0 = next((y for x, y in zip(ra0, rb0) if x != y), None)
            k = b0["recs"].index(d0) if d0 is not None else None
            mfs = []
            if k is not None:
                bi = copy.deepcopy(b0)
                kind, cyc, rest = bi["recs"][k]
                t = rest.split()
                t[0] = "%02x" % (int(t[0], 16) ^ 0x01)
                bi["recs"][k] = (kind, cyc, " ".join(t))
                mfs.append(("another uo_out bit moved on %s" % e0, judge(e0, a0, bi)[2]))
            bii = copy.deepcopy(b0)
            bii["recs"] = list(a0["recs"])
            mfs.append(("the sticky bit not set in v2 on %s" % e0, judge(e0, a0, bii)[2]))
            if PLANT_IMAGE in runs:
                a3, b3 = runs[PLANT_IMAGE]
                b3c = copy.deepcopy(b3)
                j = next((i for i, x in enumerate(b3c["recs"]) if x[0] == "P"
                          and x[1] >= (b3c["start"] or 0)), None)
                if j is not None:
                    kind, cyc, rest = b3c["recs"][j]
                    t = rest.split()
                    t[0] = "%02x" % (int(t[0], 16) ^ STICKY_BIT)
                    b3c["recs"][j] = (kind, cyc, " ".join(t))
                    mfs.append(("a sticky-only difference on %s (not listed)" % PLANT_IMAGE,
                                judge(PLANT_IMAGE, a3, b3c)[2]))
            if len(mfs) != 3:
                probs.append("must-fire: the sticky-scope plants could not all be made "
                             "(%d of 3)" % len(mfs))
            for what, prob in mfs:
                print("    must-fire: %-56s %s" % (what, "red" if prob else "*** ACCEPTED"))
                if not prob:
                    probs.append("must-fire survived: " + what)

        # ---- 1b. must-fire: a planted difference on an ADMISSIBLE image ----
        # (Wilson 11-14) PINNED to smoke_image (stable, admissible, so the
        # check is deterministic). The plant flips the LEVEL of lane 0's first
        # level-1 LEVEL word in smoke_image's v2 translation: that dispatch
        # makes the run's FIRST WRITEBACK (the first P record after it: lane
        # 0's pin rising), and the plant takes it away. REACH CHECK: the clean
        # v2 run must dispatch that exact word after the start AND write back
        # after it -- else the must-fire proves only that the bench stopped
        # early ("difference outside the run"), and is red.
        pn = PLANT_IMAGE
        if pn not in adm or pn not in live:
            probs.append("must-fire: the planted-difference image %s is not an "
                         "admissible image that runs" % pn)
        else:
            pc = next(c for c in cases if c[0] == pn)
            planted, at, word = plant_first_writeback(T.translate(pc[1]))
            reach = reached(runs[pn][1], word)
            print("    must-fire plant: %s lane 0 word at byte %d (op %d pin %d level "
                  "%d delay %d) -> level %d" % (pn, at, word["op"], word["pin"],
                                               word["level"], word["delay"],
                                               word["level"] ^ 1))
            if reach is None:
                probs.append("must-fire: difference outside the run -- the clean "
                             "%s run never dispatched the planted word (lane 0, "
                             "%s) and wrote back after it" % (pn, word))
            else:
                print("    reach: the clean run dispatches it at cycle %d (record %d); "
                      "its writeback at cycle %d (record %d)" % reach)
            pp = write_hex(os.path.join(tmp, "v2eq_plant_%s" % pn), planted,
                           register=True)
            bp = sim(vv2, pp, I.STORE_BYTES)
            _v, pd, pprob = judge(pn, runs[pn][0], bp)
            print("    must-fire: %s with a planted difference (first writeback) -> %s"
                  % (pn, "red  ok" if pprob else "*** MISSED"))
            if pd:
                print("        judged at: %s" % pd[:150])
            if not pprob:
                probs.append("must-fire: a planted difference on admissible %s "
                             "stayed green" % pn)
            elif reach is not None:
                # the difference must land INSIDE the run: the first differing
                # record is at or before the clean run's planted writeback
                m = re.match(r"record (\d+):", pd)
                if not m or int(m.group(1)) > reach[3]:
                    probs.append("must-fire: difference outside the run -- judged "
                                 "at %r, not at or before the planted writeback "
                                 "(record %d)" % (pd[:80], reach[3]))
            # and the label cannot launder an admissible image: judged as if
            # it were declared non-admissible, the same pair is NOT a problem --
            # so the redness above comes from the admissible scope, not the runs
            _v, _d, nprob = judge(sorted(NA.NON_ADMISSIBLE)[0], runs[pn][0], bp)
            if nprob:
                probs.append("must-fire control: the non-admissible label still judged")

        # ---- 1c. QUIESCENT BY DECLARATION (Wilson 11-14) -------------------
        print()
        print("  --- 1c. quiescent by declaration: each image covered WITH A PEER elsewhere ---")
        for qn in sorted(QUIESCENT):
            if qn not in runs:
                probs.append("QUIESCENT names %s, which this gate does not run" % qn)
                continue
            cov = peer_coverage(qn)
            print("    %-24s %s -> %s" % (qn, QUIESCENT[qn],
                                          "; ".join("%s (%s)" % c for c in cov)
                                          or "*** NO PEER COVERAGE"))
            if not cov:
                probs.append("%s is declared quiescent here and runs with a peer in "
                             "no registered gate -- untested everywhere" % qn)
        # must-fire: a quiescent image with no peer-bench coverage is red
        mf = peer_coverage("armnone_image.hex")
        print("    must-fire: a quiescent image no peer bench runs (armnone) -> %s"
              % ("red  ok" if not mf else "*** COVERED %s" % mf))
        if mf:
            probs.append("must-fire: peer_coverage found a peer for armnone_image")
        mf2 = peer_coverage("uart_rx_image.hex", shards=_shards() - {"test/run_uartrx.py"})
        print("    must-fire: the same image with its runner out of CI    -> %s"
              % ("red  ok" if not mf2 else "*** COVERED %s" % mf2))
        if mf2:
            probs.append("must-fire: peer_coverage counted a runner not in CI")

        # ---- 2. the offset must-fire: D - 1 and D + 1 ----------------------
        print()
        print("  --- 2. must-fire: the offset one cycle off ---")
        for dd in (D - 1, D + 1):
            red = 0
            for n, img1, p1, p2, lk in cases:
                if n not in live:
                    continue
                a = sim(vv1, p1, V1.STORE_BYTES, dd, ncyc=NCYC_MF, lookup=[p1, lk],
                        quiescent=n in QUIESCENT)
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
        # ⛔ Wilson 10-26: a RAW image (no pe_asm) with a RESERVED opcode is
        # refused AT LOAD -- in the FIRST action word, and in the LAST word of
        # the store, so the loader's check is shown to cover the whole store
        first_w = I.ACT_BASE
        last_w = I.STORE_BYTES - I.ACT_BYTES
        # + the TOP opcode (31): the BUILT_OPS mask covers the whole 5-bit space, not
        # just the lowest gap (OBSERVE, 23, was this arm until it was built, 11-19)
        for op, where, at in ((I.OP_UNBUILT, "the first", first_w),
                              (I.OP_UNBUILT, "the last", last_w),
                              ((1 << I.OP_W) - 1, "the first", first_w)):
            ro = bytearray(img2)
            ro[at] = (op << (8 - I.OP_W)) | (ro[at] & ((1 << (8 - I.OP_W)) - 1))
            pro = write_hex(os.path.join(tmp, "v2eq_resop_%d_%d.hex" % (op, at)), bytes(ro),
                            register=True)
            r = sim(vv2, pro, I.STORE_BYTES, ncyc=NCYC_MF)
            say(r["started"] == 0 and r["cfg_err"] == 1,
                "opcode %d in %s action word (byte %d) is REFUSED at load: "
                "cfg_err=%s, started=%s" % (op, where, at,
                                           r["cfg_err"], r["started"]))
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
    # the scope on its own line, beside the verdict (the token stays exact)
    print("  scope: translator + engine == v1 at 50 MHz, guard band aside "
          "(v2 built BAND 1/1 here only; the band: gate_clock_consistency)")
    print("  GATE v2-equiv: %s" % ("FAILED" if probs else "PASSED"))
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())
