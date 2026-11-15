"""poset compile -- the COMPILER SKELETON (Agent 2, 11-12; brief item 4).

A v2 poset spec in; out come the three artifacts of guiding doc step 6, as far as the
skeleton reaches, plus a refusal that NAMES the failing constraint when the spec does not fit:

  image      the chip program, through the existing ISA path (pe_proto / pe_asm, and
             pe_isa as the one encoder): every admissibility check applies
  checkset   the validator's predicates, derived from the SPEC ALONE, independently of
             the image (guiding doc §5: a check-set compiled from the same source as the
             program and run against its own output is circular)
  cert       the A2 certificate: per image (model/branch_budget, `A2`, `branch_budget`) and
             the J floor (`J_floor`, the image's certification STAMP, model/cert_stamp:
             pe_asm.compute_j on the image's lanes; the gate cross-checks it against the
             lanes the lowering handed pe_asm.assemble, which must re-assemble to the image
             byte for byte). Wilson 11-15: UNCERTIFIED is a stamp, refusal is opt-in --
             the image is built and stamped; `require_cert` (--require-cert) refuses an
             uncertified one with the same reason, as pe_asm's command line does.

Passes
  P1 parse      host/poset/spec.parse (v1 lines through pit_emit, unchanged)
  P2 order      the order graph over event kinds from `A -> B` / `A |> B` statements;
                a cycle is refused (step 6: "the compiler rejects cycles"); the Dilworth
                width (minimum chain cover) must be <= pe_isa.N_LANES
  P3 checkset   one ORDER predicate per statement; one WINDOW predicate per `during`, in
                cycles at the target clock (clock.hz()); tolerance (±J, sync, capture
                resolution) is applied by the validator, not baked in here
  P4 lower      the v1 claims -> image by test/run_pit_rt.emulation, the existing lowering,
                CALLED, not copied (one source). The poset statements do not yet steer
                the lowering: they become the check the emulation must pass.
  P5 target     program words used <= (STORE_BYTES - ACT_BASE) / ACT_BYTES (= 120, generated)

Not in the skeleton, and said so in every result: compound patterns (`or`, `and`, `~`,
repeats, nesting) are refused by name; the new poset opcodes (event core, step 1) wait for
their design note; bound certification (emulate, sniff, re-run the golden) is UNCERTIFIED.

Mutants for the gate's must-fires: env POSET_COMPILE_MUTANT (see MUTANTS).
"""
from __future__ import annotations

import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
for _p in (os.path.join(ROOT, "test"), os.path.join(ROOT, "model")):
    if _p not in sys.path:
        sys.path.insert(1, _p)
import spec as S  # noqa: E402
import pe_isa as I  # noqa: E402
import clock  # noqa: E402
import proof_constants as PC  # noqa: E402  (the proof's thresholds, derived; the one USB check)

MUTANTS = ("M_PC_NO_CYCLE",      # cycles not refused
           "M_PC_NO_CLOSURE",    # width from direct edges only (path cover, not chain cover)
           "M_PC_WINDOW_SWAP",   # window bounds swapped
           "M_PC_COMPOUND_PASS", # compound patterns silently dropped instead of refused
           "M_PC_USB_NOCHECK",   # the USB co-resident threshold not checked
           "M_PC_JFLOOR_HEAD")   # J floor from each lane's head action only, not every lowered action
MUT = os.environ.get("POSET_COMPILE_MUTANT", "")
if MUT and MUT not in MUTANTS:
    raise SystemExit("poset compile: unknown mutant %r" % MUT)

#: program words in the store, generated from the one encoder
N_WORDS = (I.STORE_BYTES - I.ACT_BASE) // I.ACT_BYTES


class Refused(Exception):
    """The spec does not fit the target. The message names the constraint."""


def _ev_name(n):
    return S.render_ast(n)


# ---------------------------------------------------------------------------
# P2: the order graph
# ---------------------------------------------------------------------------

