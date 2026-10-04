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

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
QUAR = os.environ.get(
    "PE_QUARANTINE",
    os.path.join(os.environ.get("TEMP", "/tmp"), "pe_cleanroom"))

GENERATORS = [
    [sys.executable, os.path.join(HERE, "make_smoke_image.py"), "--all"],
    [sys.executable, os.path.join(HERE, "corpus.py")],
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
    for name, top, srcs in (
        ("tb_smoke", "tb_smoke", ["test/tb_smoke.v"]),
        ("tb_edge", "tb_edge", ["test/tb_edge.v"]),
    ):
        vvp = os.path.join(sp, name + ".vvp")
        b = run(["iverilog", "-g2012", "-o", vvp, "-s", top]
                + [os.path.join(ROOT, s) for s in srcs]
                + [os.path.join(ROOT, "src", f)
                   for f in ("pe_engine.v", "pe_store.v", "project.v")])
        if b.returncode != 0:
            out.append((name, False, "build failed"))
            continue
        r = run(["vvp", vvp])
        txt = r.stdout + r.stderr
        ok = ("PASS" in txt and "FAILURE" not in txt)
        why = "PASS" if ok else [l for l in txt.splitlines()
                                 if "FAIL" in l or "Unable" in l][:1]
        out.append((name, ok, why))
    return out


def main() -> int:
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
        rc = 1
    if not absent and not differ and not unpinned:
        print("    every file reproduced and matches its pinned hash")

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
    raise SystemExit(main())
