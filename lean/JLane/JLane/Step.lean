import JLane.State
/-!
# Brick 1 — one clock cycle
`step P win e` is the engine one cycle later. Every field update reads the *old*
state `e` (Verilog nonblocking semantics). Anchors are substrings of the current
`src/pe_engine.v`.

The EDF winner is abstract: `win : Engine → Option Lane`. Its contract (returns a
ready lane; min `edf_key_off`, ties to lowest index — the TF2 tree, proved equal to
the serial loop) enters later as a hypothesis, never as code.

Modelling choice: if a capture and a WB invalidation hit the same slot in one cycle,
the invalidation wins. A later lemma shows that collision is unreachable, so the
choice is immaterial.
-/
namespace JLane

/-- Round-robin successor: `(l == LANE_LAST) ? 0 : l + 1`. -/
def nextLane (l : Lane) : Lane := ⟨(l.val + 1) % K, Nat.mod_lt _ (by decide)⟩

/-- §1 branch 1, TF3: the registered winner, still live, with an empty head.
Anchor `if (winner_v_q && l_live[winner_q] && !l_actv[hix[winner_q]]) begin`. -/
def br1 (P : Program) (e : Engine) : Option Lane :=
  match e.winq with
  | some w => if P.live w && !e.headValid w then some w else none
  | none   => none

/-- Prefetch FSM registers. -/
structure Port where
  pst   : PState
  pl    : Lane
  prr   : Lane
  pbr1  : Bool
  pslot : Slot

/-- §1–§2: the prefetch FSM's next registers.
* scan, branch 1: serve the winner's head; `prr` untouched.
* scan, branch 2: anchor `end else if (l_live[prr] && want_fetch(prr)) begin`.
* scan, branch 3: anchor `prr <= (prr == LANE_LAST) ? {LW{1'b0}} : prr + 1'b1;`.
* req/wait: anchors `P_REQ:  pst <= P_WAIT;`, `P_WAIT: pst <= P_CAP;`.
* cap: anchor `if (!pbr1) prr <= (pl == LANE_LAST) ? {LW{1'b0}} : pl + 1'b1;`. -/
def portNext (P : Program) (e : Engine) : Port :=
  let keep : Port := ⟨e.pst, e.pl, e.prr, e.pbr1, e.pslot⟩
  match e.pst with
  | .scan =>
    match br1 P e with
    | some w => { keep with pst := .req, pl := w, pbr1 := true, pslot := e.sel w }
    | none =>
      if P.live e.prr && e.wantFetch e.prr then
        { keep with pst := .req, pl := e.prr, pbr1 := false, pslot := e.fetchSlot e.prr }
      else
        { keep with prr := nextLane e.prr }
  | .req  => { keep with pst := .wait }
  | .wait => { keep with pst := .cap }
  | .cap  => { keep with pst := .scan, prr := if e.pbr1 then e.prr else nextLane e.pl }

/-- Dispatch FSM registers. -/
structure Disp where
  st  : DState
  cur : Lane

/-- §3: decide in IDLE (head valid → DRIVE, else stall), DRIVE → WB, WB → IDLE.
Anchors `if (w_hv) begin`, `st <= ST_WB;`, `st <= ST_IDLE;`. -/
def dispNext (win : Engine → Option Lane) (e : Engine) : Disp :=
  match e.st with
  | .idle =>
    match win e with
    | some w => if e.headValid w then ⟨.drive, w⟩ else ⟨.idle, e.cur⟩
    | none   => ⟨.idle, e.cur⟩
  | .drive => ⟨.wb, e.cur⟩
  | .wb    => ⟨.idle, e.cur⟩

/-- §2 capture (`fix = pl * SPL ...`, slot latched at scan) and §4 WB invalidation of the
head, on a **retiring** writeback only (`act_retire`): a held clocked phase or a chaining
re-arm re-dispatches the same head (7A, 7C). -/
def actvNext (P : Program) (e : Engine) (l : Lane) (s : Slot) : Bool :=
  if e.st = .wb ∧ l = e.cur ∧ s = e.sel e.cur ∧ P.ret e.now e.cur = true then false
  else if e.pst = .cap ∧ l = e.pl ∧ s = e.pslot then true
  else e.actv l s

/-- §4: a retiring WB flips the select. -/
def selNext (P : Program) (e : Engine) (l : Lane) : Slot :=
  if e.st = .wb ∧ l = e.cur ∧ P.ret e.now e.cur = true then !e.sel l else e.sel l

/-- §3 / P8: absolute advance at WB, by the lane's minimum delay plus this writeback's extra.
Anchor `l_timestamp[cur] <= l_timestamp[cur] + {{(TS_W-DLY_W){1'b0}}, wb_dly};`. -/
def tsNext (P : Program) (e : Engine) (l : Lane) : Nat :=
  if e.st = .wb ∧ l = e.cur then e.ts l + P.dly l + P.ext e.now l else e.ts l

/-- One clock cycle. `winq` registers this cycle's winner (anchor `winner_q   <= winner;`).
`now` advances every cycle (primed, running). -/
def step (P : Program) (win : Engine → Option Lane) (e : Engine) : Engine :=
  let p := portNext P e
  let d := dispNext win e
  { now := e.now + 1
    actv := actvNext P e
    sel := selNext P e
    ts := tsNext P e
    pst := p.pst, pl := p.pl, prr := p.prr, pbr1 := p.pbr1, pslot := p.pslot
    winq := win e
    st := d.st, cur := d.cur }

/-! ### Sanity: each clause does what its anchor says -/

/-- A capture lands (absent the unreachable collision). -/
theorem step_cap_fills (P : Program) (win : Engine → Option Lane) (e : Engine)
    (hc : e.pst = .cap)
    (hn : ¬(e.st = .wb ∧ e.pl = e.cur ∧ e.pslot = e.sel e.cur ∧ P.ret e.now e.cur = true)) :
    (step P win e).actv e.pl e.pslot = true := by
  show actvNext P e e.pl e.pslot = true
  unfold actvNext
  rw [if_neg hn, if_pos ⟨hc, rfl, rfl⟩]

/-- TF3: a branch-1 capture does not move the round-robin pointer. -/
theorem step_prr_br1_cap (P : Program) (win : Engine → Option Lane) (e : Engine)
    (hc : e.pst = .cap) (hb : e.pbr1 = true) :
    (step P win e).prr = e.prr := by
  show (portNext P e).prr = e.prr
  simp [portNext, hc, hb]

/-- §4: a retiring WB flips the select of the dispatched lane. -/
theorem step_wb_flips (P : Program) (win : Engine → Option Lane) (e : Engine)
    (hw : e.st = .wb) (hr : P.ret e.now e.cur = true) :
    (step P win e).sel e.cur = !e.sel e.cur := by
  show selNext P e e.cur = !e.sel e.cur
  simp [selNext, hw, hr]

end JLane
