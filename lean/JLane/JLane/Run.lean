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
    (step P win e).ts y = e.ts y + (if IsWB y e then P.dly y else 0) := by
  show tsNext P e y = e.ts y + (if IsWB y e then P.dly y else 0)
  unfold tsNext
  by_cases h : IsWB y e
  · have h' : e.st = .wb ∧ e.cur = y := h
    rw [if_pos h, if_pos ⟨h'.1, h'.2.symm⟩]
  · rw [if_neg h, if_neg (fun h' => h ⟨h'.1, h'.2.symm⟩), Nat.add_zero]

/-- P8 on the run: the timestamp advances by `d` at each writeback. -/
theorem ts_run (P : Program) (win : Engine → Option Lane) (y : Lane) :
    ∀ (n : Nat) (e : Engine),
      (run P win n e).ts y = e.ts y + P.dly y * cnt P win (IsWB y) n e
  | 0, e => by simp [run, cnt]
  | n + 1, e => by
    have ih := ts_run P win y n (step P win e)
    have h1 := ts_step P win e y
    have e1 : cnt P win (IsWB y) (n + 1) e
        = (if IsWB y e then 1 else 0) + cnt P win (IsWB y) n (step P win e) := rfl
    have e3 : run P win (n + 1) e = run P win n (step P win e) := rfl
    rw [e3, ih, h1, e1, Nat.mul_add]
    by_cases h : IsWB y e
    · rw [if_pos h, if_pos h, Nat.mul_one] <;> omega
    · rw [if_neg h, if_neg h, Nat.mul_zero] <;> omega

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

/-- Fresh case: every earlier refill of `y` was served by writeback #k. -/
theorem pb_fresh (P : Program) (win : Engine → Option Lane) (y : Lane) (e0 : Engine)
    (d R B T k w t : Nat) (hy : P.live y = true) (hdly : P.dly y = d)
    (hR : ∀ t, t < T → IsWB y (run P win t e0) →
      (run P win t e0).now ≤ (run P win t e0).ts y + R + 2)
    (hB : ∀ a m, a + m ≤ T → m ≤ 23 + B → chargeSum P win y m (run P win a e0) ≤ B)
    (hwt : w < t) (htT : t ≤ T) (hwk : cnt P win (IsWB y) w e0 = k)
    (hwb : IsWB y (run P win w e0))
    (heq : cnt P win (Hit y) (w + 1) e0 = cnt P win (Hit y) t e0) :
    e0.now + t ≤ e0.ts y + k * d + R + 25 + B := by
  have hRw := hR w (by omega) hwb
  have hnow := now_run P win w e0
  have hts := ts_run P win y w e0
  rw [hdly, hwk] at hts
  have hcomm : d * k = k * d := Nat.mul_comm d k
  obtain ⟨hst, hcur⟩ := hwb
  have hwant : (run P win (w + 1) e0).wantFetch y = true := by
    rw [run_succ', ← hcur]
    exact wb_owes P win (run P win w e0) hst
  have hn := window_le P win y hy (run P win (w + 1) e0) B (t - (w + 1)) hwant
    (fun m hm hm' => hB (w + 1) m (by omega) hm')
    (fun i hi => by
      rw [← run_add]
      exact no_event_between P win (Hit y) e0 (w + 1) t (w + 1 + i)
        (by omega) (by omega) heq)
  omega

/-- **The pending bound.** If refill #k of lane `y` is still pending at cycle `t ≤ T`,
then `t` is at most `R + 25 + B` past the release of job `k`. -/
theorem pending_bound (P : Program) (win : Engine → Option Lane) (y : Lane) (e0 : Engine)
    (d R B T : Nat) (hW : Wf e0) (hfull : ∀ l s, P.live l = true → e0.actv l s = true)
    (hy : P.live y = true) (hdly : P.dly y = d) (hd : DSTAR + B ≤ d)
    (hR : ∀ t, t < T → IsWB y (run P win t e0) →
      (run P win t e0).now ≤ (run P win t e0).ts y + R + 2)
    (hB : ∀ a m, a + m ≤ T → m ≤ 23 + B → chargeSum P win y m (run P win a e0) ≤ B) :
    ∀ (k t : Nat), t ≤ T → k < cnt P win (IsWB y) t e0 → cnt P win (Hit y) t e0 ≤ k →
      e0.now + t ≤ e0.ts y + k * d + R + 25 + B := by
  have hS : Struct e0 := by
    have hw := hW
    unfold Wf at hw
    exact hw.1
  have h0 := owed_full e0 y (fun s => hfull y s hy)
  intro k
  induction k with
  | zero =>
    intro t htT hk hh
    obtain ⟨w, hwt, hwk, hwb⟩ := cnt_reach P win (IsWB y) t e0 0 hk
    have hm := cnt_mono P win (Hit y) e0 (w + 1) t (by omega)
    exact pb_fresh P win y e0 d R B T 0 w t hy hdly hR hB hwt htT hwk hwb (by omega)
  | succ k ih =>
    intro t htT hk hh
    obtain ⟨w, hwt, hwk, hwb⟩ := cnt_reach P win (IsWB y) t e0 (k + 1) hk
    have hm := cnt_mono P win (Hit y) e0 (w + 1) t (by omega)
    have hmul : (k + 1) * d = k * d + d := by rw [Nat.add_mul, Nat.one_mul]
    by_cases hfresh : k + 1 ≤ cnt P win (Hit y) (w + 1) e0
    · exact pb_fresh P win y e0 d R B T (k + 1) w t hy hdly hR hB hwt htT hwk hwb (by omega)
    · by_cases hlate : cnt P win (Hit y) t e0 ≤ k
      · -- refill #k is itself still pending at `t`
        have := ih t htT (by omega) hlate
        omega
      · -- refill #k landed at some `c` after writeback #(k+1); the wait restarts there
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
        have hwb1 : cnt P win (IsWB y) (w + 1) e0 = k + 2 := by
          have := cnt_succ_back P win (IsWB y) w e0
          rw [if_pos hwb] at this
          omega
        have hwbc := cnt_mono P win (IsWB y) e0 (w + 1) c hwc
        have hwbc1 := cnt_mono P win (IsWB y) e0 (w + 1) (c + 1) (by omega)
        have hic := ih c (by omega) (by omega) (by omega)
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

/-- **Corollary.** Under the throughput and latency conditions, lane `y`'s head is
valid at every cycle `t ≤ T` where `y` is ready. -/
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
  by_cases hc : cnt P win (IsWB y) t e0 ≤ cnt P win (Hit y) t e0 + 1
  · exact hc
  · exfalso
    have hts := ts_run P win y t e0
    have hnow := now_run P win t e0
    rw [hdly] at hts
    have hpb := pending_bound P win y e0 d R B T hW hfull hy hdly hd hR hB
      (cnt P win (IsWB y) t e0 - 2) t htT (by omega) (by omega)
    have hJ : 2 ≤ cnt P win (IsWB y) t e0 := by omega
    have hm : (cnt P win (IsWB y) t e0 - 2) * d + 2 * d = cnt P win (IsWB y) t e0 * d := by
      rw [← Nat.add_mul, Nat.sub_add_cancel hJ]
    have hc' := Nat.mul_comm d (cnt P win (IsWB y) t e0)
    omega

end JLane
