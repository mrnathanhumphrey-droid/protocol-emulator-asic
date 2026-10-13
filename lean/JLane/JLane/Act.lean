import JLane.Step
/-!
# Brick V0 — action words, and the v2 step
PORT_SPEC §7A–7D: each slot now carries an action word, and writeback reads the head
word of the dispatched lane. Three RTL facts the v1 model abstracted away:

* **retire** (`act_retire = ~ck_hold_eff & ((a_op != OP_REARM) | a_lvl)`): only a
  retiring WB invalidates the head and flips the select. A chaining re-arm (7A) and a
  held clocked phase (7C) retire nothing — Amendment A1, "at most one slot per action".
* **want_fetch** (7A): a lane whose valid head is a chaining re-arm owes nothing.
* **wb_dly** (7D, CE1): the WB adds the head word's delay, halved on the HIGH phase of a
  HALF_HIGH lane's clocked action.

What the port fetches is an arbitrary input `fw` (the word that lands at the capture),
so every theorem here holds for every program stream.

Scope of this brick: gates (W1 hold 7E, RX1 capture 7F, armed 7G) and the open-drain
park rebase (7D) come in later bricks; here `ready` is v1's.

Main result: `step2_proj` — on plain words (ordinary / looping re-arm with the lane's
delay), the v2 step projects exactly onto the v1 `step`.
-/
namespace JLane

/-- TR-2 `hkind` 0–4. `clk shiftin nbits`: a clocked SHIFT (`false`) or SHIFTIN (`true`)
with `ck_nbits = nbits` bits (SHIFT: `a_cnt + 1`, SHIFTIN: `a_cnt`). -/
inductive Op where
  | ord
  | loopRe
  | chainRe
  | clk (shiftin : Bool) (nbits : Nat)
  | arm
  deriving DecidableEq, Repr

/-- `l_ckph`: `CK_LOW`, `CK_HIGH`, `CK_COLL`. -/
inductive CkPh where
  | low | high | coll
  deriving DecidableEq, Repr

/-- The timing-relevant fields of an action word: opcode class and `a_dly`. -/
structure Word where
  op  : Op
  dly : Nat
  deriving DecidableEq, Repr

/-- A v2 program: liveness and the per-lane `HALF_HIGH` flag (`half_v`).
Delays live in the words. -/
structure Program2 where
  live : Lane → Bool
  half : Lane → Bool

/-- The v2 engine: v1 registers plus slot words and the clocked-phase registers. -/
structure Engine2 where
  e     : Engine
  word  : Lane → Slot → Word
  ckph  : Lane → CkPh
  ckbit : Lane → Nat

namespace Engine2

/-- The head word of lane `l`, `l_act[hix[l]]`. -/
def head (x : Engine2) (l : Lane) : Word := x.word l (x.e.sel l)

/-- §7A `want_fetch`, exactly: `!head_valid` → 1; head is a chaining re-arm → 0;
else `!spare_valid`. (`SPL = 2`.) -/
def wantFetch (x : Engine2) (l : Lane) : Bool :=
  if x.e.headValid l = false then true
  else if (x.head l).op = .chainRe then false
  else !x.e.spareValid l

/-- `ck_hold`: a clocked action that does not retire on this dispatch.
SHIFT retires on its HIGH once all bits are counted; SHIFTIN on its COLL. -/
def hold (x : Engine2) : Bool :=
  match (x.head x.e.cur).op with
  | .clk false n => !(decide (x.ckph x.e.cur = .high) && decide (x.ckbit x.e.cur = n))
  | .clk true _  => !decide (x.ckph x.e.cur = .coll)
  | _            => false

/-- `act_retire = ~ck_hold & ((a_op != OP_REARM) | a_lvl)`. -/
def retire (x : Engine2) : Bool :=
  !x.hold && (match (x.head x.e.cur).op with
              | .chainRe => false
              | _        => true)

/-- `ck_act`. -/
def isClk (x : Engine2) : Bool :=
  match (x.head x.e.cur).op with
  | .clk _ _ => true
  | _        => false

/-- `wb_dly = (ck_act & ck_is_high & half_v[cur]) ? (a_dly >> 1) : a_dly`. -/
def wbDly (P : Program2) (x : Engine2) : Nat :=
  if x.isClk = true ∧ x.ckph x.e.cur = .high ∧ P.half x.e.cur = true
  then (x.head x.e.cur).dly / 2
  else (x.head x.e.cur).dly

