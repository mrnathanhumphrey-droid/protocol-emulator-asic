import JLane.FlushKill
import JLane.RespWinF
/-!
# Brick C3a — the response bound on the buffered engine with flushes (`slot_on_composition`, part A)

`RespWinF.wb_bound_winF` carried to `FlushKill.runBK`: the cycle-exact engine with the slot, the
depth-2 buffer, the FALLTHROUGH keep-flush (K1–K4) and the kill (K5). `stepBKK` takes the
dispatch FSM (`st`, `cur`), the clock and the branch-1 target register from `stepB`, which takes
them from `step` (`BufEng.stepB_e_*`, all `rfl`); a lane's timestamp differs from `step`'s only in
a cycle that flushes that lane. So, as on `runF`, the dispatch lemmas and Lemma A carry over for a
lane `y` that is never flushed, and every writeback of `y` lands within `K + 1` of its release
under the window budget (`M` other-lane decisions; `S` idle cycles with no decision -- the
FALLTHROUGH disarms among them, `ArmFT.disarm_noDec`, charged by `branch_budget._disarm_S` since
44cd5fb; the stalls are 0 under (b′), `BPrime.cnt_stall_bprime`).

What the buffer changes is which cycles are decisions: a head is valid at other times. That is
inside `M` and `S`, which the bound takes as hypotheses, counted along `runBK` itself.

Part A2 (`wb_bound_winBK_fl`): a lane flushed at its own edges -- the poset compiler's
`else continue` on a generic lane, for which `wb_bound_winF` / `ArmFTClose.wb_bound_T` give no
bound (they need the lane never flushed) -- gets the same `K`, counted from the release after its
last flush, given that it is not flushed between its current release and the writeback.
-/
namespace JLane

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane)

/-! ### The dispatch side of one cycle is `step`'s -/

theorem stepBKK_st (fl : Lane → Bool) (k : Lane → Nat) (X : EngBK) :
    (stepBKK P win usb sreq fl k X).x.e.st = (step P win X.x.e).st := by
  show (stepB P win usb sreq X.base).e.st = _
  rw [stepB_e_st, base_e]; rfl

theorem stepBKK_cur (fl : Lane → Bool) (k : Lane → Nat) (X : EngBK) :
    (stepBKK P win usb sreq fl k X).x.e.cur = (step P win X.x.e).cur := by
  show (stepB P win usb sreq X.base).e.cur = _
  rw [stepB_e_cur, base_e]; rfl

theorem stepBKK_now (fl : Lane → Bool) (k : Lane → Nat) (X : EngBK) :
    (stepBKK P win usb sreq fl k X).x.e.now = X.x.e.now + 1 := by
  show (stepB P win usb sreq X.base).e.now = _
  rw [stepB_e_now, base_e]

/-- An unflushed lane's timestamp moves as `step` moves it. -/
theorem stepBKK_ts_y (fl : Lane → Bool) (k : Lane → Nat) (X : EngBK) (y : Lane)
    (h : fl y = false) : (stepBKK P win usb sreq fl k X).x.e.ts y = tsNext P X.x.e y := by
  show (if fl y = true then X.base.e.now + 1 else (stepB P win usb sreq X.base).e.ts y) = _
  rw [if_neg (by simp [h]), stepB_e_ts, base_e]
  rfl

/-! ### Runs -/

