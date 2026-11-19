import JLane.GapRunT
import JLane.GapRun
/-!
# Brick C3c — the per-retirement certificate on the buffered engine
(`slot_on_composition`, step 2: `hZC` charging)

`GapRun.pending_bound_gap` and `GapRun.head_late_gap` restated on `BufEng.runB` (the slot and the
depth-2 buffer), with no-prefetch words allowed (`NpfB`) and per-retirement gaps -- the
certificate `branch_budget` evaluates with the slot on. Every link between consecutive
retirements is charged `D* + B` (`hZC`): a slot fetch is the lane's own capture (`Hit y`), so it
is one of the captures the count already takes, and `D* + B` bounds the wait for any of them.
The tighter charge for a slot-served link (fill time + contention, `hZS`) comes last, as its own
entry.

The proof is GapRun's, case for case: the fresh case reads the lane's word count from BufEng's
conservation (`held_run`: held + retirements = 2 + captures) -- a lane holding at most one word
has an empty buffer and owes a slot (`held_le_one`) -- and either wants (the masked port's wait,
`window_leB` / `window_le_19B`) or holds a no-prefetch head until its next retirement
(`npf_holdB`, `npf_unlockB`).

Flushes are not in this run (`runB`); step 3 threads them, with a discard term in the count.
-/
namespace JLane

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane)

/-! ### Release gaps along `runB` -/

/-- The release gap a writeback of `y` at cycle `x` opens. -/
def gpB (y : Lane) (x0 : EngB) (x : Nat) : Nat :=
  P.dly y + P.ext (runB P win usb sreq x x0).e.now y

/-- How far `y`'s release moved from `x` to `x2`. -/
def rdB (y : Lane) (x0 : EngB) (x x2 : Nat) : Nat :=
  (runB P win usb sreq x2 x0).e.ts y - (runB P win usb sreq x x0).e.ts y

/-- Consecutive retirements of `y` along `runB`. -/
def ConsecB (y : Lane) (x0 : EngB) (x x2 : Nat) : Prop :=
  x < x2 ∧ IsRet P y (runB P win usb sreq x x0).e ∧ IsRet P y (runB P win usb sreq x2 x0).e ∧
    cntB P win usb sreq (fun z => IsRet P y z.e) x2 x0
      = cntB P win usb sreq (fun z => IsRet P y z.e) x x0 + 1

theorem ts_monoB (y : Lane) (x0 : EngB) (m n : Nat) (h : m ≤ n) :
    (runB P win usb sreq m x0).e.ts y ≤ (runB P win usb sreq n x0).e.ts y := by
  have h1 := ts_run_geB P win usb sreq y (n - m) (runB P win usb sreq m x0)
  rw [← runB_add] at h1
  have hmn : m + (n - m) = n := by omega
  rw [hmn] at h1
  omega

