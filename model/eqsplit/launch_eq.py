"""s12c split-equivalence box: launch ONE a10 -> upload -> setup_eq.sh (SETUP_OK) -> watchdog (--verify KILL_PATH_OK, WD_UP) ->
runbox_eq.py (RUN_UP) -> POLL every 5 min: snapshot ckpt on the box (tar + sha256), pull, verify sha locally (partial pull);
print only stage changes / failures / end.  run.rc 0: pull all, touch PULLED, terminate + verify, cost.  rc != 0: pull all, box
LEFT UP (watchdog DONE grace 30 min) for repair.  Poll limit = deadline - 25 min (final pull) < watchdog DEADLINE kill.
EXTEND: write a new TOTAL cap in $ to eqbox/logs/EXTEND_CAP_USD; the poller arms a NEW watchdog at the new deadline (wd2..n.json),
checks it is up, THEN kills the old one, moves its own poll limit; file renamed .applied-<n> / .refused-<n>.
Stage first: prep_jobs.py --base <rev> and make_bundle.sh (ybin.tgz) into the same work dir.
env: PE_EQ_WORK (default formal/build/eqsplit), PE_LAM_TOOLS (dir of lam.py: req/key), PE_LAM_SSH_KEY (private key path),
     PE_LAM_KEY_NAME (the account key name, default ML-CF).
     python model/eqsplit/launch_eq.py go"""
import hashlib, json, os, subprocess, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
for _k in ("PE_LAM_TOOLS", "PE_LAM_SSH_KEY"):
    if not os.environ.get(_k):
        raise SystemExit("set %s (see the docstring); nothing launched" % _k)
sys.path.insert(0, os.environ["PE_LAM_TOOLS"])
import lam

C = Path(os.environ.get("PE_EQ_WORK") or ROOT / "formal" / "build" / "eqsplit"); LOGS = C / "logs"; PUL = C / "pulled"
SSH_KEY = os.environ["PE_LAM_SSH_KEY"]; KEY_NAME = os.environ.get("PE_LAM_KEY_NAME", "ML-CF")
NT = os.name == "nt"
SSH = "C:/Windows/System32/OpenSSH/ssh.exe" if NT else "ssh"; SCP = "C:/Windows/System32/OpenSSH/scp.exe" if NT else "scp"
OPTS = ["-i", SSH_KEY, "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=" + ("NUL" if NT else "/dev/null"), "-o", "LogLevel=ERROR",
        "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=6"]
CAP_C = 1500                                   # $15 total cap (ruling 11-21); more ONLY via EXTEND_CAP_USD, the owner's call
TYPES = ["gpu_1x_a10"]
REMOTE = "/home/ubuntu/eqbox"; NAME = "s12c-eq"
UP = ["eqsplit.py", "eqjob.py", "toy_test.py", "runbox_eq.py", "rtl_equiv.py", "manifest.json", "jobs.tgz", "ybin.tgz",
      "toy.tgz", "setup_eq.sh", "wd.py"]
stf = LOGS / "box_eq.json"


