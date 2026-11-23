"""stepB, runnable: a Python copy of lean/JLane/JLane/BufEng.lean's buffered engine, one
function per Lean definition (agent 1's piece-5 replay, 11-22).

    x_next = step_b(P, x, ext)

`x` mirrors `EngB` with the `Engine` fields flattened into it:
    now actv sel ts pst pl prr pbr1 pslot winq st cur npf     (Engine, State.lean)
    buf bnpf pb sq bsq psq nr                                  (EngB; sq bsq psq nr are ghosts)
    usb_on                                                     (K13, Wilson 11-22; see below)
Per-lane fields are lists indexed by lane; `actv`, `npf`, `sq` are [lane][slot]. A slot is a
bool as in Lean (`Slot := Bool`) and indexes a list as int(slot). `pst` is one of
'scan' 'req' 'wait' 'cap'; `st` one of 'idle' 'drive' 'wb'; `winq` a lane or None.

`P` carries what Lean's `Program` fixes for the whole run:
    live : [bool] * K      dly : [int] * K      pick : bool (Program.pick = some f)
    usb  : lane or None    -- Lean's fixed `usb` parameter, read only when `x` has no usb_on

`ext` carries what Lean takes as functions, read per cycle from the trace:
    win   : the dispatch winner `win e` (lane or None)
    sreq  : the slot requester's pick `sreq x` (lane or None)
    ret   : P.ret now cur     -- this writeback retires (read only when st == 'wb')
    xd    : P.ext now cur     -- this writeback's extra delay (read only when st == 'wb')
    fnpf  : P.fnpf e          -- the captured word allows no prefetch (read only when pst == 'cap')
    pick  : f e               -- the (b') pick before pfPick's filter (read only when P.pick)
    usb_rx: lane 0's USB receive executes this cycle (K13: sets usb_on)

K13 is AHEAD OF LEAN: BufEng.stepB still takes `usb` as a fixed parameter. Here `usb` is
`USB_LANE` while `x['usb_on']` is set, else None, and `usb_on` is set by `ext['usb_rx']` and
never cleared (agent 1's RTL, M_SLOT_YIELD_UNGATED). With `usb_on` absent from `x`, `P['usb']`
is used and the step is exactly today's Lean `stepB`.

Every update reads the OLD state (Verilog nonblocking, Step.lean).
"""
import copy
import random
import sys

K = 5          # Params.lean `abbrev K : Nat := 5`
USB_LANE = 0   # K13: the slot yields to lane 0's branch 1


def _g(ext, key, default=None):
    return ext.get(key, default)


# ---------------------------------------------------------------- State.lean (Engine namespace)

def head_valid(e, l):
    """Engine.headValid"""
    return e["actv"][l][int(e["sel"][l])]


def spare_valid(e, l):
    """Engine.spareValid"""
    return e["actv"][l][int(not e["sel"][l])]


def want_fetch(e, l):
    """Engine.wantFetch"""
    return (not head_valid(e, l)) or ((not spare_valid(e, l)) and not e["npf"][l][int(e["sel"][l])])


def fetch_slot(e, l):
    """Engine.fetchSlot"""
    return (not e["sel"][l]) if head_valid(e, l) else e["sel"][l]


# ---------------------------------------------------------------- Step.lean

def next_lane(l):
    """nextLane"""
    return (l + 1) % K


def br1(P, e):
    """br1"""
    w = e["winq"]
    if w is not None and P["live"][w] and not head_valid(e, w):
        return w
    return None


def port_next(P, e):
    """portNext -> (pst, pl, prr, pbr1, pslot)"""
    keep = (e["pst"], e["pl"], e["prr"], e["pbr1"], e["pslot"])
    pst = e["pst"]
    if pst == "scan":
        w = br1(P, e)
        if w is not None:
            return ("req", w, e["prr"], True, e["sel"][w])
        r = e["prr"]
        if P["live"][r] and want_fetch(e, r):
            return ("req", r, e["prr"], False, fetch_slot(e, r))
        return (keep[0], keep[1], next_lane(r), keep[3], keep[4])
    if pst == "req":
        return ("wait",) + keep[1:]
    if pst == "wait":
        return ("cap",) + keep[1:]
    if pst == "cap":
        return ("scan", e["pl"], e["prr"] if e["pbr1"] else next_lane(e["pl"]), e["pbr1"], e["pslot"])
    raise ValueError(pst)


