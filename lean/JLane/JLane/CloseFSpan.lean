import JLane.ArmFTClose
/-!
# Brick F7 — the per-lane response bounds closed on the flush run in span form

`usbdev_dev` / `usbdev_fpga` carry a FALLTHROUGH ARM on the USB lane, so their slot-off run is
`run3T`, whose view is the flush run `runF` (`ArmFT.run3T_proj`). Their stamps rested on
`ArmFTClose.wb_bound_T`, whose `hM` was a premise. Here `hM` comes from the certificate's span
rule (`branch_budget._decisions`, `lane_cert.span_min`), as `RespSpan.wb_close_span` does on `run`
and `CloseBKSpan.wb_closeBK_span` on `runBK` (Wilson 11-21, usbdev ruling):

* the counting lemmas along `runF` (`cntF_*`, `dec_sepF`, `cntF_wb_shift`);
* `wb_close_spanF` — every lane **never flushed** (`fz y = false`) closes within `R y + 2`, by
  `RespWinF.wb_bound_winF` with `hM` from `hspan` (anchored at a writeback, as on `runBK`: a flush
  can lower a timestamp) and `R y + 1 + R z ≤ G z`. A flushed lane (the USB lane) keeps its own
  bound (`hRz`, `PrioResp`); `hS` counts every idle cycle with no decision, disarms included (the
  checker's `_disarm_S`);
* `wb_close_spanT` — the same on the engine with ARM registers (`run3T`), through `runF_e`.
-/
namespace JLane

/-! ### Counting along `runF` -/

theorem cntF_succ_back (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool)
    (Q : Engine → Prop) [DecidablePred Q] :
    ∀ (n : Nat) (X : EngineF),
      cntF P win fl Q (n + 1) X
        = cntF P win fl Q n X + (if Q (runF P win fl n X).e then 1 else 0)
  | 0, X => by simp [cntF, runF]
  | n + 1, X => by
    have ih := cntF_succ_back P win fl Q n (stepF P win (fl X.e.now) X)
    have e1 : cntF P win fl Q (n + 1 + 1) X
        = (if Q X.e then 1 else 0) + cntF P win fl Q (n + 1) (stepF P win (fl X.e.now) X) := rfl
    have e2 : cntF P win fl Q (n + 1) X
        = (if Q X.e then 1 else 0) + cntF P win fl Q n (stepF P win (fl X.e.now) X) := rfl
    have e3 : runF P win fl (n + 1) X = runF P win fl n (stepF P win (fl X.e.now) X) := rfl
    rw [e3]
    omega

theorem cntF_add (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool)
    (Q : Engine → Prop) [DecidablePred Q] :
    ∀ (a b : Nat) (X : EngineF),
      cntF P win fl Q (a + b) X = cntF P win fl Q a X + cntF P win fl Q b (runF P win fl a X)
  | 0, b, X => by
    show cntF P win fl Q (0 + b) X = 0 + cntF P win fl Q b X
    rw [Nat.zero_add, Nat.zero_add]
  | a + 1, b, X => by
    rw [Nat.add_right_comm]
    show (if Q X.e then 1 else 0) + cntF P win fl Q (a + b) (stepF P win (fl X.e.now) X)
        = ((if Q X.e then 1 else 0) + cntF P win fl Q a (stepF P win (fl X.e.now) X))
          + cntF P win fl Q b (runF P win fl a (stepF P win (fl X.e.now) X))
    rw [cntF_add P win fl Q a b (stepF P win (fl X.e.now) X)]
    omega

theorem cntF_mono (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool)
    (Q : Engine → Prop) [DecidablePred Q] (X : EngineF) (a : Nat) :
    ∀ (b : Nat), a ≤ b → cntF P win fl Q a X ≤ cntF P win fl Q b X
  | 0, h => by
    have : a = 0 := by omega
    subst this
    exact Nat.le_refl _
  | b + 1, h => by
    by_cases hab : a = b + 1
    · subst hab
      exact Nat.le_refl _
    · have ih := cntF_mono P win fl Q X a b (by omega)
      have := cntF_succ_back P win fl Q b X
      omega

theorem cntF_reach (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool)
    (Q : Engine → Prop) [DecidablePred Q] :
    ∀ (n : Nat) (X : EngineF) (j : Nat), j < cntF P win fl Q n X →
      ∃ t, t < n ∧ cntF P win fl Q t X = j ∧ Q (runF P win fl t X).e
  | 0, X, j, h => by simp [cntF] at h
  | n + 1, X, j, h => by
    have e1 : cntF P win fl Q (n + 1) X
        = (if Q X.e then 1 else 0) + cntF P win fl Q n (stepF P win (fl X.e.now) X) := rfl
    by_cases hq : Q X.e
    · rw [if_pos hq] at e1
      cases j with
      | zero => exact ⟨0, Nat.succ_pos n, rfl, hq⟩
      | succ j =>
        have h' : j < cntF P win fl Q n (stepF P win (fl X.e.now) X) := by omega
        obtain ⟨t, ht, hc, hq'⟩ := cntF_reach P win fl Q n (stepF P win (fl X.e.now) X) j h'
        have e2 : cntF P win fl Q (t + 1) X
            = (if Q X.e then 1 else 0) + cntF P win fl Q t (stepF P win (fl X.e.now) X) := rfl
        rw [if_pos hq] at e2
        exact ⟨t + 1, by omega, by omega, hq'⟩
    · rw [if_neg hq] at e1
      have h' : j < cntF P win fl Q n (stepF P win (fl X.e.now) X) := by omega
      obtain ⟨t, ht, hc, hq'⟩ := cntF_reach P win fl Q n (stepF P win (fl X.e.now) X) j h'
      have e2 : cntF P win fl Q (t + 1) X
          = (if Q X.e then 1 else 0) + cntF P win fl Q t (stepF P win (fl X.e.now) X) := rfl
      rw [if_neg hq] at e2
      exact ⟨t + 1, by omega, by omega, hq'⟩

theorem cntF_zero_of (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool)
    (Q : Engine → Prop) [DecidablePred Q] (t : Nat) (X : EngineF)
    (h : ∀ s, s < t → ¬Q (runF P win fl s X).e) : cntF P win fl Q t X = 0 := by
  rcases Nat.eq_zero_or_pos (cntF P win fl Q t X) with h0 | hpos
  · exact h0
  · obtain ⟨s, hs, _, hq⟩ := cntF_reach P win fl Q t X 0 hpos
    exact absurd hq (h s hs)

theorem cntF_decOther_split (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool)
    (i : Lane) :
    ∀ (n : Nat) (X : EngineF),
      cntF P win fl (fun e => decOther win i e = true) n X + cntF P win fl (Dec win i) n X
        = cntF P win fl (fun e => decAny win e = true) n X
  | 0, X => by simp [cntF]
  | n + 1, X => by
    have ih := cntF_decOther_split P win fl i n (stepF P win (fl X.e.now) X)
    have h := decOther_split win i X.e
    have e0 : cntF P win fl (fun e => decOther win i e = true) (n + 1) X
        = (if decOther win i X.e = true then 1 else 0)
          + cntF P win fl (fun e => decOther win i e = true) n (stepF P win (fl X.e.now) X) := rfl
    have e1 : cntF P win fl (Dec win i) (n + 1) X
        = (if Dec win i X.e then 1 else 0)
          + cntF P win fl (Dec win i) n (stepF P win (fl X.e.now) X) := rfl
    have e2 : cntF P win fl (fun e => decAny win e = true) (n + 1) X
        = (if decAny win X.e = true then 1 else 0)
          + cntF P win fl (fun e => decAny win e = true) n (stepF P win (fl X.e.now) X) := rfl
    omega

theorem cntF_decAny_split (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool) :
    ∀ (n : Nat) (X : EngineF),
      cntF P win fl (fun e => decAny win e = true) n X
        = cntF P win fl (Dec win L0) n X + cntF P win fl (Dec win L1) n X
          + cntF P win fl (Dec win L2) n X + cntF P win fl (Dec win L3) n X
          + cntF P win fl (Dec win L4) n X
  | 0, X => by simp [cntF]
  | n + 1, X => by
    have ih := cntF_decAny_split P win fl n (stepF P win (fl X.e.now) X)
    have h := decAny_split win X.e
    have e0 : cntF P win fl (fun e => decAny win e = true) (n + 1) X
        = (if decAny win X.e = true then 1 else 0)
          + cntF P win fl (fun e => decAny win e = true) n (stepF P win (fl X.e.now) X) := rfl
    have e1 : cntF P win fl (Dec win L0) (n + 1) X
        = (if Dec win L0 X.e then 1 else 0)
          + cntF P win fl (Dec win L0) n (stepF P win (fl X.e.now) X) := rfl
    have e2 : cntF P win fl (Dec win L1) (n + 1) X
        = (if Dec win L1 X.e then 1 else 0)
          + cntF P win fl (Dec win L1) n (stepF P win (fl X.e.now) X) := rfl
    have e3 : cntF P win fl (Dec win L2) (n + 1) X
        = (if Dec win L2 X.e then 1 else 0)
          + cntF P win fl (Dec win L2) n (stepF P win (fl X.e.now) X) := rfl
    have e4 : cntF P win fl (Dec win L3) (n + 1) X
        = (if Dec win L3 X.e then 1 else 0)
          + cntF P win fl (Dec win L3) n (stepF P win (fl X.e.now) X) := rfl
    have e5 : cntF P win fl (Dec win L4) (n + 1) X
        = (if Dec win L4 X.e then 1 else 0)
          + cntF P win fl (Dec win L4) n (stepF P win (fl X.e.now) X) := rfl
    omega

/-- Two decisions of a lane along `runF` are a dispatch apart. -/
theorem dec_sepF (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool)
    (X : EngineF) (z : Lane) (a b : Nat) (hab : a < b) (ha : Dec win z (runF P win fl a X).e)
    (hb : Dec win z (runF P win fl b X).e) : a + 3 ≤ b := by
  obtain ⟨hbi, -, -⟩ := hb
  have hst1 : (runF P win fl (a + 1) X).e.st = .drive := by
    rw [runF_succ']
    exact (step_of_dec P win _ z ha).1
  have hst2 : (runF P win fl (a + 2) X).e.st = .wb := (dec_wbF P win fl X a z ha).1
  rcases Nat.lt_or_ge b (a + 3) with hlt | hge
  · exfalso
    have : b = a + 1 ∨ b = a + 2 := by omega
    rcases this with rfl | rfl
    · rw [hst1] at hbi
      cases hbi
    · rw [hst2] at hbi
      cases hbi
  · exact hge

theorem wb_iff_decF (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool)
    (X0 : EngineF) (h0 : X0.e.st = .idle) (z : Lane) (x : Nat) :
    IsWB z (runF P win fl (x + 2) X0).e ↔ Dec win z (runF P win fl x X0).e := by
  constructor
  · intro h
    obtain ⟨s, hs, hd⟩ := wb_backF P win fl X0 h0 (x + 2) z h
    have : s = x := by omega
    subst this
    exact hd
  · exact dec_wbF P win fl X0 x z

/-- Writebacks counted from `a + 2` are the decisions counted from `a`, along `runF`. -/
theorem cntF_wb_shift (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool)
    (X0 : EngineF) (h0 : X0.e.st = .idle) (z : Lane) :
    ∀ n a, cntF P win fl (IsWB z) n (runF P win fl (a + 2) X0)
      = cntF P win fl (Dec win z) n (runF P win fl a X0)
  | 0, _ => by simp [cntF]
  | n + 1, a => by
    have s1 := runF_succ' P win fl (a + 2) X0
    have s2 := runF_succ' P win fl a X0
    have e1 : cntF P win fl (IsWB z) (n + 1) (runF P win fl (a + 2) X0)
        = (if IsWB z (runF P win fl (a + 2) X0).e then 1 else 0)
          + cntF P win fl (IsWB z) n (runF P win fl (a + 1 + 2) X0) := by
      rw [show a + 1 + 2 = a + 2 + 1 by omega, s1]
      rfl
    have e2 : cntF P win fl (Dec win z) (n + 1) (runF P win fl a X0)
        = (if Dec win z (runF P win fl a X0).e then 1 else 0)
          + cntF P win fl (Dec win z) n (runF P win fl (a + 1) X0) := by
      rw [s2]
      rfl
    rw [e1, e2, cntF_wb_shift P win fl X0 h0 z n (a + 1)]
    by_cases h : Dec win z (runF P win fl a X0).e
    · rw [if_pos h, if_pos ((wb_iff_decF P win fl X0 h0 z a).mpr h)]
    · rw [if_neg h, if_neg (fun h' => h ((wb_iff_decF P win fl X0 h0 z a).mp h'))]

/-! ### The closure on `runF` -/

/-- **The per-lane response bounds on the flush run, in span form.** Every writeback of every
live lane never flushed lands within `R y + 2` of its release, before `T`. -/
theorem wb_close_spanF (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool)
    (X0 : EngineF) (T S : Nat) (R m G : Lane → Nat) (fz : Lane → Bool)
    (h0 : X0.e.st = .idle) (h0ts : ∀ l, X0.e.now ≤ X0.e.ts l)
    (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
    (hm1 : ∀ z, 1 ≤ m z)
    (hfz : ∀ y t, fz y = false → fl t y = false)
    (hRz : ∀ z t, fz z = true → t < T → P.live z = true → IsWB z (runF P win fl t X0).e →
      (runF P win fl t X0).e.now ≤ (runF P win fl t X0).e.ts z + R z + 2)
    (hS : ∀ y c, P.live y = true → fz y = false → c + (R y + 1) + 2 ≤ T →
      cntF P win fl (fun e => noDecB win e = true) (R y + 1) (runF P win fl c X0) ≤ S)
    (hspan : ∀ z x1 n, IsWB z (runF P win fl x1 X0).e →
      cntF P win fl (IsWB z) n (runF P win fl x1 X0) = m z →
      (∀ x, x1 ≤ x → x < x1 + n → IsWB z (runF P win fl x X0).e →
        (runF P win fl x X0).e.now ≤ (runF P win fl x X0).e.ts z + R z + 2) →
      (runF P win fl x1 X0).e.ts z + G z ≤ (runF P win fl (x1 + n) X0).e.ts z)
    (hrel : ∀ y x, fz y = false → IsWB y (runF P win fl x X0).e →
      (runF P win fl x X0).e.now ≤ (runF P win fl x X0).e.ts y + R y + 2 →
      (runF P win fl x X0).e.now < (runF P win fl (x + 1) X0).e.ts y)
    (hG : ∀ y z, z ≠ y → R y + 1 + R z ≤ G z)
    (hK : ∀ y, 3 * (m L0 + m L1 + m L2 + m L3 + m L4 - m y) + S + 3 ≤ R y + 1) :
    ∀ t, t < T → ∀ y, P.live y = true → fz y = false → IsWB y (runF P win fl t X0).e →
      (runF P win fl t X0).e.now ≤ (runF P win fl t X0).e.ts y + R y + 2 := by
  have key : ∀ n, ∀ t, t < n → t < T → ∀ y, P.live y = true → fz y = false →
      IsWB y (runF P win fl t X0).e →
      (runF P win fl t X0).e.now ≤ (runF P win fl t X0).e.ts y + R y + 2 := by
    intro n
    induction n with
    | zero => intro t ht; exact absurd ht (Nat.not_lt_zero t)
    | succ n ih =>
      intro t ht htT y hy hyf hwb
      rcases Nat.lt_or_ge t n with htn | htn
      · exact ih t htn htT y hy hyf hwb
      · -- every live lane's earlier writebacks: the induction, or the flushed lane's own bound
        have IHz : ∀ t', t' < t → ∀ z, P.live z = true → IsWB z (runF P win fl t' X0).e →
            (runF P win fl t' X0).e.now ≤ (runF P win fl t' X0).e.ts z + R z + 2 := by
          intro t' ht' z hz hw
          cases hfzz : fz z with
          | true => exact hRz z t' hfzz (by omega) hz hw
          | false => exact ih t' (by omega) (by omega) z hz hfzz hw
        have hfy : ∀ s, fl s y = false := fun s => hfz y s hyf
        have hw := wb_bound_winF P win fl X0 h0 h0ts y hy hfy
          (m L0 + m L1 + m L2 + m L3 + m L4 - m y) S (R y + 1) (hK y) t hwb
          (fun w hw hwbw => by
            have hr := IHz w (by omega) y hy hwbw
            have h1 := hrel y w hyf hwbw hr
            have h2 := ts_monoF P win fl y hfy X0 (w + 1) (t - (w + 1))
            rw [show w + 1 + (t - (w + 1)) = t by omega] at h2
            omega)
          (fun c hc => by
            have hz : ∀ z, z ≠ y → cntF P win fl (Dec win z) (R y + 1) (runF P win fl c X0)
                ≤ m z := by
              intro z hzy
              rcases Nat.lt_or_ge (cntF P win fl (Dec win z) (R y + 1) (runF P win fl c X0))
                  (m z + 1) with hlt | hge
              · omega
              · exfalso
                obtain ⟨i, hi, hci, hdi⟩ := cntF_reach P win fl (Dec win z) (R y + 1)
                  (runF P win fl c X0) 0 (by omega)
                obtain ⟨j, hj, hcj, hdj⟩ := cntF_reach P win fl (Dec win z) (R y + 1)
                  (runF P win fl c X0) (m z) (by omega)
                rw [← runF_add] at hdi hdj
                have hij : i < j := by
                  rcases Nat.lt_or_ge i j with h' | h'
                  · exact h'
                  · have := cntF_mono P win fl (Dec win z) (runF P win fl c X0) j i h'
                    have := hm1 z
                    omega
                have h3 := dec_sepF P win fl X0 z (c + i) (c + j) (by omega) hdi hdj
                have hsplit := cntF_add P win fl (Dec win z) i (j - i) (runF P win fl c X0)
                rw [show i + (j - i) = j by omega, ← runF_add] at hsplit
                have hsplit2 := cntF_add P win fl (Dec win z) (j - i - 2) 2
                  (runF P win fl (c + i) X0)
                rw [show j - i - 2 + 2 = j - i by omega, ← runF_add] at hsplit2
                have hlast : cntF P win fl (Dec win z) 2
                    (runF P win fl (c + i + (j - i - 2)) X0) = 0 :=
                  cntF_zero_of P win fl (Dec win z) 2 _ (fun s hs hds => by
                    rw [← runF_add] at hds
                    have := dec_sepF P win fl X0 z (c + i + (j - i - 2) + s) (c + j)
                      (by omega) hds hdj
                    omega)
                have hshift := cntF_wb_shift P win fl X0 h0 z (j - i - 2) (c + i)
                have hlz := (hwin _ z hdi.2.1).1
                have hwbi := dec_wbF P win fl X0 (c + i) z hdi
                have hsp := hspan z (c + i + 2) (j - i - 2) hwbi (by omega)
                  (fun x hx1 hx2 hxw => IHz x (by omega) z hlz hxw)
                rw [show c + i + 2 + (j - i - 2) = c + j by omega] at hsp
                have hr := IHz (c + i + 2) (by omega) z hlz hwbi
                have hrdy := (hwin _ z hdj.2.1).2
                have hni := now_runF P win fl (c + i + 2) X0
                have hnj := now_runF P win fl (c + j) X0
                have hg := hG y z hzy
                omega
            have hs := cntF_decOther_split P win fl y (R y + 1) (runF P win fl c X0)
            have ha := cntF_decAny_split P win fl (R y + 1) (runF P win fl c X0)
            rcases lane_cases y with rfl | rfl | rfl | rfl | rfl
            · have a := hz L1 (by decide); have b := hz L2 (by decide)
              have c' := hz L3 (by decide); have d := hz L4 (by decide); omega
            · have a := hz L0 (by decide); have b := hz L2 (by decide)
              have c' := hz L3 (by decide); have d := hz L4 (by decide); omega
            · have a := hz L0 (by decide); have b := hz L1 (by decide)
              have c' := hz L3 (by decide); have d := hz L4 (by decide); omega
            · have a := hz L0 (by decide); have b := hz L1 (by decide)
              have c' := hz L2 (by decide); have d := hz L4 (by decide); omega
            · have a := hz L0 (by decide); have b := hz L1 (by decide)
              have c' := hz L2 (by decide); have d := hz L3 (by decide); omega)
          (fun c hc => hS y c hy hyf (by omega))
        omega
  intro t ht
  exact key (t + 1) t (Nat.lt_succ_self t) ht

/-! ### On the engine with ARM registers -/

section
variable (P2 : Program2) (Wn : Nat) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
  (hedge : ∀ t l, t + 1 ≤ edge t l) (sched : EngineT → Option Lane) (X0 : EngineT)
  (hX0 : InvT Wn X0) (hf : ∀ y, ArmFragT Wn (fw y)) (hsw : SchedT sched)

include hedge hX0 hf hsw in
/-- **The per-lane bounds on the FALLTHROUGH engine, in span form** (the usbdev stamps): every
lane never flushed closes within `R y + 2` of its view release (`relT`) on `run3T`; the premises
are `wb_close_spanF`'s, on the run's view (`runF_e`). -/
theorem wb_close_spanT (h0 : X0.x.e.st = .idle) (h0ts : ∀ l, X0.x.e.now ≤ relT X0 l)
    (T S : Nat) (R m G : Lane → Nat) (fz : Lane → Bool)
    (hwin : ∀ e w, winT P2 fw edge sched X0 e = some w →
      (armPT P2 fw edge sched X0).live w = true ∧ e.ts w ≤ e.now)
    (hm1 : ∀ z, 1 ≤ m z)
    (hfz : ∀ y t, fz y = false → flR P2 fw edge sched X0 t y = false)
    (hRz : ∀ z t, fz z = true → t < T → (armPT P2 fw edge sched X0).live z = true →
      IsWB z (πT (run3T P2 fw edge sched t X0)) →
      (run3T P2 fw edge sched t X0).x.e.now ≤ relT (run3T P2 fw edge sched t X0) z + R z + 2)
    (hS : ∀ y c, (armPT P2 fw edge sched X0).live y = true → fz y = false →
      c + (R y + 1) + 2 ≤ T →
      cntF (armPT P2 fw edge sched X0) (winT P2 fw edge sched X0) (flR P2 fw edge sched X0)
        (fun e => noDecB (winT P2 fw edge sched X0) e = true) (R y + 1)
        (πF (run3T P2 fw edge sched c X0)) ≤ S)
    (hspan : ∀ z x1 n, IsWB z (πT (run3T P2 fw edge sched x1 X0)) →
      cntF (armPT P2 fw edge sched X0) (winT P2 fw edge sched X0) (flR P2 fw edge sched X0)
        (IsWB z) n (πF (run3T P2 fw edge sched x1 X0)) = m z →
      (∀ x, x1 ≤ x → x < x1 + n → IsWB z (πT (run3T P2 fw edge sched x X0)) →
        (run3T P2 fw edge sched x X0).x.e.now ≤ relT (run3T P2 fw edge sched x X0) z + R z + 2) →
      relT (run3T P2 fw edge sched x1 X0) z + G z ≤ relT (run3T P2 fw edge sched (x1 + n) X0) z)
    (hrel : ∀ y x, fz y = false → IsWB y (πT (run3T P2 fw edge sched x X0)) →
      (run3T P2 fw edge sched x X0).x.e.now ≤ relT (run3T P2 fw edge sched x X0) y + R y + 2 →
      (run3T P2 fw edge sched x X0).x.e.now < relT (run3T P2 fw edge sched (x + 1) X0) y)
    (hG : ∀ y z, z ≠ y → R y + 1 + R z ≤ G z)
    (hK : ∀ y, 3 * (m L0 + m L1 + m L2 + m L3 + m L4 - m y) + S + 3 ≤ R y + 1) :
    ∀ t, t < T → ∀ y, (armPT P2 fw edge sched X0).live y = true → fz y = false →
      IsWB y (πT (run3T P2 fw edge sched t X0)) →
      (run3T P2 fw edge sched t X0).x.e.now ≤ relT (run3T P2 fw edge sched t X0) y + R y + 2 := by
  have hpr := run3T_proj P2 Wn fw edge hedge sched X0 hX0 hf hsw
  have hE := runF_e P2 Wn fw edge hedge sched X0 hX0 hf hsw
  intro t ht y hy hyf hwb
  have key := wb_close_spanF (armPT P2 fw edge sched X0) (winT P2 fw edge sched X0)
    (flR P2 fw edge sched X0) (πF X0) T S R m G fz h0 h0ts hwin hm1 hfz
    (fun z t' hz ht' hl hw => by
      rw [hE] at hw ⊢
      exact hRz z t' hz ht' hl hw)
    (fun y' c hl hf' hc => by rw [← hpr]; exact hS y' c hl hf' hc)
    (fun z x1 n hw hc hb => by
      rw [hE] at hw
      rw [← hpr] at hc
      rw [hE, hE]
      exact hspan z x1 n hw hc (fun x hx1 hx2 hxw => by
        have := hb x hx1 hx2 (by rw [hE]; exact hxw)
        rw [hE] at this
        exact this))
    (fun y' x hf' hw hb => by
      rw [hE] at hw hb
      rw [hE, hE]
      exact hrel y' x hf' hw hb)
    hG hK t ht y hy hyf (by rw [hE]; exact hwb)
  rw [hE] at key
  exact key

end

end JLane
