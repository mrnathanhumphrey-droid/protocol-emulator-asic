import JLane.BPrime
/-!
# Brick M — the USB lane's priority under (b′) and EDF (stage 5, `hpri`)

`PrioResp.prio_resp` assumed the USB lane wins whenever the dispatcher is idle and the lane is
released with a valid head. Here that is **derived**, as `EdfUsb.usb_wins` derived it for the
plain model, now on any run and under the ruled scheduler (b′):

* the RTL's EDF key is the absolute deadline `ts + D_sched`; under (b′) it is taken among
  lanes that can dispatch, so another winner `w` beats a ready, head-valid USB lane only with an
  earlier absolute deadline (`EdfBeatsB`);
* under (b′) the winner is decided at once, so its writeback two cycles later meets its own
  response bound `R w`: its release is at most `R w` before now;
* with the deadline margin `ds u + R z ≤ ds z` for every other live lane, no such `w` exists.

`prio_resp_edf` closes the USB lane's response: within `L + 4` of its release, from (b′), EDF,
the margin and the other lanes' response bounds (`wb_close_span`) — no priority assumption.
-/
namespace JLane

/-- The RTL's EDF contract under (b′), against lane `u`: when `u` is released with a valid head
and the winner is another lane, that lane's absolute deadline is strictly earlier. -/
def EdfBeatsB (P : Program) (ds : Lane → Nat) (win : Engine → Option Lane) (u : Lane) : Prop :=
  ∀ e w, win e = some w → w ≠ u → Ready P u e → e.headValid u = true →
    e.ts w + ds w < e.ts u + ds u

/-- **`hpri`, derived.** -/
theorem hpri_b (P : Program) (win : Engine → Option Lane) (e0 : Engine) (u : Lane)
    (ds R : Lane → Nat) (T : Nat) (hb : BPrimeWin win)
    (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
    (hws : ∀ e, e.st = .idle → Ready P u e → e.headValid u = true → win e ≠ none)
    (hedf : EdfBeatsB P ds win u)
    (hmargin : ∀ z, P.live z = true → z ≠ u → ds u + R z ≤ ds z)
    (hR : ∀ x, x < T → ∀ z, P.live z = true → IsWB z (run P win x e0) →
      (run P win x e0).now ≤ (run P win x e0).ts z + R z + 2) :
    ∀ t, t + 2 < T → (run P win t e0).st = .idle → Ready P u (run P win t e0) →
      (run P win t e0).headValid u = true → win (run P win t e0) = some u := by
  intro t ht hid hr hv
  cases hw : win (run P win t e0) with
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
      have hdec : Dec win w (run P win t e0) := ⟨hid, hw, hb _ w hw⟩
      have hwb := dec_wb P win e0 t w hdec
      have hRw := hR (t + 2) ht w hlw hwb
      obtain ⟨hts2, hnow2⟩ := dec_ts P win e0 t w hdec
      rw [hts2, hnow2] at hRw
      omega

/-- **The USB lane's response under (b′) and EDF.** Every writeback of `u` lands within `L + 4`
of its release (`prio_resp`), the priority now derived (`hpri_b`). -/
theorem prio_resp_edf (P : Program) (win : Engine → Option Lane) (e0 : Engine)
    (h0 : e0.st = .idle) (h0ts : ∀ l, e0.now ≤ e0.ts l) (u : Lane) (hu : P.live u = true)
    (ds R : Lane → Nat) (L T : Nat) (hb : BPrimeWin win)
    (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
    (hws : ∀ e, e.st = .idle → Ready P u e → e.headValid u = true → win e ≠ none)
    (hedf : EdfBeatsB P ds win u)
    (hmargin : ∀ z, P.live z = true → z ≠ u → ds u + R z ≤ ds z)
    (hR : ∀ x, x < T → ∀ z, P.live z = true → IsWB z (run P win x e0) →
      (run P win x e0).now ≤ (run P win x e0).ts z + R z + 2)
    (t : Nat) (htT : t + 2 ≤ T) (hwb : IsWB u (run P win t e0))
    (hfree : ∀ w, w + 2 < t → IsWB u (run P win w e0) →
      (run P win w e0).now < (run P win t e0).ts u)
    (hhv : ∀ c, c < t → (run P win c e0).ts u = (run P win t e0).ts u →
      (run P win t e0).ts u + L ≤ (run P win c e0).now → (run P win c e0).headValid u = true) :
    (run P win t e0).now ≤ (run P win t e0).ts u + L + 4 :=
  prio_resp P win e0 h0 h0ts u hu L t
    (fun s hs hid hr hv =>
      hpri_b P win e0 u ds R T hb hwin hws hedf hmargin hR s (by omega) hid hr hv)
    hwb hfree hhv

#print axioms hpri_b
#print axioms prio_resp_edf

end JLane
