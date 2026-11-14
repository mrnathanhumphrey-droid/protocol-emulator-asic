import JLane.LemmaAN
import JLane.Armed
/-!
# Brick F3b — the FALLTHROUGH ARM (agent 1's batch, 11-14)

RTL, as built (agent 1, 11-14), on top of `Armed.lean`'s ARM:
* an ARM with `mod[1]` (`pe_isa.ARM_MOD_FT`, read at arming l.3814) is a **FALLTHROUGH** ARM; it
  always has a timeout (pe_isa refuses one without). Its writeback arms the lane and moves the
  timestamp to the **deadline** `D = ts + a_dly` (the one writeback rule), and it retires at its
  own writeback. A timed ARM *without* `mod[1]` halts the lane at its deadline (the error path,
  l.3367): outside the fragment, which therefore reads every timed ARM word as FALLTHROUGH
  (`ArmFragT`, `armT := 0 < dly`);
* an armed FALLTHROUGH lane is ready once `ts ≤ now` (`rel_q` with `armed & ~notmo`);
  the decision that picks it **only disarms**: nothing is dispatched that cycle, and the lane
  continues at PC+1 with the timestamp `D`;
* the edge on an armed lane wins until that decision, including its own cycle. On a FALLTHROUGH
  lane it takes PC+2: both slots are flushed, a refill in flight is killed (`FlushStep.stepF`),
  and the timestamp is rebased to the edge (`ts := now`), as for every ARM;
* a plain ARM (`a_dly = 0`) is `Armed.lean`'s.

`EngineT` is `Engine3` with the FALLTHROUGH flag and the port's kill register. The view `πT`
reads an armed FALLTHROUGH lane as released at `min(edge + 1, D)`: before the edge its release
is the deadline if the deadline comes first, else one past the edge. **`step3T_proj`**: one cycle
is one `stepF` cycle of the view, whose flushes are this cycle's FALLTHROUGH edges and whose
scheduler is the dispatched winner (`none` in a disarm cycle) — a disarm is a V4b cycle with no
decision, which `LemmaAN.lemmaA_n` counts.

Diffed against agent 1's RTL 9c0df0c (11-14): the edge's flush and kill (l.4452–4458), CAP's
`!pkill` filing (l.3302), the disarm that dispatches nothing (l.3364), the rebase `ts := now`
(`ck_rebase`, HALF + FALLTHROUGH refused) all as modelled. One difference, immaterial: the RTL
registers the disarmed lane as `winner_q` (l.2850) where this model registers none; under the
batch the port reads `pf_q`, never `winner_q`, for branch 1 (l.3264).
-/
namespace JLane

/-- The ARM registers with the FALLTHROUGH flag (`armT`) and the port's kill register. -/
structure EngineT where
  x     : Engine2
  armed : Lane → Bool
  armE  : Lane → Nat
  reb   : Lane → Bool
  armT  : Lane → Bool
  pkill : Bool

namespace EngineT

/-- `arm_hit`: the lane is armed and its edge is this cycle. -/
def hit (X : EngineT) (l : Lane) : Bool := X.armed l && decide (X.x.e.now = X.armE l)

/-- This cycle is an ARM's (retiring) writeback. -/
def armWB (X : EngineT) (P : Program2) : Bool :=
  decide (X.x.e.st = .wb) && decide ((X.x.head X.x.e.cur).op = .arm) && X.x.retire P

/-- This cycle's flushes: the FALLTHROUGH edges. -/
def fl (X : EngineT) (l : Lane) : Bool := X.hit l && X.armT l

/-- The dispatched winner: a decision for an armed lane only disarms it. -/
def wd (X : EngineT) (w : Option Lane) : Option Lane :=
  match w with
  | some v => if X.armed v = true then none else some v
  | none   => none

/-- The disarm decision on `l`: an idle cycle whose winner is `l`. -/
def disarm (X : EngineT) (w : Option Lane) (l : Lane) : Bool :=
  decide (X.x.e.st = .idle) && decide (w = some l)

end EngineT

/-- One cycle. The v2 step, with: the port masking this cycle's flushed lanes (agent 1's scan
fix), the slots of a flushed lane emptied and a killed capture filing nothing, the rebase at an
edge, arming (and the FALLTHROUGH flag) at an ARM's writeback, disarming at the edge or at a
disarm decision. -/
def step3T (P : Program2) (fw : Engine2 → Word) (edge : Nat → Lane → Nat) (w : Option Lane)
    (X : EngineT) : EngineT :=
  let p := portNextW (liveFl (P.toP (fun _ => 0)) X.fl) X.x.wantFetch X.x.e
  let d := dispNext (fun _ => X.wd w) X.x.e
  { x := { e := { now := X.x.e.now + 1
                  actv := fun l s => if X.fl l = true then false
                    else if X.x.e.pst = .cap ∧ l = X.x.e.pl ∧ s = X.x.e.pslot ∧ X.pkill = true
                    then X.x.e.actv l s
                    else X.x.actvNext P l s
                  sel := X.x.selNext P
                  ts := fun l => if X.hit l = true then X.x.e.now else X.x.tsNext P l
                  pst := p.pst, pl := p.pl, prr := p.prr, pbr1 := p.pbr1, pslot := p.pslot
                  winq := X.wd w
                  st := d.st, cur := d.cur
                  npf := npf2 fw X.x }
           word := X.x.wordNext fw
           ckph := X.x.ckphNext P
           ckbit := X.x.ckbitNext P }
    armed := fun l => if X.hit l = true then false
      else if (X.armWB P && decide (l = X.x.e.cur)) = true then true
      else if X.disarm w l = true then false else X.armed l
    armE := fun l => if (X.armWB P && decide (l = X.x.e.cur)) = true then edge X.x.e.now l
      else X.armE l
    reb := fun l => if X.hit l = true then true
      else if X.x.e.st = .wb ∧ l = X.x.e.cur then false else X.reb l
    armT := fun l => if (X.armWB P && decide (l = X.x.e.cur)) = true
      then decide (0 < (X.x.head X.x.e.cur).dly) else X.armT l
    pkill := if X.x.e.pst = .cap then false
      else X.pkill || (X.fl X.x.e.pl && (decide (X.x.e.pst = .req) || decide (X.x.e.pst = .wait))) }