def disp_next(win, e):
    """dispNext -> (st, cur); `win` is the value of `win e`"""
    st = e["st"]
    if st == "idle":
        if win is not None and head_valid(e, win):
            return ("drive", win)
        return ("idle", e["cur"])
    if st == "drive":
        return ("wb", e["cur"])
    if st == "wb":
        return ("idle", e["cur"])
    raise ValueError(st)


def _is_ret_wb(e, l, ret):
    """e.st = .wb ∧ l = e.cur ∧ P.ret e.now e.cur = true"""
    return e["st"] == "wb" and l == e["cur"] and bool(ret)


def sel_next(e, l, ret):
    """selNext"""
    return (not e["sel"][l]) if _is_ret_wb(e, l, ret) else e["sel"][l]


def ts_next(P, e, l, xd):
    """tsNext"""
    if e["st"] == "wb" and l == e["cur"]:
        return e["ts"][l] + P["dly"][l] + xd
    return e["ts"][l]


def pf_pick(P, f_e, e):
    """pfPick; `f_e` is the value of `f e`"""
    w = f_e
    if w is not None and P["live"][w] and e["ts"][w] <= e["now"] and not head_valid(e, w):
        return w
    return None


def winq_next(P, win, f_e, e):
    """winqNext"""
    if not P.get("pick", False):
        return win
    return pf_pick(P, f_e, e)


# ---------------------------------------------------------------- Slot.lean

def usb_first(P, usb, e):
    """usbFirst"""
    w = br1(P, e)
    return w is not None and usb is not None and w == usb


# ---------------------------------------------------------------- BufEng.lean

def bnum(b):
    """bnum"""
    return 1 if b else 0


def nslots(e, l):
    """nslots"""
    return bnum(e["actv"][l][0]) + bnum(e["actv"][l][1])


def held(x, l):
    """EngB.held"""
    return nslots(x, l) + bnum(x["buf"][l])


def want_m(x, l):
    """EngB.wantM"""
    return want_fetch(x, l) and not x["buf"][l]


def port_next_m(P, x):
    """portNextM"""
    if x["pst"] == "scan":
        w = br1(P, x)
        if w is not None:
            return ("req", w, x["prr"], True, x["sel"][w])
        r = x["prr"]
        if P["live"][r] and want_m(x, r):
            return ("req", r, r, False, fetch_slot(x, r))
        return ("scan", x["pl"], next_lane(r), x["pbr1"], x["pslot"])
    return port_next(P, x)


def usb_of(P, x):
    """K13: Lean's `usb`, as state (lane 0 once usb_on), or the fixed parameter."""
    if "usb_on" in x:
        return USB_LANE if x["usb_on"] else None
    return P.get("usb")


def port_next_b(P, usb, sreq, x):
    """portNextB"""
    if x["pst"] == "scan":
        if usb_first(P, usb, x):
            return port_next_m(P, x)
        if sreq is not None:
            return ("req", sreq, x["prr"], True, fetch_slot(x, sreq))
        return port_next_m(P, x)
    return port_next(P, x)


def pb_next(P, usb, sreq, x):
    """pbNext"""
    if x["pst"] == "scan":
        if usb_first(P, usb, x):
            return False
        if sreq is not None:
            return spare_valid(x, sreq)
        return False
    return x["pb"]


def cap_slot(e, l):
    """capSlot (None = the buffer)"""
    if not head_valid(e, l):
        return e["sel"][l]
    if not spare_valid(e, l):
        return not e["sel"][l]
    return None


def cap_to(x, l, s):
    """capTo"""
    if not (x["pst"] == "cap" and l == x["pl"]):
        return False
    if x["pb"]:
        return cap_slot(x, l) == s
    return s == x["pslot"]


def cap_buf(x, l):
    """capBuf"""
    return x["pst"] == "cap" and l == x["pl"] and x["pb"] and cap_slot(x, l) is None


def load_to(x, l, s):
    """loadTo"""
    return x["buf"][l] and s == (not x["sel"][l]) and not x["actv"][l][int(s)]