def order_graph(stmts):
    nodes, edges = [], set()

    def node(n):
        k = _ev_name(n)
        if k not in nodes:
            nodes.append(k)
        return k

    for st in stmts:
        a = st["ast"]
        simple = a[0] == "bin" and a[1] in ("->", "|>") and a[2][0] == "ev" and a[3][0] == "ev"
        if st["kind"] == "pattern" and simple:
            edges.add((node(a[2]), node(a[3])))
        elif st["kind"] == "pattern" and a[0] == "bin" and a[1] == "||" \
                and a[2][0] == "ev" and a[3][0] == "ev":
            node(a[2]); node(a[3])                     # incomparable: nodes, no edge
        elif MUT != "M_PC_COMPOUND_PASS":
            raise Refused("not in the compiler skeleton: %s (only `A -> B`, `A |> B` and "
                          "`A || B` over single events are lowered)" % S.render_statement(st))
    return nodes, edges


def find_cycle(nodes, edges):
    adj = {n: [b for a, b in edges if a == n] for n in nodes}
    state, stack = {}, []

    def dfs(u):
        state[u] = 1
        stack.append(u)
        for v in adj[u]:
            if state.get(v) == 1:
                return stack[stack.index(v):] + [v]
            if v not in state:
                c = dfs(v)
                if c:
                    return c
        state[u] = 2
        stack.pop()
        return None

    for n in nodes:
        if n not in state:
            c = dfs(n)
            if c:
                return c
    return None


def closure(nodes, edges):
    reach = {n: set() for n in nodes}
    for a, b in edges:
        reach[a].add(b)
    changed = True
    while changed:
        changed = False
        for a in nodes:
            add = set().union(*[reach[b] for b in reach[a]]) - reach[a] if reach[a] else set()
            if add:
                reach[a] |= add
                changed = True
    return {(a, b) for a in nodes for b in reach[a]}


def dilworth_width(nodes, edges):
    """minimum chain cover = |V| - maximum matching on the comparability bipartite graph
    (Dilworth / Fulkerson). The relation is the transitive closure of the order edges."""
    rel = edges if MUT == "M_PC_NO_CLOSURE" else closure(nodes, edges)
    succ = {n: [b for a, b in rel if a == n] for n in nodes}
    match = {}

    def aug(u, seen):
        for v in succ[u]:
            if v in seen:
                continue
            seen.add(v)
            if v not in match or aug(match[v], seen):
                match[v] = u
                return True
        return False

    m = sum(1 for u in nodes if aug(u, set()))
    return len(nodes) - m


# ---------------------------------------------------------------------------
# P3: the check-set (from the spec alone)
# ---------------------------------------------------------------------------

def checkset(stmts, hz):
    out = []
    for st in stmts:
        a = st["ast"]
        if st["kind"] != "pattern" or a[0] != "bin" or a[1] not in ("->", "|>"):
            continue
        p = {"pred": "ORDER", "a": _ev_name(a[2]), "op": a[1], "b": _ev_name(a[3]),
             "observed": st["observed"]}
        out.append(p)
        if st["during"]:
            lo = round(float(st["during"][0]) * hz / 1e9)
            hi = round(float(st["during"][1]) * hz / 1e9)
            if MUT == "M_PC_WINDOW_SWAP":
                lo, hi = hi, lo
            out.append({"pred": "WINDOW", "a": p["a"], "op": a[1], "b": p["b"],
                        "lo_cycles": lo, "hi_cycles": hi,
                        "provenance": "observed %d" % st["observed"] if st["observed"] is not None
                        else ("datasheet %s" % st["source"][1] if isinstance(st["source"], tuple)
                              else "unlabelled")})
    return out


# ---------------------------------------------------------------------------
# P4 / P5: lowering and the target
# ---------------------------------------------------------------------------

def words_used(img):
    filler = I.STORE_FILLER
    w = [bytes(img[o:o + I.ACT_BYTES]) for o in range(I.ACT_BASE, I.STORE_BYTES, I.ACT_BYTES)]
    return sum(1 for x in w if x != bytes(filler))