/-- `ck_norm`: SHIFT alternates LOW/HIGH; SHIFTIN goes LOW → HIGH → (all bits ? COLL : LOW). -/
def ckNext (x : Engine2) : CkPh :=
  match (x.head x.e.cur).op with
  | .clk false _ => if x.ckph x.e.cur = .low then .high else .low
  | .clk true n  =>
    if x.ckph x.e.cur = .low then .high
    else if x.ckph x.e.cur = .high then (if x.ckbit x.e.cur = n then .coll else .low)
    else .low
  | _ => x.ckph x.e.cur

end Engine2

/-- The prefetch FSM with the want-function as a parameter (v1: `Engine.wantFetch`). -/
def portNextW (P : Program) (want : Lane → Bool) (e : Engine) : Port :=
  let keep : Port := ⟨e.pst, e.pl, e.prr, e.pbr1, e.pslot⟩
  match e.pst with
  | .scan =>
    match br1 P e with
    | some w => { keep with pst := .req, pl := w, pbr1 := true, pslot := e.sel w }
    | none =>
      if P.live e.prr && want e.prr then
        { keep with pst := .req, pl := e.prr, pbr1 := false, pslot := e.fetchSlot e.prr }
      else
        { keep with prr := nextLane e.prr }
  | .req  => { keep with pst := .wait }
  | .wait => { keep with pst := .cap }
  | .cap  => { keep with pst := .scan, prr := if e.pbr1 then e.prr else nextLane e.pl }

theorem portNextW_v1 (P : Program) (e : Engine) :
    portNextW P e.wantFetch e = portNext P e := rfl

theorem portNextW_congr (P : Program) (e : Engine) (w1 w2 : Lane → Bool)
    (h : ∀ l, w1 l = w2 l) : portNextW P w1 e = portNextW P w2 e := by
  have : w1 = w2 := funext h
  rw [this]

/-- v1 view of a v2 program (`dly` is only read through words in v2). -/
def Program2.toP (P : Program2) (dly : Lane → Nat) : Program := { live := P.live, dly := dly }

namespace Engine2

/-- §4 + 7A/7C: only a retiring WB invalidates the head. -/
def actvNext (x : Engine2) (l : Lane) (s : Slot) : Bool :=
  if x.e.st = .wb ∧ x.retire = true ∧ l = x.e.cur ∧ s = x.e.sel x.e.cur then false
  else if x.e.pst = .cap ∧ l = x.e.pl ∧ s = x.e.pslot then true
  else x.e.actv l s

/-- Only a retiring WB flips the select. -/
def selNext (x : Engine2) (l : Lane) : Slot :=
  if x.e.st = .wb ∧ x.retire = true ∧ l = x.e.cur then !x.e.sel l else x.e.sel l

/-- Every WB advances the timestamp by `wb_dly` (§7, the one rule). -/
def tsNext (P : Program2) (x : Engine2) (l : Lane) : Nat :=
  if x.e.st = .wb ∧ l = x.e.cur then x.e.ts l + x.wbDly P else x.e.ts l

/-- The capture writes the fetched word into the latched slot. -/
def wordNext (fw : Engine2 → Word) (x : Engine2) (l : Lane) (s : Slot) : Word :=
  if x.e.pst = .cap ∧ l = x.e.pl ∧ s = x.e.pslot then fw x else x.word l s

/-- `if (act_retire) l_ckph <= CK_LOW; else if (ck_act) l_ckph <= ck_next;` at WB. -/
def ckphNext (x : Engine2) (l : Lane) : CkPh :=
  if x.e.st = .wb ∧ l = x.e.cur then
    (if x.retire = true then .low else if x.isClk = true then x.ckNext else x.ckph l)
  else x.ckph l

/-- `if (ck_act) { if (act_retire) l_ckbit <= 0; else if (ck_is_low) l_ckbit++ }` at WB. -/
def ckbitNext (x : Engine2) (l : Lane) : Nat :=
  if x.e.st = .wb ∧ l = x.e.cur ∧ x.isClk = true then
    (if x.retire = true then 0 else if x.ckph l = .low then x.ckbit l + 1 else x.ckbit l)
  else x.ckbit l

end Engine2

