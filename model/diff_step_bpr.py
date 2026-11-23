"""Differential sign-off: model/step_b.py's step_bpr against Lean ArmP.stepBPR via #eval.

The plain ARM end and HALF (agent 1's replay at dd04588, 11-23): the armed run's latches --
FALLTHROUGH `ft`, the release offset `off` (HALF's l_t/2, 0 for a plain ARM), no-timeout `nt` --
and the halted lanes. Built on diff_step_btr (its random engine state, its Lean header and
renderer); each case adds random latches, halts and the retiring ARM's word fields.
Signed off 11-23: 1000 cases, 0 mismatches (153 with a plain edge, 89 of them off > 0; 173 with a
FALLTHROUGH edge; 19 plain timeouts, 19 FALLTHROUGH timeouts; 5 timeouts a no-timeout ARM
suppresses; 552 with a halted lane; 100 arming). Planted, each caught: a plain edge flushes
(170/1000), the offset ignored (89), the rebase bit set for off > 0 (89), no halt at a plain
timeout (15), no-timeout ignored (5), a halted lane still live (28), still dispatchable (70).
Re-signed 11-23 for the clocked park (Wilson's ruling: the park clears FALLTHROUGH; latches
nt, off = hdly) and the watchdog halt (ext park / hd_w / wd): 1000 cases, 0 mismatches (102
parks, 59 of them on a lane whose ft was set; 237 with a watchdog firing; 159 plain edges, 103
with off > 0; 10 plain timeouts). Planted, each caught: the park keeps a stale ft (59/1000),
ignores hdly (86), keeps nt (77), does not arm (41); the watchdog does not halt (207), leaves the
lane armed (110); step 1's seven re-caught (158, 103, 103, 8, 6, 26, 56).
Usage: python model/diff_step_bpr.py [N] [SEED]   (defaults 1000, 7); rc 0 = no mismatch.
Needs the Lean library built (lake build).
"""
import os, random, subprocess, sys, tempfile

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(WT, "model"))
import step_b as S  # noqa: E402
import diff_step_btr as D  # noqa: E402

K = S.K


def render(B):
    L = range(K)
    head, usb = D.render(B["A"]).rsplit("|", 1)   # D.render ends with usb_on (Lean's flag)
    return "|".join([
        head,
        ",".join(D.b(B["ft"][l]) for l in L),
        ",".join(str(B["off"][l]) for l in L),
        ",".join(D.b(B["nt"][l]) for l in L),
        ",".join(D.b(B["halt"][l]) for l in L),
        usb,
    ])


def rand_case(rng):
    A, P, ext = D.rand_case(rng)
    rb = lambda p=0.5: rng.random() < p
    offs = lambda: 0 if rb(0.4) else rng.randint(1, 6)
    B = {"A": A,
         "ft": [rb(0.5) for _ in range(K)],
         "off": [offs() for _ in range(K)],
         "nt": [rb(0.2) for _ in range(K)],
         "halt": [rb(0.15) for _ in range(K)]}
    ext["is_ft"] = rb(0.5)
    ext["off_w"] = offs()
    ext["nt_w"] = rb(0.2)
    ext["park"] = rb(0.3)
    ext["hd_w"] = offs()
    ext["wd"] = [rb(0.05) for _ in range(K)]
    if rb(0.3):
        # a third of the cases on an edge cycle of an armed lane (a fully random state meets
        # now == armE about once in 80 per lane)
        l = rng.randrange(K)
        A["armed"][l] = True
        A["armE"][l] = A["X"]["x"]["now"]
    return B, P, ext