/-- `cnt` along `runBK`. -/
def cntBK (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (Q : Engine → Prop) [DecidablePred Q] :
    Nat → EngBK → Nat
  | 0, _ => 0
  | n + 1, X => (if Q X.x.e then 1 else 0)
      + cntBK fl k Q n (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X)

theorem runBK_succ' (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) :
    ∀ (n : Nat) (X : EngBK), runBK P win usb sreq fl k (n + 1) X
      = stepBKK P win usb sreq (fl (runBK P win usb sreq fl k n X).x.e.now)
          (k (runBK P win usb sreq fl k n X).x.e.now) (runBK P win usb sreq fl k n X)
  | 0, _ => rfl
  | n + 1, X => runBK_succ' fl k n (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X)

theorem now_runBK (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) :
    ∀ (n : Nat) (X : EngBK), (runBK P win usb sreq fl k n X).x.e.now = X.x.e.now + n
  | 0, _ => rfl
  | n + 1, X => by
    rw [runBK_succ', stepBKK_now, now_runBK fl k n X]
    omega

theorem runBK_add (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) :
    ∀ (a b : Nat) (X : EngBK),
      runBK P win usb sreq fl k (a + b) X = runBK P win usb sreq fl k b (runBK P win usb sreq fl k a X)
  | a, 0, _ => rfl
  | a, b + 1, X => by
    rw [← Nat.add_assoc, runBK_succ', runBK_succ', runBK_add fl k a b X]

/-! ### Timestamps of an unflushed lane -/

theorem ts_monoBK (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (y : Lane)
    (hfy : ∀ t, fl t y = false) (X : EngBK) :
    ∀ m j, (runBK P win usb sreq fl k m X).x.e.ts y ≤ (runBK P win usb sreq fl k (m + j) X).x.e.ts y
  | _, 0 => Nat.le_refl _
  | m, j + 1 => by
    rw [← Nat.add_assoc, runBK_succ', stepBKK_ts_y P win usb sreq _ _ _ y (hfy _)]
    exact Nat.le_trans (ts_monoBK fl k y hfy X m j) (tsNext_ge P _ y)

theorem ts_flatBK (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (y : Lane)
    (hfy : ∀ t, fl t y = false) (X : EngBK) (n : Nat)
    (h : ¬IsWB y (runBK P win usb sreq fl k n X).x.e) :
    (runBK P win usb sreq fl k (n + 1) X).x.e.ts y = (runBK P win usb sreq fl k n X).x.e.ts y := by
  rw [runBK_succ', stepBKK_ts_y P win usb sreq _ _ _ y (hfy _)]
  unfold tsNext
  rw [if_neg (fun h' => h ⟨h'.1, h'.2.symm⟩)]

/-! ### Decisions and writebacks -/

theorem dec_wbBK (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X : EngBK) (a : Nat) (w : Lane)
    (h : Dec win w (runBK P win usb sreq fl k a X).x.e) :
    IsWB w (runBK P win usb sreq fl k (a + 2) X).x.e := by
  obtain ⟨h1, h2⟩ := step_of_dec P win (runBK P win usb sreq fl k a X).x.e w h
  have e1 : (runBK P win usb sreq fl k (a + 1) X).x.e.st = .drive ∧
      (runBK P win usb sreq fl k (a + 1) X).x.e.cur = w := by
    rw [runBK_succ', stepBKK_st, stepBKK_cur]
    exact ⟨h1, h2⟩
  obtain ⟨h3, h4⟩ := step_drive P win (runBK P win usb sreq fl k (a + 1) X).x.e e1.1
  show (runBK P win usb sreq fl k (a + 1 + 1) X).x.e.st = .wb ∧
    (runBK P win usb sreq fl k (a + 1 + 1) X).x.e.cur = w
  rw [runBK_succ' P win usb sreq fl k (a + 1), stepBKK_st, stepBKK_cur]
  exact ⟨h3, h4.trans e1.2⟩

theorem wb_backBK (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X0 : EngBK)
    (h0 : X0.x.e.st = .idle) (t : Nat) (y : Lane)
    (hwb : IsWB y (runBK P win usb sreq fl k t X0).x.e) :
    ∃ s, t = s + 2 ∧ Dec win y (runBK P win usb sreq fl k s X0).x.e := by
  obtain ⟨hst, hcur⟩ := hwb
  cases t with
  | zero =>
    have h : (runBK P win usb sreq fl k 0 X0).x.e.st = .idle := h0
    rw [h] at hst
    cases hst
  | succ t =>
    rw [runBK_succ', stepBKK_st] at hst
    rw [runBK_succ', stepBKK_cur] at hcur
    obtain ⟨hd, hc⟩ := back_wb P win (runBK P win usb sreq fl k t X0).x.e hst
    cases t with
    | zero =>
      have h : (runBK P win usb sreq fl k 0 X0).x.e.st = .idle := h0
      rw [h] at hd
      cases hd
    | succ s =>
      have hc' : (runBK P win usb sreq fl k (s + 1) X0).x.e.cur = y := hc.symm.trans hcur
      have hd' : (step P win (runBK P win usb sreq fl k s X0).x.e).st = .drive := by
        have h := hd
        rw [runBK_succ', stepBKK_st] at h
        exact h
      have hcs : (step P win (runBK P win usb sreq fl k s X0).x.e).cur = y := by
        have h := hc'
        rw [runBK_succ', stepBKK_cur] at h
        exact h
      have hdec := back_drive P win (runBK P win usb sreq fl k s X0).x.e hd'
      refine ⟨s, rfl, ?_⟩
      rw [← hcs]
      exact hdec

theorem dec_tsBK (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X0 : EngBK) (D : Nat) (y : Lane)
    (hfy : ∀ t, fl t y = false) (h : Dec win y (runBK P win usb sreq fl k D X0).x.e) :
    (runBK P win usb sreq fl k (D + 2) X0).x.e.ts y = (runBK P win usb sreq fl k D X0).x.e.ts y ∧
    (runBK P win usb sreq fl k (D + 2) X0).x.e.now = (runBK P win usb sreq fl k D X0).x.e.now + 2 := by
  have hidle : (runBK P win usb sreq fl k D X0).x.e.st = .idle := h.1
  have hdrive : (runBK P win usb sreq fl k (D + 1) X0).x.e.st = .drive := by
    rw [runBK_succ', stepBKK_st]
    exact (step_of_dec P win _ y h).1
  have t1 := ts_flatBK P win usb sreq fl k y hfy X0 D (not_wb_of_st y _ (by rw [hidle]; decide))
  have t2 := ts_flatBK P win usb sreq fl k y hfy X0 (D + 1)
    (not_wb_of_st y _ (by rw [hdrive]; decide))
  have n1 := now_runBK P win usb sreq fl k D X0
  have n2 := now_runBK P win usb sreq fl k (D + 1 + 1) X0
  constructor
  · show (runBK P win usb sreq fl k (D + 1 + 1) X0).x.e.ts y = _
    rw [t2, t1]
  · show (runBK P win usb sreq fl k (D + 1 + 1) X0).x.e.now = _
    omega

/-! ### Lemma A along `runBK` -/

theorem ready_stepBK (f : Lane → Bool) (kk : Lane → Nat) (i : Lane) (X : EngBK) (hf : f i = false)
    (hr : Ready P i X.x.e) (hm : NotMid i X.x.e) : Ready P i (stepBKK P win usb sreq f kk X).x.e := by
  obtain ⟨hl, hts⟩ := ready_step P win i X.x.e hr hm
  refine ⟨hl, ?_⟩
  rw [stepBKK_ts_y P win usb sreq f kk X i hf, stepBKK_now]
  exact hts

theorem notMid_stepBK (f : Lane → Bool) (kk : Lane → Nat) (i : Lane) (X : EngBK)
    (hm : NotMid i X.x.e) (hnd : ¬Dec win i X.x.e) : NotMid i (stepBKK P win usb sreq f kk X).x.e := by
  have h := notMid_step P win i X.x.e hm hnd
  unfold NotMid at h ⊢
  rw [stepBKK_st, stepBKK_cur]
  exact h

theorem lemA_run_nBK (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (i : Lane)
    (hfi : ∀ t, fl t i = false) :
    ∀ (t : Nat) (X : EngBK), Ready P i X.x.e → NotMid i X.x.e →
      (∀ s, s < t → ¬Dec win i (runBK P win usb sreq fl k s X).x.e) →
      3 * cntBK P win usb sreq fl k (fun e => decOther win i e = true) t X
        + cntBK P win usb sreq fl k (fun e => noDecB win e = true) t X + ph X.x.e.st
        = t + ph (runBK P win usb sreq fl k t X).x.e.st
  | 0, X, _, _, _ => by simp [cntBK, runBK]
  | t + 1, X, hr, hm, hnd => by
    have hnd0 : ¬Dec win i X.x.e := hnd 0 (Nat.succ_pos t)
    have h1 := lemA_step_n P win i X.x.e hnd0
    have hst := stepBKK_st P win usb sreq (fl X.x.e.now) (k X.x.e.now) X
    have h1' : 3 * (if decOther win i X.x.e = true then 1 else 0)
        + (if noDecB win X.x.e = true then 1 else 0) + ph X.x.e.st
        = 1 + ph (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X).x.e.st := by
      rw [hst]; exact h1
    have ih := lemA_run_nBK fl k i hfi t (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X)
      (ready_stepBK P win usb sreq _ _ i X (hfi _) hr hm)
      (notMid_stepBK P win usb sreq _ _ i X hm hnd0)
      (fun s hs => hnd (s + 1) (Nat.succ_lt_succ hs))
    have e1 : cntBK P win usb sreq fl k (fun e => decOther win i e = true) (t + 1) X
        = (if decOther win i X.x.e = true then 1 else 0)
          + cntBK P win usb sreq fl k (fun e => decOther win i e = true) t
              (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X) := rfl
    have e2 : cntBK P win usb sreq fl k (fun e => noDecB win e = true) (t + 1) X
        = (if noDecB win X.x.e = true then 1 else 0)
          + cntBK P win usb sreq fl k (fun e => noDecB win e = true) t
              (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X) := rfl
    have e3 : runBK P win usb sreq fl k (t + 1) X
        = runBK P win usb sreq fl k t (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X) := rfl
    rw [e3]
    omega

/-- **Lemma A on the buffered engine with flushes**, for a lane never flushed. -/
theorem lemmaA_nBK (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (i : Lane)
    (hfi : ∀ t, fl t i = false) (t : Nat) (X : EngBK)
    (hr : Ready P i X.x.e) (hm : NotMid i X.x.e)
    (hnd : ∀ s, s < t → ¬Dec win i (runBK P win usb sreq fl k s X).x.e) :
    t ≤ 3 * cntBK P win usb sreq fl k (fun e => decOther win i e = true) t X
      + cntBK P win usb sreq fl k (fun e => noDecB win e = true) t X + 2 := by
  have h := lemA_run_nBK P win usb sreq fl k i hfi t X hr hm hnd
  have h2 := ph_le X.x.e.st
  omega

/-- **The response bound on the buffered engine with flushes** (`slot_on_composition` part A):
`wb_bound_winF` on `runBK` for a lane `y` never flushed. Every writeback of `y` lands within
`K + 1` of its release, given the window budget counted along `runBK` (`M` other-lane decisions,
`S` idle cycles with no decision, the disarms among them, in every `K ≥ 3M + S + 3` window). -/
theorem wb_bound_winBK (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat)
    (X0 : EngBK) (h0 : X0.x.e.st = .idle) (h0ts : ∀ l, X0.x.e.now ≤ X0.x.e.ts l) (y : Lane)
    (hy : P.live y = true) (hfy : ∀ t, fl t y = false)
    (M S K : Nat) (hK : 3 * M + S + 3 ≤ K)
    (t : Nat) (hwb : IsWB y (runBK P win usb sreq fl k t X0).x.e)
    (hfree : ∀ w, w + 2 < t → IsWB y (runBK P win usb sreq fl k w X0).x.e →
      (runBK P win usb sreq fl k w X0).x.e.now < (runBK P win usb sreq fl k t X0).x.e.ts y)
    (hM : ∀ c, c + K + 2 ≤ t →
      cntBK P win usb sreq fl k (fun e => decOther win y e = true) K
        (runBK P win usb sreq fl k c X0) ≤ M)
    (hS : ∀ c, c + K + 2 ≤ t →
      cntBK P win usb sreq fl k (fun e => noDecB win e = true) K
        (runBK P win usb sreq fl k c X0) ≤ S) :
    (runBK P win usb sreq fl k t X0).x.e.now ≤ (runBK P win usb sreq fl k t X0).x.e.ts y + K + 1 := by
  obtain ⟨D, rfl, hdec⟩ := wb_backBK P win usb sreq fl k X0 h0 t y hwb
  obtain ⟨hts2, hnow2⟩ := dec_tsBK P win usb sreq fl k X0 D y hfy hdec
  rw [hts2, hnow2]
  rw [hts2] at hfree
  by_cases hfit : (runBK P win usb sreq fl k D X0).x.e.now + 1
      ≤ (runBK P win usb sreq fl k D X0).x.e.ts y + K
  · omega
  · exfalso
    have hnD := now_runBK P win usb sreq fl k D X0
    have hts0 := ts_monoBK P win usb sreq fl k y hfy X0 0 D
    have h00 : (runBK P win usb sreq fl k 0 X0).x.e.ts y = X0.x.e.ts y := rfl
    rw [Nat.zero_add] at hts0
    have h0y := h0ts y
    obtain ⟨c, rfl⟩ : ∃ c, D = c + K := ⟨D - K, by omega⟩
    have hnc := now_runBK P win usb sreq fl k c X0
    have noWB : ∀ w, c ≤ w → w < c + K → ¬IsWB y (runBK P win usb sreq fl k w X0).x.e := by
      intro w hcw hwD hw
      have h1 := hfree w (by omega) hw
      have h2 := now_runBK P win usb sreq fl k w X0
      omega
    have hrdy : Ready P y (runBK P win usb sreq fl k c X0).x.e := by
      refine ⟨hy, ?_⟩
      have := ts_monoBK P win usb sreq fl k y hfy X0 c K
      omega
    have hmid : NotMid y (runBK P win usb sreq fl k c X0).x.e := by
      unfold NotMid
      rintro ⟨hne, hcur⟩
      cases hs : (runBK P win usb sreq fl k c X0).x.e.st with
      | idle => exact hne hs
      | wb => exact noWB c (Nat.le_refl c) (by omega) ⟨hs, hcur⟩
      | drive =>
        have h1 := step_drive P win (runBK P win usb sreq fl k c X0).x.e hs
        apply noWB (c + 1) (by omega) (by omega)
        rw [runBK_succ']
        refine ⟨?_, ?_⟩
        · rw [stepBKK_st]; exact h1.1
        · rw [stepBKK_cur]; exact h1.2.trans hcur
    have hnd : ∀ s, s < K → ¬Dec win y
        (runBK P win usb sreq fl k s (runBK P win usb sreq fl k c X0)).x.e := by
      intro s hs hds
      rw [← runBK_add] at hds
      have hw2 := dec_wbBK P win usb sreq fl k X0 (c + s) y hds
      rcases Nat.lt_or_ge (c + s + 2) (c + K) with hlt | hge
      · exact noWB (c + s + 2) (by omega) hlt hw2
      · have hidle : (runBK P win usb sreq fl k (c + K) X0).x.e.st = .idle := hdec.1
        have hst1 : (runBK P win usb sreq fl k (c + s + 1) X0).x.e.st = .drive := by
          rw [runBK_succ', stepBKK_st]
          exact (step_of_dec P win _ y hds).1
        have hst2 : (runBK P win usb sreq fl k (c + s + 2) X0).x.e.st = .wb := hw2.1
        have : c + K = c + s + 1 ∨ c + K = c + s + 2 := by omega
        rcases this with h | h
        · rw [h, hst1] at hidle
          cases hidle
        · rw [h, hst2] at hidle
          cases hidle
    have hA := lemmaA_nBK P win usb sreq fl k y hfy K (runBK P win usb sreq fl k c X0) hrdy hmid hnd
    have hm := hM c (by omega)
    have hs := hS c (by omega)
    omega

/-! ### Part A2: a lane flushed at its own edges

A FALLTHROUGH edge flushes its own lane: `ts` jumps to the cycle after the edge (a new release),
possibly below the timeout release it had. The window argument only needs `y` unflushed from its
current release to its writeback -- a flushed lane is armed (`ArmFTClose.invF_run3T`), and a
released lane is not armed before it is dispatched -- and every timestamp at or after the run's
start (each update is the clock + 1 or `tsNext`, which never goes below the old value). -/

/-- One cycle with `y` unflushed: `ts y` does not go down. -/
theorem ts_step_leBK (f : Lane → Bool) (kk : Lane → Nat) (X : EngBK) (y : Lane) (h : f y = false) :
    X.x.e.ts y ≤ (stepBKK P win usb sreq f kk X).x.e.ts y := by
  rw [stepBKK_ts_y P win usb sreq f kk X y h]
  exact tsNext_ge P _ y

/-- Every timestamp stays at or after the run's start, flushes included. -/
theorem ts_ge_startBK (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X0 : EngBK)
    (h0ts : ∀ l, X0.x.e.now ≤ X0.x.e.ts l) :
    ∀ (n : Nat) (l : Lane), X0.x.e.now ≤ (runBK P win usb sreq fl k n X0).x.e.ts l
  | 0, l => h0ts l
  | n + 1, l => by
    have ih := ts_ge_startBK fl k X0 h0ts n l
    have hn := now_runBK P win usb sreq fl k n X0
    rw [runBK_succ']
    cases hf : fl (runBK P win usb sreq fl k n X0).x.e.now l with
    | false =>
      exact Nat.le_trans ih (ts_step_leBK P win usb sreq _ _ _ l hf)
    | true =>
      show X0.x.e.now ≤ (if fl (runBK P win usb sreq fl k n X0).x.e.now l = true
        then (runBK P win usb sreq fl k n X0).base.e.now + 1
        else (stepB P win usb sreq (runBK P win usb sreq fl k n X0).base).e.ts l)
      rw [if_pos hf, base_e]
      omega

/-- Over `j` cycles from `m` with `y` unflushed in each, `ts y` does not go down. -/
theorem ts_mono_winBK (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (y : Lane) (X : EngBK)
    (m : Nat) : ∀ j, (∀ s, s < j → fl (runBK P win usb sreq fl k (m + s) X).x.e.now y = false) →
      (runBK P win usb sreq fl k m X).x.e.ts y ≤ (runBK P win usb sreq fl k (m + j) X).x.e.ts y
  | 0, _ => Nat.le_refl _
  | j + 1, hf => by
    have ih := ts_mono_winBK fl k y X m j (fun s hs => hf s (by omega))
    rw [← Nat.add_assoc, runBK_succ']
    exact Nat.le_trans ih (ts_step_leBK P win usb sreq _ _ _ y (hf j (by omega)))

/-- One cycle with `y` unflushed and not written back: `ts y` is unchanged. -/
theorem ts_flat1BK (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (y : Lane) (X : EngBK) (n : Nat)
    (hf : fl (runBK P win usb sreq fl k n X).x.e.now y = false)
    (h : ¬IsWB y (runBK P win usb sreq fl k n X).x.e) :
    (runBK P win usb sreq fl k (n + 1) X).x.e.ts y = (runBK P win usb sreq fl k n X).x.e.ts y := by
  rw [runBK_succ', stepBKK_ts_y P win usb sreq _ _ _ y hf]
  unfold tsNext
  rw [if_neg (fun h' => h ⟨h'.1, h'.2.symm⟩)]

/-- Lemma A along `runBK` with `i` unflushed only inside the window. -/
theorem lemA_run_winBK (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (i : Lane) :
    ∀ (t : Nat) (X : EngBK), Ready P i X.x.e → NotMid i X.x.e →
      (∀ s, s < t → fl (runBK P win usb sreq fl k s X).x.e.now i = false) →
      (∀ s, s < t → ¬Dec win i (runBK P win usb sreq fl k s X).x.e) →
      3 * cntBK P win usb sreq fl k (fun e => decOther win i e = true) t X
        + cntBK P win usb sreq fl k (fun e => noDecB win e = true) t X + ph X.x.e.st
        = t + ph (runBK P win usb sreq fl k t X).x.e.st
  | 0, X, _, _, _, _ => by simp [cntBK, runBK]
  | t + 1, X, hr, hm, hfi, hnd => by
    have hnd0 : ¬Dec win i X.x.e := hnd 0 (Nat.succ_pos t)
    have hf0 : fl X.x.e.now i = false := hfi 0 (Nat.succ_pos t)
    have h1 := lemA_step_n P win i X.x.e hnd0
    have hst := stepBKK_st P win usb sreq (fl X.x.e.now) (k X.x.e.now) X
    have h1' : 3 * (if decOther win i X.x.e = true then 1 else 0)
        + (if noDecB win X.x.e = true then 1 else 0) + ph X.x.e.st
        = 1 + ph (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X).x.e.st := by
      rw [hst]; exact h1
    have ih := lemA_run_winBK fl k i t (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X)
      (ready_stepBK P win usb sreq _ _ i X hf0 hr hm)
      (notMid_stepBK P win usb sreq _ _ i X hm hnd0)
      (fun s hs => hfi (s + 1) (Nat.succ_lt_succ hs))
      (fun s hs => hnd (s + 1) (Nat.succ_lt_succ hs))
    have e1 : cntBK P win usb sreq fl k (fun e => decOther win i e = true) (t + 1) X
        = (if decOther win i X.x.e = true then 1 else 0)
          + cntBK P win usb sreq fl k (fun e => decOther win i e = true) t
              (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X) := rfl
    have e2 : cntBK P win usb sreq fl k (fun e => noDecB win e = true) (t + 1) X
        = (if noDecB win X.x.e = true then 1 else 0)
          + cntBK P win usb sreq fl k (fun e => noDecB win e = true) t
              (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X) := rfl
    have e3 : runBK P win usb sreq fl k (t + 1) X
        = runBK P win usb sreq fl k t (stepBKK P win usb sreq (fl X.x.e.now) (k X.x.e.now) X) := rfl
    rw [e3]
    omega

/-- **The response bound for a lane flushed at its own edges** (`slot_on_composition` part A2):
`wb_bound_winBK` with "never flushed" replaced by "not flushed at or after its current release,
before this writeback" (`hnf`). The window argument restarts from the release after the lane's
last flush, with the same `K`. -/
theorem wb_bound_winBK_fl (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat)
    (X0 : EngBK) (h0 : X0.x.e.st = .idle) (h0ts : ∀ l, X0.x.e.now ≤ X0.x.e.ts l) (y : Lane)
    (hy : P.live y = true)
    (M S K : Nat) (hK : 3 * M + S + 3 ≤ K)
    (t : Nat) (hwb : IsWB y (runBK P win usb sreq fl k t X0).x.e)
    (hnf : ∀ n, n < t → (runBK P win usb sreq fl k t X0).x.e.ts y ≤ (runBK P win usb sreq fl k n X0).x.e.now →
      fl (runBK P win usb sreq fl k n X0).x.e.now y = false)
    (hfree : ∀ w, w + 2 < t → IsWB y (runBK P win usb sreq fl k w X0).x.e →
      (runBK P win usb sreq fl k w X0).x.e.now < (runBK P win usb sreq fl k t X0).x.e.ts y)
    (hM : ∀ c, c + K + 2 ≤ t →
      cntBK P win usb sreq fl k (fun e => decOther win y e = true) K
        (runBK P win usb sreq fl k c X0) ≤ M)
    (hS : ∀ c, c + K + 2 ≤ t →
      cntBK P win usb sreq fl k (fun e => noDecB win e = true) K
        (runBK P win usb sreq fl k c X0) ≤ S) :
    (runBK P win usb sreq fl k t X0).x.e.now ≤ (runBK P win usb sreq fl k t X0).x.e.ts y + K + 1 := by
  obtain ⟨D, rfl, hdec⟩ := wb_backBK P win usb sreq fl k X0 h0 t y hwb
  by_cases hfit : (runBK P win usb sreq fl k (D + 2) X0).x.e.now
      ≤ (runBK P win usb sreq fl k (D + 2) X0).x.e.ts y + K + 1
  · exact hfit
  · exfalso
    have hnD := now_runBK P win usb sreq fl k D X0
    have hnD1 := now_runBK P win usb sreq fl k (D + 1) X0
    have hnD2 := now_runBK P win usb sreq fl k (D + 2) X0
    -- past the release at D and D + 1: unflushed there, so ts y is flat to the writeback
    have hidle : (runBK P win usb sreq fl k D X0).x.e.st = .idle := hdec.1
    have hdrive : (runBK P win usb sreq fl k (D + 1) X0).x.e.st = .drive := by
      rw [runBK_succ', stepBKK_st]
      exact (step_of_dec P win _ y hdec).1
    have f0 := hnf D (by omega) (by omega)
    have f1 := hnf (D + 1) (by omega) (by omega)
    have t1 := ts_flat1BK P win usb sreq fl k y X0 D f0 (not_wb_of_st y _ (by rw [hidle]; decide))
    have t2 := ts_flat1BK P win usb sreq fl k y X0 (D + 1) f1
      (not_wb_of_st y _ (by rw [hdrive]; decide))
    have hts2 : (runBK P win usb sreq fl k (D + 2) X0).x.e.ts y
        = (runBK P win usb sreq fl k D X0).x.e.ts y := by
      show (runBK P win usb sreq fl k (D + 1 + 1) X0).x.e.ts y = _
      rw [t2, t1]
    have hge := ts_ge_startBK P win usb sreq fl k X0 h0ts (D + 2) y
    obtain ⟨c, rfl⟩ : ∃ c, D = c + K := ⟨D - K, by omega⟩
    have hnc := now_runBK P win usb sreq fl k c X0
    -- every cycle from c on is at or past the release: y is unflushed there
    have hfw : ∀ s, s < K → fl (runBK P win usb sreq fl k (c + s) X0).x.e.now y = false := by
      intro s hs
      have := now_runBK P win usb sreq fl k (c + s) X0
      exact hnf (c + s) (by omega) (by omega)
    have noWB : ∀ w, c ≤ w → w < c + K → ¬IsWB y (runBK P win usb sreq fl k w X0).x.e := by
      intro w hcw hwD hw
      have h1 := hfree w (by omega) hw
      have h2 := now_runBK P win usb sreq fl k w X0
      omega
    have hmono := ts_mono_winBK P win usb sreq fl k y X0 c K hfw
    have hrdy : Ready P y (runBK P win usb sreq fl k c X0).x.e := by
      refine ⟨hy, ?_⟩
      omega
    have hmid : NotMid y (runBK P win usb sreq fl k c X0).x.e := by
      unfold NotMid
      rintro ⟨hne, hcur⟩
      cases hs : (runBK P win usb sreq fl k c X0).x.e.st with
      | idle => exact hne hs
      | wb => exact noWB c (Nat.le_refl c) (by omega) ⟨hs, hcur⟩
      | drive =>
        have h1 := step_drive P win (runBK P win usb sreq fl k c X0).x.e hs
        apply noWB (c + 1) (by omega) (by omega)
        rw [runBK_succ']
        refine ⟨?_, ?_⟩
        · rw [stepBKK_st]; exact h1.1
        · rw [stepBKK_cur]; exact h1.2.trans hcur
    have hnd : ∀ s, s < K → ¬Dec win y
        (runBK P win usb sreq fl k s (runBK P win usb sreq fl k c X0)).x.e := by
      intro s hs hds
      rw [← runBK_add] at hds
      have hw2 := dec_wbBK P win usb sreq fl k X0 (c + s) y hds
      rcases Nat.lt_or_ge (c + s + 2) (c + K) with hlt | hge2
      · exact noWB (c + s + 2) (by omega) hlt hw2
      · have hst1 : (runBK P win usb sreq fl k (c + s + 1) X0).x.e.st = .drive := by
          rw [runBK_succ', stepBKK_st]
          exact (step_of_dec P win _ y hds).1
        have hst2 : (runBK P win usb sreq fl k (c + s + 2) X0).x.e.st = .wb := hw2.1
        have : c + K = c + s + 1 ∨ c + K = c + s + 2 := by omega
        rcases this with h | h
        · rw [h, hst1] at hidle
          cases hidle
        · rw [h, hst2] at hidle
          cases hidle
    have hfw' : ∀ s, s < K →
        fl (runBK P win usb sreq fl k s (runBK P win usb sreq fl k c X0)).x.e.now y = false := by
      intro s hs
      rw [← runBK_add]
      exact hfw s hs
    have hA := lemA_run_winBK P win usb sreq fl k y K (runBK P win usb sreq fl k c X0) hrdy hmid
      hfw' hnd
    have h2 := ph_le (runBK P win usb sreq fl k c X0).x.e.st
    have hm := hM c (by omega)
    have hs := hS c (by omega)
    omega

end

#print axioms stepBKK_ts_y
#print axioms lemmaA_nBK
#print axioms wb_bound_winBK
#print axioms ts_ge_startBK
#print axioms wb_bound_winBK_fl

end JLane
