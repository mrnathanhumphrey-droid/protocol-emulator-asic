import JLane.Buf
import JLane.Run
/-!
# Brick C1 — the head-valid chain under the guaranteed slot (Wilson 11-16, carry-through)

`Run.head_valid_when_ready` carried onto the slot's run (`runS`): the same conclusion -- lane
`y`'s head is valid whenever `y` is ready -- with the branch-1 budget `hB` read on the slot's
per-victim charge `chargeSumS` (USB receive's branch 1, the slot's fetches for other lanes, the
other lanes' branch 1; nothing for `y`'s own slot fetch).

The slot changes only the port's registers (`stepS_*`), so every lane-side fact carries by
definition. New here:
* `spareFill_stepS` -- a slot issue fills the spare of a lane whose head is valid (`SReqOK`),
  so SpareFill holds; `wf_stepS`, `wf_runS` -- the well-formedness bundle on the slot run;
* `owed_runS` -- conservation (owed + hits = owed₀ + retirements) on the slot run;
* `head_valid_of_countsS`, `pending_boundS`, `head_valid_when_readyS`.

The buffer's third word (Buf.lean) is not in this engine: here every slot fetch fills the spare
(one word per issue). The buffer state and two fetches per ARM are brick C2.
-/
namespace JLane

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : Engine → Option Lane)

/-! ### Lane-side fields are the shipped step's -/

theorem stepS_ts (e : Engine) : (stepS P win usb sreq e).ts = (step P win e).ts := rfl
theorem stepS_now (e : Engine) : (stepS P win usb sreq e).now = (step P win e).now := rfl
theorem stepS_owed (e : Engine) (l : Lane) :
    (stepS P win usb sreq e).owed l = (step P win e).owed l := rfl

/-- After a capture the slot's port is scanning (a CAP never issues). -/
theorem hit_then_scanS (y : Lane) (e : Engine) (hh : Hit y e) :
    (stepS P win usb sreq e).pst = .scan := by
  obtain ⟨hc, _⟩ := hh
  change (portNextS P usb sreq e).pst = .scan
  rw [portNextS_of_ne P usb sreq e (by rw [hc]; decide)]
  simp [portNext_cap P e hc]

/-! ### Well-formedness on the slot run -/

theorem headFirst_stepS (e : Engine) (hH : HeadFirst e) (hF : SpareFill e) :
    HeadFirst (stepS P win usb sreq e) :=
  fun l hl => headFirst_step P win e hH hF l hl

/-- **SpareFill under the slot.** A slot issue latches the spare of a lane whose head is valid;
that head stays valid unless the lane retires this cycle, and then the latched slot is the new
head's partner -- the new head itself is the slot being filled, so the premise fails. -/
theorem spareFill_stepS (hok : SReqOK P sreq) (e : Engine) (hS : Struct e) (hF : SpareFill e) :
    SpareFill (stepS P win usb sreq e) := by
  have hbase := spareFill_step P win e hS hF
  unfold SpareFill at hbase
  change (portNext P e).pst ≠ .scan → (portNext P e).pslot ≠ selNext P e (portNext P e).pl →
      actvNext P e (portNext P e).pl (selNext P e (portNext P e).pl) = true at hbase
  have hfall : portNextS P usb sreq e = portNext P e → SpareFill (stepS P win usb sreq e) := by
    intro hq
    unfold SpareFill
    change (portNextS P usb sreq e).pst ≠ .scan →
        (portNextS P usb sreq e).pslot ≠ selNext P e (portNextS P usb sreq e).pl →
        actvNext P e (portNextS P usb sreq e).pl (selNext P e (portNextS P usb sreq e).pl) = true
    rw [hq]
    exact hbase
  cases hp : e.pst with
  | req => exact hfall (portNextS_of_ne P usb sreq e (by rw [hp]; decide))
  | wait => exact hfall (portNextS_of_ne P usb sreq e (by rw [hp]; decide))
  | cap => exact hfall (portNextS_of_ne P usb sreq e (by rw [hp]; decide))
  | scan =>
    cases hu : usbFirst P usb e with
    | true => exact hfall (portNextS_usb P usb sreq e hp hu)
    | false =>
      cases hs : sreq e with
      | none => exact hfall (portNextS_none P usb sreq e hp hu hs)
      | some w =>
        unfold SpareFill
        change (portNextS P usb sreq e).pst ≠ .scan →
            (portNextS P usb sreq e).pslot ≠ selNext P e (portNextS P usb sreq e).pl →
            actvNext P e (portNextS P usb sreq e).pl
              (selNext P e (portNextS P usb sreq e).pl) = true
        rw [portNextS_slot P usb sreq e hp hu hs]
        intro _ hsp
        have hv : e.headValid w = true := (hok e w hs).2.1
        have hv' : e.actv w (e.sel w) = true := hv
        show actvNext P e w (selNext P e w) = true
        by_cases hw : e.st = .wb ∧ w = e.cur ∧ P.ret e.now e.cur = true
        · exfalso
          apply hsp
          show e.fetchSlot w = selNext P e w
          have hsel : selNext P e w = !e.sel w := by
            unfold selNext
            rw [if_pos hw]
          rw [hsel]
          simp [Engine.fetchSlot, hv]
        · have hsel : selNext P e w = e.sel w := by
            unfold selNext
            rw [if_neg hw]
          rw [hsel]
          exact actvNext_keep_true P e w _ hw hv'

