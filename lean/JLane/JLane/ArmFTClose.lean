import JLane.FlushLate
import JLane.ArmFT
/-!
# Brick F6 — the FALLTHROUGH results on the engine itself (Nate/Wilson 11-14, order 2)

The guarantees for runs with FALLTHROUGH ARMs were assembled from three pieces: the run map
(`ArmFT.run3T_proj`), the response bound on flush runs (`RespWinF.wb_bound_winF`) and the
refill lateness (`FlushLate.flush_head_late`). Here they are stated **on the engine with ARM
registers** (`run3T`), each one citation:

* `invF_run3T` — the flush invariant holds along the whole run, given it holds at the start: a
  flushed lane is armed, and an armed lane is never dispatched (`hmidT`);
* `wb_bound_T` — every writeback of a lane never flushed (every lane but the USB lane) lands
  within `K + 1` of its release, under the window budget (`M` other decisions, `S` idle cycles
  with no decision, disarms included, `K ≥ 3M + S + 3`);
* `flush_head_late_T` — after a FALLTHROUGH edge, the lane's release is the next cycle and its
  head (PC+2) is valid by that release plus `FLUSH_REFILL_LATE + B`.
-/
namespace JLane

theorem wd_some (X : EngineT) (w : Option Lane) (v : Lane) (h : X.wd w = some v) :
    X.armed v = false := by
  unfold EngineT.wd at h
  cases w with
  | none => cases h
  | some u =>
    by_cases hu : X.armed u = true
    · simp [hu] at h
    · have hu' : X.armed u = false := by cases hc : X.armed u <;> simp_all
      simp [hu'] at h
      rw [← h]
      exact hu'

/-- A flushed lane is never the one dispatched next. -/
theorem hmidT (Wn : Nat) (Y : EngineT) (h : InvT Wn Y) (w : Option Lane) (l : Lane)
    (hl : Y.fl l = true) :
    ¬((dispNext (fun _ => Y.wd w) (πT Y)).st ≠ .idle ∧
      (dispNext (fun _ => Y.wd w) (πT Y)).cur = l) := by
  have ha : Y.armed l = true := by
    unfold EngineT.fl EngineT.hit at hl
    simp only [Bool.and_eq_true] at hl
    exact hl.1.1
  rintro ⟨hst, hcur⟩
  change (dispNext (fun _ => Y.wd w) Y.x.e).st ≠ .idle at hst
  change (dispNext (fun _ => Y.wd w) Y.x.e).cur = l at hcur
  cases hs : Y.x.e.st with
  | idle =>
    cases hwo : Y.wd w with
    | none => simp [dispNext, hs, hwo] at hst
    | some v =>
      by_cases hv : Y.x.e.headValid v = true
      · simp [dispNext, hs, hwo, hv] at hcur
        have := wd_some Y w v hwo
        rw [hcur, ha] at this
        cases this
      · simp [dispNext, hs, hwo, hv] at hst
  | drive =>
    simp [dispNext, hs] at hcur
    exact h.2.2.2.1 l ha ⟨by rw [hs]; decide, hcur⟩
  | wb => simp [dispNext, hs] at hst

theorem winT_at (P2 : Program2) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
    (sched : EngineT → Option Lane) (X0 : EngineT) (n : Nat) :
    winT P2 fw edge sched X0 (πT (run3T P2 fw edge sched n X0)) =
      (run3T P2 fw edge sched n X0).wd (sched (run3T P2 fw edge sched n X0)) := by
  have hk : (run3T P2 fw edge sched n X0).x.e.now - X0.x.e.now = n := by
    rw [now_run3T]
    omega
  show (run3T P2 fw edge sched ((run3T P2 fw edge sched n X0).x.e.now - X0.x.e.now) X0).wd
    (sched (run3T P2 fw edge sched ((run3T P2 fw edge sched n X0).x.e.now - X0.x.e.now) X0)) = _
  rw [hk]

theorem flR_at (P2 : Program2) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
    (sched : EngineT → Option Lane) (X0 : EngineT) (n : Nat) :
    flR P2 fw edge sched X0 (run3T P2 fw edge sched n X0).x.e.now =
      (run3T P2 fw edge sched n X0).fl := by
  have hk : (run3T P2 fw edge sched n X0).x.e.now - X0.x.e.now = n := by
    rw [now_run3T]
    omega
  show (run3T P2 fw edge sched ((run3T P2 fw edge sched n X0).x.e.now - X0.x.e.now) X0).fl = _
  rw [hk]

section
variable (P2 : Program2) (Wn : Nat) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
  (hedge : ∀ t l, t + 1 ≤ edge t l) (sched : EngineT → Option Lane) (X0 : EngineT)
  (hX0 : InvT Wn X0) (hf : ∀ y, ArmFragT Wn (fw y)) (hsw : SchedT sched)

include hedge hX0 hf hsw in
theorem runF_e (n : Nat) :
    (runF (armPT P2 fw edge sched X0) (winT P2 fw edge sched X0) (flR P2 fw edge sched X0) n
      (πF X0)).e = πT (run3T P2 fw edge sched n X0) := by
  rw [← run3T_proj P2 Wn fw edge hedge sched X0 hX0 hf hsw n]
  rfl

include hedge hX0 hf hsw in
/-- No lane flushed in a cycle of the run is dispatched next. -/
theorem hmid_run (n : Nat) (l : Lane)
    (hl : flR P2 fw edge sched X0 (runF (armPT P2 fw edge sched X0) (winT P2 fw edge sched X0)
      (flR P2 fw edge sched X0) n (πF X0)).e.now l = true) :
    ¬((dispNext (winT P2 fw edge sched X0) (runF (armPT P2 fw edge sched X0)
        (winT P2 fw edge sched X0) (flR P2 fw edge sched X0) n (πF X0)).e).st ≠ .idle ∧
      (dispNext (winT P2 fw edge sched X0) (runF (armPT P2 fw edge sched X0)
        (winT P2 fw edge sched X0) (flR P2 fw edge sched X0) n (πF X0)).e).cur = l) := by
  rw [runF_e P2 Wn fw edge hedge sched X0 hX0 hf hsw n] at hl ⊢
  change flR P2 fw edge sched X0 (run3T P2 fw edge sched n X0).x.e.now l = true at hl
  rw [flR_at] at hl
  show ¬((dispNext (fun _ => winT P2 fw edge sched X0 (πT (run3T P2 fw edge sched n X0)))
      (πT (run3T P2 fw edge sched n X0))).st ≠ .idle ∧
    (dispNext (fun _ => winT P2 fw edge sched X0 (πT (run3T P2 fw edge sched n X0)))
      (πT (run3T P2 fw edge sched n X0))).cur = l)
  rw [winT_at]
  exact hmidT Wn _ (invT_run P2 Wn fw edge hedge sched hf hsw n X0 hX0) _ l hl

include hedge hX0 hf hsw in
/-- **The flush invariant along a run with FALLTHROUGH ARMs.** -/
theorem invF_run3T (hI0 : InvF (πF X0)) :
    ∀ n, InvF (runF (armPT P2 fw edge sched X0) (winT P2 fw edge sched X0)
      (flR P2 fw edge sched X0) n (πF X0))
  | 0 => hI0
  | n + 1 => by
    rw [runF_succ']
    exact invF_step _ _ _ _ (invF_run3T hI0 n)
      (hmid_run P2 Wn fw edge hedge sched X0 hX0 hf hsw n)

include hedge hX0 hf hsw in
/-- **Response bound, FALLTHROUGH, on the engine.** A lane `y` never flushed: every writeback
lands within `K + 1` of its release (the view's, `relT`), under the window budget. -/
theorem wb_bound_T (h0 : X0.x.e.st = .idle) (h0ts : ∀ l, X0.x.e.now ≤ relT X0 l) (y : Lane)
    (hy : P2.live y = true) (hfy : ∀ n, (run3T P2 fw edge sched n X0).fl y = false)
    (M S K : Nat) (hK : 3 * M + S + 3 ≤ K) (t : Nat)
    (hwb : IsWB y (πT (run3T P2 fw edge sched t X0)))
    (hfree : ∀ w, w + 2 < t → IsWB y (πT (run3T P2 fw edge sched w X0)) →
      (run3T P2 fw edge sched w X0).x.e.now < relT (run3T P2 fw edge sched t X0) y)
    (hM : ∀ c, c + K + 2 ≤ t →
      cntF (armPT P2 fw edge sched X0) (winT P2 fw edge sched X0) (flR P2 fw edge sched X0)
        (fun e => decOther (winT P2 fw edge sched X0) y e = true) K
        (πF (run3T P2 fw edge sched c X0)) ≤ M)
    (hS : ∀ c, c + K + 2 ≤ t →
      cntF (armPT P2 fw edge sched X0) (winT P2 fw edge sched X0) (flR P2 fw edge sched X0)
        (fun e => noDecB (winT P2 fw edge sched X0) e = true) K
        (πF (run3T P2 fw edge sched c X0)) ≤ S) :
    (run3T P2 fw edge sched t X0).x.e.now ≤ relT (run3T P2 fw edge sched t X0) y + K + 1 := by
  have hpr := run3T_proj P2 Wn fw edge hedge sched X0 hX0 hf hsw
  have hE := runF_e P2 Wn fw edge hedge sched X0 hX0 hf hsw
  have hfy' : ∀ t, flR P2 fw edge sched X0 t y = false := fun _ => hfy _
  have key := wb_bound_winF (armPT P2 fw edge sched X0) (winT P2 fw edge sched X0)
    (flR P2 fw edge sched X0) (πF X0) h0 h0ts y hy hfy' M S K hK t
    (by rw [hE]; exact hwb)
    (fun w hw h => by
      rw [hE] at h
      rw [hE, hE]
      exact hfree w hw h)
    (fun c hc => by rw [← hpr]; exact hM c hc)
    (fun c hc => by rw [← hpr]; exact hS c hc)
  rw [hE] at key
  exact key

include hedge hX0 hf hsw in
/-- **The refill after a FALLTHROUGH edge, on the engine.** If lane `y`'s FALLTHROUGH edge fires
at cycle `f` and no other flush comes in the next `3 + 23 + B` cycles, `y` is released the cycle
after the edge and its head (PC+2) is valid by that release plus `FLUSH_REFILL_LATE + B`. -/
theorem flush_head_late_T (hI0 : InvF (πF X0)) (y : Lane) (B f : Nat) (hy : P2.live y = true)
    (hfy : (run3T P2 fw edge sched f X0).fl y = true)
    (hnof : ∀ i, 1 ≤ i → i ≤ 3 + (23 + B) → ∀ l, (run3T P2 fw edge sched (f + i) X0).fl l = false)
    (hB : ∀ m, m ≤ 23 + B → chargeSum (armPT P2 fw edge sched X0) (winT P2 fw edge sched X0) y m
      (πT (run3T P2 fw edge sched (f + 3) X0)) ≤ B) :
    relT (run3T P2 fw edge sched (f + 1) X0) y = (run3T P2 fw edge sched f X0).x.e.now + 1 ∧
    ∃ j, (run3T P2 fw edge sched (f + 3 + j) X0).x.e.headValid y = true ∧
      (run3T P2 fw edge sched (f + 3 + j) X0).x.e.now ≤
        relT (run3T P2 fw edge sched (f + 1) X0) y + FLUSH_REFILL_LATE + B := by
  have hE := runF_e P2 Wn fw edge hedge sched X0 hX0 hf hsw
  have hnow : ∀ n, (runF (armPT P2 fw edge sched X0) (winT P2 fw edge sched X0)
      (flR P2 fw edge sched X0) n (πF X0)).e.now = (run3T P2 fw edge sched n X0).x.e.now := by
    intro n
    rw [hE]
    rfl
  have hfy' : flR P2 fw edge sched X0 (runF (armPT P2 fw edge sched X0)
      (winT P2 fw edge sched X0) (flR P2 fw edge sched X0) f (πF X0)).e.now y = true := by
    rw [hnow, flR_at]
    exact hfy
  have hnof' : ∀ i, 1 ≤ i → i ≤ 3 + (23 + B) → ∀ l, flR P2 fw edge sched X0
      ((runF (armPT P2 fw edge sched X0) (winT P2 fw edge sched X0)
        (flR P2 fw edge sched X0) f (πF X0)).e.now + i) l = false := by
    intro i h1 h2 l
    have hk : (runF (armPT P2 fw edge sched X0) (winT P2 fw edge sched X0)
        (flR P2 fw edge sched X0) f (πF X0)).e.now + i =
        (run3T P2 fw edge sched (f + i) X0).x.e.now := by
      rw [hnow, now_run3T, now_run3T]
      omega
    rw [hk, flR_at]
    exact hnof i h1 h2 l
  obtain ⟨hts, j, hv, hle⟩ := flush_head_late (armPT P2 fw edge sched X0)
    (winT P2 fw edge sched X0) (flR P2 fw edge sched X0) (πF X0) y B f hy
    (invF_run3T P2 Wn fw edge hedge sched X0 hX0 hf hsw hI0 f)
    (hmid_run P2 Wn fw edge hedge sched X0 hX0 hf hsw f) hfy' hnof'
    (fun m hm => by rw [hE]; exact hB m hm)
  rw [hE, hE] at hts
  rw [hE] at hv
  rw [hE, hE] at hle
  exact ⟨hts, j, hv, hle⟩

end

#print axioms invF_run3T
#print axioms wb_bound_T
#print axioms flush_head_late_T

end JLane
