import JLane.RespWinF
/-!
# Brick F5 — the flush refill's lateness, as a number (FALLTHROUGH)

`FlushRestart.flush_head_refill` gives a capture for the flushed lane within `3 + (23 + B)` cycles;
here that becomes the number the checker uses: **the flushed lane's head is valid by its release
plus `FLUSH_REFILL_LATE + B`** (`FLUSH_REFILL_LATE = (L_REFILL - 1) + 23 - 1 = 25`: the port's
three cycles back to a clean state, the one-pass window `23 + B` of `restart_hit`, less the cycle
between the flush and the release). `lane_cert` reads it through `proof_constants`
(`flush_refill_late`), which the gate compares with this constant.

* `hit_head` — a capture for a lane with an empty head fills its head (spare-fill latches the head
  slot, and the lane is not at its own writeback);
* `head_of_hits` — a run with a capture for `y` in its first `n` cycles has `y`'s head valid by `n`;
* `flush_head_late` — the corollary.
-/
namespace JLane

/-- A capture for a lane whose head is empty fills the head. -/
theorem hit_head (P : Program) (win : Engine → Option Lane) (y : Lane) (e : Engine)
    (hW : Wf e) (hh : Hit y e) (hv : e.headValid y = false) :
    (step P win e).headValid y = true := by
  obtain ⟨hS, -, hF⟩ := hW
  have hps : e.pslot = e.sel y := by
    by_cases h : e.pslot = e.sel y
    · exact h
    · exfalso
      have hne : e.pst ≠ .scan := by rw [hh.1]; decide
      have := hF hne (by rw [hh.2]; exact h)
      rw [hh.2, hv] at this
      cases this
  have hsel : (step P win e).sel y = e.sel y := by
    show selNext P e y = e.sel y
    unfold selNext
    rw [if_neg]
    rintro ⟨hw, hc, -⟩
    have := hS.2 (by rw [hw]; decide)
    rw [← hc, hv] at this
    cases this
  show (step P win e).actv y ((step P win e).sel y) = true
  rw [hsel, ← hps]
  exact hit_fills P win y e hS hh

theorem cnt_hit_exists (P : Program) (win : Engine → Option Lane) (y : Lane) :
    ∀ (n : Nat) (e : Engine), 1 ≤ cnt P win (Hit y) n e → ∃ j, j < n ∧ Hit y (run P win j e)
  | 0, _, h => by simp [cnt] at h
  | n + 1, e, h => by
    by_cases hh : Hit y e
    · exact ⟨0, Nat.succ_pos n, hh⟩
    · have h' : 1 ≤ cnt P win (Hit y) n (step P win e) := by
        have e1 : cnt P win (Hit y) (n + 1) e
            = (if Hit y e then 1 else 0) + cnt P win (Hit y) n (step P win e) := rfl
        rw [e1, if_neg hh] at h
        omega
      obtain ⟨j, hj, hj'⟩ := cnt_hit_exists P win y n (step P win e) h'
      exact ⟨j + 1, Nat.succ_lt_succ hj, hj'⟩

/-- A capture for `y` in the first `n` cycles: `y`'s head is valid by `n`. -/
theorem head_of_hits (P : Program) (win : Engine → Option Lane) (y : Lane) (e : Engine)
    (hW : Wf e) (n : Nat) (h : 1 ≤ cnt P win (Hit y) n e) :
    ∃ j, j ≤ n ∧ (run P win j e).headValid y = true := by
  obtain ⟨j, hj, hh⟩ := cnt_hit_exists P win y n e h
  cases hv : (run P win j e).headValid y
  · refine ⟨j + 1, hj, ?_⟩
    rw [run_succ']
    exact hit_head P win y _ (wf_run P win j e hW) hh hv
  · exact ⟨j, Nat.le_of_lt hj, hv⟩

/-- **The flush refill's lateness.** Under `flush_head_refill`'s conditions, the flushed lane's
head is valid at a cycle no later than its release after the flush plus `FLUSH_REFILL_LATE + B`
(its release is the cycle after the flush, `FlushStep.tsF`). -/
theorem flush_head_late (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool)
    (X : EngineF) (y : Lane) (B f : Nat) (hy : P.live y = true)
    (hI : InvF (runF P win fl f X))
    (hmid : ∀ l, fl (runF P win fl f X).e.now l = true →
      ¬((dispNext win (runF P win fl f X).e).st ≠ .idle ∧
        (dispNext win (runF P win fl f X).e).cur = l))
    (hfy : fl (runF P win fl f X).e.now y = true)
    (hnof : ∀ i, 1 ≤ i → i ≤ 3 + (23 + B) → ∀ l, fl ((runF P win fl f X).e.now + i) l = false)
    (hB : ∀ m, m ≤ 23 + B → chargeSum P win y m (runF P win fl (f + 3) X).e ≤ B) :
    (runF P win fl (f + 1) X).e.ts y = (runF P win fl f X).e.now + 1 ∧
    ∃ j, (runF P win fl (f + 3 + j) X).e.headValid y = true ∧
      (runF P win fl (f + 3 + j) X).e.now ≤
        (runF P win fl (f + 1) X).e.ts y + FLUSH_REFILL_LATE + B := by
  have hFL : FLUSH_REFILL_LATE = 25 := flush_refill_late_val
  obtain ⟨hW, hseg, hcnt⟩ := flush_head_refill P win fl X y B f hy hI hmid hfy hnof hB
  have hts : (runF P win fl (f + 1) X).e.ts y = (runF P win fl f X).e.now + 1 := by
    rw [runF_succ']
    show tsF P _ _ y = _
    simp [tsF, hfy]
  refine ⟨hts, ?_⟩
  obtain ⟨j, hj, hv⟩ := head_of_hits P win y _ hW (23 + B) hcnt
  refine ⟨j, ?_, ?_⟩
  · rw [(hseg j hj)]
    exact hv
  · have h1 := now_runF P win fl (f + 3 + j) X
    have h2 := now_runF P win fl f X
    rw [hts]
    omega

#print axioms hit_head
#print axioms head_of_hits
#print axioms flush_head_late

end JLane