theorem wf_stepS (hok : SReqOK P sreq) (e : Engine) (h : Wf e) : Wf (stepS P win usb sreq e) := by
  unfold Wf at h ⊢
  obtain ⟨hS, hH, hF⟩ := h
  exact ⟨struct_stepS P win usb sreq hok e hS, headFirst_stepS P win usb sreq e hH hF,
    spareFill_stepS P win usb sreq hok e hS hF⟩

theorem wf_runS (hok : SReqOK P sreq) :
    ∀ (n : Nat) (e : Engine), Wf e → Wf (runS P win usb sreq n e)
  | 0, _, h => h
  | n + 1, e, h => wf_runS hok n (stepS P win usb sreq e) (wf_stepS P win usb sreq hok e h)

theorem struct_runS (hok : SReqOK P sreq) :
    ∀ (n : Nat) (e : Engine), Struct e → Struct (runS P win usb sreq n e)
  | 0, _, h => h
  | n + 1, e, h => struct_runS hok n (stepS P win usb sreq e) (struct_stepS P win usb sreq hok e h)

/-! ### Counters on the slot run -/

theorem cntS_succ_back (Q : Engine → Prop) [DecidablePred Q] (n : Nat) (e : Engine) :
    cntS P win usb sreq Q (n + 1) e
      = cntS P win usb sreq Q n e + (if Q (runS P win usb sreq n e) then 1 else 0) := by
  have h1 : cntS P win usb sreq Q 1 (runS P win usb sreq n e)
      = (if Q (runS P win usb sreq n e) then 1 else 0) + 0 := rfl
  rw [cntS_add P win usb sreq Q n 1 e, h1, Nat.add_zero]

theorem cntS_mono (Q : Engine → Prop) [DecidablePred Q] (e : Engine) (a : Nat) :
    ∀ (b : Nat), a ≤ b → cntS P win usb sreq Q a e ≤ cntS P win usb sreq Q b e
  | 0, h => by
    have : a = 0 := by omega
    subst this
    exact Nat.le_refl _
  | b + 1, h => by
    by_cases hab : a = b + 1
    · subst hab
      exact Nat.le_refl _
    · have ih := cntS_mono Q e a b (by omega)
      have := cntS_succ_back P win usb sreq Q b e
      omega

theorem no_event_betweenS (Q : Engine → Prop) [DecidablePred Q] (e : Engine) (a b i : Nat)
    (hai : a ≤ i) (hib : i < b)
    (heq : cntS P win usb sreq Q a e = cntS P win usb sreq Q b e) :
    ¬Q (runS P win usb sreq i e) := by
  intro hq
  have h1 := cntS_mono P win usb sreq Q e a i hai
  have h2 := cntS_mono P win usb sreq Q e (i + 1) b hib
  have h3 := cntS_succ_back P win usb sreq Q i e
  rw [if_pos hq] at h3
  omega

