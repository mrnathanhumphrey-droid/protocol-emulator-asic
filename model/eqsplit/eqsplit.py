"""SPLIT FORMAL EQUIVALENCE -- model/rtl_equiv.py's recipe, with `equiv_simple` fanned out over slices of the $equiv cells.

The recipe is rtl_equiv.YS exactly; it is cut in three, and nothing is added to the proof:
  A  (one process)  reads + synth both sides, equiv_make, hierarchy, async2sync -> equiv.il + cells.sel (every $equiv cell)
  S  (K processes)  read equiv.il; `select -read slice_k.sel`; `equiv_simple -seq 5`; `equiv_status` on the slice -> unproven list
  C  (one process)  read equiv.il; the cells S proved are removed keeping gold (`equiv_remove -gold`, = what a proven cell is:
                    Y driven by A, and A == B was just proven); `equiv_induct -seq 5`; `equiv_status -assert`
Why the slices are sound: equiv_make cuts every matched signal at its $equiv cell's Y, so each cell's equiv_simple proof is over
its own cone with the other cells' Y as shared cut points -- the same proof whether its neighbours run in this process or another.
VERDICT (Wilson's strictness, unchanged): C's `equiv_status -assert` exit 0 AND its "Equivalence successfully proven!" token AND
the bookkeeping closes: slices cover every cell of cells.sel exactly once, each slice's equiv_status counted exactly its cells,
and C's remaining cell count == the slices' summed unproven.
"""
import json, os, re, subprocess, time

TAIL = ["equiv_simple -seq 5", "equiv_induct -seq 5", "equiv_status -assert"]


