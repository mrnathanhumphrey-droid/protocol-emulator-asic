"""A BENCH WRITE ON THE RISING EDGE IS A SIMULATOR'S CHOICE, NOT THE BENCH'S.

⛔⛔ AUDIT #3. A blocking write to a chip input made right after
`@(posedge clk)` lands in the same timestep as the chip's input flops sampling
that edge, and Verilog leaves the order undefined. iverilog and Verilator
chose differently, and it moved recorded numbers:
  * `tb_half`: lane 1's received bytes differed between simulators (MISO
    written on the edge that samples it);
  * `tb_smoke`: under Verilator `hdr_done` / `jobs` read 94 / 344, the values
    from BEFORE the reset network's +1 cycle -- the race swallowed it;
  * `tb_edge`: every edge-capture latency one cycle apart;
  * `tb_reload`: a false "push in load mode" from `progress.vh`.
Every one was fixed by writing on the falling edge. This gate keeps it so.

THE RULE. In every `test/tb_*.v` (includes expanded), a BLOCKING write to a
CHIP-FACING net -- one reaching the DUT's `ui_in` / `uio_in` / `rst_n` / `ena`,
followed through `assign` / `wire` three levels -- is RED when the most recent
timing control before it is `@(posedge clk)`, or when it sits inside an
`always @(posedge clk)` block. Timing hidden behind a TASK CALL counts: a task
ending on a rising edge leaves its caller there, and a task called from that
context starts there. Both misses were real (`tb_edge`'s peer edges after
`run_cycles`; `tb_reload`'s PROG raise inside `write_image`).

⚠ WHAT IT IS NOT: a Verilog parser. A textual scan for one recognisable
shape, with comments and string literals removed. It does not see `fork`
interleaving, `#` delays mixed with edges, or writes through hierarchical
references; the cross-simulator gate (`test/gate_xsim.py`, the same bench
list below) is what catches a disagreement this misses.

ALLOWLIST: an entry needs EVIDENCE, not only a reason (Wilson). An entry that
matches nothing is itself red, so the list cannot go stale.
MUST-FIRE: `tb_smoke` with its original rising-edge engine start restored
(the known real race; `MF_FIXED` / `MF_RACY`, shared with `gate_xsim`) must be
flagged.
"""
import os
import re
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TESTD = os.path.join(ROOT, "test")
sys.path.insert(0, HERE)
from gate_bench_lint import strip_comments          # noqa: E402

#: ⭐ THE BENCHES WHOSE OUTPUT FEEDS A RECORD OR A CYCLE-EXACT CHECK -- shared
#: with `test/gate_xsim.py`, so the two gates cannot drift apart.
RECORD_BENCHES = ["tb_edge", "tb_fifo", "tb_lock", "tb_pinrange", "tb_reload",
                  "tb_smoke", "tb_status", "tb_v2win", "tb_w"]
#: ... and single (bench, benchset arm) pairs whose checks are cycle-exact,
#: where the whole bench is not: tb_trace runs every corpus image, and the
#: SPI-master witness (`test/run_spim_witness.py`) is the one judged at a
#: cycle-exact rate and phase floor.
RECORD_ARMS = [("tb_trace", "corpus_spim25")]

#: ⭐ THE SHARED MUST-FIRE PLANT (this gate and `test/gate_xsim.py`): the smoke
#: bench's engine start -- the PROG fall, written with the CS release --
#: restored to the rising edge. It is the write that moved `hdr_done` 95 -> 94
#: under Verilator; restoring the reset release alone changed no output.
MF_FIXED = "    @(negedge clk); uio_drv  = 8'hFF;      // CS high = deselected\n"
MF_RACY = "    uio_drv  = 8'hFF;                      // CS high = deselected\n"

#: (bench, net, text the line must contain, reason, evidence)
ALLOW = [
    ("tb_half.v", "peer", "peer[P_MISO] = $random(plant_seed)",
     "THE PLANTED RACE: +PLANT_EDGE_RACE is tb_half's must-fire for its own "
     "receive verdict, off unless the plusarg is given",
     "run_mutants.py requires it RED under iverilog; benchset holds the arm "
     "XFAIL under Verilator"),
    ("tb_v2win.v", "ui_in", "ui_in[4:1] = n; ui_in[5] = 1'b0; ui_in[0] = 1'b0;",
     "the push's data nibble and tag, set on task entry; the chip reads them "
     "only at the synchronised WR edge, which this task raises on a falling "
     "edge at least one cycle later",
     "run_v2window's full measurement -- the dry run's slots and the taken "
     "bit at every lead -- is IDENTICAL under both simulators, and is "
     "re-measured every run by gate_xsim (tb_v2win is on its list), so the "
     "evidence is never a stored number that could go stale"),
]

EV = r"@\s*\(\s*(?:posedge|negedge)\s+clk\s*\)|#\s*\d+|\bwait\s*\("
CALL = r"\b(\w+)\s*(?:\(|;)"
DECL = re.compile(r"\b(task|endtask|function|endfunction)\b")
STR = re.compile(r'"(?:[^"\\]|\\.)*"')


def source(path, root):
    """[(file, line, code)] with `include` expanded, comments and string
    literals removed (a `$display("uio_oe=%b ...")` is not a write)."""
    raw = open(path, encoding="utf-8", errors="replace").read().split("\n")
    out = []
    for i, code in enumerate(strip_comments(raw), 1):
        m = re.match(r'\s*`include\s+"([^"]+)"', code)
        if m:
            inc = os.path.join(root, m.group(1))
            if not os.path.exists(inc):
                inc = os.path.join(root, "test", os.path.basename(m.group(1)))
            if os.path.exists(inc):
                out += source(inc, root)
            continue
        out.append((os.path.basename(path), i, STR.sub('""', code)))
    return out


