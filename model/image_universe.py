"""image_universe -- THE ONE LIST OF PROGRAM IMAGES every writer and gate scans.

⛔⛔ WHY ONE FUNCTION (Wilson 10-18, the image-universe audit). Eight tools
each enumerated images their own way: six scanned test/*.hex only, the clocked
A2 writer added fpga/images/, the response-bound writer added the generated
probe_cov_* images, and gate_wire_feed (the widest) added both plus every
benchset `+IMG=` arm. So two swept clocked arms (probe_cov_pindiv lane 3,
probe_cov_cemodes lane 0) had no clocked A2 bound and ran with A2 switched
off, and the first fpga image crashed a reader that looked in test/ only.
Every image-enumerating writer and gate now calls this module instead.

THE UNIVERSE, by PATH:
  * test/*.hex          (not probe_*)
  * fpga/images/*.hex   (not probe_*)
  * every image a benchset arm names with `+IMG=` (generated first, by the
    sweep's own builder, so the set does not depend on whether a sweep ran)

⭐ v2 PIT (10-28): an image carrying the SNIFF magic 'S' 'N' at bytes 30-31 is
NOT a program -- byte 0 is a wire mask and the engine never runs it. It goes in
`sniff`, LISTED by `report` (never silently dropped), and stays out of `paths`,
so no program gate decodes a wire mask as an action.

⛔ NAMES MUST BE UNIQUE, because every output file is keyed by image NAME. Two
paths with one name:
  * byte-identical -> DE-DUPLICATED, the copy LISTED (`dups`): the benchset
    long-path arm is a byte copy of test/tx_image.hex by design (ruling CI3);
  * different bytes -> a HARD ERROR (`NameCollision`). Keying by name would
    otherwise drop one of two different programs without a trace.
"""

from __future__ import annotations

import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

#: the directories scanned for `*.hex`, in preference order: on a de-duplicated
#: name the copy kept is the one in the EARLIEST directory (then the path).
DIRS = (os.path.join(ROOT, "test"), os.path.join(ROOT, "fpga", "images"))


class NameCollision(RuntimeError):
    """Two DIFFERENT images share one name."""


class Universe:
    def __init__(self, paths, dups, probs, sniff=None):
        self.paths = paths    # {name: path}, one per name
        self.dups = dups      # [(name, kept path, de-duplicated path)]
        self.probs = probs    # [str]: a generator failed / an arm's file absent
        self.sniff = sniff or {}   # {name: path}: SNIFF images, not programs

    def items(self):
        """[(name, path)] sorted by name."""
        return sorted(self.paths.items())


#: the +IMG paths of the GENERATED (`pygen`) arms, filled by the last building
#: scan -- gate_image_bounds G6 holds every one of them to the universe
GENERATED_ARM_IMAGES = set()


def _bench_arm_paths(generate=True):
    """(set of normalised paths every benchset `+IMG=` arm names, problems).

    ⛔ BUILDING, THE ARMS ARE `benchset.plan()`'s (Wilson 11-13, the A2 audit
    2e): the same resolved records the coverage sweep runs -- static, corpus
    and GENERATED (`pygen`) arms alike. Walking only CONFIG's static lists left
    the USB / buffer / pair / ARM2 sweep images (branch-lane images among them)
    outside the universe and every gate that reads it -- agent 1's own gap,
    from ac3443d. The generated images are BUILT by plan() (and the long-path
    copy made), so a clean checkout and a post-sweep tree see the same set.
    `generate=False` (test/sim_run.py's per-run content index) lists the
    STATIC arms without building anything."""
    sys.path.insert(0, os.path.join(ROOT, "test"))
    import benchset
    paths, probs = set(), []
    if generate:
        recs, probs = benchset.plan()
        probs = list(probs)
        arglists = [r["args"] for r in recs]
        GENERATED_ARM_IMAGES.clear()
        for r in recs:
            if benchset.CONFIG.get(r["top"], {}).get("pygen"):
                for a in r["args"]:
                    m = re.match(r"\+IMG=(.+\.hex)$", a)
                    if m:
                        GENERATED_ARM_IMAGES.add(
                            os.path.normpath(os.path.join(ROOT, m.group(1))))
    else:
        arglists = []
        for _top, cfg in sorted(benchset.CONFIG.items()):
            arms = cfg.get("arms")
            if isinstance(arms, list):
                arglists += [a for arm in arms for a in arm[1:] if isinstance(a, list)]
    for args in arglists:
        for a in args:
            m = re.match(r"\+IMG=(.+\.hex)$", a)
            if m:
                paths.add(os.path.normpath(os.path.join(ROOT, m.group(1))))
    return paths, probs


def _rel(p):
    """`p` relative to the repo root, or absolute when it is on another drive
    (Windows `relpath` raises across drives)."""
    try:
        return os.path.relpath(p, ROOT)
    except ValueError:
        return p