/-- **Conservation on the slot run.** -/
theorem owed_runS (hok : SReqOK P sreq) (y : Lane) :
    ∀ (n : Nat) (e : Engine), Struct e →
      (runS P win usb sreq n e).owed y + cntS P win usb sreq (Hit y) n e
        = e.owed y + cntS P win usb sreq (IsRet P y) n e
  | 0, e, _ => by simp [runS, cntS]
  | n + 1, e, hS => by
    have h1 := owed_step P win y e hS
    rw [← stepS_owed P win usb sreq e y] at h1
    have ih := owed_runS hok y n (stepS P win usb sreq e) (struct_stepS P win usb sreq hok e hS)
    have e1 : cntS P win usb sreq (Hit y) (n + 1) e
        = (if Hit y e then 1 else 0) + cntS P win usb sreq (Hit y) n (stepS P win usb sreq e) :=
      rfl
    have e2 : cntS P win usb sreq (IsRet P y) (n + 1) e
        = (if IsRet P y e then 1 else 0)
          + cntS P win usb sreq (IsRet P y) n (stepS P win usb sreq e) := rfl
    have e3 : runS P win usb sreq (n + 1) e = runS P win usb sreq n (stepS P win usb sreq e) := rfl
    rw [e3]
    omega

/-- **The bridge on the slot run.** -/
theorem head_valid_of_countsS (hok : SReqOK P sreq) (y : Lane) (n : Nat) (e0 : Engine)
    (hW : Wf e0) (hfull : ∀ s, e0.actv y s = true)
    (h : cntS P win usb sreq (IsRet P y) n e0 ≤ cntS P win usb sreq (Hit y) n e0 + 1) :
    (runS P win usb sreq n e0).headValid y = true := by
  have hS : Struct e0 := hW.1
  have hH : HeadFirst (runS P win usb sreq n e0) := (wf_runS P win usb sreq hok n e0 hW).2.1
  have hrun := owed_runS P win usb sreq hok y n e0 hS
  have h0 := owed_full e0 y hfull
  exact head_of_owed_le_one _ y hH (by omega)

/-! ### Clock and timestamps on the slot run -/

theorem now_runS : ∀ (n : Nat) (e : Engine), (runS P win usb sreq n e).now = e.now + n
  | 0, _ => rfl
  | n + 1, e => by
    have := now_runS n (stepS P win usb sreq e)
    show (runS P win usb sreq n (stepS P win usb sreq e)).now = e.now + (n + 1)
    rw [this]
    show e.now + 1 + n = e.now + (n + 1)
    omega

theorem ts_run_geS (y : Lane) :
    ∀ (n : Nat) (e : Engine),
      e.ts y + P.dly y * cntS P win usb sreq (IsWB y) n e ≤ (runS P win usb sreq n e).ts y
  | 0, e => by simp [runS, cntS]
  | n + 1, e => by
    have ih := ts_run_geS y n (stepS P win usb sreq e)
    have h1 : (stepS P win usb sreq e).ts y
        = e.ts y + (if IsWB y e then P.dly y + P.ext e.now y else 0) := ts_step P win e y
    have e1 : cntS P win usb sreq (IsWB y) (n + 1) e
        = (if IsWB y e then 1 else 0) + cntS P win usb sreq (IsWB y) n (stepS P win usb sreq e) :=
      rfl
    have e3 : runS P win usb sreq (n + 1) e = runS P win usb sreq n (stepS P win usb sreq e) := rfl
    rw [e3, e1, Nat.mul_add]
    by_cases h : IsWB y e
    · rw [if_pos h] at h1 ⊢
      rw [Nat.mul_one]
      omega
    · rw [if_neg h] at h1 ⊢
      rw [Nat.mul_zero]
      omega

theorem ts_spacingS (y : Lane) (e : Engine) (a k : Nat) :
    (runS P win usb sreq a e).ts y
        + P.dly y * (cntS P win usb sreq (IsWB y) (a + k) e - cntS P win usb sreq (IsWB y) a e)
      ≤ (runS P win usb sreq (a + k) e).ts y := by
  have h1 := ts_run_geS P win usb sreq y k (runS P win usb sreq a e)
  have h2 := cntS_add P win usb sreq (IsWB y) a k e
  rw [← runS_add] at h1
  rw [h2, Nat.add_sub_cancel_left]
  exact h1