def P(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def ssh(ip, cmd, timeout=900, check=False, inp=None):
    r = subprocess.run([SSH, *OPTS, f"ubuntu@{ip}", cmd], capture_output=True, text=True, timeout=timeout, input=inp)
    if check and r.returncode != 0:
        raise RuntimeError(f"ssh rc={r.returncode}: {cmd[:80]} :: {(r.stdout + r.stderr)[-800:]}")
    return r


def scp(src, dst, timeout=1800):
    for _ in range(3):
        try:
            if subprocess.run([SCP, *OPTS, src, dst], capture_output=True, timeout=timeout).returncode == 0:
                return True
        except subprocess.TimeoutExpired:
            pass
        time.sleep(8)
    return False


def terminate_verify(iid):
    try:
        lam.req("POST", "/instance-operations/terminate", {"instance_ids": [iid]})
    except SystemExit as e:
        P("terminate POST error", e)
    for _ in range(40):
        time.sleep(15)
        stt = [i["status"] for i in lam.req("GET", "/instances")["data"] if i["id"] == iid]
        if not stt or stt[0] in ("terminated", "terminating"):
            P("terminated:", stt); return True
    return False


def save(state):
    stf.write_text(json.dumps(state, indent=1))


def pull(ip, names):
    got = []
    for n in names:
        if scp(f"ubuntu@{ip}:{REMOTE}/{n}", str(PUL / n), timeout=600):
            got.append(n)
    return got


def pull_ckpt(ip, n):
    """Partial pull: snapshot on the box (tar + sha256), pull, verify locally. Returns True on a verified pull."""
    r = ssh(ip, f"cd {REMOTE} && tar czf ckpt_snap.tgz status.json jobs/*/sl/*.json jobs/*/sl/*.unproven jobs/*/c.json "
                f"2>/dev/null; sha256sum ckpt_snap.tgz | cut -c1-64", timeout=120)
    want = r.stdout.strip()
    if not want or not scp(f"ubuntu@{ip}:{REMOTE}/ckpt_snap.tgz", str(PUL / "ckpt_partial.tgz"), timeout=600):
        return False
    ok = hashlib.sha256((PUL / "ckpt_partial.tgz").read_bytes()).hexdigest() == want
    if ok:
        (PUL / "ckpt_partial.tgz").replace(PUL / f"ckpt_partial_{n % 2}.tgz")   # keep the last two verified
    return ok


def wd_cfg(iid, deadline):
    return dict(iid=iid, deadline_epoch=deadline, run_pid_file=f"{REMOTE}/run.pid", key_name=KEY_NAME, run_token="runbox_eq.py", rc_file=f"{REMOTE}/run.rc",
                pulled_flag=f"{REMOTE}/PULLED", done_grace_s=1800, died_grace_s=1200, start_grace_s=1200, idle_min=0)


def extend_stops(ip, state, n):
    """New total cap -> new watchdog armed + verified BEFORE the old one is stopped; returns the new deadline or None."""
    f = LOGS / "EXTEND_CAP_USD"
    if not f.exists():
        return None
    try:
        cap = float(f.read_text().strip())
    except ValueError:
        f.replace(LOGS / f"EXTEND_CAP_USD.refused-{n}"); P("EXTEND REFUSED (not a number)"); return None
    new_dl = state["t_launch"] + cap * 100 / state["rate_c"] * 3600
    if new_dl <= state["deadline"] or new_dl - time.time() < 1800:
        f.replace(LOGS / f"EXTEND_CAP_USD.refused-{n}"); P(f"EXTEND REFUSED (cap ${cap} gives no later deadline)"); return None
    cf = LOGS / f"box_eq_wd{n}.json"; cf.write_text(json.dumps(wd_cfg(state["iid"], new_dl)))
    if not scp(str(cf), f"ubuntu@{ip}:{REMOTE}/wd{n}.json"):
        f.replace(LOGS / f"EXTEND_CAP_USD.refused-{n}"); P("EXTEND REFUSED (upload)"); return None
    old = ssh(ip, f"cat {REMOTE}/wd.pid", timeout=30).stdout.strip()
    try:
        ssh(ip, f"cd {REMOTE} && setsid nohup python3 {REMOTE}/wd.py {REMOTE}/wd{n}.json >> {REMOTE}/wd.log 2>&1 < /dev/null & exit 0", timeout=30)
    except subprocess.TimeoutExpired:
        pass
    time.sleep(8)
    r = ssh(ip, f"p=$(cat {REMOTE}/wd.pid); [ \"$p\" != \"{old}\" ] && tr '\\0' ' ' < /proc/$p/cmdline | grep -q wd{n}.json && echo WD_UP || echo WD_DOWN", timeout=30)
    if "WD_UP" not in r.stdout:
        f.replace(LOGS / f"EXTEND_CAP_USD.refused-{n}"); P("EXTEND REFUSED (new watchdog not up; old kept)"); return None
    ssh(ip, f"kill {old}", timeout=30)
    f.replace(LOGS / f"EXTEND_CAP_USD.applied-{n}")
    state.update(deadline=new_dl, max_usd=cap); save(state)
    P(f"EXTENDED: cap ${cap}, watchdog deadline in {(new_dl - time.time()) / 3600:.2f} h (old wd {old} stopped)")
    return new_dl


def main():
    if (sys.argv[1:] or [""])[0] != "go":
        raise SystemExit("usage: launch_eq.py go   (nothing launched)")
    LOGS.mkdir(exist_ok=True); PUL.mkdir(exist_ok=True)
    if stf.exists() and json.loads(stf.read_text()).get("stage") not in ("failed_terminated", "done", None):
        raise SystemExit(f"{stf} has a live box; refusing a second launch")
    live = lam.req("GET", "/instances")["data"]
    if [i for i in live if (i.get("name") or "").startswith(NAME)]:
        raise SystemExit(f"a {NAME} instance is already live; refusing")
    foreign = [(i["id"], i.get("name"), i["status"]) for i in live]
    if foreign:
        P(f"NOTE: {len(foreign)} foreign instance(s) on the account (not ours, untouched): {foreign}")
    types = lam.req("GET", "/instance-types")["data"]; pick = None
    for t in TYPES:
        regs = [r["name"] for r in types.get(t, {}).get("regions_with_capacity_available", [])]
        if regs:
            it = types[t]["instance_type"]; pick = (t, regs[0], it["price_cents_per_hour"], it["specs"]["vcpus"]); break
    if not pick:
        raise SystemExit(f"NO CAPACITY for {TYPES} (nothing launched)")
    itype, region, rate, vcpus = pick
    cap_h = int(CAP_C * 100 / rate) / 100.0
    assert rate * cap_h <= CAP_C
    t_launch = time.time(); deadline = t_launch + cap_h * 3600
    iid = lam.req("POST", "/instance-operations/launch", {"region_name": region, "instance_type_name": itype, "ssh_key_names": [KEY_NAME],
                                                           "quantity": 1, "name": NAME})["data"]["instance_ids"][0]
    state = dict(iid=iid, type=itype, region=region, rate_c=rate, vcpus=vcpus, t_launch=t_launch, deadline=deadline, cap_h=cap_h,
                 stage="launched", max_usd=round(rate * cap_h / 100, 2))
    save(state)
    P(f"LAUNCHED {iid} {itype} {region} {rate}c/h vcpus={vcpus} cap {cap_h}h (max ${rate * cap_h / 100:.2f})")
    ok = False
    try:
        ip = None
        while time.time() - t_launch < 1500:
            d = lam.req("GET", f"/instances/{iid}")["data"]; ip = d.get("ip")
            if d.get("status") == "active" and ip:
                try:
                    if ssh(ip, "echo ok", timeout=25).stdout.strip() == "ok":
                        break
                except subprocess.TimeoutExpired:
                    pass
            time.sleep(15)
        else:
            raise RuntimeError("not active+ssh in 1500 s")
        state.update(ip=ip, stage="ssh_up"); save(state); P(f"ssh up {ip} after {time.time() - t_launch:.0f}s")
        ssh(ip, f"mkdir -p {REMOTE}", check=True)
        for f in UP:
            if not scp(str(C / f), f"ubuntu@{ip}:{REMOTE}/{f}"):
                raise RuntimeError(f"upload failed {f}")
        r = ssh(ip, f"bash {REMOTE}/setup_eq.sh > {REMOTE}/setup.log 2>&1; tail -n 8 {REMOTE}/setup.log", timeout=1800)
        P("setup:", r.stdout.strip().replace("\n", " | "))
        if "SETUP_OK" not in r.stdout:
            raise RuntimeError("setup failed")
        state.update(stage="setup_ok"); save(state)
        ssh(ip, f"umask 077; cat > {REMOTE}/.lam_key", inp=lam.key() + "\n", timeout=30, check=True)
        cf = LOGS / "box_eq_wd.json"; cf.write_text(json.dumps(wd_cfg(iid, deadline)))
        if not scp(str(cf), f"ubuntu@{ip}:{REMOTE}/wd.json"):
            raise RuntimeError("wd.json upload failed")
        r = ssh(ip, f"chmod 600 {REMOTE}/.lam_key; python3 {REMOTE}/wd.py --verify {REMOTE}/wd.json", timeout=90)
        P("verify:", r.stdout.strip())
        if "KILL_PATH_OK" not in r.stdout:
            raise RuntimeError("KILL_PATH not OK")
        try:
            ssh(ip, f"cd {REMOTE} && setsid nohup python3 {REMOTE}/wd.py {REMOTE}/wd.json >> {REMOTE}/wd.log 2>&1 < /dev/null & exit 0", timeout=30)
        except subprocess.TimeoutExpired:
            pass
        time.sleep(8)
        r = ssh(ip, f"p=$(cat {REMOTE}/wd.pid); tr '\\0' ' ' < /proc/$p/cmdline | grep -q wd.json && echo WD_UP || echo WD_DOWN", timeout=30)
        if "WD_UP" not in r.stdout:
            raise RuntimeError("watchdog not up")
        state.update(stage="wd_armed"); save(state); P("watchdog armed")
        try:
            ssh(ip, f"cd {REMOTE} && NPAR={int(vcpus)} setsid nohup python3 {REMOTE}/runbox_eq.py > {REMOTE}/run.log 2>&1 < /dev/null & exit 0", timeout=30)
        except subprocess.TimeoutExpired:
            pass
        time.sleep(20)
        r = ssh(ip, f"p=$(cat {REMOTE}/run.pid); tr '\\0' ' ' < /proc/$p/cmdline | grep -q runbox_eq.py && echo RUN_UP || echo RUN_DOWN; tail -n 3 {REMOTE}/run.log", timeout=30)
        if "RUN_UP" not in r.stdout:
            raise RuntimeError("run not up: " + r.stdout[-400:])
        state.update(stage="running", t_run=time.time()); save(state); ok = True
        P(f"RUN_UP {iid} {ip} NPAR={vcpus}; watchdog deadline in {(deadline - time.time()) / 3600:.2f} h")
    finally:
        if not ok:
            P("FAILURE before RUN_UP -> terminating", iid)
            state.update(stage="failed_terminated", t_end=time.time(), terminated_verified=terminate_verify(iid)); save(state)
            sys.exit(1)

    # ---------------- poll + partial pull + extend (quiet: stage changes, failures, end) ----------------
    FINAL = ["status.json", "result.json", "ckpt.tgz", "logs.tgz", "run.log", "wd.log", "setup.log"]
    poll_limit = deadline - 25 * 60; last = None; n = 0; next_ext = 2
    while time.time() < poll_limit:
        time.sleep(300); n += 1
        try:
            nd = extend_stops(ip, state, next_ext)
            if nd:
                poll_limit = nd - 25 * 60; next_ext += 1
            if not pull_ckpt(ip, n):
                P("partial pull NOT verified this poll")
            pull(ip, ["status.json"])
            s = json.loads((PUL / "status.json").read_text())
            key = (s.get("stage"), tuple((j, (v or {}).get("verdict"), "A" in (v or {}), "C" in (v or {})) for j, v in s.get("jobs", {}).items()))
            if key != last:
                P(f"stage {s.get('stage')} steps {[(x['step'], x['ok']) for x in s.get('steps', [])]} "
                  f"jobs {json.dumps({j: dict(A=(v.get('A') or {}), S=(v.get('S') or {}), verdict=v.get('verdict')) for j, v in s.get('jobs', {}).items()})[:900]}")
                last = key
            r = ssh(ip, f"test -f {REMOTE}/run.rc && cat {REMOTE}/run.rc || echo NORC", timeout=30).stdout.strip()
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as e:   # logged; the next poll retries,
            P("poll error", e); continue                                       # the watchdog still bounds the box
        if r != "NORC":
            got = pull(ip, FINAL)
            P(f"run.rc {r}; pulled {got}")
            if r != "0":
                P("FAILED rc != 0: box LEFT UP for repair (watchdog DONE grace 30 min)"); state.update(stage=f"failed_rc{r}_up"); save(state)
                sys.exit(1)
            ssh(ip, f"touch {REMOTE}/PULLED", timeout=30)
            state.update(stage="done", rc=r, t_end=time.time()); save(state)
            break
    else:
        got = pull(ip, FINAL)
        P(f"POLL LIMIT reached; final pull {got}; terminating")
        state.update(stage="poll_limit", t_end=time.time()); save(state)
    tv = terminate_verify(iid); hrs = (time.time() - t_launch) / 3600
    state.update(terminated_verified=tv, hours=round(hrs, 2), cost_usd=round(hrs * rate / 100, 2)); save(state)
    P(f"END terminated={tv} hours {hrs:.2f} cost ${hrs * rate / 100:.2f}")
    if (PUL / "result.json").exists():
        P("RESULT", (PUL / "result.json").read_text()[:900])


if __name__ == "__main__":
    main()