def chip_nets(lines):
    body = " ".join(c for _f, _i, c in lines)
    ids = lambda s: set(re.findall(r"[A-Za-z_]\w*", s))
    nets = set()
    for port in ("ui_in", "uio_in", "rst_n", "ena"):
        for m in re.finditer(r"\.%s\s*\(([^)]*)\)" % port, body):
            nets |= ids(m.group(1))
    for _ in range(3):
        for m in re.finditer(r"(?:assign|wire)\s+(?:\[[^\]]*\]\s*)?(\w+)\s*"
                             r"(?:\[[^\]]*\])?\s*=\s*([^;]*);", body):
            if m.group(1) in nets:
                nets |= ids(m.group(2))
    return {n for n in nets if not n.isupper() and not n.startswith("P_")
            and n not in ("begin", "end", "if", "else", "assign", "wire")}


def task_tails(lines):
    """{task: the last timing control in its body}, calls followed."""
    bodies, cur = {}, None
    for _f, _i, c in lines:
        m = re.search(r"\btask\s+(?:automatic\s+)?(\w+)", c)
        if m:
            cur = m.group(1); bodies[cur] = []
        elif cur and re.search(r"\bendtask\b", c):
            cur = None
        elif cur:
            bodies[cur].append(c)
    tails = {}
    for _ in range(2):
        for t, body in bodies.items():
            last = tails.get(t)
            for c in body:
                for tok in re.finditer("%s|%s" % (EV, CALL), c):
                    if tok.group(1) is None:
                        last = tok.group(0)
                    elif tails.get(tok.group(1)):
                        last = tails[tok.group(1)]
            tails[t] = last
    return tails


def _pass(lines, nets, tails, entry):
    hits, last, in_pos = [], None, False
    for f, i, c in lines:
        if re.search(r"\b(initial|task|always)\b", c):
            mt = re.search(r"\btask\s+(?:automatic\s+)?(\w+)", c)
            last = entry.get(mt.group(1)) if mt else None
            in_pos = bool(re.search(r"always\s*@\s*\(\s*posedge\s+clk\s*\)", c))
        decl = DECL.search(c)
        for tok in re.finditer("%s|%s|\\b(\\w+)\\s*(\\[[^\\]]*\\])?\\s*=(?![=])"
                               % (EV, CALL), c):
            if tok.group(1) is None and tok.group(2) is None:
                last = tok.group(0)                       # a timing control
            elif tok.group(1) is not None:                # a call
                if decl:
                    continue
                if last and "posedge" in last:
                    entry[tok.group(1)] = last
                if tails.get(tok.group(1)):
                    last = tails[tok.group(1)]
            else:                                         # a blocking write
                name = tok.group(2)
                if name not in nets or c[tok.end():tok.end() + 1] == "=" \
                        or c[tok.start() - 1:tok.start()] == "<" \
                        or re.match(r"\s*(assign|wire|reg|integer|localparam|"
                                    r"parameter)\b", c):
                    continue
                if in_pos or (last and "posedge" in last):
                    hits.append((f, i, name, c.strip()))
    return hits


def scan(path, root=ROOT):
    lines = source(path, root)
    nets, tails, entry = chip_nets(lines), task_tails(lines), {}
    _pass(lines, nets, tails, entry)          # learns each task's entry context
    return _pass(lines, nets, tails, entry)


def allowed(hit):
    f, _i, name, code = hit
    return next((a for a in ALLOW if a[0] == f and a[1] == name and a[2] in code),
                None)


def main() -> int:
    print("=" * 78)
    print("BENCH RACE -- no chip-input write in the timestep of a rising edge")
    print("=" * 78)
    rc, used = 0, set()
    benches = sorted(p for p in os.listdir(TESTD)
                     if p.startswith("tb_") and p.endswith(".v"))
    for top in RECORD_BENCHES:
        if top + ".v" not in benches:
            print("    *** RECORD_BENCHES names %s, which is not on disk" % top)
            rc = 1
    nhits = 0
    for b in benches:
        for h in scan(os.path.join(TESTD, b)):
            a = allowed(h)
            if a:
                used.add(ALLOW.index(a))
                print("    allowed %s:%d %-8s %s" % (h[0], h[1], h[2], a[3][:60]))
                print("            evidence: %s" % a[4][:90])
                continue
            nhits += 1
            rc = 1
            print("    *** %s:%d  `%s` written right after a rising edge: %s"
                  % (h[0], h[1], h[2], h[3][:80]))
    for k, a in enumerate(ALLOW):
        if k not in used:
            print("    *** STALE allowlist entry (matches nothing): %s %s" % a[:2])
            rc = 1
    print("    %d bench(es) scanned, %d unallowed site(s)" % (len(benches), nhits))

    # ⛔ MUST-FIRE: the known real race, restored in a scratch copy
    smoke = open(os.path.join(TESTD, "tb_smoke.v"), encoding="utf-8").read()
    if smoke.count(MF_FIXED) != 1:
        print("    *** must-fire landmark not found in tb_smoke.v")
        rc = 1
    else:
        d = tempfile.mkdtemp(prefix="bench_race_")
        p = os.path.join(d, "tb_smoke.v")
        open(p, "w", encoding="utf-8").write(smoke.replace(MF_FIXED, MF_RACY))
        fired = any(h[3].startswith("uio_drv") for h in scan(p))
        print("    must-fire (tb_smoke's original rising-edge engine start): %s"
              % ("RED" if fired else "*** NOT FLAGGED"))
        rc |= 0 if fired else 1
    print()
    print("  GATE bench-race: %s" % ("PASSED" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