/-- The V4b release: an armed FALLTHROUGH lane at `min(edge + 1, D)`, an armed plain lane one
past its edge, a rebased lane one past its timestamp, else the timestamp. -/
def relT (X : EngineT) (l : Lane) : Nat :=
  if X.armed l = true then
    (if X.armT l = true ∧ X.x.e.ts l ≤ X.armE l then X.x.e.ts l else X.armE l + 1)
  else if X.reb l = true then X.x.e.ts l + 1 else X.x.e.ts l

/-- The V4b view. -/
def πT (X : EngineT) : Engine := { X.x.e with ts := relT X }

/-- The view with the kill register. -/
def πF (X : EngineT) : EngineF := ⟨πT X, X.pkill⟩

/-! ### The fragment and its invariant -/

/-- A word in the FALLTHROUGH fragment: as `ArmFragW`, with an ARM of any delay (`0`: plain,
`> 0`: FALLTHROUGH with that timeout). -/
def ArmFragT (Wn : Nat) (w : Word) : Prop :=
  (w.op = .ord ∨ w.op = .loopRe ∨ w.op = .st ∨ w.op = .br ∨ w.op = .arm) ∧
    (w.op ≠ .arm → 1 ≤ w.dly) ∧ (w.op = .br → Wn ≤ w.dly)

/-- The invariant: `ArmInv`'s, plus an armed lane is not rebased. -/
def InvT (Wn : Nat) (X : EngineT) : Prop :=
  (∀ l s, ArmFragT Wn (X.x.word l s)) ∧
  (∀ l s, X.x.e.npf l s = decide ((X.x.word l s).op = .br)) ∧
  (∀ l, X.armed l = true → X.x.e.now ≤ X.armE l) ∧
  (∀ l, X.armed l = true → ¬(X.x.e.st ≠ .idle ∧ X.x.e.cur = l)) ∧
  (∀ l, X.reb l = true → X.x.e.ts l + 1 ≤ X.x.e.now) ∧
  (∀ l, X.armed l = true → X.reb l = false) ∧
  (X.x.e.st ≠ .idle → relT X X.x.e.cur ≤ X.x.e.now)

namespace Engine2

theorem isClk_T (Wn : Nat) (x : Engine2) (h : ∀ l s, ArmFragT Wn (x.word l s)) :
    x.isClk = false := by
  unfold isClk head
  rcases (h x.e.cur (x.e.sel x.e.cur)).1 with h1 | h1 | h1 | h1 | h1 <;> rw [h1]