def lower(v1_claims, seed):
    """-> (image, the pe_asm.assemble call that produced it: (lanes, headers, kwargs)).
    The lowering is CALLED (one source); its pe_asm.assemble is wrapped for the call only,
    so the lanes it was handed are recorded, not decoded back out of the image."""
    import run_pit_rt as RT                     # the existing lowering, called (one source)
    import pe_asm
    calls, orig = [], pe_asm.assemble

    def rec(lanes, headers, *a, **kw):
        out = orig(lanes, headers, *a, **kw)
        calls.append((bytes(out), (lanes, headers, a, kw)))
        return out
    rec.__dict__ = orig.__dict__                # assemble.a2_status / program_bytes stay visible
    pe_asm.assemble = rec
    try:
        img = bytes(RT.emulation(v1_claims, random.Random(seed))[0])
    except (RT.NotEmulable, RT.Refused) as e:
        raise Refused("lowering (run_pit_rt.emulation): %s" % e)
    finally:
        pe_asm.assemble = orig
    src = [c for out, c in calls if out == img]
    if not src:
        raise Refused("lowering: the image did not come from a pe_asm.assemble call "
                      "(%d calls recorded), so its lanes are unknown" % len(calls))
    return img, src[-1]


def finish(img, require_cert=False):
    """the image's certification stamp (model/cert_stamp.stamp: compute_j on the image's
    lanes) -- the SAME field pe_asm's command line prints. require_cert: an uncertified
    stamp is Refused with the stamp's reason (cert_stamp.Uncertified's text)."""
    import cert_stamp as CS
    if MUT == "M_PC_JFLOOR_HEAD":
        st = CS.stamp_lanes({k: v[:1] for k, v in CS.image_lanes(img).items()})
    else:
        st = CS.stamp(img)
    if require_cert:
        try:
            CS.require(st, "program")
        except CS.Uncertified as e:
            raise Refused(str(e))
    return st


def target_check(img):
    """P5 on an image -> (words used, the USB co-resident certificate line); Refused by name.
    The USB rule (Wilson 11-12, option (i)) is proof_constants.usb_coresident_problems --
    the same function gate_admissible_images calls."""
    used = words_used(img)
    if used > N_WORDS:
        raise Refused("P5 target: %d program words > %d" % (used, N_WORDS))
    k = PC.load()
    progs = I.lane_programs(img)
    if not PC.usb_receive_live(progs, I):
        return used, "not applicable (no USB receive)"
    bad = [] if MUT == "M_PC_USB_NOCHECK" else PC.usb_coresident_problems(img, k)
    # the deadline margin (usb_wins / usb_j2, Wilson 11-13: 17): pe_isa.usb_problems is
    # the one statement of every USB image rule, applied here as gate_admissible_images does
    bad += [] if MUT == "M_PC_USB_NOCHECK" else I.usb_problems(img)
    if bad:
        raise Refused("P5 target: %s" % "; ".join(bad))
    return used, ("checked: every co-resident lane >= %d (R %d certified + pending_slack %d + "
                  "br1_budget %d; usb_nostall)" % (k["coresident_usb"], k["usb_other_R"],
                                                   k["pending_slack"], k["br1_budget"]))


def branch_budget_line(img):
    """The branch-1 budget B, certified per image (Wilson 11-14, option 1: model/branch_budget).
    No finite B is NOT a refusal: the image is A2-UNCERTIFIED, and the message names the
    diagnostic (branch waits below proof_constants.branch_w_diag) when that is the cause."""
    import branch_budget as BB
    blanes = sorted({ln for ln in I.lane_programs(img)
                     for _w, x in PC.lane_words(img, ln, I) if x["op"] in I.BRANCH_OPS})
    if not blanes:
        return "not applicable (no branch lane)"
    r = BB.image_budget(img)
    if r["B"] is not None:
        return "certified B = %d (branch lanes %s)" % (r["B"], ",".join(map(str, blanes)))
    need = PC.branch_w_diag(len(blanes))
    short = sorted((I.branch_wait(x), ln) for ln in blanes for _w, x in PC.lane_words(img, ln, I)
                   if x["op"] in I.BRANCH_OPS and I.branch_wait(x) < need)
    diag = ("branch waits below %d (proof_constants.branch_w_diag, k = %d branch lanes): %s"
            % (need, len(blanes), ", ".join("lane %d W %d" % (ln, w) for w, ln in short[:6]))
            if short else ("branch waits all >= %d (k = %d): the late words that feed B are on "
                           "other lanes -- see the reason" % (need, len(blanes))))
    return "A2-UNCERTIFIED: no finite branch-1 budget (%s); diagnostic: %s" % (r["reason"], diag)


