"""HALT RESET GATE -- the halt IS the reset (WF2 #9-#11, reset-network halt).

⛔⛔ WHY. The power-on reset and the halt clear were two hand-written lists,
and they drifted: the halt cleared PCs, arms and `pin_oe` and nothing else, so
the bit pointers (#9), the pads' levels (#10) and the clocked-lane phase state
(#11 -- `l_ckbit` left at 7 made the first clocked SHIFT after a reload 16
bits long) all survived a reload into the next program. #11 then expanded one
list in BOTH a power-on and a synchronous `!run` branch per block -- correct,
but the clear's fan-in into every register's logic spread the scheduler and
cost ~5 ns on its paths (the attribution canaries, 2026-10-14).
⭐ THE RESET-NETWORK HALT (Wilson): the engine's `rst_n` is ONE FLOP in the
top (`eng_rst_n`: async-cleared by the synchronised power-on reset, following
the run condition on the clock), so the halt IS the reset -- "halt state =
reset state" is literal, and no clear logic sits in any data path. The
keep-list (status the host reads AFTER halting) moves to TWINS on a
power-on-only reset (`por_n`): `twin <= twin | flag`, read as `twin | flag`.

TEXT CHECKS (src/pe_engine.v):
  1. every `always @(posedge clk or negedge rst_n)` block resets ONLY through
     `PE_RST_*` macros -- a raw assignment in a reset branch is a register
     outside the list (RED);
  2. NO synchronous `!run` halt branch anywhere -- the halt is the reset
     network, and a second clear path is the drift this gate exists for;
  3. `PE_RST_KEEP` names EXACTLY the ruled flags' `_m` registers;
  4. the `negedge por_n` block resets EXACTLY their `_k` twins.
NETLIST CHECKS (the yosys JSON, PE_NETLIST_JSON; Wilson's flop rule):
  5. every ENGINE flop is on the engine reset network (`eng_rst_n`), except
     the keep-list twins, which must be on the power-on reset ONLY;
  6. an unreset engine flop must be on gate_reset_audit's allowlist (one
     allowlist, not two) -- any flop on NEITHER network is RED;
  7. the engine reset net is driven by a FLOP whose own reset is the
     power-on reset -- glitch-free by construction (no gate on the net).
  "Engine flop" = a flop whose Q carries a `u_eng.` name that is NOT one of
  the engine's input ports (the top's synchronisers and reset flop drive
  those and carry the alias).

MUST-FIRES (on mutated copies -- never on the tree or the real netlist): a raw
assignment in a reset branch; a `!run` halt branch re-added; an extra name on
the keep-list; an engine flop moved to the power-on reset; a twin moved to the
engine reset; the engine reset driven by a gate. Each must turn the gate red.

Usage: python model/gate_halt_reset.py [--root DIR]
Verdict: `HALT-RESET GATE: PASSED` or `*** FAIL ...`.
"""
import copy
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "model"))
import gate_reset_audit as RA                       # noqa: E402  one allowlist

#: ⚠ SIX REGISTERS, FIVE THAT CARRY STATUS. `l_timeout` (its `_m` / `_k`
#: pair) has no logic reader: the host learns of a timeout only through
#: `sticky_ovr` (status bit 3), and synthesis is expected to prune it. It stays
#: on the keep-list so the reset network is uniform; removal is deferred to
#: after the lock (`docs/REACH.md`). Do not read this set as "six flags that
#: survive a reload" -- five do anything.
KEEP_RULED = {"l_timeout", "sticky_ovr", "config_err", "clk_stretch_err",
              "lane_underrun", "lane_overflow"}
BLOCK_HEAD = "always @(posedge clk or negedge rst_n)"
POR_HEAD = "always @(posedge clk or negedge por_n)"
TOP = "tt_um_protocol_emulator"
ENG_RST = "eng_rst_n"           # the engine reset net, in the top
POR_NET = "rst_n_s"             # the synchronised power-on reset, in the top


def strip_comments(txt):
    txt = re.sub(r"/\*.*?\*/", " ", txt, flags=re.S)
    return clean_build(re.sub(r"//[^\n]*", "", txt))