def actv_b(x, l, s, ret):
    """actvB"""
    if x["st"] == "wb" and l == x["cur"] and s == x["sel"][x["cur"]] and ret:
        return False
    if cap_to(x, l, s) or load_to(x, l, s):
        return True
    return x["actv"][l][int(s)]


def npf_b(x, l, s, fnpf):
    """npfB"""
    if cap_to(x, l, s):
        return bool(fnpf)
    if load_to(x, l, s):
        return x["bnpf"][l]
    return x["npf"][l][int(s)]


def buf_b(x, l):
    """bufB"""
    if cap_buf(x, l):
        return True
    if x["buf"][l] and not spare_valid(x, l):
        return False
    return x["buf"][l]


def bnpf_b(x, l, fnpf):
    """bnpfB"""
    return bool(fnpf) if cap_buf(x, l) else x["bnpf"][l]


def sq_b(x, l, s):
    """sqB"""
    if cap_to(x, l, s):
        return x["psq"]
    if load_to(x, l, s):
        return x["bsq"][l]
    return x["sq"][l][int(s)]


def bsq_b(x, l):
    """bsqB"""
    return x["psq"] if cap_buf(x, l) else x["bsq"][l]


def psq_b(P, usb, sreq, x):
    """psqB"""
    if x["pst"] == "scan":
        p = port_next_b(P, usb, sreq, x)
        if p[0] == "req":
            return x["nr"][p[1]] + held(x, p[1])
    return x["psq"]


def nr_b(x, l, ret):
    """nrB"""
    return x["nr"][l] + 1 if _is_ret_wb(x, l, ret) else x["nr"][l]


def step_b(P, x, ext):
    """stepB: one cycle with the slot and the buffer."""
    win = _g(ext, "win")
    sreq = _g(ext, "sreq")
    ret = bool(_g(ext, "ret", True))      # Program.ret defaults to true
    xd = int(_g(ext, "xd", 0))            # Program.ext defaults to 0
    fnpf = bool(_g(ext, "fnpf", False))   # Program.fnpf defaults to false
    usb = usb_of(P, x)
    S = (False, True)
    pst, pl, prr, pbr1, pslot = port_next_b(P, usb, sreq, x)
    st, cur = disp_next(win, x)
    y = {
        "now": x["now"] + 1,
        "actv": [[actv_b(x, l, s, ret) for s in S] for l in range(K)],
        "sel": [sel_next(x, l, ret) for l in range(K)],
        "ts": [ts_next(P, x, l, xd) for l in range(K)],
        "pst": pst, "pl": pl, "prr": prr, "pbr1": pbr1, "pslot": pslot,
        "winq": winq_next(P, win, _g(ext, "pick"), x),
        "st": st, "cur": cur,
        "npf": [[npf_b(x, l, s, fnpf) for s in S] for l in range(K)],
        "buf": [buf_b(x, l) for l in range(K)],
        "bnpf": [bnpf_b(x, l, fnpf) for l in range(K)],
        "pb": pb_next(P, usb, sreq, x),
        "sq": [[sq_b(x, l, s) for s in S] for l in range(K)],
        "bsq": [bsq_b(x, l) for l in range(K)],
        "psq": psq_b(P, usb, sreq, x),
        "nr": [nr_b(x, l, ret) for l in range(K)],
    }
    if "usb_on" in x:   # K13, ahead of Lean: set by lane 0's first USB receive, never cleared
        y["usb_on"] = bool(x["usb_on"] or _g(ext, "usb_rx", False))
    return y


def run_b(P, x, exts):
    """runB over a list of per-cycle `ext`s."""
    for ext in exts:
        x = step_b(P, x, ext)
    return x


