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
    def __init__(self, paths, dups, probs):
        self.paths = paths    # {name: path}, one per name
        self.dups = dups      # [(name, kept path, de-duplicated path)]
        self.probs = probs    # [str]: a generator failed / an arm's file absent

    def items(self):
        """[(name, path)] sorted by name."""
        return sorted(self.paths.items())


def _bench_arm_paths(generate=True):
    """(set of normalised paths every benchset `+IMG=` arm names, problems).

    The generated images are BUILT first (`benchset.generate`) and the
    long-path copy made (`ensure_longpath_image`), so a clean checkout and a
    post-sweep tree see the same set. `generate=False` (test/sim_run.py's
    per-run content index) lists the arms without building anything."""
    sys.path.insert(0, os.path.join(ROOT, "test"))
    import benchset
    paths, probs = set(), []
    if generate:
        benchset.ensure_longpath_image()
    for top, cfg in sorted(benchset.CONFIG.items()):
        err = benchset.generate(cfg, top) if generate else None
        if err:
            probs.append(err)
        arms = cfg.get("arms")
        if not isinstance(arms, list):
            continue
        for arm in arms:
            for a in [a for f in arm[1:] if isinstance(f, list) for a in f]:
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
    return Universe(paths, dups, probs)


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


#: ⭐ v2 (Nate + Wilson 10-25): the BOARD images stay v1-encoded until a v2
#: FPGA build exists -- no v2 image beside a v1 bitstream. A gate that reads
#: them as programs reads them THROUGH test/v1_translate.py (the same program
#: in v2's word), and a gate green only because of that reports the declared
#: STALE (model/stale_records.py) -- `board_stale_verdict`.
BOARD_DIR = os.path.join(ROOT, "fpga", "images")


def board_names():
    return sorted(n for n in os.listdir(BOARD_DIR) if n.endswith(".hex"))


def board_as_v2(imgs):
    """`imgs` ({name: bytes} or [(name, bytes)]) with every fpga/images/*.hex
    translated -> (same shape, [the names translated])."""
    import v1_translate
    board = set(board_names())
    pairs = list(imgs.items()) if isinstance(imgs, dict) else list(imgs)
    out, names = [], []
    for n, img in pairs:
        if n in board:
            img = v1_translate.translate(bytes(img))
            names.append(n)
        out.append((n, img))
    return (dict(out) if isinstance(imgs, dict) else out), sorted(names)


def board_stale_verdict(gate, names, extra=()):
    """(verdict, why) for a gate green only through the translation: its
    staleness inputs are the board images (which must NOT move) and the
    encoder that moved under them (test/pe_isa.py), plus `extra`."""
    import stale_records as SR
    ins = ["fpga/images/" + n for n in names] + ["test/pe_isa.py"] + list(extra)
    return SR.stale_verdict(gate, SR.moved(ins))


def images_v2():
    """`images()` with the board images read THROUGH v1_translate (see
    board_as_v2) -> ([(name, bytes)], [the names translated])."""
    return board_as_v2(images())


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
    """Print the de-duplicated copies (Wilson: listed, never silent)."""
    if not u.dups:
        out("  image universe: %d images, no duplicate names" % len(u.paths))
        return
    out("  image universe: %d images; %d byte-identical copy(ies) "
        "de-duplicated:" % (len(u.paths), len(u.dups)))
    for name, keep, other in u.dups:
        out("    %-22s kept %s, copy %s" % (name, _rel(keep), _rel(other)))
