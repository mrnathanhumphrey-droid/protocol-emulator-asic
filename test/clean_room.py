"""CLEAN-ROOM CHECK -- every artefact the suite loads has a recipe.

THE ONE CLAIM: with every generated, gitignored artefact removed, running the
recorded generators reproduces them all, byte for byte, and the suite passes.

⛔⛔ WHY, FROM A REAL DEFECT. `tb_edge` loads `noop_image_h19.hex`, and NO
COMMAND IN THE REPO PRODUCED IT: it was made by hand and then gitignored, so it
was invisible. The one-encoder move regenerated the images, a guessed `half`
value silently replaced it, and must-fire 5b failed -- because the two `half`
values are a DIFFERENTIAL (19 - 7 = 12) that nothing recorded. A hand-made
artefact behind a `.gitignore` is a dependency with no source.
⇒ CI already proves this for TRACKED images: a fresh clone has them or the job
  dies. This is the same proof extended to the untracked ones.

⭐ AND IT COMPARES CONTENT, NOT JUST PRESENCE. A recipe that produces a
DIFFERENT file than the one sitting there is exactly the h19 case, and a
presence check would have passed it.

⛔ NOTHING IS DELETED. The artefacts are MOVED to a timestamped quarantine
directory and the path is printed; the generators then rebuild them. If a
rebuild is wrong, the originals are still there to compare against, and the
quarantine is the user's to remove.
"""

from __future__ import annotations

import os
import hashlib
import shutil
import subprocess
import sys
import time
from toolchain import banner, tool          # noqa: E402  ruling V
import sim_run                              # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)          # so `toolchain` imports from any cwd
ROOT = os.path.dirname(HERE)
QUAR = os.environ.get(
    "PE_QUARANTINE",
    os.path.join(os.environ.get("TEMP", "/tmp"), "pe_cleanroom"))

# ⛔⛔ ORDER IS LOAD-BEARING: THE MANIFEST WRITER MUST RUN LAST. `corpus.py`
# writes the corpus images but `make_smoke_image.py --all` writes
# `artefacts.sha256` -- hashing whatever is on disk WHEN IT RUNS. With the
# manifest writer first, a corpus change was pinned at its PREVIOUS hash, so
# the manifest was one regeneration stale for exactly the files the other
# generator owns.
# ⚠ MEASURED, not foreseen: after rewriting the corpus's self-clocked sites,
# `corpus_all5.hex` on disk read d1e2508711f0 while the manifest still said
# d1db8a89415b -- and the bit-identity check reported it as UNCHANGED, which is
# the dangerous direction. A manifest that lags is worse than no manifest,
# because it answers.
# ⛔⛔ AND IT ALSO RUNS FIRST, FROM A RED CI RUN (54f010a). `corpus.py`'s
# pad-collision audit reads the shared image universe, which names every bench
# arm -- including `edge_image`, `five_image` and `stress_image`, which only
# `make_smoke_image.py --all` writes. On a fresh clone they did not exist yet,
# so the audit refused and the coverage sweep had no images; this box carried
# old generated copies and never saw it. Measured on a clean export of 54f010a:
# this order succeeds and leaves `artefacts.sha256` byte-identical to the
# tracked one. The LAST run is still the one whose manifest stands.
GENERATORS = [
    [sys.executable, os.path.join(HERE, "make_smoke_image.py"), "--all"],
    [sys.executable, os.path.join(HERE, "corpus.py")],
    [sys.executable, os.path.join(HERE, "make_smoke_image.py"), "--all"],
]


def run(cmd, cwd=ROOT):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=cwd)


def ignored_artefacts():
    """Gitignored files under test/ -- the ones CI cannot vouch for."""
    r = run(["git", "status", "--ignored", "--porcelain", "test/"])
    out = []
    for ln in r.stdout.splitlines():
        if not ln.startswith("!! "):
            continue
        rel = ln[3:].strip()
        if rel.endswith("/"):
            continue
        # ⛔ PROBE OUTPUTS ARE NOT SUITE ARTEFACTS. Experiments write
        # `probe_*` by rule, and nothing in the suite loads them, so demanding
        # a recipe for one would make this gate red on a leftover scratch file
        # -- and the fix would be to delete evidence rather than to fix a
        # dependency. Reserved names are the subject here.
        if rel.endswith(".hex") and not os.path.basename(rel).startswith("probe_"):
            out.append(rel)
    return sorted(out)


def quarantine(files, tag):
    d = os.path.join(QUAR, "%s_%s" % (time.strftime("%H%M%S"), tag))
    os.makedirs(d, exist_ok=True)
    for rel in files:
        src = os.path.join(ROOT, rel)
        if os.path.isfile(src):
            shutil.move(src, os.path.join(d, os.path.basename(rel)))
    return d


