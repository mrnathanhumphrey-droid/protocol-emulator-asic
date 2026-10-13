import JLane.HoldRun
/-!
# Brick V3b-2 — the gate is open at every decision, and D* survives SDA holds
Induction on time. If the gate was open at every decision before `n`, the hold run is the
v1 run up to `n` (`runH_coinc`). A released lane with a running hold at an idle `n` would
trace back to a DRIVE at `t0 < n ≤ t0 + 18`, written back at `t0 + 1` within `14 + 2` of its
release (`wb_bound`), pushing its timestamp to `≥ t0 + 24` for `d ≥ 39`, with no further
writeback (it cannot be picked while gated) — so it is not released at `n`. Contradiction.
The arithmetic needs only `d ≥ 34`. Hold timing as measured (HC1): load visible at
decision + 2, gate open at decision + 20.
-/
namespace JLane

/-- A running hold counter traces back to one DRIVE of that lane, and counts down exactly. -/
theorem hcnt_origin (P2 : Program2) (fw : Engine2 → Word) (hl : EngineH → Bool)
    (sched : EngineH → Option Lane) (y0 : EngineH) (l : Lane) (hh0 : y0.hcnt l = 0) :
    ∀ n, (runH P2 fw hl sched n y0).hcnt l ≠ 0 →
      ∃ t0, t0 < n ∧ (runH P2 fw hl sched t0 y0).x.e.st = .drive ∧
        (runH P2 fw hl sched t0 y0).x.e.cur = l ∧
        ∀ u, t0 < u → u ≤ n → (runH P2 fw hl sched u y0).hcnt l + u = t0 + SDA_HS + 1
  | 0, h => absurd hh0 h
  | n + 1, h => by
    rw [runH_succ'] at h
    by_cases hY : (runH P2 fw hl sched n y0).hcnt l = 0
    · by_cases hc : (runH P2 fw hl sched n y0).x.e.st = .drive ∧
          l = (runH P2 fw hl sched n y0).x.e.cur ∧ hl (runH P2 fw hl sched n y0) = true
      · have hv : (runH P2 fw hl sched (n + 1) y0).hcnt l = SDA_HS := by
          rw [runH_succ', hc.2.1]
          exact hcnt_load P2 fw hl _ _ hc.1 (by rw [← hc.2.1]; exact hY) hc.2.2
        refine ⟨n, by omega, hc.1, hc.2.1.symm, fun u hu1 hu2 => ?_⟩
        have hu : u = n + 1 := by omega
        subst hu
        omega
      · exact absurd (hcnt_zero_stay P2 fw hl _ _ l hY hc) h
    · obtain ⟨t0, ht0, hd, hcur, hval⟩ := hcnt_origin P2 fw hl sched y0 l hh0 n hY
      have hdec : (runH P2 fw hl sched (n + 1) y0).hcnt l =
          (runH P2 fw hl sched n y0).hcnt l - 1 := by
        rw [runH_succ']
        exact hcnt_dec P2 fw hl _ _ l _ (by omega)
      refine ⟨t0, by omega, hd, hcur, fun u hu1 hu2 => ?_⟩
      by_cases hun : u ≤ n
      · exact hval u hu1 hun
      · have hu : u = n + 1 := by omega
        have := hval n (by omega) (Nat.le_refl n)
        subst hu
        omega

/-- With no writeback of `y` in `[a, a + k)`, its timestamp is unchanged. -/
theorem ts_flat_run (P : Program) (win : Engine → Option Lane) (y : Lane) (e : Engine)
    (a : Nat) :
    ∀ k, (∀ s, a ≤ s → s < a + k → ¬IsWB y (run P win s e)) →
      (run P win (a + k) e).ts y = (run P win a e).ts y
  | 0, _ => rfl
  | k + 1, h => by
    rw [← Nat.add_assoc, ts_flat P win y e (a + k) (h (a + k) (by omega) (by omega))]
    exact ts_flat_run P win y e a k (fun s h1 h2 => h s h1 (by omega))

/-- **The gate step.** If the gate was open at every decision before `n`, it is open at `n`. -/
theorem gate_open_at (P2 : Program2) (dly : Lane → Nat) (fw : Engine2 → Word)
    (hl : EngineH → Bool) (sched : EngineH → Option Lane) (y0 : EngineH)
    (hx0 : Plain dly y0.x) (hf : ∀ y, PlainW dly y.e.pl (fw y))
    (hW : Wf y0.x.e) (hfull : ∀ l s, P2.live l = true → y0.x.e.actv l s = true)
    (h0 : y0.x.e.st = .idle) (h0ts : ∀ l, y0.x.e.now ≤ y0.x.e.ts l)
    (hh0 : ∀ l, y0.hcnt l = 0)
    (hsw : ∀ y w, sched y = some w →
      (P2.toP dly).live w = true ∧ y.x.e.ts w ≤ y.x.e.now ∧ y.hcnt w = 0)
    (hss : ∀ y l, y.x.e.st = .idle →
      (P2.toP dly).live l = true ∧ y.x.e.ts l ≤ y.x.e.now ∧ y.hcnt l = 0 → sched y ≠ none)
    (hd : ∀ l, P2.live l = true → 39 ≤ dly l)
    (n : Nat) (hI : ∀ m, m < n → GateOpen (P2.toP dly) (runH P2 fw hl sched m y0)) :
    GateOpen (P2.toP dly) (runH P2 fw hl sched n y0) := by
  intro hidle l hrdy
  by_cases hz : (runH P2 fw hl sched n y0).hcnt l = 0
  · exact hz
  exfalso
  have hS : SDA_HS = 18 := rfl
  -- the v1 run under win1H: meets the v1 contract everywhere, so stall-free forever
  have hwin := win1H_ready (P2.toP dly) P2 fw hl sched y0
  have hws := win1H_wc (P2.toP dly) P2 fw hl sched y0
  have hNS : ∀ t, NoStall (win1H (P2.toP dly) P2 fw hl sched y0)
      (run (P2.toP dly) (win1H (P2.toP dly) P2 fw hl sched y0) t y0.x.e) := fun t =>
    (dstar39 (P2.toP dly) (win1H (P2.toP dly) P2 fw hl sched y0) y0.x.e hW hfull h0 h0ts
      hwin hws hd t).1
  have hd29 : ∀ l, (P2.toP dly).live l = true → 29 ≤ (P2.toP dly).dly l := fun l hl' => by
    have := hd l hl'
    show 29 ≤ dly l
    omega
  -- up to n, the hold run is that v1 run
  have hC : ∀ m, m ≤ n → (runH P2 fw hl sched m y0).x.e =
      run (P2.toP dly) (win1H (P2.toP dly) P2 fw hl sched y0) m y0.x.e := fun m hm =>
    runH_coinc P2 dly fw hl sched y0 hx0 hf hsw hss m (fun k hk => hI k (by omega))
  -- where the running hold came from
  obtain ⟨t0, ht0, hdrv, hcur, hval⟩ := hcnt_origin P2 fw hl sched y0 l (hh0 l) n hz
  have hvn := hval n ht0 (Nat.le_refl n)
  have hdv : (run (P2.toP dly) (win1H (P2.toP dly) P2 fw hl sched y0) t0 y0.x.e).st
      = .drive := by
    rw [← hC t0 (by omega)]
    exact hdrv
  have hcv : (run (P2.toP dly) (win1H (P2.toP dly) P2 fw hl sched y0) t0 y0.x.e).cur = l := by
    rw [← hC t0 (by omega)]
    exact hcur
  -- its writeback at t0 + 1
  have hst1 : (run (P2.toP dly) (win1H (P2.toP dly) P2 fw hl sched y0) (t0 + 1) y0.x.e).st
        = .wb ∧
      (run (P2.toP dly) (win1H (P2.toP dly) P2 fw hl sched y0) (t0 + 1) y0.x.e).cur = l := by
    rw [run_succ']
    obtain ⟨h1, h2⟩ := step_drive (P2.toP dly) (win1H (P2.toP dly) P2 fw hl sched y0) _ hdv
    exact ⟨h1, h2.trans hcv⟩
  have hwb : IsWB l
      (run (P2.toP dly) (win1H (P2.toP dly) P2 fw hl sched y0) (t0 + 1) y0.x.e) :=
    And.intro hst1.1 hst1.2
  -- n is idle, so it is past that writeback
  have hn2 : t0 + 2 ≤ n := by
    rcases Nat.lt_or_ge (t0 + 1) n with h | h
    · omega
    · exfalso
      have heq : n = t0 + 1 := by omega
      have hw1 := hst1.1
      rw [← hC (t0 + 1) (by omega), ← heq, hidle] at hw1
      cases hw1
  -- no further writeback of l before n: it cannot be picked while its gate is closed
  have hnowb : ∀ s, t0 + 2 ≤ s → s < t0 + 2 + (n - (t0 + 2)) →
      ¬IsWB l (run (P2.toP dly) (win1H (P2.toP dly) P2 fw hl sched y0) s y0.x.e) := by
    intro s hs1 hs2 hs
    obtain ⟨u, hu, hdec⟩ :=
      wb_back (P2.toP dly) (win1H (P2.toP dly) P2 fw hl sched y0) y0.x.e h0 s l hs
    obtain ⟨hui, huw, _⟩ := hdec
    by_cases hut : u = t0
    · rw [hut, hdv] at hui
      cases hui
    · have hu1 : t0 < u := by omega
      have hu2 : u < n := by omega
      have hcu := hC u (by omega)
      rw [← hcu, win1H_on (P2.toP dly) P2 fw hl sched y0 hsw hss u (hI u hu2)] at huw
      have hz' := (hsw _ l huw).2.2
      have := hval u hu1 (by omega)
      omega
  -- the timestamp at n
  have hlive : (P2.toP dly).live l = true := hrdy.1
  have hdl : 39 ≤ (P2.toP dly).dly l := hd l hlive
  have hb := wb_bound (P2.toP dly) (win1H (P2.toP dly) P2 fw hl sched y0) y0.x.e (t0 + 2)
    h0 h0ts hwin hws hd29 (fun t _ => hNS t) (t0 + 1) (by omega) l hlive hwb
  have hts2 :
      (run (P2.toP dly) (win1H (P2.toP dly) P2 fw hl sched y0) (t0 + 2) y0.x.e).ts l =
      (run (P2.toP dly) (win1H (P2.toP dly) P2 fw hl sched y0) (t0 + 1) y0.x.e).ts l
        + (P2.toP dly).dly l
        + (P2.toP dly).ext
            (run (P2.toP dly) (win1H (P2.toP dly) P2 fw hl sched y0) (t0 + 1) y0.x.e).now l :=
    ts_after_wb (P2.toP dly) (win1H (P2.toP dly) P2 fw hl sched y0) l y0.x.e (t0 + 1) hwb
  have hflat := ts_flat_run (P2.toP dly) (win1H (P2.toP dly) P2 fw hl sched y0) l y0.x.e
    (t0 + 2) (n - (t0 + 2)) hnowb
  have hk : t0 + 2 + (n - (t0 + 2)) = n := by omega
  rw [hk] at hflat
  have hrn := hrdy.2
  rw [hC n (Nat.le_refl n)] at hrn
  have hn1 := now_run (P2.toP dly) (win1H (P2.toP dly) P2 fw hl sched y0) (t0 + 1) y0.x.e
  have hnn := now_run (P2.toP dly) (win1H (P2.toP dly) P2 fw hl sched y0) n y0.x.e
  omega

/-- The gate is open at every decision, at every cycle. -/
theorem gate_open_all (P2 : Program2) (dly : Lane → Nat) (fw : Engine2 → Word)
    (hl : EngineH → Bool) (sched : EngineH → Option Lane) (y0 : EngineH)
    (hx0 : Plain dly y0.x) (hf : ∀ y, PlainW dly y.e.pl (fw y))
    (hW : Wf y0.x.e) (hfull : ∀ l s, P2.live l = true → y0.x.e.actv l s = true)
    (h0 : y0.x.e.st = .idle) (h0ts : ∀ l, y0.x.e.now ≤ y0.x.e.ts l)
    (hh0 : ∀ l, y0.hcnt l = 0)
    (hsw : ∀ y w, sched y = some w →
      (P2.toP dly).live w = true ∧ y.x.e.ts w ≤ y.x.e.now ∧ y.hcnt w = 0)
    (hss : ∀ y l, y.x.e.st = .idle →
      (P2.toP dly).live l = true ∧ y.x.e.ts l ≤ y.x.e.now ∧ y.hcnt l = 0 → sched y ≠ none)
    (hd : ∀ l, P2.live l = true → 39 ≤ dly l) :
    ∀ n m, m < n → GateOpen (P2.toP dly) (runH P2 fw hl sched m y0)
  | 0, m, hm => absurd hm (Nat.not_lt_zero m)
  | n + 1, m, hm => by
    have hI := gate_open_all P2 dly fw hl sched y0 hx0 hf hW hfull h0 h0ts hh0 hsw hss hd n
    by_cases hmn : m < n
    · exact hI m hmn
    · have hm' : m = n := by omega
      rw [hm']
      exact gate_open_at P2 dly fw hl sched y0 hx0 hf hW hfull h0 h0ts hh0 hsw hss hd n hI

/-- **D\* with SDA holds, d ≥ 39, no external hypotheses.** For every plain program stream,
every hold pattern, and every scheduler that picks only released, gate-open lanes and does
not idle while one exists: no dispatch decision ever stalls, and branch 1 never issues. -/
theorem dstar39_hold (P2 : Program2) (dly : Lane → Nat) (fw : Engine2 → Word)
    (hl : EngineH → Bool) (sched : EngineH → Option Lane) (y0 : EngineH)
    (hx0 : Plain dly y0.x) (hf : ∀ y, PlainW dly y.e.pl (fw y))
    (hW : Wf y0.x.e) (hfull : ∀ l s, P2.live l = true → y0.x.e.actv l s = true)
    (h0 : y0.x.e.st = .idle) (h0ts : ∀ l, y0.x.e.now ≤ y0.x.e.ts l)
    (hh0 : ∀ l, y0.hcnt l = 0)
    (hsw : ∀ y w, sched y = some w →
      (P2.toP dly).live w = true ∧ y.x.e.ts w ≤ y.x.e.now ∧ y.hcnt w = 0)
    (hss : ∀ y l, y.x.e.st = .idle →
      (P2.toP dly).live l = true ∧ y.x.e.ts l ≤ y.x.e.now ∧ y.hcnt l = 0 → sched y ≠ none)
    (hd : ∀ l, P2.live l = true → 39 ≤ dly l) :
    ∀ T, ((runH P2 fw hl sched T y0).x.e.st = .idle →
            ∀ w, sched (runH P2 fw hl sched T y0) = some w →
              (runH P2 fw hl sched T y0).x.e.headValid w = true) ∧
         NoBr1 (P2.toP dly) (runH P2 fw hl sched T y0).x.e := by
  intro T
  have hG := gate_open_all P2 dly fw hl sched y0 hx0 hf hW hfull h0 h0ts hh0 hsw hss hd (T + 1)
  have hC := runH_coinc P2 dly fw hl sched y0 hx0 hf hsw hss T (fun m hm => hG m (by omega))
  have key := dstar39 (P2.toP dly) (win1H (P2.toP dly) P2 fw hl sched y0) y0.x.e hW hfull h0
    h0ts (win1H_ready _ P2 fw hl sched y0) (win1H_wc _ P2 fw hl sched y0) hd T
  rw [← hC] at key
  refine ⟨fun hi w hw => key.1 hi w ?_, key.2⟩
  rw [win1H_on (P2.toP dly) P2 fw hl sched y0 hsw hss T (hG T (by omega))]
  exact hw

#print axioms dstar39_hold

end JLane
