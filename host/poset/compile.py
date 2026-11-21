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
import math  # noqa: E402

MUTANTS = ("M_PC_NO_CYCLE",      # cycles not refused
           "M_PC_NO_CLOSURE",    # width from direct edges only (path cover, not chain cover)
           "M_PC_WINDOW_SWAP",   # window bounds swapped
           "M_PC_COMPOUND_PASS", # compound patterns silently dropped instead of refused
           "M_PC_USB_NOCHECK",   # the USB co-resident threshold not checked
           "M_PC_JFLOOR_HEAD",   # J floor from each lane's head action only, not every lowered action
           "M_PC_WITHIN_NOARM",  # `within`: the arming check skipped (a window too tight compiles)
           "M_PC_WITHIN_LO_PASS",  # `within`: lo > 0 without `source datasheet` compiles
           "M_PC_ARMRETIRE_OFF",   # lane_cert.ARM_RETIRE off (ArmRetire's cap not applied)
           "M_PC_DRAIN_OFFBY1",    # the generated drain one past the search (the closed form disagrees)
           "M_PC_ARM3_PASS",       # three plain edge ARMs in a row not refused
           "M_PC_FTPC1_PASS",      # a FALLTHROUGH ARM at another ARM's PC+1 not refused
           "M_PC_A2_NOPREM")       # A2's line ignores the window's premise gaps (two verdicts)
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
        if st.get("within"):
            # the obligation's bound is checked on the bus too (an early arrival is the
            # validator's: the program cannot see it without a window counter)
            out.append({"pred": "WINDOW", "a": p["a"], "op": a[1], "b": p["b"],
                        "lo_cycles": round(float(st["within"][0]) * hz / 1e9),
                        "hi_cycles": round(float(st["within"][1]) * hz / 1e9),
                        "provenance": "within (program obligation), else %s" % st["else"]})
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
    """-> (image, the pe_asm.assemble call that produced it: (lanes, headers, kwargs), ROUTE).
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
        em = RT.emulation(v1_claims, random.Random(seed))
        img, route = bytes(em[0]), em[2]
    except (RT.NotEmulable, RT.Refused) as e:
        raise Refused("lowering (run_pit_rt.emulation): %s" % e)
    finally:
        pe_asm.assemble = orig
    src = [c for out, c in calls if out == img]
    if not src:
        raise Refused("lowering: the image did not come from a pe_asm.assemble call "
                      "(%d calls recorded), so its lanes are unknown" % len(calls))
    return img, src[-1], route


# ---------------------------------------------------------------------------
# P4b: `within (lo, hi) else abort | continue` (Wilson 11-15) -- onto the recorded lanes
# ---------------------------------------------------------------------------

#: the ARM's armed-by bound past its release, beyond its lateness: release + L + 4
#: (lane_cert: "writeback <= release + L + 4", the USB lane's arming check)
ARMED_BY = 4
#: a LEVEL's pin moves at its writeback, >= its release + 2 (lane_cert: a dispatch)
WB_MIN = 2
#: the ARM's timeout is the 10-bit delay field (pe_isa.DLY_W)
T_MAX = (1 << I.DLY_W) - 1
NEEDS_COUNTER = "unsupported: needs window counter (V2_MASTER_LIST)"


def _route_pin(route, w):
    """the chip pin a sniffed wire is connected to (tb_rt.v ROUTE: 1 = uo_out[k], 2 = uio_in[k])"""
    code = (route >> (8 * w)) & 0xFF
    return {1: I.UO0 + (code & 7), 2: code & 7}.get(code >> 4)


def _touched(lanes, headers):
    """every pin a word of the lowering names, plus each programmed lane's header pins"""
    pins = {a[1] for acts in lanes.values() for a in acts
            if a[0] != I.OP_LOOP and a[1] < I.N_PINS}
    for ln in lanes:
        pins |= {p for p in headers[ln][:2] if p < I.N_PINS}
    return pins


def _transitions(acts, pin, level):
    """indices of the LEVEL words driving `pin` to `level` from the other level (the lane's
    previous LEVEL on that pin, cyclically: the lane loops)"""
    lv = [(i, a[2]) for i, a in enumerate(acts) if a[0] == I.OP_LEVEL and a[1] == pin]
    return [i for n, (i, l) in enumerate(lv) if l == level and lv[n - 1][1] != level]


def _noops(d, dstar):
    """timed no-ops (LEVEL on PIN_NONE, NopSplit) for `d` cycles, each in [D*, T_MAX]"""
    out = []
    while d > T_MAX:
        step = min(T_MAX, d - dstar)
        out.append((I.OP_LEVEL, I.PIN_NONE, 0, step, 0, 0))
        d -= step
    return out + [(I.OP_LEVEL, I.PIN_NONE, 0, d, 0, 0)]


