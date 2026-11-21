"""TOY MUST-FIRE of the split pipeline (seconds): the equal pair (a counter stored inverted -- only equiv_induct proves it)
must be PROVEN through stage C, the planted pair (one term inverted) NOT PROVEN; and the un-split rtl_equiv recipe must agree
on both.  Gates every box run (runbox_eq.py's dry stage).   python3 toy_test.py <yosys cmd...>   -> TOY_OK / TOY_BAD"""
import json, os, shutil, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import eqsplit as E, eqjob as J

if sys.argv[1:]:
    Y = sys.argv[1:]                 # the box: the bundle's yosys, its banner already checked against the pin (preflight)
else:                                # local: ruling V, the one resolver, and the log names what ran
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "test"))
    from toolchain import banner, tool
    banner("yosys"); Y = [tool("yosys")]
root = tempfile.mkdtemp(prefix="eqsplit_toy_")
ok = True
for name, gate, want in (("eq", "gate", "PROVEN"), ("mf", "plant", "NOT PROVEN")):
    jd = os.path.join(root, name); os.makedirs(jd)
    shutil.copytree(os.path.join(HERE, "toy", "gold"), os.path.join(jd, "gold"))
    shutil.copytree(os.path.join(HERE, "toy", gate), os.path.join(jd, "gate"))
    pre = J.prefix(["t.v"], "ttop")
    with open(os.path.join(jd, "whole.ys"), "w", newline="\n") as fh:      # the un-split reference: one process
        fh.write("\n".join(pre + E.TAIL) + "\n")
    rc, w, m = E.run_ys(Y, os.path.join(jd, "whole.ys"), os.path.join(jd, "whole.log"), jd)
    wtxt = open(os.path.join(jd, "whole.log")).read()
    whole = "PROVEN" if (rc == 0 and "Equivalence successfully proven!" in wtxt) else "NOT PROVEN"
    out = J.run_job(Y, jd, pre, k=3, par=2)
    # the planted pair must be red for the right reason: unproven cells at the assert, not a crash
    red_ok = want == "PROVEN" or ((out.get("C") or {}).get("assert_unproven") or 0) > 0
    good = out["verdict"] == want and whole == want and red_ok
    ok &= good
    print(name, "split:", out["verdict"], "| whole:", whole, "| want:", want, "OK" if good else "BAD")
    print("   ", json.dumps({k: out.get(k) for k in ("A", "S", "C")}))
shutil.rmtree(root, ignore_errors=True)
print("TOY_OK" if ok else "TOY_BAD")
sys.exit(0 if ok else 1)
