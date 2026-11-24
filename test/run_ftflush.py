"""run_ftflush -- the slot buffer, piece 3 (Wilson 11-22): the FALLTHROUGH flush, K1-K6 and K8,
on agent 2's `FlushKeep.stepBK` -- each contract with its must-fire.

What piece 3 does (pe_engine): a FALLTHROUGH ARM's capture raises its slot request and the slot
fetches its EDGE word (PC+2) first, its TIMEOUT word (PC+1) second; the edge word carries the
EDGE TAG (one bit per head / spare / buffer place, moved with the word -- the RTL form of the
model's kept index). At the ARM's writeback the timeout word takes the head and the edge word is
held as the spare (K6). At a timeout the held PC+2 is dropped, every time (K6). At the edge the
tagged word -- in a slot, in the buffer, or arriving in that very cycle's capture -- is kept as
the head; everything else is cleared and the lane is released the cycle after (K1-K4); a fetch
for the lane in flight at the edge is killed (K5).

The checks are pe_engine's own sim-only assertions, judged from the SHADOW ADDRESSES (not the
tags): FTKEEP (the word at PC+2, held or arriving at the edge, is the head after it), FTDROP
(nothing else is held after it), FTREL (released the cycle after), FTTMO (no PC+2 held the cycle
after a timeout), and SLOTORD (every valid head holds the word at its lane's PC).

Images on tb_arm2 (lane 0 waits on uio[0]'s fall; the bench flips it ONCE at an absolute cycle,
`+PHA_ABS`, swept cycle by cycle around the image's first arming; the ARM's timeout is short, so
the lane loops and its later armings are captured after `primed`):
  ftflush_dw1    THE BUFFERED EDGE WORD (Wilson 11-22): the FT ARM captured during start-up
                 (PC+1 primed first), one earlier-deadline lane delays its writeback, so the edge
                 word is buffered at writeback + 1 -- K3's buffer clause, a standing case
  ftflush_fall   ARM(FT) -> LEVEL UO0 0 (PC+1, falls through) -> LEVEL UO0 1 (PC+2) -> ... loop
  ftflush_loop   ARM(FT) -> REARM looping (PC+1) -> LEVEL UO0 1 (PC+2) -> ...: after a timeout
                 the held PC+2 is NOT the head's successor
  ftflush_spare  a long word, then ARM(FT): the ARM is captured into the SPARE, so its edge word
                 goes to the buffer and LOADS into the spare (the tag moves)
  ftflush_quick  a 2-cycle word, then ARM(FT): the ARM retires right after its capture, so its
                 fetches can be in flight at the edge; `_b7`: four busy lanes contend for the port
plus each image with no flip at all (the timeout path only).

Clean: no assertion in any run, and the summed +SLOTSTAT counts show each situation: an FT raise,
the edge word kept in a slot / from the buffer / from the edge cycle's own capture (the tight
case), a timeout, and a tag moved by a load. The edge word ABSENT at an edge (the refetch branch)
is counted and reported, not required: 0 over 3,253 runs, agent 2's "never absent" lemma decides
it (Wilson 11-22).

Must-fires (each RED somewhere in its image's sweep, by its assertion):
  M_FT_DROP_EDGE   K1  the edge word not kept                          FTKEEP
  M_FT_KEEP_TMO    K2  the timeout word kept past the edge             FTDROP
  M_FT_CAP_LOST    K1  the edge cycle's own capture not kept           FTKEEP
  M_FT_LOAD_LATE   K3  a buffered edge word loaded a cycle late        FTKEEP (on ftflush_dw1)
  M_FT_REL_LATE    K4  released a cycle late                           FTREL
  M_FT_NO_PKILL    K5  the in-flight fetch not killed                  SLOTORD / FTDROP / FTKEEP
  M_FT_CAP_FILES   K5  the edge cycle's other capture filed            FTDROP / SLOTORD
  M_FT_TMO_KEEP    K6  the held PC+2 left valid after a timeout        FTTMO / SLOTORD
  M_FT_TMO_LOADRACE K6 the buffer loads the word the drop removes      FTTMO (V2E1, on dwrace)
  M_TMOPICK_DISPATCH  the timeout pick dispatches PC+1 in its cycle    TMOPICK (Wilson 11-24)
  M_PARKARM_MARK      the park mark set on a phase that does not park PARKARM (Wilson 11-24, parkpp)
  M_FT_TAG_LOST        the edge tag lost when its word moves           FTKEEP
  M_FT_SCAN_RACE   K9  the scan selects a flushing lane (11-14)        K9 (ScanOk)
Piece 4 (Wilson 11-20 / 11-22), the scheduler contracts, on the same images:
  M_K10_EARLY      K10 an edge acting in its arming writeback cycle   K10
  M_K11_EARLY      K11 an armed lane released before its deadline     K11 (reworded 11-22 (b))
  M_SCHED_SKIP         a ready decision cycle naming no lane          NAMES (sched_names_ready)
sched_bprime's must-fire is M_GLOBAL_STALL (readiness without the head-valid term), killed by
run_mutants; its own check BPRIME now reports it too. TMOPICK holds the FT timeout pick to one
ST_IDLE cycle with no dispatch. K8 (M_FT_REFLUSH) stays in run_arm2.

POSITIVE TOKEN: `GATE ftflush: PASSED`.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from toolchain import banner            # noqa: E402
import pe_isa as I                      # noqa: E402
import sim_run                          # noqa: E402
import run_arm2 as A                    # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

GEN = "run_ftflush"
D1 = A.D1
TMO = 40                     # the ARM's timeout: short, so the lane loops (later armings post-prime)
NCYC = 360
FLIP_LO, FLIP_HI = -6, 150   # the flip, relative to the image's first arming (one flip per run)
#: the gate's images (thinned 11-22 from a 12-image, 35-minute exploration -- R:\claude_scratch
#: is where the full sweeps live): each case the counts require, and each must-fire, is reached
#: on at least one of these. `dw1` is the standing buffered-edge-word case (K3's buffer clause).
#: `dwrace` / `dwrace2` (11-24, V2E1 in docs/V2_DEFECTS.md): the start-up order with a SHORT
#: timeout -- the edge word waits in the buffer while the spare empties, and the buffer would load
#: it in the K6 drop's own cycle (FTTMO, then SLOTORD on dwrace; FTTMO alone on dwrace2)
#: `parkpp` (Wilson 11-24, PARKARM's must-fire): a PUSH-PULL clocked write (no park) then a plain ARM
IMAGES = ("dw1", "fall", "loop", "spare", "quick", "quick_b7", "parkft", "parkqual", "dwrace", "dwrace2",
          "parkpp")
#: the flip window per image, relative to its first arming (the buffered case sits at wb + 1)
WINDOW = {"dw1": (-6, 21), "dwrace": (-6, 21), "dwrace2": (-6, 21), "parkpp": (-6, 21)}
#: the V2E1 witnesses: dw_image(n, ds, wd) at their own timeout (found 11-24, 76 of 320 images)
RACE = {"dwrace": (1, 2, 8, 2), "dwrace2": (2, 6, 4, 16)}
STATS = ("ftraise", "keepslot", "keepbuf", "keepcap", "keepnone", "fttmo", "tagmove")
#: counted but NOT required: the edge word ABSENT at an FT edge (the refetch branch) -- 0 over
#: 3,253 runs; agent 2's "never absent" lemma decides it (Wilson 11-22), so it is reported, not
#: demanded, until the lemma lands (UNREACHABLE by proof) or a case reaches it
PENDING = ("keepnone",)
#: mutant -> (contract, what it plants, the images tried in order, the assertion tags)
#: each mutant's images in the order tried, the image that turned it red first (11-22) leading
MUTANTS = [
    ("M_FT_DROP_EDGE", "K1", "the edge word not kept", ("fall", "quick"), ("FTKEEP",)),
    ("M_FT_KEEP_TMO", "K2", "the timeout word kept past the edge", ("fall", "quick"), ("FTDROP",)),
    ("M_FT_CAP_LOST", "K1", "the edge cycle's own capture not kept", ("fall", "quick_b7"), ("FTKEEP",)),
    ("M_FT_LOAD_LATE", "K3", "a buffered edge word loaded late", ("dw1",), ("FTKEEP",)),
    ("M_FT_REL_LATE", "K4", "released a cycle late", ("fall", "quick"), ("FTREL",)),
    ("M_FT_NO_PKILL", "K5", "the in-flight fetch not killed", ("quick", "quick_b7"),
     ("SLOTORD", "FTDROP", "FTKEEP")),
    ("M_FT_CAP_FILES", "K5", "the edge cycle's other capture filed", ("quick", "quick_b7"),
     ("FTDROP", "SLOTORD")),
    ("M_FT_TMO_KEEP", "K6", "PC+2 left valid after a timeout", ("loop", "fall"), ("FTTMO", "SLOTORD")),
    ("M_FT_TAG_LOST", "tag", "the edge tag lost on a move", ("spare", "quick"), ("FTKEEP",)),
    ("M_FT_SCAN_RACE", "K9", "the scan selects a flushing lane", ("quick_b7", "quick"),
     ("K9",)),
    # piece 4 (Wilson 11-20 / 11-22): the scheduler contracts
    ("M_K10_EARLY", "K10", "an edge acting in its arming writeback", ("fall", "quick"), ("K10",)),
    ("M_K11_EARLY", "K11", "an armed lane released before its deadline", ("fall", "loop"), ("K11",)),
    ("M_SCHED_SKIP", "names", "a ready decision cycle naming no lane", ("fall", "quick"), ("NAMES",)),
    # what a clocked park leaves behind (Wilson 11-23): items 1 and 2
    ("M_PARK_KEEPS_FT", "park1", "the park leaves l_armft set", ("parkft",), ("PARKFLAGS",)),
    ("M_PARK_KEEPS_QUAL", "park1", "the park leaves l_armqual set", ("parkqual",), ("PARKFLAGS",)),
    ("M_PARK_STUCK", "park2", "the park not ended at its own rise", ("parkft", "parkqual"),
     ("PARKEND",)),
    # the stale edge tag (Wilson 11-24): a tag left on a slot / buffer that holds no word
    ("M_TAG_STALE", "tag", "the edge tag left on an emptied place", ("spare", "quick", "dw1"),
     ("TAGSTALE",)),
    # V2E1 (11-24): the buffer loads the tagged word in the K6 drop's cycle, so it escapes the drop
    ("M_FT_TMO_LOADRACE", "K6", "the buffer loads the word the drop removes", ("dwrace", "dwrace2"),
     ("FTTMO",)),
    # TMOPICK (agent 2's 11-22 question, its must-fire per Wilson 11-24): the pick dispatches
    ("M_TMOPICK_DISPATCH", "pick", "the timeout pick dispatches PC+1 in its cycle", ("fall", "loop"),
     ("TMOPICK",)),
    # PARKARM (its must-fire per Wilson 11-24): a mark with no park, so no rise ever clears it
    ("M_PARKARM_MARK", "park3", "the park mark set on a phase that does not park", ("parkpp",),
     ("PARKARM",)),
]

#: THE PARK WITNESS (Wilson 11-23, item 2): lane 0 an open-drain clocked lane that WRITES, idles
#: past the stretch bound, then waits on a plain ARM -- at CK_PRE = 4, so the shipped tick bound
#: (CK_STRETCH_TO) is ~500 cycles. Clean: no fault, the ARM releases at its edge. M_PARK_STUCK:
#: the false stretch halt (erratum E2) must show -- it halts the lane inside the idle, so the
#: parked-ARM effect (PARKARM) is shown instead by parkft's loop back to its ARM.
WIT_PRE, WIT_IDLE, WIT_FLIP, WIT_NCYC = 4, 900, 1400, 2200
WIT_WANT = ("STRETCHFALSE",)


def image(name):
    """lane 0 as above. `<kind>` parks lanes 1-4 (an idle port: the edge word is held long
    before the edge, buffered and loaded); `<kind>_b<d>` keeps them BUSY with pinless
    loops of words of d.. cycles, so the one fetch port is contended at a phase set by d
    and lane 0's FT words can still be in flight -- or not yet fetched -- at its edge."""
    if name in RACE:
        n, ds, wd, tmo = RACE[name]
        return dw_image(n, ds, wd, tmo)
    if name.startswith("dw"):
        return dw_image(int(name[2:]))
    if name.startswith("park"):
        return park_image(name)
    kind, _s, b = name.partition("_b")
    busy_d = int(b) if b else None
    arm = I.act_arm(A.PIN_A, 0, TMO, ft=True)
    lvl = lambda v: I.act(I.OP_LEVEL, I.UO0, v, D1)
    loop = I.act(I.OP_REARM, 0, 1, D1)
    if kind == "fall":
        prog = [arm, lvl(0), lvl(1), lvl(0), loop]
    elif kind in ("quick", "pair"):   # a 2-cycle word before the ARM: it retires right after capture
        prog = [I.act(I.OP_LEVEL, I.PIN_NONE, 0, 2), arm, lvl(0), lvl(1), lvl(0), loop]
    elif kind == "loop":
        prog = [arm, loop, lvl(1), lvl(0), loop]
    elif kind == "spare":
        prog = [I.act(I.OP_LEVEL, I.PIN_NONE, 0, 30), arm, lvl(0), lvl(1), lvl(0), loop]
    else:
        raise ValueError(kind)
    l0 = I.ACT_BASE
    headers = [I.hdr(I.UO0, I.UO0, 1, D1, 0, 2 * D1, 3 * D1, l0)]
    base = l0 + len(prog) * I.ACT_BYTES
    if busy_d is None:
        prog.append(I.act(I.OP_REARM, 0, 0, 500))
        for k in range(1, I.N_LANES):
            headers.append(I.hdr(k + 1, k + 1, 0, 500, 0, 200, 240, base))
        return I.join_image(headers, prog)
    for k in range(1, I.N_LANES):
        d = busy_d + k
        if kind == "pair" and k == 1:
            # a SECOND FT lane on the same pin, captured with lane 0: its slot request
            # waits first-come-first-served behind lane 0's two fetches, so at the shared
            # edge its edge word can still be unfetched or in flight (K1's refetch, K5)
            pl_ = lambda v: I.act(I.OP_LEVEL, I.PIN_NONE, v, D1)
            busy = [I.act(I.OP_LEVEL, I.PIN_NONE, 0, 2), I.act_arm(A.PIN_A, 0, TMO, ft=True),
                    pl_(0), pl_(1), pl_(0), I.act(I.OP_REARM, 0, 1, D1)]
            headers.append(I.hdr(I.PIN_NONE, I.PIN_NONE, 1, D1, 0, 2 * D1, 3 * D1, base))
        else:
            busy = [I.act(I.OP_LEVEL, I.PIN_NONE, 0, d) for _ in range(4)] + [I.act(I.OP_REARM, 0, 1, d)]
            headers.append(I.hdr(I.PIN_NONE, I.PIN_NONE, 1, 40, 0, 80, 120, base))
        prog += busy
        base += len(busy) * I.ACT_BYTES
    return I.join_image(headers, prog)


