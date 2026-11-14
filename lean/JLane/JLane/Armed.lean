import JLane.BrRefine
import JLane.GapRun
/-!
# Brick E — ARM: the armed lane and the edge rebase (branch brick, stage 4 step 2; PORT_SPEC 7G)

RTL (`pe_engine.v`), read 11-14:
* an ARM's writeback adds its delay, the **timeout** (`delay = 0`: none), arms the lane
  (`armed_n = 1`, l.3624–3630) and retires like any action (no `want_fetch` clause: the next
  word is prefetched while the ARM is the head);
* an armed lane with no timeout is not ready (`rel_q = … & ~(armed & notmo)`, l.4267);
* the edge (`arm_hit`, l.1501) disarms and **rebases** `l_timestamp := now` (l.4230–4240),
  so the timestamp can go down; it cannot fire in the ARM's own writeback cycle (l.4171).

`Engine3` adds the armed registers to the v2 engine. The edge is a free input
`edge t l` — the cycle of the edge that releases an ARM written back at `t` on lane `l`
(`≥ t + 1`) — so every edge pattern is covered, as `Program2.stl` covers every last bit.
Scope: ARMs with no timeout (all 20 ARMs of the usbdev device program); a timeout halts the
lane (l.3173), an error path, outside this brick.

`πE` reads an `Engine3` as a V4b engine: an armed lane is released at `edge + 1`, a lane
rebased since its last writeback at `ts + 1` — `rel_q` is registered, so the RTL lane is
ready the cycle after the edge. `step3_proj`: one cycle is one V4b cycle of a program whose
`ext` is the edge's distance at an ARM's writeback. With the per-retirement gaps of
`GapRun`, nothing needs a uniform minimum delay.
-/
namespace JLane

/-- The v2 engine with the ARM registers: `l_armed`, the edge cycle it waits for, and
"rebased since the last writeback". -/
structure Engine3 where
  x     : Engine2
  armed : Lane → Bool
  armE  : Lane → Nat
  reb   : Lane → Bool

namespace Engine3

/-- `arm_hit`: the lane is armed and its edge is this cycle. -/
def hit (X : Engine3) (l : Lane) : Bool := X.armed l && decide (X.x.e.now = X.armE l)

/-- This cycle is an ARM's (retiring) writeback. -/
def armWB (X : Engine3) (P : Program2) : Bool :=
  decide (X.x.e.st = .wb) && decide ((X.x.head X.x.e.cur).op = .arm) && X.x.retire P

end Engine3

