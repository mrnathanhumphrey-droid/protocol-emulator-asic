import JLane.StRetire
/-!
# Brick E — the USB deadline margin, derived (Wilson 11-13)

The deadline rule (Wilson 11-08, `pe_isa.usb_problems`) promises the USB receive sample a
dispatch wait `J ≤ 2`. Its argument compared **relative** `D_sched`; the RTL's EDF key is the
**absolute** deadline `ts + D_sched` (`pe_engine.v` l.26, `key_q <= l_timestamp + l_d - now`
l.2682), ties to the lowest index (the argmin tree's strict `<`, l.1728), and the USB lane is
lane 0. Measured 11-13: with the other lanes' `D_sched` only 1 above the USB lane's, samples
waited up to 10 cycles and bytes decoded wrong.

Here the margin is **derived**: if every other live lane's `D_sched` is at least
`USB_DEADLINE_MARGIN = R_USB = 17` above the USB lane's, a lane that beats the ready USB lane
would have to be ready for more than `R_USB` cycles, which `wb_bound_usb` forbids. So
* `usb_wins`: at every idle cycle where the USB lane is ready, it is the winner;
* `usb_j2`: a ready USB lane not in its own dispatch is decided within 2 cycles (`J ≤ 2`).

The EDF contract enters as the hypothesis `EdfBeats` (the winner model stays abstract, as in
`Step.lean`). Sufficient, worst case; the 11-13 measurement found `J ≤ 2` from margin 9 on one
periodic configuration.
-/
namespace JLane

/-- The margin the USB lane's `D_sched` needs below every other live lane's. -/
abbrev USB_DEADLINE_MARGIN : Nat := R_USB

theorem usb_deadline_margin_val : USB_DEADLINE_MARGIN = 17 := rfl

/-- **The RTL's EDF contract, against lane `u`.** Whenever `u` is ready and the winner is
another lane, that lane's absolute deadline `ts + D_sched` is strictly earlier (ties go to the
lowest index, and `u` is lane 0). -/
def EdfBeats (P : Program) (ds : Lane → Nat) (win : Engine → Option Lane) (u : Lane) : Prop :=
  ∀ e w, win e = some w → w ≠ u → Ready P u e → e.ts w + ds w < e.ts u + ds u

/-- One cycle: a lane not written back keeps its timestamp. -/
theorem ts_step_keep (P : Program) (win : Engine → Option Lane) (e : Engine) (u : Lane)
    (h : ¬(e.st = .wb ∧ u = e.cur)) : (step P win e).ts u = e.ts u := by
  show tsNext P e u = e.ts u
  unfold tsNext
  rw [if_neg h]

theorem step_wb_idle (P : Program) (win : Engine → Option Lane) (e : Engine) (h : e.st = .wb) :
    (step P win e).st = .idle := by
  show (dispNext win e).st = .idle
  simp [dispNext, h]