def dw_image(n, ds=4, wd=6, tmo=None):
    """THE BUFFERED EDGE WORD (Wilson 11-22, K3's buffer clause, a standing case): lane 0's FT ARM
    is word 0, captured during start-up, so the round robin primes PC+1 first and the edge word
    comes second; lanes 1..n get EARLIER deadlines and win the first dispatches after priming, so
    lane 0's ARM writes back late, its edge word is captured before that writeback and BUFFERED
    (head and spare full), and an edge at writeback + 1 meets it in the buffer -- the flush keeps it
    from there as the head (measured 11-22: 24 of 24 images, edge word 2-23 cycles ahead).
    `tmo` overrides the module TMO (the V2E1 witnesses, RACE)."""
    arm = I.act_arm(A.PIN_A, 0, TMO if tmo is None else tmo, ft=True)
    lvl = lambda v: I.act(I.OP_LEVEL, I.UO0, v, D1)
    prog = [arm, lvl(0), lvl(1), lvl(0), I.act(I.OP_REARM, 0, 1, D1)]
    l0 = I.ACT_BASE
    headers = [I.hdr(I.UO0, I.UO0, 1, D1, 0, 2 * D1, 3 * D1, l0)]
    base = l0 + len(prog) * I.ACT_BYTES
    park = None
    for k in range(1, I.N_LANES):
        if k <= n:
            w = [I.act(I.OP_LEVEL, I.PIN_NONE, 0, wd) for _ in range(4)] + [I.act(I.OP_REARM, 0, 1, wd)]
            headers.append(I.hdr(I.PIN_NONE, I.PIN_NONE, 1, wd, 0, ds, 2 * ds, base))
            prog += w
            base += len(w) * I.ACT_BYTES
        else:
            if park is None:
                park = base
                prog.append(I.act(I.OP_REARM, 0, 0, 500))
                base += I.ACT_BYTES
            headers.append(I.hdr(k + 1, k + 1, 0, 500, 0, 200, 240, park))
    return I.join_image(headers, prog)


