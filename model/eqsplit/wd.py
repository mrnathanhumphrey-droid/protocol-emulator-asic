"""LAMBDA1 on-instance self-terminating watchdog (stdlib only, system python3).

usage:  python3 wd.py --verify /home/ubuntu/l1/wd.json    -> prints KILL_PATH_OK (GET /instances/<iid> from the box)
        python3 wd.py /home/ubuntu/l1/wd.json             -> arm (launcher runs it under setsid nohup)

wd.json: {"iid", "deadline_epoch", "run_pid_file", "run_token", "rc_file", "pulled_flag",
          "done_grace_s", "died_grace_s", "start_grace_s", "idle_min" (0 = disabled; GPU boxes only)}
API key: sibling file .lam_key (chmod 600), never on a command line.

Kill conditions (terminate THIS instance id only, passed in by the launcher):
  DEADLINE  wall clock >= deadline_epoch (no grace)
  DONE      rc file exists and (pulled flag exists or rc older than done_grace_s)
  DIED      run pid (from run_pid_file) gone or its /proc cmdline lacks run_token, rc absent,
            4 consecutive misses then died_grace_s for a final pull; no pid file start_grace_s after arm = died
  IDLE      (idle_min > 0) max GPU util < 5% for idle_min minutes
Fail-deadly: any exception in the loop -> terminate; terminate failing 20x -> sudo shutdown -h now (best effort;
a halted box still bills, so terminate is retried first).
Identity: pid + /proc/<pid>/cmdline, never pgrep (cannot self-match).
"""
import json, os, sys, time, subprocess, traceback, urllib.request

API = "https://cloud.lambda.ai/api/v1"
UA = "eqsplit-watchdog/1.0 (python-urllib)"
verify_mode = sys.argv[1] == "--verify"
CFGP = sys.argv[-1]
D = os.path.dirname(os.path.abspath(CFGP))
CFG = json.load(open(CFGP))
KEY = open(os.path.join(D, ".lam_key")).read().strip()
IID = CFG["iid"]
LOG = os.path.join(D, "wd.log")
HB = os.path.join(D, "wd_heartbeat.json")


def log(msg):
    line = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + " [WD] " + msg
    print(line, flush=True)


def api(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    rq = urllib.request.Request(API + path, data=data, method=method,
                                headers={"Authorization": "Bearer " + KEY, "User-Agent": UA,
                                         "Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(rq, timeout=30) as r:
        return r.status, json.loads(r.read().decode() or "{}")


def terminate(reason):
    log(f"TERMINATE reason={reason}")
    for i in range(20):
        try:
            st, js = api("POST", "/instance-operations/terminate", {"instance_ids": [IID]})
            log(f"terminate POST {st} {json.dumps(js)[:200]}")
            if st < 300:
                for _ in range(20):
                    time.sleep(15)
                    try:
                        _, g = api("GET", f"/instances/{IID}")
                        log(f"status now {g.get('data', {}).get('status')}")
                    except (OSError, ValueError) as e:  # 404 once gone (urllib errors are OSError); logged
                        log(f"status check: {e}")
                return
        except (OSError, ValueError) as e:     # logged; retried 20x, then the fail-deadly shutdown
            log(f"terminate err {i+1}/20: {e}")
        time.sleep(15)
    log("terminate FAILED 20x -> shutdown -h now (fail-deadly)")
    os.system("sudo shutdown -h now")


if verify_mode:
    st, js = api("GET", f"/instances/{IID}")
    d = js.get("data", {})
    ok = st == 200 and d.get("id") == IID and d.get("ssh_key_names") == [CFG.get("key_name", "ML-CF")]
    print(("KILL_PATH_OK" if ok else "KILL_PATH_BAD") + f" status={d.get('status')} id_match={d.get('id') == IID}"
          f" key={d.get('ssh_key_names')} deadline_in_h={(CFG['deadline_epoch'] - time.time()) / 3600:.2f}")
    sys.exit(0 if ok else 3)


def run_alive():
    try:
        pid = int(open(CFG["run_pid_file"]).read().strip())
    except (OSError, ValueError):
        return None  # no / partial pid file yet: judged by start_grace_s
    try:
        cmd = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return False  # pid gone: the DIED verdict
    return CFG["run_token"] in cmd


def gpu_max_util():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=30).stdout
        vals = [float(x) for x in out.split()]
        return max(vals) if vals else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None  # no GPU reading: IDLE is not judged this tick


def main():
    open(os.path.join(D, "wd.pid"), "w").write(str(os.getpid()))
    t_arm = time.time(); misses = 0; died_at = None; idle_since = None
    log(f"armed iid={IID} deadline_in_h={(CFG['deadline_epoch'] - t_arm) / 3600:.2f} idle_min={CFG.get('idle_min', 0)}")
    while True:
        now = time.time()
        state = {"t": now, "iid": IID, "deadline_left_h": round((CFG["deadline_epoch"] - now) / 3600, 3)}
        if now >= CFG["deadline_epoch"]:
            terminate("DEADLINE"); return
        rc = CFG["rc_file"]
        if os.path.exists(rc):
            age = now - os.path.getmtime(rc)
            state["rc_age_s"] = round(age)
            if os.path.exists(CFG["pulled_flag"]):
                terminate("DONE+PULLED"); return
            if age > CFG["done_grace_s"]:
                terminate("DONE+grace"); return
        else:
            a = run_alive()
            state["run_alive"] = a
            if a is None:
                if now - t_arm > CFG["start_grace_s"]:
                    terminate("NO RUN PID after start grace"); return
            elif a:
                misses = 0; died_at = None
            else:
                misses += 1
                if misses >= 4 and died_at is None:
                    died_at = now; log("run died without rc; died-grace started")
                if died_at is not None and now - died_at > CFG["died_grace_s"]:
                    terminate("RUN DIED without rc"); return
        if CFG.get("idle_min", 0) > 0:
            u = gpu_max_util()
            state["gpu_max_util"] = u
            if u is not None and u < 5:
                idle_since = idle_since or now
                if now - idle_since > CFG["idle_min"] * 60:
                    terminate("IDLE GPU"); return
            else:
                idle_since = None
        state["misses"] = misses
        tmp = HB + ".tmp"; open(tmp, "w").write(json.dumps(state)); os.replace(tmp, HB)
        time.sleep(30)


try:
    main()
except BaseException:                      # fail-deadly: terminate the box, then re-raise (ruling E)
    log("EXCEPTION (fail-deadly):\n" + traceback.format_exc())
    terminate("WATCHDOG EXCEPTION")
    raise
log("watchdog exit")
