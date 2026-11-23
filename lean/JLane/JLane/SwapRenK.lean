import JLane.SwapRen
import JLane.FlushHeld
/-!
# Brick K12c — the renaming through the flush and the armed step (11-22, Part A lift: L1 + L2)

`SwapRen.sim_step` relates the RTL's buffered step to BufEng's on the renamed state. Here the same
relation is carried through the flush-and-kill step (`FlushKill.stepBKK`, L1) and the armed step
(`FlushHeld.stepBA`, L2).

* **L1, `simK_step`.** The RTL's flush step `stepBKKR` is `stepBKK` with the RTL's buffered step.
  A flush on lane `l` keeps the edge word where K3 puts it: in its slot if it is in one, else the
  lane's current head slot. `hasEdge` does not read the select. If the edge word is in a slot the
  kept slot is the same physical slot in both, and the flush ENDS the renaming on that lane (the
  select is that slot in both). Premise (`hkeep`): every flushed renamed lane holds its edge word
  in a slot. The edge word arriving in the edge's own capture or from the buffer is filed into the
  current head slot, which differs physically between the two: that case is a slot swap, not a
  renaming, and is L3 (owed).
* **L2, `simA_step`.** The RTL's armed step `stepBAR`: the armed registers and the edge do not read
  the select (`isArm` premised not to, like `win`); the dispatcher is masked by `armed`
  (`winA`), so "the dispatcher never picks a renamed lane" follows from "every renamed lane is
  armed" (`hns_armed`), here discharged rather than premised.

The renamed set after a cycle: the old one with the new no-swap lanes, less the flushed lanes.
-/
namespace JLane

/-- The renaming on the flush run's state. -/
def renK (ns : Lane → Bool) (X : EngBK) : EngBK := { X with x := ren ns X.x }

theorem renK_base (ns : Lane → Bool) (X : EngBK) : (renK ns X).base = ren ns X.base := by
  unfold renK EngBK.base
  cases X.pkill <;> rfl

/-- `hasEdge` reads the slots' words, never the select. -/
theorem ren_hasEdge (ns : Lane → Bool) (x : EngB) (l : Lane) (k : Nat) :
    (ren ns x).hasEdge l k = x.hasEdge l k := rfl

theorem ren_inSlot (ns : Lane → Bool) (x : EngB) (l : Lane) (k : Nat) (s : Slot) :
    (ren ns x).inSlot l k s = x.inSlot l k s := rfl

/-- The kept slot is the same physical slot when the edge word is in a slot, or the lane is not
renamed. -/
theorem ren_keepSlot (ns : Lane → Bool) (x : EngB) (l : Lane) (k : Nat)
    (h : ns l = false ∨ x.inSlot l k true = true ∨ x.inSlot l k false = true) :
    keepSlot (ren ns x) l k = keepSlot x l k := by
  unfold keepSlot
  rw [ren_inSlot, ren_inSlot]
  rcases h with hn | ht | hf
  · rw [show (ren ns x).e.sel l = x.e.sel l from renE_sel_off ns x.e l hn]
  · rw [if_pos ht, if_pos ht]
  · by_cases ht : x.inSlot l k true = true
    · rw [if_pos ht, if_pos ht]
    · rw [if_neg ht, if_neg ht, if_pos hf, if_pos hf]

/-- **The RTL's flush step**: `stepBKK` with the RTL's buffered step (`stepBR`, the no-swap `nw`). -/
def stepBKKR (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
    (sreq : EngB → Option Lane) (nw : Lane → Bool) (fl : Lane → Bool) (k : Lane → Nat)
    (X : EngBK) : EngBK :=
  let b := X.base
  let y := stepBR P win usb sreq nw b
  { x := { y with
      e := { y.e with
        actv := fun l s => if fl l = true then b.hasEdge l (k l) && decide (s = keepSlot b l (k l))
          else if (X.kc && decide (l = b.e.pl) && capTo b l s) = true then false
          else y.e.actv l s
        sel := fun l => if fl l = true then keepSlot b l (k l) else y.e.sel l
        ts := fun l => if fl l = true then b.e.now + 1 else y.e.ts l }
      buf := fun l => if fl l = true then false
        else if (X.kc && decide (l = b.e.pl)) = true then false else y.buf l
      sq := fun l s => if fl l = true ∧ s = keepSlot b l (k l) then y.nr l else y.sq l s }
    pkill := if X.x.e.pst = .cap then false
      else X.pkill || (fl X.x.e.pl && (decide (X.x.e.pst = .req) || decide (X.x.e.pst = .wait))) }

theorem EngBK.ext' (a b : EngBK) (hx : a.x = b.x) (hk : a.pkill = b.pkill) : a = b := by
  cases a; cases b; simp_all

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane)