/-- One cycle with the ARM registers: the v2 step, then the rebase (`ts_n` gives `arm_hit`
priority, l.2577), arming at an ARM's writeback, disarming at the edge. -/
def step3 (P : Program2) (fw : Engine2 → Word) (edge : Nat → Lane → Nat) (w : Option Lane)
    (X : Engine3) : Engine3 :=
  let x' := step2 P fw w X.x
  { x := { x' with e := { x'.e with ts := fun l => if X.hit l then X.x.e.now else x'.e.ts l } }
    armed := fun l => if X.hit l then false
      else if X.armWB P && decide (l = X.x.e.cur) then true else X.armed l
    armE := fun l => if X.armWB P && decide (l = X.x.e.cur) then edge X.x.e.now l else X.armE l
    reb := fun l => if X.hit l then true
      else if X.x.e.st = .wb ∧ l = X.x.e.cur then false else X.reb l }

/-- The V4b view: an armed lane's release is the cycle after its edge; a rebased lane's is
one past its (rebased) timestamp, until its next writeback. -/
def πE (X : Engine3) : Engine :=
  { X.x.e with ts := fun l => if X.armed l then X.armE l + 1
      else if X.reb l then X.x.e.ts l + 1 else X.x.e.ts l }

/-! ### The fragment and its invariant -/

/-- A word in the ARM fragment: ordinary, looping re-arm, self-timed, branch or ARM; an ARM
has no timeout; every other word has a positive delay; a branch waits at least `Wn`. -/
def ArmFragW (Wn : Nat) (w : Word) : Prop :=
  (w.op = .ord ∨ w.op = .loopRe ∨ w.op = .st ∨ w.op = .br ∨ w.op = .arm) ∧
    (w.op = .arm → w.dly = 0) ∧ (w.op ≠ .arm → 1 ≤ w.dly) ∧ (w.op = .br → Wn ≤ w.dly)

/-- The invariant: fragment words, the branch flag, an armed lane is before its edge and not
dispatched, a rebased lane's timestamp is past, a dispatched lane is released. -/
def ArmInv (Wn : Nat) (X : Engine3) : Prop :=
  (∀ l s, ArmFragW Wn (X.x.word l s)) ∧
  (∀ l s, X.x.e.npf l s = decide ((X.x.word l s).op = .br)) ∧
  (∀ l, X.armed l = true → X.x.e.now ≤ X.armE l) ∧
  (∀ l, X.armed l = true → ¬(X.x.e.st ≠ .idle ∧ X.x.e.cur = l)) ∧
  (∀ l, X.reb l = true → X.x.e.ts l + 1 ≤ X.x.e.now) ∧
  (X.x.e.st ≠ .idle → (πE X).ts X.x.e.cur ≤ X.x.e.now)

namespace Engine2

theorem op_not_chain_arm {Wn : Nat} {w : Word} (h : ArmFragW Wn w) : w.op ≠ .chainRe := by
  rcases h.1 with h1 | h1 | h1 | h1 | h1 <;> rw [h1] <;> decide

theorem isClk_arm (Wn : Nat) (x : Engine2) (h : ∀ l s, ArmFragW Wn (x.word l s)) :
    x.isClk = false := by
  unfold isClk head
  rcases (h x.e.cur (x.e.sel x.e.cur)).1 with h1 | h1 | h1 | h1 | h1 <;> rw [h1]

theorem wbDly_arm (P : Program2) (Wn : Nat) (x : Engine2) (h : ∀ l s, ArmFragW Wn (x.word l s)) :
    x.wbDly P = (x.head x.e.cur).dly := by
  unfold wbDly
  rw [if_neg (fun h' => by rw [isClk_arm Wn x h] at h'; exact Bool.noConfusion h'.1)]

theorem wantFetch_arm (Wn : Nat) (x : Engine2) (h : ∀ l s, ArmFragW Wn (x.word l s))
    (hn : ∀ l s, x.e.npf l s = decide ((x.word l s).op = .br)) (l : Lane) :
    x.wantFetch l = x.e.wantFetch l := by
  have hc : (x.word l (x.e.sel l)).op ≠ .chainRe := op_not_chain_arm (h l (x.e.sel l))
  unfold wantFetch Engine.wantFetch head
  rw [hn l (x.e.sel l)]
  cases hv : x.e.headValid l <;>
    by_cases hb : (x.word l (x.e.sel l)).op = .br <;> simp [hb, hc]

/-- An ARM is never held, so it always retires. -/
theorem retire_arm (P : Program2) (x : Engine2) (h : (x.head x.e.cur).op = .arm) :
    x.retire P = true := by
  unfold retire hold
  rw [h]
  rfl

end Engine2

/-! ### One cycle -/

/-- The V4b extra delay at a writeback of `X`'s dispatched lane: at an ARM, the distance to
one past its edge; otherwise the word's delay, less the rebase's one cycle. -/
def ext3 (P : Program2) (edge : Nat → Lane → Nat) (X : Engine3) : Nat :=
  if X.armWB P = true then edge X.x.e.now X.x.e.cur + 1 - (πE X).ts X.x.e.cur
  else (X.x.head X.x.e.cur).dly - (if X.reb X.x.e.cur then 1 else 0)

/-- **Refinement, ARM.** On the fragment, one cycle of the engine with ARM registers is one
V4b cycle of any program with the same liveness, no minimum delay, the v2 retire flag, the
extra `ext3` and the branch decode, read through `πE`. -/
theorem step3_proj (P : Program2) (Q : Program) (Wn : Nat) (fw : Engine2 → Word)
    (edge : Nat → Lane → Nat) (hedge : ∀ t l, t + 1 ≤ edge t l)
    (w : Option Lane) (X : Engine3) (h : ArmInv Wn X)
    (hl : Q.live = P.live) (hd : Q.dly = fun _ => 0)
    (hr : Q.ret X.x.e.now X.x.e.cur = X.x.retire P)
    (he : Q.ext X.x.e.now X.x.e.cur = ext3 P edge X)
    (hq : Q.fnpf (πE X) = decide ((fw X.x).op = .br)) :
    πE (step3 P fw edge w X) = step Q (fun _ => w) (πE X) := by
  obtain ⟨hw, hnp, harm, hnd, hreb, hdisp⟩ := h
  have hn : npf2 fw X.x = npfNext Q (πE X) := by
    funext l s
    show _ = (if X.x.e.pst = .cap ∧ l = X.x.e.pl ∧ s = X.x.e.pslot then Q.fnpf (πE X)
      else X.x.e.npf l s)
    unfold npf2
    split
    · exact hq.symm
    · rfl
  have hp : portNextW (P.toP (fun _ => 0)) X.x.wantFetch X.x.e = portNext Q (πE X) := by
    rw [portNextW_congr _ _ _ _ (Engine2.wantFetch_arm Wn X.x hw hnp), ← portNextW_v1]
    exact portNextW_live _ _ (by rw [hl]; rfl) _ _
  have ha : X.x.actvNext P = actvNext Q (πE X) := by
    funext l s
    show X.x.actvNext P l s = actvNext Q X.x.e l s
    unfold Engine2.actvNext actvNext
    rw [hr]
    by_cases h1 : X.x.e.st = .wb <;> by_cases h2 : X.x.retire P = true <;>
      by_cases h3 : l = X.x.e.cur <;> by_cases h4 : s = X.x.e.sel X.x.e.cur <;>
      simp [h1, h2, h3, h4]
  have hs : X.x.selNext P = selNext Q (πE X) := by
    funext l
    show X.x.selNext P l = selNext Q X.x.e l
    unfold Engine2.selNext selNext
    rw [hr]
    by_cases h1 : X.x.e.st = .wb <;> by_cases h2 : X.x.retire P = true <;>
      by_cases h3 : l = X.x.e.cur <;> simp [h1, h2, h3]
  -- the timestamps
  have ht : (πE (step3 P fw edge w X)).ts = tsNext Q (πE X) := by
    funext l
    show (if (if X.hit l then false
          else if X.armWB P && decide (l = X.x.e.cur) then true else X.armed l) = true
        then (if X.armWB P && decide (l = X.x.e.cur) then edge X.x.e.now l else X.armE l) + 1
        else if (if X.hit l then true
          else if X.x.e.st = .wb ∧ l = X.x.e.cur then false else X.reb l) = true
        then (if X.hit l then X.x.e.now else X.x.tsNext P l) + 1
        else (if X.hit l then X.x.e.now else X.x.tsNext P l)) = tsNext Q (πE X) l
    unfold tsNext
    show _ = if X.x.e.st = .wb ∧ l = X.x.e.cur then (πE X).ts l + Q.dly l + Q.ext X.x.e.now l
      else (πE X).ts l
    rw [hd]
    by_cases hh : X.hit l = true
    · -- the edge: armed, so not this cycle's writeback
      have ha1 : X.armed l = true := by
        unfold Engine3.hit at hh
        simp only [Bool.and_eq_true] at hh
        exact hh.1
      have hE : X.x.e.now = X.armE l := by
        unfold Engine3.hit at hh
        simp only [Bool.and_eq_true, decide_eq_true_eq] at hh
        exact hh.2
      have hnw : ¬(X.x.e.st = .wb ∧ l = X.x.e.cur) := fun h' =>
        hnd l ha1 ⟨by rw [h'.1]; decide, h'.2.symm⟩
      rw [if_pos hh, if_pos hh, if_pos hh, if_neg hnw]
      simp only [Bool.false_eq_true, ↓reduceIte]
      show X.x.e.now + 1 = (if X.armed l = true then X.armE l + 1
        else if X.reb l = true then X.x.e.ts l + 1 else X.x.e.ts l)
      rw [if_pos ha1, hE]
    · rw [if_neg hh, if_neg hh, if_neg hh]
      by_cases hwb : X.x.e.st = .wb ∧ l = X.x.e.cur
      · -- this lane's writeback: not armed
        have hna : X.armed l = false := by
          cases hc : X.armed l
          · rfl
          · exact absurd ⟨by rw [hwb.1]; decide, hwb.2.symm⟩ (hnd l hc)
        have htn : X.x.tsNext P l = X.x.e.ts l + X.x.wbDly P := by
          unfold Engine2.tsNext
          rw [if_pos hwb]
        have he' : Q.ext X.x.e.now l = ext3 P edge X := by rw [hwb.2]; exact he
        rw [if_pos hwb, if_pos hwb, htn, he']
        show _ = (πE X).ts l + 0 + ext3 P edge X
        have hπ : (πE X).ts l = if X.reb l = true then X.x.e.ts l + 1 else X.x.e.ts l := by
          show (if X.armed l = true then X.armE l + 1
            else if X.reb l = true then X.x.e.ts l + 1 else X.x.e.ts l) = _
          rw [if_neg (by rw [hna]; decide)]
        have hdl := hdisp (by rw [hwb.1]; decide)
        rw [← hwb.2] at hdl
        have hed := hedge X.x.e.now l
        unfold ext3
        rw [← hwb.2]
        by_cases harw : X.armWB P = true
        · simp [harw]
          omega
        · have hop : (X.x.head l).op ≠ .arm := by
            intro hop
            apply harw
            unfold Engine3.armWB
            rw [hwb.2] at hop
            simp [hwb.1, hop, Engine2.retire_arm P X.x hop]
          have hpos : 1 ≤ (X.x.head l).dly := (hw l (X.x.e.sel l)).2.2.1 hop
          have hwd : X.x.wbDly P = (X.x.head l).dly := by
            rw [Engine2.wbDly_arm P Wn X.x hw, ← hwb.2]
          simp [harw, hna, hwd, hπ]
          cases hr' : X.reb l <;> simp <;> omega
      · -- not this lane's writeback: nothing moves
        have hnaw : ¬((X.armWB P && decide (l = X.x.e.cur)) = true) := by
          intro h'
          simp only [Bool.and_eq_true, decide_eq_true_eq] at h'
          apply hwb
          unfold Engine3.armWB at h'
          simp only [Bool.and_eq_true, decide_eq_true_eq] at h'
          exact ⟨h'.1.1.1, h'.2⟩
        have htn : X.x.tsNext P l = X.x.e.ts l := by
          unfold Engine2.tsNext
          rw [if_neg hwb]
        rw [if_neg hnaw, if_neg hwb, if_neg hwb, htn, if_neg hnaw]
        rfl
  show ({ now := X.x.e.now + 1, actv := X.x.actvNext P, sel := X.x.selNext P,
          ts := (πE (step3 P fw edge w X)).ts,
          pst := (portNextW (P.toP (fun _ => 0)) X.x.wantFetch X.x.e).pst,
          pl := (portNextW (P.toP (fun _ => 0)) X.x.wantFetch X.x.e).pl,
          prr := (portNextW (P.toP (fun _ => 0)) X.x.wantFetch X.x.e).prr,
          pbr1 := (portNextW (P.toP (fun _ => 0)) X.x.wantFetch X.x.e).pbr1,
          pslot := (portNextW (P.toP (fun _ => 0)) X.x.wantFetch X.x.e).pslot,
          winq := w, st := (dispNext (fun _ => w) X.x.e).st,
          cur := (dispNext (fun _ => w) X.x.e).cur,
          npf := npf2 fw X.x } : Engine) = step Q (fun _ => w) (πE X)
  rw [hp, ha, hs, ht, hn]
  rfl

/-- A lane that neither sees its edge nor writes back this cycle keeps its ARM registers,
its timestamp, and so its V4b release. -/
theorem step3_still (P : Program2) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
    (w : Option Lane) (X : Engine3) (l : Lane) (hh : X.hit l = false)
    (hwb : ¬(X.x.e.st = .wb ∧ l = X.x.e.cur)) :
    (step3 P fw edge w X).armed l = X.armed l ∧ (step3 P fw edge w X).armE l = X.armE l ∧
    (step3 P fw edge w X).reb l = X.reb l ∧ (step3 P fw edge w X).x.e.ts l = X.x.e.ts l ∧
    (πE (step3 P fw edge w X)).ts l = (πE X).ts l := by
  have hnaw : (X.armWB P && decide (l = X.x.e.cur)) = false := by
    cases h' : (X.armWB P && decide (l = X.x.e.cur))
    · rfl
    · exfalso
      simp only [Bool.and_eq_true, decide_eq_true_eq] at h'
      unfold Engine3.armWB at h'
      simp only [Bool.and_eq_true, decide_eq_true_eq] at h'
      exact hwb ⟨h'.1.1.1, h'.2⟩
  have ha : (step3 P fw edge w X).armed l = X.armed l := by
    show (if X.hit l = true then false
      else if (X.armWB P && decide (l = X.x.e.cur)) = true then true else X.armed l) = _
    rw [hh, hnaw]
    rfl
  have hE : (step3 P fw edge w X).armE l = X.armE l := by
    show (if (X.armWB P && decide (l = X.x.e.cur)) = true then edge X.x.e.now l
      else X.armE l) = _
    rw [hnaw]
    rfl
  have hr : (step3 P fw edge w X).reb l = X.reb l := by
    show (if X.hit l = true then true
      else if X.x.e.st = .wb ∧ l = X.x.e.cur then false else X.reb l) = _
    rw [hh, if_neg (by decide), if_neg hwb]
  have ht : (step3 P fw edge w X).x.e.ts l = X.x.e.ts l := by
    show (if X.hit l = true then X.x.e.now else X.x.tsNext P l) = _
    rw [hh, if_neg (by decide)]
    unfold Engine2.tsNext
    rw [if_neg hwb]
  refine ⟨ha, hE, hr, ht, ?_⟩
  show (if (step3 P fw edge w X).armed l = true then (step3 P fw edge w X).armE l + 1
      else if (step3 P fw edge w X).reb l = true then (step3 P fw edge w X).x.e.ts l + 1
      else (step3 P fw edge w X).x.e.ts l) =
    (if X.armed l = true then X.armE l + 1
      else if X.reb l = true then X.x.e.ts l + 1 else X.x.e.ts l)
  rw [ha, hE, hr, ht]

/-- An armed lane is not dispatched and sees no writeback; it sees its edge only at `armE`. -/
theorem hit_false (X : Engine3) (l : Lane) (h : X.armed l = false) : X.hit l = false := by
  unfold Engine3.hit
  rw [h]
  rfl

/-- **The invariant is preserved** when every fetched word is in the fragment and the
scheduler picks a released, unarmed lane. -/
theorem arm_step (P : Program2) (Wn : Nat) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
    (hedge : ∀ t l, t + 1 ≤ edge t l) (w : Option Lane) (X : Engine3) (h : ArmInv Wn X)
    (hf : ∀ y, ArmFragW Wn (fw y))
    (hwv : ∀ v, w = some v → X.x.e.ts v ≤ X.x.e.now ∧ X.armed v = false) :
    ArmInv Wn (step3 P fw edge w X) := by
  obtain ⟨hw, hnp, harm, hnd, hreb, hdisp⟩ := h
  refine ⟨fun l s => ?_, fun l s => ?_, fun l hl => ?_, fun l hl => ?_, fun l hl => ?_, fun hs => ?_⟩
  · show ArmFragW Wn (X.x.wordNext fw l s)
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
    show X.x.e.now + 1 ≤ (step3 P fw edge w X).armE l
    by_cases hwb : X.x.e.st = .wb ∧ l = X.x.e.cur
    · have hl' : (if X.hit l = true then false
          else if (X.armWB P && decide (l = X.x.e.cur)) = true then true else X.armed l) = true :=
        hl
      have hna : X.armed l = false := by
        cases hc : X.armed l
        · rfl
        · exact absurd ⟨by rw [hwb.1]; decide, hwb.2.symm⟩ (hnd l hc)
      rw [hit_false X l hna] at hl'
      simp only [Bool.false_eq_true, ↓reduceIte] at hl'
      show X.x.e.now + 1 ≤ (if (X.armWB P && decide (l = X.x.e.cur)) = true then edge X.x.e.now l
        else X.armE l)
      by_cases hc : (X.armWB P && decide (l = X.x.e.cur)) = true
      · rw [if_pos hc]
        exact hedge _ _
      · rw [if_neg hc, hna] at hl'
        cases hl'
    · by_cases hh : X.hit l = true
      · have hl' : (if X.hit l = true then false
            else if (X.armWB P && decide (l = X.x.e.cur)) = true then true else X.armed l) = true :=
          hl
        rw [if_pos hh] at hl'
        cases hl'
      · have hh' : X.hit l = false := by
          cases hc : X.hit l
          · rfl
          · exact absurd hc hh
        obtain ⟨ha, hE, -, -, -⟩ := step3_still P fw edge w X l hh' hwb
        rw [ha] at hl
        rw [hE]
        have h1 := harm l hl
        have h2 : X.x.e.now ≠ X.armE l := by
          intro h'
          apply hh
          unfold Engine3.hit
          rw [hl, h']
          simp
        omega
  · -- armed: not dispatched
    rintro ⟨hst, hcur⟩
    change (dispNext (fun _ => w) X.x.e).st ≠ .idle at hst
    change (dispNext (fun _ => w) X.x.e).cur = l at hcur
    cases hs : X.x.e.st with
    | idle =>
      have hnwb : ¬(X.x.e.st = .wb ∧ l = X.x.e.cur) := fun h' => by rw [hs] at h'; cases h'.1
      cases hwo : w with
      | none => simp [dispNext, hs, hwo] at hst
      | some v =>
        by_cases hv : X.x.e.headValid v = true
        · simp [dispNext, hs, hwo, hv] at hcur
          subst hcur
          have hav := (hwv v hwo).2
          obtain ⟨ha, -⟩ := step3_still P fw edge w X v (hit_false X v hav) hnwb
          rw [ha, hav] at hl
          cases hl
        · simp [dispNext, hs, hwo, hv] at hst
    | drive =>
      simp [dispNext, hs] at hcur
      have hnwb : ¬(X.x.e.st = .wb ∧ l = X.x.e.cur) := fun h' => by rw [hs] at h'; cases h'.1
      have hna : X.armed l = false := by
        cases hc : X.armed l
        · rfl
        · exact absurd ⟨by rw [hs]; decide, hcur⟩ (hnd l hc)
      obtain ⟨ha, -⟩ := step3_still P fw edge w X l (hit_false X l hna) hnwb
      rw [ha, hna] at hl
      cases hl
    | wb => simp [dispNext, hs] at hst
  · -- rebased: released
    show (step3 P fw edge w X).x.e.ts l + 1 ≤ X.x.e.now + 1
    by_cases hh : X.hit l = true
    · show (if X.hit l = true then X.x.e.now else X.x.tsNext P l) + 1 ≤ X.x.e.now + 1
      rw [if_pos hh]
      exact Nat.le_refl _
    · have hh' : X.hit l = false := by
        cases hc : X.hit l
        · rfl
        · exact absurd hc hh
      by_cases hwb : X.x.e.st = .wb ∧ l = X.x.e.cur
      · have hl' : (if X.hit l = true then true
            else if X.x.e.st = .wb ∧ l = X.x.e.cur then false else X.reb l) = true := hl
        rw [hh', if_neg (by decide), if_pos hwb] at hl'
        cases hl'
      · obtain ⟨-, -, hr, ht, -⟩ := step3_still P fw edge w X l hh' hwb
        rw [hr] at hl
        rw [ht]
        have := hreb l hl
        omega
  · -- a dispatched lane is released
    change (dispNext (fun _ => w) X.x.e).st ≠ .idle at hs
    show (πE (step3 P fw edge w X)).ts (dispNext (fun _ => w) X.x.e).cur ≤ X.x.e.now + 1
    cases hst : X.x.e.st with
    | idle =>
      cases hwo : w with
      | none => simp [dispNext, hst, hwo] at hs
      | some v =>
        by_cases hv : X.x.e.headValid v = true
        · have hc : (dispNext (fun _ => some v) X.x.e).cur = v := by simp [dispNext, hst, hv]
          rw [hc]
          have hnwb : ¬(X.x.e.st = .wb ∧ v = X.x.e.cur) := fun h' => by rw [hst] at h'; cases h'.1
          obtain ⟨hts, hav⟩ := hwv v hwo
          obtain ⟨-, -, -, -, hπ⟩ := step3_still P fw edge (some v) X v (hit_false X v hav) hnwb
          rw [hπ]
          show (if X.armed v = true then X.armE v + 1
            else if X.reb v = true then X.x.e.ts v + 1 else X.x.e.ts v) ≤ X.x.e.now + 1
          rw [hav]
          cases hr : X.reb v
          · simp only [Bool.false_eq_true, ↓reduceIte]
            omega
          · have := hreb v hr
            simp only [Bool.false_eq_true, ↓reduceIte]
            omega
        · simp [dispNext, hst, hwo, hv] at hs
    | drive =>
      have hc : (dispNext (fun _ => w) X.x.e).cur = X.x.e.cur := by simp [dispNext, hst]
      rw [hc]
      have hnwb : ¬(X.x.e.st = .wb ∧ X.x.e.cur = X.x.e.cur) := fun h' => by
        rw [hst] at h'; cases h'.1
      have hna : X.armed X.x.e.cur = false := by
        cases hc' : X.armed X.x.e.cur
        · rfl
        · exact absurd ⟨by rw [hst]; decide, rfl⟩ (hnd _ hc')
      obtain ⟨-, -, -, -, hπ⟩ := step3_still P fw edge w X X.x.e.cur (hit_false X _ hna) hnwb
      rw [hπ]
      have := hdisp (by rw [hst]; decide)
      omega
    | wb => simp [dispNext, hst] at hs

/-! ### The run -/

/-- `n` cycles of the engine with ARM registers under the scheduler `sched`. -/
def run3 (P : Program2) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
    (sched : Engine3 → Option Lane) : Nat → Engine3 → Engine3
  | 0, X => X
  | n + 1, X => run3 P fw edge sched n (step3 P fw edge (sched X) X)

theorem run3_succ' (P : Program2) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
    (sched : Engine3 → Option Lane) :
    ∀ (n : Nat) (X : Engine3), run3 P fw edge sched (n + 1) X =
      step3 P fw edge (sched (run3 P fw edge sched n X)) (run3 P fw edge sched n X)
  | 0, _ => rfl
  | n + 1, X => run3_succ' P fw edge sched n (step3 P fw edge (sched X) X)

theorem now_run3 (P : Program2) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
    (sched : Engine3 → Option Lane) :
    ∀ (n : Nat) (X : Engine3), (run3 P fw edge sched n X).x.e.now = X.x.e.now + n
  | 0, _ => rfl
  | n + 1, X => by
    rw [run3_succ' P fw edge sched n X]
    show (run3 P fw edge sched n X).x.e.now + 1 = X.x.e.now + (n + 1)
    rw [now_run3 P fw edge sched n X]
    omega

/-- The RTL's readiness for a lane is the V4b view's: released and not armed. -/
theorem ready_iff (Wn : Nat) (X : Engine3) (h : ArmInv Wn X) (v : Lane) :
    (X.x.e.ts v ≤ X.x.e.now ∧ X.armed v = false) ↔ (πE X).ts v ≤ X.x.e.now := by
  obtain ⟨-, -, harm, -, hreb, -⟩ := h
  show _ ↔ (if X.armed v = true then X.armE v + 1
    else if X.reb v = true then X.x.e.ts v + 1 else X.x.e.ts v) ≤ X.x.e.now
  constructor
  · rintro ⟨hts, hav⟩
    rw [hav]
    cases hr : X.reb v
    · simp only [Bool.false_eq_true, ↓reduceIte]
      exact hts
    · have := hreb v hr
      simp only [Bool.false_eq_true, ↓reduceIte]
      exact this
  · intro hle
    cases hav : X.armed v
    · rw [hav] at hle
      simp only [Bool.false_eq_true, ↓reduceIte] at hle
      refine ⟨?_, rfl⟩
      cases hr : X.reb v <;> rw [hr] at hle <;> simp only [Bool.false_eq_true, ↓reduceIte] at hle <;>
        omega
    · rw [hav] at hle
      simp only [↓reduceIte] at hle
      have := harm v hav
      omega

theorem arm_run3 (P : Program2) (Wn : Nat) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
    (hedge : ∀ t l, t + 1 ≤ edge t l) (sched : Engine3 → Option Lane)
    (hf : ∀ y, ArmFragW Wn (fw y))
    (hsw : ∀ X v, sched X = some v → P.live v = true ∧ X.x.e.ts v ≤ X.x.e.now ∧ X.armed v = false) :
    ∀ (n : Nat) (X : Engine3), ArmInv Wn X → ArmInv Wn (run3 P fw edge sched n X)
  | 0, _, h => h
  | n + 1, X, h => arm_run3 P Wn fw edge hedge sched hf hsw n _
      (arm_step P Wn fw edge hedge _ X h hf (fun v hv => (hsw X v hv).2))

/-- The V4b program of a run with ARMs from `X0`: no minimum delay, the v2 retire flag, the
extra `ext3` and the branch decode, read along the trajectory. -/
def armP (P2 : Program2) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
    (sched : Engine3 → Option Lane) (X0 : Engine3) : Program :=
  { live := P2.live
    dly := fun _ => 0
    ext := fun t _ => ext3 P2 edge (run3 P2 fw edge sched (t - X0.x.e.now) X0)
    ret := fun t _ => (run3 P2 fw edge sched (t - X0.x.e.now) X0).x.retire P2
    fnpf := fun e => decide ((fw (run3 P2 fw edge sched (e.now - X0.x.e.now) X0).x).op = .br) }

/-- The V4b scheduler induced by `sched` along the trajectory from `X0`. -/
def win3 (Q : Program) (P2 : Program2) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
    (sched : Engine3 → Option Lane) (X0 : Engine3) (e : Engine) : Option Lane :=
  match sched (run3 P2 fw edge sched (e.now - X0.x.e.now) X0) with
  | some w => if Q.live w && decide (e.ts w ≤ e.now) then some w else firstReady Q e
  | none   => firstReady Q e

theorem win3_ready (Q : Program) (P2 : Program2) (fw : Engine2 → Word)
    (edge : Nat → Lane → Nat) (sched : Engine3 → Option Lane) (X0 : Engine3) :
    ∀ e w, win3 Q P2 fw edge sched X0 e = some w → Q.live w = true ∧ e.ts w ≤ e.now := by
  intro e w h
  unfold win3 at h
  split at h
  · split at h
    · rename_i hc
      cases h
      simp only [Bool.and_eq_true, decide_eq_true_eq] at hc
      exact hc
    · exact firstReady_some Q e w h
  · exact firstReady_some Q e w h

theorem win3_wc (Q : Program) (P2 : Program2) (fw : Engine2 → Word)
    (edge : Nat → Lane → Nat) (sched : Engine3 → Option Lane) (X0 : Engine3) :
    ∀ y e, Ready Q y e → win3 Q P2 fw edge sched X0 e ≠ none := by
  intro y e hy h
  unfold win3 at h
  split at h
  · split at h
    · cases h
    · exact firstReady_none Q e h y hy
  · exact firstReady_none Q e h y hy

/-- Along the trajectory, `win3` is `sched`, given the RTL scheduler's contract: it picks a
live, released, unarmed lane, and some lane whenever one is. -/
theorem win3_on (P2 : Program2) (Wn : Nat) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
    (hedge : ∀ t l, t + 1 ≤ edge t l) (sched : Engine3 → Option Lane) (X0 : Engine3)
    (hX0 : ArmInv Wn X0) (hf : ∀ y, ArmFragW Wn (fw y))
    (hsw : ∀ X v, sched X = some v → P2.live v = true ∧ X.x.e.ts v ≤ X.x.e.now ∧ X.armed v = false)
    (hss : ∀ y X, ArmInv Wn X → P2.live y = true → X.x.e.ts y ≤ X.x.e.now → X.armed y = false →
      sched X ≠ none) (n : Nat) :
    win3 (armP P2 fw edge sched X0) P2 fw edge sched X0 (πE (run3 P2 fw edge sched n X0)) =
      sched (run3 P2 fw edge sched n X0) := by
  have hI := arm_run3 P2 Wn fw edge hedge sched hf hsw n X0 hX0
  have hk : (πE (run3 P2 fw edge sched n X0)).now - X0.x.e.now = n := by
    show (run3 P2 fw edge sched n X0).x.e.now - X0.x.e.now = n
    rw [now_run3]
    omega
  unfold win3
  rw [hk]
  cases hs : sched (run3 P2 fw edge sched n X0) with
  | some v =>
    have h1 := hsw _ v hs
    have h2 := (ready_iff Wn _ hI v).mp ⟨h1.2.1, h1.2.2⟩
    have hc : ((armP P2 fw edge sched X0).live v &&
        decide ((πE (run3 P2 fw edge sched n X0)).ts v ≤ (πE (run3 P2 fw edge sched n X0)).now))
        = true := by
      simp only [Bool.and_eq_true, decide_eq_true_eq]
      exact ⟨h1.1, h2⟩
    dsimp only
    rw [if_pos hc]
  | none =>
    dsimp only
    cases hf' : firstReady (armP P2 fw edge sched X0) (πE (run3 P2 fw edge sched n X0)) with
    | none => rfl
    | some v =>
      have h1 := firstReady_some _ _ v hf'
      have h2 := (ready_iff Wn _ hI v).mpr h1.2
      exact absurd hs (hss v _ hI h1.1 h2.1 h2.2)

/-- **Run refinement, ARM.** On the fragment, the V4b view of a run with ARMs is a V4b run of
`armP` under `win3`. -/
theorem run3_proj (P2 : Program2) (Wn : Nat) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
    (hedge : ∀ t l, t + 1 ≤ edge t l) (sched : Engine3 → Option Lane) (X0 : Engine3)
    (hX0 : ArmInv Wn X0) (hf : ∀ y, ArmFragW Wn (fw y))
    (hsw : ∀ X v, sched X = some v → P2.live v = true ∧ X.x.e.ts v ≤ X.x.e.now ∧ X.armed v = false)
    (hss : ∀ y X, ArmInv Wn X → P2.live y = true → X.x.e.ts y ≤ X.x.e.now → X.armed y = false →
      sched X ≠ none) :
    ∀ n, πE (run3 P2 fw edge sched n X0) =
      run (armP P2 fw edge sched X0) (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) n
        (πE X0)
  | 0 => rfl
  | n + 1 => by
    have hk : (run3 P2 fw edge sched n X0).x.e.now - X0.x.e.now = n := by
      rw [now_run3]
      omega
    rw [run3_succ', run_succ', ← run3_proj P2 Wn fw edge hedge sched X0 hX0 hf hsw hss n]
    rw [step_win_congr (armP P2 fw edge sched X0)
      (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0),
      win3_on P2 Wn fw edge hedge sched X0 hX0 hf hsw hss n]
    refine step3_proj P2 (armP P2 fw edge sched X0) Wn fw edge hedge _ _
      (arm_run3 P2 Wn fw edge hedge sched hf hsw n X0 hX0) rfl rfl ?_ ?_ ?_
    · show (run3 P2 fw edge sched ((run3 P2 fw edge sched n X0).x.e.now - X0.x.e.now) X0).x.retire
        P2 = _
      rw [hk]
    · show ext3 P2 edge (run3 P2 fw edge sched ((run3 P2 fw edge sched n X0).x.e.now - X0.x.e.now)
        X0) = _
      rw [hk]
    · show decide ((fw (run3 P2 fw edge sched
        ((πE (run3 P2 fw edge sched n X0)).now - X0.x.e.now) X0).x).op = .br) = _
      show decide ((fw (run3 P2 fw edge sched
        ((run3 P2 fw edge sched n X0).x.e.now - X0.x.e.now) X0).x).op = .br) = _
      rw [hk]

/-- **The ARM's release.** After an ARM's writeback, its lane's V4b release is one past the
edge the input names for it: the gap the ARM opens (`GapRun.gp`) is that edge's distance. -/
theorem arm_release (P : Program2) (Wn : Nat) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
    (w : Option Lane) (X : Engine3) (h : ArmInv Wn X) (harm : X.armWB P = true) :
    (πE (step3 P fw edge w X)).ts X.x.e.cur = edge X.x.e.now X.x.e.cur + 1 := by
  have hst : X.x.e.st = .wb := by
    unfold Engine3.armWB at harm
    simp only [Bool.and_eq_true, decide_eq_true_eq] at harm
    exact harm.1.1
  have hna : X.armed X.x.e.cur = false := by
    cases hc : X.armed X.x.e.cur
    · rfl
    · exact absurd ⟨by rw [hst]; decide, rfl⟩ (h.2.2.2.1 _ hc)
  have hc : (X.armWB P && decide (X.x.e.cur = X.x.e.cur)) = true := by simp [harm]
  show (if (if X.hit X.x.e.cur = true then false
      else if (X.armWB P && decide (X.x.e.cur = X.x.e.cur)) = true then true
      else X.armed X.x.e.cur) = true
    then (if (X.armWB P && decide (X.x.e.cur = X.x.e.cur)) = true then edge X.x.e.now X.x.e.cur
      else X.armE X.x.e.cur) + 1
    else _) = _
  rw [hit_false X _ hna, hc]
  rfl
/-- **Head valid for runs with ARMs and branches.** `head_late_gap` on the V4b view: with the
per-retirement gaps (an ARM's is its edge's distance, `arm_release`), response bounds `Rr`,
certificate `Z` and lateness `L` read on the projected run, lane `y`'s head is valid at `t`
once the word released after its latest retirement has waited its allowance. -/
theorem head_late_arm (P2 : Program2) (Wn : Nat) (fw : Engine2 → Word)
    (edge : Nat → Lane → Nat) (hedge : ∀ t l, t + 1 ≤ edge t l)
    (sched : Engine3 → Option Lane) (X0 : Engine3)
    (hX0 : ArmInv Wn X0) (hf : ∀ y, ArmFragW Wn (fw y))
    (hsw : ∀ X v, sched X = some v → P2.live v = true ∧ X.x.e.ts v ≤ X.x.e.now ∧ X.armed v = false)
    (hss : ∀ y X, ArmInv Wn X → P2.live y = true → X.x.e.ts y ≤ X.x.e.now → X.armed y = false →
      sched X ≠ none)
    (y : Lane) (B T : Nat) (Rr Z L : Nat → Nat)
    (hW : Wf (πE X0)) (hfull : ∀ s, X0.x.e.actv y s = true) (hy : P2.live y = true)
    (hR : ∀ x, x < T → IsRet (armP P2 fw edge sched X0) y (πE (run3 P2 fw edge sched x X0)) →
      (πE (run3 P2 fw edge sched x X0)).now ≤ (πE (run3 P2 fw edge sched x X0)).ts y + Rr x + 2)
    (hB : ∀ a m, a + m ≤ T → m ≤ 23 + B →
      chargeSum (armP P2 fw edge sched X0) (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0)
        y m (πE (run3 P2 fw edge sched a X0)) ≤ B)
    (hZ0 : ∀ x, x < T → IsRet (armP P2 fw edge sched X0) y (πE (run3 P2 fw edge sched x X0)) →
      Rr x ≤ Z x)
    (hZF : ∀ x, x < T → IsRet (armP P2 fw edge sched X0) y (πE (run3 P2 fw edge sched x X0)) →
      NpfAt y (πE (run3 P2 fw edge sched x X0)) → Rr x + DSTAR + B ≤ Z x)
    (hZC : ∀ x x2, x2 < T → Consec (armP P2 fw edge sched X0)
        (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) y (πE X0) x x2 →
      Z x + DSTAR + B ≤ gp (armP P2 fw edge sched X0)
        (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) y (πE X0) x + Z x2)
    (hHD : ∀ x, x < T → IsRet (armP P2 fw edge sched X0) y (πE (run3 P2 fw edge sched x X0)) →
      NpfAt y (πE (run3 P2 fw edge sched x X0)) →
      Rr x + HEAD_SLACK + B ≤ gp (armP P2 fw edge sched X0)
        (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) y (πE X0) x + L x)
    (hHN : ∀ x x2, x2 < T → Consec (armP P2 fw edge sched X0)
        (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) y (πE X0) x x2 →
      Z x + HEAD_SLACK + B ≤ gp (armP P2 fw edge sched X0)
          (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) y (πE X0) x +
        gp (armP P2 fw edge sched X0)
          (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) y (πE X0) x2 + L x2)
    (t : Nat) (htT : t ≤ T)
    (hlate : ∀ x, x < t →
      IsRet (armP P2 fw edge sched X0) y (πE (run3 P2 fw edge sched x X0)) →
      cnt (armP P2 fw edge sched X0) (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0)
          (IsRet (armP P2 fw edge sched X0) y) (x + 1) (πE X0) =
        cnt (armP P2 fw edge sched X0) (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0)
          (IsRet (armP P2 fw edge sched X0) y) t (πE X0) →
      (πE (run3 P2 fw edge sched t X0)).ts y + L x ≤ (run3 P2 fw edge sched t X0).x.e.now) :
    (run3 P2 fw edge sched t X0).x.e.headValid y = true := by
  have hpr := run3_proj P2 Wn fw edge hedge sched X0 hX0 hf hsw hss
  have key := head_late_gap (armP P2 fw edge sched X0)
    (win3 (armP P2 fw edge sched X0) P2 fw edge sched X0) y (πE X0) B T Rr Z L hW hfull hy
    (fun x hx h => by rw [← hpr] at h ⊢; exact hR x hx h)
    (fun a m ham hm => by rw [← hpr]; exact hB a m ham hm)
    (fun x hx h => by rw [← hpr] at h; exact hZ0 x hx h)
    (fun x hx h hn => by rw [← hpr] at h hn; exact hZF x hx h hn)
    hZC
    (fun x hx h hn => by rw [← hpr] at h hn; exact hHD x hx h hn)
    hHN t htT
    (fun x hx h hc => by rw [← hpr] at h ⊢; exact hlate x hx h hc)
  rw [← hpr] at key
  exact key
#print axioms run3_proj
#print axioms step3_proj
#print axioms arm_step
#print axioms arm_release
#print axioms head_late_arm

end JLane