theorem ts_ge_after_wbS (y : Lane) (e : Engine) (a b : Nat) (hab : a < b)
    (hw : IsWB y (runS P win usb sreq a e)) :
    (runS P win usb sreq a e).ts y + P.dly y ≤ (runS P win usb sreq b e).ts y := by
  have hsp := ts_spacingS P win usb sreq y e a (b - a)
  have hba : a + (b - a) = b := by omega
  rw [hba] at hsp
  have h1 := cntS_succ_back P win usb sreq (IsWB y) a e
  rw [if_pos hw] at h1
  have h2 := cntS_mono P win usb sreq (IsWB y) e (a + 1) b (by omega)
  have hm := dly_le_mul (P.dly y)
    (cntS P win usb sreq (IsWB y) b e - cntS P win usb sreq (IsWB y) a e) (by omega)
  omega

/-! ### Waits under the slot's charge -/

theorem port_wait_bound_19S (hok : SReqOK P sreq) (y : Lane) (hy : P.live y = true) (n : Nat)
    (e : Engine) (hS : Struct e) (hw : e.wantFetch y = true)
    (hq : e.pst = .scan ∨ e.pbr1 = false)
    (hnh : ∀ i, i < n → ¬Hit y (runS P win usb sreq i e)) :
    n ≤ 19 + chargeSumS P win usb sreq y n e := by
  have h := port_waitS P win usb sreq hok y hy n e hS hw hnh
  have h2 := phi_le_19 y (portOf e) hq
  omega

theorem window_leS (hok : SReqOK P sreq) (y : Lane) (hy : P.live y = true) (e : Engine)
    (B n : Nat) (hS : Struct e) (hw : e.wantFetch y = true)
    (hB : ∀ m, m ≤ n → m ≤ 23 + B → chargeSumS P win usb sreq y m e ≤ B)
    (hnh : ∀ i, i < n → ¬Hit y (runS P win usb sreq i e)) : n ≤ 22 + B := by
  by_cases hn : n ≤ 23 + B
  · have h := port_wait_boundS P win usb sreq hok y hy n e hS hw hnh
    have := hB n (Nat.le_refl n) hn
    omega
  · have h := port_wait_boundS P win usb sreq hok y hy (23 + B) e hS hw
      (fun i hi => hnh i (by omega))
    have := hB (23 + B) (by omega) (Nat.le_refl _)
    omega

theorem window_le_19S (hok : SReqOK P sreq) (y : Lane) (hy : P.live y = true) (e : Engine)
    (B n : Nat) (hS : Struct e) (hw : e.wantFetch y = true)
    (hq : e.pst = .scan ∨ e.pbr1 = false)
    (hB : ∀ m, m ≤ n → m ≤ 23 + B → chargeSumS P win usb sreq y m e ≤ B)
    (hnh : ∀ i, i < n → ¬Hit y (runS P win usb sreq i e)) : n ≤ 19 + B := by
  by_cases hn : n ≤ 23 + B
  · have h := port_wait_bound_19S P win usb sreq hok y hy n e hS hw hq hnh
    have := hB n (Nat.le_refl n) hn
    omega
  · have h := port_wait_bound_19S P win usb sreq hok y hy (23 + B) e hS hw hq
      (fun i hi => hnh i (by omega))
    have := hB (23 + B) (by omega) (Nat.le_refl _)
    omega

/-! ### The pending bound and the head on the slot run -/

