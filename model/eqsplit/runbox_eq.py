"""ON-BOX split equivalence (s12c eqbox).  Stages:
  1 preflight   bundle yosys -V == the pinned 0.52 fee39a3; manifest sha256s match the uploaded sources
  2 DRY         toy_test.py with the bundle yosys (every stage: A, slices, C; an induct-only proof PROVEN, a plant NOT PROVEN)
                -- gates everything after it
  3 REAL        jobs eq (cdde6d5 vs worktree) and mf (the must-fire plant), one scheduler:
                A_eq first ALONE (its peak RSS sizes everything); then A_mf, eq slices, mf slices, C_eq, C_mf as memory admits.
                Admission: launch only if MemAvailable >= est(kind) + RESERVE; guard: MemAvailable < GUARD -> kill the NEWEST slice,
                requeue it at the front, cap parallelism at the live count.  A and C are never killed by the guard.
Checkpoints: status.json (atomic, every event + every 60 s), jobs/*/sl/s*.json + s*.unproven (atomic per slice) -> the launcher
pulls ckpt.tgz each poll.  result.json at the end; run.rc last.  rc 0 = both verdicts as required (eq PROVEN, mf NOT PROVEN);
rc 1 = a verdict is wrong; rc 2 = preflight/dry failed; rc 3 = runner exception.
env: NPAR (vCPUs), K_SLICES (default 120), RESERVE_GB (12), GUARD_GB (5)"""
import hashlib, json, os, signal, subprocess, sys, time, traceback
R = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, R)
os.environ["RTL_EQUIV_DIR"] = R
import eqsplit as E, eqjob as J

Y = [os.path.join(R, "ybin", "bin", "yosys")]
NPAR = int(os.environ.get("NPAR", "30")); K = int(os.environ.get("K_SLICES", "120"))
RESERVE = float(os.environ.get("RESERVE_GB", "12")); GUARD = float(os.environ.get("GUARD_GB", "5"))
ST = dict(stage="start", t0=time.time(), steps=[], jobs={})


def save():
    ST["t"] = time.time(); ST["elapsed_s"] = round(ST["t"] - ST["t0"]); ST["mem_avail_gb"] = mem_avail()
    E.atomic(os.path.join(R, "status.json"), ST)


def mem_avail():
    for l in open("/proc/meminfo"):
        if l.startswith("MemAvailable:"):
            return round(int(l.split()[1]) / 1048576, 1)


def rss_gb(pid):
    try:
        for l in open("/proc/%d/status" % pid):
            if l.startswith("VmRSS:"):
                return int(l.split()[1]) / 1048576
    except (OSError, ValueError):          # the process just exited: a live-table display value only, never a verdict
        return 0.0
    return 0.0


def step(name, fn):
    t = time.time(); ST["stage"] = name; save()
    r = fn(); ST["steps"].append(dict(step=name, wall_s=round(time.time() - t, 1), ok=bool(r))); save()
    return r


def preflight():
    v = subprocess.run(Y + ["-V"], capture_output=True, text=True).stdout.strip()
    ST["yosys_banner"] = v
    man = json.load(open(os.path.join(R, "manifest.json")))
    bad = [f for f, h in man["files"].items()
           if hashlib.sha256(open(os.path.join(R, f if f == "rtl_equiv.py" else "jobs/" + f), "rb").read()).hexdigest() != h]
    src = open(os.path.join(R, "rtl_equiv.py")).read()
    ST["preflight"] = dict(bad_sha=bad, sv_rule='SV = {"pe_store.v"}' in src, nproc=os.cpu_count(), mem_avail_gb=mem_avail())
    return v == "Yosys 0.52 (git sha1 fee39a3284c90249e1d9684cf6944ffbbcbb8f90)" and not bad and ST["preflight"]["sv_rule"]


def dry():
    r = subprocess.run([sys.executable, os.path.join(R, "toy_test.py")] + Y, capture_output=True, text=True, cwd=R)
    open(os.path.join(R, "dry.log"), "w").write(r.stdout + r.stderr)
    return "TOY_OK" in r.stdout


