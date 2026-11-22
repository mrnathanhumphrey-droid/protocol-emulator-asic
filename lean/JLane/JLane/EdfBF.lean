import JLane.PrioRespF
import JLane.EdfB
/-!
# Brick F9 — the USB lane's priority on the flush run (the usbdev `hpri`)

`EdfB.hpri_b` derives `prio_resp`'s priority premise from (b′), the EDF contract and the deadline
margin, on `run`; `prio_respT` (the usbdev USB lane on the flush run) still took it as a premise.
Here it is derived on `runF` and lifted to `run3T` (Wilson 11-21, usbdev ruling). The one step
of `hpri_b` that reads a timestamp — the winner's release held from its decision to its
writeback (`dec_ts`) — holds on `runF` because a lane being dispatched is never flushed
(`dec_tsF1`, from `ArmFTClose.hmid_run` for every lane).
-/
namespace JLane

/-- A decision at `D` is written back at `D + 2` with the same release, along `runF`, for a
lane the run does not flush while it is being dispatched. -/
theorem dec_tsF1 (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool)
    (X0 : EngineF) (D : Nat) (y : Lane) (h : Dec win y (runF P win fl D X0).e)
    (hm0 : fl (runF P win fl D X0).e.now y = true →
      ¬((runF P win fl (D + 1) X0).e.st ≠ .idle ∧ (runF P win fl (D + 1) X0).e.cur = y))
    (hm1 : fl (runF P win fl (D + 1) X0).e.now y = true →
      ¬((runF P win fl (D + 1 + 1) X0).e.st ≠ .idle ∧ (runF P win fl (D + 1 + 1) X0).e.cur = y)) :
    (runF P win fl (D + 2) X0).e.ts y = (runF P win fl D X0).e.ts y ∧
    (runF P win fl (D + 2) X0).e.now = (runF P win fl D X0).e.now + 2 := by
  have hd1 : (runF P win fl (D + 1) X0).e.st = .drive ∧ (runF P win fl (D + 1) X0).e.cur = y := by
    rw [runF_succ']
    exact step_of_dec P win _ y h
  have hd2 := dec_wbF P win fl X0 D y h
  have nf0 : fl (runF P win fl D X0).e.now y = false := by
    cases hf : fl (runF P win fl D X0).e.now y with
    | false => rfl
    | true => exact absurd ⟨by rw [hd1.1]; decide, hd1.2⟩ (hm0 hf)
  have nf1 : fl (runF P win fl (D + 1) X0).e.now y = false := by
    cases hf : fl (runF P win fl (D + 1) X0).e.now y with
    | false => rfl
    | true => exact absurd ⟨by rw [hd2.1]; decide, hd2.2⟩ (hm1 hf)
  have hidle : (runF P win fl D X0).e.st = .idle := h.1
  have t1 := ts_flatF1 P win fl y X0 D nf0 (not_wb_of_st y _ (by rw [hidle]; decide))
  have t2 := ts_flatF1 P win fl y X0 (D + 1) nf1 (not_wb_of_st y _ (by rw [hd1.1]; decide))
  have n1 := now_runF P win fl D X0
  have n2 := now_runF P win fl (D + 1 + 1) X0
  constructor
  · show (runF P win fl (D + 1 + 1) X0).e.ts y = _
    rw [t2, t1]
  · show (runF P win fl (D + 1 + 1) X0).e.now = _
    omega

/-- **`hpri`, derived on the flush run.** -/
theorem hpri_bF (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool)
    (X0 : EngineF) (u : Lane) (ds R : Lane → Nat) (T : Nat) (hb : BPrimeWin win)
    (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
    (hws : ∀ e, e.st = .idle → Ready P u e → e.headValid u = true → win e ≠ none)
    (hedf : EdfBeatsB P ds win u)
    (hmargin : ∀ z, P.live z = true → z ≠ u → ds u + R z ≤ ds z)
    (hR : ∀ x, x < T → ∀ z, P.live z = true → IsWB z (runF P win fl x X0).e →
      (runF P win fl x X0).e.now ≤ (runF P win fl x X0).e.ts z + R z + 2)
    (hmidA : ∀ n l, fl (runF P win fl n X0).e.now l = true →
      ¬((runF P win fl (n + 1) X0).e.st ≠ .idle ∧ (runF P win fl (n + 1) X0).e.cur = l)) :
    ∀ t, t + 2 < T → (runF P win fl t X0).e.st = .idle → Ready P u (runF P win fl t X0).e →
      (runF P win fl t X0).e.headValid u = true → win (runF P win fl t X0).e = some u := by
  intro t ht hid hr hv
  cases hw : win (runF P win fl t X0).e with
  | none => exact absurd hw (hws _ hid hr hv)
  | some w =>
    by_cases hwu : w = u
    · rw [hwu]
    · exfalso
      have hbeat := hedf _ w hw hwu hr hv
      have hlw := (hwin _ w hw).1
      have hm := hmargin w hlw hwu
      have hru := hr.2
      -- under (b') w is decided now, so it writes back at t + 2 within its bound
      have hdec : Dec win w (runF P win fl t X0).e := ⟨hid, hw, hb _ w hw⟩
      have hwb := dec_wbF P win fl X0 t w hdec
      have hRw := hR (t + 2) ht w hlw hwb
      obtain ⟨hts2, hnow2⟩ := dec_tsF1 P win fl X0 t w hdec (hmidA t w) (hmidA (t + 1) w)
      rw [hts2, hnow2] at hRw
      omega

/-- **The USB lane's response on the flush run under (b′) and EDF**: `prio_respF` with the
priority derived (`hpri_bF`). -/
theorem prio_resp_edfF (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool)
    (X0 : EngineF) (h0 : X0.e.st = .idle) (u : Lane) (h0u : X0.e.now ≤ X0.e.ts u)
    (hu : P.live u = true) (ds R : Lane → Nat) (L T : Nat) (hb : BPrimeWin win)
    (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
    (hws : ∀ e, e.st = .idle → Ready P u e → e.headValid u = true → win e ≠ none)
    (hedf : EdfBeatsB P ds win u)
    (hmargin : ∀ z, P.live z = true → z ≠ u → ds u + R z ≤ ds z)
    (hR : ∀ x, x < T → ∀ z, P.live z = true → IsWB z (runF P win fl x X0).e →
      (runF P win fl x X0).e.now ≤ (runF P win fl x X0).e.ts z + R z + 2)
    (hfl : ∀ n, fl (runF P win fl n X0).e.now u = true →
      (runF P win fl n X0).e.ts u ≤ (runF P win fl n X0).e.now + 1)
    (hmidA : ∀ n l, fl (runF P win fl n X0).e.now l = true →
      ¬((runF P win fl (n + 1) X0).e.st ≠ .idle ∧ (runF P win fl (n + 1) X0).e.cur = l))
    (t : Nat) (htT : t + 2 ≤ T) (hwb : IsWB u (runF P win fl t X0).e)
    (hfree : ∀ w, w + 2 < t → IsWB u (runF P win fl w X0).e →
      (runF P win fl w X0).e.now < (runF P win fl t X0).e.ts u)
    (hhv : ∀ c, c < t → (runF P win fl c X0).e.ts u = (runF P win fl t X0).e.ts u →
      (runF P win fl t X0).e.ts u + L ≤ (runF P win fl c X0).e.now →
      (runF P win fl c X0).e.headValid u = true) :
    (runF P win fl t X0).e.now ≤ (runF P win fl t X0).e.ts u + L + 4 :=
  prio_respF P win fl X0 h0 u h0u hu L t hfl (fun n h => hmidA n u h)
    (fun s hs hid hr hv =>
      hpri_bF P win fl X0 u ds R T hb hwin hws hedf hmargin hR hmidA s (by omega) hid hr hv)
    hwb hfree hhv

section
variable (P2 : Program2) (Wn : Nat) (fw : Engine2 → Word) (edge : Nat → Lane → Nat)
  (hedge : ∀ t l, t + 1 ≤ edge t l) (sched : EngineT → Option Lane) (X0 : EngineT)
  (hX0 : InvT Wn X0) (hf : ∀ y, ArmFragT Wn (fw y)) (hsw : SchedT sched)

include hedge hX0 hf hsw in
/-- **The USB lane's response on the FALLTHROUGH engine under (b′) and EDF** (the usbdev USB
lane): `prio_respT` with `hpri` derived; the flush conditions discharged as there. -/
theorem prio_resp_edfT (h0 : X0.x.e.st = .idle) (u : Lane) (h0u : X0.x.e.now ≤ relT X0 u)
    (hu : (armPT P2 fw edge sched X0).live u = true) (ds R : Lane → Nat) (L T : Nat)
    (hb : BPrimeWin (winT P2 fw edge sched X0))
    (hwin : ∀ e w, winT P2 fw edge sched X0 e = some w →
      (armPT P2 fw edge sched X0).live w = true ∧ e.ts w ≤ e.now)
    (hws : ∀ e, e.st = .idle → Ready (armPT P2 fw edge sched X0) u e → e.headValid u = true →
      winT P2 fw edge sched X0 e ≠ none)
    (hedf : EdfBeatsB (armPT P2 fw edge sched X0) ds (winT P2 fw edge sched X0) u)
    (hmargin : ∀ z, (armPT P2 fw edge sched X0).live z = true → z ≠ u → ds u + R z ≤ ds z)
    (hR : ∀ x, x < T → ∀ z, (armPT P2 fw edge sched X0).live z = true →
      IsWB z (πT (run3T P2 fw edge sched x X0)) →
      (run3T P2 fw edge sched x X0).x.e.now ≤ relT (run3T P2 fw edge sched x X0) z + R z + 2)
    (t : Nat) (htT : t + 2 ≤ T)
    (hwb : IsWB u (πT (run3T P2 fw edge sched t X0)))
    (hfree : ∀ w, w + 2 < t → IsWB u (πT (run3T P2 fw edge sched w X0)) →
      (run3T P2 fw edge sched w X0).x.e.now < relT (run3T P2 fw edge sched t X0) u)
    (hhv : ∀ c, c < t → relT (run3T P2 fw edge sched c X0) u = relT (run3T P2 fw edge sched t X0) u →
      relT (run3T P2 fw edge sched t X0) u + L ≤ (run3T P2 fw edge sched c X0).x.e.now →
      (run3T P2 fw edge sched c X0).x.e.headValid u = true) :
    (run3T P2 fw edge sched t X0).x.e.now ≤ relT (run3T P2 fw edge sched t X0) u + L + 4 := by
  have hE := runF_e P2 Wn fw edge hedge sched X0 hX0 hf hsw
  have key := prio_resp_edfF (armPT P2 fw edge sched X0) (winT P2 fw edge sched X0)
    (flR P2 fw edge sched X0) (πF X0) h0 u h0u hu ds R L T hb hwin hws hedf hmargin
    (fun x hx z hz hw => by
      rw [hE] at hw ⊢
      exact hR x hx z hz hw)
    (fun n h => by
      rw [hE] at h ⊢
      change flR P2 fw edge sched X0 (run3T P2 fw edge sched n X0).x.e.now u = true at h
      rw [flR_at] at h
      exact relT_le_fl _ u h)
    (fun n l h => by
      have hm := hmid_run P2 Wn fw edge hedge sched X0 hX0 hf hsw n l h
      rw [runF_succ']
      exact hm)
    t htT
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