def regenerate():
    for cmd in GENERATORS:
        r = run(cmd)
        if r.returncode != 0:
            return False, "%s failed: %s" % (cmd[-1], (r.stdout + r.stderr)[-300:])
    return True, None


def suite():
    """The benches that LOAD images. Enough to prove the recipes are right."""
    sp = os.environ.get("PE_SCRATCH", os.path.join(QUAR, "build"))
    os.makedirs(sp, exist_ok=True)
    out = []
    # ⭐ tb_tx JOINS THEM BECAUSE `tx_image.hex` IS NOW A PINNED ARTEFACT. The
    # manifest hashes the recipe's OUTPUT, which catches a recipe change -- but
    # a tracked image that no bench in the clean room LOADS is the
    # named-artefact-with-no-implementation class this project has already been
    # bitten by (`noop_image_h19.hex`, made by hand and then gitignored, with
    # tb_edge depending on it). Loading it here proves the recipe produces
    # something the engine can actually run in a clean tree.
    # ⛔ ITS PLUSARGS ARE REQUIRED, NOT OPTIONAL: tb_tx refuses to start
    # without +IMG and +NBYTES, because an image that never loaded emits
    # nothing and "no bytes" would read as a queue fault rather than as a
    # missing file. NBYTES is counted from the quarantined copy.
    extra_tx = []
    txp = os.path.join(ROOT, "test", "tx_image.hex")
    if os.path.isfile(txp):
        with open(txp, encoding="ascii") as fh:
            extra_tx = ["+IMG=test/tx_image.hex",
                        "+NBYTES=%d" % len([w for w in fh.read().split() if w]),
                        "+NCYC=6000"]
    extra_half = []
    hfp = os.path.join(ROOT, "test", "half_image.hex")
    if os.path.isfile(hfp):
        with open(hfp, encoding="ascii") as fh:
            extra_half = ["+IMG=test/half_image.hex",
                          "+NBYTES=%d" % len([w for w in fh.read().split() if w]),
                          "+NCYC=40000"]
    extra_i2c = []
    i2p = os.path.join(ROOT, "test", "i2cframe_image.hex")
    if os.path.isfile(i2p):
        with open(i2p, encoding="ascii") as fh:
            extra_i2c = ["+IMG=test/i2cframe_image.hex",
                         "+NBYTES=%d" % len([w for w in fh.read().split() if w]),
                         "+NCYC=40000",
                         # ⛔ THE DUMP GOES TO A SCRATCH NAME inside the
                         # quarantine, not to the repo: the clean room's whole
                         # point is that it does not write where the tree is.
                         "+DUMP=probe_cleanroom_i2c.bin"]
    for name, top, srcs, pargs in (
        ("tb_smoke", "tb_smoke", ["test/tb_smoke.v"], []),
        ("tb_edge", "tb_edge", ["test/tb_edge.v"], []),
        ("tb_tx", "tb_tx", ["test/tb_tx.v"], extra_tx),
        ("tb_half", "tb_half", ["test/tb_half.v"], extra_half),
        ("tb_i2c", "tb_i2c", ["test/tb_i2c.v", "test/fram_i2c.v"], extra_i2c),
    ):
        if name in ("tb_tx", "tb_half", "tb_i2c") and not pargs:
            out.append((name, False, "its image is absent"))
            continue
        vvp = os.path.join(sp, name + ".vvp")
        b = run([tool("iverilog"), "-g2012", "-o", vvp, "-s", top]
                + [os.path.join(ROOT, s) for s in srcs]
                + [os.path.join(ROOT, "src", f)
                   for f in ("pe_engine.v", "pe_store.v", "project.v")])
        if b.returncode != 0:
            out.append((name, False, "build failed"))
            continue
        r = run(sim_run.vvp([vvp] + pargs,
                            images=sim_run.images_in(pargs)
                            + sim_run.hardcoded_images(top)))
        txt = r.stdout + r.stderr
        ok = ("PASS" in txt and "FAILURE" not in txt)
        why = "PASS" if ok else [l for l in txt.splitlines()
                                 if "FAIL" in l or "Unable" in l][:1]
        out.append((name, ok, why))
    return out