/-- One v2 clock cycle. `w` is this cycle's EDF winner (the v1 step reads its
scheduler only at the current state, see `step_win_congr`). -/
def step2 (P : Program2) (fw : Engine2 → Word) (w : Option Lane) (x : Engine2) : Engine2 :=
  let e := x.e
  let p := portNextW (P.toP (fun _ => 0)) x.wantFetch e
  let d := dispNext (fun _ => w) e
  { e := { now := e.now + 1
           actv := x.actvNext
           sel := x.selNext
           ts := x.tsNext P
           pst := p.pst, pl := p.pl, prr := p.prr, pbr1 := p.pbr1, pslot := p.pslot
           winq := w
           st := d.st, cur := d.cur }
    word := x.wordNext fw
    ckph := x.ckphNext
    ckbit := x.ckbitNext }

/-- The v1 step depends on its scheduler only through the value at the current state. -/
theorem step_win_congr (P : Program) (win : Engine → Option Lane) (e : Engine) :
    step P win e = step P (fun _ => win e) e := rfl

/-! ### Plain words: the v1 fragment -/

/-- A plain word on lane `l`: ordinary action or looping re-arm, with the lane's delay. -/
def PlainW (dly : Lane → Nat) (l : Lane) (w : Word) : Prop :=
  (w.op = .ord ∨ w.op = .loopRe) ∧ w.dly = dly l

/-- Every slot holds a plain word. -/
def Plain (dly : Lane → Nat) (x : Engine2) : Prop := ∀ l s, PlainW dly l (x.word l s)

namespace Engine2

theorem op_not_chain {dly : Lane → Nat} {l : Lane} {w : Word} (h : PlainW dly l w) :
    w.op ≠ .chainRe := by
  rcases h.1 with h1 | h1 <;> rw [h1] <;> decide

theorem hold_plain (dly : Lane → Nat) (x : Engine2) (h : Plain dly x) : x.hold = false := by
  unfold hold
  rcases (h x.e.cur (x.e.sel x.e.cur)).1 with h1 | h1 <;>
    · show (match (x.head x.e.cur).op with
            | .clk false n => !(decide (x.ckph x.e.cur = .high) && decide (x.ckbit x.e.cur = n))
            | .clk true _  => !decide (x.ckph x.e.cur = .coll)
            | _            => false) = false
      unfold head
      rw [h1]

theorem isClk_plain (dly : Lane → Nat) (x : Engine2) (h : Plain dly x) : x.isClk = false := by
  unfold isClk head
  rcases (h x.e.cur (x.e.sel x.e.cur)).1 with h1 | h1 <;> rw [h1]

theorem retire_plain (dly : Lane → Nat) (x : Engine2) (h : Plain dly x) : x.retire = true := by
  unfold retire
  rw [hold_plain dly x h]
  unfold head
  rcases (h x.e.cur (x.e.sel x.e.cur)).1 with h1 | h1 <;> rw [h1] <;> rfl

