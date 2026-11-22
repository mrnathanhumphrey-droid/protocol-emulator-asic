import JLane.HfreeB
import JLane.BPrime
/-!
# Brick C3i — the K11 scheduler lemma (composition L4 hS, Wilson 11-21 ruling)

The bridged run's dispatcher is `winA win armed` (`FlushHeld.winA`): `win` chooses, then an armed
choice is dropped. The RTL masks BEFORE choosing (`rdy_rel = … & ~armed`), so it never has the
idle cycle where `win` named an armed lane while an unarmed one was ready. Wilson 11-21, option
(b): the contract **K11** -- the scheduler never chooses an armed lane while an unarmed lane is
ready -- and this lemma: under K11, `winA win armed` makes the same choice as `win` whenever an
unarmed lane is ready (so as choosing among unarmed ready lanes), and keeps the ruled scheduler's
properties (`BPrimeWin`: the winner's head valid; `hwin`: only live, released lanes). So the
window bound's no-decision count `S` in the window where `y` waits is the ruled scheduler's: 0
(`CloseBK.noDec_zero_K11`). The FALLTHROUGH disarm cycle (`ArmFT.disarm_noDec`, the scheduler
naming an armed lane) is the masked-pick stall K11 excludes while `y` is ready and unarmed; the
checker still charges it (`branch_budget._disarm_S`, Wilson 11-18). No change to `runBA_proj`
or the bridge.
-/
namespace JLane

/-- **K11** at one engine with arm registers `armed`: `win` never names an armed lane while an
unarmed lane is ready. -/
def K11At (P : Program) (win : Engine → Option Lane) (armed : Lane → Bool) (e : Engine) : Prop :=
  ∀ v, win e = some v → armed v = true → ∀ u, armed u = false → ¬Ready P u e

/-- **Under K11, the mask changes nothing while an unarmed lane is ready.** -/
theorem winA_eq_of_K11 (P : Program) (win : Engine → Option Lane) (armed : Lane → Bool)
    (e : Engine) (h : K11At P win armed e) (u : Lane) (hu : armed u = false)
    (hr : Ready P u e) : winA win armed e = win e := by
  unfold winA
  cases hw : win e with
  | none => rfl
  | some v =>
    cases ha : armed v with
    | false => simp [ha]
    | true => exact absurd hr (h v hw ha u hu)

/-- The masked dispatcher names a winner whenever `win` does and an unarmed lane is ready. -/
theorem winA_ne_none_of_K11 (P : Program) (win : Engine → Option Lane) (armed : Lane → Bool)
    (e : Engine) (h : K11At P win armed e) (u : Lane) (hu : armed u = false)
    (hr : Ready P u e) (hw : win e ≠ none) : winA win armed e ≠ none := by
  rw [winA_eq_of_K11 P win armed e h u hu hr]
  exact hw

/-- The masked dispatcher never names an armed lane. -/
theorem winA_unarmed (win : Engine → Option Lane) (armed : Lane → Bool) (e : Engine) (w : Lane)
    (h : winA win armed e = some w) : armed w = false := by
  unfold winA at h
  split at h
  · split at h
    · cases h
    · rename_i hv
      cases h
      cases ha : armed w with
      | false => rfl
      | true => exact absurd ha hv
  · cases h

/-- The masked dispatcher's winner is one `win` named. -/
theorem winA_some (win : Engine → Option Lane) (armed : Lane → Bool) (e : Engine) (w : Lane)
    (h : winA win armed e = some w) : win e = some w := by
  unfold winA at h
  split at h
  · rename_i v hv
    split at h
    · cases h
    · cases h
      exact hv
  · cases h

/-- (b′) survives the mask: the winner's head is valid. -/
theorem winA_bprime (win : Engine → Option Lane) (armed : Lane → Bool) (hb : BPrimeWin win) :
    BPrimeWin (winA win armed) :=
  fun e w h => hb e w (winA_some win armed e w h)

/-- `hwin` survives the mask: the winner is live and released. -/
theorem winA_released (P : Program) (win : Engine → Option Lane) (armed : Lane → Bool)
    (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now) :
    ∀ e w, winA win armed e = some w → P.live w = true ∧ e.ts w ≤ e.now :=
  fun e w h => hwin e w (winA_some win armed e w h)

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane) (isArm : EngB → Bool) (edge : Nat → Lane → Nat)
  (kt : Nat → Lane → Nat) (A0 : EngBA)

/-- **K11 on the bridged run.** With K11 at every cycle of the armed run, `winS` at cycle `n` of
`runBK P winS usb sreq flS kt` is `win` there whenever an unarmed lane is ready. -/
theorem winS_eq_of_K11
    (hK : ∀ n, K11At P win (runBA P win usb sreq isArm edge kt n A0).armed
      (runBA P win usb sreq isArm edge kt n A0).X.x.e)
    (n : Nat) (u : Lane) (hu : (runBA P win usb sreq isArm edge kt n A0).armed u = false)
    (hr : Ready P u (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
      (flS P win usb sreq isArm edge kt A0) kt n A0.X).x.e) :
    winS P win usb sreq isArm edge kt A0 (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt n A0.X).x.e
      = win (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt n A0.X).x.e := by
  rw [← runBA_proj P win usb sreq isArm edge kt A0 n] at hr ⊢
  simp only [winS, now_runBA P win usb sreq isArm edge kt A0 n, Nat.add_sub_cancel_left]
  exact winA_eq_of_K11 P win _ _ (hK n) u hu hr

end

end JLane
