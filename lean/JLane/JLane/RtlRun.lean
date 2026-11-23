import JLane.ArmT
import JLane.SwapRenK
/-!
# Brick R5 — the RTL-side armed run, both FT paths (piece 5's reference, 11-22)

Piece 5 replays the RTL against the extended armed run (Wilson 11-22: one armed run for both FT
paths), on the RTL's side of the renaming: `stepBTR` is `ArmT.stepBT` with the RTL's flush step
(`SwapRenK.stepBKKR`: the RTL's buffered step `SwapRen.stepBR` -- no swap at a no-swap FT ARM
writeback `nw`, a buffered word loads head-first -- under the K1–K5 keep-flush and the kill), the
flush set the arming ends `ends = hit || tmo` (the timeout at the pick, ruling 1b).

`simT_step`: one cycle of `stepBTR` on the renamed state is one cycle of `stepBT` renamed (the
no-swap lanes added, the lanes whose arming ends removed) -- `SwapRenK.simA_step`'s argument with
`ends` for `hit`. `model/step_b.py`'s `step_bt` transcribes `stepBTR` definition by definition.
-/
namespace JLane

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane) (isArm : EngB → Bool) (edge : Nat → Lane → Nat)

/-- **One cycle of the RTL-side armed run, both FT paths.** -/
def stepBTR (nw : Lane → Bool) (k : Lane → Nat) (A : EngBA) : EngBA :=
  { X := stepBKKR P (winA win A.armed) usb sreq nw (A.ends win) k A.X
    armed := fun l => if A.ends win l = true then false
      else if A.arms P isArm l = true then true else A.armed l
    armE := fun l => if A.arms P isArm l = true then edge A.X.x.e.now l else A.armE l }

/-- `n` cycles; the no-swap decisions and the kept indices read by time. -/
def runBTR (nwt : Nat → Lane → Bool) (kt : Nat → Lane → Nat) : Nat → EngBA → EngBA
  | 0, A => A
  | n + 1, A => stepBTR P win usb sreq isArm edge (nwt (runBTR nwt kt n A).X.x.e.now)
      (kt (runBTR nwt kt n A).X.x.e.now) (runBTR nwt kt n A)

/-- The renaming leaves the arming ends unchanged when the scheduler ignores the select. -/
theorem renA_ends (ns : Lane → Bool) (A : EngBA) (hw : win (renE ns A.X.x.e) = win A.X.x.e) :
    (renA ns A).ends win = A.ends win := by
  funext l
  have he : (renA ns A).X.x.e = renE ns A.X.x.e := rfl
  unfold EngBA.ends EngBA.tmo EngBA.hit
  rw [he, hw]
  rfl

/-- **The RTL-side step with both paths is the model's, renamed.** -/
theorem simT_step (ns nw : Lane → Bool) (k : Lane → Nat) (A : EngBA) (hW : WfBK A.X)
    (hns_armed : ∀ l, ns l = true → A.armed l = true)
    (hhead : ∀ l, ns l = true → A.X.base.e.headValid l = true ∨
      (A.X.base.e.pst ≠ .scan ∧ A.X.base.e.pl = l ∧ A.X.base.pb = false))
    (hdisp : ∀ l, ns l = true → ¬(A.X.base.e.st ≠ .idle ∧ A.X.base.e.cur = l))
    (hnw : ∀ l, nw l = true → A.X.base.e.st = .wb ∧ l = A.X.base.e.cur ∧
      P.ret A.X.base.e.now A.X.base.e.cur = true ∧ ns l = false ∧ A.ends win l = false)
    (hnpf : ∀ l, ns l = true → A.X.base.e.npf l (A.X.base.e.sel l) = false)
    (hwinq : ∀ l, ns l = true → A.X.base.e.winq ≠ some l)
    (hsr : sreq (ren ns A.X.base) = sreq A.X.base)
    (hsrn : ∀ l, ns l = true → sreq A.X.base ≠ some l)
    (hwin : win (renE ns A.X.base.e) = win A.X.base.e)
    (hpick : ∀ f, P.pick = some f → f (renE ns A.X.base.e) = f A.X.base.e ∧
      ∀ l, ns l = true → f A.X.base.e ≠ some l)
    (hfnpf : P.fnpf (renE ns A.X.base.e) = P.fnpf A.X.base.e)
    (hisArm : isArm (ren ns A.X.base) = isArm A.X.base)
    (hkeep : ∀ l, A.ends win l = true → ns l = true →
      A.X.base.inSlot l (k l) true = true ∨ A.X.base.inSlot l (k l) false = true) :
    stepBTR P win usb sreq isArm edge nw k (renA ns A)
      = renA (fun l => (ns l || nw l) && !A.ends win l) (stepBT P win usb sreq isArm edge k A) := by
  have hE : (renA ns A).ends win = A.ends win :=
    renA_ends win ns A (by rw [← base_e]; exact hwin)
  unfold stepBTR
  rw [hE]
  have hK := simK_step P (winA win A.armed) usb sreq ns nw (A.ends win) k A.X hW hhead hdisp hnw hnpf
    hwinq hsr hsrn (winA_ren win A.armed ns _ hwin)
    (fun l h => winA_not_armed win A.armed _ l (hns_armed l h)) hpick hfnpf hkeep
  apply EngBA.ext'
  · show stepBKKR P (winA win A.armed) usb sreq nw (A.ends win) k (renK ns A.X)
      = renK (fun l => (ns l || nw l) && !A.ends win l)
          (stepBKK P (winA win A.armed) usb sreq (A.ends win) k A.X)
    exact hK
  · funext l
    show (if A.ends win l = true then false
        else if (renA ns A).arms P isArm l = true then true else A.armed l)
      = (if A.ends win l = true then false else if A.arms P isArm l = true then true else A.armed l)
    rw [renA_arms P isArm ns A l hisArm]
  · funext l
    show (if (renA ns A).arms P isArm l = true then edge A.X.x.e.now l else A.armE l)
      = (if A.arms P isArm l = true then edge A.X.x.e.now l else A.armE l)
    rw [renA_arms P isArm ns A l hisArm]

end

end JLane