theorem wbDly_plain (P : Program2) (dly : Lane → Nat) (x : Engine2) (h : Plain dly x) :
    x.wbDly P = dly x.e.cur := by
  unfold wbDly
  rw [if_neg (fun h' => by rw [isClk_plain dly x h] at h'; exact Bool.noConfusion h'.1)]
  exact (h x.e.cur (x.e.sel x.e.cur)).2

theorem wantFetch_plain (dly : Lane → Nat) (x : Engine2) (h : Plain dly x) (l : Lane) :
    x.wantFetch l = x.e.wantFetch l := by
  unfold wantFetch Engine.wantFetch
  have hc : (x.head l).op ≠ .chainRe := op_not_chain (h l (x.e.sel l))
  cases hv : x.e.headValid l
  · simp
  · rw [if_neg (by simp), if_neg hc]
    simp

end Engine2

/-- The v2 engine with its v2-only registers dropped. -/
abbrev proj (x : Engine2) : Engine := x.e

/-- **Refinement.** On plain words, one v2 cycle is exactly one v1 cycle with the
lane delays `dly` and the same winner. -/
theorem step2_proj (P : Program2) (dly : Lane → Nat) (fw : Engine2 → Word)
    (w : Option Lane) (x : Engine2) (h : Plain dly x) :
    proj (step2 P fw w x) = step (P.toP dly) (fun _ => w) (proj x) := by
  have hr := Engine2.retire_plain dly x h
  have hp : portNextW (P.toP (fun _ => 0)) x.wantFetch x.e = portNext (P.toP dly) x.e := by
    rw [portNextW_congr _ _ _ _ (Engine2.wantFetch_plain dly x h)]
    rfl
  have ha : x.actvNext = actvNext x.e := by
    funext l s
    unfold Engine2.actvNext actvNext
    simp [hr]
  have hs : x.selNext = selNext x.e := by
    funext l
    unfold Engine2.selNext selNext
    simp [hr]
  have ht : x.tsNext P = tsNext (P.toP dly) x.e := by
    funext l
    unfold Engine2.tsNext tsNext
    by_cases hc : x.e.st = .wb ∧ l = x.e.cur
    · rw [if_pos hc, if_pos hc, Engine2.wbDly_plain P dly x h, hc.2]
      rfl
    · rw [if_neg hc, if_neg hc]
  show ({ now := x.e.now + 1, actv := x.actvNext, sel := x.selNext, ts := x.tsNext P,
          pst := (portNextW (P.toP (fun _ => 0)) x.wantFetch x.e).pst,
          pl := (portNextW (P.toP (fun _ => 0)) x.wantFetch x.e).pl,
          prr := (portNextW (P.toP (fun _ => 0)) x.wantFetch x.e).prr,
          pbr1 := (portNextW (P.toP (fun _ => 0)) x.wantFetch x.e).pbr1,
          pslot := (portNextW (P.toP (fun _ => 0)) x.wantFetch x.e).pslot,
          winq := w, st := (dispNext (fun _ => w) x.e).st,
          cur := (dispNext (fun _ => w) x.e).cur } : Engine) = step (P.toP dly) (fun _ => w) x.e
  rw [hp, ha, hs, ht]
  rfl

/-- Plainness is preserved when every fetched word is plain. -/
theorem plain_step (P : Program2) (dly : Lane → Nat) (fw : Engine2 → Word)
    (w : Option Lane) (x : Engine2) (h : Plain dly x)
    (hf : ∀ y, PlainW dly y.e.pl (fw y)) :
    Plain dly (step2 P fw w x) := by
  intro l s
  show PlainW dly l (x.wordNext fw l s)
  unfold Engine2.wordNext
  by_cases hc : x.e.pst = .cap ∧ l = x.e.pl ∧ s = x.e.pslot
  · rw [if_pos hc, hc.2.1]
    exact hf x
  · rw [if_neg hc]
    exact h l s

/-! ### Amendment A1 in the model -/

/-- A non-retiring WB (chaining re-arm, held clocked phase) leaves the dispatched lane's
slots and select untouched, apart from a capture: it owes no refill. -/
theorem noretire_keeps (x : Engine2) (hr : x.retire = false) (l : Lane) (s : Slot) :
    x.actvNext l s = (if x.e.pst = .cap ∧ l = x.e.pl ∧ s = x.e.pslot then true
                      else x.e.actv l s) ∧
    x.selNext l = x.e.sel l := by
  constructor
  · unfold Engine2.actvNext
    rw [if_neg (fun h' => by rw [hr] at h'; exact Bool.noConfusion h'.2.1)]
  · unfold Engine2.selNext
    rw [if_neg (fun h' => by rw [hr] at h'; exact Bool.noConfusion h'.2.1)]

/-- §7A: a parked chaining re-arm is never a fetch candidate. -/
theorem chain_no_fetch (x : Engine2) (l : Lane) (hv : x.e.headValid l = true)
    (hc : (x.head l).op = .chainRe) : x.wantFetch l = false := by
  unfold Engine2.wantFetch
  rw [if_neg (by rw [hv]; decide), if_pos hc]

/-- §7A: a chaining re-arm never retires. -/
theorem chain_no_retire (x : Engine2) (hc : (x.head x.e.cur).op = .chainRe) :
    x.retire = false := by
  unfold Engine2.retire Engine2.hold
  rw [hc]
  rfl

/-- §7C: a SHIFT holds on every phase except its last HIGH. -/
theorem shift_hold_low (x : Engine2) (n : Nat) (hc : (x.head x.e.cur).op = .clk false n)
    (hp : x.ckph x.e.cur = .low) : x.retire = false := by
  unfold Engine2.retire Engine2.hold
  rw [hc]
  simp [hp]

#print axioms step2_proj

end JLane
