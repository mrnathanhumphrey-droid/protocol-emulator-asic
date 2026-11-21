"""STOCK vs SPLIT CROSS-CHECK on one real module (Wilson 11-21: "one real-design agreement makes it a method").
The stock one-process rtl_equiv recipe and the split pipeline run on the SAME staged pair; all four verdicts must be as wanted:
  equal pair   (<base>:src/<file> vs the worktree's, top <module>)            -> PROVEN by both
  planted pair (the worktree with --plant OLD NEW applied once)               -> NOT PROVEN by both, unproven cells at the assert
Banked 11-21: pe_symgen (src/pe_engine.v), base cdde6d5 (the len_of deletion), plant `assign ovr = ld & hv & ~consume;` ->
`& consume`: 105 cells; equal PROVEN / PROVEN (C handed 93 = the slices' unproven); planted NOT PROVEN / NOT PROVEN, 1 unproven
each; 13.6 s, 66 MB, 1 core.
  python model/eqsplit/xcheck_module.py --base cdde6d5 --file pe_engine.v --top pe_symgen \\
      --plant "assign ovr     = ld & hv & ~consume;" "assign ovr     = ld & hv &  consume;"  [--k 8] [--work DIR]
Stages under <work>/xcheck_<top>/ with the host's git, then runs yosys (on Windows: re-invoked in WSL, where yosys lives)."""
import argparse, json, os, re, shutil, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)


def wsl_path(p):
    d, rest = os.path.splitdrive(os.path.abspath(p))
    return "/mnt/%s%s" % (d[0].lower(), rest.replace("\\", "/"))


def stage(a):
    jroot = os.path.join(a.work, "xcheck_" + a.top); shutil.rmtree(jroot, ignore_errors=True)
    gold = subprocess.run(["git", "show", "%s:src/%s" % (a.base, a.file)], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8").stdout
    cur = open(os.path.join(ROOT, "src", a.file), encoding="utf-8", newline="").read()
    if not gold:
        raise SystemExit("cannot read %s:src/%s" % (a.base, a.file))
    if cur.count(a.plant[0]) != 1:
        raise SystemExit("plant site must occur exactly once in src/%s (found %d)" % (a.file, cur.count(a.plant[0])))
    for name, gate in (("eq", cur), ("mf", cur.replace(a.plant[0], a.plant[1], 1))):
        for side, txt in (("gold", gold), ("gate", gate)):
            d = os.path.join(jroot, name, side); os.makedirs(d)
            with open(os.path.join(d, a.file), "w", encoding="utf-8", newline="\n") as fh:
                fh.write(txt.replace("\r\n", "\n"))
    return jroot


def run(jroot, file, top, k):
    import eqsplit as E, eqjob as J
    os.environ.setdefault("RTL_EQUIV_DIR", os.path.join(ROOT, "model"))
    sys.path.insert(0, os.path.join(ROOT, "test"))
    from toolchain import banner, tool          # ruling V: the one resolver; the log names what ran
    banner("yosys")
    Y = [tool("yosys")]; pre = J.prefix([file], top); out = {}; ok = True
    for name, want in (("eq", "PROVEN"), ("mf", "NOT PROVEN")):
        jd = os.path.join(jroot, name)
        s = os.path.join(jd, "whole.ys")
        with open(s, "w", newline="\n") as fh:
            fh.write("\n".join(pre + E.TAIL) + "\n")
        rc, w, m = E.run_ys(Y, s, os.path.join(jd, "whole.log"), jd)
        txt = open(os.path.join(jd, "whole.log"), errors="replace").read()
        stock = "PROVEN" if (rc == 0 and "Equivalence successfully proven!" in txt) else "NOT PROVEN"
        fa = re.findall(r"Found (\d+) unproven \$equiv cells in 'equiv_status -assert'", txt)
        sp = J.run_job(Y, jd, pre, k=k, par=1)
        spc = sp.get("C") or {}
        red_ok = want == "PROVEN" or (bool(fa) and int(fa[-1]) > 0 and (spc.get("assert_unproven") or 0) > 0)
        good = stock == want and sp["verdict"] == want and red_ok
        ok &= good
        out[name] = dict(want=want, stock=stock, stock_rc=rc, stock_wall_s=w, stock_rss_gb=m,
                         stock_unproven=(int(fa[-1]) if fa else None), split=sp["verdict"], split_A=sp.get("A"),
                         split_S=sp.get("S"), split_C=spc, agree=good)
        print(name, "stock:", stock, "| split:", sp["verdict"], "| want:", want, "OK" if good else "BAD", flush=True)
    with open(os.path.join(jroot, "xcheck_result.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    print("XCHECK_OK" if ok else "XCHECK_BAD")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base"); ap.add_argument("--file"); ap.add_argument("--top")
    ap.add_argument("--plant", nargs=2); ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--work", default=os.path.join(ROOT, "formal", "build", "eqsplit"))
    ap.add_argument("--run", help="(internal) a staged dir: run only")
    a = ap.parse_args()
    if a.run:
        return run(a.run, a.file, a.top, a.k)
    jroot = stage(a)
    if os.name == "nt":
        return subprocess.run(["wsl.exe", "--", "python3", wsl_path(__file__), "--run", wsl_path(jroot), "--file", a.file,
                               "--top", a.top, "--k", str(a.k)]).returncode
    return run(jroot, a.file, a.top, a.k)


if __name__ == "__main__":
    sys.exit(main())
