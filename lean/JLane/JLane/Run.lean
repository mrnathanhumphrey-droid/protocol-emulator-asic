import JLane.Head
/-!
# Brick 8 — lateness on the run
For one lane `y` with period `d`, up to a horizon `T`: a pending refill #k is never
older than `R + 25 + B` past release `k`, given
* `hR` — every writeback of `y` lands within `R + 2` of its release (EDF response);
* `hB` — every window of length ≤ `23 + B` has branch-1 charge ≤ `B`.
Corollary: with `D* + B ≤ d` and `R + 26 + B ≤ 2d`, `y`'s head is valid whenever
`y` is ready.
-/
namespace JLane

/-! ### Runs, clocks and counters -/

theorem run_succ' (P : Program) (win : Engine → Option Lane) :
    ∀ (n : Nat) (e : Engine), run P win (n + 1) e = step P win (run P win n e)
  | 0, _ => rfl
  | n + 1, e => run_succ' P win n (step P win e)

theorem run_add (P : Program) (win : Engine → Option Lane) :
    ∀ (a i : Nat) (e : Engine), run P win (a + i) e = run P win i (run P win a e)
  | 0, i, e => by
    show run P win (0 + i) e = run P win i e
    rw [Nat.zero_add]
  | a + 1, i, e => by
    rw [Nat.add_right_comm]
    show run P win (a + i) (step P win e) = run P win i (run P win a (step P win e))
    exact run_add P win a i (step P win e)

theorem now_run (P : Program) (win : Engine → Option Lane) :
    ∀ (n : Nat) (e : Engine), (run P win n e).now = e.now + n
  | 0, _ => rfl
  | n + 1, e => by
    have := now_run P win n (step P win e)
    show (run P win n (step P win e)).now = e.now + (n + 1)
    rw [this]
    show e.now + 1 + n = e.now + (n + 1)
    omega

