import JLane.Armed
/-!
# Brick F — Lemma A with stalls (stage 5, step 1)

`LemmaA.lemmaA` assumed no stall: an idle dispatcher whose winner's head is valid. Under
option A and ARMs a word can be late, and the RTL then **stalls the whole dispatcher**
(`cur_ld = … & w_hv`, `pe_engine.v` l.1873; "THIS STALL IS THE JITTER TERM J", l.3194).
Here the identity carries the stall cycles: while lane `i` waits ready and undecided,
`3·(other-lane decisions) + (stall cycles) − (cycles left in the dispatch)` rises by exactly 1
per cycle, so the wait is at most `3·D + S + 2`. No stall-freedom hypothesis.
-/
namespace JLane

/-- A stall cycle: the dispatcher is idle, has a winner, and the winner's head is empty. -/
def stallB (win : Engine → Option Lane) (e : Engine) : Bool :=
  match win e with
  | some w => decide (e.st = .idle) && !e.headValid w
  | none   => false

theorem lemA_step_s (P : Program) (win : Engine → Option Lane) (i : Lane) (e : Engine)
    (hws : ∀ e, e.st = .idle → Ready P i e → win e ≠ none)
    (hr : Ready P i e) (hnd : ¬Dec win i e) :
    3 * (if decOther win i e = true then 1 else 0) + (if stallB win e = true then 1 else 0)
        + ph e.st = 1 + ph (step P win e).st := by
  show 3 * (if decOther win i e = true then 1 else 0) + (if stallB win e = true then 1 else 0)
      + ph e.st = 1 + ph (dispNext win e).st
  cases hs : e.st with
  | idle =>
    cases hw : win e with
    | none => exact absurd hw (hws e hs hr)
    | some w =>
      by_cases hv : e.headValid w = true
      · have hwi : w ≠ i := by
          rintro rfl
          exact hnd ⟨hs, hw, hv⟩
        have hd : decOther win i e = true := by
          simp [decOther, hw, hs, hwi, hv]
        have hst : stallB win e = false := by
          simp [stallB, hw, hs, hv]
        simp [hd, hst, dispNext, hs, hw, hv, ph]
      · have hv' : e.headValid w = false := by
          cases h' : e.headValid w
          · rfl
          · exact absurd h' hv
        have hd : decOther win i e = false := by
          simp [decOther, hw, hs, hv']
        have hst : stallB win e = true := by
          simp [stallB, hw, hs, hv']
        simp [hd, hst, dispNext, hs, hw, hv', ph]
  | drive =>
    have hd : decOther win i e = false := by
      unfold decOther
      cases win e <;> simp [hs]
    have hst : stallB win e = false := by
      unfold stallB
      cases win e <;> simp [hs]
    simp [hd, hst, dispNext, hs, ph]
  | wb =>
    have hd : decOther win i e = false := by
      unfold decOther
      cases win e <;> simp [hs]
    have hst : stallB win e = false := by
      unfold stallB
      cases win e <;> simp [hs]
    simp [hd, hst, dispNext, hs, ph]

theorem lemA_run_s (P : Program) (win : Engine → Option Lane) (i : Lane)
    (hws : ∀ e, e.st = .idle → Ready P i e → win e ≠ none) :
    ∀ (t : Nat) (e : Engine), Ready P i e → NotMid i e →
      (∀ s, s < t → ¬Dec win i (run P win s e)) →
      3 * cnt P win (fun e => decOther win i e = true) t e
        + cnt P win (fun e => stallB win e = true) t e + ph e.st
        = t + ph (run P win t e).st
  | 0, e, _, _, _ => by simp [cnt, run]
  | t + 1, e, hr, hm, hnd => by
    have hnd0 : ¬Dec win i e := hnd 0 (Nat.succ_pos t)
    have h1 := lemA_step_s P win i e hws hr hnd0
    have ih := lemA_run_s P win i hws t (step P win e) (ready_step P win i e hr hm)
      (notMid_step P win i e hm hnd0)
      (fun s hs => hnd (s + 1) (Nat.succ_lt_succ hs))
    have e1 : cnt P win (fun e => decOther win i e = true) (t + 1) e
        = (if decOther win i e = true then 1 else 0)
          + cnt P win (fun e => decOther win i e = true) t (step P win e) := rfl
    have e2 : cnt P win (fun e => stallB win e = true) (t + 1) e
        = (if stallB win e = true then 1 else 0)
          + cnt P win (fun e => stallB win e = true) t (step P win e) := rfl
    have e3 : run P win (t + 1) e = run P win t (step P win e) := rfl
    rw [e3]
    omega

/-- **Lemma A with stalls.** A lane that has waited `t` cycles ready and undecided saw at
least `(t − S − 2)/3` other-lane decisions, `S` the stall cycles in the wait:
`t ≤ 3·D + S + 2`. Holds for any scheduler that names a winner whenever `i` is ready. -/
theorem lemmaA_s (P : Program) (win : Engine → Option Lane) (i : Lane)
    (hws : ∀ e, e.st = .idle → Ready P i e → win e ≠ none) (t : Nat) (e : Engine)
    (hr : Ready P i e) (hm : NotMid i e)
    (hnd : ∀ s, s < t → ¬Dec win i (run P win s e)) :
    t ≤ 3 * cnt P win (fun e => decOther win i e = true) t e
      + cnt P win (fun e => stallB win e = true) t e + 2 := by
  have h := lemA_run_s P win i hws t e hr hm hnd
  have h2 := ph_le e.st
  omega

/-- With no stall in the window, the old Lemma A. -/
theorem lemmaA_of_s (P : Program) (win : Engine → Option Lane) (i : Lane)
    (hws : ∀ e, e.st = .idle → Ready P i e → win e ≠ none) (t : Nat) (e : Engine)
    (hr : Ready P i e) (hm : NotMid i e)
    (hnd : ∀ s, s < t → ¬Dec win i (run P win s e))
    (hS : cnt P win (fun e => stallB win e = true) t e = 0) :
    t ≤ 3 * cnt P win (fun e => decOther win i e = true) t e + 2 := by
  have := lemmaA_s P win i hws t e hr hm hnd
  omega

#print axioms lemmaA_s

end JLane