/-- **L1: the simulation through the flush.** -/
theorem simK_step (ns nw fl : Lane → Bool) (k : Lane → Nat) (X : EngBK) (hW : WfBK X)
    (hhead : ∀ l, ns l = true → X.base.e.headValid l = true ∨
      (X.base.e.pst ≠ .scan ∧ X.base.e.pl = l ∧ X.base.pb = false))
    (hdisp : ∀ l, ns l = true → ¬(X.base.e.st ≠ .idle ∧ X.base.e.cur = l))
    (hnw : ∀ l, nw l = true → X.base.e.st = .wb ∧ l = X.base.e.cur ∧
      P.ret X.base.e.now X.base.e.cur = true ∧ ns l = false ∧ fl l = false)
    (hnpf : ∀ l, ns l = true → X.base.e.npf l (X.base.e.sel l) = false)
    (hwinq : ∀ l, ns l = true → X.base.e.winq ≠ some l)
    (hsr : sreq (ren ns X.base) = sreq X.base) (hsrn : ∀ l, ns l = true → sreq X.base ≠ some l)
    (hwin : win (renE ns X.base.e) = win X.base.e)
    (hwinn : ∀ l, ns l = true → win X.base.e ≠ some l)
    (hpick : ∀ f, P.pick = some f → f (renE ns X.base.e) = f X.base.e ∧
      ∀ l, ns l = true → f X.base.e ≠ some l)
    (hfnpf : P.fnpf (renE ns X.base.e) = P.fnpf X.base.e)
    (hkeep : ∀ l, fl l = true → ns l = true →
      X.base.inSlot l (k l) true = true ∨ X.base.inSlot l (k l) false = true) :
    stepBKKR P win usb sreq nw fl k (renK ns X)
      = renK (fun l => (ns l || nw l) && !fl l) (stepBKK P win usb sreq fl k X) := by
  have hs := sim_step P win usb sreq ns nw X.base hW.wf hhead hdisp
    (fun l h => let ⟨a, b, c, d, _⟩ := hnw l h; ⟨a, b, c, d⟩) hnpf hwinq hsr hsrn hwin hwinn
    hpick hfnpf
  have hks : ∀ l, fl l = true → keepSlot (ren ns X.base) l (k l) = keepSlot X.base l (k l) :=
    fun l hf => ren_keepSlot ns X.base l (k l) (by
      cases hn : ns l
      · exact Or.inl rfl
      · exact Or.inr (hkeep l hf hn))
  have hcap := fun l s => ren_capTo ns X.base l s hhead
  -- the same facts with `ren` written out, as the unfolded steps show it
  have hksE := hks
  have hcapE := hcap
  simp only [ren] at hksE hcapE
  apply EngBK.ext'
  · show (stepBKKR P win usb sreq nw fl k (renK ns X)).x
        = ren (fun l => (ns l || nw l) && !fl l) (stepBKK P win usb sreq fl k X).x
    unfold stepBKKR stepBKK
    simp only [renK_base]
    rw [hs]
    apply EngB.ext'
    · apply Engine.ext'
      · rfl
      · funext l s
        simp only [ren, renE_actv, renE_pl]
        by_cases hf : fl l = true
        · rw [if_pos hf, if_pos hf]
          simp only [hksE l hf]
          all_goals rfl
        · rw [if_neg hf, if_neg hf]
          simp only [hcapE l s]
          all_goals rfl
      · funext l
        show (if fl l = true then keepSlot (ren ns X.base) l (k l)
            else (ren (fun l => ns l || nw l) (stepB P win usb sreq X.base)).e.sel l)
          = (renE (fun l => (ns l || nw l) && !fl l) _).sel l
        rw [renE_sel]
        by_cases hf : fl l = true
        · rw [if_pos hf, hks l hf]
          simp [hf]
        · rw [if_neg hf, ren_e, renE_sel]
          simp [hf]
      · funext l
        simp only [ren, renE_ts, renE_now]
      · rfl
      · rfl
      · rfl
      · rfl
      · rfl
      · rfl
      · rfl
      · rfl
      · rfl
    · funext l
      simp only [ren, renE_pl]
      rfl
    · rfl
    · rfl
    · funext l s
      simp only [ren]
      by_cases hf : fl l = true
      · simp only [hksE l hf]
      · simp [hf]
    · rfl
    · rfl
    · rfl
  · rfl

end

/-! ### L2: the armed step -/

/-- The renaming on the armed run's state. -/
def renA (ns : Lane → Bool) (A : EngBA) : EngBA := { A with X := renK ns A.X }

