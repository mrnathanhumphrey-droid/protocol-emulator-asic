"""Scratch mutants on the TX QUEUE HEAD -- one patch each, applied at RUN TIME
to the CURRENT `src/project.v` (Wilson): the frozen RTL carries no ifdef, and
a mutant cannot quietly become a test of stale code.

  S_HEAD_NEWER  a queue's head read from its NEWER slot (`~tx_rp`): bytes
                leave out of order
  S_QUEUE_SWAP  queues 0<->1 (and 2<->3) have their heads swapped: a lane
                pops its own queue but sends the OTHER queue's byte

⛔ ONE LANDMARK PER TX VARIANT -- (a) the single head on the action's queue,
(b4) the per-queue head vector -- and EXACTLY ONE must occur in src/. None
(src/ moved) or both is RED (SystemExit), never a skip; `scratch_sub` also
refuses a landmark inside a mutant's ifdef (dead code). The declarations live
in `test/run_mutants.py` (`SCRATCH_MUTANTS`), the registered killer.
"""
import os

from toolchain import scratch_sub

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_A = "  wire [7:0]    tx_head  = tx_mem[{q_sel, tx_rp[q_sel]}];\n"
_B = "      assign q_heads[8*gq +: 8] = tx_mem[{gq[1:0], tx_rp[gq]}];\n"
PATCHES = {
    "S_HEAD_NEWER": [
        (_A, "  wire [7:0]    tx_head  = tx_mem[{q_sel, ~tx_rp[q_sel]}];\n"),
        (_B, "      assign q_heads[8*gq +: 8] = tx_mem[{gq[1:0], ~tx_rp[gq]}];\n"),
    ],
    "S_QUEUE_SWAP": [
        (_A, "  wire [7:0]    tx_head  = tx_mem[{q_sel ^ 2'd1, "
             "tx_rp[q_sel ^ 2'd1]}];\n"),
        (_B, "      assign q_heads[8*gq +: 8] = tx_mem[{gq[1:0] ^ 2'd1, "
             "tx_rp[gq ^ 1]}];\n"),
    ],
}


def patched_project(name, src_text=None):
    """The current src/project.v with mutant `name` applied -> text."""
    if src_text is None:
        with open(os.path.join(ROOT, "src", "project.v"), encoding="utf-8") as fh:
            src_text = fh.read()
    txt = src_text.replace("\r\n", "\n")
    hits = [(a, b) for a, b in PATCHES[name] if a in txt]
    if len(hits) != 1:
        raise SystemExit("*** %s: %d head landmark(s) in src/project.v, need "
                         "exactly 1 (one per TX variant) -- the patch no longer "
                         "applies: RED, not a skip" % (name, len(hits)))
    return scratch_sub(txt, hits[0][0], hits[0][1], name)


def patched_srcdir(name, scratch):
    """A scratch copy of src/ with `name` applied to project.v -> its dir."""
    d = os.path.join(scratch, "src_" + name.lower())
    os.makedirs(d, exist_ok=True)
    for f in ("pe_engine.v", "pe_store.v", "project.v"):
        with open(os.path.join(ROOT, "src", f), encoding="utf-8") as fh:
            txt = fh.read()
        if f == "project.v":
            txt = patched_project(name, txt)
        with open(os.path.join(d, f), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(txt)
    return d