def _rank(p, dirs):
    d = os.path.dirname(p)
    idx = [i for i, x in enumerate(dirs) if os.path.normpath(x) == d]
    return (idx[0] if idx else len(dirs), p)


def scan(dirs=DIRS, arms=True, generate=True):
    """The universe as a `Universe`. Raises `NameCollision` on two different
    images under one name. `dirs` / `arms` exist for the must-fires only;
    `generate=False` builds nothing (an absent generated arm is a `probs`
    entry, as always)."""
    cands, probs = set(), []
    for d in dirs:
        for p in glob.glob(os.path.join(d, "*.hex")):
            if not os.path.basename(p).startswith("probe_"):
                cands.add(os.path.normpath(p))
    if arms:
        ap, aprobs = _bench_arm_paths(generate)
        cands |= ap
        probs += aprobs
    by_name = {}
    for p in sorted(cands):
        if not os.path.isfile(p):
            probs.append("%s is named by a bench arm but is not on disk"
                         % _rel(p))
            continue
        by_name.setdefault(os.path.basename(p), []).append(p)
    paths, dups = {}, []
    for name, ps in sorted(by_name.items()):
        ps = sorted(ps, key=lambda p: _rank(p, dirs))
        keep = ps[0]
        with open(keep, "rb") as fh:
            ref = fh.read()
        for other in ps[1:]:
            with open(other, "rb") as fh:
                if fh.read() != ref:
                    raise NameCollision(
                        "two DIFFERENT images are named %s: %s and %s -- every "
                        "output file is keyed by name, so one would be dropped"
                        % (name, _rel(keep), _rel(other)))
            dups.append((name, keep, other))
        paths[name] = keep
    sniff = {n: p for n, p in paths.items() if _is_sniff(p)}
    for n in sniff:
        del paths[n]
    return Universe(paths, dups, probs, sniff)


#: the SNIFF magic (src/project.v SNIFF_HI / SNIFF_LO) at the v2 magic's bytes
SNIFF_MAGIC, SNIFF_AT = (0x53, 0x4E), 30


def _is_sniff(path):
    """True if the image's bytes 30-31 are the SNIFF magic (a byte-per-line
    .hex, as pe_isa.write_image writes it)."""
    toks = []
    with open(path, encoding="ascii", errors="replace") as fh:
        for ln in fh:
            ln = ln.split("//")[0].strip()
            if ln and not ln.startswith("@"):
                toks += ln.split()
            if len(toks) > SNIFF_AT + 1:
                break
    try:
        return tuple(int(t, 16) for t in toks[SNIFF_AT:SNIFF_AT + 2]) == SNIFF_MAGIC
    except ValueError:
        return False


_CACHE = []


def default():
    """`scan()` of the real universe, once per process (the generators run
    once, not once per lookup)."""
    if not _CACHE:
        _CACHE.append(scan())
    return _CACHE[0]


def items():
    """[(name, path)] for the whole universe, sorted by name. ⛔ A generator
    failure or an arm whose file is absent RAISES: a writer or gate must not
    run on a silently smaller set."""
    u = default()
    if u.probs:
        raise RuntimeError("image universe: " + "; ".join(u.probs))
    return u.items()


#: F1.5 (Wilson 11-09): the board images (fpga/images/) are native v2 images,
#: read like every other. The v1 route (board_as_v2 / images_v2 /
#: board_stale_verdict, through test/v1_translate.py) is DELETED so it cannot
#: come back quietly; test/v1_translate.py's one reader is gate_v2_equiv
#: (v1-lock vs v2 RTL), never a board image.


def images():
    """[(name, image bytes)] for the whole universe, sorted by name."""
    import gate_degenerate_fields as dgf
    return [(n, dgf.load(p)) for n, p in items()]


def resolve(name):
    """The one path of image `name`; FileNotFoundError if it is not in the
    universe."""
    u = default()
    if name not in u.paths:
        raise FileNotFoundError("image %s is not in the image universe" % name)
    return u.paths[name]


def report(u, out=print):
    """Print the de-duplicated copies and the SNIFF images (Wilson: listed,
    never silent)."""
    if u.sniff:
        out("  image universe: %d SNIFF image(s) held out of the program set "
            "(not programs): %s" % (len(u.sniff), ", ".join(sorted(u.sniff))))
    if not u.dups:
        out("  image universe: %d images, no duplicate names" % len(u.paths))
        return
    out("  image universe: %d images; %d byte-identical copy(ies) "
        "de-duplicated:" % (len(u.paths), len(u.dups)))
    for name, keep, other in u.dups:
        out("    %-22s kept %s, copy %s" % (name, _rel(keep), _rel(other)))
