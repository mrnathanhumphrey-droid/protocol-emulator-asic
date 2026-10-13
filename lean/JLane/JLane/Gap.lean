import JLane.Pigeon
/-!
# Brick 12 — the gap
The dispatch FSM forwards and backwards, timestamp monotonicity, and the gap between
two decisions of the same lane: if `z` is decided at `a` and again at `b`, then
`now(b) ≥ ts_z(a) + d_z`; with `now(a) ≤ ts_z(a) + R`, `b − a ≥ d_z − R`.
-/
namespace JLane

/-! ### The dispatch FSM, forwards -/

theorem step_of_dec (P : Program) (win : Engine → Option Lane) (e : Engine) (w : Lane)
    (h : Dec win w e) : (step P win e).st = .drive ∧ (step P win e).cur = w := by
  obtain ⟨hs, hw, hv⟩ := h
  constructor
  · show (dispNext win e).st = .drive
    simp [dispNext, hs, hw, hv]
  · show (dispNext win e).cur = w
    simp [dispNext, hs, hw, hv]

theorem step_drive (P : Program) (win : Engine → Option Lane) (e : Engine)
    (h : e.st = .drive) : (step P win e).st = .wb ∧ (step P win e).cur = e.cur := by
  constructor
  · show (dispNext win e).st = .wb
    simp [dispNext, h]
  · show (dispNext win e).cur = e.cur
    simp [dispNext, h]

/-- A decision at `a` is written back at `a + 2`. -/
theorem dec_wb (P : Program) (win : Engine → Option Lane) (e : Engine) (a : Nat) (w : Lane)
    (h : Dec win w (run P win a e)) : IsWB w (run P win (a + 2) e) := by
  obtain ⟨h1, h2⟩ := step_of_dec P win (run P win a e) w h
  obtain ⟨h3, h4⟩ := step_drive P win (step P win (run P win a e)) h1
  show (run P win (a + 1 + 1) e).st = .wb ∧ (run P win (a + 1 + 1) e).cur = w
  rw [run_succ', run_succ']
  exact ⟨h3, h4.trans h2⟩

/-! ### The dispatch FSM, backwards -/

theorem back_wb (P : Program) (win : Engine → Option Lane) (e : Engine)
    (h : (step P win e).st = .wb) : e.st = .drive ∧ (step P win e).cur = e.cur := by
  change (dispNext win e).st = .wb at h
  cases hs : e.st with
  | idle =>
    exfalso
    cases hw : win e with
    | none => simp [dispNext, hs, hw] at h
    | some w =>
      by_cases hv : e.headValid w = true
      · simp [dispNext, hs, hw, hv] at h
      · simp [dispNext, hs, hw, hv] at h
  | drive => exact ⟨rfl, (step_drive P win e hs).2⟩
  | wb =>
    exfalso
    simp [dispNext, hs] at h

theorem back_drive (P : Program) (win : Engine → Option Lane) (e : Engine)
    (h : (step P win e).st = .drive) : Dec win (step P win e).cur e := by
  change (dispNext win e).st = .drive at h
  show Dec win (dispNext win e).cur e
  cases hs : e.st with
  | idle =>
    cases hw : win e with
    | none => simp [dispNext, hs, hw] at h
    | some w =>
      by_cases hv : e.headValid w = true
      · have hc : (dispNext win e).cur = w := by simp [dispNext, hs, hw, hv]
        rw [hc]
        exact ⟨hs, hw, hv⟩
      · simp [dispNext, hs, hw, hv] at h
  | drive => simp [dispNext, hs] at h
  | wb => simp [dispNext, hs] at h

/-- A writeback at `t` comes from a decision of the same lane at `t − 2`. -/
theorem wb_back (P : Program) (win : Engine → Option Lane) (e0 : Engine)
    (h0 : e0.st = .idle) (t : Nat) (y : Lane) (hwb : IsWB y (run P win t e0)) :
    ∃ s, t = s + 2 ∧ Dec win y (run P win s e0) := by
  obtain ⟨hst, hcur⟩ := hwb
  cases t with
  | zero =>
    have h : (run P win 0 e0).st = .idle := h0
    rw [h] at hst
    cases hst
  | succ t =>
    rw [run_succ'] at hst hcur
    obtain ⟨hd, hc⟩ := back_wb P win (run P win t e0) hst
    cases t with
    | zero =>
      have h : (run P win 0 e0).st = .idle := h0
      rw [h] at hd
      cases hd
    | succ s =>
      rw [run_succ'] at hd hc hcur
      have hdec := back_drive P win (run P win s e0) hd
      refine ⟨s, rfl, ?_⟩
      rw [hc] at hcur
      rw [← hcur]
      exact hdec

/-! ### Timestamps -/

theorem ts_mono (P : Program) (win : Engine → Option Lane) (y : Lane) (e : Engine)
    (m n : Nat) (h : m ≤ n) : (run P win m e).ts y ≤ (run P win n e).ts y := by
  have h1 := ts_spacing P win y e m (n - m)
  have hmn : m + (n - m) = n := by omega
  rw [hmn] at h1
  omega

/-- A writeback advances the timestamp by the lane's minimum delay plus that writeback's
extra. -/
theorem ts_after_wb (P : Program) (win : Engine → Option Lane) (y : Lane) (e : Engine)
    (t : Nat) (h : IsWB y (run P win t e)) :
    (run P win (t + 1) e).ts y
      = (run P win t e).ts y + P.dly y + P.ext (run P win t e).now y := by
  rw [run_succ', ts_step, if_pos h, Nat.add_assoc]

/-! ### The gap -/

/-- Two decisions of the same lane: the second is at or past the next release. -/
theorem dec_gap (P : Program) (win : Engine → Option Lane) (e : Engine) (z : Lane)
    (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
    (a b : Nat) (hab : a < b) (ha : Dec win z (run P win a e))
    (hb : Dec win z (run P win b e)) :
    (run P win a e).ts z + P.dly z ≤ (run P win b e).now := by
  obtain ⟨hbi, hbw, _⟩ := hb
  have hst1 : (run P win (a + 1) e).st = .drive := by
    rw [run_succ']
    exact (step_of_dec P win _ z ha).1
  have hwb := dec_wb P win e a z ha
  have hst2 : (run P win (a + 2) e).st = .wb := by
    obtain ⟨h, _⟩ := hwb
    exact h
  have hb3 : a + 3 ≤ b := by
    rcases Nat.lt_or_ge b (a + 3) with hlt | hge
    · exfalso
      have : b = a + 1 ∨ b = a + 2 := by omega
      rcases this with rfl | rfl
      · rw [hst1] at hbi
        cases hbi
      · rw [hst2] at hbi
        cases hbi
    · exact hge
  have hts3 := ts_after_wb P win z e (a + 2) hwb
  have hm1 := ts_mono P win z e a (a + 2) (by omega)
  have hm2 := ts_mono P win z e (a + 2 + 1) b (by omega)
  have hrdy := (hwin _ z hbw).2
  omega

/-- **The gap.** If `z`'s decision at `a` was within `R` of its release, its next decision
is at least `d_z − R` cycles later. -/
theorem dec_gap_time (P : Program) (win : Engine → Option Lane) (e : Engine) (z : Lane)
    (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
    (a b R : Nat) (hab : a < b) (ha : Dec win z (run P win a e))
    (hb : Dec win z (run P win b e))
    (hR : (run P win a e).now ≤ (run P win a e).ts z + R) :
    a + P.dly z ≤ b + R := by
  have h := dec_gap P win e z hwin a b hab ha hb
  have h1 := now_run P win a e
  have h2 := now_run P win b e
  omega

end JLane