#: the park lane: open-drain, data uio[2], clock uio[3] (both pulled up on tb_arm2, so a released
#: clock rises at once and every park's rise comes)
PK_PIN, PK_CLK = 2, 3
#: the park lane's spacing: the I2C images' 70 (a 12-cycle clocked bit breaks the SDA hold rule and
#: is refused -- config_err, the lane halts, no park: measured 11-23)
PK_D = 70


def park_image(name):
    """WHAT A CLOCKED PARK LEAVES BEHIND (Wilson 11-23). `parkft`: lane 0's FALLTHROUGH ARM, then a
    clocked write on BOTH of its paths (PC+1 on the timeout, PC+2 at the edge), so every flip
    parks with the ARM's flags in place; `parkqual`: the same ARM with QUAL too (a QUAL ARM can
    reach a park only through its FALLTHROUGH timeout); `parkwit`: the witness -- a clocked write,
    an idle word past the stretch bound, then a plain ARM (no timeout) on the bench's pin; `parkpp`:
    the same clocked write on a PUSH-PULL lane, which never parks, then a plain ARM (PARKARM)."""
    sh = I.act_shift_clocked(PK_PIN, PK_D, nbits=2)
    rel = I.act(I.OP_LEVEL, PK_PIN, 1, PK_D)          # open-drain: release the data line
    if name in ("parkft", "parkqual"):
        prog = [I.act_arm(A.PIN_A, 0, TMO, ft=True, qual=(name == "parkqual")),
                sh, sh, rel, I.act(I.OP_REARM, 0, 1, PK_D)]
    elif name == "parkpp":
        prog = [sh, I.act_arm(A.PIN_A, 0, 0), I.act(I.OP_REARM, 0, 1, PK_D)]
    elif name == "parkwit":
        prog = [I.act_shift_clocked(PK_PIN, PK_D, nbits=8), rel,
                I.act(I.OP_LEVEL, I.PIN_NONE, 0, WIT_IDLE),
                I.act_arm(A.PIN_A, 0, 0), rel, I.act(I.OP_REARM, 0, 0, 500)]
    else:
        raise ValueError(name)
    l0 = I.ACT_BASE
    headers = [I.hdr(PK_PIN, PK_CLK, 1 if name == "parkpp" else 0, PK_D, 0, *I.d_fields(PK_D), l0)]
    base = l0 + len(prog) * I.ACT_BYTES
    prog.append(I.act(I.OP_REARM, 0, 0, 500))
    for k in range(1, I.N_LANES):
        headers.append(I.hdr(k + 3, k + 3, 0, 500, 0, 200, 240, base))
    return I.join_image(headers, prog)


