import JLane.PrioResp
/-!
# Brick L — the ruled scheduler (b′): readiness includes "head valid" (Wilson 11-14)

Under the shipped scheduler an EDF winner with an empty head stalls the whole dispatcher
(`LemmaAS.stallB`). Under (b′) the winner is always a lane that can dispatch: released, not
armed, **and head valid**. Then:

* `stall_free_bprime` / `cnt_stall_bprime` — no cycle is a stall: the stall count is `0`;
* `lemmaA_b` — Lemma A for a lane `i` whose head is valid throughout its wait, with no stall
  term; the scheduler only has to name a winner while `i` is idle-ready-valid (`hws`);
* so a late lane delays only itself: its lateness is its own `L` in the certificate (`GapRun`).

Not here yet (needs agent 1's RTL batch, read first): the prefetch's new first priority
(earliest-deadline released lane with an empty head), FALLTHROUGH, HALF.
-/
namespace JLane

/-- The (b′) scheduler contract: the winner's head is valid. -/
def BPrimeWin (win : Engine → Option Lane) : Prop :=
  ∀ e w, win e = some w → e.headValid w = true

theorem stall_free_bprime (win : Engine → Option Lane) (h : BPrimeWin win) (e : Engine) :
    stallB win e = false := by
  unfold stallB
  cases hw : win e with
  | none => rfl
  | some w => simp [h e w hw]

theorem cnt_stall_bprime (P : Program) (win : Engine → Option Lane) (h : BPrimeWin win) :
    ∀ n e, cnt P win (fun e => stallB win e = true) n e = 0
  | 0, _ => rfl
  | n + 1, e => by
    have : cnt P win (fun e => stallB win e = true) (n + 1) e
        = (if stallB win e = true then 1 else 0)
          + cnt P win (fun e => stallB win e = true) n (step P win e) := rfl
    rw [this, stall_free_bprime win h e, cnt_stall_bprime P win h n (step P win e)]
    rfl

/-- One cycle of Lemma A's identity, with the winner required at this cycle only. -/
theorem lemA_step_l (P : Program) (win : Engine → Option Lane) (i : Lane) (e : Engine)
    (hws : e.st = .idle → win e ≠ none) (hnd : ¬Dec win i e) :
    3 * (if decOther win i e = true then 1 else 0) + (if stallB win e = true then 1 else 0)
        + ph e.st = 1 + ph (step P win e).st := by
  show 3 * (if decOther win i e = true then 1 else 0) + (if stallB win e = true then 1 else 0)
      + ph e.st = 1 + ph (dispNext win e).st
  cases hs : e.st with
  | idle =>
    cases hw : win e with
    | none => exact absurd hw (hws hs)
    | some w =>
      by_cases hv : e.headValid w = true
      · have hwi : w ≠ i := by
          rintro rfl
          exact hnd ⟨hs, hw, hv⟩
        have hd : decOther win i e = true := by simp [decOther, hw, hs, hwi, hv]
        have hst : stallB win e = false := by simp [stallB, hw, hs, hv]
        simp [hd, hst, dispNext, hs, hw, hv, ph]
      · have hv' : e.headValid w = false := by
          cases h' : e.headValid w
          · rfl
          · exact absurd h' hv
        have hd : decOther win i e = false := by simp [decOther, hw, hs, hv']
        have hst : stallB win e = true := by simp [stallB, hw, hs, hv']
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

/-- Lemma A's identity with the winner required only along this wait. -/
theorem lemA_run_l (P : Program) (win : Engine → Option Lane) (i : Lane) :
    ∀ (t : Nat) (e : Engine), Ready P i e → NotMid i e →
      (∀ s, s < t → ¬Dec win i (run P win s e)) →
      (∀ s, s < t → (run P win s e).st = .idle → Ready P i (run P win s e) →
        win (run P win s e) ≠ none) →
      3 * cnt P win (fun e => decOther win i e = true) t e
        + cnt P win (fun e => stallB win e = true) t e + ph e.st
        = t + ph (run P win t e).st
  | 0, e, _, _, _, _ => by simp [cnt, run]
  | t + 1, e, hr, hm, hnd, hws => by
    have hnd0 : ¬Dec win i e := hnd 0 (Nat.succ_pos t)
    have h1 := lemA_step_l P win i e (fun hs => hws 0 (Nat.succ_pos t) hs hr) hnd0
    have ih := lemA_run_l P win i t (step P win e) (ready_step P win i e hr hm)
      (notMid_step P win i e hm hnd0)
      (fun s hs => hnd (s + 1) (Nat.succ_lt_succ hs))
      (fun s hs => hws (s + 1) (Nat.succ_lt_succ hs))
    have e1 : cnt P win (fun e => decOther win i e = true) (t + 1) e
        = (if decOther win i e = true then 1 else 0)
          + cnt P win (fun e => decOther win i e = true) t (step P win e) := rfl
    have e2 : cnt P win (fun e => stallB win e = true) (t + 1) e
        = (if stallB win e = true then 1 else 0)
          + cnt P win (fun e => stallB win e = true) t (step P win e) := rfl
    have e3 : run P win (t + 1) e = run P win t (step P win e) := rfl
    rw [e3]
    omega

/-- **Lemma A under (b′).** A lane that waits `t` cycles ready and undecided, with its head
valid throughout, saw at least `(t − 2)/3` other-lane decisions — no stall term. The scheduler
need only name a winner when that lane is idle, ready and head-valid. -/
theorem lemmaA_b (P : Program) (win : Engine → Option Lane) (i : Lane) (hb : BPrimeWin win)
    (hws : ∀ e, e.st = .idle → Ready P i e → e.headValid i = true → win e ≠ none)
    (t : Nat) (e : Engine) (hr : Ready P i e) (hm : NotMid i e)
    (hnd : ∀ s, s < t → ¬Dec win i (run P win s e))
    (hv : ∀ s, s < t → (run P win s e).headValid i = true) :
    t ≤ 3 * cnt P win (fun e => decOther win i e = true) t e + 2 := by
  have h := lemA_run_l P win i t e hr hm hnd (fun s hs hid hrs => hws _ hid hrs (hv s hs))
  have h0 := cnt_stall_bprime P win hb t e
  have h2 := ph_le e.st
  omega

#print axioms stall_free_bprime
#print axioms lemmaA_b

end JLane
