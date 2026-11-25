"""harden.yml metrics + gates (Wilson ruling 11-25).

  python ci/harden/metrics.py stage J2 runs/j2 [--no-gates]   -> stage_J2.json, a summary line; exit 1 if the gate fails
  python ci/harden/metrics.py last-state runs/j1               -> prints the state_out.json of the run dir's last step
  python ci/harden/metrics.py summary results/ [--jobs JSON]   -> the run's summary block (pass/fail, stage reached,
                                                                   worst setup/hold, area, DRC); exit 1 if anything failed
"""
import glob, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
G = json.load(open(os.path.join(HERE, "gates.json")))


def steps(rd):
    return sorted(d for d in glob.glob(os.path.join(rd, "[0-9]*-*")) if os.path.isdir(d))


def last_state(rd):
    for d in reversed(steps(rd)):
        p = os.path.join(d, "state_out.json")
        if os.path.exists(p):
            return p
    return None


def grep_all(pattern, rx):
    out = []
    for f in sorted(glob.glob(pattern)):
        out += re.findall(rx, open(f, errors="replace").read())
    return out


def corners(m, kind):
    return {k.split("corner:")[1]: v for k, v in m.items() if k.startswith(f"timing__{kind}__ws__corner:")}


def stage(name, rd, gates=True):
    sp = last_state(rd)
    m = json.load(open(sp)).get("metrics", {}) if sp else {}
    r = {"stage": name, "run_dir": rd, "last_step": os.path.basename(os.path.dirname(sp)) if sp else None,
         "util_pct": round(100 * m["design__instance__utilization"], 2) if "design__instance__utilization" in m else None,
         "area_um2": m.get("design__instance__area"), "setup_ws": corners(m, "setup"), "hold_ws": corners(m, "hold"),
         "fail": []}
    tot = grep_all(f"{rd}/*-openroad-globalrouting/openroad-globalrouting.log",
                   r"Total\s+\d+\s+\d+\s+([\d.]+)%\s+\d+\s*/\s*\d+\s*/\s*(\d+)")
    if tot:
        r["grt_usage_pct"], r["grt_overflow"] = float(tot[-1][0]), int(tot[-1][1])
    sys.path.insert(0, HERE)
    import drt_counts                      # the router's per-pass reports, not the buffered log (11-25)
    vio = drt_counts.counts(rd)
    if vio:
        r["drt_violations"] = vio
    for k in ("route__drc_errors", "route__antenna_violation__count", "antenna__violating__nets", "design__lvs_error__count",
              "magic__drc_error__count", "klayout__drc_error__count"):
        if k in m:
            r[k] = m[k]
    if gates and name in G:
        g = G[name]
        if name == "J1":
            if r["util_pct"] is not None and r["util_pct"] > g["util_max_pct"]:
                r["fail"].append(f"utilisation {r['util_pct']} % > {g['util_max_pct']} %")
            typ = [v for c, v in r["setup_ws"].items() if "typ" in c]
            if typ and min(typ) < g["typ_setup_wns_min_ns"]:
                r["fail"].append(f"typical-corner setup {min(typ):+.3f} ns < {g['typ_setup_wns_min_ns']}")
        if name == "J2":
            if r.get("grt_usage_pct") is None:
                r["fail"].append("no global-routing report found")
            elif r["grt_usage_pct"] > g["grt_usage_max_pct"]:
                r["fail"].append(f"global-route usage {r['grt_usage_pct']} % > {g['grt_usage_max_pct']} % (overflow {r.get('grt_overflow')})")
        if name == "J3":
            for k, lim in g["drt_pass_max"].items():
                v = r.get("drt_violations", [])
                if len(v) > int(k) and v[int(k)] > lim:
                    r["fail"].append(f"DRT pass {k}: {v[int(k)]} > {lim}")
        if name == "J4":
            if r["setup_ws"] and min(r["setup_ws"].values()) < g["setup_wns_min_ns"]:
                r["fail"].append(f"setup WNS {min(r['setup_ws'].values()):+.3f} ns")
            if r["hold_ws"] and min(r["hold_ws"].values()) < g["hold_wns_min_ns"]:
                r["fail"].append(f"hold WNS {min(r['hold_ws'].values()):+.3f} ns")
            if r.get("route__drc_errors", 0) > g["route_drc_max"]:
                r["fail"].append(f"routed DRC {r['route__drc_errors']}")
            if r.get("route__antenna_violation__count", 0) > g["antenna_max"]:
                r["fail"].append(f"antenna {r['route__antenna_violation__count']}")
            if r["hold_ws"] and min(r["hold_ws"].values()) < g["hold_warn_below_ns"]:
                r["warn"] = f"hold WNS {min(r['hold_ws'].values()):+.3f} ns is under +{g['hold_warn_below_ns']} ns"
    json.dump(r, open(f"stage_{name}.json", "w"), indent=1)
    line = f"**{name}** {'PASS' if not r['fail'] else 'FAIL: ' + '; '.join(r['fail'])} -- " + ", ".join(
        f"{k} {v}" for k, v in r.items() if k in ("last_step", "util_pct", "grt_usage_pct", "grt_overflow") and v is not None)
    if r.get("drt_violations"):
        line += f", DRT per pass {r['drt_violations'][:8]}"
    if r["setup_ws"]:
        line += ", setup " + " ".join(f"{c.split('_')[1]} {v:+.2f}" for c, v in sorted(r["setup_ws"].items()))
    if r["hold_ws"]:
        line += ", hold " + " ".join(f"{c.split('_')[1]} {v:+.3f}" for c, v in sorted(r["hold_ws"].items()))
    print(line)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a").write(line + "\n\n")
    return 0 if not r["fail"] else 1