def explain_toolchain(tc_stored, tc_live, tc_diff):
    """⭐⭐ WHICH CAUSE A HASH MISMATCH HAS, printed where the decision is made.

    A mismatch with no toolchain reading leaves "it must be the tools"
    available as an unfalsifiable excuse for re-pinning a hash -- which is how
    a real recipe change gets laundered. So the comparison goes in front of
    whoever is about to edit the manifest.

    ⚠ It names a CANDIDATE, never a verdict: a differing tool is a hypothesis
    to be confirmed by rebuilding on the stored version, not a licence.
    """
    import toolchain as _tc
    print()
    print("        --- toolchain: stored (manifest) vs live ---")
    if not tc_stored:
        print("        NO TOOLCHAIN HEADER in the manifest, so it cannot vouch")
        print("        for what built these hashes. Re-run")
        print("        `make_smoke_image.py --all` to record one; until then a")
        print("        recipe change and a tool change are indistinguishable.")
    elif not tc_diff:
        for name, _c in _tc.PROBES:
            print("        %-10s %s" % (name, tc_live.get(name, _tc.MISSING)))
        print("        IDENTICAL on every tool -- the toolchain does NOT")
        print("        explain this mismatch. Treat it as a RECIPE CHANGE")
        print("        until shown otherwise.")
    else:
        for name, s, l in tc_diff:
            print("        %-10s stored %s" % (name, s))
            print("        %-10s live   %s" % ("", l))
        print("        A tool reads differently: a CANDIDATE explanation, not")
        print("        a verdict. Confirm by rebuilding on the stored version")
        print("        before re-pinning any hash.")


def selftest() -> int:
    """⛔ PRICE THE EXPLANATION (standing rule 3), without touching the real
    manifest -- mutating `artefacts.sha256` to test the gate that reads it is
    the one experiment that could leave the reference wrong.
    """
    import io
    import contextlib
    rc = 0
    full = {"python": "1", "iverilog": "2", "verilator": "3", "yosys": "4"}
    cases = (
        ("no header",      {},   full, "NO TOOLCHAIN HEADER"),
        ("identical",      full, full, "RECIPE CHANGE"),
        ("one tool moved", full, dict(full, yosys="9"), "CANDIDATE"),
    )
    print("  --- must-fire: the mismatch explanation says which cause ---")
    for name, stored, live, needle in cases:
        import toolchain as _tc
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            explain_toolchain(stored, live, _tc.compare(stored, live))
        got = needle in buf.getvalue()
        print("    %-16s -> says %-20s %s"
              % (name, needle, "yes" if got else "*** NO"))
        if not got:
            rc = 1
    # and the three cases must not all print the same thing
    outs = []
    for _n, stored, live, _needle in cases:
        import toolchain as _tc
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            explain_toolchain(stored, live, _tc.compare(stored, live))
        outs.append(buf.getvalue())
    if len(set(outs)) != 3:
        print("    *** the three causes do not print distinctly, so the")
        print("        explanation cannot be separating them")
        rc = 1
    else:
        print("    the three causes print distinctly")
    return rc


