import JLane.RespWinN
/-!
# Brick F3d — the response bound on runs with flushes (FALLTHROUGH)

A run with FALLTHROUGH ARMs is a run with flushes (`ArmFT.run3T_proj`): `FlushStep.runF`, whose
flushes are the FALLTHROUGH edges. `RespWinN.wb_bound_win_n` holds on V4b runs; here it is
carried over to `runF` for any lane `y` that is **never flushed** (every lane but the USB lane).

The flush step moves the dispatch FSM, the clock and an unflushed lane's timestamp exactly as
the V4b step does (`stepF` takes `st`, `cur`, `now` from `step`, and `tsF` is `tsNext` off the
flushed lanes), so the dispatch lemmas carry over by definition and Lemma A (`lemmaA_n`) with
them. A flush of another lane can only change which decisions happen (a winner's head emptied:
a no-decision cycle), and those are what `S` counts.
-/
namespace JLane

/-- `cnt` along a run with flushes. -/
def cntF (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool)
    (Q : Engine → Prop) [DecidablePred Q] : Nat → EngineF → Nat
  | 0, _ => 0
  | n + 1, X => (if Q X.e then 1 else 0) + cntF P win fl Q n (stepF P win (fl X.e.now) X)

theorem stepF_ts_y (P : Program) (win : Engine → Option Lane) (f : Lane → Bool) (X : EngineF)
    (y : Lane) (h : f y = false) : (stepF P win f X).e.ts y = tsNext P X.e y := by
  show tsF P f X.e y = _
  simp [tsF, h]

theorem tsNext_ge (P : Program) (e : Engine) (y : Lane) : e.ts y ≤ tsNext P e y := by
  unfold tsNext
  split <;> omega