def summary(d, jobs_json):
    res = {}
    for f in sorted(glob.glob(os.path.join(d, "**", "stage_*.json"), recursive=True)):
        r = json.load(open(f)); res[r["stage"]] = r
    jobs = json.loads(jobs_json) if jobs_json else {}
    order = ["J1", "J2", "J3", "J4"]
    reached = max((s for s in order if s in res), key=order.index, default="none")
    failed = [f"{s}: {'; '.join(res[s]['fail'])}" for s in order if s in res and res[s]["fail"]]
    failed += [f"{j}: {v}" for j, v in jobs.items() if v not in ("success", "skipped")]
    last = res.get(reached, {})
    out = ["## Harden result", "",
           f"**{'PASS' if not failed else 'FAIL'}** -- stage reached: **{reached}**", ""]
    if failed:
        out += ["Failed: " + " | ".join(failed), ""]
    out += ["| stage | result | util % | GRT usage % | DRT pass 0 / last | worst setup ns | worst hold ns | area um2 |",
            "|---|---|---|---|---|---|---|---|"]
    for s in order:
        if s not in res:
            continue
        r = res[s]; v = r.get("drt_violations") or []
        out.append(f"| {s} | {'pass' if not r['fail'] else 'FAIL'} | {r.get('util_pct')} | {r.get('grt_usage_pct', '')} | "
                   f"{(str(v[0]) + ' / ' + str(v[-1])) if v else ''} | {min(r['setup_ws'].values()) if r['setup_ws'] else ''} | "
                   f"{min(r['hold_ws'].values()) if r['hold_ws'] else ''} | {r.get('area_um2')} |")
    if jobs:
        out += ["", "Jobs: " + ", ".join(f"{j} {v}" for j, v in jobs.items())]
    if last.get("warn"):
        out += ["", "Warning: " + last["warn"]]
    txt = "\n".join(out) + "\n"
    print(txt)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a").write(txt)
    return 0 if not failed else 1


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "stage":
        sys.exit(stage(a[1], a[2], gates="--no-gates" not in a))
    if a[0] == "last-state":
        p = last_state(a[1]); print(p or ""); sys.exit(0 if p else 1)
    if a[0] == "summary":
        sys.exit(summary(a[1], a[a.index("--jobs") + 1] if "--jobs" in a else ""))
    raise SystemExit(__doc__)