theorem pb_freshS (hok : SReqOK P sreq) (y : Lane) (e0 : Engine)
    (R B T w t : Nat) (hy : P.live y = true) (hS0 : Struct e0)
    (hnp : ∀ t, (runS P win usb sreq t e0).NoNpf)
    (hR : ∀ t, t < T → IsWB y (runS P win usb sreq t e0) →
      (runS P win usb sreq t e0).now ≤ (runS P win usb sreq t e0).ts y + R + 2)
    (hB : ∀ a m, a + m ≤ T → m ≤ 23 + B →
      chargeSumS P win usb sreq y m (runS P win usb sreq a e0) ≤ B)
    (hwt : w < t) (htT : t ≤ T)
    (hwb : IsRet P y (runS P win usb sreq w e0))
    (heq : cntS P win usb sreq (Hit y) (w + 1) e0 = cntS P win usb sreq (Hit y) t e0) :
    e0.now + t ≤ (runS P win usb sreq w e0).ts y + R + PENDING_SLACK + B := by
  have hPS : PENDING_SLACK = 25 := pending_slack_val
  have hRw := hR w (by omega) (isWB_of_ret P y _ hwb)
  have hnow := now_runS P win usb sreq w e0
  obtain ⟨hst, hcur, hret⟩ := hwb
  have hwant : (runS P win usb sreq (w + 1) e0).wantFetch y = true := by
    have hn1 := hnp (w + 1)
    rw [runS_succ'] at hn1
    rw [runS_succ', ← hcur]
    exact wb_owes P win (runS P win usb sreq w e0) hst (by rw [hcur]; exact hret) (hn1 _ _)
  have hn := window_leS P win usb sreq hok y hy (runS P win usb sreq (w + 1) e0) B (t - (w + 1))
    (struct_runS P win usb sreq hok (w + 1) e0 hS0) hwant
    (fun m hm hm' => by
      have := hB (w + 1) m (by omega) hm'
      exact this)
    (fun i hi => by
      rw [← runS_add]
      exact no_event_betweenS P win usb sreq (Hit y) e0 (w + 1) t (w + 1 + i)
        (by omega) (by omega) heq)
  omega

/-- **The pending bound on the slot run.** `Run.pending_bound` with `hB` on `chargeSumS`. -/
theorem pending_boundS (hok : SReqOK P sreq) (y : Lane) (e0 : Engine)
    (d R B T : Nat) (hW : Wf e0) (hfull : ∀ l s, P.live l = true → e0.actv l s = true)
    (hy : P.live y = true) (hdly : P.dly y = d) (hd : DSTAR + B ≤ d)
    (hnp : ∀ t, (runS P win usb sreq t e0).NoNpf)
    (hR : ∀ t, t < T → IsWB y (runS P win usb sreq t e0) →
      (runS P win usb sreq t e0).now ≤ (runS P win usb sreq t e0).ts y + R + 2)
    (hB : ∀ a m, a + m ≤ T → m ≤ 23 + B →
      chargeSumS P win usb sreq y m (runS P win usb sreq a e0) ≤ B) :
    ∀ (k t w : Nat), t ≤ T → w < t → cntS P win usb sreq (IsRet P y) w e0 = k →
      IsRet P y (runS P win usb sreq w e0) → cntS P win usb sreq (Hit y) t e0 ≤ k →
      e0.now + t ≤ (runS P win usb sreq w e0).ts y + R + PENDING_SLACK + B := by
  have hS : Struct e0 := hW.1
  have h0 := owed_full e0 y (fun s => hfull y s hy)
  intro k
  induction k with
  | zero =>
    intro t w htT hwt hwk hwb hh
    have hm := cntS_mono P win usb sreq (Hit y) e0 (w + 1) t (by omega)
    exact pb_freshS P win usb sreq hok y e0 R B T w t hy hS hnp hR hB hwt htT hwb (by omega)
  | succ k ih =>
    intro t w htT hwt hwk hwb hh
    have hm := cntS_mono P win usb sreq (Hit y) e0 (w + 1) t (by omega)
    by_cases hfresh : k + 1 ≤ cntS P win usb sreq (Hit y) (w + 1) e0
    · exact pb_freshS P win usb sreq hok y e0 R B T w t hy hS hnp hR hB hwt htT hwb (by omega)
    · obtain ⟨w', hw'w, hw'k, hw'b⟩ := cntS_reach P win usb sreq (IsRet P y) w e0 k (by omega)
      have hsp := ts_ge_after_wbS P win usb sreq y e0 w' w hw'w (isWB_of_ret P y _ hw'b)
      by_cases hlate : cntS P win usb sreq (Hit y) t e0 ≤ k
      · have := ih t w' htT (by omega) hw'k hw'b hlate
        omega
      · obtain ⟨c, hct, hck, hhit⟩ := cntS_reach P win usb sreq (Hit y) t e0 k (by omega)
        have hc1 : cntS P win usb sreq (Hit y) (c + 1) e0 = k + 1 := by
          have := cntS_succ_back P win usb sreq (Hit y) c e0
          rw [if_pos hhit] at this
          omega
        have hwc : w + 1 ≤ c := by
          rcases Nat.lt_or_ge c (w + 1) with hlt | hge
          · have := cntS_mono P win usb sreq (Hit y) e0 (c + 1) (w + 1) hlt
            omega
          · exact hge
        have hwb1 : cntS P win usb sreq (IsRet P y) (w + 1) e0 = k + 2 := by
          have := cntS_succ_back P win usb sreq (IsRet P y) w e0
          rw [if_pos hwb] at this
          omega
        have hwbc1 := cntS_mono P win usb sreq (IsRet P y) e0 (w + 1) (c + 1) (by omega)
        have hic := ih c w' (by omega) (by omega) hw'k hw'b (by omega)
        have hwant : (runS P win usb sreq (c + 1) e0).wantFetch y = true := by
          rw [Engine.wantFetch_iff _ _ (hnp (c + 1) _ _)]
          have := owed_runS P win usb sreq hok y (c + 1) e0 hS
          omega
        have hscan : (runS P win usb sreq (c + 1) e0).pst = .scan := by
          rw [runS_succ']
          exact hit_then_scanS P win usb sreq y (runS P win usb sreq c e0) hhit
        have heq : cntS P win usb sreq (Hit y) (c + 1) e0 = cntS P win usb sreq (Hit y) t e0 := by
          omega
        have hn := window_le_19S P win usb sreq hok y hy (runS P win usb sreq (c + 1) e0) B
          (t - (c + 1)) (struct_runS P win usb sreq hok (c + 1) e0 hS) hwant (Or.inl hscan)
          (fun m hm hm' => hB (c + 1) m (by omega) hm')
          (fun i hi => by
            rw [← runS_add]
            exact no_event_betweenS P win usb sreq (Hit y) e0 (c + 1) t (c + 1 + i)
              (by omega) (by omega) heq)
        have hD : DSTAR = 20 := dstar_val
        omega

/-- **The head under the slot.** `Run.head_valid_when_ready` on the slot run: with the
budget `hB` on the slot's per-victim charge, lane `y`'s head is valid at every cycle `t ≤ T`
where `y` is ready. -/
theorem head_valid_when_readyS (hok : SReqOK P sreq) (y : Lane)
    (e0 : Engine) (d R B T : Nat) (hW : Wf e0) (hfull : ∀ l s, P.live l = true → e0.actv l s = true)
    (hy : P.live y = true) (hdly : P.dly y = d) (hd : DSTAR + B ≤ d)
    (hnp : ∀ t, (runS P win usb sreq t e0).NoNpf)
    (hlat : R + HEAD_SLACK + B ≤ 2 * d)
    (hR : ∀ t, t < T → IsWB y (runS P win usb sreq t e0) →
      (runS P win usb sreq t e0).now ≤ (runS P win usb sreq t e0).ts y + R + 2)
    (hB : ∀ a m, a + m ≤ T → m ≤ 23 + B →
      chargeSumS P win usb sreq y m (runS P win usb sreq a e0) ≤ B)
    (t : Nat) (htT : t ≤ T)
    (hrdy : (runS P win usb sreq t e0).ts y ≤ (runS P win usb sreq t e0).now) :
    (runS P win usb sreq t e0).headValid y = true := by
  apply head_valid_of_countsS P win usb sreq hok y t e0 hW (fun s => hfull y s hy)
  by_cases hc : cntS P win usb sreq (IsRet P y) t e0 ≤ cntS P win usb sreq (Hit y) t e0 + 1
  · exact hc
  · exfalso
    have hHS : HEAD_SLACK = PENDING_SLACK + 1 := rfl
    have hnow := now_runS P win usb sreq t e0
    obtain ⟨w, hwt, hwk, hwb⟩ := cntS_reach P win usb sreq (IsRet P y) t e0
      (cntS P win usb sreq (IsRet P y) t e0 - 2) (by omega)
    have hpb := pending_boundS P win usb sreq hok y e0 d R B T hW hfull hy hdly hd hnp hR hB
      (cntS P win usb sreq (IsRet P y) t e0 - 2) t w htT hwt hwk hwb (by omega)
    obtain ⟨w2, hw2t, hw2k, hw2b⟩ := cntS_reach P win usb sreq (IsRet P y) t e0
      (cntS P win usb sreq (IsRet P y) t e0 - 1) (by omega)
    have hww2 : w < w2 := by
      rcases Nat.lt_or_ge w w2 with hlt | hge
      · exact hlt
      · have := cntS_mono P win usb sreq (IsRet P y) e0 w2 w hge
        omega
    have hs1 := ts_ge_after_wbS P win usb sreq y e0 w w2 hww2 (isWB_of_ret P y _ hwb)
    have hs2 := ts_ge_after_wbS P win usb sreq y e0 w2 t hw2t (isWB_of_ret P y _ hw2b)
    omega

end

end JLane