def clean_build(txt):
    """the text AS THE CLEAN BUILD COMPILES IT: `ifdef/`ifndef/`else/`endif
    resolved with no command-line define (every M_* / S_* mutant off), and
    `define`s inside inactive arms ignored. ⛔ Reading raw text saw BOTH arms
    of a mutant's `ifdef` -- `M_KEEP_ON_HALT` swaps a block header, and the
    gate counted two headers and lost its begin/end balance."""
    out, stack, defined = [], [], set()
    for ln in txt.split("\n"):
        s = ln.strip()
        m = re.match(r"`(ifdef|ifndef)\s+(\w+)", s)
        if m:
            on = (m.group(2) in defined) == (m.group(1) == "ifdef")
            stack.append([on, on])          # [this arm active, any arm taken]
            out.append("")
            continue
        if s.startswith("`else"):
            top = stack[-1]
            top[0] = not top[1]
            top[1] = True
            out.append("")
            continue
        if s.startswith("`endif"):
            stack.pop()
            out.append("")
            continue
        active = all(a for a, _ in stack)
        if active:
            d = re.match(r"`define\s+(\w+)", s)
            if d:
                defined.add(d.group(1))
        out.append(ln if active else "")
    return "\n".join(out)


def macros(txt):
    out = {}
    for ln in strip_comments(txt).replace("\\\n", " ").split("\n"):
        m = re.match(r"\s*`define\s+(\w+)\s*(.*)$", ln)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def assigned(body):
    return set(re.findall(r"(\w+)\s*(?:\[[^\]]*\])?\s*<=", body))


def branch(txt, i):
    j = i
    while txt[j].isspace():
        j += 1
    if txt.startswith("begin", j):
        depth = 0
        for m in re.finditer(r"\b(begin|end)\b", txt[j:]):
            depth += 1 if m.group(1) == "begin" else -1
            if depth == 0:
                return txt[j:j + m.end()], j + m.end()
        raise ValueError("unbalanced begin/end")
    if txt[j] == "`":
        m = re.match(r"`\w+", txt[j:])
        return m.group(0), j + m.end()
    k = txt.index(";", j)
    return txt[j:k + 1], k + 1


def input_ports(engine_txt):
    """the engine's input port names (from the module header)."""
    hdr = strip_comments(engine_txt).split(");", 1)[0]
    return set(re.findall(r"\binput\s+(?:wire\s+)?(?:\[[^\]]*\]\s*)?(\w+)", hdr))


def check_text(engine_txt):
    p = []
    defs = macros(engine_txt)
    rst_defs = {n for n in defs if n.startswith("PE_RST_")}
    keep = assigned(defs.get("PE_RST_KEEP", ""))
    want_m = {k + "_m" for k in KEEP_RULED}
    if keep != want_m:
        p.append("PE_RST_KEEP names %s; it must be exactly the ruled flags' "
                 "_m registers %s" % (sorted(keep), sorted(want_m)))
    txt = strip_comments(engine_txt)
    if re.search(r"else\s+if\s*\(\s*!\s*run\s*\)", txt):
        p.append("a synchronous `else if (!run)` halt branch exists -- the halt "
                 "is the reset network; a second clear path is the drift this "
                 "gate exists for")
    used = set()
    starts = [m.start() for m in re.finditer(re.escape(BLOCK_HEAD), txt)]
    if not starts:
        p.append("no `%s` block found" % BLOCK_HEAD)
    for s in starts:
        line = txt.count("\n", 0, s) + 1
        m = re.compile(r"if\s*\(\s*!\s*rst_n\s*\)").search(txt, s)
        if not m:
            p.append("block at line %d: no `if (!rst_n)` branch" % line)
            continue
        rb, _ = branch(txt, m.end())
        mac = set(re.findall(r"`(PE_RST_\w+)", rb))
        raw = assigned(re.sub(r"`\w+", " ", rb))
        if raw:
            p.append("block at line %d: the reset branch assigns %s directly, "
                     "outside the shared list" % (line, sorted(raw)))
        if not mac:
            p.append("block at line %d: the reset branch expands no PE_RST_* "
                     "macro" % line)
        used |= mac
    for n in sorted(rst_defs - used - {"PE_RST_SHBITP"}):
        p.append("the list defines `%s but no block expands it" % n)
    # 4. the power-on-only twins
    ps = [m.start() for m in re.finditer(re.escape(POR_HEAD), txt)]
    if len(ps) != 1:
        p.append("expected ONE `%s` block (the keep-list twins), found %d"
                 % (POR_HEAD, len(ps)))
    else:
        m = re.compile(r"if\s*\(\s*!\s*por_n\s*\)").search(txt, ps[0])
        twins = assigned(branch(txt, m.end())[0]) if m else set()
        want_k = {k + "_k" for k in KEEP_RULED}
        if twins != want_k:
            p.append("the power-on-only block resets %s; it must be exactly "
                     "the twins %s" % (sorted(twins), sorted(want_k)))
    return p