def lean_case(i, B, P, ext):
    A = B["A"]
    x = A["X"]["x"]
    lb, ln, lopt = D.lb, D.ln, D.lopt
    e = ("{ now := %d, actv := tb2 [%s], sel := tb1 %s, ts := tn1 %s, pst := .%s, pl := %d, "
         "prr := %d, pbr1 := %s, pslot := %s, winq := %s, st := .%s, cur := %d, npf := tb2 [%s] }"
         % (x["now"], ", ".join(lb(r) for r in x["actv"]), lb(x["sel"]), ln(x["ts"]), x["pst"],
            x["pl"], x["prr"], "true" if x["pbr1"] else "false", "true" if x["pslot"] else "false",
            lopt(x["winq"]), x["st"], x["cur"], ", ".join(lb(r) for r in x["npf"])))
    eb = ("{ e := %s, buf := tb1 %s, bnpf := tb1 %s, pb := %s, sq := tn2 [%s], bsq := tn1 %s, "
          "psq := %d, nr := tn1 %s }"
          % (e, lb(x["buf"]), lb(x["bnpf"]), "true" if x["pb"] else "false",
             ", ".join(ln(r) for r in x["sq"]), ln(x["bsq"]), x["psq"], ln(x["nr"])))
    a = ("{ X := { x := %s, pkill := %s, reb := tb1 %s }, armed := tb1 %s, armE := tn1 %s }"
         % (eb, "true" if A["X"]["pkill"] else "false", lb(A["X"]["reb"]), lb(A["armed"]),
            ln(A["armE"])))
    bp = ("{ A := %s, ft := tb1 %s, off := tn1 %s, nt := tb1 %s, halt := tb1 %s }"
          % (a, lb(B["ft"]), ln(B["off"]), lb(B["nt"]), lb(B["halt"])))
    p = ("{ live := tb1 %s, dly := tn1 %s, ext := fun _ _ => %d, ret := fun _ _ => %s, "
         "fnpf := fun _ => %s }"
         % (lb(P["live"]), ln(P["dly"]), ext["xd"], "true" if ext["ret"] else "false",
            "true" if ext["fnpf"] else "false"))
    tf = lambda v: "true" if v else "false"
    call = ("stepBPR (%s : Program) (fun _ => %s) (usbOf %s) (fun _ => %s) (fun _ => %s) "
            "(fun _ l => tn1 %s l) (fun _ => %s) (fun _ => %d) (fun _ => %s) (fun _ => %s) "
            "(fun _ => %d) (tb1 %s) (tb1 %s) (tn1 %s) (%s : EngBP)"
            % (p, lopt(ext["win"]), tf(x["usb_on"]), lopt(ext["sreq"]), tf(ext["is_arm"]),
               ln(ext["edge"]), tf(ext["is_ft"]), ext["off_w"], tf(ext["nt_w"]),
               tf(ext["park"]), ext["hd_w"], lb(ext["wd"]), lb(ext["nw"]), ln(ext["k"]), bp))
    flag = "rb (%s || %s)" % (tf(x["usb_on"]), tf(ext["usb_rx"]))
    return ('#eval IO.println ("CASE %d " ++ renderB (%s) ++ "|" ++ %s)\n' % (i, call, flag))


HEADER = D.HEADER + r'''def renderB (B : EngBP) : String :=
  String.intercalate "|" [renderA B.A,
    csv (lanes.map fun l => rb (B.ft l)),
    csv (lanes.map fun l => toString (B.off l)),
    csv (lanes.map fun l => rb (B.nt l)),
    csv (lanes.map fun l => rb (B.halt l))]

'''


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 7
    outdir = tempfile.mkdtemp(prefix="diff_step_bpr_")
    rng = random.Random(seed)
    cases = [rand_case(rng) for _ in range(n)]
    src = HEADER + "".join(lean_case(i, *c) for i, c in enumerate(cases))
    path = os.path.join(outdir, "DiffBPR.lean")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(src)
    r = subprocess.run(["lake", "env", "lean", path], cwd=os.path.join(WT, "lean", "JLane"),
                       capture_output=True, text=True, encoding="utf-8")
    got = {}
    for line in r.stdout.splitlines():
        if line.startswith("CASE "):
            _, i, rest = line.split(" ", 2)
            got[int(i)] = rest
    if r.returncode != 0 or len(got) != n:
        print("LEAN FAILED (rc %d, %d/%d cases): %s" % (r.returncode, len(got), n,
                                                        (r.stdout + r.stderr)[-1500:]))
        return 2
    bad = 0
    for i, (B, P, ext) in enumerate(cases):
        py = render(S.step_bpr(P, B, ext))
        if py != got[i]:
            bad += 1
            if bad <= 3:
                pf, lf = py.split("|"), got[i].split("|")
                fields = [j for j in range(min(len(pf), len(lf))) if pf[j] != lf[j]]
                print("MISMATCH case %d fields %s: py %s / lean %s"
                      % (i, fields, [pf[j] for j in fields], [lf[j] for j in fields]))
    print("differential step_bpr vs Lean stepBPR: %d cases, %d mismatches" % (n, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