# ================================================================ the RTL-side armed run
# piece 5's reference (Wilson 11-22: one armed run for both FT paths), transcribing
# lean/JLane/JLane/{SwapRen,SwapRenK,ArmT,RtlRun}.lean definition by definition:
#   step_br   SwapRen.stepBR    -- no swap at a no-swap FT ARM writeback (ext['nw'], the RTL's
#                                  ft_k6), a buffered word loads HEAD-first, the buffer clears
#                                  exactly when it loads
#   step_bkkr SwapRenK.stepBKKR -- the K1-K5 keep-flush of the lanes in `fl`, kept index `k`, and
#                                  the kill (pkill)
#   step_btr  RtlRun.stepBTR    -- the armed registers; the flush set is the arming's end
#                                  (ArmT.ends = hit || tmo: the edge, or the timeout at the
#                                  pick -- deadline reached, dispatcher idle, the unmasked
#                                  scheduler naming the lane, no edge; the edge wins a tie;
#                                  ruling 1b, 11-22); a timeout's end keeps ts (the RTL
#                                  leaves it at the deadline; only an edge flush writes
#                                  now + 1 -- agent 1's replay 11-22, option (a))
# State A = {"X": {"x": <EngB dict>, "pkill": bool}, "armed": [bool]*K, "armE": [int]*K}.
# ext per cycle, beyond step_b's (win sreq ret xd fnpf pick usb_rx):
#   nw     [bool]*K  the no-swap decision on each lane this cycle (ft_k6)
#   k      [int]*K   the kept index on each lane (the edge word's at an edge, PC+1's at a timeout)
#   edge   [int]*K   the edge cycle an arming this cycle records (Lean `edge now l`)
#   is_arm bool      the head being written back is an ARM (Lean `isArm` on the base)

def load_to_r(x, l, s):
    """SwapRen.loadToR: into an empty head first, else the spare"""
    if not (x["buf"][l] and not x["actv"][l][int(s)]):
        return False
    return s == (not x["sel"][l]) if head_valid(x, l) else s == x["sel"][l]


def actv_r(x, l, s, ret):
    """SwapRen.actvR"""
    if x["st"] == "wb" and l == x["cur"] and s == x["sel"][x["cur"]] and ret:
        return False
    if cap_to(x, l, s) or load_to_r(x, l, s):
        return True
    return x["actv"][l][int(s)]


def npf_r(x, l, s, fnpf):
    """SwapRen.npfR"""
    if cap_to(x, l, s):
        return bool(fnpf)
    if load_to_r(x, l, s):
        return x["bnpf"][l]
    return x["npf"][l][int(s)]


def buf_r(x, l):
    """SwapRen.bufR: the buffer clears exactly when its word loads"""
    if cap_buf(x, l):
        return True
    if load_to_r(x, l, True) or load_to_r(x, l, False):
        return False
    return x["buf"][l]


def sq_r(x, l, s):
    """SwapRen.sqR"""
    if cap_to(x, l, s):
        return x["psq"]
    if load_to_r(x, l, s):
        return x["bsq"][l]
    return x["sq"][l][int(s)]


def sel_r(x, l, ret, nw):
    """SwapRen.selR: no flip on a no-swap writeback"""
    return x["sel"][l] if nw[l] else sel_next(x, l, ret)


def step_br(P, x, ext):
    """SwapRen.stepBR: the RTL's buffered step."""
    win = _g(ext, "win")
    sreq = _g(ext, "sreq")
    ret = bool(_g(ext, "ret", True))
    xd = int(_g(ext, "xd", 0))
    fnpf = bool(_g(ext, "fnpf", False))
    nw = _g(ext, "nw", [False] * K)
    usb = usb_of(P, x)
    S = (False, True)
    pst, pl, prr, pbr1, pslot = port_next_b(P, usb, sreq, x)
    st, cur = disp_next(win, x)
    y = {
        "now": x["now"] + 1,
        "actv": [[actv_r(x, l, s, ret) for s in S] for l in range(K)],
        "sel": [sel_r(x, l, ret, nw) for l in range(K)],
        "ts": [ts_next(P, x, l, xd) for l in range(K)],
        "pst": pst, "pl": pl, "prr": prr, "pbr1": pbr1, "pslot": pslot,
        "winq": winq_next(P, win, _g(ext, "pick"), x),
        "st": st, "cur": cur,
        "npf": [[npf_r(x, l, s, fnpf) for s in S] for l in range(K)],
        "buf": [buf_r(x, l) for l in range(K)],
        "bnpf": [bnpf_b(x, l, fnpf) for l in range(K)],
        "pb": pb_next(P, usb, sreq, x),
        "sq": [[sq_r(x, l, s) for s in S] for l in range(K)],
        "bsq": [bsq_b(x, l) for l in range(K)],
        "psq": psq_b(P, usb, sreq, x),
        "nr": [nr_b(x, l, ret) for l in range(K)],
    }
    if "usb_on" in x:
        y["usb_on"] = bool(x["usb_on"] or _g(ext, "usb_rx", False))
    return y


