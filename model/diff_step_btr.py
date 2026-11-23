"""Differential sign-off: model/step_b.py's step_btr against Lean RtlRun.stepBTR via #eval.

Random states and inputs (every field random, reachable or not); each case is written as Lean
definitions, stepBTR is evaluated by Lean (`lake env lean`, a temp file outside the library),
rendered canonically, and compared line by line with the Python step_btr on the same case.
Signed off 11-22: 1000 cases, 0 mismatches; a planted spare-first load caught (26/50).
K13's usb_on (UsbOn): the Lean call takes usb := usbOf on and the flag's next value on || rx, as
UsbOn.stepBU; the Python carries x["usb_on"] and ext["usb_rx"].
Re-signed 11-22 for ruling 1b (the timeout ends at the pick: armed, deadline reached, dispatcher
idle, the unmasked scheduler naming the lane, no edge): 1000 cases, 0 mismatches, 33 with a
timeout pick; planted old deadline-only timeout caught (516/1000), planted pick without the idle
condition caught (62/1000).
Usage: python model/diff_step_btr.py [N] [SEED]   (defaults 1000, 7); rc 0 = no mismatch.
Needs the Lean library built (lake build). Memory: ~1.7 GB peak at N = 1000.
"""
import os, random, subprocess, sys, tempfile

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(WT, "model"))
import step_b as S  # noqa: E402

K = S.K
PST = ["scan", "req", "wait", "cap"]
ST = ["idle", "drive", "wb"]


def b(v):
    return "1" if v else "0"


def render(A):
    x = A["X"]["x"]
    L = range(K)
    parts = [
        str(x["now"]),
        ",".join(b(x["actv"][l][0]) + b(x["actv"][l][1]) for l in L),
        ",".join(b(x["sel"][l]) for l in L),
        ",".join(str(x["ts"][l]) for l in L),
        x["pst"], str(x["pl"]), str(x["prr"]), b(x["pbr1"]), b(x["pslot"]),
        "-" if x["winq"] is None else str(x["winq"]),
        x["st"], str(x["cur"]),
        ",".join(b(x["npf"][l][0]) + b(x["npf"][l][1]) for l in L),
        ",".join(b(x["buf"][l]) for l in L),
        ",".join(b(x["bnpf"][l]) for l in L),
        b(x["pb"]),
        ",".join(str(x["sq"][l][0]) + ":" + str(x["sq"][l][1]) for l in L),
        ",".join(str(x["bsq"][l]) for l in L),
        str(x["psq"]),
        ",".join(str(x["nr"][l]) for l in L),
        b(A["X"]["pkill"]),
        ",".join(b(A["armed"][l]) for l in L),
        ",".join(str(A["armE"][l]) for l in L),
        b(x.get("usb_on", False)),
    ]
    return "|".join(parts)


def rand_case(rng):
    rb = lambda p=0.5: rng.random() < p
    now = rng.randint(0, 60)
    x = {
        "now": now,
        "actv": [[rb(), rb()] for _ in range(K)],
        "sel": [rb() for _ in range(K)],
        "ts": [rng.randint(0, 80) for _ in range(K)],
        "pst": rng.choice(PST), "pl": rng.randrange(K), "prr": rng.randrange(K),
        "pbr1": rb(), "pslot": rb(),
        "winq": None if rb(0.3) else rng.randrange(K),
        "st": rng.choice(ST), "cur": rng.randrange(K),
        "npf": [[rb(0.2), rb(0.2)] for _ in range(K)],
        "buf": [rb(0.3) for _ in range(K)],
        "bnpf": [rb(0.2) for _ in range(K)],
        "pb": rb(),
        "sq": [[rng.randint(0, 9), rng.randint(0, 9)] for _ in range(K)],
        "bsq": [rng.randint(0, 9) for _ in range(K)],
        "psq": rng.randint(0, 9),
        "nr": [rng.randint(0, 9) for _ in range(K)],
        "usb_on": rb(),
    }
    A = {"X": {"x": x, "pkill": rb(0.3)}, "armed": [rb(0.4) for _ in range(K)],
         "armE": [rng.randint(0, 80) for _ in range(K)]}
    P = {"live": [rb(0.8) for _ in range(K)], "dly": [rng.randint(1, 40) for _ in range(K)],
         "pick": False, "usb": None}
    ext = {"win": None if rb(0.3) else rng.randrange(K),
           "sreq": None if rb(0.5) else rng.randrange(K),
           "ret": rb(0.8), "xd": rng.randint(0, 5), "fnpf": rb(0.2), "pick": None,
           "is_arm": rb(0.4), "nw": [rb(0.2) for _ in range(K)],
           "k": [rng.randint(0, 9) for _ in range(K)],
           "edge": [rng.randint(0, 90) for _ in range(K)],
           "usb_rx": rb(0.2)}
    if rb(0.25):
        # a quarter of the cases at the slot's USB yield (K13): a scan, branch 1 at lane 0 (live,
        # head empty), a slot request pending -- usb_on decides between the USB refill and the
        # slot (a fully random state meets this about once in 300 cases)
        x["pst"] = "scan"
        x["winq"] = 0
        P["live"][0] = True
        x["actv"][0][int(x["sel"][0])] = False
        ext["sreq"] = rng.randrange(1, K)
    return A, P, ext


def lb(xs):
    return "[" + ", ".join("true" if v else "false" for v in xs) + "]"


def ln(xs):
    return "[" + ", ".join(str(v) for v in xs) + "]"


def lopt(v):
    return "none" if v is None else "(some (%d : Lane))" % v