class Job:
    def __init__(self, name):
        self.name = name; self.jd = os.path.join(R, "jobs", name); self.state = "A_todo"
        # EQ_FILES / EQ_TOP: LOCAL scheduler test only (the toy as the "real" jobs); unset on the box
        files = os.environ.get("EQ_FILES", "pe_store.v,pe_engine.v,project.v").split(",")
        self.pre = J.prefix(files, os.environ.get("EQ_TOP", "tt_um_protocol_emulator"), sv=("pe_store.v",))
        self.slices = []; self.todo = []; self.res = {}; self.out = dict(job=name)
        ST["jobs"][name] = self.out


def main():
    if not step("preflight", preflight):
        return 2
    if not step("dry_toy", dry):
        return 2
    ST["stage"] = "real"; save()
    jobs = [Job("eq"), Job("mf")]
    live = {}                       # pid -> (popen, job, kind, slice_i, t_start, logfh)
    est = {}                        # kind -> GB
    par_cap = NPAR
    last_save = 0

    def launch(job, kind, i=None):
        if kind == "A":
            s = os.path.join(job.jd, "a.ys")
            open(s, "w", newline="\n").write("\n".join(job.pre) + "\nwrite_rtlil equiv.il\nselect -write cells.sel equiv/t:$equiv\nequiv_status\n")
            cwd, log, arg = job.jd, os.path.join(job.jd, "a.log"), "a.ys"
        elif kind == "S":
            E.slice_script(job.jd, i); cwd, log, arg = os.path.join(job.jd, "sl"), os.path.join(job.jd, "sl", "s%03d.log" % i), "s%03d.ys" % i
        lf = open(log, "w")
        p = subprocess.Popen(Y + ["-s", arg], cwd=cwd, stdout=lf, stderr=subprocess.STDOUT)
        live[p.pid] = (p, job, kind, i, time.time(), lf)

    def c_thread(job):
        # C runs in a child python so the scheduler stays responsive; it writes c.json
        code = ("import sys,json,os;sys.path.insert(0,%r);os.environ['RTL_EQUIV_DIR']=%r;import eqsplit as E;"
                "sl=[(i,[l.strip() for l in open(os.path.join(%r,'sl','s%%03d.sel'%%i)) if l.strip()]) for i in %r];"
                "r=E.stage_c(%r,%r,sl);E.atomic(os.path.join(%r,'c.json'),r)") % (R, R, job.jd, [i for i, _ in job.slices], Y, job.jd, job.jd)
        lf = open(os.path.join(job.jd, "c_driver.log"), "w")
        p = subprocess.Popen([sys.executable, "-c", code], cwd=job.jd, stdout=lf, stderr=subprocess.STDOUT)
        live[p.pid] = (p, job, "C", None, time.time(), lf)

    while any(j.state != "done" for j in jobs):
        # ---- reap ----
        for pid in list(live):
            try:
                rp, st, ru = os.wait4(pid, os.WNOHANG)
            except ChildProcessError:
                rp, st, ru = pid, 0, None
            if rp == 0:
                continue
            p, job, kind, i, ts, lf = live.pop(pid); lf.close()
            rc = os.waitstatus_to_exitcode(st); w = round(time.time() - ts, 1); m = round(ru.ru_maxrss / 1048576, 2) if ru else None
            if kind == "A":
                cells = [l.strip() for l in open(os.path.join(job.jd, "cells.sel")) if l.strip()] if rc == 0 and os.path.exists(os.path.join(job.jd, "cells.sel")) else []
                job.out["A"] = dict(rc=rc, wall_s=w, maxrss_gb=m, n_cells=len(cells))
                est["A"] = max(est.get("A", 0), m or 0)
                if rc != 0 or not cells:
                    job.out["verdict"] = "NOT PROVEN (stage A failed)"; job.state = "done"
                else:
                    job.slices = E.write_slices(job.jd, cells, K); job.todo = list(job.slices); job.state = "S"
                    job.out["S"] = dict(done=0, of=len(job.slices), bad=[], requeued=0)
            elif kind == "S":
                if job.res.get(("killed", i)):
                    job.res.pop(("killed", i)); continue
                part = dict(job.slices)[i]
                r = E.judge_slice(job.jd, i, part, rc, w, m); job.res[i] = r
                est["S"] = max(est.get("S", 0), m or 0)
                done = [x for k_, x in job.res.items() if isinstance(k_, int)]
                job.out["S"].update(done=len(done), bad=[x["i"] for x in done if not x["ok"]],
                                    max_rss_gb=max(x["maxrss_gb"] for x in done), max_wall_s=max(x["wall_s"] for x in done),
                                    sum_wall_s=round(sum(x["wall_s"] for x in done)))
                if len(done) == len(job.slices):
                    if job.out["S"]["bad"]:
                        job.out["verdict"] = "NOT PROVEN (slices failed: %s)" % job.out["S"]["bad"]; job.state = "done"
                    else:
                        job.state = "C_todo"
            elif kind == "C":
                cj = os.path.join(job.jd, "c.json")
                c = json.load(open(cj)) if os.path.exists(cj) else dict(verdict="NOT PROVEN (C driver rc %d)" % rc)
                job.out["C"] = c; job.out["verdict"] = c["verdict"]; job.state = "done"
            save()
        # ---- memory guard ----
        ma = mem_avail()
        if ma < GUARD:
            sl = [(ts, pid) for pid, (p, job, kind, i, ts, lf) in live.items() if kind == "S"]
            if sl:
                _, pid = max(sl); p, job, kind, i, ts, lf = live[pid]
                os.kill(pid, signal.SIGKILL); job.res[("killed", i)] = True
                job.todo.insert(0, (i, dict(job.slices)[i])); job.out["S"]["requeued"] += 1
                par_cap = max(1, sum(1 for v in live.values() if v[2] == "S") - 1)
                ST["guard_events"] = ST.get("guard_events", 0) + 1; ST["par_cap"] = par_cap; save()
        # ---- admit ----
        a_eq = jobs[0]
        for job in jobs:
            busy_A = any(v[2] == "A" for v in live.values())
            if job.state == "A_todo":
                if job is a_eq and not live:
                    launch(job, "A"); job.state = "A_run"
                elif job is not a_eq and "A" in est and mem_avail() >= est["A"] * 1.3 + RESERVE and len(live) < NPAR:
                    launch(job, "A"); job.state = "A_run"
            if job.state == "C_todo" and mem_avail() >= est.get("A", 10) * 2 + RESERVE:
                c_thread(job); job.state = "C_run"
            if job.state == "S":
                while job.todo and sum(1 for v in live.values() if v[2] == "S") < par_cap and len(live) < NPAR:
                    need = (est.get("S") or est["A"] * 1.2) * 1.2 + RESERVE
                    if mem_avail() < need:
                        break
                    i, part = job.todo.pop(0); launch(job, "S", i)
        if time.time() - last_save > 60:
            ST["live"] = [(v[1].name, v[2], v[3], round(time.time() - v[4]), round(rss_gb(pid), 1)) for pid, v in live.items()]
            save(); last_save = time.time()
        time.sleep(5)
    eq, mf = ST["jobs"]["eq"], ST["jobs"]["mf"]
    mf_red = mf.get("verdict") == "NOT PROVEN" and (mf.get("C") or {}).get("assert_unproven", 0) not in (None, 0)
    res = dict(eq=eq, mf=mf, eq_proven=eq.get("verdict") == "PROVEN", mustfire_red=mf_red,
               manifest=json.load(open(os.path.join(R, "manifest.json"))), yosys_banner=ST.get("yosys_banner"))
    E.atomic(os.path.join(R, "result.json"), res)
    ST["stage"] = "finished"; save()
    return 0 if (res["eq_proven"] and mf_red) else 1


def _finish(rc):
    """Bundle the checkpoints + logs, then write run.rc LAST (the watchdog's DONE and the poller key on it)."""
    subprocess.run("cd %s && tar czf ckpt.tgz status.json result.json jobs/*/sl/*.json jobs/*/sl/*.unproven jobs/*/c.json 2>/dev/null; "
                   "tar czf logs.tgz dry.log jobs/*/a.log jobs/*/c.log jobs/*/c_driver.log jobs/*/sl/*.log 2>/dev/null" % R, shell=True)
    E.atomic(os.path.join(R, "run.rc"), str(rc))


if __name__ == "__main__":
    open(os.path.join(R, "run.pid"), "w").write(str(os.getpid()))
    rc = 3                                 # rc 3 = runner exception: recorded in status.json, then RE-RAISED (ruling E)
    try:
        rc = main()
    except BaseException:
        ST["exception"] = traceback.format_exc(); save()
        raise
    finally:
        _finish(rc)