def main() -> int:
    banner("iverilog", "vvp")   # ruling V2: the log names the binary that ran
    rc = 0
    print()
    print("=" * 78)
    print("CLEAN-ROOM CHECK -- does every loaded artefact have a recipe?")
    print("=" * 78)
    files = ignored_artefacts()
    print("  gitignored .hex under test/ : %d" % len(files))
    for f in files:
        print("    %s" % f)
    if not files:
        print("  *** nothing to check -- either all images are tracked, or the")
        print("      enumeration is wrong. Either way this gate is vacuous.")
        return 1

    d = quarantine(files, "main")
    print()
    print("  quarantined to %s" % d)
    print("  ⛔ MOVED, NOT DELETED -- the originals are the comparison, and")
    print("     removing them is the user's call.")
    missing = [f for f in files if not os.path.isfile(os.path.join(ROOT, f))]
    print("  removed from the tree : %d of %d" % (len(missing), len(files)))

    ok, err = regenerate()
    print()
    print("  --- regenerate from the recorded recipes ---")
    if not ok:
        print("    *** %s" % err)
        return 1
    print("    generators ran")

    # ---- compare against the TRACKED MANIFEST, not the quarantined copy ----
    # ⛔⛔ THE OLD COPY WAS NEVER A VALID REFERENCE. This gate first compared
    # regenerated content with the file it had just quarantined, and duly
    # "found" a difference that was the OLD copy's fault -- a stale file is
    # only authoritative if it was right, which is exactly what is in question.
    # A tracked `artefacts.sha256` has provenance: a recipe change must show up
    # as a diff in the same commit, and an artefact that comes out differently
    # on another machine or tool version is visible too, which a local old copy
    # could never reveal.
    man = {}
    mpath = os.path.join(HERE, "artefacts.sha256")
    if os.path.isfile(mpath):
        with open(mpath, encoding="ascii") as fh:
            for ln in fh:
                if ln.startswith("#") or not ln.strip():
                    continue
                parts = ln.split()
                man[parts[1]] = parts[0]
    if not man:
        print()
        print("  *** no artefacts.sha256 -- nothing to compare against, so this")
        print("      gate would pass by having no reference. Run")
        print("      `python test/make_smoke_image.py --all` to write it.")
        return 1

    # ---- the toolchain the manifest was written with -----------------------
    import toolchain
    tc_stored = toolchain.parse(mpath)
    tc_live = toolchain.probe()
    tc_diff = toolchain.compare(tc_stored, tc_live)

    back, absent, differ, unpinned = [], [], [], []
    for f in files:
        base = os.path.basename(f)
        now = os.path.join(ROOT, f)
        if not os.path.isfile(now):
            absent.append(f)
            continue
        back.append(f)
        with open(now, "rb") as fh:
            h = hashlib.sha256(fh.read()).hexdigest()
        if base not in man:
            unpinned.append(base)
        elif man[base] != h:
            differ.append(base)
    print()
    print("  --- regenerated content vs the tracked manifest ---")
    print("    manifest pins : %d artefacts" % len(man))
    print("    reproduced    : %d of %d" % (len(back), len(files)))
    if absent:
        print("    *** NO RECIPE PRODUCES: %s" % ", ".join(absent))
        print("        That is the h19 class: a dependency with no source.")
        rc = 1
    if unpinned:
        print("    *** NOT IN THE MANIFEST: %s" % ", ".join(unpinned))
        print("        An artefact the suite loads with no pinned hash is")
        print("        unreviewable -- a recipe change to it would show as")
        print("        nothing in a diff.")
        rc = 1
    if differ:
        print("    *** HASH MISMATCH vs the manifest: %s" % ", ".join(differ))
        print("        Either a recipe changed without updating the manifest in")
        print("        the same commit, or this artefact is not reproducible on")
        print("        this machine. Both are findings.")
        # ⭐⭐ WHICH OF THE TWO IT IS, PRINTED HERE. A mismatch with no
        # toolchain reading leaves "it must be the tools" available as an
        # unfalsifiable excuse for re-pinning a hash, so the comparison is put
        # in front of whoever is about to edit the manifest.
        explain_toolchain(tc_stored, tc_live, tc_diff)
        rc = 1
    if not absent and not differ and not unpinned:
        print("    every file reproduced and matches its pinned hash")
        print("    toolchain: %s"
              % ("as recorded in the manifest" if (tc_stored and not tc_diff)
                 else "NOT confirmed -- " + ("no header recorded" if not
                      tc_stored else "%d tool(s) differ from the header"
                      % len(tc_diff))))
        # ⚠ A MATCHING HASH UNDER A DIFFERENT TOOLCHAIN IS NOT A FAILURE: it is
        # the stronger result (the artefact is reproducible across tools), and
        # failing on it would punish the good case. But it is still printed,
        # because a header nobody checks drifts into decoration.
        for name, s, l in tc_diff:
            print("      note  %-10s header %s / here %s" % (name, s, l))

    print()
    print("  --- the suite, on freshly generated images ---")
    for name, good, why in suite():
        print("    %-10s %s%s" % (name, "PASS" if good else "*** FAIL",
                                  "" if good else " %s" % why))
        if not good:
            rc = 1

    # ---- MUST-FIRE: a missing recipe must FAIL, not reuse a stale file ----
    print()
    print("  --- must-fire: drop one recipe ---")
    victim = "test/noop_image_h19.hex"
    if victim not in files:
        print("    *** %s is not in the enumeration, so the must-fire cannot"
              % victim)
        print("        target the file whose absence caused the original bug.")
        rc = 1
    else:
        d2 = quarantine([victim], "mustfire")
        res = suite()
        edge = [r for r in res if r[0] == "tb_edge"]
        if edge and not edge[0][1]:
            print("    tb_edge FAILED with %s absent, as it must -- the bench"
                  % os.path.basename(victim))
            print("    does not silently reuse a stale copy.")
        else:
            print("    *** DID NOT FIRE: tb_edge passed without %s"
                  % os.path.basename(victim))
            rc = 1
        shutil.move(os.path.join(d2, os.path.basename(victim)),
                    os.path.join(ROOT, victim))
        print("    restored %s" % victim)

    print()
    print("=" * 78)
    print("  CLEAN-ROOM: %s" % ("PASSED" if rc == 0 else "FAILED"))
    print("    ⚠ BY-HAND GATE, mandatory at each `cmos5l` checkpoint: it moves")
    print("      files about and runs benches, so it is not part of every run.")
    print("    ⚠ quarantine left at %s -- safe to delete once this passed." % QUAR)
    return rc


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    raise SystemExit(main())