def a2_line(img):
    """A2's per-lane dispatch jitter from the certificate (Wilson / agent 1 11-14; model/branch_budget):
    each lane's J = 1 + its certified lateness (GapRun.head_late_gap; J = 1 exactly when no word of
    the lane is late, which j1_ok / OptRun.head_valid_nonbranch gives for a non-branch lane), with the
    image's certified branch-1 budget B -- or A2-UNCERTIFIED with the certificate's reason."""
    import branch_budget as BB
    r = BB.image_budget(img)
    if r["B"] is None:
        return "A2-UNCERTIFIED: %s" % r["reason"]
    lanes = ", ".join("lane %d J %d" % (l, 1 + v["max_late"]) for l, v in sorted(r["lanes"].items()))
    return "certified: B = %d; %s (model/branch_budget, lane_j)" % (r["B"], lanes)


def compile_spec(text, seed=1, hz=None, require_cert=False):
    hz = hz or clock.hz()
    log = []
    try:
        parsed = S.parse(text)
    except S.SpecError as e:
        raise Refused("P1 parse: %s" % e)
    stmts = parsed["poset"]
    nodes, edges = order_graph(stmts)
    cyc = find_cycle(nodes, edges)
    if cyc and MUT != "M_PC_NO_CYCLE":
        raise Refused("P2 order: cycle %s (the compiler rejects cycles, guiding doc step 6)"
                      % " -> ".join(cyc))
    width = dilworth_width(nodes, edges) if nodes else 0
    if width > I.N_LANES:
        raise Refused("P2 order: Dilworth width %d > %d lanes (pe_isa.N_LANES)" % (width, I.N_LANES))
    log.append("P2 order: %d event kinds, %d order edges, width %d <= %d" % (len(nodes), len(edges), width, I.N_LANES))
    cs = checkset(stmts, hz)
    log.append("P3 checkset: %d predicates (from the spec alone)" % len(cs))
    img, (lanes, _hdr, _a, _kw) = lower(parsed["v1"], seed)
    used, usb = target_check(img)
    st = finish(img, require_cert)
    log.append("P4 lower: run_pit_rt.emulation, pe_asm accepted; P5 target: %d / %d words; USB: %s"
               % (used, N_WORDS, usb))
    import cert_stamp as CS
    return {"image": img, "lowered": (lanes, _hdr, _a, _kw), "words": used, "width": width,
            "checkset": cs, "log": log, "stamp": st,
            "cert": {"usb_coresident": usb,
                     "branch_budget": branch_budget_line(img),
                     "A2": a2_line(img),
                     "bounds": "UNCERTIFIED (emulate, sniff, re-run the golden: not wired)",
                     "J_floor": CS.line(st)}}


def cli(argv):
    """`python host/poset/compile.py SPEC [--out X.hex] [--require-cert] [--seed N]`: the
    same stamp output and exit rule as pe_asm's command line (`CERT <field JSON>`)."""
    import argparse
    import json
    import cert_stamp as CS
    ap = argparse.ArgumentParser(prog="poset compile")
    ap.add_argument("spec")
    ap.add_argument("--out")
    ap.add_argument("--require-cert", action="store_true")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args(argv)
    with open(a.spec, encoding="utf-8") as fh:
        text = fh.read()
    try:
        r = compile_spec(text, a.seed, require_cert=a.require_cert)
    except Refused as e:
        print("REFUSED: %s" % e)
        return 1
    if a.out:
        CS.write(a.out, r["image"], a.require_cert)
    print("CERT %s" % json.dumps(r["stamp"], sort_keys=True))
    print(CS.line(r["stamp"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(cli(sys.argv[1:]))
