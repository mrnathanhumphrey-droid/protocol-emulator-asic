"""poset compile -- the COMPILER SKELETON (Agent 2, 11-12; brief item 4).

A v2 poset spec in; out come the three artifacts of guiding doc step 6, as far as the
skeleton reaches, plus a refusal that NAMES the failing constraint when the spec does not fit:

  image      the chip program, through the existing ISA path (pe_proto / pe_asm, and
             pe_isa as the one encoder): every admissibility check applies
  checkset   the validator's predicates, derived from the SPEC ALONE, independently of
             the image (guiding doc §5: a check-set compiled from the same source as the
             program and run against its own output is circular)
  cert       the A2 certificate. OWED in the skeleton: the delegated lowering returns an
             image, not lanes, so pe_asm.compute_j and the A2 terms cannot run on it yet.

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
           "M_PC_USB_NOCHECK")   # the USB co-resident threshold not checked
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
    import run_pit_rt as RT                     # the existing lowering, called (one source)
    try:
        img = RT.emulation(v1_claims, random.Random(seed))[0]
    except (RT.NotEmulable, RT.Refused) as e:
        raise Refused("lowering (run_pit_rt.emulation): %s" % e)
    return bytes(img)


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
    if bad:
        raise Refused("P5 target: %s" % bad[0])
    return used, "checked: every co-resident lane >= %d (R_usb %d + pending_slack %d)" % (
        k["dstar_retire_usb"], k["R_usb"], k["pending_slack"])


def compile_spec(text, seed=1, hz=None):
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
    img = lower(parsed["v1"], seed)
    used, usb = target_check(img)
    log.append("P4 lower: run_pit_rt.emulation, pe_asm accepted; P5 target: %d / %d words; USB: %s"
               % (used, N_WORDS, usb))
    return {"image": img, "words": used, "width": width, "checkset": cs, "log": log,
            "cert": {"usb_coresident": usb,
                     "A2": "OWED (lanes not exposed by the delegated lowering)",
                     "bounds": "UNCERTIFIED (emulate, sniff, re-run the golden: not wired)",
                     "J_floor": "OWED (needs pe_asm.compute_j on the lowered lanes)"}}