theorem ts_after_wbB (y : Lane) (x0 : EngB) (t : Nat) (h : IsWB y (runB P win usb sreq t x0).e) :
    (runB P win usb sreq (t + 1) x0).e.ts y
      = (runB P win usb sreq t x0).e.ts y + P.dly y + P.ext (runB P win usb sreq t x0).e.now y := by
  rw [runB_succ']
  show (step P win (runB P win usb sreq t x0).e).ts y = _
  rw [ts_step, if_pos h, Nat.add_assoc]

theorem ts_gapB (y : Lane) (x0 : EngB) (x z : Nat) (hw : IsWB y (runB P win usb sreq x x0).e)
    (hxz : x < z) :
    (runB P win usb sreq x x0).e.ts y + gpB P win usb sreq y x0 x
      ≤ (runB P win usb sreq z x0).e.ts y := by
  have h1 := ts_after_wbB P win usb sreq y x0 x hw
  have h2 := ts_monoB P win usb sreq y x0 (x + 1) z (by omega)
  unfold gpB
  omega

theorem rdB_eq (y : Lane) (x0 : EngB) (x x2 : Nat) (h : x ≤ x2) :
    (runB P win usb sreq x x0).e.ts y + rdB P win usb sreq y x0 x x2
      = (runB P win usb sreq x2 x0).e.ts y := by
  have := ts_monoB P win usb sreq y x0 x x2 h
  unfold rdB
  omega

/-! ### The deferred case -/

/-- From a cycle `s` where `y` owes, does not want and has an empty buffer, with no capture for
`y` until `t` and no retirement until `w2`: the word retiring at `w2` is no-prefetch, and `t` is
within one port wait of that retirement. -/
theorem pb_defer_gB (hok : SReqB P sreq) (y : Lane) (x0 : EngB) (B T : Nat) (Rr : Nat → Nat)
    (s w2 t : Nat) (hy : P.live y = true) (hW : WfB x0)
    (hRw : (runB P win usb sreq w2 x0).e.now ≤ (runB P win usb sreq w2 x0).e.ts y + Rr w2 + 2)
    (hB : ∀ a m, a + m ≤ T → m ≤ 23 + B →
      chargeSumB P win usb sreq y m (runB P win usb sreq a x0) ≤ B)
    (hs : s ≤ w2) (hw2t : w2 < t) (htT : t ≤ T)
    (ho : 1 ≤ (runB P win usb sreq s x0).e.owed y)
    (hw : (runB P win usb sreq s x0).e.wantFetch y = false)
    (hb : (runB P win usb sreq s x0).buf y = false)
    (hr2 : IsRet P y (runB P win usb sreq w2 x0).e)
    (hnr : cntB P win usb sreq (fun z => IsRet P y z.e) s x0
      = cntB P win usb sreq (fun z => IsRet P y z.e) w2 x0)
    (hnh : cntB P win usb sreq (fun z => Hit y z.e) s x0
      = cntB P win usb sreq (fun z => Hit y z.e) t x0) :
    NpfAt y (runB P win usb sreq w2 x0).e ∧
      x0.e.now + t ≤ (runB P win usb sreq w2 x0).e.ts y + Rr w2 + PENDING_SLACK + B := by
  have hPS : PENDING_SLACK = 25 := pending_slack_val
  have hold := npf_holdB P win usb sreq y x0 s ho hw hb (w2 - s) (fun i hi =>
    ⟨no_event_betweenB P win usb sreq (fun z => Hit y z.e) x0 s t (s + i) (by omega) (by omega) hnh,
     not_ret_form P y _
       (no_event_betweenB P win usb sreq (fun z => IsRet P y z.e) x0 s w2 (s + i) (by omega)
         (by omega) hnr)⟩)
  have hsw : s + (w2 - s) = w2 := by omega
  rw [hsw] at hold
  obtain ⟨hho, hhw, hhb⟩ := hold
  have hnh2 : ¬Hit y (runB P win usb sreq w2 x0).e :=
    no_event_betweenB P win usb sreq (fun z => Hit y z.e) x0 s t w2 hs hw2t hnh
  obtain ⟨hwant, hbuf, hnpf⟩ := npf_unlockB P win usb sreq (runB P win usb sreq w2 x0) y hho hhw
    hnh2 hhb (ret_form P y _ hr2)
  refine ⟨hnpf, ?_⟩
  have hwant' : (runB P win usb sreq (w2 + 1) x0).e.wantFetch y = true := by
    rw [runB_succ']
    exact hwant
  have hbuf' : (runB P win usb sreq (w2 + 1) x0).buf y = false := by
    rw [runB_succ']
    exact hbuf
  have hm1 := cntB_mono P win usb sreq (fun z => Hit y z.e) x0 s (w2 + 1) (by omega)
  have hm2 := cntB_mono P win usb sreq (fun z => Hit y z.e) x0 (w2 + 1) t (by omega)
  have hn := window_leB P win usb sreq hok y hy (runB P win usb sreq (w2 + 1) x0) B (t - (w2 + 1))
    (wfB_run P win usb sreq hok (w2 + 1) x0 hW) hwant' hbuf'
    (fun m hm hm' => hB (w2 + 1) m (by omega) hm')
    (fun i hi => by
      rw [← runB_add]
      exact no_event_betweenB P win usb sreq (fun z => Hit y z.e) x0 (w2 + 1) t (w2 + 1 + i)
        (by omega) (by omega) (by omega))
  have hnow := now_runB P win usb sreq w2 x0
  omega

/-! ### `runB` is a trajectory (`TrajB`): the conversions -/

theorem agree_refl (y : Lane) (a : EngB) : AgreeY y a a :=
  ⟨rfl, rfl, rfl, rfl, rfl, rfl, fun _ => rfl, fun _ => rfl, rfl⟩

theorem trajY_runB (y : Lane) (x0 : EngB) (T : Nat) :
    TrajY P win usb sreq y (fun n => runB P win usb sreq n x0) T := fun n _ => by
  show AgreeY y (runB P win usb sreq (n + 1) x0) (stepB P win usb sreq (runB P win usb sreq n x0))
  rw [runB_succ']
  exact agree_refl y _

theorem cntT_runB (x0 : EngB) (Q : EngB → Prop) [DecidablePred Q] :
    ∀ n, cntT (fun n => runB P win usb sreq n x0) Q n = cntB P win usb sreq Q n x0
  | 0 => rfl
  | n + 1 => by
    rw [cntT_succ, cntT_runB x0 Q n, cntB_succ_back]

theorem chargeSumT_runB (y : Lane) (x0 : EngB) :
    ∀ m a, chargeSumT P usb sreq y (fun n => runB P win usb sreq n x0) a m
      = chargeSumB P win usb sreq y m (runB P win usb sreq a x0)
  | 0, _ => rfl
  | m + 1, a => by
    show chargeB P usb sreq y (runB P win usb sreq a x0)
        + chargeSumT P usb sreq y (fun n => runB P win usb sreq n x0) (a + 1) m
      = chargeB P usb sreq y (runB P win usb sreq a x0)
        + chargeSumB P win usb sreq y m (stepB P win usb sreq (runB P win usb sreq a x0))
    rw [chargeSumT_runB y x0 m (a + 1), runB_succ']

/-! ### The pending bound: `GapRunT.pending_bound_gapT` along `runB`, from both slots full -/

/-- **The pending bound with per-retirement gaps, on the buffered engine.** Refill `#k` of lane
`y`, owed from retirement `#k` at `w`, still pending at `t` after retirement `#(k+1)` at `w2`:
deferred past a no-prefetch head (bound against `w2`), or within the certificate `Z w`. -/
theorem pending_bound_gapB (hok : SReqB P sreq) (y : Lane) (x0 : EngB) (B T : Nat)
    (Rr Z : Nat → Nat) (hy : P.live y = true) (hW : WfB x0) (h0 : x0.held y = 2)
    (hR : ∀ x, x < T → IsRet P y (runB P win usb sreq x x0).e →
      (runB P win usb sreq x x0).e.now ≤ (runB P win usb sreq x x0).e.ts y + Rr x + 2)
    (hB : ∀ a m, a + m ≤ T → m ≤ 23 + B →
      chargeSumB P win usb sreq y m (runB P win usb sreq a x0) ≤ B)
    (hZ0 : ∀ x, x < T → IsRet P y (runB P win usb sreq x x0).e → Rr x ≤ Z x)
    (hZF : ∀ x, x < T → IsRet P y (runB P win usb sreq x x0).e →
      NpfAt y (runB P win usb sreq x x0).e → Rr x + DSTAR + B ≤ Z x)
    (hZC : ∀ x x2, x2 < T → ConsecB P win usb sreq y x0 x x2 →
      Z x + DSTAR + B ≤ rdB P win usb sreq y x0 x x2 + Z x2) :
    ∀ (k t w w2 : Nat), t ≤ T → w < w2 → w2 < t →
      cntB P win usb sreq (fun z => IsRet P y z.e) w x0 = k →
      IsRet P y (runB P win usb sreq w x0).e →
      cntB P win usb sreq (fun z => IsRet P y z.e) w2 x0 = k + 1 →
      IsRet P y (runB P win usb sreq w2 x0).e →
      cntB P win usb sreq (fun z => Hit y z.e) t x0 ≤ k →
      (NpfAt y (runB P win usb sreq w2 x0).e ∧
        x0.e.now + t ≤ (runB P win usb sreq w2 x0).e.ts y + Rr w2 + PENDING_SLACK + B) ∨
      x0.e.now + t ≤ (runB P win usb sreq w x0).e.ts y + Z w + PENDING_SLACK + B := by
  intro k t w w2 htT hww2 hw2t hwk hwb hw2k hw2b hh
  have hc := cntT_runB P win usb sreq x0 (fun z => IsRet P y z.e)
  have hh' := cntT_runB P win usb sreq x0 (fun z => Hit y z.e)
  exact pending_bound_gapT P win usb sreq y (fun n => runB P win usb sreq n x0) hok hy T
    (trajY_runB P win usb sreq y x0 T) (fun n _ => wfB_run P win usb sreq hok n x0 hW) B Rr Z
    (Or.inr h0) hR
    (fun a m h1 h2 => by rw [chargeSumT_runB]; exact hB a m h1 h2) hZ0 hZF
    (fun x x2 h hcs => hZC x x2 h ⟨hcs.1, hcs.2.1, hcs.2.2.1, by
      have := hcs.2.2.2; rw [hc, hc] at this; exact this⟩)
    (fun w0 _ _ _ h1 => by exfalso; have : x0.held y = 1 := h1; omega)
    k t w w2 htT hww2 hw2t (by rw [hc]; exact hwk) hwb (by rw [hc]; exact hw2k) hw2b
    (by rw [hh']; show _ + x0.held y ≤ _; omega)

/-! ### The head: `GapRunT.head_late_gapT` along `runB`, from both slots full -/

/-- **Head valid, per-retirement gaps and lateness, on the buffered engine.** At `t ≤ T`, if
the word released after the latest retirement `x` has waited its allowance `L x` past its
release, `y`'s head is valid. Conditions as `GapRun.head_late_gap`:
`Rr x + 26 + B ≤ gp x + L x` at a no-prefetch retirement, `Z x + 26 + B ≤ gp x + gp x2 + L x2`
for consecutive retirements, and the certificate (`hZ0`, `hZF`, `hZC`). -/
theorem head_late_gapB (hok : SReqB P sreq) (y : Lane) (x0 : EngB) (B T : Nat)
    (Rr Z L : Nat → Nat) (hW : WfB x0) (h0 : x0.held y = 2) (hy : P.live y = true)
    (hR : ∀ x, x < T → IsRet P y (runB P win usb sreq x x0).e →
      (runB P win usb sreq x x0).e.now ≤ (runB P win usb sreq x x0).e.ts y + Rr x + 2)
    (hB : ∀ a m, a + m ≤ T → m ≤ 23 + B →
      chargeSumB P win usb sreq y m (runB P win usb sreq a x0) ≤ B)
    (hZ0 : ∀ x, x < T → IsRet P y (runB P win usb sreq x x0).e → Rr x ≤ Z x)
    (hZF : ∀ x, x < T → IsRet P y (runB P win usb sreq x x0).e →
      NpfAt y (runB P win usb sreq x x0).e → Rr x + DSTAR + B ≤ Z x)
    (hZC : ∀ x x2, x2 < T → ConsecB P win usb sreq y x0 x x2 →
      Z x + DSTAR + B ≤ rdB P win usb sreq y x0 x x2 + Z x2)
    (hHD : ∀ x, x < T → IsRet P y (runB P win usb sreq x x0).e →
      NpfAt y (runB P win usb sreq x x0).e →
      Rr x + HEAD_SLACK + B ≤ gpB P win usb sreq y x0 x + L x)
    (hHN : ∀ x x2, x2 < T → ConsecB P win usb sreq y x0 x x2 →
      Z x + HEAD_SLACK + B ≤ rdB P win usb sreq y x0 x x2 + gpB P win usb sreq y x0 x2 + L x2)
    (t : Nat) (htT : t ≤ T)
    (hlate : ∀ x, x < t → IsRet P y (runB P win usb sreq x x0).e →
      cntB P win usb sreq (fun z => IsRet P y z.e) (x + 1) x0
        = cntB P win usb sreq (fun z => IsRet P y z.e) t x0 →
      (runB P win usb sreq t x0).e.ts y + L x ≤ (runB P win usb sreq t x0).e.now) :
    (runB P win usb sreq t x0).e.headValid y = true := by
  have hc := cntT_runB P win usb sreq x0 (fun z => IsRet P y z.e)
  have hconsec : ∀ x x2, ConsecT P y (fun n => runB P win usb sreq n x0) x x2 →
      ConsecB P win usb sreq y x0 x x2 := fun x x2 hcs =>
    ⟨hcs.1, hcs.2.1, hcs.2.2.1, by have := hcs.2.2.2; rw [hc, hc] at this; exact this⟩
  exact head_late_gapT P win usb sreq y (fun n => runB P win usb sreq n x0) hok hy T
    (trajY_runB P win usb sreq y x0 T) (fun n _ => wfB_run P win usb sreq hok n x0 hW) B Rr Z L
    (Or.inr h0) hR
    (fun a m h1 h2 => by rw [chargeSumT_runB]; exact hB a m h1 h2) hZ0 hZF
    (fun x x2 h hcs => hZC x x2 h (hconsec x x2 hcs))
    (fun w0 _ _ _ h1 => by exfalso; have : x0.held y = 1 := h1; omega)
    hHD (fun x x2 h hcs => hHN x x2 h (hconsec x x2 hcs))
    (fun w0 _ _ _ h1 => by exfalso; have : x0.held y = 1 := h1; omega)
    t htT (fun x hx hr he => hlate x hx hr (by rw [hc, hc] at he; exact he))

end

#print axioms ts_monoB
#print axioms pb_defer_gB
#print axioms pending_bound_gapB
#print axioms head_late_gapB

end JLane
