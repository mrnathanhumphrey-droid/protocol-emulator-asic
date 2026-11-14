#!/usr/bin/env python3
"""GATE batch-equiv -- the ARM/dispatcher batch changes nothing it did not mean to.

    python test/gate_batch_equiv.py          (token: GATE batch-equiv: PASSED)

⛔⛔ WHY (Wilson 11-14, deviation 2 + option 2). The (b') / HALF / QUAL /
FALLTHROUGH batch must leave every EXISTING program's behaviour untouched --
its changes are new opcodes' modifiers and a dispatcher that only differs when
a head is empty. The first build did not: priming filled round-robin, the
schedule started a cycle early (125, not 126) and 26 shipped images ran one
cycle ahead -- harmless in content, but every recorded trace was invalid, and
nothing would have said so. So the regression is a GATE, not a one-off:

  * PRE  = the pre-batch RTL, read from git objects at PRE_COMMIT and pinned
           by SHA-256 (never a copied file that can drift);
  * POST = the working tree's src/;
  * the SAME test/ tree, bench (tb_trace) and plusargs for both; every SHIPPED
    image (image_universe programs minus NON_ADMISSIBLE and DELIBERATE -- the
    board images are in the universe), each with its own corpus peer and host
    feed (gate_corpus_trace.feed_args);
  * PASS = every image's pin trace, host-visible stream AND monitor lines
    bit-identical, and the engine's `primed` rising on the SAME cycle in both;
  * ⚠ MONITORS ARE COMPARED, NOT CENTRALLY JUDGED, HERE: these are trace runs
    with no peer (PEER none for non-corpus images), so an edge-paced lane (UART
    RX, SPI target, USB) retires nothing and progress.vh's vacuity line is the
    EXPECTED baseline. The runs use a PRIVATE judging scope and this gate
    requires each run's monitor lines to be identical pre and post -- the batch
    may not change what a monitor says any more than a pin. The same images run
    with real peers under the central judge in gate_corpus_trace and the
    per-protocol gates;
  * MUST-FIRE: POST built with `M_PRIME_NEWPRIO` (the new prefetch target
    during priming too, the batch's first version) -> some image differs.
⚠ The USB programs' own changes (HALF removing the nop, gap 1's fall-through
path) are NOT judged here: those images are judged by their own goldens
(run_usbrx / run_usbaddr / run_usbbuf / run_usbrst). This gate holds the RTL
to "existing programs unchanged".
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "model"), os.path.join(ROOT, "model", "a2")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from toolchain import banner, tool          # noqa: E402
import sim_run                              # noqa: E402

#: the pre-batch RTL: the last commit before the ARM/dispatcher batch
PRE_COMMIT = "ac3443d"
#: SHA-256 of each pre-batch source at PRE_COMMIT (git object content)
PRE_SHA256 = {
    "src/pe_engine.v": "b0b39621382468ea06dfb15e03430354da98155075ea4c505782bcb1b54b6802",
    "src/pe_store.v": "c0e1997ba4bf86b18ff7c6da99faf2d150907ed7d7d6e302f0e2fa8dbad07e67",
    "src/project.v": "e61f1116822ab9405ba4febfc7a8a92fc333b07e1add87f26738011ceed9f1f1",
}
BENCH = ["test/tb_trace.v", "test/fram_spi.v", "test/fram_i2c.v"]
SRCS = ["src/pe_engine.v", "src/pe_store.v", "src/project.v"]
NCYC = 8000

PROBE = r'''
module equiv_probe;
  integer c = 0, p = -1;
  always @(posedge tb_trace.dut.clk) begin
    c = c + 1;
    if (p < 0 && tb_trace.dut.u_eng.primed === 1'b1) p = c;
  end
  final $display("EQUIV_PRIMED %0d", p);
endmodule
'''


def git_blob(path):
    r = subprocess.run(["git", "show", "%s:%s" % (PRE_COMMIT, path)], cwd=ROOT,
                       capture_output=True)
    if r.returncode:
        raise RuntimeError("git show %s:%s failed" % (PRE_COMMIT, path))
    return r.stdout


def pre_problems(blobs, pins=None):
    """[problem] for the pre sources against their pinned SHA-256."""
    pins = PRE_SHA256 if pins is None else pins
    out = []
    for p, b in blobs.items():
        want = pins.get(p)
        got = hashlib.sha256(b).hexdigest()
        if want is None:
            out.append("%s: no pinned SHA-256 (run --pin once and commit it)" % p)
        elif got != want:
            out.append("%s at %s hashes %s, pinned %s" % (p, PRE_COMMIT, got[:12], want[:12]))
    return out


def build(vvp, srcdir, defines=()):
    probe = os.path.join(os.path.dirname(vvp), "equiv_probe.v")
    with open(probe, "w") as fh:
        fh.write(PROBE)
    cmd = ([tool("iverilog"), "-g2012", "-I", os.path.join(ROOT, "test"), "-I", ROOT,
            "-o", vvp, "-s", "tb_trace", "-s", "equiv_probe"]
           + ["-D%s" % d for d in defines]
           + [os.path.join(ROOT, b) for b in BENCH]
           + [os.path.join(srcdir, s) for s in SRCS] + [probe])
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("build failed: %s" % (r.stdout + r.stderr)[-800:])


def shipped():
    """[(name, path, peer)] -- every shipped program image, generated."""
    import corpus
    import gate_degenerate_fields as dgf
    import image_universe as U
    import nonadmissible as NA
    excl = set(NA.NON_ADMISSIBLE) | set(dgf.DELIBERATE)
    peers = {n + ".hex": peer for n, (_fn, peer) in corpus.CORPUS.items()}
    return [(n, p, peers.get(n, "none")) for n, p in sorted(U.default().items())
            if n not in excl]


def run(vvp, path, peer, tr):
    import gate_corpus_trace as G
    from pe_isa import STORE_BYTES
    cmd = sim_run.vvp([vvp, "+IMG=%s" % path, "+NBYTES=%d" % STORE_BYTES,
                       "+PEER=%s" % peer, "+OUT=%s" % tr, "+NCYC=%d" % NCYC]
                      + G.feed_args(path), images=[path])
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    log = r.stdout + r.stderr
    rows = open(tr).read().replace("\r", "").splitlines() if os.path.isfile(tr) else []
    host = [l for l in log.splitlines() if re.match(r"^(RX|TX|HOST|BYTE|PUSH|POP)\b", l)]
    m = re.search(r"^EQUIV_PRIMED (-?\d+)", log, re.M)
    mon = sim_run.monitor_fails(log)
    return rows, host, int(m.group(1)) if m else None, "FATAL" in log, mon


def compare(images, pre_vvp, post_vvp, tmp, stop_at_first=False):
    """{name: problem-or-None}, primed cycles seen."""
    out, primed = {}, set()
    for name, path, peer in images:
        a = run(pre_vvp, path, peer, os.path.join(tmp, "pre_%s.txt" % name))
        b = run(post_vvp, path, peer, os.path.join(tmp, "post_%s.txt" % name))
        primed |= {a[2], b[2]}
        prob = None
        if a[3] or b[3]:
            prob = "FATAL (pre %s, post %s)" % (a[3], b[3])
        elif a[2] != b[2]:
            prob = "primed at %s pre, %s post" % (a[2], b[2])
        elif a[0] != b[0]:
            i = next((k for k, (x, y) in enumerate(zip(a[0], b[0])) if x != y),
                     min(len(a[0]), len(b[0])))
            prob = "pin trace differs at row %d: pre %r post %r" % (
                i, a[0][i] if i < len(a[0]) else None, b[0][i] if i < len(b[0]) else None)
        elif a[1] != b[1]:
            prob = "host stream differs"
        elif a[4] != b[4]:
            prob = "monitor lines differ: pre %s / post %s" % (a[4][:1], b[4][:1])
        out[name] = prob
        if stop_at_first and prob:
            break
    return out, primed


def main(argv) -> int:
    banner("iverilog", "vvp")
    print("GATE batch-equiv -- pre-batch (%s) vs current RTL on every shipped image" % PRE_COMMIT)
    blobs = {p: git_blob(p) for p in SRCS}
    if "--pin" in argv:
        for p, b in blobs.items():
            print('    "%s": "%s",' % (p, hashlib.sha256(b).hexdigest()))
        return 0
    # the PRIVATE judging scope (see the docstring): monitors compared pre vs post
    os.environ[sim_run.SCOPE_ENV] = "equiv-private-%d" % os.getpid()
    probs = pre_problems(blobs)
    for p in probs:
        print("  *** " + p)
    tmp = tempfile.mkdtemp(prefix="pe_equiv_")
    try:
        pre_src = os.path.join(tmp, "pre")
        for p, b in blobs.items():
            os.makedirs(os.path.dirname(os.path.join(pre_src, p)), exist_ok=True)
            with open(os.path.join(pre_src, p), "wb") as fh:
                fh.write(b)
        pre_vvp, post_vvp = os.path.join(tmp, "pre.vvp"), os.path.join(tmp, "post.vvp")
        build(pre_vvp, pre_src, defines=("PE_EQUIV_PRE",))
        build(post_vvp, ROOT)
        images = shipped()
        res, primed = compare(images, pre_vvp, post_vvp, tmp)
        bad = {n: p for n, p in res.items() if p}
        for n, p in sorted(res.items()):
            print("    %-30s %s" % (n, "identical" if not p else "*** " + p))
        print("  %d image(s); %d bit-identical; primed cycle(s) seen %s"
              % (len(res), len(res) - len(bad), sorted(x for x in primed if x is not None)))
        if bad:
            probs.append("%d image(s) differ from the pre-batch build" % len(bad))
        if None in primed:
            probs.append("a run never reported its primed cycle (the probe is vacuous)")
        # must-fire: the new prefetch target during priming
        mut_vvp = os.path.join(tmp, "mut.vvp")
        build(mut_vvp, ROOT, defines=("M_PRIME_NEWPRIO",))
        mres, _ = compare(images, pre_vvp, mut_vvp, tmp, stop_at_first=True)
        hit = [n for n, p in mres.items() if p]
        print("    must-fire: M_PRIME_NEWPRIO (new target while priming)  %s"
              % ("red  ok (%s: %s)" % (hit[0], mres[hit[0]][:60]) if hit else "*** STAYED GREEN"))
        if not hit:
            probs.append("must-fire M_PRIME_NEWPRIO stayed green")
        # must-fire: a pin pinned to a wrong SHA
        mp = pre_problems(blobs, {p: "0" * 64 for p in blobs})
        print("    must-fire: a pre-batch source off its pinned SHA       %s"
              % ("red  ok" if mp else "*** STAYED GREEN"))
        if not mp:
            probs.append("must-fire SHA pin stayed green")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for p in probs:
        print("  *** " + p)
    print("  GATE batch-equiv: %s" % ("FAILED" if probs else "PASSED"))
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
