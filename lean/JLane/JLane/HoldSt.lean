import JLane.HoldGate
import JLane.SelfTimed
/-!
# Brick V3b-ST — the SDA hold with self-timed words (lock item, Wilson 11-08)

The master list's lock item: "Lean `hold` lacks the self-timed case (`.st n` op)".
`HoldGate.dstar39_hold` covers plain programs only (`PlainW`: ordinary, looping re-arm). Here
the same theorem for the self-timed fragment (`StFragW`: ordinary, looping re-arm, self-timed,
each delay at least the lane's minimum), so an image with SDA holds **and** self-timed bytes
(the USB receive and transmit) is covered:

* `stH` — the V4b program of a hold run, time-indexed along it (as `SelfTimed.stP` is for
  `run2`): retire = the v2 retire, extra = the head word's delay above the minimum;
* `runH_coinc_st` — while the gate is open at decisions, the hold run is a V4b run of `stH`;
* `gate_open_at_st` / `gate_open_all_st` — the gate is always open (`d ≥ 39`);
* `dstar39_hold_st` — no stall, no branch 1, with SDA holds and self-timed words.
-/
namespace JLane

theorem frag_runH (P : Program2) (dly : Lane → Nat) (fw : Engine2 → Word)
    (hl : EngineH → Bool) (sched : EngineH → Option Lane)
    (hf : ∀ y, StFragW dly y.e.pl (fw y)) :
    ∀ (n : Nat) (y : EngineH), StFrag dly y.x → StFrag dly (runH P fw hl sched n y).x
  | 0, _, h => h
  | n + 1, y, h => frag_runH P dly fw hl sched hf n _ (frag_step P dly fw _ y.x h hf)

/-- The V4b program of a hold run from `y0`, time-indexed along it. -/
def stH (P2 : Program2) (dly : Lane → Nat) (fw : Engine2 → Word) (hl : EngineH → Bool)
    (sched : EngineH → Option Lane) (y0 : EngineH) : Program :=
  { live := P2.live
    dly := dly
    ext := fun t l =>
      ((runH P2 fw hl sched (t - y0.x.e.now) y0).x.head
        (runH P2 fw hl sched (t - y0.x.e.now) y0).x.e.cur).dly - dly l
    ret := fun t _ => (runH P2 fw hl sched (t - y0.x.e.now) y0).x.retire P2 }

/-- **Coincidence, self-timed.** While the gate has been open at every decision so far, the hold
run's engine is the V4b run of `stH` under `win1H`. -/
theorem runH_coinc_st (P2 : Program2) (dly : Lane → Nat) (fw : Engine2 → Word)
    (hl : EngineH → Bool) (sched : EngineH → Option Lane) (y0 : EngineH)
    (hx0 : StFrag dly y0.x) (hf : ∀ y, StFragW dly y.e.pl (fw y))
    (hsw : ∀ y w, sched y = some w →
      (stH P2 dly fw hl sched y0).live w = true ∧ y.x.e.ts w ≤ y.x.e.now ∧ y.hcnt w = 0)
    (hss : ∀ y l, y.x.e.st = .idle →
      (stH P2 dly fw hl sched y0).live l = true ∧ y.x.e.ts l ≤ y.x.e.now ∧ y.hcnt l = 0 →
        sched y ≠ none) :
    ∀ n, (∀ m, m < n → GateOpen (stH P2 dly fw hl sched y0) (runH P2 fw hl sched m y0)) →
      (runH P2 fw hl sched n y0).x.e =
        run (stH P2 dly fw hl sched y0)
          (win1H (stH P2 dly fw hl sched y0) P2 fw hl sched y0) n y0.x.e
  | 0, _ => rfl
  | n + 1, hI => by
    have hk : (runH P2 fw hl sched n y0).x.e.now - y0.x.e.now = n := by
      rw [now_runH]
      omega
    rw [runH_succ', run_succ',
      ← runH_coinc_st P2 dly fw hl sched y0 hx0 hf hsw hss n (fun m hm => hI m (by omega))]
    rw [step_win_congr (stH P2 dly fw hl sched y0)
        (win1H (stH P2 dly fw hl sched y0) P2 fw hl sched y0),
      win1H_on (stH P2 dly fw hl sched y0) P2 fw hl sched y0 hsw hss n (hI n (by omega))]
    show (step2 P2 fw (sched (runH P2 fw hl sched n y0)) (runH P2 fw hl sched n y0).x).e = _
    refine step2_proj_st P2 (stH P2 dly fw hl sched y0) dly fw _ _
      (frag_runH P2 dly fw hl sched hf n y0 hx0) rfl rfl ?_ ?_
      (by simp [stH, Engine2.op_not_br_st (hf (runH P2 fw hl sched n y0).x)])
    · show (runH P2 fw hl sched ((runH P2 fw hl sched n y0).x.e.now - y0.x.e.now) y0).x.retire
        P2 = _
      rw [hk]
    · show ((runH P2 fw hl sched ((runH P2 fw hl sched n y0).x.e.now - y0.x.e.now) y0).x.head
          (runH P2 fw hl sched ((runH P2 fw hl sched n y0).x.e.now - y0.x.e.now) y0).x.e.cur).dly
          - dly (runH P2 fw hl sched n y0).x.e.cur = _
      rw [hk]

section
variable (P2 : Program2) (dly : Lane → Nat) (fw : Engine2 → Word)
  (hl : EngineH → Bool) (sched : EngineH → Option Lane) (y0 : EngineH)
  (hx0 : StFrag dly y0.x) (hf : ∀ y, StFragW dly y.e.pl (fw y))
  (hW : Wf y0.x.e) (hfull : ∀ l s, P2.live l = true → y0.x.e.actv l s = true)
  (h0 : y0.x.e.st = .idle) (h0ts : ∀ l, y0.x.e.now ≤ y0.x.e.ts l)
  (hh0 : ∀ l, y0.hcnt l = 0)
  (hsw : ∀ y w, sched y = some w →
    (stH P2 dly fw hl sched y0).live w = true ∧ y.x.e.ts w ≤ y.x.e.now ∧ y.hcnt w = 0)
  (hss : ∀ y l, y.x.e.st = .idle →
    (stH P2 dly fw hl sched y0).live l = true ∧ y.x.e.ts l ≤ y.x.e.now ∧ y.hcnt l = 0 →
      sched y ≠ none)
  (hd : ∀ l, P2.live l = true → 39 ≤ dly l)

include hx0 hf hW hfull h0 h0ts hh0 hsw hss hd in
/-- **The gate step, self-timed.** -/
theorem gate_open_at_st (n : Nat)
    (hI : ∀ m, m < n → GateOpen (stH P2 dly fw hl sched y0) (runH P2 fw hl sched m y0)) :
    GateOpen (stH P2 dly fw hl sched y0) (runH P2 fw hl sched n y0) := by
  intro hidle l hrdy
  by_cases hz : (runH P2 fw hl sched n y0).hcnt l = 0
  · exact hz
  exfalso
  have hS : SDA_HS = 23 := by decide
  have hwin := win1H_ready (stH P2 dly fw hl sched y0) P2 fw hl sched y0
  have hws := win1H_wc (stH P2 dly fw hl sched y0) P2 fw hl sched y0
  have hNS : ∀ t, NoStall (win1H (stH P2 dly fw hl sched y0) P2 fw hl sched y0)
      (run (stH P2 dly fw hl sched y0) (win1H (stH P2 dly fw hl sched y0) P2 fw hl sched y0) t
        y0.x.e) := fun t =>
    (dstar39 (stH P2 dly fw hl sched y0) (win1H (stH P2 dly fw hl sched y0) P2 fw hl sched y0)
      y0.x.e hW hfull (fun _ => rfl) hx0.2 h0 h0ts hwin hws hd t).1
  have hd29 : ∀ l, (stH P2 dly fw hl sched y0).live l = true →
      29 ≤ (stH P2 dly fw hl sched y0).dly l := fun l hl' => by
    have := hd l hl'
    show 29 ≤ dly l
    omega
  have hC : ∀ m, m ≤ n → (runH P2 fw hl sched m y0).x.e =
      run (stH P2 dly fw hl sched y0) (win1H (stH P2 dly fw hl sched y0) P2 fw hl sched y0) m
        y0.x.e := fun m hm =>
    runH_coinc_st P2 dly fw hl sched y0 hx0 hf hsw hss m (fun k hk => hI k (by omega))
  obtain ⟨t0, ht0, hdrv, hcur, hval⟩ := hcnt_origin P2 fw hl sched y0 l (hh0 l) n hz
  have hvn := hval n ht0 (Nat.le_refl n)
  have hdv : (run (stH P2 dly fw hl sched y0)
      (win1H (stH P2 dly fw hl sched y0) P2 fw hl sched y0) t0 y0.x.e).st = .drive := by
    rw [← hC t0 (by omega)]
    exact hdrv
  have hcv : (run (stH P2 dly fw hl sched y0)
      (win1H (stH P2 dly fw hl sched y0) P2 fw hl sched y0) t0 y0.x.e).cur = l := by
    rw [← hC t0 (by omega)]
    exact hcur
  have hst1 : (run (stH P2 dly fw hl sched y0)
        (win1H (stH P2 dly fw hl sched y0) P2 fw hl sched y0) (t0 + 1) y0.x.e).st = .wb ∧
      (run (stH P2 dly fw hl sched y0)
        (win1H (stH P2 dly fw hl sched y0) P2 fw hl sched y0) (t0 + 1) y0.x.e).cur = l := by
    rw [run_succ']
    obtain ⟨h1, h2⟩ := step_drive (stH P2 dly fw hl sched y0)
      (win1H (stH P2 dly fw hl sched y0) P2 fw hl sched y0) _ hdv
    exact ⟨h1, h2.trans hcv⟩
  have hwb : IsWB l (run (stH P2 dly fw hl sched y0)
      (win1H (stH P2 dly fw hl sched y0) P2 fw hl sched y0) (t0 + 1) y0.x.e) :=
    And.intro hst1.1 hst1.2
  have hn2 : t0 + 2 ≤ n := by
    rcases Nat.lt_or_ge (t0 + 1) n with h | h
    · omega
    · exfalso
      have heq : n = t0 + 1 := by omega
      have hw1 := hst1.1
      rw [← hC (t0 + 1) (by omega), ← heq, hidle] at hw1
      cases hw1
  have hnowb : ∀ s, t0 + 2 ≤ s → s < t0 + 2 + (n - (t0 + 2)) →
      ¬IsWB l (run (stH P2 dly fw hl sched y0)
        (win1H (stH P2 dly fw hl sched y0) P2 fw hl sched y0) s y0.x.e) := by
    intro s hs1 hs2 hs
    obtain ⟨u, hu, hdec⟩ := wb_back (stH P2 dly fw hl sched y0)
      (win1H (stH P2 dly fw hl sched y0) P2 fw hl sched y0) y0.x.e h0 s l hs
    obtain ⟨hui, huw, _⟩ := hdec
    by_cases hut : u = t0
    · rw [hut, hdv] at hui
      cases hui
    · have hu1 : t0 < u := by omega
      have hu2 : u < n := by omega
      have hcu := hC u (by omega)
      rw [← hcu, win1H_on (stH P2 dly fw hl sched y0) P2 fw hl sched y0 hsw hss u
        (hI u hu2)] at huw
      have hz' := (hsw _ l huw).2.2
      have := hval u hu1 (by omega)
      omega
  have hlive : (stH P2 dly fw hl sched y0).live l = true := hrdy.1
  have hdl : 39 ≤ (stH P2 dly fw hl sched y0).dly l := hd l hlive
  have hb := wb_bound (stH P2 dly fw hl sched y0)
    (win1H (stH P2 dly fw hl sched y0) P2 fw hl sched y0) y0.x.e (t0 + 2)
    h0 h0ts hwin hws hd29 (fun t _ => hNS t) (t0 + 1) (by omega) l hlive hwb
  have hts2 : (run (stH P2 dly fw hl sched y0)
        (win1H (stH P2 dly fw hl sched y0) P2 fw hl sched y0) (t0 + 2) y0.x.e).ts l =
      (run (stH P2 dly fw hl sched y0)
        (win1H (stH P2 dly fw hl sched y0) P2 fw hl sched y0) (t0 + 1) y0.x.e).ts l
        + (stH P2 dly fw hl sched y0).dly l
        + (stH P2 dly fw hl sched y0).ext
            (run (stH P2 dly fw hl sched y0)
              (win1H (stH P2 dly fw hl sched y0) P2 fw hl sched y0) (t0 + 1) y0.x.e).now l :=
    ts_after_wb (stH P2 dly fw hl sched y0)
      (win1H (stH P2 dly fw hl sched y0) P2 fw hl sched y0) l y0.x.e (t0 + 1) hwb
  have hflat := ts_flat_run (stH P2 dly fw hl sched y0)
    (win1H (stH P2 dly fw hl sched y0) P2 fw hl sched y0) l y0.x.e
    (t0 + 2) (n - (t0 + 2)) hnowb
  have hk : t0 + 2 + (n - (t0 + 2)) = n := by omega
  rw [hk] at hflat
  have hrn := hrdy.2
  rw [hC n (Nat.le_refl n)] at hrn
  have hn1 := now_run (stH P2 dly fw hl sched y0)
    (win1H (stH P2 dly fw hl sched y0) P2 fw hl sched y0) (t0 + 1) y0.x.e
  have hnn := now_run (stH P2 dly fw hl sched y0)
    (win1H (stH P2 dly fw hl sched y0) P2 fw hl sched y0) n y0.x.e
  omega

include hx0 hf hW hfull h0 h0ts hh0 hsw hss hd in
theorem gate_open_all_st :
    ∀ n m, m < n → GateOpen (stH P2 dly fw hl sched y0) (runH P2 fw hl sched m y0)
  | 0, m, hm => absurd hm (Nat.not_lt_zero m)
  | n + 1, m, hm => by
    have hI := gate_open_all_st n
    by_cases hmn : m < n
    · exact hI m hmn
    · have hm' : m = n := by omega
      rw [hm']
      exact gate_open_at_st P2 dly fw hl sched y0 hx0 hf hW hfull h0 h0ts hh0 hsw hss hd n hI

include hx0 hf hW hfull h0 h0ts hh0 hsw hss hd in
/-- **D\* with SDA holds and self-timed words, d ≥ 39** (closes the 11-08 lock item). For every
fragment program stream (ordinary, looping re-arm and self-timed words, each delay at least the
lane's minimum), every last-bit and stuff-slot pattern, every hold pattern, and every scheduler
that picks only released, gate-open lanes and does not idle while one exists: no dispatch
decision ever stalls, and branch 1 never issues. -/
theorem dstar39_hold_st :
    ∀ T, ((runH P2 fw hl sched T y0).x.e.st = .idle →
            ∀ w, sched (runH P2 fw hl sched T y0) = some w →
              (runH P2 fw hl sched T y0).x.e.headValid w = true) ∧
         NoBr1 (stH P2 dly fw hl sched y0) (runH P2 fw hl sched T y0).x.e := by
  intro T
  have hG := gate_open_all_st P2 dly fw hl sched y0 hx0 hf hW hfull h0 h0ts hh0 hsw hss hd
    (T + 1)
  have hC := runH_coinc_st P2 dly fw hl sched y0 hx0 hf hsw hss T (fun m hm => hG m (by omega))
  have key := dstar39 (stH P2 dly fw hl sched y0)
    (win1H (stH P2 dly fw hl sched y0) P2 fw hl sched y0) y0.x.e hW hfull (fun _ => rfl) hx0.2
    h0 h0ts (win1H_ready _ P2 fw hl sched y0) (win1H_wc _ P2 fw hl sched y0) hd T
  rw [← hC] at key
  refine ⟨fun hi w hw => key.1 hi w ?_, key.2⟩
  rw [win1H_on (stH P2 dly fw hl sched y0) P2 fw hl sched y0 hsw hss T (hG T (by omega))]
  exact hw

end

#print axioms runH_coinc_st
#print axioms dstar39_hold_st

end JLane