theorem ts_step (P : Program) (win : Engine → Option Lane) (e : Engine) (y : Lane) :
    (step P win e).ts y = e.ts y + (if IsWB y e then P.dly y + P.ext e.now y else 0) := by
  show tsNext P e y = e.ts y + (if IsWB y e then P.dly y + P.ext e.now y else 0)
  unfold tsNext
  by_cases h : IsWB y e
  · have h' : e.st = .wb ∧ e.cur = y := h
    rw [if_pos h, if_pos ⟨h'.1, h'.2.symm⟩, Nat.add_assoc]
  · rw [if_neg h, if_neg (fun h' => h ⟨h'.1, h'.2.symm⟩), Nat.add_zero]

/-- Every writeback adds at least the lane's minimum delay. -/
theorem ts_run_ge (P : Program) (win : Engine → Option Lane) (y : Lane) :
    ∀ (n : Nat) (e : Engine),
      e.ts y + P.dly y * cnt P win (IsWB y) n e ≤ (run P win n e).ts y
  | 0, e => by simp [run, cnt]
  | n + 1, e => by
    have ih := ts_run_ge P win y n (step P win e)
    have h1 := ts_step P win e y
    have e1 : cnt P win (IsWB y) (n + 1) e
        = (if IsWB y e then 1 else 0) + cnt P win (IsWB y) n (step P win e) := rfl
    have e3 : run P win (n + 1) e = run P win n (step P win e) := rfl
    rw [e3, e1, Nat.mul_add]
    by_cases h : IsWB y e
    · rw [if_pos h] at h1 ⊢
      rw [Nat.mul_one]
      omega
    · rw [if_neg h] at h1 ⊢
      rw [Nat.mul_zero]
      omega

theorem cnt_mono (P : Program) (win : Engine → Option Lane) (Q : Engine → Prop)
    [DecidablePred Q] (e : Engine) (a : Nat) :
    ∀ (b : Nat), a ≤ b → cnt P win Q a e ≤ cnt P win Q b e
  | 0, h => by
    have : a = 0 := by omega
    subst this
    exact Nat.le_refl _
  | b + 1, h => by
    by_cases hab : a = b + 1
    · subst hab
      exact Nat.le_refl _
    · have ih := cnt_mono P win Q e a b (by omega)
      have := cnt_succ_back P win Q b e
      omega

theorem no_event_between (P : Program) (win : Engine → Option Lane) (Q : Engine → Prop)
    [DecidablePred Q] (e : Engine) (a b i : Nat) (hai : a ≤ i) (hib : i < b)
    (heq : cnt P win Q a e = cnt P win Q b e) : ¬Q (run P win i e) := by
  intro hq
  have h1 := cnt_mono P win Q e a i hai
  have h2 := cnt_mono P win Q e (i + 1) b hib
  have h3 := cnt_succ_back P win Q i e
  rw [if_pos hq] at h3
  omega

/-! ### Timestamps under variable delays -/

/-- Counters add along a run. -/
theorem cnt_add (P : Program) (win : Engine → Option Lane) (Q : Engine → Prop)
    [DecidablePred Q] :
    ∀ (a k : Nat) (e : Engine),
      cnt P win Q (a + k) e = cnt P win Q a e + cnt P win Q k (run P win a e)
  | 0, k, e => by
    show cnt P win Q (0 + k) e = 0 + cnt P win Q k e
    rw [Nat.zero_add, Nat.zero_add]
  | a + 1, k, e => by
    rw [Nat.add_right_comm]
    show (if Q e then 1 else 0) + cnt P win Q (a + k) (step P win e)
        = ((if Q e then 1 else 0) + cnt P win Q a (step P win e))
          + cnt P win Q k (run P win a (step P win e))
    rw [cnt_add P win Q a k (step P win e)]
    omega

/-- **Flat between writebacks.** With no writeback of `y` between `a` and `a + k`, its
timestamp is unchanged: the release of job `k` is well defined. -/
theorem ts_flat_cnt (P : Program) (win : Engine → Option Lane) (y : Lane) (e : Engine)
    (a : Nat) :
    ∀ k, cnt P win (IsWB y) a e = cnt P win (IsWB y) (a + k) e →
      (run P win (a + k) e).ts y = (run P win a e).ts y
  | 0, _ => rfl
  | k + 1, h => by
    have hm := cnt_mono P win (IsWB y) e a (a + k) (by omega)
    have hm2 := cnt_mono P win (IsWB y) e (a + k) (a + k + 1) (by omega)
    have hk : cnt P win (IsWB y) a e = cnt P win (IsWB y) (a + k) e := by
      rw [← Nat.add_assoc] at h
      omega
    have hnw : ¬IsWB y (run P win (a + k) e) := by
      have hb := cnt_succ_back P win (IsWB y) (a + k) e
      intro hw
      rw [if_pos hw] at hb
      rw [← Nat.add_assoc] at h
      omega
    rw [← Nat.add_assoc, run_succ', ts_step, if_neg hnw, Nat.add_zero]
    exact ts_flat_cnt P win y e a k hk

/-- **At least `dly` per writeback.** Between `a` and `a + k`, the timestamp grows by at
least the lane's minimum delay times the number of its writebacks in between. -/
theorem ts_spacing (P : Program) (win : Engine → Option Lane) (y : Lane) (e : Engine)
    (a k : Nat) :
    (run P win a e).ts y
        + P.dly y * (cnt P win (IsWB y) (a + k) e - cnt P win (IsWB y) a e)
      ≤ (run P win (a + k) e).ts y := by
  have h1 := ts_run_ge P win y k (run P win a e)
  have h2 := cnt_add P win (IsWB y) a k e
  rw [← run_add] at h1
  rw [h2, Nat.add_sub_cancel_left]
  exact h1

theorem dly_le_mul (d x : Nat) (h : 1 ≤ x) : d ≤ d * x := by
  cases x with
  | zero => omega
  | succ x =>
    rw [Nat.mul_succ]
    omega

/-- **One writeback is enough.** A writeback of `y` at `a` puts its release at least
`dly` higher by any later cycle `b`, however many more writebacks come in between. -/
theorem ts_ge_after_wb (P : Program) (win : Engine → Option Lane) (y : Lane) (e : Engine)
    (a b : Nat) (hab : a < b) (hw : IsWB y (run P win a e)) :
    (run P win a e).ts y + P.dly y ≤ (run P win b e).ts y := by
  have hsp := ts_spacing P win y e a (b - a)
  have hba : a + (b - a) = b := by omega
  rw [hba] at hsp
  have h1 := cnt_succ_back P win (IsWB y) a e
  rw [if_pos hw] at h1
  have h2 := cnt_mono P win (IsWB y) e (a + 1) b (by omega)
  have hm := dly_le_mul (P.dly y)
    (cnt P win (IsWB y) b e - cnt P win (IsWB y) a e) (by omega)
  omega

/-! ### Waits under a branch-1 budget -/

theorem window_le (P : Program) (win : Engine → Option Lane) (y : Lane)
    (hy : P.live y = true) (e : Engine) (B n : Nat) (hw : e.wantFetch y = true)
    (hB : ∀ m, m ≤ n → m ≤ 23 + B → chargeSum P win y m e ≤ B)
    (hnh : ∀ i, i < n → ¬Hit y (run P win i e)) : n ≤ 22 + B := by
  by_cases hn : n ≤ 23 + B
  · have h := port_wait_bound P win y hy n e hw hnh
    have := hB n (Nat.le_refl n) hn
    omega
  · have h := port_wait_bound P win y hy (23 + B) e hw (fun i hi => hnh i (by omega))
    have := hB (23 + B) (by omega) (Nat.le_refl _)
    omega

theorem window_le_19 (P : Program) (win : Engine → Option Lane) (y : Lane)
    (hy : P.live y = true) (e : Engine) (B n : Nat) (hw : e.wantFetch y = true)
    (hq : e.pst = .scan ∨ e.pbr1 = false)
    (hB : ∀ m, m ≤ n → m ≤ 23 + B → chargeSum P win y m e ≤ B)
    (hnh : ∀ i, i < n → ¬Hit y (run P win i e)) : n ≤ 19 + B := by
  by_cases hn : n ≤ 23 + B
  · have h := port_wait_bound_19 P win y hy n e hw hq hnh
    have := hB n (Nat.le_refl n) hn
    omega
  · have h := port_wait_bound_19 P win y hy (23 + B) e hw hq (fun i hi => hnh i (by omega))
    have := hB (23 + B) (by omega) (Nat.le_refl _)
    omega

/-! ### The pending bound -/

/-- Fresh case: every earlier refill of `y` was served by retirement `w` (#k). The bound is
against the actual release `ts(w)`, whatever the earlier writebacks added. -/
theorem pb_fresh (P : Program) (win : Engine → Option Lane) (y : Lane) (e0 : Engine)
    (R B T w t : Nat) (hy : P.live y = true)
    (hR : ∀ t, t < T → IsWB y (run P win t e0) →
      (run P win t e0).now ≤ (run P win t e0).ts y + R + 2)
    (hB : ∀ a m, a + m ≤ T → m ≤ 23 + B → chargeSum P win y m (run P win a e0) ≤ B)
    (hwt : w < t) (htT : t ≤ T)
    (hwb : IsRet P y (run P win w e0))
    (heq : cnt P win (Hit y) (w + 1) e0 = cnt P win (Hit y) t e0) :
    e0.now + t ≤ (run P win w e0).ts y + R + 25 + B := by
  have hRw := hR w (by omega) (isWB_of_ret P y _ hwb)
  have hnow := now_run P win w e0
  obtain ⟨hst, hcur, hret⟩ := hwb
  have hwant : (run P win (w + 1) e0).wantFetch y = true := by
    rw [run_succ', ← hcur]
    exact wb_owes P win (run P win w e0) hst (by rw [hcur]; exact hret)
  have hn := window_le P win y hy (run P win (w + 1) e0) B (t - (w + 1)) hwant
    (fun m hm hm' => hB (w + 1) m (by omega) hm')
    (fun i hi => by
      rw [← run_add]
      exact no_event_between P win (Hit y) e0 (w + 1) t (w + 1 + i)
        (by omega) (by omega) heq)
  omega

/-- **The pending bound.** If retirement #k of lane `y` is at `w < t` and refill #k is still
pending at `t ≤ T`, then `t` is at most `R + 25 + B` past that job's actual release `ts(w)`.
Needs only that every writeback adds at least `d = P.dly y` (`ts_ge_after_wb`). -/
theorem pending_bound (P : Program) (win : Engine → Option Lane) (y : Lane) (e0 : Engine)
    (d R B T : Nat) (hW : Wf e0) (hfull : ∀ l s, P.live l = true → e0.actv l s = true)
    (hy : P.live y = true) (hdly : P.dly y = d) (hd : DSTAR + B ≤ d)
    (hR : ∀ t, t < T → IsWB y (run P win t e0) →
      (run P win t e0).now ≤ (run P win t e0).ts y + R + 2)
    (hB : ∀ a m, a + m ≤ T → m ≤ 23 + B → chargeSum P win y m (run P win a e0) ≤ B) :
    ∀ (k t w : Nat), t ≤ T → w < t → cnt P win (IsRet P y) w e0 = k →
      IsRet P y (run P win w e0) → cnt P win (Hit y) t e0 ≤ k →
      e0.now + t ≤ (run P win w e0).ts y + R + 25 + B := by
  have hS : Struct e0 := by
    have hw := hW
    unfold Wf at hw
    exact hw.1
  have h0 := owed_full e0 y (fun s => hfull y s hy)
  intro k
  induction k with
  | zero =>
    intro t w htT hwt hwk hwb hh
    have hm := cnt_mono P win (Hit y) e0 (w + 1) t (by omega)
    exact pb_fresh P win y e0 R B T w t hy hR hB hwt htT hwb (by omega)
  | succ k ih =>
    intro t w htT hwt hwk hwb hh
    have hm := cnt_mono P win (Hit y) e0 (w + 1) t (by omega)
    by_cases hfresh : k + 1 ≤ cnt P win (Hit y) (w + 1) e0
    · exact pb_fresh P win y e0 R B T w t hy hR hB hwt htT hwb (by omega)
    · -- the previous retirement, #k, at w' < w: a writeback, so its release is ≥ d earlier
      obtain ⟨w', hw'w, hw'k, hw'b⟩ := cnt_reach P win (IsRet P y) w e0 k (by omega)
      have hsp := ts_ge_after_wb P win y e0 w' w hw'w (isWB_of_ret P y _ hw'b)
      by_cases hlate : cnt P win (Hit y) t e0 ≤ k
      · -- refill #k is itself still pending at `t`
        have := ih t w' htT (by omega) hw'k hw'b hlate
        omega
      · -- refill #k landed at some `c` after retirement #(k+1); the wait restarts there
        obtain ⟨c, hct, hck, hhit⟩ := cnt_reach P win (Hit y) t e0 k (by omega)
        have hc1 : cnt P win (Hit y) (c + 1) e0 = k + 1 := by
          have := cnt_succ_back P win (Hit y) c e0
          rw [if_pos hhit] at this
          omega
        have hwc : w + 1 ≤ c := by
          rcases Nat.lt_or_ge c (w + 1) with hlt | hge
          · have := cnt_mono P win (Hit y) e0 (c + 1) (w + 1) hlt
            omega
          · exact hge
        have hwb1 : cnt P win (IsRet P y) (w + 1) e0 = k + 2 := by
          have := cnt_succ_back P win (IsRet P y) w e0
          rw [if_pos hwb] at this
          omega
        have hwbc := cnt_mono P win (IsRet P y) e0 (w + 1) c hwc
        have hwbc1 := cnt_mono P win (IsRet P y) e0 (w + 1) (c + 1) (by omega)
        have hic := ih c w' (by omega) (by omega) hw'k hw'b (by omega)
        have hwant : (run P win (c + 1) e0).wantFetch y = true := by
          rw [Engine.wantFetch_iff]
          have := owed_run P win y (c + 1) e0 hS
          omega
        have hscan : (run P win (c + 1) e0).pst = .scan := by
          rw [run_succ']
          exact hit_then_scan P win y (run P win c e0) hhit
        have heq : cnt P win (Hit y) (c + 1) e0 = cnt P win (Hit y) t e0 := by omega
        have hn := window_le_19 P win y hy (run P win (c + 1) e0) B (t - (c + 1)) hwant
          (Or.inl hscan)
          (fun m hm hm' => hB (c + 1) m (by omega) hm')
          (fun i hi => by
            rw [← run_add]
            exact no_event_between P win (Hit y) e0 (c + 1) t (c + 1 + i)
              (by omega) (by omega) heq)
        have hD : DSTAR = 20 := dstar_val
        omega

/-- **Corollary.** Under the throughput and latency conditions on the minimum delay `d`,
lane `y`'s head is valid at every cycle `t ≤ T` where `y` is ready. -/
theorem head_valid_when_ready (P : Program) (win : Engine → Option Lane) (y : Lane)
    (e0 : Engine) (d R B T : Nat) (hW : Wf e0) (hfull : ∀ l s, P.live l = true → e0.actv l s = true)
    (hy : P.live y = true) (hdly : P.dly y = d) (hd : DSTAR + B ≤ d)
    (hlat : R + 26 + B ≤ 2 * d)
    (hR : ∀ t, t < T → IsWB y (run P win t e0) →
      (run P win t e0).now ≤ (run P win t e0).ts y + R + 2)
    (hB : ∀ a m, a + m ≤ T → m ≤ 23 + B → chargeSum P win y m (run P win a e0) ≤ B)
    (t : Nat) (htT : t ≤ T)
    (hrdy : (run P win t e0).ts y ≤ (run P win t e0).now) :
    (run P win t e0).headValid y = true := by
  apply head_valid_of_counts P win y t e0 hW (fun s => hfull y s hy)
  by_cases hc : cnt P win (IsRet P y) t e0 ≤ cnt P win (Hit y) t e0 + 1
  · exact hc
  · exfalso
    have hnow := now_run P win t e0
    -- retirement #(J − 2), where J is the number of retirements so far
    obtain ⟨w, hwt, hwk, hwb⟩ :=
      cnt_reach P win (IsRet P y) t e0 (cnt P win (IsRet P y) t e0 - 2) (by omega)
    have hpb := pending_bound P win y e0 d R B T hW hfull hy hdly hd hR hB
      (cnt P win (IsRet P y) t e0 - 2) t w htT hwt hwk hwb (by omega)
    -- retirement #(J − 1), at some w2 strictly between w and t
    obtain ⟨w2, hw2t, hw2k, hw2b⟩ :=
      cnt_reach P win (IsRet P y) t e0 (cnt P win (IsRet P y) t e0 - 1) (by omega)
    have hww2 : w < w2 := by
      rcases Nat.lt_or_ge w w2 with hlt | hge
      · exact hlt
      · have := cnt_mono P win (IsRet P y) e0 w2 w hge
        omega
    -- each retirement is a writeback: the release moved at least 2d
    have hs1 := ts_ge_after_wb P win y e0 w w2 hww2 (isWB_of_ret P y _ hwb)
    have hs2 := ts_ge_after_wb P win y e0 w2 t hw2t (isWB_of_ret P y _ hw2b)
    omega

end JLane