def base_k(X):
    """FlushKill.EngBK.base: while a kill is pending, the in-flight fetch is a second fetch"""
    if X["pkill"]:
        b = dict(X["x"])
        b["pb"] = True
        return b
    return X["x"]


def kc_k(X):
    """FlushKill.EngBK.kc: this cycle is a killed capture"""
    return X["x"]["pst"] == "cap" and X["pkill"]


def in_slot(x, l, k, s):
    """FlushKeep.EngB.inSlot"""
    return x["actv"][l][int(s)] and x["sq"][l][int(s)] == k


def in_buf(x, l, k):
    """FlushKeep.EngB.inBuf"""
    return x["buf"][l] and x["bsq"][l] == k


def in_cap(x, l, k):
    """FlushKeep.EngB.inCap"""
    return x["pst"] == "cap" and l == x["pl"] and x["psq"] == k


def has_edge(x, l, k):
    """FlushKeep.EngB.hasEdge"""
    return in_slot(x, l, k, True) or in_slot(x, l, k, False) or in_buf(x, l, k) or in_cap(x, l, k)


def keep_slot(x, l, k):
    """FlushKeep.keepSlot (K3): the slot holding it, else the current head slot"""
    if in_slot(x, l, k, True):
        return True
    if in_slot(x, l, k, False):
        return False
    return x["sel"][l]


def step_bkkr(P, X, ext, fl, k):
    """SwapRenK.stepBKKR: the RTL's flush step (keep-flush of `fl`, kept index `k`, the kill)."""
    b = base_k(X)
    y = step_br(P, b, ext)
    kc = kc_k(X)
    S = (False, True)
    x2 = dict(y)
    x2["actv"] = [[(has_edge(b, l, k[l]) and s == keep_slot(b, l, k[l])) if fl[l]
                   else (False if (kc and l == b["pl"] and cap_to(b, l, s)) else y["actv"][l][int(s)])
                   for s in S] for l in range(K)]
    x2["sel"] = [keep_slot(b, l, k[l]) if fl[l] else y["sel"][l] for l in range(K)]
    x2["ts"] = [b["now"] + 1 if fl[l] else y["ts"][l] for l in range(K)]
    x2["buf"] = [False if fl[l] else (False if (kc and l == b["pl"]) else y["buf"][l])
                 for l in range(K)]
    x2["sq"] = [[y["nr"][l] if (fl[l] and s == keep_slot(b, l, k[l])) else y["sq"][l][int(s)]
                 for s in S] for l in range(K)]
    xx = X["x"]
    if xx["pst"] == "cap":
        pk = False
    else:
        pk = bool(X["pkill"] or (fl[xx["pl"]] and xx["pst"] in ("req", "wait")))
    return {"x": x2, "pkill": pk}


def hit_a(A, l):
    """FlushHeld.EngBA.hit: armed and the edge is this cycle"""
    return A["armed"][l] and A["X"]["x"]["now"] == A["armE"][l]


def tmo_a(A, l, win):
    """ArmT.EngBA.tmo (ruling 1b: at the pick): armed, the deadline (release) reached, the
    dispatcher idle, the scheduler (unmasked, `win`) naming the lane, no edge this cycle"""
    x = A["X"]["x"]
    return (A["armed"][l] and x["ts"][l] <= x["now"] and x["st"] == "idle" and win == l
            and not hit_a(A, l))


def ends_a(A, l, win):
    """ArmT.EngBA.ends"""
    return hit_a(A, l) or tmo_a(A, l, win)


def arms_a(A, l, ret, is_arm):
    """FlushHeld.EngBA.arms: a retiring writeback of an ARM"""
    x = A["X"]["x"]
    return x["st"] == "wb" and l == x["cur"] and bool(ret) and bool(is_arm)


def win_a(win, armed):
    """FlushHeld.winA: the dispatcher never picks an armed lane"""
    return None if (win is not None and armed[win]) else win


