"""THE MANIFEST STEP: stage the box's upload set in one work dir (default formal/build/eqsplit/, gitignored).
  jobs/eq  : <base>:src/* (gold) vs the worktree's src/* (gate)                        -- the proof
  jobs/mf  : the same with model/rtl_equiv.py's PLANT applied to project.v (gate)      -- its MUST-FIRE (must end red)
  manifest.json : sha256 of every staged source + rtl_equiv.py (runbox_eq.py's preflight refuses any mismatch)
  + rtl_equiv.py (its YS is the recipe), the eqsplit runner files, toy.tgz (the toy must-fire)
Line endings are normalised to LF on both sides. The yosys bundle (ybin.tgz) is built separately by make_bundle.sh.
  python model/eqsplit/prep_jobs.py --base <rev> [--work DIR]"""
import argparse, hashlib, json, os, shutil, subprocess, sys, tarfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "model"))
import rtl_equiv as R

RUNNER = ["eqsplit.py", "eqjob.py", "toy_test.py", "runbox_eq.py", "setup_eq.sh", "wd.py"]


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--work", default=os.path.join(ROOT, "formal", "build", "eqsplit"))
    a = ap.parse_args()
    W = a.work; J = os.path.join(W, "jobs")
    shutil.rmtree(J, ignore_errors=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    base = subprocess.run(["git", "rev-parse", a.base], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if not base:
        raise SystemExit("cannot resolve --base %s" % a.base)
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "src"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    man = dict(base=base, head=head, src_dirty=bool(dirty), files={})
    for job in ("eq", "mf"):
        for side in ("gold", "gate"):
            os.makedirs(os.path.join(J, job, side))
        for f in R.FILES:
            g = subprocess.run(["git", "show", "%s:src/%s" % (base, f)], cwd=ROOT, capture_output=True,
                               text=True, encoding="utf-8").stdout
            if not g:
                raise SystemExit("cannot read %s:src/%s" % (base, f))
            cur = open(os.path.join(ROOT, "src", f), encoding="utf-8", newline="").read()
            if job == "mf" and f == "project.v":
                if R.PLANT[0] not in cur:
                    raise SystemExit("must-fire plant site not found in src/project.v")
                cur = cur.replace(R.PLANT[0], R.PLANT[1], 1)
            for side, txt in (("gold", g), ("gate", cur)):
                p = os.path.join(J, job, side, f)
                with open(p, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(txt.replace("\r\n", "\n"))
                man["files"]["%s/%s/%s" % (job, side, f)] = sha(p)
    shutil.copy(os.path.join(ROOT, "model", "rtl_equiv.py"), os.path.join(W, "rtl_equiv.py"))
    man["files"]["rtl_equiv.py"] = sha(os.path.join(W, "rtl_equiv.py"))
    for f in RUNNER:
        shutil.copy(os.path.join(HERE, f), os.path.join(W, f))
    with open(os.path.join(W, "manifest.json"), "w") as fh:
        json.dump(man, fh, indent=1)
    with tarfile.open(os.path.join(W, "jobs.tgz"), "w:gz") as t:
        t.add(J, arcname="jobs")
    with tarfile.open(os.path.join(W, "toy.tgz"), "w:gz") as t:
        t.add(os.path.join(HERE, "toy"), arcname="toy")
    print(json.dumps({k: v[:12] for k, v in man["files"].items()}, indent=0))
    print("base %s head %s src_dirty %s -> %s" % (base[:7], head[:7], man["src_dirty"], W))
    print("eq gold==gate per file:", {f: man["files"]["eq/gold/" + f] == man["files"]["eq/gate/" + f] for f in R.FILES})


if __name__ == "__main__":
    main()