def _block(a, nxt, p, pre, T, dstar):
    """the words that replace A's word -> (words, the ARM's offset in them)"""
    d1 = pre if pre < 2 * dstar else dstar
    new = [a[:3] + (d1,) + a[4:]] + (_noops(pre - d1, dstar) if pre > d1 else [])
    iarm = len(new)
    arm = (I.OP_ARM, p["B_pin"], p["B_level"], T, 0, 0)
    if p["else"] == "abort":
        new.append(arm)
    else:
        new += [arm + (I.ARM_MOD_FT,), (I.OP_LEVEL, I.PIN_NONE, 0, dstar, 0, 0)]
        if nxt is not None and nxt[0] in (I.OP_SHIFT, I.OP_SHIFTIN, I.OP_SHIFTI):
            new.append((I.OP_LEVEL, I.PIN_NONE, 0, dstar, 0, 0))     # the join (PC+2)
    return new, iarm


def drain_max(k=None):
    """the drain search's ceiling, GENERATED: the post-ARM term the drain pays for is at most
    the ARM's own response (R_base) plus the refill bound (head_slack) for any next word, cap
    or no cap -- a larger drain cannot be what certifies a window"""
    k = k or PC.load()
    return k["R_base"] + k["head_slack"]


#: the certificate per (image, knobs, module switches): the drain search and the gate's mutant
#: passes compile the same images many times
_BB_CACHE = {}


def _budget(img, pg, rd):
    import branch_budget as BB
    import lane_cert as LC
    key = (img, repr(sorted((l, sorted(v.items())) for l, v in pg.items())),
           repr(sorted((l, sorted(v)) for l, v in rd.items())), LC.ARM_RETIRE, BB.EDF_MUT,
           BB.ARMGATE_MUT, BB.NOPIN_MUT, BB.UART_FRAME_MUT, BB.QUEUE_MUT, BB.SLOT,
           BB.SLOT_PER_ARM)
    if key not in _BB_CACHE:
        _BB_CACHE[key] = BB.image_budget(img, premise_gaps=pg, ready=rd)
    return _BB_CACHE[key]


def drain_closed_form(next_delay, k=None):
    """the drain the post-ARM term alone needs (ArmRetire): the word two after a plain ARM is
    late by at most head_slack - ARM_RETIRE_GAP - (the next word's gap: its delay less the
    rebase cycle), so the drain is that, or 0 -- every term read, none typed"""
    import lane_cert as LC
    k = k or PC.load()
    return max(0, k["head_slack"] - LC.ARM_RETIRE_GAP - (next_delay - LC.REBASE))