def atomic(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(obj if isinstance(obj, str) else json.dumps(obj, indent=1))
    os.replace(tmp, path)


def run_ys(yosys, script, log, cwd):
    """Run yosys on a script file; return (rc, wall_s, maxrss_gb). Peak RSS from wait4, the child's own."""
    t = time.time()
    with open(log, "w") as fh:
        p = subprocess.Popen(yosys + ["-s", script], cwd=cwd, stdout=fh, stderr=subprocess.STDOUT)
        _, st, ru = os.wait4(p.pid, 0)
    rc = os.waitstatus_to_exitcode(st)
    return rc, round(time.time() - t, 1), round(ru.ru_maxrss / 1048576, 2)


def split_recipe(ys_template):
    """rtl_equiv.YS -> (prefix lines through async2sync). Refuses if the tail is not exactly TAIL."""
    lines = [l for l in ys_template.strip().split("\n")]
    assert lines[-3:] == TAIL, lines[-3:]
    assert lines[-4] == "async2sync", lines[-4]
    return lines[:-3]


def stage_a(yosys, jd, prefix):
    s = os.path.join(jd, "a.ys")
    with open(s, "w", newline="\n") as fh:
        fh.write("\n".join(prefix) + "\nwrite_rtlil equiv.il\nselect -write cells.sel equiv/t:$equiv\nequiv_status\n")
    rc, w, m = run_ys(yosys, s, os.path.join(jd, "a.log"), jd)
    cells = []
    if rc == 0:
        cells = [l.strip() for l in open(os.path.join(jd, "cells.sel")) if l.strip()]
    return dict(rc=rc, wall_s=w, maxrss_gb=m, n_cells=len(cells)), cells


def write_slices(jd, cells, k):
    os.makedirs(os.path.join(jd, "sl"), exist_ok=True)
    n = len(cells); out = []
    for i in range(k):
        part = cells[i * n // k:(i + 1) * n // k]
        if part:
            f = os.path.join(jd, "sl", "s%03d.sel" % i)
            with open(f, "w", newline="\n") as fh:
                fh.write("\n".join(part) + "\n")
            out.append((i, part))
    return out


ST_FOUND = re.compile(r"Found (\d+) \$equiv cells in equiv:")
ST_SPLIT = re.compile(r"Of those cells (\d+) are proven and (\d+) are unproven")
ST_UNPR = re.compile(r"^\s*Unproven \$equiv (\S+):")


def parse_status(log_text):
    """The LAST equiv_status block in a log: (found, proven, unproven, [unproven cell names])."""
    i = log_text.rfind("Executing EQUIV_STATUS pass")
    blk = log_text[i:] if i >= 0 else ""
    f = ST_FOUND.findall(blk); s = ST_SPLIT.findall(blk)
    names = [m.group(1) for m in (ST_UNPR.match(l) for l in blk.split("\n")) if m]
    if not f:
        return None
    found = int(f[-1])
    pr, un = (int(s[-1][0]), int(s[-1][1])) if s else (found, 0)
    return found, pr, un, names


def slice_script(jd, i):
    s = os.path.join(jd, "sl", "s%03d.ys" % i)
    with open(s, "w", newline="\n") as fh:
        fh.write("read_rtlil ../equiv.il\nhierarchy -top equiv\nselect -read s%03d.sel\n"
                 "equiv_simple -seq 5\nequiv_status\n" % i)
    return s


def judge_slice(jd, i, part, rc, w, m):
    """Checkpoint one slice: s%03d.json (atomic). ok only if rc 0 and its equiv_status counted exactly its cells."""
    txt = open(os.path.join(jd, "sl", "s%03d.log" % i), errors="replace").read()
    st = parse_status(txt)
    r = dict(i=i, n=len(part), rc=rc, wall_s=w, maxrss_gb=m, ok=False)
    if rc == 0 and st:
        found, pr, un, names = st
        r.update(found=found, proven=pr, unproven=un, n_names=len(names))
        pset = set(part)
        names_q = ["equiv/" + n for n in names]
        r["ok"] = (found == len(part) and pr + un == found and len(names) == un and all(n in pset for n in names_q))
        if r["ok"]:
            atomic(os.path.join(jd, "sl", "s%03d.unproven" % i), "\n".join(names_q) + ("\n" if names_q else ""))
    atomic(os.path.join(jd, "sl", "s%03d.json" % i), r)
    return r


def stage_c(yosys, jd, slices):
    unpr = set()
    for i, part in slices:
        f = os.path.join(jd, "sl", "s%03d.unproven" % i)
        unpr |= {l.strip() for l in open(f) if l.strip()}
    allc = [c for _, part in slices for c in part]
    assert len(allc) == len(set(allc)), "slices overlap"
    proven = [c for c in allc if c not in unpr]
    with open(os.path.join(jd, "proven.sel"), "w", newline="\n") as fh:
        fh.write("\n".join(proven) + "\n")
    s = os.path.join(jd, "c.ys")
    with open(s, "w", newline="\n") as fh:
        fh.write("read_rtlil equiv.il\nhierarchy -top equiv\n"
                 + ("select -read proven.sel\nequiv_remove -gold\nselect -clear\n" if proven else "")
                 + "equiv_status\n" + "\n".join(TAIL[1:]) + "\n")
    rc, w, m = run_ys(yosys, s, os.path.join(jd, "c.log"), jd)
    txt = open(os.path.join(jd, "c.log"), errors="replace").read()
    # the equiv_status BEFORE induct: what C was handed must equal the slices' unproven
    blocks = txt.split("Executing EQUIV_STATUS pass")
    pre = parse_status("Executing EQUIV_STATUS pass" + blocks[1]) if len(blocks) > 1 else None
    tok = "Equivalence successfully proven!" in txt
    fa = re.findall(r"Found (\d+) unproven \$equiv cells in 'equiv_status -assert'", txt)
    return dict(rc=rc, wall_s=w, maxrss_gb=m, n_total=len(allc), n_proven_by_slices=len(proven),
                n_unproven_by_slices=len(unpr), c_handed=(pre[0] if pre else None),
                handed_matches=(pre is not None and pre[0] == len(unpr)),
                token=tok, assert_unproven=(int(fa[-1]) if fa else None),
                verdict=("PROVEN" if (rc == 0 and tok and pre is not None and pre[0] == len(unpr)) else "NOT PROVEN"))
