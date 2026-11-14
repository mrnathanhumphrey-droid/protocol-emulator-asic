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

/-- §1 branch 1: the registered target (`winq`), still live, with an empty head. Shipped (TF3):
the target is the registered dispatch winner, `winner_q`. Batch 9c0df0c ((b′)): the registered
pick `pf_q` (`Program.pick`, `winqNext`), the `ft_flush` term being `FlushStep.liveFl`'s mask:
anchor `if (pf_v_q && l_live[pf_q] && !l_actv[hix[pf_q]] && !ft_flush[pf_q]) begin`. -/
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
* scan, branch 2: anchor `end else if (l_live[prr] && want_fetch(prr) && !ft_flush[prr]) begin`
  (batch 9c0df0c: `ft_flush` is `FlushStep.liveFl`'s mask, all-zero off a FALLTHROUGH flush).
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

/-- The capture writes the fetched word's no-prefetch flag with it (`l_cls` is written at the
capture with the word, l.1218–1222 `pre_cls`). -/
def npfNext (P : Program) (e : Engine) (l : Lane) (s : Slot) : Bool :=
  if e.pst = .cap ∧ l = e.pl ∧ s = e.pslot then P.fnpf e else e.npf l s

/-- The batch's pick, filtered by its candidate test (`pf_rdy`): live, released, head empty. -/
def pfPick (P : Program) (f : Engine → Option Lane) (e : Engine) : Option Lane :=
  match f e with
  | some w => if P.live w && decide (e.ts w ≤ e.now) && !e.headValid w then some w else none
  | none   => none

/-- The branch-1 target register's next value: the dispatch winner (shipped, anchor
`winner_q   <= winner;`) or the filtered pick (batch, anchor `pf_q       <= pf_w;`). -/
def winqNext (P : Program) (win : Engine → Option Lane) (e : Engine) : Option Lane :=
  match P.pick with
  | none   => win e
  | some f => pfPick P f e

/-- One clock cycle. `winq` registers the branch-1 target (`winqNext`).
`now` advances every cycle (primed, running). -/
def step (P : Program) (win : Engine → Option Lane) (e : Engine) : Engine :=
  let p := portNext P e
  let d := dispNext win e
  { now := e.now + 1
    actv := actvNext P e
    sel := selNext P e
    ts := tsNext P e
    pst := p.pst, pl := p.pl, prr := p.prr, pbr1 := p.pbr1, pslot := p.pslot
    winq := winqNext P win e
    st := d.st, cur := d.cur
    npf := npfNext P e }

/-- What the branch-1 target register can hold after a cycle: the dispatch winner (shipped rule),
or a live lane that was released with an empty head (the batch's pick). -/
theorem winq_step (P : Program) (win : Engine → Option Lane) (e : Engine) (w : Lane)
    (h : (step P win e).winq = some w) :
    (P.pick = none ∧ win e = some w) ∨
      (P.live w = true ∧ e.ts w ≤ e.now ∧ e.headValid w = false) := by
  change winqNext P win e = some w at h
  unfold winqNext at h
  cases hp : P.pick with
  | none =>
    rw [hp] at h
    exact Or.inl ⟨rfl, h⟩
  | some f =>
    have h' : pfPick P f e = some w := by
      rw [hp] at h
      exact h
    right
    unfold pfPick at h'
    cases hf : f e with
    | none => rw [hf] at h'; cases h'
    | some v =>
      have h2 : (if (P.live v && decide (e.ts v ≤ e.now) && !e.headValid v) = true then some v
          else none) = some w := by
        rw [hf] at h'
        exact h'
      by_cases hc : (P.live v && decide (e.ts v ≤ e.now) && !e.headValid v) = true
      · rw [if_pos hc] at h2
        cases h2
        simp only [Bool.and_eq_true, decide_eq_true_eq, Bool.not_eq_true'] at hc
        exact ⟨hc.1.1, hc.1.2, hc.2⟩
      · rw [if_neg hc] at h2
        cases h2

/-- Under the shipped rule (`pick = none`) the register is the dispatch winner. -/
theorem step_pick_none (P : Program) (win : Engine → Option Lane) (e : Engine)
    (h : P.pick = none) : step P win e = { step P win e with winq := win e } := by
  have hw : winqNext P win e = win e := by
    unfold winqNext
    rw [h]
  show step P win e = { step P win e with winq := win e }
  rw [← hw]
  rfl

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