def drain_closed_form_ft(pc1_delay, pc2_delay, edge_ready, arm_gap, k=None):
    """the `else continue` drain (Wilson 11-20; K6 as ruled 11-20): the least drain, added to
    PC+1's and PC+2's delays, that leaves no word after a FALLTHROUGH ARM late, at J 1 (every
    lateness 0, B 0). None when PC+2 is not ready on its edge entry: the flush's refill floor
    (FlushLate, flush_refill_late + B) then sits on PC+2 at any spacing, so no drain certifies.
    Otherwise the ARM is not retire-capped (ArmRetire covers plain ARMs), so its Z is its own
    response R_base, and a = R_base - its retiring gap. The certificate's three terms:
      t   PC+2 refetched, entered from PC+1 (the timeout path):  a + HS + REBASE - pc1_delay
      e   PC+3 after PC+2 entered by the edge:                    a + HS + REBASE - pc2_delay
      t3  PC+3 after PC+2 entered from PC+1, both gaps drained:   (Z1 + HS + 2 REBASE
          - pc1_delay - pc2_delay) / 2, Z1 = max(R_base + 1 (the disarm cycle), a + D*)
    -- every term read (proof_constants, lane_cert), the ARM's gap from the certificate's
    graph (branch_budget.ft_edge_inputs)"""
    import lane_cert as LC
    if not edge_ready:
        return None
    k = k or PC.load()
    hs, rb = k["head_slack"], LC.REBASE
    a = k["R_base"] - arm_gap
    t = a + hs + rb - pc1_delay
    e = a + hs + rb - pc2_delay
    z1 = max(k["R_base"] + 1, a + k["dstar"])
    t3 = z1 + hs + 2 * rb - pc1_delay - pc2_delay
    return max(0, t, e, -(-t3 // 2))


#: item 1b (Wilson 11-15): the plain-ARM successor prefetch is TWO words deep; the universe's
#: longest run of plain edge ARMs is 2 (sptgt m1 / m3, b3b_a3); the USB lane's 3-run is an FT /
#: SE0 / QUAL chain, outside 1b. A lowering may not make a longer run.
MAX_PLAIN_ARM_RUN = 2


def plain_arm_run_problems(lanes):
    """[problem] for every run of more than MAX_PLAIN_ARM_RUN consecutive plain edge ARMs
    (not FALLTHROUGH, not the two-pin LEVEL ARM) in a lowered lane"""
    out = []
    for ln, acts in sorted(lanes.items()):
        run = 0
        for i, a in enumerate(acts):
            mod = a[6] if len(a) > 6 else 0
            plain = a[0] == I.OP_ARM and not mod & I.ARM_MOD_FT and not mod & I.ARM_MOD_LEVEL2
            run = run + 1 if plain else 0
            if run == MAX_PLAIN_ARM_RUN + 1:
                out.append("lane %d action %d: %d plain ARMs in a row -- item 1b's prefetch is %d "
                           "words deep" % (ln, i, run, MAX_PLAIN_ARM_RUN))
    return [] if MUT == "M_PC_ARM3_PASS" else out


def ft_after_arm_problems(lanes):
    """[problem] for every FALLTHROUGH ARM at another ARM's PC+1 in a lowered lane (Wilson 11-17:
    A's slot fetches B and PC+2 while B wants PC+3 then PC+2 -- a duplicate PC+2 and an
    out-of-order PC+3 that BufFifo does not cover; no corpus image or lowering uses the shape, so
    the compiler refuses it; a program needing both puts a word between them)"""
    out = []
    for ln, acts in sorted(lanes.items()):
        for i in range(1, len(acts)):
            a, b = acts[i - 1], acts[i]
            bmod = b[6] if len(b) > 6 else 0
            if a[0] == I.OP_ARM and b[0] == I.OP_ARM and bmod & I.ARM_MOD_FT:
                out.append("lane %d action %d: a FALLTHROUGH ARM right after an ARM -- the slot's "
                           "buffer has no theorem for it (put a word between them)" % (ln, i))
    return [] if MUT == "M_PC_FTPC1_PASS" else out


def windows(stmts, lowered, route, hz, arm="late", drain="auto", premise="datasheet", ready=False,
            counterfactual=False):
    """`within` lowered, with the DRAIN after every `else abort` window (Wilson 11-15):
      drain="auto"  the default: per statement, the least drain (0..drain_max()) at which the
                    certificate gives the windowed lanes J 1 -- generated, never typed. A
                    statement with `nodrain` gets 0 and the result says so (the stamp is
                    UNCERTIFIED with the reason, compile_spec). `else continue` too (Wilson
                    11-20): its drain spaces PC+1 and PC+2.
      drain=int     that drain on every window (the drain table's sweep)
    Every window also carries the closed form (drain_closed_form, or drain_closed_form_ft for
    `else continue`); the gate checks the search and the closed form agree. The protocol check: a `during` / `within` bound on the event
    after B shorter than the drain is refused by name."""
    # Wilson 11-15: early arming is WITHDRAWN from the compiler (its search and closed form
    # disagree: 5 vs none up to drain_max); the drain table keeps it as a labelled counterfactual
    if arm != "late" and not counterfactual:
        raise Refused("within: arm=%r is withdrawn -- the drain's search and closed form disagree "
                      "there; only the drain table uses it (counterfactual=True)" % arm)
    if drain != "auto":
        return _windows(stmts, lowered, route, hz, arm, drain, premise, ready)
    sids = [i for i, st in enumerate(s_ for s_ in stmts if s_.get("within"))]
    ws = [s_ for s_ in stmts if s_.get("within")]
    chosen = {i: 0 for i in sids}
    found = {}
    for i in sids:
        # Wilson 11-20: `else continue` joins the search on the same rules (its drain also
        # spaces the timeout path's PC+1); `nodrain` is the explicit opt-out for either
        if ws[i].get("nodrain"):
            continue
        for d in range(drain_max() + 1):
            trial = {**chosen, i: d}
            _l, _r, w = _windows(stmts, lowered, route, hz, arm, trial, premise, ready)
            if _j1(w, i):
                found[i] = d
                break
        chosen[i] = found.get(i, 0)
        if MUT == "M_PC_DRAIN_OFFBY1" and i in found:
            chosen[i] += 1
    lanes, route2, w = _windows(stmts, lowered, route, hz, arm, chosen, premise, ready)
    if w is None:
        return lanes, route2, w
    runs = plain_arm_run_problems(lanes) + ft_after_arm_problems(lanes)
    if runs:
        raise Refused("within: %s" % "; ".join(runs))
    # the protocol check: the next event after B, bounded by the spec, must not be pushed past
    for i in sids:
        d = chosen[i]
        if not d:
            continue
        b_ev = ws[i]["ast"][3]
        for st2 in stmts:
            a2 = st2["ast"]
            bound = st2.get("within") or st2.get("during")
            if (bound and a2[0] == "bin" and a2[1] in ("->", "|>") and a2[2] == b_ev):
                hi_c = math.ceil(float(bound[1]) * hz / 1e9)
                if hi_c < d:
                    raise Refused("within: the drain (%d cycles) would push the next action past %s"
                                  % (d, S.render_statement(st2)))
    for x in w["windows"]:
        x["drain"] = chosen[x["sid"]]
        x["drain_found"] = found.get(x["sid"])
        x["nodrain"] = bool(ws[x["sid"]].get("nodrain"))
    w["nodrain"] = [S.render_statement(ws[i]) for i in sids if ws[i].get("nodrain")]
    if w["nodrain"]:
        # what the default would have been (for the stamp's reason)
        trial = {i: (0 if not ws[i].get("nodrain") else None) for i in sids}
        need = {}
        for i in sids:
            if not ws[i].get("nodrain"):
                continue
            for d in range(drain_max() + 1):
                _l, _r, w2 = _windows(stmts, lowered, route, hz, arm, {**chosen, i: d},
                                      premise, ready)
                if _j1(w2, i):
                    need[i] = d
                    break
        w["nodrain_need"] = need
    return lanes, route2, w


def _j1(w, sid):
    """every lane holding a window of statement `sid` certifies at J 1"""
    if not w or w["budget"]["B"] is None:
        return False
    lanes = {x["lane"] for x in w["windows"] if x["sid"] == sid}
    return all(w["budget"]["lanes"][ln]["max_late"] == 0 for ln in lanes)


def _windows(stmts, lowered, route, hz, arm="late", drain=0, premise="datasheet", ready=False):
    """-> (lanes, route, {"windows": [...], "cert": str}) with every `within` lowered, or
    Refused by name.

    Per statement `A -> B within (lo, hi) else X` (A, B single Rise / Fall events):
      * A is a transition the lowering MAKES: a LEVEL word on A's routed pin; B is on a wire
        we do NOT drive (an unconnected wire is routed to the lowest `uio` input no word
        names). B on a pin our program names is refused by name.
      * after each A word: A's spacing becomes the arming lead `pre` (no-ops past D*), then
        the ARM on B's pin and edge (level 1 rise, 0 fall: pe_engine.v l_armedge), timeout
        T = hi + tol - pre, tol = A's lateness + 4 + SYNC_MAX (A's pin moves by its
        writeback; B is seen up to SYNC_MAX later):
          abort    a plain timed ARM: the edge releases the next word (PC+1); a timeout
                   halts the lane (live / armed cleared, l_timeout set, host status ovr)
          continue a FALLTHROUGH ARM: the timeout retires to PC+1, a no-op that runs into
                   PC+2; the edge goes to PC+2 -- the original next word, behind a join
                   no-op when that word is a SHIFT (a FALLTHROUGH edge path cannot start
                   with one: refilled after the flush, pe_isa / lane_cert)
      * the ARMING CHECK (ArmSplit's premise; L = the certificate's lateness of the ARM):
        armed by A + pre + L + 4, before B can be seen (A's writeback >= A + 2, + lo,
        + SYNC_MIN): pre <= lo + 2 + SYNC_MIN - 5 - L. pre < D* is a window too tight,
        refused by name. L comes from the certificate of the windowed image (iterated).
      * lo > 0 rests on the PEER not answering before lo: only a `source datasheet` bound
        says so. Without one, an early B is the program's to catch -> NEEDS_COUNTER.
      * T > the 10-bit timeout field -> NEEDS_COUNTER.
    Options (Wilson 11-15 call 1; the defaults are the c23c6de lowering):
      arm      "late": the ARM as close to lo as the arming check allows; "early": at A + D*
               (with a peer premise the ARM's successor then has lo - D* of guaranteed gap)
      drain    (a): cycles added to the word after the window -- its delay, so lateness drains
      premise  "datasheet": the window's `source datasheet "<part>"` premise, if that part is
               registered and stamp-usable (model/premises.DATASHEETS) -- its ID goes in the
               stamp; "spec": the spec's lo taken as the premise WITHOUT a source (the
               drain table's counterfactual, never stamped); None: image-only
      ready    the prefetch counterfactual: the ARM's successors ready at release
    The premise: B is not seen before A + lo + 2 + SYNC_MIN, so the ARM's successor (released
    at B's edge + 1, ArmSplit.arm_release_bus) is at least lo + 3 + SYNC_MIN - pre after the
    ARM's release -- its release gap in the certificate (branch_budget premise_gaps)."""
    import lane_cert as LC
    import branch_budget as BB
    import pe_asm
    k = PC.load()
    dstar = k["dstar"]
    lanes0, hdr, a_, kw = lowered
    want = []
    for st in stmts:
        if not st.get("within"):
            continue
        a = st["ast"]
        if a[0] != "bin" or a[1] not in ("->", "|>") or a[2][0] != "ev" or a[3][0] != "ev":
            raise Refused("within: `A -> B within ...` takes two single events, got %s"
                          % S.render_ast(a))
        (_e, ka, wa), (_f, kb, wb) = a[2], a[3]
        for kd, nm in ((ka, "A"), (kb, "B")):
            if kd not in ("Rise", "Fall"):
                raise Refused("within: %s is %s; a window's events are Rise / Fall (one pin, "
                              "one direction: an ARM's edge)" % (nm, kd))
        lo_ns, hi_ns = (float(x) for x in st["within"])
        if (lo_ns > 0 and MUT != "M_PC_WITHIN_LO_PASS"
                and not (isinstance(st["source"], tuple) and st["source"][0] == "datasheet")):
            raise Refused("within (%s ns, %s ns): an arrival before lo would be the program's "
                          "to catch -- %s; a lower bound the peer guarantees is written with "
                          "`source datasheet`" % (st["within"] + (NEEDS_COUNTER,)))
        want.append((st, ka, wa[0], kb, wb[0], lo_ns, hi_ns))
    if not want:
        return lanes0, route, None
    touched = _touched(lanes0, hdr)
    # a parked lane's header pin loads too (pe_asm.check_park_overlap): never B's input
    pk = dict(kw.get("park_pins") or (a_[0] if a_ else None) or {})
    touched |= {pk.get(ln, pe_asm.PARK_PIN) for ln in range(I.N_LANES) if ln not in lanes0}
    plan = []
    for st, ka, wa, kb, wb, lo_ns, hi_ns in want:
        pa = _route_pin(route, wa)
        if pa is None or pa not in touched:
            raise Refused("within: A = %s(uio%d) is not a wire the lowering drives" % (ka, wa))
        pb = _route_pin(route, wb)
        if pb is not None and (pb in touched or pb >= I.N_UIO):
            raise Refused("within: B = %s(uio%d) is on a wire we drive (pin %d) -- for our own "
                          "outputs `within` would constrain the delay, not wait" % (kb, wb, pb))
        if pb is None:
            used = touched | {_route_pin(route, w) for w in range(I.N_UIO)}
            free = [q for q in range(I.N_UIO) if q not in used]
            if not free:
                raise Refused("within: no free uio input for B = %s(uio%d)" % (kb, wb))
            pb = free[0]
            route |= (0x20 | pb) << (8 * wb)
            touched.add(pb)
        sites = [(ln, i) for ln, acts in sorted(lanes0.items())
                 for i in _transitions(acts, pa, 1 if ka == "Rise" else 0)]
        if not sites:
            raise Refused("within: no LEVEL word of the lowering makes A = %s(uio%d)" % (ka, wa))
        pid = None
        if isinstance(st["source"], tuple) and st["source"][0] == "datasheet":
            import premises as PM
            pid = PM.datasheet_part(st["source"][1])
            if pid is not None and not PM.stamp_usable(pid)[0]:
                pid = None
        plan.append({"stmt": S.render_statement(st), "A_pin": pa, "B_pin": pb, "B_wire": wb,
                     "sid": len(plan),
                     "premise": pid, "part": (st["source"][1] if isinstance(st["source"], tuple)
                                              else None),
                     "B_level": 1 if kb == "Rise" else 0, "else": st["else"],
                     "lo": math.floor(lo_ns * hz / 1e9), "hi": math.ceil(hi_ns * hz / 1e9),
                     "sites": sites})
    site_plan = {}
    for p in plan:
        for s in p["sites"]:
            if s in site_plan:
                raise Refused("within: two windows after lane %d word %d" % s)
            site_plan[s] = p
    late = {s: (0, 0) for s in site_plan}       # site -> (L of A's word, L of the ARM)
    for _round in range(8):
        lanes, where = {}, {}
        for ln, acts in sorted(lanes0.items()):
            out = []
            new_of = {}                     # old action index -> its index after the insertions
            for i, a in enumerate(acts):
                new_of[i] = len(out)
                p = site_plan.get((ln, i))
                if p is None:
                    out.append(a)
                    continue
                la, larm = late[(ln, i)]
                pre = p["lo"] + WB_MIN + LC.SYNC_MIN - (ARMED_BY + 1) - larm
                if arm == "early" and pre >= dstar:
                    pre = dstar
                if MUT == "M_PC_WITHIN_NOARM":
                    pre = max(pre, dstar)
                if pre < dstar:
                    raise Refused("within: window too tight -- after lane %d word %d the ARM "
                                  "would be armed by A + %d + L %d + %d, but B can be seen from "
                                  "A + %d (lo %d cycles): lo must leave D* = %d"
                                  % (ln, i, dstar, larm, ARMED_BY,
                                     p["lo"] + WB_MIN + LC.SYNC_MIN, p["lo"], dstar))
                T = p["hi"] + la + ARMED_BY + LC.SYNC_MAX - pre
                if T > T_MAX:
                    raise Refused("within: timeout %d cycles > %d (the ARM's 10-bit field) -- %s"
                                  % (T, T_MAX, NEEDS_COUNTER))
                new, iarm = _block(a, acts[i + 1] if i + 1 < len(acts) else None, p, pre, T, dstar)
                where[(ln, i)] = (len(out), len(out) + iarm, pre, T, p)
                out += new
            # ⛔ a LOOP names its head by the lane's ACTION INDEX (pe_asm: `(OP_LOOP, n, head,
            # wait, 0)`); the inserted words shift it, so every head is remapped (found by the
            # drain table: the UART-TX lowering's LOOP head went stale)
            out = [a[:2] + (new_of[a[2]],) + a[3:] if a[0] == I.OP_LOOP else a for a in out]
            # (a): the word after each window (the original next word) drains the lateness;
            # `drain` is one value, or one per statement ({sid: cycles})
            for s_, v in sorted(where.items()):
                if s_[0] != ln:
                    continue
                iarm_, p_ = v[1], v[4]
                dp = drain if isinstance(drain, int) else drain.get(p_["sid"], 0)
                # the first word on the edge path: PC+1 (abort), PC+2 (continue)
                j = iarm_ + (2 if out[iarm_][6:7] == (I.ARM_MOD_FT,) else 1)
                if j < len(out):
                    w_ = out[j]
                    p_.setdefault("next_delay", {})[s_] = w_[3]      # before the drain
                    if dp:
                        if w_[3] + dp > T_MAX:
                            raise Refused("within: drain %d makes lane %d word %d's delay %d > %d"
                                          % (dp, ln, j, w_[3] + dp, T_MAX))
                        out[j] = w_[:3] + (w_[3] + dp,) + w_[4:]
                # `else continue` (FT): the timeout path enters PC+2 from PC+1 and, K6 as ruled
                # 11-20, refetches it there (the swap drops it) -- PC+1's gap before PC+2 gets
                # the same drain, so the refetched word's lateness can drain on that path too
                if out[iarm_][6:7] == (I.ARM_MOD_FT,) and iarm_ + 1 < len(out):
                    p_.setdefault("pc1_delay", {})[s_] = out[iarm_ + 1][3]   # before the drain
                if dp and out[iarm_][6:7] == (I.ARM_MOD_FT,) and iarm_ + 1 < len(out):
                    t_ = out[iarm_ + 1]
                    if t_[3] + dp > T_MAX:
                        raise Refused("within: drain %d makes lane %d word %d's delay %d > %d"
                                      % (dp, ln, iarm_ + 1, t_[3] + dp, T_MAX))
                    out[iarm_ + 1] = t_[:3] + (t_[3] + dp,) + t_[4:]
            lanes[ln] = out
        try:
            img = bytes(pe_asm.assemble(lanes, hdr, *a_, **kw))
        except pe_asm.Reject as e:
            raise Refused("within: pe_asm refused the windowed program: %s" % e)
        pg, used, rd = {}, set(), {}
        for s_, (ia, iarm, pre_, _T, p_) in where.items():
            w0 = (I.read_header(img, s_[0])["base"] - I.ACT_BASE) // I.ACT_BYTES
            if (premise == "datasheet" and p_["premise"]) or premise == "spec":
                pg.setdefault(s_[0], {})[w0 + iarm] = (p_["lo"] + WB_MIN + LC.SYNC_MIN + 1 - pre_)
                used.add(p_["premise"] or "SPEC_LO(%s)" % p_["part"])
            if ready:
                g_ = LC.lane_graph(img, s_[0], I)
                rd.setdefault(s_[0], set()).update(g_[w0 + iarm][1])
        LC.ARM_RETIRE = MUT != "M_PC_ARMRETIRE_OFF"
        bb = _budget(img, pg, rd)
        LC.ARM_RETIRE = True
        fti = BB.ft_edge_inputs(img, pg, rd)
        # the closed forms assume the lane certifies at J 1 apart from its windows: read from
        # the plain lowering's own certificate (same switches, cached)
        b0 = _budget(bytes(pe_asm.assemble(lanes0, hdr, *a_, **kw)), {}, {})
        plain_j1 = {ln: b0["B"] is not None and ln in b0["lanes"]
                    and b0["lanes"][ln]["max_late"] == 0 for ln in lanes}
        info = _win(where, {s_: fti[s_[0]].get(
            (I.read_header(img, s_[0])["base"] - I.ACT_BASE) // I.ACT_BYTES + v[1])
            for s_, v in where.items()}, plain_j1, b0["reason"])
        info["premises"] = sorted(used)
        info["budget"] = bb
        # the certificate's inputs: A2's line reads the same (Wilson 11-16: one input, one verdict)
        info["premise_gaps"], info["ready"] = pg, rd
        if bb["B"] is None:
            return lanes, route, dict(info, cert="UNCERTIFIED: the arming check needs the "
                                      "lateness certificate (%s)" % bb["reason"])
        now = {}
        for s, (ia, iarm, _pre, _T, _p) in where.items():
            w0 = (I.read_header(img, s[0])["base"] - I.ACT_BASE) // I.ACT_BYTES
            lat = bb["lanes"][s[0]]["lat"]
            now[s] = (lat.get(w0 + ia, 0), lat.get(w0 + iarm, 0))
        if all(now[s][0] <= late[s][0] and now[s][1] <= late[s][1] for s in now):
            nopid = sorted({p_["part"] for *_x, p_ in where.values()
                            if p_["part"] and not p_["premise"]})
            return lanes, route, dict(info, cert="certified: every ARM armed before its B can "
                                      "be seen (lateness from the certificate, B = %d%s%s): %s"
                                      % (bb["B"],
                                         "; premises %s" % ",".join(info["premises"])
                                         if info["premises"] else "",
                                         "; no registered source for datasheet %s: image-only"
                                         % ", ".join(repr(x) for x in nopid)
                                         if nopid and premise == "datasheet" else "",
                                         "; ".join(
                                          "lane %d word %d L %d, A L %d" % (s[0], where[s][1],
                                                                            now[s][1], now[s][0])
                                          for s in sorted(now))))
        late = {s: (max(now[s][0], late[s][0]), max(now[s][1], late[s][1])) for s in now}
    return lanes, route, dict(info, cert="UNCERTIFIED: the arming lead did not settle in 8 rounds")


def _win(where, fti=None, plain_j1=None, plain_reason=""):
    """`fti` {(lane, word): branch_budget.ft_edge_inputs' entry for that window's ARM};
    `plain_j1` {lane: the plain lowering's certificate gives the lane J 1} -- where it does not,
    no drain can certify the window and both closed forms say None, with the reason"""
    out = []
    for (ln, i), (ia, iarm, pre, T, p) in sorted(where.items()):
        nd = p.get("next_delay", {}).get((ln, i))
        d1 = p.get("pc1_delay", {}).get((ln, i))
        f = (fti or {}).get((ln, i))
        why = None
        if plain_j1 is not None and not plain_j1.get(ln):
            why = "the plain lowering's lane %d is not J 1 (%s)" % (ln, plain_reason[:120])
            cf = None
        elif p["else"] == "abort":
            cf = drain_closed_form(nd) if nd is not None else None
        elif nd is not None and d1 is not None and f:
            cf = drain_closed_form_ft(d1, nd, f["edge_ready"], f["arm_gap"])
        else:
            cf = None
        out.append({"lane": ln, "A_word": ia, "ARM_word": iarm, "pre": pre, "T": T,
                    "B_pin": p["B_pin"], "else": p["else"], "stmt": p["stmt"], "sid": p["sid"],
                    "next_delay": nd, "pc1_delay": d1,
                    "edge_ready": f["edge_ready"] if f else None, "drain_cf": cf,
                    "cf_none_why": why})
    return {"windows": out}


def finish(img, require_cert=False, premises=()):
    """the image's certification stamp (model/cert_stamp.stamp: compute_j on the image's
    lanes) -- the SAME field pe_asm's command line prints. require_cert: an uncertified
    stamp is Refused with the stamp's reason (cert_stamp.Uncertified's text)."""
    import cert_stamp as CS
    if MUT == "M_PC_JFLOOR_HEAD":
        st = CS.stamp_lanes({k: v[:1] for k, v in CS.image_lanes(img).items()})
    else:
        st = CS.stamp(img)
    if premises:
        # Wilson 11-15: a certificate resting on a peer premise names it in the stamp
        st = dict(st, premises=sorted(premises))
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


def a2_budget(img, win=None):
    """(certificate, premise IDs) for A2's lines: with a `within`, the SAME inputs as the window
    certificate (its premise gaps and prefetch set, Wilson 11-16: one input, one verdict); no
    premise -> the image-only certificate. Without a `within`: image-only."""
    import branch_budget as BB
    if win is None or MUT == "M_PC_A2_NOPREM":
        return BB.image_budget(img), []
    return _budget(img, win["premise_gaps"], win["ready"]), list(win["premises"])


def _prem_note(win, prem):
    if win is None:
        return ""
    return "; premises %s" % ",".join(prem) if prem else "; image-only"


def branch_budget_line(img, win=None):
    """The branch-1 budget B, certified per image (Wilson 11-14, option 1: model/branch_budget).
    No finite B is NOT a refusal: the image is A2-UNCERTIFIED, and the message names the
    diagnostic (branch waits below proof_constants.branch_w_diag) when that is the cause."""
    blanes = sorted({ln for ln in I.lane_programs(img)
                     for _w, x in PC.lane_words(img, ln, I) if x["op"] in I.BRANCH_OPS})
    if not blanes:
        return "not applicable (no branch lane)"
    r, prem = a2_budget(img, win)
    if r["B"] is not None:
        return "certified B = %d (branch lanes %s%s)" % (r["B"], ",".join(map(str, blanes)),
                                                       _prem_note(win, prem))
    need = PC.branch_w_diag(len(blanes))
    short = sorted((I.branch_wait(x), ln) for ln in blanes for _w, x in PC.lane_words(img, ln, I)
                   if x["op"] in I.BRANCH_OPS and I.branch_wait(x) < need)
    diag = ("branch waits below %d (proof_constants.branch_w_diag, k = %d branch lanes): %s"
            % (need, len(blanes), ", ".join("lane %d W %d" % (ln, w) for w, ln in short[:6]))
            if short else ("branch waits all >= %d (k = %d): the late words that feed B are on "
                           "other lanes -- see the reason" % (need, len(blanes))))
    return "A2-UNCERTIFIED: no finite branch-1 budget (%s); diagnostic: %s" % (r["reason"], diag)


def a2_line(img, win=None):
    """A2's per-lane dispatch jitter from the certificate (Wilson / agent 1 11-14; model/branch_budget):
    each lane's J = 1 + its certified lateness (GapRun.head_late_gap; J = 1 exactly when no word of
    the lane is late, which j1_ok / OptRun.head_valid_nonbranch gives for a non-branch lane), with the
    image's certified branch-1 budget B -- or A2-UNCERTIFIED with the certificate's reason. With a
    `within`: the window certificate's inputs, and the premise IDs used (or image-only)."""
    r, prem = a2_budget(img, win)
    if r["B"] is None:
        return "A2-UNCERTIFIED%s: %s" % (_prem_note(win, prem), r["reason"])
    lanes = ", ".join("lane %d J %d" % (l, 1 + v["max_late"]) for l, v in sorted(r["lanes"].items()))
    return "certified: B = %d; %s%s (model/branch_budget, lane_j)" % (r["B"], lanes,
                                                                     _prem_note(win, prem))


def compile_spec(text, seed=1, hz=None, require_cert=False, **win_opts):
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
    img, (lanes, _hdr, _a, _kw), route = lower(parsed["v1"], seed)
    lanes, route, win = windows(stmts, (lanes, _hdr, _a, _kw), route, hz, **win_opts)
    ftb = ft_after_arm_problems(lanes)          # every lowering, with or without a window
    if ftb:
        raise Refused("P4 lower: %s" % "; ".join(ftb))
    if win is not None:
        import pe_asm
        img = bytes(pe_asm.assemble(lanes, _hdr, *_a, **_kw))
        log.append("P4b within: %d window(s) lowered onto the recorded lanes; %s"
                   % (len(win["windows"]), win["cert"]))
        if require_cert and not win["cert"].startswith("certified"):
            raise Refused("within: %s" % win["cert"])
    used, usb = target_check(img)
    st = finish(img, False, [x for x in (win or {}).get("premises", ())
                             if not x.startswith("SPEC_LO")])
    if win and win.get("nodrain"):
        need = win.get("nodrain_need") or {}
        st = dict(st, status="uncertified",
                  reason="within ... else abort|continue nodrain: no drain after the window (%s); the "
                         "generated drain would be %s cycles"
                  % ("; ".join(win["nodrain"]),
                     ", ".join(str(v) for _k, v in sorted(need.items())) or "none found"))
    if require_cert and st["status"] != "certified":
        raise Refused("program: UNCERTIFIED: %s" % st["reason"])
    log.append("P4 lower: run_pit_rt.emulation, pe_asm accepted; P5 target: %d / %d words; USB: %s"
               % (used, N_WORDS, usb))
    import cert_stamp as CS
    return {"image": img, "lowered": (lanes, _hdr, _a, _kw), "words": used, "width": width,
            "checkset": cs, "log": log, "stamp": st, "route": route,
            "windows": win["windows"] if win else [],
            # the window certificate's budget (the gate checks A2's line agrees with it)
            "within_budget": win.get("budget") if win else None,
            "within_inputs": (win.get("premise_gaps"), win.get("ready")) if win else None,
            "cert": {"usb_coresident": usb,
                     "branch_budget": branch_budget_line(img, win),
                     "A2": a2_line(img, win),
                     "bounds": "UNCERTIFIED (emulate, sniff, re-run the golden: not wired)",
                     "J_floor": CS.line(st),
                     "within": win["cert"] if win else "not applicable (no within)"}}


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