def step_btr(P, A, ext):
    """RtlRun.stepBTR: one cycle of the RTL-side armed run, both FT paths."""
    ret = bool(_g(ext, "ret", True))
    is_arm = bool(_g(ext, "is_arm", False))
    edge = _g(ext, "edge", [0] * K)
    k = _g(ext, "k", [0] * K)
    fl = [ends_a(A, l, _g(ext, "win")) for l in range(K)]
    ar = [arms_a(A, l, ret, is_arm) for l in range(K)]
    ext2 = dict(ext)
    ext2["win"] = win_a(_g(ext, "win"), A["armed"])
    X2 = step_bkkr(P, A["X"], ext2, fl, k)
    tm = [tmo_a(A, l, _g(ext, "win")) for l in range(K)]
    if any(tm):                                   # ArmT.EngBK.keepTs
        ts0 = A["X"]["x"]["ts"]
        X2 = dict(X2)
        X2["x"] = dict(X2["x"])
        X2["x"]["ts"] = [ts0[l] if tm[l] else X2["x"]["ts"][l] for l in range(K)]
    armed = [False if fl[l] else (True if ar[l] else A["armed"][l]) for l in range(K)]
    armE = [edge[l] if ar[l] else A["armE"][l] for l in range(K)]
    return {"X": X2, "armed": armed, "armE": armE}


def self_test_rtl(seeds=10, cycles=5000):
    """With no no-swap writeback, the RTL's buffered step IS BufEng's on well-formed states (the
    head-first load meets the spare load: a buffered word sits behind a valid head, WfB.bh)."""
    for seed in range(seeds):
        rng = random.Random(1000 + seed)
        P = {"live": [rng.random() < 0.85 for _ in range(K)],
             "dly": [rng.randint(3, 40) for _ in range(K)], "pick": seed % 2 == 1}
        x = empty_state(usb_on=False)
        for _ in range(cycles):
            rel = [l for l in range(K) if P["live"][l] and x["ts"][l] <= x["now"]]
            win = rng.choice(rel) if rel and rng.random() < 0.8 else None
            cand = [l for l in range(K) if sreq_ok(P, x, l)]
            sreq = rng.choice(cand) if cand and rng.random() < 0.5 else None
            ext = {"win": win, "sreq": sreq, "ret": rng.random() < 0.9, "xd": rng.randint(0, 5),
                   "fnpf": rng.random() < 0.2,
                   "pick": rng.randrange(K) if rng.random() < 0.8 else None,
                   "usb_rx": rng.random() < 0.001, "nw": [False] * K}
            a, b = step_b(P, x, ext), step_br(P, x, ext)
            if a != b:
                print("FAIL rtl seed %d now %d: step_br differs from step_b on %s"
                      % (seed, x["now"], diff(a, b, ghosts=True)))
                return 1
            x = a
    print("step_br self-test: %d seeds x %d cycles: with no no-swap writeback step_br == step_b"
          % (seeds, cycles))
    return 0


GHOSTS = ("sq", "bsq", "psq", "nr")


def diff(a, b, ghosts=False):
    """The fields where two states differ (ghosts excluded unless asked): the replay's compare."""
    return sorted(k for k in a if (ghosts or k not in GHOSTS) and a.get(k) != b.get(k))


def empty_state(now=0, ts=None, usb_on=None):
    """All slots and buffers empty, port scanning, dispatch idle, ghosts 0."""
    x = {
        "now": now, "actv": [[False, False] for _ in range(K)], "sel": [False] * K,
        "ts": list(ts) if ts is not None else [now] * K,
        "pst": "scan", "pl": 0, "prr": 0, "pbr1": False, "pslot": False, "winq": None,
        "st": "idle", "cur": 0, "npf": [[False, False] for _ in range(K)],
        "buf": [False] * K, "bnpf": [False] * K, "pb": False,
        "sq": [[0, 0] for _ in range(K)], "bsq": [0] * K, "psq": 0, "nr": [0] * K,
    }
    if usb_on is not None:
        x["usb_on"] = usb_on
    return x


# ---------------------------------------------------------------- self-test
# The contracts Lean assumes are sampled at random (win: a live released lane or None;
# sreq: SReqB), and the theorems Lean proves under them are checked each cycle:
# WfB (wfB_run), OrdB (order_kept's invariant), and held_run's conservation.

