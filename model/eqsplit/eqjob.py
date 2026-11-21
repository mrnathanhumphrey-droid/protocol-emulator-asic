"""Build one equivalence job's stage-A recipe from model/rtl_equiv.py's YS template (IMPORTED, not copied), and run a job end
to end with up to `par` concurrent slices (the local toy test and the cross-check use this; the box runner has its own
memory-gated scheduler over the same eqsplit stages)."""
import os, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import eqsplit as E


def rtl_equiv_dir():
    """RTL_EQUIV_DIR if set; else this directory when rtl_equiv.py was staged beside us (the box); else model/ (the repo)."""
    d = os.environ.get("RTL_EQUIV_DIR")
    if d:
        return d
    return HERE if os.path.exists(os.path.join(HERE, "rtl_equiv.py")) else os.path.dirname(HERE)


def ys_template():
    sys.path.insert(0, rtl_equiv_dir())
    import rtl_equiv
    return rtl_equiv.YS


def prefix(files, top, sv=(), gold="gold", gate="gate"):
    """rtl_equiv's reads + recipe. `sv`: files read with -sv (rtl_equiv's SV set). The real top keeps its name; another top
    (the toy, a cross-check submodule) is substituted for tt_um_protocol_emulator, nothing else."""
    def reads(d):
        return "\n".join("read_verilog %s%s/%s" % ("-sv " if f in sv else "", d, f) for f in files)
    t = ys_template().replace("tt_um_protocol_emulator", top)
    t = t.format(reads_gold=reads(gold), reads_gate=reads(gate))
    return E.split_recipe(t)


def run_job(yosys, jd, pre, k, par, status_cb=None):
    t0 = time.time(); out = dict(job=os.path.basename(jd))
    a, cells = E.stage_a(yosys, jd, pre); out["A"] = a
    if status_cb:
        status_cb(out)
    if a["rc"] != 0 or not cells:
        out["verdict"] = "NOT PROVEN (stage A failed)"; return out
    sl = E.write_slices(jd, cells, k)
    assert sorted(c for _, p in sl for c in p) == sorted(cells)
    todo = list(sl); live = {}; res = []
    while todo or live:
        while todo and len(live) < par:
            i, part = todo.pop(0); s = E.slice_script(jd, i)
            lf = open(os.path.join(jd, "sl", "s%03d.log" % i), "w")
            p = subprocess.Popen(yosys + ["-s", os.path.basename(s)], cwd=os.path.join(jd, "sl"), stdout=lf, stderr=subprocess.STDOUT)
            live[p.pid] = (p, i, part, time.time(), lf)
        pid, st, ru = os.wait4(-1, 0)
        if pid not in live:
            continue
        p, i, part, ts, lf = live.pop(pid); lf.close()
        r = E.judge_slice(jd, i, part, os.waitstatus_to_exitcode(st), round(time.time() - ts, 1), round(ru.ru_maxrss / 1048576, 2))
        res.append(r)
        out["S"] = dict(done=len(res), of=len(sl), bad=[x["i"] for x in res if not x["ok"]],
                        max_rss_gb=max(x["maxrss_gb"] for x in res), max_wall_s=max(x["wall_s"] for x in res))
        if status_cb:
            status_cb(out)
    if out["S"]["bad"]:
        out["verdict"] = "NOT PROVEN (slices failed: %s)" % out["S"]["bad"]; return out
    c = E.stage_c(yosys, jd, sl); out["C"] = c; out["verdict"] = c["verdict"]; out["wall_s"] = round(time.time() - t0, 1)
    if status_cb:
        status_cb(out)
    return out
