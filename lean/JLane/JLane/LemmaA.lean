import JLane.DStar
/-!
# Brick 10 — Lemma A, pigeonhole core
While lane `i` waits (ready, not yet decided), every cycle the quantity
`3·(other-lane decisions) − (cycles left in the current dispatch)` rises by exactly 1.
So the wait is at most `3·D + 2`, where `D` counts other-lane decisions in it.
With each other lane decided at most once (`D ≤ k − 1`): wait ≤ 14.
Needs only the dispatch FSM, no stalls, and a winner existing whenever `i` is ready;
holds for any work-conserving scheduler.
-/
namespace JLane

/-- Lane `w` is decided this cycle. -/
def Dec (win : Engine → Option Lane) (w : Lane) (e : Engine) : Prop :=
  e.st = .idle ∧ win e = some w ∧ e.headValid w = true

/-- Lane `i` is released and pending. -/
def Ready (P : Program) (i : Lane) (e : Engine) : Prop :=
  P.live i = true ∧ e.ts i ≤ e.now

/-- Lane `i` is not in the middle of its own dispatch. -/
def NotMid (i : Lane) (e : Engine) : Prop :=
  ¬(e.st ≠ .idle ∧ e.cur = i)

/-- Cycles until the dispatch FSM is idle again. -/
def ph : DState → Nat
  | .idle  => 0
  | .drive => 2
  | .wb    => 1

theorem ph_le (s : DState) : ph s ≤ 2 := by
  cases s <;> decide

/-- A lane other than `i` is decided this cycle. -/
def decOther (win : Engine → Option Lane) (i : Lane) (e : Engine) : Bool :=
  match win e with
  | some w => decide (e.st = .idle) && decide (w ≠ i) && e.headValid w
  | none   => false

/-! ### Waiting is stable -/

theorem ready_step (P : Program) (win : Engine → Option Lane) (i : Lane) (e : Engine)
    (hr : Ready P i e) (hm : NotMid i e) : Ready P i (step P win e) := by
  obtain ⟨hl, hts⟩ := hr
  refine ⟨hl, ?_⟩
  have h1 := ts_step P win e i
  have hnw : ¬IsWB i e := fun h => by
    obtain ⟨h1, h2⟩ := h
    exact hm ⟨by rw [h1]; decide, h2⟩
  rw [if_neg hnw] at h1
  show (step P win e).ts i ≤ e.now + 1
  omega

theorem notMid_step (P : Program) (win : Engine → Option Lane) (i : Lane) (e : Engine)
    (hm : NotMid i e) (hnd : ¬Dec win i e) : NotMid i (step P win e) := by
  unfold NotMid at hm ⊢
  show ¬((dispNext win e).st ≠ .idle ∧ (dispNext win e).cur = i)
  rintro ⟨hst, hcur⟩
  cases hs : e.st with
  | idle =>
    cases hw : win e with
    | none => simp [dispNext, hs, hw] at hst
    | some w =>
      by_cases hv : e.headValid w = true
      · simp [dispNext, hs, hw, hv] at hcur
        exact hnd ⟨hs, by rw [hw, hcur], by rw [← hcur]; exact hv⟩
      · simp [dispNext, hs, hw, hv] at hst
  | drive =>
    simp [dispNext, hs] at hcur
    exact hm ⟨by rw [hs]; decide, hcur⟩
  | wb =>
    simp [dispNext, hs] at hst

/-! ### The per-cycle identity -/

