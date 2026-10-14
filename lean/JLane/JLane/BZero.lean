import JLane.Close
/-!
# Brick B1 — towards B = 0
(1) no branch-1 issue in a window ⇒ zero charge;
(2) a head that was valid and is now empty means the lane just wrote back;
(3) under HeadFirst, an empty head means the lane owes both slots.
-/
namespace JLane

/-- No branch-1 issue this cycle. -/
def NoBr1 (P : Program) (e : Engine) : Prop :=
  e.pst = .scan → br1 P e = none

theorem charge_zero (P : Program) (y : Lane) (e : Engine) (h : NoBr1 P e) :
    charge P y e = 0 := by
  cases hb : br1 P e with
  | none => simp [charge, hb]
  | some w =>
    by_cases hp : e.pst = .scan
    · have := h hp
      rw [hb] at this
      cases this
    · simp [charge, hb, hp]

/-- **(1)** No branch-1 issue anywhere in a window ⇒ its charge is zero. -/
theorem chargeSum_zero (P : Program) (win : Engine → Option Lane) (y : Lane) :
    ∀ (n : Nat) (e : Engine), (∀ i, i < n → NoBr1 P (run P win i e)) →
      chargeSum P win y n e = 0
  | 0, _, _ => rfl
  | n + 1, e, h => by
    have h0 := charge_zero P y e (h 0 (Nat.succ_pos n))
    have ih := chargeSum_zero P win y n (step P win e)
      (fun i hi => h (i + 1) (Nat.succ_lt_succ hi))
    show charge P y e + chargeSum P win y n (step P win e) = 0
    omega

/-- **(2)** A head that was valid and is now empty: the lane just retired. -/
theorem head_drop_wb (P : Program) (win : Engine → Option Lane) (e : Engine) (w : Lane)
    (hv : e.headValid w = true) (hn : (step P win e).headValid w = false) :
    IsRet P w e := by
  by_cases hw : e.st = .wb ∧ w = e.cur ∧ P.ret e.now e.cur = true
  · exact ⟨hw.1, hw.2.1.symm, by rw [hw.2.1]; exact hw.2.2⟩
  · exfalso
    have hs : selNext P e w = e.sel w := by
      unfold selNext
      rw [if_neg hw]
    have hk : actvNext P e w (selNext P e w) = true := by
      rw [hs]
      exact actvNext_keep_true P e w _ hw hv
    change actvNext P e w (selNext P e w) = false at hn
    rw [hk] at hn
    cases hn

/-- **(3)** Under HeadFirst, an empty head means the lane owes both slots. -/
theorem owed_two_of_head (e : Engine) (l : Lane) (hH : HeadFirst e)
    (h : e.headValid l = false) : e.owed l = 2 := by
  have hs := hH l h
  unfold Engine.headValid at h
  unfold Engine.spareValid at hs
  unfold Engine.owed
  cases hsel : e.sel l
  · rw [hsel] at h hs
    have hs' : e.actv l true = false := by simpa using hs
    simp [h, hs']
  · rw [hsel] at h hs
    have hs' : e.actv l false = false := by simpa using hs
    simp [h, hs']

/-- Branch 1 serves last cycle's winner. -/
theorem br1_winq (P : Program) (e : Engine) (w : Lane) (h : br1 P e = some w) :
    e.winq = some w := by
  unfold br1 at h
  cases hq : e.winq with
  | none =>
    rw [hq] at h
    dsimp only at h
    cases h
  | some v =>
    rw [hq] at h
    dsimp only at h
    by_cases hc : (P.live v && !e.headValid v) = true
    · rw [if_pos hc] at h
      cases h
      rfl
    · rw [if_neg hc] at h
      cases h

end JLane