def check_netlist(nl, eng_inputs):
    """-> (problems, summary) over the yosys JSON netlist dict."""
    p = []
    m = nl["modules"][TOP]
    names = {}
    for nm, info in m["netnames"].items():
        for k, b in enumerate(info["bits"]):
            if isinstance(b, int):
                names.setdefault(b, []).append(nm)
    first = {b: v[0] for b, v in names.items()}      # the reset audit's naming
    drv = {}
    for cn, c in m["cells"].items():
        for port, d in c.get("port_directions", {}).items():
            if d == "output":
                for b in c["connections"][port]:
                    if isinstance(b, int):
                        drv[b] = (cn, c)

    def bit_of(net):
        info = m["netnames"].get(net)
        return info["bits"][0] if info else None

    eng_b, por_b = bit_of(ENG_RST), bit_of(POR_NET)
    if eng_b is None or por_b is None:
        return ["the netlist has no `%s` / `%s` net" % (ENG_RST, POR_NET)], {}
    # 7. the engine reset is a flop's Q, itself on the power-on reset
    d = drv.get(eng_b)
    if not d or "DFF" not in d[1]["type"].upper():
        p.append("`%s` is driven by %s, not a flop -- a gate on the reset net "
                 "can glitch" % (ENG_RST, d[1]["type"] if d else "nothing"))
    elif (d[1]["connections"].get("R") or [None])[0] != por_b:
        p.append("the `%s` flop is not reset by `%s`" % (ENG_RST, POR_NET))
    cnt = {"eng": 0, "twin": 0, "unreset": 0}
    twins = {k + "_k" for k in KEEP_RULED}
    for cn, c in m["cells"].items():
        if "DFF" not in c["type"].upper():
            continue
        q = c["connections"].get("Q", [None])[0]
        eng = [n for n in names.get(q, []) if n.startswith("u_eng.")]
        if not eng:
            continue
        base = {re.sub(r"\[\d+\]$", "", n)[len("u_eng."):] for n in eng}
        if base & eng_inputs:
            continue                    # a top flop driving an engine input
        is_twin = bool(base & twins)
        r = (c["connections"].get("R") or c["connections"].get("S") or [None])[0]
        label = sorted(eng, key=len)[0]
        if r is None:
            if first.get(q, "").split("[")[0] in RA.ALLOWED:
                cnt["unreset"] += 1
            else:
                p.append("engine flop %s has NO reset and is not on the reset "
                         "audit's allowlist" % label)
        elif is_twin:
            if r == por_b:
                cnt["twin"] += 1
            else:
                p.append("keep-list twin %s is not on the power-on reset -- a "
                         "halt would erase the status" % label)
        elif r == eng_b:
            cnt["eng"] += 1
        else:
            p.append("engine flop %s is on neither network (reset by %s)"
                     % (label, ",".join(names.get(r, ["?"]))[:40]))
    return p, cnt


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read().replace("\r\n", "\n")