theorem wbDly_T (P : Program2) (Wn : Nat) (x : Engine2) (h : ∀ l s, ArmFragT Wn (x.word l s)) :
    x.wbDly P = (x.head x.e.cur).dly := by
  unfold wbDly
  rw [if_neg (fun h' => by rw [isClk_T Wn x h] at h'; exact Bool.noConfusion h'.1)]

theorem wantFetch_T (Wn : Nat) (x : Engine2) (h : ∀ l s, ArmFragT Wn (x.word l s))
    (hn : ∀ l s, x.e.npf l s = decide ((x.word l s).op = .br)) (l : Lane) :
    x.wantFetch l = x.e.wantFetch l := by
  have hc : (x.word l (x.e.sel l)).op ≠ .chainRe := by
    rcases (h l (x.e.sel l)).1 with h1 | h1 | h1 | h1 | h1 <;> rw [h1] <;> decide
  unfold wantFetch Engine.wantFetch head
  rw [hn l (x.e.sel l)]
  cases hv : x.e.headValid l <;>
    by_cases hb : (x.word l (x.e.sel l)).op = .br <;> simp [hb, hc]

end Engine2

/-- The V4b extra delay at a writeback: at an ARM, the distance from the view's release to the
new one (`min(edge + 1, D)` for a FALLTHROUGH ARM, `edge + 1` for a plain one); otherwise the
word's delay, less the rebase's one cycle. -/
def ext3T (P : Program2) (edge : Nat → Lane → Nat) (X : EngineT) : Nat :=
  if X.armWB P = true then
    (if 0 < (X.x.head X.x.e.cur).dly ∧
        X.x.e.ts X.x.e.cur + (X.x.head X.x.e.cur).dly ≤ edge X.x.e.now X.x.e.cur
     then X.x.e.ts X.x.e.cur + (X.x.head X.x.e.cur).dly
     else edge X.x.e.now X.x.e.cur + 1) - relT X X.x.e.cur
  else (X.x.head X.x.e.cur).dly - (if X.reb X.x.e.cur = true then 1 else 0)

theorem hitT_false (X : EngineT) (l : Lane) (h : X.armed l = false) : X.hit l = false := by
  unfold EngineT.hit
  rw [h]
  rfl

theorem flT_false (X : EngineT) (l : Lane) (h : X.hit l = false) : X.fl l = false := by
  unfold EngineT.fl
  rw [h]
  rfl

theorem armWB_cur_false (P : Program2) (X : EngineT) (l : Lane)
    (hwb : ¬(X.x.e.st = .wb ∧ l = X.x.e.cur)) :
    (X.armWB P && decide (l = X.x.e.cur)) = false := by
  cases h' : (X.armWB P && decide (l = X.x.e.cur))
  · rfl
  · exfalso
    simp only [Bool.and_eq_true, decide_eq_true_eq] at h'
    unfold EngineT.armWB at h'
    simp only [Bool.and_eq_true, decide_eq_true_eq] at h'
    exact hwb ⟨h'.1.1.1, h'.2⟩

/-- A lane with no edge, no writeback and no disarm this cycle keeps its ARM registers, its
timestamp and its release. -/
theorem step3T_still (P : Program2) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
    (w : Option Lane) (X : EngineT) (l : Lane) (hh : X.hit l = false)
    (hwb : ¬(X.x.e.st = .wb ∧ l = X.x.e.cur))
    (hdis : X.disarm w l = false ∨ X.armed l = false) :
    (step3T P fw edge w X).armed l = X.armed l ∧ (step3T P fw edge w X).armE l = X.armE l ∧
    (step3T P fw edge w X).reb l = X.reb l ∧ (step3T P fw edge w X).armT l = X.armT l ∧
    (step3T P fw edge w X).x.e.ts l = X.x.e.ts l ∧
    relT (step3T P fw edge w X) l = relT X l := by
  have hnaw := armWB_cur_false P X l hwb
  have ha : (step3T P fw edge w X).armed l = X.armed l := by
    show (if X.hit l = true then false
      else if (X.armWB P && decide (l = X.x.e.cur)) = true then true
      else if X.disarm w l = true then false else X.armed l) = _
    rw [hh, hnaw]
    rcases hdis with hd | hd
    · rw [hd]
      rfl
    · rw [hd]
      simp
  have hE : (step3T P fw edge w X).armE l = X.armE l := by
    show (if (X.armWB P && decide (l = X.x.e.cur)) = true then edge X.x.e.now l
      else X.armE l) = _
    rw [hnaw]
    rfl
  have hr : (step3T P fw edge w X).reb l = X.reb l := by
    show (if X.hit l = true then true
      else if X.x.e.st = .wb ∧ l = X.x.e.cur then false else X.reb l) = _
    rw [hh, if_neg (by decide), if_neg hwb]
  have hT : (step3T P fw edge w X).armT l = X.armT l := by
    show (if (X.armWB P && decide (l = X.x.e.cur)) = true
      then decide (0 < (X.x.head X.x.e.cur).dly) else X.armT l) = _
    rw [hnaw]
    rfl
  have ht : (step3T P fw edge w X).x.e.ts l = X.x.e.ts l := by
    show (if X.hit l = true then X.x.e.now else X.x.tsNext P l) = _
    rw [hh, if_neg (by decide)]
    unfold Engine2.tsNext
    rw [if_neg hwb]
  refine ⟨ha, hE, hr, hT, ht, ?_⟩
  unfold relT
  rw [ha, hE, hr, hT, ht]

/-- **The release, one cycle.** On the fragment, the view's release after a cycle is `stepF`'s:
one past the edge on a flushed lane, else the V4b writeback rule with the extra `ext3T`. -/
theorem relT_step (P : Program2) (Q : Program) (Wn : Nat) (fw : Engine2 → Word)
    (edge : Nat → Lane → Nat) (hedge : ∀ t l, t + 1 ≤ edge t l)
    (w : Option Lane) (X : EngineT) (h : InvT Wn X)
    (hwv : ∀ v, X.x.e.st = .idle → w = some v →
      X.x.e.ts v ≤ X.x.e.now ∧ (X.armed v = true → X.armT v = true))
    (hd : Q.dly = fun _ => 0) (he : Q.ext X.x.e.now X.x.e.cur = ext3T P edge X) (l : Lane) :
    relT (step3T P fw edge w X) l = tsF Q X.fl (πT X) l := by
  obtain ⟨hw, -, harm, hnd, hreb, hrb, hdisp⟩ := h
  unfold tsF
  show _ = if X.fl l = true then X.x.e.now + 1
    else if X.x.e.st = .wb ∧ l = X.x.e.cur then relT X l + Q.dly l + Q.ext X.x.e.now l
    else relT X l
  have hd0 : Q.dly l = 0 := by rw [hd]
  rw [hd0]
  by_cases hh : X.hit l = true
  · -- the edge: the lane is armed, at its edge, not at a writeback
    have ha1 : X.armed l = true := by
      unfold EngineT.hit at hh
      simp only [Bool.and_eq_true] at hh
      exact hh.1
    have hE : X.x.e.now = X.armE l := by
      unfold EngineT.hit at hh
      simp only [Bool.and_eq_true, decide_eq_true_eq] at hh
      exact hh.2
    have hnw : ¬(X.x.e.st = .wb ∧ l = X.x.e.cur) := fun h' =>
      hnd l ha1 ⟨by rw [h'.1]; decide, h'.2.symm⟩
    have hL : relT (step3T P fw edge w X) l = X.x.e.now + 1 := by
      unfold relT
      show (if (if X.hit l = true then false
            else if (X.armWB P && decide (l = X.x.e.cur)) = true then true
            else if X.disarm w l = true then false else X.armed l) = true then _
          else if (if X.hit l = true then true
            else if X.x.e.st = .wb ∧ l = X.x.e.cur then false else X.reb l) = true
          then (if X.hit l = true then X.x.e.now else X.x.tsNext P l) + 1
          else (if X.hit l = true then X.x.e.now else X.x.tsNext P l)) = _
      rw [if_pos hh, if_pos hh, if_pos hh]
      rfl
    rw [hL]
    by_cases hf : X.fl l = true
    · rw [if_pos hf]
    · rw [if_neg hf, if_neg hnw]
      have hT : X.armT l = false := by
        cases hc : X.armT l
        · rfl
        · exact absurd (by unfold EngineT.fl; rw [hh, hc]; rfl) hf
      unfold relT
      rw [if_pos ha1, hT, ← hE]
      simp
  · have hh' : X.hit l = false := by
      cases hc : X.hit l
      · rfl
      · exact absurd hc hh
    rw [if_neg (by rw [flT_false X l hh']; decide)]
    by_cases hwb : X.x.e.st = .wb ∧ l = X.x.e.cur
    · -- this lane's writeback: it is not armed
      rw [if_pos hwb]
      have hna : X.armed l = false := by
        cases hc : X.armed l
        · rfl
        · exact absurd ⟨by rw [hwb.1]; decide, hwb.2.symm⟩ (hnd l hc)
      have hnd' : X.disarm w l = false := by
        unfold EngineT.disarm
        rw [hwb.1]
        rfl
      have htn : X.x.tsNext P l = X.x.e.ts l + (X.x.head X.x.e.cur).dly := by
        unfold Engine2.tsNext
        rw [if_pos hwb, Engine2.wbDly_T P Wn X.x hw]
      have hπ : relT X l = if X.reb l = true then X.x.e.ts l + 1 else X.x.e.ts l := by
        unfold relT
        rw [if_neg (by rw [hna]; decide)]
      have hdl : relT X l ≤ X.x.e.now := by
        have := hdisp (by rw [hwb.1]; decide)
        rw [← hwb.2] at this
        exact this
      have he' : Q.ext X.x.e.now l = ext3T P edge X := by rw [hwb.2]; exact he
      rw [he']
      have hed := hedge X.x.e.now l
      by_cases harw : X.armWB P = true
      · -- an ARM's writeback: armed, with the FALLTHROUGH flag if it has a delay
        have hc : (X.armWB P && decide (l = X.x.e.cur)) = true := by
          simp [harw, hwb.2]
        have hL : relT (step3T P fw edge w X) l =
            (if decide (0 < (X.x.head X.x.e.cur).dly) = true ∧
                X.x.e.ts l + (X.x.head X.x.e.cur).dly ≤ edge X.x.e.now l
             then X.x.e.ts l + (X.x.head X.x.e.cur).dly else edge X.x.e.now l + 1) := by
          unfold relT
          show (if (if X.hit l = true then false
                else if (X.armWB P && decide (l = X.x.e.cur)) = true then true
                else if X.disarm w l = true then false else X.armed l) = true then
              (if (if (X.armWB P && decide (l = X.x.e.cur)) = true
                  then decide (0 < (X.x.head X.x.e.cur).dly) else X.armT l) = true ∧
                (if X.hit l = true then X.x.e.now else X.x.tsNext P l) ≤
                  (if (X.armWB P && decide (l = X.x.e.cur)) = true then edge X.x.e.now l
                    else X.armE l)
               then (if X.hit l = true then X.x.e.now else X.x.tsNext P l)
               else (if (X.armWB P && decide (l = X.x.e.cur)) = true then edge X.x.e.now l
                    else X.armE l) + 1)
            else _) = _
          rw [hh', hc, htn]
          simp
        rw [hL]
        unfold ext3T
        rw [if_pos harw, ← hwb.2]
        rw [hπ] at hdl ⊢
        by_cases hc1 : 0 < (X.x.head l).dly ∧ X.x.e.ts l + (X.x.head l).dly ≤ edge X.x.e.now l
        · have hc2 : decide (0 < (X.x.head l).dly) = true ∧
              X.x.e.ts l + (X.x.head l).dly ≤ edge X.x.e.now l := ⟨by simp [hc1.1], hc1.2⟩
          rw [if_pos hc2, if_pos hc1]
          have := hc1.1
          cases hr' : X.reb l <;> simp only [hr', Bool.false_eq_true, ↓reduceIte] at hdl ⊢ <;>
            omega
        · have hc2 : ¬(decide (0 < (X.x.head l).dly) = true ∧
              X.x.e.ts l + (X.x.head l).dly ≤ edge X.x.e.now l) := fun h' =>
            hc1 ⟨by simpa using h'.1, h'.2⟩
          rw [if_neg hc2, if_neg hc1]
          cases hr' : X.reb l <;> simp only [hr', Bool.false_eq_true, ↓reduceIte] at hdl ⊢ <;>
            omega
      · -- any other writeback: the word's delay
        have hop : (X.x.head l).op ≠ .arm := by
          intro hop
          apply harw
          unfold EngineT.armWB
          rw [hwb.2] at hop
          simp [hwb.1, hop, Engine2.retire_arm P X.x hop]
        have hpos : 1 ≤ (X.x.head l).dly := (hw l (X.x.e.sel l)).2.1 hop
        have hc : (X.armWB P && decide (l = X.x.e.cur)) = false := by simp [harw]
        have hL : relT (step3T P fw edge w X) l = X.x.e.ts l + (X.x.head X.x.e.cur).dly := by
          unfold relT
          show (if (if X.hit l = true then false
                else if (X.armWB P && decide (l = X.x.e.cur)) = true then true
                else if X.disarm w l = true then false else X.armed l) = true then _
              else if (if X.hit l = true then true
                else if X.x.e.st = .wb ∧ l = X.x.e.cur then false else X.reb l) = true
              then (if X.hit l = true then X.x.e.now else X.x.tsNext P l) + 1
              else (if X.hit l = true then X.x.e.now else X.x.tsNext P l)) = _
          rw [hh', hc, hnd', hna, if_pos hwb, htn]
          rfl
        rw [hL]
        unfold ext3T
        rw [if_neg harw, hπ, ← hwb.2]
        cases hr' : X.reb l <;> simp <;> omega
    · rw [if_neg hwb]
      by_cases hdis : X.disarm w l = true ∧ X.armed l = true
      · -- the disarm decision: the deadline has passed, the release stays the deadline
        have hidle : X.x.e.st = .idle := by
          have := hdis.1
          unfold EngineT.disarm at this
          simp only [Bool.and_eq_true, decide_eq_true_eq] at this
          exact this.1
        have hwl : w = some l := by
          have := hdis.1
          unfold EngineT.disarm at this
          simp only [Bool.and_eq_true, decide_eq_true_eq] at this
          exact this.2
        obtain ⟨hts, hT⟩ := hwv l hidle hwl
        have hT' := hT hdis.2
        have hle := harm l hdis.2
        have hr0 := hrb l hdis.2
        have hnaw := armWB_cur_false P X l hwb
        have hL : relT (step3T P fw edge w X) l = X.x.e.ts l := by
          unfold relT
          show (if (if X.hit l = true then false
                else if (X.armWB P && decide (l = X.x.e.cur)) = true then true
                else if X.disarm w l = true then false else X.armed l) = true then _
              else if (if X.hit l = true then true
                else if X.x.e.st = .wb ∧ l = X.x.e.cur then false else X.reb l) = true
              then (if X.hit l = true then X.x.e.now else X.x.tsNext P l) + 1
              else (if X.hit l = true then X.x.e.now else X.x.tsNext P l)) = _
          rw [hh', hnaw, hdis.1, if_neg hwb, hr0]
          simp only [Bool.false_eq_true, ↓reduceIte]
          unfold Engine2.tsNext
          rw [if_neg hwb]
        rw [hL]
        unfold relT
        rw [if_pos hdis.2, hT']
        simp only [true_and]
        rw [if_pos (by omega)]
      · have hd' : X.disarm w l = false ∨ X.armed l = false := by
          cases h1 : X.disarm w l
          · exact Or.inl rfl
          · cases h2 : X.armed l
            · exact Or.inr rfl
            · exact absurd ⟨h1, h2⟩ hdis
        exact (step3T_still P fw edge w X l hh' hwb hd').2.2.2.2.2

/-- **Refinement, FALLTHROUGH.** On the fragment, one cycle of the engine with FALLTHROUGH ARMs
is one `stepF` cycle of its view: the flushes are this cycle's FALLTHROUGH edges, the scheduler
is the dispatched winner (none in a disarm cycle), and the program has the same liveness, no
minimum delay, the v2 retire flag, the extra `ext3T` and the branch decode. -/
theorem step3T_proj (P : Program2) (Q : Program) (Wn : Nat) (fw : Engine2 → Word)
    (edge : Nat → Lane → Nat) (hedge : ∀ t l, t + 1 ≤ edge t l)
    (w : Option Lane) (X : EngineT) (h : InvT Wn X)
    (hwv : ∀ v, X.x.e.st = .idle → w = some v →
      X.x.e.ts v ≤ X.x.e.now ∧ (X.armed v = true → X.armT v = true))
    (hl : Q.live = P.live) (hpk : Q.pick = none) (hd : Q.dly = fun _ => 0)
    (hr : Q.ret X.x.e.now X.x.e.cur = X.x.retire P)
    (he : Q.ext X.x.e.now X.x.e.cur = ext3T P edge X)
    (hq : Q.fnpf (πT X) = decide ((fw X.x).op = .br)) :
    πF (step3T P fw edge w X) = stepF Q (fun _ => X.wd w) X.fl (πF X) := by
  have hI := h
  obtain ⟨hw, hnp, -, -, -, -, -⟩ := h
  have hn : npf2 fw X.x = npfNext (liveFl Q X.fl) (πT X) := by
    funext l s
    show _ = (if X.x.e.pst = .cap ∧ l = X.x.e.pl ∧ s = X.x.e.pslot then Q.fnpf (πT X)
      else X.x.e.npf l s)
    unfold npf2
    split
    · exact hq.symm
    · rfl
  have hp : portNextW (liveFl (P.toP (fun _ => 0)) X.fl) X.x.wantFetch X.x.e =
      portNext (liveFl Q X.fl) (πT X) := by
    rw [portNextW_congr _ _ _ _ (Engine2.wantFetch_T Wn X.x hw hnp), ← portNextW_v1]
    refine portNextW_live _ _ ?_ _ _
    show (fun l => P.live l && !X.fl l) = (fun l => Q.live l && !X.fl l)
    rw [hl]
  have ha0 : X.x.actvNext P = actvNext (liveFl Q X.fl) (πT X) := by
    funext l s
    show X.x.actvNext P l s = actvNext (liveFl Q X.fl) X.x.e l s
    unfold Engine2.actvNext actvNext
    show _ = if X.x.e.st = .wb ∧ l = X.x.e.cur ∧ s = X.x.e.sel X.x.e.cur ∧
        Q.ret X.x.e.now X.x.e.cur = true then false else _
    rw [hr]
    by_cases h1 : X.x.e.st = .wb <;> by_cases h2 : X.x.retire P = true <;>
      by_cases h3 : l = X.x.e.cur <;> by_cases h4 : s = X.x.e.sel X.x.e.cur <;>
      simp [h1, h2, h3, h4]
  have ha : (fun l s => if X.fl l = true then false
      else if X.x.e.pst = .cap ∧ l = X.x.e.pl ∧ s = X.x.e.pslot ∧ X.pkill = true
      then X.x.e.actv l s else X.x.actvNext P l s) = actvF Q X.fl (πF X) := by
    funext l s
    rw [ha0]
    rfl
  have hs : X.x.selNext P = selNext (liveFl Q X.fl) (πT X) := by
    funext l
    show X.x.selNext P l = selNext (liveFl Q X.fl) X.x.e l
    unfold Engine2.selNext selNext
    show _ = if X.x.e.st = .wb ∧ l = X.x.e.cur ∧ Q.ret X.x.e.now X.x.e.cur = true
      then _ else _
    rw [hr]
    by_cases h1 : X.x.e.st = .wb <;> by_cases h2 : X.x.retire P = true <;>
      by_cases h3 : l = X.x.e.cur <;> simp [h1, h2, h3]
  have ht : relT (step3T P fw edge w X) = tsF Q X.fl (πT X) :=
    funext (relT_step P Q Wn fw edge hedge w X hI hwv hd he)
  show (⟨{ now := X.x.e.now + 1
           actv := fun l s => if X.fl l = true then false
             else if X.x.e.pst = .cap ∧ l = X.x.e.pl ∧ s = X.x.e.pslot ∧ X.pkill = true
             then X.x.e.actv l s else X.x.actvNext P l s
           sel := X.x.selNext P
           ts := relT (step3T P fw edge w X)
           pst := (portNextW (liveFl (P.toP (fun _ => 0)) X.fl) X.x.wantFetch X.x.e).pst
           pl := (portNextW (liveFl (P.toP (fun _ => 0)) X.fl) X.x.wantFetch X.x.e).pl
           prr := (portNextW (liveFl (P.toP (fun _ => 0)) X.fl) X.x.wantFetch X.x.e).prr
           pbr1 := (portNextW (liveFl (P.toP (fun _ => 0)) X.fl) X.x.wantFetch X.x.e).pbr1
           pslot := (portNextW (liveFl (P.toP (fun _ => 0)) X.fl) X.x.wantFetch X.x.e).pslot
           winq := X.wd w
           st := (dispNext (fun _ => X.wd w) X.x.e).st
           cur := (dispNext (fun _ => X.wd w) X.x.e).cur
           npf := npf2 fw X.x }, (step3T P fw edge w X).pkill⟩ : EngineF) =
    stepF Q (fun _ => X.wd w) X.fl (πF X)
  have hwq : winqNext Q (fun _ => X.wd w) (πF X).e = X.wd w := by
    unfold winqNext
    rw [hpk]
  unfold stepF
  rw [hp, ha, hs, ht, hn, hwq]
  rfl

/-- **The invariant is preserved** when every fetched word is in the fragment and a decision
names a lane whose timestamp has passed and which, if armed, is a FALLTHROUGH lane. -/
theorem invT_step (P : Program2) (Wn : Nat) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
    (hedge : ∀ t l, t + 1 ≤ edge t l) (w : Option Lane) (X : EngineT) (h : InvT Wn X)
    (hf : ∀ y, ArmFragT Wn (fw y))
    (hwv : ∀ v, X.x.e.st = .idle → w = some v →
      X.x.e.ts v ≤ X.x.e.now ∧ (X.armed v = true → X.armT v = true)) :
    InvT Wn (step3T P fw edge w X) := by
  obtain ⟨hw, hnp, harm, hnd, hreb, hrb, hdisp⟩ := h
  -- the `armed` and `reb` updates, spelled out
  have hA : ∀ l, (step3T P fw edge w X).armed l = (if X.hit l = true then false
      else if (X.armWB P && decide (l = X.x.e.cur)) = true then true
      else if X.disarm w l = true then false else X.armed l) := fun _ => rfl
  have hR : ∀ l, (step3T P fw edge w X).reb l = (if X.hit l = true then true
      else if X.x.e.st = .wb ∧ l = X.x.e.cur then false else X.reb l) := fun _ => rfl
  -- the dispatched winner is an unarmed lane
  have hwd : ∀ v, X.wd w = some v → w = some v ∧ X.armed v = false := by
    intro v hv
    unfold EngineT.wd at hv
    cases hw' : w with
    | none => rw [hw'] at hv; cases hv
    | some u =>
      rw [hw'] at hv
      by_cases hu : X.armed u = true
      · simp [hu] at hv
      · have hu' : X.armed u = false := by cases hc : X.armed u <;> simp_all
        simp [hu'] at hv
        subst hv
        exact ⟨rfl, hu'⟩
  refine ⟨fun l s => ?_, fun l s => ?_, fun l hl => ?_, fun l hl => ?_, fun l hl => ?_,
    fun l hl => ?_, fun hs => ?_⟩
  · show ArmFragT Wn (X.x.wordNext fw l s)
    unfold Engine2.wordNext
    split
    · exact hf X.x
    · exact hw l s
  · show npf2 fw X.x l s = decide ((X.x.wordNext fw l s).op = .br)
    unfold npf2 Engine2.wordNext
    by_cases hc : X.x.e.pst = .cap ∧ l = X.x.e.pl ∧ s = X.x.e.pslot
    · rw [if_pos hc, if_pos hc]
    · rw [if_neg hc, if_neg hc]
      exact hnp l s
  · -- armed: before the edge
    show X.x.e.now + 1 ≤ (if (X.armWB P && decide (l = X.x.e.cur)) = true then edge X.x.e.now l
      else X.armE l)
    rw [hA] at hl
    by_cases hh : X.hit l = true
    · rw [if_pos hh] at hl
      cases hl
    · rw [if_neg hh] at hl
      by_cases hc : (X.armWB P && decide (l = X.x.e.cur)) = true
      · rw [if_pos hc]
        exact hedge _ _
      · rw [if_neg hc] at hl
        rw [if_neg hc]
        by_cases hdl : X.disarm w l = true
        · rw [if_pos hdl] at hl
          cases hl
        · rw [if_neg hdl] at hl
          have h1 := harm l hl
          have h2 : X.x.e.now ≠ X.armE l := by
            intro h'
            apply hh
            unfold EngineT.hit
            rw [hl, h']
            simp
          omega
  · -- armed: not dispatched
    rintro ⟨hst, hcur⟩
    change (dispNext (fun _ => X.wd w) X.x.e).st ≠ .idle at hst
    change (dispNext (fun _ => X.wd w) X.x.e).cur = l at hcur
    rw [hA] at hl
    cases hs : X.x.e.st with
    | idle =>
      cases hwo : X.wd w with
      | none => simp [dispNext, hs, hwo] at hst
      | some v =>
        by_cases hv : X.x.e.headValid v = true
        · simp [dispNext, hs, hwo, hv] at hcur
          subst hcur
          obtain ⟨hwv', hav⟩ := hwd v hwo
          have hdv : X.disarm w v = true := by
            unfold EngineT.disarm
            simp [hs, hwv']
          rw [hitT_false X v hav] at hl
          have hnaw : (X.armWB P && decide (v = X.x.e.cur)) = false :=
            armWB_cur_false P X v (fun h' => by rw [hs] at h'; cases h'.1)
          rw [hnaw, hdv] at hl
          simp at hl
        · simp [dispNext, hs, hwo, hv] at hst
    | drive =>
      simp [dispNext, hs] at hcur
      have hna : X.armed l = false := by
        cases hc : X.armed l
        · rfl
        · exact absurd ⟨by rw [hs]; decide, hcur⟩ (hnd l hc)
      have hnaw : (X.armWB P && decide (l = X.x.e.cur)) = false :=
        armWB_cur_false P X l (fun h' => by rw [hs] at h'; cases h'.1)
      have hdl : X.disarm w l = false := by
        unfold EngineT.disarm
        rw [hs]
        rfl
      rw [hitT_false X l hna, hnaw, hdl, hna] at hl
      simp at hl
    | wb => simp [dispNext, hs] at hst
  · -- rebased: released
    show (if X.hit l = true then X.x.e.now else X.x.tsNext P l) + 1 ≤ X.x.e.now + 1
    rw [hR] at hl
    by_cases hh : X.hit l = true
    · rw [if_pos hh]
      exact Nat.le_refl _
    · rw [if_neg hh] at hl
      rw [if_neg hh]
      by_cases hwb : X.x.e.st = .wb ∧ l = X.x.e.cur
      · rw [if_pos hwb] at hl
        cases hl
      · rw [if_neg hwb] at hl
        unfold Engine2.tsNext
        rw [if_neg hwb]
        have := hreb l hl
        omega
  · -- armed: not rebased
    rw [hA] at hl
    rw [hR]
    by_cases hh : X.hit l = true
    · rw [if_pos hh] at hl
      cases hl
    · rw [if_neg hh] at hl
      rw [if_neg hh]
      by_cases hwb : X.x.e.st = .wb ∧ l = X.x.e.cur
      · rw [if_pos hwb]
      · rw [if_neg hwb]
        rw [armWB_cur_false P X l hwb] at hl
        by_cases hdl : X.disarm w l = true
        · rw [if_pos hdl] at hl
          cases hl
        · rw [if_neg hdl] at hl
          exact hrb l hl
  · -- a dispatched lane is released
    change (dispNext (fun _ => X.wd w) X.x.e).st ≠ .idle at hs
    show relT (step3T P fw edge w X) (dispNext (fun _ => X.wd w) X.x.e).cur ≤ X.x.e.now + 1
    cases hst : X.x.e.st with
    | idle =>
      cases hwo : X.wd w with
      | none => simp [dispNext, hst, hwo] at hs
      | some v =>
        by_cases hv : X.x.e.headValid v = true
        · have hc : (dispNext (fun _ => some v) X.x.e).cur = v := by simp [dispNext, hst, hv]
          rw [hc]
          obtain ⟨hwv', hav⟩ := hwd v hwo
          have hnwb : ¬(X.x.e.st = .wb ∧ v = X.x.e.cur) := fun h' => by
            rw [hst] at h'; cases h'.1
          obtain ⟨-, -, -, -, -, hπ⟩ :=
            step3T_still P fw edge w X v (hitT_false X v hav) hnwb (Or.inr hav)
          rw [hπ]
          have hts := (hwv v hst hwv').1
          unfold relT
          rw [hav]
          cases hr : X.reb v
          · simp only [Bool.false_eq_true, ↓reduceIte]
            omega
          · have := hreb v hr
            simp only [Bool.false_eq_true, ↓reduceIte]
            omega
        · simp [dispNext, hst, hwo, hv] at hs
    | drive =>
      have hc : (dispNext (fun _ => X.wd w) X.x.e).cur = X.x.e.cur := by simp [dispNext, hst]
      rw [hc]
      have hnwb : ¬(X.x.e.st = .wb ∧ X.x.e.cur = X.x.e.cur) := fun h' => by
        rw [hst] at h'; cases h'.1
      have hna : X.armed X.x.e.cur = false := by
        cases hc' : X.armed X.x.e.cur
        · rfl
        · exact absurd ⟨by rw [hst]; decide, rfl⟩ (hnd _ hc')
      obtain ⟨-, -, -, -, -, hπ⟩ :=
        step3T_still P fw edge w X X.x.e.cur (hitT_false X _ hna) hnwb (Or.inr hna)
      rw [hπ]
      have := hdisp (by rw [hst]; decide)
      omega
    | wb => simp [dispNext, hst] at hs

/-! ### The run -/

/-- `n` cycles under the scheduler `sched`. -/
def run3T (P : Program2) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
    (sched : EngineT → Option Lane) : Nat → EngineT → EngineT
  | 0, X => X
  | n + 1, X => run3T P fw edge sched n (step3T P fw edge (sched X) X)

theorem run3T_succ' (P : Program2) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
    (sched : EngineT → Option Lane) :
    ∀ (n : Nat) (X : EngineT), run3T P fw edge sched (n + 1) X =
      step3T P fw edge (sched (run3T P fw edge sched n X)) (run3T P fw edge sched n X)
  | 0, _ => rfl
  | n + 1, X => run3T_succ' P fw edge sched n (step3T P fw edge (sched X) X)

theorem now_run3T (P : Program2) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
    (sched : EngineT → Option Lane) :
    ∀ (n : Nat) (X : EngineT), (run3T P fw edge sched n X).x.e.now = X.x.e.now + n
  | 0, _ => rfl
  | n + 1, X => by
    rw [run3T_succ' P fw edge sched n X]
    show (run3T P fw edge sched n X).x.e.now + 1 = X.x.e.now + (n + 1)
    rw [now_run3T P fw edge sched n X]
    omega

/-- The scheduler's contract: a decision names a lane whose timestamp has passed and which, if
armed, is a FALLTHROUGH lane (`rel_q`). -/
def SchedT (sched : EngineT → Option Lane) : Prop :=
  ∀ X v, X.x.e.st = .idle → sched X = some v →
    X.x.e.ts v ≤ X.x.e.now ∧ (X.armed v = true → X.armT v = true)

theorem invT_run (P : Program2) (Wn : Nat) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
    (hedge : ∀ t l, t + 1 ≤ edge t l) (sched : EngineT → Option Lane)
    (hf : ∀ y, ArmFragT Wn (fw y)) (hsw : SchedT sched) :
    ∀ (n : Nat) (X : EngineT), InvT Wn X → InvT Wn (run3T P fw edge sched n X)
  | 0, _, h => h
  | n + 1, X, h => invT_run P Wn fw edge hedge sched hf hsw n _
      (invT_step P Wn fw edge hedge _ X h hf (fun v hi hv => hsw X v hi hv))

/-- The V4b program of a run from `X0`, read along the trajectory. -/
def armPT (P2 : Program2) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
    (sched : EngineT → Option Lane) (X0 : EngineT) : Program :=
  { live := P2.live
    dly := fun _ => 0
    ext := fun t _ => ext3T P2 edge (run3T P2 fw edge sched (t - X0.x.e.now) X0)
    ret := fun t _ => (run3T P2 fw edge sched (t - X0.x.e.now) X0).x.retire P2
    fnpf := fun e => decide ((fw (run3T P2 fw edge sched (e.now - X0.x.e.now) X0).x).op = .br) }

/-- The dispatched winners along the trajectory (none in a disarm cycle). -/
def winT (P2 : Program2) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
    (sched : EngineT → Option Lane) (X0 : EngineT) (e : Engine) : Option Lane :=
  (run3T P2 fw edge sched (e.now - X0.x.e.now) X0).wd
    (sched (run3T P2 fw edge sched (e.now - X0.x.e.now) X0))

/-- The flushes along the trajectory: the FALLTHROUGH edges of cycle `t`. -/
def flR (P2 : Program2) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
    (sched : EngineT → Option Lane) (X0 : EngineT) (t : Nat) : Lane → Bool :=
  (run3T P2 fw edge sched (t - X0.x.e.now) X0).fl

theorem stepF_win_congr (P : Program) (win : Engine → Option Lane) (fl : Lane → Bool)
    (X : EngineF) : stepF P win fl X = stepF P (fun _ => win X.e) fl X := rfl

/-- **Run refinement, FALLTHROUGH.** On the fragment, the view of a run with FALLTHROUGH ARMs is
a run with flushes (`FlushStep.runF`) of `armPT` under the dispatched winners, flushing at the
FALLTHROUGH edges. Between flushes it is a V4b run (`runF_seg`); a disarm is a cycle with no
decision (`lemmaA_n`). -/
theorem run3T_proj (P2 : Program2) (Wn : Nat) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
    (hedge : ∀ t l, t + 1 ≤ edge t l) (sched : EngineT → Option Lane) (X0 : EngineT)
    (hX0 : InvT Wn X0) (hf : ∀ y, ArmFragT Wn (fw y)) (hsw : SchedT sched) :
    ∀ n, πF (run3T P2 fw edge sched n X0) =
      runF (armPT P2 fw edge sched X0) (winT P2 fw edge sched X0) (flR P2 fw edge sched X0) n
        (πF X0)
  | 0 => rfl
  | n + 1 => by
    have hk : (run3T P2 fw edge sched n X0).x.e.now - X0.x.e.now = n := by
      rw [now_run3T]
      omega
    rw [run3T_succ', runF_succ', ← run3T_proj P2 Wn fw edge hedge sched X0 hX0 hf hsw n]
    rw [stepF_win_congr]
    have hw : winT P2 fw edge sched X0 (πF (run3T P2 fw edge sched n X0)).e =
        (run3T P2 fw edge sched n X0).wd (sched (run3T P2 fw edge sched n X0)) := by
      show (run3T P2 fw edge sched ((run3T P2 fw edge sched n X0).x.e.now - X0.x.e.now) X0).wd
        (sched (run3T P2 fw edge sched ((run3T P2 fw edge sched n X0).x.e.now - X0.x.e.now) X0))
        = _
      rw [hk]
    have hfl : flR P2 fw edge sched X0 (πF (run3T P2 fw edge sched n X0)).e.now =
        (run3T P2 fw edge sched n X0).fl := by
      show (run3T P2 fw edge sched ((run3T P2 fw edge sched n X0).x.e.now - X0.x.e.now) X0).fl
        = _
      rw [hk]
    rw [hw, hfl]
    have hI := invT_run P2 Wn fw edge hedge sched hf hsw n X0 hX0
    refine step3T_proj P2 (armPT P2 fw edge sched X0) Wn fw edge hedge _ _ hI
      (fun v hi hv => hsw _ v hi hv) rfl rfl rfl ?_ ?_ ?_
    · show (run3T P2 fw edge sched ((run3T P2 fw edge sched n X0).x.e.now - X0.x.e.now) X0).x.retire
        P2 = _
      rw [hk]
    · show ext3T P2 edge (run3T P2 fw edge sched
        ((run3T P2 fw edge sched n X0).x.e.now - X0.x.e.now) X0) = _
      rw [hk]
    · show decide ((fw (run3T P2 fw edge sched
        ((run3T P2 fw edge sched n X0).x.e.now - X0.x.e.now) X0).x).op = .br) = _
      rw [hk]

/-- **The FALLTHROUGH release.** After an ARM's writeback its lane is released at
`min(edge + 1, D)`, `D = ts + a_dly` the deadline (a plain ARM, `a_dly = 0`: one past the edge). -/
theorem arm_release_T (P : Program2) (Wn : Nat) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
    (w : Option Lane) (X : EngineT) (h : InvT Wn X) (harm : X.armWB P = true) :
    relT (step3T P fw edge w X) X.x.e.cur =
      (if 0 < (X.x.head X.x.e.cur).dly ∧
          X.x.e.ts X.x.e.cur + (X.x.head X.x.e.cur).dly ≤ edge X.x.e.now X.x.e.cur
       then X.x.e.ts X.x.e.cur + (X.x.head X.x.e.cur).dly
       else edge X.x.e.now X.x.e.cur + 1) := by
  have hst : X.x.e.st = .wb := by
    unfold EngineT.armWB at harm
    simp only [Bool.and_eq_true, decide_eq_true_eq] at harm
    exact harm.1.1
  have hna : X.armed X.x.e.cur = false := by
    cases hc : X.armed X.x.e.cur
    · rfl
    · exact absurd ⟨by rw [hst]; decide, rfl⟩ (h.2.2.2.1 _ hc)
  have hc : (X.armWB P && decide (X.x.e.cur = X.x.e.cur)) = true := by simp [harm]
  have htn : X.x.tsNext P X.x.e.cur = X.x.e.ts X.x.e.cur + (X.x.head X.x.e.cur).dly := by
    unfold Engine2.tsNext
    rw [if_pos ⟨hst, rfl⟩, Engine2.wbDly_T P Wn X.x h.1]
  unfold relT
  show (if (if X.hit X.x.e.cur = true then false
        else if (X.armWB P && decide (X.x.e.cur = X.x.e.cur)) = true then true
        else if X.disarm w X.x.e.cur = true then false else X.armed X.x.e.cur) = true then
      (if (if (X.armWB P && decide (X.x.e.cur = X.x.e.cur)) = true
          then decide (0 < (X.x.head X.x.e.cur).dly) else X.armT X.x.e.cur) = true ∧
        (if X.hit X.x.e.cur = true then X.x.e.now else X.x.tsNext P X.x.e.cur) ≤
          (if (X.armWB P && decide (X.x.e.cur = X.x.e.cur)) = true
            then edge X.x.e.now X.x.e.cur else X.armE X.x.e.cur)
       then (if X.hit X.x.e.cur = true then X.x.e.now else X.x.tsNext P X.x.e.cur)
       else (if (X.armWB P && decide (X.x.e.cur = X.x.e.cur)) = true
            then edge X.x.e.now X.x.e.cur else X.armE X.x.e.cur) + 1)
    else _) = _
  rw [hitT_false X _ hna, hc, htn]
  simp

/-- **A disarm is a cycle with no decision.** When the scheduler names an armed (FALLTHROUGH)
lane in an idle cycle, the view's cycle is one `LemmaAN.noDecB` counts. -/
theorem disarm_noDec (P2 : Program2) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
    (sched : EngineT → Option Lane) (X0 : EngineT) (n : Nat) (v : Lane)
    (hidle : (run3T P2 fw edge sched n X0).x.e.st = .idle)
    (hs : sched (run3T P2 fw edge sched n X0) = some v)
    (ha : (run3T P2 fw edge sched n X0).armed v = true) :
    noDecB (winT P2 fw edge sched X0) (πT (run3T P2 fw edge sched n X0)) = true := by
  have hk : (run3T P2 fw edge sched n X0).x.e.now - X0.x.e.now = n := by
    rw [now_run3T]
    omega
  have hw : winT P2 fw edge sched X0 (πT (run3T P2 fw edge sched n X0)) = none := by
    show (run3T P2 fw edge sched ((run3T P2 fw edge sched n X0).x.e.now - X0.x.e.now) X0).wd
      (sched (run3T P2 fw edge sched ((run3T P2 fw edge sched n X0).x.e.now - X0.x.e.now) X0))
      = none
    rw [hk, hs]
    simp [EngineT.wd, ha]
  unfold noDecB
  rw [hw]
  show (decide ((run3T P2 fw edge sched n X0).x.e.st = .idle) && true) = true
  simp [hidle]

#print axioms arm_release_T
#print axioms disarm_noDec
#print axioms relT_step
#print axioms step3T_proj
#print axioms invT_step
#print axioms run3T_proj

end JLane