/-- **The RTL's armed step**: `stepBA` with the RTL's flush step. -/
def stepBAR (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
    (sreq : EngB → Option Lane) (isArm : EngB → Bool) (edge : Nat → Lane → Nat)
    (nw : Lane → Bool) (k : Lane → Nat) (A : EngBA) : EngBA :=
  { X := stepBKKR P (winA win A.armed) usb sreq nw A.hit k A.X
    armed := fun l => if A.hit l = true then false
      else if A.arms P isArm l = true then true else A.armed l
    armE := fun l => if A.arms P isArm l = true then edge A.X.x.e.now l else A.armE l }

theorem EngBA.ext' (a b : EngBA) (hX : a.X = b.X) (ha : a.armed = b.armed) (he : a.armE = b.armE) :
    a = b := by
  cases a; cases b; simp_all

/-- The masked dispatcher never names an armed lane. -/
theorem winA_not_armed (win : Engine → Option Lane) (armed : Lane → Bool) (e : Engine) (l : Lane)
    (h : armed l = true) : winA win armed e ≠ some l := by
  unfold winA
  cases hw : win e with
  | none => simp
  | some v =>
    simp only []
    by_cases hv : armed v = true
    · rw [if_pos hv]; simp
    · rw [if_neg hv]
      intro hvl
      cases hvl
      exact hv h

theorem winA_ren (win : Engine → Option Lane) (armed : Lane → Bool) (ns : Lane → Bool) (e : Engine)
    (hwin : win (renE ns e) = win e) : winA win armed (renE ns e) = winA win armed e := by
  unfold winA; rw [hwin]

theorem renA_arms (P : Program) (isArm : EngB → Bool) (ns : Lane → Bool) (A : EngBA) (l : Lane)
    (hisArm : isArm (ren ns A.X.base) = isArm A.X.base) :
    (renA ns A).arms P isArm l = A.arms P isArm l := by
  unfold EngBA.arms
  rw [show (renA ns A).X.base = ren ns A.X.base from renK_base ns A.X, hisArm]
  rfl

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane)

/-- **L2: the simulation through the armed step.** Every renamed lane armed (`hns_armed`) makes the
dispatcher's "never a renamed lane" a consequence of `winA`'s mask, not a premise. -/
theorem simA_step (isArm : EngB → Bool) (edge : Nat → Lane → Nat) (ns nw : Lane → Bool)
    (k : Lane → Nat) (A : EngBA) (hW : WfBK A.X)
    (hns_armed : ∀ l, ns l = true → A.armed l = true)
    (hhead : ∀ l, ns l = true → A.X.base.e.headValid l = true ∨
      (A.X.base.e.pst ≠ .scan ∧ A.X.base.e.pl = l ∧ A.X.base.pb = false))
    (hdisp : ∀ l, ns l = true → ¬(A.X.base.e.st ≠ .idle ∧ A.X.base.e.cur = l))
    (hnw : ∀ l, nw l = true → A.X.base.e.st = .wb ∧ l = A.X.base.e.cur ∧
      P.ret A.X.base.e.now A.X.base.e.cur = true ∧ ns l = false ∧ A.hit l = false)
    (hnpf : ∀ l, ns l = true → A.X.base.e.npf l (A.X.base.e.sel l) = false)
    (hwinq : ∀ l, ns l = true → A.X.base.e.winq ≠ some l)
    (hsr : sreq (ren ns A.X.base) = sreq A.X.base)
    (hsrn : ∀ l, ns l = true → sreq A.X.base ≠ some l)
    (hwin : win (renE ns A.X.base.e) = win A.X.base.e)
    (hpick : ∀ f, P.pick = some f → f (renE ns A.X.base.e) = f A.X.base.e ∧
      ∀ l, ns l = true → f A.X.base.e ≠ some l)
    (hfnpf : P.fnpf (renE ns A.X.base.e) = P.fnpf A.X.base.e)
    (hisArm : isArm (ren ns A.X.base) = isArm A.X.base)
    (hkeep : ∀ l, A.hit l = true → ns l = true →
      A.X.base.inSlot l (k l) true = true ∨ A.X.base.inSlot l (k l) false = true) :
    stepBAR P win usb sreq isArm edge nw k (renA ns A)
      = renA (fun l => (ns l || nw l) && !A.hit l) (stepBA P win usb sreq isArm edge k A) := by
  have hK := simK_step P (winA win A.armed) usb sreq ns nw A.hit k A.X hW hhead hdisp hnw hnpf
    hwinq hsr hsrn (winA_ren win A.armed ns _ hwin)
    (fun l h => winA_not_armed win A.armed _ l (hns_armed l h)) hpick hfnpf hkeep
  apply EngBA.ext'
  · show stepBKKR P (winA win A.armed) usb sreq nw A.hit k (renK ns A.X)
      = renK (fun l => (ns l || nw l) && !A.hit l) (stepBKK P (winA win A.armed) usb sreq A.hit k A.X)
    exact hK
  · funext l
    show (if A.hit l = true then false
        else if (renA ns A).arms P isArm l = true then true else A.armed l)
      = (if A.hit l = true then false else if A.arms P isArm l = true then true else A.armed l)
    rw [renA_arms P isArm ns A l hisArm]
  · funext l
    show (if (renA ns A).arms P isArm l = true then edge A.X.x.e.now l else A.armE l)
      = (if A.arms P isArm l = true then edge A.X.x.e.now l else A.armE l)
    rw [renA_arms P isArm ns A l hisArm]

end

end JLane