def build_pre(out, defines=(), pre=WIT_PRE):
    """tb_arm2 with the stretch prescaler shortened (the witness)"""
    r = A.run([A.tool("iverilog"), "-g2012", "-I", ROOT, "-o", out, "-s", "tb_arm2",
               "-Ptb_arm2.CK_PRE=%d" % pre] + ["-D%s" % d for d in defines] + [A.BENCH] + A.RTL)
    if r.returncode != 0:
        raise RuntimeError("build %s failed: %s" % (out, (r.stdout + r.stderr)[-400:]))


def witness(vvp, img):
    """(assertion tag -> count, ended) for the park witness"""
    args = [vvp, "+IMG=%s" % img, "+IDLE=1", "+PHA=-1", "+PHB=-1", "+NCYC=%d" % WIT_NCYC,
            "+PHA_ABS=%d" % WIT_FLIP, "+QUIESCENT"]
    r = A.run(sim_run.vvp(args, images=[img]))
    out = r.stdout + r.stderr
    tags = {}
    for m in re.finditer(r"^\s*\*\*\* ASSERT pe_engine (\w+):", out, re.M):
        tags[m.group(1)] = tags.get(m.group(1), 0) + 1
    return tags, ("ARM2 " in out)


def armed_at(vvp, img):
    """the bench's first arming cycle on lane 0 (no flip)"""
    args = [vvp, "+IMG=%s" % img, "+IDLE=1", "+PHA=-1", "+PHB=-1", "+NCYC=10", "+PHA_ABS=-1",
            "+QUIESCENT"]
    m = re.search(r"^ARM2 armed=(-?\d+)", A.run(sim_run.vvp(args, images=[img])).stdout, re.M)
    return int(m.group(1)) if m else -1