section
variable (P : Program) (win : Engine → Option Lane) (e0 : Engine) (u : Lane) (ds : Lane → Nat)
  (hW : Wf e0) (hfull : ∀ l s, P.live l = true → e0.actv l s = true)
  (hfn : ∀ e, P.fnpf e = false) (hn0 : e0.NoNpf)
  (h0 : e0.st = .idle) (h0ts : ∀ l, e0.now ≤ e0.ts l)
  (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
  (hws : ∀ y e, e.st = .idle → Ready P y e → win e ≠ none)
  (hdu : NOWB_MIN ≤ P.dly u)
  (hretu : RetSpaced P win e0 u DSTAR_RETIRE_USB)
  (hd : ∀ l, P.live l = true → l ≠ u → DSTAR_RETIRE_USB ≤ P.dly l)
  (hedf : EdfBeats P ds win u)
  (hmargin : ∀ z, P.live z = true → z ≠ u → ds u + USB_DEADLINE_MARGIN ≤ ds z)

include hW hfull hfn hn0 h0 h0ts hwin hws hdu hretu hd hedf hmargin in
/-- **The USB lane wins every idle cycle it is ready in**, given the margin. -/
theorem usb_wins :
    ∀ t, (run P win t e0).st = .idle → Ready P u (run P win t e0) →
      win (run P win t e0) = some u := by
  intro t hid hr
  have hNS := fun T => (dstar_usb P win e0 u hW hfull hfn hn0 h0 h0ts hwin hws hdu hretu hd T).1
  cases hw : win (run P win t e0) with
  | none => exact absurd hw (hws u _ hid hr)
  | some w =>
    by_cases hwu : w = u
    · rw [hwu]
    · exfalso
      have hb := hedf _ w hw hwu hr
      have hlw := (hwin _ w hw).1
      have hm := hmargin w hlw hwu
      have hru := hr.2
      -- w is decided now ...
      have hdec : Dec win w (run P win t e0) := ⟨hid, hw, hNS t hid w hw⟩
      -- ... so it was released at most R_USB ago
      have hwb := dec_wb P win e0 t w hdec
      have hR := wb_bound_usb P win e0 (t + 3) u h0 h0ts hwin hws hdu hd
        (fun t' _ => hNS t') (t + 2) (by omega) w hlw hwb
      obtain ⟨hts2, hnow2⟩ := dec_ts P win e0 t w hdec
      rw [hts2, hnow2] at hR
      have hRv : R_USB = 17 := rfl
      have hMv : USB_DEADLINE_MARGIN = 17 := rfl
      omega

include hW hfull hfn hn0 h0 h0ts hwin hws hdu hretu hd hedf hmargin in
/-- **`J ≤ 2` for the USB lane**: ready and not in its own dispatch at `t`, it is decided at
`t`, `t + 1` or `t + 2`. -/
theorem usb_j2 :
    ∀ t, Ready P u (run P win t e0) → NotMid u (run P win t e0) →
      ∃ j, j ≤ 2 ∧ Dec win u (run P win (t + j) e0) := by
  intro t hr hm
  have hNS := fun T => (dstar_usb P win e0 u hW hfull hfn hn0 h0 h0ts hwin hws hdu hretu hd T).1
  have hwins := usb_wins P win e0 u ds hW hfull hfn hn0 h0 h0ts hwin hws hdu hretu hd hedf hmargin
  have decAt : ∀ n, (run P win n e0).st = .idle → Ready P u (run P win n e0) →
      Dec win u (run P win n e0) := fun n hi hrn => by
    have hwn := hwins n hi hrn
    exact ⟨hi, hwn, hNS n hi u hwn⟩
  -- the lane stays ready while another lane's dispatch finishes
  have keep : ∀ n, (run P win n e0).cur ≠ u ∨ (run P win n e0).st ≠ .wb →
      Ready P u (run P win n e0) → Ready P u (run P win (n + 1) e0) := fun n hc hrn => by
    refine ⟨hrn.1, ?_⟩
    rw [run_succ', ts_step_keep P win _ u (fun h' => by
      rcases hc with hc | hc
      · exact hc h'.2.symm
      · exact hc h'.1)]
    have := hrn.2
    show _ ≤ (step P win (run P win n e0)).now
    show _ ≤ (run P win n e0).now + 1
    omega
  cases hs : (run P win t e0).st with
  | idle => exact ⟨0, by omega, decAt t hs hr⟩
  | wb =>
    have hcu : (run P win t e0).cur ≠ u := fun h' => hm ⟨by rw [hs]; decide, h'⟩
    have hi1 : (run P win (t + 1) e0).st = .idle := by
      rw [run_succ']
      exact step_wb_idle P win _ hs
    exact ⟨1, by omega, decAt (t + 1) hi1 (keep t (Or.inl hcu) hr)⟩
  | drive =>
    have hcu : (run P win t e0).cur ≠ u := fun h' => hm ⟨by rw [hs]; decide, h'⟩
    have hd1 := step_drive P win (run P win t e0) hs
    have hs1 : (run P win (t + 1) e0).st = .wb := by
      rw [run_succ']
      exact hd1.1
    have hc1 : (run P win (t + 1) e0).cur ≠ u := by
      rw [run_succ', hd1.2]
      exact hcu
    have hr1 := keep t (Or.inr (by rw [hs]; decide)) hr
    have hi2 : (run P win (t + 2) e0).st = .idle := by
      show (run P win ((t + 1) + 1) e0).st = .idle
      rw [run_succ']
      exact step_wb_idle P win _ hs1
    exact ⟨2, by omega, decAt (t + 2) hi2 (keep (t + 1) (Or.inl hc1) hr1)⟩

end

#print axioms usb_wins
#print axioms usb_j2

end JLane