def lean_case(i, A, P, ext):
    x = A["X"]["x"]
    e = ("{ now := %d, actv := tb2 [%s], sel := tb1 %s, ts := tn1 %s, pst := .%s, pl := %d, "
         "prr := %d, pbr1 := %s, pslot := %s, winq := %s, st := .%s, cur := %d, npf := tb2 [%s] }"
         % (x["now"], ", ".join(lb(r) for r in x["actv"]), lb(x["sel"]), ln(x["ts"]), x["pst"],
            x["pl"], x["prr"], "true" if x["pbr1"] else "false", "true" if x["pslot"] else "false",
            lopt(x["winq"]), x["st"], x["cur"], ", ".join(lb(r) for r in x["npf"])))
    eb = ("{ e := %s, buf := tb1 %s, bnpf := tb1 %s, pb := %s, sq := tn2 [%s], bsq := tn1 %s, "
          "psq := %d, nr := tn1 %s }"
          % (e, lb(x["buf"]), lb(x["bnpf"]), "true" if x["pb"] else "false",
             ", ".join(ln(r) for r in x["sq"]), ln(x["bsq"]), x["psq"], ln(x["nr"])))
    a = ("{ X := { x := %s, pkill := %s }, armed := tb1 %s, armE := tn1 %s }"
         % (eb, "true" if A["X"]["pkill"] else "false", lb(A["armed"]), ln(A["armE"])))
    p = ("{ live := tb1 %s, dly := tn1 %s, ext := fun _ _ => %d, ret := fun _ _ => %s, "
         "fnpf := fun _ => %s }"
         % (lb(P["live"]), ln(P["dly"]), ext["xd"], "true" if ext["ret"] else "false",
            "true" if ext["fnpf"] else "false"))
    call = ("stepBTR (%s : Program) (fun _ => %s) (usbOf %s) (fun _ => %s) (fun _ => %s) "
            "(fun _ l => tn1 %s l) (tb1 %s) (tn1 %s) (%s : EngBA)"
            % (p, lopt(ext["win"]), "true" if x["usb_on"] else "false", lopt(ext["sreq"]),
               "true" if ext["is_arm"] else "false",
               ln(ext["edge"]), lb(ext["nw"]), ln(ext["k"]), a))
    on_next = "true" if (x["usb_on"] or ext["usb_rx"]) else "false"
    flag = "rb (%s || %s)" % ("true" if x["usb_on"] else "false",
                              "true" if ext["usb_rx"] else "false")
    return '#eval IO.println ("CASE %d " ++ renderA (%s) ++ "|" ++ %s)\n' % (i, call, flag)


HEADER = r'''import JLane
open JLane

def tb1 (xs : List Bool) : Lane → Bool := fun l => xs.getD l.val false
def tn1 (xs : List Nat) : Lane → Nat := fun l => xs.getD l.val 0
def tb2 (xs : List (List Bool)) : Lane → Slot → Bool :=
  fun l s => (xs.getD l.val []).getD (if s then 1 else 0) false
def tn2 (xs : List (List Nat)) : Lane → Slot → Nat :=
  fun l s => (xs.getD l.val []).getD (if s then 1 else 0) 0
def lanes : List Lane := [0, 1, 2, 3, 4]
def rb (b : Bool) : String := if b then "1" else "0"
def rPst : PState → String
  | .scan => "scan" | .req => "req" | .wait => "wait" | .cap => "cap"
def rSt : DState → String
  | .idle => "idle" | .drive => "drive" | .wb => "wb"
def rOpt : Option Lane → String
  | none => "-" | some l => toString l.val
def csv (xs : List String) : String := String.intercalate "," xs
def renderA (A : EngBA) : String :=
  let x := A.X.x
  let e := x.e
  String.intercalate "|" [
    toString e.now,
    csv (lanes.map fun l => rb (e.actv l false) ++ rb (e.actv l true)),
    csv (lanes.map fun l => rb (e.sel l)),
    csv (lanes.map fun l => toString (e.ts l)),
    rPst e.pst, toString e.pl.val, toString e.prr.val, rb e.pbr1, rb e.pslot,
    rOpt e.winq, rSt e.st, toString e.cur.val,
    csv (lanes.map fun l => rb (e.npf l false) ++ rb (e.npf l true)),
    csv (lanes.map fun l => rb (x.buf l)),
    csv (lanes.map fun l => rb (x.bnpf l)),
    rb x.pb,
    csv (lanes.map fun l => toString (x.sq l false) ++ ":" ++ toString (x.sq l true)),
    csv (lanes.map fun l => toString (x.bsq l)),
    toString x.psq,
    csv (lanes.map fun l => toString (x.nr l)),
    rb A.X.pkill,
    csv (lanes.map fun l => rb (A.armed l)),
    csv (lanes.map fun l => toString (A.armE l))]

'''


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 7
    outdir = tempfile.mkdtemp(prefix="diff_step_btr_")
    rng = random.Random(seed)
    cases = [rand_case(rng) for _ in range(n)]
    src = HEADER + "".join(lean_case(i, *c) for i, c in enumerate(cases))
    path = os.path.join(outdir, "DiffBTR.lean")
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
    for i, (A, P, ext) in enumerate(cases):
        py = render(S.step_btr(P, A, ext))
        if py != got[i]:
            bad += 1
            if bad <= 3:
                pf, lf = py.split("|"), got[i].split("|")
                fields = [j for j in range(min(len(pf), len(lf))) if pf[j] != lf[j]]
                print("MISMATCH case %d fields %s: py %s / lean %s"
                      % (i, fields, [pf[j] for j in fields], [lf[j] for j in fields]))
    print("differential step_btr vs Lean stepBTR: %d cases, %d mismatches" % (n, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