def sim(vvp, img, flip):
    """(assertion tag -> count, the SLOTSTAT dict, ended)"""
    args = [vvp, "+IMG=%s" % img, "+IDLE=1", "+PHA=-1", "+PHB=-1", "+NCYC=%d" % NCYC,
            "+PHA_ABS=%d" % flip, "+SLOTSTAT", "+QUIESCENT"]
    r = A.run(sim_run.vvp(args, images=[img]))
    out = r.stdout + r.stderr
    tags = {}
    for m in re.finditer(r"^\s*\*\*\* ASSERT pe_engine (\w+):", out, re.M):
        tags[m.group(1)] = tags.get(m.group(1), 0) + 1
    st = re.search(r"^SLOTSTAT (.*)$", out, re.M)
    sd = {k: int(v) for k, v in (kv.split("=") for kv in st.group(1).split())} if st else {}
    return tags, sd, ("ARM2 " in out)


def main() -> int:
    banner("iverilog", "vvp")
    print()
    print("=" * 78)
    print("FTFLUSH -- the slot buffer, piece 3: the FALLTHROUGH flush (K1-K6) on the RTL")
    print("=" * 78)
    probs = []
    tmp = tempfile.mkdtemp(prefix="pe_ftflush_")
    imgs = {}
    vvp = os.path.join(tmp, "ftflush.vvp")
    A.build(vvp)
    for k in IMAGES:
        p = os.path.join(tmp, "ftflush_%s.hex" % k)
        I.write_image(p, image(k))
        sim_run.scratch_image(GEN, p)
        a = armed_at(vvp, p)
        if a < 0:
            probs.append("%s: lane 0 never armed" % k)
        lo, hi = WINDOW.get(k, (FLIP_LO, FLIP_HI))
        imgs[k] = (p, [-1] + list(range(max(1, a + lo), a + hi)))
    print("\n  clean build: every image, the edge swept from %d to %d cycles around its first "
          "arming, and no edge at all" % (FLIP_LO, FLIP_HI - 1))
    totals = {}
    for k, (p, runs) in list(imgs.items()):
        tot, bad, ended = {}, {}, 0
        for f in runs:
            tags, sd, e = sim(vvp, p, f)
            ended += e
            for s in STATS:
                tot[s] = tot.get(s, 0) + sd.get(s, 0)
            if tags:
                bad[f] = tags
        print("    %-6s %s  runs %d (ended %d)  %s" % (k, " ".join("%s=%d" % (s, tot[s]) for s in STATS),
                                                      len(runs), ended,
                                                      ("asserts at flips %s" % sorted(bad)[:6]) if bad
                                                      else "no asserts"))
        if bad:
            f0 = sorted(bad)[0]
            probs.append("%s: the clean build tripped %s at flip %d (%d flips)" % (k, bad[f0], f0, len(bad)))
        if ended != len(runs):
            probs.append("%s: %d run(s) did not finish" % (k, len(runs) - ended))
        totals[k] = tot
    for s in STATS:
        n = sum(t[s] for t in totals.values())
        if s in PENDING:
            print("    %s = %d (pending agent 2's lemma: reported, not required)" % (s, n))
        elif n <= 0:
            probs.append("vacuous: %s never happened on any image" % s)
    print("\n  must-fires (each RED somewhere in its images' sweeps)")
    for d, kk, what, ks, want in MUTANTS:
        mv = os.path.join(tmp, "ftflush_%s.vvp" % d)
        A.build(mv, [d])
        hit = None
        for k in ks:
            p, runs = imgs[k]
            for f in runs:
                tags, _sd, _e = sim(mv, p, f)
                if any(tags.get(t, 0) for t in want):
                    hit = (k, f, tags)
                    break
            if hit:
                break
        print("    %-16s %-5s %-38s %s" % (d, kk, what, ("RED on %s at flip %d: %s" % hit)
                                           if hit else "*** SURVIVED on %s" % "/".join(ks)))
        if not hit:
            probs.append("%s (%s) survived on %s (no %s)" % (d, kk, "/".join(ks), "/".join(want)))
    # ---- the park witness (Wilson 11-23, item 2), at CK_PRE = WIT_PRE
    print("\n  park witness: a clocked write, %d idle cycles past the stretch bound (CK_PRE %d), "
          "then a plain ARM released at cycle %d" % (WIT_IDLE, WIT_PRE, WIT_FLIP))
    wp = os.path.join(tmp, "ftflush_parkwit.hex")
    I.write_image(wp, image("parkwit"))
    sim_run.scratch_image(GEN, wp)
    for d, want in ((None, ()), ("M_PARK_STUCK", WIT_WANT)):
        wv = os.path.join(tmp, "ftflush_wit_%s.vvp" % (d or "clean"))
        build_pre(wv, [d] if d else [])
        tags, ended = witness(wv, wp)
        if d is None:
            ok = not tags and ended
            print("    clean            %s" % ("no fault, no asserts, ended" if ok else "*** %s (ended %s)" % (tags, ended)))
            if not ok:
                probs.append("park witness, clean build: %s (ended %s)" % (tags or "no asserts", ended))
        else:
            ok = all(tags.get(t, 0) for t in want)
            print("    %-16s %s" % (d, ("RED: %s" % tags) if ok else "*** SURVIVED: %s" % tags))
            if not ok:
                probs.append("%s on the park witness: wanted %s, saw %s" % (d, "/".join(want), tags))
    print()
    for x in probs:
        print("  *** %s" % x)
    print("=" * 78)
    print("  GATE ftflush: %s" % ("PASSED" if not probs else "FAILED"))
    return 0 if not probs else 1


if __name__ == "__main__":
    sys.exit(main())
