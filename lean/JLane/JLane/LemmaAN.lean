import JLane.FlushRestart
/-!
# Brick F3a — Lemma A counting every idle cycle without a decision

`LemmaAS.lemmaA_s` counted the stalls where the winner's head is empty, and needed the scheduler
to name a winner whenever the waiting lane is ready. A FALLTHROUGH ARM's timeout adds a third
kind of empty cycle: the decision that **only disarms** the lane, with nothing dispatched
(agent 1, 11-14). Here every idle cycle with no decision counts (`noDecB`), whatever the cause —
no winner, an empty head, a disarm — and Lemma A needs no hypothesis about the scheduler at all:
a lane waiting `t` cycles ready and undecided saw `t ≤ 3·D + S + 2`, `S` the no-decision cycles.
-/
namespace JLane

/-- An idle cycle in which no lane is decided. -/
def noDecB (win : Engine → Option Lane) (e : Engine) : Bool :=
  decide (e.st = .idle) &&
    (match win e with
     | some w => !e.headValid w
     | none   => true)

theorem lemA_step_n (P : Program) (win : Engine → Option Lane) (i : Lane) (e : Engine)
    (hnd : ¬Dec win i e) :
    3 * (if decOther win i e = true then 1 else 0) + (if noDecB win e = true then 1 else 0)
        + ph e.st = 1 + ph (step P win e).st := by
  show 3 * (if decOther win i e = true then 1 else 0) + (if noDecB win e = true then 1 else 0)
      + ph e.st = 1 + ph (dispNext win e).st
  cases hs : e.st with
  | idle =>
    cases hw : win e with
    | none =>
      have hd : decOther win i e = false := by simp [decOther, hw]
      have hn : noDecB win e = true := by simp [noDecB, hw, hs]
      simp [hd, hn, dispNext, hs, hw, ph]
    | some w =>
      by_cases hv : e.headValid w = true
      · have hwi : w ≠ i := by
          rintro rfl
          exact hnd ⟨hs, hw, hv⟩
        have hd : decOther win i e = true := by simp [decOther, hw, hs, hwi, hv]
        have hn : noDecB win e = false := by simp [noDecB, hw, hs, hv]
        simp [hd, hn, dispNext, hs, hw, hv, ph]
      · have hv' : e.headValid w = false := by
          cases h' : e.headValid w
          · rfl
          · exact absurd h' hv
        have hd : decOther win i e = false := by simp [decOther, hw, hs, hv']
        have hn : noDecB win e = true := by simp [noDecB, hw, hs, hv']
        simp [hd, hn, dispNext, hs, hw, hv', ph]
  | drive =>
    have hd : decOther win i e = false := by
      unfold decOther
      cases win e <;> simp [hs]
    have hn : noDecB win e = false := by simp [noDecB, hs]
    simp [hd, hn, dispNext, hs, ph]
  | wb =>
    have hd : decOther win i e = false := by
      unfold decOther
      cases win e <;> simp [hs]
    have hn : noDecB win e = false := by simp [noDecB, hs]
    simp [hd, hn, dispNext, hs, ph]

theorem lemA_run_n (P : Program) (win : Engine → Option Lane) (i : Lane) :
    ∀ (t : Nat) (e : Engine), Ready P i e → NotMid i e →
      (∀ s, s < t → ¬Dec win i (run P win s e)) →
      3 * cnt P win (fun e => decOther win i e = true) t e
        + cnt P win (fun e => noDecB win e = true) t e + ph e.st
        = t + ph (run P win t e).st
  | 0, e, _, _, _ => by simp [cnt, run]
  | t + 1, e, hr, hm, hnd => by
    have hnd0 : ¬Dec win i e := hnd 0 (Nat.succ_pos t)
    have h1 := lemA_step_n P win i e hnd0
    have ih := lemA_run_n P win i t (step P win e) (ready_step P win i e hr hm)
      (notMid_step P win i e hm hnd0)
      (fun s hs => hnd (s + 1) (Nat.succ_lt_succ hs))
    have e1 : cnt P win (fun e => decOther win i e = true) (t + 1) e
        = (if decOther win i e = true then 1 else 0)
          + cnt P win (fun e => decOther win i e = true) t (step P win e) := rfl
    have e2 : cnt P win (fun e => noDecB win e = true) (t + 1) e
        = (if noDecB win e = true then 1 else 0)
          + cnt P win (fun e => noDecB win e = true) t (step P win e) := rfl
    have e3 : run P win (t + 1) e = run P win t (step P win e) := rfl
    rw [e3]
    omega

/-- **Lemma A, every empty cycle counted.** No scheduler hypothesis: a lane that waited `t`
cycles ready and undecided saw `t ≤ 3·D + S + 2`, `S` the idle cycles with no decision (stalls,
no winner, FALLTHROUGH disarms). -/
theorem lemmaA_n (P : Program) (win : Engine → Option Lane) (i : Lane) (t : Nat) (e : Engine)
    (hr : Ready P i e) (hm : NotMid i e)
    (hnd : ∀ s, s < t → ¬Dec win i (run P win s e)) :
    t ≤ 3 * cnt P win (fun e => decOther win i e = true) t e
      + cnt P win (fun e => noDecB win e = true) t e + 2 := by
  have h := lemA_run_n P win i t e hr hm hnd
  have h2 := ph_le e.st
  omega

#print axioms lemmaA_n

end JLane