theorem ts_monoF (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool) (y : Lane)
    (hfy : ∀ t, fl t y = false) (X : EngineF) :
    ∀ m k, (runF P win fl m X).e.ts y ≤ (runF P win fl (m + k) X).e.ts y
  | _, 0 => Nat.le_refl _
  | m, k + 1 => by
    rw [← Nat.add_assoc, runF_succ', stepF_ts_y P win _ _ y (hfy _)]
    exact Nat.le_trans (ts_monoF P win fl y hfy X m k) (tsNext_ge P _ y)

theorem ts_flatF (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool) (y : Lane)
    (hfy : ∀ t, fl t y = false) (X : EngineF) (n : Nat) (h : ¬IsWB y (runF P win fl n X).e) :
    (runF P win fl (n + 1) X).e.ts y = (runF P win fl n X).e.ts y := by
  rw [runF_succ', stepF_ts_y P win _ _ y (hfy _)]
  unfold tsNext
  rw [if_neg (fun h' => h ⟨h'.1, h'.2.symm⟩)]

/-- A decision at `a` is written back at `a + 2`. -/
theorem dec_wbF (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool)
    (X : EngineF) (a : Nat) (w : Lane) (h : Dec win w (runF P win fl a X).e) :
    IsWB w (runF P win fl (a + 2) X).e := by
  obtain ⟨h1, h2⟩ := step_of_dec P win (runF P win fl a X).e w h
  have e1 : (runF P win fl (a + 1) X).e.st = .drive ∧ (runF P win fl (a + 1) X).e.cur = w := by
    rw [runF_succ']
    exact ⟨h1, h2⟩
  obtain ⟨h3, h4⟩ := step_drive P win (runF P win fl (a + 1) X).e e1.1
  show (runF P win fl (a + 1 + 1) X).e.st = .wb ∧ (runF P win fl (a + 1 + 1) X).e.cur = w
  rw [runF_succ' P win fl (a + 1)]
  exact ⟨h3, h4.trans e1.2⟩

/-- A writeback at `t` comes from a decision of the same lane at `t − 2`. -/
theorem wb_backF (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool)
    (X0 : EngineF) (h0 : X0.e.st = .idle) (t : Nat) (y : Lane)
    (hwb : IsWB y (runF P win fl t X0).e) :
    ∃ s, t = s + 2 ∧ Dec win y (runF P win fl s X0).e := by
  obtain ⟨hst, hcur⟩ := hwb
  cases t with
  | zero =>
    have h : (runF P win fl 0 X0).e.st = .idle := h0
    rw [h] at hst
    cases hst
  | succ t =>
    rw [runF_succ'] at hst hcur
    obtain ⟨hd, hc⟩ := back_wb P win (runF P win fl t X0).e hst
    cases t with
    | zero =>
      have h : (runF P win fl 0 X0).e.st = .idle := h0
      rw [h] at hd
      cases hd
    | succ s =>
      have hc' : (runF P win fl (s + 1) X0).e.cur = y := hc.symm.trans hcur
      have hd' : (step P win (runF P win fl s X0).e).st = .drive := by
        have h := hd
        rw [runF_succ'] at h
        exact h
      have hcs : (step P win (runF P win fl s X0).e).cur = y := by
        have h := hc'
        rw [runF_succ'] at h
        exact h
      have hdec := back_drive P win (runF P win fl s X0).e hd'
      refine ⟨s, rfl, ?_⟩
      rw [← hcs]
      exact hdec

/-- A decision at `D` is written back at `D + 2`, with the same timestamp. -/
theorem dec_tsF (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool)
    (X0 : EngineF) (D : Nat) (y : Lane) (hfy : ∀ t, fl t y = false)
    (h : Dec win y (runF P win fl D X0).e) :
    (runF P win fl (D + 2) X0).e.ts y = (runF P win fl D X0).e.ts y ∧
    (runF P win fl (D + 2) X0).e.now = (runF P win fl D X0).e.now + 2 := by
  have hidle : (runF P win fl D X0).e.st = .idle := h.1
  have hdrive : (runF P win fl (D + 1) X0).e.st = .drive := by
    rw [runF_succ']
    exact (step_of_dec P win _ y h).1
  have t1 := ts_flatF P win fl y hfy X0 D (not_wb_of_st y _ (by rw [hidle]; decide))
  have t2 := ts_flatF P win fl y hfy X0 (D + 1) (not_wb_of_st y _ (by rw [hdrive]; decide))
  have n1 := now_runF P win fl D X0
  have n2 := now_runF P win fl (D + 1 + 1) X0
  constructor
  · show (runF P win fl (D + 1 + 1) X0).e.ts y = (runF P win fl D X0).e.ts y
    rw [t2, t1]
  · show (runF P win fl (D + 1 + 1) X0).e.now = (runF P win fl D X0).e.now + 2
    omega

theorem ready_stepF (P : Program) (win : Engine → Option Lane) (f : Lane → Bool) (i : Lane)
    (X : EngineF) (hf : f i = false) (hr : Ready P i X.e) (hm : NotMid i X.e) :
    Ready P i (stepF P win f X).e := by
  obtain ⟨hl, hts⟩ := ready_step P win i X.e hr hm
  refine ⟨hl, ?_⟩
  rw [stepF_ts_y P win f X i hf]
  exact hts

theorem notMid_stepF (P : Program) (win : Engine → Option Lane) (f : Lane → Bool) (i : Lane)
    (X : EngineF) (hm : NotMid i X.e) (hnd : ¬Dec win i X.e) :
    NotMid i (stepF P win f X).e :=
  notMid_step P win i X.e hm hnd

theorem lemA_run_nF (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool)
    (i : Lane) (hfi : ∀ t, fl t i = false) :
    ∀ (t : Nat) (X : EngineF), Ready P i X.e → NotMid i X.e →
      (∀ s, s < t → ¬Dec win i (runF P win fl s X).e) →
      3 * cntF P win fl (fun e => decOther win i e = true) t X
        + cntF P win fl (fun e => noDecB win e = true) t X + ph X.e.st
        = t + ph (runF P win fl t X).e.st
  | 0, X, _, _, _ => by simp [cntF, runF]
  | t + 1, X, hr, hm, hnd => by
    have hnd0 : ¬Dec win i X.e := hnd 0 (Nat.succ_pos t)
    have h1 := lemA_step_n P win i X.e hnd0
    have h1' : 3 * (if decOther win i X.e = true then 1 else 0)
        + (if noDecB win X.e = true then 1 else 0) + ph X.e.st
        = 1 + ph (stepF P win (fl X.e.now) X).e.st := h1
    have ih := lemA_run_nF P win fl i hfi t (stepF P win (fl X.e.now) X)
      (ready_stepF P win _ i X (hfi _) hr hm)
      (notMid_stepF P win _ i X hm hnd0)
      (fun s hs => hnd (s + 1) (Nat.succ_lt_succ hs))
    have e1 : cntF P win fl (fun e => decOther win i e = true) (t + 1) X
        = (if decOther win i X.e = true then 1 else 0)
          + cntF P win fl (fun e => decOther win i e = true) t (stepF P win (fl X.e.now) X) := rfl
    have e2 : cntF P win fl (fun e => noDecB win e = true) (t + 1) X
        = (if noDecB win X.e = true then 1 else 0)
          + cntF P win fl (fun e => noDecB win e = true) t (stepF P win (fl X.e.now) X) := rfl
    have e3 : runF P win fl (t + 1) X = runF P win fl t (stepF P win (fl X.e.now) X) := rfl
    rw [e3]
    omega

/-- **Lemma A on runs with flushes**, for a lane never flushed. -/
theorem lemmaA_nF (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool) (i : Lane)
    (hfi : ∀ t, fl t i = false) (t : Nat) (X : EngineF)
    (hr : Ready P i X.e) (hm : NotMid i X.e)
    (hnd : ∀ s, s < t → ¬Dec win i (runF P win fl s X).e) :
    t ≤ 3 * cntF P win fl (fun e => decOther win i e = true) t X
      + cntF P win fl (fun e => noDecB win e = true) t X + 2 := by
  have h := lemA_run_nF P win fl i hfi t X hr hm hnd
  have h2 := ph_le X.e.st
  omega

/-- **Response bound on runs with flushes.** `wb_bound_win_n` for a lane `y` that is never
flushed: on a run with FALLTHROUGH flushes of other lanes, every writeback of `y` lands within
`K + 1` of its release, given the window budget (`M` other-lane decisions, `S` idle cycles with
no decision — the disarms among them — in every `K ≥ 3M + S + 3` window). -/
theorem wb_bound_winF (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool)
    (X0 : EngineF) (h0 : X0.e.st = .idle) (h0ts : ∀ l, X0.e.now ≤ X0.e.ts l) (y : Lane)
    (hy : P.live y = true) (hfy : ∀ t, fl t y = false)
    (M S K : Nat) (hK : 3 * M + S + 3 ≤ K)
    (t : Nat) (hwb : IsWB y (runF P win fl t X0).e)
    (hfree : ∀ w, w + 2 < t → IsWB y (runF P win fl w X0).e →
      (runF P win fl w X0).e.now < (runF P win fl t X0).e.ts y)
    (hM : ∀ c, c + K + 2 ≤ t →
      cntF P win fl (fun e => decOther win y e = true) K (runF P win fl c X0) ≤ M)
    (hS : ∀ c, c + K + 2 ≤ t →
      cntF P win fl (fun e => noDecB win e = true) K (runF P win fl c X0) ≤ S) :
    (runF P win fl t X0).e.now ≤ (runF P win fl t X0).e.ts y + K + 1 := by
  obtain ⟨D, rfl, hdec⟩ := wb_backF P win fl X0 h0 t y hwb
  obtain ⟨hts2, hnow2⟩ := dec_tsF P win fl X0 D y hfy hdec
  rw [hts2, hnow2]
  rw [hts2] at hfree
  by_cases hfit : (runF P win fl D X0).e.now + 1 ≤ (runF P win fl D X0).e.ts y + K
  · omega
  · exfalso
    have hnD := now_runF P win fl D X0
    have hts0 := ts_monoF P win fl y hfy X0 0 D
    have h00 : (runF P win fl 0 X0).e.ts y = X0.e.ts y := rfl
    rw [Nat.zero_add] at hts0
    have h0y := h0ts y
    obtain ⟨c, rfl⟩ : ∃ c, D = c + K := ⟨D - K, by omega⟩
    have hnc := now_runF P win fl c X0
    have noWB : ∀ w, c ≤ w → w < c + K → ¬IsWB y (runF P win fl w X0).e := by
      intro w hcw hwD hw
      have h1 := hfree w (by omega) hw
      have h2 := now_runF P win fl w X0
      omega
    have hrdy : Ready P y (runF P win fl c X0).e := by
      refine ⟨hy, ?_⟩
      have := ts_monoF P win fl y hfy X0 c K
      omega
    have hmid : NotMid y (runF P win fl c X0).e := by
      unfold NotMid
      rintro ⟨hne, hcur⟩
      cases hs : (runF P win fl c X0).e.st with
      | idle => exact hne hs
      | wb => exact noWB c (Nat.le_refl c) (by omega) ⟨hs, hcur⟩
      | drive =>
        have h1 := step_drive P win (runF P win fl c X0).e hs
        apply noWB (c + 1) (by omega) (by omega)
        rw [runF_succ']
        exact ⟨h1.1, h1.2.trans hcur⟩
    have hnd : ∀ s, s < K → ¬Dec win y (runF P win fl s (runF P win fl c X0)).e := by
      intro s hs hds
      rw [← runF_add] at hds
      have hw2 := dec_wbF P win fl X0 (c + s) y hds
      rcases Nat.lt_or_ge (c + s + 2) (c + K) with hlt | hge
      · exact noWB (c + s + 2) (by omega) hlt hw2
      · have hidle : (runF P win fl (c + K) X0).e.st = .idle := hdec.1
        have hst1 : (runF P win fl (c + s + 1) X0).e.st = .drive := by
          rw [runF_succ']
          exact (step_of_dec P win _ y hds).1
        have hst2 : (runF P win fl (c + s + 2) X0).e.st = .wb := hw2.1
        have : c + K = c + s + 1 ∨ c + K = c + s + 2 := by omega
        rcases this with h | h
        · rw [h, hst1] at hidle
          cases hidle
        · rw [h, hst2] at hidle
          cases hidle
    have hA := lemmaA_nF P win fl y hfy K (runF P win fl c X0) hrdy hmid hnd
    have hm := hM c (by omega)
    have hs := hS c (by omega)
    omega

#print axioms lemmaA_nF
#print axioms wb_bound_winF

end JLane