def main():
    root = os.path.join(ROOT, "src")
    if "--root" in sys.argv:
        root = os.path.abspath(sys.argv[sys.argv.index("--root") + 1])
    eng = read(os.path.join(root, "pe_engine.v"))
    print("HALT RESET -- the halt IS the reset network (%s)"
          % os.path.relpath(root, ROOT))
    probs = check_text(eng)
    nlp = os.environ.get("PE_NETLIST_JSON", "")
    if not nlp or not os.path.isfile(nlp):
        probs.append("no netlist at PE_NETLIST_JSON=%r -- the flop rule "
                     "cannot be checked: RED, not a skip" % nlp)
        nl = None
    else:
        with open(nlp, encoding="utf-8") as fh:
            nl = json.load(fh)
        ins = input_ports(eng)
        np_, cnt = check_netlist(nl, ins)
        probs += np_
        print("  netlist: %d engine flop(s) on %s, %d keep-list twin(s) on "
              "%s, %d allowlisted unreset" % (cnt.get("eng", 0), ENG_RST,
                                             cnt.get("twin", 0), POR_NET,
                                             cnt.get("unreset", 0)))
    for q in probs:
        print("  *** " + q)

    # ---- must-fires, on mutated copies ---------------------------------
    mf_ok = True
    t1 = eng.replace("      `PE_RST_MAIN\n      `PE_RST_KEEP\n",
                     "      `PE_RST_MAIN\n      `PE_RST_KEEP\n"
                     "      stray_reg <= 1'b0;\n", 1)
    t2 = eng.replace("    if (!rst_n)      `PE_RST_NOW",
                     "    if (!rst_n)      `PE_RST_NOW\n"
                     "    else if (!run)   `PE_RST_NOW", 1)
    t3 = eng.replace("lane_overflow_m   <= {N_LANES{1'b0}}; \\",
                     "lane_overflow_m   <= {N_LANES{1'b0}}; \\\n"
                     "      l_ckbit[0] <= {BPW{1'b0}}; \\", 1)
    cases = [("raw assignment in a reset branch", t1, "text"),
             ("a `!run` halt branch re-added", t2, "text"),
             ("an extra name on the keep-list", t3, "text")]
    if nl is not None:
        m = nl["modules"][TOP]
        eng_b = m["netnames"][ENG_RST]["bits"][0]
        por_b = m["netnames"][POR_NET]["bits"][0]
        names = {}
        for nm, info in m["netnames"].items():
            for b in info["bits"]:
                if isinstance(b, int):
                    names.setdefault(b, []).append(nm)

        def mutate(pick, new_r):
            n2 = copy.deepcopy(nl)
            mm = n2["modules"][TOP]
            for cn, c in mm["cells"].items():
                if "DFF" in c["type"].upper() and pick(c):
                    c["connections"]["R"] = [new_r]
                    return n2
            return None

        def q_has(c, pred):
            q = c["connections"].get("Q", [None])[0]
            return any(pred(n) for n in names.get(q, []))

        n1 = mutate(lambda c: (c["connections"].get("R") or [None])[0] == eng_b
                    and q_has(c, lambda n: n.startswith("u_eng.l_pc")), por_b)
        n2 = mutate(lambda c: q_has(c, lambda n: n.startswith(
            "u_eng.config_err_k")), eng_b)
        n3 = copy.deepcopy(nl)
        d3 = [c for c in n3["modules"][TOP]["cells"].values()
              if eng_b in sum([v for k, v in c["connections"].items()
                               if c.get("port_directions", {}).get(k) ==
                               "output"], [])]
        if d3:
            d3[0]["type"] = "$_AND_"
        cases += [("an engine flop moved to the power-on reset", n1, "nl"),
                  ("a keep-list twin moved to the engine reset", n2, "nl"),
                  ("the engine reset driven by a gate", n3 if d3 else None,
                   "nl")]
    for name, mut, kind in cases:
        applied = mut is not None and mut is not eng
        if kind == "text":
            applied = mut != eng
            red = applied and bool(check_text(mut))
        else:
            red = applied and bool(check_netlist(mut, input_ports(eng))[0])
        print("  must-fire  %-44s %s" % (name, "red" if red else
                                         "*** NOT RED%s" % (
                                             "" if applied else
                                             " (the mutation did not apply)")))
        mf_ok = mf_ok and red
    if nl is None:
        print("  must-fire  (the three netlist must-fires need the netlist)")

    if not probs and mf_ok:
        print("HALT-RESET GATE: PASSED")
        return 0
    print("*** FAIL halt_reset: %d problem(s)%s" % (
        len(probs), "" if mf_ok else "; a must-fire did not fire"))
    return 1


if __name__ == "__main__":
    sys.exit(main())