def sreq_ok(P, x, w):
    """SReqB for one pick."""
    return (P["live"][w] and head_valid(x, w) and not x["buf"][w]
            and not x["npf"][w][int(x["sel"][w])]
            and (not spare_valid(x, w) or not x["npf"][w][int(not x["sel"][w])]))


def wf_b(x):
    """WfB: the failed fields (empty = holds)."""
    bad = []
    if x["st"] != "idle" and not head_valid(x, x["cur"]):
        bad.append("disp")
    if any(not head_valid(x, l) and spare_valid(x, l) for l in range(K)):
        bad.append("hf")
    fl = x["pst"] != "scan"
    if fl and not x["pb"] and x["actv"][x["pl"]][int(x["pslot"])]:
        bad.append("fe")
    if fl and x["buf"][x["pl"]]:
        bad.append("fnb")
    if any(x["buf"][l] and not head_valid(x, l) for l in range(K)):
        bad.append("bh")
    if fl and not x["pb"] and x["pslot"] != x["sel"][x["pl"]] and not head_valid(x, x["pl"]):
        bad.append("sf")
    return bad


def ord_b(x):
    """OrdB: the failed fields (empty = holds)."""
    bad = []
    for l in range(K):
        if head_valid(x, l) and x["sq"][l][int(x["sel"][l])] != x["nr"][l]:
            bad.append("o1@%d" % l)
        if spare_valid(x, l) and x["sq"][l][int(not x["sel"][l])] != x["nr"][l] + 1:
            bad.append("o2@%d" % l)
        if x["buf"][l] and x["bsq"][l] != x["nr"][l] + nslots(x, l):
            bad.append("o3@%d" % l)
    if x["pst"] != "scan" and x["psq"] != x["nr"][x["pl"]] + nslots(x, x["pl"]):
        bad.append("o4")
    return bad


def self_test(seeds=20, cycles=20000):
    worst = 0
    for seed in range(seeds):
        rng = random.Random(seed)
        P = {"live": [rng.random() < 0.85 for _ in range(K)],
             "dly": [rng.randint(3, 40) for _ in range(K)],
             "pick": seed % 2 == 1}
        x = empty_state(usb_on=False if seed % 3 else None)
        if "usb_on" not in x:
            P["usb"] = USB_LANE
        for _ in range(cycles):
            rel = [l for l in range(K) if P["live"][l] and x["ts"][l] <= x["now"]]
            win = rng.choice(rel) if rel and rng.random() < 0.8 else None
            cand = [l for l in range(K) if sreq_ok(P, x, l)]
            sreq = rng.choice(cand) if cand and rng.random() < 0.5 else None
            ext = {"win": win, "sreq": sreq, "ret": rng.random() < 0.9,
                   "xd": rng.randint(0, 5), "fnpf": rng.random() < 0.2,
                   "pick": rng.randrange(K) if rng.random() < 0.8 else None,
                   "usb_rx": rng.random() < 0.001}
            hit = [x["pst"] == "cap" and x["pl"] == l for l in range(K)]
            rt = [_is_ret_wb(x, l, ext["ret"]) for l in range(K)]
            y = step_b(P, x, ext)
            for l in range(K):       # held_step: held' + ret = held + hit
                if held(y, l) + bnum(rt[l]) != held(x, l) + bnum(hit[l]):
                    print("FAIL seed %d now %d: held conservation, lane %d" % (seed, x["now"], l))
                    return 1
            bad = wf_b(y) + ord_b(y)
            if bad:
                print("FAIL seed %d now %d: %s" % (seed, y["now"], ", ".join(bad)))
                return 1
            if "usb_on" in x and x["usb_on"] and not y["usb_on"]:
                print("FAIL seed %d: usb_on cleared" % seed)
                return 1
            worst = max(worst, max(held(y, l) for l in range(K)))
            x = y
    print("step_b self-test: %d seeds x %d cycles: WfB, OrdB, held conservation hold; "
          "max words held by a lane %d" % (seeds, cycles, worst))
    return 0


if __name__ == "__main__":
    sys.exit(self_test() or self_test_rtl())
