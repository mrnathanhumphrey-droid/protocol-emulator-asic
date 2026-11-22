import JLane.ArmFTClose
/-!
# Brick F8 — the priority lane's response on the flush run (the usbdev USB lane)

`PrioResp.prio_resp` bounds the USB lane's writebacks by `L + 4` past its release, on `run`. On
`usbdev_dev` / `usbdev_fpga` the USB lane carries the FALLTHROUGH ARM, so it is the lane the
flush run (`runF`, the view of `run3T`) flushes: its edge sets `ts := now + 1`. `prio_resp`'s proof
reads the timestamp as moving only at a writeback (`ts_mono`, `ts_const`, `dec_ts`); here each
use is re-derived with flushes (Wilson 11-21, usbdev ruling: `wb_close_spanT`'s `hRz`):

* **a flush never lowers the view's release** (`relT_le_fl`): a flush is a hit of an armed lane,
  `now = armE`, and an armed lane's view release is its deadline (when `≤ armE`) or `armE + 1` —
  at most `now + 1`, which the flush sets. So the release is monotone (`ts_monoF_fl`);
* **no flush between the decision and its writeback**: a flushed lane is never the one
  dispatched (`ArmFTClose.hmid_run`), so `dec_ts` holds;
* **no flush while the lane waits**: a flush at `w` would put the release past `now w`, but the
  window is where the job is already `L` past its release;
* the rest is `prio_resp`'s argument (`idle3F`: the dispatcher idles within three cycles).

`prio_respT` states it on the engine with ARM registers, `hfl` / `hmid` discharged.
-/
namespace JLane

/-- **A flush never lowers the view's release**: at a FALLTHROUGH edge, the view releases the
lane at most one past now. -/
theorem relT_le_fl (X : EngineT) (l : Lane) (h : X.fl l = true) : relT X l ≤ X.x.e.now + 1 := by
  unfold EngineT.fl EngineT.hit at h
  have ha : X.armed l = true := by
    cases h1 : X.armed l <;> simp_all
  have he : X.x.e.now = X.armE l := by
    cases h1 : X.armed l <;> simp_all
  unfold relT
  rw [if_pos ha]
  split
  · rename_i hc
    have := hc.2
    omega
  · omega

/-- One step with flushes keeps a lane's release from dropping, given a flush of it comes no
earlier than its release minus one. -/
theorem ts_stepF_ge (P : Program) (win : Engine → Option Lane) (f : Lane → Bool) (X : EngineF)
    (y : Lane) (h : f y = true → X.e.ts y ≤ X.e.now + 1) :
    X.e.ts y ≤ (stepF P win f X).e.ts y := by
  show X.e.ts y ≤ tsF P f X.e y
  unfold tsF
  cases hf : f y with
  | true => rw [if_pos rfl]; exact h hf
  | false => rw [if_neg (by simp)]; exact tsNext_ge P X.e y

/-- **The release is monotone along `runF`** for a lane whose flushes never lower it. -/
theorem ts_monoF_fl (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool)
    (y : Lane) (X : EngineF)
    (hfl : ∀ n, fl (runF P win fl n X).e.now y = true →
      (runF P win fl n X).e.ts y ≤ (runF P win fl n X).e.now + 1) :
    ∀ m k, (runF P win fl m X).e.ts y ≤ (runF P win fl (m + k) X).e.ts y
  | _, 0 => Nat.le_refl _
  | m, k + 1 => by
    rw [← Nat.add_assoc, runF_succ' P win fl (m + k)]
    exact Nat.le_trans (ts_monoF_fl P win fl y X hfl m k)
      (ts_stepF_ge P win _ _ y (hfl (m + k)))

/-- A flush sets the release one past now. -/
theorem ts_flushF (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool) (y : Lane)
    (X : EngineF) (n : Nat) (h : fl (runF P win fl n X).e.now y = true) :
    (runF P win fl (n + 1) X).e.ts y = (runF P win fl n X).e.now + 1 := by
  rw [runF_succ']
  show tsF P _ _ y = _
  unfold tsF
  rw [if_pos h]

/-- No writeback and no flush of `y` this cycle: its release holds. -/
theorem ts_flatF1 (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool) (y : Lane)
    (X : EngineF) (n : Nat) (hf : fl (runF P win fl n X).e.now y = false)
    (h : ¬IsWB y (runF P win fl n X).e) :
    (runF P win fl (n + 1) X).e.ts y = (runF P win fl n X).e.ts y := by
  rw [runF_succ', stepF_ts_y P win _ _ y hf]
  unfold tsNext
  rw [if_neg (fun h' => h ⟨h'.1, h'.2.symm⟩)]

theorem ts_constF (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool) (y : Lane)
    (X : EngineF) (s : Nat) :
    ∀ k, (∀ i, i < k → ¬IsWB y (runF P win fl (s + i) X).e ∧
        fl (runF P win fl (s + i) X).e.now y = false) →
      (runF P win fl (s + k) X).e.ts y = (runF P win fl s X).e.ts y
  | 0, _ => rfl
  | k + 1, h => by
    have ih := ts_constF P win fl y X s k (fun i hi => h i (by omega))
    rw [← Nat.add_assoc, ts_flatF1 P win fl y X (s + k) (h k (by omega)).2 (h k (by omega)).1, ih]

/-- The dispatcher idles within three cycles, along `runF`. -/
theorem idle3F (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool) (X0 : EngineF)
    (c : Nat) : ∃ s, c ≤ s ∧ s ≤ c + 2 ∧ (runF P win fl s X0).e.st = .idle := by
  cases hs : (runF P win fl c X0).e.st with
  | idle => exact ⟨c, Nat.le_refl c, by omega, hs⟩
  | wb =>
    refine ⟨c + 1, by omega, by omega, ?_⟩
    rw [runF_succ']
    exact step_wb_idle P win _ hs
  | drive =>
    refine ⟨c + 2, by omega, Nat.le_refl _, ?_⟩
    have h1 : (runF P win fl (c + 1) X0).e.st = .wb := by
      rw [runF_succ']
      exact (step_drive P win (runF P win fl c X0).e hs).1
    show (runF P win fl ((c + 1) + 1) X0).e.st = .idle
    rw [runF_succ' P win fl (c + 1)]
    exact step_wb_idle P win _ h1

/-- **The priority lane's response on the flush run.** As `prio_resp`, for a lane the run may
flush: its flushes never lower its release (`hfl`) and never hit it while it is dispatched
(`hmid`). -/
theorem prio_respF (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool)
    (X0 : EngineF) (h0 : X0.e.st = .idle) (u : Lane) (h0u : X0.e.now ≤ X0.e.ts u)
    (hu : P.live u = true) (L t : Nat)
    (hfl : ∀ n, fl (runF P win fl n X0).e.now u = true →
      (runF P win fl n X0).e.ts u ≤ (runF P win fl n X0).e.now + 1)
    (hmid : ∀ n, fl (runF P win fl n X0).e.now u = true →
      ¬((runF P win fl (n + 1) X0).e.st ≠ .idle ∧ (runF P win fl (n + 1) X0).e.cur = u))
    (hpri : ∀ s, s < t → (runF P win fl s X0).e.st = .idle → Ready P u (runF P win fl s X0).e →
      (runF P win fl s X0).e.headValid u = true → win (runF P win fl s X0).e = some u)
    (hwb : IsWB u (runF P win fl t X0).e)
    (hfree : ∀ w, w + 2 < t → IsWB u (runF P win fl w X0).e →
      (runF P win fl w X0).e.now < (runF P win fl t X0).e.ts u)
    (hhv : ∀ c, c < t → (runF P win fl c X0).e.ts u = (runF P win fl t X0).e.ts u →
      (runF P win fl t X0).e.ts u + L ≤ (runF P win fl c X0).e.now →
      (runF P win fl c X0).e.headValid u = true) :
    (runF P win fl t X0).e.now ≤ (runF P win fl t X0).e.ts u + L + 4 := by
  obtain ⟨D, rfl, hdec⟩ := wb_backF P win fl X0 h0 t u hwb
  -- no flush of u at its decision or the cycle after: it is being dispatched
  have hd1 : (runF P win fl (D + 1) X0).e.st = .drive ∧ (runF P win fl (D + 1) X0).e.cur = u := by
    rw [runF_succ']
    exact step_of_dec P win _ u hdec
  have hd2 := dec_wbF P win fl X0 D u hdec
  have nf0 : fl (runF P win fl D X0).e.now u = false := by
    cases h : fl (runF P win fl D X0).e.now u with
    | false => rfl
    | true => exact absurd ⟨by rw [hd1.1]; decide, hd1.2⟩ (hmid D h)
  have nf1 : fl (runF P win fl (D + 1) X0).e.now u = false := by
    cases h : fl (runF P win fl (D + 1) X0).e.now u with
    | false => rfl
    | true => exact absurd ⟨by rw [hd2.1]; decide, hd2.2⟩ (hmid (D + 1) h)
  have hidle : (runF P win fl D X0).e.st = .idle := hdec.1
  have t1 := ts_flatF1 P win fl u X0 D nf0 (not_wb_of_st u _ (by rw [hidle]; decide))
  have t2 := ts_flatF1 P win fl u X0 (D + 1) nf1 (not_wb_of_st u _ (by rw [hd1.1]; decide))
  have hts2 : (runF P win fl (D + 2) X0).e.ts u = (runF P win fl D X0).e.ts u := by
    show (runF P win fl (D + 1 + 1) X0).e.ts u = _
    rw [t2, t1]
  have hnow2 := now_runF P win fl (D + 2) X0
  have hnD := now_runF P win fl D X0
  rw [hts2]
  rw [hts2] at hfree hhv
  by_cases hfit : (runF P win fl D X0).e.now ≤ (runF P win fl D X0).e.ts u + L + 2
  · omega
  · exfalso
    have hts0 := ts_monoF_fl P win fl u X0 hfl 0 D
    have h00 : (runF P win fl 0 X0).e.ts u = X0.e.ts u := rfl
    rw [Nat.zero_add] at hts0
    obtain ⟨c0, hc0⟩ : ∃ c0, X0.e.now + c0 = (runF P win fl D X0).e.ts u + L :=
      ⟨(runF P win fl D X0).e.ts u + L - X0.e.now, by omega⟩
    have hc0D : c0 + 3 ≤ D := by omega
    -- from c0 on, before D: no writeback of u, and no flush of u
    have noWB : ∀ w, c0 ≤ w → w < D → ¬IsWB u (runF P win fl w X0).e := by
      intro w hw1 hw2 hw
      have h1 := hfree w (by omega) hw
      have h2 := now_runF P win fl w X0
      omega
    have noFl : ∀ w, c0 ≤ w → w < D → fl (runF P win fl w X0).e.now u = false := by
      intro w hw1 hw2
      cases h : fl (runF P win fl w X0).e.now u with
      | false => rfl
      | true =>
        exfalso
        have h1 := ts_flushF P win fl u X0 w h
        have h2 := ts_monoF_fl P win fl u X0 hfl (w + 1) (D - (w + 1))
        rw [show w + 1 + (D - (w + 1)) = D by omega] at h2
        have h3 := now_runF P win fl w X0
        omega
    obtain ⟨s, hs1, hs2, hsidle⟩ := idle3F P win fl X0 c0
    have hns := now_runF P win fl s X0
    have hconst := ts_constF P win fl u X0 s (D - s)
      (fun i hi => ⟨noWB (s + i) (by omega) (by omega), noFl (s + i) (by omega) (by omega)⟩)
    rw [show s + (D - s) = D by omega] at hconst
    have hrdy : Ready P u (runF P win fl s X0).e := ⟨hu, by omega⟩
    have hv := hhv s (by omega) hconst.symm (by omega)
    have hdec' : Dec win u (runF P win fl s X0).e := ⟨hsidle, hpri s (by omega) hsidle hrdy hv, hv⟩
    have hw2 := dec_wbF P win fl X0 s u hdec'
    rcases Nat.lt_or_ge (s + 2) D with hlt | hge
    · exact noWB (s + 2) (by omega) hlt hw2
    · have hst1 : (runF P win fl (s + 1) X0).e.st = .drive := by
        rw [runF_succ']
        exact (step_of_dec P win _ u hdec').1
      have hst2 : (runF P win fl (s + 2) X0).e.st = .wb := hw2.1
      have : D = s + 1 ∨ D = s + 2 := by omega
      rcases this with h | h
      · rw [h, hst1] at hidle
        cases hidle
      · rw [h, hst2] at hidle
        cases hidle

section
variable (P2 : Program2) (Wn : Nat) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
  (hedge : ∀ t l, t + 1 ≤ edge t l) (sched : EngineT → Option Lane) (X0 : EngineT)
  (hX0 : InvT Wn X0) (hf : ∀ y, ArmFragT Wn (fw y)) (hsw : SchedT sched)

include hedge hX0 hf hsw in
/-- **The priority lane's response on the FALLTHROUGH engine** (the usbdev USB lane, flushed at
its edge): every writeback within `L + 4` of its view release (`relT`). The flush conditions
are discharged (`relT_le_fl`, `hmid_run`); `hpri`, `hfree`, `hhv` are `prio_resp`'s. -/
theorem prio_respT (h0 : X0.x.e.st = .idle) (u : Lane) (h0u : X0.x.e.now ≤ relT X0 u)
    (hu : (armPT P2 fw edge sched X0).live u = true) (L t : Nat)
    (hpri : ∀ s, s < t → (run3T P2 fw edge sched s X0).x.e.st = .idle →
      Ready (armPT P2 fw edge sched X0) u (πT (run3T P2 fw edge sched s X0)) →
      (run3T P2 fw edge sched s X0).x.e.headValid u = true →
      winT P2 fw edge sched X0 (πT (run3T P2 fw edge sched s X0)) = some u)
    (hwb : IsWB u (πT (run3T P2 fw edge sched t X0)))
    (hfree : ∀ w, w + 2 < t → IsWB u (πT (run3T P2 fw edge sched w X0)) →
      (run3T P2 fw edge sched w X0).x.e.now < relT (run3T P2 fw edge sched t X0) u)
    (hhv : ∀ c, c < t → relT (run3T P2 fw edge sched c X0) u = relT (run3T P2 fw edge sched t X0) u →
      relT (run3T P2 fw edge sched t X0) u + L ≤ (run3T P2 fw edge sched c X0).x.e.now →
      (run3T P2 fw edge sched c X0).x.e.headValid u = true) :
    (run3T P2 fw edge sched t X0).x.e.now ≤ relT (run3T P2 fw edge sched t X0) u + L + 4 := by
  have hE := runF_e P2 Wn fw edge hedge sched X0 hX0 hf hsw
  have key := prio_respF (armPT P2 fw edge sched X0) (winT P2 fw edge sched X0)
    (flR P2 fw edge sched X0) (πF X0) h0 u h0u hu L t
    (fun n h => by
      rw [hE] at h ⊢
      change flR P2 fw edge sched X0 (run3T P2 fw edge sched n X0).x.e.now u = true at h
      rw [flR_at] at h
      exact relT_le_fl _ u h)
    (fun n h => by
      have hm := hmid_run P2 Wn fw edge hedge sched X0 hX0 hf hsw n u h
      rw [runF_succ']
      exact hm)
    (fun s hs hst hr hv => by
      rw [hE] at hst hr hv ⊢
      exact hpri s hs hst hr hv)
    (by rw [hE]; exact hwb)
    (fun w hw h => by
      rw [hE] at h ⊢
      rw [hE]
      exact hfree w hw h)
    (fun c hc heq hle => by
      rw [hE, hE] at heq
      rw [hE, hE] at hle
      rw [hE]
      exact hhv c hc heq hle)
  rw [hE] at key
  exact key

end

end JLane