theorem lemA_step (P : Program) (win : Engine → Option Lane) (i : Lane) (e : Engine)
    (hws : ∀ e, e.st = .idle → Ready P i e → win e ≠ none)
    (hr : Ready P i e) (hnd : ¬Dec win i e) (hns : NoStall win e) :
    3 * (if decOther win i e = true then 1 else 0) + ph e.st
      = 1 + ph (step P win e).st := by
  show 3 * (if decOther win i e = true then 1 else 0) + ph e.st
      = 1 + ph (dispNext win e).st
  cases hs : e.st with
  | idle =>
    cases hw : win e with
    | none => exact absurd hw (hws e hs hr)
    | some w =>
      have hv : e.headValid w = true := hns hs w hw
      have hwi : w ≠ i := by
        rintro rfl
        exact hnd ⟨hs, hw, hv⟩
      have hd : decOther win i e = true := by
        simp [decOther, hw, hs, hwi, hv]
      simp [hd, dispNext, hs, hw, hv, ph]
  | drive =>
    have hd : decOther win i e = false := by
      unfold decOther
      cases win e <;> simp [hs]
    simp [hd, dispNext, hs, ph]
  | wb =>
    have hd : decOther win i e = false := by
      unfold decOther
      cases win e <;> simp [hs]
    simp [hd, dispNext, hs, ph]

theorem lemA_run (P : Program) (win : Engine → Option Lane) (i : Lane)
    (hws : ∀ e, e.st = .idle → Ready P i e → win e ≠ none) :
    ∀ (t : Nat) (e : Engine), Ready P i e → NotMid i e →
      (∀ s, s < t → ¬Dec win i (run P win s e)) →
      (∀ s, s < t → NoStall win (run P win s e)) →
      3 * cnt P win (fun e => decOther win i e = true) t e + ph e.st
        = t + ph (run P win t e).st
  | 0, e, _, _, _, _ => by simp [cnt, run]
  | t + 1, e, hr, hm, hnd, hns => by
    have hnd0 : ¬Dec win i e := hnd 0 (Nat.succ_pos t)
    have h1 := lemA_step P win i e hws hr hnd0 (hns 0 (Nat.succ_pos t))
    have ih := lemA_run P win i hws t (step P win e) (ready_step P win i e hr hm)
      (notMid_step P win i e hm hnd0)
      (fun s hs => hnd (s + 1) (Nat.succ_lt_succ hs))
      (fun s hs => hns (s + 1) (Nat.succ_lt_succ hs))
    have e1 : cnt P win (fun e => decOther win i e = true) (t + 1) e
        = (if decOther win i e = true then 1 else 0)
          + cnt P win (fun e => decOther win i e = true) t (step P win e) := rfl
    have e3 : run P win (t + 1) e = run P win t (step P win e) := rfl
    rw [e3]
    omega

/-- **Lemma A (pigeonhole core).** A lane that has waited `t` cycles undecided saw at
least `(t − 2)/3` other-lane decisions: `t ≤ 3·D + 2`. -/
theorem lemmaA (P : Program) (win : Engine → Option Lane) (i : Lane)
    (hws : ∀ e, e.st = .idle → Ready P i e → win e ≠ none) (t : Nat) (e : Engine)
    (hr : Ready P i e) (hm : NotMid i e)
    (hnd : ∀ s, s < t → ¬Dec win i (run P win s e))
    (hns : ∀ s, s < t → NoStall win (run P win s e)) :
    t ≤ 3 * cnt P win (fun e => decOther win i e = true) t e + 2 := by
  have h := lemA_run P win i hws t e hr hm hnd hns
  have h2 := ph_le e.st
  omega

/-- With at most `k − 1` other-lane decisions in the wait, it lasts at most
`3(k − 1) + 2 = 14` cycles. -/
theorem lemmaA_14 (P : Program) (win : Engine → Option Lane) (i : Lane)
    (hws : ∀ e, e.st = .idle → Ready P i e → win e ≠ none) (t : Nat) (e : Engine)
    (hr : Ready P i e) (hm : NotMid i e)
    (hnd : ∀ s, s < t → ¬Dec win i (run P win s e))
    (hns : ∀ s, s < t → NoStall win (run P win s e))
    (hD : cnt P win (fun e => decOther win i e = true) t e ≤ K - 1) :
    t ≤ 3 * (K - 1) + 2 := by
  have := lemmaA P win i hws t e hr hm hnd hns
  have hK : K - 1 = 4 := rfl
  omega

end JLane
